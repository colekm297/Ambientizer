// Sing end to end in Chromium against the TEST copy (python3 serve.py 5071). Fake mic plays a synthetic hum.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { synthHum, wavBytes } from './sing_synth.mjs';
const require = createRequire('/Users/colemonroe/Projects/satie-app/package.json');
const { chromium } = require('playwright');
const URL_ = 'http://127.0.0.1:5071/';
const DIR = path.dirname(new URL(import.meta.url).pathname);
let fails = 0;
const ok = (c, m) => { console.log((c ? 'ok   ' : 'FAIL ') + m); if (!c) fails++; };

// hum: E aeolian, 56 bpm, the 8-note contour an octave low. The take starts 0.3 s + 4 beats before the tune.
const beat = 60 / 56;
const steps = [[0, 1], [2, 1], [4, 1.5], [3, 0.5], [2, 1], [1, 1], [2, 1], [0, 3]].map(([i, beats]) => ({ i, beats }));
const hum = synthHum({ key: 4, mode: 'aeolian', bpm: 56, steps, octave: -1, lead: 0.4 + 4 * beat + 0.12, tail: 0, seed: 11 });
const padded = new Float32Array(Math.ceil(30 * hum.sr)); padded.set(hum.data.subarray(0, Math.min(hum.data.length, padded.length)));
const wavPath = path.join(os.tmpdir(), 'grow_sing_hum.wav');
fs.writeFileSync(wavPath, wavBytes(padded, hum.sr));

const b = await chromium.launch({ headless: true, args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--use-file-for-fake-audio-capture=' + wavPath, '--autoplay-policy=no-user-gesture-required'] });
const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, permissions: ['microphone'] });
const p = await ctx.newPage();
// Headless Chromium's fake capture device records short and near silent, so the mic is replaced by the hum
// played through a MediaStreamDestination. MediaRecorder, decode, note extraction and preview all run for real.
await p.route('**/__hum.wav', (r) => r.fulfill({ body: fs.readFileSync(wavPath), contentType: 'audio/wav' }));
await p.addInitScript(() => {
  navigator.mediaDevices.getUserMedia = async () => {
    const c = new AudioContext({ sampleRate: 48000 });
    const buf = await c.decodeAudioData(await (await fetch('/__hum.wav')).arrayBuffer());
    const src = c.createBufferSource(); src.buffer = buf; const dst = c.createMediaStreamDestination();
    src.connect(dst); src.start(c.currentTime + 0.02);
    const s = dst.stream; const tr = s.getAudioTracks()[0]; const stop = tr.stop.bind(tr);
    tr.stop = () => { stop(); try { src.stop(); c.close(); } catch {} };
    return s;
  };
});
const bad = [];
p.on('console', (m) => { if (['error','warning'].includes(m.type())) { bad.push(m.text()); console.log('PAGE', m.type(), m.text()); } });
p.on('pageerror', (e) => bad.push('pageerror ' + e.message));
p.on('response', (r) => r.status() >= 400 && bad.push(r.status() + ' ' + r.url()));
await p.goto(URL_);
await p.evaluate(() => window.GrowTest.ready());
const sec = p.locator('#roles');
await sec.scrollIntoViewIfNeeded();
await p.screenshot({ path: path.join(DIR, 'shots/sing_idle_390.png') });
ok(await p.locator('[data-act=sing]').count() === 1, 'Sing button is on the Melody part only');
ok((await p.locator('.gr-role[data-role=voice] [data-act]').allTextContents()).map((s) => s.trim()).join('|').startsWith('Import|Record|Sing'), 'order: Import, Record, Sing');

