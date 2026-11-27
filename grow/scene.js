// Scene: a code-drawn matte painting of one world ("Arrakis, last light") that animates under a Grow piece.
// Shapes are drawn once into cached layers. Only light, sand, haze and stars move, locally. Cliff and dunes never move.
import { Kit, Player, defaultSettings, mulberry32 } from './grow.js';
import { createAsk } from './scene_ask.js';

const W = 1280, H = 720;
const $ = (s) => document.querySelector(s);
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const lerp = (a, b, t) => a + (b - a) * t;
const sm = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const mixC = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
const rgba = (c, a = 1) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${+a.toFixed(3)})`;
const safe = (fn, fb) => { try { return fn(); } catch (e) { return fb; } };
const fmt = (t) => { t = Math.max(0, Math.round(t)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
const hash = (k, s) => { const v = Math.sin(k * 127.1 + s * 311.7) * 43758.5453; return v - Math.floor(v); };
const mk = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };

// ------------------------------------------------------------ palette (late afternoon, dusk, deep dusk)
const STOPS = [
  { top: [92, 106, 170], mid: [206, 150, 160], hor: [252, 204, 140], sun: [255, 236, 190], sun2: [255, 200, 156], glow: [255, 186, 108], far: [168, 132, 158], cliff: [106, 62, 74], lit: [240, 152, 98], near: [92, 50, 60], haze: [246, 196, 152], rim: [255, 208, 140], shade: [70, 44, 88] },
  { top: [46, 48, 112], mid: [140, 82, 134], hor: [240, 134, 104], sun: [255, 200, 142], sun2: [255, 154, 132], glow: [250, 128, 90], far: [112, 82, 132], cliff: [58, 36, 70], lit: [200, 106, 94], near: [46, 28, 54], haze: [198, 114, 126], rim: [255, 158, 106], shade: [38, 26, 70] },
  { top: [10, 12, 40], mid: [36, 30, 82], hor: [134, 70, 114], sun: [248, 140, 116], sun2: [228, 102, 122], glow: [208, 84, 106], far: [46, 38, 80], cliff: [20, 16, 42], lit: [118, 62, 94], near: [16, 12, 32], haze: [94, 60, 114], rim: [228, 120, 116], shade: [14, 10, 36] },
];
function palette(t) {
  const a = t < 0.5 ? STOPS[0] : STOPS[1], b = t < 0.5 ? STOPS[1] : STOPS[2];
  const u = sm(0, 1, (t < 0.5 ? t : t - 0.5) * 2);
  const P = {};
  for (const k in a) P[k] = mixC(a[k], b[k], u);
  P.night = sm(0.45, 0.95, t);
  return P;
}
const timeName = (t) => (t < 0.28 ? 'Afternoon' : t < 0.62 ? 'Dusk' : 'Deep dusk');

// ------------------------------------------------------------ noise and ridge profiles
function noise1(seed) {
  const r = mulberry32(seed >>> 0), v = new Float32Array(512);
  for (let i = 0; i < 512; i++) v[i] = r();
  return (x) => { const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f); return lerp(v[i & 511], v[(i + 1) & 511], u); };
}
function fbm(n, x, o = 4) {
  let s = 0, a = 0.5, f = 1, tot = 0;
  for (let i = 0; i < o; i++) { s += a * n(x * f + i * 17.3); tot += a; a *= 0.5; f *= 2.03; }
  return s / tot;
}
function duneTrain(n, x, f, seed, pk, sharp) {
  const u = x * f + 2.2 * fbm(n, x * f * 0.3, 3), k = Math.floor(u), p = u - k;
  const a = 0.38 + 0.62 * hash(k, seed), pkk = clamp(pk + (hash(k, seed + 5) - 0.5) * 0.14, 0.14, 0.6);
  const q = p < pkk ? p / pkk : (1 - p) / (1 - pkk);
  return (sharp ? Math.pow(q, 1.55) : q * q * (3 - 2 * q)) * a;
}
function ridgeYs(o) {
  const n = noise1(o.seed), n2 = noise1(o.seed + 99);
  const N = Math.ceil((o.x1 - o.x0) / o.step) + 1, ys = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    const x = o.x0 + i * o.step;
    let h;
    if (o.kind === 'saw') {
      // three dune trains of unrelated spacing; the larger two meet at a soft maximum, so crests pass behind one another
      const A = duneTrain(n, x, o.freq, o.seed, o.peak ?? 0.3, o.sharp), B = duneTrain(n2, x + 913, o.freq * 1.63, o.seed + 17, (o.peak ?? 0.3) * 0.9, o.sharp) * 0.6, C = duneTrain(n, x + 311, o.freq * 2.9, o.seed + 41, 0.36, false);
      h = 0.5 * (A + B + Math.sqrt((A - B) * (A - B) + 0.0016)) + C * 0.08 * (0.3 + 0.7 * A);
      h += (fbm(n2, x * 0.02, 3) - 0.5) * 0.12 + (fbm(n, x * 0.09 + 50, 2) - 0.5) * 0.03;
    } else if (o.kind === 'mesa') {
      const v = fbm(n, x * o.freq, 3);
      h = sm(0.46, 0.54, v) * 0.6 + sm(0.6, 0.68, v) * 0.4 + (fbm(n2, x * 0.03, 2) - 0.5) * 0.04;
    } else {
      h = (fbm(n, x * o.freq, 4) - 0.2) * 1.5 + (n2(x * 0.011) - 0.5) * 0.12;
    }
    ys[i] = o.base - o.amp * h;
  }
  return ys;
}
const shadeTmp = mk(2.4 * W + 8, 1.6 * H);
const stripCache = new Map();
function strip(col) {
  const key = col.map((v) => v | 0).join();
  if (stripCache.has(key)) return stripCache.get(key);
  const c = mk(1, 64), x = c.getContext('2d'), g = x.createLinearGradient(0, 0, 0, 64);
  g.addColorStop(0, rgba(col, 1)); g.addColorStop(0.35, rgba(col, 0.42)); g.addColorStop(1, rgba(col, 0));
  x.fillStyle = g; x.fillRect(0, 0, 1, 64);
  if (stripCache.size > 40) stripCache.clear();
  stripCache.set(key, c); return c;
}

// ------------------------------------------------------------ fx: noise plate, sky scattering, air light
// One tileable fbm plate feeds every per-pixel pass, so nothing calls noise per pixel. v is the full five octaves
// (largest feature 64 texels), s is the two largest octaves only, for smooth warps and slopes; g* are their differences.
const TEX = 512, TM = TEX - 1;
const tex = (() => {
  const r = mulberry32(90210), lat = new Float32Array(65536 + 64), v = new Float32Array(TEX * TEX), gx = new Float32Array(TEX * TEX), gy = new Float32Array(TEX * TEX), s = new Float32Array(TEX * TEX), sgx = new Float32Array(TEX * TEX), sgy = new Float32Array(TEX * TEX), rnd = new Uint8Array(65536);
  for (let i = 0; i < lat.length; i++) lat[i] = r();
  for (let i = 0; i < 65536; i++) rnd[i] = (r() * 256) | 0;
  let amp = 0.5, tot = 0;
  for (let o = 0, cells = 8; o < 5; o++, cells *= 2, amp *= 0.5) {
    tot += amp; const k = cells / TEX, sh = o * 11;
    for (let y = 0; y < TEX; y++) {
      const fy = y * k, iy = Math.floor(fy), ty = fy - iy, uy = ty * ty * (3 - 2 * ty), y0 = (iy % cells) * 256 + sh, y1 = ((iy + 1) % cells) * 256 + sh;
      for (let x = 0; x < TEX; x++) {
        const fx = x * k, ix = Math.floor(fx), t = fx - ix, ux = t * t * (3 - 2 * t), x0 = ix % cells, x1 = (ix + 1) % cells;
        const a = lat[y0 + x0], b = lat[y0 + x1], c = lat[y1 + x0], d = lat[y1 + x1];
        v[y * TEX + x] += amp * (a + (b - a) * ux + (c - a + (a - b - c + d) * ux) * uy);
      }
    }
    if (o === 1) for (let i = 0; i < v.length; i++) s[i] = v[i] / tot;
  }
  for (let i = 0; i < v.length; i++) v[i] /= tot;
  for (let y = 0; y < TEX; y++) for (let x = 0; x < TEX; x++) {
    gx[y * TEX + x] = v[y * TEX + ((x + 1) & TM)] - v[y * TEX + ((x - 1) & TM)];
    gy[y * TEX + x] = v[((y + 1) & TM) * TEX + x] - v[((y - 1) & TM) * TEX + x];
    sgx[y * TEX + x] = s[y * TEX + ((x + 1) & TM)] - s[y * TEX + ((x - 1) & TM)];
    sgy[y * TEX + x] = s[((y + 1) & TM) * TEX + x] - s[((y - 1) & TM) * TEX + x];
  }
  return { v, gx, gy, s, sgx, sgy, rnd };
})();
function tx2(a, u, v) {
  const iu = Math.floor(u), iv = Math.floor(v), fu = u - iu, fv = v - iv, x0 = iu & TM, x1 = (iu + 1) & TM, y0 = (iv & TM) * TEX, y1 = ((iv + 1) & TM) * TEX;
  const p = a[y0 + x0], q = a[y1 + x0];
  return p + (a[y0 + x1] - p) * fu + (q + (a[y1 + x1] - q) * fu - p - (a[y0 + x1] - p) * fu) * fv;
}
function blur2(a, w, h, r, passes) {
  const t = new Float32Array(a.length), k = 1 / (2 * r + 1);
  for (let p = 0; p < passes; p++) {
    for (let y = 0; y < h; y++) { const o = y * w; let s = 0; for (let i = -r; i <= r; i++) s += a[o + clamp(i, 0, w - 1)]; for (let x = 0; x < w; x++) { t[o + x] = s * k; s += a[o + Math.min(w - 1, x + r + 1)] - a[o + Math.max(0, x - r)]; } }
    for (let x = 0; x < w; x++) { let s = 0; for (let i = -r; i <= r; i++) s += t[clamp(i, 0, h - 1) * w + x]; for (let y = 0; y < h; y++) { a[y * w + x] = s * k; s += t[Math.min(h - 1, y + r + 1) * w + x] - t[Math.max(0, y - r) * w + x]; } }
  }
}

// Dusk sky. Two vertical ramps (looking toward the sun, and away from it) stand in for Rayleigh scattering through a long
// air path: dusty peach at the horizon, rose above it, blue-violet overhead, with the away side cooler (the rose belt
// opposite a low sun). On top, forward (Mie) scatter: a tight aureole and a wide glow that hugs the horizon.
const HORIZON = 0.66 * H;
const sky = { sun: new Float32Array(768), anti: new Float32Array(768), m: { s: 1, e: 0, f: 0 }, gl: 0.6, glow: [0, 0, 0], core: [0, 0, 0], air: new Float32Array(W * 3), cool: [0, 0, 0] };
function skyRamp(out, stops) {
  const tmp = new Float32Array(768);
  for (let i = 0; i < 256; i++) {
    const h = -0.1 + 1.2 * i / 255; let k = 0; while (k < stops.length - 2 && h > stops[k + 1][0]) k++;
    const a = stops[k], b = stops[k + 1], u = clamp((h - a[0]) / (b[0] - a[0]), 0, 1);
    for (let c = 0; c < 3; c++) tmp[i * 3 + c] = lerp(a[1][c], b[1][c], u);
  }
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 0; i < 256; i++) for (let c = 0; c < 3; c++) { let s = 0; for (let j = -6; j <= 6; j++) s += tmp[clamp(i + j, 0, 255) * 3 + c]; out[i * 3 + c] = s / 13; }
    tmp.set(out);
  }
}
function skyPrep(P) {
  sky.m = mat('sky'); sky.gl = st.layers.suns.show ? st.layers.suns.v.glow : 0.25;
  const zen = [P.top[0] * 0.68, P.top[1] * 0.66, P.top[2] * 0.9], day = 1 - P.night;
  const dust = mixC(mixC(P.hor, P.haze, 0.28), [255, 226, 190], 0.14 * day), rose = mixC(mixC(P.hor, P.mid, 0.58), [255, 150, 160], 0.1 * day);
  skyRamp(sky.sun, [[-0.1, dust], [0, dust], [0.07, P.hor], [0.2, rose], [0.4, P.mid], [0.63, mixC(P.mid, P.top, 0.7)], [0.86, P.top], [1.1, zen]]);
  const a0 = mixC(dust, P.shade, 0.14);
  skyRamp(sky.anti, [[-0.1, a0], [0, a0], [0.06, mixC(P.hor, P.mid, 0.45)], [0.17, mixC(P.hor, P.mid, 0.85)], [0.36, mixC(P.mid, P.top, 0.4)], [0.58, mixC(P.mid, P.top, 0.85)], [0.84, P.top], [1.1, zen]]);
  sky.glow = P.glow; sky.core = mixC(P.glow, P.sun, 0.7); sky.cool = mixC(mixC(P.top, P.haze, 0.42), P.far, 0.25);
  const o = [0, 0, 0], y = sky.m.f + sky.m.s * HORIZON * 0.965;
  for (let x = 0; x < W; x++) { skyRGB(x, y, o); sky.air[x * 3] = o[0]; sky.air[x * 3 + 1] = o[1]; sky.air[x * 3 + 2] = o[2]; }
}
function skyRGB(px, py, o) {
  const m = sky.m, h = (HORIZON - (py - m.f) / m.s) / HORIZON;
  const fi = clamp((h + 0.1) / 1.2, 0, 1) * 255, i0 = Math.min(254, fi | 0), u = fi - i0, a = i0 * 3, A0 = sky.anti, S0 = sky.sun;
  let az = 0, m1 = 0, m2 = 0;
  for (let k = 0; k < geo.suns.length; k++) {
    const s = geo.suns[k], dx = (px - s.x) / H, dy = (py - s.y) / H, r0 = (s.r / H) * 1.7 + 0.01;
    az = Math.max(az, s.g * (0.3 + 0.7 * Math.exp(-dx * dx / 1.2)));
    m1 += s.g / (1 + (dx * dx + dy * dy) / (r0 * r0));
    m2 += s.g * Math.exp(-Math.sqrt(dx * dx + dy * dy * 2.9) / 0.42);
  }
  const low = 0.28 + 0.72 * Math.exp(-Math.max(h, 0) / 0.2), g = 0.45 + sky.gl;
  const A = Math.min(0.85, 0.62 * m2 * low * g), B = Math.min(0.9, 0.4 * m1 * g);
  for (let c = 0; c < 3; c++) {
    const an = A0[a + c] + (A0[a + 3 + c] - A0[a + c]) * u, sn = S0[a + c] + (S0[a + 3 + c] - S0[a + c]) * u;
    let v = an + (sn - an) * az; v += (sky.glow[c] - v) * A; v += (sky.core[c] - v) * B; o[c] = v;
  }
}
// colour of the air a layer fades into, per column: the sky at the horizon behind it, cooler away from the sun
function airGradient(ctx, cool) {
  const g = ctx.createLinearGradient(0, 0, W, 0), S = geo.suns[0];
  for (let i = 0; i <= 10; i++) {
    const x = Math.min(W - 1, Math.round(i / 10 * (W - 1))), dx = S ? (x - S.x) / H : 9, k = cool * (1 - 0.8 * Math.exp(-dx * dx / 0.5));
    g.addColorStop(i / 10, rgba(mixC([sky.air[x * 3], sky.air[x * 3 + 1], sky.air[x * 3 + 2]], sky.cool, k)));
  }
  return g;
}
// sun bloom: a sharp core, a soft shoulder and a long faint tail, dithered so the tail does not band
function makeBloom(c, col) {
  const n = c.width, x = c.getContext('2d'), img = x.createImageData(n, n), d = img.data, hf = n / 2, dr = mulberry32(99), T = new Float32Array(513);
  for (let i = 0; i <= 512; i++) { const r = i / 512; T[i] = Math.min(1, (0.8 / (1 + (r / 0.05) * (r / 0.05)) + 0.42 * Math.exp(-r / 0.11) + 0.12 * Math.exp(-r / 0.36)) * (1 - r) * (1 - r)) * 255; }
  for (let y = 0, i = 0; y < n; y++) for (let xx = 0; xx < n; xx++, i += 4) {
    const dx = xx + 0.5 - hf, dy = y + 0.5 - hf, r = Math.sqrt(dx * dx + dy * dy) / hf; if (r >= 1) continue;
    const f = r * 512, k = f | 0;
    d[i] = col[0]; d[i + 1] = col[1]; d[i + 2] = col[2]; d[i + 3] = T[k] + (T[k + 1] - T[k]) * (f - k) + dr() - 0.5;
  }
  x.putImageData(img, 0, 0);
}

// ------------------------------------------------------------ state
const ANCH = { sky: [W / 2, H / 2], suns: [0.76 * W, 0.55 * H], far: [W / 2, 0.66 * H], cliff: [W / 2, 0.74 * H], near: [W / 2, H], air: [W / 2, H / 2] };
const LAYERS = [
  { id: 'sky', name: 'Sky', looks: ['Clear', 'Streaks', 'Clouds'], sliders: [{ id: 'clouds', label: 'Clouds', def: 0.55 }, { id: 'stars', label: 'Stars', def: 0.65 }] },
  { id: 'suns', name: 'Suns', looks: ['Twin', 'Single', 'Pair'], sliders: [{ id: 'size', label: 'Size', def: 0.5 }, { id: 'glow', label: 'Glow', def: 0.6 }] },
  { id: 'far', name: 'Far', looks: ['Ridges', 'Mesas', 'Dunes'], sliders: [{ id: 'height', label: 'Height', def: 0.5 }, { id: 'haze', label: 'Haze', def: 0.5 }] },
  { id: 'cliff', name: 'Cliff', looks: ['Mesa', 'Spire', 'Broken'], sliders: [{ id: 'height', label: 'Height', def: 0.5 }, { id: 'width', label: 'Width', def: 0.5 }, { id: 'strata', label: 'Strata', def: 0.55 }] },
  { id: 'near', name: 'Near', looks: ['Rolling', 'Sharp', 'Flat'], sliders: [{ id: 'height', label: 'Height', def: 0.5 }, { id: 'ripples', label: 'Ripples', def: 0.5 }] },
  { id: 'air', name: 'Air', looks: ['Sand', 'Haze', 'Dust'], sliders: [{ id: 'amount', label: 'Amount', def: 0.5 }, { id: 'wind', label: 'Wind', def: 0.5 }] },
];
const LOOK0 = { sky: 1, suns: 0, far: 0, cliff: 0, near: 0, air: 0 };
function defaultState() {
  const layers = {};
  for (const L of LAYERS) {
    layers[L.id] = { show: true, look: LOOK0[L.id], x: 0, y: 0, s: 1, op: 1, tint: 0.6, v: Object.fromEntries(L.sliders.map((s) => [s.id, s.def])) };
  }
  return { time: 0.3, seed: 20261124, layer: 'sky', layers, custom: [] };
}
let st = defaultState();
safe(() => {
  const saved = JSON.parse(localStorage.getItem('scene.current'));
  if (!saved) return;
  st.time = clamp(+saved.time || st.time, 0, 1); st.seed = (+saved.seed >>> 0) || st.seed;
  if (saved.layer && st.layers[saved.layer]) st.layer = saved.layer;
  for (const id in st.layers) {
    const a = st.layers[id], b = saved.layers && saved.layers[id]; if (!b) continue;
    a.show = b.show !== false;
    for (const k of ['look', 'x', 's', 'y', 'op', 'tint']) if (typeof b[k] === 'number') a[k] = b[k];
    Object.assign(a.v, b.v || {});
  }
  if (Array.isArray(saved.custom)) st.custom = saved.custom.filter((c) => c && typeof c.code === 'string' && c.box && typeof c.mask === 'string' && Array.isArray(c.params)).slice(0, 12).map((c) => ({ id: String(c.id), name: String(c.name || 'Element').slice(0, 24), show: c.show !== false, z: clamp(Math.round(+c.z), 0, 5) || 0, op: clamp(+c.op, 0, 1), request: String(c.request || ''), code: c.code, params: c.params, box: c.box, mask: c.mask }));
});
const persist = () => safe(() => localStorage.setItem('scene.current', JSON.stringify(st)));
const layerDef = (id) => LAYERS.find((l) => l.id === id);
const lseed = (id) => ((st.seed * 7 + LAYERS.findIndex((l) => l.id === id) * 1013) >>> 0);
const mat = (id) => { const L = st.layers[id], [ax, ay] = ANCH[id], s = L.s; return { s, e: ax * (1 - s) + L.x * W, f: ay * (1 - s) + L.y * H }; };
const setT = (ctx, m) => ctx.setTransform(m.s, 0, 0, m.s, m.e, m.f);

// ------------------------------------------------------------ photos (IndexedDB "scene")
const photos = {}; // layer -> { img, name }
const DB = 'scene', STORE = 'photos';
const idb = () => new Promise((res, rej) => { const r = indexedDB.open(DB, 1); r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: 'layer' }); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
const idbPut = async (rec) => { const d = await idb(); return new Promise((res, rej) => { const t = d.transaction(STORE, 'readwrite'); t.objectStore(STORE).put(rec); t.oncomplete = res; t.onerror = () => rej(t.error); }); };
const idbDel = async (k) => { const d = await idb(); return new Promise((res) => { const t = d.transaction(STORE, 'readwrite'); t.objectStore(STORE).delete(k); t.oncomplete = res; }); };
const idbAll = async () => { const d = await idb(); return new Promise((res) => { const q = d.transaction(STORE).objectStore(STORE).getAll(); q.onsuccess = () => res(q.result); q.onerror = () => res([]); }); };
const imgFromBlob = (blob) => new Promise((res, rej) => { const u = URL.createObjectURL(blob), im = new Image(); im.onload = () => res(im); im.onerror = () => rej(new Error('image')); im.src = u; });
async function importPhoto(id, file) {
  const im = await imgFromBlob(file);
  const k = Math.min(1, 2400 / Math.max(im.naturalWidth, im.naturalHeight));
  const c = mk(Math.round(im.naturalWidth * k), Math.round(im.naturalHeight * k));
  c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
  const png = file.type === 'image/png';
  const blob = await new Promise((r) => c.toBlob(r, png ? 'image/png' : 'image/jpeg', 0.92));
  await idbPut({ layer: id, blob, name: file.name || 'Photo' });
  photos[id] = { img: c, name: file.name || 'Photo' };
  const L = st.layers[id]; L.look = layerDef(id).looks.length; // Photo look
  persist(); photoRev++; dirty = true; buildPanel();
}
async function removePhoto(id) {
  delete photos[id]; await idbDel(id).catch(() => {});
  const L = st.layers[id]; if (L.look >= layerDef(id).looks.length) L.look = 0;
  persist(); photoRev++; dirty = true; buildPanel();
}
async function loadPhotos() {
  const all = await idbAll();
  for (const rec of all) { try { photos[rec.layer] = { img: await imgFromBlob(rec.blob), name: rec.name }; } catch (e) {} }
  photoRev++; dirty = true; buildPanel();
}

// ------------------------------------------------------------ caches
const cache = {
  sky: mk(W, H), suns: mk(W, H), air: mk(W, H),
  far: mk(W, H), farRim: mk(W, H), cliff: mk(W, H), cliffRim: mk(W, H), near: mk(W, H), nearRim: mk(W, H),
  hazeA: mk(1536, 300), hazeB: mk(1536, 200),
  skyLo: mk(W / 4, H / 4), plate: mk(W, H), low: mk(W / 4, H / 4), back: mk(W, H), bloom: [mk(256, 256), mk(256, 256)],
};
const geo = { P: palette(0.3), suns: [], stars: [], topFar: new Float32Array(W / 4 + 2).fill(H), topNear: new Float32Array(W / 4 + 2).fill(H), peakFar: new Float32Array(W / 4 + 2), peakNear: new Float32Array(W / 4 + 2), cliffPoly: null };
let dirty = true;

function photoOf(id) { const L = st.layers[id]; return photos[id] && L.look >= layerDef(id).looks.length; }
function drawPhoto(ctx, id, m) {
  const ph = photos[id]; if (!ph) return;
  const L = st.layers[id], im = ph.img, iw = im.width, ih = im.height;
  let w, h, x, y;
  if (id === 'sky' || id === 'air') { const k = Math.max(W / iw, H / ih); w = iw * k; h = ih * k; x = (W - w) / 2; y = (H - h) / 2; }
  else if (id === 'suns') { w = W * 0.6; h = w * ih / iw; x = ANCH.suns[0] - w / 2; y = ANCH.suns[1] - h / 2; }
  else { w = W; h = w * ih / iw; x = 0; y = ANCH[id][1] - h; }
  const t = mk(W, H), tx = t.getContext('2d');
  tx.setTransform(m.s, 0, 0, m.s, m.e, m.f); tx.drawImage(im, x, y, w, h); tx.setTransform(1, 0, 0, 1, 0, 0);
  if (id === 'sky' && L.tint > 0.01) {
    const P = geo.P, g = tx.createLinearGradient(0, 0, 0, H * 0.72);
    g.addColorStop(0, rgba(P.top)); g.addColorStop(0.5, rgba(P.mid)); g.addColorStop(0.9, rgba(P.hor));
    tx.globalCompositeOperation = 'source-atop'; tx.globalAlpha = L.tint * 0.55; tx.fillStyle = g; tx.fillRect(0, 0, W, H);
    tx.globalCompositeOperation = 'soft-light'; tx.globalAlpha = L.tint; tx.fillRect(0, 0, W, H);
  }
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = L.op; ctx.drawImage(t, 0, 0); ctx.restore();
}

// ------------------------------------------------------------ sun geometry
function computeSuns(P) {
  const L = st.layers.suns, look = L.look, m = mat('suns'), size = L.v.size;
  const y0 = lerp(0.43, 0.64, sm(0, 1, st.time)) * H;
  const R = (16 + 34 * size);
  let list;
  if (look === 1 || look >= 3) list = [{ x: 0.72 * W, y: y0, r: R * 1.15, col: P.sun, g: 1 }];
  else if (look === 2) list = [{ x: 0.69 * W, y: y0, r: R * 0.9, col: P.sun, g: 0.9 }, { x: 0.775 * W, y: y0 + 0.012 * H, r: R * 0.85, col: P.sun2, g: 0.9 }];
  else list = [{ x: 0.70 * W, y: y0, r: R * 1.1, col: P.sun, g: 1 }, { x: 0.845 * W, y: y0 + 0.052 * H, r: R * 0.52, col: P.sun2, g: 0.8 }];
  geo.suns = list.map((s) => ({ ...s, x: m.s * s.x + m.e, y: m.s * s.y + m.f, r: s.r * m.s }));
}
function litAt(wx, wy, nx, ny) {
  const S = geo.suns[0]; if (!S) return 0;
  const dx = S.x - wx, dy = S.y - wy, d = Math.hypot(dx, dy) || 1;
  return (nx * dx + ny * dy) / d;
}

// ------------------------------------------------------------ layer drawing
function drawSky(ctx, P, L, seed, m) {
  // scattering plate at quarter size (it is smooth, so it scales up cleanly), dithered against banding.
  // Same maths as skyRGB, with everything that only depends on the row or the column lifted out of the pixel loop.
  const lo = cache.skyLo, w = lo.width, h = lo.height, lx = lo.getContext('2d'), img = lx.createImageData(w, h), d = img.data, o = [0, 0, 0], dr = mulberry32(4711);
  const sc = W / w, ns = geo.suns.length, g = 0.45 + sky.gl, A0 = sky.anti, S0 = sky.sun, gw = sky.glow, cr = sky.core;
  const azT = new Float32Array(w), dx2 = new Float32Array(w * 2);
  for (let x = 0; x < w; x++) for (let k = 0; k < ns; k++) { const s = geo.suns[k], dx = ((x + 0.5) * sc - s.x) / H; dx2[x * 2 + k] = dx * dx; azT[x] = Math.max(azT[x], s.g * (0.3 + 0.7 * Math.exp(-dx * dx / 1.2))); }
  for (let y = 0, i = 0; y < h; y++) {
    const py = (y + 0.5) * sc, hh = (HORIZON - (py - m.f) / m.s) / HORIZON, fi = clamp((hh + 0.1) / 1.2, 0, 1) * 255, i0 = Math.min(254, fi | 0), u = fi - i0, a = i0 * 3;
    const low = (0.28 + 0.72 * Math.exp(-Math.max(hh, 0) / 0.2)) * 0.62 * g;
    const a0 = A0[a] + (A0[a + 3] - A0[a]) * u, a1 = A0[a + 1] + (A0[a + 4] - A0[a + 1]) * u, a2 = A0[a + 2] + (A0[a + 5] - A0[a + 2]) * u;
    const s0 = S0[a] + (S0[a + 3] - S0[a]) * u - a0, s1 = S0[a + 1] + (S0[a + 4] - S0[a + 1]) * u - a1, s2 = S0[a + 2] + (S0[a + 5] - S0[a + 2]) * u - a2;
    for (let x = 0; x < w; x++, i += 4) {
      let m1 = 0, m2 = 0;
      for (let k = 0; k < ns; k++) { const s = geo.suns[k], dy = (py - s.y) / H, r0 = (s.r / H) * 1.7 + 0.01, xx = dx2[x * 2 + k]; m1 += s.g / (1 + (xx + dy * dy) / (r0 * r0)); m2 += s.g * Math.exp(-Math.sqrt(xx + dy * dy * 2.9) / 0.42); }
      const az = azT[x], A = Math.min(0.85, m2 * low), B = Math.min(0.9, 0.4 * m1 * g), dz = dr() - 0.5;
      let v = a0 + s0 * az; v += (gw[0] - v) * A; v += (cr[0] - v) * B; d[i] = v + dz;
      v = a1 + s1 * az; v += (gw[1] - v) * A; v += (cr[1] - v) * B; d[i + 1] = v + dz;
      v = a2 + s2 * az; v += (gw[2] - v) * A; v += (cr[2] - v) * B; d[i + 2] = v + dz; d[i + 3] = 255;
    }
  }
  lx.putImageData(img, 0, 0);
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high'; ctx.drawImage(lo, 0, 0, W, H);
  setT(ctx, m);
  const r = mulberry32(seed), cl = L.v.clouds, sx = geo.suns[0] ? geo.suns[0].x : 0.7 * W, hy = 0.64 * H;
  const blob = (x, y, rx, ry, col, a, rot = 0) => {
    ctx.save(); ctx.translate(x, y); if (rot) ctx.rotate(rot); ctx.scale(rx, ry);
    const rg = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
    rg.addColorStop(0, rgba(col, a)); rg.addColorStop(0.5, rgba(col, a * 0.45)); rg.addColorStop(1, rgba(col, 0));
    ctx.fillStyle = rg; ctx.beginPath(); ctx.arc(0, 0, 1, 0, 7); ctx.fill(); ctx.restore();
  };
  if (L.look === 1) {
    // thin high streaks: lit from below near the sun, grey-violet away from it
    const n = 5 + Math.round(cl * 8), r2 = mulberry32(seed + 9);
    for (let i = 0; i < n; i++) {
      const y = H * (0.05 + 0.5 * r()), len = W * (0.18 + 0.4 * r()), x = W * (-0.1 + 1.2 * r()), th = H * (0.014 + 0.03 * r());
      const near = Math.exp(-Math.pow((y - hy) / (0.28 * H), 2)) * Math.exp(-Math.pow((x - sx) / (0.7 * W), 2));
      skyRGB(m.s * x + m.e, m.s * y + m.f, o);
      const col = mixC(mixC(o, P.mid, 0.3), P.glow, near), al = (0.05 + 0.24 * near) * (0.35 + cl), rot = (r2() - 0.5) * 0.06;
      // each streak is a few uneven wisps on a slight tilt, not one clean ellipse
      for (let j = -1; j <= 1; j++) blob(x + j * len * (0.3 + 0.25 * r2()), y + (r2() - 0.5) * th * 1.6, len * (0.35 + 0.35 * r2()), th * (0.35 + 0.6 * r2()), col, al * 0.75, rot);
      blob(x + len * 0.1, y + th * 0.45, len * 0.7, th * 0.4, mixC(P.glow, P.sun, 0.5), 0.3 * near * (0.35 + cl), rot);
    }
  } else if (L.look === 2) {
    const n = 4 + Math.round(cl * 7);
    for (let i = 0; i < n; i++) {
      const cx = W * (-0.05 + 1.1 * r()), cy = H * (0.1 + 0.42 * r()), sz = W * (0.07 + 0.1 * r());
      const near = Math.exp(-Math.pow((cy - hy) / (0.3 * H), 2));
      const dark = mixC(P.mid, P.shade, 0.5), warm = mixC(P.glow, P.hor, 0.4);
      for (let k = 0; k < 9; k++) {
        const bx = cx + (r() - 0.5) * sz * 2.4, by = cy + (r() - 0.5) * sz * 0.35, bs = sz * (0.35 + 0.5 * r());
        blob(bx, by, bs, bs * 0.3, dark, 0.34 * (0.5 + cl * 0.7));
        blob(bx + bs * 0.08, by + bs * 0.18, bs * 0.9, bs * 0.15, warm, (0.12 + 0.5 * near) * (0.4 + cl * 0.6));
      }
    }
  }
  ctx.restore();
  if (photos.sky) { if (photoOf('sky')) ctx.clearRect(0, 0, W, H); drawPhoto(ctx, 'sky', m); }
}

// Per-pixel sand for one dune band. The slope under each pixel (sharp at the crest, broader down the face, bent by
// low surface noise) is lit from where the sun really is, with the sun a little behind the scene, so faces that turn
// to it glow and faces that turn away fall into violet shade that lengthens as the sun drops.
function shadeBand(pl, m, b, ys, P) {
  const N = ys.length, S = geo.suns[0] || { x: 0.7 * W, y: 0.5 * H }, inv = 1 / m.s;
  const cy = new Float32Array(W), sF = new Float32Array(W), sB = new Float32Array(W);
  const at = (lx) => { const f = clamp((lx - b.x0) / b.step, 0, N - 1.001), i = f | 0; return ys[i] + (ys[i + 1] - ys[i]) * (f - i); };
  let minY = 1e9;
  for (let X = 0; X < W; X++) {
    const lx = (X - m.e) * inv; cy[X] = m.s * at(lx) + m.f; if (cy[X] < minY) minY = cy[X];
    sF[X] = (at(lx + 7) - at(lx - 7)) / 14; sB[X] = (at(lx + 44) - at(lx - 44)) / 88;
  }
  const Y0 = clamp(Math.floor(minY) - 1, 0, H), Y1 = clamp(Math.ceil(b.yEnd), Y0, H); if (Y1 <= Y0) return null;
  const q = b.q || 1, w = Math.ceil(W / q), rows = Math.ceil((Y1 - Y0) / q), img = new ImageData(w, rows), d = img.data, rn = tex.rnd;
  const ox = (b.seed * 37) % TEX, oy = (b.seed * 91) % TEX, top = b.top, bot = b.bot, lit = b.litCol, sh = b.shadeCol, rp = b.ripples;
  const g1 = Math.max(minY + 1, m.s * b.bottom + m.f), gk = 1 / (g1 - minY), air = sky.air, cool = sky.cool;
  // everything that only depends on depth below the crest, at half-pixel steps
  const TN = 2048, kT = new Float32Array(TN), flL = new Float32Array(TN), flS = new Float32Array(TN), hzT = new Float32Array(TN), rpT = new Float32Array(TN);
  for (let i = 0; i < TN; i++) {
    const v = i * 0.5, tv = v / b.depth, k0 = Math.min(1, tv * 3.2);
    kT[i] = k0 * k0 * (3 - 2 * k0); flL[i] = b.litAmt * (0.05 + 0.95 * Math.exp(-tv * 1.8)); flS[i] = b.shadeAmt * (0.15 + 0.85 * Math.exp(-tv));
    hzT[i] = Math.min(0.92, b.air + b.fog * Math.min(1, tv * tv * 0.9)); rpT[i] = 20 * Math.log(1 + v / 60);
  }
  for (let xi = 0; xi < w; xi++) {
    const X = Math.min(W - 1, xi * q), c0 = cy[X], lx = (X - m.e) * inv, ldx = S.x - X, sf = sF[X], sb = sB[X];
    const dxs = ldx / H, ck = b.cool * (1 - 0.8 * Math.exp(-dxs * dxs / 0.5));
    const ar = air[X * 3] + (cool[0] - air[X * 3]) * ck, ag = air[X * 3 + 1] + (cool[1] - air[X * 3 + 1]) * ck, ab = air[X * 3 + 2] + (cool[2] - air[X * 3 + 2]) * ck;
    const u1 = lx * 0.4 + ox, ur = lx * 0.3 + oy, uw = lx * 0.5 + ox, ldx2 = ldx * ldx + 1;
    for (let yi = Math.max(0, Math.floor((c0 - Y0) / q) - 2); yi < rows; yi++) {
      const Y = Y0 + yi * q, v = Math.max(0, Y - c0) * inv, vi = Math.min(TN - 1, (v * 2) | 0), v1 = v * 1.5 + oy;
      const sx = sf + (sb - sf) * kT[vi] + tx2(tex.sgx, u1, v1) * b.und, sy = -1 + tx2(tex.sgy, u1, v1) * b.und * 0.8;
      const ldy = S.y - Y, dir = ((sx * ldx + sy * ldy) / Math.sqrt(ldx2 + ldy * ldy) * 0.95 - 0.165) / Math.sqrt(sx * sx + sy * sy + 0.3);
      const tg = Math.min(1, (Y - minY) * gk);
      let cr = top[0] + (bot[0] - top[0]) * tg, cg = top[1] + (bot[1] - top[1]) * tg, cb = top[2] + (bot[2] - top[2]) * tg, fl;
      if (dir > 0) { fl = flL[vi]; const a = Math.min(1, dir * 1.2) * fl; cr += (lit[0] - cr) * a; cg += (lit[1] - cg) * a; cb += (lit[2] - cb) * a; }
      else { fl = flS[vi]; const a = Math.min(1, -dir * 1.8) * fl; cr += (sh[0] - cr) * a; cg += (sh[1] - cg) * a; cb += (sh[2] - cb) * a; }
      // hollows sit a little darker than swells; grain on top
      let mul = 0.87 + 0.26 * tx2(tex.s, u1, v1) + (rn[(X * 7919 + Y * 104729) & 65535] / 255 - 0.5) * b.grain;
      if (rp > 0.02) {
        // wind ripples: lines that follow the crest, wider apart lower on the face, broken into patches
        const on = (tx2(tex.v, ur, v * 0.9 + ox) - 0.47) * 7;
        if (on > 0) mul += Math.sin(6.2832 * (rpT[vi] + lx * 0.014 + 5 * tx2(tex.s, uw, v * 0.9 + oy))) * 0.085 * rp * Math.min(1, on) * (0.35 + 0.65 * fl) * (dir > 0 ? 1 : 0.5);
      }
      const hz = hzT[vi], o = (yi * w + xi) * 4;
      d[o] = cr * mul + (ar - cr * mul) * hz; d[o + 1] = cg * mul + (ag - cg * mul) * hz; d[o + 2] = cb * mul + (ab - cb * mul) * hz; d[o + 3] = 255;
    }
  }
  pl.putImageData(img, 0, 0);
  return { Y0, w, rows, q };
}

function drawRidge(ctx, rim, m, b, P) {
  const ys = ridgeYs(b), N = ys.length, x0 = b.x0, step = b.step;
  let minY = 1e9, maxY = -1e9; for (let i = 0; i < N; i++) { minY = Math.min(minY, ys[i]); maxY = Math.max(maxY, ys[i]); }
  const path = (c) => { c.beginPath(); c.moveTo(x0, b.bottom + 600); for (let i = 0; i < N; i++) c.lineTo(x0 + i * step, ys[i]); c.lineTo(x0 + (N - 1) * step, b.bottom + 600); c.closePath(); };
  const lit = new Float32Array(N), wN = 7;
  for (let i = wN; i < N - wN; i++) {
    const x = x0 + i * step, slope = (ys[i + wN] - ys[i - wN]) / (2 * wN * step), d = Math.hypot(slope, 1);
    lit[i] = litAt(m.s * x + m.e, m.s * ys[i] + m.f, slope / d, -1 / d);
  }
  const pl = clear(cache.plate);
  let band = null;
  if (b.px) {
    band = shadeBand(pl, m, b, ys, P);
  } else {
    setT(pl, m);
    const g = pl.createLinearGradient(0, minY, 0, b.bottom);
    g.addColorStop(0, rgba(b.top)); g.addColorStop(1, rgba(b.bot));
    path(pl); pl.fillStyle = g; pl.fill();
    const litS = strip(b.litCol), shS = strip(b.shadeCol);
    const yA = Math.max(0, Math.floor(minY) - 2), yB = Math.min(shadeTmp.height, Math.ceil(maxY + b.depth * 1.8));
    const tx = shadeTmp.getContext('2d'); tx.setTransform(1, 0, 0, 1, 0, 0); tx.clearRect(0, yA, shadeTmp.width, yB - yA);
    for (let i = wN; i < N - wN; i++) {
      const l = lit[i], px = i * step, py = Math.floor(ys[i]);
      if (l > 0.04) { tx.globalAlpha = Math.pow(Math.min(1, l), 1.1) * b.litAmt; tx.drawImage(litS, px, py, step, b.depth * 0.9); }
      else if (l < -0.04) { tx.globalAlpha = Math.min(1, -l) * b.shadeAmt; tx.drawImage(shS, px, py, step, b.depth * 1.6); }
    }
    tx.globalAlpha = 1;
    pl.globalCompositeOperation = 'source-atop';
    pl.drawImage(shadeTmp, 0, yA, shadeTmp.width, yB - yA, x0, yA, shadeTmp.width, yB - yA);
    // aerial perspective: the whole ridge, light and shade together, fades toward the air behind it
    pl.setTransform(1, 0, 0, 1, 0, 0); pl.globalAlpha = b.air; pl.fillStyle = airGradient(pl, b.cool); pl.fillRect(0, 0, W, H);
  }
  pl.setTransform(1, 0, 0, 1, 0, 0); pl.globalAlpha = 1; pl.globalCompositeOperation = 'source-over';
  ctx.save(); ctx.imageSmoothingQuality = 'high';
  if (band) { setT(ctx, m); path(ctx); ctx.clip(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(cache.plate, 0, 0, band.w, band.rows, 0, band.Y0, band.w * band.q, band.rows * band.q); }
  else if (!b.px) { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(cache.plate, 0, 0); }
  ctx.restore();
  rim.save(); setT(rim, m); rim.globalCompositeOperation = 'destination-out'; rim.fillStyle = '#000';
  rim.beginPath(); rim.moveTo(x0, b.bottom + 600); for (let i = 0; i < N; i += 2) rim.lineTo(x0 + i * step, ys[i] + 1.5); rim.lineTo(x0 + (N - 1) * step, b.bottom + 600); rim.closePath(); rim.fill();
  rim.globalCompositeOperation = 'source-over'; rim.lineCap = 'round'; rim.lineJoin = 'round';
  const S = geo.suns[0];
  for (let i = 2; i < N - 4; i += 2) {
    const l = lit[i]; if (l < 0.12) continue;
    const xa = x0 + i * step, xb = x0 + (i + 2) * step;
    // crests glow hardest where you look toward the sun (forward scatter off the blowing sand), and thin out away from it
    const sd = S ? (m.s * xa + m.e - S.x) / H : 2, fwd = 0.38 + 0.62 * Math.exp(-sd * sd / 0.32);
    const a = Math.pow(Math.min(1, l * 1.25), 1.2) * 0.62 * fwd;
    rim.strokeStyle = rgba(P.rim, a * 0.2 * b.rimAmt); rim.lineWidth = 6; rim.beginPath(); rim.moveTo(xa, ys[i] + 1); rim.lineTo(xb, ys[i + 2] + 1); rim.stroke();
    rim.strokeStyle = rgba(mixC(P.rim, [255, 244, 220], 0.4), a * b.rimAmt); rim.lineWidth = 1.5; rim.beginPath(); rim.moveTo(xa, ys[i]); rim.lineTo(xb, ys[i + 2]); rim.stroke();
  }
  rim.restore();
  return { ys, x0, step };
}
function recordTop(arr, peak, rd, m, minX = 0) {
  // world-space top silhouette (min y per 4 px bucket)
  for (let i = 0; i < rd.ys.length; i++) {
    const wx = m.s * (rd.x0 + i * rd.step) + m.e, wy = m.s * rd.ys[i] + m.f, k = Math.round(wx / 4);
    if (k >= 0 && k < arr.length && wy < arr[k]) arr[k] = wy;
  }
}
function finishPeaks(top, peak) {
  const n = top.length, R = 14;
  for (let i = 0; i < n; i++) {
    let s = 0, c = 0;
    for (let k = -R; k <= R; k += 2) { const j = clamp(i + k, 0, n - 1); s += top[j]; c++; }
    peak[i] = clamp((s / c - top[i]) / 16, 0, 1);
  }
}

function drawFar(ctx, rim, P, L, seed) {
  const m = mat('far'), hz = L.v.haze, amp = (0.02 + 0.075 * L.v.height) * H;
  const spec = L.look === 1 ? [{ base: 0.6, d: 0.7, f: 1 / 380, k: 'mesa', a: 0.9 }, { base: 0.635, d: 0.5, f: 1 / 300, k: 'mesa', a: 1.0 }]
    : L.look === 2 ? [{ base: 0.59, d: 0.72, f: 1 / 210, k: 'saw', a: 0.55 }, { base: 0.615, d: 0.58, f: 1 / 160, k: 'saw', a: 0.5 }, { base: 0.64, d: 0.42, f: 1 / 190, k: 'saw', a: 0.5 }]
      : [{ base: 0.585, d: 0.72, f: 1 / 330, k: 'round', a: 1.0 }, { base: 0.615, d: 0.56, f: 1 / 260, k: 'round', a: 1.1 }, { base: 0.645, d: 0.4, f: 1 / 220, k: 'round', a: 0.9 }];
  geo.topFar.fill(H);
  const rock = mixC(P.far, P.cliff, 0.3);
  spec.forEach((s, i) => {
    // d is distance: the farther ridge keeps less of its own colour and contrast
    const d = clamp(s.d + (hz - 0.5) * 0.45, 0.05, 0.95), air = 1 - Math.exp(-1.25 * d), fog = mixC(P.haze, P.hor, 0.45);
    const rd = drawRidge(ctx, rim, m, {
      x0: -W * 0.7, x1: W * 1.7, step: 2, seed: seed + i * 31, kind: s.k, freq: s.f, base: s.base * H, amp: amp * s.a, sharp: false, peak: 0.4,
      top: rock, bot: mixC(rock, fog, 0.55), bottom: 0.7 * H, litCol: mixC(P.lit, P.rim, 0.25), shadeCol: P.shade, litAmt: 0.8, shadeAmt: 0.6, depth: 50, ripples: 0, rimAmt: 0.36 * (1 - d * 0.7),
      air, cool: 0.2 + 0.5 * d,
    }, P);
    recordTop(geo.topFar, geo.peakFar, rd, m);
  });
  finishPeaks(geo.topFar, geo.peakFar);
  // a still sheet of ground haze pooled at the foot of the ridges
  const pl = clear(cache.plate);
  pl.fillStyle = airGradient(pl, 0.25); pl.fillRect(0, 0, W, H);
  setT(pl, m); pl.globalCompositeOperation = 'destination-in';
  const g = pl.createLinearGradient(0, 0.585 * H, 0, 0.7 * H);
  g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(0.55, `rgba(0,0,0,${(0.1 + 0.2 * hz).toFixed(3)})`); g.addColorStop(1, `rgba(0,0,0,${(0.3 + 0.3 * hz).toFixed(3)})`);
  pl.fillStyle = g; pl.fillRect(-W, -H, 3 * W, 4 * H);
  pl.setTransform(1, 0, 0, 1, 0, 0); pl.globalCompositeOperation = 'source-over';
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalCompositeOperation = 'source-atop'; ctx.drawImage(cache.plate, 0, 0); ctx.restore();
  if (photoOf('far') || photos.far) drawPhoto(ctx, 'far', m);
}

function jag(pts, r, rough, levels = 4) {
  for (let l = 0; l < levels; l++) {
    const out = [];
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1]; out.push(a);
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, d = len * rough * (r() - 0.5) * 2 / (l * 0.6 + 1);
      out.push([(a[0] + b[0]) / 2 - (b[1] - a[1]) / len * d, (a[1] + b[1]) / 2 + (b[0] - a[0]) / len * d * 0.8]);
    }
    out.push(pts[pts.length - 1]); pts = out;
  }
  return pts;
}
const CLIFFS = [
  [[-3.2, -0.05], [-2.2, 0.06], [-1.5, 0.18], [-1.0, 0.3], [-0.78, 0.36], [-0.72, 0.6], [-0.62, 0.78], [-0.55, 0.97], [-0.3, 1.0], [0.1, 0.985], [0.45, 1.0], [0.58, 0.96], [0.62, 0.8], [0.7, 0.62], [0.78, 0.5], [1.05, 0.42], [1.4, 0.3], [2.0, 0.14], [3.2, -0.05]],
  [[-2.6, -0.05], [-1.6, 0.08], [-0.9, 0.2], [-0.45, 0.32], [-0.34, 0.55], [-0.26, 0.8], [-0.2, 0.93], [-0.1, 1.0], [0.0, 0.97], [0.08, 0.9], [0.12, 0.7], [0.2, 0.5], [0.34, 0.34], [0.8, 0.28], [1.3, 0.27], [1.45, 0.2], [2.2, 0.08], [3.2, -0.05]],
  [[-3.0, -0.05], [-2.0, 0.1], [-1.3, 0.25], [-1.1, 0.55], [-0.95, 0.8], [-0.75, 0.88], [-0.6, 1.0], [-0.4, 0.93], [-0.2, 0.7], [0.0, 0.6], [0.2, 0.64], [0.35, 0.86], [0.5, 0.82], [0.62, 0.7], [0.7, 0.5], [0.95, 0.4], [1.5, 0.25], [2.2, 0.1], [3.2, -0.05]],
];
// The cliff is shaded per pixel. A blurred copy of its silhouette gives the big rounded form (which way each part of
// the wall faces); strata are hard and soft beds of uneven thickness along a warped, slightly dipping height, cut by
// vertical gullies; the lower third relaxes into a scree apron. All of it is lit from the sun's position.
function drawCliff(ctx, rim, P, L, seed) {
  const m = mat('cliff'), r = mulberry32(seed), base = ANCH.cliff[1];
  const h = (0.24 + 0.34 * L.v.height) * H, w = (0.1 + 0.2 * L.v.width) * W * (L.look === 1 ? 0.7 : 1), cx = 0.30 * W;
  let pts = CLIFFS[L.look % 3].map(([x, y]) => [cx + x * w, base - y * h]);
  pts = jag(pts, r, 0.2, 4);
  const xs = pts.map((p) => p[0]), minX = Math.min(...xs), maxX = Math.max(...xs), topY = Math.min(...pts.map((p) => p[1]));
  geo.cliffPoly = { pts, m, base, topY };
  const path = (c) => { c.beginPath(); c.moveTo(minX, base + 700); pts.forEach((p) => c.lineTo(p[0], p[1])); c.lineTo(maxX, base + 700); c.closePath(); };
  const lw = W / 4, lh = H / 4, lc = cache.low.getContext('2d', { willReadFrequently: true });
  lc.setTransform(1, 0, 0, 1, 0, 0); lc.clearRect(0, 0, lw, lh); lc.setTransform(m.s / 4, 0, 0, m.s / 4, m.e / 4, m.f / 4); lc.fillStyle = '#fff'; path(lc); lc.fill();
  const md = lc.getImageData(0, 0, lw, lh).data, B = new Float32Array(lw * lh), Gx = new Float32Array(lw * lh), Gy = new Float32Array(lw * lh);
  for (let i = 0; i < B.length; i++) B[i] = md[i * 4 + 3] / 255;
  blur2(B, lw, lh, 5, 3);
  for (let y = 0; y < lh; y++) for (let x = 0; x < lw; x++) { Gx[y * lw + x] = B[y * lw + Math.min(lw - 1, x + 1)] - B[y * lw + Math.max(0, x - 1)]; Gy[y * lw + x] = B[Math.min(lh - 1, y + 1) * lw + x] - B[Math.max(0, y - 1) * lw + x]; }
  const sv = L.v.strata, n1 = noise1(seed + 5), n2 = noise1(seed + 6), SL = 2400, prof = new Float32Array(SL), dprof = new Float32Array(SL), albL = new Float32Array(SL);
  for (let i = 0; i < SL; i++) {
    const s = i * 0.5, a = n1(s * 0.045), b2 = n1(s * 0.16 + 40), c = n1(s * 0.33 + 90);
    prof[i] = sm(0.4, 0.56, a * 0.62 + b2 * 0.38) * 0.6 + sm(0.5, 0.6, b2 * 0.5 + c * 0.5) * 0.28 + c * 0.12;
    albL[i] = n2(s * 0.045) * 0.6 + n2(s * 0.19 + 7) * 0.4;
  }
  for (let i = 1; i < SL - 1; i++) dprof[i] = prof[i + 1] - prof[i - 1];
  const S = geo.suns[0] || { x: W, y: 0.5 * H }, inv = 1 / m.s, dip = (hash(3, seed) - 0.5) * 0.07;
  const X0 = clamp(Math.floor(m.s * minX + m.e), 0, W), X1 = clamp(Math.ceil(m.s * maxX + m.e), 0, W), Y0 = clamp(Math.floor(m.s * topY + m.f) - 2, 0, H), Yb = clamp(Math.ceil(m.s * (base + 14) + m.f), Y0, H);
  if (X1 > X0 && H > Y0) {
    const q = builtQ.cliff || 1, iw = Math.ceil((X1 - X0) / q), ih = Math.ceil((H - Y0) / q), yb = Math.min(ih, Math.ceil((Yb - Y0) / q)), img = new ImageData(iw, ih), d = img.data, rn = tex.rnd, air = sky.air;
    const body = mixC(P.cliff, P.haze, 0.1), bandA = mixC(body, P.lit, 0.3), bandB = mixC(body, P.shade, 0.36), hot = mixC(P.lit, P.rim, 0.45), fogC = mixC(P.haze, P.hor, 0.4), shadeC = mixC(P.shade, P.top, 0.2), warm = P.lit;
    const ox = seed % TEX, oy = (seed * 7) % TEX;
    for (let yi = 0; yi < yb; yi++) {
      const Y = Y0 + yi * q, ly = (Y - m.f) * inv, hh = (base - ly) / h, fy = clamp(Y / 4 - 0.5, 0, lh - 1.001), iy = fy | 0, wy = fy - iy;
      const tal = 1 - sm(0.3, 0.44, hh), qf = (ly - (base - 0.42 * h)) / (0.42 * h + 10), fog = qf <= 0 ? 0 : qf < 0.7 ? 0.3 * qf / 0.7 : Math.min(0.8, 0.3 + 0.5 * (qf - 0.7) / 0.3);
      const ldy = S.y - Y, ldy2 = ldy * ldy + 1, bnc = 0.24 * Math.pow(clamp(1 - hh, 0, 1), 2), amt = sv * 1.6 * (1 - 0.8 * tal), fv = ly * 0.22 + oy;
      for (let xi = 0; xi < iw; xi++) {
        const X = X0 + xi * q, fx = clamp(X / 4 - 0.5, 0, lw - 1.001), ix = fx | 0, wx = fx - ix, i0 = iy * lw + ix, i1 = i0 + lw;
        const Bv = (B[i0] * (1 - wx) + B[i0 + 1] * wx) * (1 - wy) + (B[i1] * (1 - wx) + B[i1 + 1] * wx) * wy; if (Bv < 0.01) continue;
        const gx = (Gx[i0] * (1 - wx) + Gx[i0 + 1] * wx) * (1 - wy) + (Gx[i1] * (1 - wx) + Gx[i1 + 1] * wx) * wy, gy = (Gy[i0] * (1 - wx) + Gy[i0 + 1] * wx) * (1 - wy) + (Gy[i1] * (1 - wx) + Gy[i1 + 1] * wx) * wy;
        // big form: sideways at the silhouette, toward the eye in the middle of the wall
        const z0 = clamp((Bv - 0.42) / 0.56, 0, 1), mz = z0 * z0 * (3 - 2 * z0), side = Math.sqrt((1 - mz * mz) / (gx * gx + gy * gy + 1e-9));
        const lx = (X - m.e) * inv, fu = lx * 1.7 + ox;
        // gullies run down the wall where the smooth noise crosses its middle; beds sag a little into them
        const e = tx2(tex.s, fu, fv) - 0.5, rg = 1 - Math.min(1, Math.abs(e) * 10), rg2 = rg * rg * (1 - tal);
        const sy = ly + (tx2(tex.v, lx * 0.24 + oy, ly * 0.24 + ox) - 0.5) * 64 + (tx2(tex.v, lx * 0.7 + ox, ly * 0.7 + oy) - 0.5) * 14 + dip * (lx - cx) - rg2 * 6;
        const si = clamp((sy + 260) * 2, 1, SL - 2) | 0, pr = prof[si];
        const ru = lx * 1.7 + oy, rv = ly * 1.7 + ox;
        let nx = -gx * side + ((e > 0 ? -1 : 1) * rg * tx2(tex.sgx, fu, fv) * 13 * (1 - tal) + tx2(tex.gx, ru, rv) * 2.4) * amt;
        let ny = -gy * side + (-dprof[si] * 6 + tx2(tex.gy, ru, rv) * 2.4) * amt - 0.5 * tal;
        const nz = mz + 0.25, nl = 1 / Math.sqrt(nx * nx + ny * ny + nz * nz); nx *= nl; ny *= nl;
        const ldx = S.x - X, dir = (nx * ldx + ny * ldy) / Math.sqrt(ldx * ldx + ldy2) * 0.954 - nz * nl * 0.3;
        const ao = Math.max(0.15, 1 - sv * 1.3 * (0.7 * rg2 + 0.42 * (1 - pr) * (1 - 0.8 * tal)));
        const ka = (albL[si] - 0.5) * sv * 2.2 * (1 - 0.6 * tal), bc = ka > 0 ? bandA : bandB, kk = Math.min(1, Math.abs(ka) * 2);
        const shd = clamp(0.2 + 0.75 * (1 - ao) + 0.22 * ny, 0, 0.9), wrap = Math.max(0, (dir + 0.4) / 1.4) * 0.26, bn = bnc * (0.6 + 0.4 * Math.max(0, ny));
        const dl = dir > 0 ? Math.min(1, dir * 1.7) * 0.92 : 0;
        const mul = yi === yb - 1 ? 1 : 1 + (rn[(X * 7919 + Y * 104729) & 65535] / 255 - 0.5) * 0.07 * (0.5 + sv); // the last row is copied down, so no grain in it
        const o = (yi * iw + xi) * 4, a3 = X * 3;
        for (let c = 0; c < 3; c++) {
          let v = body[c] + (bc[c] - body[c]) * kk;
          v += (shadeC[c] - v) * shd; v += (warm[c] - v) * wrap; v += (warm[c] - v) * bn; v += (hot[c] - v) * dl; v *= mul;
          v += (air[a3 + c] - v) * 0.13; v += (fogC[c] - v) * fog; d[o + c] = v;
        }
        d[o + 3] = 255;
      }
    }
    for (let yi = Math.max(yb, 1); yi < ih; yi++) { const o = yi * iw * 4; d.copyWithin(o, o - iw * 4, o); }
    const pl = clear(cache.plate); pl.putImageData(img, 0, 0);
    ctx.save(); ctx.imageSmoothingQuality = 'high'; setT(ctx, m); path(ctx); ctx.clip(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(cache.plate, 0, 0, iw, ih, X0, Y0, iw * q, ih * q); ctx.restore();
  }
  rim.save(); setT(rim, m); rim.lineCap = 'round'; rim.lineJoin = 'round';
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1], dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
    if (a[1] > base - h * 0.04) continue;
    const l = litAt(m.s * a[0] + m.e, m.s * a[1] + m.f, dy / len, -dx / len); if (l < 0.1) continue;
    const al = Math.pow(Math.min(1, l * 1.2), 1.1);
    rim.strokeStyle = rgba(P.rim, al * 0.14); rim.lineWidth = 8; rim.beginPath(); rim.moveTo(a[0], a[1]); rim.lineTo(b[0], b[1]); rim.stroke();
    rim.strokeStyle = rgba(mixC(P.rim, [255, 244, 220], 0.45), al * 0.7); rim.lineWidth = 1.4; rim.beginPath(); rim.moveTo(a[0], a[1]); rim.lineTo(b[0], b[1]); rim.stroke();
  }
  rim.restore();
  if (photos.cliff) drawPhoto(ctx, 'cliff', m);
}

function drawNear(ctx, rim, P, L, seed) {
  const m = mat('near'), k = L.v.height, rp = L.v.ripples;
  const look = L.look;
  const fq = look === 1 ? 1 / 300 : look === 2 ? 1 / 720 : 1 / 420, sharp = look === 1, peak = look === 1 ? 0.22 : 0.3;
  const a1 = (look === 2 ? 0.045 : 0.07 + 0.12 * k) * H, a2 = (look === 2 ? 0.03 : 0.045 + 0.08 * k) * H;
  geo.topNear.fill(H);
  // back to front: less air and more of the sand's own colour the closer the band is
  const bands = [
    { base: 0.735, a: (0.035 + 0.06 * k) * H, f: fq * 0.8, col: mixC(P.near, P.haze, 0.12), litAmt: 0.8, ripples: 0, depth: 110, seedo: 7, air: 0.26, fog: 0.3, cool: 0.3, und: 8, grain: 0.03 },
    { base: 0.835, a: a1, f: fq, col: mixC(P.near, P.haze, 0.05), litAmt: 0.86, ripples: rp * 0.6, depth: 130, seedo: 3, air: 0.1, fog: 0.18, cool: 0.2, und: 10, grain: 0.045 },
    { base: 0.94, a: a2, f: fq * 1.25, col: mixC(mixC(P.near, [0, 0, 0], 0.1), P.lit, 0.05), litAmt: 0.88, ripples: rp, depth: 110, seedo: 11, air: 0.03, fog: 0, cool: 0, und: 12, grain: 0.06 },
  ];
  bands.forEach((b, i) => {
    const nb = bands[i + 1];
    const rd = drawRidge(ctx, rim, m, {
      x0: -W * 0.7, x1: W * 1.7, step: 2, seed: seed + b.seedo, kind: 'saw', freq: b.f, base: b.base * H, amp: b.a, sharp, peak, px: true, q: builtQ.near || 1,
      yEnd: nb ? m.s * (nb.base * H + nb.a * 0.12 + 8) + m.f : H,
      top: mixC(b.col, P.lit, 0.1), bot: mixC(b.col, [0, 0, 0], 0.25), bottom: H, litCol: P.lit, shadeCol: P.shade, litAmt: b.litAmt, shadeAmt: 0.6, depth: b.depth, ripples: b.ripples, rimAmt: 1,
      air: b.air, fog: b.fog, cool: b.cool, und: b.und, grain: b.grain,
    }, P);
    recordTop(geo.topNear, geo.peakNear, rd, m);
  });
  finishPeaks(geo.topNear, geo.peakNear);
  if (photos.near) drawPhoto(ctx, 'near', m);
}

// drifting ground haze: wisps cut from the noise plate, tileable along x
function makeHaze(tile, P, seed, band) {
  const w = tile.width, h = tile.height, lw = w / 4, lh = Math.ceil(h / 4), lo = mk(lw, lh), lx = lo.getContext('2d'), img = lx.createImageData(lw, lh), d = img.data;
  const col = mixC(P.haze, P.hor, 0.3), ox = seed % TEX, oy = (seed * 7) % TEX, a0 = band === 'A' ? 0.56 : 0.38, ku = TEX / lw;
  for (let y = 0, i = 0; y < lh; y++) {
    const win = Math.pow(Math.sin(Math.PI * (y + 0.5) / lh), 1.3);
    for (let x = 0; x < lw; x++, i += 4) {
      const n = tx2(tex.v, x * ku + ox, y * 5 + oy) * 0.62 + tx2(tex.v, x * ku * 2 + ox * 3, y * 11 + oy + 91) * 0.38;
      d[i] = col[0]; d[i + 1] = col[1]; d[i + 2] = col[2]; d[i + 3] = sm(0.38, 0.66, n) * win * a0 * 255;
    }
  }
  lx.putImageData(img, 0, 0);
  const x = clear(tile); x.imageSmoothingQuality = 'high'; x.drawImage(lo, 0, 0, w, h);
}

// ------------------------------------------------------------ render the cached layers (only the ones whose inputs changed)
function clear(c) { const x = c.getContext('2d'); x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = 'source-over'; x.clearRect(0, 0, c.width, c.height); return x; }
const built = {}, builtQ = {}, buildMs = {};
let photoRev = 0, lastBuild = -1e9, settleAt = 0; // lastBuild: when the last real rebuild finished
// full: every per-pixel plate at full size now (tests, stills). Otherwise edits that arrive in a quick run (a slider
// drag) build the cliff and the dunes at half size, and they are redone at full size once the hand stops.
function renderAll(full) {
  const P = geo.P = palette(st.time);
  computeSuns(P);
  const Ls = st.layers, J = JSON.stringify, now = performance.now(), fast = !full && now - lastBuild < 260;
  const lightK = J([st.time, st.seed, Ls.suns, photoRev]), airK = lightK + J([Ls.sky.x, Ls.sky.y, Ls.sky.s]);
  let tm = now, tmId = 'prep', changed = false, settled = false;
  const need = (id, key, px) => {
    const n = performance.now(); buildMs[tmId] = +(n - tm).toFixed(1); tm = n; tmId = id;
    const settle = px && builtQ[id] > 1 && (full || (now >= settleAt && !settled)); // one settle a frame, to spread the cost
    if (built[id] === key && !settle) return false;
    if (built[id] === key) settled = true;
    const q = px && fast && built[id] !== key ? 2 : 1;
    if (built[id] !== key) changed = true;
    built[id] = key; builtQ[id] = q;
    return true;
  };
  skyPrep(P);
  if (need('sky', lightK + J(Ls.sky))) {
    const x = clear(cache.sky); if (Ls.sky.show) drawSky(x, P, Ls.sky, lseed('sky'), mat('sky'));
    geo.suns.forEach((s, i) => makeBloom(cache.bloom[i], mixC(P.glow, s.col, 0.3)));
    // stars (positions only depend on seed)
    const r = mulberry32(lseed('sky') + 77); geo.stars = []; for (let i = 0; i < 170; i++) geo.stars.push({ x: r() * W, y: H * 0.5 * Math.pow(r(), 1.3), r: 0.5 + r() * 1.1 * (r() < 0.12 ? 1.8 : 1), ph: r() * 7, sp: 0.4 + r() * 1.6 });
  }
  if (need('suns', lightK)) { const x = clear(cache.suns); if (Ls.suns.show && photos.suns) drawPhoto(x, 'suns', mat('suns')); }
  if (need('far', airK + J(Ls.far))) { const x = clear(cache.far), rx = clear(cache.farRim); geo.topFar.fill(H); if (Ls.far.show) { if (!photoOf('far')) drawFar(x, rx, P, Ls.far, lseed('far')); else drawPhoto(x, 'far', mat('far')); } }
  if (need('cliff', airK + J(Ls.cliff), true)) { const x = clear(cache.cliff), rx = clear(cache.cliffRim); geo.cliffPoly = null; if (Ls.cliff.show) { if (!photoOf('cliff')) drawCliff(x, rx, P, Ls.cliff, lseed('cliff')); else drawPhoto(x, 'cliff', mat('cliff')); } }
  if (need('near', airK + J(Ls.near), true)) { const x = clear(cache.near), rx = clear(cache.nearRim); geo.topNear.fill(H); if (Ls.near.show) { if (!photoOf('near')) drawNear(x, rx, P, Ls.near, lseed('near')); else drawPhoto(x, 'near', mat('near')); } }
  if (need('air', lightK + J(Ls.air))) { const x = clear(cache.air); if (Ls.air.show && photos.air) drawPhoto(x, 'air', mat('air')); makeHaze(cache.hazeA, P, lseed('air') + 1, 'A'); makeHaze(cache.hazeB, P, lseed('air') + 2, 'B'); }
  buildMs[tmId] = +(performance.now() - tm).toFixed(1);
  if (changed) { lastBuild = performance.now(); settleAt = lastBuild + 300; }
  dirty = false;
}
// a half-size plate is waiting and the edits have stopped: time to redo it
const needsSettle = () => (builtQ.cliff > 1 || builtQ.near > 1) && performance.now() >= settleAt;

// ------------------------------------------------------------ simulation (fixed step, deterministic)
const DT = 1 / 60;
const sim = { t: 0, lift: 0, liftTarget: 0, parts: [], r: mulberry32(1234), accN: 0, accF: 0, accM: 0, gust: noise1(4242) };
const AIRLOOK = [{ sand: 1, mote: 0.25, haze: 1 }, { sand: 0.4, mote: 0.2, haze: 1.9 }, { sand: 0.3, mote: 3, haze: 0.7 }];
function emitX(top, peak, t) {
  for (let tries = 0; tries < 10; tries++) {
    const x = sim.r() * W, k = clamp(Math.round(x / 4), 0, top.length - 1);
    if (top[k] >= H - 1) continue;
    const g = 0.2 + 0.9 * sm(0.34, 0.74, sim.gust(x * 0.0055 + t * 0.32));
    if (sim.r() < (0.1 + peak[k]) * g) return k * 4;
  }
  return -1;
}
function simStep(dt) {
  const r = sim.r, A = st.layers.air, t = sim.t;
  sim.lift += (sim.liftTarget - sim.lift) * (1 - Math.exp(-dt / 2.4));
  if (A.show) {
    const amt = A.v.amount * 2, wind = 0.35 + A.v.wind * 1.3, lk = AIRLOOK[A.look % 3];
    sim.accN += 170 * amt * lk.sand * dt; sim.accF += 90 * amt * lk.sand * dt; sim.accM += 30 * amt * lk.mote * dt;
    while (sim.accN >= 1) {
      sim.accN--; if (!st.layers.near.show) continue;
      const x = emitX(geo.topNear, geo.peakNear, t); if (x < 0) continue;
      const y = geo.topNear[Math.round(x / 4)] - 1 - r() * 3;
      sim.parts.push({ k: 1, x, y, vx: -(70 + 110 * r()) * wind, vy: -(1 + 12 * r()), a: 0, life: 1.0 + 1.8 * r(), s: 1.6 + 2.4 * r(), al: 0.2 + 0.35 * r() });
    }
    while (sim.accF >= 1) {
      sim.accF--; if (!st.layers.far.show) continue;
      const x = emitX(geo.topFar, geo.peakFar, t); if (x < 0) continue;
      const y = geo.topFar[Math.round(x / 4)] - 1 - r() * 2;
      sim.parts.push({ k: 0, x, y, vx: -(45 + 70 * r()) * wind, vy: -(1 + 6 * r()), a: 0, life: 1.2 + 2 * r(), s: 1.1 + 1.5 * r(), al: 0.16 + 0.25 * r() });
    }
    while (sim.accM >= 1) {
      sim.accM--;
      sim.parts.push({ k: 2, x: W * (0.1 + 1.0 * r()), y: H * (0.5 + 0.5 * r()), vx: -(10 + 22 * r()) * wind, vy: -(3 + 9 * r()), a: 0, life: 5 + 6 * r(), s: 1.2 + 2.4 * r(), al: 0.2 + 0.35 * r(), ph: r() * 6 });
    }
  }
  const ps = sim.parts;
  for (let i = ps.length - 1; i >= 0; i--) {
    const p = ps[i]; p.a += dt;
    if (p.a >= p.life || p.x < -40 || p.x > W + 40) { ps[i] = ps[ps.length - 1]; ps.pop(); continue; }
    if (p.k === 2) { p.x += p.vx * dt + Math.sin(t * 0.7 + p.ph) * 4 * dt; p.y += p.vy * dt + Math.cos(t * 0.9 + p.ph) * 3 * dt; continue; }
    if (p.a > 0.2) p.vy += 34 * dt;
    p.vx *= 1 - 0.18 * dt; p.x += p.vx * dt; p.y += p.vy * dt;
  }
  sim.t += dt;
}
function resetSim() {
  sim.t = 0; sim.lift = 0; sim.liftTarget = 0; sim.parts = []; sim.r = mulberry32(1234); sim.accN = sim.accF = sim.accM = 0;
  for (let i = 0; i < 360; i++) simStep(DT);
}
function advance(tNow) {
  if (tNow - sim.t > 0.5) sim.t = tNow - 0.5;
  let n = 0;
  while (sim.t + DT <= tNow + 1e-9 && n++ < 120) simStep(DT);
}

// ------------------------------------------------------------ composite
const cv = $('#cv'), cx = cv.getContext('2d');
// finish plates, built once: a vignette, and a film grain tile laid down as a repeating pattern at a new offset each tick
const fin = (() => {
  const vig = mk(W, H), vx = vig.getContext('2d'), g = vx.createRadialGradient(W / 2, H * 0.52, H * 0.42, W / 2, H * 0.52, Math.hypot(W, H) * 0.54);
  g.addColorStop(0, 'rgba(10,6,20,0)'); g.addColorStop(0.5, 'rgba(10,6,20,0.1)'); g.addColorStop(1, 'rgba(10,6,20,0.4)');
  vx.fillStyle = g; vx.fillRect(0, 0, W, H);
  const n = 512, gc = mk(n, n), gx = gc.getContext('2d'), img = gx.createImageData(n, n), d = img.data, r = mulberry32(777);
  for (let i = 0; i < d.length; i += 4) { const v = r() - r(), w = v > 0 ? 255 : 0; d[i] = d[i + 1] = d[i + 2] = w; d[i + 3] = Math.abs(v) * 0.034 * 255; }
  gx.putImageData(img, 0, 0);
  return { vig, grain: gc, pat: null };
})();
function drawBloom(ctx, sprite, s, R, a) { if (a <= 0.003) return; ctx.globalAlpha = Math.min(1, a); ctx.drawImage(sprite, s.x - R, s.y - R, 2 * R, 2 * R); }
function drawParticles(ctx, kind, P) {
  const buckets = [[], [], [], []], col = kind === 1 ? mixC(P.rim, P.hor, 0.35) : kind === 0 ? mixC(P.rim, P.haze, 0.55) : mixC(P.rim, [255, 240, 220], 0.35);
  for (const p of sim.parts) {
    if (p.k !== kind) continue;
    const f = p.a / p.life, a = p.al * Math.pow(Math.sin(Math.PI * Math.min(1, f)), 0.8);
    buckets[Math.min(3, Math.floor(a * 6.5))].push(p);
  }
  ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.lineCap = 'round';
  buckets.forEach((arr, bi) => {
    if (!arr.length) return;
    const a = (bi + 0.5) / 6.5;
    if (kind === 2) { ctx.fillStyle = rgba(col, Math.min(0.7, a)); for (const p of arr) ctx.fillRect(p.x, p.y, p.s, p.s); return; }
    const sz = kind === 1 ? 1.7 : 1.2, k = kind === 1 ? 0.07 : 0.06;
    [[0, 1], [1, 0.62], [2, 0.38], [3, 0.2], [4, 0.1]].forEach(([j, f]) => {
      ctx.fillStyle = rgba(col, Math.min(0.85, a * f * 1.25));
      for (const p of arr) ctx.fillRect(p.x - p.vx * k * j, p.y - p.vy * k * j, sz, sz * 0.8);
    });
  });
  ctx.restore();
}
function composite() {
  if (dirty || needsSettle()) renderAll(manual);
  const P = geo.P, Ls = st.layers, t = sim.t, lift = sim.lift, bx = cache.back.getContext('2d');
  // everything at the horizon and beyond goes to a back plate first, so heat shimmer can bend it without touching the foreground
  bx.setTransform(1, 0, 0, 1, 0, 0); bx.globalAlpha = 1; bx.globalCompositeOperation = 'source-over';
  bx.fillStyle = rgba(P.top); bx.fillRect(0, 0, W, H);
  if (Ls.sky.show) bx.drawImage(cache.sky, 0, 0);
  // stars
  if (Ls.sky.show && !photoOf('sky')) {
    const sa = sm(0.5, 0.95, st.time) * Ls.sky.v.stars;
    if (sa > 0.01) {
      bx.save(); bx.globalCompositeOperation = 'lighter';
      for (const s of geo.stars) {
        const a = sa * sm(0.5 * H, 0, s.y) * (0.7 + 0.3 * Math.sin(t * s.sp + s.ph)); if (a < 0.02) continue;
        bx.fillStyle = `rgba(255,244,230,${a.toFixed(3)})`; bx.fillRect(s.x, s.y, s.r, s.r);
      }
      bx.restore();
    }
  }
  ask.drawSlot(bx, 0, t);
  // suns: the bloom breathes a little, the disc does not
  const sunsOn = Ls.suns.show && !photoOf('suns'), gl = Ls.suns.v.glow, breathe = 1 + 0.045 * Math.sin(t * 0.55) + 0.02 * Math.sin(t * 1.3 + 1.7), up = 1 + lift;
  if (sunsOn) {
    bx.save(); bx.globalCompositeOperation = 'lighter';
    geo.suns.forEach((s, i) => {
      const k = breathe * (i ? 1 + 0.03 * Math.sin(t * 0.7 + 2) : 1) * s.g;
      drawBloom(bx, cache.bloom[i], s, s.r * (7 + 6 * gl) * (1 + 0.3 * (breathe - 1)), (0.3 + 0.45 * gl) * k * up);
    });
    bx.restore();
    geo.suns.forEach((s) => {
      // limb darkening: white-hot centre, the sun's own colour at the edge
      const g = bx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.r * 1.03);
      g.addColorStop(0, rgba(mixC(s.col, [255, 255, 246], 0.62), 1)); g.addColorStop(0.55, rgba(mixC(s.col, [255, 255, 246], 0.45), 1)); g.addColorStop(0.9, rgba(mixC(s.col, [255, 255, 246], 0.12), 1)); g.addColorStop(0.965, rgba(s.col, 1)); g.addColorStop(1, rgba(s.col, 0));
      bx.fillStyle = g; bx.beginPath(); bx.arc(s.x, s.y, s.r * 1.03, 0, 7); bx.fill();
    });
  }
  if (Ls.suns.show) bx.drawImage(cache.suns, 0, 0);
  ask.drawSlot(bx, 1, t);
  const rimK = 0.75 * (1 + lift);
  const air = Ls.air, lk = AIRLOOK[air.look % 3], wind = 0.35 + air.v.wind * 1.3;
  const hz = air.show ? clamp(0.32 + 0.5 * air.v.amount, 0, 1) * lk.haze : 0;
  if (Ls.far.show) { bx.drawImage(cache.far, 0, 0); bx.globalCompositeOperation = 'lighter'; bx.globalAlpha = rimK; bx.drawImage(cache.farRim, 0, 0); bx.globalAlpha = 1; bx.globalCompositeOperation = 'source-over'; }
  ask.drawSlot(bx, 2, t);
  if (air.show) {
    drawParticles(bx, 0, P);
    const off = (t * 7 * wind) % 1536;
    bx.globalAlpha = clamp(hz, 0, 1); const y = 0.575 * H + 3 * Math.sin(t * 0.11);
    bx.drawImage(cache.hazeA, -off, y); bx.drawImage(cache.hazeA, 1536 - off, y); bx.globalAlpha = 1;
  }
  // light scattered in the air between the eye and the far ground, strongest toward the sun
  if (sunsOn && geo.suns[0]) { bx.globalCompositeOperation = 'lighter'; drawBloom(bx, cache.bloom[0], geo.suns[0], H * 0.8, 0.13 * (0.4 + gl) * up); bx.globalAlpha = 1; bx.globalCompositeOperation = 'source-over'; }

  cx.setTransform(1, 0, 0, 1, 0, 0); cx.globalAlpha = 1; cx.globalCompositeOperation = 'source-over';
  cx.drawImage(cache.back, 0, 0);
  // heat shimmer: thin rows of the back plate redrawn a fraction of a pixel off, growing toward the horizon, fading with the day
  const shim = 1 - 0.7 * P.night;
  if (shim > 0.05) {
    const y0 = Math.round(0.53 * H), y1 = Math.round(0.686 * H);
    for (let y = y0; y < y1; y += 3) {
      const k = sm(y0, y1 - 16, y), A = shim * k * k;
      const dy = A * (0.8 * Math.sin(y * 0.61 + t * 4.1) + 0.45 * Math.sin(y * 1.37 - t * 6.3)), dx = A * 0.7 * Math.sin(y * 0.83 + t * 3.3 + 1.7);
      cx.drawImage(cache.back, 0, y + dy, W, 3, dx, y, W, 3);
    }
  }
  if (Ls.cliff.show) { cx.drawImage(cache.cliff, 0, 0); cx.globalCompositeOperation = 'lighter'; cx.globalAlpha = rimK; cx.drawImage(cache.cliffRim, 0, 0); cx.globalAlpha = 1; cx.globalCompositeOperation = 'source-over'; }
  ask.drawSlot(cx, 3, t);
  if (Ls.near.show) { cx.drawImage(cache.near, 0, 0); cx.globalCompositeOperation = 'lighter'; cx.globalAlpha = rimK; cx.drawImage(cache.nearRim, 0, 0); cx.globalAlpha = 1; cx.globalCompositeOperation = 'source-over'; }
  ask.drawSlot(cx, 4, t);
  if (air.show) {
    drawParticles(cx, 1, P); drawParticles(cx, 2, P);
    const off = (t * 11 * wind + 400) % 1536; cx.globalAlpha = clamp(hz * 0.8, 0, 1); const y = 0.8 * H;
    cx.drawImage(cache.hazeB, -off, y); cx.drawImage(cache.hazeB, 1536 - off, y); cx.globalAlpha = 1;
    cx.drawImage(cache.air, 0, 0);
  }
  if (sunsOn && geo.suns[0]) { cx.globalCompositeOperation = 'lighter'; drawBloom(cx, cache.bloom[0], geo.suns[0], H * 0.62, 0.05 * (0.4 + gl) * up); cx.globalAlpha = 1; cx.globalCompositeOperation = 'source-over'; }
  ask.drawSlot(cx, 5, t);
  // finish: vignette, then grain at 24 steps a second
  cx.drawImage(fin.vig, 0, 0);
  fin.pat = fin.pat || cx.createPattern(fin.grain, 'repeat');
  const gi = Math.floor(t * 24), gox = (hash(gi, 3) * 512) | 0, goy = (hash(gi, 9) * 512) | 0;
  cx.save(); cx.translate(-gox, -goy); cx.fillStyle = fin.pat; cx.fillRect(gox, goy, W, H); cx.restore();
  window.__sceneFrames = (window.__sceneFrames || 0) + 1;
}

// ------------------------------------------------------------ refrains from the Grow plan
const S = defaultSettings('Desert Dusk');
const kit = new Kit(48000);
const player = new Player(kit, S, { onState: (s) => setPlayUi(s), onEnd: () => setPlayUi('idle') });
let loadPromise = null;
const ensureKit = () => (loadPromise = loadPromise || kit.loadStarter('sounds/folding-city/').catch((e) => { loadPromise = null; throw e; }));
const session = (type) => { try { if (navigator.audioSession) navigator.audioSession.type = type; } catch {} };
let fake = null; // test: { refrains: [...] } overrides the Grow plan, position is the scene clock
function refrainInfo(pos) {
  const refs = fake ? fake.refrains : player.plan.refrains;
  let target = 0, cur = null, next = null;
  for (const r of refs) {
    if (pos >= r.start - 3 && pos < r.end) { target = Math.max(target, r.peak ? 0.25 : 0.18); }
    if (pos >= r.start && pos < r.end) cur = r;
    if (!next && r.start > pos) next = r;
  }
  return { target, cur, next };
}
function pulseUi(pos, active) {
  const el = $('#refrain'), nx = $('#next');
  if (!active) { el.hidden = true; nx.textContent = ''; return; }
  const { cur, next } = refrainInfo(pos);
  el.hidden = !cur;
  nx.textContent = cur ? '' : next ? `Next refrain ${fmt(next.start - pos)}` : '';
}
let uiTick = 0;
function liftFrom(pos, active) {
  if (!active) { sim.liftTarget = 0; return; }
  sim.liftTarget = refrainInfo(pos).target;
}

// ------------------------------------------------------------ main loop
let manual = false, t0 = performance.now() / 1000;
function frame() {
  if (!manual) {
    const playing = player.state === 'playing', pos = playing ? player.position : 0;
    liftFrom(fake ? pos : pos, playing || !!fake);
    advance(performance.now() / 1000 - t0);
    composite(); ask.drawPreviews(sim.t);
    if (++uiTick % 6 === 0) { pulseUi(pos, playing); if (playing) $('#next').dataset.pos = pos.toFixed(1); }
  }
  requestAnimationFrame(frame);
}

// ------------------------------------------------------------ UI
const slidersEl = $('#sliders');
function sliderRow(parent, label, get, set, o) {
  const w = document.createElement('label'); w.className = 'gr-slider';
  w.innerHTML = `<span class="ds-label">${label}</span><output></output><input type="range" min="${o.min}" max="${o.max}" step="${o.step}" aria-label="${label}">`;
  const inp = w.querySelector('input'), out = w.querySelector('output');
  const paint = () => { const v = get(); inp.value = v; inp.style.setProperty('--p', ((v - o.min) / (o.max - o.min)) * 100 + '%'); out.textContent = o.fmt ? o.fmt(v) : `${Math.round(v * 100)}%`; };
  inp.addEventListener('input', () => { set(+inp.value); paint(); if (!o.light) dirty = true; persist(); });
  paint(); parent.appendChild(w); return w;
}
function segEl(label, opts, idx, onPick) {
  const d = document.createElement('div'); d.className = 'ds-seg'; d.setAttribute('role', 'radiogroup'); d.setAttribute('aria-label', label);
  d.innerHTML = opts.map((o, i) => `<button type="button" class="ds-seg__opt" role="radio" aria-checked="${i === idx}" data-value="${i}">${o}</button>`).join('');
  window.DS && window.DS.seg(d);
  d.addEventListener('seg-change', (e) => onPick(+e.detail.value));
  return d;
}
function field(label, child) { const f = document.createElement('div'); f.className = 'gr-field'; f.innerHTML = `<span class="ds-label">${label}</span>`; f.appendChild(child); return f; }

function paintLayerSeg() {
  document.querySelectorAll('#layerSeg .ds-seg__opt').forEach((b) => b.classList.toggle('is-off', !st.layers[b.dataset.value].show));
}
function buildPanel() {
  const id = st.layer, D = layerDef(id), L = st.layers[id], panel = $('#panel');
  panel.innerHTML = '';
  const hasPhoto = !!photos[id];
  panel.appendChild(field('Layer', segEl('Show or hide', ['Show', 'Hide'], L.show ? 0 : 1, (i) => { L.show = i === 0; dirty = true; persist(); paintLayerSeg(); })));
  panel.appendChild(field('Look', segEl('Look', hasPhoto ? [...D.looks, 'Photo'] : D.looks, Math.min(L.look, hasPhoto ? D.looks.length : D.looks.length - 1), (i) => { L.look = i; dirty = true; persist(); buildPanel(); })));
  const sl = document.createElement('div'); sl.id = 'lsliders'; sl.className = 'sc-sub'; sl.style.borderTop = '0'; sl.style.paddingTop = '0';
  panel.appendChild(sl);
  if (!photoOf(id)) D.sliders.forEach((d) => sliderRow(sl, d.label, () => L.v[d.id], (v) => { L.v[d.id] = v; }, { min: 0, max: 1, step: 0.01 }));
  if (id !== 'air' || hasPhoto) {
    sliderRow(sl, 'Position X', () => L.x, (v) => { L.x = v; }, { min: -0.4, max: 0.4, step: 0.005, fmt: (v) => `${Math.round(v * 100)}` });
    sliderRow(sl, 'Position Y', () => L.y, (v) => { L.y = v; }, { min: -0.25, max: 0.25, step: 0.005, fmt: (v) => `${Math.round(v * 100)}` });
    sliderRow(sl, 'Scale', () => L.s, (v) => { L.s = v; }, { min: 0.6, max: 1.6, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` });
  }
  const ph = document.createElement('div'); ph.className = 'sc-sub';
  const row = document.createElement('div'); row.className = 'sc-photo';
  row.innerHTML = `<button type="button" class="ds-btn ds-btn--raised" data-act="import">${hasPhoto ? 'Replace Photo' : 'Import Photo'}</button>${hasPhoto ? '<button type="button" class="ds-btn ds-btn--ghost" data-act="remove">Remove Photo</button>' : ''}<input type="file" accept="image/*" aria-label="${D.name} photo">`;
  ph.appendChild(row);
  const file = row.querySelector('input');
  row.addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; if (b.dataset.act === 'import') file.click(); else removePhoto(id); });
  file.addEventListener('change', async () => { const f = file.files[0]; if (!f) return; try { await importPhoto(id, f); status(''); } catch (err) { status('That file is not an image.'); } });
  if (hasPhoto) {
    sliderRow(ph, 'Opacity', () => L.op, (v) => { L.op = v; }, { min: 0, max: 1, step: 0.01 });
    if (id === 'sky') sliderRow(ph, 'Tint', () => L.tint, (v) => { L.tint = v; }, { min: 0, max: 1, step: 0.01 });
  }
  panel.appendChild(ph);
}
$('#layerSeg').addEventListener('seg-change', (e) => { st.layer = e.detail.value; persist(); buildPanel(); });

