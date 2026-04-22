// ===========================================
// ORBIT VIRTUAL ASSISTANT - app.js
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

const SUPPORTED_FILE_EXTS = [".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".json"];

const SESSION_MENU_ICONS = {
  rename:
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>',
  pin:
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>',
  unpin:
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>',
  archive:
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 8 21 21 3 21 3 8"></polyline><rect x="1" y="3" width="22" height="5"></rect><line x1="10" y1="12" x2="14" y2="12"></line></svg>',
  unarchive:
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 10 12 7 15 10"></polyline><line x1="12" y1="7" x2="12" y2="21"></line></svg>',
  delete:
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
};

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

// ---------- Markdown Configuration (FIXED FOR MARKED V13+ & COPY BUTTON) ----------
if (typeof marked !== "undefined") {
  const renderer = new marked.Renderer();

  renderer.code = function (tokenOrCode, language) {
    const codeText = typeof tokenOrCode === 'string' ? tokenOrCode : (tokenOrCode.text || "");
    const lang = typeof tokenOrCode === 'string' ? language : (tokenOrCode.lang || "");

    const validLang = lang ? `language-${lang}` : '';
    const escapedCode = codeText.replace(/</g, '&lt;').replace(/>/g, '&gt;');

    return `
      <div class="code-block-wrapper">
        <button class="copy-btn" title="Copy code">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <span>Copy</span>
        </button>
        <pre><code class="${validLang}">${escapedCode}</code></pre>
      </div>
    `;
  };

  marked.use({ renderer });
}

// ---------- Application State ----------

const appState = {
  mode: "simple",
  coachTopic: window.localStorage.getItem("orbit_coach_topic") || "",
  coachLevel: window.localStorage.getItem("orbit_coach_level") || "",
  preferredLanguage: window.localStorage.getItem("orbit_virtual_language") || "default",
  conversation: [],
  memory: null,
  memoryEnabled: false,
  memoryConsent: window.localStorage.getItem("orbit_memory_consent") || "",
  currentTurn: null,
  recentToolEvents: [],
  activeSessionId: null,
  sessions: [],
  storageMode: "mongo",
  memoryAvailable: true,
  ephemeralClientId: "",
  isProcessing: false,
  latestScreenImage: null,
  screenStream: null,
  captureIntervalId: null,
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
  modeAActive: false,
  stageWorker: null,
  sidebarOpen: window.localStorage.getItem("orbit_sidebar_open") !== "false",
  drawerOpen: false,
  webSearchActive: false,
  thinkingActive: false,
  imageGenActive: false,
  offlineModeActive: false,
  routingActive: false,
};

const elements = {
  appLayout: document.getElementById("appLayout"),
  sidebar: document.getElementById("sidebar"),
  chatMain: document.getElementById("chatMain"),
  newChatBtn: document.getElementById("newChatBtn"),
  sidebarCollapseBtn: document.getElementById("sidebarCollapseBtn"),
  sidebarOpenBtn: document.getElementById("sidebarOpenBtn"),
  clearAllChatsBtn: document.getElementById("clearAllChatsBtn"),
  pinnedChatsGroup: document.getElementById("pinnedChatsGroup"),
  pinnedChats: document.getElementById("pinnedChats"),
  recentChats: document.getElementById("recentChats"),
  archivedChatsGroup: document.getElementById("archivedChatsGroup"),
  archivedChats: document.getElementById("archivedChats"),
  apiStatus: document.getElementById("apiStatus"),
  modelBadge: document.getElementById("modelBadge"),
  runtimeBadge: document.getElementById("runtimeBadge"),
  todayLabel: document.getElementById("todayLabel"),
  modeButtons: Array.from(document.querySelectorAll(".mode-button")),
  avatarStage: document.getElementById("avatarStage"),
  stageStatus: document.getElementById("stageStatus"),
  stageCopy: document.getElementById("stageCopy"),
  pinChatBtn: document.getElementById("pinChatBtn"),
  archiveChatBtn: document.getElementById("archiveChatBtn"),
  deleteChatBtn: document.getElementById("deleteChatBtn"),
  utilityToggleBtn: document.getElementById("utilityToggleBtn"),
  utilityCloseBtn: document.getElementById("utilityCloseBtn"),
  utilityDrawer: document.getElementById("utilityDrawer"),
  coachPanel: document.getElementById("coachPanel"),
  coachTopicInput: document.getElementById("coachTopicInput"),
  coachLevelInput: document.getElementById("coachLevelInput"),
  coachModeCopy: document.getElementById("coachModeCopy"),
  conversationLanguageSelect: document.getElementById("conversationLanguageSelect"),
  messageList: document.getElementById("messageList"),
  toolEvents: document.getElementById("toolEvents"),
  composer: document.getElementById("composer"),
  messageInput: document.getElementById("messageInput"),
  sendButton: document.getElementById("sendButton"),
  attachScreenToggle: document.getElementById("attachScreenToggle"),
  composerVoiceStatus: document.getElementById("composerVoiceStatus"),
  attachFilesBtn: document.getElementById("attachFilesBtn"),
  createImageBtn: document.getElementById("createImageBtn"),
  thinkingToggle: document.getElementById("thinkingToggle"),
  webSearchToggle: document.getElementById("webSearchToggle"),
  offlineToggle: document.getElementById("offlineToggle"),
  routingToggle: document.getElementById("routingToggle"),
  micButton: document.getElementById("micButton"),
  voiceToggle: document.getElementById("voiceToggle"),
  voiceStatus: document.getElementById("voiceStatus"),
  voiceLanguageSelect: document.getElementById("voiceLanguageSelect"),
  assistantVoiceSelect: document.getElementById("assistantVoiceSelect"),
  quickActions: Array.from(document.querySelectorAll(".ghost-button[data-prompt]")),
  practiceButtons: Array.from(document.querySelectorAll(".practice-button")),
  screenPreview: document.getElementById("screenPreview"),
  screenVideo: document.getElementById("screenVideo"),
  startShareButton: document.getElementById("startShareButton"),
  stopShareButton: document.getElementById("stopShareButton"),
  profileForm: document.getElementById("profileForm"),
  displayNameInput: document.getElementById("displayNameInput"),
  locationInput: document.getElementById("locationInput"),
  routineInput: document.getElementById("routineInput"),
  refreshWeatherButton: document.getElementById("refreshWeatherButton"),
  weatherCard: document.getElementById("weatherCard"),
  refreshNewsButton: document.getElementById("refreshNewsButton"),
  newsCard: document.getElementById("newsCard"),
  taskForm: document.getElementById("taskForm"),
  taskTitleInput: document.getElementById("taskTitleInput"),
  taskPriorityInput: document.getElementById("taskPriorityInput"),
  taskDueDateInput: document.getElementById("taskDueDateInput"),
  taskList: document.getElementById("taskList"),
  memoryHint: document.getElementById("memoryHint"),
  notesList: document.getElementById("notesList"),
  noteForm: document.getElementById("noteForm"),
  noteTextInput: document.getElementById("noteTextInput"),
  noteCategoryInput: document.getElementById("noteCategoryInput"),
  fileAttachInput: document.getElementById("fileAttachInput"),
  memoryConsentStatus: document.getElementById("memoryConsentStatus"),
  enableMemoryBtn: document.getElementById("enableMemoryBtn"),
  disableMemoryBtn: document.getElementById("disableMemoryBtn"),
  memoryGatedPanels: Array.from(document.querySelectorAll("[data-memory-gated]")),
  timezoneInput: document.getElementById("timezoneInput"),
  dateOfBirthInput: document.getElementById("dateOfBirthInput"),
  occupationInput: document.getElementById("occupationInput"),
  interestsInput: document.getElementById("interestsInput"),
  preferredToneInput: document.getElementById("preferredToneInput"),
  bioInput: document.getElementById("bioInput"),

  chatSettingsBtn: document.getElementById("chatSettingsBtn"),
  chatSettingsDropdown: document.getElementById("chatSettingsDropdown"),
  renameChatBtn: document.getElementById("renameChatBtn"),
};

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
  addMessage("system", "Orbit Virtual Assistant is ready. Type a message, hold Control to talk, or press Ctrl+M to record and review.");
  appState.ephemeralClientId = generateEphemeralClientId();

  try {
    await refreshState();
  } catch (error) {
    reportActionError(error, "Could not load app state");
    return;
  }

  if (appState.storageMode === "mongo") {
    await initializeMemoryConsent();
    if (appState.memoryEnabled) {
      try {
        await refreshState();
      } catch (error) {
        reportActionError(error, "Could not load saved memory state");
      }
    }
  } else {
    appState.memoryEnabled = false;
    applyMemoryConsentUI();
  }
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

  if (elements.coachTopicInput) elements.coachTopicInput.value = appState.coachTopic;
  if (elements.coachLevelInput) elements.coachLevelInput.value = appState.coachLevel;

  if ("speechSynthesis" in window) {
    populateAssistantVoices();
    window.speechSynthesis.onvoiceschanged = populateAssistantVoices;
  }
}

