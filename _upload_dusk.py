# Dusk Over Arrakis private upload. Untracked scratch script (see _upload_fairwind.py).
import sys
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
from youtube_publisher import YouTubePublisher

D = "/Users/colemonroe/Projects/Ambientizer/output/release/dusk_arrakis"
TITLE = "Dune | Dusk Over Arrakis | 1 Hour Desert Ambient Music"
DESCRIPTION = """The sun goes down on Arrakis the way it goes down nowhere else: all at once, and then for a long time. The heat leaves the sand before the light does. Out on the ridge one figure stands and watches it happen, because there is nothing to do about it and no reason to go in yet.

The heat still shimmers over the far dunes. That is the only thing that moves.

An hour of it, warm and slow, no drums, nothing that resolves. The companion to Dawn Over Arrakis, from the other end of the day.

Visuals and music produced with AI tools, arranged and edited by hand.

#Dune #AmbientMusic #DeepWork"""
TAGS = ["dune","arrakis","dusk over arrakis","dawn over arrakis","desert ambient","dune ambient",
        "warm ambient","cinematic ambient","ambient music","deep work music","focus music",
        "study music","reading music","drone music","desert at dusk","duduk","1 hour ambient",
        "d phrygian","no drums","villeneuve"]

pub = YouTubePublisher()
result = pub.upload_video(
    video_path=f"{D}/dusk_arrakis_1h.mp4", title=TITLE, description=DESCRIPTION, tags=TAGS,
    privacy="private", thumbnail_path=f"{D}/thumbnail.png",
    on_progress=lambda pct, msg: print(f"PROGRESS {pct:.0f}% {msg}", flush=True),
)
print("RESULT:", result, flush=True)
print("DONE", flush=True)
