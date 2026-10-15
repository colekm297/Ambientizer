#!/usr/bin/env python3
"""One new song experiment a day for Cole to rate in the app (his ask, 2026-10-14).

Metric: stars Cole gives these takes per week. Each morning this:
  1. reads every past daily experiment and the rating Cole gave it (live from saved_jobs),
     plus his 3-star prompts and the house rules in docs/HOW-A-TRACK-IS-MADE.md;
  2. asks Claude for ONE new experiment (world, title, what it tests, prompt) that learns
     from what scored and tries something not tried recently;
  3. generates it the way Cole makes tracks: raw prompt, text mode, music_v2, 10 minutes;
  4. titles it in the app ("<World> · Daily · <title>") so it sits at the top of his list;
  5. appends to data/daily_experiments.jsonl and rewrites docs/DAILY-EXPERIMENTS.md
     (per-week star totals).
Nothing is published. Run by launchd com.cole.ambientizer-daily.
"""
import datetime as dt
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import anthropic
import requests

HERE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:5050"
LEDGER = HERE / "data" / "daily_experiments.jsonl"
REPORT = HERE / "docs" / "DAILY-EXPERIMENTS.md"
MIN_CREDITS = 100_000  # leave headroom on ElevenLabs before spending ~18k on a take


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def load_env():
    for line in (HERE / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def job_json(job_id):
    p = HERE / "saved_jobs" / f"{job_id}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def ledger():
    if not LEDGER.exists():
        return []
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    for r in rows:  # ratings are live: Cole rates in the app whenever he listens
        r["stars"] = int(job_json(r["job_id"]).get("rating", 0) or 0)
    return rows


def coles_best_prompts():
    out = []
    for p in glob.glob(str(HERE / "saved_jobs" / "*.json")):
        try:
            d = json.loads(Path(p).read_text())
        except Exception:
            continue
        if (d.get("rating") or 0) >= 3 and d.get("prompt"):
            out.append(d["prompt"])
    return out[:8]


def write_report(rows):
    weeks = {}
    for r in rows:
        y, w, _ = dt.date.fromisoformat(r["date"]).isocalendar()
        weeks.setdefault(f"{y}-W{w:02d}", []).append(r)
    lines = ["# Daily experiments", "",
             "One generated take a day for Cole to rate in the app. The number that matters is stars per week.",
             "Written by `daily_experiment.py`; ratings are read live from the app.", "",
             "| Week | Takes | Rated | Stars | Avg of rated |", "|---|---|---|---|---|"]
    for wk in sorted(weeks, reverse=True):
        rs = weeks[wk]; rated = [r for r in rs if r["stars"] > 0]
        avg = f"{sum(r['stars'] for r in rated)/len(rated):.1f}" if rated else "-"
        lines.append(f"| {wk} | {len(rs)} | {len(rated)} | {sum(r['stars'] for r in rs)} | {avg} |")
    lines += ["", "## Log", "", "| Date | World | Title | Testing | Stars |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["date"], reverse=True):
        lines.append(f"| {r['date']} | {r['world']} | {r['title']} | {r['testing']} | {'★'*r['stars'] or '-'} |")
    REPORT.write_text("\n".join(lines) + "\n")


SCHEMA = {
    "type": "object",
    "properties": {
        "world": {"type": "string", "description": "Story world, e.g. Dune, Odyssey, Hail Mary, Interstellar, or a plain atmosphere name if no IP"},
        "title": {"type": "string", "description": "Short plain title Cole will see in his list, under 40 characters, no jargon"},
        "testing": {"type": "string", "description": "One plain sentence: what this experiment tests that recent ones did not"},
        "prompt": {"type": "string", "description": "The full ElevenLabs music prompt, written in the shape of Cole's best prompts"},
    },
    "required": ["world", "title", "testing", "prompt"],
    "additionalProperties": False,
}


def design(rows):
    guide = (HERE / "docs" / "HOW-A-TRACK-IS-MADE.md").read_text()
    history = [{k: r[k] for k in ("date", "world", "title", "testing", "stars")} for r in rows[-30:]]
    system = (
        "You design one experimental ambient track a day for The Space of Sound, a YouTube channel of one-hour "
        "ambient videos set in story worlds people love. Cole, the owner, rates each take 0-3 stars in his app; "
        "your goal is the most stars per week. Touchstones for the sound: Brian Eno, Stars of the Lid, Hiroshi "
        "Yoshimura's Music for Nine Postcards. Rules he has given: write from a specific, well-known moment, not "
        "an obscure setting word (nobody knows what a sietch is); percussion-heavy is bad, at most one soft, "
        "distant pulse far back in the mix; no stitched or multi-part structures; boring takes that go nowhere "
        "fail, so give each take a hook and a journey across its 10 minutes; nothing dark or dread-filled under "
        "a hopeful story; plain titles. Unrated takes (0 stars) may simply not have been heard yet. Learn from "
        "what scored, keep what worked, and vary one thing at a time so the ratings teach something: world, "
        "instrument palette, tempo, density, the hook. Also try general YouTube ambient ideas that are not tied "
        "to an IP (rain on a window, a train at night) when the log suggests it is worth testing.")
    user = (
        f"House guide (read the 3-star pattern section closely):\n\n{guide}\n\n"
        f"Cole's 3-star prompts, verbatim:\n\n" + "\n\n---\n\n".join(coles_best_prompts()) +
        f"\n\nDaily experiment log so far (newest last):\n{json.dumps(history, indent=1)}\n\n"
        f"Today is {dt.date.today().isoformat()}. Design today's one experiment.")
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-opus-5", max_tokens=16000, system=system,
        messages=[{"role": "user", "content": user}],
        extra_body={"output_config": {"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
                    "thinking": {"type": "adaptive"}},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("design refused")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def generated_seconds(job_id):
    d = job_json(job_id)
    p = (d.get("config") or {}).get("layers", [{}])[0].get("generated_audio_path")
    if not p or not os.path.exists(p):
        return 0.0
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def generate(prompt):
    g = requests.post(f"{BASE}/api/generate", json={
        "prompt": prompt, "mode": "musical", "planner_mode": "raw", "music_length": 10, "duration": 10,
        "music_generation_mode": "text", "music_model": "music_v2", "mastering": True}, timeout=60).json()
    jid = g["job_id"]
    while True:
        s = requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()
        if s.get("status") in ("complete", "error", "canceled"):
            return jid, s.get("status")
        time.sleep(15)


def main():
    load_env()
    os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")
    today = dt.date.today().isoformat()
    rows = ledger()
    if any(r["date"] == today for r in rows) and "--force" not in sys.argv:
        log("already ran today"); write_report(rows); return
    cr = requests.get(f"{BASE}/api/credits", timeout=30).json()
    if cr.get("remaining", 0) < MIN_CREDITS:
        log(f"skipping: ElevenLabs credits low ({cr.get('remaining')})"); return
    exp = design(rows)
    log(f"designed: {exp['world']} / {exp['title']} / {exp['testing']}")
    for attempt in (1, 2):
        jid, status = generate(exp["prompt"])
        secs = generated_seconds(jid)
        log(f"attempt {attempt}: job {jid} {status}, {secs:.0f} s")
        if status == "complete" and secs >= 480:
            break
    else:
        log("take came back short twice; logging it anyway")
    requests.post(f"{BASE}/api/job/{jid}/meta", json={"title": f"Daily · {exp['title']}", "world": exp["world"]}, timeout=30)
    rec = {"date": today, "job_id": jid, "world": exp["world"], "title": exp["title"],
           "testing": exp["testing"], "prompt": exp["prompt"], "seconds": round(secs)}
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    rows = ledger(); write_report(rows)
    log("done")


if __name__ == "__main__":
    main()