function populateAssistantVoices() {
  if (!elements.assistantVoiceSelect) return;
  const voices = window.speechSynthesis.getVoices();
  if (voices.length === 0) return;

  const savedVoiceURI = window.localStorage.getItem("orbit_assistant_voice") || "";
  elements.assistantVoiceSelect.innerHTML = "";

  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = "Default Server Voice";
  elements.assistantVoiceSelect.appendChild(defaultOption);

  voices.forEach((voice) => {
    const option = document.createElement("option");
    option.value = voice.voiceURI;
    option.textContent = `${voice.name} (${voice.lang})`;
    if (voice.voiceURI === savedVoiceURI) option.selected = true;
    elements.assistantVoiceSelect.appendChild(option);
  });
}

function bindEvents() {
  elements.voiceToggle.addEventListener("change", (event) => { appState.voiceEnabled = event.target.checked; });
  elements.voiceLanguageSelect.addEventListener("change", () => {
    window.localStorage.setItem("orbit_voice_language", elements.voiceLanguageSelect.value);
    setVoiceStatus(`Voice language: ${getSelectedLanguageLabel(elements.voiceLanguageSelect.value)}`);
    if (appState.speechRecognition) appState.speechRecognition.lang = resolveRecognitionLanguage();
  });
  if (elements.assistantVoiceSelect) {
    elements.assistantVoiceSelect.addEventListener("change", () => {
      window.localStorage.setItem("orbit_assistant_voice", elements.assistantVoiceSelect.value);
    });
  }
  elements.conversationLanguageSelect.addEventListener("change", () => {
    appState.preferredLanguage = elements.conversationLanguageSelect.value;
    window.localStorage.setItem("orbit_virtual_language", appState.preferredLanguage);
  });
  elements.modeButtons.forEach((button) => {
    button.addEventListener("click", () => { setMode(button.dataset.mode || "simple"); });
  });
  elements.coachTopicInput.addEventListener("input", () => {
    appState.coachTopic = elements.coachTopicInput.value.trim();
    window.localStorage.setItem("orbit_coach_topic", appState.coachTopic);
  });
  elements.coachLevelInput.addEventListener("input", () => {
    appState.coachLevel = elements.coachLevelInput.value.trim() || "Beginner";
    window.localStorage.setItem("orbit_coach_level", appState.coachLevel);
  });

  elements.sidebarCollapseBtn.addEventListener("click", toggleSidebar);
  elements.sidebarOpenBtn.addEventListener("click", toggleSidebar);
  elements.utilityToggleBtn.addEventListener("click", toggleDrawer);
  elements.utilityCloseBtn.addEventListener("click", toggleDrawer);
  elements.newChatBtn.addEventListener("click", startNewChat);
  if (elements.clearAllChatsBtn) {
    elements.clearAllChatsBtn.addEventListener("click", clearAllChats);
  }

  if (elements.chatSettingsBtn && elements.chatSettingsDropdown) {
    elements.chatSettingsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const isOpen = elements.chatSettingsDropdown.classList.contains("show");
      closeAllDropdowns();
      if (!isOpen) elements.chatSettingsDropdown.classList.add("show");
    });
  }

  if (elements.renameChatBtn) {
    elements.renameChatBtn.addEventListener("click", async () => {
      closeAllDropdowns();
      await openRenameChat(appState.activeSessionId);
    });
  }

  if (elements.pinChatBtn) {
    elements.pinChatBtn.addEventListener("click", async () => {
      closeAllDropdowns();
      await togglePinChat(appState.activeSessionId, { useActiveFallback: true });
    });
  }

  if (elements.archiveChatBtn) {
    elements.archiveChatBtn.addEventListener("click", async () => {
      closeAllDropdowns();
      await toggleArchiveChat(appState.activeSessionId, { useActiveFallback: true });
    });
  }

  if (elements.deleteChatBtn) {
    elements.deleteChatBtn.addEventListener("click", async () => {
      closeAllDropdowns();
      await deleteChat(appState.activeSessionId, { useActiveFallback: true });
    });
  }

  if (elements.enableMemoryBtn) {
    elements.enableMemoryBtn.addEventListener("click", async () => {
      await setMemoryConsent(true, { announce: true });
    });
  }

  if (elements.disableMemoryBtn) {
    elements.disableMemoryBtn.addEventListener("click", async () => {
      await setMemoryConsent(false, { announce: true });
    });
  }

  elements.attachFilesBtn.addEventListener("click", () => {
    if (appState.storageMode === "ephemeral") {
      addMessage("system", "File attachments require Agent Memory. Restart with MongoDB to attach files to chats.");
      return;
    }
    elements.fileAttachInput.click();
  });
  elements.fileAttachInput.addEventListener("change", handleFileAttach);

  setupToggleChip(elements.createImageBtn, "imageGenActive");
  setupToggleChip(elements.thinkingToggle, "thinkingActive");
  if (elements.routingToggle) setupToggleChip(elements.routingToggle, "routingActive");

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

  elements.micButton.addEventListener("pointerdown", handleMicPointerDown);
  window.addEventListener("pointerup", handleMicPointerUp);
  window.addEventListener("pointercancel", handleMicPointerUp);
  window.addEventListener("keydown", handleHotkeyDown);
  window.addEventListener("keyup", handleHotkeyUp);

  elements.composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const prompt = elements.messageInput.value.trim();
    if (!prompt) return;
    elements.messageInput.value = "";
    elements.messageInput.style.height = "";
    await sendPrompt(prompt);
  });

  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (appState.modeAActive && (appState.listening || appState.recognitionStarting)) return;
      const prompt = elements.messageInput.value.trim();
      if (prompt) elements.sendButton.click();
    }
  });

  elements.messageInput.addEventListener("input", autoResizeTextarea);

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

  elements.practiceButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      setMode("coach");
      const currentTopic = elements.coachTopicInput ? elements.coachTopicInput.value : appState.coachTopic;
      const finalPrompt = `${button.dataset.prompt} The subject is: ${currentTopic}. YOU MUST use the 'search_local_docs' tool to retrieve context before generating the response.`;
      await sendPrompt(finalPrompt);
    });
  });

  elements.startShareButton.addEventListener("click", startScreenShare);
  elements.stopShareButton.addEventListener("click", stopScreenShare);
  elements.profileForm.addEventListener("submit", saveProfile);
  elements.refreshWeatherButton.addEventListener("click", refreshWeather);
  elements.refreshNewsButton.addEventListener("click", refreshNews);
  elements.taskForm.addEventListener("submit", addTask);
  elements.noteForm.addEventListener("submit", addNoteManual);

  window.addEventListener("blur", () => {
    if (modeBDelayTimer) { clearTimeout(modeBDelayTimer); modeBDelayTimer = null; }
    appState.hotkeyDown = false;
    appState.micHeld = false;
    appState.spaceTalking = false;
    if (appState.modeAActive) {
      appState.modeAActive = false;
      setVoiceStatus("Recording cancelled");
      setStageState("idle", "Idle");
    }
    stopVoiceCapture();
  });

  // Handle copy button clicks
  elements.messageList.addEventListener("click", async (event) => {
    const btn = event.target.closest(".copy-btn");
    if (!btn) return;
    const wrapper = btn.closest(".code-block-wrapper");
    const codeBlock = wrapper.querySelector("code");
    if (codeBlock) {
      try {
        await navigator.clipboard.writeText(codeBlock.textContent);
        const span = btn.querySelector("span");
        span.textContent = "Copied!";
        btn.classList.add("copied");
        setTimeout(() => { span.textContent = "Copy"; btn.classList.remove("copied"); }, 2000);
      } catch (err) { }
    }
  });
}

