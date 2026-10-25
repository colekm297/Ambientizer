"""Model upgrade test 2026-10-24: does music_v2_5 (ElevenLabs' newest) give 10-minute takes now? Two world-first
Dune prompts, 10 min requested, through the app. Graded against the Empyreal reference like the others."""
import re, sys, time, json, requests
from pathlib import Path
sys.argv = ["x", "output/_competitor/empyreal/prompts_world.md", "v25"]
exec(open("_gen_empyreal_takes.py").read().split("res = []")[0])
res = []
for p in prompts[:2]:
    g = requests.post(f"{BASE}/api/generate", json={"prompt": p["prompt"], "mode": "musical", "planner_mode": "raw",
        "music_length": 10, "duration": 10, "music_generation_mode": "text", "music_model": "music_v2_5",
        "mastering": True}, timeout=60).json()
    jid = g["job_id"]
    while (s := requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()).get("status") not in ("complete", "error", "canceled"):
        time.sleep(15)
    d = secs(wav(jid)) if s.get("status") == "complete" else 0
    print(p["name"], "v2.5", jid, s.get("status"), round(d), s.get("error"), flush=True)
    requests.post(f"{BASE}/api/job/{jid}/meta", json={"title": f"Dune · Music v2.5 · {p['name']}", "world": "Dune"}, timeout=30)
    try: crit = grade(wav(jid), p["name"] + " v25")
    except Exception as e: crit = f"grade failed: {e}"
    m = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)", crit)
    res.append({"name": p["name"] + " v2.5", "job": jid, "secs": round(d), "score": float(m.group(1)) if m else None, "critique": crit})
    print(crit, flush=True); (OUT / "takes_v25.json").write_text(json.dumps(res, indent=1))
print("DONE", flush=True)
