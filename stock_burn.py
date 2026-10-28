#!/usr/bin/env python3
"""stock_burn.py: final burn-down before the ElevenLabs downgrade lands (2026-11-05 19:53 PT).

Fires from launchd (com.cole.ambientizer-stock-burn) on Nov 4. Builds a wave sized to spend the credits
above RESERVE: prompts from Cole's rated takes (3 stars weighted heaviest) and unflagged stock takes,
each with a fresh "Take N." so the app's prompt cache can't replay a file. Then runs stock_campaign.py
2 at a time (the account's music concurrency limit). Does nothing on any other date, so the yearly calendar trigger is harmless.
"""
import datetime as dt, json, random, subprocess, sys
from pathlib import Path
import requests
HERE = Path(__file__).resolve().parent; BASE = "http://127.0.0.1:5050"
RESERVE = 30000; PER_TAKE = 9500
if dt.date.today() != dt.date(2026, 11, 4) and "--force" not in sys.argv:
    sys.exit(0)
left = int(requests.get(f"{BASE}/api/credits", timeout=30).json()["remaining"])
n = max(0, (left - RESERVE) // PER_TAKE)
print("credits", left, "takes", n, flush=True)
if not n:
    sys.exit(0)
hist = requests.get(f"{BASE}/api/history", timeout=60).json()
hist = hist if isinstance(hist, list) else hist.get("jobs") or hist.get("history") or []
pool = []
for j in hist:
    r = j.get("rating") or 0
    t = j.get("title") or ""
    if j.get("status") != "complete" or "[" in t or "ignore" in t.lower() or "BUG" in t:
        continue
    w = {3: 6, 2: 3, 1: 0}.get(r, 1 if t.startswith("Stock ·") else 0)
    if not w:
        continue
    try:
        p = json.load(open(HERE / "saved_jobs" / f"{j['job_id']}.json"))["config"]["layers"][0]["elevenlabs_prompt"]
    except Exception:
        continue
    pool.append((w, j.get("world") or "Mixed", t.replace("Stock · ", "").split(" · ")[-1][:40] or "take", p))
if not pool:
    sys.exit("no prompts")
random.seed(1104)
picks = random.choices(pool, weights=[x[0] for x in pool], k=n)
items = [{"world": w, "name": f"{name} (burn {i+1})", "prompt": f"{p} Take {20+i}.", "kind": "burn"}
         for i, (_, w, name, p) in enumerate(picks)]
wave = HERE / "data/stock/burn_2026-11-04.json"
wave.write_text(json.dumps(items, indent=1))
subprocess.run([str(HERE / ".venv/bin/python"), str(HERE / "stock_campaign.py"), str(wave),
                "--parallel", "2", "--reserve", str(RESERVE)], cwd=HERE)
