"""The Great Guilds - UI generator. Owns the GG21xxxx GUID prefix.

WHY GENERATED, and why the emitter is a copy rather than a shared import:
a GUID that appears in <components> with no matching node in <hierarchy> is a
SILENT non-draw - no error, no log line, the widget simply never appears. One
working emitter already existed in tools/gen_exchange_ui.py and it is the shape
tools/check_guilds_ui.py understands, so this file uses a COPY of it -
tools/gen_guilds_emitter.py. A copy, not an import: while it was an import, fixes
made for this mod silently changed the Zharr Exchange's shipped output too.

GUID RANGE:
    GG21xxxx  derpy_gg_panel / derpy_gg_card / derpy_gg_row   <- this file
Claimed 2026-09-10 in both ledgers (gen_exchange_ui.py and docs/CUSTOM_UI.md).
DE15xxxx is RETIRED and must never be reused - a reused prefix against a save
still holding the old component is a silent non-draw.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# NOT gen_exchange_ui. This mod used to import the Zharr Exchange's emitter directly,
# and three fixes made here therefore changed the EXCHANGE's shipped output too - font
# categories snapped from body_11 to body_10 on 16 of its panel cells and body_13 to
# body_12 on 4 row cells. Two mods that ship separately do not share a code path that
# decides what they emit. gen_guilds_emitter.py is a copy; its docstring lists what
# differs and why.
import gen_guilds_emitter as EU       # noqa: E402  - our own copy of the emitter
import gen_great_guilds as G          # noqa: E402  - SERVICES, for the card count

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "Modding Files", "pack", "ui", "campaign ui")

GUID_PREFIX = "GG21"

PANEL_W, PANEL_H = 790, 700

# name -> (x, y, width, height). Absolute offsets only: dockpoint is IGNORED on a
# runtime-created component and MoveTo is the only thing that positions one, so
# nothing here may sit inside a layout group.
#
# SIX TABS AT 125px = the strip's whole 750, abutting. Five at 132 was "full" by the
# Exchange's measure, which left 90px spare; the Log tab (2026-09-23) takes that and
# 35px more from re-pitching. The row sits at y=56..90, below the close cross (ends y=42).
# ONE LIST, read by the layout, the button styling and both tab checks below - it was
# three hand copies, and the text-block check had already lost gg_tab_court.
# Visual order, NOT GGUI.TAB order: the Lua numbers Log 6 so no existing tab renumbers.
TABS = ["gg_tab_guilds", "gg_tab_stand", "gg_tab_bounty", "gg_tab_court", "gg_tab_log",
        "gg_tab_help"]
TAB_W, TAB_H = 125, 34
PANEL_LAYOUT = {
    "gg_crest":      (16,  9,   34,  34),
    # CENTRED ON THE PANEL, on CA's title plate: 55..735, clear of the crest (ends x=50)
    # and the close cross (x=748), and ending at y=54 above the tabs. 680, not the 600
    # CA's Hell-Forge header uses: at 600 the 165px end caps leave a ~270px dark band and
    # "The Great Guilds" at header_24_bold touched both ends of it (seen in game
    # 2026-09-30). Every culture's plate is transparent for its first 25px or more, so the
    # arrows still start clear of the crest.
    "gg_title":      (55,  0,   680, 54),
    "gg_close":      (748, 12,  30,  30),
    "gg_divider":    (20,  44,  750, 10),
    # THE HELL-FORGE HEADER BAR (see RANK_BAR_LAYERS) with the guild's glyph in CA's round
    # holder over its left end, the way the Hell-Forge draws "Melee Infantry". The bar's
    # lower third is its bronze strip, so the text is lifted into the dark band above it.
    "gg_rank_line":  (20,  92,  750, 46),
    # NAMED TO SORT AFTER gg_rank_line: siblings draw in hierarchy order, which is sorted
    # name order here, and as gg_rank_icon it drew UNDER the bar and vanished.
    "gg_rank_mark":  (18,  89,  44,  47),
    # The convoys panel's segmented bar, and its fill inside the frame's trough: the
    # trough is x 18..338, y 8..21 of the 356x29 file, measured off its alpha.
    "gg_bar_track":  (20,  140, 750, 29),
    "gg_rep_bar":    (38,  148, 714, 13),
    "gg_card_1":     (20,  170, 750, 120),
    "gg_card_2":     (20,  300, 750, 120),
    "gg_card_3":     (20,  430, 750, 120),
    "gg_prev":       (20,  596, 38,  38),
    "gg_next":       (732, 596, 38,  38),
    # WHAT THIS GUILD PAID YOU, AND FOR WHAT, on the Guilds tab only - the clear band
    # between the third card (ends y=550) and the pager (starts y=596).
    "gg_earned":     (20,  562, 750, 24),
    "gg_footer":     (20,  640, 750, 30),
}
for _i, _name in enumerate(TABS):
    PANEL_LAYOUT[_name] = (20 + _i * TAB_W, 56, TAB_W, TAB_H)
# ONE CLICK TO ANY GUILD: six glyph buttons between the arrows, the pager's own size and
# row, centred on the panel (256..534 around 395). The bar above them marks the page on
# screen; GGUI.draw_guild_buttons moves it along, so its x here is only where it starts.
GUILD_BTNS = ["gg_gtab_%d" % (_i + 1) for _i in range(6)]
GTAB_W, GTAB_STEP = 38, 48
for _i, _name in enumerate(GUILD_BTNS):
    PANEL_LAYOUT[_name] = (256 + _i * GTAB_STEP, 596, GTAB_W, GTAB_W)
PANEL_LAYOUT["gg_gsel"] = (256, 590, GTAB_W, 4)
# The Hell-Forge's bronze button bar behind the six, 80px past each end, drawn first
# (gg_gbar sorts before gg_gtab_*) so the buttons sit on it.
# 438 WIDE, NOT 310 (2026-09-30). At 310 only 16px of bar showed past each end button, and
# every race bar with end ornaments - the culture bar_small_buttons, Kislev's horse heads,
# the High Elf griffins, the Vows scrolls - drew them UNDER the first and last button. 438
# at x=176 clears them all (the widest, Kislev's heads, end at column 75) and stays clear
# of the pager (20..58, 732..770).
# 40 TALL, CENTRED on the plates' rings (rows 2..35 of 38, so y 598..631) with 3-4px of bar
# above and below. At 34 tall and y=598 the ring ended on the bar's last row and read as
# sliced off; see GBAR_LAYERS for why the bar now has a bottom rim at all.
PANEL_LAYOUT["gg_gbar"] = (176, 595, 438, 40)
# THE LOG'S FILTERS, in the band the reputation bar and its track use on the Guilds tab -
# both are hidden on the Log, and the first of its 21 lines starts at y=168.
LOG_FILTERS = ["gg_lf_all", "gg_lf_mine", "gg_lf_rivals", "gg_lf_ranks"]
for _i, _name in enumerate(LOG_FILTERS):
    PANEL_LAYOUT[_name] = (20 + _i * 120, 138, 110, 24)
# 21 SLOTS AT A 20px STEP, not 16 at 24. The Help tab truncates in silence - its
# builder stops at HELP_SLOTS - and the text had grown to about 21 lines. The last slot
# sits at y=568 and ends at 586, clear of the pager at y=596.
HELP_SLOTS = 21
for _i in range(HELP_SLOTS):
    PANEL_LAYOUT["gg_help_%02d" % (_i + 1)] = (20, 168 + _i * 20, 750, 18)

# One card, three children. The card template is its own file so the panel file
# does not carry three near-identical subtrees.
CARD_W, CARD_H = 750, 120
# THE GLYPHS ARE 74x74 AND WERE DRAWN AT 44. A downscale that steep turns a mark into
# a smudge, and the card has the room - 68 square sits inside a 120-tall card with 26
# clear above and below. The text column moves from x=72 to x=92 to clear it; both
# still stop short of the cost/buy column at x=596.
#
# NOW IN CA'S ROUND BRONZE HOLDER (CARD_ICON_LAYERS), 100x106 at the file's 62:66, with
# the glyph at 62 in its dark disc - still a downscale of the 74px source. The text
# column moves to x=114 to clear it; the description still ends at 594, short of 596.
# The price sits on the Hell-Forge's small title plate, 30 tall as CA draws it.
CARD_LAYOUT = {
    "card_icon": (8, 7, 100, 106),
    "card_name": (114, 12, 440, 26),
    "card_desc_1": (114, 44, 480, 20),
    "card_desc_2": (114, 64, 480, 20),
    "card_cost": (596, 10, 138, 30),
    "card_buy":  (596, 60, 138, 38),
}

# One standings row: guild, the player's rank, and who leads.
ROW_W, ROW_H = 750, 40
# REBALANCED TOWARDS THE LEADER COLUMN. That cell now carries the holder, their rank,
# what they gained on the round just past and a mark when the guild changed hands -
# which is the whole point of this tab - and at 250px it had about 37 characters, which
# "Leader: Zharr-Naggrund (Ironmaster)" already filled. The two columns to its left were
# the ones with room: a guild name is at most 22 characters and "You: Ironmaster (1240)"
# is 22.
#
# THE GUILD'S GLYPH OPENS THE ROW, at 36 in a 40-tall row - the largest square that
# fits. The name gives up 32px for it: the longest guild name is 22 characters.
ROW_LAYOUT = {
    "row_icon":   (6, 2, 36, 36),
    "row_guild":  (46, 8, 160, 24),
    "row_rank":   (212, 8, 196, 24),
    "row_leader": (416, 8, 324, 24),
}

# ------------------------------------------------- the standings faction list ----
# WHERE IT GOES. The six standings rows run y=170..430 (44 step, 40 tall) and the pager
# sits at y=596, so 440..590 is the only clear band on this tab and the list is exactly
# that band. It is not on the Guilds tab because three service cards already fill that
# one to y=550, which leaves 46px - two rows short of being worth a scrollbar.
LIST_XY = (20, 440)
LIST_W, LIST_H = 750, 150

# THE FOUR RESERVED NAMES. The engine does not offer a scroll widget; it recognises this
# arrangement - a clip window, a box inside it whose layout engine stacks the rows, and a
# slider with a draggable handle - and binds them to each other BY NAME. Renaming any of
# these four to something more descriptive silently produces a list that does not scroll.
# Structure read out of CA's ui/common ui/tab_completer.twui.xml.
#
# The slider is 16 wide at the right edge, so the clip window stops 20px short of it.
SLIDER_W = 16
LIST_LAYOUT = {
    "list_clip": (0, 0, LIST_W - SLIDER_W - 4, LIST_H),
    "vslider":   (LIST_W - SLIDER_W, 0, SLIDER_W, LIST_H),
}
# The handle's authored height is a starting size only - the engine resizes it to the
# fraction of the list that is on screen, which is what makes a scrollbar readable.
HANDLE_H = 40

# ONE FACTION, AND EXACTLY ONE COMPONENT. 24px tall, so six of the eight Chaos Dwarf
# factions are on screen at once and the slider has a real job rather than a decorative one.
FROW_W, FROW_H = LIST_W - SLIDER_W - 24, 24

# WHY THE ROW HAS NO CHILDREN, which is the one design decision in this list that is not
# obvious and cannot be undone casually.
#
# Everything else in this panel is a parent with child cells - a card has six, a standings
# row has three - and every one of them is placed by ABSOLUTE MoveTo out of GGUI.layout(),
# because the .twui.xml offsets do not position a runtime-created component. That is fine
# for a card, which never moves again after it is placed.
#
# A ROW INSIDE A SCROLLING LIST MOVES CONSTANTLY, and it is moved by the engine's own list
# layout, not by us. A child placed at an absolute screen position would stay exactly where
# it was put while its row scrolled out from under it - the name of the fourth faction
# hanging in the middle of the panel while the row it belongs to has gone. There is no
# event to re-run layout() on, because scrolling is engine-internal.
#
# So the row is ONE text component and the crest is drawn INSIDE the string with CA's
# [[img:path]][[/img]] markup - measured working from Lua-built strings, with a full path
# rather than a registry key, in 156 distinct paths across CA's own loc. Nothing to detach,
# because there is nothing to place. check_frow_has_no_children() keeps it that way.
#
# The cost is column alignment: a proportional font cannot be padded into columns, so the
# reputation and rank sit after the name rather than under each other. That is the price of
# a list that survives being scrolled.
FLAG_FALLBACK = "ui/flags/wh3_dlc23_chd_chaos_dwarfs/mon_24.png"

# CA's own slider art, the same textures ui/templates/parchment_slider_vertical.twui.xml
# draws - the template CA's own listview uses. Referenced, never copied: a vanilla path
# costs this pack no bytes and cannot drift from a duplicate after a patch.
SLIDER_TRACK = "ui/skins/default/slider_vertical_mid.png"
SLIDER_HANDLE = "ui/skins/default/slider_vertical_handle.png"
SLIDER_HANDLE_UNDER = "ui/skins/default/slider_vertical_handle_underlay.png"

# The panel title plate clips silently at about 19 characters, so the title is a
# short constant and the guild name goes in gg_rank_line, a plain text component.
PANEL_TITLE = "The Great Guilds"

# CA components this mod reaches for but does not own. The opener is created as a
# child of one of these, so they must be exempt from the "declared in our xml"
# check - the same OURS-versus-HOST split tools/check_rite_panel_ui.py uses.
# CA components this mod reads but does not own. The opener used to be CREATED on
# button_rituals, which is a member of a RadialList layout group - a layout group owns
# its children's positions, so MoveTo never got to have the fight and the button never
# drew. The opener is now created on the UI root and resources_bar is only a RULER,
# read for coordinates. A name here is unvalidated against CA, so keep the list short.
HOST_COMPONENTS = {"resources_bar"}


def guid_for(name):
    """Deterministic per-name GUID in this file's range. 8-4-4-16, as CA writes them."""
    n = _ORDER.index(name) + 1
    return "%s%04X-D000-4000-B%015X" % (GUID_PREFIX, n, n)


_ORDER = (["root", "derpy_gg_panel"] + sorted(PANEL_LAYOUT)
          + ["derpy_gg_card"] + sorted(CARD_LAYOUT)
          + ["derpy_gg_row"] + sorted(ROW_LAYOUT)
          + ["listview"] + sorted(LIST_LAYOUT) + ["handle"]
          + ["derpy_gg_frow"]
          + ["gg_opener"])


# ------------------------------------------------------------------- art ---
# EVERY ONE OF THESE FILES SHIPPED WITH NO ART AT ALL. Four .twui.xml files, zero
# <componentimages> between them, against 106 imagepath lines across the Zharr
# Exchange's three. The whole UI was invisible geometry: the opener button was
# created, positioned, RegisterTopMost'd, read back at the coordinates it asked for -
# and drew nothing, because a component with no image is nothing to draw.
#
# Text-bearing cells are the exception and are deliberately left bare: SetStateText
# renders without any image, and CA's own panels leave label cells transparent.
# What needs a texture is anything that must READ as a surface - the panel frame, a
# clickable card, a row band, and above all a button.
#
# Every path below is asserted to exist in the game's ui packs by check(); a path
# that does not resolve draws a blank square in silence.
PLATE = "ui/skins/default/button_round_medium_%s.png"

# The Exchange's opener uses icon_trade. This one is the Tribute Halls - the guild
# hall, which is what the panel is about - and it is a BUILDING icon at 74x74 rather
# than a 29x29 spell-lore glyph, so it stays sharp at 44. The Lore of Hashut mark
# that was here first was both off-topic and upscaled 1.5x.
OPENER_ICON = "ui/campaign ui/derpy_gg_icons/crest.png"

# 7, not 10. At 10 the glyph drew at 24x24 inside a 44px plate - a third of the
# button was rim. 7 leaves the plate's edge clear and gives the mark 30px.
_ICON_INSET = 7

OPENER_LAYERS = [
    {"path": PLATE % "underlay", "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0,
     "dock": None},
    {"path": PLATE % "active", "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0,
     "dock": None},
    {"path": OPENER_ICON, "offset": (_ICON_INSET, _ICON_INSET),
     "dw": -2 * _ICON_INSET, "dh": -2 * _ICON_INSET, "margin": 0, "dock": "Center"},
]
# Only the plate between underlay and glyph lights on hover. A <hover> state with no
# transitionmap edge pointing at it is never entered - EU._state wires that pair.
OPENER_HOVER = [
    {"path": PLATE % "underlay", "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0,
     "dock": None},
    {"path": PLATE % "hover", "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0,
     "dock": None},
    {"path": OPENER_ICON, "offset": (_ICON_INSET, _ICON_INSET),
     "dw": -2 * _ICON_INSET, "dh": -2 * _ICON_INSET, "margin": 0, "dock": "Center"},
]
OPENER_SOUND = "UI_GBL_TMP_Round_Medium_Button"

# AND EVERY OTHER BUTTON. soundcategory is the only route to a click sound - there is no
# script call for it, common.trigger_soundevent takes a sound EVENT and CA's UI clicks are
# driven by these categories - and only the opener had one, so the close cross, the tabs,
# the pager and every Buy button clicked in silence. Categories chosen to match the art:
# the round plates take the round-button sound, the text plates the square-text one, and
# Buy takes CA's purchase sound, the same one the Zharr Exchange's buy button uses.
# check() proves all three appear in CA's own ui packs; an invented one is silent.
SOUND_ROUND = "UI_GBL_TMP_Round_Small_Button"
SOUND_TAB = "UI_GBL_TMP_Square_Large_Text_Button"
SOUND_BUY = "UI_GBL_HUD_Purchase"

# THE PANEL'S GROUND. A tiled texture and a frame said "a mod panel"; this says whose
# panel it is. CA's Tower of Zharr tier-1 background - the pillared hall the Sorcerer-
# Prophets sit in - read out of CA's ui packs and REFERENCED, never copied in: a vanilla
# path costs this pack no bytes and cannot drift from a duplicate of itself after a patch.
#
# Chosen out of the 20 Chaos Dwarf background candidates CA ships (all extracted and
# measured; see the contact sheet in the session write-up). Three things decided it:
#
#   ASPECT. The panel is 790x700, 1.13:1. This art is 1920x1278, 1.50:1, so it squashes
#   by 1.33x - the least of any candidate. The Hell Forge backgrounds are 1.78:1 and 2.0:1
#   (1.58x and 1.78x), the event pictures 1.78:1 at 380x214, and the battle maps 3.1:1.
#
#   RESOLUTION. It is larger than the panel in both axes, so it downsamples. Everything in
#   ui/eventpics/chd (380x214) and ui/frontend ui/battle_map_images (468x150) would be
#   upscaled 2x to 4.7x, which is visibly soft - and those are the best-looking Chaos Dwarf
#   pictures CA ships. They are simply not background-sized.
#
#   BRIGHTNESS. The Help tab draws body text straight onto the panel with no plate between
#   it and the ground, so what matters is the bright end, not the average. Measured at
#   panel size under the scrim below: p99 luminance 34, peak 131 - within a point of the
#   Hell Forge ground this replaced. The tech tree's Zharr-Naggrund (avg 67,67,67) and all
#   seven event pictures (avg 62-119) are far too bright to carry unplated text.
#
# And it is symmetric and architectural, which is what a hall of six guilds should be.
PANEL_ART = "ui/skins/default/dlc23_tower_of_zharr/tier_01_background.png"

