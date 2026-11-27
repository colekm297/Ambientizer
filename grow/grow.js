// Grow engine: plan (pure, seeded), sampler, live player, offline render, pitch detection.
// The plan is a list of events. The same list feeds live playback and the offline render.
// Nothing at import time touches the browser, so node can import this file for the unit check.

// ---------------------------------------------------------------- utils
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const mod = (n, m) => ((n % m) + m) % m;

export function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function hashStr(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
const sub = (seed, name) => mulberry32((seed ^ hashStr(name)) >>> 0);
const rr = (r, a, b) => a + (b - a) * r();
const pick = (r, arr) => arr[Math.floor(r() * arr.length)];
const dbToLin = (db) => Math.pow(10, db / 20);

// ---------------------------------------------------------------- music data
export const MODES = {
  aeolian: [0, 2, 3, 5, 7, 8, 10],
  dorian: [0, 2, 3, 5, 7, 9, 10],
  lydian: [0, 2, 4, 6, 7, 9, 11],
  ionian: [0, 2, 4, 5, 7, 9, 11],
};
export const KEYS = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B'];
export const WORLDS = {
  'Folding City': { key: 4, mode: 'aeolian', bpm: 56 },
  'Quiet Shore': { key: 2, mode: 'lydian', bpm: 50 },
  'Desert Dusk': { key: 11, mode: 'dorian', bpm: 46 },
};
// Chord roots (scale degrees, 0 based) that may follow each other, per mode.
const GRAPH = {
  aeolian: { 0: [5, 3, 6, 2], 5: [6, 2, 3, 0], 2: [6, 5, 0, 3], 6: [0, 5, 2], 3: [0, 5, 6], 4: [0, 5] },
  dorian: { 0: [3, 6, 2, 4], 3: [0, 6, 4], 6: [0, 3, 2], 2: [3, 6, 0], 4: [0, 3], 1: [0, 3] },
  lydian: { 0: [1, 4, 5], 1: [0, 4, 5], 4: [0, 1, 5], 5: [0, 1, 4], 2: [5, 0] },
  ionian: { 0: [3, 5, 4], 3: [0, 4, 5], 4: [0, 5, 3], 5: [3, 0, 1], 1: [4, 0, 3] },
};
const CONTRAST = { aeolian: [5, 3, 2, 6], dorian: [3, 6, 4, 2], lydian: [1, 4, 5, 2], ionian: [3, 5, 4, 1] };

export function defaultSettings(world = 'Folding City') {
  const w = WORLDS[world];
  return {
    world, key: w.key, mode: w.mode, bpm: w.bpm,
    refrainEvery: 150, density: 0.5, space: 0.5, brightness: 0.5,
    length: 600, seed: 20261124,
  };
}
function normalize(S) {
  const d = defaultSettings(S.world in WORLDS ? S.world : 'Folding City');
  const o = Object.assign({}, d, S);
  o.bpm = clamp(+o.bpm, 36, 84);
  o.refrainEvery = clamp(+o.refrainEvery, 90, 240);
  o.density = clamp(+o.density, 0, 1);
  o.space = clamp(+o.space, 0, 1);
  o.brightness = clamp(+o.brightness, 0, 1);
  o.length = +o.length;
  o.seed = (+o.seed) >>> 0;
  return o;
}

// Arc of the whole piece: intro, build, peak at 2/3, settling end. f is 0..1.
const ARC = [[0, 0.16], [0.1, 0.34], [0.3, 0.58], [0.667, 1], [0.85, 0.52], [1, 0.14]];
export function arcAt(f) {
  f = clamp(f, 0, 1);
  for (let i = 1; i < ARC.length; i++) {
    if (f <= ARC[i][0]) {
      const [x0, y0] = ARC[i - 1], [x1, y1] = ARC[i];
      const u = (f - x0) / (x1 - x0);
      const s = (1 - Math.cos(Math.PI * u)) / 2;
      return y0 + (y1 - y0) * s;
    }
  }
  return ARC[ARC.length - 1][1];
}

// ---------------------------------------------------------------- the plan
export function plan(S0) {
  const S = normalize(S0);
  const seed = S.seed;
  const L = S.length;
  const beat = 60 / S.bpm, bar = beat * 4;
  const scale = MODES[S.mode];
  const pc0 = S.key;
  const T4 = 58 + mod(pc0 - 58, 12); // tonic midi in 58..69
  // scale index i (0 = tonic at T4) to midi
  const midiOf = (i, base = T4) => base + 12 * Math.floor(i / 7) + scale[mod(i, 7)];
  const chordPcs = (d) => [d, d + 2, d + 4].map((i) => mod(midiOf(i, pc0), 12));
  const tonesIn = (d, lo, hi) => {
    const pcs = chordPcs(d), o = [];
    for (let m = lo; m <= hi; m++) if (pcs.includes(m % 12)) o.push(m);
    return o;
  };
  const nearestPc = (pc, around, lo, hi) => {
    let best = null, bd = 1e9;
    for (let m = lo; m <= hi; m++) if (m % 12 === pc && Math.abs(m - around) < bd) { bd = Math.abs(m - around); best = m; }
    return best;
  };
  const snapBar = (t) => Math.max(0, Math.round(t / bar) * bar);
  const events = [];
  const push = (e) => { events.push(Object.assign({ pan: 0, det: 0, att: 0.05, rel: 1.5, tag: '', ref: -1 }, e)); };

  // ----- refrain schedule
  const rngS = sub(seed, 'sched');
  let cb = 8; for (let c = 8; c >= 2; c--) if (c * bar >= 15 && Math.abs(3 * c * bar - 53) <= Math.abs(3 * cb * bar - 53)) cb = c; // bars per refrain chord, refrain near 53 s
  const chordSpan = cb * bar;
  const rDur = 3 * chordSpan;
  const refrains = [];
  {
    const R = S.refrainEvery;
    const gap = () => Math.max(R * (1 + rr(rngS, -0.15, 0.15)), rDur + 15 + 12);
    const P = snapBar(0.62 * L);
    const starts = [P];
    const first = snapBar(rr(rngS, 78, 96));
    const nb = P - first > 20 ? Math.max(1, Math.ceil((P - first) / Math.max(R, 160))) : 0;
    if (nb > 0) {
      const g = (P - first) / nb;
      for (let j = 0; j < nb; j++) {
        const jit = (j === 0 ? 0 : rr(rngS, -0.05, 0.05) * g);
        starts.unshift(snapBar(first + j * g + jit));
      }
    }
    const availEnd = Math.floor((L - rDur - 24) / bar) * bar; // last refrain ends 24 s or more before the end
    const nf = availEnd - P > 30 ? Math.max(1, Math.ceil((availEnd - P) / Math.max(R, 160))) : 0;
    if (nf > 0) {
      const g = (availEnd - P) / nf;
      for (let j = 1; j <= nf; j++) starts.push(j === nf ? availEnd : snapBar(P + j * g + rr(rngS, -0.05, 0.05) * g));
    }
    starts.sort((a, b) => a - b);
    for (let k = 1; k < starts.length; k++) if (starts[k] - starts[k - 1] < rDur + 27) starts[k] = starts[k - 1] + rDur + 27;
    while (starts.length && starts[starts.length - 1] + rDur + 20 > L) starts.pop();
    const rngQ = sub(seed, 'quiet');
    starts.forEach((st, k) => {
      const nextStart = k + 1 < starts.length ? starts[k + 1] : L + 2;
      const quiet = Math.min(rr(rngQ, 10, 20), Math.max(10, nextStart - (st + rDur) - 10));
      const c = (st + rDur / 2) / L;
      refrains.push({ k, start: st, end: st + rDur, quiet, quietEnd: st + rDur + quiet,
        dur: rDur, intensity: 0.5 + 0.5 * arcAt(c), peak: false });
    });
    let bi = 0, bv = -1;
    refrains.forEach((r, i) => { const v = -Math.abs((r.start + rDur / 2) / L - 0.667); if (v > bv) { bv = v; bi = i; } });
    if (refrains.length) { refrains[bi].peak = true; refrains[bi].intensity = 1; }
  }
  const inRefrain = (t) => refrains.find((r) => t >= r.start && t < r.end);
  const inQuiet = (t) => refrains.find((r) => t >= r.end - 3 && t < r.quietEnd);
  const nextRefrainAfter = (t) => refrains.find((r) => r.start > t);
  const bloom = (t) => { // 0..1 around a refrain, smooth ramps
    let b = 0;
    for (const r of refrains) {
      if (t > r.start - 8 && t < r.end + 4) {
        const up = clamp((t - (r.start - 8)) / 10, 0, 1), dn = clamp((r.end + 4 - t) / 6, 0, 1);
        b = Math.max(b, Math.min(up, dn) * (0.6 + 0.4 * r.intensity));
      }
    }
    return b;
  };

  // ----- chord timeline
  const rngH = sub(seed, 'harmony');
  const chords = []; // {t0,t1,deg,refrain:-1|k}
  const nmin = Math.max(1, Math.ceil(16 / bar)), nmax = Math.max(nmin, Math.floor(40 / bar));
  let prevDeg = 0;
  const fillFree = (t0, t1) => {
    let rem = Math.round((t1 - t0) / bar), t = t0;
    let first = true;
    while (rem > 0) {
      let n = nmin + Math.floor(rngH() * (nmax - nmin + 1));
      if (rem - n < nmin) n = rem <= nmax ? rem : rem - nmin;
      n = Math.min(n, rem);
      let deg;
      if (first && t0 === 0) deg = 0;
      else { const opts = (GRAPH[S.mode][prevDeg] || [0]).filter((d) => d !== prevDeg); deg = pick(rngH, opts); }
      first = false;
      chords.push({ t0: t, t1: t + n * bar, deg, refrain: -1 });
      prevDeg = deg; t += n * bar; rem -= n;
    }
  };
  {
    let cur = 0;
    for (const r of refrains) {
      if (r.start > cur) fillFree(cur, r.start);
      cur = r.end;
      prevDeg = 0;
    }
    const endT = Math.ceil((L + 4) / bar) * bar;
    if (endT > cur) fillFree(cur, endT);
  }

  // ----- motif
  const rngM = sub(seed, 'motif');
  const motif = makeMotif(rngM, cb, beat);
  const motifMidiRange = (idx) => [midiOf(Math.min(...idx)), midiOf(Math.max(...idx))];
  const foldIdx = (idx) => {
    idx = idx.slice();
    for (let g = 0; g < 4; g++) {
      const [lo, hi] = motifMidiRange(idx);
      if (hi > 80) idx = idx.map((i) => i - 7); else if (lo < 55) idx = idx.map((i) => i + 7); else break;
    }
    return idx;
  };
  const fitScore = (deg, idx, beats) => {
    const set = [deg, deg + 2, deg + 4].map((i) => mod(i, 7));
    let s = 0; idx.forEach((i, k) => { if (set.includes(mod(i, 7))) s += beats[k]; });
    return s;
  };

  // ----- refrains: voice, cello, bed
  const rngR = sub(seed, 'refrain');
  let prevVar = null;
  const bedLo = 43, bedHi = 58;
  const refrainChords = []; // chords inside refrains (also pushed into chords[])
  refrains.forEach((r) => {
    const v = {
      answer: pick(rngR, [2, 5]), dev: pick(rngR, ['seq', 'invert', 'stretch']),
      harm: pick(rngR, ['thirds', 'pedal', 'counter']), end: pick(rngR, ['root', 'root', 'third', 'fifth']),
      reg: pick(rngR, [0, 0, 7]),
    };
    if (prevVar) {
      if (v.answer === prevVar.answer) v.answer = v.answer === 2 ? 5 : 2;
      while (v.dev === prevVar.dev) v.dev = pick(rngR, ['seq', 'invert', 'stretch']);
      while (v.harm === prevVar.harm) v.harm = pick(rngR, ['thirds', 'pedal', 'counter']);
      while (v.end === prevVar.end && v.end !== 'root') v.end = pick(rngR, ['root', 'third', 'fifth']);
    }
    prevVar = v; r.variant = v;
    const I = r.intensity;
    const swellDb = 4 + 2 * I; // 4 to 6 dB
    const swell = dbToLin(swellDb);
    r.swellDb = +swellDb.toFixed(1);
    const sBeats = motif.total;
    const stmts = [];
    // statement 1: the motif
    let idx1 = motif.idx.slice();
    // statement 2: developed
    let idx2, beats2 = motif.beats.slice();
    if (v.dev === 'seq') idx2 = motif.idx.map((i) => i + 1);
    else if (v.dev === 'invert') { const s0 = motif.idx[0]; idx2 = motif.idx.map((i) => s0 - (i - s0) + 2); }
    else { idx2 = motif.idx.map((i) => i + 1); const cap = chordSpan / beat - 1.5; let b = beats2.map((x, k) => (k < beats2.length - 1 ? x * 1.4 : x)); const tot = b.reduce((a, c) => a + c, 0); if (tot > cap) b = b.map((x) => x * cap / tot); beats2 = b; }
    // statement 3: answered a third or sixth above, ending chosen
    let idx3 = motif.idx.map((i) => i + v.answer + (v.reg ? 7 : 0));
    const target = { root: 0, third: 2, fifth: 4 }[v.end];
    {
      const last = idx3[idx3.length - 1]; let bestD = 0, bd = 99;
      for (let d = -6; d <= 6; d++) if (mod(last + d, 7) === target && Math.abs(d) < bd) { bd = Math.abs(d); bestD = d; }
      idx3[idx3.length - 1] = last + bestD;
    }
    idx1 = foldIdx(idx1); idx2 = foldIdx(idx2); idx3 = foldIdx(idx3);
    // choose chords
    let deg2 = 0, bestS = -1;
    const pref = CONTRAST[S.mode];
    for (let d = 1; d < 7; d++) {
      const pi = pref.indexOf(d);
      const s = fitScore(d, idx2, beats2) / sBeats * 5 + (pi >= 0 ? 4 - pi : 0) + rr(rngR, 0, 0.5);
      if (s > bestS) { bestS = s; deg2 = d; }
    }
    const degs = [0, deg2, 0];
    r.chordDegs = degs;
    const sets = [[idx1, motif.beats], [idx2, beats2], [idx3, motif.beats]];
    for (let s = 0; s < 3; s++) {
      const t0 = r.start + s * chordSpan, t1 = t0 + chordSpan;
      const deg = degs[s];
      chords.push({ t0, t1, deg, refrain: r.k });
      refrainChords.push({ t0, t1, deg, r, s });
      // voice notes
      const [idx, bts] = sets[s];
      let b = 0.5 + (s === 0 ? 0.5 : 0);
      const voiceNotes = [];
      idx.forEach((i, k) => {
        const lastNote = k === idx.length - 1;
        let dur = bts[k] * beat;
        if (s === 2 && lastNote) dur = Math.max(dur, r.end - 3.5 - (t0 + b * beat));
        voiceNotes.push({ t: t0 + b * beat, dur: dur * 0.98, midi: midiOf(i), idx: i });
        b += bts[k];
      });
      voiceNotes.forEach((n, k) => {
        push({ t: n.t, dur: n.dur, role: 'voice', midi: n.midi, vel: (0.62 + 0.35 * I) * (n.idx === voiceNotes[voiceNotes.length - 1].idx && k === voiceNotes.length - 1 ? 1.0 : 0.92),
          att: 0.25, rel: 2.2, tag: 'refrain', ref: r.k, pan: (k % 2 ? 0.12 : -0.12), det: rr(rngR, -4, 4) });
      });
      // cello
      const cel = (m) => { while (m > 55) m -= 12; while (m < 38) m += 12; return m; };
      const root = cel(midiOf(deg, pc0)), alts = tonesIn(deg, 38, 55);
      const cv = (0.42 + 0.3 * I);
      if (s === 0) {
        push({ t: t0, dur: chordSpan + 2, role: 'low', midi: root, alts, vel: cv, att: 3.5, rel: 3, tag: 'harm', ref: r.k });
      } else if (s === 1 && v.harm === 'pedal') {
        const fifth = cel(midiOf(deg + 4, pc0));
        push({ t: t0, dur: chordSpan / 2 + 1, role: 'low', midi: root, alts, vel: cv, att: 2.5, rel: 3, tag: 'harm', ref: r.k });
        push({ t: t0 + chordSpan / 2, dur: chordSpan / 2 + 1, role: 'low', midi: fifth, alts, vel: cv, att: 2.5, rel: 3, tag: 'harm', ref: r.k });
      } else if (s === 1 && v.harm === 'counter') {
        for (let k = 0; k < voiceNotes.length; k += 2) {
          const n = voiceNotes[k], n2 = voiceNotes[k + 1];
          const dur = (n2 ? n2.t + n2.dur - n.t : n.dur);
          push({ t: n.t, dur, role: 'low', midi: cel(midiOf(n.idx - 5)), alts, vel: cv, att: 0.8, rel: 2.5, tag: 'harm', ref: r.k });
        }
      } else {
        const back = (s === 2 && v.harm === 'counter') ? 5 : 2;
        voiceNotes.forEach((n) => {
          push({ t: n.t, dur: n.dur, role: 'low', midi: cel(midiOf(n.idx - back)), alts, vel: cv, att: 0.6, rel: 2.5, tag: 'harm', ref: r.k });
        });
      }
      // bed swell: chord tones, 4 to 6 dB louder, one octave-up tone in the last chord
      const pcs = chordPcs(deg);
      const avg = s === 0 ? 50 : 52;
      pcs.forEach((pc, j) => {
        const m = nearestPc(pc, avg + (j - 1) * 3, bedLo, bedHi);
        const st = t0 + j * rr(rngR, 0.4, 1.4) * beat;
        const end = (s === 2 ? r.end : t1 + 3);
        push({ t: st, dur: Math.min(48, end - st), role: 'bed', midi: m, alts: tonesIn(deg, bedLo, bedHi), vel: 0.26 * swell * (0.7 + 0.3 * I),
          att: Math.min(7, 3 + 4 * I), rel: 3.5, tag: 'refrain-bed', ref: r.k, pan: (j - 1) * 0.3, det: rr(rngR, -5, 5) });
      });
      if (s === 2) {
        const m = nearestPc(pcs[2], 58, 54, 62);
        push({ t: t0 + 0.5 * beat, dur: Math.min(48, r.end - t0 - 0.5 * beat), role: 'bed', midi: m, alts: tonesIn(deg, 54, 62), vel: 0.2 * swell * I, att: 6, rel: 4, tag: 'refrain-bed', ref: r.k, pan: 0.3 });
      }
    }
  });

  // ----- ordinary chords: bed, low roots (not in refrain)
  const rngB = sub(seed, 'bed');
  let prevVoicing = [47, 52, 55];
  chords.sort((a, b) => a.t0 - b.t0);
  for (const c of chords) {
    if (c.refrain >= 0) { prevVoicing = chordPcs(c.deg).map((pc) => nearestPc(pc, 52, bedLo, bedHi)).sort((a, b) => a - b); continue; }
    const pcs = chordPcs(c.deg);
    const avg = prevVoicing.reduce((a, b) => a + b, 0) / prevVoicing.length;
    const voicing = pcs.map((pc) => nearestPc(pc, avg, bedLo, bedHi)).sort((a, b) => a - b);
    prevVoicing = voicing;
    const f = (c.t0 + (c.t1 - c.t0) / 2) / L, a = arcAt(f);
    const overlap = rr(rngB, 3, 6);
    const alts = tonesIn(c.deg, bedLo, bedHi);
    voicing.forEach((m, j) => {
      let st = c.t0 + j * rr(rngB, 0.5, 3) * beat;
      const q = inRefrain(st) || null;
      const qq = refrains.find((r) => st >= r.end - 3 && st < r.quietEnd);
      if (qq) st = qq.quietEnd + j * 2.5;
      const end = c.t1 + overlap;
      if (end - st < 4) return;
      const att = clamp((end - st) * 0.3, 3, 9);
      push({ t: st, dur: Math.min(48, end - st), role: 'bed', midi: m, alts, vel: 0.19 * (0.65 + 0.35 * a), att, rel: 3.5, tag: 'chord', pan: (j - 1) * 0.35, det: rr(rngB, -6, 6) });
    });
    // low root
    let lst = c.t0 + rr(rngB, 0, 1.5) * beat;
    const qq2 = refrains.find((r) => lst >= r.end - 3 && lst < r.quietEnd);
    if (qq2) lst = qq2.quietEnd + 3;
    const root = (() => { let m = midiOf(c.deg, pc0); while (m > 50) m -= 12; while (m < 38) m += 12; return m; })();
    const lend = c.t1 + overlap;
    if (lend - lst > 4) push({ t: lst, dur: Math.min(48, lend - lst), role: 'low', midi: root, alts: tonesIn(c.deg, 38, 50), vel: 0.28 * (0.6 + 0.4 * a), att: clamp((lend - lst) * 0.25, 3, 8), rel: 3.5, tag: 'chord', pan: -0.15 });
  }
  const chordAt = (t) => { for (const c of chords) if (t >= c.t0 && t < c.t1) return c; return chords[chords.length - 1]; };

  // ----- loops on prime lengths (13, 17, 23, 29 beats): they never line up
  const lanes = [
    { id: 'laneA', prime: 13, role: 'bed', lo: 46, hi: 58, dur: [9, 14], vel: 0.15 },
    { id: 'laneB', prime: 17, role: 'low', lo: 38, hi: 50, dur: [8, 13], vel: 0.26 },
    { id: 'laneC', prime: 23, role: 'air', lo: 60, hi: 60, dur: [8, 8], vel: 0.5 },
    { id: 'laneD', prime: 29, role: 'bed', lo: 52, hi: 60, dur: [8, 12], vel: 0.1 },
  ];
  for (const ln of lanes) {
    const r = sub(seed, ln.id);
    const phase = rr(r, 0, ln.prime) * beat;
    const period = ln.prime * beat;
    for (let t = phase; t < L; t += period) {
      const gate = r(), pc = r(), du = r(), pn = r(), zi = r(), vv = r();
      const f = t / L;
      let dens = S.density * (0.45 + 0.75 * arcAt(f));
      const nr = nextRefrainAfter(t);
      if (nr && nr.start - t < 28) dens *= 1.5; // approach: a little more happening before a refrain
      if (inQuiet(t)) continue;
      const inR = inRefrain(t);
      if (inR) dens *= 0.5;
      if (gate > clamp(0.25 + dens * 0.75, 0, 0.98)) continue;
      const c = chordAt(t);
      if (ln.role === 'air') {
        push({ t, dur: 7.5, role: 'air', midi: 60, z: Math.floor(zi * 3), vel: ln.vel * (0.5 + 0.5 * vv) * (0.6 + 0.4 * arcAt(f)), att: 1.2, rel: 2, tag: 'lane', pan: (pn - 0.5) * 1.2 });
        continue;
      }
      const tones = tonesIn(c.deg, ln.lo, ln.hi);
      const m = tones[Math.floor(pc * tones.length)];
      const d = ln.dur[0] + du * (ln.dur[1] - ln.dur[0]);
      push({ t, dur: d, role: ln.role, midi: m, alts: tones, vel: ln.vel * (0.6 + 0.4 * arcAt(f)) * (0.6 + 0.8 * vv), att: Math.min(5, d * 0.4), rel: 3, tag: 'lane', pan: (pn - 0.5) * 0.9, det: (vv - 0.5) * 8 });
    }
  }
  // a breath of air as a refrain falls away
  // a very soft held root keeps the quiet from going dead: one low pad note through each quiet stretch
  for (const r of refrains) {
    const d = r.chordDegs ? r.chordDegs[2] : 0;
    const m = nearestPc(chordPcs(d)[0], 48, 43, 58);
    push({ t: r.end - 0.5, dur: Math.min(40, r.quiet + 8), role: 'bed', midi: m, alts: tonesIn(d, 43, 58), vel: 0.07, att: 4, rel: 5, tag: 'quiet-pad', pan: 0 });
  }
  for (const r of refrains) push({ t: r.end - 1.5, dur: 7.5, role: 'air', midi: 60, z: r.k % 3, vel: 0.35, att: 0.8, rel: 3, tag: 'fall', pan: 0.2 });

  // ----- fragments between refrains
  const rngF = sub(seed, 'frag');
  let ft = rr(rngF, 14, 30);
  while (ft < L - 20) {
    const t = Math.round(ft / beat) * beat;
    const gapn = rr(rngF, 16, 42) / (0.45 + S.density);
    ft += gapn;
    const nextR = nextRefrainAfter(t - 0.01);
    const bad = refrains.some((r) => t > r.start - 5 && t < r.quietEnd) || (inRefrain(t));
    const r1 = rngF(), r2 = rngF(), r3 = rngF(), r4 = rngF(), r5 = rngF();
    if (bad || t < 10) continue;
    const c = chordAt(t);
    const n = 2 + (r1 < 0.4 ? 1 : 0);
    const startK = r2 < 0.5 ? 0 : Math.floor(r2 * (motif.idx.length - n + 1));
    let idx = motif.idx.slice(startK, startK + n);
    let bts = motif.beats.slice(startK, startK + n);
    const how = pick(() => r3, ['plain', 'transpose', 'invert', 'stretch']);
    if (how === 'invert') { const s0 = idx[0]; idx = idx.map((i) => s0 - (i - s0)); }
    // first note lands on a chord tone of the current chord, nearest shift
    const set = [c.deg, c.deg + 2, c.deg + 4].map((i) => mod(i, 7));
    let sh = 0;
    for (const cand of [0, 1, -1, 2, -2, 3, -3]) if (set.includes(mod(idx[0] + cand + (how === 'transpose' ? 2 : 0), 7))) { sh = cand + (how === 'transpose' ? 2 : 0); break; }
    idx = foldIdx(idx.map((i) => i + sh));
    const stretch = how === 'stretch' ? rr(() => r4, 1.6, 2.4) : 1.3;
    const f = t / L, a = arcAt(f);
    let tt = t;
    idx.forEach((i, k) => {
      const last = k === idx.length - 1;
      const d = (last ? Math.max(bts[k], 3) * 1.4 : bts[k]) * beat * stretch;
      push({ t: tt, dur: d, role: 'voice', midi: midiOf(i), vel: (0.3 + 0.22 * a) * (last ? 0.95 : 1), att: 0.7, rel: 3, tag: 'fragment', pan: (r5 - 0.5) * 0.5, det: rr(rngF, -4, 4) });
      tt += bts[k] * beat * stretch;
    });
  }

  // ----- avoid minor-second clashes between simultaneous pitched voices
  const finalEvents = resolveClashes(events);
  finalEvents.sort((a, b) => a.t - b.t || a.midi - b.midi);
  finalEvents.forEach((e) => { e.att = Math.min(e.att, Math.max(0.02, e.dur * 0.5)); });

  // ----- automation: filter and level, every 2 s
  const auto = [];
  const baseCut = 650 * Math.pow(2, 3.4 * S.brightness);
  for (let t = 0; t <= L + 6; t += 2) {
    const f = clamp(t / L, 0, 1), a = arcAt(f), bl = bloom(t);
    const q = inQuiet(t) ? 1 : 0;
    const wob = 1 + 0.28 * Math.sin((2 * Math.PI * t) / 61) + 0.16 * Math.sin((2 * Math.PI * t) / 97 + 1.3) + 0.08 * Math.sin((2 * Math.PI * t) / 37 + 0.4);
    const nr = nextRefrainAfter(t);
    const approach = nr ? clamp(1 - (nr.start - t) / 30, 0, 1) : 0;
    const cut = clamp(baseCut * (0.5 + 0.7 * a) * wob * (1 + 0.9 * bl + 0.25 * approach) * (q ? 0.55 : 1), 250, 12000);
    const lvl = (0.62 + 0.38 * a) * (1 + 0.1 * approach) * (q ? 0.6 : 1);
    auto.push({ t, cut: Math.round(cut), lvl: +lvl.toFixed(3) });
  }

  // arc samples for the picture
  const arcPts = [];
  for (let i = 0; i <= 200; i++) arcPts.push(arcAt(i / 200));

  return {
    settings: S, events: finalEvents, refrains, chords, motif, auto, arcPts,
    meta: { beat, bar, length: L, bpm: S.bpm, key: S.key, mode: S.mode, seed, chordBars: cb },
  };
}

function makeMotif(rng, cb, beat) {
  const scaleIdx = (arr) => arr;
  let best = null;
  for (let tries = 0; tries < 6000 && !best; tries++) {
    const n = 5 + Math.floor(rng() * 3);
    const s0 = pick(rng, [0, 2, 4]);
    const leapAt = Math.floor(rng() * (n - 2)); // never the last interval
    const idx = [s0];
    let dir = rng() < 0.7 ? 1 : -1;
    let lastInt = 0;
    for (let k = 0; k < n - 1; k++) {
      let iv;
      if (k === leapAt) { iv = (rng() < 0.5 ? 2 : 3) * (rng() < 0.75 ? 1 : -1); }
      else if (k === leapAt + 1 && lastInt !== 0 && Math.abs(lastInt) >= 2) iv = -Math.sign(lastInt);
      else { if (rng() < 0.28) dir = -dir; iv = dir; }
      lastInt = iv; idx.push(idx[idx.length - 1] + iv);
    }
    const leaps = idx.slice(1).filter((x, k) => Math.abs(x - idx[k]) >= 2).length;
    const lastIdx = idx[idx.length - 1];
    const mn = Math.min(...idx), mx = Math.max(...idx);
    let changes = 0;
    for (let k = 2; k < idx.length; k++) if (Math.sign(idx[k] - idx[k - 1]) !== Math.sign(idx[k - 1] - idx[k - 2])) changes++;
    if (leaps !== 1) continue;
    if (![0, 2, 4].includes(mod(lastIdx, 7))) continue;
    if (mx - mn < 3 || mx - mn > 6) continue;
    if (changes > 3) continue;
    if (mn < -2 || mx > 8) continue;
    if (Math.abs(idx[idx.length - 1] - idx[idx.length - 2]) !== 1) continue;
    best = idx;
  }
  if (!best) best = [0, 1, 2, 4, 3, 2, 0];
  const n = best.length;
  const span = cb * 4 * beat;
  // total beats: about 11 s, never more than the chord span minus 3 beats
  const total = Math.max(7, Math.min(cb * 4 - 3, Math.round((11 / beat) * 2) / 2));
  const w = best.map((_, k) => (k === n - 1 ? 3 : pick(rng, [1, 1, 1.5, 2])));
  const sw = w.reduce((a, b) => a + b, 0);
  let beats = w.map((x) => Math.max(0.5, Math.round((x / sw) * total * 2) / 2));
  const sum = beats.slice(0, -1).reduce((a, b) => a + b, 0);
  beats[n - 1] = Math.max(1.5, total - sum);
  return { idx: best, beats, total: beats.reduce((a, b) => a + b, 0) };
}

// ---------------------------------------------------------------- clash resolution
const isClash = (a, b) => { const d = Math.abs(a - b) % 12; return d === 1 || d === 11; };
const pitched = (e) => e.role !== 'air';
const grp = (e) => (e.role === 'voice' ? 5 : e.role === 'low' && e.tag === 'harm' ? 4 : e.role === 'bed' ? 3 : 2);

function resolveClashes(evs) {
  const items = evs.filter(pitched).sort((a, b) => grp(b) - grp(a) || a.t - b.t);
  const B = new Map();
  const add = (e) => { for (let k = Math.floor(e.t); k <= Math.floor(e.t + e.dur); k++) { let a = B.get(k); if (!a) B.set(k, (a = [])); a.push(e); } };
  const conflicts = (m, t0, t1, self) => {
    const out = new Set();
    for (let k = Math.floor(t0); k <= Math.floor(t1); k++) {
      const a = B.get(k); if (!a) continue;
      for (const n of a) if (n !== self && !n.dead && n.t < t1 - 1e-6 && n.t + n.dur > t0 + 1e-6 && isClash(n.midi, m)) out.add(n);
    }
    return [...out];
  };
  for (const e of items) {
    let ok = false;
    for (let guard = 0; guard < 14 && !e.dead; guard++) {
      let cons = conflicts(e.midi, e.t, e.t + e.dur, e);
      if (!cons.length) { ok = true; break; }
      if (e.alts) {
        let found = false;
        for (const m of e.alts) { if (m !== e.midi && !conflicts(m, e.t, e.t + e.dur, e).length) { e.midi = m; found = true; break; } }
        if (found) { ok = true; break; }
      }
      const atStart = cons.filter((n) => n.t <= e.t + 1e-6);
      if (atStart.length) {
        const older = atStart.filter((n) => grp(n) === grp(e) || grp(n) < grp(e));
        const higher = atStart.filter((n) => grp(n) > grp(e));
        if (higher.length) { // wait for the stronger note to end
          const endT = Math.max(...higher.map((n) => n.t + n.dur));
          const nd = e.dur - (endT - e.t);
          if (nd < 3) { e.dead = true; break; }
          e.t = endT; e.dur = nd; continue;
        }
        for (const n of older) { n.dur = e.t - n.t; if (n.dur < 2) n.dead = true; }
        continue;
      }
      const startT = Math.min(...cons.map((n) => n.t));
      const nd = startT - e.t;
      if (nd < 3) { e.dead = true; break; }
      e.dur = nd;
    }
    if (e.dead || !ok) e.dead = true; else add(e);
  }
  return evs.filter((e) => !e.dead);
}

export function findClashes(events) {
  const ev = events.filter(pitched).sort((a, b) => a.t - b.t);
  const out = [];
  let active = [];
  for (const e of ev) {
    active = active.filter((n) => n.t + n.dur > e.t + 1e-6);
    for (const n of active) if (isClash(n.midi, e.midi)) out.push([n, e]);
    active.push(e);
  }
  return out;
}

export function harmonySig(S) {
  const s = normalize(S);
  return [s.key, s.mode, s.bpm, s.seed, s.length, s.refrainEvery].join('|');
}

// ---------------------------------------------------------------- pitch detection and loop making (imports)
export function detectPitch(data, sr) {
  const W = 2048, fmin = 40, fmax = 1100;
  const tauMax = Math.floor(sr / fmin), tauMin = Math.floor(sr / fmax);
  const need = W + tauMax + 4;
  if (data.length < need) return null;
  const nWin = 14;
  let best = null;
  const lo = Math.floor(data.length * 0.15), hi = Math.floor(data.length * 0.85) - need;
  for (let w = 0; w < nWin; w++) {
    const off = Math.floor(lo + (hi - lo) * (w / Math.max(1, nWin - 1)));
    if (off < 0) continue;
    let e = 0; for (let j = 0; j < W; j++) e += data[off + j] * data[off + j];
    if (e / W < 1e-6) continue;
    const d = new Float32Array(tauMax + 1);
    for (let tau = tauMin; tau <= tauMax; tau++) {
      let s = 0;
      for (let j = 0; j < W; j++) { const x = data[off + j] - data[off + j + tau]; s += x * x; }
      d[tau] = s;
    }
    const cm = new Float32Array(tauMax + 1);
    let run = 0; cm[0] = 1;
    for (let tau = 1; tau <= tauMax; tau++) { run += d[tau]; cm[tau] = tau < tauMin ? 1 : (d[tau] * tau) / (run || 1); }
    let tau = -1;
    for (let t = tauMin; t < tauMax; t++) { if (cm[t] < 0.15) { while (t + 1 < tauMax && cm[t + 1] < cm[t]) t++; tau = t; break; } }
    if (tau < 0) { let mn = 1e9; for (let t = tauMin; t < tauMax; t++) if (cm[t] < mn) { mn = cm[t]; tau = t; } }
    const conf = 1 - cm[tau];
    if (!best || conf > best.conf) {
      const a = cm[tau - 1], b = cm[tau], c = cm[tau + 1];
      const den = a - 2 * b + c;
      const ref = den !== 0 ? tau + (a - c) / (2 * den) : tau;
      best = { freq: sr / ref, conf };
    }
  }
  if (!best) return null;
  const midiF = 69 + 12 * Math.log2(best.freq / 440);
  const midi = Math.round(midiF);
  return { freq: best.freq, midi, cents: Math.round((midiF - midi) * 100), conf: best.conf };
}
export const noteName = (m) => ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B'][mod(m, 12)] + (Math.floor(m / 12) - 1);

// Steady part with an equal power crossfade baked into the tail so the loop has no click.
export function bakeLoop(mono, sr) {
  const dur = mono.length / sr;
  let a = Math.floor(sr * Math.max(0.25, dur * 0.22));
  let b = Math.floor(mono.length * 0.92);
  if (dur < 1.2) { a = Math.floor(mono.length * 0.3); b = mono.length; }
  let X = Math.min(Math.floor(sr * 1.2), Math.floor((b - a) * 0.4));
  if (a < X) a = X;
  const out = new Float32Array(b);
  out.set(mono.subarray(0, b));
  for (let i = 0; i < X; i++) {
    const u = i / X, fo = Math.cos(u * Math.PI / 2), fi = Math.sin(u * Math.PI / 2);
    out[b - X + i] = mono[b - X + i] * fo + mono[a - X + i] * fi;
  }
  return { data: out, loopStart: a / sr, loopEnd: b / sr };
}
export function rmsOf(data) { let s = 0; for (let i = 0; i < data.length; i++) s += data[i] * data[i]; return Math.sqrt(s / Math.max(1, data.length)); }

// ---------------------------------------------------------------- kit (samples)
export const ROLES = ['bed', 'low', 'voice', 'air'];
export const ROLE_NAMES = { bed: 'Bed', low: 'Low', voice: 'Melody', air: 'Air' };
const ROLE_INSTR = { bed: 'pad', low: 'cello', voice: 'horn', air: 'texture' };
const NORM = { pad: 0.34, cello: 0.7, horn: 0.7, texture: 2.0 };

export class Kit {
  constructor(sampleRate = 48000) {
    this.sr = sampleRate;
    this.starter = {}; // role -> {zones}
    this.imported = {}; // role -> {zones, name, root, ...}
    this.ready = false;
  }
  async loadStarter(base) {
    const AC = globalThis.OfflineAudioContext;
    const dec = new AC(2, 1, this.sr);
    const meta = await (await fetch(base + 'samples.json')).json();
    const files = new Map();
    for (const ins of meta.instruments) for (const z of ins.zones) files.set(z.file, null);
    await Promise.all([...files.keys()].map(async (f) => {
      const r = await fetch(base + encodeURIComponent(f.replace(/\.wav$/, '.flac'))); // same 24-bit audio, lossless
      if (!r.ok) throw new Error(`${f}: ${r.status}`);
      const ab = await r.arrayBuffer();
      files.set(f, await dec.decodeAudioData(ab));
    }));
    for (const role of ROLES) {
      const ins = meta.instruments.find((i) => i.id === ROLE_INSTR[role]);
      const zones = ins.zones.map((z) => ({
        buf: files.get(z.file), root: z.root, lo: z.lo, hi: z.hi,
        loopStart: z.loop_start != null ? z.loop_start / meta.sample_rate : null,
        loopEnd: z.loop_end != null ? z.loop_end / meta.sample_rate : null,
        gain: dbToLin(z.gain_db || 0) * NORM[ins.id], tune: z.tune_cents || 0,
      }));
      this.starter[role] = { zones, name: ins.name, sustain: ins.sustain };
    }
    this.ready = true;
  }
  // rec: {data Float32Array mono, sr, root, name}
  setImported(role, rec) {
    if (!rec) { delete this.imported[role]; return; }
    const baked = bakeLoop(rec.data, rec.sr);
    const AC = globalThis.OfflineAudioContext;
    const ctx = new AC(1, 1, this.sr);
    const buf = ctx.createBuffer(1, baked.data.length, rec.sr);
    buf.copyToChannel(baked.data, 0);
    const steady = baked.data.subarray(Math.floor(baked.loopStart * rec.sr), Math.floor(baked.loopEnd * rec.sr));
    const r = rmsOf(steady) || 0.05;
    const gain = clamp(0.08 / r, 0.1, 8);
    this.imported[role] = { name: rec.name, root: rec.root, imported: true, sustain: true,
      zones: [{ buf, root: rec.root, lo: -999, hi: 999, loopStart: baked.loopStart, loopEnd: baked.loopEnd, gain, tune: 0 }] };
  }
  isYours(role) { return !!this.imported[role]; }
  instr(role) { return this.imported[role] || this.starter[role]; }
  // choose buffer, rate and loop for a pitched note
  voice(role, midi, z = 0) {
    const ins = this.instr(role);
    if (!ins) return null;
    if (role === 'air' && !ins.imported) {
      const zone = ins.zones[z % ins.zones.length];
      return { zone, rate: 1, loop: false };
    }
    let zone = ins.zones.find((q) => midi >= q.lo && midi <= q.hi);
    if (!zone) { let bd = 1e9; for (const q of ins.zones) { const d = Math.abs(midi - q.root); if (d < bd) { bd = d; zone = q; } } }
    let m = midi;
    if (ins.imported) { while (m - zone.root > 12) m -= 12; while (zone.root - m > 12) m += 12; }
    const rate = Math.pow(2, (m - zone.root + zone.tune / 100) / 12);
    return { zone, rate, loop: zone.loopStart != null && ins.sustain };
  }
}

// ---------------------------------------------------------------- audio graph
function makeImpulse(ctx, seconds, seed) {
  const sr = ctx.sampleRate, n = Math.floor(sr * seconds);
  const buf = ctx.createBuffer(2, n, sr);
  for (let c = 0; c < 2; c++) {
    const r = mulberry32(seed + c * 977), d = buf.getChannelData(c);
    let lp = 0;
    for (let i = 0; i < n; i++) {
      const t = i / sr;
      const env = Math.exp(-t * 3.1 / seconds * 2.2) * (t < 0.02 ? t / 0.02 : 1);
      const k = 0.55 + 0.4 * Math.exp(-t * 0.9); // darker as it decays
      lp += k * ((r() * 2 - 1) - lp) * 0.6;
      d[i] = lp * env;
    }
  }
  // normalise energy
  let e = 0; for (let c = 0; c < 2; c++) { const d = buf.getChannelData(c); for (let i = 0; i < n; i++) e += d[i] * d[i]; }
  const g = 1 / Math.sqrt(e / 2) * 0.18;
  for (let c = 0; c < 2; c++) { const d = buf.getChannelData(c); for (let i = 0; i < n; i++) d[i] *= g; }
  return buf;
}

export function buildGraph(ctx, S, dest) {
  const g = {};
  const bus = {};
  for (const r of ROLES) { bus[r] = ctx.createGain(); }
  bus.bed.gain.value = 1.0; bus.low.gain.value = 0.95; bus.voice.gain.value = 1.0; bus.air.gain.value = 0.7;
  g.bus = bus;
  g.pre = ctx.createGain();
  g.tone = ctx.createBiquadFilter(); g.tone.type = 'lowpass'; g.tone.frequency.value = 3000; g.tone.Q.value = 0.5;
  g.lvl = ctx.createGain(); g.lvl.gain.value = 0.8;
  bus.bed.connect(g.tone); bus.low.connect(g.tone); bus.air.connect(g.tone);
  g.tone.connect(g.lvl); g.lvl.connect(g.pre);
  g.vlp = ctx.createBiquadFilter(); g.vlp.type = 'lowpass'; g.vlp.frequency.value = 2500 + 6500 * (S.brightness || 0.5); g.vlp.Q.value = 0.3;
  bus.voice.connect(g.vlp); g.vlp.connect(g.pre);
  g.master = ctx.createGain(); g.master.gain.value = MASTER_TRIM;
  g.pre.connect(g.master); // dry
  // reverb
  g.conv = ctx.createConvolver(); g.conv.buffer = makeImpulse(ctx, 6.5, 4242);
  g.send = ctx.createGain(); g.send.gain.value = 0.2 + 0.9 * (S.space ?? 0.5);
  g.wet = ctx.createGain(); g.wet.gain.value = 1;
  g.pre.connect(g.send); g.send.connect(g.conv); g.conv.connect(g.wet); g.wet.connect(g.master);
  // stereo delay on voice and air
  g.dsend = ctx.createGain(); g.dsend.gain.value = 0.12 + 0.45 * (S.space ?? 0.5);
  bus.voice.connect(g.dsend); bus.air.connect(g.dsend);
  const dl = ctx.createDelay(2), dr = ctx.createDelay(2), fb = ctx.createGain(), fl = ctx.createBiquadFilter();
  dl.delayTime.value = 0.43; dr.delayTime.value = 0.61; fb.gain.value = 0.38;
  fl.type = 'lowpass'; fl.frequency.value = 2400;
  const pl = ctx.createStereoPanner(), pr = ctx.createStereoPanner(); pl.pan.value = -0.8; pr.pan.value = 0.8;
  g.dsend.connect(dl); dl.connect(pl); pl.connect(g.master);
  dl.connect(dr); dr.connect(pr); pr.connect(g.master);
  dr.connect(fl); fl.connect(fb); fb.connect(dl);
  // dynamics: gentle compressor, then a fast limiter, then a soft ceiling
  g.comp = ctx.createDynamicsCompressor();
  g.comp.threshold.value = -16; g.comp.knee.value = 14; g.comp.ratio.value = 3; g.comp.attack.value = 0.03; g.comp.release.value = 0.5;
  g.lim = ctx.createDynamicsCompressor();
  g.lim.threshold.value = -3; g.lim.knee.value = 0; g.lim.ratio.value = 20; g.lim.attack.value = 0.002; g.lim.release.value = 0.2;
  g.shaper = ctx.createWaveShaper();
  const N = 2048, curve = new Float32Array(N);
  for (let i = 0; i < N; i++) { const x = (i / (N - 1)) * 2 - 1; curve[i] = Math.tanh(x * 1.1) * 0.93; }
  g.shaper.curve = curve;
  g.analyser = ctx.createAnalyser(); g.analyser.fftSize = 1024; g.analyser.smoothingTimeConstant = 0.8;
  g.master.connect(g.comp); g.comp.connect(g.lim); g.lim.connect(g.shaper); g.shaper.connect(dest || ctx.destination);
  g.shaper.connect(g.analyser);
  g.setSpace = (v) => { g.send.gain.value = 0.2 + 0.9 * v; g.dsend.gain.value = 0.12 + 0.45 * v; };
  return g;
}
export let MASTER_TRIM = 0.56;

// Start one note. Returns {gain, src, end}
export function playEvent(ctx, g, kit, ev, when, skipStartOffset = 0) {
  const v = kit.voice(ev.role, ev.midi, ev.z || 0);
  if (!v) return null;
  const src = ctx.createBufferSource();
  src.buffer = v.zone.buf;
  src.playbackRate.value = v.rate;
  src.detune.value = ev.det || 0;
  const env = ctx.createGain();
  const pan = ctx.createStereoPanner(); pan.pan.value = clamp(ev.pan || 0, -1, 1);
  const peak = ev.vel * v.zone.gain;
  const t0 = when;
  env.gain.setValueAtTime(0, t0);
  let end;
  if (v.loop) {
    src.loop = true; src.loopStart = v.zone.loopStart; src.loopEnd = v.zone.loopEnd;
    const att = Math.max(0.02, Math.min(ev.att, ev.dur));
    env.gain.linearRampToValueAtTime(peak, t0 + att);
    env.gain.setValueAtTime(peak, t0 + Math.max(att, ev.dur));
    env.gain.setTargetAtTime(0, t0 + ev.dur, ev.rel / 3.2);
    end = t0 + ev.dur + ev.rel + 0.2;
  } else {
    const len = v.zone.buf.duration / v.rate;
    const att = Math.max(0.02, ev.att);
    env.gain.linearRampToValueAtTime(peak, t0 + att);
    const hold = Math.min(ev.dur, len - ev.rel);
    env.gain.setValueAtTime(peak, t0 + Math.max(att, hold));
    env.gain.setTargetAtTime(0, t0 + Math.max(att, hold), ev.rel / 3.2);
    end = Math.min(t0 + len, t0 + Math.max(att, hold) + ev.rel + 0.2);
  }
  src.connect(env); env.connect(pan); pan.connect(g.bus[ev.role]);
  src.start(t0);
  src.stop(end);
  return { env, src, end, role: ev.role };
}

function scheduleAuto(g, pts, t0, from, to, firstCall) {
  for (const p of pts) {
    if (p.t < from || p.t >= to) continue;
    const at = t0 + p.t;
    g.tone.frequency.linearRampToValueAtTime(p.cut, at);
    g.lvl.gain.linearRampToValueAtTime(p.lvl, at);
  }
}

// ---------------------------------------------------------------- live player
export class Player {
  constructor(kit, settings, hooks = {}) {
    this.kit = kit; this.S = normalize(settings); this.plan = plan(this.S);
    this.hooks = hooks; this.ctx = null; this.g = null; this.state = 'idle';
    this.t0 = 0; this.cursor = 0; this.autoCursor = 0; this.active = []; this.timer = null;
    this.look = 3.0;
  }
  get position() { if (!this.ctx || this.state === 'idle') return this.stoppedAt || 0; return clamp(this.ctx.currentTime - this.t0, 0, this.plan.meta.length + 8); }
  unlock() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'playback', sampleRate: 48000 });
      this.g = buildGraph(this.ctx, this.S);
      this.t0 = this.ctx.currentTime + 0.25;
      this.cursor = 0; this.autoCursor = 0;
      this.g.tone.frequency.setValueAtTime(this.plan.auto[0].cut, this.ctx.currentTime);
      this.g.lvl.gain.setValueAtTime(this.plan.auto[0].lvl, this.ctx.currentTime);
      this.fresh = true;
    }
    return this.ctx.state === 'running' ? Promise.resolve() : this.ctx.resume();
  }
  async start() {
    await this.unlock();
    if (this.fresh) { this.t0 = this.ctx.currentTime + 0.25; this.fresh = false; } // loading time must not eat the opening
    this.state = 'playing';
    clearInterval(this.timer);
    this.timer = setInterval(() => this.tick(), 120);
    this.tick();
    this.hooks.onState && this.hooks.onState(this.state);
  }
  async pause() {
    if (!this.ctx) return;
    await this.ctx.suspend();
    this.state = 'paused'; clearInterval(this.timer);
    this.hooks.onState && this.hooks.onState(this.state);
  }
  stop() {
    clearInterval(this.timer);
    this.stoppedAt = 0;
    if (this.ctx) { const c = this.ctx; this.ctx = null; this.g = null; c.close().catch(() => {}); }
    this.active = []; this.state = 'idle';
    this.hooks.onState && this.hooks.onState(this.state);
  }
  tick() {
    const ctx = this.ctx; if (!ctx) return;
    const now = ctx.currentTime, songNow = now - this.t0;
    const horizon = songNow + this.look;
    const ev = this.plan.events;
    // binary search to first event >= cursor
    let lo = 0, hi = ev.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (ev[m].t < this.cursor) lo = m + 1; else hi = m; }
    let i = lo;
    for (; i < ev.length && ev[i].t < horizon; i++) {
      const e = ev[i];
      const when = this.t0 + e.t;
      if (when < now - 0.4) continue;
      const h = playEvent(ctx, this.g, this.kit, e, Math.max(when, now + 0.02));
      if (h) this.active.push(h);
    }
    this.cursor = Math.max(this.cursor, horizon);
    scheduleAuto(this.g, this.plan.auto, this.t0, this.autoCursor, horizon + 2);
    this.autoCursor = Math.max(this.autoCursor, horizon + 2);
    this.active = this.active.filter((h) => h.end > now);
    this.hooks.onTick && this.hooks.onTick(songNow);
    if (songNow > this.plan.meta.length + 7) { this.stop(); this.hooks.onEnd && this.hooks.onEnd(); }
  }
  // Re-plan from the next bar without stopping sound.
  update(settings) {
    const oldSig = harmonySig(this.S);
    const oldBar = this.plan.meta.bar;
    this.S = normalize(settings);
    const np = plan(this.S);
    const newSig = harmonySig(this.S);
    if (this.g) this.g.setSpace(this.S.space);
    if (!this.ctx || this.state === 'idle') { this.plan = np; return; }
    const now = this.ctx.currentTime, songNow = now - this.t0;
    const cutT = Math.ceil((songNow + 0.3) / oldBar) * oldBar;
    const cutAbs = this.t0 + cutT;
    this.plan = np;
    this.cursor = cutT; this.autoCursor = cutT;
    const g = this.g;
    g.tone.frequency.cancelScheduledValues(cutAbs); g.lvl.gain.cancelScheduledValues(cutAbs);
    g.vlp.frequency.setTargetAtTime(2500 + 6500 * this.S.brightness, now, 0.5);
    if (oldSig !== newSig) {
      // fade what still rings across the cut, and restart in-progress sustained notes from the new plan
      for (const h of this.active) {
        if (h.end > cutAbs + 0.2) { h.env.gain.cancelScheduledValues(cutAbs); h.env.gain.setTargetAtTime(0, cutAbs, 0.7); try { h.src.stop(cutAbs + 4); } catch (e) {} }
      }
      for (const e of np.events) {
        if (e.t < cutT && e.t + e.dur > cutT + 2.5 && e.role !== 'voice' && e.role !== 'air') {
          const c = Object.assign({}, e, { t: cutT, dur: e.t + e.dur - cutT, att: 2.2, tag: 'resume' });
          const h = playEvent(this.ctx, g, this.kit, c, cutAbs);
          if (h) this.active.push(h);
        }
      }
    }
    this.hooks.onPlan && this.hooks.onPlan(np, cutT);
  }
  // The kit changed under a playing piece: fade what rings now and restart sustained notes with the new sounds,
  // so the change is heard in seconds instead of when the next long chord starts (up to 48 s later).
  swapSounds() {
    if (!this.ctx || this.state !== 'playing') return;
    const now = this.ctx.currentTime, cutAbs = now + 0.15, cutT = cutAbs - this.t0;
    for (const h of this.active) {
      if (h.end > cutAbs + 0.2) { h.env.gain.cancelScheduledValues(cutAbs); h.env.gain.setTargetAtTime(0, cutAbs, 0.5); try { h.src.stop(cutAbs + 3); } catch (e) {} }
    }
    for (const e of this.plan.events) {
      if (e.t < cutT && e.t + e.dur > cutT + 1.5) {
        const c = Object.assign({}, e, { t: cutT, dur: e.t + e.dur - cutT, att: 1.2, tag: 'resume' });
        const h = playEvent(this.ctx, this.g, this.kit, c, cutAbs);
        if (h) this.active.push(h);
      }
    }
  }
}

