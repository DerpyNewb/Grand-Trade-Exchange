# Building a custom UI panel (WH3)

Traced end to end while building the Zharr Exchange panel, 2026-09-04/05. Every rule below was
**measured in game**, most of them after shipping the wrong thing first; the screenshot that
caught each one is named. It covers shipping **your own** panel, as opposed to re-laying
out one of CA's.

The build is `tools/gen_exchange_ui.py` (three `.twui.xml` files) plus
`Modding Files/pack/script/campaign/mod/zzz_derpy_chd_exchange.lua` (creation, layout, text,
clicks). Read those two together with this.

## The shape: your own files, created at runtime

Never override a CA `.twui.xml`. It collides with every other mod touching that file and goes
stale on each patch. Ship your own layout files under `ui/campaign ui/` and create them into
the live UI from Lua:

```lua
core:get_ui_root():CreateComponent("derpy_chd_exchange_panel",
                                   "ui/campaign ui/derpy_chd_exchange_panel")
local panel = find_uicomponent(core:get_ui_root(), "derpy_chd_exchange_panel")
```

The path passed to `CreateComponent` has **no `.twui.xml` suffix**. The component id it creates
is the first argument, not anything inside the file.

The Exchange ships three files, and the split is the pattern:

| File | Created into | Why separate |
|---|---|---|
| `..._panel.twui.xml` | the UI root | one instance |
| `..._row.twui.xml` | the panel's `rows_holder` | **one instance per data item**, created in a loop |
| `..._button.twui.xml` | `button_rituals`'s parent | the HUD opener, lives in CA's button row |

A repeating row is its own file created N times. There is no data binding and no template
instancing available to a runtime component — you create the file once per row and set every
string yourself.

`[[wh3-twui-runtime-createcomponent-not-override]]`

## GUIDs: get them wrong and nothing draws, silently

Every component needs `this` / `uniqueguid`, and every state needs its own pair. A GUID that
collides with another file's, or one that appears in `<components>` with no matching node in
`<hierarchy>`, is a **silent non-draw** — no error, no log line, the widget is simply absent.

The Exchange's sparkline alone is 12 bar components per row. Hand-writing that is how you get a
collision, so `gen_exchange_ui.py` assigns them from a counter and its `selftest()` asserts
every GUID is unique across all three files and appears at least twice in the emitted XML
(once in each section). Reserve a prefix per file so nothing you ship can collide:

```
DE14xxxx  derpy_chd_rite_costs / _totals / _fire
DE15xxxx  RETIRED (was derpy_chd_ex_delta) - do not reuse
DE16xxxx  derpy_chd_exchange_panel
DE17xxxx  derpy_chd_exchange_row
DE18xxxx  derpy_chd_exchange_button
```

## The file skeleton

```xml
<?xml version="1.0"?>
<layout version="142" comment="..." precache_condition="">
  <hierarchy>
    <root this="GUID">
      <derpy_chd_exchange_row this="GUID">
        <row_name this="GUID"/>
      </derpy_chd_exchange_row>
    </root>
  </hierarchy>
  <components>
    <row_name this="GUID" id="row_name" tooltipslocalised="true"
              uniqueguid="GUID" currentstate="SGUID" defaultstate="SGUID">
      <componentimages>
        <component_image this="IGUID" uniqueguid="IGUID" imagepath="ui/skins/default/..."/>
      </componentimages>
      <states>
        <standard this="SGUID" name="standard" width="170" height="20" uniqueguid="SGUID">
          <imagemetrics>
            <image this="MGUID" uniqueguid="MGUID" componentimage="IGUID"
                   offset="0.00,0.00" width="170" height="20" margin="0.00,0.00,0.00,0.00"/>
          </imagemetrics>
          <component_text texthalign="Left" textvalign="Center" .../>
        </standard>
      </states>
    </row_name>
  </components>
</layout>
```

Three things that are easy to get wrong here:

- The tag name **is** the component name in both sections. `id=` repeats it.
- Width and height live on the **state**, not the component.
- An image is declared twice: once in `<componentimages>` (the texture) and once in
  `<imagemetrics>` (where and how big it draws in this state), linked by `componentimage`.

## Layout: `dockpoint` does not work, `MoveTo` does

**Measured 2026-09-04: the engine ignores `dockpoint` and `dock_offset` in the XML, and
`SetDockOffset` at runtime, for components you created yourself.** Every child rendered at its
parent's origin, stacked, so only the last-drawn one was visible and the footer painted over
the title.

