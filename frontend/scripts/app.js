// ===========================================
// ORBIT VIRTUAL ASSISTANT - app.js
// Phase 2: Frontend Logic for ChatGPT-style UI
// ===========================================

const VOICE_LANGUAGE_OPTIONS = [
  { value: "default", label: "Browser default" },
  { value: "en-US", label: "English (US)" },
  { value: "en-GB", label: "English (UK)" },
  { value: "vi-VN", label: "Vietnamese" },
  { value: "ja-JP", label: "Japanese" },
  { value: "ko-KR", label: "Korean" },
  { value: "zh-CN", label: "Chinese (Simplified)" },
  { value: "fr-FR", label: "French" },
  { value: "de-DE", label: "German" },
  { value: "es-ES", label: "Spanish" },
  { value: "th-TH", label: "Thai" },
  { value: "id-ID", label: "Indonesian" },
];

function createEmptyTurn(source = "text") {
  return {
    source,
    inputText: "",
    outputText: "",
    userNode: null,
    assistantNode: null,
    userStored: false,
    assistantStored: false,
  };
}

// ---------- Application State ----------

const appState = {
  // Chat & mode
  mode: "simple",
  coachTopic: window.localStorage.getItem("orbit_coach_topic") || "",
  coachLevel: window.localStorage.getItem("orbit_coach_level") || "",
  preferredLanguage: window.localStorage.getItem("orbit_virtual_language") || "default",
  conversation: [],
  memory: null,
  currentTurn: null,
  recentToolEvents: [],

  // Session management
  activeSessionId: null,
  sessions: [],
  isProcessing: false,

  // Screen sharing
  latestScreenImage: null,
  screenStream: null,
  captureIntervalId: null,

  // Voice
  voiceEnabled: false,
  speechRecognition: null,
  speechSupported: false,
  listening: false,
  recognitionStarting: false,
  stopRecognitionAfterStart: false,
  micHeld: false,
  spaceTalking: false,
  hotkeyDown: false,
  liveVoiceTranscript: "",
  liveVoiceName: "Kore",
  silenceTimeoutId: null,

  // Dual voice mode: Mode A (Ctrl+M, review-then-send) vs Mode B (hold Control, instant send)
  modeAActive: false,

  // Avatar
  stageWorker: null,

  // UI panel state
  sidebarOpen: window.localStorage.getItem("orbit_sidebar_open") !== "false",
  drawerOpen: false,

  // Composer toggle states
  webSearchActive: false,
  thinkingActive: false,
  imageGenActive: false,
  offlineModeActive: false,
};

// ---------- DOM Element References ----------

const elements = {
  // Layout
  appLayout: document.getElementById("appLayout"),
  sidebar: document.getElementById("sidebar"),
  chatMain: document.getElementById("chatMain"),

  // Sidebar controls
  newChatBtn: document.getElementById("newChatBtn"),
  sidebarCollapseBtn: document.getElementById("sidebarCollapseBtn"),
  sidebarOpenBtn: document.getElementById("sidebarOpenBtn"),
  pinnedChatsGroup: document.getElementById("pinnedChatsGroup"),
  pinnedChats: document.getElementById("pinnedChats"),
  recentChats: document.getElementById("recentChats"),
  archivedChatsGroup: document.getElementById("archivedChatsGroup"),
  archivedChats: document.getElementById("archivedChats"),

  // Header
  apiStatus: document.getElementById("apiStatus"),
  modelBadge: document.getElementById("modelBadge"),
  runtimeBadge: document.getElementById("runtimeBadge"),
  todayLabel: document.getElementById("todayLabel"),

  // Mode switch
  modeButtons: Array.from(document.querySelectorAll(".mode-button")),

  // Avatar
  avatarStage: document.getElementById("avatarStage"),
  stageStatus: document.getElementById("stageStatus"),
  stageCopy: document.getElementById("stageCopy"),

  // Session actions
  pinChatBtn: document.getElementById("pinChatBtn"),
  archiveChatBtn: document.getElementById("archiveChatBtn"),
  deleteChatBtn: document.getElementById("deleteChatBtn"),

  // Utility drawer
  utilityToggleBtn: document.getElementById("utilityToggleBtn"),
  utilityCloseBtn: document.getElementById("utilityCloseBtn"),
  utilityDrawer: document.getElementById("utilityDrawer"),

  // Coach panel
  coachPanel: document.getElementById("coachPanel"),
  coachTopicInput: document.getElementById("coachTopicInput"),
  coachLevelInput: document.getElementById("coachLevelInput"),
  coachModeCopy: document.getElementById("coachModeCopy"),
  conversationLanguageSelect: document.getElementById("conversationLanguageSelect"),

  // Messages
  messageList: document.getElementById("messageList"),
  toolEvents: document.getElementById("toolEvents"),

  // Composer
  composer: document.getElementById("composer"),
  messageInput: document.getElementById("messageInput"),
  sendButton: document.getElementById("sendButton"),
  attachScreenToggle: document.getElementById("attachScreenToggle"),
  composerVoiceStatus: document.getElementById("composerVoiceStatus"),

  // Composer toggle chips
  attachFilesBtn: document.getElementById("attachFilesBtn"),
  createImageBtn: document.getElementById("createImageBtn"),
  thinkingToggle: document.getElementById("thinkingToggle"),
  webSearchToggle: document.getElementById("webSearchToggle"),
  offlineToggle: document.getElementById("offlineToggle"),

  // Mic
  micButton: document.getElementById("micButton"),
  voiceToggle: document.getElementById("voiceToggle"),
  voiceStatus: document.getElementById("voiceStatus"),
  voiceLanguageSelect: document.getElementById("voiceLanguageSelect"),

  // Quick actions & practice
  quickActions: Array.from(document.querySelectorAll(".ghost-button[data-prompt]")),
  practiceButtons: Array.from(document.querySelectorAll(".practice-button")),

  // Screen sharing
  screenPreview: document.getElementById("screenPreview"),
  screenVideo: document.getElementById("screenVideo"),
  startShareButton: document.getElementById("startShareButton"),
  stopShareButton: document.getElementById("stopShareButton"),

  // Profile
  profileForm: document.getElementById("profileForm"),
  displayNameInput: document.getElementById("displayNameInput"),
  locationInput: document.getElementById("locationInput"),
  routineInput: document.getElementById("routineInput"),

  // Weather & News
  refreshWeatherButton: document.getElementById("refreshWeatherButton"),
  weatherCard: document.getElementById("weatherCard"),
  refreshNewsButton: document.getElementById("refreshNewsButton"),
  newsCard: document.getElementById("newsCard"),

  // Tasks
  taskForm: document.getElementById("taskForm"),
  taskTitleInput: document.getElementById("taskTitleInput"),
  taskPriorityInput: document.getElementById("taskPriorityInput"),
  taskDueDateInput: document.getElementById("taskDueDateInput"),
  taskList: document.getElementById("taskList"),

  // Memory
  memoryHint: document.getElementById("memoryHint"),
  notesList: document.getElementById("notesList"),
  noteForm: document.getElementById("noteForm"),
  noteTextInput: document.getElementById("noteTextInput"),
  noteCategoryInput: document.getElementById("noteCategoryInput"),
  fileAttachInput: document.getElementById("fileAttachInput"),
};

