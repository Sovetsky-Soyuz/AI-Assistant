# OpenRouter and OpenAI-Compatible Providers

<cite>
**Referenced Files in This Document**
- [llm_client.py](file://backend/api_clients/llm_client.py)
- [config.py](file://backend/config.py)
- [orbit_brain.py](file://backend/core/orbit_brain.py)
- [server.py](file://backend/server.py)
- [web_search.py](file://backend/tools/web_search.py)
- [knowledge.py](file://backend/tools/knowledge.py)
- [README.md](file://README.md)
- [requirements.txt](file://requirements.txt)
</cite>

## Update Summary
**Changes Made**
- Added comprehensive documentation for dynamic model switching based on task complexity
- Updated OpenRouter compatibility documentation to include hybrid mode routing functionality
- Enhanced provider routing capabilities with intelligent provider selection features
- Added new hybrid mode configuration and runtime routing mechanisms
- Updated architecture diagrams to reflect dynamic routing capabilities

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
This document explains the OpenRouter and OpenAI-compatible provider integration, focusing on the enhanced dynamic routing capabilities with intelligent model switching. The system now features:
- **Dynamic Model Switching**: Automatic provider/model selection based on task complexity analysis
- **Hybrid Mode Routing**: Intelligent routing between different providers and models
- **Task Complexity Classification**: Automated determination of whether a task requires advanced or basic processing
- OpenRouter API endpoint configuration and authentication headers
- Model compatibility handling across providers
- Trigger phrase detection for factual queries that automatically enables web search tools
- Tool function declaration and tool call execution flow
- Response processing for OpenAI-compatible APIs
- Provider-specific configurations for LM Studio and Ollama local deployments
- Examples of API endpoint routing, header management, and tool orchestration patterns

## Project Structure
The assistant routes chat requests through a server endpoint that delegates to a provider-agnostic client with enhanced routing capabilities. The OpenRouter/OpenAI-compatible logic resides in the LLM client, which now includes dynamic model switching based on task complexity analysis.

```mermaid
graph TB
subgraph "Frontend"
FE["Browser UI"]
end
subgraph "Backend"
SRV["HTTP Server<br/>server.py"]
CFG["Settings Loader<br/>config.py"]
LLM["LLM Client<br/>llm_client.py"]
BRAIN["System Prompt & Tools<br/>orbit_brain.py"]
KBASE["Knowledge Service<br/>knowledge.py"]
WSRCH["Web Search Service<br/>web_search.py"]
ENDPT["Dynamic Router<br/>Task Complexity Analysis"]
ENDPT --> LLM
ENDPT --> CFG
ENDPT --> LLM
ENDPT --> BRAIN
ENDPT --> KBASE
ENDPT --> WSRCH
end
FE --> SRV
SRV --> ENDPT
SRV --> LLM
LLM --> BRAIN
LLM --> KBASE
LLM --> WSRCH
```

**Diagram sources**
- [server.py:276-321](file://backend/server.py#L276-L321)
- [llm_client.py:38-78](file://backend/api_clients/llm_client.py#L38-L78)
- [config.py:55-76](file://backend/config.py#L55-L76)
- [orbit_brain.py:302-387](file://backend/core/orbit_brain.py#L302-L387)
- [knowledge.py:88-138](file://backend/tools/knowledge.py#L88-L138)
- [web_search.py:53-104](file://backend/tools/web_search.py#L53-L104)

**Section sources**
- [README.md:164-201](file://README.md#L164-L201)
- [server.py:276-321](file://backend/server.py#L276-L321)

## Core Components
- **LLMAssistant**: Orchestrates chat across providers with enhanced routing capabilities. It selects the OpenRouter path for openrouter, lm_studio, and ollama, and falls back to Google otherwise. Now includes dynamic model switching based on task complexity.
- **Dynamic Routing Engine**: Intelligent task classification system that determines whether to use default or hybrid provider/model combinations.
- **_chat_openrouter**: Implements OpenAI-compatible chat with tool calling, trigger phrase detection, and iterative tool loop handling.
- **Settings**: Loads provider selection, API keys, and provider-specific URLs/models from environment variables, including new hybrid mode configuration.
- **Tool Orchestration**: build_rest_tools declares function tools; run_tool_call executes them and records events.

**Section sources**
- [llm_client.py:38-78](file://backend/api_clients/llm_client.py#L38-L78)
- [llm_client.py:82-216](file://backend/api_clients/llm_client.py#L82-L216)
- [config.py:20-76](file://backend/config.py#L20-L76)
- [orbit_brain.py:361-387](file://backend/core/orbit_brain.py#L361-L387)
- [orbit_brain.py:389-502](file://backend/core/orbit_brain.py#L389-L502)

## Architecture Overview
The enhanced OpenRouter-compatible flow integrates with the broader assistant architecture and now includes dynamic routing capabilities. The server endpoint receives chat requests, constructs the assistant request, and delegates to LLMAssistant. The assistant builds system instructions, classifies task complexity, selects appropriate provider/model, declares tools, sends requests to the selected provider, and executes tool calls until a final text response is produced.

```mermaid
sequenceDiagram
participant Client as "Client"
participant Server as "AssistantApplication<br/>server.py"
participant Router as "Dynamic Router<br/>llm_client.py"
participant Assistant as "LLMAssistant<br/>llm_client.py"
participant Classifier as "Task Complexity<br/>_classify_task_complexity"
participant Brain as "System Prompt & Tools<br/>orbit_brain.py"
participant Provider as "Provider Endpoint<br/>OpenRouter/LM Studio/Ollama"
participant Tools as "run_tool_call<br/>orbit_brain.py"
Client->>Server : POST /api/chat
Server->>Assistant : chat(message, conversation, ...)
Assistant->>Classifier : _classify_task_complexity(message)
Classifier-->>Assistant : "simple" or "complex"
alt Complex Task
Assistant->>Router : Use Hybrid Provider/Model
Router-->>Assistant : target_provider, target_model
else Simple Task
Assistant->>Router : Use Default Provider/Model
Router-->>Assistant : target_provider, target_model
end
Assistant->>Brain : build_system_instruction(...)
Assistant->>Assistant : build tool declarations via build_rest_tools
Assistant->>Provider : POST chat/completions (OpenAI-compatible)
Provider-->>Assistant : choices[0].message (text or tool_calls)
alt Has tool_calls
Assistant->>Tools : run_tool_call(name, args, session_id)
Tools-->>Assistant : ToolRunResult(event, function_response)
Assistant->>Provider : POST next iteration with tool results
Provider-->>Assistant : Final text response
else No tool_calls
Assistant-->>Server : reply + tool_events
end
Server-->>Client : {reply, toolEvents, memory, model}
```

**Diagram sources**
- [server.py:276-321](file://backend/server.py#L276-L321)
- [llm_client.py:82-216](file://backend/api_clients/llm_client.py#L82-L216)
- [llm_client.py:59-71](file://backend/api_clients/llm_client.py#L59-L71)
- [orbit_brain.py:361-387](file://backend/core/orbit_brain.py#L361-L387)
- [orbit_brain.py:389-502](file://backend/core/orbit_brain.py#L389-L502)

## Detailed Component Analysis

### Enhanced Provider Routing with Dynamic Model Switching
**Updated** The system now includes intelligent task complexity classification and automatic provider/model switching:

- **Task Complexity Classification**: The `_classify_task_complexity` method analyzes incoming messages to determine if they require advanced processing
- **Complex Task Indicators**:
  - Message length > 800 characters
  - Presence of complex keywords (analyze, optimize, refactor, architect, explain code, calculate, prove, derive, logic)
  - Vietnamese equivalents of complex verbs
- **Dynamic Routing Logic**: When `routing_mode` is "dynamic" and hybrid mode is enabled, the system automatically selects appropriate provider/model combinations
- **Provider Selection**: The assistant routes to _chat_openrouter when active_provider is openrouter, lm_studio, or ollama, with automatic model upgrades for complex tasks

```mermaid
flowchart TD
Start(["Receive user message"]) --> LengthCheck{"Message > 800 chars?"}
LengthCheck --> |Yes| ClassifyComplex["Classify as COMPLEX"]
LengthCheck --> |No| KeywordCheck{"Contains complex keywords?"}
KeywordCheck --> |Yes| ClassifyComplex
KeywordCheck --> |No| ClassifySimple["Classify as SIMPLE"]
ClassifyComplex --> HybridCheck{"Hybrid Mode Enabled?"}
HybridCheck --> |Yes| UpgradeRoute["Upgrade to Hybrid Provider/Model"]
HybridCheck --> |No| DefaultRoute["Use Default Provider/Model"]
ClassifySimple --> DefaultRoute
UpgradeRoute --> Next["Proceed with upgraded routing"]
DefaultRoute --> Next
```

**Diagram sources**
- [llm_client.py:59-71](file://backend/api_clients/llm_client.py#L59-L71)
- [llm_client.py:92-101](file://backend/api_clients/llm_client.py#L92-L101)

**Section sources**
- [llm_client.py:59-71](file://backend/api_clients/llm_client.py#L59-L71)
- [llm_client.py:92-101](file://backend/api_clients/llm_client.py#L92-L101)

### OpenRouter and OpenAI-Compatible Provider Routing
- **Enhanced Provider selection**: The assistant routes to _chat_openrouter when active_provider is openrouter, lm_studio, or ollama, with automatic model switching for complex tasks.
- **Endpoint resolution**:
  - OpenRouter: Fixed endpoint for OpenAI-compatible completions.
  - LM Studio: Resolved from LM_STUDIO_URL with /chat/completions.
  - Ollama: Resolved from OLLAMA_URL with /v1/chat/completions.
- **Authentication**:
  - OpenRouter: Authorization Bearer header using OPENROUTER_API_KEY.
  - LM Studio/Ollama: No API key required; Content-Type is set for JSON.

**Section sources**
- [llm_client.py:74-78](file://backend/api_clients/llm_client.py#L74-L78)
- [llm_client.py:136-149](file://backend/api_clients/llm_client.py#L136-L149)
- [config.py:63-72](file://backend/config.py#L63-L72)

### Trigger Phrase Detection for Factual Queries
- **Trigger phrases**: The assistant checks the user message for factual-query keywords.
- **Behavior**: If matched, it appends a system note instructing the model to use the web search tool before answering.

```mermaid
flowchart TD
Start(["Receive user message"]) --> Lower["Normalize to lowercase"]
Lower --> CheckPhrases{"Contains trigger phrase?"}
CheckPhrases --> |Yes| AppendNote["Append system note to use search_web"]
CheckPhrases --> |No| KeepMsg["Keep original message"]
AppendNote --> Next["Proceed to build messages"]
KeepMsg --> Next
```

**Diagram sources**
- [llm_client.py:84-87](file://backend/api_clients/llm_client.py#L84-L87)

**Section sources**
- [llm_client.py:84-87](file://backend/api_clients/llm_client.py#L84-L87)

### Tool Function Declaration and Tool Call Execution Flow
- **Tool declarations**:
  - build_rest_tools generates functionDeclarations based on capabilities (knowledge, web_search_only, offline_mode, session docs).
  - The assistant converts functionDeclarations to OpenAI-style tools for OpenRouter/LM Studio/Ollama.
- **Tool execution**:
  - run_tool_call dispatches to concrete services (weather, news, knowledge, web search) and records events.
  - The assistant appends tool results back into the conversation as role=tool entries.

```mermaid
sequenceDiagram
participant Assistant as "_chat_openrouter"
participant Brain as "build_rest_tools"
participant Model as "Provider"
participant Runner as "run_tool_call"
Assistant->>Brain : Build functionDeclarations
Brain-->>Assistant : [{"functionDeclarations" : ...}]
Assistant->>Model : POST with tools + messages
Model-->>Assistant : message.tool_calls
loop For each tool_call
Assistant->>Runner : run_tool_call(name, args, session_id)
Runner-->>Assistant : ToolRunResult(event, response)
Assistant->>Model : POST with role=tool result
end
Model-->>Assistant : Final message.content
```

**Diagram sources**
- [llm_client.py:109-116](file://backend/api_clients/llm_client.py#L109-L116)
- [llm_client.py:185-213](file://backend/api_clients/llm_client.py#L185-L213)
- [orbit_brain.py:361-387](file://backend/core/orbit_brain.py#L361-L387)
- [orbit_brain.py:389-502](file://backend/core/orbit_brain.py#L389-L502)

**Section sources**
- [llm_client.py:109-116](file://backend/api_clients/llm_client.py#L109-L116)
- [llm_client.py:185-213](file://backend/api_clients/llm_client.py#L185-L213)
- [orbit_brain.py:361-387](file://backend/core/orbit_brain.py#L361-L387)
- [orbit_brain.py:389-502](file://backend/core/orbit_brain.py#L389-L502)

### Response Processing for OpenAI-Compatible APIs
- **Choice extraction**: The assistant reads the first choice's message.
- **Tool-call presence**: If tool_calls exist, it executes them and continues until a final text response is produced.
- **Moderation handling**: On 403 with moderation flags, it returns a safety message instead of raising.

**Section sources**
- [llm_client.py:176-181](file://backend/api_clients/llm_client.py#L176-L181)
- [llm_client.py:164-174](file://backend/api_clients/llm_client.py#L164-L174)

### Provider-Specific Configurations for LM Studio and Ollama
- **LM Studio**:
  - Base URL configured via LM_STUDIO_URL; model via LM_STUDIO_MODEL.
  - Embeddings for RAG connect to LM Studio using an OpenAI-compatible base URL and a placeholder API key.
- **Ollama**:
  - Base URL configured via OLLAMA_URL; model via OLLAMA_MODEL.
  - The assistant resolves the /v1/chat/completions endpoint for OpenAI compatibility.

**Section sources**
- [config.py:71-72](file://backend/config.py#L71-L72)
- [knowledge.py:122-137](file://backend/tools/knowledge.py#L122-L137)
- [llm_client.py:136-141](file://backend/api_clients/llm_client.py#L136-L141)

### API Endpoint Routing and Header Management
- **Server endpoint**: POST /api/chat delegates to LLMAssistant.chat with mode, language, web search toggles, offline mode, and session_id.
- **Enhanced routing parameters**: The chat method now accepts `routing_mode`, `override_provider`, and `override_model` parameters for dynamic routing control.
- **Headers**:
  - OpenRouter: Content-Type and Authorization Bearer.
  - LM Studio/Ollama: Content-Type only.
- **Payload composition**: Includes model, messages, tools, and temperature.

**Section sources**
- [server.py:276-321](file://backend/server.py#L276-L321)
- [llm_client.py:129-156](file://backend/api_clients/llm_client.py#L129-L156)

### Tool Orchestration Patterns Across Providers
- **Capability gating**: build_rest_tools conditionally includes search_web, search_local_docs, and search_session_docs depending on mode and session attachments.
- **Event recording**: run_tool_call returns ToolRunResult with event metadata for UI and analytics.
- **Web search fallback**: WebSearchService tries Tavily first, then DuckDuckGo if Tavily is unavailable.

**Section sources**
- [orbit_brain.py:361-387](file://backend/core/orbit_brain.py#L361-L387)
- [orbit_brain.py:389-502](file://backend/core/orbit_brain.py#L389-L502)
- [web_search.py:69-104](file://backend/tools/web_search.py#L69-L104)

## Dependency Analysis
- **Enhanced Provider selection**: Depends on Settings.active_provider, Settings.current_api_key, and new Settings.enable_hybrid, Settings.hybrid_provider, Settings.hybrid_model.
- **Dynamic routing**: Depends on task complexity classification and hybrid mode configuration.
- **Tool orchestration**: Depends on orbit_brain for function declarations and run_tool_call.
- **Web search and knowledge services**: Are optional; their availability influences tool capability gating.

```mermaid
graph LR
CFG["Settings<br/>config.py"] --> LLM["LLMAssistant<br/>llm_client.py"]
LLM --> ROUTER["_classify_task_complexity<br/>llm_client.py"]
LLM --> BRAIN["Tool Declarations<br/>orbit_brain.py"]
LLM --> WSRCH["Web Search<br/>web_search.py"]
LLM --> KBASE["Knowledge Base<br/>knowledge.py"]
BRAIN --> RUN["run_tool_call<br/>orbit_brain.py"]
ROUTER --> LLM
```

**Diagram sources**
- [config.py:20-76](file://backend/config.py#L20-L76)
- [llm_client.py:38-78](file://backend/api_clients/llm_client.py#L38-L78)
- [llm_client.py:59-71](file://backend/api_clients/llm_client.py#L59-L71)
- [orbit_brain.py:361-387](file://backend/core/orbit_brain.py#L361-L387)
- [web_search.py:53-104](file://backend/tools/web_search.py#L53-L104)
- [knowledge.py:88-138](file://backend/tools/knowledge.py#L88-L138)

**Section sources**
- [config.py:20-76](file://backend/config.py#L20-L76)
- [llm_client.py:38-78](file://backend/api_clients/llm_client.py#L38-L78)
- [llm_client.py:59-71](file://backend/api_clients/llm_client.py#L59-L71)
- [orbit_brain.py:361-387](file://backend/core/orbit_brain.py#L361-L387)

## Performance Considerations
- **Loop limit**: The assistant enforces a maximum iteration count to prevent infinite tool loops.
- **Temperature tuning**: The assistant sets a moderate temperature for balanced creativity and focus.
- **Tool batching**: The system prompt encourages the model to execute multiple tools when needed, reducing repeated round trips.
- **Enhanced routing efficiency**: Dynamic model switching reduces unnecessary use of expensive providers for simple tasks.
- **Task complexity filtering**: Prevents complex processing overhead for straightforward queries.

**Section sources**
- [llm_client.py:128-128](file://backend/api_clients/llm_client.py#L128-L128)
- [llm_client.py:133-133](file://backend/api_clients/llm_client.py#L133-L133)
- [llm_client.py:118-126](file://backend/api_clients/llm_client.py#L118-L126)

## Troubleshooting Guide
- **Provider errors**:
  - OpenRouter 403 with moderation: Returns a safety message instead of propagating the error.
  - URLError/HTTPError: Propagated as LLMClientError with details.
- **Missing API key**:
  - Raises an explicit error if the current provider's API key is not set.
- **Tool execution failures**:
  - run_tool_call catches known exceptions and returns error events.
- **Hybrid mode issues**:
  - Dynamic routing disabled when hybrid mode is not enabled in CLI configuration.
  - Task complexity classification may misclassify edge cases; manual override available via parameters.

**Section sources**
- [llm_client.py:60-61](file://backend/api_clients/llm_client.py#L60-L61)
- [llm_client.py:164-174](file://backend/api_clients/llm_client.py#L164-L174)
- [orbit_brain.py:490-493](file://backend/core/orbit_brain.py#L490-L493)

## Conclusion
The enhanced OpenRouter and OpenAI-compatible provider integration centers on a robust, intelligent routing system that adapts to task complexity. The assistant now features:
- **Dynamic Model Switching**: Automatic provider/model selection based on task complexity analysis
- **Intelligent Routing**: Complex tasks are routed to hybrid providers while simple tasks use default configurations
- **Task Classification**: Automated determination of processing requirements using multiple criteria
- **Factual Query Detection**: Enhanced trigger phrase detection for web search integration
- **Conditional Tool Capabilities**: Dynamic tool availability based on mode and session context
- **Provider-Specific Optimizations**: Maintains consistent API surfaces across different provider implementations

## Appendices

### Enhanced Provider Configuration Reference
- **OpenRouter**
  - Endpoint: OpenAI-compatible completions
  - Headers: Content-Type, Authorization Bearer
  - **New Hybrid Settings**: HYBRID_PROVIDER, HYBRID_MODEL for dynamic routing
- **LM Studio**
  - Endpoint: {LM_STUDIO_URL}/chat/completions
  - Headers: Content-Type
- **Ollama**
  - Endpoint: {OLLAMA_URL}/v1/chat/completions
  - Headers: Content-Type

**Section sources**
- [llm_client.py:142-149](file://backend/api_clients/llm_client.py#L142-L149)
- [config.py:71-72](file://backend/config.py#L71-L72)
- [config.py:39-43](file://backend/config.py#L39-L43)
- [config.py:83-86](file://backend/config.py#L83-L86)

### Dynamic Routing Configuration
- **Task Complexity Classification**:
  - Simple: Short messages (< 800 chars) without complex keywords
  - Complex: Long messages (> 800 chars) or messages containing complex keywords
- **Hybrid Mode Activation**: Controlled by CLI prompt during startup
- **Automatic Provider Selection**: Complex tasks routed to hybrid provider/model combination

**Section sources**
- [llm_client.py:59-71](file://backend/api_clients/llm_client.py#L59-L71)
- [llm_client.py:92-101](file://backend/api_clients/llm_client.py#L92-L101)
- [server.py:297-303](file://backend/server.py#L297-L303)

### Tool Capabilities Matrix
- **search_web**: Enabled unless offline_mode; bias towards web when web_search_only is true
- **search_local_docs**: Enabled when knowledge base is available
- **search_session_docs**: Enabled when session has attachments

**Section sources**
- [orbit_brain.py:361-387](file://backend/core/orbit_brain.py#L361-L387)

### Hybrid Mode Setup
- **CLI Configuration**: Users can enable hybrid mode during startup with custom provider/model combinations
- **Environment Variables**: HYBRID_PROVIDER and HYBRID_MODEL control the backup routing configuration
- **Runtime Override**: Manual provider/model overrides available via chat parameters

**Section sources**
- [server.py:297-303](file://backend/server.py#L297-L303)
- [config.py:83-86](file://backend/config.py#L83-L86)
- [llm_client.py:84-87](file://backend/api_clients/llm_client.py#L84-L87)