`uicomponent:MoveTo(x, y)` with **absolute screen coordinates** is the only thing that
positions them. So the layout lives in the Lua as a table, not in the XML:

```lua
EX.PANEL_LAYOUT = { { "title_text", 20, 14 }, { "hdr_name", 54, 50 }, ... }

local px, py = panel:Position()
for _, e in ipairs(EX.PANEL_LAYOUT) do
    local c = find_uicomponent(panel, e[1])
    if is_uicomponent(c) then c:MoveTo(px + e[2], py + e[3]); c:SetVisible(true) end
end
```

Centre the panel from the root's own bounds, never from a constant:

```lua
local sw, sh = core:get_ui_root():Bounds()
local pw, ph = panel:Bounds()
panel:MoveTo(math.floor((sw - pw) / 2), math.floor((sh - ph) / 2))
```

Two consequences worth writing down:

- **The XML widths and the Lua offsets are two halves of one layout and nothing notices when
  one is edited alone.** `gen_exchange_ui.py` parses `EX.PANEL_LAYOUT` and `EX.ROW_LAYOUT` out
  of the Lua and asserts each header's x equals its row column's x plus the holder inset, that
  no column's width reaches the next column's x, and that the last column does not leave dead
  space inside the row.
- `MoveTo` still loses to a CA **layout group**. Inside `button_group_management` the docker
  re-places children every frame. Outside CA's docking groups it sticks.

`[[wh3-layout-group-overrides-moveto]]`

### Place what this view names, and HIDE EVERYTHING IT DOES NOT

An unplaced component keeps its last coordinates — or, if it has never been placed, the
`dock_offset` from the XML, which is the one moment that attribute means anything — and draws
over whatever the new view put there. So a layout pass has two halves, and the second is the one
that gets forgotten.

Measured 2026-09-09: a panel had run for months with its hide pass walking the column headers
**and nothing else**, and nothing was wrong, because every panel-level component that existed
was either a header or named by every layout table. The first table to name a cell no other
table named — a chart page — broke it on arrival. Its cells were never placed on page 1, never
hidden, and drew at their XML dock offsets straight across the list: a full-height bar over the
rows, four labels through the middle of them, and the pager still reading 1/2.

The fix is to hide against the **union of every layout table**, not against any one of them.
Build that union lazily and memoise it if the tables are declared below the function that reads
it — a file-scope union that reads a nil takes the whole file down at load, and the tell for
that is a `Loading mod file` line with no `loaded successfully`, the quietest failure there is.

The same rule holds one level down for a row's cells, and one level up for the rows themselves.
Three levels, one rule, and each was found the hard way.

## Textures

**Every `imagepath` must be a real entry in a shipped pack.** A path that does not exist renders
as a **blank white square** with no error anywhere. `button_icon_close_24.png` survived a full
deploy that way; it does not exist in any pack. A byte-grep is not proof — it matches strings
*inside* other files, not pack entries. `gen_exchange_ui.py::_game_assets()` reads every path
out of the game's `ui*.pack` files with `tools/read_pack_index.py`, caches it to
`.skilltree_cache/ui_asset_paths.json`, and the selftest fails on any path not in that set.

**The same rule covers a path built at RUNTIME, and that one needs asking for.** `_game_assets()`
walks the three generated `.twui.xml` files, so it never sees a path a Lua `SetImagePath` call
assembles — and those are the ones a screenshot is least likely to catch, because they draw on
a page the player sees once. The Zharr Exchange's introduction resolves nine of them
(`EX.art(stem)` → `ui/campaign ui/effect_bundles/<stem>.png`), and `check_intro_art()` holds
every one against the same cached index rather than enumerating the packs a second time.

**Where to shop for icons.** `ui/campaign ui/effect_bundles/` holds 980 flat, consistently
framed icons — including a `trait_*` crest for every race — and is the right family for
anything drawn at 24x24. Do not mix it with `ui/buildings/icons/`, whose entries are bordered
art tiles and read as a different size class beside it. **Look at the art before choosing it**:
the packs are zstd behind a `u32` length prefix (`read_vanilla_loc._decompress`), so a contact
sheet of candidates is a dozen lines of Pillow, and picking by filename is guessing.

**`tile="true"` REPEATS the texture; it does not stretch it.** The generator emitted it on every
image at first, so a 339x51 button texture in a 100x26 box drew as a narrow repeated slab beside
the label (screenshotted 2026-09-04). Only a genuine background tile wants it. CA's own button
templates emit `this` / `uniqueguid` / `componentimage` / `width` / `height` and nothing else —
no tile, no dockpoint, no margin.

