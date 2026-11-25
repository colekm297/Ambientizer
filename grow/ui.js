import { Kit, Player, plan, renderWav, defaultSettings, WORLDS, MODES, KEYS, ROLES, ROLE_NAMES, detectPitch, noteName, arcAt } from './grow.js';

const $ = (s) => document.querySelector(s);
const fmt = (t) => { t = Math.max(0, Math.round(t)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const safe = (fn, fb) => { try { return fn(); } catch (e) { return fb; } };

// ------------------------------------------------------------ state
let S = defaultSettings();
const savedCur = safe(() => JSON.parse(localStorage.getItem('grow.current')), null);
if (savedCur && savedCur.world in WORLDS) S = Object.assign(S, savedCur);
const kit = new Kit(48000);
const player = new Player(kit, S, {
  onState: (st) => setPlayUi(st),
  onPlan: () => { drawStatic = null; },
  onEnd: () => setPlayUi('idle'),
});
let loadPromise = null;
const ensureKit = () => (loadPromise = loadPromise || kit.loadStarter('sounds/folding-city/'));

// ------------------------------------------------------------ settings UI
const keySel = $('#key'), modeSel = $('#mode');
KEYS.forEach((k, i) => keySel.add(new Option(k, i)));
Object.keys(MODES).forEach((m) => modeSel.add(new Option(m[0].toUpperCase() + m.slice(1), m)));

const SLIDERS = [
  { id: 'bpm', label: 'Pace', min: 36, max: 84, step: 1, fmt: (v) => `${Math.round(v)} BPM` },
  { id: 'refrainEvery', label: 'Refrain', min: 90, max: 240, step: 5, fmt: (v) => `every ${fmt(v)}` },
  { id: 'density', label: 'Density', min: 0, max: 1, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { id: 'space', label: 'Space', min: 0, max: 1, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { id: 'brightness', label: 'Brightness', min: 0, max: 1, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
];
const slidersEl = $('#sliders');
SLIDERS.forEach((d) => {
  const w = document.createElement('label');
  w.className = 'gr-slider';
  w.innerHTML = `<span class="ds-label">${d.label}</span><output id="o_${d.id}"></output><input type="range" id="r_${d.id}" min="${d.min}" max="${d.max}" step="${d.step}" aria-label="${d.label}">`;
  slidersEl.appendChild(w);
  w.querySelector('input').addEventListener('input', (e) => { S[d.id] = +e.target.value; paintSlider(d); changed(); });
});
function paintSlider(d) {
  const inp = $('#r_' + d.id);
  inp.value = S[d.id];
  inp.style.setProperty('--p', ((S[d.id] - d.min) / (d.max - d.min)) * 100 + '%');
  $('#o_' + d.id).textContent = d.fmt(S[d.id]);
}
function paintAll() {
  SLIDERS.forEach(paintSlider);
  keySel.value = S.key; modeSel.value = S.mode;
  setSeg('#worldSeg', S.world); setSeg('#lenSeg', String(S.length));
  $('#chipKey').textContent = `${KEYS[S.key]} ${S.mode}`;
  $('#timeTotal').textContent = `of ${fmt(S.length)}`;
}
function setSeg(sel, value) {
  const seg = $(sel);
  const opts = [...seg.querySelectorAll('.ds-seg__opt')];
  const i = Math.max(0, opts.findIndex((o) => o.dataset.value === value));
  if (seg.dsSeg) seg.dsSeg.select(i); else opts.forEach((o, k) => o.setAttribute('aria-checked', k === i ? 'true' : 'false'));
}
let tChange = null;
function changed() {
  safe(() => localStorage.setItem('grow.current', JSON.stringify(S)));
  paintAll();
  clearTimeout(tChange);
  tChange = setTimeout(() => player.update(S), 120);
}
keySel.addEventListener('change', () => { S.key = +keySel.value; changed(); });
modeSel.addEventListener('change', () => { S.mode = modeSel.value; changed(); });
$('#worldSeg').addEventListener('seg-change', (e) => {
  const w = e.detail.value; if (!(w in WORLDS) || w === S.world) return;
  S.world = w; Object.assign(S, { key: WORLDS[w].key, mode: WORLDS[w].mode, bpm: WORLDS[w].bpm }); changed();
});
$('#lenSeg').addEventListener('seg-change', (e) => { const v = +e.detail.value; if (v === S.length) return; S.length = v; changed(); });
$('#reseed').addEventListener('click', () => { S.seed = (Math.random() * 4294967295) >>> 0; changed(); });

// ------------------------------------------------------------ transport
const playBtn = $('#play');
function setPlayUi(st) {
  const playing = st === 'playing';
  $('#playWord').textContent = playing ? 'Pause' : 'Play';
  playBtn.setAttribute('aria-label', playing ? 'Pause' : 'Play');
  playBtn.querySelector('use').setAttribute('href', `ds/icons/sprite.svg#i-${playing ? 'pause' : 'play'}`);
  playBtn.removeAttribute('aria-busy');
}
playBtn.addEventListener('click', async () => {
  try {
    if (player.state === 'playing') { await player.pause(); return; }
    playBtn.setAttribute('aria-busy', 'true'); $('#playWord').textContent = 'Loading';
    await ensureKit();
    await player.start();
  } catch (err) { console.error(err); $('#playWord').textContent = 'Play'; playBtn.removeAttribute('aria-busy'); }
});

// ------------------------------------------------------------ sounds (yours)
const DB = 'grow', STORE = 'sounds';
const idb = () => new Promise((res, rej) => {
  const r = indexedDB.open(DB, 1);
  r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: 'role' });
  r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
});
const idbPut = async (rec) => { const d = await idb(); return new Promise((res, rej) => { const t = d.transaction(STORE, 'readwrite'); t.objectStore(STORE).put(rec); t.oncomplete = res; t.onerror = () => rej(t.error); }); };
const idbDel = async (role) => { const d = await idb(); return new Promise((res) => { const t = d.transaction(STORE, 'readwrite'); t.objectStore(STORE).delete(role); t.oncomplete = res; }); };
const idbAll = async () => { const d = await idb(); return new Promise((res) => { const q = d.transaction(STORE).objectStore(STORE).getAll(); q.onsuccess = () => res(q.result); }); };

const yours = {}; // role -> {name, root, detected, conf}
const rolesEl = $('#roles');
const INSTR = { bed: 'Pad', low: 'Cello', voice: 'Horn', air: 'Texture' };
function paintRoles() {
  rolesEl.innerHTML = '';
  ROLES.forEach((r) => {
    const y = yours[r];
    const row = document.createElement('div');
    row.className = 'gr-role'; row.dataset.role = r;
    row.innerHTML = `
      <div class="gr-role__name"><span class="ds-label">${ROLE_NAMES[r]}</span>
        ${y ? '<span class="ds-chip">Yours</span>' : ''}<span class="ds-meta">${y ? esc(y.name) : INSTR[r]}</span></div>
      <div class="gr-role__acts">
        <button type="button" class="ds-btn ds-btn--sm ds-btn--raised" data-act="import">Import</button>
        <button type="button" class="ds-btn ds-btn--sm ds-btn--raised" data-act="record"><svg class="ds-icon ds-icon--sm" aria-hidden="true"><use href="ds/icons/sprite.svg#i-microphone"></use></svg><span>Record</span></button>
        ${y ? '<button type="button" class="ds-btn ds-btn--sm ds-btn--ghost" data-act="reset">Reset</button>' : ''}
      </div>
      ${y ? `<div class="gr-role__pitch"><span class="ds-meta">Root ${noteName(y.root)}</span>
        <button type="button" class="ds-btn ds-btn--sm ds-btn--raised" data-act="down" aria-label="Root down">-1</button>
        <button type="button" class="ds-btn ds-btn--sm ds-btn--raised" data-act="up" aria-label="Root up">+1</button>
        <span class="ds-meta">${y.detected == null ? 'No pitch found' : 'Heard ' + noteName(y.detected) + (y.cents ? ` ${y.cents > 0 ? '+' : ''}${y.cents}c` : '')}</span></div>` : ''}
      <input type="file" accept="audio/*" aria-label="${ROLE_NAMES[r]} file">`;
    rolesEl.appendChild(row);
    const file = row.querySelector('input');
    file.addEventListener('change', () => file.files[0] && importFile(r, file.files[0]));
    row.addEventListener('dragover', (e) => { e.preventDefault(); row.classList.add('is-drop'); });
    row.addEventListener('dragleave', () => row.classList.remove('is-drop'));
    row.addEventListener('drop', (e) => { e.preventDefault(); row.classList.remove('is-drop'); const f = e.dataTransfer.files[0]; if (f) importFile(r, f); });
    row.addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      const a = b.dataset.act;
      if (a === 'import') file.click();
      else if (a === 'record') recordFor(r, b);
      else if (a === 'reset') resetRole(r);
      else if (a === 'up' || a === 'down') nudgeRoot(r, a === 'up' ? 1 : -1);
    });
  });
  const n = Object.keys(yours).length;
  $('#yoursLine').textContent = `${n} of 4 yours`;
  $('#chipYours').textContent = `${n} of 4 yours`;
}
let noteT = null;
function say(msg) { const n = $('#note'); n.textContent = msg; clearTimeout(noteT); noteT = setTimeout(() => { n.textContent = ''; }, 7000); }
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
async function adopt(role, data, sr, name) {
  const det = detectPitch(data, sr);
  const rec = { role, name: name.slice(0, 40), sr, data, root: det ? det.midi : 60, detected: det ? det.midi : null, cents: det ? det.cents : 0, conf: det ? det.conf : 0 };
  kit.setImported(role, rec);
  yours[role] = rec;
  await idbPut(rec).catch(() => {});
  paintRoles();
}
async function decodeToMono(arrayBuf) {
  const ctx = new OfflineAudioContext(1, 1, 48000);
  const buf = await ctx.decodeAudioData(arrayBuf);
  const n = Math.min(buf.length, Math.floor(buf.sampleRate * 20));
  const mono = new Float32Array(n);
  for (let c = 0; c < buf.numberOfChannels; c++) { const d = buf.getChannelData(c); for (let i = 0; i < n; i++) mono[i] += d[i] / buf.numberOfChannels; }
  return { mono, sr: buf.sampleRate };
}
async function importFile(role, file) {
  try { const { mono, sr } = await decodeToMono(await file.arrayBuffer()); await adopt(role, mono, sr, file.name.replace(/\.[^.]+$/, '')); }
  catch (e) { console.error(e); say('That file could not be read.'); }
}
async function recordFor(role, btn) {
  const word = btn.querySelector('span');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    const mr = new MediaRecorder(stream); const chunks = [];
    mr.ondataavailable = (e) => chunks.push(e.data);
    const done = new Promise((res) => (mr.onstop = res));
    mr.start();
    let left = 10; btn.classList.add('gr-rec'); word.textContent = `Stop ${left}`;
    const iv = setInterval(() => { left--; word.textContent = `Stop ${Math.max(0, left)}`; if (left <= 0) mr.stop(); }, 1000);
    btn.onclick = (e) => { e.stopPropagation(); mr.stop(); };
    await done; clearInterval(iv);
    stream.getTracks().forEach((t) => t.stop());
    const ab = await new Blob(chunks, { type: mr.mimeType }).arrayBuffer();
    const { mono, sr } = await decodeToMono(ab);
    await adopt(role, mono, sr, 'Recording');
  } catch (e) { console.warn(e); say(e && e.name === 'NotAllowedError' ? 'Microphone blocked. Allow it in the browser to record.' : 'No microphone available.'); paintRoles(); }
}
async function resetRole(role) { delete yours[role]; kit.setImported(role, null); await idbDel(role).catch(() => {}); paintRoles(); }
async function nudgeRoot(role, d) {
  const y = yours[role]; if (!y) return;
  y.root = Math.max(24, Math.min(96, y.root + d));
  kit.setImported(role, y); await idbPut(y).catch(() => {}); paintRoles();
}

