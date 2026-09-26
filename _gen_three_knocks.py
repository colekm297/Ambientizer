"""'Three Knocks (Rocky & Grace)': one 10-min text take, music_v2, raw prompt, per docs/HOW-A-TRACK-IS-MADE.md."""
import requests, time
BASE = "http://127.0.0.1:5050"
PROMPT = ("Warm, hopeful ambient in D major, around 60 BPM, calm and steady. Soft glass-organ tones hold slow, simple chords that "
          "move between D, G and A and back. A steel drum plays gentle single notes now and then, far apart, like a friendly knock "
          "from the next room. A warm string section breathes quietly underneath, and a soft wordless choir enters on some chords "
          "and leaves again. It should feel like two friends working side by side in a quiet room: safe, warm, not alone. Keep it "
          "gentle the whole way through. No low drones, no dark or minor turns, no percussion with a beat, no big swells, nothing tense.")
g = requests.post(f"{BASE}/api/generate", json={"prompt": PROMPT, "title": "Three Knocks (Rocky & Grace)", "mode": "musical",
     "planner_mode": "raw", "music_length": 10, "duration": 10, "music_generation_mode": "text", "music_model": "music_v2",
     "mastering": True}, timeout=60).json()
jid = g.get("job_id"); print("JOB", jid, flush=True)
while True:
    s = requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()
    if s.get("status") in ("complete", "error", "canceled"): break
    time.sleep(15)
print(jid, s.get("status"), s.get("title"), s.get("error"), flush=True)