**`margin` is the 9-slice inset** — which border of the texture must not be stretched or
repeated. With `margin="0,0,0,0"` on a tiled texture the transparent edge repeats and shows
through as a grid of seams. It also must be smaller than half the component: margin 14 on a
26px-tall box makes the middle slice negative.

**A panel background is two layers**, copied from CA's `ui/templates/panel_frame.twui.xml`:
`panel_back_tile.png` at margin 5 and `panel_back_border.png` at margin 30, both at
`priority="60"`. One flat image stretched to panel size reads as no background at all.

**`dockpoint` and `offset` on an `<image>` are cumulative, not alternatives.** CA insets its
body by (9,3) *and* docks it Center inside a 418x530 frame; copying both shifted our body 18
right and 6 down and left a bare strip along the right and bottom edges. The border draws over
the body, so a full-size body layer with no dockpoint is the safe shape.

**For a bar, a rule or any solid block use `ui/skins/default/1x1_blank_white.png` with a
`colour`.** A decorative texture squeezed to a few pixels averages out to nothing: the sparkline
bars were 7x14 slices of a 127x29 banner and read as faint dots; the row divider was
`parchment_divider.png` (256x256) squashed to 948x3 and was invisible. Colours are `#RRGGBBAA` —
alpha **last**.

**A left/right pair comes from ONE texture and `x_flipped="true"`.** CA ships no mirrored
arrow anywhere in `ui/skins/default`. Its own `ui/templates/cycle_button_arrow_next.twui.xml`
and `cycle_button_arrow_previous.twui.xml` name the **same five imagepaths** and differ by
exactly one attribute on the `<image>` metrics:

```xml
<image ... componentimage="..." width="49" height="45" x_flipped="true"/>
```

Two traps sit on top of that, and both shipped:

- **`x_flipped`, not `flipped`.** The short name is not an attribute the engine knows, and an
  unknown attribute is ignored in silence — two arrows pointing the same way, no error. Worse,
  a build-time check written against `flipped="true"` passes on **both** names, because it is a
  substring of the real one. Count the full string, and count it in the **rendered** file: a
  missing emitter in a generator looks identical from the generator's own side.
- **Flip every state.** The glyph is a layer of `standard` *and* `hover`; flipping only
  `standard` mirrors the arrow the instant the mouse arrives.

**`button_cycle_arrow_active.png` is not a glyph — it is a whole button.** That template names
the `button_cycle_arrow_*` files and nothing else, so the texture is an arrow-*shaped* red plate
with its own bronze border, 49x45. Laid over a plate of your own it reads as a slab with a mark
on it. `button_indicator_arrow_active.png` is the same kind of file. The bare directional glyph
that does exist is **`ui/skins/default/icon_credits_back.png`**: a flat bronze triangle pointing
LEFT on transparency, 56x56 — the same family as `icon_cross_small` and `icon_question_mark`,
so it sits on `button_round_small_active.png` exactly the way a close or help button does.

**To see a texture before you ship it**, pull it out of the pack and look: `read_pack_index.read`
gives the bytes, `read_vanilla_loc._decompress` strips the `u32`+zstd wrapper, and Pillow will
build a contact sheet. Twelve candidates on one sheet answered "which of these is a bare arrow"
in one look, after two rounds of guessing from filenames had produced the wrong texture twice.

`[[wh3-twui-arrow-direction-is-flipped-attribute]]` `[[wh3-twui-particle-colour-is-rgba]]`

## Text

```xml
<component_text texthalign="Center" textvalign="Center"
                textxoffset="4.00,0.00" textyoffset="0.00,0.00"
                texthbehaviour="Never split"
                font_m_size="13" font_m_colour="#FFF8D7FF"
                font_m_leading="3" fontcat_name="body_13"/>
```

- `texthalign` is **horizontal**, `textvalign` is **vertical**. The generator had them the other
  way round.
- The value is American **`Center`**. `Centre` is not in the engine's vocabulary and an unknown
  value is **ignored in silence**, so every button label sat left and high. Counted in
  `ui3.pack`: `textvalign` Center 8734 / Bottom 219, `texthalign` Center 3981 / Right 631.
- Set the string from Lua with `SetStateText`. Do not build a padded single-line header — the
  font is proportional, so spaces never line up with the columns below. Use **one label per
  column** and keep its x in step with the row's.
