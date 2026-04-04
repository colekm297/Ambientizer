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
  }

  async init(durationSec) {
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    this.duration = durationSec;
    this.masterGain = this.ctx.createGain();
    this.masterGain.connect(this.ctx.destination);
    this._reverbImpulse = this._buildReverbIR(2.5, 3.0);
    console.log(`[LiveMixer] init: duration=${durationSec}s (${(durationSec/60).toFixed(1)} min)`);
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
    const ab = await resp.arrayBuffer();
    const audioBuf = await this.ctx.decodeAudioData(ab);

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

  _startSource(layer) {
    if (layer.source) {
      try { layer.source.stop(); } catch (_) {}
    }
    const src = this.ctx.createBufferSource();
    src.buffer = layer.buffer;
    src.loop = true;
    src.connect(layer.gain);

    const elapsed = this.ctx.currentTime - this.startedAt;
    const offset = elapsed > 0 ? elapsed % layer.buffer.duration : 0;
    src.start(0, offset);
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

  setTiming(name, startSec, endSec) {
    const l = this.layers[name];
    if (!l) return;
    l.startSec = startSec;
    l.endSec = endSec;
  }

  _updateTimingGains() {
    const t = this.currentTime;
    const FADE = 2.0;
    const anySoloed = Object.values(this.layers).some(l => l._soloed);

    for (const l of Object.values(this.layers)) {
      const s = l.startSec || 0;
      const e = l.endSec || 0;

      // No timing set — skip entirely, don't touch controlGain
      if (s === 0 && e === 0) continue;

      const end = e > 0 ? e : this.duration;
      let tg = 1;
      if (t < s) {
        tg = 0;
      } else if (t < s + FADE) {
        tg = (t - s) / FADE;
      } else if (t > end - FADE && t < end) {
        tg = (end - t) / FADE;
      } else if (t >= end) {
        tg = 0;
      }
      tg = Math.max(0, Math.min(1, tg));

      // Combine with solo state
      const soloMuted = anySoloed && !l._soloed;
      const finalGain = soloMuted ? 0 : tg;
      l.controlGain.gain.setValueAtTime(finalGain, this.ctx.currentTime);
    }
  }

  // ── Layer management ────────────────────────────

  async reloadLayer(name, url) {
    const l = this.layers[name];
    if (!l) return;
    const resp = await fetch(url);
    const ab = await resp.arrayBuffer();
    l.buffer = await this.ctx.decodeAudioData(ab);
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

  play() {
    if (this.playing) return;
    if (this.ctx.state === "suspended") this.ctx.resume();

    this.startedAt = this.ctx.currentTime - this.pausedAt;
    this.playing = true;

    for (const l of Object.values(this.layers)) {
      this._startSource(l);
    }
    this._startTimer();
  }

  pause() {
    if (!this.playing) return;
    this.pausedAt = this.ctx.currentTime - this.startedAt;
    this.playing = false;

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

  _startTimer() {
    this._stopTimer();
    this._timer = setInterval(() => {
      const t = this.currentTime;
      this._updateTimingGains();
      if (this.onTimeUpdate) this.onTimeUpdate(t, this.duration);
      if (t >= this.duration) {
        console.log(`[LiveMixer] loop: t=${t.toFixed(1)}s >= duration=${this.duration}s, seeking to 0`);
        this.seek(0);
      }
    }, 250);
  }

  _stopTimer() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
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