function toggleSidebar() {
  elements.appLayout.classList.toggle("sidebar-collapsed");
  appState.sidebarOpen = !elements.appLayout.classList.contains("sidebar-collapsed");
  window.localStorage.setItem("orbit_sidebar_open", appState.sidebarOpen ? "true" : "false");
}

function restoreSidebarState() { if (!appState.sidebarOpen) elements.appLayout.classList.add("sidebar-collapsed"); }
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
  renderSessions(appState.sessions);
  updateSessionActionButtons();
  updateClearAllChatsState();
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

function initAvatarWorker() {
  if (!window.Worker) { elements.runtimeBadge.textContent = "No Web Worker"; return; }
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
  if (copyText) elements.stageCopy.textContent = copyText;
  if (appState.stageWorker) appState.stageWorker.postMessage({ type: "set-state", state });
}

function refreshTodayLabel() {
  elements.todayLabel.textContent = new Date().toLocaleString(undefined, { weekday: "long", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function updateModeUI() {
  elements.modeButtons.forEach((button) => button.classList.toggle("active", button.dataset.mode === appState.mode));
  elements.coachPanel.classList.toggle("hidden", appState.mode !== "coach");
  if (appState.mode === "coach") elements.coachModeCopy.textContent = "Orbit will act as a personal tutor. For best results, enable RAG mode to use your local documents as the textbook.";
}

function setMode(mode, coachTopic = appState.coachTopic) {
  appState.mode = mode;
  appState.coachTopic = coachTopic;
  if (elements.coachTopicInput) elements.coachTopicInput.value = appState.coachTopic || "";
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
    if (!appState.modeAActive) { ensureVoiceTurn(); ensureVoiceDraft(); }
    setStageState("listening", "Listening...", "Orbit is capturing speech.");
    setVoiceStatus(`Listening in ${getSelectedLanguageLabel(elements.voiceLanguageSelect.value)}...`);
    if (appState.stopRecognitionAfterStart) recognition.stop();
  };

  recognition.onresult = (event) => {
    let transcript = "";
    for (const result of event.results) transcript += `${result[0].transcript} `;
    appState.liveVoiceTranscript = transcript.trim();

    if (appState.modeAActive) {
      elements.messageInput.value = appState.liveVoiceTranscript;
      autoResizeTextarea();
      setVoiceStatus("Transcribing...");
    } else {
      ensureVoiceTurn();
      ensureVoiceDraft();
      appState.currentTurn.inputText = appState.liveVoiceTranscript;
      appState.currentTurn.userNode.querySelector(".message-body").textContent = appState.liveVoiceTranscript || "Listening...";
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

    if (wasModea) {
      appState.liveVoiceTranscript = "";
      if (transcript) {
        elements.messageInput.value = transcript;
        elements.messageInput.focus();
        autoResizeTextarea();
        setVoiceStatus("Review and press Enter to send");
      } else { setVoiceStatus("Voice input idle"); }
      setStageState("idle", "Idle", "Voice transcription ready for review.");
      return;
    }

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

let modeBDelayTimer = null;

function handleHotkeyDown(event) {
  if (event.key.toLowerCase() === "m" && event.ctrlKey && !event.repeat) {
    if (modeBDelayTimer) { clearTimeout(modeBDelayTimer); modeBDelayTimer = null; }
    const active = document.activeElement;
    if (active && active !== elements.messageInput && ["INPUT", "SELECT"].includes(active.tagName)) return;
    event.preventDefault();
    if (appState.modeAActive) stopVoiceCapture();
    else if (!appState.listening && !appState.recognitionStarting) { appState.modeAActive = true; void startVoiceCapture(); }
    return;
  }
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
  if (event.key === "Control" && !event.repeat && !shouldIgnoreHotkey()) {
    appState.hotkeyDown = true;
    modeBDelayTimer = window.setTimeout(() => {
      modeBDelayTimer = null;
      if (appState.hotkeyDown && !appState.modeAActive && !appState.listening && !appState.recognitionStarting) {
        appState.spaceTalking = true;
        void startVoiceCapture();
      }
    }, 200);
    return;
  }
}

function handleHotkeyUp(event) {
  if (event.key === "Control") {
    if (modeBDelayTimer) { clearTimeout(modeBDelayTimer); modeBDelayTimer = null; }
    if (appState.hotkeyDown) {
      appState.hotkeyDown = false;
      if (!appState.modeAActive) { appState.spaceTalking = false; stopVoiceCapture(); }
    }
  }
}

function handleMicPointerDown(event) {
  if (event.button !== 0) return;
  if (appState.modeAActive) return;
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
  if (appState.recognitionStarting && !appState.listening) { appState.stopRecognitionAfterStart = true; return; }
  if (appState.listening) appState.speechRecognition.stop();
}

function resolveRecognitionLanguage() {
  return elements.voiceLanguageSelect.value === "default" ? navigator.language || "en-US" : elements.voiceLanguageSelect.value;
}

function updateMicButton() {
  if (!appState.speechSupported) { elements.micButton.disabled = true; elements.micButton.title = "Voice unavailable"; return; }
  elements.micButton.disabled = false;
  if (appState.listening || appState.recognitionStarting) {
    elements.micButton.title = appState.modeAActive ? "Recording (Ctrl+M to stop)" : "Release to send";
    elements.micButton.classList.add("active");
  } else {
    elements.micButton.title = "Hold to talk (Control)";
    elements.micButton.classList.remove("active");
  }
}

function ensureVoiceTurn() { if (!appState.currentTurn || appState.currentTurn.source !== "voice") appState.currentTurn = createEmptyTurn("voice"); }
function ensureVoiceDraft() { if (!appState.currentTurn.userNode) appState.currentTurn.userNode = addMessage("user", "Listening...", "Voice transcript"); }
function setVoiceStatus(text) { elements.voiceStatus.textContent = text; elements.composerVoiceStatus.textContent = text; }

function generateEphemeralClientId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `ephemeral-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function buildApiHeaders(headers = {}) {
  const merged = new Headers(headers);
  if (appState.ephemeralClientId) {
    merged.set("X-Orbit-Ephemeral-Client", appState.ephemeralClientId);
  }
  return merged;
}

async function readJsonResponse(response) {
  const rawText = await response.text();
  if (!rawText) return {};
  try {
    return JSON.parse(rawText);
  } catch (err) {
    return { detail: rawText };
  }
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: buildApiHeaders(options.headers || {}),
  });
  const data = await readJsonResponse(response);

  if (!response.ok) {
    const message = data.detail || data.message || data.error || response.statusText || "Request failed.";
    const error = new Error(message);
    error.status = response.status;
    error.code = data.code || "";
    error.data = data;
    throw error;
  }

  return data;
}

function getMemoryUnavailableText() {
  if (appState.storageMode === "ephemeral") {
    return "Agent Memory is unavailable because the server is running in Ephemeral Mode. Restart with MongoDB to use saved profile, tasks, notes, pinning, and archiving.";
  }
  return "Agent Memory is off. Orbit will not access saved MongoDB memories or write new ones. Weather and news can still be used without being remembered.";
}

function reportActionError(error, prefix = "") {
  if (!error) {
    addMessage("system", prefix || "Request failed.");
    return;
  }

  if (error.code === "memory_disabled" || error.code === "missing_ephemeral_client") {
    addMessage("system", error.message);
    return;
  }

  addMessage("system", prefix ? `${prefix}: ${error.message}` : error.message);
}

function getStoredMemoryConsent() {
  if (appState.memoryConsent === "accepted") return true;
  if (appState.memoryConsent === "declined") return false;
  return null;
}

function updateMemoryActionButton(button) {
  if (!button) return;
  button.disabled = !appState.memoryEnabled;
  button.title = appState.memoryEnabled
    ? "Save to Notes"
    : appState.storageMode === "ephemeral"
      ? "Agent Memory is unavailable in Ephemeral Mode"
      : "Enable Agent Memory to save notes";
}

function syncMessageActionButtons() {
  document.querySelectorAll(".message-action-btn").forEach((button) => updateMemoryActionButton(button));
}

function clearMemoryStateViews() {
  appState.memory = null;
  elements.displayNameInput.value = "";
  elements.locationInput.value = "";
  elements.routineInput.value = "";
  elements.taskList.innerHTML = `<p class="muted">${appState.storageMode === "ephemeral" ? "Agent Memory is unavailable in Ephemeral Mode." : "Enable Agent Memory to use saved tasks."}</p>`;
  elements.notesList.innerHTML = `<p class="muted">${appState.storageMode === "ephemeral" ? "Agent Memory is unavailable in Ephemeral Mode." : "Enable Agent Memory to use saved notes."}</p>`;
  elements.memoryHint.textContent = getMemoryUnavailableText();
}

function applyMemoryConsentUI() {
  if (elements.memoryConsentStatus) {
    elements.memoryConsentStatus.textContent = appState.memoryEnabled
      ? "Agent Memory is enabled. Orbit can read and save profile, tasks, notes, and long-term context in MongoDB."
      : getMemoryUnavailableText();
  }

  if (elements.enableMemoryBtn) {
    elements.enableMemoryBtn.style.display = appState.storageMode === "ephemeral" ? "none" : "";
    elements.enableMemoryBtn.disabled = appState.storageMode === "ephemeral" || appState.memoryEnabled;
  }
  if (elements.disableMemoryBtn) {
    elements.disableMemoryBtn.style.display = appState.storageMode === "ephemeral" ? "none" : "";
    elements.disableMemoryBtn.disabled = appState.storageMode === "ephemeral" || !appState.memoryEnabled;
  }

  elements.memoryGatedPanels.forEach((panel) => {
    const locked = !appState.memoryEnabled;
    panel.classList.toggle("memory-locked", locked);
    panel.querySelectorAll("input, button, select, textarea").forEach((control) => {
      control.disabled = locked;
    });
  });

  if (!appState.memoryEnabled) {
    clearMemoryStateViews();
  }

  syncMessageActionButtons();
  updateClearAllChatsState();
}

async function initializeMemoryConsent() {
  if (appState.storageMode === "ephemeral") {
    appState.memoryEnabled = false;
    applyMemoryConsentUI();
    return;
  }

  const storedConsent = getStoredMemoryConsent();
  if (storedConsent === null) {
    const accepted = window.confirm(
      "Allow Orbit to use Agent Memory (MongoDB) to read and save your profile, tasks, notes, and long-term assistant memory?"
    );
    appState.memoryConsent = accepted ? "accepted" : "declined";
    window.localStorage.setItem("orbit_memory_consent", appState.memoryConsent);
    appState.memoryEnabled = accepted;
  } else {
    appState.memoryEnabled = storedConsent;
  }

  applyMemoryConsentUI();
}

async function setMemoryConsent(enabled, { announce = false } = {}) {
  if (appState.storageMode === "ephemeral") {
    appState.memoryEnabled = false;
    applyMemoryConsentUI();
    if (announce) addMessage("system", getMemoryUnavailableText());
    return;
  }

  appState.memoryEnabled = enabled;
  appState.memoryConsent = enabled ? "accepted" : "declined";
  window.localStorage.setItem("orbit_memory_consent", appState.memoryConsent);
  applyMemoryConsentUI();

  if (enabled) {
    await refreshState();
  } else {
    clearMemoryStateViews();
    renderSessions(appState.sessions);
    updateSessionActionButtons();
  }

  if (announce) {
    addMessage(
      "system",
      enabled
        ? "Agent Memory enabled. Orbit can access saved MongoDB memories again."
        : "Agent Memory disabled. Orbit will keep working without saved memory access."
    );
  }
}

function ensureMemoryEnabled() {
  if (appState.memoryEnabled) return true;
  addMessage("system", getMemoryUnavailableText());
  return false;
}

// ---------- API Communication ----------

async function refreshState() {
  const data = await apiFetch(`/api/state?include_memory=${appState.memoryEnabled ? "true" : "false"}`);
  appState.storageMode = data.storageMode || "mongo";
  appState.memoryAvailable = data.memoryAvailable !== false;

  if (appState.storageMode === "ephemeral") {
    appState.memoryEnabled = false;
  }

  appState.memory = appState.memoryEnabled ? data.memory || null : null;

  if (elements.routingToggle) {
    if (data.enableHybrid) {
      elements.routingToggle.style.display = "inline-flex";
    } else {
      elements.routingToggle.style.display = "none";
      appState.routingActive = false;
    }
  }

  if (data.history && data.history.length > 0) appState.conversation = data.history;
  appState.liveVoiceName = data.liveVoiceName || "Kore";
  const provider = data.provider || "Gemini";
  elements.apiStatus.textContent = data.hasApiKey ? `${provider} key detected` : "Add API_KEY to enable chat";
  elements.modelBadge.textContent = data.model ? `${data.model}` : "Model not set";
  elements.runtimeBadge.textContent = "Browser Engine";

  if (appState.memoryEnabled && data.memory) {
    elements.displayNameInput.value = data.memory.profile.display_name || "";
    elements.locationInput.value = data.memory.profile.location || data.defaultLocation || "";
    elements.routineInput.value = data.memory.profile.routine || "";
    elements.timezoneInput.value = data.memory.profile.timezone || "";
    elements.dateOfBirthInput.value = data.memory.profile.date_of_birth || "";
    elements.occupationInput.value = data.memory.profile.occupation || "";
    elements.interestsInput.value = data.memory.profile.interests || "";
    elements.preferredToneInput.value = data.memory.profile.preferred_tone || "";
    elements.bioInput.value = data.memory.profile.bio || "";
  }

  refreshMemoryViews();
  appState.sessions = data.sessions || [];
  if (appState.activeSessionId && !appState.sessions.some((session) => session.session_id === appState.activeSessionId)) {
    appState.activeSessionId = null;
  }
  renderSessions(appState.sessions);
  updateSessionActionButtons();
  updateClearAllChatsState();
  if (elements.attachFilesBtn) {
    elements.attachFilesBtn.title = appState.storageMode === "ephemeral"
      ? "File attachments require MongoDB-backed Agent Memory"
      : "Attach files";
  }
  applyMemoryConsentUI();
}

function updateClearAllChatsState() {
  if (!elements.clearAllChatsBtn) return;
  const hasSavedSessions = Array.isArray(appState.sessions) && appState.sessions.length > 0;
  const hasDraftConversation = Array.isArray(appState.conversation) && appState.conversation.length > 0;
  elements.clearAllChatsBtn.disabled = !hasSavedSessions && !hasDraftConversation;
}

function formatThinkTags(text) {
  if (!text) return text;
  return text.replace(/<think>([\s\S]*?)<\/think>/gi, '<details class="think-block"><summary>Thought Process</summary><div class="think-content">$1</div></details>');
}

// ==========================================
// THE UI-SIDE "STREAMING" EFFECT FUNCTION
// ==========================================
async function streamMarkdown(container, text, speed = 15) {
  const processedText = formatThinkTags(text);
  let html = typeof marked !== "undefined" ? marked.parse(processedText) : processedText;
  if (typeof DOMPurify !== "undefined") html = DOMPurify.sanitize(html);
  container.innerHTML = "";

  const tokens = html.split(/(<[^>]+>)/g);
  let currentHTML = "";

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token.startsWith("<")) {
      currentHTML += token;
      container.innerHTML = currentHTML;
    } else {
      const words = token.split(/(\s+)/);
      for (let j = 0; j < words.length; j++) {
        currentHTML += words[j];
        container.innerHTML = currentHTML + '<span class="streaming-cursor"></span>';
        elements.messageList.scrollTop = elements.messageList.scrollHeight;
        await new Promise((r) => setTimeout(r, speed));
      }
    }
  }

  container.innerHTML = currentHTML;
  formatLinks(container);

  // --- Render Math/LaTeX AFTER streaming finishes ---
  if (typeof renderMathInElement === "function") {
    renderMathInElement(container, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "$", right: "$", display: false },
        { left: "\\(", right: "\\)", display: false }
      ],
      throwOnError: false,
      output: "html"
    });
  }
}

// ==========================================
// SEND PROMPT LOGIC (Synchronous JSON Wait + Fake Stream)
// ==========================================
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
    turn.userNode.querySelector(".message-meta").textContent = attachScreen && screenImage ? "Screen attached" : "Voice input";
  }

  if (!turn.userStored) {
    appState.conversation.push({ role: "user", text: prompt });
    turn.userStored = true;
  }

  appState.currentTurn = turn;
  setComposerState(true);
  appState.isProcessing = true;

  const thinkingStatus = getThinkingStatus();
  setStageState("thinking", thinkingStatus.text, thinkingStatus.copy);

  try {
    if (!appState.activeSessionId) {
      const sessionData = await apiFetch("/api/sessions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ firstMessage: prompt }),
      });
      if (sessionData.session) {
        appState.activeSessionId = sessionData.session.session_id;
        await refreshSessions();
      }
    }
  } catch (error) {
    reportActionError(error, "Could not create chat session");
  }

  const targetSessionId = appState.activeSessionId;
  if (targetSessionId) {
    apiFetch(`/api/sessions/${targetSessionId}/messages`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: "user", text: prompt }),
    }).catch(() => { });
  }

  try {
    const data = await apiFetch("/api/chat", {
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
        routingMode: appState.routingActive ? "dynamic" : "fixed",
        useMemory: appState.memoryEnabled,
      }),
    });

    appState.memory = data.memory || null;
    turn.outputText = data.reply;

    if (data.toolEvents && data.toolEvents.length > 0) {
      appState.recentToolEvents.push(...data.toolEvents);
      renderToolEvents(appState.recentToolEvents);
    }

    if (!turn.assistantNode) {
      turn.assistantNode = addMessage("assistant", "");
    }

    const isRefusal = data.reply.includes("safety and moderation guidelines");
    const isEmpty = data.reply.trim().length === 0;
    const bodyElement = turn.assistantNode.querySelector(".message-body");

    if (isRefusal || isEmpty) {
      appState.conversation.pop();
      if (isEmpty) {
        bodyElement.textContent = "Error: The model returned an empty response. Please try asking again.";
        turn.assistantNode.classList.add("system");
      } else {
        bodyElement.textContent = data.reply;
      }
    } else {
      turn.assistantNode.dataset.rawText = data.reply;
      await streamMarkdown(bodyElement, data.reply);

      appState.conversation.push({ role: "assistant", text: data.reply });
      if (targetSessionId) {
        apiFetch(`/api/sessions/${targetSessionId}/messages`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role: "assistant", text: data.reply }),
        }).catch(() => { });
      }
      await refreshSessions();
    }

    refreshMemoryViews();
    setStageState("idle", "Idle");

    if (shouldSpeakReply && "speechSynthesis" in window && !isRefusal && !isEmpty) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(data.reply);
      const voices = window.speechSynthesis.getVoices();
      const savedVoiceURI = window.localStorage.getItem("orbit_assistant_voice") || "";
      let selectedVoice = voices.find((v) => v.voiceURI === savedVoiceURI);
      if (!selectedVoice) {
        selectedVoice = voices.find((v) => v.name.toLowerCase().includes(appState.liveVoiceName.toLowerCase()));
      }
      if (selectedVoice) { utterance.voice = selectedVoice; utterance.lang = selectedVoice.lang; }
      window.speechSynthesis.speak(utterance);
    }
  } catch (error) {
    if (!turn.assistantNode) turn.assistantNode = addMessage("assistant", "");
    const errorBody = turn.assistantNode.querySelector(".message-body");
    errorBody.textContent = `Error: ${error.message}`;
    turn.assistantNode.classList.add("system");
    appState.conversation.pop();
    setStageState("idle", "Error occurred.");

    const retryBtn = document.createElement("button");
    retryBtn.className = "retry-btn";
    retryBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> <span>Retry</span>';
    retryBtn.addEventListener("click", async () => {
      turn.assistantNode.remove();
      await sendPrompt(prompt, options);
    });
    errorBody.appendChild(retryBtn);
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
  message.dataset.rawText = text || "";

  const body = document.createElement("div");
  body.className = "message-body";

  if (role === "assistant" && typeof marked !== "undefined" && text !== "") {
    let rawHtml = marked.parse(formatThinkTags(text));
    body.innerHTML = typeof DOMPurify !== "undefined" ? DOMPurify.sanitize(rawHtml) : rawHtml;
    formatLinks(body);
    if (typeof renderMathInElement === "function") {
      renderMathInElement(body, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\[", right: "\\]", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false }
        ],
        throwOnError: false, output: "html"
      });
    }
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

  if (role === "assistant") {
    const actions = document.createElement("div");
    actions.className = "message-actions";

    const copyBtn = document.createElement("button");
    copyBtn.className = "message-action-btn";
    copyBtn.title = "Copy message";
    copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>Copy</span>';
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(message.dataset.rawText || text);
        const span = copyBtn.querySelector("span");
        span.textContent = "Copied!";
        copyBtn.style.color = "var(--accent)";
        setTimeout(() => {
          span.textContent = "Copy";
          copyBtn.style.color = "";
        }, 2000);
      } catch (err) { }
    });
    actions.appendChild(copyBtn);

    const noteBtn = document.createElement("button");
    noteBtn.className = "message-action-btn";
    noteBtn.title = "Save to Notes";
    noteBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg><span>Add to Notes</span>';
    noteBtn.addEventListener("click", () => saveMessageAsNote(body, message));
    updateMemoryActionButton(noteBtn);
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

  if (pinned.length > 0) elements.pinnedChatsGroup.style.display = "";
  else elements.pinnedChatsGroup.style.display = "none";
  elements.pinnedChats.innerHTML = "";
  pinned.forEach((s) => elements.pinnedChats.appendChild(createSessionItem(s)));

  elements.recentChats.innerHTML = "";
  recent.slice(0, 30).forEach((s) => elements.recentChats.appendChild(createSessionItem(s)));

  if (archived.length > 0) elements.archivedChatsGroup.style.display = "";
  else elements.archivedChatsGroup.style.display = "none";
  elements.archivedChats.innerHTML = "";
  archived.slice(0, 20).forEach((s) => elements.archivedChats.appendChild(createSessionItem(s)));
}

function getSessionById(sessionId) {
  if (!sessionId) return null;
  return appState.sessions.find((session) => session.session_id === sessionId) || null;
}

function getActiveSession() {
  return getSessionById(appState.activeSessionId);
}

function getSessionMenuMarkup(action, session = null) {
  if (action === "rename") return `${SESSION_MENU_ICONS.rename} Rename`;
  if (action === "pin") {
    return session && session.pinned
      ? `${SESSION_MENU_ICONS.unpin} Unpin chat`
      : `${SESSION_MENU_ICONS.pin} Pin chat`;
  }
  if (action === "archive") {
    return session && session.archived
      ? `${SESSION_MENU_ICONS.unarchive} Unarchive`
      : `${SESSION_MENU_ICONS.archive} Archive`;
  }
  if (action === "delete") return `${SESSION_MENU_ICONS.delete} Delete`;
  return "";
}

function setSessionMenuItemMarkup(element, action, session = null) {
  if (element) element.innerHTML = getSessionMenuMarkup(action, session);
}

async function openRenameChat(sessionId) {
  const session = getSessionById(sessionId);
  if (!session) return;

  const currentTitle = session.title || "";
  const newTitle = prompt("Enter new title for this chat:", currentTitle);
  const trimmedTitle = newTitle ? newTitle.trim() : "";

  if (!trimmedTitle || trimmedTitle === currentTitle) return;

  try {
    await apiFetch(`/api/sessions/${session.session_id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: trimmedTitle }),
    });

    await refreshSessions();
  } catch (err) {
    reportActionError(err, "Failed to rename");
  }
}

