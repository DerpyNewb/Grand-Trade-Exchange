"""The Great Guilds' XML emitter. A COPY of the Zharr Exchange's, deliberately.

WHY A COPY. gen_guilds_ui.py used to import gen_exchange_ui and call its emitter
directly, so three fixes made for the Guilds silently changed the EXCHANGE's shipped
output as well: snapping font categories to the ones the game actually has stepped
the Exchange's own labels from body_11 to body_10 on 16 panel cells and body_13 to
body_12 on 4 row cells. Every one of those was a real fix, and none of them was this
mod's decision to make for another mod that is already published.

Two mods that ship separately do not share a code path that changes what they emit.
The duplication is the point.

WHAT DIFFERS FROM THE EXCHANGE'S COPY:
  * fontcat()  - font category is a fixed 32-name vocabulary, not a number. The
    Exchange builds "body_%d" from the pixel size, which mints body_11/13/14 -
    names the game does not have. An unknown value is not an error and not a blank:
    the engine falls back, so the label draws at a size nobody chose. Here the size
    snaps to the nearest real body category, or fontcat= names one outright.
  * leading    - font_m_leading was hardcoded to 3. On a one-line button caption
    that is an offset, not leading, and it dropped the glyphs onto the plate's
    bottom rim. kw["leading"] now sets it, default 3.

Everything else is byte-for-byte the Exchange's emitter as of 2026-09-11. If a fix
here is general, port it across deliberately rather than by sharing the module.
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III"


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


# FONT CATEGORY IS A FIXED VOCABULARY, NOT A NUMBER. Counted across ui.pack,
# ui2.pack and ui3.pack: 32 distinct fontcat_name values, and the only BODY sizes in
# them are 10, 12 and 16. This emitter built the name as "body_%d" from the requested
# pixel size, so every size-14 label in the Exchange and the Guilds shipped
# fontcat_name="body_14" - a category the game does not have. An unknown value is not
# an error and not a blank; the engine falls back, so the label draws at a size nobody
# chose. That is why button captions and card text never matched their layout.
#
# Snap to the nearest real body category, or pass fontcat= to name one outright (the
# header_* family are the other real ones - see FONTCATS).
FONTCATS = set("""
body_10 body_12 body_16 body_12_bold body_12_italic body_alternative_12
header_12 header_14 header_16 header_18 header_20_bold header_24_bold
header_16_bold header_18_bold header_alternative_18
dev_text dev_text_on_white dev_text_grey dev_button_text dev_subheader
dev_header dev_item_header dev_text_grey_disable dev_text_dark_grey_on_white
grudges_subheader
""".split())

_BODY_SIZES = (10, 12, 16)


def fontcat(kw):
    """The font category for a text block: an explicit fontcat=, else nearest body."""
    named = kw.get("fontcat")
    if named:
        assert named in FONTCATS, "no such font category: %r" % (named,)
        return named
    size = kw.get("size", 12)
    return "body_%d" % min(_BODY_SIZES, key=lambda n: abs(n - size))


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
            # Vertical, same naming: y_flipped is on 319 image elements in CA's ui packs.
            if lay.get("vflip"):
                out += '\t\t\t\t\t\t\ty_flipped="true"\n'
            if dock:
                out += '\t\t\t\t\t\t\tdockpoint="%s"\n' % dock
            if lay.get("colour"):
                out += '\t\t\t\t\t\t\tcolour="%s"\n' % lay["colour"]
            # A SHADER ON ONE IMAGE, not the state: shader_name plus shadertechnique_vars on
            # the <image>, the shape 44 of CA's campaign smoke layers use. On the STATE
            # (shadervars) it would run over every layer the component draws.
            if lay.get("shader"):
                out += '\t\t\t\t\t\t\tshader_name="%s"\n' % lay["shader"]
                out += ('\t\t\t\t\t\t\tshadertechnique_vars="%s"\n'
                        % lay.get("shader_vars", "0.00,0.00,0.00,0.00"))
            # A number is all four sides; a 4-tuple is top,right,bottom,left, CA's order
            # (TWUI Studio's rasteriser reads it the same way). CA's Chaos Dwarf bars slice
            # left and right only - cap_title_holder is 0,50,0,60 - which one number cannot say.
            m = lay.get("margin", 0)
            m = tuple(m) if isinstance(m, (tuple, list)) else (m,) * 4
            out += '\t\t\t\t\t\t\tmargin="%.2f,%.2f,%.2f,%.2f"/>\n' % tuple(map(float, m))
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
                '\t\t\t\t\t\tfont_m_leading="%d"\n\t\t\t\t\t\tfontcat_name="%s"/>\n'
                % (kw.get("align", "Left"), kw.get("valign", "Center"),
                   kw.get("tx", "4.00,0.00"),
                   kw.get("ty", "8.00,0.00"), kw.get("size", 12),
                   kw.get("colour", "#FFF8D7FF"), kw.get("leading", 3),
                   fontcat(kw)))

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
    # ---------------------------------------------------- the scrolling attributes ----
    # None of these existed here until the Guilds needed a list that scrolls. A scrolling
    # list in this engine is not a widget you switch on: it is four components with
    # RESERVED NAMES (list_clip, list_box, vslider, handle) carrying RESERVED CALLBACKS
    # (List, VSlider, VSliderHandle), and the engine wires them to each other by those
    # names. Read out of CA's own ui/common ui/tab_completer.twui.xml, the smallest panel
    # in the game with exactly one of them, and checked against it by check_scroll_parts.
    #
    # Every one of these is silent when absent: no error and no log line, the list simply
    # does not scroll and the slider is a decoration that can be dragged and moves nothing.
    if kw.get("clipchildren"):
        # WHAT MAKES A LIST A WINDOW rather than a pile that overflows the panel. Without
        # it the rows past the bottom draw over whatever is below them.
        attrs.append('clipchildren="true"')
    if kw.get("docking"):
        attrs.append('docking="%s"' % kw["docking"])
    if kw.get("relativeresize"):
        # The child follows its parent's resize. list_clip needs it, or resizing the list
        # leaves the clip window at its authored size and the rows are cut at the old edge.
        attrs.append('isrelativeresize="true"')
    if kw.get("moveable"):
        # The slider handle is DRAGGED. Without this it is a picture.
        attrs.append('moveable="%s"' % kw["moveable"])
    if kw.get("allowhresize") is False:
        attrs.append('allowhorizontalresize="false"')

    attrs += ['uniqueguid="%s"' % c.gid,
              'currentstate="%s"' % c.sid, 'defaultstate="%s"' % c.sid]
    out = "\t\t<%s\n\t\t\t%s>\n" % (c.name, "\n\t\t\t".join(attrs))

    # THE CALLBACKS ARE THE BEHAVIOUR. A component named list_box with no List callback is
    # an ordinary container; the callback is what makes the engine treat its children as a
    # list and the vslider as that list's scrollbar. CA's order is callbacks, then user
    # properties, then images, then states, then the layout engine - matched here because
    # this file is read back against CA's own.
    if kw.get("callbacks"):
        out += "\t\t\t<callbackwithcontextlist>\n"
        for cb in kw["callbacks"]:
            out += '\t\t\t\t<callback_with_context callback_id="%s"/>\n' % _esc(cb)
        out += "\t\t\t</callbackwithcontextlist>\n"

    # The slider's travel. maxValue is how far the handle may run and min_size how small
    # it may shrink on a long list; CA sets both on every slider it ships.
    if kw.get("props"):
        out += "\t\t\t<userproperties>\n"
        for pname in sorted(kw["props"]):
            out += ('\t\t\t\t<property\n\t\t\t\t\tname="%s"\n'
                    '\t\t\t\t\tvalue="%s"/>\n'
                    % (_esc(pname), _esc(str(kw["props"][pname]))))
        out += "\t\t\t</userproperties>\n"

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
    out += "\t\t\t</states>\n"

    # A ZERO-LENGTH FONT-SCALE ANIMATION, for a runtime that rewrites its frame and plays
    # it: the only route to a label's drawn size (see gen_guilds_ui.SCALE_ANIM). Shape
    # copied from CA's ui/common ui/scripted_topic_leader.twui.xml - tag and id alike,
    # after <states> and before <LayoutEngine>, width and height written as CA writes
    # them. interpolationpropertymask 512 animates font_scale and nothing else.
    anim = kw.get("font_anim")
    if anim:
        out += ('\t\t\t<animations>\n\t\t\t\t<%s\n\t\t\t\t\tid="%s">\n'
                '\t\t\t\t\t<frames>\n\t\t\t\t\t\t<frame\n'
                '\t\t\t\t\t\t\tinterpolationtime="0"\n'
                '\t\t\t\t\t\t\tinterpolationpropertymask="512"\n'
                '\t\t\t\t\t\t\ttargetmetrics_m_height="%d"\n'
                '\t\t\t\t\t\t\ttargetmetrics_m_width="%d"\n'
                '\t\t\t\t\t\t\ttargetmetrics_m_font_scale="1"/>\n'
                '\t\t\t\t\t</frames>\n\t\t\t\t</%s>\n\t\t\t</animations>\n'
                % (anim, anim, c.h, c.w, anim))

    # WHAT STACKS THE ROWS. Runtime-created children of a list_box are placed by this
    # engine and not by MoveTo - the one place in this whole mod where MoveTo is the wrong
    # tool, because a layout group owns its children's positions and beats it.
    # sizetocontent is what lets the box grow past the clip window, which is the only
    # reason there is ever anything to scroll to.
    le = kw.get("layoutengine")
    if le:
        out += '\t\t\t<LayoutEngine\n\t\t\t\ttype="%s"' % _esc(le["type"])
        if le.get("margins"):
            out += '\n\t\t\t\tmargins="%s"' % _esc(le["margins"])
        if le.get("sizetocontent"):
            out += '\n\t\t\t\tsizetocontent="true"'
        out += ">\n"
        if le.get("columns"):
            out += "\t\t\t\t<columnwidths>\n"
            for cw in le["columns"]:
                out += '\t\t\t\t\t<column width="%s"/>\n' % cw
            out += "\t\t\t\t</columnwidths>\n"
        out += "\t\t\t</LayoutEngine>\n"

    out += "\t\t</%s>\n" % c.name
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

def _game_sound_categories():
    """Every soundcategory CA uses anywhere in its own ui packs, cached.

    A category that does not exist is SILENT with no error - the same silent-failure
    shape as a missing imagepath. .twui.xml is stored as text in the ui packs, so a byte
    scan reaches it without RPFM and without decoding anything.
    """
    import json
    cache = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         ".skilltree_cache", "ui_sound_categories.json")
    if os.path.isfile(cache):
        return set(json.load(open(cache, encoding="utf-8")))
    pat = re.compile(br'soundcategory="([^"]{1,80})"')
    data = os.path.join(GAME, "data")
    out = set()
    for name in sorted(os.listdir(data)):
        if not name.endswith(".pack") or not name.startswith("ui"):
            continue
        # Chunked with an overlap, so a category straddling a chunk boundary is still
        # found and ui.pack's 892MB never lands in memory at once.
        tail = b""
        with open(os.path.join(data, name), "rb") as fh:
            while True:
                blob = fh.read(1 << 26)
                if not blob:
                    break
                blob = tail + blob
                out.update(m.group(1).decode("utf-8", "ignore")
                           for m in pat.finditer(blob))
                tail = blob[-128:]
    assert out, "no soundcategory found in any ui pack under %s" % data
    if not os.path.isdir(os.path.dirname(cache)):
        os.makedirs(os.path.dirname(cache))
    json.dump(sorted(out), open(cache, "w", encoding="utf-8"))
    return out


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

