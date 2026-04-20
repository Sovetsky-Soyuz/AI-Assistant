# Client Architecture and Factory Pattern

<cite>
**Referenced Files in This Document**
- [llm_client.py](file://backend/api_clients/llm_client.py)
- [__init__.py](file://backend/api_clients/__init__.py)
- [config.py](file://backend/config.py)
- [server.py](file://backend/server.py)
- [orbit_brain.py](file://backend/core/orbit_brain.py)
- [memory_store.py](file://backend/core/memory_store.py)
- [web_search.py](file://backend/tools/web_search.py)
- [README.md](file://README.md)
</cite>

## Update Summary
**Changes Made**
- Updated LLMAssistant class to use async/await patterns with httpx integration
- Added hybrid routing mode with dynamic model selection
- Enhanced error handling with improved httpx error mapping
- Updated tool execution to use asyncio.to_thread for better performance
- Added new routing_mode parameter and override_provider/model functionality
- Modernized client architecture from synchronous urllib-based to asynchronous httpx-based implementation

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)
10. [Appendices](#appendices)

## Introduction
This document explains the LLM client architecture with a focus on the modernized asynchronous implementation using httpx, the factory-like routing mechanism that selects the appropriate client implementation based on active provider settings, the client abstraction layer, and the main LLMAssistant class initialization. The system now features async/await patterns, improved error handling, hybrid routing capabilities, and enhanced tool execution handling. It documents the exception handling model, the AssistantResult data structure, provider detection logic, conversation management, multimodal input handling (text and screen images), parameter validation, and the expanded chat method signature with new routing capabilities.

## Project Structure
The LLM client architecture centers around the backend/api_clients module, which exposes a unified asynchronous interface for interacting with multiple LLM providers. The server integrates the client with memory, tools, and configuration to deliver a cohesive assistant experience with modern async patterns.

```mermaid
graph TB
subgraph "Backend"
CFG["Settings (config.py)"]
MS["MemoryStore (memory_store.py)"]
KB["KnowledgeService (tools/knowledge.py)"]
WS["WebSearchService (tools/web_search.py)"]
OB["OrbitBrain (orbit_brain.py)"]
AC["LLMAssistant (llm_client.py)"]
SRV["HTTP Server (server.py)"]
end
SRV --> AC
AC --> CFG
AC --> MS
AC --> OB
AC --> WS
AC --> KB
```

**Diagram sources**
- [server.py:23-63](file://backend/server.py#L23-L63)
- [llm_client.py:38-46](file://backend/api_clients/llm_client.py#L38-L46)
- [config.py:20-76](file://backend/config.py#L20-L76)
- [memory_store.py:67-117](file://backend/core/memory_store.py#L67-L117)
- [orbit_brain.py:302-386](file://backend/core/orbit_brain.py#L302-L386)
- [web_search.py:53-104](file://backend/tools/web_search.py#L53-L104)

**Section sources**
- [README.md:164-201](file://README.md#L164-L201)
- [server.py:23-63](file://backend/server.py#L23-L63)

## Core Components
- **LLMAssistant**: The central asynchronous client abstraction that orchestrates provider selection, conversation construction, tool invocation, and response synthesis using httpx.
- **LLMClientError**: A dedicated exception type for client-side failures with enhanced error mapping from httpx exceptions.
- **AssistantResult**: A data structure encapsulating the assistant's textual reply and tool events.
- **Settings**: Centralized configuration controlling provider selection, API keys, model choices, and new hybrid routing capabilities.
- **MemoryStore**: Persistent storage for sessions, messages, tasks, notes, and cached tool results with MongoDB integration.
- **Tools**: Weather, News, Web Search, and Knowledge services used by the brain and client.

**Section sources**
- [llm_client.py:28-36](file://backend/api_clients/llm_client.py#L28-L36)
- [llm_client.py:38-46](file://backend/api_clients/llm_client.py#L38-L46)
- [config.py:20-76](file://backend/config.py#L20-L76)
- [memory_store.py:67-117](file://backend/core/memory_store.py#L67-L117)
- [orbit_brain.py:302-386](file://backend/core/orbit_brain.py#L302-L386)
- [web_search.py:53-104](file://backend/tools/web_search.py#L53-L104)

## Architecture Overview
The system routes requests to provider-specific implementations based on active provider settings with enhanced hybrid routing capabilities. The LLMAssistant builds system instructions and messages, invokes provider APIs asynchronously, executes tool calls, and aggregates results into AssistantResult with improved error handling.

```mermaid
sequenceDiagram
participant Client as "HTTP Client"
participant Server as "AssistantApplication (server.py)"
participant Assistant as "LLMAssistant (llm_client.py)"
participant Brain as "OrbitBrain (orbit_brain.py)"
participant Tools as "Tools (weather/news/web_search/knowledge)"
participant Provider as "Provider API"
Client->>Server : POST /api/chat {message, conversation, ...}
Server->>Assistant : await chat(message, conversation, ...)
Assistant->>Brain : build_system_instruction(...)
Assistant->>Assistant : detect active_provider
alt Dynamic Routing Mode
Assistant->>Assistant : classify_task_complexity
Assistant->>Assistant : upgrade_to_hybrid_model
end
alt OpenRouter/LM Studio/Ollama
Assistant->>Provider : POST chat/completions (async)
else Google
Assistant->>Provider : POST generateContent (async)
end
Provider-->>Assistant : response (text/tool_calls)
Assistant->>Tools : run_tool_call(...) via asyncio.to_thread
Tools-->>Assistant : tool events + function responses
Assistant-->>Server : AssistantResult(reply, tool_events)
Server-->>Client : {reply, toolEvents, memory, model}
```

**Diagram sources**
- [server.py:276-321](file://backend/server.py#L276-L321)
- [llm_client.py:47-78](file://backend/api_clients/llm_client.py#L47-L78)
- [llm_client.py:82-216](file://backend/api_clients/llm_client.py#L82-L216)
- [llm_client.py:220-272](file://backend/api_clients/llm_client.py#L220-L272)
- [orbit_brain.py:302-386](file://backend/core/orbit_brain.py#L302-L386)
- [web_search.py:53-104](file://backend/tools/web_search.py#L53-L104)

## Detailed Component Analysis

### LLMAssistant: Modernized Asynchronous Client with Hybrid Routing
- **Initialization**: Receives Settings, MemoryStore, KnowledgeService, and WebSearchService. Creates WeatherService and NewsService instances.
- **Async chat method**: Validates API key presence, constructs system instructions via OrbitBrain, detects active provider, and dispatches to provider-specific async handlers with enhanced routing capabilities.
- **Hybrid Routing**: New dynamic routing mode automatically classifies task complexity and upgrades to hybrid models for complex tasks.
- **Provider detection**: Routes to `_chat_openrouter` for openrouter, lm_studio, and ollama; otherwise routes to `_chat_google`.
- **Multimodal input**: Supports screen_image payloads for both provider branches with improved data URL parsing.
- **Conversation management**: Maintains conversation snapshots and appends user/system messages appropriately.
- **Parameter validation**: Enforces non-empty message and API key presence; raises LLMClientError on failure.
- **Tool orchestration**: Executes tool calls returned by provider APIs asynchronously using asyncio.to_thread and aggregates tool events.

**Updated** The LLMAssistant now uses async/await patterns throughout, httpx for HTTP requests, and enhanced error handling with better exception mapping.

```mermaid
flowchart TD
Start(["LLMAssistant.chat (async)"]) --> ValidateKey["Validate API Key"]
ValidateKey --> |Missing| RaiseError["Raise LLMClientError"]
ValidateKey --> |Present| BuildInstructions["Build System Instructions"]
BuildInstructions --> CheckHybrid{"routing_mode == dynamic?"}
CheckHybrid --> |Yes| ClassifyTask["Classify Task Complexity"]
ClassifyTask --> UpgradeModel["Upgrade to Hybrid Model"]
CheckHybrid --> |No| DetectProvider{"Active Provider"}
UpgradeModel --> DetectProvider
DetectProvider --> |openrouter/lm_studio/ollama| OpenRouter["_chat_openrouter (async)"]
DetectProvider --> |google| Google["_chat_google (async)"]
OpenRouter --> End(["AssistantResult"])
Google --> End
```

**Diagram sources**
- [llm_client.py:38-78](file://backend/api_clients/llm_client.py#L38-L78)
- [llm_client.py:82-216](file://backend/api_clients/llm_client.py#L82-L216)
- [llm_client.py:220-272](file://backend/api_clients/llm_client.py#L220-L272)

**Section sources**
- [llm_client.py:38-78](file://backend/api_clients/llm_client.py#L38-L78)
- [llm_client.py:82-216](file://backend/api_clients/llm_client.py#L82-L216)
- [llm_client.py:220-272](file://backend/api_clients/llm_client.py#L220-L272)

### LLMClientError and AssistantResult
- **LLMClientError**: A dedicated runtime exception used to signal client-side failures with enhanced error mapping from httpx exceptions (e.g., missing API key, provider errors).
- **AssistantResult**: Encapsulates the assistant's reply text and a list of tool events generated during tool execution.

```mermaid
classDiagram
class LLMClientError {
+RuntimeError
+Enhanced error mapping from httpx exceptions
}
class AssistantResult {
+string reply
+dict[] tool_events
}
```

**Diagram sources**
- [llm_client.py:28-36](file://backend/api_clients/llm_client.py#L28-L36)
- [llm_client.py:29-32](file://backend/api_clients/llm_client.py#L29-L32)

**Section sources**
- [llm_client.py:28-36](file://backend/api_clients/llm_client.py#L28-L36)
- [llm_client.py:29-32](file://backend/api_clients/llm_client.py#L29-L32)

### Enhanced Provider Detection Logic and Hybrid Routing
- **Active provider selection** is driven by Settings.active_provider with new override capabilities.
- **Hybrid routing**: New dynamic routing mode automatically classifies task complexity and upgrades to hybrid models for complex tasks.
- **Routing conditions**:
  - openrouter, lm_studio, ollama → `_chat_openrouter` (async)
  - google → `_chat_google` (async)
- **Endpoint selection** varies by provider and configuration (e.g., OpenRouter, LM Studio, Ollama vs. Google REST API).
- **Model override**: New override_model parameter allows explicit model specification.

**Updated** Added hybrid routing capabilities and enhanced provider detection logic.

```mermaid
flowchart TD
A["Settings.active_provider"] --> B{"openrouter/lm_studio/ollama?"}
B --> |Yes| C["_chat_openrouter (async)"]
B --> |No| D["_chat_google (async)"]
E["routing_mode == dynamic?"] --> F{"Task complexity == complex?"}
F --> |Yes| G["Upgrade to hybrid model"]
F --> |No| H["Use default model"]
G --> B
H --> B
```

**Diagram sources**
- [llm_client.py:74-77](file://backend/api_clients/llm_client.py#L74-L77)
- [config.py:25-52](file://backend/config.py#L25-L52)

**Section sources**
- [llm_client.py:74-77](file://backend/api_clients/llm_client.py#L74-L77)
- [config.py:25-52](file://backend/config.py#L25-L52)

### Conversation Management and Multimodal Inputs
- **Conversation snapshot**: Recent conversation entries are included in system instructions and transformed into provider-specific message formats.
- **Multimodal inputs**:
  - OpenRouter branch: Accepts screen_image as a data URL; splits header/mime and appends as image_url.
  - Google branch: Accepts screen_image as a data URL; parses header/mime and appends inlineData.
- **Message construction**:
  - OpenRouter: Builds mixed content (text + image_url) under a user role.
  - Google: Builds parts array with text and inlineData.

```mermaid
flowchart TD
Start(["Incoming message + screen_image"]) --> CheckImage{"screen_image present?"}
CheckImage --> |No| BuildText["Build text-only message"]
CheckImage --> |Yes| ParseHeader["Parse data URL header/mime"]
ParseHeader --> AppendImage["Append image part"]
BuildText --> Send["Send to provider (async)"]
AppendImage --> Send
```

**Diagram sources**
- [llm_client.py:97-102](file://backend/api_clients/llm_client.py#L97-L102)
- [llm_client.py:274-291](file://backend/api_clients/llm_client.py#L274-L291)

**Section sources**
- [llm_client.py:97-102](file://backend/api_clients/llm_client.py#L97-L102)
- [llm_client.py:274-291](file://backend/api_clients/llm_client.py#L274-L291)

### Enhanced Tool Orchestration and Execution
- **Tool discovery**: build_rest_tools generates function declarations based on mode and capabilities (web search only, offline mode, session docs).
- **Tool execution**: run_tool_call dispatches to specific services (weather, news, memory, tasks, notes, knowledge, web search) using asyncio.to_thread for better performance and returns ToolRunResult with event and function_response.
- **Loop control**: Both provider branches enforce a maximum iteration limit to prevent infinite tool loops.
- **Error handling**: Enhanced error handling with proper exception mapping and graceful degradation.

**Updated** Tool execution now uses asyncio.to_thread for better performance and improved error handling.

```mermaid
flowchart TD
Start(["Provider returns tool_calls"]) --> Iterate["Iterate tool_calls"]
Iterate --> Dispatch["run_tool_call(name, args) via asyncio.to_thread"]
Dispatch --> Event["Append tool event"]
Event --> AppendToolMsg["Append tool result to messages"]
AppendToolMsg --> Next{"More tool_calls?"}
Next --> |Yes| Iterate
Next --> |No| Reply["Return AssistantResult"]
```

**Diagram sources**
- [orbit_brain.py:361-386](file://backend/core/orbit_brain.py#L361-L386)
- [orbit_brain.py:389-501](file://backend/core/orbit_brain.py#L389-L501)
- [llm_client.py:185-215](file://backend/api_clients/llm_client.py#L185-L215)
- [llm_client.py:255-271](file://backend/api_clients/llm_client.py#L255-L271)

**Section sources**
- [orbit_brain.py:361-386](file://backend/core/orbit_brain.py#L361-L386)
- [orbit_brain.py:389-501](file://backend/core/orbit_brain.py#L389-L501)
- [llm_client.py:185-215](file://backend/api_clients/llm_client.py#L185-L215)
- [llm_client.py:255-271](file://backend/api_clients/llm_client.py#L255-L271)

### Enhanced Chat Method Signature and Parameters
The chat method now accepts the following parameters:
- **message**: The user's input text.
- **conversation**: Optional list of prior messages (role/text).
- **screen_image**: Optional base64 data URL of a screen image.
- **mode**: Mode selection (simple, copilot, coach).
- **coach_topic**: Topic for coach mode.
- **coach_level**: Level for coach mode.
- **preferred_language**: Preferred language hint.
- **web_search_only**: Boolean toggle to prioritize web search.
- **offline_mode**: Boolean toggle to disable web search.
- **session_id**: Optional session identifier for knowledge/session docs.
- **routing_mode**: New parameter for routing strategy (fixed, dynamic).
- **override_provider**: New parameter to override active provider.
- **override_model**: New parameter to override default model.
- **use_memory**: New parameter to control memory usage.

**Updated** Added new routing_mode, override_provider, override_model, and use_memory parameters for enhanced flexibility.

Validation:
- Non-empty message enforced by server handler.
- API key presence enforced by LLMAssistant.
- New hybrid routing mode with automatic task classification.

**Section sources**
- [llm_client.py:47-59](file://backend/api_clients/llm_client.py#L47-L59)
- [server.py:295-307](file://backend/server.py#L295-L307)

### Example Patterns

#### Client Instantiation
- The server constructs LLMAssistant with Settings, MemoryStore, KnowledgeService, and WebSearchService.

**Section sources**
- [server.py:60](file://backend/server.py#L60)

#### Conversation State Management
- Sessions and messages are managed via MemoryStore. The server exposes endpoints to create/update sessions, add messages, and retrieve histories.

**Section sources**
- [server.py:110-143](file://backend/server.py#L110-L143)
- [server.py:188-202](file://backend/server.py#L188-L202)
- [memory_store.py:579-646](file://backend/core/memory_store.py#L579-L646)
- [memory_store.py:652-685](file://backend/core/memory_store.py#L652-L685)

#### Enhanced Error Handling Patterns
- **Missing API key**: LLMAssistant raises LLMClientError.
- **Provider errors**: Enhanced httpx.HTTPStatusError mapped to LLMClientError with contextual details.
- **Tool errors**: run_tool_call catches exceptions and returns error events.
- **Connection errors**: Improved httpx timeout handling with 600-second timeout.
- **Hybrid routing**: Automatic model upgrade for complex tasks with logging.

**Updated** Enhanced error handling with httpx integration and improved exception mapping.

**Section sources**
- [llm_client.py:60-61](file://backend/api_clients/llm_client.py#L60-L61)
- [llm_client.py:161-174](file://backend/api_clients/llm_client.py#L161-L174)
- [llm_client.py:319-323](file://backend/api_clients/llm_client.py#L319-L323)
- [orbit_brain.py:490-493](file://backend/core/orbit_brain.py#L490-L493)

## Dependency Analysis
The LLMAssistant depends on configuration, memory, tools, and brain utilities with enhanced async dependencies. The server composes these dependencies and exposes a clean HTTP API with async support.

```mermaid
graph LR
Settings["Settings (config.py)"] --> LLMA["LLMAssistant (llm_client.py)"]
Memory["MemoryStore (memory_store.py)"] --> LLMA
Brain["OrbitBrain (orbit_brain.py)"] --> LLMA
ToolsWS["WebSearchService (web_search.py)"] --> LLMA
ToolsKB["KnowledgeService (tools/knowledge.py)"] --> LLMA
Server["AssistantApplication (server.py)"] --> LLMA
LLMA --> Provider["Provider APIs (async)"]
```

**Diagram sources**
- [llm_client.py:38-46](file://backend/api_clients/llm_client.py#L38-L46)
- [config.py:20-76](file://backend/config.py#L20-L76)
- [memory_store.py:67-117](file://backend/core/memory_store.py#L67-L117)
- [orbit_brain.py:302-386](file://backend/core/orbit_brain.py#L302-L386)
- [web_search.py:53-104](file://backend/tools/web_search.py#L53-L104)
- [server.py:23-63](file://backend/server.py#L23-L63)

**Section sources**
- [llm_client.py:38-46](file://backend/api_clients/llm_client.py#L38-L46)
- [server.py:23-63](file://backend/server.py#L23-L63)

## Performance Considerations
- **Async HTTP requests**: Using httpx.AsyncClient for concurrent provider requests with proper timeout handling.
- **Thread pool execution**: Tool calls executed via asyncio.to_thread to prevent blocking the event loop.
- **Provider branching**: Choosing openrouter/lm_studio/ollama avoids Google REST API overhead; Google branch uses a single generateContent call per iteration.
- **Tool loop limits**: Both branches cap iterations to prevent excessive latency.
- **Message windowing**: Only recent conversation entries are forwarded to reduce payload sizes.
- **Multimodal payloads**: Image data URLs are parsed once and appended as minimal parts.
- **Hybrid routing**: Automatic model upgrade for complex tasks reduces retry attempts.
- **Connection pooling**: httpx AsyncClient provides efficient connection reuse.

**Updated** Added async performance considerations and thread pool execution benefits.

## Troubleshooting Guide
Common issues and resolutions:
- **Missing API key**: Ensure ACTIVE_PROVIDER and corresponding API key are configured; LLMAssistant raises LLMClientError if missing.
- **Provider connectivity**: Enhanced httpx.HTTPStatusError mapped to LLMClientError with details; verify network and endpoint URLs.
- **Tool failures**: run_tool_call returns error events; inspect tool events and logs.
- **Conversation anomalies**: Verify session_id correctness and ensure MemoryStore is reachable.
- **Async timeouts**: Check httpx timeout settings (600 seconds) and network connectivity.
- **Hybrid routing issues**: Verify enable_hybrid setting and hybrid model configuration.
- **Thread pool exhaustion**: Monitor asyncio.to_thread usage and adjust tool execution patterns.

**Updated** Added async-specific troubleshooting and hybrid routing considerations.

**Section sources**
- [llm_client.py:60-61](file://backend/api_clients/llm_client.py#L60-L61)
- [llm_client.py:161-174](file://backend/api_clients/llm_client.py#L161-L174)
- [llm_client.py:319-323](file://backend/api_clients/llm_client.py#L319-L323)
- [orbit_brain.py:490-493](file://backend/core/orbit_brain.py#L490-L493)

## Conclusion
The LLM client architecture employs a modernized asynchronous abstraction layer (LLMAssistant) with provider-specific routing, robust error handling (LLMClientError), and a consistent result format (AssistantResult). The system integrates tightly with memory, tools, and configuration to support multimodal inputs, conversation management, and flexible search modes with enhanced hybrid routing capabilities. The server composes these components into a cohesive HTTP API with async support, enabling reliable and extensible assistant behavior across providers with improved performance and reliability.

## Appendices

### API Exposure and Initialization
- LLMAssistant is exported via backend/api_clients/__init__.py.
- The server initializes LLMAssistant with Settings, MemoryStore, KnowledgeService, and WebSearchService.

**Section sources**
- [__init__.py:1-3](file://backend/api_clients/__init__.py#L1-L3)
- [server.py:60](file://backend/server.py#L60)

### New Hybrid Routing Configuration
- **enable_hybrid**: Enable/disable hybrid routing mode.
- **hybrid_provider**: Provider for complex tasks (default: openrouter).
- **hybrid_model**: Model for complex tasks (default: openai/gpt-4o).
- **routing_mode**: fixed or dynamic routing strategy.

**Section sources**
- [config.py:39-43](file://backend/config.py#L39-L43)
- [llm_client.py:89-96](file://backend/api_clients/llm_client.py#L89-L96)