async function togglePinChat(sessionId, { useActiveFallback = false } = {}) {
  const resolvedSessionId = sessionId || (useActiveFallback ? appState.activeSessionId : null);
  const session = getSessionById(resolvedSessionId);

  if (!session) {
    if (useActiveFallback) addMessage("system", "Start a conversation first.");
    return;
  }

  const newPinned = !session.pinned;

  try {
    await apiFetch(`/api/sessions/${session.session_id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned: newPinned }),
    });

    addMessage("system", newPinned ? "Chat pinned." : "Chat unpinned.");
    await refreshSessions();
  } catch (err) {
    reportActionError(err, "Failed to update pin");
  }
}

async function toggleArchiveChat(sessionId, { useActiveFallback = false } = {}) {
  const resolvedSessionId = sessionId || (useActiveFallback ? appState.activeSessionId : null);
  const session = getSessionById(resolvedSessionId);

  if (!session) {
    if (useActiveFallback) addMessage("system", "Start a conversation first.");
    return;
  }

  const isArchived = !!session.archived;

  try {
    await apiFetch(`/api/sessions/${session.session_id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archived: !isArchived }),
    });

    if (!isArchived && session.session_id === appState.activeSessionId) {
      startNewChat();
    }

    addMessage("system", isArchived ? "Chat unarchived." : "Chat archived.");
    await refreshSessions();
  } catch (err) {
    reportActionError(err, `Failed to ${isArchived ? "unarchive" : "archive"}`);
  }
}

