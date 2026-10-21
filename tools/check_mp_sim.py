# -*- coding: utf-8 -*-
"""Multiplayer lockstep simulation of the Great Guilds, the Iron Court and the Zharr Exchange.

Runs the SHIPPED Lua of each pack on three simulated machines at once (two Chaos Dwarf houses
and a Dwarf hold), each with its own local faction, MCT, math.random, clock and screen size,
and presses every button the mod's panels draw - one machine at a time, through the real
ComponentLClickUp handlers. CampaignUI.TriggerCampaignScriptEvent goes on a bus that delivers
UITrigger to every machine in one order, as CA promises. After every step the machines'
model calls (gold, pooled resources, effect bundles, saved values, cm:random_number, every cm
write) are compared, and a difference is a desync, printed with the file:line that made it.

    py tools/check_mp_sim.py                 # gg, ic, ex, and all three loaded together
    py tools/check_mp_sim.py gg ic           # just these (gg / ic / ex / all)
    py tools/check_mp_sim.py --staged        # Modding Files/pack instead of the shipped packs
    py tools/check_mp_sim.py --errors        # list every script error, not the first 15
    py tools/check_mp_sim.py --selftest

EVERY MOD IS RUN TWICE. The second run plants a fault - each op is applied on the machine
that sent it and nowhere else - and that run MUST report a desync. If it does not, no click
reached an op, so the clean run proved nothing; that is a failure, not a pass.

Exit 1 on a desync, on a planted fault that went unseen, or on a pack that cannot be read.
The script errors it lists are mostly the stubbed world answering a call wrongly, not bugs:
they bound what the run reached, and the "ops no click reached" line says the same per op.
No two-machine game has been played; this is the closest thing to one with the game shut.
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import read_pack_index as RPI        # noqa: E402

LUA = r"C:\Program Files (x86)\Lua\5.1\lua.exe"
SIM = os.path.join(ROOT, "tools", "_mp_sim.lua")
CACHE = os.path.join(ROOT, ".skilltree_cache", "mp_sim")
GAME = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III"
WORKSHOP = r"F:\SteamLibrary\steamapps\workshop\content\1142710"
STAGED = os.path.join(ROOT, "Modding Files", "pack")

# pack file name, the button that opens the panel, and - for --staged - the staged
# scripts that belong to it.
MODS = {
    "gg": {"pack": "derpy_great_guilds.pack", "openers": ["gg_opener"],
           "staged": r"^(zzz_derpy_guilds.*|derpy_hub_gg)\.lua$",
           "mct": "derpy_great_guilds.lua", "ui": r"derpy_gg_|derpy_hub"},
    # A NEW COURT CAN AFFORD NOTHING: every move costs influence a court earns over many
    # turns, so without this the panel refuses every row and no op is ever sent.
    "ic": {"pack": "derpy_iron_court.pack", "openers": ["derpy_ic_opener"],
           "staged": r"^(zzz_derpy_iron_court.*|derpy_hub_ic)\.lua$",
           "mct": "derpy_iron_court.lua", "ui": r"derpy_ic|derpy_hub",
           "seed": """
for _, k in ipairs(cm:get_human_factions()) do
    local court = IC.court(k)
    if court and court.standing then
        local cl = cm:get_faction(k):character_list()
        for i = 0, cl:num_items() - 1 do
            court.standing[cl:item_at(i):command_queue_index()] = 2000
        end
        IC.save(k)
    end
