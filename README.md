<<<<<<< HEAD
# Orbit Virtual Assistant

This main app is now the simple virtual-assistant foundation for the project.

## What it does now

- gives Orbit a lightweight companion stage inspired by AIRI-style assistants
- keeps chat, screen-aware help, local memory, tasks, weather, and live news
- adds an IELTS coach mode for Speaking, Writing, Reading, and Listening
- keeps browser voice input and optional spoken replies
- uses a small Web Worker-driven stage animation so the assistant feels more alive on screen

## Current architecture

- `assistant_app/` handles Gemini chat, tools, memory, weather, and news
- `web/` is the virtual companion shell, chat console, and browser voice layer
- `web/avatar-worker.js` drives the simple animated stage loop
- `data/assistant_memory.json` stores local profile, tasks, notes, weather, and news snapshots

## Run it

1. Copy `.env.example` to `.env`
2. Add your `GEMINI_API_KEY`
3. Start the app:

```powershell
python run.py
```

4. Open `http://127.0.0.1:8000`

## Notes

- This is the simple web-first version, not a full AIRI clone yet.
- The main app is meant to stay realistic for your local laptop while we grow the more advanced realtime and local-runtime pieces later.
- The sibling folders are still useful:
  - `AI_Assistant S2S` is the Gemini Live speech-to-speech version
  - `AI_Assistant_whisper_in_asr` is the local Whisper streaming ASR version
=======
# AI-Assistant
>>>>>>> a50729c20012b8fcb62fd5547a222e1693ce4d08