async function deleteChat(sessionId, { useActiveFallback = false } = {}) {
  const resolvedSessionId = sessionId || (useActiveFallback ? appState.activeSessionId : null);
  const session = getSessionById(resolvedSessionId);

  if (!session) {
    if (useActiveFallback && appState.conversation.length > 0) {
      startNewChat();
      addMessage("system", "Conversation cleared.");
      updateClearAllChatsState();
    }
    return;
  }

  if (!confirm("Delete this chat permanently?")) return;

  try {
    await apiFetch(`/api/sessions/${session.session_id}`, { method: "DELETE" });

    if (session.session_id === appState.activeSessionId) startNewChat();
    addMessage("system", "Chat deleted.");
    await refreshSessions();
  } catch (err) {
    reportActionError(err, "Failed to delete");
  }
}

// function createSessionItem(session) {
//   const item = document.createElement("div");
//   item.className = "session-item";
//   if (session.session_id === appState.activeSessionId) item.classList.add("active");

//   const icon = document.createElement("span");
//   icon.className = "session-icon";
//   icon.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>';

//   const title = document.createElement("span");
//   title.className = "session-title";
//   title.textContent = session.title || "Untitled chat";

//   item.append(icon, title);

//   if (session.pinned) {
//     const pin = document.createElement("span");
//     pin.className = "session-pin-indicator";
//     pin.textContent = "\u{1F4CC}";
//     item.appendChild(pin);
//   }

