#!/usr/bin/env python3
"""_disclose_public.py: set YouTube's AI disclosure (status.containsSyntheticMedia) on the channel's public long-form videos.

YouTube Help requires it when AI "creates music that's the main focus of the video". New uploads already set
it (youtube_publisher.py); this covers what went up before that. Only that one field changes: every other
status field is sent back at its current value, read again just before each write. Refuses to write unless
the list is exactly the 13 IDs Cole was shown, and stops at any video that isn't public. A rerun skips videos
already logged. videos.list didn't return the field on the two drafts set 2026-11-04, so check in Studio
afterward (altered content radio, under Show more).

Usage: .venv/bin/python _disclose_public.py            dry run of the 13: prints the list and the exact request bodies
       .venv/bin/python _disclose_public.py --write    only after Cole's yes
       Add --shorts to either to act on the 5 public Shorts INSTEAD of the 13, a separate yes.
Log: data/disclose_public.jsonl (one line per write).
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from drafts_daily import yt_client

HERE = Path(__file__).resolve().parent
LOG = HERE / "data" / "disclose_public.jsonl"
MIN_SECS = 180   # Shorts run up to 3 minutes
EXPECTED = {"7E-NO3zf7w4", "s0s476Lnjtk", "pr5JhPlr18c", "ofA7JRdzH8k", "frJb60y4d5M", "tg1Ixcm_-6k", "nAiWwRx1Tk0",
            "kg-RRBuGsuQ", "JhV1RPOGAGw", "wHOZ8ppszSI", "HvumlX9trg0", "y6YS18A8hYY", "I1EbGRaQumk"}
SHORTS = {"INqxNO66Le0", "BRS8MRfNvZ4", "n-QS428KnS0", "IDMcx6lX9fM", "PTYSsjpW6NU"}
UPDATE_UNITS = 50


def seconds(iso: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def channel_videos(yt) -> list[dict]:
    uploads = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0][
        "contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=50, pageToken=token).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        token = r.get("nextPageToken")
        if not token:
            break
    out = []
    for i in range(0, len(ids), 50):
        out += yt.videos().list(part="snippet,status,contentDetails", id=",".join(ids[i:i + 50])).execute()["items"]
    return out


def update_body(v: dict) -> dict:
    st = v["status"]
    body = {k: st[k] for k in ("privacyStatus", "embeddable", "license", "publicStatsViewable") if k in st}
    body["selfDeclaredMadeForKids"] = st.get("madeForKids", False)
    body["containsSyntheticMedia"] = True
    return {"id": v["id"], "status": body}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--shorts", action="store_true", help="the 5 public Shorts instead of the 13")
    a = ap.parse_args()
    yt = yt_client()
    vids = channel_videos(yt)
    public = [v for v in vids if v["status"]["privacyStatus"] == "public"]
    long_form = [v for v in public if seconds(v["contentDetails"]["duration"]) > MIN_SECS]
    shorts = [v for v in public if v not in long_form]
    targets = sorted(shorts if a.shorts else long_form, key=lambda v: v["snippet"]["publishedAt"])
    wanted = SHORTS if a.shorts else EXPECTED
    other = [v for v in vids if v["status"]["privacyStatus"] != "public"]
    for n, v in enumerate(targets, 1):
        print(f"{n:2d}. https://youtu.be/{v['id']}  {v['contentDetails']['duration']:12s} {v['snippet']['publishedAt'][:10]}  {v['snippet']['title']}")
    print(f"\n{len(targets)} targets, {len(targets) * UPDATE_UNITS} quota units to write. Left alone: "
          f"{len(public) - len(targets)} other public, {len(other)} private or unlisted.")
    if not a.write:
        print("\nDRY RUN, nothing written. First request body:")
        print(json.dumps(update_body(targets[0]), indent=1))
        bad = [v["id"] for v in targets if set(update_body(v)["status"]) - {"privacyStatus", "embeddable", "license",
               "publicStatsViewable", "selfDeclaredMadeForKids", "containsSyntheticMedia"}
               or update_body(v)["status"]["privacyStatus"] != "public"]
        print("bodies keep public status:", not bad)
        return
    if {v["id"] for v in targets} != wanted:
        raise SystemExit(f"the public list no longer matches the {len(wanted)} Cole was shown: stopping, nothing written")
    done = {json.loads(l)["video_id"] for l in LOG.read_text().splitlines() if l.strip()} if LOG.exists() else set()
    for v in targets:
        if v["id"] in done:
            continue
        fresh = yt.videos().list(part="status", id=v["id"]).execute()["items"][0]
        if fresh["status"]["privacyStatus"] != "public":
            raise SystemExit(f"{v['id']} is no longer public: stopping before writing it")
        yt.videos().update(part="status", body=update_body(fresh)).execute()
        after = yt.videos().list(part="status", id=v["id"]).execute()["items"][0]["status"]
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"video_id": v["id"], "title": v["snippet"]["title"], "privacy_after": after["privacyStatus"],
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        print("set", v["id"], after["privacyStatus"], v["snippet"]["title"], flush=True)
        if after["privacyStatus"] != "public":
            raise SystemExit(f"{v['id']} is no longer public: stopping")


if __name__ == "__main__":
    main()
