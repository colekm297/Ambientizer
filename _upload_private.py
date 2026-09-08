import requests, time, json
BASE="http://127.0.0.1:5050"

# Today's two batches only (5 + 10 = 15) — the older 10 already-finished tracks
# are explicitly excluded per Cole's confirmation.
JOBS = [
 "159a6999","81616421","ea801dc8","8e828c6f","5d2f6285",   # batch of 5
 "58163771","9e2e4e65","072ec5a5","c5575d27","ee649bf2",   # batch of 10
 "d5d8759e","72cb749e","b8ae74fc","3d040493","9d326873",
]

def jget(r):
    try: return r.json()
    except Exception: return {"error": f"non-JSON ({r.status_code}): {r.text[:200]}"}

def title_of(jid):
    try:
        d = json.load(open(f"saved_jobs/{jid}.json"))
        return (d.get("config", {}) or {}).get("title") or jid
    except Exception:
        return jid

results = []
for jid in JOBS:
    label = f"[{title_of(jid)} / {jid}]"
    print(f"\n=== {label} START ===", flush=True)
    try:
        meta = jget(requests.post(f"{BASE}/api/youtube/auto-metadata/{jid}", timeout=120))
        if meta.get("error"):
            raise RuntimeError(f"metadata failed: {meta}")
        title = meta.get("title", "").strip()
        print(f"{label} title: {title}", flush=True)

        r = jget(requests.post(f"{BASE}/api/youtube/upload/{jid}", json={
            "title": title,
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "privacy": "private",
        }, timeout=60))
        if r.get("error"):
            raise RuntimeError(f"upload start failed: {r}")

        t0 = time.time()
        while time.time() - t0 < 30 * 60:
            s = jget(requests.get(f"{BASE}/api/youtube/upload-status/{jid}", timeout=30))
            st = s.get("status")
            if st == "done":
                print(f"{label} UPLOADED (private): {s.get('youtube_url') or s.get('message')}", flush=True)
                results.append({"title": title, "job_id": jid, "status": "uploaded", "url": s.get("youtube_url")})
                break
            if st == "error":
                raise RuntimeError(f"upload failed: {s.get('message')}")
            time.sleep(10)
        else:
            raise RuntimeError("upload timed out")
    except Exception as e:
        print(f"{label} FAILED: {e}", flush=True)
        results.append({"title": title_of(jid), "job_id": jid, "status": "failed", "error": str(e)})

print("\n==== UPLOAD SUMMARY ====", flush=True)
for r in results:
    line = f"  {r['status'].upper():8s} {r['title']}"
    if r.get("url"): line += f"  {r['url']}"
    print(line, flush=True)
print("UPLOAD_PRIVATE_DONE", flush=True)
