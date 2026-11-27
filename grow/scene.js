// Scene: a code-drawn matte painting of one world ("Arrakis, last light") that animates under a Grow piece.
// Shapes are drawn once into cached layers. Only light, sand, haze and stars move, locally. Cliff and dunes never move.
import { Kit, Player, defaultSettings, mulberry32 } from './grow.js';

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
function ridgeYs(o) {
  const n = noise1(o.seed), n2 = noise1(o.seed + 99);
  const N = Math.ceil((o.x1 - o.x0) / o.step) + 1, ys = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    const x = o.x0 + i * o.step;
    let h;
    if (o.kind === 'saw') {
      const u = x * o.freq + 2.2 * fbm(n, x * o.freq * 0.3, 3), k = Math.floor(u), p = u - k;
      const a = 0.4 + 0.6 * hash(k, o.seed), pk = o.peak ?? 0.3;
      const q = p < pk ? p / pk : (1 - p) / (1 - pk);
      h = (o.sharp ? Math.pow(q, 1.55) : q * q * (3 - 2 * q)) * a;
      h += (fbm(n2, x * 0.02, 3) - 0.5) * 0.12;
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
  return { time: 0.3, seed: 20261124, layer: 'sky', layers };
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
  persist(); dirty = true; buildPanel();
}
async function removePhoto(id) {
  delete photos[id]; await idbDel(id).catch(() => {});
  const L = st.layers[id]; if (L.look >= layerDef(id).looks.length) L.look = 0;
  persist(); dirty = true; buildPanel();
}
async function loadPhotos() {
  const all = await idbAll();
  for (const rec of all) { try { photos[rec.layer] = { img: await imgFromBlob(rec.blob), name: rec.name }; } catch (e) {} }
  dirty = true; buildPanel();
}

// ------------------------------------------------------------ caches
const cache = {
  sky: mk(W, H), suns: mk(W, H), air: mk(W, H),
  far: mk(W, H), farRim: mk(W, H), cliff: mk(W, H), cliffRim: mk(W, H), near: mk(W, H), nearRim: mk(W, H),
  hazeA: mk(1536, 300), hazeB: mk(1536, 200),
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
  ctx.save(); setT(ctx, m);
  const g = ctx.createLinearGradient(0, 0, 0, H * 0.72);
  g.addColorStop(0, rgba(P.top)); g.addColorStop(0.5, rgba(P.mid)); g.addColorStop(0.87, rgba(P.hor)); g.addColorStop(1, rgba(mixC(P.hor, P.haze, 0.5)));
  ctx.fillStyle = g; ctx.fillRect(-W, -H, 3 * W, 4 * H);
  const r = mulberry32(seed), cl = L.v.clouds, sx = geo.suns[0] ? geo.suns[0].x : 0.7 * W, hy = 0.64 * H;
  const blob = (x, y, rx, ry, col, a) => {
    ctx.save(); ctx.translate(x, y); ctx.scale(rx, ry);
    const rg = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
    rg.addColorStop(0, rgba(col, a)); rg.addColorStop(0.5, rgba(col, a * 0.45)); rg.addColorStop(1, rgba(col, 0));
    ctx.fillStyle = rg; ctx.beginPath(); ctx.arc(0, 0, 1, 0, 7); ctx.fill(); ctx.restore();
  };
  // horizon glow
  blob(sx, hy, W * 0.62, H * 0.3, P.glow, 0.62); blob(sx, hy, W * 0.22, H * 0.12, P.sun, 0.45);
  if (L.look === 1) {
    const n = 5 + Math.round(cl * 8);
    for (let i = 0; i < n; i++) {
      const y = H * (0.05 + 0.5 * r()), len = W * (0.18 + 0.4 * r()), x = W * (-0.1 + 1.2 * r()), th = H * (0.014 + 0.03 * r());
      const near = Math.exp(-Math.pow((y - hy) / (0.28 * H), 2)) * Math.exp(-Math.pow((x - sx) / (0.7 * W), 2));
      blob(x, y, len, th, mixC(P.mid, P.glow, near), (0.07 + 0.22 * near) * (0.35 + cl));
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

function drawRidge(ctx, rim, m, b, P) {
  const ys = ridgeYs(b), N = ys.length, x0 = b.x0, step = b.step;
  let minY = 1e9; for (let i = 0; i < N; i++) minY = Math.min(minY, ys[i]);
  ctx.save(); setT(ctx, m);
  const g = ctx.createLinearGradient(0, minY, 0, b.bottom);
  g.addColorStop(0, rgba(b.top)); g.addColorStop(1, rgba(b.bot));
  ctx.beginPath(); ctx.moveTo(x0, b.bottom + 600);
  for (let i = 0; i < N; i++) ctx.lineTo(x0 + i * step, ys[i]);
  ctx.lineTo(x0 + (N - 1) * step, b.bottom + 600); ctx.closePath(); ctx.fillStyle = g; ctx.fill();
  const litS = strip(b.litCol), shS = strip(b.shadeCol), lit = new Float32Array(N);
  let maxY = -1e9; for (let i = 0; i < N; i++) maxY = Math.max(maxY, ys[i]);
  const yA = Math.max(0, Math.floor(minY) - 2), yB = Math.min(shadeTmp.height, Math.ceil(maxY + b.depth * 1.8));
  const tx = shadeTmp.getContext('2d'); tx.setTransform(1, 0, 0, 1, 0, 0); tx.clearRect(0, yA, shadeTmp.width, yB - yA);
  const wN = 7;
  for (let i = wN; i < N - wN; i++) {
    const x = x0 + i * step, slope = (ys[i + wN] - ys[i - wN]) / (2 * wN * step), d = Math.hypot(slope, 1);
    lit[i] = litAt(m.s * x + m.e, m.s * ys[i] + m.f, slope / d, -1 / d);
    const l = lit[i], px = i * step, py = Math.floor(ys[i]);
    if (l > 0.04) { tx.globalAlpha = Math.pow(Math.min(1, l), 1.1) * b.litAmt; tx.drawImage(litS, px, py, step, b.depth * 0.9); }
    else if (l < -0.04) { tx.globalAlpha = Math.min(1, -l) * b.shadeAmt; tx.drawImage(shS, px, py, step, b.depth * 1.6); }
  }
  tx.globalAlpha = 1;
  ctx.drawImage(shadeTmp, 0, yA, shadeTmp.width, yB - yA, x0, yA, shadeTmp.width, yB - yA);
  if (b.ripples > 0.02) {
    ctx.lineWidth = 1; ctx.lineCap = 'round';
    for (let k = 0, off = 7; k < 9 && off < b.depth * 1.5; k++, off *= 1.22) {
      for (let i = 4; i < N - 4; i += 2) {
        if (lit[i] < 0.12) continue;
        const wob = Math.sin(i * 0.9 + k * 2.1) * 0.9;
        ctx.strokeStyle = rgba(b.litCol, 0.18 * lit[i] * b.ripples * (1 - off / (b.depth * 1.6)));
        ctx.beginPath(); ctx.moveTo(x0 + i * step, ys[i] + off + wob); ctx.lineTo(x0 + (i + 2) * step, ys[i + 2] + off + wob); ctx.stroke();
      }
    }
  }
  ctx.restore();
  rim.save(); setT(rim, m); rim.globalCompositeOperation = 'destination-out'; rim.fillStyle = '#000';
  rim.beginPath(); rim.moveTo(x0, b.bottom + 600); for (let i = 0; i < N; i += 2) rim.lineTo(x0 + i * step, ys[i] + 1.5); rim.lineTo(x0 + (N - 1) * step, b.bottom + 600); rim.closePath(); rim.fill();
  rim.globalCompositeOperation = 'source-over'; rim.lineCap = 'round'; rim.lineJoin = 'round';
  for (let i = 2; i < N - 4; i += 2) {
    const l = lit[i]; if (l < 0.12) continue;
    const a = Math.pow(Math.min(1, l * 1.25), 1.2) * 0.62, xa = x0 + i * step, xb = x0 + (i + 2) * step;
    rim.strokeStyle = rgba(P.rim, a * 0.2 * b.rimAmt); rim.lineWidth = 6; rim.beginPath(); rim.moveTo(xa, ys[i] + 1); rim.lineTo(xb, ys[i + 2] + 1); rim.stroke();
    rim.strokeStyle = rgba(mixC(P.rim, [255, 244, 220], 0.4), a * b.rimAmt); rim.lineWidth = 1.7; rim.beginPath(); rim.moveTo(xa, ys[i]); rim.lineTo(xb, ys[i + 2]); rim.stroke();
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
  spec.forEach((s, i) => {
    const d = clamp(s.d + (hz - 0.5) * 0.45, 0.05, 0.95), farC = mixC(P.far, P.haze, d), fog = mixC(P.haze, P.hor, 0.45);
    const rd = drawRidge(ctx, rim, m, {
      x0: -W * 0.7, x1: W * 1.7, step: 2, seed: seed + i * 31, kind: s.k, freq: s.f, base: s.base * H, amp: amp * s.a, sharp: false, peak: 0.4,
      top: farC, bot: mixC(farC, fog, 0.8), bottom: 0.7 * H, litCol: mixC(P.lit, P.haze, 0.35), shadeCol: mixC(P.shade, P.far, 0.5), litAmt: 0.55 * (1 - d * 0.5), shadeAmt: 0.35, depth: 50, ripples: 0, rimAmt: 0.36 * (1 - d * 0.7),
    }, P);
    recordTop(geo.topFar, geo.peakFar, rd, m);
  });
  finishPeaks(geo.topFar, geo.peakFar);
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
function drawCliff(ctx, rim, P, L, seed) {
  const m = mat('cliff'), r = mulberry32(seed), base = ANCH.cliff[1];
  const h = (0.24 + 0.34 * L.v.height) * H, w = (0.1 + 0.2 * L.v.width) * W * (L.look === 1 ? 0.7 : 1), cx = 0.30 * W;
  let pts = CLIFFS[L.look % 3].map(([x, y]) => [cx + x * w, base - y * h]);
  pts = jag(pts, r, 0.2, 4);
  const xs = pts.map((p) => p[0]), minX = Math.min(...xs), maxX = Math.max(...xs), topY = Math.min(...pts.map((p) => p[1]));
  geo.cliffPoly = { pts, m, base, topY };
  const sunX = geo.suns[0] ? geo.suns[0].x : W, side = sunX > m.s * cx + m.e ? 1 : -1;
  const body = mixC(P.cliff, P.haze, 0.1), litC = P.lit, fogC = mixC(P.haze, P.hor, 0.4);
  ctx.save(); setT(ctx, m);
  const poly = () => { ctx.beginPath(); ctx.moveTo(minX, base + 700); pts.forEach((p) => ctx.lineTo(p[0], p[1])); ctx.lineTo(maxX, base + 700); ctx.closePath(); };
  poly();
  const cxm = (minX + maxX) / 2;
  const g = ctx.createLinearGradient(cxm - side * w * 1.1, 0, cxm + side * w * 1.1, 0);
  g.addColorStop(0, rgba(mixC(body, P.shade, 0.35))); g.addColorStop(0.5, rgba(body)); g.addColorStop(1, rgba(mixC(body, litC, 0.5)));
  ctx.fillStyle = g; ctx.fill();
  ctx.save(); poly(); ctx.clip();
  // strata and gullies
  const sv = L.v.strata, n = noise1(seed + 5);
  for (let y = topY + 6; y < base; y += 5 + r() * 13) {
    const dark = r() < 0.6; ctx.lineWidth = 1 + r() * 2.2;
    ctx.strokeStyle = dark ? rgba(P.shade, (0.1 + 0.22 * r()) * sv * 1.6) : rgba(litC, (0.04 + 0.1 * r()) * sv * 1.6);
    ctx.beginPath();
    for (let x = minX, k = 0; x <= maxX; x += 14, k++) { const yy = y + (n(x * 0.02 + y * 0.01) - 0.5) * 5; if (k === 0) ctx.moveTo(x, yy); else ctx.lineTo(x, yy); }
    ctx.stroke();
  }
  for (let i = 0; i < 90; i++) {
    const x = lerp(minX + w * 0.3, maxX - w * 0.3, r()), y = topY + r() * (base - topY) * 0.6, len = 20 + r() * h * 0.45;
    ctx.strokeStyle = rgba(P.shade, 0.06 + 0.14 * r() * sv); ctx.lineWidth = 1 + r() * 3;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + (r() - 0.5) * 8, y + len); ctx.stroke();
  }
  for (let i = 0; i < 2600; i++) {
    const x = lerp(minX, maxX, r()), y = lerp(topY, base, r() * r()), lightDot = r() < 0.4;
    ctx.fillStyle = lightDot ? rgba(litC, 0.07 * sv) : rgba(P.shade, 0.1 * sv); ctx.fillRect(x, y, 1 + r() * 2.5, 1 + r() * 2);
  }
  for (let i = 0; i < 16; i++) {
    const fx = lerp(minX + w * 0.2, maxX - w * 0.2, r()), fw = w * (0.06 + 0.22 * r()), dark = r() < 0.55;
    const fg2 = ctx.createLinearGradient(0, topY, 0, base);
    const c = dark ? rgba(P.shade, 0.06 + 0.1 * r()) : rgba(litC, 0.03 + 0.05 * r());
    fg2.addColorStop(0, c); fg2.addColorStop(1, c.replace(/[\d.]+\)$/, '0)'));
    ctx.fillStyle = fg2; ctx.fillRect(fx, topY, fw, base - topY);
  }
  // light along sun-facing edges, falling off inward
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1], dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
    const l = litAt(m.s * a[0] + m.e, m.s * a[1] + m.f, dy / len, -dx / len); if (l < 0.1) continue;
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    for (const [lw, al] of [[46, 0.1], [22, 0.16], [9, 0.22]]) { ctx.strokeStyle = rgba(litC, al * Math.min(1, l * 1.2)); ctx.lineWidth = lw; ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); }
  }
  // atmospheric fade at the base
  const fg = ctx.createLinearGradient(0, base - h * 0.42, 0, base + 10);
  fg.addColorStop(0, rgba(fogC, 0)); fg.addColorStop(0.7, rgba(fogC, 0.3)); fg.addColorStop(1, rgba(fogC, 0.8));
  ctx.fillStyle = fg; ctx.fillRect(minX, base - h * 0.42, maxX - minX, h * 0.42 + 700);
  ctx.restore();
  ctx.restore();
  rim.save(); setT(rim, m); rim.lineCap = 'round'; rim.lineJoin = 'round';
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1], dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
    if (a[1] > base - h * 0.04) continue;
    const l = litAt(m.s * a[0] + m.e, m.s * a[1] + m.f, dy / len, -dx / len); if (l < 0.1) continue;
    const al = Math.pow(Math.min(1, l * 1.2), 1.1);
    rim.strokeStyle = rgba(P.rim, al * 0.14); rim.lineWidth = 8; rim.beginPath(); rim.moveTo(a[0], a[1]); rim.lineTo(b[0], b[1]); rim.stroke();
    rim.strokeStyle = rgba(mixC(P.rim, [255, 244, 220], 0.45), al * 0.8); rim.lineWidth = 1.6; rim.beginPath(); rim.moveTo(a[0], a[1]); rim.lineTo(b[0], b[1]); rim.stroke();
  }
  rim.restore();
  if (photos.cliff) drawPhoto(ctx, 'cliff', m);
}

