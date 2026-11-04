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
