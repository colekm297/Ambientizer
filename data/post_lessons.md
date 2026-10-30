LESSONS (updated 2026-10-26)

# Lessons file: The Space of Sound (non-music half)

Updated 2026-10-26, from the pull at 2026-10-26 08:00. The last logged file was 2026-10-19 08:00, exactly 7 days earlier. This file replaces the 2026-10-19 version.

**Data used:**
- 13 of the channel's 18 public videos, plus 1 private upload.
- 13 videos have outcomes. I1EbGRaQumk has analytics for the first time. GsNmBR0BGF0 is still private.
- Tracked analytics cover 3,632 of the channel's 3,982 views. The other 350 are on the 5 untracked videos or still in analytics lag, which runs about 2 to 3 days behind the public counter.

**Glossary:**
- "Browse" means the API's SUBSCRIBER source (home feed and subscriptions feed).
- "Suggested" means RELATED_VIDEO.
- "Discovery" means browse plus suggested.
- Times are PT. Until 31 October it is PDT (UTC minus 7). DST ends 1 November 2026, and PST is UTC minus 8.

**Noise rule:** by chance, a retention share at n viewers moves by about ±2×√(p(1−p)/n).

| Viewers | Band |
|---|---|
| 225 | about ±0.07 |
| 160 | about ±0.07 to ±0.08 |
| 110 | about ±0.09 |
| 50 | about ±0.13 |

- To compare two videos, add their variances.
- Retention audiences are not exactly equal to views, so all bands are approximate.

**Changes from the 2026-10-19 file:**
- **I1EbGRaQumk's first week is in:** 161 views, 142 of them discovery, and r_1min 0.311.
  - Lesson 6's pre-registered prediction (r_1min 0.23 to 0.39) held.
  - Lessons 2, 4, 5, 6, 7, 10 and 12 are updated with it.
- **The `views_since_last_pull` field does not match the 10-19 file.** I computed 7-day changes from totals instead.
  - wHOZ8ppszSI: totals show +3 (100 to 103), but the field says 0.
  - JhV1RPOGAGw: totals show +5, but the field says 1.
  - I1EbGRaQumk: the field says 39 since the last pull, against a total of 161.
  - The field seems to measure from a later pull that was never logged here.
- **Lesson 3:** y6YS18A8hYY's run is now judged over, not just slowed.
- **Lesson 4:** Odyssey no longer explains HvumlX9trg0's flop, because I1EbGRaQumk is Odyssey and reached 142 discovery in about 8 days.
- **Lesson 7:** frJb60y4d5M vs y6YS18A8hYY at 30 minutes moves from the edge of noise to inside it.
- **pr5JhPlr18c's sources** came back. Its discovery is 6, not the carried 5.
- **Open tests:** test 3 is promoted to run now, because the prediction check that blocked a thumbnail change is done. Test 4 is parked.

---

## What the numbers show

**1. Two videos have bought views. Both are excluded from every lesson.**
- **JhV1RPOGAGw (Calypso):**
  - 1,874 of 2,005 views came from ADVERTISING.
  - It gained 5 views in 7 days, none from ads.
- **tg1Ixcm_-6k (Dune temples):**
  - 451 of 541 views came from ADVERTISING.
  - It gained 0 views in 7 days.
- **Organic remainders are excluded too:** 131 views and 90 views. Ad viewers can come back later through browse, so these remainders are not clean.
- **Clean organic base:** 1,086 views across 11 videos. That is the 10 older ones (925, up 4 in 7 days) plus I1EbGRaQumk (161).
- **Subs:** tg1Ixcm_-6k's 6 subs, the most on any video, are excluded with it.

**2. Story-world titles get discovered. Generic ambient titles mostly do not.**

Discovery views, lifetime, clean organic videos only:

| Group | Video | Discovery | Age (days) |
|---|---|---|---|
| IP named in title | y6YS18A8hYY | 211 | 45 |
| | I1EbGRaQumk | 142 | 8 |
| | frJb60y4d5M | 121 | 148 |
| | nAiWwRx1Tk0 | 95 | 131 |
| | 7E-NO3zf7w4 | 80 | 205 |
| | wHOZ8ppszSI | 79 | 77 |
| | s0s476Lnjtk | 19 | 204 |
| | HvumlX9trg0 | 17 | 48 |
| No IP name | ofA7JRdzH8k | 33 | 157 |
| | kg-RRBuGsuQ | 23 | 95 |
| | pr5JhPlr18c | 6 | 197 |

