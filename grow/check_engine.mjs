import { plan, WORLDS, defaultSettings, findClashes, noteName } from './grow.js';
import { createHash } from 'node:crypto';
const fmt=(t)=>`${Math.floor(t/60)}:${String(Math.round(t%60)).padStart(2,'0')}`;
for (const w of Object.keys(WORLDS)) {
  const S = defaultSettings(w); S.length = 600;
  const P = plan(S), P2 = plan(S);
  const same = createHash('md5').update(JSON.stringify(P.events)).digest('hex') === createHash('md5').update(JSON.stringify(P2.events)).digest('hex');
  console.log(`\n== ${w}  ${['C','C#','D','Eb','E','F','F#','G','Ab','A','Bb','B'][S.key]} ${S.mode} ${S.bpm} BPM  events=${P.events.length}  deterministic=${same}`);
  const rs = P.refrains;
  console.log('refrain starts:', rs.map(r=>fmt(r.start)+(r.peak?'*':'')).join('  '));
  console.log('gaps (s):', rs.slice(1).map((r,i)=>Math.round(r.start-rs[i].start)).join(', '), ' durations:', rs.map(r=>Math.round(r.dur)).join(','), ' quiet:', rs.map(r=>Math.round(r.quietEnd-r.end)).join(','));
  console.log('swell dB:', rs.map(r=>r.swellDb).join(','), ' variants:', rs.map(r=>`${r.variant.answer===2?'3rd':'6th'}/${r.variant.dev}/${r.variant.harm}/${r.variant.end}/reg${r.variant.reg}`).join(' | '));
  const inR = (e)=>rs.some(r=>e.t>=r.start&&e.t<r.end);
  const v = P.events.filter(e=>e.role==='voice');
  const vr = v.filter(inR), vf = v.filter(e=>!inR(e));
  console.log(`voice notes: in refrains ${vr.length}, between (fragments) ${vf.length}; motif idx=${P.motif.idx.join(',')} beats=${P.motif.beats.join(',')} total=${P.motif.total}`);
  const roles={}; P.events.forEach(e=>roles[e.role]=(roles[e.role]||0)+1); console.log('by role', JSON.stringify(roles));
  const cl = findClashes(P.events);
  console.log('minor-second clashes among simultaneous pitched voices:', cl.length);
  const cd = P.chords.filter(c=>c.refrain<0).map(c=>c.t1-c.t0);
  console.log(`ordinary chord lengths s: min ${Math.min(...cd).toFixed(1)} max ${Math.max(...cd).toFixed(1)}; refrain chord ${(P.refrains[0].dur/3).toFixed(1)} s x3`);
  console.log('first refrain voice notes:', v.filter(e=>e.ref===0).map(e=>noteName(e.midi)).join(' '));
}
// replan stability + 60 min
const S=defaultSettings(); S.length=3600; const P=plan(S);
console.log('\n60 min Folding City: events', P.events.length, 'refrains', P.refrains.length, 'clashes', findClashes(P.events).length);
for (const seed of [1,2,3,4,5,6,7,8]) for (const w of Object.keys(WORLDS)) { const s=defaultSettings(w); s.seed=seed; s.refrainEvery=[90,150,240][seed%3]; const c=findClashes(plan(s).events).length; if(c) console.log('CLASH',seed,w,c); }
console.log('seed sweep done');
// pace sweep: refrain duration for every BPM
let mx=0,mn=999; for(let b=36;b<=84;b++){const s=defaultSettings();s.bpm=b;const p=plan(s);const d=p.refrains[0].dur;mx=Math.max(mx,d);mn=Math.min(mn,d);} console.log('refrain dur over all BPM: min',mn.toFixed(1),'max',mx.toFixed(1));

// gap rule: first by 100 s, no gap over 180 s (start to start, and last refrain start to the end), none running into the ending
let bad = 0;
for (const len of [600, 3600]) for (const w of Object.keys(WORLDS)) for (const R of [90, 120, 150]) for (let seed = 1; seed <= 12; seed++) {
  const s = defaultSettings(w); s.length = len; s.refrainEvery = R; s.seed = seed * 7919;
  const p = plan(s), rs = p.refrains; const why = [];
  if (!rs.length) why.push('no refrains');
  else {
    if (rs[0].start > 100) why.push('first at ' + Math.round(rs[0].start));
    for (let i = 1; i < rs.length; i++) if (rs[i].start - rs[i - 1].start > 180) why.push('gap ' + Math.round(rs[i].start - rs[i - 1].start));
    if (len - rs[rs.length - 1].start > 180) why.push('end gap ' + Math.round(len - rs[rs.length - 1].start));
    if (rs[rs.length - 1].quietEnd > len - 8) why.push('runs into ending');
    for (let i = 1; i < rs.length; i++) if (rs[i].start < rs[i - 1].quietEnd + 5) why.push('overlap');
    if (rs.length < (len === 600 ? 3 : 20)) why.push('only ' + rs.length);
  }
  if (why.length) { bad++; console.log('FAIL', len, w, 'R', R, 'seed', seed, why.join(', ')); }
}
const d = defaultSettings(); const p10 = plan(d).refrains;
console.log('gap rule failures:', bad);
if (bad) process.exitCode = 1;
