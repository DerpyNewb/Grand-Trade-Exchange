"""Generate the Zharr Exchange's three .twui.xml files.

    py tools/gen_exchange_ui.py            # writes them
    py tools/gen_exchange_ui.py --check    # build only, write nothing
    py tools/gen_exchange_ui.py --selftest

WHY GENERATED. A GUID that collides with another file, or one that appears in <components>
with no matching node in <hierarchy>, is a SILENT non-draw - no error, no log line, the widget
simply never appears. The sparkline alone is 12 bar components per row. Hand-writing that is
how you get a collision, so the GUIDs are assigned by a counter here and the selftest asserts
every one is unique and paired.

GUID RANGES, so nothing here can collide with what already ships:
    DE14xxxx  derpy_chd_rite_costs / _totals / _fire   (the commission panel widgets)
    DE15xxxx  RETIRED - was derpy_chd_ex_delta, deleted 2026-09-09. Do not reuse.
    DE16xxxx  derpy_chd_exchange_panel                 <- this file
    DE17xxxx  derpy_chd_exchange_row                   <- this file
    DE18xxxx  derpy_chd_exchange_button                <- this file
    GG21xxxx  derpy_gg_panel / _card / _row            (The Great Guilds, claimed 2026-09-10,
                                                        owned by tools/gen_guilds_ui.py)
"""
import io
import re
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "Modding Files", "pack", "ui", "campaign ui")

SPARK_BARS = 12       # sparkline width, in turns of history
# THE DEEP CHART on Trade page 2. Must match EX.DEEP_BARS in the campaign script - the Lua
# indexes cbar_00..cbar_39 by name, so a mismatch is a chart that silently draws short or
# reaches for a component that does not exist. selftest() pins the two together.
DEEP_BARS  = 40
# 20 AND 16, NOT 21 AND 17. The plot gave up 66px off its left edge for the y scale, so
# the pitch had to come down to keep 40 bars inside the panel: CHART_LEFT + 40*20 = 886
# against a content edge at 900. 4px of air between bars either way.
CHART_PITCH = 20
CHART_BAR_W = 16
CHART_H     = 300
CHART_TOP   = 110
# THE PLOT'S LEFT EDGE, and the gutter left of it that the y scale is right-aligned into
# (20..80, then 6px of air). The bars used to start at 20; a y label inside the plot would
# be legible for the first twenty turns and then sit under a bar forever.
CHART_LEFT  = 86
CHART_GUT   = 60
# THE SHORTEST BAR A LOW PRICE DRAWS, so the lowest rung in the window is still visible
# rather than a zero-height nothing. It is also why the LOW gridline is at CHART_H - 6 and
# not at CHART_H: the bottom of the scale is the top of that stub. Must match
# EX.CHART_FLOOR - check_chart_geometry pins all six of these constants across the two
# files, because nothing else can see that the Lua and the XML disagree.
CHART_FLOOR = 6
# THE FIVE VIEWS, in the order their tabs sit across the strip. selftest() asserts this is
# exactly EX.MODES from the Lua: a tab with no mode is a dead button, a mode with no tab is a
# view the player cannot reach now that the arrows page instead of cycling.
TAB_MODES = ["trade", "stats", "offer", "houses", "deals", "log"]
TAB_W, TAB_PITCH = 108, 116

ROW_W, ROW_H = 880, 40
# 736, not 700: the last 36px are the nav strip below the two footer lines. See the
# derpy_chd_ex_prev block in build_panel() for why the nav does not share their line.
PANEL_W, PANEL_H = 920, 736

# icon_banner_bg.png is the one CA texture confirmed to actually render for us at WIDGET size -
# it is what the existing derpy rite widgets use, and it drew correctly in game.
# panel_back_border.png resolves but drew nothing, so it is not used.
#
# At PANEL size it is not enough: stretched to 900x700 it reads as no background at all
# (reported 2026-09-04). panel_back_tile.png is what CA's own panel interiors use - 204
# references in ui3.pack - and it is built to tile, so it is the panel body here.
GAME = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III"

BG = "ui/skins/default/icon_banner_bg.png"

