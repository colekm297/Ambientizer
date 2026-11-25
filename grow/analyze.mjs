import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { plan, WORLDS, defaultSettings } from './grow.js';
const worlds = Object.keys(WORLDS);
const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, '0')}`;
function fft(re, im) { const n = re.length; for (let i = 1, j = 0; i < n; i++) { let b = n >> 1; for (; j & b; b >>= 1) j ^= b; j ^= b; if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; } }
  for (let len = 2; len <= n; len <<= 1) { const a = -2 * Math.PI / len, wr = Math.cos(a), wi = Math.sin(a); for (let i = 0; i < n; i += len) { let cr = 1, ci = 0; for (let k = 0; k < len / 2; k++) { const ur = re[i + k], ui = im[i + k], vr = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci, vi = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr; re[i + k] = ur + vr; im[i + k] = ui + vi; re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi; const t = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = t; } } } }
for (const w of worlds) {
  const f = `renders/${w.replace(/ /g, '_').toLowerCase()}_600.wav`;
  if (!fs.existsSync(f)) { console.log('missing', f); continue; }
  const buf = fs.readFileSync(f); const sr = 48000;
  const n = (buf.length - 44) / 4; const L = new Float32Array(n), R = new Float32Array(n);
  let peak = 0, clip = 0;
  for (let i = 0; i < n; i++) { const l = buf.readInt16LE(44 + 4 * i), r = buf.readInt16LE(46 + 4 * i); L[i] = l / 32768; R[i] = r / 32768; const a = Math.max(Math.abs(l), Math.abs(r)); if (a > peak) peak = a; if (a >= 32767) clip++; }
  const r = spawnSyncStderr(f);
  const lufs = /I:\s+(-?[\d.]+) LUFS/.exec(r.slice(r.lastIndexOf('Summary'))), tp = /Peak:\s+(-?[\d.]+) dBFS/.exec(r.slice(r.lastIndexOf('True peak')));
  console.log(`\n== ${w}: peak ${(20 * Math.log10(peak / 32768)).toFixed(2)} dBFS (sample), clipped samples ${clip}, integrated ${lufs && lufs[1]} LUFS, true peak ${tp && tp[1]} dBFS`);
  const step = 5, N = 2048; const rms = [], cen = [];
  for (let t = 0; t + step <= n / sr; t += step) {
    let s = 0; const a0 = t * sr; for (let i = a0; i < a0 + step * sr; i++) { const m = (L[i] + R[i]) / 2; s += m * m; }
    rms.push(20 * Math.log10(Math.sqrt(s / (step * sr)) + 1e-9));
    let cs = 0, ws = 0;
    for (let k = 0; k < 4; k++) { const o = Math.floor(a0 + (k + 0.5) * step * sr / 4); const re = new Float64Array(N), im = new Float64Array(N); for (let i = 0; i < N; i++) re[i] = (L[o + i] + R[o + i]) / 2 * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / N)); fft(re, im); for (let b = 1; b < N / 2; b++) { const m = Math.hypot(re[b], im[b]); cs += m * b * sr / N; ws += m; } }
    cen.push(cs / ws);
  }
  const S = Object.assign(defaultSettings(w), { length: 600 }); const P = plan(S);
  const mean = (a, i0, i1) => { const x = a.slice(Math.max(0, Math.floor(i0 / step)), Math.floor(i1 / step)); return x.reduce((p, c) => p + c, 0) / x.length; };
  console.log('refrain   RMS in / minute before (dB)   centroid in / before (Hz)   up?');
  P.refrains.forEach((rf) => { const ri = mean(rms, rf.start, rf.end), rb = mean(rms, rf.start - 60, rf.start), ci = mean(cen, rf.start, rf.end), cb = mean(cen, rf.start - 60, rf.start); console.log(`${fmt(rf.start)}  ${ri.toFixed(1)} / ${rb.toFixed(1)}  (${(ri - rb >= 0 ? '+' : '') + (ri - rb).toFixed(1)})   ${ci.toFixed(0)} / ${cb.toFixed(0)}  (${((ci / cb - 1) * 100).toFixed(0)}%)   ${ri - rb >= 3 ? 'RMS up' : ci / cb > 1.25 ? 'centroid up' : 'WEAK'}`); });
  let flat = 0, worst = 0, c = 0; for (let i = 1; i < rms.length; i++) { if (Math.abs(rms[i] - rms[i - 1]) < 0.6 && Math.abs(rms[i] - rms[Math.max(0, i - 24)]) < 2.5) { c++; worst = Math.max(worst, c * step); } else c = 0; }
  console.log('RMS range', Math.min(...rms).toFixed(1), 'to', Math.max(...rms).toFixed(1), 'dB; longest flat stretch ~', worst, 's');
  console.log('RMS per 20 s:', rms.filter((_, i) => i % 4 === 0).map((x) => x.toFixed(0)).join(' '));
  console.log('centroid per 20 s:', cen.filter((_, i) => i % 4 === 0).map((x) => Math.round(x)).join(' '));
  // clicks: max sample-to-sample jump at segment joins (every 120 s) vs typical
  const jumps = []; for (const j of [120, 240, 360, 480]) { const i = j * sr; jumps.push(Math.abs(L[i] - L[i - 1]).toFixed(4)); }
  { const win = Math.round(0.006 * sr); const d2 = (i0) => { let m = 0; for (let i = i0 + 2; i < i0 + win; i++) m = Math.max(m, Math.abs(L[i] - 2 * L[i - 1] + L[i - 2])); return m; };
    const all = []; for (let i = sr; i + win < n; i += Math.round(sr * 0.37)) all.push(d2(i)); all.sort((x, y) => x - y);
    const p99 = all[Math.floor(all.length * 0.99)], mx = all[all.length - 1];
    const js = [120, 240, 360, 480].map((j) => Math.max(d2(j * sr - win), d2(j * sr - Math.floor(win / 2))));
    console.log('click check (max 2nd difference in 6 ms around each join): ' + js.map((x) => x.toFixed(4)).join(' ') + ' | elsewhere p99 ' + p99.toFixed(4) + ', max ' + mx.toFixed(4) + (Math.max(...js) <= mx ? '  joins are within normal range' : '  JOIN ABOVE NORMAL')); }
  let mj = 0; for (let i = 1; i < n; i++) mj = Math.max(mj, Math.abs(L[i] - L[i - 1])); console.log('join jumps', jumps.join(' '), ' max jump anywhere', mj.toFixed(4));
}
function spawnSyncStderr(f) { try { return execFileSync('sh', ['-c', `ffmpeg -hide_banner -nostats -i '${f}' -af ebur128=peak=true -f null - 2>&1`], { encoding: 'utf8', maxBuffer: 1 << 28 }); } catch (e) { return String(e.stdout || ''); } }