- A text offset larger than the box draws the text *outside* it: the first header carried
  `textyoffset="44.00,0.00"` in a 22px box, so it drew below itself behind row 1 and was
  invisible on screen. Vertical centring replaces every hand-tuned y nudge.

## Sound

UI click sound is a component **attribute**, not a script call:

```xml
soundcategory="UI_GBL_TMP_Square_Large_Text_Button"
```

`common.trigger_soundevent` takes a sound **event**; CA's UI clicks are driven by these
**categories**. An invented category name is silent with no error, so harvest real ones out of
`ui3.pack`. Four that are confirmed:

| Category | Uses in ui3.pack | For |
|---|---|---|
| `UI_GBL_HUD_Purchase` | — | a generic buy |
| `UI_GBL_TMP_Square_Large_Text_Button` | 39 | the rectangular text button |
| `UI_GBL_TMP_Round_Medium_Button` | 38 | a 48px round HUD button |
| `UI_GBL_TMP_Round_Small_Button` | 232 | a small round button |

A panel created at runtime is not an animated CA panel and has no open/close sound of its own.
The opener's and the close button's own clicks are what a player hears, and that is enough.

`gen_exchange_ui.py::selftest()` asserts every `interactive="true"` component carries a
`soundcategory`.

## Tooltips

**Literal text, never a loc key.** This section said the opposite until 2026-09-06 and the
example below used to be `{{tr:...}}`; both were wrong.

```xml
tooltipslocalised="true" componentleveltooltip="Buy a lot||Bought at the price shown."
```

`Title||Body` is CA's split, and it **only works as literal attribute text**. Routed through a
loc key of your own the pipes render verbatim on screen — screenshotted twice. `{{tr:X}}` is a
*text replacement* lookup (`ui_text_replacements_localised_text_X`) and that consumer is what
applies the split; a bare loc key never reaches it. All 498 vanilla loc values containing `||`
live in `ui_text_replacements`. CA writes 1,076 literal tooltips against 178 `{{tr:}}` ones.

The cost is that literal text is not localisable. That is the trade.

**A tooltip needs an INTERACTIVE component or it is never reached.** Counted in `ui3.pack`: of
1,747 `componentleveltooltip`s, **1,670 sit on an element declaring `interactive="true"`**, and
several of the 77 that do not are placeholders (`[PH] ...`, keyboard mash). CA's own words for
the flag, from `cco/documentation.html`: *"Interactivity determines if a component can handle
mouse interactions like clicks and mouseovers."* A tooltip on a plain text cell is set, correct
and invisible. Add `SetInteractive(true)` beside it — a cell that is not clickable can still be
hoverable.

**Length.** Over roughly 60 characters a tooltip without the `||` split renders in a box that
does not grow and clips mid-glyph on line two. CA's own literal tooltips that skip the split run
to a **median of 42 characters**.

### When the component's meaning changes between views: set it at runtime

A `componentleveltooltip` is one string for the life of the component. If a cell is reused — a
gold price in one view, a percentage in the next — no single attribute is true, and the pair goes
on at runtime instead:

```lua
c:SetTooltipText(text, true)     -- true = all states, or only the default state answers
c:SetInteractive(true)
```

Proven in game 2026-09-06 on plain text cells. **Keep these under ~60 characters and skip the
`||` split entirely** — the split has only ever been verified through the XML attribute, never
through `SetTooltipText`.

**And a view with nothing to say must CLEAR every cell, not skip it.** Reported from play
2026-09-08: the Zharr Exchange's Log view answered on hover with the Houses view's trend legend,
"^ up, v down, - held", over the line "Delisted. The house is gone." The writer returned early
for a view that had no tooltip table, so the cells kept what the last view wrote. Two halves,
and the second is the one that is easy to miss:

- **Walk the cell map, not the view's own entries.** Iterating this view's tooltips writes only
  the columns it explains; a column it does not mention is never touched and keeps what it had.
- **Walk every row, not just the ones this view draws.** A hidden row still holds its old text
  and is one view switch from showing it.

Clearing is a write, and the pair has to come apart:

```lua
c:SetTooltipText(text, true)
c:SetInteractive(text ~= "")     -- an empty tooltip on an interactive cell still eats the
                                 -- mouse and draws an empty box over the row
```

None of this fails loudly — the text is set, the component is valid, nothing throws, and it is
invisible in a screenshot taken with the pointer off the row. Only a player hovering the wrong
column ever sees it. `[[wh3-shared-cells-must-be-cleared-not-skipped]]`

