# Ambientizer

> An AI ambient soundscape studio: prompt → multi-layer composition → real-time browser mixer → AI visuals → YouTube publish → growth automation.

Ambientizer is a single-user, locally-hosted Flask app that turns a one-paragraph creative brief into a finished YouTube-ready ambient music video. It chains Claude (composition planning), ElevenLabs Music v1 (audio generation), Web Audio API (live mixing in the browser), xAI Grok (cover image), and ffmpeg (final video render and live streaming), and ships with a "Distribute" tab that automates Shorts cutting, SEO metadata, ads briefs, and community-post drafts.

See [`AMBIENTIZER_README.md`](./AMBIENTIZER_README.md) for the full architecture deep-dive.

## Features

- **Prompt → multi-layer SoundscapeConfig** via Claude. Each layer gets its own ElevenLabs Music v1 prompt, fade behavior, panning, and effects chain.
- **Browser-native live mixer.** Per-layer gain, mute, solo, FX tweaking, and a master fade preview that matches the YouTube export sample-for-sample.
- **AI-driven mastering** with a loudness/critique feedback loop (Gemini listens, Claude tunes the chain).
- **Visuals tab.** Generates a scene image with xAI Grok, animates it (Ken Burns / custom video), then renders an MP4 at the correct length.
- **YouTube publish.** OAuth-based upload with auto-compressed thumbnails (handles the 2 MB cap transparently) and resumable retries.
- **Distribute tab.**
  - **Shorts factory** — Gemini picks the most atmospheric segment, ffmpeg renders vertical 9:16 with blurred letterbox or Ken-Burns-on-image.
  - **SEO metadata v2** — comparable channels, 3 title variants, thumbnail prompt.
  - **Ads brief generator** — Claude drafts a YouTube Ads campaign brief from the track.
  - **Community / Reddit / Discord drafts** — copy-paste ready posts; Discord can post directly via webhook.
  - **24/7 live stream** — ffmpeg RTMP loop pushing your catalog to YouTube Live, with playlist management and status UI.

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.13, Flask |
| LLM | Anthropic Claude (Sonnet 4) |
| Audio gen | ElevenLabs Music v1 + SFX v2 |
| Audio DSP | pydub, pedalboard, librosa, pyloudnorm |
| Reference analysis | Google Gemini 2.5 |
| Client | Vanilla JS + Web Audio API |
| Visuals | xAI Grok image generation |
| Video / stream | ffmpeg, ffprobe |
| YouTube | Google OAuth2 + YouTube Data API v3 |

## Requirements

- **Python 3.13+**
- **ffmpeg** and **ffprobe** on `PATH` (`brew install ffmpeg` on macOS, `apt install ffmpeg` on Debian/Ubuntu)
- API keys for:
  - [Anthropic Claude](https://console.anthropic.com/) — required
  - [Google Gemini](https://aistudio.google.com/apikey) — required
  - [ElevenLabs](https://elevenlabs.io/app/settings/api-keys) — required
  - [xAI Grok](https://console.x.ai/) — optional (only needed for the Visuals tab)
- A Google Cloud OAuth 2.0 client (Desktop app) with the YouTube Data API enabled, if you want the YouTube publishing / Distribute features.

## Setup

```bash
git clone https://github.com/colekm297/Ambientizer.git
cd Ambientizer

python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and fill in your keys
```

### YouTube OAuth (optional)

Only needed if you want the Publish / Distribute tabs.

1. In [Google Cloud Console](https://console.cloud.google.com/), create a new project.
2. Enable **YouTube Data API v3**.
3. Create an **OAuth 2.0 Client ID** of type **Desktop app**.
4. Download the JSON and save it as `client_secret.json` in the project root.
5. The first time you click "Connect YouTube" in the app, it'll open a browser to consent.

`client_secret.json` and `youtube_token.json` are in `.gitignore` — they'll never be committed.

## Run

```bash
source .venv/bin/activate
python -m web.app
```

Then open <http://127.0.0.1:5050>.

## Project layout

```
Ambientizer/
├── web/                    Flask app, frontend, templates
│   ├── app.py              ~4000 lines, 70+ REST routes
│   ├── static/{app,mixer}.js, style.css
│   └── templates/index.html
├── theme_interpreter.py    Claude: prompt → SoundscapeConfig
├── sample_generator.py     ElevenLabs API wrapper + caching
├── audio_engine.py         DSP: mixing, looping, effects
├── audio_critic.py         Gemini/Claude audio critique
├── mix_master.py           AI-driven mastering chain
├── visual_generator.py     xAI Grok image gen + Ken Burns
├── youtube_publisher.py    OAuth + resumable upload + thumbnail compressor
├── upload_worker.py        Detached upload subprocess
├── distribute_shorts.py    Shorts segment picker + vertical renderer
├── distribute_stream.py    24/7 RTMP live stream worker
├── reference_analyzer.py   Gemini reference-track ingest
├── orchestrator.py         CLI / batch runner
├── schemas.py              Dataclasses + enums
└── requirements.txt
```

## Notes

- This is a personal project I built for my own channel; treat it as reference code, not a polished library. Many features assume a single user and a single local machine.
- The Reddit / Community draft generators produce text only — actual posting through those APIs is rate-limited and TOS-sensitive, so the app deliberately stops at "click to copy". Discord posts are direct because webhooks are explicitly user-controlled.
- Generated content (`generated_samples/`, `output/`, `saved_jobs/`, `interpreter_logs/`, `loop_demos/`) is gitignored. Your prompts and outputs never leave your machine.

## License

[MIT](./LICENSE).
