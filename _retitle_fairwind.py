"""Wait for youtube_token.json to carry youtube.force-ssl, then retitle Fair Wind.

Description, tags, categoryId are read back from the live video and sent
unchanged; only the title moves. Runs detached (see AGENTS.md long-job rule).
"""
import time
from pathlib import Path

from youtube_publisher import YouTubePublisher

VIDEO_ID = "HvumlX9trg0"
NEW_TITLE = "The Odyssey | Fair Wind Home | 1 Hour Warm Ambient for Deep Work"
TOKEN = Path(__file__).with_name("youtube_token.json")


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


log(f"armed; polling {TOKEN} for youtube.force-ssl")
while True:
    try:
        if TOKEN.exists() and "youtube.force-ssl" in TOKEN.read_text():
            break
    except OSError:
        pass
    time.sleep(15)

log("force-ssl scope present; applying title")
yt = YouTubePublisher()._get_youtube()
snippet = yt.videos().list(part="snippet", id=VIDEO_ID).execute()["items"][0]["snippet"]
log(f"current title: {snippet['title']!r}")
snippet["title"] = NEW_TITLE
body = {"id": VIDEO_ID, "snippet": {k: snippet[k] for k in ("title", "description", "tags", "categoryId") if k in snippet}}
if "defaultLanguage" in snippet:
    body["snippet"]["defaultLanguage"] = snippet["defaultLanguage"]
res = yt.videos().update(part="snippet", body=body).execute()
log(f"done; live title now {res['snippet']['title']!r}")
