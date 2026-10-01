# -*- coding: utf-8 -*-
"""Render the Great Guilds panel to a PNG with the game shut, and validate its XML.

WHY THIS EXISTS. Every UI bug this mod has shipped was a SILENT one - a GUID with no
hierarchy node, a component with no image, a clickable thing that was not interactive, a
list that drew and would not scroll - and the only way to see any of them was to start a
campaign and look. That is a slow loop, and the last one shipped because the contract was
checked and the picture never was.

TWO INDEPENDENT THINGS HAPPEN HERE:

  1. VALIDATE. TWUI Studio's own document reader links <hierarchy> to <components> the way
     the engine does and reports every mismatch - a reader written by another modder from
     CA's files, with no knowledge of our generator. An independent second opinion on the
     GUID discipline that gen_guilds_ui.py enforces from the inside.

  2. DRAW. Its rasteriser decodes and nine-slice scales CA's art the way the game does, so
     the panel can be looked at without launching anything.

WHY IT DOES NOT JUST OPEN THE FILE IN TWUI STUDIO. Our .twui.xml files carry NO offsets.
The engine ignores them on a runtime-created component, so zzz_derpy_guilds_ui.lua MoveTo's
every piece instead - meaning a faithful preview of the file alone draws the whole panel
stacked in one corner. The coordinates live in gen_guilds_ui.py, and this reads them from
there. It also honours the per-tab visibility the Lua applies, because a preview that draws
every declared component is a preview of the FILE and not of the TAB.

WHAT IT IS NOT. Text is PIL's own font, not the game's, so glyph widths and wrapping are
approximate and this cannot answer a "does that label fit" question - gen_great_guilds.py's
help-fit check and the game itself own that. Everything positional is exact. It does not
run Lua, so it draws a plausible set of contents, not your save's.

    py tools/preview_guilds_panel.py            # render to .skilltree_cache/ui_preview/:
                                                #   gg_standings, gg_guilds, gg_log, gg_pick
    py tools/preview_guilds_panel.py slavers    # ... with that guild's baked ground
    py tools/preview_guilds_panel.py --check    # validate the XML only, no PNG
    py tools/preview_guilds_panel.py --selftest

Imports TWUI_Studio/pyc (the installed build's modules, tools/extract_twui_studio.py) when
present, else the vendored 0.22.2 source in TWUI_Studio/src. Non-commercial licence, see
TWUI_Studio/LICENSE.txt.
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# pyc/ is the installed exe's own modules (tools/extract_twui_studio.py); src/ is the 0.22.2
# source, the last one published, and the fallback wherever pyc/ was never extracted.
STUDIO_PYC = os.path.join(ROOT, "TWUI_Studio", "pyc")
STUDIO = STUDIO_PYC if os.path.isdir(STUDIO_PYC) else os.path.join(ROOT, "TWUI_Studio", "src")
OURS = os.path.join(ROOT, "Modding Files", "pack", "ui", "campaign ui")
CACHE = os.path.join(ROOT, ".skilltree_cache", "ui_preview")
UI = os.path.join(CACHE, "ui")
GAME = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III\data"
PACKS = ("ui.pack", "ui2.pack", "ui3.pack")


def _studio():
    """Import TWUI Studio's model and renderer. It reads its catalogs from its own cwd."""
    if not os.path.isdir(STUDIO):
        raise SystemExit("TWUI_Studio/src is not present - vendor the 0.22.2 source there")
    if STUDIO == STUDIO_PYC:
        ver = [open(os.path.join(d, "VERSION.txt")).read().strip() for d in (STUDIO, os.path.dirname(STUDIO))]
        if ver[0] != ver[1]:
            raise SystemExit("TWUI_Studio/pyc is %s but the exe is %s - re-run tools/extract_twui_studio.py"
                             % tuple(ver))
    here = os.getcwd()
    sys.path.insert(0, STUDIO)
    os.chdir(STUDIO)
    try:
        import model
        import rendering
    finally:
        os.chdir(here)
    return model, rendering


def _gen():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gen_guilds_ui", os.path.join(ROOT, "tools", "gen_guilds_ui.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("gen_guilds_ui", mod)
    spec.loader.exec_module(mod)
    return mod


# WHICH PANEL. The three reusable halves below - the file list, the validator and
# the art extractor - are about a PREFIX and not about the guilds, so the Iron
# Court's preview imports them rather than owning a second copy that can drift.
GG = "derpy_gg_"


def our_files(prefix=GG):
    return sorted(f for f in os.listdir(OURS)
                  if f.startswith(prefix) and f.endswith(".twui.xml"))


def validate(prefix=GG):
    """Every hierarchy node must resolve to exactly one component definition.

    A GUID in <components> with no <hierarchy> node is a silent non-draw, and the reverse is
    a node the engine cannot build. gen_guilds_ui.py checks this from inside the generator;
    this checks the FILES, with a reader that has never heard of the generator.
    """
    model, _r = _studio()
    out = []
    for name in our_files(prefix):
        src = io.open(os.path.join(OURS, name), encoding="utf-8").read()
        try:
            doc = model.Document(src)
        except Exception as exc:                                   # noqa: BLE001
            out.append("%s: TWUI Studio cannot parse it: %r" % (name, exc))
            continue
        for i in getattr(doc, "issues", []):
            tags = ", ".join(sorted({n.tag for n in i.nodes})) or "-"
            out.append("%s: [%s] %s (%s) %s" % (name, i.severity, i.code, tags, i.message))
        for keys, what in ((getattr(doc, "unsafe_keys", ()), "duplicate guid"),
                           (getattr(doc, "missing_keys", ()), "missing definition"),
                           (getattr(doc, "unlinked_keys", ()), "unlinked node")):
            for k in sorted(keys):
                tag = doc.by_guid[k].tag if k in doc.by_guid else k
                out.append("%s: %s on %s" % (name, what, tag))
    return out