# A SCRIM over the art, not a dimmed copy of the file. 1x1_blank_white tinted is the idiom
# the reputation track already uses; shipping a darkened duplicate of a CA texture would
# be a second copy to keep in step with every patch.
#
# 0x77, not the 0x55 the Hell Forge ground used. This art is brighter (avg 27,23,23
# against 20,17,13) and its pillars carry specular highlights the furnace did not, so the
# same scrim would have been a quieter picture behind LESS readable text. Measured at
# panel size: 0x55 leaves p99 42 / peak 164, 0x77 brings it to 34 / 131, which is what the
# shipped ground measured. 0x88 reaches 29 / 115 and starts flattening the pillars.
PANEL_SCRIM = "#00000077"

# DO NOT OVERSCAN THE GROUND. Tried and reverted, MEASURED IN GAME 2026-09-12: the art
# and its scrim were drawn at 822x732 at offset (-16,-16) to crop the picture's own dead
# outer rows away, on the assumption that the engine clips a child image to its component.
# IT DOES NOT. The image simply draws where it is told, so the panel gained a 16px black
# ring OUTSIDE its gold frame - the scrim, painted over the campaign map. The outermost
# thing a panel draws must be the frame.
#
# This is the opposite of the shape the rest of the file uses and that is why the file
# uses it: CARD_ICON_LAYERS, ROUND_LAYERS and plate() all pass NEGATIVE dw/dh to draw
# INSIDE the component, which is safe for exactly the same reason. An image bigger than
# its component escapes; an image smaller than it cannot.
#
# The complaint that started it - a dead strip along the panel's bottom, the art's own
# masonry plinth stopping about 10 rows short of its file edge - is real but small, and the
# frame's 9-slice margin is the knob for it if it ever matters. Nothing here may exceed
# PANEL_W x PANEL_H; check() enforces it.

# THE GROUND STOPS WHERE THE BORDER'S LINE STARTS. panel_back_border.png is transparent
# for its outer 3 pixels (alpha 0,0,0,25 then 255 at pixel 4, measured on every side and
# the corners), so a ground drawn to the component's edge showed a strip of picture
# OUTSIDE the brown line - 3px at 100% UI scale, 5-10 at the scales players use. Inset,
# not an outward border: see the overscan note above.
GROUND_INSET = 4

# THE MAIN MENU'S DRIFTING SMOKE, over the art. CA's frontend main.twui.xml draws it with
# smoke_overlay_t0 on a component named "smoke" at "8.00,10.00,0.00,0.00" - the idle state's
# values; hover, selected and new states drop the first to 4, 2 and 1. The shader is NOT in
# the uicomponent.html shader table, so the four numbers are copied, never reasoned about.
# The mask is not the menu's: porthole_back.png is an opaque grey texture that covers a
# whole screen there and would cover the art here. panel_back_smoke.png - flat black at
# alpha 102, so the shader paints the smoke - is what CA puts under a PANEL (the Silent
# Sanctum confirm box, Oxyotl's drop-down). Tint is the ember of CA's Chaos Dwarf narrative
# panel smoke. Under the scrim, so the scrim that was tuned for text dims it too.
# SEEN IN GAME 2026-09-30 at the menu's idle 8.00 and alpha FF: a dense orange mottle over
# the whole ground, "too strong and too compact". Now 2.00 (the menu's own selected-state
# value) and alpha 3C (the Silent Sanctum's, CA's panel-sized use) - both CA's numbers.
PANEL_SMOKE = {"path": "ui/skins/default/panel_back_smoke.png",
               "offset": (GROUND_INSET, GROUND_INSET), "dw": -2 * GROUND_INSET,
               "dh": -2 * GROUND_INSET, "margin": 0, "colour": "#FF822E3C",
               "shader": "smoke_overlay_t0", "shader_vars": "2.00,10.00,0.00,0.00",
               "dock": None}

