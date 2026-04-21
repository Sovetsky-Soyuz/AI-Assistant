from __future__ import annotations

import json
import logging
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ConnectionFailure

logger = logging.getLogger(__name__)

_MAX_ACTIVITY_ENTRIES = 20
_MAX_EPHEMERAL_CLIENTS = 100
MEMORY_DISABLED_MESSAGE = (
    "This feature requires Agent Memory. Please enable MongoDB on server startup "
    "to use long-term memory, notes, tasks, pinning, and archiving."
)


class MemoryDisabledError(RuntimeError):
    """Raised when a persistent-memory-only feature is used in Ephemeral Mode."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_state() -> dict[str, Any]:
    return {
        "profile": {
            "display_name": "",
            "location": "",
            "routine": "",
            "notes": [],
        },
        "tasks": [],
        "history": [],
        "last_weather": None,
        "last_news": None,
        "activity": [],
        "updated_at": "",
    }


@dataclass
class EphemeralClientState:
    sessions: OrderedDict[str, dict[str, Any]] = field(default_factory=OrderedDict)
    messages_by_session: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    activity: list[dict[str, Any]] = field(default_factory=list)
    cache: dict[str, Any] = field(default_factory=dict)
    last_accessed_at: str = field(default_factory=utc_now)


class MemoryStore:
    """Application storage with Mongo-backed and Ephemeral in-RAM modes."""

    def __init__(
        self,
        mongodb_uri: str = "mongodb://localhost:27017",
        db_name: str = "orbit_assistant",
        mode: str = "mongo",
    ) -> None:
        self._lock = threading.Lock()
        self.storage_mode = "ephemeral" if (mode or "").strip().lower() == "ephemeral" else "mongo"

        self._client: MongoClient | None = None
        self._db: Database | None = None
        self._sessions: Collection | None = None
        self._messages: Collection | None = None
        self._profile: Collection | None = None
        self._notes: Collection | None = None
        self._tasks: Collection | None = None
        self._activity: Collection | None = None
        self._cache: Collection | None = None
        self._knowledge_chunks: Collection | None = None
        self._session_attachments: Collection | None = None
        self._session_chunks: Collection | None = None

        self._ephemeral_clients: OrderedDict[str, EphemeralClientState] = OrderedDict()
        self._knowledge_chunks_ram: dict[str, list[dict[str, Any]]] = {}

        if self.is_ephemeral:
            logger.info("MemoryStore started in Ephemeral Mode.")
            return

        try:
            self._client = MongoClient(
                mongodb_uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
            self._client.admin.command("ping")
        except ConnectionFailure as exc:
            raise RuntimeError(
                f"Cannot connect to MongoDB at {mongodb_uri}. "
                "Make sure the MongoDB server is running."
            ) from exc

        self._db = self._client[db_name]
        self._sessions = self._db["sessions"]
        self._messages = self._db["messages"]
        self._profile = self._db["profile"]
        self._notes = self._db["notes"]
        self._tasks = self._db["tasks"]
        self._activity = self._db["activity"]
        self._cache = self._db["cache"]
        self._knowledge_chunks = self._db["knowledge_chunks"]
        self._session_attachments = self._db["session_attachments"]
        self._session_chunks = self._db["session_chunks"]

        self._ensure_indexes()
        self._ensure_profile()
        logger.info("MemoryStore connected to MongoDB (%s / %s)", mongodb_uri, db_name)

    @property
    def is_ephemeral(self) -> bool:
        return self.storage_mode == "ephemeral"

    @property
    def supports_persistent_memory(self) -> bool:
        return not self.is_ephemeral

    def _ensure_indexes(self) -> None:
        if self.is_ephemeral:
            return

        # assert self._sessions and self._messages and self._tasks and self._notes
        # assert self._activity and self._knowledge_chunks and self._session_attachments and self._session_chunks

        assert self._sessions is not None and self._messages is not None and self._tasks is not None and self._notes is not None
        assert self._activity is not None and self._knowledge_chunks is not None and self._session_attachments is not None and self._session_chunks is not None

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
        if self.is_ephemeral:
            return

        # assert self._profile

        assert self._profile is not None

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
        if self._client is not None:
            self._client.close()

    @staticmethod
    def _strip_id(doc: dict[str, Any] | None) -> dict[str, Any]:
        if doc is None:
            return {}
        clean = dict(doc)
        clean.pop("_id", None)
        return clean

    def _require_persistent_memory(self) -> None:
        if self.is_ephemeral:
            raise MemoryDisabledError(MEMORY_DISABLED_MESSAGE)

    def _require_ephemeral_client(self, client_id: str | None) -> str:
        cleaned = (client_id or "").strip()
        if not cleaned:
            raise ValueError("Missing X-Orbit-Ephemeral-Client header.")
        return cleaned

    def _append_ephemeral_activity_locked(
        self, state: EphemeralClientState, kind: str, payload: dict[str, Any] | None = None
    ) -> None:
        state.activity.append(
            {
                "id": uuid.uuid4().hex[:8],
                "kind": kind,
                "payload": payload or {},
                "created_at": utc_now(),
            }
        )
        if len(state.activity) > _MAX_ACTIVITY_ENTRIES:
            state.activity = state.activity[-_MAX_ACTIVITY_ENTRIES:]

    def _count_ephemeral_messages_locked(self, state: EphemeralClientState) -> int:
        return sum(len(messages) for messages in state.messages_by_session.values())

    def _ephemeral_counts_locked(self, state: EphemeralClientState) -> dict[str, int]:
        return {
            "sessions": len(state.sessions),
            "messages": self._count_ephemeral_messages_locked(state),
        }

    def _prune_ephemeral_clients_locked(self) -> None:
        while len(self._ephemeral_clients) > _MAX_EPHEMERAL_CLIENTS:
            client_id, state = self._ephemeral_clients.popitem(last=False)
            counts = self._ephemeral_counts_locked(state)
            logger.info(
                "Pruned Ephemeral client '%s' from RAM (%s session(s), %s message(s)).",
                client_id,
                counts["sessions"],
                counts["messages"],
            )

    def _get_ephemeral_client_locked(self, client_id: str | None) -> EphemeralClientState:
        client_key = self._require_ephemeral_client(client_id)
        state = self._ephemeral_clients.get(client_key)
        if state is None:
            state = EphemeralClientState()
            self._ephemeral_clients[client_key] = state
        state.last_accessed_at = utc_now()
        self._ephemeral_clients.move_to_end(client_key)
        self._prune_ephemeral_clients_locked()
        return state

    def _get_state_for_ephemeral_client_locked(self, state: EphemeralClientState) -> dict[str, Any]:
        return {
            "profile": {
                "display_name": "",
                "location": "",
                "routine": "",
                "notes": [],
            },
            "tasks": [],
            "history": [],
            "last_weather": state.cache.get("last_weather"),
            "last_news": state.cache.get("last_news"),
            "activity": list(state.activity),
            "updated_at": state.last_accessed_at,
        }

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

    def get_state(self, client_id: str | None = None) -> dict[str, Any]:
        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                return self._get_state_for_ephemeral_client_locked(state)

        # assert self._profile and self._tasks and self._notes and self._activity and self._cache

        assert self._profile is not None and self._tasks is not None and self._notes is not None and self._activity is not None and self._cache is not None

        with self._lock:
            profile_doc = self._profile.find_one({"_id": "user_profile"}) or {}
            task_docs = list(self._tasks.find().sort("created_at", ASCENDING))
            note_docs = list(self._notes.find().sort("created_at", ASCENDING))
            activity_docs = list(
                self._activity.find().sort("created_at", ASCENDING).limit(_MAX_ACTIVITY_ENTRIES)
            )
            weather_doc = self._cache.find_one({"_id": "last_weather"})
            news_doc = self._cache.find_one({"_id": "last_news"})

        return {
            "profile": {
                "display_name": profile_doc.get("display_name", ""),
                "location": profile_doc.get("location", ""),
                "routine": profile_doc.get("routine", ""),
                "notes": [
                    {
                        "id": n.get("note_id", ""),
                        "category": n.get("category", "note"),
                        "text": n.get("text", ""),
                        "created_at": n.get("created_at", ""),
                    }
                    for n in note_docs
                ],
            },
            "tasks": [
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
            ],
            "history": [],
            "last_weather": weather_doc.get("data") if weather_doc else None,
            "last_news": news_doc.get("data") if news_doc else None,
            "activity": [
                {
                    "id": a.get("activity_id", ""),
                    "kind": a.get("kind", ""),
                    "payload": a.get("payload", {}),
                    "created_at": a.get("created_at", ""),
                }
                for a in activity_docs
            ],
            "updated_at": profile_doc.get("updated_at", ""),
        }

    def get_brief(self, client_id: str | None = None) -> dict[str, Any]:
        return self._build_brief(self.get_state(client_id=client_id))

    def update_profile(
        self,
        display_name: str | None = None,
        location: str | None = None,
        routine: str | None = None,
    ) -> dict[str, Any]:
        self._require_persistent_memory()

        # assert self._profile

        assert self._profile is not None

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

    def remember_note(self, note: str, category: str = "note") -> dict[str, Any]:
        self._require_persistent_memory()

        # assert self._notes

        assert self._notes is not None

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

    def add_task(
        self, title: str, priority: str = "medium", due_date: str | None = None
    ) -> dict[str, Any]:
        self._require_persistent_memory()

        # assert self._tasks

        assert self._tasks is not None

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
            self._append_activity_record(
                "task_added",
                {
                    "id": task_id,
                    "title": cleaned_title,
                    "priority": prio,
                    "due_date": dd,
                    "status": "open",
                    "created_at": now,
                    "completed_at": "",
                },
            )

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
        self._require_persistent_memory()

        # assert self._tasks

        assert self._tasks is not None

        reference = (task_ref or "").strip().lower()
        if not reference:
            raise KeyError("Task reference cannot be empty.")

        now = utc_now()

        with self._lock:
            task = self._tasks.find_one({"task_id": reference, "status": "open"})
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
        self._require_persistent_memory()

        # assert self._tasks

        assert self._tasks is not None

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
        self._require_persistent_memory()

        # assert self._notes

        assert self._notes is not None

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

    def set_last_weather(self, weather: dict[str, Any], client_id: str | None = None) -> None:
        if self.is_ephemeral:
            if not client_id:
                return
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                state.cache["last_weather"] = weather
                self._append_ephemeral_activity_locked(
                    state, "weather_checked", {"location": weather.get("location", "")}
                )
            return

        # assert self._cache

        assert self._cache is not None

        with self._lock:
            self._cache.update_one(
                {"_id": "last_weather"},
                {"$set": {"data": weather, "updated_at": utc_now()}},
                upsert=True,
            )
            self._append_activity_record(
                "weather_checked", {"location": weather.get("location", "")}
            )

    def set_last_news(self, news: dict[str, Any], client_id: str | None = None) -> None:
        if self.is_ephemeral:
            if not client_id:
                return
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                state.cache["last_news"] = news
                self._append_ephemeral_activity_locked(
                    state, "news_checked", {"topic": news.get("topic", "")}
                )
            return

        # assert self._cache

        assert self._cache is not None

        with self._lock:
            self._cache.update_one(
                {"_id": "last_news"},
                {"$set": {"data": news, "updated_at": utc_now()}},
                upsert=True,
            )
            self._append_activity_record(
                "news_checked", {"topic": news.get("topic", "")}
            )

    def update_history(
        self,
        chat_history: list[dict[str, str]],
        session_id: str | None = None,
        client_id: str | None = None,
    ) -> None:
        if not chat_history:
            return

        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                target_session_id = session_id or uuid.uuid4().hex[:12]
                if target_session_id not in state.sessions:
                    now = utc_now()
                    state.sessions[target_session_id] = {
                        "session_id": target_session_id,
                        "title": "Default" if session_id is None else "New Chat",
                        "created_at": now,
                        "updated_at": now,
                        "pinned": False,
                        "archived": False,
                    }

                messages: list[dict[str, Any]] = []
                for entry in chat_history:
                    text = (entry.get("text") or "").strip()
                    if not text:
                        continue
                    messages.append(
                        {
                            "message_id": uuid.uuid4().hex[:8],
                            "session_id": target_session_id,
                            "role": entry.get("role", "user"),
                            "text": text,
                            "created_at": entry.get("created_at", utc_now()),
                        }
                    )

                state.messages_by_session[target_session_id] = messages
                state.sessions[target_session_id]["updated_at"] = utc_now()
            return

        # assert self._sessions and self._messages

        assert self._sessions is not None and self._messages is not None

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

    def get_history(
        self, session_id: str | None = None, client_id: str | None = None
    ) -> list[dict[str, Any]]:
        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                docs: list[dict[str, Any]] = []
                if session_id:
                    docs = list(state.messages_by_session.get(session_id, []))
                else:
                    for messages in state.messages_by_session.values():
                        docs.extend(messages)
                docs.sort(key=lambda item: item.get("created_at", ""))

            return [
                {
                    "role": m.get("role", "user"),
                    "text": m.get("text", ""),
                    "created_at": m.get("created_at", ""),
                    "session_id": m.get("session_id", ""),
                }
                for m in docs
            ]

        # assert self._messages

        assert self._messages is not None

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

    def create_session(self, title: str | None = None, client_id: str | None = None) -> dict[str, Any]:
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

        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                state.sessions[session_id] = dict(doc)
                state.messages_by_session.setdefault(session_id, [])
                self._append_ephemeral_activity_locked(
                    state,
                    "session_created",
                    {"session_id": session_id, "title": doc["title"]},
                )
            return dict(doc)

        # assert self._sessions

        assert self._sessions is not None

        with self._lock:
            self._sessions.insert_one(doc)
            self._append_activity_record(
                "session_created",
                {"session_id": session_id, "title": doc["title"]},
            )
        return self._strip_id(doc)

    def get_sessions(
        self, include_archived: bool = False, client_id: str | None = None
    ) -> list[dict[str, Any]]:
        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                docs = [dict(doc) for doc in state.sessions.values()]
            filtered = docs if include_archived else [doc for doc in docs if not doc.get("archived")]
            return sorted(
                filtered,
                key=lambda doc: (
                    1 if doc.get("pinned") else 0,
                    doc.get("updated_at", ""),
                ),
                reverse=True,
            )

        # assert self._sessions

        assert self._sessions is not None

        query: dict[str, Any] = {} if include_archived else {"archived": {"$ne": True}}
        with self._lock:
            docs = list(
                self._sessions.find(query).sort(
                    [("pinned", DESCENDING), ("updated_at", DESCENDING)]
                )
            )
        return [self._strip_id(d) for d in docs]

    def get_session(self, session_id: str, client_id: str | None = None) -> dict[str, Any] | None:
        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                doc = state.sessions.get(session_id)
                return dict(doc) if doc else None

        # assert self._sessions

        assert self._sessions is not None

        with self._lock:
            doc = self._sessions.find_one({"session_id": session_id})
        if doc is None:
            return None
        return self._strip_id(doc)

    def update_session(
        self, session_id: str, client_id: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        allowed = {"title", "pinned", "archived"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            raise ValueError("No valid fields to update.")

        if self.is_ephemeral:
            if "pinned" in updates or "archived" in updates:
                raise MemoryDisabledError(MEMORY_DISABLED_MESSAGE)

            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                session = state.sessions.get(session_id)
                if session is None:
                    raise KeyError(f"Session '{session_id}' not found.")

                if "title" in updates:
                    session["title"] = str(updates["title"]).strip()
                session["updated_at"] = utc_now()
                state.sessions[session_id] = session
                self._append_ephemeral_activity_locked(
                    state,
                    "session_updated",
                    {"session_id": session_id, "fields": list(updates.keys())},
                )
                return dict(session)

        # assert self._sessions

        assert self._sessions is not None

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

    def delete_session(self, session_id: str, client_id: str | None = None) -> list[dict[str, Any]]:
        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                state.sessions.pop(session_id, None)
                state.messages_by_session.pop(session_id, None)
                self._append_ephemeral_activity_locked(
                    state, "session_deleted", {"session_id": session_id}
                )
            return []

        # assert self._session_attachments and self._sessions and self._messages and self._session_chunks

        assert self._session_attachments is not None and self._sessions is not None and self._messages is not None and self._session_chunks is not None

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

    def delete_all_sessions(self, client_id: str | None = None) -> dict[str, Any]:
        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                counts = self._ephemeral_counts_locked(state)
                state.sessions.clear()
                state.messages_by_session.clear()
                self._append_ephemeral_activity_locked(
                    state, "sessions_cleared", {"session_count": counts["sessions"]}
                )
            return {
                "counts": {
                    "sessions": counts["sessions"],
                    "messages": counts["messages"],
                    "attachments": 0,
                    "session_chunks": 0,
                },
                "attachments": [],
                "session_ids": [],
            }

        # assert self._sessions and self._messages and self._session_attachments and self._session_chunks

        assert self._session_attachments is not None and self._sessions is not None and self._messages is not None and self._session_chunks is not None

        with self._lock:
            session_docs = list(self._sessions.find({}, {"session_id": 1}))
            session_ids = [doc.get("session_id", "") for doc in session_docs if doc.get("session_id")]
            attachments = [self._strip_id(doc) for doc in self._session_attachments.find({})]
            message_count = self._messages.count_documents({})
            attachment_count = len(attachments)
            session_chunk_count = self._session_chunks.count_documents({})
            session_count = len(session_ids)

            self._sessions.delete_many({})
            self._messages.delete_many({})
            self._session_attachments.delete_many({})
            self._session_chunks.delete_many({})
            self._append_activity_record(
                "sessions_cleared", {"session_count": session_count}
            )

        return {
            "counts": {
                "sessions": session_count,
                "messages": message_count,
                "attachments": attachment_count,
                "session_chunks": session_chunk_count,
            },
            "attachments": attachments,
            "session_ids": session_ids,
        }

    def flush_all_ephemeral(self) -> dict[str, Any]:
        with self._lock:
            client_count = len(self._ephemeral_clients)
            session_count = sum(len(state.sessions) for state in self._ephemeral_clients.values())
            message_count = sum(
                self._count_ephemeral_messages_locked(state)
                for state in self._ephemeral_clients.values()
            )
            self._ephemeral_clients.clear()

        logger.info(
            "Flushed Ephemeral RAM (%s client(s), %s session(s), %s message(s)).",
            client_count,
            session_count,
            message_count,
        )
        return {
            "clients": client_count,
            "sessions": session_count,
            "messages": message_count,
        }

    def add_message(
        self, session_id: str, role: str, text: str, client_id: str | None = None
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

        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                session = state.sessions.get(session_id)
                if session is None:
                    raise KeyError(f"Session '{session_id}' not found.")
                state.messages_by_session.setdefault(session_id, []).append(dict(doc))
                session["updated_at"] = now
                state.sessions[session_id] = session
            return dict(doc)

        # assert self._messages and self._sessions

        assert self._messages is not None and self._sessions is not None

        with self._lock:
            self._messages.insert_one(doc)
            self._sessions.update_one(
                {"session_id": session_id},
                {"$set": {"updated_at": now}},
            )
        return self._strip_id(doc)

    def get_messages(
        self, session_id: str, limit: int = 0, client_id: str | None = None
    ) -> list[dict[str, Any]]:
        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                docs = list(state.messages_by_session.get(session_id, []))
            docs.sort(key=lambda item: item.get("created_at", ""))
            if limit > 0:
                docs = docs[:limit]
            return [dict(doc) for doc in docs]

        # assert self._messages

        assert self._messages is not None

        with self._lock:
            cursor = self._messages.find({"session_id": session_id}).sort(
                "created_at", ASCENDING
            )
            if limit > 0:
                cursor = cursor.limit(limit)
            docs = list(cursor)
        return [self._strip_id(d) for d in docs]

    def delete_message(self, message_id: str, client_id: str | None = None) -> None:
        if self.is_ephemeral:
            with self._lock:
                state = self._get_ephemeral_client_locked(client_id)
                for session_id, messages in state.messages_by_session.items():
                    state.messages_by_session[session_id] = [
                        message for message in messages if message.get("message_id") != message_id
                    ]
            return

        # assert self._messages

        assert self._messages is not None

        with self._lock:
            self._messages.delete_one({"message_id": message_id})

    def get_knowledge_file_hashes(self) -> dict[str, str]:
        if self.is_ephemeral:
            with self._lock:
                return {
                    source_file: chunks[0]["file_hash"]
                    for source_file, chunks in self._knowledge_chunks_ram.items()
                    if chunks
                }

        # assert self._knowledge_chunks

        assert self._knowledge_chunks is not None

        with self._lock:
            pipeline = [
                {"$group": {"_id": "$source_file", "hash": {"$first": "$file_hash"}}},
            ]
            results = list(self._knowledge_chunks.aggregate(pipeline))
        return {r["_id"]: r["hash"] for r in results}

    def store_knowledge_chunks(
        self, source_file: str, file_hash: str, chunks: list[dict[str, Any]]
    ) -> int:
        now = utc_now()
        if self.is_ephemeral:
            docs = [
                {
                    "chunk_id": uuid.uuid4().hex[:12],
                    "source_file": source_file,
                    "file_hash": file_hash,
                    "chunk_index": index,
                    "text": chunk["text"],
                    "metadata": chunk.get("metadata", {}),
                    "created_at": now,
                }
                for index, chunk in enumerate(chunks)
            ]
            with self._lock:
                self._knowledge_chunks_ram[source_file] = docs
            return len(docs)

        # assert self._knowledge_chunks

        assert self._knowledge_chunks is not None

        with self._lock:
            self._knowledge_chunks.delete_many({"source_file": source_file})
            docs = [
                {
                    "chunk_id": uuid.uuid4().hex[:12],
                    "source_file": source_file,
                    "file_hash": file_hash,
                    "chunk_index": index,
                    "text": chunk["text"],
                    "metadata": chunk.get("metadata", {}),
                    "created_at": now,
                }
                for index, chunk in enumerate(chunks)
            ]
            if docs:
                self._knowledge_chunks.insert_many(docs)
        return len(docs)

    def get_all_knowledge_chunks(self) -> list[dict[str, Any]]:
        if self.is_ephemeral:
            with self._lock:
                docs: list[dict[str, Any]] = []
                for chunk_group in self._knowledge_chunks_ram.values():
                    docs.extend(chunk_group)
            docs.sort(key=lambda doc: (doc.get("source_file", ""), doc.get("chunk_index", 0)))
            return [dict(doc) for doc in docs]

        # assert self._knowledge_chunks

        assert self._knowledge_chunks is not None

        with self._lock:
            docs = list(
                self._knowledge_chunks.find().sort(
                    [("source_file", ASCENDING), ("chunk_index", ASCENDING)]
                )
            )
        return [self._strip_id(d) for d in docs]

    def delete_knowledge_file(self, source_file: str) -> None:
        if self.is_ephemeral:
            with self._lock:
                self._knowledge_chunks_ram.pop(source_file, None)
            return

        # assert self._knowledge_chunks

        assert self._knowledge_chunks is not None

        with self._lock:
            self._knowledge_chunks.delete_many({"source_file": source_file})

    def clear_all_knowledge_chunks(self) -> int:
        if self.is_ephemeral:
            with self._lock:
                count = sum(len(chunks) for chunks in self._knowledge_chunks_ram.values())
                self._knowledge_chunks_ram.clear()
            return count

        # assert self._knowledge_chunks

        assert self._knowledge_chunks is not None

        with self._lock:
            count = self._knowledge_chunks.count_documents({})
            self._knowledge_chunks.drop()
        self._ensure_indexes()
        return count

    def add_session_attachment(
        self,
        session_id: str,
        filename: str,
        file_type: str,
        file_size: int,
        storage_path: str,
    ) -> dict[str, Any]:
        if self.is_ephemeral:
            raise MemoryDisabledError(MEMORY_DISABLED_MESSAGE)

        # assert self._session_attachments

        assert self._session_attachments is not None

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
        if self.is_ephemeral:
            return []

        # assert self._session_attachments

        assert self._session_attachments is not None

        with self._lock:
            docs = list(
                self._session_attachments.find({"session_id": session_id}).sort("created_at", ASCENDING)
            )
        return [self._strip_id(d) for d in docs]

    def delete_session_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        if self.is_ephemeral:
            return None

        # assert self._session_attachments and self._session_chunks

        assert self._session_attachments is not None and self._session_chunks is not None

        with self._lock:
            doc = self._session_attachments.find_one({"attachment_id": attachment_id})
            if doc is None:
                return None
            self._session_attachments.delete_one({"_id": doc["_id"]})
            self._session_chunks.delete_many({"attachment_id": attachment_id})
        return self._strip_id(doc)

    def store_session_chunks(
        self, session_id: str, attachment_id: str, chunks: list[dict[str, Any]]
    ) -> int:
        if self.is_ephemeral:
            raise MemoryDisabledError(MEMORY_DISABLED_MESSAGE)

        # assert self._session_chunks

        assert self._session_chunks is not None

        now = utc_now()
        with self._lock:
            docs = [
                {
                    "chunk_id": uuid.uuid4().hex[:12],
                    "attachment_id": attachment_id,
                    "session_id": session_id,
                    "chunk_index": index,
                    "text": chunk["text"],
                    "metadata": chunk.get("metadata", {}),
                    "created_at": now,
                }
                for index, chunk in enumerate(chunks)
            ]
            if docs:
                self._session_chunks.insert_many(docs)
        return len(docs)

    def get_session_chunks(self, session_id: str) -> list[dict[str, Any]]:
        if self.is_ephemeral:
            return []

        # assert self._session_chunks

        assert self._session_chunks is not None

        with self._lock:
            docs = list(
                self._session_chunks.find({"session_id": session_id}).sort(
                    [("attachment_id", ASCENDING), ("chunk_index", ASCENDING)]
                )
            )
        return [self._strip_id(d) for d in docs]

    def _append_activity_record(
        self, kind: str, payload: dict[str, Any] | None = None
    ) -> None:
        if self.is_ephemeral:
            return

        # assert self._activity

        assert self._activity is not None

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
                self._activity.delete_many({"_id": {"$in": [doc["_id"] for doc in excess]}})

    @classmethod
    def migrate_from_json(
        cls,
        json_path: str | Path,
        history_path: str | Path | None = None,
        mongodb_uri: str = "mongodb://localhost:27017",
        db_name: str = "orbit_assistant",
    ) -> "MemoryStore":
        store = cls(mongodb_uri=mongodb_uri, db_name=db_name, mode="mongo")
        json_file = Path(json_path)

        if not json_file.exists():
            logger.info("No legacy JSON file found at %s -- skipping migration.", json_file)
            return store

        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read legacy JSON (%s): %s", json_file, exc)
            return store

        # assert store._profile and store._notes and store._tasks and store._activity and store._cache

        assert store._profile is not None and store._notes is not None and store._tasks is not None and store._activity is not None and store._cache is not None

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

        for note in profile.get("notes", []):
            note_id = note.get("id", uuid.uuid4().hex[:8])
            if store._notes.find_one({"note_id": note_id}) is None:
                store._notes.insert_one(
                    {
                        "note_id": note_id,
                        "category": note.get("category", "note"),
                        "text": note.get("text", ""),
                        "created_at": note.get("created_at", utc_now()),
                    }
                )

        for task in data.get("tasks", []):
            task_id = task.get("id", uuid.uuid4().hex[:8])
            if store._tasks.find_one({"task_id": task_id}) is None:
                store._tasks.insert_one(
                    {
                        "task_id": task_id,
                        "title": task.get("title", ""),
                        "priority": task.get("priority", "medium"),
                        "due_date": task.get("due_date", ""),
                        "status": task.get("status", "open"),
                        "created_at": task.get("created_at", utc_now()),
                        "completed_at": task.get("completed_at", ""),
                    }
                )

        for activity in data.get("activity", []):
            activity_id = activity.get("id", uuid.uuid4().hex[:8])
            if store._activity.find_one({"activity_id": activity_id}) is None:
                store._activity.insert_one(
                    {
                        "activity_id": activity_id,
                        "kind": activity.get("kind", ""),
                        "payload": activity.get("payload", {}),
                        "created_at": activity.get("created_at", utc_now()),
                    }
                )

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

        if history_path:
            history_file = Path(history_path)
            if history_file.exists() and history_file.stat().st_size > 2:
                try:
                    history = json.loads(history_file.read_text(encoding="utf-8"))
                    if isinstance(history, list) and history:
                        store.update_history(history)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Could not read legacy chat history (%s): %s", history_file, exc)

        logger.info("Legacy JSON data migrated successfully from %s", json_file)
        return store