// Browser pass for Scene on http://127.0.0.1:5071 (own copy, headless Chromium). Run: node scene_check.mjs
import { createRequire } from 'node:module';
import fs from 'node:fs';
const require = createRequire('/Users/colemonroe/Projects/satie-app/package.json');
const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:5071/scene.html';
const browser = await chromium.launch({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const log = (k, v) => console.log(k + ':', typeof v === 'string' ? v : JSON.stringify(v));
fs.mkdirSync('shots', { recursive: true });
const png = (b64, f) => fs.writeFileSync(f, Buffer.from(b64.split(',')[1], 'base64'));

for (const [tag, vw, vh, dsf] of [['390', 390, 844, 2], ['1512', 1512, 982, 1]]) {
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
await browser.close();
