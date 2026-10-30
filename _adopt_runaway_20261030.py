"""One-off: finish the 18 takes the 2026-10-30 status-check bug submitted at once (title, log, offload)."""
import json, re, threading
from pathlib import Path
import stock_campaign as sc

waves = {w: json.loads(Path(f"data/stock/{w}.json").read_text()) for w in ("wave1", "wave2")}
jobs = []
for line in Path("data/stock/wave2.log").read_text().splitlines():
    m = re.match(r"SHORT/FAILED (.+) ([0-9a-f]{8}) (running|complete) 0s$", line)
    if not m:
        continue
    name, jid = m.group(1), m.group(2)
    for w, items in waves.items():
        it = next((i for i in items if i["name"] == name), None)
        if it:
            model = sc.requests.get(f"{sc.BASE}/api/status/{jid}", timeout=30).json().get("music_model") or "music_v2_5"
            jobs.append((dict(it, model=model), jid, Path(f"data/stock/{w}.jsonl")))
            break
print(f"adopting {len(jobs)} jobs", flush=True)
ts = [threading.Thread(target=sc.adopt, args=j) for j in jobs]
[t.start() for t in ts]; [t.join() for t in ts]
print("ADOPT ALL DONE", flush=True)
