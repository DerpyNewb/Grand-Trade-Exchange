"""The Derpy HUD hub: one source, three shipped copies.

    py tools/sync_derpy_hub.py             write the three Lua copies, six .twui.xml and the
                                           plate .png (needs the game installed)
    py tools/sync_derpy_hub.py --check     exit 1 if a shipped file differs from the source
    py tools/sync_derpy_hub.py --selftest  run the hub harness on the source and the copies,
                                           and prove --check sees drift

Edit only Modding Files/source/derpy_hub/derpy_hud_hub.lua. Each mod ships its own copy
under its own path (derpy_hub_ic / _gg / _ex), so every installed copy loads, and the
highest HUB_VERSION serves all three at runtime. The copies differ from the source in ONE
line, `local HUB_TAG = "<tag>"`, which names that copy's own .twui.xml. Each .twui.xml has
its own GUID prefix, because a GUID that collides with another file's is a silent non-draw.

An unknown flag is refused: tools here have no --help, and a flag that was ignored once
built and deployed a pack nobody asked for.
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
SRC = os.path.join(ROOT, "Modding Files", "source", "derpy_hub", "derpy_hud_hub.lua")
MOD_REL = "Modding Files/pack/script/campaign/mod/"
UI_REL = "Modding Files/pack/ui/campaign ui/"
HARNESS = os.path.join(ROOT, "tools", "_hub_harness.lua")
LUA = r"C:\Program Files (x86)\Lua\5.1\lua.exe"

# tag -> GUID prefix. Registered in docs/CUSTOM_UI.md's prefix table.
TAGS = {"ic": "DH01", "gg": "DH02", "ex": "DH03"}
PLATE_TAGS = {"ic": "DH04", "gg": "DH05", "ex": "DH06"}
HUB_W = HUB_H = 48          # must match HUB.SIZE in the source; check() asserts it
# Chosen by the author from tools/hub_icon_sheet.py's contact sheet (#212), 2026-10-01.
ICON = "ui/skins/default/tech_tree_tab_chd_sorcery.png"
PLATE = "ui/skins/default/button_round_medium_%s.png"
SOUND = "UI_GBL_TMP_Round_Medium_Button"
INSET = 8                   # the Guilds' 7 at 44px, scaled to 48
# THE PLATE BEHIND THE COLUMN: CA's panel_stack, the HUD's leather-in-bronze. Measured off
# the file: the frame line is ~9px inside the box, the top-right ornament reaches 36px in
# from the top and the right, the thicker bottom band sits inside 16. Margins are CA's
# top,right,bottom,left order. The Lua resizes it; images follow their box.
#
# BAKED, NOT REFERENCED. Drawn straight from CA's 256px file, the nine-slice squeezed 204px of
# the top and bottom frame into 24, 8:1, and in game both edges came out blurred (author,
# 2026-10-01: "theres a blurred part on top and bottom of the ui"). So bake_plate() cuts the
# file down to the plate's own width by joining its left and right edges, and to 128 tall by
# joining its top and bottom: across, nothing is ever scaled, and down, little. Each pack
# ships the same bytes at the same path.
BACK_SRC = "ui/skins/default/panel_stack.png"
BACK = "ui/derpy_hub/plate.png"
BACK_REL = "Modding Files/pack/" + BACK
BACK_H = 128
BACK_MARGIN = (36, 36, 16, 16)
PAD = 14                    # must match HUB.PAD; check() asserts it
PLATE_MIN = 56              # must match HUB.PLATE_MIN, and clear both margin sums
PLATE_W = HUB_W + 2 * PAD
TAG_LINE = re.compile(r'^local HUB_TAG = "src"', re.M)


def _layers(state):
    return [
        {"path": PLATE % "underlay", "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0,
         "dock": None},
        {"path": PLATE % state, "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0,
         "dock": None},
        {"path": ICON, "offset": (INSET, INSET), "dw": -2 * INSET, "dh": -2 * INSET,
         "margin": 0, "dock": "Center"},
    ]


def lua_rel(tag):
    return MOD_REL + "derpy_hub_%s.lua" % tag


def ui_rel(tag):
    return UI_REL + "derpy_hub_%s.twui.xml" % tag


def plate_rel(tag):
    return UI_REL + "derpy_hub_plate_%s.twui.xml" % tag


def pack_files(tag):
    """(workspace-relative source, path inside the pack) for one mod's three hub files."""
    return [(rel, rel.replace("Modding Files/pack/", ""))
            for rel in (lua_rel(tag), ui_rel(tag), plate_rel(tag), BACK_REL)]