// ---------- Initialization ----------

document.addEventListener("DOMContentLoaded", async () => {
  initializeFormValues();
  bindEvents();
  initAvatarWorker();
  refreshTodayLabel();
  setInterval(refreshTodayLabel, 60000);
  updateModeUI();
  setupSpeechRecognition();
  restoreSidebarState();
  setStageState("idle", "Idle", "Orbit Virtual Assistant is running.");
  addMessage(
    "system",
    "Orbit Virtual Assistant is ready. Type a message, hold Control to talk, or press Ctrl+M to record and review."
  );
  await refreshState();
});

function initializeFormValues() {
  const voiceValue = window.localStorage.getItem("orbit_voice_language") || "default";

  if (elements.voiceLanguageSelect) elements.voiceLanguageSelect.innerHTML = "";
  if (elements.conversationLanguageSelect) elements.conversationLanguageSelect.innerHTML = "";

  VOICE_LANGUAGE_OPTIONS.forEach((option) => {
    if (elements.voiceLanguageSelect) {
      const voiceNode = document.createElement("option");
      voiceNode.value = option.value;
      voiceNode.textContent = option.label;
      voiceNode.selected = option.value === voiceValue;
      elements.voiceLanguageSelect.appendChild(voiceNode);
    }

    if (elements.conversationLanguageSelect) {
      const conversationNode = document.createElement("option");
      conversationNode.value = option.value;
      conversationNode.textContent = option.label;
      conversationNode.selected = option.value === appState.preferredLanguage;
      elements.conversationLanguageSelect.appendChild(conversationNode);
    }
  });

  if (elements.coachTopicInput) {
    elements.coachTopicInput.value = appState.coachTopic;
  }
  if (elements.coachLevelInput) {
    elements.coachLevelInput.value = appState.coachLevel;
  }
}

// ---------- Event Binding ----------

function bindEvents() {
  // Voice settings
  elements.voiceToggle.addEventListener("change", (event) => {
    appState.voiceEnabled = event.target.checked;
  });

  elements.voiceLanguageSelect.addEventListener("change", () => {
    window.localStorage.setItem("orbit_voice_language", elements.voiceLanguageSelect.value);
    setVoiceStatus(`Voice language: ${getSelectedLanguageLabel(elements.voiceLanguageSelect.value)}`);
    if (appState.speechRecognition) {
      appState.speechRecognition.lang = resolveRecognitionLanguage();
    }
  });

  elements.conversationLanguageSelect.addEventListener("change", () => {
    appState.preferredLanguage = elements.conversationLanguageSelect.value;
    window.localStorage.setItem("orbit_virtual_language", appState.preferredLanguage);
  });

  // Mode switch
  elements.modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setMode(button.dataset.mode || "simple");
    });
  });

  // Coach inputs
  elements.coachTopicInput.addEventListener("input", () => {
    appState.coachTopic = elements.coachTopicInput.value.trim();
    window.localStorage.setItem("orbit_coach_topic", appState.coachTopic);
  });

  elements.coachLevelInput.addEventListener("input", () => {
    appState.coachLevel = elements.coachLevelInput.value.trim() || "Beginner";
    window.localStorage.setItem("orbit_coach_level", appState.coachLevel);
  });

  // Sidebar toggle
  elements.sidebarCollapseBtn.addEventListener("click", toggleSidebar);
  elements.sidebarOpenBtn.addEventListener("click", toggleSidebar);

  // Utility drawer toggle
  elements.utilityToggleBtn.addEventListener("click", toggleDrawer);
  elements.utilityCloseBtn.addEventListener("click", toggleDrawer);

  // New chat
  elements.newChatBtn.addEventListener("click", startNewChat);

  // Session actions
  elements.pinChatBtn.addEventListener("click", async () => {
    if (!appState.activeSessionId) {
      addMessage("system", "Start a conversation first.");
      return;
    }
    const session = appState.sessions.find((s) => s.session_id === appState.activeSessionId);
    const newPinned = !(session && session.pinned);
    try {
      const res = await fetch(`/api/sessions/${appState.activeSessionId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pinned: newPinned }),
      });
      if (res.ok) {
        addMessage("system", newPinned ? "Chat pinned." : "Chat unpinned.");
        await refreshSessions();
        updateSessionActionButtons();
      }
    } catch (err) {
      addMessage("system", `Failed to update pin: ${err.message}`);
    }
  });
  elements.archiveChatBtn.addEventListener("click", async () => {
    if (!appState.activeSessionId) {
      addMessage("system", "Start a conversation first.");
      return;
    }
    const session = appState.sessions.find((s) => s.session_id === appState.activeSessionId);
    const isArchived = session && session.archived;
    try {
      const res = await fetch(`/api/sessions/${appState.activeSessionId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ archived: !isArchived }),
      });
      if (res.ok) {
        if (!isArchived) {
          startNewChat();
          addMessage("system", "Chat archived.");
        } else {
          addMessage("system", "Chat unarchived.");
        }
        await refreshSessions();
        updateSessionActionButtons();
      }
    } catch (err) {
      addMessage("system", `Failed to ${isArchived ? "unarchive" : "archive"}: ${err.message}`);
    }
  });
  elements.deleteChatBtn.addEventListener("click", async () => {
    if (!appState.activeSessionId) {
      if (appState.conversation.length > 0) {
        startNewChat();
        addMessage("system", "Conversation cleared.");
      }
      return;
    }
    if (!confirm("Delete this chat permanently?")) return;
    try {
      const res = await fetch(`/api/sessions/${appState.activeSessionId}`, { method: "DELETE" });
      if (res.ok) {
        startNewChat();
        addMessage("system", "Chat deleted.");
        await refreshSessions();
      }
    } catch (err) {
      addMessage("system", `Failed to delete: ${err.message}`);
    }
  });

  // Composer toggle chips
  elements.attachFilesBtn.addEventListener("click", () => {
    elements.fileAttachInput.click();
  });

  elements.fileAttachInput.addEventListener("change", handleFileAttach);

  setupToggleChip(elements.createImageBtn, "imageGenActive");
  setupToggleChip(elements.thinkingToggle, "thinkingActive");

  // Search and Offline toggles are mutually exclusive
  elements.webSearchToggle.addEventListener("click", () => {
    appState.webSearchActive = !appState.webSearchActive;
    elements.webSearchToggle.classList.toggle("active", appState.webSearchActive);
    if (appState.webSearchActive) {
      appState.offlineModeActive = false;
      elements.offlineToggle.classList.remove("active");
    }
  });

  elements.offlineToggle.addEventListener("click", () => {
    appState.offlineModeActive = !appState.offlineModeActive;
    elements.offlineToggle.classList.toggle("active", appState.offlineModeActive);
    if (appState.offlineModeActive) {
      appState.webSearchActive = false;
      elements.webSearchToggle.classList.remove("active");
    }
  });

  // Push-to-Talk: mic button (Mode B)
  elements.micButton.addEventListener("pointerdown", handleMicPointerDown);
  window.addEventListener("pointerup", handleMicPointerUp);
  window.addEventListener("pointercancel", handleMicPointerUp);

  // Keyboard voice shortcuts (Ctrl+M for Mode A, hold Control for Mode B)
  window.addEventListener("keydown", handleHotkeyDown);
  window.addEventListener("keyup", handleHotkeyUp);

  // Form submission
  elements.composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const prompt = elements.messageInput.value.trim();
    if (!prompt) return;
    elements.messageInput.value = "";
    elements.messageInput.style.height = "";
    await sendPrompt(prompt);
  });

  // Enter to send (Shift+Enter for newline)
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      // Don't send during Mode A recording
      if (appState.modeAActive && (appState.listening || appState.recognitionStarting)) {
        return;
      }
      const prompt = elements.messageInput.value.trim();
      if (prompt) {
        elements.sendButton.click();
      }
    }
  });

  // Textarea auto-resize
  elements.messageInput.addEventListener("input", autoResizeTextarea);

  // Quick actions
  elements.quickActions.forEach((button) => {
    button.addEventListener("click", async () => {
      const needsScreen = button.dataset.needsScreen === "true";
      if (needsScreen && !appState.latestScreenImage) {
        addMessage("system", "Start screen sharing first so Orbit can use your current screen as context.");
        return;
      }

      let finalPrompt = button.dataset.prompt || "";

      if (finalPrompt.includes("RAG") || finalPrompt.includes("local papers")) {
        const topic = elements.coachTopicInput ? elements.coachTopicInput.value : appState.coachTopic;
        finalPrompt = `${finalPrompt} The topic is: ${topic}. YOU MUST call the search_local_docs tool first.`;
      }

      await sendPrompt(finalPrompt, { forceScreen: needsScreen });
    });
  });

  // Practice buttons
  elements.practiceButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      setMode("coach");
      const currentTopic = elements.coachTopicInput ? elements.coachTopicInput.value : appState.coachTopic;
      const finalPrompt = `${button.dataset.prompt} The subject is: ${currentTopic}. YOU MUST use the 'search_local_docs' tool to retrieve context before generating the response.`;
      await sendPrompt(finalPrompt);
    });
  });

  // Existing panel event handlers
  elements.startShareButton.addEventListener("click", startScreenShare);
  elements.stopShareButton.addEventListener("click", stopScreenShare);
  elements.profileForm.addEventListener("submit", saveProfile);
  elements.refreshWeatherButton.addEventListener("click", refreshWeather);
  elements.refreshNewsButton.addEventListener("click", refreshNews);
  elements.taskForm.addEventListener("submit", addTask);
  elements.noteForm.addEventListener("submit", addNoteManual);

  // Window blur - stop any active voice
  window.addEventListener("blur", () => {
    if (modeBDelayTimer) {
      clearTimeout(modeBDelayTimer);
      modeBDelayTimer = null;
    }
    if (appState.hotkeyDown || appState.micHeld) {
      appState.hotkeyDown = false;
      appState.micHeld = false;
      appState.spaceTalking = false;
      if (!appState.modeAActive) {
        stopVoiceCapture();
      }
    }
  });
}

