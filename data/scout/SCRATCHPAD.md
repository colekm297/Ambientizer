dry_streak: 0
stop: no

# Scout scratchpad (seeded 2026-11-03; last tick 2026-11-05, tick 3; trial ends 2026-11-17)

## Objective
Find worlds, sounds and reference records with lasting listener demand that The Space of Sound could
serve. Prefer rare, specific leads over consensus.

## Seeds (what good looks like)
- Cole's touchstones: Brian Eno (Music for Airports, Apollo), Stars of the Lid (The Tired Sounds of...,
  And Their Refinement of the Decline), Hiroshi Yoshimura (Music for Nine Postcards).
- Sound Cole rated top: Empyreal's 3SnFFdHVvdo (warm, slow, world-branded).
- Competitor year_pace, re-scored 2026-11-03, NOT farm-audited: Ambient Worlds "Peaceful Night in
  Skyrim" 0.84, "Night in The Shire" 0.60, Symbology "Aragorn's Song" 0.40, Interstellar pair 0.31
  and 0.28, Ambient Cinematics "Most Peaceful DUNE Music" 0.17, Finding Nemo 0.20.
- HackerTube's lasting ambient picks: "Star Trek TNG Ambient Engine Noise (24 hrs)" (recommended in
  4 separate months), Reich's Music for 18 Musicians, The Caretaker's Everywhere at the End of Time.

## Method
- year_pace = comments in the last 365 days (replies included) / lifetime yearly pace.
- Comment farms inflate year_pace (Hollow Knight fell from 0.73 to about 0.27). Before believing any
  score above about 0.5, print its months and read the spike month. Farm signs: zero likes, generic
  praise, no mention of the subject.
- A floor score (year_pace_floor true, or my 12-page cap hit) is not comparable. Use reply-inclusive
  comments per day over the read window against lifetime per day instead.
- Uploads under about 2 years old can't show lasting yet. Newer uploads also take demand from older
  ones, so judge a world across uploads and years.
- Top uploads from channel_uploads(yt, id, 100) cover only the newest 100. Walk the whole catalogue
  (max_videos 500) on larger channels, or the real hits are missed. Tick 3 nearly missed all of them.
- Pinned old comments head page one of order=time. Don't stop paging on the first old comment.
- Comment world counts from tick 1 are regex over 2,909 comments, not hand-read. Treat as rough.
- Quota: search.list 100, comment pages 1, channels and videos.list 1. Ticks 1 to 3 used about 900,
  780, 530. To get a channel ID, use videos.list (1 unit), not search. search.list with
  publishedBefore finds older examples of a format.
- Reddit: search didn't surface threads and WebFetch is refused on reddit.com. Try other forums, blogs
  or a search phrased around thread titles before calling it closed.
- Set PYTHONDONTWRITEBYTECODE=1 when importing competitor_watch, to keep writes inside data/scout/.

## Known (already ours or already checked)
Ours: Dune, The Odyssey, Project Hail Mary, Interstellar, LOTR. Blade Runner: SpaceWave owns it.
References, audited 2026-11-04:
- Wet Land (Yoshimura, 1993) 0.79, 5.1M views, reads real. Green (1986) 0.90 and 0.13 by upload, the
  0.90 reads real. Soundscape 1 0.11 on the 2.0M upload. Oasis of the Wind (Kokubo) 0.29, 1.5M views.
Game worlds, checked 2026-11-04. Nearly all of this demand sits on the original game music:
- Skyrim: lasting. Everness 0.45, 0.45, 0.28, 0.16 on 14M to 26M views. Night 10h reads real and steady.
- Minecraft: huge, but older uploads fade (0.05 to 0.23) as new ones take over. Drift Away Ambience
  (299k subs, created 2024-01) leads with C418's music. Comments are about childhood and loss.
- Hollow Knight: about 0.27 after removing farmed months, other uploads 0.13 to 0.39. Silksong gave
  only a small lift, so that confound is closed.
- Zelda: 0.67 partly farmed, true value unmeasured. FFX: small, 0.08 to 0.91 on thin counts.
- Tenpers Universe and Everness use game tracklists, so they don't show demand for original music.
Rest format ("rest, traveler, you're safe"), checked 2026-11-05. It is real, it is large, and single
uploads fade. Demand moves to the newest upload, as with Minecraft:
- Chill Cartoon Vibes (2024-03, 364k subs, 48.0M views): 6.6M at 0.24, 3.4M at 0.11, 2.2M at 0.05.
- spiritual brother (2023-08, 91.6k subs, claims original music, one-hour videos): "i must rest here
  a moment" 6.4M at 0.16. One hit, median 9,515.
