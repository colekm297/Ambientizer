#!/usr/bin/env python3
"""
yt_analytics_pull.py — standalone YouTube channel analytics exporter.

Pulls everything we'd want to analyze for "The Space of Sound" and writes it to
a timestamped folder as JSON (raw) + CSV (flat, spreadsheet-friendly). This is a
throwaway exploration tool — it does NOT touch the app's upload token or any app
state. It keeps its OWN OAuth token in yt_analytics_token.json.

WHAT IT PULLS
  - Channel summary (subs, total views, video count)
  - Every video: title, publish date, duration, lifetime view/like/comment counts
  - Per-video analytics (publish-date → today):
      views, estimatedMinutesWatched, averageViewDuration,
      averageViewPercentage, subscribersGained, subscribersLost,
      and (when available) impressions + impressionsClickThroughRate (CTR)
  - Channel-level daily timeseries (views / watch-time / subs by day)
  - Traffic sources (where views come from)
  - Optional: per-video retention curve (--retention) — audienceWatchRatio across
    the video timeline, the data behind Studio's retention graph

ONE-TIME SETUP (required before first run)
  1. Google Cloud Console → your Ambientizer project → "APIs & Services" →
     "Enable APIs" → enable **YouTube Analytics API** (youtubeAnalytics.googleapis.com).
     (YouTube Data API v3 is already enabled.)
  2. "APIs & Services" → Credentials → your OAuth client → add this Authorized
     redirect URI:  http://localhost:8765/
  3. Run this script. A browser opens for consent (read-only analytics scope).
     The token is cached, so this is a one-time login.

USAGE
  .venv/bin/python yt_analytics_pull.py                 # full pull
  .venv/bin/python yt_analytics_pull.py --retention     # also pull retention curves
  .venv/bin/python yt_analytics_pull.py --days 90       # limit channel timeseries window
"""

import os
import sys
import csv
import json
import argparse
import datetime as dt
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

HERE = Path(__file__).resolve().parent
# Prefer a dedicated analytics OAuth client if present, else fall back to the
# app's client. Keeping a separate client isolates analytics from uploads.
CLIENT_SECRET = (HERE / "client_secret_analytics.json"
                 if (HERE / "client_secret_analytics.json").exists()
                 else HERE / "client_secret.json")
TOKEN_PATH = HERE / "yt_analytics_token.json"        # SEPARATE from app's upload token
OAUTH_PORT = 8765                                     # must match the redirect URI you added

# Read-only scopes only — this tool never writes anything to YouTube.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def get_credentials() -> Credentials:
    creds = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception:
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
            return creds
        except Exception:
            pass
    if not CLIENT_SECRET.exists():
        sys.exit(f"ERROR: {CLIENT_SECRET} not found.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=OAUTH_PORT, prompt="consent",
                                  authorization_prompt_message="")
    TOKEN_PATH.write_text(creds.to_json())
    print(f"  Saved token → {TOKEN_PATH}")
    return creds


def iso_today() -> str:
    return dt.date.today().isoformat()


def parse_duration(iso_dur: str) -> int:
    """ISO8601 PT#H#M#S → seconds (good enough for our durations)."""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_dur or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def get_channel(youtube):
    resp = youtube.channels().list(part="snippet,statistics,contentDetails",
                                   mine=True).execute()
    return resp["items"][0]


def list_all_videos(youtube, uploads_playlist_id):
    """Walk the uploads playlist → all video IDs + snippets."""
    videos = []
    page = None
    while True:
        resp = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=page,
        ).execute()
        for it in resp.get("items", []):
            videos.append({
                "video_id": it["contentDetails"]["videoId"],
                "title": it["snippet"]["title"],
                "published_at": it["contentDetails"].get("videoPublishedAt")
                or it["snippet"].get("publishedAt"),
            })
        page = resp.get("nextPageToken")
        if not page:
            break
    return videos


