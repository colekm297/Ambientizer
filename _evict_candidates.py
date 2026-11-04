#!/usr/bin/env python3
"""_evict_candidates.py: which local files over 100 MB could leave the Mac, without deleting anything.

Read only (head_object plus local hashing). "Verified" means the R2 object's size and ETag match the local bytes.
For uploads through boto3 the ETag is the md5 of the 8 MB part md5s, so that proves the bytes without a download.
The sha256 in the object's metadata doesn't: it's computed locally before the upload. YouTube never counts,
because it re-encodes. Takes in the draft queue are held back, since drafts_daily reads their audio locally.

Usage: .venv/bin/python _evict_candidates.py    writes data/offload/candidates-<date>.jsonl, prints totals
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path

from botocore.exceptions import ClientError
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
os.chdir(HERE)
import drafts_daily  # noqa: E402
from media_store import get_store  # noqa: E402

MIN_BYTES = 100_000_000
RECENT_SECS = 2 * 86400


def etag_of(path: str, part: int = 8 * 1024 * 1024) -> str:
    parts = []
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(part), b""):
            parts.append(hashlib.md5(b).digest())
    if len(parts) == 1:
        return parts[0].hex()
    return f"{hashlib.md5(b''.join(parts)).hexdigest()}-{len(parts)}"


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)


def main():
    s = get_store()
    queue = drafts_daily.queue()
    held = set()
    for p in queue:
        for v in strings(json.load(open(HERE / "saved_jobs" / f"{p['job_id']}.json"))):
            if "/" in v and len(v) < 500:
                held.add(os.path.abspath(v))
    rows, now = [], time.time()
    for root in ("output", "generated_samples", "inputs", "data"):
        for d, _, fs in os.walk(root):
            for f in fs:
                p = os.path.join(d, f)
                if os.path.islink(p) or not os.path.isfile(p):
                    continue
                z = os.path.getsize(p)
                if z <= MIN_BYTES:
                    continue
                r = {"path": p, "size": z, "needed": os.path.abspath(p) in held,
                     "recent": now - os.path.getmtime(p) < RECENT_SECS}
                try:
                    h = s.client.head_object(Bucket=s.bucket, Key=s.relkey(p))
                except ClientError:
                    r["r2"] = "absent"
                else:
                    ok = h["ContentLength"] == z and h["ETag"].strip('"') == etag_of(p)
                    r["r2"] = "verified" if ok else "differs"
                rows.append(r)
    out = HERE / "data" / "offload" / f"candidates-{time.strftime('%F')}.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    gb, n = Counter(), Counter()
    for r in rows:
        k = r["r2"] + (", queue" if r["needed"] else "") + (", recent" if r["recent"] else "")
        gb[k] += r["size"]
        n[k] += 1
    for k, v in gb.most_common():
        print(f"{v / 1e9:7.1f} GB  {n[k]:4d} files  {k}")
    print(f"{sum(gb.values()) / 1e9:7.1f} GB  {sum(n.values()):4d} files  total; queue {len(queue)} takes; {out}")


if __name__ == "__main__":
    main()
