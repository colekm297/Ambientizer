import requests, time, json
BASE="http://127.0.0.1:5050"
JOBS = {
  "Moonlit Arrakis": "159a6999",
  "Cooper Station Homecoming": "81616421",
  "Marigold Dusk": "ea801dc8",
  "Abyssal Cathedral": "8e828c6f",
  "Ringworld Dawn": "5d2f6285",
}

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
for title, jid in JOBS.items():
    label = f"[{title} / {jid}]"
    print(f"\n=== {label} START ===", flush=True)
    try:
        # 1) auto image prompt from the soundscape
        ap = jget(requests.post(f"{BASE}/api/visual/auto-prompt/{jid}", timeout=120))
        img_prompt = ap.get("image_prompt")
        if not img_prompt: raise RuntimeError(f"auto-prompt failed: {ap}")
        print(f"{label} image prompt: {img_prompt[:90]}...", flush=True)

        # 2) generate scene image
        r = jget(requests.post(f"{BASE}/api/visual/image/{jid}", json={"prompt": img_prompt}, timeout=60))
        if r.get("error"): raise RuntimeError(f"image start failed: {r}")
        t = wait_task(jid)
        if t.get("status") != "done": raise RuntimeError(f"image task ended: {t}")
        print(f"{label} scene image done", flush=True)

        # 3) living-still (motion clip)
        r = jget(requests.post(f"{BASE}/api/visual/clip/{jid}", json={
            "mode": "motion", "motion_style": "auto", "motion_intensity": 1.0,
            "motion_loop_sec": 16, "motion_director_style": "subtle",
        }, timeout=60))
        if r.get("error"): raise RuntimeError(f"clip start failed: {r}")
        t = wait_task(jid)
        if t.get("status") != "done": raise RuntimeError(f"clip task ended: {t}")
        print(f"{label} living still done", flush=True)

        # 4) thumbnail — default hailmary-ish style, use title as hook
        r = jget(requests.post(f"{BASE}/api/thumbnail/{jid}/set", json={
            "style": "hailmary", "hook": title, "subtitle": "Ambient Soundscape",
        }, timeout=60))
        if r.get("error"): raise RuntimeError(f"thumbnail failed: {r}")
        print(f"{label} thumbnail set", flush=True)

        # 5) export final video (loop to full track length, with fade-in default)
        r = jget(requests.post(f"{BASE}/api/visual/export/{jid}", json={
            "duration_minutes": 0,  # match audio length
        }, timeout=60))
        if r.get("error"): raise RuntimeError(f"export start failed: {r}")
        t = wait_task(jid, timeout=40*60)
        if t.get("status") != "done": raise RuntimeError(f"export task ended: {t}")
        print(f"{label} FINAL VIDEO READY", flush=True)

        results.append({"title": title, "job_id": jid, "status": "ready"})
    except Exception as e:
        print(f"{label} FAILED: {e}", flush=True)
        results.append({"title": title, "job_id": jid, "status": "failed", "error": str(e)})

print("\n==== PUBLISH5 SUMMARY ====", flush=True)
for r in results:
    print(f"  {r['status'].upper():8s} {r['title']}  ({r['job_id']})", flush=True)
print("PUBLISH5 DONE", flush=True)
