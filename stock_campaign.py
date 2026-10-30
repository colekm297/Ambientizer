#!/usr/bin/env python3
"""stock_campaign.py: spend ElevenLabs credits on a library of takes before the plan drops.

Cole, 2026-10-28: Pro downgrades to Creator on Nov 5 (19:53 PT) and the ~1.3M rolled-over credits
expire then. "Start the process to using all of or as much of the credits as we can before we lose them."

Each item in a wave file ({world, name, prompt, kind}) becomes one 10-min music_v2_5 take in the app,
titled "Stock · <world> · <name>". Two run at once (music concurrency on this account is 2, whatever the plan page says; retries cover
for the daily take and the learning lessons' TTS). Before each submit the remaining credits must stay
above RESERVE. After a take lands, Gemini screens it for defects Cole hates (drums, arpeggios, busy
lead, dead air) and the flag goes in the title, so he can skip duds.

Usage:
  .venv/bin/python stock_campaign.py data/stock/wave1.json [--parallel 4] [--reserve 120000]
Log: data/stock/<wave>.jsonl (one line per finished take). Re-running skips items already done.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
BASE = "http://127.0.0.1:5050"
lock = threading.Lock()
offload_lock = threading.Lock()
MODEL_ROTATION = ["music_v2", "music_v1", "music_v2", "music_v2_5"]
MODEL_TAG = {"music_v1": "v1", "music_v2": "v2", "music_v2_5": "v2.5"}
MIN_FREE_GB = 20

SCREEN = ("Listen to the AUDIO. This is a 10-minute ambient take meant as calm background music for focus "
          "and sleep. List only real problems, with times: drums or a beat, a busy arpeggio or sequencer, a "
          "lead melody that never rests, harsh or brassy tones, sudden loud swells, dead air or near silence, "
          "glitches. If there are none, say so. End with exactly one line 'FLAGS: none' or 'FLAGS: <2-4 words>'.")


_credits = {"t": 0.0, "v": None}
_gemini_ok = {"v": True}


def remaining() -> int:
    """Credits left. ElevenLabs rate-limits its subscription endpoint, so cache for 2 minutes and back off;
    on failure keep the last known value (each take costs ~9k, so a 2-minute-old number is close enough)."""
    if _credits["v"] is not None and time.time() - _credits["t"] < 120:
        return _credits["v"]
    for wait in (0, 20, 60, 120):
        time.sleep(wait)
        try:
            j = requests.get(f"{BASE}/api/credits", timeout=30).json()
            if "remaining" in j:
                _credits.update(t=time.time(), v=int(j["remaining"]))
                return _credits["v"]
        except Exception:
            pass
    if _credits["v"] is None:
        raise RuntimeError("credits unavailable")
    return _credits["v"]


def wav(jid: str) -> str:
    # The layer path is sometimes None on a completed job (seen 2026-10-28); the mixed raw output is
    # the same take, so fall back to it.
    j = json.load(open(HERE / "saved_jobs" / f"{jid}.json"))
    return (j["config"]["layers"][0].get("generated_audio_path") or j.get("raw_output_path")
            or j.get("audio_path") or j.get("output_path"))


def secs(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout
    return float(out or 0)


def screen(path: str) -> tuple[str, str]:
    from google import genai
    from google.genai import types
    mp3 = Path(path).with_suffix(".screen.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-ac", "1", "-b:a", "64k", str(mp3)], check=True)
    c = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    try:
        r = c.models.generate_content(model="gemini-4-argon", contents=[
            types.Part.from_bytes(data=mp3.read_bytes(), mime_type="audio/mpeg"), SCREEN])
        text = r.text or ""
    finally:
        mp3.unlink(missing_ok=True)
    m = re.search(r"FLAGS:\s*(.+)", text)
    return (m.group(1).strip() if m else "unscreened"), text


def run_one(item: dict, reserve: int, log: Path) -> None:
    try:
        _run_one(item, reserve, log)
    except Exception as e:
        print(f"ERROR {item['name']}: {e}", flush=True)


def _run_one(item: dict, reserve: int, log: Path) -> None:
    for attempt in (1, 2):
        with lock:
            # Wave 1 filled the disk on 2026-10-28 (each take leaves ~300 MB of WAVs across output/ and
            # generated_samples/), so stop well before it fills again.
            free_gb = shutil.disk_usage(HERE).free / 1e9
            if free_gb < MIN_FREE_GB:
                print(f"STOP disk: {free_gb:.1f} GB free, floor {MIN_FREE_GB} GB", flush=True)
                return
            left = remaining()
            if left - 12000 < reserve:
                print(f"STOP reserve: {left} left, reserve {reserve}", flush=True)
                return
        # The app caches by prompt, so a repeated prompt returns the old (possibly short or broken) take
        # for free instead of generating (the 2026-10-30 rerun of wave 1 got Oct 28's failures back).
        # A fresh take number on every attempt forces a new generation.
        prompt = f"{item['prompt']} Take {random.randint(100, 999)}."
        g = requests.post(f"{BASE}/api/generate", json={
            "prompt": prompt, "mode": "musical", "planner_mode": "raw", "music_length": 10, "duration": 10,
            "music_generation_mode": "text", "music_model": item["model"], "mastering": True}, timeout=60).json()
        jid = g.get("job_id")
        if not jid:
            print("SUBMIT FAILED", item["name"], g, flush=True)
            return
        # An app restart drops in-flight jobs ({"error": "Job not found"}); without this the run polled a dead
        # job for 20 minutes on 2026-10-30.
        while (s := requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()).get("status") not in (
                "complete", "error", "canceled") and "error" not in s:
            time.sleep(20)
        d = secs(wav(jid)) if s.get("status") == "complete" else 0
        if d >= 300:
            break
        print(f"SHORT/FAILED {item['name']} {jid} {s.get('status')} {d:.0f}s", flush=True)
        if s.get("status") == "complete":
            offload(jid)   # short takes stay in the library, but their WAVs shouldn't sit on the disk
    else:
        return
    flags, note = "unscreened", ""
    if _gemini_ok["v"]:
        try:
            flags, note = screen(wav(jid))
        except Exception as e:  # screening is a convenience; the take still counts
            note = str(e)[:200]
            if "402" in note or "RESOURCE_EXHAUSTED" in note:
                _gemini_ok["v"] = False   # Gemini prepay is out; stop calling it this run
                print("GEMINI OUT: screening off for this run", flush=True)
    tag = "" if flags.lower() in ("none", "unscreened") else f" [{flags}]"
    title = f"Stock · {item['world']} · {item['name']} · {MODEL_TAG[item['model']]}{tag}"[:120]
    requests.post(f"{BASE}/api/job/{jid}/meta", json={"title": title, "world": item["world"]}, timeout=30)
    rec = {**item, "job_id": jid, "secs": round(d), "flags": flags, "screen": note, "title": title,
           "done_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with lock:
        with open(log, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    print(f"DONE {jid} {round(d)}s {title}", flush=True)
    offload(jid)


def offload(jid: str) -> None:
    """Move the take's raw and mastered mixes to R2 (verified by sha256) and drop the local copies; the
    layer WAV in generated_samples stays, so the app's player and the flat mix work as before, and the
    app serves the evicted files from R2. Each take is ~308 MB as three WAVs; this leaves ~104 MB."""
    from media_store import get_store
    store = get_store()
    if not store.enabled:
        return
    j = json.load(open(HERE / "saved_jobs" / f"{jid}.json"))
    for p in {j.get("raw_output_path"), j.get("output_path"), j.get("audio_path")} - {None}:
        p = str(p if Path(p).is_absolute() else HERE / p)
        if not os.path.exists(p):
            continue
        with offload_lock:
            ok = store.upload(p) and store.evict(p)
        print(f"  {'offloaded' if ok else 'OFFLOAD FAILED (kept local)'} {Path(p).name}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wave")
    ap.add_argument("--parallel", type=int, default=2)  # ElevenLabs music allows 2 concurrent on this account (429 concurrent_limit_exceeded at 4)
    ap.add_argument("--reserve", type=int, default=120000)
    a = ap.parse_args()
    wave = Path(a.wave)
    items = json.loads(wave.read_text())
    log = wave.with_suffix(".jsonl")
    done = set()
    if log.exists():
        done = {(r["name"], r["prompt"]) for r in map(json.loads, log.read_text().splitlines())}
    todo = [i for i in items if (i["name"], i["prompt"]) not in done]
    # Cole, 2026-10-30: his best-rated takes came from v2, so mix models instead of all-v2.5, weighted to v2.
    # An item can pin its own "model"; the rest rotate v2, v1, v2, v2.5.
    for n, it in enumerate(todo):
        it.setdefault("model", MODEL_ROTATION[n % len(MODEL_ROTATION)])
    print(f"START {wave.name}: {len(todo)} to do, {remaining()} credits left, reserve {a.reserve}", flush=True)
    with ThreadPoolExecutor(a.parallel) as ex:
        for it in todo:
            ex.submit(run_one, it, a.reserve, log)
            time.sleep(5)
    print(f"WAVE DONE {wave.name}: {remaining()} credits left", flush=True)


if __name__ == "__main__":
    main()