//   item.addEventListener("click", () => loadSession(session.session_id));
//   return item;
// }

function createSessionItem(session) {
  const item = document.createElement("div");
  item.className = "session-item";
  if (session.session_id === appState.activeSessionId) item.classList.add("active");

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

  // --- Three Dots Menu ---
  const optionsBtn = document.createElement("button");
  optionsBtn.className = "session-actions-btn";
  optionsBtn.title = "Options";
  optionsBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle></svg>';

  const dropdown = document.createElement("div");
  dropdown.className = "dropdown-menu session-dropdown";

  const renameOpt = document.createElement("button");
  renameOpt.className = "dropdown-item";
  renameOpt.innerHTML = getSessionMenuMarkup("rename");
  renameOpt.onclick = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    closeAllDropdowns();
    await openRenameChat(session.session_id);
  };

  const pinOpt = document.createElement("button");
  pinOpt.className = "dropdown-item";
  pinOpt.innerHTML = getSessionMenuMarkup("pin", session);
  pinOpt.onclick = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    closeAllDropdowns();
    await togglePinChat(session.session_id);
  };

  const archiveOpt = document.createElement("button");
  archiveOpt.className = "dropdown-item";
  archiveOpt.innerHTML = getSessionMenuMarkup("archive", session);
  archiveOpt.onclick = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    closeAllDropdowns();
    await toggleArchiveChat(session.session_id);
  };

  const divider = document.createElement("div");
  divider.className = "dropdown-divider";

  const deleteOpt = document.createElement("button");
  deleteOpt.className = "dropdown-item danger";
  deleteOpt.innerHTML = getSessionMenuMarkup("delete");
  deleteOpt.onclick = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    closeAllDropdowns();
    await deleteChat(session.session_id);
  };

  dropdown.append(renameOpt, pinOpt, archiveOpt, divider, deleteOpt);

  optionsBtn.onclick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const isOpen = dropdown.classList.contains("show");
    closeAllDropdowns();
    if (!isOpen) {
      dropdown.classList.add("show");
      optionsBtn.classList.add("menu-open");
    }
  };

  item.append(optionsBtn, dropdown);

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
    const data = await apiFetch(`/api/sessions/${sessionId}/messages`);
    const messages = data.messages || [];

    messages.forEach((msg) => {
      addMessage(msg.role, msg.text, "", msg.created_at);
      appState.conversation.push({ role: msg.role, text: msg.text });
    });
  } catch (err) {
    reportActionError(err, "Failed to load chat");
  }

  renderSessions(appState.sessions);
  updateSessionActionButtons();
  updateClearAllChatsState();
}

