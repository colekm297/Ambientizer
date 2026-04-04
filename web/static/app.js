/**
 * app.js — Ambientizer web frontend
 *
 * Handles prompt submission, generation progress polling,
 * audio playback, feedback chat for mix refinement, and history.
 */

(function () {
  "use strict";

  // ── DOM refs ──────────────────────────────────
  const promptEl = document.getElementById("prompt");
  const referenceUrlEl = document.getElementById("reference-url");
  const durationEl = document.getElementById("duration");
  const loopableEl = document.getElementById("loopable");
  const generateBtn = document.getElementById("generate-btn");
  const modeButtons = document.querySelectorAll(".btn-mode");

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

  // ── Mode toggle ─────────────────────────────
  modeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      modeButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentMode = btn.dataset.mode;
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

  // ── Progress updates ──────────────────────────
  function resetProgress() {
    progressStage.textContent = "Starting";
    progressStage.className = "stage-badge";
    progressMessage.textContent = "";
    progressBar.style.width = "0%";
    progressBar.classList.add("indeterminate");
    logContainer.innerHTML = "";
  }

  function updateProgress(data) {
    const stageName = formatStage(data.stage);
    progressStage.textContent = stageName;

    if (data.status === "complete") {
      progressStage.className = "stage-badge complete";
    } else if (data.status === "error") {
      progressStage.className = "stage-badge error";
    } else {
      progressStage.className = "stage-badge";
    }

    progressMessage.textContent = cleanMessage(data.progress_message || "");

    const pct = stageProgress[data.stage] || 50;
    progressBar.classList.remove("indeterminate");
    progressBar.style.width = pct + "%";

    renderLogs(data.logs || []);
  }

  function formatStage(stage) {
    const names = {
      starting: "Starting",
      analyzing_reference: "Analyzing Reference",
      interpreting: "Interpreting",
      generating_samples: "Generating Audio",
      rendering: "Rendering",
      mastering: "Mastering",
      complete: "Complete",
      error: "Error",
    };
    return names[stage] || stage;
  }

  function cleanMessage(msg) {
    return msg.replace(/^[\s=]+/, "").replace(/[=]+$/, "").trim();
  }

  function renderLogs(logs) {
    logContainer.innerHTML = logs
      .map(
        (l) =>
          `<div class="log-entry">${cleanMessage(l.message)}</div>`
      )
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

  // ── State: root key ──────────────────────────────
  let currentRootKey = "";

  // ── Audio Player ──────────────────────────────
  function showPlayer(data) {
    playerPanel.classList.remove("hidden");
    playerPrompt.textContent = `"${data.prompt}" (30s preview)`;

    audioPlayer.src = `/api/audio/${data.job_id}?t=${Date.now()}`;
    audioPlayer.load();

    btnDownload.onclick = () => finalizeAndDownload(data.job_id);

    if (data.root_key) currentRootKey = data.root_key;

    if (data.layers && data.layers.length) {
      renderLayers(data.layers);
    }
  }

  // ── Layer Inspector ────────────────────────────
  let currentLayers = [];
  let layerActionPending = false;
  let sliderDebounceTimers = {};
  let pendingSliderUpdates = {};

  function renderLayers(layers) {
    currentLayers = layers;
    layersPanel.classList.remove("hidden");
    const keyBadge = currentRootKey ? ` · Key: ${escapeHtml(currentRootKey)}` : "";
    layersCount.textContent = `(${layers.length}${keyBadge})`;

    const typeIcons = { base: "🌊", mid: "🌿", detail: "✨", musical: "🎵" };
    const typeLabels = { base: "Base", mid: "Mid", detail: "Detail", musical: "Musical" };

    let html = layers
      .map((l, i) => {
        const icon = typeIcons[l.layer_type] || "🔊";
        const label = typeLabels[l.layer_type] || l.layer_type;
        const isMuted = l.volume_db <= -55;
        const statusDot = l.has_audio ? "ready" : "missing";
        const eName = escapeHtml(l.name);

        const vol = isMuted ? -60 : l.volume_db;
        const pan = l.pan || 0;
        const reverb = l.effects ? (l.effects.reverb_amount || 0) : 0;
        const lpHz = l.effects ? (l.effects.low_pass_hz || 20000) : 20000;
        const pitchSt = l.pitch_shift_semitones || 0;

        const panLabel = pan === 0 ? "C" : pan < 0 ? `L${Math.abs(Math.round(pan * 100))}` : `R${Math.round(pan * 100)}`;

        const muteBtn = isMuted
          ? `<button class="layer-btn layer-btn-unmute" data-action="unmute" data-layer="${eName}" title="Unmute">Unmute</button>`
          : `<button class="layer-btn layer-btn-mute" data-action="mute" data-layer="${eName}" title="Mute">Mute</button>`;

        const indepLoop = l.independent_loop || false;

        return `
          <div class="layer-card ${isMuted ? "muted" : ""}" data-layer-name="${eName}" data-layer-index="${i}">
            <div class="layer-header">
              <span class="layer-icon">${icon}</span>
              <span class="layer-name">${eName}</span>
              <span class="layer-type-badge ${l.layer_type}">${label}</span>
              <span class="layer-status ${statusDot}"></span>
            </div>
            <div class="layer-prompt">${escapeHtml(l.elevenlabs_prompt || "No prompt")}</div>
            <div class="layer-sliders">
              <div class="slider-row">
                <span class="slider-label">Vol</span>
                <input type="range" class="layer-slider slider-vol" data-param="volume_db" data-layer="${eName}"
                  min="-40" max="0" step="1" value="${vol}">
                <span class="slider-value" data-display="volume_db">${isMuted ? "MUTE" : vol + " dB"}</span>
              </div>
              <div class="slider-row">
                <span class="slider-label">Pan</span>
                <input type="range" class="layer-slider slider-pan" data-param="pan" data-layer="${eName}"
                  min="-100" max="100" step="5" value="${Math.round(pan * 100)}">
                <span class="slider-value" data-display="pan">${panLabel}</span>
              </div>
              <div class="slider-row">
                <span class="slider-label">Reverb</span>
                <input type="range" class="layer-slider slider-reverb" data-param="reverb_amount" data-layer="${eName}"
                  min="0" max="100" step="5" value="${Math.round(reverb * 100)}">
                <span class="slider-value" data-display="reverb_amount">${Math.round(reverb * 100)}%</span>
              </div>
              <div class="slider-row">
                <span class="slider-label">LP</span>
                <input type="range" class="layer-slider slider-lp" data-param="low_pass_hz" data-layer="${eName}"
                  min="500" max="20000" step="500" value="${lpHz}">
                <span class="slider-value" data-display="low_pass_hz">${lpHz >= 20000 ? "Off" : (lpHz / 1000).toFixed(1) + "k"}</span>
              </div>
              <div class="slider-row">
                <span class="slider-label">Pitch</span>
                <input type="range" class="layer-slider slider-pitch" data-param="pitch_shift_semitones" data-layer="${eName}"
                  min="-6" max="6" step="1" value="${pitchSt}">
                <span class="slider-value" data-display="pitch_shift_semitones">${pitchSt === 0 ? "0" : (pitchSt > 0 ? "+" + pitchSt : pitchSt) + "st"}</span>
                <span class="detected-key" data-key-for="${eName}"></span>
              </div>
            </div>
            <label class="layer-toggle" title="Loop this layer on its own cycle for natural variation">
              <input type="checkbox" class="indep-loop-cb" data-layer="${eName}" ${indepLoop ? "checked" : ""}>
              <span class="layer-toggle-text">Independent loop</span>
            </label>
            <div class="layer-actions">
              ${muteBtn}
              <button class="layer-btn layer-btn-reroll" data-action="regenerate" data-layer="${eName}" title="Re-roll (same prompt, new result)">Re-roll</button>
              <button class="layer-btn layer-btn-regen" data-action="show-regen" data-layer="${eName}" title="Regenerate with new prompt">New Sound</button>
              <button class="layer-btn layer-btn-remove" data-action="remove" data-layer="${eName}" title="Remove layer">Remove</button>
            </div>
            <div class="layer-regen-form hidden" data-regen-for="${eName}">
              <textarea class="regen-prompt-input" rows="2" placeholder="Describe the sound you want (e.g. Soft crackling fireplace, warm and close, gentle pops)"></textarea>
              <div class="regen-form-row">
                <select class="regen-type-select">
                  <option value="">Same type</option>
                  <option value="base">SFX: Base</option>
                  <option value="mid">SFX: Mid</option>
                  <option value="detail">SFX: Detail</option>
                  <option value="musical">Musical</option>
                </select>
                <button class="layer-btn layer-btn-regen regen-submit" data-layer="${eName}">Generate</button>
                <button class="layer-btn layer-btn-mute regen-cancel" data-layer="${eName}">Cancel</button>
              </div>
            </div>
          </div>`;
      })
      .join("");

    html += `
      <div class="layer-tools">
        <button id="detect-keys-btn" class="layer-btn layer-btn-detect" title="Analyze each layer's musical key">Detect Keys</button>
        <button id="auto-harmonize-btn" class="layer-btn layer-btn-regen" title="Auto pitch-shift tonal layers to match root key">Auto-Harmonize</button>
      </div>
      <div class="add-layer-section">
        <button id="add-layer-toggle" class="btn btn-add-layer">+ Add Layer</button>
        <div id="add-layer-form" class="add-layer-form hidden">
          <input type="text" id="add-layer-name" placeholder="Layer name (e.g. Warm Piano Pad)" class="add-input">
          <div class="add-type-row">
            <select id="add-layer-type" class="add-select">
              <option value="base">Base (foundation)</option>
              <option value="mid" selected>Mid (character)</option>
              <option value="detail">Detail (accents)</option>
              <option value="musical">Musical (tonal)</option>
            </select>
          </div>
          <textarea id="add-layer-prompt" rows="2" placeholder="Describe the sound for ElevenLabs (e.g. Warm, mellow piano chords with heavy reverb, slow tempo, jazzy feel, dark and intimate)" class="add-input"></textarea>
          <div class="add-actions">
            <button id="add-layer-cancel" class="layer-btn layer-btn-mute">Cancel</button>
            <button id="add-layer-submit" class="layer-btn layer-btn-regen">Add</button>
          </div>
        </div>
      </div>`;

    layersList.innerHTML = html;

    // Bind prompt expand
    layersList.querySelectorAll(".layer-prompt").forEach((el) => {
      el.addEventListener("click", () => el.classList.toggle("expanded"));
    });

    // Bind layer action buttons (mute, unmute, regenerate, remove)
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

    // Bind regen form submit/cancel
    layersList.querySelectorAll(".regen-submit").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const layerName = btn.dataset.layer;
        const form = layersList.querySelector(`[data-regen-for="${layerName}"]`);
        const prompt = form.querySelector(".regen-prompt-input").value.trim();
        const newType = form.querySelector(".regen-type-select").value || null;

        if (!prompt) {
          form.querySelector(".regen-prompt-input").focus();
          return;
        }

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

    // Bind sliders
    layersList.querySelectorAll(".layer-slider").forEach((slider) => {
      slider.addEventListener("input", (e) => {
        updateSliderDisplay(slider);
        queueSliderUpdate(slider);
      });
    });

    // Bind independent loop checkboxes
    layersList.querySelectorAll(".indep-loop-cb").forEach((cb) => {
      cb.addEventListener("change", () => {
        const layerName = cb.dataset.layer;
        if (!pendingSliderUpdates[layerName]) pendingSliderUpdates[layerName] = {};
        pendingSliderUpdates[layerName]["independent_loop"] = cb.checked;
        if (sliderDebounceTimers[layerName]) clearTimeout(sliderDebounceTimers[layerName]);
        sliderDebounceTimers[layerName] = setTimeout(() => {
          flushSliderUpdate(layerName, layerName);
        }, 400);
      });
    });

    // Bind add-layer toggle
    const addToggle = document.getElementById("add-layer-toggle");
    const addForm = document.getElementById("add-layer-form");
    if (addToggle && addForm) {
      addToggle.addEventListener("click", () => {
        addForm.classList.toggle("hidden");
        addToggle.classList.toggle("hidden");
      });
      document.getElementById("add-layer-cancel").addEventListener("click", () => {
        addForm.classList.add("hidden");
        addToggle.classList.remove("hidden");
      });
      document.getElementById("add-layer-submit").addEventListener("click", () => {
        performAddLayer();
      });
    }

    // Bind detect-keys and auto-harmonize
    const detectBtn = document.getElementById("detect-keys-btn");
    if (detectBtn) {
      detectBtn.addEventListener("click", () => detectKeysForJob());
    }
    const harmonizeBtn = document.getElementById("auto-harmonize-btn");
    if (harmonizeBtn) {
      harmonizeBtn.addEventListener("click", () => autoHarmonize());
    }
  }

  async function detectKeysForJob() {
    if (!currentJobId) return;
    const btn = document.getElementById("detect-keys-btn");
    if (btn) { btn.disabled = true; btn.textContent = "Analyzing..."; }

    try {
      const res = await fetch(`/api/detect-keys/${currentJobId}`, { method: "POST" });
      const data = await res.json();
      if (data.error) {
        addChatMessage("system", `Key detection error: ${data.error}`);
        return;
      }
      if (data.root_key) currentRootKey = data.root_key;

      for (const [name, info] of Object.entries(data.keys)) {
        const el = layersList.querySelector(`[data-key-for="${escapeHtml(name)}"]`);
        if (el) {
          if (info.tonal) {
            el.textContent = info.key;
            el.title = `Detected key (confidence: ${(info.confidence * 100).toFixed(0)}%)`;
            el.classList.add("key-tonal");
          } else {
            el.textContent = "noise";
            el.title = "Non-tonal (no key detected)";
            el.classList.add("key-noise");
          }
        }
      }
      const keyBadge = currentRootKey ? ` · Key: ${escapeHtml(currentRootKey)}` : "";
      layersCount.textContent = `(${currentLayers.length}${keyBadge})`;
    } catch (err) {
      addChatMessage("system", `Key detection failed: ${err.message}`);
    }

    if (btn) { btn.disabled = false; btn.textContent = "Detect Keys"; }
  }

  async function autoHarmonize() {
    if (!currentJobId) return;
    const btn = document.getElementById("auto-harmonize-btn");
    if (btn) { btn.disabled = true; btn.textContent = "Harmonizing..."; }

    try {
      const res = await fetch(`/api/auto-harmonize/${currentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root_key: currentRootKey || "" }),
      });
      const data = await res.json();
      if (data.error) {
        addChatMessage("system", `Harmonize error: ${data.error}`);
      } else {
        if (data.root_key) currentRootKey = data.root_key;
        addChatMessage("system", `Harmonized to ${data.root_key}`);
        audioPlayer.src = data.audio_url;
        audioPlayer.load();
        audioPlayer.play().catch(() => {});
        if (data.layers) renderLayers(data.layers);
      }
    } catch (err) {
      addChatMessage("system", `Harmonize failed: ${err.message}`);
    }

    if (btn) { btn.disabled = false; btn.textContent = "Auto-Harmonize"; }
  }

  function updateSliderDisplay(slider) {
    const param = slider.dataset.param;
    const val = parseFloat(slider.value);
    const card = slider.closest(".layer-card");
    const display = card.querySelector(`[data-display="${param}"]`);
    if (!display) return;

    if (param === "volume_db") {
      display.textContent = val <= -40 ? "MUTE" : val + " dB";
    } else if (param === "pan") {
      const p = val / 100;
      display.textContent = p === 0 ? "C" : p < 0 ? `L${Math.abs(val)}` : `R${val}`;
    } else if (param === "reverb_amount") {
      display.textContent = val + "%";
    } else if (param === "low_pass_hz") {
      display.textContent = val >= 20000 ? "Off" : (val / 1000).toFixed(1) + "k";
    } else if (param === "pitch_shift_semitones") {
      display.textContent = val === 0 ? "0" : (val > 0 ? "+" + val : val) + "st";
    }
  }

  function queueSliderUpdate(slider) {
    const layerName = slider.dataset.layer;
    const param = slider.dataset.param;
    const key = `${layerName}`;

    if (!pendingSliderUpdates[key]) {
      pendingSliderUpdates[key] = {};
    }

    let val = parseFloat(slider.value);
    if (param === "pan") val = val / 100;
    else if (param === "reverb_amount") val = val / 100;

    pendingSliderUpdates[key][param] = val;

    if (sliderDebounceTimers[key]) {
      clearTimeout(sliderDebounceTimers[key]);
    }

    sliderDebounceTimers[key] = setTimeout(() => {
      flushSliderUpdate(key, layerName);
    }, 800);
  }

  async function flushSliderUpdate(key, layerName) {
    const params = pendingSliderUpdates[key];
    if (!params || !currentJobId) return;
    delete pendingSliderUpdates[key];

    const card = layersList.querySelector(`[data-layer-name="${layerName}"]`);
    if (card) card.classList.add("layer-loading");

    try {
      const res = await fetch(`/api/layer-action/${currentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "update_params",
          layer_name: layerName,
          params,
        }),
      });
      const data = await res.json();
      if (card) card.classList.remove("layer-loading");

      if (data.error) {
        addChatMessage("system", `Error: ${data.error}`);
      } else {
        audioPlayer.src = data.audio_url;
        audioPlayer.load();
        audioPlayer.play().catch(() => {});
      }
    } catch (err) {
      if (card) card.classList.remove("layer-loading");
      addChatMessage("system", `Error: ${err.message}`);
    }
  }

  async function performRegenWithPrompt(layerName, prompt, newType) {
    if (!currentJobId || layerActionPending) return;
    layerActionPending = true;

    layersList.querySelectorAll(".layer-btn").forEach((b) => (b.disabled = true));
    const card = layersList.querySelector(`[data-layer-name="${layerName}"]`);
    if (card) card.classList.add("layer-loading");

    addChatMessage("user", `Regenerate "${layerName}": ${prompt}`);

    try {
      const res = await fetch(`/api/layer-action/${currentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "regenerate_with_prompt",
          layer_name: layerName,
          prompt,
          layer_type: newType,
        }),
      });
      const data = await res.json();

      if (data.error) {
        addChatMessage("system", `Error: ${data.error}`);
      } else {
        addChatMessage("system", data.changes);
        audioPlayer.src = data.audio_url;
        audioPlayer.load();
        audioPlayer.play().catch(() => {});
        if (data.layers) renderLayers(data.layers);
      }
    } catch (err) {
      addChatMessage("system", `Error: ${err.message}`);
    }

    layerActionPending = false;
    layersList.querySelectorAll(".layer-btn").forEach((b) => (b.disabled = false));
  }

  async function performLayerAction(action, layerName) {
    if (!currentJobId || layerActionPending) return;
    layerActionPending = true;

    const body = { action, layer_name: layerName };

    if (action === "unmute") {
      body.restore_volume = -12.0;
    }

    // Disable all layer buttons while working
    layersList.querySelectorAll(".layer-btn").forEach((b) => (b.disabled = true));

    const targetCard = layersList.querySelector(`[data-action="${action}"][data-layer="${layerName}"]`);
    if (targetCard) {
      const card = targetCard.closest(".layer-card");
      if (card) card.classList.add("layer-loading");
    }

    try {
      const res = await fetch(`/api/layer-action/${currentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();

      if (data.error) {
        addChatMessage("system", `Error: ${data.error}`);
      } else {
        addChatMessage("system", data.changes);
        audioPlayer.src = data.audio_url;
        audioPlayer.load();
        audioPlayer.play().catch(() => {});

        if (data.layers) renderLayers(data.layers);
      }
    } catch (err) {
      addChatMessage("system", `Error: ${err.message}`);
    }

    layerActionPending = false;
    layersList.querySelectorAll(".layer-btn").forEach((b) => (b.disabled = false));
  }

  async function performAddLayer() {
    if (!currentJobId || layerActionPending) return;

    const name = document.getElementById("add-layer-name").value.trim();
    const layerType = document.getElementById("add-layer-type").value;
    const prompt = document.getElementById("add-layer-prompt").value.trim();

    if (!name || !prompt) {
      alert("Name and prompt are required");
      return;
    }

    layerActionPending = true;
    const submitBtn = document.getElementById("add-layer-submit");
    submitBtn.disabled = true;
    submitBtn.textContent = "Generating...";

    try {
      const res = await fetch(`/api/layer-action/${currentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "add",
          name,
          layer_type: layerType,
          prompt,
        }),
      });
      const data = await res.json();

      if (data.error) {
        addChatMessage("system", `Error: ${data.error}`);
      } else {
        addChatMessage("system", data.changes);
        audioPlayer.src = data.audio_url;
        audioPlayer.load();
        audioPlayer.play().catch(() => {});

        if (data.layers) renderLayers(data.layers);

        document.getElementById("add-layer-name").value = "";
        document.getElementById("add-layer-prompt").value = "";
      }
    } catch (err) {
      addChatMessage("system", `Error: ${err.message}`);
    }

    layerActionPending = false;
    submitBtn.disabled = false;
    submitBtn.textContent = "Add";
  }

  // ── Feedback Chat ─────────────────────────────
  function enableFeedback() {
    feedbackPanel.classList.remove("hidden");
    feedbackInput.disabled = false;
    feedbackSend.disabled = false;
    feedbackInput.focus();
  }

  function addChatMessage(role, text) {
    const div = document.createElement("div");
    div.className = `feedback-message ${role}`;
    div.textContent = text;
    feedbackMessages.appendChild(div);
    feedbackMessages.scrollTop = feedbackMessages.scrollHeight;
  }

  function addStatusMessage(text) {
    const div = document.createElement("div");
    div.className = "feedback-message status";
    div.innerHTML = text;
    div.id = "feedback-status-active";
    feedbackMessages.appendChild(div);
    feedbackMessages.scrollTop = feedbackMessages.scrollHeight;
    return div;
  }

  function removeActiveStatus() {
    const el = document.getElementById("feedback-status-active");
    if (el) el.remove();
  }

  async function submitFeedback(text) {
    if (!currentJobId || feedbackPending) return;

    feedbackPending = true;
    feedbackInput.disabled = true;
    feedbackSend.disabled = true;

    addChatMessage("user", text);
    const statusEl = addStatusMessage("Applying changes (may take a moment if regenerating sounds)...");

    try {
      const res = await fetch(`/api/feedback/${currentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback: text }),
      });

      const data = await res.json();
      removeActiveStatus();

      if (data.error) {
        addChatMessage("system", `Error: ${data.error}`);
      } else {
        addChatMessage("system", `Updated! ${data.changes}`);

        audioPlayer.src = data.audio_url;
        audioPlayer.load();
        audioPlayer.play().catch(() => {});

        if (data.layers && data.layers.length) {
          renderLayers(data.layers);
        }
      }
    } catch (err) {
      removeActiveStatus();
      addChatMessage("system", `Error: ${err.message}`);
    }

    feedbackPending = false;
    feedbackInput.disabled = false;
    feedbackSend.disabled = false;
    feedbackInput.value = "";
    feedbackInput.focus();
  }

  feedbackSend.addEventListener("click", () => {
    const text = feedbackInput.value.trim();
    if (text) submitFeedback(text);
  });

  feedbackInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const text = feedbackInput.value.trim();
      if (text) submitFeedback(text);
    }
  });

  // ── Finalize & Download ───────────────────────
  async function finalizeAndDownload(jobId) {
    btnDownload.disabled = true;
    btnDownload.textContent = "Rendering full length + mastering...";

    try {
      const res = await fetch(`/api/finalize/${jobId}`, {
        method: "POST",
      });

      const data = await res.json();

      if (data.error) {
        alert("Failed: " + data.error);
      } else {
        window.location.href = data.download_url;
      }
    } catch (err) {
      alert("Download failed: " + err.message);
    }

    btnDownload.disabled = false;
    btnDownload.textContent = "Download WAV";
  }

  // ── History ───────────────────────────────────
  async function refreshHistory() {
    try {
      const res = await fetch("/api/history");
      const history = await res.json();

      if (!history.length) {
        historyList.innerHTML =
          '<p class="history-empty">No generations yet. Create your first soundscape above.</p>';
        return;
      }

      historyList.innerHTML = history
        .map(
          (j) => {
            let timeStr = "";
            if (j.created_at) {
              const d = new Date(j.created_at);
              const now = new Date();
              const diff = now - d;
              if (diff < 60000) timeStr = "just now";
              else if (diff < 3600000) timeStr = Math.floor(diff / 60000) + "m ago";
              else if (diff < 86400000) timeStr = Math.floor(diff / 3600000) + "h ago";
              else timeStr = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
            }
            const edits = j.feedback_count ? j.feedback_count + " edits" : "";
            const meta = [edits, timeStr].filter(Boolean).join(" · ");

            return `
        <div class="history-item" data-job-id="${j.job_id}">
          <span class="status-dot ${j.status}"></span>
          <span class="prompt-text">${escapeHtml(j.prompt)}</span>
          <span class="meta">${meta}</span>
        </div>`;
          }
        )
        .join("");

      historyList.querySelectorAll(".history-item").forEach((el) => {
        el.addEventListener("click", () => {
          viewJob(el.dataset.jobId);
        });
      });
    } catch (err) {
      console.error("History fetch error:", err);
    }
  }

  async function viewJob(jobId) {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();

      if (data.status === "complete") {
        currentJobId = jobId;
        progressPanel.classList.remove("hidden");
        layersPanel.classList.add("hidden");
        updateProgress(data);
        showPlayer(data);
        enableFeedback();

        feedbackMessages.innerHTML = '<div class="feedback-hint">Listen to your soundscape, then describe what to change.<br>Mix tweaks: "rain too loud", "more reverb"<br>Change a sound: "I don\'t like the thunder", "regenerate the wind"</div>';
        if (data.feedback_history) {
          data.feedback_history.forEach((entry) => {
            addChatMessage("user", entry.feedback);
            addChatMessage("system", `Updated! ${entry.changes}`);
          });
        }
      } else if (data.status === "running") {
        progressPanel.classList.remove("hidden");
        playerPanel.classList.add("hidden");
        feedbackPanel.classList.add("hidden");
        currentJobId = jobId;
        startPolling(jobId);
      } else if (data.status === "error") {
        progressPanel.classList.remove("hidden");
        playerPanel.classList.add("hidden");
        layersPanel.classList.add("hidden");
        feedbackPanel.classList.add("hidden");
        showError(`This session failed: ${data.error || "Unknown error"}. Try generating a new one.`);
      }
    } catch (err) {
      console.error("View job error:", err);
    }
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Init ──────────────────────────────────────
  refreshHistory();
})();
