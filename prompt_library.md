# Prompt Library — proven generation prompts

Reference prompts with known outcomes, for reuse and as style anchors for the
generator rebuild. The pattern all three share is the **Small Light recipe**:
long single generation (10 min), instruments given NARRATIVE ROLES, diegetic
world-sound woven into the fabric, an explicit shape over time, and concrete
music-theory anchors (key/tempo) the model can execute.

Lessons paid for in credits (2026-08-02, sirens session):
- **The build is the point.** Stripping the arc ("no crescendo") produced a
  track that "never actually starts." Stripping the melody into pure texture
  produced wallpaper. Edit the PEAK, never the arc.
- **Cap the peak warm, don't remove it.** "At its fullest the music becomes
  CLOSER, WARMER and more enveloping, never louder or harsher" fixed v1's
  harsh ending while keeping its life. Planner mapped it to max_energy 0.85
  (Small Light's exact ceiling) vs v1's 0.95.
- Same prompt = new performance each time. Take-selection is normal producing.

---

## Hail Mary — "A Small Light in the Dark"  (job 003d71e2)
Best-retaining video on the channel: 14.1 min avg/view, 23% of an hour held,
no ads/intro/thumbnail. The benchmark.

An evolving cosmic soundscape inspired by Project Hail Mary, blending symphonic orchestral textures with organic alien communication sounds. Warm strings and subtle choir pads drift through vast harmonic spaces in D minor, punctuated by ethereal ocarina and bass clarinet melodies that echo Rocky's musical language. Gentle spacecraft ambience weaves through the musical fabric - soft mechanical hums, distant engine drones, and the whispered breath of life support systems creating an intimate bubble of hope against the cosmic void. Piano swells and brings variance to the long term warmth of the soundscape.

---

## The Sirens' Strait v1 — the take Cole loved  (job eec20d97)
Flaw: peak overshoots into loud/dissonant in the final stretch (max_energy 0.95).
Character: dual-force structure (LURE / PERIL / SHIP) — keep.

Slow cinematic ambient soundscape at ~40 BPM, built on a low D pedal drone in dark modal harmony, for the sirens' strait of the Odyssey. THE LURE: a wordless female vocal carries an achingly sweet three-note descending call — the sirens' language — shimmering in soft microtonal clusters with parallel quartal motion, distantly answered and doubled by a breathy aulos and bowed lyra drifting across glassy water. THE PERIL beneath: sul ponticello cellos and double basses sustain the D pedal while a slow analog glissando creeps between sonorities a tritone apart, hypnotically perilous, never resolving. THE SHIP: a steady muffled pulse of wooden oars and low frame drum keeps unhurried rowing time — the crew with waxed ears — with quiet diegetic creaks of rigging and rope strain and soft granular sea-mist woven into the fabric. The sirens' call grows slowly nearer and stronger, peaks past the midpoint, then recedes as the ship passes beyond the strait. Richly textured yet unhurried, never busy, instrumental except the wordless voice, breathing with agonized enchantment through the very end.

---

## The Sirens' Strait — capped warm peak  (job b043fc9e)
v1 verbatim except the peak clause. Confirmed good by ear. This peak language
is the reusable fix for "gets too crazy near the end":

Slow cinematic ambient soundscape at ~40 BPM, built on a low D pedal drone in dark modal harmony, for the sirens' strait of the Odyssey. THE LURE: a wordless female vocal carries an achingly sweet three-note descending call — the sirens' language — shimmering in soft microtonal clusters with parallel quartal motion, distantly answered and doubled by a breathy aulos and bowed lyra drifting across glassy water. THE PERIL beneath: sul ponticello cellos and double basses sustain the D pedal while a slow analog glissando creeps between sonorities, hypnotically perilous, never resolving. THE SHIP: a steady muffled pulse of wooden oars and low frame drum keeps unhurried rowing time — the crew with waxed ears — with quiet diegetic creaks of rigging and rope strain and soft granular sea-mist woven into the fabric. The sirens' call grows slowly nearer and stronger, peaks past the midpoint, then recedes as the ship passes beyond the strait — but at its fullest the music becomes CLOSER, WARMER and more enveloping, never louder or harsher: the peak is intimacy, not volume, the dissonance never grows beyond the gentle unease of the opening minutes, and the final quarter returns fully to the calm of the beginning. Richly textured yet unhurried, never busy, instrumental except the wordless voice, breathing with agonized enchantment through the very end.
