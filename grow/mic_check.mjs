// Record, Play-before-loaded and a /grow/ prefix, in Chromium (simulated mic) and WebKit. Test copies only.
import { createRequire } from 'node:module';
import http from 'node:http';
const require = createRequire('/Users/colemonroe/Projects/satie-app/package.json');
const { chromium, webkit } = require('playwright');
// 5072: strips /grow/ like the Inbox section will; DELAY slows the samples
const prox = http.createServer((q, r) => {
  if (!q.url.startsWith('/grow/')) { r.writeHead(404); return r.end(); }
  const go = () => http.get({ port: 5071, host: '127.0.0.1', path: q.url.slice(5) }, (u) => { r.writeHead(u.statusCode, u.headers); u.pipe(r); });
  q.url.includes('/sounds/') ? setTimeout(go, +process.env.DELAY || 0) : go();
}).listen(5072, '127.0.0.1');
const url = 'http://127.0.0.1:5072/grow/';
for (const [name, eng, opt, perms] of [
  ['chromium', chromium, { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] }, ['microphone']],
  ['webkit', webkit, {}, []],
]) {
  const b = await eng.launch({ headless: true, ...opt });
  const p = await (await b.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, permissions: perms })).newPage();
  const bad = []; p.on('console', (m) => ['error', 'warning'].includes(m.type()) && bad.push(m.text())); p.on('pageerror', (e) => bad.push('pageerror ' + e.message));
  p.on('response', (r) => r.status() >= 400 && bad.push(r.status() + ' ' + r.url()));
  try {
    await p.goto(url);
    await p.click('#play'); // while samples still load
    await p.waitForFunction(() => document.querySelector('#playWord').textContent === 'Pause', null, { timeout: 60000 });
    await p.waitForTimeout(6000);
    console.log(name, 'play', await p.evaluate(() => { const g = window.GrowTest.player, a = new Float32Array(g.g.analyser.fftSize); g.g.analyser.getFloatTimeDomainData(a); return { ctx: g.ctx.state, pos: +g.position.toFixed(2), rms: +Math.sqrt(a.reduce((x, y) => x + y * y, 0) / a.length).toFixed(4), audioSession: navigator.audioSession ? navigator.audioSession.type : 'n/a' }; }));
    const rec = p.locator('[data-act=record]').first();
    for (const how of ['tap to stop', 'auto stop']) {
      await p.locator('[data-act=record]').first().click();
      await p.waitForTimeout(400);
      const word = await p.locator('[data-act=record]').first().textContent();
      if (how === 'tap to stop') { await p.waitForTimeout(2000); await p.locator('[data-act=record]').first().click({ timeout: 2000 }); await p.waitForTimeout(1500); } else await p.waitForTimeout(12500);
      console.log(name, how, '|', word.trim(), '|', await p.evaluate(() => ({ state: window.GrowTest.player.state, yours: document.querySelector('#chipYours').textContent, note: document.querySelector('#note').textContent, btn: document.querySelector('[data-act=record]').textContent.trim() })));
    }
  } catch (e) { console.log(name, 'FAILED', e.message.split('\n')[0]); }
  console.log(name, 'console', bad.length ? bad : 'none');
  await b.close();
}
prox.close();
