-- The order model: validation, packing, the cap, and which side of the rung each of the four
-- side/comparison combinations fires on.
--
-- EX.setp is stubbed to a table rather than left alone: EX.place_order saves on every
-- successful placement, and EX.store does not exist until EX.init runs.
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    get_saved_value = function() return nil end,
    get_local_faction_name = function() return "player" end,
    callback = function() end,
    model = function() return { turn_number = function() return 1 end } end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])

EX.store = {}
EX.saved = nil
EX.setp = function(_k, v) EX.saved = v end
EX.getp = function() return EX.saved end

-- VALIDATION ------------------------------------------------------------------------------
local bad = {
    { "", "b", "le", 10 }, { "res_gems", "x", "le", 10 },
    { "res_gems", "b", "eq", 10 }, { "res_gems", "b", "le", 0 },
    { "res_gems", "b", "le", EX.RUNGS + 1 }, { "res_gems", "b", "le", 10.5 },
    { "res_gems", "b", "le", nil },
    -- A NIL INSTRUMENT, NOT JUST AN EMPTY STRING. EX.ticket_click reads EX.selected and is
    -- meant to guard it before ever reaching here - but the guard is UI plumbing, and the
    -- ticket's Place button and EX.MP_OPS.ord both route through EX.place_order_check, so
    -- this is the guard that actually matters: a caller bug that lets a nil res through must
    -- still be refused here rather than indexing into EX.orders/EX.current with a nil key.
    { nil, "b", "le", 10 },
}
local nbad = 0
for _, a in ipairs(bad) do
    if not EX.valid_order(a[1], a[2], a[3], a[4]) then nbad = nbad + 1 end
