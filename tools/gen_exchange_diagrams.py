"""Zharr Exchange - the three Workshop diagrams, as 1920x1080 PNGs.

    py tools\\gen_exchange_diagrams.py             write docs/workshop/zharr_exchange/*.png
    py tools\\gen_exchange_diagrams.py --selftest  assert nothing is clipped or overlapping

Numbers here mirror the constants in
Modding Files/pack/script/campaign/mod/zzz_derpy_chd_exchange.lua - see the fact table in
docs/sessions/WORKSHOP_POST_ZHARR_EXCHANGE_20260908.md. Change one there, change it here.
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "docs" / "workshop" / "zharr_exchange"
W, H = 1920, 1080

BG      = (18, 15, 12)
PANEL   = (30, 25, 21)
EDGE    = (66, 55, 45)
INK     = (232, 221, 207)
MUTED   = (138, 127, 112)
EMBER   = (217, 98, 43)
GOLD    = (201, 162, 39)
GOOD    = (127, 166, 80)
BAD     = (184, 67, 58)
COOL    = (70, 108, 130)

F = "C:/Windows/Fonts/"
def font(name, size):
    return ImageFont.truetype(F + name, size)

TITLE  = lambda s: font("seguisb.ttf", s)
BODY   = lambda s: font("segoeui.ttf", s)
MONO   = lambda s: font("consola.ttf", s)

# every text run drawn, as (text, ink_bbox, clip_bbox) - the selftest's only input
_DRAWN = []


def text(d, xy, s, fnt, fill=INK, anchor="la", clip=None):
    """Draw, and record the ink box against the box it is promised to stay inside."""
    d.text(xy, s, font=fnt, fill=fill, anchor=anchor)
    box = d.textbbox(xy, s, font=fnt, anchor=anchor)
    _DRAWN.append((s, box, clip if clip else (0, 0, W, H)))


def panel(d, box, fill=PANEL, edge=EDGE, width=2):
    d.rectangle(box, fill=fill, outline=edge, width=width)


def canvas():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W - 1, 7), fill=EMBER)
    return img, d


def header(d, title, sub):
    text(d, (90, 70), title, TITLE(64), INK, clip=(0, 0, W, 175))
    text(d, (90, 152), sub, BODY(30), MUTED, clip=(0, 140, W, 200))


def footer(d, s):
    text(d, (90, H - 62), s, BODY(26), MUTED, clip=(0, H - 90, W, H))


def arrow(d, x0, y0, x1, y1, fill=MUTED, width=3, head=12):
    d.line((x0, y0, x1, y1), fill=fill, width=width)
    if y1 > y0:                      # down
        d.polygon([(x1, y1), (x1 - head, y1 - head), (x1 + head, y1 - head)], fill=fill)
    elif x1 > x0:                    # right
        d.polygon([(x1, y1), (x1 - head, y1 - head), (x1 - head, y1 + head)], fill=fill)
    else:                            # left
        d.polygon([(x1, y1), (x1 + head, y1 - head), (x1 + head, y1 + head)], fill=fill)


# ---------------------------------------------------------------- 1: the ladder

def diagram_ladder():
    img, d = canvas()
    header(d, "Where a price comes from",
           "One 42-rung ladder. Every rung is 10% from its neighbour.")

    # the ladder bar, cool at the glut end, ember at the famine end
    bx0, bx1, by, bh = 150, 1770, 278, 58
    for i in range(bx1 - bx0):
        t = i / (bx1 - bx0)
        c = tuple(int(COOL[k] + (EMBER[k] - COOL[k]) * t) for k in range(3))
        d.line((bx0 + i, by, bx0 + i, by + bh), fill=c)
    d.rectangle((bx0, by, bx1, by + bh), outline=EDGE, width=2)

    for rung, label, price, col in ((1, "rung 1", "~102g", INK),
                                    (25, "rung 25  neutral", "1000g", (255, 255, 255)),
                                    (42, "rung 42", "~5054g", INK)):
        x = bx0 + (bx1 - bx0) * (rung - 1) / 41
        d.line((x, by - 18, x, by + bh + 18), fill=INK, width=3)
        anchor = "la" if rung == 1 else ("ra" if rung == 42 else "ma")
        ax = x + 14 if rung == 1 else (x - 14 if rung == 42 else x)
        text(d, (ax, by + bh + 30), label, BODY(28), MUTED, anchor=anchor)
        text(d, (ax, by + bh + 68), price, MONO(38), col, anchor=anchor)

    text(d, (bx0 + 14, by - 62), "glut - the world is drowning in it", BODY(28), COOL)
    text(d, (bx1 - 14, by - 62), "famine - nobody is making any", BODY(28), EMBER, anchor="ra")

    # the five shifts
    top = 460
    text(d, (150, top),
         "The base rung comes from world output, weighted for who owns it. "
         "Four things then move it, every turn:", BODY(32), INK)

    rows = [("Pressure", "your own net buying - 4 lots is a rung", "+/- 6 rungs", EMBER),
            ("Appetite", "what the world's cultures want, and how much of it is at war", "+/- 2 rungs", GOLD),
            ("Shock",    "sacks, razes, sieges and raids take supply off the market", "+/- 6 rungs", BAD),
            ("Book",     "what the AI houses are holding", "+/- 2 rungs", COOL)]

    y = top + 64
    for name, why, cap, col in rows:
        box = (150, y, 1770, y + 92)
        panel(d, box)
        d.rectangle((150, y, 158, y + 92), fill=col)
        text(d, (200, y + 14), name, TITLE(34), col, clip=box)
        text(d, (200, y + 56), why, BODY(26), MUTED, clip=box)
        text(d, (1740, y + 28), cap, MONO(34), INK, anchor="ra", clip=box)
        y += 104

    d.line((150, y + 10, 1770, y + 10), fill=EDGE, width=2)
    text(d, (200, y + 26), "= the number on the Buy button this turn", TITLE(36), INK)
    text(d, (1740, y + 32), "clamped to 1 - 42", MONO(28), MUTED, anchor="ra")

    footer(d, "Supply is production, not region count. A besieged, razed or abandoned "
              "region makes nothing, so the price of what it made goes up.")
    return img


# ------------------------------------------------------------- 2: the warehouse

def diagram_warehouse():
    img, d = canvas()
    header(d, "The warehouse charges by the crate",
           "0.5 gold per unit held per turn. Flat - not a percentage of what it is worth.")

    # two piles, same size, same rent, wildly different bite
    cases = [("800 timber",    "~20g a unit",  "16,000g", "400g", "2.5%",  BAD,
              "Hoarding bulk is ruinous."),
             ("800 gemstones", "~500g a unit", "400,000g", "400g", "0.1%", GOOD,
              "Hoarding dense wealth is cheap.")]

    y, ch = 270, 360
    for i, (what, unit, worth, rent, pct, col, verdict) in enumerate(cases):
        box = (150 + i * 830, y, 940 + i * 830, y + ch)
        panel(d, box)
        d.rectangle((box[0], y, box[2], y + 8), fill=col)
        text(d, (box[0] + 40, y + 34), what, TITLE(44), INK, clip=box)
        text(d, (box[0] + 40, y + 92), unit, BODY(28), MUTED, clip=box)

        for j, (k, v, c) in enumerate((("the pile is worth", worth, INK),
                                       ("rent per turn", rent, INK),
                                       ("of the pile, per turn", pct, col))):
            ry = y + 150 + j * 54
            text(d, (box[0] + 40, ry), k, BODY(28), MUTED, clip=box)
            text(d, (box[2] - 40, ry - 6), v, MONO(36), c, anchor="ra", clip=box)

        d.line((box[0] + 40, y + 300, box[2] - 40, y + 300), fill=EDGE, width=2)
        text(d, (box[0] + 40, y + 314), verdict, TITLE(28), col, clip=box)

    text(d, (960, 664), "Same 800 units. Same 400 gold. One of them is a business.",
         BODY(32), MUTED, anchor="ma")

    # the boon ramp - a step per threshold, each bar starting AT the units it needs
    ry = 744
    text(d, (150, ry), "Hold enough of a good and it grants a standing campaign bonus:",
         BODY(32), INK)
    text(d, (1770, ry + 6), "Iron: +4 armour, all armies", BODY(26), MUTED, anchor="ra")

    gx0, gx1, gy1, gh = 150, 1770, 962, 150
    d.line((gx0, gy1, gx1, gy1), fill=EDGE, width=2)
    # (left frac, right frac, label, bar height fraction, units at the left edge)
    bands = [(0.00, 0.14, "no boon", 0.0,  "0"),
             (0.14, 0.44, "1x",      0.34, "100 units"),
             (0.44, 0.74, "2x",      0.67, "300 units"),
             (0.74, 1.00, "3x",      1.00, "600 units")]
    for lo, hi, label, hf, units in bands:
        x0 = gx0 + (gx1 - gx0) * lo
        x1 = gx0 + (gx1 - gx0) * hi
        if hf:
            h = gh * hf
            d.rectangle((x0, gy1 - h, x1, gy1), fill=PANEL, outline=GOLD, width=2)
            text(d, ((x0 + x1) / 2, gy1 - h + 14), label, MONO(40), GOLD, anchor="ma")
        else:
            text(d, ((x0 + x1) / 2, gy1 - 40), label, BODY(24), MUTED, anchor="ma")
        text(d, (x0, gy1 + 12), units, BODY(26), MUTED,
             anchor="la" if lo == 0 else "ma")

    footer(d, "The altar is the other half: burn 30 units for the same boon at 2x, "
              "for five turns. Rent is what stops doing nothing from being free.")
    return img


# ----------------------------------------------------------------- 3: the shares

def diagram_shares():
    img, d = canvas()
    header(d, "Shares in the houses",
           "Every living Chaos Dwarf faction is an instrument. A lot is 5 shares.")

    cx = 960

    def node(y, h, title, lines, col, w=760):
        box = (cx - w // 2, y, cx + w // 2, y + h)
        panel(d, box)
        d.rectangle((box[0], y, box[2], y + 8), fill=col)
        text(d, (cx, y + 26), title, TITLE(40), col, anchor="ma", clip=box)
        for j, ln in enumerate(lines):
            text(d, (cx, y + 82 + j * 36), ln, BODY(27), MUTED, anchor="ma", clip=box)
        return box

    node(230, 160, "Buy shares",
         ["Priced on the house's power: regions held,",
          "halved again if it has lost its capital."], GOLD)
    arrow(d, cx, 390, cx, 436)

    node(444, 160, "A dividend every turn",
         ["2% of the share's own live price.",
          "It rises and falls with the house."], GOOD)

    # the war side-branch, hung off the dividend node
    d.line((cx + 380, 524, cx + 555, 524), fill=MUTED, width=3)
    arrow(d, cx + 555, 524, cx + 596, 524)
    wbox = (cx + 600, 456, 1830, 600)
    panel(d, wbox)
    d.rectangle((wbox[0], wbox[1], wbox[2], wbox[1] + 8), fill=BAD)
    text(d, (wbox[0] + 28, wbox[1] + 26), "at war with them", TITLE(30), BAD, clip=wbox)
    text(d, (wbox[0] + 28, wbox[1] + 72), "dividend suspended,", BODY(22), MUTED, clip=wbox)
    text(d, (wbox[0] + 28, wbox[1] + 100), "the position is kept", BODY(22), MUTED, clip=wbox)

    arrow(d, cx, 604, cx, 650)
    node(658, 140, "The house dies",
         ["and its paper settles, once, at what it was worth alive"], EMBER)

    # the two branches
    ly, lh = 838, 160
    for i, (who, mult, note, col) in enumerate(
            (("You took its capital", "1.25x", "the buyout. A seat claim counts.", GOOD),
             ("Somebody else did", "0.50x", "the wind-up. You backed a loser.", BAD))):
        bx0 = 260 + i * 760
        box = (bx0, ly, bx0 + 640, ly + lh)
        panel(d, box)
        d.rectangle((box[0], ly, box[2], ly + 8), fill=col)
        arrow(d, cx, 798, bx0 + 320, ly - 8, fill=col)
        text(d, (bx0 + 320, ly + 22), who, TITLE(32), INK, anchor="ma", clip=box)
        text(d, (bx0 + 320, ly + 64), mult, MONO(54), col, anchor="ma", clip=box)
        text(d, (bx0 + 320, ly + 128), note, BODY(24), MUTED, anchor="ma", clip=box)

    footer(d, "So you can back a house, or you can bury one. A house that dies during your "
              "own turn cannot be bought up first - that hole is closed.")
    return img


DIAGRAMS = [("zharr_01_price_ladder.png", diagram_ladder),
            ("zharr_02_warehouse.png",    diagram_warehouse),
            ("zharr_03_shares.png",       diagram_shares)]


def selftest():
    """A generated diagram fails two silent ways: a label clipped out of its box, or two
    labels drawn on top of each other. Neither raises. Both are checked here."""
    bad = []
    for name, fn in DIAGRAMS:
        _DRAWN.clear()
        fn()
        assert _DRAWN, name + " drew no text at all"
        for s, (x0, y0, x1, y1), (c0, c1, c2, c3) in _DRAWN:
            if x0 < c0 or y0 < c1 or x1 > c2 or y1 > c3:
                bad.append(f"{name}: {s!r} ink ({x0},{y0})-({x1},{y1}) "
                           f"escapes ({c0},{c1})-({c2},{c3})")
        runs = [(t, b) for t, b, _ in _DRAWN]
        for i in range(len(runs)):
            for j in range(i + 1, len(runs)):
                (s1, a), (s2, b) = runs[i], runs[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    bad.append(f"{name}: {s1!r} {a} overlaps {s2!r} {b}")
    if bad:
        print("\n".join(bad))
        print(f"FAIL - {len(bad)} layout fault(s)")
        return 1
    print(f"ok - {len(DIAGRAMS)} diagrams, no clipped or overlapping labels")
    return 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in DIAGRAMS:
        _DRAWN.clear()
        fn().save(OUT / name)
        print(f"{OUT / name}  {W}x{H}")
    return selftest()


if __name__ == "__main__":
    sys.exit(main())