await p.locator('[data-act=sing]').click();
await p.waitForTimeout(1500);
await p.locator('#singPanel').scrollIntoViewIfNeeded();
await p.screenshot({ path: path.join(DIR, 'shots/sing_countin_390.png') });
console.log('status', await p.locator('#singStatus').textContent());
await p.waitForTimeout(8000);
await p.screenshot({ path: path.join(DIR, 'shots/sing_singing_390.png') });
console.log('status', await p.locator('#singStatus').textContent());
await p.waitForFunction(() => window.GrowTest.sing && window.GrowTest.sing.result(), null, { timeout: 60000 }).catch(async (e) => { console.log('PANEL', await p.evaluate(() => [document.querySelector('#singPanel')?.innerText, window.GrowTest.lastNote(), !!window.GrowTest.sing, window.GrowTest.sing && window.GrowTest.sing.busy()])); throw e; });
await p.waitForTimeout(600);
const r = await p.evaluate(() => { const x = window.GrowTest.sing.result(); return { close: x.tunes.close, polished: x.tunes.polished, raw: x.raw.map((n) => +n.midi.toFixed(1)), shift: x.shift }; });
console.log('raw', r.raw.join(' '), '| shift', r.shift.toFixed(3));
console.log('close   ', r.close.notes.map((n) => n.i).join(','), '| polished', r.polished.notes.map((n) => n.i).join(','));
const want = [0, 2, 4, 3, 2, 1, 2, 0];
ok(r.close.notes.map((n) => n.i).join() === want.join(), 'Close matches the contour sung through the mic');
ok(r.polished.notes.length === 8 && r.polished.notes.every((n, k) => Math.abs(n.i - want[k]) <= 1), 'Polished keeps the contour');
ok([r.close, r.polished].every((t) => t.notes.every((n) => (n.b * 2) % 1 === 0 && (n.l * 2) % 1 === 0)), 'on the 8th grid');
ok(r.polished.notes.at(-1).i % 7 === 0 && r.polished.notes.at(-1).l >= 3, 'Polished ends on the tonic, held');
await p.locator('#singPanel').scrollIntoViewIfNeeded();
await p.screenshot({ path: path.join(DIR, 'shots/sing_result_polished_390.png') });
await p.locator('#singSeg [data-value=close]').click();
await p.waitForTimeout(800);
await p.screenshot({ path: path.join(DIR, 'shots/sing_result_close_390.png') });
ok(await p.locator('#singSeg [data-value=close]').getAttribute('aria-checked') === 'true', 'Close selected');
await p.locator('[data-sing=play]').click(); await p.waitForTimeout(300);
console.log('play button', (await p.locator('[data-sing=play]').textContent()).trim());
await p.locator('[data-sing=play]').click();
await p.locator('#singSeg [data-value=polished]').click();
await p.waitForTimeout(500);

// what the plan does without and with the tune
const planFirst = (withTune) => p.evaluate(async (withTune) => {
  const g = await import('/grow.js');
  const S = Object.assign({}, window.GrowTest.getS()); if (!withTune) delete S.tune;
  const pl = g.plan(S);
  const ev = pl.events.filter((e) => e.role === 'voice' && e.tag === 'refrain' && e.ref === 0).sort((a, b) => a.t - b.t).map((e) => e.midi);
  const fr = pl.events.filter((e) => e.role === 'voice' && e.tag === 'fragment').length;
  return { ev, fr, refrains: pl.refrains.length, tune: pl.meta.tune };
}, withTune);
const before = await planFirst(true);
ok(before.tune === false, 'no tune yet: generated refrain');
await p.locator('[data-sing=use]').click();
await p.waitForTimeout(400);
const used = await p.evaluate(() => ({ tune: window.GrowTest.getS().tune, ls: JSON.parse(localStorage.getItem('grow.current')).tune }));
ok(used.tune && used.tune.notes.length === 8 && used.ls && used.ls.notes.length === 8, 'Use stores S.tune (and localStorage grow.current)');
const after = await planFirst(true), without = await planFirst(false);
const tuneMidi = used.tune.notes.map((n) => [64, 66, 67, 69, 71, 72, 74][((n.i % 7) + 7) % 7] + 12 * Math.floor(n.i / 7));
console.log('refrain 1 notes with tune', after.ev.slice(0, 8).join(','), '| generated', without.ev.slice(0, 8).join(','), '| tune', tuneMidi.join(','));
ok(after.tune === true && after.ev.slice(0, 8).join() === tuneMidi.join(), 'plan() plays his tune as the first statement of the refrain');
ok(after.ev.join() !== without.ev.join(), 'refrain differs from the generated one');
ok(after.fr > 0, 'fragments between refrains use the tune (' + after.fr + ')');
// variation: statements 2 and 3
const stm = await p.evaluate(async () => {
  const g = await import('/grow.js'); const pl = g.plan(window.GrowTest.getS());
  return pl.refrains.map((r) => pl.events.filter((e) => e.role === 'voice' && e.tag === 'refrain' && e.ref === r.k).sort((a, b) => a.t - b.t).map((e) => e.midi));
});
console.log('every refrain:', stm.map((x) => x.length + ' notes').join(', '));
ok(stm.every((s) => s.length >= 24 && s.slice(0, 8).join() === stm[0].slice(0, 8).join()), 'every refrain opens with the same tune, later statements vary');
await p.locator('.gr-role[data-role=voice]').scrollIntoViewIfNeeded();
await p.screenshot({ path: path.join(DIR, 'shots/sing_used_390.png') });
ok(await p.locator('.gr-role__tune').count() === 1, 'Your tune indicator shows');

