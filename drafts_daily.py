#!/usr/bin/env python3
"""drafts_daily.py: turn takes into finished 1-hour videos, uploaded PRIVATE, for Cole to review on YouTube.

Cole, 2026-11-03: "can we just start posting stuff... start private but i get to see the whole thing easily
and just ok what i like delete what i don't." So the music pick moves to the end: every day a few takes
become full videos (scene image, living still, thumbnail, metadata) and land private in a playlist
called "Drafts to review" on his channel. He watches there, makes the keepers public and deletes the
rest in YouTube Studio. Nothing here ever makes a video public or deletes one.

Order: his 3-star takes, then 2-star, then the stock-campaign takes (oldest first). Never 1-star, never
a take already on YouTube, never one under 2 minutes. Same app flow as _publish_3star.py.
Cost per video: gpt-image-2 still ($0.16), one Seedance 1.5 Pro loop, three Claude calls; the export is local.
Takes with a beat (beat_check.py) are skipped.
YouTube quota: an upload is 1,600 units of the 10,000/day, so PER_DAY stays at 5.

Cole's publish or delete is his verdict on a draft, and each run records it (read only, never acts on it).

Usage: .venv/bin/python drafts_daily.py [--n 5] [--dry-run] [--verdicts]
Log: data/drafts.jsonl (one line per attempt), data/draft_verdicts.jsonl (one line per status change).
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import shutil
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")   # launchd passes no keys: without this the Claude, fal and R2 steps fail or skip
BASE = "http://127.0.0.1:5050"
LOG = HERE / "data" / "drafts.jsonl"
VERDICTS = HERE / "data" / "draft_verdicts.jsonl"
PLAYLIST_FILE = HERE / "data" / "drafts_playlist.json"
PLAYLIST_TITLE = "Drafts to review"
PER_DAY = 1   # Cole, 2026-11-03: "one a day is fine"; he publishes the ones he likes himself
ANCIENT_WORLDS = re.compile(r"dune|odyssey|lord of the rings|hobbit|greek|egypt|rome|norse|viking|arthur|narnia", re.I)
MIN_FREE_GB = 24   # an hour at Seedance's 18 Mbps is 8 GB, and the fade step holds three copies at its peak
# beat_check.py percussive share. Rain Over Arrakis (Cole: "the beat in it is just bad") scored 0.147 and his
# drum-y 1-stars 0.142 and 0.393; every 3-star he has is 0.085 or under. Calibrated 2026-11-03.
MAX_PERC = 0.10
# Takes already in a release whose job record doesn't carry the YouTube id (built by the _build_*_master
# scripts): Sirens eec20d97, Fair Wind 2bacadbf plus its two sister takes, Calypso, Dawn, the observatory.
RELEASED = {"eec20d97", "2bacadbf", "324a1f7b", "1af58c0f", "16a924b4", "a38b5c83", "10919aaa", "94b60fc9"}
CTA = "If you liked this track, please consider liking and subscribing!"
# Cole, 2026-09-26: "nobody fucking knows what a sietch is". 36 competitor Dune videos agree: places a film viewer
# knows win, book lore loses (Irulan 0.20x, Salusa Secundus 0.44x). The metadata prompt asks; this enforces.
LORE = re.compile(r"\b(sietch|irulan|alia|salusa|secundus|giedi|caladan|bene gesserit|kwisatz|haderach|shai[- ]hulud"
                  r"|lisan|mahdi|muad.?dib|ornithopter|melange|crysknife)\b", re.I)


def jget(r):
    try:
        return r.json()
    except Exception:
        return {"error": f"non-JSON ({r.status_code}): {r.text[:200]}"}


def wait_task(jid, timeout=40 * 60):
    t0 = time.time()
    time.sleep(3)
    while time.time() - t0 < timeout:
        try:
            s = jget(requests.get(f"{BASE}/api/task-status/{jid}", timeout=30))
        except Exception:
            time.sleep(10)
            continue
        if s.get("status") in ("done", "error", "canceled", "idle"):
            return s
        time.sleep(10)
    return {"status": "timeout"}


def tried() -> set:
    """Takes that are finished with: uploaded, skipped, or failed twice. A single failure retries next run."""
    if not LOG.exists():
        return set()
    fails, out = {}, set()
    for l in LOG.read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r["status"].startswith("failed"):
            fails[r["job_id"]] = fails.get(r["job_id"], 0) + 1
            if fails[r["job_id"]] >= 2:
                out.add(r["job_id"])
        else:
            out.add(r["job_id"])
    return out


def take_secs(j: dict) -> float:
    """Length of the take, pulling its audio back from R2 if it was offloaded (export needs it local)."""
    from stock_campaign import secs
    from media_store import get_store
    store = get_store()
    for p in (((j.get("config") or {}).get("layers") or [{}])[0].get("generated_audio_path"),
              j.get("raw_output_path"), j.get("output_path"), j.get("audio_path")):
        if not p:
            continue
        p = str(p if Path(p).is_absolute() else HERE / p)
        if not Path(p).exists() and store.enabled and store.lookup(p):
            store.restore(p)
        if Path(p).exists():
            return secs(p)
    return 0.0


def beat_perc(j: dict) -> float | None:
    from beat_check import beat_scores
    for p in (((j.get("config") or {}).get("layers") or [{}])[0].get("generated_audio_path"), j.get("raw_output_path")):
        if p and Path(p).exists():
            return beat_scores(p)["perc"]
    return None


LOOP_PROMPT = """Write the motion prompt for a 12-second image-to-video shot of this still, for an ambient music
video that loops for an hour. The camera is locked off and almost everything holds perfectly still; only one
or two small, natural things move gently (a flame flickering, rain falling, mist drifting, water glinting,
stars twinkling). Name exactly what moves and say firmly that everything else (land, buildings, figures,
sky shapes, the frame) does not move. Start with: "Static locked-off tripod shot. The camera does not move
at all: no push in, no zoom, no pan, no drift." End with: "A living photograph, cinematic, no cuts."
Nothing may appear, burst, puff, grow, fade out or travel across the frame: no smoke plumes, no sparks, no
birds, no lightning, no people moving. Every motion is continuous and even, the same at the last second as
at the first, so the loop has no visible event. Under 110 words. Reply with the prompt only.