Never **read** a HUD button's tooltip or image at runtime — `GetTooltipText` and `GetImagePath`
both hard-crash at the same address. `Position()` and `Bounds()` are safe.

`[[wh3-tooltip-pipe-split-needs-literal-text]]` `[[wh3-gettooltiptext-reads-current-state]]`
`[[wh3-placeholder-loc-key-silent-empty-tooltip]]`

## Your panel does not block the map until you say so

A runtime-created panel draws over the campaign map and **consumes nothing**. Hovering it raises
the region and army tooltips of whatever sits behind it, because a component that cannot handle
a mouseover does not eat one either.

```lua
panel:SetVisible(visible)
panel:SetInteractive(visible)    -- follows visibility; NEVER a literal true
```

**An interactive container does not swallow its children's clicks** — CA's rituals panel ships
`agent_list`, `bottom` and `action` interactive with working children inside them.

**Interactive-while-hidden is the worse bug**: a panel-sized dead zone in the middle of the map
that nothing on screen explains, and that no player would ever file against your mod. Write the
flag in the one place visibility is written, from the same variable.

## Clicks

One global listener, filtered on the component id, because `ComponentLClickUp` fires for every
click in the game:

```lua
core:add_listener("zharr_exchange_click", "ComponentLClickUp",
    function(context)
        local s = context.string
        return s == EX.BUTTON or s == "close_button" or s == "btn_buy" or s == "btn_sell"
    end,
    function(context)
        local clicked = UIComponent(context.component)
        local row = UIComponent(clicked:Parent())   -- the button carries no key
        local id = row:Id()
        ...
    end, true)
```

`context.string` is the clicked component's **id**, so every row's Buy button reports the same
`btn_buy` — walk up to the parent row and read its id to know which one. That is why row
components are named `<row>_<key>`.

Anything that changes game state must be multiplayer-safe: route it through
`CampaignUI.TriggerCampaignScriptEvent(faction_cqi, trigger_string)` and do the work in the
`UITrigger` handler. (The Exchange is single-player-shaped and calls `cm:` directly; a mod meant
for MP cannot.)

## Reaching a CA panel from your own

`PanelOpenedCampaign` fires for **every** panel, so the filter is mandatory, and the panel's
list is filled from its context a frame *after* it opens:

```lua
core:add_listener("zharr_exchange_rites_panel", "PanelOpenedCampaign",
    function(context) return context.string == "rituals_panel" end,
    function() cm:callback(EX.hide_cards, 0.1, "zharr_hide_cards") end, true)
```

Hiding cards you own inside CA's list is component-side and by id:

```lua
local list = find_uicomponent(core:get_ui_root(), "rituals_panel", "panel_frame",
                              "context_rituals_list")
for i = 0, list:ChildCount() - 1 do
    local e = UIComponent(list:Find(i))
    local rk = string.match(e:Id(), "CcoCampaignRitual%d+(.+)")
    if rk and string.sub(rk, 1, string.len(EX.PREFIX)) == EX.PREFIX then e:SetVisible(false) end
end
```

`[[wh3-panelopened-fires-for-every-panel]]`

## Placing a button on the HUD

**The HUD is not laid out when the first-tick callback runs.** Reading `button_rituals` then
reported a position off the edge of the screen: our button was placed at 2517,1429 on a
2717x1419 display — invisible. Once the HUD settles the same button reads 1705,846.

The anchor can also be **absent** at that moment, so a one-shot `CreateComponent` silently did
nothing forever. Retry **creation and placement**, and reject an off-screen answer:

```lua
function EX.place_button(attempt)
    local root = core:get_ui_root()
    local b = find_uicomponent(root, EX.BUTTON)
    -- CREATE ON THE UI ROOT. Never on the anchor - see "the anchor is a ruler" below.
    if not is_uicomponent(b) then
        root:CreateComponent(EX.BUTTON, EX.BUTTON_FILE)
        b = find_uicomponent(root, EX.BUTTON)
    end
    local x, y, anchor = EX.button_anchor()
    if not is_uicomponent(b) or not x or x < 0 or x + 48 > sw then
        if attempt < 8 then
            cm:callback(function() EX.place_button(attempt + 1) end, 2.0, "..." .. attempt)
        end
        return
    end
    b:MoveTo(x, y); b:SetVisible(true)
    -- READ IT BACK. Nothing else in the engine reports a lost layout fight.
    local ax, ay = b:Position()
    if ax ~= x or ay ~= y then out("MoveTo OVERRIDDEN - something else lays this out") end
end
```

