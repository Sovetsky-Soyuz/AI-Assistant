from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    from langchain_unstructured import UnstructuredLoader as UnstructuredFileLoader
except ImportError:
    from langchain_community.document_loaders import UnstructuredFileLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_openai import OpenAIEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_MARKDOWN_SEPARATORS = [
    "\n#{1,6} ",
    "'''\n",
    "\n\\*\\*\\**\n",
    "\n---+\n",
    "\n___+\n",
    "\n\n",
    "\n",
    " ",
    "",
]

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".json", ".png", ".jpg", ".jpeg"}


class SpinnerTimer:
    def __init__(self, message: str = "Processing") -> None:
        self.message = message
        self.is_running = False
        self._thread: threading.Thread | None = None
        self.start_time: float = 0

    def _spin(self) -> None:
        while self.is_running:
            elapsed = time.time() - self.start_time
            sys.stdout.write(f"\r[...] {self.message}... ({elapsed:.1f}s)")
            sys.stdout.flush()
            time.sleep(0.1)

    def start(self) -> None:
        self.is_running = True
        self.start_time = time.time()
        self._thread = threading.Thread(target=self._spin)
        self._thread.start()

    def stop(self) -> float:
        self.is_running = False
        if self._thread:
            self._thread.join()
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
        return time.time() - self.start_time


