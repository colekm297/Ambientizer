"""Two tries written in the shape of Cole's 3-star prompts (pulse, hook, journey, named parts, scene sound).
One 10-min raw text take each on music_v2_5."""
import requests, time
BASE = "http://127.0.0.1:5050"
PROMPTS = [
 # Project Hail Mary: Three Knocks
 "Warm cinematic space ambient in D major at ~66 BPM, curious and hopeful — Project Hail Mary, the night Grace and Rocky "
 "first knock to each other through the clear wall between their two ships. THE SHIP: a soft, steady pulse like a friendly "
 "machine heartbeat — a muted steel drum and a low woodblock tapping an easy rhythm under the hum of life support and quiet "
 "clicks and whirs of instruments. THE KNOCKS: the hook is three gentle knocks answered by three more — played as a soft "
 "three-note steel-drum figure, rising, then answered a step higher, returning every so often like a friend checking in. "
 "THE FRIENDSHIP: warm glass-organ chords and cello move through a slow I–V–vi–IV progression with added 9ths, and a soft "
 "wordless choir swells in on the answers. Opens with the ship's hum, pulse and a single knock motif alone; strings and glass "
 "organ gradually join as the two of them work side by side; the middle is at its fullest, warm and bright, the knock motif "
 "passing between steel drum and choir like a conversation; the last stretch settles into a calm, contented glow with every "
 "instrument still sounding through the final seconds. Richly textured, playful but unhurried, instrumental except the "
 "wordless choir, always moving forward. No cymbals, no electric guitar, no dark or ominous low drones.",
 # The Odyssey: Penelope's loom
 "Warm cinematic ambient in A Dorian at ~62 BPM, tender and patient — the Odyssey, Penelope at her loom in the palace on "
 "Ithaca at night, weaving the shroud by day and secretly unweaving it by lamplight, waiting twenty years for Odysseus. "
 "THE LOOM: a soft wooden pulse of the shuttle and beater like a slow heartbeat — a muted frame drum and gentle wooden "
 "clicks keeping unhurried time, with the quiet creak of the loom frame and a lamp flickering. THE WAITING: an ancient lyre "
 "plays the hook, a slow four-note figure that rises and falls back, woven over and over like thread, sometimes answered by a "
 "breathy wooden flute. THE SEA OUTSIDE: warm cello and low French horns hold a slow i–IV–i–VII progression over a steady "
 "tonic pedal, with distant waves on the rocks below the palace and a soft night wind at the shutters. Opens with the loom's "
 "pulse and the lyre alone; cellos and horns gradually gather like the night deepening; the middle is fullest, the lyre "
 "hook doubled by flute and warm strings swelling with hope that he is still coming home; the last stretch eases into a "
 "calm lamplit glow with every instrument still sounding through the final seconds. Richly textured yet spacious, "
 "instrumental, yearning but warm, always moving forward. No cymbals, no electric guitar, the waves stay soft and distant.",
]
for p in PROMPTS:
    g = requests.post(f"{BASE}/api/generate", json={"prompt": p, "mode": "musical", "planner_mode": "raw", "music_length": 10,
         "duration": 10, "music_generation_mode": "text", "music_model": "music_v2_5", "mastering": True}, timeout=60).json()
    jid = g.get("job_id"); print("JOB", jid, p[:60], flush=True)
    while True:
        s = requests.get(f"{BASE}/api/status/{jid}", timeout=30).json()
        if s.get("status") in ("complete", "error", "canceled"): break
        time.sleep(15)
    print(jid, s.get("status"), s.get("error"), flush=True)
print("DONE", flush=True)