- The IP-group median is about 88. The no-IP median is 23.
- The no-IP videos are older, so they had more time, not less.
- ofA7JRdzH8k and pr5JhPlr18c are not story worlds at all. The table supports the story-world idea. It does not show where the IP name should sit in the title.

**3. y6YS18A8hYY's run is over.**
- **Lifetime:** 226 views in 45 days, about 5.0 per day. Browse brought 132.
- **Last two windows:**
  - 1 view in 2.6 days (to 10-19).
  - 1 view in 7 days (to 10-26), about 0.14 per day.
- Two windows in a row make analytics lag an unlikely explanation. Almost all its views came early in its life.
- **Other lifetime rates for comparison:**
  - wHOZ8ppszSI: about 1.3 per day (103 in 77 days).
  - frJb60y4d5M: about 1.0 per day (145 in 148 days).
  - I1EbGRaQumk: about 19 per day (161 in about 8.4 days, front-loaded).

**4. Neither the package nor the IP explains HvumlX9trg0's flop.**
- **Package:** HvumlX9trg0 shipped 3 days before y6YS18A8hYY. It had the same title format, the same ip_first thumbnail style, and close thumbnail metrics:

| Metric | HvumlX9trg0 | y6YS18A8hYY |
|---|---|---|
| Luminance | 82.7 | 82.9 |
| Contrast | 64.9 | 70.7 |
| Lower third darker by | 66.1 | 60.8 |

  It got 17 discovery views against 211.
- **IP:** I1EbGRaQumk is also Odyssey. It reached 142 discovery in about 8 days, with 109 from browse. So Odyssey does not explain the 17.
- **What is left:** the publish slot (HvumlX9trg0 went out Labor Day, Monday 19:46 PT), the visual, or timing luck. See the guesses section.
- **There is still no IP ranking.** The spread inside each IP is wider than the gaps between them:

| IP | Videos and views |
|---|---|
| Dune | y6YS18A8hYY 226, 7E-NO3zf7w4 119 |
| Project Hail Mary | frJb60y4d5M 145, nAiWwRx1Tk0 111, s0s476Lnjtk 50 |
| Odyssey | I1EbGRaQumk 161, wHOZ8ppszSI 103, HvumlX9trg0 18 |

**5. The 1-minute promise is kept best on y6YS18A8hYY and frJb60y4d5M. I1EbGRaQumk sits with the rest.**

| Video | r_1min | Viewers |
|---|---|---|
| y6YS18A8hYY | 0.573 | 226 |
| frJb60y4d5M | 0.540 | 145 |
| nAiWwRx1Tk0 | 0.387 | 111 |
| ofA7JRdzH8k | 0.386 | 45 |
| pr5JhPlr18c | 0.375 | 51 |
| wHOZ8ppszSI | 0.322 | 103 |
| I1EbGRaQumk | 0.311 | 161 |
| 7E-NO3zf7w4 | 0.246 | 119 |
| s0s476Lnjtk | 0.225 | 50 |

- **The two leaders:** gap 0.03, inside noise.
- **Beyond noise:**
  - Both leaders vs wHOZ8ppszSI, 7E-NO3zf7w4, s0s476Lnjtk and nAiWwRx1Tk0. For example, y6YS18A8hYY vs nAiWwRx1Tk0 is a gap of 0.19 against a band of ±0.11.
  - Both leaders vs I1EbGRaQumk: gap 0.26 against ±0.10, and gap 0.23 against ±0.11.
  - y6YS18A8hYY vs pr5JhPlr18c (gap 0.20, band ±0.15) and vs ofA7JRdzH8k (gap 0.19, band ±0.16).
- **At the edge:** frJb60y4d5M vs pr5JhPlr18c (gap 0.165, band ±0.16).
- **Inside noise:**
  - frJb60y4d5M vs ofA7JRdzH8k (gap 0.15, band ±0.17).
  - I1EbGRaQumk vs nAiWwRx1Tk0 (gap 0.08, band ±0.12).
- **Noise only:** HvumlX9trg0's 0.818 rests on about 18 viewers.

**6. Thumbnails with a dark lower third go with a kept 1-minute promise. The prediction made on 10-19 held.**

This is a correlation, not a tested cause.

