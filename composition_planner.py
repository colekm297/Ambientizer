"""
composition_planner.py — Claude authors a real, evolving ElevenLabs composition plan.

The old `_build_ambient_composition_plan` chopped time into near-identical sections
with the same copy-pasted style tags, so ElevenLabs Music had no actual arrangement
to follow — it sounded the same as a plain text prompt. This module instead has
Claude write a genuine arrangement: distinct sections that establish → develop →
widen → return to the opening for a seamless loop, each with its OWN style guidance.

Returns a dict in ElevenLabs `composition_plan` shape, or None on any failure so
the caller can fall back to the generic plan (never blocks generation).
"""

import json
import os
from typing import Optional

# ElevenLabs Music rejects any composition-plan section longer than this (422).
# A 600s track in 3-4 sections = 150-200s each, which ALWAYS exceeded this and
# caused the whole plan to be rejected → silent fallback. Every plan is clamped.
MAX_SECTION_MS = 120_000


_PLANNER_SYSTEM = """You are an ambient arrangement designer. Given a soundscape brief, write a \
COMPOSITION PLAN for ElevenLabs Music: a sequence of distinct sections that EVOLVE over time, \
for hours-long background listening. This is NOT a song — no verse/chorus, no drops, no vocals, \
no drums, no fade-out. The piece is LOOPED downstream (a loop finder + crossfade craft the seamless \
wrap), so the final section does NOT need to return to the opening — keep REAL INSTRUMENTS playing at \
body-level density through the end. NEVER end on a sparse, instrument-less "resonance / empty space / \
distant texture / dissolve to silence" section — with no concrete instrument to play, the generator \
synthesizes warbling, metallic, underwater-robot artifacts. EVERY section must name at least one \
concrete sustained instrument that is actually playing.

CONTRAST IS THE WHOLE POINT. The model smooths over long durations, so you must make sections \
DECISIVELY different or the listener hears no change. For every section, be explicit about which \
instruments/elements ARE PRESENT and which are ABSENT — and make adjacent sections clearly differ \
in density and instrumentation:
- Name specific instruments ENTERING in `positive_local_styles` (e.g. "solo cello enters, prominent").
- Name instruments that should be ABSENT/removed in `negative_local_styles` (e.g. "no cello", \
"no high shimmer") so the model actually drops them.
- Vary DENSITY hard between neighbors: a sparse section (1-2 elements) next to a full section \
(3-4 elements), not a gentle ramp.

Design a clear arc, e.g.:
  1. SPARSE bed — foundation + space only; other instruments explicitly absent.
  2. A lead instrument ENTERS and is prominent; bed continues.
  3. FULLEST — add a second color/harmonic widening; most elements present.
  4. SETTLE — ease toward a warm sustained texture, but keep real instruments present (do NOT dissolve to silence).

Use 3-4 sections (fewer, LONGER sections give each change room to be heard — avoid 5+). \
The last section must stay musically present (real instruments at body density), NOT dissolve — the \
seamless loop is crafted downstream, so the ending does not need to match the opening.

Output STRICT JSON only:
{
  "positive_global_styles": ["6-10 global descriptors true of the whole piece (key, tempo, core timbres)"],
  "negative_global_styles": ["vocals", "drums", "verse chorus bridge", "fade-out ending", "..."],
  "sections": [
    {
      "section_name": "short name stating what's happening (e.g. 'Solo cello enters')",
      "positive_local_styles": ["4-7 styles — name the instruments PRESENT/entering this section"],
      "negative_local_styles": ["2-5 — name instruments that should be ABSENT here"],
      "duration_fraction": 0.25
    }
  ]
}
duration_fraction values are each section's share of total length and must sum to 1.0. \
Output ONLY the JSON, no prose, no markdown fences."""


def clamp_plan_sections(plan: Optional[dict], max_ms: int = MAX_SECTION_MS) -> Optional[dict]:
    """Split any section longer than max_ms into equal sub-sections that each fit,
    preserving the section's styles. Guarantees ElevenLabs accepts the plan no
    matter the total length. Idempotent and safe on any plan shape."""
    if not isinstance(plan, dict) or not isinstance(plan.get("sections"), list):
        return plan
    out = []
    for s in plan["sections"]:
        try:
            dur = int(s.get("duration_ms", 0))
        except (TypeError, ValueError):
            dur = 0
        if dur <= max_ms:
            out.append(s)
            continue
        import math
        parts = math.ceil(dur / max_ms)
        base = dur // parts
        name = str(s.get("section_name", "Section"))
        for i in range(parts):
            piece = dict(s)
            piece["duration_ms"] = (dur - base * (parts - 1)) if i == parts - 1 else base
            piece["section_name"] = name if parts == 1 else f"{name} ({i + 1}/{parts})"
            out.append(piece)
    plan = dict(plan)
    plan["sections"] = out
    return plan


def _strip_fences(raw: str) -> str:
    clean = (raw or "").strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
    if clean.endswith("```"):
        clean = clean.rsplit("```", 1)[0]
    return clean.strip()