# Body, art, smoke, scrim, frame - in that order, because each draws over the one before it.
PANEL_LAYERS = [
    # The plain tile STAYS, underneath. The art above is opaque and hides it completely,
    # and that is the point: a panel whose only ground is one texture has no ground at all
    # on the day that texture moves.
    {"path": "ui/skins/default/panel_back_tile.png",
     "offset": (GROUND_INSET, GROUND_INSET), "dw": -2 * GROUND_INSET,
     "dh": -2 * GROUND_INSET, "margin": 5, "tile": True, "dock": None},
    {"path": PANEL_ART,
     "offset": (GROUND_INSET, GROUND_INSET), "dw": -2 * GROUND_INSET,
     "dh": -2 * GROUND_INSET, "margin": 0, "dock": None},
    PANEL_SMOKE,
    # SAME RECT AS THE ART, deliberately. The scrim is what makes this ground dark enough
    # to carry the Help tab's unplated text; a strip of art the scrim misses is that text
    # losing its contrast on one edge.
    {"path": "ui/skins/default/1x1_blank_white.png",
     "offset": (GROUND_INSET, GROUND_INSET), "dw": -2 * GROUND_INSET,
     "dh": -2 * GROUND_INSET, "margin": 0, "colour": PANEL_SCRIM,
     "dock": None},
    # The border draws over the body's edge last, so nothing can leave a bare strip.
    {"path": "ui/skins/default/panel_back_border.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 30, "tile": True, "dock": None},
]

# ------------------------------------------------ the Chaos Dwarf dressing ---
# CA'S OWN CHAOS DWARF FRAMES, referenced out of its ui packs and never copied in, and
# every margin copied from the component that draws the same file in CA's own panel -
# hellforge_panel_unit_caps_tab, hellforge_panel_category_tab, hellforge_panel_main and
# military_convoys. CA reuses these outside the Chaos Dwarf panels too: Nurgle's plague
# panel wears sub_title.png and the High Elves' Valiant Imperatives the large square
# button, so a guild panel wearing them is the house style rather than a borrowing.
HF = "ui/skins/default/dlc23_chd_hell_forge/"

# THE TITLE PLATE. CA's panels name ui/skins/default/panel_title.png and the game swaps
# in the player's own culture's copy - ui/skins/wh3_dlc23_chd_chaos_dwarfs/panel_title.png
# is the spiked one the Hell-Forge shows, and fifteen cultures ship their own. So this is
# the DEFAULT path on purpose: a Dwarf player gets the Dwarf plate, as on CA's panels.
# Margins are the Hell-Forge header's, which draws this file at 600 wide.
TITLE_PLATE = "ui/skins/default/panel_title.png"
TITLE_LAYERS = [
    {"path": TITLE_PLATE, "offset": (0, 0), "dw": 0, "dh": 0,
     "margin": (0, 165, 0, 165), "tile": True, "dock": None},
]

# THE HEADER BAR - the Hell-Forge's unit-cap group title, the bar "Melee Infantry" sits
# on. Its dark band is rows 9..32 of 54 and the rest is a bronze strip, so the text is
# lifted by RANK_TY: bottom padding 11 moves a Center-aligned line up 5.5px, onto the
# band's middle at 46px tall. RANK_TX clears the round holder over the bar's left end.
RANK_BAR_LAYERS = [
    {"path": HF + "cap_title_holder.png", "offset": (0, 0), "dw": 0, "dh": 0,
     "margin": (0, 50, 0, 60), "tile": True, "dock": None},
]
RANK_TX, RANK_TY = "50.00,0.00", "0.00,11.00"

# A GLYPH IN CA'S ROUND HOLDER, placed by OFFSET WITH NO DOCKPOINT: on an image the two
# are cumulative (docs/CUSTOM_UI.md), so an inset plus dock Center draws the glyph off
# centre by its own inset.
# NOT the Hell-Forge's cap_category_iconm_holder: it is 62x66, so the 100x106 card box drew
# it 1.6x its size, soft in game (2026-09-30). The labour economy's surplus ring is 129px,
# drawn smaller than its file; its dark disc is centred.
ICON_HOLDER = "ui/skins/default/chd_labour_economy/surplus_holder.png"
ICON_HOLDER_CX, ICON_HOLDER_CY = 0.5, 0.5


def holder_layers(w, h, glyph, path, tag=""):
    """The round holder at w x h and a glyph-px square centred on its disc."""
    # "" is the Chaos Dwarf holder, and is what the module-level layers below are built
    # from before FRAMES exists.
    holder, cx, cy = (frame(tag)["holder"] if tag
                      else (ICON_HOLDER, ICON_HOLDER_CX, ICON_HOLDER_CY))
    ox = int(round(cx * w - glyph / 2.0))
    oy = int(round(cy * h - glyph / 2.0))
    return [
        {"path": holder, "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0,
         "dock": None},
        {"path": path, "offset": (ox, oy), "dw": glyph - w, "dh": glyph - h,
         "margin": 0, "dock": None},
    ]


# A CARD IS A RECESS, NOT A BUTTON - and now it is the Hell-Forge's own recess, the
# bronze plate behind each unit group, sliced left and right only as CA slices it.
# Measured mean luminance 52 (top 75): FFF8D7 text on it is about 11:1 and the C9BFA8
# descriptions about 5:1 at the brightest edge.
#
# A SERVICE THAT IS RUNNING LIGHTS ITS CARD (asked for 2026-09-26, after the rites panel's
# look): CA's own "active" art over the plate - the Hell-Forge's red heat glow behind the
# icon and the Tower of Zharr's glowing rim around the card. Both layers ship as CLEAR -
# our own fully transparent file - and the Lua swaps the glow in by index, so a card is
# unlit unless the Lua says otherwise, including the pick card built from this template.
#
# NOT CA's icon_blank.png, which this first used. It is 24x24, and the rim layer's
# 9-slice margin is 40: a margin larger than its texture samples OUTSIDE it, into
# whatever the game's texture atlas holds beside it. SEEN IN GAME 2026-09-26 as streaks,
# arrows and red and blue bars across every card on three tabs - and invisible in the
# preview, whose renderer reads the PNG alone and has no atlas to bleed from.
# check_margins_fit_textures() now refuses any layer whose margins exceed a texture it
# can hold, including the ones the Lua swaps in.
CLEAR = "ui/campaign ui/derpy_gg_icons/clear.png"
CLEAR_PX = 128
CARD_OFF = CLEAR
CARD_HEAT = HF + "heat_glow.png"
CARD_RIM = "ui/skins/default/dlc23_tower_of_zharr/district_complete_glow_02.png"
CARD_LAYERS = [
    {"path": HF + "cap_group_background.png", "offset": (0, 0), "dw": 0, "dh": 0,
     "margin": (0, 24, 0, 24), "tile": True, "dock": None},
    # From the card's left edge to twice the icon holder's middle (58): the glow's bright
    # centre sits behind the name, where the eye lands, and its left half behind the holder.
    # Nothing may draw outside the card - the engine does not clip.
    {"path": CARD_OFF, "offset": (0, 0), "dw": 300 - CARD_W, "dh": 0, "margin": 0,
     "dock": None},
    {"path": CARD_OFF, "offset": (0, 0), "dw": 0, "dh": 0, "margin": (40, 40, 40, 40),
     "dock": None},
]
CARD_HEAT_INDEX, CARD_RIM_INDEX = 1, 2

# THE REPUTATION TRACK is the convoys panel's segmented bronze bar, and the fill is its
# own fill texture drawn in the frame's trough (gg_rep_bar sits inside gg_bar_track).
# The middle tiles, as CA's does, so the segment marks keep their spacing at 750 wide.
REP_TRACK_LAYERS = [
    {"path": "ui/skins/default/dlc23_chd_military_convoys/"
             "military_convoys_completed_convoys_bar.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": (0, 20, 0, 20), "tile": True,
     "dock": None},
]

# The per-guild glyph on each card. The file ships ONE placeholder and the campaign
# Lua swaps it per service with SetImagePath - the card is a single template used by
# all six guilds, so the icon cannot be baked in. GGUI.GUILD_ICON holds the real
# mapping and check() proves every path in it exists. The glyph is image CARD_ICON,
# over the holder; GGUI.CARD_ICON_INDEX must say the same, which check() pins.
CARD_GLYPH = 62
CARD_ICON_LAYERS = holder_layers(CARD_LAYOUT["card_icon"][2], CARD_LAYOUT["card_icon"][3],
                                 CARD_GLYPH, "ui/campaign ui/effect_bundles/income.png")
CARD_ICON = 1

# The same holder over the header bar's left end, repainted to the guild on screen.
RANK_GLYPH = 28
RANK_ICON_LAYERS = holder_layers(PANEL_LAYOUT["gg_rank_mark"][2],
                                 PANEL_LAYOUT["gg_rank_mark"][3], RANK_GLYPH,
                                 "ui/campaign ui/derpy_gg_icons/brass.png")

# The price, on the Hell-Forge's small title plate, drawn at the full box. The plate's
# art stops at row 24 of 30 (the rest is shadow), so its middle is ~2px above the box's -
# and so is the game font's, which draws a Center-aligned line high. A 3px drop that
# centred the plate on the box put the number on its top rim, SEEN IN GAME 2026-09-26.
COST_LAYERS = [
    {"path": HF + "sub_title.png", "offset": (0, 0), "dw": 0, "dh": 0,
     "margin": (0, 12, 0, 12), "tile": True, "dock": None},
]

# The bronze bar the six guild buttons sit on, as the Hell-Forge's category buttons do.
# TWO HALVES, THE LOWER ONE y_flipped. The art has a rim and angled caps along its top only:
# CA docks it on the Hell-Forge's bottom border, which hides the open edge. Mid-panel that
# edge read as the buttons being cut off - SEEN IN GAME 2026-09-28, twice. Each half is
# squashed 34->20 like the tab plates, sliced left and right only.
_GBAR_HALF = PANEL_LAYOUT["gg_gbar"][3] // 2
GBAR_LAYERS = [
    {"path": HF + "buttons_holder.png", "offset": (0, 0), "dw": 0, "dh": -_GBAR_HALF,
     "margin": (0, 20, 0, 20), "dock": None},
    {"path": HF + "buttons_holder.png", "offset": (0, _GBAR_HALF), "dw": 0,
     "dh": -_GBAR_HALF, "margin": (0, 20, 0, 20), "vflip": True, "dock": None},
]

# THE TABS: the Hell-Forge's large square button. Sliced LEFT AND RIGHT ONLY, so it
# squashes vertically as one picture. Its frame is rows 3..10 and 69..78 of 82, and
# slicing those at full size left 12px of red at 34px tall - SEEN IN GAME 2026-09-26: the
# caption ran over both frame lines. Squashed, the frames are 3-4px and the red is ~24px.
# The middle stretches rather than tiles, so the gradient keeps its shading.
# The open tab wears _selected, set from GGUI.TAB_PLATE by the Lua - the file cannot
# know which tab is open.
TAB_PLATE = HF + "button_square_extra_large_%s.png"
TAB_STATES = ("active", "hover", "selected", "selected_hover")


def tab_plate(state):
    return [{"path": TAB_PLATE % state, "offset": (0, 0), "dw": 0, "dh": 0,
             "margin": (0, 12, 0, 12), "dock": None}]

# The same one-placeholder idea for the Leaderboard row's glyph, repainted per guild.
ROW_ICON_LAYERS = [
    {"path": "ui/campaign ui/derpy_gg_icons/brass.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
]

# CA's gold, the colour of the counts on these buttons and on the HUD opener.
GOLD = "#FFD37AFF"
GSEL_LAYERS = [
    {"path": "ui/skins/default/1x1_blank_white.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "colour": GOLD, "dock": None},
]

# A standings row is a BAND, not a button - a flat tint, the same idiom as the
# reputation track. It was a 750px-wide stretched button plate, which is the exact
# smear the cards were, six times over.
ROW_LAYERS = [
    {"path": "ui/skins/default/1x1_blank_white.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "colour": "#00000055",
     "dock": None},
]

# Hashut's mark beside the title. The panel is otherwise CA's generic parchment,
# and one crest is what makes it read as belonging to the Dark Lands rather than to
# any panel in the game.
CREST_LAYERS = [
    {"path": "ui/campaign ui/derpy_gg_icons/crest.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": "Center"},
]

DIVIDER_LAYERS = [
    {"path": "ui/skins/default/panel_back_divider.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
]


# The pager and the close button are round: a chevron and a cross both want a disc,
# and button_square_medium stretched into one read as unfinished. Same plate family
# as the opener, one size down.
ROUND_PLATE = "ui/skins/default/button_round_small_%s.png"
ROUND_LAYERS = [
    {"path": ROUND_PLATE % "active", "offset": (0, 0), "dw": 0, "dh": 0,
     "margin": 0, "dock": None},
]
ROUND_HOVER = [
    {"path": ROUND_PLATE % "hover", "offset": (0, 0), "dw": 0, "dh": 0,
     "margin": 0, "dock": None},
]
_X = 7
CLOSE_LAYERS = ROUND_LAYERS + [
    {"path": "ui/skins/default/icon_cross_small.png", "offset": (_X, _X),
     "dw": -2 * _X, "dh": -2 * _X, "margin": 0, "dock": "Center"},
]
CLOSE_HOVER = ROUND_HOVER + [
    {"path": "ui/skins/default/icon_cross_small.png", "offset": (_X, _X),
     "dw": -2 * _X, "dh": -2 * _X, "margin": 0, "dock": "Center"},
]

# THE GUILD BUTTONS: the pager's round plate, the guild's glyph inset on it. The plate is
# for the count, not decoration - drawn straight onto the pale glyph, the gold digit was
# lost in it (seen in preview_guilds_panel.py's gg_guilds.png); on the plate it has the
# dark rim the HUD opener's count sits on. The glyph is a placeholder the Lua repaints by
# index, GGUI.GUILD_BTN_ICON, which check() pins to GTAB_ICON.
GTAB_INSET = 5
GTAB_ICON_PATH = "ui/campaign ui/derpy_gg_icons/brass.png"
GTAB_LAYERS = ROUND_LAYERS + [
    {"path": GTAB_ICON_PATH, "offset": (GTAB_INSET, GTAB_INSET),
     "dw": -2 * GTAB_INSET, "dh": -2 * GTAB_INSET, "margin": 0, "dock": "Center"},
]
GTAB_ICON = [l["path"] for l in GTAB_LAYERS].index(GTAB_ICON_PATH)

# The tabs and each card's Buy button are BUTTONS: they carry a click
# handler and nothing else. With no image and no label they were live click targets
# that drew nothing - measured through the wh3 bridge with every one of them present,
# correctly positioned and vis=true, and invisible on screen.
BTN_PLATE = "ui/skins/default/button_square_medium_text_%s.png"

# THE PLATE'S BOTTOM THIRD IS TRANSPARENT, and that is why every caption looked like
# it overflowed the bottom of its button. Measured from the extracted PNG: the file
# is 310x46 and its visible pill occupies rows 3..32 - rows 33..45 are empty. Stretch
# that into a 38px box and the pill fills only the top ~65%, while text centred in the
# BOX centres on the box. The caption is not too big for the button: "Buy" measures
# 31x18 in a 138x38 component, live through the wh3 bridge. It was sitting below the
# only part of the plate that is actually drawn.
#
# So draw the image TALLER than the component and offset it up, until the PILL fills
# the box. Then centred text is centred on what the player can see. Negative image
# offsets are ordinary - 36% of CA's 74,321 in ui3.pack carry one.
PLATE_TOP, PLATE_BOT, PLATE_PX = 3.0, 33.0, 46.0        # measured alpha rows
_PLATE_SPAN = (PLATE_BOT - PLATE_TOP) / PLATE_PX        # 0.652 of the texture


def plate_fit(h):
    """(dh, offset_y) making the plate's visible pill exactly fill a box h tall."""
    img_h = h / _PLATE_SPAN
    return int(round(img_h - h)), int(round(-PLATE_TOP / PLATE_PX * img_h))


def plate(h, state):
    dh, dy = plate_fit(h)
    return [{"path": BTN_PLATE % state, "offset": (0, dy), "dw": 0, "dh": dh,
             "margin": 8, "dock": None}]


# The convoys bar's own fill, 32x13 and flat along its length, so stretching it to the
# fraction earned is exact. The Lua narrows the component; the image follows it.
REP_BAR_LAYERS = [
    {"path": "ui/skins/default/dlc23_chd_military_convoys/"
             "military_convoys_completed_convoys_bar_fill.png",
     "offset": (0, 0), "dw": 0, "dh": 0, "margin": 0, "dock": None},
]


# ------------------------------------------------------ the race frames ---
# EVERY RACE IN ITS OWN CHROME (asked for 2026-09-29). Everything above is the Chaos
# Dwarf dressing, and until now every race wore it: an Empire player's guild hall was
# framed in Hell-Forge bronze and Tower of Zharr glow. The ground and the glyphs were
# already per race; the frames were not.
#
# A SECOND .twui.xml PER RACE, not a runtime repaint. The 9-slice margins live in the file
# and SetImagePath cannot change them, so a repaint would stretch each race's art through
# the Chaos Dwarf margins. derpy_gg_panel_emp.twui.xml / derpy_gg_card_emp.twui.xml carry
# the same components under the same GUIDs with only their images changed, and the Lua
# creates the reader's copy (GGUI.frame_path). check() refuses a copy whose tree differs.
#
# CULTURE SKINS DO NOT DO THIS BY THEMSELVES. ui/skins/<culture>/X.png replaces
# ui/skins/default/X.png, but they carry only a handful of generic files - Empire and the
# Dark Elves override none - so every path below is named outright. Direct paths into a
# culture skin or into ui/skins/warhammer2/ are CA's own habit: 51 twui files do it.
#
# SOURCES, all CA art, referenced and never copied:
#   _emp  Gardens of Morr (tabs, holder, price, button bar), Great Temple of Ulric (header,
#         card, reputation), Gunnery School (the gold rim a running service wears)
#   _dwf  Book of Grudges (tabs, holder, reputation fill), the Dwarf skin's Mortuary Cult
#         and button-bar pieces, Malakai's rune glow for the rim
#   _hef  the Intrigue Court (tabs, card, header), Asur Domination (holder, price, reputation)
#   _cth  the Tiger Court (tabs, holder, card), Shang Yang (header, price), the Cathay skin
#   _ksl  the Ice Court and Orthodoxy (tabs, card, price, rim, reputation), Devotion (header)
#   _brt  the Vows (header, price, tabs), Chivalry (reputation), the Bretonnian skin's
#         heraldic tile and border for the card
#   _def  Malus Darkblade (tabs, card, header, holder), Murderous Prowess (reputation, price),
#         Hag Graef's bar, and the Dark Elf rite flare as the running-service glow
# Margins are CA's where CA draws the file (py scratch ca_margins, 2026-09-29) and measured
# off the file where it does not. Tab captions turn yellow on the open tab, so no selected
# plate may be light: the Dwarfs' gold banner failed that and the open Dwarf tab is blue.
_D = "ui/skins/default/"
_W2 = "ui/skins/warhammer2/"
# ONE GREY GLOW, tinted per race, for the six races with no glow of their own: Ulric's radial
# blur, which falls off from the middle to nothing at every edge the way the Hell-Forge's
# heat_glow does and has no colour to fight the tint. NOT Malakai's tab_shadow, used first: it
# is a flat plateau with 20px soft edges, and stretched to 300px it drew a lit BLOCK that
# stopped a third of the way across the card.
_GLOW = _D + "dlc29_great_temple_of_ulric/fx_radial_blur.png"
_TUTGLOW = _D + "tutglow_square.png"
# The dimmed standard state of a tab that has one texture for every state: hover is the
# same art at full brightness. Colour multiplies, so this is the only direction it goes.
_DIM = "#B4B4B4FF"
_HEF_TAB = _D + "dlc27_hef_dragonships/wh3_hef_dragonships_header_tooltip.png"
_BRT_TILE = "ui/skins/wh_main_brt_bretonnia/legacy/panel_back_tile.png"


def _L(path, margin=0, tile=False, colour=None, offset=(0, 0), dw=0, dh=0):
    lay = {"path": path, "offset": offset, "dw": dw, "dh": dh, "margin": margin,
           "dock": None}
    if tile:
        lay["tile"] = True
    if colour:
        lay["colour"] = colour
    return lay


# THE REPUTATION FILL'S RECT IS FIXED - gg_rep_bar at 38,148 714x13, which the Lua narrows
# to the fraction earned - so each race's track is drawn to put ITS trough there instead.
# trough is (x0, y0, x1, y1) in the texture, measured off its alpha and luminance. The ends
# keep their native width (the L/R margin) and the height scales to fit 13 rows into the
# trough. An end cap wider than the 18px the track has left of the fill is clamped at the
# track's edge rather than drawn outside it (the engine does not clip), and the fill then
# overlaps that cap by the difference.
_TRACK_W, _TRACK_H = 750, 29          # PANEL_LAYOUT["gg_bar_track"], checked in check()
_FILL_IN = (18, 8, 714, 13)           # gg_rep_bar inside gg_bar_track


def fit_track(path, size, trough, tile=False):
    W, H = size
    x0, y0, x1, y1 = trough
    fx, fy, fw, fh = _FILL_IN
    sy = min(float(fh) / (y1 - y0), float(_TRACK_H) / H)
    h = int(round(H * sy))
    dy = max(0, min(_TRACK_H - h, int(round(fy - y0 * sy))))
    dx = max(0, fx - x0)
    w = min(_TRACK_W - dx, fx + fw - dx + (W - x1))
    return [_L(path, (0, W - x1, 0, x0), tile, offset=(dx, dy),
               dw=w - _TRACK_W, dh=h - _TRACK_H)]


# tab: "layers" and "hover" are the two states the file draws; "selected" and
# "selected_hover" are PATHS the Lua swaps into those same slots for the open tab, so they
# are drawn through the slot's margins and colour - check_margins_fit_textures() checks
# them against those. Every state has the same number of layers.
FRAMES = {
    "": {
        "card": CARD_LAYERS[0], "heat": (CARD_HEAT, "#FFFFFFD0"),
        "rim": (CARD_RIM, (40, 40, 40, 40), None),
        "holder": (ICON_HOLDER, ICON_HOLDER_CX, ICON_HOLDER_CY),
        "cost": COST_LAYERS, "rank": RANK_BAR_LAYERS, "rank_tx": RANK_TX, "rank_ty": RANK_TY,
        "gbar": GBAR_LAYERS,
        "tab": {"layers": tab_plate("active"), "hover": tab_plate("hover"),
                "selected": [TAB_PLATE % "selected"],
                "selected_hover": [TAB_PLATE % "selected_hover"]},
        "track": REP_TRACK_LAYERS, "fill": REP_BAR_LAYERS,
    },
    # THE RACE FRAMES WERE REBUILT 2026-09-30 after an in-game Dwarf screenshot: pieces cut
    # off (half-strips of larger frames, one-sided bookmark tabs, bar ends under the first
    # and last button) and pieces soft (holders drawn 1.3-2.3x their file, a card 3.3x its
    # height). Every layer below is either drawn at or under its file's size, or stretched
    # only along content that is flat in that direction. TILE REPEATS AT THE FILE'S SIZE IN
    # BOTH AXES - it does not scale - so a tiled layer drawn shorter than its file loses its
    # bottom rows unless top/bottom margins keep them.
    "_emp": {
        "card": _L(_D + "dlc29_great_temple_of_ulric/text_bgr.png", (25, 20, 25, 20), True),
        "heat": (_GLOW, "#FFB45A50"),
        "rim": (_D + "dlc25_gunnery_school/frame_unit_card_selected.png",
                (25, 25, 25, 25), None),
        # Ulric's hexagon plate, 119x99: drawn 0.84 across, 1.07 down.
        "holder": (_D + "dlc29_great_temple_of_ulric/plate.png", 0.51, 0.5),
        # Not tiled: tiled at 30px the 47px slot lost its bottom border.
        "cost": [_L(_D + "dlc25_gardens_of_morr/don_square_slot_empty.png", (0, 25, 0, 25))],
        # Ulric's bronze frame, middle TILED between 83/85px ends - the edge columns whose
        # join matches best - where it was stretched 3.3x into streaks.
        "rank": [_L(_D + "dlc29_great_temple_of_ulric/button_frame.png", (12, 85, 13, 83), True)],
        "rank_tx": RANK_TX, "rank_ty": "0.00,0.00",
        "gbar": [_L(_D + "dlc29_great_temple_of_ulric/button_frame.png", (12, 85, 13, 83), True)],
        "tab": {"layers": [_L(_D + "dlc25_gardens_of_morr/don_square_button_default.png",
                              (0, 25, 0, 25))],
                "hover": [_L(_D + "dlc25_gardens_of_morr/don_square_button_hover.png",
                             (0, 25, 0, 25))],
                "selected": [_D + "dlc25_gardens_of_morr/don_square_button_selected.png"],
                "selected_hover":
                    [_D + "dlc25_gardens_of_morr/don_square_button_selected_hover.png"]},
        # A complete slot frame (7px border every side); its dark inside y 7..21, x 7..742
        # holds the 714x13 fill. The old progress_bar_bg showed no frame at all.
        "track": [_L(_D + "dlc25_gardens_of_morr/don_square_slot_empty.png", (7, 25, 7, 25),
                     True)],
        # Every column identical, already 13 tall: stretched along its length it loses
        # nothing. A plain amber bar; the Chaos Gifts path is only where CA keeps it.
        "fill": [_L(_D + "chaos_gifts/souls_bar_fill_undiveded.png")],
    },
    "_dwf": {
        # Malakai's dark ground sliced as CA slices it (25, tiled), in the Book of Grudges'
        # complete red double-line frame - diamonds at all four corners. unit_info_frame,
        # before it, had a gap in its top line and was drawn 1.44x.
        "card": _L(_D + "dlc25_malakais_adventures/text_bg.png", (25, 25, 25, 25), True),
        "card_extra": [_L(_D + "dlc25_book_of_grudges/book_of_grudges_unit_pack_frame.png",
                          (15, 15, 15, 15), True)],
        "heat": (_GLOW, "#FF8A2A50"),
        "rim": (_D + "dlc25_malakais_adventures/tab_hover_glow.png", (35, 35, 35, 35), None),
        # Malakai's diamond slot, 109x110: drawn under its size. The Grudges hexagon was
        # 44x51 drawn 2.3x.
        "holder": (_D + "dlc25_malakais_adventures/button_slot.png", 0.5, 0.5),
        # 13 top/bottom, measured: CA's 15 fills all 30 rows. Complete on four sides, where
        # the mortuary-cult strips were the top and bottom halves of a larger frame. The
        # frame is open inside, so a dark ground goes under it: without one a running
        # card's rim glow ran behind the price at 2.3:1.
        "cost": [_L(_D + "1x1_blank_white.png", colour="#140E0AE6", offset=(2, 2),
                    dw=-4, dh=-4),
                 _L(_D + "dlc25_book_of_grudges/book_of_grudges_unit_pack_frame.png",
                    (13, 15, 13, 15))],
        "rank": [_L(_D + "dlc25_malakais_adventures/text_bg.png", (20, 25, 20, 25), True),
                 _L(_D + "dlc25_book_of_grudges/book_of_grudges_unit_pack_frame.png",
                    (15, 15, 15, 15), True)],
        "rank_tx": RANK_TX, "rank_ty": "0.00,0.00",
        # The Dwarf HUD bar, SCALED WHOLE (0.59 both ways) to 438x34 - its carved pillar caps
        # end clear of the first and last button.
        "gbar": [_L("ui/skins/wh_main_dwf_dwarfs/bar_small_central_left.png",
                    offset=(0, 3), dh=-6)],
        # The complete bookmark banners, drawn whole: trimmed at both ends. The _active files
        # before were cut square on the right.
        "tab": {"layers": [_L(_D + "dlc25_book_of_grudges/tab_button_confederation_selected.png",
                              colour=_DIM)],
                "hover": [_L(_D + "dlc25_book_of_grudges/tab_button_confederation_selected.png")],
                "selected": [_D + "dlc25_book_of_grudges/tab_button_unit_pack_selected.png"],
                "selected_hover":
                    [_D + "dlc25_book_of_grudges/tab_button_unit_pack_selected.png"]},
        # At native height, not fit_track: the trough is 8 rows, so fitting it was 1.26x.
        # Only row 15, one dark trough row, repeats. Trough y 8..21, x 17..732.
        "track": [_L(_D + "grudge_bar_hud_frame.png", (15, 18, 7, 17), True)],
        # The 1px highlight native; rows 1..3 (175/165/167) are near flat and stretch.
        "fill": [_L(_D + "dlc25_book_of_grudges/tab_button_bar_fill.png", (1, 0, 0, 0))],
    },
    "_hef": {
        # The Intrigue Court's alert plate at CA's top 70 / bottom 20, sides 20 so the edge
        # lines keep their size, inside Influence's 3px gold rim - the card was a 30% wash
        # before and vanished into the panel.
        "card": _L(_D + "dlc27_hef_intrigue_court/dlc27_intrigue_court_alert_holder.png",
                   (70, 20, 20, 20)),
        "card_extra": [_L(_D + "influence_balance_bar_frame.png", (3, 3, 2, 3), True)],
        "heat": (_GLOW, "#FFF0C050"),
        "rim": (_TUTGLOW, (16, 16, 16, 16), "#FFE9A0C0"),
        "holder": (_D + "dlc27_hef_asur_domination/faction_selection_frame_active.png",
                   0.5, 0.46),
        # Asur Domination's symmetric teal banner, full width, 0.79 tall.
        "cost": [_L(_D + "dlc27_hef_asur_domination/wh3_hef_gifted_settlement_bg.png",
                    offset=(3, 0), dw=-6)],
        "rank": [_L(_D + "dlc27_hef_intrigue_court/dlc27_intrigue_court_immunity.png",
                    (0, 70, 0, 70))],
        # 64: the scroll at the plate's left end runs to column 57 and the band starts at 58.
        "rank_tx": "64.00,0.00", "rank_ty": "0.00,0.00",
        # CA's 85 ends, NOT tiled: 467x71 into 438x40 only shrinks. The griffins (columns
        # 30..70) sit outside the buttons.
        "gbar": [_L("ui/skins/wh2_main_hef_high_elves/bar_small_buttons.png", (0, 85, 0, 85))],
        # Aislinn's dragonship header, navy with blue corner curls, tiled at its own size;
        # its last 12 columns are transparent, hence the 24 right margin and the second
        # slot stopping at 113. The open tab wears a gold outline.
        "tab": {"layers": [_L(_HEF_TAB, (12, 24, 12, 12), True, colour=_DIM,
                              offset=(6, 0), dw=-6),
                           _L(CLEAR, (8, 8, 8, 8), colour="#FFD37AFF", offset=(6, 0), dw=-18)],
                "hover": [_L(_HEF_TAB, (12, 24, 12, 12), True, offset=(6, 0), dw=-6),
                          _L(CLEAR, (8, 8, 8, 8), colour="#FFD37AFF", offset=(6, 0), dw=-18)],
                "selected": [_HEF_TAB, _D + "white_frame.png"],
                "selected_hover": [_HEF_TAB, _D + "white_frame.png"]},
        # The card's gold rim again round a dark trough; its opening 17..733, 7..21 holds the
        # fill. The sea patrol frame had two dividers in its middle and was drawn 3.5x.
        "track": [_L(_D + "1x1_blank_white.png", colour="#000000A0", offset=(17, 7),
                     dw=-34, dh=-14),
                  _L(_D + "influence_balance_bar_frame.png", (3, 3, 2, 3), True,
                     offset=(14, 4), dw=-28, dh=-9)],
        "fill": [_L(_D + "dlc27_hef_asur_domination/wh3_sea_patrol_progress_bar_fill.png",
                    tile=True)],
    },
    "_cth": {
        # The Tiger Court's pillar ground, tiled as CA tiles it, inset to where the frame's
        # rails start, inside Shang Yang's chain-railed category frame at CA's 20. The old
        # capacity holder was 67px tall drawn at 120.
        "card": _L(_D + "cp1_cth_tiger_court/pillar_info_holder.png", 0, True,
                   offset=(12, 7), dw=-21, dh=-12),
        "card_extra": [_L(_D + "cp1_cth_shang_yang/unit_category_holder.png", 20)],
        "heat": (_GLOW, "#60E0A050"),
        "rim": (_TUTGLOW, (16, 16, 16, 16), "#70E8B8C0"),
        "holder": (_D + "cp1_cth_tiger_court/button_decrees_active.png", 0.5, 0.5),
        "cost": [_L(_D + "cp1_cth_shang_yang/requirement_holder.png", (0, 25, 0, 25))],
        # 84-PIXEL ENDS, TEXT AT 90 AND LIFTED 2. The spear collar runs to column 81; at 60
        # it was stretched under the first word, and the line crossed it at 2.7:1. Squeezed
        # into the 46px strip, the plate's band is rows 14-29 with a 1px rail at each edge,
        # and a centred line's descenders sat on the lower rail - bottom padding 4 lifts it
        # clear. Not drawn taller than the strip: nothing may draw outside its component.
        "rank": [_L(_D + "cp1_cth_shang_yang/unit_category_header_holder_plate.png",
                    (0, 84, 0, 84))],
        "rank_tx": "90.00,0.00", "rank_ty": "0.00,4.00",
        # Shang Yang's army-cap pill: 20px round ends, flat middle.
        "gbar": [_L(_D + "cp1_cth_shang_yang/army_cap_holder.png", (0, 20, 0, 20))],
        # The Tiger Court's jade banner top SCALED WHOLE (0.68 both ways), so each tab is its
        # own banner; the open tab ringed by the tutorial glow in jade. Only position_flag_3
        # is dark enough for the yellow caption: flag_1 puts it at 2.4:1, flag_2 at 0.9:1.
        "tab": {"layers": [_L(_D + "cp1_cth_tiger_court/position_flag_3.png", colour=_DIM),
                           _L(CLEAR, 16, colour="#70E8B8C0")],
                "hover": [_L(_D + "cp1_cth_tiger_court/position_flag_3.png"),
                          _L(CLEAR, 16, colour="#70E8B8C0")],
                "selected": [_D + "cp1_cth_tiger_court/position_flag_3.png", _TUTGLOW],
                "selected_hover": [_D + "cp1_cth_tiger_court/position_flag_3.png", _TUTGLOW]},
        "track": fit_track("ui/skins/wh3_main_cth_cathay/compass_power_bar_frame.png",
                           (272, 26), (5, 5, 267, 20), True),
        "fill": [_L(_D + "compass_power_bar_fill.png")],
    },
    "_ksl": {
        # Kislev's own frost tile (CA's 1px slices, tiled) with the Ice Court's corner
        # ornaments - plain when unlit, CA's glowing pair when a service runs. The Orthodoxy
        # chain background before was drawn short of the card with hard edges.
        "card": _L("ui/skins/wh3_main_ksl_kislev/selectable_non_button_tile_bg.png", 1, True,
                   colour="#B4B4B4FF"),
        "card_extra": [_L(_D + "wh3_main_court_orthodoxy/court_btn_ornaments.png",
                          (32, 36, 32, 36))],
        "heat": (_GLOW, "#80D8FF50"),
        "rim": (_D + "wh3_main_court_orthodoxy/court_completed_btn_ornaments.png",
                (32, 36, 32, 36), None),
        "holder": (_D + "buildings_slot_circle_bg.png", 0.5, 0.5),
        # The star ends at column 43 and its rim at 46; the old 40 cut into the star.
        "cost": [_L(_D + "wh3_main_court_orthodoxy/court_favour_resource_holder.png",
                    (0, 16, 0, 46))],
        # The Kislev HUD bar with horse-head ends at almost its own width (1.017x).
        "rank": [_L("ui/skins/wh3_main_ksl_kislev/bar_small_central_left.png", (0, 75, 0, 75))],
        "rank_tx": "78.00,0.00", "rank_ty": "8.00,0.00",
        # Heads at columns 18..75; the middle only shrinks (307 to 278).
        "gbar": [_L("ui/skins/wh3_main_ksl_kislev/bar_small_buttons.png", (0, 80, 0, 80))],
        # The icy bar and its copper outline SCALED WHOLE: nine-sliced, the files' 23px
        # transparent left pad pushed each caption 10px off centre. The open tab is
        # Devotion's black plate.
        "tab": {"layers": [_L(_D + "wh3_main_court_orthodoxy/court_progress_bar.png",
                              colour="#50647AFF"),
                           _L(_D + "wh3_main_court_orthodoxy/kislev_support_frame.png")],
                "hover": [_L(_D + "wh3_main_court_orthodoxy/court_progress_bar.png",
                             colour="#6A8098FF"),
                          _L(_D + "wh3_main_court_orthodoxy/kislev_support_frame.png")],
                "selected": ["ui/skins/warhammer3/kislev_devotion_base.png",
                             "ui/skins/warhammer3/kislev_devotion_frame.png"],
                "selected_hover": ["ui/skins/warhammer3/kislev_devotion_base.png",
                                   "ui/skins/warhammer3/kislev_devotion_frame.png"]},
        "track": [_L("ui/skins/warhammer3/kislev_devotion_frame_small.png", (5, 10, 5, 10),
                     True, offset=(0, 3), dh=-6)],
        "fill": [_L(_D + "wh3_main_court_orthodoxy/court_progress_top_bar.png", (0, 0, 0, 20),
                    True)],
    },
    "_brt": {
        # The heraldic border is gone: it collided with the title and the price. A dimmed
        # burgundy ground inside Chivalry's thin copper outline, both tiled at CA's slices.
        "card": _L("ui/skins/wh_main_brt_bretonnia/legacy/panel_back_tile.png", 5, True,
                   colour=_DIM),
        "card_extra": [_L(_D + "chivalry_bar_frame.png", (5, 10, 5, 10), True)],
        "heat": (_GLOW, "#FFD37A50"),
        "rim": (_TUTGLOW, (16, 16, 16, 16), "#FFD37AC0"),
        # A plain copper ring, 96x96: no square box and no spikes. Bretonnia has no round
        # holder of this size; button_round_medium_frame was 56px drawn 1.9x.
        "holder": (_D + "dlc26_fragments_sorcery/ability_frame.png", 0.51, 0.53),
        "cost": [_L(_D + "bret_vows_titel.png", (0, 45, 0, 45))],
        # CA's 64 ends, middle tiled where it was stretched 2.7x.
        "rank": [_L(_D + "bret_vows_titel.png", (0, 64, 0, 64), True)],
        # 64, not RANK_TX's 50: the plate's scroll and post run to column 57.
        "rank_tx": "64.00,0.00", "rank_ty": "0.00,0.00",
        # The Vows plate again, its scroll ends outside the buttons. 8px top and bottom kept
        # native so the tile does not crop the lower rim.
        "gbar": [_L(_D + "bret_vows_titel.png", (8, 64, 8, 64), True)],
        # Burgundy with a copper outline, tiled; the open tab gets CA's gold selection line.
        # The Vows plates before had scroll ends that collided between neighbours.
        "tab": {"layers": [_L(_BRT_TILE, 5, True, colour=_DIM),
                           _L(_D + "chivalry_bar_frame.png", (5, 10, 5, 10), True)],
                "hover": [_L(_BRT_TILE, 5, True),
                          _L(_D + "chivalry_bar_frame.png", (5, 10, 5, 10), True)],
                "selected": [_BRT_TILE, _D + "building_frame_selected.png"],
                "selected_hover": [_BRT_TILE, _D + "building_frame_selected.png"]},
        # The trough counts the bevel rows 3..15: 13 rows, so the frame stays 19px native.
        "track": fit_track(_D + "chivalry_bar_frame.png", (60, 19), (4, 3, 56, 16), True),
        "fill": [_L(_D + "chaos_gifts/souls_bar_fill_undiveded.png")],
    },
    "_def": {
        # Malus's parchment plate, complete with its thin dark border, tiled at CA's 10 and
        # darkened to median 36 under the text, under CA's own tooltip overlay. No Dark Elf
        # plate exists at card proportions: the whispers tooltip before has 75 transparent
        # rows at its top and drew short of the card.
        "card": _L(_W2 + "malus_parchment_button_square_pressed.png", 10, True,
                   colour="#909090FF"),
        "card_extra": [_L(_W2 + "malus_whispers_tooltip_backgound_text.png",
                          (30, 30, 15, 30), True)],
        # THE SHARED GLOW, TINTED, like the six races with no glow of their own. The Dark Elf
        # rite flare that was here is white-hot in the middle and sat under the first half of
        # a running card's text at 0.7:1 (preview_guilds_panel.py, 2026-09-30).
        "heat": (_GLOW, "#D040FF50"),
        "rim": (_TUTGLOW, (16, 16, 16, 16), "#E050FFC0"),
        # Slaanesh's Eternal Dance ring, bronze with a purple centre, 128px. No Dark Elf round
        # holder over 60px exists.
        "holder": (_D + "dlc27_sla_the_eternal_dance/tempo_choice_t4_frame.png", 0.493, 0.483),
        # A small Murderous Prowess frame with the price in its own dark trough.
        "cost": [_L(_W2 + "murderous_prowess_back.png", offset=(24, 7), dw=-49, dh=-15),
                 _L(_W2 + "murderous_prowess_frame.png", (0, 25, 0, 24))],
        # The same frame at native height with its 50px caps, where a tooltip's BOTTOM border
        # was stretched 2.3x.
        "rank": [_L(_W2 + "murderous_prowess_back.png", offset=(24, 11), dw=-49, dh=-25),
                 _L(_W2 + "murderous_prowess_frame.png", (0, 50, 0, 50), True,
                    offset=(0, 2), dh=-5)],
        "rank_tx": "56.00,0.00", "rank_ty": "0.00,0.00",
        # Malus's orb bar. Hag Graef's bar_top_center is a 200px plate in the middle of a
        # 399px texture, so behind six buttons it drew nothing that showed.
        "gbar": [_L(_W2 + "malus_whispers_tooltip_border_bottom.png", (0, 70, 0, 70))],
        # Same parchment, sliced as CA slices it at this height (10, tiled).
        "tab": {"layers": [_L(_W2 + "malus_parchment_button_square_active.png", 10, True)],
                "hover": [_L(_W2 + "malus_parchment_button_square_hover.png", 10, True)],
                "selected": [_W2 + "malus_parchment_button_square_pressed.png"],
                "selected_hover": [_W2 + "malus_parchment_button_square_pressed.png"]},
        "track": [_L(_W2 + "murderous_prowess_frame.png", (0, 50, 0, 50), True,
                     offset=(0, 2), dh=-4)],
        "fill": [_L(_W2 + "murderous_prowess_fill.png")],
    },
}
FRAME_TAGS = sorted(t for t in FRAMES if t)


def frame(tag):
    """A race's frame; the Chaos Dwarf one for "" and for any flavour without its own."""
    return FRAMES.get(tag) or FRAMES[""]


def frame_file(base, tag):
    """The .twui.xml a race's panel or card is created from (GGUI.frame_path)."""
    return base + (tag if tag in FRAME_TAGS else "") + ".twui.xml"


def card_layers(tag=""):
    """Ground, heat, rim, then any border: the glows stay images 1 and 2 for every race."""
    f = frame(tag)
    heat = dict(CARD_LAYERS[CARD_HEAT_INDEX])
    rim = dict(CARD_LAYERS[CARD_RIM_INDEX], margin=f["rim"][1])
    for lay, colour in ((heat, f["heat"][1]), (rim, f["rim"][2])):
        if colour:
            lay["colour"] = colour
    return [f["card"], heat, rim] + f.get("card_extra", [])


# A RACE'S PANEL SHIPS ITS OWN GROUND. The Lua repaints image 1 per guild on every refresh
# (GGUI.paint_ground), so this is only what shows before that runs - but it is the Tower of
# Zharr in the Chaos Dwarf file, and a frame that exists so no other race wears Chaos Dwarf
# art should not start from it. The first guild's ground, in the race's flavour.
PANEL_BG_FIRST = "ui/campaign ui/derpy_gg_bg/brass.png"


def panel_layers(tag=""):
    if tag not in FRAME_TAGS:
        return PANEL_LAYERS
    return [dict(l, path=flavoured(PANEL_BG_FIRST, tag)) if l["path"] == PANEL_ART else l
            for l in PANEL_LAYERS]


def tab_layers(tag, state):
    """The file's layers for a tab state: "layers" (standard) or "hover"."""
    return frame(tag)["tab"][state]


# TWO BUGS LIVED IN THE OLD BUILDERS, and they are the same bug twice.
#
# 1. tx/ty ARE THE TEXT OFFSET INSIDE A COMPONENT, not the component's position.
#    EU._state feeds them to textxoffset/textyoffset. These builders passed the
#    LAYOUT coordinates into them, so gg_next got textxoffset="730.00" inside a
#    40px-wide component and gg_tab_help got 416 inside 132 - the labels were
#    pushed clean outside their own boxes. Component position is MoveTo at runtime
#    and nothing else; see GGUI.layout in zzz_derpy_guilds_ui.lua.
#
# 2. text= AND interactive= WERE TREATED AS EXCLUSIVE ("text=not interactive").
#    A button is both. Without a <component_text> block there is nothing for
#    SetStateText to render into, which is why the tab plates, the pager and every
#    Buy button drew as blank plates once they finally had art.
#
# So: every component that a label is ever written onto asks for text=True, and the
# text offset stays small and local to the component.
LABEL_TX, LABEL_TY = "6.00,0.00", "4.00,0.00"
# leading=0: a caption is ONE line, and per-line leading on one line is just an
# offset that drops the glyphs onto the plate's bottom rim. See EU._state.
BTN_TEXT = {"text": True, "size": 12, "align": "Center", "valign": "Center",
            "fontcat": "header_14", "leading": 0,
            "tx": "0.00,0.00", "ty": "0.00,0.00"}


def _panel(tag=""):
    f = frame(tag)
    root = EU.C("root", PANEL_W, PANEL_H)
    p = root.add(EU.C("derpy_gg_panel", PANEL_W, PANEL_H, priority=60,
                      layers=panel_layers(tag)))
    for name in sorted(PANEL_LAYOUT):
        _x, _y, w, h = PANEL_LAYOUT[name]
        interactive = name in TABS + LOG_FILTERS + ["gg_prev", "gg_next", "gg_close"]
        if name in GUILD_BTNS:
            # The glyph IS the button, and the count sits on its corner the way the
            # opener's badge does: same font, same gold, same bottom-right.
            kw = {"layers": GTAB_LAYERS, "interactive": True, "sound": SOUND_ROUND,
                  "text": True, "size": 12, "align": "Right", "valign": "Bottom",
                  "fontcat": "header_14", "leading": 0, "colour": GOLD,
                  "tx": "-2.00,0.00", "ty": "-1.00,0.00"}
        elif name == "gg_gsel":
            kw = {"layers": GSEL_LAYERS}
        elif name == "gg_gbar":
            kw = {"layers": f["gbar"]}
        elif name == "gg_rank_mark":
            kw = {"layers": holder_layers(w, h, RANK_GLYPH,
                                          RANK_ICON_LAYERS[-1]["path"], tag)}
        elif name in TABS:
            kw = dict(BTN_TEXT, layers=f["tab"]["layers"], hover=f["tab"]["hover"],
                      interactive=True, sound=SOUND_TAB)
        elif name == "gg_close":
            # A cross, not a caption: no text block, so there is nothing to write
            # onto it and nothing that can vanish off it.
            kw = {"layers": CLOSE_LAYERS, "hover": CLOSE_HOVER, "interactive": True,
                  "sound": SOUND_ROUND}
        elif name in ("gg_prev", "gg_next"):
            kw = dict(BTN_TEXT, layers=ROUND_LAYERS, hover=ROUND_HOVER,
                      interactive=True, sound=SOUND_ROUND)
        elif interactive:
            kw = dict(BTN_TEXT, layers=plate(h, "active"), hover=plate(h, "hover"),
                      interactive=True, sound=SOUND_TAB)
        elif name == "gg_rep_bar":
            # The bar is drawn, never written on.
            kw = {"layers": f["fill"]}
        elif name == "gg_bar_track":
            kw = {"layers": f["track"]}
        elif name == "gg_divider":
            kw = {"layers": DIVIDER_LAYERS}
        elif name == "gg_crest":
            kw = {"layers": CREST_LAYERS}
        elif name == "gg_title":
            # The largest bold header CA has, centred with no side offset, on CA's plate.
            kw = {"layers": TITLE_LAYERS,
                  "text": True, "size": 24, "align": "Center", "valign": "Center",
                  "fontcat": "header_24_bold", "tx": "0.00,0.00", "ty": "0.00,0.00"}
        elif name == "gg_rank_line":
            kw = {"layers": f["rank"],
                  "text": True, "size": 12, "align": "Left", "valign": "Center",
                  "fontcat": "body_12", "tx": f["rank_tx"], "ty": f["rank_ty"]}
        elif name.startswith("gg_help_"):
            kw = {"text": True, "size": 12, "align": "Left", "valign": "Center",
                  "fontcat": "body_12", "colour": "#C9BFA8FF",
                  "tx": LABEL_TX, "ty": "0.00,0.00"}
        else:
            kw = {"text": True, "size": 12, "align": "Left", "valign": "Center",
                  "fontcat": "body_12", "tx": LABEL_TX, "ty": LABEL_TY}
        p.add(EU.C(name, w, h, **kw))
    return root


def _card(tag=""):
    f = frame(tag)
    root = EU.C("root", CARD_W, CARD_H)
    # INTERACTIVE, for two reasons: its tooltip carries everything the card has no room
    # for, and a tooltip on a component that is not interactive is never shown; and on the
    # bounty board a click on the card pans the map to the target. NO SOUND, deliberately:
    # on the Guilds and Court tabs the card body does nothing, and a click sound there
    # would say something happened. On the board the camera moving is the answer.
    c = root.add(EU.C("derpy_gg_card", CARD_W, CARD_H, layers=card_layers(tag),
                      interactive=True))
    for name in sorted(CARD_LAYOUT):
        _x, _y, w, h = CARD_LAYOUT[name]
        if name == "card_buy":
            kw = dict(BTN_TEXT, layers=plate(h, "active"), hover=plate(h, "hover"),
                      interactive=True, sound=SOUND_BUY)
        elif name == "card_icon":
            kw = {"layers": holder_layers(w, h, CARD_GLYPH,
                                          CARD_ICON_LAYERS[CARD_ICON]["path"], tag)}
        elif name.startswith("card_desc"):
            # Dimmer than the name, and body text rather than a heading.
            kw = {"text": True, "size": 12, "align": "Left", "valign": "Center",
                  "fontcat": "body_12", "colour": "#C9BFA8FF",
                  "tx": LABEL_TX, "ty": "2.00,0.00"}
        elif name == "card_name":
            kw = {"text": True, "size": 14, "align": "Left", "valign": "Center",
                  "fontcat": "header_14", "tx": LABEL_TX, "ty": LABEL_TY}
        elif name == "card_cost":
            # The number reads better against the Buy button below it when centred.
            kw = {"layers": f["cost"],
                  "text": True, "size": 14, "align": "Center", "valign": "Center",
                  "tx": "0.00,0.00", "ty": "0.00,0.00"}
        else:
            kw = {"text": True, "size": 14, "align": "Left", "valign": "Center",
                  "tx": LABEL_TX, "ty": LABEL_TY}
        c.add(EU.C(name, w, h, **kw))
    return root


def _row():
    root = EU.C("root", ROW_W, ROW_H)
    # INTERACTIVE, because a standings row is now the control that picks which guild the
    # faction list underneath is showing. A row that is not interactive does not raise
    # ComponentLClickUp at all - the click lands on the panel behind it and nothing
    # happens, with nothing on screen or in the log to say why.
    r = root.add(EU.C("derpy_gg_row", ROW_W, ROW_H, layers=ROW_LAYERS,
                      interactive=True, sound=SOUND_TAB))
    for name in sorted(ROW_LAYOUT):
        _x, _y, w, h = ROW_LAYOUT[name]
        if name == "row_icon":
            # A BUTTON INSIDE THE ROW: the row picks the list below, its glyph opens the
            # guild's services. On top of the row, so it takes its own clicks.
            r.add(EU.C(name, w, h, layers=ROW_ICON_LAYERS, interactive=True,
                       sound=SOUND_TAB))
            continue
        r.add(EU.C(name, w, h, text=True, size=14, align="Left", valign="Center",
                   tx=LABEL_TX, ty=LABEL_TY))
    return root


def _list():
    """The scrolling frame: a clip window, a stacking box, a slider and its handle.

    THE CALLBACKS ARE THE WHOLE THING. list_box carries "List", vslider "VSlider", handle
    "VSliderHandle" - and THE CONTAINER carries "Listview", which is the one that binds the
    other three to each other. Without them this is four nested rectangles that draw
    correctly, accept a drag, and scroll nothing. There is no error for their absence.

    THE CONTAINER CALLBACK IS WHAT THE FIRST BUILD MISSED, and it shipped: the list drew
    its rows, stacked them, clipped them at the window edge and would not scroll a line.
    The container was named derpy_gg_list and carried no callback at all, so the three
    working parts had nothing joining them.

    Measured afterwards across all 824 of CA's panels: of the 317 components that parent a
    list_clip, 144 are named `listview` outright, and CA's own
    ui/templates/listview.twui.xml - referenced by template_id="Listview" from 145 panels -
    is exactly this subtree with callback_id="Listview" on its root. The one CA panel this
    structure was first read from, ui/common ui/tab_completer.twui.xml, was a POOR DONOR
    for that reason: its container carries a bespoke TabCompleteSuggestionList callback
    instead, so copying its four inner parts copied everything except the binding.

    Named `listview` as well as carrying the callback, because the engine binds the four
    inner parts by name and there is no reason to find out the hard way whether it binds
    this one by name too. It is inside our own panel, so it collides with nothing: CA's
    own scripts reach their lists through a parent chain.
    """
    root = EU.C("root", LIST_W, LIST_H)
    lst = root.add(EU.C("listview", LIST_W, LIST_H, interactive=True,
                        callbacks=["Listview"]))

    _x, _y, w, h = LIST_LAYOUT["list_clip"]
    clip = lst.add(EU.C("list_clip", w, h, clipchildren=True, relativeresize=True,
                        interactive=True))
    # sizetocontent is what lets the box grow taller than the window above it. A box
    # pinned to the window's height has nothing below the fold, so nothing to scroll to,
    # and the slider correctly refuses to move.
    clip.add(EU.C("list_box", FROW_W, 1, interactive=True, callbacks=["List"],
                  docking="Top Left",
                  layoutengine={"type": "List", "sizetocontent": True,
                                "margins": "0.00,0.00", "columns": [FROW_W]}))

    _x, _y, w, h = LIST_LAYOUT["vslider"]
    vs = lst.add(EU.C("vslider", w, h, interactive=True, callbacks=["VSlider"],
                      allowhresize=False,
                      # The travel. CA sets both on every slider it ships; a slider with
                      # no maxValue has nowhere to go.
                      props={"Value": 0, "minValue": 0, "maxValue": LIST_H - HANDLE_H},
                      layers=[{"path": SLIDER_TRACK, "offset": (0, 0), "dw": 0, "dh": 0,
                               "margin": 0, "tile": True, "dock": None}]))
    vs.add(EU.C("handle", SLIDER_W, HANDLE_H, interactive=True,
                callbacks=["VSliderHandle"], allowhresize=False,
                # DRAGGABLE. Without moveable the handle is a picture of a handle.
                moveable="Movable XP", sound=SOUND_ROUND,
                props={"max_height": LIST_H - HANDLE_H, "min_size": 10},
                layers=[{"path": SLIDER_HANDLE_UNDER, "offset": (0, 0), "dw": 0,
                         "dh": 0, "margin": 0, "dock": None},
                        {"path": SLIDER_HANDLE, "offset": (0, 0), "dw": 0, "dh": 0,
                         "margin": 0, "dock": None}]))
    return root


def _frow():
    """One faction in the list. One component, no children - see FLAG_FALLBACK above.

    NO PLATE. These stack inside the list box on the panel's own ground, the way the
    Help tab's lines do; a band behind every row at 24px reads as stripes rather than
    as rows, and the list already has the clip window's edge to sit in.
    """
    root = EU.C("root", FROW_W, FROW_H)
    # INTERACTIVE for its tooltip, and because a click pans the map to the faction's
    # capital. No sound, for the card's reason: the camera moving is the answer.
    root.add(EU.C("derpy_gg_frow", FROW_W, FROW_H, text=True, size=12, align="Left",
                  valign="Center", fontcat="body_12", tx=LABEL_TX, ty=LABEL_TY,
                  interactive=True))
    return root


# The opener button on the campaign HUD. Its own file: it is created beside the
# rites button, not inside the panel, and reusing the 750x40 standings row for it
# would put a full-width row on the HUD.
OPENER_W, OPENER_H = 44, 44


def _opener():
    root = EU.C("root", OPENER_W, OPENER_H)
    # TEXT ON THE BUTTON ITSELF, not a separate badge component. A child would need its own
    # .twui.xml file, its own GUID range and its own placement call; the count is one or two
    # characters and the component is already here. Bottom-right, so it sits on the plate's
    # rim rather than over the crest, which is docked Center at 30x30 inside 44x44.
    #
    # EU._state emits component_text on EVERY state, so the number does not vanish on
    # hover. Writing it is SetText (all states), never SetStateText (current state only) -
    # that distinction is what made the Buy caption disappear on mouseover once already.
    root.add(EU.C("gg_opener", OPENER_W, OPENER_H, interactive=True,
                  sound=OPENER_SOUND, layers=OPENER_LAYERS, hover=OPENER_HOVER,
                  text=True, size=12, align="Right", valign="Bottom",
                  fontcat="header_14", leading=0,
                  # CA's gold. A count is a call to action, not body copy.
                  colour="#FFD37AFF",
                  tx="-4.00,0.00", ty="-2.00,0.00"))
    return root


FILES = [
    ("derpy_gg_panel.twui.xml", _panel, "The Great Guilds - panel frame, tabs, pager"),
    ("derpy_gg_card.twui.xml", _card, "The Great Guilds - one service card"),
    ("derpy_gg_row.twui.xml", _row, "The Great Guilds - one standings row"),
    ("derpy_gg_list.twui.xml", _list,
     "The Great Guilds - the standings faction list, clip plus slider"),
    ("derpy_gg_frow.twui.xml", _frow,
     "The Great Guilds - one faction inside the standings list"),
    ("derpy_gg_opener.twui.xml", _opener, "The Great Guilds - HUD opener button"),
]


def frame_files():
    """FILES plus each race's own panel and card (see FRAMES)."""
    out = list(FILES)
    for tag in FRAME_TAGS:
        out.append((frame_file("derpy_gg_panel", tag), lambda t=tag: _panel(t),
                    "The Great Guilds - panel frame, tabs, pager (%s frame)" % tag))
        out.append((frame_file("derpy_gg_card", tag), lambda t=tag: _card(t),
                    "The Great Guilds - one service card (%s frame)" % tag))
    return out


def build_xml():
    """path -> xml text. GUIDs are minted per file from one counter, as the Exchange does."""
    out = {}
    for fname, builder, comment in frame_files():
        root = EU.assign(builder(), GUID_PREFIX)
        if fname not in UNSCALED_FILES:
            for c in root.walk():
                if c.kw.get("text"):
                    c.kw["font_anim"] = SCALE_ANIM
        out[fname] = EU.layout(root, comment)
    return out


def xml_component_names(text):
    """Every component name declared in the <components> block of one file."""
    body = text.split("<components>", 1)[1]
    return sorted(set(re.findall(r"(?m)^\t\t<(\w+)", body)))


def _lua_xy_tables():
    """The three layout tables as the campaign Lua declares them.

    Returns {table_name: {component: (x, y)}}, or {} when the file is absent.
    """
    path = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign",
                        "mod", "zzz_derpy_guilds_ui.lua")
    if not os.path.isfile(path):
        return {}
    lua = io.open(path, encoding="utf-8").read()
    out = {}
    for tbl in ("PANEL_XY", "CARD_CHILD_XY", "ROW_CHILD_XY"):
        m = re.search(r"GGUI\.%s\s*=\s*\{(.*?)\n\}" % tbl, lua, re.S)
        if not m:
            continue
        found = {}
        for name, x, y in re.findall(r"(\w+)\s*=\s*\{\s*(-?\d+)\s*,\s*(-?\d+)\s*\}",
                                     m.group(1)):
            found[name] = (int(x), int(y))
        out[tbl] = found
    return out


def flavoured(path, tag):
    """The path the panel Lua builds for a flavour: the tag before ".png" (GGUI.art)."""
    return path[:-len(".png")] + tag + ".png" if tag else path


def _assets():
    """Every imagepath this pack may reference: CA's ui packs PLUS what we ship.

    EU._game_assets() reads the game's packs only, so an icon this mod generates
    itself - tools/make_guild_icons.py writes seven - reads as missing and the
    existence guard would refuse art that is perfectly present.
    """
    paths = set(EU._game_assets())
    base = os.path.join(ROOT, "Modding Files", "pack")
    for dirpath, _dirs, names in os.walk(base):
        for n in names:
            if n.lower().endswith(".png"):
                rel = os.path.relpath(os.path.join(dirpath, n), base)
                paths.add(rel.replace("\\", "/"))
    return paths


def check_help_fits(lua):
    """Every help page must fit in HELP_SLOTS, because the overflow is dropped silently.

    GGUI.help_lines stops pushing at HELP_SLOTS - it cannot do anything else, there are
    only that many components - so a page that runs long simply ends early and the tab
    looks perfectly well-formed with its last block missing. That is how the mission
    paragraph and the rank ladder vanished from the old single-page version.

    This SIMULATES the renderer rather than grepping it: a heading is one line plus a
    blank above it, a bullet wraps with five characters of indent, a blank is a line.
    The width is an ESTIMATE - only the game measures text - and it errs narrow (100
    characters to a 750px line at body_12 against a real figure nearer 113), so it would
    rather refuse a page that just fits than pass one that does not.

    `lua` is read for one thing only: the renderer must still be the one this models.
    """
    out = []
    try:
        import gen_great_guilds as GG
        # EVERY FLAVOUR. The Empire's names are longer and wrap where ours do not, so a
        # page that fits in Chaos Dwarf can drop its last line for an Empire player.
        flavours = [(tag, GG.help_pages(tag)) for tag in GG.FLAVOURS]
    except Exception as e:
        return ["help fit check could not read the pages: %r" % (e,)]

    # If the renderer stops being line-typed, this whole model is wrong and silently
    # measuring something that is not what draws.
    for needed in ('string.sub(seg, 1, 1)', 'GGUI.HELP_BULLET'):
        if needed not in lua:
            out.append("GGUI.help_lines no longer renders typed lines (%s is gone), so "
                       "the fit estimate below models a renderer that is not there"
                       % needed)
            return out

    import textwrap
    WIDTH = 100
    INDENT = len("  -  ")
    for tag, pages in flavours:
        for i, lines in enumerate(pages):
            n = 0
            for j, line in enumerate(lines):
                if line == "":
                    n += 1
                elif line.startswith("#"):
                    if j:
                        n += 1      # the blank above every heading but the first
                    n += 1
                elif line.startswith("-"):
                    n += max(1, len(textwrap.wrap(line[1:], WIDTH - INDENT)))
                else:
                    n += max(1, len(textwrap.wrap(line, WIDTH)))
            if n > HELP_SLOTS:
                out.append("help page %d (%s) needs about %d lines and there are %d slots "
                           "- the text past the last one is dropped in silence"
                           % (i + 1, tag or "chd", n, HELP_SLOTS))
    return out


def check_parent_walks(lua):
    """`:Parent()` hands back a component ADDRESS, so it must be re-wrapped.

    `UIComponent(c):Parent():Id()` throws, and every call site here is inside a pcall,
    so it fails silently and the widget simply does nothing. That shipped once: every
    Buy and Take button in the panel was dead while the clicks themselves registered.
    """
    out = []
    for i, line in enumerate(lua.split("\n"), 1):
        code = line.split("--", 1)[0]
        if re.search(r":Parent\(\)\s*:", code):
            out.append("line %d calls a method straight off :Parent(), which returns an "
                       "address - wrap it: UIComponent(x:Parent()):Id()" % i)
    return out


def check_loc_keys(lua):
    """Every literal key the panel asks GGUI.loc for must be a row this mod ships.

    GGUI.loc FALLS BACK TO THE KEY. A misspelled one does not error and does not draw a
    blank - it prints its own key onto the panel, in the middle of a sentence, forever.
    Nothing checked this: the Standings tab's activity line alone added eight new keys
    and a typo in any of them would have shipped as "derpy_gg_rivals_bought" written
    across the header.

    Only LITERAL arguments are checked. A key built by concatenation - GGUI.loc("help_p"
    .. GGUI.HELP_PAGE) - cannot be resolved here, and check_help_pages() in
    gen_great_guilds.py covers that family instead. The argument text is taken by
    counting parentheses rather than to the end of the line, so `GGUI.loc("a") .. "b"`
    does not offer "b" as a key.
    """
    out = []
    try:
        shipped = set(r["key"] for r in G.build()["loc"])
    except Exception as e:
        return ["could not read the loc rows to check the panel's keys: %r" % (e,)]

    for m in re.finditer(r"GGUI\.loc\(", lua):
        i, depth = m.end(), 1
        while i < len(lua) and depth:
            if lua[i] == "(":
                depth += 1
            elif lua[i] == ")":
                depth -= 1
            i += 1
        arg = lua[m.end():i - 1]
        # A literal followed by ".." is a PREFIX, not a key.
        for lit in re.finditer(r'"([a-z0-9_]+)"(\s*\.\.)?', arg):
            if lit.group(2):
                continue
            key = "derpy_gg_" + lit.group(1)
            if key not in shipped:
                out.append("the panel draws GGUI.loc(%r) and no loc row ships %s, so "
                           "that key prints itself onto the panel"
                           % (lit.group(1), key))
    return sorted(set(out))


def check_scroll_parts(files):
    """The faction list scrolls only if it is spelled exactly the way the engine reads.

    THERE IS NO SCROLL WIDGET IN THIS ENGINE. A list that scrolls is four components with
    RESERVED NAMES carrying RESERVED CALLBACKS, and the engine binds them to each other by
    those names alone. Every way of getting it wrong is silent - the parts draw, the handle
    accepts a drag, and nothing moves:

      * list_clip without clipchildren     the rows overflow the panel instead of scrolling
      * list_box without callback "List"   an ordinary container; nothing stacks or scrolls
      * list_box without sizetocontent     the box cannot grow past the window, so there is
                                           nothing below the fold and the slider is right
                                           to refuse to move
      * vslider without callback "VSlider" a picture of a scrollbar
      * handle without "VSliderHandle"     drags and scrolls nothing
      * handle without moveable            does not even drag
      * any of the four renamed            the engine never finds it

    Checked against CA's own ui/common ui/tab_completer.twui.xml, which is where this
    structure was read from - so if a patch changes what CA spells, this says so rather
    than shipping a dead list against a stale copy.
    """
    out = []
    text = files.get("derpy_gg_list.twui.xml", "")
    if not text:
        return ["derpy_gg_list.twui.xml is not built, so the Standings tab has no list"]

    want = {
        # THE CONTAINER FIRST. This is the one that was missing on the first build, and
        # its absence is the quietest of the lot: the other three parts all work, so the
        # list draws, stacks and clips perfectly and simply never moves.
        "listview": {"attrs": [], "callbacks": ["Listview"]},
        "list_clip": {"attrs": ["clipchildren=\"true\""], "callbacks": []},
        "list_box": {"attrs": [], "callbacks": ["List"]},
        "vslider": {"attrs": [], "callbacks": ["VSlider"]},
        "handle": {"attrs": ["moveable="], "callbacks": ["VSliderHandle"]},
    }
    for name in sorted(want):
        i = text.find('id="%s"' % name)
        if i < 0:
            out.append("derpy_gg_list.twui.xml declares no %s - the engine binds a "
                       "scrolling list by these four names and finds nothing" % name)
            continue
        nxt = text.find("\n\t\t<", i)
        body = text[i:nxt if nxt > 0 else len(text)]
        for a in want[name]["attrs"]:
            if a not in body:
                out.append("%s carries no %s - silent: it draws, and does not scroll"
                           % (name, a.rstrip("=\"true")))
        for cb in want[name]["callbacks"]:
            if 'callback_id="%s"' % cb not in body:
                out.append("%s carries no callback_id=%s, which IS the behaviour - "
                           "without it this is a rectangle that looks like a list"
                           % (name, cb))
    i = text.find('id="list_box"')
    if i >= 0:
        nxt = text.find("\n\t\t<", i)
        body = text[i:nxt if nxt > 0 else len(text)]
        if 'sizetocontent="true"' not in body:
            out.append("list_box has no sizetocontent, so it cannot grow past the clip "
                       "window - there is nothing below the fold and nothing to scroll to")
        if "<LayoutEngine" not in body:
            out.append("list_box has no LayoutEngine, so rows created into it all sit at "
                       "its origin, stacked on each other")

    # AND CA MUST STILL SPELL IT THIS WAY. This structure was read out of one CA file; if a
    # patch renames a part, this mod's list dies silently and nothing else would say so.
    try:
        import read_pack_index
        ca = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III\data\ui3.pack"
        got = b""
        for _p, comp, data in read_pack_index.read(ca, "ui/common ui/tab_completer.twui.xml"):
            if not comp:
                got = data
        if got:
            t = got.decode("utf-8", "replace")
            for name in ("list_clip", "list_box", "vslider", "handle"):
                if 'id="%s"' % name not in t:
                    out.append("CA's tab_completer no longer declares %s - the reserved "
                               "names this list relies on have changed" % name)
            for cb in ("List", "VSlider", "VSliderHandle"):
                if 'callback_id="%s"' % cb not in t:
                    out.append("CA's tab_completer no longer uses callback_id=%s" % cb)
        # AND THE CONTAINER CALLBACK, which tab_completer does NOT have - it uses a
        # bespoke one - so it is read from the template CA's own panels reference instead.
        # Checking it against tab_completer is what let the first build ship inert.
        tpl = b""
        for _p, comp, data in read_pack_index.read(ca, "ui/templates/listview.twui.xml"):
            if not comp:
                tpl = data
        if not tpl:
            out.append("CA's ui/templates/listview.twui.xml is gone - the container "
                       "callback this list depends on cannot be confirmed")
        elif 'callback_id="Listview"' not in tpl.decode("utf-8", "replace"):
            out.append("CA's listview template no longer carries callback_id=Listview - "
                       "the container binding has changed and this list will not scroll")
    except Exception as exc:                                       # noqa: BLE001
        out.append("could not read CA's tab_completer to confirm the scroll contract: "
                   "%r" % (exc,))
    return out


def check_panel_bg(lua_src):
    """The per-guild panel ground: the index, the six files, and their brightness.

    Three ways this goes wrong and none of them says anything in game:

    1. THE INDEX. SetImagePath replaces one of the panel's four images by position -
       tile, art, scrim, frame. The Lua carries the art's index as a literal, so
       inserting a layer above the art in PANEL_LAYERS silently repoints the swap at
       the tile UNDERNEATH the art (nothing visible changes, ever) or at the scrim
       (every tab's text loses the contrast it was tuned against).
    2. A MISSING FILE. These paths are assembled in Lua, so the imagepath sweep over
       the .twui.xml cannot see them; SetImagePath to a path the game does not have
       draws nothing and logs nothing.
    3. BRIGHTNESS. The whole point of the bake is that each ground measures what CA's
       tier_01 ground measures under this panel's scrim. Re-measured here from the
       files that SHIP, because the bake and the pack are separate steps.
    """
    out = []
    art = [i for i, l in enumerate(PANEL_LAYERS) if l["path"] == PANEL_ART]
    m = re.search(r"GGUI\.BG_INDEX\s*=\s*(\d+)", lua_src)
    if not m:
        out.append("zzz_derpy_guilds_ui.lua declares no GGUI.BG_INDEX, so nothing says "
                   "which of the panel's four images the ground swap replaces")
    elif len(art) != 1:
        out.append("PANEL_LAYERS holds %d layers drawing PANEL_ART; GGUI.BG_INDEX "
                   "cannot name one of them" % len(art))
    elif int(m.group(1)) != art[0]:
        out.append("GGUI.BG_INDEX is %s but the panel art is image %d of %d (%s) - the "
                   "ground swap would replace the wrong layer"
                   % (m.group(1), art[0], len(PANEL_LAYERS),
                      ", ".join(l["path"].rsplit("/", 1)[-1] for l in PANEL_LAYERS)))

    block = re.search(r"GGUI\.PANEL_BG\s*=\s*\{(.*?)\n\}", lua_src, re.S)
    if not block:
        out.append("zzz_derpy_guilds_ui.lua declares no GGUI.PANEL_BG, so the panel "
                   "ground never changes")
        return out
    got = dict(re.findall(r"(\w+)\s*=\s*\"([^\"]+)\"", block.group(1)))
    for guild in G.GUILDS:
        path = got.get(guild)
        if not path:
            out.append("GGUI.PANEL_BG has no entry for %s, so that guild keeps "
                       "whichever ground the last one painted" % guild)
            continue
        disk = os.path.join(ROOT, "Modding Files", "pack", *path.split("/"))
        if not os.path.isfile(disk):
            out.append("GGUI.PANEL_BG[%s] points at %s, which is not staged - "
                       "SetImagePath draws nothing and logs nothing" % (guild, path))
    for tag in [t for t in G.FLAVOURS if t]:
        for guild in G.GUILDS:
            path = got.get(guild)
            if not path:
                continue
            fpath = flavoured(path, tag)
            disk = os.path.join(ROOT, "Modding Files", "pack", *fpath.split("/"))
            if not os.path.isfile(disk):
                out.append("GGUI.PANEL_BG[%s] has no %s ground - %s is not staged, so "
                           "that race's panel keeps whichever ground was painted last"
                           % (guild, tag, fpath))
    for extra in sorted(set(got) - set(G.GUILDS)):
        out.append("GGUI.PANEL_BG has an entry for %r, which is not one of the six "
                   "guilds - nothing will ever ask for it" % extra)

    try:
        import make_guild_backgrounds as BG
        out += ["panel ground: " + p for p in BG.check()]
    except Exception as e:                                    # noqa: BLE001
        out.append("could not measure the panel grounds: %r" % (e,))
    return out


# THE PANEL GROWS ITS TEXT THROUGH ONE ANIMATION PER TEXT CELL. The Lua rewrites that
# animation's font_scale frame and plays it, the way CA's lib_topic_leader.lua shrinks its
# own text; nothing else in the uicomponent API changes the size a label draws at. A cell
# without it stays at 1x inside a box GGUI.S times its size, which errors nowhere: the
# words are simply small. 512 is the font-scale bit of interpolationpropertymask, read off
# CA's own frames (512 alone, and 576 = 512 + colour).
SCALE_ANIM = "derpy_gg_scale"
# The opener sits in CA's HUD row beside the resource strip and stays HUD-sized.
UNSCALED_FILES = {"derpy_gg_opener.twui.xml"}


def check_scale_anim(files, lua_src):
    out = []
    m = re.search(r'GGUI\.SCALE_ANIM\s*=\s*"([^"]+)"', lua_src)
    if not m:
        out.append("zzz_derpy_guilds_ui.lua declares no GGUI.SCALE_ANIM, so no text "
                   "grows with the panel")
    elif m.group(1) != SCALE_ANIM:
        out.append("GGUI.SCALE_ANIM is %r but the .twui.xml files carry %r"
                   % (m.group(1), SCALE_ANIM))
    for fname, text in sorted(files.items()):
        if fname in UNSCALED_FILES:
            continue
        body = text.split("<components>", 1)[1]
        for name, block in re.findall(r"(?ms)^\t\t<(\w+)\n(.*?)^\t\t</\1>", body):
            if "<component_text" not in block:
                continue
            if ('id="%s"' % SCALE_ANIM not in block
                    or 'interpolationpropertymask="512"' not in block
                    or "targetmetrics_m_font_scale=" not in block):
                out.append("%s: %s carries text but no %s font-scale animation, so it "
                           "stays small on a large screen" % (fname, name, SCALE_ANIM))
    return out


def check_opener_crest(lua):
    """The crest repaints go by IMAGE INDEX, so their numbers must be where the crest sits.

    derpy_gg_opener lists OPENER_LAYERS and then OPENER_HOVER; gg_crest has CREST_LAYERS.
    A wrong number repaints the button's plate with a crest and leaves the old crest on
    top, which is wrong on screen and says nothing.
    """
    out = []
    for fn_name, layers, crest in (
            ("paint_opener", OPENER_LAYERS + OPENER_HOVER, OPENER_ICON),
            ("paint_crest", CREST_LAYERS, CREST_LAYERS[0]["path"])):
        want = [i for i, l in enumerate(layers) if l["path"] == crest]
        fn = re.search(r"function GGUI\.%s\(b?\)(.*?)\nend" % fn_name, lua, re.S)
        if not fn:
            out.append("zzz_derpy_guilds_ui.lua has no GGUI.%s, so a flavoured player "
                       "keeps the Chaos Dwarf crest there" % fn_name)
            continue
        got = sorted(int(x) for x in re.findall(r"SetImagePath\(path,\s*(\d+)\)",
                                                 fn.group(1)))
        if got != want:
            out.append("GGUI.%s repaints image(s) %r and the crest is image(s) %r"
                       % (fn_name, got, want))
    return out


_TEX_SIZES = {}


def tex_size(path):
    """(w, h) of a texture: ours from where it is staged, CA's out of the ui packs."""
    if path in _TEX_SIZES:
        return _TEX_SIZES[path]
    from PIL import Image
    local = os.path.join(ROOT, "Modding Files", "pack", path.replace("/", os.sep))
    size = None
    if os.path.isfile(local):
        size = Image.open(local).size
    else:
        import read_pack_index as RP
        from read_vanilla_loc import _decompress
        game = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III\data"
        for pk in ("ui.pack", "ui2.pack", "ui3.pack", "ui_3.pack"):
            fp = os.path.join(game, pk)
            if not os.path.isfile(fp):
                continue
            for _p, comp, blob in RP.read(fp, path):
                if _p == path:
                    size = Image.open(io.BytesIO(_decompress(blob) if comp else blob)).size
                    break
            if size:
                break
    _TEX_SIZES[path] = size
    return size


def _margins(lay):
    m = lay.get("margin", 0)
    return tuple(m) if isinstance(m, (tuple, list)) else (m,) * 4


def check_margins_fit_textures():
    """A 9-slice margin must fit inside EVERY texture its layer can show.

    Top+bottom under the texture's height and left+right under its width. Past that the
    engine samples outside the image, into its neighbours in the texture atlas - streaks
    and fragments of other panels' art across the component, which is what the card's
    rim layer drew over every card on 2026-09-26 with a 40px margin on CA's 24px
    icon_blank. The preview cannot show it: it rasterises the PNG alone.

    The layers the Lua repaints are checked against what it paints in as well as what the
    file ships - the tab plate's four states, the card's two glows.
    """
    out = []
    pairs = []
    for fname, builder, _c in frame_files():
        for c in builder().walk():
            for lay in EU._spec(c.kw, "layers") + EU._spec(c.kw, "hover"):
                pairs.append((fname, c.name, lay, lay["path"]))
    # WHAT THE LUA SWAPS IN is drawn through the SLOT's margins: the open tab's plates
    # through the standard and hover layers, the glows through the card's images 1 and 2.
    for tag in [""] + FRAME_TAGS:
        f, pf, cf = frame(tag), frame_file("derpy_gg_panel", tag), frame_file("derpy_gg_card", tag)
        for slot, state in (("layers", "selected"), ("hover", "selected_hover")):
            for lay, path in zip(f["tab"][slot], f["tab"][state]):
                pairs.append((pf, "tabs (%s)" % state, lay, path))
        cl = card_layers(tag)
        pairs.append((cf, "card heat", cl[CARD_HEAT_INDEX], f["heat"][0]))
        pairs.append((cf, "card rim", cl[CARD_RIM_INDEX], f["rim"][0]))
    for fname, name, lay, path in pairs:
        t, r, b, lft = _margins(lay)
        if not (t or r or b or lft):
            continue
        size = tex_size(path)
        if size is None:
            out.append("%s: %s's texture %s could not be read to check its margins"
                       % (fname, name, path))
            continue
        w, h = size
        if lft + r >= w or t + b >= h:
            out.append("%s: %s has margins %r on %s, which is only %dx%d - the slices "
                       "reach outside the texture and draw its atlas neighbours"
                       % (fname, name, (t, r, b, lft), path.rsplit("/", 1)[-1], w, h))
    # And CLEAR must be what it says: fully transparent and as large as it claims.
    try:
        from PIL import Image
        im = Image.open(os.path.join(ROOT, "Modding Files", "pack",
                                     CLEAR.replace("/", os.sep))).convert("RGBA")
        if im.size != (CLEAR_PX, CLEAR_PX) or im.getchannel("A").getextrema() != (0, 0):
            out.append("%s is %r with alpha %r - it must be %dpx and fully transparent"
                       % (CLEAR, im.size, im.getchannel("A").getextrema(), CLEAR_PX))
    except OSError:
        out.append("%s is not staged - run --write" % CLEAR)
    return out


def write_clear():
    """Our fully transparent 'off' texture. Written, not copied: it is nobody's art."""
    from PIL import Image
    path = os.path.join(ROOT, "Modding Files", "pack", CLEAR.replace("/", os.sep))
    Image.new("RGBA", (CLEAR_PX, CLEAR_PX), (0, 0, 0, 0)).save(path)
    return path


def check():
    """Refuses to write on anything that is a silent non-draw in game."""
    out = []
    files = build_xml()

    # EVERY imagepath MUST RESOLVE. A path the game does not have draws a blank
    # square and logs nothing - the same silence that let all four of these files
    # ship with no art at all. EU._game_assets() reads the real ui packs.
    try:
        assets = _assets()
        for fname, text in sorted(files.items()):
            for path in sorted(set(re.findall(r'imagepath="([^"]+)"', text))):
                if path not in assets:
                    out.append("%s: imagepath does not exist in any ui pack, so it "
                               "draws a blank square: %s" % (fname, path))
    except Exception as e:
        out.append("could not verify imagepaths against the game's ui packs: %r" % (e,))

    # A TALLER BOX DOES NOT WRAP - measured live for the Exchange's footer, which
    # still reported one 1333px line at 880x60. So a body of text is a COLUMN of
    # single-line components, and the Lua that fills them must reach every one.
    lua_path = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign",
                            "mod", "zzz_derpy_guilds_ui.lua")
    if os.path.isfile(lua_path):
        lua_src = io.open(lua_path, encoding="utf-8").read()
        out += check_parent_walks(lua_src)
        if "TextDimensionsForText" not in lua_src:
            out.append("zzz_derpy_guilds_ui.lua never measures text, so a long "
                       "string clips mid-word with no error")
        m = re.search(r"GGUI\.HELP_SLOTS\s*=\s*(\d+)", lua_src)
        if not m:
            out.append("zzz_derpy_guilds_ui.lua declares no GGUI.HELP_SLOTS, so the "
                       "Help tab has nothing to write into")
        elif int(m.group(1)) != HELP_SLOTS:
            out.append("GGUI.HELP_SLOTS is %s but this file lays out %d"
                       % (m.group(1), HELP_SLOTS))
        out += check_help_fits(lua_src)
        out += check_loc_keys(lua_src)
        out += check_panel_bg(lua_src)
        out += check_opener_crest(lua_src)
        # The guild buttons repaint their glyph by index; the plate is image 0.
        m = re.search(r"GGUI\.GUILD_BTN_ICON\s*=\s*(\d+)", lua_src)
        if not m or int(m.group(1)) != GTAB_ICON:
            out.append("GGUI.GUILD_BTN_ICON is %s but the guild buttons' glyph is image %d "
                       "- the Lua would paint over the plate and leave brass on every "
                       "button" % (m and m.group(1), GTAB_ICON))
        out += check_scale_anim(files, lua_src)

    # THE OPENER STACKS UNDER THE ZHARR EXCHANGE'S BUTTON, and when that mod is not
    # installed it takes the slot the Exchange would have used. The uninstalled case
    # cannot read EX.BUTTON_SIZE / EX.BUTTON_GAP, so it carries literals - and a
    # literal copy of another file's constant is exactly the kind of drift that shows
    # up as a button two pixels out of line and is never traced. Pin them.
    ex_lua = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign", "mod",
                          "zzz_derpy_chd_exchange.lua")
    gg_lua = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign", "mod",
                          "zzz_derpy_guilds_ui.lua")
    if os.path.isfile(ex_lua) and os.path.isfile(gg_lua):
        ex_src = io.open(ex_lua, encoding="utf-8").read()
        gg_src = io.open(gg_lua, encoding="utf-8").read()
        for const, pat in (("EX.BUTTON_SIZE", r"or (\d+)\n\s*local ex_gap"),
                           ("EX.BUTTON_GAP", r"local ex_gap = \(EX and EX.BUTTON_GAP\) or (\d+)")):
            m_ex = re.search(re.escape(const) + r"\s*=\s*(\d+)", ex_src)
            m_gg = re.search(pat, gg_src)
            if not m_ex:
                out.append("the Exchange script declares no %s" % const)
            elif not m_gg:
                out.append("zzz_derpy_guilds_ui.lua has no fallback for %s" % const)
            elif m_ex.group(1) != m_gg.group(1):
                out.append("the opener's %s fallback is %s but the Exchange ships %s"
                           % (const, m_gg.group(1), m_ex.group(1)))

    # THE PANEL MUST EAT THE MOUSE WHILE IT IS UP, AND LET GO WHEN IT IS NOT.
    # Both halves fail silently and the second is the worse one:
    #   1. Not interactive while open - the panel is scenery. The cursor reaches the
    #      campaign map through 790x700 of background, so hovering raises the region
    #      and army tooltips behind it and a click lands on the map too. This is what
    #      shipped, and it is what the player reported.
    #   2. Still interactive while hidden - a 790x700 dead zone in the middle of the
    #      map that nothing on screen explains. Nothing points at this mod.
    # GGUI.close DESTROYS the panel, so (2) cannot happen and a literal `true` is
    # correct. The moment close() hides instead, the flag has to be written from the
    # same variable as the visibility - so this refuses the literal in that case.
    lua_p = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign", "mod",
                         "zzz_derpy_guilds_ui.lua")
    if os.path.isfile(lua_p):
        src = io.open(lua_p, encoding="utf-8").read()
        code = chr(10).join(l for l in src.splitlines()
                            if not l.lstrip().startswith("--"))
        if "panel:SetInteractive(" not in code:
            out.append("the panel is never made interactive, so the cursor goes "
                       "through it to the campaign map and hovering it raises the "
                       "tooltips of whatever is behind")
        m = re.search(r"function GGUI\.close\(\).*?" + chr(10) + r"end", code, re.S)
        if not m:
            out.append("GGUI.close is gone - it is what makes a literal "
                       "SetInteractive(true) safe")
        elif ":Destroy()" not in m.group(0):
            if "panel:SetInteractive(true)" in code:
                out.append("GGUI.close no longer destroys the panel, so "
                           "SetInteractive(true) leaves an invisible dead zone over "
                           "the map - write the flag from the same value as the "
                           "panel's visibility instead")

    # AN UPSCALED ICON IS SOFT, AND NOTHING SAYS SO. Six of them shipped at 24x24
    # drawn into a 44x44 box. tools/ui_icon_sizes.json carries the native size of
    # every icon this pack draws, read out of the PNG header after extracting it with
    # RPFM; anything drawn larger than its source, or drawn without having been
    # measured at all, is refused here.
    try:
        sizes = json.load(io.open(os.path.join(os.path.dirname(
            os.path.abspath(__file__)), "ui_icon_sizes.json"), encoding="utf-8"))
    except Exception as e:
        sizes = None
        out.append("could not read ui_icon_sizes.json: %r" % (e,))
    if sizes is not None:
        drawn = [(OPENER_ICON, OPENER_W - 2 * _ICON_INSET),
                 (CREST_LAYERS[0]["path"], PANEL_LAYOUT["gg_crest"][2])]
        lua_i = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign",
                             "mod", "zzz_derpy_guilds_ui.lua")
        if os.path.isfile(lua_i):
            m = re.search(r"GGUI\.GUILD_ICON\s*=\s*\{(.*?)\n\}",
                          io.open(lua_i, encoding="utf-8").read(), re.S)
            if m:
                # The GLYPH's size, not the card_icon box's: the box is the holder now.
                box = CARD_GLYPH
                for _g, _p in re.findall(r'(\w+)\s*=\s*"([^"]+)"', m.group(1)):
                    drawn.append((_p, box))
        # EVERY FLAVOUR'S COPY is drawn in the same box as ours.
        ours = [(p, px) for p, px in drawn if "derpy_gg_icons/" in p]
        for tag in [t for t in G.FLAVOURS if t]:
            drawn += [(flavoured(p, tag), px) for p, px in ours]
        for path, px in drawn:
            if path not in sizes:
                out.append("%s is drawn at %dpx but its native size was never "
                           "measured - add it to tools/ui_icon_sizes.json"
                           % (path, px))
            elif sizes[path] < px:
                out.append("%s is %dpx native but drawn at %dpx, so it is upscaled "
                           "and will look soft" % (path, sizes[path], px))

    # A FONT CATEGORY THE GAME DOES NOT HAVE FALLS BACK IN SILENCE. There are 32 of
    # them in CA's ui packs and none is body_11 or body_14, which is what "body_%d"
    # built from a pixel size produces. See EU.FONTCATS.
    for fname, text in sorted(files.items()):
        for cat in sorted(set(re.findall(r'fontcat_name="([^"]*)"', text))):
            if cat not in EU.FONTCATS:
                out.append("%s: fontcat_name=%r is not one of the game's font "
                           "categories, so the label draws in a fallback font"
                           % (fname, cat))

    # THE LUA'S LAYOUT MUST MATCH THIS FILE'S. The .twui.xml tx/ty offsets position
    # nothing at runtime - measured live: every child sits at its parent's origin -
    # so zzz_derpy_guilds_ui.lua carries its own copy of these coordinates and
    # MoveTo's each component. Two copies of the same numbers drift silently, and the
    # symptom is components stacked on each other rather than an error.
    lua_tables = _lua_xy_tables()
    if lua_tables:
        for tbl, want in (("PANEL_XY", PANEL_LAYOUT),
                          ("CARD_CHILD_XY", CARD_LAYOUT),
                          ("ROW_CHILD_XY", ROW_LAYOUT)):
            got = lua_tables.get(tbl)
            if got is None:
                out.append("zzz_derpy_guilds_ui.lua declares no GGUI.%s - nothing "
                           "will be positioned" % tbl)
                continue
            for name, (x, y, _w, _h) in sorted(want.items()):
                if name not in got:
                    out.append("GGUI.%s is missing %s, so it stays at its parent's "
                               "origin" % (tbl, name))
                elif got[name] != (x, y):
                    out.append("GGUI.%s[%s] is %r but this file says %r"
                               % (tbl, name, got[name], (x, y)))
            for name in sorted(set(got) - set(want)):
                out.append("GGUI.%s has %s, which this file does not lay out"
                           % (tbl, name))
    else:
        out.append("could not read the campaign Lua's layout tables")

    # Every per-guild icon the Lua swaps in must exist, for the same reason every
    # baked-in imagepath must: a path the game does not have draws a blank square and
    # says nothing about it.
    lua_i = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign",
                         "mod", "zzz_derpy_guilds_ui.lua")
    if os.path.isfile(lua_i):
        src = io.open(lua_i, encoding="utf-8").read()
        m = re.search(r"GGUI\.GUILD_ICON\s*=\s*\{(.*?)\n\}", src, re.S)
        if not m:
            out.append("zzz_derpy_guilds_ui.lua declares no GGUI.GUILD_ICON")
        else:
            try:
                assets = _assets()
                named = dict(re.findall(r'(\w+)\s*=\s*"([^"]+)"', m.group(1)))
                import gen_great_guilds as GEN
                tags = [t for t in GEN.FLAVOURS if t]
                for g in GEN.GUILDS:
                    if g not in named:
                        out.append("GGUI.GUILD_ICON has no entry for %s" % g)
                    elif named[g] not in assets:
                        out.append("GGUI.GUILD_ICON[%s] does not exist in any ui "
                                   "pack: %s" % (g, named[g]))
                    else:
                        for tag in tags:
                            if flavoured(named[g], tag) not in assets:
                                out.append("GGUI.GUILD_ICON[%s] has no %s copy - %s is "
                                           "not staged, so that race's cards draw a "
                                           "blank square"
                                           % (g, tag, flavoured(named[g], tag)))
                for tag in tags:
                    if flavoured(OPENER_ICON, tag) not in assets:
                        out.append("the %s crest %s is not staged - GGUI.paint_crest and "
                                   "GGUI.paint_opener would paint a blank square"
                                   % (tag, flavoured(OPENER_ICON, tag)))
            except Exception as e:
                out.append("could not verify guild icons: %r" % (e,))

    # The Lua narrows the reputation bar to the fraction earned, so it carries its
    # own copy of the bar's full size. A disagreement here is a bar that never fills
    # or overflows its track - wrong in silence, like every other geometry drift.
    lua_path = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign",
                            "mod", "zzz_derpy_guilds_ui.lua")
    if os.path.isfile(lua_path):
        lua_src = io.open(lua_path, encoding="utf-8").read()
        for const, idx, what in (("REP_BAR_W", 2, "width"), ("REP_BAR_H", 3, "height")):
            m = re.search(r"GGUI\.%s\s*=\s*(\d+)" % const, lua_src)
            want = PANEL_LAYOUT["gg_rep_bar"][idx]
            if not m:
                out.append("zzz_derpy_guilds_ui.lua declares no GGUI.%s" % const)
            elif int(m.group(1)) != want:
                out.append("GGUI.%s is %s but gg_rep_bar's %s here is %d"
                           % (const, m.group(1), what, want))

    # EVERY COMPONENT THE LUA WRITES A LABEL ONTO NEEDS A <component_text> BLOCK.
    # Without one there is nothing for SetStateText to render into and the component
    # draws blank - a plate with no caption, which is how the tab row, the pager and
    # the Buy buttons shipped once they had art.
    for fname, names in (("derpy_gg_panel.twui.xml",
                          ["gg_title", "gg_rank_line", "gg_earned", "gg_footer"] + TABS
                          + ["gg_prev", "gg_next"] + GUILD_BTNS + LOG_FILTERS),
                         ("derpy_gg_card.twui.xml",
                          ["card_name", "card_desc_1", "card_desc_2",
                           "card_cost", "card_buy"]),
                         ("derpy_gg_row.twui.xml",
                          ["row_guild", "row_rank", "row_leader"]),
                         ("derpy_gg_frow.twui.xml", ["derpy_gg_frow"])):
        text = files.get(fname, "")
        for name in names:
            i = text.find('id="%s"' % name)
            if i < 0:
                continue
            nxt = text.find("\n\t\t<", i)
            body = text[i:nxt if nxt > 0 else len(text)]
            if "<component_text" not in body:
                out.append("%s: %s carries no component_text, so a label written to "
                           "it draws nothing" % (fname, name))
            else:
                # A text offset larger than the component pushes the label outside it.
                for attr, extent in (("textxoffset", "w"), ("textyoffset", "h")):
                    for val in re.findall(r'%s="(-?[\d.]+)' % attr, body):
                        lim = dict(PANEL_LAYOUT, **dict(CARD_LAYOUT, **ROW_LAYOUT)) \
                            .get(name)
                        if not lim:
                            continue
                        size = lim[2] if extent == "w" else lim[3]
                        if float(val) >= size:
                            out.append("%s: %s has %s=%s but is only %d%s wide/tall - "
                                       "the label is pushed outside its own box"
                                       % (fname, name, attr, val, size, "px"))

    # A CLICKABLE THING THE PLAYER CANNOT SEE IS THE SAME BUG AS A MISSING BUTTON.
    # These carry a click handler in the campaign Lua; without an image they are live
    # but invisible, which is how the tab row, the pager and every Buy button shipped.
    for fname, names in (("derpy_gg_panel.twui.xml",
                          TABS + ["gg_prev", "gg_next"] + GUILD_BTNS + LOG_FILTERS),
                         ("derpy_gg_panel.twui.xml", ["gg_close"]),
                         ("derpy_gg_card.twui.xml", ["card_buy"]),
                         ("derpy_gg_row.twui.xml", ["derpy_gg_row", "row_icon"])):
        text = files.get(fname, "")
        for name in names:
            i = text.find('id="%s"' % name)
            if i < 0:
                out.append("%s: %s is not declared" % (fname, name))
                continue
            nxt = text.find("\n\t\t<", i)
            body = text[i:nxt if nxt > 0 else len(text)]
            if "imagepath=" not in body and "componentimage=" not in body:
                out.append("%s: %s is clickable but carries no image, so it is a live "
                           "click target that draws nothing" % (fname, name))
            # SAME SHAPE, ONE SENSE OVER. soundcategory is the only route to a click
            # sound, and every one of these shipped without it: a button that looks
            # right, works, and makes no noise while CA's buttons beside it do.
            if "soundcategory=" not in body:
                out.append("%s: %s is clickable and carries no soundcategory, so it "
                           "clicks in silence" % (fname, name))
            # AND IT HAS TO BE INTERACTIVE, which is the one of these three that stops the
            # click happening at all rather than making it ugly. A component that is not
            # interactive does not raise ComponentLClickUp - the click falls through to
            # whatever is behind it, and nothing is logged.
            if 'interactive="true"' not in body:
                out.append("%s: %s is clicked by the campaign Lua but no state of it is "
                           "interactive, so it raises no click event at all" % (fname, name))

    # HOVERED AND CLICKED, BUT SILENT ON PURPOSE: the card and the faction row. Their
    # tooltips need them interactive, and so do the bounty board's and the Leaderboard's
    # map links - a click that is not interactive never reaches the Lua. They carry no
    # soundcategory; see _card(). Asserted here because set_tooltip also makes them
    # interactive at runtime, which would hide this file losing the flag until a click on
    # the board did nothing.
    for fname, name in (("derpy_gg_card.twui.xml", "derpy_gg_card"),
                        ("derpy_gg_frow.twui.xml", "derpy_gg_frow")):
        text = files.get(fname, "")
        i = text.find('id="%s"' % name)
        nxt = text.find("\n\t\t<", i)
        body = text[i:nxt if nxt > 0 else len(text)] if i >= 0 else ""
        if 'interactive="true"' not in body:
            out.append("%s: %s is not interactive, so its tooltip is never shown and "
                       "its map link never fires" % (fname, name))

    # AND THE CATEGORY MUST BE ONE CA HAS. An invented name is silent with no error -
    # the missing-attribute failure one layer down, and unreachable by reading our own
    # files, so this asks the game's ui packs.
    known = EU._game_sound_categories()
    for fname, text in sorted(files.items()):
        for cat in sorted(set(re.findall(r'soundcategory="([^"]+)"', text))):
            if cat not in known:
                out.append("%s: soundcategory %s appears in none of CA's ui packs, so "
                           "the button is silent" % (fname, cat))

    # And every surface that must READ as one needs at least one image. This is the
    # check that would have caught the invisible opener before it shipped.
    for fname, want in (("derpy_gg_opener.twui.xml", "gg_opener"),
                        ("derpy_gg_panel.twui.xml", "derpy_gg_panel"),
                        ("derpy_gg_card.twui.xml", "derpy_gg_card"),
                        ("derpy_gg_row.twui.xml", "derpy_gg_row"),
                        ("derpy_gg_list.twui.xml", "vslider")):
        text = files.get(fname, "")
        if "imagepath=" not in text:
            out.append("%s draws NOTHING - %s carries no componentimages, and a "
                       "component with no image is invisible however correctly it is "
                       "created and positioned" % (fname, want))

    for fname, text in sorted(files.items()):
        if any(ch.isupper() for ch in fname):
            out.append("uppercase in pack path crashes since patch 6.1: " + fname)

        hier = text.split("<hierarchy>", 1)[1].split("</hierarchy>", 1)[0]
        comps = text.split("<components>", 1)[1]
        hier_guids = set(re.findall(r'this="([^"]+)"', hier))
        comp_guids = set(re.findall(r'(?m)^\t\t<\w+[^>]*?this="([^"]+)"', comps))

        for g in sorted(comp_guids - hier_guids):
            out.append("%s: guid %s is in <components> with no <hierarchy> node "
                       "- a silent non-draw" % (fname, g))
        for g in sorted(hier_guids - comp_guids):
            out.append("%s: guid %s is in <hierarchy> with no component" % (fname, g))
        for g in sorted(comp_guids):
            if not g.startswith(GUID_PREFIX):
                out.append("%s: guid %s outside this file's %s range"
                           % (fname, g, GUID_PREFIX))
            if g.startswith("DE15"):
                out.append("%s: DE15 is RETIRED and must not be reused" % fname)

    out += check_scroll_parts(files)
    out += check_margins_fit_textures()

    # THE CREST FALLBACK MUST RESOLVE. It is drawn with [[img:]] markup rather than as a
    # component image, and that markup fails the same way an imagepath does: a path the
    # game does not have draws nothing at all and raises nothing.
    try:
        if FLAG_FALLBACK not in _assets():
            out.append("FLAG_FALLBACK %s is in none of the game's ui packs, so a faction "
                       "whose own crest cannot be read gets no crest and no error"
                       % FLAG_FALLBACK)
    except Exception as exc:                                       # noqa: BLE001
        out.append("could not verify FLAG_FALLBACK: %r" % (exc,))

    # AND THE LUA CARRIES ITS OWN COPY OF THE LIST GEOMETRY, like every other component
    # here, because the .twui.xml offsets do not position a runtime-created component. Two
    # copies of the same numbers drift in silence.
    lua_list = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign",
                            "mod", "zzz_derpy_guilds_ui.lua")
    if os.path.isfile(lua_list):
        src = io.open(lua_list, encoding="utf-8").read()
        for const, want in (("LIST_W", LIST_W), ("LIST_H", LIST_H)):
            m = re.search(r"GGUI\.%s\s*=\s*(\d+)" % const, src)
            if not m:
                out.append("zzz_derpy_guilds_ui.lua declares no GGUI.%s" % const)
            elif int(m.group(1)) != want:
                out.append("GGUI.%s is %s but this file says %d"
                           % (const, m.group(1), want))
        m = re.search(r"GGUI\.LIST_XY\s*=\s*\{\s*(\d+)\s*,\s*(\d+)\s*\}", src)
        if not m:
            out.append("zzz_derpy_guilds_ui.lua declares no GGUI.LIST_XY, so the list "
                       "stays at the panel's top-left corner over the guild rows")
        elif (int(m.group(1)), int(m.group(2))) != LIST_XY:
            out.append("GGUI.LIST_XY is %r but this file says %r"
                       % ((int(m.group(1)), int(m.group(2))), LIST_XY))
        m = re.search(r"GGUI\.LIST_CHILD_XY\s*=\s*\{(.*?)\n\}", src, re.S)
        if not m:
            out.append("zzz_derpy_guilds_ui.lua declares no GGUI.LIST_CHILD_XY")
        else:
            got = {n: (int(x), int(y)) for n, x, y in
                   re.findall(r"(\w+)\s*=\s*\{\s*(-?\d+)\s*,\s*(-?\d+)\s*\}",
                              m.group(1))}
            for name, (x, y, _w, _h) in sorted(LIST_LAYOUT.items()):
                if name not in got:
                    out.append("GGUI.LIST_CHILD_XY is missing %s, so it stays at its "
                               "parent's origin" % name)
                elif got[name] != (x, y):
                    out.append("GGUI.LIST_CHILD_XY[%s] is %r but this file says %r"
                               % (name, got[name], (x, y)))
            # list_box and handle must NOT be in it: the engine owns where those sit, and
            # moving a list_box is how a list scrolls to somewhere it is not.
            for name in ("list_box", "handle"):
                if name in got:
                    out.append("GGUI.LIST_CHILD_XY places %s, which the engine owns - "
                               "moving it fights the list layout and the slider" % name)

    # THE LIST MUST NOT LAND ON THE ROWS ABOVE IT OR THE PAGER BELOW. Everything on this
    # panel is placed by absolute MoveTo, so an overlap is not a layout error the engine
    # reports - it is two things drawn on top of each other.
    rows_end = 170 + (6 - 1) * 44 + ROW_H
    if LIST_XY[1] < rows_end:
        out.append("the faction list starts at y=%d and the six standings rows end at "
                   "y=%d - it would draw on top of them" % (LIST_XY[1], rows_end))
    pager_top = PANEL_LAYOUT["gg_prev"][1]
    if LIST_XY[1] + LIST_H > pager_top:
        out.append("the faction list ends at y=%d and the pager starts at y=%d"
                   % (LIST_XY[1] + LIST_H, pager_top))
    # THE EARNED LINE SITS IN THE BAND UNDER THE THIRD CARD AND OVER THE PAGER - the
    # Guilds tab shows all three, so anywhere else it is drawn on top of one of them.
    _ex, ey, _ew, eh = PANEL_LAYOUT["gg_earned"]
    card_end = PANEL_LAYOUT["gg_card_3"][1] + CARD_H
    if ey < card_end or ey + eh > pager_top:
        out.append("gg_earned runs y=%d..%d, outside the clear band y=%d..%d between the "
                   "third card and the pager - it would draw on top of one of them"
                   % (ey, ey + eh, card_end, pager_top))
    # A ROW WITH CHILDREN IS A ROW THAT COMES APART WHEN IT SCROLLS. Children here are
    # placed by absolute MoveTo and the engine's list layout moves the row without telling
    # anyone, so a cell would be left behind mid-panel. The crest is inline markup for
    # exactly this reason; this refuses the change that would quietly undo that.
    ftext = files.get("derpy_gg_frow.twui.xml", "")
    if ftext:
        fhier = ftext.split("<hierarchy>", 1)[1].split("</hierarchy>", 1)[0]
        if fhier.count("<derpy_gg_frow") and "</derpy_gg_frow>" in fhier:
            out.append("derpy_gg_frow has child components. A row inside the list is "
                       "moved by the engine when it scrolls, and a child positioned by "
                       "MoveTo does not follow it - it is left hanging in the panel. "
                       "The crest belongs inside the text as [[img:]] markup")
    if FROW_W > LIST_LAYOUT["list_clip"][2]:
        out.append("a faction row is %dpx wide and the clip window is %d - every row is "
                   "cut off at the right" % (FROW_W, LIST_LAYOUT["list_clip"][2]))

    # Panel children must fit inside the panel. Bounds() includes children and
    # Dimensions() does not, so an overhanging child is a silent misplacement.
    for name, (x, y, w, h) in sorted(PANEL_LAYOUT.items()):
        if x + w > PANEL_W or y + h > PANEL_H:
            out.append("panel child %s (%d,%d %dx%d) overhangs the %dx%d panel"
                       % (name, x, y, w, h, PANEL_W, PANEL_H))
    for name, (x, y, w, h) in sorted(CARD_LAYOUT.items()):
        if x + w > CARD_W or y + h > CARD_H:
            out.append("card child %s overhangs the %dx%d card" % (name, CARD_W, CARD_H))
    for name, (x, y, w, h) in sorted(ROW_LAYOUT.items()):
        if x + w > ROW_W or y + h > ROW_H:
            out.append("row child %s overhangs the %dx%d row" % (name, ROW_W, ROW_H))

    # Three cards on screen, three ranks per guild. If those ever disagree the
    # panel silently drops or duplicates one.
    # ONE CARD PER RANK: a guild holds a POOL of services per rank since 2026-09-29.
    per_guild = max(len(set(s["rank"] for s in G.SERVICES if s["guild"] == g))
                    for g in G.GUILDS)
    cards = len([n for n in PANEL_LAYOUT if n.startswith("gg_card_")])
    if cards != per_guild:
        out.append("%d card slots but %d ranks per guild" % (cards, per_guild))

    # Six guild pages, six pager stops.
    if len(G.GUILDS) != 6:
        out.append("the pager assumes six guild pages, generator has %d" % len(G.GUILDS))

    if len(PANEL_TITLE) > 19:
        out.append("panel title plate clips silently past ~19 chars: %r" % PANEL_TITLE)

    # THE ART AND ITS SCRIM MUST COVER THE SAME RECT. The scrim is what makes this
    # background dark enough to carry the Help tab's unplated body text, and the two are
    # separate layers - overscan one and not the other and the uncovered strip is the raw
    # picture at full brightness, a bright rim around a dark panel. Nothing in the file
    # ties them together, so this does.
    def _rect(lay):
        return (lay.get("offset", (0, 0)), lay.get("dw", 0), lay.get("dh", 0))
    art = [l for l in PANEL_LAYERS if l["path"] == PANEL_ART]
    scrim = [l for l in PANEL_LAYERS if l.get("colour") == PANEL_SCRIM]
    if len(art) != 1 or len(scrim) != 1:
        out.append("the panel ground is %d art layer(s) and %d scrim layer(s); this "
                   "check assumes exactly one of each" % (len(art), len(scrim)))
    elif _rect(art[0]) != _rect(scrim[0]):
        out.append("the panel art draws at %r and its scrim at %r - the uncovered strip "
                   "is unscrimmed art" % (_rect(art[0]), _rect(scrim[0])))

    # NO LAYER MAY DRAW OUTSIDE ITS COMPONENT. MEASURED IN GAME 2026-09-12: the engine does
    # NOT clip a child image to its component - an image given a rect larger than its parent
    # draws there, over whatever the panel happens to be sitting on. The panel ground was
    # overscanned by 16px to crop the art's dead outer rows and the result was a black ring
    # around the OUTSIDE of the gold frame, painted onto the campaign map. Every deliberate
    # inset in this file is negative dw/dh, which is safe for the same reason this is not.
    sized = (("panel", PANEL_LAYERS, (PANEL_W, PANEL_H)),
             ("card", CARD_LAYERS, (CARD_W, CARD_H)),
             ("card icon", CARD_ICON_LAYERS, tuple(CARD_LAYOUT["card_icon"][2:])),
             ("card cost", COST_LAYERS, tuple(CARD_LAYOUT["card_cost"][2:])),
             ("rank icon", RANK_ICON_LAYERS, tuple(PANEL_LAYOUT["gg_rank_mark"][2:])),
             ("rank bar", RANK_BAR_LAYERS, tuple(PANEL_LAYOUT["gg_rank_line"][2:])),
             ("title", TITLE_LAYERS, tuple(PANEL_LAYOUT["gg_title"][2:])),
             ("rep track", REP_TRACK_LAYERS, tuple(PANEL_LAYOUT["gg_bar_track"][2:])),
             ("guild bar", GBAR_LAYERS, tuple(PANEL_LAYOUT["gg_gbar"][2:])),
             ("tab", tab_plate("active"), (TAB_W, TAB_H)),
             ("row icon", ROW_ICON_LAYERS, tuple(ROW_LAYOUT["row_icon"][2:])),
             ("row", ROW_LAYERS, (ROW_W, ROW_H)))
    # AND EVERY RACE'S FRAME, which is where a fitted track or a two-layer tab could reach
    # past its box.
    for tag in FRAME_TAGS:
        f = frame(tag)
        sized += (
            (tag + " card", card_layers(tag), (CARD_W, CARD_H)),
            (tag + " card icon", holder_layers(CARD_LAYOUT["card_icon"][2],
                                               CARD_LAYOUT["card_icon"][3], CARD_GLYPH,
                                               CLEAR, tag),
             tuple(CARD_LAYOUT["card_icon"][2:])),
            (tag + " card cost", f["cost"], tuple(CARD_LAYOUT["card_cost"][2:])),
            (tag + " rank bar", f["rank"], tuple(PANEL_LAYOUT["gg_rank_line"][2:])),
            (tag + " rep track", f["track"], tuple(PANEL_LAYOUT["gg_bar_track"][2:])),
            (tag + " rep fill", f["fill"], tuple(PANEL_LAYOUT["gg_rep_bar"][2:])),
            (tag + " guild bar", f["gbar"], tuple(PANEL_LAYOUT["gg_gbar"][2:])),
            (tag + " tab", f["tab"]["layers"] + f["tab"]["hover"], (TAB_W, TAB_H)))
    for lname, layers, (cw, ch) in sized:
        for lay in layers:
            ox, oy = lay.get("offset", (0, 0))
            w, h = cw + lay.get("dw", 0), ch + lay.get("dh", 0)
            if ox < 0 or oy < 0 or ox + w > cw or oy + h > ch:
                out.append("%s layer %s draws (%d,%d %dx%d) outside its %dx%d component - "
                           "the engine does not clip, so this lands on whatever is behind "
                           "the panel" % (lname, lay["path"].rsplit("/", 1)[-1],
                                          ox, oy, w, h, cw, ch))
            # A NINE-SLICE WHOSE EDGES MEET HAS NO MIDDLE: the corners overlap and the
            # frame draws folded over itself. Top+bottom must stay under the drawn
            # height and left+right under the drawn width.
            m = lay.get("margin", 0)
            t, r, b, lft = tuple(m) if isinstance(m, (tuple, list)) else (m,) * 4
            if t + b >= h or lft + r >= w:
                out.append("%s layer %s has margins %r on a %dx%d image - the slices "
                           "overlap" % (lname, lay["path"].rsplit("/", 1)[-1],
                                        (t, r, b, lft), w, h))

    # DRAW ORDER IS NAME ORDER. Siblings are declared sorted, and a later sibling draws
    # over an earlier one - the holder must land on the bar, the bar under the buttons.
    order = sorted(PANEL_LAYOUT)
    for under, over in (("gg_rank_line", "gg_rank_mark"), ("gg_gbar", GUILD_BTNS[0])):
        if order.index(under) > order.index(over):
            out.append("%s sorts after %s, so it draws on top of it" % (under, over))

    # THE LUA REPAINTS THESE BY INDEX, so each index is pinned to the layer order here,
    # the way GUILD_BTN_ICON is: an index one off paints the glyph over the holder and
    # leaves the placeholder showing, with nothing in the log.
    lua_ix = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign", "mod",
                          "zzz_derpy_guilds_ui.lua")
    if os.path.isfile(lua_ix):
        src = io.open(lua_ix, encoding="utf-8").read()
        rank_glyph = len(RANK_ICON_LAYERS) - 1
        for const, want in (("CARD_ICON_INDEX", CARD_ICON), ("RANK_ICON_INDEX", rank_glyph)):
            m = re.search(r"GGUI\.%s\s*=\s*(\d+)" % const, src)
            if not m or int(m.group(1)) != want:
                out.append("GGUI.%s is %s but the glyph is image %d"
                           % (const, m and m.group(1), want))
        if CARD_ICON_LAYERS[CARD_ICON]["path"] == ICON_HOLDER:
            out.append("CARD_ICON points at the holder, not the glyph")
        # THE LIT CARD: the two glow layers by index, and the three paths the Lua swaps
        # between. Off must be what the file ships, or every card starts lit.
        for const, want in (("CARD_HEAT_INDEX", CARD_HEAT_INDEX),
                            ("CARD_RIM_INDEX", CARD_RIM_INDEX)):
            m = re.search(r"GGUI\.%s\s*=\s*(\d+)" % const, src)
            if not m or int(m.group(1)) != want:
                out.append("GGUI.%s is %s but that glow is card image %d"
                           % (const, m and m.group(1), want))
            if CARD_LAYERS[want]["path"] != CARD_OFF:
                out.append("card image %d ships %s, not the blank - the card starts lit"
                           % (want, CARD_LAYERS[want]["path"]))
        m = re.search(r'GGUI\.CARD_OFF\s*=\s*"([^"]+)"', src)
        if not m or m.group(1) != CARD_OFF:
            out.append("GGUI.CARD_OFF is %r but the generator says %r"
                       % (m and m.group(1), CARD_OFF))
        out += check_frame_mirror(src)

    out += check_frame_files(files)

    return out


