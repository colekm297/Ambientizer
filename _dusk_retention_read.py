"""Side-by-side retention read: Dusk vs Dawn vs Temples. Read-only analytics."""
import json, sys
from googleapiclient.discovery import build
from yt_analytics_pull import get_credentials, iso_today

VIDS = [("Dusk Over Arrakis", "y6YS18A8hYY", "2026-09-11"),
        ("Dawn Over Arrakis", "kg-RRBuGsuQ", "2026-07-23"),
        ("Beneath the Desert Temples", "tg1Ixcm_-6k", "2026-06-05")]
POINTS = [("0:36", 36), ("1:12", 72), ("5:00", 300), ("15:00", 900),
          ("30:00", 1800), ("45:00", 2700), ("60:00", 3600)]

creds = get_credentials()
yt = build("youtube", "v3", credentials=creds)
yta = build("youtubeAnalytics", "v2", credentials=creds)
cid = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]

def q(**kw):
    r = yta.reports().query(ids=f"channel=={cid}", endDate=iso_today(), **kw).execute()
    cols = [h["name"] for h in r.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in r.get("rows", [])]

def interp(curve, t, dur):
    xs = [c["elapsedVideoTimeRatio"] * dur for c in curve]
    ys = [c["audienceWatchRatio"] for c in curve]
    if t <= xs[0]: return ys[0]
    for i in range(1, len(xs)):
        if t <= xs[i]:
            f = (t - xs[i-1]) / (xs[i] - xs[i-1])
            return ys[i-1] + f * (ys[i] - ys[i-1])
    return ys[-1]

out = {}
for name, vid, start in VIDS:
    st = yt.videos().list(part="statistics,contentDetails", id=vid).execute()["items"][0]
    core = q(startDate=start, metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost", filters=f"video=={vid}")
    curve = q(startDate=start, metrics="audienceWatchRatio", dimensions="elapsedVideoTimeRatio", filters=f"video=={vid}")
    traffic = q(startDate=start, metrics="views,estimatedMinutesWatched", dimensions="insightTrafficSourceType", filters=f"video=={vid}", sort="-views")
    dur = 3600
    out[name] = {"id": vid, "lifetime_views": int(st["statistics"].get("viewCount", 0)),
                 "core": core[0] if core else {}, "traffic": traffic,
                 "curve_points": {lbl: round(100 * interp(curve, t, dur), 1) for lbl, t in POINTS} if curve else None,
                 "n_curve": len(curve)}
json.dump(out, open("output/_yt_analytics/dusk_read_" + iso_today() + ".json", "w"), indent=2)
print(json.dumps(out, indent=2))
