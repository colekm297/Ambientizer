#!/usr/bin/env python3
"""migrate_media.py — staged offload of output/ media to the cloud bucket.

Policy, conservative on purpose:
  * Only files REFERENCED by a saved job (the app can serve them; orphans are a
    separate cleanup problem, not a migration one).
  * Only files >= --min-mb (default 25) — small images/thumbnails stay local.
  * Only files older than --min-age-days (default 14) — actively-changing files
    don't churn the bucket.
  * Upload + hash-verify EVERYTHING first; evict local copies only with --evict,
    and eviction re-verifies the local hash so a file changed since upload is
    never deleted.

    .venv/bin/python migrate_media.py                 # dry run: what would move
    .venv/bin/python migrate_media.py --apply         # upload (keeps local copies)
    .venv/bin/python migrate_media.py --apply --evict # upload then free the disk
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

from media_store import get_store  # noqa: E402


def referenced_paths() -> set[str]:
    refs = set()
    for jf in glob.glob(str(HERE / "saved_jobs" / "*.json")):
        try:
            d = json.load(open(jf))
        except Exception:
            continue

        def walk(o):
            if isinstance(o, str) and o.endswith((".mp4", ".wav", ".mp3", ".png", ".jpg", ".jpeg")):
                p = o if os.path.isabs(o) else str(HERE / o)
                refs.add(os.path.normpath(p))
            elif isinstance(o, dict):
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(d)
    return refs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--evict", action="store_true", help="delete local copies after verified upload")
    ap.add_argument("--min-mb", type=float, default=25)
    ap.add_argument("--min-age-days", type=float, default=14)
    ap.add_argument("--limit-gb", type=float, default=0, help="stop after this much uploaded")
    a = ap.parse_args()

    store = get_store()
    if a.apply and not store.enabled:
        sys.exit("R2 credentials not set in .env (R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / "
                 "R2_SECRET_ACCESS_KEY). Dry run works without them; --apply does not.")

    refs = referenced_paths()
    now = time.time()
    cands = []
    for p in sorted(refs):
        if not os.path.exists(p):
            continue
        st = os.stat(p)
        if st.st_size < a.min_mb * 1e6:
            continue
        if (now - st.st_mtime) < a.min_age_days * 86400:
            continue
        ent = store.lookup(p)
        if ent and ent.get("evicted"):
            continue                      # already offloaded
        cands.append((st.st_size, st.st_mtime, p, bool(ent)))

    cands.sort(key=lambda c: c[1])        # oldest first
    total = sum(c[0] for c in cands)
    print(f"{len(cands)} candidate files, {total/1e9:.1f} GB "
          f"(referenced, >={a.min_mb:.0f} MB, older than {a.min_age_days:.0f} d)\n")

    if not a.apply:
        for sz, mt, p, up in cands[:40]:
            tag = "uploaded, local copy remains" if up else ""
            print(f"  {sz/1e9:6.2f} GB  {time.strftime('%Y-%m-%d', time.localtime(mt))}  "
                  f"{os.path.basename(p)[:58]}  {tag}")
        if len(cands) > 40:
            print(f"  ... and {len(cands)-40} more")
        print("\nDry run. --apply uploads; add --evict to also free the disk.")
        return

    done = 0
    for i, (sz, mt, p, up) in enumerate(cands, 1):
        if not up:
            key = store.upload(p)
            if not key:
                print(f"  [{i}/{len(cands)}] FAILED verify: {os.path.basename(p)}", file=sys.stderr)
                continue
            done += sz
            print(f"  [{i}/{len(cands)}] up {sz/1e9:5.2f} GB  {os.path.basename(p)[:56]}")
        if a.evict:
            if store.evict(p):
                print(f"           evicted local copy")
        if a.limit_gb and done / 1e9 >= a.limit_gb:
            print(f"\nhit --limit-gb {a.limit_gb}, stopping")
            break

    print(f"\nUploaded {done/1e9:.1f} GB this run. Manifest: output/cloud_manifest.json")


if __name__ == "__main__":
    main()
