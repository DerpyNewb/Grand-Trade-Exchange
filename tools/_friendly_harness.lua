-- THE FRIENDLY DISCOUNT, RUN. Whether a liked guild actually cuts the price, whether the cut
-- is bounded by the spread that has to absorb it, and - the one that matters - whether a round
-- trip can still print gold with the discount at its maximum.
--
-- NOT A LIVE PANEL. Nothing draws. What is measured is EX.hostility, EX.buy_price,
-- EX.sell_price and the three sentences that report them.
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

local OPT = {}
EX.opt = function(k) return OPT[k] end
local STANCE = {}
EX.guild = function() return { "h1", "h2" } end
EX.book_of = function(house, _res) return STANCE[house] and 50 or 0 end
EX.guild_book = function() return 100 end
EX.stance_of = function(house) return STANCE[house] or 0 end
EX.is_house = function() return false end
EX.is_layer2 = function() return false end
EX.faction_display = function(f) return f end
EX.guild_counterparty = function() return "h1" end
EX.market_closed = function() return nil end
EX.refused_by = function() return nil end

local function setopts(spread, step, fmax, hmax)
    OPT.spread, OPT.friendly_max, OPT.hostile_max = spread, fmax, hmax
    OPT.sell_floor = 0.25
    -- BOTH of them. EX.price_at reads the option; EX.friendly_cap reads the constant. They
    -- are the same number and the harness has to keep them so, or the round trip below is
    -- measured on one ladder and bounded by another.
    OPT.ladder_step = step
    EX.LADDER_STEP = step
end

-- DEFAULTS FIRST. spread 0.10, step 1.10 -> the headroom is exactly one percent, so a 0.25
-- slider must come back as 0.01 and not as 0.25.
setopts(0.10, 1.10, 0.25, 0.25)
STANCE = { h1 = 1.0, h2 = 1.0 }
print("cap_default " .. string.format("%%.4f", EX.friendly_cap()))
print("friendly_default " .. string.format("%%.4f", EX.hostility("res_gems")))
STANCE = { h1 = -1.0, h2 = -1.0 }
print("hostile_default " .. string.format("%%.4f", EX.hostility("res_gems")))
STANCE = {}
print("neutral_default " .. string.format("%%.4f", EX.hostility("res_gems")))

-- A WIDER SPREAD AFFORDS A REAL DISCOUNT. 0.20 -> 1 - 1.10*0.80 = 0.12, under the 0.25 slider.
setopts(0.20, 1.10, 0.25, 0.25)
STANCE = { h1 = 1.0, h2 = 1.0 }
print("cap_wide " .. string.format("%%.4f", EX.friendly_cap()))
print("friendly_wide " .. string.format("%%.4f", EX.hostility("res_gems")))

-- AND A SLIDER BELOW THE HEADROOM IS THE ONE THAT WINS. 0.05 into 0.12 of room.
setopts(0.20, 1.10, 0.05, 0.25)
print("friendly_small " .. string.format("%%.4f", EX.hostility("res_gems")))

-- NO HEADROOM AT ALL: the cap floors at zero rather than going negative and turning the
-- discount into a surcharge.
setopts(0.02, 1.10, 0.25, 0.25)
print("cap_none " .. string.format("%%.4f", EX.friendly_cap()))
print("friendly_none " .. string.format("%%.4f", EX.hostility("res_gems")))

-- HALF THE BOOK FRIENDLY, HALF NEUTRAL - the discount is book-weighted like the markup.
-- The slider is small on purpose: at 0.25 the spread's cap binds first and would hide the
-- weighting entirely (0.5 * 0.25 = 0.125, clamped to 0.12, which is the unweighted answer).
setopts(0.20, 1.10, 0.05, 0.25)
STANCE = { h1 = 1.0 }
print("friendly_half " .. string.format("%%.4f", EX.hostility("res_gems")))

-- ================= THE ROUND TRIP, WHICH IS THE WHOLE POINT ==========================
-- Buy at a rung, sell ONE RUNG UP - the move your own buying pressure can open - at the
-- maximum discount the settings allow. If that ever pays, the market prints gold.
setopts(0.20, 1.10, 0.25, 0.25)
STANCE = { h1 = 1.0, h2 = 1.0 }
local worst, worst_rung = -1e9, 0
for r = 1, EX.RUNGS - 1 do
    EX.current = { res_gems = r }
    local buy = EX.buy_price("res_gems")
    EX.current = { res_gems = r + 1 }
    local sell = EX.sell_price("res_gems")
    if sell - buy > worst then worst, worst_rung = sell - buy, r end
end
print("roundtrip_worst " .. worst .. " at rung " .. worst_rung)

-- ...and at the DEFAULT spread, where the headroom is thinnest.
setopts(0.10, 1.10, 0.25, 0.25)
local worst2 = -1e9
for r = 1, EX.RUNGS - 1 do
    EX.current = { res_gems = r }
    local buy = EX.buy_price("res_gems")
    EX.current = { res_gems = r + 1 }
    local sell = EX.sell_price("res_gems")
    if sell - buy > worst2 then worst2 = sell - buy end
end
print("roundtrip_default " .. worst2)

-- SAME RUNG, which is the free-money case that needs no price movement at all.
setopts(0.20, 1.10, 0.25, 0.25)
EX.current = { res_gems = 20 }
print("same_rung " .. (EX.sell_price("res_gems") - EX.buy_price("res_gems")))

-- ============== WHAT THE PLAYER IS TOLD ==============================================
EX.TIPS = EX.TIPS or {}
EX.current = { res_gems = 20 }
STANCE = { h1 = 1.0, h2 = 1.0 }
print("pct_buy " .. EX.markup_pct("res_gems", true))
print("pct_sell " .. EX.markup_pct("res_gems", false))
print("cell_buy " .. EX.price_cell("res_gems", true))
print("cell_sell " .. EX.price_cell("res_gems", false))
print("tip_buy " .. EX.buy_tip("res_gems"))
print("tip_sell " .. EX.sell_tip("res_gems"))
STANCE = { h1 = -1.0, h2 = -1.0 }
print("cell_buy_hostile " .. EX.price_cell("res_gems", true))
print("tip_buy_hostile " .. EX.buy_tip("res_gems"))
STANCE = {}
print("cell_buy_neutral " .. EX.price_cell("res_gems", true))

-- THE CELL AND THE TOOLTIP MUST SAY THE SAME NUMBER. Reported from a screenshot 2026-09-08:
-- the sell cell read -11%% and its tooltip read 10%%, on the same row, for the same trade.
-- Both were defensible, which is exactly why they disagreed - the RAW hostility is 10%%, but
-- what the sell price loses is measured against the sell base (1 - spread), so 0.10/0.90 is
-- 11.1%%. This reproduces those settings precisely.
setopts(0.10, 1.10, 0.25, 0.10)
STANCE = { h1 = -1.0, h2 = -1.0 }
print("shot_h " .. string.format("%%.4f", EX.hostility("res_gems")))
print("shot_cell " .. EX.price_cell("res_gems", false))
print("shot_tip " .. EX.sell_tip("res_gems"))
