#!/usr/bin/env python3
"""competitor_watch.py — reverse-engineer what works for incumbent ambient channels.

Retention and CTR are private, but the public record is enough to see demand:
  * OUTLIERS: a video doing 5x its own channel's median didn't get lucky — the
    TOPIC overperformed. Outliers across several channels = a demand map.
  * FAIR COMPARISON: views-per-day at the same video age. Comparing a 2-day-old
    video's total views to a 2-year-old's is meaningless; trajectory isn't.
  * PATTERNS: what franchises/words/durations/cadences the winners share.

Usage:
  .venv/bin/python competitor_watch.py             # snapshot + report
  .venv/bin/python competitor_watch.py --discover "odyssey ambient"   # find channels
  .venv/bin/python competitor_watch.py --recurrence  # + which outliers people keep coming back to

Output: output/_competitor/<stamp>/report.json (+ printed summary).
Reuses the read-only analytics OAuth token; public data only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

HERE = Path(__file__).resolve().parent

# The competitive set. Start with channels Cole actually loses suggested-slots
# to; extend via --discover. Handle = fallback if the ID ever goes stale.
COMPETITORS = {
    "UCmGU7IuCWuFRhM8WXvOEM4A": "Symbology Cinematics",
    "UCfR8HhkbpDAwvYxrecNg4Mg": "Ambient Worlds",
    "UC7GZzOWjuG4wMua82uEguXQ": "Obsidian Soundfields",
    "UCTn68irGFi8M5EdYrfWqJuQ": "Ambient Cinematics",
    "UClDzr-KM5H2-bsO3xIC32mg": "Bjorth",
    "UCj3460Ylt4JEcEiW6PxCH9Q": "SpaceWave",
}
OWN_CHANNEL = "UCgTQFa3Fjc78PjMK2HGsGXQ"   # The Space of Sound

FRANCHISE_WORDS = re.compile(
    r"\b(dune|arrakis|lotr|rings|middle.?earth|gondor|rivendell|hobbit|odyssey|"
    r"calypso|greek|witcher|elden|zelda|hyrule|star wars|tatooine|interstellar|"
    r"hail mary|blade runner|cyberpunk|skyrim|harry potter|hogwarts|got|westeros|"
    r"avatar|pandora|halo|mass effect|warhammer|ghibli|narnia|conan|stargate)\b",
    re.I)


def yt_client():
    creds = Credentials.from_authorized_user_info(
        json.load(open(HERE / "yt_analytics_token.json")))
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def comments_client():
    # commentThreads.list wants the youtube.force-ssl scope, which only the upload token carries;
    # this script uses it for that one read call and nothing else.
    creds = Credentials.from_authorized_user_info(json.load(open(HERE / "youtube_token.json")))
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_uploads(yt, channel_id, max_videos=200):
    ch = yt.channels().list(part="snippet,statistics,contentDetails",
                            id=channel_id).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    vids, page = [], None
    while len(vids) < max_videos:
        r = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                    maxResults=50, pageToken=page).execute()
        vids += [it["contentDetails"]["videoId"] for it in r.get("items", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    stats = []
    for i in range(0, len(vids), 50):
        r = yt.videos().list(part="snippet,statistics,contentDetails",
                             id=",".join(vids[i:i + 50])).execute()
        for it in r.get("items", []):
            sn, st = it["snippet"], it.get("statistics", {})
            dur = _dur_sec(it.get("contentDetails", {}).get("duration", ""))
            pub = dt.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
            age = max(1.0, (dt.datetime.now(dt.timezone.utc) - pub).total_seconds() / 86400)
            stats.append({
                "video_id": it["id"], "title": sn["title"],
                "published_at": sn["publishedAt"], "age_days": round(age, 1),
                "duration_sec": dur, "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comment_count": int(st.get("commentCount", 0)),
                "views_per_day": round(int(st.get("viewCount", 0)) / age, 1),
            })
    return {
        "channel_id": channel_id,
        "title": ch["snippet"]["title"],
        "subs": int(ch["statistics"].get("subscriberCount", 0)),
        "videos": stats,
    }


def _dur_sec(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def analyze(chan):
    """Outlier score = video's views/day over the channel's median views/day.
    >2 means the TOPIC overperformed the channel's own audience — demand."""
    longform = [v for v in chan["videos"] if v["duration_sec"] > 900 and v["age_days"] > 7]
    if len(longform) < 3:
        longform = [v for v in chan["videos"] if v["age_days"] > 2] or chan["videos"]
    med = statistics.median(v["views_per_day"] for v in longform) or 0.1
    for v in chan["videos"]:
        v["outlier_score"] = round(v["views_per_day"] / med, 2)
        fr = FRANCHISE_WORDS.search(v["title"])
        v["franchise"] = fr.group(0).lower() if fr else None
    chan["median_views_per_day"] = round(med, 1)
    # views per subscriber per month: is the catalogue reaching past its audience? Fair across channel sizes.
    if chan["subs"]:
        chan["views_per_sub_month"] = round(sum(v["views_per_day"] for v in chan["videos"]) * 30 / chan["subs"], 2)
    # cadence: uploads in the last 90 days
    recent = [v for v in chan["videos"] if v["age_days"] <= 90]
    chan["uploads_per_month_recent"] = round(len(recent) / 3, 1)
    return chan


