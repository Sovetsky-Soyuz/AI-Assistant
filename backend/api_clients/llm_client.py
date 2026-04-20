from __future__ import annotations

import json
import uuid
import asyncio
import httpx
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

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


API_URL_GOOGLE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
API_URL_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"

@dataclass
class AssistantResult:
    reply: str
    tool_events: list[dict[str, Any]]

class LLMClientError(RuntimeError):
    pass


class LLMAssistant:
    def __init__(self, settings: Settings, memory_store: MemoryStore, knowledge_service: Any, web_search_service: Any) -> None:
        self.settings = settings
        self.memory_store = memory_store
        self.weather_service = WeatherService(settings.default_location)
        self.news_service = NewsService()
        self.knowledge_service = knowledge_service
        self.web_search_service = web_search_service

    def _resolve_api_key(self, provider: str) -> str:
        if provider == "openrouter":
            return self.settings.openrouter_api_key
        elif provider == "google":
            return self.settings.google_api_key
        else:
            return "local-no-key"

    def generate_title(self, first_message: str) -> str:
        return first_message[:40] + "..." if len(first_message) > 40 else first_message

    def _classify_task_complexity(self, message: str) -> str:
        complex_keywords = [
            "analyze", "optimize", "refactor", "architect", 
            "explain code", "calculate", "prove", "derive", "logic",
            "phân tích", "tối ưu", "cấu trúc", "thuật toán"
        ]
        lower_message = message.lower()
        if len(message) > 800:
            return "complex"
        if any(keyword in lower_message for keyword in complex_keywords):
            return "complex"
        return "simple"

    async def chat(
        self,
        message: str,
        conversation: list[dict[str, str]] | None = None,
        screen_image: str | None = None,
        mode: str = "simple",
        coach_topic: str = "General Learning", 
        coach_level: str = "Beginner",         
        preferred_language: str = "default",
        web_search_only: bool = False,
        offline_mode: bool = False,
        session_id: str | None = None,
        routing_mode: str = "fixed",
        override_provider: str | None = None,
        override_model: str | None = None,
        use_memory: bool = True,
    ) -> AssistantResult:
        
        target_provider = override_provider or self.settings.active_provider
        target_model = override_model or self.settings.ai_model
        
        if routing_mode == "dynamic" and not override_model and getattr(self.settings, 'enable_hybrid', False):
            task_type = self._classify_task_complexity(message)
            if task_type == "complex":
                target_provider = getattr(self.settings, 'hybrid_provider', 'openrouter')
                target_model = getattr(self.settings, 'hybrid_model', 'openai/gpt-4o')
                print(f"[Routing] Task classified as COMPLEX. Upgrading to {target_model}")
            else:
                print(f"[Routing] Task classified as SIMPLE. Using default: {target_model}")

        current_api_key = self._resolve_api_key(target_provider)
        if not current_api_key and target_provider not in ["lm_studio", "ollama"]:
            raise LLMClientError(f"{target_provider} API Key is missing. Please check your .env file.")

        instructions = build_system_instruction(
            self.memory_store,
            normalize_mode(mode),
            coach_topic=coach_topic,         
            coach_level=coach_level,         
            preferred_language=preferred_language,
            recent_conversation=conversation or [],
            web_search_only=web_search_only,
            offline_mode=offline_mode,
            use_memory=use_memory,
        )

        if target_provider in ["openrouter", "lm_studio", "ollama"]:
            return await self._chat_openrouter(
                message, conversation or [], screen_image, instructions, 
                web_search_only, offline_mode, session_id,
                target_model, target_provider, current_api_key, use_memory
            )
        else:
            return await self._chat_google(
                message, conversation or [], screen_image, instructions, 
                web_search_only, offline_mode, session_id,
                target_model, current_api_key, use_memory
            )

    async def _chat_openrouter(
        self, message: str, conversation: list[dict[str, str]], 
        screen_image: str | None, instructions: str, 
        web_search_only: bool, offline_mode: bool, session_id: str | None,
        current_model: str, current_provider: str, current_api_key: str,
        use_memory: bool,
    ) -> AssistantResult:
        
        trigger_phrases = ["do you know", "who is", "what is", "tell me about", "give me information on", "details about"]
        if any(phrase in message.lower() for phrase in trigger_phrases):
            message = f"{message}\n\n[System Note: This looks like a factual query. You MUST use the `search_web` tool to find the latest info before answering.]"

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

        has_session_docs = False
        if session_id and self.knowledge_service:
            has_session_docs = bool(self.memory_store.get_session_attachments(session_id))

        google_tools = build_rest_tools(
            enable_knowledge=self.knowledge_service is not None and self.knowledge_service.kb_retriever is not None,
            web_search_only=web_search_only,
            offline_mode=offline_mode,
            enable_session_docs=has_session_docs,
            enable_memory=use_memory,
        )
        tools = [{"type": "function", "function": f} for f in google_tools[0]["functionDeclarations"]]
        tool_events: list[dict[str, Any]] = []

        if messages and messages[-1]["role"] == "user":
             multi_tool_reminder = "\n\n[SYSTEM INSTRUCTION: If the prompt contains multiple distinct requests, execute MULTIPLE tool calls before generating your final response.]"
             for part in messages[-1]["content"]:
                 if isinstance(part, dict) and part.get("type") == "text":
                     part["text"] += multi_tool_reminder
                     break
                 elif isinstance(messages[-1]["content"], str):
                     messages[-1]["content"] += multi_tool_reminder
                     break

        for _ in range(100):
            payload = {
                "model": current_model,
                "messages": messages,
                "temperature": 0.5,
            }
            if tools:
                payload["tools"] = tools

            if current_provider == "lm_studio":
                endpoint = f"{self.settings.lm_studio_url.rstrip('/')}/chat/completions"
                headers = {"Content-Type": "application/json"}
            elif current_provider == "ollama":
                endpoint = f"{self.settings.ollama_url.rstrip('/')}/v1/chat/completions"
                headers = {"Content-Type": "application/json"}
            else: 
                endpoint = API_URL_OPENROUTER
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {current_api_key}",
                    "HTTP-Referer": "http://127.0.0.1",
                    "X-Title": "Orbit Assistant"
                }

            try:
                async with httpx.AsyncClient(timeout=600.0) as client:
                    response = await client.post(endpoint, json=payload, headers=headers)
                    response.raise_for_status()
                    res_data = response.json()
            except httpx.HTTPStatusError as exc:
                details = exc.response.text
                if exc.response.status_code == 403 and ("moderation" in details.lower() or "flagged" in details.lower()):
                    return AssistantResult(reply="I cannot fulfill this request as it goes against safety guidelines.", tool_events=tool_events)
                raise LLMClientError(f"{current_provider.capitalize()} API error: {details}") from exc
            except Exception as exc:
                raise LLMClientError(f"Unable to reach {current_provider.capitalize()}: {exc}") from exc

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

                tool_result = await asyncio.to_thread(
                    run_tool_call,
                    self.memory_store, self.weather_service, self.news_service,
                    self.knowledge_service, self.web_search_service,
                    name=name, arguments=args, call_id=call_id, session_id=session_id,
                    allow_memory=use_memory,
                )
                tool_events.append(tool_result.event)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": json.dumps(tool_result.function_response["response"]),
                })

        raise LLMClientError("The assistant reached the tool loop limit before finishing the response.")

    async def _chat_google(
        self, message: str, conversation: list[dict[str, str]], 
        screen_image: str | None, instructions: str, 
        web_search_only: bool, offline_mode: bool, session_id: str | None,
        current_model: str, current_api_key: str, use_memory: bool
    ) -> AssistantResult:
        
        contents = self._build_google_contents(message, conversation, screen_image)
        tool_events: list[dict[str, Any]] = []
        has_session_docs = False
        if session_id and self.knowledge_service:
            has_session_docs = bool(self.memory_store.get_session_attachments(session_id))

        for _ in range(100):
            endpoint = API_URL_GOOGLE.format(model=quote(current_model, safe=""))
            payload = {
                "systemInstruction": {"parts": [{"text": instructions}]},
                "contents": contents,
                "tools": build_rest_tools(
                    enable_knowledge=self.knowledge_service is not None and self.knowledge_service.kb_retriever is not None,
                    web_search_only=web_search_only,
                    offline_mode=offline_mode,
                    enable_session_docs=has_session_docs,
                    enable_memory=use_memory,
                ),
            }

            try:
                async with httpx.AsyncClient(timeout=600.0) as client:
                    response = await client.post(endpoint, json=payload, headers={"Content-Type": "application/json", "x-goog-api-key": current_api_key})
                    response.raise_for_status()
                    res_data = response.json()
            except httpx.HTTPStatusError as exc:
                raise LLMClientError(f"Google API error: {exc.response.text}") from exc
            except Exception as exc:
                raise LLMClientError(f"Unable to reach Google API: {exc}") from exc

            function_calls = self._extract_google_function_calls(res_data)
            if not function_calls:
                return AssistantResult(reply=self._extract_google_text(res_data), tool_events=tool_events)

            model_content = self._extract_google_model_content(res_data)
            if model_content:
                contents.append(model_content)

            function_response_parts = []
            for fc in function_calls:
                tool_result = await asyncio.to_thread(
                    run_tool_call,
                    self.memory_store, self.weather_service, self.news_service,
                    self.knowledge_service, self.web_search_service,
                    name=fc.get("name", ""), arguments=fc.get("args", {}), call_id=fc.get("id"),
                    session_id=session_id, allow_memory=use_memory
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

    def _extract_google_model_content(self, response: dict[str, Any]) -> dict[str, Any] | None:
        candidates = response.get("candidates") or []
        if not candidates: return None
        content = candidates[0].get("content")
        return content if isinstance(content, dict) else None

    def _extract_google_function_calls(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        content = self._extract_google_model_content(response)
        if not content: return []
        function_calls: list[dict[str, Any]] = []
        for part in content.get("parts", []):
            fc = part.get("functionCall")
            if fc:
                function_calls.append({
                    "id": fc.get("id") or uuid.uuid4().hex[:8],
                    "name": fc.get("name", ""),
                    "args": fc.get("args") or {},
                })
        return function_calls

    def _extract_google_text(self, response: dict[str, Any]) -> str:
        candidates = response.get("candidates") or []
        if not candidates:
            return "Google API did not return a candidate response."
        parts = candidates[0].get("content", {}).get("parts", [])
        chunks = [part.get("text", "").strip() for part in parts if part.get("text", "").strip()]
        return "\n\n".join(chunks) if chunks else "No text response."