// ------------------------------------------------------------ pieces
const loadPieces = () => safe(() => JSON.parse(localStorage.getItem('grow.pieces')) || [], []);
const savePieces = (a) => safe(() => localStorage.setItem('grow.pieces', JSON.stringify(a)));
function paintPieces() {
  const el = $('#saved'); el.innerHTML = '';
  loadPieces().forEach((p, i) => {
    const row = document.createElement('div'); row.className = 'gr-piece';
    row.innerHTML = `<div><div class="ds-label">${esc(p.name)}</div><div class="ds-meta">${KEYS[p.settings.key]} ${p.settings.mode}, ${Math.round(p.settings.bpm)} BPM</div></div>
      <button type="button" class="ds-btn ds-btn--sm ds-btn--raised" data-open="${i}">Open</button>
      <button type="button" class="ds-btn ds-btn--sm ds-btn--ghost" data-del="${i}" aria-label="Delete ${esc(p.name)}">Delete</button>`;
    el.appendChild(row);
  });
}
$('#saved').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  const all = loadPieces();
  if (b.dataset.open != null) { S = Object.assign(defaultSettings(), all[+b.dataset.open].settings); changed(); }
  if (b.dataset.del != null) {
    if (b.dataset.armed) { all.splice(+b.dataset.del, 1); savePieces(all); paintPieces(); }
    else { b.dataset.armed = '1'; b.textContent = 'Sure?'; setTimeout(() => { if (b.isConnected) { delete b.dataset.armed; b.textContent = 'Delete'; } }, 3000); }
  }
});
$('#save').addEventListener('click', () => {
  const inp = $('#saveName'); const name = inp.value.trim() || `${S.world} ${new Date().toLocaleDateString()}`;
  const all = loadPieces(); all.unshift({ name, settings: Object.assign({}, S), ts: Date.now() }); savePieces(all.slice(0, 40));
  inp.value = ''; paintPieces();
});

