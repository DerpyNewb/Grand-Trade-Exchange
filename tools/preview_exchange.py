# -*- coding: utf-8 -*-
"""Render the Zharr Exchange panel to PNGs with the game shut.

WHAT IS REAL AND WHAT IS NOT. The positions, the text, the greyed buttons and the tooltips are
the SHIPPED Lua's own: this runs zzz_derpy_chd_exchange.lua under Lua 5.1 against fake UI
components that CreateComponent builds from our three .twui.xml files, calls the real
EX.build_panel, EX.layout and EX.refresh_panel, and reads back what they left on screen. The
Log scene's lines are written by the real EX.charge_carry, EX.apply_offer, EX.fire_demand and
EX.bulk_trade, not typed here. The ART is CA's, drawn by TWUI Studio's rasteriser (the same one
preview_guilds_panel.py uses).

What is approximate: glyphs are Segoe UI, not the game's font, so widths are close and not
exact; a greyed button is drawn from the shader EX.set_off asks for (set_greyscale_t0 and its
two values), which is CA's documented effect and not a capture of the game's own render; the
HUD opener sits where the game would never put it, beside its tooltip. The
world is a demo - supply, prices and holdings are set by the scene, the faction is a stub.

    py tools/preview_exchange.py             # .skilltree_cache/ui_preview/ex_offer.png, ex_trade.png, ex_log.png
    py tools/preview_exchange.py --selftest  # each scene ran clean and drew what it is for

Any cm: / common. member the Lua reached that the stub does not define is answered with a
no-op and NAMED in the output, so a scene that silently lost a game call says so.
"""
import io
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import preview_guilds_panel as PG                                    # noqa: E402

LUA = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign", "mod",
                   "zzz_derpy_chd_exchange.lua")
LUA_EXE = r"C:\Program Files (x86)\Lua\5.1\lua.exe"
PREFIX = "derpy_chd_exchange_"
FILES = {"panel": PREFIX + "panel.twui.xml", "row": PREFIX + "row.twui.xml",
         "button": PREFIX + "button.twui.xml"}
SCREEN = (1600, 900)
FONT = "C:/Windows/Fonts/segoeui.ttf"
FONT_B = "C:/Windows/Fonts/seguisb.ttf"

