# Handoff — Ambientizer / Odyssey release work (2026-08-09)

Supersedes the 2026-08-08 entry. The big change since then: **living stills are no
longer procedural.** Cole's words on seeing the first clean generative loop:
"Bro that looks phenomenal. Theres no way! We cracked it!"

## Cold-start reading order

1. `AGENTS.md` — project source of truth (architecture, run/restart, multi-agent rules)
2. `fal_loop.py` — the new loop pipeline; read its module docstring first
3. `HANDOFF-TAIL-ambientizer.md` (beside this file) — the live conversation thread; open with it

## What changed today

**The loop problem is solved.** Commits `ae8717c` and `017f5a8` on
`living-still-harden`.

The wall was real and not a settings problem: hand a video model the same image as
first and last frame and it collapses to a still, because the endpoint constraint
lives in latent space while the motion prompt is only a suggestion. The way around
it is **two legs, neither with matching endpoints** — leg A runs free from the
still, leg B starts on leg A's true last frame and ends on the still. That is
`fal_loop.py`.

Three things that cost real attempts, all now encoded in the module:

- **Veo ignores camera instructions in the negative prompt.** "no camera movement"
  as a negative did nothing; the same words as the OPENING clause of the positive
  prompt locked the camera completely. The first render pushed in across both legs
  and therefore could never land home. Cole saw it instantly: "V1 doesnt loop it
  boomerangs."
- **Leg B lands the framing but never the water.** A generative model has no
  periodic function underneath it, so the last frame's wave pattern is simply a
  different pattern. `wrap_blend` folds the clip's own tail over its head with a
  rising alpha. Time runs one direction throughout, so `feedback-never-boomerang`
  is not violated.
- **Judge the seam with `wrap_ratio`, never raw `wrap`.** Raw wrap is an absolute
  pixel delta, so 1080p inflates it and a 720p comparison reads as a regression
  that is not there. Under 1.0 means the loop point is a smaller step than an
  ordinary frame. The shipped master is 0.82.

Endpoints: `fal-ai/veo3.1/lite/image-to-video` and
`fal-ai/veo3.1/lite/first-last-frame-to-video`. $0.03/sec at 720p with audio off,
$0.05 at 1080p. About $0.36 per 720p attempt, ~90s. Cole funded $10 of fal credits
on 2026-08-08; **$2.24 spent, ~$7.76 left**. `FAL_KEY` is in `.env`.

Also: **Chrome control works in CLI sessions.** The previous home-dir session told
Cole it did not have it and was wrong. That mistake is what cost a day.

## Where things are

**The Sirens release is BUILT and STAGED in `output/release/sirens/`:**

- `sirens_strait_3h_intro.mp4` — the upload candidate. 3:00:00 exactly, 1920x1080
  at 24fps, AAC 384k, silver aperture sting on the front, 17.5GB
- `sirens_strait_3h.mp4` — identical without the sting
- `thumbnail.png` — Nolan style, cool grey accent (`#c9d8e4`), hook "THE SIRENS'
  STRAIT", subtitle "3 HOURS"
- `copy.md` — title, description, tags, two alternate titles
- `cell.mp4` (11.2s video loop, CRF 18) and `audio_cell.wav` (1135s) — everything
  is tiled from these two
- `intro_preview.mp4`, `seam_sampler.mp4`, `seam_sampler.mp3` — review cuts

**Audio take: `eec20d97`, "The Sirens' Strait", Cole's 3-star, B minor.** He picked
it as "literally the first one siren we generated 3 star rating" — it is both.

**A defect found and fixed that would have shipped:** the mastered wav is 1175s,
which looks like a prepared loop cell (1200 minus the 25s crossfade), but its end
does not meet its start. Tiling it put an audible click and a 3dB level step every
19m35s. `audio_cell.wav` is the real seamless cell, built by crossfading the
track's tail over its own head with a 40s `acrossfade`. Verified at three
boundaries in the final encode: edge jump below the track's own 99.9th-percentile
sample jump. **Any future export must use `audio_cell.wav`, not the raw mastered
wav.**

Verified, not assumed: frame at 2:45:00 intact, duration exactly 10800s, all
sampled audio joins clean.

## In flight at retirement

- **Cole has not watched the 3-hour file yet.** That is the only thing between this
  and an upload. NOTHING POSTS BEFORE HE REVIEWS.
- **Unresolved: he reports hearing no audio on delivered clips.** The files measure
  fine — AAC-LC stereo, start_time 0.000, -16.8 dBFS RMS, 0.64 peak — and he
  confirmed his player was unmuted with a screenshot. Never settled whether it is
  the phone's inline video player. Every clip sent before `seam_sampler.mp4` was
  deliberately silent (`-an`), so nothing earlier would have revealed it. An mp3 of
  the same 60 seconds was sent last; his verdict on it never came.
- He got impatient with being asked to choose: "Whatever you think just stop asking
  and lets move this forward for gods sakes." Decide and report. Do not queue up
  questions.

## Open questions for Cole

1. Does the 3-hour file pass on your TV?
2. Any redlines on the title and description in `copy.md`?
3. Do you hear audio on the mp3 I sent, or is your player eating it?

## Promised and not delivered

- Nothing outstanding on the Sirens release itself; it is built.
- **Fair Wind / Ithaca has had none of this treatment.** `inputs/ithaca_dawn2.png`
  is approved and its audio take is still unpicked (drum-free lineage, job
  `2bacadbf` was the latest). It is now a $0.36 loop plus an export away.
- Cole floated mermaid-style sirens ("theres no way they are quite hitting the
  sirens from the movie") — a new Midjourney still plus a loop, about 4 minutes and
  $0.36. Parked deliberately in favor of shipping.
- Generator rebuild: bake standing exclusions (no drums/cymbals/electric
  guitar/arpeggios, everything sustains) into every music generation. Still just
  discussed.

## Notes

- `boomerang_check.py` was written today and DELETED, not committed. Its flow test
  returns zeros on a locked camera and it produced two wrong readings. Do not
  resurrect it without rebuilding the measurement.
- The old procedural sway engine still works and is still committed. It is simply
  no longer what carries a scene.
- Stray uncommitted edits remain in `segmenter.py` and `visual_generator.py`, plus
  the untracked `_batch*.py` scratch scripts — another session's, leave them.
