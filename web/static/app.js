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
      try { localStorage.setItem("ambientizer_active_tab", target); } catch (e) {}

      // Single global player keeps playing across tabs — never pause on switch.
      // Each tab just renders a view of the currently-selected track.
      if (target === "visuals" && currentJobId && window._currentTrackData) {
        loadVisualsForTrack(currentJobId, window._currentTrackData);
      }
      if (target === "publish") {
        checkYouTubeStatus();
        if (currentJobId && window._currentTrackData) loadPublishForTrack(currentJobId, window._currentTrackData);
      }
      if (target === "distribute") { onDistributeTabOpen(); }
    });
  });

  // ═══════════════════════════════════════════════════════
  //  TAB: Create
  // ═══════════════════════════════════════════════════════

  // ── DOM refs ──────────────────────────────────
  const promptEl = document.getElementById("prompt");
  const referenceUrlEl = document.getElementById("reference-url");
  const refStartEl = document.getElementById("ref-start");
  const refEndEl = document.getElementById("ref-end");
  const useReferenceGenerationEl = document.getElementById("use-reference-generation");
  const musicLengthEl = document.getElementById("music-length");
  // Track duration is auto-derived as music_length × 2 (min 5 min). Used as
  // the server-side preview render length; live player derives its own length
  // from the actual prepped loop length, and exports use the Extended
  // Duration picker instead.
  function getDerivedTrackMinutes() {
    const m = parseFloat(musicLengthEl?.value) || 5;
    return Math.max(5, m * 2);
  }
  const plannerModeEl = document.getElementById("planner-mode");
  const musicGenerationModeEl = document.getElementById("music-generation-mode");
  const creditEstimateEl = document.getElementById("credit-estimate");
  const generateBtn = document.getElementById("generate-btn");
  const modeButtons = document.querySelectorAll("[data-mode]");

  function parseTimestamp(str) {
    const parts = (str || "0:00").split(":").map(Number);
    if (parts.length === 2) return (parts[0] || 0) * 60 + (parts[1] || 0);
    if (parts.length === 3) return (parts[0] || 0) * 3600 + (parts[1] || 0) * 60 + (parts[2] || 0);
    return parseInt(str) || 0;
  }

  const progressPanel = document.getElementById("progress-panel");
  const progressStage = document.getElementById("progress-stage");
  const progressMessage = document.getElementById("progress-message");
  const progressBar = document.getElementById("progress-bar");
  const stopGenerationBtn = document.getElementById("stop-generation-btn");
  const logContainer = document.getElementById("log-container");

  const playerPanel = document.getElementById("player-panel");
  const playerPrompt = document.getElementById("player-prompt");
  const audioPlayer = document.getElementById("audio-player");
  const btnDownload = document.getElementById("btn-download");
  const btnReprepLoop = document.getElementById("btn-reprep-loop");

  const layersPanel = document.getElementById("layers-panel");
  const layersList = document.getElementById("layers-list");
  const layersCount = document.getElementById("layers-count");

  const feedbackPanel = document.getElementById("feedback-panel");
  const feedbackMessages = document.getElementById("feedback-messages");
  const feedbackInput = document.getElementById("feedback-input");
  const feedbackSend = document.getElementById("feedback-send");

  const historySelect = document.getElementById("history-select");
  const favToggleBtn = document.getElementById("fav-toggle-btn");
  const filterFavBtn = document.getElementById("filter-favorites");

  // ── State ─────────────────────────────────────
  let currentJobId = null;
  let pollInterval = null;
  let stemPollInterval = null;
  let currentMode = "ambient";
  let currentApproach = "unified";
  let currentStemSeparation = "none";
  let currentLayerPlan = null;
  let feedbackPending = false;
  let showFavoritesOnly = false;
  let currentRootKey = "";
  let currentLayers = [];
  let layerActionPending = false;
  let sliderDebounceTimers = {};
  let pendingSliderUpdates = {};
  let mixer = null;
  let usingAudioElement = false;  // true when the bar drives the <audio> element (full-mix / mobile-safe)
  let currentTrackDuration = 300;

  // iOS: declare a "playback" audio session at startup so ALL audio (incl. the
  // streaming <audio> element) routes to the speaker and ignores the ringer
  // switch. Same fix that rescued the Web Audio mixer, applied page-wide.
  try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (e) { /* unsupported */ }

  // NOTE: deliberately NOT routing the <audio> element through Web Audio via
  // createMediaElementSource — that produces silence on iOS Safari (WebKit bug).
  // We play the bare element (iOS plays user-initiated media past the ringer
  // switch) and just (re)assert the playback session.
  function _ensureElementAudioGraph() {
    try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (e) {}
  }
  function _resumeElementCtx() { /* no Web Audio context for the element path */ }
  window._elCtxState = () => "bare-element";
  const MASTER_VOLUME_KEY = "ambientizer_master_volume";

  function getSavedMasterVolume() {
    const raw = localStorage.getItem(MASTER_VOLUME_KEY);
    const val = raw === null ? 0.8 : parseFloat(raw);
    return Number.isFinite(val) ? Math.max(0, Math.min(1, val)) : 0.8;
  }

  function setSavedMasterVolume(value) {
    const vol = Math.max(0, Math.min(1, value));
    localStorage.setItem(MASTER_VOLUME_KEY, String(vol));

    const createVolume = document.getElementById("transport-volume");
    const visualVolume = document.getElementById("vis-transport-volume");
    if (createVolume) createVolume.value = String(Math.round(vol * 100));
    if (visualVolume) visualVolume.value = String(vol);

    if (mixer) mixer.setMasterVolume(vol);
    if (window._ambientizerVisMixer) window._ambientizerVisMixer.setMasterVolume(vol);
    if (audioPlayer) audioPlayer.volume = vol;
    return vol;
  }

  // ── Credit estimate ──────────────────────────
  function _getCreditCosts() {
    const musicMin = parseFloat(musicLengthEl.value) || 0.5;
    const musicSec = Math.min(musicMin * 60, 600);
    const isMusical = currentMode === "musical";
    const MUSIC_CR_PER_SEC = 30;
    const SFX_CR_PER_SEC = 20;
    const SFX_SEC = 5;
    const STEM_CR_PER_SEC = 10;
    let musicLayers, sfxLayers;
    if (isMusical && currentApproach === "unified") {
      musicLayers = 1; sfxLayers = 1;
    } else if (isMusical) {
      musicLayers = 3; sfxLayers = 1;
    } else {
      musicLayers = 0; sfxLayers = 3;
    }
    const baseCost = (musicLayers * musicSec * MUSIC_CR_PER_SEC) + (sfxLayers * SFX_SEC * SFX_CR_PER_SEC);
    let stemCost = 0;
    if (isMusical && currentApproach === "unified" && currentStemSeparation !== "none") {
      stemCost = Math.round(musicSec * STEM_CR_PER_SEC);
    }
    return {
      musicSec,
      perMusic: musicSec * MUSIC_CR_PER_SEC,
      perSfx: SFX_SEC * SFX_CR_PER_SEC,
      stemCost,
      total: baseCost + stemCost,
      musicLayers,
      sfxLayers,
    };
  }

  function updateCreditEstimate() {
    const c = _getCreditCosts();
    // Just the dollar price — credits don't mean anything at a glance.
    const usd = _creditsToUsd(c.total);
    const usdStr = _fmtUsd(usd);
    creditEstimateEl.textContent = usdStr ? `${usdStr} to generate` : `~${c.total.toLocaleString()} cr to generate`;
    creditEstimateEl.classList.toggle("credit-warn", c.total > 3000);
  }
  musicLengthEl.addEventListener("change", updateCreditEstimate);

  // ── Composition Sections (visible + editable plan) ──────────────────────
  window._compositionPlan = null;
  const compSectionsGroup = document.getElementById("comp-sections-group");
  const compSectionsList = document.getElementById("comp-sections-list");
  const btnPlanSections = document.getElementById("btn-plan-sections");

  function _toggleCompSections() {
    const on = currentMode === "musical" && musicGenerationModeEl?.value === "composition_plan";
    if (compSectionsGroup) compSectionsGroup.classList.toggle("hidden", !on);
    // One plan artifact at a time: the layer plan and the timeline never co-exist.
    if (on) { const pp = document.getElementById("plan-preview"); if (pp) pp.classList.add("hidden"); }
  }
  musicGenerationModeEl?.addEventListener("change", _toggleCompSections);

  let _selectedSection = 0;
  const _fmtClock = (mins) => {
    const t = Math.round(mins * 60);
    return Math.floor(t / 60) + ":" + String(t % 60).padStart(2, "0");
  };
  function _renderCompSections(plan) {
    window._compositionPlan = plan;
    if (!compSectionsList) return;
    const secs = (plan && plan.sections) || [];
    if (!secs.length) {
      compSectionsList.innerHTML = `<div class="canvas-empty">
          <div class="canvas-empty-icon">⎓</div>
          <p class="canvas-empty-title">Your timeline appears here</p>
          <p class="canvas-empty-sub">With <strong>Composition plan</strong> selected, press <strong>Enhance &amp; Plan</strong> — Claude designs an evolving arrangement (sparse → full → sparse) you can sculpt before generating.</p>
        </div>`;
      return;
    }
    if (_selectedSection >= secs.length) _selectedSection = 0;
    const total = secs.reduce((a, s) => a + (s.duration_ms || 0), 0) || 1;
    let elapsed = 0;
    const blocks = secs.map((s, i) => {
      const dur = s.duration_ms || 0;
      const startMin = elapsed / 60000, endMin = (elapsed + dur) / 60000;
      elapsed += dur;
      const density = Math.min((s.positive_local_styles || []).length / 6, 1);
      const fillH = Math.round(22 + density * 78);
      const sel = i === _selectedSection ? " selected" : "";
      return `<button type="button" class="tl-block${sel}" data-idx="${i}" style="flex:${Math.max(dur, 1)}" title="${escapeHtml(s.section_name || '')}">
          <span class="tl-block-bars"><span class="tl-block-fill" style="height:${fillH}%"></span></span>
          <span class="tl-block-label">${escapeHtml(s.section_name || ('Section ' + (i + 1)))}</span>
          <span class="tl-block-time">${startMin.toFixed(1)}–${endMin.toFixed(1)}m</span>
        </button>`;
    }).join("");
    const sel = secs[_selectedSection];
    const editor = `<div class="tl-editor">
        <div class="tl-editor-head">
          <input class="comp-name tl-edit-name" data-idx="${_selectedSection}" value="${escapeHtml(sel.section_name || '')}" placeholder="Section name">
          <span class="tl-editor-pos">${_selectedSection + 1} / ${secs.length}</span>
        </div>
        <label class="tl-edit-label">Present <span>instruments &amp; textures in this section</span></label>
        <textarea class="comp-pos tl-edit-area" data-idx="${_selectedSection}" rows="3" placeholder="e.g. solo cello prominent; low string pads; sub-bass hum">${escapeHtml((sel.positive_local_styles || []).join('; '))}</textarea>
        <label class="tl-edit-label">Absent <span>dropped here — this forces the contrast</span></label>
        <textarea class="comp-neg tl-edit-area" data-idx="${_selectedSection}" rows="2" placeholder="e.g. no glass harmonica; no vocal pads">${escapeHtml((sel.negative_local_styles || []).join('; '))}</textarea>
      </div>`;
    compSectionsList.innerHTML = `
      <div class="tl-wrap">
        <div class="tl-track">${blocks}</div>
        <div class="tl-ruler"><span>0:00</span><span>${_fmtClock(total / 60000)}</span></div>
      </div>
      ${editor}`;
    compSectionsList.querySelectorAll(".tl-block").forEach(el =>
      el.addEventListener("click", () => { _selectedSection = +el.dataset.idx; _renderCompSections(window._compositionPlan); }));
    const setArr = (idx, key, val) => { window._compositionPlan.sections[idx][key] = val.split(';').map(x => x.trim()).filter(Boolean); };
    compSectionsList.querySelectorAll(".comp-name").forEach(el => el.addEventListener("input", () => {
      window._compositionPlan.sections[+el.dataset.idx].section_name = el.value;
      const lbl = compSectionsList.querySelector(`.tl-block[data-idx="${el.dataset.idx}"] .tl-block-label`);
      if (lbl) lbl.textContent = el.value;
    }));
    compSectionsList.querySelectorAll(".comp-pos").forEach(el => el.addEventListener("input", () => setArr(+el.dataset.idx, "positive_local_styles", el.value)));
    compSectionsList.querySelectorAll(".comp-neg").forEach(el => el.addEventListener("input", () => setArr(+el.dataset.idx, "negative_local_styles", el.value)));
  }
  window._renderCompSections = _renderCompSections;

  async function _planCompositionSections() {
    const prompt = promptEl.value.trim();
    if (!prompt) { showError("Enter a prompt first."); return false; }
    if (compSectionsList) compSectionsList.innerHTML =
      `<div class="canvas-empty"><div class="canvas-empty-icon tl-spin">✦</div>
        <p class="canvas-empty-title">Designing your arrangement…</p>
        <p class="canvas-empty-sub">Claude is composing the sections from your prompt.</p></div>`;
    if (btnPlanSections) btnPlanSections.disabled = true;
    try {
      const res = await fetch("/api/compose-plan", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, music_length: parseFloat(musicLengthEl.value) || 10 }),
      });
      const data = await res.json();
      if (data.error) { showError("Plan failed: " + data.error); _renderCompSections(window._compositionPlan); return false; }
      if (data.composition_plan) { _selectedSection = 0; _renderCompSections(data.composition_plan); return true; }
      _renderCompSections(window._compositionPlan); return false;
    } catch (e) { showError("Plan failed: " + e.message); _renderCompSections(window._compositionPlan); return false; }
    finally { if (btnPlanSections) btnPlanSections.disabled = false; }
  }
  window._planCompositionSections = _planCompositionSections;
  btnPlanSections?.addEventListener("click", _planCompositionSections);

  // Auto-grow the prompt textarea so the full text is always visible
  function _autogrowPrompt() {
    if (!promptEl) return;
    promptEl.style.height = "auto";
    promptEl.style.height = Math.max(promptEl.scrollHeight, 120) + "px";
  }
  window._autogrowPrompt = _autogrowPrompt;
  promptEl?.addEventListener("input", _autogrowPrompt);

  _toggleCompSections();

  // ── Real credit balance from ElevenLabs API ──────
  const creditBarFill = document.getElementById("credit-bar-fill");
  const creditRemainingEl = document.getElementById("credit-remaining");
  const creditResetEl = document.getElementById("credit-reset");
  const creditRefreshBtn = document.getElementById("credit-refresh-btn");
  const creditSessionLog = document.getElementById("credit-session-log");
  const SESSION_LOG_KEY = "ambientizer_credit_log";

  let _lastBalance = null;

  function _creditsToUsd(credits) {
    if (!_lastBalance || !_lastBalance.usd_per_credit) return null;
    return credits * _lastBalance.usd_per_credit;
  }

  function _fmtUsd(usd) {
    if (usd === null || usd === undefined || isNaN(usd)) return null;
    if (usd < 0.01) return "<$0.01";
    if (usd < 1) return `$${usd.toFixed(2)}`;
    if (usd < 10) return `$${usd.toFixed(2)}`;
    return `$${usd.toFixed(2)}`;
  }

  function _costLabel(credits, sep = " · ") {
    const usd = _creditsToUsd(credits);
    const usdStr = _fmtUsd(usd);
    if (usdStr) return `${usdStr}${sep}~${credits.toLocaleString()} cr`;
    return `~${credits.toLocaleString()} credits`;
  }

  async function fetchCreditBalance() {
    if (creditRefreshBtn) {
      creditRefreshBtn.classList.add("spinning");
      setTimeout(() => creditRefreshBtn.classList.remove("spinning"), 600);
    }
    try {
      const r = await fetch("/api/credits");
      if (!r.ok) throw new Error("API error");
      const d = await r.json();
      _lastBalance = d;
      _renderCreditBalance(d);
      updateCreditEstimate();  // now that the USD rate is known, show $ in the price
      return d;
    } catch (e) {
      if (creditRemainingEl) creditRemainingEl.textContent = "Could not load balance";
      return null;
    }
  }

  function _renderCreditBalance(d) {
    if (!d || !creditBarFill) return;
    const pct = d.limit > 0 ? ((d.remaining / d.limit) * 100) : 0;
    creditBarFill.style.width = `${Math.max(0.5, pct)}%`;
    creditBarFill.classList.remove("bar-warn", "bar-danger", "bar-dead");
    if (pct <= 0) creditBarFill.classList.add("bar-dead");
    else if (pct < 5) creditBarFill.classList.add("bar-danger");
    else if (pct < 20) creditBarFill.classList.add("bar-warn");

    const fmt = (n) => n.toLocaleString();
    let cls = "";
    if (pct <= 0) cls = "credit-danger-text";
    else if (pct < 5) cls = "credit-danger-text";
    else if (pct < 20) cls = "credit-warn-text";

    // One clean line: just how much is left.
    let mainLine = `<span class="${cls}">${fmt(d.remaining)}</span> credits left`;
    if (d.usd_per_credit) {
      const remainingUsd = d.remaining * d.usd_per_credit;
      mainLine = `<span class="${cls}">$${remainingUsd.toFixed(2)}</span> left`;
    }
    creditRemainingEl.innerHTML = mainLine;
    if (creditResetEl) creditResetEl.textContent = "";  // reset date removed — too noisy
  }

  async function fetchGeminiUsage() {
    const el = document.getElementById("gemini-usage-text");
    if (!el) return;
    try {
      const r = await fetch("/api/gemini-usage");
      if (!r.ok) return;
      const d = await r.json();
      const rpmPct = d.rpm_limit > 0 ? (d.rpm_used / d.rpm_limit * 100) : 0;
      const rpdPct = d.rpd_limit > 0 ? (d.rpd_used / d.rpd_limit * 100) : 0;
      let cls = "";
      if (rpdPct >= 100) cls = "credit-danger-text";
      else if (rpdPct >= 80) cls = "credit-warn-text";
      el.innerHTML = `<span class="${cls}">${d.rpd_used}/${d.rpd_limit} today</span> · ${d.rpm_used}/${d.rpm_limit} rpm`;
    } catch (_) {}
  }

  function _canAfford(cost) {
    if (!_lastBalance) return true;
    return _lastBalance.remaining >= cost;
  }

  function _getSessionLog() {
    try {
      const raw = JSON.parse(localStorage.getItem(SESSION_LOG_KEY) || "{}");
      const today = new Date().toISOString().slice(0, 10);
      if (raw.date !== today) return { date: today, entries: [], total: 0 };
      return raw;
    } catch (_) { return { date: new Date().toISOString().slice(0, 10), entries: [], total: 0 }; }
  }

  function _trackCredits(amount, label) {
    const log = _getSessionLog();
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    log.entries.push({ time, label: label || "Action", amount });
    log.total += amount;
    try { localStorage.setItem(SESSION_LOG_KEY, JSON.stringify(log)); } catch (_) {}
    _renderSessionLog();
    if (_lastBalance) {
      _lastBalance.remaining = Math.max(0, _lastBalance.remaining - amount);
      _lastBalance.used += amount;
      _renderCreditBalance(_lastBalance);
    }
  }

  function _renderSessionLog() {
    if (!creditSessionLog) return;
    const log = _getSessionLog();
    if (!log.entries.length) { creditSessionLog.innerHTML = ""; return; }
    const last5 = log.entries.slice(-5);
    creditSessionLog.innerHTML =
      last5.map(e => `<div class="log-entry">${e.time} — ${e.label}: ${_costLabel(e.amount, " · ")}</div>`).join("") +
      `<div class="log-entry" style="font-weight:600;">Session total: ${_costLabel(log.total, " · ")}</div>`;
  }

  if (creditRefreshBtn) creditRefreshBtn.addEventListener("click", () => { fetchCreditBalance(); fetchGeminiUsage(); });
  fetchCreditBalance();
  fetchGeminiUsage();
  _renderSessionLog();

  // ── Auto-save form state to localStorage ─────
  const FORM_KEY = "ambientizer_form";
  const SAVED_PROMPTS_KEY = "ambientizer_saved_prompts";

  function saveFormState() {
    const state = {
      prompt: promptEl.value,
      mode: currentMode,
      approach: currentApproach,
      stem_separation: currentStemSeparation,
      planner_mode: plannerModeEl?.value || "claude",
      music_generation_mode: musicGenerationModeEl?.value || "text",
      music_length: musicLengthEl.value,
      reference_url: referenceUrlEl.value,
      ref_start: refStartEl.value,
      ref_end: refEndEl.value,
      ref_use_generation: useReferenceGenerationEl?.checked || false,
    };
    try { localStorage.setItem(FORM_KEY, JSON.stringify(state)); } catch (_) {}
  }

  function restoreFormState() {
    try {
      const raw = localStorage.getItem(FORM_KEY);
      if (!raw) return;
      const s = JSON.parse(raw);
      if (s.prompt) { promptEl.value = s.prompt; _autogrowPrompt(); }
      if (s.mode) {
        currentMode = s.mode;
        modeButtons.forEach(b => b.classList.toggle("active", b.dataset.mode === s.mode));
      }
      if (s.approach) {
        currentApproach = s.approach;
        document.querySelectorAll("[data-approach]").forEach(b =>
          b.classList.toggle("active", b.dataset.approach === s.approach));
      }
      if (s.stem_separation) {
        currentStemSeparation = s.stem_separation;
        const stemEl = document.getElementById("stem-separation");
        if (stemEl) stemEl.value = s.stem_separation;
      }
      if (plannerModeEl && s.planner_mode) plannerModeEl.value = s.planner_mode;
      if (musicGenerationModeEl && s.music_generation_mode) musicGenerationModeEl.value = s.music_generation_mode;
      if (typeof _toggleCompSections === "function") _toggleCompSections();
      if (s.composition_plan && s.composition_plan.sections) _renderCompSections(s.composition_plan);
      else { window._compositionPlan = null; _renderCompSections(null); }
      if (s.music_length) musicLengthEl.value = s.music_length;
      if (s.reference_url) referenceUrlEl.value = s.reference_url;
      if (s.ref_start) refStartEl.value = s.ref_start;
      if (s.ref_end) refEndEl.value = s.ref_end;
      if (useReferenceGenerationEl) useReferenceGenerationEl.checked = s.ref_use_generation === true;
      _updateApproachVisibility();
    } catch (_) {}
  }

  promptEl.addEventListener("input", saveFormState);
  musicLengthEl.addEventListener("change", saveFormState);
  if (plannerModeEl) plannerModeEl.addEventListener("change", saveFormState);
  if (musicGenerationModeEl) musicGenerationModeEl.addEventListener("change", saveFormState);
  referenceUrlEl.addEventListener("input", saveFormState);
  refStartEl.addEventListener("change", saveFormState);
  refEndEl.addEventListener("change", saveFormState);
  if (useReferenceGenerationEl) useReferenceGenerationEl.addEventListener("change", saveFormState);
  restoreFormState();
  updateCreditEstimate();

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
        promptEl.value = p.prompt; _autogrowPrompt();
        if (p.mode) {
          currentMode = p.mode;
          modeButtons.forEach(b => b.classList.toggle("active", b.dataset.mode === p.mode));
        }
        if (p.music_length) musicLengthEl.value = p.music_length;
        if (p.reference_url) referenceUrlEl.value = p.reference_url;
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
        music_length: musicLengthEl.value,
        reference_url: referenceUrlEl.value,
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
      _updateApproachVisibility();
      if (typeof _toggleCompSections === "function") _toggleCompSections();
      saveFormState();
      updateCreditEstimate();
    });
  });

  // ── Approach toggle (Unified / Multi-Layer) ──────
  const approachButtons = document.querySelectorAll("[data-approach]");
  approachButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      approachButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentApproach = btn.dataset.approach;
      _updateApproachVisibility();
      saveFormState();
      updateCreditEstimate();
    });
  });

  const stemSelectEl = document.getElementById("stem-separation");
  if (stemSelectEl) {
    currentStemSeparation = stemSelectEl.value;
    stemSelectEl.addEventListener("change", () => {
      currentStemSeparation = stemSelectEl.value;
      saveFormState();
      updateCreditEstimate();
    });
  }

  function _updateApproachVisibility() {
    const musicExperimentGroup = document.getElementById("music-experiment-group");
    if (currentMode === "musical") {
      musicExperimentGroup.classList.remove("hidden");
    } else {
      musicExperimentGroup.classList.add("hidden");
    }
  }

  const stageProgress = {
    starting: 5,
    analyzing_reference: 10,
    interpreting: 20,
    generating_samples: 40,
    rendering: 65,
    mastering: 85,
    separating_stems: 95,
    complete: 100,
    error: 100,
    canceled: 100,
  };

  // ── Enhance & Plan ──────────────────────────────
  const btnEnhancePrompt = document.getElementById("btn-enhance-prompt");
  const enhanceStatus = document.getElementById("enhance-status");
  const planPreview = document.getElementById("plan-preview");

  function _renderPlanPreview(layers) {
    if (!layers || !layers.length) {
      planPreview.classList.add("hidden");
      currentLayerPlan = null;
      return;
    }
    currentLayerPlan = layers;
    const esc = s => (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    const typeIcons = { musical: "\u{1F3B5}", base: "\u{1F30A}", mid: "\u{1F33F}", detail: "\u2728" };

    let totalCost = 0;
    let html = '<div class="plan-header"><span class="plan-title">Layer Plan</span><button id="btn-clear-plan" class="plan-clear-btn" title="Clear plan">&times;</button></div>';
    html += '<div class="plan-cards">';
    layers.forEach((l, i) => {
      totalCost += l.est_credits || 0;
      const icon = typeIcons[l.type] || "\u{1F50A}";
      const chips = (l.instruments || []).map(inst =>
        `<span class="plan-chip" data-layer="${i}" data-inst="${esc(inst)}">${esc(inst)} <button class="plan-chip-x" data-layer="${i}" data-inst="${esc(inst)}">&times;</button></span>`
      ).join("");
      html += `<div class="plan-card" data-idx="${i}">
        <div class="plan-card-header">
          <span class="plan-card-icon">${icon}</span>
          <input class="plan-card-name" value="${esc(l.name)}" data-idx="${i}">
          <span class="plan-card-role">${esc(l.role)}</span>
          <span class="layer-type-badge ${l.type}">${l.type}</span>
          <span class="plan-card-cost">${_costLabel(l.est_credits||0, " · ")}</span>
          <button class="plan-card-remove" data-idx="${i}" title="Remove layer">&times;</button>
        </div>
        <div class="plan-card-instruments">${chips}
          <input class="plan-add-inst" data-idx="${i}" placeholder="+ instrument" size="10">
        </div>
        <textarea class="plan-card-prompt" data-idx="${i}" rows="2">${esc(l.prompt_preview)}</textarea>
      </div>`;
    });
    html += '</div>';
    html += `<div class="plan-footer">
      <span class="plan-total">Total: ${_costLabel(totalCost, " · ")}</span>
      <button id="btn-replan" class="btn btn-enhance">Re-Plan</button>
    </div>`;
    planPreview.innerHTML = html;
    planPreview.classList.remove("hidden");

    planPreview.querySelector("#btn-clear-plan")?.addEventListener("click", () => {
      currentLayerPlan = null;
      planPreview.classList.add("hidden");
    });

    planPreview.querySelectorAll(".plan-card-remove").forEach(btn => {
      btn.addEventListener("click", () => {
        currentLayerPlan.splice(parseInt(btn.dataset.idx), 1);
        _renderPlanPreview(currentLayerPlan);
      });
    });

    planPreview.querySelectorAll(".plan-card-name").forEach(inp => {
      inp.addEventListener("change", () => {
        currentLayerPlan[parseInt(inp.dataset.idx)].name = inp.value;
      });
    });

    planPreview.querySelectorAll(".plan-card-prompt").forEach(ta => {
      ta.addEventListener("change", () => {
        currentLayerPlan[parseInt(ta.dataset.idx)].prompt_preview = ta.value;
      });
    });

    planPreview.querySelectorAll(".plan-chip-x").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.layer);
        const inst = btn.dataset.inst;
        const layer = currentLayerPlan[idx];
        layer.instruments = layer.instruments.filter(i => i !== inst);
        _renderPlanPreview(currentLayerPlan);
      });
    });

    planPreview.querySelectorAll(".plan-add-inst").forEach(inp => {
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && inp.value.trim()) {
          e.preventDefault();
          currentLayerPlan[parseInt(inp.dataset.idx)].instruments.push(inp.value.trim());
          _renderPlanPreview(currentLayerPlan);
        }
      });
    });

    planPreview.querySelector("#btn-replan")?.addEventListener("click", () => {
      btnEnhancePrompt.click();
    });
  }

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
        body: JSON.stringify({
          prompt: raw,
          mode: currentMode,
          approach: currentApproach,
        }),
      });
      const data = await res.json();
      if (data.error) {
        enhanceStatus.textContent = data.error;
        enhanceStatus.className = "enhance-status error";
      } else {
        promptEl.value = data.enhanced_prompt;
        _autogrowPrompt();
        // Unified flow: ONE plan artifact at a time.
        //  Composition plan → timeline (hide the layer plan)
        //  Ambient / Text   → layer plan
        const wantsPlan = currentMode === "musical" && musicGenerationModeEl?.value === "composition_plan";
        if (wantsPlan) {
          if (planPreview) planPreview.classList.add("hidden");
          enhanceStatus.textContent = "Designing composition timeline…";
          btnEnhancePrompt.textContent = "Planning…";
          await _planCompositionSections();
          enhanceStatus.textContent = "Enhanced + composition timeline ready";
        } else if (data.layers && data.layers.length) {
          _renderPlanPreview(data.layers);
          enhanceStatus.textContent = "Enhanced + layer plan ready";
        } else {
          enhanceStatus.textContent = data.research_summary ? "Enhanced with web research" : "Enhanced";
        }
        enhanceStatus.className = "enhance-status success";
        setTimeout(() => { enhanceStatus.textContent = ""; enhanceStatus.className = "enhance-status"; }, 5000);
      }
    } catch (err) {
      enhanceStatus.textContent = "Enhancement failed: " + err.message;
      enhanceStatus.className = "enhance-status error";
    }
    btnEnhancePrompt.disabled = false;
    btnEnhancePrompt.textContent = "✦ Enhance & Plan";
  });

  // ── Reference Analysis (pre-generate) ────────
  const btnAnalyzeRef = document.getElementById("btn-analyze-ref");
  const analyzeRefStatus = document.getElementById("analyze-ref-status");
  const refAnalysisPanel = document.getElementById("ref-analysis-panel");
  const refAnalysisSummary = document.getElementById("ref-analysis-summary");
  const refAnalysisLayers = document.getElementById("ref-analysis-layers");
  const refSuggestedPrompt = document.getElementById("ref-suggested-prompt");
  const btnRefUse = document.getElementById("btn-ref-use");
  const btnRefMerge = document.getElementById("btn-ref-merge");
  const btnRefClose = document.getElementById("btn-ref-close");

  let _lastRefSuggested = "";
  let _lastRefAnalysis = null;
  let _lastRefSignature = "";

  function _referenceSignature() {
    return JSON.stringify({
      url: referenceUrlEl.value.trim(),
      start: parseTimestamp(refStartEl.value),
      end: parseTimestamp(refEndEl.value),
    });
  }

  if (btnAnalyzeRef) {
    btnAnalyzeRef.addEventListener("click", async () => {
      const url = referenceUrlEl.value.trim();
      if (!url) { referenceUrlEl.focus(); return; }

      btnAnalyzeRef.disabled = true;
      btnAnalyzeRef.textContent = "Analyzing...";
      analyzeRefStatus.textContent = "Gemini is listening to the audio...";
      analyzeRefStatus.className = "enhance-status active";
      refAnalysisPanel.classList.add("hidden");

      try {
        const res = await fetch("/api/analyze-reference", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url,
            start_sec: parseTimestamp(refStartEl.value),
            end_sec: parseTimestamp(refEndEl.value),
          }),
        });
        const data = await res.json();
        if (data.error) {
          analyzeRefStatus.textContent = data.error;
          analyzeRefStatus.className = "enhance-status error";
        } else {
          refAnalysisSummary.textContent = data.summary || "";
          refAnalysisLayers.innerHTML = (data.layers || []).map(l =>
            `<span class="ref-layer-tag ${l.type}">${l.name}</span>`
          ).join("");
          _lastRefSuggested = data.suggested_prompt || "";
          _lastRefAnalysis = data.analysis || null;
          _lastRefSignature = _referenceSignature();
          refSuggestedPrompt.textContent = _lastRefSuggested;
          refAnalysisPanel.classList.remove("hidden");
          analyzeRefStatus.textContent = "Analysis complete";
          analyzeRefStatus.className = "enhance-status success";
        }
      } catch (err) {
        analyzeRefStatus.textContent = "Analysis failed — check connection";
        analyzeRefStatus.className = "enhance-status error";
      }
      btnAnalyzeRef.disabled = false;
      btnAnalyzeRef.textContent = "Analyze";
    });
  }

  if (btnRefUse) {
    btnRefUse.addEventListener("click", () => {
      if (_lastRefSuggested) {
        promptEl.value = _lastRefSuggested;
        promptEl.style.height = "auto";
        promptEl.style.height = promptEl.scrollHeight + "px";
        saveFormState();
        analyzeRefStatus.textContent = "Prompt replaced with reference suggestion";
        analyzeRefStatus.className = "enhance-status success";
        setTimeout(() => { analyzeRefStatus.textContent = ""; analyzeRefStatus.className = "enhance-status"; }, 3000);
      } else {
        analyzeRefStatus.textContent = "No suggested prompt available from reference analysis";
        analyzeRefStatus.className = "enhance-status error";
      }
    });
  }

  if (btnRefMerge) {
    btnRefMerge.addEventListener("click", () => {
      if (_lastRefSuggested) {
        const current = promptEl.value.trim();
        promptEl.value = current ? `${current}\n\n${_lastRefSuggested}` : _lastRefSuggested;
        promptEl.style.height = "auto";
        promptEl.style.height = promptEl.scrollHeight + "px";
        saveFormState();
        analyzeRefStatus.textContent = "Reference suggestion merged into prompt";
        analyzeRefStatus.className = "enhance-status success";
        setTimeout(() => { analyzeRefStatus.textContent = ""; analyzeRefStatus.className = "enhance-status"; }, 3000);
      } else {
        analyzeRefStatus.textContent = "No suggested prompt available from reference analysis";
        analyzeRefStatus.className = "enhance-status error";
      }
    });
  }

  if (btnRefClose) {
    btnRefClose.addEventListener("click", () => {
      refAnalysisPanel.classList.add("hidden");
      analyzeRefStatus.textContent = "";
      analyzeRefStatus.className = "enhance-status";
    });
  }

  // ── Generate ──────────────────────────────────
  generateBtn.addEventListener("click", async () => {
    const prompt = promptEl.value.trim();
    if (!prompt) {
      promptEl.focus();
      return;
    }

    const c = _getCreditCosts();
    if (!_canAfford(c.total)) {
      alert(`Not enough credits. Need ${_costLabel(c.total)} but only ${_costLabel(_lastBalance?.remaining || 0)} remaining.\n\nAdd credits at elevenlabs.io/subscription`);
      return;
    }
    let confirmMsg = `This will use ${_costLabel(c.total)} (${c.musicLayers} music @ ${(c.musicSec/60).toFixed(0)}min + ${c.sfxLayers} SFX @ 5s`;
    if (c.stemCost > 0) confirmMsg += ` + stems ${_costLabel(c.stemCost)}`;
    confirmMsg += `). Generate?`;
    if (!confirm(confirmMsg)) return;

    _trackCredits(c.total, "Generate");
    generateBtn.disabled = true;
    generateBtn.textContent = "Generating...";
    stopGenerationBtn.classList.remove("hidden");
    stopGenerationBtn.disabled = false;

    progressPanel.classList.remove("hidden");
    playerPanel.classList.add("hidden");
    layersPanel.classList.add("hidden");
    feedbackPanel.classList.add("hidden");
    resetProgress();

    try {
      const genBody = {
          prompt,
          duration: getDerivedTrackMinutes(),
          music_length: parseFloat(musicLengthEl.value),
          mastering: true,
          mode: currentMode,
          approach: currentApproach,
          stem_separation: (currentMode === "musical" && currentApproach === "unified") ? currentStemSeparation : "none",
          planner_mode: plannerModeEl?.value || "claude",
          music_generation_mode: musicGenerationModeEl?.value || "text",
          reference_url: useReferenceGenerationEl?.checked ? referenceUrlEl.value.trim() : "",
          ref_start_sec: parseTimestamp(refStartEl.value),
          ref_end_sec: parseTimestamp(refEndEl.value),
          loopable: true,
      };
      if (currentLayerPlan) genBody.layer_plan = currentLayerPlan;
      // Send the visible/edited composition plan so what-you-see-is-what-generates.
      if (musicGenerationModeEl?.value === "composition_plan" &&
          window._compositionPlan && window._compositionPlan.sections?.length) {
        genBody.composition_plan = window._compositionPlan;
      }
      const plannerUsesReference = genBody.planner_mode === "reference_direct";
      if ((useReferenceGenerationEl?.checked || plannerUsesReference) && _lastRefAnalysis && _lastRefSignature === _referenceSignature()) {
        genBody.reference_analysis = _lastRefAnalysis;
      }
      if (plannerUsesReference && !genBody.reference_analysis) {
        showError("Reference Direct requires Analyze Reference first, with the same URL/timestamps.");
        generateBtn.disabled = false;
        generateBtn.textContent = "Generate Soundscape";
        stopGenerationBtn.classList.add("hidden");
        return;
      }
      console.log("[Generate] Sending:", JSON.stringify({mode: genBody.mode, approach: genBody.approach, planner_mode: genBody.planner_mode, music_generation_mode: genBody.music_generation_mode, stem_separation: genBody.stem_separation, has_plan: !!genBody.layer_plan, use_reference: !!genBody.reference_url, has_reference_analysis: !!genBody.reference_analysis}));
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(genBody),
      });

      const data = await res.json();
      if (data.error) {
        showError(data.error);
        return;
      }

      currentJobId = data.job_id;
      refreshHistory();
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

        if (data.status === "complete" || data.status === "error" || data.status === "canceled") {
          clearInterval(pollInterval);
          pollInterval = null;
          generateBtn.disabled = false;
          generateBtn.textContent = "Generate Soundscape";
          stopGenerationBtn.classList.add("hidden");
          stopGenerationBtn.disabled = false;
          stopGenerationBtn.textContent = "Stop";

          if (data.status === "complete") {
            currentJobId = jobId; visCurrentJobId = jobId; pubCurrentJobId = jobId;
            showPlayer(data);
            enableFeedback();
            if (typeof loadVisualsForTrack === "function") loadVisualsForTrack(jobId, data);
            if (typeof loadPublishForTrack === "function") loadPublishForTrack(jobId, data);
            // Jump to the Listen tab so the finished track is front-and-center.
            const listenBtn = document.querySelector('.tab-btn[data-tab="listen"]');
            if (listenBtn) listenBtn.click();
            if (data.stems_status === "processing") {
              startStemPolling(jobId);
            }
          } else if (data.status === "canceled") {
            progressMessage.textContent = data.progress_message || "Generation stopped";
            progressStage.textContent = "Stopped";
            progressStage.className = "stage-badge canceled";
          } else if (data.status === "error") {
            const errMsg = data.error || "Generation failed";
            progressMessage.textContent = errMsg;
            progressStage.textContent = "Error";
            progressStage.className = "stage-badge error";
            addChatMessage("system", `Generation failed: ${errMsg}`);
          }

          refreshHistory();
        }
      } catch (err) {
        console.error("Poll error:", err);
      }
    }, 2000);
  }

  function startStemPolling(jobId) {
    if (stemPollInterval) clearInterval(stemPollInterval);
    progressMessage.textContent = "Stems separating in background — you can listen now";
    stemPollInterval = setInterval(async () => {
      try {
        const res = await fetch(`/api/status/${jobId}`);
        const data = await res.json();
        if (data.stems_status === "ready" && data.stems) {
          clearInterval(stemPollInterval);
          stemPollInterval = null;
          _currentStems = data.stems;
          progressMessage.textContent = "Stems ready";
          if (currentLayers && currentLayers.length) renderLayers(currentLayers);
          addChatMessage("system", "Stem separation finished — expand a music layer to mix stems.");
        } else if (data.stems_status === "failed") {
          clearInterval(stemPollInterval);
          stemPollInterval = null;
          addChatMessage("system", `Stem separation failed: ${data.stems_error || "unknown error"}`);
        }
      } catch (err) {
        console.warn("Stem poll error:", err);
      }
    }, 3000);
  }

  // ── Progress ──────────────────────────────────
  function resetProgress() {
    progressStage.textContent = "Starting";
    progressStage.className = "stage-badge";
    progressMessage.textContent = "";
    progressBar.style.width = "0%";
    progressBar.classList.add("indeterminate");
    progressBar.style.background = "";
    logContainer.innerHTML = "";
  }

  function updateProgress(data) {
    progressStage.textContent = formatStage(data.stage);
    if (data.status === "complete") progressStage.className = "stage-badge complete";
    else if (data.status === "error") progressStage.className = "stage-badge error";
    else if (data.status === "canceled") progressStage.className = "stage-badge canceled";
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
      separating_stems: "Separating Stems",
      canceled: "Stopped",
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
    stopGenerationBtn.classList.add("hidden");
    stopGenerationBtn.disabled = false;
    stopGenerationBtn.textContent = "Stop";
  }

  if (stopGenerationBtn) {
    stopGenerationBtn.addEventListener("click", async () => {
      if (!currentJobId) return;
      stopGenerationBtn.disabled = true;
      stopGenerationBtn.textContent = "Stopping...";
      try {
        const res = await fetch(`/api/cancel/${currentJobId}`, { method: "POST" });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        progressStage.textContent = "Stopped";
        progressStage.className = "stage-badge canceled";
        progressMessage.textContent = "Generation stop requested";
      } catch (err) {
        stopGenerationBtn.disabled = false;
        stopGenerationBtn.textContent = "Stop";
        showError("Could not stop generation: " + err.message);
      }
    });
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

  function _setSeekLoopMarker(frac) {
    if (!transportSeek || !transportSeek.parentElement) return;
    const parent = transportSeek.parentElement;
    const style = window.getComputedStyle(parent);
    if (style.position === "static") parent.style.position = "relative";

    let marker = document.getElementById("seek-loop-marker");
    if (!marker) {
      marker = document.createElement("div");
      marker.id = "seek-loop-marker";
      marker.title = "Loop wrap point";
      Object.assign(marker.style, {
        position: "absolute",
        top: "0",
        bottom: "0",
        width: "2px",
        background: "rgba(120, 200, 255, 0.85)",
        pointerEvents: "none",
        boxShadow: "0 0 6px rgba(120, 200, 255, 0.7)",
        zIndex: "2",
      });
      parent.appendChild(marker);
    }

    const place = () => {
      const parentRect = parent.getBoundingClientRect();
      const sliderRect = transportSeek.getBoundingClientRect();
      if (parentRect.width === 0 || sliderRect.width === 0) {
        requestAnimationFrame(place);
        return;
      }
      // Slider thumb travels from (left + thumbW/2) to (right - thumbW/2).
      // Approximate thumb width based on the slider's height.
      const thumbW = Math.max(12, sliderRect.height);
      const trackLeft = sliderRect.left - parentRect.left + thumbW / 2;
      const trackWidth = sliderRect.width - thumbW;
      const px = trackLeft + trackWidth * frac;
      marker.style.left = `${px}px`;
    };
    place();
    window.addEventListener("resize", place, { passive: true });
  }

  if (btnPlayPause) {
    btnPlayPause.addEventListener("click", () => {
      if (usingAudioElement) {
        // A tap here is the iOS user-gesture: build + resume the Web Audio graph.
        _ensureElementAudioGraph();
        _resumeElementCtx();
        if (audioPlayer.paused) audioPlayer.play().catch(() => {}); else audioPlayer.pause();
        return; // icons handled by audioPlayer onplay/onpause
      }
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
      if (usingAudioElement) {
        const d = audioPlayer.duration || 0;
        transportCurrent.textContent = formatTime((parseFloat(transportSeek.value) / 1000) * d);
        return;
      }
      if (!mixer) return;
      const t = (parseFloat(transportSeek.value) / 1000) * mixer.duration;
      transportCurrent.textContent = formatTime(t);
    });
    transportSeek.addEventListener("change", () => {
      if (usingAudioElement) {
        const d = audioPlayer.duration || 0;
        audioPlayer.currentTime = (parseFloat(transportSeek.value) / 1000) * d;
        seeking = false;
        return;
      }
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

  // ── Volume slider ──
  const transportVolume = document.getElementById("transport-volume");
  if (transportVolume) {
    transportVolume.value = String(Math.round(getSavedMasterVolume() * 100));
    transportVolume.addEventListener("input", () => {
      setSavedMasterVolume(parseFloat(transportVolume.value) / 100);
    });
  }

  // ── Loop toggle ──
  const btnLoopToggle = document.getElementById("btn-loop-toggle");
  if (btnLoopToggle) {
    btnLoopToggle.addEventListener("click", () => {
      if (usingAudioElement) {
        audioPlayer.loop = !audioPlayer.loop;
        btnLoopToggle.classList.toggle("active", audioPlayer.loop);
        btnLoopToggle.title = audioPlayer.loop ? "Loop: ON" : "Loop: OFF";
        return;
      }
      if (!mixer) return;
      const looping = mixer.toggleLoop();
      btnLoopToggle.classList.toggle("active", looping);
      btnLoopToggle.title = looping ? "Loop: ON" : "Loop: OFF";
    });
  }

  // Click-to-seek on any layer timeline bar
  document.addEventListener("click", (e) => {
    const track = e.target.closest(".timeline-track");
    if (!track || !mixer) return;
    const rect = track.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const targetSec = frac * mixer.duration;
    mixer.seek(targetSec);
    if (transportSeek) transportSeek.value = Math.round(frac * 1000);
    if (transportCurrent) transportCurrent.textContent = formatTime(targetSec);
  });

  async function initMixer(jobId, layers, durationSec, autoplay = true) {
    usingAudioElement = false;
    if (audioPlayer) { audioPlayer.pause(); audioPlayer.removeAttribute("src"); }
    if (mixer) mixer.destroy();
    mixer = new LiveMixer();
    await mixer.init(durationSec);
    mixer.setMasterVolume(getSavedMasterVolume());

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
      iconPlay.classList.toggle("hidden", mixer.playing);
      iconPause.classList.toggle("hidden", !mixer.playing);
    };
    transportTotal.textContent = formatTime(durationSec);

    const layersWithAudio = layers.filter(l => l.has_audio);
    const failedLayers = [];
    const loadPromises = layersWithAudio.map(l => {
      // full_mix_url lets us play the whole-track mix (unified tracks) through
      // Web Audio — the path proven to actually output sound on iOS.
      const url = l.full_mix_url || `/api/audio/${jobId}/layer/${encodeURIComponent(l.name)}`;
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
        repeat_every_sec: l.repeat_every_sec || 0,
      }).catch(err => {
        console.error(`[Mixer] Failed to load layer "${l.name}":`, err);
        failedLayers.push(l.name);
      });
    });

    await Promise.all(loadPromises);
    const loaded = Object.keys(mixer.layers).length;
    console.log(`[Mixer] Loaded ${loaded}/${layersWithAudio.length} layers (${layers.length} total, ${layers.length - layersWithAudio.length} without audio)`);
    if (loaded > 0) {
      const loopLengths = Object.values(mixer.layers)
        .map(l => l.buffer?.duration || 0)
        .filter(d => d > 0);
      if (loopLengths.length) {
        const maxLoop = Math.max(...loopLengths);
        const minLoop = Math.min(...loopLengths);
        console.log(`[Mixer] Layer loop lengths: ${minLoop.toFixed(1)}s–${maxLoop.toFixed(1)}s`);
        // Set the player to 2x the loop length so the wrap point lands at
        // the midpoint of the transport bar — listener can hear the loop
        // boundary in context without watching the clock.
        const previewDur = maxLoop * 2;
        mixer.duration = previewDur;
        currentTrackDuration = previewDur;
        transportTotal.textContent = formatTime(previewDur);
        _setSeekLoopMarker(0.5);
        console.log(`[Mixer] Player duration set to 2x loop = ${previewDur.toFixed(1)}s (wrap at ${maxLoop.toFixed(1)}s)`);
      }
    }
    if (failedLayers.length > 0) {
      console.error(`[Mixer] Failed layers:`, failedLayers);
      markLayerLoadFailures(failedLayers);
    }

    if (_currentStems) {
      const silentStems = [];
      const stemPromises = Object.entries(_currentStems).map(async ([stemName, stemUrl]) => {
        const mixerName = `stem:${stemName}`;
        try {
          await mixer.addLayer(mixerName, stemUrl, {
            volume_db: -6,
            pan: 0,
            muted: true,
          });
          const layer = mixer.layers[mixerName];
          if (layer && layer.buffer) {
            let peak = 0;
            for (let ch = 0; ch < layer.buffer.numberOfChannels; ch++) {
              const data = layer.buffer.getChannelData(ch);
              const step = Math.max(1, Math.floor(data.length / 10000));
              for (let i = 0; i < data.length; i += step) {
                const abs = Math.abs(data[i]);
                if (abs > peak) peak = abs;
              }
            }
            if (peak < 0.001) {
              silentStems.push(stemName);
              console.log(`[Mixer] Stem "${stemName}" is silent (peak=${peak.toFixed(6)}) — hiding`);
            }
          }
        } catch (err) {
          console.warn(`[Mixer] Failed to load stem "${stemName}":`, err);
          silentStems.push(stemName);
        }
      });
      await Promise.all(stemPromises);
      if (silentStems.length > 0) {
        for (const s of silentStems) delete _currentStems[s];
      }
      const remaining = Object.keys(_currentStems).length;
      console.log(`[Mixer] Loaded ${remaining} audible stems (${silentStems.length} silent, hidden)`);
      if (remaining === 0) _currentStems = null;
    }

    liveTransport.classList.remove("hidden");
    audioPlayer.classList.add("hidden");
    mixerBadge.classList.remove("hidden");

    // Match the YouTube export: 5s fade-in on play, 5s fade-out near the end
    // of the displayed duration, then fade back in on wrap. Lets the user
    // preview what the exported file's intro/outro will actually sound like.
    mixer.setMasterFades(5, 5);
    if (autoplay) {
      mixer.play();
      iconPlay.classList.add("hidden");
      iconPause.classList.remove("hidden");
    } else {
      // Loaded but paused (e.g. preloaded on startup) — show the play icon.
      iconPlay.classList.remove("hidden");
      iconPause.classList.add("hidden");
    }
  }

  let _currentStems = null;

  function showPlayer(data, autoplay = true) {
    window._currentTrackData = data;
    try { if (data && data.job_id) localStorage.setItem("ambientizer_last_track", data.job_id); } catch (e) {}
    const gp = document.getElementById("global-player");
    if (gp) gp.classList.remove("hidden");
    playerPanel.classList.remove("hidden");
    playerPrompt.textContent = `"${data.prompt}"`;
    fetchCreditBalance();
    btnDownload.onclick = () => finalizeAndDownload(data.job_id);
    if (btnReprepLoop) {
      btnReprepLoop.onclick = () => reprepLoopForJob(data);
    }
    if (data.root_key) currentRootKey = data.root_key;
    _currentStems = data.stems || null;
    const playable = (data.layers || []).filter(l => l.has_audio);
    if (playable.length) {
      const durationSec = (data.duration || 5) * 60;
      currentTrackDuration = durationSec;
      renderLayers(data.layers);
      initMixer(data.job_id, data.layers, durationSec, autoplay).then(() => {
        const altPairs = data.alternate_pairs || [];
        for (const p of altPairs) {
          if (mixer) mixer.setAlternate(p.layer_a, p.layer_b, p.cycle_sec, p.xfade_sec);
        }
        if (window._restoreTimingStateGlobal) window._restoreTimingStateGlobal();
        renderLayers(data.layers);
      }).catch(err => {
        console.warn("LiveMixer init failed, streaming full mix instead:", err);
        initAudioElementPlayer(data.job_id, autoplay);
      });
    } else {
      // Unified track (only a full mix exists) → play through the NATIVE <audio>
      // element. Native media playback is clean on AirPods/Bluetooth; routing the
      // full mix through Web Audio produced a constant background buzz on iOS BT.
      // (The earlier "bare element is silent on iOS" finding was a red herring —
      // the test tracks happened to be silent files, not an element problem.)
      const durationSec = (data.duration || 5) * 60;
      currentTrackDuration = durationSec;
      if (data.layers && data.layers.length) renderLayers(data.layers);
      initAudioElementPlayer(data.job_id, autoplay);
    }
    aiFeedbackPanel.classList.remove("hidden");
    aiFeedbackResult.classList.add("hidden");
    partsPanel.classList.remove("hidden");
    loadParts();
  }

  // Stream the full mix through the <audio> element, driven by the global bar.
  // Used for unified tracks (no per-layer files) — and it's the mobile-safe path
  // since iOS can't decode a 100MB+ WAV into Web Audio.
  function initAudioElementPlayer(jobId, autoplay = true) {
    usingAudioElement = true;
    if (mixer) { mixer.destroy(); mixer = null; }
    if (liveTransport) liveTransport.classList.remove("hidden");
    if (mixerBadge) mixerBadge.classList.add("hidden");
    if (!audioPlayer) return;
    audioPlayer.classList.add("hidden");   // the bar is the controls, not the native element
    audioPlayer.loop = true;
    if (btnLoopToggle) { btnLoopToggle.classList.add("active"); btnLoopToggle.title = "Loop: ON"; }
    audioPlayer.onloadedmetadata = () => {
      if (transportTotal) transportTotal.textContent = formatTime(audioPlayer.duration || 0);
    };
    audioPlayer.ontimeupdate = () => {
      if (window._seekDragging && window._seekDragging()) return;
      const d = audioPlayer.duration || 0;
      if (transportCurrent) transportCurrent.textContent = formatTime(audioPlayer.currentTime);
      if (transportSeek) transportSeek.value = d ? Math.round((audioPlayer.currentTime / d) * 1000) : 0;
    };
    audioPlayer.onplay = () => { iconPlay.classList.add("hidden"); iconPause.classList.remove("hidden"); };
    audioPlayer.onpause = () => { iconPlay.classList.remove("hidden"); iconPause.classList.add("hidden"); };
    audioPlayer.src = `/api/audio/${jobId}?t=${Date.now()}`;
    audioPlayer.volume = getSavedMasterVolume();
    audioPlayer.load();
    _ensureElementAudioGraph();
    if (autoplay) {
      _resumeElementCtx();
      audioPlayer.play().catch(() => {});  // iOS may block until a tap; the bar play button then works
    } else {
      // Preloaded/paused — show the play icon so the bar invites a tap.
      iconPlay.classList.remove("hidden");
      iconPause.classList.add("hidden");
    }
  }
  window.initAudioElementPlayer = initAudioElementPlayer;

  function markLayerLoadFailures(failedNames) {
    document.querySelectorAll(".layer-card").forEach(card => {
      const name = card.dataset.name;
      if (failedNames.includes(name)) {
        let badge = card.querySelector(".layer-load-error");
        if (!badge) {
          badge = document.createElement("span");
          badge.className = "layer-load-error";
          badge.title = "Audio failed to load — try regenerating this layer";
          badge.textContent = "No audio";
          const header = card.querySelector(".layer-header") || card.firstElementChild;
          if (header) header.appendChild(badge);
        }
      }
    });
  }

  // ── Layer Inspector ────────────────────────────

  function _renderStemCards(layer, eName) {
    if (!_currentStems || layer.layer_type !== "musical") return "";
    const stemNames = Object.keys(_currentStems);
    if (!stemNames.length) return "";
    if (stemNames.length === 1 && stemNames[0] === "other") {
      return `<div class="stem-section" data-parent="${eName}">
        <p class="stem-note">Stem separation couldn't isolate individual instruments in this track. The audio may be too ambient/textural for the model to separate.</p>
      </div>`;
    }
    const prettyName = { bass: "Bass", drums: "Drums", guitar: "Guitar", piano: "Piano", vocals: "Vocals", other: "Other", instrumental: "Instrumental" };
    const stemIcon = { bass: "\u{1F3B8}", drums: "\u{1F941}", guitar: "\u{1F3B8}", piano: "\u{1F3B9}", vocals: "\u{1F399}", other: "\u{1F50A}", instrumental: "\u{1F3B6}" };
    return `<div class="stem-section" data-parent="${eName}">
      <button class="btn-stems-toggle" data-parent="${eName}">\u{1F3A4} Show ${stemNames.length} Stems</button>
      <div class="stem-cards hidden" data-parent="${eName}">
        ${stemNames.map(s => {
          const sName = escapeHtml(s);
          return `<div class="stem-card" data-stem="${sName}">
            <div class="stem-card-header">
              <span class="stem-icon">${stemIcon[s] || "\u{1F50A}"}</span>
              <span class="stem-name">${escapeHtml(prettyName[s] || s)}</span>
              <button class="stem-mute-btn muted" data-stem="${sName}" title="Stems start muted">Muted</button>
              <button class="stem-solo-btn" data-stem="${sName}" title="Solo this stem">S</button>
            </div>
            <div class="stem-sliders">
              <label class="stem-slider-label">Vol</label>
              <input type="range" class="stem-vol-slider" data-stem="${sName}" min="-40" max="6" step="1" value="-6">
              <span class="stem-vol-val" data-stem="${sName}">-6 dB</span>
            </div>
            <div class="stem-sliders">
              <label class="stem-slider-label">Pan</label>
              <input type="range" class="stem-pan-slider" data-stem="${sName}" min="-100" max="100" step="5" value="0">
              <span class="stem-pan-val" data-stem="${sName}">C</span>
            </div>
          </div>`;
        }).join("")}
      </div>
    </div>`;
  }

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
      const repeatEvery = l.repeat_every_sec || 0;
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
              <label class="tl-label tl-repeat-label">Repeat: <input type="number" class="tl-input tl-repeat" data-layer="${eName}" value="${repeatEvery > 0 ? (repeatEvery / 60).toFixed(1) : ""}" min="0" max="${(trackDur / 60).toFixed(0)}" step="0.5" placeholder="off"> min</label>
              <button class="tl-sporadic-btn" data-layer="${eName}" title="Make this layer appear sporadically">Sporadic</button>
              <button class="tl-alt-btn" data-layer="${eName}" title="Alternate this layer with another">Alt</button>
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
            <button class="layer-btn layer-btn-reroll" data-action="regenerate" data-layer="${eName}" title="${l.layer_type === 'musical' ? `Re-roll music (~${_costLabel(_getCreditCosts().perMusic)})` : `Re-roll SFX (~${_costLabel(_getCreditCosts().perSfx)})`}">Re-roll</button>
            <button class="layer-btn layer-btn-vary" data-action="vary" data-layer="${eName}" title="${l.layer_type === 'musical' ? `Create music variation (~${_costLabel(_getCreditCosts().perMusic)})` : `Create SFX variation (~${_costLabel(_getCreditCosts().perSfx)})`}">Vary</button>
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
          ${_renderStemCards(l, eName)}
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

    // Wire stem toggle buttons — mute parent layer when stems are shown,
    // restore parent when stems are hidden.
    layersList.querySelectorAll(".btn-stems-toggle").forEach(btn => {
      btn.addEventListener("click", () => {
        const parentName = btn.dataset.parent;
        const cards = layersList.querySelector(`.stem-cards[data-parent="${parentName}"]`);
        if (!cards) return;
        const hidden = cards.classList.toggle("hidden");
        const count = cards.querySelectorAll(".stem-card").length;
        btn.textContent = hidden ? `\u{1F3A4} Show ${count} Stems` : `\u{1F3A4} Hide Stems`;

        if (mixer && _currentStems) {
          if (!hidden) {
            // Showing stems — mute the parent, unmute all stems
            mixer.setMute(parentName, true);
            const parentMuteBtn = layersList.querySelector(`.layer-mute-btn[data-layer="${parentName}"]`);
            if (parentMuteBtn) { parentMuteBtn.textContent = "Muted"; parentMuteBtn.classList.add("muted"); }
            Object.keys(_currentStems).forEach(s => {
              const name = `stem:${s}`;
              if (mixer.hasLayer(name)) mixer.setMute(name, false);
            });
            cards.querySelectorAll(".stem-mute-btn").forEach(b => {
              b.textContent = "Playing"; b.classList.remove("muted");
            });
          } else {
            // Hiding stems — mute all stems, restore the parent
            Object.keys(_currentStems).forEach(s => {
              const name = `stem:${s}`;
              if (mixer.hasLayer(name)) mixer.setMute(name, true);
            });
            mixer.setMute(parentName, false);
            const parentMuteBtn = layersList.querySelector(`.layer-mute-btn[data-layer="${parentName}"]`);
            if (parentMuteBtn) { parentMuteBtn.textContent = "Playing"; parentMuteBtn.classList.remove("muted"); }
          }
        }
      });
    });

    // Wire stem controls
    layersList.querySelectorAll(".stem-mute-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const stemName = `stem:${btn.dataset.stem}`;
        if (!mixer || !mixer.hasLayer(stemName)) {
          console.warn(`[Stems] Layer "${stemName}" not in mixer`);
          return;
        }
        const isMuted = mixer.layers[stemName]?.muted;
        mixer.setMute(stemName, !isMuted);
        btn.textContent = !isMuted ? "Muted" : "Playing";
        btn.classList.toggle("muted", !isMuted);
      });
    });
    layersList.querySelectorAll(".stem-solo-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        if (!mixer || !_currentStems) return;
        const soloStem = `stem:${btn.dataset.stem}`;
        const allSoloed = btn.classList.contains("active");
        Object.keys(_currentStems).forEach(s => {
          const name = `stem:${s}`;
          if (!mixer.hasLayer(name)) return;
          if (allSoloed) {
            mixer.setMute(name, true);
          } else {
            mixer.setMute(name, name !== soloStem);
          }
        });
        layersList.querySelectorAll(".stem-solo-btn").forEach(b => b.classList.remove("active"));
        layersList.querySelectorAll(".stem-mute-btn").forEach(b => {
          const name = `stem:${b.dataset.stem}`;
          const m = mixer.layers[name]?.muted;
          b.textContent = m ? "Muted" : "Playing";
          b.classList.toggle("muted", m);
        });
        if (!allSoloed) btn.classList.add("active");
      });
    });
    layersList.querySelectorAll(".stem-vol-slider").forEach(sl => {
      sl.addEventListener("input", () => {
        const stemName = `stem:${sl.dataset.stem}`;
        if (mixer) mixer.setVolume(stemName, parseFloat(sl.value));
        const valEl = layersList.querySelector(`.stem-vol-val[data-stem="${sl.dataset.stem}"]`);
        if (valEl) valEl.textContent = `${sl.value} dB`;
      });
    });
    layersList.querySelectorAll(".stem-pan-slider").forEach(sl => {
      sl.addEventListener("input", () => {
        const stemName = `stem:${sl.dataset.stem}`;
        if (mixer) mixer.setPan(stemName, parseFloat(sl.value) / 100);
        const v = parseInt(sl.value);
        const label = v === 0 ? "C" : v < 0 ? `L${Math.abs(v)}` : `R${v}`;
        const valEl = layersList.querySelector(`.stem-pan-val[data-stem="${sl.dataset.stem}"]`);
        if (valEl) valEl.textContent = label;
      });
    });

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
        if (action === "regenerate" || action === "vary") {
          const layer = currentLayers.find(l => l.name === layerName);
          const isMusic = layer && layer.layer_type === "musical";
          const cost = isMusic ? _getCreditCosts().perMusic : _getCreditCosts().perSfx;
          const durLabel = isMusic ? `${(_getCreditCosts().musicSec/60).toFixed(0)} min music` : "5s SFX";
          if (!_canAfford(cost)) {
            alert(`Not enough credits. Need ${_costLabel(cost)} but only ${_costLabel(_lastBalance?.remaining || 0)} remaining.`);
            return;
          }
          if (!confirm(`${action === "vary" ? "Vary" : "Re-roll"} "${layerName}" — generates ${durLabel} (${_costLabel(cost)}). Continue?`)) return;
          _trackCredits(cost, `${action === "vary" ? "Vary" : "Re-roll"} ${layerName}`);
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
        const isMusic = newType === "musical" || (!newType && currentLayers.find(l => l.name === layerName)?.layer_type === "musical");
        const cost = isMusic ? _getCreditCosts().perMusic : _getCreditCosts().perSfx;
        if (!_canAfford(cost)) {
          alert(`Not enough credits. Need ${_costLabel(cost)} but only ${_costLabel(_lastBalance?.remaining || 0)} remaining.`);
          return;
        }
        if (!confirm(`Regenerate "${layerName}" with new prompt (${_costLabel(cost)}). Continue?`)) return;
        _trackCredits(cost, `Regen ${layerName}`);
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
        if (mixer) mixer.setTiming(name, startSec, _getEndSec(name), _getRepeatEvery(name));
        syncTimingToServer(name, startSec, _getEndSec(name), _getRepeatEvery(name));
        updateTimelineFill(name);
      });
    });
    layersList.querySelectorAll(".tl-end").forEach(input => {
      input.addEventListener("change", () => {
        const name = input.dataset.layer;
        const endSec = input.value ? parseFloat(input.value) * 60 : 0;
        if (mixer) mixer.setTiming(name, _getStartSec(name), endSec, _getRepeatEvery(name));
        syncTimingToServer(name, _getStartSec(name), endSec, _getRepeatEvery(name));
        updateTimelineFill(name);
      });
    });
    layersList.querySelectorAll(".tl-repeat").forEach(input => {
      input.addEventListener("change", () => {
        const name = input.dataset.layer;
        const repeatSec = input.value ? parseFloat(input.value) * 60 : 0;
        if (mixer) mixer.setTiming(name, _getStartSec(name), _getEndSec(name), repeatSec);
        syncTimingToServer(name, _getStartSec(name), _getEndSec(name), repeatSec);
        updateTimelineFill(name);
      });
    });

    // ── Alternate pairing ──────────────────────────
    let _altPendingLayer = null;
    layersList.querySelectorAll(".tl-alt-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const name = btn.dataset.layer;

        if (btn.classList.contains("alt-linked")) {
          const altInfo = mixer && mixer.getAlternateInfo(name);
          const partnerName = altInfo ? (altInfo.a === name ? altInfo.b : altInfo.a) : null;
          if (mixer) mixer.clearAlternate(name);
          layersList.querySelectorAll(".tl-alt-btn.alt-linked").forEach(b => {
            b.classList.remove("alt-linked");
            b.textContent = "Alt";
          });
          updateTimelineFill(name);
          if (partnerName) updateTimelineFill(partnerName);
          _syncAlternatePairsToServer();
          return;
        }

        if (_altPendingLayer && _altPendingLayer !== name) {
          const cycleStr = prompt("How many minutes should each layer play before switching?", "2");
          if (!cycleStr) { _clearAltState(); return; }
          const cycleSec = parseFloat(cycleStr) * 60;
          if (isNaN(cycleSec) || cycleSec <= 0) { _clearAltState(); return; }
          _applyAlternate(_altPendingLayer, name, cycleSec);
          _clearAltState();
        } else if (_altPendingLayer === name) {
          _clearAltState();
        } else {
          _altPendingLayer = name;
          btn.classList.add("alt-active");
          btn.textContent = "Pick 2nd...";
        }
      });
    });

    function _clearAltState() {
      _altPendingLayer = null;
      layersList.querySelectorAll(".tl-alt-btn").forEach(b => {
        b.classList.remove("alt-active");
        b.textContent = "Alt";
      });
    }

    function _applyAlternate(nameA, nameB, cycleSec) {
      const xfade = Math.min(8, cycleSec * 0.3);
      if (mixer) mixer.setAlternate(nameA, nameB, cycleSec, xfade);
      _drawAlternateTimeline(nameA, nameB, cycleSec, xfade);

      [nameA, nameB].forEach(name => {
        const startEl = layersList.querySelector(`.tl-start[data-layer="${name}"]`);
        const endEl = layersList.querySelector(`.tl-end[data-layer="${name}"]`);
        const repEl = layersList.querySelector(`.tl-repeat[data-layer="${name}"]`);
        if (startEl) startEl.value = "0";
        if (endEl) endEl.value = "";
        if (repEl) repEl.value = "";
      });

      [nameA, nameB].forEach(name => {
        const btn = layersList.querySelector(`.tl-alt-btn[data-layer="${name}"]`);
        if (btn) { btn.classList.add("alt-linked"); btn.textContent = "Linked"; }
      });

      _syncAlternatePairsToServer();
    }

    function _syncAlternatePairsToServer() {
      if (!currentJobId || !mixer) return;
      const pairs = mixer._alternates.map(a => ({
        layer_a: a.a, layer_b: a.b, cycle_sec: a.cycle, xfade_sec: a.xfade,
      }));
      fetch(`/api/alternate-pairs/${currentJobId}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pairs }),
      }).catch(() => {});
    }

    function _drawAlternateTimeline(nameA, nameB, cycleSec, xfadeSec) {
      const dur = currentTrackDuration || 300;
      const period = cycleSec * 2;

      [nameA, nameB].forEach((name, idx) => {
        const tl = layersList.querySelector(`.layer-timeline[data-layer="${name}"]`);
        if (!tl) return;
        const track = tl.querySelector(".timeline-track");
        if (!track) return;
        track.querySelectorAll(".timeline-fill").forEach(f => f.remove());

        let t = 0;
        while (t < dur) {
          const phase = t;
          let segStart, segEnd;
          if (idx === 0) {
            segStart = t;
            segEnd = Math.min(t + cycleSec, dur);
          } else {
            segStart = t + cycleSec;
            segEnd = Math.min(t + period, dur);
          }
          if (segStart < dur) {
            const fill = document.createElement("div");
            fill.className = "timeline-fill" + (idx === 1 ? " alt-b" : "");
            fill.style.left = (segStart / dur * 100) + "%";
            fill.style.width = (Math.max(0, segEnd - segStart) / dur * 100) + "%";
            track.appendChild(fill);
          }
          t += period;
        }
      });
    }

    // ── Restore timing state after renderLayers ───
    function _restoreTimingState() {
      // 1. Restore sporadic/window timeline fills for all layers
      if (currentLayers) {
        for (const l of currentLayers) {
          const name = escapeHtml(l.name);
          const startSec = l.start_sec || 0;
          const endSec = l.end_sec || 0;
          const repeatSec = l.repeat_every_sec || 0;
          if (repeatSec > 0 || startSec > 0 || endSec > 0) {
            updateTimelineFill(name);
          }
        }
      }

      // 2. Restore alternate pairs from mixer state
      if (mixer && mixer._alternates) {
        for (const alt of mixer._alternates) {
          _drawAlternateTimeline(alt.a, alt.b, alt.cycle, alt.xfade);
          [alt.a, alt.b].forEach(name => {
            const btn = layersList.querySelector(`.tl-alt-btn[data-layer="${name}"]`);
            if (btn) { btn.classList.add("alt-linked"); btn.textContent = "Linked"; }
          });
        }
      }
    }

    function _setLayerTiming(name, startSec, endSec, repeatSec) {
      const startEl = layersList.querySelector(`.tl-start[data-layer="${name}"]`);
      const endEl = layersList.querySelector(`.tl-end[data-layer="${name}"]`);
      const repEl = layersList.querySelector(`.tl-repeat[data-layer="${name}"]`);
      if (startEl) startEl.value = (startSec / 60).toFixed(1);
      if (endEl) endEl.value = (endSec / 60).toFixed(1);
      if (repEl) repEl.value = (repeatSec / 60).toFixed(1);
      if (mixer) mixer.setTiming(name, startSec, endSec, repeatSec);
      syncTimingToServer(name, startSec, endSec, repeatSec);
      updateTimelineFill(name);
    }

    // ── Sporadic presets ───────────────────────────
    layersList.querySelectorAll(".tl-sporadic-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const name = btn.dataset.layer;
        const durStr = prompt("How many seconds should it play each time?", "30");
        if (!durStr) return;
        const playSec = parseFloat(durStr);
        if (isNaN(playSec) || playSec <= 0) return;
        const everyStr = prompt("Come back every how many minutes?", "3");
        if (!everyStr) return;
        const everySec = parseFloat(everyStr) * 60;
        if (isNaN(everySec) || everySec <= 0) return;
        _setLayerTiming(name, 0, playSec, everySec);
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
    function _getRepeatEvery(name) {
      const el = layersList.querySelector(`.tl-repeat[data-layer="${name}"]`);
      return el && el.value ? parseFloat(el.value) * 60 : 0;
    }
    function updateTimelineFill(name) {
      const tl = layersList.querySelector(`.layer-timeline[data-layer="${name}"]`);
      if (!tl) return;
      const track = tl.querySelector(".timeline-track");
      if (!track) return;
      track.querySelectorAll(".timeline-fill").forEach(f => f.remove());
      const startSec = _getStartSec(name);
      const endSec = _getEndSec(name);
      const repeatSec = _getRepeatEvery(name);
      const dur = currentTrackDuration || 300;
      const windowLen = (endSec > 0 ? endSec : dur) - startSec;

      if (repeatSec > 0 && windowLen > 0) {
        const effectiveRepeat = Math.max(repeatSec, windowLen);
        let t = startSec;
        while (t < dur) {
          const s = Math.max(0, t);
          const e = Math.min(dur, t + windowLen);
          const fill = document.createElement("div");
          fill.className = "timeline-fill";
          fill.style.left = (s / dur * 100) + "%";
          fill.style.width = ((e - s) / dur * 100) + "%";
          track.appendChild(fill);
          t += effectiveRepeat;
        }
      } else {
        const fill = document.createElement("div");
        fill.className = "timeline-fill";
        const startPct = (startSec / dur) * 100;
        const endPct = endSec > 0 ? (endSec / dur) * 100 : 100;
        fill.style.left = startPct + "%";
        fill.style.width = (endPct - startPct) + "%";
        track.appendChild(fill);
      }
    }
    function syncTimingToServer(name, startSec, endSec, repeatEvery) {
      if (!currentJobId) return;
      const params = { start_sec: startSec, end_sec: endSec };
      if (repeatEvery !== undefined) params.repeat_every_sec = repeatEvery;
      fetch(`/api/layer-action/${currentJobId}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "update_params", layer_name: name, params }),
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

    _restoreTimingState();

    // Expose for use after initMixer
    window._restoreTimingStateGlobal = _restoreTimingState;
  }

  const soundPalette = {
    "Instruments": [
      { name: "Piano Ambient", type: "musical", prompt: "Continuous slow ambient piano pad, dense sustained chords, reverberant, spacious, gentle felt-dampened sustain throughout, no silent gaps" },
      { name: "Rhodes Pad", type: "musical", prompt: "Warm Rhodes electric piano chords, soft tremolo, pillowy sustain, vintage warmth" },
      { name: "Celesta/Music Box", type: "musical", prompt: "Delicate celesta or music box melody, tinkling and ethereal, sparse notes" },
      { name: "Harp Arpeggios", type: "musical", prompt: "Gentle harp arpeggios, slow and spacious, reverberant, classical warmth" },
      { name: "Acoustic Guitar", type: "musical", prompt: "Gentle fingerpicked acoustic guitar, slow arpeggios, warm tone, intimate" },
      { name: "Cello Drone", type: "musical", prompt: "Deep cello sustained bowing, rich overtones, slow harmonic shifts" },
      { name: "Violin Harmonics", type: "musical", prompt: "High violin natural harmonics, crystalline and fragile, sparse bowed notes" },
      { name: "Synth Pad", type: "musical", prompt: "Warm analog synthesizer pad, slowly evolving filter sweep, rich detuned oscillators" },
      { name: "Granular Texture", type: "musical", prompt: "Granular time-stretched texture, frozen spectral fragments, slowly morphing" },
      { name: "Tape Loops", type: "musical", prompt: "Generative tape loop, imperfect repetition, warped pitch, analog degradation" },
      { name: "Flute Breath", type: "musical", prompt: "Airy flute long tones, breathy and meditative, gentle vibrato, spacious" },
      { name: "Shakuhachi", type: "musical", prompt: "Japanese shakuhachi flute, meditative single notes, breath sounds, Zen aesthetic" },
      { name: "Singing Bowl", type: "detail", prompt: "Tibetan singing bowl strike and sustain, rich overtones, slowly decaying resonance" },
      { name: "Kalimba", type: "detail", prompt: "Gentle kalimba melody, sparse plucked notes, warm metallic tone, African thumb piano" },
      { name: "Hang Drum", type: "musical", prompt: "Hang drum soft melodic pattern, steel resonance, meditative, gentle percussion" },
      { name: "Vibraphone", type: "detail", prompt: "Vibraphone with motor vibrato, sparse jazz chords, metallic shimmer, cool tone" },
      { name: "Tongue Drum", type: "detail", prompt: "Steel tongue drum, soft melodic tones, meditative, warm resonance" },
      { name: "Choir Pad", type: "musical", prompt: "Ethereal vocal choir pad, sustained vowel sounds, reverberant, celestial harmonies" },
    ],
    "Environments": [
      { name: "Gentle Rain", type: "base", prompt: "Soft steady rain falling on leaves and wet ground, natural outdoor recording" },
      { name: "Thunderstorm", type: "base", prompt: "Distant thunderstorm with rolling thunder, heavy rain, atmospheric storm ambience" },
      { name: "Forest", type: "base", prompt: "Deep forest ambience, distant songbirds, rustling leaves, dappled sunlight atmosphere" },
      { name: "Ocean Waves", type: "base", prompt: "Slow ocean waves breaking gently on shore, rhythmic and calming, distant surf" },
      { name: "River/Creek", type: "mid", prompt: "Small creek babbling over smooth stones, gentle water flow, natural stream" },
      { name: "Night Crickets", type: "base", prompt: "Crickets chirping on a warm summer night, continuous gentle rhythm, field recording" },
      { name: "Wind", type: "mid", prompt: "Gentle wind across an open landscape, soft whooshing, natural air movement" },
      { name: "Snow/Winter", type: "base", prompt: "Quiet winter atmosphere, muffled snow ambience, cold stillness, distant wind" },
      { name: "Cave", type: "base", prompt: "Underground cave ambience, dripping water echoes, deep reverberant darkness" },
      { name: "Fireplace", type: "mid", prompt: "Wood fire crackling softly, occasional pop, warm campfire or fireplace" },
      { name: "City at Night", type: "base", prompt: "Distant late-night city ambience, muffled traffic, occasional sirens, urban quiet" },
      { name: "Cafe Murmur", type: "mid", prompt: "Soft indistinct cafe background conversation, clinking cups, espresso machine hiss" },
      { name: "Space/Void", type: "base", prompt: "Deep space ambient void, sub-bass drone, cosmic radiation crackle, vast emptiness" },
      { name: "Mountain Air", type: "base", prompt: "High altitude mountain atmosphere, thin wind, distant eagle cry, vast openness" },
      { name: "Underwater", type: "base", prompt: "Underwater ambient sounds, muffled bubbles, deep oceanic pressure, whale song distance" },
    ],
    "Treatments": [
      { name: "Tape Saturation", type: "detail", prompt: "Warm tape-saturated texture, analog harmonic distortion, gentle compression artifacts" },
      { name: "Vinyl Crackle", type: "detail", prompt: "Warm vinyl record surface noise, gentle crackle and pop, analog warmth" },
      { name: "Lo-fi Hiss", type: "detail", prompt: "Lo-fi tape hiss and noise floor, nostalgic cassette recording quality" },
      { name: "Shimmer Reverb", type: "detail", prompt: "Shimmer reverb tail, pitch-shifted octave reflections, crystalline and infinite" },
      { name: "Reversed Pad", type: "mid", prompt: "Reversed ambient pad swell, building backwards, ghostly and ethereal" },
      { name: "Granular Freeze", type: "mid", prompt: "Granular freeze effect on sustained tone, spectral smearing, frozen in time" },
      { name: "Slowed Down", type: "base", prompt: "Extremely slowed-down recording, pitch-shifted low, stretched time, deep and vast" },
      { name: "Deep Drone", type: "base", prompt: "Deep sub-bass drone, slowly evolving texture, cinematic low-end rumble" },
    ],
    "Atmospheric": [
      { name: "Ethereal Shimmer", type: "detail", prompt: "High-frequency shimmering texture, crystalline sparkle, airy and bright" },
      { name: "Room Tone", type: "base", prompt: "Empty room tone, subtle air, interior ambience, close-mic'd silence" },
      { name: "Wind Chimes", type: "detail", prompt: "Distant wind chimes in a gentle breeze, metallic tinkling, sparse and random" },
      { name: "Bell Resonance", type: "detail", prompt: "Large bell strike with long decay, deep bronze resonance, ceremonial tone" },
      { name: "Radio Static", type: "detail", prompt: "Shortwave radio static and interference, distant signals, analog noise" },
      { name: "Train Distant", type: "mid", prompt: "Distant train horn and wheels on tracks, far-off rumble, nostalgic travel" },
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
          const isMusic = btn.dataset.stype === "musical";
          const cost = isMusic ? _getCreditCosts().perMusic : _getCreditCosts().perSfx;
          if (!_canAfford(cost)) {
            alert(`Not enough credits. Need ${_costLabel(cost)} but only ${_costLabel(_lastBalance?.remaining || 0)} remaining.`);
            return;
          }
          if (!confirm(`Add "${btn.dataset.sname}" (${isMusic ? "music" : "SFX"}) — ${_costLabel(cost)}. Continue?`)) return;
          _trackCredits(cost, `Add ${btn.dataset.sname}`);
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
              const newLayer = (data.layers || []).find(l => l.name === btn.dataset.sname);
              if (mixer && newLayer && newLayer.has_audio) {
                const url = `/api/audio/${currentJobId}/layer/${encodeURIComponent(btn.dataset.sname)}?t=${Date.now()}`;
                mixer.addLayer(btn.dataset.sname, url, { volume_db: newLayer.volume_db || -6 }).catch(err => {
                  console.error(`Failed to load new layer "${btn.dataset.sname}":`, err);
                  addChatMessage("system", `Warning: layer added but audio failed to load. Try regenerating.`);
                  markLayerLoadFailures([btn.dataset.sname]);
                });
              } else if (newLayer && !newLayer.has_audio) {
                addChatMessage("system", `Warning: layer "${btn.dataset.sname}" was added but audio generation failed. Try regenerating.`);
                markLayerLoadFailures([btn.dataset.sname]);
              } else if (!mixer) {
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
        const regenLayer = (data.layers || []).find(l => l.name === layerName);
        if (mixer && regenLayer && regenLayer.has_audio) {
          const url = `/api/audio/${currentJobId}/layer/${encodeURIComponent(layerName)}?t=${Date.now()}`;
          if (mixer.hasLayer(layerName)) {
            mixer.reloadLayer(layerName, url).catch(err => {
              console.error(`Failed to reload layer "${layerName}":`, err);
              addChatMessage("system", `Warning: regenerated but audio failed to load.`);
            });
          } else {
            mixer.addLayer(layerName, url, { volume_db: regenLayer.volume_db || -6 }).catch(err => {
              console.error(`Failed to add regenerated layer "${layerName}":`, err);
              addChatMessage("system", `Warning: regenerated but audio failed to load.`);
            });
          }
        } else if (regenLayer && !regenLayer.has_audio) {
          addChatMessage("system", `Warning: regeneration failed for "${layerName}".`);
          markLayerLoadFailures([layerName]);
        } else if (!mixer) {
          audioPlayer.src = data.audio_url; audioPlayer.load(); audioPlayer.play().catch(() => {});
        }
      }
    } catch (err) { addChatMessage("system", `Error: ${err.message}`); }
    layerActionPending = false;
    layersList.querySelectorAll(".layer-btn").forEach((b) => (b.disabled = false));
  }

  async function performLayerAction(action, layerName) {
    if (!currentJobId || layerActionPending) return;

    // Vary: create a new layer with the same prompt for alternation
    if (action === "vary") {
      const srcLayer = currentLayers.find(l => l.name === layerName);
      if (!srcLayer || !srcLayer.elevenlabs_prompt) {
        addChatMessage("system", "Cannot vary — layer has no prompt.");
        return;
      }
      const existingNames = currentLayers.map(l => l.name);
      let varName = layerName + " v2";
      let n = 2;
      while (existingNames.includes(varName)) { n++; varName = layerName + " v" + n; }
      layerActionPending = true;
      layersList.querySelectorAll(".layer-btn").forEach(b => (b.disabled = true));
      const card = layersList.querySelector(`.layer-btn[data-layer="${CSS.escape(layerName)}"]`)?.closest(".layer-card");
      if (card) card.classList.add("layer-loading");
      addChatMessage("system", `Creating variation "${varName}" from "${layerName}"...`);
      try {
        const res = await fetch(`/api/layer-action/${currentJobId}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "add", name: varName, layer_type: srcLayer.layer_type, prompt: srcLayer.elevenlabs_prompt }),
        });
        const data = await res.json();
        if (data.error) { addChatMessage("system", `Error: ${data.error}`); }
        else {
          addChatMessage("system", `Variation "${varName}" created — use Alt to alternate them!`);
          if (data.layers) renderLayers(data.layers);
          const newLayer = (data.layers || []).find(l => l.name === varName);
          if (mixer && newLayer && newLayer.has_audio) {
            const url = `/api/audio/${currentJobId}/layer/${encodeURIComponent(varName)}?t=${Date.now()}`;
            mixer.addLayer(varName, url, { volume_db: newLayer.volume_db || -6 }).catch(err => {
              console.error(`Failed to load variation "${varName}":`, err);
              addChatMessage("system", `Warning: variation added but audio failed to load.`);
            });
          }
        }
      } catch (err) { addChatMessage("system", `Error: ${err.message}`); }
      layerActionPending = false;
      layersList.querySelectorAll(".layer-btn").forEach(b => (b.disabled = false));
      fetchCreditBalance();
      return;
    }

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
    fetchCreditBalance();
  }

  async function performAddLayer() {
    if (!currentJobId || layerActionPending) return;
    const name = document.getElementById("add-layer-name").value.trim();
    const layerType = document.getElementById("add-layer-type").value;
    const prompt = document.getElementById("add-layer-prompt").value.trim();
    if (!name || !prompt) { alert("Name and prompt are required"); return; }
    const isMusic = layerType === "musical";
    const cost = isMusic ? _getCreditCosts().perMusic : _getCreditCosts().perSfx;
    if (!_canAfford(cost)) {
      alert(`Not enough credits. Need ${_costLabel(cost)} but only ${_costLabel(_lastBalance?.remaining || 0)} remaining.`);
      return;
    }
    if (!confirm(`Add "${name}" (${isMusic ? "music" : "SFX"}) — ${_costLabel(cost)}. Continue?`)) return;
    _trackCredits(cost, `Add ${name}`);
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
        const newLayer = (data.layers || []).find(l => l.name === name);
        if (mixer && newLayer && newLayer.has_audio) {
          const url = `/api/audio/${currentJobId}/layer/${encodeURIComponent(name)}?t=${Date.now()}`;
          mixer.addLayer(name, url, { volume_db: newLayer.volume_db || -6 }).catch(err => {
            console.error(`Failed to load new layer "${name}":`, err);
            addChatMessage("system", `Warning: layer added but audio failed to load. Try regenerating.`);
            markLayerLoadFailures([name]);
          });
        } else if (newLayer && !newLayer.has_audio) {
          addChatMessage("system", `Warning: audio generation failed for "${name}". Try regenerating.`);
          markLayerLoadFailures([name]);
        } else if (!mixer) {
          audioPlayer.src = data.audio_url; audioPlayer.load(); audioPlayer.play().catch(() => {});
        }
        document.getElementById("add-layer-name").value = "";
        document.getElementById("add-layer-prompt").value = "";
      }
    } catch (err) { addChatMessage("system", `Error: ${err.message}`); }
    layerActionPending = false; submitBtn.disabled = false; submitBtn.textContent = "Add";
    fetchCreditBalance();
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

  // ── Re-prep loop (re-run loop algorithm on this song only) ──
  async function reprepLoopForJob(data) {
    if (!btnReprepLoop || !data || !data.job_id) return;
    const jobId = data.job_id;
    const original = btnReprepLoop.textContent;
    btnReprepLoop.disabled = true;
    btnReprepLoop.textContent = "Re-prepping...";
    try {
      // Pause any current playback while we swap audio.
      const wasPlaying = mixer && mixer.playing;
      if (mixer && mixer.playing) mixer.pause();
      // Clear the cached loop files on the server.
      const res = await fetch(`/api/audio/${jobId}/reprep`, { method: "POST" });
      const out = await res.json();
      if (out.error) throw new Error(out.error);
      console.log(`[Reprep] Cleared ${out.deleted} cached loop file(s) for job ${jobId}`);
      // Re-init the mixer so it re-fetches each layer; the server will
      // re-run prepare_musical_loop with the current algorithm.
      const durationSec = (data.duration || 5) * 60;
      currentTrackDuration = durationSec;
      await initMixer(jobId, data.layers || [], durationSec);
      const altPairs = data.alternate_pairs || [];
      for (const p of altPairs) {
        if (mixer) mixer.setAlternate(p.layer_a, p.layer_b, p.cycle_sec, p.xfade_sec);
      }
      if (wasPlaying && mixer) mixer.play();
    } catch (err) {
      alert("Re-prep failed: " + err.message);
    } finally {
      btnReprepLoop.disabled = false;
      btnReprepLoop.textContent = original;
    }
  }

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
  const extendedProgress = document.getElementById("extended-progress");
  const extendedProgressText = document.getElementById("extended-progress-text");
  const extendedStopBtn = document.getElementById("extended-stop-btn");
  wireStopButton(extendedStopBtn);

  btnExportExtended.addEventListener("click", async () => {
    if (!currentJobId) return;
    const minutes = parseInt(extendedDurationEl.value);
    btnExportExtended.disabled = true;
    btnExportExtended.textContent = `Exporting ${minutes} min...`;

    await runLongTask(currentJobId, {
      initialMessage: `Exporting ${minutes} minute looped audio...`,
      progressEl: extendedProgress,
      progressTextEl: extendedProgressText,
      stopBtn: extendedStopBtn,
      startRequest: () => fetch(`/api/export-extended/${currentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_minutes: minutes }),
      }),
      onDone: (data) => {
        window.location.href = data.download_url;
      },
      onError: (msg) => { if (msg) alert("Export failed: " + msg); },
    });

    btnExportExtended.disabled = false;
    btnExportExtended.textContent = "Export Looped";
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
  let _historyCache = [];

  async function refreshHistory() {
    try {
      const res = await fetch("/api/history");
      _historyCache = await res.json();
      _renderHistoryDropdown();
    } catch (err) { console.error("History fetch error:", err); }
  }

  function _renderHistoryDropdown() {
    let items = _historyCache;
    if (showFavoritesOnly) items = items.filter((j) => j.favorite);

    // Reveal the global player bar as soon as any track exists.
    const gp = document.getElementById("global-player");
    if (gp && _historyCache.length) gp.classList.remove("hidden");

    historySelect.innerHTML = "";
    if (!items.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.disabled = true;
      opt.selected = true;
      opt.textContent = showFavoritesOnly ? "No favorites yet" : "No saved sessions";
      historySelect.appendChild(opt);
      _updateFavBtn(null);
      return;
    }

    items.forEach((j) => {
      const opt = document.createElement("option");
      opt.value = j.job_id;

      let timeStr = "";
      if (j.created_at) {
        const d = new Date(j.created_at);
        const diff = Date.now() - d;
        if (diff < 60000) timeStr = "just now";
        else if (diff < 3600000) timeStr = Math.floor(diff / 60000) + "m ago";
        else if (diff < 86400000) timeStr = Math.floor(diff / 3600000) + "h ago";
        else timeStr = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
      }
      const star = j.favorite ? "\u2605 " : "";
      const dot = j.status === "complete" ? "\u2713" : j.status === "running" ? "\u25CB" : "\u2717";
      // Prefer the short evocative title; fall back to the prompt if absent.
      const label = (j.title && j.title.trim()) ? j.title.trim() : j.prompt;
      const shown = label.length > 60 ? label.slice(0, 57) + "..." : label;
      opt.textContent = `${star}${dot} ${shown}  (${timeStr})`;
      // Full description on hover so identical titles are still distinguishable.
      opt.title = j.prompt || "";

      if (j.job_id === currentJobId) opt.selected = true;
      historySelect.appendChild(opt);
    });

    _updateFavBtn(currentJobId);
  }

  function _updateFavBtn(jobId) {
    const job = _historyCache.find((j) => j.job_id === jobId);
    if (job) {
      favToggleBtn.textContent = job.favorite ? "\u2605" : "\u2606";
      favToggleBtn.title = job.favorite ? "Unfavorite" : "Favorite";
      favToggleBtn.dataset.jobId = job.job_id;
      favToggleBtn.style.display = "";
    } else {
      favToggleBtn.style.display = "none";
    }
  }

  historySelect.addEventListener("change", () => {
    const jobId = historySelect.value;
    if (jobId) viewJob(jobId);
  });

  favToggleBtn.addEventListener("click", async () => {
    const jobId = favToggleBtn.dataset.jobId;
    if (!jobId) return;
    try {
      const r = await fetch(`/api/favorite/${jobId}`, { method: "POST" });
      const data = await r.json();
      const cached = _historyCache.find((j) => j.job_id === jobId);
      if (cached) cached.favorite = data.favorite;
      _updateFavBtn(jobId);
      if (showFavoritesOnly) _renderHistoryDropdown();
    } catch (err) { console.error("Favorite toggle error:", err); }
  });

  if (filterFavBtn) {
    filterFavBtn.addEventListener("click", () => {
      showFavoritesOnly = !showFavoritesOnly;
      filterFavBtn.textContent = showFavoritesOnly ? "Favorites" : "All";
      filterFavBtn.classList.toggle("active", showFavoritesOnly);
      _renderHistoryDropdown();
    });
  }

  async function viewJob(jobId, autoplay = true) {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();
      if (data.prompt) { promptEl.value = data.prompt; window._autogrowPrompt && window._autogrowPrompt(); }
      // Restore the ElevenLabs method + composition timeline this track was made with.
      const _hasPlan = !!(data.composition_plan && data.composition_plan.sections && data.composition_plan.sections.length);
      // A stored plan implies Musical + Composition plan (older jobs didn't persist the mode).
      const _restoredMode = data.mode || (_hasPlan ? "musical" : null);
      if (_restoredMode) {
        currentMode = _restoredMode;
        modeButtons.forEach(b => b.classList.toggle("active", b.dataset.mode === _restoredMode));
        _updateApproachVisibility();   // reveal the Music engine group in Musical mode
      }
      if (data.reference_url) referenceUrlEl.value = data.reference_url;
      if (musicGenerationModeEl) {
        musicGenerationModeEl.value = data.music_generation_mode || (_hasPlan ? "composition_plan" : musicGenerationModeEl.value);
      }
      if (typeof _toggleCompSections === "function") _toggleCompSections();
      if (_hasPlan) {
        _renderCompSections(data.composition_plan);
      } else {
        window._compositionPlan = null;
        if (typeof _renderCompSections === "function") _renderCompSections(null);
      }
      saveFormState();
      if (data.status === "complete") {
        currentJobId = jobId;
        visCurrentJobId = jobId;
        pubCurrentJobId = jobId;
        showPlayer(data, autoplay); enableFeedback();
        feedbackMessages.innerHTML = '<div class="feedback-hint">Listen, then describe what to change.</div>';
        if (data.feedback_history) data.feedback_history.forEach((entry) => { addChatMessage("user", entry.feedback); addChatMessage("system", `Updated! ${entry.changes}`); });
        // Keep every tab's view in sync with the one global selection.
        if (typeof loadVisualsForTrack === "function") loadVisualsForTrack(jobId, data);
        if (typeof loadPublishForTrack === "function") loadPublishForTrack(jobId, data);
      } else if (data.status === "running") {
        progressPanel.classList.remove("hidden"); playerPanel.classList.add("hidden"); feedbackPanel.classList.add("hidden");
        currentJobId = jobId; startPolling(jobId);
      } else if (data.status === "error") {
        progressPanel.classList.remove("hidden"); playerPanel.classList.add("hidden"); layersPanel.classList.add("hidden"); feedbackPanel.classList.add("hidden");
        showError(`Session failed: ${data.error || "Unknown error"}`);
        currentJobId = jobId;
      }
      historySelect.value = jobId;
      _updateFavBtn(jobId);
      try { localStorage.setItem("ambientizer_last_track", jobId); } catch (e) {}
    } catch (err) { console.error("View job error:", err); }
  }


  // ═══════════════════════════════════════════════════════
  //  TAB: Visuals
  // ═══════════════════════════════════════════════════════

  const visTrackSelect = document.getElementById("vis-track-select");
  const visTrackInfo = document.getElementById("vis-track-info");
  const visTrackPrompt = document.getElementById("vis-track-prompt");
  let visMixer = null;

  // ── Visuals tab mixer (identical to Create tab's LiveMixer) ──
  const visTransport = document.getElementById("vis-transport");
  const visBtnPlayPause = document.getElementById("vis-btn-play-pause");
  const visIconPlay = document.getElementById("vis-icon-play");
  const visIconPause = document.getElementById("vis-icon-pause");
  const visTransportCurrent = document.getElementById("vis-transport-current");
  const visTransportSeek = document.getElementById("vis-transport-seek");
  const visTransportTotal = document.getElementById("vis-transport-total");
  const visTransportVolume = document.getElementById("vis-transport-volume");
  const visLoadingMsg = document.getElementById("vis-loading-msg");

  async function initVisMixer(jobId, layers, durationSec) {
    if (visMixer) { visMixer.destroy(); visMixer = null; }
    visMixer = new LiveMixer();
    window._ambientizerVisMixer = visMixer;
    await visMixer.init(durationSec);
    visMixer.setMasterVolume(getSavedMasterVolume());

    visMixer.onTimeUpdate = (t, dur) => {
      visTransportCurrent.textContent = formatTime(t);
      visTransportSeek.value = Math.round((t / dur) * 1000);
      visIconPlay.classList.toggle("hidden", visMixer.playing);
      visIconPause.classList.toggle("hidden", !visMixer.playing);
    };
    visTransportTotal.textContent = formatTime(durationSec);

    const layersWithAudio = layers.filter(l => l.has_audio);
    const loadPromises = layersWithAudio.map(l => {
      const url = `/api/audio/${jobId}/layer/${encodeURIComponent(l.name)}`;
      return visMixer.addLayer(l.name, url, {
        volume_db: l.volume_db,
        pan: l.pan || 0,
        muted: l.volume_db <= -55,
        low_pass_hz: l.effects?.low_pass_hz || 20000,
        reverb_amount: l.effects?.reverb_amount || 0,
        swell_amount: l.swell_amount || 0,
        swell_period_sec: l.swell_period_sec || 20,
        start_sec: l.start_sec || 0,
        end_sec: l.end_sec || 0,
        repeat_every_sec: l.repeat_every_sec || 0,
      }).catch(err => {
        console.warn(`[VisMixer] Failed to load layer "${l.name}":`, err);
      });
    });
    await Promise.all(loadPromises);
    console.log(`[VisMixer] Loaded ${Object.keys(visMixer.layers).length}/${layersWithAudio.length} layers`);

    visMixer.setMasterFades(5, 5);
    visMixer.play();
    visIconPlay.classList.add("hidden");
    visIconPause.classList.remove("hidden");
  }

  if (visBtnPlayPause) {
    visBtnPlayPause.addEventListener("click", () => {
      if (!visMixer) return;
      if (visMixer.playing) visMixer.pause(); else visMixer.play();
    });
  }
  if (visTransportSeek) {
    visTransportSeek.addEventListener("input", () => {
      if (!visMixer) return;
      visMixer.seek((parseFloat(visTransportSeek.value) / 1000) * visMixer.duration);
    });
  }
  if (visTransportVolume) {
    visTransportVolume.value = String(getSavedMasterVolume());
    visTransportVolume.addEventListener("input", () => {
      setSavedMasterVolume(parseFloat(visTransportVolume.value));
    });
  }

  // ── Cancellable long-running tasks ─────────────
  let longTaskPollTimer = null;
  let longTaskJobId = null;

  async function cancelLongTask(jobId) {
    if (!jobId) return;
    try {
      await fetch(`/api/cancel-task/${jobId}`, { method: "POST" });
    } catch (err) {
      console.warn("Cancel request failed:", err);
    }
  }

  function stopLongTaskPolling() {
    if (longTaskPollTimer) {
      clearInterval(longTaskPollTimer);
      longTaskPollTimer = null;
    }
    longTaskJobId = null;
  }

  function setTaskStopVisible(stopBtn, visible) {
    if (!stopBtn) return;
    stopBtn.classList.toggle("hidden", !visible);
    stopBtn.disabled = false;
    stopBtn.textContent = "Stop";
  }

  // Drive a .task-bar fill from any progress message containing "N/M"
  // (e.g. "frame 153/384"). Switches off the indeterminate sweep once real.
  function _updateTaskBar(progressEl, message) {
    if (!progressEl || !message) return;
    const fill = progressEl.querySelector(".task-bar-fill");
    const bar = progressEl.querySelector(".task-bar");
    if (!fill || !bar) return;
    const m = message.match(/(\d+)\s*\/\s*(\d+)/);
    if (!m) return;
    const pct = Math.max(2, Math.min(100, Math.round((+m[1] / +m[2]) * 100)));
    bar.classList.remove("indeterminate");
    fill.style.width = pct + "%";
  }

  async function runLongTask(jobId, options) {
    const {
      startRequest,
      progressEl,
      progressTextEl,
      stopBtn,
      onDone,
      onError,
      initialMessage = "Working...",
    } = options;

    stopLongTaskPolling();
    longTaskJobId = jobId;
    if (progressTextEl) progressTextEl.textContent = initialMessage;
    progressEl?.classList.remove("hidden");
    // Reset the progress bar to an indeterminate sweep until the first "N/M" tick.
    const _bar = progressEl?.querySelector(".task-bar");
    const _fill = progressEl?.querySelector(".task-bar-fill");
    if (_bar) _bar.classList.add("indeterminate");
    if (_fill) _fill.style.width = "0%";
    setTaskStopVisible(stopBtn, true);

    try {
      const res = await startRequest();
      const data = await res.json();
      if (data.error) {
        stopLongTaskPolling();
        setTaskStopVisible(stopBtn, false);
        progressEl?.classList.add("hidden");
        onError?.(data.error);
        return;
      }
      if (data.status === "ready" || data.status === "done") {
        stopLongTaskPolling();
        setTaskStopVisible(stopBtn, false);
        progressEl?.classList.add("hidden");
        onDone?.(data);
        return;
      }

      if (data.message && progressTextEl) progressTextEl.textContent = data.message;
      _updateTaskBar(progressEl, data.message);

      longTaskPollTimer = setInterval(async () => {
        try {
          const sr = await fetch(`/api/task-status/${jobId}`);
          const sd = await sr.json();
          if (sd.message && progressTextEl) progressTextEl.textContent = sd.message;
          _updateTaskBar(progressEl, sd.message);

          if (sd.status === "done") {
            stopLongTaskPolling();
            setTaskStopVisible(stopBtn, false);
            progressEl?.classList.add("hidden");
            onDone?.(sd);
          } else if (sd.status === "error") {
            stopLongTaskPolling();
            setTaskStopVisible(stopBtn, false);
            progressEl?.classList.add("hidden");
            onError?.(sd.message || "Task failed");
          } else if (sd.status === "canceled") {
            stopLongTaskPolling();
            setTaskStopVisible(stopBtn, false);
            progressEl?.classList.add("hidden");
            onError?.(null);
          }
        } catch (err) {
          console.warn("Task poll failed:", err);
        }
      }, 1500);
    } catch (err) {
      stopLongTaskPolling();
      setTaskStopVisible(stopBtn, false);
      progressEl?.classList.add("hidden");
      onError?.(err.message);
    }
  }

  function wireStopButton(btn) {
    if (!btn) return;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Stopping...";
      await cancelLongTask(longTaskJobId);
    });
  }

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
  const extendPromptEl = document.getElementById("extend-prompt");
  const btnExtendClip = document.getElementById("btn-extend-clip");
  const clipSpeedEl = document.getElementById("clip-speed");
  const btnApplySpeed = document.getElementById("btn-apply-speed");
  const btnBoomerang = document.getElementById("btn-boomerang");
  const btnExportVideo = document.getElementById("btn-export-video");
  const exportProgress = document.getElementById("export-progress");
  const exportProgressText = document.getElementById("export-progress-text");
  const exportStopBtn = document.getElementById("export-stop-btn");
  const imageProgress = document.getElementById("image-progress");
  const imageProgressText = document.getElementById("image-progress-text");
  const imageStopBtn = document.getElementById("image-stop-btn");
  const clipStopBtn = document.getElementById("clip-stop-btn");
  const videoDownload = document.getElementById("video-download");
  const videoDownloadLink = document.getElementById("video-download-link");
  const vmodeButtons = document.querySelectorAll("[data-vmode]");

  wireStopButton(clipStopBtn);
  wireStopButton(exportStopBtn);
  wireStopButton(imageStopBtn);

  let visCurrentJobId = null;
  let currentVideoMode = "ai";

  const uploadVideoGroup = document.getElementById("upload-video-group");
  const uploadVideoInput = document.getElementById("upload-video-input");
  const uploadBrowseBtn = document.getElementById("upload-browse-btn");
  const uploadDropArea = document.getElementById("upload-drop-area");
  const uploadFileName = document.getElementById("upload-file-name");
  const btnUploadVideo = document.getElementById("btn-upload-video");

  function showClipPreview(clipUrl) {
    clipVideo.src = clipUrl;
    clipVideo.load();
    clipPreview.classList.remove("hidden");
    visExportPanel.classList.remove("hidden");
    videoDownload.classList.add("hidden");
    const exportPreview = document.getElementById("export-preview");
    if (exportPreview) exportPreview.classList.add("hidden");
  }

  vmodeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      vmodeButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentVideoMode = btn.dataset.vmode;
      const isUpload = currentVideoMode === "upload";
      // Motion Prompt steers BOTH AI Animation and Living Still (the latter feeds
      // it to the motion director: "deep space, slow drift, faint red glow, no clouds").
      motionPromptGroup.classList.toggle("hidden", !(currentVideoMode === "ai" || currentVideoMode === "motion"));
      const motionSettings = document.getElementById("motion-settings-group");
      if (motionSettings) motionSettings.classList.toggle("hidden", currentVideoMode !== "motion");
      if (uploadVideoGroup) uploadVideoGroup.classList.toggle("hidden", !isUpload);
      btnCreateClip.classList.toggle("hidden", isUpload);
    });
  });

  // ── Upload Video handlers ──
  if (uploadBrowseBtn && uploadVideoInput) {
    uploadBrowseBtn.addEventListener("click", () => uploadVideoInput.click());

    uploadVideoInput.addEventListener("change", () => {
      const file = uploadVideoInput.files[0];
      if (file) {
        uploadFileName.textContent = `${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)`;
        uploadFileName.classList.remove("hidden");
        btnUploadVideo.disabled = false;
      } else {
        uploadFileName.classList.add("hidden");
        btnUploadVideo.disabled = true;
      }
    });

    if (uploadDropArea) {
      uploadDropArea.addEventListener("dragover", (e) => { e.preventDefault(); uploadDropArea.classList.add("dragover"); });
      uploadDropArea.addEventListener("dragleave", () => uploadDropArea.classList.remove("dragover"));
      uploadDropArea.addEventListener("drop", (e) => {
        e.preventDefault();
        uploadDropArea.classList.remove("dragover");
        if (e.dataTransfer.files.length) {
          uploadVideoInput.files = e.dataTransfer.files;
          uploadVideoInput.dispatchEvent(new Event("change"));
        }
      });
    }

    btnUploadVideo.addEventListener("click", async () => {
      const file = uploadVideoInput.files[0];
      if (!file || !visCurrentJobId) return;

      btnUploadVideo.disabled = true;
      btnUploadVideo.textContent = "Uploading...";
      clipProgress.classList.remove("hidden");
      clipProgressText.textContent = "Uploading video...";
      clipPreview.classList.add("hidden");

      try {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(`/api/visual/upload-video/${visCurrentJobId}`, {
          method: "POST",
          body: form,
        });
        const data = await res.json();
        if (data.error) {
          alert("Upload failed: " + data.error);
        } else {
          showClipPreview(data.clip_url);
        }
      } catch (err) {
        alert("Upload failed: " + err.message);
      }

      btnUploadVideo.disabled = false;
      btnUploadVideo.textContent = "Upload & Preview";
      clipProgress.classList.add("hidden");
    });
  }

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

  // Render the Visuals tab for the globally-selected track (audio plays via the global bar).
  async function loadVisualsForTrack(jobId, data) {
    if (!jobId) return;
    visCurrentJobId = jobId;
    try {
      if (!data) { const res = await fetch(`/api/status/${jobId}`); data = await res.json(); }

      if (visTrackPrompt) visTrackPrompt.textContent = `"${data.prompt}"`;
      if (visTrackInfo) visTrackInfo.classList.remove("hidden");
      if (visImagePanel) visImagePanel.classList.remove("hidden");

      if (imagePromptEl && !imagePromptEl.value) imagePromptEl.value = data.visual_image_prompt || "";

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
      console.error("Failed to load visuals for track:", err);
    }
  }
  window.loadVisualsForTrack = loadVisualsForTrack;

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

    await runLongTask(visCurrentJobId, {
      initialMessage: "Generating scene image...",
      progressEl: imageProgress,
      progressTextEl: imageProgressText,
      stopBtn: imageStopBtn,
      startRequest: () => fetch(`/api/visual/image/${visCurrentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      }),
      onDone: (data) => {
        previewImg.src = data.image_url;
        imagePreview.classList.remove("hidden");
        visAnimatePanel.classList.remove("hidden");
        clipPreview.classList.add("hidden");
        visExportPanel.classList.add("hidden");
        videoDownload.classList.add("hidden");
      },
      onError: (msg) => {
        if (msg) alert("Image generation failed: " + msg);
      },
    });

    btnGenImage.disabled = false; btnGenImage.textContent = "Generate Image ($0.02)";
    btnRegenImage.disabled = false;
  }

  // ── Upload your own image / screenshot (instead of generating) ──
  const btnUploadImage = document.getElementById("btn-upload-image");
  const uploadImageInput = document.getElementById("upload-image-input");
  if (btnUploadImage && uploadImageInput) {
    btnUploadImage.addEventListener("click", () => {
      if (!visCurrentJobId) { alert("Select a track first"); return; }
      uploadImageInput.click();
    });
    uploadImageInput.addEventListener("change", async () => {
      const file = uploadImageInput.files && uploadImageInput.files[0];
      if (!file || !visCurrentJobId) return;
      btnUploadImage.disabled = true; btnUploadImage.textContent = "Uploading...";
      try {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch(`/api/visual/upload-image/${visCurrentJobId}`, { method: "POST", body: fd });
        const data = await res.json();
        if (data.error) { alert("Upload failed: " + data.error); }
        else {
          previewImg.src = data.image_url;
          imagePreview.classList.remove("hidden");
          visAnimatePanel.classList.remove("hidden");
          clipPreview.classList.add("hidden");
          visExportPanel.classList.add("hidden");
          videoDownload.classList.add("hidden");
        }
      } catch (e) { alert("Upload failed: " + e.message); }
      btnUploadImage.disabled = false; btnUploadImage.textContent = "⬆ Upload Image";
      uploadImageInput.value = "";  // allow re-selecting the same file
    });
  }

  // ── Motion Layer editor (Living Still) ─────────
  // Every motion effect is a layer with its own params. The list IS what renders.
  window._motionLayers = [];
  const MOTION_SCHEMA = {
    breathing_zoom: { label: "Camera", params: [
      { key: "amount", label: "Zoom", min: 0, max: 0.25, step: 0.01, def: 0.08 },
      { key: "orbit", label: "Orbit", min: 0, max: 1, step: 0.05, def: 0.3 },
      { key: "pan", label: "Pan (glide)", min: 0, max: 1, step: 0.05, def: 0 } ] },
    parallax: { label: "Parallax depth", params: [
      { key: "amount", label: "Depth", min: 0, max: 1, step: 0.05, def: 0.5 } ] },
    particles: { label: "Particles", params: [
      { key: "kind", label: "Kind", type: "select", options: ["dust", "snow", "rain", "embers", "fireflies", "bokeh"], def: "dust" },
      { key: "count", label: "Count", min: 10, max: 500, step: 10, def: 200 },
      { key: "amount", label: "Strength", min: 0, max: 1.2, step: 0.05, def: 0.6 } ] },
    nebula: { label: "Nebula / gas drift", params: [
      { key: "amount", label: "Drift", min: 0, max: 1, step: 0.05, def: 0.5 } ] },
    shimmer: { label: "Shimmer", params: [
      { key: "amount", label: "Strength", min: 0, max: 1, step: 0.05, def: 0.5 },
      { key: "region", label: "Only on", type: "select", options: ["(whole frame)", "water"], def: "(whole frame)" } ] },
    twinkle: { label: "Twinkle lights", params: [
      { key: "amount", label: "Strength", min: 0, max: 1, step: 0.05, def: 0.7 } ] },
    god_rays: { label: "God rays", params: [
      { key: "amount", label: "Strength", min: 0, max: 0.9, step: 0.05, def: 0.5 },
      { key: "count", label: "Beams", min: 3, max: 16, step: 1, def: 8 } ] },
    aurora: { label: "Aurora", params: [
      { key: "amount", label: "Strength", min: 0, max: 1, step: 0.05, def: 0.7 } ] },
    color_glow: { label: "Color glow", params: [
      { key: "amount", label: "Strength", min: 0, max: 0.6, step: 0.02, def: 0.28 },
      { key: "color", label: "Color", type: "select", options: ["red", "amber", "gold", "orange", "blue", "cyan", "teal", "green", "purple", "magenta", "white", "warm"], def: "amber" } ] },
    fog: { label: "Fog / mist", params: [
      { key: "amount", label: "Density", min: 0, max: 0.5, step: 0.02, def: 0.22 } ] },
    light: { label: "Light breathing", params: [
      { key: "amount", label: "Strength", min: 0, max: 0.25, step: 0.01, def: 0.1 } ] },
    vignette_pulse: { label: "Vignette pulse", params: [
      { key: "amount", label: "Strength", min: 0, max: 0.4, step: 0.02, def: 0.16 } ] },
  };
  const MOTION_PRESETS = {
    drift: [{ type: "breathing_zoom", amount: 0.08, orbit: 0.35 }, { type: "light", amount: 0.07 }, { type: "vignette_pulse", amount: 0.14 }],
    stargaze: [{ type: "breathing_zoom", amount: 0.1, orbit: 0.5 }, { type: "twinkle", amount: 0.8 }, { type: "nebula", amount: 0.5 }, { type: "light", amount: 0.07 }, { type: "vignette_pulse", amount: 0.14 }],
    parallax: [{ type: "parallax", amount: 0.5 }, { type: "light", amount: 0.08 }, { type: "vignette_pulse", amount: 0.14 }],
    calm: [{ type: "breathing_zoom", amount: 0.1, orbit: 0.5 }, { type: "particles", kind: "dust", count: 140, amount: 0.5 }, { type: "fog", amount: 0.22 }, { type: "light", amount: 0.1 }, { type: "vignette_pulse", amount: 0.15 }],
  };
  const motionLayersList = document.getElementById("motion-layers-list");

  function _defaultMotionLayer(type) {
    const layer = { type };
    (MOTION_SCHEMA[type]?.params || []).forEach(p => {
      if (p.type === "select") { if (p.def !== "(whole frame)") layer[p.key] = p.def; }
      else layer[p.key] = p.def;
    });
    return layer;
  }

  function _renderMotionLayers() {
    if (!motionLayersList) return;
    const layers = window._motionLayers || [];
    if (!layers.length) {
      motionLayersList.innerHTML = '<div class="canvas-empty"><p class="canvas-empty-sub">No layers yet. <strong>Auto-plan from image</strong>, load a preset, or add layers — then tweak and Generate.</p></div>';
      return;
    }
    motionLayersList.innerHTML = layers.map((l, i) => {
      const schema = MOTION_SCHEMA[l.type] || { label: l.type, params: [] };
      const rows = schema.params.map(p => {
        if (p.type === "select") {
          const cur = l[p.key] != null ? l[p.key] : p.def;
          const opts = p.options.map(o => `<option value="${o}"${o === cur ? " selected" : ""}>${o}</option>`).join("");
          return `<label class="ml-param"><span>${p.label}</span><select class="ml-input" data-idx="${i}" data-key="${p.key}" data-kind="select">${opts}</select></label>`;
        }
        const cur = l[p.key] != null ? l[p.key] : p.def;
        return `<label class="ml-param"><span>${p.label}</span>
          <input type="range" class="ml-input" data-idx="${i}" data-key="${p.key}" min="${p.min}" max="${p.max}" step="${p.step}" value="${cur}">
          <span class="ml-val">${cur}</span></label>`;
      }).join("");
      return `<div class="ml-card"><div class="ml-card-head"><span class="ml-card-name">${schema.label}</span>
        <button class="ml-remove" data-idx="${i}" title="Remove">&times;</button></div>${rows}</div>`;
    }).join("");
    motionLayersList.querySelectorAll(".ml-input").forEach(el => {
      el.addEventListener("input", () => {
        const i = +el.dataset.idx, key = el.dataset.key;
        if (el.dataset.kind === "select") {
          if (el.value === "(whole frame)") delete window._motionLayers[i][key];
          else window._motionLayers[i][key] = el.value;
        } else {
          window._motionLayers[i][key] = parseFloat(el.value);
          const v = el.parentElement.querySelector(".ml-val"); if (v) v.textContent = el.value;
        }
      });
    });
    motionLayersList.querySelectorAll(".ml-remove").forEach(el => {
      el.addEventListener("click", () => { window._motionLayers.splice(+el.dataset.idx, 1); _renderMotionLayers(); });
    });
  }
  window._renderMotionLayers = _renderMotionLayers;

  document.getElementById("btn-add-motion-layer")?.addEventListener("click", () => {
    const type = document.getElementById("motion-add-type").value;
    window._motionLayers.push(_defaultMotionLayer(type));
    _renderMotionLayers();
  });
  document.getElementById("motion-loadpreset")?.addEventListener("change", (e) => {
    const preset = MOTION_PRESETS[e.target.value];
    if (preset) { window._motionLayers = preset.map(l => ({ ...l })); _renderMotionLayers(); }
    e.target.value = "";
  });
  document.getElementById("btn-auto-plan-motion")?.addEventListener("click", async () => {
    if (!visCurrentJobId) { alert("Select a track + scene image first"); return; }
    const btn = document.getElementById("btn-auto-plan-motion");
    btn.disabled = true; btn.textContent = "✦ Looking at image…";
    try {
      const res = await fetch(`/api/visual/motion-plan/${visCurrentJobId}`, { method: "POST" });
      const data = await res.json();
      if (data.error) alert("Auto-plan failed: " + data.error);
      else { window._motionLayers = (data.layers || []).map(l => ({ ...l })); _renderMotionLayers(); }
    } catch (e) { alert("Auto-plan failed: " + e.message); }
    btn.disabled = false; btn.textContent = "✦ Auto-plan from image";
  });

  // ── Clip generation (step 2) ──────────────────
  btnCreateClip.addEventListener("click", async () => {
    if (!visCurrentJobId) return;

    btnCreateClip.disabled = true;
    const isAI = currentVideoMode === "ai";
    btnCreateClip.textContent = isAI ? "Animating..." : "Processing...";
    clipPreview.classList.add("hidden");
    visExportPanel.classList.add("hidden");

    const initialMessage = isAI
      ? "Grok is animating your image (1-3 min)..."
      : "Creating Ken Burns clip...";

    await runLongTask(visCurrentJobId, {
      initialMessage,
      progressEl: clipProgress,
      progressTextEl: clipProgressText,
      stopBtn: clipStopBtn,
      startRequest: () => fetch(`/api/visual/clip/${visCurrentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: currentVideoMode,
          motion_prompt: motionPromptEl.value.trim(),
          // Editor-composed layers (what-you-see-is-what-renders). Empty → backend auto-plans.
          motion_layers: window._motionLayers || [],
          motion_loop_sec: parseFloat((document.getElementById("motion-loop-sec") || {}).value) || 16,
        }),
      }),
      onDone: (data) => showClipPreview(data.clip_url),
      onError: (msg) => { if (msg) alert("Animation failed: " + msg); },
    });

    btnCreateClip.disabled = false;
    btnCreateClip.textContent = "Generate Animation";
  });

  if (btnExtendClip) {
    btnExtendClip.addEventListener("click", async () => {
      if (!visCurrentJobId) return;

      btnExtendClip.disabled = true;
      btnExtendClip.textContent = "Extending...";

      await runLongTask(visCurrentJobId, {
        initialMessage: "Grok is extending the current clip (+10s)...",
        progressEl: clipProgress,
        progressTextEl: clipProgressText,
        stopBtn: clipStopBtn,
        startRequest: () => fetch(`/api/visual/extend/${visCurrentJobId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            prompt: extendPromptEl?.value.trim() || "",
            duration: 10,
          }),
        }),
        onDone: (data) => showClipPreview(data.clip_url),
        onError: (msg) => { if (msg) alert("Extend failed: " + msg); },
      });

      btnExtendClip.disabled = false;
      btnExtendClip.textContent = "Extend Clip (+10s)";
    });
  }

  if (btnApplySpeed) {
    btnApplySpeed.addEventListener("click", async () => {
      if (!visCurrentJobId) return;

      const speed = parseFloat(clipSpeedEl?.value || "0.5");
      btnApplySpeed.disabled = true;
      btnApplySpeed.textContent = "Applying...";

      await runLongTask(visCurrentJobId, {
        initialMessage: `Creating ${speed}x slowed clip...`,
        progressEl: clipProgress,
        progressTextEl: clipProgressText,
        stopBtn: clipStopBtn,
        startRequest: () => fetch(`/api/visual/slow/${visCurrentJobId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ speed }),
        }),
        onDone: (data) => showClipPreview(data.clip_url),
        onError: (msg) => { if (msg) alert("Speed change failed: " + msg); },
      });

      btnApplySpeed.disabled = false;
      btnApplySpeed.textContent = "Apply Speed";
    });
  }

  if (btnBoomerang) {
    btnBoomerang.addEventListener("click", async () => {
      if (!visCurrentJobId) return;

      btnBoomerang.disabled = true;
      btnBoomerang.textContent = "Creating...";

      await runLongTask(visCurrentJobId, {
        initialMessage: "Creating boomerang (ping-pong) loop...",
        progressEl: clipProgress,
        progressTextEl: clipProgressText,
        stopBtn: clipStopBtn,
        startRequest: () => fetch(`/api/visual/boomerang/${visCurrentJobId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        }),
        onDone: (data) => showClipPreview(data.clip_url),
        onError: (msg) => { if (msg) alert("Boomerang failed: " + msg); },
      });

      btnBoomerang.disabled = false;
      btnBoomerang.textContent = "↔ Boomerang Loop";
    });
  }

  // ── Export full video (step 3) ────────────────
  btnExportVideo.addEventListener("click", async () => {
    if (!visCurrentJobId) return;

    btnExportVideo.disabled = true;
    btnExportVideo.textContent = "Exporting...";
    videoDownload.classList.add("hidden");

    const minutes = parseFloat(videoDurationEl.value);

    await runLongTask(visCurrentJobId, {
      initialMessage: "Looping clip + combining with audio...",
      progressEl: exportProgress,
      progressTextEl: exportProgressText,
      stopBtn: exportStopBtn,
      startRequest: () => fetch(`/api/visual/export/${visCurrentJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duration_minutes: minutes }),
      }),
      onDone: (data) => {
        const exportPreview = document.getElementById("export-preview");
        const exportVideo = document.getElementById("export-video");
        exportVideo.src = `/api/visual/video/${visCurrentJobId}/view?t=${Date.now()}`;
        exportVideo.load();
        exportPreview.classList.remove("hidden");
        if (visMixer && visMixer.playing) visMixer.pause();
        videoDownloadLink.href = data.download_url;
        videoDownload.classList.remove("hidden");
      },
      onError: (msg) => { if (msg) alert("Export failed: " + msg); },
    });

    btnExportVideo.disabled = false;
    btnExportVideo.textContent = "Export Video";
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
  const pubVideoPreview = document.getElementById("pub-video-preview");
  const pubPreviewVideo = document.getElementById("pub-preview-video");
  const btnYtUpload = document.getElementById("btn-yt-upload");
  const uploadProgress = document.getElementById("upload-progress");
  const uploadProgressText = document.getElementById("upload-progress-text");
  const uploadProgressBar = document.getElementById("upload-progress-bar");
  const uploadResult = document.getElementById("upload-result");
  const uploadResultLink = document.getElementById("upload-result-link");

  let pubCurrentJobId = null;
  let ytConnected = false;

  function clearPubVideoPreview() {
    if (!pubPreviewVideo) return;
    pubPreviewVideo.pause();
    pubPreviewVideo.removeAttribute("src");
    pubPreviewVideo.load();
    pubVideoPreview?.classList.add("hidden");
  }

  function showPubVideoPreview(jobId) {
    if (!pubPreviewVideo || !pubVideoPreview) return;
    pubPreviewVideo.src = `/api/visual/video/${jobId}/view?t=${Date.now()}`;
    pubPreviewVideo.load();
    pubVideoPreview.classList.remove("hidden");
  }

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
      const withVideo = history.filter((j) => j.status === "complete" && j.visual_video_url);

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

  // Render the Publish tab for the globally-selected track.
  async function loadPublishForTrack(jobId, data) {
    if (!jobId) return;
    pubCurrentJobId = jobId;

    try {
      if (!data) { const res = await fetch(`/api/status/${jobId}`); data = await res.json(); }

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
        showPubVideoPreview(jobId);
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
        clearPubVideoPreview();
        pubMetaPanel.classList.add("hidden");
        pubUploadPanel.classList.add("hidden");
      }
    } catch (err) {
      console.error("Failed to load track:", err);
    }
  }
  window.loadPublishForTrack = loadPublishForTrack;

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
        if (data.needs_reconnect) checkYouTubeStatus();
        alert("Upload failed: " + data.error);
        btnYtUpload.disabled = false;
        btnYtUpload.textContent = "Upload to YouTube";
        return;
      }

      // Open upload progress in a new tab — works in all browsers including
      // embedded ones (Windsurf, etc.) that block popup windows.
      const uploadUrl = `/upload?job_id=${pubCurrentJobId}`;
      window.open(uploadUrl, "_blank");

      uploadProgressText.textContent = "Upload running in separate tab...";
      btnYtUpload.textContent = "Uploading (see new tab)...";

      // Listen for completion message from the popup
      const onMessage = (e) => {
        if (e.data && e.data.type === "yt-upload-done" && e.data.job_id === pubCurrentJobId) {
          window.removeEventListener("message", onMessage);
          uploadProgressBar.style.width = "100%";
          uploadProgressText.textContent = "Upload complete!";
          if (e.data.url) {
            uploadResultLink.href = e.data.url;
            uploadResultLink.textContent = e.data.url;
            uploadResult.classList.remove("hidden");
          }
          btnYtUpload.disabled = false;
          btnYtUpload.textContent = "Upload to YouTube";
          setTimeout(() => uploadProgress.classList.add("hidden"), 3000);
        }
      };
      window.addEventListener("message", onMessage);

      // Also poll in background so the main page updates even if popup is closed
      const pollUpload = setInterval(async () => {
        try {
          const sr = await fetch(`/api/youtube/upload-status/${pubCurrentJobId}`);
          const sd = await sr.json();
          uploadProgressBar.style.width = (sd.progress || 0) + "%";

          if (sd.status === "done") {
            clearInterval(pollUpload);
            window.removeEventListener("message", onMessage);
            uploadProgressBar.style.width = "100%";
            uploadProgressText.textContent = "Upload complete!";
            if (sd.youtube_url) {
              uploadResultLink.href = sd.youtube_url;
              uploadResultLink.textContent = sd.youtube_url;
              uploadResult.classList.remove("hidden");
            }
            btnYtUpload.disabled = false;
            btnYtUpload.textContent = "Upload to YouTube";
            setTimeout(() => uploadProgress.classList.add("hidden"), 3000);
          } else if (sd.status === "error") {
            clearInterval(pollUpload);
            window.removeEventListener("message", onMessage);
            const errMsg = sd.message || "Unknown error";
            uploadProgressText.textContent = "Upload failed: " + errMsg;
            if (errMsg.includes("authorization expired") || errMsg.includes("invalid_grant")) {
              checkYouTubeStatus();
            }
            btnYtUpload.disabled = false;
            btnYtUpload.textContent = "Upload to YouTube";
          }
        } catch (e) { /* keep polling */ }
      }, 3000);

    } catch (err) {
      alert("Upload failed: " + err.message);
      btnYtUpload.disabled = false;
      btnYtUpload.textContent = "Upload to YouTube";
    }
  });


  // ═══════════════════════════════════════════════════════
  //  TAB: Distribute
  // ═══════════════════════════════════════════════════════

  const distCatalogList = document.getElementById("dist-catalog-list");
  const distFilter = document.getElementById("dist-filter");
  const btnDistRefresh = document.getElementById("btn-dist-refresh");
  const distSelectedPanel = document.getElementById("dist-selected-panel");
  const distSelectedSummary = document.getElementById("dist-selected-summary");
  const distSubBtns = document.querySelectorAll(".dist-subnav-btn");
  const distSubPanels = {
    shorts: document.getElementById("dist-sub-shorts"),
    seo: document.getElementById("dist-sub-seo"),
    ads: document.getElementById("dist-sub-ads"),
    community: document.getElementById("dist-sub-community"),
    reddit: document.getElementById("dist-sub-reddit"),
    discord: document.getElementById("dist-sub-discord"),
  };

  let distSelectedJobId = null;
  let distCatalogCache = [];

  async function onDistributeTabOpen() {
    await refreshDistributeCatalog();
    await refreshStreamStatus();
    await refreshDiscordWebhookList();
  }

  btnDistRefresh.addEventListener("click", refreshDistributeCatalog);
  distFilter.addEventListener("change", renderDistributeCatalog);

  async function refreshDistributeCatalog() {
    try {
      const res = await fetch("/api/distribute/catalog");
      const data = await res.json();
      distCatalogCache = Array.isArray(data) ? data : [];
    } catch (err) {
      console.error("[Distribute] catalog fetch failed:", err);
      distCatalogCache = [];
    }
    renderDistributeCatalog();
  }

  function renderDistributeCatalog() {
    if (!distCatalogList) return;
    const f = distFilter.value;
    let rows = distCatalogCache.slice();
    if (f === "published") rows = rows.filter((r) => r.youtube_url);
    else if (f === "unpublished") rows = rows.filter((r) => !r.youtube_url);
    else if (f === "favorites") rows = rows.filter((r) => r.favorite);

    if (rows.length === 0) {
      distCatalogList.innerHTML = `<p class="form-hint">No tracks with exported videos yet. Export one on the Visuals tab to start.</p>`;
      return;
    }

    distCatalogList.innerHTML = rows.map((r) => {
      const thumb = r.visual_image_url
        ? `<img src="${r.visual_image_url}?t=${Date.now()}" alt="">`
        : `<div class="no-thumb">no thumb</div>`;
      const badges = [];
      if (r.youtube_url) badges.push(`<span class="badge badge-ready">Published</span>`);
      else badges.push(`<span class="badge badge-warn">Unpublished</span>`);
      if (r.shorts_total) badges.push(`<span class="badge">${r.shorts_published}/${r.shorts_total} Shorts</span>`);
      if (r.has_seo_v2) badges.push(`<span class="badge">SEO v2</span>`);
      if (r.has_ads_brief) badges.push(`<span class="badge">Ads brief</span>`);
      return `
        <div class="distribute-row" data-job-id="${r.job_id}">
          <div class="dist-thumb">${thumb}</div>
          <div class="dist-meta">
            <div class="dist-title">${escapeHtml(r.title || r.prompt.slice(0, 60))}</div>
            <div class="dist-prompt">${escapeHtml((r.prompt || "").slice(0, 140))}</div>
            <div class="dist-badges">${badges.join(" ")}</div>
          </div>
          <div class="dist-actions">
            <button class="btn btn-secondary btn-dist-select">Open</button>
            ${r.youtube_url ? `<a class="btn btn-secondary" href="${r.youtube_url}" target="_blank">YouTube</a>` : ""}
          </div>
        </div>
      `;
    }).join("");

    distCatalogList.querySelectorAll(".btn-dist-select").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const row = e.target.closest(".distribute-row");
        const jobId = row?.dataset?.jobId;
        if (jobId) selectDistributeRow(jobId);
      });
    });
    if (distSelectedJobId && !rows.find((r) => r.job_id === distSelectedJobId)) {
      // Selected row is no longer visible — clear selection.
      distSelectedJobId = null;
      distSelectedPanel.classList.add("hidden");
      Object.values(distSubPanels).forEach((p) => p.classList.add("hidden"));
    }
  }

  function selectDistributeRow(jobId) {
    distSelectedJobId = jobId;
    const row = distCatalogCache.find((r) => r.job_id === jobId);
    if (!row) return;
    distSelectedPanel.classList.remove("hidden");
    distSelectedSummary.innerHTML = `
      <strong>${escapeHtml(row.title)}</strong>
      <div class="form-hint">${escapeHtml(row.prompt.slice(0, 200))}</div>
      <div class="dist-badges">
        ${row.youtube_url ? `<a class="badge badge-ready" href="${row.youtube_url}" target="_blank">View on YouTube</a>` : `<span class="badge badge-warn">Not uploaded</span>`}
        <span class="badge">${row.shorts_published}/${row.shorts_total} Shorts published</span>
        ${!row.youtube_url ? `<button type="button" class="btn btn-secondary btn-small" onclick="window.__attachYoutubeUrl && window.__attachYoutubeUrl('${jobId}')">Attach existing YouTube URL…</button>` : ""}
      </div>
    `;
    // Reset to shorts sub by default.
    activateDistSubpanel("shorts");
    refreshShortsList();
  }

  distSubBtns.forEach((btn) => {
    btn.addEventListener("click", () => activateDistSubpanel(btn.dataset.sub));
  });

  function activateDistSubpanel(sub) {
    distSubBtns.forEach((b) => b.classList.toggle("active", b.dataset.sub === sub));
    Object.entries(distSubPanels).forEach(([k, panel]) => {
      panel.classList.toggle("hidden", k !== sub);
    });
    if (sub === "shorts") refreshShortsList();
    if (sub === "seo") renderSeoV2FromCache();
    if (sub === "ads") renderAdsBriefFromCache();
    if (sub === "community") renderCommunityFromCache();
    if (sub === "reddit") renderRedditFromCache();
    if (sub === "discord") refreshDiscordWebhookList();
  }

  // ── Shorts factory ────────────────────────────
  const shortsCountEl = document.getElementById("shorts-count");
  const shortsModeEl = document.getElementById("shorts-mode");
  const shortsManualStartGroup = document.getElementById("shorts-manual-start-group");
  const shortsManualStartEl = document.getElementById("shorts-manual-start");
  const shortsClipSecEl = document.getElementById("shorts-clip-sec");
  const shortsVisualModeEl = document.getElementById("shorts-visual-mode");
  const btnShortsGenerate = document.getElementById("btn-shorts-generate");
  const shortsStatus = document.getElementById("shorts-status");
  const shortsList = document.getElementById("shorts-list");

  shortsModeEl.addEventListener("change", () => {
    shortsManualStartGroup.style.display = shortsModeEl.value === "manual" ? "" : "none";
  });

  btnShortsGenerate.addEventListener("click", async () => {
    if (!distSelectedJobId) return;
    const body = {
      count: parseInt(shortsCountEl.value, 10),
      mode: shortsModeEl.value,
      manual_start_sec: parseFloat(shortsManualStartEl.value) || 0,
      clip_sec: parseFloat(shortsClipSecEl.value) || 50,
      visual_mode: shortsVisualModeEl.value,
    };

    btnShortsGenerate.disabled = true;
    btnShortsGenerate.textContent = "Generating…";
    shortsStatus.textContent = "Starting…";
    try {
      const res = await fetch(`/api/distribute/shorts/${distSelectedJobId}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const out = await res.json();
      if (out.error) throw new Error(out.error);
      // Poll task-status.
      const poll = setInterval(async () => {
        try {
          const sr = await fetch(`/api/task-status/${distSelectedJobId}`);
          const sd = await sr.json();
          shortsStatus.textContent = sd.message || sd.status || "";
          if (sd.status === "done" || sd.status === "error" || sd.status === "canceled") {
            clearInterval(poll);
            btnShortsGenerate.disabled = false;
            btnShortsGenerate.textContent = "Generate Shorts";
            await refreshShortsList();
            await refreshDistributeCatalog();
          }
        } catch (e) { /* keep polling */ }
      }, 1500);
    } catch (err) {
      shortsStatus.textContent = "Error: " + err.message;
      btnShortsGenerate.disabled = false;
      btnShortsGenerate.textContent = "Generate Shorts";
    }
  });

  window.__attachYoutubeUrl = attachYoutubeUrl;
  async function attachYoutubeUrl(jobId) {
    console.log("[Distribute] attachYoutubeUrl invoked for", jobId);
    const url = prompt(
      "Paste the existing YouTube URL for this job\n" +
      "(e.g. https://www.youtube.com/watch?v=… or https://youtu.be/…)"
    );
    if (!url) return;
    const applyThumb = confirm(
      "Also re-apply this job's thumbnail to that video?\n\n" +
      "OK = compress + upload thumbnail (uses your YouTube quota)\n" +
      "Cancel = just link the URL, leave the thumbnail alone"
    );
    try {
      const res = await fetch(`/api/distribute/attach-youtube/${jobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ youtube_url: url, apply_thumbnail: applyThumb }),
      });
      const data = await res.json();
      if (!res.ok) {
        alert("Couldn't attach: " + (data.error || res.statusText));
        return;
      }
      const note = data.thumbnail ? `\n\n${data.thumbnail}` : "";
      alert(`Linked.${note}`);
      await refreshDistributeCatalog();
      selectDistributeRow(jobId);
    } catch (e) {
      alert("Network error: " + e.message);
    }
  }

  async function refreshShortsList() {
    if (!distSelectedJobId || !shortsList) return;
    try {
      const res = await fetch(`/api/distribute/shorts/${distSelectedJobId}`);
      const items = await res.json();
      if (!Array.isArray(items) || items.length === 0) {
        shortsList.innerHTML = `<p class="form-hint">No Shorts yet. Generate the first ones above.</p>`;
        return;
      }
      shortsList.innerHTML = items.map((s) => {
        const preview = s.preview_url
          ? `<video class="short-preview" controls preload="metadata" src="${s.preview_url}"></video>`
          : `<div class="short-preview-missing">video missing</div>`;
        const ytLink = s.youtube_url
          ? `<a class="badge badge-ready" href="${s.youtube_url}" target="_blank">View on YouTube</a>`
          : `<button class="btn btn-primary btn-short-publish" data-short-id="${s.short_id}">Publish</button>`;
        return `
          <div class="short-card" data-short-id="${s.short_id}">
            ${preview}
            <div class="short-meta">
              <div class="form-group">
                <label>Title</label>
                <input type="text" class="short-title" value="${escapeHtml(s.yt_title || '')}" maxlength="100">
              </div>
              <div class="form-group">
                <label>Description</label>
                <textarea class="short-desc" rows="3">${escapeHtml(s.yt_description || '')}</textarea>
              </div>
              <div class="form-group">
                <label>Tags (comma sep)</label>
                <input type="text" class="short-tags" value="${escapeHtml(Array.isArray(s.yt_tags) ? s.yt_tags.join(', ') : (s.yt_tags || ''))}">
              </div>
              <div class="short-card-actions">
                <button class="btn btn-secondary btn-short-save" data-short-id="${s.short_id}">Save metadata</button>
                ${ytLink}
                <button class="btn btn-secondary btn-short-delete" data-short-id="${s.short_id}">Delete</button>
              </div>
              <span class="form-hint">Moment: ${escapeHtml(s.moment_description || '')} · ${s.clip_sec || 0}s starting ${s.start_sec ? s.start_sec.toFixed(1) : '0'}s</span>
              <span class="short-upload-status form-hint" data-short-id="${s.short_id}">${s.upload_status === 'uploading' ? 'Uploading…' : ''}</span>
            </div>
          </div>
        `;
      }).join("");
      attachShortHandlers();
    } catch (err) {
      console.error("[Shorts] list failed:", err);
    }
  }

  function attachShortHandlers() {
    shortsList.querySelectorAll(".btn-short-save").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const card = btn.closest(".short-card");
        const shortId = btn.dataset.shortId;
        const title = card.querySelector(".short-title").value;
        const description = card.querySelector(".short-desc").value;
        const tags = card.querySelector(".short-tags").value;
        btn.disabled = true; btn.textContent = "Saving…";
        try {
          const res = await fetch(`/api/distribute/shorts/${shortId}/metadata`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title, description, tags }),
          });
          const out = await res.json();
          if (out.error) throw new Error(out.error);
          btn.textContent = "Saved";
          setTimeout(() => { btn.textContent = "Save metadata"; btn.disabled = false; }, 1500);
        } catch (e) {
          btn.textContent = "Save metadata"; btn.disabled = false;
          alert("Save failed: " + e.message);
        }
      });
    });

    shortsList.querySelectorAll(".btn-short-delete").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const shortId = btn.dataset.shortId;
        if (!confirm("Delete this Short?")) return;
        await fetch(`/api/distribute/shorts/${shortId}`, { method: "DELETE" });
        await refreshShortsList();
        await refreshDistributeCatalog();
      });
    });

    shortsList.querySelectorAll(".btn-short-publish").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const card = btn.closest(".short-card");
        const shortId = btn.dataset.shortId;
        const title = card.querySelector(".short-title").value.trim();
        if (!title) { alert("Title required."); return; }
        const description = card.querySelector(".short-desc").value;
        const tags = card.querySelector(".short-tags").value;
        btn.disabled = true; btn.textContent = "Publishing…";
        try {
          const res = await fetch(`/api/distribute/shorts/${shortId}/publish`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title, description, tags, privacy: "public" }),
          });
          const out = await res.json();
          if (out.error) throw new Error(out.error);
          pollShortUploadStatus(shortId);
        } catch (e) {
          btn.disabled = false; btn.textContent = "Publish";
          alert("Publish failed: " + e.message);
        }
      });
    });
  }

  function pollShortUploadStatus(shortId) {
    const statusEl = shortsList.querySelector(`.short-upload-status[data-short-id="${shortId}"]`);
    if (statusEl) statusEl.textContent = "Uploading…";
    const interval = setInterval(async () => {
      try {
        const r = await fetch(`/api/distribute/shorts/${shortId}/upload-status`);
        const d = await r.json();
        if (statusEl) statusEl.textContent = d.message || d.status || "";
        if (d.status === "done" || d.status === "error") {
          clearInterval(interval);
          await refreshShortsList();
          await refreshDistributeCatalog();
        }
      } catch (e) { /* keep polling */ }
    }, 2000);
  }

  // ── SEO v2 ────────────────────────────────────
  const seoComparablesEl = document.getElementById("seo-comparables");
  const btnSeoV2 = document.getElementById("btn-seo-v2");
  const seoOutput = document.getElementById("seo-v2-output");

  btnSeoV2.addEventListener("click", async () => {
    if (!distSelectedJobId) return;
    btnSeoV2.disabled = true; btnSeoV2.textContent = "Generating…";
    seoOutput.innerHTML = "<p class='form-hint'>Working…</p>";
    try {
      const comparable_channels = seoComparablesEl.value.split(",").map((s) => s.trim()).filter(Boolean);
      const res = await fetch(`/api/distribute/seo-v2/${distSelectedJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comparable_channels }),
      });
      const out = await res.json();
      if (out.error) throw new Error(out.error);
      renderSeoV2(out);
    } catch (e) {
      seoOutput.innerHTML = `<p class="form-hint">Error: ${escapeHtml(e.message)}</p>`;
    }
    btnSeoV2.disabled = false; btnSeoV2.textContent = "Generate SEO v2";
  });

  function renderSeoV2(out) {
    const titles = (out.title_variants || []).map((t, i) => `
      <div class="seo-title-row">
        <strong>Title ${i + 1}:</strong>
        <span class="seo-title-value">${escapeHtml(t)}</span>
        <button class="btn btn-secondary btn-copy" data-copy-text="${escapeHtml(t)}">Copy</button>
      </div>
    `).join("");
    seoOutput.innerHTML = `
      <h4>Title variants</h4>
      ${titles || "<p>(none)</p>"}
      <h4>Description</h4>
      <pre class="seo-block">${escapeHtml(out.description || "")}</pre>
      <button class="btn btn-secondary btn-copy" data-copy-text="${escapeHtml(out.description || '')}">Copy description</button>
      <h4>Tags</h4>
      <pre class="seo-block">${escapeHtml(Array.isArray(out.tags) ? out.tags.join(", ") : (out.tags || ""))}</pre>
      <h4>Thumbnail prompt</h4>
      <pre class="seo-block">${escapeHtml(out.thumbnail_prompt || "")}</pre>
      <button class="btn btn-secondary btn-copy" data-copy-text="${escapeHtml(out.thumbnail_prompt || '')}">Copy thumbnail prompt</button>
    `;
    attachCopyHandlers(seoOutput);
  }

  async function renderSeoV2FromCache() {
    if (!distSelectedJobId) return;
    try {
      const res = await fetch(`/api/status/${distSelectedJobId}`);
      const data = await res.json();
      if (data.seo_v2) renderSeoV2(data.seo_v2);
      else seoOutput.innerHTML = "<p class='form-hint'>No SEO v2 generated for this track yet.</p>";
    } catch (e) { /* ignore */ }
  }

  // ── Ads brief ─────────────────────────────────
  const adsComparablesEl = document.getElementById("ads-comparables");
  const adsBudgetEl = document.getElementById("ads-budget");
  const btnAdsBrief = document.getElementById("btn-ads-brief");
  const adsOutput = document.getElementById("ads-brief-output");

  btnAdsBrief.addEventListener("click", async () => {
    if (!distSelectedJobId) return;
    btnAdsBrief.disabled = true; btnAdsBrief.textContent = "Generating…";
    adsOutput.innerHTML = "<p class='form-hint'>Working…</p>";
    try {
      const comparable_channels = adsComparablesEl.value.split(",").map((s) => s.trim()).filter(Boolean);
      const res = await fetch(`/api/distribute/ads/brief/${distSelectedJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comparable_channels, budget_range: adsBudgetEl.value }),
      });
      const out = await res.json();
      if (out.error) throw new Error(out.error);
      renderAdsBrief(out.brief_md);
      await refreshDistributeCatalog();
    } catch (e) {
      adsOutput.innerHTML = `<p class="form-hint">Error: ${escapeHtml(e.message)}</p>`;
    }
    btnAdsBrief.disabled = false; btnAdsBrief.textContent = "Generate Ads brief";
  });

  function renderAdsBrief(md) {
    adsOutput.innerHTML = `
      <pre class="ads-brief-block">${escapeHtml(md || "")}</pre>
      <button class="btn btn-secondary btn-copy" data-copy-text="${escapeHtml(md || '')}">Copy brief</button>
    `;
    attachCopyHandlers(adsOutput);
  }

  async function renderAdsBriefFromCache() {
    if (!distSelectedJobId) return;
    try {
      const res = await fetch(`/api/distribute/ads/brief/${distSelectedJobId}`);
      const out = await res.json();
      if (out.brief_md) renderAdsBrief(out.brief_md);
      else adsOutput.innerHTML = "<p class='form-hint'>No ads brief yet for this track.</p>";
    } catch (e) { /* ignore */ }
  }

  // ── Community ─────────────────────────────────
  const communityOutput = document.getElementById("community-output");
  document.querySelectorAll("[data-community-style]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!distSelectedJobId) return;
      const style = btn.dataset.communityStyle;
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = "Writing…";
      try {
        const res = await fetch(`/api/distribute/community/draft/${distSelectedJobId}?style=${encodeURIComponent(style)}`, { method: "POST" });
        const out = await res.json();
        if (out.error) throw new Error(out.error);
        renderCommunity(out);
      } catch (e) {
        communityOutput.innerHTML = `<p class="form-hint">Error: ${escapeHtml(e.message)}</p>`;
      }
      btn.disabled = false; btn.textContent = orig;
    });
  });

  function renderCommunity(out) {
    communityOutput.innerHTML = `
      <h4>${escapeHtml(out.style)} draft</h4>
      <pre class="seo-block">${escapeHtml(out.body || "")}</pre>
      <button class="btn btn-secondary btn-copy" data-copy-text="${escapeHtml(out.body || '')}">Copy</button>
      <a class="btn btn-secondary" href="${out.studio_url}" target="_blank">Open YouTube Studio Community</a>
    `;
    attachCopyHandlers(communityOutput);
  }

  async function renderCommunityFromCache() {
    if (!distSelectedJobId) return;
    try {
      const res = await fetch(`/api/status/${distSelectedJobId}`);
      const data = await res.json();
      const drafts = data.community_drafts || {};
      const keys = Object.keys(drafts);
      if (keys.length === 0) {
        communityOutput.innerHTML = "<p class='form-hint'>No community drafts yet. Pick a style above.</p>";
        return;
      }
      // Show the most recent draft.
      const sorted = keys.sort((a, b) => (drafts[b].generated_at || "").localeCompare(drafts[a].generated_at || ""));
      const top = sorted[0];
      renderCommunity({ style: top, body: drafts[top].body, studio_url: "https://studio.youtube.com/channel/UC/community" });
    } catch (e) { /* ignore */ }
  }

  // ── Reddit ────────────────────────────────────
  const redditSubEl = document.getElementById("reddit-sub");
  const redditContextEl = document.getElementById("reddit-context");
  const btnRedditDraft = document.getElementById("btn-reddit-draft");
  const redditOutput = document.getElementById("reddit-output");

  btnRedditDraft.addEventListener("click", async () => {
    if (!distSelectedJobId) return;
    btnRedditDraft.disabled = true; btnRedditDraft.textContent = "Writing…";
    redditOutput.innerHTML = "<p class='form-hint'>Working…</p>";
    try {
      const res = await fetch(`/api/distribute/reddit/draft/${distSelectedJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subreddit: redditSubEl.value.trim(),
          context_hint: redditContextEl.value.trim(),
        }),
      });
      const out = await res.json();
      if (out.error) throw new Error(out.error);
      renderReddit(out);
    } catch (e) {
      redditOutput.innerHTML = `<p class="form-hint">Error: ${escapeHtml(e.message)}</p>`;
    }
    btnRedditDraft.disabled = false; btnRedditDraft.textContent = "Generate Reddit draft";
  });

  function renderReddit(out) {
    redditOutput.innerHTML = `
      <h4>r/${escapeHtml(out.subreddit || "")}</h4>
      <div class="form-group">
        <label>Title</label>
        <input type="text" class="reddit-title-out" value="${escapeHtml(out.title || '')}">
      </div>
      <div class="form-group">
        <label>Body</label>
        <textarea class="reddit-body-out" rows="8">${escapeHtml(out.body || "")}</textarea>
      </div>
      <a class="btn btn-primary" href="${out.submit_url}" target="_blank">Open Reddit submit page (prefilled)</a>
      <button class="btn btn-secondary btn-copy" data-copy-text="${escapeHtml(out.body || '')}">Copy body</button>
    `;
    attachCopyHandlers(redditOutput);
  }

  async function renderRedditFromCache() {
    if (!distSelectedJobId) return;
    try {
      const res = await fetch(`/api/status/${distSelectedJobId}`);
      const data = await res.json();
      const drafts = data.reddit_drafts || {};
      const keys = Object.keys(drafts);
      if (keys.length === 0) {
        redditOutput.innerHTML = "<p class='form-hint'>No Reddit drafts yet.</p>";
        return;
      }
      const sorted = keys.sort((a, b) => (drafts[b].generated_at || "").localeCompare(drafts[a].generated_at || ""));
      const sub = sorted[0];
      const draft = drafts[sub];
      const submit_url = `https://www.reddit.com/r/${sub}/submit?title=${encodeURIComponent(draft.title || '')}&text=${encodeURIComponent(draft.body || '')}&kind=self`;
      renderReddit({ subreddit: sub, title: draft.title, body: draft.body, submit_url });
    } catch (e) { /* ignore */ }
  }

  // ── Discord ───────────────────────────────────
  const discordWebhookSelect = document.getElementById("discord-webhook-name");
  const discordContextEl = document.getElementById("discord-context");
  const btnDiscordPost = document.getElementById("btn-discord-post");
  const btnDiscordAddWebhook = document.getElementById("btn-discord-add-webhook");
  const discordOutput = document.getElementById("discord-output");
  const discordWebhooksState = document.getElementById("discord-webhooks-state");

  async function refreshDiscordWebhookList() {
    try {
      const res = await fetch("/api/distribute/secrets");
      const out = await res.json();
      const names = out.discord_webhook_names || [];
      discordWebhookSelect.innerHTML = names.length
        ? names.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join("")
        : `<option value="">— no webhooks saved —</option>`;
      discordWebhooksState.innerHTML = names.length
        ? `<p class="form-hint">${names.length} webhook${names.length === 1 ? '' : 's'} saved.</p>`
        : `<p class="form-hint">No Discord webhooks saved yet. Click "Add webhook" to store one.</p>`;
    } catch (e) { /* ignore */ }
  }

  btnDiscordAddWebhook.addEventListener("click", async () => {
    const name = prompt("Webhook name (any short label, e.g. 'main'):");
    if (!name) return;
    const url = prompt("Discord webhook URL (server settings → Integrations → Webhooks):");
    if (!url) return;
    await fetch("/api/distribute/secrets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ discord_webhooks: { [name]: url } }),
    });
    await refreshDiscordWebhookList();
  });

  btnDiscordPost.addEventListener("click", async () => {
    if (!distSelectedJobId) return;
    const webhook_name = discordWebhookSelect.value;
    if (!webhook_name) { alert("Add a webhook first."); return; }
    btnDiscordPost.disabled = true; btnDiscordPost.textContent = "Posting…";
    discordOutput.innerHTML = "<p class='form-hint'>Working…</p>";
    try {
      const res = await fetch(`/api/distribute/discord/post/${distSelectedJobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ webhook_name, context_hint: discordContextEl.value.trim() }),
      });
      const out = await res.json();
      if (out.error) throw new Error(out.error);
      discordOutput.innerHTML = `
        <p class="form-hint">Posted via webhook "${escapeHtml(out.webhook_name)}".</p>
        <pre class="seo-block">${escapeHtml(out.body)}</pre>
      `;
    } catch (e) {
      discordOutput.innerHTML = `<p class="form-hint">Error: ${escapeHtml(e.message)}</p>`;
    }
    btnDiscordPost.disabled = false; btnDiscordPost.textContent = "Generate & post to Discord";
  });

  // ── Live stream ───────────────────────────────
  const streamStatusEl = document.getElementById("stream-status");
  const streamPlaylistCountEl = document.getElementById("stream-playlist-count");
  const streamStartedEl = document.getElementById("stream-started");
  const streamErrorEl = document.getElementById("stream-error");
  const streamUrlEl = document.getElementById("stream-url");
  const streamKeyEl = document.getElementById("stream-key");
  const btnStreamSaveKey = document.getElementById("btn-stream-save-key");
  const btnStreamRebuild = document.getElementById("btn-stream-rebuild");
  const btnStreamStart = document.getElementById("btn-stream-start");
  const btnStreamStop = document.getElementById("btn-stream-stop");

  async function refreshStreamStatus() {
    try {
      const res = await fetch("/api/distribute/stream/status");
      const s = await res.json();
      streamStatusEl.textContent = s.status || "unknown";
      streamPlaylistCountEl.textContent = s.playlist_tracks ?? "—";
      streamStartedEl.textContent = s.started_at || "—";
      if (s.last_error) {
        streamErrorEl.textContent = s.last_error;
        streamErrorEl.classList.remove("hidden");
      } else {
        streamErrorEl.classList.add("hidden");
      }
      if (s.rtmp_url) streamUrlEl.value = s.rtmp_url;
      btnStreamStart.disabled = s.status === "running";
      btnStreamStop.disabled = s.status !== "running";
    } catch (e) { /* ignore */ }
  }

  btnStreamSaveKey.addEventListener("click", async () => {
    btnStreamSaveKey.disabled = true; btnStreamSaveKey.textContent = "Saving…";
    try {
      await fetch("/api/distribute/secrets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          youtube_stream_url: streamUrlEl.value.trim(),
          youtube_stream_key: streamKeyEl.value.trim(),
        }),
      });
      btnStreamSaveKey.textContent = "Saved";
      streamKeyEl.value = "";
      setTimeout(() => { btnStreamSaveKey.textContent = "Save stream settings"; btnStreamSaveKey.disabled = false; }, 1500);
    } catch (e) {
      alert("Save failed: " + e.message);
      btnStreamSaveKey.disabled = false; btnStreamSaveKey.textContent = "Save stream settings";
    }
  });

  btnStreamRebuild.addEventListener("click", async () => {
    btnStreamRebuild.disabled = true; btnStreamRebuild.textContent = "Rebuilding…";
    try {
      const res = await fetch("/api/distribute/stream/playlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const out = await res.json();
      alert(`Playlist rebuilt — ${out.tracks} track(s).`);
      await refreshStreamStatus();
    } catch (e) {
      alert("Rebuild failed: " + e.message);
    }
    btnStreamRebuild.disabled = false; btnStreamRebuild.textContent = "Rebuild playlist from catalog";
  });

  btnStreamStart.addEventListener("click", async () => {
    if (!confirm("Start the YouTube Live stream now? Make sure 'Go Live' is set up in YouTube Studio.")) return;
    btnStreamStart.disabled = true; btnStreamStart.textContent = "Starting…";
    try {
      const res = await fetch("/api/distribute/stream/start", { method: "POST" });
      const out = await res.json();
      if (out.error) throw new Error(out.error);
      await refreshStreamStatus();
    } catch (e) {
      alert("Start failed: " + e.message);
    }
    btnStreamStart.textContent = "Start stream";
  });

  btnStreamStop.addEventListener("click", async () => {
    if (!confirm("Stop the live stream?")) return;
    btnStreamStop.disabled = true; btnStreamStop.textContent = "Stopping…";
    try {
      await fetch("/api/distribute/stream/stop", { method: "POST" });
      await refreshStreamStatus();
    } catch (e) {
      alert("Stop failed: " + e.message);
    }
    btnStreamStop.textContent = "Stop stream";
  });

  // Poll stream status every 30s while the Distribute tab is open.
  setInterval(() => {
    if (document.getElementById("tab-distribute").classList.contains("active")) {
      refreshStreamStatus();
    }
  }, 30000);

  // ── Shared helpers ────────────────────────────
  function attachCopyHandlers(scope) {
    scope.querySelectorAll(".btn-copy").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const text = btn.dataset.copyText || "";
        try {
          await navigator.clipboard.writeText(text);
          const orig = btn.textContent;
          btn.textContent = "Copied!";
          setTimeout(() => { btn.textContent = orig; }, 1200);
        } catch (e) {
          alert("Copy failed: " + e.message);
        }
      });
    });
  }


  // ═══════════════════════════════════════════════════════
  //  Shared
  // ═══════════════════════════════════════════════════════

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Init ──────────────────────────────────────
  // Restore the tab you were on across refreshes.
  try {
    const savedTab = localStorage.getItem("ambientizer_active_tab");
    if (savedTab && savedTab !== "create") {
      const tb = document.querySelector(`.tab-btn[data-tab="${savedTab}"]`);
      if (tb) tb.click();
    }
  } catch (e) {}

  refreshHistory().then(() => {
    // Restore whichever track was selected last time (persisted in localStorage);
    // fall back to the most recent if that track no longer exists. Loaded PAUSED
    // and ready, so the first tap on play actually plays (works on iOS too).
    if (currentJobId || !historySelect) return;
    let target = "";
    try {
      const saved = localStorage.getItem("ambientizer_last_track");
      if (saved && [...historySelect.options].some(o => o.value === saved)) target = saved;
    } catch (e) {}
    if (!target) target = historySelect.value;  // most recent
    if (target) { historySelect.value = target; viewJob(target, false); }
  });
})();