def _file_hash(filepath: str) -> str:
    """Compute MD5 hash of a file for change detection."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _chunks_to_documents(chunks: list[dict[str, Any]]) -> list[Document]:
    """Convert stored chunk dicts into LangChain Document objects."""
    return [
        Document(page_content=c["text"], metadata=c.get("metadata", {}))
        for c in chunks
        if c.get("text", "").strip()
    ]


class KnowledgeService:
    """Handles both persistent knowledge_base and session-scoped document search.

    - Knowledge base: indexed from ``docs_dir`` on startup, cached in MongoDB.
    - Session docs: files attached in chat, parsed on upload, BM25 search
      (or hybrid if embeddings available).
    """

    def __init__(
        self,
        memory_store: Any,
        docs_dir: str | None = None,
        upload_dir: str | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.docs_dir = docs_dir
        self.upload_dir = upload_dir or ""
        self.embeddings: OpenAIEmbeddings | None = None
        self.kb_retriever: EnsembleRetriever | None = None
        self._session_retrievers: dict[str, Any] = {}
        self._lock = threading.Lock()

        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=200,
            add_start_index=True,
            strip_whitespace=True,
            separators=_MARKDOWN_SEPARATORS,
        )

        # Ensure upload directory exists
        if self.upload_dir:
            os.makedirs(self.upload_dir, exist_ok=True)

        # Initialize embeddings (LM Studio) -- only when docs_dir provided
        if self.docs_dir:
            try:
                self.embeddings = OpenAIEmbeddings(
                    base_url="http://127.0.0.1:1234/v1",
                    api_key="lm-studio",
                    model=os.getenv("EMBEDDING_MODEL", "text-embedding-bge-m3"),
                    check_embedding_ctx_length=False,
                )
                # Quick connectivity test
                self.embeddings.embed_query("test")
                print("[*] LM Studio embedding model connected.")
                print(f"[*] Embedding Model: {self.embeddings.model}")
            except Exception as exc:
                logger.warning("Could not connect to LM Studio embeddings: %s", exc)
                print(f"[!] LM Studio embedding unavailable: {exc}")
                self.embeddings = None

            self._initialize_knowledge_base()

    # ------------------------------------------------------------------
    # Knowledge base initialisation (startup)
    # ------------------------------------------------------------------

    def _initialize_knowledge_base(self) -> None:
        if not self.docs_dir:
            return

        if not os.path.exists(self.docs_dir):
            os.makedirs(self.docs_dir)
            print(f"[*] Created knowledge_base directory: {self.docs_dir}")
            return

        # 1. Get stored file hashes from MongoDB
        stored_hashes = self.memory_store.get_knowledge_file_hashes()

        # 2. Scan docs_dir for current files (only supported extensions)
        current_files: dict[str, str] = {}  # {relative_path: full_path}
        for root, _, files in os.walk(self.docs_dir):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, self.docs_dir)
                current_files[rel_path] = full_path

        if not current_files:
            print("[*] No documents found in knowledge_base folder.")
            return

        # 3. Determine new/changed/removed files
        new_or_changed: list[tuple[str, str]] = []  # (rel_path, full_path)
        for rel_path, full_path in current_files.items():
            file_h = _file_hash(full_path)
            if rel_path not in stored_hashes or stored_hashes[rel_path] != file_h:
                new_or_changed.append((rel_path, full_path))

        removed = set(stored_hashes.keys()) - set(current_files.keys())

        # 4. Remove chunks for deleted files
        for rel_path in removed:
            self.memory_store.delete_knowledge_file(rel_path)
            print(f"[*] Removed indexed data for deleted file: {rel_path}")

        # 5. Parse and index new/changed files
        if new_or_changed:
            print(f"[*] Indexing {len(new_or_changed)} new/changed file(s)...")
            timer = SpinnerTimer("Parsing and chunking documents")
            timer.start()

            for rel_path, full_path in new_or_changed:
                try:
                    loader = UnstructuredFileLoader(full_path)
                    docs = loader.load()
                    splits = self._text_splitter.split_documents(docs)
                    chunks = [
                        {
                            "text": s.page_content,
                            "metadata": {
                                "source": rel_path,
                                "start_index": s.metadata.get("start_index", 0),
                            },
                        }
                        for s in splits
                    ]
                    fh = _file_hash(full_path)
                    count = self.memory_store.store_knowledge_chunks(rel_path, fh, chunks)
                    print(f"    Indexed: {rel_path} ({count} chunks)")
                except Exception as exc:
                    logger.warning("Failed to index %s: %s", rel_path, exc)
                    print(f"    [!] Failed: {rel_path} -- {exc}")

            elapsed = timer.stop()
            print(f"[*] Indexing complete ({elapsed:.1f}s)")
        else:
            print(f"[*] All {len(current_files)} knowledge_base files already indexed in MongoDB.")

        # 6. Load all chunks from MongoDB and build retrievers
        all_chunks = self.memory_store.get_all_knowledge_chunks()
        if not all_chunks:
            print("[*] No knowledge chunks available.")
            return

        all_docs = _chunks_to_documents(all_chunks)
        self.kb_retriever = self._build_retriever(all_docs)

        if self.kb_retriever:
            print(f"[*] Knowledge Base ready: {len(all_docs)} chunks from {len(current_files)} file(s).")

    def _build_retriever(self, docs: list[Document]) -> EnsembleRetriever | None:
        """Build BM25 + optional FAISS hybrid retriever from Document list."""
        if not docs:
            return None

        bm25 = BM25Retriever.from_documents(docs)
        bm25.k = 5

        if self.embeddings:
            try:
                timer = SpinnerTimer("Building vector index (LM Studio)")
                timer.start()
                vectorstore = FAISS.from_documents(
                    documents=docs,
                    embedding=self.embeddings,
                    distance_strategy=DistanceStrategy.COSINE,
                )
                elapsed = timer.stop()
                print(f"[*] FAISS index built ({elapsed:.1f}s)")

                faiss_retriever = vectorstore.as_retriever(
                    search_type="mmr",
                    search_kwargs={"k": 5, "fetch_k": 20, "lambda_mult": 0.5},
                )
                return EnsembleRetriever(
                    retrievers=[bm25, faiss_retriever],
                    weights=[0.5, 0.5],
                )
            except Exception as exc:
                logger.warning("FAISS build failed, falling back to BM25: %s", exc)
                print(f"[!] FAISS failed ({exc}), using BM25-only search.")

        # Fallback: BM25-only retriever wrapped in EnsembleRetriever for uniform API
        return EnsembleRetriever(retrievers=[bm25], weights=[1.0])

    # ------------------------------------------------------------------
    # Knowledge base search
    # ------------------------------------------------------------------

    def search(self, query: str) -> dict[str, Any]:
        """Search the persistent knowledge_base."""
        if not self.kb_retriever:
            return {"error": "Knowledge base is not available. Enable RAG at startup."}

        print(f"\n[KB] Searching knowledge base for: '{query}'...")
        timer = SpinnerTimer("Reading and ranking chunks")
        timer.start()

        try:
            docs = self.kb_retriever.invoke(query)
            elapsed = timer.stop()

            if not docs:
                print(f"[KB] No relevant info found. ({elapsed:.1f}s)")
                return {"result": "No relevant local information found."}

            print(f"[KB] Retrieved {len(docs)} chunks ({elapsed:.1f}s)")
            context = "\n\n---\n\n".join(
                f"[Source: {doc.metadata.get('source', 'Unknown')}]\n{doc.page_content}"
                for doc in docs
            )
            return {"result": context}

        except Exception as exc:
            timer.stop()
            logger.error("Knowledge base search failed: %s", exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Session document indexing (file attachments in chat)
    # ------------------------------------------------------------------

    def index_session_file(
        self,
        session_id: str,
        attachment_id: str,
        file_path: str,
        filename: str,
    ) -> int:
        """Parse, chunk, and store a file for session-scoped search.
        Returns the number of chunks created."""
        try:
            loader = UnstructuredFileLoader(file_path)
            docs = loader.load()
            splits = self._text_splitter.split_documents(docs)
        except Exception as exc:
            logger.error("Failed to parse %s: %s", filename, exc)
            raise ValueError(f"Could not parse file '{filename}': {exc}") from exc

        chunks = [
            {
                "text": s.page_content,
                "metadata": {"source": filename, "start_index": s.metadata.get("start_index", 0)},
            }
            for s in splits
        ]

        count = self.memory_store.store_session_chunks(session_id, attachment_id, chunks)

        # Invalidate cached session retriever so it gets rebuilt on next search
        with self._lock:
            self._session_retrievers.pop(session_id, None)

        print(f"[Session] Indexed attachment '{filename}' for session {session_id[:8]}... ({count} chunks)")
        return count

    def search_session(self, session_id: str, query: str) -> dict[str, Any]:
        """Search within documents attached to a specific chat session."""
        retriever = self._get_session_retriever(session_id)
        if retriever is None:
            return {"error": "No documents attached to this chat session."}

        try:
            docs = retriever.invoke(query)
            if not docs:
                return {"result": "No relevant information found in attached documents."}

            context = "\n\n---\n\n".join(
                f"[Source: {doc.metadata.get('source', 'Unknown')}]\n{doc.page_content}"
                for doc in docs
            )
            return {"result": context}
        except Exception as exc:
            logger.error("Session doc search failed: %s", exc)
            return {"error": str(exc)}

    def _get_session_retriever(self, session_id: str) -> Any | None:
        """Lazily build/cache a BM25 retriever for session documents."""
        with self._lock:
            if session_id in self._session_retrievers:
                return self._session_retrievers[session_id]

        chunks = self.memory_store.get_session_chunks(session_id)
        if not chunks:
            return None

        docs = _chunks_to_documents(chunks)
        if not docs:
            return None

        bm25 = BM25Retriever.from_documents(docs)
        bm25.k = 5

        retriever: Any = bm25

        # If embeddings available, build hybrid retriever for session docs too
        if self.embeddings and len(docs) >= 3:
            try:
                vs = FAISS.from_documents(docs, self.embeddings, distance_strategy=DistanceStrategy.COSINE)
                faiss_ret = vs.as_retriever(search_type="mmr", search_kwargs={"k": 5, "fetch_k": 20, "lambda_mult": 0.5})
                retriever = EnsembleRetriever(retrievers=[bm25, faiss_ret], weights=[0.5, 0.5])
            except Exception:
                pass  # Fall back to BM25-only

        with self._lock:
            self._session_retrievers[session_id] = retriever
        return retriever

    def cleanup_session(self, session_id: str) -> None:
        """Remove cached retriever for a deleted session."""
        with self._lock:
            self._session_retrievers.pop(session_id, None)