### The anchor is a RULER, never a parent

An earlier version of the snippet above did `UIComponent(rites:Parent()):CreateComponent(...)`.
**That is a bug, and it shipped.** `button_rituals:Parent()` is `button_group_management`, which
carries

```xml
<LayoutEngine type="RadialList" starting_angle="3.64773798" arc="3.490659"
              spacing="0.715584993" radius="95" clockwise="true"/>
```

A layout group **owns** its children's positions, so the button became an extra slot on the
Chaos Dwarf ring and CA moved it back onto the arc on every re-layout. `MoveTo` does not lose a
fight with a layout engine — it never gets to have one.

Create on the UI root (the same parent a runtime panel uses, no `LayoutEngine`, always present)
and only **read** coordinates off the anchor. Reading cannot be overridden; being a child can.

### A component's box is not its art

Three HUD anchors have now been wrong, all the same way:

| anchor | what went wrong |
|---|---|
| `button_rituals:Parent()` | RadialList owns its children |
| `root:Bounds()` for the screen size | `Bounds()` includes children; use `Dimensions()` |
| `resources_bar_holder:Position()` | its own child **overhangs it on both sides** |

That last one, measured live on 1920x1080:

```
resources_bar_holder   pos 564,0    792x67
resources_bar          pos 431,-4  1019x60    <- the art, 133px left and 94px right of its parent
```

The holder's 792x67 box describes nothing that is drawn. **Measure the component that is
actually drawn, live, on every placement call** — never derive a HUD position from CA's XML
(the strip's `docked Top Center` + `anchor 0.50` + `offset 404` works out to ~968 by hand and is
wrong by 460px), and never from a parent's declared size.

### A fallback must not resolve to different geometry

The teleport that followed: the anchor fell back to the holder when the child was not yet
readable, so the first-tick placement and the first click disagreed by 133px and the button
visibly jumped. Both lines were in `script_log`:

```
opener button at 512,9 (resources_bar_holder)
opener button at 379,9 (resources_bar_holder)
```

**A fallback that resolves to a different position turns "not ready yet" into a guaranteed
visible jump.** Fall back only when the anchor is *absent entirely* (a CA rename); while it is
merely still loading, retry. And put the anchor's name in the log line — a silent fallback
otherwise reads as the button moving on its own.

`[[wh3-uicreated-fires-before-world]]` `[[wh3-layout-group-overrides-moveto]]`
`[[wh3-bounds-includes-children-dimensions-does-not]]`

## `find_uicomponent` returns `false`, not `nil`

This cost a full debugging round and a deploy. `find_uicomponent` returns boolean `false` when
it finds nothing, so `tostring(c ~= nil)` prints `true` for a component that does not exist
while `if c then` takes the false branch. **Use `is_uicomponent(c)`**, always — including in
debug probes, which is where the wrong answer did the damage.

The same probe had a mistyped component name in it. A wrong name and a genuinely missing
component are indistinguishable at the call site, so check the constant before believing the
probe.

`[[wh3-lua-nil-vs-false-and-call-each]]`

## `is_uicomponent()` is a TYPE test — never cache a component

The companion trap, and a worse one, because the guard *looks* like it is doing the checking.
`is_uicomponent(c)` answers "is this a UIComponent value", **not** "does this component still
exist". A component the engine has since destroyed passes it happily.

So a cache like this is a bug with a delayed fuse:

```lua
EX.rows[res] = find_uicomponent(holder, name)   -- held for the whole session
...
local row = EX.rows[res]
if is_uicomponent(row) then                     -- passes, even when row is dead
    set_text(row, "row_name", ...)              -- -> find_uicomponent(<dead parent>, ...)
end
```

The failure surfaces one call later and **inside CA's code**, which is what makes it hard to
trace back:

```
ERROR: find_single_uicomponent() called but supplied parent [UIComponent (...)] is not a ui component
ERROR: uicomponent_descended_from() called but supplied uicomponent [UIComponent (...)] is not a ui component
ERROR: output_uicomponent() called but supplied object [UIComponent (...)] is not a ui component
```

One session logged **1,350 of these in eight minutes** and grew `script_log` from 988KB to
2.2MB; the HUD button stopped responding because CA's click plumbing could not even *log* the
clicked component before erroring. There is no liveness accessor to call instead — a dead handle
is indistinguishable from a live one until you use it — so **the rule is not to keep one**. Look
the component up fresh. Two `find_uicomponent` calls on a panel open cost nothing.

