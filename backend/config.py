from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    root_dir: Path
    web_dir: Path
    data_dir: Path
    active_provider: str
    google_api_key: str
    openrouter_api_key: str
    ai_model: str
    assistant_port: int
    default_location: str
    live_voice_name: str
    embedding_model: str = ""
    rag_docs_path: str = ""
    lm_studio_url: str = ""
    ollama_url: str = ""
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "orbit_assistant"

    @property
    def provider_name(self) -> str:
        names = {
            "google": "Google", 
            "openrouter": "OpenRouter", 
            "lm_studio": "LM Studio", 
            "ollama": "Ollama"
        }
        return names.get(self.active_provider, "OpenRouter")

    @property
    def current_api_key(self) -> str:
        if self.active_provider == "openrouter": return self.openrouter_api_key
        if self.active_provider == "google": return self.google_api_key
        return "local-no-key" 


def get_settings() -> Settings:
    root_dir = Path(__file__).resolve().parent.parent
    load_dotenv(root_dir / ".env")

    return Settings(
        root_dir=root_dir,
        web_dir=root_dir / "frontend",
        data_dir=root_dir / "data",
        active_provider=os.getenv("ACTIVE_PROVIDER", "google").strip().lower(),
        google_api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        ai_model=os.getenv("AI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash",
        assistant_port=int(os.getenv("ASSISTANT_PORT", "8000")),
        live_voice_name=os.getenv("LIVE_VOICE_NAME", "").strip() or "Nanami",
        default_location=os.getenv("DEFAULT_LOCATION", "").strip() or "Ho Chi Minh City",
        rag_docs_path=os.getenv("RAG_DOCS_PATH", "").strip(),
        lm_studio_url=os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234/v1").strip(),
        ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/v1").strip(),
        mongodb_uri=os.getenv("MONGODB_URI", "mongodb://localhost:27017").strip(),
        mongodb_db=os.getenv("MONGODB_DB", "orbit_assistant").strip(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-bge-m3").strip(),
    )