async function refreshSessions() {
  try {
    const data = await apiFetch("/api/sessions?include_archived=true");
    appState.sessions = data.sessions || [];
    if (appState.activeSessionId && !appState.sessions.some((session) => session.session_id === appState.activeSessionId)) {
      appState.activeSessionId = null;
    }
    renderSessions(appState.sessions);
    updateSessionActionButtons();
    updateClearAllChatsState();
  } catch (err) {
    reportActionError(err, "Failed to refresh chats");
  }
}

function updateSessionActionButtons() {
  const session = getActiveSession();
  setSessionMenuItemMarkup(elements.renameChatBtn, "rename");
  setSessionMenuItemMarkup(elements.pinChatBtn, "pin", session);
  setSessionMenuItemMarkup(elements.archiveChatBtn, "archive", session);
  setSessionMenuItemMarkup(elements.deleteChatBtn, "delete");
}

async function clearAllChats() {
  const hasSavedSessions = Array.isArray(appState.sessions) && appState.sessions.length > 0;
  const hasDraftConversation = Array.isArray(appState.conversation) && appState.conversation.length > 0;

  if (!hasSavedSessions && !hasDraftConversation) {
    addMessage("system", "There are no chats to clear.");
    return;
  }

  if (!confirm("Clear all chats? This will remove every chat in the current scope.")) return;

  if (!hasSavedSessions && hasDraftConversation) {
    startNewChat();
    addMessage("system", "Conversation cleared.");
    updateClearAllChatsState();
    return;
  }

  try {
    const data = await apiFetch("/api/sessions", { method: "DELETE" });
    const total = Number(data.counts?.sessions || 0);
    startNewChat();
    await refreshSessions();
    addMessage("system", total <= 0 ? "Chats cleared." : total === 1 ? "Cleared 1 chat." : `Cleared ${total} chats.`);
  } catch (error) {
    reportActionError(error, "Failed to clear chats");
  }
}

// ---------- Memory & Data Views ----------

