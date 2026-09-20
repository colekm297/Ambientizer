"""Three warmer 60 s candidate takes for the Hail Mary still, for Cole to pick from (rule of 2026-09-20)."""
import requests, time, json, subprocess, os
BASE = "http://127.0.0.1:5050"; D = "output/release/hailmary_tauceti/previews"
TAKES = {
 "A_felt_keys_strings": "Warm, hopeful, gentle space ambient in C Lydian at 60 BPM, free-meter: soft felt electric piano notes far apart, "
    "a warm string pad breathing underneath, a faint high celesta shimmer like starlight. Feels like relief and quiet wonder, someone "
    "safe and far from home looking at a beautiful star. STRICT: no drums, no percussion, no low brass, no dark drones, no dissonance, "
    "no dread, no tension; major-leaning, soft, unhurried, nothing resolves.",
 "B_analog_synth_warm": "Warm analog synthesizer ambient in F major at 58 BPM, Vangelis-like: rich soft brass-pad chords held long, a slow "
    "gentle lead melody with a little vibrato, airy reverb, a soft sub bed. Tender, awed, hopeful; a small ship near a warm orange star. "
    "STRICT: no drums, no percussion, no arpeggios, no dark drones, no minor-key dread, no tension; unhurried, nothing resolves.",
 "C_cello_choir_hush": "Intimate hopeful space ambient in G major at 56 BPM: a solo cello sings slow warm phrases over soft sustained "
    "wordless choir 'ah' and gentle guitar harmonics, with a faint warm pad and distant starlight shimmer. Like a lullaby sung to the "
    "stars, quiet and kind. STRICT: no drums, no percussion, no low ominous drones, no dissonance, no dread; unhurried, nothing resolves.",
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
        print(name, "MP3", f"{D}/{name}.mp3", flush=True)
print("DONE", flush=True)