// global sliders: time of day
sliderRow(slidersEl, 'Time', () => st.time, (v) => { st.time = v; }, { min: 0, max: 1, step: 0.005, fmt: timeName });
const seedEl = $('#seed');
const paintSeed = () => { seedEl.value = String(st.seed); };
$('#reseed').addEventListener('click', () => { st.seed = 1 + Math.floor(Math.random() * 999999998); paintSeed(); dirty = true; persist(); });
seedEl.addEventListener('change', () => { const v = parseInt(seedEl.value, 10); if (Number.isFinite(v) && v >= 0) { st.seed = v >>> 0; dirty = true; persist(); } paintSeed(); });

// transport
const playBtn = $('#play');
function setPlayUi(s) {
  const playing = s === 'playing';
  $('#playWord').textContent = playing ? 'Pause' : 'Play';
  playBtn.setAttribute('aria-label', playing ? 'Pause' : 'Play');
  playBtn.querySelector('use').setAttribute('href', `ds/icons/sprite.svg#i-${playing ? 'pause' : 'play'}`);
  playBtn.removeAttribute('aria-busy');
  if (!playing) pulseUi(0, false);
}
playBtn.addEventListener('click', async () => {
  try {
    if (player.state === 'playing') { await player.pause(); return; }
    playBtn.setAttribute('aria-busy', 'true'); $('#playWord').textContent = 'Loading';
    session('playback');
    player.unlock().catch(() => {}); // inside the tap, or iOS refuses audio that starts after an await
    await ensureKit();
    await player.start();
  } catch (err) { console.error(err); $('#playWord').textContent = 'Play'; playBtn.removeAttribute('aria-busy'); status('Audio could not start.'); }
});

