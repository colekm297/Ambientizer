#!/bin/bash
# Launch wrapper for the Ambientizer Flask app under launchd.
# Loads API keys from .env (launchd does not source shell profiles) and runs
# the app on localhost:5050. Tailscale `serve` proxies it onto the tailnet.
cd /Users/colemonroe/Projects/Ambientizer || exit 1
# launchd runs with a minimal PATH (/usr/bin:/bin:...) that excludes Homebrew,
# so ffmpeg/ffprobe (used by the motion compositor, pydub, loop prep, exports)
# aren't found → "[Errno 2] No such file or directory: 'ffmpeg'". Add Homebrew.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
set -a
[ -f .env ] && source .env
set +a
exec .venv/bin/python web/app.py --port 5050 --host 127.0.0.1
