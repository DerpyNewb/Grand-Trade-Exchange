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
    py tools/preview_guilds_panel.py --help-page 7
                                                # ONLY the Help tab, that chapter, to
                                                #   gg_help_p7.png (the halls page; 7 exists
                                                #   for a race with halls). Drives the
                                                #   harness's GG_DUMP_HELP_PAGE.
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


# CA'S OWN COLOURS for the three [[col:]] names this panel writes, read out of
# db/ui_colours_tables - the table the tag resolves against - and not picked by eye.
# selftest() re-reads the cached table when it is there.
INK = {"red": (0xFF, 0x2D, 0x2D, 255), "yellow": (0xFF, 0xB9, 0x00, 255),
       "orange": (0xFF, 0xAD, 0x5B, 255),
       "green": (0xA0, 0xFF, 0x37, 255)}
PALE, GOLD = (235, 225, 200, 255), (255, 211, 122, 255)
DIM = (0xC9, 0xBF, 0xA8, 255)          # the card descriptions' and help lines' colour
MARKUP = re.compile(r"\[\[(/?)col(?::([^\]]*))?\]\]")

# --size small|large: the MCT Panel size to draw (gen_guilds_ui.SIZES); "" is Medium.
DSIZE = ""


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
    for kind in ("panel", "row", "list", "card", "frow"):
        # The race's own panel and card, as GGUI.frame_path creates them.
        fname = G.frame_file("derpy_gg_" + kind, tag) if kind in ("panel", "card") \
            else "derpy_gg_%s.twui.xml" % kind
        fname = fname.replace(".twui.xml", DSIZE + ".twui.xml")
        d = model.Document(io.open(os.path.join(OURS, fname), encoding="utf-8").read())
        docs[kind] = d
        for c in d.components:
            named[(kind, c.get("id", c.tag))] = c
    n, d = G.SIZES[DSIZE][:2] if DSIZE else (1, 1)
    canvas = Image.new("RGBA", size or (int(G.PANEL_W * n / d + 0.5),
                                        int(G.PANEL_H * n / d + 0.5)), (0, 0, 0, 255))

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
                           missing=missing, low=low, contrast=contrast, docs=docs,
                           named=named)


