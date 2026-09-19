"""Hail Mary / Tau Ceti music: 30-min stitched source in 5-min cells (fewer, longer cells than Dusk's
150 s default, so the hour has fewer audible seams and a slower harmonic drift)."""
import requests, time, json, re
BASE = "http://127.0.0.1:5050"
seed = ("Project Hail Mary — alone at Tau Ceti, twelve light years from home, a small ship hanging near a warm orange star. "
        "Warm, slow, hopeful-but-lonely space ambient in F Lydian at 58 BPM, free-meter: a soft church-organ-like pad and a deep "
        "sub drone hold long chords while a solo cello and a distant breathy flute trade slow sustained phrases; faint glassy "
        "high harmonics shimmer like starlight. STRICT: no drums, no percussion, no cymbals, no electric guitar, no arpeggios, "
        "no piano runs; every voice sustains; nothing resolves, the harmony never lands; the tempo never rises.")
e = requests.post(f"{BASE}/api/enhance-prompt", json={"prompt": seed, "mode": "musical", "approach": "unified",
                  "enhance_style": "cinematic"}, timeout=240).json()
layers, enh = e.get("layers"), e.get("enhanced_prompt") or seed
BAN = r"(drum|percussion|percussive|cymbal|tabla|electric guitar|arpeggio|piano run|pulse|beat|rhythm)"
def scrub(s):
    s = re.sub(r"[^.;,]*\b" + BAN + r"\b[^.;,]*[.;,]?", "", s, flags=re.I)
    return s.strip() + " No drums, no percussion, nothing resolves; every voice sustains; the tempo never rises."
enh2 = scrub(enh)
if layers:
    for L in layers:
        for k in ("prompt", "prompt_preview", "elevenlabs_prompt"):
            if isinstance(L.get(k), str): L[k] = scrub(L[k])
print("PROMPT", enh2[:500], flush=True)
g = requests.post(f"{BASE}/api/generate", json={"prompt": enh2, "layer_plan": layers, "mode": "musical",
     "approach": "unified", "music_length": 30, "duration": 30, "planner_mode": "claude",
     "music_generation_mode": "stitch", "stitch_cell_sec": 300, "music_model": "music_v1", "mastering": True}, timeout=60).json()
jid = g.get("job_id"); print("JOB", jid, json.dumps(g)[:300], flush=True)
while True:
    s = requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()
    st = s.get("status")
    if st in ("complete", "error", "canceled"):
        print("STATUS", st, json.dumps(s)[:800], flush=True); break
    time.sleep(20)
print("DONE", flush=True)
