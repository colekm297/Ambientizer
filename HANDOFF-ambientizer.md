> SNAPSHOT as of 2026-10-15 07:40. Anything newer — git commits, file mtimes, or your own conversation — outranks this file. Verify before acting.

# Handoff — Ambientizer (2026-10-15)

This replaces the 2026-09-13 handoff entirely. Back then the open items were a Fair Wind retitle, a consent click, and a Dusk retention read. All three are done and superseded.

## Cold-start reading order

1. `CLAUDE.md`: Cole's "Who you are" section. Releases are SUSPENDED (since 2026-09-20), the music is always his pick, and the away-move is plumbing and prep only.
2. `docs/HOW-A-TRACK-IS-MADE.md`: his method (one 10-minute text-mode take, raw prompt, music_v2, looped to the hour, never stitched), what his 3-star prompts share, and the traps.
3. `AGENTS.md`: Models section (Claude Opus 5.5 only through `llm.py`, Gemini 4 Argon first), Field notes, and gotchas 13 to 15.
4. `HANDOFF-TAIL-ambientizer.md`: the live thread.

## What changed since 2026-09-13 (31 commits, 828887f..bd99d23 on `living-still-harden`)

- **Channel package, 2026-09-18.** Fair Wind was retitled "The Odyssey | Going Home After 20 Years | 1 Hour Deep Work Ambient" and Dusk "Dune | Last Light on Arrakis | 1 Hour Deep Focus Ambient". Both carry Cole's plain CTA line in the description and a pinned comment. Chief set up end screens and three-way thumbnail tests in Studio. Watermark and avatar were never set (channel-level, Cole's hands).
- **Hail Mary "Tau Ceti Vigil"** (private 2dElNNIY91w): HELD. Cole: "sounds like a Doom soundtrack." Its decision trail is in the Chief chat.
- **The method was relearned.** Agent sessions had drifted into stitch mode, music_v1, 1-minute sketches, and percussion bans. Cole corrected all of it. It's written down in the docs and in memory (`feedback-one-take-looped`, `feedback-listen-in-the-app`, `feedback-music-is-coles-choice`).
- **App fixes.** Raw mode is `planner_mode: "raw"`. The PCM channel detection now reads the samples, not the requested length. The model is now in the music cache key. Every song shows its WORLD tag (set via `POST /api/job/<id>/meta`). The app has an icon and a manifest, and a Dock launcher at `~/Applications/Ambientizer.app`. The Tailscale Mac app is installed so the Mac resolves the tailnet name.
- **Daily experiments.** launchd `com.cole.ambientizer-daily` runs at 07:30 and executes `daily_experiment.py`. It designs one take with Claude from his ratings and its lessons file (`data/daily_lessons.md`), then generates it and titles it "Daily · …". The metric is stars per week (`docs/DAILY-EXPERIMENTS.md`).
- **Frontier models (Cole's picks).** `claude-opus-5-5` through `llm.py`, `gemini-4-argon` first (slow; Cole: "it can take longer if it's better"), `music_v2` default. `music_v2_5` is selectable but caps around 6 minutes.
- **First-play lag fixed (2026-10-15).** Cold first byte dropped from 19.4 s to 1.8 s through the tailnet URL: the MP3 now streams while it encodes, and a prewarm thread caches the 25 newest songs (gotcha 15).

## Where things are

- Live public: Fair Wind (HvumlX9trg0), Dusk (y6YS18A8hYY), plus the older catalog. Nothing new has been published since 09-11.
- Private, held: 2dElNNIY91w (Hail Mary). Private, dead, Cole's delete call: 1Eolx51Xr60, xpuDzlkZYRA.
- The app is at http://ambientizer-mac.tail07d072.ts.net:5050 (Mac and iPhone).
- Dailies so far: 43199a6e "Interstellar · Daily · The Endurance Passes Saturn" (unrated), and a083d482 "Lord of the Rings · Daily · Frodo Sails West", the design-panel pick. Cole played Frodo at 06:57 on 2026-10-15; it's unrated so far.

## In flight at retirement

- Nothing half-built. The 07:30 daily keeps running on its own. The prewarm thread runs inside the app.

## Open bug (yours)

- **Selecting job 32e87510 ("Three Knocks (misfire: rewritten, 1 min)") froze Chrome's renderer** for minutes, before any `/api/audio` request. The log shows status, parts, `visual/living-still` and a 400 on `POST /api/visual/boomerang/32e87510`, then nothing. This was my 2026-09-26 misfire: interpreter-rewritten, 60 s returned, originally decoded as mono. The suspects are its living-still or visual state, or a client loop on that 400. Reproduce on localhost with DevTools open before guessing. Then check whether any normal track can hit the same path.

## Open questions for Cole (one line each)

1. How does Frodo Sails West rate? Star it in the app; the daily lessons learn from it.
2. Want the misfire takes (32e87510, 9a250bd5 duplicate) hidden from the list?

## Promised and not delivered

- None outstanding. A weekly stars report was offered as standing practice; the first full week closes 2026-10-19.

## Notes

- The branch is `living-still-harden`, and pushes go there. CLAUDE.md says main. Never reconciled; ask Chief before merging.
- Untracked on purpose: `inputs/`, `saved_stills/`, `brand/out/sting_silver.mp4`, `logs/` (gitignored).
