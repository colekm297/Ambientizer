"""Three 60 s candidate takes for a Dune sietch-interior piece (still already exists), prepared ahead of Cole's pick."""
import requests, time, subprocess, os
BASE = "http://127.0.0.1:5050"; D = "output/release/sietch_dusk/previews"
TAKES = {
 "A_duduk_santur_warm": "Warm desert ambient in D Dorian at 60 BPM, free-meter: a low duduk sings slow phrases over a soft hammered "
    "santur shimmer and a warm bowed-cello bed; feels sheltered and calm, evening light through a cave mouth. STRICT: no drums, "
    "no percussion, no dark drones, no dissonance, no tension; unhurried, nothing resolves.",
 "B_oud_strings_hush": "Gentle Middle-Eastern-tinged ambient in A minor pentatonic at 58 BPM: soft oud notes far apart, a warm string "
    "pad, a distant ney flute breath; intimate and safe, a quiet refuge at dusk. STRICT: no drums, no percussion, no low ominous "
    "drones, no dread; unhurried, nothing resolves.",
 "C_choir_pad_glow": "Warm reverent ambient in E major at 56 BPM: soft wordless choir 'oo' over a glowing analog pad, a faint solo "
    "violin line, gentle and hopeful, like sunset through stone. STRICT: no drums, no percussion, no dark drones, no dissonance; "
    "unhurried, nothing resolves.",
}
for name, prompt in TAKES.items():
    g = requests.post(f"{BASE}/api/generate", json={"prompt": prompt, "mode": "musical", "approach": "unified", "music_length": 1,
         "duration": 1, "planner_mode": "claude", "music_generation_mode": "text", "music_model": "music_v1", "mastering": True}, timeout=60).json()
    jid = g.get("job_id"); print(name, "JOB", jid, flush=True)
    while True:
        s = requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()
        if s.get("status") in ("complete", "error", "canceled"): break
        time.sleep(10)
    wav = s.get("output_path"); print(name, s.get("status"), wav, flush=True)
    if wav and os.path.exists(wav):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-t", "62", "-af", "afade=t=out:st=58:d=4", "-c:a", "libmp3lame", "-b:a", "192k", f"{D}/{name}.mp3"], check=True)
print("DONE", flush=True)
