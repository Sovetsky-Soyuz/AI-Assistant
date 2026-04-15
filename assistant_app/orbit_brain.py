from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .memory_store import MemoryStore
from .news import NewsError, NewsService
from .weather import WeatherError, WeatherService


BASE_PROMPT = """You are Orbit, a warm virtual daily AI assistant.

You help with everyday questions, lightweight coaching, planning, screen-aware assistance, weather, news, and spoken conversation.
Rules:
- Be practical, calm, and concise.
- If the user asks for current weather or temperature, call the weather tool instead of guessing.
- If the user asks for current news or headlines, call the news tool instead of guessing.
- If the user shares a screen image, describe only what you can reasonably infer from the image and say when something is uncertain.
- Offer short next steps when the user seems blocked.
- Do not claim you can control the laptop. You can see a shared screen image and advise the user based on it.
- If the user clearly asks you to remember something useful for later, save it with the memory tools.
- If the user states a task they want to do, you may add it as a task when that would obviously help.
"""

SIMPLE_MODE_PROMPT = """Mode: simple assistant.
- Focus on the user's current message.
- Keep answers short and direct.
- Only save memory or tasks when the user explicitly asks.
"""

COPILOT_MODE_PROMPT = """Mode: next-level virtual copilot.
- Be a little more proactive.
- When helpful, turn vague goals into a crisp 2-4 step plan.
- Save clear preferences, routines, and tasks when it adds long-term value.
- If a screen image is attached, connect what is visible to the user's likely next move.
"""

IELTS_MODE_PROMPT = """Mode: IELTS coach.
- Help the user practice IELTS Speaking, Writing, Reading, and Listening with realistic task framing.
- Be accurate about band descriptors, but do not claim to be an official IELTS examiner.
- Keep practice structured, focused, and easy to continue turn by turn.
- When the user submits an answer, estimate a likely band range and explain the strongest fix first.
- Default to English for actual IELTS practice prompts unless the user explicitly asks for explanations in another language.
"""

IELTS_SKILL_PROMPTS = {
    "speaking": """Current IELTS focus: Speaking.
- Act like a realistic examiner when the user wants a mock test.
- Ask one question at a time and wait for the user's answer.
- After each answer, give concise feedback on fluency, vocabulary, grammar, and coherence.
""",
    "writing": """Current IELTS focus: Writing.
- Score work using Task Response, Coherence and Cohesion, Lexical Resource, and Grammar.
- Point out sentence-level fixes and show a stronger rewrite when helpful.
- If the user gives an essay plan, help improve structure before full drafting.
""",
    "reading": """Current IELTS focus: Reading.
- Teach skimming, scanning, locating evidence, and time management.
- When the user asks for practice, create short reading drills with answer explanations.
- Highlight why distractor choices are wrong.
""",
    "listening": """Current IELTS focus: Listening.
- Help with note-taking, keyword prediction, dictation-style checks, and answer review.
- When the user asks for practice, create listening-style exercises using text-based prompts only.
- Emphasize spelling, number formats, and common trap patterns.
""",
}

LANGUAGE_HINTS = {
    "default": "",
    "en-US": "Prefer replying in English unless the user asks for a different language.",
    "en-GB": "Prefer replying in British English unless the user asks for a different language.",
    "vi-VN": "Prefer replying in Vietnamese when it helps, but keep IELTS mock questions in English by default.",
    "ja-JP": "Prefer replying in Japanese when it helps, but keep IELTS mock questions in English by default.",
    "ko-KR": "Prefer replying in Korean when it helps, but keep IELTS mock questions in English by default.",
    "zh-CN": "Prefer replying in Simplified Chinese when it helps, but keep IELTS mock questions in English by default.",
    "fr-FR": "Prefer replying in French when it helps, but keep IELTS mock questions in English by default.",
    "de-DE": "Prefer replying in German when it helps, but keep IELTS mock questions in English by default.",
    "es-ES": "Prefer replying in Spanish when it helps, but keep IELTS mock questions in English by default.",
    "th-TH": "Prefer replying in Thai when it helps, but keep IELTS mock questions in English by default.",
    "id-ID": "Prefer replying in Indonesian when it helps, but keep IELTS mock questions in English by default.",
}

_FUNCTION_DECLARATIONS = [
    {
        "name": "get_weather",
        "description": "Get the current weather and today's temperature range for a place.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "A city, district, or country such as 'Ho Chi Minh City' or 'Tokyo'.",
                }
            },
            "required": ["location"],
        },
    },
    {
        "name": "get_latest_news",
        "description": "Get the latest news headlines for a topic or region.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "A topic like 'AI', 'Vietnam', 'world headlines', or 'technology'.",
                },
                "max_items": {
                    "type": "integer",
                    "description": "How many headlines to return, usually between 1 and 8.",
                },
            },
        },
    },
    {
        "name": "remember_note",
        "description": "Save a user preference, detail, or note for later.",
        "parameters": {
            "type": "object",
            "properties": {
                "note": {"type": "string"},
                "category": {
                    "type": "string",
                    "description": "Short label like preference, habit, profile, reminder, or note.",
                },
            },
            "required": ["note"],
        },
    },
    {
        "name": "update_profile",
        "description": "Save the user's name, location, or routine.",
        "parameters": {
            "type": "object",
            "properties": {
                "display_name": {"type": "string"},
                "location": {"type": "string"},
                "routine": {"type": "string"},
            },
        },
    },
    {
        "name": "add_task",
        "description": "Create a task in the assistant's task list.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                },
                "due_date": {
                    "type": "string",
                    "description": "Optional date or deadline phrase such as 'Friday' or '2026-04-14'.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task complete by id or a unique part of its title.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_ref": {"type": "string"},
            },
            "required": ["task_ref"],
        },
    },

    {
        "name": "search_local_docs",
        "description": "Search the user's local private documents, papers, and files for specific information. Use this when the user asks about something in their local files or shared screen content.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The specific search query or keywords to look up in the local database.",
                }
            },
            "required": ["query"]
        }
    }
]


