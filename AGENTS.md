# AGENTS.md — shared rules for AI coding agents (Claude Code, Cursor, Grok Build)

**This file is the single source of truth for any AI agent working on Ambientizer.**
Claude Code (`CLAUDE.md`) and Cursor (`.cursor/rules/`) both point here. Read it first.

---

## Multi-agent workflow (READ THIS)

Several AI tools edit this repo. To avoid chaos:

1. **One agent at a time.** Never have two tools editing uncommitted changes simultaneously.
2. **Commit before switching tools**, and **pull/refresh latest before starting.** Git is the shared memory — if it's committed, the next agent sees it; if it's not, they don't.
3. **Write clear commit messages** — they are how the *other* agents learn what changed (no shared private memory between tools).
4. Prefer working in **different files/areas** when possible to avoid merge conflicts.
5. Solo project — commits go straight to `main`. Keep the working tree clean between handoffs.

---

## What this is

Locally-hosted **Flask** app (Python 3.13, runs in `.venv`) that turns a creative brief into a
YouTube ambient music video: Claude/LLM planning → ElevenLabs audio → browser live-mixer →
Grok visuals / procedural motion → ffmpeg → YouTube publish. Public repo.

## Run it

- App: `web/app.py` on **port 5050** (5000 is taken by macOS AirPlay), in `.venv`.
- It runs as a **launchd service** (persists across reboot). After editing code you MUST restart:
  ```
  launchctl kickstart -k gui/$UID/com.cole.ambientizer
  ```
  and **hard-refresh the browser** (Flask + browser cache hold old code otherwise).
- API keys live in `.env` (ANTHROPIC, GEMINI, ELEVENLABS, XAI). The launch wrapper
  `run_ambientizer.sh` sources `.env` and adds Homebrew to PATH — see gotchas.

## Architecture map

Backend logic (flat in repo root — sensibly separated, just not packaged):
- **orchestrator.py** — top-level generate() pipeline (plan → audio → master).
- **theme_interpreter.py / config_adjuster.py / feedback_adjuster.py** — LLM planning + edits.
- **composition_planner.py** — Claude authors evolving ElevenLabs composition plans (sections).
- **sample_generator.py** — ElevenLabs Music/SFX generation; per-layer audio.
- **audio_engine.py** (1.3k) — mixing, looping, tiling, sparse rendering.
- **mix_master.py / audio_critic.py / reference_analyzer.py** — mastering, QC, reference (Gemini).
- **motion_compositor.py** — "Living Still" procedural seamless motion (camera drift, particles,
  fog, god-rays, aurora, parallax, color_glow, twinkle, nebula). depth_estimator.py / segmenter.py
  run on the system python (MPS) for depth/segmentation.
- **visual_generator.py** — Grok image/video. youtube_publisher.py / distribute_*.py — publish/growth.

Web layer (the big files — navigate carefully):
- **web/app.py (~4.3k lines)** — every Flask route. ⚠️ monolith; find routes by `@app.route`.
- **web/static/app.js (~4.9k lines)** — all frontend logic, one IIFE. ⚠️ monolith.
- **web/static/style.css (~3.8k)**, **web/templates/index.html** — UI.
- Tabs: Create | Listen | Visuals | Publish | Distribute. A single global bottom player bar
  (`#global-player`) + one track selection drive all tabs.

> Known debt: `app.py` and `app.js` should be split (blueprints / per-tab modules). Not yet done.

## Conventions & guardrails

- **Never commit secrets.** `.env`, `client_secret*.json`, `youtube_token.json`, `output/`,
  `saved_jobs/` are gitignored — keep it that way. No hardcoded API keys (read from env).
- **Don't commit `output/`** (huge: ~70GB of wav/mp4) or `saved_jobs/`.
- Validate before committing: `python -m py_compile <file>` for Python, `node --check web/static/app.js` for JS.

## Cursor Cloud specific instructions (remote agents)

When you are a **Cloud Agent** (running in Cursor's cloud VM, not on Cole's Mac):

- The VM provisions via `.cursor/environment.json`: it `apt install`s **ffmpeg**, creates `.venv`,
  and `pip install -r requirements.txt`. Use **`.venv/bin/python`** for anything needing deps.
- **No `.env` / API keys and no `client_secret*.json` are present** in the cloud. Do NOT try to run
  the live server, generate audio/visuals, or call Anthropic/Gemini/ElevenLabs/YouTube — those need
  secrets that only exist on Cole's machine. Stick to code edits + static validation.
- **Ignore the launchd / Tailscale steps** in "Run it" — those are local-only. There's no
  `launchctl`, no `com.cole.ambientizer`, no Tailscale in the cloud.
- **Validate before committing** (works without secrets):
  `.venv/bin/python -m py_compile <file>` for Python, `node --check web/static/app.js` for JS.
- The heavy ML extras (torch/torchvision for `depth_estimator.py` / `segmenter.py`) are NOT in
  `requirements.txt` and won't be installed; don't run depth/segmentation in the cloud.
- You push to a branch + open a PR; Cole reviews/merges from his phone. Keep commit messages clear
  (per "Multi-agent workflow") — they're how the local agents learn what you changed.

## CRITICAL GOTCHAS (these have bitten us — don't repeat)

1. **launchd has a minimal PATH** (no Homebrew). ffmpeg/ffprobe live in `/opt/homebrew/bin`, so
   anything shelling out to ffmpeg (motion render, pydub, exports) fails with
   `[Errno 2] ... 'ffmpeg'` unless PATH is set. Fixed in `run_ambientizer.sh` (`export PATH=...`).
2. **ElevenLabs composition plans reject any section > 120,000 ms (120s).** A 600s track in
   3-4 sections = 150-200s each → 422 → silent fallback. `composition_planner.clamp_plan_sections()`
   splits long sections; keep using it. Also: `force_instrumental` is REJECTED with a composition_plan.
3. **A silent generation must ERROR, not save as "complete."** `sample_generator.generate_layer_audio`
   raises on silent output (`_is_silent_file`). Never let a silent file masquerade as a finished track.
4. **iOS/AirPods audio:** play full-mix tracks through the NATIVE `<audio>` element, NOT Web Audio
   (`createMediaElementSource` is silent on iOS; full Web Audio decode buzzes over Bluetooth).
   `navigator.audioSession.type="playback"` is set at startup.
5. **Code changes need a launchd restart** (see Run it) — the service holds Python in memory.
6. **Visuals motion** must loop seamlessly (16-32s loop tiled to fill an hour); camera uses
   sub-pixel sampling (integer crop offsets caused jitter). Keep effects seamless (integer cycles).
