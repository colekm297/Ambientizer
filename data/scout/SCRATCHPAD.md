dry_streak: 0
stop: no

# Scout scratchpad (seeded 2026-11-03; last tick 2026-11-03; trial ends 2026-11-17)

## Objective
Find worlds, sounds and reference records with lasting listener demand that The Space of Sound could
serve. Prefer rare, specific leads over consensus.

## Seeds (what good looks like)
- Cole's touchstones: Brian Eno (Music for Airports, Apollo), Stars of the Lid (The Tired Sounds of...,
  And Their Refinement of the Decline), Hiroshi Yoshimura (Music for Nine Postcards).
- Sound Cole rated top: Empyreal's 3SnFFdHVvdo (warm, slow, world-branded).
- Lasting competitor videos, re-scored 2026-11-03 with year_pace (competitor_watch --recurrence now
  uses it): Ambient Worlds "Peaceful Night in Skyrim" 0.84, "Night in The Shire" 0.60, Symbology
  "Aragorn's Song" 0.40, Interstellar pair 0.31 and 0.28, Ambient Cinematics "Most Peaceful DUNE
  Music" 0.17 (faded), Finding Nemo 0.20.
- HackerTube's lasting ambient picks: "Star Trek TNG Ambient Engine Noise (24 hrs)" (recommended in
  4 separate months), Reich's Music for 18 Musicians, The Caretaker's Everywhere at the End of Time.

## Method (learned 2026-11-03)
- still_alive was wrong (it read ~0.6 by construction, or hid fades); the tick-1 flag was right.
  competitor_watch.py now computes year_pace = comments in the last 365 days (replies included) /
  lifetime yearly pace, and skips past a pinned old comment heading page one. Fixed 2026-11-03.
- Judge a record across uploads: Green reads 0.90 on one upload and 0.13 on another.
- Comment world counts are regex over 2,909 top-level comments, not hand-read. Treat as rough.
- Quota: search.list costs 100; comment pages cost 1. Budget 7 searches a tick at most. Tick 1 used
  about 900 of 1,000.
- Reddit: search didn't surface threads and WebFetch is refused on reddit.com. Try other forums, blogs
  or a search phrased around thread titles before calling it closed.

## Known (already ours or already checked)
Ours: Dune, The Odyssey, Project Hail Mary, Interstellar, LOTR. Blade Runner: SpaceWave owns it.
year_pace, checked 2026-11-03:
- Wet Land (Yoshimura, 1993) 0.79, 5.1M views. Most-viewed of the 12 kankyo uploads tested, not on the seed list.
- Green (Yoshimura, 1986) 0.90 and 0.13 by upload.
- Soundscape 1 (Yoshimura) 0.11 on the 2.0M upload. Oasis of the Wind (Kokubo) 0.29, 1.5M views.
- Relaxing Zelda + campfire 0.67, 12.4M views. Hollow Knight + rain 0.70, 5.9M views (sequel confound
  not checked).
- Relaxing Nintendo: Donkey Kong Country 0.44, "2000s nostalgic nintendo" 0.20, Luigi's 75 minutes
  0.19.
Worlds kankyo commenters name, by distinct commenters / separate months: Minecraft 26/24, Nintendo or
Wii 23/20, Zelda 18/17, Mario 13/13, Final Fantasy 5/5, Akira 4/4, Sims or SimCity 4/3 (last seen
2021), Yume Nikki 3/2. Japan places (train stations, Kansai, Kyoto, Tokyo) 26/20.
Commissioned origins: Hosono's Watering a Flower (Muji flagship), Soundscape 1 (sold with a prefab
house), A.I.R. (Shiseido perfume), Nine Post Cards (Hara Museum).

## Ranked leads
1. Calm game worlds: kankyo listeners keep hearing games in this music, and Zelda and Hollow Knight
   hold pace while Mario Galaxy doesn't. Test Minecraft (most named, untested), Skyrim, Final Fantasy
   X's Besaid, Hollow Knight's sequel confound. Which world has demand but no warm, slow channel? The
   titles seen so far look like game OST plus rain or campfire; unverified, so check who makes them.
2. Real places as worlds: Japanese train stations and the commissioned-space origin (Muji, museum,
   prefab house). Hypothesis only. Does anyone search for or return to this, or is it just commenters'
   memories? 26/20 is a noisy regex, so hand-read it first.
3. Wet Land's register: "calm, wet". Who else serves it, and why does it outlast Soundscape 1? Check
   more uploads before believing the gap.
4. Star Trek TNG engine-noise lineage: is "ship idling" a lasting format? Which ships or worlds besides
   TNG (Nostromo, Discovery One, Rocinante)?
5. Stars of the Lid listeners' adjacent records (Kranky label, A Winged Victory for the Sullen): any
   world-branded channel serving that register?
6. Kankyo listeners off YouTube (forums, blogs, Discogs lists). Still unread. Single mentions to watch
   for recurrence: Steve Roach Structures from Silence, Kerry Leimer Imposed Order, Hand of Umi Time
   Sand, August in the Water, Moomin music.

## Next actions
- Tick 2: lead 1. Score Minecraft, Skyrim and FFX calm uploads with year_pace across at least 2 uploads
  each, and note who makes them (OST rips or original music). Check the Hollow Knight confound with one
  search.

## Deprioritized
- Super Mario Galaxy: 0.02 on the 3.2M upload, despite commenters naming Mario. One upload only.
- Mushishi: one commenter, OST at 0.13.
