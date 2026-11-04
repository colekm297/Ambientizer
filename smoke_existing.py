#!/usr/bin/env python3
"""smoke_existing.py: do the paths existing songs use still work? Run BEFORE restarting the app, and again after.

Added 2026-11-04, when a media_store change dropped a method and a test of only the new code passed, so songs
on R2 broke until the next restart. Read only. Before a restart it checks the code on disk: web/app.py parses,
and an evicted take resolves to a signed R2 URL that serves real bytes. If the app is up, it also checks history,
a local take and an evicted take through the running app, which is the old code until you restart.

Usage: .venv/bin/python smoke_existing.py    exits 1 on any failure
"""
from __future__ import annotations

import ast
import glob
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
load_dotenv(HERE / ".env")
from media_store import get_store  # noqa: E402

BASE = "http://127.0.0.1:5050"
fails = []


def check(name: str, ok: bool, detail="") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name} {detail}", flush=True)
    if not ok:
        fails.append(name)


def main():
    ast.parse(Path("web/app.py").read_text())
    store = get_store()
    local = evicted = None
    for f in glob.glob("saved_jobs/*.json"):
        j = json.load(open(f))
        p = j.get("audio_path") or j.get("output_path")
        if not p or j.get("status") != "complete":
            continue
        if os.path.exists(p):
            local = local or Path(f).stem
        elif store.lookup(p):
            evicted = evicted or (Path(f).stem, p)
        if local and evicted:
            break
    check("found a local and an evicted take", bool(local and evicted))
    if evicted:
        url = store.presign_for_path(evicted[1])
        r = requests.get(url, headers={"Range": "bytes=0-1023"}, timeout=30) if url else None
        check("evicted take: signed R2 URL serves bytes", bool(r is not None and r.status_code == 206 and r.content))
    try:
        up = requests.get(f"{BASE}/api/history", timeout=60).status_code == 200
    except requests.RequestException:
        print("app not reachable: skipped the running-app checks", flush=True)
        up = False
    if up:
        for name, jid in (("local", local), ("evicted", evicted and evicted[0])):
            if jid:
                r = requests.get(f"{BASE}/api/audio/{jid}", headers={"Range": "bytes=0-1023"},
                                 allow_redirects=False, stream=True, timeout=120)
                check(f"app plays {name} take {jid}", r.status_code in (200, 206, 302), str(r.status_code))
                r.close()
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