// ---------- UI Panel Controls ----------

function toggleSidebar() {
  elements.appLayout.classList.toggle("sidebar-collapsed");
  appState.sidebarOpen = !elements.appLayout.classList.contains("sidebar-collapsed");
  window.localStorage.setItem("orbit_sidebar_open", appState.sidebarOpen ? "true" : "false");
}

function restoreSidebarState() {
  if (!appState.sidebarOpen) {
    elements.appLayout.classList.add("sidebar-collapsed");
  }
}

function toggleDrawer() {
  elements.appLayout.classList.toggle("drawer-open");
  appState.drawerOpen = elements.appLayout.classList.contains("drawer-open");
}

function startNewChat() {
  appState.activeSessionId = null;
  appState.conversation = [];
  elements.messageList.innerHTML = "";
  elements.toolEvents.innerHTML = "";
  elements.attachFilesBtn.classList.remove("active");
  addMessage("system", "New conversation started.");
  renderSessions(appState.sessions);
  updateSessionActionButtons();
  elements.messageInput.focus();
}

function setupToggleChip(button, stateKey) {
  button.addEventListener("click", () => {
    appState[stateKey] = !appState[stateKey];
    button.classList.toggle("active", appState[stateKey]);
  });
}

function autoResizeTextarea() {
  const textarea = elements.messageInput;
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 180) + "px";
}

// ---------- Avatar Worker ----------

function initAvatarWorker() {
  if (!window.Worker) {
    elements.runtimeBadge.textContent = "No Web Worker";
    return;
  }

  const worker = new Worker("/avatar-worker.js");
  worker.addEventListener("message", (event) => {
    const payload = event.data || {};
    if (payload.type !== "frame") return;
    elements.avatarStage.style.setProperty("--stage-sway", `${payload.sway || 0}px`);
    elements.avatarStage.style.setProperty("--stage-pulse", String(payload.pulse || 1));
    elements.avatarStage.style.setProperty("--stage-blink", String(payload.blink ?? 1));
    elements.avatarStage.style.setProperty("--stage-mouth", String(payload.mouth || 0));
  });
  appState.stageWorker = worker;
}

function setStageState(state, statusText, copyText = "") {
  elements.avatarStage.dataset.stageState = state;
  elements.stageStatus.textContent = statusText;
  if (copyText) {
    elements.stageCopy.textContent = copyText;
  }
  if (appState.stageWorker) {
    appState.stageWorker.postMessage({ type: "set-state", state });
  }
}

// ---------- Mode & UI State ----------

