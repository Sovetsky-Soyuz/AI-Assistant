from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..config import Settings
from ..core.memory_store import MemoryStore
from ..tools.news import NewsService
from ..core.orbit_brain import (
    build_rest_tools,
    build_system_instruction,
    normalize_mode,
    run_tool_call,
)
from ..tools.weather import WeatherService


API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass
class AssistantResult:
    reply: str
    tool_events: list[dict[str, Any]]


class GeminiClientError(RuntimeError):
    pass


class GeminiAssistant:
    def __init__(self, settings: Settings, memory_store: MemoryStore) -> None:
        self.settings = settings
        self.memory_store = memory_store
        self.weather_service = WeatherService(settings.default_location)
        self.news_service = NewsService()

    def chat(
        self,
        message: str,
        conversation: list[dict[str, str]] | None = None,
        screen_image: str | None = None,
        mode: str = "simple",
        ielts_skill: str = "speaking",
        target_band: str = "6.5",
        preferred_language: str = "default",
    ) -> AssistantResult:
        if not self.settings.gemini_api_key:
            raise GeminiClientError(
                "API_KEY is missing. Add it to a local .env file before using the assistant chat."
            )

        instructions = build_system_instruction(
            self.memory_store,
            normalize_mode(mode),
            ielts_skill=normalize_ielts_skill(ielts_skill),
            target_band=target_band,
            preferred_language=preferred_language,
            recent_conversation=conversation or [],
        )
        history = self._build_contents(message, conversation or [], screen_image)
        tool_events: list[dict[str, Any]] = []

        for _ in range(6):
            response = self._generate_content(history, instructions)
            function_calls = self._extract_function_calls(response)
            if not function_calls:
                return AssistantResult(reply=self._extract_text(response), tool_events=tool_events)

            model_content = self._extract_model_content(response)
            if model_content:
                history.append(model_content)

            function_response_parts = []
            for function_call in function_calls:
                tool_result = run_tool_call(
                    self.memory_store,
                    self.weather_service,
                    self.news_service,
                    name=function_call.get("name", ""),
                    arguments=function_call.get("args") or {},
                    call_id=function_call.get("id"),
                )
                tool_events.append(tool_result.event)
                function_response_parts.append({"functionResponse": tool_result.function_response})

            history.append({"role": "user", "parts": function_response_parts})

        raise GeminiClientError("The assistant reached the tool loop limit before finishing the response.")

    def _build_contents(
        self,
        message: str,
        conversation: list[dict[str, str]],
        screen_image: str | None,
    ) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for entry in conversation[-12:]:
            role = "model" if entry.get("role") == "assistant" else "user"
            text = (entry.get("text") or "").strip()
            if text:
                contents.append({"role": role, "parts": [{"text": text}]})

        parts: list[dict[str, Any]] = [{"text": message.strip()}]
        image_part = self._build_image_part(screen_image)
        if image_part:
            parts.append(image_part)
        contents.append({"role": "user", "parts": parts})
        return contents

    def _build_image_part(self, screen_image: str | None) -> dict[str, Any] | None:
        if not screen_image or not screen_image.startswith("data:") or "," not in screen_image:
            return None

        header, data = screen_image.split(",", 1)
        mime_type = "image/jpeg"
        if ";" in header:
            mime_type = header[5:].split(";", 1)[0] or mime_type

        return {
            "inlineData": {
                "mimeType": mime_type,
                "data": data,
            }
        }

    def _generate_content(self, contents: list[dict[str, Any]], instructions: str) -> dict[str, Any]:
        endpoint = API_URL_TEMPLATE.format(model=quote(self.settings.gemini_model, safe=""))
        payload = {
            "systemInstruction": {
                "parts": [{"text": instructions}],
            },
            "contents": contents,
            "tools": build_rest_tools(),
            "generationConfig": {
                "temperature": 0.7,
            },
        }
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.settings.gemini_api_key,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise GeminiClientError(f"API error ({exc.code}): {details}") from exc
        except URLError as exc:
            raise GeminiClientError(f"Unable to reach the API: {exc.reason}") from exc

    def _extract_model_content(self, response: dict[str, Any]) -> dict[str, Any] | None:
        candidates = response.get("candidates") or []
        if not candidates:
            return None
        content = candidates[0].get("content")
        return content if isinstance(content, dict) else None

    def _extract_function_calls(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        content = self._extract_model_content(response)
        if not content:
            return []

        function_calls: list[dict[str, Any]] = []
        for part in content.get("parts", []):
            function_call = part.get("functionCall")
            if not function_call:
                continue
            function_calls.append(
                {
                    "id": function_call.get("id") or uuid.uuid4().hex[:8],
                    "name": function_call.get("name", ""),
                    "args": function_call.get("args") or {},
                }
            )
        return function_calls

    def _extract_text(self, response: dict[str, Any]) -> str:
        candidates = response.get("candidates") or []
        if not candidates:
            prompt_feedback = response.get("promptFeedback") or {}
            block_reason = prompt_feedback.get("blockReason")
            if block_reason:
                return f"Gemini did not return a reply because the request was blocked: {block_reason}."
            return "Gemini did not return a candidate response."

        parts = candidates[0].get("content", {}).get("parts", [])
        chunks = [part.get("text", "").strip() for part in parts if part.get("text", "").strip()]
        if chunks:
            return "\n\n".join(chunks)

        finish_reason = candidates[0].get("finishReason")
        if finish_reason:
            return f"Gemini finished without a text reply. Finish reason: {finish_reason}."
        return "Gemini finished without a readable text reply."
