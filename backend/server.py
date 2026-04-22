from __future__ import annotations

import base64
import dataclasses
import os
from pathlib import Path
from typing import Any, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .api_clients.llm_client import LLMAssistant, LLMClientError
from .config import Settings, get_settings
from .core.memory_store import MemoryDisabledError, MemoryStore
from .tools.knowledge import KnowledgeService
from .tools.news import NewsError, NewsService
from .tools.weather import WeatherError, WeatherService
from .tools.web_search import WebSearchService

EPHEMERAL_CLIENT_HEADER = "X-Orbit-Ephemeral-Client"
ADMIN_TOKEN_HEADER = "X-Admin-Token"


class MissingEphemeralClientHeaderError(RuntimeError):
    """Raised when Ephemeral Mode requires a client token but it was not provided."""


class ChatRequest(BaseModel):
    message: str
    conversation: Optional[List[dict]] = []
    screenImage: Optional[str] = None
    mode: Optional[str] = "simple"
    coachTopic: Optional[str] = "General Learning"
    coachLevel: Optional[str] = "Beginner"
    preferredLanguage: Optional[str] = "default"
    webSearchOnly: Optional[bool] = False
    offlineMode: Optional[bool] = False
    sessionId: Optional[str] = None
    imageGen: Optional[bool] = False
    routingMode: Optional[str] = "fixed"
    providerOverride: Optional[str] = None
    modelOverride: Optional[str] = None
    useMemory: Optional[bool] = True


class SessionCreateRequest(BaseModel):
    title: Optional[str] = None
    firstMessage: Optional[str] = None


class SessionUpdateRequest(BaseModel):
    title: Optional[str] = None
    pinned: Optional[bool] = None
    archived: Optional[bool] = None


class AttachmentUpload(BaseModel):
    filename: str
    data: str


class ProfileUpdateRequest(BaseModel):
    displayName: Optional[str] = None
    location: Optional[str] = None
    routine: Optional[str] = None
    timezone: Optional[str] = None
    dateOfBirth: Optional[str] = None
    occupation: Optional[str] = None
    interests: Optional[str] = None
    preferredTone: Optional[str] = None
    bio: Optional[str] = None


class TaskCreateRequest(BaseModel):
    title: str
    priority: Optional[str] = "medium"
    dueDate: Optional[str] = None


class TaskCompleteRequest(BaseModel):
    taskRef: str


class NoteCreateRequest(BaseModel):
    text: str
    category: Optional[str] = "note"


app = FastAPI(title="Orbit Virtual Assistant API")
settings = get_settings()

memory_store: MemoryStore | None = None
knowledge: KnowledgeService | None = None
web_search: WebSearchService | None = None
assistant: LLMAssistant | None = None
weather_svc: WeatherService | None = None
news_svc: NewsService | None = None


@app.exception_handler(MemoryDisabledError)
async def handle_memory_disabled(_: Request, exc: MemoryDisabledError) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"code": "memory_disabled", "detail": str(exc)},
    )


@app.exception_handler(MissingEphemeralClientHeaderError)
async def handle_missing_ephemeral_client(_: Request, exc: MissingEphemeralClientHeaderError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": "missing_ephemeral_client", "detail": str(exc)},
    )


