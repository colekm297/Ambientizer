// Unit check of note extraction on three synthetic hums. Node only, no browser.
import { buildTunes } from './sing.js';
import { synthHum } from './sing_synth.mjs';
import { scaleMidi, MODES, plan, defaultSettings } from './grow.js';

let fails = 0;
const ok = (c, msg) => { console.log((c ? 'ok   ' : 'FAIL ') + msg); if (!c) fails++; };
const inScale = (i) => true; // scale steps are in the scale by construction
const grid = (t) => t.notes.every((n) => Math.abs(n.b * 2 - Math.round(n.b * 2)) < 1e-9 && Math.abs(n.l * 2 - Math.round(n.l * 2)) < 1e-9);
const ids = (t) => t.notes.map((n) => n.i).join(',');

const cases = [
  { name: 'A contour, E aeolian 56 bpm, an octave low', S: { key: 4, mode: 'aeolian', bpm: 56 },
    steps: [[0, 1], [2, 1], [4, 1.5], [3, 0.5], [2, 1], [1, 1], [2, 1], [0, 3]], octave: -1, expect: [0, 2, 4, 3, 2, 1, 2, 0], lead: 0.35 },
  { name: 'B very short, C ionian 60 bpm', S: { key: 0, mode: 'ionian', bpm: 60 },
    steps: [[2, 1], [3, 1], [4, 2]], octave: 0, expectMoreThan: 3, lead: 0.2, flat: 0 },
  { name: 'C flat 40 cents, leap past an octave, stray blip and a cough, D lydian 46 bpm', S: { key: 2, mode: 'lydian', bpm: 46 },
    steps: [[0, 1], [2, 1], [4, 1.5], [13, 1.5], [11, 1], [9, 3]], octave: -1, flat: -40, lead: 0.4, blip: true, expect: null },
];
for (const c of cases) {
  const S = Object.assign(defaultSettings(), c.S);
  const beat = 60 / S.bpm;
  const blips = c.blip ? [{ t: c.lead + 1.2 * beat + 0.02, dur: 0.07, midi: 75 }] : [];
  const h = synthHum({ ...S, steps: c.steps.map(([i, beats]) => ({ i, beats })), octave: c.octave, lead: c.lead, flat: c.flat || 0, blips, coughAt: c.blip ? c.lead + 6 * beat + 0.2 : null });
  const t0 = performance.now();
  const r = buildTunes(h.data, h.sr, S);
  const ms = Math.round(performance.now() - t0);
  console.log(`\n${c.name}  (${ms} ms, raw notes ${r.raw && r.raw.length}, grid shift ${r.shift && r.shift.toFixed(3)}, tuning ${r.tuning && r.tuning.toFixed(2)} st)`);
  if (r.error) { ok(false, 'tune built: ' + r.error); continue; }
  const { close, polished } = r.tunes;
  console.log('  raw  ', r.raw.map((n) => n.midi.toFixed(1) + '@' + n.t0.toFixed(2)).join(' '));
  console.log('  close   ', ids(close), '| beats', close.notes.map((n) => n.b + '/' + n.l).join(' '));
  console.log('  polished', ids(polished), '| beats', polished.notes.map((n) => n.b + '/' + n.l).join(' '));
  ok(grid(close) && grid(polished), 'onsets and lengths on the 8th grid');
  for (const [nm, t] of [['close', close], ['polished', polished]]) {
    const last = t.notes[t.notes.length - 1], pcs = ((last.i % 7) + 7) % 7;
    ok([0, 2, 4].includes(pcs), `${nm} ends on a chord tone (step ${pcs})`);
    ok(t.notes.every((n, k) => k === 0 || n.b > t.notes[k - 1].b), `${nm} onsets increase`);
    const ms2 = t.notes.map((n) => scaleMidi(n.i, S.key, S.mode));
    ok(Math.min(...ms2) >= 52 && Math.max(...ms2) <= 83, `${nm} in the melody range (${Math.min(...ms2)}..${Math.max(...ms2)})`);
    ok(t.total <= 13 + 1e-9 || S.bpm < 50, `${nm} fits the refrain (${t.total} beats)`);
  }
  ok(((polished.notes.at(-1).i % 7) + 7) % 7 === 0, 'polished ends on the tonic');
  ok(polished.notes.at(-1).l >= 2.5, `polished final note held (${polished.notes.at(-1).l} beats)`);
  if (c.expect) { ok(ids(close) === c.expect.join(','), 'close matches the contour ' + c.expect.join(',')); { const p = polished.notes.map((n) => n.i), e = c.expect; ok(p.length === e.length && p.every((x, k) => Math.abs(x - e[k]) <= 1) && p.filter((x, k) => x !== e[k]).length <= 2, 'polished keeps the contour (within a step, at most 2 notes moved): ' + p.join(',')); } }
  if (c.expectMoreThan) { ok(close.notes.length > c.expectMoreThan && polished.notes.length > c.expectMoreThan, 'short take extended (' + close.notes.length + ' and ' + polished.notes.length + ' notes)'); }
  if (c.blip) {
    ok(!polished.notes.some((n) => n.i > 15), 'blip removed');
    const maxLeap = Math.max(...polished.notes.slice(1).map((n, k) => Math.abs(n.i - polished.notes[k].i)));
    ok(maxLeap <= 7, `polished leaps stay within an octave (max ${maxLeap} steps)`);
  }
  // plan() uses it
  const S2 = Object.assign({}, S, { tune: polished });
  const pl = plan(S2);
  const first = pl.events.filter((e) => e.role === 'voice' && e.tag === 'refrain' && e.ref === 0).sort((a, b) => a.t - b.t);
  const want = polished.notes.map((n) => scaleMidi(n.i, S.key, S.mode));
  ok(first.length >= polished.notes.length && want.every((m, k) => Math.abs(first[k].midi - m) <= 12 && ((first[k].midi - m) % 12 === 0)), 'plan() plays the tune as the first refrain statement');
}
console.log(fails ? `\n${fails} FAILED` : '\nall passed');
process.exit(fails ? 1 : 0);
