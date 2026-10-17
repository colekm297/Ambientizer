LESSONS (updated 2026-10-16)

# Lessons file: The Space of Sound (non-music half)

Updated 2026-10-16. Second pass on the same pull (2026-10-16 17:55). This replaces the first-run file.

**Data used:** 12 of 17 videos, 3,454 of the channel's 3,801 views. The other 5 videos (347 views) are not in this pull.

**Glossary:**
- "Browse" means the API's SUBSCRIBER source, which covers the home feed and subscriptions feed.
- "Suggested" means RELATED_VIDEO.
- "Discovery" means browse + suggested views.
- Times are PT. April to October is all PDT (UTC minus 7). DST ends 1 November 2026.

**Noise rule:** by chance, a retention share at n viewers moves by about ±2×√(p(1−p)/n):

| Viewers | Band |
|---|---|
| 224 | about ±0.07 |
| 110 | about ±0.09 |
| 50 | about ±0.12 |

To compare two videos, combine their variances. Retention audiences are not exactly equal to views, so these bands are approximate.

**Changes from the first run:**
- s0s476Lnjtk was missing from the discovery table. It is now in, and it lowers the IP-group median from 88 to 80.
- The organic remainders of the two ad-boosted videos are removed from the IP comparison, to match the exclusion rule.
- kg-RRBuGsuQ is removed from the retention comparisons because of its traffic mix.
- Lesson 6 is completed.
- Lessons 7 to 11 are new.

---

## What the numbers show

**1. Two videos have bought views. Both are excluded from every lesson.**
- **JhV1RPOGAGw (Calypso):** 1,874 of 1,995 views came from ADVERTISING.
- **tg1Ixcm_-6k (Dune temples):** 451 of 541 views came from ADVERTISING.
- **Totals:** 2,325 bought views, leaving about 1,129 organic views across the 12 videos.
- The exclusion covers tg1Ixcm_-6k's 6 subs, the most on any video, because we cannot tell how many the ads brought.
- It also covers the organic remainders of both videos (121 and 90). Ad viewers can return through browse later, so those remainders are not clean.

**2. Story-world titles get discovered. Generic ambient titles mostly do not.**

Discovery views, lifetime, organic videos only:

| Group | Video | Discovery | Age (days) |
|---|---|---|---|
| IP named in title | y6YS18A8hYY | 209 | 35 |
| | frJb60y4d5M | 121 | 138 |
| | nAiWwRx1Tk0 | 95 | 121 |
| | 7E-NO3zf7w4 | 80 | 195 |
| | wHOZ8ppszSI | 79 | 67 |
| | s0s476Lnjtk | 19 | 194 |
| | HvumlX9trg0 | 17 | 38 |
| No IP name | ofA7JRdzH8k | 33 | 147 |
| | kg-RRBuGsuQ | 23 | 85 |
| | pr5JhPlr18c | 5 | 187 |

- The IP-group median is 80. The no-IP median is 23.
- The no-IP videos are older, so they had more time, not less.
- Two of the three no-IP videos (ofA7JRdzH8k Sanctuary, pr5JhPlr18c Escher) are not story worlds at all. This supports the story-world idea. It says nothing yet about where the IP name should sit in the title.

**3. y6YS18A8hYY is the best organic video by a wide margin.**
- It has 224 views in 35 days, about 6.4 per day. The next best rate is wHOZ8ppszSI at about 1.5 per day (100 in 67 days), then frJb60y4d5M at about 1.05 per day (145 in 138 days).
- Browse brought 132 of its views. No other video has more than 68 from browse (nAiWwRx1Tk0).

**4. The same title and thumbnail recipe did not repeat.**
- HvumlX9trg0 (Odyssey) shipped 3 days before y6YS18A8hYY. It used the same title format and the same ip_first thumbnail style. Its thumbnail metrics were close:
  - luminance 82.7 vs 82.9
  - contrast 64.9 vs 70.7
  - lower third darker by 66.1 vs 60.8
- It got 18 views (4 browse, 13 suggested) against 224. The package alone does not explain y6YS18A8hYY.
- There is no IP ranking yet, because organic views per IP overlap:

| IP | Videos and views |
|---|---|
| Dune | y6YS18A8hYY 224, 7E-NO3zf7w4 118 |
| Project Hail Mary | frJb60y4d5M 145, nAiWwRx1Tk0 111, s0s476Lnjtk 50 |
| Odyssey | wHOZ8ppszSI 100, HvumlX9trg0 18 |

The spread inside each IP is wider than the gaps between them.

**5. The 1-minute promise is kept best on y6YS18A8hYY and frJb60y4d5M.**
- r_1min is 0.574 on y6YS18A8hYY (n 224) and 0.540 on frJb60y4d5M (n 145). The two are inside noise of each other.
- The other comparable organic videos range from 0.225 to 0.387:

| Video | r_1min |
|---|---|
| s0s476Lnjtk | 0.225 |
| 7E-NO3zf7w4 | 0.246 |
| wHOZ8ppszSI | 0.330 |
| pr5JhPlr18c | 0.362 |
| ofA7JRdzH8k | 0.386 |
| nAiWwRx1Tk0 | 0.387 |

