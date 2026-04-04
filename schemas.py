"""
schemas.py — Shared data models for the soundscape agent.

These are the "contracts" between components. The LLM outputs a SoundscapeConfig,
the engine consumes it, the critic produces a CritiqueResult, and the adjuster
modifies the config based on the critique.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class GenerationMode(str, Enum):
    AMBIENT = "ambient"     # Pure soundscape — nature, environments, textures
    MUSICAL = "musical"     # Ambient music with soundscape elements


class LayerType(str, Enum):
    BASE = "base"           # Continuous drones, ambient beds
    MID = "mid"             # Periodic elements (birdsong, distant thunder)
    DETAIL = "detail"       # Sparse accents (twig snap, bell, water drip)
    MUSICAL = "musical"     # Melodic/harmonic fragments


@dataclass
class EffectsChain:
    reverb_amount: float = 0.3          # 0.0 - 1.0
    reverb_room_size: float = 0.5       # 0.0 - 1.0 (small room to cathedral)
    low_pass_hz: Optional[float] = None # Cut highs above this freq
    high_pass_hz: Optional[float] = None # Cut lows below this freq
    compression_threshold_db: float = -20.0
    compression_ratio: float = 2.0


@dataclass
class LayerConfig:
    """Configuration for a single audio layer in the soundscape."""
    name: str                               # Human-readable name
    layer_type: LayerType
    sample_tags: list[str]                  # Tags to match from sample library
    volume_db: float = -6.0                 # Relative volume in dB
    pan: float = 0.0                        # -1.0 (left) to 1.0 (right)
    pan_randomize: bool = False             # Randomize pan per occurrence
    loop: bool = True                       # Loop continuously vs. play once
    fade_in_sec: float = 2.0
    fade_out_sec: float = 2.0

    # Timing (for non-looping / accent layers)
    min_interval_sec: float = 0.0           # Min seconds between plays
    max_interval_sec: float = 0.0           # Max seconds between plays
    density: float = 1.0                    # 0.0 - 1.0, probability of playing

    # Variation over time
    volume_drift_db: float = 0.0            # Slow random volume variation range
    pitch_drift_cents: float = 0.0          # Slow random pitch variation

    # Per-layer effects
    effects: Optional[EffectsChain] = None

    # Pitch / tuning
    pitch_shift_semitones: int = 0              # Manual pitch shift (-6 to +6 semitones)

    # Swell / breathing — slow sine-wave volume modulation for organic movement
    swell_amount: float = 0.0                   # 0.0 (constant) to 1.0 (dramatic swell)
    swell_period_sec: float = 20.0              # Full cycle length in seconds

    # Timeline — when this layer enters/exits within the track (0 = full duration)
    start_sec: float = 0.0
    end_sec: float = 0.0

    # Looping
    independent_loop: bool = False              # Loop at own sample length, not with the mix

    # ElevenLabs generation
    elevenlabs_prompt: Optional[str] = None     # Detailed sound description for AI generation
    generated_audio_path: Optional[str] = None  # Path to generated audio file


@dataclass
class EnergyCurve:
    """Describes how the soundscape's energy evolves over its duration."""
    style: str = "steady"                   # steady, slow_build, rise_and_fall, wave
    peak_position: float = 0.5             # 0.0 - 1.0, where peak energy occurs
    min_energy: float = 0.4                 # Floor energy level
    max_energy: float = 1.0                 # Ceiling energy level


@dataclass
class SoundscapeConfig:
    """
    Complete specification for generating a soundscape.
    This is the core data structure — the LLM produces it, the engine consumes it.
    """
    title: str
    description: str                        # Original user intent, preserved
    mood: str                               # e.g. "melancholy", "peaceful", "tense"
    setting: str                            # e.g. "indoor café", "deep forest"
    time_of_day: str                        # e.g. "midnight", "dawn", "afternoon"
    layers: list[LayerConfig] = field(default_factory=list)
    master_effects: EffectsChain = field(default_factory=EffectsChain)
    energy_curve: EnergyCurve = field(default_factory=EnergyCurve)
    target_loudness_lufs: float = -18.0     # Target integrated loudness
    duration_sec: float = 300.0             # Render duration
    music_length_sec: float = 0.0           # Music generation length (0 = match track duration)
    loopable: bool = True                   # Make output seamlessly loopable
    crossfade_seconds: float = 15.0         # Crossfade duration at loop boundary
    root_key: str = ""                      # Harmonic key for tonal coordination (e.g. "C minor")

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SoundscapeConfig":
        """Reconstruct from a dict (e.g. loaded from JSON)."""
        layers = []
        for ld in d.get("layers", []):
            effects = None
            if ld.get("effects"):
                effects = EffectsChain(**ld["effects"])
            layers.append(LayerConfig(
                name=ld["name"],
                layer_type=LayerType(ld["layer_type"]),
                sample_tags=ld.get("sample_tags", []),
                volume_db=ld.get("volume_db", -6.0),
                pan=ld.get("pan", 0.0),
                pan_randomize=ld.get("pan_randomize", False),
                loop=ld.get("loop", True),
                fade_in_sec=ld.get("fade_in_sec", 2.0),
                fade_out_sec=ld.get("fade_out_sec", 2.0),
                min_interval_sec=ld.get("min_interval_sec", 0.0),
                max_interval_sec=ld.get("max_interval_sec", 0.0),
                density=ld.get("density", 1.0),
                volume_drift_db=ld.get("volume_drift_db", 0.0),
                pitch_drift_cents=ld.get("pitch_drift_cents", 0.0),
                effects=effects,
                pitch_shift_semitones=ld.get("pitch_shift_semitones", 0),
                swell_amount=ld.get("swell_amount", 0.0),
                swell_period_sec=ld.get("swell_period_sec", 20.0),
                start_sec=ld.get("start_sec", 0.0),
                end_sec=ld.get("end_sec", 0.0),
                independent_loop=ld.get("independent_loop", False),
                elevenlabs_prompt=ld.get("elevenlabs_prompt"),
                generated_audio_path=ld.get("generated_audio_path"),
            ))

        me = d.get("master_effects", {})
        master_effects = EffectsChain(**me) if me else EffectsChain()

        ec = d.get("energy_curve", {})
        energy_curve = EnergyCurve(**ec) if ec else EnergyCurve()

        return cls(
            title=d.get("title", "Untitled"),
            description=d.get("description", ""),
            mood=d.get("mood", ""),
            setting=d.get("setting", ""),
            time_of_day=d.get("time_of_day", ""),
            layers=layers,
            master_effects=master_effects,
            energy_curve=energy_curve,
            target_loudness_lufs=d.get("target_loudness_lufs", -18.0),
            duration_sec=d.get("duration_sec", 300.0),
            loopable=d.get("loopable", True),
            crossfade_seconds=d.get("crossfade_seconds", 15.0),
            root_key=d.get("root_key", ""),
        )