end
"""},
    "ex": {"pack": "derpy_zharr_exchange.pack", "openers": ["derpy_chd_exchange_button"],
           "staged": r"^(zzz_derpy_chd_exchange.*|derpy_hub_ex)\.lua$",
           "mct": "derpy_chd_zharr_exchange.lua", "ui": r"derpy_chd_ex|derpy_hub"},
}


def find_pack(name):
    """The live copy: a Workshop folder first, then data/."""
    if os.path.isdir(WORKSHOP):
        for item in sorted(os.listdir(WORKSHOP)):
            p = os.path.join(WORKSHOP, item, name)
            if os.path.isfile(p):
                return p
    p = os.path.join(GAME, "data", name)
    return p if os.path.isfile(p) else None


def extract(mod):
    """{path in pack: bytes} for the scripts, MCT files and twui layouts of one pack."""
    spec = MODS[mod]
    pack = find_pack(spec["pack"])
    if not pack:
        raise SystemExit("no %s in a Workshop folder or data/" % spec["pack"])
    f, es = RPI.entries(pack)
    files = {}
    try:
        for path, size, offset, comp in es:
            low = path.lower()
            if not (low.startswith("script/campaign/mod/") or low.startswith("script/mct/settings/")
                    or low.endswith(".twui.xml")):
                continue
            if comp != 0:
                raise SystemExit("%s: %s is compressed - this reader cannot open it" % (pack, path))
            f.seek(offset)
            files[path] = f.read(size)
    finally:
        f.close()
    return pack, files


def staged(mod):
    spec = MODS[mod]
    files = {}
    mod_dir = os.path.join(STAGED, "script", "campaign", "mod")
    for n in sorted(os.listdir(mod_dir)):
        if re.match(spec["staged"], n):
            files["script/campaign/mod/" + n] = open(os.path.join(mod_dir, n), "rb").read()
    mct = os.path.join(STAGED, "script", "mct", "settings", spec["mct"])
    files["script/mct/settings/" + spec["mct"]] = open(mct, "rb").read()
    ui_dir = os.path.join(STAGED, "ui")
    for dp, _dn, fn in os.walk(ui_dir):
        for n in fn:
            if n.endswith(".twui.xml") and re.search(spec["ui"], n):
                full = os.path.join(dp, n)
                rel = os.path.relpath(full, STAGED).replace(os.sep, "/")
                files[rel] = open(full, "rb").read()
    return "staged " + STAGED, files


def lua_str(s):
    return '"' + (s.replace("\\", "\\\\").replace('"', '\\"')
                  .replace("\r", "\\r").replace("\n", "\\n")) + '"'


def layout_tree(xml_bytes):
    """The <hierarchy> as nested {id, w, h, c}, sized from each component's current state."""
    root = ET.fromstring(xml_bytes)
    sizes = {}
    comps = root.find("components")
    if comps is not None:
        for c in comps:
            cur = c.get("currentstate")
            states = c.find("states")
            if states is None:
                continue
            for st in states:
                if st.get("this") == cur:
                    try:
                        sizes[c.get("this")] = (int(float(st.get("width", 100))),
                                                int(float(st.get("height", 30))))
                    except ValueError:
                        pass
    hier = root.find("hierarchy")
    if hier is None or len(hier) == 0:
        return None

    def walk(el):
        w, h = sizes.get(el.get("this"), (100, 30))
        kids = ",".join(walk(k) for k in el)
        return "{id=%s,w=%d,h=%d,c={%s}}" % (lua_str(el.tag), w, h, kids)
    return walk(hier[0])


