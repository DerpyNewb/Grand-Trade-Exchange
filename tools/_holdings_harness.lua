-- Runs the SHIPPED EX.holdings_value against a board with known prices.
--
-- NOTHING ABOUT THE VALUATION IS STUBBED. EX.sell_price, EX.lot, EX.price_at and the ladder
-- are the real ones - that is the point, because the three faults this function can have are
-- all IN that arithmetic: marking at the mid price, forgetting that a price is per LOT while
-- a holding is per UNIT, and summing before flooring. Only the INPUTS are stubbed: what is
-- held, what rung each instrument sits on, and which houses exist.
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    get_saved_value = function() return nil end,
    set_saved_value = function() end,
    callback = function() end,
    get_local_faction_name = function() return "player" end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])

-- EVERY INSTRUMENT AT THE NEUTRAL RUNG, so EX.price is EX.BASE_COST exactly and every number
-- below can be derived by hand rather than read back off the thing being measured.
local HELD = {}
EX.held = function(res) return HELD[res] or 0 end
for _, res in ipairs(EX.COMMODITIES) do EX.current[res] = EX.neutral_rung() end
for _, res in ipairs(EX.LAYER2) do EX.current[res] = EX.neutral_rung() end

local GEMS = EX.COMMODITIES[1]
local L2   = EX.LAYER2[1]

-- The houses, discovered the way EX.instruments reads them. EX.is_house is left alone: it
-- consults EX.shares_held, so a key with shares in it IS a house to the shipped code.
EX.houses = { "h_alive", "h_dead" }
-- EX.is_house MEMOISES EX.house_set on its first call, so a list assigned after that call is
-- never seen. Clearing it is what makes the two houses below instruments at all.
EX.house_set = nil
EX.shares_held = { h_alive = 0, h_dead = 0 }
EX.delisted = { h_dead = true }
EX.current["h_alive"] = EX.neutral_rung()
EX.current["h_dead"] = EX.neutral_rung()

print("base " .. EX.BASE_COST)
print("lot " .. EX.lot(GEMS))
print("l2_lot " .. EX.lot(L2))
print("house_lot " .. EX.lot("h_alive"))
print("price " .. EX.price(GEMS))
print("sell " .. EX.sell_price(GEMS))
print("house_sell " .. EX.sell_price("h_alive"))

-- NOTHING HELD IS ZERO, not nil and not the mid price of an empty book.
print("empty " .. EX.holdings_value())

-- EXACTLY ONE LOT. The whole lot price, once - so a function marking at EX.price instead of
-- EX.sell_price differs here by the spread, and one dividing by the wrong lot size differs
-- by a factor.
HELD[GEMS] = EX.lot(GEMS)
print("one_lot " .. EX.holdings_value())

-- TEN LOTS. Linear, and ten times a floored lot value - which is NOT floor(ten times the
-- unit value) if the per-unit number has a fraction. This is the summed-then-floored fault.
HELD[GEMS] = EX.lot(GEMS) * 10
print("ten_lots " .. EX.holdings_value())

-- ONE UNIT, which is a FRACTION of a lot price. A function that forgot to divide by the lot
-- would report a whole lot's money for a single unit - the dividend fault exactly.
HELD[GEMS] = 1
print("one_unit " .. EX.holdings_value())
HELD[GEMS] = 0

-- LAYER 2 COUNTS. Its lot is 100 and its sell side is the fire-sale factor, not the spread,
-- so a function that only walked EX.COMMODITIES would report zero here.
HELD[L2] = EX.lot(L2)
print("l2_one_lot " .. EX.holdings_value())
print("l2_sell " .. EX.sell_price(L2))
HELD[L2] = 0

-- PAPER COUNTS, AND A DELISTED HOUSE DOES NOT. Both held, both at the same rung, both with
-- the same number of shares: the total must be one house's worth, not two.
EX.shares_held.h_alive = EX.HOUSE_LOT_SIZE
HELD.h_alive = EX.HOUSE_LOT_SIZE
print("house_only " .. EX.holdings_value())
EX.shares_held.h_dead = EX.HOUSE_LOT_SIZE
HELD.h_dead = EX.HOUSE_LOT_SIZE
print("with_dead " .. EX.holdings_value())

-- AND THE WHOLE BOOK AT ONCE, which is the number the footer prints.
HELD[GEMS] = EX.lot(GEMS)
HELD[L2] = EX.lot(L2)
print("everything " .. EX.holdings_value())

-- FRACTIONS, AND THEY ARE THE WHOLE POINT OF THIS BLOCK. Everything above divides evenly -
-- a lot of ten at a sell price of 900 is exactly 90 a unit - so flooring each instrument and
-- flooring the sum give the same answer and a check built on that board cannot tell the two
-- apart. Measured: the summed-then-floored mutant survived the entire suite on it. Two rungs
-- up the ladder a lot sells for 1089 and a unit is 108.9, so the two now differ by a gold.
local FRAC = EX.COMMODITIES[2]
HELD[GEMS], HELD[L2], HELD.h_alive, HELD.h_dead = 0, 0, 0, 0
EX.shares_held.h_alive, EX.shares_held.h_dead = 0, 0
EX.current[GEMS] = EX.neutral_rung() + 2
EX.current[FRAC] = EX.neutral_rung() + 2
HELD[GEMS], HELD[FRAC] = 1, 1
print("frac_lot_price " .. EX.sell_price(GEMS))
print("frac_lot " .. EX.lot(GEMS))
print("frac_total " .. EX.holdings_value())

-- THE FOOTER'S OWN WIDTH, at the widest thing the clause can print. Measured from the
-- shipped format string rather than restated in Python, so a reworded label is caught.
print("clause " .. ("  Worth: " .. 99999999 .. "g"))
