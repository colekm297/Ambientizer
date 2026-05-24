# Ambientizer — AI Ambient Soundscape Generator

A full-stack application for generating ambient soundscapes and music using AI. Combines LLM-powered prompt interpretation, ElevenLabs audio generation, real-time browser mixing, AI-generated visuals, and YouTube publishing — all in one local app.

## Architecture Overview

```
User prompt → ThemeInterpreter (Claude) → SoundscapeConfig JSON
    → ElevenLabs SFX/Music APIs → individual layer WAVs
    → AudioEngine (render_flat) → mixed output
    → LiveMixer (Web Audio API, client-side) → real-time playback with per-layer controls
    → VisualGenerator (xAI Grok) → image/video
    → FFmpeg → final exported video
    → YouTubePublisher → upload to YouTube
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.13, Flask (single `app.py` with 50+ routes) |
| LLM (prompt → config) | Anthropic Claude (Sonnet 4) |
| Audio generation | ElevenLabs SFX v2 + Music v1 APIs |
| Audio processing | pydub, pedalboard, librosa, numpy, pyloudnorm |
| Reference analysis | Google Gemini 2.5 (native YouTube URL processing) |
| Client mixer | Vanilla JS + Web Audio API (`LiveMixer` class) |
| Visuals | xAI Grok image generation, Ken Burns animation |
| Video processing | FFmpeg / ffprobe |
| YouTube | Google OAuth2 + YouTube Data API v3 |
| Styling | Custom CSS (dark theme, ~3000 lines) |

## Project Structure

```
Ambientizer/
├── web/
│   ├── app.py                 # Flask server — 2566 lines, 50+ REST endpoints
│   ├── static/
│   │   ├── app.js             # Frontend logic — 3341 lines
│   │   ├── mixer.js           # LiveMixer (Web Audio API) — 530 lines
│   │   └── style.css          # Dark theme UI — 3021 lines
│   └── templates/
│       ├── index.html          # Main SPA — 542 lines
│       └── upload.html         # YouTube upload progress page
├── schemas.py                  # Data models (dataclasses + enums) — 286 lines
├── theme_interpreter.py        # Claude: prompt → SoundscapeConfig — 391 lines
├── sample_generator.py         # ElevenLabs API wrapper + caching — 388 lines
├── audio_engine.py             # DSP: mixing, looping, effects — 1059 lines
├── audio_critic.py             # Gemini/Claude audio critique — 355 lines
├── mix_master.py               # AI-driven mastering chain — 359 lines
├── feedback_adjuster.py        # NL feedback → config changes — 310 lines
├── config_adjuster.py          # Critique-driven config revision — 225 lines
├── orchestrator.py             # Pipeline coordinator — 319 lines
├── reference_analyzer.py       # Gemini YouTube analysis — 162 lines
├── visual_generator.py         # Grok image + FFmpeg video — 277 lines
├── youtube_publisher.py        # YouTube OAuth + upload — 240 lines
├── upload_worker.py            # Detached YouTube upload subprocess — 83 lines
├── gemini_limiter.py           # Local Gemini rate tracking — 132 lines
├── retry_utils.py              # Exponential backoff decorator — 63 lines
├── bootstrap_samples.py        # Synthetic sample generator (dev) — 602 lines
├── test_engine.py              # Audio engine smoke test — 124 lines
├── requirements.txt            # Python dependencies
├── .env                        # API keys (not committed)
├── generated_samples/          # Cached audio + stems + spend logs
├── output/                     # Generated mixes, videos, exports
├── saved_jobs/                 # Persisted job state (JSON per job)
├── interpreter_logs/           # Claude request/response logs
├── client_secret.json          # YouTube OAuth credentials
└── youtube_token.json          # YouTube OAuth token (auto-generated)
```

## Data Flow

### 1. Prompt Enhancement (`POST /api/enhance-prompt`)
- Optional Gemini web search for context (movies, games, places)
- Claude generates an enhanced prompt + structured layer plan
- User can edit the plan before committing

### 2. Reference Analysis (`POST /api/analyze-reference`)
- User provides a YouTube URL
- Gemini 2.5 processes the video natively (no download)
- Returns: overall feel, layer breakdown, mix qualities, recreate prompts
- Feeds into ThemeInterpreter for grounded generation

### 3. Generation (`POST /api/generate` → background thread)
Pipeline steps (reported via status polling):
1. **interpreting** — Claude converts prompt → `SoundscapeConfig` JSON
2. **generating_samples** — ElevenLabs creates audio for each layer
3. **rendering** — AudioEngine produces flat mix (volume + pan only)
4. **separating_stems** (optional) — ElevenLabs splits musical layer into instrument stems
5. **complete** — layers + stems available for LiveMixer playback

### 4. Real-time Playback (Client-side LiveMixer)
- Each layer loaded as independent Web Audio source
- Per-layer: volume, pan, mute, solo, low-pass filter, reverb send, swell LFO
- Stems shown as sub-tracks under their parent musical layer
- Silent stems auto-detected and hidden
- Master volume, loop toggle, fade in/out

### 5. Feedback Loop (`POST /api/feedback/<job_id>`)
- Natural language feedback → FeedbackAdjuster (Claude)
- Produces config diffs, optional layer regeneration
- Re-renders flat mix, LiveMixer reloads affected layers

### 6. Visuals & Export
- `POST /api/visual/image/<job_id>` — Grok generates scene image
- `POST /api/visual/clip/<job_id>` — Ken Burns animation or Grok video
- `POST /api/visual/upload-video/<job_id>` — user uploads custom video
- `POST /api/visual/export/<job_id>` — single FFmpeg pass: loop video + loop audio → final MP4

### 7. YouTube Publishing
- OAuth2 flow via `YouTubePublisher`
- Auto-metadata generation (Gemini)
- Upload runs in detached subprocess (`upload_worker.py`) — survives server restarts
- Progress tracked via disk-based JSON status file
- Dedicated browser tab shows upload progress

## Key Schemas (`schemas.py`)

### GenerationMode
- `AMBIENT` — pure environmental soundscape (SFX layers only)
- `MUSICAL` — ambient music + environmental layers

### LayerType
- `BASE` — foundational drone/texture (loop, background)
- `MID` — mid-ground elements (occasional, textural)
- `DETAIL` — foreground accents (sparse, ear-catching)
- `MUSICAL` — tonal/harmonic content (via Music API)

### SoundscapeConfig
```python
@dataclass
class SoundscapeConfig:
    title: str
    mood: str
    setting: str
    time_of_day: str
    root_key: str               # e.g. "G major", "F# minor"
    duration_sec: float
    music_length_sec: float
    layers: list[LayerConfig]   # 1-6 layers
    master_effects: EffectsChain
    energy_curve: EnergyCurve
