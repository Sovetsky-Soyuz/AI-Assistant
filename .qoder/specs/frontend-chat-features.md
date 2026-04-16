# Frontend Chat Features Implementation Plan

## Context
The backend session APIs (MongoDB CRUD for sessions and messages) were built in Phase 3, but the frontend never wired them up. The sidebar shows no chat history, pin/archive buttons are placeholders, messages lack timestamps, and there's no agent status or offline mode. This plan connects the existing backend to the frontend and adds two new features (search status, offline mode).

---

## Feature 1: Timestamps on Messages

**File:** `frontend/scripts/app.js`

1. Add helper `formatTimestamp(date)` that returns locale time string (e.g., "2:45 PM") using `toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })`
2. Modify `addMessage(role, text, meta = "", timestamp = null)`:
   - Accept optional `timestamp` (ISO string from DB for historical messages)
   - Compute time via `timestamp ? new Date(timestamp) : new Date()`
   - `role === "user"`: footer = `meta ? meta + " \u00b7 " + timeStr : timeStr`
   - `role === "assistant"`: footer = `"Orbit \u00b7 " + timeStr`
   - `role === "system"`: footer = meta (unchanged, no timestamp)

---

## Feature 2: Chat History in Sidebar

**File:** `frontend/scripts/app.js`

1. **Extend `appState`** - add `activeSessionId: null`, `sessions: []`, `isProcessing: false`
2. **New `renderSessions(sessions)`** - partition into pinned/recent, render `div.session-item` elements in sidebar, attach click handler calling `loadSession(id)`, highlight active session
3. **New `loadSession(sessionId)`** - guard if processing, fetch `GET /api/sessions/{id}/messages`, clear message list, re-render messages with historical timestamps, rebuild `appState.conversation`
4. **New `refreshSessions()`** - lightweight fetch of `GET /api/sessions`, update `appState.sessions`, call `renderSessions()`
5. **Modify `refreshState()`** - store `data.sessions` in appState, call `renderSessions()`
6. **Modify `sendPrompt()`**:
   - If no `activeSessionId`: create session via `POST /api/sessions` with title = first 40 chars of prompt
   - Store user message via `POST /api/sessions/{id}/messages`
   - After response: store assistant message, call `refreshSessions()`
   - Remove old `POST /api/history` sync
   - Capture `targetSessionId` at start, discard UI update if session changed mid-request
7. **Modify `startNewChat()`** - set `activeSessionId = null`, re-render sidebar

**Race condition defense:** `setComposerState(true)` + `isProcessing` flag prevent double-send. `targetSessionId` check prevents stale response rendering.

---

## Feature 3: Pin/Unpin & Archive/Unarchive & Delete

**File:** `frontend/scripts/app.js` (replace handlers at lines 287-297)

1. **Pin button**: guard `activeSessionId`, toggle `pinned` via `PUT /api/sessions/{id}`, call `refreshSessions()`
2. **Archive button**: guard `activeSessionId`, set `archived: true` via PUT, call `startNewChat()` + `refreshSessions()`
3. **Delete button**: guard `activeSessionId`, confirm dialog, `DELETE /api/sessions/{id}`, call `startNewChat()` + `refreshSessions()`
4. **New `updateSessionActionButtons()`** - toggle pin button active class based on current session's pinned state

---

## Feature 4: Agent Search Status

**File:** `frontend/scripts/app.js`

1. Add helper `getThinkingStatus()` returning `{ text, copy }`:
   - `webSearchActive` -> `"Searching Online..."` / `"Orbit is searching the web."`
   - `offlineModeActive` -> `"Searching Offline..."` / `"Orbit is searching local documents."`
   - default -> `"Thinking..."` / `"Orbit is processing your request."`
2. Replace `setStageState("thinking", "Thinking...", "...")` call in `sendPrompt()` with dynamic values from helper

---

## Feature 5: Offline Mode Toggle

### Frontend
**Files:** `frontend/index.html`, `frontend/scripts/app.js`

1. **HTML**: Add `<button id="offlineToggle" class="toggle-chip">` with wifi-off SVG after the Search toggle
2. **JS state**: Add `offlineModeActive: false` to appState, add `offlineToggle` to elements
3. **Mutual exclusivity**: Replace `setupToggleChip` for webSearch/offline with custom handlers - activating one deactivates the other
4. **Payload**: Add `offlineMode: appState.offlineModeActive` to `/api/chat` body in `sendPrompt()`

### Backend
**Files:** `backend/server.py`, `backend/api_clients/llm_client.py`, `backend/core/orbit_brain.py`

5. **server.py** `_handle_chat()`: read `offlineMode` from payload, pass `offline_mode=` to `assistant.chat()`
6. **llm_client.py** `chat()`: accept `offline_mode`, thread to `_chat_google()` / `_chat_openrouter()` -> `build_rest_tools()` / `build_system_instruction()`
7. **orbit_brain.py** `build_rest_tools()`: add `offline_mode` param, filter out `search_web` when true
8. **orbit_brain.py** `build_system_instruction()`: add `offline_mode` param, inject "OFFLINE MODE" annotation when true

---

## Implementation Order

1. Feature 1 (Timestamps) - isolated, no dependencies
2. Feature 5 (Offline Mode) - backend self-contained, frontend toggle independent  
3. Feature 4 (Search Status) - trivial once Feature 5 state exists
4. Feature 2 (Chat History) - largest change, touches most code
5. Feature 3 (Pin/Archive/Delete) - builds on Feature 2's infrastructure

---

## Files Modified

| File | Features |
|------|----------|
| `frontend/scripts/app.js` | All 5 |
| `frontend/index.html` | F5 |
| `frontend/assets/styles.css` | F3 (optional pin active style) |
| `backend/server.py` | F5 |
| `backend/api_clients/llm_client.py` | F5 |
| `backend/core/orbit_brain.py` | F5 |

## Verification

1. Start the server with `python run.py` (select provider, skip RAG)
2. Open browser to `http://127.0.0.1:<port>`
3. **Timestamps**: Send a message, verify time appears on user and assistant bubbles
4. **Offline toggle**: Activate Offline, verify Search deactivates; send a message and confirm backend doesn't offer `search_web` tool
5. **Search status**: Activate Search toggle, send a query, verify avatar shows "Searching Online..."
6. **Chat history**: Send messages, verify session appears in sidebar; click "New Chat", verify old session persists in sidebar; click old session, verify messages reload with correct timestamps
7. **Pin/Archive/Delete**: Pin a chat, verify it moves to "Pinned" group; archive, verify it disappears; delete, verify removal