| Lower third darker by | Videos | r_1min |
|---|---|---|
| 48 or more | y6YS18A8hYY (60.8), frJb60y4d5M (48.1) | 0.573, 0.540 |
| 35 to 39 | nAiWwRx1Tk0 (39.3), ofA7JRdzH8k (35.1) | 0.387, 0.386 |
| 3 or less | 7E-NO3zf7w4 (3.2), pr5JhPlr18c (−0.6), s0s476Lnjtk (−1.0), wHOZ8ppszSI (−14.9), I1EbGRaQumk (−28.4) | 0.246, 0.375, 0.225, 0.322, 0.311 |

- **The prediction:** on 10-19, I1EbGRaQumk (lower third brighter by 28.4) was predicted at r_1min 0.23 to 0.39. A result of 0.50 or more would have weakened this lesson.
- **The result:** 0.311 on 161 viewers (band ±0.07), with the thumbnail unchanged.
  - This is the first out-of-sample check, and it passed.
  - It is consistent with the lesson but does not prove it.
- **Correlation:** the rank correlation across 9 videos is 0.82, down from 0.88 across 8. The new point landed in the bottom group as predicted. The order inside the bottom group is noise.
- **What the pattern really is:** two high videos, and seven between 0.23 and 0.39.
- **Audience mix does not explain it.** Browse share and r_1min do not line up:

| Video | Browse share | r_1min |
|---|---|---|
| I1EbGRaQumk | 68% | 0.311 |
| nAiWwRx1Tk0 | 61% | 0.387 |
| y6YS18A8hYY | 58% | 0.573 |

- **Overall brightness does not explain it either.** pr5JhPlr18c has luminance 91.0 and sits in the bottom group. frJb60y4d5M has luminance 61.6 and sits in the top group. That said, the two darkest thumbnails, s0s476Lnjtk (26.3) and I1EbGRaQumk (33.8), both sit low.
- **HvumlX9trg0** (66.1, r_1min 0.818) fits the pattern but is noise-sized.
- **The thumb_style label does not explain it.** frJb60y4d5M is mood_text and sits in the top group.
- **It does not predict discovery, in either direction.**
  - HvumlX9trg0 has the darkest lower third and 17 discovery views.
  - I1EbGRaQumk has the brightest lower third and 142 discovery views in 8 days.
  - The lower third goes with whether viewers stay past a minute, not with whether they arrive.
- **Range limit:** luminance is 26 to 92 across every video behind this lesson.

**7. The 30-minute hold is best on frJb60y4d5M. The visual label does not predict it.**

| Video | r_30min | Share of 1-min viewers still there at 30 min |
|---|---|---|
| frJb60y4d5M | 0.241 | 0.45 |
| y6YS18A8hYY | 0.164 | 0.29 |
| pr5JhPlr18c | 0.146 | 0.39 (about 19 viewers at 1 min) |
| nAiWwRx1Tk0 | 0.099 | 0.26 |
| I1EbGRaQumk | 0.082 | 0.26 |
| ofA7JRdzH8k | 0.068 | 0.18 |
| 7E-NO3zf7w4 | 0.061 | 0.25 |
| wHOZ8ppszSI | 0.056 | 0.17 (3-hour video) |
| s0s476Lnjtk | 0.020 | 0.09 |

- **frJb60y4d5M vs y6YS18A8hYY:** gap 0.077 against a band of ±0.086. That is now inside noise.
- **frJb60y4d5M vs nAiWwRx1Tk0:** gap 0.14 against ±0.09, still beyond noise. Both are "space" visuals, and so is s0s476Lnjtk at 0.020.
- **I1EbGRaQumk's interior visual** held 0.26 of its 1-minute viewers. That matches nAiWwRx1Tk0 and is close to y6YS18A8hYY.
  - The band is about ±0.12 on roughly 50 one-minute viewers.
  - Its low r_30min comes from the first-minute drop, not from the visual losing people later.
  - Against frJb60y4d5M's 0.45, the gap is at the edge of noise (gap 0.19, band ±0.17).

**8. kg-RRBuGsuQ's retention is not comparable with the others.**
- 30 of its 57 views came from EXT_URL, meaning an outside site or embed.
- Its r_start is 0.446, against 0.82 to 1.0 everywhere else.
- Its curve rises from 10 to 30 minutes (0.250 to 0.286).
- It stays out of lessons 5 to 7.

