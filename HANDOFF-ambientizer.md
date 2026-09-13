> SNAPSHOT as of 2026-09-13 09:30. Anything newer — git commits, file mtimes, or your own conversation — outranks this file. Verify before acting.

# Handoff — Ambientizer (2026-09-13)

Supersedes the 2026-08-09 entry entirely. That one described a Sirens release
waiting on review and a Fair Wind that "had none of this treatment." Both have
shipped since, Veo has been replaced, and the channel now has a retention method.

## Cold-start reading order

1. `AGENTS.md` — source of truth; gotchas 7-11 were written this session
2. `HANDOFF-TAIL-ambientizer.md` — the live thread; open with it
3. Memory index (`~/.claude/projects/-Users-colemonroe-Projects-Ambientizer/memory/MEMORY.md`) — one-line pointers to every lesson below

## What changed since 2026-08-09 (commits fd265be..73390bd on `living-still-harden`)

- **Fair Wind Home shipped.** Cole published it 2026-09-07: https://www.youtube.com/watch?v=HvumlX9trg0. 1 hour, Seedance 1.5 Pro loop, audio take `2bacadbf` with the track's natural lead-in. Two earlier private uploads are dead (`1Eolx51Xr60` loud-start audio bug, `xpuDzlkZYRA` stuck in YouTube processing for a week) and await his delete verdict via Chief.
- **Dusk Over Arrakis shipped.** Built 2026-09-08 on Chief's default as the keeper-vs-puller test; Cole published it himself 2026-09-11 22:02Z: https://www.youtube.com/watch?v=y6YS18A8hYY. Files in `output/release/dusk_arrakis/`.
- **Veo is gone from the pipeline.** `fal-ai/bytedance/seedance/v1.5/pro/image-to-video` with `end_image_url` = start still and `camera_fixed: True`; the raw output ships with no fold and no flatten. See `_build_dusk_master.py` for the reusable 1-hour build (natural-head audio timeline, acrossfade middle-segment cell, sting + tiles, join and loudness checks).
- **Release masters now reach R2 on build.** `offload_release.py <name> --apply`; `--check` is green for fairwind, sirens, dusk_arrakis. Root cause of the Aug 9 Sirens loss documented in AGENTS.md gotcha 7.
- **Retention method exists.** `yt_analytics_pull.py --retention` gives 100-point curves (36 s each on a 1-hour video). Read: keepers (Dawn Over Arrakis, A Small Light in the Dark) hold 24-38% for the full hour; pullers (Temples, Calypso) lose 70-80% inside the first minute but recruit subs. Proposal built on it became Dusk Over Arrakis.
- **Fair Wind door fix, half done.** 1% CTR at 31% retention. New IP-first thumbnail is LIVE on the video (Cole: "swap it", 2026-09-12). The matching title change failed on scope; see In flight.
- **Channel avatar candidates** in `brand/out/avatar_*_v2.png` + `avatar_compare_sizes.png`. Recommended: `avatar_aperture_bold_v2.png`.
- **youtube_publisher SCOPES** now request `youtube.force-ssl` (73390bd); the stored token does not have it yet.

## Where things are

- Live public: Fair Wind Home (new thumbnail, old title), Dusk Over Arrakis.
- Private, dead, awaiting delete word: 1Eolx51Xr60, xpuDzlkZYRA.
- Local + R2: `output/release/{fairwind,sirens,dusk_arrakis}/`.
- fal balance ~ $25 (Cole's $30 top-up 2026-08-28 minus ~$4.80 across Fair Wind tests and Dusk).
- Grok image API: key blocked on xAI's side (403 "API key is currently blocked"). Stills now come from `fal-ai/flux-pro/v1.1-ultra`.
- Gemini: this project DOES call Gemini (audio_critic, motion_critic, theme_interpreter, reference_analyzer, orchestrator; rate-limited by gemini_limiter.py) on the single `GEMINI_API_KEY` in `.env`. That answers Chief's billing-notice question.

## In flight at retirement

- **Fair Wind retitle waiting on one click from Cole.** Target title: `The Odyssey | Fair Wind Home | 1 Hour Warm Ambient for Deep Work`. Blocked because `videos.update` needs `youtube.force-ssl` and `youtube_token.json` carries only upload+readonly. He was given the consent URL (from `POST /api/youtube/connect`, must be opened on the Mac since the callback is localhost:5050). **Successor: re-arm the watcher** — poll `youtube_token.json` for the string `youtube.force-ssl`, then `videos.update` with the new title and the existing description/tags/categoryId (the code is in the 2026-09-12 transcript; it is eight lines).
- **Dusk retention pull due 2026-09-18** (Chief's standing move): `yt_analytics_pull.py --retention`, then send chief-f1 the read against Dawn Over Arrakis and Temples: hold or bounce, the minute, subs gained. Nothing else publishes before then.
- **Avatar decision open.** Setting the channel avatar is an account setting: his word, then upload `brand/out/avatar_aperture_bold_v2.png` in Studio (or via API if he says do it).

## Open questions for Cole (one line each)

1. Approve the re-consent click so the Fair Wind title can change?
2. Set the bold aperture as the channel avatar?
3. Delete the two dead private uploads? (Chief holds this one.)

## Promised and not delivered

- The Fair Wind title swap (blocked on his click, above).
- Nothing else. The sietch-interior still (`output/release/dusk_arrakis/still_sietch_dusk.png`) is an unused candidate, not a promise.

## Notes

- Untracked and deliberately not committed: `inputs/`, `saved_stills/`, `brand/out/sting_silver.mp4`.
- Known dead R2 key `external/sirens_3h_v2.mp4` — leave it (AGENTS.md gotcha 7).
- Long jobs: launch as `( trap '' HUP; exec nohup <cmd> > <durable-log> 2>&1 < /dev/null ) & disown`, log under the project. A session restart kills plain nohup children and wipes the scratchpad.
