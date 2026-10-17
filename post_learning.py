#!/usr/bin/env python3
"""post_learning.py — the learning loop for everything around a release that is not the music:
the title, the thumbnail, the visual loop, and when it went out.

The music already learns from Cole's stars (daily_experiment.py). This does the same job for
posts, from YouTube's own numbers, which are the only honest judge of a thumbnail or a title.

  record   log the choices made for one published video (title format, thumbnail style and
           measured look, visual motion numbers, publish time) into data/post_ledger.jsonl
  pull     weekly: for every public video, fetch views, average view %, subs gained, the
           retention curve at 1/10/30/60 min, and traffic sources (search terms, suggested-next
           neighbours) into data/post_outcomes.json, with a dated snapshot appended to
           data/post_outcomes_history.jsonl so week-over-week deltas exist
  lessons  Claude (Opus 5.5 via llm.py) reads choices + outcomes and rewrites
           data/post_lessons.md, then docs/POST-EXPERIMENTS.md is regenerated
  backfill one-time: build ledger rows for the existing catalogue from brand/ref thumbnails and
           the live titles so there is evidence on day one

Impressions and CTR are not in the API (Studio only). A thumbnail's outcome here is views by
traffic source and subs gained; its CTR has to come from Studio's Test & compare by hand.

Weekly: launchd com.cole.ambientizer-post-learning (Mondays 08:00) runs `pull` then `lessons`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DATA = HERE / "data"
LEDGER = DATA / "post_ledger.jsonl"
OUTCOMES = DATA / "post_outcomes.json"
HISTORY = DATA / "post_outcomes_history.jsonl"
LESSONS = DATA / "post_lessons.md"
REPORT = HERE / "docs" / "POST-EXPERIMENTS.md"
REF = HERE / "brand" / "ref"

IPS = ["Dune", "The Odyssey", "Project Hail Mary", "The Lord of the Rings", "Lord of the Rings", "Interstellar"]


def load_env():
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


# ───────────────────────────── attributes of a choice ─────────────────────────────

def title_attrs(title: str) -> dict:
    t = title or ""
    first = t.split("|")[0].strip()
    ip = next((ip for ip in IPS if ip.lower() in t.lower()), None)
    fmt = "ip_first" if ip and first.lower().startswith(ip.lower()) else ("ip_inside" if ip else "no_ip")
    return {
        "title_format": fmt, "ip": ip, "title_chars": len(t), "pipes": t.count("|"),
        "has_hour_tag": bool(re.search(r"\b(\d+ hours?|\[\d+ HOURS?\])", t, re.I)),
        "has_use_case": bool(re.search(r"deep work|focus|study|sleep|reading", t, re.I)),
        "has_emoji": bool(re.search(r"[\U0001F300-\U0001FAFF☀-➿]", t)),
        "is_short": "#shorts" in t.lower(),
    }


def thumb_attrs(path: str | Path) -> dict:
    """What a thumbnail looks like, measured, not judged: warmth, brightness, contrast, how much of
    the frame is near-white (type and sky), and whether the lower third is darker (a scrim)."""
    from PIL import Image
    import numpy as np
    im = Image.open(path).convert("RGB").resize((320, 180))
    a = np.asarray(im).astype(float)
    lum = a.mean(axis=2)
    r, b = a[..., 0], a[..., 2]
    lower, upper = lum[120:], lum[:120]
    return {
        "warmth": round(float((r - b).mean()), 1),
        "luminance": round(float(lum.mean()), 1),
        "contrast": round(float(lum.std()), 1),
        "white_share": round(float((lum > 230).mean()), 3),
        "lower_third_darker_by": round(float(upper.mean() - lower.mean()), 1),
    }


def visual_attrs(loop_path: str | Path) -> dict:
    """Motion numbers of the loop cell from fal_loop.seam_report (wrap < 2 reads clean on a calm loop)."""
    try:
        import fal_loop as fl
        rep = fl.seam_report(str(loop_path))
        keep = {k: rep[k] for k in ("wrap", "wrap_ratio", "speed", "speed_envelope", "detail", "detail_swing") if k in rep}
        keep["cell_seconds"] = round(float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(loop_path)],
            capture_output=True, text=True).stdout.strip() or 0), 2)
        return keep
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)[:160]}


def ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]


def write_ledger(rows: list[dict]):
    DATA.mkdir(exist_ok=True)
    LEDGER.write_text("".join(json.dumps(r) + "\n" for r in rows))


def upsert(row: dict):
    rows = [r for r in ledger() if r.get("video_id") != row["video_id"]]
    rows.append(row)
    write_ledger(rows)


# ───────────────────────────── record ─────────────────────────────

def cmd_record(a):
    row = {"video_id": a.video_id, "job_id": a.job, "recorded": dt.date.today().isoformat(),
           "title": a.title, "world": a.world, "thumb_style": a.thumb_style,
           "visual_style": a.visual_style, "notes": a.notes, "source": "release"}
    row.update(title_attrs(a.title))
    if a.thumbnail:
        row["thumb"] = thumb_attrs(a.thumbnail)
    if a.loop:
        row["visual"] = visual_attrs(a.loop)
    if a.job:
        try:
            j = json.loads((HERE / "saved_jobs" / f"{a.job}.json").read_text())
            row["music_stars"] = int(j.get("rating") or 0)
        except Exception:  # noqa: BLE001
            pass
    upsert(row)
    print(json.dumps(row, indent=1))


# ───────────────────────────── pull ─────────────────────────────

def clients():
    import yt_analytics_pull as y
    from googleapiclient.discovery import build
    creds = y.get_credentials()
    return y, build("youtube", "v3", credentials=creds), build("youtubeAnalytics", "v2", credentials=creds)


def per_video_traffic(yta, channel_id, video_id, start):
    from googleapiclient.errors import HttpError
    out = {}
    try:
        r = yta.reports().query(ids=f"channel=={channel_id}", startDate=start, endDate=dt.date.today().isoformat(),
                                metrics="views,estimatedMinutesWatched", dimensions="insightTrafficSourceType",
                                filters=f"video=={video_id}", sort="-views").execute()
        cols = [h["name"] for h in r.get("columnHeaders", [])]
        out["sources"] = [dict(zip(cols, row)) for row in r.get("rows", [])]
    except HttpError as e:
        out["sources_error"] = str(e)[:160]
    for src, key in (("YT_SEARCH", "search_terms"), ("RELATED_VIDEO", "suggested_from")):
        try:
            r = yta.reports().query(ids=f"channel=={channel_id}", startDate=start, endDate=dt.date.today().isoformat(),
                                    metrics="views", dimensions="insightTrafficSourceDetail",
                                    filters=f"video=={video_id};insightTrafficSourceType=={src}",
                                    sort="-views", maxResults=10).execute()
            out[key] = [[row[0], row[1]] for row in r.get("rows", [])]
        except HttpError as e:
            out[key + "_error"] = str(e)[:120]
    return out


def retention_points(curve) -> dict:
    """audienceWatchRatio at 1, 10, 30 and 60 minutes of a one-hour video (ratio axis is 0..1 of length)."""
    if not isinstance(curve, list) or not curve:
        return {}
    pts = {}
    for label, ratio in (("r_1min", 1 / 60), ("r_10min", 10 / 60), ("r_30min", 0.5), ("r_end", 0.99)):
        best = min(curve, key=lambda p: abs(float(p.get("elapsedVideoTimeRatio", 0)) - ratio))
        pts[label] = round(float(best.get("audienceWatchRatio", 0)), 3)
    pts["r_start"] = round(float(curve[0].get("audienceWatchRatio", 0)), 3)
    return pts


def cmd_pull(a):
    y, yt, yta = clients()
    ch = y.get_channel(yt)
    channel_id = ch["id"]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    videos, _nonpublic = y.hydrate_video_stats(yt, y.list_all_videos(yt, uploads))
    today = dt.date.today().isoformat()
    prev = json.loads(OUTCOMES.read_text()) if OUTCOMES.exists() else {}
    out = {"pulled_at": dt.datetime.now().isoformat(timespec="seconds"), "channel": ch.get("statistics"), "videos": {}}
    for v in videos:
        vid = v["video_id"]
        if v.get("privacy") not in (None, "public"):
            continue
        start = (v.get("published_at") or "")[:10] or "2026-01-01"
        core = y.video_analytics(yta, channel_id, vid, start)
        rec = {
            "title": v["title"], "published_at": v.get("published_at"), "duration_sec": v.get("duration_sec"),
            "lifetime_views": v.get("lifetime_views"), "likes": v.get("lifetime_likes"), "comments": v.get("lifetime_comments"),
            "views": core.get("views"), "minutes_watched": core.get("estimatedMinutesWatched"),
            "avg_view_pct": core.get("averageViewPercentage"), "avg_view_sec": core.get("averageViewDuration"),
            "subs_gained": core.get("subscribersGained"), "subs_lost": core.get("subscribersLost"),
        }
        if (v.get("duration_sec") or 0) >= 1200:
            rec["retention"] = retention_points(y.retention_curve(yta, channel_id, vid, start))
        rec.update(per_video_traffic(yta, channel_id, vid, start))
        p = (prev.get("videos") or {}).get(vid)
        if p and p.get("views") is not None and rec.get("views") is not None:
            rec["views_since_last_pull"] = rec["views"] - p["views"]
            rec["subs_since_last_pull"] = (rec.get("subs_gained") or 0) - (p.get("subs_gained") or 0)
        out["videos"][vid] = rec
        print(f"  {vid} {v['title'][:50]:50s} views {rec.get('views')} avg% {rec.get('avg_view_pct')} subs +{rec.get('subs_gained')}", flush=True)
    DATA.mkdir(exist_ok=True)
    OUTCOMES.write_text(json.dumps(out, indent=1))
    with HISTORY.open("a") as fh:
        fh.write(json.dumps({"date": today, "channel": out["channel"],
                             "videos": {k: {kk: vv for kk, vv in r.items() if kk in ("views", "avg_view_pct", "subs_gained", "minutes_watched")}
                                        for k, r in out["videos"].items()}}) + "\n")
    print(f"pulled {len(out['videos'])} public videos -> {OUTCOMES}")


# ───────────────────────────── backfill ─────────────────────────────

# Thumbnail style labels for the catalogue as shipped, judged from brand/ref (hand labels, 2026-10-16):
# ip_first = big IP name as the headline with a small subtitle; scene_only = no type; mood_text = mood words,
# not the IP; emoji_title = the early emoji-styled uploads.
BACKFILL_STYLES = {
    "HvumlX9trg0": ("ip_first", "live_HvumlX9trg0.jpg", "sailing_sea_dawn"),
    "y6YS18A8hYY": ("ip_first", "live_y6YS18A8hYY.jpg", "desert_dusk_figure"),
    "JhV1RPOGAGw": ("mood_text", "calypso_JhV1RPOGAGw.jpg", "shore_figure"),
    "kg-RRBuGsuQ": ("mood_text", "dawn_kg-RRBuGsuQ.jpg", "desert_dawn"),
    "7E-NO3zf7w4": ("mood_text", "desert_rain_7E-NO3zf7w4.jpg", "desert_rain"),
    "pr5JhPlr18c": ("mood_text", "escher_pr5JhPlr18c.jpg", "abstract"),
    "ofA7JRdzH8k": ("mood_text", "sanctuary_ofA7JRdzH8k.jpg", "interior"),
    "wHOZ8ppszSI": ("mood_text", "sirens_wHOZ8ppszSI.jpg", "dark_sea"),
    "frJb60y4d5M": ("mood_text", "small_light_frJb60y4d5M.jpg", "space"),
    "s0s476Lnjtk": ("mood_text", "spacecraft_s0s476Lnjtk.jpg", "space"),
    "tg1Ixcm_-6k": ("mood_text", "temples_tg1Ixcm_-6k.jpg", "temple_interior"),
    "nAiWwRx1Tk0": ("mood_text", "two_minds_nAiWwRx1Tk0.jpg", "space"),
}


def cmd_backfill(a):
    outcomes = json.loads(OUTCOMES.read_text()) if OUTCOMES.exists() else {"videos": {}}
    have = {r["video_id"] for r in ledger()}
    n = 0
    for vid, (style, ref, scene) in BACKFILL_STYLES.items():
        if vid in have and not a.force:
            continue
        info = outcomes["videos"].get(vid, {})
        row = {"video_id": vid, "recorded": dt.date.today().isoformat(), "title": info.get("title", ""),
               "published_at": info.get("published_at"), "thumb_style": style, "visual_style": scene,
               "source": "backfill", "notes": "catalogue as shipped; style labels by hand"}
        row.update(title_attrs(row["title"]))
        if (REF / ref).exists():
            row["thumb"] = thumb_attrs(REF / ref)
        upsert(row); n += 1
    print(f"backfilled {n} rows")


# ───────────────────────────── lessons + report ─────────────────────────────

def joined() -> list[dict]:
    outcomes = json.loads(OUTCOMES.read_text()) if OUTCOMES.exists() else {"videos": {}}
    rows = []
    for r in ledger():
        o = outcomes["videos"].get(r["video_id"], {})
        rows.append({**r, "outcome": {k: o.get(k) for k in ("published_at", "views", "views_since_last_pull", "avg_view_pct",
                                                            "subs_gained", "subs_since_last_pull", "retention", "sources",
                                                            "search_terms", "suggested_from", "likes", "comments")}})
    rows.sort(key=lambda r: (r.get("outcome", {}).get("published_at") or r.get("published_at") or ""), reverse=True)
    return rows


def cmd_lessons(a):
    import anthropic
    from llm import llm_create, llm_text
    load_env()
    rows = joined()
    outcomes = json.loads(OUTCOMES.read_text()) if OUTCOMES.exists() else {}
    lessons = LESSONS.read_text() if LESSONS.exists() else "(none yet: first run)"
    algo = (HERE / "docs" / "ALGORITHM-LEVERS.md")
    algo_txt = algo.read_text() if algo.exists() else ""
    system = (
        "You run the learning loop for the non-music half of The Space of Sound, a YouTube channel of one-hour "
        "ambient videos set in story worlds people love (Dune, The Odyssey, Project Hail Mary, The Lord of the Rings). "
        "Cole, the owner, decides; your job is to turn the numbers into lessons about titles, thumbnails, visual loops "
        "and publish timing, and to recommend concrete choices for the next release. Rules: numbers before claims; "
        "name the video ids behind every lesson; separate what the data shows from what you suspect; bought views "
        "(Calypso JhV1RPOGAGw, about 1,900 of its views were advertising) prove nothing; impressions and CTR are not "
        "available, so judge thumbnails by views from browse and suggested traffic and subs gained, not by a CTR you "
        "cannot see; retention at 1 min is the thumbnail-and-title promise being kept or broken, retention at 30 min "
        "is the visual and the music holding. Small numbers: say when a difference is inside noise. Plain language, "
        "no hype, no em-dashes.")
    user = (
        f"Channel today: {json.dumps(outcomes.get('channel'))}, pulled {outcomes.get('pulled_at')}.\n\n"
        f"Every video with the choices made for it and its outcomes (newest first):\n{json.dumps(rows, indent=1)}\n\n"
        f"Channel-level notes already established:\n{algo_txt[:6000]}\n\n"
        f"Your lessons so far (rewrite the whole file; keep what still holds, revise what the new numbers contradict):\n{lessons}\n\n"
        f"Today is {dt.date.today().isoformat()}. Return the full new lessons file as markdown with these sections: "
        f"What the numbers show (each lesson with video ids and the figures), What is still a guess, "
        f"Next release: recommended title format, thumbnail style, visual, publish day and hour (PT), each in one line "
        f"with the evidence, Open tests (one variable each).")
    client = anthropic.Anthropic()
    # Opus 5.5 thinks inside max_tokens; the first run at 16000 cut the file off mid-sentence.
    # The SDK refuses a non-streaming call whose max_tokens implies more than 10 minutes unless a timeout is
    # given explicitly; 32000 tokens with a 25-minute timeout passes the guard and leaves room for thinking.
    resp = llm_create(client, effort="high", max_tokens=32000, timeout=1500, system=system,
                      messages=[{"role": "user", "content": user}])
    text = llm_text(resp).strip()
    print(f"stop_reason={getattr(resp, 'stop_reason', None)} chars={len(text)}", flush=True)
    if getattr(resp, "stop_reason", None) == "max_tokens":
        text += "\n\n(Output hit the token limit; this file is incomplete. Raise max_tokens in post_learning.py.)"
    LESSONS.write_text(f"LESSONS (updated {dt.date.today().isoformat()})\n\n{text}\n")
    write_report(rows, outcomes)
    print(f"lessons written -> {LESSONS}\nreport -> {REPORT}")


def write_report(rows, outcomes):
    lines = ["# Post experiments: titles, thumbnails, visuals, timing", "",
             "What was chosen for each release and what YouTube did with it. Choices are logged by "
             "`post_learning.py record` at upload; outcomes come from the Analytics API every Monday "
             "(`post_learning.py pull`); lessons are rewritten by Claude after each pull.", "",
             f"Last pull: {outcomes.get('pulled_at', 'never')}. Channel: {json.dumps(outcomes.get('channel'))}", "",
             "| Published | Video | Title format | Thumb style | Visual | Views | +since last | Avg % | Subs | r@1m | r@30m | Top source |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        o = r.get("outcome", {}) or {}
        ret = o.get("retention") or {}
        srcs = o.get("sources") or []
        top = f"{srcs[0]['insightTrafficSourceType']} {srcs[0]['views']}" if srcs else ""
        lines.append(f"| {(o.get('published_at') or r.get('published_at') or '')[:10]} | {r['video_id']} {str(r.get('title',''))[:38]} | "
                     f"{r.get('title_format','')} | {r.get('thumb_style','')} | {r.get('visual_style','')} | {o.get('views','')} | "
                     f"{o.get('views_since_last_pull','')} | {o.get('avg_view_pct','')} | {o.get('subs_gained','')} | "
                     f"{ret.get('r_1min','')} | {ret.get('r_30min','')} | {top} |")
    lines += ["", "## Lessons", "", LESSONS.read_text() if LESSONS.exists() else "(none yet)"]
    REPORT.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record"); r.add_argument("video_id"); r.add_argument("--job"); r.add_argument("--title", required=True)
    r.add_argument("--world"); r.add_argument("--thumb-style", required=True); r.add_argument("--thumbnail")
    r.add_argument("--visual-style"); r.add_argument("--loop"); r.add_argument("--notes", default="")
    r.set_defaults(fn=cmd_record)
    p = sub.add_parser("pull"); p.set_defaults(fn=cmd_pull)
    b = sub.add_parser("backfill"); b.add_argument("--force", action="store_true"); b.set_defaults(fn=cmd_backfill)
    l = sub.add_parser("lessons"); l.set_defaults(fn=cmd_lessons)
    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
