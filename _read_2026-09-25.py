import json, sys
sys.path.insert(0, '.')
from googleapiclient.discovery import build
from yt_analytics_pull import get_credentials, iso_today
creds = get_credentials()
yt = build("youtube", "v3", credentials=creds)
yta = build("youtubeAnalytics", "v2", credentials=creds)
ch = yt.channels().list(part="id,statistics", mine=True).execute()["items"][0]
cid = ch["id"]
print("CHANNEL", json.dumps(ch["statistics"]))
def q(**kw):
    kw.setdefault("endDate", iso_today())
    r = yta.reports().query(ids=f"channel=={cid}", **kw).execute()
    cols = [h["name"] for h in r.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in r.get("rows", [])]
def interp(curve, t, dur=3600):
    xs = [c["elapsedVideoTimeRatio"] * dur for c in curve]; ys = [c["audienceWatchRatio"] for c in curve]
    if t <= xs[0]: return ys[0]
    for i in range(1, len(xs)):
        if t <= xs[i]:
            f = (t - xs[i-1]) / (xs[i] - xs[i-1]); return ys[i-1] + f * (ys[i] - ys[i-1])
    return ys[-1]
POINTS = [("0:36",36),("5:00",300),("15:00",900),("30:00",1800),("45:00",2700),("60:00",3600)]
DUSK="y6YS18A8hYY"; FW="HvumlX9trg0"
for label, filt in [("dusk_all_since0918", f"video=={DUSK}"), ("dusk_unsub_since0918", f"video=={DUSK};subscribedStatus==UNSUBSCRIBED"), ("dusk_sub_since0918", f"video=={DUSK};subscribedStatus==SUBSCRIBED")]:
    try:
        core = q(startDate="2026-09-18", metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage", filters=filt)
        curve = q(startDate="2026-09-18", metrics="audienceWatchRatio", dimensions="elapsedVideoTimeRatio", filters=filt)
        print(label, json.dumps(core), {l: round(100*interp(curve,t),1) for l,t in POINTS} if curve else "NO CURVE", "n=",len(curve))
    except Exception as e: print(label, "ERR", e)
for label, filt in [("dusk_lifetime", f"video=={DUSK}"), ("dusk_unsub_lifetime", f"video=={DUSK};subscribedStatus==UNSUBSCRIBED")]:
    try:
        core = q(startDate="2026-09-11", metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage", filters=filt)
        curve = q(startDate="2026-09-11", metrics="audienceWatchRatio", dimensions="elapsedVideoTimeRatio", filters=filt)
        print(label, json.dumps(core), {l: round(100*interp(curve,t),1) for l,t in POINTS} if curve else "NO CURVE")
    except Exception as e: print(label, "ERR", e)
for name, vid in [("DUSK",DUSK),("FW",FW)]:
    print(name, "traffic since 09-18", json.dumps(q(startDate="2026-09-18", metrics="views,estimatedMinutesWatched", dimensions="insightTrafficSourceType", filters=f"video=={vid}", sort="-views")))
    print(name, "per day", json.dumps(q(startDate="2026-09-11", metrics="views,estimatedMinutesWatched,subscribersGained", dimensions="day", filters=f"video=={vid}")))
print("CHANNEL per day since 09-04", json.dumps(q(startDate="2026-09-04", metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost", dimensions="day")))
print("YPP 365d watch by traffic", json.dumps(q(startDate="2025-09-25", metrics="estimatedMinutesWatched,views", dimensions="insightTrafficSourceType", sort="-estimatedMinutesWatched")))
