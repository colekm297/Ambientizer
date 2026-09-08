import requests, time, json
BASE="http://127.0.0.1:5050"
ids=[l.strip() for l in open("/tmp/burn5_ids.txt") if l.strip()]
def meta(jid):
    d=json.load(open(f"saved_jobs/{jid}.json")); c=d.get("config",{}) or {}
    return c.get("title") or jid, d.get("seed_idea","")[:24], d.get("music_generation_mode"), d.get("music_model")
res=[]
for jid in ids:
    t,seed,mode,model=meta(jid); sc=None
    for _ in range(3):
        try:
            fb=requests.post(f"{BASE}/api/ai-feedback/{jid}",timeout=600).json()
            if "score" in fb: sc=fb["score"]; break
        except: pass
        time.sleep(10)
    res.append((sc,t,seed,mode,(model or "?").replace("music_","")))
    print(f"  {sc}  {t[:26]:<26} {seed}",flush=True)
print("\n==== RANKED batch5 ====",flush=True)
for sc,t,seed,mode,model in sorted(res,key=lambda r:(r[0] is not None,r[0] or 0),reverse=True):
    print(f"{sc}/10  {t[:26]:<26} {mode}/{model}  ::  {seed}",flush=True)
print("GRADE5 DONE",flush=True)