def build_lua(tag, src_text=None):
    src = src_text if src_text is not None else io.open(SRC, encoding="utf-8", newline="").read()
    out, n = TAG_LINE.subn('local HUB_TAG = "%s"' % tag, src)
    if n != 1:
        raise SystemExit('the hub source must carry exactly one `local HUB_TAG = "src"` '
                         "line, found %d" % n)
    return out


def build_ui(tag):
    import gen_guilds_emitter as EU
    root = EU.C("root", HUB_W, HUB_H)
    root.add(EU.C("derpy_hub", HUB_W, HUB_H, interactive=True, sound=SOUND,
                  layers=_layers("active"), hover=_layers("hover")))
    EU.assign(root, TAGS[tag])
    return EU.layout(root, "Derpy HUD hub - one button for the author's mods")


def bake_plate():
    """PNG bytes: CA's panel_stack joined down to PLATE_W x BACK_H, quadrant by quadrant."""
    from PIL import Image
    import preview_guilds_panel as PV
    from read_pack_index import read
    from read_vanilla_loc import _decompress
    data = None
    for pk in PV.PACKS:
        fp = os.path.join(PV.GAME, pk)
        if os.path.isfile(fp):
            for path, comp, blob in read(fp, BACK_SRC):
                if path.lower() == BACK_SRC:
                    data = _decompress(blob) if comp else blob
    if not data or data[:4] != b"\x89PNG":
        raise SystemExit("cannot read %s out of CA's ui packs" % BACK_SRC)
    src = Image.open(io.BytesIO(data)).convert("RGBA")
    w, h = src.size
    out = Image.new("RGBA", (PLATE_W, BACK_H))
    left, top = PLATE_W // 2, BACK_H // 2
    for sx, dx, cw in ((0, 0, left), (w - (PLATE_W - left), left, PLATE_W - left)):
        for sy, dy, ch in ((0, 0, top), (h - (BACK_H - top), top, BACK_H - top)):
            out.paste(src.crop((sx, sy, sx + cw, sy + ch)), (dx, dy))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def build_plate(tag):
    import gen_guilds_emitter as EU
    root = EU.C("root", PLATE_W, PLATE_MIN)
    root.add(EU.C("derpy_hub_plate", PLATE_W, PLATE_MIN, interactive=True,
                  layers=[{"path": BACK, "offset": (0, 0), "dw": 0, "dh": 0,
                           "margin": BACK_MARGIN, "dock": None}]))
    EU.assign(root, PLATE_TAGS[tag])
    return EU.layout(root, "Derpy HUD hub - the plate behind the column")


def built(tag):
    return {lua_rel(tag): build_lua(tag), ui_rel(tag): build_ui(tag),
            plate_rel(tag): build_plate(tag)}


