from __future__ import annotations

import base64
import os
import dataclasses
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import Settings, get_settings
from .api_clients.llm_client import LLMAssistant, LLMClientError
from .core.memory_store import MemoryStore
from .tools.news import NewsError, NewsService
from .tools.weather import WeatherError, WeatherService
from .tools.web_search import WebSearchService
from .tools.knowledge import KnowledgeService


class AssistantApplication:
    def __init__(self, settings: Settings, rag_path: str | None = None) -> None:
        self.settings = settings

        # --- MongoDB-backed MemoryStore with auto-migration ---
        legacy_json = settings.data_dir / "assistant_memory.json"
        legacy_history = settings.data_dir / "chat_history.json"

        if legacy_json.exists():
            print("[*] Legacy JSON files detected -- migrating to MongoDB...")
            self.memory_store = MemoryStore.migrate_from_json(
                json_path=legacy_json,
                history_path=legacy_history if legacy_history.exists() else None,
                mongodb_uri=settings.mongodb_uri,
                db_name=settings.mongodb_db,
            )
            # Rename legacy files so migration doesn't run again.
            legacy_json.rename(legacy_json.with_suffix(".json.bak"))
            if legacy_history.exists():
                legacy_history.rename(legacy_history.with_suffix(".json.bak"))
            print("[*] Migration complete. Legacy files renamed to .json.bak")
        else:
            self.memory_store = MemoryStore(
                mongodb_uri=settings.mongodb_uri,
                db_name=settings.mongodb_db,
            )

        # --- Knowledge service (always created; RAG requires docs_dir) ---
        upload_dir = str(settings.data_dir / "uploads")
        self.knowledge = KnowledgeService(
            memory_store=self.memory_store,
            docs_dir=rag_path,
            upload_dir=upload_dir,
        )

        self.web_search = WebSearchService()

        self.assistant = LLMAssistant(settings, self.memory_store, self.knowledge, self.web_search)
        self.weather = WeatherService(settings.default_location)
        self.news = NewsService()

    def handler(self) -> type[BaseHTTPRequestHandler]:
        app = self

        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                app.handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                app.handle_post(self)

            def do_PUT(self) -> None:  # noqa: N802
                app.handle_put(self)

            def do_DELETE(self) -> None:  # noqa: N802
                app.handle_delete(self)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        return RequestHandler

    def handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        path = parsed.path

        # --- Frontend file serving (new directory layout) ---
        if path in {"/", "/index.html"}:
            self._serve_file(handler, self.settings.web_dir / "index.html")
            return
        if path == "/styles.css":
            self._serve_file(handler, self.settings.web_dir / "assets" / "styles.css")
            return
        if path == "/app.js":
            self._serve_file(handler, self.settings.web_dir / "scripts" / "app.js")
            return
        if path == "/avatar-worker.js":
            self._serve_file(handler, self.settings.web_dir / "scripts" / "avatar-worker.js")
            return
        if path == "/avatar-renderer.js":
            self._serve_file(handler, self.settings.web_dir / "scripts" / "avatar-renderer.js")
            return
        
        if path == "/api/state":
            self._send_json(handler, self._state_payload())
            return

        # --- Session endpoints (GET) ---
        if path == "/api/sessions":
            query = parse_qs(parsed.query)
            include_archived = (query.get("include_archived") or ["false"])[0].lower() == "true"
            sessions = self.memory_store.get_sessions(include_archived=include_archived)
            self._send_json(handler, {"sessions": sessions})
            return

        if path.startswith("/api/sessions/") and "/messages" not in path:
            session_id = path.split("/api/sessions/", 1)[1].strip("/")
            if session_id:
                session = self.memory_store.get_session(session_id)
                if session is None:
                    self._send_json(handler, {"error": "Session not found."}, status=HTTPStatus.NOT_FOUND)
                else:
                    self._send_json(handler, {"session": session})
                return

        if path.startswith("/api/sessions/") and path.endswith("/messages"):
            session_id = path.replace("/api/sessions/", "").replace("/messages", "").strip("/")
            if session_id:
                query = parse_qs(parsed.query)
                limit = int((query.get("limit") or ["0"])[0])
                messages = self.memory_store.get_messages(session_id, limit=limit)
                self._send_json(handler, {"messages": messages})
                return

        # GET /api/sessions/<session_id>/attachments
        if path.startswith("/api/sessions/") and path.endswith("/attachments"):
            session_id = path.replace("/api/sessions/", "").replace("/attachments", "").strip("/")
            if session_id:
                attachments = self.memory_store.get_session_attachments(session_id)
                self._send_json(handler, {"attachments": attachments})
                return
        
        if path == "/api/weather":
            query = parse_qs(parsed.query)
            location = (query.get("location") or [""])[0]
            try:
                weather = self.weather.fetch_weather(location)
                self.memory_store.set_last_weather(weather)
                self._send_json(handler, {"weather": weather, "memory": self.memory_store.get_state()})
            except WeatherError as exc:
                self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/news":
            query = parse_qs(parsed.query)
            topic = (query.get("topic") or [""])[0]
            try:
                news = self.news.fetch_news(topic)
                self.memory_store.set_last_news(news)
                self._send_json(handler, {"news": news, "memory": self.memory_store.get_state()})
            except NewsError as exc:
                self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        

        self._send_json(handler, {"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)

        if parsed.path == "/api/history":
            payload = self._read_json_body(handler)
            history = payload if isinstance(payload, list) else payload.get("history", [])
            session_id = payload.get("sessionId") if isinstance(payload, dict) else None
            self.memory_store.update_history(history, session_id=session_id)
            self._send_json(handler, {"status": "success"})
            return

        payload = self._read_json(handler)

        # --- Session endpoints (POST) ---
        if parsed.path == "/api/sessions":
            session = self.memory_store.create_session(title=payload.get("title"))
            self._send_json(handler, {"ok": True, "session": session})
            return

        # --- Message endpoints (POST) ---
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/messages"):
            session_id = parsed.path.replace("/api/sessions/", "").replace("/messages", "").strip("/")
            if session_id:
                try:
                    message = self.memory_store.add_message(
                        session_id=session_id,
                        role=payload.get("role", "user"),
                        text=payload.get("text", ""),
                    )
                except ValueError as exc:
                    self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(handler, {"ok": True, "message": message})
                return

        # --- Attachment upload (POST /api/sessions/<id>/attachments) ---
        if parsed.path.startswith("/api/sessions/") and parsed.path.endswith("/attachments"):
            session_id = parsed.path.replace("/api/sessions/", "").replace("/attachments", "").strip("/")
            if session_id:
                self._handle_attachment_upload(handler, payload, session_id)
                return

        if parsed.path == "/api/chat":
            self._handle_chat(handler, payload)
            return
        if parsed.path == "/api/profile":
            snapshot = self.memory_store.update_profile(
                display_name=payload.get("displayName"),
                location=payload.get("location"),
                routine=payload.get("routine"),
            )
            self._send_json(handler, {"ok": True, "snapshot": snapshot, "memory": self.memory_store.get_state()})
            return
        if parsed.path == "/api/tasks":
            try:
                task = self.memory_store.add_task(
                    title=payload.get("title", ""),
                    priority=payload.get("priority", "medium"),
                    due_date=payload.get("dueDate"),
                )
            except ValueError as exc:
                self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(handler, {"ok": True, "task": task, "memory": self.memory_store.get_state()})
            return
        if parsed.path == "/api/tasks/complete":
            try:
                task = self.memory_store.complete_task(payload.get("taskRef", ""))
            except KeyError as exc:
                self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(handler, {"ok": True, "task": task, "memory": self.memory_store.get_state()})
            return

        if parsed.path == "/api/notes":
            try:
                note = self.memory_store.remember_note(
                    note=payload.get("text", ""),
                    category=payload.get("category", "note"),
                )
            except ValueError as exc:
                self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(handler, {"ok": True, "note": note, "memory": self.memory_store.get_state()})
            return

        # --- Phase 5: Graceful fallback for unsupported POST endpoints ---
        if parsed.path in {"/api/generate-image"}:
            self._send_json(handler, {
                "reply": self._UNSUPPORTED_REFUSAL,
                "toolEvents": [],
                "memory": self.memory_store.get_state(),
                "model": self.settings.ai_model,
            })
            return

        self._send_json(handler, {"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------------
    # Unsupported-feature refusal message (Phase 5: Graceful Fallbacks)
    # ------------------------------------------------------------------

    _UNSUPPORTED_REFUSAL = (
        "Sorry, I don't have this function. "
        "If you want to use this, please use other LLMs that are available for them."
    )

    def _handle_chat(self, handler: BaseHTTPRequestHandler, payload: dict[str, Any]) -> None:
        message = (payload.get("message") or "").strip()
        if not message:
            self._send_json(handler, {"error": "Message cannot be empty."}, status=HTTPStatus.BAD_REQUEST)
            return

        # --- Phase 5: Graceful fallbacks for unsupported features ---
        # Image generation toggle
        if payload.get("imageGen"):
            self._send_json(handler, {
                "reply": self._UNSUPPORTED_REFUSAL,
                "toolEvents": [],
                "memory": self.memory_store.get_state(),
                "model": self.settings.ai_model,
            })
            return

        session_id = (payload.get("sessionId") or "").strip() or None

        try:
            result = self.assistant.chat(
                message=message,
                conversation=payload.get("conversation") or [],
                screen_image=payload.get("screenImage"),
                mode=(payload.get("mode") or "simple").strip().lower(),
                coach_topic=(payload.get("coachTopic") or "General Learning").strip(), 
                coach_level=(payload.get("coachLevel") or "Beginner").strip(),         
                preferred_language=(payload.get("preferredLanguage") or "default").strip() or "default",
                web_search_only=bool(payload.get("webSearchOnly", False)),
                offline_mode=bool(payload.get("offlineMode", False)),
                session_id=session_id,
            )
        except LLMClientError as exc:
            self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        self._send_json(
            handler,
            {
                "reply": result.reply,
                "toolEvents": result.tool_events,
                "memory": self.memory_store.get_state(),
                "model": self.settings.ai_model,
            },
        )

    # ------------------------------------------------------------------
    # Attachment upload
    # ------------------------------------------------------------------

    _ALLOWED_ATTACH_TYPES = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".json"}
    _MAX_ATTACH_SIZE = 20 * 1024 * 1024  # 20 MB

    def _handle_attachment_upload(
        self, handler: BaseHTTPRequestHandler, payload: dict[str, Any], session_id: str
    ) -> None:
        """Accept a base64-encoded file, save to disk, parse and index for search."""
        filename = (payload.get("filename") or "").strip()
        file_data_b64 = (payload.get("data") or "").strip()

        if not filename or not file_data_b64:
            self._send_json(handler, {"error": "Missing filename or data."}, status=HTTPStatus.BAD_REQUEST)
            return

        ext = os.path.splitext(filename)[1].lower()
        if ext not in self._ALLOWED_ATTACH_TYPES:
            self._send_json(
                handler,
                {"error": f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(self._ALLOWED_ATTACH_TYPES))}"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            file_bytes = base64.b64decode(file_data_b64)
        except Exception:
            self._send_json(handler, {"error": "Invalid base64 data."}, status=HTTPStatus.BAD_REQUEST)
            return

        if len(file_bytes) > self._MAX_ATTACH_SIZE:
            self._send_json(
                handler,
                {"error": f"File too large. Maximum size is {self._MAX_ATTACH_SIZE // (1024*1024)} MB."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        # Save to disk
        upload_dir = self.knowledge.upload_dir
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = f"{session_id}_{filename}"
        disk_path = os.path.join(upload_dir, safe_name)
        with open(disk_path, "wb") as f:
            f.write(file_bytes)

        # Register in MongoDB
        attachment = self.memory_store.add_session_attachment(
            session_id=session_id,
            filename=filename,
            file_type=ext,
            file_size=len(file_bytes),
            storage_path=disk_path,
        )

        # Parse and index the file for session-scoped search
        try:
            chunk_count = self.knowledge.index_session_file(
                session_id=session_id,
                attachment_id=attachment["attachment_id"],
                file_path=disk_path,
                filename=filename,
            )
            attachment["chunk_count"] = chunk_count
        except ValueError as exc:
            # File saved but parsing failed -- still keep the attachment record
            attachment["parse_error"] = str(exc)

        self._send_json(handler, {"ok": True, "attachment": attachment})

    # ------------------------------------------------------------------
    # PUT  (session updates)
    # ------------------------------------------------------------------

    def handle_put(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        payload = self._read_json(handler)

        # PUT /api/sessions/<session_id>
        if parsed.path.startswith("/api/sessions/"):
            session_id = parsed.path.replace("/api/sessions/", "").strip("/")
            if session_id:
                kwargs: dict[str, Any] = {}
                if "title" in payload:
                    kwargs["title"] = payload["title"]
                if "pinned" in payload:
                    kwargs["pinned"] = payload["pinned"]
                if "archived" in payload:
                    kwargs["archived"] = payload["archived"]
                try:
                    session = self.memory_store.update_session(session_id, **kwargs)
                except (KeyError, ValueError) as exc:
                    self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(handler, {"ok": True, "session": session})
                return

        self._send_json(handler, {"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------------
    # DELETE  (session / message deletion)
    # ------------------------------------------------------------------

    def handle_delete(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)

        # DELETE /api/sessions/<session_id>
        if parsed.path.startswith("/api/sessions/") and "/messages/" not in parsed.path and "/attachments/" not in parsed.path:
            session_id = parsed.path.replace("/api/sessions/", "").strip("/")
            if session_id:
                attachments = self.memory_store.delete_session(session_id)
                self.knowledge.cleanup_session(session_id)
                # Clean up uploaded files from disk
                for att in attachments:
                    disk_path = att.get("storage_path", "")
                    if disk_path and os.path.isfile(disk_path):
                        try:
                            os.remove(disk_path)
                        except OSError:
                            pass
                self._send_json(handler, {"ok": True})
                return

        # DELETE /api/sessions/<session_id>/attachments/<attachment_id>
        if "/attachments/" in parsed.path and parsed.path.startswith("/api/sessions/"):
            # e.g. /api/sessions/abc123/attachments/def456
            parts = parsed.path.replace("/api/sessions/", "").strip("/").split("/attachments/")
            if len(parts) == 2:
                session_id, attachment_id = parts[0], parts[1]
                if session_id and attachment_id:
                    att_doc = self.memory_store.delete_session_attachment(attachment_id)
                    if att_doc:
                        disk_path = att_doc.get("storage_path", "")
                        if disk_path and os.path.isfile(disk_path):
                            try:
                                os.remove(disk_path)
                            except OSError:
                                pass
                        # Invalidate session retriever cache
                        self.knowledge.cleanup_session(session_id)
                    self._send_json(handler, {"ok": True})
                    return

        # DELETE /api/messages/<message_id>
        if parsed.path.startswith("/api/messages/"):
            message_id = parsed.path.replace("/api/messages/", "").strip("/")
            if message_id:
                self.memory_store.delete_message(message_id)
                self._send_json(handler, {"ok": True})
                return

        # DELETE /api/notes/<note_id>
        if parsed.path.startswith("/api/notes/"):
            note_id = parsed.path.replace("/api/notes/", "").strip("/")
            if note_id:
                try:
                    self.memory_store.delete_note(note_id)
                except KeyError as exc:
                    self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(handler, {"ok": True, "memory": self.memory_store.get_state()})
                return

        # DELETE /api/tasks/<task_id>
        if parsed.path.startswith("/api/tasks/") and parsed.path != "/api/tasks/complete":
            task_id = parsed.path.replace("/api/tasks/", "").strip("/")
            if task_id:
                try:
                    self.memory_store.delete_task(task_id)
                except KeyError as exc:
                    self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(handler, {"ok": True, "memory": self.memory_store.get_state()})
                return

        self._send_json(handler, {"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------------
    # State payload  (now reads from MongoDB, no more JSON file I/O)
    # ------------------------------------------------------------------

    def _state_payload(self) -> dict[str, Any]:
        state = self.memory_store.get_state()
        history = self.memory_store.get_history()
        sessions = self.memory_store.get_sessions(include_archived=True)

        return {
            "provider": self.settings.provider_name,
            "hasApiKey": bool(self.settings.current_api_key),
            "model": self.settings.ai_model,
            "defaultLocation": self.settings.default_location,
            "liveVoiceName": self.settings.live_voice_name,
            "memory": state,
            "history": history,
            "sessions": sessions,
        }

    def _serve_file(self, handler: BaseHTTPRequestHandler, file_path: Path) -> None:
        if not file_path.exists():
            self._send_json(handler, {"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            return

        mime_type, _ = mimetypes.guess_type(str(file_path))
        body = file_path.read_bytes()
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", mime_type or "application/octet-stream")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _read_json(self, handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        content_length = int(handler.headers.get("Content-Length", "0"))
        raw_body = handler.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        return json.loads(raw_body or "{}")

    def _read_json_body(self, handler: BaseHTTPRequestHandler) -> Any:
        """Read the request body and parse as JSON.  Returns list or dict."""
        content_length = int(handler.headers.get("Content-Length", "0"))
        raw_body = handler.rfile.read(content_length).decode("utf-8") if content_length else "[]"
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError:
            return []

    def _send_json(
        self,
        handler: BaseHTTPRequestHandler,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        try:
            handler.send_response(status)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
        except ConnectionAbortedError:
            pass


def run() -> None:
    settings = get_settings()

    print("==================================================")
    print("      ORBIT VIRTUAL ASSISTANT")
    print("==================================================")

    print(f"Current default provider in .env: {settings.provider_name.upper()}")
    print("Select AI Provider:")
    print("  1: Google (Gemini)")
    print("  2: OpenRouter")
    print("  3: LM Studio (Local)")
    print("  4: Ollama (Local)")
    p_choice = input("Choice [Press Enter for default]: ").strip()

    if p_choice == "1":
        settings = dataclasses.replace(settings, active_provider="google", ai_model=os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"))
    elif p_choice == "2":
        settings = dataclasses.replace(settings, active_provider="openrouter", ai_model=os.getenv("OPENROUTER_MODEL", settings.ai_model))
    elif p_choice == "3":
        settings = dataclasses.replace(settings, active_provider="lm_studio", ai_model=os.getenv("LM_STUDIO_MODEL", "local-model"))
    elif p_choice == "4":
        settings = dataclasses.replace(settings, active_provider="ollama", ai_model=os.getenv("OLLAMA_MODEL", "llama3.1"))

    print(f"--- Running with Provider: {settings.active_provider.upper()} ({settings.ai_model}) ---")

    use_rag = input("Do you want to enable RAG with local documents (RAG via LM Studio)? (y/n) [n]: ").strip().lower()

    rag_path = None
    if use_rag in ['y', 'yes']:
        default_path = settings.rag_docs_path or str(settings.root_dir / "knowledge_base")
        
        user_path = input(f"Enter the path to your local documents (default: {default_path}): ").strip()
        
        rag_path = user_path if user_path else default_path

        print(f"Connecting to LM Studio and initializing the Vector Database....")
        print(f"RAG will be enabled with documents from: {rag_path}")
    else:
        print("RAG will be disabled. The assistant will not have access to local documents.")

    app = AssistantApplication(settings, rag_path)
    server = ThreadingHTTPServer(("127.0.0.1", settings.assistant_port), app.handler())
    print(f"Orbit Assistant is running on http://127.0.0.1:{settings.assistant_port}")
    server.serve_forever()
