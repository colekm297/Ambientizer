#!/usr/bin/env python3
"""offload_release.py — push a finished release to R2 the moment it is built.

Why this exists: `migrate_media.py` only offloads files that some
`saved_jobs/*.json` references, and only after they are 14 days old. Release
masters live in `output/release/<name>/` and are referenced by no job, so they
never qualify. That gap is how the Aug 9 2026 Sirens masters disappeared from
local disk with no cloud copy (the v2 was recovered on Aug 23 only because a
session had pushed it by hand).

Rule: every release build ends with

    python offload_release.py <name> --apply

Idempotent: a file whose sha256 already matches the manifest entry is skipped,
so re-running after a rebuild uploads only what changed. Uses
`MediaStore.upload(verify=True)` — the object is hashed after upload and never
recorded in the manifest unless the round trip matches.

    python offload_release.py                 # dry run, every release
    python offload_release.py fairwind        # dry run, one release
    python offload_release.py fairwind --apply
    python offload_release.py --check         # which releases are NOT fully in R2
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

from media_store import _sha256, get_store  # noqa: E402

RELEASE_ROOT = HERE / "output" / "release"
# Logs and scratch never need a cloud copy.
SKIP_SUFFIXES = (".log", ".tmp", ".DS_Store")


def release_files(name: str) -> list[Path]:
    root = RELEASE_ROOT / name
    if not root.is_dir():
        sys.exit(f"no such release: {root}")
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and not p.name.endswith(SKIP_SUFFIXES))


def status(store, path: Path) -> str:
    """'ok' (in R2, hash matches), 'stale' (in R2, local differs), 'missing'."""
    ent = store.lookup(str(path))
    if not ent:
        return "missing"
    return "ok" if ent.get("sha256") == _sha256(str(path)) else "stale"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name", nargs="?", help="release directory name under output/release/")
    ap.add_argument("--apply", action="store_true", help="upload; default is a dry run")
    ap.add_argument("--check", action="store_true", help="report releases not fully offloaded")
    a = ap.parse_args()

    store = get_store()
    names = [a.name] if a.name else sorted(
        p.name for p in RELEASE_ROOT.iterdir() if p.is_dir())
    if not names:
        sys.exit("no releases under output/release/")

    if a.apply and not store.enabled:
        sys.exit("R2 credentials not set in .env; dry run and --check work without them.")

    incomplete = []
    for name in names:
        files = release_files(name)
        rows = [(p, status(store, p), p.stat().st_size) for p in files]
        todo = [r for r in rows if r[1] != "ok"]
        total = sum(r[2] for r in rows)
        print(f"{name}: {len(files)} files, {total/1e9:.2f} GB, "
              f"{len(rows)-len(todo)} in R2, {len(todo)} to upload")
        for p, st, sz in rows:
            print(f"  {st:8s} {sz/1e9:6.2f} GB  {p.relative_to(RELEASE_ROOT / name)}")
        if todo:
            incomplete.append(name)
        if not a.apply or not todo:
            continue
        for p, st, sz in todo:
            print(f"  uploading {p.name} ({sz/1e9:.2f} GB) ...", flush=True)
            key = store.upload(str(p), verify=True)
            if key is None:
                sys.exit(f"UPLOAD FAILED verification: {p} — manifest untouched, stop here")
            print(f"  verified {key}", flush=True)
        # Re-check so the exit status reflects reality, not intent.
        left = [p for p in files if status(store, p) != "ok"]
        if left:
            sys.exit(f"{name}: {len(left)} file(s) still not in R2 after apply")
        incomplete.remove(name)
        print(f"{name}: fully offloaded", flush=True)

    if a.check:
        if incomplete:
            print(f"\nNOT fully offloaded: {', '.join(incomplete)}")
            sys.exit(1)
        print("\nall releases fully offloaded")
    elif not a.apply and incomplete:
        print("\nDry run. Re-run with --apply to upload.")


if __name__ == "__main__":
    main()
