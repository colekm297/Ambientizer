# Hail Mary / Tau Ceti private upload (same shape as _upload_dusk.py). Copy from output/release/hailmary_tauceti/copy.md.
import sys
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
from youtube_publisher import YouTubePublisher
D = "/Users/colemonroe/Projects/Ambientizer/output/release/hailmary_tauceti"
TITLE = "Project Hail Mary | 12 Light Years From Home | 1 Hour Space Ambience for Deep Focus"
DESCRIPTION = """If you liked this track, please consider liking and subscribing. I'll be putting out new music weekly.

Twelve light years from Earth, a small ship hangs near Tau Ceti and one person stands at the window looking at a star that is not the sun. Nothing is coming. Nothing has to be done right now. The star is warm through the glass and the panels hum.

An hour of it, slow and warm, no drums, nothing that resolves. Organ pad, cello, a distant flute, and a little starlight on top. Made for reading, deep work, or sitting with something.

Visuals and music produced with AI tools, arranged and edited by hand.

#ProjectHailMary #SpaceAmbience #DeepWork"""
TAGS = ["project hail mary","project hail mary ambience","project hail mary ambient","tau ceti","space ambience",
        "space sounds","space ambient","interstellar ambient","cinematic ambient","ambient music","deep work music",
        "focus music","study music","reading music","drone music","1 hour ambient","f lydian","no drums",
        "sci-fi ambient","andy weir"]
pub = YouTubePublisher()
result = pub.upload_video(video_path=f"{D}/hailmary_tauceti_1h.mp4", title=TITLE, description=DESCRIPTION, tags=TAGS,
    privacy="private", thumbnail_path=f"{D}/thumb_h2.png",
    on_progress=lambda pct, msg: print(f"PROGRESS {pct:.0f}% {msg}", flush=True))
print("RESULT:", result, flush=True); print("DONE", flush=True)