DRIVER = r"""
local TREES = @@TREES@@
local SAVED, STUBBED = {}, {}
TURN = 10
TREASURY = { player = 60000 }
POOL = {}
local function stub_rest(t, what)
    return setmetatable(t, { __index = function(_, k)
        STUBBED[what .. k] = true
        return function() end
    end })
end
local function faction(k)
    return {
        name = function() return k end,
        -- A COVERED RACE, so the Offerings tab and the tithe are live the way a Chaos Dwarf
        -- player sees them. Uncovered, both are locked and the patron is "The altar".
        culture = function() return "wh3_dlc23_chd_chaos_dwarfs" end,
        is_null_interface = function() return false end,
        treasury = function() return TREASURY[k] or 0 end,
        at_war_with = function() return false end,
        allied_with = function() return false end,
        military_allies_with = function() return false end,
        is_vassal_of = function() return false end,
        trade_agreement_with = function() return false end,
        non_aggression_pact_with = function() return false end,
        diplomatic_standing_with = function() return 0 end,
        is_human = function() return k == "player" end,
        pooled_resource_manager = function() return { resource = function(_, key)
            return { is_null_interface = function() return false end,
                     value = function() return POOL[key] or 0 end }
        end } end,
    }
end
cm = stub_rest({
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function(_, k, v) SAVED[k] = v end,
    get_saved_value = function(_, k) return SAVED[k] end,
    get_local_faction_name = function() return "player" end,
    get_faction = function(_, k) if k == "player" then return faction(k) end return false end,
    turn_number = function() return TURN end,
    model = function() return { turn_number = function() return TURN end } end,
    random_number = function() return 1 end,
    treasury_mod = function(_, k, n) TREASURY[k] = (TREASURY[k] or 0) + n end,
    faction_add_pooled_resource = function(_, _f, key, _why, n) POOL[key] = (POOL[key] or 0) + n end,
}, "cm:")
common = stub_rest({ get_localised_string = function() return "" end }, "common.")
core = { add_listener = function() end, get_ui_root = function() return ROOT end }
function out() end

local ALL, build = {}, nil
local function comp(name, parent, xid)
    local node = xid or name
    local c = { name = name, xid = node, x = 0, y = 0, vis = true, kids = {}, order = {},
                parent = parent, states = { standard = "" }, cur = "standard" }
    c.MoveTo = function(_, x, y) c.x, c.y = x, y end
    c.Position = function() return c.x, c.y end
    c.Dimensions = function() return c.w or (TREES.size[node] or {100})[1], c.h or (TREES.size[node] or {0, 30})[2] end
    c.Bounds = c.Dimensions
    c.SetVisible = function(_, v) c.vis = v and true or false end
    c.Visible = function() return c.vis end
    c.SetStateText = function(_, t) c.states[c.cur] = t end
    c.GetStateText = function() return c.states[c.cur] end
    c.SetTooltipText = function(_, t) c.tip = t end
    c.SetInteractive = function() end
    c.SetDisabled = function(_, v) c.disabled = v and true or false end
    c.ShaderTechniqueSet = function(_, sh, all) c.shader, c.shader_all = sh, all end
    c.ShaderVarsSet = function(_, a, b) c.svars = { a or 0, b or 1 } end
    c.SetImagePath = function(_, p) c.img = p end
    c.SetCanResizeWidth = function() end
    c.SetCanResizeHeight = function() end
    c.Resize = function(_, w, h) c.w, c.h = w, h end
    c.SetState = function(_, st) c.cur = st end
    c.CurrentState = function() return c.cur end
    c.Id = function() return c.name end
    c.TextDimensionsForText = function(_, t) return math.floor(#t * 6.7), 16 end
    c.ChildCount = function() return #c.order end
    c.Find = function(_, j) return c.order[j + 1] end
    c.CreateComponent = function(_, n, file)
        if c.kids[n] then return end
        local which = file and (string.find(file, "_row") and "row" or "panel")
        local k = comp(n, c, which and TREES[which][1] or n)
        if which then for _, sub in ipairs(TREES[which][2]) do build(sub, k) end end
    end
    if parent then parent.kids[name] = c; parent.order[#parent.order + 1] = c end
    ALL[#ALL + 1] = c
    return c
end
build = function(node, parent)
    local c = comp(node[1], parent)
    for _, sub in ipairs(node[2]) do build(sub, c) end
end
ROOT = comp("root")
function find_uicomponent(from, name)
    if from == nil then return nil end
    if from.name == name then return from end
    for _, k in ipairs(from.order or {}) do
        local hit = find_uicomponent(k, name)
        if hit then return hit end
    end
    return nil
end
function is_uicomponent(c) return type(c) == "table" and c.MoveTo ~= nil end
function UIComponent(c) return c end

dofile([[@@LUA@@]])
EX.store = SAVED
EX.screen = function() return @@SW@@, @@SH@@ end
EX.place_button = function() end
local OPENER = comp(EX.BUTTON, ROOT)
local function give(res, n) POOL[EX.hold_key(res)] = n end
-- 5.1's xpcall takes no arguments for f, hence the closure.
local function ok(tag, f, ...)
    local args = { ... }
    local good, err = xpcall(function() return f(unpack(args)) end, debug.traceback)
    if not good then print("ERR\t" .. tag .. "\t" .. string.gsub(tostring(err), "[\t\n]+", " | ")) end
end

-- A DEMO WORLD: output per turn, a price on each good, twelve turns of history for the
-- sparklines. Deterministic, so two runs draw the same picture.
for i, res in ipairs(EX.COMMODITIES) do
    EX.supply = EX.supply or {}
    EX.supply[res] = 2 + (i * 7) % 23
    EX.current[res] = EX.neutral_rung() + ((i * 5) % 11) - 5
    local h = {}
    for t = 1, 12 do h[t] = EX.current[res] + math.floor(3 * math.sin(i + t / 2)) end
    EX.history[res] = h
end

ok("bind_race", EX.bind_race)
print("build", pcall(EX.build_panel))
@@SCENE@@

local function shown(c)
    while c do if not c.vis then return false end c = c.parent end
    return true
end
local function esc(s) return (string.gsub(tostring(s or ""), "[\t\n]", " ")) end
local function emit(c, depth)
    if not shown(c) then return end
    print(table.concat({ "C", depth, c.xid, c.name, c.x, c.y, tostring(c.w), tostring(c.h),
        esc(c.states.standard), esc(c.img), tostring(c.disabled), esc(c.tip),
        c.parent and c.parent.name or "", tostring(c.shader),
        c.svars and (c.svars[1] .. "," .. c.svars[2]) or "" }, "\t"))
    for _, k in ipairs(c.order) do emit(k, depth + 1) end
end
for _, k in ipairs(ROOT.order) do if k ~= OPENER then emit(k, 0) end end
print("OPENER\t" .. esc(EX.button_tip()))
local s = {}
for k in pairs(STUBBED) do s[#s + 1] = k end
table.sort(s)
print("STUBBED\t" .. table.concat(s, ","))
"""