def write(root=ROOT):
    path = os.path.join(root, BACK_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(bake_plate())
    print("wrote", BACK_REL)
    for tag in TAGS:
        for rel, text in built(tag).items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            print("wrote", rel)


def check(root=ROOT):
    """[problem] - empty when every shipped file is exactly what the source builds."""
    problems = []
    src = io.open(SRC, encoding="utf-8", newline="").read()
    size = re.search(r"^\s*SIZE = (\d+),", src, re.M)
    if not size or int(size.group(1)) != HUB_W:
        problems.append("HUB.SIZE in the source is not HUB_W (%d)" % HUB_W)
    for name, want in (("PAD", PAD), ("PLATE_MIN", PLATE_MIN)):
        got = re.search(r"^\s*%s = (\d+)," % name, src, re.M)
        if not got or int(got.group(1)) != want:
            problems.append("HUB.%s in the source is not %d" % (name, want))
    top, right, bottom, left = BACK_MARGIN
    if top + bottom >= PLATE_MIN or left + right >= PLATE_W:
        problems.append("the plate's nine-slice margins overlap at its smallest size")
    if not os.path.isfile(os.path.join(root, BACK_REL)):
        problems.append("missing: " + BACK_REL)
    for tag in TAGS:
        for rel, want in built(tag).items():
            path = os.path.join(root, rel)
            if not os.path.isfile(path):
                problems.append("missing: " + rel)
            elif io.open(path, encoding="utf-8", newline="").read() != want:
                problems.append("drifted from the source: " + rel
                                + " (run py tools/sync_derpy_hub.py)")
    return problems


def check_assets():
    """The art exists in CA's packs, each file validates, and no GUID is shared."""
    import gen_guilds_emitter as EU
    import preview_guilds_panel as PV
    problems = []
    have = EU._game_assets()
    for p in [PLATE % s for s in ("underlay", "active", "hover")] + [ICON, BACK_SRC]:
        if p not in have:
            problems.append("not in CA's ui packs: " + p)
    # THE BAKED PLATE IS TODAY'S BAKE, at the size the twui and the margins assume.
    path = os.path.join(ROOT, BACK_REL)
    if os.path.isfile(path):
        from PIL import Image
        if open(path, "rb").read() != bake_plate():
            problems.append("stale bake: " + BACK_REL + " (run py tools/sync_derpy_hub.py)")
        if Image.open(path).size != (PLATE_W, BACK_H):
            problems.append("%s is not %dx%d" % (BACK_REL, PLATE_W, BACK_H))
    # TWUI Studio is non-commercial and never in a public repo; the workspace has it.
    if os.path.isdir(PV.STUDIO):
        problems += PV.validate("derpy_hub_")
    else:
        print("  (skipped the TWUI Studio read: no TWUI_Studio folder)")
    seen = {}
    for tag in TAGS:
        for what, text in (("hub", build_ui(tag)), ("plate", build_plate(tag))):
            for g in set(re.findall(r'uniqueguid="([^"]+)"', text)):
                if g in seen:
                    problems.append("GUID %s in both %s and %s %s" % (g, seen[g], what, tag))
                seen[g] = "%s %s" % (what, tag)
    return problems


def run_harness(files):
    p = subprocess.run([LUA, HARNESS] + files, capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout + p.stderr


def selftest():
    assert os.path.isfile(LUA), "lua.exe is required for the hub selftest"
    code, out = run_harness([])
    assert code == 0, "the harness fails on the source:\n" + out
    copies = [os.path.join(ROOT, lua_rel(t)) for t in TAGS]
    code, out = run_harness(copies)
    assert code == 0, "the harness fails on the shipped copies:\n" + out
    # Exactly one line differs between the source and a copy.
    src = io.open(SRC, encoding="utf-8", newline="").read().split("\n")
    ic = build_lua("ic").split("\n")
    diff = [i for i in range(len(src)) if src[i] != ic[i]]
    assert len(src) == len(ic) and len(diff) == 1, "a copy differs in %r" % diff
    # The tag line is required exactly once.
    try:
        build_lua("ic", "local HUB_VERSION = 1\n")
        raise AssertionError("a source with no HUB_TAG line was accepted")
    except SystemExit:
        pass
    # --check sees drift and a missing file.
    tmp = tempfile.mkdtemp()
    try:
        write(tmp)
        assert check(tmp) == [], check(tmp)
        victim = os.path.join(tmp, lua_rel("gg"))
        with io.open(victim, "a", encoding="utf-8", newline="\n") as fh:
            fh.write("-- edited by hand\n")
        assert any("derpy_hub_gg.lua" in p for p in check(tmp)), "drift went unseen"
        os.remove(os.path.join(tmp, ui_rel("ex")))
        assert any("missing" in p and "derpy_hub_ex" in p for p in check(tmp)), "missing unseen"
    finally:
        shutil.rmtree(tmp)
    problems = check_assets()
    assert not problems, "\n".join(problems)
    print("sync_derpy_hub selftest: ok")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == []:
        write()
    elif args == ["--check"]:
        found = check() + check_assets()
        for p in found:
            print(p)
        sys.exit(1 if found else 0)
    elif args == ["--selftest"]:
        selftest()
    else:
        raise SystemExit("unknown arguments %r - see the docstring" % (args,))