def hydrate_video_stats(youtube, videos):
    """Batch-fetch lifetime stats + duration for each video (Data API, 50/call)."""
    by_id = {v["video_id"]: v for v in videos}
    ids = list(by_id)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        resp = youtube.videos().list(part="statistics,contentDetails,status",
                                     id=",".join(chunk)).execute()
        for it in resp.get("items", []):
            v = by_id[it["id"]]
            st = it.get("statistics", {})
            v["lifetime_views"] = int(st.get("viewCount", 0))
            v["lifetime_likes"] = int(st.get("likeCount", 0))
            v["lifetime_comments"] = int(st.get("commentCount", 0))
            v["duration_sec"] = parse_duration(
                it.get("contentDetails", {}).get("duration"))
            v["privacy"] = it.get("status", {}).get("privacyStatus", "unknown")
    # The uploads playlist includes PRIVATE and UNLISTED videos. Analyzing those
    # alongside public ones poisons every average with videos nobody could watch
    # (learned the hard way: 20 of 34 uploads were private, and "your 4-15min
    # videos get no views" turned out to mean "your private videos get no views").
    public = [v for v in videos if v.get("privacy") == "public"]
    hidden = len(videos) - len(public)
    if hidden:
        print(f"  (excluding {hidden} non-public uploads from analysis; "
              f"IDs kept in JSON under 'non_public_videos')")
    return public, [v for v in videos if v.get("privacy") != "public"]


CORE_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,"
    "averageViewPercentage,subscribersGained,subscribersLost"
)
# NOTE: impressions + impressionsClickThroughRate are NOT exposed by the public
# YouTube Analytics API for regular channels (only Content Owner / Studio UI).
# A query returns 400 "Unknown identifier". The only way to get CTR is the
# manual Studio export: Studio → Analytics → Advanced mode → Export → choose the
# Impressions / Impressions CTR columns. We attempt it anyway and degrade
# gracefully if the channel happens to have access.
IMPRESSION_METRICS = "impressions,impressionsClickThroughRate"


def video_analytics(yta, channel_id, video_id, start_date):
    """Lifetime (publish→today) analytics for one video."""
    out = {}
    try:
        r = yta.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date, endDate=iso_today(),
            metrics=CORE_METRICS,
            filters=f"video=={video_id}",
        ).execute()
        if r.get("rows"):
            cols = [h["name"] for h in r["columnHeaders"]]
            out.update(dict(zip(cols, r["rows"][0])))
    except HttpError as e:
        out["_core_error"] = str(e)[:200]
    return out


def impressions_by_video(yta, channel_id, start_date):
    """One batched call: impressions + CTR per video (dimensions=video).

    Impressions metrics live in their own group and don't combine with the
    core metrics in a single query, so we pull them once across all videos.
    Returns {video_id: {impressions, impressionsClickThroughRate}} or an
    {"_error": ...} dict so failures are visible, not swallowed.
    """
    try:
        r = yta.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date, endDate=iso_today(),
            metrics=IMPRESSION_METRICS + ",views",
            dimensions="video",
            sort="-impressions",
            maxResults=200,
        ).execute()
        cols = [h["name"] for h in r.get("columnHeaders", [])]
        vid_idx = cols.index("video")
        out = {}
        for row in r.get("rows", []):
            rec = dict(zip(cols, row))
            out[rec.pop("video")] = rec
        return out
    except HttpError as e:
        return {"_error": str(e)[:300]}


def retention_curve(yta, channel_id, video_id, start_date):
    try:
        r = yta.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date, endDate=iso_today(),
            metrics="audienceWatchRatio,relativeRetentionPerformance",
            dimensions="elapsedVideoTimeRatio",
            filters=f"video=={video_id}",
        ).execute()
        cols = [h["name"] for h in r.get("columnHeaders", [])]
        return [dict(zip(cols, row)) for row in r.get("rows", [])]
    except HttpError as e:
        return {"_error": str(e)[:200]}


def channel_timeseries(yta, channel_id, start_date):
    r = yta.reports().query(
        ids=f"channel=={channel_id}",
        startDate=start_date, endDate=iso_today(),
        metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost",
        dimensions="day",
    ).execute()
    cols = [h["name"] for h in r.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in r.get("rows", [])]


