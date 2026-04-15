from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import Settings
from .memory_store import MemoryStore
from .news import NewsService
from .orbit_brain import (
    build_rest_tools,
    build_system_instruction,
    normalize_ielts_skill,
    normalize_mode,
    run_tool_call,
)
from .weather import WeatherService
from typing import Any


API_URL_GOOGLE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
API_URL_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class AssistantResult:
    reply: str
    tool_events: list[dict[str, Any]]


class LLMClientError(RuntimeError):
    pass


class LLMAssistant:
    def __init__(self, settings: Settings, memory_store: MemoryStore, knowledge_service: Any) -> None:
        self.settings = settings
        self.memory_store = memory_store
        self.weather_service = WeatherService(settings.default_location)
        self.news_service = NewsService()
        self.knowledge_service = knowledge_service

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
        if not self.settings.current_api_key:
            raise LLMClientError(f"{self.settings.provider_name} API Key is missing. Please check your .env file.")

        instructions = build_system_instruction(
            self.memory_store,
            normalize_mode(mode),
            ielts_skill=normalize_ielts_skill(ielts_skill),
            target_band=target_band,
            preferred_language=preferred_language,
            recent_conversation=conversation or [],
        )

        if self.settings.active_provider == "openrouter":
            return self._chat_openrouter(message, conversation or [], screen_image, instructions)
        else:
            return self._chat_google(message, conversation or [], screen_image, instructions)

    # ==========================================
    #  OPENROUTER (OPENAI-COMPATIBLE) LOGIC
    # ==========================================
    def _chat_openrouter(self, message: str, conversation: list[dict[str, str]], screen_image: str | None, instructions: str) -> AssistantResult:
        messages: list[dict[str, Any]] = [{"role": "system", "content": instructions}]

        for entry in conversation[-12:]:
            role = "assistant" if entry.get("role") == "assistant" else "user"
            text = (entry.get("text") or "").strip()
            if text:
                messages.append({"role": role, "content": text})

        current_content: list[dict[str, Any]] = []
        if screen_image and screen_image.startswith("data:") and "," in screen_image:
            current_content.append({"type": "image_url", "image_url": {"url": screen_image}})
            
        current_content.append({"type": "text", "text": message.strip()})
        messages.append({"role": "user", "content": current_content})

        # google_tools = build_rest_tools()
        google_tools = build_rest_tools(enable_knowledge=self.knowledge_service is not None)
        tools = [{"type": "function", "function": f} for f in google_tools[0]["functionDeclarations"]]
        tool_events: list[dict[str, Any]] = []

        for _ in range(6):
            payload = {
                "model": self.settings.ai_model,
                "messages": messages,
                "tools": tools,
                "temperature": 0.7,
            }
                
            request = Request(
                API_URL_OPENROUTER,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.settings.current_api_key}",
                    "HTTP-Referer": "http://127.0.0.1",
                    "X-Title": "Orbit Assistant"
                },
                method="POST",
            )

            try:
                with urlopen(request, timeout=90) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                details = exc.read().decode("utf-8", errors="ignore")
                raise LLMClientError(f"OpenRouter error ({exc.code}): {details}") from exc
            except URLError as exc:
                raise LLMClientError(f"Unable to reach OpenRouter: {exc.reason}") from exc

            choice = res_data.get("choices", [{}])[0]
            msg = choice.get("message", {})

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return AssistantResult(reply=msg.get("content", "") or "No text response.", tool_events=tool_events)

            messages.append(msg)

            for tool_call in tool_calls:
                func = tool_call.get("function", {})
                call_id = tool_call.get("id")
                name = func.get("name", "")
                    
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                tool_result = run_tool_call(
                    self.memory_store,
                    self.weather_service,
                    self.news_service,
                    self.knowledge_service,
                    name=name,
                    arguments=args,
                    call_id=call_id,
                )
                tool_events.append(tool_result.event)

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps(tool_result.function_response["response"]),
                })

        raise LLMClientError("The assistant reached the tool loop limit before finishing the response.")

    # ==========================================
    #  GOOGLE REST API LOGIC
    # ==========================================
    def _chat_google(self, message: str, conversation: list[dict[str, str]], screen_image: str | None, instructions: str) -> AssistantResult:
        contents = self._build_google_contents(message, conversation, screen_image)
        tool_events: list[dict[str, Any]] = []

        for _ in range(6):
            response = self._generate_google_content(contents, instructions)
            function_calls = self._extract_google_function_calls(response)
                
            if not function_calls:
                return AssistantResult(reply=self._extract_google_text(response), tool_events=tool_events)

            model_content = self._extract_google_model_content(response)
            if model_content:
                contents.append(model_content)

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

            contents.append({"role": "user", "parts": function_response_parts})

        raise LLMClientError("The assistant reached the tool loop limit before finishing the response.")

    def _build_google_contents(self, message: str, conversation: list[dict[str, str]], screen_image: str | None) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for entry in conversation[-12:]:
            role = "model" if entry.get("role") == "assistant" else "user"
            text = (entry.get("text") or "").strip()
            if text:
                contents.append({"role": role, "parts": [{"text": text}]})

        parts: list[dict[str, Any]] = [{"text": message.strip()}]
        if screen_image and screen_image.startswith("data:") and "," in screen_image:
            header, data = screen_image.split(",", 1)
            mime_type = "image/jpeg"
            if ";" in header:
                mime_type = header[5:].split(";", 1)[0] or mime_type
            parts.append({"inlineData": {"mimeType": mime_type, "data": data}})
                
        contents.append({"role": "user", "parts": parts})
        return contents

    def _generate_google_content(self, contents: list[dict[str, Any]], instructions: str) -> dict[str, Any]:
        endpoint = API_URL_GOOGLE.format(model=quote(self.settings.ai_model, safe=""))
        payload = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": contents,
            "tools": build_rest_tools(),
            "generationConfig": {"temperature": 0.7},
        }
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.settings.current_api_key,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise LLMClientError(f"Google API error ({exc.code}): {details}") from exc
        except URLError as exc:
            raise LLMClientError(f"Unable to reach the Google API: {exc.reason}") from exc

    def _extract_google_model_content(self, response: dict[str, Any]) -> dict[str, Any] | None:
        candidates = response.get("candidates") or []
        if not candidates:
            return None
        content = candidates[0].get("content")
        return content if isinstance(content, dict) else None

    def _extract_google_function_calls(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        content = self._extract_google_model_content(response)
        if not content:
            return []

        function_calls: list[dict[str, Any]] = []
        for part in content.get("parts", []):
            function_call = part.get("functionCall")
            if not function_call:
                continue
            function_calls.append({
                "id": function_call.get("id") or uuid.uuid4().hex[:8],
                "name": function_call.get("name", ""),
                "args": function_call.get("args") or {},
            })
        return function_calls

    def _extract_google_text(self, response: dict[str, Any]) -> str:
        candidates = response.get("candidates") or []
        if not candidates:
            prompt_feedback = response.get("promptFeedback") or {}
            block_reason = prompt_feedback.get("blockReason")
            if block_reason:
                return f"Google blocked the request: {block_reason}."
            return "Google API did not return a candidate response."

        parts = candidates[0].get("content", {}).get("parts", [])
        chunks = [part.get("text", "").strip() for part in parts if part.get("text", "").strip()]
        if chunks:
            return "\n\n".join(chunks)

        finish_reason = candidates[0].get("finishReason")
        if finish_reason:
            return f"Google API finished without text. Reason: {finish_reason}."
        return "Google API finished without a readable text reply."