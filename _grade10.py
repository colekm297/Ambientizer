import requests, time, json
BASE="http://127.0.0.1:5050"
JOBS=[("10919aaa","Dawn Over Arrakis","v1/5m"),("436f5b7c","Sietch Reverence","v2/10m"),
("19041ed5","Across The Dark","v1/5m"),("521c4ed4","Hail Mary Drift","v2/10m"),
("8db0eec4","Endurance Drift","v1/5m"),("64d864c5","Across the Years","v2/10m"),
("043a0b2e","Limbo Tide","v1/5m"),("7fcf5532","Folded Dream","v2/10m"),
("2bd08f05","Luminous Drift","v1/5m"),("4b7d06f8","Generation Ship Drift","v2/10m")]
results=[]
for jid,title,ml in JOBS:
    sc=None; notes=[]; sub={}
    for attempt in range(3):
        try:
            d=requests.post(f"{BASE}/api/ai-feedback/{jid}",timeout=600).json()
            if "score" in d:
                sc=d.get("score"); notes=d.get("notes",[]); sub=d.get("subscores") or d.get("scores") or {}
                break
            print(f"  {title}: no score (attempt {attempt+1}) {str(d)[:120]}",flush=True)
        except Exception as e:
            print(f"  {title}: err {e}",flush=True)
        time.sleep(15)
    results.append((sc,title,ml,sub,notes))
    print(f"GRADED {title} ({ml}): {sc}",flush=True)
print("\n==== RANKED ====",flush=True)
for sc,title,ml,sub,notes in sorted(results,key=lambda r:(r[0] is not None, r[0] or 0),reverse=True):
    print(f"{sc}/10  {title:<24} {ml}",flush=True)
    if sub: print(f"        {json.dumps(sub)}",flush=True)
    if notes: print(f"        {notes[0] if isinstance(notes,list) and notes else notes}",flush=True)
print("GRADE10 DONE",flush=True)
