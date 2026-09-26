"""Full-length (30 min, 5-min stitched cells) versions of the three warmer Hail Mary directions,
so Cole reviews what would actually play under the hour, not a 1-minute sketch."""
import requests, time, json
BASE = "http://127.0.0.1:5050"
from _gen_hm_previews import TAKES  # same three briefs he heard as sketches
NAMES = {"A_felt_keys_strings": "Hail Mary A: felt keys + strings (30 min)",
         "B_analog_synth_warm": "Hail Mary B: warm analog synth (30 min)",
         "C_cello_choir_hush": "Hail Mary C: cello + soft choir (30 min)"}
jobs = {}
for k, prompt in TAKES.items():
    g = requests.post(f"{BASE}/api/generate", json={"prompt": prompt, "title": NAMES[k], "mode": "musical", "approach": "unified",
         "music_length": 30, "duration": 30, "planner_mode": "claude", "music_generation_mode": "stitch",
         "stitch_cell_sec": 300, "music_model": "music_v1", "mastering": True}, timeout=60).json()
    jobs[k] = g.get("job_id"); print(k, "JOB", jobs[k], flush=True)
    while True:
        s = requests.get(f"{BASE}/api/status/{jobs[k]}", timeout=30).json()
        if s.get("status") in ("complete", "error", "canceled"): break
        time.sleep(20)
    print(k, s.get("status"), s.get("title"), s.get("duration_sec"), flush=True)
print("DONE", flush=True)