function refreshTodayLabel() {
  elements.todayLabel.textContent = new Date().toLocaleString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function updateModeUI() {
  elements.modeButtons.forEach((button) =>
    button.classList.toggle("active", button.dataset.mode === appState.mode)
  );
  elements.coachPanel.classList.toggle("hidden", appState.mode !== "coach");
  if (appState.mode === "coach") {
    elements.coachModeCopy.textContent =
      "Orbit will act as a personal tutor. For best results, enable RAG mode to use your local documents as the textbook.";
  }
}

function setMode(mode, coachTopic = appState.coachTopic) {
  appState.mode = mode;
  appState.coachTopic = coachTopic;
  if (elements.coachTopicInput) {
    elements.coachTopicInput.value = appState.coachTopic || "";
  }
  updateModeUI();
}

// ---------- Speech Recognition ----------

function setupSpeechRecognition() {
  const SpeechRecognitionClass = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognitionClass) {
    appState.speechSupported = false;
    updateMicButton();
    elements.voiceLanguageSelect.disabled = true;
    setVoiceStatus("This browser does not expose speech recognition.");
    return;
  }

  const recognition = new SpeechRecognitionClass();
  recognition.lang = resolveRecognitionLanguage();
  recognition.interimResults = true;
  recognition.continuous = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    appState.recognitionStarting = false;
    appState.listening = true;
    updateMicButton();

    // Mode A: don't create chat bubbles (transcript goes to textarea)
    if (!appState.modeAActive) {
      ensureVoiceTurn();
      ensureVoiceDraft();
    }

    setStageState("listening", "Listening...", "Orbit is capturing speech.");
    setVoiceStatus(`Listening in ${getSelectedLanguageLabel(elements.voiceLanguageSelect.value)}...`);

    if (appState.stopRecognitionAfterStart) {
      recognition.stop();
    }
  };

  recognition.onresult = (event) => {
    let transcript = "";
    for (const result of event.results) {
      transcript += `${result[0].transcript} `;
    }
    appState.liveVoiceTranscript = transcript.trim();

    if (appState.modeAActive) {
      // Mode A: put transcript in textarea for review
      elements.messageInput.value = appState.liveVoiceTranscript;
      autoResizeTextarea();
      setVoiceStatus("Transcribing...");
    } else {
      // Mode B: put transcript in chat bubble
      ensureVoiceTurn();
      ensureVoiceDraft();
      appState.currentTurn.inputText = appState.liveVoiceTranscript;
      appState.currentTurn.userNode.querySelector(".message-body").textContent =
        appState.liveVoiceTranscript || "Listening...";
      appState.currentTurn.userNode.querySelector(".message-meta").textContent = "Voice transcript";
      setVoiceStatus("Capturing speech...");
    }
  };

  recognition.onerror = (event) => {
    appState.recognitionStarting = false;
    appState.listening = false;
    appState.stopRecognitionAfterStart = false;
    appState.micHeld = false;
    appState.spaceTalking = false;
    appState.modeAActive = false;
    updateMicButton();
    if (event.error !== "aborted") {
      setVoiceStatus(`Voice input error: ${event.error}`);
      setStageState("idle", "Idle", "Speech recognition returned an error.");
    }
  };

  recognition.onend = async () => {
    const transcript = appState.liveVoiceTranscript.trim();
    const wasModea = appState.modeAActive;

    appState.recognitionStarting = false;
    appState.listening = false;
    appState.stopRecognitionAfterStart = false;
    appState.micHeld = false;
    appState.spaceTalking = false;
    appState.modeAActive = false;
    updateMicButton();

    // --- Mode A: leave transcript in textarea for user review ---
    if (wasModea) {
      appState.liveVoiceTranscript = "";
      if (transcript) {
        elements.messageInput.value = transcript;
        elements.messageInput.focus();
        autoResizeTextarea();
        setVoiceStatus("Review and press Enter to send");
      } else {
        setVoiceStatus("Voice input idle");
      }
      setStageState("idle", "Idle", "Voice transcription ready for review.");
      return;
    }

    // --- Mode B: auto-send transcript ---
    if (transcript) {
      const voiceTurn = appState.currentTurn || createEmptyTurn("voice");
      voiceTurn.inputText = transcript;
      if (voiceTurn.userNode) {
        voiceTurn.userNode.querySelector(".message-body").textContent = transcript;
        voiceTurn.userNode.querySelector(".message-meta").textContent = "Voice input";
      }
      appState.liveVoiceTranscript = "";
      await sendPrompt(transcript, { fromVoice: true, voiceTurn });
      return;
    }

    // No transcript - clean up
    if (appState.currentTurn?.userNode && !appState.currentTurn.inputText.trim()) {
      appState.currentTurn.userNode.remove();
      appState.currentTurn = null;
    }
    setVoiceStatus("Voice input idle");
    setStageState("idle", "Idle", "Orbit is waiting for your next question.");
  };

  appState.speechRecognition = recognition;
  appState.speechSupported = true;
  updateMicButton();
  setVoiceStatus(`Voice ready (${getSelectedLanguageLabel(elements.voiceLanguageSelect.value)})`);
}

// ---------- Voice Input Handlers ----------

let modeBDelayTimer = null;

function handleHotkeyDown(event) {
  // --- Ctrl+M: Toggle Mode A (record-then-review) ---
  if (event.key.toLowerCase() === "m" && event.ctrlKey && !event.repeat) {
    // Cancel any pending Mode B timer
    if (modeBDelayTimer) {
      clearTimeout(modeBDelayTimer);
      modeBDelayTimer = null;
    }

    // Allow Ctrl+M in messageInput textarea but block in other form fields
    const active = document.activeElement;
    if (active && active !== elements.messageInput &&
        ["INPUT", "SELECT"].includes(active.tagName)) {
      return;
    }

    event.preventDefault();

    if (appState.modeAActive) {
      // Stop Mode A recording - onend will keep transcript in textarea
      stopVoiceCapture();
    } else if (!appState.listening && !appState.recognitionStarting) {
      // Start Mode A recording
      appState.modeAActive = true;
      void startVoiceCapture();
    }
    return;
  }

  // --- ESC: Cancel Mode A recording ---
  if (event.key === "Escape") {
    if (appState.modeAActive && (appState.listening || appState.recognitionStarting)) {
      event.preventDefault();
      appState.modeAActive = false;
      appState.liveVoiceTranscript = "";
      stopVoiceCapture();
      elements.messageInput.value = "";
      autoResizeTextarea();
      setVoiceStatus("Recording cancelled");
      setStageState("idle", "Idle");
    }
    return;
  }

  // --- Hold Control: Mode B (instant-send) with delay to avoid Ctrl+M conflict ---
  if (event.key === "Control" && !event.repeat && !shouldIgnoreHotkey()) {
    appState.hotkeyDown = true;
    modeBDelayTimer = window.setTimeout(() => {
      modeBDelayTimer = null;
      if (appState.hotkeyDown && !appState.modeAActive &&
          !appState.listening && !appState.recognitionStarting) {
        appState.spaceTalking = true;
        void startVoiceCapture();
      }
    }, 200);
    return;
  }
}

function handleHotkeyUp(event) {
  if (event.key === "Control") {
    // Cancel Mode B delay timer if still pending
    if (modeBDelayTimer) {
      clearTimeout(modeBDelayTimer);
      modeBDelayTimer = null;
    }

    if (appState.hotkeyDown) {
      appState.hotkeyDown = false;
      if (!appState.modeAActive) {
        appState.spaceTalking = false;
        stopVoiceCapture();
      }
    }
  }
}

// Mic button click-and-hold (Mode B behavior)
function handleMicPointerDown(event) {
  if (event.button !== 0) return;
  if (appState.modeAActive) return; // Don't interfere with Mode A
  appState.micHeld = true;
  void startVoiceCapture();
}