end
print("reject " .. nbad .. "/" .. #bad)
print("accept " .. tostring(EX.valid_order("res_gems", "b", "le", 28)))

-- THE CAP ---------------------------------------------------------------------------------
EX.orders = {}
local placed, refused = 0, nil
for i = 1, EX.ORDER_MAX + 3 do
    local why = EX.place_order("res_gems", "b", "le", i)
    if why then refused = why else placed = placed + 1 end
end
print("cap " .. placed)
print("capsaid " .. tostring(refused ~= nil))

-- DUPLICATES ------------------------------------------------------------------------------
EX.orders = {}
EX.place_order("res_rom_iron", "s", "ge", 30)
print("dup " .. tostring(EX.place_order("res_rom_iron", "s", "ge", 30) ~= nil))
print("dupcount " .. #EX.orders)

-- AT THE CAP, A DUPLICATE STILL READS AS A DUPLICATE. Both refusals apply at once here and
-- the specific one has to win, or the ticket sends the player off to cancel an order to make
-- room for one that is already standing.
EX.orders = {}
for i = 1, EX.ORDER_MAX do EX.place_order("res_gems", "b", "le", i) end
print("capdup " .. tostring(EX.place_order("res_gems", "b", "le", 1)))
print("capdup_n " .. #EX.orders)

-- THE PRICE EACH SIDE ACTUALLY GETS ------------------------------------------------------
-- Every order surface printed EX.price_at, which is the MIDDLE of the spread: the ticket, the
-- order sentence and the ledger's price column all read "Sell at or above 621g" over a fill
-- that paid 559 - or 310 on a Layer 2 instrument, where EX.sell_price applies the l2_sell
-- factor. Found by the 2026-09-10 whole-feature review; it is a display defect, but the thing
-- displayed is a promise about money.
EX.current = EX.current or {}
EX.current["res_gems"] = 20
print("mid " .. EX.price_at(20))
print("ordbuy " .. EX.order_price("res_gems", "b", 20))
print("ordsell " .. EX.order_price("res_gems", "s", 20))
print("ordtext " .. EX.order_text({ res = "res_gems", side = "s", cmp = "ge", rung = 20 }))
-- AND IT TRACKS THE RUNG, not just today's price - two rungs apart must quote two prices, or
-- the ticket would read the same number whatever the stepper was set to.
print("ordsell2 " .. EX.order_price("res_gems", "s", 24))

-- THE AMOUNT ----------------------------------------------------------------------------
-- One number for both surfaces: the Buy/Sell buttons read it and Place freezes it onto the
-- order. Measured need, 2026-09-11: 25 separate Buy clicks on Salt in a single turn.
EX.amount = 1
local ladder = {}
for i = 1, #EX.AMOUNTS + 1 do
    ladder[#ladder + 1] = tostring(EX.amount)
    EX.cycle_amount()
end
print("amount_cycle " .. table.concat(ladder, ","))
EX.amount = 7                      -- not on the ladder at all
EX.cycle_amount()
print("amount_offladder " .. EX.amount)
print("clamp_lo " .. EX.clamp_lots(0) .. " " .. EX.clamp_lots(-4) .. " " .. EX.clamp_lots("x"))
print("clamp_hi " .. EX.clamp_lots(9999))
print("clamp_frac " .. EX.clamp_lots(3.7))
print("clamp_nil " .. EX.clamp_lots(nil))
EX.amount = 1

-- ONE LOT AT A TIME, AND IT STOPS AT BOTH ENDS. The ladder cannot reach 20, which is the
-- size the player asked for; the steppers can. Clamping is EX.clamp_lots' job and this is the
-- proof the steppers go through it rather than adding to a raw field.
EX.amount = 1
EX.step_amount(-1)
print("step_floor " .. EX.amount)
EX.amount = 25
EX.step_amount(1)
print("step_ceil " .. EX.amount)
EX.amount = 19
EX.step_amount(1)
print("step_twenty " .. EX.amount)
EX.amount = 1

-- A LOT IS NOT A UNIT, AND THE PANEL HAS TO SAY WHICH. EX.LOT_SIZE is 10 on a commodity and
-- EX.L2_LOT_SIZE is 100 on a Layer 2 pool, so "x5" means 50 of one and 500 of the other -
-- reported from a screenshot 2026-09-11, an Amount x5 on Marble that moved 50 Marble for 2565
-- gold with neither number anywhere on screen.
EX.amount = 5
print("units_commodity " .. EX.amount_units("res_gems"))
print("units_layer2 " .. EX.amount_units(EX.LAYER2[1]))
-- NO INSTRUMENT, NO UNIT COUNT. The Trade list governs 17 commodities and two Layer 2 pools
-- at once, so its own button has to fall back to the multiplier rather than pick one of them.
print("units_none " .. EX.amount_units(nil))
-- AND THE COST LINE IS THE SIDE'S PRICE TIMES THE LOTS, at the rung the ticket is set to.
EX.ord_side = "b"
local one = EX.order_price("res_gems", "b", 20)
print("cost_line " .. EX.amount_line("res_gems", 20))
print("cost_expect " .. (one * 5))
-- AND THE SELL SIDE, which is the one that proves it is not quoting the mid. On a calm board
-- EX.buy_price and EX.price_at are the SAME NUMBER - hostility is the only thing that parts
-- them - so a buy-side check alone passes against the mid. EX.sell_price applies the spread
-- unconditionally, so this is where the two disagree. Third time this trap has cost a
-- surviving mutant in this file; see the rent floor's own note.
EX.ord_side = "s"
print("cost_sell " .. EX.amount_line("res_gems", 20))
print("cost_sell_expect " .. (EX.order_price("res_gems", "s", 20) * 5))
print("cost_mid " .. (EX.price_at(20) * 5))
EX.ord_side = "b"
EX.amount = 1

-- A FOUR-FIELD RECORD IS A SAVE WRITTEN BEFORE THE AMOUNT EXISTED. It has to load, and it
-- has to load as one lot - a build upgrade that empties the ledger, or that silently turns
-- every standing order into twenty-five lots, is the worst outcome this feature can have.
EX.unpack_orders("res_gems,b,le,28;res_dyes,s,ge,30")
print("legacy_n " .. #EX.orders)
print("legacy_qty " .. tostring(EX.orders[1] and EX.orders[1].qty))
print("legacy_requantised " .. EX.pack_orders())
-- and a five-field one round-trips its size
EX.unpack_orders("res_gems,b,le,28,5")
print("modern_qty " .. tostring(EX.orders[1] and EX.orders[1].qty))
-- a qty outside the ladder is clamped on the way in rather than rejected, so a hand-edited
-- or corrupted save loses the size and keeps the order
EX.unpack_orders("res_gems,b,le,28,9999")
print("wild_qty " .. tostring(EX.orders[1] and EX.orders[1].qty))

-- THE SENTENCE ONLY SPEAKS THE SIZE WHEN THERE IS ONE.
print("text_one " .. EX.order_text({ res = "res_gems", side = "b", cmp = "le", rung = 28, qty = 1 }))
print("text_many " .. EX.order_text({ res = "res_gems", side = "b", cmp = "le", rung = 28, qty = 5 }))

-- SCOPE -----------------------------------------------------------------------------------
EX.orders = {}
print("house " .. tostring(EX.place_order("cr_chd_zharr_naggrund", "b", "le", 20) ~= nil))

-- ROUND TRIP ------------------------------------------------------------------------------
EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)
EX.place_order("res_gems", "b", "le", 24)
EX.place_order("res_rom_iron", "s", "ge", 19)
local packed = EX.pack_orders()
print("packed " .. packed)
EX.unpack_orders(packed)
print("trip " .. tostring(EX.pack_orders() == packed))
print("tripn " .. #EX.orders)
-- AND AT A SIZE THAT IS NOT THE DEFAULT. Everything above places at one lot, so a pack_orders
-- that wrote a hard "1" would round-trip perfectly and still reset every sized order a player
-- holds on the next load. The size has to be READ from the order on the way out.
EX.amount = 10
EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)
EX.amount = 1
local sized = EX.pack_orders()
print("sized_packed " .. sized)
EX.unpack_orders(sized)
print("sized_qty " .. tostring(EX.orders[1] and EX.orders[1].qty))
EX.unpack_orders(packed)     -- and put the three-order board back for the scenes below

-- ORDERS BY INSTRUMENT ---------------------------------------------------------------------
-- EX.orders_on(res) is what the ticket lists beside a selected row; wrong filtering here
-- would show one instrument's standing orders on another's ticket.
print("on_gems " .. #EX.orders_on("res_gems"))
print("on_iron " .. #EX.orders_on("res_rom_iron"))
print("on_dyes " .. #EX.orders_on("res_dyes"))

-- MALFORMED INPUT ---------------------------------------------------------------------------
EX.unpack_orders("")
print("empty " .. #EX.orders)
EX.unpack_orders(nil)
print("nilin " .. #EX.orders)
EX.unpack_orders("res_gems,b,le,28;garbage;res_rom_iron,s,ge,99;res_dyes,b,ge,7")
print("salvage " .. #EX.orders)

-- A SAVE CARRYING MORE THAN THE CAP IS TRUNCATED. EX.ORDER_MAX can be lowered between
-- builds, and a save written under the old one still names every order it held - so the
-- while-loop at the end of EX.unpack_orders is the only thing standing between that save and
-- a ledger with more rows than the page has slots. It drops from the END, so the orders the
-- player placed FIRST are the ones kept.
local over = {}
for i = 1, EX.ORDER_MAX + 4 do
    over[#over + 1] = EX.pack_one("res_gems", "b", "le", i)
end
EX.unpack_orders(table.concat(over, EX.ORD_RS))
print("overcap " .. #EX.orders)
print("overcap_first " .. EX.orders[1].rung)
print("overcap_last " .. EX.orders[#EX.orders].rung)

-- CANCEL ------------------------------------------------------------------------------------
EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)
EX.place_order("res_gems", "b", "le", 28 - 4)
print("cancel " .. tostring(EX.cancel_order("res_gems", "b", "le", 28)))
print("cancelleft " .. #EX.orders)
print("cancelkept " .. EX.orders[1].rung)
print("cancelmiss " .. tostring(EX.cancel_order("res_ivory", "b", "le", 3)))

-- WHICH SIDE OF THE RUNG ---------------------------------------------------------------------
-- The whole feature in four lines. A comparison inverted here is a stop-loss that sells on the
-- way up, and nothing else in the suite would notice.
EX.current = { res_gems = 20 }
local function hits(side, cmp, rung)
    return EX.order_hits({ res = "res_gems", side = side, cmp = cmp, rung = rung })
end
print("limitbuy_in "   .. tostring(hits("b", "le", 21)))
print("limitbuy_out "  .. tostring(hits("b", "le", 19)))
print("stopbuy_in "    .. tostring(hits("b", "ge", 19)))
print("stopbuy_out "   .. tostring(hits("b", "ge", 21)))
print("limitsell_in "  .. tostring(hits("s", "ge", 19)))
print("limitsell_out " .. tostring(hits("s", "ge", 21)))
print("stopsell_in "   .. tostring(hits("s", "le", 21)))
print("stopsell_out "  .. tostring(hits("s", "le", 19)))
print("exact_le " .. tostring(hits("b", "le", 20)))
print("exact_ge " .. tostring(hits("b", "ge", 20)))

-- TEXT ----------------------------------------------------------------------------------------
print("text " .. EX.order_text({ res = "res_gems", side = "b", cmp = "le", rung = 28 }))
print("textsell " .. EX.order_text({ res = "res_gems", side = "s", cmp = "ge", rung = 28 }))

-- THE FATAL / TRANSIENT SPLIT ------------------------------------------------------------
-- Every token EX.apply_trade can return is classified, and the two sets do not overlap. An
-- unclassified token defaults to transient, which is the safe direction - an order that
-- outlives its cause is visible in the ledger, an order silently cancelled is not.
local tokens = { "delisted", "nopool", "nothold", "unavailable", "blocked", "afford",
                 "rent", "threw" }
local nfatal, ntrans, nsaid = 0, 0, 0
for _, t in ipairs(tokens) do
    if EX.ORDER_FATAL[t] then nfatal = nfatal + 1 else ntrans = ntrans + 1 end
    if EX.ORDER_REASON[t] then nsaid = nsaid + 1 end
end
print("fatal " .. nfatal)
print("transient " .. ntrans)
print("reasons " .. nsaid .. "/" .. #tokens)
print("unknown_transient " .. tostring(not EX.ORDER_FATAL["something_new"]))

-- THE FILL PASS ---------------------------------------------------------------------------
-- EX.apply_trade is replaced wholesale. What is being measured is which orders fill_orders
-- chooses and what it does with the answers, not the trade itself - that is _price_harness
-- and _holdings_harness.
EX.feature = function() return true end
EX.log_subject = function(r) return r end
-- COUNTED, NOT SWALLOWED. A bare no-op here is the same shape as the EX.feature stub that
-- let EX.fill_orders sit dead in a live game across two builds: a stub that makes the thing
-- under test unobservable turns a real check green. The fill pass does not care what the Log
-- says, but the TICKET's refusal path does - it is the whole of finding 3.
EX.log_calls, EX.log_last = 0, nil
EX.log_add = function(_s, d) EX.log_calls = EX.log_calls + 1; EX.log_last = d end
EX.neutral_rung = function() return 25 end

-- THE WORLD THE FILL PASS READS. EX.fill_orders reserves this turn's warehouse rent before
-- each buy, so it reaches EX.carry_total -> EX.carry_cost -> EX.held on every pass. These
-- three are the INPUTS to that floor; EX.carry_total, EX.carry_cost, EX.rent_delta and
-- EX.fill_clears_rent all run for real, because stubbing the arithmetic under test is the
-- EX.log_add mistake in another costume. Rent starts OFF so the fill-choice tests below
-- measure only which orders fill; the floor's own scene turns it on.
local gold, holding, rent_on = 0, {}, false
cm.get_faction = function()
    return { treasury = function() return gold end,
             is_null_interface = function() return false end }
end
EX.held = function(res) return holding[res] or 0 end
EX.setting = function(k) if k == "warehouse_rent" then return rent_on end return true end

local calls, verdict = {}, {}
EX.apply_trade = function(res, is_buy)
    calls[#calls + 1] = res .. (is_buy and ":b" or ":s")
    return verdict[res] == nil and true or verdict[res]
end

-- ONE FILL PER INSTRUMENT PER TURN, and FIFO within it.
EX.current = { res_gems = 10, res_rom_iron = 40 }
EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)   -- in the money, first
EX.place_order("res_gems", "b", "le", 24)   -- in the money, second - must NOT fill
EX.place_order("res_rom_iron", "s", "ge", 30)   -- in the money, other instrument - must fill
EX.place_order("res_dyes", "b", "le", 5)    -- out of the money - must not fill
calls = {}
EX.fill_orders()
print("fills " .. table.concat(calls, "|"))
print("left " .. #EX.orders)
print("leftfirst " .. EX.orders[1].res .. "," .. EX.orders[1].rung)

-- A FATAL REFUSAL CANCELS, A TRANSIENT ONE DOES NOT.
EX.current = { res_gems = 10 }
EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)
verdict = { res_gems = "afford" }
calls = {}
EX.fill_orders()
print("transient_left " .. #EX.orders)

EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)
verdict = { res_gems = "nopool" }
EX.fill_orders()
print("fatal_left " .. #EX.orders)

-- THE FEATURE SWITCH STOPS THE MODEL, not just the page.
verdict = {}
EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)
EX.feature = function() return false end
calls = {}
EX.fill_orders()
print("switched_off " .. #calls)
print("switched_left " .. #EX.orders)
EX.feature = function() return true end

-- THE WAREHOUSE-RENT FLOOR ------------------------------------------------------------------
-- A fill spends at turn step 9b; EX.charge_carry debits the rent about six steps later in the
-- SAME turn round with no floor, so before this a standing order could end the turn with a
-- negative treasury the player never chose. Manual buys are deliberately still unfloored, so
-- what is measured here is that the floor is on the FILL path and nowhere else.
--
-- THE STUBS ARE THE INPUTS, NOT THE ANSWER. EX.carry_total, EX.carry_cost, EX.rent_delta and
-- EX.fill_clears_rent all run for real; only the treasury, the holding and the rent switch
-- are stood in for. Stubbing carry_total itself would be the EX.log_add mistake again.
local keep_trade = EX.apply_trade
rent_on = true
-- THE TREASURY MOVES WITH THE FILL. A static treasury stub cannot tell rent_added from a
-- floor that only ever reads the pre-pass number, because the second buy of a pass would see
-- the same gold the first one did.
EX.apply_trade = function(res, is_buy)
    calls[#calls + 1] = res .. (is_buy and ":b" or ":s")
    if is_buy then gold = gold - EX.buy_price(res)
    else gold = gold + EX.sell_price(res) end
    return true
end

EX.current = { res_gems = 20 }
local gem_buy = EX.buy_price("res_gems")
holding = { res_gems = 600 }        -- 600 * 0.5 = 300 gold of rent already standing
print("rent_rate " .. EX.opt("carry_per_unit"))
print("rent_base " .. EX.carry_total())
print("rent_delta " .. EX.rent_delta("res_gems"))

-- ONE GOLD INSIDE THE FLOOR: the buy is affordable and the rent that follows it is not.
local function one_buy(g)
    gold, calls, EX.orders = g, {}, {}
    EX.place_order("res_gems", "b", "le", 28)
    EX.fill_orders()
    return #calls, #EX.orders
end
local n, left = one_buy(gem_buy + 300)
print("floor_calls " .. n)
print("floor_left " .. left)
print("floor_said " .. tostring(EX.log_last))
-- AND TEN GOLD OUTSIDE IT, which is the case that proves the floor is not simply refusing
-- every fill. The gap between these two is the new lot's own rent: reserve 300 instead of 305
-- and the 300 case fills.
n, left = one_buy(gem_buy + 310)
print("clear_calls " .. n)
print("clear_left " .. left)

-- RENT OFF RESERVES NOTHING AT ALL, and the treasury is exactly the price to prove it: the
-- 600 units in the warehouse are still there and EX.carry_total still answers 300, so a floor
-- that read the holding without reading the switch refuses this and the honest one fills it.
rent_on = false
n, left = one_buy(gem_buy)
print("rentoff_calls " .. n)
rent_on = true

-- THE FLOOR PREDICTS THE PRICE EX.apply_trade WILL ACTUALLY CHARGE. On a calm board
-- EX.buy_price and EX.price are the same number, so every case above passes either way; a
-- hostile guild is what separates them, and the markup is real gold the fill will spend.
local keep_hostility = EX.hostility
EX.hostility = function() return 0.25 end
local hot_buy = EX.buy_price("res_gems")
print("hot_buy " .. hot_buy)
print("hot_mid " .. EX.price("res_gems"))
gold, calls, EX.orders = hot_buy + 300, {}, {}
EX.place_order("res_gems", "b", "le", 28)
EX.fill_orders()
print("hot_calls " .. #calls)
EX.hostility = keep_hostility

-- A SELL IS NEVER FLOORED. It raises gold and lowers the holding; floor it and a player short
-- of the rent could not sell to raise it.
gold, calls, EX.orders = 0, {}, {}
EX.place_order("res_gems", "s", "ge", 12)
EX.fill_orders()
print("sell_calls " .. #calls)

-- THE PASS ACCUMULATES. Two buys, no holding at all, so the whole reserve is the two new lots'
-- own rent: the first fill must carry its 5 gold into the second's floor. Read the pre-pass
-- carry_total only and the second buy fills with nothing left for its rent.
holding = {}
EX.current = { res_gems = 20, res_dyes = 20 }
local dye_buy = EX.buy_price("res_dyes")
gold, calls, EX.orders = gem_buy + dye_buy + 5, {}, {}
EX.place_order("res_gems", "b", "le", 28)
EX.place_order("res_dyes", "b", "le", 28)
EX.fill_orders()
print("accum_calls " .. table.concat(calls, "|"))
print("accum_left " .. #EX.orders)

-- The rent switch goes back off and the counting stub returns, so everything below measures
-- what it did before this scene existed.
-- LAYER 2 PAYS NO WAREHOUSING, so an order on it reserves nothing however much is held.
-- EX.carry_cost exempts it because Armaments and Raw Materials come out of BUILDINGS and
-- charging rent on them would tax ordinary Chaos Dwarf play; a floor that forgot the
-- exemption would refuse fills against a bill that is never sent.
local l2 = EX.LAYER2[1]
holding = { [l2] = 1000 }
EX.current = { [l2] = 20 }
gold, calls, EX.orders = EX.buy_price(l2), {}, {}
EX.place_order(l2, "b", "le", 28)
print("l2_delta " .. EX.rent_delta(l2))
EX.fill_orders()
print("l2_calls " .. #calls)

EX.apply_trade, rent_on = keep_trade, false
EX.current = { res_gems = 10, res_rom_iron = 40 }
EX.orders = {}

-- PLACING AND WITHDRAWING LEAVE A TRACE -----------------------------------------------------
-- Before 2026-09-11 neither wrote a Log line, so an order that vanished for a BAD reason was
-- indistinguishable from one the player withdrew - both left the Log silent. Measured live at
-- turn 11: three orders gone, zero order lines in a 37-entry Log, and no way to tell which.
EX.current = { res_gems = 20 }
EX.orders = {}
EX.log_calls, EX.log_last = 0, nil
EX.place_order("res_gems", "b", "le", 28)
print("place_logged " .. EX.log_calls)
print("place_said " .. tostring(EX.log_last))

EX.log_calls, EX.log_last = 0, nil
EX.cancel_order("res_gems", "b", "le", 28)
print("cancel_logged " .. EX.log_calls)
print("cancel_said " .. tostring(EX.log_last))

-- A REFUSED PLACEMENT IS NOT A PLACEMENT. The refusal already reaches the player through the
-- return value - the ticket prints it on the standing line and EX.ticket_click logs it - so a
-- line here too would double up on one click.
EX.log_calls, EX.log_last = 0, nil
print("refused_why " .. tostring(EX.place_order("res_gems", "x", "le", 28)))
print("refused_logged " .. EX.log_calls)

-- WITHDRAWING SOMETHING THAT IS NOT THERE LOGS NOTHING EITHER.
EX.log_calls = 0
print("nocancel " .. tostring(EX.cancel_order("res_ivory", "b", "le", 3)))
print("nocancel_logged " .. EX.log_calls)

-- N LOTS IS N REAL TRADES ------------------------------------------------------------------
-- The manual path. Twenty-five clicks and one x25 click must reach EX.apply_trade the same
-- number of times, on the same instrument, or the bulk path is a second pricing model.
EX.orders = {}
verdict = {}
calls = {}
EX.bulk_trade("res_gems" .. EX.ORD_FS .. "5", true)
print("bulk_calls " .. #calls)
print("bulk_same " .. tostring(calls[1] == "res_gems:b" and calls[5] == "res_gems:b"))
-- A BARE RESOURCE KEY, no amount field, is one lot - that is what every caller written
-- before the amount control sends.
calls = {}
EX.bulk_trade("res_gems", true)
print("bulk_bare " .. #calls)
-- AND IT STOPS AT THE FIRST NO rather than hammering the same refusal N times.
calls = {}
verdict = { res_dyes = "afford" }
print("bulk_done " .. EX.bulk_trade("res_dyes" .. EX.ORD_FS .. "10", true))
print("bulk_stopped " .. #calls)
verdict = {}

-- AN ORDER FILLS ITS OWN SIZE ----------------------------------------------------------------
EX.current = { res_gems = 10 }
EX.orders = {}
EX.amount = 5
EX.place_order("res_gems", "b", "le", 28)
print("order_qty " .. tostring(EX.orders[1].qty))
calls = {}
EX.fill_orders()
print("qty_calls " .. #calls)
print("qty_left " .. #EX.orders)
EX.amount = 1

-- A PART FILL SHRINKS AND STANDS. Three lots go through, the fourth is refused; the order
-- must keep the REMAINDER rather than vanishing (the player loses a size they chose) or
-- staying whole (next turn buys more than they asked for).
EX.current = { res_gems = 10 }
EX.orders = {}
EX.amount = 5
EX.place_order("res_gems", "b", "le", 28)
EX.amount = 1
local n_ok = 0
EX.apply_trade = function(res, is_buy)
    calls[#calls + 1] = res .. (is_buy and ":b" or ":s")
    n_ok = n_ok + 1
    if n_ok > 3 then return "afford" end
    return true
end
calls = {}
EX.log_calls, EX.log_last = 0, nil
EX.fill_orders()
print("part_calls " .. #calls)
print("part_left " .. #EX.orders)
print("part_qty " .. tostring(EX.orders[1] and EX.orders[1].qty))
print("part_said " .. tostring(EX.log_last))
EX.apply_trade = function(res, is_buy)
    calls[#calls + 1] = res .. (is_buy and ":b" or ":s")
    return verdict[res] == nil and true or verdict[res]
end

-- THE PER-TRADE REPRICE IS SUPPRESSED DURING THE PASS.
print("filling_clear " .. tostring(EX.filling == false))

-- AN ERROR INSIDE EX.apply_trade MUST NOT ABORT THE PASS. Found 2026-09-10: cm:get_faction
-- and the counterparty walk in the real EX.apply_trade are not defensive, and an error
-- escaping mid-loop would skip BOTH the EX.filling reset and the `EX.orders = keep` commit -
-- leaving an order that ALREADY FILLED earlier in the same pass still in EX.orders, primed to
-- fire a second real trade next turn, and EX.filling stuck true, silently killing every later
-- manual trade's reprice. Every stub above returns a plain value and can never throw, so this
-- is the one scenario nothing else in this file can reach.
EX.current = { res_gems = 10, res_rom_iron = 40 }
EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)       -- fills first
EX.place_order("res_rom_iron", "s", "ge", 30)   -- throws
EX.apply_trade = function(res, is_buy)
    if res == "res_rom_iron" then error("boom") end
    return true
end
local ok = pcall(EX.fill_orders)
print("throw_survived " .. tostring(ok))
local function has_res(res)
    for i = 1, #EX.orders do if EX.orders[i].res == res then return true end end
    return false
end
print("throw_gems_gone " .. tostring(not has_res("res_gems")))
print("throw_iron_kept " .. tostring(has_res("res_rom_iron")))
print("throw_filling_clear " .. tostring(EX.filling == false))

-- THE OPS ----------------------------------------------------------------------------------
-- mp_send in singleplayer calls mp_apply directly, so this measures the same path the network
-- takes minus the transport - which is the only half a single process can reach.
EX.orders = {}
EX.me = function() return "test_faction" end
EX.is_mp = function() return false end
EX.with_player = function(_f, fn) fn() end
EX.order_send("res_gems", "b", "le", 28)
print("op_place " .. #EX.orders)
EX.order_cancel_send("res_gems", "b", "le", 28)
print("op_cancel " .. #EX.orders)
EX.MP_OPS.ord("this,is,not,an,order")
print("op_junk " .. #EX.orders)
-- THE LONGEST KEY, FOUND RATHER THAN NAMED. This was hand-picked as res_gold_idols, which
-- is 14 characters against res_rom_textiles's 16 - so the worst case it measured was not the
-- worst case. Derived from EX.instruments() so a longer key added later is measured on the
-- day it lands, and taken over ALL instruments rather than only the orderable ones, because
-- a budget wants the ceiling.
local longest = ""
for _, k in ipairs(EX.instruments()) do
    if #k > #longest then longest = k end
end
print("op_longest " .. longest)
print("op_len " .. #("zx1|ordx|" .. EX.pack_one(longest, "s", "ge", 42)))

-- EX.unpack_one'S OWN GUARD, TESTED DIRECTLY. The op_junk case above goes through
-- EX.MP_OPS.ord, which happens to be safe either way because EX.place_order re-validates on
-- its own - so that alone cannot tell a dropped EX.valid_order check in EX.unpack_one from one
-- that is still there. EX.MP_OPS.ordx has no such second gate (EX.cancel_order does not call
-- EX.valid_order at all), so unpack_one is the only thing standing at that trust boundary.
print("unpack_one_junk " .. tostring(EX.unpack_one("this,is,not,an,order") == nil))

-- THE LEDGER'S CANCEL CLICK -----------------------------------------------------------------
-- ROWS ARE KEYED BY ORDER INDEX, NOT BY INSTRUMENT. EX.row is pooled ONE PER RESOURCE
-- everywhere else in this file (EX.ROW .. "_" .. EX.short(res)), and uicomponent:Id()
-- "returns the string name of this uicomponent" per CA's own docs - exactly the string
-- CreateComponent was given, with no rename call ever available on a live component - so a
-- resource-keyed row could never carry two orders on one instrument. A LADDER here (two gem
-- rungs) is the case that actually exercises that: under the old resource-keyed naming both
-- would resolve to the SAME physical row.
EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)   -- ord1
EX.place_order("res_gems", "b", "le", 20)   -- ord2, the ladder rung this test cancels
EX.place_order("res_dyes", "s", "ge", 30)   -- ord3
local row2 = EX.ROW .. "_ord2"
local resolved = EX.order_of_row(row2)
print("order_of_row_res " .. tostring(resolved and resolved.res))
print("order_of_row_rung " .. tostring(resolved and resolved.rung))
print("order_of_row_unknown " .. tostring(EX.order_of_row("no_such_row") == nil))
-- A RESOURCE-KEYED ID MUST NEVER RESOLVE THROUGH EX.res_of_row EITHER. It inverts
-- EX.ROW .. "_" .. EX.short(res) against EX.instruments(), which never contains an "ordN"
-- key, so an "ord" row id has to come back nil on its own - if it ever did not, the
-- trade/offerings/houses click paths could claim a ledger row by accident.
print("res_of_row_on_ord_id " .. tostring(EX.res_of_row(row2) == nil))

-- THE CLICK REMOVES THE ORDER THE ROW NAMED - the SECOND gem rung, not the first, and not
-- "whichever one happens to be on res_gems". This is exactly what EX.refresh_panel's Cancel
-- button sends: the resolved order's own fields, not its position. A resolver that always
-- answered EX.orders[1] would still pass every check above (all four THE OPS calls above
-- cancel the order they name too, because EX.orders[1] there legitimately IS the order under
-- test) while cancelling the FIRST gem rung every time the player pressed Cancel on the
-- SECOND row.
EX.order_cancel_send(resolved.res, resolved.side, resolved.cmp, resolved.rung)
print("cancel_click_left " .. #EX.orders)
print("cancel_click_gone_rung20 " .. tostring(EX.find_order("res_gems", "b", "le", 20) == nil))
print("cancel_click_kept_rung28 " .. tostring(EX.find_order("res_gems", "b", "le", 28) ~= nil))
print("cancel_click_kept_dyes " .. tostring(EX.find_order("res_dyes", "s", "ge", 30) ~= nil))

-- THE ROW-CLICK DISPATCH ---------------------------------------------------------------------
-- FOUND 2026-09-10: every check above proves the MODEL works (EX.order_of_row resolves the
-- right rung, EX.cancel_order removes the right one) but none of them ever go through
-- EX.row_click, the function the real ComponentLClickUp listener now dispatches to. That gap
-- hid a fully dead Cancel button: the listener used to resolve EX.res_of_row and bail with
-- `if not res then return end` BEFORE ever reaching the EX.on_orders() branch - and
-- EX.res_of_row can never match a synthetic "ordN" ledger row id - so every ledger click
-- returned early and Cancel did nothing, silently, with every check above still green.
-- EX.row_click(s, row_id) is the extracted tail, callable with a bare row id and no live
-- campaign, and it puts EX.on_orders() FIRST specifically so this cannot happen again unnoticed.
--
-- EX.layout/EX.refresh_panel are stubbed to no-ops here: this harness has no UIComponent
-- system at all (see _layout_harness.lua for that), and what is under test is whether the
-- click reaches the model, not how the page redraws afterwards.
EX.layout = function() end
EX.refresh_panel = function() end
EX.mode = EX.MODE_TRADE
EX.trade_page = 3   -- trade_pages() is {"list","chart","orders"} with EX.feature stubbed true.

EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)   -- ord1
EX.place_order("res_gems", "b", "le", 20)   -- ord2, the ladder rung
EX.place_order("res_dyes", "s", "ge", 30)   -- ord3

-- CLICK 1: cancels the FIRST gem rung (ord1) and leaves the second, which slides up to ord1.
EX.row_click("btn_buy", EX.ROW .. "_ord1")
print("row_click_1_left " .. #EX.orders)
print("row_click_1_first " .. tostring(EX.orders[1] and (EX.orders[1].res .. "," .. EX.orders[1].rung)))

-- CLICK 2, SAME ROW ID: must remove what is NOW first (rung 20), not no-op and not reach
-- past it to the dyes order. A resolver that always answered EX.orders[1] would pass click 1
-- by coincidence and still be caught here.
EX.row_click("btn_buy", EX.ROW .. "_ord1")
print("row_click_2_left " .. #EX.orders)
print("row_click_2_first " .. tostring(EX.orders[1] and (EX.orders[1].res .. "," .. EX.orders[1].rung)))

-- AN INSTRUMENT-KEYED ID IS NOT A LEDGER ROW. Still on the ledger (EX.on_orders() true),
-- EX.order_of_row must fail to resolve this id (it never ends "_ordN") and the on_orders
-- branch must return having done nothing - not fall through to EX.res_of_row and treat this
-- click as an ordinary buy.
EX.orders = {}
EX.place_order("res_gems", "b", "le", 28)
EX.row_click("btn_buy", EX.ROW .. "_" .. EX.short("res_gems"))
print("row_click_instrument_id_on_ledger_noop " .. tostring(
    #EX.orders == 1 and EX.find_order("res_gems", "b", "le", 28) ~= nil))

-- THE REORDERING MUST NOT BREAK ORDINARY BUY/SELL. Off the ledger (the trade list), the same
-- EX.row_click must still resolve through EX.res_of_row and reach EX.trade - proving that
-- moving the EX.on_orders() branch to the front did not swallow every other row click with it.
local trade_calls = {}
EX.trade = function(res, is_buy) trade_calls[#trade_calls + 1] = res .. (is_buy and ":b" or ":s") end
EX.mode = EX.MODE_TRADE
EX.trade_page = 1
EX.row_click("btn_buy", EX.ROW .. "_" .. EX.short("res_gems"))
print("row_click_trade_reached " .. tostring(trade_calls[1] == "res_gems:b"))

-- THE TICKET-CLICK DISPATCH -------------------------------------------------------------------
-- Same gap as EX.row_click's above, and the same fix: EX.ticket_click is the extracted tail
-- the real ComponentLClickUp listener calls for these five panel-level components, and
-- nothing anywhere else ever calls it. A toggle wired backwards, a rung that never moves, or
-- a Place button reading the wrong side would pass every geometry and wiring check in this
-- task list with EX.ticket_click never having run once - which is the exact "branch that
-- looks right and is unreachable" trap the filter/handler static check cannot see into.
EX.orders = {}
EX.selected = "res_gems"
EX.ord_side, EX.ord_cmp, EX.ord_rung = "b", "le", 20

EX.ticket_click("ord_side")
print("ticket_side_toggle " .. EX.ord_side)
EX.ticket_click("ord_side")
print("ticket_side_back " .. EX.ord_side)

EX.ticket_click("ord_cmp")
print("ticket_cmp_toggle " .. EX.ord_cmp)
EX.ticket_click("ord_cmp")
print("ticket_cmp_back " .. EX.ord_cmp)

EX.ticket_click("ord_up")
print("ticket_up " .. EX.ord_rung)
EX.ticket_click("ord_down")
EX.ticket_click("ord_down")
print("ticket_down " .. EX.ord_rung)

-- CLAMPED BOTH ENDS, the same ladder EX.valid_order enforces - a rung that walked past
-- either end would be an order nothing could ever place afterwards.
EX.ord_rung = 1
EX.ticket_click("ord_down")
print("ticket_floor " .. EX.ord_rung)
EX.ord_rung = EX.RUNGS
EX.ticket_click("ord_up")
print("ticket_ceiling " .. EX.ord_rung)

-- PLACE, THROUGH THE OP - not EX.place_order directly. EX.order_send goes over
-- EX.mp_send/EX.mp_apply, the same path THE OPS section above already proves round-trips;
-- this is what proves the CLICK actually reaches it, rather than a handler that computes the
-- right rung and then does nothing with it.
EX.orders = {}
EX.ord_side, EX.ord_cmp, EX.ord_rung = "b", "le", 24
EX.ticket_click("ord_place")
print("ticket_place_left " .. #EX.orders)
print("ticket_place_order " .. tostring(EX.find_order("res_gems", "b", "le", 24) ~= nil))

-- THE DRY RUN REFUSES WITHOUT SENDING, and the button must not disagree with the op about
-- why: clicking Place again on the SAME order must add nothing, which is only true if
-- EX.place_order_check is the same guard EX.place_order itself uses.
EX.log_calls = 0
EX.ticket_click("ord_place")
print("ticket_place_dup_left " .. #EX.orders)
-- AND THE PLAYER IS TOLD. EX.say is out() behind log_level >= 2 AND the log_trade debug
-- toggle, so until 2026-09-10 every refusal this button can give was invisible in a real
-- game: the second click on a duplicate did nothing, silently, forever, and the Log view -
-- this mod's stated answer to "the click did nothing" - had no entry either.
print("dup_refusal " .. tostring(EX.ord_refusal ~= nil))
print("dup_logged " .. tostring(EX.log_calls > 0))
-- AND IT IS RETIRED BY THE NEXT EDIT: it described the order that was on screen when Place
-- was pressed, so a stepper click has to clear it rather than leave a stale sentence under
-- an order the player has since changed.
EX.ticket_click("ord_up")
print("dup_refusal_cleared " .. tostring(EX.ord_refusal == nil))

-- THE TICKET IS INERT WITH THE SWITCH OFF. EX.place_order_check refuses the placement either
-- way, so this guard is belt to that brace - but without it every other control on a
-- switched-off feature is still live: the side toggles, the rung steps and the panel
-- refreshes, on a page the player has switched away.
local feat = EX.feature
EX.feature = function(k) if k == "orders" then return false end return feat(k) end
EX.ord_side = "b"
EX.ticket_click("ord_side")
print("ticket_off_side " .. EX.ord_side)
local keep_orders = EX.orders
EX.orders = {}
EX.ticket_click("ord_place")
print("ticket_off_left " .. #EX.orders)
EX.feature = feat
-- PUT THE BOOK BACK. The nil-instrument test below counts on the one order placed above.
EX.orders = keep_orders

-- MUTATION: drop EX.ticket_click's own `if not res then return end` and confirm the deeper
-- guard still holds. EX.place_order_check (and EX.valid_order under it) is the shared check
-- both the ticket and EX.MP_OPS.ord call, so a caller bug that lets a nil instrument through
-- must still be refused THERE rather than relying on this guard alone - see the nil case
-- added to the validation table above for the permanent regression pin on that guard.
EX.selected = nil
EX.ticket_click("ord_place")
print("ticket_place_nil_left " .. #EX.orders)

-- THE REAL DISPATCH, NOT THE TAIL --------------------------------------------------------------
-- EVERYTHING ABOVE CALLS EX.ticket_click DIRECTLY, which proves the tail behaves correctly
-- once reached and proves NOTHING about whether the real ComponentLClickUp handler actually
-- reaches it. That is precisely how Task 6's Cancel button shipped dead: a correct model, a
-- correct filter, and a handler branch that was never wired to either - every check green.
-- EX.click_dispatch(context) is now the WHOLE handler body (see its own comment, where the
-- listener used to carry an anonymous function no harness could reach), so this drives a
-- Place click through THAT, exactly as the game does, rather than through EX.ticket_click.
--
-- MINIMAL UICOMPONENT. This harness has no UI system at all (see _layout_harness.lua for
-- that); this is the smallest fake that lets EX.click_dispatch's row-resolution FALLBACK run
-- to completion if the ticket branch is ever missing or moved past it, instead of throwing
-- before the assertion below can tell a silent wrong-branch from a working one apart.
function UIComponent(c) return c end
local parent_walked = false
local function fake_ticket_component()
    return {
        -- RECORDS THE WALK, and hands back a REAL instrument's row id rather than a bogus
        -- one - so if the ticket branch is ever moved below this walk, the click falls
        -- through to EX.row_click and DOES something (EX.trade on res_gems, since s ==
        -- "ord_place" is not "btn_buy"), not nothing. A bogus id that made EX.res_of_row
        -- return nil would let a silently-broken dispatch pass by coincidence.
        Parent = function()
            parent_walked = true
            return { Id = function() return EX.ROW .. "_" .. EX.short("res_gems") end }
        end,
    }
end

EX.orders = {}
EX.selected = "res_gems"
EX.ord_side, EX.ord_cmp, EX.ord_rung = "b", "le", 26
-- Stubbed for the same reason as the row-click dispatch section above: EX.trade must not
-- actually run cm:get_faction et al, and if the mutation below DOES fall through to it, the
-- call is what proves the wrong branch fired rather than a crash masking the question.
local wrong_branch_calls = 0
EX.trade = function() wrong_branch_calls = wrong_branch_calls + 1 end

parent_walked = false
EX.click_dispatch({ string = "ord_place", component = fake_ticket_component() })
print("dispatch_place_left " .. #EX.orders)
print("dispatch_place_order " .. tostring(EX.find_order("res_gems", "b", "le", 26) ~= nil))
-- THE ASSERTION FINDING 1 ASKS FOR: the ticket branch returns before EX.click_dispatch ever
-- calls UIComponent(clicked:Parent()) - not just that a Place click happens to still work.
print("dispatch_no_row_walk " .. tostring(not parent_walked))
print("dispatch_wrong_branch_calls " .. wrong_branch_calls)

-- THE DEALS PAGE'S OWN BUTTON, THROUGH THE SAME DISPATCH -----------------------------------
-- For exactly the reason the section above exists. EX.accept_deal is asserted a hundred lines
-- at a time in the books harness and every one of those assertions calls it BY NAME; none of
-- them can see whether a click on the page ever reaches it. The deal branch sits above the
-- EX.res_of_row gate in EX.row_click - "dl3" names no instrument, so below the gate it would
-- be eaten silently - and this is the only check that the order is right.
--
-- EX.mp_send IS STUBBED, NOT EX.accept_deal. What is under test is the whole route from the
-- click to the wire, and that includes which op name and which argument go onto it: in
-- multiplayer the argument IS the message.
EX.mode = EX.MODE_DEALS
EX.deals = {
    { fac = "house_a", res = "res_gems", side = "buy",  lots = 1, px = 1060, turn = 10 },
    { fac = "house_b", res = "res_dyes", side = "sell", lots = 2, px = 940,  turn = 10 },
}
local sent_op, sent_arg
EX.mp_send = function(op, arg) sent_op, sent_arg = op, arg end
wrong_branch_calls = 0
parent_walked = false

local function fake_deal_component(n)
    return {
        Parent = function()
            parent_walked = true
            return { Id = function() return EX.ROW .. "_dl" .. n end }
        end,
    }
end

EX.click_dispatch({ string = "btn_buy", component = fake_deal_component(2) })
print("dispatch_deal_op " .. tostring(sent_op) .. "/" .. tostring(sent_arg))
print("dispatch_deal_wrong_branch " .. wrong_branch_calls)

-- PAST THE END SENDS NOTHING. EX.deal_of_row answers nil for an index the list does not hold,
-- which is not paranoia: the row components outlive the page (they are a fixed pool, like the
-- ledger's) and a click landing on turn N+1's shorter list would otherwise send an index into
-- a deal that has already expired.
sent_op, sent_arg = nil, nil
EX.click_dispatch({ string = "btn_buy", component = fake_deal_component(9) })
print("dispatch_deal_past_end " .. tostring(sent_op))

-- AND THE NAME CELL IS NOT A SECOND BUTTON. On the trade page a row_name click charts the
-- instrument; a deal row has no instrument to chart, and charting the commodity behind it
-- would leave the player on another page wondering what their click did.
sent_op, sent_arg = nil, nil
EX.click_dispatch({ string = "row_name", component = fake_deal_component(1) })
print("dispatch_deal_name " .. tostring(sent_op) .. "/" .. tostring(EX.selected))
EX.mode = EX.MODE_TRADE