@dataclass
class ToolRunResult:
    event: dict[str, Any]
    function_response: dict[str, Any]


def normalize_mode(mode: str) -> str:
    normalized = (mode or "simple").strip().lower()
    if normalized in {"simple", "copilot", "ielts"}:
        return normalized
    return "simple"


def normalize_ielts_skill(skill: str) -> str:
    normalized = (skill or "speaking").strip().lower()
    if normalized in IELTS_SKILL_PROMPTS:
        return normalized
    return "speaking"


def _build_conversation_snapshot(conversation: list[dict[str, str]] | None) -> str:
    if not conversation:
        return "[]"

    snapshot: list[dict[str, str]] = []
    for entry in conversation[-8:]:
        text = " ".join((entry.get("text") or "").split())
        if not text:
            continue
        snapshot.append(
            {
                "role": entry.get("role") or "user",
                "text": text[:220],
            }
        )

    return json.dumps(snapshot, ensure_ascii=True)


def build_system_instruction(
    memory_store: MemoryStore,
    mode: str,
    ielts_skill: str = "speaking",
    target_band: str = "6.5",
    preferred_language: str = "default",
    recent_conversation: list[dict[str, str]] | None = None,
) -> str:
    normalized_mode = normalize_mode(mode)
    normalized_skill = normalize_ielts_skill(ielts_skill)
    memory_brief = json.dumps(memory_store.get_brief(), ensure_ascii=True)
    now = datetime.now().astimezone().strftime("%A, %B %d, %Y at %H:%M %Z")

    if normalized_mode == "copilot":
        mode_prompt = COPILOT_MODE_PROMPT
    elif normalized_mode == "ielts":
        mode_prompt = (
            f"{IELTS_MODE_PROMPT}\nTarget IELTS band: {target_band or '6.5'}.\n"
            f"{IELTS_SKILL_PROMPTS[normalized_skill]}"
        )
    else:
        mode_prompt = SIMPLE_MODE_PROMPT

    language_hint = LANGUAGE_HINTS.get(preferred_language, "")
    language_section = f"\nLanguage preference: {language_hint}" if language_hint else ""
    conversation_snapshot = _build_conversation_snapshot(recent_conversation)
    return (
        f"{BASE_PROMPT}\n{mode_prompt}\nLocal date and time: {now}{language_section}\n"
        f"Saved context snapshot: {memory_brief}\nRecent conversation snapshot: {conversation_snapshot}"
    )


# def build_rest_tools() -> list[dict[str, Any]]:
#     return [{"functionDeclarations": _FUNCTION_DECLARATIONS}]

def build_rest_tools(enable_knowledge: bool = True) -> list[dict[str, Any]]:
    funcs = [f for f in _FUNCTION_DECLARATIONS if enable_knowledge or f["name"] != "search_local_docs"]
    return [{"functionDeclarations": funcs}]


def run_tool_call(
    memory_store: MemoryStore,
    weather_service: WeatherService,
    news_service: NewsService,
    knowledge_service: Any = None,
    *,
    name: str,
    arguments: dict[str, Any] | None = None,
    call_id: str | None = None,
) -> ToolRunResult:
    args = arguments or {}
    resolved_call_id = call_id or uuid.uuid4().hex[:8]

    try:
        if name == "get_weather":
            result = weather_service.fetch_weather(args.get("location"))
            memory_store.set_last_weather(result)
            event = {"type": "weather", "label": f'Weather checked for {result["location"]}'}
        elif name == "get_latest_news":
            result = news_service.fetch_news(args.get("topic"), args.get("max_items", 5))
            memory_store.set_last_news(result)
            event = {"type": "news", "label": f'News checked for {result["topic"]}'}
        elif name == "remember_note":
            saved = memory_store.remember_note(args.get("note", ""), args.get("category", "note"))
            result = {"saved_note": saved}
            event = {"type": "memory", "label": f'Remembered: {saved["text"]}'}
        elif name == "update_profile":
            updated = memory_store.update_profile(
                display_name=args.get("display_name"),
                location=args.get("location"),
                routine=args.get("routine"),
            )
            result = {"profile_snapshot": updated["profile"]}
            event = {"type": "profile", "label": "Profile updated"}
        elif name == "add_task":
            task = memory_store.add_task(
                title=args.get("title", ""),
                priority=args.get("priority", "medium"),
                due_date=args.get("due_date"),
            )
            result = {"task": task}
            event = {"type": "task", "label": f'Task added: {task["title"]}'}
        elif name == "complete_task":
            task = memory_store.complete_task(args.get("task_ref", ""))
            result = {"task": task}
            event = {"type": "task", "label": f'Task completed: {task["title"]}'}
        elif name == "search_local_docs":
            # docs = knowledge_service.search(args.get("query", ""))
            # result = {"documents": docs}
            # event = {"type": "knowledge", "label": f'Searched local docs for: {args.get("query", "")}'}
            result = knowledge_service.search(args.get("query", ""))
            event = {"type": "knowledge", "label": f'Searched local files for: "{args.get("query", "")[:15]}..."'}
        else:
            raise ValueError(f"Unsupported tool call '{name}'.")
    except (NewsError, WeatherError, KeyError, ValueError) as exc:
        result = {"error": str(exc)}
        event = {"type": "error", "label": f"Tool error in {name}: {exc}"}

    return ToolRunResult(
        event=event,
        function_response={
            "id": resolved_call_id,
            "name": name,
            "response": result,
        },
    )
