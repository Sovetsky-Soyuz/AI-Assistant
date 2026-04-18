from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, PyMongoError

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# MongoDB Schema Reference
# ---------------------------------------------------------------------------
#
# Collection: sessions
#   { session_id: str, title: str, created_at: str, updated_at: str,
#     pinned: bool, archived: bool }
#
# Collection: messages
#   { message_id: str, session_id: str, role: str, text: str,
#     created_at: str }
#
# Collection: profile  (single document, _id = "user_profile")
#   { display_name: str, location: str, routine: str, updated_at: str }
#
# Collection: notes
#   { note_id: str, category: str, text: str, created_at: str }
#
# Collection: tasks
#   { task_id: str, title: str, priority: str, due_date: str,
#     status: str, created_at: str, completed_at: str }
#
# Collection: activity
#   { activity_id: str, kind: str, payload: dict, created_at: str }
#
# Collection: cache  (_id = "last_weather" | "last_news")
#   { data: dict, updated_at: str }
#
# Collection: knowledge_chunks
#   { chunk_id: str, source_file: str, file_hash: str, chunk_index: int,
#     text: str, metadata: dict, created_at: str }
#
# Collection: session_attachments
#   { attachment_id: str, session_id: str, filename: str, file_type: str,
#     file_size: int, storage_path: str, created_at: str }
#
# Collection: session_chunks
#   { chunk_id: str, attachment_id: str, session_id: str, chunk_index: int,
#     text: str, metadata: dict, created_at: str }
# ---------------------------------------------------------------------------

_MAX_ACTIVITY_ENTRIES = 20