- Quest & Rest (2025-03, 103k subs): 3.45M upload, 0.67 is a capped floor, too young. Threads fell
  from 269 (2026-02) to 51 (2026-10).
- Older uploads, 2022 to 2023: Hueniverse 3.3M at 0.03, nobody 2.6M at 0.08, aTolphas 1.0M at 0.04.
  Commenters call the last two Skyrim music. Three uploads from one search, not a survey.
- Chill Cartoon and Quest & Rest use near-identical channel text, so they may not be independent.
- New entrants still arriving: bluehour (2026-08, 718k on one video, views not audited), alone again
  (2026-10). The comments across all of them are people saying they are tired or alone. That
  gathering is the most distinctive thing about this format, and year_pace doesn't measure it.
- Open: does the music matter or the rain? Not answered. Compare with Wet Land at 0.79, which has
  held at that scale with no title speaking to the listener.
Worlds kankyo commenters name, distinct commenters / separate months: Minecraft 26/24, Nintendo or Wii
23/20, Zelda 18/17, Mario 13/13, Final Fantasy 5/5, Akira 4/4, Sims or SimCity 4/3 (last 2021), Yume
Nikki 3/2. Japan places (train stations, Kansai, Kyoto, Tokyo) 26/20.
Commissioned origins: Hosono's Watering a Flower (Muji flagship), Soundscape 1 (sold with a prefab
house), A.I.R. (Shiseido perfume), Nine Post Cards (Hara Museum).

## Ranked leads
1. Named worlds carried by a channel's own music. This is the question that decides whether a world
   transfers without its soundtrack. Two cases surfaced 2026-11-05:
   - klr, "silent hill inspired ambient music" (credits music to klr): 1.12M at 0.40 on 351 comments,
     other uploads 486k and 348k unscored. Check release confounds (remake and new game dates).
   - Athena IV (says all original): Ancient Egypt 3.5M and 3.1M, Japanese Zen 2.4M and 1.8M, Aero
     733k and 708k (under a year old), TRON-inspired 507k. None scored yet.
2. Skyrim-shaped game worlds with non-OST music. Does Ambient Worlds use original music on its Skyrim
   and Elder Scrolls pieces? If so, 0.84 could mean a world transfers without its soundtrack. Audit
   that 0.84 for farming and check Elder Scrolls 6 anticipation as a confound.
3. Real places as worlds: Japanese train stations and the commissioned-space origin (Muji, museum,
   prefab house). Hypothesis only. Hand-read the 26/20 regex hits first. Ancient Egypt in lead 1 may
   bear on this.
4. Wet Land's register: "calm, wet". Who else serves it, and why does it outlast Soundscape 1? Check
   more uploads. It now has an audit behind it.
5. Star Trek TNG engine-noise lineage: is "ship idling" a lasting format? Which ships or worlds besides
   TNG (Nostromo, Discovery One, Rocinante)?
6. Stars of the Lid listeners' adjacent records (Kranky label, A Winged Victory for the Sullen): any
   world-branded channel serving that register?
7. Kankyo listeners off YouTube (forums, blogs, Discogs lists). Still unread. Single mentions to watch
   for recurrence: Steve Roach Structures from Silence, Kerry Leimer Imposed Order, Hand of Umi Time
   Sand, August in the Water, Moomin music.
8. Rest format, what's left: catalogue-level demand rather than per upload (total comments a month
   across Chill Cartoon's whole catalogue over time). Only worth it if the format is of interest.

## Next actions
- Tick 4: lead 1. Score Athena IV's two Egypt and two Zen uploads and klr's next two Silent Hill
  uploads, printing months. Search the Silent Hill 2 remake and Silent Hill f release dates as a
  confound. Run --discover on "ancient egypt ambient" to see whether anyone else holds that world.

## Deprioritized
- Super Mario Galaxy: 0.02 on the 3.2M upload, despite commenters naming Mario. One upload only.
- Mushishi: one commenter, OST at 0.13.
- Final Fantasy X: small on the uploads tested.
- Minecraft as a world for us: its demand looks tied to C418's music (inference, untested).
- Rest format as a lasting bet on the per-upload test: 0.03 to 0.24 on all 7 rest-titled uploads aged 21 months or more (klr, 0.40, is in lead 1).
  Its second-person titles also sit apart from the channel's pipe-title packaging, which is Cole's call.