def author_composition_plan(
    prompt: str,
    duration_ms: int,
    root_key: str = "",
    mood: str = "",
    anthropic_key: Optional[str] = None,
    model: str = "claude-sonnet-4-6",
    style_examples: Optional[list] = None,
) -> Optional[dict]:
    """Have Claude author an evolving ambient composition plan. Returns a validated
    ElevenLabs composition_plan dict, or None (caller falls back to the generic plan).

    style_examples: optional list of proven-excellent prompt strings (the user's
    favorited generations) used as few-shot guidance so the arrangement inherits
    the specificity/instrumentation that has worked before."""
    anthropic_key = anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return None

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key)
        key_bit = f"\nKEY: {root_key}" if root_key else ""
        mood_bit = f"\nMOOD: {mood}" if mood else ""
        examples_bit = ""
        if style_examples:
            joined = "\n\n".join(f'- "{e}"' for e in style_examples[:3])
            examples_bit = (
                "\n\nPROVEN-EXCELLENT REFERENCE PROMPTS (the user favorited soundscapes built "
                "from these — match their level of instrumentation detail and clarity, do NOT "
                f"copy their content):\n{joined}"
            )
        user = (
            f"BRIEF: {prompt}{key_bit}{mood_bit}{examples_bit}\n"
            f"TOTAL LENGTH: {duration_ms / 1000:.0f} seconds.\n"
            "Write the composition plan now. Keep style lists concise so the JSON is complete."
        )
        # Two attempts. max_tokens is generous (1100 truncated mid-JSON before,
        # producing an unparseable plan → ToS-rejected generic fallback → silence).
        last_err = None
        for attempt in range(2):
            try:
                resp = client.messages.create(
                    model=model, max_tokens=2400, system=_PLANNER_SYSTEM,
                    messages=[{"role": "user", "content": user}],
                )
                data = _lenient_json_parse(resp.content[0].text)
                if data:
                    plan = _normalize_plan(data, duration_ms)
                    if plan:
                        return plan
                last_err = "unparseable/empty plan"
            except Exception as e:
                last_err = e
        print(f"      [plan] Claude composition plan failed ({last_err}); using generic plan", flush=True)
        return None
    except Exception as e:
        print(f"      [plan] Claude composition plan failed ({e}); using generic plan", flush=True)
        return None


def _lenient_json_parse(raw: str) -> Optional[dict]:
    """Parse Claude's JSON, salvaging a truncated response by dropping an
    incomplete trailing section and closing the brackets."""
    text = _strip_fences(raw)
    try:
        return json.loads(text)
    except Exception:
        pass
    # Salvage: keep everything up to the last complete object, then close the
    # sections array and root object in whatever combination parses.
    last_brace = text.rfind("}")
    if last_brace == -1:
        return None
    head = text[:last_brace + 1]
    for suffix in ("", "]}", "}]}", "]}}", "}", "]}}}"):
        try:
            return json.loads(head + suffix)
        except Exception:
            continue
    return None


def finalize_plan(plan: dict, duration_ms: int) -> Optional[dict]:
    """Coerce an authored OR user-edited plan into a clean ElevenLabs payload,
    rescaling section durations to sum exactly to duration_ms. Used when a plan
    is provided from the UI so 'what you see is what generates'."""
    if not isinstance(plan, dict) or not plan.get("sections"):
        return None
    secs = plan["sections"]
    durs = []
    for s in secs:
        try:
            durs.append(max(1, int(s.get("duration_ms", 0))))
        except (TypeError, ValueError):
            durs.append(1)
    if sum(durs) <= 0:
        durs = [1] * len(secs)
    total = sum(durs)
    out, allocated = [], 0
    for i, s in enumerate(secs):
        d = (duration_ms - allocated) if i == len(secs) - 1 else max(3000, int(round(duration_ms * durs[i] / total)))
        allocated += d
        out.append({
            "section_name": str(s.get("section_name", f"Section {i + 1}"))[:80],
            "positive_local_styles": [str(x) for x in (s.get("positive_local_styles") or [])][:8] or ["evolving instrumental ambient texture"],
            "negative_local_styles": [str(x) for x in (s.get("negative_local_styles") or [])][:6] or ["vocals", "drums"],
            "duration_ms": d,
            "lines": [],
        })
    return {
        "positive_global_styles": [str(x) for x in (plan.get("positive_global_styles") or ["instrumental ambient soundscape"])][:10],
        "negative_global_styles": [str(x) for x in (plan.get("negative_global_styles") or ["vocals", "drums", "fade-out ending"])][:12],
        "sections": out,
    }


def _normalize_plan(data: dict, duration_ms: int) -> Optional[dict]:
    """Validate Claude's output and convert duration_fraction → duration_ms that
    sums exactly to the target. Returns None if the shape is unusable."""
    if not isinstance(data, dict):
        return None
    sections_in = data.get("sections")
    if not isinstance(sections_in, list) or not sections_in:
        return None

    # Pull fractions, default to equal split if missing/invalid.
    fracs = []
    for s in sections_in:
        try:
            f = float(s.get("duration_fraction", 0))
        except (TypeError, ValueError):
            f = 0.0
        fracs.append(max(0.0, f))
    if sum(fracs) <= 0:
        fracs = [1.0 / len(sections_in)] * len(sections_in)
    total_f = sum(fracs)

    sections = []
    allocated = 0
    for i, s in enumerate(sections_in):
        if i == len(sections_in) - 1:
            dur = max(3000, duration_ms - allocated)  # last takes the remainder
        else:
            dur = max(3000, int(round(duration_ms * fracs[i] / total_f)))
        allocated += dur
        pls = s.get("positive_local_styles") or []
        nls = s.get("negative_local_styles") or []
        sections.append({
            "section_name": str(s.get("section_name", f"Section {i + 1}"))[:80],
            "positive_local_styles": [str(x) for x in pls][:8] or ["evolving instrumental ambient texture"],
            "negative_local_styles": [str(x) for x in nls][:6] or ["vocals", "drums", "song ending"],
            "duration_ms": dur,
            "lines": [],
        })

    pos = data.get("positive_global_styles") or ["instrumental ambient soundscape", "slow evolving harmony", "seamless loop"]
    neg = data.get("negative_global_styles") or ["vocals", "drums", "verse chorus bridge", "fade-out ending"]
    return {
        "positive_global_styles": [str(x) for x in pos][:10],
        "negative_global_styles": [str(x) for x in neg][:12],
        "sections": sections,
    }
