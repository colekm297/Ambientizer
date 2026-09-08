import requests, time
BASE="http://127.0.0.1:5050"
JOBS = [
  ("Cliffside Temple", "58163771"),
  ("Orbital Solitude", "9e2e4e65"),
  ("Snow Globe Reverie", "072ec5a5"),
  ("Starlit Observatory", "c5575d27"),
  ("Atoll Lagoon Bloom", "ee649bf2"),
  ("Night Train Reverie", "d5d8759e"),
  ("Snowfall Village Hush", "72cb749e"),
  ("Cartographer's Reverie", "b8ae74fc"),
  ("Snowlit Spring", "3d040493"),
  ("Lantern-lit Bazaar", "9d326873"),
]

def jget(r):
    try: return r.json()
    except Exception: return {"error": f"non-JSON ({r.status_code}): {r.text[:200]}"}

def wait_task(job_id, timeout=25*60):
    t0=time.time(); time.sleep(3)
    while time.time()-t0 < timeout:
        try:
            s=jget(requests.get(f"{BASE}/api/task-status/{job_id}", timeout=30))
        except Exception as e:
            print(f"  poll error (retry): {e}", flush=True); time.sleep(10); continue
        st=s.get("status")
        if st in ("done","error","canceled","idle"): return s
        time.sleep(10)
    return {"status":"timeout"}

results = []
for title, jid in JOBS:
    label = f"[{title} / {jid}]"
    print(f"\n=== {label} START ===", flush=True)
    try:
        ap = jget(requests.post(f"{BASE}/api/visual/auto-prompt/{jid}", timeout=120))
        img_prompt = ap.get("image_prompt")
        if not img_prompt: raise RuntimeError(f"auto-prompt failed: {ap}")
        print(f"{label} image prompt: {img_prompt[:90]}...", flush=True)

        r = jget(requests.post(f"{BASE}/api/visual/image/{jid}", json={"prompt": img_prompt}, timeout=60))
        if r.get("error"): raise RuntimeError(f"image start failed: {r}")
        t = wait_task(jid)
        if t.get("status") != "done": raise RuntimeError(f"image task ended: {t}")
        print(f"{label} scene image done", flush=True)

        r = jget(requests.post(f"{BASE}/api/visual/clip/{jid}", json={
            "mode": "motion", "motion_style": "auto", "motion_intensity": 1.0,
            "motion_loop_sec": 16, "motion_director_style": "subtle",
        }, timeout=60))
        if r.get("error"): raise RuntimeError(f"clip start failed: {r}")
        t = wait_task(jid)
        if t.get("status") != "done": raise RuntimeError(f"clip task ended: {t}")
        print(f"{label} living still done", flush=True)

        r = jget(requests.post(f"{BASE}/api/thumbnail/{jid}/set", json={
            "style": "hailmary", "hook": title, "subtitle": "Ambient Soundscape",
        }, timeout=60))
        if r.get("error"): raise RuntimeError(f"thumbnail failed: {r}")
        print(f"{label} thumbnail set", flush=True)

        r = jget(requests.post(f"{BASE}/api/visual/export/{jid}", json={
            "duration_minutes": 0,
        }, timeout=60))
        if r.get("error"): raise RuntimeError(f"export start failed: {r}")
        t = wait_task(jid, timeout=40*60)
        if t.get("status") != "done": raise RuntimeError(f"export task ended: {t}")
        print(f"{label} FINAL VIDEO READY", flush=True)

        results.append({"title": title, "job_id": jid, "status": "ready"})
    except Exception as e:
        print(f"{label} FAILED: {e}", flush=True)
        results.append({"title": title, "job_id": jid, "status": "failed", "error": str(e)})

print("\n==== PUBLISH10 SUMMARY ====", flush=True)
for r in results:
    print(f"  {r['status'].upper():8s} {r['title']}  ({r['job_id']})", flush=True)
print("PUBLISH10 DONE", flush=True)