// export
const statusEl = $('#status');
function status(html) { statusEl.innerHTML = html || ''; }
const MIMES = ['video/mp4;codecs=avc1.42E01E,mp4a.40.2', 'video/mp4', 'video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm'];
const pickMime = () => (window.MediaRecorder ? MIMES.find((m) => safe(() => MediaRecorder.isTypeSupported(m), false)) : null);
let exporting = false, lastUrl = null;
async function exportPreview(seconds) {
  if (exporting) return;
  if (!window.MediaRecorder || !cv.captureStream) { status('This browser cannot record video.'); return; }
  const mime = pickMime();
  if (!mime) { status('No video codec is available here.'); return; }
  exporting = true; const btn = $('#export'); btn.disabled = true;
  try {
    player.stop(); session('playback');
    player.unlock().catch(() => {}); await ensureKit(); await player.start();
    const dest = player.ctx.createMediaStreamDestination();
    player.g.shaper.connect(dest);
    const stream = cv.captureStream(30);
    dest.stream.getAudioTracks().forEach((t) => stream.addTrack(t));
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 6000000 }), chunks = [];
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    const done = new Promise((res) => { rec.onstop = res; });
    rec.start(1000);
    const t1 = performance.now();
    const timer = setInterval(() => status(`Recording ${fmt((performance.now() - t1) / 1000)} of ${fmt(seconds)}`), 500);
    status(`Recording 0:00 of ${fmt(seconds)}`);
    await new Promise((r) => setTimeout(r, seconds * 1000));
    clearInterval(timer); rec.stop(); await done;
    try { player.g.shaper.disconnect(dest); } catch {}
    player.stop();
    const blob = new Blob(chunks, { type: mime.split(';')[0] });
    if (!blob.size) { status('The recording came out empty.'); return; }
    if (lastUrl) URL.revokeObjectURL(lastUrl);
    lastUrl = URL.createObjectURL(blob);
    const ext = mime.startsWith('video/mp4') ? 'mp4' : 'webm', name = `scene-preview.${ext}`;
    status(`Done ${(blob.size / 1e6).toFixed(1)} MB. <a href="${lastUrl}" download="${name}" id="saveLink">Save ${ext.toUpperCase()}</a>`);
    window.SceneTest.lastExport = { size: blob.size, type: blob.type, name };
    const a = document.createElement('a'); a.href = lastUrl; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  } catch (err) { console.error(err); status('Export failed.'); } finally { exporting = false; btn.disabled = false; }
}
$('#export').addEventListener('click', () => exportPreview(window.SceneTest.exportSeconds || 60));