RETURNING = re.compile(
    r"\b(every (day|night|morning)|each (day|night)|daily|again|back (here|to this)|keep coming back|"
    r"come back|came back|still (listen|here|coming)|for (months|years|weeks)|on repeat|"
    r"(study|work|sleep|focus|read|cod)\w* (to|with) this|my go.?to)\b", re.I)


# Scout, 2026-11-04: farmed comments arrive in bursts with nobody liking or answering them. Hollow Knight's 0.73 held
# 2 such months (40 and 117 threads, 96%+ dead); the real listeners on Wet Land and Green never pass 62% and 100% only
# at 6 threads. Tuned on 1 confirmed farm, so a flag to read, not proof.
FARM_MIN_THREADS, FARM_DEAD_SHARE = 20, 0.9


def recurrence(yt, video, max_pages=10):
    """HackerTube's test (Karpathy, 2026-10): what lasts beats what spiked. year_pace = comments in
    the last 365 days over the video's lifetime yearly pace; near 1 means people keep arriving as fast
    as they ever did, near 0 means it spiked and went quiet. Replies count as comments on both sides
    (the API's commentCount includes them), credited to their thread's date. Also counts comments that
    read as a returning listener ("I study to this every night"), a regex stand-in for HackerTube's
    model-labeled stance. Videos under 1 year old aren't scored: too young to tell.
    (v1 compared the newest 300 comments' pace to lifetime pace; the scout's first tick, 2026-11-03,
    showed it reads ~0.6 by construction when every comment fits in 300 and hides fades when 300
    span years.)
    year_pace_clean drops months that look farmed (FARM_*), on the same denominator; farm_months names them."""
    now = dt.datetime.now(dt.timezone.utc)
    year, read, returning, page, capped = 0, 0, 0, None, True
    months = {}   # "YYYY-MM": [comments incl. replies, threads, threads with no like and no reply]
    for _ in range(max_pages):
        try:
            r = yt.commentThreads().list(part="snippet", videoId=video["video_id"], maxResults=100,
                                         order="time", textFormat="plainText", pageToken=page).execute()
        except Exception:   # comments disabled
            capped = False
            break
        last = None
        for it in r.get("items", []):
            c = it["snippet"]["topLevelComment"]["snippet"]
            t = dt.datetime.fromisoformat(c["publishedAt"].replace("Z", "+00:00"))
            read += 1
            returning += bool(RETURNING.search(c.get("textDisplay", "")))
            if (now - t).days <= 365:
                replies = it["snippet"].get("totalReplyCount", 0)
                year += 1 + replies
                m = months.setdefault(t.strftime("%Y-%m"), [0, 0, 0])
                m[0] += 1 + replies
                m[1] += 1
                m[2] += not (replies or c.get("likeCount", 0))
            last = t
        page = r.get("nextPageToken")
        # stop once a page's oldest comment is past a year (a pinned old comment can head page one,
        # so the first old comment seen isn't the end)
        if not page or (last and (now - last).days > 365):
            capped = False
            break
    farm = sorted(k for k, m in months.items() if m[1] >= FARM_MIN_THREADS and m[2] / m[1] >= FARM_DEAD_SHARE)
    video.update(comments_read=read, returning_comments=returning, year_pace=None, year_pace_clean=None,
                 year_pace_floor=capped, farm_months=farm)
    if video["age_days"] < 365 or not video["comment_count"] or read < 10:
        return
    lifetime_pace = video["comment_count"] / video["age_days"] * 365
    video["year_pace"] = round(year / lifetime_pace, 2)
    video["year_pace_clean"] = round((year - sum(months[k][0] for k in farm)) / lifetime_pace, 2)


