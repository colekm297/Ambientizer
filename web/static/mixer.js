/**
 * mixer.js — Web Audio API live mixer for Ambientizer
 *
 * Plays each layer as an independent looping AudioBuffer with real-time
 * control over volume, pan, low-pass filter, reverb, and swell (LFO).
 * Slider changes are instant — no server round-trip, no playback restart.
 *
 * Only destructive operations (regenerate, pitch shift, add layer) need
 * a server call, and they reload only the affected layer's buffer.
 */

class LiveMixer {
  constructor() {
    this.ctx = null;
    this.layers = {};
    this.masterGain = null;
    this.playing = false;
    this.startedAt = 0;
    this.pausedAt = 0;
    this.duration = 300;
    this.onTimeUpdate = null;
    this._timer = null;
    this._reverbImpulse = null;
    this._alternates = [];
    this._looping = true;
    this._hasLooped = false;
    this._masterVolume = 1;
  }

  async init(durationSec) {
    // iOS Safari: by default Web Audio uses a silenceable "ambient" audio
    // session — the context can be running with sources playing yet produce NO
    // speaker output (and it obeys the ringer switch). Declaring "playback"
    // routes it to the main speaker at full volume. (iOS 16.4+; no-op elsewhere.)
    try {
      if (navigator.audioSession) navigator.audioSession.type = "playback";
    } catch (e) { /* unsupported — ignore */ }

    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    this.duration = durationSec;
    this.masterGain = this.ctx.createGain();
    this.masterGain.connect(this.ctx.destination);
    this._reverbImpulse = this._buildReverbIR(2.5, 3.0);
    this._installIOSUnlock();
    this._initAudioStatus();
    console.log(`[LiveMixer] init: duration=${durationSec}s (${(durationSec/60).toFixed(1)} min)`);
  }

  // iOS won't output ANY Web Audio until a buffer has been played from inside a
  // user gesture — resume() alone isn't enough. We play a 1-sample silent buffer
  // on the first touch/click to "unlock" the audio hardware.
  _installIOSUnlock() {
    const unlock = async () => {
      try {
        await this.ctx.resume();
        const buf = this.ctx.createBuffer(1, 1, 22050);
        const src = this.ctx.createBufferSource();
        src.buffer = buf;
        src.connect(this.ctx.destination);
        src.start(0);
      } catch (e) {
        console.warn("[LiveMixer] iOS unlock failed", e);
      }
      this._updateAudioStatus();
      if (this.ctx.state === "running") {
        document.removeEventListener("touchend", unlock, true);
        document.removeEventListener("click", unlock, true);
      }
    };
    document.addEventListener("touchend", unlock, true);
    document.addEventListener("click", unlock, true);
  }

  // Tiny on-screen readout so we can diagnose audio state on the phone.
  // Disabled now that iOS audio is confirmed working; flip to true to re-enable.
  _initAudioStatus() {
    if (!window._ambientizerAudioDebug) return;
    let el = document.getElementById("audio-status");
    if (!el) {
      el = document.createElement("div");
      el.id = "audio-status";
      el.style.cssText = "position:fixed;bottom:6px;left:6px;z-index:99999;font:11px monospace;" +
        "background:rgba(0,0,0,.72);color:#3f3;padding:3px 7px;border-radius:4px;pointer-events:none;";
      document.body.appendChild(el);
    }
    this._audioStatusEl = el;
    this._updateAudioStatus();
  }

  _updateAudioStatus() {
    if (!this._audioStatusEl) return;
    const c = this.ctx;
    const ls = Object.values(this.layers);
    // per-layer detail for the first layer: gain, dry/wet, muted, source live?
    let detail = "";
    if (ls.length) {
      const l = ls[0];
      const g = l.gain ? l.gain.gain.value.toFixed(2) : "?";
      const dry = l.dryGain ? l.dryGain.gain.value.toFixed(2) : "?";
      const mg = this.masterGain ? this.masterGain.gain.value.toFixed(2) : "?";
      detail = ` | L0 g${g} dry${dry} ${l.muted ? "MUTED" : "on"} src${l.source ? "✓" : "✗"} | mg${mg}`;
    }
    this._audioStatusEl.textContent =
      `audio:${c ? c.state : "no-ctx"} sr${c ? c.sampleRate : "-"} layers${ls.length}${detail}`;
  }

