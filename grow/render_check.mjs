// Renders the 10-minute piece of each world in headless Chromium and saves it into renders/.
import { createRequire } from 'node:module';
const require = createRequire('/Users/colemonroe/Projects/satie-app/package.json');
const { chromium } = require('playwright');
const worlds = { 'Folding City': { key: 4, mode: 'aeolian', bpm: 56 }, 'Quiet Shore': { key: 2, mode: 'lydian', bpm: 50 }, 'Desert Dusk': { key: 11, mode: 'dorian', bpm: 46 } };
const only = process.argv[2] && process.argv[2] !== 'all' ? process.argv[2] : null;
const secs = +(process.argv[3] || 600);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
page.on('console', (m) => { if (m.type() === 'error') console.log('console error:', m.text()); });
page.on('pageerror', (e) => console.log('page error:', e.message));
await page.goto('http://127.0.0.1:5071/index.html');
await page.evaluate(() => window.GrowTest.ready());
for (const [w, o] of Object.entries(worlds)) {
  if (only && only !== w) continue;
  const name = w.replace(/ /g, '_').toLowerCase() + (secs === 600 ? '_600.wav' : `_test${secs}.wav`);
  const t0 = Date.now();
  const size = await page.evaluate(([w, o, name, secs]) => window.GrowTest.render(Object.assign({ world: w, length: 600, seed: 20261124 }, o), secs, name), [w, o, name, secs]);
  console.log(w, name, size, ((Date.now() - t0) / 1000).toFixed(0) + 's');
}
await browser.close();
