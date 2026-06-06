"""
thumbnail_maker.py — branded YouTube thumbnails with an LLM art director.

Two pieces:
  1. A curated STYLES registry (font + typographic treatment). The LLM may ONLY
     pick from these, so output always looks intentional — never random fonts.
  2. choose_thumbnail_design(): Claude LOOKS at the scene image + the track's
     title/mood/setting and returns {style, hook, subtitle, accent, align,
     position} — the per-video art-direction. render_thumbnail() bakes it.

Falls back to a sensible default (engraved/Copperplate) if no API key or on error,
so a thumbnail is ALWAYS produced.

Designed to be called from the publish flow: generate → set as the YouTube
thumbnail right before upload.
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

TW, TH = 1280, 720
_FONTS = "/System/Library/Fonts/Supplemental"
_CORE = "/System/Library/Fonts"
_PROJ = str(Path(__file__).parent / "fonts")  # bundled display fonts (OFL)

# Curated styles. Each: title font (path, weight), subtitle font, label, case for
# the hook ("upper"/"title"), letter tracking, default alignment, and a treatment:
# "glow" (accent-colored blur behind title), "line" (accent rule under title), or
# "engrave" (small centered accent tick). Weight is the variable-font axis value
# (ignored by static fonts).
STYLES = {
    "cinzel": {  # epic Trajan-style Roman caps — cinematic / sci-fi hero look
        "label": "Cinzel — epic cinematic caps",
        "title": (f"{_PROJ}/Cinzel.ttf", 800), "sub": (f"{_PROJ}/Cinzel.ttf", 500),
        "case": "upper", "tracking": 4, "sub_tracking": 6, "align": "center",
        "treatment": "line", "title_size": 88, "sub_size": 30,
    },
    "bebas": {  # tall punchy condensed — modern, bold, clean
        "label": "Bebas Neue — tall modern condensed",
        "title": (f"{_PROJ}/BebasNeue.ttf", 400), "sub": (f"{_PROJ}/BebasNeue.ttf", 400),
        "case": "upper", "tracking": 2, "sub_tracking": 6, "align": "left",
        "treatment": "glow", "title_size": 132, "sub_size": 40,
    },
    "oswald": {  # condensed grotesque — documentary / focused
        "label": "Oswald — modern condensed sans",
        "title": (f"{_PROJ}/Oswald.ttf", 600), "sub": (f"{_PROJ}/Oswald.ttf", 400),
        "case": "upper", "tracking": 2, "sub_tracking": 6, "align": "left",
        "treatment": "line", "title_size": 104, "sub_size": 34,
    },
    "cormorant": {  # elegant high-contrast serif — refined, premium
        "label": "Cormorant — elegant serif",
        "title": (f"{_PROJ}/Cormorant.ttf", 600), "sub": (f"{_PROJ}/Cormorant.ttf", 500),
        "case": "title", "tracking": 1, "sub_tracking": 4, "align": "center",
        "treatment": "line", "title_size": 116, "sub_size": 36,
    },
    "engraved": {  # timeless engraved caps — Copperplate (system)
        "label": "Copperplate — engraved classic",
        "title": (f"{_FONTS}/Copperplate.ttc", 0), "sub": (f"{_FONTS}/Copperplate.ttc", 0),
        "case": "upper", "tracking": 8, "sub_tracking": 3, "align": "center",
        "treatment": "engrave", "title_size": 76, "sub_size": 27, "system": True,
    },
    "didot": {  # premium fashion serif — Didot (system)
        "label": "Didot — premium serif",
        "title": (f"{_FONTS}/Didot.ttc", 0), "sub": (f"{_FONTS}/Didot.ttc", 0),
        "case": "title", "tracking": 1, "sub_tracking": 3, "align": "left",
        "treatment": "line", "title_size": 100, "sub_size": 34, "system": True,
    },
}
DEFAULT_STYLE = "cinzel"


def _hex(c: str, fallback=(255, 255, 255)) -> tuple[int, int, int]:
    try:
        c = c.lstrip("#")
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    except Exception:
        return fallback


def _font(spec, size):
    path, weight = spec
    try:
        f = ImageFont.truetype(path, size)
        # Set the weight on variable fonts (no-op / harmless on static fonts).
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
        return f
    except Exception:
        return ImageFont.truetype(f"{_CORE}/SFNS.ttf", size)


def _base_image(image_path: str) -> Image.Image:
    img = Image.open(image_path).convert("RGB")
    sw, sh = img.size
    s = max(TW / sw, TH / sh)
    img = img.resize((int(sw * s), int(sh * s)), Image.LANCZOS)
    x = (img.width - TW) // 2
    y = (img.height - TH) // 2
    return img.crop((x, y, x + TW, y + TH))


def _scrim(img, position, strength=150):
    """Darken ONLY the edge where the text sits, fading to fully clear elsewhere so
    the image stays vivid. upper→darken top, lower→darken bottom, center→soft band.

    `strength` is the peak opacity (0–255). 0 disables the scrim entirely so the
    underlying image shows through unchanged behind the text.
    """
    strength = max(0, min(255, int(strength)))
    if strength == 0:
        return img
    g = Image.new("L", (1, TH), 0)
    for i in range(TH):
        f = i / TH
        if position == "upper":
            a = max(0.0, 1.0 - f / 0.42)            # opaque at top → clear by 42%
        elif position == "center":
            a = max(0.0, 1.0 - abs(f - 0.5) / 0.30) * 0.85
        else:  # lower
            a = max(0.0, (f - 0.58) / 0.42)          # clear until 58% → opaque at bottom
        g.putpixel((0, i), int(strength * a))
    return Image.composite(Image.new("RGB", (TW, TH), (0, 0, 0)), img, g.resize((TW, TH)))


def _measure(draw, text, font, tr):
    return sum(draw.textlength(c, font=font) + tr for c in text) - tr


def _draw_spaced(draw, xy, text, font, fill, tr=0):
    x, y = xy
    for dx in (-3, -1, 1, 3):
        for dy in (-3, -1, 1, 3):
            xx = x
            for ch in text:
                draw.text((xx + dx, y + dy), ch, font=font, fill=(0, 0, 0))
                xx += draw.textlength(ch, font=font) + tr
    xx = x
    for ch in text:
        draw.text((xx, y), ch, font=font, fill=fill)
        xx += draw.textlength(ch, font=font) + tr


def render_thumbnail(image_path: str, out_path: str, hook: str, subtitle: str = "",
                     style: str = DEFAULT_STYLE, accent: str = "#d6b46e",
                     align: str = "", position: str = "lower",
                     title_scale: float = 1.0, sub_scale: float = 1.0,
                     scrim_opacity: float = 1.0) -> str:
    """Render a 1280x720 branded thumbnail. `style` must be a key in STYLES.

    title_scale / sub_scale multiply each style's default title_size / sub_size.
    scrim_opacity multiplies the dark band behind the text (0 = no darkening,
    1 = current default, up to 1.5 for heavy contrast on bright images).
    """
    sd = STYLES.get(style, STYLES[DEFAULT_STYLE])
    align = align or sd["align"]
    accent_rgb = _hex(accent)

    # Clamp scales so the user can't accidentally render unreadable or
    # off-canvas thumbnails. UI exposes 0.5–1.5 as the safe range.
    title_scale = max(0.5, min(2.0, float(title_scale or 1.0)))
    sub_scale = max(0.5, min(2.0, float(sub_scale or 1.0)))
    scrim_opacity = max(0.0, min(1.5, float(scrim_opacity if scrim_opacity is not None else 1.0)))

    hook = (hook or "").strip()
    if sd["case"] == "upper":
        hook = hook.upper()
    elif sd["case"] == "title":
        hook = hook.title()
    subtitle = (subtitle or "").strip()
    if sd["case"] == "upper" and subtitle:
        subtitle = subtitle.upper()

    img = _base_image(image_path)

    # Darken only the edge where the text sits (keeps the image vivid).
    # Default peak strength is 150/255; user can scale up to ~225 or down to 0.
    img = _scrim(img, position, strength=int(150 * scrim_opacity))
    if position == "upper":
        title_y = int(TH * 0.09)
    elif position == "center":
        title_y = int(TH * 0.40)
    else:  # lower
        title_y = int(TH * 0.66)

    title_size_px = max(28, int(round(sd["title_size"] * title_scale)))
    sub_size_px = max(14, int(round(sd["sub_size"] * sub_scale)))
    title_font = _font(sd["title"], title_size_px)
    sub_font = _font(sd["sub"], sub_size_px)
    margin = 64

    draw = ImageDraw.Draw(img)
    tw = _measure(draw, hook, title_font, sd["tracking"])
    if align == "center":
        tx = (TW - tw) // 2
    else:
        tx = margin

    # Treatment: glow draws an accent-colored, blurred copy behind the title.
    if sd["treatment"] == "glow":
        glow = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gx = tx
        for ch in hook:
            gd.text((gx, title_y), ch, font=title_font, fill=accent_rgb + (255,))
            gx += draw.textlength(ch, font=title_font) + sd["tracking"]
        img = Image.alpha_composite(img.convert("RGBA"),
                                    glow.filter(ImageFilter.GaussianBlur(12))).convert("RGB")
        draw = ImageDraw.Draw(img)

    _draw_spaced(draw, (tx, title_y), hook, title_font, (245, 245, 248), sd["tracking"])

    # Accent rule + subtitle. Spacing tracks the *rendered* title height so the
    # subtitle still sits cleanly below the hook when the user scales the title.
    sub_y = title_y + title_size_px + 22
    if sd["treatment"] == "line":
        lx2 = tx + min(tw, int(TW * 0.42))
        draw.line([(tx, sub_y - 6), (lx2, sub_y - 6)], fill=accent_rgb, width=2)
        sub_y += 8
    elif sd["treatment"] == "engrave":
        draw.rectangle([(TW // 2 - 60, title_y - 22), (TW // 2 + 60, title_y - 18)], fill=accent_rgb)

    if subtitle:
        sw = _measure(draw, subtitle, sub_font, sd["sub_tracking"])
        sx = (TW - sw) // 2 if align == "center" else tx
        _draw_spaced(draw, (sx, sub_y), subtitle, sub_font, accent_rgb, sd["sub_tracking"])

    img.save(out_path, quality=92)
    return out_path


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def choose_thumbnail_design(image_path: str, title: str = "", mood: str = "",
                            setting: str = "", duration_label: str = "1 Hour",
                            anthropic_key: Optional[str] = None,
                            model: str = "claude-sonnet-4-6") -> dict:
    """Claude art director: LOOK at the scene + brief, pick the typographic style,
    a complementary accent color, the hook + subtitle text, and where to place the
    text so it doesn't cover the focal point. Returns a design dict for
    render_thumbnail(). Falls back to a default design on any failure."""
    fallback = {
        "style": DEFAULT_STYLE,
        "hook": (title or "Ambient Soundscape")[:30],
        "subtitle": f"Ambient · {duration_label}",
        "accent": "#d6b46e",
        "align": "center",
        "position": "lower",
    }
    if not anthropic_key:
        return fallback
    try:
        im = Image.open(image_path).convert("RGB")
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        b64 = base64.standard_b64encode(buf.getvalue()).decode()

        styles_help = (
            "engraved = timeless engraved caps (classic, neutral); "
            "cinematic = premium film-score serif (epic, prestige); "
            "scifi = geometric space/tech with a glow (futuristic); "
            "literary = classic book serif (for book/story themes); "
            "elegant = soft humanist (calm, meditative); "
            "dramatic = bold high-contrast serif (intense)."
        )
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key)
        resp = client.messages.create(
            model=model, max_tokens=400,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text":
                    f"You are the thumbnail art director for an ambient-music YouTube channel.\n"
                    f"Track: {title}\nMood: {mood}\nSetting: {setting}\nDuration: {duration_label}\n\n"
                    f"LOOK at this scene and design a thumbnail. Choose ONE typographic style "
                    f"that matches the vibe: {styles_help}\n\n"
                    "Return ONLY JSON:\n"
                    "{\n"
                    '  "style": "<one of: engraved|cinematic|scifi|literary|elegant|dramatic>",\n'
                    '  "hook": "<the SHORT punchy title to print, <=24 chars, the recognizable subject>",\n'
                    '  "subtitle": "<short descriptor + duration, e.g. \'Deep Space Ambience · 1 Hour\'>",\n'
                    '  "accent": "#RRGGBB (a color pulled FROM the image that pops against it)",\n'
                    '  "align": "left|center",\n'
                    '  "position": "upper|center|lower (put text where it WON\'T cover the focal subject)"\n'
                    "}"},
            ]}],
        )
        data = json.loads(_strip_fences(resp.content[0].text))
        # sanitize
        out = dict(fallback)
        if data.get("style") in STYLES:
            out["style"] = data["style"]
        for k in ("hook", "subtitle", "accent"):
            if isinstance(data.get(k), str) and data[k].strip():
                out[k] = data[k].strip()
        if data.get("align") in ("left", "center"):
            out["align"] = data["align"]
        if data.get("position") in ("upper", "center", "lower"):
            out["position"] = data["position"]
        out["hook"] = out["hook"][:30]
        return out
    except Exception as e:
        print(f"  [thumbnail] art director fell back to default: {e}", flush=True)
        return fallback


def make_thumbnail(image_path: str, out_path: str, title: str = "", mood: str = "",
                   setting: str = "", duration_label: str = "1 Hour",
                   anthropic_key: Optional[str] = None,
                   design: Optional[dict] = None) -> dict:
    """High-level: pick a design (LLM) unless one is provided, render it, return the
    design used (so the UI can show/edit it)."""
    if design is None:
        design = choose_thumbnail_design(image_path, title, mood, setting,
                                         duration_label, anthropic_key)
    render_thumbnail(image_path, out_path,
                     hook=design.get("hook", title), subtitle=design.get("subtitle", ""),
                     style=design.get("style", DEFAULT_STYLE),
                     accent=design.get("accent", "#d6b46e"),
                     align=design.get("align", ""), position=design.get("position", "lower"),
                     title_scale=design.get("title_scale", 1.0),
                     sub_scale=design.get("sub_scale", 1.0),
                     scrim_opacity=design.get("scrim_opacity", 1.0))
    return design
