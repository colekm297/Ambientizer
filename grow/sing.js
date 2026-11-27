// Sing: turn a hummed or sung take into a refrain melody.
// Pure functions, no browser needed (node imports this for the unit check).
//   trackPitch  -> frame-wise pitch (YIN, 10 ms hop) with confidence and a voicing flag
//   segmentNotes -> notes from the pitch track (median filtered, scoops and vibrato ignored)
//   buildTunes  -> snap to the piece's scale, quantize to 8ths, then shape two versions: Close and Polished
// His voice is never played back: the result is only notes (scale steps + beats).
import { MODES, scaleMidi, refrainCap } from './grow.js';

const mod = (n, m) => ((n % m) + m) % m;
const median = (a) => { if (!a.length) return NaN; const s = a.slice().sort((x, y) => x - y); const h = s.length >> 1; return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2; };
const CHORD = [0, 2, 4]; // tonic triad, as scale degrees
const isCT = (i) => CHORD.includes(mod(i, 7));

// ---------------------------------------------------------------- pitch tracking
function to16k(data, sr) {
  if (sr === 16000) return data;
  const ratio = sr / 16000, n = Math.floor(data.length / ratio);
  const out = new Float32Array(n);
  const w = Math.max(1, Math.round(ratio)); // box average as the low-pass
  for (let i = 0; i < n; i++) {
    const c = Math.floor(i * ratio); let s = 0, k = 0;
    for (let j = 0; j < w; j++) { const p = c + j - (w >> 1); if (p >= 0 && p < data.length) { s += data[p]; k++; } }
    out[i] = k ? s / k : 0;
  }
  return out;
}

export function trackPitch(data, sr, { fmin = 70, fmax = 1000, hop = 0.01 } = {}) {
  const x = to16k(data, sr), R = 16000;
  const W = 512, tauMin = Math.floor(R / fmax), tauMax = Math.floor(R / fmin);
  const H = Math.round(hop * R);
  const frames = [];
  const d = new Float32Array(tauMax + 2), cm = new Float32Array(tauMax + 2);
  for (let s = 0; s + W + tauMax + 2 < x.length; s += H) {
    let e = 0; for (let j = 0; j < W; j++) e += x[s + j] * x[s + j];
    const rms = Math.sqrt(e / W);
    const fr = { t: (s + W / 2) / R, rms, f0: 0, midi: NaN, conf: 0, voiced: false };
    frames.push(fr);
    if (rms < 1e-4) continue;
    for (let tau = 1; tau <= tauMax + 1; tau++) {
      let sum = 0;
      for (let j = 0; j < W; j++) { const dd = x[s + j] - x[s + j + tau]; sum += dd * dd; }
      d[tau] = sum;
    }
    let run = 0; cm[0] = 1;
    for (let tau = 1; tau <= tauMax + 1; tau++) { run += d[tau]; cm[tau] = (d[tau] * tau) / (run || 1); }
    let tau = -1;
    for (let t = tauMin; t < tauMax; t++) { if (cm[t] < 0.15) { while (t + 1 < tauMax && cm[t + 1] < cm[t]) t++; tau = t; break; } }
    if (tau < 0) { let mn = 1e9; for (let t = tauMin; t < tauMax; t++) if (cm[t] < mn) { mn = cm[t]; tau = t; } }
    if (tau < tauMin + 1 || tau >= tauMax) continue;
    const a = cm[tau - 1], b = cm[tau], c = cm[tau + 1], den = a - 2 * b + c;
    const ref = den > 1e-9 ? tau + (a - c) / (2 * den) : tau;
    fr.f0 = R / ref; fr.conf = 1 - b; fr.midi = 69 + 12 * Math.log2(fr.f0 / 440);
  }
  // voicing: confident and not near the noise floor
  const rs = frames.map((f) => f.rms).sort((p, q) => p - q);
  const p90 = rs[Math.floor(rs.length * 0.9)] || 0;
  const gate = Math.max(0.0015, 0.08 * p90);
  for (const f of frames) f.voiced = f.conf >= 0.72 && f.rms >= gate && Number.isFinite(f.midi);
  // octave repair against a rolling median, then a 5-frame median filter inside voiced runs
  const raw = frames.map((f) => (f.voiced ? f.midi : NaN));
  for (let i = 0; i < frames.length; i++) {
    if (!frames[i].voiced) continue;
    const nb = []; for (let k = Math.max(0, i - 12); k <= Math.min(frames.length - 1, i + 12); k++) if (frames[k].voiced) nb.push(raw[k]);
    const m = median(nb);
    let v = raw[i]; while (v - m > 7) v -= 12; while (m - v > 7) v += 12;
    frames[i].midi = v;
  }
  const sm = frames.map((f) => f.midi);
  for (let i = 0; i < frames.length; i++) {
    if (!frames[i].voiced) continue;
    const nb = []; for (let k = i - 2; k <= i + 2; k++) if (k >= 0 && k < frames.length && frames[k].voiced) nb.push(frames[k].midi);
    sm[i] = median(nb);
  }
  frames.forEach((f, i) => { f.m = sm[i]; });
  return { hop, frames };
}