def init_services(
    current_settings: Settings,
    rag_path: str | None = None,
    storage_mode: str = "mongo",
) -> None:
    global memory_store, knowledge, web_search, assistant, weather_svc, news_svc, settings
    settings = current_settings

    storage_mode = "ephemeral" if storage_mode == "ephemeral" else "mongo"
    legacy_json = settings.data_dir / "assistant_memory.json"
    legacy_history = settings.data_dir / "chat_history.json"

    if storage_mode == "mongo" and legacy_json.exists():
        print("[*] Legacy JSON files detected -- migrating to MongoDB...")
        memory_store = MemoryStore.migrate_from_json(
            json_path=legacy_json,
            history_path=legacy_history if legacy_history.exists() else None,
            mongodb_uri=settings.mongodb_uri,
            db_name=settings.mongodb_db,
        )
        legacy_json.rename(legacy_json.with_suffix(".json.bak"))
        if legacy_history.exists():
            legacy_history.rename(legacy_history.with_suffix(".json.bak"))
    else:
        # memory_store = MemoryStore(
        #     mongodb_uri=settings.mongodb_uri,
        #     db_name=settings.mongodb_db,
        #     mode=storage_mode,
        # )

        try:
            memory_store = MemoryStore(
                mongodb_uri=settings.mongodb_uri,
                db_name=settings.mongodb_db,
                mode=storage_mode,
            )
        except Exception as e:
            print("[WARNING] MongoDB is not available. Switching to Ephemeral Mode.")
            print(f"Reason: {e}")
            memory_store = MemoryStore(
                mongodb_uri=settings.mongodb_uri,
                db_name=settings.mongodb_db,
                mode="ephemeral",
            )

    knowledge = KnowledgeService(
        memory_store=memory_store,
        docs_dir=rag_path,
        upload_dir=str(settings.data_dir / "uploads"),
    )
    web_search = WebSearchService()
    assistant = LLMAssistant(settings, memory_store, knowledge, web_search)
    weather_svc = WeatherService(settings.default_location)
    news_svc = NewsService()


def get_ephemeral_client_id(request: Request, *, required: bool = False) -> str | None:
    if not memory_store or not memory_store.is_ephemeral:
        return None

    client_id = request.headers.get(EPHEMERAL_CLIENT_HEADER, "").strip()
    if required and not client_id:
        raise MissingEphemeralClientHeaderError(
            f"Missing {EPHEMERAL_CLIENT_HEADER} header."
        )
    return client_id or None


def require_admin_token(request: Request) -> None:
    expected = (settings.admin_token or "").strip()
    provided = request.headers.get(ADMIN_TOKEN_HEADER, "").strip()

    if not expected:
        raise HTTPException(status_code=403, detail="ADMIN_TOKEN is not configured.")
    if provided != expected:
        raise HTTPException(status_code=403, detail="Invalid admin token.")


def cleanup_attachment_files(attachments: list[dict[str, Any]]) -> None:
    for attachment in attachments:
        path = attachment.get("storage_path")
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


@app.get("/api/state")
async def get_state(request: Request, include_memory: bool = True) -> dict[str, Any]:
    client_id = get_ephemeral_client_id(request, required=True)
    allow_memory = include_memory and bool(memory_store and memory_store.supports_persistent_memory)

    return {
        "provider": settings.provider_name,
        "hasApiKey": bool(settings.current_api_key),
        "model": settings.ai_model,
        "defaultLocation": settings.default_location,
        "liveVoiceName": settings.live_voice_name,
        "memory": memory_store.get_state(client_id=client_id) if allow_memory else None,
        "history": memory_store.get_history(client_id=client_id) if allow_memory else [],
        "sessions": memory_store.get_sessions(include_archived=True, client_id=client_id),
        "enableHybrid": getattr(settings, "enable_hybrid", False),
        "storageMode": memory_store.storage_mode,
        "memoryAvailable": memory_store.supports_persistent_memory,
    }


@app.get("/api/sessions")
async def get_sessions(request: Request, include_archived: bool = False) -> dict[str, Any]:
    client_id = get_ephemeral_client_id(request, required=True)
    return {"sessions": memory_store.get_sessions(include_archived, client_id=client_id)}


@app.post("/api/sessions")
async def create_session(request: Request, payload: SessionCreateRequest) -> dict[str, Any]:
    client_id = get_ephemeral_client_id(request, required=True)
    title = payload.title
    if payload.firstMessage and not title:
        try:
            title = assistant.generate_title(payload.firstMessage)
        except Exception:
            title = "New Chat"
    session = memory_store.create_session(title=title or "New Chat", client_id=client_id)
    return {"ok": True, "session": session}