class MemoryStore:
    """Persistent memory store backed by MongoDB.

    Public API is kept identical to the previous JSON-file implementation so
    that ``orbit_brain.py``, ``llm_client.py``, and ``gemini_client.py``
    continue to work without any changes.
    """

    # ------------------------------------------------------------------
    # Initialisation & connection
    # ------------------------------------------------------------------

    def __init__(
        self,
        mongodb_uri: str = "mongodb://localhost:27017",
        db_name: str = "orbit_assistant",
    ) -> None:
        self._lock = threading.Lock()

        try:
            self._client: MongoClient = MongoClient(
                mongodb_uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
            # Force a connection check so we fail fast if Mongo is down.
            self._client.admin.command("ping")
        except ConnectionFailure as exc:
            raise RuntimeError(
                f"Cannot connect to MongoDB at {mongodb_uri}. "
                "Make sure the MongoDB server is running."
            ) from exc

        self._db: Database = self._client[db_name]

        # Collection handles
        self._sessions: Collection = self._db["sessions"]
        self._messages: Collection = self._db["messages"]
        self._profile: Collection = self._db["profile"]
        self._notes: Collection = self._db["notes"]
        self._tasks: Collection = self._db["tasks"]
        self._activity: Collection = self._db["activity"]
        self._cache: Collection = self._db["cache"]
        self._knowledge_chunks: Collection = self._db["knowledge_chunks"]
        self._session_attachments: Collection = self._db["session_attachments"]
        self._session_chunks: Collection = self._db["session_chunks"]

        self._ensure_indexes()
        self._ensure_profile()

        logger.info("MemoryStore connected to MongoDB (%s / %s)", mongodb_uri, db_name)

    def _ensure_indexes(self) -> None:
        self._sessions.create_index("session_id", unique=True)
        self._sessions.create_index([("pinned", DESCENDING), ("updated_at", DESCENDING)])
        self._messages.create_index([("session_id", ASCENDING), ("created_at", ASCENDING)])
        self._messages.create_index("message_id", unique=True)
        self._tasks.create_index("task_id", unique=True)
        self._notes.create_index("note_id", unique=True)
        self._activity.create_index([("created_at", DESCENDING)])
        self._knowledge_chunks.create_index("chunk_id", unique=True)
        self._knowledge_chunks.create_index("source_file")
        self._knowledge_chunks.create_index("file_hash")
        self._session_attachments.create_index("attachment_id", unique=True)
        self._session_attachments.create_index("session_id")
        self._session_chunks.create_index("chunk_id", unique=True)
        self._session_chunks.create_index("session_id")
        self._session_chunks.create_index("attachment_id")

    def _ensure_profile(self) -> None:
        if self._profile.find_one({"_id": "user_profile"}) is None:
            self._profile.insert_one(
                {
                    "_id": "user_profile",
                    "display_name": "",
                    "location": "",
                    "routine": "",
                    "updated_at": utc_now(),
                }
            )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_id(doc: dict[str, Any] | None) -> dict[str, Any]:
        if doc is None:
            return {}
        doc.pop("_id", None)
        return doc

    def _append_activity_record(
        self, kind: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Insert an activity entry and trim the collection to the last N."""
        self._activity.insert_one(
            {
                "activity_id": uuid.uuid4().hex[:8],
                "kind": kind,
                "payload": payload or {},
                "created_at": utc_now(),
            }
        )
        count = self._activity.count_documents({})
        if count > _MAX_ACTIVITY_ENTRIES:
            excess = list(
                self._activity.find()
                .sort("created_at", ASCENDING)
                .limit(count - _MAX_ACTIVITY_ENTRIES)
            )
            if excess:
                self._activity.delete_many({"_id": {"$in": [d["_id"] for d in excess]}})

    # ------------------------------------------------------------------
    # Legacy read interface  (consumed by orbit_brain / server)
    # ------------------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        """Return the full memory state as a plain dict.

        The shape mirrors the old JSON structure so every caller that relied
        on it keeps working.
        """
        with self._lock:
            profile_doc = self._profile.find_one({"_id": "user_profile"}) or {}
            task_docs = list(self._tasks.find().sort("created_at", ASCENDING))
            note_docs = list(self._notes.find().sort("created_at", ASCENDING))
            activity_docs = list(
                self._activity.find().sort("created_at", ASCENDING).limit(_MAX_ACTIVITY_ENTRIES)
            )
            weather_doc = self._cache.find_one({"_id": "last_weather"})
            news_doc = self._cache.find_one({"_id": "last_news"})

        note_entries = [
            {
                "id": n.get("note_id", ""),
                "category": n.get("category", "note"),
                "text": n.get("text", ""),
                "created_at": n.get("created_at", ""),
            }
            for n in note_docs
        ]

        task_entries = [
            {
                "id": t.get("task_id", ""),
                "title": t.get("title", ""),
                "priority": t.get("priority", "medium"),
                "due_date": t.get("due_date", ""),
                "status": t.get("status", "open"),
                "created_at": t.get("created_at", ""),
                "completed_at": t.get("completed_at", ""),
            }
            for t in task_docs
        ]

        activity_entries = [
            {
                "id": a.get("activity_id", ""),
                "kind": a.get("kind", ""),
                "payload": a.get("payload", {}),
                "created_at": a.get("created_at", ""),
            }
            for a in activity_docs
        ]

        return {
            "profile": {
                "display_name": profile_doc.get("display_name", ""),
                "location": profile_doc.get("location", ""),
                "routine": profile_doc.get("routine", ""),
                "notes": note_entries,
            },
            "tasks": task_entries,
            "history": [],  # Deprecated field -- use get_messages / get_sessions
            "last_weather": weather_doc.get("data") if weather_doc else None,
            "last_news": news_doc.get("data") if news_doc else None,
            "activity": activity_entries,
            "updated_at": profile_doc.get("updated_at", ""),
        }

    def get_brief(self) -> dict[str, Any]:
        state = self.get_state()
        return self._build_brief(state)

    def _build_brief(self, state: dict[str, Any]) -> dict[str, Any]:
        open_tasks = [t for t in state["tasks"] if t["status"] == "open"]
        completed_tasks = [t for t in state["tasks"] if t["status"] == "done"]

        return {
            "profile": {
                "display_name": state["profile"]["display_name"],
                "location": state["profile"]["location"],
                "routine": state["profile"]["routine"],
            },
            "recent_notes": state["profile"]["notes"][-6:],
            "open_tasks": open_tasks[:8],
            "completed_tasks": completed_tasks[-4:],
            "last_weather": state["last_weather"],
            "last_news": state.get("last_news"),
            "stats": {
                "open_task_count": len(open_tasks),
                "completed_task_count": len(completed_tasks),
                "note_count": len(state["profile"]["notes"]),
            },
        }

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def update_profile(
        self,
        display_name: str | None = None,
        location: str | None = None,
        routine: str | None = None,
    ) -> dict[str, Any]:
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if display_name is not None:
            updates["display_name"] = display_name.strip()
        if location is not None:
            updates["location"] = location.strip()
        if routine is not None:
            updates["routine"] = routine.strip()

        with self._lock:
            self._profile.update_one({"_id": "user_profile"}, {"$set": updates})
            self._append_activity_record(
                "profile_updated",
                {"display_name": display_name, "location": location},
            )

        return self._build_brief(self.get_state())

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def remember_note(self, note: str, category: str = "note") -> dict[str, Any]:
        cleaned_note = note.strip()
        if not cleaned_note:
            raise ValueError("Note text cannot be empty.")

        note_id = uuid.uuid4().hex[:8]
        now = utc_now()
        cat = (category or "note").strip().lower()

        with self._lock:
            self._notes.insert_one(
                {
                    "note_id": note_id,
                    "category": cat,
                    "text": cleaned_note,
                    "created_at": now,
                }
            )
            self._append_activity_record(
                "note_saved",
                {"id": note_id, "category": cat, "text": cleaned_note, "created_at": now},
            )

        return {"id": note_id, "category": cat, "text": cleaned_note, "created_at": now}

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def add_task(
        self, title: str, priority: str = "medium", due_date: str | None = None
    ) -> dict[str, Any]:
        cleaned_title = title.strip()
        if not cleaned_title:
            raise ValueError("Task title cannot be empty.")

        task_id = uuid.uuid4().hex[:8]
        now = utc_now()
        prio = (priority or "medium").strip().lower()
        dd = due_date.strip() if isinstance(due_date, str) and due_date.strip() else ""

        task_doc = {
            "task_id": task_id,
            "title": cleaned_title,
            "priority": prio,
            "due_date": dd,
            "status": "open",
            "created_at": now,
            "completed_at": "",
        }

        with self._lock:
            self._tasks.insert_one(task_doc)
            self._append_activity_record("task_added", {
                "id": task_id, "title": cleaned_title, "priority": prio,
                "due_date": dd, "status": "open", "created_at": now, "completed_at": "",
            })

        return {
            "id": task_id,
            "title": cleaned_title,
            "priority": prio,
            "due_date": dd,
            "status": "open",
            "created_at": now,
            "completed_at": "",
        }

    def complete_task(self, task_ref: str) -> dict[str, Any]:
        reference = (task_ref or "").strip().lower()
        if not reference:
            raise KeyError("Task reference cannot be empty.")

        now = utc_now()

        with self._lock:
            # Try exact match on task_id first.
            task = self._tasks.find_one({"task_id": reference, "status": "open"})

            # Fall back to substring match on title.
            if task is None:
                for candidate in self._tasks.find({"status": "open"}):
                    if reference in candidate.get("title", "").lower():
                        task = candidate
                        break

            if task is None:
                raise KeyError(f"Could not find an open task matching '{task_ref}'.")

            self._tasks.update_one(
                {"_id": task["_id"]},
                {"$set": {"status": "done", "completed_at": now}},
            )
            self._append_activity_record(
                "task_completed",
                {"id": task.get("task_id", ""), "title": task.get("title", "")},
            )

        return {
            "id": task.get("task_id", ""),
            "title": task.get("title", ""),
            "priority": task.get("priority", "medium"),
            "due_date": task.get("due_date", ""),
            "status": "done",
            "created_at": task.get("created_at", ""),
            "completed_at": now,
        }

    def delete_task(self, task_ref: str) -> dict[str, Any]:
        """Delete a task by id or a unique substring of its title."""
        reference = (task_ref or "").strip().lower()
        if not reference:
            raise KeyError("Task reference cannot be empty.")

        with self._lock:
            task = self._tasks.find_one({"task_id": reference})

            if task is None:
                for candidate in self._tasks.find():
                    if reference in candidate.get("title", "").lower():
                        task = candidate
                        break

            if task is None:
                raise KeyError(f"Could not find a task matching '{task_ref}'.")

            self._tasks.delete_one({"_id": task["_id"]})
            self._append_activity_record(
                "task_deleted",
                {"id": task.get("task_id", ""), "title": task.get("title", "")},
            )

        return {
            "id": task.get("task_id", ""),
            "title": task.get("title", ""),
            "status": task.get("status", ""),
            "deleted": True,
        }

    def delete_note(self, note_id: str) -> dict[str, Any]:
        """Delete a note by its note_id. Used by the REST API (user-initiated only)."""
        nid = (note_id or "").strip()
        if not nid:
            raise KeyError("Note ID cannot be empty.")

        with self._lock:
            note = self._notes.find_one({"note_id": nid})
            if note is None:
                raise KeyError(f"Note '{note_id}' not found.")

            self._notes.delete_one({"_id": note["_id"]})
            self._append_activity_record(
                "note_deleted",
                {"id": nid, "text": note.get("text", "")[:60]},
            )

        return {
            "id": nid,
            "text": note.get("text", ""),
            "deleted": True,
        }

    # ------------------------------------------------------------------
    # Weather / News cache
    # ------------------------------------------------------------------

    def set_last_weather(self, weather: dict[str, Any]) -> None:
        with self._lock:
            self._cache.update_one(
                {"_id": "last_weather"},
                {"$set": {"data": weather, "updated_at": utc_now()}},
                upsert=True,
            )
            self._append_activity_record(
                "weather_checked", {"location": weather.get("location", "")}
            )

    def set_last_news(self, news: dict[str, Any]) -> None:
        with self._lock:
            self._cache.update_one(
                {"_id": "last_news"},
                {"$set": {"data": news, "updated_at": utc_now()}},
                upsert=True,
            )
            self._append_activity_record(
                "news_checked", {"topic": news.get("topic", "")}
            )

    # ------------------------------------------------------------------
    # Chat history  (legacy compatibility bridge)
    # ------------------------------------------------------------------

    def update_history(
        self,
        chat_history: list[dict[str, str]],
        session_id: str | None = None,
    ) -> None:
        """Persist a chat-history list into the messages collection.

        FIX: the old implementation blindly wrote whatever the frontend sent,
        including empty arrays, wiping saved history.  Now we skip empty
        payloads entirely.
        """
        if not chat_history:
            return  # <-- fix: never overwrite with nothing

        with self._lock:
            if not session_id:
                default = self._sessions.find_one({"title": "Default"})
                if default is None:
                    session_id = uuid.uuid4().hex[:12]
                    now = utc_now()
                    self._sessions.insert_one(
                        {
                            "session_id": session_id,
                            "title": "Default",
                            "created_at": now,
                            "updated_at": now,
                            "pinned": False,
                            "archived": False,
                        }
                    )
                else:
                    session_id = default["session_id"]

            # Replace all messages for this session with the incoming list.
            self._messages.delete_many({"session_id": session_id})

            now = utc_now()
            docs = [
                {
                    "message_id": uuid.uuid4().hex[:8],
                    "session_id": session_id,
                    "role": entry.get("role", "user"),
                    "text": entry.get("text", ""),
                    "created_at": entry.get("created_at", now),
                }
                for entry in chat_history
                if (entry.get("text") or "").strip()
            ]
            if docs:
                self._messages.insert_many(docs)
                self._sessions.update_one(
                    {"session_id": session_id},
                    {"$set": {"updated_at": now}},
                )

    def get_history(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """Return chat messages, optionally filtered by session."""
        with self._lock:
            query: dict[str, Any] = {}
            if session_id:
                query["session_id"] = session_id
            cursor = self._messages.find(query).sort("created_at", ASCENDING)
            messages = list(cursor)

        return [
            {
                "role": m.get("role", "user"),
                "text": m.get("text", ""),
                "created_at": m.get("created_at", ""),
                "session_id": m.get("session_id", ""),
            }
            for m in messages
        ]

    # ==================================================================
    # Session management  (new -- supports multi-session UI)
    # ==================================================================

    def create_session(self, title: str | None = None) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        now = utc_now()
        doc = {
            "session_id": session_id,
            "title": (title or "New Chat").strip(),
            "created_at": now,
            "updated_at": now,
            "pinned": False,
            "archived": False,
        }
        with self._lock:
            self._sessions.insert_one(doc)
            self._append_activity_record(
                "session_created",
                {"session_id": session_id, "title": doc["title"]},
            )
        return self._strip_id(doc)

    def get_sessions(self, include_archived: bool = False) -> list[dict[str, Any]]:
        query: dict[str, Any] = {} if include_archived else {"archived": {"$ne": True}}
        with self._lock:
            docs = list(
                self._sessions.find(query).sort(
                    [("pinned", DESCENDING), ("updated_at", DESCENDING)]
                )
            )
        return [self._strip_id(d) for d in docs]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            doc = self._sessions.find_one({"session_id": session_id})
        if doc is None:
            return None
        return self._strip_id(doc)

    def update_session(self, session_id: str, **kwargs: Any) -> dict[str, Any]:
        allowed = {"title", "pinned", "archived"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            raise ValueError("No valid fields to update.")
        updates["updated_at"] = utc_now()

        with self._lock:
            result = self._sessions.find_one_and_update(
                {"session_id": session_id},
                {"$set": updates},
                return_document=True,
            )
        if result is None:
            raise KeyError(f"Session '{session_id}' not found.")
        return self._strip_id(result)

    def delete_session(self, session_id: str) -> list[dict[str, Any]]:
        """Delete session and return attachment docs (for disk cleanup by caller)."""
        with self._lock:
            attachments = [
                self._strip_id(a)
                for a in self._session_attachments.find({"session_id": session_id})
            ]
            self._sessions.delete_one({"session_id": session_id})
            self._messages.delete_many({"session_id": session_id})
            self._session_attachments.delete_many({"session_id": session_id})
            self._session_chunks.delete_many({"session_id": session_id})
            self._append_activity_record(
                "session_deleted", {"session_id": session_id}
            )
        return attachments

    # ==================================================================
    # Message management  (new -- per-message CRUD)
    # ==================================================================

    def add_message(
        self, session_id: str, role: str, text: str
    ) -> dict[str, Any]:
        if not (text or "").strip():
            raise ValueError("Message text cannot be empty.")

        message_id = uuid.uuid4().hex[:8]
        now = utc_now()
        doc = {
            "message_id": message_id,
            "session_id": session_id,
            "role": role,
            "text": text.strip(),
            "created_at": now,
        }
        with self._lock:
            self._messages.insert_one(doc)
            self._sessions.update_one(
                {"session_id": session_id},
                {"$set": {"updated_at": now}},
            )
        return self._strip_id(doc)

    def get_messages(
        self, session_id: str, limit: int = 0
    ) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self._messages.find({"session_id": session_id}).sort(
                "created_at", ASCENDING
            )
            if limit > 0:
                cursor = cursor.limit(limit)
            docs = list(cursor)
        return [self._strip_id(d) for d in docs]

    def delete_message(self, message_id: str) -> None:
        with self._lock:
            self._messages.delete_one({"message_id": message_id})

    # ==================================================================
    # Knowledge chunks  (persistent RAG cache from knowledge_base)
    # ==================================================================

    def get_knowledge_file_hashes(self) -> dict[str, str]:
        """Return {source_file: file_hash} for all indexed knowledge files."""
        with self._lock:
            pipeline = [
                {"$group": {"_id": "$source_file", "hash": {"$first": "$file_hash"}}},
            ]
            results = list(self._knowledge_chunks.aggregate(pipeline))
        return {r["_id"]: r["hash"] for r in results}

    def store_knowledge_chunks(
        self, source_file: str, file_hash: str, chunks: list[dict[str, Any]]
    ) -> int:
        """Store parsed chunks for a knowledge_base file. Replaces old chunks."""
        now = utc_now()
        with self._lock:
            self._knowledge_chunks.delete_many({"source_file": source_file})
            docs = [
                {
                    "chunk_id": uuid.uuid4().hex[:12],
                    "source_file": source_file,
                    "file_hash": file_hash,
                    "chunk_index": i,
                    "text": c["text"],
                    "metadata": c.get("metadata", {}),
                    "created_at": now,
                }
                for i, c in enumerate(chunks)
            ]
            if docs:
                self._knowledge_chunks.insert_many(docs)
        return len(docs)

    def get_all_knowledge_chunks(self) -> list[dict[str, Any]]:
        """Return all knowledge chunks for building retrievers at startup."""
        with self._lock:
            docs = list(
                self._knowledge_chunks.find().sort(
                    [("source_file", ASCENDING), ("chunk_index", ASCENDING)]
                )
            )
        return [self._strip_id(d) for d in docs]

    def delete_knowledge_file(self, source_file: str) -> None:
        """Remove all chunks for a specific knowledge_base file."""
        with self._lock:
            self._knowledge_chunks.delete_many({"source_file": source_file})

    def clear_all_knowledge_chunks(self) -> int:
        """Drop all knowledge chunks and rebuild indexes. Returns count of cleared docs."""
        with self._lock:
            count = self._knowledge_chunks.count_documents({})
            self._knowledge_chunks.drop()
        self._ensure_indexes()
        return count

    # ==================================================================
    # Session attachments  (files attached in chat sessions)
    # ==================================================================

    def add_session_attachment(
        self,
        session_id: str,
        filename: str,
        file_type: str,
        file_size: int,
        storage_path: str,
    ) -> dict[str, Any]:
        attachment_id = uuid.uuid4().hex[:12]
        now = utc_now()
        doc = {
            "attachment_id": attachment_id,
            "session_id": session_id,
            "filename": filename,
            "file_type": file_type,
            "file_size": file_size,
            "storage_path": storage_path,
            "created_at": now,
        }
        with self._lock:
            self._session_attachments.insert_one(doc)
            self._append_activity_record(
                "attachment_added",
                {"attachment_id": attachment_id, "session_id": session_id, "filename": filename},
            )
        return self._strip_id(doc)

    def get_session_attachments(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            docs = list(
                self._session_attachments.find({"session_id": session_id}).sort("created_at", ASCENDING)
            )
        return [self._strip_id(d) for d in docs]

    def delete_session_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        """Delete an attachment and its chunks. Returns the attachment doc for disk cleanup."""
        with self._lock:
            doc = self._session_attachments.find_one({"attachment_id": attachment_id})
            if doc is None:
                return None
            self._session_attachments.delete_one({"_id": doc["_id"]})
            self._session_chunks.delete_many({"attachment_id": attachment_id})
        return self._strip_id(doc)

    # ==================================================================
    # Session chunks  (parsed text from session attachments)
    # ==================================================================

    def store_session_chunks(
        self, session_id: str, attachment_id: str, chunks: list[dict[str, Any]]
    ) -> int:
        now = utc_now()
        with self._lock:
            docs = [
                {
                    "chunk_id": uuid.uuid4().hex[:12],
                    "attachment_id": attachment_id,
                    "session_id": session_id,
                    "chunk_index": i,
                    "text": c["text"],
                    "metadata": c.get("metadata", {}),
                    "created_at": now,
                }
                for i, c in enumerate(chunks)
            ]
            if docs:
                self._session_chunks.insert_many(docs)
        return len(docs)

    def get_session_chunks(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            docs = list(
                self._session_chunks.find({"session_id": session_id}).sort(
                    [("attachment_id", ASCENDING), ("chunk_index", ASCENDING)]
                )
            )
        return [self._strip_id(d) for d in docs]

    # ==================================================================
    # Data migration  (one-time import from legacy JSON files)
    # ==================================================================

    @classmethod
    def migrate_from_json(
        cls,
        json_path: str | Path,
        history_path: str | Path | None = None,
        mongodb_uri: str = "mongodb://localhost:27017",
        db_name: str = "orbit_assistant",
    ) -> "MemoryStore":
        """Import existing ``assistant_memory.json`` and ``chat_history.json``
        into MongoDB.  Returns the ready-to-use MemoryStore instance.

        Safe to call repeatedly -- duplicate entries (matched by id) are
        skipped.
        """
        store = cls(mongodb_uri=mongodb_uri, db_name=db_name)
        json_file = Path(json_path)

        if not json_file.exists():
            logger.info("No legacy JSON file found at %s -- skipping migration.", json_file)
            return store

        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read legacy JSON (%s): %s", json_file, exc)
            return store

        # --- Profile ---
        profile = data.get("profile", {})
        store._profile.update_one(
            {"_id": "user_profile"},
            {
                "$set": {
                    "display_name": profile.get("display_name", ""),
                    "location": profile.get("location", ""),
                    "routine": profile.get("routine", ""),
                    "updated_at": data.get("updated_at", utc_now()),
                }
            },
            upsert=True,
        )

        # --- Notes ---
        for note in profile.get("notes", []):
            nid = note.get("id", uuid.uuid4().hex[:8])
            if store._notes.find_one({"note_id": nid}) is None:
                store._notes.insert_one(
                    {
                        "note_id": nid,
                        "category": note.get("category", "note"),
                        "text": note.get("text", ""),
                        "created_at": note.get("created_at", utc_now()),
                    }
                )

        # --- Tasks ---
        for task in data.get("tasks", []):
            tid = task.get("id", uuid.uuid4().hex[:8])
            if store._tasks.find_one({"task_id": tid}) is None:
                store._tasks.insert_one(
                    {
                        "task_id": tid,
                        "title": task.get("title", ""),
                        "priority": task.get("priority", "medium"),
                        "due_date": task.get("due_date", ""),
                        "status": task.get("status", "open"),
                        "created_at": task.get("created_at", utc_now()),
                        "completed_at": task.get("completed_at", ""),
                    }
                )

        # --- Activity ---
        for act in data.get("activity", []):
            aid = act.get("id", uuid.uuid4().hex[:8])
            if store._activity.find_one({"activity_id": aid}) is None:
                store._activity.insert_one(
                    {
                        "activity_id": aid,
                        "kind": act.get("kind", ""),
                        "payload": act.get("payload", {}),
                        "created_at": act.get("created_at", utc_now()),
                    }
                )

        # --- Cache (weather / news) ---
        if data.get("last_weather"):
            store._cache.update_one(
                {"_id": "last_weather"},
                {"$set": {"data": data["last_weather"], "updated_at": utc_now()}},
                upsert=True,
            )
        if data.get("last_news"):
            store._cache.update_one(
                {"_id": "last_news"},
                {"$set": {"data": data["last_news"], "updated_at": utc_now()}},
                upsert=True,
            )

        # --- Chat history ---
        if history_path:
            hist_file = Path(history_path)
            if hist_file.exists() and hist_file.stat().st_size > 2:
                try:
                    history = json.loads(hist_file.read_text(encoding="utf-8"))
                    if isinstance(history, list) and history:
                        store.update_history(history)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Could not read legacy chat history (%s): %s", hist_file, exc)

        logger.info("Legacy JSON data migrated successfully from %s", json_file)
        return store