// ---------------------------------------------------------------- notes from the track
// A note is a run of frames near one pitch. A new note starts only when the pitch has settled somewhere else for
// 60 ms, so scoops, vibrato and wobble stay inside notes. A gap of 50 ms of silence or a dip in loudness splits notes.
export function segmentNotes(track, { tol = 0.7, settle = 6, gapFrames = 5 } = {}) {
  const F = track.frames, hop = track.hop, notes = [];
  let cur = null, pending = [], gap = 0, lastIn = -1, peak = 0, dip = 0, dipStart = -1;
  const finish = (endI) => {
    if (cur && endI >= cur.i0) {
      const vals = cur.vals.slice().sort((a, b) => a - b);
      const lo = Math.floor(vals.length * 0.2), mid = vals.slice(lo, Math.max(lo + 1, Math.ceil(vals.length * 0.8)));
      const n = endI - cur.i0 + 1;
      if (n >= 3) notes.push({ t0: F[cur.i0].t - hop / 2, t1: F[endI].t + hop / 2, dur: n * hop, midi: mid.reduce((a, b) => a + b, 0) / mid.length });
    }
    cur = null; pending = []; peak = 0; dip = 0;
  };
  const begin = (i, vals) => { cur = { i0: i, vals }; pending = []; lastIn = i; peak = F[i].rms; dip = 0; };
  for (let i = 0; i < F.length; i++) {
    const f = F[i];
    if (!f.voiced) { gap++; if (cur && gap >= gapFrames) finish(lastIn); continue; }
    gap = 0;
    if (!cur) { begin(i, [f.m]); continue; }
    const center = median(cur.vals.slice(-40));
    if (Math.abs(f.m - center) <= tol) {
      if (pending.length) { pending.forEach((p) => cur.vals.push(p.m)); pending = []; }
      if (f.rms < peak * 0.4) { if (!dip) dipStart = i; dip++; lastIn = i; continue; }
      if (dip >= 3 && f.rms > peak * 0.7) { finish(dipStart - 1); begin(i, [f.m]); continue; } // a repeated note
      dip = 0; peak = Math.max(peak * 0.998, f.rms);
      cur.vals.push(f.m); lastIn = i;
    } else {
      pending.push({ i, m: f.m });
      if (pending.length >= settle) {
        const last = pending.slice(-settle), pm = median(last.map((p) => p.m));
        if (last.every((p) => Math.abs(p.m - pm) <= tol)) { // settled somewhere else: the note changed where the pitch left
          const start = pending[0].i, vals = last.map((p) => p.m);
          finish(lastIn); begin(start, vals); lastIn = i;
        }
      }
    }
  }
  if (cur) finish(lastIn);
  // a short note right before another one, close in pitch, is the scoop into it: it becomes the start of that note
  for (let k = notes.length - 2; k >= 0; k--) {
    const a = notes[k], b = notes[k + 1];
    if (a.dur < 0.13 && b.t0 - a.t1 < 0.03 && Math.abs(a.midi - b.midi) <= 2.5) { b.t0 = a.t0; b.dur = b.t1 - b.t0; notes.splice(k, 1); }
  }
  return notes;
}

