"""Cole 2026-09-18: drop the 'room' metaphor. Plain wording on description line 1
and the pinned comments (edited in place so the pins survive)."""
import json
from youtube_publisher import YouTubePublisher

OLD = "Subscribe for the next room, and a like if this one held you. New rooms every few weeks."
NEW = "If you liked this track, please consider liking and subscribing. I'll be putting out new music weekly."
JOBS = {
    "HvumlX9trg0": ("UgwvvLCs38KAKYM4iXB4AaABAg",
        "If you liked this track, please consider liking and subscribing! I'll be putting out new music weekly. "
        "If you want more like this, Trapped on Calypso's Shore is the companion piece: https://www.youtube.com/watch?v=JhV1RPOGAGw"),
    "y6YS18A8hYY": ("Ugyja-JxHCcJjT4JlVx4AaABAg",
        "If you liked this track, please consider liking and subscribing! I'll be putting out new music weekly. "
        "If you want more like this, Dawn Over Arrakis is the companion piece: https://www.youtube.com/watch?v=kg-RRBuGsuQ"),
}
yt = YouTubePublisher()._get_youtube()
out = {}
for vid, (cid, ctext) in JOBS.items():
    sn = yt.videos().list(part="snippet", id=vid).execute()["items"][0]["snippet"]
    desc = sn["description"]
    assert desc.startswith(OLD), desc[:80]
    desc = NEW + desc[len(OLD):]
    body = {"id": vid, "snippet": {"title": sn["title"], "description": desc, "tags": sn.get("tags", []), "categoryId": sn["categoryId"]}}
    if "defaultLanguage" in sn: body["snippet"]["defaultLanguage"] = sn["defaultLanguage"]
    r = yt.videos().update(part="snippet", body=body).execute()["snippet"]
    c = yt.comments().update(part="snippet", body={"id": cid, "snippet": {"textOriginal": ctext}}).execute()
    out[vid] = {"title": r["title"], "desc_line1": r["description"].split("\n")[0], "comment_id": c["id"], "comment": c["snippet"]["textOriginal"]}
print(json.dumps(out, indent=2)); json.dump(out, open("logs/apply_cta_plain_2026-09-18.json", "w"), indent=2)