def _save(P, name, path=None):
    out = path or os.path.join(CACHE, name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    P.canvas.convert("RGB").save(out)
    return out


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


# ------------------------------------------------------------ drawn from the Lua ---
# WHAT THE SHIPPED LUA PUT ON SCREEN, tab by tab. tools/_guilds_harness.lua opens the real
# panel over a demo save with GG_DUMP set and writes every component it touched: where it
# moved it, the size it gave it, the text and images it set, and whether it hid it. This
# draws exactly that. It replaced four hand-written views that retyped the Lua's strings
# and laid the panel out from the generator's coordinates, so a fault in the Lua - a label
# the script never writes, a part it never moves - drew correctly in the picture.
LUA = r"C:\Program Files (x86)\Lua\5.1\lua.exe"
HARNESS = os.path.join("tools", "_guilds_harness.lua")
VIEWS = {1: "guilds", 2: "standings", 3: "bounties", 4: "court", 5: "help", 6: "log"}
IMG = re.compile(r"\[\[img:([^\]]*)\]\]\[\[/img\]\]")
TOKENS = re.compile(r"\[\[(/?)col(?::([^\]]*))?\]\]|\[\[img:([^\]]*)\]\]\[\[/img\]\]")


def snapshot(tag="", help_page=None, page=None):
    """{tab: {key: row}} from the harness's GG_DUMP, read as `tag`'s race. `help_page`
    picks the Help chapter every tab is dumped on (GG_DUMP_HELP_PAGE); None is page 1.
    `page` picks the guild page the same way (GG_DUMP_PAGE)."""
    import subprocess
    import tempfile
    out = tempfile.mkdtemp()
    env = dict(os.environ, GG_DUMP=out.replace(os.sep, "/"), GG_DUMP_TAG=tag,
               GG_DUMP_SIZE={"_sm": "small", "_lg": "large"}.get(DSIZE, "medium"))
    if help_page:
        env["GG_DUMP_HELP_PAGE"] = str(help_page)
    if page:
        env["GG_DUMP_PAGE"] = str(page)
    r = subprocess.run([LUA, HARNESS], cwd=ROOT, env=env, capture_output=True, text=True)
    if r.returncode or "harness ok" not in r.stdout:
        raise SystemExit("the guilds harness failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])

    def num(v):
        return float(v) if v else None
    got = {}
    for tab in VIEWS:
        rows = {}
        for line in io.open(os.path.join(out, "tab%d.tsv" % tab), encoding="utf-8"):
            f = line.rstrip("\n").split("\t")
            imgs = {}
            for part in filter(None, f[7].split(";")):
                i, p = part.split("=", 1)
                imgs[int(i)] = p
            rows[f[0]] = dict(key=f[0], x=num(f[1]), y=num(f[2]), w=num(f[3]), h=num(f[4]),
                              vis=f[5] == "true", text=f[6], img=imgs)
        got[tab] = rows
    return got


def _where(key):
    """(file kind, component id) for a dump key, or None for something not ours."""
    if key == "root/derpy_gg_panel":
        return "panel", "derpy_gg_panel"
    parts = key.split("/")
    if parts[0] != "P" or len(parts) < 2:
        return None
    top, name = parts[1], parts[-1]
    if re.match(r"derpy_gg_frow_\d+$", name):
        return "frow", "derpy_gg_frow"
    for kind in ("card", "row"):
        if re.match(r"derpy_gg_%s_\d+$" % kind, top):
            return kind, ("derpy_gg_" + kind if len(parts) == 2 else name)
    if top == "listview":
        return "list", name
    return ("panel", name) if len(parts) == 2 else None


def draw_order(P, rows):
    """Keys in the order the engine draws them: the panel's own children in hierarchy
    order, then what the Lua created on it - cards, standings rows, the list - in the
    order open() creates them, each followed by its own children."""
    def ids(kind):
        return [c.get("id", c.tag) for c in P.docs[kind].components]
    out = ["root/derpy_gg_panel"]
    out += ["P/" + i for i in ids("panel")]
    for kind, n in (("card", 3), ("row", len(P.G.G.GUILDS))):
        for i in range(1, n + 1):
            top = "P/derpy_gg_%s_%d" % (kind, i)
            out += [top] + [top + "/" + c for c in ids(kind)]
    # The slider's parts are found through it, so their keys nest a level deeper.
    for c in ids("list"):
        out += sorted(k for k in rows if k.startswith("P/listview/") and k.rsplit("/", 1)[1] == c)
    frows = sorted((k for k in rows if _where(k) == ("frow", "derpy_gg_frow")),
                   key=lambda k: int(k.rsplit("_", 1)[1]))
    seen, order = set(), []
    for k in out + frows:
        if k in rows and k not in seen:
            seen.add(k)
            order.append(k)
    return order


def shown(rows, key):
    """Visible, and so is every ancestor: a hidden row hides its cells."""
    if not rows["root/derpy_gg_panel"]["vis"]:
        return False
    parts = key.split("/")
    for i in range(2, len(parts) + 1):
        r = rows.get("/".join(parts[:i]))
        if r is not None and not r["vis"]:
            return False
    return True


def _pair(v):
    a, b = (v or "0,0").split(",")
    return float(a), float(b)


OVER = []          # every line wider than the box it is written in


def write(P, key, box, text, ct):
    """A dumped string in its component's box, as its <component_text> places it: the
    offsets, the alignment, the colour, [[col:]] honoured and [[img:]] drawn inline."""
    from PIL import Image
    x, y, w, h = box
    size = int(float(ct.get("font_m_size") or 12))
    l, r = _pair(ct.get("textxoffset"))
    t, b = _pair(ct.get("textyoffset"))
    base = PALE
    col = ct.get("font_m_colour")
    if col and len(col) == 9:
        base = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5, 7))
    font = P.font(size)
    # An inline image costs a square a little taller than the line, as the engine draws a flag.
    icon = size + 8
    plain = IMG.sub("", MARKUP.sub("", text))
    tw = P.draw.textlength(plain, font=font) + len(IMG.findall(text)) * icon
    room = w - l - r
    if tw > room + 1:
        OVER.append("%s: %dpx in %dpx  %s" % (key, tw, room, plain[:60]))
    halign = (ct.get("texthalign") or "Left").lower()
    tx = x + l + {"left": 0, "right": room - tw}.get(halign, (room - tw) / 2)
    valign = (ct.get("textvalign") or "Center").lower()
    ty = {"top": y + t, "bottom": y + h - b - size}.get(
        valign, y + t + (h - t - b - size) / 2 - 1)
    colour = base

    def run(seg):
        nonlocal tx
        if seg:
            P.contrast(tx, ty, seg, size, colour)
            P.draw.text((tx, ty), seg, fill=colour, font=font)
            tx += P.draw.textlength(seg, font=font)
    pos = 0
    for m in TOKENS.finditer(text):
        run(text[pos:m.start()])
        if m.group(3) is not None:
            f = os.path.join(UI, os.path.relpath(m.group(3), "ui").replace("/", os.sep))
            ix, iy = int(tx), int(ty + size / 2 - icon / 2)
            if os.path.isfile(f):
                P.canvas.alpha_composite(Image.open(f).convert("RGBA").resize((icon, icon)),
                                         (ix, iy))
            else:
                P.draw.rectangle([ix, iy, ix + icon - 1, iy + icon - 1],
                                 outline=(120, 100, 70, 255))
            tx += icon
        else:
            colour = base if m.group(1) else INK.get(m.group(2), base)
        pos = m.end()
    run(text[pos:])