# CA's own textures for the parts that should read as CA parts. Buttons carry no 9-slice margin
# in CA's templates - they simply stretch to the state size - so neither do ours.
BTN_BG = "ui/skins/default/button_square_large_text_active.png"
# HOVER. Every _hover texture below is the _active one's own sibling in ui/skins/default, so
# the lit state is CA's art for exactly this button rather than a tint of ours.
#
# The state machine is NOT implicit: a <hover> state the engine has no <transitionmap> edge to
# reach is simply never entered, and that is a silent non-draw of the ordinary kind. See
# _state() for the index vocabulary, read out of CA's ui/templates/round_small_button.twui.xml.
BTN_HOVER = "ui/skins/default/button_square_large_text_hover.png"
# The HUD opener. A round parchment button is what CA uses for the small standalone HUD
# buttons, and unlike a flat icon it reads as pressable at 48x48.
# The round parchment plate CA uses for standalone HUD buttons (41x42 native), with a trade
# icon laid over it. The plate alone is just a blank disc and reads as nothing.
# CA's own round HUD button chrome, not our own parchment square.
#
# Reported from play 2026-09-06: "the button looks low quality". It was
# parchment_button_round_active.png 9-sliced with margin 8 - a flat pale plate that reads as a
# square next to the bronze rings CA uses for every other HUD button.
#
# button_round_medium_* is THE standard: 555 uses of _active across ui3.pack, against 0 for the
# parchment one on any HUD button. underlay goes down first (it is the base plate CA draws
# beneath every round button), then the frame, then our own logo on top - the logo is unchanged,
# which is what was asked for.
#
# MARGIN 0 ON BOTH, deliberately. A 9-slice margin on a ROUND texture stretches its middle and
# pins its corners, which is exactly how a circle turns into a squarish blob - the old margin 8
# is half of why this read as low quality.
OPENER_LAYERS = [
    {"path": "ui/skins/default/button_round_medium_underlay.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
    {"path": "ui/skins/default/button_round_medium_active.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
    {"path": "ui/skins/default/icon_trade.png",
     "offset": (10, 10), "dw": -20, "dh": -20, "margin": 0, "dock": "Center"},
]
# The underlay and the logo are unchanged; only the plate between them lights.
OPENER_HOVER = [
    {"path": "ui/skins/default/button_round_medium_underlay.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
    {"path": "ui/skins/default/button_round_medium_hover.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
    {"path": "ui/skins/default/icon_trade.png",
     "offset": (10, 10), "dw": -20, "dh": -20, "margin": 0, "dock": "Center"},
]
# A 1x1 white pixel, stretched and tinted. The sparkline bars used icon_banner_bg (127x29 of
# decorative banner), and a 7x14 slice of that reads as a faint dot, not a bar - which is what
# made the "Last 12 turns" column look broken rather than flat.
BAR_BG = "ui/skins/default/1x1_blank_white.png"
BAR_COLOUR = "#C8A05AFF"
# THE GRIDLINES, the bar gold at a third alpha. #RRGGBBAA - alpha LAST; a four-digit tail
# read as RGB would be a colour rather than a fade, and nothing would say so.
GRID_COLOUR = "#C8A05A55"

# CA sound categories, counted out of ui3.pack so every one is real:
#   UI_GBL_HUD_Purchase                    generic buy
#   UI_GBL_TMP_Square_Large_Text_Button    the click that goes with BTN_BG (39 uses)
#   UI_GBL_TMP_Round_Medium_Button         a 48px round HUD button (38 uses)
#   UI_GBL_TMP_Round_Small_Button          a small round button (232 uses)
# The panel has no open/close sound of its own - it is not an animated CA panel - so opening
# and closing are heard as the opener's and the close button's own clicks, which is what a
# player actually hears anyway.
SND_BUY = "UI_GBL_HUD_Purchase"
SND_SELL = "UI_GBL_TMP_Square_Large_Text_Button"
SND_OPEN = "UI_GBL_TMP_Round_Medium_Button"
SND_CLOSE = "UI_GBL_TMP_Round_Small_Button"
# Placeholder only. Lua rewrites this per row with the resource's own icon_filepath, read
# straight out of CA's resources_tables - see EX.INFO in zzz_derpy_chd_exchange.lua.
ICON_BG = "ui/campaign ui/effect_bundles/resource_gold.png"
# CA's close button is a round plate plus a cross glyph - see button_close in
# ui/campaign ui/search_panel.twui.xml. button_icon_close_24.png, which this used to name,
# DOES NOT EXIST in any shipped pack; a missing texture renders as a blank white square, which
# is exactly what it drew. selftest() now checks every imagepath against the game's packs.
CLOSE_LAYERS = [
    {"path": "ui/skins/default/button_round_small_active.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
    {"path": "ui/skins/default/icon_cross_small.png",
     "offset": (5, 5), "dw": -10, "dh": -10, "margin": 0, "dock": "Center"},
]
CLOSE_HOVER = [
    {"path": "ui/skins/default/button_round_small_hover.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
    {"path": "ui/skins/default/icon_cross_small.png",
     "offset": (5, 5), "dw": -10, "dh": -10, "margin": 0, "dock": "Center"},
]
# THE GUIDE BUTTON. Same round_small plate as close_button, so it reads as a control of the
# same rank, with CA's own question-mark glyph on it - ui/skins/default/icon_question_mark.png,
# which ships (12 question-mark textures exist across the skins; this is the neutral one).
# Only the plate swaps on hover, exactly as close_button does: the glyph has no _hover sibling.
HELP_LAYERS = [
    {"path": "ui/skins/default/button_round_small_active.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
    {"path": "ui/skins/default/icon_question_mark.png",
     "offset": (6, 6), "dw": -12, "dh": -12, "margin": 0, "dock": "Center"},
]
HELP_HOVER = [
    {"path": "ui/skins/default/button_round_small_hover.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
    {"path": "ui/skins/default/icon_question_mark.png",
     "offset": (6, 6), "dw": -12, "dh": -12, "margin": 0, "dock": "Center"},
]
# THE VIEW NAVIGATION ARROWS. Round plate plus a bare glyph, exactly like close_button and
# btn_help, because they are controls of the same rank and sit in the same right-hand column.
#
# NOT button_cycle_arrow_active.png, which is what shipped first. That file is not a glyph -
# ui/templates/cycle_button_arrow_next.twui.xml names it and nothing else, so it is the WHOLE
# button: an arrow-shaped red plate with its own bronze border, 49x45. Laid over a second plate
# it read as a red slab with a small mark on it (screenshotted 2026-09-07, "make the buttons
# circular"). button_indicator_arrow_active.png is the same kind of thing.
#
# icon_credits_back.png is a flat bronze triangle pointing LEFT on transparency, 56x56 - the
# same family as icon_cross_small and icon_question_mark, which is why it sits on the round
# plate the way those two do. Flipped, it is the forward arrow; see _flipped().
MODE_LAYERS = [
    {"path": "ui/skins/default/button_round_small_active.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
    {"path": "ui/skins/default/icon_credits_back.png",
     "offset": (6, 6), "dw": -12, "dh": -12, "margin": 0, "dock": "Center"},
]
# Only the plate lights, as on close_button and btn_help: the glyph has no _hover sibling.
MODE_HOVER = [
    {"path": "ui/skins/default/button_round_small_hover.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
    {"path": "ui/skins/default/icon_credits_back.png",
     "offset": (6, 6), "dw": -12, "dh": -12, "margin": 0, "dock": "Center"},
]


# LEFT AND RIGHT OUT OF ONE TEXTURE. CA ships no mirrored arrow anywhere:
# ui/templates/cycle_button_arrow_next.twui.xml and cycle_button_arrow_previous.twui.xml (read
# out of ui3.pack) name the SAME imagepaths and differ by exactly one attribute -
# x_flipped="true" on the next template's <image> metrics. Our glyph points LEFT unflipped, so
# MODE_LAYERS above is the PREVIOUS button and the flipped copy is Next.
#
# Only the glyph flips. The plate under it is symmetric, so mirroring that as well would be a
# no-op that still doubled the number of things that can be wrong.
def _flipped(layers):
    out = []
    for i, lay in enumerate(layers):
        lay = dict(lay)
        if i:
            lay["flip"] = True
        out.append(lay)
    return out


NEXT_LAYERS = _flipped(MODE_LAYERS)
NEXT_HOVER = _flipped(MODE_HOVER)
# TOOLTIPS ARE LITERAL TEXT HERE, NOT A {{tr:}} LOC KEY, and the "||" is why.
#
# "Title||Body" is how CA splits a tooltip's title from its body, and a long tooltip without the
# split renders in a box that does not grow - ours clipped mid-glyph on line two. But routing the
# same string through a loc key printed the pipes VERBATIM on screen (screenshotted twice,
# 2026-09-04 and again 2026-09-05 after a first fix that only moved the text around).
#
# The difference is the resolver. CA's `{{tr:X}}` is a TEXT REPLACEMENT lookup, not a plain
# translate - it resolves `ui_text_replacements_localised_text_X`, and whatever consumes that
# table is what applies the split. A bare loc key of our own reaches the tooltip by some other
# path that does no such processing, so the pipes survive to the screen.
#
# CA's own split is 1,076 literal values against 178 `{{tr:}}` ones, so literal text is both the
# majority route and the one with no indirection to get wrong. The cost is that these strings are
# not localisable; that is the trade, and it is why they live here rather than in the loc.
# THE LAST SENTENCE IS THE AI-TURN GATE EXPLAINING ITSELF, and it lives HERE rather than in a
# runtime SetTooltipText. The gate greys the button between FactionTurnEnd and
# FactionTurnStart (EX.gate_button), and a greyed control with no reason reads as a bug.
# Swapping the tooltip at runtime was the obvious version and it is the risky one: TIP_OPEN
# carries CA's Title||Body split, which is proven only as literal XML, and writing it back
# through SetTooltipText might draw the pipes (wh3-tooltip-pipe-split-needs-literal-text).
# As a permanent line it needs no setter, no state to restore, and it teaches the rule
# BEFORE the player meets it rather than only once they are already blocked.
# check_ai_turn_gate() refuses to let the gate and this sentence part company.
# THE TITLE LINE IS RACE-NEUTRAL, and this string is only a FALLBACK now. The panel serves
# four races and this text is static, so it said "The Zharr Exchange" to a Skaven player
# (screenshot, 2026-09-08). EX.button_tip() overwrites the whole tooltip at runtime with the
# player's own market name; what is left here is what shows if that setter never runs.
#
# THE BODY MUST MATCH EX.TIP_OPEN_BODY in zzz_derpy_chd_exchange.lua word for word -
# check_button_tip() in gen_zharr_exchange.py fails the build if the two drift.
TIP_OPEN = ("The Exchange||Buy and sell the world's trade goods at prices set by how "
            "scarce they are on the map, and by who controls them. Closed while the other "
            "powers take their turn.")
# TWO BUTTONS NOW, NOT ONE CYCLE. The single arrow only ever went forwards, so reaching
# the view one to the left cost three clicks, and a player who overshot had no way back.
# The page counter between them is what makes "one to the left" a thing you can see
# rather than count out.
TIP_MODE = ("Next view||Trading, ownership, offerings and houses: who produces each "
            "commodity, who controls it, and what that control adds to the price.")
TIP_PREV = ("Previous view||Back one. The four trading views wrap, so this reaches the "
            "last of them from the first.")
TIP_TAB = "Switch to this view."
# A PAGE COUNTER SINCE THE TABS ARRIVED, not a view counter - it read "the four trading views"
# for a year of six tabs. The arrows either side of it carry runtime tooltips; this one does not.
TIP_PAGE = ("Page||Which page of this view you are on. The arrows either side of it turn the "
            "page; the tabs below change the view.")
TIP_CLOSE = "Close"
TIP_HELP = ("What the panel means||Every column, symbol and view explained, with what holding "
            "goods costs and what it earns.")
TIP_BUY = ("Buy a lot||Bought at the price shown. Buying repeatedly drives this commodity's "
           "price up.")
# The 10% is EX.SPREAD in zzz_derpy_chd_exchange.lua. It is named here because the Price
# column shows the BUY price only, so without this line the panel would be lying about
# what a sale pays - the one invariant this UI has held from the start.
# The 10% is no longer spelled out here: the Sell column shows the actual figure, and a
# tooltip repeating a number that is already on the row is one more place for it to go stale.
TIP_SELL = ("Sell a lot||Sold at the Sell price, which is under the Buy price. The exchange "
            "keeps the difference, so a round trip cannot mint gold.")

# THE ORDER TICKET'S OWN FOUR TOOLTIPS. Literal text for the same reason every tooltip above
# is: {{tr:}} prints the "||" title split as two literal pipes (see the block above TIP_OPEN).
TIP_ORD_SIDE = "Buy or sell||Switch this standing order between buying and selling."
TIP_ORD_CMP = ("At or below / at or above||Whether the order fires once the price falls to "
               "this level, or once it rises to it.")
TIP_ORD_STEP = ("Adjust the price||Move the order's target one rung up or down the same "
                "ladder every price on this board sits on.")
TIP_ORD_PLACE = ("Place the order||Stands until the price crosses the level shown, then "
                  "fills automatically on a later turn.")
TIP_AMOUNT = ("Amount per click||How many lots a Buy or Sell moves, and the size a new "
              "standing order is placed at. Cycles 1, 5, 10, 25; the - and + beside it step "
              "one lot at a time. A lot is 10 of a commodity, 100 of Armaments or Raw "
              "Materials, 5 of a house share.")
TIP_AMOUNT_STEP = ("One lot at a time||The button between these cycles the round sizes. "
                   "Use these to reach the ones in between.")

DIVIDER = "ui/skins/default/1x1_blank_white.png"
DIVIDER_COLOUR = "#6B583680"

# THE PANEL BACKGROUND IS TWO LAYERS WITH 9-SLICE MARGINS, copied from CA's own
# ui/templates/panel_frame.twui.xml. Do not simplify it back to one image.
#
# `margin` is the 9-slice inset: it tells the engine which border of the texture must NOT be
# stretched or repeated. With margin="0,0,0,0" - what this generator emitted first - a tiled
# texture repeats raw, and panel_back_tile.png's transparent edge then shows through as a grid
# of seams across the panel. Screenshotted 2026-09-04; it read as floating blocks, not a panel.
#
# CA's recipe at 418x530: border at full size margin 30, body inset 9,3 at margin 5, priority 60.
# Scaled to our size below.
PANEL_LAYERS = [
    # FULL SIZE, no dockpoint. CA insets its body by (9,3) inside a 418x530 frame, but CA also
    # relies on dockpoint="Center" meaning "centre it" - here the two are CUMULATIVE, so the
    # body was shifted 18 right and 6 down and left a bare strip along the right and bottom
    # edges (screenshotted 2026-09-04). The border draws after the body and covers the overlap,
    # so filling the whole component is safe and cannot gap.
    {"path": "ui/skins/default/panel_back_tile.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 5, "tile": True, "dock": None},
    {"path": "ui/skins/default/panel_back_border.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 30, "tile": True, "dock": None},
]


class C(object):
    """One component. Children are nested in the hierarchy and flat in <components>."""

    def __init__(self, name, w, h, **kw):
        self.name, self.w, self.h, self.kw = name, w, h, kw
        self.kids = []
        self.gid = None
        self.sid = None

    def add(self, child):
        self.kids.append(child)
        return child

    def walk(self):
        yield self
        for k in self.kids:
            for d in k.walk():
                yield d


def assign(root, prefix):
    """Two GUIDs per component - the component and its standard state - from one counter."""
    n = [0]

    def guid():
        n[0] += 1
        return "%s%04X-D000-4000-B%015X" % (prefix, n[0], n[0])

    for c in root.walk():
        c.gid = guid()
        c.sid = guid()
        # A THIRD GUID PER COMPONENT, always minted even where no hover is authored. Handing
        # them out unconditionally keeps the counter - and therefore every GUID in the file -
        # independent of which components happen to carry a hover this build, so adding one
        # later does not renumber the rest.
        c.hid = guid()
    return root


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def hierarchy(c, depth=2):
    tab = "\t" * depth
    if not c.kids:
        return '%s<%s this="%s"/>\n' % (tab, c.name, c.gid)
    out = '%s<%s this="%s">\n' % (tab, c.name, c.gid)
    for k in c.kids:
        out += hierarchy(k, depth + 1)
    out += "%s</%s>\n" % (tab, c.name)
    return out


def _spec(kw, key):
    """The image layer list for one state. `image` is shorthand for a single standard layer."""
    if kw.get(key):
        return list(kw[key])
    if key == "layers" and kw.get("image"):
        return [{"path": kw["image"], "offset": (0, 0), "dw": 0, "dh": 0,
                 "margin": kw.get("imagemargin", 0), "colour": kw.get("colour_img"),
                 "tile": kw.get("tile", False), "dock": None}]
    return []


def _state(c, name, sguid, entries, target):
    """One <state> block. `entries` are (componentimage guid, metrics guid, layer) tuples.

    `target` is the state GUID this one transitions to, or None for a component with only the
    one state.

    THE TRANSITION MAP IS WHAT MAKES HOVER WORK, and authoring the extra state without it is
    the silent failure here - the state exists, the engine has no edge to reach it by, and the
    button simply never lights. The index vocabulary is read out of CA's own
    ui/templates/round_small_button.twui.xml, whose active state carries an index-less
    transition to hover and whose hover state carries index="1" back to active:
        (omitted) = 0  mouse enters
        1              mouse leaves
        2              mouse down
    Only 0 and 1 are used here. A press state would need 2 and its own texture, and the button
    already has a click sound, so it buys nothing.
    """
    kw = c.kw
    st = ['this="%s"' % sguid, 'name="%s"' % name,
          'width="%d"' % c.w, 'height="%d"' % c.h]
    if kw.get("interactive"):
        st.append('interactive="true"')
    # NO dockpoint / dock_offset. MEASURED 2026-09-04: the engine ignores both on these
    # runtime-created components - every child rendered at its parent's origin, stacked, so only
    # the last-drawn one was visible. uicomponent:MoveTo works, so EX.layout() in
    # zzz_derpy_chd_exchange.lua positions every component explicitly. The same is true of
    # SetDockOffset at runtime.
    st.append('uniqueguid="%s"' % sguid)
    out = "\t\t\t\t<%s\n\t\t\t\t\t%s>\n" % (name, "\n\t\t\t\t\t".join(st))

    if entries:
        out += "\t\t\t\t\t<imagemetrics>\n"
        for cig, mg, lay in entries:
            ox, oy = lay.get("offset", (0, 0))
            dock = lay.get("dock", "Center")
            out += ('\t\t\t\t\t\t<image\n\t\t\t\t\t\t\tthis="%s"\n'
                    '\t\t\t\t\t\t\tuniqueguid="%s"\n\t\t\t\t\t\t\tcomponentimage="%s"\n'
                    '\t\t\t\t\t\t\toffset="%.2f,%.2f"\n\t\t\t\t\t\t\twidth="%d"\n'
                    '\t\t\t\t\t\t\theight="%d"\n'
                    % (mg, mg, cig, ox, oy,
                       c.w + lay.get("dw", 0), c.h + lay.get("dh", 0)))
            if lay.get("tile"):
                out += '\t\t\t\t\t\t\ttile="true"\n'
            # MIRRORS THE GLYPH HORIZONTALLY. x_flipped, NOT flipped - the shorter name
            # is not an attribute the engine knows, and an unknown attribute is ignored
            # in silence, so the first version of this shipped two arrows pointing the
            # same way with every check green (screenshotted 2026-09-07). The name is
            # copied out of CA's own ui/templates/cycle_button_arrow_next.twui.xml,
            # where it is the ONLY difference from the previous button.
            if lay.get("flip"):
                out += '\t\t\t\t\t\t\tx_flipped="true"\n'
            if dock:
                out += '\t\t\t\t\t\t\tdockpoint="%s"\n' % dock
            if lay.get("colour"):
                out += '\t\t\t\t\t\t\tcolour="%s"\n' % lay["colour"]
            m = float(lay.get("margin", 0))
            out += '\t\t\t\t\t\t\tmargin="%.2f,%.2f,%.2f,%.2f"/>\n' % (m, m, m, m)
        out += "\t\t\t\t\t</imagemetrics>\n"

    if target:
        # index is OMITTED on the enter edge and 1 on the leave edge - CA's own shape.
        idx = "" if name == "standard" else '\n\t\t\t\t\t\t\tindex="1"'
        out += ('\t\t\t\t\t<transitionmap>\n\t\t\t\t\t\t<transition%s\n'
                '\t\t\t\t\t\t\ttransition_m_target_state="%s"/>\n'
                '\t\t\t\t\t</transitionmap>\n' % (idx, target))

    if kw.get("text"):
        # EMITTED ON EVERY STATE, not just standard. A state with no component_text draws its
        # label in the engine's default font, so a hover state missing this block changes the
        # typeface the instant the mouse arrives.
        #
        # The STRING is a separate problem and it is solved in Lua: SetStateText writes to the
        # CURRENT state only, so a dynamic label ("Buy 10") set once would leave the hover state
        # blank. EX.set_state_text walks the states and writes each. See its comment.
        out += ('\t\t\t\t\t<component_text\n'
                # texthalign is HORIZONTAL, textvalign is VERTICAL - counted in ui3.pack:
                # textvalign is Center 8734 / Bottom 219, texthalign is Center 3981 /
                # Right 631. This generator had them the other way round, and passed British
                # "Centre", which is not a value the engine accepts - an unknown value is
                # ignored in silence, so every button label sat left and high.
                '\t\t\t\t\t\ttexthalign="%s"\n\t\t\t\t\t\ttextvalign="%s"\n'
                '\t\t\t\t\t\ttextxoffset="%s"\n\t\t\t\t\t\ttextyoffset="%s"\n'
                '\t\t\t\t\t\ttexthbehaviour="Never split"\n'
                '\t\t\t\t\t\tfont_m_size="%d"\n\t\t\t\t\t\tfont_m_colour="%s"\n'
                '\t\t\t\t\t\tfont_m_leading="3"\n\t\t\t\t\t\tfontcat_name="body_%d"/>\n'
                % (kw.get("align", "Left"), kw.get("valign", "Center"),
                   kw.get("tx", "4.00,0.00"),
                   kw.get("ty", "8.00,0.00"), kw.get("size", 12),
                   kw.get("colour", "#FFF8D7FF"), kw.get("size", 12)))

    out += "\t\t\t\t</%s>\n" % name
    return out


def component(c):
    kw = c.kw
    attrs = ['this="%s"' % c.gid, 'id="%s"' % c.name, 'tooltipslocalised="true"']
    if kw.get("tooltip"):
        # literal, not {{tr:}} - see the TIP_* block for the measurement behind that
        attrs.append('componentleveltooltip="%s"' % _esc(kw["tooltip"]))
    if kw.get("priority"):
        attrs.append('priority="%d"' % kw["priority"])
    # UI sound. This is a component ATTRIBUTE (it sits beside priority in CA's own templates),
    # not a script call - common.trigger_soundevent takes a sound EVENT, and CA's UI clicks are
    # driven by these CATEGORIES instead. Names harvested from ui3.pack; an invented one is
    # silent with no error, so only use categories that actually appear there.
    if kw.get("sound"):
        attrs.append('soundcategory="%s"' % kw["sound"])
    attrs += ['uniqueguid="%s"' % c.gid,
              'currentstate="%s"' % c.sid, 'defaultstate="%s"' % c.sid]
    out = "\t\t<%s\n\t\t\t%s>\n" % (c.name, "\n\t\t\t".join(attrs))

    # ONE component_image PER LAYER OF EVERY STATE, concatenated. <componentimages> is a
    # COMPONENT-level list and each state's <imagemetrics> picks the entries it draws by GUID -
    # CA's round_small_button carries seven images and each of its eleven states references a
    # different handful. A texture used by both states therefore appears twice here, which is
    # harmless and keeps the index arithmetic below trivial.
    std_spec = _spec(kw, "layers")
    hov_spec = _spec(kw, "hover")
    layers = []
    for i, lay in enumerate(std_spec + hov_spec):
        # Two fresh guid slots per layer, well inside the -D0xx- space at these layer counts.
        layers.append((c.gid.replace("-D000-", "-D%03d-" % (i * 2 + 1)),
                       c.gid.replace("-D000-", "-D%03d-" % (i * 2 + 2)), lay))
    if layers:
        out += "\t\t\t<componentimages>\n"
        for cig, _mg, lay in layers:
            out += ('\t\t\t\t<component_image\n\t\t\t\t\tthis="%s"\n'
                    '\t\t\t\t\tuniqueguid="%s"\n\t\t\t\t\timagepath="%s"/>\n'
                    % (cig, cig, _esc(lay["path"])))
        out += "\t\t\t</componentimages>\n"

    # THE STATE LIST. One state where no hover is authored - which is every text cell, the
    # sparkline bars and the panel itself - and two where one is, wired to each other by the
    # transition map inside _state().
    out += "\t\t\t<states>\n"
    if hov_spec:
        out += _state(c, "standard", c.sid, layers[:len(std_spec)], c.hid)
        out += _state(c, "hover", c.hid, layers[len(std_spec):], c.sid)
    else:
        out += _state(c, "standard", c.sid, layers, None)
    out += "\t\t\t</states>\n\t\t</%s>\n" % c.name
    return out


def layout(root, comment):
    out = '<?xml version="1.0"?>\n<layout\n\tversion="142"\n\tcomment="%s"\n' % _esc(comment)
    out += '\tprecache_condition="">\n\t<hierarchy>\n'
    out += hierarchy(root)
    out += "\t</hierarchy>\n\t<components>\n"
    for c in root.walk():
        out += component(c)
    out += "\t</components>\n</layout>\n"
    return out


def build_panel():
    root = C("root", PANEL_W, PANEL_H)
    p = root.add(C("derpy_chd_exchange_panel", PANEL_W, PANEL_H,
                   layers=PANEL_LAYERS, priority=60))
    p.add(C("title_text", 400, 28, text=True, size=16, tx="16.00,0.00", ty="0.00,0.00"))
    p.add(C("close_button", 30, 30, interactive=True, layers=CLOSE_LAYERS, hover=CLOSE_HOVER,
            sound=SND_CLOSE,
            dockpoint="Top Right", dock_offset="-12.00,10.00",
            tooltip=TIP_CLOSE))
    # THE GUIDE. A button of its own rather than a stop on the view cycle: the guide is not a
    # view you page through while trading, and a player looking for help should not have to
    # walk past two other views to reach it. It sits beside close_button in the title bar
    # because it is a control OF the panel, not a place inside it.
    p.add(C("btn_help", 30, 30, interactive=True, layers=HELP_LAYERS,
            hover=HELP_HOVER, sound=SND_CLOSE,
            dockpoint="Top Right", dock_offset="-50.00,10.00",
            tooltip=TIP_HELP))
    # THE VIEW NAVIGATION, bottom right, on a strip of its own below both footer lines. It
    # lived in the title bar as a single forward-only cycle button until 2026-09-07: paging a
    # four-view panel one way only meant three clicks to reach the view immediately left of you
    # and no undo at all for an overshoot.
    #
    # IT DOES NOT SHARE THE FOOTER'S LINE, which is where the empty pixels actually were.
    # check_footer_bounds in gen_zharr_exchange.py measures those two lines at their worst case
    # and gets 114 and 118 characters against an 880px box at ~6.7px each; a nav cluster on the
    # same line leaves 117 characters at the very best, and this text has clipped mid-word in
    # play twice already. PANEL_H went 700 -> 736 instead, which costs nothing and risks
    # nothing.
    #
    # derpy_chd_ex_mode keeps its name through the move: the Lua click listener matches on
    # component name alone, and a name CA also uses would fire this on unrelated panels. It is
    # the NEXT button, so its glyph is the flipped one - see _flipped().
    p.add(C("derpy_chd_ex_prev", 30, 30, interactive=True, layers=MODE_LAYERS,
            hover=MODE_HOVER, sound=SND_CLOSE,
            dockpoint="Bottom Right", dock_offset="-116.00,-10.00",
            tooltip=TIP_PREV))
    # BETWEEN THE ARROWS, and Center-aligned so "1/4" and "4/4" do not shuffle sideways as the
    # player pages. Its width is the one in EX.PANEL_LAYOUT, not this one - place() resizes it.
    p.add(C("nav_page", 44, 20, text=True, size=12, colour="#C8B48CFF", align="Center",
            tx="0.00,0.00", ty="0.00,0.00",
            dockpoint="Bottom Right", dock_offset="-74.00,-15.00",
            tooltip=TIP_PAGE))
    p.add(C("derpy_chd_ex_mode", 30, 30, interactive=True, layers=NEXT_LAYERS,
            hover=NEXT_HOVER, sound=SND_CLOSE,
            dockpoint="Bottom Right", dock_offset="-14.00,-10.00",
            tooltip=TIP_MODE))
    # THE VIEW TABS, five across the empty half of the same strip. Asked for from play
    # 2026-09-07: "additional 5 buttons here for all the panels so that the player dont need
    # to scroll the panels using the two arrow buttons" - Houses was three clicks from Trade.
    #
    # NAMED AFTER THE MODE THEY SELECT, matching EX.tab_name(mode) in the Lua, so the click
    # listener maps a component straight back to a view with no second table between them.
    # selftest() asserts this list against EX.MODES, because a tab the Lua never places is a
    # button that is simply not on screen and a mode with no tab is a view with no way in.
    #
    # 108 WIDE AT 116 PITCH from x=20: the last ends at 708 and the back arrow starts at 774,
    # so the two clusters cannot touch. It was 132 on 140 for FIVE tabs, ending at 712 - a sixth
    # on that pitch would have started at 720 and run to 852, straight through both nav buttons,
    # which is why adding a view re-pitched the strip. The 8px gap between tabs is preserved.
    # The x/y here are placeholders - place() positions every one of these from the layout
    # tables in the Lua, which is where the numbers live, and selftest() pins the two together.
    tabhov = [{"path": BTN_HOVER, "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0,
               "dock": None}]
    for i, mode in enumerate(TAB_MODES):
        p.add(C("derpy_chd_ex_tab_" + mode, TAB_W, 26, interactive=True, image=BTN_BG,
                hover=tabhov, sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
                dockpoint="Bottom Left", dock_offset="%.2f,-12.00" % (20 + i * TAB_PITCH),
                tooltip=TIP_TAB))
    # ONE LABEL PER COLUMN, not one space-padded string. The font is proportional, so padded
    # spaces never line up with the row columns below; and the single header_text carried
    # ty="44.00,0.00" - a 44px text offset inside a 22px-tall box - so it drew below its own
    # component, behind the first row, and was invisible on screen (screenshotted 2026-09-04).
    # x offsets here must stay in step with EX.ROW_LAYOUT in the Lua, plus the 20px holder inset.
    # Widths must leave a gap to the NEXT column's x offset (see EX.PANEL_LAYOUT): at 60 wide
    # hdr_trend overlapped the sparkline header and drew "TrendLast 12 turns"; at 28 it clipped
    # to "Tr...". 46 fits the word and still clears hdr_spark at 384.
    #
    # ALIGNMENT AND textxoffset ARE THE ROW CELL'S, NOT A CHOICE MADE HERE. Every header shipped
    # Left with tx=0 while the numeric cells under them are Right with tx=4, so "Held / rent"
    # and "Last 12 turns" floated a column-width away from the figures they name (§7 of
    # HANDOFF_20260906_PANEL_TOOLTIPS). Copying BOTH values off the cell is what makes the two
    # boxes resolve to the same pixel, whatever textxoffset means against a Right align - and it
    # is right in all three views for free, because a cell's alignment does not change with the
    # mode. check_ui() pins each pair.
    #
    # hdr_spark is the one header with no text cell under it, and it is Right because the bars
    # are: EX.draw_spark indexes h[#h - (SPARK_BARS - 1 - i)], so history fills from the RIGHT
    # and an early campaign draws three bars at the far end of the strip. Left-aligned, the
    # label sat 70px from its own data. Its width tracks the strip (SPARK_BARS * 9) in
    # EX.PANEL_LAYOUT so "right" means the newest bar's edge.
    # SEVEN HEADERS, AND THE HOUSES VIEW ADDS NONE. It briefly had two of its own, hdr_div and
    # hdr_seat, on the argument that a table mapping "hdr_sell" to a dividend column is the
    # wrong kind of surprising. That cost two GUIDs, two EX.HEADERS.trade entries whose only job
    # was to feed the hide loop, two EX.TIPS.trade entries whose only job was to satisfy
    # check_tooltips - and a real bug: EX.TIP_CELL then pointed both hdr_div and hdr_sell at
    # row_sell, and EX.apply_tips walks pairs(), so the trade view's sell column answered with
    # one of the two tooltips at random. EX.HEADERS is the mechanism for "same component,
    # different label per mode" and it already relabels hdr_price to "Share" in the stats view.
    for hid, w, align in (("hdr_name", 170, "Left"), ("hdr_price", 90, "Right"),
                          ("hdr_sell", 74, "Right"),
                          ("hdr_supply", 60, "Right"),
                          ("hdr_trend", 36, "Left"), ("hdr_spark", 100, "Right"),
                          ("hdr_hold", 100, "Right")):
        p.add(C(hid, w, 20, text=True, size=11, colour="#C8B48CFF", align=align,
                tx="4.00,0.00", ty="0.00,0.00"))
    # Lua creates one derpy_chd_exchange_row per instrument into this.
    p.add(C("rows_holder", ROW_W, 560, dockpoint="Top Left", dock_offset="16.00,70.00"))
    # TWO FOOTER LINES, and the second is not decoration.
    #
    # MEASURED IN GAME 2026-09-06 with uicomponent:TextDimensionsForText: the trade footer needs
    # 1333px and the offerings footer 1333px, in an 880px box. Both clipped mid-word on screen
    # ("Shaken: Gemsto...").
    #
    # A TALLER BOX DOES NOT WRAP. texthbehaviour has exactly three values in ui3.pack - "Never
    # split" (5365), "Resize" (4403), "Slip by character" (115) - there is no wrap value, and
    # textvbehaviour does not exist at all. Resizing the live component to 880x60 still measured
    # the text as 1333x32: one line, clipped. So more lines means more COMPONENTS.
    # ------------------------------------------------------------------ THE DEEP CHART
    # Trade page 2: one instrument, forty turns, the full width of the panel. It lives in
    # the PANEL file rather than a file of its own, so it costs no new GUID range - DE15
    # is retired and reusing it against a save that still holds the old component is a
    # silent non-draw.
    #
    # EVERY ONE OF THESE IS HIDDEN ON EVERY OTHER VIEW by EX.layout, which hides anything
    # its mode's table does not name. An unplaced component keeps the last view's
    # coordinates and draws over whatever the new one put there - the fault that once put
    # 19 commodity rows on top of the Houses view.
    # THE GRIDLINES, one per y tick, DECLARED BEFORE THE PLOT so the bars paint over them
    # rather than the other way round. That ordering is INTENT, not a measurement - the
    # engine's sibling draw order has not been read here - so check_chart_geometry pins the
    # order rather than the result, and a rule sitting on top of a bar is the thing to look
    # for the first time this is seen in play. Asked for from a screenshot 2026-09-09 ("add also line guide
    # for the chart"): with three numbers down the left and nothing carrying them across, a
    # bar's value has to be estimated against a label 800px away.
    #
    # THIS REVERSES THE NOTE THAT USED TO SIT BELOW, which read "three ticks and not a grid:
    # a row of 880px-wide images per tick is a lot of components for a rule the eye supplies
    # anyway". The first half of that was a bad estimate - it is ONE stretched 1x1 per line,
    # three components in total, not a row of them - and the second half was wrong in play.
    #
    # Same 1x1 white as the bars, tinted down to a third alpha: a rule the eye can follow
    # across the plot without competing with the data drawn on top of it.
    for name, frac in (("chart_grid_hi", 1.0), ("chart_grid_mid", 0.5),
                       ("chart_grid_lo", 0.0)):
        y = CHART_TOP + (CHART_H - CHART_FLOOR) * (1.0 - frac)
        p.add(C(name, DEEP_BARS * CHART_PITCH, 2, image=BAR_BG, colour_img=GRID_COLOUR,
                dockpoint="Top Left", dock_offset="%.2f,%.2f" % (CHART_LEFT, y)))

    chart = p.add(C("chart", DEEP_BARS * CHART_PITCH, CHART_H, dockpoint="Top Left",
                    dock_offset="%.2f,%.2f" % (CHART_LEFT, CHART_TOP)))
    # Bars are docked BOTTOM so a height change grows them upward, like the sparkline -
    # but imagedock is ignored at runtime like every other dock attribute, so EX.draw_chart
    # bottom-aligns each bar by hand with MoveTo. The attribute is kept for the static
    # layout only.
    for i in range(DEEP_BARS):
        chart.add(C("cbar_%02d" % i, CHART_BAR_W, CHART_H, image=BAR_BG,
                    colour_img=BAR_COLOUR, imagedock="Bottom Left",
                    dockpoint="Bottom Left",
                    dock_offset="%.2f,0.00" % (i * CHART_PITCH)))
    # THE COMMODITY'S OWN ICON beside the title, the same 24x24 cell the list rows carry
    # and painted from the same EX.icon(). Hidden, never left on the last commodity's
    # picture, when nothing is chosen - a wrong icon is a claim about the wrong good.
    p.add(C("chart_icon", 24, 24, image=ICON_BG,
            dockpoint="Top Left", dock_offset="20.00,65.00"))
    p.add(C("chart_title", ROW_W - 30, 26, text=True, size=16, colour="#E8D8A8FF",
            dockpoint="Top Left", dock_offset="50.00,64.00",
            tx="0.00,0.00", ty="0.00,0.00"))

    # THE Y SCALE, in gold, right-aligned into the gutter. Each tick has a rule running
    # across the plot at the same y - see chart_grid_* above, which is computed from this
    # same expression and pinned to it by check_chart_geometry.
    #
    # THE POSITIONS COME OFF THE BAR FORMULA, not off thirds of the box. EX.draw_chart
    # sizes a bar as CHART_FLOOR + frac * (CHART_H - CHART_FLOOR), so the top of the bar
    # for the window's LOW is CHART_FLOOR up from the bottom, not at the bottom - put the
    # label at CHART_H and the axis is 6px out of step with its own data.
    for name, frac in (("chart_y_hi", 1.0), ("chart_y_mid", 0.5), ("chart_y_lo", 0.0)):
        line = CHART_TOP + (CHART_H - CHART_FLOOR) * (1.0 - frac)
        p.add(C(name, CHART_GUT, 18, text=True, size=11, colour="#C8B48CFF", align="Right",
                dockpoint="Top Left", dock_offset="20.00,%.2f" % (line - 9),
                tx="0.00,0.00", ty="0.00,0.00"))

    # THE X SCALE, in turn numbers, under three FIXED bars - the first, the middle and the
    # newest. Fixed, not tracking the oldest bar that has data: a moving tick would have to
    # be MoveTo'd from EX.draw_chart every refresh, and a tick that has no bar over it is
    # written blank instead, which is the same information with no ordering to get wrong.
    #
    # Aligned outward at the ends so neither label leaves the plot: the first reads left
    # from the first bar (a centred one would sit in the y gutter), the last reads right
    # to where the last bar ends.
    XT = CHART_TOP + CHART_H + 4
    p.add(C("chart_x_left", 90, 18, text=True, size=11, colour="#C8B48CFF", align="Left",
            dockpoint="Top Left", dock_offset="%.2f,%.2f" % (CHART_LEFT, XT),
            tx="0.00,0.00", ty="0.00,0.00"))
    p.add(C("chart_x_mid", 90, 18, text=True, size=11, colour="#C8B48CFF", align="Center",
            dockpoint="Top Left",
            dock_offset="%.2f,%.2f"
            % (CHART_LEFT + (DEEP_BARS // 2) * CHART_PITCH + CHART_BAR_W / 2.0 - 45, XT),
            tx="0.00,0.00", ty="0.00,0.00"))
    p.add(C("chart_x_right", 90, 18, text=True, size=11, colour="#C8B48CFF", align="Right",
            dockpoint="Top Left",
            dock_offset="%.2f,%.2f"
            % (CHART_LEFT + (DEEP_BARS - 1) * CHART_PITCH + CHART_BAR_W - 90, XT),
            tx="0.00,0.00", ty="0.00,0.00"))

    p.add(C("chart_axis", ROW_W, 20, text=True, size=11, colour="#C8B48CFF",
            dockpoint="Top Left", dock_offset="20.00,%.2f" % (CHART_TOP + CHART_H + 26),
            tx="0.00,0.00", ty="0.00,0.00"))
    p.add(C("chart_stats", ROW_W, 22, text=True, size=13,
            dockpoint="Top Left", dock_offset="20.00,%.2f" % (CHART_TOP + CHART_H + 48),
            tx="0.00,0.00", ty="0.00,0.00"))
    p.add(C("chart_note", ROW_W, 22, text=True, size=12, colour="#C8B48CFF",
            dockpoint="Top Left", dock_offset="20.00,%.2f" % (CHART_TOP + CHART_H + 70),
            tx="0.00,0.00", ty="0.00,0.00"))

    # THE ORDER TICKET, in the 130px between the chart's note and the footers. It acts on
    # whatever instrument the chart already has selected, which is what makes it six controls
    # and not a picker as well.
    tickhov = [{"path": BTN_HOVER, "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0,
                "dock": None}]
    p.add(C("ord_side", 100, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="20.00,508.00", tooltip=TIP_ORD_SIDE))
    p.add(C("ord_cmp", 140, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="128.00,508.00", tooltip=TIP_ORD_CMP))
    p.add(C("ord_down", 40, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="276.00,508.00", tooltip=TIP_ORD_STEP))
    p.add(C("ord_price", 100, 26, text=True, size=13, align="Center",
            dockpoint="Top Left", dock_offset="324.00,508.00"))
    p.add(C("ord_up", 40, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="432.00,508.00", tooltip=TIP_ORD_STEP))
    p.add(C("ord_place", 100, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="480.00,508.00", tooltip=TIP_ORD_PLACE))
    p.add(C("ord_standing", ROW_W, 22, text=True, size=12, colour="#C8B48CFF",
            dockpoint="Top Left", dock_offset="20.00,540.00"))
    # THE AMOUNT, TWICE, ONE VALUE. btn_amount sits in the header band directly above the
    # rows' own Buy and Sell columns (they start at x654), because that is what it governs;
    # ord_qty sits on the ticket right of Place, where it governs the size Place bakes in.
    # Both read and cycle EX.amount, so the number cannot disagree with itself.
    p.add(C("btn_amt_down", 26, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="676.00,46.00", tooltip=TIP_AMOUNT_STEP))
    p.add(C("btn_amount", 130, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="706.00,46.00", tooltip=TIP_AMOUNT))
    p.add(C("btn_amt_up", 26, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="840.00,46.00", tooltip=TIP_AMOUNT_STEP))
    # THE TICKET'S COPY. It counts in real goods rather than in lots - it has a selected
    # instrument and the list button does not - and carries the cost line underneath.
    p.add(C("ord_qty_down", 26, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="596.00,508.00", tooltip=TIP_AMOUNT_STEP))
    p.add(C("ord_qty", 130, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="626.00,508.00", tooltip=TIP_AMOUNT))
    p.add(C("ord_qty_up", 26, 26, interactive=True, image=BTN_BG, hover=tickhov,
            sound=SND_CLOSE, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Left", dock_offset="760.00,508.00", tooltip=TIP_AMOUNT_STEP))
    p.add(C("ord_cost", ROW_W, 22, text=True, size=12, colour="#C8B48CFF",
            dockpoint="Top Left", dock_offset="20.00,566.00"))

    p.add(C("footer_text", ROW_W, 24, text=True, size=12,
            dockpoint="Bottom Left", dock_offset="16.00,-38.00"))
    p.add(C("footer_text2", ROW_W, 24, text=True, size=12,
            dockpoint="Bottom Left", dock_offset="16.00,-14.00"))
    return assign(root, "DE16")


def build_row():
    root = C("root", ROW_W, ROW_H)
    r = root.add(C("derpy_chd_exchange_row", ROW_W, ROW_H))
    # A hairline under each row. Rows are 28px apart, so this sits at +26 (see EX.ROW_LAYOUT)
    # and reads as a list rather than as floating text.
    r.add(C("divider", ROW_W - 12, 2, image=DIVIDER, colour_img=DIVIDER_COLOUR))
    r.add(C("icon", 24, 24, image=ICON_BG))
    r.add(C("row_name", 170, 20, text=True, tx="4.00,0.00", ty="0.00,0.00"))
    r.add(C("row_price", 90, 20, text=True, align="Right", size=13,
            dockpoint="Top Left", dock_offset="196.00,10.00"))
    # THE SELL PRICE, added 2026-09-06. Same shape as row_price and right beside it: the two
    # numbers are read together, and before this column existed the cut was named only in the
    # Sell button's tooltip.
    r.add(C("row_sell", 74, 20, text=True, align="Right", size=13,
            dockpoint="Top Left", dock_offset="270.00,10.00"))
    # Map-wide supply - the number the price is actually derived from, so showing it makes the
    # pricing legible instead of magic. Layer-2 resources have no map supply and read "-".
    r.add(C("row_supply", 60, 20, text=True, align="Right", size=13,
            dockpoint="Top Left", dock_offset="310.00,10.00"))
    r.add(C("row_trend", 30, 20, text=True, size=13,
            dockpoint="Top Left", dock_offset="292.00,10.00"))
    spark = r.add(C("spark", SPARK_BARS * 9, 26,
                    dockpoint="Top Left", dock_offset="324.00,7.00"))
    # Bars are docked BOTTOM so a height change grows them upward, like a real chart.
    for i in range(SPARK_BARS):
        spark.add(C("bar_%02d" % i, 7, 24, image=BAR_BG, colour_img=BAR_COLOUR,
                    imagedock="Bottom Left",
                    dockpoint="Bottom Left", dock_offset="%.2f,0.00" % (i * 9), ))
    r.add(C("row_hold", 100, 20, text=True, align="Right",
            dockpoint="Top Left", dock_offset="%.2f,10.00" % (324 + SPARK_BARS * 9 + 12)))
    # hover=[...] rather than image= for these two: the hover state needs a full layer list,
    # and `image` is only shorthand for a single standard layer.
    hov = [{"path": BTN_HOVER, "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None}]
    r.add(C("btn_buy", 100, 26, interactive=True, image=BTN_BG, hover=hov,
            sound=SND_BUY, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Right", dock_offset="-84.00,7.00",
            tooltip=TIP_BUY))
    r.add(C("btn_sell", 100, 26, interactive=True, image=BTN_BG, hover=hov,
            sound=SND_SELL, text=True, align="Center", ty="0.00,0.00",
            dockpoint="Top Right", dock_offset="-4.00,7.00",
            tooltip=TIP_SELL))
    return assign(root, "DE17")


def build_button():
    root = C("root", 48, 48)
    root.add(C("derpy_chd_exchange_button", 48, 48, interactive=True, sound=SND_OPEN,
               layers=OPENER_LAYERS, hover=OPENER_HOVER, tooltip=TIP_OPEN))
    return assign(root, "DE18")


FILES = [
    ("derpy_chd_exchange_panel.twui.xml", build_panel,
     "derpy: the Zharr Exchange panel. Created at runtime into the campaign UI root by "
     "script/campaign/mod/zzz_derpy_chd_exchange.lua - no CA file is overridden. The 40 trade "
     "ritual cards are HIDDEN from CA's rites panel with SetVisible(false) so they stop "
     "crowding the Hell-Forge commissions - cm:lock_ritual does not remove them - and the "
     "trade runs here as cm:treasury_mod plus cm:faction_add_pooled_resource, because "
     "cm:perform_ritual never charges the treasury. Generated by tools/gen_exchange_ui.py; "
     "do not hand-edit."),
    ("derpy_chd_exchange_row.twui.xml", build_row,
     "derpy: one commodity row of the Zharr Exchange. Lua creates one per instrument into the "
     "panel's rows_holder. The bar_NN components are the sparkline - Lua sets each one's height "
     "with SetCanResizeHeight/Resize, and they are docked Bottom Left so they grow upward. "
     "Generated by tools/gen_exchange_ui.py; do not hand-edit."),
    ("derpy_chd_exchange_button.twui.xml", build_button,
     "derpy: the campaign-bar button that opens the Zharr Exchange. Created at runtime next to "
     "CA's button_rituals. Generated by tools/gen_exchange_ui.py; do not hand-edit."),
]


def _game_assets():
    """Every file path in the game's ui packs, cached. Used to prove a texture exists."""
    import json
    cache = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         ".skilltree_cache", "ui_asset_paths.json")
    if os.path.isfile(cache):
        return set(json.load(open(cache, encoding="utf-8")))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import read_pack_index as rpi
    data = os.path.join(GAME, "data")
    out = set()
    for name in sorted(os.listdir(data)):
        if not name.endswith(".pack") or not name.startswith("ui"):
            continue
        try:
            out.update(rpi.paths(os.path.join(data, name)))
        except Exception:
            pass
    assert out, "no ui pack read from %s" % data
    json.dump(sorted(out), open(cache, "w", encoding="utf-8"))
    return out


def _our_imagepaths():
    """imagepath values across the three generated files, minus our own placeholder."""
    found = set()
    for build in (build_panel, build_row, build_button):
        for c in build().walk():
            for key in ("layers", "hover"):
                for lay in (c.kw.get(key) or []):
                    found.add(lay["path"])
            if c.kw.get("image"):
                found.add(c.kw["image"])
    return found


def selftest():
    seen = {}
    for name, fn, _c in FILES:
        root = fn()
        ids = [c.name for c in root.walk()]
        assert len(ids) == len(set(ids)), "%s has duplicate component ids: %s" % (name, ids)
        for c in root.walk():
            for g in (c.gid, c.sid, c.hid):
                assert g not in seen, "GUID %s reused (%s and %s) - a silent non-draw" % (
                    g, seen.get(g), name)
                seen[g] = name
        # every guid in <components> must have a node in <hierarchy>, or it never draws
        xml = layout(root, "t")
        for c in root.walk():
            assert xml.count('this="%s"' % c.gid) >= 2, "%s: %s unpaired" % (name, c.name)
        assert xml.count("<root") == 2 and xml.count("</layout>") == 1
        # the names the Lua reaches for must exist
    row = build_row()
    names = {c.name for c in row.walk()}
    for want in ["row_name", "row_price", "row_trend", "row_hold", "btn_buy", "btn_sell",
                 "spark", "divider", "icon", "row_supply"]:
        assert want in names, want
    assert sum(1 for n in names if n.startswith("bar_")) == SPARK_BARS
    panel = {c.name for c in build_panel().walk()}
    for want in ["title_text", "close_button", "derpy_chd_ex_mode", "derpy_chd_ex_prev",
                 "nav_page", "btn_help", "rows_holder",
                 "footer_text", "hdr_name", "hdr_price", "hdr_supply", "hdr_trend",
                 "hdr_spark", "hdr_hold"]:
        assert want in panel, want

    # THE TWO NAV ARROWS MUST POINT OPPOSITE WAYS, and this is checked against the RENDERED
    # file rather than the layer tables, because the flip is an attribute _state() has to
    # emit and a missing emitter looks identical from the Python side. CA ships no mirrored
    # arrow texture (see _flipped()), so both buttons draw the same png and the only thing
    # separating "back" from "forward" on screen is flipped="true" on one of them. Lose it and
    # the panel still pages correctly in both directions - only the glyph lies, which is
    # exactly the kind of fault nothing but a screenshot ever catches.
    #
    # TWO, not one: the arrow is a layer of the standard state AND of the hover state, and a
    # flip on only the standard one would mirror the glyph the instant the mouse arrived.
    pxml = layout(build_panel(), "t")
    blocks = dict((b.split(chr(10), 1)[0].strip(), b)
                  for b in re.split(r"(?m)^\t\t<(?=\w)", pxml.split("<components>", 1)[1]))
    # x_flipped, and the assertion says so in full: `flipped="true"` is a SUBSTRING of
    # `x_flipped="true"`, so a check written against the short name passes on the real
    # attribute AND on the wrong one. That is how two identical arrows shipped.
    assert blocks["derpy_chd_ex_mode"].count('x_flipped="true"') == 2, (
        "the Next arrow carries %d x_flipped layers, not 2 (standard and hover). Unflipped, "
        "icon_credits_back.png points LEFT - the same way as Previous."
        % blocks["derpy_chd_ex_mode"].count('x_flipped="true"'))
    assert 'flipped="true"' not in blocks["derpy_chd_ex_prev"], (
        "the Previous arrow is flipped, so both nav buttons point right")

    # AND THEY ARE ROUND. Asked for from play - the first pair used CA's cycle-button art,
    # which is an arrow-SHAPED red plate, and read as two square slabs next to the round close
    # and help buttons. The plate is pinned to close_button's rather than named literally, so
    # the four controls in that right-hand column cannot drift apart one edit at a time.
    def plates(name):
        return set(re.findall(r'imagepath="(ui/skins/default/button_[a-z_]+)\.png"',
                              blocks[name]))
    want = plates("close_button")
    assert want, "close_button has no plate texture to match against"
    for name in ("derpy_chd_ex_prev", "derpy_chd_ex_mode"):
        assert plates(name) == want, (
            "%s is built on %s but close_button and btn_help use %s - the nav has to be the "
            "same round plate as the other controls in that column"
            % (name, sorted(plates(name)), sorted(want)))

    # The column headers only line up because their x offsets are the row's plus the 20px
    # rows_holder inset, and those offsets live in the LUA, not here. Nothing else notices when
    # one side is edited alone, so check it.
    lua = io.open("Modding Files/pack/script/campaign/mod/zzz_derpy_chd_exchange.lua",
                  encoding="utf-8").read()

    # BOUNDS() IS NOT DIMENSIONS(), and mixing them up is silent - it draws, just in the wrong
    # place. Bounds() is a component's extent INCLUDING ITS CHILDREN.
    #
    # THIS ASSERT USED TO PERMIT `root:Bounds()` on the stated grounds that the ui root's own
    # Dimensions() are not the screen size. That was WRONG, and the exemption is what let the
    # remaining bug through. CA's own accessor, out of data_script.pack/script/_lib/lib_core.lua
    # line 392, is:
    #     function core_object:get_screen_resolution() return self.ui_root:Dimensions() end
    # Dimensions(), and the root is no exception. Bounds() on the root includes every child, so
    # during load it reports larger than the display - measured, the opener button landed at
    # 2090,1195 on a 1966x901 screen and PASSED its own on-screen guard because the guard asked
    # the same inflated question, and the panel centred inside a screen that does not exist.
    #
    # So the rule is now absolute: no :Bounds() anywhere in this script, root included. Screen
    # size comes from core:get_screen_resolution().
    # COMMENT LINES ARE STRIPPED FIRST. The blocks explaining this trap quote the bad call
    # verbatim, so a raw scan fails on its own documentation - exactly as
    # check_trend_colours did on its first run.
    code = chr(10).join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    bad = re.findall(r"(\w+):Bounds\(\)", code)
    assert not bad, (
        "%s:Bounds() in zzz_derpy_chd_exchange.lua. Bounds() INCLUDES CHILDREN, and the ui "
        "root is NOT an exception - core:get_screen_resolution() is ui_root:Dimensions(). "
        "Use Dimensions() for a component's own size and EX.screen() for the display."
        % ", ".join(sorted(set(bad))))
    # `code`, not `lua`: the comment above EX.screen() quotes the call, so scanning the
    # raw file would pass on the documentation alone. Verified by replacing the call with
    # a hardcoded 1920,1080 - which this did not catch until it read stripped code.
    assert "core:get_screen_resolution()" in code, (
        "nothing reads the screen resolution any more - EX.screen() is what centres the panel "
        "and bounds-checks the opener button")

    # The off-screen guard in EX.place_button measures the button it is placing, so the two
    # sides of that number live in two files.
    m = re.search(r"EX\.BUTTON_SIZE\s*=\s*(\d+)", lua)
    assert m and int(m.group(1)) == build_button().w, (
        "EX.BUTTON_SIZE is %s but build_button() emits %d"
        % (m.group(1) if m else "absent", build_button().w))

    def offsets(table_name):
        # split on a closing brace at column 0 - each ENTRY is also brace-delimited.
        # Entries are { name, x, y } or { name, x, y, width }; width is captured when present.
        body = lua.split(table_name + " = {", 1)[1].split(chr(10) + "}", 1)[0]
        found = re.findall(
            r'\{\s*"(\w+)"\s*,\s*(-?\d+)\s*,\s*(-?\d+)(?:\s*,\s*(-?\d+))?', body)
        return dict((n, (int(x), int(w) if w else None)) for n, x, _y, w in found)

    # THE STATS VIEW IS CHECKED EXACTLY LIKE THE TRADE VIEW. Both modes reposition and resize
    # the SAME components, so a stats column that overlaps or clips is the same silent fault
    # class as "TrendLast 12 turns" was - and it would only ever be caught by a screenshot.
    inset = 20
    xml_w, xml_text = {}, {}
    for build in (build_panel, build_row):
        for c in build().walk():
            xml_w[c.name] = c.w
            if c.kw.get("text"):
                xml_text[c.name] = (c.kw.get("align", "Left"), c.kw.get("tx", "4.00,0.00"))

    checked = set()

    def check_mode(mode, row_tbl, panel_tbl, pairs):
        checked.add(mode)
        rows, hdrs = offsets(row_tbl), offsets(panel_tbl)
        for hid, rid in pairs:
            assert hid in hdrs, "%s: %s missing from %s" % (mode, hid, panel_tbl)
            assert rid in rows, "%s: %s missing from %s" % (mode, rid, row_tbl)
            want = rows[rid][0] + inset
            assert hdrs[hid][0] == want, (
                "%s: %s is at x=%d but %s puts its column at x=%d"
                % (mode, hid, hdrs[hid][0], rid, want))
            # A HEADER IS ALIGNED LIKE ITS CELL, or it names a column it does not sit over.
            # Both boxes start at the same x and (bar hdr_trend) are the same width, so equal
            # texthalign + textxoffset is the whole of "the label lines up with the figures".
            # Left over right-aligned numbers is what shipped and what §7 reported; it is not
            # visible to any other check here, all of which measure BOXES.
            if rid in xml_text:
                assert xml_text[hid] == xml_text[rid], (
                    "%s: %s is %s/tx=%s over %s cells that are %s/tx=%s - the header floats "
                    "off its own column" % ((mode, hid) + xml_text[hid] + (rid,)
                                            + xml_text[rid]))
        def width(tbl, name):
            return tbl[name][1] or xml_w[name]

        ordered = sorted((v[0], k) for k, v in hdrs.items() if k.startswith("hdr_"))
        for (x, hid), (nx, nhid) in zip(ordered, ordered[1:]):
            w = width(hdrs, hid)
            end = x + w
            assert end <= nx, ("%s: %s ends at %d but %s starts at %d"
                               % (mode, hid, end, nhid, nx))
            # A NARROW BOX IS A FULL BOX - BUT ONLY AGAINST A LEFT-ALIGNED NEIGHBOUR. A tight
            # header's label fills its box, so the box gap is its own text gap; whether that
            # gap READS as a gap depends on where the NEXT label starts. Left-aligned, the next
            # label starts at its box edge and the box gap is the whole story - that is the case
            # this models, and it is how the row once read "Trend Last 12 turns" (2026-09-05).
            # Right-aligned, the next label starts most of a box away and this rule would refuse
            # a layout that is perfectly legible. The real text-to-text gap needs the LABELS,
            # which live in EX.HEADERS, so check_header_labels() in gen_zharr_exchange.py owns
            # it for every pair; this stays as the cheap guard on the case it is exact for.
            if w <= 60 and xml_text.get(nhid, ("Left",))[0] == "Left":
                assert nx - end >= 12, (
                    "%s: %s is only %dpx wide, so its label fills it - %dpx to left-aligned %s "
                    "reads as one run-on phrase. Give a tight header at least 12px of clear "
                    "space." % (mode, hid, w, nx - end, nhid))
        # divider spans the whole row by design, so it is not a column
        right = max(x + width(rows, rid) for rid, (x, _w) in rows.items() if rid != "divider")
        assert right <= ROW_W, ("%s: row content reaches %d in a %d row" % (mode, right, ROW_W))
        assert ROW_W - right <= 24, (
            "%s: %d px of dead space right of the last column" % (mode, ROW_W - right))
        return rows, hdrs

    # THE SPARKLINE HEADER HAS NO TEXT CELL UNDER IT, so check_mode cannot pair it. Its data is
    # the bar strip, which fills from the right (EX.draw_spark), so the label follows.
    assert xml_text["hdr_spark"][0] == "Right", (
        "hdr_spark is %s. The sparkline fills from the RIGHT - an early campaign draws three "
        "bars at the far end of the strip - so a left-aligned label sits 70px from its own "
        "data." % xml_text["hdr_spark"][0])

    # AND ITS BOX ENDS WHERE THE LAST BAR DOES. Right-aligned into a narrower box, the label
    # would stop short of the newest bar - the one thing the alignment exists to touch.
    for tbl in ("EX.PANEL_LAYOUT", "EX.PANEL_LAYOUT_STATS"):
        got = offsets(tbl).get("hdr_spark", (None, None))[1]
        assert got == SPARK_BARS * 9, (
            "%s: hdr_spark is %s wide but the strip is %d (SPARK_BARS * 9). It is right-aligned "
            "to the newest bar, so the two have to end together."
            % (tbl, got, SPARK_BARS * 9))

    rows, hdrs = check_mode(
        "trade", "EX.ROW_LAYOUT", "EX.PANEL_LAYOUT",
        (("hdr_name", "row_name"), ("hdr_price", "row_price"), ("hdr_supply", "row_supply"),
         ("hdr_trend", "row_trend"), ("hdr_spark", "spark"), ("hdr_hold", "row_hold")))
    check_mode(
        "stats", "EX.ROW_LAYOUT_STATS", "EX.PANEL_LAYOUT_STATS",
        (("hdr_name", "row_name"), ("hdr_price", "row_price"), ("hdr_supply", "row_supply"),
         ("hdr_trend", "row_trend"), ("hdr_spark", "spark"), ("hdr_hold", "row_hold")))
    # The offerings view drops the sparkline entirely, so it is checked without that pair -
    # every OTHER rule (header over its column, no overlap, no run-on, no dead space) still
    # applies, because they are properties of the row and not of a particular mode.
    check_mode(
        "offer", "EX.ROW_LAYOUT_OFFER", "EX.PANEL_LAYOUT_OFFER",
        (("hdr_name", "row_name"), ("hdr_price", "row_price"), ("hdr_supply", "row_supply"),
         ("hdr_trend", "row_trend"), ("hdr_hold", "row_hold")))
    # THE HOUSES VIEW. Same seven headers over the same seven cells as the trade view, at the
    # same x offsets - only the LABELS differ, through EX.HEADERS.houses ("Div" over row_sell,
    # "Seat" over row_supply). See build_panel() for why the two components of its own that this
    # view briefly had were deleted.
    check_mode(
        "houses", "EX.ROW_LAYOUT_HOUSES", "EX.PANEL_LAYOUT_HOUSES",
        (("hdr_name", "row_name"), ("hdr_price", "row_price"), ("hdr_sell", "row_sell"),
         ("hdr_supply", "row_supply"), ("hdr_trend", "row_trend"),
         ("hdr_spark", "spark"), ("hdr_hold", "row_hold")))

    # THE DEALS PAGE (Stage 2). Five columns, no sparkline: a deal is an offer standing now, not
    # a price history. row_trend carries the offer as a sentence, which is why it is the wide one.
    check_mode(
        "deals", "EX.ROW_LAYOUT_DEALS", "EX.PANEL_LAYOUT_DEALS",
        (("hdr_name", "row_name"), ("hdr_trend", "row_trend"), ("hdr_price", "row_price"),
         ("hdr_sell", "row_sell"), ("hdr_hold", "row_hold")))

    # THE LOG VIEW. Two columns - a "T14  Gems" stamp and a whole sentence - so it is checked
    # on the pair it has. It borrows the guide's geometry, but unlike the guide it sits IN the
    # mode cycle, which is what makes every rule below apply to it: a player reaches it with
    # the same arrow that reaches the trade view and leaves the same way, so a cell this view
    # resizes is a cell the trade view inherits.
    check_mode(
        "log", "EX.ROW_LAYOUT_LOG", "EX.PANEL_LAYOUT_LOG",
        (("hdr_name", "row_name"), ("hdr_trend", "row_trend")))

    # WIDTHS MUST BE SYMMETRIC ACROSS MODES. Resize is one-way: a cell widened for the stats
    # view keeps that width when the player toggles back unless the trade table names its own.
    # So if a component carries an explicit width in one mode's table it must carry one in the
    # other. Text clips to its component, so the failure is a trade column silently drawing
    # "12..." after one visit to the stats view - and only a screenshot would ever show it.
    for what, tables in (("row", ("EX.ROW_LAYOUT", "EX.ROW_LAYOUT_STATS",
                                  "EX.ROW_LAYOUT_OFFER", "EX.ROW_LAYOUT_HOUSES",
                                  "EX.ROW_LAYOUT_LOG")),
                         ("panel", ("EX.PANEL_LAYOUT", "EX.PANEL_LAYOUT_STATS",
                                    "EX.PANEL_LAYOUT_OFFER", "EX.PANEL_LAYOUT_HOUSES",
                                    "EX.PANEL_LAYOUT_LOG"))):
        for i, ta in enumerate(tables):
            for tb in tables[i + 1:]:
                a, b = offsets(ta), offsets(tb)
                for name in set(a) & set(b):
                    assert (a[name][1] is None) == (b[name][1] is None), (
                        "%s: %s has an explicit width in %s but not %s - Resize never restores "
                        "the other view's width" % (what, name, ta, tb))

    # The stats view hides the trade buttons instead of placing them. If they ever appear in
    # its layout table they would be positioned AND left clickable over the stats columns.
    stats_rows = offsets("EX.ROW_LAYOUT_STATS")
    for b in ("btn_buy", "btn_sell"):
        assert b not in stats_rows, b + " must not be placed in the stats view"
    # THE OFFERINGS VIEW REUSES btn_buy AS "Sacrifice" and must not place btn_sell: the click
    # handler branches on EX.mode, so a placed btn_sell would be a live Sell button sitting in
    # a view whose prices and columns mean something else entirely.
    assert "btn_sell" not in offsets("EX.ROW_LAYOUT_OFFER"), \
        "btn_sell must not be placed in the offerings view"
    assert "btn_buy" in offsets("EX.ROW_LAYOUT_OFFER"), \
        "the offerings view has no Sacrifice button"
    # THE ORDERS LEDGER REUSES btn_buy AS "Cancel", the same idiom as the offerings view above -
    # a placed btn_sell would be a live Sell button sitting over the Cancel column.
    assert "btn_sell" not in offsets("EX.ROW_LAYOUT_ORDERS"), \
        "btn_sell must not be placed in the orders ledger"
    assert "btn_buy" in offsets("EX.ROW_LAYOUT_ORDERS"), \
        "the orders ledger has no Cancel button"
    # THE LEDGER'S OWN ROW-WIDTH CHECK, not check_mode()'s: that function's 24px dead-space
    # rule assumes a SECOND button out near the row's right edge, which every view it covers
    # has and this one does not - Cancel is the only button, so the space past it is
    # deliberate. What check_mode would still be right to catch is a cell with nowhere to
    # go: PANEL_LAYOUT_ORDERS names no header for price, sell, supply or the sparkline (see
    # its own comment), so any of those cells - or anything else - landing in this row would
    # draw whatever the previous view left painted into it, with nothing here to say what it
    # means.
    order_rows = offsets("EX.ROW_LAYOUT_ORDERS")
    order_allowed = {"divider", "icon", "row_name", "row_trend", "row_price", "btn_buy"}
    assert set(order_rows) == order_allowed, (
        "EX.ROW_LAYOUT_ORDERS places %s, which PANEL_LAYOUT_ORDERS names no header for"
        % sorted(set(order_rows) - order_allowed))
    order_right = max(x + (w or xml_w[n]) for n, (x, w) in order_rows.items()
                       if n != "divider")
    assert order_right <= ROW_W, (
        "the ledger row reaches %d in a %dpx row" % (order_right, ROW_W))
    # THE NAV STRIP HAS TO CLEAR THE FOOTERS AND STAY ON THE PANEL, and both failures are
    # silent. The footer lines reach 114 and 118 characters at worst case (check_footer_bounds
    # in gen_zharr_exchange.py measures them by running the shipped summary functions), so a
    # nav button sharing their line is drawn over live text - and on a quiet turn, when the
    # footer is short, it looks perfectly fine. A y past PANEL_H is simply not on screen.
    #
    # The y values live in the LUA layout tables and the heights in this file, which is why
    # nothing else compares them. Widths come from the layout table where it names one - the
    # counter is resized by place() - and from the component otherwise.
    def boxes(table_name):
        body = lua.split(table_name + " = {", 1)[1].split(chr(10) + "}", 1)[0]
        found = re.findall(
            r'\{\s*"(\w+)"\s*,\s*(-?\d+)\s*,\s*(-?\d+)(?:\s*,\s*(-?\d+))?', body)
        return dict((n, (int(x), int(y), int(w) if w else xml_w[n]))
                    for n, x, y, w in found)

    panel_h = {c.name: c.h for c in build_panel().walk()}
    NAV = ("derpy_chd_ex_prev", "nav_page", "derpy_chd_ex_mode")
    for tbl in ("EX.PANEL_LAYOUT", "EX.PANEL_LAYOUT_STATS", "EX.PANEL_LAYOUT_OFFER",
                "EX.PANEL_LAYOUT_HOUSES", "EX.PANEL_LAYOUT_HELP"):
        b = boxes(tbl)
        floor = max(b[f][1] + panel_h[f] for f in ("footer_text", "footer_text2"))
        for name in NAV:
            x, y, w = b[name]
            assert y >= floor, (
                "%s: %s starts at y=%d but the footer text runs to y=%d. On a quiet turn the "
                "footer is short and this looks fine; at worst case it is 118 characters and "
                "the button sits on top of them." % (tbl, name, y, floor))
            assert y + panel_h[name] <= PANEL_H, (
                "%s: %s runs to y=%d in a %dpx panel - it is off the bottom edge"
                % (tbl, name, y + panel_h[name], PANEL_H))
            assert x + w <= PANEL_W, (
                "%s: %s runs to x=%d in a %dpx panel" % (tbl, name, x + w, PANEL_W))
        ordered = sorted((b[n][0], n) for n in NAV)
        for (x, name), (nx, nname) in zip(ordered, ordered[1:]):
            end = x + b[name][2]
            assert end <= nx, ("%s: %s ends at %d but %s starts at %d - the arrows and the "
                               "counter overlap" % (tbl, name, end, nname, nx))
        assert ordered[0][1] == "derpy_chd_ex_prev" and ordered[-1][1] == "derpy_chd_ex_mode", (
            "%s: the nav reads %s left to right. Back belongs on the left and forward on the "
            "right, whichever way the glyphs happen to point."
            % (tbl, [n for _x, n in ordered]))

    # Both toggle buttons must be reachable in every view, or a player can get stuck in one.
    for tbl in ("EX.PANEL_LAYOUT", "EX.PANEL_LAYOUT_STATS", "EX.PANEL_LAYOUT_OFFER",
                "EX.PANEL_LAYOUT_HOUSES", "EX.PANEL_LAYOUT_HELP"):
        placed = offsets(tbl)
        # btn_help is in this list for the same reason: the guide is where a confused player
        # goes, and it must be one click away from whichever view confused them.
        for b in ("close_button", "derpy_chd_ex_mode", "derpy_chd_ex_prev", "nav_page",
                  "btn_help"):
            assert b in placed, "%s is unreachable in %s" % (b, tbl)

    # EVERY CELL A MODE DOES NOT PLACE MUST BE HIDDEN, and EX.layout does that by walking
    # EX.ROW_CELLS. A cell missing from that list is never hidden and keeps the previous view's
    # position, drawing on top of whatever the new mode put there - which is what the sparkline
    # would have done in the offerings view.
    m = re.search(r"EX\.ROW_CELLS = \{(.*?)\}", lua, re.S)
    assert m, "EX.ROW_CELLS is gone - nothing hides an unplaced cell any more"
    cells = set(re.findall(r'"(\w+)"', m.group(1)))
    for tbl in ("EX.ROW_LAYOUT", "EX.ROW_LAYOUT_STATS", "EX.ROW_LAYOUT_OFFER",
                "EX.ROW_LAYOUT_HELP"):
        for name in offsets(tbl):
            assert name in cells, (
                "%s places %s, which EX.ROW_CELLS does not list - no other mode will hide it"
                % (tbl, name))

    # THE TAB STRIP MUST NOT REACH THE NAV CLUSTER, in any view. The .twui.xml has said "the
    # two clusters cannot touch" since the strip was five wide, and nothing enforced it: a
    # mutant that re-pitched the six tabs back to 132-on-140 - running the last two straight
    # through the back arrow and the page counter - passed every check in both generators.
    # Measured per layout table, because each one carries its own copy of the strip.
    for tbl in [n for n in re.findall(r"EX\.PANEL_LAYOUT\w*", lua)]:
        placed = offsets(tbl)
        tabs = {k: v for k, v in placed.items() if k.startswith("derpy_chd_ex_tab_")}
        if not tabs or "derpy_chd_ex_prev" not in placed:
            continue
        arrow = placed["derpy_chd_ex_prev"][0]
        for name, (x, w) in sorted(tabs.items()):
            end = x + (w or xml_w[name])
            assert end <= arrow, (
                "%s: %s ends at %d and the back arrow starts at %d. The strip has run into the "
                "nav cluster - both are drawn, both are clickable, and the overlap is only "
                "visible in a screenshot." % (tbl, name, end, arrow))
        # AND NOT INTO EACH OTHER.
        byx = sorted((v[0], k) for k, v in tabs.items())
        for (x, k), (nx, nk) in zip(byx, byx[1:]):
            end = x + (tabs[k][1] or xml_w[k])
            assert end <= nx, ("%s: tab %s ends at %d but %s starts at %d" % (tbl, k, end, nx, nk))

    # TAB_MODES HERE VS EX.MODES IN THE LUA. This file MAKES the five tab components and the
    # Lua PLACES and labels them, so the two lists have to be the same list. A tab this file
    # emits for a mode the Lua does not know is a button that never gets positioned - it draws
    # at whatever the .twui.xml said, which since 2026-09-07 is a placeholder offset. A mode
    # with no tab is a view that, now the arrows page instead of cycling, has no way in at all.
    lua_modes = re.search(r"EX\.MODES = \{(.*?)\}", lua)
    assert lua_modes, "EX.MODES is gone"
    assert re.findall(r'"(\w+)"', lua_modes.group(1)) == TAB_MODES, (
        "TAB_MODES here is %s but EX.MODES in the Lua is %s. A tab with no mode is a button "
        "that is never placed; a mode with no tab is a view with no way in."
        % (TAB_MODES, re.findall(r'"(\w+)"', lua_modes.group(1))))

    # Every mode named in EX.MODES needs a header set, or the mode cycle lands on a view whose
    # columns keep the previous one's labels over the new one's numbers.
    m = re.search(r"EX\.MODES = \{(.*?)\}", lua, re.S)
    assert m, "EX.MODES is gone - the mode button has nothing to cycle"
    modes = re.findall(r'"(\w+)"', m.group(1))
    # Not a hardcoded count: a fourth view is fine, it just has to be CHECKED like the other
    # three. Every rule above is per-mode, so a mode the selftest never ran check_mode on ships
    # with none of them applied.
    assert set(modes) == checked, (
        "EX.MODES and the checked views disagree: unchecked %s, checked-but-gone %s. Add a "
        "check_mode call for a new view." % (set(modes) - checked, checked - set(modes)))
    hdrs = re.search(r"EX\.HEADERS = \{(.*?)\n\}", lua, re.S)
    assert hdrs, "EX.HEADERS is gone"
    # EVERY HEADER ID IN EVERY MODE MUST ALSO APPEAR IN EX.HEADERS.trade, because that is the
    # set EX.layout() walks to HIDE the headers a mode does not place. An id only the stats
    # view knows about is never hidden on the way out of it, so it keeps that view's position
    # and draws on top of whatever the next mode put there - the exact fault EX.ROW_CELLS
    # exists to prevent on the row side, and it had no equivalent guard on the header side
    # until hdr_sell became the first header that is not in all three views.
    trade_block = re.search(r"\n\s+trade = \{(.*?)\n\s+\w+ = \{", hdrs.group(1), re.S)
    assert trade_block, "EX.HEADERS.trade is gone - nothing drives the header hide loop"
    trade_ids = set(re.findall(r"(hdr_\w+)\s*=", trade_block.group(1)))
    for mode in modes:
        block = re.search(r"\n\s+%s = \{(.*?)\n\s+\}|\n\s+%s = \{(.*?)\n\s+\w+ = \{"
                          % (mode, mode), hdrs.group(1), re.S)
        if block:
            ids = set(re.findall(r"(hdr_\w+)\s*=", block.group(1) or block.group(2) or ""))
            extra = ids - trade_ids
            assert not extra, (
                "EX.HEADERS.%s names %s, which EX.HEADERS.trade does not. EX.layout hides "
                "headers by walking the trade set, so these would never be hidden when the "
                "player switches away from this view." % (mode, sorted(extra)))
    # EVERY VIEW THE PANEL CAN BE IN NEEDS A HEADERS ENTRY, and `modes` is NOT that set:
    # EX.MODES is the TAB STRIP, and the guide and the introduction are reachable views that
    # are deliberately absent from it. refresh_panel walks pairs(EX.HEADERS[EX.mode]) BEFORE
    # it branches on the mode, so a view with no entry indexes nil and takes the whole refresh
    # down the first time anyone reaches it - which for the introduction is the first time
    # anyone opens the panel at all.
    #
    # Read off EX.panel_layout's own branches instead, which is by definition every mode the
    # panel can be in. The comment above EX.HEADERS.log has warned about this fault since
    # 2026-09-07 and the check underneath it only ever covered the five tabs.
    picker = re.search(r"function EX\.panel_layout\(\)(.*?)\nend", lua, re.S)
    assert picker, "EX.panel_layout is gone - the view list cannot be derived"
    consts = dict(re.findall(r'EX\.(MODE_\w+)\s*=\s*"(\w+)"', lua))
    reachable = {"trade"}
    for name in re.findall(r"EX\.mode == EX\.(MODE_\w+)", picker.group(1)):
        assert name in consts, "EX.panel_layout tests %s, which is not declared" % name
        reachable.add(consts[name])
    assert reachable >= set(modes) | {"help"}, (
        "EX.panel_layout no longer branches on every tab plus the guide: %s" % sorted(reachable))
    for mode in sorted(reachable):
        assert re.search(r"\n\s+%s = \{" % mode, hdrs.group(1)), (
            "EX.panel_layout can put the panel in %r and EX.HEADERS has no entry for it. "
            "refresh_panel indexes EX.HEADERS[EX.mode] before it branches, so the first "
            "player to reach that view takes the whole panel down with them." % mode)

    for mode in modes:
        assert re.search(r"\n\s+%s = \{" % mode, hdrs.group(1)), \
            "EX.MODES lists %r but EX.HEADERS has no labels for it" % mode
        for tbl in ("EX.PANEL_LAYOUT", "EX.ROW_LAYOUT"):
            want = tbl if mode == "trade" else tbl + "_" + mode.upper()
            assert re.search(r"%s = \{" % re.escape(want), lua), \
                "EX.MODES lists %r but %s does not exist" % (mode, want)

    # Alignment values the engine actually accepts. "Centre" is silently ignored.
    for build in (build_panel, build_row, build_button):
        for c in build().walk():
            a, v = c.kw.get("align", "Left"), c.kw.get("valign", "Center")
            assert a in ("Left", "Center", "Right"), "%s: bad texthalign %r" % (c.name, a)
            assert v in ("Top", "Center", "Bottom"), "%s: bad textvalign %r" % (c.name, v)

    # EVERY imagepath must be a real entry in a shipped pack. A path that does not exist
    # renders as a blank white square with no error anywhere - that is how
    # button_icon_close_24.png survived a deploy. Do not trust a byte-grep for a texture name:
    # it matches strings inside other files, not pack entries.
    missing = [pa for pa in sorted(_our_imagepaths()) if pa not in _game_assets()]
    assert not missing, "imagepath not present in any shipped pack:\n  " + "\n  ".join(missing)

    # HOVER STATES. Four things here fail SILENTLY and none of them raises anything:
    #
    #   1. A <hover> state with no <transitionmap> edge pointing at it. The state is in the
    #      file, the engine has no way to enter it, and the button never lights. This is the
    #      one that makes authoring hover look like it "does not work".
    #   2. A hover state with no way BACK. The button lights once and stays lit for the rest
    #      of the session.
    #   3. A hover state missing <component_text> on a component that has a label - the
    #      typeface changes the instant the mouse arrives.
    #   4. A hover texture that is not in any shipped pack: a blank white square, on mouseover
    #      only, which is where a screenshot is least likely to catch it. That one is covered
    #      by the imagepath sweep above, now that _our_imagepaths() reads hover layers too.
    #
    # An interactive component with NO hover at all is also a finding. Every clickable thing in
    # this panel is meant to light, and "we forgot one" is invisible until someone hovers it.
    for name, fn, _c in FILES:
        root = fn()
        xml = layout(root, "")
        for c in root.walk():
            if not c.kw.get("interactive"):
                assert not c.kw.get("hover"), (
                    "%s: %s has a hover state but is not interactive, so the engine will "
                    "never enter it" % (name, c.name))
                continue
            assert c.kw.get("hover"), (
                "%s: %s is clickable but has no hover state - it will not light on mouseover"
                % (name, c.name))
            block = xml.split('id="%s"' % c.name, 1)[1].split("</%s>" % c.name, 1)[0]
            assert '<hover' in block, "%s: %s emitted no hover state" % (name, c.name)
            # BOTH EDGES. index is omitted on enter (0) and 1 on leave - CA's own shape, read
            # out of ui/templates/round_small_button.twui.xml.
            assert 'transition_m_target_state="%s"' % c.hid in block, (
                "%s: %s has a hover state with nothing transitioning INTO it. The state exists "
                "and the engine can never reach it - a silent non-draw." % (name, c.name))
            assert 'transition_m_target_state="%s"' % c.sid in block, (
                "%s: %s never transitions back out of hover - it lights once and stays lit"
                % (name, c.name))
            assert block.count('index="1"') == 1, (
                "%s: %s should carry exactly one leave edge" % (name, c.name))
            if c.kw.get("text"):
                assert block.count("<component_text") == 2, (
                    "%s: %s has a label but %d component_text blocks; both states need one or "
                    "the font changes on mouseover"
                    % (name, c.name, block.count("<component_text")))
            # The hover layers must actually differ from the standard ones, or the state is
            # real, reachable, and visually identical - which reads as "hover does not work".
            assert ([l["path"] for l in _spec(c.kw, "hover")]
                    != [l["path"] for l in _spec(c.kw, "layers")]), (
                "%s: %s hover draws exactly the standard textures - nothing will change"
                % (name, c.name))

    # THE FOOTER CLIPS, AND NOTHING IN THE ENGINE SAYS SO.
    #
    # Shipped broken 2026-09-06: the trade footer measured 1333px in an 880px component and the
    # game drew "Shaken: Gemsto..." - no error, no log line. A taller box does not help, because
    # texthbehaviour has no wrap value in this engine and textvbehaviour does not exist; the
    # live component resized to 880x60 still measured its text as one 1333px line.
    #
    # So both halves are required: TWO footer components, and every string written to one
    # routed through the fit() helper, which asks uicomponent:TextDimensionsForText what the
    # string would actually need and drops trailing words until it fits. A character budget is
    # the guess that caused this - the footer's content is unbounded, because the shock summary
    # names one commodity per shaken good.
    panel_ids = {c.name for c in build_panel().walk()}
    for fid in ("footer_text", "footer_text2"):
        assert fid in panel_ids, "%s is missing - the footer has nowhere to put its second line" % fid
    assert "local function fit(c, text)" in lua, (
        "the fit() helper is gone from the campaign script. Footer text is unbounded and the "
        "engine clips it mid-word in silence.")
    # COMMENTS STRIPPED FIRST. The block above fit() explains the measurement and names the
    # function, so the first version of this assert passed on its own documentation - the same
    # trap check_trend_colours() carries a note about.
    lua_code_only = chr(10).join(l for l in lua.splitlines()
                                 if not l.lstrip().startswith("--"))
    assert "TextDimensionsForText" in lua_code_only, (
        "fit() no longer measures the text - it is guessing. A character budget cannot be safe "
        "here: the footer's content is unbounded, because the shock summary names one commodity "
        "per shaken good.")
    for fid in ("footer", "footer2"):
        bad = re.findall(r"%s:SetStateText\(\s*(?!fit\()" % fid, lua)
        assert not bad, (
            "%s:SetStateText is called without fit() - that string will clip mid-word with no "
            "error the moment the board gets busy" % fid)
    # Both lines must be placed in EVERY mode, or a view keeps the previous one's second line
    # sitting under its own footer.
    for tbl in ("EX.PANEL_LAYOUT", "EX.PANEL_LAYOUT_STATS", "EX.PANEL_LAYOUT_OFFER"):
        placed = offsets(tbl)
        for fid in ("footer_text", "footer_text2"):
            assert fid in placed, "%s does not place %s" % (tbl, fid)
        assert placed["footer_text"][0] == placed["footer_text2"][0], (
            "%s: the two footer lines are not left-aligned with each other" % tbl)

    # TOOLTIPS: literal text, and long ones need the title split or they clip.
    #
    # Both halves have shipped broken. A {{tr:}} loc key put "||" on screen as two pipes; a long
    # tooltip with no "||" rendered in a box that did not grow and was cut mid-glyph on line two.
    # CA's own files set the threshold: of its literal tooltips on a component 60x60 or smaller,
    # 67% of those over 90 characters carry the split against 0% of those under 40.
    tips = [c.kw["tooltip"] for build in (build_panel, build_row, build_button)
            for c in build().walk() if c.kw.get("tooltip")]
    assert tips, "no tooltips found - did the attribute name change?"
    for t in tips:
        assert not t.startswith("{{"), (
            "%r goes through a resolver; a loc key renders || literally, so tooltip text must be "
            "literal here" % t[:40])
        if len(t) > 60:
            assert "||" in t, (
                "tooltip is %d chars with no title split - it will clip mid-glyph on line two. "
                "Use \"Title||Body\". Offending text: %r" % (len(t), t[:60]))

    # Every clickable component needs a soundcategory, or the panel is silent. An invented
    # category name is silent too, with no error, so these are checked against the set CA
    # actually ships (see the comment on SND_BUY).
    for build in (build_panel, build_row, build_button):
        for c in build().walk():
            if c.kw.get("interactive"):
                assert c.kw.get("sound"), "%s is clickable but silent" % c.name

    assert PANEL_W - ROW_W == 40, "panel should clear the rows by 20px each side"

    # The panel background is two 9-sliced layers. A margin of 0 is what made the tile show
    # seams; do not let it regress to one flat layer.
    assert len(PANEL_LAYERS) == 2, "panel needs a body and a border layer"
    assert all(l["margin"] > 0 for l in PANEL_LAYERS), "9-slice margin must be non-zero"

    print("selftest ok: %d files, %d guids, %d sparkline bars, headers aligned to row columns"
          % (len(FILES), len(seen), SPARK_BARS))


def main():
    written = []
    for name, fn, comment in FILES:
        xml = layout(fn(), comment)
        if "--check" not in sys.argv:
            with io.open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(xml)
        written.append((name, len(xml)))
    for name, size in written:
        print("  %6dB  %s" % (size, name))
    print("--check: nothing written" if "--check" in sys.argv else "\nwrote %d files to %s"
          % (len(written), OUT))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
