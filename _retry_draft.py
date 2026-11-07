#!/usr/bin/env python3
"""_retry_draft.py: upload a draft whose hour exported but whose upload failed, without exporting it again.

Private, into "Drafts to review", then the same offload and log row as the daily job. Uses the title, description,
tags and thumbnail the failed run saved on the job.

Usage: .venv/bin/python _retry_draft.py <job_id>
"""
import json
import sys
import time
from pathlib import Path

import requests

import drafts_daily as d


def main(jid):
    j = json.load(open(d.HERE / "saved_jobs" / f"{jid}.json"))
    if not Path(j["visual_video_path"]).exists():
        sys.exit(f"no local hour: {j['visual_video_path']}")
    rec = {"job_id": jid, "rating": j.get("rating"), "take_title": j.get("title") or j.get("prompt", "")[:80],
           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    r = d.jget(requests.post(f"{d.BASE}/api/youtube/upload/{jid}", json={
        "title": j["yt_title"], "description": j["yt_description"], "tags": j["yt_tags"], "privacy": "private"}, timeout=60))
    if r.get("error"):
        sys.exit(f"upload start failed: {r}")
    t0 = time.time()
    while time.time() - t0 < 3 * 60 * 60:
        s = d.jget(requests.get(f"{d.BASE}/api/youtube/upload-status/{jid}", timeout=30))
        if s.get("status") == "done":
            break
        if s.get("status") == "error":
            sys.exit(f"upload failed: {s.get('message')}")
        time.sleep(10)
    else:
        sys.exit("upload timed out")
    done = json.load(open(d.HERE / "saved_jobs" / f"{jid}.json"))
    rec.update(title=j["yt_title"], video_id=done.get("youtube_video_id"), url=s.get("youtube_url"), status="private")
    if rec["video_id"]:
        yt = d.yt_client()
        yt.playlistItems().insert(part="snippet", body={"snippet": {
            "playlistId": d.playlist_id(yt), "resourceId": {"kind": "youtube#video", "videoId": rec["video_id"]}}}).execute()
    try:
        rec["preview"] = d.cut_preview(done["visual_video_path"], jid)
    except Exception as e:
        print(f"preview failed: {str(e)[:200]}", flush=True)
    d.offload(jid)
    with open(d.LOG, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
