"""One-shot batch driver: generate 10 sci-fi soundscapes via the web API
(enhance → plan → generate, 10 min each), grade each with Gemini
(/api/ai-feedback), then build a Living Still for every job
(auto image prompt → Grok image → procedural motion loop → full export → save).

Writes progress to stdout and a final ranked summary to _batch_scifi10_results.json.
Safe to re-run: phases skip jobs already done (state in the results file).
"""
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE = "http://127.0.0.1:5050"
RESULTS = Path(__file__).parent / "_batch_scifi10_results.json"

THEMES = [
    ("Dune", "Arrakis open desert at night — vast dunes under two moons, distant sandworm rumble felt more than heard, Fremen stillness", "world"),
    ("Dune", "dawn over a spice harvester on the open erg of Arrakis, heat shimmer rising, ornithopter wings far away", "score"),
    ("Dune", "deep inside a Fremen sietch on Arrakis — cool stone, dripping water reclaimed, ritual calm", "world"),
    ("Project Hail Mary", "the Hail Mary coasting alone toward Tau Ceti — soft ship hum, instruments ticking, one man and the void", "world"),
    ("Project Hail Mary", "Rocky's workshop aboard the Blip-A — warm engineering sounds reimagined as music, alien camaraderie across a xenonite wall", "score"),
    ("Interstellar", "endless cornfields at golden hour before the dust storm — wind through stalks, a quiet farmhouse, longing for the stars", "world"),
    ("Interstellar", "slow rotation of the Endurance over Saturn's rings — graceful orbital ballet, organ-like vastness, free-meter", "score"),
    ("Interstellar", "the still ocean of Miller's planet between waves — shallow water, dread and awe, time stretched thin", "world"),
    ("Inception", "the dream-layer hotel corridor in zero gravity — suspended weightless calm, elegant tension, slowed time", "score"),
    ("Inception", "limbo city at the shoreline — crumbling skyscrapers into the sea, two lifetimes of memory, melancholic grandeur", "world"),
]


def jget(r):
    try:
        return r.json()
    except Exception:
        return {"error": f"non-JSON ({r.status_code}): {r.text[:200]}"}


def log(msg):
    print(msg, flush=True)


def load_state():
    if RESULTS.exists():
        return json.loads(RESULTS.read_text())
    return {"jobs": []}


def save_state(state):
    RESULTS.write_text(json.dumps(state, indent=2))


def wait_job(job_id, timeout=40 * 60):
    """Poll generation status until terminal."""
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        try:
            s = jget(requests.get(f"{BASE}/api/status/{job_id}", timeout=30))
        except Exception as e:
            log(f"  [{job_id}] status poll error (retrying): {e}")
            time.sleep(15)
            continue
        st = s.get("status")
        msg = s.get("progress_message", "")
        if msg != last:
            log(f"  [{job_id}] {st}: {msg}")
            last = msg
        if st in ("complete", "error", "canceled"):
            return s
        time.sleep(20)
    return {"status": "timeout"}


def wait_task(job_id, timeout=25 * 60):
    """Poll a background visual/export task until terminal."""
    t0 = time.time()
    time.sleep(3)
    while time.time() - t0 < timeout:
        try:
            s = jget(requests.get(f"{BASE}/api/task-status/{job_id}", timeout=30))
        except Exception as e:
            log(f"  [{job_id}] task poll error (retrying): {e}")
            time.sleep(10)
            continue
        st = s.get("status")
        if st in ("done", "error", "canceled", "idle"):
            return s
        time.sleep(10)
    return {"status": "timeout"}


def generate_one(idx, franchise, seed, style):
    label = f"#{idx + 1} [{franchise}]"
    log(f"{label} ENHANCE ({style}): {seed[:70]}...")
    r = jget(requests.post(f"{BASE}/api/enhance-prompt", json={
        "prompt": seed, "mode": "musical", "approach": "unified",
        "enhance_style": style,
    }, timeout=300))
    enhanced = r.get("enhanced_prompt") or seed
    layers = r.get("layers") or []
    log(f"{label} enhanced → {enhanced[:90]}...")

    body = {
        "prompt": enhanced, "mode": "musical", "approach": "unified",
        "music_length": 10, "duration": 5, "mastering": True, "loopable": True,
        "planner_mode": "claude", "music_generation_mode": "text",
    }
    if layers:
        body["layer_plan"] = layers
    g = jget(requests.post(f"{BASE}/api/generate", json=body, timeout=60))
    job_id = g.get("job_id")
    if not job_id:
        return {"idx": idx, "franchise": franchise, "seed": seed, "error": f"generate failed: {g}"}
    log(f"{label} GENERATING as job {job_id}")
    s = wait_job(job_id)
    return {
        "idx": idx, "franchise": franchise, "seed": seed, "style": style,
        "enhanced": enhanced, "job_id": job_id,
        "status": s.get("status"), "error": s.get("error"),
        "warnings": s.get("warnings", []),
        "output_path": s.get("output_path"),
    }