// select and ask: generated elements drawn above a named base layer
const ask = createAsk({ W, H, $, clamp, st: () => st, persist, geo, sim, cv, status, segEl, sliderRow, mk, timeName, dirtyAll: () => { dirty = true; }, renderNow: () => composite() });

// ------------------------------------------------------------ test hooks
function regionDiff(tA, tB) {
  if (tA < sim.t - 1e-6) resetSim();
  const rb = mk(W, H), rx = rb.getContext('2d', { willReadFrequently: true });
  const grab = (t) => { advance(t); composite(); rx.drawImage(cv, 0, 0); return rx.getImageData(0, 0, W, H).data; };
  const a = grab(tA), b = grab(tB);
  const mask = (draw) => { const c = mk(W, H), x = c.getContext('2d', { willReadFrequently: true }); x.fillStyle = '#fff'; draw(x); return x.getImageData(0, 0, W, H).data; };
  const cp = geo.cliffPoly, regions = {};
  if (cp) {
    const { pts, m, base, topY } = cp, yCut = topY + (base - topY) * 0.55;
    regions.cliffUpper = mask((x) => { x.setTransform(m.s, 0, 0, m.s, m.e, m.f); x.beginPath(); pts.forEach((p, i) => (i ? x.lineTo(p[0], Math.min(p[1], 1e9)) : x.moveTo(p[0], p[1]))); x.lineTo(pts[pts.length - 1][0], base + 700); x.lineTo(pts[0][0], base + 700); x.closePath(); x.clip(); x.setTransform(1, 0, 0, 1, 0, 0); x.fillRect(0, 0, W, m.s * yCut + m.f); });
  }
  regions.crestBand = mask((x) => { x.fillStyle = '#fff'; for (const [top] of [[geo.topNear], [geo.topFar]]) for (let i = 0; i < top.length; i++) if (top[i] < H - 1) x.fillRect(i * 4, top[i] - 40, 4, 40); });
  regions.sky = mask((x) => { x.fillRect(0, 0, W, 0.3 * H); });
  const out = { frame: 0 };
  const stat = (name, mk2) => { let s = 0, n = 0; for (let i = 0; i < W * H; i++) { if (mk2 && mk2[i * 4 + 3] < 200) continue; const o = i * 4; s += (Math.abs(a[o] - b[o]) + Math.abs(a[o + 1] - b[o + 1]) + Math.abs(a[o + 2] - b[o + 2])) / 3; n++; } out[name] = { mean: +(s / Math.max(1, n)).toFixed(4), px: n }; };
  stat('frame', null); for (const k in regions) stat(k, regions[k]);
  return out;
}
window.SceneTest = {
  exportSeconds: 0, st: () => st, player, kit, geo, sim,
  ready: () => ensureKit().then(() => true),
  setManual(v) { manual = v; },
  renderAt(t, refrains) { manual = true; if (t < sim.t - 1e-6) resetSim(); fake = refrains ? { refrains } : null; liftFrom(t, !!refrains); advance(t); composite(); ask.drawPreviews(t, true); return true; },
  fakeRefrains(list) { fake = list ? { refrains: list } : null; },
  regionDiff,
  setState(patch) { Object.assign(st, patch); dirty = true; buildPanel(); },
  dirty() { dirty = true; },
  photos, ask: ask.test, buildMs,
};

// ------------------------------------------------------------ boot
paintSeed(); paintLayerSeg();
(function boot() {
  const idx = LAYERS.findIndex((l) => l.id === st.layer);
  const segEl0 = $('#layerSeg');
  const go = () => { if (segEl0.dsSeg) segEl0.dsSeg.select(idx); else document.querySelectorAll('#layerSeg .ds-seg__opt').forEach((b, k) => b.setAttribute('aria-checked', String(k === idx))); };
  setTimeout(go, 0);
})();
renderAll(); for (let i = 0; i < 360; i++) simStep(DT); t0 = performance.now() / 1000 - sim.t; buildPanel(); loadPhotos().catch(() => {});
ensureKit().catch(() => {});
requestAnimationFrame(frame);
