# Penelope at the Loom private upload. Untracked scratch script (see _upload_frodo.py).
import sys
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
from youtube_publisher import YouTubePublisher

D = "/Users/colemonroe/Projects/Ambientizer/output/release/penelope_loom"
TITLE = "The Odyssey | Penelope at the Loom | 1 Hour Deep Focus Ambient"
DESCRIPTION = """Night in the palace on Ithaca. Penelope sits at the loom with the lamps lit, weaving the shroud she will unpick again before morning, as she has for years, while the sea outside the window stays empty.

The loom keeps slow time, a muted wooden pulse like a heartbeat. A lyre plays a four-note figure that rises and falls back, over and over like thread, answered now and then by a breathy flute. Cellos and low horns gather through the middle and ease off into lamplight at the end. An hour of it, unhurried, no fade.

Visuals and music produced with AI tools, arranged and edited by hand.

If you liked this track, please consider liking and subscribing!

#Odyssey #AmbientMusic #DeepWork"""
TAGS = ["the odyssey","penelope","ithaca","odysseus","homer","greek mythology","odyssey ambient","warm ambient",
        "cinematic ambient","ambient music","deep work music","focus music","study music","reading music",
        "lyre music","night sea","lamplight","1 hour ambient","a dorian","no vocals"]

pub = YouTubePublisher()
result = pub.upload_video(
    video_path=f"{D}/penelope_loom_1h.mp4", title=TITLE, description=DESCRIPTION, tags=TAGS,
    privacy="private", thumbnail_path=f"{D}/thumbnail.png",
    on_progress=lambda pct, msg: print(f"PROGRESS {pct:.0f}% {msg}", flush=True),
)
print("RESULT:", result, flush=True)
print("DONE", flush=True)