// ------------------------------------------------------------ export
let exporting = false;
async function exportWav(name, post, seconds = window.GrowTest && window.GrowTest.exportSeconds || 600) {
  if (exporting) return null;
  exporting = true;
  const btn = $('#export'), meter = $('#expMeter'), info = $('#expInfo');
  btn.disabled = true; meter.hidden = false; DS.meter(meter, 0); info.textContent = '0%';
  try {
    await ensureKit();
    const S10 = Object.assign({}, S, { length: 600 });
    seconds = seconds || 600;
    const blob = await renderWav(kit, S10, { seconds, onProgress: (f) => { DS.meter(meter, f); info.textContent = Math.round(f * 100) + '%'; } });
    if (post) await fetch('/__save?name=' + encodeURIComponent(post), { method: 'POST', body: blob });
    else { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `grow-${(name || S.world).replace(/\W+/g, '-')}.wav`; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); }
    info.textContent = 'Done';
    return blob.size;
  } catch (e) { console.error(e); info.textContent = 'Failed'; }
  finally { exporting = false; btn.disabled = false; setTimeout(() => { meter.hidden = true; if (info.textContent === 'Done') info.textContent = '10 min'; }, 2500); }
}
$('#export').addEventListener('click', () => exportWav($('#saveName').value.trim() || S.world, null));

