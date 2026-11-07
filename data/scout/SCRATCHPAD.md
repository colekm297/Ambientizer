dry_streak: 0
stop: no

# Scout scratchpad (seeded 2026-11-03; last tick 2026-11-07, tick 5; trial ends 2026-11-17)

## Objective
Find worlds, sounds and reference records with lasting listener demand that The Space of Sound could
serve. Prefer rare, specific leads over consensus.

## Seeds (what good looks like)
- Cole's touchstones: Eno (Music for Airports, Apollo), Stars of the Lid, Yoshimura (Nine Postcards).
- Sound Cole rated top: Empyreal's 3SnFFdHVvdo (warm, slow, world-branded).
- Competitor year_pace, re-scored 2026-11-03, NOT farm-audited: Ambient Worlds "Peaceful Night in
  Skyrim" 0.84, "Night in The Shire" 0.60, Symbology "Aragorn's Song" 0.40, Interstellar pair 0.31
  and 0.28, Ambient Cinematics "Most Peaceful DUNE Music" 0.17, Finding Nemo 0.20.
- HackerTube's lasting ambient picks: "Star Trek TNG Ambient Engine Noise (24 hrs)", Reich's Music for
  18 Musicians, The Caretaker's Everywhere at the End of Time.

## Method
- year_pace = comments in the last 365 days (replies included) / lifetime yearly pace.
- Comment farms inflate it (Hollow Knight 0.73 fell to about 0.27). Before believing a score above about
  0.5, print its months and read the spike month. Farm signs: zero likes, generic praise, off subject.