@dataclass
class PartLayerState:
    """Per-layer mix state within a Part."""
    volume_db: float = -6.0
    pan: float = 0.0
    muted: bool = False
    reverb_amount: float = 0.3
    low_pass_hz: Optional[float] = None
    pitch_shift_semitones: int = 0
    swell_amount: float = 0.0
    swell_period_sec: float = 20.0


@dataclass
class PartSnapshot:
    """A snapshot of the mix state for one section of a long-form composition."""
    name: str                                       # "Gentle Intro", "Peak", etc.
    duration_sec: float = 300.0                     # How long this part lasts
    layer_states: dict[str, dict] = field(default_factory=dict)  # layer_name -> PartLayerState as dict
    added_layers: list[LayerConfig] = field(default_factory=list)  # new layers only in this part
    fade_in_sec: float = 5.0                        # Crossfade into this part

    def to_dict(self) -> dict:
        import dataclasses
        return {
            "name": self.name,
            "duration_sec": self.duration_sec,
            "layer_states": self.layer_states,
            "added_layers": [dataclasses.asdict(l) for l in self.added_layers],
            "fade_in_sec": self.fade_in_sec,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PartSnapshot":
        added = []
        for ld in d.get("added_layers", []):
            effects = None
            if ld.get("effects"):
                effects = EffectsChain(**ld["effects"])
            added.append(LayerConfig(
                name=ld["name"],
                layer_type=LayerType(ld["layer_type"]),
                sample_tags=ld.get("sample_tags", []),
                volume_db=ld.get("volume_db", -6.0),
                pan=ld.get("pan", 0.0),
                loop=ld.get("loop", True),
                fade_in_sec=ld.get("fade_in_sec", 2.0),
                fade_out_sec=ld.get("fade_out_sec", 2.0),
                effects=effects,
                pitch_shift_semitones=ld.get("pitch_shift_semitones", 0),
                swell_amount=ld.get("swell_amount", 0.0),
                swell_period_sec=ld.get("swell_period_sec", 20.0),
                start_sec=ld.get("start_sec", 0.0),
                end_sec=ld.get("end_sec", 0.0),
                independent_loop=ld.get("independent_loop", False),
                elevenlabs_prompt=ld.get("elevenlabs_prompt"),
                generated_audio_path=ld.get("generated_audio_path"),
            ))
        return cls(
            name=d.get("name", "Untitled"),
            duration_sec=d.get("duration_sec", 300.0),
            layer_states=d.get("layer_states", {}),
            added_layers=added,
            fade_in_sec=d.get("fade_in_sec", 5.0),
        )


@dataclass
class AudioFeatures:
    """
    Extracted features from rendered audio, used to augment the critic's analysis.
    These give the listening model concrete data alongside its perceptual judgment.
    """
    duration_sec: float
    loudness_lufs: float
    spectral_centroid_mean_hz: float        # Brightness indicator
    spectral_centroid_std_hz: float         # Brightness variation
    low_energy_ratio: float                 # % energy below 250Hz
    mid_energy_ratio: float                 # % energy 250-4000Hz
    high_energy_ratio: float                # % energy above 4000Hz
    dynamic_range_db: float                 # Loudness range
    silence_ratio: float                    # % near-silent frames
    onset_density_per_sec: float            # How "busy" the texture is
    spectral_flatness_mean: float           # Noise-like (1.0) vs tonal (0.0)


@dataclass
class CritiqueResult:
    """
    The audio critic's assessment of a rendered soundscape.
    Combines perceptual listening with extracted audio features.
    """
    # From the listening model
    perceived_mood: str
    perceived_setting: str
    perceived_quality: str                  # "professional", "amateur", "mixed"
    strengths: list[str]
    issues: list[str]
    specific_suggestions: list[str]

    # Match scores (0.0 - 1.0)
    mood_match: float                       # Does the mood match intent?
    density_match: float                    # Is the density appropriate?
    frequency_balance_score: float          # Is the frequency balance good?
    overall_score: float                    # Composite quality score

    # Extracted features (for the config adjuster to reason about)
    features: Optional[AudioFeatures] = None

    @property
    def needs_revision(self) -> bool:
        return self.overall_score < 0.75 or len(self.issues) > 2