function handleMicPointerUp() {
  if (!appState.micHeld) return;
  appState.micHeld = false;
  stopVoiceCapture();
}

function shouldIgnoreHotkey() {
  const active = document.activeElement;
  if (!active) return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName) || active.isContentEditable;
}

async function startVoiceCapture() {
  if (!appState.speechSupported || !appState.speechRecognition) return;
  if (appState.listening || appState.recognitionStarting) return;

  try {
    appState.recognitionStarting = true;
    appState.stopRecognitionAfterStart = false;
    appState.speechRecognition.lang = resolveRecognitionLanguage();
    appState.speechRecognition.start();
    updateMicButton();
  } catch (error) {
    appState.recognitionStarting = false;
    appState.modeAActive = false;
    updateMicButton();
    setVoiceStatus(error.message || "Could not start speech recognition.");
  }
}

function stopVoiceCapture() {
  if (!appState.speechRecognition) return;

  if (appState.recognitionStarting && !appState.listening) {
    appState.stopRecognitionAfterStart = true;
    return;
  }
  if (appState.listening) {
    appState.speechRecognition.stop();
  }
}

function resolveRecognitionLanguage() {
  return elements.voiceLanguageSelect.value === "default"
    ? navigator.language || "en-US"
    : elements.voiceLanguageSelect.value;
}

function updateMicButton() {
  if (!appState.speechSupported) {
    elements.micButton.disabled = true;
    elements.micButton.title = "Voice unavailable";
    return;
  }

  elements.micButton.disabled = false;
  if (appState.listening || appState.recognitionStarting) {
    elements.micButton.title = appState.modeAActive ? "Recording (Ctrl+M to stop)" : "Release to send";
    elements.micButton.classList.add("active");
  } else {
    elements.micButton.title = "Hold to talk (Control)";
    elements.micButton.classList.remove("active");
  }
}

function ensureVoiceTurn() {
  if (!appState.currentTurn || appState.currentTurn.source !== "voice") {
    appState.currentTurn = createEmptyTurn("voice");
  }
}

function ensureVoiceDraft() {
  if (!appState.currentTurn.userNode) {
    appState.currentTurn.userNode = addMessage("user", "Listening...", "Voice transcript");
  }
}

function setVoiceStatus(text) {
  elements.voiceStatus.textContent = text;
  elements.composerVoiceStatus.textContent = text;
}

// ---------- API Communication ----------

async function refreshState() {
  const response = await fetch("/api/state");
  const data = await response.json();

  appState.memory = data.memory;

  if (data.history && data.history.length > 0) {
    appState.conversation = data.history;
  }

  appState.liveVoiceName = data.liveVoiceName || "Kore";
  const provider = data.provider || "Gemini";
  elements.apiStatus.textContent = data.hasApiKey ? `${provider} key detected` : "Add API_KEY to enable chat";
  elements.modelBadge.textContent = data.model ? `${data.model}` : "Model not set";
  elements.runtimeBadge.textContent = "Browser + REST";

  elements.displayNameInput.value = data.memory.profile.display_name || "";
  elements.locationInput.value = data.memory.profile.location || data.defaultLocation || "";
  elements.routineInput.value = data.memory.profile.routine || "";

  refreshMemoryViews();

  appState.sessions = data.sessions || [];
  renderSessions(appState.sessions);
}

async function sendPrompt(prompt, options = {}) {
  if (appState.currentTurn && appState.currentTurn.assistantNode) return;
  if (appState.isProcessing) return;

  const attachScreen = options.forceScreen || elements.attachScreenToggle.checked;
  const screenImage = attachScreen ? appState.latestScreenImage : null;
  const priorConversation = [...appState.conversation];
  const shouldSpeakReply = appState.voiceEnabled;
  const turn = options.voiceTurn || createEmptyTurn(options.fromVoice ? "voice" : "text");

  turn.inputText = prompt;

  if (!turn.userNode) {
    turn.userNode = addMessage("user", prompt, attachScreen && screenImage ? "Screen attached" : "");
  } else {
    turn.userNode.querySelector(".message-body").textContent = prompt;
    turn.userNode.querySelector(".message-meta").textContent =
      attachScreen && screenImage ? "Screen attached" : "Voice input";
  }

  if (!turn.userStored) {
    appState.conversation.push({ role: "user", text: prompt });
    turn.userStored = true;
  }

  const placeholderText = getThinkingStatus().text;
  turn.assistantNode = turn.assistantNode || addMessage("assistant", placeholderText);
  turn.assistantNode.querySelector(".message-body").textContent = placeholderText;
  appState.currentTurn = turn;

  setComposerState(true);
  appState.isProcessing = true;
  const thinkingStatus = getThinkingStatus();
  setStageState("thinking", thinkingStatus.text, thinkingStatus.copy);

  // Auto-create session on first message
  try {
    if (!appState.activeSessionId) {
      const sessionRes = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: prompt.substring(0, 40) + (prompt.length > 40 ? "..." : "") }),
      });
      const sessionData = await sessionRes.json();
      if (sessionRes.ok && sessionData.session) {
        appState.activeSessionId = sessionData.session.session_id;
      }
    }
  } catch (err) {
    console.error("Session creation error:", err);
  }

  const targetSessionId = appState.activeSessionId;

  // Store user message in session
  if (targetSessionId) {
    fetch(`/api/sessions/${targetSessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: "user", text: prompt }),
    }).catch((err) => console.error("User message store error:", err));
  }

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: prompt,
        conversation: priorConversation,
        screenImage,
        mode: appState.mode,
        coachTopic: appState.coachTopic,
        coachLevel: appState.coachLevel,
        preferredLanguage: appState.preferredLanguage,
        webSearchOnly: appState.webSearchActive,
        thinkingMode: appState.thinkingActive,
        imageGen: appState.imageGenActive,
        offlineMode: appState.offlineModeActive,
        sessionId: appState.activeSessionId || "",
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Chat request failed.");
    }

    // Discard UI update if user switched sessions during the request
    if (targetSessionId && targetSessionId !== appState.activeSessionId) {
      // Message is already stored in DB; just skip UI rendering
      return;
    }

    turn.outputText = data.reply;

    if (typeof marked !== "undefined") {
      turn.assistantNode.querySelector(".message-body").innerHTML = marked.parse(data.reply);
      formatLinks(turn.assistantNode.querySelector(".message-body"));
    } else {
      turn.assistantNode.querySelector(".message-body").textContent = data.reply;
    }

    const isRefusal = data.reply.includes("safety and moderation guidelines");
    if (isRefusal) {
      appState.conversation.pop();
    } else {
      appState.conversation.push({ role: "assistant", text: data.reply });

      // Store assistant message in session
      if (targetSessionId) {
        fetch(`/api/sessions/${targetSessionId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role: "assistant", text: data.reply }),
        }).catch((err) => console.error("Assistant message store error:", err));
      }

      refreshSessions();
    }

    appState.memory = data.memory;
    appState.recentToolEvents = data.toolEvents || [];
    refreshMemoryViews();
    renderToolEvents(appState.recentToolEvents);
    setStageState("speaking", "Replying", "Model reply is visible in chat.");

    if (shouldSpeakReply && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(data.reply);
      const voices = window.speechSynthesis.getVoices();
      const selectedVoice = voices.find((v) =>
        v.name.toLowerCase().includes(appState.liveVoiceName.toLowerCase())
      );
      if (selectedVoice) {
        utterance.voice = selectedVoice;
        utterance.lang = selectedVoice.lang;
      }
      utterance.onend = () => setStageState("idle", "Idle");
      window.speechSynthesis.speak(utterance);
    } else {
      window.setTimeout(() => setStageState("idle", "Idle"), 320);
    }
  } catch (error) {
    const errorMessage = error.message.includes("image input")
      ? "I'm sorry, the current AI model doesn't support image analysis. Please try text-only or switch models."
      : `Error: ${error.message}`;

    turn.assistantNode.querySelector(".message-body").textContent = errorMessage;
    turn.assistantNode.classList.add("system");
    appState.conversation.pop();
    setStageState("idle", "Error occurred.");
  } finally {
    appState.currentTurn = null;
    appState.isProcessing = false;
    setComposerState(false);
    setVoiceStatus("Voice input idle");
  }
}