- **Beyond noise:** both top videos sit clearly above 7E-NO3zf7w4, s0s476Lnjtk and wHOZ8ppszSI. They are just beyond noise against nAiWwRx1Tk0 (gaps of 0.15 to 0.19, combined bands about ±0.11 to 0.12) and pr5JhPlr18c (frJb gap 0.18, band ±0.16).
- **Inside noise:** frJb60y4d5M vs ofA7JRdzH8k (gap 0.15, band ±0.17).
- HvumlX9trg0's 0.818 rests on about 18 viewers and is noise.

**6. Thumbnails with a dark lower third go with a kept 1-minute promise.**

This is a correlation, not a tested cause. Sorted by "lower third darker by":

| Lower third darker by | Videos | r_1min |
|---|---|---|
| 48 or more | y6YS18A8hYY (60.8), frJb60y4d5M (48.1) | 0.574, 0.540 |
| 35 to 39 | nAiWwRx1Tk0 (39.3), ofA7JRdzH8k (35.1) | 0.387, 0.386 |
| 3 or less | 7E-NO3zf7w4 (3.2), pr5JhPlr18c (−0.6), s0s476Lnjtk (−1.0), wHOZ8ppszSI (−14.9) | 0.246, 0.362, 0.225, 0.330 |

- The rank correlation across these 8 videos is about 0.88.
- The top group sits beyond noise above every video in the bottom group.
- The middle and bottom groups overlap within noise.
- HvumlX9trg0 (66.1, r_1min 0.818) fits the pattern but is noise-sized.
- The thumb_style label does not explain this. frJb60y4d5M is mood_text and sits in the top group.
- The same metric does not predict discovery. HvumlX9trg0 has the darkest lower third and only 17 discovery views.

**7. The 30-minute hold is best on frJb60y4d5M, and the visual label does not predict it.**

| Video | r_30min | Share of 1-min viewers still there at 30 min |
|---|---|---|
| frJb60y4d5M | 0.241 | 0.45 |
| y6YS18A8hYY | 0.157 | 0.27 |
| pr5JhPlr18c | 0.149 | 0.41 (only about 18 viewers at 1 min) |
| nAiWwRx1Tk0 | 0.099 | 0.26 |
| ofA7JRdzH8k | 0.068 | 0.18 |
| 7E-NO3zf7w4 | 0.061 | 0.25 |
| wHOZ8ppszSI | 0.057 | 0.17 (3-hour video) |
| s0s476Lnjtk | 0.020 | 0.09 |

- frJb60y4d5M vs y6YS18A8hYY is a gap of 0.084 against a band of ±0.086. That is at the edge of noise.
- Three videos share the "space" visual label: frJb60y4d5M 0.241, nAiWwRx1Tk0 0.099, s0s476Lnjtk 0.020. frJb60y4d5M vs nAiWwRx1Tk0 is beyond noise (gap 0.14, band ±0.09).
- The right-hand column removes the 1-minute promise and isolates the visual and music holding. frJb60y4d5M leads on it too.

**8. kg-RRBuGsuQ's retention is not comparable with the others.**
- 30 of its 57 views came from EXT_URL, meaning an outside site or embed.
- Its r_start is 0.446, against 0.82 to 1.0 everywhere else.
- Its curve rises from 10 min to 30 min (0.250 to 0.286), which does not happen with normal on-platform viewing.
- It is left out of lessons 5 to 7.

**9. Suggested traffic is lumpy, and one outside video can make a release.**
- 49 of frJb60y4d5M's 92 suggested views came from a single video, 5gO0xpY_Y3E.
- Those suggested viewers watched about 18.4 min per view, the highest of any source on the channel.
- Without that one placement, frJb60y4d5M would have about 72 discovery views, not 121.
- OaourFG3xYY suggested both y6YS18A8hYY (5) and JhV1RPOGAGw (2). At least one outside video is treating our Dune and Odyssey releases as related.

**10. Browse viewers leave sooner than suggested viewers.**
- Estimated minutes per view by source:

| Video | Browse | Suggested |
|---|---|---|
| y6YS18A8hYY | 2.5 (331 / 132) | 10.6 (820 / 77) |
| frJb60y4d5M | 7.9 | 18.4 |
| nAiWwRx1Tk0 | 6.1 | 8.4 |
| wHOZ8ppszSI | 5.3 | 11.9 |

- The only exception is 7E-NO3zf7w4: browse 7.6, suggested 2.6.
- Caveat: per-source minutes do not reconcile with avg_view_pct on y6YS18A8hYY. Use these as a comparison between sources, not as absolute watch time.

**11. Subs and search are too small to judge anything.**
- **Subs:** organic subs total 7 across 10 videos, roughly 1 per 160 views. The most is 3, on 7E-NO3zf7w4. No video differs from another beyond noise, so subs cannot be used to rank thumbnails yet.
- **Search:** the only recurring search intent is "project hail mary ambience/ambient" (5 searches on s0s476Lnjtk, 2 on nAiWwRx1Tk0). s0s476Lnjtk's 8 search viewers watched 3 minutes in total. The searchers did not find what they wanted there.

