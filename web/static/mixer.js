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
    if (!resp.ok) {
      throw new Error(`Layer "${name}" audio fetch failed: HTTP ${resp.status}`);
    }
    const ab = await resp.arrayBuffer();
    if (ab.byteLength < 100) {
      throw new Error(`Layer "${name}" audio is empty or too small (${ab.byteLength} bytes)`);
    }
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

  setMasterFades(fadeInSec, fadeOutSec) {
    this._fadeInSec = fadeInSec || 0;
    this._fadeOutSec = fadeOutSec || 0;
  }

  _applyMasterFade(t) {
    const fadeIn = this._fadeInSec || 0;
    const fadeOut = this._fadeOutSec || 0;
    let fadeGain = 1;
    if (fadeIn > 0 && t < fadeIn && !this._hasLooped) {
      fadeGain = t / fadeIn;
    }
    if (!this._looping && fadeOut > 0 && t > this.duration - fadeOut) {
      fadeGain = Math.min(fadeGain, (this.duration - t) / fadeOut);
    }
    fadeGain = Math.max(0, Math.min(1, fadeGain));
    const vol = this._masterVolume !== undefined ? this._masterVolume : 1;
    this.masterGain.gain.setValueAtTime(fadeGain * vol, this.ctx.currentTime);
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
          console.log(`[LiveMixer] loop: t=${t.toFixed(1)}s >= duration=${this.duration}s, seeking to 0`);
          this._hasLooped = true;
          this.seek(0);
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