**9. Suggested traffic is lumpy on some videos and spread thin on others.**
- **frJb60y4d5M:** 49 of its 92 suggested views came from one video, 5gO0xpY_Y3E. Without that placement it would have about 72 discovery views, not 121.
- **OaourFG3xYY** suggested both y6YS18A8hYY (5) and JhV1RPOGAGw (2).
- **I1EbGRaQumk** is spread thin. Its top suggester, qoVqOaRpQXI, sent 2 of 33. None of our own videos appear in its top 10. Its reach came from browse, not from one placement.
- **Our own videos feed each other a little:**
  - nAiWwRx1Tk0 sent 3 to frJb60y4d5M.
  - kg-RRBuGsuQ sent 2 to 7E-NO3zf7w4.
  - 7E-NO3zf7w4 sent 1 each to ofA7JRdzH8k and frJb60y4d5M.

**10. On most videos, browse viewers leave sooner than suggested viewers.**

Estimated minutes per view by source:

| Video | Browse | Suggested |
|---|---|---|
| y6YS18A8hYY | 2.5 (331 / 132) | 11.1 (874 / 79) |
| frJb60y4d5M | 7.9 | 18.4 |
| nAiWwRx1Tk0 | 6.1 | 8.4 |
| wHOZ8ppszSI | 5.3 | 11.9 |
| I1EbGRaQumk | 1.9 (209 / 109) | 4.0 (133 / 33) |

- **I1EbGRaQumk's browse viewers stayed the shortest of any video with more than 10 browse views.** Many home-feed viewers arrived and left quickly.
- **Exceptions:**
  - 7E-NO3zf7w4: browse 7.6, suggested 2.6.
  - ofA7JRdzH8k: browse 10.0, suggested 6.2, on only 4 browse views.
  - s0s476Lnjtk: 2.6 vs 2.0, both tiny.
- **Caveat:** per-source minutes run about half of avg_view_pct.
  - y6YS18A8hYY: 5.8 minutes per view, about 9.6% of an hour, against avg_view_pct 19.5.
  - I1EbGRaQumk: 2.1 minutes per view, about 3.6%, against avg_view_pct 8.0.
  - Use this table to compare sources, not as absolute watch time.

**11. Subs and search are too small to judge anything.**
- **Organic subs:** 7 across 11 clean videos and 1,086 views, about 1 per 155.
  - I1EbGRaQumk gained 0 from 161 views. At 1 per 130, about 1.2 would be expected, so 0 is inside noise.
- **Channel subs:** 170 at both pulls. There was no net change in a week when the counter rose 138.
- **Tracked subs:** all tracked videos together account for 16 subs, against a channel total of 170.
- **Search:** no new terms. The only recurring intent is still "project hail mary ambience/ambient" (5 searches on s0s476Lnjtk, 2 on nAiWwRx1Tk0).

**12. I1EbGRaQumk's first week: strong reach, weak first minute.**
- **Published:** Saturday 2026-10-17 at 15:58 PT. The pull came about 8.4 days later, roughly 6 days of analytics after lag.
- **Reach:**
  - 161 views, 142 of them discovery (109 browse, 33 suggested).
  - Its 109 browse views are second only to y6YS18A8hYY's 132 lifetime.
  - Its 142 discovery views are second on the channel, reached in 8 days.
- **Retention:**

| Measure | Value |
|---|---|
| r_1min | 0.311 |
| r_10min | 0.164 |
| r_30min | 0.082 |
| r_end | 0.049 |
| avg_view_pct | 8.04 |

- **Other outcomes:** 0 subs, 1 like, 0 comments.
- **What it changes:**
  - Odyssey can reach (lesson 4).
  - An off-recipe thumbnail did not stop reach (lesson 6).
  - The interior visual held its 1-minute viewers at an average rate (lesson 7).
- **Logged for later:**
  - Music 3 stars.
  - Visual metrics: wrap 1.79, wrap ratio 2.05, speed envelope 3.96, detail swing 0.26.
  - The loom-click audio was flagged SUSPECT. The 4-point retention curve cannot show whether it caused a drop.
- **Thumbnail:** unchanged, with the lower third brighter by 28.4. So open test 3 has not started.

**Channel total check**
- The counter rose 138 (3,844 to 3,982). Tracked analytics rose 170 (3,462 to 3,632).
- Tracked rose more because I1EbGRaQumk's early views were already on the counter at 10-19 but had no analytics then.