@app.delete("/api/sessions")
async def delete_all_sessions(request: Request) -> dict[str, Any]:
    client_id = get_ephemeral_client_id(request, required=True)
    result = memory_store.delete_all_sessions(client_id=client_id)
    for session_id in result.get("session_ids", []):
        knowledge.cleanup_session(session_id)
    cleanup_attachment_files(result.get("attachments", []))
    return {"ok": True, "counts": result.get("counts", {})}


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(request: Request, session_id: str, limit: int = 0) -> dict[str, Any]:
    client_id = get_ephemeral_client_id(request, required=True)
    return {"messages": memory_store.get_messages(session_id, limit, client_id=client_id)}


@app.post("/api/sessions/{session_id}/messages")
async def add_message(request: Request, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    client_id = get_ephemeral_client_id(request, required=True)
    try:
        message = memory_store.add_message(
            session_id=session_id,
            role=payload.get("role", "user"),
            text=payload.get("text", ""),
            client_id=client_id,
        )
        return {"ok": True, "message": message}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/sessions/{session_id}")
async def update_session(
    request: Request, session_id: str, payload: SessionUpdateRequest
) -> dict[str, Any]:
    client_id = get_ephemeral_client_id(request, required=True)
    kwargs: dict[str, Any] = {}
    if payload.title is not None:
        kwargs["title"] = payload.title
    if payload.pinned is not None:
        kwargs["pinned"] = payload.pinned
    if payload.archived is not None:
        kwargs["archived"] = payload.archived

    try:
        session = memory_store.update_session(session_id, client_id=client_id, **kwargs)
        return {"ok": True, "session": session}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/sessions/{session_id}")
async def delete_session(request: Request, session_id: str) -> dict[str, Any]:
    client_id = get_ephemeral_client_id(request, required=True)
    attachments = memory_store.delete_session(session_id, client_id=client_id)
    knowledge.cleanup_session(session_id)
    cleanup_attachment_files(attachments)
    return {"ok": True}


@app.post("/api/profile")
async def save_profile(payload: ProfileUpdateRequest) -> dict[str, Any]:
    try:
        memory_store.update_profile(
            display_name=payload.displayName,
            location=payload.location,
            routine=payload.routine,
            timezone=payload.timezone,
            date_of_birth=payload.dateOfBirth,
            occupation=payload.occupation,
            interests=payload.interests,
            preferred_tone=payload.preferredTone,
            bio=payload.bio,
        )
        return {"ok": True, "memory": memory_store.get_state()}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/tasks")
async def create_task(payload: TaskCreateRequest) -> dict[str, Any]:
    try:
        memory_store.add_task(
            title=payload.title,
            priority=payload.priority or "medium",
            due_date=payload.dueDate,
        )
        return {"ok": True, "memory": memory_store.get_state()}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/tasks/complete")
async def complete_task(payload: TaskCompleteRequest) -> dict[str, Any]:
    try:
        memory_store.complete_task(payload.taskRef)
        return {"ok": True, "memory": memory_store.get_state()}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str) -> dict[str, Any]:
    try:
        memory_store.delete_task(task_id)
        return {"ok": True, "memory": memory_store.get_state()}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/notes")
async def create_note(payload: NoteCreateRequest) -> dict[str, Any]:
    try:
        memory_store.remember_note(payload.text, payload.category or "note")
        return {"ok": True, "memory": memory_store.get_state()}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/notes/{note_id}")
async def remove_note(note_id: str) -> dict[str, Any]:
    try:
        memory_store.delete_note(note_id)
        return {"ok": True, "memory": memory_store.get_state()}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/admin/flush")
async def flush_admin_ram(request: Request) -> dict[str, Any]:
    require_admin_token(request)
    if not memory_store.is_ephemeral:
        return {
            "ok": True,
            "applicable": False,
            "detail": "Ephemeral RAM flush is not applicable in Mongo mode.",
        }

    counts = memory_store.flush_all_ephemeral()
    return {"ok": True, "applicable": True, "counts": counts}


