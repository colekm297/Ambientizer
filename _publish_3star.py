import requests, time, json
BASE="http://127.0.0.1:5050"
JOBS = [
  ("Dawn Over Arrakis", "10919aaa"),
  ("Stargazer's Reverence", "94b60fc9"),
]

def jget(r):
    try: return r.json()
    except Exception: return {"error": f"non-JSON ({r.status_code}): {r.text[:200]}"}

def wait_task(job_id, timeout=40*60):
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

        # FIX from last time: duration_minutes=60, NOT 0 — 0 just matched the raw
        # (short) track length instead of looping to a real runtime.
        r = jget(requests.post(f"{BASE}/api/visual/export/{jid}", json={
            "duration_minutes": 60,
        }, timeout=60))
        if r.get("error"): raise RuntimeError(f"export start failed: {r}")
        t = wait_task(jid, timeout=40*60)
        if t.get("status") != "done": raise RuntimeError(f"export task ended: {t}")
        print(f"{label} FINAL VIDEO READY (60 min)", flush=True)

        meta = jget(requests.post(f"{BASE}/api/youtube/auto-metadata/{jid}", timeout=120))
        if meta.get("error"): raise RuntimeError(f"metadata failed: {meta}")
        yt_title = meta.get("title", "").strip()
        print(f"{label} yt title: {yt_title}", flush=True)

        r = jget(requests.post(f"{BASE}/api/youtube/upload/{jid}", json={
            "title": yt_title,
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "privacy": "private",
        }, timeout=60))
        if r.get("error"): raise RuntimeError(f"upload start failed: {r}")

        t0 = time.time()
        while time.time() - t0 < 30 * 60:
            s = jget(requests.get(f"{BASE}/api/youtube/upload-status/{jid}", timeout=30))
            st = s.get("status")
            if st == "done":
                print(f"{label} UPLOADED (private): {s.get('youtube_url') or s.get('message')}", flush=True)
                results.append({"title": yt_title, "job_id": jid, "status": "uploaded", "url": s.get("youtube_url")})
                break
            if st == "error":
                raise RuntimeError(f"upload failed: {s.get('message')}")
            time.sleep(10)
        else:
            raise RuntimeError("upload timed out")
    except Exception as e:
        print(f"{label} FAILED: {e}", flush=True)
        results.append({"title": title, "job_id": jid, "status": "failed", "error": str(e)})

print("\n==== 3-STAR PUBLISH SUMMARY ====", flush=True)
for r in results:
    line = f"  {r['status'].upper():8s} {r['title']}"
    if r.get("url"): line += f"  {r['url']}"
    print(line, flush=True)
print("PUBLISH_3STAR_DONE", flush=True)
