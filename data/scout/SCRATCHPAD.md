dry_streak: 0
stop: no

# Scout scratchpad (seeded 2026-11-03; last tick 2026-11-04, tick 2; trial ends 2026-11-17)

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
- Learned 2026-11-04: comment farms inflate year_pace. Hollow Knight fell from 0.73 to about 0.27
  once two farmed months were removed. Before believing any score above about 0.5, print its months
  and read the spike month. Farm signs: zero likes, generic praise, no mention of the subject.
- A floor score (year_pace_floor true, 1,000 threads read) is not comparable. Use reply-inclusive
  comments per day over the read window against lifetime per day instead.
- Uploads under about 2 years old can't show lasting yet. Newer uploads also take demand from older
  ones, so judge a world across uploads and years.
- Pinned old comments head page one of order=time. Don't stop paging on the first old comment.
- Comment world counts from tick 1 are regex over 2,909 comments, not hand-read. Treat as rough.
- Quota: search.list 100, comment pages 1, channels and videos.list 1. Tick 1 used about 900, tick 2
  about 780. To get a channel ID, use videos.list (1 unit), not search.
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
- Hollow Knight: about 0.27 after removing farmed months, other uploads 0.13 to 0.39. Silksong
  (2025-09-04) gave only a small lift, so that confound is closed.
- Zelda: 0.67 partly farmed, true value unmeasured. FFX: small, 0.08 to 0.91 on thin counts.
- Tenpers Universe and Everness use game tracklists, so they don't show demand for original music.
Worlds kankyo commenters name, distinct commenters / separate months: Minecraft 26/24, Nintendo or Wii
23/20, Zelda 18/17, Mario 13/13, Final Fantasy 5/5, Akira 4/4, Sims or SimCity 4/3 (last 2021), Yume
Nikki 3/2. Japan places (train stations, Kansai, Kyoto, Tokyo) 26/20.
Commissioned origins: Hosono's Watering a Flower (Muji flagship), Soundscape 1 (sold with a prefab
house), A.I.R. (Shiseido perfume), Nine Post Cards (Hara Museum).

## Ranked leads
1. Rest as the world, with no franchise. Quest & Rest (created 2025-03, 103k subs, 19.2M views) claims
   wholly original music, and its titles name only a state and a shelter: "Rest... Let the storm pass"
   (4.9M). Its comments gather people saying who they are and how tired they are. This is the one case
   so far of large demand not tied to game music. Is it one channel or a format? Who else does it, do
   older examples hold, and does the music matter or the rain? Too young to call lasting. Its second-
   person titles sit apart from the channel's current pipe-title packaging, which is Cole's call.
2. Skyrim-shaped game worlds with non-OST music. Does Ambient Worlds use original music on its Skyrim
   and Elder Scrolls pieces? If so, 0.84 could mean a world transfers without its soundtrack. Audit
   that 0.84 for farming and check Elder Scrolls 6 anticipation as a confound.
3. Real places as worlds: Japanese train stations and the commissioned-space origin (Muji, museum,
   prefab house). Hypothesis only. Hand-read the 26/20 regex hits first.
4. Wet Land's register: "calm, wet". Who else serves it, and why does it outlast Soundscape 1? Check
   more uploads. It now has an audit behind it.
5. Star Trek TNG engine-noise lineage: is "ship idling" a lasting format? Which ships or worlds besides
   TNG (Nostromo, Discovery One, Rocinante)?
6. Stars of the Lid listeners' adjacent records (Kranky label, A Winged Victory for the Sullen): any
   world-branded channel serving that register?
7. Kankyo listeners off YouTube (forums, blogs, Discogs lists). Still unread. Single mentions to watch
   for recurrence: Steve Roach Structures from Silence, Kerry Leimer Imposed Order, Hand of Umi Time
   Sand, August in the Water, Moomin music.

## Next actions
- Tick 3: lead 1. Run competitor_watch --discover on 2 or 3 queries ("fantasy rest rain ambient",
  "you can rest now ambient"). Find channels with this format and original music, favouring any at
  least 2 years old. Score their older uploads, reading the months as the Method section says.

## Deprioritized
- Super Mario Galaxy: 0.02 on the 3.2M upload, despite commenters naming Mario. One upload only.
- Mushishi: one commenter, OST at 0.13.
- Final Fantasy X: small on the uploads tested.
- Minecraft as a world for us: its demand looks tied to C418's music (inference, untested).
