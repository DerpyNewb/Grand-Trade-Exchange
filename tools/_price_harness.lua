-- Runs the SHIPPED price-cell code. EX.hostility and EX.price are stubbed so the measurement
-- is what the CELL says about a known markup, not how hostility is computed - check_lua_books
-- owns that.
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    get_saved_value = function() return nil end,
    callback = function() end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])

-- 1007, NOT 1000. A round base gives a round price, and a cell that quietly rounded the
-- number to the nearest ten would draw the same string - measured by mutation, that
-- mutant survived the whole suite on a base of 1000.
local H, PRICE = 0, 1007
local REAL_PRICE = EX.price       -- kept: the ladder measurement at the bottom needs it back
EX.hostility = function() return H end
EX.price = function() return PRICE end

print("spread " .. EX.SPREAD)
print("sell_floor " .. EX.SELL_FLOOR)
print("hostile_max " .. EX.HOSTILE_MAX)

-- NO HOSTILITY: a bare number, no markup and no colour tags to explain.
H = 0
print("calm_buy " .. EX.price_cell("res_gems", true))
print("calm_sell " .. EX.price_cell("res_gems", false))

-- THE NUMBER IS STILL buy_price / sell_price. The cell must not round or re-derive.
H = 0.14
print("buy_num " .. tostring(EX.buy_price("res_gems")))
print("sell_num " .. tostring(EX.sell_price("res_gems")))
print("buy_cell " .. EX.price_cell("res_gems", true))
print("sell_cell " .. EX.price_cell("res_gems", false))
print("buy_pct " .. EX.markup_pct("res_gems", true))
print("sell_pct " .. EX.markup_pct("res_gems", false))

-- AT THE CEILING. HOSTILE_MAX bounds the figure to two digits, which is what keeps the cell
-- inside its 74px column.
H = EX.HOSTILE_MAX
print("max_pct " .. EX.markup_pct("res_gems", true))
print("max_cell " .. EX.price_cell("res_gems", true))

-- THE SELL CLAMP. sell_price stops at EX.SELL_FLOOR, so past that point the raw hostility is
-- no longer what came off the price - printing it would claim a haircut the floor refused.
H = 0.9
print("clamped_price " .. tostring(EX.sell_price("res_gems")))
print("clamped_pct " .. EX.markup_pct("res_gems", false))
print("clamped_raw " .. math.floor(H * 100 + 0.5))

-- THE WIDEST THING THIS CELL CAN DRAW, with the colour markup stripped: the biggest price on
-- the ladder at the biggest markup. Printed as a length so the check can measure it against
-- the column rather than eyeball it.
--
-- ASSEMBLED FROM THE PARTS RATHER THAN STRIPPED WITH gsub. A Lua pattern would need percent
-- escapes for the brackets, and this file is read through a Python percent-format - so a
-- percent sign anywhere in it, comments included, breaks the substitution. Three earlier
-- harnesses in this suite each cost a correction for exactly that, and so did this comment.
-- AND THE PRICE IS THE LADDER'S REAL TOP, not a round number picked to look large: the top
-- rung of the real ladder against the real base is the dearest thing this cell can ever be
-- asked to draw, and a made-up 999999 would condemn a layout that is actually fine.
H = EX.HOSTILE_MAX
EX.price = REAL_PRICE
local top = 0
for _, res in ipairs(EX.COMMODITIES) do
    EX.current[res] = EX.RUNGS
    local v = EX.price(res)
    if v > top then top = v end
end
print("ladder_top " .. top)
EX.price = function() return top end
print("widest " .. EX.price_cell("res_gems", true))
print("widest_len " .. (#tostring(EX.buy_price("res_gems"))
                        + 1 + #tostring(EX.markup_pct("res_gems", true)) + 1))
