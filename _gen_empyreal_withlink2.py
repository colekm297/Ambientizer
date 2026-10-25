"""Rerun after the fix that keeps the typed world in reference-driven prompts, on music_v2_5. Cole 2026-10-24: "use those prompts but PUT IN THE LINK where it literally accepts links".
Same four world-first Dune prompts, sent the way the UI does with a reference link: planner_mode claude,
reference_url + the saved /api/analyze-reference result. Waits for the world-first run to finish."""
import re, sys, time, json, requests
from pathlib import Path
OUT = Path("output/_competitor/empyreal"); BASE = "http://127.0.0.1:5050"
REF = "https://www.youtube.com/watch?v=3SnFFdHVvdo"
pass
sys.argv = ["x", str(OUT / "prompts_world.md"), "link2"]
exec(open("_gen_empyreal_takes.py").read().split("res = []")[0])
analysis = json.loads((OUT / "linkpath_analysis.json").read_text())["analysis"]
res = []
for p in prompts:
    g = requests.post(f"{BASE}/api/generate", json={"prompt": p["prompt"], "mode": "musical", "planner_mode": "claude",
        "reference_url": REF, "reference_analysis": analysis, "music_length": 10, "duration": 10,
        "music_generation_mode": "text", "music_model": "music_v2_5", "mastering": True}, timeout=60).json()
    jid = g["job_id"]
    while (s := requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()).get("status") not in ("complete", "error", "canceled"):
        time.sleep(15)
    sent = json.load(open(f"saved_jobs/{jid}.json"))["config"]["layers"][0].get("elevenlabs_prompt", "") if s.get("status") == "complete" else ""
    print(p["name"], "+link", jid, s.get("status"), "\n  SENT:", sent[:600], flush=True)
    requests.post(f"{BASE}/api/job/{jid}/meta", json={"title": f"Dune + link (fixed) · {p['name']}", "world": "Dune"}, timeout=30)
    try: crit = grade(wav(jid), p["name"] + " link")
    except Exception as e: crit = f"grade failed: {e}"
    m = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)", crit)
    res.append({"name": p["name"] + " +link", "job": jid, "score": float(m.group(1)) if m else None, "sent": sent, "critique": crit})
    print(crit, flush=True); (OUT / "takes_withlink2.json").write_text(json.dumps(res, indent=1))
print("DONE", flush=True)