// ---------------------------------------------------------------- quantize, snap, shape
const nearestIdx = (m, key, mode, strong) => {
  let best = 0, bc = 1e9;
  for (let i = -21; i <= 28; i++) {
    const mm = scaleMidi(i, key, mode), dist = Math.abs(mm - m);
    if (dist > 3) continue;
    const c = dist + (strong && !isCT(i) ? 0.5 : 0) - (isCT(i) ? 0.1 : 0);
    if (c < bc) { bc = c; best = i; }
  }
  return best;
};

function tuningOffset(notes) { // consistent flat or sharp singing, in semitones
  let sx = 0, sy = 0, w = 0;
  for (const n of notes) { const dev = n.midi - Math.round(n.midi); sx += Math.cos(2 * Math.PI * dev) * n.dur; sy += Math.sin(2 * Math.PI * dev) * n.dur; w += n.dur; }
  if (!w) return 0;
  const r = Math.hypot(sx, sy) / w;
  return r > 0.5 ? Math.atan2(sy, sx) / (2 * Math.PI) : 0;
}

function gridShift(notes, eighth) { // whole-take lateness: the shift that puts onsets closest to the 8th grid
  let best = 0, bc = 1e9;
  for (let s = -0.35 * eighth; s <= 0.35 * eighth + 1e-9; s += 0.01) {
    let c = 0; for (const n of notes) { const u = (n.t0 - s) / eighth; c += Math.abs(u - Math.round(u)); }
    c += 0.02 * Math.abs(s) / eighth * notes.length;
    if (c < bc) { bc = c; best = s; }
  }
  return best;
}

const medianIdxShift = (notes, key, mode) => { // whole octaves into the horn's comfortable range
  const ms = notes.map((n) => scaleMidi(n.i, key, mode)).sort((a, b) => a - b);
  const mid = ms[Math.floor(ms.length / 2)];
  let k = Math.round((67 - mid) / 12);
  const lo = ms[0] + 12 * k, hi = ms[ms.length - 1] + 12 * k;
  if (hi > 80 && lo - 12 >= 52) k -= 1; else if (lo < 55 && hi + 12 <= 83) k += 1;
  return 7 * k;
};

function quantize(raw, o) {
  const { bpm, key, mode } = o;
  const beat = 60 / bpm, eighth = beat / 2;
  const q = [];
  raw.forEach((n) => {
    const s = Math.max(0, Math.round((n.t0 - o.shift) / eighth) / 2);
    let e = Math.round((n.t1 - o.shift) / eighth) / 2;
    if (e <= s + 0.5) e = s + 0.5;
    q.push({ b: s, l: e - s, m: n.midi, dur: n.dur, raw: n.midi });
  });
  // longer notes sit on beats: an off-beat start of a note of a beat or more moves to the nearest beat
  q.forEach((n) => { if (n.l >= 1.5 && n.b % 1 === 0.5) { const up = n.b + 0.5, dn = n.b - 0.5; n.b = (dn % 2 === 0 || up % 2 !== 0) ? dn : up; if (n.b < 0) n.b = 0; } });
  // one note per onset
  const out = [];
  q.sort((a, b) => a.b - b.b);
  for (const n of q) {
    const p = out[out.length - 1];
    if (p && n.b <= p.b) { if (n.dur > p.dur) { p.m = n.m; p.raw = n.raw; p.dur = n.dur; p.l = Math.max(p.l, n.l); } continue; }
    out.push(n);
  }
  for (let k = 0; k < out.length; k++) { const nx = out[k + 1]; out[k].l = nx ? Math.min(out[k].l, nx.b - out[k].b) : out[k].l; if (out[k].l < 0.5) out[k].l = 0.5; }
  // pitch: nearest scale tone, leaning to chord tones on strong beats (beats 1 and 3)
  out.forEach((n, k) => { n.i = nearestIdx(n.m, key, mode, n.b % 2 === 0); });
  for (let k = 1; k < out.length; k++) { // keep the direction of a clear step
    const dr = out[k].raw - out[k - 1].raw;
    if (Math.abs(dr) >= 1.2 && out[k].i === out[k - 1].i) out[k].i += Math.sign(dr);
  }
  return out;
}