// ---------------------------------------------------------------- offline render
export async function renderSegment(kit, pl, S, from, to, pre, onSr = 48000) {
  const sr = onSr;
  const startRender = Math.max(0, from - pre);
  const lenSec = to - startRender;
  const ctx = new OfflineAudioContext(2, Math.ceil(lenSec * sr), sr);
  const g = buildGraph(ctx, S);
  const first = pl.auto.find((p) => p.t >= startRender) || pl.auto[0];
  g.tone.frequency.setValueAtTime(first.cut, 0); g.lvl.gain.setValueAtTime(first.lvl, 0);
  for (const p of pl.auto) {
    if (p.t < startRender || p.t > to) continue;
    g.tone.frequency.linearRampToValueAtTime(p.cut, p.t - startRender);
    g.lvl.gain.linearRampToValueAtTime(p.lvl, p.t - startRender);
  }
  for (const e of pl.events) {
    if (e.t >= to) break;
    if (e.t + e.dur + e.rel < startRender) continue;
    const w = e.t - startRender;
    if (w < 0) continue; // pre-roll is long enough that nothing active starts before it
    playEvent(ctx, g, kit, e, w);
  }
  const buf = await ctx.startRendering();
  const skip = Math.round((from - startRender) * sr);
  const n = Math.round((to - from) * sr);
  return { l: buf.getChannelData(0).subarray(skip, skip + n), r: buf.getChannelData(1).subarray(skip, skip + n), n };
}

