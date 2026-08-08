# Handoff — Ambientizer / Odyssey release work (2026-08-08)

Outgoing session ran from `~` (home), retired in favor of a fresh session in this
project. Everything below is current as of the evening of Aug 8.

## Cold-start reading order

1. `AGENTS.md` — project source of truth (architecture, run/restart, multi-agent rules)
2. `living_still.py` — the recipe system + guardrails; every render goes through it
3. `HANDOFF-TAIL-ambientizer.md` (beside this file) — the live conversation thread; open with it

## What changed today (branch `living-still-harden`, merged to main through `ec4f05e`; later commits `0f317de`, `b8c5514` + another session's `2abe822`, `bf686f8` are branch-only — merge to main at next stopping point)

- **dawn_shore / moonlit_shore recipes** (this session + a parallel session):
  long swells (density 0.8, shear_cap 0.30), shimmer, brighten-only glints
  (`twinkle` gained `lift: true` — symmetric twinkle mottled bright water black),
  NO twinkle on dawn water at all.
- **Wind**: `sway` layer for vegetation (rooted, gusts, tall=slow) and — new,
  commit `b8c5514` — `anchor: "top"` hang mode for cloth: sails pinned at the
  yard, robes at the shoulders, hems swing free and rise slightly. Registered
  `sway` in `_IMAGE_MOVEMENT_TYPES`.
- **Guard fix**: aliveness is measured over the union of animated-region masks,
  not the whole frame (water-only scenes false-failed at 10x dilution).
- **render_recipe** accepts a `regions=` override for images the segmenter
  misreads; auto-derives `glitter` (bright water) and flora.
- **Key lesson (memory `project-living-still-image-spec`)**: dead renders are an
  IMAGE problem, not a recipe problem. The engine needs textured water + a light
  streak. Glassy pastel gradients are always invisible. Fix by regenerating the
  image with texture language, not by re-tuning layers.

## Where things are

- **Approved visuals** (both rendered at preview 1456x816, guard-clean):
  - **Fair Wind / Ithaca**: `inputs/ithaca_dawn2.png` (2912x1632, textured golden
    dawn water, lavender foreground). Cole: "That looks good... workable for now."
  - **Sirens**: `inputs/sirens_final.png` (2912x1632, empty crewless galley,
    four white-robed sirens in left foreground facing the ship, moonlight streak).
    v5 render adds sail billow + robe-hem flutter via hang-mode sway. Sent to
    Cole; **his verdict on v5 not yet in** (v4 he liked).
- **Sirens v5 render specifics** (script: session scratchpad `sirens_cloth.py`,
  scratchpad is `/private/tmp/claude-501/-Users-colemonroe/47ea973c-.../scratchpad/`
  and dies with the session — the RECIPE + masks logic is what matters):
  hull carved out of open_water mask (`w[390:528, 630:820] = 0` at 1456x816 —
  dark hull segments as water and warps otherwise), sail mask = bright pixels in
  box (560,225)-(830,440), robes = bright in (0,360)-(370,816), sail sway
  `anchor:top amount:0.32 cycles:2 slow_ratio:0.7`, robes `amount:0.22 cycles:3`.
  Rebuild this as a driver in the repo if v5 is approved (it currently lives
  nowhere permanent).
- **Midjourney workflow**: fully drivable via Claude-in-Chrome on Cole's account
  (he granted this). Full-res pulls: navigate to the job, fetch the CDN PNG from
  a www.midjourney.com page into OPFS, copy from
  `~/Library/Application Support/Google/Chrome/Profile 4/File System/<NNN>/t/00/...`
  (find by exact byte size). curl/downloads/localhost ALL fail. Details in memory
  `gotcha-mj-browser-download`.
- **Unpicked audio**: SIRENS track (6 takes exist) and FAIR WIND track (drum-free
  lineage, job `2bacadbf` latest). Cole picks by ear; he has not picked.

## In flight at retirement

- Awaiting Cole's verdict on Sirens v5 (cloth motion) — sent as the last message.
- His anchor idea: parked. Position taken: breathing sail reads as becalmed,
  title/description carry the story; offer a MJ region-edit on the bow only if
  he still wants a literal anchor line.
- Cole wants a better plants-in-wind solution eventually ("workable for now" on
  Fair Wind's sway).

## Promised and not delivered

- **The full release run** — for whichever scene he green-lights first (Sirens has
  precedence): 3-hour export, intro sting (`intro_compositor.add_intro_sting`),
  feeling-first title, story description, silver Nolan-style thumbnail
  (`thumbnail_maker` nolan styles), staged for review. **NOTHING posts before Cole
  reviews.** This was promised repeatedly and is the immediate next action once
  he picks audio + confirms v5.
- Generator rebuild: bake standing exclusions (no drums/cymbals/electric
  guitar/arpeggios, everything sustains) into every music generation. Discussed,
  not built.
- Stray uncommitted edits in repo: `segmenter.py` (1 line), `visual_generator.py`,
  untracked `_batch10.py`/`_batch20.py` — another session's; leave unless claimed.

## Open questions for Cole

1. Sirens v5 (sail + robes moving) — good to lock as the Sirens visual?
2. Which Sirens audio take? (that's the last blocker for the release build)
3. Fair Wind audio take — same question, second priority.