def extract_art(prefix=GG, extra=(), optional=()):
    """Pull only the art our files reference out of CA's packs, once, into the cache.

    TWUI Studio wants an extracted top-level `ui` folder and will not read .pack files. The
    whole library is over 40,000 assets; this panel touches eighteen. CA's ui png is zstd
    behind a u32 length prefix - the wrapper tools/read_vanilla_loc.py already strips.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from read_pack_index import paths, read
    from read_vanilla_loc import _decompress

    want = set(extra)
    for f in our_files(prefix):
        t = io.open(os.path.join(OURS, f), encoding="utf-8").read()
        want |= set(re.findall(r'imagepath="([^"]+)"', t))
    # A CULTURE SKIN'S COPY of a generic file is what the game draws for that race - the
    # title plate is ui/skins/default/panel_title.png in the file and the reader's own
    # culture's plate on screen. Fetched where CA ships one; absence is not a fault.
    optional = set(optional) - want
    want |= optional

    def dest(p):
        return os.path.join(UI, os.path.relpath(p, "ui").replace("/", os.sep))

    todo = [p for p in sorted(want) if not os.path.isfile(dest(p))]
    if not todo:
        return len(want), []

    local = os.path.join(ROOT, "Modding Files", "pack")
    missing, still = [], []
    for p in todo:
        src = os.path.join(local, p.replace("/", os.sep))
        if os.path.isfile(src):                      # this mod's own art
            os.makedirs(os.path.dirname(dest(p)), exist_ok=True)
            io.open(dest(p), "wb").write(io.open(src, "rb").read())
        else:
            still.append(p)

    if still:
        index = {}
        for pk in PACKS:
            fp = os.path.join(GAME, pk)
            if os.path.isfile(fp):
                for e in paths(fp):
                    index.setdefault(e, pk)
        for p in still:
            pk = index.get(p)
            if not pk:
                if p not in optional:
                    missing.append(p)
                continue
            data = b""
            for _path, comp, blob in read(os.path.join(GAME, pk), p):
                data = _decompress(blob) if comp else blob
            if not data or data[:4] != b"\x89PNG":
                missing.append(p)
                continue
            os.makedirs(os.path.dirname(dest(p)), exist_ok=True)
            io.open(dest(p), "wb").write(data)
    return len(want - optional), missing


# EVERY LINE OF TEXT UNDER 4.5:1, across every picture this run draws. A race's frame is
# CA art chosen by eye, and a plate a shade too bright is text nobody can read.
LOW = []


def skin_path(p, culture):
    """The culture skin's copy of a generic ui/skins/default/X.png, as the game swaps it."""
    if culture and p.startswith("ui/skins/default/") and p.count("/") == 3:
        return "ui/skins/%s/%s" % (culture, p.rsplit("/", 1)[-1])
    return None


DEMO_FACTIONS = ("You", "Uzkul Mingol Company", "Slaves of the Black Dwarf",
                 "Labourfleet of Uzkulak", "Disciples of Hashut",
                 "The Legion of Azgorh", "Sentinels of Zharr", "Drazhoath's Host")

# CA'S OWN COLOURS for the three [[col:]] names this panel writes, read out of
# db/ui_colours_tables - the table the tag resolves against - and not picked by eye.
# selftest() re-reads the cached table when it is there.
INK = {"red": (0xFF, 0x2D, 0x2D, 255), "yellow": (0xFF, 0xB9, 0x00, 255),
       "green": (0xA0, 0xFF, 0x37, 255)}
PALE, GOLD = (235, 225, 200, 255), (255, 211, 122, 255)
DIM = (0xC9, 0xBF, 0xA8, 255)          # the card descriptions' and help lines' colour
MARKUP = re.compile(r"\[\[(/?)col(?::([^\]]*))?\]\]")

# GGUI.TAB numbers the tabs by age; the strip draws them in this order.
TAB_LABELS = ("Guilds", "Leaderboard", "Bounties", "Court", "Log", "Help")
TAB_SLOT = {1: 0, 2: 1, 3: 2, 4: 3, 5: 5, 6: 4}


def _shown(name, tab):
    """Whether GGUI.refresh leaves a panel part visible on this tab (GGUI.TAB numbering)."""
    if name.startswith(("gg_help_", "gg_card_")):
        return False              # text only, or drawn from the card's own file
    if name in ("gg_prev", "gg_next"):
        return tab in (1, 4, 5, 6)
    if name in ("gg_bar_track", "gg_rep_bar"):
        return tab == 1
    if name.startswith("gg_gtab_") or name in ("gg_gsel", "gg_gbar"):
        return tab in (1, 4)
    if name.startswith("gg_lf_"):
        return tab == 6
    return True


