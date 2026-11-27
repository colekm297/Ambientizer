// Browser pass for Scene on http://127.0.0.1:5071 (own copy, headless Chromium). Run: node scene_check.mjs
// The select-and-ask pass at the bottom makes real Gemini calls through grow/serve.py (about $0.05 each, logged to data/spend.jsonl).
import { createRequire } from 'node:module';
import fs from 'node:fs';
const require = createRequire('/Users/colemonroe/Projects/satie-app/package.json');
const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:5071/scene.html';
const browser = await chromium.launch({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const log = (k, v) => console.log(k + ':', typeof v === 'string' ? v : JSON.stringify(v));
fs.mkdirSync('shots', { recursive: true });
const png = (b64, f) => fs.writeFileSync(f, Buffer.from(b64.split(',')[1], 'base64'));

// ASK_ONLY=1 runs just the select-and-ask pass at the bottom
for (const [tag, vw, vh, dsf] of process.env.ASK_ONLY ? [] : [['390', 390, 844, 2], ['1512', 1512, 982, 1]]) {
  const ctx = await browser.newContext({ viewport: { width: vw, height: vh }, deviceScaleFactor: dsf, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errors.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  await page.goto(BASE); await page.waitForTimeout(1500);
  const lay = await page.evaluate(() => { const c = document.querySelector('#cv').getBoundingClientRect(), p = document.querySelector('#play').getBoundingClientRect(); return { scrollW: document.documentElement.scrollWidth, innerW: innerWidth, canvas: [Math.round(c.width), Math.round(c.height), Math.round(c.top)], ratio: +(c.width / c.height).toFixed(3), playBottom: Math.round(p.bottom), innerH: innerHeight }; });
  log(`${tag} layout`, lay);
  await page.screenshot({ path: `shots/scene_idle_${tag}.png` });

  // every layer panel renders and looks switch
  for (const id of ['sky', 'suns', 'far', 'cliff', 'near', 'air']) {
    await page.click(`#layerSeg [data-value="${id}"]`); await page.waitForTimeout(150);
    const info = await page.evaluate(() => ({ looks: [...document.querySelectorAll('#panel .ds-seg')][1].innerText.replace(/\n+/g, '/'), sliders: document.querySelectorAll('#panel .gr-slider').length }));
    log(`${tag} panel ${id}`, info);
  }
  await page.click('#layerSeg [data-value="cliff"]'); await page.waitForTimeout(200);
  await page.screenshot({ path: `shots/scene_panel_${tag}.png`, fullPage: true });

  if (tag === '1512') {
    // looks sweep: 3 looks per layer, screenshot of the canvas
    const T = 'window.SceneTest';
    for (const [id, n] of [['sky', 3], ['suns', 3], ['far', 3], ['cliff', 3], ['near', 3], ['air', 3]]) for (let k = 0; k < n; k++) {
      const b64 = await page.evaluate(([id, k]) => { const T = window.SceneTest; T.st().layers[id].look = k; T.dirty(); T.renderAt(8); return document.querySelector('#cv').toDataURL('image/png'); }, [id, k]);
      png(b64, `shots/scene_look_${id}${k}.png`);
      await page.evaluate(([id]) => { window.SceneTest.st().layers[id].look = 0; if (id === 'sky') window.SceneTest.st().layers.sky.look = 1; }, [id]);
    }
    await page.evaluate(() => { const T = window.SceneTest; const L = T.st().layers; L.sky.look = 1; for (const k in L) if (k !== 'sky') L[k].look = 0; T.dirty(); });
    // time of day
    for (const t of [0, 0.3, 0.6, 1]) {
      const b64 = await page.evaluate((t) => { const T = window.SceneTest; T.st().time = t; T.dirty(); T.renderAt(8); return document.querySelector('#cv').toDataURL('image/png'); }, t);
      png(b64, `shots/scene_time_${t}.png`);
    }
    await page.evaluate(() => { const T = window.SceneTest; T.st().time = 0.3; T.dirty(); T.setManual(false); });
  }

  // play: audio and the canvas keep going
  await page.evaluate(() => { window.SceneTest.setManual(false); });
  await page.click('#play');
  await page.waitForFunction(() => window.SceneTest.player.state === 'playing', null, { timeout: 20000 });
  await page.waitForTimeout(6000);
  const pl = await page.evaluate(() => { const p = window.SceneTest.player, a = new Float32Array(p.g.analyser.fftSize); p.g.analyser.getFloatTimeDomainData(a); let s = 0; for (const x of a) s += x * x; return { ctx: p.ctx.state, pos: +p.position.toFixed(2), rms: +Math.sqrt(s / a.length).toFixed(5), world: p.S.world, frames: window.__sceneFrames, btn: document.querySelector('#playWord').textContent }; });
  log(`${tag} playing`, pl);
  await page.waitForTimeout(1500);
  log(`${tag} frames advancing`, `${pl.frames} -> ${await page.evaluate(() => window.__sceneFrames)}`);
  await page.screenshot({ path: `shots/scene_playing_${tag}.png` });
  // a refrain: fake one on the scene clock, check indicator and lift
  await page.evaluate(() => { const T = window.SceneTest, pos = T.player.position; T.fakeRefrains([{ start: pos + 1, end: pos + 14, peak: true }]); });
  await page.waitForTimeout(9000);
  log(`${tag} refrain`, await page.evaluate(() => ({ lift: +window.SceneTest.sim.lift.toFixed(3), chipHidden: document.querySelector('#refrain').hidden })));
  await page.screenshot({ path: `shots/scene_refrain_${tag}.png` });
  await page.evaluate(() => { window.SceneTest.fakeRefrains(null); window.SceneTest.player.stop(); });
  await page.waitForTimeout(500);
  log(`${tag} real plan refrains`, await page.evaluate(() => window.SceneTest.player.plan.refrains.slice(0, 3).map((r) => [Math.round(r.start), Math.round(r.end)])));

  if (tag === '1512') {
    // motion locality
    await page.evaluate(() => window.SceneTest.setManual(true));
    const d = await page.evaluate(() => { const T = window.SceneTest; T.renderAt(10); return T.regionDiff(10, 13); });
    log('motion locality (mean abs diff 0..255, 3 s apart)', d);
    // dirty path: a layer hidden, a changed look, time
    // export 8 s through the button
    await page.evaluate(() => { window.SceneTest.setManual(false); window.SceneTest.exportSeconds = 8; });
    const dl = page.waitForEvent('download', { timeout: 60000 });
    await page.click('#export');
    await page.waitForTimeout(2000);
    log('export status mid', await page.evaluate(() => document.querySelector('#status').textContent));
    const dd = await dl; const out = 'shots/scene_export_test.mp4'; await dd.saveAs(out);
    log('export file', { file: out, bytes: fs.statSync(out).size, status: await page.evaluate(() => document.querySelector('#status').textContent) });
    // photo import (sky and cliff) with a generated image
    await page.click('#layerSeg [data-value="sky"]'); await page.waitForTimeout(200);
    await page.setInputFiles('#panel input[type=file]', process.env.PHOTO); await page.waitForTimeout(1200);
    log('photo import', await page.evaluate(() => ({ look: window.SceneTest.st().layers.sky.look, has: !!window.SceneTest.photos.sky, panel: document.querySelector('#panel').innerText.replace(/\n+/g, ' | ') })));
    await page.screenshot({ path: 'shots/scene_photo_1512.png' });
    await page.reload(); await page.waitForTimeout(1500);
    log('photo persists after reload', await page.evaluate(() => ({ has: !!window.SceneTest.photos.sky, look: window.SceneTest.st().layers.sky.look, time: window.SceneTest.st().time })));
    await page.click('#layerSeg [data-value="sky"]'); await page.waitForTimeout(200);
    await page.click('#panel [data-act="remove"]'); await page.waitForTimeout(500);
    log('photo removed', await page.evaluate(() => ({ has: !!window.SceneTest.photos.sky, look: window.SceneTest.st().layers.sky.look })));
    // show/hide
    await page.click('#layerSeg [data-value="cliff"]'); await page.waitForTimeout(150);
    await page.click('#panel .ds-seg__opt:text("Hide")'); await page.waitForTimeout(500);
    log('cliff hidden', await page.evaluate(() => window.SceneTest.st().layers.cliff.show));
    await page.screenshot({ path: 'shots/scene_cliffhidden_1512.png' });
    await page.click('#panel .ds-seg__opt:text("Show")');
  }
  log(`${tag} console errors/warnings`, errors.length ? errors : 'none');
  await ctx.close();
}

// ---------------------------------------------------------------- select and ask (real Gemini call, test copy only)
for (const [tag, vw, vh, dsf, touch] of [['1512', 1512, 982, 1, false], ['390', 390, 844, 2, true]].filter((q) => !process.env.ASK_TAGS || process.env.ASK_TAGS.split(',').includes(q[0]))) {
  const ctx = await browser.newContext({ viewport: { width: vw, height: vh }, deviceScaleFactor: dsf, hasTouch: touch });
  const page = await ctx.newPage(); const errors = [];
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errors.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  await page.goto(BASE); await page.waitForTimeout(1200);
  const A = (name) => `shots/scene_ask_${tag}_${name}.png`;
  // cliff face in scene px, then the page px of a stroke across its upper middle
  const cliff = await page.evaluate(() => { const g = window.SceneTest.geo.cliffPoly, X = g.pts.map((p) => g.m.s * p[0] + g.m.e), Y = g.pts.map((p) => g.m.s * p[1] + g.m.f); const x0 = Math.min(...X), x1 = Math.max(...X), top = Math.min(...Y); return { x0, x1, top, base: g.m.s * g.base + g.m.f }; });
  const rect = await page.evaluate(() => { const r = document.querySelector('#cv').getBoundingClientRect(); return { l: r.left, t: r.top, w: r.width, h: r.height }; });
  const pt = (sx, sy) => ({ x: rect.l + (sx / 1280) * rect.w, y: rect.t + (sy / 720) * rect.h });
  const cxm = (cliff.x0 + cliff.x1) / 2 - 20, y1 = cliff.top + (cliff.base - cliff.top) * 0.28, y2 = cliff.top + (cliff.base - cliff.top) * 0.62;
  await page.click('#select'); await page.waitForTimeout(300);
  log(`${tag} ask card open`, await page.evaluate(() => ({ hidden: document.querySelector('#askCard').hidden, word: document.querySelector('#selectWord').textContent, pe: getComputedStyle(document.querySelector('#selcv')).pointerEvents })));
  if (touch) {
    // lasso with real touch events: a loop around the cliff face
    await page.click('#askToolSlot .ds-seg__opt:text("Lasso")');
    const cdp = await ctx.newCDPSession(page);
    const loop = []; for (let k = 0; k < 24; k++) { const a = (k / 24) * Math.PI * 2; loop.push(pt(cxm + Math.cos(a) * 150, (y1 + y2) / 2 + Math.sin(a) * (y2 - y1) * 0.55)); }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [loop[0]] });
    for (const q of loop.slice(1)) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [q] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  } else {
    const a = pt(cxm - 150, y1), b = pt(cxm + 150, y1);
    await page.mouse.move(a.x, a.y); await page.mouse.down();
    for (let row = 0; row < 4; row++) { const yy = y1 + (y2 - y1) * (row / 3); const l = pt(cxm - 150, yy), r = pt(cxm + 150, yy); await page.mouse.move(row % 2 ? r.x : l.x, l.y, { steps: 6 }); await page.mouse.move(row % 2 ? l.x : r.x, l.y, { steps: 14 }); }
    await page.mouse.up();
  }
  await page.waitForTimeout(200);
  const selState = await page.evaluate(() => window.SceneTest.ask.state());
  log(`${tag} selection (grid cells)`, selState.bounds);
  await page.screenshot({ path: A('1_selected') });
  await page.fill('#askText', 'a natural rock arch');
  const t0 = Date.now(); await page.click('#askGo');
  await page.waitForFunction(() => window.SceneTest.ask.state().previews || /^(Type|Select|Model|The model|Daily|Ask failed|No Gemini)/.test(document.querySelector('#askNote').textContent), null, { timeout: 120000 });
  log(`${tag} ask`, { seconds: +((Date.now() - t0) / 1000).toFixed(1), note: await page.evaluate(() => document.querySelector('#askNote').textContent), previews: (await page.evaluate(() => window.SceneTest.ask.state())).previews });
  await page.waitForTimeout(700);
  await page.screenshot({ path: A('2_variants'), fullPage: tag === '390' });
  const nPrev = await page.evaluate(() => document.querySelectorAll('#variants .sc-var').length);
  log(`${tag} variant cards`, nPrev);
  if (!nPrev) { await ctx.close(); continue; }
  await page.click('#variants .sc-var:nth-child(1) .ds-btn'); await page.waitForTimeout(800);
  const kept = await page.evaluate(() => { const c = window.SceneTest.st().custom; return c.map((q) => ({ id: q.id, name: q.name, z: q.z, params: q.params.map((p) => p.name + '=' + (+p.value).toFixed(2)), box: q.box, codeLen: q.code.length, maskLen: q.mask.length })); });
  log(`${tag} kept layer`, kept);
  await page.evaluate(() => window.SceneTest.renderAt(9));
  await page.screenshot({ path: A('3_kept') });
  // move a slider, run a fake refrain, confirm the pixels change
  await page.evaluate(() => document.querySelector('#elements summary').click()); await page.waitForTimeout(200);
  const before = await page.evaluate(() => { window.SceneTest.renderAt(12); const b = window.SceneTest.st().custom[0].box, x = document.querySelector('#cv').getContext('2d'); return [...x.getImageData(b.x, b.y, b.w, b.h).data].reduce((s, v) => s + v, 0); });
  const sl = page.locator('#elements .gr-slider input').first();
  await sl.evaluate((el) => { el.value = el.min; el.dispatchEvent(new Event('input', { bubbles: true })); });
  const lo = await page.evaluate(() => { window.SceneTest.renderAt(12); const b = window.SceneTest.st().custom[0].box, x = document.querySelector('#cv').getContext('2d'); return [...x.getImageData(b.x, b.y, b.w, b.h).data].reduce((s, v) => s + v, 0); });
  await sl.evaluate((el) => { el.value = el.max; el.dispatchEvent(new Event('input', { bubbles: true })); });
  const hi = await page.evaluate(() => { window.SceneTest.renderAt(12); const b = window.SceneTest.st().custom[0].box, x = document.querySelector('#cv').getContext('2d'); return [...x.getImageData(b.x, b.y, b.w, b.h).data].reduce((s, v) => s + v, 0); });
  log(`${tag} slider changes pixels`, { before, lo, hi, changed: lo !== hi });
  await page.screenshot({ path: A('4_slider') });
  const lift = await page.evaluate(() => { const T = window.SceneTest, sum = (t, r) => { T.renderAt(t, r); const b = T.st().custom[0].box, x = document.querySelector('#cv').getContext('2d'); return [...x.getImageData(b.x, b.y, b.w, b.h).data].reduce((s, v) => s + v, 0); }; const a = sum(14, null); T.sim.lift = 0; const bR = sum(30, [{ start: 20, end: 60, peak: true }]); return { calm: a, refrainSimLift: +T.sim.lift.toFixed(3), withRefrain: bR }; });
  log(`${tag} refrain lift (summed channel values over box)`, lift);
  // persist across reload
  const persisted = await page.evaluate(() => JSON.stringify(window.SceneTest.st().custom.map((c) => c.params.map((p) => p.value))));
  await page.reload(); await page.waitForTimeout(1500);
  const after = await page.evaluate(() => { window.SceneTest.renderAt(9); const T = window.SceneTest, c = T.st().custom; const r = c[0] && T.ask.rt.get(c[0].id); return { n: c.length, vals: JSON.stringify(c.map((q) => q.params.map((p) => p.value))), err: r && r.err, hasFn: !!(r && r.fn), hasMask: !!(r && r.mask), panelItems: document.querySelectorAll('#elements .sc-el').length }; });
  log(`${tag} after reload`, { sameParams: after.vals === persisted, ...after });
  await page.screenshot({ path: A('5_reloaded') });

  if (tag === '1512') {
    // sandbox: a throwing layer, a slow layer, a layer that names a blocked word
    const bad = await page.evaluate(async () => {
      const T = window.SceneTest, base = T.st().custom[0], out = {};
      const mk = (id, code) => ({ ...base, id, name: id, code, params: [] });
      try { T.ask.compile('const x = window.location; return;'); out.window = 'compiled'; } catch (e) { out.window = 'blocked: ' + e.message; }
      try { T.ask.compile('ctx.fillRect(0,0,1,1); fetch("/x")'); out.fetch = 'compiled'; } catch (e) { out.fetch = 'blocked: ' + e.message; }
      try { const f = T.ask.compile('const k = ["doc", "ument"]; return [typeof top, typeof Image, typeof Date, typeof indexedDB, typeof Math].join();'); out.shadow = f({}, 0, {}, {}, {}); } catch (e) { out.shadow = 'err ' + e.message; }
      T.ask.add(mk('t_throw', 'ctx.fillStyle="red"; ctx.fillRect(box.x,box.y,10,10); throw new Error("boom");'));
      T.ask.add(mk('t_slow', 'let n = 0; for (let i = 0; i < 4e7; i++) n += i % 7; ctx.fillRect(box.x,box.y,5,5);'));
      T.renderAt(20); await new Promise((r) => setTimeout(r, 400)); // masks load async
      for (let i = 0; i < 40; i++) T.renderAt(20 + i / 30);
      for (const id of ['t_throw', 't_slow']) out[id] = T.ask.rt.get(id) && T.ask.rt.get(id).err;
      out.status = document.querySelector('#status').textContent;
      out.errChips = [...document.querySelectorAll('#elements .sc-el__err')].map((e) => e.textContent);
      out.insideMask = (() => { const c = T.st().custom[0], r = T.ask.rt.get(c.id); return !!r.mask; })();
      return out;
    });
    log('sandbox', bad);
    await page.screenshot({ path: A('6_disabled') });
    await page.evaluate(() => { const T = window.SceneTest; for (const id of ['t_throw', 't_slow']) { const S = T.st(); S.custom = S.custom.filter((c) => c.id !== id); T.ask.rt.delete(id); } });
    // clipped to the mask: fill the whole scene and confirm nothing lands outside the mask box
    const clip = await page.evaluate(async () => {
      const T = window.SceneTest, base = T.st().custom[0], S = T.st(); S.custom.push({ ...base, id: 't_fill', name: 't_fill', code: 'ctx.fillStyle="#00ff00"; ctx.fillRect(0,0,1280,720);', params: [] });
      T.st().custom[0].show = false; T.renderAt(5); await new Promise((r) => setTimeout(r, 400)); T.renderAt(5.1); const x = document.querySelector('#cv').getContext('2d'), d = x.getImageData(0, 0, 1280, 720).data, b = base.box;
      let inside = 0, outside = 0; for (let i = 0; i < 1280 * 720; i++) { if (d[i * 4] < 40 && d[i * 4 + 1] > 230 && d[i * 4 + 2] < 40) { const px = i % 1280, py = (i / 1280) | 0; if (px >= b.x && px < b.x + b.w && py >= b.y && py < b.y + b.h) inside++; else outside++; } }
      S.custom = S.custom.filter((c) => c.id !== 't_fill'); T.st().custom[0].show = true; T.ask.rt.delete('t_fill'); return { greenInsideBox: inside, greenOutsideBox: outside };
    });
    log('mask clip (a full-scene fill)', clip);
    // refine through the second Ask, then delete
    await page.evaluate(() => { const T = window.SceneTest; T.renderAt(9); document.querySelector('#elements summary').click(); });
    await page.click('#elements [data-act="ask"]'); await page.waitForTimeout(300);
    log('refine card', await page.evaluate(() => ({ title: document.querySelector('#askTitle').textContent, tools: document.querySelector('#askTools').hidden })));
    const codeBefore = await page.evaluate(() => window.SceneTest.st().custom[0].code);
    await page.fill('#askText', 'make it taller with more cracks');
    await page.click('#askGo');
    await page.waitForFunction(() => window.SceneTest.ask.state().previews || /^(Type|Select|Model|The model|Daily|Ask failed|No Gemini)/.test(document.querySelector('#askNote').textContent), null, { timeout: 120000 });
    await page.waitForTimeout(600);
    log('refine ask', await page.evaluate(() => ({ note: document.querySelector('#askNote').textContent, previews: window.SceneTest.ask.state().previews })));
    await page.screenshot({ path: A('7_refine') });
    if (await page.locator('#variants .sc-var').count()) {
      await page.click('#variants .sc-var:nth-child(2) .ds-btn'); await page.waitForTimeout(600);
      const r2 = await page.evaluate(() => { window.SceneTest.renderAt(9); const c = window.SceneTest.st().custom; return { n: c.length, name: c[0].name }; });
      log('refine kept', { n: r2.n, name: r2.name, codeChanged: await page.evaluate((b) => window.SceneTest.st().custom[0].code !== b, codeBefore) });
      await page.screenshot({ path: A('8_refined') });
    }
    await page.evaluate(() => document.querySelector('#elements summary') && !document.querySelector('#elements details').open && document.querySelector('#elements summary').click());
    await page.click('#elements [data-act="delete"]'); await page.waitForTimeout(400);
    log('after delete', await page.evaluate(() => ({ n: window.SceneTest.st().custom.length, secHidden: document.querySelector('#elementsSec').hidden, saved: JSON.parse(localStorage.getItem('scene.current')).custom.length })));
  }
  log(`${tag} ask console errors/warnings`, errors.length ? errors : 'none');
  await ctx.close();
}
await browser.close();