def render_tab(tab, rows, tag="", path=None):
    """One tab, every part where the Lua put it and saying what the Lua wrote."""
    P = _setup(None, tag)
    # The images the dump names that no file does: flags written inline, swapped CA art.
    inline = set()
    for r in rows.values():
        inline |= set(IMG.findall(r["text"]))
        inline |= {p for p in r["img"].values()
                   if p.startswith("ui/") and "derpy_gg_" not in p}
    extract_art(extra=(), optional=sorted(inline))
    clip = None
    for key in draw_order(P, rows):
        where = _where(key)
        if where is None or not shown(rows, key):
            continue
        kind, xid = where
        r = rows[key]
        comp = P.named.get((kind, xid))
        st = P.docs[kind].state(comp) if comp is not None else None
        if st is None:
            continue
        w = r["w"] if r["w"] is not None else float(st.get("width") or 0)
        h = r["h"] if r["h"] is not None else float(st.get("height") or 0)
        x, y = r["x"], r["y"]
        if key == "root/derpy_gg_panel":
            x, y = 0, 0                      # every other position is relative to it
        if kind == "frow":
            # The engine's List layout stacks these; no script moves them.
            if clip is None:
                continue
            n = int(key.rsplit("_", 1)[1]) - 1
            x, y = clip[0], clip[1] + n * h
            if y + h > clip[1] + clip[3]:
                continue                     # below the clip window, scrolled out
        if x is None and xid == "handle":
            # The engine owns the handle; at rest it sits at the top of the track.
            vs = next((v for k, v in rows.items() if k.endswith("/vslider")), None)
            if vs and vs["x"] is not None:
                x, y = vs["x"], vs["y"]
        if x is None:
            continue                         # never placed: the engine owns it
        if xid == "list_clip":
            clip = (x, y, w, h)
        full_w = float(st.get("width") or w)
        crop = int(w) if r["w"] is not None and w < full_w else None
        P.paste(kind, xid, x, y, w, h, by_index=r["img"] or None, crop=crop)
        ct = st.child("component_text")
        if r["text"] and ct is not None:
            write(P, key, (x, y, w, h), r["text"], ct)
    # THE HEADER'S TWO CELLS SHARE ONE BAR: the heading from the left, the figures from the
    # right. Each fits its own box, so OVER cannot see them run into each other.
    head, stats = rows.get("P/gg_rank_line"), rows.get("P/gg_rank_stats")
    # Measured in Medium's design pixels and fonts, so only at Medium.
    if head and stats and head["text"] and stats["text"] and not DSIZE:
        G = P.G
        x, y, w, h = G.PANEL_LAYOUT["gg_rank_line"]
        lx = float(G.frame(tag)["rank_tx"].split(",")[0])
        need = (lx + P.draw.textlength(MARKUP.sub("", head["text"]), font=P.font(18)) + 24
                + P.draw.textlength(MARKUP.sub("", stats["text"]), font=P.font(12))
                + G.RANK_STATS_PAD[tag])
        if need > w:
            OVER.append("%s header: heading and figures need %dpx of %d  %s | %s"
                        % (VIEWS[tab], need, w, head["text"][:30], stats["text"][:40]))
    return _save(P, "gg_%s%s%s.png" % (VIEWS[tab], tag, DSIZE), path)


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

    # THE PICTURES ARE THE LUA'S: every tab is dumped, its panel and header are there, and
    # what one tab hides another shows - a dump that wrote nothing, or wrote every tab the
    # same, would draw six identical pictures and report nothing.
    got = snapshot()
    for tab, rows in got.items():
        assert "root/derpy_gg_panel" in rows, "tab %d: no panel in the dump" % tab
        assert rows.get("P/gg_rank_line", {}).get("text"), "tab %d: no heading" % tab
    lists = [shown(got[t], "P/listview") for t in VIEWS if "P/listview" in got[t]]
    assert lists.count(True) == 1, "the faction list shows on exactly one tab: %r" % lists
    # And the width check can fail.
    n = len(OVER)
    P = _setup(None)
    ct = P.named[("panel", "gg_footer")]
    write(P, "probe", (0, 0, 40, 20), "far too long for forty pixels",
          P.docs["panel"].state(ct).child("component_text"))
    assert len(OVER) == n + 1, "a line wider than its box is not reported"
    del OVER[n:]

    print("selftest ok: %d files validate, the reader catches a broken link, six tabs dumped"
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
        if "--size" in args:
            at = args.index("--size")
            DSIZE = {"small": "_sm", "large": "_lg", "medium": ""}[args[at + 1]]
            del args[at:at + 2]
        if "--flavour" in args:
            at = args.index("--flavour")
            tag = "_" + args[at + 1]
            del args[at:at + 2]
        page = None
        if "--page" in args:
            at = args.index("--page")
            page = int(args[at + 1])
            del args[at:at + 2]
        if "--help-page" in args:
            at = args.index("--help-page")
            page = int(args[at + 1])
            got = snapshot(tag, page)
            print("wrote %s" % render_tab(5, got[5], tag, os.path.join(
                CACHE, "gg_help_p%d%s%s.png" % (page, tag, DSIZE))))
            for o in OVER:
                print("  TOO WIDE " + o)
            for m in LOW:
                print("  LOW CONTRAST " + m)
            sys.exit(1 if problems or LOW or OVER else 0)
        got = snapshot(tag, page=page)
        for tab in VIEWS:
            print("wrote %s" % render_tab(tab, got[tab], tag, None if not page else
                  os.path.join(CACHE, "gg_%s%s%s_g%d.png" % (VIEWS[tab], tag, DSIZE, page))))
        if not DSIZE:   # the pick card is drawn from Medium's coordinates
            pick, lines = render_pick(tag=tag)
            print("wrote %s  (the instruction takes %d of the card's 2 lines%s)"
                  % (pick, len(lines), ", CUT" if lines and lines[-1].endswith(" ...")
                     else ""))
        for o in OVER:
            print("  TOO WIDE " + o)
        # AFTER EVERY RENDER, not after the first. Printed after the Leaderboard alone, the
        # Guilds, Log, Bounties and picking views appended their failures to a list nobody
        # read again - the Guilds tab is where the service cards are, and a Dark Elf card's
        # text sat on a white-hot flare with nothing reported (2026-09-30).
        for m in LOW:
            print("  LOW CONTRAST " + m)
        sys.exit(1 if problems or LOW or OVER else 0)
