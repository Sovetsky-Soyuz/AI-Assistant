# from __future__ import annotations

# import os
# from dataclasses import dataclass
# from pathlib import Path


# def load_dotenv(dotenv_path: Path) -> None:
#     if not dotenv_path.exists():
#         return

#     for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
#         line = raw_line.strip()
#         if not line or line.startswith("#") or "=" not in line:
#             continue
#         key, value = line.split("=", 1)
#         os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# @dataclass(frozen=True)
# class Settings:
#     root_dir: Path
#     web_dir: Path
#     data_dir: Path
#     provider_name: str
#     gemini_api_key: str
#     gemini_model: str
#     assistant_port: int
#     default_location: str
#     live_voice_name: str


# def get_settings() -> Settings:
#     root_dir = Path(__file__).resolve().parent.parent
#     load_dotenv(root_dir / ".env")

#     return Settings(
#         root_dir=root_dir,
#         web_dir=root_dir / "web",
#         data_dir=root_dir / "data",
#         provider_name="Gemini",
#         # gemini_api_key=os.getenv("GEMINI_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip(),
#         # gemini_model=os.getenv("GEMINI_MODEL", os.getenv("OPENAI_MODEL", "gemini-2.5-flash")).strip()
#         # or "gemini-2.5-flash",
#         gemini_api_key=os.getenv("API_KEY", os.getenv("OPENAI_API_KEY", "")).strip(),
#         gemini_model=os.getenv("AI_MODEL", os.getenv("OPENAI_MODEL", "gemini-2.5-flash")).strip(),
#         assistant_port=int(os.getenv("ASSISTANT_PORT", "8000")),
#         live_voice_name=os.getenv("LIVE_VOICE_NAME", "Kore").strip() or "Kore",
#         default_location=os.getenv("DEFAULT_LOCATION", "Ho Chi Minh City").strip() or "Ho Chi Minh City",
#     )


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


@dataclass(frozen=True)
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

    @property
    def provider_name(self) -> str:
        return "OpenRouter" if self.active_provider == "openrouter" else "Google"

    @property
    def current_api_key(self) -> str:
        return self.openrouter_api_key if self.active_provider == "openrouter" else self.google_api_key


def get_settings() -> Settings:
    root_dir = Path(__file__).resolve().parent.parent
    load_dotenv(root_dir / ".env")

    return Settings(
        root_dir=root_dir,
        web_dir=root_dir / "web",
        data_dir=root_dir / "data",
        active_provider=os.getenv("ACTIVE_PROVIDER", "google").strip().lower(),
        google_api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        ai_model=os.getenv("AI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash",
        assistant_port=int(os.getenv("ASSISTANT_PORT", "8000")),
        live_voice_name=os.getenv("LIVE_VOICE_NAME", "Nanami").strip() or "Nanami",
        default_location=os.getenv("DEFAULT_LOCATION", "Ho Chi Minh City").strip() or "Ho Chi Minh City",
    )