- recurrence() returns year_pace_clean and farm_months (months of 20+ threads, 90%+ with no like and no
  reply are dropped). It misses thin spread-out farming (Zelda's 0.47). Keep reading text on high scores.
- A floor score (year_pace_floor, or a page cap hit) isn't comparable. Use comments per day instead.
- Uploads under about 2 years can't show lasting. Scores aren't age-matched: compare within a set.
- Judge a world across uploads and by catalogue year. A channel's view medians fall by upload year from
  age alone, so compare a world's yearly median against the whole channel's for that year.
- channel_uploads(yt, id, 500) walks the whole catalogue. The newest 100 misses the real hits.
- Pinned old comments head page one of order=time. Don't stop paging on the first old comment.
- Tick 1 world counts are regex over 2,909 comments, not hand-read. Treat as rough.
- Quota: search.list 100, comment pages 1, channels and videos.list 1. Ticks 1 to 5 used about 900, 780,
  530, 180, 270. Get channel IDs from videos.list, not search. publishedBefore finds older examples.
- Reddit: search finds no threads, WebFetch refused. godisageek.com also returned 403.
- Set PYTHONDONTWRITEBYTECODE=1 when importing competitor_watch, to keep writes inside data/scout/.
- Year_pace on one upload understates a world that gets remade (Shire). Use views over the channel's
  median for that upload year as well, and read the music credit before reading any score.
- --discover on a topic word returns documentaries. Add a format word, and don't read an empty result as
  an open niche.

## Known (already ours or already checked)
Ours: Dune, The Odyssey, Project Hail Mary, Interstellar, LOTR. Blade Runner: SpaceWave owns it.
References, audited 2026-11-04:
- Wet Land (Yoshimura, 1993) 0.79, 5.1M, reads real. Green 0.90 and 0.13 by upload, the 0.90 reads real.
  Soundscape 1 0.11 on 2.0M. Oasis of the Wind (Kokubo) 0.29, 1.5M.
Game worlds, checked 2026-11-04. Nearly all this demand sits on the original game music:
- Skyrim: lasting. Everness 0.45, 0.45, 0.28, 0.16 on 14M to 26M views. Night 10h reads real and steady.
- Minecraft: huge, older uploads fade (0.05 to 0.23). Drift Away Ambience leads with C418's music.
- Hollow Knight about 0.27 cleaned, others 0.13 to 0.39, Silksong lift small. Zelda 0.67 partly farmed.
  FFX small. Tenpers Universe and Everness use game tracklists, so they don't show original music demand.
Rest format, checked 2026-11-05. Real, large, single uploads fade (0.03 to 0.24 on 7 uploads at 21+
months), demand moves to the newest: Chill Cartoon Vibes, spiritual brother, Quest & Rest (0.67 floor,
too young), Hueniverse, nobody, aTolphas. Comments are tired, lonely people talking to each other, which
year_pace doesn't measure. Open: does the music matter, or the rain?
Worlds on claimed-original music, checked 2026-11-06 (Athena IV, 324k subs; klr, 13.6k subs):
- Ancient Egypt: Valley of Time 0.45 (3.5M), Winds of Time 0.39 (3.1M), The Nile 0.13 (1.0M). Winds is
  the clean case. Valley has a cat-comment shift, 2% of threads to 15% from 2025-11, with one commenter
  describing a Japanese meme I couldn't confirm. Yearly medians match the channel from 2025, so the top two
  are outliers. No other ambient holder found on one poor query. "Original" is unverified.
- Japanese Zen: 0.42, 0.28, 0.05, 0.04. Mixed. Athena's last Japan-tagged upload is 2026-03-11.
- Silent Hill (klr): 0.40, 0.23, 0.23, 0.14, 0.05, 0.03. The 0.40 was the best of six. Thread lift after
  SH2 remake (2024-10-08), f (2025-09-25), Townfall (2026-09-24) looks small on thin counts. Dropped from
  lead 1. Recent comments on the top upload are lost and tired people, as in the rest format.
- Athena's other: Forgotten Gods 0.26 (4.0M), Dead Gods 0.14 (3.8M), Future セルフ cyberpunk 0.29 (3.0M),
  rest a while, user (TRON) 0.21 (752k). Aero uploads under a year, unscored.
- Odyssean Sea (ours-adjacent): 216,774 views, under Athena's Circe and Greece 323 BC. One upload.
Ambient Worlds audited 2026-11-07 (1.2M subs, 220 long uploads). Read the music credit first:
- Skyrim 0.84 is the soundtrack (Soule, ESO), 559 days old, real, steady 15 to 34 threads a month. Older
  Skyrim uploads 0.21 and 0.14, so mostly youth. Shows nothing about transfer without a soundtrack.
- Night in The Shire 0.60 is human-made covers of Shore and Enya, 474 days old. Shire over year median:
  5.43x and 5.13x on 2018-19 uploads, then 8.61x, 5.88x, 7.68x (2025) and 4.74x (2026) on covers. The
  premium survived a change of recordings. The melodies stayed. Lasting at world level: old Shire uploads
  are 0.09 and 0.02, demand moved to new versions.
- Removing music: ambience-only Skyrim on its second channel 2,709 vs 2,509,011 (926x, subs differ 26x).
  Second pair 1,221 vs 138,504 is unclear on contents. Confounded, but large.
- Removing the franchise: Spirit of Fall 0.35x, nature pieces 0.08x and 0.10x (those drop music too).
- 2026 medians, ages uneven: LOTR 283,263 (7), Harry Potter 131,378 (4), channel 170,828 (16). It sells
  "Human Made" and "No AI" in titles and credits. Covers' licensing not established.
- Credits read on 2025-07 onward only: none states theme-free music. Hocus Pocus and Disney parks are
  unclear. Older uploads unread, so the test case wasn't found, not ruled out.
Elder Scrolls VI: Sentinel, reported revealed 2026-11-03, Hammerfell, desert teaser, no date. Event only.
Worlds kankyo commenters name, distinct commenters / months: Minecraft 26/24, Nintendo or Wii 23/20,
Zelda 18/17, Mario 13/13, Final Fantasy 5/5, Akira 4/4, Sims 4/3, Yume Nikki 3/2. Japan places 26/20.
Commissioned origins: Watering a Flower (Muji), Soundscape 1 (prefab house), A.I.R. (Shiseido), Nine Post
Cards (Hara Museum).

## Ranked leads
1. Franchise worlds on theme-free music, narrowed 2026-11-07. Ambient Worlds' recent credits don't answer
   it, they name themes or say too little. Who does a franchise with no themes? Read credits and score Ambient
   Cinematics "Most Peaceful DUNE Music" (0.17), Symbology "Aragorn's Song" (0.40), Empyreal 3SnFFdHVvdo,
   Obsidian Soundfields, Bjorth. These are our closest neighbours, and the answer sets what our music can
   carry. If they all use themes, that's a finding about our own position.
2. Reading and writing as the use: Circe (Madeline Miller), Ancient Greece. Athena's Circe 752,819 at
   0.24, too young; "while I read Circe", "while writing my book", "Reading some Aristotle". Four comments,
   a hint. Who plays music to novels, and which books recur? Song of Achilles and other novels are
   untested guesses. Sits next to our Odyssey.
3. Place-worlds beyond one channel: is Egypt more than Athena IV? Retry discover with a format word
   ("ancient egyptian music relaxing"), and try Rome, Persia, Mesopotamia. Athena's Atlantis (Princess of
   Atlantis 1.5M) is unscored. Real places (Japanese stations, Muji) also belong here: hand-read 26/20.
4. Wet Land's register: "calm, wet". Who else serves it, why does it outlast Soundscape 1?
5. Star Trek TNG engine-noise lineage: is "ship idling" lasting? Nostromo, Discovery One, Rocinante?
6. Stars of the Lid adjacents (Kranky, A Winged Victory for the Sullen): any world-branded channel?
7. Kankyo listeners off YouTube (forums, blogs, Discogs). Unread. Watch for: Steve Roach Structures from
   Silence, Kerry Leimer Imposed Order, Hand of Umi Time Sand, August in the Water, Moomin music.
8. Rest format, catalogue-level demand across Chill Cartoon's catalogue. Only if the format is of interest.

## Next actions
- Tick 6: lead 1. Get video IDs from COMPETITORS in competitor_watch.py via channel_uploads, no search. For
  each franchise piece above, read the music credit, score it, and compare views to that channel's year
  median. Sort them into soundtrack, covers, and theme-free. Listening isn't possible here, so credits
  and comments are the evidence; say so where a credit is missing.

## Deprioritized
- Silent Hill as a lasting world: one upload of six above 0.23.
- Super Mario Galaxy: 0.02 on 3.2M. Mushishi: one commenter. Final Fantasy X: small.
- Minecraft for us: demand looks tied to C418's music (inference, untested).
- Skyrim as a test of transfer: it's soundtrack demand. Hammerfell has no evidence yet.
- Rest format on the per-upload test. Its second-person titles also sit apart from the channel's pipe-title
  packaging, which is Cole's call.
