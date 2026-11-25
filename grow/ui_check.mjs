// Browser pass on http://127.0.0.1:5071 (headless Chromium, own profile). Idle and playing at two sizes.
import { createRequire } from 'node:module';
import fs from 'node:fs';
const require = createRequire('/Users/colemonroe/Projects/satie-app/package.json');
const { chromium } = require('playwright');
const SP = '/private/tmp/claude-501/-Users-colemonroe-Projects-Ambientizer/d78f9849-d408-4dce-a708-60343f603b5a/scratchpad';
const BASE = 'http://127.0.0.1:5071/index.html';
const browser = await chromium.launch({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const res = {};
const log = (k, v) => { res[k] = v; console.log(k + ':', typeof v === 'string' ? v : JSON.stringify(v)); };
for (const [tag, vw, vh] of [['390', 390, 844], ['1512', 1512, 982]]) {
  const ctx = await browser.newContext({ viewport: { width: vw, height: vh }, deviceScaleFactor: tag === '390' ? 2 : 1, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errors.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  await page.goto(BASE); await page.evaluate(() => window.GrowTest.ready()); await page.waitForTimeout(1200);
  await page.screenshot({ path: `shots/idle_${tag}.png` });
  const lay = await page.evaluate(() => { const b = document.querySelector('#play').getBoundingClientRect(); const w = document.querySelector('#worldSeg').getBoundingClientRect(); return { scrollW: document.documentElement.scrollWidth, innerW: innerWidth, playBottom: Math.round(b.bottom), worldBottom: Math.round(w.bottom), innerH: innerHeight, canvas: [document.querySelector('#pic').width, document.querySelector('#pic').height] }; });
  log(`${tag} layout`, lay);
  // painted canvas?
  const painted = await page.evaluate(() => { const c = document.querySelector('#pic'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4 * 97) if (d[i] > 0) n++; return n; });
  log(`${tag} canvas painted samples`, painted);
  // play
  await page.click('#play');
  await page.waitForFunction(() => window.GrowTest.player.state === 'playing', null, { timeout: 15000 });
  await page.waitForTimeout(9000);
  const st = await page.evaluate(() => { const p = window.GrowTest.player; const a = new Float32Array(p.g.analyser.fftSize); p.g.analyser.getFloatTimeDomainData(a); let s = 0; for (const x of a) s += x * x; return { ctx: p.ctx.state, pos: +p.position.toFixed(2), rms: +Math.sqrt(s / a.length).toFixed(5), btn: document.querySelector('#playWord').textContent, time: document.querySelector('#time').textContent, frames: window.__lastDraw && window.__lastDraw.frames }; });
  log(`${tag} playing`, st);
  await page.waitForTimeout(1500);
  const f2 = await page.evaluate(() => window.__lastDraw.frames);
  log(`${tag} canvas frames advancing`, `${st.frames} -> ${f2}`);
  await page.screenshot({ path: `shots/playing_${tag}.png` });
  // controls while playing
  await page.evaluate(() => { const r = document.querySelector('#r_bpm'); r.value = 64; r.dispatchEvent(new Event('input', { bubbles: true })); });
  await page.click('#worldSeg [data-value="Quiet Shore"]');
  await page.click('#reseed');
  await page.waitForTimeout(1500);
  const c1 = await page.evaluate(() => ({ S: window.GrowTest.getS(), chip: document.querySelector('#chipKey').textContent, bpmOut: document.querySelector('#o_bpm').textContent, state: window.GrowTest.player.state, planBpm: window.GrowTest.player.plan.meta.bpm, pos: window.GrowTest.player.position }));
  log(`${tag} after controls`, { world: c1.S.world, key: c1.chip, bpmOut: c1.bpmOut, planBpm: c1.planBpm, state: c1.state, seed: c1.S.seed });
  await page.waitForTimeout(2500);
  const pos2 = await page.evaluate(() => window.GrowTest.player.position);
  log(`${tag} still playing after replan`, `pos ${c1.pos.toFixed(1)} -> ${pos2.toFixed(1)}`);
  // pause / resume
  await page.click('#play'); await page.waitForTimeout(600);
  log(`${tag} paused`, await page.evaluate(() => window.GrowTest.player.state));
  await page.click('#play'); await page.waitForTimeout(600);
  log(`${tag} resumed`, await page.evaluate(() => window.GrowTest.player.state));
  // length + key + mode
  await page.click('#lenSeg [data-value="3600"]'); await page.selectOption('#key', '7'); await page.selectOption('#mode', 'dorian'); await page.waitForTimeout(800);
  log(`${tag} 60 min`, await page.evaluate(() => ({ L: window.GrowTest.player.plan.meta.length, refrains: window.GrowTest.player.plan.refrains.length, total: document.querySelector('#timeTotal').textContent, next: document.querySelector('#next').textContent })));
  await page.screenshot({ path: `shots/playing60_${tag}.png` });
  await page.click('#lenSeg [data-value="600"]');
  // save piece, reload, persisted
  await page.fill('#saveName', 'Test piece'); await page.click('#save');
  log(`${tag} saved list`, await page.evaluate(() => [...document.querySelectorAll('#saved .gr-piece .ds-label')].map((e) => e.textContent)));
  // import
  await page.setInputFiles('[data-role="bed"] input[type=file]', `${SP}/test_a3.wav`);
  await page.waitForSelector('[data-role="bed"] .ds-chip', { timeout: 15000 });
  log(`${tag} import`, await page.evaluate(() => ({ role: document.querySelector('[data-role="bed"]').innerText.replace(/\n+/g, ' | '), yours: document.querySelector('#yoursLine').textContent })));
  await page.click('[data-role="bed"] [data-act="up"]'); await page.waitForTimeout(500);
  log(`${tag} root nudge`, await page.evaluate(() => document.querySelector('[data-role="bed"] .gr-role__pitch .ds-meta').textContent));
  // mic denied
  await page.click('[data-role="voice"] [data-act="record"]'); await page.waitForTimeout(1200);
  log(`${tag} mic message`, await page.evaluate(() => document.querySelector('#note').textContent || '(none)'));
  // export 20 s through the button
  await page.evaluate(() => { window.GrowTest.exportSeconds = 20; });
  const dl = page.waitForEvent('download', { timeout: 120000 });
  await page.click('#export');
  const d = await dl; const out = `renders/ui_export_${tag}.wav`; await d.saveAs(out);
  log(`${tag} export file`, { file: out, bytes: fs.statSync(out).size, expected: 20 * 192000 + 44 });
  await page.evaluate(() => window.GrowTest.player.stop());
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `shots/full_${tag}.png`, fullPage: true });
  // reload: saved piece and your sound persist
  await page.reload(); await page.evaluate(() => window.GrowTest.ready()); await page.waitForTimeout(1200);
  log(`${tag} after reload`, await page.evaluate(() => ({ saved: document.querySelectorAll('#saved .gr-piece').length, yours: document.querySelector('#yoursLine').textContent })));
  log(`${tag} console errors/warnings`, errors.length ? errors : 'none');
  await ctx.close();
}
await browser.close();