def _setup(guild=None, tag="", size=None):
    """A canvas, and the means to paste any part of our four files onto it."""
    from PIL import Image, ImageDraw, ImageFont
    from pathlib import Path
    from types import SimpleNamespace
    model, rendering = _studio()
    G = _gen()
    # Plus what the Lua paints that no file names: the open tab's plates and the lit
    # card's glows, for every race's frame.
    swapped = []
    for t in [""] + G.FRAME_TAGS:
        f = G.frame(t)
        swapped += [f["heat"][0], f["rim"][0]] + list(f["tab"]["selected"]) \
            + list(f["tab"]["selected_hover"])
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import gen_great_guilds as GEN
    culture = GEN.FLAVOURS[tag]["culture"]
    skinned = set()
    for f in our_files():
        t = io.open(os.path.join(OURS, f), encoding="utf-8").read()
        for p in re.findall(r'imagepath="([^"]+)"', t):
            if skin_path(p, culture):
                skinned.add(skin_path(p, culture))
    n_art, missing = extract_art(extra=swapped, optional=sorted(skinned))
    ground = None
    if guild:
        ground = Path(os.path.join(OURS, "derpy_gg_bg", guild + tag + ".png"))
        if not ground.is_file():
            raise SystemExit("no baked ground for %r: %s (py tools/"
                             "make_guild_backgrounds.py writes them)" % (guild, ground))
    docs, named = {}, {}
    for kind in ("panel", "row", "list", "card"):
        # The race's own panel and card, as GGUI.frame_path creates them.
        fname = G.frame_file("derpy_gg_" + kind, tag) if kind in ("panel", "card") \
            else "derpy_gg_%s.twui.xml" % kind
        d = model.Document(io.open(os.path.join(OURS, fname), encoding="utf-8").read())
        docs[kind] = d
        for c in d.components:
            named[(kind, c.get("id", c.tag))] = c
    canvas = Image.new("RGBA", size or (G.PANEL_W, G.PANEL_H), (0, 0, 0, 255))

    def paste(kind, name, x, y, w=None, h=None, swap=None, crop=None, by_index=None):
        """`swap` maps an imagepath to the one the Lua puts there with SetImagePath.

        `crop` keeps only the left `crop` pixels of each layer - the reputation fill, which
        the Lua narrows at runtime to the fraction earned. `by_index` maps an image INDEX
        to a path, which is how SetImagePath addresses it - the lit card's two glows ship
        as the same blank, so a path swap cannot tell them apart."""
        doc, comp = docs[kind], named.get((kind, name))
        if comp is None:
            return
        images = {}
        box = comp.child("componentimages")
        if box is not None:
            for n in box.children:
                if n.get("this"):
                    images[n.get("this")] = n.get("imagepath")
        st = doc.state(comp)
        metrics = st.child("imagemetrics") if st is not None else None
        if metrics is None:
            return
        for idx, n in enumerate(metrics.children):
            p = images.get(n.get("componentimage"))
            if not p:
                continue
            p = (swap or {}).get(p, p)
            p = (by_index or {}).get(idx, p)
            asset = Path(os.path.join(UI, os.path.relpath(p, "ui").replace("/", os.sep)))
            if ground is not None and p == G.PANEL_ART:
                asset = ground
            # OUR OWN ART is not in CA's packs, so it is read where it is staged, in the
            # flavour asked for - the Lua appends the same tag at runtime (GGUI.art). A
            # race's own file already names its flavoured ground, so that is not tagged twice.
            if p.startswith("ui/campaign ui/derpy_gg_"):
                stem, ext = os.path.splitext(os.path.relpath(p, "ui/campaign ui"))
                if not (tag and stem.endswith(tag)):
                    stem += tag
                asset = Path(os.path.join(OURS, stem + ext))
            elif skin_path(p, culture):
                alt = Path(os.path.join(UI, os.path.relpath(skin_path(p, culture), "ui")
                                        .replace("/", os.sep)))
                if alt.is_file():
                    asset = alt
            if not asset.is_file():
                continue
            iw = int(model.number(n.get("width"), w or 0)) or (w or 1)
            ih = int(model.number(n.get("height"), h or 0)) or (h or 1)
            ox, oy = model.pair(n.get("offset"), (0, 0))
            img = rendering.raster(asset, iw, ih, n)
            # TWUI Studio's raster ignores both flips; the engine draws them.
            if n.get("x_flipped") == "true":
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            if n.get("y_flipped") == "true":
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
            if crop is not None:
                if crop <= 0:
                    continue
                img = img.crop((0, 0, min(crop, img.width), img.height))
            canvas.alpha_composite(img, (int(x + ox), int(y + oy)))

    def icon(guild_key, x, y, w, h):
        """The glyph the Lua paints per guild with SetImagePath."""
        f = os.path.join(OURS, "derpy_gg_icons", guild_key + tag + ".png")
        if os.path.isfile(f):
            canvas.alpha_composite(Image.open(f).convert("RGBA").resize((w, h)), (x, y))

    draw = ImageDraw.Draw(canvas)
    fonts = {}

    def font(size):
        if size not in fonts:
            fonts[size] = ImageFont.load_default(size=size)
        return fonts[size]

    def ink(x, y, text, size=12, base=PALE):
        """A string with its [[col:]] markup honoured, left-aligned at x."""
        f, pos, colour = font(size), 0, base
        for m in MARKUP.finditer(text):
            seg = text[pos:m.start()]
            draw.text((x, y), seg, fill=colour, font=f)
            x += draw.textlength(seg, font=f)
            colour = base if m.group(1) else INK.get(m.group(2), base)
            pos = m.end()
        draw.text((x, y), text[pos:], fill=colour, font=f)

    def width(text, size=12):
        return draw.textlength(MARKUP.sub("", text), font=font(size))

    low = LOW

    def contrast(x, y, text, size, base):
        """Record a line whose ink is under 4.5:1 against what it is drawn on.

        Measured on the canvas as composed so far, against the brightest tenth - text is
        read against the bright end, not the average - and in WINDOWS one glyph wide, at
        half-glyph steps, reporting the worst. Over the whole line at once, a thing that
        crosses only a few letters is outvoted by the dark band everywhere else: a post
        through the first letter, an end cap on the first word, a flare under the first
        half of a card's text and a rail through every letter all measured clean.
        """
        w = int(width(text, size))
        if w <= 0:
            return
        box = canvas.crop((int(x), int(y), int(x) + w, int(y) + size)).convert("RGB")
        bw, bh = box.size

        def lum(rgb):
            c = [v / 255.0 for v in rgb]
            c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        data = list(box.get_flattened_data()) if hasattr(
            box, "get_flattened_data") else list(box.getdata())
        cols = [[lum(data[r * bw + c]) for r in range(bh)] for c in range(bw)]
        win = max(1, min(size, bw))
        worst, at = None, 0
        for c0 in range(0, bw - win + 1, max(1, win // 2)):
            ls = sorted(v for col in cols[c0:c0 + win] for v in col)
            bg = ls[int(len(ls) * 0.9)]
            ratio = (lum(base[:3]) + 0.05) / (bg + 0.05)
            if worst is None or ratio < worst:
                worst, at = ratio, c0
        if worst < 4.5:
            low.append("%.1f:1 at +%dpx  %s" % (worst, at, MARKUP.sub("", text)[:48]))

    def cell(box, text, size=12, align="left", base=PALE):
        """Text in a layout box the way its component_text sits: 6px in, or centred."""
        x, y, w, h = box
        ty = y + (h - size) / 2 - 1
        tx = x + (w - width(text, size)) / 2 if align == "center" else x + 6
        contrast(tx, ty, text, size, base)
        ink(tx, ty, text, size, base)

    loc = dict((r["key"], r["text"]) for r in GEN.build()["loc"])

    def L(key):
        """This mod's own words, out of the rows gen_great_guilds.py ships."""
        return loc.get("derpy_gg_" + key + tag, loc.get("derpy_gg_" + key, key))

    return SimpleNamespace(G=G, GEN=GEN, F=GEN.FLAVOURS[tag], FR=G.frame(tag), tag=tag,
                           canvas=canvas, draw=draw, paste=paste, icon=icon, ink=ink,
                           width=width, cell=cell, font=font, L=L, n_art=n_art,
                           missing=missing, low=low, contrast=contrast)


def _frame(P, tab, guild="brass"):
    """The ground, every panel part this tab shows, the title and the tab strip."""
    G = P.G
    P.paste("panel", "derpy_gg_panel", 0, 0, G.PANEL_W, G.PANEL_H)
    open_tab = G.TABS[TAB_SLOT[tab]]
    for name, (x, y, w, h) in sorted(G.PANEL_LAYOUT.items()):
        # The bar is narrowed to the fraction earned and the marker moved to the page,
        # both at runtime; their callers draw them.
        if _shown(name, tab) and name not in ("gg_rep_bar", "gg_gsel"):
            swap = None
            # What the Lua repaints: the open tab's plate, and the header's glyph.
            by_index = None
            if name == open_tab:
                by_index = dict(enumerate(P.FR["tab"]["selected"]))
            elif name == "gg_rank_mark":
                swap = {G.RANK_ICON_LAYERS[-1]["path"]:
                        "ui/campaign ui/derpy_gg_icons/%s.png" % guild}
            P.paste("panel", name, x, y, w, h, swap=swap, by_index=by_index)
    # Centred in gg_title's own box at its own size, read off the generator.
    tx, ty, tw, th = G.PANEL_LAYOUT["gg_title"]
    title = "The Great Guilds"
    P.draw.text((tx + (tw - P.draw.textlength(title, font=P.font(24))) / 2,
                 ty + (th - 24) / 2), title, fill=PALE, font=P.font(24))
    # Pitch read off the generator's own TABS, so a re-pitched strip draws where it is.
    for i, lbl in enumerate(TAB_LABELS):
        # The open tab's caption is [[col:yellow]] (GGUI.refresh); the rest are pale.
        ink = INK["yellow"] if i == TAB_SLOT[tab] else PALE
        # CENTRED, as BTN_TEXT writes the tab's component_text. A fixed 40px inset put
        # "Leaderboard" 30px right of where the game draws it, onto the plate's right rim,
        # and the contrast check then measured a rim the caption never touches.
        cx = G.PANEL_LAYOUT[G.TABS[i]][0] + (G.TAB_W - P.width(lbl, 12)) / 2
        P.contrast(cx, 68, lbl, 12, ink)
        P.draw.text((cx, 68), lbl, fill=ink, font=P.font(12))
    if _shown("gg_prev", tab):
        P.cell(G.PANEL_LAYOUT["gg_prev"], P.L("prev"), 14, "center")
        P.cell(G.PANEL_LAYOUT["gg_next"], P.L("next"), 14, "center")


def rank_box(G, tag=""):
    """gg_rank_line as its text sits: the frame's text x in from the left (cell() adds 6 of
    it), and lifted by its bottom padding onto the header bar's dark band."""
    x, y, w, h = G.PANEL_LAYOUT["gg_rank_line"]
    f = G.frame(tag)
    tx = float(f["rank_tx"].split(",")[0]) - 6
    pad = float(f["rank_ty"].split(",")[1])
    return (x + tx, y, w - tx, h - pad)


def _save(P, name, path=None):
    out = path or os.path.join(CACHE, name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    P.canvas.convert("RGB").save(out)
    return out


def render(path=None, guild=None, tag=""):
    """The Leaderboard. `guild` swaps the ground for that guild's baked background.

    THE GROUND IS NOT IN THE .twui.xml. The file names CA's tier_01 background and the
    campaign Lua replaces image index 1 at runtime as the player pages from guild to
    guild, so a preview that only reads the file draws the one ground nobody with the
    mod installed ever sees.
    """
    from PIL import Image, ImageDraw
    P = _setup(guild, tag)
    G, GEN, draw = P.G, P.GEN, P.draw
    _frame(P, 2, guild or "brass")
    P.cell(rank_box(G, P.tag), "The Leaderboard   Rivals last turn: 0 services bought, 0 demands "
                        "paid, 0 patrons afield")

    low = GEN.FLAVOURS[tag]["ranks"][0]          # the flavour's own lowest rank
    RL = G.ROW_LAYOUT
    for i, key in enumerate(GEN.GUILDS):
        g = GEN.FLAVOURS[tag]["guilds"][key]
        ry = 170 + i * 44
        P.paste("row", "derpy_gg_row", 20, ry, G.ROW_W, G.ROW_H)
        ix, iy, iw, ih = RL["row_icon"]
        P.icon(key, 20 + ix, ry + iy, iw, ih)
        sel = (i == 0)
        lx0 = 20 + RL["row_leader"][0]
        for name, s in (("row_guild", g),
                        ("row_rank", "You: %s (%d)  %d/8"
                         % (low, 9 if sel else 0, 1 if sel else 5)),
                        ("row_leader", "Leader:" if sel else "Leader: Nobody")):
            draw.text((20 + RL[name][0], ry + 14), s,
                      fill=GOLD if sel and name == "row_guild" else PALE)
        if sel:
            # Your flag after "Leader:", a 24px square as the inline [[img:]] draws it.
            fx = lx0 + draw.textlength("Leader: ") + 4
            draw.rectangle([fx, ry + 8, fx + 24, ry + 32], outline=(120, 100, 70, 255))

    lx, ly = G.LIST_XY
    cx, cy, cw, ch = G.LIST_LAYOUT["list_clip"]
    vx, vy, vw, vh = G.LIST_LAYOUT["vslider"]
    P.paste("list", "vslider", lx + vx, ly + vy, vw, vh)
    P.paste("list", "handle", lx + vx, ly + vy, G.SLIDER_W, G.HANDLE_H)

    clip = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    cd = ImageDraw.Draw(clip)
    for i, f in enumerate(DEMO_FACTIONS):
        ry = i * G.FROW_H
        if ry >= ch:
            break
        cd.rectangle([2, ry + 2, 22, ry + 22], outline=(120, 100, 70, 255))
        cd.text((28, ry + 6), "%d.  %s   %d   %s" % (i + 1, f, 9 if i == 0 else 0, low),
                fill=GOLD if i == 0 else PALE)
    P.canvas.alpha_composite(clip, (lx + cx, ly + cy))
    draw.rectangle([lx + cx, ly + cy, lx + cx + cw, ly + cy + ch], outline=(90, 80, 60, 255))
    draw.text((24, 646), "Favour: 9", fill=PALE)

    out = _save(P, "gg_standings%s%s.png" % (guild and "_" + guild or "", tag), path)
    return out, P.n_art, P.missing, (ch // G.FROW_H, len(DEMO_FACTIONS))


def _wrap(P, text, box_w, size=12, max_lines=2):
    """GGUI.wrap's rule, against PIL's font: by words, and " ..." marks a cut."""
    lines, cur = [], None
    for word in text.split():
        t = word if cur is None else cur + " " + word
        if cur is not None and P.width(t, size) > box_w:
            lines.append(cur)
            if len(lines) >= max_lines:
                lines[-1] = cur + " ..."
                return lines
            cur = word
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def _card(P, x, y, guild_key, name, desc, cost, button, lit=False):
    """One card the way GGUI.fill_card writes it: plate, glyph and six cells. `lit` is a
    running service, lit the way GGUI.light_card lights it."""
    G = P.G
    CL = G.CARD_LAYOUT
    glow = {G.CARD_HEAT_INDEX: P.FR["heat"][0], G.CARD_RIM_INDEX: P.FR["rim"][0]} \
        if lit else None
    P.paste("card", "derpy_gg_card", x, y, G.CARD_W, G.CARD_H, by_index=glow)

    def at(n):
        cx, cy, cw, ch = CL[n]
        return (x + cx, y + cy, cw, ch)
    # The holder, and the guild's glyph where the Lua paints it (GGUI.CARD_ICON_INDEX).
    P.paste("card", "card_icon", *at("card_icon"),
            swap={G.CARD_ICON_LAYERS[G.CARD_ICON]["path"]:
                  "ui/campaign ui/derpy_gg_icons/%s.png" % guild_key})
    if cost:
        P.paste("card", "card_cost", *at("card_cost"))
    if button:
        P.paste("card", "card_buy", *at("card_buy"))
        P.cell(at("card_buy"), button, 12, "center")
    P.cell(at("card_name"), name, 14)
    for i, line in enumerate(desc[:2]):
        P.cell(at("card_desc_%d" % (i + 1)), line, 12, base=DIM)
    P.cell(at("card_cost"), cost, 14, "center")


def render_guilds(path=None, tag="", guild="khanate", rep=340, favour=240):
    """The Guilds tab, with the three states of a service card that has a live button:
    waiting on a map target (Select), asking before a big spend (Confirm), and locked by
    rank. The six guild buttons and the page marker run along the bottom.
    """
    P = _setup(guild, tag)
    G, GEN, F, L = P.G, P.GEN, P.F, P.L
    _frame(P, 1, guild)
    order = list(GEN.GUILDS)                     # GGUI.GUILD_ORDER is the same six
    page = order.index(guild) + 1

    thr = GEN.RANK_THRESHOLDS
    rank = max(i for i in range(len(thr)) if rep >= thr[i])
    nxt = thr[min(rank + 1, len(thr) - 1)]
    P.cell(rank_box(G, P.tag), "%s   %s   %s %d / %d" % (
        F["guilds"][guild], F["ranks"][rank], L("reputation"), rep, nxt))
    # NARROWED AT RUNTIME to the fraction earned (the Lua resizes it), so it is drawn
    # here cropped to that fraction: its image metric would draw it at full width.
    bx, by, bw, bh = G.PANEL_LAYOUT["gg_rep_bar"]
    P.paste("panel", "gg_rep_bar", bx, by, bw, bh, crop=int(bw * rep / nxt))

    mine = [s for s in GEN.SERVICES if s["guild"] == guild]
    for i, s in enumerate(mine[:3]):
        cx, cy = G.PANEL_LAYOUT["gg_card_%d" % (i + 1)][:2]
        name = F["services"][s["key"]]
        # The middle card is a service IN EFFECT - bought, still running, on cooldown - and
        # lit the way GGUI.light_card lights it. Knife in the Dark on the Khanate's page.
        state = ("pick", "running", "rank")[i]
        if state == "pick":
            name += "  [[col:red]]" + L("needs_target_short") + "[[/col]]"
            button = L("pick_button")
        elif state == "running":
            name += "  7t"
            button = L("buy")
        else:
            name += ("  [[col:red]]" + L("needs") + " " + F["ranks"][s["rank"] - 1]
                     + "[[/col]]")
            button = "[[col:red]]" + L("buy") + "[[/col]]"
        # What the card reads: GGUI.loc_service_desc, up to its first "||".
        blurb = L("service_desc_" + s["key"]).split("||")[0]
        desc_w = G.CARD_LAYOUT["card_desc_1"][2] - 6
        _card(P, cx, cy, guild, name, _wrap(P, blurb, desc_w), str(s["cost"]), button,
              lit=(state == "running"))

    P.cell(G.PANEL_LAYOUT["gg_earned"], "%s +14 (%s 8, %s 6)   %s +9" % (
        L("earned_now"), L("src_missions"), L("src_bounties"), L("earned_last")))
    # The six buttons: the glyph, and the badge's gold count where something is ready.
    ready = {"brass": 2, "khanate": 1}
    for i, g in enumerate(order):
        x, y, w, h = G.PANEL_LAYOUT["gg_gtab_%d" % (i + 1)]
        P.paste("panel", "gg_gtab_%d" % (i + 1), x, y, w, h,
                swap={G.GTAB_ICON_PATH: "ui/campaign ui/derpy_gg_icons/%s.png" % g})
        if ready.get(g):
            n = str(ready[g])
            # tx -2, ty -1, right and bottom: the component_text the generator writes.
            P.draw.text((x + w - 2 - P.width(n), y + h - 14), n, fill=GOLD, font=P.font(12))
    gx = G.PANEL_LAYOUT["gg_gtab_%d" % page][0]
    _sx, sy, sw, sh = G.PANEL_LAYOUT["gg_gsel"]
    P.paste("panel", "gg_gsel", gx, sy, sw, sh)
    P.cell(G.PANEL_LAYOUT["gg_footer"], "%s: %d" % (L("favour"), favour))
    return _save(P, "gg_guilds%s.png" % tag, path)


def render_log(path=None, tag="", guild="brass"):
    """The Log tab with its four filters, All active, over a page of mixed entries."""
    P = _setup(guild, tag)
    G, F, L = P.G, P.F, P.L
    _frame(P, 6, guild)
    P.cell(rank_box(G, P.tag), "%s   1 %s 3" % (L("hdr_log"), L("help_of")))
    for f in ("all", "mine", "rivals", "ranks"):
        lbl = L("lf_" + f)
        if f == "all":
            lbl = "[[col:yellow]]" + lbl + "[[/col]]"
        P.cell(G.PANEL_LAYOUT["gg_lf_" + f], lbl, 12, "center")
    gn, sv, rk = F["guilds"], F["services"], F["ranks"]
    rival = DEMO_FACTIONS[1]
    entries = [
        (30, "brass", "%s %s (50 %s)" % (L("log_bought"), sv["caravan_levy"],
                                         L("favour").lower()), False),
        (30, "khanate", "%s %s %s" % (rival, L("log_ai_bought"), sv["knife_in_dark"]),
         False),
        (29, "khanate", "%s %s %s" % (sv["khans_price"], L("log_hit"), rival), True),
        (28, "immortals", "%s %s" % (L("log_rose"), rk[2]), False),
        (27, "brass", "%s %s %s" % (L("log_lead_won"), L("log_from"), rival), False),
        (26, "slavers", "%s %s" % (L("log_lead_lost"), rival), True),
        (25, "overseers", "%s %s" % (L("log_fell"), rk[1]), True),
        (24, "daemonsmiths", "%s %s %s" % (rival, L("log_ai_bought"),
                                           sv["bound_blueprint"]), False),
    ]
    slot = 0
    for turn, g, body, bad in entries:
        text = "%s %d   %s:  %s." % (L("log_turn"), turn, gn[g], body)
        for j, line in enumerate(_wrap(P, text, G.PANEL_LAYOUT["gg_help_01"][2] - 6,
                                       12, 3)):
            if slot >= G.HELP_SLOTS:
                break
            line = ("     " if j else "") + line
            if bad:
                line = "[[col:red]]" + line + "[[/col]]"
            P.cell(G.PANEL_LAYOUT["gg_help_%02d" % (slot + 1)], line, 12, base=DIM)
            slot += 1
    P.cell(G.PANEL_LAYOUT["gg_footer"], "%s: 240" % L("favour"))
    return _save(P, "gg_log%s.png" % tag, path)


def render_pick(path=None, tag="", service="raise_ziggurat"):
    """The card a pick puts at the top of the screen, over a stand-in for the map.

    Drawn with the LONGEST instruction any pick shows - a building service's - because a
    picture of the easy case answers nothing. GGUI.start_pick wraps it across the card's
    two lines, and the Escape note goes in the tooltip.
    """
    G = _gen()
    P = _setup(None, tag, size=(G.CARD_W + 40, G.CARD_H + 40))
    P.canvas.paste((46, 54, 40, 255), (0, 0, G.CARD_W + 40, G.CARD_H + 40))
    GEN, F, L = P.GEN, P.F, P.L
    s = [x for x in GEN.SERVICES if x["key"] == service][0]
    # GGUI.target_hint's rule.
    hint = {"unit": "needs_army", "shroud": "needs_region_any",
            "building": "needs_region_own"}.get(s.get("kind"), "needs_target")
    if s.get("hostile"):
        hint = "needs_target"
    lines = _wrap(P, L(hint), G.CARD_LAYOUT["card_desc_1"][2] - 6)
    _card(P, 20, 20, s["guild"], F["services"][service], lines, "", L("cancel"))
    return _save(P, "gg_pick%s.png" % tag, path), lines


def render_bounties(path=None, tag=""):
    """The Bounties tab with the three card shapes v2 added, each at its hardest: a
    new-war capture naming the longest demo faction, a building request the player is
    short of favour for (red Take), and a taken sabotage counting up (1/2).

    Returns the path and every card line wider than its cell, so "does it fit" is a
    measured answer and not a look at the picture.
    """
    P = _setup("brass", tag)
    G, GEN, L = P.G, P.GEN, P.L
    _frame(P, 3, "brass")
    enemy = max(DEMO_FACTIONS, key=len)
    band, pays, rep = L("bounty_routine"), L("bounty_pays"), L("reputation")

    def pay(gold, reps, left=None, taken=False):
        s = "%s   %s %dg   %d %s" % (band, pays, gold, reps, rep)
        if taken:
            return "[[col:yellow]]" + L("bounty_taken") + "[[/col]]   " + s
        return s + "   %d %s" % (left, L("bounty_turns"))
    stake_short = L("bounty_stake_short").replace("%n", "60").replace("%m", "40")
    cards = [
        ("brass", GEN.BOUNTIES["brass"][1],
         ["Karak Azgal  [[col:red]]%s %s[[/col]]" % (L("bounty_war"), enemy),
          pay(6000, 450, 5)], "20", L("take")),
        ("brass", GEN.BOUNTY_TEXT["job_build"][0],
         ["%s: %s" % (L("bounty_obj_build"), "Gunnery School"), pay(2500, 180, 4)],
         "60", "[[col:red]]" + L("take") + "[[/col]]"),
        ("daemonsmiths", GEN.BOUNTY_TEXT["hero_sabotage"][0],
         ["%s: Karak Azgal  (%s)  (1/2)" % (L("bounty_obj_sabotage"), enemy),
          pay(1200, 90, taken=True)], "", ""),
    ]
    over = []
    for i, (g, name, desc, cost, button) in enumerate(cards):
        cx, cy = G.PANEL_LAYOUT["gg_card_%d" % (i + 1)][:2]
        _card(P, cx, cy, g, name, desc, cost, button)
        for n, line in enumerate(desc):
            w = P.width(re.sub(r"\[\[/?col[^\]]*\]\]", "", line), 12)
            if w > G.CARD_LAYOUT["card_desc_%d" % (n + 1)][2] - 6:
                over.append("card %d line %d is %dpx: %s" % (i + 1, n + 1, w, line))
    P.cell(G.PANEL_LAYOUT["gg_footer"], "%s: 40   (%s)" % (L("favour"), stake_short))
    return _save(P, "gg_bounties%s.png" % tag, path), over


def selftest():
    model, rendering = _studio()
    G = _gen()

    # The reader must actually read ours - a parse that silently returns nothing would make
    # validate() pass on anything.
    doc = model.Document(io.open(os.path.join(OURS, "derpy_gg_list.twui.xml"),
                                 encoding="utf-8").read())
    assert len(doc.components) >= 5, "the list file has a container, clip, box, slider, handle"
    names = {c.get("id", c.tag) for c in doc.components}
    for want in ("listview", "list_clip", "list_box", "vslider", "handle"):
        assert want in names, "TWUI Studio does not see %s in our list file" % want

    # And it must be capable of REPORTING a fault, or a clean run means nothing. Break the
    # link between a hierarchy node and its definition, the way a bad GUID does.
    src = io.open(os.path.join(OURS, "derpy_gg_row.twui.xml"), encoding="utf-8").read()
    broken = src.replace('this="GG21', 'this="ZZ99', 1)
    assert broken != src, "could not break a guid for the negative test"
    assert model.Document(broken).issues, (
        "TWUI Studio reported nothing on a broken GUID link, so a clean report from it "
        "proves nothing")

    assert not validate(), "our shipped files do not validate: %r" % (validate(),)

    # The generator's coordinates have to be readable from here, since they are what this
    # draws with. A rename there would otherwise silently draw a panel of the wrong shape.
    for attr in ("PANEL_W", "PANEL_H", "PANEL_LAYOUT", "LIST_XY", "LIST_LAYOUT",
                 "ROW_W", "ROW_H", "FROW_H", "SLIDER_W", "HANDLE_H"):
        assert hasattr(G, attr), "gen_guilds_ui.py no longer exposes %s" % attr
    # THE COLOURS ARE CA'S. [[col:]] resolves against db/ui_colours_tables; the cache is
    # optional (RPFM makes it and a game patch deletes it), so this is skipped without it.
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import read_vanilla_cache as _V
        rows = _V.load("ui_colours")[0]
    except (ImportError, FileNotFoundError, IndexError, ValueError):
        rows = []
    if rows:
        # The cached definition's field names are shifted against its data: the key is
        # under "blue" and the hex under "description" (see preview_iron_court.py).
        by_key = dict((r["blue"], r["description"].upper()) for r in rows)
        for name, rgba in INK.items():
            assert by_key.get(name) == "%02X%02X%02X" % rgba[:3], (
                "db/ui_colours_tables calls %s %s, not %02X%02X%02X"
                % ((name, by_key.get(name)) + tuple(rgba[:3])))

    print("selftest ok: %d files validate, the reader catches a broken link"
          % len(our_files()))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--check" in sys.argv:
        problems = validate()
        for p in problems:
            print("PROBLEM: " + p)
        print("%d file(s) checked by TWUI Studio's reader" % len(our_files()))
        sys.exit(1 if problems else 0)
    else:
        problems = validate()
        for p in problems:
            print("PROBLEM: " + p)
        args = sys.argv[1:]
        tag = ""
        if "--flavour" in args:
            at = args.index("--flavour")
            tag = "_" + args[at + 1]
            del args[at:at + 2]
        want = [a for a in args if not a.startswith("--")]
        out, n_art, missing, (shown, total) = render(guild=want[0] if want else None,
                                                     tag=tag)
        for m in missing:
            print("  art not found in any ui pack: " + m)
        print("wrote %s  (%d art files, %d of %d faction rows visible)"
              % (out, n_art, shown, total))
        print("wrote %s" % render_guilds(tag=tag))
        print("wrote %s" % render_log(tag=tag))
        bounties, over = render_bounties(tag=tag)
        print("wrote %s" % bounties)
        for o in over:
            print("  TOO WIDE: " + o)
        pick, lines = render_pick(tag=tag)
        print("wrote %s  (the instruction takes %d of the card's 2 lines%s)"
              % (pick, len(lines), ", CUT" if lines and lines[-1].endswith(" ...") else ""))
        # AFTER EVERY RENDER, not after the first. Printed after the Leaderboard alone, the
        # Guilds, Log, Bounties and picking views appended their failures to a list nobody
        # read again - the Guilds tab is where the service cards are, and a Dark Elf card's
        # text sat on a white-hot flare with nothing reported (2026-09-30).
        for m in LOW:
            print("  LOW CONTRAST " + m)
        sys.exit(1 if problems or LOW else 0)