def write_inputs(name, files, workdir):
    """Write the extracted files and the layouts table; return (scripts, mct_files, layouts)."""
    scripts, mcts, layouts = [], [], []
    for path in sorted(files):
        out = os.path.join(workdir, *path.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as fh:
            fh.write(files[path])
        low = path.lower()
        if low.startswith("script/campaign/mod/") and low.endswith(".lua"):
            scripts.append(out)
        elif low.startswith("script/mct/settings/") and low.endswith(".lua"):
            mcts.append(out)
        elif low.endswith(".twui.xml"):
            try:
                tree = layout_tree(files[path])
            except ET.ParseError as e:
                print("  %s: %s does not parse: %s" % (name, path, e))
                tree = None
            if tree:
                key = re.sub(r"^ui/", "", low)[:-len(".twui.xml")]
                layouts.append("[%s]=%s" % (lua_str(key), tree))
    # The game loads campaign/mod scripts alphabetically by file name.
    scripts.sort(key=lambda p: os.path.basename(p).lower())
    lay = os.path.join(workdir, "layouts.lua")
    with open(lay, "w", encoding="utf-8") as fh:
        fh.write("return {\n" + ",\n".join(layouts) + "\n}\n")
    return scripts, mcts, lay


def run(name, scripts, mcts, layouts, openers, workdir, mutant, show_errors=15, seed="",
        max_clicks=1500):
    cfg = os.path.join(workdir, "config_%s.lua" % ("mutant" if mutant else "clean"))
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write("return {\n")
        fh.write("  name = %s,\n" % lua_str(name))
        fh.write("  scripts = {%s},\n" % ", ".join(lua_str(s) for s in scripts))
        fh.write("  mct_files = {%s},\n" % ", ".join(lua_str(s) for s in mcts))
        fh.write("  layouts = %s,\n" % lua_str(layouts))
        fh.write("  openers = {%s},\n" % ", ".join(lua_str(s) for s in openers))
        fh.write("  rounds = 2, max_clicks = %d, show_errors = %d,\n" % (max_clicks, show_errors))
        if seed:
            fh.write("  seed = %s,\n" % lua_str(seed))
        fh.write("  mutant = %s,\n" % ("true" if mutant else "false"))
        fh.write("}\n")
    r = subprocess.run([LUA, SIM, cfg], capture_output=True, text=True, timeout=1800)
    out = r.stdout
    if r.returncode not in (0, 1) or "RESULT" not in out:
        raise SystemExit("%s: the simulator crashed (exit %d)\n%s\n%s"
                         % (name, r.returncode, out[-3000:], r.stderr[-3000:]))
    m = re.search(r"RESULT desyncs=(\d+) clicks=(\d+) ops_reached=(\d+) ops_declared=(\d+)", out)
    return out, {"desyncs": int(m.group(1)), "clicks": int(m.group(2)),
                 "ops_reached": int(m.group(3)), "ops_declared": int(m.group(4))}


def check(name, files, openers, show_errors=15, seed=""):
    """Run clean and planted. Returns a list of failure strings."""
    workdir = os.path.join(CACHE, name)
    scripts, mcts, layouts = write_inputs(name, files, workdir)
    fails = []
    out, res = run(name, scripts, mcts, layouts, openers, workdir, False, show_errors, seed)
    print(out.rstrip())
    if res["desyncs"]:
        fails.append("%s: %d desync(s)" % (name, res["desyncs"]))
    mout, mres = run(name, scripts, mcts, layouts, openers, workdir, True, show_errors, seed)
    if mres["desyncs"] == 0:
        fails.append("%s: the planted fault went unseen - no click reached an op, so the clean "
                     "run proves nothing" % name)
        print(mout.rstrip())
    else:
        print("  planted fault: caught (%d desyncs)" % mres["desyncs"])
    print()
    return fails


# ------------------------------------------------------------------ selftest --
GOOD = r'''
-- A mod that does it right: the click broadcasts, the UITrigger applies.
local function apply(cqi)
    for _, k in ipairs(cm:get_human_factions()) do
        local f = cm:get_faction(k)
        if f:command_queue_index() == cqi then cm:treasury_mod(k, 100) end
    end
end
core:add_listener("good_click", "ComponentLClickUp", true, function(context)
    if context.string == "good_open" then
        local p = core:get_ui_root():CreateComponent("good_panel", "ui/campaign ui/good_panel")
        p:SetVisible(true)
    elseif context.string == "good_buy" then
        local me = cm:get_local_faction_name(true)
        CampaignUI.TriggerCampaignScriptEvent(cm:get_faction(me):command_queue_index(), "good|buy|")
    end
end, true)
core:add_listener("good_mp", "UITrigger", true, function(context)
    if context:trigger() == "good|buy|" then apply(context:faction_cqi()) end
end, true)
GOOD = {MP_TAG = "good", MP_OPS = {buy = function() end}}
'''

BAD_CLICK = r'''
-- Changes the model straight off a click: the commonest multiplayer bug.
core:add_listener("bad_click", "ComponentLClickUp", true, function(context)
    if context.string == "bad_buy" then
        cm:treasury_mod(cm:get_local_faction_name(true), -100)
    end
end, true)
'''

BAD_RANDOM = r'''
-- Rolls math.random into the model on a turn start that every machine sees.
core:add_listener("bad_roll", "FactionTurnStart", true, function(context)
    cm:set_saved_value("bad_roll", math.random(1, 1000000))
end, true)
'''

BAD_UNFORCED = r'''
-- The unforced accessor throws in multiplayer.
cm:add_first_tick_callback(function()
    cm:set_saved_value("bad_me", cm:get_local_faction_name())
end)
'''

BAD_MCT = r'''
-- Freezes its own machine's MCT into the save.
cm:add_first_tick_callback(function()
    local mct = get_mct()
    local v = mct:get_mod_by_key("bad_mod"):get_option_by_key("bad_rate"):get_finalized_setting()
    cm:set_saved_value("bad_rate", v)
end)
'''

BAD_MCT_FILE = r'''
local mct = get_mct()
local m = mct:register_mod("bad_mod")
local o = m:add_new_option("bad_rate", "slider")
o:slider_set_min_max(1, 9)
o:set_default_value(5)
'''

PANEL = b'''<?xml version="1.0"?>
<layout version="142"><hierarchy><root this="A"><good_panel this="B">
<good_buy this="C"/><bad_buy this="D"/></good_panel></root></hierarchy><components/></layout>'''


def _sim_once(tag, files, openers, mutant=False):
    workdir = os.path.join(CACHE, "_selftest_" + tag)
    scripts, mcts, layouts = write_inputs(tag, files, workdir)
    return run(tag, scripts, mcts, layouts, openers, workdir, mutant)


def selftest():
    ui = {"ui/campaign ui/good_panel.twui.xml": PANEL}

    def lua(name, src):
        return {"script/campaign/mod/%s.lua" % name: src.encode("utf-8")}

    good = dict(ui, **lua("good", GOOD))
    out, res = _sim_once("good", good, ["good_open"])
    assert res["desyncs"] == 0, "a correct mod was reported:\n" + out
    assert res["clicks"] >= 2, "the monkey never pressed the panel's buttons:\n" + out
    assert res["ops_reached"] == 1, "the good op never crossed the bus:\n" + out
    out, res = _sim_once("good", good, ["good_open"], mutant=True)
    assert res["desyncs"] > 0, "the planted fault went unseen on a mod with one op:\n" + out

    cases = [("bad_click", dict(good, **lua("bad_click", BAD_CLICK)), "treasury_mod"),
             ("bad_random", lua("bad_random", BAD_RANDOM), "bad_roll"),
             ("bad_mct", dict(lua("bad_mct", BAD_MCT),
                              **{"script/mct/settings/bad_mod.lua": BAD_MCT_FILE.encode()}),
              "bad_rate")]
    for tag, files, needle in cases:
        out, res = _sim_once(tag, files, ["good_open"])
        assert res["desyncs"] > 0, "%s was not reported:\n%s" % (tag, out)
        assert needle in out, "%s was reported without naming %s:\n%s" % (tag, needle, out)
        assert "%s.lua:" % tag in out, "%s's report does not name the file:line:\n%s" % (tag, out)

    out, res = _sim_once("bad_unforced", lua("bad_unforced", BAD_UNFORCED), ["x"])
    assert "unforced" in out, "the unforced local-faction call raised nothing:\n" + out

    # The layout reader: nesting, sizes, and a renamed root.
    tree = layout_tree(b'''<layout><hierarchy><root this="R"><p this="P"><k this="K"/></p>
        </root></hierarchy><components><p this="P" currentstate="S1"><states>
        <standard this="S1" width="640" height="48"/></states></p></components></layout>''')
    assert tree == '{id="root",w=100,h=30,c={{id="p",w=640,h=48,c={{id="k",w=100,h=30,c={}}}}}}', tree
    print("selftest ok - a correct mod passes, a planted fault is caught, and click, math.random,"
          " own-MCT and unforced-accessor faults are each reported with their file:line")


def main(argv):
    if "--selftest" in argv:
        selftest()
        return 0
    flags = [a for a in argv if a.startswith("--")]
    for a in flags:
        if a not in ("--staged", "--errors"):
            raise SystemExit("unknown flag %s - see the docstring" % a)
    names = [a for a in argv if not a.startswith("--")] or ["gg", "ic", "ex", "all"]
    for n in names:
        if n not in MODS and n != "all":
            raise SystemExit("unknown mod %s - gg, ic, ex or all" % n)
    show = 1000 if "--errors" in flags else 15
    source = staged if "--staged" in flags else extract
    loaded = {}
    fails = []
    for n in names:
        parts = list(MODS) if n == "all" else [n]
        files, openers, seeds = {}, [], []
        for p in parts:
            if p not in loaded:
                where, fs = source(p)
                loaded[p] = fs
                print("%s: %s" % (p, where))
            files.update(loaded[p])
            openers += MODS[p]["openers"]
            seeds.append(MODS[p].get("seed", ""))
        fails += check(n, files, openers, show, "\n".join(x for x in seeds if x))
    if fails:
        print("FAILED")
        for f in fails:
            print("  " + f)
        return 1
    print("ok - no desync in %s" % ", ".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