# Each scene: its Lua, then the callouts to draw as (row component or "", cell, side).
SCENES = {
    "offer": (r"""
give("res_rom_iron", 120)                 -- a tithe of 90 is due and can be paid
give("res_gems", 45)                      -- an offering's favour still running
give("res_rom_timber", 40)                -- enough for an offering
give("res_rom_wine", 12)                  -- not enough
EX.offer_until = { res_gems = 13 }
EX.demand_res, EX.demand_tier, EX.demand_due = "res_rom_iron", "hunger", 12
EX.mode = EX.MODE_OFFER
ok("layout", EX.layout)
ok("refresh", EX.refresh_panel)
""", [("gems", "btn_buy", "right"), ("rom_iron", "btn_buy", "right"),
      ("rom_wine", "btn_buy", "right")],
        "Offerings, a tithe of Iron due, favour running on Gems, Timber ready"),
    "trade": (r"""
give("res_rom_iron", 340)                 -- between stockpile levels 2 and 3
give("res_gems", 4)                       -- under one lot: Sell greys
give("res_rom_timber", 25)
give("res_spices", 110)
EX.mode = EX.MODE_TRADE
ok("layout", EX.layout)
ok("refresh", EX.refresh_panel)
""", [("gems", "btn_sell", "right"), ("rom_iron", "row_hold", "right")],
        "Trade, Held tooltip on Iron, Sell greyed on Gems (4 held, a lot is 10)"),
    "log": (r"""
give("res_rom_iron", 30)
give("res_gems", 4)
give("res_rom_timber", 60)
TURN = 8
ok("rent", EX.charge_carry)
TURN = 9
ok("offering", EX.apply_offer, "res_rom_timber")
TURN = 10
give("res_spices", 400)
ok("tithe", EX.fire_demand)
TREASURY.player = 7 * EX.buy_price("res_rom_iron") + 500
ok("bulk_buy", EX.bulk_trade, "res_rom_iron" .. EX.ORD_FS .. "25", true)
ok("bulk_sell", EX.bulk_trade, "res_gems" .. EX.ORD_FS .. "5", false)
EX.deals = { { fac = "a", res = "res_gems", side = "sell", lots = 1, px = 900, turn = 10 },
             { fac = "b", res = "res_rom_wine", side = "buy", lots = 2, px = 700, turn = 10 } }
EX.mode = EX.MODE_LOG
ok("layout", EX.layout)
ok("refresh", EX.refresh_panel)
""", [("", "OPENER", "left")],
        "Log after a turn: rent, an offering, a tithe, a partly filled x25 buy, a refused sell"),
}


def _tree(fname):
    t = io.open(os.path.join(PG.OURS, fname), encoding="utf-8").read()
    h = t[t.index("<hierarchy>"):t.index("</hierarchy>")]
    stack, top = [], None
    for m in re.finditer(r"<(/?)([A-Za-z0-9_]+)[^>]*?(/?)>", h):
        close, tag, selfc = m.groups()
        if tag == "hierarchy":
            continue
        if close:
            stack.pop()
            continue
        node = [tag, []]
        if stack:
            stack[-1][1].append(node)
        else:
            top = node
        if not selfc:
            stack.append(node)
    return top[1][0]


def _lua_tree(n):
    return '{"%s",{%s}}' % (n[0], ",".join(_lua_tree(k) for k in n[1]))


def _docs():
    """Each XML component by id: its Document, the component and its standard state."""
    model, _r = PG._studio()
    out = {}
    for kind, f in FILES.items():
        d = model.Document(io.open(os.path.join(PG.OURS, f), encoding="utf-8").read())
        for c in d.components:
            out.setdefault(c.get("id", c.tag), (d, c, d.state(c)))
    return out


