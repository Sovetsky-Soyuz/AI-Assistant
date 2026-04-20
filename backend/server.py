from __future__ import annotations

import base64
import os
import dataclasses
import uvicorn
from typing import Any, List, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Import your modules
from .config import Settings, get_settings
from .api_clients.llm_client import LLMAssistant, LLMClientError
from .core.memory_store import MemoryStore
from .tools.news import NewsError, NewsService
from .tools.weather import WeatherError, WeatherService
from .tools.web_search import WebSearchService
from .tools.knowledge import KnowledgeService

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

app = FastAPI(title="Orbit Virtual Assistant API")
settings = get_settings()

memory_store: MemoryStore = None
knowledge: KnowledgeService = None
web_search: WebSearchService = None
assistant: LLMAssistant = None
weather_svc: WeatherService = None
news_svc: NewsService = None

def init_services(current_settings: Settings, rag_path: str | None = None):
    global memory_store, knowledge, web_search, assistant, weather_svc, news_svc, settings
    settings = current_settings

    legacy_json = settings.data_dir / "assistant_memory.json"
    legacy_history = settings.data_dir / "chat_history.json"

    if legacy_json.exists():
        print("[*] Legacy JSON files detected -- migrating to MongoDB...")
        memory_store = MemoryStore.migrate_from_json(
            json_path=legacy_json, history_path=legacy_history if legacy_history.exists() else None,
            mongodb_uri=settings.mongodb_uri, db_name=settings.mongodb_db,
        )
        legacy_json.rename(legacy_json.with_suffix(".json.bak"))
        if legacy_history.exists():
            legacy_history.rename(legacy_history.with_suffix(".json.bak"))
    else:
        memory_store = MemoryStore(mongodb_uri=settings.mongodb_uri, db_name=settings.mongodb_db)

    knowledge = KnowledgeService(memory_store=memory_store, docs_dir=rag_path, upload_dir=str(settings.data_dir / "uploads"))
    web_search = WebSearchService()
    assistant = LLMAssistant(settings, memory_store, knowledge, web_search)
    weather_svc = WeatherService(settings.default_location)
    news_svc = NewsService()

@app.get("/api/state")
async def get_state():
    return {
        "provider": settings.provider_name,
        "hasApiKey": bool(settings.current_api_key),
        "model": settings.ai_model,
        "defaultLocation": settings.default_location,
        "liveVoiceName": settings.live_voice_name,
        "memory": memory_store.get_state(),
        "history": memory_store.get_history(),
        "sessions": memory_store.get_sessions(include_archived=True),
        "enableHybrid": getattr(settings, 'enable_hybrid', False),
    }

@app.get("/api/sessions")
async def get_sessions(include_archived: bool = False):
    return {"sessions": memory_store.get_sessions(include_archived)}

@app.post("/api/sessions")
async def create_session(payload: SessionCreateRequest):
    title = payload.title
    if payload.firstMessage and not title:
        try:
            title = assistant.generate_title(payload.firstMessage)
        except Exception:
            title = "New Chat"
    session = memory_store.create_session(title=title or "New Chat")
    return {"ok": True, "session": session}

@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 0):
    return {"messages": memory_store.get_messages(session_id, limit)}

@app.post("/api/sessions/{session_id}/messages")
async def add_message(session_id: str, payload: dict):
    try:
        message = memory_store.add_message(session_id=session_id, role=payload.get("role", "user"), text=payload.get("text", ""))
        return {"ok": True, "message": message}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.put("/api/sessions/{session_id}")
async def update_session(session_id: str, payload: SessionUpdateRequest):
    kwargs = {}
    if payload.title is not None:
        kwargs["title"] = payload.title
    if payload.pinned is not None:
        kwargs["pinned"] = payload.pinned
    if payload.archived is not None:
        kwargs["archived"] = payload.archived
    
    try:
        session = memory_store.update_session(session_id, **kwargs)
        return {"ok": True, "session": session}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    attachments = memory_store.delete_session(session_id)
    knowledge.cleanup_session(session_id)
    for att in attachments:
        path = att.get("storage_path")
        if path and os.path.isfile(path):
            try: os.remove(path)
            except OSError: pass
    return {"ok": True}

# --- EXACT OLD LOGIC FOR CHAT (Non-Streaming JSON Return) ---
@app.post("/api/chat")
async def handle_chat(payload: ChatRequest):
    UNSUPPORTED_REFUSAL = "Sorry, I don't have this function. Please use other LLMs that support this."
    used_model = payload.modelOverride or settings.ai_model
    
    if payload.imageGen:
        return {"reply": UNSUPPORTED_REFUSAL, "toolEvents": [], "memory": memory_store.get_state(), "model": used_model}

    try:
        # TỪ KHÓA AWAIT QUAN TRỌNG: Đợi LLM suy nghĩ xong 100% rồi mới chạy tiếp
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
            override_model=payload.modelOverride
        )
        return {
            "reply": result.reply,
            "toolEvents": result.tool_events,
            "memory": memory_store.get_state(),
            "model": used_model,
        }
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

