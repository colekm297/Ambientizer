# Ambientizer Roadmap

## Completed

- **Core Generation Pipeline**: Claude theme interpretation → ElevenLabs audio generation → audio engine rendering → mix/master
- **Human Feedback Loop**: Chat-based feedback for iterative mix refinement via Claude
- **Layer Inspector**: Direct manipulation of layers (volume, pan, reverb, LP filter, pitch, mute, re-roll, regenerate, add, remove)
- **Reference Analysis**: Gemini-powered YouTube reference audio analysis
- **Seamless Looping**: Global and per-layer crossfade looping with extended export (30 min–8 hr)
- **Harmonic Tools**: Key detection, pitch shifting, auto-harmonize
- **Consolidated Layers**: 2-3 rich, cohesive layers instead of many thin ones
- **Visuals Pipeline**: Grok image generation → AI/Ken Burns animation → full video export
- **YouTube Publishing**: OAuth 2.0 connection, AI-generated metadata, background upload with progress
- **Job Persistence**: Save/load sessions across restarts
- **Interactive Parts Builder**: Compose multi-section tracks by saving mix snapshots as parts, crossfade-stitch together
- **AI Feedback (Gemini)**: Quality scoring (1-10) and actionable critique notes
- **Global Fades**: Automatic fade-in/fade-out on exports and stitched compositions
- **Accurate YouTube Timestamps**: Auto-metadata uses real part names and timestamps

## In Progress / Near-Term

- **Layer fade automation in parts**: Layers entering/exiting a part should auto-fade rather than hard-cut
- **Part reordering via drag-and-drop**: Visual reordering in the Parts Builder UI
- **Stitched track preview**: Play the full stitched composition in-browser before exporting

## Future Ideas

- **Community sharing**: Browse and remix other users' soundscapes
- **Preset library**: Save and reuse layer configurations as templates
- **Mobile-friendly UI**: Responsive layout improvements for phone/tablet
- **Scheduled publishing**: Queue YouTube uploads for optimal posting times
- **Multi-platform publishing**: Export and publish to Spotify, SoundCloud, etc.
- **Waveform visualization**: Visual waveform display in the audio player
- **Batch generation**: Generate multiple variations from a single prompt