@app.post("/api/chat")
async def handle_chat(payload: ChatRequest) -> dict[str, Any]:
    unsupported_refusal = "Sorry, I don't have this function. Please use other LLMs that support this."
    used_model = payload.modelOverride or settings.ai_model
    use_memory = bool(payload.useMemory) and memory_store.supports_persistent_memory

    if payload.imageGen:
        return {
            "reply": unsupported_refusal,
            "toolEvents": [],
            "memory": memory_store.get_state() if use_memory else None,
            "model": used_model,
        }

    try:
        result = await assistant.chat(
            message=payload.message,
            conversation=payload.conversation,
            screen_image=payload.screenImage,
            mode=payload.mode,
            coach_topic=payload.coachTopic,
            coach_level=payload.coachLevel,
            preferred_language=payload.preferredLanguage,
            web_search_only=payload.webSearchOnly,
            offline_mode=payload.offlineMode,
            session_id=payload.sessionId,
            routing_mode=payload.routingMode,
            override_provider=payload.providerOverride,
            override_model=payload.modelOverride,
            use_memory=use_memory,
        )
        return {
            "reply": result.reply,
            "toolEvents": result.tool_events,
            "memory": memory_store.get_state() if use_memory else None,
            "model": used_model,
        }
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/weather")
async def get_weather(request: Request, location: Optional[str] = "", use_memory: bool = True) -> dict[str, Any]:
    client_id = get_ephemeral_client_id(request, required=False)
    allow_memory = use_memory and memory_store.supports_persistent_memory
    try:
        data = weather_svc.fetch_weather(location)
        if allow_memory:
            memory_store.set_last_weather(data, client_id=client_id)
        return {"weather": data, "memory": memory_store.get_state(client_id=client_id) if allow_memory else None}
    except WeatherError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/news")
async def get_news(request: Request, topic: Optional[str] = "", use_memory: bool = True) -> dict[str, Any]:
    client_id = get_ephemeral_client_id(request, required=False)
    allow_memory = use_memory and memory_store.supports_persistent_memory
    try:
        data = news_svc.fetch_news(topic)
        if allow_memory:
            memory_store.set_last_news(data, client_id=client_id)
        return {"news": data, "memory": memory_store.get_state(client_id=client_id) if allow_memory else None}
    except NewsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/sessions/{session_id}/attachments")
async def upload_attachment(session_id: str, payload: AttachmentUpload) -> dict[str, Any]:
    if memory_store.is_ephemeral:
        raise MemoryDisabledError(
            "This feature requires Agent Memory. Please enable MongoDB on server startup to use long-term memory, notes, tasks, pinning, archiving, and file attachments."
        )

    try:
        file_bytes = base64.b64decode(payload.data)
        safe_name = f"{session_id}_{payload.filename}"
        disk_path = os.path.join(knowledge.upload_dir, safe_name)
        with open(disk_path, "wb") as file_handle:
            file_handle.write(file_bytes)

        attachment = memory_store.add_session_attachment(
            session_id=session_id,
            filename=payload.filename,
            file_type=os.path.splitext(payload.filename)[1].lower(),
            file_size=len(file_bytes),
            storage_path=disk_path,
        )
        chunk_count = knowledge.index_session_file(
            session_id=session_id,
            attachment_id=attachment["attachment_id"],
            file_path=disk_path,
            filename=payload.filename,
        )
        attachment["chunk_count"] = chunk_count
        return {"ok": True, "attachment": attachment}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/")
async def serve_index() -> FileResponse:
    return FileResponse(settings.web_dir / "index.html")


@app.get("/styles.css")
async def serve_styles() -> FileResponse:
    return FileResponse(settings.web_dir / "assets" / "styles.css")


@app.get("/app.js")
async def serve_app_js() -> FileResponse:
    return FileResponse(settings.web_dir / "scripts" / "app.js")


@app.get("/avatar-worker.js")
async def serve_avatar_worker() -> FileResponse:
    return FileResponse(settings.web_dir / "scripts" / "avatar-worker.js")


