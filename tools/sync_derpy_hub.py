"""The Derpy HUD hub: one source, five shipped copies.

    py tools/sync_derpy_hub.py             write the five Lua copies, ten .twui.xml and the
                                           two baked .png (needs the game installed)
    py tools/sync_derpy_hub.py --check     exit 1 if a shipped file differs from the source
    py tools/sync_derpy_hub.py --selftest  run the hub harness on the source and the copies,
                                           and prove --check sees drift
    py tools/sync_derpy_hub.py --pack-left-bar
                                           build Modding Files/Modpacks/derpy_hub_left_bar.pack
                                           (needs RPFM open)

Edit only Modding Files/source/derpy_hub/derpy_hud_hub.lua. Each mod ships its own copy
under its own path (derpy_hub_ic / _gg / _ex / _mr), so every installed copy loads, and the
highest HUB_VERSION serves all of them at runtime. The fifth copy, _lb, is the LEFT BAR
SUBMOD's (2026-10-11): it sets DERPY_HUB_LEFT_BAR and the hub moves into CA's top-left menu
bar. The copies differ from the source in ONE line, `local HUB_TAG = "<tag>"`, which names
that copy's own .twui.xml. Each .twui.xml has its own GUID prefix, because a GUID that
collides with another file's is a silent non-draw.

An unknown flag is refused: tools here have no --help, and a flag that was ignored once
built and deployed a pack nobody asked for.
"""
import io
import json
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
TAGS = {"ic": "DH01", "gg": "DH02", "ex": "DH03", "mr": "DH07", "lb": "DH09"}
PLATE_TAGS = {"ic": "DH04", "gg": "DH05", "ex": "DH06", "mr": "DH08", "lb": "DH10"}
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
# THE LEFT BAR'S ICON. There the hub is CA's round_small_button, whose image 0 draws at the
# full 38px; CA's own icons for it are 38px files with the glyph inset (icon_options: 22px at
# 9,9). The hub's 60px icon drawn there would cover the button's ring, so it is baked down
# onto a 38px canvas the same way. Only the submod ships it.
SMALL = "ui/derpy_hub/icon_small.png"
SMALL_REL = "Modding Files/pack/" + SMALL
SMALL_W, SMALL_GLYPH = 38, 24
BAR_TEMPLATE = "ui/templates/round_small_button.twui.xml"
LB_PACK = os.path.join(ROOT, "Modding Files", "Modpacks", "derpy_hub_left_bar.pack")


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
    """(workspace-relative source, path inside the pack) for one mod's hub files."""
    rels = [lua_rel(tag), ui_rel(tag), plate_rel(tag), BACK_REL]
    if tag == "lb":
        rels.append(SMALL_REL)
    return [(rel, rel.replace("Modding Files/pack/", "")) for rel in rels]


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


def _ca_png(want):
    """A PIL image of one png out of CA's ui packs."""
    from PIL import Image
    import preview_guilds_panel as PV
    from read_pack_index import read
    from read_vanilla_loc import _decompress
    data = None
    for pk in PV.PACKS:
        fp = os.path.join(PV.GAME, pk)
        if os.path.isfile(fp):
            for path, comp, blob in read(fp, want):
                if path.lower() == want:
                    data = _decompress(blob) if comp else blob
    if not data or data[:4] != b"\x89PNG":
        raise SystemExit("cannot read %s out of CA's ui packs" % want)
    return Image.open(io.BytesIO(data)).convert("RGBA")


def bake_icon():
    """PNG bytes: the hub's icon at SMALL_GLYPH px, centred on a SMALL_W px clear canvas."""
    from PIL import Image
    glyph = _ca_png(ICON).resize((SMALL_GLYPH, SMALL_GLYPH), Image.LANCZOS)
    out = Image.new("RGBA", (SMALL_W, SMALL_W))
    at = (SMALL_W - SMALL_GLYPH) // 2
    out.paste(glyph, (at, at))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def bake_plate():
    """PNG bytes: CA's panel_stack joined down to PLATE_W x BACK_H, quadrant by quadrant."""
    from PIL import Image
    src = _ca_png(BACK_SRC)
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
    for rel, bake in ((BACK_REL, bake_plate), (SMALL_REL, bake_icon)):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(bake())
        print("wrote", rel)
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
    for name, want in (("BAR_ICON", SMALL), ("BAR_TEMPLATE", BAR_TEMPLATE[:-len(".twui.xml")])):
        if '%s = "%s",' % (name, want) not in src:
            problems.append("HUB.%s in the source is not %s" % (name, want))
    for rel in (BACK_REL, SMALL_REL):
        if not os.path.isfile(os.path.join(root, rel)):
            problems.append("missing: " + rel)
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
    for p in [PLATE % s for s in ("underlay", "active", "hover")] + [ICON, BACK_SRC, BAR_TEMPLATE]:
        if p not in have:
            problems.append("not in CA's ui packs: " + p)
    path = os.path.join(ROOT, SMALL_REL)
    if os.path.isfile(path) and open(path, "rb").read() != bake_icon():
        problems.append("stale bake: " + SMALL_REL + " (run py tools/sync_derpy_hub.py)")
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


def pack_left_bar():
    """Build the left bar submod from scratch, then read the SAVED file back with RPFM shut out
    of the loop: every path present and byte for byte what the workspace holds."""
    import datetime
    from check_skill_trees import _rpc, _call
    from read_pack_index import entries
    found = check() + check_assets()
    if found:
        raise SystemExit("refusing to pack:\n" + "\n".join(found))
    files = [(os.path.join(ROOT, s), d) for s, d in pack_files("lb")]
    if os.path.exists(LB_PACK):
        backup = os.path.join(ROOT, "Modding Files", "Backup", "derpy_hub_left_bar_%s.pack"
                              % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copy2(LB_PACK, backup)
        print("backed up the old pack to", os.path.relpath(backup, ROOT))
    _rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "sync_derpy_hub", "version": "1"}})
    _rpc("notifications/initialized", notify=True)
    _call("set_game_selected", {"game_name": "warhammer_3", "rebuild_dependencies": False})
    key = _call("new_pack", {})["String"]
    _call("set_pack_file_type", {"pack_key": key, "pack_file_type": '"Mod"'})
    _call("add_packed_files", {"pack_key": key, "source_paths": [s for s, _d in files],
                               "destination_paths": json.dumps([{"File": d} for _s, d in files])})
    _call("save_pack_as", {"pack_key": key, "path": LB_PACK})
    fh, index = entries(LB_PACK)
    got = {}
    for path, size, offset, comp in index:
        fh.seek(offset)
        got[path] = (comp, fh.read(size))
    fh.close()
    for src, dest in files:
        comp, data = got.get(dest, (None, None))
        assert data is not None, "not in the saved pack: " + dest
        assert comp == 0 and data == open(src, "rb").read(), "differs in the saved pack: " + dest
    extra = sorted(set(got) - {d for _s, d in files})
    assert all(p.endswith(".rpfm_reserved") for p in extra), "unexpected in the pack: %s" % extra
    print("saved and verified %s: %d files" % (os.path.relpath(LB_PACK, ROOT), len(files)))


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
    elif args == ["--pack-left-bar"]:
        selftest()
        pack_left_bar()
    else:
        raise SystemExit("unknown arguments %r - see the docstring" % (args,))
