"""Cole 2026-10-24: "can we use the thing that generates based on the audio... the link approach".
Runs the app's own link path: /api/analyze-reference on the YouTube URL, then /api/generate with the
suggested prompt plus the analysis (music_v2, 10 min). One take, titled for comparison in the app."""
import json, time, requests
BASE = "http://127.0.0.1:5050"; REF = "https://www.youtube.com/watch?v=3SnFFdHVvdo"
a = requests.post(f"{BASE}/api/analyze-reference", json={"url": REF, "start_sec": 0, "end_sec": 600}, timeout=900).json()
json.dump(a, open("output/_competitor/empyreal/linkpath_analysis.json", "w"), indent=1)
prompt = a.get("suggested_prompt") or a.get("prompt")
print("keys", list(a), "\nPROMPT", prompt, flush=True)
g = requests.post(f"{BASE}/api/generate", json={"prompt": prompt, "mode": "musical", "planner_mode": "raw",
    "reference_url": REF, "reference_analysis": a.get("analysis"), "music_length": 10, "duration": 10,
    "music_generation_mode": "text", "music_model": "music_v2", "mastering": True}, timeout=60).json()
jid = g["job_id"]
while (s := requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()).get("status") not in ("complete", "error", "canceled"):
    time.sleep(15)
requests.post(f"{BASE}/api/job/{jid}/meta", json={"title": "Empyreal-style · app link path", "world": "Dune"}, timeout=30)
print("LINKPATH", jid, s.get("status"), flush=True)
