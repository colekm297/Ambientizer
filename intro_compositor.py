#!/usr/bin/env python3
"""
intro_compositor.py — add a branded channel intro to an exported ambient video.

STANDALONE + SELF-CONTAINED. Does not import or modify app.py / motion_compositor.
It operates on an already-exported final video (the one the export route writes to
job["visual_video_path"]) as a post-process step, so it can be wired into the
export flow later with a single call — no entanglement with the export internals.

Two styles (the user wants both, selectable):

  • "overlay"  — the real ambient scene plays from t=0; the channel name fades in
                 over it for ~10s then fades out. Music is untouched (it's already
                 in the source video). PERFORMANCE: only the first N seconds are
                 re-encoded (to composite the title); the rest of the hour is
                 stream-copied and concatenated, so an hour video stays fast.

  • "card"     — a distinct animated title card (Ken-Burns drift over a background
                 image + the channel name) plays for ~Ns, then crossfades into the
                 main video. Stronger "show open" identity.

Text is rendered with PIL (this ffmpeg build has no drawtext/libfreetype), which
also gives nicer typography — letter-spacing, soft glow, drop shadow.

CLI (for testing):
  python intro_compositor.py --video out.mp4 --name "The Space of Sound" \
      --style overlay --out out_intro.mp4
  python intro_compositor.py --video out.mp4 --name "The Space of Sound" \
      --subtitle "Ambient worlds for deep focus" --style card --bg scene.png \
      --out out_intro.mp4
"""

import os
import sys
import json
import math
import shlex
import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).resolve().parent
FONTS_DIR = HERE / "fonts"

# ffmpeg/ffprobe absolute paths (launchd has no Homebrew on PATH — see AGENTS.md).
FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe" if os.path.exists("/opt/homebrew/bin/ffprobe") else "ffprobe"

# Font presets — point at the .ttf files already in ./fonts.
FONT_PRESETS = {
    "hailmary": "HailMarySans.otf",  # Project Hail Mary display face — default
    "cinzel": "Cinzel.ttf",        # classical, cinematic
    "cormorant": "Cormorant.ttf",  # elegant serif
    "bebas": "BebasNeue.ttf",      # bold condensed display
    "oswald": "Oswald.ttf",        # modern condensed
    "nolan": "ArchivoBlack.ttf",   # heavy grotesque — matches the nolan thumbnail style
    "nolan_tall": "Anton.ttf",     # condensed heavy — matches nolan_tall
}
DEFAULT_FONT = "hailmary"


def _run(cmd: list[str]):
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n  {shlex.join(cmd)}\n{proc.stderr[-800:]}")


def probe(video: str) -> dict:
    """Return {width,height,fps,duration,vcodec,pix_fmt,has_audio}."""
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", video],
        capture_output=True, text=True, timeout=30,
    )
    data = json.loads(r.stdout or "{}")
    vinfo = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    num, den = (vinfo.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den or 1)
    return {
        "width": int(vinfo.get("width", 1920)),
        "height": int(vinfo.get("height", 1080)),
        "fps": round(fps, 3),
        "duration": float(data.get("format", {}).get("duration", 0) or 0),
        "vcodec": vinfo.get("codec_name", ""),
        "pix_fmt": vinfo.get("pix_fmt", ""),
        "has_audio": has_audio,
    }


def _load_font(font_key: str, size: int) -> ImageFont.FreeTypeFont:
    fname = FONT_PRESETS.get(font_key, FONT_PRESETS[DEFAULT_FONT])
    path = FONTS_DIR / fname
    if not path.exists():  # fall back to a system serif
        for sysf in ("/System/Library/Fonts/Optima.ttc",
                     "/System/Library/Fonts/Times.ttc"):
            if os.path.exists(sysf):
                return ImageFont.truetype(sysf, size)
        return ImageFont.load_default()
    return ImageFont.truetype(str(path), size)


def _draw_tracked_text(draw, xy, text, font, fill, tracking=0):
    """Draw text with letter-spacing (tracking, in px). Returns total width."""
    x, y = xy
    total = 0
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        w = draw.textlength(ch, font=font)
        x += w + tracking
        total += w + tracking
    return total - tracking if text else 0


def _text_width(draw, text, font, tracking=0):
    w = sum(draw.textlength(ch, font=font) + tracking for ch in text)
    return w - tracking if text else 0


def hex_to_rgb(value, default=(180, 200, 255)):
    """Parse '#rrggbb' (or 'rrggbb') → (r,g,b). Returns default on bad input."""
    if not value:
        return default
    s = str(value).lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return default


