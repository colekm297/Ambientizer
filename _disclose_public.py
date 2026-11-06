#!/usr/bin/env python3
"""_disclose_public.py: set YouTube's AI disclosure (status.containsSyntheticMedia) on the channel's public long-form videos.

YouTube Help requires it when AI "creates music that's the main focus of the video". New uploads already set
it (youtube_publisher.py); this covers what went up before that. Only that one field changes: every other
status field is sent back at its current value, read again just before each write. Acts only on the 13 IDs Cole
was shown (videos published since, like Sietch, were labeled at upload and stay untouched). Refuses to write if any
of them isn't public, and stops at the first video whose snippet, status or contentDetails changed beyond the label.
A rerun skips videos already logged. videos.list never returns the field, so the proof is the public watch page: a labeled video carries
howThisWasMadeSectionViewModel, an unlabeled one doesn't (seen 2026-11-06 on Sietch and two unlabeled videos).

Usage: .venv/bin/python _disclose_public.py            dry run of the 13: prints the list and the exact request bodies
       .venv/bin/python _disclose_public.py --write    only after Cole's yes
       Add --only ID to write one of them, the first-video check.
       Add --shorts to either to act on the 5 public Shorts INSTEAD of the 13, a separate yes.
Log: data/disclose_public.jsonl (one line per write).
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests

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


def public_label(video_id: str) -> bool:
    r = requests.get(f"https://www.youtube.com/watch?v={video_id}", timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36",
        "Accept-Language": "en-US"})
    return "howThisWasMadeSectionViewModel" in r.text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--shorts", action="store_true", help="the 5 public Shorts instead of the 13")
    ap.add_argument("--only", help="write just this one video")
    a = ap.parse_args()
    yt = yt_client()
    vids = channel_videos(yt)
    public = [v for v in vids if v["status"]["privacyStatus"] == "public"]
    long_form = [v for v in public if seconds(v["contentDetails"]["duration"]) > MIN_SECS]
    shorts = [v for v in public if v not in long_form]
    wanted = SHORTS if a.shorts else EXPECTED
    targets = sorted((v for v in public if v["id"] in wanted), key=lambda v: v["snippet"]["publishedAt"])
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
        raise SystemExit(f"not all {len(wanted)} videos Cole was shown are public: stopping, nothing written")
    if a.only and a.only not in wanted:
        raise SystemExit(f"{a.only} isn't one of the {len(wanted)} Cole was shown: stopping, nothing written")
    done = {json.loads(l)["video_id"] for l in LOG.read_text().splitlines() if l.strip()} if LOG.exists() else set()
    for v in targets:
        if v["id"] in done or (a.only and v["id"] != a.only):
            continue
        parts = "snippet,status,contentDetails"
        fresh = yt.videos().list(part=parts, id=v["id"]).execute()["items"][0]
        if fresh["status"]["privacyStatus"] != "public":
            raise SystemExit(f"{v['id']} is no longer public: stopping before writing it")
        yt.videos().update(part="status", body=update_body(fresh)).execute()
        full = yt.videos().list(part=parts, id=v["id"]).execute()["items"][0]
        after = full["status"]
        for _ in range(12):
            shown = public_label(v["id"])
            if shown:
                break
            time.sleep(10)
        changed = [f"{part}.{k}: {fresh[part].get(k)!r} -> {full[part].get(k)!r}" for part in parts.split(",") for k in set(fresh[part]) | set(full[part])
                   if fresh[part].get(k) != full[part].get(k) and k != "containsSyntheticMedia"]
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"video_id": v["id"], "title": v["snippet"]["title"], "privacy_after": after["privacyStatus"],
                                 "public_label": shown, "changed": changed,
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
        print("set", v["id"], after["privacyStatus"], "label:", shown, "changed:", changed, v["snippet"]["title"], flush=True)
        if not shown:
            raise SystemExit(f"{v['id']}: no label on the public page after 2 minutes: stopping")
        if changed:
            raise SystemExit(f"{v['id']} changed beyond the label: {changed}: stopping")
        if after["privacyStatus"] != "public":
            raise SystemExit(f"{v['id']} is no longer public: stopping")


if __name__ == "__main__":
    main()
