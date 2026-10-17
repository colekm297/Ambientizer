# Frodo Sails West private upload. Untracked scratch script (see _upload_dusk.py).
import sys
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
from youtube_publisher import YouTubePublisher

D = "/Users/colemonroe/Projects/Ambientizer/output/release/frodo_west"
TITLE = "The Lord of the Rings | Frodo Sails West | 1 Hour Deep Focus Ambient"
DESCRIPTION = """The very end of the story. The white ship leaves the Grey Havens with Frodo, Gandalf and Bilbo aboard, and for a long while there is only grey sea and the creak of rope and timber. Then the veil draws back, and the light on the sail turns from silver to gold, and far ahead there are white shores and a green country under a swift sunrise.

A soft heartbeat far back, cellos and horns that come closer and warmer past the middle, and a distant wordless voice answered by harp and low whistle. An hour of it, unhurried, no fade, the ship still sailing on at the end.

Visuals and music produced with AI tools, arranged and edited by hand.

If you liked this track, please consider liking and subscribing!

#LordOfTheRings #AmbientMusic #DeepWork"""
TAGS = ["lord of the rings","frodo","grey havens","into the west","undying lands","tolkien","middle earth",
        "lotr ambient","warm ambient","cinematic ambient","ambient music","deep work music","focus music",
        "study music","reading music","drone music","sea at dawn","1 hour ambient","d major","no drums"]

pub = YouTubePublisher()
result = pub.upload_video(
    video_path=f"{D}/frodo_west_1h.mp4", title=TITLE, description=DESCRIPTION, tags=TAGS,
    privacy="private", thumbnail_path=f"{D}/thumbnail.png",
    on_progress=lambda pct, msg: print(f"PROGRESS {pct:.0f}% {msg}", flush=True),
)
print("RESULT:", result, flush=True)
print("DONE", flush=True)