@app.get("/api/weather")
async def get_weather(location: Optional[str] = ""):
    try:
        data = weather_svc.fetch_weather(location)
        memory_store.set_last_weather(data)
        return {"weather": data, "memory": memory_store.get_state()}
    except WeatherError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/news")
async def get_news(topic: Optional[str] = ""):
    try:
        data = news_svc.fetch_news(topic)
        memory_store.set_last_news(data)
        return {"news": data, "memory": memory_store.get_state()}
    except NewsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.post("/api/sessions/{session_id}/attachments")
async def upload_attachment(session_id: str, payload: AttachmentUpload):
    try:
        file_bytes = base64.b64decode(payload.data)
        safe_name = f"{session_id}_{payload.filename}"
        disk_path = os.path.join(knowledge.upload_dir, safe_name)
        with open(disk_path, "wb") as f: f.write(file_bytes)

        attachment = memory_store.add_session_attachment(
            session_id=session_id, filename=payload.filename,
            file_type=os.path.splitext(payload.filename)[1].lower(),
            file_size=len(file_bytes), storage_path=disk_path,
        )
        chunk_count = knowledge.index_session_file(session_id=session_id, attachment_id=attachment["attachment_id"], file_path=disk_path, filename=payload.filename)
        attachment["chunk_count"] = chunk_count
        return {"ok": True, "attachment": attachment}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/")
async def serve_index(): return FileResponse(settings.web_dir / "index.html")

@app.get("/styles.css")
async def serve_styles(): return FileResponse(settings.web_dir / "assets" / "styles.css")

@app.get("/app.js")
async def serve_app_js(): return FileResponse(settings.web_dir / "scripts" / "app.js")

@app.get("/avatar-worker.js")
async def serve_avatar_worker(): return FileResponse(settings.web_dir / "scripts" / "avatar-worker.js")

@app.get("/avatar-renderer.js")
async def serve_avatar_renderer(): return FileResponse(settings.web_dir / "scripts" / "avatar-renderer.js")

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
    p_choice = input("Choice [Press Enter for default]: ").strip()

    if p_choice == "1":
        current_settings = dataclasses.replace(current_settings, active_provider="google", ai_model=os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"))
    elif p_choice == "2":
        current_settings = dataclasses.replace(current_settings, active_provider="openrouter", ai_model=os.getenv("OPENROUTER_MODEL", current_settings.ai_model))
    elif p_choice == "3":
        current_settings = dataclasses.replace(current_settings, active_provider="lm_studio", ai_model=os.getenv("LM_STUDIO_MODEL", "local-model"))
    elif p_choice == "4":
        current_settings = dataclasses.replace(current_settings, active_provider="ollama", ai_model=os.getenv("OLLAMA_MODEL", "llama3.1"))

    print(f"--- Running with Default Provider: {current_settings.active_provider.upper()} ({current_settings.ai_model}) ---")

    use_hybrid = input("Do you want to enable Hybrid Mode (Multi-model smart routing)? (y/n) [n]: ").strip().lower()
    if use_hybrid in ['y', 'yes']:
        current_settings = dataclasses.replace(current_settings, enable_hybrid=True)
        print(f"[*] Hybrid Mode ENABLED. Complex tasks can be routed to: {getattr(current_settings, 'hybrid_provider', 'openrouter').upper()} ({getattr(current_settings, 'hybrid_model', 'openai/gpt-4o')})")
    else:
        print("[*] Hybrid Mode DISABLED. Single model will be used for all tasks.")

    use_rag = input("Do you want to enable RAG with local documents (RAG via LM Studio)? (y/n) [n]: ").strip().lower()
    
    rag_path = None
    if use_rag in ['y', 'yes']:
        default_path = current_settings.rag_docs_path or str(current_settings.root_dir / "knowledge_base")
        user_path = input(f"Enter the path to your local documents (default: {default_path}): ").strip()
        rag_path = user_path if user_path else default_path
        print(f"Connecting to LM Studio and initializing the Vector Database....")
        print(f"RAG will be enabled with documents from: {rag_path}")
    else:
        print("RAG will be disabled. The assistant will not have access to local documents.")

    init_services(current_settings, rag_path)

    print(f"Orbit Assistant is starting on http://127.0.0.1:{current_settings.assistant_port}")
    uvicorn.run(app, host="127.0.0.1", port=current_settings.assistant_port)

if __name__ == "__main__":
    run()