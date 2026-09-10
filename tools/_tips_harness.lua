-- THE COLUMN TOOLTIPS, ACROSS A VIEW SWITCH. The panel has one set of row components and five
-- views borrow them, so what this measures is not "does a tooltip get set" - EX.apply_tips has
-- always done that - but what happens to a cell in a view that has nothing to say about it.
--
-- The answer used to be "it keeps the last view's". EX.TIPS has no entry for the Log or the
-- guide, EX.apply_tips returned early on a nil tips table, and the Log's "What happened" column
-- therefore answered with whatever had last been written onto row_trend: from the Houses view,
-- "^ up, v down, - held. Hi/Lo: at the ladder's limit." over the line "Delisted. The house is
-- gone." Nothing errors, nothing logs, and it is invisible in any screenshot taken with the
-- pointer off the row.
--
-- EX.layout and EX.refresh_panel both reach a live panel; apply_tips does not, so it is the one
-- of the three run for real here.
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    get_saved_value = function() return nil end,
    callback = function() end,
    model = function() return { turn_number = function() return 1 end } end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])

-- A FAKE PANEL. Cells record what was written to them rather than drawing it; the two things
-- worth recording are the text and whether the cell still takes hover, because a cleared
-- tooltip on a still-interactive cell is a mouse trap over an empty box.
local function cell(name)
    local c = { name = name, tip = "(never set)", interactive = "(never set)" }
    c.SetTooltipText = function(_, t) c.tip = t end
    c.SetInteractive = function(_, b) c.interactive = b end
    return c
end

local CELLS = { "row_name", "row_price", "row_sell", "row_supply", "row_trend", "spark",
                "row_hold" }
local HDRS = { "hdr_name", "hdr_price", "hdr_sell", "hdr_supply", "hdr_trend", "hdr_spark",
               "hdr_hold" }

local function node(name)
    local n = { name = name, kids = {} }
    n.SetTooltipText = function() end
    n.SetInteractive = function() end
    return n
end

local PANEL = node("panel")
for _, h in ipairs(HDRS) do PANEL.kids[h] = cell(h) end

-- One row per instrument the two lists can produce, plus the fake houses below. EX.row builds
-- the name as EX.ROW .. "_" .. EX.short(res), so it is built the same way here rather than
-- spelled out - a change to EX.short would otherwise make this harness silently test nothing.
local function add_row(res)
    local r = node(EX.ROW .. "_" .. EX.short(res))
    for _, c in ipairs(CELLS) do r.kids[c] = cell(c) end
    PANEL.kids[r.name] = r
    return r
end

EX.houses = { "wh3_dlc23_chd_zharr_naggrund", "wh3_dlc23_chd_dawi_zharr" }
for _, res in ipairs(EX.COMMODITIES) do add_row(res) end
for _, res in ipairs(EX.LAYER2) do add_row(res) end
for _, res in ipairs(EX.houses) do add_row(res) end

function find_uicomponent(parent, name)
    if not parent or not parent.kids then return false end
    return parent.kids[name] or false
end
function is_uicomponent(c) return c ~= nil and c ~= false end
function UIComponent(c) return c end

local FIRST = EX.ROW .. "_" .. EX.short(EX.COMMODITIES[1])
local HOUSE = EX.ROW .. "_" .. EX.short(EX.houses[1])

local function look(row, c)
    local x = PANEL.kids[row].kids[c]
    return x.tip, x.interactive
end

local function report(key, row, c)
    local tip, inter = look(row, c)
    print(key .. " [" .. tostring(tip) .. "]")
    print(key .. "_interactive " .. tostring(inter))
end

-- TRADE, the baseline. Every column this view names must answer, on the row as well as the
-- header - the whole point of the feature is that the player hovers whichever is nearer.
EX.mode = "trade"
EX.apply_tips(PANEL, PANEL)
report("trade_trend", FIRST, "row_trend")
print("trade_hdr_trend [" .. tostring(PANEL.kids.hdr_trend.tip) .. "]")
-- A ROW THIS VIEW DOES NOT DRAW MUST BE UNWRITTEN, not merely skipped: the house rows are
-- hidden here, and a hidden row that keeps a tooltip is one view switch away from showing it.
report("trade_house_trend", HOUSE, "row_trend")

-- LOG, straight after it. EX.TIPS has no log entry, so every cell must come back empty AND
-- non-interactive. row_price is checked too: the Log draws two columns, so the other five are
-- the ones most likely to be left carrying stale text nobody thought to look at.
EX.mode = EX.MODE_LOG
EX.apply_tips(PANEL, PANEL)
report("log_trend", FIRST, "row_trend")
report("log_price", FIRST, "row_price")
print("log_hdr_trend [" .. tostring(PANEL.kids.hdr_trend.tip) .. "]")

-- HOUSES then LOG, which is the exact path that shipped - the Houses view is where the trend
-- legend the player saw over "Delisted. The house is gone." comes from.
EX.mode = EX.MODE_HOUSES
EX.apply_tips(PANEL, PANEL)
report("houses_trend", HOUSE, "row_trend")
EX.mode = EX.MODE_LOG
EX.apply_tips(PANEL, PANEL)
report("houses_then_log_trend", HOUSE, "row_trend")

-- AND BACK AGAIN. A clear that cannot be undone is the same bug facing the other way: the
-- player who visits the Log once and returns to Trade would find the column silent for the
-- rest of the session.
EX.mode = "trade"
EX.apply_tips(PANEL, PANEL)
report("back_to_trade_trend", FIRST, "row_trend")
