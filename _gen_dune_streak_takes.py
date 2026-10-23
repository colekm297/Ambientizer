"""Dune streak, week 1 candidates (2026-10-23 process plan, experiment 3). Three takes in Last Light on
Arrakis's register (the channel's best organic video), each at an iconic place. Cole picks in the app."""
import time, requests
BASE = "http://127.0.0.1:5050"
COMMON = ("Richly textured yet spacious, warm and reverent, instrumental, unhurried, never busy; every instrument "
          "keeps sounding at full presence through the final seconds, no fade-out, no silence. No drum kit, no "
          "cymbals, no electric guitar, no vocals.")
TAKES = {
 "Sietch Tabr at Night": "Warm reverent desert ambient in D Phrygian, free-meter with no pulse: night inside Sietch Tabr, "
   "the Fremen cave city, lamplight on carved rock and the hush of the water-hall far below. A low duduk sings long, "
   "aching phrases answered by a breathy ney flute, over a shimmering hammered santur drone and warm bowed cellos holding "
   "modal harmonies that never resolve; a faint deep drone like the mountain itself, and distant night wind at the cave "
   "mouth. Opens with santur drone and duduk alone; cellos gather slowly; the middle is warmest and fullest. " + COMMON,
 "The Deep Desert": "Warm vast desert ambient in A Phrygian, free-meter with no pulse: the deep desert of Arrakis under a "
   "night sky full of stars, dunes rolling to every horizon, the air cooling after the heat. A breathy ney flute and a low "
   "duduk trade long sustained phrases far apart, over a glowing analog pad and a soft hammered santur shimmer like starlight; "
   "low cellos and a quiet sub drone hold a slow i-bII-i motion; soft wind over sand. Opens with pad and ney alone; the duduk "
   "and cellos arrive slowly and stay. " + COMMON,
 "Arrakeen at Dawn": "Warm hopeful desert ambient in D Dorian at a slow free-flowing 58 BPM: dawn from a high balcony of "
   "Arrakeen, first gold light spreading across the city and the dunes beyond. A duduk carries a slow rising four-note hook "
   "that falls back home, answered by ney flute and a hammered santur rippling slow arpeggios, over warm cellos and soft "
   "French horns on a tonic D pedal; a faint frame drum far back like a slow heartbeat; morning wind. Opens with santur and "
   "duduk; horns and cellos gather as the light grows; the middle is fullest and warmest. " + COMMON,
}
for title, prompt in TAKES.items():
    for attempt in (1, 2):
        g = requests.post(f"{BASE}/api/generate", json={"prompt": prompt, "mode": "musical", "planner_mode": "raw",
            "music_length": 10, "duration": 10, "music_generation_mode": "text", "music_model": "music_v2",
            "mastering": True}, timeout=60).json()
        jid = g["job_id"]
        while True:
            s = requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()
            if s.get("status") in ("complete", "error", "canceled"): break
            time.sleep(15)
        print(title, "attempt", attempt, jid, s.get("status"), flush=True)
        if s.get("status") == "complete": break
    requests.post(f"{BASE}/api/job/{jid}/meta", json={"title": f"Dune streak · {title}", "world": "Dune"}, timeout=30)
print("DONE", flush=True)
