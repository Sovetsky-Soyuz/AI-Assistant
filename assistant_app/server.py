from __future__ import annotations

import os
import dataclasses
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from os import path
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import Settings, get_settings
# from .gemini_client import GeminiAssistant, GeminiClientError
from .llm_client import LLMAssistant, LLMClientError
from .memory_store import MemoryStore
from .news import NewsError, NewsService
from .weather import WeatherError, WeatherService
from .knowledge import KnowledgeService
from .web_search import WebSearchService


class AssistantApplication:
    def __init__(self, settings: Settings, rag_path: str | None = None) -> None:
        self.settings = settings
        self.memory_store = MemoryStore(settings.data_dir / "assistant_memory.json")

        if rag_path:
            from .knowledge import KnowledgeService
            self.knowledge = KnowledgeService(rag_path)
        else:
                self.knowledge = None

        self.web_search = WebSearchService()

        # self.knowledge = KnowledgeService(str(settings.root_dir / "Knowledge"))
        self.assistant = LLMAssistant(settings, self.memory_store, self.knowledge, self.web_search)
        # self.assistant = GeminiAssistant(settings, self.memory_store)
        # self.assistant = LLMAssistant(settings, self.memory_store)
        self.weather = WeatherService(settings.default_location)
        self.news = NewsService()

    def handler(self) -> type[BaseHTTPRequestHandler]:
        app = self

        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                app.handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                app.handle_post(self)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        return RequestHandler

    def handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        path = parsed.path

        if path in {"/", "/index.html"}:
            self._serve_file(handler, self.settings.web_dir / "index.html")
            return
        if path == "/styles.css":
            self._serve_file(handler, self.settings.web_dir / "styles.css")
            return
        if path == "/app.js":
            self._serve_file(handler, self.settings.web_dir / "app.js")
            return
        if path == "/avatar-worker.js":
            self._serve_file(handler, self.settings.web_dir / "avatar-worker.js")
            return
        
        if path == "/avatar-renderer.js":
            self._serve_file(handler, self.settings.web_dir / "avatar-renderer.js")
            return
        
        if path == "/api/state":
            self._send_json(handler, self._state_payload())
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
        payload = self._read_json(handler)

        if parsed.path == "/api/history":
            content_length = int(handler.headers.get("Content-Length", "0"))
            raw_body = handler.rfile.read(content_length).decode("utf-8") if content_length else "[]"
            
            try:
                payload = json.loads(raw_body)
                if not isinstance(payload, list):
                     payload = []
            except json.JSONDecodeError:
                payload = []

            self.memory_store.update_history(payload)
            self._send_json(handler, {"status": "success"})
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

        self._send_json(handler, {"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def _handle_chat(self, handler: BaseHTTPRequestHandler, payload: dict[str, Any]) -> None:
        message = (payload.get("message") or "").strip()
        if not message:
            self._send_json(handler, {"error": "Message cannot be empty."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            result = self.assistant.chat(
                message=message,
                conversation=payload.get("conversation") or [],
                screen_image=payload.get("screenImage"),
                mode=(payload.get("mode") or "simple").strip().lower(),
                coach_topic=(payload.get("coachTopic") or "General Learning").strip(), 
                coach_level=(payload.get("coachLevel") or "Beginner").strip(),         
                preferred_language=(payload.get("preferredLanguage") or "default").strip() or "default",
            )
        # except GeminiClientError as exc:
        #     self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
        #     return
        except LLMClientError as exc:
            self._send_json(handler, {"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        self._send_json(
            handler,
            {
                "reply": result.reply,
                "toolEvents": result.tool_events,
                "memory": self.memory_store.get_state(),
                # "model": self.settings.gemini_model,
                "model": self.settings.ai_model,
            },
        )

    # def _state_payload(self) -> dict[str, Any]:
    #     return {
    #         "provider": self.settings.provider_name,
    #         "hasApiKey": bool(self.settings.gemini_api_key),
    #         "model": self.settings.gemini_model,
    #         "defaultLocation": self.settings.default_location,
    #         "liveVoiceName": self.settings.live_voice_name,
    #         "memory": self.memory_store.get_state(),
    #     }

    # def _state_payload(self) -> dict[str, Any]:
    #     state = self.memory_store.get_state()
    #     history_path = self.settings.data_dir / "chat_history.json"

    #     history = []
    #     if history_path.exists():
    #         with open(history_path, "r", encoding="utf-8") as f:
    #             history = json.load(f)

    #     return {
    #         "provider": self.settings.provider_name,
    #         "hasApiKey": bool(self.settings.current_api_key),
    #         "model": self.settings.ai_model,
    #         "defaultLocation": self.settings.default_location,
    #         "liveVoiceName": self.settings.live_voice_name,
    #         "memory": self.memory_store.get_state(),
    #         "history": history,
    #     }

    def _state_payload(self) -> dict[str, Any]:
        state = self.memory_store.get_state()
        history_path = self.settings.data_dir / "chat_history.json"
        
        history = []
        if history_path.exists():
            try:
                # Kiểm tra nếu file có dung lượng > 0 mới đọc
                if history_path.stat().st_size > 0:
                    with open(history_path, "r", encoding="utf-8") as f:
                        history = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                print(f"[⚠️] Warning: Could not read chat_history.json ({e}). Resetting history.")
                history = []

        return {
            "provider": self.settings.provider_name,
            "hasApiKey": bool(self.settings.current_api_key),
            "model": self.settings.ai_model,
            "defaultLocation": self.settings.default_location,
            "liveVoiceName": self.settings.live_voice_name,
            "memory": state,
            "history": history,
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
        # default_path = str(settings.root_dir / "Knowledge")
        default_path = settings.rag_docs_path or str(settings.root_dir / "Knowledge")
        
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