def lua_frames(src):
    """GGUI.FRAME as the campaign Lua declares it: {tag: {key: path or [paths]}}."""
    m = re.search(r"GGUI\.FRAME\s*=\s*\{(.*?)\n\}", src, re.S)
    if not m:
        return None
    out = {}
    for key, body in re.findall(r'\n    (\[""\]|_\w+)\s*=\s*\{(.*?)\n    \},',
                                m.group(1), re.S):
        ent = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', body))
        for name, lst in re.findall(r"(\w+)\s*=\s*\{([^}]*)\}", body):
            ent[name] = re.findall(r'"([^"]*)"', lst)
        out["" if key == '[""]' else key] = ent
    return out


def check_frame_mirror(src):
    """GGUI.FRAME must say what FRAMES says, race by race and layer by layer.

    The Lua repaints the lit card's glows and the open tab's plates from its own copy. A
    drift is a Chaos Dwarf glow in an Empire frame, or a tab whose plate vanishes the
    moment it is opened - both silent.
    """
    out = []
    got = lua_frames(src)
    if got is None:
        return ["zzz_derpy_guilds_ui.lua declares no GGUI.FRAME"]
    for tag in [""] + FRAME_TAGS:
        f = frame(tag)
        want = {"heat": f["heat"][0], "rim": f["rim"][0],
                "active": [l["path"] for l in f["tab"]["layers"]],
                "hover": [l["path"] for l in f["tab"]["hover"]],
                "selected": list(f["tab"]["selected"]),
                "selected_hover": list(f["tab"]["selected_hover"])}
        if tag not in got:
            out.append("GGUI.FRAME has no %r entry - that race's glows and tabs fall back "
                       "to the Chaos Dwarf art in a frame that is not" % tag)
            continue
        for k, v in sorted(want.items()):
            if got[tag].get(k) != v:
                out.append("GGUI.FRAME[%r].%s is %r but FRAMES says %r"
                           % (tag, k, got[tag].get(k), v))
        n = set(len(want[k]) for k in ("active", "hover", "selected", "selected_hover"))
        if len(n) != 1:
            out.append("the %r tab states have %r layers - GGUI.paint_tab puts the hover "
                       "state's at image n, so every state needs the same count" % (tag, n))
    for tag in sorted(set(got) - set([""] + FRAME_TAGS)):
        out.append("GGUI.FRAME has %r, which FRAMES does not - GGUI.frame_path would ask "
                   "for a .twui.xml nobody writes" % tag)
    try:
        assets = _assets()
        for tag, ent in sorted(got.items()):
            for k, v in sorted(ent.items()):
                for p in (v if isinstance(v, list) else [v]):
                    if p not in assets:
                        out.append("GGUI.FRAME[%r].%s names %s, which is in no ui pack - "
                                   "it would draw a blank" % (tag, k, p))
    except Exception as e:                                          # noqa: BLE001
        out.append("could not verify GGUI.FRAME's art: %r" % (e,))
    return out


