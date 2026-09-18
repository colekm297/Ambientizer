"""Cole's 'just do it' (via Chief, 2026-09-18): retitle both, prepend the CTA
line to both descriptions, post the pinned-comment text on both."""
import json, time
from youtube_publisher import YouTubePublisher

CTA = "Subscribe for the next room, and a like if this one held you. New rooms every few weeks."
JOBS = {
    "HvumlX9trg0": dict(
        title="The Odyssey | Going Home After 20 Years | 1 Hour Deep Work Ambient",
        comment="If this held you for the hour, a like tells YouTube to show it to the next person, and subscribing means the next room finds you. Trapped on Calypso's Shore is the other side of this same voyage: https://www.youtube.com/watch?v=JhV1RPOGAGw"),
    "y6YS18A8hYY": dict(
        title="Dune | Last Light on Arrakis | 1 Hour Deep Focus Ambient",
        comment="If this held you for the hour, a like tells YouTube to show it to the next person, and subscribing means the next room finds you. Dawn Over Arrakis is the other end of this same day: https://www.youtube.com/watch?v=kg-RRBuGsuQ"),
}
yt = YouTubePublisher()._get_youtube()
out = {}
for vid, j in JOBS.items():
    sn = yt.videos().list(part="snippet", id=vid).execute()["items"][0]["snippet"]
    before = {"title": sn["title"], "desc_head": sn["description"][:90]}
    desc = sn["description"]
    if not desc.startswith(CTA):
        desc = CTA + "\n\n" + desc
    body = {"id": vid, "snippet": {"title": j["title"], "description": desc,
            "tags": sn.get("tags", []), "categoryId": sn["categoryId"]}}
    if "defaultLanguage" in sn: body["snippet"]["defaultLanguage"] = sn["defaultLanguage"]
    r = yt.videos().update(part="snippet", body=body).execute()["snippet"]
    c = yt.commentThreads().insert(part="snippet", body={"snippet": {"videoId": vid,
        "topLevelComment": {"snippet": {"textOriginal": j["comment"]}}}}).execute()
    out[vid] = {"before": before, "title": r["title"], "desc_head": r["description"][:90],
                "comment_id": c["id"], "comment_head": c["snippet"]["topLevelComment"]["snippet"]["textOriginal"][:60]}
    time.sleep(1)
print(json.dumps(out, indent=2))
json.dump(out, open("logs/apply_cta_2026-09-18.json", "w"), indent=2)