// Returns a Blob (16-bit stereo WAV at 48 kHz). Renders in segments so memory stays small.
export async function renderWav(kit, S0, { seconds, onProgress, segLen = 120, pl } = {}) {
  const S = normalize(S0);
  pl = pl || plan(S);
  const total = Math.min(seconds || S.length, S.length);
  const sr = 48000, pre = 50;
  const parts = [];
  const nTotal = Math.round(total * sr);
  const header = new ArrayBuffer(44);
  const dv = new DataView(header);
  const w4 = (o, s) => { for (let i = 0; i < 4; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  w4(0, 'RIFF'); dv.setUint32(4, 36 + nTotal * 4, true); w4(8, 'WAVE'); w4(12, 'fmt ');
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 2, true); dv.setUint32(24, sr, true);
  dv.setUint32(28, sr * 4, true); dv.setUint16(32, 4, true); dv.setUint16(34, 16, true); w4(36, 'data'); dv.setUint32(40, nTotal * 4, true);
  parts.push(header);
  let done = 0;
  const fadeN = sr * 4;
  for (let from = 0; from < total; from += segLen) {
    const to = Math.min(total, from + segLen);
    const seg = await renderSegment(kit, pl, S, from, to, pre, sr);
    const out = new Int16Array(seg.n * 2);
    for (let i = 0; i < seg.n; i++) {
      let gain = 1;
      const gi = done + i;
      if (gi > nTotal - fadeN) gain = Math.max(0, (nTotal - gi) / fadeN);
      let l = clamp(seg.l[i] * gain, -1, 1), r = clamp(seg.r[i] * gain, -1, 1);
      out[2 * i] = Math.round(l * 32767); out[2 * i + 1] = Math.round(r * 32767);
    }
    parts.push(out.buffer);
    done += seg.n;
    onProgress && onProgress(Math.min(1, done / nTotal));
    await new Promise((res) => setTimeout(res, 0));
  }
  return new Blob(parts, { type: 'audio/wav' });
}