@app.get("/avatar-renderer.js")
async def serve_avatar_renderer() -> FileResponse:
    return FileResponse(settings.web_dir / "scripts" / "avatar-renderer.js")


app.mount("/assets", StaticFiles(directory=settings.web_dir / "assets"), name="assets")
app.mount("/scripts", StaticFiles(directory=settings.web_dir / "scripts"), name="scripts")


def run() -> None:
    current_settings = get_settings()

    print("==================================================")
    print("      ORBIT VIRTUAL ASSISTANT (FASTAPI)")
    print("==================================================")

    print(f"Current default provider in .env: {current_settings.provider_name.upper()}")
    print("Select AI Provider:")
    print("  1: Google (Gemini)")
    print("  2: OpenRouter")
    print("  3: LM Studio (Local)")
    print("  4: Ollama (Local)")
    provider_choice = input("Choice [Press Enter for default]: ").strip()

    if provider_choice == "1":
        current_settings = dataclasses.replace(
            current_settings,
            active_provider="google",
            ai_model=os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"),
        )
    elif provider_choice == "2":
        current_settings = dataclasses.replace(
            current_settings,
            active_provider="openrouter",
            ai_model=os.getenv("OPENROUTER_MODEL", current_settings.ai_model),
        )
    elif provider_choice == "3":
        current_settings = dataclasses.replace(
            current_settings,
            active_provider="lm_studio",
            ai_model=os.getenv("LM_STUDIO_MODEL", "local-model"),
        )
    elif provider_choice == "4":
        current_settings = dataclasses.replace(
            current_settings,
            active_provider="ollama",
            ai_model=os.getenv("OLLAMA_MODEL", "llama3.1"),
        )

    print(
        f"--- Running with Default Provider: "
        f"{current_settings.active_provider.upper()} ({current_settings.ai_model}) ---"
    )

    use_hybrid = input(
        "Do you want to enable Hybrid Mode (Multi-model smart routing)? (y/n) [n]: "
    ).strip().lower()
    if use_hybrid in ["y", "yes"]:
        current_settings = dataclasses.replace(current_settings, enable_hybrid=True)
        print(
            "[*] Hybrid Mode ENABLED. Complex tasks can be routed to: "
            f"{getattr(current_settings, 'hybrid_provider', 'openrouter').upper()} "
            f"({getattr(current_settings, 'hybrid_model', 'openai/gpt-4o')})"
        )
    else:
        print("[*] Hybrid Mode DISABLED. Single model will be used for all tasks.")

    use_rag = input(
        "Do you want to enable RAG with local documents (RAG via LM Studio)? (y/n) [n]: "
    ).strip().lower()

    rag_path = None
    if use_rag in ["y", "yes"]:
        default_path = current_settings.rag_docs_path or str(current_settings.root_dir / "knowledge_base")
        user_path = input(
            f"Enter the path to your local documents (default: {default_path}): "
        ).strip()
        rag_path = user_path if user_path else default_path
        print("Connecting to LM Studio and initializing the Vector Database....")
        print(f"RAG will be enabled with documents from: {rag_path}")
    else:
        print("RAG will be disabled. The assistant will not have access to local documents.")

    memory_choice = input(
        "Do you want to enable Agent Memory (MongoDB)? (y/n) [n]: "
    ).strip().lower()

    storage_mode = "mongo" if memory_choice in ["y", "yes"] else "ephemeral"

    if storage_mode == "mongo":
        print("[*] MongoDB Agent Memory ENABLED. Attempting connection...")
    else:
        print("[*] Ephemeral Mode ENABLED (RAM only).")

    init_services(current_settings, rag_path, storage_mode=storage_mode)

    print(f"Orbit Assistant is starting on http://127.0.0.1:{current_settings.assistant_port}")
    uvicorn.run(app, host="127.0.0.1", port=current_settings.assistant_port)


if __name__ == "__main__":
    run()