// ---------- Message Rendering ----------

function addMessage(role, text, meta = "", timestamp = null) {
  const message = document.createElement("article");
  message.className = `message ${role}`;

  const body = document.createElement("div");
  body.className = "message-body";

  if (role === "assistant" && typeof marked !== "undefined") {
    body.innerHTML = marked.parse(text);
    formatLinks(body);
  } else {
    body.textContent = text;
  }

  const footer = document.createElement("div");
  footer.className = "message-meta";

  if (role === "system") {
    footer.textContent = meta;
  } else {
    const timeStr = formatTimestamp(timestamp || new Date());
    if (role === "user") {
      footer.textContent = meta ? `${meta} \u00b7 ${timeStr}` : timeStr;
    } else {
      footer.textContent = `Orbit \u00b7 ${timeStr}`;
    }
  }

  message.append(body, footer);

  // Add "Add to Notes" button for assistant and user messages (not system)
  if (role === "assistant" || role === "user") {
    const actions = document.createElement("div");
    actions.className = "message-actions";

    const noteBtn = document.createElement("button");
    noteBtn.className = "message-action-btn";
    noteBtn.title = "Save to Notes";
    noteBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg><span>Add to Notes</span>';
    noteBtn.addEventListener("click", () => saveMessageAsNote(body, message));
    actions.appendChild(noteBtn);

    message.appendChild(actions);
  }

  elements.messageList.append(message);
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
  return message;
}

function renderToolEvents(events) {
  elements.toolEvents.innerHTML = "";
  events.forEach((event) => {
    const pill = document.createElement("span");
    pill.className = "tool-pill";
    pill.textContent = event.label;
    elements.toolEvents.appendChild(pill);
  });
}

// ---------- Session Management ----------

function renderSessions(sessions) {
  const pinned = sessions.filter((s) => s.pinned && !s.archived);
  const recent = sessions.filter((s) => !s.pinned && !s.archived);
  const archived = sessions.filter((s) => s.archived);

  // Pinned group
  if (pinned.length > 0) {
    elements.pinnedChatsGroup.style.display = "";
  } else {
    elements.pinnedChatsGroup.style.display = "none";
  }

  elements.pinnedChats.innerHTML = "";
  pinned.forEach((s) => {
    elements.pinnedChats.appendChild(createSessionItem(s));
  });

  // Recent group
  elements.recentChats.innerHTML = "";
  recent.slice(0, 30).forEach((s) => {
    elements.recentChats.appendChild(createSessionItem(s));
  });

  // Archived group
  if (archived.length > 0) {
    elements.archivedChatsGroup.style.display = "";
  } else {
    elements.archivedChatsGroup.style.display = "none";
  }

  elements.archivedChats.innerHTML = "";
  archived.slice(0, 20).forEach((s) => {
    elements.archivedChats.appendChild(createSessionItem(s));
  });
}

function createSessionItem(session) {
  const item = document.createElement("div");
  item.className = "session-item";
  if (session.session_id === appState.activeSessionId) {
    item.classList.add("active");
  }

  const icon = document.createElement("span");
  icon.className = "session-icon";
  icon.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>';

  const title = document.createElement("span");
  title.className = "session-title";
  title.textContent = session.title || "Untitled chat";

  item.append(icon, title);

  if (session.pinned) {
    const pin = document.createElement("span");
    pin.className = "session-pin-indicator";
    pin.textContent = "\u{1F4CC}";
    item.appendChild(pin);
  }

  item.addEventListener("click", () => loadSession(session.session_id));
  return item;
}

async function loadSession(sessionId) {
  if (appState.isProcessing) return;
  if (sessionId === appState.activeSessionId) return;

  appState.activeSessionId = sessionId;
  appState.conversation = [];
  elements.messageList.innerHTML = "";
  elements.toolEvents.innerHTML = "";

  try {
    const response = await fetch(`/api/sessions/${sessionId}/messages`);
    const data = await response.json();
    const messages = data.messages || [];

    messages.forEach((msg) => {
      addMessage(msg.role, msg.text, "", msg.created_at);
      appState.conversation.push({ role: msg.role, text: msg.text });
    });
  } catch (err) {
    addMessage("system", `Failed to load session: ${err.message}`);
  }

  renderSessions(appState.sessions);
  updateSessionActionButtons();
}

async function refreshSessions() {
  try {
    const response = await fetch("/api/sessions?include_archived=true");
    const data = await response.json();
    appState.sessions = data.sessions || [];
    renderSessions(appState.sessions);
  } catch (err) {
    console.error("Failed to refresh sessions:", err);
  }
}

function updateSessionActionButtons() {
  const session = appState.sessions.find((s) => s.session_id === appState.activeSessionId);
  if (session && session.pinned) {
    elements.pinChatBtn.classList.add("active");
    elements.pinChatBtn.title = "Unpin this chat";
  } else {
    elements.pinChatBtn.classList.remove("active");
    elements.pinChatBtn.title = "Pin this chat";
  }
  if (session && session.archived) {
    elements.archiveChatBtn.classList.add("active");
    elements.archiveChatBtn.title = "Unarchive this chat";
  } else {
    elements.archiveChatBtn.classList.remove("active");
    elements.archiveChatBtn.title = "Archive this chat";
  }
}

// ---------- Memory & Data Views ----------

function refreshMemoryViews() {
  if (!appState.memory) return;
  renderWeather(appState.memory.last_weather);
  renderNews(appState.memory.last_news);
  renderTasks(appState.memory.tasks);
  renderNotes(appState.memory.profile.notes);
  updateMemoryHint(appState.memory.profile.notes || []);
}