def snapshot(scene):
    """Run one scene through the shipped Lua. Returns (components, opener tip, stubbed, errors)."""
    docs = _docs()
    size = ",".join('["%s"]={%s,%s}' % (k, st.get("width"), st.get("height"))
                    for k, (_d, _c, st) in docs.items() if st is not None)
    trees = "{panel=%s,row=%s,size={%s}}" % (_lua_tree(_tree(FILES["panel"])),
                                              _lua_tree(_tree(FILES["row"])), size)
    src = (DRIVER.replace("@@TREES@@", trees).replace("@@LUA@@", LUA)
           .replace("@@SW@@", str(SCREEN[0])).replace("@@SH@@", str(SCREEN[1]))
           .replace("@@SCENE@@", SCENES[scene][0]))
    fd, tmp = tempfile.mkstemp(suffix=".lua")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(src)
    try:
        run = subprocess.run([LUA_EXE, tmp], capture_output=True, text=True, encoding="utf-8")
    finally:
        os.remove(tmp)
    if run.returncode:
        raise SystemExit("scene %s: lua failed:\n%s" % (scene, run.stderr))
    comps, tip, stubbed, errs = [], "", [], []
    for line in run.stdout.splitlines():
        f = line.split("\t")
        if f[0] == "C":
            comps.append(dict(depth=int(f[1]), xid=f[2], name=f[3], x=float(f[4]), y=float(f[5]),
                              w=None if f[6] == "nil" else float(f[6]),
                              h=None if f[7] == "nil" else float(f[7]),
                              text=f[8], img=f[9] or None, disabled=f[10] == "true",
                              tip=f[11], parent=f[12],
                              # set_greyscale_t0's two values: greyscale 0-1, alpha 0-1
                              grey=tuple(float(v) for v in f[14].split(","))
                              if f[13] == "set_greyscale_t0" and f[14] else None))
        elif f[0] == "OPENER":
            tip = f[1]
        elif f[0] == "STUBBED":
            stubbed = [s for s in f[1].split(",") if s]
        elif f[0] == "ERR":
            errs.append("%s: %s" % (f[1], f[2]))
        elif f[0] == "build" and f[1:] != ["true", "true"]:
            errs.append("build_panel: " + " ".join(f[1:]))
    return comps, tip, stubbed, errs


# CA's [[col:]] names, from db/ui_colours_tables via preview_guilds_panel.py.
MARKUP = PG.MARKUP
INK = PG.INK


def _rgba(hexs, default=(255, 248, 215, 255)):
    if not hexs or not hexs.startswith("#"):
        return default
    h = hexs[1:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6)) if len(h) == 8 else default