```

### LayerConfig
```python
@dataclass
class LayerConfig:
    name: str
    layer_type: LayerType
    elevenlabs_prompt: str       # sent directly to ElevenLabs API
    volume_db: float             # -40 to +6
    pan: float                   # -1.0 (L) to 1.0 (R)
    loop: bool
    effects: EffectsChain        # low_pass_hz, high_pass_hz, reverb_amount
    generated_audio_path: str    # filled after generation
    # ... swell, timing, pitch fields
```

## API Keys Required (`.env`)

```
ANTHROPIC_API_KEY=sk-ant-...        # Claude (theme interpretation, feedback, mastering)
ELEVENLABS_API_KEY=...              # Audio generation + stem separation
GEMINI_API_KEY=AIza...              # Reference analysis, web search, audio critique
XAI_API_KEY=xai-...                 # Grok image/video generation (visuals)
```

Optional:
```
DAILY_CREDIT_LIMIT=100000           # ElevenLabs soft spend cap (credits/day)
```

## External Dependencies

- **FFmpeg** + **ffprobe** — video processing, audio export
- **Python 3.13** with venv

### Python packages (`requirements.txt`)
```
anthropic, google-genai, elevenlabs, pydub, pedalboard, librosa,
numpy, soundfile, scipy, python-dotenv, pyloudnorm, flask,
google-auth, google-auth-oauthlib, google-api-python-client,
httplib2, requests
```

## Key Constants

| Constant | Location | Value | Purpose |
|----------|----------|-------|---------|
| `HARD_MAX_MUSIC_SEC` | sample_generator.py | 600 | ElevenLabs Music API max duration |
| `HARD_MAX_SFX_SEC` | sample_generator.py | 8 | ElevenLabs SFX API max duration |
| `DAILY_CREDIT_LIMIT` | sample_generator.py | env or 100,000 | Soft daily spend cap |
| `SAMPLE_RATE` | audio_engine.py | 44100 | Audio sample rate |
| `MAX_ANALYSIS_SEC` | reference_analyzer.py | 120 | Max video duration sent to Gemini |
| `DEFAULT_RPM/RPD` | gemini_limiter.py | 150 / 1000 | Gemini rate limit tracking |

## Generation Approaches

### Unified (default for Musical mode)
- 1 cohesive musical layer (all instruments in one ElevenLabs generation)
- 1 atmosphere/SFX layer
- Optional stem separation (2-stem or 6-stem) to split the musical layer

### Multi-Layer
- 2-4 independent layers (mix of musical + SFX)
- Each generated separately, mixed by AudioEngine

## Audio Pipeline Details

### Rendering
- `render_flat()` — volume + pan only, no DSP effects. Used everywhere for consistency with client-side LiveMixer
- `render()` — full DSP chain (EQ, compression, reverb, limiting). Only used in `test_engine.py`
- Musical layers: simple concatenation (no crossfade) to preserve arrangement arc
- Non-musical layers: crossfade tiling via `make_loopable()` for seamless loops

### Caching
- Content-hash based: `sha256(prompt|type|duration|key)` → WAV file
- Identical prompts skip regeneration entirely
- Flat mix cached as `{job_id}_flat.wav`, invalidated on any layer change

### Credit Tracking
- Local daily spend log: `generated_samples/_daily_spend.json`
- Pre-flight balance check via ElevenLabs subscription API
- `SpendingLimitError` raised when soft cap exceeded
- UI shows real-time credit balance + per-action cost estimates

## Frontend Architecture (`app.js` + `mixer.js`)

### LiveMixer (Web Audio API)
- `addLayer(name, url, opts)` — fetch + decode + connect to audio graph
- Per-layer chain: GainNode → StereoPanner → BiquadFilter → SwellLFO → ControlGain → Dry/Wet reverb → MasterGain
- `setAlternate(layerA, layerB, cycleSec, xfadeSec)` — crossfade alternation between layers
- Stems loaded as `stem:bass`, `stem:drums`, etc. — muted by default
- Silent stem detection: samples AudioBuffer peak, hides stems with peak < 0.001

### UI Features
- Tab-based: Create, Visuals, Publish
- Real-time generation progress with stage-based progress bar
- Layer cards with inline controls (volume, pan, mute, solo, effects, regenerate)
- Stem toggle: shows/hides stem sub-cards, auto-mutes parent when stems visible
- Feedback chat interface for iterative refinement
- Parts builder for multi-section compositions
- History sidebar with favorite toggle and filter
- ElevenLabs credit display + Gemini usage indicator
- Credit cost estimation before generation

## Error Handling & Resilience

- **Retry with backoff**: Claude and ElevenLabs calls retry 3x with exponential backoff on transient errors (`retry_utils.py`)
- **Gemini rate limiter**: local RPM/RPD tracking, automatic wait-before-call, 429 backoff (`gemini_limiter.py`)
- **Model fallback chain**: Gemini calls try Flash → Pro → Flash-Lite in sequence
- **Quota errors surfaced to UI**: regeneration failures return 500 with descriptive message instead of silently continuing
- **YouTube upload isolation**: runs in detached subprocess (`upload_worker.py`) with disk-based progress, survives server restarts

## Running

```bash
cd Ambientizer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Add API keys to .env
python web/app.py --port 5050
# Open http://localhost:5050
```

## CLI Mode

```bash
python orchestrator.py --prompt "rainy Tokyo alley at 2am" --duration 5 --mode musical
python orchestrator.py --interactive   # discovery conversation mode
```

## Known Limitations

- **Stem separation**: Works well for conventional music (distinct instruments). Ambient/textural audio gets classified entirely as "Other" by the ElevenLabs model.
- **Thread safety**: `jobs` dict is modified outside lock in some paths (single-user localhost mitigates risk).
- **No structured logging**: all output is `print()` statements.
- **`app.py` is monolithic**: 2500+ lines, could benefit from Flask Blueprints.
- **Gemini YouTube analysis**: Sensitive to URL format and video accessibility. Rate limits can cause transient 429s even with paid tier.