**GsNmBR0BGF0 (Frodo)**
- Still private and unchanged.
- Thumbnail luminance is 133.5 and white share is 0.073, both outside every lesson's range.
- Music is 2 stars.

---

## What is still a guess

**Why I1EbGRaQumk drew 109 browse views in its first week.** The candidates are:
- the Saturday 15:58 PT slot;
- YouTube testing a new upload widely in the home feed;
- the Odyssey IP;
- the character-led scene title ("Penelope at the Loom").

The data cannot separate them.

**Whether a broken first-minute promise will cut its run short.** This is a suspicion. Its browse viewers stayed about 1.9 minutes each, and the home feed may stop showing it sooner than it stopped showing y6YS18A8hYY. There is no first-week figure for y6YS18A8hYY to compare against.

What to watch: its discovery against y6YS18A8hYY's 211.
- If I1EbGRaQumk passes 211 within 45 days despite r_1min 0.311, slot or momentum matters more for reach than the first minute.
- If it stalls well below, the broken promise may be capping it.

**Why y6YS18A8hYY broke out.** The field has narrowed:
- The package alone is ruled out (lesson 4, HvumlX9trg0).
- Dune is no longer required for a strong first week (I1EbGRaQumk).
- The remaining candidates are the publish slot, a home-feed test that went well and ended, and outside pickup that ended. The sharp end of its run (lesson 3) fits the last two.

**Publish timing.** The three highest-discovery videos all went out Friday to Sunday, 15:00 to 16:00 PT:

| Video | Slot | Discovery |
|---|---|---|
| y6YS18A8hYY | Friday 15:02 | 211 |
| I1EbGRaQumk | Saturday 15:58 | 142 |
| frJb60y4d5M | Sunday 15:23 | 121 |

The other IP videos went out at other times:

| Video | Slot | Discovery |
|---|---|---|
| nAiWwRx1Tk0 | Wednesday 09:29 | 95 |
| 7E-NO3zf7w4 | Saturday 08:56 | 80 |
| wHOZ8ppszSI | Monday 12:04 | 79 |
| s0s476Lnjtk | Saturday 18:32 | 19 |
| HvumlX9trg0 | Monday 19:46 | 17 |

- The medians are 142 inside the window and 79 outside.
- Every one of these videos also differs in IP, package, visual and channel age. One exception: ofA7JRdzH8k went out Friday at 14:56 and got 33, but it has no IP.
- This is the strongest common thread, and it is still not tested.

**Why a dark lower third helps the first minute.** Possible reasons:
- text reads more clearly over a dark band;
- the composition matches the opening frames;
- it stands in for the newer image pipeline;
- chance, since two high videos still carry it.

The I1EbGRaQumk result is consistent with the lesson but cannot tell these apart.

**Whether the 30-minute hold comes from the visual or from the audience.** frJb60y4d5M's best hold coincides with 49 viewers arriving from 5gO0xpY_Y3E.

**Music and visual metrics.** Only I1EbGRaQumk has both metrics and outcomes: 3 stars, and 0.26 of 1-minute viewers still there at 30 minutes. One point links nothing.

**IP effect.** Dune, Project Hail Mary and Odyssey overlap. Lord of the Rings is untested.

A hunch only: sailing-at-dawn visuals are weak. This rests on HvumlX9trg0 alone. GsNmBR0BGF0 has not shipped.

**Use-case phrase.**
- With it: 211, 142, 80, 79 and 17 discovery views.
- Without it: 121, 95 and 19.
- There is no pattern. It stays constant from here.

**Data gaps:**
- No impressions or CTR.
- No first-48-hour numbers for y6YS18A8hYY.
- 5 videos are untracked.
- The `views_since_last_pull` field refers to a pull this file never logged.

Pulling every Monday 08:00, and recording each pull here, would keep the 7-day deltas clean. This pull already falls on that day.

---

## Next release