def render(scene, path=None):
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps
    from pathlib import Path
    model, rendering = PG._studio()
    docs = _docs()
    comps, opener_tip, stubbed, errs = snapshot(scene)
    extra = sorted({c["img"] for c in comps if c["img"]})
    _n, missing = PG.extract_art(PREFIX, extra)

    canvas = Image.new("RGBA", SCREEN, (14, 12, 10, 255))
    draw = ImageDraw.Draw(canvas)
    fonts = {}

    def font(size, bold=False):
        key = (size, bold)
        if key not in fonts:
            fonts[key] = ImageFont.truetype(FONT_B if bold else FONT, size)
        return fonts[key]

    def art(p):
        return Path(os.path.join(PG.UI, os.path.relpath(p, "ui").replace("/", os.sep)))

    def paste_images(c, x, y, w, h):
        d, comp, st = docs.get(c["xid"], (None, None, None))
        if st is None:
            return
        images = {}
        box = comp.child("componentimages")
        if box is not None:
            for n in box.children:
                images[n.get("this")] = n.get("imagepath")
        metrics = st.child("imagemetrics")
        if metrics is None:
            return
        layer = Image.new("RGBA", SCREEN, (0, 0, 0, 0))
        xw, xh = float(st.get("width") or w), float(st.get("height") or h)
        for i, n in enumerate(metrics.children):
            p = images.get(n.get("componentimage"))
            if not p:
                continue
            if i == 0 and c["img"]:
                p = c["img"]          # SetImagePath(path, 0) repaints image 0
            a = art(p)
            if not a.is_file():
                continue
            # AN IMAGE THE SAME SIZE AS ITS STATE FOLLOWS A RESIZE; a smaller one (a glyph on
            # a button) keeps its own size and sits centred, which is how these files draw.
            iw, ih = float(n.get("width") or xw), float(n.get("height") or xh)
            if abs(iw - xw) < 1 and abs(ih - xh) < 1:
                iw, ih, ox, oy = w, h, 0, 0
            else:
                ox, oy = (w - iw) / 2, (h - ih) / 2
            img = rendering.raster(a, max(1, int(iw)), max(1, int(ih)), n)
            # The Next arrow is the Previous glyph with x_flipped - CA's own idiom.
            if n.get("x_flipped") == "true":
                img = ImageOps.mirror(img)
            if n.get("y_flipped") == "true":
                img = ImageOps.flip(img)
            layer.alpha_composite(img, (int(x + ox), int(y + oy)))
        if c.get("grey"):
            amount, alpha = c["grey"]
            layer = ImageEnhance.Color(layer).enhance(1 - amount)
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
        canvas.alpha_composite(layer)

    def ink(x, y, text, f, base, clip_w=None):
        pos, colour = 0, base
        plain = MARKUP.sub("", text)
        if clip_w is not None and draw.textlength(plain, font=f) > clip_w:
            while plain and draw.textlength(plain + "...", font=f) > clip_w:
                plain = plain[:-1]
            text = plain + "..."
        for m in MARKUP.finditer(text):
            seg = text[pos:m.start()]
            draw.text((x, y), seg, fill=colour, font=f)
            x += draw.textlength(seg, font=f)
            colour = base if m.group(1) else INK.get(m.group(2), base)
            pos = m.end()
        draw.text((x, y), text[pos:], fill=colour, font=f)

    def text_of(c, x, y, w, h):
        if not c["text"]:
            return
        d, comp, st = docs.get(c["xid"], (None, None, None))
        ct = st.child("component_text") if st is not None else None
        if ct is None:
            return
        size = int(float(ct.get("font_m_size") or 12))
        col = _rgba(ct.get("font_m_colour"))
        if c.get("grey"):
            lum = int(0.3 * col[0] + 0.59 * col[1] + 0.11 * col[2])
            col = (lum, lum, lum, int(255 * c["grey"][1]))
        ox = model.pair(ct.get("textxoffset"), (0, 0))[0]
        f = font(size)
        tw = draw.textlength(MARKUP.sub("", c["text"]), font=f)
        align = (ct.get("texthalign") or "Left").lower()
        tx = x + ox if align == "left" else (x + w - tw - ox if align == "right" else x + (w - tw) / 2)
        ty = y + (h - size) / 2 - 3
        ink(max(tx, x), ty, c["text"], f, col, clip_w=w - ox if align == "left" else w)

    boxes = {}
    for c in comps:
        d, comp, st = docs.get(c["xid"], (None, None, None))
        w = c["w"] if c["w"] is not None else float(st.get("width") or 0) if st is not None else 0
        h = c["h"] if c["h"] is not None else float(st.get("height") or 0) if st is not None else 0
        # A cell place() widened keeps its XML HEIGHT: the stub answers Dimensions() with it.
        paste_images(c, c["x"], c["y"], w, h)
        text_of(c, c["x"], c["y"], w, h)
        boxes[(c["parent"], c["name"])] = (c["x"], c["y"], w, h, c["tip"])

    GOLDEN = (200, 160, 90, 255)
    BW = 316                          # a margin is (1600 - 920) / 2 = 340px wide

    def badge(x, y, n):
        draw.ellipse([x - 10, y - 10, x + 10, y + 10], fill=GOLDEN)
        draw.text((x, y), str(n), fill=(20, 16, 12, 255), font=font(13, True), anchor="mm")

    def tooltip(n, tip, anchor, side, floor):
        """CA's tooltip shape - title, then the body wrapped - set in a margin, numbered to
        match a badge on the cell it belongs to, so it covers none of the panel."""
        title, _s, body = tip.partition("||")
        if not _s:
            title, body = "", tip
        tf, bf = font(14, True), font(13)

        def wrap(text, f):
            lines, cur = [], ""
            for word in text.split():
                t = (cur + " " + word).strip()
                if draw.textlength(t, font=f) > BW - 44 and cur:
                    lines.append(cur)
                    cur = word
                else:
                    cur = t
            return lines + [cur] * bool(cur)
        heads, lines = wrap(title, tf), wrap(body, bf)
        bh = 16 + 20 * len(heads) + 4 * bool(heads) + 18 * len(lines)
        ax, ay, aw, ah = anchor
        bx = SCREEN[0] - BW - 12 if side == "right" else 12
        by = max(floor, min(SCREEN[1] - bh - 40, ay + ah / 2 - bh / 2))
        draw.rectangle([ax - 2, ay - 2, ax + aw + 2, ay + ah + 2], outline=GOLDEN, width=2)
        badge(ax + aw + 2, ay - 2, n)
        draw.rectangle([bx, by, bx + BW, by + bh], fill=(24, 20, 16, 245),
                       outline=(150, 120, 70, 255), width=2)
        badge(bx + 16, by + 16, n)
        y = by + 8
        for ln in heads:
            draw.text((bx + 32, y), ln, fill=(255, 211, 122, 255), font=tf)
            y += 20
        y += 4 * bool(heads)
        for ln in lines:
            draw.text((bx + 32, y), ln, fill=(235, 225, 200, 255), font=bf)
            y += 18
        return by + bh + 12

    shown_tips = []
    floors = {"left": 12, "right": 12}
    for n, (row, cell, side) in enumerate(SCENES[scene][1], 1):
        if cell == "OPENER":
            # The opener lives on the HUD. It is drawn in the margin above its own tooltip,
            # not where EX.place_button puts it.
            bx = 12 + BW // 2 - 24 if side == "left" else SCREEN[0] - 12 - BW // 2 - 24
            fake = dict(xid=PREFIX + "button", img=None, disabled=False, grey=None)
            paste_images(fake, bx, 60, 48, 48)
            draw.text((bx - 10, 84), "HUD button", fill=(150, 140, 120, 255), font=font(12),
                      anchor="rm")
            floors[side] = tooltip(n, opener_tip, (bx, 60, 48, 48), side, 60 + 48 + 20)
            shown_tips.append(opener_tip)
            continue
        hit = boxes.get((PREFIX + "row_" + row, cell))
        if hit and hit[4]:
            floors[side] = tooltip(n, hit[4], hit[:4], side, floors[side])
            shown_tips.append(hit[4])

    draw.text((16, SCREEN[1] - 28), SCENES[scene][2] + ".   Drawn offline by tools/preview_exchange.py "
              "from the shipped Lua; glyphs approximate.", fill=(150, 140, 120, 255), font=font(13))
    out = path or os.path.join(PG.CACHE, "ex_%s.png" % scene)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    canvas.convert("RGB").save(out)
    return out, comps, shown_tips, stubbed, errs, missing