def grade_one(job):
    job_id = job["job_id"]
    for attempt in range(3):
        try:
            r = requests.post(f"{BASE}/api/ai-feedback/{job_id}", timeout=600)
            d = jget(r)
            if "score" in d:
                job["score"] = d["score"]
                job["grade_notes"] = d.get("notes", [])
                log(f"GRADE [{job['franchise']}] {job_id}: {d['score']}/10")
                return
            log(f"GRADE {job_id} attempt {attempt + 1} failed: {d.get('error')}")
        except Exception as e:
            log(f"GRADE {job_id} attempt {attempt + 1} exception: {e}")
        time.sleep(20)
    job["score"] = None
    job["grade_notes"] = ["grading failed"]


def living_still_one(job):
    job_id = job["job_id"]
    label = f"STILL [{job['franchise']}] {job_id}"
    try:
        ap = jget(requests.post(f"{BASE}/api/visual/auto-prompt/{job_id}", timeout=120))
        img_prompt = ap.get("image_prompt")
        if not img_prompt:
            raise RuntimeError(f"auto-prompt failed: {ap}")
        log(f"{label} image prompt: {img_prompt[:80]}...")

        r = jget(requests.post(f"{BASE}/api/visual/image/{job_id}",
                               json={"prompt": img_prompt}, timeout=60))
        if r.get("error"):
            raise RuntimeError(f"image start failed: {r}")
        t = wait_task(job_id)
        if t.get("status") != "done":
            raise RuntimeError(f"image task ended: {t}")
        log(f"{label} image done; compositing motion loop...")

        r = jget(requests.post(f"{BASE}/api/visual/clip/{job_id}", json={
            "mode": "motion", "motion_style": "auto", "motion_intensity": 1.0,
            "motion_loop_sec": 16, "motion_director_style": "subtle",
        }, timeout=60))
        if r.get("error"):
            raise RuntimeError(f"clip start failed: {r}")
        t = wait_task(job_id)
        if t.get("status") != "done":
            raise RuntimeError(f"motion clip task ended: {t}")
        log(f"{label} motion loop done; exporting full video...")

        r = jget(requests.post(f"{BASE}/api/visual/export/{job_id}",
                               json={"duration_minutes": 0}, timeout=60))
        if r.get("error"):
            raise RuntimeError(f"export start failed: {r}")
        t = wait_task(job_id, timeout=40 * 60)
        if t.get("status") != "done":
            raise RuntimeError(f"export task ended: {t}")

        name = f"{job['franchise']} — auto batch"
        r = jget(requests.post(f"{BASE}/api/visual/living-still/{job_id}",
                               json={"name": name}, timeout=60))
        if not r.get("ok"):
            raise RuntimeError(f"living-still save failed: {r}")
        job["living_still"] = "ok"
        log(f"{label} ✅ living still saved")
    except Exception as e:
        job["living_still"] = f"failed: {e}"
        log(f"{label} ❌ {e}")


def main():
    random.shuffle(THEMES)
    state = load_state()
    done_ids = {j.get("idx") for j in state["jobs"] if j.get("status") == "complete"}

    # Phase 1: generate (3 concurrent)
    todo = [(i, f, s, st) for i, (f, s, st) in enumerate(THEMES) if i not in done_ids]
    if todo:
        log(f"=== PHASE 1: generating {len(todo)} soundscapes (3 concurrent, 10 min each) ===")
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = [ex.submit(generate_one, i, f, s, st) for i, f, s, st in todo]
            for fut in as_completed(futs):
                job = fut.result()
                state["jobs"] = [j for j in state["jobs"] if j.get("idx") != job["idx"]]
                state["jobs"].append(job)
                save_state(state)

    ok_jobs = [j for j in state["jobs"] if j.get("status") == "complete"]
    log(f"=== PHASE 1 done: {len(ok_jobs)}/{len(THEMES)} complete ===")

    # Phase 2: grade (sequential — Gemini rate limiter)
    log("=== PHASE 2: Gemini grading ===")
    for job in ok_jobs:
        if job.get("score") is None:
            grade_one(job)
            save_state(state)

    # Phase 3: living stills (2 concurrent)
    log("=== PHASE 3: living stills ===")
    todo = [j for j in ok_jobs if j.get("living_still") != "ok"]
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(living_still_one, j) for j in todo]
        for fut in as_completed(futs):
            save_state(state)

    # Final ranked summary
    ranked = sorted(ok_jobs, key=lambda j: (j.get("score") or 0), reverse=True)
    log("\n=== FINAL RANKING ===")
    for j in ranked:
        log(f"{j.get('score')}/10  [{j['franchise']}] job {j['job_id']}  still={j.get('living_still')}  — {j['seed'][:60]}")
    failed = [j for j in state["jobs"] if j.get("status") != "complete"]
    for j in failed:
        log(f"FAILED [{j['franchise']}] idx {j['idx']}: {j.get('error')}")
    save_state(state)
    log("BATCH COMPLETE")


if __name__ == "__main__":
    sys.exit(main())
