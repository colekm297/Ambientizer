> SNAPSHOT as of 2026-11-04 02:26 PST. Anything newer (git commits, file mtimes, your own conversation) outranks this file. Verify before acting.

# Thread tail: open with this

**First thing: Cole has NOT seen the thinking-run results.** Deliver this "While you were out" note to him (rewrite it in a conversational voice, no em-dashes). Source: `.claude/thinking/2026-11-03-2240.md` (synthesis + checker results near the end). The run went from 22:40:25 to about 23:04, so about 24 minutes, not 45.
1. **AI-music disclosure is required and isn't set.** YouTube Help requires it when AI "creates music that's the main focus of the video". The upload code never sets `status.containsSyntheticMedia`. Fix: one field in the upload code, plus a Studio pass on the 13 public long-form videos. Cole decides.
2. **The Odyssey is the series world.** Underserved: 10 competitor videos, 7 above their channel's norm, median 2.0x (Dune is 0.86x across 30). We have 4 Odyssey pieces. Nolan's film hits digital and 4K on **Nov 17, 2026** (two checkers PASS) and has grossed about $1.8B (checker-corrected). Order: disclosure, then a public playlist and retitles (searchable words, never "OST"), then new pieces from his draft picks.
3. **Identity gap.** Fewer than one view per subscriber in 5 months (SUBSCRIBED 154 views vs UNSUBSCRIBED 3,661). Zero public playlists. The biggest suggester is Zimmer's "Interstellar (Space Sounds)" (49 views).
4. **The human-made line.** Competitors sell "Human-made" and "handcrafted". Idea: a Juno or guitar bed Cole plays, tried on one piece, only if he wants.
5. **An 8-week bet with a kill line:** views per subscriber per month from 0.18 to 0.5, or one piece past 500 organic views in 30 days.
Smaller: feed his packaging rules into draft metadata (the 11-03 draft title says "Sietch", a lore word he banned). Enable the YouTube Reporting API for project 247866141133 (403 now). The 24/7 stream (distribute_stream.py) has never been used. Fresh-eyes agents saw what I'd missed: 59% of lifetime views were paid, and the genre rewards sameness (habit) over novelty.
Also tell him: the 11-03 draft "Dune | Ember-Lit Ritual in the Hidden Sietch" is private at https://www.youtube.com/watch?v=QtzjbUNs5lI (playlist "Drafts to review").

**Live systems (built 11-03, all committed):**
- `drafts_daily.py`, launchd `com.cole.ambientizer-drafts` at 10:00: one take a day becomes a private 1-hour video. Cole publishes or deletes; never do either for him. See memory project-daily-private-drafts.
- Scout trial: `scout_tick.sh`, launchd `com.cole.ambientizer-scout` at 08:30, ends itself by Nov 17 or after 3 dry ticks. Data in `data/scout/`.
- `competitor_watch.py --recurrence` (year_pace).
- SFX now on ElevenLabs v3 (`sample_generator.SFX_MODEL`); v2 is removed 2027-03-01.

**Waiting on Cole (bring through Chief, don't do without him):** the disclosure flag, the Odyssey playlist and retitles before Nov 17, the human bed, enabling the Reporting API, the packaging rules in draft metadata.

**2026-11-06 AI label backfill (Cole's tap on inbox item 9):** Studio's altered-content radio, read today, says Yes on 8 of 13: written by `_disclose_public.py` Spacecraft, Arrakis Desert Rain, Escher, Sanctuary, A Small Light, Temples; already Yes without a write, Sirens and Penelope. Blank: Two Minds, Dawn, Calypso, Going Home, Last Light. Writing Temples (tg1Ixcm_-6k) changed snippet.defaultAudioLanguage; it now reads en, the old value wasn't recorded, not restored. Run stopped there. The other 5 wait on his inbox tap; write them one at a time with `--write --only ID`, never bare `--write`, which would also hit Sirens and Penelope. The public "Made with AI" section also appears on videos Studio shows blank and on all 5 Shorts, so Studio's radio is the proof of a declaration, not the public page.

## 2026-11-06 17:51 PT: inbox 41, 42, 43 done (Cole's taps, read with `ask show`)
- AI label: Studio radio Yes on all 13 (read back on the 5 written today). Audio language changed from unset to `en` on Two Minds, Dawn, Calypso; unchanged on Going Home and Last Light (en-US). Before-state: `data/items_41_42_before.json`. Log: `data/disclose_public.jsonl`.
- Titles: A Small Light and Dawn changed, public pages read back. Only title fields changed. Log: `data/title_changes.jsonl`.
- Reporting API on for project 247866141133. One job, `channel_reach_basic_a1`, id f8986e22-8ca8-44d2-9637-0edab3a1bf96, created with `yt_analytics_token.json`. Nothing downloads its reports yet: `post_learning` has to read them next.
- Chrome account was not switched.

## 2026-11-07 06:30 PT: current state, checked against the API, launchd and Studio (answer test)
This replaces older lines below or above it where they differ, including "other 5 wait" and "nothing downloads".
- Public 19: 14 long-form, 5 Shorts. Newest QtzjbUNs5lI, "Dune | Ember-Lit Ritual in the Hidden Sietch | 1 Hour Desert Ambient".
- Private 5: drafts YyaOKVjFs8s (Rain Over Arrakis), U4S-hZzRBZA (Inception, Folding City), MR8ulRDFyHE (Dusk on a Hidden Island); held 2dElNNIY91w (Hail Mary), GsNmBR0BGF0 (Frodo). The Drafts playlist also still holds public Sietch.
- Titles changed 11-06: frJb60y4d5M "Project Hail Mary | A Small Light in the Dark | 1 Hour Space Ambient"; kg-RRBuGsuQ "Dune | Dawn Over Arrakis | 1 Hour Desert Ambient Music".
- Label: Studio Yes on the 13 and Sietch. The 5 Shorts were not declared by us; item 9 excluded them.
- Reach: `reach_reports.py` runs from Monday's pull; no report has arrived; first check after 2026-11-09 08:00.
- Open inbox for this project: 36 (Odyssey playlist and Sirens retitle, Chief relays), 48 (traffic-source report job).
- Schedulers: drafts 10:00, daily experiment 07:30 (running, 24 GB floor, see below), scout 08:30, post-learning Mon 08:00. Stock-burn was a one-time Nov 4 calendar job.
- Generation is not on hold. Cole's 10-28 "hold on more generation please" (Finance chat, beside backing up to his external drive) was about disk; Chief reads it as superseded by 10-29 "Can we continue or are we quickly going to run out of memory again?" and 10-30 "Are we still cranking?" Chief told Cole on 11-07; stopping the daily job is his call.
- Work lives on `living-still-harden`, which is 113 commits ahead of `main`, although CLAUDE.md and AGENTS rule 5 say main. Unreconciled; ask Chief before merging.