  _buildReverbIR(seconds, decay) {
    const len = this.ctx.sampleRate * seconds;
    const buf = this.ctx.createBuffer(2, len, this.ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch);
      for (let i = 0; i < len; i++) {
        d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay);
      }
    }
    return buf;
  }

  _dbToLinear(db) {
    return Math.pow(10, db / 20);
  }

  async addLayer(name, url, opts = {}) {
    const resp = await fetch(url);
    if (!resp.ok) {
      throw new Error(`Layer "${name}" audio fetch failed: HTTP ${resp.status}`);
    }
    const ab = await resp.arrayBuffer();
    if (ab.byteLength < 100) {
      throw new Error(`Layer "${name}" audio is empty or too small (${ab.byteLength} bytes)`);
    }
    // If the mixer was destroyed while this layer was fetching (e.g. the user
    // navigated to a different song and a new initMixer call ran), abort
    // cleanly instead of crashing on a null ctx.
    if (!this.ctx) {
      throw new Error(`Layer "${name}" cancelled: mixer was destroyed mid-load`);
    }
    const audioBuf = await this.ctx.decodeAudioData(ab);
    if (!this.ctx) {
      throw new Error(`Layer "${name}" cancelled: mixer was destroyed during decode`);
    }

    const gain = this.ctx.createGain();
    const pan = this.ctx.createStereoPanner();
    const filter = this.ctx.createBiquadFilter();
    const swellGain = this.ctx.createGain();
    const controlGain = this.ctx.createGain();
    const dryGain = this.ctx.createGain();
    const wetGain = this.ctx.createGain();
    const convolver = this.ctx.createConvolver();
    convolver.buffer = this._reverbImpulse;

    filter.type = "lowpass";
    filter.frequency.value = opts.low_pass_hz || 20000;
    filter.Q.value = 0.707;

    // Chain: source → gain → pan → filter → swell → controlGain → dry/wet → master
    // controlGain is ONLY for solo/timing — keeps _applyGain untouched
    gain.connect(pan);
    pan.connect(filter);
    filter.connect(swellGain);
    swellGain.connect(controlGain);
    controlGain.connect(dryGain);
    dryGain.connect(this.masterGain);
    controlGain.connect(convolver);
    convolver.connect(wetGain);
    wetGain.connect(this.masterGain);

    const layer = {
      name,
      buffer: audioBuf,
      source: null,
      gain,
      pan,
      filter,
      swellGain,
      controlGain,
      dryGain,
      wetGain,
      convolver,
      swellLFO: null,
      swellLFOGain: null,
      volume_db: opts.volume_db ?? -6,
      muted: opts.muted || false,
      swell_amount: opts.swell_amount || 0,
      swell_period: opts.swell_period_sec || 20,
      startSec: opts.start_sec || 0,
      endSec: opts.end_sec || 0,
      repeatEvery: opts.repeat_every_sec || 0,
      _soloed: false,
    };

    this._applyGain(layer);
    pan.pan.value = opts.pan || 0;
    this._applyReverbMix(layer, opts.reverb_amount || 0);
    this.layers[name] = layer;

    console.log(`[LiveMixer] addLayer: "${name}" buffer=${audioBuf.duration.toFixed(1)}s`);
    if (this.playing) this._startSource(layer);
  }

  // ORIGINAL _applyGain — ONLY handles volume + mute, nothing else
  _applyGain(layer) {
    layer.gain.gain.setValueAtTime(
      layer.muted ? 0 : this._dbToLinear(layer.volume_db),
      this.ctx.currentTime
    );
  }

  _applyReverbMix(layer, amount) {
    layer.dryGain.gain.setValueAtTime(1 - amount * 0.4, this.ctx.currentTime);
    layer.wetGain.gain.setValueAtTime(amount, this.ctx.currentTime);
  }

  _startSource(layer, startTime) {
    if (layer.source) {
      try { layer.source.stop(); } catch (_) {}
    }
    const src = this.ctx.createBufferSource();
    src.buffer = layer.buffer;
    src.loop = true;
    src.connect(layer.gain);

    const when = startTime ?? this.ctx.currentTime;
    const elapsed = when - this.startedAt;
    const offset = elapsed > 0 ? elapsed % layer.buffer.duration : 0;
    src.start(when, offset);
    layer.source = src;

    this._applySwell(layer);
  }

  _applySwell(layer) {
    if (layer.swellLFO) {
      try { layer.swellLFO.stop(); } catch (_) {}
      layer.swellLFO = null;
    }
    if (layer.swellLFOGain) {
      layer.swellLFOGain.disconnect();
      layer.swellLFOGain = null;
    }

    if (layer.swell_amount <= 0.01) {
      layer.swellGain.gain.value = 1;
      return;
    }

    const lfo = this.ctx.createOscillator();
    const lfoGain = this.ctx.createGain();
    lfo.type = "sine";
    lfo.frequency.value = 1 / Math.max(4, layer.swell_period);

    const depth = layer.swell_amount * 0.5;
    layer.swellGain.gain.value = 1 - depth;
    lfoGain.gain.value = depth;

    lfo.connect(lfoGain);
    lfoGain.connect(layer.swellGain.gain);
    lfo.start();

    layer.swellLFO = lfo;
    layer.swellLFOGain = lfoGain;
  }

  // ── Instant parameter setters ───────────────────

  setVolume(name, db) {
    const l = this.layers[name];
    if (!l) return;
    l.volume_db = db;
    this._applyGain(l);
  }

  setPan(name, value) {
    const l = this.layers[name];
    if (!l) return;
    l.pan.pan.setValueAtTime(Math.max(-1, Math.min(1, value)), this.ctx.currentTime);
  }

  setLowPass(name, hz) {
    const l = this.layers[name];
    if (!l) return;
    l.filter.frequency.setValueAtTime(
      Math.max(200, Math.min(20000, hz)),
      this.ctx.currentTime
    );
  }

  setReverb(name, amount) {
    const l = this.layers[name];
    if (!l) return;
    this._applyReverbMix(l, Math.max(0, Math.min(1, amount)));
  }

  setSwell(name, amount, periodSec) {
    const l = this.layers[name];
    if (!l) return;
    l.swell_amount = amount;
    l.swell_period = periodSec || 20;
    this._applySwell(l);
  }

  setMute(name, muted) {
    const l = this.layers[name];
    if (!l) return;
    l.muted = muted;
    this._applyGain(l);
  }

  // ── Solo (uses controlGain, not gain) ─────────────

  solo(name) {
    const target = this.layers[name];
    if (!target) return;
    target._soloed = !target._soloed;

    const anySoloed = Object.values(this.layers).some(l => l._soloed);
    for (const l of Object.values(this.layers)) {
      const shouldMute = anySoloed && !l._soloed;
      l.controlGain.gain.setValueAtTime(shouldMute ? 0 : 1, this.ctx.currentTime);
    }
  }

  isSoloed(name) {
    const l = this.layers[name];
    return l ? !!l._soloed : false;
  }

  clearSolo() {
    for (const l of Object.values(this.layers)) {
      l._soloed = false;
      l.controlGain.gain.setValueAtTime(1, this.ctx.currentTime);
    }
  }

  // ── Layer timing (uses controlGain, not gain) ─────

  setTiming(name, startSec, endSec, repeatEvery) {
    const l = this.layers[name];
    if (!l) return;
    l.startSec = startSec;
    l.endSec = endSec;
    if (repeatEvery !== undefined) l.repeatEvery = repeatEvery;
  }

  // ── Alternate pairs with crossfade ─────────────

  setAlternate(nameA, nameB, cycleSec, xfadeSec = 8) {
    this.clearAlternate(nameA);
    this.clearAlternate(nameB);
    this._alternates.push({ a: nameA, b: nameB, cycle: cycleSec, xfade: xfadeSec });
    const la = this.layers[nameA];
    const lb = this.layers[nameB];
    if (la) { la.startSec = 0; la.endSec = 0; la.repeatEvery = 0; la._altPair = nameB; }
    if (lb) { lb.startSec = 0; lb.endSec = 0; lb.repeatEvery = 0; lb._altPair = nameA; }
    console.log(`[LiveMixer] alternate: "${nameA}" <-> "${nameB}" cycle=${cycleSec}s xfade=${xfadeSec}s`);
  }

  clearAlternate(name) {
    this._alternates = this._alternates.filter(a => a.a !== name && a.b !== name);
    const l = this.layers[name];
    if (l) delete l._altPair;
  }

  getAlternateInfo(name) {
    return this._alternates.find(a => a.a === name || a.b === name) || null;
  }

  _updateTimingGains() {
    const t = this.currentTime;
    const FADE = 3.0;
    const anySoloed = Object.values(this.layers).some(l => l._soloed);

    // Handle alternate pairs first
    const altHandled = new Set();
    for (const alt of this._alternates) {
      const la = this.layers[alt.a];
      const lb = this.layers[alt.b];
      if (!la && !lb) continue;

      const { gainA, gainB } = this._alternateCrossfade(t, alt.cycle, alt.xfade);

      if (la) {
        const soloMuted = anySoloed && !la._soloed;
        la.controlGain.gain.setValueAtTime(soloMuted ? 0 : gainA, this.ctx.currentTime);
        altHandled.add(alt.a);
      }
      if (lb) {
        const soloMuted = anySoloed && !lb._soloed;
        lb.controlGain.gain.setValueAtTime(soloMuted ? 0 : gainB, this.ctx.currentTime);
        altHandled.add(alt.b);
      }
    }

    // Handle non-alternate layers with window timing
    for (const l of Object.values(this.layers)) {
      if (altHandled.has(l.name)) continue;

      const s = l.startSec || 0;
      const e = l.endSec || 0;
      const repeat = l.repeatEvery || 0;

      if (s === 0 && e === 0) continue;

      const windowLen = (e > 0 ? e : this.duration) - s;
      let tg = 0;

      if (repeat > 0 && windowLen > 0) {
        const effectiveRepeat = Math.max(repeat, windowLen);
        let ws = s;
        while (ws < this.duration) {
          const we = Math.min(ws + windowLen, this.duration);
          tg = this._windowGain(t, ws, we, FADE);
          if (tg > 0) break;
          ws += effectiveRepeat;
        }
      } else {
        const end = e > 0 ? e : this.duration;
        tg = this._windowGain(t, s, end, FADE);
      }

      const soloMuted = anySoloed && !l._soloed;
      const finalGain = soloMuted ? 0 : tg;
      l.controlGain.gain.setValueAtTime(finalGain, this.ctx.currentTime);
    }
  }

  _alternateCrossfade(t, cycleSec, xfadeSec) {
    const period = cycleSec * 2;
    const phase = ((t % period) + period) % period;
    const hold = cycleSec - xfadeSec;

    let gainA, gainB;
    if (phase < hold) {
      gainA = 1; gainB = 0;
    } else if (phase < cycleSec) {
      const frac = (phase - hold) / xfadeSec;
      gainA = Math.cos(frac * Math.PI * 0.5);
      gainB = Math.sin(frac * Math.PI * 0.5);
    } else if (phase < cycleSec + hold) {
      gainA = 0; gainB = 1;
    } else {
      const frac = (phase - cycleSec - hold) / xfadeSec;
      gainA = Math.sin(frac * Math.PI * 0.5);
      gainB = Math.cos(frac * Math.PI * 0.5);
    }
    return { gainA, gainB };
  }

  _windowGain(t, start, end, fade) {
    if (t < start) return 0;
    if (t >= end) return 0;
    if (t < start + fade) return (t - start) / fade;
    if (t > end - fade) return (end - t) / fade;
    return 1;
  }

  // ── Layer management ────────────────────────────

  async reloadLayer(name, url) {
    const l = this.layers[name];
    if (!l) return;
    const resp = await fetch(url);
    if (!resp.ok) {
      throw new Error(`Layer "${name}" reload failed: HTTP ${resp.status}`);
    }
    const ab = await resp.arrayBuffer();
    l.buffer = await this.ctx.decodeAudioData(ab);
    console.log(`[LiveMixer] reloadLayer: "${name}" buffer=${l.buffer.duration.toFixed(1)}s`);
    if (this.playing) this._startSource(l);
  }

  removeLayer(name) {
    const l = this.layers[name];
    if (!l) return;
    if (l.source) try { l.source.stop(); } catch (_) {}
    if (l.swellLFO) try { l.swellLFO.stop(); } catch (_) {}
    l.gain.disconnect();
    l.controlGain.disconnect();
    l.dryGain.disconnect();
    l.wetGain.disconnect();
    delete this.layers[name];
  }

  hasLayer(name) {
    return name in this.layers;
  }

  // ── Transport ───────────────────────────────────

  async play() {
    if (this.playing) return;
    // iOS: the AudioContext starts "suspended" and only resumes from a user
    // gesture. We MUST await it — otherwise currentTime stays frozen, the
    // sources get scheduled into the past, and nothing sounds while the JS
    // timer still advances (looks like it's playing, but silent).
    if (this.ctx.state === "suspended") {
      try { await this.ctx.resume(); } catch (e) { console.warn("[LiveMixer] resume failed", e); }
    }

    const vol = this._masterVolume !== undefined ? this._masterVolume : 1;

    // Anchor everything to a single future timestamp so the gain ramp and
    // every layer's source.start() are sample-aligned. The prepped buffer's
    // sample 0 is non-zero (~-20 dBFS), so a hard jump from silence to that
    // value pops in the speakers. We schedule the ramp from 0 → target over
    // 50 ms starting exactly when the sources begin emitting samples.
    // 5-second fade-in matching the export. Runs on every play press
    // (one-shot per press; loop wraps don't fire play()). On internal loop
    // wraps the timer schedules its own fade-out → fade-in pair so the
    // preview matches what the exported file will sound like.
    const startTime = this.ctx.currentTime + 0.020;
    const fadeInSec = this._fadeInSec || 5.0;
    this.masterGain.gain.cancelScheduledValues(startTime);
    this.masterGain.gain.setValueAtTime(0, startTime);
    this.masterGain.gain.linearRampToValueAtTime(vol, startTime + fadeInSec);
    this._suppressMasterFadeUntil = startTime + fadeInSec + 0.050;
    this._fadeOutScheduled = false;
    console.log(`[LiveMixer] play() fade-in ${fadeInSec}s, fade-out ${this._fadeOutSec || 0}s [v8]`);

    this.startedAt = startTime - this.pausedAt;
    this.playing = true;

    for (const l of Object.values(this.layers)) {
      this._startSource(l, startTime);
    }
    this._startTimer();
    this._updateAudioStatus();
  }

  pause() {
    if (!this.playing) return;
    this.pausedAt = this.ctx.currentTime - this.startedAt;
    this.playing = false;
    this._fadeOutScheduled = false;

    for (const l of Object.values(this.layers)) {
      if (l.source) try { l.source.stop(); } catch (_) {}
      if (l.swellLFO) try { l.swellLFO.stop(); } catch (_) {}
    }
    this._stopTimer();
  }

  togglePlayPause() {
    if (this.playing) this.pause();
    else this.play();
  }

  seek(seconds) {
    const was = this.playing;
    if (was) this.pause();
    this.pausedAt = Math.max(0, Math.min(seconds, this.duration));
    if (was) this.play();
    if (this.onTimeUpdate) this.onTimeUpdate(this.pausedAt, this.duration);
  }

  get currentTime() {
    if (this.playing) {
      const t = this.ctx.currentTime - this.startedAt;
      return Math.min(t, this.duration);
    }
    return this.pausedAt;
  }

  setMasterFades(fadeInSec, fadeOutSec) {
    this._fadeInSec = fadeInSec || 0;
    this._fadeOutSec = fadeOutSec || 0;
  }

  _applyMasterFade(t) {
    // During the play() click-suppress ramp, do NOT touch masterGain.gain.
    // Calling setValueAtTime() here would terminate the linearRampToValueAtTime
    // scheduled in play() and snap the gain to vol — producing the very click
    // we're trying to prevent.
    if (this._suppressMasterFadeUntil && this.ctx.currentTime < this._suppressMasterFadeUntil) {
      return;
    }

    // Schedule a smooth fade-out before the playhead reaches the displayed
    // duration. We don't repeatedly call setValueAtTime each tick — instead we
    // queue one Web Audio ramp the first time we cross the threshold, then
    // leave the AudioParam alone until wrap. This makes the preview match the
    // exported file's fade-out shape exactly.
    const fadeOut = this._fadeOutSec || 0;
    if (fadeOut > 0 && !this._fadeOutScheduled && t > this.duration - fadeOut) {
      const remaining = this.duration - t;
      if (remaining > 0) {
        const vol = this._masterVolume !== undefined ? this._masterVolume : 1;
        const now = this.ctx.currentTime;
        this.masterGain.gain.cancelScheduledValues(now);
        this.masterGain.gain.setValueAtTime(vol, now);
        this.masterGain.gain.linearRampToValueAtTime(0, now + remaining);
        this._fadeOutScheduled = true;
        console.log(`[LiveMixer] fade-out scheduled: ${remaining.toFixed(2)}s → 0`);
      }
    }
  }

  _startTimer() {
    this._stopTimer();
    this._timer = setInterval(() => {
      const t = this.currentTime;
      this._applyMasterFade(t);
      this._updateTimingGains();
      if (this.onTimeUpdate) this.onTimeUpdate(t, this.duration);
      if (t >= this.duration) {
        if (this._looping !== false) {
          // Web Audio's src.loop=true is already looping each buffer natively
          // at its own length. We just shift the timeline so the playhead wraps
          // visually without disturbing the running audio sources.
          this._hasLooped = true;
          this.startedAt += this.duration;

          // Schedule a fresh fade-in on every wrap so the preview keeps showing
          // what the exported file's intro sounds like, without ever cutting
          // the running buffer (still seamlessly looping underneath).
          const fadeIn = this._fadeInSec || 0;
          if (fadeIn > 0) {
            const vol = this._masterVolume !== undefined ? this._masterVolume : 1;
            const now = this.ctx.currentTime;
            this.masterGain.gain.cancelScheduledValues(now);
            this.masterGain.gain.setValueAtTime(0, now);
            this.masterGain.gain.linearRampToValueAtTime(vol, now + fadeIn);
            this._suppressMasterFadeUntil = now + fadeIn + 0.050;
            console.log(`[LiveMixer] wrap → fade-in scheduled (${fadeIn}s)`);
          }
          this._fadeOutScheduled = false;
        } else {
          console.log(`[LiveMixer] end: t=${t.toFixed(1)}s, looping disabled — stopping`);
          this.pause();
          this.pausedAt = 0;
          if (this.onTimeUpdate) this.onTimeUpdate(0, this.duration);
        }
      }
    }, 250);
  }

  _stopTimer() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  setMasterVolume(value) {
    this._masterVolume = Math.max(0, Math.min(1, value));
    if (this.masterGain) {
      this.masterGain.gain.setValueAtTime(this._masterVolume, this.ctx.currentTime);
    }
  }

  toggleLoop() {
    this._looping = !this._looping;
    return this._looping;
  }

  get looping() {
    return this._looping !== false;
  }

  destroy() {
    this.pause();
    for (const name of Object.keys(this.layers)) {
      this.removeLayer(name);
    }
    if (this.ctx) this.ctx.close();
    this.ctx = null;
  }
}
