-- WHAT COLUMN SORTING ACTUALLY DOES TO THE ROW ORDER, run against the shipped EX.sorted,
-- EX.sort_click and EX.mode_instruments rather than read out of the file.
--
-- NOT A LIVE PANEL. EX.layout and EX.refresh_panel are stubbed; nothing here draws. What is
-- measured is the ORDER the panel would be handed, which is the whole of the feature.
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
core = { add_listener = function() end }
function out() end
dofile([[%s]])
EX.store = SAVED
EX.layout = function() end
EX.refresh_panel = function() end

-- A KNOWN BOARD. Four commodities with deliberate TIES in every column, because ties are what
-- an unstable table.sort scrambles and they are the reason EX.sorted carries a tiebreak.
EX.COMMODITIES = { "a", "b", "c", "d" }
EX.LAYER2 = {}
EX.current = { a = 5, b = 2, c = 5, d = 1 }
EX.supply  = { a = 30, b = 10, c = 20, d = 10 }
local HELD = { a = 0, b = 7, c = 7, d = 3 }
EX.buy_price  = function(r) return ({ a = 300, b = 100, c = 200, d = 100 })[r] end
EX.sell_price = function(r) return ({ a = 250, b = 90,  c = 180, d = 80  })[r] end
EX.held       = function(r) return HELD[r] or 0 end
EX.is_house   = function(r) return false end
EX.is_layer2  = function() return false end

local function order()
    local t = EX.mode_instruments()
    local s = {}
    for i, r in ipairs(t) do s[i] = r end
    return table.concat(s, ",")
end

EX.mode = EX.MODE_TRADE
print("default " .. order())

-- THE CYCLE THE PLAYER CLICKS: low to high, high to low, back to the list's own order.
EX.sort_click("hdr_price")
print("price_asc " .. order() .. " mark=" .. EX.sort_mark("hdr_price", "Buy"))
EX.sort_click("hdr_price")
print("price_desc " .. order() .. " mark=" .. EX.sort_mark("hdr_price", "Buy"))
EX.sort_click("hdr_price")
print("price_default " .. order() .. " col=" .. tostring(EX.sort_col))

-- TIES KEEP THE LIST ORDER, AND KEEP IT ACROSS REPEATED READS. refresh_panel runs about once
-- a second while the panel is open; an unstable comparator reshuffles b and d on every one of
-- them and the panel reads as broken rather than sorted.
EX.sort_click("hdr_price")
local first = order()
local stable = true
for _ = 1, 20 do if order() ~= first then stable = false end end
print("tie_order " .. first .. " stable=" .. tostring(stable))