def traffic_sources(yta, channel_id, start_date):
    r = yta.reports().query(
        ids=f"channel=={channel_id}",
        startDate=start_date, endDate=iso_today(),
        metrics="views,estimatedMinutesWatched",
        dimensions="insightTrafficSourceType",
        sort="-views",
    ).execute()
    cols = [h["name"] for h in r.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in r.get("rows", [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retention", action="store_true",
                    help="also pull per-video retention curves (slower)")
    ap.add_argument("--days", type=int, default=None,
                    help="limit channel timeseries to the last N days (default: all-time)")
    args = ap.parse_args()

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    yta = build("youtubeAnalytics", "v2", credentials=creds)

    print("Fetching channel…")
    ch = get_channel(youtube)
    channel_id = ch["id"]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    stats = ch.get("statistics", {})
    print(f"  {ch['snippet']['title']} — "
          f"{stats.get('subscriberCount','?')} subs, "
          f"{stats.get('videoCount','?')} videos, "
          f"{stats.get('viewCount','?')} total views")

    # Earliest date we can ask analytics for (channel-wide timeseries).
    if args.days:
        ts_start = (dt.date.today() - dt.timedelta(days=args.days)).isoformat()
    else:
        ts_start = "2005-01-01"  # YouTube's birth; API clamps to channel creation

    print("Listing videos…")
    videos = list_all_videos(youtube, uploads)
    videos, non_public = hydrate_video_stats(youtube, videos)
    print(f"  {len(videos)} public videos ({len(non_public)} non-public excluded)")

    print("Pulling impressions + CTR (batched)…")
    impr = impressions_by_video(yta, channel_id, ts_start)
    if isinstance(impr, dict) and impr.get("_error"):
        print("  ℹ impressions/CTR not available via API (YouTube limits these "
              "to Content Owners). Use Studio → Analytics → Advanced → Export "
              "for CTR. Continuing without it.")

    print("Pulling per-video analytics…")
    for i, v in enumerate(videos, 1):
        start = (v.get("published_at") or "2005-01-01")[:10]
        v["analytics"] = video_analytics(yta, channel_id, v["video_id"], start)
        # Merge in impressions/CTR from the batched call.
        if isinstance(impr, dict) and not impr.get("_error"):
            v["analytics"].update(impr.get(v["video_id"], {}))
        if args.retention:
            v["retention"] = retention_curve(yta, channel_id, v["video_id"], start)
        print(f"  [{i}/{len(videos)}] {v['title'][:50]}")

    print("Pulling channel timeseries + traffic sources…")
    try:
        ts = channel_timeseries(yta, channel_id, ts_start)
    except HttpError as e:
        ts = {"_error": str(e)[:300]}
    try:
        traffic = traffic_sources(yta, channel_id, ts_start)
    except HttpError as e:
        traffic = {"_error": str(e)[:300]}

    # ── write output ──────────────────────────────────────────────
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = HERE / "output" / "_yt_analytics" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = {
        "pulled_at": dt.datetime.now().isoformat(),
        "channel": {
            "id": channel_id,
            "title": ch["snippet"]["title"],
            "statistics": stats,
        },
        "videos": videos,
        "non_public_videos": [{k: v.get(k) for k in
                               ("video_id", "title", "privacy", "published_at")}
                              for v in non_public],
        "channel_timeseries": ts,
        "traffic_sources": traffic,
    }
    (out_dir / "analytics.json").write_text(json.dumps(bundle, indent=2))

    # Flat per-video CSV for spreadsheet exploration.
    csv_path = out_dir / "videos.csv"
    fields = ["video_id", "title", "published_at", "duration_sec",
              "lifetime_views", "lifetime_likes", "lifetime_comments",
              "views", "estimatedMinutesWatched", "averageViewDuration",
              "averageViewPercentage", "subscribersGained", "subscribersLost",
              "impressions", "impressionsClickThroughRate"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for v in videos:
            row = {k: v.get(k) for k in fields}
            row.update(v.get("analytics", {}))
            row["video_id"] = v["video_id"]
            row["title"] = v["title"]
            w.writerow({k: row.get(k) for k in fields})

    print(f"\nDone.\n  JSON: {out_dir / 'analytics.json'}\n  CSV:  {csv_path}")


if __name__ == "__main__":
    main()
