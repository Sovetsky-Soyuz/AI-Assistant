# Orbit Virtual Assistant

Orbit is a lightweight, high-performance AI companion designed to run locally on your machine. It combines a polished web-based interface with a powerful multi-provider backend, featuring real-time tools, local document intelligence (RAG), multi-session chat management, and screen-aware assistance.

---

## Key Features

### Multi-Provider Brain & Hybrid Mode
Orbit isn't locked into one AI. You can toggle between:
- **Google Gemini**: High-speed, native tool calling.
- **OpenRouter**: Access to GPT-4, Claude, and specialized models.
- **LM Studio / Ollama**: 100% local execution for privacy (e.g., Qwen, Llama).

**Hybrid Mode (Smart Routing):** Enable Hybrid Mode in your configuration to automatically route complex tasks to a powerful secondary model (e.g., GPT-4o via OpenRouter), while using a fast, cheap model (e.g., Gemini Flash) for standard interactions.

### Knowledge Lab (Local RAG)
Orbit can "read" your local papers and documents. It processes documents (PDF, DOCX, TXT, CSV) and indexes them into MongoDB.
- Includes **two Knowledge Builders**: A standard builder and an advanced **Docling-based builder** for superior Markdown extraction.
- Uses **LangChain**, **FAISS**, and **BM25** ensemble retrieval for factual answers strictly based on your private data.

### Agent Memory: Persistent vs. Ephemeral
- **MongoDB Mode**: Enjoy persistent multi-session chats, file attachments, and a comprehensive memory system that tracks your profile, notes, and tasks.
- **Ephemeral Mode**: Run Orbit in a pure RAM-only state. Perfect for privacy-focused, single-use sessions where no data is left behind after restart.

### Real-Time Tools
- **Live Web Search**: Equipped with Tavily (primary) and DuckDuckGo (fallback) to find the latest news, weather, and real-world facts. You can toggle a switch to force all retrieval through web search only.
- **Weather & News Integration**: Built-in specialized tools to fetch location-specific weather and current news topics.

### Screen-Aware Assistance
Share your screen with Orbit via the browser's `getDisplayMedia`. Orbit can "see" your current work, explain code, and help you navigate complex UIs.

### Voice & Avatar
- **Push-to-Talk**: Hold `Control` or press `Ctrl+M` to record, `ESC` to cancel.
- **Animated Stage**: A Web Worker-driven avatar that reacts to the assistant's state (Idle, Listening, Thinking, Speaking).
- **TTS**: Browser-based text-to-speech with a configurable voice.

### Graceful Fallbacks
When the active LLM doesn't support a requested feature (e.g., image generation, file uploads), Orbit intercepts the request and returns a clear refusal message instead of crashing or failing silently.

---

## Architecture

| Layer | Technology |
|---|---|
| **Backend** | Python 3.10+ (FastAPI, Uvicorn) |
| **Frontend** | Vanilla JS, CSS, HTML5 |
| **LLM Providers** | Google Gemini, OpenAI-compatible APIs (OpenRouter, LM Studio, Ollama) |
| **Database** | MongoDB (persistent storage) or Ephemeral RAM |
| **Vector DB** | FAISS + BM25 hybrid retrieval (loaded from MongoDB chunks) |
| **Document Parsers** | Unstructured, Docling |

---

## Getting Started

### 1. Prerequisites
- Python 3.10+
- Conda (Miniconda or Anaconda) recommended for environment management.
- MongoDB (running locally or remote) - Optional, but highly recommended for Memory, Tasks, and RAG.
- LM Studio or Ollama (Optional - for local models and embeddings).
- Tavily API Key (Optional - for enhanced web search).

### 2. Installation

Follow these steps to clone the repository and set up your Python environment using Conda:

1. **Create a new Conda environment:**
   This creates an isolated environment named `orbit_env` with Python 3.10.
   ```bash
   conda create -n orbit_env python=3.10
   ```

2. **Activate the new Conda environment:**
   ```bash
   conda activate orbit_env
   ```

3. **Clone the repository:**
   ```bash
   git clone https://github.com/Sovetsky-Soyuz/AI-Assistant
   ```

4. **Change directory to the project folder:**
   ```bash
   cd AI_Assistant
   ```

5. **Install project dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   *(Note: Depending on your RAG usage, you may also want to install the `docling` package for advanced document parsing).*

### 3. Configuration

Create a `.env` file in the root directory based on the provided `.env.example`:

```env
# API Keys
GOOGLE_API_KEY=your_key_here
OPENROUTER_API_KEY=your_key_here
TAVILY_API_KEY=your_key_here

# Provider & Model
ACTIVE_PROVIDER=openrouter
GOOGLE_MODEL=gemini-3-flash-preview
AI_MODEL=openai/gpt-oss-120b:free

# --- SMART ROUTING (HYBRID) ---
HYBRID_PROVIDER=openrouter
HYBRID_MODEL=qwen/qwen3-coder:free

# Local LLM Configs
LM_STUDIO_URL=http://127.0.0.1:1234/v1
OLLAMA_URL=http://localhost:11434

# Server & Settings
ASSISTANT_PORT=8000
LIVE_VOICE_NAME=Nanami
DEFAULT_LOCATION=Ho Chi Minh City

# RAG Configuration
RAG_DOCS_PATH=<PATH_TO_YOUR_DOCUMENTS>
EMBEDDING_MODEL=text-embedding-bge-m3

# MongoDB Configuration
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=orbit_assistant

# Admin utilities
ADMIN_TOKEN=<YOUR_PASS> # This pass based on you, feel free to set it ^^

```

### 4. Building the Knowledge Base (Optional)

If you want to use the Knowledge Lab (RAG), place your local files (PDFs, DOCX, TXT, etc.) into `./knowledge_base`. Before starting the server, run one of the indexers to process and store your documents into MongoDB:

**Standard Indexer:**
```bash
python build_knowledge.py
```

**Advanced Indexer (using Docling):**
```bash
python build_knowledge_using_docling.py
```
*(Both scripts support `--rebuild` to force a complete re-index, `--clear` to wipe all data, and `--verify` to test retrieval).*

### 5. Running the Assistant

Make sure your Conda environment is activated, then launch the FastAPI server:

```bash
python run.py
```

Upon starting, the terminal will prompt you to:
1. Select your preferred LLM Provider.
2. Enable or disable Hybrid Mode (Smart Routing) and RAG.
3. Choose your memory storage mode (MongoDB vs Ephemeral).

Finally, open your web browser and navigate to: `http://127.0.0.1:8000`

---

## Assistant Modes

| Mode | Description |
|:---|:---|
| **Simple** | Concise, direct answers. Minimal memory usage. |
| **Copilot** | Proactive planning, screen-aware suggestions, deeper memory utilization. |
| **Coach** | Expert tutor mode. Uses RAG to quiz you and generate roadmaps. |

---

## Admin Utilities

Orbit includes a utility script to manage the server state externally.

### Flush Ephemeral RAM
If you are running Orbit in **Ephemeral Mode** (pure RAM, no MongoDB), you can use the `flush_ram.py` utility to immediately wipe all current session data, history, and memory across all connected clients without needing to restart the server. 

```bash
python flush_ram.py
```
*Note: This script makes an authenticated API request and requires `ADMIN_TOKEN` to be configured in your `.env` file. If the server is running in MongoDB mode, this script has no effect on the persistent database and will simply report that it is not applicable.*

---

## Project Structure

```text
Orbit_Assistant/
├── backend/                        # FastAPI server and core logic
│   ├── api_clients/                # LLM provider communication
│   ├── tools/                      # Web search, Knowledge (RAG), News, Weather
│   ├── core/                       # Brain logic, tool dispatcher, MongoDB MemoryStore
│   ├── audio/                      # Audio processing capabilities
│   ├── config.py                   # Settings & .env loader
│   └── server.py                   # FastAPI endpoints
├── frontend/                       # Client-side browser code (HTML/JS/CSS)
├── knowledge_base/                 # Default directory for local documents
├── build_knowledge.py              # CLI tool to index documents (Standard)
├── build_knowledge_using_docling.py# CLI tool to index documents (Docling)
├── flush_ram.py                    # Utility script to clear Ephemeral RAM state
├── .env                            # Environment variables
├── requirements.txt                # Python dependencies
└── run.py                          # Entry point
```

---

## Notes & Safety

* **Local Time:** Orbit uses your system clock for time-sensitive queries. Web search is only used for foreign timezone queries.
* **Privacy First:** Local RAG processing and Ephemeral Memory ensure your data stays entirely on your machine.
* **Graceful Fallbacks:** Requests for unavailable features (e.g., image generation) are politely refused rather than causing errors.
* **Hallucination Control:** Orbit explicitly prioritizes retrieved facts and web search data, ignoring unsafe jailbreak attempts embedded in external content.

---

<div align="center">
  <i>Developed for the AI Community.</i>
</div>