function updateMemoryHint(notes) {
  const recentNote = (notes || []).slice(-1)[0];
  elements.memoryHint.textContent = recentNote
    ? `Latest memory: ${recentNote.text}`
    : "Recent notes appear when Orbit remembers something for later.";
}

function renderWeather(weather) {
  if (!weather) {
    elements.weatherCard.innerHTML = '<p class="muted">No weather loaded yet.</p>';
    return;
  }

  elements.weatherCard.innerHTML = `
    <div class="weather-item">
      <p class="task-title">${escapeHtml(weather.location)}</p>
      <p>${escapeHtml(weather.condition)}</p>
      <p class="tiny">${escapeHtml(weather.advice || "")}</p>
    </div>
    <div class="weather-grid">
      <div class="weather-item"><strong>${formatValue(weather.temperature_c)}&deg;C</strong><div class="tiny">Temperature</div></div>
      <div class="weather-item"><strong>${formatValue(weather.feels_like_c)}&deg;C</strong><div class="tiny">Feels like</div></div>
      <div class="weather-item"><strong>${formatValue(weather.high_c)}&deg; / ${formatValue(weather.low_c)}&deg;</strong><div class="tiny">High / low</div></div>
      <div class="weather-item"><strong>${formatValue(weather.rain_chance_pct)}%</strong><div class="tiny">Rain chance</div></div>
    </div>
  `;
}

function renderNews(news) {
  if (!news || !Array.isArray(news.items) || !news.items.length) {
    elements.newsCard.innerHTML = '<p class="muted">No news loaded yet.</p>';
    return;
  }

  elements.newsCard.innerHTML = news.items
    .map(
      (item) => `
        <article class="news-item">
          <p class="task-title">${escapeHtml(item.title)}</p>
          <div class="tiny">${escapeHtml(item.source || "Google News")}${item.published_at ? ` - ${escapeHtml(item.published_at)}` : ""}</div>
          <a href="${escapeHtml(item.link)}" target="_blank" rel="noreferrer">Open headline</a>
        </article>
      `
    )
    .join("");
}

function renderTasks(tasks) {
  const openTasks = (tasks || []).filter((task) => task.status === "open");
  if (!openTasks.length) {
    elements.taskList.innerHTML = '<p class="muted">No open tasks yet.</p>';
    return;
  }

  elements.taskList.innerHTML = "";
  openTasks.forEach((task) => {
    const item = document.createElement("div");
    item.className = "task-item";
    item.innerHTML = `
      <div>
        <p class="task-title">${escapeHtml(task.title)}</p>
        <div class="tiny">#${escapeHtml(task.id)} - ${escapeHtml(task.priority)} priority${task.due_date ? ` - due ${escapeHtml(task.due_date)}` : ""}</div>
      </div>
      <button class="ghost-button">Done</button>
    `;
    item.querySelector("button").addEventListener("click", () => completeTask(task.id));
    elements.taskList.appendChild(item);
  });
}

function renderNotes(notes) {
  const recentNotes = (notes || []).slice(-4).reverse();
  if (!recentNotes.length) {
    elements.notesList.innerHTML =
      '<p class="muted">Ask Orbit to remember preferences, routines, or useful details.</p>';
    return;
  }

  elements.notesList.innerHTML = "";
  recentNotes.forEach((note) => {
    const item = document.createElement("div");
    item.className = "note-item";
    item.innerHTML = `
      <div class="note-content">
        <p class="note-title">${escapeHtml(note.category)}</p>
        <p>${escapeHtml(note.text)}</p>
        <div class="tiny">${escapeHtml(note.created_at)}</div>
      </div>
      <button class="note-delete-btn" title="Delete this note">&times;</button>
    `;
    item.querySelector(".note-delete-btn").addEventListener("click", () => deleteNote(note.id));
    elements.notesList.appendChild(item);
  });
}

// ---------- Profile, Weather, News, Tasks ----------

async function saveProfile(event) {
  event.preventDefault();

  const response = await fetch("/api/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      displayName: elements.displayNameInput.value.trim(),
      location: elements.locationInput.value.trim(),
      routine: elements.routineInput.value.trim(),
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    addMessage("system", data.error || "Could not save your profile.");
    return;
  }

  appState.memory = data.memory;
  refreshMemoryViews();
  addMessage("system", "Profile saved for Orbit.");
}

async function refreshWeather() {
  const location = elements.locationInput.value.trim();
  const query = location ? `?location=${encodeURIComponent(location)}` : "";
  const response = await fetch(`/api/weather${query}`);
  const data = await response.json();
  if (!response.ok) {
    addMessage("system", data.error || "Could not refresh the weather.");
    return;
  }

  appState.memory = data.memory;
  refreshMemoryViews();
  addMessage("system", `Weather refreshed for ${data.weather.location}.`);
}

async function refreshNews() {
  const location = elements.locationInput.value.trim();
  const topic = location ? `${location} headlines` : "top headlines";
  const query = `?topic=${encodeURIComponent(topic)}`;
  const response = await fetch(`/api/news${query}`);
  const data = await response.json();
  if (!response.ok) {
    addMessage("system", data.error || "Could not refresh the news.");
    return;
  }

  appState.memory = data.memory;
  refreshMemoryViews();
  addMessage("system", `News refreshed for ${data.news.topic}.`);
}

async function addTask(event) {
  event.preventDefault();

  const response = await fetch("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: elements.taskTitleInput.value.trim(),
      priority: elements.taskPriorityInput.value,
      dueDate: elements.taskDueDateInput.value.trim(),
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    addMessage("system", data.error || "Could not add the task.");
    return;
  }

  elements.taskTitleInput.value = "";
  elements.taskDueDateInput.value = "";
  appState.memory = data.memory;
  refreshMemoryViews();
}

async function completeTask(taskRef) {
  const response = await fetch("/api/tasks/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ taskRef }),
  });
  const data = await response.json();
  if (!response.ok) {
    addMessage("system", data.error || "Could not complete the task.");
    return;
  }

  appState.memory = data.memory;
  refreshMemoryViews();
}

async function deleteNote(noteId) {
  if (!noteId) return;
  try {
    const response = await fetch(`/api/notes/${noteId}`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) {
      addMessage("system", data.error || "Could not delete the note.");
      return;
    }
    appState.memory = data.memory;
    refreshMemoryViews();
  } catch (err) {
    addMessage("system", `Failed to delete note: ${err.message}`);
  }
}

async function addNoteManual(event) {
  event.preventDefault();
  const text = elements.noteTextInput.value.trim();
  const category = elements.noteCategoryInput.value.trim() || "note";
  if (!text) return;

  try {
    const response = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, category }),
    });
    const data = await response.json();
    if (!response.ok) {
      addMessage("system", data.error || "Could not save the note.");
      return;
    }
    elements.noteTextInput.value = "";
    elements.noteCategoryInput.value = "";
    appState.memory = data.memory;
    refreshMemoryViews();
  } catch (err) {
    addMessage("system", `Failed to save note: ${err.message}`);
  }
}