def render_title_png(out_png: str, width: int, height: int, name: str,
                     subtitle: str = "", font_key: str = DEFAULT_FONT,
                     color=(255, 255, 255), accent=(180, 200, 255),
                     size_scale: float = 1.0):
    """Render a transparent PNG with the channel name (+ optional subtitle),
    centered, with a soft glow + drop shadow for legibility over any scene.
    size_scale multiplies the base title size (1.0 = default ~8.5% of height)."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # Size the title to ~8.5% of frame height, scaled by the user's size choice.
    size_scale = max(0.5, min(2.0, float(size_scale or 1.0)))
    size = max(28, int(height * 0.085 * size_scale))
    font = _load_font(font_key, size)
    tracking = max(2, int(size * 0.12))
    name_up = name.upper() if font_key in ("cinzel", "bebas", "oswald", "nolan", "nolan_tall") else name

    measure = ImageDraw.Draw(img)
    tw = _text_width(measure, name_up, font, tracking)
    # Shrink to fit within 82% width if needed.
    while tw > width * 0.82 and size > 20:
        size -= 4
        font = _load_font(font_key, size)
        tracking = max(2, int(size * 0.12))
        tw = _text_width(measure, name_up, font, tracking)

    # Subtitle stays in the SAME family as the title. It used to hard-code
    # Cormorant, which pairs a serif subtitle under a grotesque title and reads
    # as two unrelated designs -- and it silently overrode whatever font the
    # caller picked. Serif titles still get a contrasting sans below.
    _sub_key = "oswald" if font_key in ("cormorant", "cinzel") else font_key
    sub_font = _load_font(_sub_key,
                          max(18, int(size * 0.34)))
    sub_track = max(1, int(size * 0.06))
    sub_w = _text_width(measure, subtitle, sub_font, sub_track) if subtitle else 0

    block_h = size + (int(size * 0.7) if subtitle else 0)
    name_x = (width - tw) / 2
    name_y = (height - block_h) / 2

    # Glow layer: draw text in accent on its own canvas, blur, paste under.
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    _draw_tracked_text(gd, (name_x, name_y), name_up, font, accent + (255,), tracking)
    glow = glow.filter(ImageFilter.GaussianBlur(int(size * 0.22)))
    img = Image.alpha_composite(img, glow)

    draw = ImageDraw.Draw(img)
    # Drop shadow.
    _draw_tracked_text(draw, (name_x + 2, name_y + 3), name_up, font,
                       (0, 0, 0, 170), tracking)
    # Main text.
    _draw_tracked_text(draw, (name_x, name_y), name_up, font, color + (255,), tracking)

    # Thin accent rule under the title.
    rule_y = int(name_y + size * 1.18)
    rule_w = int(tw * 0.5)
    rule_x = int((width - rule_w) / 2)
    draw.line([(rule_x, rule_y), (rule_x + rule_w, rule_y)],
              fill=accent + (200,), width=max(1, int(size * 0.02)))

    if subtitle:
        sy = rule_y + int(size * 0.18)
        sx = (width - sub_w) / 2
        _draw_tracked_text(draw, (sx + 1, sy + 1), subtitle, sub_font,
                           (0, 0, 0, 150), sub_track)
        _draw_tracked_text(draw, (sx, sy), subtitle, sub_font,
                           (225, 232, 245, 235), sub_track)

    img.save(out_png)
    return out_png


def add_intro_overlay(video: str, out: str, name: str, subtitle: str = "",
                      duration: float = 10.0, fade: float = 1.5,
                      font_key: str = DEFAULT_FONT, color=None,
                      size_scale: float = 1.0) -> str:
    """Style A: fade the title in/out over the first `duration`s of the scene.
    Re-encodes only the head; stream-copies the (long) tail; concats. Keeps the
    source audio intact throughout. `color` is a hex string for the glow/accent."""
    info = probe(video)
    W, H, fps = info["width"], info["height"], info["fps"]
    total = info["duration"]
    head = min(duration, max(1.0, total))
    fade = min(fade, head / 3)
    accent = hex_to_rgb(color) if color else (180, 200, 255)

    tmp = Path(tempfile.mkdtemp(prefix="intro_"))
    try:
        title_png = render_title_png(str(tmp / "title.png"), W, H, name, subtitle,
                                     font_key, accent=accent, size_scale=size_scale)

        head_mp4 = str(tmp / "head.mp4")
        # Overlay the title with alpha fade in/out only on the head segment.
        filt = (
            f"[1:v]format=rgba,"
            f"fade=t=in:st=0:d={fade}:alpha=1,"
            f"fade=t=out:st={head - fade}:d={fade}:alpha=1[ttl];"
            f"[0:v][ttl]overlay=0:0:format=auto[v]"
        )
        head_cmd = [
            FFMPEG, "-y",
            "-t", f"{head}", "-i", video,
            "-loop", "1", "-t", f"{head}", "-i", title_png,
            "-filter_complex", filt,
            "-map", "[v]",
        ]
        if info["has_audio"]:
            head_cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "320k"]
        head_cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                     "-pix_fmt", "yuv420p", "-r", f"{fps}", head_mp4]
        _run(head_cmd)

        # Tail: everything after `head`. Stream-copy if codec is concat-compatible.
        tail_mp4 = str(tmp / "tail.mp4")
        can_copy = info["vcodec"] == "h264" and info["pix_fmt"] in ("yuv420p", "yuvj420p")
        tail_cmd = [FFMPEG, "-y", "-ss", f"{head}", "-i", video]
        if can_copy:
            tail_cmd += ["-c", "copy"]
        else:
            tail_cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "18",
                         "-pix_fmt", "yuv420p"]
            if info["has_audio"]:
                tail_cmd += ["-c:a", "aac", "-b:a", "320k"]
        tail_cmd += [tail_mp4]
        _run(tail_cmd)

        # Concat (demuxer, stream-copy — both segments are H.264 yuv420p now).
        listf = tmp / "concat.txt"
        listf.write_text(f"file '{head_mp4}'\nfile '{tail_mp4}'\n")
        _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
              "-c", "copy", out])
        return out
    finally:
        for p in tmp.glob("*"):
            try: p.unlink()
            except OSError: pass
        try: tmp.rmdir()
        except OSError: pass


def add_video_fades(video: str, out: str, fade_in: float = 10.0, fade_out: float = 8.0) -> str:
    """Add a gentle VIDEO fade-in from black (head) and fade-out to black (tail)
    so an exported video doesn't start/end full-tilt. Stays fast: only the short
    head + tail are re-encoded, the long middle is stream-copied, then concat'd.
    Audio is COPIED untouched (the export already applies its audio fades)."""
    info = probe(video)
    fps, total = info["fps"], info["duration"]
    fi = max(0.0, min(fade_in, total / 3))
    fo = max(0.0, min(fade_out, total / 3))
    if fi <= 0 and fo <= 0:
        return video
    can_copy = info["vcodec"] == "h264" and info["pix_fmt"] in ("yuv420p", "yuvj420p")
    acopy = ["-c:a", "copy"] if info["has_audio"] else []
    venc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", f"{fps}"]
    tmp = Path(tempfile.mkdtemp(prefix="vfade_"))
    try:
        segs = []
        if fi > 0:
            head = str(tmp / "head.mp4")
            _run([FFMPEG, "-y", "-t", f"{fi}", "-i", video,
                  "-vf", f"fade=t=in:st=0:d={fi}", *venc, *acopy, head])
            segs.append(head)
        mid = str(tmp / "mid.mp4")
        midcmd = [FFMPEG, "-y", "-ss", f"{fi}"]
        if fo > 0:
            midcmd += ["-to", f"{total - fo}"]
        midcmd += ["-i", video]
        midcmd += (["-c", "copy"] if can_copy else [*venc, *acopy])
        midcmd += [mid]
        _run(midcmd)
        segs.append(mid)
        if fo > 0:
            tail = str(tmp / "tail.mp4")
            _run([FFMPEG, "-y", "-ss", f"{total - fo}", "-i", video,
                  "-vf", f"fade=t=out:st=0:d={fo}", *venc, *acopy, tail])
            segs.append(tail)
        listf = tmp / "c.txt"
        listf.write_text("".join(f"file '{s}'\n" for s in segs))
        _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listf), "-c", "copy", out])
        return out
    finally:
        for p in tmp.glob("*"):
            try: p.unlink()
            except OSError: pass
        try: tmp.rmdir()
        except OSError: pass


def add_intro_card(video: str, out: str, name: str, subtitle: str = "",
                   duration: float = 7.0, xfade: float = 1.2,
                   font_key: str = DEFAULT_FONT, bg_image: str = None,
                   color=None, size_scale: float = 1.0) -> str:
    """Style B: an animated title card (slow Ken-Burns zoom over `bg_image`, or a
    dark cosmic gradient if none) that crossfades into the main video. The main
    video's audio plays under the card from t=0 so the music is continuous."""
    info = probe(video)
    W, H, fps = info["width"], info["height"], info["fps"]
    tmp = Path(tempfile.mkdtemp(prefix="introcard_"))
    try:
        # Background for the card.
        if bg_image and os.path.exists(bg_image):
            base = Image.open(bg_image).convert("RGB").resize((W, H))
            base = base.filter(ImageFilter.GaussianBlur(8))
            # Darken for text legibility.
            dark = Image.new("RGB", (W, H), (0, 0, 0))
            base = Image.blend(base, dark, 0.45)
        else:
            base = _cosmic_gradient(W, H)
        bg_png = str(tmp / "bg.png")
        base.save(bg_png)

        title_png = render_title_png(str(tmp / "title.png"), W, H, name, subtitle,
                                     font_key, accent=hex_to_rgb(color) if color else (180, 200, 255),
                                     size_scale=size_scale)

        # Card clip: slow zoom on bg + title fading in. Silent (audio comes from
        # main). The bg PNG is already at WxH — DON'T prescale (zoompan at 4K is
        # pathologically slow). zoompan runs at native res for a fast render.
        card_mp4 = str(tmp / "card.mp4")
        zf = int(duration * fps)
        card_filt = (
            f"[0:v]zoompan=z='min(zoom+0.0006,1.10)':d={zf}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={fps}[bg];"
            f"[1:v]format=rgba,fade=t=in:st=0.4:d=1.4:alpha=1[ttl];"
            f"[bg][ttl]overlay=0:0:format=auto,fade=t=out:st={duration-xfade}:d={xfade}[v]"
        )
        # IMPORTANT: bg image is fed ONCE (no -loop). With -loop, zoompan emits
        # d frames PER input frame → tens of thousands of frames (pathological).
        # A single input frame makes zoompan emit exactly d frames.
        _run([FFMPEG, "-y",
              "-i", bg_png,
              "-loop", "1", "-t", f"{duration}", "-i", title_png,
              "-filter_complex", card_filt, "-map", "[v]",
              "-c:v", "libx264", "-preset", "fast", "-crf", "18",
              "-pix_fmt", "yuv420p", "-r", f"{fps}", card_mp4])

        # Crossfade card → main video; main audio plays under the whole thing.
        # Video: xfade at the card/main boundary. Audio: take main audio, delayed
        # so it starts at t=0 (under the card) and runs continuously.
        out_filt = (
            f"[0:v][1:v]xfade=transition=fade:duration={xfade}:offset={duration-xfade}[v]"
        )
        cmd = [FFMPEG, "-y", "-i", card_mp4, "-i", video,
               "-filter_complex", out_filt, "-map", "[v]"]
        if info["has_audio"]:
            cmd += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "320k"]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-pix_fmt", "yuv420p", out]
        _run(cmd)
        return out
    finally:
        for p in tmp.glob("*"):
            try: p.unlink()
            except OSError: pass
        try: tmp.rmdir()
        except OSError: pass


