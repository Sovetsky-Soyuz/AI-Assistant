// import { AnimeAvatar } from "./avatar-renderer.js";

// const canvas = document.getElementById("avatarCanvas");
// const avatar = new AnimeAvatar(canvas);

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

const IELTS_MODE_COPY = {
  speaking: "Orbit can roleplay as an examiner, ask one question at a time, and score fluency, vocabulary, grammar, and coherence.",
  writing: "Orbit can estimate a band, score the four writing criteria, and rewrite weak paragraphs into stronger IELTS-style responses.",
  reading: "Orbit can teach question strategy, create mini reading drills, and explain exactly why each answer is right or wrong.",
  listening: "Orbit can build note completion and dictation-style drills, then explain trap answers, spelling, and number formatting.",
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

const appState = {
  mode: "simple",
  ieltsSkill: window.localStorage.getItem("orbit_virtual_ielts_skill") || "speaking",
  targetBand: window.localStorage.getItem("orbit_virtual_target_band") || "6.5",
  preferredLanguage: window.localStorage.getItem("orbit_virtual_language") || "default",
  conversation: [],
  latestScreenImage: null,
  screenStream: null,
  captureIntervalId: null,
  memory: null,
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
  currentTurn: null,
  stageWorker: null,
  recentToolEvents: [],
  silenceTimeoutId: null,
};

const elements = {
  apiStatus: document.getElementById("apiStatus"),
  modelBadge: document.getElementById("modelBadge"),
  runtimeBadge: document.getElementById("runtimeBadge"),
  todayLabel: document.getElementById("todayLabel"),
  voiceToggle: document.getElementById("voiceToggle"),
  voiceStatus: document.getElementById("voiceStatus"),
  composerVoiceStatus: document.getElementById("composerVoiceStatus"),
  voiceLanguageSelect: document.getElementById("voiceLanguageSelect"),
  conversationLanguageSelect: document.getElementById("conversationLanguageSelect"),
  micButton: document.getElementById("micButton"),
  modeButtons: Array.from(document.querySelectorAll(".mode-button")),
  quickActions: Array.from(document.querySelectorAll(".ghost-button[data-prompt]")),
  practiceButtons: Array.from(document.querySelectorAll(".practice-button")),
  ieltsPanel: document.getElementById("ieltsPanel"),
  ieltsModeCopy: document.getElementById("ieltsModeCopy"),
  ieltsSkillSelect: document.getElementById("ieltsSkillSelect"),
  targetBandInput: document.getElementById("targetBandInput"),
  stageStatus: document.getElementById("stageStatus"),
  stageCopy: document.getElementById("stageCopy"),
  avatarStage: document.getElementById("avatarStage"),
  memoryHint: document.getElementById("memoryHint"),
  messageList: document.getElementById("messageList"),
  toolEvents: document.getElementById("toolEvents"),
  composer: document.getElementById("composer"),
  messageInput: document.getElementById("messageInput"),
  attachScreenToggle: document.getElementById("attachScreenToggle"),
  sendButton: document.getElementById("sendButton"),
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
  notesList: document.getElementById("notesList"),
};

document.addEventListener("DOMContentLoaded", async () => {
  populateLanguageSelects();
  bindEvents();
  initAvatarWorker();
  refreshTodayLabel();
  updateModeUI();
  setupSpeechRecognition();
  setStageState("idle", "Idle and ready.", "A lighter Assistant shell is running locally in your browser.");
  addMessage(
    "system",
    "Orbit Virtual Assistant is ready. You can type, Unmute the mic to talk, share your screen for context, or switch into IELTS coach mode."
  );
  await refreshState();
});

function populateLanguageSelects() {
  const voiceValue = window.localStorage.getItem("orbit_voice_language") || "default";
  elements.voiceLanguageSelect.innerHTML = "";
  elements.conversationLanguageSelect.innerHTML = "";

  VOICE_LANGUAGE_OPTIONS.forEach((option) => {
    const voiceNode = document.createElement("option");
    voiceNode.value = option.value;
    voiceNode.textContent = option.label;
    voiceNode.selected = option.value === voiceValue;
    elements.voiceLanguageSelect.appendChild(voiceNode);

    const conversationNode = document.createElement("option");
    conversationNode.value = option.value;
    conversationNode.textContent = option.label;
    conversationNode.selected = option.value === appState.preferredLanguage;
    elements.conversationLanguageSelect.appendChild(conversationNode);
  });

  elements.ieltsSkillSelect.value = appState.ieltsSkill;
  elements.targetBandInput.value = appState.targetBand;
}

function bindEvents() {
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

  elements.modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setMode(button.dataset.mode || "simple");
    });
  });

  elements.ieltsSkillSelect.addEventListener("change", () => {
    appState.ieltsSkill = elements.ieltsSkillSelect.value;
    window.localStorage.setItem("orbit_virtual_ielts_skill", appState.ieltsSkill);
    updateModeUI();
  });

  elements.targetBandInput.addEventListener("change", () => {
    appState.targetBand = elements.targetBandInput.value.trim() || "6.5";
    elements.targetBandInput.value = appState.targetBand;
    window.localStorage.setItem("orbit_virtual_target_band", appState.targetBand);
  });

  /// Hold-to-talk voice capture is currently disabled to avoid conflicts with spacebar hotkey and to simplify the experience, but the handlers are left here for easy re-enabling in the future if desired.
  
  // elements.micButton.addEventListener("pointerdown", handleMicPointerDown);
  // window.addEventListener("pointerup", handleMicPointerUp);
  // window.addEventListener("pointercancel", handleMicPointerUp);
  // window.addEventListener("keydown", handleHotkeyDown);
  // window.addEventListener("keyup", handleHotkeyUp);

  elements.micButton.addEventListener("click", toggleVoiceCapture);
  window.addEventListener("keydown", handleToggleHotkey);

  elements.composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const prompt = elements.messageInput.value.trim();
    if (!prompt) {
      return;
    }
    elements.messageInput.value = "";
    await sendPrompt(prompt);
  });

  elements.quickActions.forEach((button) => {
    button.addEventListener("click", async () => {
      const needsScreen = button.dataset.needsScreen === "true";
      if (needsScreen && !appState.latestScreenImage) {
        addMessage("system", "Start screen sharing first so Orbit can use your current screen as context.");
        return;
      }
      if ((button.dataset.prompt || "").includes("IELTS Speaking")) {
        setMode("ielts", "speaking");
      }
      await sendPrompt(button.dataset.prompt || "", { forceScreen: needsScreen });
    });
  });

  elements.practiceButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      setMode("ielts", button.dataset.ieltsSkill || "speaking");
      await sendPrompt(button.dataset.prompt || "");
    });
  });

  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault(); 
      
      const prompt = elements.messageInput.value.trim();
      if (prompt) {
        elements.sendButton.click();
      }
    }
  });

  elements.startShareButton.addEventListener("click", startScreenShare);
  elements.stopShareButton.addEventListener("click", stopScreenShare);
  elements.profileForm.addEventListener("submit", saveProfile);
  elements.refreshWeatherButton.addEventListener("click", refreshWeather);
  elements.refreshNewsButton.addEventListener("click", refreshNews);
  elements.taskForm.addEventListener("submit", addTask);
}