function drawNear(ctx, rim, P, L, seed) {
  const m = mat('near'), k = L.v.height, rp = L.v.ripples;
  const look = L.look;
  const fq = look === 1 ? 1 / 300 : look === 2 ? 1 / 720 : 1 / 420, sharp = look === 1, peak = look === 1 ? 0.22 : 0.3;
  const a1 = (look === 2 ? 0.045 : 0.07 + 0.12 * k) * H, a2 = (look === 2 ? 0.03 : 0.045 + 0.08 * k) * H;
  const back = mixC(P.near, P.haze, 0.14), front = mixC(P.near, [0, 0, 0], 0.12);
  geo.topNear.fill(H);
  const bands = [
    { base: 0.735, a: (0.035 + 0.06 * k) * H, f: fq * 0.8, col: mixC(P.near, P.haze, 0.42), litAmt: 0.85, ripples: 0, depth: 110, seedo: 7 },
    { base: 0.835, a: a1, f: fq, col: back, litAmt: 0.85, ripples: rp * 0.5, depth: 130, seedo: 3 },
    { base: 0.94, a: a2, f: fq * 1.25, col: front, litAmt: 0.75, ripples: rp, depth: 110, seedo: 11 },
  ];
  bands.forEach((b) => {
    const rd = drawRidge(ctx, rim, m, {
      x0: -W * 0.7, x1: W * 1.7, step: 2, seed: seed + b.seedo, kind: 'saw', freq: b.f, base: b.base * H, amp: b.a, sharp, peak,
      top: mixC(b.col, P.lit, 0.1), bot: mixC(b.col, [0, 0, 0], 0.25), bottom: H, litCol: P.lit, shadeCol: P.shade, litAmt: b.litAmt, shadeAmt: 0.55, depth: b.depth, ripples: b.ripples, rimAmt: 1,
    }, P);
    recordTop(geo.topNear, geo.peakNear, rd, m);
  });
  finishPeaks(geo.topNear, geo.peakNear);
  if (photos.near) drawPhoto(ctx, 'near', m);
}