def _cosmic_gradient(W: int, H: int) -> Image.Image:
    """A dark violet→black radial-ish gradient as a fallback card background."""
    base = Image.new("RGB", (W, H), (6, 4, 14))
    top = Image.new("RGB", (W, H), (30, 18, 54))
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    for i in range(40):
        a = int(120 * (1 - i / 40))
        md.ellipse([W*0.5 - W*0.7*(i/40), H*0.4 - H*0.7*(i/40),
                    W*0.5 + W*0.7*(i/40), H*0.4 + H*0.7*(i/40)], fill=a)
    mask = mask.filter(ImageFilter.GaussianBlur(60))
    return Image.composite(top, base, mask)


def add_intro(video: str, out: str, name: str, style: str = "overlay", **kw) -> str:
    if style == "card":
        return add_intro_card(video, out, name, **kw)
    return add_intro_overlay(video, out, name, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="exported final video (mp4)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True, help="channel name")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--style", choices=["overlay", "card"], default="overlay")
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--font", choices=list(FONT_PRESETS), default=DEFAULT_FONT)
    ap.add_argument("--bg", default=None, help="background image for card style")
    args = ap.parse_args()

    kw = dict(subtitle=args.subtitle, font_key=args.font)
    if args.duration:
        kw["duration"] = args.duration
    if args.style == "card":
        kw["bg_image"] = args.bg
    out = add_intro(args.video, args.out, args.name, style=args.style, **kw)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
