"""Orbit Assistant - Wipe Database Utility

This is a standalone nuclear safety script to securely and permanently 
wipe all data from the Orbit Assistant MongoDB database.

It drops all collections including:
- Chat sessions & messages
- User Profile, Notes, & Tasks
- Uploaded file attachments
- Document Knowledge Base chunks

Usage:
    python wipe_database.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import get_settings
from backend.core.memory_store import MemoryStore

def main() -> int:
    settings = get_settings()
    
    # ---------------------------------------------------------
    # 1. First Safety Check: ADMIN_TOKEN
    # ---------------------------------------------------------
    admin_token = os.getenv("ADMIN_TOKEN", "").strip()
    if not admin_token:
        print("ERROR: ADMIN_TOKEN is not configured in .env.")
        print("You must have an ADMIN_TOKEN set to use this nuclear script.")
        return 1

    print("\n" + "=" * 60)
    print("                  SECURITY AUTHORIZATION")
    print("=" * 60)
    token_input = input("Enter your ADMIN_TOKEN to unlock this tool: ").strip()
    
    if token_input != admin_token:
        print("\n[!] AUTHORIZATION FAILED. Incorrect token.")
        return 1

    # ---------------------------------------------------------
    # 2. Second Safety Check: WIPE Confirmation
    # ---------------------------------------------------------
    print("\n\n" + "!" * 60)
    print("!!! DANGER: NUCLEAR WIPE UTILITY !!!".center(60))
    print("!" * 60)
    print("\nYou are about to PERMANENTLY DELETE everything in the database:")
    print(f"  Database URI:  {settings.mongodb_uri}")
    print(f"  Database Name: {settings.mongodb_db}")
    print("\nThis includes:")
    print("  - All Chat Sessions and Messages")
    print("  - All Agent Memories (Profile, Notes, Tasks)")
    print("  - All Knowledge Base Documents and Chunks")
    print("  - All File Attachments")
    print("\nTHIS ACTION CANNOT BE UNDONE.")
    
    confirm = input('\nTo proceed, type exactly the word "WIPE" (in all caps): ')
    
    if confirm != "WIPE":
        print("\n[+] Aborted. Your data is safe.")
        return 0

    # ---------------------------------------------------------
    # 3. Execution: Drop Collections
    # ---------------------------------------------------------
    print("\nConnecting to MongoDB...")
    try:
        # Initialize in mongo mode
        store = MemoryStore(
            mongodb_uri=settings.mongodb_uri,
            db_name=settings.mongodb_db,
            mode="mongo"
        )
    except Exception as exc:
        print(f"ERROR: Cannot connect to MongoDB: {exc}")
        return 1

    print("\nWiping collections...")
    
    # List of all collections managed by MemoryStore
    collections_to_drop = [
        store._sessions,
        store._messages,
        store._profile,
        store._notes,
        store._tasks,
        store._activity,
        store._cache,
        store._knowledge_chunks,
        store._session_attachments,
        store._session_chunks,
    ]

    dropped_count = 0
    for collection in collections_to_drop:
        if collection is not None:
            col_name = collection.name
            try:
                count = collection.count_documents({})
                collection.drop()
                print(f"  - Dropped '{col_name}' ({count} documents destroyed)")
                dropped_count += 1
            except Exception as e:
                print(f"  - Failed to drop '{col_name}': {e}")

    # The store._ensure_indexes() and _ensure_profile() might run on next boot,
    # but we don't need to rebuild them here since we're just wiping.
    
    store._client.close()

    print("\n" + "=" * 60)
    print(f"SUCCESS: {dropped_count} collections have been completely wiped.")
    print("Your database is now entirely empty.")
    print("=" * 60 + "\n")
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n[+] Aborted by user. Your data is safe.")
        sys.exit(130)