function initAvatarWorker() {
  if (!window.Worker) {
    elements.runtimeBadge.textContent = "No Web Worker";
    return;
  }

  const worker = new Worker("/avatar-worker.js");
  worker.addEventListener("message", (event) => {
    const payload = event.data || {};
    if (payload.type !== "frame") {
      return;
    }
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
  elements.modeButtons.forEach((button) => button.classList.toggle("active", button.dataset.mode === appState.mode));
  elements.ieltsPanel.classList.toggle("hidden", appState.mode !== "ielts");
  elements.ieltsModeCopy.textContent = IELTS_MODE_COPY[appState.ieltsSkill] || IELTS_MODE_COPY.speaking;
}

function setMode(mode, ieltsSkill = appState.ieltsSkill) {
  appState.mode = mode;
  appState.ieltsSkill = ieltsSkill;
  elements.ieltsSkillSelect.value = appState.ieltsSkill;
  updateModeUI();
}

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
    ensureVoiceTurn();
    ensureVoiceDraft();
    setStageState("listening", "Listening for your voice.", "Orbit is capturing speech and will turn it into the next chat bubble.");
    setVoiceStatus(`Listening in ${getSelectedLanguageLabel(elements.voiceLanguageSelect.value)}...`);

    resetSilenceTimer();

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
    ensureVoiceTurn();
    ensureVoiceDraft();
    appState.currentTurn.inputText = appState.liveVoiceTranscript;
    appState.currentTurn.userNode.querySelector(".message-body").textContent =
      appState.liveVoiceTranscript || "Listening...";
    appState.currentTurn.userNode.querySelector(".message-meta").textContent = "Voice transcript";
    setVoiceStatus("Capturing speech...");

    resetSilenceTimer();
  };

  recognition.onerror = (event) => {
    clearSilenceTimer();
    appState.recognitionStarting = false;
    appState.listening = false;
    appState.stopRecognitionAfterStart = false;
    appState.micHeld = false;
    appState.spaceTalking = false;
    updateMicButton();
    if (event.error !== "aborted") {
      setVoiceStatus(`Voice input error: ${event.error}`);
      setStageState("idle", "Idle and ready.", "Speech recognition stopped because the browser returned an error.");
    }
  };

  recognition.onend = async () => {
    clearSilenceTimer();
    const transcript = appState.liveVoiceTranscript.trim();
    appState.recognitionStarting = false;
    appState.listening = false;
    appState.stopRecognitionAfterStart = false;
    appState.micHeld = false;
    appState.spaceTalking = false;
    updateMicButton();

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
    setStageState("idle", "Idle and ready.", "Orbit is waiting for your next question.");
  };

  appState.speechRecognition = recognition;
  appState.speechSupported = true;
  updateMicButton();
  setVoiceStatus(`Voice ready (${getSelectedLanguageLabel(elements.voiceLanguageSelect.value)})`);
}

