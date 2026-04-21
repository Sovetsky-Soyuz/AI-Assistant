"""Orbit Knowledge Base Builder

Standalone CLI tool to build, rebuild, or manage the knowledge database
in MongoDB. Run this anytime to pre-index documents before starting the
assistant server.

Usage:
    python build_knowledge_using_docling.py                         # Incremental update
    python build_knowledge_using_docling.py --rebuild               # Wipe + re-index all
    python build_knowledge_using_docling.py --clear                 # Wipe all chunks
    python build_knowledge_using_docling.py -d ./my_docs --verify   # Custom dir + test
    python build_knowledge_using_docling.py --dry-run               # Preview changes
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import get_settings
from backend.core.memory_store import MemoryStore

try:
    try:
        # from langchain_unstructured import UnstructuredLoader as UnstructuredFileLoader

        from docling.document_converter import DocumentConverter
        from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
        from langchain_core.documents import Document

    except ImportError:
        from langchain_community.document_loaders import UnstructuredFileLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.retrievers import BM25Retriever
    from langchain_core.documents import Document
except ImportError:
    print("ERROR: RAG dependencies not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

from backend.tools.knowledge import (
    SpinnerTimer,
    _file_hash,
    _MARKDOWN_SEPARATORS,
    _chunks_to_documents,
)

# -----------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".json"}
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


# -----------------------------------------------------------------------
# KnowledgeBuilder
# -----------------------------------------------------------------------

class KnowledgeBuilder:
    def __init__(self, memory_store: MemoryStore, docs_dir: str) -> None:
        self.memory_store = memory_store
        self.docs_dir = docs_dir

        self._md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "Header 1"),
                ("##", "Header 2"),
                ("###", "Header 3"),
                ("####", "Header 4"),
                ("#####", "Header 5"),
                ("######", "Header 6"),
                ("#######", "Header 7"),
                ("#########", "Header 8"),
                ("##########", "Header 9"),
                ("###########", "Header 10"),
            ]
        )

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            add_start_index=True,
            strip_whitespace=True,
            separators=_MARKDOWN_SEPARATORS,
        )

        self.doc_converter = DocumentConverter()

    # ----- Scan -----

    def scan_directory(self) -> dict[str, str]:
        """Walk docs_dir and return {relative_path: full_path} for supported files."""
        files: dict[str, str] = {}
        for root, _, filenames in os.walk(self.docs_dir):
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, self.docs_dir)
                files[rel_path] = full_path
        return files

    # ----- Diff -----

    def compute_diff(
        self, disk_files: dict[str, str]
    ) -> dict[str, list[str]]:
        """Compare disk files against MongoDB and classify them."""
        stored_hashes = self.memory_store.get_knowledge_file_hashes()
        new_files: list[str] = []
        changed_files: list[str] = []
        unchanged_files: list[str] = []

        for rel_path, full_path in disk_files.items():
            fh = _file_hash(full_path)
            if rel_path not in stored_hashes:
                new_files.append(rel_path)
            elif stored_hashes[rel_path] != fh:
                changed_files.append(rel_path)
            else:
                unchanged_files.append(rel_path)

        removed_files = list(set(stored_hashes.keys()) - set(disk_files.keys()))

        return {
            "new": new_files,
            "changed": changed_files,
            "unchanged": unchanged_files,
            "removed": removed_files,
        }

    # ----- Index -----

    def index_files(
        self, rel_paths: list[str], disk_files: dict[str, str]
    ) -> dict[str, Any]:
        """Parse, chunk, and store files using Docling. Returns stats dict."""
        stats = {"indexed": 0, "chunks": 0, "failed": 0, "failures": []}
        total = len(rel_paths)

        if total == 0:
            return stats

        timer = SpinnerTimer("Parsing and chunking documents")
        timer.start()

        for i, rel_path in enumerate(rel_paths, 1):
            full_path = disk_files[rel_path]
            try:
                # 1. Use Docling to read the file and convert it to Markdown with super accuracy.
                docling_result = self.doc_converter.convert(full_path)
                md_text = docling_result.document.export_to_markdown()

                # 2. Chunk the Markdown text using the Markdown header splitter and then the character splitter
                md_splits = self._md_splitter.split_text(md_text)
                splits = self._splitter.split_documents(md_splits)

                chunks = [
                    {
                        "text": s.page_content,
                        "metadata": {
                            "source": rel_path,
                            "start_index": s.metadata.get("start_index", 0),
                            # Can also store additional Header 1, Header 2 from s.metadata if desired
                        },
                    }
                    for s in splits
                ]
                fh = _file_hash(full_path)
                count = self.memory_store.store_knowledge_chunks(rel_path, fh, chunks)
                stats["indexed"] += 1
                stats["chunks"] += count
                timer.stop()
                print(f"  [{i}/{total}] Indexed: {rel_path} ({count} chunks)")
                if i < total:
                    timer = SpinnerTimer("Parsing and chunking documents")
                    timer.start()
            except Exception as exc:
                timer.stop()
                print(f"  [{i}/{total}] FAILED: {rel_path} -- {exc}")
                stats["failed"] += 1
                stats["failures"].append(rel_path)
                if i < total:
                    timer = SpinnerTimer("Parsing and chunking documents")
                    timer.start()

        return stats

    # ----- Remove stale -----

    def remove_stale(self, removed: list[str]) -> int:
        for rel_path in removed:
            self.memory_store.delete_knowledge_file(rel_path)
            print(f"  Removed stale: {rel_path}")
        return len(removed)

    # ----- Verify -----

    def verify(self, query: str) -> bool:
        """Build a BM25 retriever from MongoDB chunks and run a test query."""
        all_chunks = self.memory_store.get_all_knowledge_chunks()
        if not all_chunks:
            print("  No chunks in database -- nothing to verify.")
            return False

        docs = _chunks_to_documents(all_chunks)
        if not docs:
            print("  No valid documents from chunks.")
            return False

        print(f"  Building BM25 retriever from {len(docs)} chunks...")
        bm25 = BM25Retriever.from_documents(docs)
        bm25.k = 3

        results = bm25.invoke(query)
        if not results:
            print(f'  Query "{query}" returned 0 results.')
            return False

        print(f'  Query "{query}" returned {len(results)} result(s):')
        for j, doc in enumerate(results, 1):
            source = doc.metadata.get("source", "Unknown")
            preview = doc.page_content[:200].replace("\n", " ")
            print(f"    [{j}] Source: {source}")
            print(f"        {preview}...")
        return True

    # ----- Total chunk count -----

    def total_chunk_count(self) -> int:
        return len(self.memory_store.get_all_knowledge_chunks())


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_knowledge_using_docling",
        description="Orbit Knowledge Base Builder -- index local documents into MongoDB for RAG search.",
        epilog="After building, start the server with RAG enabled. It will load chunks from MongoDB instantly.",
    )
    parser.add_argument(
        "-d", "--docs-dir",
        type=str,
        default=None,
        help="Path to documents directory (default: knowledge_base/)",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-r", "--rebuild",
        action="store_true",
        help="Drop all existing chunks and re-index everything from scratch.",
    )
    mode_group.add_argument(
        "-c", "--clear",
        action="store_true",
        help="Delete all knowledge chunks from MongoDB and exit.",
    )

    parser.add_argument(
        "-v", "--verify",
        action="store_true",
        help="After indexing, run a test BM25 query to confirm the retriever works.",
    )
    parser.add_argument(
        "--verify-query",
        type=str,
        default="summary",
        help='Query string for --verify (default: "summary").',
    )
    parser.add_argument(
        "--mongodb-uri",
        type=str,
        default=None,
        help="Override MongoDB connection URI from .env.",
    )
    parser.add_argument(
        "--mongodb-db",
        type=str,
        default=None,
        help="Override MongoDB database name from .env.",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Scan and report what would change without writing to MongoDB.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Load settings from .env
    settings = get_settings()
    mongodb_uri = args.mongodb_uri or settings.mongodb_uri
    mongodb_db = args.mongodb_db or settings.mongodb_db

    # Resolve docs directory
    if args.docs_dir:
        docs_dir = os.path.abspath(args.docs_dir)
    elif settings.rag_docs_path:
        docs_dir = settings.rag_docs_path
    else:
        docs_dir = str(settings.root_dir / "knowledge_base")

    # Determine mode label
    if args.clear:
        mode_label = "Clear all chunks"
    elif args.rebuild:
        mode_label = "Full rebuild"
    elif args.dry_run:
        mode_label = "Dry run (preview)"
    else:
        mode_label = "Incremental update"

    # Banner
    print("=" * 54)
    print("  Orbit Knowledge Base Builder")
    print("=" * 54)
    print(f"  Docs directory:  {docs_dir}")
    print(f"  MongoDB:         {mongodb_uri} / {mongodb_db}")
    print(f"  Mode:            {mode_label}")
    print("=" * 54)
    print()

    # Connect to MongoDB
    try:
        memory_store = MemoryStore(mongodb_uri=mongodb_uri, db_name=mongodb_db)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    builder = KnowledgeBuilder(memory_store, docs_dir)
    start_time = time.time()

    # --- Clear mode ---
    if args.clear:
        count = memory_store.clear_all_knowledge_chunks()
        print(f"Cleared {count} knowledge chunk(s) from MongoDB.")
        memory_store.close()
        sys.exit(0)

    # --- Validate docs directory ---
    if not os.path.isdir(docs_dir):
        print(f"ERROR: Documents directory does not exist: {docs_dir}")
        print("Create it and add your files, then run this script again.")
        memory_store.close()
        sys.exit(1)

    # --- Scan ---
    print("[1/4] Scanning documents directory...")
    disk_files = builder.scan_directory()

    if not disk_files:
        print(f"  No supported files found in {docs_dir}")
        print(f"  Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        memory_store.close()
        sys.exit(0)

    print(f"  Found {len(disk_files)} supported file(s)")

    # --- Diff ---
    print("\n[2/4] Comparing with MongoDB...")

    if args.rebuild:
        # For rebuild, wipe first then treat everything as new
        count = memory_store.clear_all_knowledge_chunks()
        print(f"  Dropped {count} existing chunk(s)")
        diff = {"new": list(disk_files.keys()), "changed": [], "unchanged": [], "removed": []}
    else:
        diff = builder.compute_diff(disk_files)

    to_index = diff["new"] + diff["changed"]

    print(f"  New files:          {len(diff['new'])}")
    print(f"  Changed files:      {len(diff['changed'])}")
    print(f"  Unchanged (skip):   {len(diff['unchanged'])}")
    print(f"  Stale (to remove):  {len(diff['removed'])}")

    # --- Dry run ---
    if args.dry_run:
        if diff["new"]:
            print("\n  New files:")
            for f in diff["new"]:
                print(f"    + {f}")
        if diff["changed"]:
            print("\n  Changed files:")
            for f in diff["changed"]:
                print(f"    ~ {f}")
        if diff["removed"]:
            print("\n  Stale entries:")
            for f in diff["removed"]:
                print(f"    - {f}")
        print("\n  Dry run complete. No changes written.")
        memory_store.close()
        sys.exit(0)

    # --- Remove stale ---
    if diff["removed"]:
        print(f"\n[3/4] Removing {len(diff['removed'])} stale entry(ies)...")
        builder.remove_stale(diff["removed"])
    else:
        print("\n[3/4] No stale entries to remove.")

    # --- Index ---
    if to_index:
        print(f"\n[4/4] Indexing {len(to_index)} file(s)...")
        stats = builder.index_files(to_index, disk_files)
    else:
        print("\n[4/4] No files to index -- everything is up to date.")
        stats = {"indexed": 0, "chunks": 0, "failed": 0, "failures": []}

    elapsed = time.time() - start_time
    total_chunks = builder.total_chunk_count()

    # --- Summary ---
    print()
    print("=" * 54)
    print("  Knowledge Base Build Complete")
    print("=" * 54)
    print(f"  Total files on disk:     {len(disk_files)}")
    print(f"  Files indexed:           {stats['indexed']}")
    print(f"  Files skipped (same):    {len(diff['unchanged'])}")
    print(f"  Stale entries removed:   {len(diff['removed'])}")
    print(f"  Failed files:            {stats['failed']}")
    print(f"  Total chunks in DB:      {total_chunks}")
    print(f"  Time elapsed:            {elapsed:.1f}s")
    print("=" * 54)

    if stats["failures"]:
        print("\n  Failed files:")
        for f in stats["failures"]:
            print(f"    ! {f}")

    # --- Verify ---
    if args.verify:
        print(f'\n[Verify] Running test query: "{args.verify_query}"')
        ok = builder.verify(args.verify_query)
        print(f"  Retriever verification: {'PASS' if ok else 'FAIL'}")

    memory_store.close()

    exit_code = 1 if stats["failed"] > 0 else 0
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAborted by user.")
        sys.exit(130)
