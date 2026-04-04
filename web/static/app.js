/**
 * app.js — Ambientizer web frontend
 *
 * Two tabs:
 *   - Create: prompt → generate → layers → feedback loop
 *   - Visuals: pick a track → generate image → create video → download
 */

(function () {
  "use strict";

  // ═══════════════════════════════════════════════════════
  //  Tab Navigation
  // ═══════════════════════════════════════════════════════

  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabContents = document.querySelectorAll(".tab-content");

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      tabButtons.forEach((b) => b.classList.remove("active"));
      tabContents.forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${target}`).classList.add("active");

      if (target === "visuals") refreshVisTrackList();
      if (target === "publish") { checkYouTubeStatus(); refreshPubTrackList(); }
    });
  });

  // ═══════════════════════════════════════════════════════
  //  TAB: Create
  // ═══════════════════════════════════════════════════════

  // ── DOM refs ──────────────────────────────────
  const promptEl = document.getElementById("prompt");
  const referenceUrlEl = document.getElementById("reference-url");
  const durationEl = document.getElementById("duration");
  const musicLengthEl = document.getElementById("music-length");
  const loopableEl = document.getElementById("loopable");
  const generateBtn = document.getElementById("generate-btn");
  const modeButtons = document.querySelectorAll("[data-mode]");

  const progressPanel = document.getElementById("progress-panel");
  const progressStage = document.getElementById("progress-stage");
  const progressMessage = document.getElementById("progress-message");
  const progressBar = document.getElementById("progress-bar");
  const logContainer = document.getElementById("log-container");

  const playerPanel = document.getElementById("player-panel");
  const playerPrompt = document.getElementById("player-prompt");
  const audioPlayer = document.getElementById("audio-player");
  const btnDownload = document.getElementById("btn-download");

  const layersPanel = document.getElementById("layers-panel");
  const layersList = document.getElementById("layers-list");
  const layersCount = document.getElementById("layers-count");

  const feedbackPanel = document.getElementById("feedback-panel");
  const feedbackMessages = document.getElementById("feedback-messages");
  const feedbackInput = document.getElementById("feedback-input");
  const feedbackSend = document.getElementById("feedback-send");

  const historyList = document.getElementById("history-list");

  // ── State ─────────────────────────────────────
  let currentJobId = null;
  let pollInterval = null;
  let currentMode = "ambient";
  let feedbackPending = false;
  let currentRootKey = "";
  let currentLayers = [];
  let layerActionPending = false;
  let sliderDebounceTimers = {};
  let pendingSliderUpdates = {};
  let mixer = null;
  let currentTrackDuration = 300;

  // ── Auto-save form state to localStorage ─────
  const FORM_KEY = "ambientizer_form";
  const SAVED_PROMPTS_KEY = "ambientizer_saved_prompts";

  function saveFormState() {
    const state = {
      prompt: promptEl.value,
      mode: currentMode,
      duration: durationEl.value,
      music_length: musicLengthEl.value,
      reference_url: referenceUrlEl.value,
      loopable: loopableEl.checked,
    };
    try { localStorage.setItem(FORM_KEY, JSON.stringify(state)); } catch (_) {}
  }

  function restoreFormState() {
    try {
      const raw = localStorage.getItem(FORM_KEY);
      if (!raw) return;
      const s = JSON.parse(raw);
      if (s.prompt) promptEl.value = s.prompt;
      if (s.mode) {
        currentMode = s.mode;
        modeButtons.forEach(b => b.classList.toggle("active", b.dataset.mode === s.mode));
      }
      if (s.duration) durationEl.value = s.duration;
      if (s.music_length) musicLengthEl.value = s.music_length;
      if (s.reference_url) referenceUrlEl.value = s.reference_url;
      if (s.loopable !== undefined) loopableEl.checked = s.loopable;
    } catch (_) {}
  }

  promptEl.addEventListener("input", saveFormState);
  durationEl.addEventListener("change", saveFormState);
  musicLengthEl.addEventListener("change", saveFormState);
  referenceUrlEl.addEventListener("input", saveFormState);
  loopableEl.addEventListener("change", saveFormState);
  restoreFormState();

  // ── Saved Prompts Library ─────────────────────
  function getSavedPrompts() {
    try { return JSON.parse(localStorage.getItem(SAVED_PROMPTS_KEY) || "[]"); } catch (_) { return []; }
  }
  function setSavedPrompts(list) {
    try { localStorage.setItem(SAVED_PROMPTS_KEY, JSON.stringify(list)); } catch (_) {}
  }

  function renderSavedPrompts() {
    const container = document.getElementById("saved-prompts-list");
    if (!container) return;
    const prompts = getSavedPrompts();
    if (!prompts.length) {
      container.innerHTML = '<div class="sp-empty">No saved prompts yet. Click the star to save one.</div>';
      return;
    }
    container.innerHTML = prompts.map((p, i) => `
      <div class="sp-item" data-idx="${i}">
        <div class="sp-item-body">
          <span class="sp-mode-badge ${p.mode || "ambient"}">${p.mode || "ambient"}</span>
          <span class="sp-text">${escapeHtml(p.prompt.length > 120 ? p.prompt.slice(0, 120) + "..." : p.prompt)}</span>
        </div>
        <div class="sp-item-actions">
          <button class="sp-load" data-idx="${i}" title="Load this prompt">Use</button>
          <button class="sp-delete" data-idx="${i}" title="Delete">&times;</button>
        </div>
      </div>
    `).join("");

    container.querySelectorAll(".sp-load").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const p = prompts[parseInt(btn.dataset.idx)];
        promptEl.value = p.prompt;
        if (p.mode) {
          currentMode = p.mode;
          modeButtons.forEach(b => b.classList.toggle("active", b.dataset.mode === p.mode));
        }
        if (p.duration) durationEl.value = p.duration;
        if (p.music_length) musicLengthEl.value = p.music_length;
        if (p.reference_url) referenceUrlEl.value = p.reference_url;
        if (p.loopable !== undefined) loopableEl.checked = p.loopable;
        saveFormState();
        document.getElementById("saved-prompts-dropdown").classList.add("hidden");
      });
    });
    container.querySelectorAll(".sp-delete").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const list = getSavedPrompts();
        list.splice(parseInt(btn.dataset.idx), 1);
        setSavedPrompts(list);
        renderSavedPrompts();
      });
    });
  }

  const btnSavePrompt = document.getElementById("btn-save-prompt");
  const btnShowSaved = document.getElementById("btn-show-saved");
  const savedDropdown = document.getElementById("saved-prompts-dropdown");

  if (btnSavePrompt) {
    btnSavePrompt.addEventListener("click", () => {
      const prompt = promptEl.value.trim();
      if (!prompt) { promptEl.focus(); return; }
      const list = getSavedPrompts();
      if (list.some(p => p.prompt === prompt)) {
        btnSavePrompt.textContent = "Already saved";
        setTimeout(() => { btnSavePrompt.textContent = "Save"; }, 1500);
        return;
      }
      list.unshift({
        prompt,
        mode: currentMode,
        duration: durationEl.value,
        music_length: musicLengthEl.value,
        reference_url: referenceUrlEl.value,
        loopable: loopableEl.checked,
        saved_at: new Date().toISOString(),
      });
      setSavedPrompts(list);
      btnSavePrompt.textContent = "Saved!";
      setTimeout(() => { btnSavePrompt.textContent = "Save"; }, 1500);
      renderSavedPrompts();
    });
  }

  if (btnShowSaved) {
    btnShowSaved.addEventListener("click", () => {
      savedDropdown.classList.toggle("hidden");
      if (!savedDropdown.classList.contains("hidden")) renderSavedPrompts();
    });
    document.addEventListener("click", (e) => {
      if (!savedDropdown.contains(e.target) && e.target !== btnShowSaved) {
        savedDropdown.classList.add("hidden");
      }
    });
  }

  // ── Mode toggle ─────────────────────────────
  modeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      modeButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentMode = btn.dataset.mode;
      saveFormState();
    });
  });

  const stageProgress = {
    starting: 5,
    analyzing_reference: 10,
    interpreting: 20,
    generating_samples: 40,
    rendering: 65,
    mastering: 85,
    complete: 100,
    error: 100,
  };

  // ── Enhance Prompt ──────────────────────────────
  const btnEnhancePrompt = document.getElementById("btn-enhance-prompt");
  const enhanceStatus = document.getElementById("enhance-status");

  btnEnhancePrompt.addEventListener("click", async () => {
    const raw = promptEl.value.trim();
    if (!raw) { promptEl.focus(); return; }

    btnEnhancePrompt.disabled = true;
    btnEnhancePrompt.textContent = "Researching...";
    enhanceStatus.textContent = "Searching the web for context...";
    enhanceStatus.className = "enhance-status active";

    try {
      const res = await fetch("/api/enhance-prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: raw, mode: currentMode }),
      });
      const data = await res.json();
      if (data.error) {
        enhanceStatus.textContent = data.error;
        enhanceStatus.className = "enhance-status error";
      } else {
        promptEl.value = data.enhanced_prompt;
        promptEl.style.height = "auto";
        promptEl.style.height = promptEl.scrollHeight + "px";
        enhanceStatus.textContent = data.research_summary
          ? "Enhanced with web research"
          : "Enhanced";
        enhanceStatus.className = "enhance-status success";
        setTimeout(() => { enhanceStatus.textContent = ""; enhanceStatus.className = "enhance-status"; }, 5000);
      }
    } catch (err) {
      enhanceStatus.textContent = "Enhancement failed: " + err.message;
      enhanceStatus.className = "enhance-status error";
    }
    btnEnhancePrompt.disabled = false;
    btnEnhancePrompt.textContent = "Enhance Prompt";
  });

  // ── Generate ──────────────────────────────────
  generateBtn.addEventListener("click", async () => {
    const prompt = promptEl.value.trim();
    if (!prompt) {
      promptEl.focus();
      return;
    }

    generateBtn.disabled = true;
    generateBtn.textContent = "Generating...";

    progressPanel.classList.remove("hidden");
    playerPanel.classList.add("hidden");
    layersPanel.classList.add("hidden");
    feedbackPanel.classList.add("hidden");
    resetProgress();

    try {
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          duration: parseFloat(durationEl.value),
          music_length: parseFloat(musicLengthEl.value),
          mastering: true,
          mode: currentMode,
          reference_url: referenceUrlEl.value.trim(),
          loopable: loopableEl.checked,
        }),
      });

      const data = await res.json();
      if (data.error) {
        showError(data.error);
        return;
      }

      currentJobId = data.job_id;
      startPolling(data.job_id);
    } catch (err) {
      showError("Failed to start generation: " + err.message);
    }
  });

  // ── Polling ───────────────────────────────────
  function startPolling(jobId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`/api/status/${jobId}`);
        const data = await res.json();
        updateProgress(data);

        if (data.status === "complete" || data.status === "error") {
          clearInterval(pollInterval);
          pollInterval = null;
          generateBtn.disabled = false;
          generateBtn.textContent = "Generate Soundscape";

          if (data.status === "complete") {
            showPlayer(data);
            enableFeedback();
          }

          refreshHistory();
        }
      } catch (err) {
        console.error("Poll error:", err);
      }
    }, 2000);
  }

  // ── Progress ──────────────────────────────────
  function resetProgress() {
    progressStage.textContent = "Starting";
    progressStage.className = "stage-badge";
    progressMessage.textContent = "";
    progressBar.style.width = "0%";
    progressBar.classList.add("indeterminate");
    logContainer.innerHTML = "";
  }

  function updateProgress(data) {
    progressStage.textContent = formatStage(data.stage);
    if (data.status === "complete") progressStage.className = "stage-badge complete";
    else if (data.status === "error") progressStage.className = "stage-badge error";
    else progressStage.className = "stage-badge";

    progressMessage.textContent = cleanMessage(data.progress_message || "");
    const pct = stageProgress[data.stage] || 50;
    progressBar.classList.remove("indeterminate");
    progressBar.style.width = pct + "%";
    renderLogs(data.logs || []);
  }

  function formatStage(stage) {
    const names = {
      starting: "Starting", analyzing_reference: "Analyzing Reference",
      interpreting: "Interpreting", generating_samples: "Generating Audio",
      rendering: "Rendering", mastering: "Mastering",
      complete: "Complete", error: "Error",
    };
    return names[stage] || stage;
  }

  function cleanMessage(msg) {
    return msg.replace(/^[\s=]+/, "").replace(/[=]+$/, "").trim();
  }

  function renderLogs(logs) {
    logContainer.innerHTML = logs
      .map((l) => `<div class="log-entry">${cleanMessage(l.message)}</div>`)
      .join("");
    logContainer.scrollTop = logContainer.scrollHeight;
  }

  function showError(msg) {
    progressStage.textContent = "Error";
    progressStage.className = "stage-badge error";
    progressMessage.textContent = msg;
    progressBar.classList.remove("indeterminate");
    progressBar.style.width = "100%";
    progressBar.style.background = "var(--error)";
    generateBtn.disabled = false;
    generateBtn.textContent = "Generate Soundscape";
  }

  // ── Audio Player ──────────────────────────────
  // ── Live transport DOM refs ─────────────────────
  const liveTransport = document.getElementById("live-transport");
  const btnPlayPause = document.getElementById("btn-play-pause");
  const iconPlay = document.getElementById("icon-play");
  const iconPause = document.getElementById("icon-pause");
  const transportCurrent = document.getElementById("transport-current");
  const transportTotal = document.getElementById("transport-total");
  const transportSeek = document.getElementById("transport-seek");
  const mixerBadge = document.getElementById("mixer-badge");

  function formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  if (btnPlayPause) {
    btnPlayPause.addEventListener("click", () => {
      if (!mixer) return;
      mixer.togglePlayPause();
      iconPlay.classList.toggle("hidden", mixer.playing);
      iconPause.classList.toggle("hidden", !mixer.playing);
    });
  }

  if (transportSeek) {
    let seeking = false;
    transportSeek.addEventListener("mousedown", () => { seeking = true; });
    transportSeek.addEventListener("touchstart", () => { seeking = true; });
    transportSeek.addEventListener("input", () => {
      if (!mixer) return;
      const t = (parseFloat(transportSeek.value) / 1000) * mixer.duration;
      transportCurrent.textContent = formatTime(t);
    });
    transportSeek.addEventListener("change", () => {
      if (!mixer) return;
      const t = (parseFloat(transportSeek.value) / 1000) * mixer.duration;
      mixer.seek(t);
      seeking = false;
    });
    transportSeek.addEventListener("mouseup", () => { seeking = false; });
    transportSeek.addEventListener("touchend", () => { seeking = false; });

    // Prevent seek slider from updating while user is dragging
    window._seekDragging = () => seeking;
  }

  async function initMixer(jobId, layers, durationSec) {
    if (mixer) mixer.destroy();
    mixer = new LiveMixer();
    await mixer.init(durationSec);

    mixer.onTimeUpdate = (t, dur) => {
      if (!window._seekDragging || !window._seekDragging()) {
        transportCurrent.textContent = formatTime(t);
        transportSeek.value = Math.round((t / dur) * 1000);
      }
      document.querySelectorAll(".timeline-track").forEach(track => {
        let ph = track.querySelector(".timeline-playhead");
        if (!ph) {
          ph = document.createElement("div");
          ph.className = "timeline-playhead";
          track.appendChild(ph);
        }
        ph.style.left = (dur > 0 ? (t / dur) * 100 : 0) + "%";
      });
    };
    transportTotal.textContent = formatTime(durationSec);

    const loadPromises = layers.filter(l => l.has_audio && l.volume_db > -55).map(l => {
      const url = `/api/audio/${jobId}/layer/${encodeURIComponent(l.name)}`;
      return mixer.addLayer(l.name, url, {
        volume_db: l.volume_db,
        pan: l.pan || 0,
        muted: l.volume_db <= -55,
        low_pass_hz: l.effects?.low_pass_hz || 20000,
        reverb_amount: l.effects?.reverb_amount || 0,
        swell_amount: l.swell_amount || 0,
        swell_period_sec: l.swell_period_sec || 20,
        start_sec: l.start_sec || 0,
        end_sec: l.end_sec || 0,
      }).catch(err => console.warn(`Failed to load layer "${l.name}":`, err));
    });

    await Promise.all(loadPromises);

    liveTransport.classList.remove("hidden");
    audioPlayer.classList.add("hidden");
    mixerBadge.classList.remove("hidden");

    mixer.play();
    iconPlay.classList.add("hidden");
    iconPause.classList.remove("hidden");
  }

  function showPlayer(data) {
    playerPanel.classList.remove("hidden");
    playerPrompt.textContent = `"${data.prompt}"`;
    btnDownload.onclick = () => finalizeAndDownload(data.job_id);
    if (data.root_key) currentRootKey = data.root_key;
    if (data.layers && data.layers.length) {
      const durationSec = (data.duration || 5) * 60;
      currentTrackDuration = durationSec;
      renderLayers(data.layers);
      initMixer(data.job_id, data.layers, durationSec).catch(err => {
        console.warn("LiveMixer init failed, falling back to audio element:", err);
        audioPlayer.classList.remove("hidden");
        liveTransport.classList.add("hidden");
        mixerBadge.classList.add("hidden");
        audioPlayer.src = `/api/audio/${data.job_id}?t=${Date.now()}`;
        audioPlayer.load();
      });
    } else {
      audioPlayer.classList.remove("hidden");
      liveTransport.classList.add("hidden");
      mixerBadge.classList.add("hidden");
      audioPlayer.src = `/api/audio/${data.job_id}?t=${Date.now()}`;
      audioPlayer.load();
    }
    aiFeedbackPanel.classList.remove("hidden");
    aiFeedbackResult.classList.add("hidden");
    partsPanel.classList.remove("hidden");
    loadParts();
  }

  // ── Layer Inspector ────────────────────────────

  function renderLayers(layers) {
    currentLayers = layers;
    layersPanel.classList.remove("hidden");
    const keyBadge = currentRootKey ? ` · Key: ${escapeHtml(currentRootKey)}` : "";
    layersCount.textContent = `(${layers.length}${keyBadge})`;

    const typeIcons = { base: "\u{1F30A}", mid: "\u{1F33F}", detail: "\u2728", musical: "\u{1F3B5}" };
    const typeLabels = { base: "Base", mid: "Mid", detail: "Detail", musical: "Musical" };

    let html = layers.map((l, i) => {
      const icon = typeIcons[l.layer_type] || "\u{1F50A}";
      const label = typeLabels[l.layer_type] || l.layer_type;
      const isMuted = l.volume_db <= -55;
      const statusDot = l.has_audio ? "ready" : "missing";
      const eName = escapeHtml(l.name);
      const vol = isMuted ? -60 : l.volume_db;
      const pan = l.pan || 0;
      const reverb = l.effects ? (l.effects.reverb_amount || 0) : 0;
      const lpHz = l.effects ? (l.effects.low_pass_hz || 20000) : 20000;
      const pitchSt = l.pitch_shift_semitones || 0;
      const swellAmt = Math.round((l.swell_amount || 0) * 100);
      const swellPeriod = l.swell_period_sec || 20;
      const panLabel = pan === 0 ? "C" : pan < 0 ? `L${Math.abs(Math.round(pan * 100))}` : `R${Math.round(pan * 100)}`;
      const muteBtn = isMuted
        ? `<button class="layer-btn layer-btn-unmute" data-action="unmute" data-layer="${eName}" title="Unmute">Unmute</button>`
        : `<button class="layer-btn layer-btn-mute" data-action="mute" data-layer="${eName}" title="Mute">Mute</button>`;
      const indepLoop = l.independent_loop || false;
      const startSec = l.start_sec || 0;
      const endSec = l.end_sec || 0;
      const trackDur = currentTrackDuration || 300;
      const startPct = (startSec / trackDur) * 100;
      const endPct = endSec > 0 ? (endSec / trackDur) * 100 : 100;
      const soloActive = mixer && mixer.isSoloed(l.name);

      return `
        <div class="layer-card ${isMuted ? "muted" : ""}" data-layer-name="${eName}" data-layer-index="${i}">
          <div class="layer-header">
            <span class="layer-icon">${icon}</span>
            <span class="layer-name">${eName}</span>
            <span class="layer-type-badge ${l.layer_type}">${label}</span>
            <button class="layer-solo-btn ${soloActive ? "active" : ""}" data-layer="${eName}" title="Solo — hear only this layer">S</button>
            <span class="layer-status ${statusDot}"></span>
          </div>
          <div class="layer-prompt">${escapeHtml(l.elevenlabs_prompt || "No prompt")}</div>
          <div class="layer-timeline" data-layer="${eName}" title="When this layer is active within the track">
            <div class="timeline-track">
              <div class="timeline-fill" style="left:${startPct}%;width:${endPct - startPct}%"></div>
            </div>
            <div class="timeline-inputs">
              <label class="tl-label">In: <input type="number" class="tl-input tl-start" data-layer="${eName}" value="${startSec > 0 ? (startSec / 60).toFixed(1) : "0"}" min="0" max="${(trackDur / 60).toFixed(0)}" step="0.5"> min</label>
              <label class="tl-label">Out: <input type="number" class="tl-input tl-end" data-layer="${eName}" value="${endSec > 0 ? (endSec / 60).toFixed(1) : ""}" min="0" max="${(trackDur / 60).toFixed(0)}" step="0.5" placeholder="end"> min</label>
            </div>
          </div>
          <div class="layer-sliders">
            <div class="slider-row"><span class="slider-label">Vol</span><input type="range" class="layer-slider slider-vol" data-param="volume_db" data-layer="${eName}" min="-40" max="0" step="1" value="${vol}"><span class="slider-value" data-display="volume_db">${isMuted ? "MUTE" : vol + " dB"}</span></div>
            <div class="slider-row"><span class="slider-label">Pan</span><input type="range" class="layer-slider slider-pan" data-param="pan" data-layer="${eName}" min="-100" max="100" step="5" value="${Math.round(pan * 100)}"><span class="slider-value" data-display="pan">${panLabel}</span></div>
            <div class="slider-row"><span class="slider-label">Reverb</span><input type="range" class="layer-slider slider-reverb" data-param="reverb_amount" data-layer="${eName}" min="0" max="100" step="5" value="${Math.round(reverb * 100)}"><span class="slider-value" data-display="reverb_amount">${Math.round(reverb * 100)}%</span></div>
            <div class="slider-row"><span class="slider-label">LP</span><input type="range" class="layer-slider slider-lp" data-param="low_pass_hz" data-layer="${eName}" min="500" max="20000" step="500" value="${lpHz}"><span class="slider-value" data-display="low_pass_hz">${lpHz >= 20000 ? "Off" : (lpHz / 1000).toFixed(1) + "k"}</span></div>
            <div class="slider-row"><span class="slider-label">Pitch</span><input type="range" class="layer-slider slider-pitch" data-param="pitch_shift_semitones" data-layer="${eName}" min="-6" max="6" step="1" value="${pitchSt}"><span class="slider-value" data-display="pitch_shift_semitones">${pitchSt === 0 ? "0" : (pitchSt > 0 ? "+" + pitchSt : pitchSt) + "st"}</span><span class="detected-key" data-key-for="${eName}"></span></div>
            <div class="slider-row"><span class="slider-label">Swell</span><input type="range" class="layer-slider slider-swell" data-param="swell_amount" data-layer="${eName}" min="0" max="100" step="5" value="${swellAmt}"><span class="slider-value" data-display="swell_amount">${swellAmt === 0 ? "Off" : swellAmt + "%"}</span></div>
          </div>
          <label class="layer-toggle" title="Loop this layer on its own cycle for natural variation"><input type="checkbox" class="indep-loop-cb" data-layer="${eName}" ${indepLoop ? "checked" : ""}><span class="layer-toggle-text">Independent loop</span></label>
          <div class="layer-actions">
            ${muteBtn}
            <button class="layer-btn layer-btn-reroll" data-action="regenerate" data-layer="${eName}" title="Re-roll">Re-roll</button>
            <button class="layer-btn layer-btn-regen" data-action="show-regen" data-layer="${eName}" title="Regenerate with new prompt">New Sound</button>
            <button class="layer-btn layer-btn-remove" data-action="remove" data-layer="${eName}" title="Remove layer">Remove</button>
          </div>
          <div class="layer-regen-form hidden" data-regen-for="${eName}">
            <textarea class="regen-prompt-input" rows="2" placeholder="Describe the sound you want..."></textarea>
            <div class="regen-form-row">
              <select class="regen-type-select"><option value="">Same type</option><option value="base">SFX: Base</option><option value="mid">SFX: Mid</option><option value="detail">SFX: Detail</option><option value="musical">Musical</option></select>
              <button class="layer-btn layer-btn-regen regen-submit" data-layer="${eName}">Generate</button>
              <button class="layer-btn layer-btn-mute regen-cancel" data-layer="${eName}">Cancel</button>
            </div>
          </div>
        </div>`;
    }).join("");

    html += `
      <div class="layer-tools">
        <button id="detect-keys-btn" class="layer-btn layer-btn-detect" title="Analyze each layer's musical key">Detect Keys</button>
        <button id="auto-harmonize-btn" class="layer-btn layer-btn-regen" title="Auto pitch-shift tonal layers to match root key">Auto-Harmonize</button>
      </div>
      <div class="add-layer-section">
        <button id="add-layer-toggle" class="btn btn-add-layer">+ Add Layer</button>
        <div id="add-layer-form" class="add-layer-form hidden">
          ${buildSoundPaletteHTML()}
          <input type="text" id="add-layer-name" placeholder="Layer name" class="add-input">
          <div class="add-type-row"><select id="add-layer-type" class="add-select"><option value="base">Base</option><option value="mid" selected>Mid</option><option value="detail">Detail</option><option value="musical">Musical</option></select></div>
          <textarea id="add-layer-prompt" rows="2" placeholder="Describe the sound you want, or pick from the palette above..." class="add-input"></textarea>
          <div class="add-actions"><button id="add-layer-cancel" class="layer-btn layer-btn-mute">Cancel</button><button id="add-layer-submit" class="layer-btn layer-btn-regen">Add</button></div>
        </div>
      </div>`;

    layersList.innerHTML = html;

    layersList.querySelectorAll(".layer-prompt").forEach((el) => {
      el.addEventListener("click", () => el.classList.toggle("expanded"));
    });

    layersList.querySelectorAll(".layer-btn[data-action]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const action = btn.dataset.action;
        const layerName = btn.dataset.layer;
        if (action === "show-regen") {
          const form = layersList.querySelector(`[data-regen-for="${layerName}"]`);
          if (form) form.classList.toggle("hidden");
          return;
        }
        performLayerAction(action, layerName);
      });
    });

    layersList.querySelectorAll(".regen-submit").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const layerName = btn.dataset.layer;
        const form = layersList.querySelector(`[data-regen-for="${layerName}"]`);
        const prompt = form.querySelector(".regen-prompt-input").value.trim();
        const newType = form.querySelector(".regen-type-select").value || null;
        if (!prompt) { form.querySelector(".regen-prompt-input").focus(); return; }
        performRegenWithPrompt(layerName, prompt, newType);
        form.classList.add("hidden");
      });
    });

    layersList.querySelectorAll(".regen-cancel").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const layerName = btn.dataset.layer;
        const form = layersList.querySelector(`[data-regen-for="${layerName}"]`);
        if (form) form.classList.add("hidden");
      });
    });

    layersList.querySelectorAll(".layer-slider").forEach((slider) => {
      slider.addEventListener("input", () => { updateSliderDisplay(slider); queueSliderUpdate(slider); });
    });

    layersList.querySelectorAll(".indep-loop-cb").forEach((cb) => {
      cb.addEventListener("change", () => {
        const layerName = cb.dataset.layer;
        if (!pendingSliderUpdates[layerName]) pendingSliderUpdates[layerName] = {};
        pendingSliderUpdates[layerName]["independent_loop"] = cb.checked;
        if (sliderDebounceTimers[layerName]) clearTimeout(sliderDebounceTimers[layerName]);
        sliderDebounceTimers[layerName] = setTimeout(() => syncParamsToServer(layerName), 400);
      });
    });

    const addToggle = document.getElementById("add-layer-toggle");
    const addForm = document.getElementById("add-layer-form");
    if (addToggle && addForm) {
      addToggle.addEventListener("click", () => { addForm.classList.toggle("hidden"); addToggle.classList.toggle("hidden"); });
      document.getElementById("add-layer-cancel").addEventListener("click", () => { addForm.classList.add("hidden"); addToggle.classList.remove("hidden"); });
      document.getElementById("add-layer-submit").addEventListener("click", () => performAddLayer());

      addForm.querySelectorAll(".palette-tab").forEach(tab => {
        tab.addEventListener("click", () => {
          addForm.querySelectorAll(".palette-tab").forEach(t => t.classList.remove("active"));
          addForm.querySelectorAll(".palette-chips").forEach(c => c.classList.add("hidden"));
          tab.classList.add("active");
          const chips = addForm.querySelector(`[data-cat-chips="${tab.dataset.cat}"]`);
          if (chips) chips.classList.remove("hidden");
        });
      });

      addForm.querySelectorAll(".palette-chip").forEach(chip => {
        chip.addEventListener("click", () => {
          document.getElementById("add-layer-name").value = chip.dataset.pname;
          document.getElementById("add-layer-type").value = chip.dataset.ptype;
          document.getElementById("add-layer-prompt").value = chip.dataset.pprompt;
        });
      });
    }

    // Solo buttons
    layersList.querySelectorAll(".layer-solo-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const name = btn.dataset.layer;
        if (mixer) {
          mixer.solo(name);
          layersList.querySelectorAll(".layer-solo-btn").forEach(b => {
            b.classList.toggle("active", mixer.isSoloed(b.dataset.layer));
          });
        }
      });
    });

    // Timeline inputs
    layersList.querySelectorAll(".tl-start").forEach(input => {
      input.addEventListener("change", () => {
        const name = input.dataset.layer;
        const startSec = parseFloat(input.value || 0) * 60;
        if (mixer) mixer.setTiming(name, startSec, _getEndSec(name));
        syncTimingToServer(name, startSec, _getEndSec(name));
        updateTimelineFill(name);
      });
    });
    layersList.querySelectorAll(".tl-end").forEach(input => {
      input.addEventListener("change", () => {
        const name = input.dataset.layer;
        const endSec = input.value ? parseFloat(input.value) * 60 : 0;
        if (mixer) mixer.setTiming(name, _getStartSec(name), endSec);
        syncTimingToServer(name, _getStartSec(name), endSec);
        updateTimelineFill(name);
      });
    });

    function _getStartSec(name) {
      const el = layersList.querySelector(`.tl-start[data-layer="${name}"]`);
      return el ? parseFloat(el.value || 0) * 60 : 0;
    }
    function _getEndSec(name) {
      const el = layersList.querySelector(`.tl-end[data-layer="${name}"]`);
      return el && el.value ? parseFloat(el.value) * 60 : 0;
    }
    function updateTimelineFill(name) {
      const tl = layersList.querySelector(`.layer-timeline[data-layer="${name}"]`);
      if (!tl) return;
      const fill = tl.querySelector(".timeline-fill");
      const startSec = _getStartSec(name);
      const endSec = _getEndSec(name);
      const dur = currentTrackDuration || 300;
      const startPct = (startSec / dur) * 100;
      const endPct = endSec > 0 ? (endSec / dur) * 100 : 100;
      fill.style.left = startPct + "%";
      fill.style.width = (endPct - startPct) + "%";
    }
    function syncTimingToServer(name, startSec, endSec) {
      if (!currentJobId) return;
      fetch(`/api/layer-action/${currentJobId}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "update_params", layer_name: name, params: { start_sec: startSec, end_sec: endSec } }),
      }).catch(() => {});
    }

    const detectBtn = document.getElementById("detect-keys-btn");
    if (detectBtn) detectBtn.addEventListener("click", () => detectKeysForJob());
    const harmonizeBtn = document.getElementById("auto-harmonize-btn");
    if (harmonizeBtn) harmonizeBtn.addEventListener("click", () => autoHarmonize());

    const suggestBtn = document.getElementById("btn-ai-suggest");
    if (suggestBtn) {
      suggestBtn.onclick = () => fetchAiSuggestions();
    }
  }

  const soundPalette = {
    "Nature": [
      { name: "Gentle Rain", type: "base", prompt: "Soft steady rain falling on leaves and wet ground, natural outdoor recording" },
      { name: "Forest Birds", type: "detail", prompt: "Distant songbirds in a forest canopy, varied species, occasional calls" },
      { name: "Ocean Waves", type: "base", prompt: "Slow ocean waves breaking gently on a sandy shore, rhythmic and calming" },
      { name: "Wind Through Trees", type: "mid", prompt: "Gentle breeze rustling through pine trees, soft whooshing" },
      { name: "Creek Babble", type: "mid", prompt: "Small creek babbling over smooth stones, gentle water flow" },
      { name: "Thunder Distant", type: "detail", prompt: "Distant rolling thunder, low rumbles far away, no sharp cracks" },
      { name: "Crickets Night", type: "base", prompt: "Crickets chirping on a warm summer night, continuous gentle rhythm" },
    ],
    "Urban": [
      { name: "City Traffic", type: "base", prompt: "Distant city traffic hum, muffled cars passing, urban ambience" },
      { name: "Cafe Chatter", type: "mid", prompt: "Soft indistinct cafe background conversation, clinking cups and plates" },
      { name: "Train Station", type: "base", prompt: "Train station ambient sounds, distant announcements, footsteps, echoing hall" },
      { name: "Vinyl Crackle", type: "detail", prompt: "Warm vinyl record surface noise, gentle crackle and pop, analog warmth" },
    ],
    "Musical": [
      { name: "Piano Ambient", type: "musical", prompt: "Slow ambient piano chords in C major, reverberant, spacious, gentle sustain" },
      { name: "Synth Pad", type: "musical", prompt: "Warm analog synthesizer pad, slowly evolving, rich harmonics, dreamy" },
      { name: "Acoustic Guitar", type: "musical", prompt: "Gentle fingerpicked acoustic guitar, slow arpeggios, warm tone, intimate" },
      { name: "Cello Drone", type: "musical", prompt: "Deep cello sustained note, slow bow, rich overtones, melancholic" },
      { name: "Music Box", type: "detail", prompt: "Delicate music box melody, simple lullaby, tinkling and ethereal" },
    ],
    "Atmospheric": [
      { name: "Deep Drone", type: "base", prompt: "Deep sub-bass drone, slowly evolving texture, cinematic low-end rumble" },
      { name: "Ethereal Shimmer", type: "detail", prompt: "High-frequency shimmering texture, crystalline sparkle, airy and bright" },
      { name: "Breathing Room", type: "base", prompt: "Empty room tone, subtle air conditioning hum, interior ambience" },
      { name: "Fire Crackle", type: "mid", prompt: "Wood fire crackling softly, occasional pop, warm campfire or fireplace" },
      { name: "Wind Chimes", type: "detail", prompt: "Distant wind chimes in a gentle breeze, metallic tinkling, sparse and random" },
    ],
  };

  function buildSoundPaletteHTML() {
    let html = '<div class="sound-palette"><div class="palette-label">Quick picks:</div><div class="palette-tabs">';
    const categories = Object.keys(soundPalette);
    categories.forEach((cat, i) => {
      html += `<button class="palette-tab ${i === 0 ? 'active' : ''}" data-cat="${cat}">${cat}</button>`;
    });
    html += '</div>';
    categories.forEach((cat, i) => {
      html += `<div class="palette-chips ${i === 0 ? '' : 'hidden'}" data-cat-chips="${cat}">`;
      soundPalette[cat].forEach(s => {
        html += `<button class="palette-chip" data-pname="${escapeHtml(s.name)}" data-ptype="${s.type}" data-pprompt="${escapeHtml(s.prompt)}" title="${escapeHtml(s.prompt)}">${escapeHtml(s.name)}</button>`;
      });
      html += '</div>';
    });
    html += '</div>';
    return html;
  }

  async function fetchAiSuggestions() {
    if (!currentJobId) return;
    const btn = document.getElementById("btn-ai-suggest");
    const container = document.getElementById("ai-suggestions");
    if (!btn || !container) return;
    btn.disabled = true;
    btn.textContent = "Thinking...";
    container.classList.add("hidden");

    try {
      const res = await fetch(`/api/suggest-layers/${currentJobId}`, { method: "POST" });
      const data = await res.json();
      if (data.error) { addChatMessage("system", `Suggest error: ${data.error}`); return; }

      container.innerHTML = data.suggestions.map(s => `
        <div class="suggestion-card">
          <div class="suggestion-header">
            <span class="suggestion-name">${escapeHtml(s.name)}</span>
            <span class="layer-type-badge ${s.type}">${s.type}</span>
          </div>
          <div class="suggestion-prompt">${escapeHtml(s.prompt)}</div>
          <div class="suggestion-reason">${escapeHtml(s.reason)}</div>
          <button class="layer-btn layer-btn-regen suggestion-add" data-sname="${escapeHtml(s.name)}" data-stype="${s.type}" data-sprompt="${escapeHtml(s.prompt)}">+ Add This</button>
        </div>
      `).join("");
      container.classList.remove("hidden");

      container.querySelectorAll(".suggestion-add").forEach(btn => {
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          btn.textContent = "Adding...";
          try {
            const res = await fetch(`/api/layer-action/${currentJobId}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ action: "add", name: btn.dataset.sname, layer_type: btn.dataset.stype, prompt: btn.dataset.sprompt }),
            });
            const data = await res.json();
            if (data.error) addChatMessage("system", `Error: ${data.error}`);
            else {
              addChatMessage("system", data.changes);
              if (data.layers) renderLayers(data.layers);
              if (mixer) {
                const url = `/api/audio/${currentJobId}/layer/${encodeURIComponent(btn.dataset.sname)}?t=${Date.now()}`;
                mixer.addLayer(btn.dataset.sname, url, { volume_db: -6 }).catch(() => {});
              } else {
                audioPlayer.src = data.audio_url; audioPlayer.load(); audioPlayer.play().catch(() => {});
              }
            }
          } catch (err) { addChatMessage("system", `Error: ${err.message}`); }
        });
      });
    } catch (err) { addChatMessage("system", `Suggest failed: ${err.message}`); }
    btn.disabled = false;
    btn.textContent = "AI Suggest Layers";
  }

  async function detectKeysForJob() {
    if (!currentJobId) return;
    const btn = document.getElementById("detect-keys-btn");
    if (btn) { btn.disabled = true; btn.textContent = "Analyzing..."; }
    try {
      const res = await fetch(`/api/detect-keys/${currentJobId}`, { method: "POST" });
      const data = await res.json();
      if (data.error) { addChatMessage("system", `Key detection error: ${data.error}`); return; }
      if (data.root_key) currentRootKey = data.root_key;
      for (const [name, info] of Object.entries(data.keys)) {
        const el = layersList.querySelector(`[data-key-for="${escapeHtml(name)}"]`);
        if (el) {
          if (info.tonal) { el.textContent = info.key; el.title = `Confidence: ${(info.confidence * 100).toFixed(0)}%`; el.classList.add("key-tonal"); }
          else { el.textContent = "noise"; el.title = "Non-tonal"; el.classList.add("key-noise"); }
        }
      }
      const keyBadge = currentRootKey ? ` · Key: ${escapeHtml(currentRootKey)}` : "";
      layersCount.textContent = `(${currentLayers.length}${keyBadge})`;
    } catch (err) { addChatMessage("system", `Key detection failed: ${err.message}`); }
    if (btn) { btn.disabled = false; btn.textContent = "Detect Keys"; }
  }

  async function autoHarmonize() {
    if (!currentJobId) return;
    const btn = document.getElementById("auto-harmonize-btn");
    if (btn) { btn.disabled = true; btn.textContent = "Harmonizing..."; }
    try {
      const res = await fetch(`/api/auto-harmonize/${currentJobId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ root_key: currentRootKey || "" }) });
      const data = await res.json();
      if (data.error) { addChatMessage("system", `Harmonize error: ${data.error}`); }
      else {
        if (data.root_key) currentRootKey = data.root_key;
        addChatMessage("system", `Harmonized to ${data.root_key}`);
        audioPlayer.src = data.audio_url; audioPlayer.load(); audioPlayer.play().catch(() => {});
        if (data.layers) renderLayers(data.layers);
      }
    } catch (err) { addChatMessage("system", `Harmonize failed: ${err.message}`); }
    if (btn) { btn.disabled = false; btn.textContent = "Auto-Harmonize"; }
  }

  function updateSliderDisplay(slider) {
    const param = slider.dataset.param;
    const val = parseFloat(slider.value);
    const card = slider.closest(".layer-card");
    const display = card.querySelector(`[data-display="${param}"]`);
    if (!display) return;
    if (param === "volume_db") display.textContent = val <= -40 ? "MUTE" : val + " dB";
    else if (param === "pan") { const p = val / 100; display.textContent = p === 0 ? "C" : p < 0 ? `L${Math.abs(val)}` : `R${val}`; }
    else if (param === "reverb_amount") display.textContent = val + "%";
    else if (param === "low_pass_hz") display.textContent = val >= 20000 ? "Off" : (val / 1000).toFixed(1) + "k";
    else if (param === "pitch_shift_semitones") display.textContent = val === 0 ? "0" : (val > 0 ? "+" + val : val) + "st";
    else if (param === "swell_amount") display.textContent = val === 0 ? "Off" : val + "%";
  }

  // Params that the mixer can handle instantly (no server round-trip)
  const LIVE_PARAMS = new Set(["volume_db", "pan", "reverb_amount", "low_pass_hz", "swell_amount"]);

  function queueSliderUpdate(slider) {
    const layerName = slider.dataset.layer;
    const param = slider.dataset.param;
    let val = parseFloat(slider.value);
    if (param === "pan") val = val / 100;
    else if (param === "reverb_amount") val = val / 100;
    else if (param === "swell_amount") val = val / 100;

    // If mixer is active and this is a live-mixable param, apply instantly
    if (mixer && LIVE_PARAMS.has(param)) {
      if (param === "volume_db") mixer.setVolume(layerName, val);
      else if (param === "pan") mixer.setPan(layerName, val);
      else if (param === "reverb_amount") mixer.setReverb(layerName, val);
      else if (param === "low_pass_hz") mixer.setLowPass(layerName, val);
      else if (param === "swell_amount") mixer.setSwell(layerName, val, 20);

      // Still sync to server in background (debounced, no re-render needed)
      if (!pendingSliderUpdates[layerName]) pendingSliderUpdates[layerName] = {};
      pendingSliderUpdates[layerName][param] = val;
      if (sliderDebounceTimers[layerName]) clearTimeout(sliderDebounceTimers[layerName]);
      sliderDebounceTimers[layerName] = setTimeout(() => syncParamsToServer(layerName), 2000);
      return;
    }

    // For non-live params (pitch), use the server round-trip
    if (!pendingSliderUpdates[layerName]) pendingSliderUpdates[layerName] = {};
    pendingSliderUpdates[layerName][param] = val;
    if (sliderDebounceTimers[layerName]) clearTimeout(sliderDebounceTimers[layerName]);
    sliderDebounceTimers[layerName] = setTimeout(() => flushSliderUpdate(layerName, layerName), 800);
  }

  async function syncParamsToServer(layerName) {
    const params = pendingSliderUpdates[layerName];
    if (!params || !currentJobId) return;
    delete pendingSliderUpdates[layerName];
    try {
      await fetch(`/api/layer-action/${currentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "update_params", layer_name: layerName, params }),
      });
    } catch (err) { console.warn("Background sync failed:", err); }
  }

  async function flushSliderUpdate(key, layerName) {
    const params = pendingSliderUpdates[key];
    if (!params || !currentJobId) return;
    delete pendingSliderUpdates[key];
    const card = layersList.querySelector(`[data-layer-name="${layerName}"]`);
    if (card) card.classList.add("layer-loading");
    try {
      const res = await fetch(`/api/layer-action/${currentJobId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "update_params", layer_name: layerName, params }) });
      const data = await res.json();
      if (card) card.classList.remove("layer-loading");
      if (data.error) addChatMessage("system", `Error: ${data.error}`);
      else if (!mixer) { audioPlayer.src = data.audio_url; audioPlayer.load(); audioPlayer.play().catch(() => {}); }
      // If mixer is active, we've already applied live — server render is just for saving state
    } catch (err) { if (card) card.classList.remove("layer-loading"); addChatMessage("system", `Error: ${err.message}`); }
  }

  async function performRegenWithPrompt(layerName, prompt, newType) {
    if (!currentJobId || layerActionPending) return;
    layerActionPending = true;
    layersList.querySelectorAll(".layer-btn").forEach((b) => (b.disabled = true));
    const card = layersList.querySelector(`[data-layer-name="${layerName}"]`);
    if (card) card.classList.add("layer-loading");
    addChatMessage("user", `Regenerate "${layerName}": ${prompt}`);
    try {
      const res = await fetch(`/api/layer-action/${currentJobId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "regenerate_with_prompt", layer_name: layerName, prompt, layer_type: newType }) });
      const data = await res.json();
      if (data.error) addChatMessage("system", `Error: ${data.error}`);
      else {
        addChatMessage("system", data.changes);
        if (data.layers) renderLayers(data.layers);
        if (mixer) {
          const url = `/api/audio/${currentJobId}/layer/${encodeURIComponent(layerName)}?t=${Date.now()}`;
          mixer.reloadLayer(layerName, url).catch(() => {});
        } else {
          audioPlayer.src = data.audio_url; audioPlayer.load(); audioPlayer.play().catch(() => {});
        }
      }
    } catch (err) { addChatMessage("system", `Error: ${err.message}`); }
    layerActionPending = false;
    layersList.querySelectorAll(".layer-btn").forEach((b) => (b.disabled = false));
  }

  async function performLayerAction(action, layerName) {
    if (!currentJobId || layerActionPending) return;

    // Mute/unmute can be instant via mixer
    if (mixer && (action === "mute" || action === "unmute")) {
      mixer.setMute(layerName, action === "mute");
      // Sync to server in background
      const body = { action, layer_name: layerName };
      if (action === "unmute") body.restore_volume = -12.0;
      fetch(`/api/layer-action/${currentJobId}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(r => r.json()).then(data => {
        if (data.layers) renderLayers(data.layers);
      }).catch(() => {});
      return;
    }

    layerActionPending = true;
    const body = { action, layer_name: layerName };
    if (action === "unmute") body.restore_volume = -12.0;
    layersList.querySelectorAll(".layer-btn").forEach((b) => (b.disabled = true));
    const targetCard = layersList.querySelector(`[data-action="${action}"][data-layer="${layerName}"]`);
    if (targetCard) { const card = targetCard.closest(".layer-card"); if (card) card.classList.add("layer-loading"); }
    try {
      const res = await fetch(`/api/layer-action/${currentJobId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json();
      if (data.error) addChatMessage("system", `Error: ${data.error}`);
      else {
        addChatMessage("system", data.changes);
        if (data.layers) renderLayers(data.layers);
        if (mixer && action === "remove") {
          mixer.removeLayer(layerName);
        } else if (!mixer) {
          audioPlayer.src = data.audio_url; audioPlayer.load(); audioPlayer.play().catch(() => {});
        }
      }
    } catch (err) { addChatMessage("system", `Error: ${err.message}`); }
    layerActionPending = false;
    layersList.querySelectorAll(".layer-btn").forEach((b) => (b.disabled = false));
  }

  async function performAddLayer() {
    if (!currentJobId || layerActionPending) return;
    const name = document.getElementById("add-layer-name").value.trim();
    const layerType = document.getElementById("add-layer-type").value;
    const prompt = document.getElementById("add-layer-prompt").value.trim();
    if (!name || !prompt) { alert("Name and prompt are required"); return; }
    layerActionPending = true;
    const submitBtn = document.getElementById("add-layer-submit");
    submitBtn.disabled = true; submitBtn.textContent = "Generating...";
    try {
      const res = await fetch(`/api/layer-action/${currentJobId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "add", name, layer_type: layerType, prompt }) });
      const data = await res.json();
      if (data.error) addChatMessage("system", `Error: ${data.error}`);
      else {
        addChatMessage("system", data.changes);
        if (data.layers) renderLayers(data.layers);
        if (mixer) {
          const url = `/api/audio/${currentJobId}/layer/${encodeURIComponent(name)}?t=${Date.now()}`;
          mixer.addLayer(name, url, { volume_db: -6 }).catch(() => {});
        } else {
          audioPlayer.src = data.audio_url; audioPlayer.load(); audioPlayer.play().catch(() => {});
        }
        document.getElementById("add-layer-name").value = "";
        document.getElementById("add-layer-prompt").value = "";
      }
    } catch (err) { addChatMessage("system", `Error: ${err.message}`); }
    layerActionPending = false; submitBtn.disabled = false; submitBtn.textContent = "Add";
  }

  // ── Feedback Chat ─────────────────────────────
  function enableFeedback() { feedbackPanel.classList.remove("hidden"); feedbackInput.disabled = false; feedbackSend.disabled = false; }

  function addChatMessage(role, text) {
    const div = document.createElement("div");
    div.className = `feedback-message ${role}`;
    div.textContent = text;
    feedbackMessages.appendChild(div);
    feedbackMessages.scrollTop = feedbackMessages.scrollHeight;
  }

  function addStatusMessage(text) {
    const div = document.createElement("div");
    div.className = "feedback-message status"; div.innerHTML = text; div.id = "feedback-status-active";
    feedbackMessages.appendChild(div); feedbackMessages.scrollTop = feedbackMessages.scrollHeight; return div;
  }

  function removeActiveStatus() { const el = document.getElementById("feedback-status-active"); if (el) el.remove(); }

  async function submitFeedback(text) {
    if (!currentJobId || feedbackPending) return;
    feedbackPending = true; feedbackInput.disabled = true; feedbackSend.disabled = true;
    addChatMessage("user", text);
    addStatusMessage("Applying changes...");
    try {
      const res = await fetch(`/api/feedback/${currentJobId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ feedback: text }) });
      const data = await res.json();
      removeActiveStatus();
      if (data.error) addChatMessage("system", `Error: ${data.error}`);
      else {
        addChatMessage("system", `Updated! ${data.changes}`);
        if (data.layers && data.layers.length) renderLayers(data.layers);
        if (!mixer) {
          audioPlayer.src = data.audio_url; audioPlayer.load(); audioPlayer.play().catch(() => {});
        }
      }
    } catch (err) { removeActiveStatus(); addChatMessage("system", `Error: ${err.message}`); }
    feedbackPending = false; feedbackInput.disabled = false; feedbackSend.disabled = false; feedbackInput.value = "";
  }

  feedbackSend.addEventListener("click", () => { const text = feedbackInput.value.trim(); if (text) submitFeedback(text); });
  feedbackInput.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); const text = feedbackInput.value.trim(); if (text) submitFeedback(text); } });

  // ── Finalize & Download ───────────────────────
  async function finalizeAndDownload(jobId) {
    btnDownload.disabled = true; btnDownload.textContent = "Mastering...";
    try {
      const res = await fetch(`/api/finalize/${jobId}`, { method: "POST" });
      const data = await res.json();
      if (data.error) alert("Failed: " + data.error);
      else window.location.href = data.download_url;
    } catch (err) { alert("Download failed: " + err.message); }
    btnDownload.disabled = false; btnDownload.textContent = "Download WAV";
  }

  // ── Export Extended ───────────────────────────
  const btnExportExtended = document.getElementById("btn-export-extended");
  const extendedDurationEl = document.getElementById("extended-duration");
  btnExportExtended.addEventListener("click", async () => {
    if (!currentJobId) return;
    const minutes = parseInt(extendedDurationEl.value);
    btnExportExtended.disabled = true; btnExportExtended.textContent = `Exporting ${minutes} min...`;
    try {
      const res = await fetch(`/api/export-extended/${currentJobId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target_minutes: minutes }) });
      const data = await res.json();
      if (data.error) alert("Export failed: " + data.error);
      else window.location.href = data.download_url;
    } catch (err) { alert("Export failed: " + err.message); }
    btnExportExtended.disabled = false; btnExportExtended.textContent = "Export Looped";
  });

  // ── AI Feedback ──────────────────────────────
  const aiFeedbackPanel = document.getElementById("ai-feedback-panel");
  const btnAiFeedback = document.getElementById("btn-ai-feedback");
  const aiFeedbackResult = document.getElementById("ai-feedback-result");
  const aiScoreValue = document.getElementById("ai-score-value");
  const aiScoreBar = document.getElementById("ai-score-bar");
  const aiFeedbackNotes = document.getElementById("ai-feedback-notes");

  btnAiFeedback.addEventListener("click", async () => {
    if (!currentJobId) return;
    btnAiFeedback.disabled = true;
    btnAiFeedback.textContent = "Analyzing...";
    aiFeedbackResult.classList.add("hidden");

    try {
      const res = await fetch(`/api/ai-feedback/${currentJobId}`, { method: "POST" });
      const data = await res.json();
      if (data.error) {
        addChatMessage("system", `AI Feedback error: ${data.error}`);
      } else {
        const score = data.score;
        aiScoreValue.textContent = `${score}/10`;
        aiScoreValue.className = "ai-score-value " + (score >= 7 ? "score-good" : score >= 4 ? "score-ok" : "score-bad");
        aiScoreBar.style.width = (score * 10) + "%";
        aiScoreBar.className = "ai-score-bar " + (score >= 7 ? "bar-good" : score >= 4 ? "bar-ok" : "bar-bad");
        aiFeedbackNotes.innerHTML = (data.notes || []).map(n => `<li>${escapeHtml(n)}</li>`).join("");
        aiFeedbackResult.classList.remove("hidden");
      }
    } catch (err) {
      addChatMessage("system", `AI Feedback failed: ${err.message}`);
    }
    btnAiFeedback.disabled = false;
    btnAiFeedback.textContent = "Get AI Feedback";
  });

  // ── Parts Builder ──────────────────────────────
  const partsPanel = document.getElementById("parts-panel");
  const partsList = document.getElementById("parts-list");
  const partsCount = document.getElementById("parts-count");
  const btnSavePart = document.getElementById("btn-save-part");
  const partsStitchSection = document.getElementById("parts-stitch-section");
  const btnStitchParts = document.getElementById("btn-stitch-parts");
  const partsFadeIn = document.getElementById("parts-fade-in");
  const partsFadeOut = document.getElementById("parts-fade-out");

  let currentParts = [];

  function captureLayerStates() {
    const states = {};
    if (!currentLayers) return states;
    currentLayers.forEach(l => {
      const card = layersList.querySelector(`[data-layer-name="${escapeHtml(l.name)}"]`);
      if (!card) return;
      const volSlider = card.querySelector('[data-param="volume_db"]');
      const panSlider = card.querySelector('[data-param="pan"]');
      const reverbSlider = card.querySelector('[data-param="reverb_amount"]');
      const lpSlider = card.querySelector('[data-param="low_pass_hz"]');
      const pitchSlider = card.querySelector('[data-param="pitch_shift_semitones"]');
      const swellSlider = card.querySelector('[data-param="swell_amount"]');
      const muteState = l.volume_db <= -55;
      states[l.name] = {
        volume_db: volSlider ? parseFloat(volSlider.value) : l.volume_db,
        pan: panSlider ? parseFloat(panSlider.value) / 100 : l.pan || 0,
        muted: muteState,
        reverb_amount: reverbSlider ? parseFloat(reverbSlider.value) / 100 : 0.3,
        low_pass_hz: lpSlider ? parseFloat(lpSlider.value) : null,
        pitch_shift_semitones: pitchSlider ? parseInt(pitchSlider.value) : 0,
        swell_amount: swellSlider ? parseFloat(swellSlider.value) / 100 : 0,
        swell_period_sec: 20,
      };
      if (states[l.name].low_pass_hz >= 20000) states[l.name].low_pass_hz = null;
    });
    return states;
  }

  btnSavePart.addEventListener("click", () => {
    if (!currentJobId || !currentLayers.length) return;
    const partNum = currentParts.length + 1;
    const name = prompt("Part name:", `Part ${partNum}`) || `Part ${partNum}`;
    const durationStr = prompt("Duration in minutes:", "5");
    const durationMin = parseFloat(durationStr) || 5;
    const fadeInSec = partNum === 1 ? 0 : 5;

    const part = {
      name,
      duration_sec: durationMin * 60,
      layer_states: captureLayerStates(),
      added_layers: [],
      fade_in_sec: fadeInSec,
    };
    currentParts.push(part);
    renderParts();
    saveParts();
  });

  function renderParts() {
    partsCount.textContent = currentParts.length ? `(${currentParts.length})` : "";
    if (!currentParts.length) {
      partsList.innerHTML = '<p class="parts-empty">No parts yet. Adjust your layers, then save the mix as a part.</p>';
      partsStitchSection.classList.add("hidden");
      return;
    }

    const totalMin = currentParts.reduce((s, p) => s + p.duration_sec, 0) / 60;
    partsList.innerHTML = currentParts.map((p, i) => {
      const layerNames = Object.keys(p.layer_states);
      const activeCount = layerNames.filter(n => !p.layer_states[n].muted).length;
      const durationMin = (p.duration_sec / 60).toFixed(1);
      return `
        <div class="part-card" data-part-idx="${i}">
          <div class="part-header">
            <span class="part-number">${i + 1}</span>
            <input class="part-name-input" value="${escapeHtml(p.name)}" data-pidx="${i}">
            <span class="part-meta">${durationMin} min · ${activeCount}/${layerNames.length} layers</span>
          </div>
          <div class="part-controls">
            <label class="part-dur-label">Duration:
              <input type="number" class="part-dur-input" value="${durationMin}" min="0.5" max="60" step="0.5" data-pidx="${i}"> min
            </label>
            <label class="part-dur-label">Fade in:
              <input type="number" class="part-fade-input" value="${p.fade_in_sec}" min="0" max="30" step="1" data-pidx="${i}"> sec
            </label>
          </div>
          <div class="part-actions">
            <button class="layer-btn layer-btn-regen part-preview-btn" data-pidx="${i}">Preview</button>
            <button class="layer-btn part-load-btn" data-pidx="${i}" title="Load this part's mix into the layer inspector">Load Mix</button>
            <button class="layer-btn layer-btn-remove part-delete-btn" data-pidx="${i}">Delete</button>
          </div>
        </div>`;
    }).join("");
    partsList.innerHTML += `<div class="parts-total">Total: ${totalMin.toFixed(1)} min</div>`;
    partsStitchSection.classList.remove("hidden");

    partsList.querySelectorAll(".part-name-input").forEach(el => {
      el.addEventListener("change", () => { currentParts[el.dataset.pidx].name = el.value; saveParts(); });
    });
    partsList.querySelectorAll(".part-dur-input").forEach(el => {
      el.addEventListener("change", () => { currentParts[el.dataset.pidx].duration_sec = parseFloat(el.value) * 60; renderParts(); saveParts(); });
    });
    partsList.querySelectorAll(".part-fade-input").forEach(el => {
      el.addEventListener("change", () => { currentParts[el.dataset.pidx].fade_in_sec = parseFloat(el.value); saveParts(); });
    });
    partsList.querySelectorAll(".part-preview-btn").forEach(btn => {
      btn.addEventListener("click", () => previewPart(parseInt(btn.dataset.pidx)));
    });
    partsList.querySelectorAll(".part-load-btn").forEach(btn => {
      btn.addEventListener("click", () => loadPartMix(parseInt(btn.dataset.pidx)));
    });
    partsList.querySelectorAll(".part-delete-btn").forEach(btn => {
      btn.addEventListener("click", () => { currentParts.splice(parseInt(btn.dataset.pidx), 1); renderParts(); saveParts(); });
    });
  }

  async function saveParts() {
    if (!currentJobId) return;
    try {
      await fetch(`/api/parts/${currentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parts: currentParts }),
      });
    } catch (err) { console.error("Save parts error:", err); }
  }

  async function loadParts() {
    if (!currentJobId) return;
    try {
      const res = await fetch(`/api/parts/${currentJobId}`);
      const data = await res.json();
      currentParts = data.parts || [];
      renderParts();
    } catch (err) { console.error("Load parts error:", err); }
  }

  async function previewPart(idx) {
    if (!currentJobId || idx >= currentParts.length) return;
    const btn = partsList.querySelector(`.part-preview-btn[data-pidx="${idx}"]`);
    if (btn) { btn.disabled = true; btn.textContent = "Rendering..."; }
    try {
      const res = await fetch(`/api/parts/${currentJobId}/preview/${idx}`, { method: "POST" });
      const data = await res.json();
      if (data.error) { addChatMessage("system", `Part preview error: ${data.error}`); }
      else {
        audioPlayer.src = data.audio_url + "?t=" + Date.now();
        audioPlayer.load();
        audioPlayer.play().catch(() => {});
        addChatMessage("system", `Playing Part ${idx + 1} preview (${data.duration_sec.toFixed(0)}s)`);
      }
    } catch (err) { addChatMessage("system", `Preview error: ${err.message}`); }
    if (btn) { btn.disabled = false; btn.textContent = "Preview"; }
  }

  function loadPartMix(idx) {
    if (idx >= currentParts.length) return;
    const part = currentParts[idx];
    for (const [name, state] of Object.entries(part.layer_states)) {
      const card = layersList.querySelector(`[data-layer-name="${escapeHtml(name)}"]`);
      if (!card) continue;

      const setSlider = (param, value) => {
        const slider = card.querySelector(`[data-param="${param}"]`);
        if (slider) { slider.value = value; updateSliderDisplay(slider); }
      };

      if (state.muted) {
        setSlider("volume_db", -40);
      } else {
        setSlider("volume_db", state.volume_db);
      }
      setSlider("pan", Math.round((state.pan || 0) * 100));
      setSlider("reverb_amount", Math.round((state.reverb_amount || 0) * 100));
      setSlider("low_pass_hz", state.low_pass_hz || 20000);
      setSlider("pitch_shift_semitones", state.pitch_shift_semitones || 0);
      setSlider("swell_amount", Math.round((state.swell_amount || 0) * 100));
    }
    addChatMessage("system", `Loaded mix from "${part.name}" into sliders.`);
  }

  btnStitchParts.addEventListener("click", async () => {
    if (!currentJobId || !currentParts.length) return;
    btnStitchParts.disabled = true;
    btnStitchParts.textContent = "Stitching...";

    try {
      const res = await fetch(`/api/parts/${currentJobId}/stitch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          global_fade_in_sec: parseFloat(partsFadeIn.value) || 20,
          global_fade_out_sec: parseFloat(partsFadeOut.value) || 10,
        }),
      });
      const data = await res.json();
      if (data.error) {
        addChatMessage("system", `Stitch error: ${data.error}`);
      } else {
        addChatMessage("system", `Stitching ${data.part_count} parts... this may take a few minutes.`);
        startPolling(currentJobId);
      }
    } catch (err) { addChatMessage("system", `Stitch error: ${err.message}`); }
    btnStitchParts.disabled = false;
    btnStitchParts.textContent = "Stitch All Parts & Render";
  });

  // ── History ───────────────────────────────────
  async function refreshHistory() {
    try {
      const res = await fetch("/api/history");
      const history = await res.json();
      if (!history.length) { historyList.innerHTML = '<p class="history-empty">No generations yet.</p>'; return; }
      historyList.innerHTML = history.map((j) => {
        let timeStr = "";
        if (j.created_at) {
          const d = new Date(j.created_at); const diff = Date.now() - d;
          if (diff < 60000) timeStr = "just now";
          else if (diff < 3600000) timeStr = Math.floor(diff / 60000) + "m ago";
          else if (diff < 86400000) timeStr = Math.floor(diff / 3600000) + "h ago";
          else timeStr = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
        }
        const edits = j.feedback_count ? j.feedback_count + " edits" : "";
        const meta = [edits, timeStr].filter(Boolean).join(" · ");
        return `<div class="history-item" data-job-id="${j.job_id}"><span class="status-dot ${j.status}"></span><span class="prompt-text">${escapeHtml(j.prompt)}</span><span class="meta">${meta}</span></div>`;
      }).join("");
      historyList.querySelectorAll(".history-item").forEach((el) => { el.addEventListener("click", () => viewJob(el.dataset.jobId)); });
    } catch (err) { console.error("History fetch error:", err); }
  }

  async function viewJob(jobId) {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();
      if (data.prompt) promptEl.value = data.prompt;
      if (data.mode) {
        currentMode = data.mode;
        modeButtons.forEach(b => b.classList.toggle("active", b.dataset.mode === data.mode));
      }
      if (data.duration) durationEl.value = String(data.duration);
      if (data.reference_url) referenceUrlEl.value = data.reference_url;
      saveFormState();
      if (data.status === "complete") {
        currentJobId = jobId;
        progressPanel.classList.remove("hidden"); layersPanel.classList.add("hidden");
        updateProgress(data); showPlayer(data); enableFeedback();
        feedbackMessages.innerHTML = '<div class="feedback-hint">Listen, then describe what to change.</div>';
        if (data.feedback_history) data.feedback_history.forEach((entry) => { addChatMessage("user", entry.feedback); addChatMessage("system", `Updated! ${entry.changes}`); });
      } else if (data.status === "running") {
        progressPanel.classList.remove("hidden"); playerPanel.classList.add("hidden"); feedbackPanel.classList.add("hidden");
        currentJobId = jobId; startPolling(jobId);
      } else if (data.status === "error") {
        progressPanel.classList.remove("hidden"); playerPanel.classList.add("hidden"); layersPanel.classList.add("hidden"); feedbackPanel.classList.add("hidden");
        showError(`Session failed: ${data.error || "Unknown error"}`);
      }
    } catch (err) { console.error("View job error:", err); }
  }


  // ═══════════════════════════════════════════════════════
  //  TAB: Visuals
  // ═══════════════════════════════════════════════════════

  const visTrackSelect = document.getElementById("vis-track-select");
  const visTrackInfo = document.getElementById("vis-track-info");
  const visTrackPrompt = document.getElementById("vis-track-prompt");
  const visAudioPlayer = document.getElementById("vis-audio-player");
  const visImagePanel = document.getElementById("vis-image-panel");
  const imagePromptEl = document.getElementById("image-prompt");
  const btnAutoPrompt = document.getElementById("btn-auto-prompt");
  const btnGenImage = document.getElementById("btn-gen-image");
  const btnRegenImage = document.getElementById("btn-regen-image");
  const imagePreview = document.getElementById("image-preview");
  const previewImg = document.getElementById("preview-img");
  const visAnimatePanel = document.getElementById("vis-animate-panel");
  const visExportPanel = document.getElementById("vis-export-panel");
  const videoDurationEl = document.getElementById("video-duration");
  const motionPromptEl = document.getElementById("motion-prompt");
  const motionPromptGroup = document.getElementById("motion-prompt-group");
  const btnCreateClip = document.getElementById("btn-create-clip");
  const clipProgress = document.getElementById("clip-progress");
  const clipProgressText = document.getElementById("clip-progress-text");
  const clipPreview = document.getElementById("clip-preview");
  const clipVideo = document.getElementById("clip-video");
  const btnExportVideo = document.getElementById("btn-export-video");
  const exportProgress = document.getElementById("export-progress");
  const exportProgressText = document.getElementById("export-progress-text");
  const videoDownload = document.getElementById("video-download");
  const videoDownloadLink = document.getElementById("video-download-link");
  const vmodeButtons = document.querySelectorAll("[data-vmode]");

  let visCurrentJobId = null;
  let currentVideoMode = "ai";

  vmodeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      vmodeButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentVideoMode = btn.dataset.vmode;
      motionPromptGroup.classList.toggle("hidden", currentVideoMode === "kenburns");
    });
  });

  async function refreshVisTrackList() {
    try {
      const res = await fetch("/api/history");
      const history = await res.json();
      const completeTracks = history.filter((j) => j.status === "complete");

      const prev = visTrackSelect.value;
      visTrackSelect.innerHTML = '<option value="">— Choose a soundscape —</option>';
      completeTracks.forEach((j) => {
        const opt = document.createElement("option");
        opt.value = j.job_id;
        let timeStr = "";
        if (j.created_at) {
          const d = new Date(j.created_at);
          const diff = Date.now() - d;
          if (diff < 3600000) timeStr = Math.floor(diff / 60000) + "m ago";
          else if (diff < 86400000) timeStr = Math.floor(diff / 3600000) + "h ago";
          else timeStr = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
        }
        opt.textContent = `${j.prompt.substring(0, 60)}${j.prompt.length > 60 ? "..." : ""} (${timeStr})`;
        visTrackSelect.appendChild(opt);
      });
      if (prev) visTrackSelect.value = prev;
    } catch (err) {
      console.error("Failed to load tracks:", err);
    }
  }

  visTrackSelect.addEventListener("change", async () => {
    const jobId = visTrackSelect.value;
    if (!jobId) {
      visTrackInfo.classList.add("hidden");
      visImagePanel.classList.add("hidden");
      visAnimatePanel.classList.add("hidden");
      visExportPanel.classList.add("hidden");
      visCurrentJobId = null;
      return;
    }

    visCurrentJobId = jobId;

    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();

      visTrackPrompt.textContent = `"${data.prompt}"`;
      visAudioPlayer.src = `/api/audio/${jobId}?t=${Date.now()}`;
      visAudioPlayer.load();
      visTrackInfo.classList.remove("hidden");
      visImagePanel.classList.remove("hidden");

      imagePromptEl.value = data.visual_image_prompt || "";
      motionPromptEl.value = "";

      if (data.visual_image_url) {
        previewImg.src = data.visual_image_url + "?t=" + Date.now();
        imagePreview.classList.remove("hidden");
        visAnimatePanel.classList.remove("hidden");
      } else {
        imagePreview.classList.add("hidden");
        visAnimatePanel.classList.add("hidden");
      }

      if (data.visual_clip_url) {
        clipVideo.src = data.visual_clip_url + "?t=" + Date.now();
        clipPreview.classList.remove("hidden");
        visExportPanel.classList.remove("hidden");
      } else {
        clipPreview.classList.add("hidden");
        visExportPanel.classList.add("hidden");
      }

      if (data.visual_video_url) {
        videoDownloadLink.href = data.visual_video_url;
        videoDownload.classList.remove("hidden");
      } else {
        videoDownload.classList.add("hidden");
      }
    } catch (err) {
      console.error("Failed to load track info:", err);
    }
  });

  // ── Auto prompt ───────────────────────────────
  btnAutoPrompt.addEventListener("click", async () => {
    if (!visCurrentJobId) { alert("Select a track first"); return; }
    btnAutoPrompt.disabled = true;
    btnAutoPrompt.textContent = "Writing...";
    try {
      const res = await fetch(`/api/visual/auto-prompt/${visCurrentJobId}`, { method: "POST" });
      const data = await res.json();
      if (data.error) alert("Auto-prompt failed: " + data.error);
      else imagePromptEl.value = data.image_prompt;
    } catch (err) { alert("Auto-prompt failed: " + err.message); }
    btnAutoPrompt.disabled = false;
    btnAutoPrompt.textContent = "Auto-Write Prompt";
  });

  // ── Image generation ──────────────────────────
  btnGenImage.addEventListener("click", () => generateImage());
  btnRegenImage.addEventListener("click", () => generateImage());

  async function generateImage() {
    if (!visCurrentJobId) { alert("Select a track first"); return; }
    const prompt = imagePromptEl.value.trim();
    if (!prompt) { imagePromptEl.focus(); return; }

    btnGenImage.disabled = true; btnGenImage.textContent = "Generating...";
    btnRegenImage.disabled = true;

    try {
      const res = await fetch(`/api/visual/image/${visCurrentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const data = await res.json();
      if (data.error) {
        alert("Image generation failed: " + data.error);
      } else {
        previewImg.src = data.image_url;
        imagePreview.classList.remove("hidden");
        visAnimatePanel.classList.remove("hidden");
        clipPreview.classList.add("hidden");
        visExportPanel.classList.add("hidden");
        videoDownload.classList.add("hidden");
      }
    } catch (err) {
      alert("Image generation failed: " + err.message);
    }

    btnGenImage.disabled = false; btnGenImage.textContent = "Generate Image ($0.02)";
    btnRegenImage.disabled = false;
  }

  // ── Clip generation (step 2) ──────────────────
  btnCreateClip.addEventListener("click", async () => {
    if (!visCurrentJobId) return;

    btnCreateClip.disabled = true;
    const isAI = currentVideoMode === "ai";
    btnCreateClip.textContent = isAI ? "Animating..." : "Processing...";
    clipProgressText.textContent = isAI
      ? "Grok is animating your image (1-3 min)..."
      : "Creating Ken Burns clip...";
    clipProgress.classList.remove("hidden");
    clipPreview.classList.add("hidden");
    visExportPanel.classList.add("hidden");

    try {
      const res = await fetch(`/api/visual/clip/${visCurrentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: currentVideoMode,
          motion_prompt: motionPromptEl.value.trim(),
        }),
      });
      const data = await res.json();
      if (data.error) {
        alert("Animation failed: " + data.error);
      } else {
        clipVideo.src = data.clip_url;
        clipVideo.load();
        clipPreview.classList.remove("hidden");
        visExportPanel.classList.remove("hidden");
        videoDownload.classList.add("hidden");
      }
    } catch (err) {
      alert("Animation failed: " + err.message);
    }

    btnCreateClip.disabled = false;
    btnCreateClip.textContent = "Generate Animation";
    clipProgress.classList.add("hidden");
  });

  // ── Export full video (step 3) ────────────────
  btnExportVideo.addEventListener("click", async () => {
    if (!visCurrentJobId) return;

    btnExportVideo.disabled = true;
    btnExportVideo.textContent = "Exporting...";
    exportProgressText.textContent = "Looping clip + combining with audio...";
    exportProgress.classList.remove("hidden");
    videoDownload.classList.add("hidden");

    const minutes = parseFloat(videoDurationEl.value);

    try {
      const res = await fetch(`/api/visual/export/${visCurrentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duration_minutes: minutes }),
      });
      const data = await res.json();
      if (data.error) {
        alert("Export failed: " + data.error);
      } else {
        videoDownloadLink.href = data.download_url;
        videoDownload.classList.remove("hidden");
      }
    } catch (err) {
      alert("Export failed: " + err.message);
    }

    btnExportVideo.disabled = false;
    btnExportVideo.textContent = "Export Video";
    exportProgress.classList.add("hidden");
  });


  // ═══════════════════════════════════════════════════════
  //  TAB: Publish
  // ═══════════════════════════════════════════════════════

  const ytStatusText = document.getElementById("yt-status-text");
  const ytChannelInfo = document.getElementById("yt-channel-info");
  const ytChannelThumb = document.getElementById("yt-channel-thumb");
  const ytChannelName = document.getElementById("yt-channel-name");
  const ytChannelSubs = document.getElementById("yt-channel-subs");
  const btnYtConnect = document.getElementById("btn-yt-connect");
  const btnYtDisconnect = document.getElementById("btn-yt-disconnect");
  const ytSetupHint = document.getElementById("yt-setup-hint");
  const pubSelectPanel = document.getElementById("pub-select-panel");
  const pubTrackSelect = document.getElementById("pub-track-select");
  const pubTrackInfo = document.getElementById("pub-track-info");
  const pubTrackPrompt = document.getElementById("pub-track-prompt");
  const pubVideoBadge = document.getElementById("pub-video-badge");
  const pubMetaPanel = document.getElementById("pub-meta-panel");
  const btnAutoMeta = document.getElementById("btn-auto-meta");
  const ytTitleEl = document.getElementById("yt-title");
  const ytDescEl = document.getElementById("yt-description");
  const ytTagsEl = document.getElementById("yt-tags");
  const ytPrivacyEl = document.getElementById("yt-privacy");
  const ytTitleCount = document.getElementById("yt-title-count");
  const ytDescCount = document.getElementById("yt-desc-count");
  const pubUploadPanel = document.getElementById("pub-upload-panel");
  const pubPreviewTitle = document.getElementById("pub-preview-title");
  const pubPreviewPrivacy = document.getElementById("pub-preview-privacy");
  const pubThumbPreview = document.getElementById("pub-thumb-preview");
  const btnYtUpload = document.getElementById("btn-yt-upload");
  const uploadProgress = document.getElementById("upload-progress");
  const uploadProgressText = document.getElementById("upload-progress-text");
  const uploadProgressBar = document.getElementById("upload-progress-bar");
  const uploadResult = document.getElementById("upload-result");
  const uploadResultLink = document.getElementById("upload-result-link");

  let pubCurrentJobId = null;
  let ytConnected = false;

  ytTitleEl.addEventListener("input", () => {
    ytTitleCount.textContent = ytTitleEl.value.length;
    pubPreviewTitle.textContent = ytTitleEl.value || "—";
  });
  ytDescEl.addEventListener("input", () => { ytDescCount.textContent = ytDescEl.value.length; });
  ytPrivacyEl.addEventListener("change", () => { pubPreviewPrivacy.textContent = ytPrivacyEl.value; });

  async function checkYouTubeStatus() {
    try {
      const res = await fetch("/api/youtube/status");
      const data = await res.json();

      if (data.connected) {
        ytConnected = true;
        ytStatusText.textContent = "Connected to YouTube";
        ytStatusText.classList.add("yt-connected");
        ytChannelThumb.src = data.channel.thumbnail;
        ytChannelName.textContent = data.channel.name;
        ytChannelSubs.textContent = data.channel.subscribers > 0
          ? `${data.channel.subscribers.toLocaleString()} subscribers`
          : "";
        ytChannelInfo.classList.remove("hidden");
        btnYtConnect.classList.add("hidden");
        btnYtDisconnect.classList.remove("hidden");
        ytSetupHint.classList.add("hidden");
        pubSelectPanel.classList.remove("hidden");
      } else {
        ytConnected = false;
        ytStatusText.textContent = data.message;
        ytStatusText.classList.remove("yt-connected");
        ytChannelInfo.classList.add("hidden");
        btnYtDisconnect.classList.add("hidden");

        if (data.has_client_secret) {
          btnYtConnect.classList.remove("hidden");
          ytSetupHint.classList.add("hidden");
          pubSelectPanel.classList.add("hidden");
        } else {
          btnYtConnect.classList.add("hidden");
          ytSetupHint.classList.remove("hidden");
          pubSelectPanel.classList.add("hidden");
        }
      }
    } catch (err) {
      ytStatusText.textContent = "Could not check YouTube status";
    }
  }

  btnYtConnect.addEventListener("click", async () => {
    btnYtConnect.disabled = true;
    btnYtConnect.textContent = "Connecting...";
    try {
      const res = await fetch("/api/youtube/connect", { method: "POST" });
      const data = await res.json();
      if (data.error) { alert(data.error); return; }
      const popup = window.open(data.auth_url, "yt-auth", "width=600,height=700");
      window.addEventListener("message", function handler(e) {
        if (e.data === "youtube-connected") {
          window.removeEventListener("message", handler);
          checkYouTubeStatus();
        }
      });
    } catch (err) { alert("Connect failed: " + err.message); }
    btnYtConnect.disabled = false;
    btnYtConnect.textContent = "Connect YouTube";
  });

  btnYtDisconnect.addEventListener("click", async () => {
    if (!confirm("Disconnect YouTube account?")) return;
    await fetch("/api/youtube/disconnect", { method: "POST" });
    checkYouTubeStatus();
    pubSelectPanel.classList.add("hidden");
    pubMetaPanel.classList.add("hidden");
    pubUploadPanel.classList.add("hidden");
  });

  async function refreshPubTrackList() {
    try {
      const res = await fetch("/api/history");
      const history = await res.json();
      const withVideo = history.filter((j) => j.status === "complete");

      const prev = pubTrackSelect.value;
      pubTrackSelect.innerHTML = '<option value="">— Choose a track —</option>';
      withVideo.forEach((j) => {
        const opt = document.createElement("option");
        opt.value = j.job_id;
        let timeStr = "";
        if (j.created_at) {
          const d = new Date(j.created_at);
          const diff = Date.now() - d;
          if (diff < 3600000) timeStr = Math.floor(diff / 60000) + "m ago";
          else if (diff < 86400000) timeStr = Math.floor(diff / 3600000) + "h ago";
          else timeStr = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
        }
        opt.textContent = `${j.prompt.substring(0, 60)}${j.prompt.length > 60 ? "..." : ""} (${timeStr})`;
        pubTrackSelect.appendChild(opt);
      });
      if (prev) pubTrackSelect.value = prev;
    } catch (err) {
      console.error("Failed to load tracks:", err);
    }
  }

  pubTrackSelect.addEventListener("change", async () => {
    const jobId = pubTrackSelect.value;
    if (!jobId) {
      pubTrackInfo.classList.add("hidden");
      pubMetaPanel.classList.add("hidden");
      pubUploadPanel.classList.add("hidden");
      pubCurrentJobId = null;
      return;
    }

    pubCurrentJobId = jobId;

    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();

      pubTrackPrompt.textContent = `"${data.prompt}"`;

      if (data.visual_video_url) {
        pubVideoBadge.innerHTML = '<span class="badge badge-ready">Video ready</span>';
      } else if (data.visual_image_url) {
        pubVideoBadge.innerHTML = '<span class="badge badge-warn">Image only — export a video in the Visuals tab first</span>';
      } else {
        pubVideoBadge.innerHTML = '<span class="badge badge-warn">No video — create one in the Visuals tab first</span>';
      }
      pubTrackInfo.classList.remove("hidden");

      if (data.visual_video_url) {
        pubMetaPanel.classList.remove("hidden");
        pubUploadPanel.classList.remove("hidden");
        uploadResult.classList.add("hidden");
        uploadProgress.classList.add("hidden");

        if (data.yt_title) ytTitleEl.value = data.yt_title;
        if (data.yt_description) ytDescEl.value = data.yt_description;
        if (data.yt_tags) ytTagsEl.value = data.yt_tags;
        if (data.yt_privacy) ytPrivacyEl.value = data.yt_privacy;
        ytTitleCount.textContent = ytTitleEl.value.length;
        ytDescCount.textContent = ytDescEl.value.length;
        pubPreviewTitle.textContent = ytTitleEl.value || "—";
        pubPreviewPrivacy.textContent = ytPrivacyEl.value;

        if (data.visual_image_url) {
          pubThumbPreview.innerHTML = `<img src="${data.visual_image_url}?t=${Date.now()}" alt="Thumbnail">`;
        } else {
          pubThumbPreview.innerHTML = '<span class="no-thumb">No thumbnail</span>';
        }

        if (data.youtube_url) {
          uploadResultLink.href = data.youtube_url;
          uploadResultLink.textContent = "View on YouTube → " + data.youtube_url;
          uploadResult.classList.remove("hidden");
        } else {
          uploadResult.classList.add("hidden");
        }
      } else {
        pubMetaPanel.classList.add("hidden");
        pubUploadPanel.classList.add("hidden");
      }
    } catch (err) {
      console.error("Failed to load track:", err);
    }
  });

  // ── Auto-generate metadata ────────────────────
  btnAutoMeta.addEventListener("click", async () => {
    if (!pubCurrentJobId) return;
    btnAutoMeta.disabled = true;
    btnAutoMeta.textContent = "Writing...";

    try {
      const res = await fetch(`/api/youtube/auto-metadata/${pubCurrentJobId}`, { method: "POST" });
      const data = await res.json();
      if (data.error) {
        alert("Auto-metadata failed: " + data.error);
      } else {
        ytTitleEl.value = data.title || "";
        ytTitleCount.textContent = ytTitleEl.value.length;
        pubPreviewTitle.textContent = ytTitleEl.value;
        ytDescEl.value = data.description || "";
        ytDescCount.textContent = ytDescEl.value.length;
        if (Array.isArray(data.tags)) {
          ytTagsEl.value = data.tags.join(", ");
        }
      }
    } catch (err) { alert("Auto-metadata failed: " + err.message); }
    btnAutoMeta.disabled = false;
    btnAutoMeta.textContent = "Auto-Write Everything";
  });

  // ── Upload ────────────────────────────────────
  btnYtUpload.addEventListener("click", async () => {
    if (!pubCurrentJobId) return;
    const title = ytTitleEl.value.trim();
    if (!title) { ytTitleEl.focus(); alert("Title is required"); return; }

    btnYtUpload.disabled = true;
    btnYtUpload.textContent = "Uploading...";
    uploadProgressText.textContent = "Starting upload...";
    uploadProgressBar.style.width = "0%";
    uploadProgress.classList.remove("hidden");
    uploadResult.classList.add("hidden");

    try {
      const res = await fetch(`/api/youtube/upload/${pubCurrentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          description: ytDescEl.value,
          tags: ytTagsEl.value,
          privacy: ytPrivacyEl.value,
        }),
      });
      const data = await res.json();
      if (data.error) {
        alert("Upload failed: " + data.error);
        btnYtUpload.disabled = false;
        btnYtUpload.textContent = "Upload to YouTube";
        return;
      }

      const pollUpload = setInterval(async () => {
        try {
          const sr = await fetch(`/api/youtube/upload-status/${pubCurrentJobId}`);
          const sd = await sr.json();
          uploadProgressBar.style.width = sd.progress + "%";
          uploadProgressText.textContent = sd.message || "Uploading...";

          if (sd.status === "done") {
            clearInterval(pollUpload);
            uploadProgressBar.style.width = "100%";
            uploadProgressText.textContent = "Upload complete!";
            uploadResultLink.href = sd.youtube_url;
            uploadResultLink.textContent = sd.youtube_url;
            uploadResult.classList.remove("hidden");
            btnYtUpload.disabled = false;
            btnYtUpload.textContent = "Upload to YouTube";
            setTimeout(() => uploadProgress.classList.add("hidden"), 3000);
          } else if (sd.status === "error") {
            clearInterval(pollUpload);
            alert("Upload failed: " + sd.message);
            btnYtUpload.disabled = false;
            btnYtUpload.textContent = "Upload to YouTube";
            uploadProgress.classList.add("hidden");
          }
        } catch (e) { /* keep polling */ }
      }, 2000);

    } catch (err) {
      alert("Upload failed: " + err.message);
      btnYtUpload.disabled = false;
      btnYtUpload.textContent = "Upload to YouTube";
    }
  });


  // ═══════════════════════════════════════════════════════
  //  Shared
  // ═══════════════════════════════════════════════════════

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Init ──────────────────────────────────────
  refreshHistory();
})();