def selftest():
    """Each scene ran without a Lua error and drew the thing it exists to show."""
    fails = []
    got = {}
    for scene in SCENES:
        comps, tip, stubbed, errs = snapshot(scene)
        got[scene] = (comps, tip)
        fails += ["%s: %s" % (scene, e) for e in errs]
    def cell(scene, row, name):
        for c in got[scene][0]:
            if c["parent"] == PREFIX + "row_" + row and c["name"] == name:
                return c
        return None
    b = cell("offer", "rom_iron", "btn_buy")
    if not (b and b["text"] == "Pay tithe" and not b["disabled"]):
        fails.append("offer: the tithe row's button is %r" % ((b and (b["text"], b["disabled"])),))
    s = cell("trade", "gems", "btn_sell")
    if not (s and s["disabled"] and s["grey"]):
        fails.append("trade: Sell on 4 Gems is not greyed (disabled and wearing the greyscale)")
    names = " ".join(c["text"] for c in got["log"][0] if c["name"] == "row_trend")
    for want in ("Warehouse rent", "Offered", "demands", "of 25 lots", "Sell refused"):
        if want not in names:
            fails.append("log: no line containing %r" % want)
    if "deals are waiting" not in got["log"][1]:
        fails.append("log: the opener's tooltip does not name the deals: %r" % got["log"][1])
    for f in fails:
        print("FAIL", f)
    print("selftest %s: %d scenes" % ("ok" if not fails else "FAILED", len(SCENES)))
    return not fails


def main(argv):
    if "--selftest" in argv:
        return 0 if selftest() else 1
    for scene in SCENES:
        out, comps, tips, stubbed, errs, missing = render(scene)
        print("%s  (%d components, %d tooltips)" % (out, len(comps), len(tips)))
        for e in errs:
            print("  LUA ERROR", e)
        if stubbed:
            print("  no-op stubs reached:", ", ".join(stubbed))
        if missing:
            print("  art not found:", ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