async function refreshState() {
  const response = await fetch("/api/state");
  const data = await response.json();

  appState.memory = data.memory;
  appState.liveVoiceName = data.liveVoiceName || "Kore";
  const provider = data.provider || "Gemini";
  elements.apiStatus.textContent = data.hasApiKey ? `${provider} key detected` : "Add API_KEY to enable chat";
  elements.modelBadge.textContent = data.model ? `Model: ${data.model}` : "Model not set";
  elements.runtimeBadge.textContent = "Browser + REST";

  elements.displayNameInput.value = data.memory.profile.display_name || "";
  elements.locationInput.value = data.memory.profile.location || data.defaultLocation || "";
  elements.routineInput.value = data.memory.profile.routine || "";

  refreshMemoryViews();
}

async function sendPrompt(prompt, options = {}) {
  if (appState.currentTurn && appState.currentTurn.assistantNode) {
    return; 
  }
  const attachScreen = options.forceScreen || elements.attachScreenToggle.checked;
  const screenImage = attachScreen ? appState.latestScreenImage : null;
  const priorConversation = [...appState.conversation];
  const shouldSpeakReply = appState.voiceEnabled || options.fromVoice === true;
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

  turn.assistantNode = turn.assistantNode || addMessage("assistant", "Thinking...", "Orbit");
  turn.assistantNode.querySelector(".message-body").textContent = "Thinking...";
  turn.assistantNode.querySelector(".message-meta").textContent = "Orbit";
  appState.currentTurn = turn;

  setComposerState(true);
  setStageState("thinking", "Thinking through your request.", "Orbit is combining memory, tools, and your latest screen or voice context.");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: prompt,
        conversation: priorConversation,
        screenImage,
        mode: appState.mode,
        ieltsSkill: appState.ieltsSkill,
        targetBand: appState.targetBand,
        preferredLanguage: appState.preferredLanguage,
      }),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Chat request failed.");
    }

    turn.outputText = data.reply;
    turn.assistantNode.querySelector(".message-body").textContent = data.reply;
    // turn.assistantNode.querySelector(".message-meta").textContent = data.model || "";
    turn.assistantNode.querySelector(".message-meta").textContent = "Orbit";

    if (!turn.assistantStored) {
      appState.conversation.push({ role: "assistant", text: data.reply });
      turn.assistantStored = true;
    }
    appState.memory = data.memory;
    appState.recentToolEvents = data.toolEvents || [];
    refreshMemoryViews();
    renderToolEvents(appState.recentToolEvents);
    setStageState("speaking", "Orbit is replying.", "This simple virtual shell uses browser speech and a worker-driven stage while the model reply stays visible in chat.");

    if (shouldSpeakReply && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(data.reply);

      // const voices = window.speechSynthesis.getVoices();
      // // const targetVoiceName = process.env.LIVE_VOICE_NAME || "Kore";
      // const targetVoiceName = appState.liveVoiceName;
      // const selectedVoice = voices.find((voice) => voice.name.includes(targetVoiceName));

      // if (selectedVoice) {
      //   utterance.voice = selectedVoice;
      // }

      const voices = window.speechSynthesis.getVoices();
      const targetVoiceName = appState.liveVoiceName;
      
      const selectedVoice = voices.find((voice) => 
        voice.name.toLowerCase().includes(targetVoiceName.toLowerCase())
      );

      if (selectedVoice) {
        utterance.voice = selectedVoice;
        utterance.lang = selectedVoice.lang; 
      }

      utterance.onend = () => {
        setStageState("idle", "Idle and ready.", "Orbit is waiting for your next question.");
        //
        if (options.fromVoice) {
          void startVoiceCapture();
        }
      };
      window.speechSynthesis.speak(utterance);
    } else {
      window.setTimeout(() => {
        setStageState("idle", "Idle and ready.", "Orbit is waiting for your next question.");
        
        if (options.fromVoice) {
            void startVoiceCapture();
        }

      }, 320);
    }
  } catch (error) {
    turn.assistantNode.querySelector(".message-body").textContent = error.message;
    turn.assistantNode.classList.add("system");
    setStageState("idle", "Idle and ready.", "Orbit hit an error and is waiting for another try.");
  } finally {
    appState.currentTurn = null;
    setComposerState(false);
    setVoiceStatus("Voice input idle");
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

function addMessage(role, text, meta = "") {
  const message = document.createElement("article");
  message.className = `message ${role}`;

  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text;

  const footer = document.createElement("div");
  footer.className = "message-meta";
  footer.textContent = meta;

  message.append(body, footer);
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

function refreshMemoryViews() {
  if (!appState.memory) {
    return;
  }
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
    elements.notesList.innerHTML = '<p class="muted">Ask Orbit to remember preferences, routines, or useful details.</p>';
    return;
  }

  elements.notesList.innerHTML = "";
  recentNotes.forEach((note) => {
    const item = document.createElement("div");
    item.className = "note-item";
    item.innerHTML = `
      <p class="note-title">${escapeHtml(note.category)}</p>
      <p>${escapeHtml(note.text)}</p>
      <div class="tiny">${escapeHtml(note.created_at)}</div>
    `;
    elements.notesList.appendChild(item);
  });
}

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
  if (!elements.screenVideo.videoWidth || !elements.screenVideo.videoHeight) {
    return;
  }

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

// function handleMicPointerDown(event) {
//   if (event.button !== 0) {
//     return;
//   }
//   appState.micHeld = true;
//   void startVoiceCapture();
// }

// function handleMicPointerUp() {
//   if (!appState.micHeld) {
//     return;
//   }
//   appState.micHeld = false;
//   stopVoiceCapture();
// }

// function handleHotkeyDown(event) {
//   if (event.code !== "Space" || event.repeat || shouldIgnoreSpaceHotkey()) {
//     return;
//   }
//   event.preventDefault();
//   appState.hotkeyDown = true;
//   appState.spaceTalking = true;
//   void startVoiceCapture();
// }

// function handleHotkeyUp(event) {
//   if (event.code !== "Space" || !appState.hotkeyDown) {
//     return;
//   }
//   event.preventDefault();
//   appState.hotkeyDown = false;
//   appState.spaceTalking = false;
//   stopVoiceCapture();
// }

// function shouldIgnoreSpaceHotkey() {
//   const activeElement = document.activeElement;
//   if (!activeElement) {
//     return false;
//   }
//   return ["INPUT", "TEXTAREA", "SELECT"].includes(activeElement.tagName) || activeElement.isContentEditable;
// }


function toggleVoiceCapture() {
  if (!appState.speechSupported) return;

  if (appState.listening || appState.recognitionStarting) {
    stopVoiceCapture();
  } else {
    void startVoiceCapture();
  }
}

function handleToggleHotkey(event) {
  if (event.key.toLowerCase() !== "m" || event.repeat || shouldIgnoreHotkey()) {
    return;
  }
  event.preventDefault();
  toggleVoiceCapture();
}

function shouldIgnoreHotkey() {
  const activeElement = document.activeElement;
  if (!activeElement) {
    return false;
  }
  return ["INPUT", "TEXTAREA", "SELECT"].includes(activeElement.tagName) || activeElement.isContentEditable;
}

async function startVoiceCapture() {
  if (!appState.speechSupported || !appState.speechRecognition) {
    return;
  }
  if (appState.listening || appState.recognitionStarting) {
    return;
  }

  try {
    appState.recognitionStarting = true;
    appState.stopRecognitionAfterStart = false;
    appState.speechRecognition.lang = resolveRecognitionLanguage();
    appState.speechRecognition.start();
    updateMicButton();
  } catch (error) {
    appState.recognitionStarting = false;
    updateMicButton();
    setVoiceStatus(error.message || "Could not start speech recognition.");
  }
}

function stopVoiceCapture() {
  if (!appState.speechRecognition) {
    return;
  }

  if (appState.recognitionStarting && !appState.listening) {
    appState.stopRecognitionAfterStart = true;
    return;
  }
  if (appState.listening) {
    appState.speechRecognition.stop();
  }
}

function resolveRecognitionLanguage() {
  return elements.voiceLanguageSelect.value === "default" ? navigator.language || "en-US" : elements.voiceLanguageSelect.value;
}

// function updateMicButton() {
//   if (!appState.speechSupported) {
//     elements.micButton.disabled = true;
//     elements.micButton.textContent = "Voice unavailable";
//     return;
//   }

//   elements.micButton.disabled = false;
//   if (appState.listening || appState.recognitionStarting) {
//     elements.micButton.textContent = "Release to send";
//     return;
//   }
//   elements.micButton.textContent = "Hold to talk";
// }

function updateMicButton() {
  if (!appState.speechSupported) {
    elements.micButton.disabled = true;
    elements.micButton.textContent = "Voice unavailable";
    return;
  }

  elements.micButton.disabled = false;
  if (appState.listening || appState.recognitionStarting) {
    elements.micButton.textContent = "Mute (Listening...)"; 
    elements.micButton.classList.add("active"); 
    return;
  }
  elements.micButton.textContent = "Unmute (Press M)";
  elements.micButton.classList.remove("active");
}

function setVoiceStatus(text) {
  elements.voiceStatus.textContent = text;
  elements.composerVoiceStatus.textContent = text;
}

function setComposerState(isBusy) {
  elements.sendButton.disabled = isBusy;
  elements.messageInput.disabled = isBusy;

  elements.quickActions.forEach(button => button.disabled = isBusy);
  elements.practiceButtons.forEach(button => button.disabled = isBusy);
}

function getSelectedLanguageLabel(value) {
  const selected = VOICE_LANGUAGE_OPTIONS.find((option) => option.value === value);
  return selected ? selected.label : "Browser default";
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return escapeHtml(value);
  }
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


function resetSilenceTimer() {
  clearSilenceTimer();
  appState.silenceTimeoutId = window.setTimeout(() => {
    if (appState.listening) {
      setVoiceStatus("Auto-stopped after 2s of silence.");
      stopVoiceCapture();
    }
  }, 2000); 
}

function clearSilenceTimer() {
  if (appState.silenceTimeoutId) {
    window.clearTimeout(appState.silenceTimeoutId);
    appState.silenceTimeoutId = null;
  }
}

// function setStage(state, text) {
//   avatar.setState(state);

//   document.getElementById("stageStatus").textContent = text;
// }

// micButton.addEventListener("mousedown", () => {
//   avatar.setState("listening");
// });

// micButton.addEventListener("mouseup", () => {
//   avatar.setState("thinking");
// });

// avatar.setState("speaking");

// speechSynthesis.onend = () => {
//   avatar.setState("idle");
// };