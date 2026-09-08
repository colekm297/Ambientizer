import requests, time, json, re
BASE = "http://127.0.0.1:5050"
seed = ("Dune — dusk over Arrakis, the last light leaving the dunes. Warm, slow, reverent ambient in D Phrygian "
        "at 62 BPM, free-meter: a low duduk and breathy ney trade long sustained phrases over a shimmering "
        "hammered santur drone and warm bowed cello. STRICT: no drums, no percussion, no frame drum, no cymbals, "
        "no electric guitar, no arpeggios; every voice sustains; nothing resolves, the harmony never lands.")
e = requests.post(f"{BASE}/api/enhance-prompt", json={"prompt": seed, "mode": "musical", "approach": "unified",
                  "enhance_style": "world"}, timeout=240).json()
layers, enh = e.get("layers"), e.get("enhanced_prompt") or seed
BAN = r"(frame drum|drum|percussion|percussive|cymbal|tabla|daf|riq|electric guitar|arpeggio)"
def scrub(s):
    s = re.sub(r"[^.;,]*\b" + BAN + r"\b[^.;,]*[.;,]?", "", s, flags=re.I)
    return s.strip() + " No drums, no percussion, nothing resolves; every voice sustains."
enh2 = scrub(enh)
if layers:
    for L in layers:
        for k in ("prompt", "prompt_preview", "elevenlabs_prompt"):
            if isinstance(L.get(k), str): L[k] = scrub(L[k])
print("PROMPT", enh2[:400], flush=True)
g = requests.post(f"{BASE}/api/generate", json={"prompt": enh2, "layer_plan": layers, "mode": "musical",
     "approach": "unified", "music_length": 20, "duration": 20, "planner_mode": "claude",
     "music_generation_mode": "stitch", "music_model": "music_v1", "mastering": True}, timeout=60).json()
jid = g.get("job_id"); print("JOB", jid, flush=True)
while True:
    s = requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()
    st = s.get("status")
    if st in ("complete", "error", "canceled"):
        print("STATUS", st, json.dumps(s)[:600], flush=True); break
    time.sleep(15)
print("DONE", flush=True)