The still was made from this description:
"""


def seedance_loop(jid: str) -> str:
    """The living still the releases use (memory: Seedance pipeline, 2026-08-28): Seedance 1.5 Pro, the same
    still as first and last frame, camera fixed, 12 s at 1080p, shipped raw. The app's "motion" clip warps
    the whole frame, which is what Cole saw on the first draft ("the entire background is just moving")."""
    import anthropic
    import fal_loop as fl
    from llm import llm_create, llm_text
    j = json.load(open(HERE / "saved_jobs" / f"{jid}.json"))
    still, desc = j["visual_image_path"], j.get("visual_image_prompt", "")
    motion = llm_text(llm_create(anthropic.Anthropic(), model="claude-opus-5-5", max_tokens=400,
                                 messages=[{"role": "user", "content": LOOP_PROMPT + desc}])).strip()
    fal = fl._fal()
    url = fal.upload_file(still)
    res = fal.subscribe("fal-ai/bytedance/seedance/v1.5/pro/image-to-video", arguments={
        "prompt": motion, "image_url": url, "end_image_url": url, "resolution": "1080p", "duration": "12",
        "camera_fixed": True, "generate_audio": False, "aspect_ratio": "16:9"}, with_logs=False)
    out = HERE / "output" / f"{jid}_seedance.mp4"
    out.write_bytes(requests.get(res["video"]["url"], timeout=300).content)
    with open(out, "rb") as fh:
        r = jget(requests.post(f"{BASE}/api/visual/upload-video/{jid}",
                               files={"file": (out.name, fh, "video/mp4")}, timeout=300))
    if r.get("status") != "ready":
        raise RuntimeError(f"attaching the loop failed: {r}")
    return motion


def fl_seam(jid: str) -> dict:
    import fal_loop as fl
    return fl.seam_report(str(HERE / "output" / f"{jid}_seedance.mp4"))


def queue() -> list[dict]:
    """Takes to draft, best first."""
    done = tried()
    stock_order = {}
    for f in sorted(glob.glob(str(HERE / "data" / "stock" / "wave*.jsonl")) + glob.glob(str(HERE / "data" / "stock" / "burn_*.jsonl"))):
        for l in Path(f).read_text().splitlines():
            r = json.loads(l)
            stock_order.setdefault(r["job_id"], (r.get("done_at", ""), r))
    picks = []
    for f in glob.glob(str(HERE / "saved_jobs" / "*.json")):
        try:
            j = json.load(open(f))
        except Exception:
            continue
        jid = Path(f).stem
        if j.get("status") != "complete" or jid in done or jid in RELEASED or j.get("youtube_video_id") or j.get("youtube_url"):
            continue
        rating = j.get("rating") or 0
        title = (j.get("config") or {}).get("title") or j.get("title") or ""
        if rating == 1:
            continue
        if rating >= 2:
            tier, key = (0 if rating == 3 else 1), j.get("created_at", "")
        elif jid in stock_order:
            tier, key = 2, stock_order[jid][0]
        else:
            continue
        picks.append({"job_id": jid, "tier": tier, "key": key, "rating": rating, "title": title,
                      "world": (stock_order.get(jid, (0, {}))[1] or {}).get("world")})
    picks.sort(key=lambda p: (p["tier"], p["key"]))
    return picks


def playlist_id(yt) -> str:
    if PLAYLIST_FILE.exists():
        return json.loads(PLAYLIST_FILE.read_text())["id"]
    r = yt.playlists().insert(part="snippet,status", body={
        "snippet": {"title": PLAYLIST_TITLE, "description": "Private drafts for Cole to review."},
        "status": {"privacyStatus": "private"}}).execute()
    PLAYLIST_FILE.write_text(json.dumps({"id": r["id"], "title": PLAYLIST_TITLE}))
    return r["id"]


def yt_client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_info(json.load(open(HERE / "youtube_token.json")))
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def offload(jid: str) -> None:
    """The finished mp4 (about 8 GB) is on YouTube now; move the local copy to R2 like the release media."""
    from media_store import get_store
    store = get_store()
    p = json.load(open(HERE / "saved_jobs" / f"{jid}.json")).get("visual_video_path")
    if store.enabled and p and Path(p).exists():
        ok = store.upload(p) and store.evict(p)
        print(f"  {'offloaded' if ok else 'OFFLOAD FAILED (kept local)'} {Path(p).name}", flush=True)
    elif not store.enabled:
        print("  OFFLOAD SKIPPED: R2 keys missing", flush=True)


def draft(p: dict) -> dict:
    jid = p["job_id"]
    still = json.load(open(HERE / "saved_jobs" / f"{jid}.json")).get("visual_image_path")
    if not (still and Path(still).exists()):   # a retry keeps the still it already paid for
        ap = jget(requests.post(f"{BASE}/api/visual/auto-prompt/{jid}", timeout=120))
        if not ap.get("image_prompt"):
            raise RuntimeError(f"auto-prompt failed: {ap}")
        r = jget(requests.post(f"{BASE}/api/visual/image/{jid}", json={"prompt": ap["image_prompt"]}, timeout=60))
        if r.get("error") or wait_task(jid).get("status") != "done":
            raise RuntimeError(f"image failed: {r}")
    # Gate on the jump at the loop point. wrap_ratio (jump / mean motion) punishes calm shots: the Sietch loop
    # had a clean seam by eye and wrap 2.66 (shipped loops: 1.6-5.1) but ratio 2.55 because it barely moves.
    # Shipped junction spikes ran 1.16-1.69; the loop with a smoke plume puffing every cycle hit 2.06.
    loop = HERE / "output" / f"{jid}_seedance.mp4"
    for attempt in (0, 1, 2):
        if attempt or not loop.exists():
            seedance_loop(jid)
        seam = fl_seam(jid)
        print(f"  loop attempt {attempt}: wrap {seam['wrap']}, junction {seam['junction_spike']}", flush=True)
        if seam["junction_spike"] <= 1.9 and seam["wrap"] <= 5.5:
            if not attempt:   # reusing a loop from an earlier run: attach it
                with open(loop, "rb") as fh:
                    requests.post(f"{BASE}/api/visual/upload-video/{jid}",
                                  files={"file": (loop.name, fh, "video/mp4")}, timeout=300)
            break
    else:
        raise RuntimeError(f"loop seam failed twice (junction {seam['junction_spike']})")
    r = jget(requests.post(f"{BASE}/api/visual/export/{jid}", json={
        "duration_minutes": 60,
        # Cole, 2026-11-05 on the Sietch draft: "there was no intro". The channel name fades over the opening scene;
        # only those seconds re-encode. The 2026-10-23 no-sting rule still holds: the hour opens on the scene.
        "intro": {"enabled": True, "name": "The Space of Sound", "style": "overlay", "duration": 10, "size_scale": 0.75}}, timeout=60))
    if r.get("error") or wait_task(jid, 60 * 60).get("status") != "done":
        raise RuntimeError(f"export failed: {r}")
    for attempt in range(3):
        meta = jget(requests.post(f"{BASE}/api/youtube/auto-metadata/{jid}", timeout=180))
        if meta.get("error"):
            raise RuntimeError(f"metadata failed: {meta}")
        lore = LORE.findall(f"{meta.get('title', '')} {meta.get('description', '')}")
        if not lore:
            break
        print(f"  metadata attempt {attempt}: lore words {lore}", flush=True)
    else:
        raise RuntimeError(f"metadata kept using lore words: {lore}")
    # Channel titles read "Dune | Last Light on Arrakis | 1 Hour ...", and nothing of Cole's carries an em-dash.
    title = re.sub(r"\s*[—–]\s*", " | ", meta.get("title", "").strip())[:100]
    desc = re.sub(r"\s*[—–]\s*", ", ", meta.get("description", "")).rstrip() + f"\n\n{CTA}"
    # Cole, 2026-11-05: "basically always in Project Hail Mary font which makes no sense". One big word, the world's
    # name, set in a face that suits it; the title beside the thumbnail carries the rest. No "Ambient Soundscape".
    # Studio, lifetime, suggested CTR: wide two-line caps over a cluttered room 0.7%, no text on a lit vista 1.9-2.4%.
    hook = title.split(" | ")[0]
    r = jget(requests.post(f"{BASE}/api/thumbnail/{jid}/set", json={
        "style": "cinzel" if ANCIENT_WORLDS.search(hook) else "odyssey", "hook": hook, "subtitle": "",
        "title_scale": 1.6}, timeout=60))
    if r.get("error"):
        raise RuntimeError(f"thumbnail failed: {r}")
    r = jget(requests.post(f"{BASE}/api/youtube/upload/{jid}", json={
        "title": title, "description": desc, "tags": meta.get("tags", []), "privacy": "private"}, timeout=60))
    if r.get("error"):
        raise RuntimeError(f"upload start failed: {r}")
    t0 = time.time()
    while time.time() - t0 < 3 * 60 * 60:   # an 8 GB hour took over 45 min on 2026-11-04
        s = jget(requests.get(f"{BASE}/api/youtube/upload-status/{jid}", timeout=30))
        if s.get("status") == "done":
            break
        if s.get("status") == "error":
            raise RuntimeError(f"upload failed: {s.get('message')}")
        time.sleep(10)
    else:
        raise RuntimeError("upload timed out")
    vid = json.load(open(HERE / "saved_jobs" / f"{jid}.json")).get("youtube_video_id")
    return {"title": title, "video_id": vid, "url": s.get("youtube_url")}


def record_verdicts(yt) -> list[dict]:
    """Note each uploaded draft's status when it changes: private, public, unlisted, or deleted (YouTube returns
    nothing for it). One videos.list per 50 drafts, 1 quota unit each. Returns the new rows."""
    drafts = {}
    for l in LOG.read_text().splitlines() if LOG.exists() else []:
        r = json.loads(l) if l.strip() else {}
        if r.get("video_id"):
            drafts[r["video_id"]] = r
    last = {}
    for l in VERDICTS.read_text().splitlines() if VERDICTS.exists() else []:
        if l.strip():
            r = json.loads(l)
            last[r["video_id"]] = r["status"]
    ids, seen = list(drafts), {}
    for i in range(0, len(ids), 50):
        for v in yt.videos().list(part="status", id=",".join(ids[i:i + 50])).execute().get("items", []):
            seen[v["id"]] = v["status"]["privacyStatus"]
    new = []
    for vid, d in drafts.items():
        status = seen.get(vid, "deleted")
        if last.get(vid) != status:
            new.append({"video_id": vid, "job_id": d["job_id"], "title": d.get("title"), "status": status,
                        "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    if new:
        with open(VERDICTS, "a") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in new)
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=PER_DAY)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verdicts", action="store_true", help="record publish/delete verdicts and stop")
    a = ap.parse_args()
    if a.verdicts:
        for r in record_verdicts(yt_client()):
            print(r["status"], r["video_id"], r["title"], flush=True)
        return
    q = queue()
    print(f"{time.strftime('%F %T')} queue: {len(q)} takes "
          f"({sum(p['tier'] == 0 for p in q)} 3-star, {sum(p['tier'] == 1 for p in q)} 2-star, "
          f"{sum(p['tier'] == 2 for p in q)} stock)", flush=True)
    if a.dry_run:
        for p in q[:a.n]:
            print("  would draft", p["job_id"], p["rating"], p["title"][:70])
        return
    yt = yt_client()
    try:
        record_verdicts(yt)
    except Exception as e:
        print(f"verdicts failed: {str(e)[:200]}", flush=True)
    pl = playlist_id(yt)
    made, streak = 0, 0
    for p in q:
        if made >= a.n:
            break
        free = shutil.disk_usage(HERE).free / 1e9
        if free < MIN_FREE_GB:
            print(f"STOP disk: {free:.1f} GB free", flush=True)
            break
        j = json.load(open(HERE / "saved_jobs" / f"{p['job_id']}.json"))
        rec = {"job_id": p["job_id"], "rating": p["rating"], "take_title": p["title"],
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        perc = beat_perc(j) if take_secs(j) >= 120 else None
        if perc is None:
            rec["status"] = "skipped: under 2 min or audio missing"
        elif perc > MAX_PERC:
            rec["status"] = f"skipped: beat (perc {perc})"
        else:
            try:
                rec.update(draft(p), status="private")
                if rec.get("video_id"):
                    yt.playlistItems().insert(part="snippet", body={"snippet": {
                        "playlistId": pl, "resourceId": {"kind": "youtube#video", "videoId": rec["video_id"]}}}).execute()
                offload(p["job_id"])
                made, streak = made + 1, 0
            except Exception as e:
                rec["status"] = f"failed: {str(e)[:300]}"
                streak += 1
                if "quota" in str(e).lower():
                    print("STOP: YouTube quota", flush=True)
                    with open(LOG, "a") as fh:
                        fh.write(json.dumps(rec) + "\n")
                    break
        with open(LOG, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"{time.strftime('%T')} {rec['status'][:60]:60s} {p['job_id']} {rec.get('title') or p['title'][:60]}", flush=True)
        if streak >= 3:
            print("STOP: 3 failures in a row, something upstream is broken", flush=True)
            break
    print(f"{time.strftime('%F %T')} DRAFTS DONE: {made} uploaded private to '{PLAYLIST_TITLE}'", flush=True)


if __name__ == "__main__":
    main()