-- EVERY SORTABLE COLUMN IN EVERY VIEW, ascending, so a column wired to the wrong accessor
-- shows up as the wrong order rather than as nothing at all.
for _, mode in ipairs({ "trade", "stats", "offer" }) do
    EX.mode = mode
    local cols = {}
    for hid in pairs(EX.SORT_VALUE[mode] or {}) do cols[#cols + 1] = hid end
    table.sort(cols)
    for _, hid in ipairs(cols) do
        EX.sort_col, EX.sort_dir = hid, 1
        print("col_" .. mode .. "_" .. hid .. " " .. order())
    end
    EX.sort_col = nil
end

-- THE TREND COLUMN, AGAINST THE GLYPHS IT ACTUALLY DRAWS.
--
-- It used to sort on EX.current - the price rung - which is a DIFFERENT quantity from the one
-- the column shows: trend_arrow compares the rung with the PREVIOUS rung. Two rows on the
-- same rung can draw opposite arrows. Sorting by rung gave Hi, Hi, ^ x5, -, v x3, ^, ^, v, v,
-- ^, v on screen (2026-09-08). So this reads the ARROWS back, not the numbers.
EX.mode = EX.MODE_TRADE
EX.COMMODITIES = { "cap", "up2", "up1", "flat", "dn1", "dn2", "floor" }
EX.current   = { cap = EX.RUNGS, up2 = 20, up1 = 20, flat = 20, dn1 = 20, dn2 = 20, floor = 1 }
local PREV   = { cap = EX.RUNGS, up2 = 18, up1 = 19, flat = 20, dn1 = 21, dn2 = 23, floor = 1 }
EX.prev_rung = function(r) return PREV[r] end
EX.sort_col, EX.sort_dir = "hdr_trend", -1
local glyphs = {}
for _, r in ipairs(EX.mode_instruments()) do glyphs[#glyphs + 1] = EX.trend_arrow(r) end
print("trend_desc " .. order())
print("trend_glyphs " .. table.concat(glyphs, ","))
EX.sort_dir = 1
print("trend_asc " .. order())
EX.sort_col = nil
EX.COMMODITIES = { "a", "b", "c", "d" }
EX.current = { a = 5, b = 2, c = 5, d = 1 }
EX.prev_rung = function() return nil end

-- A COLUMN WITH NOTHING TO ORDER BY DOES NOT RESPOND. hdr_name is a word and hdr_spark is a
-- chart; a header that swallows a click and does nothing is the live-looking dead control
-- this file condemns elsewhere.
EX.mode = EX.MODE_TRADE
print("name_click " .. tostring(EX.sort_click("hdr_name"))
    .. " spark_click " .. tostring(EX.sort_click("hdr_spark"))
    .. " junk_click " .. tostring(EX.sort_click("btn_buy"))
    .. " nil_click " .. tostring(EX.sort_click(nil))
    .. " col=" .. tostring(EX.sort_col))

-- AN ERRORING ACCESSOR MUST NOT TAKE THE REFRESH DOWN. EX.held is reached for the Held column
-- and reads a live pooled resource; a null interface there threw for a whole build.
EX.held = function(r) if r == "c" then error("boom") end return HELD[r] or 0 end
EX.sort_col, EX.sort_dir = "hdr_hold", 1
local ok, res = pcall(order)
print("erroring_accessor ok=" .. tostring(ok) .. " " .. tostring(res))
EX.held = function(r) return HELD[r] or 0 end

-- THE SORT IS CLEARED BY A VIEW CHANGE. A column id means a different number in each view.
EX.sort_col, EX.sort_dir = "hdr_price", -1
EX.tab_locked = function() return nil end
EX.set_mode(EX.MODE_STATS)
print("after_set_mode col=" .. tostring(EX.sort_col) .. " dir=" .. EX.sort_dir)

-- HOUSES ARE SORTED BEFORE THEY ARE PAGED. Sorting the page instead of the list orders the
-- twenty rows the player is looking at and leaves every other page alone.
EX.mode = EX.MODE_HOUSES
EX.MAX_ROWS = 2
EX.houses = { "h1", "h2", "h3", "h4", "h5" }
EX.is_house = function(r) return true end
EX.buy_price = function(r) return ({ h1 = 50, h2 = 40, h3 = 30, h4 = 20, h5 = 10 })[r] end
EX.dividend = function(r) return ({ h1 = 1, h2 = 2, h3 = 3, h4 = 4, h5 = 5 })[r] end
EX.sort_col, EX.sort_dir = nil, 1
EX.house_page = 1
print("houses_default_p1 " .. order())
EX.sort_click("hdr_price")
print("houses_asc_p1 " .. order() .. " page=" .. EX.house_page)
EX.house_page = 2
print("houses_asc_p2 " .. order())
EX.house_page = 3
print("houses_asc_p3 " .. order())

-- AND SORTING SENDS THE PLAYER BACK TO PAGE 1. Re-sorting under someone sitting on page 3
-- leaves them looking at the middle of the new order, which is its least meaningful part.
EX.house_page = 3
EX.sort_click("hdr_sell")
print("resort_page " .. EX.house_page .. " " .. order())

-- THE DEFAULT PATH ALLOCATES NOTHING: EX.sorted hands back the very table it was given.
EX.sort_col = nil
print("identity " .. tostring(EX.sorted(EX.houses) == EX.houses))

-- ===========================================================================================
-- OWN PEOPLE FIRST, THE NAME COLUMN, AND THE POWER CAP. Added 2026-09-11 with trade blocs.
-- ===========================================================================================
--
-- All three live in EX.listed_houses, which EX.house_pages and EX.house_slice BOTH read. The
-- grouping has to survive every column: it is a primary key, not a default order.
EX.MAX_ROWS = 20
EX.house_page = 1
EX.sort_col, EX.sort_dir = nil, 1
EX.HOUSE_CULTURE = "mine"
EX.houses = { "a_far", "b_own", "c_far", "d_own" }
EX.culture_of = function(k) return string.find(k, "own") and "mine" or "far" end
-- Names deliberately out of key order, so a name sort cannot be mistaken for the key sort.
EX.faction_display = function(k) return ({ a_far = "Zulu", b_own = "Yankee",
                                           c_far = "Alpha", d_own = "Bravo" })[k] end
EX.buy_price = function(k) return ({ a_far = 10, b_own = 20, c_far = 30, d_own = 40 })[k] end
EX.held = function() return 0 end
EX.house_regions = {}

local function listed() return table.concat(EX.listed_houses(), ",") end

print("grp_default " .. listed())
EX.sort_col, EX.sort_dir = "hdr_name", 1
print("grp_name_asc " .. listed())
EX.sort_dir = -1
print("grp_name_desc " .. listed())
EX.sort_col, EX.sort_dir = "hdr_price", 1
print("grp_price_asc " .. listed())

-- THE CAP, on a board where the foreign tail is longer than it. Own-culture rows never count
-- against it and held rows are exempt from it.
EX.sort_col, EX.sort_dir = nil, 1
EX.HOUSE_LIST_MAX = 2
EX.houses = { "b_own", "f1", "f2", "f3", "f4" }
EX.house_regions = { f1 = 1, f2 = 9, f3 = 5, f4 = 7 }
print("cap_power " .. listed())
EX.held = function(k) return k == "f1" and 5 or 0 end
print("cap_held " .. listed())
-- AND THE PAGE COUNT FOLLOWS THE CAPPED LIST. If it read #EX.houses the counter would promise
-- a page the slice returns empty.
EX.MAX_ROWS = 2
print("cap_pages " .. EX.house_pages())
