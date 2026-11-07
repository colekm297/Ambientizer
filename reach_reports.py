#!/usr/bin/env python3
"""reach_reports.py: per-video thumbnail impressions and CTR from YouTube's Reporting API, so nobody has to read Studio.

Cole's yes, inbox 43, 2026-11-06: one read-only daily job, channel_reach_basic_a1. Reports land about 48 hours after
the job was created, with 30 days of history a couple of days later. YouTube keeps history reports for 30 days and
daily ones for 60, so the raw CSVs stay in data/reach/raw. A report restated for the same period arrives under a new
id: the newest createTime wins. CSV columns are read from the header, as YouTube asks.

Only reads. It never creates or changes a job. post_learning.py pull calls sync() every Monday.

Usage: .venv/bin/python reach_reports.py    download anything new and print data/reach.json's totals
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "reach" / "raw"
OUT = HERE / "data" / "reach.json"
API = "https://youtubereporting.googleapis.com/v1"
JOB = "f8986e22-8ca8-44d2-9637-0edab3a1bf96"
NEEDED = {"date", "video_id", "video_thumbnail_impressions", "video_thumbnail_impressions_ctr"}
WINDOWS = {"last_7d": 7, "last_28d": 28}


def list_reports(token: str) -> list[dict]:
    out, page = [], None
    while True:
        r = requests.get(f"{API}/jobs/{JOB}/reports", headers={"Authorization": f"Bearer {token}"},
                         params={"pageToken": page} if page else {}, timeout=60)
        r.raise_for_status()
        out += r.json().get("reports", [])
        page = r.json().get("nextPageToken")
        if not page:
            return out


def raw_path(rep: dict) -> Path:
    return RAW / f"{rep['startTime'][:10]}_{rep['endTime'][:10]}_{re.sub(r'[^0-9]', '', rep['createTime'])}.csv"


def download_new(token: str) -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    n = 0
    for rep in list_reports(token):
        path = raw_path(rep)
        if path.exists():
            continue
        r = requests.get(rep["downloadUrl"], headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "gzip"}, timeout=300)
        r.raise_for_status()
        path.write_text(r.text)
        n += 1
    return n


def parse(text: str) -> list[dict]:
    """Rows as date, video_id, impressions, clicks. The docs call CTR clicks divided by impressions, so a ratio;
    a real value over 1 means that reading is wrong, and failing beats publishing numbers 100 times off."""
    reader = csv.DictReader(io.StringIO(text))
    missing = NEEDED - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"reach report is missing columns {sorted(missing)}: has {reader.fieldnames}")
    rows = []
    for row in reader:
        imp = int(float(row["video_thumbnail_impressions"] or 0))
        ctr = float(row["video_thumbnail_impressions_ctr"] or 0)
        if ctr > 1:
            raise ValueError(f"CTR {ctr} on {row['video_id']} isn't a ratio: check the unit before trusting this feed")
        rows.append({"date": row["date"], "video_id": row["video_id"], "impressions": imp, "clicks": imp * ctr})
    return rows


def current_files() -> list[Path]:
    """For each period, the file with the newest createTime."""
    newest: dict[str, Path] = {}
    for path in sorted(RAW.glob("*.csv")):
        start, end, created = path.stem.split("_")
        key = f"{start}_{end}"
        if key not in newest or created > newest[key].stem.split("_")[2]:
            newest[key] = path
    return list(newest.values())


def total(rows: list[dict]) -> dict:
    imp = sum(r["impressions"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    return {"impressions": imp, "ctr_pct": round(100 * clicks / imp, 2) if imp else None}


def aggregate(rows: list[dict]) -> dict:
    """Per video: all the days held, then trailing windows ending on the newest day in the data."""
    if not rows:
        return {"first_date": None, "last_date": None, "videos": {}}
    last = max(r["date"] for r in rows)
    end = dt.datetime.strptime(last, "%Y%m%d").date()
    cutoff = {name: (end - dt.timedelta(days=days - 1)).strftime("%Y%m%d") for name, days in WINDOWS.items()}
    videos = {}
    for vid in {r["video_id"] for r in rows}:
        mine = [r for r in rows if r["video_id"] == vid]
        videos[vid] = {"all": total(mine), **{name: total([r for r in mine if r["date"] >= c]) for name, c in cutoff.items()},
                       "days": len({r["date"] for r in mine})}
    return {"first_date": min(r["date"] for r in rows), "last_date": last, "videos": videos}


def sync(creds) -> dict:
    """Download anything new, rebuild data/reach.json, return it."""
    from google.auth.transport.requests import Request
    if not creds.valid:
        creds.refresh(Request())
    new = download_new(creds.token)
    rows = [r for path in current_files() for r in parse(path.read_text())]
    out = {"pulled_at": dt.datetime.now().isoformat(timespec="seconds"), "new_reports": new, **aggregate(rows)}
    OUT.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    import yt_analytics_pull as y
    res = sync(y.get_credentials())
    print(f"{res['new_reports']} new reports, {res['first_date']} to {res['last_date']}, {len(res['videos'])} videos")
    for vid, v in sorted(res["videos"].items(), key=lambda kv: -kv[1]["all"]["impressions"]):
        print(f"  {vid}  {v['all']['impressions']:>7} imp  {v['all']['ctr_pct']}%  last 7d {v['last_7d']['ctr_pct']}%")