---

## What is still a guess

- **Why y6YS18A8hYY broke out.** The candidates are:
  - the Dune IP;
  - the publish slot (Friday 15:02 PT, against HvumlX9trg0's Monday 19:46 PT, which was Labor Day evening);
  - a home-feed test that happened to go well;
  - outside videos picking it up.

  The data cannot separate these. Lesson 4 rules out the package alone.
- **Why a dark lower third helps the first minute.** Three possible reasons:
  - text reads more clearly over a dark band;
  - a bright-sky, dark-ground horizon composition matches the opening frames, so the promise is kept;
  - it is a proxy for the newer image pipeline.

  It may not be causal at all. Eight videos is thin.
- **Whether the 30-minute hold comes from the visual or from the audience.** frJb60y4d5M's best hold coincides with 49 viewers arriving from one video (5gO0xpY_Y3E), probably a similar long-form ambient piece. Those viewers may have stayed because of who they were, not because of what they saw.
- **IP effect.** Nothing beyond lesson 2. Dune, Project Hail Mary and Odyssey all overlap.
- **Publish timing.** The two best organic videos went out mid-afternoon PT near the weekend: y6YS18A8hYY on Friday at 15:02, frJb60y4d5M on Sunday at 15:23. That is two data points with heavy confounds. Treat it as a hunch.
- **Use-case phrase ("Deep Focus", "Deep Work").** Videos with it got 209, 17, 79 and 80 discovery views. Videos without it got 121, 95 and 19. No pattern.
- **Data gaps that limit every claim above:**
  - No impressions or CTR.
  - No first-48-hour numbers.
  - views_since_last_pull is null because this is the first pull.
  - 5 videos are missing.

  Weekly pulls from now on would give deltas and let thumbnail and title changes be read cleanly.

---

## Next release

- **Title format:** ip_first, two pipes, hour tag, use case, about 56 characters. For example: "Dune | The Deep Desert at Night | 1 Hour Deep Focus Ambient". Evidence: IP titles have a discovery median of 80 vs 23 (lesson 2), and this copies y6YS18A8hYY exactly so that only the scene changes.
- **Thumbnail style:** bright image (luminance about 80) with a lower third about 50 to 65 darker, title text in that band. Evidence: the two videos at 48 or more, y6YS18A8hYY and frJb60y4d5M, hold the first minute at 0.54 to 0.57, against 0.23 to 0.36 for flat thumbnails (lesson 6). It is not a discovery fix (HvumlX9trg0).
- **Visual:** a slow, low-motion dusk horizon with a lone figure, in the same family as y6YS18A8hYY's desert_dusk_figure. Evidence: no visual label predicts the 30-minute hold (lesson 7), so the safest choice is the second-best hold (0.157) and the only breakout, which keeps the release a clean repeat.
- **IP:** Dune. Evidence: y6YS18A8hYY is the only video pulling browse traffic now (132 views), so a Dune sibling has the best chance of being shown next to it. This is a suspicion, not shown.
- **Publish day and hour:** Friday, 15:00 PT (22:00 UTC, still PDT in October). Evidence: this repeats y6YS18A8hYY's slot (Friday 15:02, the best organic result). frJb60y4d5M (Sunday 15:23) is the second best. Both are single data points and inside noise.

---

## Open tests (one variable each)

1. **Recipe repeat (the next release above).**
   - Variable: scene only. Same IP, title format, thumbnail metrics, visual family and slot as y6YS18A8hYY.
   - Read discovery views at 7, 14 and 35 days. The only benchmark is y6YS18A8hYY's 209 at 35 days.
   - If it reaches about 100 or more, the recipe plus IP plus slot is real.
   - If it lands near HvumlX9trg0's 17, y6YS18A8hYY was largely luck or outside pickup.
2. **Retitle kg-RRBuGsuQ to put the IP first.**
   - Change: "Dawn Over Arrakis" becomes "Dune | Dawn Over Arrakis | 1 Hour Desert Ambient".
   - Variable: title only. Thumbnail stays.
   - Baseline: 23 discovery views in 85 days, about 0.27 per day, so roughly 8 expected in 30 days.
   - 15 or more in the 30 days after the change would be beyond chance. This is the first direct test of where the IP name sits.
3. **Thumbnail lower third on 7E-NO3zf7w4.**
   - Its lower third is darker by only 3.2, and r_1min is 0.246.
   - Variable: thumbnail only. Use the same image with a darkened lower band and the text moved into it.
   - Use YouTube Studio's Test & Compare, which picks a winner by watch time and so suits our lack of CTR. Alternatively, swap the thumbnail and compare weekly deltas.
4. **IP swap.**
   - After test 1 reads out, ship an Odyssey release with the identical recipe and the same Friday 15:00 PT slot.
   - Variable: IP only. This also explains HvumlX9trg0 if Dune repeats and Odyssey does not.
5. **Publish slot.**
   - After two releases at Friday 15:00 PT, ship one identical-recipe release on Wednesday at 09:00 PT. That is nAiWwRx1Tk0's slot, which has the third-highest discovery (95).
   - Variable: slot only. Expect to need several rounds before any difference clears noise.
