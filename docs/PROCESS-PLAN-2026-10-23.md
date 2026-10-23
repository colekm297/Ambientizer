# Process plan, 2026-10-23 (after Penelope at the Loom)

Asked by Cole via Chief: "penelope at the loom is not doing great at all. 1.3% click through and 5:00 average watch time."

## What is broken

- Reach, not one video. Lifetime 3,968 views on 18 videos and 170 subscribers. 2,325 of those views (59%) were paid ads on Calypso and Temples. Organic discovery across the whole catalogue: 467 suggested, 403 browse, 110 search.
- Penelope's start was in fact our second best organic start (154 views in 6 days, 74 browse, 30 suggested). YouTube showed it. People did not click (1.3% CTR, below the 2-10% band YouTube says half of channels sit in) and the ones who clicked left early.
- The first minute broke. 28% were still there at 1:00, against 57% on Last Light on Arrakis. At these sample sizes that gap is about four times the noise band. Penelope is the first public video with the subscribe card at 0:07. Last Light had no card. The take is also 3 dB quieter than Last Light and opens on loom clicks.
- Average view 8.8% (5:15 of 60:00) sits mid-pack for our own clean 1-hour videos (6% to 27%). No public ambient benchmark exists. YouTube does not publish one, so Studio's relative retention is the honest comparison.

## What the niche does that we don't (YouTube API, 2026-10-23)

| Channel | Subs | Length | Gap between uploads | Title pattern |
|---|---|---|---|---|
| Ambient Worlds | 1.2M | 3 h | 21 days | IP + iconic place + "Peaceful Music & Ambience", "Human/Fan-Made" |
| Cinematic Focus | 62K | 1 h | 13 days | "You Are Solving the Impossible \| Interstellar Soundtrack" |
| 3791 Ambience | 57K | 3.2 h | 16 days | "The Lord of the Rings: A Peaceful Night On The Borders Of The Shire" |
| Ambient Cinematics | 195K | 8 h | 7 days | "Relax With Batman \| Gotham City Music & Ambience" |

- They name an iconic place everyone knows (the Shire, Hogwarts, Rivendell). We name a deep-cut scene (Penelope's loom, Frodo sailing west).
- Their titles promise a use or feeling: peaceful, focus, sleep. Ours promise a scene.
- Their thumbnails are bright with centered text in the IP's own look, or a face mid-task. Ours are dark, the figure is small and the text sits at the bottom in a generic block face.
- Cinematic Focus broke out at its eighth upload during a run of five uploads in 25 days (Interstellar, 5.9M views). We have shipped 9 long videos in 6.5 months with month-long gaps.
- Structural gap: the big channels play the actual film score (Cinematic Focus) or sell "Human-made" (Ambient Worlds). We play originals labelled as AI-assisted under an IP title. Some of the 1-minute drop may be people who expected the score.

## Three experiments, ranked by expected impact

1. **Package to the niche's proven pattern.** Change: iconic place plus promise in the title, for example "The Odyssey | Night in the Palace of Ithaca | Peaceful Music & Ambience". Brighter thumbnail with centered big text. Measure: Studio Test & compare on Penelope and Last Light now (it scores by watch-time share), then CTR and browse views on the next two releases against Penelope's 1.3%. Sample: Test & compare reports its own confidence. For CTR, a jump from 1.3% to 3% is readable after about 2,000 impressions. Cost: $0, new thumbnails only.
2. **Fix the first minute.** Change: no subscribe card at 0:07 (move it to 5:00 or drop it), no sting, open at full level on the take's most inviting moment. Measure: 1-minute retention on the next two releases against Penelope's 0.28 and Last Light's 0.57. Sample: about 120 viewers per video gives ±0.08, so a 0.15 move is readable after two releases. Cost: $0, a build-script change.
3. **A short streak in one IP.** Change: four releases in four weeks in one world with known places (Dune or Middle-earth), and at least one at 3 hours. Measure: suggested plus browse views per video per week, and whether each release lifts the others' suggested traffic. Sample: four videos is a trend read, not a test. Cost: about $3 in visuals per video, and Cole's ears picking four takes. Cadence is Cole's call. This needs his yes.
