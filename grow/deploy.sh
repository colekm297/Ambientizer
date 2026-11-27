#!/bin/sh
# Ship grow/ to Cole's copy (~/.local/share/grow). Run the checks on 5071 first.
set -e
S="$(cd "$(dirname "$0")" && pwd)"; D="$HOME/.local/share/grow"
mkdir -p "$D/site"; [ -f "$D/site/index.html" ] && rsync -a --delete "$D/site/" "$D/previous/"
rsync -a --delete --include index.html --include ui.js --include grow.js --include grow.css --include scene.html --include scene.js --include scene.css --include scene_ask.js --include sing.js --include sing_ui.js --include ab.html --include '/ds/***' --include '/sounds/' --include '/sounds/*/' --include '/sounds/*/*.flac' --include '/sounds/*/samples.json' --exclude '*' "$S/" "$D/site/"
cp "$S/serve.py" "$D/scene_api.py"
cp "$S/serve_live.py" "$D/serve.py"
