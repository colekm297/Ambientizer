"""Niche-pattern thumbnails for Test & compare (2026-10-23 process plan, experiment 1).
Pattern from Ambient Worlds / 3791: brighter image, big centered title in a film-poster serif,
iconic place + a promise line ("Peaceful Music & Ambience"). Control = the shipped thumbnail.png."""
import sys
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
TW, TH = 1280, 720
CINZEL, BEBAS = "fonts/Cinzel.ttf", "fonts/BebasNeue.ttf"
CREAM, GOLD = (250, 244, 230), (236, 196, 120)

def lift(im, b=1.35, c=1.08, s=1.12):
    im = ImageEnhance.Brightness(im).enhance(b); im = ImageEnhance.Contrast(im).enhance(c)
    return ImageEnhance.Color(im).enhance(s)

def center_scrim(im, cy, h, strength=120):
    m = Image.new("L", (TW, TH), 0); d = ImageDraw.Draw(m)
    d.ellipse((TW*0.08, cy-h/2, TW*0.92, cy+h/2), fill=strength)
    m = m.filter(ImageFilter.GaussianBlur(70))
    return Image.composite(Image.new("RGB", (TW, TH), (6, 5, 4)), im, m)

def line(d, s, font, cy, fill, track=0, stroke=3):
    w = sum(d.textlength(c, font=font) for c in s) + track*(len(s)-1); x = (TW-w)/2
    for c in s:
        d.text((x+3, cy+4), c, font=font, fill=(0,0,0), anchor="lm", stroke_width=stroke, stroke_fill=(0,0,0))
        d.text((x, cy), c, font=font, fill=fill, anchor="lm", stroke_width=stroke, stroke_fill=(20,14,8))
        x += d.textlength(c, font=font) + track

def make(src, out, lines, crop=None, cy=380, scrim_h=330):
    im = Image.open(src).convert("RGB")
    if crop: im = im.crop(crop)
    im = lift(im.resize((TW, TH), Image.LANCZOS))
    im = center_scrim(im, cy, scrim_h); d = ImageDraw.Draw(im)
    for text, font, size, y, fill, track in lines:
        line(d, text, ImageFont.truetype(font, size), y, fill, track, 4 if size > 60 else 2)
    im.save(out, quality=95); return im

P = "output/release/penelope_loom"; L = "output/release/dusk_arrakis"
ims = [
 make(f"{P}/start.png", f"{P}/thumbnail_n1_place.png", [
   ("THE ODYSSEY", CINZEL, 120, 300, GOLD, 4),
   ("A NIGHT ON ITHACA", CINZEL, 64, 410, CREAM, 3),
   ("PEACEFUL MUSIC & AMBIENCE", CINZEL, 34, 485, CREAM, 6)]),
 make(f"{P}/start.png", f"{P}/thumbnail_n2_close.png", [
   ("THE ODYSSEY", CINZEL, 112, 300, GOLD, 4),
   ("PENELOPE'S LOOM", CINZEL, 62, 405, CREAM, 3),
   ("PEACEFUL MUSIC & AMBIENCE", CINZEL, 32, 478, CREAM, 6)], crop=(220, 120, 1700, 952)),
 make(f"{L}/start.png", f"{L}/thumbnail_n1_place.png", [
   ("DUNE", CINZEL, 170, 290, GOLD, 40),
   ("ARRAKIS AT DUSK", CINZEL, 62, 410, CREAM, 4),
   ("PEACEFUL DESERT MUSIC & AMBIENCE", CINZEL, 30, 480, CREAM, 5)]),
 make(f"{L}/start.png", f"{L}/thumbnail_n2_focus.png", [
   ("DUNE", CINZEL, 170, 290, GOLD, 40),
   ("DEEP FOCUS ON ARRAKIS", CINZEL, 56, 410, CREAM, 3),
   ("1 HOUR OF DESERT MUSIC & AMBIENCE", CINZEL, 30, 478, CREAM, 5)]),
]
sheet = Image.new("RGB", (2560, 1440+400), (24,24,24))
ctrl = [Image.open(f"{P}/thumbnail.png").convert("RGB").resize((TW,TH)), Image.open(f"{L}/thumbnail.png").convert("RGB").resize((TW,TH))]
for i, im in enumerate([ctrl[0], ims[0], ims[1], ctrl[1], ims[2], ims[3]]):
    sheet.paste(im.resize((853, 480)), ((i%3)*853, (i//3)*480))
for i, im in enumerate(ims):  # phone size
    sheet.paste(im.resize((336, 189)), (i*350, 1000))
sheet.crop((0,0,2560,1200)).save(sys.argv[1] if len(sys.argv)>1 else "/tmp/x.jpg", quality=85); print("ok")