def own_suggesters(limit=15):
    """The videos that actually send us suggested traffic, lifetime, from the Analytics API."""
    creds = Credentials.from_authorized_user_info(json.load(open(HERE / "yt_analytics_token.json")))
    yta = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    rows = yta.reports().query(ids="channel==MINE", startDate="2026-01-01", endDate=dt.date.today().isoformat(),
                               metrics="views", dimensions="insightTrafficSourceDetail", maxResults=25, sort="-views",
                               filters="insightTrafficSourceType==RELATED_VIDEO").execute().get("rows", [])[:limit]
    titles = {}
    if rows:
        for v in build("youtube", "v3", credentials=creds, cache_discovery=False).videos().list(
                part="snippet", id=",".join(r[0] for r in rows)).execute().get("items", []):
            titles[v["id"]] = (v["snippet"]["channelTitle"], v["snippet"]["title"])
    return [{"video_id": r[0], "views": r[1], "channel": titles.get(r[0], ("?", "?"))[0], "title": titles.get(r[0], ("?", "?"))[1]}
            for r in rows]


def discover(yt, query, limit=8):
    r = yt.search().list(part="snippet", q=query, type="video",
                         maxResults=25, order="viewCount").execute()
    seen = {}
    for it in r.get("items", []):
        cid = it["snippet"]["channelId"]
        if cid not in seen and cid != OWN_CHANNEL:
            seen[cid] = it["snippet"]["channelTitle"]
    return dict(list(seen.items())[:limit])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", help="search query to find competitor channels")
    ap.add_argument("--max-videos", type=int, default=120)
    ap.add_argument("--recurrence", action="store_true",
                    help="also read comments on each channel's top outliers and rank by lasting months")
    a = ap.parse_args()
    yt = yt_client()

    if a.discover:
        found = discover(yt, a.discover)
        print(f"Channels ranking for {a.discover!r}:")
        for cid, name in found.items():
            print(f"  {cid}  {name}")
        return

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = HERE / "output" / "_competitor" / stamp
    out.mkdir(parents=True, exist_ok=True)

    channels = []
    for cid in list(COMPETITORS) + [OWN_CHANNEL]:
        try:
            print(f"pulling {COMPETITORS.get(cid, 'own channel')}…")
            channels.append(analyze(channel_uploads(yt, cid, a.max_videos)))
        except Exception as e:
            print(f"  FAILED {cid}: {e}", file=sys.stderr)

    if a.recurrence:
        cyt = comments_client()
        for c in channels:
            for v in sorted(c["videos"], key=lambda v: -v["outlier_score"])[:8]:
                recurrence(cyt, v)

    (out / "report.json").write_text(json.dumps(channels, indent=1))
    print(f"\nwrote {out/'report.json'}\n")

    own = next((c for c in channels if c["channel_id"] == OWN_CHANNEL), None)
    for c in channels:
        if c is own:
            continue
        print(f"=== {c['title']} — {c['subs']:,} subs, "
              f"{c['uploads_per_month_recent']}/mo recently, "
              f"median {c['median_views_per_day']} views/day ===")
        top = sorted(c["videos"], key=lambda v: -v["outlier_score"])[:8]
        for v in top:
            fr = f" [{v['franchise']}]" if v["franchise"] else ""
            print(f"  {v['outlier_score']:5.1f}x  {v['views_per_day']:7.0f} v/d  "
                  f"{v['duration_sec']//60:3d}min{fr}  {v['title'][:56]}")
        print()
    if a.recurrence:
        rows = [(c["title"], v) for c in channels for v in c["videos"] if v.get("year_pace") is not None]
        print("=== LASTING (year_pace, farmed months removed = last 365 days' comments / lifetime yearly pace; 1 = never faded, + = lower bound) ===")
        for ch, v in sorted(rows, key=lambda r: -r[1]["year_pace_clean"])[:20]:
            fr = f" [{v['franchise']}]" if v["franchise"] else ""
            farm = f" (raw {v['year_pace']:.2f}, farmed {','.join(v['farm_months'])})" if v["farm_months"] else ""
            print(f"  {v['year_pace_clean']:5.2f}{'+' if v['year_pace_floor'] else ' '} pace  {v['returning_comments']:3d}/{v['comments_read']:<3d} returning  "
                  f"{v['outlier_score']:5.1f}x  age {v['age_days']:4.0f}d  {ch[:18]:18s}{fr}  {v['title'][:44]}{farm}")
        print()
    if own:
        print(f"=== YOU — {own['subs']} subs, median {own['median_views_per_day']} views/day, "
              f"{own.get('views_per_sub_month')} views/sub/month ===")
        for v in sorted(own["videos"], key=lambda v: -v["views_per_day"])[:6]:
            print(f"  {v['outlier_score']:5.1f}x  {v['views_per_day']:7.1f} v/d  "
                  f"age {v['age_days']:4.0f}d  {v['title'][:56]}")
        print("\n=== WHO SUGGESTS YOU (lifetime views from each video's suggestions) ===")
        try:
            for r in own_suggesters():
                print(f"  {r['views']:5d}  {r['channel'][:22]:22s}  {r['title'][:56]}")
        except Exception as e:
            print(f"  failed: {str(e)[:200]}")


if __name__ == "__main__":
    main()
