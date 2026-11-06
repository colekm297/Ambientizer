dry_streak: 0
stop: no

# Scout scratchpad (seeded 2026-11-03; last tick 2026-11-06, tick 4; trial ends 2026-11-17)

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
- Quota: search.list 100, comment pages 1, channels and videos.list 1. Ticks 1 to 4 used about 900, 780,
  530, 180. Get channel IDs from videos.list, not search. publishedBefore finds older examples.
- Reddit: search finds no threads, WebFetch refused. godisageek.com also returned 403.
- Set PYTHONDONTWRITEBYTECODE=1 when importing competitor_watch, to keep writes inside data/scout/.
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
Worlds kankyo commenters name, distinct commenters / months: Minecraft 26/24, Nintendo or Wii 23/20,
Zelda 18/17, Mario 13/13, Final Fantasy 5/5, Akira 4/4, Sims 4/3, Yume Nikki 3/2. Japan places 26/20.
Commissioned origins: Watering a Flower (Muji), Soundscape 1 (prefab house), A.I.R. (Shiseido), Nine Post
Cards (Hara Museum).

## Ranked leads
1. Franchise worlds on non-OST music, still the deciding question, since Egypt is a place. Does Ambient
   Worlds use original music on Skyrim and Elder Scrolls? If so, 0.84 could mean a franchise transfers
   without its soundtrack. Audit that 0.84 and check Elder Scrolls 6 anticipation as a confound.
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
- Tick 5: lead 1. Print months and read the spike on Ambient Worlds' "Peaceful Night in Skyrim" and "Night
  in The Shire", read the descriptions and comments for whose music it is, walk its catalogue for other
  Elder Scrolls uploads, and search the Elder Scrolls 6 news dates as a confound.

## Deprioritized
- Silent Hill as a lasting world: one upload of six above 0.23.
- Super Mario Galaxy: 0.02 on 3.2M. Mushishi: one commenter. Final Fantasy X: small.
- Minecraft for us: demand looks tied to C418's music (inference, untested).
- Rest format on the per-upload test. Its second-person titles also sit apart from the channel's pipe-title
  packaging, which is Cole's call.
