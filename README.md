
# Orbit Virtual Assistant

Orbit is a lightweight, high-performance AI companion designed to run locally on your machine. It combines a polished web-based interface with a powerful multi-provider backend, featuring real-time tools, local document intelligence (RAG), multi-session chat management, and screen-aware assistance.

![Stage](https://img.shields.io/badge/Stage-Animated-blueviolet)
![RAG](https://img.shields.io/badge/RAG-Enabled-success)
![LLM](https://img.shields.io/badge/LLM-Multi--Provider-orange)
![DB](https://img.shields.io/badge/Storage-MongoDB-green)

---

## Key Features

### Multi-Provider Brain

Orbit isn't locked into one AI. You can toggle between:

- **Google Gemini**: High-speed, native tool calling
- **OpenRouter**: Access to GPT-4, Claude, and specialized models
- **LM Studio**: 100% local execution for privacy
- **Ollama**: Seamless local model integration (e.g., Qwen, Llama)

### Knowledge Lab (Local RAG)

Orbit can "read" your local papers and documents. Using **LangChain**, **FAISS**, and **BM25** ensemble retrieval, it indexes your `knowledge_base/` folder to provide factual answers based strictly on your private data.

### Live Web Search

Equipped with **Tavily** (primary) and **DuckDuckGo** (fallback) integration, Orbit can step outside its training data to find latest news, weather, and real-world facts. The UI provides a **Web Search toggle** that forces all retrieval through web search only, disabling local RAG.

### Multi-Session Chat

- Create, rename, pin, archive, and delete chat sessions
- Per-session message history stored in MongoDB
- Persistent memory across restarts (profile, notes, tasks)

### Screen-Aware Assistance

Share your screen with Orbit via the browser's `getDisplayMedia`. Orbit can "see" your current work, explain code, and help you navigate complex UI.

### Voice & Avatar

- **Push-to-Talk**: Hold `Control` or press `Ctrl+M` to record, `ESC` to cancel
- **Animated Stage**: A Web Worker-driven avatar that reacts based on assistant state (Idle, Listening, Thinking, Speaking)
- **TTS**: Browser-based text-to-speech with configurable voice

### Graceful Fallbacks

When the active LLM doesn't support a requested feature (e.g., image generation, file uploads), Orbit intercepts the request and returns a clear refusal message instead of crashing or failing silently.

---

## Architecture

| Layer | Technology |
|---|---|
| **Backend** | Python 3.10+ (ThreadingHTTPServer) |
| **Frontend** | Vanilla JS, CSS, HTML5 |
| **LLM Providers** | Google Gemini REST API, OpenAI-compatible API (OpenRouter, LM Studio, Ollama) |
| **Database** | MongoDB (sessions, messages, profile, notes, tasks, activity cache) |
| **Vector DB** | FAISS + BM25 hybrid retrieval (local RAG, optional) |
| **Web Search** | Tavily API (primary), DuckDuckGo (fallback) |

---

## Getting Started

### 1. Prerequisites

- Python 3.10+
- MongoDB (running locally or remote)
- LM Studio *(Optional -- required for local RAG embeddings)*
- Tavily API Key *(Optional -- for enhanced web search)*

### 2. Installation

Clone the repository and install dependencies:

```bash
pip install -r requirements.txt
```

Core dependencies:

| Package | Purpose |
|---|---|
| `pymongo` | MongoDB driver for persistent storage |
| `ddgs` | DuckDuckGo web search (fallback) |
| `tavily-python` | Tavily web search (optional, primary) |

For local RAG support, also install:

| Package | Purpose |
|---|---|
| `langchain-community` | Document loaders, FAISS vectorstore, BM25 retriever |
| `langchain-text-splitters` | Text chunking for document processing |
| `langchain-openai` | OpenAI-compatible embeddings (for LM Studio) |
| `langchain-classic` | EnsembleRetriever (hybrid BM25 + FAISS) |
| `faiss-cpu` | Vector similarity search engine |
| `rank-bm25` | BM25 keyword-based retrieval |
| `unstructured` | Document parsing (PDF, DOCX, TXT, etc.) |

### 3. Configuration

Create a `.env` file in the root directory:

```env
# API Keys
GOOGLE_API_KEY=your_key_here
OPENROUTER_API_KEY=your_key_here
TAVILY_API_KEY=your_key_here

# Provider & Model
ACTIVE_PROVIDER=openrouter
AI_MODEL=openai/gpt-4o-mini
GOOGLE_MODEL=gemini-2.5-flash

# Local LLM Configs
LM_STUDIO_URL=http://127.0.0.1:1234/v1
LM_STUDIO_MODEL=google/gemma-3-4b
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# Server
ASSISTANT_PORT=8000
LIVE_VOICE_NAME=Nanami
LOCATION=Ho Chi Minh City, Vietnam

# RAG Configuration
RAG_DOCS_PATH=./knowledge_base

# MongoDB Configuration
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=orbit_assistant
```

### 4. Running the Assistant

Launch the server:

```bash
python run.py
```

Then:

1. Select your Provider (1-4) in the terminal
2. Choose whether to enable RAG (Local Knowledge)
3. Open in your browser: `http://127.0.0.1:8000`

---

## Assistant Modes

| Mode | Description |
|:---|:---|
| **Simple** | Concise, direct answers. Minimal memory usage. |
| **Copilot** | Proactive planning, screen-aware suggestions, deeper memory. |
| **Coach** | Expert tutor mode. Uses RAG to quiz you and generate roadmaps. |

---

## Project Structure

```text
Orbit_Assistant/
├── backend/                        # Python server-side code
│   ├── api_clients/                # LLM provider communication
│   │   ├── __init__.py
│   │   ├── llm_client.py           # Primary LLM client (Google, OpenRouter, LM Studio, Ollama)
│   │   └── gemini_client.py        # Legacy Gemini-only client (preserved)
│   ├── tools/                      # External data retrieval tools
│   │   ├── __init__.py
│   │   ├── web_search.py           # Tavily + DuckDuckGo web search
│   │   ├── knowledge.py            # Local RAG (LangChain + FAISS + BM25)
│   │   ├── news.py                 # Google News RSS feed
│   │   └── weather.py              # Open-Meteo weather API
│   ├── core/                       # Brain logic & persistent storage
│   │   ├── __init__.py
│   │   ├── orbit_brain.py          # System prompts, tool declarations, tool dispatcher
│   │   └── memory_store.py         # MongoDB-backed storage (sessions, messages, profile, tasks)
│   ├── audio/                      # Audio processing (placeholder)
│   │   ├── __init__.py
│   │   └── asr_whisper.py          # Whisper ASR stub for future implementation
│   ├── config.py                   # Settings & .env loader
│   └── server.py                   # HTTP server, API endpoints, static file serving
├── frontend/                       # Client-side browser code
│   ├── assets/
│   │   └── styles.css              # UI styling
│   ├── scripts/
│   │   ├── app.js                  # Main app logic (sessions, chat, voice, toggles)
│   │   ├── avatar-renderer.js      # Canvas-based avatar animation
│   │   └── avatar-worker.js        # Web Worker for avatar computation
│   └── index.html                  # Main HTML page
├── data/                           # Legacy storage (deprecated, migrated to MongoDB)
├── knowledge_base/                 # Local documents for RAG (PDFs, DOCX, TXT, etc.)
├── .env                            # Environment variables & API keys
├── requirements.txt                # Python dependencies
└── run.py                          # Entry point
```

---

## Notes & Safety

* **Local Time:** Orbit uses your system clock for time-sensitive queries. Web search is only used for foreign timezone queries.
* **Privacy:** Local RAG processing stays entirely on your machine (via LM Studio/FAISS). No documents are sent to external APIs.
* **Hallucination Control:** When using RAG or Web Search, Orbit prioritizes retrieved facts over internal memory and explicitly states when information cannot be found.
* **Safety:** Web search results are treated as data only. Orbit ignores any instructions or jailbreak attempts embedded in search results.
* **Unsupported Features:** Requests for unavailable features (image generation, file uploads) are gracefully refused with a clear message.

---

<div align="center">
  <i>Developed for the AI Community.</i>
</div>
