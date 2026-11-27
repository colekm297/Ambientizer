// Scene: select a region, ask for an element, keep one. Generated draw(ctx, t, p, box, e) bodies run clipped to the mask,
// time-boxed, with no network or DOM names in scope. Best-effort sandbox: the code comes from Cole's own request to Gemini.
const MW = 320, MH = 180; // selection mask grid, 4 scene px per cell
const CELL = 4;
const SLOTS = ['Sky', 'Suns', 'Far', 'Cliff', 'Near', 'Air']; // an element sits above the named base layer
const SHADOW = ['window', 'document', 'fetch', 'globalThis', 'self', 'top', 'parent', 'frames', 'XMLHttpRequest', 'WebSocket', 'localStorage', 'sessionStorage', 'indexedDB', 'navigator', 'location', 'Worker', 'importScripts', 'setTimeout', 'setInterval', 'requestAnimationFrame', 'Image', 'Function', 'caches', 'crypto', 'performance', 'Date', 'Atomics', 'SharedArrayBuffer'];
const BANNED = /\b(eval|arguments|constructor|__proto__|prototype|import|require|process|Reflect|Proxy|WebAssembly|globalThis|self|window|document|fetch|XMLHttpRequest|WebSocket|localStorage|sessionStorage|indexedDB|navigator|location|Worker|importScripts|setTimeout|setInterval|Function)\b|\[\s*['"`]/;
const BUDGET_MS = 4;

export function createAsk(h) {
  const { W, H, $, clamp, st, persist, geo, sim, cv, status, segEl, sliderRow, mk, dirtyAll } = h;
  const rt = new Map();      // layer id -> runtime { fn, mask, off, ema, n, err }
  let selecting = false, tool = 0, brush = 0.5, drawing = null, lasso = null;
  let target = null;         // layer id being refined, or null for a new element
  let preview = null;        // { variants:[{v, fn, canvas, err}], sel, snap, crop }
  let busy = false;

  // ------------------------------------------------------------ compile and run
  function compile(code) {
    if (typeof code !== 'string' || !code.trim() || code.length > 8000) throw new Error('No code');
    if (BANNED.test(code)) throw new Error('Blocked word in code');
    const outer = new Function(...SHADOW, '"use strict";\nreturn function (ctx, t, p, box, e) {\n' + code + '\n};');
    return outer();
  }
  const hash = (k, s) => { const v = Math.sin(k * 127.1 + s * 311.7) * 43758.5453; return v - Math.floor(v); };
  const env = { lift: 0, night: 0, time: 0, col: {}, rgba: null, sun: { x: 0, y: 0 }, rnd: null };
  let envP = null;
  function fillEnv(seed) {
    const P = geo.P;
    if (envP !== P) { envP = P; env.col = {}; for (const k of ['top', 'mid', 'hor', 'sun', 'glow', 'far', 'cliff', 'lit', 'near', 'haze', 'rim', 'shade']) env.col[k] = `rgb(${P[k][0] | 0},${P[k][1] | 0},${P[k][2] | 0})`; }
    env.rgba = (n, a) => { const c = P[n] || P.rim; return `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${clamp(+a || 0, 0, 1)})`; };
    env.lift = sim.lift; env.night = P.night; env.time = st().time;
    const S = geo.suns[0]; env.sun = S ? { x: S.x, y: S.y } : { x: 0.7 * W, y: 0.5 * H };
    env.rnd = (i) => hash(+i || 0, seed);
  }
  const pvals = (c) => { const o = {}; for (const q of c.params) o[q.name] = q.value; return o; };
  const boxOf = (c) => { const b = c.box; return { x: b.x, y: b.y, w: b.w, h: b.h, cx: b.x + b.w / 2, cy: b.y + b.h / 2 }; };

  // mask: a cropped alpha PNG at grid resolution, scaled to scene pixels for use
  function maskCanvas(c, cb) {
    const im = new Image();
    im.onload = () => {
      const m = mk(c.box.w, c.box.h), x = m.getContext('2d');
      x.imageSmoothingEnabled = true; x.imageSmoothingQuality = 'high';
      try { x.filter = 'blur(1.5px)'; } catch {}
      x.drawImage(im, 0, 0, c.box.w, c.box.h); x.filter = 'none';
      cb(m);
    };
    im.onerror = () => cb(null);
    im.src = c.mask;
  }
  function runtimeOf(c) {
    let r = rt.get(c.id);
    if (r) return r;
    r = { fn: null, mask: null, off: mk(c.box.w, c.box.h), ema: 0, n: 0, err: '' };
    rt.set(c.id, r);
    try { r.fn = compile(c.code); } catch (e) { r.err = String(e.message || e).slice(0, 60); }
    maskCanvas(c, (m) => { r.mask = m; if (!m && !r.err) r.err = 'Mask failed'; });
    return r;
  }
  // draw one element onto dst (which carries the caller's transform). Returns false when the element failed.
  function render(dst, c, r, t, op, limit) {
    if (!r.fn || !r.mask || r.err) return false;
    const o = r.off, x = o.getContext('2d'), b = c.box;
    if (x.reset) x.reset(); else { x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = 'source-over'; x.clearRect(0, 0, o.width, o.height); }
    x.save(); x.setTransform(1, 0, 0, 1, -b.x, -b.y);
    const t0 = performance.now();
    try { r.fn(x, t, pvals(c), boxOf(c), env); } catch (e) { r.err = ('Error: ' + (e && e.message || e)).slice(0, 70); }
    const ms = performance.now() - t0;
    x.restore(); x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1;
    x.globalCompositeOperation = 'destination-in'; x.drawImage(r.mask, 0, 0); x.globalCompositeOperation = 'source-over';
    if (limit) {
      r.n++; r.ema = r.n === 1 ? ms : r.ema * 0.9 + ms * 0.1; r.last = ms;
      if (!r.err && ((r.n >= 20 && r.ema > BUDGET_MS) || ms > 60)) r.err = `Too slow: ${Math.max(r.ema, ms).toFixed(1)} ms`;
    }
    if (r.err) return false;
    dst.globalAlpha = op; dst.drawImage(o, b.x, b.y);
    if (env.lift > 0.01) { dst.globalCompositeOperation = 'lighter'; dst.globalAlpha = Math.min(1, op * env.lift * 1.5); dst.drawImage(o, b.x, b.y); dst.globalCompositeOperation = 'source-over'; }
    dst.globalAlpha = 1;
    return true;
  }
  // called from composite() at each slot of the layer stack
  let errShown = '';
  function drawSlot(dst, slot, t) {
    const list = st().custom; if (!list || !list.length) return;
    let any = false;
    for (const c of list) { if (c.z !== slot || !c.show || c.hidden) continue; if (!any) { fillEnv(st().seed); any = true; } const r = runtimeOf(c); const was = r.err; render(dst, c, r, t, c.op, true); if (r.err && r.err !== was) onFail(c, r); }
  }
  function onFail(c, r) {
    status(`${c.name}: ${r.err}`); errShown = c.id; paintElements();
  }

  // ------------------------------------------------------------ selection
  const sel = document.createElement('canvas'); sel.width = MW; sel.height = MH;
  const sx = sel.getContext('2d', { willReadFrequently: true });
  const ov = $('#selcv'), ox = ov.getContext('2d');
  let selBox = null; // grid-aligned scene px box of the current selection
  function bounds(ctx2, thr = 40) {
    const d = ctx2.getImageData(0, 0, MW, MH).data; let x0 = MW, y0 = MH, x1 = -1, y1 = -1, n = 0;
    for (let y = 0; y < MH; y++) for (let x = 0; x < MW; x++) if (d[(y * MW + x) * 4 + 3] > thr) { n++; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    return n ? { x0, y0, x1: x1 + 1, y1: y1 + 1, n } : null;
  }
  function paintSel() {
    ox.clearRect(0, 0, MW, MH);
    ox.globalCompositeOperation = 'source-over'; ox.drawImage(sel, 0, 0);
    ox.globalCompositeOperation = 'source-in'; ox.fillStyle = 'rgba(255,244,214,.5)'; ox.fillRect(0, 0, MW, MH);
    ox.globalCompositeOperation = 'source-over';
    ox.lineWidth = 1; ox.setLineDash([3, 2]); ox.strokeStyle = 'rgba(255,255,255,.95)';
    if (lasso && lasso.length > 1) { ox.beginPath(); lasso.forEach((p, i) => (i ? ox.lineTo(p[0], p[1]) : ox.moveTo(p[0], p[1]))); ox.stroke(); }
    if (selBox) ox.strokeRect(selBox.x0 + 0.5, selBox.y0 + 0.5, selBox.x1 - selBox.x0 - 1, selBox.y1 - selBox.y0 - 1);
    ox.setLineDash([]);
  }
  function refreshBox() { selBox = bounds(sx); paintSel(); paintAsk(); }
  const at = (e) => { const r = ov.getBoundingClientRect(); return [clamp((e.clientX - r.left) / r.width, 0, 1) * MW, clamp((e.clientY - r.top) / r.height, 0, 1) * MH]; };
  const brushR = () => (2 + 14 * brush); // grid cells, diameter
  ov.addEventListener('pointerdown', (e) => {
    if (!selecting) return; e.preventDefault(); ov.setPointerCapture(e.pointerId);
    const p = at(e);
    if (tool === 0) { drawing = p; sx.fillStyle = '#fff'; sx.beginPath(); sx.arc(p[0], p[1], brushR() / 2, 0, 7); sx.fill(); paintSel(); }
    else { lasso = [p]; paintSel(); }
  });
  ov.addEventListener('pointermove', (e) => {
    if (!selecting) return; const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    for (const ev of (evs.length ? evs : [e])) {
      const p = at(ev);
      if (tool === 0 && drawing) { sx.strokeStyle = '#fff'; sx.lineCap = 'round'; sx.lineWidth = brushR(); sx.beginPath(); sx.moveTo(drawing[0], drawing[1]); sx.lineTo(p[0], p[1]); sx.stroke(); drawing = p; }
      else if (tool === 1 && lasso) lasso.push(p);
    }
    paintSel();
  });
  const end = (e) => {
    if (!selecting) return;
    if (tool === 0 && drawing) { drawing = null; refreshBox(); }
    else if (tool === 1 && lasso) {
      if (lasso.length > 2) { sx.fillStyle = '#fff'; sx.beginPath(); lasso.forEach((p, i) => (i ? sx.lineTo(p[0], p[1]) : sx.moveTo(p[0], p[1]))); sx.closePath(); sx.fill(); }
      lasso = null; refreshBox();
    }
  };
  ov.addEventListener('pointerup', end); ov.addEventListener('pointercancel', end);
  function clearSel() { sx.clearRect(0, 0, MW, MH); selBox = null; drawing = null; lasso = null; paintSel(); paintAsk(); }

  // the mask summary the model sees: area, box, and a coarse grid (# selected, . not)
  function selectionInfo() {
    if (!selBox) return null;
    const b = selBox, d = sx.getImageData(0, 0, MW, MH).data;
    // pad one cell, clamp, and fix a minimum size so tiny picks still get room to draw
    let x0 = Math.max(0, b.x0 - 1), y0 = Math.max(0, b.y0 - 1), x1 = Math.min(MW, b.x1 + 1), y1 = Math.min(MH, b.y1 + 1);
    const crop = mk(x1 - x0, y1 - y0), cx2 = crop.getContext('2d');
    cx2.drawImage(sel, x0, y0, x1 - x0, y1 - y0, 0, 0, x1 - x0, y1 - y0);
    const gw = 24, gh = Math.max(4, Math.round(gw * (y1 - y0) / (x1 - x0) * 0.5)), rows = [];
    for (let j = 0; j < gh; j++) {
      let row = '';
      for (let i = 0; i < gw; i++) { const gx = Math.min(MW - 1, Math.floor(x0 + (i + 0.5) / gw * (x1 - x0))), gy = Math.min(MH - 1, Math.floor(y0 + (j + 0.5) / gh * (y1 - y0))); row += d[(gy * MW + gx) * 4 + 3] > 100 ? '#' : '.'; }
      rows.push(row);
    }
    return { box: { x: x0 * CELL, y: y0 * CELL, w: (x1 - x0) * CELL, h: (y1 - y0) * CELL }, mask: crop.toDataURL('image/png'), coverage: +(b.n / ((x1 - x0) * (y1 - y0))).toFixed(2), grid: rows, area: +(b.n / (MW * MH)).toFixed(3) };
  }

  // ------------------------------------------------------------ the request
  const norm = (b) => ({ x: +(b.x / W).toFixed(3), y: +(b.y / H).toFixed(3), w: +(b.w / W).toFixed(3), h: +(b.h / H).toFixed(3) });
  function sceneContext() {
    const S = st(), P = geo.P, round = (c) => c.map((v) => Math.round(v));
    const palette = {}; for (const k of ['top', 'mid', 'hor', 'sun', 'glow', 'far', 'cliff', 'lit', 'near', 'haze', 'rim', 'shade']) palette[k] = round(P[k]);
    const layers = ['sky', 'suns', 'far', 'cliff', 'near', 'air'].map((id, i) => ({ id, z: i, look: S.layers[id].look, shown: S.layers[id].show }));
    const anchors = { horizonY: 0.64, suns: geo.suns.map((s) => ({ x: +(s.x / W).toFixed(2), y: +(s.y / H).toFixed(2), r: +(s.r / W).toFixed(3) })) };
    if (geo.cliffPoly) { const { pts, m } = geo.cliffPoly, X = pts.map((p) => m.s * p[0] + m.e), Y = pts.map((p) => m.s * p[1] + m.f); anchors.cliff = { x0: +(Math.min(...X) / W).toFixed(2), x1: +(Math.max(...X) / W).toFixed(2), topY: +(Math.min(...Y) / H).toFixed(2), baseY: +(m.s * geo.cliffPoly.base + m.f) / H > 1 ? 1 : +((m.s * geo.cliffPoly.base + m.f) / H).toFixed(2) }; }
    return { palette, layers, anchors, time: +S.time.toFixed(2), timeName: h.timeName(S.time), elements: (S.custom || []).map((c) => ({ name: c.name, z: c.z, box: norm(c.box) })) };
  }
  async function ask() {
    if (busy) return;
    const text = $('#askText').value.trim(); if (!text) { note('Type a request.'); return; }
    const refine = target && st().custom.find((c) => c.id === target);
    let sinfo; if (refine) sinfo = { box: refine.box, mask: refine.mask, coverage: 1, grid: [], area: 0 }; else sinfo = selectionInfo();
    if (!sinfo) { note('Select a region first.'); return; }
    busy = true; paintAsk(); note('Asking');
    if (refine) refine.hidden = true; // the preview background is the scene without this element
    h.renderNow(); const snap = mk(W, H); snap.getContext('2d').drawImage(cv, 0, 0); if (refine) refine.hidden = false;
    const body = { request: text, bbox: norm(sinfo.box), box: sinfo.box, mask: { coverage: sinfo.coverage, areaOfScene: sinfo.area, grid: sinfo.grid }, ...sceneContext() };
    if (refine) body.refine = { code: refine.code, params: refine.params, name: refine.name };
    try {
      const r = await fetch('api/scene/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || 'Ask failed');
      setPreview(j.variants, sinfo, snap, refine ? refine.id : null);
      note(j.cost != null ? `${j.variants.length} options, about $${j.cost.toFixed(2)}` : '');
    } catch (e) { note(String(e.message || e)); }
    busy = false; paintAsk();
  }

  // ------------------------------------------------------------ previews
  const PW = 288, PH = 162;
  function setPreview(variants, sinfo, snap, refineId) {
    // crop window: 16:9 around the box, with room around it
    const b = sinfo.box; let w = Math.max(b.w * 1.7, 360), hh = w * 9 / 16; if (hh < b.h * 1.5) { hh = b.h * 1.5; w = hh * 16 / 9; }
    w = Math.min(w, W); hh = w * 9 / 16;
    const cx = clamp(b.x + b.w / 2 - w / 2, 0, W - w), cy = clamp(b.y + b.h / 2 - hh / 2, 0, H - hh);
    const mask = { id: 'pv', box: b, mask: sinfo.mask };
    const items = variants.map((v) => {
      const c = { id: 'pv' + Math.random().toString(36).slice(2), box: b, mask: sinfo.mask, code: v.code, params: v.params, name: v.name, op: 1 };
      const r = { fn: null, mask: null, off: mk(b.w, b.h), ema: 0, n: 0, err: '' };
      try { r.fn = compile(v.code); } catch (e) { r.err = String(e.message || e).slice(0, 60); }
      maskCanvas(c, (m) => { r.mask = m; });
      const canvas = document.createElement('canvas'); canvas.width = PW * 2; canvas.height = PH * 2;
      return { v, c, r, canvas };
    });
    preview = { items, snap, crop: { x: cx, y: cy, w, h: hh }, sel: sinfo, refineId, mask };
    paintAsk(); drawPreviews(sim.t, true);
  }
  let pvTick = 0;
  function drawPreviews(t, force) {
    if (!preview || (!force && (++pvTick & 1))) return;
    const { items, snap, crop } = preview; fillEnv(st().seed);
    for (const it of items) {
      const x = it.canvas.getContext('2d'), k = it.canvas.width / crop.w;
      x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = 'source-over';
      x.drawImage(snap, crop.x, crop.y, crop.w, crop.h, 0, 0, it.canvas.width, it.canvas.height);
      x.setTransform(k, 0, 0, k, -crop.x * k, -crop.y * k);
      const ok = render(x, it.c, it.r, t, 1, false);
      x.setTransform(1, 0, 0, 1, 0, 0);
      if (!ok && it.r.err && !it.err) { it.err = it.r.err; paintAsk(); }
    }
  }
  function keep(i) {
    if (!preview) return; const it = preview.items[i]; if (!it || it.r.err) return;
    const S = st(); S.custom = S.custom || [];
    if (preview.refineId) {
      const c = S.custom.find((q) => q.id === preview.refineId);
      if (c) { c.code = it.v.code; c.params = it.v.params; c.name = it.v.name; rt.delete(c.id); }
    } else {
      const id = 'e' + Date.now().toString(36);
      S.custom.push({ id, name: it.v.name, show: true, z: 3, op: 1, request: $('#askText').value.trim(), code: it.v.code, params: it.v.params, box: preview.sel.box, mask: preview.sel.mask });
    }
    preview = null; target = null; $('#askText').value = ''; clearSel(); persist(); paintElements(); paintAsk(); h.dirtyAll(); status('');
  }

  // ------------------------------------------------------------ ask card
  const card = $('#askCard');
  function note(t) { $('#askNote').textContent = t || ''; }
  function paintAsk() {
    const refine = target && st().custom.find((c) => c.id === target);
    const open = selecting || !!preview || !!refine;
    card.hidden = !open;
    $('#askTools').hidden = !!refine;
    $('#askTitle').textContent = refine ? `Refine ${refine.name}` : 'Select';
    $('#askGo').disabled = busy; $('#askGo').textContent = busy ? 'Asking' : 'Ask';
    $('#askClear').disabled = !selBox;
    $('#askText').disabled = busy;
    const v = $('#variants'); v.innerHTML = '';
    if (preview) preview.items.forEach((it, i) => {
      const d = document.createElement('div'); d.className = 'sc-var';
      const b = document.createElement('button'); b.type = 'button'; b.className = 'sc-var__pic'; b.setAttribute('aria-label', `Keep ${it.v.name}`); b.dataset.keep = i; b.appendChild(it.canvas);
      d.appendChild(b);
      const row = document.createElement('div'); row.className = 'sc-var__row';
      row.innerHTML = `<span class="ds-label"></span><button type="button" class="ds-btn ds-btn--raised" data-keep="${i}">Keep</button>`;
      row.firstChild.textContent = it.err ? `${it.v.name}: ${it.err}` : it.v.name;
      if (it.err) row.lastChild.disabled = true;
      d.appendChild(row); v.appendChild(d);
    });
  }
  $('#variants').addEventListener('click', (e) => { const b = e.target.closest('[data-keep]'); if (b && !b.disabled) keep(+b.dataset.keep); });
  $('#askGo').addEventListener('click', ask);
  $('#askText').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); ask(); } });
  $('#askClear').addEventListener('click', () => { clearSel(); preview = null; paintAsk(); });
  const toolSeg = segEl('Tool', ['Brush', 'Lasso'], tool, (i) => { tool = i; $('#askSize').hidden = i !== 0; });
  $('#askToolSlot').appendChild(toolSeg);
  sliderRow($('#askSize'), 'Size', () => brush, (v) => { brush = v; }, { light: 1, min: 0, max: 1, step: 0.01 });
  function setSelecting(on) {
    selecting = on; ov.classList.toggle('is-select', on);
    const b = $('#select'); b.setAttribute('aria-pressed', String(on)); $('#selectWord').textContent = on ? 'Done' : 'Select';
    if (on) { target = null; preview = preview && preview.refineId ? null : preview; }
    paintAsk(); if (on) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  $('#select').addEventListener('click', () => { setSelecting(!selecting); });

  // ------------------------------------------------------------ elements list (sliders, order, delete, refine)
  const list = $('#elements');
  function paintElements() {
    const S = st(); list.innerHTML = '';
    const items = S.custom || [];
    $('#elementsSec').hidden = !items.length;
    items.forEach((c) => {
      const r = rt.get(c.id), err = r && r.err;
      const d = document.createElement('details'); d.className = 'sc-el'; d.dataset.id = c.id; if (open.has(c.id)) d.open = true;
      d.innerHTML = `<summary><span class="sc-el__name"></span><span class="sc-el__err" role="status"></span></summary><div class="sc-el__body"></div>`;
      d.querySelector('.sc-el__name').textContent = c.name;
      d.querySelector('.sc-el__err').textContent = err || (c.show ? '' : 'Hidden');
      d.addEventListener('toggle', () => { if (d.open) open.add(c.id); else open.delete(c.id); });
      const body = d.querySelector('.sc-el__body');
      c.params.forEach((q) => sliderRow(body, q.label, () => q.value, (v) => { q.value = v; }, { light: 1, min: q.min, max: q.max, step: (q.max - q.min) / 200, fmt: (v) => `${Math.round(((v - q.min) / (q.max - q.min)) * 100)}%` }));
      sliderRow(body, 'Depth', () => c.z, (v) => { c.z = Math.round(v); }, { light: 1, min: 0, max: 5, step: 1, fmt: (v) => `Above ${SLOTS[Math.round(v)]}` });
      sliderRow(body, 'Opacity', () => c.op, (v) => { c.op = v; }, { light: 1, min: 0, max: 1, step: 0.01 });
      const acts = document.createElement('div'); acts.className = 'sc-el__acts';
      acts.innerHTML = `<button type="button" class="ds-btn ds-btn--raised" data-act="ask">Ask</button><button type="button" class="ds-btn ds-btn--raised" data-act="show">${c.show ? 'Hide' : 'Show'}</button>${err ? '<button type="button" class="ds-btn ds-btn--raised" data-act="retry">Retry</button>' : ''}<button type="button" class="ds-btn ds-btn--ghost" data-act="delete">Delete</button>`;
      acts.addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; act(c, b.dataset.act); });
      body.appendChild(acts);
      list.appendChild(d);
    });
  }
  const open = new Set();
  function act(c, a) {
    if (a === 'delete') { const S = st(); S.custom = S.custom.filter((q) => q.id !== c.id); rt.delete(c.id); if (target === c.id) { target = null; preview = null; } persist(); paintElements(); paintAsk(); status(''); }
    else if (a === 'show') { c.show = !c.show; persist(); paintElements(); }
    else if (a === 'retry') { rt.delete(c.id); status(''); paintElements(); }
    else if (a === 'ask') { target = c.id; preview = null; selecting = false; ov.classList.remove('is-select'); $('#select').setAttribute('aria-pressed', 'false'); $('#selectWord').textContent = 'Select'; paintAsk(); card.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); $('#askText').focus({ preventScroll: true }); }
  }

  // ------------------------------------------------------------ boot and test hooks
  paintSel(); paintAsk(); paintElements();
  return {
    drawSlot, drawPreviews, paintElements,
    test: {
      compile, rt, runtime: runtimeOf,
      state: () => ({ selecting, target, bounds: selBox, previews: preview ? preview.items.map((i) => ({ name: i.v.name, err: i.err || i.r.err })) : null, busy }),
      add(c) { const S = st(); S.custom = S.custom || []; S.custom.push(c); persist(); paintElements(); },
      setPreview, clearSel, keep,
    },
  };
}
