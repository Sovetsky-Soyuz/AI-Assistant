
# Orbit Virtual Assistant - Advanced Architecture & UI/UX Refactoring Plan

## 1. Project Overview & Hardware Context

Orbit is transitioning into a comprehensive, ChatGPT-style AI assistant optimized for local execution. The system runs on a machine with **16GB RAM and an RTX 3060 (6GB VRAM)**, making it capable of running quantized 7B/8B local models alongside lightweight embedding models for RAG.

**Key Refactoring Goals:**

1. **UI/UX Overhaul:** Migrate to a minimalist, side-bar driven interface (ChatGPT style) supporting multiple chat sessions, message management, and dynamic input toggles.
2. **Database Migration:** Transition from fragile JSON file storage to a robust NoSQL/In-memory database (MongoDB or Redis) for efficient chat history and memory management.
3. **Smart Tool Routing:** Unify all external and internal retrievals (including Local RAG) under the `tools/` directory, allowing the Agent to dynamically choose between online web search and offline local data.
4. **Graceful Fallbacks:** Implement primary-fallback LLM logic (e.g., using Local/OpenRouter as primary, Google Gemini strictly as a limited fallback to conserve free tier quotas) and natural language fallbacks for unsupported features (like image generation).

---

## 2. Updated Directory Structure

```text
Orbit_Assistant/
├── backend/   
│   ├── api_clients/   
│   │   ├── __init__.py
│   │   ├── llm_client.py       # Primary API client (Local/OpenRouter)
│   │   └── gemini_client.py    # Fallback API client (Limited quota handling)
│   ├── tools/   
│   │   ├── __init__.py
│   │   ├── web_search.py       # Online context retrieval
│   │   ├── knowledge.py        # Offline/Local RAG context retrieval
│   │   ├── news.py             # To be updated with reliable real-time APIs
│   │   └── weather.py          # To be updated with reliable real-time APIs
│   ├── core/  
│   │   ├── __init__.py
│   │   ├── orbit_brain.py      # System prompts & Tool routing logic
│   │   └── memory_store.py     # Refactoring target: MongoDB/Redis integration
│   ├── audio/   
│   │   ├── __init__.py
│   │   └── asr_whisper.py  
│   ├── config.py  
│   └── server.py  
├── frontend/  
│   ├── assets/  
│   │   └── styles.css          # Refactoring target: Minimalist ChatGPT-style UI
│   ├── scripts/   
│   │   ├── app.js              # Updated logic for sessions, UI toggles, mic shortcuts
│   │   ├── avatar-renderer.js
│   │   └── avatar-worker.js
│   └── index.html              # Refactoring target: Sidebar layout, Chat Area, Toolbar
├── data/                       # Legacy storage (To be deprecated post-DB migration)
├── knowledge_base/             # Local PDF/Docs for knowledge.py tool
├── .env   
├── requirements.txt
└── run.py   
```

---

## 3. Component Design & Functional Requirements

### 🟢 Backend Subsystems (`/backend`)

**A. API Clients**

* `llm_client.py`: The primary router. Handles requests to OpenRouter/Gemini API or Local Models (LM Studio/Ollama).

**B. External & Internal Tools (`/backend/tools/`)**

* `knowledge.py`: Acts as a standard tool. The LLM Agent decides whether to trigger this tool (for offline, user-specific queries) or `web_search.py` (for online queries). Currently supports PDFs; architecture should allow future extensions.
* `news.py` & `weather.py`: Slated for upgrades to more robust, real-time free APIs.

**C. Core Logic & Memory**

* `memory_store.py`: **Critical Fix required.** The current JSON-based `chat_history` is bugged (saving empty arrays). This module must be rewritten to interface with **MongoDB or Redis** to manage multiple chat sessions, pinned messages, and long-term "Assistant Memory" (Archived context).

### 🔵 Frontend Subsystems (`/frontend`) - UI/UX Overhaul

The UI is being redesigned to mimic a clean, minimalist chat interface.

**1. Left Sidebar (Collapsible)**

* **New Chat:** Button to initialize a fresh session.
* **Recent Chats:** A list of past conversation sessions retrieved from the database.
* **Session Settings (Per Chat):**
  * *Rename:* Agent automatically generates a title based on the first prompt. User can manually edit.
  * *Pin/Unpin:* Keep important chats at the top.
  * *Archive/Unarchive:* Moves the chat's context into the Agent's long-term Assistant Memory.
  * *Delete:* Permanently removes the chat history.

**2. Chat Area (Main View)**

* Displays message bubbles containing text, transcribed voice, and timestamps.
* Support for rendering images/files (Future update).
* **Message-level Settings (Top Right of Chat Area):** Options to Pin, Archive, or Delete the *current active* chat session.

**3. Texting Area (Input Box & Controls)**
The input area features a rich toolbar for dynamic interactions:

* **Add Photos & Files:** UI element prepared (Backend handling in future versions).
* **Create Image:** Triggers a specific image generation tool.
* **Thinking Mode:** Toggles the Agent's deep reasoning mode (if supported by the model).
* **Web Search Toggle:** When active, the Agent is *forced* to use online tools and is restricted from accessing local data (`knowledge.py`).
* **Voice Input Mechanisms (Dual Mode):**
  * *Mode A (Review before send):* Press `Ctrl + M` to start recording. Press `ESC` to cancel. Upon finishing, the audio is transcribed into the Textarea. User can review, edit, and press `Enter` to send (`Shift + Enter` for a new line).
  * *Mode B (Walkie-Talkie):* Hold `Control` to talk, release `Control` to instantly send the transcribed message (Logic to be refined).

**4. Feature Fallback Protocol (`app.js` & Backend coordination)**
If a user requests a feature (e.g., Image Generation or File Upload) that the currently active LLM does not support, the system must not crash. Instead, it must gracefully return a natural language response (e.g., *"Sorry, I don't have this function. If you want to use this, please switch to a supported LLM."*).