The one thing worth caching is a *number* you derived from a component (a measured anchor
position), never the component itself.

`[[wh3-is-uicomponent-is-a-type-test]]`

## Hover states

Two separate things have to be right, and getting either wrong is silent.

**1. The transition map is what makes a state reachable.** A `<hover>` state with no
`<transitionmap>` edge pointing at it is never entered — the state is in the file, the engine
has no way to reach it, and the button simply never lights. The vocabulary, read out of CA's own
`ui/templates/round_small_button.twui.xml` in `ui3.pack`:

| `index` | edge |
|---|---|
| omitted (0) | mouse enters |
| `1` | mouse leaves |
| `2` | mouse down |

CA's eleven-state button is an explicit graph — `active -> [(0, hover)]`,
`hover -> [(1, active), (2, down)]`. The minimum useful pair is two states and two edges:

```xml
<standard this="SGUID" name="standard" width="100" height="26" interactive="true" ...>
  <imagemetrics>...the unlit texture...</imagemetrics>
  <transitionmap>
    <transition transition_m_target_state="HGUID"/>
  </transitionmap>
  <component_text .../>
</standard>
<hover this="HGUID" name="hover" width="100" height="26" interactive="true" ...>
  <imagemetrics>...the lit texture...</imagemetrics>
  <transitionmap>
    <transition index="1" transition_m_target_state="SGUID"/>
  </transitionmap>
  <component_text .../>
</hover>
```

`<componentimages>` is a **component**-level list; each state's `<imagemetrics>` picks the
entries it draws by GUID. A texture used by both states appears twice in that list, which is
harmless — CA does the same.

Every state needs its own `<component_text>` or the label draws in the engine's default font the
instant the mouse arrives. Every `_active` texture in `ui/skins/default` has a `_hover` sibling.

**2. `SetStateText` writes to the CURRENT STATE ONLY** — CA documents it in those words. A
button with a hover state whose label is set once draws *nothing* while the mouse is over it,
and the label returns when the mouse leaves. Write it into each state, and **restore** the state
rather than forcing `standard`: a panel that refreshes after a click is refreshing a button the
mouse is by definition still over.

```lua
local was = c:CurrentState()
c:SetState("hover")    c:SetStateText(text)
c:SetState("standard") c:SetStateText(text)
if was and was ~= "" and was ~= "standard" then c:SetState(was) end
```

Do this only for components that actually have two states; `SetState` with a name a component
does not have returns false, and calling it on every text cell of every row is unmeasured noise.

A **tab** is still not worth it: it needs `selected` and `selected_hover` too, doubling the
states again for a control that a pair of arrow buttons and a page counter already expresses.

`[[wh3-hover-state-needs-transitionmap]]` `[[wh3-setstatetext-is-per-state]]`

## What you cannot do

- **Widen a panel title plate.** A renamed header clips silently at about 19 characters.
- **Two prices on one rites-panel row**, or colouring a two-resource cost —
  `can_afford_resource_cost` returns one boolean for the whole row.
- **Give a runtime component a CCO context** it did not inherit, except by `SetContextObject`
  with a CCO type you can name.
- **Call a CCO function with an argument** — `AgentSubtypeCap(key)` and friends null-deref the
  game.

`[[wh3-panel-title-plate-cannot-widen]]` `[[wh3-runtime-component-has-no-context]]`

## Build-time checks that earned their place

Each of these was added after the fault it catches shipped at least once. This is the list to
copy into the next UI generator:

| Check | Fault it caught |
|---|---|
| every GUID unique, and paired between the two sections | silent non-draw |
| every `imagepath` present in a shipped `ui*.pack` | blank white square |
| every `interactive` component has a `soundcategory` | a silent panel |
| `texthalign`/`textvalign` in the engine's vocabulary | labels left and high |
| header x == row column x + holder inset | headers not over their columns |
| no column's width reaches the next column's x | "TrendLast 12 turns" |
| the last column leaves under 24px inside the row | 90px of dead space right of Sell |
| the panel background keeps two layers with non-zero margins | tiling seams |
| no `\|\|` in any **loc** value (literal attribute text only) | pipes drawn verbatim on screen |
| every tooltip's component is interactive | a correct tooltip nothing can reach |
| the panel's interactive flag follows its visibility | a dead zone on the map after close |
| on-disk TSV row counts match `build()` | a stale table nearly shipped a removed feature |
| every component in the XML is named by some layout table | a cell nothing ever places, hidden on every page, drawing nowhere |
| the XML's geometry constants equal the runtime's own copies | the fortieth bar walked off the end of the plot |
| a label is asserted on its TEXT, not on its visibility | a dead commodity's price scale beside "nothing chosen" |

