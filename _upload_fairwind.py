# Fair Wind Home private upload. Untracked scratch script (see other _upload_*.py).
import sys
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
from youtube_publisher import YouTubePublisher

TITLE = "Fair Wind Home | The Odyssey [1 HOUR] | Warm Ambient for Deep Work and Focus"
DESCRIPTION = """The wind came up at dawn on the tenth year and it was the right wind, finally, the one that had been withheld the whole time. Below the headland the water went gold in a long strip out to where the ship sat, small and patient, sails already drawing.

There is an olive tree on that slope that has watched every departure and every failure to depart. The lavender moves. Nothing else on the cliff does.

An hour of it, unhurried, no drums, nothing that resolves. What's happening in the picture is a man being allowed to go home, and the sea not making a thing of it.

Visuals and music produced with AI tools, arranged and edited by hand.

#Odyssey #AmbientMusic #DeepWork"""
TAGS = ["fair wind","the odyssey","homecoming","ithaca","odysseus","greek mythology",
        "warm ambient","cinematic ambient","ambient music","deep work music","focus music",
        "study music","reading music","drone music","golden hour","sea at dawn",
        "1 hour ambient","e major","no drums","sailing"]

pub = YouTubePublisher()
def prog(pct, msg):
    print(f"PROGRESS {pct:.0f}% {msg}", flush=True)

result = pub.upload_video(
    video_path="/Users/colemonroe/Projects/Ambientizer/output/release/fairwind/fairwind_1h.mp4",
    title=TITLE, description=DESCRIPTION, tags=TAGS, privacy="private",
    thumbnail_path="/Users/colemonroe/Projects/Ambientizer/output/release/fairwind/thumbnail.png",
    on_progress=prog,
)
print("RESULT:", result, flush=True)
print("DONE", flush=True)