function foldLeaps(ns, limit) { // a leap past `limit` steps moves the rest of the phrase an octave
  for (let k = 1; k < ns.length; k++) {
    let d = ns[k].i - ns[k - 1].i, guard = 0;
    while (Math.abs(d) >= limit && guard++ < 3) { const sh = d > 0 ? -7 : 7; for (let j = k; j < ns.length; j++) ns[j].i += sh; d = ns[k].i - ns[k - 1].i; }
  }
}
function nearestWhere(i, ok, span) { for (let d = 0; d <= span; d++) { if (ok(i + d)) return i + d; if (ok(i - d)) return i - d; } return i; }

function shape(base, level, o) {
  const polished = level === 'polished';
  let ns = base.map((n) => ({ i: n.i, b: n.b, l: n.l, raw: n.raw }));
  const cap = o.cap;
  // 1. merge repeated notes that are only a stutter
  const lim = polished ? 1 : 0.5;
  for (let k = ns.length - 1; k > 0; k--) if (ns[k].i === ns[k - 1].i && ns[k - 1].l <= lim && ns[k].b - (ns[k - 1].b + ns[k - 1].l) <= 0.5) { ns[k - 1].l = ns[k].b + ns[k].l - ns[k - 1].b; ns.splice(k, 1); }
  // 2. polished: few notes, keep the ones on beats
  if (polished) while (ns.length > 10) {
    let wi = -1, ws = 1e9;
    for (let k = 1; k < ns.length - 1; k++) { const sc = ns[k].l + (ns[k].b % 1 === 0 ? 0.6 : 0) + (ns[k].b % 2 === 0 ? 0.6 : 0); if (sc < ws) { ws = sc; wi = k; } }
    if (wi < 0) break;
    ns[wi - 1].l = ns[wi].b + ns[wi].l - ns[wi - 1].b; ns.splice(wi, 1);
  }
  // 3. leaps
  foldLeaps(ns, polished ? 8 : 9);
  // 4. very short: a question then an answer
  const end = () => ns[ns.length - 1].b + ns[ns.length - 1].l;
  if (ns.length >= 1 && (polished ? (end() < 8 || ns.length <= 3) : (end() < 4.5 || ns.length < 2))) {
    const P = ns.map((n) => ({ ...n }));
    const Q = P.map((n) => ({ ...n }));
    const lq = Q[Q.length - 1];
    const open = nearestWhere(lq.i, (x) => [1, 4].includes(mod(x, 7)), 3);
    lq.i = open; lq.l = Math.min(Math.max(lq.l, 1), 2);
    const span = Math.ceil((lq.b + lq.l) / 2) * 2;
    const A = P.map((n) => ({ ...n, b: n.b + span, i: n.i - 1, raw: null })); // the answer: the same shape one step down, then it closes below
    ns = Q.concat(A);
  }
  // 5. trim to the room the refrain gives
  ns = ns.filter((n) => n.b + 0.5 <= cap);
  ns.forEach((n) => { if (n.b + n.l > cap) n.l = cap - n.b; });
  if (!ns.length) return null;
  // 6. polished: strong beats take chord tones (one step at most)
  if (polished) ns.forEach((n, k) => {
    if (k >= ns.length - 1 || n.b % 2 !== 0 || isCT(n.i)) return;
    const cs = [n.i - 1, n.i + 1].filter(isCT); if (!cs.length) return;
    const pc = (x) => Math.abs(((x % 12) + 18) % 12 - 6);
    const prev = k ? ns[k - 1].i : null, next = ns[k + 1].i;
    const sc = (c) => (n.raw == null ? Math.abs(c - n.i) * 0.1 : pc(scaleMidi(c, o.key, o.mode) - n.raw)) + (c === prev || c === next ? 0.6 : 0);
    n.i = cs.sort((a, b) => sc(a) - sc(b))[0];
  });
  // 7. the phrase ends on the tonic or a chord tone, held
  const last = ns[ns.length - 1];
  if (polished) { const t = nearestWhere(last.i, (x) => mod(x, 7) === 0, 3); last.i = (Math.abs(t - last.i) <= 3) ? t : nearestWhere(last.i, isCT, 2); }
  else if (!isCT(last.i)) last.i = nearestWhere(last.i, isCT, 2);
  const want = polished ? 3 : 2;
  last.l = Math.max(last.l, Math.min(want, cap - last.b));
  if (polished) last.l = Math.min(Math.max(last.l, Math.ceil(last.b + last.l) - last.b), cap - last.b);
  foldLeaps(ns, polished ? 8 : 9);
  // 8. range
  const sh = medianIdxShift(ns, o.key, o.mode);
  ns.forEach((n) => { n.i += sh; });
  // 9. start at the first beat pair (keeps where on the bar he began)
  const lead = Math.floor(ns[0].b / 2) * 2;
  ns.forEach((n) => { n.b -= lead; });
  const total = ns[ns.length - 1].b + ns[ns.length - 1].l;
  return { v: 1, name: polished ? 'Polished' : 'Close', total, notes: ns.map((n) => ({ i: n.i, b: n.b, l: n.l })) };
}

