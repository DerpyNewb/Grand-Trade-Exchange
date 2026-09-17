-- WHERE EVERY ROW ACTUALLY LANDS, run against the shipped EX.layout.
--
-- Reported from a screenshot 2026-09-08: two rows drawn ON TOP of two others in the Houses
-- view, 22 names in 20 slots. Nothing that reads the source can see that - it is a question
-- about the SET of visible components and their y coordinates after a real layout pass, so
-- this stubs a panel and reads the coordinates back.
local SAVED = {}
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function(_, k, v) SAVED[k] = v end,
    get_saved_value = function(_, k) return SAVED[k] end,
    get_local_faction_name = function() return "player" end,
    get_faction = function() return false end,
    turn_number = function() return 10 end,
}
core = { add_listener = function() end, get_ui_root = function() return ROOT end }
function out() end

-- A FAKE COMPONENT. Records what was done to it and nothing else.
local ALL = {}
local function comp(name, parent)
    local c = { name = name, x = 0, y = 0, vis = true, kids = {}, text = "" }
    c.MoveTo = function(_, x, y) c.x, c.y = x, y end
    c.Position = function() return c.x, c.y end
    c.Dimensions = function() return 900, 700 end
    c.Bounds = function() return 900, 700 end
    c.SetVisible = function(_, v) c.vis = v and true or false end
    c.Visible = function() return c.vis end
    -- PER-STATE, not one scalar - c.text ALONE cannot tell "written to every state" from
    -- "written to whichever one happened to be current", and that gap is the whole of the
    -- order ticket's blanking bug: SetStateText writes ONE state on the real engine, and a
    -- blank that skips the dual write set_text() does leaves "hover" holding the last
    -- commodity's numbers. c.text stays a mirror of the "standard" state so every scene
    -- written before the ticket existed keeps reading exactly what it always read.
    c.states = { standard = "" }
    c.cur = "standard"
    c.SetStateText = function(_, t)
        c.states[c.cur] = t
        c.text = c.states.standard or ""
    end
    c.SetTooltipText = function() end
    c.SetInteractive = function() end
    -- RECORDED, not swallowed, and for the fourth time in this file the same lesson: a stub
    -- that swallows the behaviour under test turns a real check green. A greyed button is the
    -- only thing that tells a player the market is shut BEFORE they click, and with this as a
    -- no-op a mutant that never disabled anything survived a full round (2026-09-16).
    c.disabled = false
    c.SetDisabled = function(_, v) c.disabled = v and true or false end
    -- RECORDED, not swallowed. "the icon cell is visible" is not "the icon was
    -- painted": EX.layout SHOWS every cell its table names, so a draw_chart that never
    -- touched the icon still leaves a visible - and blank, or worse, still carrying the
    -- previous commodity's picture - cell behind it. The image path is the only signal
    -- that says which of the two happened.
    c.img = nil
    c.SetImagePath = function(_, path) c.img = path end
    c.SetCanResizeWidth = function() end
    c.SetCanResizeHeight = function() end
    -- RECORDED, not swallowed, for the reason SetImagePath is. place() Resizes a cell
    -- to the width its layout table gives it, and set_text() forces any cell it writes
    -- to SetVisible(true) - so a cell left OUT of a layout table still draws, still
    -- carries text, and is still the width the LAST view gave it. Prose at a price
    -- column's width is 200px of an 850px paragraph and nothing raises.
    c.w, c.h = nil, nil
    c.Resize = function(_, w, h) c.w, c.h = w, h end
    c.SetState = function(_, st) c.cur = st end
    c.CurrentState = function() return c.cur end
    c.Id = function() return c.name end
    -- CA's own child enumeration, 0-based, which is what EX.layout hides by. The order is
    -- insertion order here; the engine's is its own, and nothing below depends on it.
    c.order = {}
    c.ChildCount = function() return #c.order end
    c.Find = function(_, j) return c.order[j + 1] end
    c.CreateComponent = function(_, n)
        -- CreateComponent with a name that already exists is a NO-OP here, which is the
        -- charitable reading. If the engine instead makes a SECOND sibling, the duplicate is
        -- unreachable by name and never placed or hidden - see the note in the check.
        -- comp() already registers in ALL; appending here too counted every row TWICE and
        -- made the clash report fire on rows against themselves.
        if not c.kids[n] then
            c.kids[n] = comp(n, c)
            c.order[#c.order + 1] = c.kids[n]
        end
    end
    if parent then
        parent.kids[name] = c
        parent.order[#parent.order + 1] = c
    end
    ALL[#ALL + 1] = c
    return c
end

ROOT = comp("root")
local PANEL, HOLDER

function find_uicomponent(from, name)
    if from == nil then return nil end
    if from.name == name then return from end
    for _, k in pairs(from.kids or {}) do
        local hit = find_uicomponent(k, name)
        if hit then return hit end
    end
    return nil
end
function is_uicomponent(c) return type(c) == "table" and c.MoveTo ~= nil end
function UIComponent(c) return c end

dofile([[%s]])
EX.store = SAVED

-- Build the panel by hand, the way EX.build_panel would, then let EX.layout do the work.
PANEL = comp(EX.PANEL, ROOT)
HOLDER = comp("rows_holder", PANEL)
for _, n in ipairs({ EX.NAV_PAGE, EX.MODE_BTN, EX.MODE_PREV, EX.HELP_BTN, "close_button",
                     "footer_text", "footer_text2", "title" }) do
    comp(n, PANEL)
end
for hid in pairs(EX.TIP_CELL) do comp(hid, PANEL) end
for _, m in ipairs(EX.MODES) do comp(EX.tab_name(m), PANEL) end
-- EVERY REMAINING PANEL CHILD ANY VIEW NAMES. The list above is what build_panel creates
-- by hand; this catches the ones only a layout table knows about - the deep chart, whose
-- components exist in the .twui.xml, are named ONLY by PANEL_LAYOUT_CHART, and were
-- therefore never created here at all. A component this harness does not create cannot
-- be seen to be left on screen, so the fault was invisible to it by construction.
-- Guarded: comp() overwrites parent.kids[name], so a second "rows_holder" would replace
-- HOLDER with an empty one and every row scene would report zero.
--
-- FOUND BY SCANNING EX FOR THE LAYOUT TABLES, NOT BY CALLING EX.panel_cells(). The first
-- version of this asked panel_cells() - the function under test - which made the harness
-- blind by construction: dropping PANEL_LAYOUT_CHART from the union meant the chart cells
-- were never created here either, so nothing was left visible and the mutant survived. A
-- check that reads its expectation from the code it is checking asserts only that the
-- code equals itself.
local MYCELLS, MYTABLES = {}, 0
for k, v in pairs(EX) do
    if type(v) == "table" and string.sub(k, 1, 12) == "PANEL_LAYOUT" then
        MYTABLES = MYTABLES + 1
        for _, e in ipairs(v) do MYCELLS[e[1]] = true end
    end
end
local missing = 0
for id in pairs(MYCELLS) do
    if not PANEL.kids[id] then comp(id, PANEL) end
    if not EX.panel_cells()[id] then missing = missing + 1 end
end
print("union tables=" .. MYTABLES .. " missing=" .. missing)
comp(EX.BUTTON, ROOT)

EX.screen = function() return 1920, 1080 end
EX.built = true
EX.place_button = function() end
EX.refresh_panel = function() end
EX.faction_display = function(f) return f end
EX.icon = function() return nil end

local HOUSES = {}
for i = 1, 41 do HOUSES[i] = "skv_clan_" .. (i < 10 and "0" or "") .. i end
EX.houses = HOUSES
EX.LAYER2 = {}

-- The row components, created once - exactly what EX.build_panel does, and the point is that
-- it does it ONCE, from the instrument list as it stood at build time.
local function build_rows()
    for _, res in ipairs(EX.instruments()) do
        local name = EX.ROW .. "_" .. EX.short(res)
        HOLDER:CreateComponent(name)
        -- AND ITS CELLS. Until 2026-09-09 the rows were created empty, because every scene
        -- here measured whether a ROW was visible and where it sat - never what one said. A
        -- row with no cells cannot be asked, so a draw that wrote nothing into any of them
        -- read as a clean pass. EX.ROW_CELLS is the row's own list, the same one EX.layout
        -- hides against.
        for _, cell in ipairs(EX.ROW_CELLS) do
            HOLDER.kids[name]:CreateComponent(cell)
        end
    end
    -- THE LEDGER'S OWN POOL, mirroring EX.build_panel's EX.ORDER_MAX loop exactly. Without
    -- this the orders_p3 scene below would report visible=0 no matter what EX.layout does -
    -- EX.row("ord1") finds nothing, so the whole placement loop skips every ledger row
    -- silently, which is a worse failure than a wrong number: a passing "0 == 0" nobody asked
    -- for.
    for i = 1, EX.ORDER_MAX do
        local name = EX.ROW .. "_ord" .. i
        HOLDER:CreateComponent(name)
        for _, cell in ipairs(EX.ROW_CELLS) do
            HOLDER.kids[name]:CreateComponent(cell)
        end
    end
end
build_rows()

local function report(tag, extra)
    -- What SHOULD be on screen right now, straight off the mode - the check compares the
    -- rows actually visible against this, so a row from another view still showing counts.
    local want = {}
    for _, res in ipairs(EX.mode_instruments()) do
        want[EX.ROW .. "_" .. EX.short(res)] = true
    end
    local seen, clash = {}, {}
    local shown, stale = 0, 0
    for _, c in ipairs(ALL) do
        if c.vis and string.sub(c.name, 1, #EX.ROW) == EX.ROW then
            shown = shown + 1
            if not want[c.name] then stale = stale + 1 end
            local key = c.y
            if seen[key] then clash[#clash + 1] = seen[key] .. "+" .. c.name end
            seen[key] = c.name
        end
    end
    -- THE SAME RULE ONE LEVEL UP. A panel-level component this view does not name was
    -- never MoveTo'd, so it is still at the last view's coordinates - or, if no view has
    -- ever placed it, at the dock offset in the .twui.xml, which for the chart cells is
    -- the top-left of the panel, straight over the commodity list. Screenshotted
    -- 2026-09-09; the row count above was 0 and every check was green.
    local pwant = {}
    for _, e in ipairs(EX.panel_layout()) do pwant[e[1]] = true end
    local pstale, pfirst = 0, nil
    for id in pairs(MYCELLS) do
        local c = PANEL.kids[id]
        if c and c.vis and not pwant[id] then
            pstale = pstale + 1
            if not pfirst or id < pfirst then pfirst = id end
        end
    end
    print(tag .. " visible=" .. shown .. " clashes=" .. #clash .. " stale=" .. stale
        .. " pstale=" .. pstale .. (pfirst and (" pfirst=" .. pfirst) or "")
        .. (clash[1] and (" first=" .. clash[1]) or "")
        .. (extra or ""))
end

EX.mode = EX.MODE_HOUSES
EX.house_page = 1
EX.layout()
report("houses_p1")

EX.house_page = 2
EX.layout()
report("houses_p2")

-- NOW PRUNE, the way EX.prune_houses does at turn start, and lay out again WITHOUT rebuilding
-- the row components. This is the shape the screenshot showed: rows that are no longer in the
-- instrument list, still visible, still where the last pass put them.
local kept = {}
local DROP = { [7] = true, [14] = true, [21] = true, [28] = true, [35] = true }
for i = 1, #HOUSES do if not DROP[i] then kept[#kept + 1] = HOUSES[i] end end
EX.houses = kept
EX.house_page = 1
EX.layout()
report("after_prune")

-- ...and DISCOVERY, which adds houses the panel has no component for.
local grown = {}
for i = 1, #kept do grown[i] = kept[i] end
for i = 1, 6 do grown[#grown + 1] = "skv_new_" .. i end
EX.houses = grown
EX.layout()
report("after_discover")

-- Back to the trade view: no house row may survive the switch.
EX.mode = EX.MODE_TRADE
EX.trade_page = 1
EX.layout()
report("trade_after")

-- TRADE PAGE 2, THE DEEP CHART. Not a mode change - the same view, one page across - and
-- the two scenes that follow are the ones that matter. On page 2 every commodity row and
-- every column header has to be gone; on the way BACK to page 1 the chart has to be gone.
-- The second of those is what shipped broken: the hide pass walked EX.HEADERS.trade, so
-- the chart's six panel-level components were never named by it and drew over the list.
EX.trade_page = 2
EX.layout()
report("chart_p2")

EX.trade_page = 1
EX.layout()
report("trade_p1_back")

-- TRADE PAGE 3, THE STANDING-ORDER LEDGER. A LADDER - two orders on res_gems at different
-- rungs, plus one on res_dyes - because that IS the feature: the user chose a free list
-- capped at EX.ORDER_MAX with several orders allowed on one instrument, over one slot per
-- instrument, and laddering is the stated reason. Rows keyed by RESOURCE (the old
-- EX.ROW .. "_" .. EX.short(res) naming) would put both gem rungs on the SAME physical
-- component - three orders, two visible rows, and Cancel on either one removing whichever
-- rung the collapsed row happened to be showing. Rows are keyed by ORDER INDEX instead
-- ("ord1".."ordN" - see EX.mode_instruments and EX.order_of_row), so this scene is what
-- proves three orders draw three rows and each Cancel click hits the rung it was clicked on.
EX.orders = {
    { res = "res_gems", side = "b", cmp = "le", rung = 28 },  -- first gem rung
    { res = "res_gems", side = "b", cmp = "le", rung = 20 },  -- second gem rung
    { res = "res_dyes", side = "s", cmp = "ge", rung = 30 },  -- the other commodity
}
EX.trade_page = 3
EX.layout()
-- MISSING, SPECIFIC TO PANEL_LAYOUT_ORDERS - not the same number as the "union missing="
-- line above, though it is built the same way: a cell this table names that
-- EX.panel_cells() does not carry can never be taken off screen by EX.layout, and draws at
-- its last coordinates over whatever the next view puts there.
local missing_ord = 0
for _, e in ipairs(EX.PANEL_LAYOUT_ORDERS) do
    if not EX.panel_cells()[e[1]] then missing_ord = missing_ord + 1 end
end
-- EACH ROW'S OWN ORDER, not just how many rows there are. Rungs stand in for the order
-- sentence EX.order_text would draw (EX.order_text's own wording is pinned separately in
-- _orders_harness.lua) - 28/20/30 are three different numbers, so a row answering the wrong
-- one is caught the same way a wrong sentence would be. "nil" if the row resolves to nothing.
local function row_rung(i)
    local o = EX.order_of_row(EX.ROW .. "_ord" .. i)
    return o and tostring(o.rung) or "nil"
end
report("orders_p3", " rows=" .. #EX.orders .. " missing=" .. missing_ord
    .. " r1=" .. row_rung(1) .. " r2=" .. row_rung(2) .. " r3=" .. row_rung(3))

-- CANCEL THE FIRST GEM RUNG - exactly what clicking Cancel on row 1 sends: the row's OWN
-- resolved order, not its position in the list. EX.cancel_order is the model half of
-- EX.order_cancel_send; the network round trip is covered in _orders_harness.lua.
local o1 = EX.order_of_row(EX.ROW .. "_ord1")
EX.cancel_order(o1.res, o1.side, o1.cmp, o1.rung)
EX.layout()
-- BOTH SURVIVORS CHECKED, NOT JUST THE FIRST. table.remove shifted the second gem rung down
-- to slot 1 and dyes to slot 2 - querying only row 1 here would read right even under the
-- mutation that always answers EX.orders[1], because row 1 legitimately IS EX.orders[1].
-- Row 2 is what tells them apart: correct code says dyes (30), the mutation still says 20.
report("orders_ladder_cancel1", " left=" .. #EX.orders
    .. " r1=" .. row_rung(1) .. " r2=" .. row_rung(2))

-- ...AND THE REMAINING GEM RUNG, LEAVING ONLY THE OTHER COMMODITY'S ORDER STANDING.
local o1b = EX.order_of_row(EX.ROW .. "_ord1")
EX.cancel_order(o1b.res, o1b.side, o1b.cmp, o1b.rung)
EX.layout()
report("orders_ladder_cancel2", " left=" .. #EX.orders .. " r1=" .. row_rung(1))

-- ...AND PAGING BACK LEAVES NOTHING OF THE LEDGER STANDING - the same fault the chart page
-- shipped with: a row or a header this view does not name keeps the coordinates the ledger
-- left it at and draws over the list.
EX.trade_page = 1
EX.layout()
report("trade_p1_orders_back")
EX.orders = {}

-- THE INTRODUCTION, and the way out of it. It is the only view a player does not choose -
-- EX.show puts them in it - so it is also the only one whose exit nothing else exercises.
-- Two things have to hold: its own cells are placed on the way in, and NONE of them is left
-- on screen on the way out. The second is the fault the chart page shipped with, and this
-- view is more exposed to it than the chart was: it has no column headers, so every cell the
-- trade view expects is one this view never places.
EX.mode = EX.MODE_INTRO
EX.layout()
report("intro")

EX.mode = EX.MODE_TRADE
EX.trade_page = 1
EX.layout()
report("after_intro")

-- ONCE, AND ONLY ONCE. Every scene above draws the introduction; none of them can tell a page
-- shown once from a page shown on every opening, which is the failure a player would actually
-- report. Three states, all worth pinning: unseen on a fresh campaign, retired by LEAVING and
-- not by arriving, and still retired afterwards.
--
-- A TAG OF ITS OWN, not "intro" again: report() and this line both feed one dict keyed by tag,
-- so reusing it would silently drop the scene's own counts.
EX.store = {}
local seen_fresh = EX.intro_seen()
EX.mode = EX.MODE_INTRO
local seen_arrived = EX.intro_seen()
EX.set_mode(EX.MODE_TRADE)
local seen_left = EX.intro_seen()
print("intro_once fresh=" .. tostring(seen_fresh)
    .. " arrived=" .. tostring(seen_arrived)
    .. " left=" .. tostring(seen_left))

-- ...AND THE DRAW, which is a separate question from the layout and was not asked until three
-- mutants walked. Coming in FROM the trade view is the case that matters: the introduction
-- borrows the very row components the commodity list uses, so a spare row it fails to hide is
-- a price left sitting under a paragraph.
EX.mode = EX.MODE_TRADE
EX.trade_page = 1
EX.layout()
EX.mode = EX.MODE_INTRO
EX.layout()
EX.draw_intro(PANEL, HOLDER)

local shown, texted, empty_shown = 0, 0, 0
-- iconed: visible cell carrying an image. bare: cell deliberately put away for a paragraph
-- break. icon_x: where the first picture landed, -1 until one is seen.
local iconed, bare, icon_x = 0, 0, -1
-- ASKED THE WAY THE CODE ASKS. Rows are keyed by commodity - EX.ROW .. "_" .. EX.short(res) -
-- not by slot index, so a loop over 1..MAX_ROWS finds nothing and reports a clean zero, which
-- is the shape of a check that passes because it looked in the wrong place.
for _, res in ipairs(EX.mode_instruments()) do
    local row = EX.row(HOLDER, res)
    if row then
        local cell = row.kids and row.kids["row_name"]
        local pic = row.kids and row.kids["icon"]
        if row.vis then
            shown = shown + 1
            -- PAINTED, LEFT UP, OR PUT AWAY - three states, and only the image path can tell
            -- the first two apart. EX.ROW_LAYOUT_INTRO names the icon cell, so EX.layout has
            -- already made every one of them visible: a draw that never touched them would
            -- leave nineteen visible cells wearing whatever the trade view last painted.
            if pic and pic.vis and pic.img then iconed = iconed + 1
            elseif pic and not pic.vis then bare = bare + 1 end
            -- AND WHERE the picture sits, RELATIVE TO ITS ROW. place() MoveTos to
            -- row_x + offset, so the recorded x is absolute and wherever the panel happens
            -- to be centred is in it. The offset is what the layout table states.
            if pic and pic.vis and icon_x < 0 then icon_x = pic.x - row.x end
            -- VISIBLE AND CARRYING TEXT ARE DIFFERENT QUESTIONS, the lesson the chart icon
            -- taught: EX.layout shows every cell the view names, so visibility alone cannot
            -- tell a drawn line from a row that was simply left up.
            if cell and cell.vis and cell.text ~= "" then texted = texted + 1
            else empty_shown = empty_shown + 1 end
        end
    end
end
-- HOW MANY OF THE LINES ARE MEANT TO CARRY TEXT. Two of them are deliberately empty - the
-- paragraph breaks either side of the body - so "no visible row may be blank" would be a
-- check that fails on correct code, and relaxing it to "some row has text" would pass on
-- eleven paragraphs missing out of twelve.
local want, want_icon = 0, 0
for _, l in ipairs(EX.intro_lines()) do
    if l[1] ~= "" then want = want + 1 end
    if l[2] then want_icon = want_icon + 1 end
end
-- AND THE WIDTH THE PARAGRAPH ACTUALLY GOT. One cell is enough: they are all placed by
-- the same loop off the same table.
local w = 0
for _, res in ipairs(EX.mode_instruments()) do
    local row = EX.row(HOLDER, res)
    local cell = row and row.kids and row.kids["row_name"]
    if cell and cell.vis and cell.w then w = cell.w break end
end
print("intro_draw shown=" .. shown .. " texted=" .. texted
    .. " want=" .. want .. " width=" .. w .. " lines=" .. #EX.intro_lines()
    .. " iconed=" .. iconed .. " bare=" .. bare .. " want_icon=" .. want_icon
    .. " icon_x=" .. icon_x)

-- ---------------------------------------------------------------- THE CHART'S OWN LABELS
-- Laying the chart out proves its cells are placed and hidden. It says nothing about what
-- they SAY, and a label is a panel-level component: it keeps its last text forever unless
-- something writes over it. So chart furs, click away, and the furs price scale is still
-- standing beside "No commodity chosen" - the same class of fault as the log rows keeping
-- another commodity's icon, and equally invisible to a layout pass.
local CHART_CELLS = { "chart_y_hi", "chart_y_mid", "chart_y_lo",
                      "chart_x_left", "chart_x_mid", "chart_x_right" }

local function report_chart(tag)
    local filled = 0
    for _, n in ipairs(CHART_CELLS) do
        local c = PANEL.kids[n]
        if c and c.text ~= "" then filled = filled + 1 end
    end
    local ic = PANEL.kids["chart_icon"]
    print(tag .. " filled=" .. filled
        .. " icon=" .. ((ic and ic.vis and ic.img) and 1 or 0)
        .. " title=" .. ((PANEL.kids["chart_title"] or {}).text ~= "" and 1 or 0))
end

EX.mode = EX.MODE_TRADE
EX.trade_page = 2
EX.layout()

local CRES = EX.instruments()[1]
EX.selected = CRES
-- EX.icon was stubbed to nil at the top of this file for the row scenes. The chart's icon
-- cell is exactly the thing under test here, so give it a path back - what is being checked
-- is that draw_chart SHOWS the cell for a chosen commodity and HIDES it for none, which is
-- the branch a stale picture would come from. paint_icon short-circuits before calling this
-- when nothing is chosen, so the nil case is still reached honestly.
EX.icon = function(r) return r and "ui/chart_test.png" or nil end
EX.shock, EX.shock_why = EX.shock or {}, EX.shock_why or {}

-- A FULL BUFFER: every tick has a bar under it, so all six labels carry text.
local full = {}
-- %% IS DOUBLED: this whole file is a Python format string (the dofile path is its one
-- substitution), so a lone %% here is a format directive and the harness never runs.
for i = 1, EX.DEEP_BARS do full[i] = 10 + (i %% 7) end
EX.deep = { [CRES] = full }
EX.draw_chart()
report_chart("chart_full")

-- FOUR TURNS IN: the bars are packed at the right, so the first and middle ticks have no bar
-- over them and must be blank rather than naming a turn from before the campaign began.
EX.deep = { [CRES] = { 12, 9, 14, 11 } }
EX.draw_chart()
report_chart("chart_short")

-- NOTHING CHOSEN. Every label blank, the icon down. This is the state the stale text shows up
-- in, and it is reached by a click, not by a page change - EX.layout never runs.
EX.selected = nil
EX.draw_chart()
report_chart("chart_none")

-- ---------------------------------------------------------------------- THE ORDER TICKET
-- Same page, same draw_chart(), seven more panel-level cells with the same stale-text fault
-- class as the axis labels just above. What makes this different is that FIVE of the seven
-- are BUTTONS with a hover state, and a blank that only reaches "standard" - skipping the
-- dual write EX.TWO_STATE_CELLS and set_text exist for - leaves "hover" still showing the
-- last commodity's numbers. c.text alone (a single scalar) cannot see that, which is why
-- comp() above now tracks c.states per state name.
local function ticket_all_texted(name)
    local c = PANEL.kids[name]
    if not c then return false end
    if EX.TWO_STATE_CELLS[name] then
        return (c.states.standard or "") ~= "" and (c.states.hover or "") ~= ""
    end
    return (c.text or "") ~= ""
end
local function ticket_any_texted(name)
    local c = PANEL.kids[name]
    if not c then return false end
    if EX.TWO_STATE_CELLS[name] then
        return (c.states.standard or "") ~= "" or (c.states.hover or "") ~= ""
    end
    return (c.text or "") ~= ""
end

-- CHOSEN: all seven must carry text in EVERY state a two-state cell has, not just the one
-- SetStateText happened to leave current - AND all seven must be VISIBLE. report()'s own
-- pstale cannot stand in for that second half: these seven are named by
-- EX.PANEL_LAYOUT_CHART whether or not anything is selected, so pstale (visible AND NOT
-- WANTED by this page) reads 0 whichever way clear_ticket()'s SetVisible(false) call goes -
-- it has nothing to say about a component this page legitimately owns.
EX.selected = CRES
EX.draw_chart()
local ticket_full, ticket_shown = 0, 0
for _, n in ipairs(EX.TICKET_CELLS) do
    if ticket_all_texted(n) then ticket_full = ticket_full + 1 end
    local c = PANEL.kids[n]
    if c and c.vis then ticket_shown = ticket_shown + 1 end
end

-- NOTHING CHOSEN: ANY state still carrying text counts against the blank pass - a cell
-- cleared in "standard" alone but still hover-lit from the last commodity is still telling
-- the player something - and now NONE may still be visible either. A component blanked but
-- left showing is seven empty buttons sitting under "No commodity chosen" inviting a click
-- that silently does nothing (the ticket_click guard eats it, but nothing on screen says so).
EX.selected = nil
EX.draw_chart()
local ticket_blank, ticket_shown_none = 0, 0
for _, n in ipairs(EX.TICKET_CELLS) do
    if ticket_any_texted(n) then ticket_blank = ticket_blank + 1 end
    local c = PANEL.kids[n]
    if c and c.vis then ticket_shown_none = ticket_shown_none + 1 end
end

-- report(), not report_chart(): the ticket scene is folded into check_layout's own `scenes`
-- tuple (it needs the clashes/stale/pstale triple every other page-2 scene gets), where
-- report_chart's shape has none of those fields.
report("ticket_p2", " text=" .. ticket_full .. " blank=" .. ticket_blank
    .. " shown=" .. ticket_shown .. " shown_none=" .. ticket_shown_none)

-- THE SAME TICKET ON THE LEDGER PAGE. It was drawn ONLY by EX.draw_chart and named ONLY by
-- EX.PANEL_LAYOUT_CHART until 2026-09-10, so with deep_history off there was no chart page,
-- no draw call and no ticket - on a page whose own empty-state line told the player to go
-- and set one under its chart. EX.draw_ticket is the extracted, top-level draw both pages
-- call; this drives it the way the ledger page does.
EX.selected = CRES
EX.trade_page = 3
EX.layout()
EX.draw_ticket(PANEL, CRES)
local t3_text, t3_shown = 0, 0
for _, n in ipairs(EX.TICKET_CELLS) do
    if ticket_all_texted(n) then t3_text = t3_text + 1 end
    local c = PANEL.kids[n]
    if c and c.vis then t3_shown = t3_shown + 1 end
end
print("ticket_p3 text=" .. t3_text .. " shown=" .. t3_shown)

-- AND WITH THE SWITCH OFF IT IS NOT ON SCREEN AT ALL. The chart page answers to deep_history,
-- not to the orders switch, so with orders off the ticket used to sit there fully drawn and
-- fully live while the ledger page holding the only Cancel button no longer existed. The
-- model refuses the placement (EX.place_order_check), but a Place button that looks live and
-- silently refuses forever is the complaint, not the fix.
local real_feature = EX.feature
EX.feature = function(k) if k == "orders" then return false end return real_feature(k) end
EX.draw_ticket(PANEL, CRES)
local t_off_shown, t_off_text = 0, 0
for _, n in ipairs(EX.TICKET_CELLS) do
    if ticket_any_texted(n) then t_off_text = t_off_text + 1 end
    local c = PANEL.kids[n]
    if c and c.vis then t_off_shown = t_off_shown + 1 end
end
print("ticket_off shown=" .. t_off_shown .. " text=" .. t_off_text)
EX.feature = real_feature
EX.trade_page = 1

-- EX.IN_LAYOUT HAS TO BE ABLE TO SAY NO ------------------------------------------------------
-- It is the guard that stops EX.refresh_panel writing - and therefore SHOWING, because
-- set_text calls SetVisible(true) - a cell the current view does not own. A guard that always
-- answers true is the same bug with a check in front of it, and the static check that reads
-- the guard out of the source text cannot tell the two apart. Reported live 2026-09-11: the
-- amount button drawn across the Ownership view's Cartel premium header.
EX.mode = EX.MODE_TRADE
EX.trade_page = 1
local il_trade = tostring(EX.in_layout("btn_amount"))
EX.mode = EX.MODE_STATS
local il_stats = tostring(EX.in_layout("btn_amount"))
EX.mode = EX.MODE_TRADE
local il_never = tostring(EX.in_layout("btn_nonesuch"))
print("inlayout trade=" .. il_trade .. " stats=" .. il_stats .. " never=" .. il_never)

-- ONE ROW OF THE DEALS PAGE, DRAWN FOR REAL --------------------------------------------------
-- EX.deal_cells decides every string on this row and is asserted commodity by commodity in the
-- books harness. What NOTHING could see until this section existed is whether the draw writes
-- what it decided: two mutants - SetDisabled(false), and a button label hardcoded over the one
-- EX.deal_cells returned - survived a full round on 2026-09-16 with these lines inside
-- EX.refresh_panel, which no harness can run. EX.draw_deal_row is now a top-level function for
-- the same reason EX.draw_chart and EX.draw_intro are, and this drives it.
EX.mode = EX.MODE_DEALS
EX.snap = { ai_deals = true }
EX.current["res_rom_iron"] = EX.neutral_rung()
EX.deals = {
    -- The counterparty SELLS, so the player BUYS - the one side a refusal may reach.
    { fac = "house_a", res = "res_rom_iron", side = "sell", lots = 3, px = 940,  turn = 10 },
    -- The counterparty BUYS, so the player SELLS. Selling stays open with the market shut.
    { fac = "house_b", res = "res_rom_iron", side = "buy",  lots = 1, px = 1060, turn = 10 },
}
local DR1 = comp("deal_row_1", HOLDER)
local DR2 = comp("deal_row_2", HOLDER)
local DR3 = comp("deal_row_3", HOLDER)
for _, r in ipairs({ DR1, DR2, DR3 }) do
    for _, cell in ipairs({ "icon", "row_name", "row_trend", "row_price", "row_sell",
                            "row_hold", "btn_buy" }) do
        comp(cell, r)
    end
end
-- STALE TEXT IN EVERY CELL FIRST. A row the draw never touches is not blank - it is a fixed
-- pool row still carrying the last page, which is the fault the SetVisible(false) below is for.
for _, r in ipairs({ DR1, DR2, DR3 }) do
    for _, cell in ipairs({ "row_name", "row_trend", "btn_buy" }) do
        find_uicomponent(r, cell):SetStateText("STALE")
    end
end

local real_refusal = EX.buy_refusal
EX.buy_refusal = function() return "the market is shut", "Closed" end
EX.draw_deal_row(DR1, 1)
EX.draw_deal_row(DR2, 2)
EX.buy_refusal = real_refusal
EX.draw_deal_row(DR3, 3)

local function cell(r, n) return find_uicomponent(r, n).text end
local function btn(r) return find_uicomponent(r, "btn_buy") end
print("deal_draw name=" .. cell(DR1, "row_name")
    .. " buyside=" .. cell(DR1, "btn_buy") .. "/" .. tostring(btn(DR1).disabled)
    .. " sellside=" .. cell(DR2, "btn_buy") .. "/" .. tostring(btn(DR2).disabled)
    -- BOTH STATES. btn_buy is in EX.TWO_STATE_CELLS, so a label written to "standard" alone
    -- leaves hover holding the previous view's word - shown to the one player already pointing
    -- at it. This is the order ticket's blanking bug, on a button that spends gold.
    .. " hover=" .. tostring(btn(DR1).states.hover)
    .. " icon=" .. tostring(find_uicomponent(DR1, "icon").img ~= nil)
    -- PAST THE END: hidden, and its stale text is irrelevant because nothing draws it.
    .. " pastend=" .. tostring(DR3.vis) .. "/" .. cell(DR3, "row_name"))
EX.mode = EX.MODE_TRADE
