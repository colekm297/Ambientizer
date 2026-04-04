# Soundscape Agent

An LLM-powered ambient soundscape generator with an AI listening/critique loop.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       ORCHESTRATOR                           │
│                                                              │
│  User Prompt ──► Theme Interpreter (Claude API)              │
│                        │                                     │
│                        ▼                                     │
│            SoundscapeConfig (with elevenlabs_prompts)         │
│                        │                                     │
│                        ▼                                     │
│          ElevenLabs SFX v2 API (generate each layer)         │
│                        │                                     │
│              ┌─────────┴──────────┐                          │
│              ▼                    │                          │
│        Audio Engine               │                          │
│    (mix/layer/effects)            │                          │
│              │                    │                          │
│              ▼                    │                          │
│        .wav segment               │                          │
│              │                    │                          │
│              ▼                    │                          │
│        Audio Critic          max iterations?                 │
│        (Gemini API)              │                          │
│              │                    │                          │
│              ▼                    │                          │
│        CritiqueResult ───►  Config Adjuster (Claude)         │
│                                   │                          │
│                      Adjust MIX (volumes, effects, panning)  │
│                      Generate new layers if added ──► loop   │
│                                                              │
│  Final render ──► raw_mix.wav                                │
│                        │                                     │
│                        ▼                                     │
│              Mix/Master Agent                                │
│    (librosa analysis → Claude DSP prescription               │
│     → pedalboard EQ/comp/limit → LUFS normalization)         │
│                        │                                     │
│                        ▼                                     │
│                 mastered.wav                                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                    WEB INTERFACE                              │
│                                                              │
│  Browser ──► Flask API ──► Orchestrator (background thread)  │
│     ▲                            │                          │
│     └── poll /api/status ◄── on_status callback              │
└──────────────────────────────────────────────────────────────┘
```

## Components

| Module | Role | Model/Service |
|--------|------|---------------|
| `theme_interpreter.py` | Converts natural language to structured config | Claude (Anthropic API) |
| `sample_generator.py` | Generates audio for each layer on-demand | ElevenLabs SFX v2 API |
| `audio_engine.py` | Renders soundscape from config + generated audio | pydub + pedalboard |
| `audio_critic.py` | Listens to rendered audio and critiques it | Gemini 2.5 Flash (Google API) |
| `config_adjuster.py` | Translates critique into mix changes | Claude (Anthropic API) |
| `mix_master.py` | Professional mastering (EQ, compression, limiting, LUFS) | Claude + pedalboard + pyloudnorm |
| `orchestrator.py` | Runs the generate → critique → refine → master loop | — |
| `schemas.py` | Shared data models (configs, critiques) | — |
| `web/app.py` | Flask web server with REST API | Flask |

## Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# System dependency
brew install ffmpeg

# Create .env file with your API keys
cat > .env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...
ELEVENLABS_API_KEY=sk_...
EOF
```

## Environment Variables

```bash
ANTHROPIC_API_KEY="sk-ant-..."     # Required — theme interpreter + config adjuster
GEMINI_API_KEY="..."               # Required — audio critic (Gemini)
ELEVENLABS_API_KEY="sk_..."        # Required — AI audio generation
```

## Usage

### CLI

```bash
# Full pipeline: ElevenLabs generation + Gemini critique loop + mastering
python orchestrator.py "cozy rainy café at midnight with soft jazz piano" --duration 2

# Skip critique loop (just generate, render, and master)
python orchestrator.py "gentle rain on a window at night" --no-iterate --duration 0.5

# Use feature-only critic (no Gemini API needed)
python orchestrator.py "forest stream at dawn" --critic feature-only --duration 1

# Force regeneration of cached samples
python orchestrator.py "ocean waves at sunset" --no-cache --duration 0.5

# Skip mastering (raw mix only)
python orchestrator.py "mountain stream" --no-master --duration 1

# Interactive discovery conversation
python orchestrator.py --interactive --duration 5
```

### Web Interface

```bash
# Start the web server
python web/app.py --port 5050

# Open http://localhost:5050 in your browser
```

The web UI provides:
- Prompt input with duration and critic mode selection
- Real-time generation progress with critique scores
- Audio player with toggle between Raw and Mastered outputs
- Download button and generation history

### Python API

```python
from orchestrator import SoundscapeOrchestrator

agent = SoundscapeOrchestrator(
    anthropic_api_key="sk-...",
    gemini_api_key="...",
    elevenlabs_api_key="sk_...",
)

result = agent.generate("cozy rainy café at midnight", duration_minutes=60)
print(f"Saved to: {result.output_path}")
print(f"Raw mix: {result.raw_output_path}")
print(f"Final score: {result.final_score:.2f}")
```

## How It Works

1. **Theme Interpreter** — Claude converts your prompt into a structured config with 3-7 layers, each with a vivid `elevenlabs_prompt` describing the exact sound to generate.

2. **ElevenLabs Generation** — Each layer's audio is generated on-demand via the SFX v2 API. Results are cached by prompt hash so identical sounds aren't regenerated.

3. **Audio Engine** — Layers are mixed together with volume, panning, effects (reverb, compression, filters), and energy curve modulation.

4. **Gemini Critique Loop** — Gemini 2.5 Flash listens to a 25-second preview and critiques the mix. The Config Adjuster (Claude) revises volumes, effects, and panning. This loops until quality threshold is met.

5. **Mix/Master Agent** — After the final render, librosa analyzes the raw mix (5-band energy, stereo width, crest factor, LUFS). Claude prescribes a mastering chain (EQ, compression, limiting). Pedalboard applies the chain and pyloudnorm normalizes to -14 LUFS.

Key insight: ElevenLabs generates audio **once** per layer. The critique loop only adjusts the **mix** — it doesn't regenerate samples unless the adjuster explicitly adds new layers.

## Caching

Generated audio is cached in `generated_samples/` by prompt hash. This means:
- Same prompt = same cached file, no API call
- Critique loop iterations don't burn ElevenLabs credits
- Use `--no-cache` to force regeneration

## Cost

- **ElevenLabs SFX v2**: ~440 credits per 22s clip, ~110K credits/month on Creator plan
- **Gemini 2.5 Flash**: ~$0.001 per critique call
- **Claude**: ~$0.01-0.02 per soundscape (interpretation + adjustment)
