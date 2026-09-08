import requests, time, json
BASE="http://127.0.0.1:5050"
JOBS=[("382deaeb","stitch"),("f65ee5f7","stitch"),("46d0fb91","stitch"),("94b60fc9","stitch"),
("90b8939e","stitch"),("97a383a8","stitch"),("fc002c6a","v2/10"),("f23c0cc7","v2/10"),
("444b17d8","v2/10"),("f2e5442b","v2/10"),("b3c3ae18","v2/10"),("bca3440c","v2/10"),
("22c0fc33","v2/10"),("9db8291a","v2/10"),("cfd21d18","v2/10"),("9e2e4e65","v1/5"),
("ba6be15f","v1/5"),("1e0e7c6e","v1/5"),("60a3e3a0","v1/5"),("8fd02771","v1/5")]
def title(jid):
    try: return (json.load(open(f"saved_jobs/{jid}.json")).get("config",{}) or {}).get("title") or jid
    except: return jid
res=[]
for jid,tag in JOBS:
    t=title(jid); sc=None; sub={}
    for _ in range(3):
        try:
            d=requests.post(f"{BASE}/api/ai-feedback/{jid}",timeout=600).json()
            if "score" in d: sc=d["score"]; sub=d.get("subscores",{}); break
        except Exception as e: pass
        time.sleep(15)
    res.append((sc,t,tag,sub))
    print(f"GRADED {t} ({tag}): {sc}",flush=True)
print("\n==== RANKED ====",flush=True)
for sc,t,tag,sub in sorted(res,key=lambda r:(r[0] is not None,r[0] or 0),reverse=True):
    w=sub.get("warmth","?"); print(f"{sc}/10  {t[:30]:<30} {tag:<8} warmth={w}",flush=True)
print("GRADE20 DONE",flush=True)
