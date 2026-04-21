# AI Assistant Engine

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [run.py](file://run.py)
- [backend/config.py](file://backend/config.py)
- [backend/server.py](file://backend/server.py)
- [backend/api_clients/llm_client.py](file://backend/api_clients/llm_client.py)
- [backend/api_clients/gemini_client.py](file://backend/api_clients/gemini_client.py)
- [backend/core/orbit_brain.py](file://backend/core/orbit_brain.py)
- [backend/core/memory_store.py](file://backend/core/memory_store.py)
- [backend/tools/web_search.py](file://backend/tools/web_search.py)
- [backend/tools/knowledge.py](file://backend/tools/knowledge.py)
- [backend/tools/weather.py](file://backend/tools/weather.py)
- [backend/tools/news.py](file://backend/tools/news.py)
- [frontend/index.html](file://frontend/index.html)
- [frontend/scripts/app.js](file://frontend/scripts/app.js)
</cite>

## Update Summary
**Changes Made**
- Added Smart Hybrid Mode with intelligent model routing capabilities
- Enhanced operational modes to include dynamic provider switching
- Updated system prompts and instruction following with hybrid mode awareness
- Added automatic task complexity classification system
- Integrated Smart Routing toggle in the frontend UI
- Enhanced LLM client with dynamic routing logic
- Added new hybrid provider configuration settings
- Improved memory management with enhanced persistence features

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
This document describes the AI assistant engine that powers the Orbit Virtual Assistant. It explains the reasoning engine architecture, conversation management, tool orchestration, system prompts, instruction-following mechanisms, and context preservation strategies. The engine now features Smart Hybrid Mode with intelligent model routing, automatic task complexity classification, and dynamic provider switching capabilities. It covers operational modes (simple, copilot, coach), session handling, memory integration, tool calling workflows, function execution patterns, result processing, examples of conversation flows, decision-making processes, error recovery, performance considerations, memory management, and extensibility for adding new capabilities.

## Project Structure
The assistant is organized into a backend server, provider-agnostic LLM clients, a reasoning brain module, a MongoDB-backed memory store, and tool integrations for web search, knowledge (RAG), weather, and news. The system now includes Smart Hybrid Mode with dynamic routing capabilities.

```mermaid
graph TB
subgraph "Frontend"
FE_Index["index.html"]
FE_App["app.js"]
FE_Assets["styles.css"]
FE_Avatar["avatar-renderer.js / avatar-worker.js"]
FE_Routing["Smart Routing Toggle"]
end
subgraph "Backend"
Server["server.py"]
Config["config.py"]
LLMClient["api_clients/llm_client.py"]
GeminiClient["api_clients/gemini_client.py"]
Brain["core/orbit_brain.py"]
Memory["core/memory_store.py"]
Tools_WS["tools/web_search.py"]
Tools_KB["tools/knowledge.py"]
Tools_Weather["tools/weather.py"]
Tools_News["tools/news.py"]
end
FE_Index --> Server
FE_App --> Server
FE_Assets --> Server
FE_Avatar --> Server
FE_Routing --> Server
Server --> LLMClient
Server --> Memory
Server --> Tools_KB
Server --> Tools_WS
Server --> Tools_Weather
Server --> Tools_News
LLMClient --> Brain
LLMClient --> Memory
LLMClient --> Tools_WS
LLMClient --> Tools_KB
LLMClient --> Tools_Weather
LLMClient --> Tools_News
GeminiClient --> Brain
GeminiClient --> Memory
GeminiClient --> Tools_Weather
GeminiClient --> Tools_News
```

**Diagram sources**
- [backend/server.py:23-63](file://backend/server.py#L23-L63)
- [backend/api_clients/llm_client.py:38-46](file://backend/api_clients/llm_client.py#L38-L46)
- [backend/api_clients/gemini_client.py:36-42](file://backend/api_clients/gemini_client.py#L36-L42)
- [backend/core/orbit_brain.py:74-268](file://backend/core/orbit_brain.py#L74-L268)
- [backend/core/memory_store.py:67-117](file://backend/core/memory_store.py#L67-L117)
- [backend/tools/web_search.py:53-104](file://backend/tools/web_search.py#L53-L104)
- [backend/tools/knowledge.py:88-140](file://backend/tools/knowledge.py#L88-L140)
- [backend/tools/weather.py:48-75](file://backend/tools/weather.py#L48-L75)
- [backend/tools/news.py:22-60](file://backend/tools/news.py#L22-L60)
- [frontend/index.html:156-160](file://frontend/index.html#L156-L160)

**Section sources**
- [README.md:164-201](file://README.md#L164-L201)
- [backend/server.py:23-63](file://backend/server.py#L23-L63)

## Core Components
- Configuration and settings loader: centralizes environment variables and provider/model selection, now includes hybrid mode settings.
- HTTP server and API endpoints: serves frontend, exposes session/message/tool endpoints, and orchestrates chat with routing mode support.
- LLM clients: provider-agnostic chat logic for Google, OpenRouter, LM Studio, and Ollama with dynamic routing capabilities.
- Reasoning brain: constructs system prompts, declares tools, and dispatches tool calls with hybrid mode awareness.
- Memory store: MongoDB-backed persistence for sessions, messages, profile, tasks, notes, and caches.
- Tools: web search (Tavily + DuckDuckGo), knowledge base (RAG), weather, and news.
- Smart Hybrid Mode: intelligent model routing with automatic task complexity classification and dynamic provider switching.

**Section sources**
- [backend/config.py:55-76](file://backend/config.py#L55-L76)
- [backend/server.py:23-63](file://backend/server.py#L23-L63)
- [backend/api_clients/llm_client.py:38-46](file://backend/api_clients/llm_client.py#L38-L46)
- [backend/core/orbit_brain.py:74-268](file://backend/core/orbit_brain.py#L74-L268)
- [backend/core/memory_store.py:67-117](file://backend/core/memory_store.py#L67-L117)
- [backend/tools/web_search.py:53-104](file://backend/tools/web_search.py#L53-L104)
- [backend/tools/knowledge.py:88-140](file://backend/tools/knowledge.py#L88-L140)
- [backend/tools/weather.py:48-75](file://backend/tools/weather.py#L48-L75)
- [backend/tools/news.py:22-60](file://backend/tools/news.py#L22-L60)

## Architecture Overview
The assistant runs a threaded HTTP server that exposes REST endpoints with Smart Hybrid Mode support. The chat flow delegates to an LLM client based on the selected provider and routing mode. The client builds a system instruction and message history, performs automatic task complexity classification, dynamically selects appropriate models/providers, invokes the LLM with function-declared tools, executes tool calls via the brain dispatcher, persists tool events and results in memory, and returns a final reply with tool events.

```mermaid
sequenceDiagram
participant Client as "Browser"
participant Server as "AssistantApplication"
participant LLM as "LLMAssistant"
participant Brain as "build_system_instruction/run_tool_call"
participant Tools as "Weather/News/Web/Knowledge"
participant Mem as "MemoryStore"
Client->>Server : POST /api/chat {message, conversation, mode, routingMode, ...}
Server->>LLM : chat(message, conversation, mode, routingMode, ...)
LLM->>LLM : classify_task_complexity(message)
LLM->>LLM : select_target_provider(model)
LLM->>Brain : build_system_instruction(...)
LLM->>LLM : prepare messages + tools
LLM->>LLM : send request to provider
alt Tool calls present
LLM->>Brain : run_tool_call(name, args, session_id)
Brain->>Tools : execute tool
Tools-->>Brain : result
Brain->>Mem : persist tool events/results
LLM->>LLM : append tool result as user parts
LLM->>LLM : send follow-up request
end
LLM-->>Server : {reply, tool_events}
Server-->>Client : JSON response
```

**Diagram sources**
- [backend/server.py:276-321](file://backend/server.py#L276-L321)
- [backend/api_clients/llm_client.py:47-78](file://backend/api_clients/llm_client.py#L47-L78)
- [backend/core/orbit_brain.py:302-356](file://backend/core/orbit_brain.py#L302-L356)
- [backend/core/orbit_brain.py:389-501](file://backend/core/orbit_brain.py#L389-L501)
- [backend/core/memory_store.py:188-250](file://backend/core/memory_store.py#L188-L250)

## Detailed Component Analysis

### Smart Hybrid Mode and Dynamic Routing
- **Task Complexity Classification**: Automatic classification of user tasks into "simple" or "complex" categories based on message length (>800 characters) and keyword analysis (analyze, optimize, refactor, architect, explain code, calculate, prove, derive, logic).
- **Dynamic Provider Switching**: When routing mode is "dynamic" and hybrid mode is enabled, complex tasks automatically switch from the default provider/model to the hybrid provider/model.
- **Automatic Model Upgrade**: Complex tasks trigger automatic upgrade to higher-capability models (e.g., GPT-4o) while simple tasks use the default model for cost efficiency.
- **Fallback Handling**: If hybrid mode is disabled but dynamic routing is requested, the system falls back to using the default provider/model.
- **Hybrid Configuration**: New hybrid provider settings allow separate configuration of provider and model for complex tasks.

```mermaid
flowchart TD
Start(["Task Received"]) --> Classify["Classify Task Complexity"]
Classify --> Simple{"Simple Task?"}
Simple --> |Yes| UseDefault["Use Default Provider/Model"]
Simple --> |No| CheckHybrid{"Hybrid Mode Enabled?"}
CheckHybrid --> |Yes| Switch["Switch to Hybrid Provider/Model"]
CheckHybrid --> |No| UseDefault
Switch --> Route["Route to Hybrid Provider"]
UseDefault --> Route
Route --> Process["Process Task"]
Process --> End(["Return Response"])
```

**Diagram sources**
- [backend/api_clients/llm_client.py:59-101](file://backend/api_clients/llm_client.py#L59-L101)

**Section sources**
- [backend/api_clients/llm_client.py:59-101](file://backend/api_clients/llm_client.py#L59-L101)
- [backend/api_clients/llm_client.py:84-87](file://backend/api_clients/llm_client.py#L84-L87)
- [backend/server.py:38](file://backend/server.py#L38)

### System Prompts and Instruction Following
- Base system prompt defines the assistant persona and rules.
- Mode-specific prompts tailor behavior for simple, copilot, and coach modes.
- Search-mode annotations adjust tool availability and bias when toggled (web search only, offline).
- Language hints influence response language preferences.
- Recent conversation and memory brief snapshots are injected to preserve context.
- **Hybrid Mode Awareness**: System instructions now account for dynamic routing capabilities and provider switching.

```mermaid
flowchart TD
Start(["Build System Instruction"]) --> Mode["Normalize mode<br/>and select mode prompt"]
Mode --> SearchMode{"Web Search Only / Offline?"}
SearchMode --> |Yes| Bias["Adjust tool availability and bias"]
SearchMode --> |No| Keep["Keep default tool set"]
Bias --> Lang["Apply language hint"]
Keep --> Lang
Lang --> Snapshot["Build memory brief + recent conversation snapshot"]
Snapshot --> Hybrid["Check Hybrid Mode Status"]
Hybrid --> Inject["Inject into system instruction"]
Inject --> End(["Return instruction"])
```

**Diagram sources**
- [backend/core/orbit_brain.py:302-356](file://backend/core/orbit_brain.py#L302-L356)

**Section sources**
- [backend/core/orbit_brain.py:14-32](file://backend/core/orbit_brain.py#L14-L32)
- [backend/core/orbit_brain.py:35-56](file://backend/core/orbit_brain.py#L35-L56)
- [backend/core/orbit_brain.py:302-356](file://backend/core/orbit_brain.py#L302-L356)

### Operational Modes and Context Preservation
- Simple mode: concise answers, minimal memory usage.
- Copilot mode: proactive planning, screen-aware suggestions, deeper memory.
- Coach mode: expert tutoring with RAG-driven quizzes and roadmaps.
- **Smart Hybrid Mode**: Intelligent model routing with automatic task complexity classification and dynamic provider switching.
- Context preservation: recent conversation snapshot and memory brief injected into the system instruction; session-scoped document search enabled when attachments exist.

**Section sources**
- [backend/core/orbit_brain.py:35-56](file://backend/core/orbit_brain.py#L35-L56)
- [backend/core/orbit_brain.py:283-299](file://backend/core/orbit_brain.py#L283-L299)
- [backend/core/orbit_brain.py:302-356](file://backend/core/orbit_brain.py#L302-L356)

### Tool Orchestration and Execution Patterns
- Function declarations define available tools: weather, news, memory, tasks, notes, web search, local knowledge, and session docs.
- Tool availability is dynamically adjusted by mode and provider:
  - Web search only: both web and local tools available; system prompt biases toward web.
  - Offline: web tool stripped; only local tools usable.
  - Session docs: enabled when session has attachments.
- Tool dispatcher executes tools and records events; results are appended to the conversation to guide the LLM's final answer.
- **Dynamic Routing Integration**: Tool calls are executed through the selected provider/model based on task complexity classification.

```mermaid
flowchart TD
A["LLM returns tool_calls"] --> B["Iterate tool_calls"]
B --> C{"Tool name"}
C --> |get_weather| D["WeatherService.fetch_weather"]
C --> |get_latest_news| E["NewsService.fetch_news"]
C --> |remember_note/update_profile/add_task/complete_task/delete_task/get_tasks/get_notes| F["MemoryStore operations"]
C --> |search_local_docs| G["KnowledgeService.search"]
C --> |search_session_docs| H["KnowledgeService.search_session"]
C --> |search_web| I["WebSearchService.search"]
D --> J["Persist tool event + cache"]
E --> J
F --> J
G --> J
H --> J
I --> J
J --> K["Append tool result as user parts"]
K --> L["Next iteration or return final reply"]
```

**Diagram sources**
- [backend/core/orbit_brain.py:389-501](file://backend/core/orbit_brain.py#L389-L501)
- [backend/api_clients/llm_client.py:185-214](file://backend/api_clients/llm_client.py#L185-L214)
- [backend/core/memory_store.py:475-495](file://backend/core/memory_store.py#L475-L495)

**Section sources**
- [backend/core/orbit_brain.py:74-268](file://backend/core/orbit_brain.py#L74-L268)
- [backend/core/orbit_brain.py:361-386](file://backend/core/orbit_brain.py#L361-L386)
- [backend/core/orbit_brain.py:389-501](file://backend/core/orbit_brain.py#L389-L501)
- [backend/api_clients/llm_client.py:185-214](file://backend/api_clients/llm_client.py#L185-L214)

### Conversation Management and Sessions
- Sessions: creation, listing, updates (title/pinned/archived), and deletion with cascading cleanup of messages, attachments, and session chunks.
- Messages: per-session CRUD with ordering by creation time.
- History: legacy compatibility for bulk history updates; new endpoints prefer per-session message management.
- Attachments: upload base64 files, parse and index for session-scoped search, and track metadata.

```mermaid
classDiagram
class MemoryStore {
+create_session(title)
+get_sessions(include_archived)
+update_session(session_id, ...)
+delete_session(session_id)
+add_message(session_id, role, text)
+get_messages(session_id, limit)
+delete_message(message_id)
+add_session_attachment(session_id, filename, file_type, file_size, storage_path)
+get_session_attachments(session_id)
+delete_session_attachment(attachment_id)
+get_state()
+get_brief()
}
```

**Diagram sources**
- [backend/core/memory_store.py:579-646](file://backend/core/memory_store.py#L579-L646)
- [backend/core/memory_store.py:652-690](file://backend/core/memory_store.py#L652-L690)
- [backend/core/memory_store.py:754-796](file://backend/core/memory_store.py#L754-L796)

**Section sources**
- [backend/server.py:106-167](file://backend/server.py#L106-L167)
- [backend/server.py:182-266](file://backend/server.py#L182-L266)
- [backend/server.py:329-394](file://backend/server.py#L329-L394)
- [backend/core/memory_store.py:579-646](file://backend/core/memory_store.py#L579-L646)
- [backend/core/memory_store.py:652-690](file://backend/core/memory_store.py#L652-L690)
- [backend/core/memory_store.py:754-796](file://backend/core/memory_store.py#L754-L796)

### Memory Integration and Persistence
- MongoDB collections: sessions, messages, profile, notes, tasks, activity, cache, knowledge_chunks, session_attachments, session_chunks.
- Indexes ensure efficient queries for sessions, messages, and retrievers.
- Activity records track user actions for auditability.
- Caches store last weather and news for quick retrieval.
- **Enhanced Memory Management**: Improved persistence with better state management and memory brief optimization.

```mermaid
erDiagram
SESSIONS {
string session_id PK
string title
string created_at
string updated_at
boolean pinned
boolean archived
}
MESSAGES {
string message_id PK
string session_id FK
string role
string text
string created_at
}
PROFILE {
string _id PK "user_profile"
string display_name
string location
string routine
string updated_at
}
NOTES {
string note_id PK
string category
string text
string created_at
}
TASKS {
string task_id PK
string title
string priority
string due_date
string status
string created_at
string completed_at
}
ACTIVITY {
string activity_id PK
string kind
json payload
string created_at
}
CACHE {
string _id PK "last_weather|last_news"
json data
string updated_at
}
KNOWLEDGE_CHUNKS {
string chunk_id PK
string source_file
string file_hash
int chunk_index
string text
json metadata
string created_at
}
SESSION_ATTACHMENTS {
string attachment_id PK
string session_id FK
string filename
string file_type
int file_size
string storage_path
string created_at
}
SESSION_CHUNKS {
string chunk_id PK
string attachment_id FK
string session_id FK
int chunk_index
string text
json metadata
string created_at
}
SESSIONS ||--o{ MESSAGES : "has"
SESSIONS ||--o{ SESSION_ATTACHMENTS : "has"
SESSION_ATTACHMENTS ||--o{ SESSION_CHUNKS : "indexes"
```

**Diagram sources**
- [backend/core/memory_store.py:23-62](file://backend/core/memory_store.py#L23-L62)
- [backend/core/memory_store.py:119-135](file://backend/core/memory_store.py#L119-L135)

**Section sources**
- [backend/core/memory_store.py:188-250](file://backend/core/memory_store.py#L188-L250)
- [backend/core/memory_store.py:475-495](file://backend/core/memory_store.py#L475-L495)
- [backend/core/memory_store.py:695-748](file://backend/core/memory_store.py#L695-L748)

### Tool Integrations
- Web search: Tavily primary, DuckDuckGo fallback; spinner timer for UX; graceful error handling.
- Knowledge base (RAG): document parsing, chunking, BM25 + optional FAISS hybrid retriever; persistent indexing in MongoDB; session-scoped retriever caching.
- Weather: Open-Meteo geocoding and forecast; advice generation; cache persisted in memory.
- News: Google News RSS feed parsing; clamped item counts; UTC timestamps.

**Section sources**
- [backend/tools/web_search.py:53-104](file://backend/tools/web_search.py#L53-L104)
- [backend/tools/knowledge.py:88-140](file://backend/tools/knowledge.py#L88-L140)
- [backend/tools/knowledge.py:270-298](file://backend/tools/knowledge.py#L270-L298)
- [backend/tools/knowledge.py:337-355](file://backend/tools/knowledge.py#L337-L355)
- [backend/tools/weather.py:48-75](file://backend/tools/weather.py#L48-L75)
- [backend/tools/news.py:22-60](file://backend/tools/news.py#L22-L60)

### LLM Clients and Provider Abstraction
- LLMAssistant: provider-agnostic chat with two paths:
  - Google REST API: constructs contents, extracts function calls, executes tools, and returns replies.
  - OpenRouter/LM Studio/Ollama: constructs messages with tools, handles tool calls, and returns replies.
  - **Dynamic Routing**: Automatic task complexity classification and provider/model switching based on routing mode.
- GeminiAssistant: legacy client for Google Gemini with similar orchestration.

```mermaid
classDiagram
class LLMAssistant {
+chat(message, conversation, screen_image, mode, routing_mode, ...)
-_classify_task_complexity(message)
-_chat_google(...)
-_chat_openrouter(...)
}
class GeminiAssistant {
+chat(message, conversation, screen_image, mode, ...)
-_generate_content(contents, instructions)
-_extract_function_calls(response)
-_extract_text(response)
}
LLMAssistant --> "uses" build_system_instruction
LLMAssistant --> "uses" run_tool_call
GeminiAssistant --> "uses" build_system_instruction
GeminiAssistant --> "uses" run_tool_call
```

**Diagram sources**
- [backend/api_clients/llm_client.py:38-78](file://backend/api_clients/llm_client.py#L38-L78)
- [backend/api_clients/llm_client.py:220-272](file://backend/api_clients/llm_client.py#L220-L272)
- [backend/api_clients/llm_client.py:82-175](file://backend/api_clients/llm_client.py#L82-L175)
- [backend/api_clients/gemini_client.py:36-94](file://backend/api_clients/gemini_client.py#L36-L94)

**Section sources**
- [backend/api_clients/llm_client.py:47-78](file://backend/api_clients/llm_client.py#L47-L78)
- [backend/api_clients/llm_client.py:82-175](file://backend/api_clients/llm_client.py#L82-L175)
- [backend/api_clients/llm_client.py:220-272](file://backend/api_clients/llm_client.py#L220-L272)
- [backend/api_clients/gemini_client.py:43-94](file://backend/api_clients/gemini_client.py#L43-L94)

### HTTP Server and API Endpoints
- Static file serving for frontend assets.
- Session endpoints: create, list, get, update, delete; messages CRUD; attachments CRUD.
- Weather and news endpoints: fetch and cache results; update memory state.
- Chat endpoint: validates inputs, delegates to LLMAssistant with routing mode support, and returns reply plus tool events and memory snapshot.

**Section sources**
- [backend/server.py:85-167](file://backend/server.py#L85-L167)
- [backend/server.py:169-266](file://backend/server.py#L169-L266)
- [backend/server.py:276-321](file://backend/server.py#L276-L321)
- [backend/server.py:329-394](file://backend/server.py#L329-L394)

### Smart Routing UI Integration
- **Smart Routing Toggle**: Frontend toggle chip that enables/disables dynamic routing mode.
- **Routing Mode Parameter**: Passes routingMode parameter ("dynamic" or "fixed") to the backend.
- **Hybrid Mode Detection**: UI detects if hybrid mode is enabled in the backend configuration.
- **Visual Feedback**: Toggle indicates when Smart Routing is active and available.

**Section sources**
- [frontend/index.html:156-160](file://frontend/index.html#L156-L160)
- [frontend/scripts/app.js:113](file://frontend/scripts/app.js#L113)
- [frontend/scripts/app.js:409](file://frontend/scripts/app.js#L409)
- [frontend/scripts/app.js:974](file://frontend/scripts/app.js#L974)
- [frontend/scripts/app.js:1081](file://frontend/scripts/app.js#L1081)

## Dependency Analysis
- Coupling: server depends on LLM client, memory store, and tools; LLM client depends on brain and tools; brain depends on memory store and tools.
- Cohesion: each module encapsulates a single concern (configuration, server, brain, memory, tools).
- External dependencies: MongoDB, provider APIs, LangChain ecosystem for RAG, web search providers.
- **Hybrid Mode Dependencies**: Additional complexity classification logic and dynamic routing infrastructure.

```mermaid
graph LR
Server["server.py"] --> LLM["api_clients/llm_client.py"]
Server --> Brain["core/orbit_brain.py"]
Server --> Memory["core/memory_store.py"]
Server --> Tools_WS["tools/web_search.py"]
Server --> Tools_KB["tools/knowledge.py"]
Server --> Tools_Weather["tools/weather.py"]
Server --> Tools_News["tools/news.py"]
LLM --> Brain
LLM --> Memory
LLM --> Tools_WS
LLM --> Tools_KB
LLM --> Tools_Weather
LLM --> Tools_News
Brain --> Memory
Brain --> Tools_WS
Brain --> Tools_KB
Brain --> Tools_Weather
Brain --> Tools_News
```

**Diagram sources**
- [backend/server.py:23-63](file://backend/server.py#L23-L63)
- [backend/api_clients/llm_client.py:38-46](file://backend/api_clients/llm_client.py#L38-L46)
- [backend/core/orbit_brain.py:9-20](file://backend/core/orbit_brain.py#L9-L20)

**Section sources**
- [backend/server.py:23-63](file://backend/server.py#L23-L63)
- [backend/api_clients/llm_client.py:38-46](file://backend/api_clients/llm_client.py#L38-L46)
- [backend/core/orbit_brain.py:9-20](file://backend/core/orbit_brain.py#L9-L20)

## Performance Considerations
- Tool loop limits: enforced to prevent runaway tool calls.
- Provider timeouts: HTTP requests to providers use timeouts to avoid hanging.
- RAG indexing: chunk size and overlap tuned for balance; hybrid retriever optional to reduce latency when embeddings are unavailable.
- Session retriever caching: invalidated on attachment changes to avoid stale results.
- MongoDB indexes: ensure efficient queries on sessions, messages, and retrievers.
- Attachment upload limits: size and type checks prevent oversized or unsupported files.
- **Smart Hybrid Mode Optimization**: Automatic task complexity classification prevents unnecessary expensive model usage for simple tasks.
- **Dynamic Routing Efficiency**: Provider switching only occurs for complex tasks, optimizing cost and performance.
- **Enhanced Memory Management**: Improved state management and memory brief optimization for better performance.

## Troubleshooting Guide
- API key missing: provider-specific exceptions raised when API key is absent.
- Provider errors: HTTP errors and URLError mapped to LLMClientError with details.
- Tool errors: WeatherError, NewsError, and ValueError propagated with clear messages.
- Unsupported features: Graceful refusal messages returned for unsupported endpoints.
- Connection failures: MongoDB connection failure raises runtime error with guidance.
- **Hybrid Mode Issues**: Missing hybrid provider configuration or disabled hybrid mode when dynamic routing is requested.
- **Task Classification Errors**: Complex keyword detection may need adjustment for specific use cases.
- **Memory Persistence Issues**: Enhanced error handling for memory store operations and state synchronization.

**Section sources**
- [backend/api_clients/llm_client.py:60-61](file://backend/api_clients/llm_client.py#L60-L61)
- [backend/api_clients/llm_client.py:161-174](file://backend/api_clients/llm_client.py#L161-L174)
- [backend/api_clients/llm_client.py](file://backend/api_clients/llm_client.py#L215)
- [backend/tools/weather.py](file://backend/tools/weather.py#L54)
- [backend/tools/news.py](file://backend/tools/news.py#L34)
- [backend/server.py:271-274](file://backend/server.py#L271-L274)
- [backend/core/memory_store.py:94-98](file://backend/core/memory_store.py#L94-L98)

## Conclusion
The Orbit Virtual Assistant engine integrates a flexible provider-agnostic LLM client, a robust reasoning brain with precise system prompts and tool orchestration, and a MongoDB-backed memory store with multi-session support. The new Smart Hybrid Mode adds intelligent model routing capabilities with automatic task complexity classification and dynamic provider switching, enhancing both performance and cost efficiency. It balances performance and safety with explicit anti-hallucination rules, controlled tool usage, and graceful fallbacks. Extensibility is straightforward: add new tools, adjust prompts, integrate new providers through the existing client abstraction, and leverage the dynamic routing system for optimal resource utilization.

## Appendices

### Smart Hybrid Mode Configuration
- **Enable Hybrid Mode**: Configurable via CLI during startup with `enable_hybrid` setting.
- **Hybrid Provider/Model**: Separate provider and model configuration for complex tasks.
- **Routing Modes**: Fixed (default) or Dynamic (automatic routing based on task complexity).
- **Task Classification**: Automatic determination of simple vs complex tasks using keywords and length thresholds.
- **Configuration Settings**: New hybrid provider settings in config.py with environment variable support.

### Example Conversation Flows
- Simple mode: concise answer to a single query; minimal tool usage.
- Copilot mode: proactive suggestion with plan; uses memory and tasks.
- Coach mode: RAG-powered quiz with local knowledge; enforces tool usage for facts.
- **Smart Hybrid Mode**: Automatically routes complex tasks to higher-capability providers while keeping simple tasks on default models.
- Web search only: prefers web search; still allows local knowledge when relevant.
- Offline mode: strips web tool; relies on local knowledge and memory.

### Extensibility Guidelines
- Adding a new tool:
  - Define function declaration in brain tool list.
  - Implement tool execution in brain dispatcher.
  - Persist tool events and results in memory store.
  - Expose tool via API if needed.
- Adding a new provider:
  - Extend LLM client with provider-specific request/response handling.
  - Adjust tool availability and system instruction injection.
  - Configure hybrid provider settings if desired.
- Enhancing RAG:
  - Integrate new document loaders and chunkers.
  - Tune retriever configuration and hybrid strategies.
- **Smart Hybrid Mode Enhancement**:
  - Extend task complexity classification with additional keywords or criteria.
  - Configure multiple hybrid provider/model combinations for different task types.
  - Implement custom routing logic for specialized use cases.
- **Enhanced Memory Management**:
  - Improve state synchronization and memory brief optimization.
  - Add enhanced error handling for memory operations.
  - Optimize cache management for better performance.