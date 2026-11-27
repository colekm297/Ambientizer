// Sing UI: count-in, quiet chords, record, turn the take into notes, preview Close and Polished, Use.
// His voice is analysed and thrown away. Only notes are kept (S.tune, scale steps and beats).
import { buildGraph, playEvent, scaleMidi, refrainCap, ROLE_NAMES } from './grow.js';
import { buildTunes, tuneEvents } from './sing.js';

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const TIPS = 'Headphones keep the chords out of the mic.';

export function initSing(d) {
  const { $, getS } = d;
  const panel = $('#singPanel');
  let busy = false, ctx = null, res = null, which = 'polished', pv = null, singTimer = null, abort = null;

  const hide = () => { panel.hidden = true; panel.innerHTML = ''; };
  const closeCtx = () => { stopPreview(); if (ctx) { const c = ctx; ctx = null; c.close().catch(() => {}); } };
  const say = d.say;

  // ------------------------------------------------------------ sound
  const chordEvents = (S, t, dur, vel) => {
    const evs = [];
    const cel = (m) => { while (m > 55) m -= 12; while (m < 38) m += 12; return m; };
    [0, 2, 4].forEach((i, k) => {
      let m = scaleMidi(i, S.key, S.mode) - 12; while (m > 58) m -= 12; while (m < 43) m += 12;
      evs.push({ role: 'bed', midi: m, vel: vel * 0.9, att: 2.2, rel: 2.5, dur, pan: (k - 1) * 0.3, det: 0, z: 0, when: t + k * 0.35 });
    });
    evs.push({ role: 'low', midi: cel(scaleMidi(0, S.key, S.mode)), vel: vel * 1.2, att: 1.5, rel: 2.5, dur, pan: 0, det: 0, z: 0, when: t });
    return evs;
  };
  const click = (c, dest, when, accent) => {
    const o = c.createOscillator(), g = c.createGain();
    o.type = 'sine'; o.frequency.value = accent ? 1760 : 1320;
    g.gain.setValueAtTime(0, when); g.gain.linearRampToValueAtTime(accent ? 0.16 : 0.09, when + 0.004); g.gain.exponentialRampToValueAtTime(0.0008, when + 0.05);
    o.connect(g); g.connect(dest); o.start(when); o.stop(when + 0.08);
  };
  const tonicCue = (c, dest, S, when, dur) => { // the key's tonic, soft, an octave pair so any voice finds it
    for (const oct of [-1, 0]) {
      const o = c.createOscillator(), g = c.createGain();
      o.type = 'sine'; o.frequency.value = 440 * Math.pow(2, (scaleMidi(0, S.key, S.mode) + 12 * oct - 69) / 12);
      g.gain.setValueAtTime(0, when); g.gain.linearRampToValueAtTime(0.1, when + 0.05); g.gain.setValueAtTime(0.1, when + dur - 0.15); g.gain.linearRampToValueAtTime(0, when + dur);
      o.connect(g); g.connect(dest); o.start(when); o.stop(when + dur + 0.05);
    }
  };

  function stopPreview() {
    if (!pv) return;
    const { g, handles, timer } = pv; pv = null; clearTimeout(timer);
    if (ctx) { const now = ctx.currentTime; for (const h of handles) { try { h.env.gain.cancelScheduledValues(now); h.env.gain.setTargetAtTime(0, now, 0.06); h.src.stop(now + 0.6); } catch {} } setTimeout(() => { try { g.master.disconnect(); } catch {} }, 900); }
    const b = panel.querySelector('[data-sing=play]'); if (b) b.querySelector('span').textContent = 'Play';
  }
  async function preview(tune) {
    if (!ctx) return;
    stopPreview();
    try { await ctx.resume(); } catch {}
    const S = getS(), g = buildGraph(ctx, S), handles = [];
    const beat = 60 / S.bpm, t0 = ctx.currentTime + 0.2;
    const evs = tuneEvents(tune, S), end = Math.max(...evs.map((e) => e.t + e.dur)) + 0.3;
    for (const e of chordEvents(S, t0, end + 2.5, 0.3)) { const h = playEvent(ctx, g, d.kit, e, e.when); if (h) handles.push(h); }
    evs.forEach((e, k) => {
      const h = playEvent(ctx, g, d.kit, { role: 'voice', midi: e.midi, vel: 0.85, att: 0.22, rel: e.last ? 2.6 : 1.6, dur: e.last ? e.dur + 0.6 : e.dur, pan: 0, det: 0, z: 0 }, t0 + 0.3 + e.t);
      if (h) handles.push(h);
    });
    pv = { g, handles, timer: setTimeout(() => stopPreview(), (0.3 + end + 3.5) * 1000) };
    const b = panel.querySelector('[data-sing=play]'); if (b) b.querySelector('span').textContent = 'Stop';
  }

  // ------------------------------------------------------------ panel
  function rollSvg(tune, ghost) {
    const S = getS();
    const all = tune.notes.concat(ghost ? ghost.notes : []);
    const lo = Math.min(...all.map((n) => n.i)) - 1, hi = Math.max(...all.map((n) => n.i)) + 1;
    const total = Math.max(8, tune.total, ghost ? ghost.total : 0);
    const W = 300, H = 84, x = (b) => 4 + (b / total) * (W - 8), y = (i) => H - 6 - ((i - lo) / Math.max(4, hi - lo)) * (H - 12);
    const bar = (n, cls) => `<rect class="${cls}" x="${x(n.b).toFixed(1)}" y="${(y(n.i) - 4).toFixed(1)}" width="${Math.max(3, x(n.b + n.l * 0.94) - x(n.b)).toFixed(1)}" height="8" rx="4"/>`;
    let lines = ''; for (let b = 0; b <= total; b += 4) lines += `<line x1="${x(b).toFixed(1)}" x2="${x(b).toFixed(1)}" y1="2" y2="${H - 2}"/>`;
    return `<svg class="gr-roll" viewBox="0 0 ${W} ${H}" role="img" aria-label="Notes of the tune"><g class="gr-roll__grid">${lines}</g>${ghost ? `<g class="gr-roll__ghost">${ghost.notes.map((n) => bar(n, 'g')).join('')}</g>` : ''}<g class="gr-roll__notes">${tune.notes.map((n) => bar(n, 'n')).join('')}</g></svg>`;
  }
  function paintResult() {
    const tune = res.tunes[which], other = res.tunes[which === 'polished' ? 'close' : 'polished'];
    const on = (w) => (which === w ? 'true' : 'false');
    panel.innerHTML = `
      <div class="gr-sing__head"><span class="ds-label">Sing</span><span class="ds-meta">${tune.notes.length} notes, ${Math.round(tune.total)} beats</span></div>
      ${rollSvg(tune, other)}
      <div class="ds-seg" role="radiogroup" aria-label="Version" id="singSeg">
        <button type="button" class="ds-seg__opt" role="radio" aria-checked="${on('close')}" data-value="close" title="Your notes, lightly cleaned">Close</button>
        <button type="button" class="ds-seg__opt" role="radio" aria-checked="${on('polished')}" data-value="polished" title="Stronger shaping, same contour">Polished</button>
      </div>
      <div class="gr-sing__acts">
        <button type="button" class="ds-btn ds-btn--sm ds-btn--raised" data-sing="play"><svg class="ds-icon ds-icon--sm" aria-hidden="true"><use href="ds/icons/sprite.svg#i-play"></use></svg><span>Play</span></button>
        <button type="button" class="ds-btn ds-btn--sm ds-btn--primary" data-sing="use">Use</button>
        <button type="button" class="ds-btn ds-btn--sm ds-btn--ghost" data-sing="discard">Discard</button>
      </div>`;
    panel.hidden = false;
    const seg = panel.querySelector('#singSeg');
    if (window.DS && DS.seg) DS.seg(seg);
    seg.addEventListener('seg-change', (e) => { const w = e.detail.value; if (!res.tunes[w] || w === which) return; which = w; paintResult(); preview(res.tunes[which]); });
  }
  panel.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-sing]'); if (!b) return;
    const a = b.dataset.sing;
    if (a === 'stop') abort && abort();
    else if (a === 'play') { if (pv) stopPreview(); else if (res) preview(res.tunes[which]); }
    else if (a === 'use') { const t = Object.assign({}, res.tunes[which]); closeCtx(); hide(); d.useTune(t); res = null; say(`Your tune is in the refrains (${t.name}).`); }
    else if (a === 'discard') { closeCtx(); hide(); res = null; }
  });

  // ------------------------------------------------------------ the take
  async function start() {
    if (busy) return;
    busy = true;
    let stream = null, mr = null;
    const S = Object.assign({}, getS());
    try {
      if (!navigator.mediaDevices || typeof MediaRecorder === 'undefined') throw new DOMException('no recorder', 'NotFoundError');
      closeCtx(); res = null;
      if (d.player.state === 'playing') await d.player.pause(); // the mic would hear the piece
      d.session('play-and-record');
      ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000 });
      const c = ctx; c.resume().catch(() => {});
      panel.hidden = false;
      panel.innerHTML = `<div class="gr-sing__head"><span class="ds-label">Sing</span><span class="ds-meta" id="singStatus">Allow the microphone</span></div>`;
      if (!d.kit.ready) await d.ensureKit();
      // echoCancellation stays ON here: the chords come out of the speaker while he sings
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: false } });
      await d.ensureKit();
      mr = new MediaRecorder(stream); const chunks = [];
      mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      const started = new Promise((r) => (mr.onstart = r)), stopped = new Promise((r) => (mr.onstop = r));
      mr.start(); await started;
      const recStart = c.currentTime;
      const beat = 60 / S.bpm, bar = beat * 4;
      const bars = clamp(Math.ceil(refrainCap(S.bpm) / 4), 3, 8);
      const t0 = c.currentTime + 0.3, tuneStart = t0 + 4 * beat, tuneEnd = tuneStart + bars * bar;
      const g = buildGraph(c, S); g.master.gain.value = 0.3;
      const dest = c.createGain(); dest.gain.value = 1; dest.connect(c.destination);
      for (let k = 0; k < 4; k++) click(c, dest, t0 + k * beat, k === 0);
      tonicCue(c, dest, S, t0, 4 * beat * 0.9);
      for (const e of chordEvents(S, tuneStart - 0.2, bars * bar + 3, 0.34)) playEvent(c, g, d.kit, e, e.when);
      panel.innerHTML = `
        <div class="gr-sing__head"><span class="ds-label">Sing</span><span class="ds-meta" id="singStatus">Count in</span></div>
        <span class="ds-meter gr-meter" id="singMeter" data-value="0" data-label=" "></span>
        <div class="ds-meta">${TIPS}</div>
        <div class="gr-sing__acts"><button type="button" class="ds-btn ds-btn--sm ds-btn--raised" data-sing="stop">Stop</button></div>`;
      const meter = $('#singMeter'), status = $('#singStatus');
      let stopping = false;
      const end = () => { if (stopping) return; stopping = true; clearInterval(singTimer); if (mr.state !== 'inactive') mr.stop(); };
      abort = end;
      singTimer = setInterval(() => {
        const now = c.currentTime;
        if (now < tuneStart) status.textContent = `Count in ${clamp(Math.ceil((tuneStart - now) / beat), 1, 4)}`;
        else { status.textContent = `Sing ${Math.max(0, Math.ceil(tuneEnd - now))}`; if (window.DS) DS.meter(meter, clamp((now - tuneStart) / (tuneEnd - tuneStart), 0, 1)); }
        if (now > tuneEnd + 0.8) end();
      }, 100);
      await stopped; clearInterval(singTimer);
      const sungFor = c.currentTime - tuneStart;
      stream.getTracks().forEach((t) => t.stop()); stream = null;
      d.session('playback');
      g.master.disconnect(); try { dest.disconnect(); } catch {}
      panel.innerHTML = `<div class="gr-sing__head"><span class="ds-label">Sing</span><span class="ds-meta">Working on your tune</span></div>`;
      await new Promise((r) => setTimeout(r, 30));
      if (sungFor < 1) { say('That was too short. Sing a few notes after the count.'); closeCtx(); hide(); return; }
      const ab = await new Blob(chunks, { type: mr.mimeType }).arrayBuffer();
      const { mono, sr } = await d.decode(ab, 45);
      const data = mono.subarray(Math.floor(Math.max(0, tuneStart - recStart) * sr));
      const out = buildTunes(data, sr, S, { cap: refrainCap(S.bpm) });
      if (out.error) { say(out.error); closeCtx(); hide(); return; }
      res = out; res.S = S; which = 'polished';
      paintResult();
      preview(res.tunes[which]).catch(() => {});
    } catch (e) {
      console.warn(e);
      const n = e && e.name;
      say(n === 'NotAllowedError' ? 'Microphone blocked. Allow it in the browser to sing.' : n === 'EncodingError' ? 'That recording could not be read.' : mr ? 'Singing failed.' : 'No microphone available.');
      closeCtx(); hide();
    } finally {
      clearInterval(singTimer); abort = null; busy = false;
      if (stream) stream.getTracks().forEach((t) => t.stop());
      d.session('playback');
    }
  }
  return { start, stop: () => abort && abort(), busy: () => busy, test: { result: () => res, which: () => which, busy: () => busy } };
}