async function saveMessageAsNote(bodyEl, messageEl) {
  // Use selected text within the message if any, otherwise full text content
  const selection = window.getSelection();
  let noteText = "";

  if (selection && selection.toString().trim() && messageEl.contains(selection.anchorNode)) {
    noteText = selection.toString().trim();
  } else {
    noteText = bodyEl.innerText.trim();
  }

  if (!noteText) {
    addMessage("system", "Nothing to save - the message is empty.");
    return;
  }

  // Truncate very long messages to a reasonable note size
  if (noteText.length > 500) {
    noteText = noteText.substring(0, 500) + "...";
  }

  try {
    const response = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: noteText, category: "saved" }),
    });
    const data = await response.json();
    if (!response.ok) {
      addMessage("system", data.error || "Could not save note.");
      return;
    }
    appState.memory = data.memory;
    refreshMemoryViews();

    // Visual feedback on the button
    const btn = messageEl.querySelector(".message-action-btn");
    if (btn) {
      const original = btn.innerHTML;
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg><span>Saved!</span>';
      btn.classList.add("saved");
      setTimeout(() => {
        btn.innerHTML = original;
        btn.classList.remove("saved");
      }, 2000);
    }
  } catch (err) {
    addMessage("system", `Failed to save note: ${err.message}`);
  }
}

// ---------- File Attachment ----------

async function handleFileAttach() {
  const files = elements.fileAttachInput.files;
  if (!files || files.length === 0) return;

  // Auto-create session if none exists
  if (!appState.activeSessionId) {
    try {
      const sessionRes = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "File attachment chat" }),
      });
      const sessionData = await sessionRes.json();
      if (sessionRes.ok && sessionData.session) {
        appState.activeSessionId = sessionData.session.session_id;
        await refreshSessions();
      }
    } catch (err) {
      addMessage("system", `Failed to create session: ${err.message}`);
      elements.fileAttachInput.value = "";
      return;
    }
  }

  for (const file of files) {
    const allowedExts = [".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".json"];
    const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
    if (!allowedExts.includes(ext)) {
      addMessage("system", `Unsupported file type: ${ext}. Allowed: ${allowedExts.join(", ")}`);
      continue;
    }

    if (file.size > 20 * 1024 * 1024) {
      addMessage("system", `File too large: ${file.name}. Maximum 20 MB.`);
      continue;
    }

    addMessage("system", `Uploading ${file.name}...`);

    try {
      const base64Data = await fileToBase64(file);
      const response = await fetch(`/api/sessions/${appState.activeSessionId}/attachments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, data: base64Data }),
      });
      const data = await response.json();
      if (!response.ok) {
        addMessage("system", data.error || `Failed to upload ${file.name}.`);
        continue;
      }

      const chunks = data.attachment?.chunk_count ?? "?";
      const parseErr = data.attachment?.parse_error;
      if (parseErr) {
        addMessage("system", `Attached ${file.name} but could not parse for search: ${parseErr}`);
      } else {
        addMessage("system", `Attached ${file.name} (${chunks} chunks indexed). You can now ask questions about it.`);
      }
      // Update attach button visual
      elements.attachFilesBtn.classList.add("active");
    } catch (err) {
      addMessage("system", `Upload error for ${file.name}: ${err.message}`);
    }
  }

  // Reset input so the same file can be re-selected
  elements.fileAttachInput.value = "";
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      // result is "data:...;base64,XXXX" -- we only want the base64 part
      const result = reader.result;
      const base64 = result.substring(result.indexOf(",") + 1);
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// ---------- Screen Sharing ----------

async function startScreenShare() {
  try {
    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: 2 },
      audio: false,
    });

    appState.screenStream = stream;
    elements.screenVideo.srcObject = stream;
    await elements.screenVideo.play();
    captureScreenFrame();

    if (appState.captureIntervalId) {
      clearInterval(appState.captureIntervalId);
    }
    appState.captureIntervalId = window.setInterval(captureScreenFrame, 2500);

    const [track] = stream.getVideoTracks();
    if (track) {
      track.addEventListener("ended", stopScreenShare);
    }
    addMessage("system", "Screen sharing is active. Orbit can now use the latest captured frame when you send a message.");
  } catch (error) {
    addMessage("system", `Screen sharing was not started: ${error.message}`);
  }
}

function stopScreenShare() {
  if (appState.screenStream) {
    appState.screenStream.getTracks().forEach((track) => track.stop());
  }
  appState.screenStream = null;
  appState.latestScreenImage = null;
  elements.screenVideo.srcObject = null;

  if (appState.captureIntervalId) {
    clearInterval(appState.captureIntervalId);
    appState.captureIntervalId = null;
  }

  const context = elements.screenPreview.getContext("2d");
  context.clearRect(0, 0, elements.screenPreview.width, elements.screenPreview.height);
}

function captureScreenFrame() {
  if (!elements.screenVideo.videoWidth || !elements.screenVideo.videoHeight) return;

  const context = elements.screenPreview.getContext("2d");
  const maxWidth = 1280;
  const scale = Math.min(1, maxWidth / elements.screenVideo.videoWidth);
  const width = Math.round(elements.screenVideo.videoWidth * scale);
  const height = Math.round(elements.screenVideo.videoHeight * scale);

  elements.screenPreview.width = width;
  elements.screenPreview.height = height;
  context.drawImage(elements.screenVideo, 0, 0, width, height);
  appState.latestScreenImage = elements.screenPreview.toDataURL("image/jpeg", 0.82);
}

// ---------- Composer State ----------

function getThinkingStatus() {
  if (appState.webSearchActive) return { text: "Searching Online...", copy: "Orbit is searching the web." };
  if (appState.offlineModeActive) return { text: "Searching Offline...", copy: "Orbit is searching local documents." };
  return { text: "Thinking...", copy: "Orbit is processing your request." };
}

function setComposerState(isBusy) {
  elements.sendButton.disabled = isBusy;
  elements.messageInput.disabled = isBusy;
  elements.quickActions.forEach((button) => (button.disabled = isBusy));
  elements.practiceButtons.forEach((button) => (button.disabled = isBusy));
}

// ---------- Utility Functions ----------

function getSelectedLanguageLabel(value) {
  const selected = VOICE_LANGUAGE_OPTIONS.find((option) => option.value === value);
  return selected ? selected.label : "Browser default";
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return escapeHtml(value);
  return String(Math.round(numeric * 10) / 10);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatTimestamp(date) {
  const d = date instanceof Date ? date : new Date(date);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function formatLinks(container) {
  if (!container) return;
  const links = container.querySelectorAll("a");
  links.forEach((link) => {
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener noreferrer");
  });
}
