"""Clickbait-direction thumbnail candidates for Dusk + Fair Wind (2026-09-18).

Big bold type (2-4 words), one focal element via crop-zoom, heavy contrast:
white fill, black stroke, drop shadow, bottom/top scrim. Plus a 1280/336/168
legibility sheet. Nothing here touches YouTube.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
OUT = "brand/out/thumbs"; import os; os.makedirs(OUT, exist_ok=True)
TW, TH = 1280, 720
ANTON = "fonts/Anton.ttf"; ARCHIVO = "fonts/ArchivoBlack.ttf"
AMBER = (255, 176, 74); GOLD = (255, 214, 120); WHITE = (250, 248, 244)

def crop(src, box):
    im = Image.open(src).convert("RGB"); w, h = im.size
    x0, y0, x1, y1 = box; c = im.crop((int(x0*w), int(y0*h), int(x1*w), int(y1*h)))
    # force 16:9 around the box centre
    cw, ch = c.size
    if cw/ch > 16/9: nw = int(ch*16/9); c = c.crop(((cw-nw)//2, 0, (cw-nw)//2+nw, ch))
    else: nh = int(cw*9/16); c = c.crop((0, (ch-nh)//2, cw, (ch-nh)//2+nh))
    return c.resize((TW, TH), Image.LANCZOS)

def scrim(im, where="bottom", strength=200, span=0.55):
    g = Image.new("L", (1, TH), 0); px = g.load()
    for y in range(TH):
        t = (y/TH - (1-span))/span if where == "bottom" else ((span*TH - y)/(span*TH))
        t = max(0.0, min(1.0, t)); px[0, y] = int(strength * (t**1.4))
    mask = g.resize((TW, TH)); black = Image.new("RGB", (TW, TH), (8, 6, 10))
    return Image.composite(black, im, mask)

def vignette(im, strength=110):
    m = Image.new("L", (TW, TH), 0); d = ImageDraw.Draw(m)
    d.ellipse((-TW*0.15, -TH*0.35, TW*1.15, TH*1.35), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(160)); m = m.point(lambda v: 255 - int((255-v)*strength/255))
    return Image.composite(im, Image.new("RGB", (TW, TH), (0, 0, 0)), m)

def text(im, s, size, xy, fill=WHITE, font=ANTON, stroke=10, anchor="ms", track=0):
    f = ImageFont.truetype(font, size); d = ImageDraw.Draw(im)
    x, y = xy
    if track:
        w = sum(d.textlength(c, font=f) for c in s) + track*(len(s)-1)
        cx = x - w/2 if anchor[0] == "m" else (x - w if anchor[0] == "r" else x)
        for c in s:
            d.text((cx+6, y+8), c, font=f, fill=(0, 0, 0), stroke_width=stroke, stroke_fill=(0, 0, 0), anchor="l"+anchor[1])
            d.text((cx, y), c, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0), anchor="l"+anchor[1])
            cx += d.textlength(c, font=f) + track
        return
    d.text((x+6, y+8), s, font=f, fill=(0, 0, 0), stroke_width=stroke, stroke_fill=(0, 0, 0), anchor=anchor)
    d.text((x, y), s, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0), anchor=anchor)

def pill(im, s, xy, bg=AMBER, fg=(20, 12, 6), size=44, pad=18, anchor="lt"):
    f = ImageFont.truetype(ARCHIVO, size); d = ImageDraw.Draw(im)
    w = d.textlength(s, font=f); x, y = xy
    if anchor[0] == "r": x -= w + 2*pad
    d.rounded_rectangle((x, y, x+w+2*pad, y+size+2*pad*0.7), radius=10, fill=bg)
    d.text((x+pad, y+pad*0.7-size*0.08), s, font=f, fill=fg)

DUNES = "output/release/dusk_arrakis/still_dunes_dusk.png"
SIETCH = "output/release/dusk_arrakis/still_sietch_dusk.png"
ITHACA = "inputs/ithaca_dawn2.png"; ITHACA_SIL = "inputs/ithaca_dawn.png"

def d1():  # IP callout, Temples-style: giant DUNE
    im = crop(DUNES, (0.18, 0.22, 0.82, 0.82)); im = scrim(im, "bottom", 210, 0.5); im = vignette(im, 90)
    text(im, "DUNE", 300, (TW//2, 520), track=14)
    text(im, "ARRAKIS AT DUSK", 76, (TW//2, 640), fill=AMBER, stroke=7, track=6)
    return im, "D1 IP: DUNE / ARRAKIS AT DUSK"

def d2():  # benefit hook on the sietch doorway
    im = crop(SIETCH, (0.12, 0.05, 0.88, 0.95)); im = scrim(im, "bottom", 200, 0.42)
    pill(im, "DUNE", (48, 44), size=52)
    text(im, "1 HOUR", 200, (TW//2, 560), track=8)
    text(im, "OF DEEP FOCUS", 84, (TW//2, 665), fill=AMBER, stroke=7, track=6)
    return im, "D2 benefit: 1 HOUR OF DEEP FOCUS"

def d3():  # curiosity: tight on the sun and the figure
    im = crop(DUNES, (0.28, 0.28, 0.72, 0.74)); im = scrim(im, "bottom", 220, 0.5); im = vignette(im, 100)
    pill(im, "DUNE", (48, 44), size=52)
    text(im, "LAST LIGHT", 230, (TW//2, 545), track=6)
    text(im, "ON ARRAKIS", 96, (TW//2, 665), fill=AMBER, stroke=8, track=8)
    return im, "D3 curiosity: LAST LIGHT ON ARRAKIS"

def f1():  # IP callout, Calypso-style: giant THE ODYSSEY
    im = crop(ITHACA, (0.02, 0.02, 0.9, 0.98)); im = scrim(im, "top", 200, 0.5); im = vignette(im, 80)
    text(im, "THE ODYSSEY", 210, (TW//2, 205), track=10)
    text(im, "FAIR WIND HOME", 78, (TW//2, 300), fill=GOLD, stroke=7, track=8)
    return im, "F1 IP: THE ODYSSEY / FAIR WIND HOME"

def f2():  # benefit
    im = crop(ITHACA, (0.02, 0.02, 0.9, 0.98)); im = scrim(im, "bottom", 210, 0.5)
    pill(im, "THE ODYSSEY", (48, 44), size=52, bg=GOLD)
    text(im, "1 HOUR", 210, (TW//2, 560), track=8)
    text(im, "DEEP WORK", 96, (TW//2, 668), fill=GOLD, stroke=8, track=8)
    return im, "F2 benefit: 1 HOUR DEEP WORK"

def f3():  # curiosity: the ship, going home
    im = crop(ITHACA, (0.3, 0.02, 0.98, 0.78)); im = scrim(im, "bottom", 220, 0.55); im = vignette(im, 90)
    pill(im, "THE ODYSSEY", (48, 44), size=52, bg=GOLD)
    text(im, "GOING HOME", 220, (TW//2, 560), track=6)
    text(im, "AFTER 20 YEARS", 90, (TW//2, 668), fill=GOLD, stroke=8, track=8)
    return im, "F3 curiosity: GOING HOME AFTER 20 YEARS"

if __name__ == "__main__":
    made = []
    for fn in (d1, d2, d3, f1, f2, f3):
        im, label = fn(); p = f"{OUT}/{fn.__name__}.png"; im.save(p, quality=95); made.append((p, label))
    # legibility sheet: 168 / 336 / 640 per candidate
    lf = ImageFont.truetype("fonts/Oswald.ttf", 20); pad = 24; row_h = 360 + 60
    sheet = Image.new("RGB", (pad*4 + 640 + 336 + 168, pad + row_h*6), (245, 245, 245)); d = ImageDraw.Draw(sheet)
    for i, (p, label) in enumerate(made):
        im = Image.open(p); y = pad + i*row_h; d.text((pad, y), label, fill=(0, 0, 0), font=lf); y += 30
        x = pad
        for w in (640, 336, 168):
            h = w*9//16; sheet.paste(im.resize((w, h), Image.LANCZOS), (x, y)); x += w + pad
    sheet.save(f"{OUT}/_sheet_sizes.png")
    print("\n".join(p for p, _ in made))
