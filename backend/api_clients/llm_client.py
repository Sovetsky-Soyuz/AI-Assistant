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
        """Resolve the appropriate API key based on the selected provider."""
        if provider == "openrouter":
            return self.settings.openrouter_api_key
        elif provider == "google":
            return self.settings.google_api_key
        else:
            # Local providers (LM Studio, Ollama) do not require authentication
            return "local-no-key"

    def generate_title(self, first_message: str) -> str:
        """
        Generates a concise 3-5 word title for the conversation based on the first message.
        Uses a fast internal call without tools to minimize latency.
        """
        summary_instruction = (
            "You are a professional editor. Summarize the user's request into a short, "
            "concise title of 3-5 words. Use the same language as the user's message. "
            "Output ONLY the title text without quotes or punctuation."
        )

        # We can use a fast model like Gemini Flash or a light local model for this task
        # to ensure the UI doesn't lag while creating a new chat.
        try:
            # We'll leverage the existing _chat_google logic but simplified
            # Note: You can customize which provider/model handles this.
            result = self.chat(
                message=f"Summarize this: {first_message}",
                mode="simple",
                instructions_override=summary_instruction # Optional: If you update chat() to support this
            )
            # For simplicity in this snippet, we'll call the chat logic with a direct prompt
            # If your chat() logic is too heavy, you can implement a lean version here.
            
            # Clean up the response (remove quotes, trailing dots)
            title = result.reply.strip().strip('"').strip("'").rstrip(".")
            return title if title else "New Chat"
        except Exception:
            # Fallback to the old method if AI generation fails
            return first_message[:40] + "..." if len(first_message) > 40 else first_message
            

    def _classify_task_complexity(self, message: str) -> str:
        """
        Heuristic-based task classification to determine required reasoning power.
        Returns 'complex' for heavy tasks, 'simple' for general queries.
        """
        complex_keywords = [
            "analyze", "optimize", "refactor", "architect", 
            "explain code", "calculate", "prove", "derive", "logic",
            "phân tích", "tối ưu", "cấu trúc", "thuật toán"
        ]
        
        lower_message = message.lower()
        
        # Rule 1: Long context usually requires better reasoning/context window
        if len(message) > 800:
            return "complex"
            
        # Rule 2: Specific keywords indicate complex analytical tasks
        if any(keyword in lower_message for keyword in complex_keywords):
            return "complex"
            
        return "simple"

    def chat(
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
        # Resource Management & Dynamic Overrides
        routing_mode: str = "fixed",
        override_provider: str | None = None,
        override_model: str | None = None,
    ) -> AssistantResult:
        
        # 1. Determine baseline provider and model
        target_provider = override_provider or self.settings.active_provider
        target_model = override_model or self.settings.ai_model
        
        # 2. Dynamic Routing Logic (Smart Hybrid Mode)
        # Only override if routing is dynamic, no manual override exists, and CLI enabled hybrid
        if routing_mode == "dynamic" and not override_model and self.settings.enable_hybrid:
            task_type = self._classify_task_complexity(message)
            
            if task_type == "complex":
                # Use .env configured heavy model instead of hardcoded gpt-4o
                target_provider = self.settings.hybrid_provider
                target_model = self.settings.hybrid_model
                print(f"[Routing] Task classified as COMPLEX. Upgrading to {target_model}")
            else:
                print(f"[Routing] Task classified as SIMPLE. Using default: {target_model}")
        elif routing_mode == "dynamic" and not self.settings.enable_hybrid:
            print(f"[Routing] Dynamic mode requested by UI, but Hybrid Mode is disabled in CLI. Using default: {target_model}")

            
        # 3. Resolve API Key for the final target provider
        current_api_key = self._resolve_api_key(target_provider)
        if not current_api_key and target_provider not in ["lm_studio", "ollama"]:
            raise LLMClientError(f"{target_provider} API Key is missing. Please check your .env file.")

        # 4. Build Context and System Instructions
        instructions = build_system_instruction(
            self.memory_store,
            normalize_mode(mode),
            coach_topic=coach_topic,         
            coach_level=coach_level,         
            preferred_language=preferred_language,
            recent_conversation=conversation or [],
            web_search_only=web_search_only,
            offline_mode=offline_mode,
        )

        # 5. Dispatch to the appropriate API handler
        if target_provider in ["openrouter", "lm_studio", "ollama"]:
            return self._chat_openrouter(
                message, conversation or [], screen_image, instructions, 
                web_search_only, offline_mode, session_id,
                target_model, target_provider, current_api_key
            )
        else:
            return self._chat_google(
                message, conversation or [], screen_image, instructions, 
                web_search_only, offline_mode, session_id,
                target_model, current_api_key
            )
        
    # ==========================================
    #  OPENROUTER (OPENAI-COMPATIBLE) LOGIC
    # ==========================================
    def _chat_openrouter(
        self, message: str, conversation: list[dict[str, str]], 
        screen_image: str | None, instructions: str, 
        web_search_only: bool, offline_mode: bool, session_id: str | None,
        current_model: str, current_provider: str, current_api_key: str
    ) -> AssistantResult:
        
        # Inject search hints for factual queries
        trigger_phrases = ["do you know", "who is", "what is", "tell me about", "give me information on", "details about"]
        lower_msg = message.lower()
        if any(phrase in lower_msg for phrase in trigger_phrases):
            message = f"{message}\n\n[System Note: This looks like a factual query. You MUST use the `search_web` tool to find the latest info before answering.]"

        messages: list[dict[str, Any]] = [{"role": "system", "content": instructions}]

        # Append recent conversation history
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

        # Determine if session has attachments (enables search_session_docs tool)
        has_session_docs = False
        if session_id and self.knowledge_service:
            has_session_docs = bool(self.memory_store.get_session_attachments(session_id))

        google_tools = build_rest_tools(
            enable_knowledge=self.knowledge_service is not None and self.knowledge_service.kb_retriever is not None,
            web_search_only=web_search_only,
            offline_mode=offline_mode,
            enable_session_docs=has_session_docs,
        )
        tools = [{"type": "function", "function": f} for f in google_tools[0]["functionDeclarations"]]
        tool_events: list[dict[str, Any]] = []

        # Remind model to execute multiple tools if needed
        if messages and messages[-1]["role"] == "user":
             multi_tool_reminder = (
                 "\n\n[SYSTEM INSTRUCTION: Analyze the user's request carefully. If the prompt contains multiple distinct requests (e.g., asking about one topic on the web AND another topic in local files), you MUST execute MULTIPLE tool calls in parallel or sequence before generating your final text response. Do not skip any part of the query. Only answer after ALL relevant tools have returned data.]"
             )

             for part in messages[-1]["content"]:
                 if part.get("type") == "text":
                     part["text"] += multi_tool_reminder
                     break

        # Tool execution loop
        for _ in range(100):
            payload = {
                "model": current_model,
                "messages": messages,
                "tools": tools,
                "temperature": 0.5,
            }

            # Configure endpoints based on the dynamic provider
            if current_provider == "lm_studio":
                endpoint = f"{self.settings.lm_studio_url.rstrip('/')}/chat/completions"
                headers = {"Content-Type": "application/json"}
            elif current_provider == "ollama":
                endpoint = f"{self.settings.ollama_url.rstrip('/')}/v1/chat/completions"
                headers = {"Content-Type": "application/json"}
            else: # OpenRouter
                endpoint = API_URL_OPENROUTER
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {current_api_key}",
                    "HTTP-Referer": "http://127.0.0.1",
                    "X-Title": "Orbit Assistant"
                }
                
            request = Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )

            try:
                with urlopen(request, timeout=600) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                details = exc.read().decode("utf-8", errors="ignore")
                if exc.code == 403 and ("moderation" in details.lower() or "flagged" in details.lower()):
                    return AssistantResult(
                        reply="I'm sorry, but I cannot fulfill this request as it goes against my safety and moderation guidelines.",
                        tool_events=tool_events
                    )
                raise LLMClientError(f"{current_provider.capitalize()} API error ({exc.code}): {details}") from exc
            except URLError as exc:
                raise LLMClientError(f"Unable to reach {current_provider.capitalize()}: {exc.reason}") from exc
            except TimeoutError as exc:
                raise LLMClientError(f"{current_provider.capitalize()} is taking too long to respond. Please try a lighter model or increase the timeout.") from exc


            choice = res_data.get("choices", [{}])[0]
            msg = choice.get("message", {})

            # If no tools were called, return the final text reply
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return AssistantResult(reply=msg.get("content", "") or "No text response.", tool_events=tool_events)

            messages.append(msg)

            # Execute requested tools
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
                    self.web_search_service,
                    name=name,
                    arguments=args,
                    call_id=call_id,
                    session_id=session_id,
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
    def _chat_google(
        self, message: str, conversation: list[dict[str, str]], 
        screen_image: str | None, instructions: str, 
        web_search_only: bool, offline_mode: bool, session_id: str | None,
        current_model: str, current_api_key: str
    ) -> AssistantResult:
        
        contents = self._build_google_contents(message, conversation, screen_image)
        tool_events: list[dict[str, Any]] = []

        # Determine if session has attachments (enables search_session_docs tool)
        has_session_docs = False
        if session_id and self.knowledge_service:
            has_session_docs = bool(self.memory_store.get_session_attachments(session_id))

        if contents and contents[-1]["role"] == "user":
            multi_tool_reminder = (
                 "\n\n[SYSTEM INSTRUCTION: Analyze the user's request carefully. If the prompt contains multiple distinct requests (e.g., asking about one topic on the web AND another topic in local files), you MUST execute MULTIPLE tool calls in parallel or sequence before generating your final text response. Do not skip any part of the query. Only answer after ALL relevant tools have returned data.]"
            )

            if "parts" in contents[-1] and len(contents[-1]["parts"]) > 0:
                if "text" in contents[-1]["parts"][0]:
                    contents[-1]["parts"][0]["text"] += multi_tool_reminder

        # Tool execution loop
        for _ in range(100):
            response = self._generate_google_content(
                contents, instructions,
                web_search_only=web_search_only,
                offline_mode=offline_mode,
                enable_session_docs=has_session_docs,
                current_model=current_model,
                current_api_key=current_api_key
            )
            function_calls = self._extract_google_function_calls(response)
                
            # If no function calls, return text
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
                    self.knowledge_service,
                    self.web_search_service,
                    name=function_call.get("name", ""),
                    arguments=function_call.get("args") or {},
                    call_id=function_call.get("id"),
                    session_id=session_id,
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

    def _generate_google_content(
        self, contents: list[dict[str, Any]], instructions: str, 
        web_search_only: bool, offline_mode: bool, enable_session_docs: bool,
        current_model: str, current_api_key: str
    ) -> dict[str, Any]:
        
        endpoint = API_URL_GOOGLE.format(model=quote(current_model, safe=""))
        payload = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": contents,
            "tools": build_rest_tools(
                enable_knowledge=self.knowledge_service is not None and self.knowledge_service.kb_retriever is not None,
                web_search_only=web_search_only,
                offline_mode=offline_mode,
                enable_session_docs=enable_session_docs,
            ),
            "generationConfig": {"temperature": 0.7},
        }
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": current_api_key,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=600) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise LLMClientError(f"Google API error ({exc.code}): {details}") from exc
        except URLError as exc:
            raise LLMClientError(f"Unable to reach the Google API: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMClientError(f"Google API is taking too long to respond (Timeout).") from exc

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