// reload
await p.reload(); await p.evaluate(() => window.GrowTest.ready()); await p.waitForTimeout(500);
const re = await p.evaluate(() => ({ tune: window.GrowTest.getS().tune && window.GrowTest.getS().tune.notes.length, plan: window.GrowTest.player.plan.meta.tune, ind: !!document.querySelector('.gr-role__tune') }));
ok(re.tune === 8 && re.plan === true && re.ind, 'tune survives reload (state, plan, indicator)');
await p.locator('.gr-role[data-role=voice]').scrollIntoViewIfNeeded();
await p.screenshot({ path: path.join(DIR, 'shots/sing_reload_390.png') });

// key change follows
const kc = await p.evaluate(async () => { const g = await import('/grow.js'); const S = Object.assign({}, window.GrowTest.getS(), { key: 9, mode: 'dorian' }); const pl = g.plan(S); const t = pl.events.filter((e) => e.role === 'voice' && e.tag === 'refrain' && e.ref === 0).sort((a, b) => a.t - b.t)[0].midi; return { first: t, scaleMidi: g.scaleMidi(S.tune.notes[0].i, 9, 'dorian') }; });
ok(kc.first === kc.scaleMidi, `tune follows a key change (first note ${kc.first})`);

// export
for (const f of ['sing_export_tune.wav', 'sing_export_plain.wav']) { try { fs.unlinkSync(path.join(DIR, 'renders', f)); } catch {} }
const t0 = Date.now();
const sz1 = await p.evaluate(() => window.GrowTest.render({}, 130, 'sing_export_tune.wav'));
await p.evaluate(() => { const S = window.GrowTest.getS(); delete S.tune; });
const sz2 = await p.evaluate(() => window.GrowTest.render({}, 130, 'sing_export_plain.wav'));
const a = fs.readFileSync(path.join(DIR, 'renders/sing_export_tune.wav')), c2 = fs.readFileSync(path.join(DIR, 'renders/sing_export_plain.wav'));
const rms = (buf) => { let s = 0, n = 0; for (let i = 44; i < buf.length - 1; i += 40) { const v = buf.readInt16LE(i) / 32768; s += v * v; n++; } return Math.sqrt(s / n); };
ok(sz1 > 1e6 && a.length === c2.length && rms(a) > 0.005, `Export renders with the tune (${(sz1 / 1e6).toFixed(1)} MB, rms ${rms(a).toFixed(3)}, ${(Date.now() - t0) / 1000}s)`);
ok(!a.equals(c2), 'Export with the tune differs from the one without');
for (const f of ['sing_export_tune.wav', 'sing_export_plain.wav']) fs.unlinkSync(path.join(DIR, 'renders', f));

// clear
await p.evaluate(() => window.GrowTest.getS());
await p.reload(); await p.evaluate(() => window.GrowTest.ready());
// the earlier delete only changed memory (not saved); the stored tune is back: Clear removes it
ok(await p.locator('.gr-role__tune').count() === 1, 'tune back after reload (the delete above was memory only)');
await p.locator('[data-act=clear-tune]').click(); await p.waitForTimeout(300);
const cl = await p.evaluate(() => ({ s: !!window.GrowTest.getS().tune, ls: !!JSON.parse(localStorage.getItem('grow.current')).tune, ind: !!document.querySelector('.gr-role__tune'), plan: window.GrowTest.player.plan.meta.tune }));
ok(!cl.s && !cl.ls && !cl.ind && !cl.plan, 'Clear removes the tune everywhere');

// Record and Import still there; Record still works with echoCancellation off
const rec = await p.evaluate(async () => { const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices); let c; navigator.mediaDevices.getUserMedia = (x) => { c = x; return orig(x); }; document.querySelector('.gr-role[data-role=low] [data-act=record]').click(); await new Promise((r) => setTimeout(r, 800)); document.querySelector('.gr-role[data-role=low] [data-act=record]').click(); await new Promise((r) => setTimeout(r, 1500)); navigator.mediaDevices.getUserMedia = orig; return { c, yours: document.querySelector('#chipYours').textContent }; });
ok(rec.c && rec.c.audio.echoCancellation === false && /1 of 4/.test(rec.yours), 'Record still works, echoCancellation off for his sound: ' + JSON.stringify(rec));

console.log('console errors:', bad.length ? bad : 'none');
if (bad.length) fails++;
await b.close();
console.log(fails ? `${fails} FAILED` : 'all passed');
process.exit(fails ? 1 : 0);