# THE CHAOS DWARFS' OWN ART, by where CA keeps it. None of it may be in another race's frame.
CHD_ART = ("dlc23_chd_", "dlc23_tower_of_zharr", "wh3_dlc23_chd_chaos_dwarfs")


def check_frame_files(files):
    """Each race's panel and card are the original's tree with only their art changed.

    The Lua creates the reader's copy and then reaches every component by name and
    repaints images by index, so a copy with one component more or less, or a GUID moved,
    is a panel that half-works for one race only. And the reason the copies exist is that
    no race but the Chaos Dwarfs wears Chaos Dwarf art.
    """
    out = []
    for base in ("derpy_gg_panel", "derpy_gg_card"):
        orig = files.get(base + ".twui.xml", "")
        tree = orig.split("<hierarchy>", 1)[-1].split("</hierarchy>", 1)[0]
        names = xml_component_names(orig) if orig else []
        for tag in FRAME_TAGS:
            fname = frame_file(base, tag)
            text = files.get(fname)
            if text is None:
                out.append("%s is not generated, so a %s reader's panel draws nothing"
                           % (fname, tag))
                continue
            if text.split("<hierarchy>", 1)[-1].split("</hierarchy>", 1)[0] != tree:
                out.append("%s's hierarchy is not %s.twui.xml's - same components, same "
                           "GUIDs, or the Lua reaches for parts that are not there"
                           % (fname, base))
            if xml_component_names(text) != names:
                out.append("%s declares different components from %s.twui.xml"
                           % (fname, base))
            for path in sorted(set(re.findall(r'imagepath="([^"]+)"', text))):
                if any(k in path for k in CHD_ART):
                    out.append("%s draws Chaos Dwarf art: %s" % (fname, path))
    for tag in FRAME_TAGS:
        f = frame(tag)
        for p in [f["heat"][0], f["rim"][0]] + list(f["tab"]["selected"]) \
                + list(f["tab"]["selected_hover"]):
            if any(k in p for k in CHD_ART):
                out.append("FRAMES[%r] swaps in Chaos Dwarf art at runtime: %s" % (tag, p))
    return out