- **Title format:** ip_first, two pipes, hour tag, use case, 56 to 68 characters, with scene words matching the visual, for example "Dune | Dusk Over the Deep Desert | 1 Hour Deep Focus Ambient". Evidence: IP titles have a discovery median of about 88 against 23 for no-IP titles (lesson 2), and I1EbGRaQumk used this format and reached 142 in 8 days.
- **IP:** Dune, as the recipe repeat (test 1). Evidence: I1EbGRaQumk shows Odyssey can reach, so Dune is no longer the leading suspect, but a clean repeat of y6YS18A8hYY needs the same IP (lessons 3 and 4).
- **Thumbnail style:** luminance about 80 (keep it between 60 and 92), lower third 50 to 65 darker, title text in that band. Evidence: the 10-19 prediction held, with I1EbGRaQumk landing at r_1min 0.311 against 0.54 to 0.57 for the two dark-lower-third leaders (lessons 5 and 6); this buys first-minute retention, not reach.
- **Visual:** a slow dusk horizon with a lone figure, in the desert_dusk_figure family. Evidence: no visual label predicts the 30-minute hold, and I1EbGRaQumk's interior visual held 0.26 of 1-minute viewers against y6YS18A8hYY's 0.29 (lesson 7), so copying y6YS18A8hYY keeps test 1 clean and costs nothing.
- **Publish day and hour:** Friday 30 October, 15:00 PT (22:00 UTC); if the release is not ready, use Friday 6 November, 15:00 PST (23:00 UTC). Evidence: the three highest-discovery videos all went out Friday to Sunday, 15:00 to 16:00 PT (y6YS18A8hYY 211, I1EbGRaQumk 142, frJb60y4d5M 121), though every one is confounded.
  - Either date leaves at least 13 days after I1EbGRaQumk.
  - A new release may slow I1EbGRaQumk's thumbnail test by drawing home-feed traffic. This is a suspicion, not shown.
- **If Cole posts Frodo (GsNmBR0BGF0) instead:**
  - Use the same Friday 15:00 PT slot.
  - First, measure the 3 thumbnail candidates in the release folder. Ship one with luminance 92 or less and a lower third 50 to 65 darker, if one exists.
  - Log it as a new-IP release with 2-star music, not as a recipe test.

---

## Open tests (one variable each)

1. **Thumbnail Test & Compare on I1EbGRaQumk: start now.**
   - **Variable:** thumbnail only.
   - **Why now:**
     - The prediction check is done, so changing the thumbnail no longer costs a reading.
     - I1EbGRaQumk is the only video with real current traffic. The latest field shows 39 views since an unlogged pull. The older videos added 4 views combined in 7 days.
   - **Setup:**
     - Measure the lower third on thumbnail_b_scene.png and thumbnail_c_moment.png.
     - Pit the shipped thumbnail (brighter by 28.4) against whichever alternate is darker by 48 or more. If neither is, darken the band on the shipped image.
   - **Reading:** Test & Compare picks by watch-time share, which suits our lack of CTR. A dark-lower-third win supports lesson 6 on the same video at the same time.
2. **Recipe repeat: still not run.**
   - **Variable:** scene only. Use Dune, the title format, the thumbnail metrics, the dusk-figure visual and Friday 15:00 PT, all as on y6YS18A8hYY.
   - **Read** discovery at 7, 14 and 35 days, against y6YS18A8hYY's 211 at 45 days and I1EbGRaQumk's 142 at 8 days.
   - **About 100 or more by day 14** means the recipe plus the slot is repeatable.
   - **Near 17** means y6YS18A8hYY was largely luck or outside pickup.
3. **Retitle kg-RRBuGsuQ to put the IP first: not started.**
   - **Change:** "Dawn Over Arrakis" becomes "Dune | Dawn Over Arrakis | 1 Hour Desert Ambient". Variable: title only.
   - **Baseline:** 23 discovery views in 95 days, about 0.24 per day, so roughly 7 expected in 30 days.
   - **Beyond chance:** 15 or more in the 30 days after the change.
4. **Thumbnail lower third on 7E-NO3zf7w4: parked.**
   - It added 0 views in 7 days, so Test & Compare would not conclude.
   - Revisit only if its traffic returns.
5. **IP swap: after test 2.**
   - **Variable:** IP only. Ship Odyssey with the identical recipe in the Friday 15:00 PT slot.
   - **Lower value than before.** I1EbGRaQumk already shows that Odyssey is not why HvumlX9trg0 failed. This now tests only whether IP changes the recipe's result.
6. **Publish slot: higher value than before.**
   - **Variable:** slot only.
   - **Setup:** after two releases at Friday 15:00 PT, ship one identical-recipe release outside the weekend-afternoon window, on Wednesday at 09:00 PT (nAiWwRx1Tk0's slot, 95 discovery).
   - **Why it matters:** this slot pattern is now the strongest unexplained thread (three of three top-discovery videos).
   - **Expect** several rounds before any difference clears noise.
