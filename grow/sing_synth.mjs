// Synthetic hums for the Sing checks: loose timing, out of tune, vibrato, scoops, breath noise.
import { mulberry32, scaleMidi } from './grow.js';

// notes: [{ i (scale step) or midi, beats }], returns { data, sr, truth: [{midi, t0, t1}] }
export function synthHum({ key, mode, bpm, steps, octave = -1, sr = 48000, lead = 0, tail = 1.5, seed = 7, flat = 0, vib = 28, jitter = 0.06, tuneErr = 20, blips = [], coughAt = null }) {
  const rnd = mulberry32(seed);
  const beat = 60 / bpm;
  const events = [];
  let b = 0;
  for (const s of steps) {
    const midi = (s.midi != null ? s.midi : scaleMidi(s.i, key, mode) + 12 * octave) + (flat / 100);
    events.push({ midi, t0: lead + b * beat + (rnd() * 2 - 1) * jitter, dur: s.beats * beat - 0.07, off: (rnd() * 2 - 1) * tuneErr / 100, truth: s });
    b += s.beats;
  }
  const total = lead + b * beat + tail;
  const data = new Float32Array(Math.ceil(total * sr));
  const render = (e, scoop = true, amp = 0.3) => {
    let ph = 0;
    const n0 = Math.floor(e.t0 * sr), n = Math.floor(e.dur * sr);
    for (let k = 0; k < n; k++) {
      const t = k / sr;
      const sc = scoop ? -1.6 * Math.max(0, 1 - t / 0.09) : 0;
      const v = Math.sin(2 * Math.PI * 5.6 * t) * (vib / 100) * Math.min(1, t / 0.2);
      const f = 440 * Math.pow(2, (e.midi + e.off + sc + v - 69) / 12);
      ph += 2 * Math.PI * f / sr;
      const env = Math.min(1, t / 0.04) * Math.min(1, (e.dur - t) / 0.06);
      let y = 0; for (let h = 1; h <= 5; h++) y += Math.sin(h * ph) / (h * h * 0.8 + 0.2);
      if (n0 + k < data.length) data[n0 + k] += y * env * amp * 0.6;
    }
  };
  events.forEach((e) => render(e));
  for (const bl of blips) render({ midi: bl.midi, t0: bl.t, dur: bl.dur, off: 0 }, false, 0.25);
  if (coughAt != null) for (let k = 0; k < 0.1 * sr; k++) data[Math.floor(coughAt * sr) + k] += (rnd() * 2 - 1) * 0.25;
  for (let k = 0; k < data.length; k++) data[k] += (rnd() * 2 - 1) * 0.002;
  return { data, sr, events, total };
}

export function wavBytes(data, sr) {
  const b = Buffer.alloc(44 + data.length * 2);
  b.write('RIFF', 0); b.writeUInt32LE(36 + data.length * 2, 4); b.write('WAVEfmt ', 8);
  b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(sr, 24); b.writeUInt32LE(sr * 2, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34);
  b.write('data', 36); b.writeUInt32LE(data.length * 2, 40);
  for (let i = 0; i < data.length; i++) b.writeInt16LE(Math.round(Math.max(-1, Math.min(1, data[i])) * 32767), 44 + i * 2);
  return b;
}