function makeHaze(tile, P, seed, band, tall) {
  const x = tile.getContext('2d'), w = tile.width, h = tile.height, r = mulberry32(seed);
  x.clearRect(0, 0, w, h);
  const col = mixC(P.haze, P.hor, 0.3);
  const n = band === 'A' ? 22 : 16;
  for (let i = 0; i < n; i++) {
    const cx = r() * w, cy = h * (0.35 + 0.5 * r()), rx = w * (0.07 + 0.14 * r()), ry = h * (0.12 + 0.3 * r()), a = (band === 'A' ? 0.2 : 0.12) * (0.5 + r());
    for (const ox of [-w, 0, w]) {
      x.save(); x.translate(cx + ox, cy); x.scale(rx, ry);
      const g = x.createRadialGradient(0, 0, 0, 0, 0, 1);
      g.addColorStop(0, rgba(col, a)); g.addColorStop(0.55, rgba(col, a * 0.4)); g.addColorStop(1, rgba(col, 0));
      x.fillStyle = g; x.beginPath(); x.arc(0, 0, 1, 0, 7); x.fill(); x.restore();
    }
  }
}

// ------------------------------------------------------------ render all cached layers
function clear(c) { const x = c.getContext('2d'); x.setTransform(1, 0, 0, 1, 0, 0); x.clearRect(0, 0, c.width, c.height); return x; }
function renderAll() {
  const P = geo.P = palette(st.time);
  computeSuns(P);
  const Ls = st.layers;
  // sky
  { const x = clear(cache.sky); if (Ls.sky.show) drawSky(x, P, Ls.sky, lseed('sky'), mat('sky')); }
  { const x = clear(cache.suns); if (Ls.suns.show && photos.suns) drawPhoto(x, 'suns', mat('suns')); }
  // stars (positions only depend on seed)
  { const r = mulberry32(lseed('sky') + 77); geo.stars = []; for (let i = 0; i < 170; i++) geo.stars.push({ x: r() * W, y: H * 0.5 * Math.pow(r(), 1.3), r: 0.5 + r() * 1.1 * (r() < 0.12 ? 1.8 : 1), ph: r() * 7, sp: 0.4 + r() * 1.6 }); }
  { const x = clear(cache.far), rx = clear(cache.farRim); geo.topFar.fill(H); if (Ls.far.show) { if (!photoOf('far')) drawFar(x, rx, P, Ls.far, lseed('far')); else drawPhoto(x, 'far', mat('far')); } }
  { const x = clear(cache.cliff), rx = clear(cache.cliffRim); geo.cliffPoly = null; if (Ls.cliff.show) { if (!photoOf('cliff')) drawCliff(x, rx, P, Ls.cliff, lseed('cliff')); else drawPhoto(x, 'cliff', mat('cliff')); } }
  { const x = clear(cache.near), rx = clear(cache.nearRim); geo.topNear.fill(H); if (Ls.near.show) { if (!photoOf('near')) drawNear(x, rx, P, Ls.near, lseed('near')); else drawPhoto(x, 'near', mat('near')); } }
  { const x = clear(cache.air); if (Ls.air.show && photos.air) drawPhoto(x, 'air', mat('air')); makeHaze(cache.hazeA, P, lseed('air') + 1, 'A'); makeHaze(cache.hazeB, P, lseed('air') + 2, 'B'); }
  dirty = false;
}

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
function glowAt(ctx, s, R, a, col) {
  const g = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, R);
  g.addColorStop(0, rgba(col, a)); g.addColorStop(0.2, rgba(col, a * 0.55)); g.addColorStop(0.55, rgba(col, a * 0.15)); g.addColorStop(1, rgba(col, 0));
  ctx.fillStyle = g; ctx.fillRect(s.x - R, s.y - R, 2 * R, 2 * R);
}
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
  if (dirty) renderAll();
  const P = geo.P, Ls = st.layers, t = sim.t, lift = sim.lift;
  cx.setTransform(1, 0, 0, 1, 0, 0); cx.globalAlpha = 1; cx.globalCompositeOperation = 'source-over';
  cx.fillStyle = rgba(P.top); cx.fillRect(0, 0, W, H);
  if (Ls.sky.show) cx.drawImage(cache.sky, 0, 0);
  // stars
  if (Ls.sky.show && !photoOf('sky')) {
    const sa = sm(0.5, 0.95, st.time) * Ls.sky.v.stars;
    if (sa > 0.01) {
      cx.save(); cx.globalCompositeOperation = 'lighter';
      for (const s of geo.stars) {
        const a = sa * sm(0.5 * H, 0, s.y) * (0.7 + 0.3 * Math.sin(t * s.sp + s.ph)); if (a < 0.02) continue;
        cx.fillStyle = `rgba(255,244,230,${a.toFixed(3)})`; cx.fillRect(s.x, s.y, s.r, s.r);
      }
      cx.restore();
    }
  }
  // suns: glow breathes a little, the disk does not
  if (Ls.suns.show && !photoOf('suns')) {
    const gl = Ls.suns.v.glow, breathe = 1 + 0.045 * Math.sin(t * 0.55) + 0.02 * Math.sin(t * 1.3 + 1.7), up = 1 + lift;
    cx.save(); cx.globalCompositeOperation = 'lighter';
    geo.suns.forEach((s, i) => {
      const k = breathe * (i ? 1 + 0.03 * Math.sin(t * 0.7 + 2) : 1) * s.g;
      glowAt(cx, s, s.r * (9 + 6 * gl) * (1 + 0.03 * (breathe - 1) * 10), 0.3 * (0.4 + gl) * k * up, P.glow);
      glowAt(cx, s, s.r * 3.4, 0.5 * k * up, mixC(P.glow, s.col, 0.5));
    });
    cx.restore();
    geo.suns.forEach((s) => {
      const g = cx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.r * 1.08);
      g.addColorStop(0, rgba(mixC(s.col, [255, 255, 245], 0.45), 1)); g.addColorStop(0.8, rgba(s.col, 1)); g.addColorStop(1, rgba(s.col, 0));
      cx.fillStyle = g; cx.beginPath(); cx.arc(s.x, s.y, s.r * 1.08, 0, 7); cx.fill();
    });
  }
  if (Ls.suns.show) cx.drawImage(cache.suns, 0, 0);
  const rimK = 0.75 * (1 + lift);
  const air = Ls.air, lk = AIRLOOK[air.look % 3], wind = 0.35 + air.v.wind * 1.3;
  const hz = air.show ? clamp(0.32 + 0.5 * air.v.amount, 0, 1) * lk.haze : 0;
  if (Ls.far.show) { cx.drawImage(cache.far, 0, 0); cx.globalCompositeOperation = 'lighter'; cx.globalAlpha = rimK; cx.drawImage(cache.farRim, 0, 0); cx.globalAlpha = 1; cx.globalCompositeOperation = 'source-over'; }
  if (air.show) {
    drawParticles(cx, 0, P);
    const off = (t * 7 * wind) % 1536;
    cx.globalAlpha = clamp(hz, 0, 1); const y = 0.575 * H;
    cx.drawImage(cache.hazeA, -off, y); cx.drawImage(cache.hazeA, 1536 - off, y); cx.globalAlpha = 1;
  }
  if (Ls.cliff.show) { cx.drawImage(cache.cliff, 0, 0); cx.globalCompositeOperation = 'lighter'; cx.globalAlpha = rimK; cx.drawImage(cache.cliffRim, 0, 0); cx.globalAlpha = 1; cx.globalCompositeOperation = 'source-over'; }
  if (Ls.near.show) { cx.drawImage(cache.near, 0, 0); cx.globalCompositeOperation = 'lighter'; cx.globalAlpha = rimK; cx.drawImage(cache.nearRim, 0, 0); cx.globalAlpha = 1; cx.globalCompositeOperation = 'source-over'; }
  if (air.show) {
    drawParticles(cx, 1, P); drawParticles(cx, 2, P);
    const off = (t * 11 * wind + 400) % 1536; cx.globalAlpha = clamp(hz * 0.8, 0, 1); const y = 0.8 * H;
    cx.drawImage(cache.hazeB, -off, y); cx.drawImage(cache.hazeB, 1536 - off, y); cx.globalAlpha = 1;
    cx.drawImage(cache.air, 0, 0);
  }
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
    composite();
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
  inp.addEventListener('input', () => { set(+inp.value); paint(); dirty = true; persist(); });
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
  renderAt(t, refrains) { manual = true; if (t < sim.t - 1e-6) resetSim(); fake = refrains ? { refrains } : null; liftFrom(t, !!refrains); advance(t); composite(); return true; },
  fakeRefrains(list) { fake = list ? { refrains: list } : null; },
  regionDiff,
  setState(patch) { Object.assign(st, patch); dirty = true; buildPanel(); },
  dirty() { dirty = true; },
  photos,
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
