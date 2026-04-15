from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


DEFAULT_STATE: dict[str, Any] = {
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


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(DEFAULT_STATE)

    def _read(self) -> dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, data: dict[str, Any]) -> None:
        payload = deepcopy(data)
        payload["updated_at"] = utc_now()
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=True)

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read())

    def get_brief(self) -> dict[str, Any]:
        state = self.get_state()
        return self._build_brief(state)

    def _build_brief(self, state: dict[str, Any]) -> dict[str, Any]:
        open_tasks = [task for task in state["tasks"] if task["status"] == "open"]
        completed_tasks = [task for task in state["tasks"] if task["status"] == "done"]

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

    def update_profile(
        self,
        display_name: str | None = None,
        location: str | None = None,
        routine: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            if display_name is not None:
                state["profile"]["display_name"] = display_name.strip()
            if location is not None:
                state["profile"]["location"] = location.strip()
            if routine is not None:
                state["profile"]["routine"] = routine.strip()
            self._append_activity(state, "profile_updated", {"display_name": display_name, "location": location})
            self._write(state)
            return self._build_brief(state)

    def remember_note(self, note: str, category: str = "note") -> dict[str, Any]:
        cleaned_note = note.strip()
        if not cleaned_note:
            raise ValueError("Note text cannot be empty.")

        with self._lock:
            state = self._read()
            entry = {
                "id": uuid.uuid4().hex[:8],
                "category": (category or "note").strip().lower(),
                "text": cleaned_note,
                "created_at": utc_now(),
            }
            state["profile"]["notes"].append(entry)
            self._append_activity(state, "note_saved", entry)
            self._write(state)
            return entry

    def add_task(self, title: str, priority: str = "medium", due_date: str | None = None) -> dict[str, Any]:
        cleaned_title = title.strip()
        if not cleaned_title:
            raise ValueError("Task title cannot be empty.")

        with self._lock:
            state = self._read()
            task = {
                "id": uuid.uuid4().hex[:8],
                "title": cleaned_title,
                "priority": (priority or "medium").strip().lower(),
                "due_date": due_date.strip() if isinstance(due_date, str) and due_date.strip() else "",
                "status": "open",
                "created_at": utc_now(),
                "completed_at": "",
            }
            state["tasks"].append(task)
            self._append_activity(state, "task_added", task)
            self._write(state)
            return task

    def complete_task(self, task_ref: str) -> dict[str, Any]:
        reference = (task_ref or "").strip().lower()
        if not reference:
            raise KeyError("Task reference cannot be empty.")

        with self._lock:
            state = self._read()
            for task in state["tasks"]:
                if task["status"] != "open":
                    continue
                if task["id"].lower() == reference or reference in task["title"].lower():
                    task["status"] = "done"
                    task["completed_at"] = utc_now()
                    self._append_activity(state, "task_completed", {"id": task["id"], "title": task["title"]})
                    self._write(state)
                    return task
        raise KeyError(f"Could not find an open task matching '{task_ref}'.")

    def set_last_weather(self, weather: dict[str, Any]) -> None:
        with self._lock:
            state = self._read()
            state["last_weather"] = weather
            self._append_activity(state, "weather_checked", {"location": weather.get("location", "")})
            self._write(state)

    def set_last_news(self, news: dict[str, Any]) -> None:
        with self._lock:
            state = self._read()
            state["last_news"] = news
            self._append_activity(state, "news_checked", {"topic": news.get("topic", "")})
            self._write(state)

    def _append_activity(self, state: dict[str, Any], kind: str, payload: dict[str, Any] | None = None) -> None:
        state["activity"].append(
            {
                "id": uuid.uuid4().hex[:8],
                "kind": kind,
                "payload": payload or {},
                "created_at": utc_now(),
            }
        )
        state["activity"] = state["activity"][-20:]

    def update_history(self, chat_history: list[dict[str, str]]) -> None:
        history_path = self.path.parent / "chat_history.json"
        with self._lock:
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(chat_history, f, indent=2, ensure_ascii=False)