def write_ui(outdir=None):
    outdir = outdir or OUT
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    written = [write_clear()]
    for fname, text in sorted(build_xml().items()):
        path = os.path.join(outdir, fname)
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        written.append(path)
    return written


def selftest():
    seen = {}
    for name in _ORDER:
        g = guid_for(name)
        assert g.startswith(GUID_PREFIX), "guid prefix: " + g
        parts = g.split("-")
        assert [len(p) for p in parts] == [8, 4, 4, 16], "guid must be 8-4-4-16: " + g
        assert g not in seen, "duplicate guid %s on %s and %s" % (g, name, seen.get(g))
        seen[g] = name

    files = build_xml()
    assert len(files) == 6 + 2 * len(FRAME_TAGS), (
        "six xml files and a panel and card per race frame, got %d" % len(files))

    total_guids = 0
    for path, text in sorted(files.items()):
        names = xml_component_names(text)
        assert names, "no components in " + path
        hier = text.split("<hierarchy>", 1)[1].split("</hierarchy>", 1)[0]
        for g in re.findall(r'this="([^"]+)"', hier):
            assert ('this="%s"' % g) in text.split("<components>", 1)[1], (
                "%s: %s in hierarchy but not in components" % (path, g))
        total_guids += len(set(re.findall(r'this="([^"]+)"', text)))

    # Every name the campaign Lua reaches for must exist in some file.
    lua_path = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign",
                            "mod", "zzz_derpy_guilds_ui.lua")
    if os.path.isfile(lua_path):
        lua = io.open(lua_path, encoding="utf-8").read()
        declared = set()
        for text in files.values():
            declared |= set(xml_component_names(text))
        # find_uicomponent is scanned too, not just comp(). The opener anchor is reached
        # that way, and a typo in a CA component name fails silently at runtime - the
        # button simply never appears, which is exactly the bug this list exists to catch.
        # Comments must come out FIRST. This file documents the CA components it no
        # longer uses - including the button_rituals mistake - and scanning raw text
        # reads those prose mentions as live references.
        code_lines = []
        for line in lua.splitlines():
            cut = None
            for k in range(len(line) - 1):
                if line[k] == "-" and line[k + 1] == "-" \
                        and line[:k].count('"') % 2 == 0:
                    cut = k
                    break
            code_lines.append(line if cut is None else line[:cut])
        code = "\n".join(code_lines)
        reached = (re.findall(r'comp\("([a-z0-9_]+)"', code)
                   + re.findall(r'find_uicomponent\([^,]+,\s*"([a-z0-9_]+)"', code))
        for m in reached:
            if m in HOST_COMPONENTS:
                continue
            base = re.sub(r"_\d+$", "_1", m)
            assert m in declared or base in declared, (
                "Lua reaches for %r, which no .twui.xml declares and which is "
                "not a known CA host component" % m)

    # THE RACE FRAME CHECKS MUST BE ABLE TO FAIL. Each fault below is one a later edit
    # could plausibly make, and each must be reported.
    assert not check_frame_files(files), check_frame_files(files)
    broken = dict(files)
    broken["derpy_gg_card_emp.twui.xml"] = broken["derpy_gg_card_emp.twui.xml"].replace(
        FRAMES["_emp"]["card"]["path"], CARD_LAYERS[0]["path"])
    assert any("Chaos Dwarf art" in m for m in check_frame_files(broken)), \
        "an Empire card on the Hell-Forge plate was not reported"
    broken = dict(files)
    del broken["derpy_gg_panel_ksl.twui.xml"]
    assert any("not generated" in m for m in check_frame_files(broken)), \
        "a missing Kislev panel was not reported"
    broken = dict(files)
    broken["derpy_gg_card_dwf.twui.xml"] = broken["derpy_gg_card_dwf.twui.xml"].replace(
        "<card_cost this=", "<card_price this=", 1)
    assert any("hierarchy" in m for m in check_frame_files(broken)), \
        "a Dwarf card with a renamed part was not reported"
    if os.path.isfile(lua_path):
        assert not check_frame_mirror(lua), check_frame_mirror(lua)
        assert any("no '_hef' entry" in m for m in check_frame_mirror(
            re.sub(r"\n    _hef = \{.*?\n    \},", "", lua, flags=re.S))), \
            "a Lua frame table without the High Elves was not reported"
        assert any("GGUI.FRAME['_emp'].rim" in m for m in check_frame_mirror(
            lua.replace(FRAMES["_emp"]["rim"][0], CARD_RIM, 1))), \
            "an Empire rim drifted to the Tower of Zharr glow was not reported"
        # The first path from FRAMES, not a literal: a literal went stale when the frames
        # were rebuilt, and the mutation then changed nothing.
        first = FRAMES["_brt"]["tab"]["selected"][0]
        cut = lua.replace('selected = {"%s", ' % first, 'selected = {', 1)
        assert cut != lua, "the Bretonnian mutation no longer matches the Lua"
        assert any("GGUI.FRAME['_brt'].selected" in m for m in check_frame_mirror(cut)), \
            "a Lua open Bretonnian tab one layer short was not reported"
        saved = FRAMES["_brt"]["tab"]["selected"]
        FRAMES["_brt"]["tab"]["selected"] = saved[:1]
        try:
            assert any("layers" in m for m in check_frame_mirror(lua)), \
                "an open Bretonnian tab with fewer layers than its slot was not reported"
        finally:
            FRAMES["_brt"]["tab"]["selected"] = saved

    assert not check(), "check() found problems: %r" % (check(),)
    print("selftest ok: %d files, %d guids" % (len(files), total_guids))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    if "--check" in sys.argv:
        problems = check()
        for p in problems:
            print("PROBLEM: " + p)
        sys.exit(1 if problems else 0)
    if "--write" in sys.argv:
        print("\n".join(write_ui()))