// ------------------------------------------------------------ the picture
const canvas = $('#pic'); const cx = canvas.getContext('2d');
let W = 0, H = 0, dpr = 1, colors = {};
let drawStatic = null, pulse = 0, rings = [], lastRing = 0, frames = 0;
function readColors() { colors = { accent: css('--accent'), mark: css('--attention'), ink: css('--ink'), line: css('--line-default'), card: css('--bg-card'), sunken: css('--bg-sunken'), tint: css('--accent-tint') }; }
function fit() {
  const r = canvas.getBoundingClientRect(); dpr = Math.min(2, window.devicePixelRatio || 1);
  W = Math.max(10, r.width); H = Math.max(10, r.height);
  canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); drawStatic = null;
}
new ResizeObserver(fit).observe(canvas);
const alpha = (c, a) => { // color string to rgba
  const m = c.match(/^#([0-9a-f]{6})$/i);
  if (m) { const n = parseInt(m[1], 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; }
  const g = c.match(/rgba?\(([^)]+)\)/); if (g) { const p = g[1].split(',').map((x) => parseFloat(x)); return `rgba(${p[0]},${p[1]},${p[2]},${a})`; }
  return c;
};
function layout() { const padX = 18, top = 70, bot = 26; return { x0: padX, x1: W - padX, yTop: top, yBase: H - bot, h: H - bot - top }; }
const xOf = (t, L, ly) => ly.x0 + (t / L) * (ly.x1 - ly.x0);
const yArc = (f, ly) => ly.yBase - arcAt(f) * ly.h * 0.82;

function drawFrame(now) {
  requestAnimationFrame(drawFrame);
  if (!W) return;
  frames++;
  const pl = player.plan, L = pl.meta.length, pos = player.position;
  const playing = player.state === 'playing';
  // amplitude
  let amp = 0;
  if (player.g && playing) {
    const a = new Float32Array(player.g.analyser.fftSize); player.g.analyser.getFloatTimeDomainData(a);
    let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * a[i]; amp = Math.sqrt(s / a.length);
  }
  pulse += (Math.min(1, amp * 7) - pulse) * 0.12;
  const ly = layout();
  cx.setTransform(dpr, 0, 0, dpr, 0, 0);
  cx.clearRect(0, 0, W, H);
  const tsec = now / 1000;
  // arc fill
  const pts = pl.arcPts; const n = pts.length - 1;
  cx.beginPath(); cx.moveTo(ly.x0, ly.yBase);
  for (let i = 0; i <= n; i++) cx.lineTo(ly.x0 + (i / n) * (ly.x1 - ly.x0), yArc(i / n, ly));
  cx.lineTo(ly.x1, ly.yBase); cx.closePath();
  const gr = cx.createLinearGradient(0, ly.yTop, 0, ly.yBase);
  gr.addColorStop(0, alpha(colors.accent, 0.16)); gr.addColorStop(1, alpha(colors.accent, 0.02));
  cx.fillStyle = gr; cx.fill();
  // played part, clipped
  const px = xOf(Math.min(pos, L), L, ly);
  cx.save(); cx.beginPath(); cx.rect(0, 0, px, H); cx.clip();
  cx.beginPath(); cx.moveTo(ly.x0, ly.yBase);
  for (let i = 0; i <= n; i++) cx.lineTo(ly.x0 + (i / n) * (ly.x1 - ly.x0), yArc(i / n, ly));
  cx.lineTo(ly.x1, ly.yBase); cx.closePath(); cx.fillStyle = alpha(colors.accent, 0.2); cx.fill();
  cx.restore();
  // arc line
  cx.beginPath();
  for (let i = 0; i <= n; i++) { const x = ly.x0 + (i / n) * (ly.x1 - ly.x0), y = yArc(i / n, ly); i ? cx.lineTo(x, y) : cx.moveTo(x, y); }
  cx.strokeStyle = colors.accent; cx.lineWidth = 2; cx.lineJoin = 'round'; cx.stroke();
  // baseline and ticks
  cx.strokeStyle = colors.line; cx.lineWidth = 1; cx.beginPath(); cx.moveTo(ly.x0, ly.yBase + 0.5); cx.lineTo(ly.x1, ly.yBase + 0.5); cx.stroke();
  const tick = L > 1200 ? 600 : 120;
  cx.fillStyle = colors.ink; cx.font = '500 11px "Hanken Grotesk", sans-serif'; cx.textAlign = 'center';
  for (let t = 0; t <= L; t += tick) { const x = xOf(t, L, ly); cx.fillRect(x - 0.5, ly.yBase, 1, 4); if (t > 0 && t < L) cx.fillText(fmt(t), x, ly.yBase + 17); }
  // chord bands along the base
  for (const c of pl.chords) { if (c.t0 >= L) continue; const xa = xOf(c.t0, L, ly), xb = xOf(Math.min(c.t1, L), L, ly); cx.fillStyle = alpha(colors.ink, c.deg === 0 ? 0.1 : 0.05); cx.fillRect(xa + 0.5, ly.yBase - 5, Math.max(1, xb - xa - 1), 4); }
  // voice notes as dots (the melody, seen)
  for (const e of pl.events) {
    if (e.role !== 'voice') continue;
    const x = xOf(e.t, L, ly), y = ly.yBase - 14 - ((e.midi - 52) / 32) * (ly.h * 0.55);
    const r = e.tag === 'refrain' ? 2.4 : 1.7;
    cx.fillStyle = e.t <= pos ? alpha(colors.ink, e.tag === 'refrain' ? 0.85 : 0.55) : alpha(colors.ink, e.tag === 'refrain' ? 0.45 : 0.28);
    cx.beginPath(); cx.arc(x, y, r, 0, 6.2832); cx.fill();
  }
  // refrain blooms
  let nextR = null;
  for (const r of pl.refrains) {
    const mid = r.start + r.dur / 2, x = xOf(mid, L, ly), y = yArc(mid / L, ly) - 4;
    const past = pos > r.end, now_ = pos >= r.start && pos <= r.end;
    if (!nextR && r.start > pos) nextR = r;
    const near = !past && !now_ && r.start - pos < 40 && playing;
    const base = (r.peak ? 24 : 16) * (0.6 + 0.4 * r.intensity) * Math.min(1.4, Math.max(0.55, (ly.x1 - ly.x0) / 520)) * (L > 1200 ? 0.62 : 1);
    const breathe = 1 + 0.07 * Math.sin(tsec * 1.1 + r.k) + (now_ ? pulse * 0.5 : 0) + (near ? 0.18 + 0.1 * Math.sin(tsec * 3) : 0);
    const rad = base * breathe;
    const a = past ? 0.4 : now_ ? 1 : 0.85;
    const grd = cx.createRadialGradient(x, y, 0, x, y, rad * 1.9);
    grd.addColorStop(0, alpha(colors.mark, 0.55 * a)); grd.addColorStop(0.5, alpha(colors.mark, 0.2 * a)); grd.addColorStop(1, alpha(colors.mark, 0));
    cx.fillStyle = grd; cx.beginPath(); cx.arc(x, y, rad * 1.9, 0, 6.2832); cx.fill();
    // petals
    cx.strokeStyle = alpha(colors.mark, 0.9 * a); cx.lineWidth = 1.5;
    const petals = 6;
    for (let k = 0; k < petals; k++) {
      const ang = (k / petals) * 6.2832 + tsec * 0.07 + r.k;
      cx.beginPath(); cx.ellipse(x + Math.cos(ang) * rad * 0.42, y + Math.sin(ang) * rad * 0.42, rad * 0.42, rad * 0.2, ang, 0, 6.2832); cx.stroke();
    }
    cx.fillStyle = alpha(colors.mark, a); cx.beginPath(); cx.arc(x, y, Math.max(2.5, rad * 0.14), 0, 6.2832); cx.fill();
    // span of the refrain on the base
    cx.fillStyle = alpha(colors.mark, past ? 0.35 : 0.8); cx.fillRect(xOf(r.start, L, ly), ly.yBase - 1.5, Math.max(2, xOf(r.end, L, ly) - xOf(r.start, L, ly)), 3);
  }
  // playhead
  const hy = yArc(Math.min(1, pos / L), ly);
  cx.strokeStyle = colors.ink; cx.lineWidth = 1.5; cx.beginPath(); cx.moveTo(px, ly.yTop - 6); cx.lineTo(px, ly.yBase); cx.stroke();
  // living rings from the playhead
  if (playing && now - lastRing > 520 - pulse * 300) { rings.push({ t: now, a: 0.15 + pulse * 0.5 }); lastRing = now; }
  rings = rings.filter((r) => now - r.t < 2600);
  for (const r of rings) {
    const u = (now - r.t) / 2600;
    cx.strokeStyle = alpha(colors.accent, r.a * (1 - u)); cx.lineWidth = 1.5;
    cx.beginPath(); cx.arc(px, hy, 6 + u * (30 + pulse * 40), 0, 6.2832); cx.stroke();
  }
  cx.fillStyle = colors.card; cx.beginPath(); cx.arc(px, hy, 6.5 + pulse * 3, 0, 6.2832); cx.fill();
  cx.fillStyle = colors.accent; cx.beginPath(); cx.arc(px, hy, 4.5 + pulse * 3, 0, 6.2832); cx.fill();
  // text
  $('#time').textContent = fmt(pos);
  const cur = pl.refrains.find((r) => pos >= r.start && pos < r.end);
  $('#next').textContent = cur ? 'Refrain now' : nextR ? `Next refrain ${fmt(nextR.start - pos)}` : (pos >= L ? 'Finished' : 'No more refrains');
  if (frames % 30 === 0) window.__lastDraw = { frames, pos, amp, pulse };
}

// ------------------------------------------------------------ boot
(async function boot() {
  paintAll(); paintRoles(); paintPieces(); readColors(); fit();
  window.matchMedia && matchMedia('(prefers-color-scheme: dark)').addEventListener && matchMedia('(prefers-color-scheme: dark)').addEventListener('change', readColors);
  player.update(S);
  requestAnimationFrame(drawFrame);
  try { await ensureKit(); } catch (e) { console.error('kit', e); }
  safe(async () => {
    const all = await idbAll();
    for (const rec of all) { if (rec && ROLES.includes(rec.role)) { yours[rec.role] = rec; kit.setImported(rec.role, rec); } }
    paintRoles();
  });
})();

// test hooks (used by the headless checks)
window.GrowTest = {
  exportSeconds: 0,
  player, kit, getS: () => S, setS: (o) => { Object.assign(S, o); changed(); },
  render: (o, seconds, name) => { Object.assign(S, o); return exportWav(name, name, seconds); },
  ready: () => ensureKit().then(() => true),
};