// data: mono Float32Array of the take, starting at the first beat. S: the piece's settings.
export function buildTunes(data, sr, S, { cap } = {}) {
  const track = trackPitch(data, sr);
  const voiced = track.frames.filter((f) => f.voiced).length * track.hop;
  let raw = segmentNotes(track);
  if (voiced < 0.6 || raw.length < 1) return { error: 'No tune heard. Try again, a little louder.', track, raw };
  const off = tuningOffset(raw);
  raw.forEach((n) => { n.midi -= off; });
  const beat = 60 / S.bpm;
  const shift = gridShift(raw, beat / 2);
  const o = { bpm: S.bpm, key: S.key, mode: S.mode, shift, cap: cap || refrainCap(S.bpm) };
  const out = { track, raw, shift, tuning: off, tunes: {} };
  for (const [lv, minDur] of [['close', 0.1], ['polished', 0.2]]) {
    let r = raw.filter((n) => n.dur >= minDur);
    if (!r.length) r = raw.slice().sort((a, b) => b.dur - a.dur).slice(0, 1);
    const q = quantize(r, o);
    out.tunes[lv] = shape(q, lv, o);
  }
  if (!out.tunes.close || !out.tunes.polished) return { error: 'No tune heard. Try again, a little louder.', track, raw };
  return out;
}

// Tune to timed notes (for the preview). t in seconds from the start.
export function tuneEvents(tune, S) {
  const beat = 60 / S.bpm;
  return tune.notes.map((n, k) => {
    const nx = tune.notes[k + 1];
    const dur = (nx ? nx.b - n.b : n.l) * beat;
    return { t: n.b * beat, dur: dur * 0.98, midi: scaleMidi(n.i, S.key, S.mode), last: !nx };
  });
}
export { MODES };