function refreshMemoryViews() {
  if (!appState.memoryEnabled) {
    clearMemoryStateViews();
    return;
  }
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
    <div class="weather-item"><p class="task-title">${escapeHtml(weather.location)}</p><p>${escapeHtml(weather.condition)}</p><p class="tiny">${escapeHtml(weather.advice || "")}</p></div>
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
  elements.newsCard.innerHTML = news.items.map((item) => `
        <article class="news-item">
          <p class="task-title">${escapeHtml(item.title)}</p>
          <div class="tiny">${escapeHtml(item.source || "Google News")}${item.published_at ? ` - ${escapeHtml(item.published_at)}` : ""}</div>
          <a href="${escapeHtml(item.link)}" target="_blank" rel="noreferrer">Open headline</a>
        </article>
      `).join("");
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
      <div><p class="task-title">${escapeHtml(task.title)}</p><div class="tiny">#${escapeHtml(task.id)} - ${escapeHtml(task.priority)} priority${task.due_date ? ` - due ${escapeHtml(task.due_date)}` : ""}</div></div>
      <div class="task-actions">
        <button class="ghost-button task-done-btn">Done</button>
        <button class="task-delete-btn" title="Delete this task">&times;</button>
      </div>
    `;
    item.querySelector(".task-done-btn").addEventListener("click", () => completeTask(task.id));
    item.querySelector(".task-delete-btn").addEventListener("click", () => deleteTask(task.id));
    elements.taskList.appendChild(item);
  });
}

function renderNotes(notes) {
  const recentNotes = (notes || []).slice(-4).reverse();
  if (!recentNotes.length) {
    elements.notesList.innerHTML = '<p class="muted">Ask Orbit to remember preferences, routines, or useful details.</p>';
    return;
  }
  elements.notesList.innerHTML = "";
  recentNotes.forEach((note) => {
    const item = document.createElement("div");
    item.className = "note-item";
    item.innerHTML = `
      <div class="note-content"><p class="note-title">${escapeHtml(note.category)}</p><p>${escapeHtml(note.text)}</p><div class="tiny">${escapeHtml(note.created_at)}</div></div>
      <button class="note-delete-btn" title="Delete this note">&times;</button>
    `;
    item.querySelector(".note-delete-btn").addEventListener("click", () => deleteNote(note.id));
    elements.notesList.appendChild(item);
  });
}

// ---------- Profile, Weather, News, Tasks ----------

async function saveProfile(event) {
  event.preventDefault();
  if (!ensureMemoryEnabled()) return;
  try {
    const data = await apiFetch("/api/profile", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        displayName: elements.displayNameInput.value.trim(),
        location: elements.locationInput.value.trim(),
        routine: elements.routineInput.value.trim(),
        timezone: elements.timezoneInput.value.trim(),
        dateOfBirth: elements.dateOfBirthInput.value.trim(),
        occupation: elements.occupationInput.value.trim(),
        interests: elements.interestsInput.value.trim(),
        preferredTone: elements.preferredToneInput.value,
        bio: elements.bioInput.value.trim(),
      }),
    });
    appState.memory = data.memory || null;
    refreshMemoryViews();
  } catch (error) {
    reportActionError(error, "Could not save your profile");
  }
}

async function refreshWeather() {
  const location = elements.locationInput.value.trim();
  const params = new URLSearchParams();
  if (location) params.set("location", location);
  params.set("use_memory", appState.memoryEnabled ? "true" : "false");
  try {
    const data = await apiFetch(`/api/weather?${params.toString()}`);
    if (appState.memoryEnabled) {
      appState.memory = data.memory || null;
      refreshMemoryViews();
    } else {
      renderWeather(data.weather);
    }
  } catch (error) {
    reportActionError(error, "Could not refresh the weather");
  }
}

async function refreshNews() {
  const location = elements.locationInput.value.trim();
  const topic = location ? `${location} headlines` : "top headlines";
  const params = new URLSearchParams();
  params.set("topic", topic);
  params.set("use_memory", appState.memoryEnabled ? "true" : "false");
  try {
    const data = await apiFetch(`/api/news?${params.toString()}`);
    if (appState.memoryEnabled) {
      appState.memory = data.memory || null;
      refreshMemoryViews();
    } else {
      renderNews(data.news);
    }
  } catch (error) {
    reportActionError(error, "Could not refresh the news");
  }
}

async function addTask(event) {
  event.preventDefault();
  if (!ensureMemoryEnabled()) return;
  try {
    const data = await apiFetch("/api/tasks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: elements.taskTitleInput.value.trim(),
        priority: elements.taskPriorityInput.value,
        dueDate: elements.taskDueDateInput.value.trim(),
      }),
    });
    elements.taskTitleInput.value = "";
    elements.taskDueDateInput.value = "";
    appState.memory = data.memory || null;
    refreshMemoryViews();
  } catch (error) {
    reportActionError(error, "Could not add task");
  }
}

async function completeTask(taskRef) {
  if (!ensureMemoryEnabled()) return;
  try {
    const data = await apiFetch("/api/tasks/complete", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ taskRef }),
    });
    appState.memory = data.memory || null;
    refreshMemoryViews();
  } catch (error) {
    reportActionError(error, "Could not complete task");
  }
}

async function deleteTask(taskId) {
  if (!taskId) return;
  if (!ensureMemoryEnabled()) return;
  try {
    const data = await apiFetch(`/api/tasks/${taskId}`, { method: "DELETE" });
    appState.memory = data.memory || null;
    refreshMemoryViews();
  } catch (error) {
    reportActionError(error, "Could not delete task");
  }
}

async function deleteNote(noteId) {
  if (!noteId) return;
  if (!ensureMemoryEnabled()) return;
  try {
    const data = await apiFetch(`/api/notes/${noteId}`, { method: "DELETE" });
    appState.memory = data.memory || null;
    refreshMemoryViews();
  } catch (error) {
    reportActionError(error, "Could not delete note");
  }
}

async function addNoteManual(event) {
  event.preventDefault();
  if (!ensureMemoryEnabled()) return;
  const text = elements.noteTextInput.value.trim();
  const category = elements.noteCategoryInput.value.trim() || "note";
  if (!text) return;
  try {
    const data = await apiFetch("/api/notes", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, category }),
    });
    elements.noteTextInput.value = "";
    elements.noteCategoryInput.value = "";
    appState.memory = data.memory || null;
    refreshMemoryViews();
  } catch (error) {
    reportActionError(error, "Could not save note");
  }
}

async function saveMessageAsNote(bodyEl, messageEl) {
  if (!ensureMemoryEnabled()) return;
  const selection = window.getSelection();
  let noteText = "";
  if (selection && selection.toString().trim() && messageEl.contains(selection.anchorNode)) {
    noteText = selection.toString().trim();
  } else { noteText = bodyEl.innerText.trim(); }
  if (!noteText) return;
  if (noteText.length > 500) noteText = noteText.substring(0, 500) + "...";
  try {
    const data = await apiFetch("/api/notes", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: noteText, category: "saved" }),
    });
    appState.memory = data.memory || null;
    refreshMemoryViews();
    const btn = messageEl.querySelector(".message-action-btn");
    if (btn) {
      const original = btn.innerHTML;
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg><span>Saved!</span>';
      btn.classList.add("saved");
      setTimeout(() => { btn.innerHTML = original; btn.classList.remove("saved"); }, 2000);
    }
  } catch (error) {
    reportActionError(error, "Could not save note");
  }
}

// ---------- File Attachment ----------

async function handleFileAttach() {
  if (appState.storageMode === "ephemeral") {
    addMessage("system", "File attachments require Agent Memory. Restart with MongoDB to attach files to chats.");
    elements.fileAttachInput.value = "";
    return;
  }

  const files = elements.fileAttachInput.files;
  if (!files || files.length === 0) return;
  if (!appState.activeSessionId) {
    try {
      const sessionData = await apiFetch("/api/sessions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "File attachment chat" }),
      });
      if (sessionData.session) {
        appState.activeSessionId = sessionData.session.session_id;
        await refreshSessions();
      }
    } catch (error) {
      elements.fileAttachInput.value = "";
      reportActionError(error, "Could not create file attachment chat");
      return;
    }
  }

  for (const file of files) {
    const allowedExts = SUPPORTED_FILE_EXTS;
    const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
    if (!allowedExts.includes(ext)) { addMessage("system", `Unsupported file type: ${ext}`); continue; }
    if (file.size > 20 * 1024 * 1024) continue;
    addMessage("system", `Uploading ${file.name}...`);
    try {
      const base64Data = await fileToBase64(file);
      const data = await apiFetch(`/api/sessions/${appState.activeSessionId}/attachments`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, data: base64Data }),
      });
      if (data.attachment?.parse_error) {
        addMessage("system", `Attached ${file.name} but could not parse for search: ${data.attachment.parse_error}`);
      } else {
        addMessage("system", `Attached ${file.name}. You can now ask questions about it.`);
      }
      elements.attachFilesBtn.classList.add("active");
    } catch (error) {
      reportActionError(error, `Could not attach ${file.name}`);
    }
  }
  elements.fileAttachInput.value = "";
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
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
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 2 }, audio: false });
    appState.screenStream = stream;
    elements.screenVideo.srcObject = stream;
    await elements.screenVideo.play();
    captureScreenFrame();
    if (appState.captureIntervalId) clearInterval(appState.captureIntervalId);
    appState.captureIntervalId = window.setInterval(captureScreenFrame, 2500);
    const [track] = stream.getVideoTracks();
    if (track) track.addEventListener("ended", stopScreenShare);
    addMessage("system", "Screen sharing is active. Orbit can now use the latest captured frame when you send a message.");
  } catch (error) { }
}

function stopScreenShare() {
  if (appState.screenStream) appState.screenStream.getTracks().forEach((track) => track.stop());
  appState.screenStream = null;
  appState.latestScreenImage = null;
  elements.screenVideo.srcObject = null;
  if (appState.captureIntervalId) { clearInterval(appState.captureIntervalId); appState.captureIntervalId = null; }
  const context = elements.screenPreview.getContext("2d");
  context.clearRect(0, 0, elements.screenPreview.width, elements.screenPreview.height);
}

function captureScreenFrame() {
  if (!elements.screenVideo.videoWidth || !elements.screenVideo.videoHeight) return;
  const context = elements.screenPreview.getContext("2d");
  const scale = Math.min(1, 1280 / elements.screenVideo.videoWidth);
  const width = Math.round(elements.screenVideo.videoWidth * scale);
  const height = Math.round(elements.screenVideo.videoHeight * scale);
  elements.screenPreview.width = width;
  elements.screenPreview.height = height;
  context.drawImage(elements.screenVideo, 0, 0, width, height);
  appState.latestScreenImage = elements.screenPreview.toDataURL("image/jpeg", 0.82);
}

// ---------- Utility ----------

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

// ---------- Global Dropdown Listeners ----------
function closeAllDropdowns() {
  document.querySelectorAll(".dropdown-menu.show").forEach(d => d.classList.remove("show"));
  document.querySelectorAll(".session-actions-btn.menu-open").forEach(b => b.classList.remove("menu-open"));
}

document.addEventListener("click", closeAllDropdowns);