The last three are 2026-09-09 and are worth a sentence each. **A component the layout tables do
not name cannot draw at all** once the hide pass walks their union — the fault flips from "draws
in the wrong place forever" to "never draws", which is quieter still. **A generator that lays a
chart out at build time and a runtime that re-positions every bar from its own copies of the
same constants share nothing but a comment**, and a pitch one pixel wider on one side is silent
in both directions. And **a drawn label is not a placed one**: the layout pass shows every cell
the current view names, so visibility proves the cell is there and says nothing about whether
anything wrote into it.

Two lessons about the checks themselves, from the same day:

- **A check that reads its expectation from the code it is checking asserts only that the code
  equals itself.** A layout harness that asked the function under test both which components to
  create *and* which set to verify was blind by construction: delete a layout table and its
  cells were never created either, so nothing was left visible and the mutant walked. The
  harness now scans for the layout tables itself and reports what the function under test is
  missing.
- **A harness that stubs a setter away cannot tell "painted" from "left up".** Record what
  `SetImagePath` and `SetStateText` were handed and assert on that, not on `SetVisible`.

## Reading CA's names LIVE: the context viewer

CA ships a UI inspector and it is off by default: **Settings -> Modding -> Enable context
viewer**. It gives you a **Component Tree** (every component, searchable, with a Live Update
Tree toggle) and a **Context menu** showing the CCO context objects and their queries under the
cursor — `CcoCampaignRoot`, `FactionList (837)`, `SettlementList (753)` and so on, which is
where a `context_key` in a `.twui.xml` expression comes from.

**Turn it on before doing any HUD work.** Two rounds of this workspace's UI debugging were spent
reconstructing by hand what it shows at a glance — byte-scanning `ui3.pack` for component ids
and firing `wh3_eval` probes for positions.

### The names are exact, and several are plural

The first search that failed here was `resource_bar`. The component is **`resources_bar`**
— plural — and a near-miss returns nothing, which looks exactly like
"this component does not exist": the same indistinguishable-failure shape as a mistyped name
in a `find_uicomponent` probe. Confirmed live in the viewer, the chain is

```
root > hud_campaign > resources_bar_holder > resources_bar
```

with `resources_bar` as child **0** of the holder and 43 children of its own (`treasury_holder`,
`court_boon_holder`, and one holder per race mechanic). The detail pane names the parent for
you — `CcoComponent ParentContext` reads `16. resources_bar_holder` — so a component
found by search tells you its whole chain without walking the tree.

The tree also starts collapsed at `root`, so expand or use the search box rather than expecting
to see the HUD laid out.

### What it does NOT replace

It shows you names and context. It does **not** tell you that a component's box differs from its
art — `resources_bar_holder` looks like a perfectly good anchor in the tree and is a 792x67 box
around a 1019x60 child that overhangs it on both sides. **Names come from the viewer; geometry
still has to be measured at runtime** with `Position()` and `Dimensions()`. See "A component's
box is not its art" above.

Never read a HUD button's `GetTooltipText()` or `GetImagePath()` — both hard-crash. Position and
bounds are safe.

`[[wh3-panel-icons-derived-in-twui]]`

## Reading CA's names offline

- Textures and layout files: `tools/read_pack_index.py` lists every path in any `.pack`, and
  returns the bytes of uncompressed entries, with RPFM closed. `.twui.xml` is text, so a
  byte-grep reaches it; DB table contents it never reaches.
- Display names: `tools/read_vanilla_loc.py` parses CA's `text/db/*.loc` — zstd behind a `u32`
  prefix, then `\xff\xfeLOC`, a `u32` version, a `u32` count, then `u16` char count plus
  UTF-16LE for **both** key and value. That is how the Exchange shows "Salt" rather than
  `rom_lead`; the resource keys and their display names disagree in vanilla (`res_rom_lead` is
  Salt, `res_rom_glass` is Dwarf Beer, `res_rom_textiles` is Pottery).
- Icons: `resources_tables.icon_filepath`, read out of the same cache.

`[[wh3-byte-grep-reaches-text-not-db]]` `[[wh3-vanilla-loc-readable-offline]]`
