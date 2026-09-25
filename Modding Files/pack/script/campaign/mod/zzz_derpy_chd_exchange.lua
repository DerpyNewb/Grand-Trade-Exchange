-- Zharr Exchange: scarcity pricing for the 17 vanilla trade commodities, plus the three
-- Chaos Dwarf pooled resources.
-- Spec: docs/STOCK_MARKET_DESIGN.md
--
-- The EX.* math functions are pure so tools/gen_zharr_exchange.py can run them under lua.exe
-- and assert they agree with the Python side that generated the ladder rows.
--
-- NOTHING RUNS AT FILE ROOT. A local-faction call at script root hard-crashes past pcall, and
-- the log tell is a "Loading mod file" line with no "loaded successfully".
--
-- THERE ARE NO TRADE RITUALS ANY MORE, and this is the history of why there were.
-- v1 traded through 38 STANDARD_RITUAL rows because that is the only category CA's rites panel
-- renders. Then perform_ritual turned out not to charge the treasury (measured 2026-09-04), so
-- the trade became cm:treasury_mod + cm:faction_add_pooled_resource and the rituals stopped
-- doing anything. They stayed anyway - hidden component-side on every rites-panel open, because
-- cm:lock_ritual does not remove a card - and they still counted toward the engine's rite total,
-- which is how the Hell-Forge commission panel came to report 39 rites.
-- Removed 2026-09-05 with their costs, groups and bonus-value junctions. What is left is the
-- three pooled-resource tables that actually hold the goods.

EX = {}

EX.PREFIX      = "derpy_chd_ex_"
EX.LOT_SIZE    = 10
EX.L2_LOT_SIZE = 100
EX.BASE_COST   = 1000
EX.MULT_MIN    = 0.10
EX.MULT_MAX    = 5.00
EX.EXPONENT    = 0.7
EX.LADDER_STEP = 1.10
EX.LADDER_LO   = -24
EX.RUNGS       = 42
EX.SPARK_BARS  = 12
-- Forty turns is the deep chart's width. It is the STORE; the sparkline above is its
-- tail, so a turn is recorded once and the two can never disagree about the same turn.
EX.DEEP_BARS   = 40
-- THE CHART'S GEOMETRY, and all FOUR must match tools/gen_exchange_ui.py. The bars are
-- reached by name (cbar_00..cbar_39) and bottom-aligned by hand with MoveTo, because
-- imagedock is ignored at runtime like every other dock attribute - the same trap
-- EX.draw_spark carries a comment about. check_chart_geometry pins them across the two
-- files; a disagreement is bars that overlap or a plot that stops short, in silence.
EX.CHART_H     = 300
-- 20/16 SINCE THE Y SCALE ARRIVED. The plot starts at x=86 now rather than 20, so the
-- pitch came down to keep all forty bars inside the panel.
EX.CHART_PITCH = 20
EX.CHART_BAR_W = 16
-- THE SHORTEST BAR THE LOWEST PRICE IN THE WINDOW DRAWS. Without a floor that bar has no
-- height at all and the low of the range is invisible. It is also the offset the LOW
-- gridline label is placed at - the bottom of the scale is the top of this stub, not the
-- bottom of the box, and a label at the box bottom would be 6px out from its own data.
EX.CHART_FLOOR = 6
-- WHICH INSTRUMENT THE CHART IS SHOWING, and which page of the Trade view is up. Both are
-- VIEW STATE and neither is ever saved - the same rule EX.log_page and EX.house_page
-- follow. A saved selection would reopen the panel on a commodity the player last looked
-- at four sessions ago, or on a house that has since been delisted.
EX.selected    = nil
EX.trade_page  = 1
-- THE TICKET'S STATE. SESSION ONLY, never saved, same as EX.selected above: a half-composed
-- order need not survive a reload. EX.ord_rung is re-seeded from the instrument's own current
-- rung every time a row is selected - see the row_name click in EX.row_click.
EX.ord_side = "b"
EX.ord_cmp  = "le"
EX.ord_rung = nil
-- WHY THE LAST PLACE WAS REFUSED, or nil. Session state like the three above: it describes
-- the order that was on screen when the button was pressed, so any edit to the ticket and any
-- change of instrument clears it. It exists because EX.say goes to the script log behind two
-- debug gates and a refused Place was otherwise completely silent in a real game.
EX.ord_refusal = nil
-- HOW MANY LOTS A CLICK MOVES. ONE NUMBER FOR BOTH SURFACES, deliberately: the Buy and Sell
-- buttons on the Trade list read it, and Place bakes the same value into the standing order
-- it creates, so "amount" means the same thing wherever the player sets it. Measured need -
-- 2026-09-11, one campaign turn: 25 separate Buy clicks on Salt at 3797 gold, plus four at
-- 3452 and four at 3138. A market whose only size control is the mouse is not a market.
--
-- A LADDER, NOT A STEPPER. The stepper idiom already on the ticket takes two components and
-- a click per step; twenty-five lots would be twenty-four clicks to set up, which is the
-- problem rather than the fix. Four rungs cycle on a single button.
--
-- SESSION ONLY, like every other value in this block. An amount is a thing you set for the
-- trade you are about to make, and a reload should not have opinions about it. The number a
-- standing ORDER carries is different - that one is saved, on the order itself.
EX.AMOUNTS = { 1, 5, 10, 25 }
EX.amount   = 1

function EX.amount_label()
    return "Amount x" .. tostring(EX.amount)
end

-- THE TICKET'S OWN LABEL, IN GOODS. It has a selected instrument, so it can say 50 where the
-- list button can only say x5 - Trade page 1 carries 17 commodities at a lot of 10 beside two
-- Layer 2 pools at 100, and a single unit count there would be wrong on two of its rows. The
-- list's own row buttons carry the units instead, which is where they are unambiguous.
function EX.amount_units(res)
    if not res then return EX.amount_label() end
    return "Amount " .. tostring(EX.lot(res) * EX.clamp_lots(EX.amount))
end

-- Next rung, wrapping. Reads the CURRENT value out of the ladder rather than tracking an
-- index, so a saved-off or hand-set amount that is not on the ladder still advances instead
-- of sticking - it lands on the first rung and carries on from there.
function EX.cycle_amount()
    for i = 1, #EX.AMOUNTS do
        if EX.AMOUNTS[i] == EX.amount then
            EX.amount = EX.AMOUNTS[(i % #EX.AMOUNTS) + 1]
            return
        end
    end
    EX.amount = EX.AMOUNTS[1]
end

-- ONE LOT AT A TIME, so a size the ladder does not carry is still reachable. The cycling
-- button between these two is the fast way to a round number; these are the only way to 7,
-- and 20 - which is the size the player actually asked for - is not on the ladder at all.
function EX.step_amount(d)
    EX.amount = EX.clamp_lots(EX.amount + d)
end

-- WHAT IT WILL ACTUALLY MOVE, AND WHAT THAT COSTS, in goods and in gold.
--
-- "x5" IS FIVE LOTS AND A LOT IS NOT ONE UNIT. EX.LOT_SIZE is 10 for a commodity, 100 for a
-- Layer 2 pool and 5 for a house share, so the multiplier alone never says how much of
-- anything is being bought - reported from a screenshot 2026-09-11, an "Amount x5" on Marble
-- that meant 50 Marble for 2565 gold with neither number anywhere on the panel.
--
-- PRICED AT THE RUNG THE TICKET IS SET TO, not at today's price: this is a projection of what
-- the order will pay when it fills, and EX.order_price is the side's own price rather than
-- the mid. Multiplied rather than walked, because walking it would need the counterparty book
-- turn by turn - so it is a floor on a buy and a ceiling on a sell, which is the honest
-- direction for a number shown before the money moves.
function EX.amount_line(res, rung)
    if not res then return "" end
    local n = EX.clamp_lots(EX.amount)
    local units = EX.lot(res) * n
    local each = EX.order_price(res, EX.ord_side, rung or EX.ord_rung or EX.neutral_rung())
    return units .. " " .. EX.instrument_name(res) .. " - " .. tostring(each * n) .. "g"
end

-- CLAMPED AND WHOLE. Reached from a network op and from a save, so neither a fraction nor a
-- hostile number can turn into that many real trades.
function EX.clamp_lots(n)
    n = tonumber(n)
    if not n then return 1 end
    n = math.floor(n)
    if n < 1 then return 1 end
    local top = EX.AMOUNTS[#EX.AMOUNTS]
    if n > top then return top end
    return n
end
-- THE EIGHT TICKET COMPONENTS, named once so EX.draw_chart's blank pass and the layout
-- harness read the same list rather than two copies that can drift apart.
EX.TICKET_CELLS = { "ord_side", "ord_cmp", "ord_down", "ord_price", "ord_up",
                    "ord_place", "ord_qty_down", "ord_qty", "ord_qty_up", "ord_cost",
                    "ord_standing" }
EX.SPARK_H     = 24     -- must match tools/gen_exchange_ui.py

-- CA's inline colour markup, and it works on a component of ours set with SetStateText -
-- CONFIRMED BY LOOKING, 2026-09-05, not inferred from CA's usage. That distinction is the whole
-- lesson of the "||" tooltip split, which is equally common in vanilla loc and is applied by a
-- resolver our text never reaches. Vanilla uses [[col:red]] 1,649 times and [[col:green]] 854
-- across 241,972 loc entries, but the count was only ever a reason to TEST these two names.
-- The flat arrow stays uncoloured so it reads as "nothing happened" rather than a third state.
EX.TREND_UP   = "[[col:green]]^[[/col]]"
EX.TREND_DOWN = "[[col:red]]v[[/col]]"
EX.TREND_FLAT = "-"
-- FLAT AT EITHER END OF THE LADDER IS NOT "NOTHING HAPPENED". Rung 42 is the MULT_MAX
-- clamp and rung 1 the MULT_MIN one, so a commodity that reaches either cannot move that
-- way again and reads TREND_FLAT forever. Measured over the turn-1-to-60 soak of
-- 2026-09-06: res_rom_glass and res_gold_idols both sat pinned at 42, and gold idols got
-- there by DRIFTING in (40 at turn 34), so it is not only the no-supply case EX.unavailable
-- already catches. The row drew a straight sparkline and a flat dash - the same thing a
-- quiet market draws. These two say which.
--
-- MEASURED, NOT ESTIMATED, AND THE FIRST ATTEMPT SHIPPED BROKEN. These were "MAX" and "MIN",
-- picked against the ~6.7px/char figure check_help_lines uses - which is derived from the
-- GUIDE column at a smaller font and does not describe this one. Screenshotted from play:
-- the cell drew "M...". Asked the engine instead, via TextDimensionsForText on a live
-- row_trend (30x20, state "standard"):
--     ^ 11   v 11   - 8   Hi 19   Lo 20   |   max 29   min 26   MAX 35   MIN 32   TOP 33
-- Capitals in this font run 11-16px EACH, so three of them never had a chance in a 30px box.
-- "Hi"/"Lo" clear it by 10px; lowercase "max"/"min" fit by ONE pixel, which is not a margin.
-- check_trend_glyph_widths pins these against that measurement.
--
-- LETTERS AND NOT MORE ARROWS. "^^" and "vv" both fit at 18px and were rejected: at the cap
-- the price is NOT moving, and a doubled arrow reads as moving hard. The whole point is to
-- distinguish "held still" from "cannot move", so the marker must not look like motion.
EX.TREND_CAP   = "[[col:green]]Hi[[/col]]"
EX.TREND_FLOOR = "[[col:red]]Lo[[/col]]"
EX.SAVE_PREFIX = "zharr_rung_"
EX.SAVE_HIST   = "zharr_hist_"
-- THE DEEP PRICE HISTORY, and it is a SECOND key rather than a widened first one.
-- EX.SPARK_BARS is not just the sparkline's length: it sets the 108px strip width
-- (SPARK_BARS * 9), it is written into the "Last 12 turns" column header, and
-- gen_exchange_ui.py generates exactly that many bar components against it. Widening it
-- to get a longer chart would silently resize a column that has been measured in game.
EX.SAVE_DEEP   = "zharr_deep_"
EX.SAVE_PRESS  = "zharr_press_"
-- LAST TURN'S CULTURE SHARES, packed. WORLD, not per-player: it describes the map, and
-- two players must read one map. Written once per turn by EX.rescan and read by two
-- features that both need "what changed since last turn" - EX.culture_trend, which is the
-- appetite drift term, and EX.share_shocks, where a culture collapsing is a demand shock.
EX.SAVE_CSHARE = "zharr_cshare"
-- PER PLAYER, not per world. Two humans in a multiplayer campaign each meet the panel for
-- the first time on their own turn, and one of them reading the introduction must not
-- take it away from the other. It joins the per-player set for that reason - see
-- EX.PLAYER_KEYS and the note beside EX.setp.
EX.SAVE_INTRO  = "zharr_intro"
EX.SAVE_STRIPPED = "zharr_bundles_stripped"
-- STANDING ORDERS, PER PLAYER. One string, orders separated by EX.ORD_RS and fields by
-- EX.ORD_FS. Per-player because an order spends one player's gold; check_lua_mp refuses to
-- pass on any EX.SAVE_* key that is not classified, and this one is in its PER_PLAYER set.
EX.SAVE_ORDERS = "zharr_ord"

-- STAGE 2. One packed string, the shape EX.SAVE_ORDERS and EX.SAVE_HOUSES already use. Deals
-- are rebuilt every turn, so this exists only so a save reloaded mid-turn shows the same page
-- it showed before the reload - not to carry a deal across a turn boundary, which EX.post_deals
-- would overwrite anyway.
EX.SAVE_DEALS = "zharr_deals"
EX.deals = {}

-- Own-trade impact, moved here from the DB. rituals.percentage_cost_increase_per_use is
-- invisible to script, so it would make the panel show a price the game does not charge.
-- What a deposit with NO building on it contributes. Must match LATENT_PER_REGION in
-- tools/gen_zharr_exchange.py.
--
-- Without it, three commodities read zero on a turn-1 map (ivory, medicine and obsidian all
-- have 10-16 deposit regions and not one mine between them) and would draw "No offer" until
-- somebody built one. It also keeps a deposit worth holding before the mine goes up.
EX.LATENT_PER_REGION = 1

EX.PRESSURE_PER_RUNG = 4      -- net lots bought before the price climbs one rung
EX.PRESSURE_MAX      = 24     -- ...up to six rungs
EX.PRESSURE_DECAY    = 1      -- pressure bled off each turn, so a corner does not last forever

-- THE EXCHANGE'S CUT, and the reason a round trip cannot mint gold. Measured in game
-- 2026-09-05: 55 buys and 55 sells of Exotic Animals, holdings back to 0, netted +906 gold out
-- of nothing. The mechanism is not the supply column - it is that buy and sell both read one
-- EX.price. The fourth buy ticks the rung up, the first sell collects at the higher rung, and
-- pressure then falls back. Bounded per trip, unbounded in repetitions.
--
-- 0.10 IS A FLOOR, NOT A TASTE. One rung is LADDER_STEP = 1.10, and the largest instantaneous
-- edge a round trip can open is exactly one rung, so the spread closes it only while
-- (1 + s_up) * (1 - SPREAD) <= 1. At 1.10 that needs SPREAD >= 1/1.1 = 0.0909. Anything under
-- that reopens the loop with a thinner margin, which is worse than leaving it open - it takes
-- more clicks to find and looks like a rounding artefact. Do not "tune" this below 0.10.
EX.SPREAD            = 0.10

-- LAYER 2 SELLS AT HALF, and it is a different rule from EX.SPREAD rather than a wider one.
--
-- The Forge's output has no map supply signal, so armaments and raw materials sit on the
-- neutral rung for ever: buy 1000, sell 1000 * (1 - SPREAD) = 900, at every price and in every
-- campaign. A fixed 10% round trip on a price that CANNOT MOVE is not a market, it is a
-- 100-unit locker charging 100 gold a visit - and unlike a commodity there is no scenario
-- where waiting for the price to come to you makes it back.
--
-- Half is what makes the direction mean something. Buying the Forge's output out of the
-- Exchange is a convenience worth paying full price for; dumping it back is a fire sale,
-- because a Chaos Dwarf market is not short of armaments and everyone there knows what you
-- are doing. So it is deliberately punitive and deliberately not a spread: the two are
-- separate numbers because EX.SPREAD is load-bearing algebra (see check_spread - it must
-- clear 1 - 1/LADDER_STEP or a round trip mints gold) and this one is a design lever with no
-- arithmetic riding on it. A layer-2 round trip loses half whatever anyone sets the spread to,
-- so it can never open the loop the spread exists to close.
--
-- 100 units per lot: at the default that is BUY 1000, SELL 500. Read through
-- EX.opt("l2_sell"), so this constant is the DEFAULT and the presets move it - easy 0.75,
-- hard 0.40, ultra 0.25, and any value the player likes under Custom.
--
-- IT IS BOUNDED AT RUNTIME, and that bound is not decoration. Layer 2 is not on a frozen
-- price: EX.target_rung excludes appetite, shocks and the guild's book from it, but NOT
-- EX.pressure_shift - so the player's own buying moves the Forge's goods, and it is the only
-- thing that does. Four net lots is a rung, one rung is LADDER_STEP, and a sell factor above
-- 1/LADDER_STEP therefore pays more than the buy cost with no market risk whatsoever. That is
-- the same loop check_spread closes for the commodities, and EX.sell_price clamps it here the
-- way EX.friendly_cap clamps the friendly discount.
EX.L2_SELL           = 0.5

-- OPTION B: the price level moves each faction's VANILLA trade-good income.
-- Must match TRADE_STEPS in tools/gen_zharr_exchange.py - one bundle ships per step.
EX.TRADE_STEPS = { -40, -30, -20, -10, 10, 20, 30, 40 }
-- Percent of trade-good income per 1.0 of price deviation. A commodity at double price
-- (multiplier 2.0, deviation +1.0) earns its owners +40% before the step ladder rounds it down.
-- START LOW AND MEASURE. The whole map gets this, not just the player, and this session already
-- shipped CONCENTRATION_K = 1 as an obviously-reasonable number that turned out to be completely
-- inert in play. A campaign-wide income knob is the one place a bad guess compounds every turn.
EX.TRADE_GAIN  = 40

-- OFFERINGS TO HASHUT. Must match OFFER_COST / OFFER_TURNS in tools/gen_zharr_exchange.py.
--
-- This replaced a passive hold-N-units-for-a-permanent-bonus design, which was a DEPOSIT rather
-- than a purchase: ~363,000 gold reached every tier on the live board, the bonuses then ran
-- forever, and the sell spread gave ~90% of the capital back on demand. An offering BURNS the
-- goods and the favour expires, so the market becomes a supply chain instead of a vault.
-- THE STARTING price, not the price. Each voluntary sacrifice makes the next one 5% dearer:
-- the altar gets used to being fed. 30 units is three lots, so a first offering is cheap
-- enough to try and the tenth is not.
--
-- The escalation is GLOBAL, not per commodity - it is the god's appetite, not one altar's -
-- and it counts VOLUNTARY sacrifices only. Paying a demand does not raise it: that amount is
-- Hashut's to name, and being punished for obedience reads as a bug.
EX.OFFER_COST  = 30
EX.OFFER_STEP  = 1.05
-- ...and a ceiling, or 5% compounding quietly kills the feature. At 1.05 the cap is reached
-- after 33 sacrifices; past that the price stops rising rather than climbing past anything a
-- player could hold, which would make the offerings view a wall of "Cannot".
EX.OFFER_MULT_MAX = 5.0
EX.SAVE_OFFERINGS = "zharr_offerings_made"

EX.OFFER_TURNS = 5
EX.SAVE_OFFER  = "zharr_offer_"

-- ===========================================================================================
-- LAYER 3: SHARES IN CHAOS DWARF FACTIONS.
-- ===========================================================================================
--
-- THE LIST IS DISCOVERED, NEVER HARDCODED. The ten modded houses live in the lords pack and
-- only under script/campaign/cr_combi_expanded/; this file ships in script/campaign/mod/ and
-- loads in EVERY campaign. Naming them here would put eleven permanently dead rows in a plain
-- Immortal Empires game. Discovery by culture instead: vanilla yields Astragoth, Drazhoath and
-- Zhatan and their minors, the lords pack adds the ten, and neither case needs a gate.
--
-- The culture key is NOT a new unvalidated string - it is already a key of EX.CULTURE_WANTS,
-- which check_lua_appetite asserts against the 26 vanilla cultures.
--
-- SINCE 2026-09-08 THIS IS A DEFAULT, NOT A CONSTANT. EX.bind_race overwrites it at EX.init
-- with the PLAYER's own culture, which is what generalises discovery and the guild to every
-- race - the logic below was always culture-generic and only the constant it read was not.

-- ===========================================================================================
-- THE COVERED RACES. Eight rows, and everything race-shaped in this file derives from them.
-- ===========================================================================================
--
-- `seg` IS THE SAVE-COMPATIBILITY MECHANISM, not a cosmetic field. Every key that carries
-- per-race text is built as EX.PREFIX .. EX.seg() .. <rest>, so the Chaos Dwarf empty string
-- reproduces the keys this mod has been shipping - derpy_chd_ex_offering_gems,
-- derpy_chd_ex_dem_tithe_gems - byte for byte. A live campaign holds those inside applied
-- effect bundles; renaming one orphans it mid-game with nothing on screen to say why.
--
-- `wrath` and `pleased` are CARRIED LITERALLY rather than derived, for the same reason: the
-- patron's name is already inside the Chaos Dwarf key, and deriving would produce
-- derpy_chd_ex_emp_hashut_wrath - both wrong, and a rename of the Chaos Dwarf one.
--
-- `boon_over` overrides EX.BOON for one commodity. Exotic Animals grants Chaos Dwarf
-- post-battle Labour, which the other seven races have no pool for: the bundle applies, the
-- effect moves nothing, and the panel advertises a number that never arrives.
--
-- LAYER 2 IS EMPTY FOR EVERYONE BUT CHAOS DWARFS. None of the other seven has a
-- chd_armaments analogue - skaven_food is FACTION scope but caps at 100 (a survival clock,
-- not a stockpile), emp_imperial_authority is the confederation currency,
-- wh3_main_cth_harmony is a balance rather than a pile, and the three added in
-- 2026-09-09 have none at all: the Dwarfs' oathgold and the elves' influence pools are
-- vanilla-absent, and a mod's pool cannot be a hard dependency of this one. That also means this build never
-- calls cm:faction_add_pooled_resource on a vanilla pool at all.
--
-- EVERY CULTURE KEY HERE IS CHECKED against the vanilla cultures table by check_race_table()
-- in tools/gen_zharr_exchange.py. A typo is otherwise permanent, total silence.
-- VANILLA ART, BY STEM. Everything the introduction draws comes out of
-- ui/campaign ui/effect_bundles/ - the same family this panel already paints its resource
-- icons from (see EX.INFO), so nothing new ships and nothing new is read off disk.
--
-- STEMS RATHER THAN WHOLE PATHS, so the folder is spelled once and check_intro_art() has a
-- list it can hold against the real ui.pack index. A missing image path draws a BLANK SQUARE
-- with no error and nothing in the log - a byte-grep would not have been proof either, which
-- is why the check enumerates the pack rather than searching it.
EX.ART_DIR = "ui/campaign ui/effect_bundles/"
function EX.art(stem)
    return EX.ART_DIR .. stem .. ".png"
end

EX.RACES = {
    ["wh3_dlc23_chd_chaos_dwarfs"] = {
        seg = "", name = "Zharr Exchange", offer_title = "Offerings to Hashut",
        patron = "Hashut", house_word = "A Chaos Dwarf house",
        -- THE FIRST LINE OF THE INTRODUCTION, and the only race-specific one. It answers
        -- "who am I and what kind of board is this" in a sentence, because that is the
        -- question a player has on the first opening and the guide answers a different one.
        -- Kept under 120 characters: it is printed into one 850px row cell, and text clips
        -- to its component with no error.
        intro = "You are the Chaos Dwarfs. The Zharr Exchange is the Forge's own market, and it is Hashut who takes the offerings.",
        -- AND THE HERALDRY THAT GOES BESIDE IT. One crest per race, from CA's own
        -- trait_* set, which happens to hold a shield for all eight of these and nothing
        -- this mod would have to draw.
        crest = "trait_chaos_dwarfs",
        wrath = "derpy_chd_ex_hashut_wrath", pleased = "derpy_chd_ex_hashut_pleased",
        layer2 = { "wh3_dlc23_chd_armaments", "wh3_dlc23_chd_raw_materials" } },
    ["wh_main_emp_empire"] = {
        seg = "emp_", name = "Imperial Bourse", offer_title = "Tithes to Sigmar",
        patron = "Sigmar", house_word = "An Imperial state",
        intro = "You are the Empire. The Imperial Bourse is slow and civil - dull, open through most wars, and the best paper here.",
        crest = "trait_human",
        wrath = "derpy_chd_ex_emp_sigmar_wrath", pleased = "derpy_chd_ex_emp_sigmar_pleased",
        boon_over = { res_animals = "+4 public order" },
        -- INSTITUTIONAL. A slow, deep, civil market: shocks are damped, it takes half again as
        -- much volume to move a price, the states are polite even when they dislike you, the
        -- Bourse stays open through wars that would shut a rougher market, a failed state is
        -- wound up in an orderly way - and the paper pays better than anyone else's, which is
        -- the trade: dull, and the best yield in the game.
        tune = { shock_gain = 0.5, shock_max = 0.7, div_yield = 1.5, hostile_max = 0.7,
                 demand_cooldown = 1.4, demand_chance = 0.7, guild_close = 1.3,
                 windup = 1.4, book_per_rung = 1.4, pressure_per_rung = 1.25 },
        layer2 = {} },
    ["wh3_main_cth_cathay"] = {
        seg = "cth_", name = "The Ivory Road", offer_title = "The Assessment",
        patron = "The Court", house_word = "A Cathayan house",
        intro = "You are Grand Cathay. The Ivory Road is regulated: the calmest and deepest board there is, and a thoroughly taxed one.",
        crest = "trait_cathay",
        wrath = "derpy_chd_ex_cth_court_wrath", pleased = "derpy_chd_ex_cth_court_pleased",
        boon_over = { res_animals = "+4 public order" },
        -- REGULATED. The deepest and calmest board of the four - the Court damps shocks harder
        -- than the Empire does and the books are so thick that cornering anything takes real
        -- money. What you pay for it is the Assessment: more often than anyone else's tithe
        -- and on a shorter cycle, because a regulated market is a taxed one.
        tune = { shock_gain = 0.4, shock_max = 0.6, div_yield = 1.2, hostile_max = 0.8,
                 demand_cooldown = 0.8, demand_chance = 1.2, guild_close = 1.2,
                 windup = 1.2, book_per_rung = 1.6, pressure_per_rung = 1.5 },
        layer2 = {} },
    ["wh2_main_skv_skaven"] = {
        seg = "skv_", name = "The Under-Market", offer_title = "The Council's Cut",
        patron = "The Council", house_word = "A Skaven clan",
        intro = "You are the Skaven. The Under-Market is what that implies - thin books, savage markups, and a dead clan leaves a corpse.",
        crest = "trait_skaven",
        wrath = "derpy_chd_ex_skv_council_wrath", pleased = "derpy_chd_ex_skv_council_pleased",
        boon_over = { res_animals = "+4 public order" },
        -- PREDATORY. Every dial that can cost you is turned up and every dial that pays you is
        -- turned down. A clan that hates you charges more than double the worst markup anyone
        -- else can reach; refusals are common rather than rare; a third of the book at war
        -- shuts the market; the board lurches on any disruption; the Council takes its cut
        -- nearly twice as often; and a clan that dies leaves you almost nothing, which is the
        -- backstab - the Under-Market has no orderly wind-up, only a corpse.
        --
        -- The books are THIN (book_per_rung down, not up), so clans move prices against you on
        -- volume the other races would not notice. That is the same lever from the other side.
        tune = { hostile_max = 2.2, refuse_share = 0.5, guild_close = 0.6,
                 shock_gain = 2.0, shock_max = 1.5, demand_chance = 1.83,
                 windup = 0.3, div_yield = 0.7, book_per_rung = 0.6,
                 pressure_per_rung = 0.75 },
        layer2 = {} },
    -- CATAPH'S SOUTHERN REALMS (Steam 2927296206, ships as !ak_teb3.pack). The culture key was
    -- read off a live campaign rather than off the store page - a faction of that mod answers
    -- culture() AND subculture() with the same string, which is not the usual shape and is the
    -- sort of thing a guess gets wrong silently and forever.
    --
    -- A SOFT DEPENDENCY, and it has to stay one. Every DB row this mod generates is keyed by
    -- our own prefix and the culture appears ONLY here, as a table key - so with the Southern
    -- Realms absent nothing ever matches it and the mod behaves exactly as it did before. The
    -- generator's check_no_foreign_keys() asserts that: the string must appear in zero DB rows
    -- and zero loc rows. Naming one of their factions or tables in a row is what would turn
    -- this into a required dependency, and the check is there to stop that happening later.
    ["mixer_teb_southern_realms"] = {
        seg = "teb_", name = "Merchant Compact", offer_title = "Consigned to the Temple",
        patron = "Myrmidia", house_word = "A Southern Realms city",
        intro = "You are the Southern Realms. The Merchant Compact is a bankers' board - the most liquid here, and it feels every sack.",
        -- THE EMPIRE'S CREST, BORROWED, exactly as the event-feed art is: Cataph's
        -- Southern Realms ships no crest of its own, and the choice is between another
        -- human culture's shield and a path that draws a blank square in silence.
        crest = "trait_human",
        wrath = "derpy_chd_ex_teb_myrmidia_wrath",
        pleased = "derpy_chd_ex_teb_myrmidia_pleased",
        boon_over = { res_animals = "+4 public order" },
        -- BANKERS. The most liquid and most forgiving board in the game and the one that
        -- almost never shuts: the Compact deals with everyone, refuses almost nobody, keeps
        -- trading through wars that would close a rougher market, and winds a failed house up
        -- through receivers rather than leaving a corpse. What it pays for that is exposure -
        -- a mercantile economy feels every sack and every siege, so shocks land harder here
        -- than anywhere. Myrmidia asks less than the other patrons do.
        tune = { hostile_max = 0.5, refuse_share = 1.6, guild_close = 1.5,
                 book_per_rung = 1.5, pressure_per_rung = 1.5, div_yield = 1.4,
                 windup = 1.6, shock_gain = 1.6, shock_max = 1.3,
                 demand_chance = 0.8 },
        layer2 = {} },
    ["wh_main_dwf_dwarfs"] = {
        seg = "dwf_", name = "The Long Ledger", offer_title = "Offered to Grungni",
        -- GRUNGNI, NOT "THE ANCESTORS". The patron string is a grammatical SUBJECT in five
        -- places - "<patron> grants" in the Offerings header, "<patron> demands 8 Iron",
        -- "<patron> has no use for these" - and every one of them is third-person singular.
        -- A plural collective reads as "The Ancestors grants" and there is no branch anywhere
        -- that would notice. Grungni is the Ancestor God of the mine and the forge in any
        -- case, which is a better patron for a commodities market than the whole line of them.
        patron = "Grungni", house_word = "A Dwarf hold",
        intro = "You are the Dwarfs. The Long Ledger is a vault: slow, hard to get into, and a hold that fails still pays what it owes.",
        crest = "trait_dwarf",
        wrath = "derpy_chd_ex_dwf_ancestors_wrath",
        pleased = "derpy_chd_ex_dwf_ancestors_pleased",
        boon_over = { res_animals = "+4 public order" },
        -- THE VAULT. The safest board in the game and the hardest to get into, and the two
        -- are the same fact: a Dwarf who dislikes you does not charge you more, he declines
        -- to trade and writes it down. So hostile_max goes DOWN and refuse_share with it -
        -- a grudge is expressed as a closed gate, not a markup.
        --
        -- windup 1.8 is the headline and the exact inverse of the Under-Market: a hold that
        -- fails pays its debts, so backing a loser here costs you almost nothing. What you
        -- pay for that is the yield, which is the worst on the board - holds hoard, they do
        -- not distribute - and the gates, which shut early in a war.
        tune = { windup = 1.8, hostile_max = 0.6, refuse_share = 0.5, guild_close = 0.5,
                 div_yield = 0.6, book_per_rung = 1.5, pressure_per_rung = 1.5,
                 shock_gain = 0.6, shock_max = 0.7,
                 demand_cooldown = 1.6, demand_chance = 0.7 },
        layer2 = {} },
    ["wh2_main_hef_high_elves"] = {
        seg = "hef_", name = "The Emerald Gate", offer_title = "Tribute to Asuryan",
        -- ASURYAN RATHER THAN "THE PHOENIX COURT", and the reason is a measured ceiling
        -- rather than taste. check_help_lines substitutes the LONGEST patron name into the
        -- guide's offering line and measures it: at 17 characters the line reached ~636px in
        -- a 620px column and would have clipped mid-sentence with no error. The split is the
        -- Empire's - the patron who receives the offering is a god, the institution that
        -- notices is the Court, and the tier and wrath titles still say so.
        patron = "Asuryan", house_word = "An Elven kingdom",
        intro = "You are the Asur. The Emerald Gate is old money: the deepest books there are, no refusals, and a price for being you.",
        crest = "trait_high_elves",
        wrath = "derpy_chd_ex_hef_phoenix_wrath",
        pleased = "derpy_chd_ex_hef_phoenix_pleased",
        boon_over = { res_animals = "+4 public order" },
        -- THE DEEPEST AND MOST EXPENSIVE BOARD. An Elf does not decline commerce; an Elf
        -- sets a price. refuse_share goes UP and hostile_max goes up with it, which is the
        -- opposite pairing to the Dwarfs and says the same thing about the race from the
        -- other side: they will always deal with you, and being what you are has a price.
        --
        -- div_yield is deliberately UNDER the Imperial Bourse's 1.5. Ulthuan is old money and
        -- pays well, but the Empire keeps the best-yield title it has shipped with, because
        -- two races tied for a superlative is two races with no superlative.
        tune = { book_per_rung = 1.8, pressure_per_rung = 1.6, refuse_share = 1.5,
                 hostile_max = 1.2, guild_close = 1.4, div_yield = 1.3, windup = 1.2,
                 shock_gain = 0.7, shock_max = 0.8,
                 demand_cooldown = 1.4, demand_chance = 0.6 },
        layer2 = {} },
    ["wh2_main_def_dark_elves"] = {
        seg = "def_", name = "The Black Ark Market", offer_title = "Given to the Temple",
        patron = "Khaine", house_word = "A Dark Elf city",
        intro = "You are the Druchii. The Black Ark Market pays well right up to the turn a city falls and you are left a fifth of it.",
        crest = "trait_dark_elves",
        wrath = "derpy_chd_ex_def_khaine_wrath",
        pleased = "derpy_chd_ex_def_khaine_pleased",
        boon_over = { res_animals = "+4 public order" },
        -- RICH AND PREDATORY, WHICH IS NOT THE SKAVEN. The Under-Market is predatory AND
        -- POOR - thin books, a board that lurches on any disruption - and a Dark Elf profile
        -- built the same way would be a reskin. So book_per_rung goes UP: Naggaroth has real
        -- wealth, and the depth is the difference.
        --
        -- The robbery is at the END rather than throughout. div_yield UP and windup DOWN is
        -- the whole race in two numbers: slave-worked cities pay handsomely right up to the
        -- turn one is sacked, and then you get a fifth of your money back. Every other race
        -- pays you less and hands more of it back.
        --
        -- hostile_max stays UNDER the Skaven's 2.2 on purpose. They keep the gouging crown;
        -- these are expensive, not extortionate.
        tune = { div_yield = 1.3, windup = 0.4, book_per_rung = 1.3, hostile_max = 1.8,
                 refuse_share = 0.7, guild_close = 0.7,
                 shock_gain = 1.4, shock_max = 1.2,
                 demand_chance = 1.4, demand_cooldown = 0.8 },
        layer2 = {} },
}

-- WHAT A RACE PROFILE MAY MOVE, AND HOW FAR THE RESULT MAY GO.
--
-- A profile entry is a MULTIPLIER on whatever the difficulty preset and MCT have already
-- resolved, not a replacement for it - so Skaven aggression composes with Hard rather than
-- being erased by it. That is the whole reason it is a factor: a race that set absolute values
-- would flatten every preset but `default`, and the flavour would silently vanish for anyone
-- who moved the difficulty.
--
-- THE WHITELIST IS THE SAFETY RAIL. `spread`, `ladder_step`, `sell_floor` and `friendly_max`
-- are DELIBERATELY ABSENT: those four are the round-trip algebra check_spread() guards, and a
-- race factor on any of them can mint gold the way the `easy` preset silently did for months.
-- A key not in this table is inert - and the generator's check_race_tune() refuses to build if
-- a profile names one, so "inert" never has to be discovered in play.
--
-- THE BOUNDS ARE NOT DECORATION. Multiplying compounds: `ultra` already sets hostile_max 0.60,
-- and the Skaven 2.2 on top of it is 1.32 - a buy at 2.32x the world price, which is not a
-- market, it is a wall. Every pair is sized to contain every preset x race product, with the
-- extremes clamped rather than allowed; check_race_tune() prints which combinations clamp.
-- HOW MUCH OF THE PROFILE THE PLAYER WANTS. 0 switches race profiles off entirely and every
-- board becomes the shared baseline; 1 is the profile as designed; 2 doubles every departure
-- from it. It scales the DISTANCE FROM 1, not the factor - 1 + (f - 1) * strength - so a knob
-- the profile does not touch stays untouched at every strength, and a x0.6 and a x1.4 soften
-- and sharpen symmetrically instead of one of them collapsing toward zero.
--
-- Between this and the per-knob base sliders under Custom, every final number is reachable: set
-- the strength to 0 and the sliders mean exactly what they say again.
--
-- IT MUST NEVER BE ADDED TO EX.RACE_TUNABLE. EX.race_factor reads it through EX.opt, and
-- EX.race_apply returns early for a key that is not in that table - which is the only thing
-- stopping the read from recursing into itself. check_race_tune() asserts the exclusion.
EX.RACE_STRENGTH = 1.0

EX.RACE_TUNABLE = {
    hostile_max       = { 0.05, 0.75 },
    refuse_share      = { 0.15, 0.95 },
    guild_close       = { 0.20, 1.00 },
    shock_gain        = { 1,    40   },
    shock_max         = { 1,    14   },
    demand_chance     = { 1,    100  },
    demand_cooldown   = { 3,    60   },
    windup            = { 0.05, 1.00 },
    div_yield         = { 0.005, 0.08 },
    book_per_rung     = { 5,    100  },
    pressure_per_rung = { 2,    16   },
}

-- WHICH RACE THE PLAYER IS, resolved once at EX.init. nil means uncovered, which is the
-- majority case: 23 of the game's 27 cultures.
EX.race = nil

-- EVERY ONE OF THESE READS THE SUBJECT, NOT THE LOCAL PLAYER. In singleplayer those are the
-- same faction and always were. In multiplayer the turn round binds each human in turn (see
-- EX.with_player), and a tithe demanded of the Empire player must resolve Sigmar's bundles and
-- the emp_ message segment on EVERY machine - including the one sitting in Zharr-Naggrund.
-- EX.race stays what it always was, the LOCAL player's row, because bind_race writes the
-- panel's own header and tooltip literals out of it and those are per-client by definition.
EX.culture_cache = {}

function EX.culture_of(faction)
    if not faction then return nil end
    local c = EX.culture_cache[faction]
    if c == nil then
        c = ""
        pcall(function()
            local f = cm:get_faction(faction)
            if f and not f:is_null_interface() then c = f:culture() or "" end
        end)
        EX.culture_cache[faction] = c
    end
    return (c ~= "") and c or nil
end

-- THE LOCAL SHORTCUT IS LOAD-BEARING FOR THE HARNESSES, not an optimisation. Several checks in
-- gen_zharr_exchange.py steer this file by assigning EX.race directly against a stub that has
-- no faction list to read a culture out of; without this branch every one of them would fall
-- through to nil and silently test the uncovered path instead of the race they set.
-- NIL COUNTS AS LOCAL. EX.who() answers nil before the first tick and in any harness with no
-- faction stub, and EX.race is then the only answer there is - falling through to a culture
-- lookup on nil would report "uncovered" and quietly lock the Offerings tab on a race that is
-- plainly bound. _nav_harness.lua sets EX.race directly and does exactly this.
function EX.race_of(faction)
    if EX.race ~= nil and (faction == nil or faction == EX.local_faction) then
        return EX.race
    end
    local c = EX.culture_of(faction)
    return (c and EX.RACES[c]) or nil
end

function EX.rc() return EX.race_of(EX.who()) end

function EX.covered() return EX.rc() ~= nil end
function EX.seg()    local r = EX.rc(); return (r and r.seg) or "" end
-- "The altar" rather than "Hashut" for an uncovered player. Nothing patron-flavoured is
-- reachable there - the Offerings tab is locked and no demand fires - but a fallback naming
-- another race's god is the sort of thing that surfaces in a screenshot eventually.
function EX.patron()     local r = EX.rc(); return (r and r.patron) or "The altar" end
function EX.house_word() local r = EX.rc(); return (r and r.house_word) or "A rival house" end
function EX.boon(res)
    local r = EX.rc()
    local o = r and r.boon_over
    return (o and o[res]) or EX.BOON[res]
end
function EX.wrath_bundle()   local r = EX.rc(); return (r and r.wrath) or EX.WRATH_BUNDLE end
function EX.pleased_bundle() local r = EX.rc(); return (r and r.pleased) or EX.PLEASED_BUNDLE end

-- ==========================================================================================
-- MULTIPLAYER. Read this before touching anything that spends gold or moves goods.
--
-- THREE RULES, and CA states all three - campaign_manager.html "Local Player Faction", and
-- campaignui.html "Multiplayer UI Events":
--
--  1. cm:get_local_faction_name() THROWS A SCRIPT ERROR in a multiplayer campaign unless true
--     is passed to force the result. Every call in this file now goes through EX.me(), which
--     passes it. Before that, this mod did not desync in multiplayer - it DIED at first tick,
--     inside cm:process_first_tick_callbacks, whose call_each has no pcall, taking every mod
--     queued behind it down with no log line naming us. That is the fault this section fixes
--     first, because until it is fixed none of the rest can even run.
--
--  2. A model change made on one machine and not the others IS a desync. So nothing that
--     spends gold, moves a pooled resource or applies an effect bundle may run straight off a
--     UI click. Clicks go through EX.mp_send, which broadcasts with
--     CampaignUI.TriggerCampaignScriptEvent and lets the resulting UITrigger - which CA
--     delivers to every machine, in one order - apply the identical mutation everywhere.
--
--  3. Anything scoped to "the local player" names a DIFFERENT faction on each machine. So the
--     turn round walks cm:get_human_factions(), which answers the same list everywhere, and
--     never asks who this client happens to be.
--
-- SINGLEPLAYER RUNS THE SAME CODE, deliberately and not as a courtesy. EX.humans() is a
-- one-entry list, the subject is always that entry, and EX.mp_send calls the op directly
-- instead of broadcasting. So every line below is exercised by ordinary singleplayer play
-- except the transport itself - which is the one thing that cannot be exercised without a
-- second machine, and is therefore the one thing to suspect first if multiplayer misbehaves.
--
-- NOT VERIFIED IN A MULTIPLAYER CAMPAIGN. Built 2026-09-09 against CA's documentation and the
-- lua.exe harnesses; no two-machine run has happened. Do not read the care taken here as
-- evidence that it works.
-- ==========================================================================================

EX.local_faction = nil

-- THE CLIENT'S OWN FACTION, forced and cached. Forced because rule 1 above; cached because it
-- cannot change inside a session and the forced form is the one CA warns about.
function EX.me()
    if EX.local_faction then return EX.local_faction end
    local ok, n = pcall(function() return cm:get_local_faction_name(true) end)
    if ok and type(n) == "string" and n ~= "" then EX.local_faction = n end
    return EX.local_faction
end

-- IS THIS A MULTIPLAYER CAMPAIGN. Used for exactly two decisions - which transport EX.mp_send
-- takes, and whether an unscoped saved key may be migrated - and for nothing else. No rule,
-- price or payout in this mod branches on it.
function EX.is_mp()
    local ok, v = pcall(function() return cm:is_multiplayer() end)
    return ok and v == true
end

-- EVERY HUMAN FACTION, SORTED.
--
-- SORTED IS NOT TIDINESS. This list decides the order positions settle in and which faction
-- the AI houses front-run; CA promises no order from get_human_factions, so two machines
-- walking it as returned could diverge on turn one. table.sort on faction keys is the same
-- answer everywhere.
--
-- IDLE HUMANS STAY IN. CA includes factions whose player has dropped, and that is what we
-- want: their warehouse still charges rent and their paper still settles, so the campaign a
-- returning player comes back to is the one they left.
EX.human_list = nil

function EX.humans()
    if EX.human_list then return EX.human_list end
    local t = {}
    pcall(function()
        for _, k in ipairs(cm:get_human_factions() or {}) do
            if type(k) == "string" and k ~= "" then t[#t + 1] = k end
        end
    end)
    -- THE FALLBACK IS FOR THE HARNESSES, and for a stub with no human list. It is never the
    -- multiplayer answer: EX.me() is a different string on each machine, so if this branch
    -- were ever taken in a real multiplayer game every machine would walk a different round.
    if #t == 0 then
        local me = EX.me()
        if me then t[1] = me end
    end
    table.sort(t)
    EX.human_list = t
    return t
end

-- Rebuilt at the top of every round rather than cached for the session: a player can drop or
-- resume, and a confederation can end a human faction outright.
function EX.forget_humans() EX.human_list = nil end

function EX.is_human(faction)
    if not faction then return false end
    for _, k in ipairs(EX.humans()) do if k == faction then return true end end
    return false
end

-- ------------------------------------------------------------------------------------------
-- THE SUBJECT, and the one piece of cleverness in this file. It is deliberate and it is fenced.
--
-- ponytail: EX.shares_held, EX.LOG, EX.offer_until and the five demand values are read from
-- about sixty places that all mean "the player", plus thirteen lua.exe harnesses that assign
-- them directly. Threading a faction argument through all of that is a far larger and far
-- riskier diff than SWAPPING WHICH PLAYER THOSE NAMES POINT AT, so they stay exactly where
-- they are and EX.bind_player moves the set to another faction's slice.
--
-- THE CEILING, stated plainly: nothing may mutate those names while no subject is bound, and
-- nothing may interleave two subjects. Both hold because every mutation happens inside
-- EX.with_player, which is also where the pcall lives that stops an error stranding the wrong
-- subject for the rest of the campaign. check_lua_mp_slices() asserts the two name lists below
-- still match what EX.restore actually restores, which is the way this drifts.
-- Upgrade path if the fence ever breaks: two-level tables keyed by faction.
-- ------------------------------------------------------------------------------------------

EX.SLICE_TABLES  = { "shares_held", "offer_until", "LOG", "orders", "deals" }
EX.SLICE_SCALARS = { "offerings_made", "demand_turn", "demand_res", "demand_tier", "demand_due" }
-- demand_res and demand_tier are absent on purpose: nil IS their cleared state, and a table
-- literal cannot carry a nil value anyway.
EX.SLICE_ZERO    = { offerings_made = 0, demand_turn = 0, demand_due = 0 }

EX.slices  = {}
EX.subject = nil

function EX.who() return EX.subject or EX.me() end

function EX.slice(faction)
    if not faction then return nil end
    local s = EX.slices[faction]
    if not s then
        s = {}
        for _, k in ipairs(EX.SLICE_TABLES)  do s[k] = {} end
        for _, k in ipairs(EX.SLICE_SCALARS) do s[k] = EX.SLICE_ZERO[k] end
        EX.slices[faction] = s
    end
    return s
end

-- THE FILE-SCOPE TABLES ARE THE LOCAL PLAYER'S SLICE, adopted rather than replaced. Adopting
-- them keeps every harness that assigns EX.shares_held directly working, and makes the
-- singleplayer path allocation-for-allocation what it was before this section existed.
function EX.adopt_local()
    local me = EX.me()
    if not me or EX.subject then return end
    local s = {}
    for _, k in ipairs(EX.SLICE_TABLES)  do s[k] = EX[k] or {} end
    for _, k in ipairs(EX.SLICE_SCALARS) do s[k] = EX[k] end
    EX.slices[me] = s
    EX.subject = me
end

function EX.bind_player(faction)
    -- ADOPT FIRST, AND THIS IS NOT BELT AND BRACES. Without it the very first bind has no
    -- previous subject to save into, so the live tables are dropped on the floor and replaced
    -- by an empty slice - and binding back to nil afterwards leaves them pointing at that
    -- slice rather than at what was there before. EX.init calls adopt_local so the game never
    -- reaches here unbound, but the thirteen lua.exe harnesses do: they assign EX.shares_held
    -- directly and then call EX.trade, and the first version of this silently zeroed the
    -- position they had just seeded. A buy against a house at war then "went through", because
    -- the holding it was compared against had been thrown away rather than because the war
    -- gate had failed - a check reporting the wrong bug, which is worse than no check.
    EX.adopt_local()
    local prev = EX.subject
    -- NO LOCAL FACTION MEANS NO GAME AND NOTHING TO SWAP. Leaving the live tables alone is the
    -- only safe answer; replacing them with an empty slice would be the fault described above.
    if not prev then return nil end
    if prev then
        local s = EX.slice(prev)
        for _, k in ipairs(EX.SLICE_TABLES)  do s[k] = EX[k] end
        for _, k in ipairs(EX.SLICE_SCALARS) do s[k] = EX[k] end
    end
    EX.subject = faction
    if faction then
        local s = EX.slice(faction)
        for _, k in ipairs(EX.SLICE_TABLES)  do EX[k] = s[k] end
        for _, k in ipairs(EX.SLICE_SCALARS) do EX[k] = s[k] end
    end
    -- THE GUILD HOLD IS A MEMO OF ONE SUBJECT'S DIPLOMACY, so it cannot survive a change of
    -- subject. EX.stance_of reads diplomatic standing WITH THE PLAYER; a hold built while the
    -- panel was refreshing for this client would otherwise price another player's trade off
    -- this client's treaties - and only on the machine that happened to have the panel open,
    -- which is a desync that appears and disappears with a UI action.
    EX.guild_hold = nil
    return prev
end

-- THE ONLY SANCTIONED WAY TO ACT AS SOMEBODY ELSE, and the pcall is the whole point: an error
-- raised halfway through one player's pass must not leave their slice bound for the rest of
-- the campaign, which would quietly credit every later payout to the wrong faction.
function EX.with_player(faction, fn)
    local prev = EX.bind_player(faction)
    local ok, err = pcall(fn)
    EX.bind_player(prev)
    if not ok then
        EX.say("error", "pass for " .. tostring(faction) .. " failed: " .. tostring(err))
    end
    return ok
end

-- ------------------------------------------------------------------------------------------
-- PER-PLAYER SAVED KEYS CARRY THE FACTION.
--
-- EX.store is one table written into the savegame, and in multiplayer that save is shared:
-- two players' positions under one key is a wrong number AND, because every machine writes
-- the whole store, a divergent save on the next load.
--
-- WORLD KEYS STAY UNSCOPED, on purpose - the rungs, the price history, the shocks, the AI
-- books, the house list, the delisted marks that are per-player and the settings snapshot that
-- is not. Getting that split wrong in either direction is silent: scope a world key and the
-- market forks per player, share a player key and they rob each other.
-- ------------------------------------------------------------------------------------------

function EX.pkey(key, faction) return key .. "@" .. tostring(faction or EX.who()) end

function EX.setp(key, value, faction) EX.setv(EX.pkey(key, faction), value) end

-- THE MIGRATION GUARD IS NOT DECORATION. A campaign saved before this build holds these values
-- under the UNSCOPED key, and reading them back is right when there is exactly one human -
-- which is every such save, because the mod could not survive first tick in multiplayer
-- before today. With two humans the same fallback would hand player B player A's position,
-- and would do it identically on both machines, so it would not even announce itself as a
-- desync. It would just be theft.
function EX.getp(key, faction)
    local v = EX.store[EX.pkey(key, faction)]
    if v ~= nil then return v end
    if #EX.humans() == 1 then return EX.getv(key) end
    return nil
end

-- ------------------------------------------------------------------------------------------
-- THE TRANSPORT. One tagged string over CampaignUI.TriggerCampaignScriptEvent, unpacked by a
-- UITrigger listener on every machine.
-- ------------------------------------------------------------------------------------------

EX.MP_TAG = "zx1"

-- op name -> function(arg), run with the acting player bound. Every one of these takes the
-- faction it acts on from the binding rather than reading the local player, because on most
-- machines receiving it the acting player is somebody else. Filled in beside the actions
-- themselves - EX.trade, EX.offer, EX.pay_demand - so an op and its validation stay together.
EX.MP_OPS = {}

-- CQI -> FACTION, over the human list alone. Only a human can originate one of these, the list
-- is at most eight long, and walking it avoids depending on the exact spelling of an undocumented
-- model lookup - faction_for_command_queue_index is listed in CA's interface index with no
-- signature anywhere in the docs.
function EX.faction_by_cqi(cqi)
    if not cqi then return nil end
    local found = nil
    pcall(function()
        for _, k in ipairs(EX.humans()) do
            local f = cm:get_faction(k)
            if f and not f:is_null_interface() and f:command_queue_index() == cqi then
                found = k
                return
            end
        end
    end)
    return found
end

-- SEND, OR JUST DO IT. Singleplayer calls the op directly - same function, same argument, same
-- order - so the only thing multiplayer does differently is the round trip through the network.
function EX.mp_send(op, arg)
    local faction = EX.me()
    if not faction then return end
    if not EX.MP_OPS[op] then
        EX.say("error", "no mp op named " .. tostring(op))
        return
    end
    if not EX.is_mp() then
        EX.mp_apply(faction, op, arg)
        return
    end
    local cqi = nil
    pcall(function()
        local f = cm:get_faction(faction)
        if f and not f:is_null_interface() then cqi = f:command_queue_index() end
    end)
    -- REFUSE RATHER THAN FALL BACK. A local apply here would move gold on one machine only,
    -- which is the exact fault this whole section exists to prevent - better a click that
    -- visibly does nothing and says why in the log.
    if not cqi then
        EX.say("error", "no command_queue_index for " .. faction .. " - " .. op .. " not sent")
        return
    end
    -- Both arguments or neither, per CA. The faction rides on the cqi; the op and its one
    -- argument ride in the id string, which is ours to shape.
    pcall(function()
        CampaignUI.TriggerCampaignScriptEvent(cqi,
            EX.MP_TAG .. "|" .. op .. "|" .. tostring(arg or ""))
    end)
end

function EX.mp_apply(faction, op, arg)
    local fn = EX.MP_OPS[op]
    if not fn or not faction then return end
    EX.with_player(faction, function() fn(arg) end)
end

-- RESOLVED AT EX.init, NOT AT FILE SCOPE. A local-faction call at script root hard-crashes
-- past pcall - see the banner at the top of this file - and this reads the local faction
-- through EX.me(). It is safe where init calls it: the first tick has been and gone by then,
-- which is also the point CA says the local-faction accessors become legal at all.
--
-- IDEMPOTENT. init has two entry points (ScriptEventFirstTickAfterWorldCreated and the
-- first-tick callback list) and EX.inited makes the second a no-op, but a future third caller
-- must not be able to accumulate anything - which is why LAYER2 is ASSIGNED, never appended.
--
-- FAILS TO UNCOVERED. cm:get_faction returns FALSE - not nil - for a name it does not know,
-- and a null interface answers only is_null_interface. Either way the player keeps Layer 1
-- and the panel, which is the shipped behaviour for every race but one.
function EX.bind_race()
    -- CLEARED FIRST, ALWAYS. EX.culture_of memoises, and this function's whole job is to read
    -- cultures fresh: at init it runs before anything else has looked one up, but it is also
    -- idempotent by contract and _race_harness.lua rebinds the same faction key through all
    -- five races in one process. A stale entry there pinned every race to whichever one was
    -- read first, and the symptom was the Southern Realms drawing the Chaos Dwarf feed index -
    -- caught by check_race_bind, which is exactly the fault it was written for.
    EX.culture_cache = {}
    local culture = EX.culture_of(EX.me()) or ""
    EX.race = EX.RACES[culture]
    if culture ~= "" then EX.HOUSE_CULTURE = culture end

    -- THE HOUSE CULTURES AND LAYER 2 ARE THE UNION ACROSS EVERY HUMAN, not this client's.
    --
    -- WHY A UNION AND NOT A PER-PLAYER LIST. EX.instruments() is the row list, and the row list
    -- is what EX.restore, EX.apply_prices and EX.remember_all iterate to keep the WORLD price
    -- tables. A per-player instrument list would fork the price ladder itself: two machines
    -- would walk different rows, save different rungs, and the market would stop being one
    -- market. So every machine keeps one list covering everyone, and the panel does the
    -- narrowing at draw time - which is where a per-player difference belongs.
    --
    -- In singleplayer the union is one culture and one layer-2 pair, so this is exactly what
    -- it always was.
    EX.HOUSE_CULTURES = {}
    local l2, seen = {}, {}
    for _, f in ipairs(EX.humans()) do
        local c = EX.culture_of(f)
        if c then EX.HOUSE_CULTURES[c] = true end
        local r = EX.RACES[c or ""]
        for _, k in ipairs((r and r.layer2) or {}) do
            if not seen[k] then seen[k] = true; l2[#l2 + 1] = k end
        end
    end
    if culture ~= "" then EX.HOUSE_CULTURES[culture] = true end

    -- THE TRADING BLOCS ANY HUMAN BELONGS TO, and a UNION for the same reason the line above
    -- is one. EX.is_house_culture decides which factions become instruments, so it feeds
    -- EX.instruments() - the list EX.restore, EX.apply_prices and EX.remember_all all walk to
    -- keep the WORLD price tables. Reading the LOCAL player's bloc there would fork the row
    -- list per machine, which forks the price ladder, which is the one thing the comment above
    -- EX.HOUSE_CULTURES exists to prevent. Built here, once, from the same EX.humans() walk.
    --
    -- In singleplayer this is one bloc, so the gate collapses to "my bloc or the wildcard".
    EX.BLOCS = {}
    for _, f in ipairs(EX.humans()) do
        local b = EX.BLOC[EX.culture_of(f) or ""]
        if b then EX.BLOCS[b] = true end
    end
    local mine = EX.BLOC[culture]
    if mine then EX.BLOCS[mine] = true end

    -- Sorted so two machines that discovered their humans in a different order still hand
    -- EX.instruments() the same row order, and therefore the same panel slot per instrument.
    table.sort(l2)
    EX.LAYER2 = l2

    -- THE PATRON'S NAME ON SCREEN, written into the tables AFTER the bind. EX.HEADERS,
    -- EX.TIPS and EX.HELP_PAGES are file-scope literals: they are constructed before any
    -- faction exists, so they cannot read EX.race at construction, and the alternative - a
    -- format string resolved at draw time - would put the same substitution in five separate
    -- render paths.
    --
    -- THE CHAOS DWARF VALUES REPRODUCE THE SHIPPED LITERALS EXACTLY, which is what keeps
    -- check_header_labels, check_tooltips and check_help_lines measuring real text: all three
    -- read this file statically and none of them ever calls bind_race.
    local who = EX.patron()
    EX.HEADERS.offer.hdr_trend = who .. " grants"
    EX.TIPS.offer.hdr_trend    = "What " .. who .. " grants while the offering lasts."
    -- THE HOUSE COLUMN TOOLTIP IS NO LONGER PER-RACE. Before trade blocs the column held one
    -- culture, so EX.house_word() described every row in it; since 2026-09-11 it holds your
    -- own people AND your bloc's, and "A Chaos Dwarf house" was a flat lie on two thirds of
    -- the board. The literal in EX.TIPS is race-neutral now and nothing overwrites it here.
    -- EX.house_word() moved to the guild line below, which is the one place it is still true.
    EX.HELP_PAGES[1][EX.HELP_OFFER_LINE][2] =
        "Burn " .. EX.OFFER_COST .. " units for " .. who .. "'s favour, "
        .. EX.OFFER_TURNS .. " turns - the quick way. Holding is the slow one."
    EX.HELP_PAGES[2][EX.HELP_GUILD_LINE][2] =
        EX.house_word() .. " trades here - so do your bloc's. One is across every deal."
end

-- THE SHIPPED DEFAULT, and it is Chaos Dwarf on purpose. EX.bind_race overwrites it at
-- EX.init; until then - and in every generator harness that loads this file without calling
-- init - the whole file behaves exactly as it did before EX.RACES existed. That is what makes
-- this change invisible to the twenty-odd checks that run the shipped Lua against stubs.
EX.HOUSE_CULTURE = "wh3_dlc23_chd_chaos_dwarfs"

-- THE SET FORM, and the one every walk actually reads. EX.HOUSE_CULTURE above survives as the
-- LOCAL player's culture because the panel and two harnesses name it; the region walks and the
-- house discovery read this instead, because in multiplayer "a house" means a faction of any
-- human's culture, not of this client's.
EX.HOUSE_CULTURES = { [EX.HOUSE_CULTURE] = true }

-- THE BLOCS ANY HUMAN BELONGS TO. Empty until EX.bind_race builds it, and empty is the SAFE
-- default rather than a placeholder: with no bloc known the gate below falls through to
-- own-culture-only, which is byte-for-byte the behaviour this file shipped before blocs
-- existed. That is what keeps the twenty-odd checks that load this file without calling
-- bind_race measuring the same thing they always did.
EX.BLOCS = {}

-- ===========================================================================================
-- TRADING BLOCS - who may hold paper in whom.
-- ===========================================================================================
--
-- WH3 HAS NO ORDER/DESTRUCTION ANYWHERE IN ITS DATA. cultures_tables carries eight columns and
-- none is an alliance; factions_tables carries sixty and none is either; and CA's own script
-- docs have no grand_alliance, alliance_group or faction_group. Checked 2026-09-11. The split
-- below is authored, and it is authored on TRADE rather than on morality - who would actually
-- do business with whom.
--
-- EVERY KEY HERE IS ALSO A KEY OF EX.CULTURE_WANTS, which check_lua_appetite already holds
-- against the vanilla cultures table. check_bloc() in tools/gen_zharr_exchange.py asserts the
-- subset, so a typo fails the build instead of failing silently forever.
--
-- "any" IS A WILDCARD, NOT A THIRD BLOC. It joins every board and sees every board, because
-- these five are the setting's merchant and mercenary cultures: Clan Eshin and Skryre sell to
-- Empire nobles, Cathay pays the Ogres in gold, Sartosa and Tilea deal with whoever pays. It
-- is also what gives the Chaos Dwarfs their arms-dealer reach WITHOUT a special case - a CHD
-- player reaches Skaven, Ogres, the Coast and Tilea through this row and not through an
-- exemption in the gate.
--
-- A CULTURE ABSENT FROM THIS TABLE IS NOT AN INVESTMENT FOR OUTSIDERS, and that is the whole
-- of it - it is NOT locked out. Branch 1 of EX.is_house_culture tests the player's own culture
-- first, so a Beastmen or Lizardmen player keeps their own houses, their own guild and the
-- entire commodity market, exactly as today. Beastmen have herdstones rather than an economy,
-- daemons have no economy at all, and the Slann have no concept of commerce.
--
-- WOOD ELVES ARE IN, and the argument is internal rather than lore. Athel Loren proper is
-- isolationist, but EX.CULTURE_WANTS already has them bidding dyes at 0.8 and medicine at 0.5
-- and selling iron, marble and timber - they are already a counterparty on Layer 1. Excluding
-- them from Layer 3 while they bid on Layer 1 is this mod arguing with itself, which is the
-- exact failure the Southern Realms note in EX.CULTURE_WANTS warns about. CA also ships two
-- Laurelorn factions, and the Eonir trade with the Empire and Marienburg in canon.
--
-- mixer_teb_southern_realms IS A MODDED CULTURE. Vanilla TEB maps to wh_main_emp_empire
-- through wh_main_sc_teb_teb, so this row is inert unless Mixu's TEB is loaded. Harmless.
EX.BLOC = {
    -- ORDER - the treaty web.
    ["wh_main_emp_empire"]        = "order",
    ["wh_main_brt_bretonnia"]     = "order",
    ["wh_main_dwf_dwarfs"]        = "order",
    ["wh2_main_hef_high_elves"]   = "order",
    ["wh_dlc05_wef_wood_elves"]   = "order",
    ["wh3_main_cth_cathay"]       = "order",
    ["wh3_main_ksl_kislev"]       = "order",
    ["wh3_main_pro_ksl_kislev"]   = "order",
    -- DESTRUCTION - the slaver and arms web. Naggaroth to Zharr-Naggrund is a real canon
    -- trade route in slaves, iron and weapons, which is the strongest single link the Chaos
    -- Dwarf player has and it lands inside their own bloc.
    ["wh_main_grn_greenskins"]    = "destr",
    ["wh_dlc08_nor_norsca"]       = "destr",
    ["wh_main_chs_chaos"]         = "destr",
    ["wh2_main_def_dark_elves"]   = "destr",
    ["wh3_dlc23_chd_chaos_dwarfs"] = "destr",
    -- ANY - the merchant races, in both blocs.
    ["wh2_main_skv_skaven"]       = "any",
    ["wh3_main_ogr_ogre_kingdoms"] = "any",
    ["mixer_teb_southern_realms"] = "any",
    -- ABSENT, deliberately: wh2_main_lzd_lizardmen, wh_dlc03_bst_beastmen,
    -- wh3_main_kho_khorne, wh3_main_tze_tzeentch, wh3_main_sla_slaanesh,
    -- wh3_main_nur_nurgle, wh3_main_dae_daemons, and THE FOUR UNDEAD CULTURES -
    -- wh2_dlc09_tmb_tomb_kings, wh_main_vmp_vampire_counts, wh2_dlc11_cst_vampire_coast,
    -- wh3_dlc29_nag_undead_legions.
    --
    -- THE UNDEAD CAME OUT ON 2026-09-11, after the first build put the Tomb Kings and the
    -- Coast in the wildcard and the Counts in Destruction. The dead are not a going concern:
    -- Settra hoards rather than trades, Sylvania's wealth is in its crypts, and a share is a
    -- claim on a capital that has to still be accumulating something. It also takes the board
    -- down by roughly a fifth, which the cap was carrying instead.
}

-- THE ONE GATE. EX.discover_houses and the region-power tally in EX.scan_supply are its only
-- callers, and EX.guild() is EX.houses minus delisted - so widening this widens discovery, the
-- share board AND the commodity counterparty pool together, which is intended: a bloc-sized
-- guild is what makes guild_close and refuse_share mean something again. Across the whole map
-- those ratios never trip.
--
-- READS EX.BLOCS, NEVER EX.HOUSE_CULTURE. EX.HOUSE_CULTURE is this client's culture, and this
-- function feeds EX.instruments() - the row list every machine must build identically or the
-- price ladder forks. See the union note in EX.bind_race.
function EX.is_house_culture(c)
    if c == nil then return false end
    -- Own culture always, on every machine, even for a culture absent from EX.BLOC. You can
    -- always invest in your own people.
    if EX.HOUSE_CULTURES[c] == true then return true end
    if not EX.setting("cross_bloc") then return false end
    local theirs = EX.BLOC[c]
    if not theirs then return false end
    -- THE PLAYER HAS TO BE IN A BLOC TOO, and this line is not a formality. Without it
    -- `theirs == "any"` below opens the five merchant cultures to EVERYONE - including a
    -- player whose own culture is in no bloc at all, and including the PRE-BIND state where
    -- no bloc is known yet, which would have moved the own-culture-only default that twenty
    -- other harnesses in tools/gen_zharr_exchange.py measure against. Caught by check_bloc's
    -- "prebind" probe, never by reading.
    if next(EX.BLOCS) == nil then return false end
    return theirs == "any" or EX.BLOCS["any"] == true or EX.BLOCS[theirs] == true
end

-- IS THIS HOUSE ONE OF OUR OWN PEOPLE? Drives the listing order only - own-culture houses sort
-- above foreign ones under every column - so it reads EX.HOUSE_CULTURE, the LOCAL player's
-- culture, on purpose. Row ORDER is a per-client display concern; the row LIST is not.
function EX.is_own_house(key)
    local ok, c = pcall(function() return EX.culture_of(key) end)
    return ok and c ~= nil and c == EX.HOUSE_CULTURE
end

-- ===========================================================================================
-- THE CULTURE LOCK - who gets no Exchange at all.
-- ===========================================================================================
--
-- SEPARATE FROM EX.BLOC, AND THE TWO ARE NOT THE SAME QUESTION. EX.BLOC answers "may others
-- buy shares in this culture"; this answers "may a player OF this culture open the Exchange".
-- Greenskins, Norsca and the Warriors of Chaos stay in EX.BLOC and are locked here: a Chaos
-- Dwarf is betting on their territory, not on their bookkeeping.
--
-- BOTH SWITCHES DEFAULT OFF, which is the opposite of every other switch in this file and is
-- why they cannot use EX.setting or EX.feature. Both of those return TRUE for a key MCT has
-- not written - the right default for a feature you are turning off, and exactly wrong for a
-- permission you are turning on. EX.lock_allowed below defaults to FALSE on purpose.
EX.LOCK_GROUPS = {
    -- No commercial existence at all. The dead do not accumulate, daemons have no economy,
    -- Beastmen have herdstones rather than markets and the Slann have no concept of commerce.
    uncommercial = { "wh2_dlc09_tmb_tomb_kings", "wh_main_vmp_vampire_counts",
                     "wh2_dlc11_cst_vampire_coast", "wh3_dlc29_nag_undead_legions",
                     "wh3_main_kho_khorne",
                     "wh3_main_tze_tzeentch", "wh3_main_sla_slaanesh",
                     "wh3_main_nur_nurgle", "wh3_main_dae_daemons",
                     "wh_dlc03_bst_beastmen", "wh2_main_lzd_lizardmen" },
    -- They take rather than trade. Still investable by others - see the note above.
    raiders      = { "wh_main_grn_greenskins", "wh_dlc08_nor_norsca", "wh_main_chs_chaos" },
}

EX.LOCK_OF = {}
for group, list in pairs(EX.LOCK_GROUPS) do
    for _, c in ipairs(list) do EX.LOCK_OF[c] = group end
end

-- DEFAULT FALSE, and MULTIPLAYER IS LOCKED. EX.feature answers true under mp_ignores_mct
-- because a feature nobody can configure should still run; a PERMISSION nobody can configure
-- must stay at its default instead, and the default is locked. It also has to answer the same
-- on every machine, which "the default" does and "whatever this client's MCT says" does not.
function EX.lock_allowed(group)
    if EX.LOCK_GROUPS[group] == nil then return false end
    if EX.mp_ignores_mct() then return false end
    return EX.mct_raw("allow_" .. group) == true
end

-- The group name that locks this culture, or nil if it may trade.
function EX.culture_locked(c)
    local group = EX.LOCK_OF[c or ""]
    if not group then return nil end
    if EX.lock_allowed(group) then return nil end
    return group
end

function EX.exchange_locked()
    return EX.culture_locked(EX.HOUSE_CULTURE)
end
EX.HOUSE_LOT_SIZE = 5
EX.SAVE_HOUSES  = "zharr_houses"     -- semicolon-joined, the shape EX.shocked uses
EX.SAVE_SHARES  = "zharr_sh_"        -- per house; holdings are SAVE STATE, not a pooled resource
EX.SAVE_HOME    = "zharr_home_"      -- per house; its capital REGION KEY, cached while alive

-- ===========================================================================================
-- THE GUILD'S BOOKS. Spec: 2026-09-07-zharr-exchange-ai-traders-design.md
-- ===========================================================================================
--
-- ONE PACKED STRING PER HOUSE, not one saved value per (house, commodity) pair: 14 values
-- rather than 238. Same shape EX.SAVE_HOUSES already uses for its house list.
EX.SAVE_BOOK = "zharr_bk_"
EX.SAVE_WBOOK = "zharr_wb_"

-- Net guild lots per rung of price effect, and the ceiling in rungs. BOOK_MAX ships small for
-- the reason EX.AI_MAX_RUNGS = 2 ships small: the constant is uncalibrated and must not be
-- able to dominate the supply model underneath it. CONCENTRATION_K was chosen the same way
-- and was inert in play for a full day before measurement found it - this bound guards the
-- other direction, a dial that is too loud rather than silent.
EX.BOOK_PER_RUNG = 30
EX.BOOK_MAX      = 2

-- Lots one house may move in one direction in one turn. With ~10 houses that is at most 40
-- lots of flow a turn against a 30-lot rung, so the board moves at a pace a player can read.
EX.BOOK_TRADE_MAX = 4

-- The markup a maximally hostile guild charges, and the ceiling under a non-aggression pact.
-- 0.25 against EX.SPREAD's 0.10 makes a worst-case round trip cost about half the position -
-- steep, deliberately, and reachable only by a house that despises you and holds the book.
EX.HOSTILE_MAX      = 0.25
-- THE FRIENDLY HALF, AND IT IS A CEILING RATHER THAN A RATE. What a liked guild actually
-- takes off is min(this, EX.friendly_cap()), because a discount larger than the spread's own
-- headroom lets a player buy and sell one rung up at a profit. See EX.friendly_cap.
EX.FRIENDLY_MAX     = 0.25
EX.HOSTILE_PACT_CAP = 0.05
-- A sell never pays less than this fraction of the world price, whatever the spread and the
-- hostility add up to. Without a floor the two terms can in principle meet and a sale pays
-- nothing, which reads as a broken button rather than as a bad market.
EX.SELL_FLOOR = 0.25

-- Refusal needs a house to be in the deepest quarter of the guild's negative spread AND to
-- hold half the book on that good. Both, because either alone catches the wrong house: rank
-- alone refuses on a token position, share alone refuses for mild dislike.
EX.REFUSE_RANK  = 0.25
EX.REFUSE_SHARE = 0.50
-- The share of the guild's whole book that must be at war with you before the Exchange shuts.
EX.GUILD_CLOSE = 0.60

-- Per-turn treasury movement cap per house, both directions. AI treasuries drive AI armies,
-- so this is the one number in the Exchange that changes the campaign for factions the player
-- is not playing. Without the cap, one large position hands a house a campaign's worth of
-- gold in a turn.
EX.HOUSE_CASH_MAX = 20000

-- THE WORLD TIER. Deliberately small, like the four appetite constants and the 25/150 stance
-- thresholds before them: every one of these is a guess until a campaign is played.
-- WORLD_CASH_MAX is an order of magnitude under HOUSE_CASH_MAX because there are ~80 actors
-- rather than 14, and one actor's ceiling is not the map's.
EX.WORLD_CASH_MAX  = 3000
EX.WORLD_TRADE_MAX = 3

-- THE WORLD TIER'S PRICING GAIN. See EX.world_book_shift, directly below EX.book_shift: a
-- SECOND term with its own gain and its own clamp, so the fourteen-house calibration EX.book_shift
-- rests on is never touched by this tier's numbers.
EX.WORLD_GAIN = 4.0

-- THE DEALS PAGE. Each turn a few world actors with the strongest conviction post one deal
-- the player can take or leave.
--
-- HOW MANY THE PAGE CAN CARRY AT ONCE. Small on purpose, like WORLD_TRADE_MAX and the four
-- appetite constants above it: the whole map posts these and every one is a decision the
-- player has to read. START LOW AND MEASURE - no campaign has been played on any of them.
-- IT IS ALSO THE ROW POOL. EX.build_panel creates exactly this many row components once,
-- so the cap in EX.post_deals and the loop in EX.build_panel must read the SAME knob or the
-- page posts a deal with nothing to draw it in. Both read EX.opt("deal_max") and a static
-- check asserts they still agree.
EX.DEAL_MAX = 3
-- HOW FAR OFF MARKET A DEAL IS PRICED, in percent.
--
-- THE EDGE IS FOR THE PLAYER, BOTH WAYS, and the plan's own comment had this backwards: a
-- deal buyer pays OVER market for what the player sells it, and a deal seller takes UNDER
-- market for what the player buys. That is the entire incentive to use this page rather than
-- the Trade view, and it is also a direct gold transfer out of the map and into the player -
-- so it is deliberately smaller than one step of the price ladder.
EX.DEAL_EDGE = 6


-- ===========================================================================================
-- MCT. Spec sections 13, 15.
-- ===========================================================================================

-- THE RAW MCT READ, AND THE ONLY ONE. Returns nil for every failure - MCT absent, mod absent,
-- option absent, getter throwing - rather than a value, because the caller is the only thing
-- that knows what a sensible default for this key is.
--
-- THE OLD EX.setting RETURNED `true` HERE, which was right while every option was a checkbox
-- and wrong the moment one was not: `true` for a dropdown key makes EX.PRESETS[true] nil, and
-- a nil into arithmetic is a crash somewhere else entirely, on a line that is not the bug.
function EX.mct_raw(key)
    if not get_mct then return nil end
    local ok, v = pcall(function()
        local m = get_mct():get_mod_by_key("derpy_chd_zharr_exchange")
        if not m then return nil end
        local o = m:get_option_by_key(key)
        if not o then return nil end
        return o:get_finalized_setting()
    end)
    if not ok then return nil end
    return v
end

-- THE TUNABLE KNOBS, key -> the CONSTANT that holds its default. The constants above stay the
-- single source of every default value: nothing here restates a number, so the defaults and
-- the code that documents them cannot drift, and a harness that overrides EX.SPREAD still
-- overrides what EX.opt("spread") answers.
--
-- WHAT IS NOT HERE IS AS DELIBERATE AS WHAT IS. EX.TRADE_STEPS, EX.BOON, EX.DEMAND_TIERS and
-- the EX.FEED_* indices are baked into DB rows at pack build time, and EX.LOT_SIZE /
-- EX.L2_LOT_SIZE / EX.HOUSE_LOT_SIZE are written into tooltip and header TEXT that
-- check_tooltips() pins character for character. A slider over any of them would move a number
-- the game never reads, or make a tooltip lie. A preset can switch those systems off; it
-- cannot renumber them.
EX.TUNE_NUM = {
    ladder_step = "LADDER_STEP", spread = "SPREAD", sell_floor = "SELL_FLOOR",
    l2_sell = "L2_SELL",
    pressure_per_rung = "PRESSURE_PER_RUNG", carry_per_unit = "CARRY_PER_UNIT",
    ai_gain = "AI_GAIN", ai_max_rungs = "AI_MAX_RUNGS", book_per_rung = "BOOK_PER_RUNG",
    book_max = "BOOK_MAX", hostile_max = "HOSTILE_MAX", friendly_max = "FRIENDLY_MAX",
    guild_close = "GUILD_CLOSE",
    refuse_share = "REFUSE_SHARE", house_cash_max = "HOUSE_CASH_MAX",
    div_yield = "DIV_YIELD", buyout_premium = "BUYOUT_PREMIUM", windup = "WINDUP",
    seat_lost = "SEAT_LOST",
    demand_first_turn = "DEMAND_FIRST_TURN", demand_cooldown = "DEMAND_COOLDOWN",
    demand_chance = "DEMAND_CHANCE",
    shock_gain = "SHOCK_GAIN", shock_max = "SHOCK_MAX", shock_decay = "SHOCK_DECAY",
    race_strength = "RACE_STRENGTH",
    world_cash_max = "WORLD_CASH_MAX", world_trade_max = "WORLD_TRADE_MAX",
    deal_max = "DEAL_MAX", deal_edge = "DEAL_EDGE",
    pos_step = "POS_STEP_LOTS",
    world_gain = "WORLD_GAIN",
}

-- The twelve system switches. All default TRUE: a settings panel that is not installed must
-- never silently disable a feature.
EX.TUNE_BOOL = { "ai_traders", "ai_gold", "refusal", "war_lock", "warehouse_rent",
                 "hashut_demands", "trade_income", "cross_bloc", "ai_stance", "ai_world",
                 "world_scarcity", "ai_deals", "world_bundles" }
EX.TUNE_BOOL_SET = {}
for _, k in ipairs(EX.TUNE_BOOL) do EX.TUNE_BOOL_SET[k] = true end

-- THE DIFFICULTY PRESETS. A preset owns the seven booleans as well as the numbers - "Ultra
-- Capitalism with the AI traders switched off" is not Ultra Capitalism, it is Custom, and
-- Custom is where that lives.
--
-- `default` MUST STAY EMPTY. The defaults are the constants above and restating them here
-- would be two places to change and one to forget; check_presets() asserts it is empty and
-- asserts the other three are COMPLETE. A partially-filled preset is half `default` with
-- nothing on screen saying so, which is the ambiguity a delta table cannot resolve.
EX.PRESET_DEFAULT = "default"
EX.PRESET_CUSTOM  = "custom"
EX.PRESET_KEYS = { "easy", "default", "hard", "ultra", "custom" }
EX.PRESETS = {
    default = {},
    -- LOW RISK, NOT LOW REWARD. The spread is thin, the sell floor returns most of a bad
    -- stake, storage is cheap, the guild moves the price slowly and almost never refuses or
    -- shuts - and shares still pay double the default dividend. Rent and the tithe are off.
    easy = {
        -- SPREAD 0.08, NOT 0.04. At ladder_step 1.08 a four percent spread means selling
        -- ONE RUNG UP pays 1.0368x what you bought at - this preset minted gold on its own,
        -- with no friendly discount involved, and had done since it was written.
        -- check_spread() never saw it because it only ever ran against the DEFAULT constants;
        -- it now runs against every preset. 0.08 clears the 1 - 1/1.08 = 0.0741 floor and is
        -- still the thinnest spread of the four.
        l2_sell = 0.75, -- the Forge's goods are nearly liquid here
        ladder_step = 1.08, spread = 0.08, sell_floor = 0.60, pressure_per_rung = 3,
        carry_per_unit = 0.2,
        ai_gain = 3.0, ai_max_rungs = 1, book_per_rung = 45, book_max = 1,
        hostile_max = 0.10, friendly_max = 0.10,
        guild_close = 0.90, refuse_share = 0.80, house_cash_max = 20000,
        div_yield = 0.04, buyout_premium = 1.50, windup = 0.75, seat_lost = 0.80,
        demand_first_turn = 30, demand_cooldown = 25, demand_chance = 15,
        shock_gain = 5, shock_max = 3, shock_decay = 0.35,
        -- HALF FLAVOUR ON EASY. A first campaign should not meet the Under-Market at full
        -- strength; the races still read differently, at half the departure from baseline.
        race_strength = 0.5,
        world_cash_max = 1500, world_trade_max = 2, world_gain = 2.0,
        -- THE PAGE IS THE FRIENDLIEST THING IN THE MOD and easy leans on it: four offers a
        -- turn at a tenth off market, against three at six per cent. Still under one step of
        -- the price ladder, which at easy's 1.08 is eight per cent - a deal must never be a
        -- free round trip against the Trade view.
        deal_max = 4, deal_edge = 7,
        -- THE WIDEST STEP OF THE FOUR, so the fewest factions on the map carry a position
        -- bundle at all. A first campaign should meet this as flavour rather than as a
        -- second economy running underneath the one it is learning.
        pos_step = 6,
        ai_traders = true, ai_gold = true, refusal = true, war_lock = true,
        warehouse_rent = false, hashut_demands = false, trade_income = true,
        cross_bloc = true, ai_stance = true, ai_world = true, ai_deals = true,
        world_bundles = true,
        -- THE ONE DELIBERATE ASYMMETRY. A first campaign should never have a purchase
        -- refused for want of a seller.
        world_scarcity = false,
    },
    -- HIGH RISK, HIGH REWARD. Every edge that costs you widens and every payout rises with it.
    hard = {
        l2_sell = 0.40,
        ladder_step = 1.13, spread = 0.16, sell_floor = 0.15, pressure_per_rung = 6,
        carry_per_unit = 0.8,
        ai_gain = 9.0, ai_max_rungs = 3, book_per_rung = 22, book_max = 3,
        hostile_max = 0.40, friendly_max = 0.40,
        guild_close = 0.45, refuse_share = 0.35, house_cash_max = 30000,
        div_yield = 0.03, buyout_premium = 1.60, windup = 0.30, seat_lost = 0.45,
        demand_first_turn = 10, demand_cooldown = 10, demand_chance = 45,
        shock_gain = 15, shock_max = 8, shock_decay = 0.60,
        race_strength = 1.0,
        world_cash_max = 4000, world_trade_max = 3, world_gain = 6.0,
        deal_max = 3, deal_edge = 4,
        pos_step = 3,
        ai_traders = true, ai_gold = true, refusal = true, war_lock = true,
        warehouse_rent = true, hashut_demands = true, trade_income = true,
        cross_bloc = true, ai_stance = true, ai_world = true, ai_deals = true,
        world_bundles = true,
        world_scarcity = true,
    },
    -- ULTRA CAPITALISM. A quarter spread against a tenth floor, the guild moving five rungs a
    -- turn on books that shift twice as hard, hostility to +60%, the market shutting when under
    -- a third of the guild is at war, the altar demanding from turn 5 on a six-turn cycle, and
    -- shocks reaching twelve rungs and lingering. Shares pay 5% and a buyout pays double.
    ultra = {
        l2_sell = 0.25,
        ladder_step = 1.18, spread = 0.25, sell_floor = 0.10, pressure_per_rung = 8,
        carry_per_unit = 1.2,
        ai_gain = 14.0, ai_max_rungs = 5, book_per_rung = 15, book_max = 4,
        hostile_max = 0.60, friendly_max = 0.60,
        guild_close = 0.30, refuse_share = 0.25, house_cash_max = 60000,
        div_yield = 0.05, buyout_premium = 2.00, windup = 0.15, seat_lost = 0.30,
        demand_first_turn = 5, demand_cooldown = 6, demand_chance = 60,
        shock_gain = 25, shock_max = 12, shock_decay = 0.70,
        -- Ultra sharpens the profiles as it sharpens everything else. Several Skaven knobs
        -- already clamp here, so the practical effect is on the Empire and Cathay boards.
        race_strength = 1.25,
        world_cash_max = 8000, world_trade_max = 4, world_gain = 9.0,
        -- TWO OFFERS AT TWO PER CENT. Ultra keeps the page - it is information about what
        -- the world wants, which is worth more here than anywhere - and takes the gift out
        -- of it. Two per cent against a 1.18 ladder is a rounding error on a single lot.
        deal_max = 2, deal_edge = 2,
        -- THE NARROWEST. Two lots of net war goods is a tier, so most of the map wears one
        -- and the war-materiel trade is a live strategic lever rather than a side effect.
        pos_step = 2,
        ai_traders = true, ai_gold = true, refusal = true, war_lock = true,
        warehouse_rent = true, hashut_demands = true, trade_income = true,
        cross_bloc = true, ai_stance = true, ai_world = true, ai_deals = true,
        world_bundles = true,
        world_scarcity = true,
    },
}

-- The default for one knob, read off the constant that documents it. nil for a key that is not
-- a knob at all, which is a caller bug and must not be papered over with a plausible value.
function EX.opt_default(key)
    local c = EX.TUNE_NUM[key]
    if c then return EX[c] end
    if EX.TUNE_BOOL_SET[key] then return true end
    return nil
end

-- THE SNAPSHOT. Every value this campaign runs on, resolved once and written into the save.
--
-- WHY IT EXISTS AT ALL: the difficulty is fixed for the life of a campaign, and MCT's own
-- gating cannot enforce that - mct_option:set_context_specific is an EMPTY function body and
-- set_local_only is commented out end to end, so both read as gating and gate nothing. The
-- settings file greys the controls with set_locked, but a greyed control says nothing about a
-- player who installs MCT mid-campaign, uninstalls it, or edits the registry. The numbers a
-- save is played on live in the save.
--
-- IT IS ALSO THE CACHE. Once taken, EX.opt is a table read: no get_finalized_setting in the
-- price path, nothing to invalidate, and no MctFinalized listener for the economy half. That
-- matters here - the AI-trader review measured 58,786 cm:get_faction calls per refresh on
-- exactly this shape of per-row engine call.
EX.SAVE_SNAP = "zharr_opts"
EX.snap = nil

-- MULTIPLAYER IGNORES MCT ENTIRELY, and this is the guard that makes it.
--
-- MCT IS A LOCAL REGISTRY. Two players can have different mods, different presets and
-- different sliders, and nothing reconciles them - so a snapshot taken from MCT would freeze a
-- DIFFERENT economy into each machine's save on the first turn, which is a desync from the
-- first rent charge onward and one that no amount of care further down could undo.
--
-- SO IN MULTIPLAYER EVERY ECONOMIC VALUE IS THE SHIPPED DEFAULT, on every machine, and the
-- difficulty preset is Default. That is a real loss of a real feature and it is stated in the
-- MCT panel's own description; the alternative was a broadcast of thirty values through an
-- event id string, which the transport cannot carry.
--
-- ONLY THE ECONOMY. EX.dbg_opt reads MCT live and is deliberately NOT gated here: log level
-- and the seven category switches change nothing in the model, and a multiplayer bug is
-- exactly when a player needs to be able to turn logging up on their own machine.
function EX.mp_ignores_mct()
    return EX.is_mp()
end

-- Resolve one key live. Only ever reached before the snapshot exists.
function EX.opt_live(key)
    local def = EX.opt_default(key)
    if def == nil then return nil end
    if EX.mp_ignores_mct() then return def end
    local preset = EX.mct_raw("preset")
    if type(preset) ~= "string" or preset == "" then preset = EX.PRESET_DEFAULT end
    if preset ~= EX.PRESET_CUSTOM then
        local p = EX.PRESETS[preset]
        if p == nil then return def end          -- an unknown preset key is the default
        if p[key] ~= nil then return p[key] end
        return def
    end
    local v = EX.mct_raw(key)
    -- TYPE-CHECKED, NOT NIL-CHECKED. MCT hands back whatever the option holds, and a harness
    -- or a mis-registered option can hand back a boolean for a slider. Anything that is not
    -- the shape of the default is the default.
    if type(v) ~= type(def) then return def end
    return v
end

-- The player's race profile factor for one key, or 1. An uncovered race, a race with no
-- profile, a key off the whitelist and a non-numeric entry all answer 1.
function EX.race_factor(key)
    if EX.RACE_TUNABLE[key] == nil then return 1 end
    -- EX.rc(), NOT EX.race. This is applied at READ time inside EX.opt, and EX.opt is read
    -- while another player is bound all through the turn round - so reading the LOCAL player's
    -- profile here would charge the Empire player's rent at Chaos Dwarf factors on one machine
    -- and at Empire factors on theirs. In singleplayer the subject is always the local player
    -- and this is the same lookup it always was.
    local r = EX.rc()
    local t = r and r.tune
    local f = t and t[key]
    if type(f) ~= "number" then return 1 end
    -- SAFE BECAUSE race_strength IS NOT ON THE WHITELIST. EX.opt calls EX.race_apply, which
    -- returns before reaching this function for any key EX.RACE_TUNABLE does not list. Adding
    -- race_strength to that table would make this recurse until the stack goes, inside the
    -- price path - which is why check_race_tune() asserts it is absent rather than trusting
    -- the comment.
    local strength = EX.opt("race_strength")
    if type(strength) ~= "number" then strength = EX.RACE_STRENGTH end
    if strength < 0 then strength = 0 end
    if strength == 1 then return f end
    return 1 + (f - 1) * strength
end

-- Apply that factor, clamp to the key's bounds, and round if the knob counts in whole units.
--
-- THE ROUNDING IS NOT COSMETIC. demand_cooldown is a number of turns and demand_chance a
-- percentage rolled against an integer; 54.899998 is what single-precision actually produces
-- for 30 * 1.83, and leaving it unrounded puts a fractional turn count into a comparison that
-- reads as off-by-one exactly when the fraction lands wrong. The test is the DEFAULT's shape,
-- not the resolved value's: a preset may hand back 0.5 for a knob whose constant is 6.
function EX.race_apply(key, v)
    local b = EX.RACE_TUNABLE[key]
    if b == nil or type(v) ~= "number" then return v end
    local f = EX.race_factor(key)
    if f == 1 then return v end
    v = v * f
    if v < b[1] then v = b[1] end
    if v > b[2] then v = b[2] end
    local def = EX.opt_default(key)
    if type(def) == "number" and def % 1 == 0 then v = math.floor(v + 0.5) end
    return v
end

-- HERE, AND NOT IN EX.opt_live. The snapshot is built from opt_live and is written into the
-- save, so factoring there would freeze the race profile into new campaigns and leave every
-- campaign started before this feature permanently un-flavoured. Factoring at READ time is
-- safe in a way MCT is not: a save's faction cannot change, so the factor is as fixed for the
-- life of a campaign as the frozen numbers underneath it - and an in-flight campaign picks the
-- profile up on the next load rather than needing a restart.
--
-- The cost is one table lookup on a hot path. The AI-trader review's 58,786 engine calls per
-- refresh is the scale that matters here; this is not on it.
function EX.opt(key)
    local s = EX.snap
    if s and s[key] ~= nil then return EX.race_apply(key, s[key]) end
    return EX.race_apply(key, EX.opt_live(key))
end

-- Called first thing at FactionTurnStart, and NOT at first tick: first tick is not provably
-- after MCT's registry has loaded, and a snapshot taken too early would freeze the DEFAULTS
-- over the player's actual choice - permanently, with a correct-looking MCT panel beside it
-- saying otherwise. A campaign that predates this feature takes its snapshot on the next turn
-- start from whatever MCT says then, and is frozen from that point like any other.
function EX.snapshot()
    if EX.snap then return false end
    local saved = EX.getv(EX.SAVE_SNAP)
    if type(saved) == "table" and next(saved) ~= nil then
        EX.snap = saved
        return false
    end
    local t = {}
    for key in pairs(EX.TUNE_NUM) do t[key] = EX.opt_live(key) end
    for _, key in ipairs(EX.TUNE_BOOL) do t[key] = EX.opt_live(key) end
    t.preset = EX.opt_live_preset()
    EX.snap = t
    EX.setv(EX.SAVE_SNAP, t)
    return true
end

-- The preset NAME, for the log line and the panel. Kept beside the snapshot because the name
-- is the one thing a player can check against what they chose.
function EX.opt_live_preset()
    if EX.mp_ignores_mct() then return EX.PRESET_DEFAULT end
    local p = EX.mct_raw("preset")
    if type(p) ~= "string" or p == "" then return EX.PRESET_DEFAULT end
    return p
end

function EX.preset_name()
    if EX.snap and EX.snap.preset then return EX.snap.preset end
    return EX.opt_live_preset()
end

-- THE BOOLEAN FACE OF EX.opt, kept because ten call sites and their assertions read it, and
-- because "is this system on" reads better than "is this option not false".
function EX.setting(key)
    local v = EX.opt(key)
    if v == nil then return true end
    return v ~= false
end

-- ===========================================================================================
-- LOGGING. Separate from everything above, on purpose.
-- ===========================================================================================
--
-- THE DEBUG OPTIONS ARE NOT SNAPSHOTTED AND NOT PRESET-CONTROLLED. Every economic value is
-- frozen for the life of a campaign; the log level is the exact opposite and must be movable
-- while a bug is happening, which is the entire point of having it. So it reads MCT live,
-- through its own accessor, and no preset touches it.
EX.DEBUG_DEFAULT = {
    log_level = "normal",
    log_turn = true, log_trade = true, log_price = true, log_house = true,
    log_demand = true, log_shock = true, log_ui = true,
}
-- Seven subsystems, and "error" is deliberately not one of them - it has no switch.
EX.LOG_CATS = { "turn", "trade", "price", "house", "demand", "shock", "ui" }
EX.LOG_LEVELS = { off = 0, errors = 1, normal = 2, verbose = 3 }
EX.LOG_TAG = "ZHARR EXCHANGE: "

function EX.dbg_opt(key)
    local def = EX.DEBUG_DEFAULT[key]
    if def == nil then return nil end
    local v = EX.mct_raw(key)
    if type(v) ~= type(def) then return def end
    return v
end

-- THE FEATURE SWITCHES, and they are DELIBERATELY NOT IN EX.TUNE_BOOL.
--
-- TUNE_BOOL is snapshotted into the save at the first turn start so that a price you were
-- quoted stays the price you are charged. A kill-switch wants the exact opposite property:
-- it exists to be moved WHILE a bug is happening, which is the justification the debug
-- options already carry. So these read MCT live like those do, and a campaign can be
-- reloaded with one feature off to find out which of four is behind a symptom.
--
-- THEY ARE NOT IN EX.DEBUG_DEFAULT EITHER. check_snapshot_and_debug asserts that table is
-- exactly {log_level} plus the log categories, and that every category name is a log_ one;
-- a feat_ key there breaks two invariants that have nothing to do with this.
--
-- SINGLEPLAYER ONLY. A live switch that changes the model would have to hold the same
-- value on every machine, and reconciling it is exactly the MCT race EX.mp_ignores_mct
-- already refuses to run. In multiplayer all four are forced ON, which is the shipped
-- configuration, so no machine can be running a different model from another.
--
-- ORDERS CAME BACK 2026-09-10, with the feature and in the same commit as its first call
-- site, which is the condition its deletion set. It has two readers, the same shape
-- deep_history has and for the same reason: EX.trade_pages stops the page being REACHED and
-- EX.fill_orders stops the model RUNNING. A kill-switch is thrown while the thing is
-- misbehaving, and the half that moves gold is the fill.
--
-- EX.FEATURES WENT WITH IT (deleted 2026-09-08). It listed the same four keys, was read by
-- nothing in this file or any tool, and was a second place for the set to drift out of
-- agreement with the table below that EX.feature actually reads. check_features now derives
-- the set from THIS table.
EX.FEATURE_DEFAULT = {
    deep_history = true, demand_shocks = true, appetite_drift = true, orders = true,
}

function EX.feature(key)
    if EX.FEATURE_DEFAULT[key] == nil then return false end
    if EX.mp_ignores_mct() then return true end
    local v = EX.mct_raw("feat_" .. key)
    if type(v) ~= "boolean" then return true end
    return v
end

function EX.log_level()
    return EX.LOG_LEVELS[EX.dbg_opt("log_level")] or EX.LOG_LEVELS[EX.DEBUG_DEFAULT.log_level]
end

-- ERRORS ARE NEVER GATED, at any level, and that is not a matter of taste. This mod has
-- already cost four shipped builds to a fault that logged nothing at all - a switch able to
-- silence a failure is not a feature, it is the same fault with a settings entry.
--
-- Everything else carries a subsystem, so a player chasing one thing can silence the other
-- five without losing the log entirely. At `normal` - the default - exactly the lines that
-- printed before this existed still print.
function EX.say(cat, msg)
    if cat == "error" then out(EX.LOG_TAG .. msg) return end
    if EX.log_level() < 2 then return end
    if not EX.dbg_opt("log_" .. cat) then return end
    out(EX.LOG_TAG .. msg)
end

-- Detail nobody wants by default: only at `verbose`, and still subsystem-gated.
function EX.trace(cat, msg)
    if EX.log_level() < 3 then return end
    EX.say(cat, msg)
end

-- The player pressed a button asking for this, so it is never gated by anything. Used by the
-- two MCT debug actions.
function EX.emit(msg)
    out(EX.LOG_TAG .. msg)
end

-- THE TWO DEBUG ACTIONS, reached from the MCT panel's Debug section.
--
-- THROUGH A CUSTOM EVENT, NOT A DIRECT CALL. The MCT settings file loads in MCT's own
-- environment and this file loads in the campaign mod environment; a mod script's globals are
-- not `_G` (measured 2026-09-07 on the victory routes, where `rawget(_G, name)` was nil for a
-- table that read fine as a global), so `EX` is not reliably visible from there.
-- core:trigger_custom_event is CA-documented, works from both, and is what MCT itself uses.
--
-- BOTH RUN FROM THE FRONTEND TOO, where the panel is also reachable and `cm` does not exist.
-- Every campaign read below is behind that check, and the whole body is behind a pcall: a
-- diagnostic that takes the script down with it is worse than no diagnostic.
function EX.dump_state()
    local ok, err = pcall(function()
        EX.emit("---- state dump ----")
        EX.emit("preset " .. tostring(EX.preset_name()) .. ", snapshot "
                .. (EX.snap and "TAKEN - these values are frozen for this campaign"
                             or "not taken yet, reading MCT live"))
        -- WHICH KNOBS THE RACE MOVED, and by how much. Without this the dump shows a number
        -- that matches no preset and nothing on screen says a profile is why.
        EX.emit("race " .. tostring(EX.race and EX.race.name or "uncovered")
                .. (EX.race and EX.race.tune
                    and (" - profile at strength " .. tostring(EX.opt("race_strength"))
                         .. (EX.opt("race_strength") == 0 and " (OFF - baseline board)" or ""))
                    or " - no profile, preset values as-is"))
        local keys = {}
        for k in pairs(EX.TUNE_NUM) do keys[#keys + 1] = k end
        for _, k in ipairs(EX.TUNE_BOOL) do keys[#keys + 1] = k end
        table.sort(keys)
        for _, k in ipairs(keys) do
            local f = EX.race_factor(k)
            EX.emit("  " .. k .. " = " .. tostring(EX.opt(k))
                    .. (f ~= 1 and ("   (race x" .. tostring(f) .. " on "
                                    .. tostring(EX.snap and EX.snap[k]
                                                or EX.opt_live(k)) .. ")") or ""))
        end
        if not cm then EX.emit("---- no campaign, settings only ----") return end
        for _, res in ipairs(EX.instruments()) do
            EX.emit(string.format("  %-32s step %-4s price %-8s held %s",
                                  res, tostring(EX.current[res]), tostring(EX.price(res)),
                                  tostring(EX.held(res))))
        end
        EX.emit("  houses " .. #EX.houses .. ", guild " .. #EX.guild()
                .. ", demand " .. tostring(EX.demand_res)
                .. " due " .. tostring(EX.demand_due))
        EX.emit("---- end state dump ----")
    end)
    if not ok then EX.say("error", "state dump failed: " .. tostring(err)) end
end

-- The supply scan is the one input that fails OPEN - it holds prices at their last rung and
-- says so once. This prints what it actually found, which is the only way to tell "nothing
-- produces this" from "the scan did not run".
function EX.dump_supply()
    local ok, err = pcall(function()
        if not cm then EX.emit("supply scan needs a campaign") return end
        EX.emit("---- supply ----")
        local s = EX.scan_supply()
        if type(s) ~= "table" then EX.emit("scan returned " .. tostring(s)) return end
        for _, res in ipairs(EX.instruments()) do
            if not EX.is_house(res) then
                EX.emit(string.format("  %-32s %s", res, tostring(s[res] or 0)))
            end
        end
        EX.emit("---- end supply ----")
    end)
    if not ok then EX.say("error", "supply dump failed: " .. tostring(err)) end
end

EX.houses = {}        -- discovered faction keys, runtime
EX.house_set = nil    -- memo for EX.is_house, invalidated whenever EX.houses changes
EX.shares_held = {}   -- house -> shares, mirrored from saved values
EX.delisted = {}      -- house -> true once settled; restored from EX.SAVE_DELISTED
-- house -> its capital's REGION KEY, last seen while the faction still existed. A dead or
-- confederated faction answers nothing, so the key is the only thing that outlives it - see
-- EX.absorbed_by_us, where resolving it is what decides which multiplier the paper settles at.
EX.house_home = {}

-- What losing your capital does to your share price. A house that no longer holds its own
-- home region is a house in collapse, and this is the plain-language meaning of "its seat".
-- The original spec priced on whether the Tower of Zharr SEAT was claimed; that is
-- unobservable, because claiming one force-confederates the house and the instrument
-- delists in the same instant. See the design doc §2.
EX.SEAT_LOST = 0.6

-- A horde holds zero regions for its whole life, so its army count stands in for territory.
-- military_force_list counts GARRISONS for a settled faction, which is why this is read only
-- on the zero-region branch, where there are no garrisons to miscount.
EX.HORDE_WEIGHT = 2

-- A FRACTION OF THE LIVE PRICE, not a flat rate. A flat per-share dividend scaled by house
-- power needs two constants and the yield then drifts away from the price: a cheap house can
-- end up paying a better RETURN than a dear one, which is a loop the player can farm. A
-- fraction is self-balancing and can never pay more than the house is worth.
--
-- 0.02 is ~50 turns to pay back. Against EX.SPREAD's 10%, a position turns profitable after
-- five turns held, which is the shortest trip worth making. So a share is a bet that the
-- house RISES, not an income cheat.
--
-- UNCALIBRATED, in the same sense as CARRY_PER_UNIT and the warehouse tiers - a shape argued
-- from the spread, not a measurement. It is also a campaign-wide income knob, which is the one
-- place a bad guess compounds every turn. Ship it, then read the board.
EX.DIV_YIELD = 0.02

-- WHO KILLED IT DECIDES WHAT IT PAYS. A flat premium on delist pays the player for backing a
-- loser: buy into a doomed house, wait for anybody at all to finish it, collect more than you
-- paid. So the payout splits on whether OUR faction ended up with the house's capital.
EX.BUYOUT_PREMIUM = 1.25   -- we absorbed it: the cornering hook, and the only path that pays
EX.WINDUP         = 0.5    -- somebody else did: a distressed wind-up, you backed a loser
EX.SAVE_DELISTED  = "zharr_delisted"
EX.FEED_DELIST    = 7404   -- see EX.FEED_SHOCK for why the persistent flag must match the row

-- What each offering buys, in the panel's words. The effect bundle carries its own tooltip once
-- it is running, but that is no use to someone deciding whether to light it - so the number is
-- here, in the row, before the click.
--
-- EVERY VALUE IS OFFERING_EFFECTS[res] * OFFER_MULT from tools/gen_zharr_exchange.py, and the
-- generator's check_lua_boons() re-derives all seventeen from the DB rows and fails if this
-- table drifts. A wrong number here is a lie the player acts on and nothing else would catch.
-- HASHUT'S DEMANDS. Every number here is mirrored in tools/gen_zharr_exchange.py and
-- re-derived from the shipped DB rows by its check_demands() - the dilemma TEXT is a static loc
-- string that names the amount and the duration, so a drift between these and the rows means
-- the altar promises one thing on screen and charges another, with nothing to say so.
-- NO DILEMMA. A DilemmaChoiceMadeEvent listener that MATCHES hard-crashes this game:
-- 0xc0000005 null deref at Warhammer3.exe+0x236C1CF, seven times, byte-identical, and the
-- last of those was an EMPTY handler - not one line of our code inside it. With the listener
-- removed the same click is clean. Since a dilemma cannot be dismissed without answering, a
-- fired demand bricked the campaign outright.
--
-- Ruled out first, none of them the cause: the required flag, the payload type (a pooled
-- transaction AND a text_display both crash), a dangling optional_icon_path (a real defect,
-- fixed, unrelated), the pool reaching exactly 0, every column of the dilemma row (all are
-- vanilla's majority value), the ui_image (CA's own file), deferring the work with
-- cm:callback, and EX.resolve_demand itself (called directly it runs clean and takes the
-- goods). See section 30 of the 2026-09-05 handoff.
--
-- So the demand is a NOTIFICATION plus a DEADLINE instead of a popup with two buttons:
-- Hashut names a price in the event feed, the player pays it through the Sacrifice button in
-- the offerings view, and if the deadline passes unpaid the wrath lands at turn start.
-- Every call in that path is one this campaign has already run thousands of times.
EX.DEMANDS_ENABLED = true

-- Turns the player has to pay before the wrath lands.
EX.DEMAND_GRACE = 3

-- The event_feed_message_events index show_message_event resolves against. NOT a free number
-- and NOT 0: it is the campaign_group_member_criteria_values value of our own feed record, and
-- an index with no record behind it makes the call log and draw nothing.
-- THE EVENT-FEED INDEX BLOCK PER RACE. The record's PICTURE is a DB column and nothing can
-- swap it at runtime, so each race owns four records rather than sharing four - a Skaven
-- player was shown the Chaos Dwarf forge for a Trade Disrupted bulletin (2026-09-08).
--
-- The Chaos Dwarf block stays at 7401-7404, which is where it has always been. The offsets
-- below are the SLOT within a block and must match the order of FEED in
-- tools/gen_zharr_exchange.py; the generator asserts the two agree.
EX.FEED_BASE = {
    [""]     = 7401,
    emp_     = 7411,
    cth_     = 7421,
    skv_     = 7431,
    teb_     = 7441,
    dwf_     = 7451,
    hef_     = 7461,
    def_     = 7471,
}
EX.FEED_SLOT = { call = 0, wrath = 1, shock = 2, delist = 3 }

-- An UNCOVERED race has no block of its own and falls back to the Chaos Dwarf one. That is
-- deliberate rather than an oversight: the shock bulletin fires for every player, covered or
-- not (EX.announce_shocks is not gated), so returning nil here would draw nothing at all -
-- and a bulletin with the wrong picture beats a bulletin that silently does not appear.
function EX.feed(kind)
    local base = EX.FEED_BASE[EX.seg()] or EX.FEED_BASE[""]
    return base + (EX.FEED_SLOT[kind] or 0)
end

EX.FEED_CALL  = 7401     -- Hashut speaks, and the tithe accepted
EX.FEED_WRATH = 7402     -- the tithe refused
-- NEWS, NOT A SUMMONS, and that is a different RECORD rather than a different message. The
-- two above are scripted_persistent_event records and steal the screen, which is right for a
-- god naming a price and wrong for a market report - the 2026-09-06 log carries 320 shock
-- events over ~30 turns, so a popup per shock would fire ten times a turn. This one is a
-- scripted_transient_event: it lands in the event feed strip and expires. Four vanilla
-- precedents, all instant_open false (Alith Anar's targets, Defender of Ulthuan, Gotrek and
-- Felix, the dlc27 consult-leaders notice).
--
-- THE PERSISTENT FLAG PASSED TO show_message_event MUST AGREE WITH THE RECORD - false here,
-- true for the two above - or nothing draws. Same rule the demand messages carry.
EX.FEED_SHOCK = 7403     -- war shook the market; see EX.announce_shocks

EX.SAVE_DEM_RES  = "zharr_demand_res"
EX.SAVE_DEM_TIER = "zharr_demand_tier"
EX.SAVE_DEM_DUE  = "zharr_demand_due"

EX.DEMAND_FIRST_TURN = 15   -- nothing before the market has had time to matter
EX.DEMAND_COOLDOWN   = 15   -- turns between demands, whatever the answer was
EX.DEMAND_CHANCE     = 30   -- per cent per turn once off cooldown
EX.DEMAND_TOP_N      = 3    -- the altar names one of the three biggest piles, not any pile
-- THE CHAOS DWARF DEFAULTS. Read through EX.wrath_bundle() / EX.pleased_bundle(), which
-- prefer the bound race's own keys; these two stay module constants because twenty
-- generator checks load this file without ever calling EX.bind_race and read them direct.
EX.WRATH_BUNDLE  = "derpy_chd_ex_hashut_wrath"
-- Paying a demand grants this ON TOP of the commodity's own boon: +3 public order and +5
-- leadership, for the same duration. The boon is what the goods were good for; this is the
-- god noticing they arrived.
EX.PLEASED_BUNDLE = "derpy_chd_ex_hashut_pleased"
-- suffix, units taken, boon turns, wrath turns, weight out of 100.
-- Amounts are 1x / 3x / 6x the BASE offering cost, which is where 30/90/180 comes from - a
-- tithe is exactly what you would have given freely. They do NOT escalate with EX.offer_cost;
-- Hashut names his own price and it does not care how often you have volunteered.
EX.DEMAND_TIERS = {
    { "tithe",   30,  6,  4, 55 },
    { "hunger",  90, 12,  8, 32 },
    { "wrath",  180, 24, 15, 13 },
}
EX.SAVE_DEMAND = "zharr_demand_turn"    -- last turn a demand was issued

EX.BOON = {
    res_rom_iron     = "+4 armour, all armies",
    res_obsidian     = "+10 winds of magic cap",
    res_rom_marble   = "-6% construction cost",
    res_rom_timber   = "-6% construction cost",
    res_rom_wine     = "+4 public order",
    res_spices       = "+4 public order",
    res_rom_glass    = "+4 public order",
    res_gems         = "+6% trade tariffs",
    res_dyes         = "+6% trade tariffs",
    res_trinkets     = "+6% trade tariffs",
    res_gold_idols   = "+2 hero capacity",
    res_ivory        = "+4 research points",
    res_animals      = "+10% Labour per battle",
    res_medicine     = "+6% replenishment",
    res_rom_lead     = "+6% replenishment",
    res_rom_furs     = "+6% movement range",
    res_rom_textiles = "-6% recruit cost",
}

-- ---------------------------------------------------------------------------------------
-- THE WAREHOUSE. Holding goods costs gold per turn, and a big enough pile grants a standing
-- bonus. One lever pointed both ways. Both numbers must match tools/gen_zharr_exchange.py -
-- its check_lua_warehouse() reads them back out of this file and fails if they drift.
--
-- CARRY IS FLAT PER UNIT, NOT A PERCENTAGE OF THE POSITION'S VALUE. A percentage of value is a
-- financier's cost of carry - interest on capital - and there are no banks in Zharr-Naggrund.
-- A warehouse charges by the crate: slaves to haul it, guards to watch it, a roof over it. A
-- tonne of timber costs the same to store as a tonne of gemstones, so hoarding bulk is ruinous
-- and hoarding dense wealth is cheap, out of ONE constant and with no per-commodity table:
--
--     800 timber    (~20g/unit)  -> 400g/turn = 2.5% of the position per turn
--     800 gemstones (~500g/unit) -> 400g/turn = 0.1% of the position per turn
--
-- This is what stops "do nothing and wait" being free. The big loss on a bad position is
-- market impact, which you only realise if you act; without a carry cost the correct play is
-- always to park it, and a position you can park for free is not a position, it is a save file.
EX.CARRY_PER_UNIT = 0.5

-- THE RAMP: { units held, tier }. Tier is the index, and it is also the bundle suffix.
--
-- A CLIFF AT ONE THRESHOLD WAS REJECTED IN REVIEW. Selling one lot out of a 100-unit position
-- would silently kill the bonus, and losing a buff for selling 10 units reads as a bug the
-- first time it happens. The ramp also makes a deep position a strategy rather than a flat
-- subscription.
--
-- Tier 2 grants exactly what BURNING the goods on the altar grants (OFFER_MULT is 2), and that
-- comparison is deliberate: the altar destroys 30 units for a 5-turn buff, the warehouse ties
-- up 300 for as long as you keep paying the carry.
EX.STOCK_TIERS = { 100, 300, 600 }

-- WHAT COUNTS AS WAR MATERIEL. Iron for weapons, timber for hafts and siege engines,
-- obsidian for the shot the Forge actually fires. Chosen by DISPLAY name and then written
-- as keys, because five of the seventeen filenames name a different good than they draw -
-- res_rom_lead is Salt and res_rom_glass is Dwarf Beer, so a set picked by reading the key
-- names would be a set of the wrong three commodities with every gate green.
--
-- check_lua_books asserts every key here is in EX.COMMODITIES: an unlisted key is not an
-- error in Lua, it is a set that silently never matches, and the whole asymmetry would be
-- dead with nothing to show for it.
EX.WAR_GOODS = {
    res_rom_iron = true, res_rom_timber = true, res_obsidian = true,
}

-- SYMMETRIC, AND DELIBERATELY SHORT. Two steps either side of neutral. Spec section 15
-- item 5 says the bundle set is unsized and no offline check can answer it, so this starts
-- at the smallest ladder that can express "better" and "worse" at two intensities and is
-- measured in a played campaign. Too weak to notice is recoverable; too strong re-tunes the
-- whole map's economy and is not.
EX.POS_TIERS = { -2, -1, 1, 2 }

-- HOW MANY LOTS OF NET WAR-GOODS POSITION EACH STEP IS WORTH.
EX.POS_STEP_LOTS = 4

-- pos_, not stock_ or trade_: derpy_chd_ex_trade_* and derpy_chd_ex_stock_* are both live
-- families, each applied by a sweep that removes the whole family before applying one of
-- it, so a collision in either direction would have one family deleting the other's
-- bundles - silently, and only on the factions that hold both. Mirrors pos_bundle() in the
-- generator; the DB rows are built from the same formula so the two cannot disagree.
function EX.pos_bundle_key(tier)
    return string.format("%spos_%s%02d", EX.PREFIX, tier < 0 and "neg" or "pos",
                         math.abs(tier))
end

EX.BUTTON_SIZE = 48     -- must match build_button() in tools/gen_exchange_ui.py
EX.BUTTON_GAP  = 4      -- clear space between the button and its anchor's visible left
-- HOW LONG THE OPENER BUTTON KEEPS TRYING. It used to be a flat 8 attempts - a 14-second
-- window from first tick - and that is a race the mod loses at random. resources_bar is
-- ANIMATED: it slides off the top of the screen for the intro, cutscenes and end-turn, and
-- while it is away Position() reports a real but useless y. Measured 2026-09-06 on one
-- 1920x1080 machine across six loads of the SAME build: by = -100, -527, -601, -640 while
-- hidden against -4 when settled, so the guard below correctly refuses - but the chain then
-- ran out and nothing ever tried again. SetVisible(true) is only on the success path, so the
-- button stayed created-but-invisible for the whole campaign and the panel had no way in.
-- Four loads won the race at 66-70s; the 12:33 load lost it and logged zero placements.
--
-- The terminator is now "placed at least once" (EX.button_at), not a countdown. The count
-- survives only so a CA rename of resources_bar cannot reschedule forever.
EX.PLACE_TRIES = 150    -- x2.0s = 5 minutes
                        -- edge. Was 12, which read as floating once the anchor moved to
                        -- the resource strip; flush against the strip's end-cap is what
                        -- makes it look like part of the bar rather than dropped near it.

EX.PANEL  = "derpy_chd_exchange_panel"
EX.ROW    = "derpy_chd_exchange_row"
EX.BUTTON = "derpy_chd_exchange_button"
EX.MODE_BTN = "derpy_chd_ex_mode"   -- uniquely named: the click listener matches on component
                                    -- name alone, and "close_button" is a name CA also uses
-- THE NAVIGATION IS TWO BUTTONS AND A COUNTER, bottom right, since 2026-09-07. It was one
-- forward-only cycle button in the title bar, which meant three clicks to reach the view
-- immediately to the left of you and no way at all to undo an overshoot.
EX.MODE_PREV = "derpy_chd_ex_prev"
-- THE VIEW TABS. One per entry in EX.MODES, named after the mode they select, so the click
-- listener maps a component straight back to a view with no second table to keep in step.
-- The prefix is ours and long: the listener matches on component name alone, and a name CA
-- also uses would fire this on unrelated panels.
EX.TAB_PREFIX = "derpy_chd_ex_tab_"
function EX.tab_name(mode) return EX.TAB_PREFIX .. mode end
-- SHORTER THAN THE TITLES, because these sit five across a strip rather than alone on a title
-- plate. "Ownership" is the stats view's own word - its title reads "Zharr Exchange:
-- Ownership" - so the tab and the title cannot disagree about what the player just opened.
--
-- SIX ACROSS SINCE STAGE 2, AT 108 WIDE ON A 116 PITCH. Five sat at 132 on 140 and ended at
-- 712, against the back arrow at 774; a sixth on that pitch would have started at 720 and
-- run to 852, straight through both nav buttons. The 8px gap between tabs is preserved and
-- the strip now ends at 708, so the two clusters still cannot touch.
EX.TAB_LABEL = {
    trade = "Trade", stats = "Ownership", offer = "Offerings",
    houses = "Houses", deals = "Deals", log = "Log",
}
EX.NAV_PAGE  = "nav_page"

-- The panel has two views over ONE set of components. A second panel file would mean a second
-- GUID range, a second set of imagepaths and soundcategories, and a second half of the
-- generator selftest - every one of which is a silent failure mode here. Instead the six text
-- cells per row are repositioned, resized and refilled, and the two trade buttons hide.
-- Which cell shows what per mode is EX.ROW_LAYOUT / EX.ROW_LAYOUT_STATS plus EX.refresh_panel.
-- ponytail: cell reuse holds while both views are six columns of text over one row shape. A
-- stats column needing a different SHAPE - sub-rows per holding faction, a wide bar - is where
-- this stops paying, and the upgrade is a second row .twui.xml in a new GUID range (DE19xxxx).
EX.MODE_TRADE = "trade"
EX.MODE_STATS = "stats"
EX.MODE_OFFER = "offer"
EX.MODE_HOUSES = "houses"
-- THE SIXTH VIEW (Stage 2). Deals the world posts TO the player, one turn at a time.
EX.MODE_DEALS = "deals"
-- The cycle button walks this list, so a mode is added by adding it here and giving it a
-- PANEL_LAYOUT_* / ROW_LAYOUT_* pair. EX.layout hides any component the current mode's table
-- does not name, which is what keeps an unplaced cell from sitting on top of another column.
EX.MODES = { "trade", "stats", "offer", "houses", "deals", "log" }
-- THE GUIDE IS A MODE BUT NOT A STOP ON THE CYCLE. It is deliberately absent from EX.MODES:
-- the cycle button walks the three TRADING views, and a player paging between them should not
-- have to step over the manual every third click. Its own button reaches it from any view.
EX.MODE_HELP = "help"
-- THE INTRODUCTION IS A MODE AND NOT A TAB, for the same reason the guide is not one: it
-- is not a place a trader goes, it is a page that happens once. It is not on EX.MODES and
-- has no button; EX.show puts the panel into it the first time a player opens it, and any
-- tab click leaves it for good.
EX.MODE_INTRO = "intro"
EX.HELP_BTN  = "btn_help"
EX.mode = EX.MODE_TRADE
EX.PANEL_FILE  = "ui/campaign ui/derpy_chd_exchange_panel"
EX.ROW_FILE    = "ui/campaign ui/derpy_chd_exchange_row"
EX.BUTTON_FILE = "ui/campaign ui/derpy_chd_exchange_button"

-- Must match COMMODITIES in tools/gen_zharr_exchange.py exactly. The generator's selftest reads
-- these lists back out of this file and fails if they ever drift apart.
EX.COMMODITIES = {
    "res_animals", "res_dyes", "res_gems", "res_gold_idols", "res_ivory",
    "res_medicine", "res_obsidian", "res_rom_furs", "res_rom_glass", "res_rom_iron",
    "res_rom_lead", "res_rom_marble", "res_rom_textiles", "res_rom_timber",
    "res_rom_wine", "res_spices", "res_trinkets",
}
-- Layer 2: CA's own pooled resources. Priced flat for now - they have no map supply signal.
-- LABOUR IS DELIBERATELY ABSENT. wh3_dlc23_chd_labour is FACTION_PROVINCE scope, and a
-- province-scoped pool is unreachable from script: measured 2026-09-04, both the faction's and
-- the province's pooled_resource_manager return a NULL INTERFACE for it (same for workload and
-- efficiency, the other two FACTION_PROVINCE pools), so cm:faction_add_pooled_resource moved
-- nothing and the row sat at "0 held" with a dead Buy button. See tools/gen_zharr_exchange.py.
EX.LAYER2 = { "wh3_dlc23_chd_armaments", "wh3_dlc23_chd_raw_materials" }

function EX.short(res)
    -- THE LEDGER'S SYNTHETIC KEYS, PASSED THROUGH UNCHANGED. "ord1".."ordN" are not
    -- instruments - see EX.mode_instruments's EX.on_orders() branch - and the guard is
    -- narrow (a full-string match, not a prefix) so no real key can ever take this path by
    -- coincidence; no vanilla resources_tables key or house faction key is shaped like this.
    if string.match(res, "^ord%d+$") then return res end
    -- AND THE DEALS PAGE'S, for the same reason: two deals can name one commodity (measured
    -- - the shipped fixture posts glass twice), which would collide on a single component.
    if string.match(res, "^dl%d+$") then return res end
    if res == "wh3_dlc23_chd_armaments" then return "armaments" end
    if res == "wh3_dlc23_chd_raw_materials" then return "raw_materials" end
    return string.gsub(res, "^res_", "")
end

-- Display name and icon per instrument, both taken from CA rather than derived from the key.
-- THE KEY IS NOT THE NAME. res_rom_lead is "Salt", res_rom_glass is "Dwarf Beer" and
-- res_rom_textiles is "Pottery" - Rome-era keys CA repurposed - so stripping the prefix off the
-- key produced three wrong names and fourteen ugly ones. Names come from
-- resources_onscreen_text_<key> in the loc (resources_tables has NO name column at all), icons
-- from resources_tables.icon_filepath. Regenerate with tools/read_vanilla_loc.py.
EX.INFO = {
    ["res_animals"] = { "Exotic Animals", "ui/campaign ui/effect_bundles/resource_animals.png" },
    ["res_dyes"] = { "Dyes", "ui/campaign ui/effect_bundles/resource_dyes.png" },
    ["res_gems"] = { "Gemstones", "ui/campaign ui/effect_bundles/resource_gemstones.png" },
    ["res_gold_idols"] = { "Golden Idols", "ui/campaign ui/effect_bundles/resource_gold_idols.png" },
    ["res_ivory"] = { "Tusks", "ui/campaign ui/effect_bundles/resource_ivory.png" },
    ["res_medicine"] = { "Medicinal Plants", "ui/campaign ui/effect_bundles/resource_medicine.png" },
    ["res_obsidian"] = { "Carved Obsidian", "ui/campaign ui/effect_bundles/resource_obsidian.png" },
    ["res_rom_furs"] = { "Furs", "ui/campaign ui/effect_bundles/resource_furs.png" },
    ["res_rom_glass"] = { "Dwarf Beer", "ui/campaign ui/effect_bundles/resource_dwarf_beer.png" },
    ["res_rom_iron"] = { "Iron", "ui/campaign ui/effect_bundles/resource_iron.png" },
    ["res_rom_lead"] = { "Salt", "ui/campaign ui/effect_bundles/resource_salt.png" },
    ["res_rom_marble"] = { "Marble", "ui/campaign ui/effect_bundles/resource_marble.png" },
    ["res_rom_textiles"] = { "Pottery", "ui/campaign ui/effect_bundles/resource_pottery.png" },
    ["res_rom_timber"] = { "Timber", "ui/campaign ui/effect_bundles/resource_timber.png" },
    ["res_rom_wine"] = { "Wine", "ui/campaign ui/effect_bundles/resource_wine.png" },
    ["res_spices"] = { "Spices", "ui/campaign ui/effect_bundles/resource_spices.png" },
    ["res_trinkets"] = { "Elven Trinkets", "ui/campaign ui/effect_bundles/resource_trinkets.png" },
    ["wh3_dlc23_chd_armaments"] = { "Armaments", "ui/skins/default/icon_chd_armaments.png" },
    ["wh3_dlc23_chd_raw_materials"] = { "Raw Materials", "ui/skins/default/icon_chd_raw_materials.png" },
}

function EX.display(res)
    local i = EX.INFO[res]
    return i and i[1] or EX.short(res)
end

function EX.icon(res)
    local i = EX.INFO[res]
    if i then return i[2] end
    -- A house is not in EX.INFO - that table is the generated commodity list - so without this
    -- branch EX.icon returned nil for every house and the row kept the gold bar from the XML.
    if EX.is_house(res) then return EX.house_icon(res) end
    return nil
end

-- A HOUSE'S ICON IS ITS OWN FLAG. faction:flag_path() is documented as "Gets the flag folder
-- path used by this faction" (scripting_doc.html) and hands back factions_tables.flags_path
-- VERBATIM - separators included, and they are NOT consistent. Measured in a live campaign
-- 2026-09-07:
--     wh3_dlc23_chd_zhatan             ui\flags\wh3_dlc23_chd_zhatan       <- backslashes
--     cr_chd_slaves_of_the_black_dwarf ui/flags/cr_chd_slaves_of_the_black_dwarf <- forward
-- All four of CA's rows use backslashes and two of the three modded ones use forward slashes,
-- so normalising is load-bearing rather than tidy-up.
--
-- mon_24.png BECAUSE THE CELL IS 24x24 in derpy_chd_exchange_row.twui.xml. Every CHD faction in
-- ui.pack ships that file, wh3_dlc23_chd_minor_faction included - checked with read_pack_index.
--
-- Nil, never a guess, when the faction is gone or declares no path: the row then keeps its gold
-- bar. A WRONG path is strictly worse than none, because a missing imagepath draws a blank
-- square and logs nothing at all.
function EX.house_icon(house)
    local f = cm:get_faction(house)
    if not f then return nil end
    local ok, p = pcall(function() return f:flag_path() end)
    if not ok or type(p) ~= "string" or p == "" then return nil end
    -- parenthesised: gsub returns (string, count) and the count must not reach the caller
    return (string.gsub(p, "\\", "/")) .. "/mon_24.png"
end

function EX.is_layer2(res)
    for _, k in ipairs(EX.LAYER2) do
        if k == res then return true end
    end
    return false
end

-- Memoised like EX.is_commodity: every exclusion guard in the file calls this.
function EX.is_house(res)
    if not EX.house_set then
        EX.house_set = {}
        for _, k in ipairs(EX.houses) do EX.house_set[k] = true end
    end
    if EX.house_set[res] then return true end
    -- A HOUSE WE HOLD IS AN INSTRUMENT EVEN IF IT IS NOT IN THE DISCOVERED LIST. It dies,
    -- it drops out of faction_list, and without this its position becomes unreachable -
    -- no row, no price, no settlement, and the gold the player spent is simply gone.
    return (EX.shares_held[res] or 0) > 0
end

-- "EVERY LIVING CHAOS DWARF FACTION" - and the three words that are not "Chaos Dwarf" all do
-- work. The subculture is not only houses: CA ships wh3_dlc23_chd_chaos_dwarfs_rebels, the
-- _qb1/_qb2/_qb3 quest-battle shells and wh3_dlc25_chd_chaos_dwarfs_invasion inside it. None
-- of them is a house anyone can buy a stake in, and none can be absorbed - but EX.houses only
-- ever GROWS and EX.delisted is permanent, so discovering one once leaves a greyed "gone" row
-- on the panel for the rest of the campaign.
--
-- All three reads are free: this runs once per campaign, not per turn.
--
-- FAILS CLOSED. A read that errors excludes the faction rather than admitting it. A wrong
-- exclusion leaves one house out of the view for this campaign; a wrong inclusion is a dead
-- row that nothing can ever remove. Recoverable beats permanent.
function EX.tradeable_faction(f)
    local ok, bad = pcall(function()
        return f:is_dead() or f:is_rebel() or f:is_quest_battle_faction()
    end)
    if not ok or bad ~= false then return false end
    -- PRESENT ON THE MAP, AND is_dead() DOES NOT ESTABLISH THAT. Measured on a fresh campaign
    -- 2026-09-07: mixer_chd_black_kraken, mixer_chd_gargath and mixer_chd_lost_slavers own no
    -- region, no army and no character anywhere, yet answered is_dead() == FALSE during the
    -- first-tick walk and true a moment later. The window is one tick wide and discovery sits
    -- in it, so all three were listed - and discovery is a UNION, so once in they never left.
    -- They drew three rows with a raw key for a name, "gone" for a seat and a red "Lo".
    local regions, forces = 0, 0
    pcall(function() regions = f:region_list():num_items() end)
    pcall(function() forces = f:military_force_list():num_items() end)
    -- OR, NOT AND. cr_chd_black_kraken_armada is a CHARACTER_BOUND_HORDE and owns zero regions
    -- for its whole life; requiring territory would delist the one house that never has any.
    return regions > 0 or forces > 0
end

-- Walked once per session (see the first-tick block), not per turn. ~250 factions and one
-- culture() call each. MERGES with the saved list rather than replacing it, so EX.houses
-- only ever grows within a campaign - it never shrinks back to whatever this session's walk
-- alone finds.
--
-- This is deliberate, not an oversight. Whether WH3's faction_list() still reports a dead or
-- confederated faction is not settled anywhere CA ships, and a design that does not need to
-- know the answer beats a correct guess about engine behaviour nobody could confirm. A house
-- dropping out of the list is exactly what strands a still-held position - EX.restore() only
-- rebuilds EX.shares_held for houses IN EX.houses - and a union can never drop one.
function EX.discover_houses()
    -- Seed from what is already known, not from an empty table, so a faction this session's
    -- walk does not report is carried forward rather than lost.
    local found = {}
    local hs = EX.getv(EX.SAVE_HOUSES)
    if hs and hs ~= "" then
        for k in string.gmatch(hs, "[^;]+") do
            -- CARRIED FORWARD ONLY IF WE STILL HOLD IT. The union exists for exactly one
            -- reason - EX.restore rebuilds EX.shares_held by walking EX.houses, so a key that
            -- drops out of the list strands the position inside it. A key we hold NOTHING in
            -- has nothing to strand, so re-deriving it from the live walk costs us nothing and
            -- stops a faction discovered in error from being permanent. Before this, one bad
            -- tick of is_dead() put three phantom rows in the save for good.
            --
            -- Read out of the store directly, not through EX.held: EX.restore has not run yet
            -- when this is called, so EX.shares_held is still empty.
            --
            -- ANY HUMAN'S POSITION KEEPS THE ROW, not just this client's. The list is world
            -- state and every machine has to build the same one; dropping a house because the
            -- player on THIS machine holds nothing in it would strand the position of whoever
            -- does, and would drop a different row on each machine.
            for _, h in ipairs(EX.humans()) do
                if (tonumber(EX.getp(EX.SAVE_SHARES .. k, h)) or 0) > 0 then
                    found[k] = true
                    break
                end
            end
        end
    end
    pcall(function()
        local fl = cm:model():world():faction_list()
        for i = 0, fl:num_items() - 1 do
            local f = fl:item_at(i)
            if f and not f:is_null_interface() then
                local name = f:name()
                -- EVERY HUMAN IS EXCLUDED, not only this client's faction: you cannot buy
                -- yourself, the settlement branch would otherwise try to pay out on your own
                -- death, and in multiplayer a board that listed the other players as houses
                -- would let one buy the other's collapse. EX.is_human answers the same on
                -- every machine; cm:get_local_faction_name does not, and excluding only the
                -- local player would have built a different house list per client.
                if not EX.is_human(name) and EX.is_house_culture(f:culture())
                        and EX.tradeable_faction(f) then
                    found[name] = true
                end
            end
        end
    end)
    local list = {}
    for k in pairs(found) do list[#list + 1] = k end
    table.sort(list)                      -- stable row order across loads
    EX.houses = list
    EX.house_set = nil
    EX.setv(EX.SAVE_HOUSES, table.concat(list, ";"))
end

-- Memoised: EX.region_goods asks this once per built slot on every region, every turn.
EX.commodity_set = nil
function EX.is_commodity(res)
    if not EX.commodity_set then
        EX.commodity_set = {}
        for _, k in ipairs(EX.COMMODITIES) do EX.commodity_set[k] = true end
    end
    return EX.commodity_set[res] == true
end

function EX.lot(res)
    if EX.is_house(res) then return EX.HOUSE_LOT_SIZE end
    if EX.is_layer2(res) then return EX.L2_LOT_SIZE end
    return EX.LOT_SIZE
end

-- THE PANEL'S ROW CEILING, and it is geometry, not a preference. rows_holder is 560px tall in
-- derpy_chd_exchange_panel.twui.xml and EX.layout places rows EX.ROW_PITCH apart, so 560 / 28
-- = 20 slots. Row 21 lands below the panel: drawn, interactive, and off screen. Both numbers
-- are cross-checked against the shipped .twui.xml by check_help_lines() in
-- tools/gen_zharr_exchange.py, because neither file can see the other's copy.
EX.ROW_PITCH = 28
EX.MAX_ROWS  = 20

-- THE PANEL GROWS WITH THE SCREEN (2026-09-24; docs/superpowers/specs/
-- 2026-09-24-exchange-ui-scale-design.md). 4K players reported it too small: it was 920x736 on
-- every screen. Same model as the Iron Court - two layouts, blended. Every layout table in this
-- file IS the 1600x900 end, unchanged; the 2560x1440 end is derived from it by the rule in
-- EX.grow, and anything between is placed proportionally. EX.MAX_ROWS above is the 1600x900
-- value; EX.fit rewrites it on every layout pass. Text does not grow - its size is fixed in
-- the .twui.xml.
--
-- 1600 IS THE FLOOR A SCRIPT EVER SEES: the root reports the window divided by UI Scale,
-- clamped to at least 1600x900 (HANDOFF_20260924_GUILDS_UI_SCALE.md section 1). 2560 is the
-- cap: past it, normal-size text in columns that wide loses the eye along the line.
--
-- INTEGER ARITHMETIC, NOT A FACTOR. Game Lua is float32; floor((v * box + 800) / 1600) stays
-- exact for every v * box here (all under 2^24), where v * 1.6 would not.
EX.ROWS_BASE = EX.MAX_ROWS
EX.BASE_W    = 920          -- PANEL_W in tools/gen_exchange_ui.py
EX.BASE_H    = 736          -- PANEL_H
EX.BOX_MIN   = 1600
EX.BOX_MAX   = 2560
EX.BOX       = 1600
EX.GROW_E    = 0
EX.PANEL_DW  = 0
EX.CHART_G   = 0
-- AT OR BELOW THIS y A CELL IS THE BOTTOM STRIP (footers 636/662, tabs 698, nav 696/701) and
-- moves down with the panel's bottom edge. No other table cell sits below 600.
EX.GROW_BOTTOM = 600

function EX.sc(v)
    return math.floor((v * EX.BOX + 800) / 1600)
end

-- KEEP SIZE: art with a fixed shape. Moves with its column and is never stretched. hdr_spark
-- is here because it is right-aligned over the sparkline and pinned to its width, and the
-- sparkline's bars are fixed.
EX.GROW_FIXED = { icon = true, chart_icon = true, spark = true, hdr_spark = true,
                  btn_buy = true, btn_sell = true,
                  btn_amt_down = true, btn_amt_up = true, ord_down = true, ord_up = true,
                  ord_qty_down = true, ord_qty_up = true }
-- STICK RIGHT: keeps today's distance from the panel's right edge, and its size.
EX.GROW_RIGHT = { close_button = true, btn_help = true, derpy_chd_ex_prev = true,
                  nav_page = true, derpy_chd_ex_mode = true }
-- THE CHART PAGE ONLY: the fraction of the plot's growth (EX.CHART_G) a cell moves down by.
-- The mid gridline is half way down the plot; the low one and everything under the plot move
-- with its bottom. The orders page's ticket is NOT here - it sits under at most EX.ORDER_MAX
-- rows, which fit above it already.
EX.GROW_CHART_Y = { chart_y_mid = 0.5, chart_grid_mid = 0.5,
                    chart_y_lo = 1, chart_grid_lo = 1,
                    chart_x_left = 1, chart_x_mid = 1, chart_x_right = 1,
                    chart_axis = 1, chart_stats = 1, chart_note = 1,
                    ord_side = 1, ord_cmp = 1, ord_down = 1, ord_price = 1, ord_up = 1,
                    ord_place = 1, ord_qty_down = 1, ord_qty = 1, ord_qty_up = 1,
                    ord_standing = 1, ord_cost = 1 }
-- WIDENED FROM ITS .twui.xml WIDTH: a cell no table gives a width, which would otherwise keep
-- its 1600x900 width on a grown panel. The footers are why this exists beyond the divider:
-- their text is trimmed to the component's own width (local fit, below), so an unwidened
-- footer still cut the longest lines to "..." in a panel with 500px to spare (review,
-- 2026-09-24). check_scale_far_end refuses any widenable cell missing from here.
EX.GROW_BASE_W = { divider = 868,       -- ROW_W - 12 in tools/gen_exchange_ui.py
                   footer_text = 880, footer_text2 = 880, title_text = 400 }

-- The box, the panel and the row ceiling for a screen. Called by EX.layout on every pass, so
-- a player who changes UI Scale gets the new size on the next open or tab click.
function EX.fit(sw, sh)
    local box = math.floor(math.min(sw, sh * 16 / 9))
    if box < EX.BOX_MIN then box = EX.BOX_MIN end
    if box > EX.BOX_MAX then box = EX.BOX_MAX end
    EX.BOX = box
    local pw, ph = EX.sc(EX.BASE_W), EX.sc(EX.BASE_H)
    EX.PANEL_DW = pw - EX.BASE_W
    EX.GROW_E = ph - EX.BASE_H
    EX.CHART_G = EX.sc(EX.CHART_H) - EX.CHART_H
    EX.MAX_ROWS = EX.ROWS_BASE + math.floor(EX.GROW_E / EX.ROW_PITCH)
    return box, pw, ph, EX.MAX_ROWS
end

-- One layout entry at the current box: x, y and width (nil = leave the width alone). `chart`
-- is true only for EX.PANEL_LAYOUT_CHART. A widened cell grows by the same factor its x does
-- and a fixed one only moves, so no gap between two cells can shrink as the box grows.
function EX.grow(e, chart)
    local id, x, y, w = e[1], e[2], e[3], e[4]
    local nx, nw = EX.sc(x), w
    if EX.GROW_RIGHT[id] then
        nx = x + EX.PANEL_DW
    elseif w and not EX.GROW_FIXED[id] then
        nw = EX.sc(w)
    end
    if not w and EX.GROW_BASE_W[id] then nw = EX.sc(EX.GROW_BASE_W[id]) end
    local ny = y
    local f = chart and EX.GROW_CHART_Y[id]
    if f then
        ny = y + math.floor(f * EX.CHART_G + 0.5)
    elseif y >= EX.GROW_BOTTOM then
        ny = y + EX.GROW_E
    end
    return nx, ny, nw
end

-- Every tradeable thing, commodities first, in the same order the DB rows were generated,
-- then layer 2, then the discovered houses. Houses come last so adding one never shifts a
-- commodity's position in any list that indexes by number. This is the list rows_holder gets
-- one ROW COMPONENT per; what a given view actually draws is EX.mode_instruments().
function EX.instruments()
    local t = {}
    for _, r in ipairs(EX.COMMODITIES) do t[#t + 1] = r end
    for _, r in ipairs(EX.LAYER2) do t[#t + 1] = r end
    for _, r in ipairs(EX.houses) do t[#t + 1] = r end
    -- NO shares_held FALLBACK HERE. There used to be one, appending any held house EX.houses
    -- did not name - dead code, because EX.discover_houses() MERGES with the saved list and so
    -- EX.houses can never lose a house we hold. The equivalent fallback in EX.is_house() stays:
    -- that one is what keeps EX.held() reading the save state rather than the pooled-resource
    -- branch if the two tables ever do disagree, and it costs one table lookup instead of a
    -- pairs() walk on every enumeration.
    return t
end

-- WHAT THIS MODE DRAWS, which is NOT the whole instrument list.
--
-- Every view used to iterate EX.instruments(), so the Houses view opened on 19 commodity rows
-- fed through the houses branch - row_name a raw key like "res_animals", Seat reading "horde"
-- because cm:get_faction("res_animals") is false, a Div column for a dividend that is never
-- paid, and live Buy/Sell buttons - with the actual houses starting at slot 20. Two of those
-- 19 were the Offerings view's own fault in reverse: a house row there read "Ready" beside a
-- button reading "Insufficient".
--
-- TRUNCATED AT EX.MAX_ROWS. rows_holder is 560px and rows are EX.ROW_PITCH apart, so slot 21
-- is MoveTo'd past the panel's bottom edge - still a live component with live buttons, simply
-- not on the panel, and nothing errors. The commodity list is 19 and fixed; the HOUSE list is
-- discovered and vanilla alone ships about eleven Chaos Dwarf factions with the lords pack
-- adding ten more. The Houses footer says how many are not shown, which is the honest answer -
-- a row drawn off the bottom edge is invisible AND clickable, which is worse than absent.
-- WHICH PAGE OF HOUSES IS SHOWING. VIEW STATE ONLY, never saved - same as EX.log_page and
-- EX.help_page. A saved page would reopen the view three pages away from the house the
-- player clicked "Houses" to look at.
EX.house_page = 1

-- HOW MANY FOREIGN HOUSES THE BOARD LISTS. Own-culture houses, and anything the player holds,
-- are ALWAYS listed and do not count against this - see EX.listed_houses.
--
-- 60 IS THREE PAGES OF EX.MAX_ROWS. Bloc-scoped discovery puts 70-130 factions in reach of an
-- Order or Destruction player against the ten this board shipped with, and six or seven pages
-- with no way to narrow is not a board anybody reads. The cap is the cheap half of that
-- answer; a filter is the expensive half and is deliberately not built.
EX.HOUSE_LIST_MAX = 60

-- THE HOUSES THE BOARD ACTUALLY LISTS, in the order it lists them. EX.house_pages and
-- EX.house_slice must BOTH read this, or the page counter names pages the slice cannot reach.
--
-- THREE STEPS, IN THIS ORDER:
--   1. Sort, by whatever column the player picked. EX.sorted returns EX.houses itself when
--      nothing is picked, so the default path allocates nothing extra here.
--   2. Split own-culture from foreign, each group keeping its sorted order. Own people first,
--      under EVERY column - the home board is the one you came for, and a sort inside it is
--      still a sort. This is a per-client DISPLAY order and so may read EX.HOUSE_CULTURE; the
--      row LIST may not, which is why EX.is_house_culture reads EX.BLOCS instead.
--   3. Cap the foreign tail by power, keeping anything held whatever its rank. Dropping a
--      house the player holds would hide a live position, which is strictly worse than a
--      long list.
--
-- POWER IS READ STRAIGHT OUT OF EX.house_regions, not through EX.house_power_of. That accessor
-- falls back to cm:get_faction for a house the scan has not seen, which is right when pricing
-- one house and wrong when ranking a hundred of them about once a second. Before the first
-- turn-start scan every power reads 0, so the cap keeps a stable alphabetical subset for one
-- turn and the right one from then on.
function EX.listed_houses()
    local all = EX.sorted(EX.houses)
    local mine, theirs = {}, {}
    for i = 1, #all do
        local h = all[i]
        if EX.is_own_house(h) then mine[#mine + 1] = h else theirs[#theirs + 1] = h end
    end
    if #theirs > EX.HOUSE_LIST_MAX then
        local reg = EX.house_regions or {}
        local keyed = {}
        for i = 1, #theirs do
            keyed[i] = { h = theirs[i], i = i, p = reg[theirs[i]] or 0 }
        end
        -- Tiebroken on the pre-cap index, for the reason EX.sorted is: table.sort is not
        -- stable in Lua 5.1, and a board that reshuffles once a second reads as broken.
        table.sort(keyed, function(a, b)
            if a.p ~= b.p then return a.p > b.p end
            return a.i < b.i
        end)
        local keep = {}
        for i = 1, EX.HOUSE_LIST_MAX do
            local e = keyed[i]
            if not e then break end
            keep[e.h] = true
        end
        local out = {}
        for i = 1, #theirs do
            local h = theirs[i]
            -- EX.held reads the SAVE STATE for a house, not a pooled resource - see the note
            -- on the is_house fallback in EX.instruments - so this costs a table lookup.
            if keep[h] or (EX.held(h) or 0) > 0 then out[#out + 1] = h end
        end
        theirs = out
    end
    for i = 1, #theirs do mine[#mine + 1] = theirs[i] end
    return mine
end

function EX.house_pages()
    local n = math.ceil(#EX.listed_houses() / EX.MAX_ROWS)
    if n < 1 then n = 1 end
    return n
end

-- THE SLICE, AND ITS CLAMP. The clamp lives HERE, not only where the arrows move the index -
-- exactly as EX.log_lines clamps inside itself. EX.check_delistings and EX.prune_houses both
-- shorten EX.houses at turn start, so a page index that was valid when the player set it can
-- be past the end by the time this runs, and an out-of-range page draws an empty view that
-- reads exactly like a market with no houses in it.
function EX.house_slice()
    local pages = EX.house_pages()
    if EX.house_page > pages then EX.house_page = pages end
    if EX.house_page < 1 then EX.house_page = 1 end
    -- SORTED FIRST, PAGED SECOND. The other way round orders the twenty rows on whichever
    -- page the player happens to be on and leaves the rest untouched, which looks like sorting
    -- and is not. The sort, the own-people-first split and the power cap all live in
    -- EX.listed_houses, which EX.house_pages above reads too - the page counter and this slice
    -- MUST walk one list or the counter names a page the slice returns empty.
    local all = EX.listed_houses()
    local out = {}
    local from = (EX.house_page - 1) * EX.MAX_ROWS
    for j = 1, EX.MAX_ROWS do
        local h = all[from + j]
        if not h then break end
        out[#out + 1] = h
    end
    return out
end

function EX.mode_instruments()
    local t = {}
    -- ONE ROW PER STANDING ORDER, in placement order - the same order EX.fill_orders walks,
    -- so the ledger reads top to bottom in the order things will happen.
    --
    -- ROWS ARE KEYED BY ORDER INDEX HERE, NOT BY INSTRUMENT, and that is forced rather than
    -- stylistic: rows are created one per key as EX.ROW .. "_" .. EX.short(key), so two
    -- orders on one commodity - a ladder, which is the whole reason the list is a list and
    -- not one slot per instrument - would collide on a single component. The order carries
    -- its own resource (o.res), so nothing downstream loses it - see EX.refresh_panel's
    -- EX.on_orders() branch and EX.order_of_row.
    if EX.on_orders() then
        for i = 1, #EX.orders do t[#t + 1] = string.format("ord%d", i) end
        return t
    end
    -- THE CHART PAGE DRAWS NO ROWS. Returning empty here is what makes EX.layout's hide
    -- pass take every row off screen: that pass builds its keep-set from this list.
    if EX.on_chart() then return t end
    -- ONE ROW PER POSTED DEAL, keyed by position for the reason the ledger is: two deals can
    -- name one commodity and would collide on a single component. An empty list hands back
    -- nothing, which is what hides every row and leaves the footer to say why.
    if EX.mode == EX.MODE_DEALS then
        for i = 1, #EX.deals do t[#t + 1] = string.format("dl%d", i) end
        return t
    end
    if EX.mode == EX.MODE_HOUSES then
        -- PAGED, NOT TRUNCATED. The old `while #t > EX.MAX_ROWS do t[#t] = nil end` ran
        -- against an ALPHABETICALLY SORTED list, so everything past slot 20 was dropped for
        -- good - already a live fault at 20 Chaos Dwarf houses (10 vanilla plus the lords
        -- pack's 10, exactly on the limit), and it would have listed an Empire player
        -- Averland through Nordland and silently lost Reikland, Stirland and Talabecland.
        return EX.house_slice()
    end
    for _, r in ipairs(EX.COMMODITIES) do t[#t + 1] = r end
    for _, r in ipairs(EX.LAYER2) do t[#t + 1] = r end
    -- The commodity list is 19 at most - 17 plus the Chaos Dwarf pair - against 20 slots, so
    -- this can only ever be a no-op. Kept as the guard it is.
    while #t > EX.MAX_ROWS do t[#t] = nil end
    return EX.sorted(t)
end

function EX.median(t)
    local s = {}
    for _, v in ipairs(t) do s[#s + 1] = v end
    table.sort(s)
    if #s == 0 then return 1 end
    local mid = math.floor(#s / 2)
    if #s % 2 == 1 then return s[mid + 1] end
    return (s[mid] + s[mid + 1]) / 2
end

-- Herfindahl-Hirschman index of an ownership table {faction_name -> output amount}.
-- 1.0 = one faction produces every unit of supply; ~1/n = spread evenly over n factions.
-- Pure, so tools/gen_zharr_exchange.py can run it under lua.exe against the Python side.
function EX.hhi(counts)
    local total = 0
    for _, n in pairs(counts) do total = total + n end
    if total <= 0 then return 0 end
    local h = 0
    for _, n in pairs(counts) do
        local s = n / total
        h = h + s * s
    end
    return h
end

-- Concentrated supply trades dearer: twelve Iron regions in one faction's hands is not the
-- same market as twelve spread over eight. A DIVISOR, not a multiplier - `raw * (1 - hhi)`
-- would take a monopoly to zero and peg every cartel at MULT_MAX, which reads as "absent from
-- the map" and is a different thing entirely.
--
-- EX.CONCENTRATION_K MUST MATCH CONCENTRATION_K in tools/gen_zharr_exchange.py; the generator
-- selftest runs this function under lua.exe and fails if they drift. K=1 was MEASURED INERT in
-- game: real maps spread every commodity over 19-49 owners, so HHI is 0.02-0.05 and a 3%
-- divisor is finer than the ladder's own 10% rungs. See the Python side for the full reading.
EX.CONCENTRATION_K = 10

function EX.effective_supply(raw, h)
    return raw / (1 + EX.CONCENTRATION_K * h)
end

function EX.price_multiplier(supply, median_supply)
    if supply <= 0 then return EX.MULT_MAX end
    local m = (median_supply / supply) ^ EX.EXPONENT
    if m < EX.MULT_MIN then return EX.MULT_MIN end
    if m > EX.MULT_MAX then return EX.MULT_MAX end
    return m
end

-- NOT EX.price_multiplier, WHICH IS INVERTED. That one is (median / supply) ^ EXPONENT
-- because a scarce commodity is dear. A house is the opposite: more territory is worth more.
-- Reusing the commodity function here prices the entire view upside down and nothing about
-- it looks wrong on screen - the numbers still move, they just move the wrong way.
function EX.house_multiplier(power, median_power)
    if not power or power <= 0 then return EX.MULT_MIN end
    if not median_power or median_power <= 0 then return 1.0 end
    local m = (power / median_power) ^ EX.EXPONENT
    if m < EX.MULT_MIN then return EX.MULT_MIN end
    if m > EX.MULT_MAX then return EX.MULT_MAX end
    return m
end

-- Territory, or an army where there is no territory AND THERE NEVER WAS ANY.
--
-- ZERO REGIONS HAS TWO OPPOSITE CAUSES and the army fallback is only right for one of them: a
-- CHARACTER_BOUND_HORDE that owns none by design, and a settled house that has just lost its
-- last one. Reading armies for both prices a collapsing three-army house at 6 - ABOVE a
-- healthy four-region rival - on the very turn it is destroyed, which is the seat signal
-- running backwards. has_home_region() separates them and it is the same read EX.holds_capital
-- already makes: a horde has none.
--
-- The pcall defaults to SETTLED, so an unreadable interface prices at the ladder floor rather
-- than off an army count. That is the safe direction here - the fault being fixed is the
-- inflation, not the floor.
function EX.house_power(f)
    if not f or f:is_null_interface() then return 0 end
    local regions = 0
    pcall(function() regions = f:region_list():num_items() end)
    if regions > 0 then return regions end
    local settled = true
    pcall(function() settled = f:has_home_region() end)
    if settled then return 0 end
    local forces = 0
    pcall(function() forces = f:military_force_list():num_items() end)
    return forces * EX.HORDE_WEIGHT
end

-- WHERE ITS CAPITAL IS, remembered while there is still a faction to ask. A house that dies -
-- and confederation, which is how a Tower of Zharr seat claim kills one, is the case that
-- matters - answers cm:get_faction with FALSE, so home_region() is unreachable from the moment
-- it counts. The key outlives it; the region does not go anywhere.
--
-- Only writes on a change. EX.target_rung is the caller and it runs 0.1s after every trade as
-- well as at turn start, so an unconditional set_saved_value would be a write per house per
-- click for a string that changes about twice a campaign.
function EX.remember_home(house, f)
    if not f or f:is_null_interface() then return end
    local key = nil
    pcall(function()
        local r = f:home_region()
        if r and not r:is_null_interface() then key = r:name() end
    end)
    if key and key ~= "" and EX.house_home[house] ~= key then
        EX.house_home[house] = key
        EX.setv(EX.SAVE_HOME .. house, key)
    end
end

-- true held, false lost, NIL for a faction that has no capital to lose (a horde). The three
-- states are distinct on purpose: false cuts the price by EX.SEAT_LOST and draws "LOST",
-- and a horde is not in trouble, it simply has nothing to hold.
function EX.holds_capital(f)
    if not f or f:is_null_interface() then return nil end
    local has = false
    pcall(function() has = f:has_home_region() end)
    if not has then return nil end
    local held = nil
    pcall(function()
        local r = f:home_region()
        if r and not r:is_null_interface() then
            local o = r:owning_faction()
            held = (o and not o:is_null_interface() and o:name() == f:name()) or false
        end
    end)
    return held
end

-- 1-based, so rung 1 is the cheapest. The Python side is 0-based; the bundle key suffix is
-- the Python index, so bundle_key subtracts 1.
function EX.ladder_index(multiplier)
    if multiplier <= 0 then return 1 end
    local n = math.floor(math.log(multiplier) / math.log(EX.opt("ladder_step")) + 0.5)
    local i = n - EX.LADDER_LO + 1
    if i < 1 then return 1 end
    if i > EX.RUNGS then return EX.RUNGS end
    return i
end

function EX.bundle_key(res, index_1based)
    return string.format("%sladder_%s_%02d", EX.PREFIX, EX.short(res), index_1based - 1)
end

function EX.hold_key(res)
    if EX.is_layer2(res) then return res end
    return EX.PREFIX .. "hold_" .. EX.short(res)
end

-- The gold a lot costs at a given rung. This MUST equal what the game charges, which is
-- base * (1 + the applied bundle's percentage_cost_mod) - hence percentage_cost_increase_per_use
-- being zero in the DB. Anything else and the panel lies about the price.
function EX.price_at(rung)
    local pct = (EX.opt("ladder_step") ^ (rung - 1 + EX.LADDER_LO)) - 1
    return math.floor(EX.BASE_COST * (1 + pct) + 0.5)
end

function EX.neutral_rung()
    return -EX.LADDER_LO + 1
end

-- Rungs moved by our own trading. TRUNCATES TOWARD ZERO, which math.floor does not:
-- floor(-1/4) is -1 while floor(1/4) is 0, so ONE sold lot used to drop the price a full rung
-- where buying took four to raise it. That asymmetry was an accident of rounding, not a design
-- choice, and it is what let a liquidation mark a commodity down six rungs on the way out.
function EX.pressure_shift(p)
    local q = math.floor(math.abs(p) / EX.opt("pressure_per_rung"))
    if q == 0 then return 0 end     -- Lua 5.1 has -0, and it stringifies as "-0"
    if p < 0 then return -q end
    return q
end

-- THE GUILD'S POSITION, in rungs. The LEVEL, not the turn's flow: the guild being long iron
-- is what makes iron dear; the fact that it bought some this particular turn is news, and the
-- footer is where news goes.
--
-- This sits beside EX.pressure_shift and not beside EX.appetite_shift on purpose. Appetite is
-- a level recomputed from the map with no state to drift; a book is a position somebody took
-- and it persists. See the amended note above EX.CULTURE_WANTS.
--
-- SAME TRUNCATION TRAP as pressure_shift and appetite_shift: math.floor(-0.5) is -1, so
-- flooring a signed quantity would mark a good down on a guild position too small to mark it
-- up. Truncate the magnitude, then re-apply the sign.
function EX.book_shift(res)
    if EX.is_house(res) then return 0 end     -- a share is paper; no book is held in it
    if EX.is_layer2(res) then return 0 end    -- the Forge's output, not a traded good
    local net = EX.guild_book(res)
    local q = math.floor(math.abs(net) / EX.opt("book_per_rung"))
    if q > EX.opt("book_max") then q = EX.opt("book_max") end
    if q == 0 then return 0 end               -- Lua 5.1 has -0 and it stringifies as "-0"
    if net < 0 then return -q end
    return q
end

-- THE WORLD TIER'S PRICING TERM. A SECOND term, never folded into EX.book_shift: that
-- function's constants are calibrated against a fourteen-house book, and the spread floor
-- resting on them is what stands between the player and the measured +906 gold from 55 free
-- round trips. Its own gain, its own clamp, its own switch.
-- Truncated TOWARD ZERO, the same trap as EX.appetite_shift and EX.pressure_shift:
-- math.floor(-0.5) is -1, so flooring a signed shift moves a price DOWN on a position too
-- small to move it up.
function EX.world_book_shift(res)
    if not EX.setting("ai_world") then return 0 end
    if EX.is_house(res) or EX.is_layer2(res) then return 0 end
    local net = EX.world_book(res)
    if net == 0 then return 0 end
    local v = EX.opt("world_gain") * net / 100
    local q = math.floor(math.abs(v))
    if q > EX.opt("ai_max_rungs") then q = EX.opt("ai_max_rungs") end
    if q == 0 then return 0 end
    if v < 0 then return -q end
    return q
end

-- What a sell actually pays. It has its OWN column since 2026-09-06 - see the SELL COLUMN note
-- on EX.PANEL_LAYOUT. Before that the panel drew the buy price alone and named the cut only in
-- the Sell button's tooltip, which hid the one number a player needs to close a position.
-- WHAT YOU PAY, as opposed to what the thing is worth. EX.price stays the world price and
-- remains what the ladder, the sparkline, the dividend and every house's own trading read;
-- this is the only number that should ever be charged to the player or drawn in the Buy
-- column. The design doc's rule: the displayed price must equal what the game charges.
-- ROUNDING IS CONSERVATIVE ON THE DISCOUNTED SIDE, and only there.
--
-- The two-sided cap is exact in real numbers, but both prices are rounded to whole gold with
-- floor(x + 0.5), and that can round the buy DOWN and the sell UP by half a gold each. The
-- harness measured the result: +1 gold per round trip one rung up, repeatable for ever. So
-- when the guild is being generous the rounding goes the other way - ceil the buy, floor the
-- sell - which costs the player at most one gold and closes the leak by construction rather
-- than by shaving a magic number off the cap.
--
-- The hostile and neutral paths are untouched: floor(x + 0.5) is what shipped and what
-- check_spread has always measured.
function EX.buy_price(res, base)
    -- BASE IS OPTIONAL and defaults to today's price. The standing-order surfaces pass the mid
    -- AT THE ORDER'S TARGET RUNG instead, so the spread is applied here once rather than being
    -- re-derived against EX.price_at by the ticket. See EX.order_price.
    local p = base or EX.price(res)
    local h = EX.hostility(res)
    if h < 0 then return math.ceil(p * (1 + h)) end
    return math.floor(p * (1 + h) + 0.5)
end

-- What a sell actually pays. It has its OWN column since 2026-09-06 - see the SELL COLUMN
-- note on EX.PANEL_LAYOUT. Hostility widens the spread against you here as well: a house
-- that dislikes you charges more AND pays less - and a house that likes you does the reverse,
-- since EX.hostility is negative there and the same subtraction becomes an addition.
function EX.sell_price(res, base)
    -- BASE IS OPTIONAL, exactly as in EX.buy_price - see EX.order_price.
    local p = base or EX.price(res)
    -- BEFORE the hostility read, not after. EX.hostility already returns 0 for layer 2, so
    -- the order does not change the number today - it is here so that a future task giving
    -- the guild a stance on the Forge's output cannot silently stack a markup on top of a
    -- fire sale that is already discounted.
    --
    -- THE CLAMP IS THE SAFETY RAIL, not a tidy-up. Layer 2's rung is moved by EX.pressure_shift
    -- and by nothing else, so four net lots buys a rung and a factor above 1/LADDER_STEP turns
    -- that into free gold with no market risk - the loop check_spread closes for commodities.
    -- Written as min() rather than trusted to the slider's ceiling because ladder_step is a
    -- knob too: a Custom board at step 1.30 needs a tighter cap than one at 1.02, and no fixed
    -- slider maximum can be right for both.
    if EX.is_layer2(res) then
        local f = EX.opt("l2_sell")
        local cap = 1 / EX.opt("ladder_step")
        if f > cap then f = cap end
        return math.floor(p * f)
    end
    local h = EX.hostility(res)
    local f = 1 - EX.opt("spread") - h
    if f < EX.opt("sell_floor") then f = EX.opt("sell_floor") end
    -- See the note on EX.buy_price: the discounted side rounds against the player so whole
    -- gold cannot reopen the round trip the cap closes.
    if h < 0 then return math.floor(p * f) end
    return math.floor(p * f + 0.5)
end

-- HOW MUCH THE MARKUP ACTUALLY MOVED THIS PRICE, as a whole percent.
--
-- REALISED, NOT RAW. EX.hostility is the input; what reaches the sell price is clamped at
-- EX.SELL_FLOOR, so printing the raw figure would claim a reduction the floor had refused to
-- apply. Derived from the same two expressions buy_price and sell_price use, so the number on
-- the cell is the number in the price by construction and not by a second copy of the maths.
function EX.markup_pct(res, is_buy)
    local h = EX.hostility(res)
    -- == 0, NOT <= 0. A negative h is the friendly discount, and floored here it would move
    -- the price while the cell claimed it had not.
    if h == 0 then return 0 end
    local base, now
    if is_buy then
        base, now = 1, 1 + h
    else
        base = 1 - EX.opt("spread")
        now = base - h
        if now < EX.opt("sell_floor") then now = EX.opt("sell_floor") end
    end
    return math.floor(math.abs(now - base) / base * 100 + 0.5)
end

-- THE PRICE, AND WHAT THE GUILD ADDED TO IT. One cell, because they are one number: the
-- player is being charged this much BECAUSE of that percentage, and two columns would invite
-- the reading that the markup is still to come.
--
-- RED BOTH WAYS. A markup on the buy and a haircut on the sell are the same fact costing the
-- player money, so they get the same colour; only the sign differs.
function EX.price_cell(res, is_buy)
    local n = is_buy and EX.buy_price(res) or EX.sell_price(res)
    local p = EX.markup_pct(res, is_buy)
    if p <= 0 then return tostring(n) end
    -- GREEN WHEN THE GUILD LIKES YOU, and the sign flips with it. The two cases are the same
    -- sentence read from either end: a hostile guild costs the player money on both sides of
    -- the trade, a friendly one saves it on both.
    if EX.hostility(res) < 0 then
        return tostring(n) .. "[[col:green]]" .. (is_buy and "-" or "+") .. p .. "%[[/col]]"
    end
    return tostring(n) .. "[[col:red]]" .. (is_buy and "+" or "-") .. p .. "%[[/col]]"
end

-- ===========================================================================================
-- HOSTILITY. What the guild thinks of you, and what that costs you.
--
-- IT CHANGES YOUR FILL AND NEVER THE RUNG. The market price is world state and the same for
-- everyone; you are simply being gouged. If hostility reached EX.target_rung it would land in
-- the sparkline, in the dividend formula and in every house's own trading decision - your
-- personal diplomacy rewriting the world's prices. check_lua_books pins this mechanically.
-- ===========================================================================================

-- THE LADDER IS TREATIES, NOT NUMBERS. diplomatic_standing_with returns an int32 of
-- undocumented range, so nothing here depends on its magnitude. These booleans are documented
-- on the same interface, need no calibration, and every rung is something the player changes
-- directly in the diplomacy screen.
function EX.treaty_tier(house)
    local me = cm:get_faction(EX.who())
    local f = cm:get_faction(house)
    if not f or f:is_null_interface() or not me or me:is_null_interface() then return "free" end
    local ok, tier = pcall(function()
        if f:at_war_with(me) then return "war" end
        if f:is_vassal_of(me) or f:allied_with(me) or f:military_allies_with(me) then
            return "free"
        end
        if f:trade_agreement_with(me) then return "free" end
        if f:non_aggression_pact_with(me) then return "pact" end
        return "open"
    end)
    -- A guarded read that throws is a house we know nothing about, and charging a player for
    -- our own failure to read the game is the wrong default.
    if not ok then return "free" end
    return tier
end

-- IT TAKES A FACTION KEY STRING, NOT A FACTION INTERFACE. Passing the interface does not
-- error and does not return nil - it returns 0, for every faction, forever. This shipped and
-- ran a whole campaign before a live probe caught it: the houses read 0 across the board while
-- the same call with a key string returned -280, -30, +40. Measured 2026-09-07, turn 21.
--
-- The damage was not the zeroes themselves. It was that EX.check_standing_sign saw a board
-- where every house at war scored exactly what every trading house scored, correctly concluded
-- the sign convention was violated, and set EX.standing_trusted = false - which pins every
-- open house at a flat -0.5 stance. Refusal needs -0.75, so THE ENTIRE MIDDLE RUNG OF THE
-- HOSTILITY LADDER WAS UNREACHABLE and nothing said so. The self-check did its job and
-- degraded safely; it just diagnosed the wrong cause, because a broken accessor and an
-- inverted convention look identical from inside.
--
-- AND THE DIRECTION MATTERS: standing is ASYMMETRIC. me:diplomatic_standing_with(house) is what
-- WE think of THEM; this design reads what THEY think of US, so the house is the receiver and
-- the player's key is the argument. Measured on the same board, the two disagreed on every one
-- of the seven houses (warfleet -183 one way, -280 the other).
function EX.standing_of(house)
    local me = cm:get_faction(EX.who())
    local f = cm:get_faction(house)
    if not f or f:is_null_interface() or not me or me:is_null_interface() then return 0 end
    local ok, v = pcall(function()
        return f:diplomatic_standing_with(EX.who())
    end)
    if not ok or not v then return 0 end
    return v
end

-- THE SIGN CONVENTION, VERIFIED RATHER THAN ASSUMED. Negative-means-hostile is the Total War
-- convention, but the number is undocumented and this design reads its sign. So: any house at
-- war must rank below any house allied or trading. Violated, we log and fall back to the
-- treaty ladder alone; inconclusive (no such pair on the board), we assume it. One comparison,
-- no campaign probe, and it degrades to a system that still works rather than one that
-- silently never fires.
EX.standing_trusted = true
function EX.check_standing_sign()
    local worst_war, best_friend
    for _, h in ipairs(EX.guild()) do
        local tier, v = EX.treaty_tier(h), EX.standing_of(h)
        if tier == "war" and (not worst_war or v > worst_war) then worst_war = v end
        if tier == "free" and (not best_friend or v < best_friend) then best_friend = v end
    end
    if not worst_war or not best_friend then
        EX.standing_trusted = true          -- inconclusive: assume the convention
        return
    end
    EX.standing_trusted = worst_war < best_friend
    if not EX.standing_trusted then
        EX.say("error", "diplomatic_standing_with sign convention looks INVERTED "
            .. "(war " .. worst_war .. " vs ally " .. best_friend
            .. ") - falling back to treaty tiers alone")
    end
end

-- ONE PASS OVER THE GUILD, HELD FOR THE LENGTH OF ONE REFRESH OR ONE TURN STEP.
--
-- EX.stance_of used to re-walk the whole guild on every single call - one treaty_tier and one
-- standing_of per member, two cm:get_faction calls each - while EX.refresh_panel asks for it
-- four times per row (buy_price, sell_price, buy_tip, sell_tip). Measured cm:get_faction calls
-- per refresh: 3,009 at 3 houses, 31,110 at 10, 58,786 at 14 - and cr_combi_expanded ships 14.
-- EX.step_books cost another 14,308 a turn. The panel refreshes on open, on mode switch, at
-- turn start and 0.1s after every trade, so that is a visible hang, not a micro-optimisation.
--
-- SCOPED, NOT CACHED. EX.hold_guild() is opened and closed around one refresh and around one
-- turn step, and nothing survives the call - so a treaty signed between two refreshes is picked
-- up by the next one with no invalidation anybody has to remember. A cache that outlived its
-- scope would quietly price the wrong markup. The turn handler frees it once more before it
-- starts, so a refresh that errored mid-hold cannot strand a stale vector for the campaign.
EX.guild_hold = nil   -- { list = {...}, stance = { house -> -1..0 }, deepest = n } while held

function EX.hold_guild()
    EX.guild_hold = nil                     -- never build a hold on top of a hold
    local hd = { list = EX.guild(), stance = {} }
    EX.guild_hold = hd                      -- the guild list is memoised from here on
    hd.deepest = EX.deepest_standing()      -- ...and the rank denominator from here
    for _, h in ipairs(hd.list) do hd.stance[h] = EX.stance_of(h) end
end

function EX.free_guild()
    EX.guild_hold = nil
end

-- The denominator the severity rank is taken against: the deepest negative standing among
-- guild members holding no treaty. Zero when the guild all likes you, which is what makes
-- "a guild that all likes you charges nothing" fall out of the arithmetic rather than needing
-- its own branch. This is the walk that used to sit inside EX.stance_of.
function EX.deepest_standing()
    if EX.guild_hold and EX.guild_hold.deepest then return EX.guild_hold.deepest end
    local d = 0
    for _, h in ipairs(EX.guild()) do
        if EX.treaty_tier(h) ~= "free" then
            local v = EX.standing_of(h)
            if v < d then d = v end
        end
    end
    return d
end

-- -1 .. 0. Zero is never penalised. Severity is RANK within the guild's negative spread, so
-- the scale of the underlying number is irrelevant; only its sign and its ordering are read.
function EX.stance_of(house)
    -- 0 is truthy in Lua, so this reads a memoised zero correctly; a house outside the held
    -- guild is absent from the table and falls through to the live path below.
    local hd = EX.guild_hold
    if hd and hd.stance[house] then return hd.stance[house] end

    local tier = EX.treaty_tier(house)
    if tier == "free" then return 0 end
    if tier == "war" then return -1 end
    if not EX.standing_trusted then return -0.5 end   -- flat mid, see check_standing_sign

    local mine = EX.standing_of(house)
    if mine >= 0 then return 0 end                    -- the zero anchor

    -- The deepest negative in the guild is the full -1; everyone else scales against it. The
    -- house's own standing is folded in afterwards rather than seeding the walk, so the answer
    -- is identical to the old inline loop even for a house outside the guild.
    local deepest = EX.deepest_standing()
    if mine < deepest then deepest = mine end
    if deepest >= 0 then return 0 end
    local s = -(mine / deepest)
    if tier == "pact" and s < -(EX.HOSTILE_PACT_CAP / EX.opt("hostile_max")) then
        s = -(EX.HOSTILE_PACT_CAP / EX.opt("hostile_max"))
    end
    return s
end

-- WEIGHTED BY WHO HOLDS THE GOOD. A house that holds none of a commodity has no say in what
-- it costs you, however much it hates you.
-- HOW MUCH DISCOUNT A FRIENDLY GUILD CAN SAFELY GIVE, and why it is not the player's slider.
--
-- A round trip must never mint gold. check_spread() exists because 55 buys and sells of Exotic
-- Animals netted +906 out of nothing (measured 2026-09-05), and its condition is that selling
-- ONE RUNG HIGHER than you bought must still not pay - one rung is exactly what your own
-- buying pressure can open.
--
-- THE DISCOUNT LANDS ON BOTH SIDES, which is what makes the bound tighter than it looks. A
-- liked guild sells to you cheaper AND pays you more, so the spread closes from both ends:
--
--     buy  = P * (1 - d)
--     sell = P * (1 - spread + d)
--
-- Sell one rung up must not beat buy here:
--     P*STEP*(1 - spread + d)  <=  P*(1 - d)
--     d * (1 + STEP)           <=  1 - STEP*(1 - spread)
--     d                        <=  (1 - STEP*(1 - spread)) / (1 + STEP)
--
-- THE FIRST VERSION OF THIS DROPPED THE (1 + STEP) and used the buy-side-only bound. The
-- harness caught it immediately: at a 0.20 spread it granted 12%, and buying and selling at
-- the SAME RUNG then netted +25 gold a lot - free money needing no price movement at all,
-- strictly worse than the exploit check_spread was written to stop. The two-sided algebra is
-- the whole difference between a feature and a money printer.
--
-- At the default spread of 0.10 and STEP 1.10 the headroom is under half a percent, because
-- that spread only just clears check_spread's floor of 1 - 1/STEP = 0.0909. The discount
-- therefore scales with the spread the player has set, and the slider is a ceiling on it,
-- never an override.
--
-- BOTH INPUTS THROUGH EX.opt, and this line shipped with only one of them that way. The step
-- was read off EX.LADDER_STEP - the DEFAULT 1.10 - while the spread came from the player's own
-- setting, so the algebra above was solved for a ladder the game was not running. On ultra
-- (step 1.18, spread 0.25) the safe headroom is 5.3% and this granted 8.3%: buy from a friendly
-- house, sell one rung up, net gold with no price movement at all. Exactly the exploit the
-- derivation was written to rule out, defeated by one of its two terms coming from the wrong
-- place. Found by check_knob_reads() on 2026-09-16, not by a harness - every preset check was
-- green, because presets and constants agree at the default and only there.
function EX.friendly_cap()
    local step = EX.opt("ladder_step")
    local d = (1 - step * (1 - EX.opt("spread"))) / (1 + step)
    if d < 0 then d = 0 end
    return d
end

-- THE GUILD'S STANCE AS A PRICE FACTOR. POSITIVE IS HOSTILE, NEGATIVE IS FRIENDLY.
--
-- It used to floor at zero and throw the friendly half away - a liked house computed a
-- negative number and got clamped to nothing. The two halves are deliberately ASYMMETRIC:
-- hostility runs to hostile_max (0.25 by default) because charging more can never mint gold,
-- while the discount is bounded by EX.friendly_cap() because a discount can.
function EX.hostility(res)
    if EX.is_house(res) or EX.is_layer2(res) then return 0 end
    local total = EX.guild_book(res)
    if total <= 0 then return 0 end
    local h = 0
    for _, house in ipairs(EX.guild()) do
        local n = EX.book_of(house, res)
        if n > 0 then
            h = h + (n / total) * (-EX.stance_of(house))
        end
    end
    if h > 1 then h = 1 end
    if h < -1 then h = -1 end
    if h < 0 then
        -- The slider asks; the spread decides. Whichever is smaller wins.
        local want = -h * EX.opt("friendly_max")
        local cap = EX.friendly_cap()
        if want > cap then want = cap end
        return -want
    end
    return h * EX.opt("hostile_max")
end

-- WHO THE MARKUP IS FOR: the holder adding the most of EX.hostility's sum. The "dislikes you"
-- sentences used to name EX.guild_counterparty instead - the house you BUY FROM, which skips
-- houses at war and so is never the one charging you. Reported 2026-09-23: the Warhost of
-- Zharr "dislikes you" at +85 standing, which EX.stance_of scores 0 - the markup on its gems
-- came from other holders, and a house at war counts in the sum while being skipped as seller.
function EX.hostility_source(res)
    local best, best_w = nil, 0
    for _, house in ipairs(EX.guild()) do
        local w = EX.book_of(house, res) * -EX.stance_of(house)
        if w > best_w then best, best_w = house, w end
    end
    return best
end

function EX.price(res)
    return EX.price_at(EX.current[res] or EX.neutral_rung())
end

function EX.held(res)
    -- SHARES ARE SAVE STATE, NOT A POOLED RESOURCE. Commodities use pooled resources only
    -- because v1 traded them as ritual costs and a ritual cost has to name one; the rituals
    -- were deleted 2026-09-05 and the reason went with them. Skipping the DB here saves ~42
    -- rows and, more importantly, thirteen more icons in the Chaos Dwarf resource bar.
    --
    -- THIS BRANCH MUST COME BEFORE THE PCALL BELOW, and not for the reason first written here.
    -- `f` down there is always the PLAYER'S faction, whatever res is - it is not a house's
    -- interface and it never fails. What fails is the LOOKUP: a house key names a pooled
    -- resource the DB never registered, so resource() answers a null interface, the guard
    -- returns 0, and the pcall succeeds. Falling through would price every house position at
    -- zero with nothing anywhere reporting it.
    if EX.is_house(res) then return EX.shares_held[res] or 0 end
    local f = cm:get_faction(EX.who())
    if not f or f:is_null_interface() then return 0 end
    local ok, v = pcall(function()
        local pr = f:pooled_resource_manager():resource(EX.hold_key(res))
        if pr and not pr:is_null_interface() then return pr:value() end
        return 0
    end)
    return (ok and v) or 0
end

-- IS THE POOL ACTUALLY ON THIS FACTION? A pooled resource whose campaign_group does not cover
-- the player's culture answers a NULL INTERFACE, and cm:faction_add_pooled_resource against it
-- moves nothing and reports nothing. Shipped 2026-09-08 and found in a live Empire campaign:
-- every buy charged the gold, paid the counterparty, wrote "bought 10 ..." to the log and
-- granted zero goods. The DB fix is the universal registration group; this is the guard that
-- makes the next such regression refuse the trade instead of eating the treasury.
function EX.pool_live(res)
    if EX.is_house(res) then return true end        -- shares are save state, no pool involved
    local ok, live = pcall(function()
        local f = cm:get_faction(EX.who())
        if not f or f:is_null_interface() then return false end
        local pr = f:pooled_resource_manager():resource(EX.hold_key(res))
        return pr ~= nil and pr ~= false and not pr:is_null_interface()
    end)
    return ok and live
end

-- THE DISPLAY HALF OF EX.pool_live, and it is deliberately NOT the same question.
--
-- EX.pool_live guards the TRADE and must fail CLOSED: anything it cannot confirm, it refuses,
-- because the cost of being wrong is gold taken for goods never granted. This guards the BUTTON
-- LABEL and must fail OPEN: it answers "the game told me this faction has no store for it", and
-- a lookup that merely threw has told us nothing. Greying a row on an unreadable answer would
-- take the market away on the strength of an error nobody sees.
--
-- The practical difference is a stub, a null interface or a patched-out accessor. In a real
-- campaign both answer the same thing.
function EX.pool_absent(res)
    if EX.is_house(res) then return false end
    local ok, absent = pcall(function()
        local f = cm:get_faction(EX.who())
        if not f or f:is_null_interface() then return false end
        local prm = f:pooled_resource_manager()
        if not prm then return false end
        local pr = prm:resource(EX.hold_key(res))
        return pr == nil or pr == false or pr:is_null_interface()
    end)
    return ok and absent == true
end

-- The writer beside EX.held. Clamped at zero rather than trusting every caller to pre-check -
-- a sell that raced past the held-check in EX.trade must not leave a negative position sitting
-- in the save.
function EX.set_shares(house, n)
    if n < 0 then n = 0 end
    EX.shares_held[house] = n
    EX.setp(EX.SAVE_SHARES .. house, n)
end

-- ---------------------------------------------------------------------------------------
-- THE WAREHOUSE: what a holding costs, and what it grants.
-- ---------------------------------------------------------------------------------------

-- EVERY PATH THAT MOVES GOODS ENDS HERE. Buying, selling, a voluntary offering and paying a
-- tithe all change a holding, and any of them can carry it across a tier boundary in either
-- direction. Without this the panel and the game disagree until the next turn start: the Held
-- cell reads the live holding and goes green immediately, while the bundle that actually
-- grants the bonus would not be applied until FactionTurnStart came round.
--
-- Deferred by the caller for the same reason the reprice is - the pooled-resource change is
-- not visible on the same tick it is requested.
-- THE FACTION IS AN ARGUMENT, AND IT IS THE WHOLE MULTIPLAYER CORRECTNESS OF THIS FUNCTION.
--
-- Every caller reaches here through cm:callback, which fires AFTER EX.with_player has restored
-- the subject - so an unbound EX.apply_stockpiles() here would apply the LOCAL player's
-- warehouse tier on every machine instead of the trading player's. That is not a missed update,
-- it is a desync: machine A would move A's bundles and machine B would move B's, off the same
-- one trade. The tier would look right on the trader's own screen, which is the worst way for
-- it to be wrong.
--
-- EX.refresh_panel stays unbound on purpose - it draws THIS client's panel and reads EX.me().
function EX.after_holding_change(faction)
    if faction then
        EX.with_player(faction, function() EX.apply_stockpiles() end)
    else
        EX.apply_stockpiles()
    end
    EX.refresh_panel()
end

function EX.stock_bundle(res, tier)
    -- stock_, not hold_: derpy_chd_ex_hold_<short> is the POOLED RESOURCE the goods live in
    -- and a collision there would be silent. Mirrors stock_bundle() in the generator.
    return string.format("%sstock_%s_%d", EX.PREFIX, EX.short(res), tier)
end

-- Highest tier this holding reaches, or 0 for none. Walks the whole list and keeps the LAST
-- match rather than returning the first, so the thresholds may be listed in any order without
-- silently capping the ramp at tier 1.
function EX.stock_tier(held)
    local tier = 0
    for i, units in ipairs(EX.STOCK_TIERS) do
        if held >= units then tier = i end
    end
    return tier
end

-- Gold per turn to warehouse this commodity. Layer 2 is EXEMPT and that is not an oversight:
-- Armaments and Raw Materials are Hell-Forge currency the player earns from BUILDINGS, so
-- charging rent on them would tax ordinary Chaos Dwarf play rather than trading. Nothing about
-- this feature should touch a player who never opens the panel. Houses are EXEMPT too - they
-- are paper, not goods, and there is nothing to store in a warehouse.
function EX.carry_cost(res)
    if EX.is_layer2(res) or EX.is_house(res) then return 0 end
    return math.floor(EX.held(res) * EX.opt("carry_per_unit"))
end

-- Summed per commodity, NOT computed from a summed holding. math.floor of each is what the
-- rows print, and a total that disagreed with the column above it by a gold or two is the
-- kind of thing a player reports as the panel lying.
function EX.carry_total()
    local total = 0
    for _, res in ipairs(EX.COMMODITIES) do
        total = total + EX.carry_cost(res)
    end
    return total
end

-- WHAT THE WHOLE POSITION WOULD FETCH IF IT WERE SOLD NOW - the one number on the panel that
-- answers "what am I worth here". Every view has told the player what they hold of ONE thing;
-- nothing anywhere added the seventeen up, so a player with goods in ten markets and paper in
-- four houses had to do it on paper.
--
-- SELL PRICE, NOT PRICE, AND THAT IS THE WHOLE POINT OF THE NUMBER. A book marked at the mid
-- price is not money: EX.SPREAD is 10% at default and a hostile house widens it further, so a
-- mid-priced total overstates the liquidation by exactly what the market takes on the way out.
-- This is what the Sell buttons on the panel would actually pay, today, at today's rungs.
--
-- EX.sell_price IS THE PRICE OF A LOT AND EX.held COUNTS UNITS. That mismatch is not
-- hypothetical here - it is the exact fault that paid the dividend five times over (measured:
-- 100 shares cost 20,000 and paid 2,000 a turn; see EX.dividend). Divide by EX.lot(res).
--
-- FLOORED PER INSTRUMENT, not once at the end: the same rule and the same reason as
-- EX.carry_total above. The rows print floored numbers and a total that disagreed with the
-- column above it by a gold reads as the panel lying.
--
-- A DELISTED HOUSE IS WORTH ZERO and is skipped rather than trusted to hold zero shares -
-- same shape as EX.dividend_total, same reason: EX.shares_held is rebuilt from a save that may
-- predate the delist, and both its buttons are disabled, so its paper cannot be sold at all.
--
-- ponytail: one EX.held call per instrument per refresh, on top of the one each drawn row
-- already makes - so the Houses view now reads the commodity pools too. Panel refresh, not a
-- turn loop; cache it on EX.refresh_panel's frame if a profile ever says otherwise.
function EX.holdings_value()
    local total = 0
    for _, res in ipairs(EX.instruments()) do
        if not (EX.is_house(res) and EX.is_delisted(res)) then
            local n = EX.held(res)
            if n > 0 then
                total = total + math.floor(n * EX.sell_price(res) / EX.lot(res))
            end
        end
    end
    return total
end

-- EXACTLY ONE TIER BUNDLE PER COMMODITY, EVER.
--
-- REMOVE ALL THREE FIRST, not just the one we believe is applied - the same shape and the same
-- reason as EX.apply_trade_income. Same-effect bundles stack ADDITIVELY, so tier 1 left behind
-- under tier 3 grants 4x rather than 3x; and effect bundles SURVIVE A SAVE while this script's
-- tables do not, so on a reload the game already carries whatever the last session applied.
-- The unconditional remove is what makes this idempotent and safe to call from the first tick.
--
-- ponytail: 17 removes plus up to 17 applies, once per turn, unconditionally. Cheap enough not
-- to measure and it needs no saved state at all. If the Faction Effects panel is ever seen to
-- flicker on turn start, cache the applied tier in memory and only call on a change.
function EX.apply_stockpiles()
    local faction = EX.who()
    if not faction then return end
    for _, res in ipairs(EX.COMMODITIES) do
        local want = EX.stock_tier(EX.held(res))
        for tier = 1, #EX.STOCK_TIERS do
            if tier ~= want then
                pcall(function()
                    cm:remove_effect_bundle(EX.stock_bundle(res, tier), faction)
                end)
            end
        end
        if want > 0 then
            -- Re-applying the bundle that is already on is a no-op for the same key, so this
            -- does not stack with itself across turns. 0 = no duration, it runs until removed.
            cm:apply_effect_bundle(EX.stock_bundle(res, want), faction, 0)
        end
    end
end

-- The rent. A DIRECT treasury debit rather than an effect bundle: an income modifier would
-- need its own step ladder of bundles the way EX.TRADE_STEPS does, and the amount here is an
-- exact number of gold rather than a percentage of anything.
--
-- ponytail: the cost is therefore NOT a line item in the treasury breakdown panel - it lands
-- as a lump. The exchange footer names the total, which is the only place it is explained.
--
-- DO NOT RETRY THIS WITH wh2_main_effect_background_income_mod. Measured in a live campaign
-- 2026-09-06, turn 11 to 12, and it is INERT. The build was correct at every step that can be
-- checked: cm:create_new_custom_effect_bundle returned a real interface, set_effect_value_by_key
-- returned TRUE, the bundle's own effects() listed exactly
--     [wh2_main_effect_background_income_mod scope=faction_to_faction_own_unseen val=-734]
-- and has_effect_bundle read true across the turn change. faction:income() went 4370 -> 4371
-- and the treasury rose by exactly net_income, with nothing deducted. So the player paid no
-- rent at all - the mechanic was silently OFF, which is worse than being invisible.
--
-- The mistake was mine and it is the one this workspace already has a rule for: three vanilla
-- junction rows prove the game ACCEPTS the effect, never that it DOES anything. The scope was
-- copied from those rows to inherit their verification, but the EFFECT itself was never
-- verified live, and only two of the three rows are real content - the third is
-- wh3_main_background_income_mod_1000, whose name is the effect plus its value, i.e. a dev
-- bundle. See MEMORY/wh3-vanilla-row-count-is-not-behaviour.
--
-- A replacement must be an effect with MANY vanilla junction rows AND a measured before/after
-- across a turn, not a plausible-looking key.
function EX.charge_carry()
    if not EX.setting("warehouse_rent") then return end
    local faction = EX.who()
    if not faction then return end
    local total = EX.carry_total()
    if total <= 0 then return end
    cm:treasury_mod(faction, -total)
    EX.say("turn", "warehousing charged " .. total)
    -- THE ONE CHARGE THE TREASURY BREAKDOWN CANNOT SHOW (it lands as a lump - see below), so
    -- the Log is where last turn's bill can be read back.
    EX.log_add("Rent", "Warehouse rent: -" .. total .. "g.", "")
end

-- ---------------------------------------------------------------------------------------
-- DIVIDENDS. The other half of the ledger from the warehouse: holding COMMODITIES costs rent,
-- holding a HOUSE'S paper pays a yield - EX.DIV_YIELD, a fraction of the share's own live
-- price rather than a flat number, for the reason argued on that constant.
-- ---------------------------------------------------------------------------------------

-- PER SHARE - AND EX.price IS THE PRICE OF A LOT, NOT OF A SHARE.
--
-- EX.trade charges exactly EX.price(res) and hands over EX.lot(res) of the thing, so one house
-- price buys EX.HOUSE_LOT_SIZE shares. (EX.trade actually charges EX.buy_price(res) - this
-- equals EX.price(res) for a house ONLY because EX.hostility(res) is hardcoded to 0 for any
-- EX.is_house(res) instrument. A future task that gives houses their own hostility invalidates
-- that equality, and this comment with it - fix here too, not just EX.trade.) Taking the
-- yield off the whole lot price and then
-- letting EX.dividend_total multiply it by every SHARE held paid the yield five times over:
-- measured on this file's own harness, 100 shares cost 20,000 gold and paid 2,000 a turn - 10%
-- of the position per turn, not the 2% EX.DIV_YIELD is argued from. That beats EX.SPREAD's 10%
-- round-trip cost after ONE turn instead of five, so a player parks the whole treasury in the
-- cheapest house for a risk-free 10% a turn. The income cheat the constant exists to prevent.
--
-- IT CAN FLOOR TO ZERO, and that is the right answer rather than a case to guard. The ladder
-- floor is EX.price_at(1) = 100 gold a lot, so 100 * 0.02 / 5 = 0.4 -> 0. A house priced at
-- the floor has collapsed to a tenth of neutral; paper in it paying nothing is the signal, and
-- rounding a dead house's dividend UP to a gold a share would pay the player to hold losers.
--
-- WAR SUSPENDS IT ENTIRELY. A house fighting you does not fund a shareholder it is fighting.
-- Done HERE rather than in EX.dividend_total so that the Div column, the footer total and the
-- payment all read the same zero - three call sites that would otherwise have to remember.
-- The position is not confiscated: make peace and the dividend resumes, and selling is open
-- throughout, so a war is a freeze on the income rather than a loss of the capital.
function EX.dividend(house)
    if EX.treaty_tier(house) == "war" then return 0 end
    return math.floor(EX.price(house) * EX.opt("div_yield") / EX.HOUSE_LOT_SIZE)
end

-- A DELISTED HOUSE PAYS NOTHING. EX.settle_house zeroes the position on the way out, so this
-- skip looks redundant - it is not. EX.shares_held is rebuilt from saved values on every load
-- and a save written before the delist still names a count, so leaning on the zero alone
-- leaves one shape where a dead house pays a dividend every turn forever.
function EX.dividend_total()
    local total = 0
    for _, h in ipairs(EX.houses) do
        if not EX.is_delisted(h) then
            local n = EX.held(h)
            if n > 0 then total = total + EX.dividend(h) * n end
        end
    end
    return total
end

-- THE HOUSE PAYS IT. This used to be one cm:treasury_mod crediting the player and nothing
-- else - the gold was minted, and an issuing house lost nothing however much of its paper the
-- player held. That is the opposite of how the commodity side settles, where a buy and a sell
-- were both measured conserved to the gold (player -467 / house +467, player +420 / house
-- -420, 2026-09-07). Paper is now conserved the same way.
--
-- BOUNDED BY WHAT THE HOUSE ACTUALLY HAS. EX.pay_house already clamps a debit to the house's
-- treasury and to HOUSE_CASH_MAX, so a poor house pays what it can and the player is credited
-- only what was really taken - the dividend visibly shrinks instead of a faction going
-- negative to fund it. AI treasuries drive AI armies; this is the only reason that clamp
-- exists.
--
-- ONE cm:treasury_mod for the player's whole credit, the way EX.charge_carry makes one for the
-- rent. It lands under Expenses > Event Outcomes in the finance screen, which this mod already
-- recolours - see EX.recolour_finance.
function EX.pay_dividends()
    local paid, payers = 0, 0
    for _, h in ipairs(EX.houses or {}) do
        if not EX.is_delisted(h) then
            local n = EX.held(h)
            -- EX.dividend is already zero for a house at war, so a belligerent contributes
            -- nothing here without this loop needing to know about war at all.
            local due = n > 0 and EX.dividend(h) * n or 0
            if due > 0 then
                payers = payers + 1
                if EX.setting("ai_gold") then
                    -- NEGATIVE debits the house. pay_house returns what it could actually move.
                    paid = paid - EX.pay_house(h, -due)
                else
                    -- ai_gold off means the houses' books are notional and no gold moves
                    -- THROUGH them - the player's dividend still pays, exactly as it did
                    -- before this function learned to debit anyone.
                    paid = paid + due
                end
            end
        end
    end
    if paid <= 0 then return end
    cm:treasury_mod(EX.who(), paid)
    -- IN THE LOG, NOT ONLY THE DEBUG STREAM. Gold arriving with nothing anywhere saying where
    -- from is the same complaint the offering log answered: no house is NAMED, because this is
    -- a turn handler and a house's name is loc - see EX.build_world_log.
    EX.log_add("Dividends", payers .. " house(s) paid you " .. paid .. "g.", "")
    EX.say("turn", "dividends paid " .. paid)
end

-- ---------------------------------------------------------------------------------------
-- DELISTING. A house dies, its paper settles once, and the row freezes at its last price.
-- ---------------------------------------------------------------------------------------

function EX.is_delisted(house)
    return (EX.delisted or {})[house] == true
end

-- Dead, or gone from the world entirely.
function EX.house_gone(house)
    local f = cm:get_faction(house)
    -- cm:get_faction returns FALSE, not nil, for a faction that does not exist. A `not f`
    -- test is correct here only because false is falsy; `f == nil` would not be.
    if not f or f:is_null_interface() then return true end
    local dead = false
    pcall(function() dead = f:is_dead() end)
    return dead
end

-- Did WE end up with it? THE QUESTION IS ASKED OF THE REGION, NOT THE FACTION, because by the
-- time it is asked there may be no faction left to ask: cm:get_faction answers FALSE for a
-- confederated house, and EX.house_gone treats exactly that as dead - so a version that reads
-- home_region() off the dead faction can never return true down the confederation path, which
-- is how a Tower of Zharr seat claim kills a house. That is the headline hook, and it would
-- have paid EX.WINDUP every time with nothing anywhere reporting it.
--
-- EX.remember_home cached the key while the house was alive. region_by_key answers NULL only
-- for an invalid key (CA's own docs), so a razed or abandoned capital still comes back as a
-- real interface and the owner guard below reads it correctly either way - no is_abandoned
-- test, which would answer a different question.
--
-- The live read stays as the fallback for the one window the cache cannot cover: a house that
-- died before EX.target_rung ever priced it.
function EX.absorbed_by_us(house)
    local me = EX.who()
    local ours = false
    local key = EX.house_home[house]
    if key then
        pcall(function()
            local r = cm:model():world():region_manager():region_by_key(key)
            if r and not r:is_null_interface() then
                local o = r:owning_faction()
                ours = (o and not o:is_null_interface() and o:name() == me) or false
            end
        end)
        return ours
    end
    local f = cm:get_faction(house)
    -- cm:get_faction returns FALSE, not nil, for a faction that does not exist.
    if not f or f:is_null_interface() then return false end
    pcall(function()
        local r = f:home_region()
        if r and not r:is_null_interface() then
            local o = r:owning_faction()
            ours = (o and not o:is_null_interface() and o:name() == me) or false
        end
    end)
    return ours
end

-- ONE PLAYER'S SIDE OF A SETTLEMENT. Bound subject; called once per human by EX.settle_house.
--
-- THE PRICE IS PASSED IN, NOT READ HERE. EX.price(house) collapses to rung 1 the moment the
-- reprice sees a dead house owning nothing, so every holder has to be paid off the SAME living
-- price - the one read before the loop started. Reading it per player would be correct for
-- whoever went first and a near-total loss for everyone after them, which is exactly the
-- measured 621-to-102 collapse the turn order note in EX.turn_round is about.
function EX.settle_holder(house, px)
    local fname = EX.who()
    local n = EX.held(house)
    -- THE MULTIPLIER IS PER PLAYER, and this is the whole reason the loop exists rather than
    -- one payout: "did I take the capital" has a different answer for each human, so in a
    -- multiplayer game one holder can be paid the buyout premium on the same death that pays
    -- everybody else the wind-up.
    local mult = EX.absorbed_by_us(house) and EX.opt("buyout_premium") or EX.opt("windup")
    local paid = math.floor(px * mult * n)
    if n > 0 and paid > 0 then
        cm:treasury_mod(fname, paid)
    end
    EX.set_shares(house, 0)
    -- NO POSITION, NO BULLETIN, gated on the same n the payout is. Both texts say "your
    -- shares are paid out"; eleven-odd houses die over a campaign and most players hold paper
    -- in none of them, so an ungated message is eleven notices about somebody else's money.
    if n > 0 then
        -- The wording has to match the multiplier that paid: a wind-up worded as a buyout
        -- reads as a bug in the gold. Both keys resolve against the one EX.FEED_DELIST record.
        local m = (mult == EX.opt("buyout_premium")) and (EX.PREFIX .. "delist_buyout")
                                              or (EX.PREFIX .. "delist_windup")
        -- false, not true: EX.FEED_DELIST is a scripted_transient_event record, and the flag
        -- picks which event type the index resolves against. See EX.FEED_SHOCK.
        cm:show_message_event(fname, m .. "_title", m .. "_primary",
                              m .. "_secondary", false, EX.feed("delist"))
    end
    EX.say("house", house .. " delisted for " .. fname .. ", paid " .. paid)
    -- STEP MARKERS. A CTD here on 2026-09-07 left the out() above as the last line in the log
    -- and nothing to say which of the statements after it had run. Cheap, and this is the one
    -- code path in the mod that has taken the process down.
    -- UNGATED, unlike the bulletin above. A message event about somebody else's money is
    -- eleven interruptions over a campaign; a LOG LINE is a record the player goes looking
    -- for - and it is the only place the fact survives EX.prune_houses taking the row away.
    EX.log_settlement(house, paid, n)
    EX.say("house", house .. " settlement logged")
end

-- THE WHOLE SETTLEMENT: every holder paid off one price, then one world flag.
--
-- THE FLAG IS WORLD STATE AND IS WRITTEN LAST. It is the only thing standing between this and
-- a second payout on the next load - the F9 gold printer - so it must not be set until every
-- holder has actually been paid, or an error mid-loop would mark the house settled with some
-- players still owed.
function EX.settle_house(house)
    local px = EX.price(house)
    for _, f in ipairs(EX.humans()) do
        EX.with_player(f, function() EX.settle_holder(house, px) end)
    end
    EX.delisted[house] = true
    local parts = {}
    for k in pairs(EX.delisted) do parts[#parts + 1] = k end
    -- Sorted: this string is compared byte for byte across machines on the next load, and
    -- pairs() has no order.
    table.sort(parts)
    EX.setv(EX.SAVE_DELISTED, table.concat(parts, ";"))
end

-- THE SETTLEMENT, IN THE LOG. Until now it existed only as an out() line in script_log.txt,
-- which no player reads - and since EX.prune_houses can now take the row away, the log is the
-- only place the fact would survive at all.
-- THE SUBJECT IS LEFT EMPTY ON PURPOSE and resolved when the row is drawn. Calling
-- EX.faction_display here - which reaches common.get_localised_string - is what killed the
-- process at turn 1 of a fresh campaign on 2026-09-07, twice, with the out() line above as the
-- last thing in the log and no minidump. This runs inside a FactionTurnStart handler at the
-- earliest moment the mod ever executes; drawing a row does not.
--
-- IT IS ALSO THE BETTER SHAPE. A name that could not resolve at turn 1 would otherwise be
-- frozen into the saved log for the rest of the campaign; resolved at draw time it fixes
-- itself on the next refresh.
function EX.log_settlement(house, paid, lots)
    local n = tonumber(lots) or 0
    pcall(function()
        EX.log_add("",
            n > 0
                and ("Delisted. The house is gone; your " .. n .. " share(s) settled for "
                     .. tostring(paid) .. "g.")
                or "Delisted. The house is gone. You held nothing in it.",
            house)
    end)
end

function EX.check_delistings()
    for _, h in ipairs(EX.houses) do
        -- ALREADY DELISTED IS CHECKED FIRST. The turn handler re-runs on every load, so
        -- without this a reload settles the same dead house again - an unbounded gold
        -- printer reachable by pressing F9.
        if not EX.is_delisted(h) and EX.house_gone(h) then EX.settle_house(h) end
    end
    EX.say("house", "delisting pass done, pruning")
    EX.prune_houses()
    EX.say("house", "prune done, " .. #EX.houses .. " houses")
end

-- A DELISTED HOUSE THE PLAYER HOLDS NOTHING IN IS DROPPED FROM THE LIST.
--
-- WHY THIS DOES NOT UNDO THE UNION. EX.discover_houses merges rather than replaces, on the
-- argument that a key dropping out of faction_list() would strand a position inside it -
-- EX.restore only rebuilds EX.shares_held for houses IN EX.houses. That argument is about
-- POSITIONS. A house that is delisted has already settled, and one the player holds nothing
-- in has nothing left to strand, so carrying it forward buys nothing and costs a row.
--
-- IT SELF-HEALS SAVES. Measured live 2026-09-07: four dead factions were sitting on the
-- Houses view as permanent Delisted rows, admitted during the one-tick window in
-- EX.tradeable_faction. All four answer is_dead() and hold nothing; nothing in the code
-- could ever have removed them, and the fix had to reach saves that already had them.
--
-- A HELD POSITION IS NEVER PRUNED, even delisted - the row is how a player sees the
-- settlement they were paid, and it disappears on its own once the position is closed.
-- ANY HUMAN'S POSITION KEEPS THE ROW. EX.houses is world state and the drop has to be the same
-- decision on every machine, so the test is "nobody is holding it" rather than "I am not".
function EX.anyone_holds(house)
    -- THE BOUND PLAYER IS READ FROM MEMORY, EVERYONE ELSE FROM THE STORE, and that asymmetry
    -- is the point rather than an inconsistency. EX.held is the accessor with the house branch
    -- and the live position; it is what this test was before there was more than one player,
    -- so the singleplayer answer is unchanged to the line. The other humans are not bound, so
    -- their slice is not in EX.shares_held and the saved value EX.set_shares wrote alongside it
    -- is the only reading available - and it cannot be stale, because the two are written in
    -- the same statement.
    if (EX.held(house) or 0) > 0 then return true end
    local me = EX.who()
    for _, f in ipairs(EX.humans()) do
        if f ~= me and (tonumber(EX.getp(EX.SAVE_SHARES .. house, f)) or 0) > 0 then
            return true
        end
    end
    return false
end

function EX.prune_houses()
    local keep, dropped = {}, 0
    for _, h in ipairs(EX.houses) do
        if EX.is_delisted(h) and not EX.anyone_holds(h) then
            dropped = dropped + 1
            -- Only this client's cached slice needs clearing here; every other player's was
            -- already zeroed by EX.set_shares inside their own EX.settle_holder pass, which is
            -- what wrote the saved value EX.anyone_holds just read.
            EX.shares_held[h] = nil
        else
            keep[#keep + 1] = h
        end
    end
    if dropped == 0 then return end
    EX.houses = keep
    EX.house_set = nil
    EX.setv(EX.SAVE_HOUSES, table.concat(keep, ";"))
    EX.say("house", "pruned " .. dropped .. " delisted house(s) held at zero")
end

-- ---------------------------------------------------------------------------------------
-- State. All of it persisted: effect bundles survive a save and these tables do not, so
-- without this a reload re-applies a second bundle on top of the first - and same-effect
-- bundles stack ADDITIVELY, so prices would compound on every load.
-- ---------------------------------------------------------------------------------------

EX.current  = {}   -- res -> rung currently applied
EX.history  = {}   -- res -> { rung, rung, ... } most recent last, for the sparkline
EX.deep     = {}   -- res -> the same, DEEP_BARS long. history is its tail, not a copy
EX.pressure = {}   -- res -> net lots bought, our own-trade impact

-- house key -> commodity key -> lots. Restored from EX.SAVE_BOOK, never regenerated: unlike
-- supply, which is rescanned from the map every turn, a position is a thing somebody did.
EX.book = {}

-- THE WORLD TIER'S BOOK. F1, final review 2026-09-13: EX.set_world_book has always written
-- EX.SAVE_WBOOK .. faction, and nothing ever read it back - EX.wbook = EX.wbook or {} at its
-- own declaration is a fresh empty table on every load, since the script re-executes. With
-- world_scarcity on (default, hard and ultra) that reads as EVERY commodity the guild is not
-- long being sold out, from the instant a save loads until the player's turn ends.
--
-- NO KNOWN ROSTER TO ITERATE, unlike the guild's EX.houses. EX.actors is a per-turn scan
-- result, not a saved list, so this walks EX.store itself for every key beginning with
-- EX.SAVE_WBOOK instead of building one from a faction list that does not exist yet. EX.store
-- is guaranteed populated before EX.restore runs - see the comment above EX.getv - so this
-- needs no new save key and maintains no roster of its own.
--
-- MIRRORS EX.pack_world_book's FORMAT EXACTLY: "res=n;res2=n2", sorted - the same gmatch shape
-- the guild's book uses on its own packed string. tonumber handles a leading "-" for free, so
-- a short position restores as read, no separate branch needed.
--
-- SPLIT OUT OF EX.restore, TASK 9, so the selftest harness can exercise a load in isolation
-- without a full campaign restore.
function EX.restore_world_books()
    EX.wbook = {}
    for key, packed in pairs(EX.store) do
        if type(key) == "string" and string.sub(key, 1, #EX.SAVE_WBOOK) == EX.SAVE_WBOOK then
            local faction = string.sub(key, #EX.SAVE_WBOOK + 1)
            EX.wbook[faction] = EX.wbook[faction] or {}
            if packed and packed ~= "" then
                for res, n in string.gmatch(packed, "([^;=]+)=([^;]+)") do
                    EX.wbook[faction][res] = tonumber(n) or 0
                end
            end
        end
    end
end

function EX.restore()
    -- HOUSES FIRST. EX.instruments() reads EX.houses, so restoring per-instrument state
    -- before this would silently skip every house's rung, pressure and history.
    EX.houses = {}
    local hs = EX.getv(EX.SAVE_HOUSES)
    if hs and hs ~= "" then
        for k in string.gmatch(hs, "[^;]+") do EX.houses[#EX.houses + 1] = k end
    end
    EX.house_set = nil
    EX.house_home = {}
    EX.book = {}
    for _, h in ipairs(EX.houses) do
        -- The capital key cached while the house was alive. Nil for one that has not been
        -- priced yet; EX.absorbed_by_us falls back to a live read for that window.
        EX.house_home[h] = EX.getv(EX.SAVE_HOME .. h)
        -- The book, unpacked from its one string. A house with no entry has an empty book,
        -- not a nil one: every reader does arithmetic on what this returns.
        EX.book[h] = {}
        local packed = EX.getv(EX.SAVE_BOOK .. h)
        if packed and packed ~= "" then
            for res, n in string.gmatch(packed, "([^;=]+)=([^;]+)") do
                EX.book[h][res] = tonumber(n) or 0
            end
        end
    end

    -- THE WORLD TIER'S BOOK, restored by EX.restore_world_books() below - split out so the
    -- selftest harness can exercise a load in isolation, without a full campaign restore.
    EX.restore_world_books()

    -- WHICH HOUSES HAVE ALREADY PAID OUT, same semicolon shape as EX.shocked below. A reload
    -- re-runs the turn handler, so losing this is a second settlement for every dead house on
    -- the board - the F9 gold printer EX.check_delistings guards against.
    EX.delisted = {}
    local dl = EX.getv(EX.SAVE_DELISTED)
    if dl and dl ~= "" then
        for k in string.gmatch(dl, "[^;]+") do EX.delisted[k] = true end
    end

    for _, res in ipairs(EX.instruments()) do
        local rung = EX.getv(EX.SAVE_PREFIX .. res)
        if rung then EX.current[res] = rung end
        local press = EX.getv(EX.SAVE_PRESS .. res)
        EX.pressure[res] = press or 0
        -- A shock outlives a save, or reloading is a way to un-raze a settlement.
        local sh = EX.getv(EX.SAVE_SHOCK .. res)
        EX.shock[res] = sh or 0
        local why = EX.getv(EX.SAVE_SHOCK_WHY .. res)
        EX.shock_why[res] = (why and why ~= "") and why or nil
        local hist = EX.getv(EX.SAVE_HIST .. res)
        EX.history[res] = {}
        if hist then
            -- stored as a comma-joined string: a table saved value is not worth the risk here
            for n in string.gmatch(hist, "[^,]+") do
                EX.history[res][#EX.history[res] + 1] = tonumber(n)
            end
        end
        local deep = EX.getv(EX.SAVE_DEEP .. res)
        EX.deep[res] = {}
        if deep and deep ~= "" then
            for n in string.gmatch(deep, "[^,]+") do
                EX.deep[res][#EX.deep[res] + 1] = tonumber(n)
            end
        end
        -- A SAVE FROM BEFORE THE DEEP BUFFER EXISTED seeds from the sparkline it does
        -- have, so an in-flight campaign starts the chart with twelve real turns rather
        -- than a blank panel, and fills to forty from there. Without this the feature
        -- looks broken for 28 turns to everyone who is already playing.
        if #EX.deep[res] == 0 and #EX.history[res] > 0 then
            for i = 1, #EX.history[res] do
                EX.deep[res][i] = EX.history[res][i]
            end
        end
    end
    -- The per-turn duplicate guard, or a reload is a way to shock the same region twice.
    EX.shocked = {}
    local seen = EX.getv(EX.SAVE_SHOCKED)
    if seen and seen ~= "" then
        for k in string.gmatch(seen, "[^;]+") do EX.shocked[k] = true end
    end

    -- EVERY HUMAN'S SLICE, not just this client's.
    --
    -- WHY ALL OF THEM ON EVERY MACHINE. The turn round below charges rent, pays dividends and
    -- settles paper for each human in turn, ON EVERY MACHINE - that is the whole of how this
    -- mod stays in sync. A machine that restored only its own player's position would compute
    -- a different number for everybody else on the very first turn after a load.
    for _, f in ipairs(EX.humans()) do
        EX.with_player(f, function() EX.restore_player() end)
    end
end

-- THE PER-PLAYER HALF OF EX.restore, run with a subject bound. Split out rather than inlined
-- because it is also the only correct way to add a player who joined mid-campaign: bind them
-- and call this, and they get empty tables rather than the last player's.
function EX.restore_player()
    pcall(function() EX.unpack_log(EX.getp(EX.SAVE_LOG)) end)
    EX.shares_held = {}
    for _, h in ipairs(EX.houses) do
        EX.shares_held[h] = EX.getp(EX.SAVE_SHARES .. h) or 0
    end
    EX.offer_until = {}
    for _, res in ipairs(EX.instruments()) do
        local until_turn = EX.getp(EX.SAVE_OFFER .. res)
        if until_turn then EX.offer_until[res] = until_turn end
    end
    pcall(function() EX.unpack_orders(EX.getp(EX.SAVE_ORDERS)) end)
    pcall(function() EX.unpack_deals(EX.getp(EX.SAVE_DEALS)) end)
    EX.demand_turn = EX.getp(EX.SAVE_DEMAND) or 0
    -- A DEMAND IN FLIGHT SURVIVES A SAVE. It is three plain values rather than a table:
    -- the deadline has to outlive a reload or an unpaid tithe would quietly forgive itself.
    -- Empty string, not nil, is the cleared state - cm:set_saved_value has no delete.
    local dres = EX.getp(EX.SAVE_DEM_RES)
    EX.demand_res = (dres and dres ~= "") and dres or nil
    local dtier = EX.getp(EX.SAVE_DEM_TIER)
    EX.demand_tier = (dtier and dtier ~= "") and dtier or nil
    EX.demand_due = EX.getp(EX.SAVE_DEM_DUE) or 0
    -- The escalation has to survive a reload, or every load resets the altar's appetite.
    EX.offerings_made = EX.getp(EX.SAVE_OFFERINGS) or 0
end

-- ONE STORE, TWO LENGTHS. The deep buffer is appended to and the sparkline is taken as
-- its tail, so a turn is recorded exactly once. Two independent buffers would eventually
-- disagree about the same turn, and the one on screen is the one nobody would check.
function EX.remember(res, rung)
    local d = EX.deep[res] or {}
    d[#d + 1] = rung
    while #d > EX.DEEP_BARS do table.remove(d, 1) end
    EX.deep[res] = d
    local dp = {}
    for _, v in ipairs(d) do dp[#dp + 1] = tostring(v) end
    EX.setv(EX.SAVE_DEEP .. res, table.concat(dp, ","))

    local h = {}
    for i = (#d - EX.SPARK_BARS + 1 > 1 and #d - EX.SPARK_BARS + 1 or 1), #d do
        h[#h + 1] = d[i]
    end
    EX.history[res] = h
    -- STILL WRITTEN, deliberately. It is redundant with the deep buffer and costs one
    -- saved value per instrument per turn, and it is what lets a player roll back to the
    -- previous build without their sparklines going blank. Drop it a release after the
    -- deep buffer has shipped, not before.
    local parts = {}
    for _, v in ipairs(h) do parts[#parts + 1] = tostring(v) end
    EX.setv(EX.SAVE_HIST .. res, table.concat(parts, ","))
end

-- The deep buffer with its high and low, for the chart. Returns the table, the lowest
-- rung, the highest, and the index of the highest - the chart labels all three.
function EX.deep_of(res)
    local d = EX.deep[res] or {}
    if #d == 0 then return d, nil, nil, nil end
    local lo, hi, hi_at = d[1], d[1], 1
    for i = 2, #d do
        if d[i] < lo then lo = d[i] end
        if d[i] > hi then hi, hi_at = d[i], i end
    end
    return d, lo, hi, hi_at
end

-- THE TREND ARROW, DERIVED RATHER THAN REMEMBERED.
--
-- It used to compare against EX.last, a plain in-memory table refilled only at turn start - so
-- a LOAD left it empty and the reader's fallback made every row equal to itself: all nineteen
-- arrows flat until the next turn ticked. Found by comparing two screenshots of the SAME save
-- at the same treasury and the same prices, one with arrows and one without.
--
-- EX.history already holds the answer and is persisted. EX.remember_all appends this turn's
-- rung after apply_prices, so the entry before it is last turn's rung - exactly what EX.last
-- held, and it survives the load that broke the old one.
--
-- IT ALSO INHERITS THE SPARKLINE'S PROTECTION. The bug EX.snapshot_trend was created to fix
-- was a baseline reset by every trade; nothing but the turn boundary appends to history, and
-- check_trend_snapshot already pins EX.remember_all there. One source of truth, one guard.
function EX.prev_rung(res)
    local h = EX.history[res]
    -- NO LENGTH TEST. h[0] and h[-1] are both nil in Lua, so an empty or one-bar history
    -- already answers nil - a "#h < 2" guard was written here and deleted again when no input
    -- could tell the two apart. EX.restore assigns {} for every instrument, so the nil check
    -- only covers a key that is not an instrument at all.
    return h and h[#h - 1]
end

-- A NUMBER AS A PLAYER SHOULD SEE IT. WH3's Lua is SINGLE-PRECISION: an MCT slider set to
-- 0.2 comes back as 0.20000000298023, and concatenating it straight into a sentence is what
-- put "at 0.20000000298023 gold per unit per turn to ..." in the Offerings footer - fourteen
-- junk characters, which then pushed the line past the box and fit() amputated the end of it.
-- Reported from a screenshot 2026-09-08.
--
-- Three decimals then trimmed, rather than a fixed %.2f: the MCT sliders this reads are not
-- all two-decimal, and a hard %.2f would silently round a 0.125 to 0.13 in the text while the
-- economy went on using 0.125. Integers come out with no decimal point at all.
function EX.num(v)
    if type(v) ~= "number" then return tostring(v) end
    local t = string.format("%.3f", v)
    t = string.gsub(t, "0+$", "")
    t = string.gsub(t, "%.$", "")
    return t
end

-- THE OFFERINGS FOOTER, as a function rather than inline in refresh_panel.
--
-- IT IS A FUNCTION BECAUSE NOTHING COULD MEASURE IT INLINE. check_footer_bounds runs the
-- shipped summary FUNCTIONS - appetite_summary, guild_summary, closed_banner - against a
-- worst-case board and measures what comes back. These two lines were the only footer built
-- inside refresh_panel, which needs a live panel, so they were measured by nothing at all -
-- and line 2 duly overran the 880px box and had its ending amputated by fit() in a live
-- Cathay campaign (reported 2026-09-08, "...per turn to ...").
--
-- THE PATRON, NOT HASHUT. The possessive went with it rather than becoming a per-race field:
-- "The Council" and "The Court" both take "its", and one dropped word beats a pronoun column
-- in EX.RACES.
-- THE RACE'S NAME WITH AN ARTICLE, and only one. Two of the four names already begin with
-- "The " - "The Ivory Road" and "The Under-Market" - which is how the trade view came to read
-- "The The Ivory Road" (2026-09-08). Shared by the panel title and the opener button's
-- tooltip so the two cannot drift, and so a fifth race is handled in one place.
function EX.race_name()
    return (EX.race and EX.race.name) or "Exchange"
end

function EX.the_name()
    local nm = EX.race_name()
    if string.sub(nm, 1, 4) == "The " then return nm end
    return "The " .. nm
end

-- THE OPENER BUTTON'S TOOLTIP, BUILT AT RUNTIME.
--
-- It was a static componentleveltooltip in derpy_chd_exchange_button.twui.xml, and the comment
-- there argued against a runtime setter on the grounds that CA's Title||Body split is proven
-- only as literal XML and SetTooltipText might draw the pipes. That reasoning is stale: this
-- file already sets ||-split tooltips at runtime through set_tip - EX.buy_refusal's is one -
-- and they render. Meanwhile the static text said "The Zharr Exchange" to a Skaven player
-- (screenshot, 2026-09-08), which is the same fault as the patron literals one layer out.
--
-- The XML keeps a race-neutral version as the fallback for the window before the bind.
-- THE BODY IS THE SAME SENTENCE IN BOTH FILES and check_button_tip() asserts they match, so
-- editing one and not the other is a build error rather than a silent divergence.
EX.TIP_OPEN_BODY = "Buy and sell the world's trade goods at prices set by how scarce they "
    .. "are on the map, and by who controls them. Closed while the other powers take their turn."

function EX.button_tip()
    return EX.the_name() .. "||" .. EX.TIP_OPEN_BODY .. EX.button_news()
end

-- WHAT IS WAITING, on the opener's own tooltip: the two things on the panel with a clock on
-- them. Deals expire at the end of the turn they were posted and a tithe turns to wrath, and
-- until this the only way to learn that either existed was to open the panel and look.
function EX.button_news()
    local out = ""
    local n = #(EX.deals or {})
    if n > 0 then
        out = out .. " " .. n .. (n == 1 and " deal is" or " deals are")
            .. " waiting on the Deals tab, gone at the end of this turn."
    end
    local t = EX.tithe()
    if t then
        out = out .. " " .. EX.patron() .. " demands " .. t.amount .. " " .. EX.display(t.res)
            .. " within " .. t.left .. (t.left == 1 and " turn." or " turns.")
    end
    return out
end

-- The opener's tooltip again, for the moments place_button does not run: a deal taken or a
-- tithe paid mid-turn changes what it should say. Written, never read - reading a HUD
-- button's tooltip back crashes the game.
function EX.refresh_button_tip()
    local b = find_uicomponent(core:get_ui_root(), EX.BUTTON)
    if is_uicomponent(b) then b:SetTooltipText(EX.button_tip(), true) end
end

function EX.offer_footer()
    local l1 = EX.patron() .. " takes " .. EX.offer_cost() .. " units and grants favour for "
        .. EX.OFFER_TURNS .. " turns; the goods are burned."
    -- EX.num, NOT the raw option. WH3's Lua is single-precision, so a 0.2 slider reads back
    -- as 0.20000000298023 - fourteen junk characters, which is what pushed this line past the
    -- box in the first place.
    -- SHORTENED from "a standing bonus of rising size ... per turn to warehouse", which came
    -- to 120 characters against the 118-character footer budget even after the float was
    -- formatted. "a rent of" also matches what the Held / rent column and the Trade footer
    -- both call the same charge - one number, one name.
    local l2 = "Holding " .. table.concat(EX.STOCK_TIERS, " / ") .. " units instead earns a "
        .. "rising standing bonus, at a rent of " .. EX.num(EX.opt("carry_per_unit"))
        .. " gold per unit per turn."
    -- A PENDING TITHE TAKES LINE 2. The demand was announced once, in the event feed, and this
    -- is the only other place its deadline is written; the warehouse note is in the guide.
    local t = EX.tithe()
    if t then
        l2 = EX.patron() .. " demands " .. t.amount .. " " .. EX.display(t.res) .. " within "
            .. t.left .. (t.left == 1 and " turn" or " turns") .. ". Unpaid, the wrath lasts "
            .. t.wrath .. " turns."
    end
    return l1, l2
end

function EX.trend_arrow(res)
    local now = EX.current[res] or 0
    -- Nothing to compare against yet - a fresh campaign's first turn. Comparing the row with
    -- itself reads flat, which is the truth rather than a guess at a direction.
    local was = EX.prev_rung(res) or now
    if now > was then return EX.TREND_UP end
    if now < was then return EX.TREND_DOWN end
    -- DIRECTION FIRST. The turn a price climbs INTO the cap is an honest rise and reads UP;
    -- only the turns after it are the pin. `now > 0` covers the nil-EX.current fallback on
    -- the first line, which is 0 and would otherwise read as the floor.
    if now >= EX.RUNGS then return EX.TREND_CAP end
    if now > 0 and now <= 1 then return EX.TREND_FLOOR end
    return EX.TREND_FLAT
end

-- ---------------------------------------------------------------------------------------
-- Supply and pricing.
-- ---------------------------------------------------------------------------------------

-- Walk every region once and count who produces what. Region-to-resource lives in the
-- startpos, not the DB - no table maps a region to its resource - so this is the only way to
-- learn the map's supply.
-- Returns supply[res] = total output, and owners[res] = {faction_name -> output amount}.
-- Returns nil on failure, which means "hold last turn's picture" - see EX.apply_prices. Half a
-- map is worse than a stale one: it would price every commodity as scarce for one turn.
-- What a region puts on the market: the latent deposit plus whatever is actually built.
-- Returns a list of {res, amount} pairs, empty if the region contributes nothing.
--
-- EXTRACTED so the supply scan and the shock handlers read the map through the same code.
-- They have to: a shock is priced as a share of world supply, and a shock that disagreed with
-- the scan about which goods a region makes would move a price the next reprice then quietly
-- undoes.
EX.region_last = {}    -- region name -> the goods list from the last scan. In memory only.

function EX.region_goods(region)
    local out_list = {}
    -- LATENT: the deposit itself, whether or not anything is built on it.
    for _, res in ipairs(EX.COMMODITIES) do
        if region:resource_exists(res) then
            out_list[#out_list + 1] = { res, EX.LATENT_PER_REGION }
        end
    end

    -- PRODUCTION: what is actually built. This is the supply term that matters, and
    -- resource_exists above is NOT a substitute for it - measured on a live map, four Ulthuan
    -- regions produce trinkets with resource_exists false, while ten to sixteen medicine,
    -- obsidian and ivory deposits produce nothing at all. The deposit is a terrain
    -- prerequisite for SOME buildings; the building is always the producer.
    --
    -- EX_PRODUCTION is read HERE and not at load: it lives in
    -- zzz_derpy_chd_exchange_prod.lua, every script/campaign/mod/*.lua autoloads, and the
    -- order between two of them is not guaranteed.
    local prod = EX_PRODUCTION
    if prod then
        local slots = region:slot_list()
        for si = 0, slots:num_items() - 1 do
            local slot = slots:item_at(si)
            if slot:has_building() then
                -- A LIST OF PAIRS, not one pair. 27 vanilla buildings make more than one good
                -- - Hag Graef's mines are iron AND marble at 96 each by tier 4, and Peg Street
                -- Pawnshop makes five at once.
                --
                -- An unmapped producer is IGNORED IN SILENCE on purpose: res_gold and the
                -- pasture buildings carry production effects and are not tradeable goods, and
                -- a modded building we do not know about is not an error either.
                local e = prod[slot:building():name()]
                if e then
                    for k = 1, #e do
                        local res, amount = e[k][1], e[k][2]
                        if EX.is_commodity(res) then
                            out_list[#out_list + 1] = { res, amount }
                        end
                    end
                end
            end
        end
    end
    return out_list
end

function EX.scan_supply()
    local supply, owners = {}, {}
    local blockaded = 0
    -- WORLD APPETITE, gathered in the SAME walk. A second pass over faction_list would be ~250
    -- interfaces re-fetched for two booleans the region walk already has an owner handle for.
    -- culture() and at_war() are cached PER FACTION NAME, not called per region: 750 regions
    -- across ~80 landholders is an order of magnitude of wasted calls otherwise.
    local fcache, culture_regions, house_regions = {}, {}, {}
    -- PER-CULTURE WAR, in the same walk as the world total. The drift term asks "is THIS
    -- culture fighting", which the single world war_index cannot answer - it applies the
    -- same war pressure to a culture at peace as to one that is losing.
    local culture_war = {}
    local total_regions, war_regions = 0, 0
    for _, res in ipairs(EX.COMMODITIES) do
        supply[res] = 0
        owners[res] = {}
    end
    local ok, err = pcall(function()
        local regions = cm:model():world():region_manager():region_list()
        for i = 0, regions:num_items() - 1 do
            local region = regions:item_at(i)
            -- A RAZED OR ABANDONED REGION IS NOT ON THE MARKET. It still answers
            -- resource_exists(), so the ownership-blind scan counted every sacked settlement
            -- as full supply and quietly held the price down for a producer nobody owns.
            -- Checked FIRST because owning_faction() on an abandoned region is a NULL
            -- INTERFACE, and a null interface answers nothing but is_null_interface - calling
            -- :name() on one is an error that would kill the whole walk, not a nil.
            -- OPTION D: A BESIEGED REGION IS OFF THE MARKET. Nothing leaves a settlement
            -- with an army camped outside it, so a siege takes the region out of supply
            -- entirely - not just off its owner's tally - and the price moves while the siege
            -- lasts. is_under_siege lives on GARRISON_RESIDENCE_SCRIPT_INTERFACE, reached
            -- through region:garrison_residence(); a region without one answers a null
            -- interface, so it is guarded like every other interface in this walk.
            local skip = region:is_abandoned()
            if not skip then
                -- ITS OWN pcall, not the walk's. The siege read is an enhancement, and it must
                -- never be able to blank the whole map: the outer pcall's failure mode is
                -- "hold last turn's prices for every commodity", which is a very large
                -- consequence for one odd region. Caught by check_lua_scan, whose stub regions
                -- had no garrison_residence and took the entire scan down with them.
                local okg, besieged = pcall(function()
                    local gr = region:garrison_residence()
                    return gr and not gr:is_null_interface() and gr:is_under_siege()
                end)
                if okg and besieged then
                    blockaded = blockaded + 1
                    skip = true
                end
            end
            if not skip then
                local owner = region:owning_faction()
                local oname = nil
                if owner and not owner:is_null_interface() then oname = owner:name() end

                -- Its own pcall for the same reason the siege probe has one: appetite is an
                -- enhancement and must never be able to blank the whole map. A faction whose
                -- culture cannot be read simply has no appetite, and still counts as land.
                if oname then
                    local info = fcache[oname]
                    if not info then
                        local okf, c, w = pcall(function()
                            return owner:culture(), owner:at_war()
                        end)
                        -- ITS OWN pcall, not the culture/war one above. Treasury is an
                        -- enhancement over land the walk already counts, and it must never be
                        -- able to cost a faction its culture along with it - a faction whose
                        -- treasury cannot be read is simply an actor with 0 gold, the correct
                        -- "cannot buy" degradation a later consumer will apply; it must not
                        -- also go silently missing from culture_regions and every appetite
                        -- that feeds.
                        local okt, t = pcall(function() return owner:treasury() end)
                        info = { culture = okf and c or nil,
                                 war = (okf and w) == true,
                                 gold = (okt and t) or 0,
                                 regions = 0 }
                        fcache[oname] = info
                    end
                    info.regions = info.regions + 1
                    total_regions = total_regions + 1
                    if info.culture then
                        culture_regions[info.culture] =
                            (culture_regions[info.culture] or 0) + 1
                    end
                    -- One line, on a walk that already has the owner and its culture. The
                    -- alternative is a second faction_list pass for a number we are holding.
                    if EX.is_house_culture(info.culture) then
                        house_regions[oname] = (house_regions[oname] or 0) + 1
                    end
                    if info.war then
                        war_regions = war_regions + 1
                        if info.culture then
                            culture_war[info.culture] =
                                (culture_war[info.culture] or 0) + 1
                        end
                    end
                end

                -- add() keeps supply and the concentration tally in the same units. They MUST
                -- agree: EX.hhi is a share-of-supply measure, so an owners table counting
                -- regions against a supply counting output would make every share meaningless.
                local function add(res, amount)
                    supply[res] = supply[res] + amount
                    -- An owned region with no readable owner still counts as supply; it just
                    -- belongs to nobody for concentration, which is the honest read.
                    if oname then
                        owners[res][oname] = (owners[res][oname] or 0) + amount
                    end
                end

                -- ONE READ of what this region puts on the market, shared with the shock
                -- handlers. They MUST agree: a shock that priced a commodity the scan does
                -- not think comes from that region would move a price nothing supports, and
                -- the next reprice would silently undo it.
                local goods = EX.region_goods(region)
                for gi = 1, #goods do
                    add(goods[gi][1], goods[gi][2])
                end
                -- Kept per region, in memory only, because a RAZED settlement answers with
                -- nothing: by the time CharacterRazedSettlement fires the buildings are gone,
                -- so reading the region live would give the flagship shock a supply loss of
                -- zero. The last completed scan is the only record of what was there.
                EX.region_last[region:name()] = goods
            end
        end
    end)
    if not ok then
        EX.say("error", "supply scan failed, prices hold at their last step: "
            .. tostring(err))
        return nil, nil
    end
    if blockaded > 0 then
        EX.say("price", blockaded .. " besieged regions are off the market")
    end
    -- Shares are taken over the COUNTED regions, not over num_items(), so they sum to 1. A
    -- razed or besieged region is out of the market and out of the appetite with it - the
    -- province still has mouths, but nothing is leaving it, which is the same reason its
    -- output came off supply.
    -- ponytail: besieged land drops out of demand as well as supply. Split them if a long
    -- siege ever reads as the world losing its appetite rather than its access.
    local share = {}
    if total_regions > 0 then
        for c, n in pairs(culture_regions) do share[c] = n / total_regions end
    end
    local war = 0
    if total_regions > 0 then war = war_regions / total_regions end
    -- PER-CULTURE WAR AS A FRACTION OF THAT CULTURE'S OWN LAND, not of the world. A
    -- culture holding 2% of the map and wholly at war must read 1.0, not 0.02: the
    -- question is whether it is fighting, and its size is already carried by the share
    -- this gets multiplied by in EX.world_appetite. Dividing by the world instead makes
    -- every culture's war term proportional to its size TWICE.
    local cwar = {}
    for c, n in pairs(culture_regions) do
        if n > 0 then cwar[c] = (culture_war[c] or 0) / n end
    end
    -- THE WORLD TIER'S ROSTER. Houses are excluded because they have the guild, which is
    -- deeper in every way: shares, dividends, delisting, stance. A faction in both would
    -- be priced twice and paid twice. Set directly here, not threaded through the return
    -- tuple, so a bare EX.scan_supply() call refreshes it exactly like every other export
    -- below - and a failed scan (the early return above) leaves last turn's roster alone,
    -- same as it leaves EX.supply and EX.owners alone.
    local actors = {}
    for name, info in pairs(fcache) do
        if not EX.is_house_culture(info.culture) then actors[name] = info end
    end
    EX.actors = actors
    return supply, owners, share, war, house_regions, cwar
end

-- ANY CULTURE HOLDING LAND THAT THIS MOD HAS NO APPETITE FOR, said once per campaign.
--
-- EX.world_appetite reads `if wants and wants[res]`, so a culture missing from
-- EX.CULTURE_WANTS contributes exactly ZERO to world demand - no fallback, no default, and
-- nothing anywhere saying so. The Southern Realms shipped that way for a whole build: covered
-- as a race, with a patron and seventeen flavour lines, and invisible to the prices those
-- describe. check_culture_appetites() now stops that happening to a race this mod covers.
--
-- IT CANNOT STOP IT HAPPENING TO SOMEBODY ELSE'S MOD. A build-time check only knows the
-- cultures installed on the machine that ran it, and the player's campaign is full of races
-- this pack has never heard of. So the game reports it instead: one line, naming the culture
-- and what share of the world's land it holds, the first time a scan sees it.
--
-- THE THRESHOLD IS NOT ZERO. A single region changing hands mid-war would otherwise announce a
-- culture that holds a rounding error. One per cent of the map is roughly a small faction and
-- is where a missing appetite starts to be worth knowing about - the Southern Realms were 2.4%.
EX.UNCOVERED_MIN = 0.01
EX.said_uncovered = nil

function EX.warn_uncovered(share)
    if not share then return end
    EX.said_uncovered = EX.said_uncovered or {}
    for c, sh in pairs(share) do
        if sh >= EX.UNCOVERED_MIN and not EX.CULTURE_WANTS[c]
           and not EX.said_uncovered[c] then
            EX.said_uncovered[c] = true
            EX.say("price", string.format(
                "%s holds %.1f%% of the world's regions and this mod has no appetite for "
                .. "it - it contributes nothing to any price. Add it to EX.CULTURE_WANTS.",
                c, sh * 100))
        end
    end
end

-- Refresh EX.supply / EX.owners, keeping the previous picture if the scan could not complete.
function EX.rescan()
    local supply, owners, share, war, house_regions, cwar = EX.scan_supply()
    if supply then
        EX.supply, EX.owners = supply, owners
        -- LAST TURN'S SHARES ARE TAKEN HERE AND NOWHERE ELSE, before this turn's overwrite
        -- them. By the time anything downstream runs, EX.culture_share is already new.
        -- Memory first, the save only as the reload bridge: a second reload inside one
        -- turn then reads its own value back and every trend is 0, which is the safe way
        -- to be wrong. A reload MINTING a trend would mint a demand shock with it, and
        -- that is the F9 gold printer EX.check_delistings already had to be guarded
        -- against - which is also why EX.share_shocks is called from the turn round only
        -- and never from here.
        --
        -- BOTH SAVE TOUCHES GET THEIR OWN pcall, for the reason the siege probe inside
        -- the scan has one: the trend is an ENHANCEMENT and must never be able to blank
        -- the whole map. The outer failure mode here is 'hold last turn's prices for
        -- every commodity', which is a very large consequence for a history read. A save
        -- that cannot be reached means no previous shares, which means no trend - not a
        -- dead scan. Caught by check_lua_appetite, whose stub board has no cm at all.
        if EX.culture_share then
            EX.culture_share_prev = EX.culture_share
        else
            local okp, prev = pcall(EX.load_cshare)
            EX.culture_share_prev = (okp and prev) or {}
        end
        EX.culture_share, EX.war_index = share, war
        EX.culture_war = cwar
        EX.house_regions = house_regions
        pcall(EX.save_cshare, share)
        EX.warn_uncovered(share)
    end
end

-- The largest holder of a commodity, and how much it produces - an output AMOUNT, not a region
-- count. This comment used to say "regions"; that wrong reading of EX.owners is what caused the
-- accrual approach withdrawn earlier in this effort, so get it from EX.owners directly rather
-- than trusting a comment that has been wrong before.
-- SKIP IS OPTIONAL, a faction key to exclude from the search - added for F2, REVIEW
-- 2026-09-13, so EX.settle_counterparty's rung 3 can fall through to the SECOND-largest holder
-- instead of refusing outright when the largest is the player. Every pre-existing caller passes
-- nothing and sees no change.
function EX.top_holder(res, skip)
    local best, bestn = nil, 0
    for name, n in pairs((EX.owners or {})[res] or {}) do
        if n > bestn and name ~= skip then best, bestn = name, n end
    end
    return best, bestn
end

-- THE GUILD IS THE LIVE HOUSES. A delisted house has settled and left; its book goes with it,
-- because nobody is owed anything for it and a dead house's position paying out would be a
-- second settlement racing EX.settle_house.
--
-- AND THIS IS WHERE MCT'S ai_traders SWITCH IS ENFORCED - at the one shared reader, not at the
-- call sites. EX.book_shift, EX.hostility, EX.refused_by, EX.market_closed, EX.guild_summary,
-- the counterparty search and EX.step_books all route through here, so an empty list is the
-- whole of "off means an empty guild" (spec 3 and 13).
--
-- Gating EX.step_books alone - which is what shipped - FROZE the market instead of switching it
-- off. Measured with books saved from a traders-on session: book_shift stuck at +2 rungs,
-- hostility 0.214, buy_price 1214 against a world price of 1000, refused_by still naming a
-- house and market_closed still firing - and permanently, because step_books is the only thing
-- that ever sells a book back down.
--
-- EX.houses IS A DIFFERENT LIST AND IS DELIBERATELY NOT GATED. That one is Layer 3's discovered
-- INSTRUMENT list - what EX.is_house, EX.instruments, EX.mode_instruments, EX.restore,
-- EX.check_delistings and the dividend read - and gating it would delete the Houses view and
-- strand every share position the player holds. The two lists overlap and are not the same
-- thing: this one is who trades, that one is what is traded.
function EX.guild()
    -- The memo, when one is held: see EX.hold_guild. It is scoped to a single refresh or turn
    -- step, so it can never outlive the diplomacy it was built from.
    if EX.guild_hold then return EX.guild_hold.list end
    if not EX.setting("ai_traders") then return {} end
    local g = {}
    for _, h in ipairs(EX.houses or {}) do
        if not EX.is_delisted(h) then g[#g + 1] = h end
    end
    return g
end

function EX.book_of(house, res)
    local b = EX.book[house]
    if not b then return 0 end
    return b[res] or 0
end

function EX.set_book(house, res, n)
    if n < 0 then n = 0 end          -- houses do not short; see spec 12
    EX.book[house] = EX.book[house] or {}
    EX.book[house][res] = n
    EX.setv(EX.SAVE_BOOK .. house, EX.pack_book(house))
end

-- The guild's NET position in a commodity - the level, not this turn's flow. This is what
-- prices; the flow is news.
function EX.guild_book(res)
    local total = 0
    for _, h in ipairs(EX.guild()) do total = total + EX.book_of(h, res) end
    return total
end

-- THE WORLD TIER'S BOOK. Mirrors EX.book_of / EX.set_book / EX.guild_book exactly; see those
-- for the reasoning that is identical. The one difference is the clear below.
EX.wbook = EX.wbook or {}

function EX.world_book_of(faction, res)
    local b = EX.wbook[faction]
    if not b then return 0 end
    return b[res] or 0
end

-- WHAT AN ACTOR'S LAND CAN MAKE, in LOTS. EX.owners[res][faction] is a production AMOUNT and
-- not a region count - the add() helper in EX.scan_supply is explicit about it, and the
-- comments on EX.top_holder and above EX.scan_supply both say "regions" and are both wrong.
-- Divide by EX.lot(res) or every number downstream is an order of magnitude out.
function EX.world_capacity(faction, res)
    local mine = ((EX.owners or {})[res] or {})[faction] or 0
    if mine <= 0 then return 0 end
    -- FLOOR THE PRODUCT, NOT THE FACTOR. floor(mine / lot) * TURNS discards everything under a
    -- lot BEFORE accumulating, so a faction making 6 units a turn of a 10-unit lot had capacity
    -- 0 forever rather than 1 lot every other turn. The world makes 6 units of glass a turn in
    -- total (measured, see the producible note in EX.validate_keys), so glass was refused from
    -- turn 1 for the life of the campaign.
    return math.floor(mine * EX.WORLD_STOCK_TURNS / EX.lot(res))
end

-- COULD THE WORLD TIER EVER SELL THIS? Capacity ignoring positions. This is the difference
-- between "drained" and "never a participant", and only the first is scarcity.
--
-- A commodity whose every producer is smaller than one lot is not the world tier's to refuse:
-- it cannot supply it, so it must not be able to veto the guild and top_holder supplying it.
-- Without this, a thin commodity is refused from turn 1 forever - which is not scarcity, it is
-- the market being taken away, and it shipped that way at default settings.
function EX.world_potential(res)
    local total = 0
    for faction in pairs(EX.actors or {}) do
        if not EX.is_human(faction) then
            total = total + EX.world_capacity(faction, res)
        end
    end
    return total
end

-- WHAT IT CAN SELL RIGHT NOW: what its land makes, plus whatever position it already holds. A
-- negative book is stock already sold forward, so it reduces this one for one; a positive book
-- is stock bought and held, and adds.
function EX.world_sellable(faction, res)
    local n = EX.world_capacity(faction, res) + EX.world_book_of(faction, res)
    if n < 0 then n = 0 end
    return n
end

function EX.set_world_book(faction, res, n)
    -- SHORT TO WHAT THE LAND MAKES, AND NO FURTHER - BUT NEVER SHALLOWER, EITHER. This
    -- replaces a floor at 0 that read "actors do not short, same rule as the houses". That
    -- rule is right for the guild, whose book is a warehouse it buys into, and wrong for a
    -- tier whose stock comes out of the ground every turn: a producer selling this turn's
    -- output IS short until it digs it up.
    --
    -- FIX ROUND 2, REVIEW 2026-09-13: THE FLOOR MUST NOT MINT GOODS WHEN CAPACITY SHRINKS.
    -- `EX.world_capacity` is re-derived from LIVE `EX.owners` on every single call, and
    -- `EX.owners` is rebuilt by every scan - so a faction that is already short and then loses
    -- the land that earned it that short has its floor rise (move toward zero) on its very
    -- next write. A plain `if n < floor then n = floor end` clamps ANY write below the new,
    -- shallower floor - including a write that was moving the position TOWARD zero, which is
    -- exactly what a buyer leg crediting an existing short does. That silently forgives part
    -- of the debt: measured through EX.step_world, a seller debited 3 while the buyer - short
    -- and just stripped of its land - was credited 6, net iron -6 to -3, 3 lots minted from
    -- nothing. The rule can only be one-sided: a write may not DEEPEN a short beyond capacity,
    -- and may always move a position toward zero, however far, however the capacity that
    -- produced the floor has since moved. `cur` is read before the new floor is applied, so
    -- "toward zero" is judged against what the position WAS, not against the new floor itself.
    local cur = EX.world_book_of(faction, res)
    local cap = EX.world_capacity(faction, res)
    -- (cap > 0) and -cap or 0, NOT -cap: Lua 5.1 has -0 and it stringifies as "-0" - the same
    -- trap EX.book_shift already guards against - and a zero-capacity floor must print as a
    -- clean 0, not a book that shows a player "-0".
    local floor = (cap > 0) and -cap or 0
    if n < cur and n < floor then n = math.min(cur, floor) end
    EX.wbook[faction] = EX.wbook[faction] or {}
    EX.wbook[faction][res] = n
    -- A FACTION WHOSE BOOK EMPTIES GIVES UP ITS SAVE KEY. The guild is fourteen names that
    -- exist for the whole campaign; this tier is ~80 that come and go, and a key per dead rump
    -- state is a save that only ever grows.
    local any = false
    for _, v in pairs(EX.wbook[faction]) do
        -- ~= 0, NOT > 0. A faction short in everything has a very real book, and testing for
        -- positives deleted its row and minted back every lot it owed.
        if v ~= 0 then any = true break end
    end
    if any then
        EX.setv(EX.SAVE_WBOOK .. faction, EX.pack_world_book(faction))
    else
        EX.wbook[faction] = nil
        EX.setv(EX.SAVE_WBOOK .. faction, nil)
    end
end

-- ITERATES THE BOOK, NOT THE ROSTER. Ruled 2026-09-13 in the pre-flight scan. `EX.wbook` is the
-- position record; `EX.actors` is a per-turn observation of the map. A faction missing from one
-- scan - conquered, a null interface, a scan that returned early - would otherwise drop its lots
-- out of the pricing term silently and jolt every price it was holding.
function EX.world_book(res)
    local total = 0
    for faction in pairs(EX.wbook or {}) do
        total = total + EX.world_book_of(faction, res)
    end
    return total
end

-- WHAT THE WORLD COULD SELL, as opposed to what it is net holding. EX.world_book is a NET
-- position and sums to roughly zero by construction - one actor's short is another's long - so
-- it answers "is the world long or short", which is the right question for pricing and the
-- wrong one for "can anybody sell me a lot".
--
-- ITERATES EX.actors, NOT EX.wbook, and that is the opposite of EX.world_book's rule. Capacity
-- comes from land the scan observed this turn, so an actor with no book at all still has supply
-- if it owns the ground; a faction in the book but off the map has a stale position, which
-- prices, but cannot sell anybody anything.
function EX.world_supply(res)
    local total = 0
    for faction in pairs(EX.actors or {}) do
        if not EX.is_human(faction) then
            total = total + EX.world_sellable(faction, res)
        end
    end
    return total
end

-- SORTED, so the same book always packs to the same string. Unsorted, pairs() order varies
-- and two identical positions produce two different saved values, which makes a diff of two
-- saves unreadable and a round-trip assertion flaky.
function EX.pack_book(house)
    local keys = {}
    for res, n in pairs(EX.book[house] or {}) do
        if n > 0 then keys[#keys + 1] = res end
    end
    table.sort(keys)
    local parts = {}
    for _, res in ipairs(keys) do
        parts[#parts + 1] = res .. "=" .. EX.book[house][res]
    end
    return table.concat(parts, ";")
end

-- WORLD BOOK'S PACKER, same sorted-key rule as EX.pack_book: unsorted, the same book packs
-- two different ways and a diff of two saves is unreadable.
function EX.pack_world_book(faction)
    local b = EX.wbook[faction] or {}
    local keys = {}
    -- ~= 0, NOT > 0. A short-only faction's book is a real position and must not be filtered
    -- out of the save - see EX.set_world_book's emptiness test for the same fix.
    for k, v in pairs(b) do if v ~= 0 then keys[#keys + 1] = k end end
    table.sort(keys)
    local parts = {}
    for _, k in ipairs(keys) do parts[#parts + 1] = k .. "=" .. b[k] end
    return table.concat(parts, ";")
end

-- A DETERMINISTIC HASH, BOUNDED ON PURPOSE. WH3's Lua numbers are single-precision floats,
-- so integers stop being exact above 16,777,216: the usual djb2 (h * 33 + byte, modulo 2^31)
-- silently loses low bits partway through a long key and stops being reproducible. Multiplier
-- 31 with modulus 65536 keeps the worst intermediate at 65535 * 31 + 255 = 2,031,840, well
-- inside float32's exact range, so the same key gives the same number on every machine and
-- after every reload.
function EX.key_hash(s)
    local h = 0
    for i = 1, #s do
        h = (h * 31 + string.byte(s, i)) % 65536
    end
    return h
end

-- A house's standing preference for a good, in the range -0.5 .. +0.5. Every house shares the
-- Chaos Dwarf culture, so EX.CULTURE_WANTS contributes an identical constant to all of them
-- and differentiates nothing; this is what makes two houses in identical circumstances behave
-- differently. Derived, not saved, because there is nothing to save when there is no roll.
function EX.house_bias(house, res)
    return (EX.key_hash(house .. "|" .. res) % 1000) / 1000 - 0.5
end

-- Lots this house may move in one direction this turn. Bounded three ways: by what its
-- treasury can actually pay, by BOOK_TRADE_MAX, and by the price of the good. A broke house
-- gets zero and can only sell, which is the feedback loop that makes a bad trader stop
-- mattering.
function EX.house_budget(house, res)
    local f = cm:get_faction(house)
    if not f or f:is_null_interface() then return 0 end
    local ok, gold = pcall(function() return f:treasury() end)
    if not ok or not gold or gold <= 0 then return 0 end
    local px = EX.price(res)
    if px <= 0 then return 0 end
    local n = math.floor(gold / px)
    if n > EX.BOOK_TRADE_MAX then n = EX.BOOK_TRADE_MAX end
    return n
end

-- Five terms, spec 4.2. All shapes. The inputs are all already in memory: EX.owners is
-- rebuilt by EX.scan_supply every turn and EX.pressure already persists per commodity.
function EX.house_desire(house, res)
    -- PRODUCTION. Owning regions that make it means selling it; owning none means importing.
    local mine = ((EX.owners or {})[res] or {})[house] or 0
    local d = (mine > 0) and -(0.4 * mine) or 0.5

    -- VALUE, in rungs from neutral. Linear and unbounded above neutral, so a good the guild
    -- has driven up attracts selling harder the further it goes. This is what stops a guild
    -- of one culture pinning a commodity at the ladder clamp.
    local rung = EX.current[res] or EX.neutral_rung()
    d = d + 0.15 * (EX.neutral_rung() - rung)

    -- POSITION. Already long reduces the appetite to add.
    d = d - 0.05 * EX.book_of(house, res)

    -- FRONT-RUN. Needs BOTH: a house hostile to the player, and the player accumulating.
    -- Either alone is a different behaviour nothing asked for.
    local stance = EX.stance_of(house)
    local press = (EX.pressure or {})[res] or 0
    if stance < 0 and press > 0 then
        d = d + (-stance) * 0.5
    end

    return d + EX.house_bias(house, res)
end

-- FIVE TERMS, and every input is already in memory - see the des_calls assertion. Mirrors
-- EX.house_desire's shape, minus the two house-only terms: there is no front-run term and no
-- house_bias, because a world faction does not watch the player's book. Watching it is a house
-- behaviour and stays one.
function EX.world_desire(faction, res)
    if EX.is_house(res) or EX.is_layer2(res) then return 0 end
    local info = (EX.actors or {})[faction]
    if not info then return 0 end

    -- PRODUCTION. Owning regions that make it means selling it; owning none means importing.
    -- Same shape and same constants as the house term.
    local mine = ((EX.owners or {})[res] or {})[faction] or 0
    local d = (mine > 0) and -(0.4 * mine) or 0.5

    -- TASTE. The culture appetite table, doing a better job than shifting an aggregate price:
    -- here it is this faction's personality. A culture with no entry contributes exactly zero
    -- and the faction is still an actor - it trades on the other four terms.
    -- EX.drift is deliberately NOT applied: drift shades a culture-level aggregate, and this
    -- faction's own war state is already the war term below. Both would count it twice.
    local wants = EX.CULTURE_WANTS[info.culture]
    if wants and wants[res] then d = d + wants[res] end

    -- WAR. The actor's OWN war state, not the world index - the world index applies the same
    -- pressure to a faction at peace as to one that is losing.
    if info.war then
        local wa = EX.WAR_APPETITE[res]
        if wa then d = d + wa end
    end

    -- VALUE, in rungs from neutral. Same term and same constant as the house version.
    local rung = EX.current[res] or EX.neutral_rung()
    d = d + 0.15 * (EX.neutral_rung() - rung)

    -- POSITION. Already long reduces the appetite to add. ONE-SIDED ON PURPOSE: a negative book
    -- is an actor that sold what its land made, which is its normal state and not an appetite
    -- to buy back. Left two-sided, a fully short producer scored up to +1.35 here and turned
    -- into the keenest buyer on the map for the very thing it produces.
    local pos = EX.world_book_of(faction, res)
    if pos > 0 then d = d - 0.05 * pos end

    return d
end

-- ONE BUY AND ONE SELL PER HOUSE PER TURN. Deliberately: at most ~14 book changes a turn is
-- a number a player can read in a footer, and a house that can only move once each way has a
-- legible character rather than a portfolio.
--
-- Houses trade at LAST turn's prices and EX.apply_prices reprices on the result. That is both
-- correct and free of the circular dependency a same-frame reprice would create.
--
-- NO ai_traders GATE HERE ANY MORE. It lives in EX.guild() instead, which is the only list
-- this loop reads and the list every other consumer reads too - see that function for what
-- gating this one alone actually did.
-- WHAT THE GUILD DID ON THE LAST STEP: { bought, sold, houses, buy = {res=n}, sell = {res=n} }.
-- Accumulated AS THE TRADES HAPPEN rather than diffed off the books afterwards, because a diff
-- would also count the player's own trades, every delisting and every book the reprice touched.
-- Read by EX.build_world_log and by nothing else.
EX.book_flow = nil

function EX.step_books()
    -- ONE STANCE VECTOR FOR THE WHOLE STEP. EX.house_desire's front-run term asks EX.stance_of
    -- once per house per commodity; unheld that is a full guild walk each time.
    EX.hold_guild()
    local flow = { bought = 0, sold = 0, houses = 0, buy = {}, sell = {} }
    for _, house in ipairs(EX.guild()) do
        local moved = false
        local best, best_d, worst, worst_d
        for _, res in ipairs(EX.COMMODITIES) do
            local d = EX.house_desire(house, res)
            if not best_d or d > best_d then best, best_d = res, d end
            if EX.book_of(house, res) > 0 and (not worst_d or d < worst_d) then
                worst, worst_d = res, d
            end
        end
        if best and best_d > 0 then
            local n = EX.house_budget(house, best)
            if n > 0 then
                EX.set_book(house, best, EX.book_of(house, best) + n)
                EX.pay_house(house, -n * EX.price(best))
                flow.bought = flow.bought + n
                flow.buy[best] = (flow.buy[best] or 0) + n
                moved = true
            end
        end
        if worst and worst_d < 0 then
            local n = EX.book_of(house, worst)
            if n > EX.BOOK_TRADE_MAX then n = EX.BOOK_TRADE_MAX end
            EX.set_book(house, worst, EX.book_of(house, worst) - n)
            EX.pay_house(house, math.floor(n * EX.price(worst) * (1 - EX.opt("spread"))))
            if n > 0 then
                flow.sold = flow.sold + n
                flow.sell[worst] = (flow.sell[worst] or 0) + n
                moved = true
            end
        end
        if moved then flow.houses = flow.houses + 1 end
    end
    EX.book_flow = flow
    EX.free_guild()
end

-- ===========================================================================================
-- THE WORLD TIER. Every OTHER landholding faction, matched against each other.
-- ===========================================================================================
--
-- ONE BUY AND ONE SELL PER ACTOR PER TURN, matched against each other. The guild's step_books
-- pays a house and the gold leaves the world; that is affordable for fourteen and is a
-- map-wide drain for eighty. So this pass MATCHES: the buyer pays exactly what the seller
-- receives, world gold is unchanged, and an order with no counterparty does not execute.
--
-- Finite supply falls out of that for free. You can only buy what somebody is selling, so
-- supply is finite because it is somebody's, not because a counter was decremented.
EX.world_flow = nil

-- STOCK NO LONGER ACCRUES. EX.world_capacity and EX.world_sellable, beside EX.world_book_of
-- below, read what an actor's land can put on the board straight off EX.owners on every call,
-- rather than banking a running stock that nothing ever draws down - see those two functions
-- for the reasoning and the shape. EX.accrue_world_stock is WITHDRAWN, not deprecated: it read
-- EX.owners as a region count when the add() helper in EX.scan_supply is explicit that it is a
-- production amount, it saturated EX.world_book_shift's position term permanently within a few
-- turns, and it only ever added, so the book ratcheted upward forever with nothing to match it.
--
-- EX.WORLD_STOCK_TURNS IS NOW HOW MANY TURNS OF PRODUCTION AN ACTOR MAY SELL FORWARD, not an
-- accrual cap. A negative book is stock already sold that has not been dug up yet, and this is
-- how far short of zero EX.set_world_book's floor lets that go: a faction may be short by up to
-- this many turns of what its land currently makes, and no further.
EX.WORLD_STOCK_TURNS = 3

function EX.step_world()
    if not EX.setting("ai_world") then
        -- CLEARED, NOT LEFT STALE. Without this, a player who switches the world tier off
        -- mid-campaign keeps seeing LAST turn's flow numbers forever, since the early return
        -- used to skip building a fresh (empty) one. Found 2026-09-13 in fix round 2.
        EX.world_flow = { bought = 0, sold = 0, actors = 0 }
        return
    end
    local buyers, sellers = {}, {}
    for faction in pairs(EX.actors or {}) do
        -- EVERY HUMAN IS EXCLUDED, same rule and same reason as EX.discover_houses: EX.actors
        -- is built in EX.scan_supply from every landholding faction whose culture is not
        -- Chaos Dwarf, with no human filter on that path - a player faction scores a real
        -- EX.world_desire, enters buyers/sellers, and would be traded on (and paid, or
        -- charged) without ever asking to be. EX.is_human is memoised (EX.humans() caches
        -- EX.human_list), so this costs nothing extra across ~80 actors. Found 2026-09-13 in
        -- fix round 2.
        if not EX.is_human(faction) then
            local best, best_d, worst, worst_d
            for _, res in ipairs(EX.COMMODITIES) do
                local d = EX.world_desire(faction, res)
                if not best_d or d > best_d then best, best_d = res, d end
                if EX.world_sellable(faction, res) > 0 and (not worst_d or d < worst_d) then
                    worst, worst_d = res, d
                end
            end
            if best and best_d > 0 then
                buyers[best] = buyers[best] or {}
                buyers[best][#buyers[best] + 1] = faction
            end
            if worst and worst_d < 0 then
                sellers[worst] = sellers[worst] or {}
                sellers[worst][#sellers[worst] + 1] = faction
            end
        end
    end

    -- A DEAD FACTION'S POSITION IS NOT A POSITION. Confirmed dead only: absence from EX.actors
    -- means the scan did not see it this turn, which EX.world_book deliberately tolerates.
    for faction in pairs(EX.wbook or {}) do
        local f = cm:get_faction(faction)
        -- cm:get_faction returns FALSE, not nil, for a key it does not know.
        if f and not f:is_null_interface() then
            local ok, dead = pcall(function() return f:is_dead() end)
            if ok and dead then
                EX.wbook[faction] = nil
                EX.setv(EX.SAVE_WBOOK .. faction, nil)
            end
        end
    end

    local flow = { bought = 0, sold = 0, actors = 0 }
    local moved = {}
    for _, res in ipairs(EX.COMMODITIES) do
        local bs, ss = buyers[res] or {}, sellers[res] or {}
        -- SMALLEST SIDE FIRST. The unmatched remainder of the longer side simply does not
        -- trade this turn - see the wld_unmatched assertion.
        local pairs_n = math.min(#bs, #ss)
        local px = EX.price(res)
        for i = 1, pairs_n do
            local buyer, seller = bs[i], ss[i]
            local n = EX.world_sellable(seller, res)
            if n > EX.opt("world_trade_max") then n = EX.opt("world_trade_max") end
            -- BOUNDED BY WHAT THE BUYER CAN ACTUALLY PAY, read off the scan.
            local gold = ((EX.actors or {})[buyer] or {}).gold or 0
            if px > 0 then
                local afford = math.floor(gold / px)
                if n > afford then n = afford end
                -- BOUNDED BY world_cash_max TOO, not just by gold. Without this, a trade
                -- priced over the cap has EX.pay_actor clamp the GOLD leg while the books
                -- below still move the full n lots - goods created from nothing, the same
                -- class of defect wld_net exists to catch, just invisible to it because
                -- gold still nets to zero. Found 2026-09-13 in fix round 1: reachable on
                -- shipped values (easy preset is 1500/2, and any price above 750 puts a
                -- 2-lot trade over that cap).
                local cap_lots = math.floor(EX.opt("world_cash_max") / px)
                if n > cap_lots then n = cap_lots end
            end
            if n > 0 then
                local cost = n * px
                -- THE TWO LEGS ARE THE SAME NUMBER. Not two independent pay calls sized
                -- separately: pay_actor clamps, and two clamps that disagree is a leak.
                -- WITH THE cap_lots CLAMP ABOVE, cost <= world_cash_max ALWAYS, so
                -- EX.pay_actor's own cap clamp can never actually bind here and paid == -cost
                -- exactly - this call is provably unreachable-as-a-clamp from this call site
                -- (same shape as the affordability floor discussed in the Task 5 report). A
                -- future edit that removes the cap_lots or afford pre-clamps above puts that
                -- guarantee back in EX.pay_actor's hands, so keep using the returned value.
                local paid = EX.pay_actor(buyer, -cost)
                EX.pay_actor(seller, -paid)
                -- SPEND THE SCANNED TREASURY AS A PER-TURN BUDGET, not a per-commodity
                -- allowance. Ruled 2026-09-13 in the pre-flight scan: `info.gold` is read
                -- fresh from the scan each turn, so without this an actor can afford the
                -- same treasury once for every one of the 17 commodities. The seller is
                -- credited for the same reason - it can turn round and buy with it.
                local bi = (EX.actors or {})[buyer]
                local si = (EX.actors or {})[seller]
                if bi then bi.gold = bi.gold + paid end        -- paid is negative
                if si then si.gold = si.gold - paid end
                EX.set_world_book(seller, res, EX.world_book_of(seller, res) - n)
                EX.set_world_book(buyer, res, EX.world_book_of(buyer, res) + n)
                flow.bought = flow.bought + n
                flow.sold = flow.sold + n
                moved[buyer], moved[seller] = true, true
            end
        end
    end
    for _ in pairs(moved) do flow.actors = flow.actors + 1 end
    EX.world_flow = flow
end

-- ===========================================================================================
-- THE AI NOTICES. Market position promotes a CAI strategic stance.
-- ===========================================================================================
--
-- CA's campaign AI has no hook that says "consider a trade", and nothing here pretends
-- otherwise - EX.step_books remains the only thing that ever moves a book. What the AI CAN be
-- told is how to FEEL about somebody:
-- cm:cai_strategic_stance_manager_promote_specified_stance_towards_target_faction makes a
-- stance "much more likely" to be chosen, and that reaches war targeting and deal generation -
-- the parts of the AI no DB row and no other script call can touch.
--
-- THE INPUT IS MARKET STATE AND NOTHING ELSE. Not EX.stance_of, and emphatically not
-- EX.standing_of: standing_of reads f:diplomatic_standing_with(player), which is the very
-- number a promoted stance goes on to move. Feeding it back in is a loop that walks every
-- house to VERY_UNFRIENDLY within a few turns under its own power, with the market
-- contributing nothing after the first one. The two terms below are the player's SHARES and
-- the player's WAREHOUSE, and the AI can move neither.
--
-- CLEAR THEN PROMOTE, EVERY TURN, NO MEMO. The same shape as EX.apply_trade_income removing
-- all eight bundles before applying one, for the same reason: the alternative is remembering
-- across a save what the engine currently holds, which is the exact bug EX.trade_swept had to
-- be added to fix. 14 houses x 2 calls is 28 engine calls a turn - against the 58,786
-- cm:get_faction calls EX.hold_guild was written to kill, this is free, and it cannot go stale.
--
-- IT STOMPS OTHER PROMOTIONS BETWEEN THE SAME PAIR. clear_all_promotions_between_factions is
-- not scoped to this mod, so a CA narrative script or another mod promoting a stance from a
-- Chaos Dwarf house toward the player loses it every turn this runs. That is what the MCT
-- switch is for - it is not a knob nobody needs.
--
-- BEST_FRIENDS AND BITTER_ENEMIES ARE DELIBERATELY UNUSED. A commodity position should colour
-- a relationship, not force an alliance or a blood feud.
EX.STANCE_STEPS = {
    [-2] = "CAI_STRATEGIC_STANCE_VERY_UNFRIENDLY",
    [-1] = "CAI_STRATEGIC_STANCE_UNFRIENDLY",
    [1]  = "CAI_STRATEGIC_STANCE_FRIENDLY",
    [2]  = "CAI_STRATEGIC_STANCE_VERY_FRIENDLY",
}
-- Shares in one house that read as one step friendlier. HOUSE_LOT_SIZE is 5, so this is five
-- deliberate buys rather than a position somebody backed into.
EX.STANCE_SHARES = 25
-- Units of a house's OWN goods in your warehouse that read as one step colder. STOCK_TIERS
-- starts at 100, so this sits above the first stockpile tier: hoarding enough to be noticed.
EX.STANCE_CORNER = 150

-- Steps, truncated TOWARD ZERO and clamped to the table above. Same trap as
-- EX.appetite_shift: math.floor(-0.5) is -1, so flooring a signed score would shove the AI a
-- whole step on a position far too small to mean anything.
--
-- `mine` is the player's holdings, hoisted by the caller - see EX.promote_stances.
function EX.stance_score(house, mine)
    local n = EX.held(house) / EX.STANCE_SHARES
    for _, res in ipairs(EX.COMMODITIES) do
        -- ONLY WHAT THIS HOUSE ACTUALLY PRODUCES. Hoarding gems is nothing to a house that
        -- owns no gem regions; EX.owners is rebuilt by EX.scan_supply every turn and is the
        -- same table the prices are taken from, so the two can never disagree about who
        -- sells what.
        if (((EX.owners or {})[res] or {})[house] or 0) > 0 then
            n = n - (mine[res] or 0) / EX.STANCE_CORNER
        end
    end
    local q = math.floor(math.abs(n))
    if q > 2 then q = 2 end
    if q == 0 then return 0 end
    if n < 0 then return -q end
    return q
end

function EX.promote_stances()
    if not EX.setting("ai_stance") then return end
    local up, down = 0, 0
    for _, f in ipairs(EX.humans()) do
        EX.with_player(f, function()
            -- HOISTED OUT OF THE HOUSE LOOP. EX.held goes through cm:get_faction and the
            -- pooled resource manager on every single call; asking it per house is 17 x 14
            -- interface reads a turn for seventeen numbers that cannot change while this runs.
            local mine = {}
            for _, res in ipairs(EX.COMMODITIES) do mine[res] = EX.held(res) end
            for _, house in ipairs(EX.guild()) do
                local step = EX.stance_score(house, mine)
                -- ITS OWN pcall, PER HOUSE. A key the stance manager will not take must cost
                -- that one house its stance, never the rest of the round - the same rule the
                -- siege probe inside EX.scan_supply follows. Nothing downstream reads a
                -- result, so there is nothing to fall back to.
                pcall(function()
                    cm:cai_strategic_stance_manager_clear_all_promotions_between_factions(
                        house, f)
                    local stance = EX.STANCE_STEPS[step]
                    if stance then
                        cm:cai_strategic_stance_manager_promote_specified_stance_towards_target_faction(
                            house, f, stance)
                    end
                end)
                if step > 0 then up = up + 1 elseif step < 0 then down = down + 1 end
            end
        end)
    end
    if up + down > 0 then
        EX.say("house", up .. " house(s) warmer, " .. down .. " colder on your book")
    end
end

-- The gold the concentration term is adding to this commodity's price, against the same map
-- with the same region count spread evenly. This is the number that has nowhere to go in the
-- trade view, and the reason the stats view exists.
-- No region on this map produces it, so there is no seller. Real markets in that position go
-- no-offer or squeeze upward without bound; ours clamps at MULT_MAX, which is a CEILING rather
-- than a discovered price. Buying at it was a no-op dressed as a trade: measured, 10 bought and
-- 10 sold back is exactly break-even, because the rung is already clamped at 42 and buying
-- pressure cannot push past it. So the buy is refused and the row reads "-".
--
-- LAYER 2 IS NOT THIS CASE and must stay buyable. Armaments and Raw Materials are never scanned
-- at all, so EX.supply is NIL for them, not 0. Conflating "unscanned" with "absent from the map"
-- would kill the only rows that feed anything outside this panel.
function EX.unavailable(res)
    if EX.is_layer2(res) then return false end
    local s = (EX.supply or {})[res]
    return s ~= nil and s <= 0
end

-- WHO WILL NOT SELL YOU THIS. Three conditions, all required - see the constants above.
-- Returns the house key so the tooltip can name it; nil means nobody.
function EX.refused_by(res)
    if not EX.setting("refusal") then return nil end
    if EX.is_house(res) or EX.is_layer2(res) then return nil end
    local total = EX.guild_book(res)
    if total <= 0 then return nil end
    for _, house in ipairs(EX.guild()) do
        local n = EX.book_of(house, res)
        if n > 0 and (n / total) >= EX.opt("refuse_share")
           and EX.treaty_tier(house) == "open"
           and EX.stance_of(house) <= -(1 - EX.REFUSE_RANK) then
            return house
        end
    end
    return nil
end

-- ENOUGH OF THE GUILD AT WAR AND THE EXCHANGE SHUTS. Weighted by book rather than counted by
-- head: one large house closing its book matters more than three small ones. Returns the
-- largest belligerent so the tooltip can name somebody.
function EX.market_closed()
    if not EX.setting("war_lock") then return nil end
    local total, at_war, worst, worst_n = 0, 0, nil, 0
    for _, house in ipairs(EX.guild()) do
        local n = 0
        for _, res in ipairs(EX.COMMODITIES) do n = n + EX.book_of(house, res) end
        total = total + n
        if EX.treaty_tier(house) == "war" then
            at_war = at_war + n
            if n >= worst_n then worst, worst_n = house, n end
        end
    end
    if total <= 0 then return nil end
    if (at_war / total) < EX.opt("guild_close") then return nil end
    return worst
end

-- A HOUSE AT WAR WILL NOT SELL YOU ITS OWN PAPER. Returns the house key, or nil.
--
-- HOUSE PAPER WAS OUTSIDE THE DIPLOMACY LAYER ENTIRELY and nobody had decided that it should
-- be. EX.hostility and EX.refused_by both early-return on is_house, so until now you could buy
-- into a faction you were actively at war with, at no markup, and draw a dividend off it every
-- turn. Reported from play 2026-09-07: 30 shares in The Legion of Azgorh, at war, paying +120g
-- a turn. The spec says nothing about the exemption and the guard carried no comment - it was
-- copied from the is_layer2 exclusion, which IS justified (layer 2 has no book), and extended
-- to houses without the question being asked.
--
-- Deliberately NOT a hostility markup: a share is a claim on the house itself, so war is a
-- yes/no about whether they will deal at all, not a price. Selling stays open, as everywhere.
function EX.house_at_war(res)
    if not EX.is_house(res) then return nil end
    if EX.treaty_tier(res) ~= "war" then return nil end
    return res
end

-- The one question the trade path and the row display both ask. FOUR causes now, and
-- EX.buy_refusal must test the same four in the same order or the button and the trade
-- disagree about whether a row is live.
--
-- Scarcity is LAST because it is the weakest claim: the guild's own refusals are about a
-- relationship and should be named first, and a player who is both refused by a house and out
-- of stock is better told about the house.
function EX.blocked(res)
    return EX.market_closed() or EX.house_at_war(res) or EX.refused_by(res) or EX.sold_out(res)
end

-- WHY THE BUY BUTTON IS DEAD, or nil if it is not. One answer for the row's price cell, its
-- button label, its disabled flag and its button tooltip, so those four cannot drift apart -
-- and one function a harness can run, which a row loop that needs a live panel is not.
--
-- The Buy button used to be built from EX.unavailable alone and then SetDisabled(false)
-- unconditionally, so a refused or war-locked row drew a live-looking "Buy 10" at a normal
-- price and did nothing at all when pressed but write an out() line. EX.blocked reached the row
-- only through EX.buy_tip, which is written on the PRICE cell - and nobody hovers a price when
-- the button beside it looks live. "Disabled, not hidden, and the tooltip says why" is this
-- file's own standard, from the AI-turn gate on the opener button and from the delisted-house
-- row in EX.refresh_panel.
--
-- BUY-SIDE ONLY, exactly as EX.trade's own guards are. A house that despises you is delighted
-- to take your goods cheap, and blocking a sell traps the player's capital with no exit.
-- THE WAR LOCK AND A HOUSE REFUSAL ARE DIFFERENT THINGS AND MUST NOT SHARE A SENTENCE.
--
-- This read EX.blocked, which is `market_closed() or refused_by()`, and then phrased whatever
-- came back as "<house> will not sell to you". When the war lock is what fired, market_closed
-- returns the LARGEST BELLIGERENT merely so the message has somebody to name - so every row on
-- the board said "The Legion of Azgorh will not sell to you", and a player reading twenty
-- identical rows concludes that one house owns every commodity on the map. Reported from play,
-- 2026-09-07, and it is exactly what the screenshot showed.
--
-- The footer had it right all along ("EXCHANGE CLOSED: at war with ..."). The button did not.
-- So: check the two causes separately and say which one it is.
--
-- Returns REASON, LABEL - one call still answers the price cell, the button label, the disabled
-- flag and the tooltip, which is the whole point of this function. The label used to be built
-- inline at the row with its own `gone and "No offer" or "Refused"`, which could drift from the
-- reason string beside it.
function EX.buy_refusal(res)
    -- FIRST, BECAUSE IT IS THE ONE REFUSAL THAT IS ABOUT THE PLAYER RATHER THAN THE MARKET.
    -- EX.trade already refuses a pool the faction does not carry - that guard was added on
    -- 2026-09-08 after a live Empire campaign charged gold for goods it then failed to grant -
    -- but the BUTTON said nothing, so the only way to find out was to lose the money.
    --
    -- It reads as an MP-only case and is not: EX.LAYER2 is now the union across every human,
    -- so a mixed multiplayer game puts the two Chaos Dwarf rows on the Empire player's board,
    -- and any future commodity that is not registered for a culture lands here too.
    if EX.pool_absent(res) then
        return "This market is not open to your people. Your faction carries no store for it.",
               "Closed to you"
    end
    if EX.unavailable(res) then
        return "Nothing on this map produces this. There is no seller.", "No offer"
    end
    local closed = EX.market_closed()
    if closed then
        return "The Exchange is shut: too much of the guild is at war with you, "
            .. EX.faction_display(closed) .. " chief among them. Selling stays open.", "Closed"
    end
    -- SAME ORDER AS EX.blocked, which is what actually refuses the trade.
    local war = EX.house_at_war(res)
    if war then
        return EX.faction_display(war) .. " is at war with you. It will not sell you a stake in "
            .. "itself, and pays you no dividend while the war lasts. Selling stays open.", "At war"
    end
    local by = EX.refused_by(res)
    if by then
        -- WHY THAT HOUSE HAS STANDING TO REFUSE. The Trade view shows map-wide Output and
        -- nothing about the guild's BOOK, which is the number refusal actually reads - so a
        -- player sees healthy production, an unexplained refusal, and reasonably concludes the
        -- named house must be the producer. Reported from play 2026-09-07. It usually is not:
        -- the refusing house had 0 fur-producing regions and 8 of the guild's 12 fur lots.
        local n, tot = EX.book_of(by, res), EX.guild_book(res)
        return EX.faction_display(by) .. " holds " .. n .. " of the guild's " .. tot
            .. " lots and will not sell to you. Selling stays open.", "Refused"
    end
    -- SAME ORDER AS EX.blocked, fourth cause. EX.unavailable above has already answered the
    -- "nothing on this map produces this" case, so reaching here means the good IS produced and
    -- simply nobody is holding a lot of it - which is also why sold_out's "unknown" fallback
    -- cannot reach this sentence.
    local out = EX.sold_out(res)
    if out then
        return "Nobody is holding any. " .. EX.faction_display(out) .. " owns the largest "
            .. "deposit and has none to sell. Selling stays open.", "Sold out"
    end
    return nil, nil
end

-- The Buy button's tooltip when nothing is wrong with it. Written on every refresh beside the
-- refusal reason above, so a row that STOPS being refused stops saying that it is.
-- "THE AMOUNT ON THE BUTTON", NOT "ONE LOT": the button reads "Buy 50" at x5 and moves all
-- of it, and this tooltip said one lot beside it.
EX.TIP_BUY = "Buy the amount on the button. Buying pushes the price up."
-- THE SELL BUTTON'S, WRITTEN BOTH WAYS FOR THE SAME REASON: greyed with too little held, and
-- given back its plain tooltip the moment a lot is held again.
EX.TIP_SELL = "Sell the amount on the button, under the Buy price."
EX.TIP_SELL_NONE = "You hold less than one lot of this."
EX.TIP_CANCEL = "Cancel this standing order."
-- ITS OWN TOOLTIP AND NOT EX.TIP_BUY: this button settles the whole deal at the agreed price,
-- every lot of it, and it is gone at the next turn whether it was taken or not.
EX.TIP_DEAL = "Settle this deal in full, at the price agreed. It expires at the end of the turn."

-- THE CLOSURE BANNER, in one place because two footers draw it. It used to live only inside
-- EX.guild_summary - which is the HOUSES footer - so the Trade view, the one view the player
-- actually buys from, said nothing at all while every Buy on it refused.
--
-- IT REPLACES THE LINE IT LANDS ON rather than being appended to one. Both footer lines it can
-- land on already carry clause lists that grow with the board, and a fourth growing clause is
-- what overran the 880px box once already - see check_footer_bounds().
function EX.closed_banner()
    local by = EX.market_closed()
    if not by then return nil end
    return "EXCHANGE CLOSED: at war with " .. EX.faction_display(by) .. ". Selling stays open."
end

-- What concentration is doing to this commodity's price, against a board on which NOBODY is
-- concentrated. Positive means cartelised relative to the map; negative means unusually widely
-- held, and therefore cheaper than it would otherwise be.
--
-- THE TWO MEDIANS ARE NOT INTERCHANGEABLE, and using one for both sides is the bug this
-- replaces. `EX.med` is the median of EFFECTIVE supplies, so pricing raw supply against it asks
-- "what if this one commodity were unconcentrated while the whole board stayed concentrated" -
-- which is nobody's question, and inflated every row by the board-wide divisor. Measured in game
-- 2026-09-05: it read +130 to +331 on a map where no faction held more than 11% of anything.
-- The real counterfactual prices raw supply against the RAW median.
-- RETURNS A PERCENTAGE, and is computed from the UNQUANTISED multipliers rather than from two
-- ladder prices. Subtracting two independently rounded prices carried +/-1 rung of jitter: a
-- difference of a fraction of a rung still straddles a boundary if the two sides fall either
-- side of it. Measured in game 2026-09-05 - Timber and Wine were both -2.2%, and the gold column
-- showed 0 for one and -91 for the other. The multiplier ratio has no such step.
function EX.premium(res)
    if EX.is_layer2(res) then return nil end
    local raw = (EX.supply or {})[res]
    if not raw or raw <= 0 then return nil end
    local flat = EX.price_multiplier(raw, EX.med_raw or raw)
    if flat <= 0 then return nil end
    local eff = EX.effective_supply(raw, EX.hhi((EX.owners or {})[res] or {}))
    return (EX.price_multiplier(eff, EX.med or raw) / flat - 1) * 100
end

-- A faction KEY is not a faction NAME - the same trap as res_rom_lead being "Salt". CA's
-- display names live at factions_screen_name_<key> (1,434 of them), so look it up rather than
-- printing the key. Cached: this runs once per row per refresh.
EX.fac_names = {}
-- A KEY MADE READABLE, for a faction whose loc is missing or is a placeholder. Strips the
-- namespace prefix, swaps underscores for spaces and capitalises: mixer_chd_black_kraken
-- becomes "Black Kraken". Not the faction's real name - nothing on the machine knows it - but
-- a name-shaped thing rather than a key, which is what a row on a panel needs.
function EX.humanise_key(key)
    local s = key
    for _, p in ipairs({ "wh3_dlc23_chd_", "wh3_dlc23_", "cr_chd_", "mixer_chd_", "cr_" }) do
        if string.sub(s, 1, #p) == p then
            s = string.sub(s, #p + 1)
            break
        end
    end
    s = string.gsub(s, "_", " ")
    -- gsub returns TWO values and the second is the match count, so this cannot be the tail
    -- of a return or of an argument list without discarding it - the count would be passed
    -- along as a second argument and land in whatever the caller does next.
    s = string.gsub(s, "(%a[%w]*)", function(w)
        return string.upper(string.sub(w, 1, 1)) .. string.sub(w, 2)
    end)
    return s
end

-- NO PLAIN FLAG ON string.find - EVER. string.find(s, p, 1, true) CORRUPTS WH3'S STRING
-- SUBSYSTEM PROCESS-WIDE: string.sub and string.find start returning garbage for every script
-- in the game, nothing throws, and only a restart recovers it. Measured live 2026-09-08 - one
-- call flipped a healthy session to broken - and independently found on 2026-08-21 by the MCP
-- bridge, whose strings_ok() tripwire exists for exactly this.
--
-- THIS IS WHAT BROKE THE PANEL FOR FOUR BUILDS. The call lived here, in a MEMOISED accessor, so
-- it fired on the first house name a session had not yet resolved - which is why the panel died
-- at a different row every run, why CA's own find_uicomponent began missing silently with no Lua
-- error, and why the MCP bridge went with it. The placeholder is matched as a plain PATTERN
-- instead; EX.LOC_PLACEHOLDER must therefore stay free of pattern magic, which check_lua_placeholder
-- asserts.
--
-- CA'S OWN PLACEHOLDER, which is a real localised string and therefore passes every empty
-- check. Two dead factions drew "[YOU SHOULDN'T SEE THIS]" on the Houses view, screenshotted
-- 2026-09-07 - the loc key EXISTS, it just resolves to CA's marker for a row nobody was
-- supposed to reach. Matched on the distinctive middle rather than on the whole string so a
-- differently-punctuated variant is still caught.
EX.LOC_PLACEHOLDER = "SHOULDN"

function EX.faction_display(key)
    if not key then return "-" end
    if EX.fac_names[key] then return EX.fac_names[key] end
    -- THE INDEX GOES INSIDE THE pcall. `pcall(common.get_localised_string, ...)` evaluates
    -- common.get_localised_string BEFORE pcall is entered, so a nil `common` throws right past
    -- the guard that exists to catch exactly that. The fallback below is worthless without
    -- this. Found when a harness with no `common` stub crashed here rather than degrading.
    local ok, loc = pcall(function()
        return common.get_localised_string("factions_screen_name_" .. key)
    end)
    local name
    if ok and loc and loc ~= "" and not string.find(loc, EX.LOC_PLACEHOLDER) then
        name = loc
    else
        name = EX.humanise_key(key)
    end
    EX.fac_names[key] = name
    return name
end

-- ===========================================================================================
-- WORLD APPETITE: what the map wants, on top of what it produces.
-- ===========================================================================================
--
-- THE LORE THIS ENCODES, because the mechanic is meaningless without it. Zharr-Naggrund is the
-- one city everybody has to deal with: the Dark Lands make everything and grow nothing, so the
-- Chaos Dwarfs import every organic thing they touch, and they are already the setting's great
-- caravan traders - weapons north to the Chaos tribes, slaves and grain back, Hobgoblin Khans
-- hauling for them along the overland routes east. The exchange is that traffic given a price
-- list, and EX.SPREAD is the Tower's toll on it.
--
-- So the WORLD is not modelled as traders visiting a market. Nobody outside the guild opts
-- in. The world moves the price BY EXISTING - by holding land and by going to war - and the
-- panel merely reports what the Sorcerer-Prophets already knew. That is why THIS TERM is a
-- LEVEL and not an accumulation: if the Greenskins hold a fifth of the map and want iron,
-- iron IS dearer, not GETTING dearer. It is recomputed from the map every turn, saved
-- nowhere, and cannot drift across a reload because there is no state to drift.
--
-- THE CHAOS DWARF HOUSES ARE THE EXCEPTION, and they are not the world - they are the guild
-- whose market this is, and the lore above says they are the setting's great caravan
-- traders. They DO opt in: EX.book_shift is an accumulation and sits beside EX.pressure_shift
-- for the reason this paragraph gives. See the AI traders spec, 2026-09-07.

-- Each culture's short list: what it buys, and what it has no use for. SPARSE ON PURPOSE -
-- anything unnamed is 0, so a culture is described by the four or five goods that characterise
-- it rather than by seventeen numbers nobody can defend. Values run -1 to +1.
-- A culture key absent from this table contributes nothing (wh2_main_rogue, and any modded
-- culture). check_lua_appetite asserts every key here is one of the 27 vanilla cultures and
-- every commodity named is real - both fail silently forever otherwise.
EX.CULTURE_WANTS = {
    -- THE SOUTHERN REALMS: an entrepot with an army habit. Tilea, Estalia and the Border
    -- Princes buy the inputs to war and civic vanity, and sell what the Middle Sea makes.
    --
    -- The negatives are the point. Wine, glass and spices all had DEMANDERS in this table and
    -- no supplier worth the name - the Dwarfs want glass at 1.0, and Empire, Bretonnia and
    -- Cathay all want spices - so a Mediterranean trading culture arriving as the counterparty
    -- is what the board was already shaped for. Wine pairs them with Bretonnia (-0.9), the only
    -- other exporter.
    --
    -- Consistent with TEB_FLAVOUR in tools/gen_zharr_exchange.py, and deliberately: the glass
    -- line there has them FILLING orders after a wreck off Bilbali, and the spice line has a
    -- galley out of Sartosa failing to arrive. A culture that supplies a good in its prose and
    -- demands it in its numbers is a mod arguing with itself.
    ["mixer_teb_southern_realms"] = { res_rom_iron = 0.9, res_rom_marble = 0.6, res_gems = 0.5,
        res_rom_wine = -0.8, res_rom_glass = -0.7, res_spices = -0.5 },
    -- Choppas and squigs. Greenskins smash what they cannot eat or swing.
    ["wh_main_grn_greenskins"] = { res_rom_iron = 1.0, res_animals = 0.7, res_rom_furs = 0.4,
        res_rom_marble = -0.8, res_rom_textiles = -0.6, res_trinkets = -0.8 },
    -- They make their own beer and gems and drink the first faster than they mine the second.
    ["wh_main_dwf_dwarfs"] = { res_rom_glass = 1.0, res_rom_iron = 0.8, res_gems = 0.3,
        res_trinkets = -1.0, res_animals = -0.6 },
    -- The setting's great consumer economy: everything, in bulk, all the time.
    ["wh_main_emp_empire"] = { res_rom_iron = 0.7, res_rom_lead = 0.6, res_rom_wine = 0.5,
        res_spices = 0.5, res_rom_textiles = -0.4, res_rom_timber = -0.3 },
    -- Knights and cathedrals. Bretonnia exports wine and would not dream of buying it.
    ["wh_main_brt_bretonnia"] = { res_rom_iron = 0.8, res_rom_marble = 0.7, res_spices = 0.4,
        res_rom_wine = -0.9, res_rom_furs = -0.3 },
    -- Sylvania is poor land and rich crypts.
    ["wh_main_vmp_vampire_counts"] = { res_rom_marble = 0.8, res_rom_iron = 0.5, res_gems = 0.4,
        res_medicine = -0.9, res_rom_lead = -0.7, res_rom_wine = -0.4 },
    -- Nagash's Undead Legions (9.0) trade as the Counts do.
    ["wh3_dlc29_nag_undead_legions"] = { res_rom_marble = 0.8, res_rom_iron = 0.5, res_gems = 0.4,
        res_medicine = -0.9, res_rom_lead = -0.7, res_rom_wine = -0.4 },
    -- Marauders arm themselves and salt what they raid.
    ["wh_main_chs_chaos"] = { res_rom_iron = 1.0, res_rom_lead = 0.6, res_rom_furs = 0.3,
        res_rom_marble = -0.7, res_rom_textiles = -0.5, res_trinkets = -0.6 },
    ["wh_dlc08_nor_norsca"] = { res_rom_iron = 0.9, res_rom_lead = 0.6, res_rom_glass = 0.5,
        res_rom_furs = -0.8, res_rom_marble = -0.6, res_trinkets = -0.5 },
    -- Beastmen buy crude iron and destroy everything civilisation values. Their expansion is
    -- the clearest luxury-price signal on the board.
    ["wh_dlc03_bst_beastmen"] = { res_rom_iron = 0.6, res_rom_furs = 0.3,
        res_rom_marble = -1.0, res_rom_textiles = -0.9, res_gold_idols = -0.9,
        res_trinkets = -0.9 },
    -- Athel Loren builds with living wood and dyes what it weaves.
    ["wh_dlc05_wef_wood_elves"] = { res_dyes = 0.8, res_medicine = 0.5,
        res_rom_iron = -0.7, res_rom_marble = -0.8, res_rom_timber = -0.6 },
    -- Ulthuan is the merchant power. It is the SOURCE of elven trinkets, so it sells them.
    ["wh2_main_hef_high_elves"] = { res_gems = 0.7, res_spices = 0.6, res_rom_wine = 0.5,
        res_trinkets = -1.0, res_rom_iron = -0.3 },
    -- Naggaroth is cold and barren, and Dark Elves heal nobody.
    ["wh2_main_def_dark_elves"] = { res_rom_iron = 0.9, res_rom_timber = 0.6, res_dyes = 0.5,
        res_medicine = -0.8, res_trinkets = -0.7 },
    -- Temple-cities and obsidian carving. Lustria is already made of gold.
    ["wh2_main_lzd_lizardmen"] = { res_obsidian = 0.9, res_rom_marble = 0.6,
        res_gold_idols = -0.9, res_animals = -0.6, res_medicine = -0.5 },
    -- Teeming millions to feed, and warpstone weapons to forge.
    ["wh2_main_skv_skaven"] = { res_rom_iron = 0.8, res_rom_lead = 0.9, res_medicine = 0.6,
        res_rom_marble = -0.8, res_rom_wine = -0.6 },
    -- Settra hoards. The dead need no salt, no medicine and no wine.
    ["wh2_dlc09_tmb_tomb_kings"] = { res_rom_marble = 0.9, res_gold_idols = 0.8, res_gems = 0.6,
        res_medicine = -1.0, res_rom_lead = -0.8, res_rom_wine = -0.7 },
    -- Ships, provisions and grog.
    ["wh2_dlc11_cst_vampire_coast"] = { res_rom_timber = 0.9, res_rom_lead = 0.7,
        res_rom_glass = 0.6, res_rom_marble = -0.7, res_medicine = -0.5 },
    -- The Silk Road's eastern terminus: it buys gems and spice and sells its own porcelain.
    ["wh3_main_cth_cathay"] = { res_gems = 0.8, res_spices = 0.6, res_rom_marble = 0.5,
        res_rom_textiles = -0.8, res_rom_furs = -0.4 },
    -- Perpetually mobilised, and it already has more furs than it can wear.
    ["wh3_main_ksl_kislev"] = { res_rom_iron = 0.8, res_rom_lead = 0.6, res_rom_timber = 0.5,
        res_rom_furs = -0.9, res_animals = -0.4 },
    ["wh3_main_pro_ksl_kislev"] = { res_rom_iron = 0.8, res_rom_lead = 0.6,
        res_rom_timber = 0.5, res_rom_furs = -0.9, res_animals = -0.4 },
    -- Ogres eat first and are paid second. Tusks are what they sell.
    ["wh3_main_ogr_ogre_kingdoms"] = { res_animals = 1.0, res_rom_lead = 0.8, res_spices = 0.6,
        res_rom_iron = 0.4, res_ivory = -0.9, res_trinkets = -0.7, res_rom_textiles = -0.5 },
    -- Zharr-Naggrund itself: it makes iron and obsidian and imports everything that grows.
    ["wh3_dlc23_chd_chaos_dwarfs"] = { res_rom_lead = 0.8, res_rom_timber = 0.8,
        res_medicine = 0.5, res_rom_iron = 0.4, res_obsidian = -0.6, res_trinkets = -0.8 },
    -- Blood for the Blood God. Comfort is for the weak.
    ["wh3_main_kho_khorne"] = { res_rom_iron = 1.0, res_rom_furs = 0.4, res_rom_wine = -0.9,
        res_trinkets = -0.9, res_rom_marble = -0.7, res_medicine = -0.8 },
    -- Excess, in every form that can be poured or worn.
    ["wh3_main_sla_slaanesh"] = { res_rom_wine = 1.0, res_spices = 0.8, res_dyes = 0.7,
        res_trinkets = 0.6, res_rom_iron = -0.6, res_rom_lead = -0.5 },
    -- Change, gold and colour.
    ["wh3_main_tze_tzeentch"] = { res_gems = 0.8, res_gold_idols = 0.7, res_dyes = 0.6,
        res_rom_lead = -0.6, res_rom_timber = -0.5 },
    -- Nurgle hoards medicine the way a gardener hoards seed, and salt is anathema to rot.
    ["wh3_main_nur_nurgle"] = { res_medicine = 0.9, res_spices = 0.4, res_rom_lead = -0.9,
        res_gems = -0.6, res_rom_marble = -0.4 },
    -- Daemons want weapons and offerings and nothing a living thing needs.
    ["wh3_main_dae_daemons"] = { res_rom_iron = 0.7, res_gold_idols = 0.5, res_medicine = -0.7,
        res_rom_lead = -0.7, res_rom_wine = -0.5 },
}

-- What a war does to each good, independent of who is fighting. Armies eat salt, burn timber,
-- bleed and need iron; nobody commissions a marble frieze during a siege.
-- EVERY COMMODITY APPEARS, including the zeroes: a missing key here is indistinguishable from
-- a deliberate war-neutral, and check_lua_appetite asserts the table is complete for that
-- reason. Dwarf Beer is 0 on purpose - it is drunk in the same quantity either way.
EX.WAR_APPETITE = {
    res_rom_iron     =  1.0,   -- the war good
    res_medicine     =  0.9,   -- the wounded
    res_rom_lead     =  0.8,   -- Salt: rations and preservation
    res_rom_timber   =  0.7,   -- siege engines, palisades, hulls
    res_rom_furs     =  0.4,   -- campaigning through a winter
    res_animals      =  0.2,   -- mounts and draught beasts
    res_obsidian     =  0.0,
    res_rom_glass    =  0.0,   -- Dwarf Beer: war-neutral
    res_rom_textiles =  0.0,   -- Pottery
    res_dyes         =  0.0,   -- banners offset finery
    res_spices       = -0.4,
    res_ivory        = -0.5,   -- Tusks
    res_rom_wine     = -0.6,
    res_rom_marble   = -0.7,
    res_gems         = -0.8,
    res_gold_idols   = -0.9,
    res_trinkets     = -0.9,
}

-- WHAT A GROWING POWER BUYS, and a shrinking one stops buying. Mirrors WAR_APPETITE's
-- shape and its rule: EVERY commodity carries a key including the zeroes, because a
-- missing one is indistinguishable from a deliberate growth-neutral, and both signs are
-- present, because a table with only positives pushes every price it touches one way for
-- the whole campaign.
--
-- The reading is construction, not consumption: a power annexing provinces roofs and arms
-- them before it decorates them, so timber and marble lead and the treasure goods go
-- negative - gems and idols are what a growing power SPENDS, not what it accumulates.
EX.BUILD_APPETITE = {
    res_rom_timber   =  1.0,   -- scaffolding, roofs, hulls
    res_rom_marble   =  0.9,   -- the buildings a growing power puts up
    res_rom_iron     =  0.7,   -- tools before weapons
    res_obsidian     =  0.5,
    res_rom_lead     =  0.4,   -- Salt: more mouths to feed
    res_animals      =  0.3,   -- draught beasts
    res_rom_glass    =  0.2,   -- Dwarf Beer
    res_rom_textiles =  0.2,   -- Pottery
    res_medicine     =  0.0,
    res_dyes         =  0.0,
    res_rom_furs     = -0.2,
    res_gems         = -0.3,
    res_gold_idols   = -0.4,
    res_trinkets     = -0.4,
    res_ivory        = -0.5,   -- Tusks
    res_spices       = -0.5,
    res_rom_wine     = -0.6,
}

-- ALL FOUR ARE UNCALIBRATED and ship deliberately small. CONCENTRATION_K was chosen the same
-- way and was completely inert in play for a day before measurement found it, so the ceiling
-- here is set low enough that a wrong constant cannot dominate the supply model it sits on top
-- of.
--
-- AI_MAX_RUNGS CLAMPS TWO TERMS INDEPENDENTLY, not one. EX.appetite_shift clamps here, and
-- since Task 6 so does EX.world_book_shift - each on its own, with no shared budget between
-- them - so the AI half's combined reach on a single price is DOUBLE what one clamped term
-- gives alone: at most +46% / -32% at the shipped default (ladder_step 1.10, AI_MAX_RUNGS 2),
-- not the +21% / -17% a single term produces in isolation. Per preset, both terms pinned at
-- their own ceiling in the same direction: easy (ladder_step 1.08, AI_MAX_RUNGS 1) +17% / -14%;
-- hard (1.13 / 3) +108% / -52%; ultra (1.18 / 5) +423% / -81%.
--
-- A SEPARATE WORLD-TIER CLAMP WAS CONSIDERED AND REJECTED. Every constant in this tier is an
-- uncalibrated guess until a campaign is played, the whole tier has its own off switch
-- (ai_world), and a seventh settings place for a number nobody has measured yet is surface
-- without benefit - so EX.world_book_shift shares this ceiling rather than minting its own.
EX.AI_GAIN      = 6.0    -- rungs per unit of net appetite, before the clamp
EX.WAR_WEIGHT   = 0.5    -- war modulates culture rather than drowning it
EX.WAR_BASELINE = 0.80   -- MEASURED, not guessed. war_index read 0.6235 / 0.6291 /
                         -- 0.8488 / 0.8969 at turns 1 / 2 / 17 / 27 of one IE campaign:
                         -- it climbs and flattens near 0.9, and only turns 1-2 sit below
                         -- 0.85. There is no resting state to centre on, so this is set
                         -- near the value a campaign spends most of its length at - the
                         -- war term then reads NEGATIVE through the quiet opening and
                         -- positive once the world burns, which is the intended swing.
                         -- Shipped at 0.35 on 2026-09-06 and never once went negative.
EX.AI_MAX_RUNGS = 2

-- The appetite in RUNGS, unrounded. Culture is the base, war is added on top - the two are
-- independent, so a good can be craved by a big culture AND dragged down by a warring world at
-- the same time. That is the case worth having: gemstones under an expanding Cathay in a
-- burning world.
-- LAST TURN'S SHARES, PACKED. Sorted for the reason EX.pack_book sorts: unsorted, pairs()
-- order varies and two identical worlds produce two different saved strings, which makes a
-- diff of two saves unreadable and any round-trip assertion flaky.
--
-- FOUR DECIMALS is a tenth of one region in a 750-region world, and keeps a 30-culture
-- campaign well inside a kilobyte of saved string.
function EX.pack_cshare(share)
    local keys = {}
    for c in pairs(share or {}) do keys[#keys + 1] = c end
    table.sort(keys)
    local parts = {}
    for _, c in ipairs(keys) do
        parts[#parts + 1] = c .. "=" .. string.format("%.4f", share[c])
    end
    return table.concat(parts, ";")
end

-- LUA'S %w EXCLUDES THE UNDERSCORE and every culture key is underscore-heavy, so the
-- capture is [%w_]+ and not [%w]+. A pattern that silently matches nothing here reads as
-- an empty world with no trend anywhere, which is indistinguishable from a quiet turn.
function EX.unpack_cshare(str)
    local out = {}
    for c, v in string.gmatch(tostring(str or ""), "([%w_]+)=([%d%.%-]+)") do
        out[c] = tonumber(v) or 0
    end
    return out
end

function EX.save_cshare(share) EX.setv(EX.SAVE_CSHARE, EX.pack_cshare(share)) end
function EX.load_cshare()      return EX.unpack_cshare(EX.getv(EX.SAVE_CSHARE)) end

-- HOW MUCH OF THIS CULTURE IS AT WAR, 0..1 of its own land.
--
-- AN UNMEASURED CULTURE FALLS BACK TO THE WORLD, NOT TO ZERO, and this is the one place
-- the silent-zero convention used everywhere else in this file would be actively wrong.
-- The drift term reads this as a DEVIATION from WAR_BASELINE, so a fallback of 0 does not
-- mean "unknown", it means "wholly at peace" - the most negative reading available - and
-- every culture the scan has not reached yet would drag its appetites hard the wrong way.
-- Falling back to WAR_BASELINE makes an unmeasured culture drift by exactly 0, which is
-- what unknown should cost. Caught by check_lua_appetite's stub board, which had no
-- culture_war table and inverted every appetite on it.
--
-- THE LIVE WORLD INDEX WAS THE FIRST ANSWER HERE AND IS THE WRONG ONE, though only just:
-- it degrades an unmeasured culture to the legacy world war term rather than to nothing,
-- which is defensible until you notice it is also unpredictable - the same unknown culture
-- drifts differently on a peaceful map and a burning one, for no reason a player could
-- read. The baseline is the boring answer and boring is right for a fallback.
--
-- IT IS ALSO NEARLY UNREACHABLE, which is why this is a small decision: culture_war and
-- culture_regions are filled in the SAME walk, so any culture with a share above zero has
-- an entry here, and a culture with a share of zero contributes nothing to
-- EX.world_appetite whatever its drift. The fallback only really answers direct callers.
function EX.war_share(c)
    local cw = EX.culture_war
    if cw and cw[c] then return cw[c] end
    return EX.WAR_BASELINE
end

-- HOW MUCH THIS CULTURE GREW OR SHRANK SINCE LAST TURN, as a fraction of its OWN previous
-- size: +0.1 is a tenth bigger, -0.5 is half gone. A culture with no previous entry is new
-- to the scan and reads 0 rather than infinite growth.
function EX.culture_trend(c)
    local prev = (EX.culture_share_prev or {})[c]
    local now  = (EX.culture_share or {})[c] or 0
    if not prev or prev <= 0 then return 0 end
    return (now - prev) / prev
end

-- THE DRIFT TERM: what a culture's own state does to what it wants.
--
-- BOTH HALVES ARE DEVIATIONS, NOT LEVELS, and that is what keeps them on the same scale as
-- the world war term they replace. That term is WAR_WEIGHT * appetite * (index - 0.80),
-- so at a typical index of 0.85 it is 0.025 * appetite - tiny, because it measures how
-- unusual the war is, not that there is one. A war half written as a LEVEL would be
-- 0.35 * 0.85 = 0.30 * appetite, twelve times larger, and would swamp the culture term it
-- is meant to shade. So war drift is measured against the same WAR_BASELINE, and growth is
-- already a deviation by construction (0 means unchanged).
--
-- DRIFT_MAX BOUNDS THE TOTAL so drift can shade an appetite and never invert it: a culture
-- at war wants more iron, it does not start supplying wine. Without the clamp a
-- confederation doubling a culture's share in one turn is a trend of 1.0 and would do
-- exactly that.
--
-- ALL THREE CONSTANTS ARE UNCALIBRATED and ship deliberately small, the same way the four
-- appetite constants above do.
EX.DRIFT_WAR    = 0.35
EX.DRIFT_GROWTH = 0.50
EX.DRIFT_MAX    = 0.25

function EX.drift(c, res)
    if not EX.feature("appetite_drift") then return 0 end
    local d = 0
    local wa = EX.WAR_APPETITE[res]
    if wa then
        d = d + EX.DRIFT_WAR * wa * (EX.war_share(c) - EX.WAR_BASELINE)
    end
    local ba = EX.BUILD_APPETITE[res]
    if ba then
        d = d + EX.DRIFT_GROWTH * ba * EX.culture_trend(c)
    end
    if d >  EX.DRIFT_MAX then d =  EX.DRIFT_MAX end
    if d < -EX.DRIFT_MAX then d = -EX.DRIFT_MAX end
    return d
end

function EX.world_appetite(res)
    if EX.is_layer2(res) then return 0 end   -- the Forge's output, not the world's appetite
    local shares = EX.culture_share
    if not shares then return 0 end          -- no scan has completed yet
    local culture = 0
    for c, share in pairs(shares) do
        local wants = EX.CULTURE_WANTS[c]
        -- THE GATE IS STILL THE BASE ENTRY. A culture missing from CULTURE_WANTS
        -- contributes exactly zero including its drift, so EX.warn_uncovered still means
        -- what it says: no entry is no demand, not a drifting default.
        if wants and wants[res] then
            culture = culture + (wants[res] + EX.drift(c, res)) * share
        end
    end
    -- THE WORLD WAR TERM AND THE PER-CULTURE ONE ARE ALTERNATIVES, NEVER BOTH. Drift
    -- carries war per culture when it is on, so leaving this here as well would count
    -- every war twice. Making the switch a true A/B is also the whole point of it: turn
    -- appetite_drift off and the shipped 2026-09-06 pricing is back, to the line.
    local war = 0
    if not EX.feature("appetite_drift") then
        local wa = EX.WAR_APPETITE[res]
        if wa then
            war = EX.WAR_WEIGHT * wa
                  * ((EX.war_index or EX.WAR_BASELINE) - EX.WAR_BASELINE)
        end
    end
    return EX.opt("ai_gain") * (culture + war)
end

-- Rungs, truncated TOWARD ZERO and clamped. Same trap as EX.pressure_shift: math.floor(-0.5)
-- is -1, so flooring a signed appetite would move a price DOWN on a demand too small to move
-- it up. Sub-rung appetite reads 0 rather than flickering the board every turn.
-- WH3's Lua numbers are single-precision, so an appetite landing exactly on a rung boundary
-- can fall either side of it. That is a one-rung jitter on an uncalibrated dial, not a fault.
function EX.appetite_shift(res)
    if EX.is_house(res) then return 0 end      -- CULTURE_WANTS holds goods, not factions
    local v = EX.world_appetite(res)
    local q = math.floor(math.abs(v))
    if q > EX.opt("ai_max_rungs") then q = EX.opt("ai_max_rungs") end
    if q == 0 then return 0 end
    if v < 0 then return -q end
    return q
end

-- The footer's one line. The per-row signal is the trend arrow, which now moves for world
-- reasons as well as the player's; this names WHY.
-- ponytail: footer-level reason, not per-row. A per-row column means rewriting both mode
-- layout tables plus the alignment selftest in tools/gen_exchange_ui.py - do it if the
-- aggregate line proves too coarse to act on.
function EX.appetite_summary()
    local moved = {}
    for _, res in ipairs(EX.COMMODITIES) do
        if EX.appetite_shift(res) ~= 0 then
            moved[#moved + 1] = { res, EX.world_appetite(res) }
        end
    end
    table.sort(moved, function(a, b) return math.abs(a[2]) > math.abs(b[2]) end)
    local up, down = {}, {}
    for _, e in ipairs(moved) do
        local t = e[2] > 0 and up or down
        -- TWO, NOT THREE. The footer line is ONE component of 880px and the engine does not
        -- wrap, so the clause list is what makes the line unbounded. Three of the longest
        -- display names in each clause overruns the box and fit() then amputates mid-list,
        -- which shipped as "Shaken: Medicinal Plants (raided), ..." with a dangling comma.
        -- check_footer_bounds() measures the real worst case; do not raise this without it.
        if #t < 2 then t[#t + 1] = EX.display(e[1]) end
    end
    -- "World at war", not "The world at war" - four characters, and the worst-case line is
    -- within six of the budget. See check_footer_bounds().
    local s = string.format("World at war: %d%%.",
                            math.floor((EX.war_index or 0) * 100 + 0.5))
    if #up > 0 then s = s .. "  Wanted: " .. table.concat(up, ", ") .. "." end
    if #down > 0 then s = s .. "  Unwanted: " .. table.concat(down, ", ") .. "." end
    return s
end

-- THE HOUSES VIEW'S OWN LINE. It used to fall through to a static "Absorb a house yourself..."
-- explanation with no live signal at all - the one view with no per-commodity row to hang a
-- Buy/Sell tooltip on had nowhere to say "the guild is hostile" or "the market is shut". Two
-- clauses, same shape as EX.appetite_summary above: a base clause plus ONE list capped at 2
-- names - see check_footer_bounds().
function EX.guild_summary()
    local g = EX.guild()
    if #g == 0 then return "No other house trades here." end
    local hostile = {}
    for _, h in ipairs(g) do
        if EX.stance_of(h) < 0 and #hostile < 2 then
            hostile[#hostile + 1] = EX.faction_display(h)
        end
    end
    local s = "Guild: " .. #g .. " houses trading."
    if #hostile > 0 then
        s = s .. "  Hostile: " .. table.concat(hostile, ", ") .. "."
    end
    -- THE "N MORE NOT SHOWN" CLAUSE IS GONE. It existed because the view TRUNCATED; the view
    -- PAGES since 2026-09-08, the counter beside the arrows says which page of how many, and
    -- a footer giving a second, different answer to the same question is worse than either
    -- answer on its own.
    -- THE BANNER REPLACES THE LINE, and it is EX.closed_banner's job now rather than this
    -- function's: the Trade footer draws the same sentence, and one closure must not read two
    -- different ways depending on which view the player happens to be on.
    return EX.closed_banner() or s
end

-- ===========================================================================================
-- SHOCKS. Violence disrupts supply, and the market prices the news before it prices the
-- fundamentals.
--
-- THE SPLIT WITH THE SCAN IS THE WHOLE DESIGN. The scan already prices the STATE - who owns
-- what, what is built, what is besieged - and it does so smoothly, one turn behind. A shock is
-- the SPIKE on top of that, and it decays back to whatever the scan says the fundamentals are.
-- So a raze gets both: a panic now, and a permanently smaller world supply from next turn.
-- A raid gets only the spike, because a raid destroys nothing - which is exactly right.
--
-- Priced as a SHARE OF WORLD SUPPLY, not as a flat number of rungs. Razing one of sixty timber
-- regions should do nothing and razing one of six obsidian regions should hurt; a flat shock
-- cannot tell those apart, and it is the difference between a market worth cornering and a
-- number that twitches.
EX.SHOCK_GAIN  = 10     -- rungs per 1.0 of "share of world supply disrupted", before the kind
EX.SHOCK_MAX   = 6      -- rungs either side. Six is 1.77x - a spike, not a new price level.
EX.SHOCK_DECAY = 0.5    -- multiplied each turn: half gone next turn, gone in about three
EX.SHOCK_MIN   = 0.05   -- below this it is dropped, rather than carried as dust forever
EX.SAVE_SHOCK  = "zharr_shock_"
EX.SAVE_SHOCK_WHY = "zharr_shockwhy_"
EX.SAVE_SHOCKED   = "zharr_shocked"     -- the per-turn duplicate guard, ";"-joined

-- ALL FOUR ARE UNCALIBRATED. Every one is a first guess, and the clamp is what makes that
-- survivable: the worst a bad SHOCK_GAIN can do is peg a commodity at six rungs for a turn.
-- The one to watch is raze, which is the only kind that also permanently moves the scan.
--
-- A RAZE REALLY WEIGHS 4.0, NOT 3.0. Measured over six soaked turns 2026-09-06: CA fires
-- CharacterLootedSettlement and CharacterRazedSettlement for the SAME settlement in the same
-- tick, 4 times out of 4, so a raze always lands on top of a loot. A SACK does not - three
-- sacks in the same run each stood alone. The effective ladder is therefore 1 / 2 / 4, which
-- is a defensible shape (a razed settlement genuinely was looted first) but it is not what
-- this table appears to say, and editing `razed` moves the total by less than it looks.
-- Suppressing the loot would need cross-event state, because nothing at loot time knows a
-- raze is coming - not worth it for a compound that is arguably correct.
EX.SHOCK_KINDS = {
    razed    = 3.0,
    sacked   = 2.0,
    rebels   = 1.5,   -- a province in revolt ships nothing while it is fighting itself
    looted   = 1.0,
    raided   = 1.0,
    captured = 0.5,   -- changes hands: disrupted for a season, not destroyed
}

-- GarrisonOccupiedEvent IS DELIBERATELY NOT HERE. It appears in CA's event index with no
-- documented context accessor, so what it carries is a guess - and a listener reading a
-- method the context does not have fails inside a pcall and shocks nothing, forever,
-- silently. It also almost certainly overlaps CharacterCapturedSettlement, which would
-- double-count one capture through two kinds, since the per-turn guard is keyed by kind.
-- Add it only with the context read off a running game, the way the TEB culture key was.

-- The three stances that stop goods leaving a region. LAND_RAID and SEA_RAID are the army and
-- fleet raiding stances; SET_CAMP_RAIDING is a settled army camped and raiding at once.
-- BLOCKADE is deliberately absent: it is a SITUATIONAL stance, so it is not adopted through
-- ForceAdoptsStance and would never fire.
EX.RAID_STANCES = {
    MILITARY_FORCE_ACTIVE_STANCE_TYPE_LAND_RAID       = true,
    MILITARY_FORCE_ACTIVE_STANCE_TYPE_SEA_RAID        = true,
    MILITARY_FORCE_ACTIVE_STANCE_TYPE_SET_CAMP_RAIDING = true,
}

EX.shock     = {}   -- res -> rungs, a FLOAT. Truncated only where it meets the price.
EX.shock_why = {}   -- res -> the kind that last moved it, for the footer
EX.shocked   = {}   -- "<region>|<kind>" already applied this turn; cleared at FactionTurnStart

-- PERSISTED, because a guard that a reload empties is a guard with a hole in it: the whole
-- point is that a region's share of world supply is disrupted once, and a mid-turn save and
-- load would let the next event through to count it a second time.
--
-- One delimited string, which is EX.remember's idiom for EX.history and for the same reason -
-- cm:set_saved_value stores scalars, and a key per region would be an unbounded number of
-- them. Region keys are lowercase engine strings, so ";" cannot appear inside one.
function EX.save_shocked()
    local keys = {}
    for k in pairs(EX.shocked) do keys[#keys + 1] = k end
    EX.setv(EX.SAVE_SHOCKED, table.concat(keys, ";"))
end

-- Held as a float on purpose. Six raids each worth 0.2 of a rung are a real corner and would
-- each round to nothing if the truncation happened here instead of at the price.
-- DEMAND SHOCKS, TAKEN FROM THE SCAN RATHER THAN FROM AN EVENT.
--
-- There is no FactionDestroyed to listen for - CA ships none, checked against the event
-- index in Modding Files/reference/ca_script_docs_wh3 - and EX.check_delistings only ever
-- looks at the houses, which are one culture's factions and not the world's. But EX.rescan
-- already measures every culture's share of the world's regions every turn, so a share
-- COLLAPSING is the event. One mechanism then catches every cause of it - destroyed,
-- conquered, confederated, or simply ground down - with no listener firing for every
-- faction in the world and no event name to get silently wrong.
--
-- THE SIGN IS THE WHOLE POINT. Every kind in EX.SHOCK_KINDS is positive: supply comes off
-- the market and the price goes up. Before this the board could spike and never crater,
-- which made a protective sell-stop an order against a thing that could not happen. A
-- culture that WANTED a good disappearing is demand leaving and the price falls; one that
-- SUPPLIED it (a negative want) disappearing is supply leaving and the price rises. The
-- product delta * want gives both from one line, and a culture GROWING gives both mirrored.
--
-- A CULTURE WITH NO PREVIOUS ENTRY IS SKIPPED, not read as growing from zero - otherwise
-- the first scan of a campaign sees every culture on the map as having just appeared and
-- shocks all seventeen commodities at once, on turn one, in every game.
--
-- CALLED FROM THE TURN ROUND ONLY, never from EX.rescan. rescan also runs at first tick
-- and after a load, and a shock minted there is the same unbounded printer reachable by
-- pressing F9 that EX.check_delistings already had to be guarded against.
EX.SHARE_SHOCK_MIN = 0.01   -- one per cent of the world's regions, as EX.warn_uncovered

-- FALSE UNTIL A FULL TURN HAS BEEN OBSERVED. View state, never saved: it must be false
-- again after every load, which is the whole point of it.
EX.cshare_ready = false

function EX.share_shocks()
    if not EX.feature("demand_shocks") then return end
    -- THE FIRST COMPARISON OF A SESSION IS NOT A TURN'S WORTH OF CHANGE, so it must not
    -- shock. EX.init runs its own EX.rescan, and the first turn round therefore compares
    -- an INIT-TIME scan against a turn-time one. On a new campaign that window contains
    -- the whole of the scripted start - a Ghorth run confederates three houses into the
    -- Conclave inside it - and on a load it is however long the player sat there, which
    -- is not a turn either. Measured 2026-09-09 in play: the first round announced
    -- "wh_main_emp_empire lost 2.1% of the world", which is a quarter of the Empire in one
    -- turn and is really setup being priced as news.
    --
    -- Costs one turn of real demand shocks after every load. That is the safe direction:
    -- a missed shock is invisible, an invented one moves the player's money.
    if not EX.cshare_ready then
        EX.cshare_ready = true
        EX.say("shock", "first share comparison since load - no demand shocks this turn")
        return
    end
    local prev, now = EX.culture_share_prev, EX.culture_share
    if not prev or not now then return end
    local gain = EX.opt("shock_gain")
    for c, wants in pairs(EX.CULTURE_WANTS) do
        local was = prev[c]
        if was then
            local delta = (now[c] or 0) - was
            if delta >= EX.SHARE_SHOCK_MIN or delta <= -EX.SHARE_SHOCK_MIN then
                -- The same per-turn guard the region shocks use. This is called once a
                -- turn so it is insurance rather than a fix - but counting one event
                -- twice is exactly what the raid listener was caught doing.
                local seen = "cshare|" .. c
                if not EX.shocked[seen] then
                    EX.shocked[seen] = true
                    EX.save_shocked()
                    local moved = 0
                    for res, want in pairs(wants) do
                        if want ~= 0 then
                            EX.bump_shock(res, gain * delta * want,
                                          delta < 0 and "collapse" or "surge")
                            moved = moved + 1
                        end
                    end
                    EX.say("shock", string.format(
                        "%s %s %.1f%% of the world, shocking %d commodities",
                        c, delta < 0 and "lost" or "gained",
                        (delta < 0 and -delta or delta) * 100, moved))
                end
            end
        end
    end
end

function EX.bump_shock(res, rungs, why)
    if rungs == 0 then return end
    local v = (EX.shock[res] or 0) + rungs
    if v > EX.opt("shock_max") then v = EX.opt("shock_max") end
    if v < -EX.opt("shock_max") then v = -EX.opt("shock_max") end
    EX.shock[res] = v
    EX.shock_why[res] = why
    EX.setv(EX.SAVE_SHOCK .. res, v)
    EX.setv(EX.SAVE_SHOCK_WHY .. res, why or "")
end

-- kind is a key of EX.SHOCK_KINDS, and is also the word the footer prints.
--
-- ponytail: the price does not move until the next turn starts. A shock landing mid-AI-turn
-- is the common case and the player is not looking; repricing here would run apply_prices
-- once per razed settlement on the whole map. Call EX.apply_prices() from here if a shock
-- during the PLAYER'S own turn ever needs to show immediately.
function EX.add_shock(region, kind)
    local mult = EX.SHOCK_KINDS[kind]
    if not mult then return end
    if not EX.supply then return end     -- no scan has completed; there is no share to take
    -- THE LAST SCAN FIRST, the live region second. A razed settlement answers with nothing -
    -- the buildings are gone by the time the event fires - so reading it live would give the
    -- largest shock in the table a supply loss of zero.
    -- ONE SHOCK PER REGION PER KIND PER TURN. ForceAdoptsStance fires once per army, so two
    -- armies raiding one region on one tick disrupt the SAME goods twice - and the 2026-09-06
    -- soak logged ten raids 2-3 times over at an identical timestamp and region, about 7% of
    -- 150. Whether that was two armies or the listener firing twice cannot be told from the
    -- log and does not need to be: the share of world supply this region contributes is
    -- disrupted once either way, and a share counted twice is simply wrong.
    --
    -- KEYED BY KIND, not by region alone. CA fires CharacterLootedSettlement and
    -- CharacterRazedSettlement for the same settlement in the same tick 4 times out of 4, and
    -- that 1+3 compound is deliberate (see EX.SHOCK_KINDS) - a region-only key would eat it.
    --
    -- AFTER the EX.supply guard, so a shock that applied nothing does not claim the slot.
    local seen = region:name() .. "|" .. kind
    if EX.shocked[seen] then
        EX.say("shock", kind .. " at " .. region:name() .. " already counted "
            .. "this turn, ignored")
        return
    end
    EX.shocked[seen] = true
    EX.save_shocked()
    local goods = EX.region_last[region:name()]
    if not goods then goods = EX.region_goods(region) end
    local moved = 0
    for i = 1, #goods do
        local res, amount = goods[i][1], goods[i][2]
        local total = EX.supply[res] or 0
        if total > 0 then
            EX.bump_shock(res, mult * (amount / total) * EX.opt("shock_gain"), kind)
            moved = moved + 1
        end
    end
    if moved > 0 then
        EX.say("shock", kind .. " at " .. region:name() .. " shocked "
            .. moved .. " commodities")
    end
end

-- Every shock handler funnels through here so one bad context cannot kill a listener. A
-- listener whose handler errors is dropped SILENTLY for the rest of the campaign, which would
-- turn "razes stopped moving the market" into an unfindable bug.
function EX.shock_from_garrison(context, kind)
    local ok, err = pcall(function()
        local gr = context:garrison_residence()
        if not gr or gr:is_null_interface() then return end
        local region = gr:region()
        if not region or region:is_null_interface() then return end
        EX.add_shock(region, kind)
    end)
    if not ok then
        EX.say("error", kind .. " shock failed: " .. tostring(err))
    end
end

-- Rungs, truncated TOWARD ZERO. Same trap as EX.pressure_shift and EX.appetite_shift:
-- math.floor(-0.5) is -1, so flooring a signed shock would move a price DOWN on a disruption
-- too small to move it up.
function EX.shock_shift(res)
    if EX.is_house(res) then return 0 end      -- a raze already moves the region count
    local v = EX.shock[res] or 0
    local q = math.floor(math.abs(v))
    if q > EX.opt("shock_max") then q = EX.opt("shock_max") end
    if q == 0 then return 0 end
    if v < 0 then return -q end
    return q
end

-- Multiplicative, so it can never cross zero and flip the sign of a shock on the way down.
-- Runs AFTER apply_prices in the turn handler: a settlement razed during the AI round must be
-- priced at full strength on the turn the player first sees it, and halved from the next one.
function EX.decay_shocks()
    for _, res in ipairs(EX.instruments()) do
        local v = EX.shock[res]
        if v and v ~= 0 then
            v = v * EX.opt("shock_decay")
            if math.abs(v) < EX.SHOCK_MIN then v = 0 end
            EX.shock[res] = v
            EX.setv(EX.SAVE_SHOCK .. res, v)
            if v == 0 then
                EX.shock_why[res] = nil
                EX.setv(EX.SAVE_SHOCK_WHY .. res, "")
            end
        end
    end
end

-- Named in the footer beside the appetite line. The kind is printed rather than the region,
-- because a region key is not a region NAME and looking one up would mean a second loc cache
-- for a word the player can find on the map themselves.
function EX.shock_summary()
    local hit = {}
    for _, res in ipairs(EX.COMMODITIES) do
        if EX.shock_shift(res) ~= 0 then
            hit[#hit + 1] = { res, math.abs(EX.shock[res] or 0) }
        end
    end
    if #hit == 0 then return nil end
    table.sort(hit, function(a, b) return a[2] > b[2] end)
    local names = {}
    -- Two, for the same reason as EX.appetite_summary's clauses.
    for i = 1, math.min(2, #hit) do
        local res = hit[i][1]
        names[#names + 1] = EX.display(res) .. " (" .. (EX.shock_why[res] or "disrupted") .. ")"
    end
    return "Shaken: " .. table.concat(names, ", ") .. "."
end

-- THE FOOTER IS NOT ENOUGH, because it is only read by a player who already opened the panel.
-- A war on the other side of the world moves a price here, and until this the only trace of it
-- outside the panel was a line in script_log.
--
-- ONE MESSAGE A TURN AT MOST, and only for a shock that actually moved a price. The gate is
-- two tests and they are not the same test:
--
--   EX.shocked non-empty   NEW EVENTS LANDED SINCE THE LAST TURN START. A shock decays over
--                          about three turns, so without this the same razed settlement would
--                          be announced three times - news the first turn, noise after.
--   EX.shock_shift ~= 0    THE PRICE ACTUALLY MOVED. A shock under one rung is truncated away
--                          at the price, so announcing it would name a commodity as shaken
--                          while its number sits exactly where it was.
--
-- THERE IS NO THIRD, SIZE-BASED TEST, and there was one until the break test killed it. A
-- EX.SHOCK_NEWS_MIN constant at 1 rung sat on top of the shift test and could not be made to
-- fail: the shift test already answers "did the price move", exactly, with nothing to
-- calibrate. The measured rate it was invented against is 320 shock events across ~30 turns
-- in the 2026-09-06 soak, the vast majority a fraction of a rung on a common good and
-- correctly silent.
--
-- ponytail: if the feed still turns out noisy in play, the bar goes up in place -
-- `EX.shock_shift(res) >= 2` is a 21% move - rather than by reintroducing a second gate.
--
-- Called BEFORE EX.decay_shocks and BEFORE the guard is cleared, which is the only window
-- where both halves of the gate are still true.
function EX.announce_shocks()
    if not next(EX.shocked) then return end
    local fname = EX.who()
    if not fname then return end
    local best, size = nil, 0
    for _, res in ipairs(EX.COMMODITIES) do
        local v = math.abs(EX.shock[res] or 0)
        if EX.shock_shift(res) ~= 0 and v > size then best, size = res, v end
    end
    if not best then return end
    -- One message per commodity, because the goods have to be named and the text is a static
    -- loc string - the same reason the demand messages are per (tier, commodity). The KIND is
    -- deliberately not in the key: it would multiply 17 messages by four for a word the
    -- panel's own footer already prints beside the commodity.
    local m = EX.PREFIX .. "shock_" .. EX.short(best)
    -- false, not true: EX.FEED_SHOCK is a scripted_transient_event record and the flag has to
    -- agree with the record or nothing draws.
    cm:show_message_event(fname, m .. "_title", m .. "_primary", m .. "_secondary",
                          false, EX.feed("shock"))
    -- AND IN THE LOG. The bulletin is an event-feed message, which the player dismisses and
    -- cannot get back; the shock it announced is still moving their prices several turns later.
    -- SUBJECT DEFERRED: "" plus the commodity key gives the row the good's name AND its icon,
    -- and costs nothing here - EX.display is plain Lua, but deferring is the shape every
    -- turn-time entry uses and one exception is how the next one gets written unsafely.
    local shift = EX.shock_shift(best)
    EX.log_add("", "Demand shock: prices " .. (shift > 0 and "+" or "") .. shift
        .. " step(s) (" .. (EX.shock_why[best] or "disrupted") .. ").", best)
    EX.say("shock", "news - " .. best .. " shaken "
        .. string.format("%.2f", size) .. " steps (" .. (EX.shock_why[best] or "disrupted")
        .. ")")
end

-- Power for a house key, from the scan's table with a live read as the fallback for the
-- turn a house is discovered on.
function EX.house_power_of(res)
    local n = (EX.house_regions or {})[res]
    if n and n > 0 then return n end
    local f = cm:get_faction(res)
    if f and f ~= false and not f:is_null_interface() then return EX.house_power(f) end
    return 0
end

-- THE DEAD ARE NOT SAMPLES. A delisted house owns nothing, so its power reads 0 and leaving
-- it in here drags the median down - and the dead only ever accumulate, so over a campaign
-- every LIVING house's multiplier inflates. That is a slow upward drift across the whole
-- board with no cause the player can see anywhere on screen.
--
-- Skipping them all leaves an empty list, which falls back to 1 exactly as an unscanned board
-- does: no house is then priced against another, which is the honest answer when none is left.
function EX.house_median()
    local t = {}
    for _, h in ipairs(EX.houses) do
        if not EX.is_delisted(h) then t[#t + 1] = EX.house_power_of(h) end
    end
    if #t == 0 then return 1 end
    return EX.median(t)
end

-- `hmed` IS EX.house_median(), HOISTED BY EX.apply_prices. Computed here per house it walked
-- every house again for each house - 11,130 power reads and 11,235 cm:get_faction calls per
-- reprice at the 105 houses of a live 2026-09-23 save, and a reprice runs 0.1s after every
-- trade: the ~1.2s hang on each Buy click. Optional so a lone caller still gets the live read.
function EX.target_rung(res, supply, owners, med, hmed)
    local base
    if EX.is_house(res) then
        -- A DELISTED ROW FREEZES at the price it settled against. A dead house owns nothing,
        -- so a live reprice reads its power as 0, EX.house_multiplier clamps to EX.MULT_MIN
        -- and the row drops to rung 1 in ONE step - not a slide over several turns. The
        -- freeze is why the settlement is worth what the house was, and why the sparkline
        -- reads as a book that closed rather than a collapse still under way. THE TURN
        -- HANDLER CALLS EX.check_delistings BEFORE EX.apply_prices for the same reason; this
        -- alone would not save the payout, because the first reprice after the death runs
        -- while EX.is_delisted is still false.
        if EX.is_delisted(res) then return EX.current[res] or EX.neutral_rung() end
        -- The median is over HOUSES ONLY. Houses and commodities are priced on different
        -- quantities - territory held against regions producing - and share only the ladder.
        local mult = EX.house_multiplier(EX.house_power_of(res), hmed or EX.house_median())
        local f = cm:get_faction(res)
        local seat = EX.holds_capital(f)
        if seat == false then mult = mult * EX.opt("seat_lost") end   -- nil (horde) is exempt
        -- REMEMBER WHERE ITS CAPITAL IS, while there is still a faction to ask. This runs
        -- every turn for every live house and is the only reader of home_region() that is
        -- guaranteed to happen before the house dies.
        --
        -- THE KEY, NEVER THE BOOLEAN. Caching "do we own its capital" as evaluated here is
        -- wrong in the exact case that matters, because taking the capital IS the killing
        -- blow: the last observation made while the house was alive always says we did not
        -- own it. Only resolving the key at settlement gives the right answer.
        EX.remember_home(res, f)
        base = EX.ladder_index(mult)
    elseif EX.is_layer2(res) then
        base = EX.neutral_rung()          -- no map supply signal; flat for now
    else
        local eff = EX.effective_supply(supply[res] or 0,
                                        EX.hhi((owners or {})[res] or {}))
        base = EX.ladder_index(EX.price_multiplier(eff, med))
    end
    local shift = EX.pressure_shift(EX.pressure[res] or 0)
    local rung = base + shift + EX.appetite_shift(res) + EX.shock_shift(res)
                      + EX.book_shift(res) + EX.world_book_shift(res)
    if rung < 1 then return 1 end
    if rung > EX.RUNGS then return EX.RUNGS end
    return rung
end

-- ONE BAR PER TURN, and the turn boundary is the only honest place to add one.
--
-- This used to live inside EX.apply_prices, which also runs 0.1s after every single buy and
-- sell - so every purchase pushed a bar into ALL NINETEEN sparklines and shifted the oldest
-- off. A column headed "Last 12 turns" was really showing the last 12 REPRICES, and five
-- trades in one turn silently threw away five turns of history for every commodity on the
-- board, including the ones the player never touched.
--
-- Reported from play 2026-09-06 ("everytime i buy, the last 12 turns moves"). It is the exact
-- bug EX.snapshot_trend was moved out of apply_prices to fix, in the same function, and the
-- check that pinned that one down was never written for this one. See check_trend_snapshot.
function EX.remember_all()
    for _, res in ipairs(EX.instruments()) do
        -- EX.current is what apply_prices just settled on - it is assigned only when the rung
        -- CHANGED, so reading it back is right either way. A scan that failed leaves last
        -- turn's rung there, and repeating a bar is the honest record of a price that held.
        EX.remember(res, EX.current[res] or EX.neutral_rung())
    end
end

function EX.apply_prices()
    local faction = EX.me()
    if not faction then return end

    if not EX.supply then EX.rescan() end
    local supply, owners = EX.supply, EX.owners or {}
    if not supply then return end          -- the scan has never once completed; nothing to do

    -- The median is taken over EFFECTIVE supplies, not raw counts. Effective supply is always
    -- at or below raw, so a median of raw counts would push every price up by roughly the
    -- average concentration and quietly inflate the whole board. Against the effective median,
    -- concentration is purely RELATIVE - the typical commodity still prices at 1000, and only
    -- being more cartelised than the rest of the map makes a thing dear.
    local counts, raws = {}, {}
    for _, res in ipairs(EX.COMMODITIES) do
        counts[#counts + 1] = EX.effective_supply(supply[res] or 0,
                                                  EX.hhi(owners[res] or {}))
        raws[#raws + 1] = supply[res] or 0
    end
    local med = EX.median(counts)
    EX.med = med
    -- The median of RAW counts, kept only for EX.premium's counterfactual. Pricing never uses
    -- it. See EX.premium for why comparing across the two medians is the whole point.
    EX.med_raw = EX.median(raws)

    -- THE RUNG IS THE WHOLE STATE. This used to apply a derpy_chd_ex_ladder_* effect bundle to
    -- the faction on every move and remove the previous one. That bundle carried a
    -- percentage_cost_mod whose only consumer was the ritual it was junctioned to, and no
    -- ritual has been performed since 2026-09-04 - EX.price_at() computes what the player pays.
    -- So 798 bundle rows and two engine calls per reprice were maintaining a number nothing
    -- read. See EX.strip_legacy_bundles for the saves that still have one applied.
    local moved = 0
    local hmed = EX.house_median()      -- once per reprice; see EX.target_rung
    for _, res in ipairs(EX.instruments()) do
        local rung = EX.target_rung(res, supply, owners, med, hmed)
        if EX.current[res] ~= rung then
            EX.current[res] = rung
            EX.setv(EX.SAVE_PREFIX .. res, rung)
            moved = moved + 1
        end
    end

    -- The CampaignTreasuryChanged nudge went with them. It existed to refresh CA's rites-panel
    -- cost widget, which no longer has any of our cards on it - and cm:treasury_mod(faction, 1)
    -- is a literal gold coin, so it was also paying the player once per reprice.
    EX.say("price", "repriced " .. moved .. " of " .. #EX.instruments()
        .. ", median supply " .. med)
end

-- Pressure bleeds TOWARD ZERO, from either side. It used to be guarded `if p > 0`, so a sale
-- depressed a commodity for the rest of the campaign while a purchase inflated it for four
-- turns - a market that only ever remembered being sold into. Nothing about the design wanted
-- that; the guard was just written before selling existed.
-- ===========================================================================================
-- OPTION B: the exchange price drives vanilla trade income.
-- ===========================================================================================

-- In memory only. After a load nothing knows which bundle a save carries, which is what
-- EX.trade_swept is for - see EX.apply_trade_income.
EX.trade_level = {}
EX.trade_swept = false

function EX.trade_bundle_key(step)
    return string.format("%strade_%s%02d", EX.PREFIX, step < 0 and "neg" or "pos",
                         math.abs(step))
end

-- How far this faction's commodities sit from the neutral price, weighted by how many regions
-- it holds of each. A faction with ten cheap iron regions and one dear gem region is an iron
-- economy, and the number says so.
function EX.trade_income_level(fname)
    local regions, sum = 0, 0
    for _, res in ipairs(EX.COMMODITIES) do
        local n = ((EX.owners or {})[res] or {})[fname]
        if n and n > 0 then
            regions = regions + n
            sum = sum + n * (EX.price(res) / EX.BASE_COST - 1)
        end
    end
    if regions == 0 then return 0 end
    return sum / regions
end

-- Snap to the LARGEST step the deviation has actually reached, in whichever direction. Taking
-- the first match instead would return -10 for a -25% faction, because the steps are listed
-- most-negative first and every negative step below -25 also matches.
function EX.trade_bundle_for(level)
    local pct = level * EX.TRADE_GAIN
    local best = nil
    for _, step in ipairs(EX.TRADE_STEPS) do
        if (step > 0 and pct >= step) or (step < 0 and pct <= step) then
            if best == nil or math.abs(step) > math.abs(best) then best = step end
        end
    end
    return best
end

function EX.apply_trade_income()
    if not EX.setting("trade_income") then return end
    if not EX.owners then return end
    local seen = {}
    for _, res in ipairs(EX.COMMODITIES) do
        for fname, _ in pairs((EX.owners or {})[res] or {}) do seen[fname] = true end
    end

    local function set(fname, want)
        -- REMOVE ALL EIGHT, not just the one we believe is applied. Two same-effect bundles
        -- stack additively, so one stale row from a previous load would silently double the
        -- modifier - the same trap the price ladder's restore logic was written to avoid.
        for _, step in ipairs(EX.TRADE_STEPS) do
            pcall(function() cm:remove_effect_bundle(EX.trade_bundle_key(step), fname) end)
        end
        if want then
            cm:apply_effect_bundle(EX.trade_bundle_key(want), fname, 0)
        end
        EX.trade_level[fname] = want
    end

    local changed = 0
    for fname, _ in pairs(seen) do
        local want = EX.trade_bundle_for(EX.trade_income_level(fname))
        -- The sweep is forced once per load. Comparing against an empty EX.trade_level would
        -- skip every faction whose new answer is "no bundle", leaving whatever the save carries
        -- applied forever - nil == nil reads as "already correct".
        if not EX.trade_swept or EX.trade_level[fname] ~= want then
            set(fname, want)
            changed = changed + 1
        end
    end

    -- A faction that lost its last producing region keeps its bundle otherwise.
    for fname, cur in pairs(EX.trade_level) do
        if cur ~= nil and not seen[fname] then
            set(fname, nil)
            changed = changed + 1
        end
    end

    EX.trade_swept = true
    if changed > 0 then
        EX.say("price", "trade income updated for " .. changed .. " factions")
    end
end

-- ===========================================================================================
-- POSITION BUNDLES (Stage 3). The third bundle family, and a sibling of the one above.
--
-- EX.apply_trade_income is keyed on the price deviation of a faction's LAND and
-- EX.apply_stockpiles on the PLAYER's holdings. This one is keyed on an actor's POSITION on
-- the exchange, crossed with whether it is at war: a faction holding war materiel while
-- fighting replenishes better, one that sold its war goods into a shortage pays for it.
-- Widening either of the other two would have re-tuned a calibrated, shipped, player-visible
-- number; a third family adds one.
-- ===========================================================================================

-- NET, NOT GROSS, AND WAR GOODS ONLY.
--
-- The world book is a POSITION and it may be negative - EX.set_world_book replaced its floor
-- at 0 on 2026-09-13 because a producer selling this turn's output IS short until it digs it
-- up - so a negative here is a real obligation and not a missing entry. Summing absolute
-- values would read a faction that is long iron and short timber as heavily armed when it is
-- neither, and it is the one mistake that leaves every one-sided fixture green.
--
-- No `or 0` on the accessor: EX.world_book_of already returns 0 for a faction with no book
-- and cannot return nil, so a fallback here would be a guard that no mutant can break - and
-- a check nobody can make fail is worse than one that is missing.
function EX.war_position(faction)
    local n = 0
    for res, _ in pairs(EX.WAR_GOODS) do
        n = n + EX.world_book_of(faction, res)
    end
    return n
end

-- WAR IS THE MULTIPLIER, NOT THE CONDITION.
--
-- A faction long on war goods is better supplied whether or not it is fighting; being at war
-- is what makes the difference matter. So peace HALVES the tier rather than zeroing it. A
-- bundle that appeared and vanished on a declaration of war would flicker for every faction
-- on the map every time anyone declared anything - and the sweep writes a bundle change to
-- the engine, not to a table, so that flicker is real work on every client every turn.
--
-- A FACTION WITH NO ACTOR RECORD READS AS AT PEACE. EX.actors is rebuilt by every scan and
-- EX.wbook is restored from the save, so a faction can be in the book and out of the scan on
-- the same tick; at peace is the conservative answer (half a tier, never a bigger one).
function EX.pos_tier(faction)
    local steps = EX.war_position(faction) / EX.opt("pos_step")
    local info = (EX.actors or {})[faction]
    if not (info and info.war) then steps = steps / 2 end
    -- SNAP TO THE LARGEST STEP REACHED, in whichever direction - the same rule and the same
    -- reason as EX.trade_bundle_for. Taking the first match returns the SMALLEST tier for a
    -- faction that has earned the largest, because every step below the one it reached also
    -- matches.
    local want = 0
    for _, tier in ipairs(EX.POS_TIERS) do
        if tier > 0 and steps >= tier and tier > want then want = tier end
        if tier < 0 and steps <= tier and tier < want then want = tier end
    end
    return want
end

-- In memory only, and deliberately NOT saved. The effect bundle survives the save on its
-- own - the engine holds it - while this table does not, so after a load the game already
-- carries whatever the last session applied and this script knows nothing about it. That
-- asymmetry is the whole reason EX.pos_swept exists below.
EX.pos_level = {}
EX.pos_swept = false

-- EXACTLY ONE POSITION BUNDLE PER FACTION, EVER.
--
-- REMOVE ALL FOUR FIRST, not just the one this script believes is applied - the same shape
-- and the same reason as EX.apply_trade_income and EX.apply_stockpiles. Same-effect bundles
-- stack ADDITIVELY, so one stale row from a previous load silently doubles the modifier.
--
-- The duration is 0, matching the shipped trade-income family. CA's two docs disagree about
-- which value means "indefinitely" - campaign_manager.html says 0 and episodic_scripting.html
-- says -1 - and 0 is what the bundle family that has already shipped uses.
function EX.apply_positions()
    -- EX.setting, NOT EX.opt. EX.opt returns nil for a key that is in neither TUNE_NUM nor
    -- TUNE_BOOL, and nil is falsy: a gate written with it deletes the feature the day the
    -- key is renamed or dropped from a preset, silently, with the switch still on screen.
    -- EX.setting fails open. This is the Stage 2 Task 7 finding applied.
    --
    -- AND OFF DOES NOT RETURN EARLY. Off means every faction's answer is 0, which the sweep
    -- below expresses by removing all four keys and applying none - so switching the feature
    -- off CLEANS UP after itself instead of stranding whatever was applied when it was last
    -- on. That is reachable rather than theoretical: a campaign started before this feature
    -- existed has no world_bundles entry in its frozen snapshot, so EX.opt falls through to
    -- the live MCT value and the switch is a real mid-campaign toggle for exactly those
    -- saves. Effect bundles survive every save; a stranded one would outlive the campaign.
    --
    -- The cost of off is therefore one pass of removes per load rather than nothing: after
    -- it, every memo entry reads 0 and the sweep goes quiet for the rest of the session.
    local on = EX.setting("world_bundles")
    if not EX.actors then return end

    local function set(fname, want)
        for _, tier in ipairs(EX.POS_TIERS) do
            pcall(function() cm:remove_effect_bundle(EX.pos_bundle_key(tier), fname) end)
        end
        if want ~= 0 then
            cm:apply_effect_bundle(EX.pos_bundle_key(want), fname, 0)
        end
        EX.pos_level[fname] = want
    end

    local changed = 0
    for fname, _ in pairs(EX.actors) do
        local want = on and EX.pos_tier(fname) or 0
        -- THE SWEEP IS FORCED ONCE PER LOAD. Comparing against an empty EX.pos_level would
        -- skip every faction whose new answer is "no bundle", leaving whatever the save
        -- carries applied forever - nil == nil reads as "already correct". This is the bug
        -- EX.trade_swept was added to fix, verbatim.
        if not EX.pos_swept or EX.pos_level[fname] ~= want then
            set(fname, want)
            changed = changed + 1
        end
    end

    -- A FACTION THAT DROPPED OUT OF THE SCAN KEEPS ITS BUNDLE OTHERWISE. EX.actors is rebuilt
    -- every scan and a faction leaves it by dying or by losing its last region - neither of
    -- which is a reason to stay armed. EX.apply_trade_income carries the same loop for the
    -- same reason; the plan for this task did not, which would have left a dead faction
    -- wearing a war-supply bundle for the rest of the campaign, across every save.
    -- Assigning to a key that already exists is defined during pairs; adding one is not, and
    -- every fname here is already a key of EX.pos_level.
    for fname, cur in pairs(EX.pos_level) do
        if cur ~= 0 and not EX.actors[fname] then
            set(fname, 0)
            changed = changed + 1
        end
    end

    EX.pos_swept = true
    if changed > 0 then
        EX.say("price", "positions updated for " .. changed .. " factions")
    end
end

-- ===========================================================================================
-- OFFERINGS TO HASHUT.
-- ===========================================================================================

-- res -> the turn the favour runs out. Persisted: the effect bundle survives a save on its own
-- (the engine holds the countdown), so without this a reload would forget an offering was
-- burning and let the player light a second one on top of it.
EX.offer_until = {}

-- SEGMENTED. Each race's offering bundle carries its own title and description - "Offering
-- to Hashut: Gemstones" against "Tithe to Sigmar: Gemstones" - so these are four sets of 17,
-- not one shared set. EX.seg() is "" for Chaos Dwarfs, so this returns exactly the key it has
-- always returned and a live save's applied offering is untouched.
function EX.offering_key(res)
    return EX.PREFIX .. EX.seg() .. "offering_" .. EX.short(res)
end

function EX.offer_turns_left(res)
    local until_turn = EX.offer_until[res]
    if not until_turn then return 0 end
    local left = until_turn - cm:turn_number()
    if left < 0 then return 0 end
    return left
end

-- Voluntary sacrifices made so far. Restored from the save; see EX.offer_cost.
EX.offerings_made = 0

-- WH3'S LUA NUMBERS ARE SINGLE-PRECISION FLOATS, which shows up here and nowhere else in this
-- file. EX.OFFER_STEP reads back in game as 1.0499999523163 - the float32 of 1.05 - so
-- 30 * 1.05 is 31.4999985 rather than 31.5, and the +0.5 rounding below falls the OTHER WAY:
-- offering #1 costs 31, not the 32 the same arithmetic gives in any double-precision Lua.
-- Measured in game, not reasoned about. It only bites where a product lands exactly on a .5
-- boundary, so rung 1 is the only step affected; the rest of the curve matches. Do not "fix"
-- this by rounding differently - the price the panel shows and the price charged both come
-- from this one function, so they agree whatever the float does.
function EX.offer_cost()
    local mult = EX.OFFER_STEP ^ EX.offerings_made
    if mult > EX.OFFER_MULT_MAX then mult = EX.OFFER_MULT_MAX end
    return math.floor(EX.OFFER_COST * mult + 0.5)
end

function EX.can_offer(res)
    if EX.is_house(res) then return false end   -- you cannot burn equity on an altar
    if EX.is_layer2(res) then return false end
    if EX.offer_turns_left(res) > 0 then return false end
    return EX.held(res) >= EX.offer_cost()
end

-- Burn the goods, take the favour. THE DURATION IS THE ENGINE'S:
-- cm:apply_effect_bundle(key, faction, turns) expires it by itself, so nothing here has to
-- remember to remove anything - EX.offer_until exists only to gate a second offering and to
-- draw the countdown.
-- THE CLICK, same shape as EX.trade above: send, and let the op run on every machine.
function EX.offer(res)
    EX.mp_send("offer", res)
end

EX.MP_OPS.offer = function(res) EX.apply_offer(res) end

function EX.apply_offer(res)
    local faction = EX.who()
    if not faction then return end
    -- A PENDING DEMAND TAKES PRECEDENCE on its own commodity. The same button, a different
    -- price: Hashut named the amount, so the ordinary OFFER_COST does not apply and neither
    -- does the offering cooldown. This is the whole payment route now that there is no
    -- dilemma to click.
    if EX.demand_pending() and EX.demand_res == res then
        EX.pay_demand()
        return
    end
    if not EX.can_offer(res) then
        EX.say("trade", "cannot offer " .. res
            .. " (held " .. EX.held(res) .. ", " .. EX.offer_turns_left(res) .. " turns left)")
        return
    end
    -- Read the price ONCE and spend that number. Recomputing it after the counter moves would
    -- charge one price and log another.
    local cost = EX.offer_cost()
    cm:faction_add_pooled_resource(faction, EX.hold_key(res), "other", -cost)
    cm:apply_effect_bundle(EX.offering_key(res), faction, EX.OFFER_TURNS)
    EX.offerings_made = EX.offerings_made + 1
    EX.setp(EX.SAVE_OFFERINGS, EX.offerings_made)
    local until_turn = cm:turn_number() + EX.OFFER_TURNS
    EX.offer_until[res] = until_turn
    EX.setp(EX.SAVE_OFFER .. res, until_turn)
    EX.say("trade", "offered " .. cost .. " " .. EX.hold_key(res)
        .. " to " .. EX.patron() .. " for " .. EX.OFFER_TURNS .. " turns (offering #"
        .. EX.offerings_made .. ", next costs " .. EX.offer_cost() .. ")")
    EX.log_add(EX.log_subject(res), "Offered " .. cost .. " to " .. EX.patron() .. ". Favour for "
        .. EX.OFFER_TURNS .. " turns; the next offering takes " .. EX.offer_cost() .. ".", res)
    -- THE NAME CARRIES THE FACTION, and so does the argument. Two players offering in the
    -- same tenth of a second would otherwise queue one cm:callback name twice, and the tier
    -- update for one of them would be the one that goes missing.
    cm:callback(function() EX.after_holding_change(faction) end, 0.1,
                "zharr_after_offer_" .. tostring(faction))
end

-- ===========================================================================================
-- HASHUT'S DEMANDS.
-- ===========================================================================================
--
-- The offerings view is the player choosing to spend. This is Hashut choosing for them, and it
-- is what stops a vault being a safe place to sit: the priests count the stores and name the
-- biggest pile. Refusing is always allowed and always costs.
--
-- THE DILEMMA IS ONE ROW PER (COMMODITY, TIER), 51 of them, because the amount and the boon
-- have to appear in the dilemma's text and that text is a static loc string.

EX.demand_turn = 0   -- last turn a demand was issued; restored from the save
EX.demand_res  = nil -- commodity Hashut is currently asking for, or nil
EX.demand_tier = nil -- its tier suffix
EX.demand_due  = 0   -- the turn the wrath lands if it is still unpaid

-- EX.demand_key IS GONE. It built a "demand_" prefix that no loc key has used since
-- the dilemmas were removed on 2026-09-05, and nothing called it - EX.fire_demand builds
-- the real message key inline, through EX.seg().

-- Cumulative threshold against cm:random_number(100), which is the MP-safe RNG and returns
-- 1..100 inclusive. The weights sum to 100 (asserted generator-side), so the final tier is the
-- fallthrough and no roll can escape the loop.
function EX.pick_demand_tier()
    local roll = cm:random_number(100)
    local at = 0
    for _, tier in ipairs(EX.DEMAND_TIERS) do
        at = at + tier[5]
        if roll <= at then return tier end
    end
    return EX.DEMAND_TIERS[#EX.DEMAND_TIERS]
end

-- Commodities the faction could actually pay this demand out of, biggest hoard first.
--
-- ONLY AFFORDABLE ONES, and that is the whole point rather than a convenience: a demand for
-- goods you do not have is a dilemma whose Submit button the engine greys out (the payload is
-- built with required=true), so the "choice" would be a single button reading "refuse".
function EX.demand_candidates(amount)
    local t = {}
    for _, res in ipairs(EX.COMMODITIES) do
        if not EX.is_house(res) then           -- Hashut takes goods, never paper
            local held = EX.held(res)
            if held >= amount then t[#t + 1] = { res, held } end
        end
    end
    table.sort(t, function(a, b) return a[2] > b[2] end)
    return t
end

function EX.tier_by_suffix(sfx)
    for _, t in ipairs(EX.DEMAND_TIERS) do
        if t[1] == sfx then return t end
    end
    return nil
end

function EX.demand_pending()
    return EX.demand_res ~= nil and EX.demand_tier ~= nil
end

-- cm:set_saved_value has no delete, so "" is the cleared state and every reader tests for it.
function EX.clear_demand()
    EX.demand_res, EX.demand_tier, EX.demand_due = nil, nil, 0
    EX.setp(EX.SAVE_DEM_RES, "")
    EX.setp(EX.SAVE_DEM_TIER, "")
    EX.setp(EX.SAVE_DEM_DUE, 0)
end

-- One demand. Returns the commodity asked for, or nil if nothing was eligible.
function EX.fire_demand()
    local fname = EX.who()
    if not fname then return nil end
    if EX.demand_pending() then return nil end   -- one at a time, always

    local tier = EX.pick_demand_tier()
    local sfx, amount = tier[1], tier[2]
    local pool = EX.demand_candidates(amount)
    if #pool == 0 then
        -- The tier is rolled BEFORE this filter, so a tier the player cannot pay is a wasted
        -- turn rather than a smaller demand. Deliberately does NOT set demand_turn: the
        -- cooldown should not burn on a demand that never happened.
        EX.say("demand", EX.patron() .. " wanted " .. amount .. " of something and found nothing "
            .. "worth taking")
        return nil
    end
    -- The top N hoards, so the altar reliably goes after what is being stockpiled without
    -- being perfectly predictable about which one.
    local n = #pool
    if n > EX.DEMAND_TOP_N then n = EX.DEMAND_TOP_N end
    local res = pool[cm:random_number(n)][1]

    EX.demand_res, EX.demand_tier = res, sfx
    EX.demand_due = cm:turn_number() + EX.DEMAND_GRACE
    EX.setp(EX.SAVE_DEM_RES, res)
    EX.setp(EX.SAVE_DEM_TIER, sfx)
    EX.setp(EX.SAVE_DEM_DUE, EX.demand_due)
    EX.demand_turn = cm:turn_number()
    EX.setp(EX.SAVE_DEMAND, EX.demand_turn)

    -- One message per (tier, commodity), because the amount and the goods have to appear in
    -- the text and that text is a static loc string - the same reason the dilemmas were 51
    -- rows. true, not false: our feed records are scripted_persistent_event, and the flag has
    -- to agree with the record or nothing draws.
    local msg = EX.PREFIX .. EX.seg() .. "dem_" .. sfx .. "_" .. EX.short(res)
    cm:show_message_event(fname, msg .. "_title", msg .. "_primary", msg .. "_secondary",
                          true, EX.feed("call"))
    EX.say("demand", EX.patron() .. " demands " .. amount .. " " .. res .. " (" .. sfx
        .. ") by turn " .. EX.demand_due)
    -- THE LOG KEEPS THE DEMAND, AND ITS ANSWER, beside the trades it will be paid out of. The
    -- event feed says it once; this is where a player looks back three turns later.
    EX.log_add(EX.log_subject(res), EX.patron() .. " demands " .. amount .. ", within "
        .. EX.DEMAND_GRACE .. " turns. Pay it on the Offerings tab.", res)
    if is_uicomponent(EX.panel()) then EX.refresh_panel() end
    return res
end

-- Paying one. Called from the Sacrifice button in the offerings view, which is why it returns
-- a boolean rather than logging and swallowing - EX.offer needs to know whether to fall
-- through to an ordinary offering.
function EX.pay_demand()
    local fname = EX.who()
    if not fname or not EX.demand_pending() then return false end
    local tier = EX.tier_by_suffix(EX.demand_tier)
    if not tier then
        -- The tier table changed under a save. Drop the demand rather than charge an amount
        -- nothing can name.
        EX.say("demand", "demand tier " .. tostring(EX.demand_tier)
            .. " no longer exists - dropping it")
        EX.clear_demand()
        return false
    end
    local res, amount, turns = EX.demand_res, tier[2], tier[3]
    if EX.held(res) < amount then
        EX.say("demand", "cannot pay the tithe - " .. amount .. " " .. res
            .. " wanted, " .. EX.held(res) .. " held")
        return false
    end
    cm:faction_add_pooled_resource(fname, EX.hold_key(res), "other", -amount)
    -- The favour is the SAME bundle the voluntary offering uses, at a longer duration -
    -- re-applying one key refreshes its timer rather than stacking.
    cm:apply_effect_bundle(EX.offering_key(res), fname, turns)
    -- ...and Hashut's own favour on top, which the voluntary offering does NOT grant. Paying
    -- what you were told to pay is worth more than paying what you chose to.
    cm:apply_effect_bundle(EX.pleased_bundle(), fname, turns)
    local until_turn = cm:turn_number() + turns
    EX.offer_until[res] = until_turn
    EX.setp(EX.SAVE_OFFER .. res, until_turn)
    local m = EX.PREFIX .. EX.seg() .. "dem_paid"
    cm:show_message_event(fname, m .. "_title", m .. "_primary", m .. "_secondary",
                          true, EX.feed("call"))
    EX.say("demand", "tithe paid - " .. amount .. " " .. res .. " taken, favour for "
        .. turns .. " turns")
    EX.log_add(EX.log_subject(res), "Tithe paid: " .. amount .. " to " .. EX.patron()
        .. ". Favour for " .. turns .. " turns.", res)
    EX.clear_demand()
    cm:callback(function() EX.after_holding_change(fname) end, 0.1,
                "zharr_after_pay_" .. tostring(fname))
    return true
end

-- The deadline. Runs at turn start BEFORE a new demand can be issued, so the wrath for an
-- unpaid tithe always lands before the altar asks again.
function EX.check_demand()
    if not EX.demand_pending() then return end
    if cm:turn_number() < EX.demand_due then return end
    local fname = EX.who()
    if not fname then return end
    local tier = EX.tier_by_suffix(EX.demand_tier)
    local wturns = (tier and tier[4]) or 4
    cm:apply_effect_bundle(EX.wrath_bundle(), fname, wturns)
    local m = EX.PREFIX .. EX.seg() .. "dem_wrath"
    cm:show_message_event(fname, m .. "_title", m .. "_primary", m .. "_secondary",
                          true, EX.feed("wrath"))
    EX.say("demand", "the tithe went unpaid - displeasure for " .. wturns .. " turns")
    EX.log_add(EX.log_subject(EX.demand_res), "Tithe unpaid. " .. EX.patron() .. "'s wrath for "
        .. wturns .. " turns.", EX.demand_res)
    EX.clear_demand()
end

-- The cadence gate, called at turn start.
function EX.maybe_demand()
    if not EX.setting("hashut_demands") then return end
    -- FIRST GATE, and a hard one: an unanswerable dilemma is worse than no dilemma.
    if not EX.DEMANDS_ENABLED then return end
    -- NO PATRON, NO TITHE. An uncovered race has no demand messages generated for it, and
    -- show_message_event on a key with no loc row draws an EMPTY feed entry rather than
    -- erroring - so this failure would look exactly like a game that ate the notification.
    if not EX.covered() then return end
    local turn = cm:turn_number()
    if turn < EX.opt("demand_first_turn") then return end
    -- THE `> 0` IS LOAD-BEARING. EX.demand_turn is 0 until a demand has actually fired, so
    -- without it the cooldown is measured against turn 0 and silently swallows every demand
    -- until turn DEMAND_COOLDOWN - making DEMAND_FIRST_TURN a lie whenever it is set below the
    -- cooldown. It worked only by arithmetic accident at the shipped 20 vs 15; dropping the
    -- first turn to 11 exposed it, and raising the cooldown past 20 would have exposed it in
    -- production. DEMAND_FIRST_TURN is now the sole gate on the first demand, which is what its
    -- name promises.
    if EX.demand_turn > 0 and turn - EX.demand_turn < EX.opt("demand_cooldown") then return end
    if cm:random_number(100) > EX.opt("demand_chance") then return end
    EX.fire_demand()
end

function EX.decay_pressure()
    for _, res in ipairs(EX.instruments()) do
        local p = EX.pressure[res] or 0
        if p ~= 0 then
            if p > 0 then
                p = math.max(0, p - EX.PRESSURE_DECAY)
            else
                p = math.min(0, p + EX.PRESSURE_DECAY)
            end
            EX.pressure[res] = p
            EX.setv(EX.SAVE_PRESS .. res, p)
        end
    end
end

-- ---------------------------------------------------------------------------------------
-- The panel.
-- ---------------------------------------------------------------------------------------

EX.built = false

-- ROW COMPONENTS ARE LOOKED UP, NEVER CACHED. This used to be EX.rows[res], a table of raw
-- UIComponents held for the whole session, and every reader guarded it with is_uicomponent().
-- That guard does not do what it looks like it does: is_uicomponent() is a TYPE test, so a
-- component the engine has since destroyed still passes it, and the next find_uicomponent(row,
-- ...) raises "supplied parent is not a ui component" - once per row, per refresh, forever.
-- A dead handle is indistinguishable from a live one until you use it, so the only safe rule is
-- not to keep one. Two find_uicomponent calls per row, on panel open and mode toggle only.
function EX.row(holder, res)
    if not is_uicomponent(holder) then return nil end
    return find_uicomponent(holder, EX.ROW .. "_" .. EX.short(res))
end

function EX.panel()
    return find_uicomponent(core:get_ui_root(), EX.PANEL)
end

function EX.build_panel()
    if EX.built and is_uicomponent(EX.panel()) then return true end
    local root = core:get_ui_root()
    root:CreateComponent(EX.PANEL, EX.PANEL_FILE)
    local panel = EX.panel()
    if not is_uicomponent(panel) then
        EX.say("error", "panel did not create - the exchange stays on the rites panel")
        return false
    end
    local holder = find_uicomponent(panel, "rows_holder")
    if not is_uicomponent(holder) then
        EX.say("error", "rows_holder missing from the panel layout")
        return false
    end

    for i, res in ipairs(EX.instruments()) do
        local name = EX.ROW .. "_" .. EX.short(res)
        holder:CreateComponent(name, EX.ROW_FILE)
        local row = find_uicomponent(holder, name)
        if is_uicomponent(row) then
            local ic = find_uicomponent(row, "icon")
            local path = EX.icon(res)
            if is_uicomponent(ic) and path then ic:SetImagePath(path, 0) end
        end
    end
    -- THE LEDGER'S OWN ROW POOL, EX.ORDER_MAX OF THEM, NAMED BY POSITION NOT INSTRUMENT.
    -- EX.instruments() is the row list everywhere else in this file - one component per
    -- TRADEABLE THING - but EX.orders can hold two orders on one commodity (a ladder), and
    -- that would collide on the single component EX.instruments() would give it. Created
    -- here, once, exactly like every row above; EX.mode_instruments's EX.on_orders() branch
    -- hands out the matching "ord1".."ordN" keys and EX.refresh_panel paints each one from
    -- its OWN order's resource on every call, so no icon is set at build time - there is no
    -- order yet to paint one from.
    for i = 1, EX.ORDER_MAX do
        holder:CreateComponent(EX.ROW .. "_ord" .. i, EX.ROW_FILE)
    end
    -- THE DEALS PAGE'S POOL, the same shape and for the same reason: EX.deals is a list, two
    -- of its entries can name one commodity, and the icon is painted per refresh from each
    -- deal's own resource rather than baked in here.
    for i = 1, EX.opt("deal_max") do
        holder:CreateComponent(EX.ROW .. "_dl" .. i, EX.ROW_FILE)
    end
    EX.built = true
    EX.layout()
    EX.say("ui", "panel built with " .. #EX.instruments() .. " rows")
    return true
end

-- LAYOUT LIVES HERE, NOT IN THE .twui.xml.
-- MEASURED 2026-09-04: the engine ignores dockpoint/dock_offset in the XML AND SetDockOffset at
-- runtime for these components. Every child rendered at its parent's origin, stacked, so only
-- the last-drawn one ("Sell 10") was visible and the footer text painted over the title.
-- uicomponent:MoveTo with ABSOLUTE screen coordinates is the only thing that positions them, so
-- every offset is applied here.
-- Entries are { name, x, y, width }. x, y are offsets from the parent's top-left; WIDTH is
-- optional and, where given, is applied with SetCanResizeWidth/Resize on every layout pass.
-- The width is not decoration: text CLIPS to its component, which is how a 28px-wide hdr_trend
-- once drew "Tr...". The stats view puts a faction name where "Trend" used to be, so both
-- tables carry explicit widths and switching back restores the trade view's exactly.
-- Header x offsets are the row's plus the 20px rows_holder inset. Keep them in step - the
-- generator selftest asserts it, for both modes.
-- THE SELL COLUMN, added 2026-09-06. The Price column used to be the buy price alone, with the
-- 10% cut named only in the Sell button's tooltip - which meant the one number a player needs
-- before closing a position was the one number the panel would not show. Every column left of
-- the sparkline shifted to make room; the two buttons did not move.
--
-- A 36px hdr_trend and a 56px hdr_supply each need 12px of clear space after them (a header
-- box sized to its own label has no slack, so the box gap IS the text gap - see hdr_trend's
-- history below). Those two gaps are exactly 12 and the generator selftest pins them, so this
-- table has no room left: another column means narrowing row_name or dropping the sparkline.
EX.PANEL_LAYOUT = {
    { "title_text",    20,  14 },
    { "hdr_name",      54,  50, 140 },
    { "hdr_price",    198,  50,  74 },
    { "hdr_sell",     276,  50,  74 },
    { "hdr_supply",   354,  50,  56 },
    -- hdr_spark was once at 434, two pixels past hdr_trend's right edge. A 36px box holds
    -- "Trend" with almost nothing to spare, so a 2px BOX gap is a ~6px TEXT gap and the header
    -- row read "Trend Last 12 turns" as one phrase (screenshotted 2026-09-05). The wide columns
    -- get away with 4px gaps because their boxes are far wider than their labels; this one
    -- could not, and neither can hdr_supply.
    -- 46, NOT 36. At 36 with textxoffset=4 the label has 32px and drew "Tr..." on screen
    -- (2026-09-06, second time). check_header_labels now subtracts the offset, which is
    -- what let a 33.5px word into a 32px hole while every check passed. 46 is the ceiling
    -- here: hdr_spark starts at 470.
    { "hdr_trend",    422,  50,  46 },
    -- 108 = EX.SPARK_BARS * 9, the strip's own width. hdr_spark is RIGHT-aligned (the
    -- bars fill from the right, so an early campaign draws three of them at the far end),
    -- and right-aligning to a box narrower than the strip would put the label 8px inside
    -- the newest bar. The generator selftest pins the two together.
    { "hdr_spark",    470,  50, 108 },
    { "hdr_hold",     580,  50,  88 },
    -- THE AMOUNT CLUSTER, in the 232px the header row leaves right of hdr_hold (which ends at
    -- 668) - directly above the rows' own Buy and Sell columns at 654 and 762, because that is
    -- what it governs.
    { "btn_amt_down", 676,  46,  26 },
    { "btn_amount",   706,  46, 130 },
    { "btn_amt_up",   840,  46,  26 },
    { "rows_holder",   20,  78 },
    -- BOTH FOOTERS KEEP THE FULL 880. They reach 114 and 118 characters at worst case in a
    -- box that holds ~131, and this text has clipped mid-word in play twice; the nav cluster
    -- got its own strip below them rather than 90px out of that margin.
    { "footer_text",   20, 636 },
    { "footer_text2",  20, 662 },
    { "close_button", 876,  14 },
    { "btn_help",     838,  14 },
    -- THE NAV STRIP, 696..726 in a 736-tall panel. Right edge at 906, the same as
    -- close_button's, so the two controls line up down the right-hand side. nav_page is
    -- Center-aligned in its 44px box, so "1/4" and "4/4" do not shuffle sideways as you page.
    -- THESE NINE ROWS ARE REPEATED, BYTE FOR BYTE, IN ALL TEN PANEL LAYOUT TABLES.
    -- (Written without the EX-dot-PANEL-LAYOUT spelling on purpose: gen_exchange_ui.py
    -- finds the layout tables by regex over this file, and a mention of that name inside a
    -- COMMENT is enough to invent a table it then cannot find. This comment did exactly
    -- that when it was first written - which is the eight-parser fragility it describes,
    -- demonstrating itself.)
    -- Measured, not estimated: every panel layout carries the identical block, and there is
    -- no exception anywhere - so adding the Deals tab in Stage 2 was a ten-place edit and
    -- re-pitching the strip from 132-on-140 to 108-on-116 to fit it was a second one.
    --
    -- KEPT DELIBERATELY (ruled 2026-09-16). Extracting it to one EX.TAB_STRIP means editing
    -- the eight regexes across gen_zharr_exchange.py and gen_exchange_ui.py that read these
    -- tables AS TEXT, and the failure mode of getting one wrong is a geometry check that
    -- silently sees no tabs and passes, rather than one that breaks. The duplication costs a
    -- ten-place edit per new tab; the extraction risks disarming the check that catches a bad
    -- one. gen_exchange_ui.py's tab-strip check measures each tab's right edge against its
    -- neighbour and against derpy_chd_ex_prev, per table, so the ten-place edit is at least
    -- a LOUD mistake today.
    { "derpy_chd_ex_tab_trade", 20, 698, 108 },
    { "derpy_chd_ex_tab_stats", 136, 698, 108 },
    { "derpy_chd_ex_tab_offer", 252, 698, 108 },
    { "derpy_chd_ex_tab_houses", 368, 698, 108 },
    { "derpy_chd_ex_tab_deals", 484, 698, 108 },
    { "derpy_chd_ex_tab_log",   600, 698, 108 },
    { "derpy_chd_ex_prev", 774, 696 },
    { "nav_page",     816, 701,  44 },
    { "derpy_chd_ex_mode", 876, 696 },
}

-- TRADE PAGE 2. Names no header and no row cell, so EX.layout hides every one of them, and
-- names none of page 1's columns, so none of them can be left at stale coordinates. The
-- tabs, the nav strip and both footers keep the positions they have on every other view -
-- paging must not move the furniture.
EX.PANEL_LAYOUT_CHART = {
    { "title_text",    20,  14 },
    -- The commodity icon and its name, the same pairing every list row draws.
    { "chart_icon",    20,  65 },
    { "chart_title",   50,  64, 850 },
    -- THE PLOT STARTS AT 86, NOT 20: 20..80 is the y scale gutter and 80..86 is its air.
    -- 86 + 40 * EX.CHART_PITCH = 886, against a panel content edge at 900.
    { "chart",         86, 110 },
    -- THE Y SCALE. Right-aligned into the gutter, and the three y values are NOT thirds
    -- of the box - they are where EX.draw_chart actually puts a bar top for that price.
    -- hi is CHART_TOP; lo is CHART_TOP + CHART_H - CHART_FLOOR, because the lowest price
    -- draws a CHART_FLOOR-tall stub rather than nothing at all.
    { "chart_y_hi",    20, 101,  60 },
    { "chart_y_mid",   20, 248,  60 },
    { "chart_y_lo",    20, 395,  60 },
    -- AND THE RULE EACH LABEL NAMES, running the width of the plot. The y is the LABEL's
    -- y plus 9, because the label is an 18px box centred on the line - so these three
    -- numbers and the three above cannot be edited independently without the rule and its
    -- own value drifting apart, which check_chart_geometry is what stops.
    { "chart_grid_hi",  86, 110, 800 },
    { "chart_grid_mid", 86, 257, 800 },
    { "chart_grid_lo",  86, 404, 800 },
    -- THE X SCALE, three fixed ticks under bars 0, 20 and 39. A tick with no bar over it
    -- is written blank by EX.draw_chart, which is why they can be fixed at all.
    { "chart_x_left",  86, 414,  90 },
    { "chart_x_mid",  449, 414,  90 },
    { "chart_x_right",792, 414,  90 },
    { "chart_axis",    20, 436, 880 },
    { "chart_stats",   20, 458, 880 },
    { "chart_note",    20, 480, 880 },
    -- THE TICKET, in the dead space between the chart's note and the footers. Named here and
    -- nowhere else, so EX.layout hides all seven on every other view.
    { "ord_side",     20, 508, 100 },
    { "ord_cmp",     128, 508, 140 },
    { "ord_down",    276, 508,  40 },
    { "ord_price",   324, 508, 100 },
    { "ord_up",      432, 508,  40 },
    { "ord_place",   480, 508, 100 },
    -- THE AMOUNT, STEPPED. Same idiom as the rung stepper three cells left, and for the same
    -- reason: the ladder button jumps to a round size, these reach the one in between.
    { "ord_qty_down", 596, 508, 26 },
    { "ord_qty",      626, 508, 130 },
    { "ord_qty_up",   760, 508,  26 },
    { "ord_standing", 20, 540, 880 },
    -- WHAT IT MOVES AND WHAT IT COSTS, in goods and gold - see EX.amount_line.
    { "ord_cost",     20, 566, 880 },
    { "footer_text",   20, 636 },
    { "footer_text2",  20, 662 },
    { "close_button", 876,  14 },
    { "btn_help",     838,  14 },
    { "derpy_chd_ex_tab_trade", 20, 698, 108 },
    { "derpy_chd_ex_tab_stats", 136, 698, 108 },
    { "derpy_chd_ex_tab_offer", 252, 698, 108 },
    { "derpy_chd_ex_tab_houses", 368, 698, 108 },
    { "derpy_chd_ex_tab_deals", 484, 698, 108 },
    { "derpy_chd_ex_tab_log",   600, 698, 108 },
    { "derpy_chd_ex_prev", 774, 696 },
    { "nav_page",     816, 701,  44 },
    { "derpy_chd_ex_mode", 876, 696 },
}

-- EMPTY ON PURPOSE. Every row cell is hidden by EX.layout because nothing names it, and
-- EX.mode_instruments returns an empty list on this page so no row is drawn at all.
EX.ROW_LAYOUT_CHART = {}

-- TRADE PAGE 3. The standing-order ledger, one row per order, reusing the trade row shape.
-- Names no price/sell/supply/spark header, so EX.layout hides all of them.
EX.PANEL_LAYOUT_ORDERS = {
    { "title_text",    20,  14 },
    { "hdr_name",      54,  50, 170 },
    -- The order sentence gets the width the sparkline and the two price columns had.
    { "hdr_trend",    240,  50, 320 },
    { "hdr_price",    574,  50,  74 },
    { "rows_holder",   20,  78 },
    -- THE TICKET, at the same coordinates the chart page gives it. Named by BOTH tables on
    -- purpose: the chart page answers to deep_history and the ledger to orders, and with the
    -- ticket named only by the chart there was no way to place an order with deep_history off
    -- - on a page whose own empty-state text told the player to go and set one. Twelve rows
    -- of ledger end at y 414, so this sits in the same dead space here as it does there.
    { "ord_side",     20, 508, 100 },
    { "ord_cmp",     128, 508, 140 },
    { "ord_down",    276, 508,  40 },
    { "ord_price",   324, 508, 100 },
    { "ord_up",      432, 508,  40 },
    { "ord_place",   480, 508, 100 },
    -- THE AMOUNT, STEPPED. Same idiom as the rung stepper three cells left, and for the same
    -- reason: the ladder button jumps to a round size, these reach the one in between.
    { "ord_qty_down", 596, 508, 26 },
    { "ord_qty",      626, 508, 130 },
    { "ord_qty_up",   760, 508,  26 },
    { "ord_standing", 20, 540, 880 },
    -- WHAT IT MOVES AND WHAT IT COSTS, in goods and gold - see EX.amount_line.
    { "ord_cost",     20, 566, 880 },
    { "footer_text",   20, 636 },
    { "footer_text2",  20, 662 },
    { "close_button", 876,  14 },
    { "btn_help",     838,  14 },
    { "derpy_chd_ex_tab_trade", 20, 698, 108 },
    { "derpy_chd_ex_tab_stats", 136, 698, 108 },
    { "derpy_chd_ex_tab_offer", 252, 698, 108 },
    { "derpy_chd_ex_tab_houses", 368, 698, 108 },
    { "derpy_chd_ex_tab_deals", 484, 698, 108 },
    { "derpy_chd_ex_tab_log",   600, 698, 108 },
    { "derpy_chd_ex_prev", 774, 696 },
    { "nav_page",     816, 701,  44 },
    { "derpy_chd_ex_mode", 876, 696 },
}

-- btn_buy IS THE CANCEL BUTTON, and btn_sell is deliberately not placed. Same idiom as the
-- offerings view, where btn_buy is "Sacrifice": the click handler branches on which view it
-- is in, so a placed btn_sell here would be a live Sell button sitting over a Cancel column.
-- gen_exchange_ui.py asserts that for the offerings view already; extend it to this one.
EX.ROW_LAYOUT_ORDERS = {
    { "divider",      6, 26 },
    { "icon",         6,  2 },
    { "row_name",    34,  5, 170 },
    { "row_trend",  220,  5, 320 },
    { "row_price",  554,  5,  74 },
    { "btn_buy",    654,  1 },
}

-- WHICH ORDER A ROW IS. NOT resolved through EX.res_of_row: rows are pooled ONE PER
-- INSTRUMENT everywhere else in this file (EX.row keys strictly on EX.short(res)), and a
-- ladder - two orders on one commodity, which is the entire reason standing orders are a
-- LIST and not one slot per instrument - would collide on that single component. The ledger
-- gets its own fixed pool instead: EX.mode_instruments()'s EX.on_orders() branch hands out
-- synthetic "ord1".."ordN" keys, one per LIST POSITION rather than per instrument, and
-- EX.build_panel creates a matching EX.ORDER_MAX row components for them. The id this
-- receives is always EX.ROW .. "_ord" .. n; anything else - a real instrument's row, a
-- foreign component - answers nil, which is what keeps the trade/offerings/houses click
-- paths from ever claiming a ledger row by accident.
function EX.order_of_row(id)
    local n = tonumber(string.match(tostring(id), "^" .. EX.ROW .. "_ord(%d+)$"))
    if not n then return nil end
    return EX.orders[n]
end

-- THE DEALS PAGE'S OWN, and it exists for exactly the reason EX.order_of_row does: the page
-- hands out "dl1".."dlN" by LIST POSITION, because two deals can name one commodity (the
-- shipped fixture posts glass twice) and a per-instrument key would collide. Anything that is
-- not EX.ROW .. "_dl" .. n answers nil, which is what stops a trade or offerings row ever being
-- claimed as a deal.
--
-- IT RETURNS THE INDEX AND NOT THE DEAL. EX.accept_deal takes an index, and the index is also
-- what crosses the wire in multiplayer - see EX.MP_OPS.deal. Handing back the table here would
-- mean finding the index again at the send site, off a list the other client resolved
-- separately.
function EX.deal_of_row(id)
    local n = tonumber(string.match(tostring(id), "^" .. EX.ROW .. "_dl(%d+)$"))
    if not n or not EX.deals[n] then return nil end
    return n
end

-- Rows are 28px apart, so every child has to fit inside 28 or it bleeds into the next row.
EX.ROW_LAYOUT = {
    { "divider",      6, 26 },
    { "icon",         6,  2 },
    { "row_name",    34,  5, 140 },
    { "row_price",  178,  5,  74 },
    { "row_sell",   256,  5,  74 },
    { "row_supply", 334,  5,  56 },
    { "row_trend",  402,  5,  30 },
    { "spark",      450,  1 },
    -- "600  -300g" is ~62px at size 12, so 88 holds the widest holding this can print.
    { "row_hold",   560,  5,  88 },
    { "btn_buy",    654,  1 },
    { "btn_sell",   762,  1 },
}

-- THE STATS VIEW. Same components, different places, different widths, different text. The two
-- trade buttons are hidden, which is what frees 200px for a faction name.
--   row_name   Commodity          row_price  the top holder's share
--   row_supply total output       row_hold   the cartel premium in gold
--   row_trend  the top holder     spark      unchanged, price history reads in both views
EX.PANEL_LAYOUT_STATS = {
    { "title_text",    20,  14 },
    { "hdr_name",      54,  50, 170 },
    { "hdr_supply",   240,  50,  60 },
    { "hdr_trend",    320,  50, 190 },
    { "hdr_price",    532,  50,  70 },
    { "hdr_hold",     636,  50, 100 },
    { "hdr_spark",    780,  50, 108 },
    { "rows_holder",   20,  78 },
    -- BOTH FOOTERS KEEP THE FULL 880. They reach 114 and 118 characters at worst case in a
    -- box that holds ~131, and this text has clipped mid-word in play twice; the nav cluster
    -- got its own strip below them rather than 90px out of that margin.
    { "footer_text",   20, 636 },
    { "footer_text2",  20, 662 },
    { "close_button", 876,  14 },
    { "btn_help",     838,  14 },
    -- THE NAV STRIP, 696..726 in a 736-tall panel. Right edge at 906, the same as
    -- close_button's, so the two controls line up down the right-hand side. nav_page is
    -- Center-aligned in its 44px box, so "1/4" and "4/4" do not shuffle sideways as you page.
    { "derpy_chd_ex_tab_trade", 20, 698, 108 },
    { "derpy_chd_ex_tab_stats", 136, 698, 108 },
    { "derpy_chd_ex_tab_offer", 252, 698, 108 },
    { "derpy_chd_ex_tab_houses", 368, 698, 108 },
    { "derpy_chd_ex_tab_deals", 484, 698, 108 },
    { "derpy_chd_ex_tab_log",   600, 698, 108 },
    { "derpy_chd_ex_prev", 774, 696 },
    { "nav_page",     816, 701,  44 },
    { "derpy_chd_ex_mode", 876, 696 },
}

EX.ROW_LAYOUT_STATS = {
    { "divider",      6, 26 },
    { "icon",         6,  2 },
    { "row_name",    34,  5, 170 },
    { "row_supply", 220,  5,  60 },
    { "row_trend",  300,  5, 190 },
    { "row_price",  512,  5,  70 },
    { "row_hold",   616,  5, 100 },
    { "spark",      760,  1 },
}

-- THE GUIDE, one line per row component, now PAGED (Task 8). Asked for from play 2026-09-06:
-- "we need to add a guide on what the symbols mean or how it works in the game". It was full
-- at 19 lines against 19 usable rows, and this comment used to say "a twentieth line needs a
-- real panel" - Tasks 1-7 then added seven concepts a player cannot infer (guild, their book,
-- markup, refusal, war lock, whose gold, front-running), so the ceiling was hit before the
-- first of them was written. Paging is that panel, and it costs no new file - the guide
-- already borrows rows_holder rather than owning components, so a second page is one more
-- index into the same rows.
--
-- IT REUSES THE ROWS. rows_holder already creates one row per instrument and every row already
-- has a name cell and a wide cell, so the guide is a relabelling rather than a second panel -
-- no new file, no new GUID range, no second set of textures. The ceiling is the row count, and
-- check_help_lines() holds every PAGE to it, not just the first.
--
-- Column 2 is 620px and the font is ~6.7px/char, so a line has about 92 characters.
-- check_help_lines() measures every line of every page; nothing else would catch a clip.
EX.HELP_PAGES = {
    { -- PAGE 1: the market
        { "Buy / Sell",   "What a lot costs, and what one pays you. The gap is the house's cut." },
        { "Output",       "Units the whole world makes per turn. Buying never consumes it." },
        { EX.TREND_UP .. " / " .. EX.TREND_DOWN,
                          "The price rose or fell since last turn. A dash means it held still." },
        { EX.TREND_CAP .. " / " .. EX.TREND_FLOOR,
                          "The highest or lowest the ladder goes. It cannot move further that way." },
        { "Last 12 turns", "One bar per turn of this good's price. Taller costs more." },
        { "Held",         "Units you own. They are yours until you sell them." },
        -- FOLDED FROM TWO LINES, to make room for the Houses view below without breaking the
        -- 19-row ceiling - see the note above EX.HELP_PAGES. Same two facts, one line. ONE
        -- quoted string, not a concatenation: check_help_lines() takes the LAST quoted literal
        -- in an entry as the whole sentence, so a "..".join sentence here would be measured short.
        { "Rent",         "0.5g per unit per turn, whatever it's worth - cheap bulk hurts, dense goods almost free." },
        { "Stockpile 100", "Hold 100 of one good and it grants a standing bonus while you hold." },
        { "Warehouse 300", "Hold 300 and the bonus doubles. Same as burning them on the altar." },
        { "Vaults 600",   "Hold 600 and it triples. A deep position is a strategy, not a tax." },
        -- ALSO FOLDED FROM TWO LINES, same reason and same one-string rule.
        { "Offerings",    "Burn 30 units for Hashut's favour, 5 turns - the quick way. Holding is the slow one." },  -- patron-literal: rewritten by EX.bind_race
        { "Ownership",    "The second tab: who makes each good and what their grip adds to it." },
        { "Cartel premium", "One faction holding most of a good makes it cost more than scattered." },
        { "Wanted",       "The world wants more of these than it makes, so prices are climbing." },
        { "Unwanted",     "Nobody wants these. Prices are falling." },
        { "Shaken",       "A settlement making this was just hit. The spike fades in ~3 turns." },
        -- THE HOUSES VIEW, the three lines Task 7 adds. The fold above is what buys their room.
        { "Div",          "Houses pay 2% of their price per share, every turn - it just arrives, no altar needed." },
        { "Delisted",     "A house's capital falls: taken by you pays 1.25x, by anyone else 0.5x." },
        { "House Sell",   "Sell still pays 10% under Buy here too - Div shows the dividend, not the sell price." },
    },
    { -- PAGE 2: the guild
        { "Guild",        "A Chaos Dwarf house trades here - so do your bloc's. One is across every deal." },
        { "Their book",   "What the guild holds moves the price, the same way your own buying does." },
        { "Markup",       "A house that dislikes you charges more and pays less. Sign anything and it stops." },
        { "Refused",      "A house that despises you and holds most of a good will not sell it." },
        { "At war",       "A house at war closes its book. Enough of them and the Exchange shuts." },
        { "Their gold",   "Your money goes to the house that sold to you. Gouging you makes it richer." },
        { "Front-run",    "A hostile house that sees you buying will buy ahead of you." },
        -- LAYER 2, and the one line that stops the fire sale reading as a bug. Page 2 because
        -- page 1 is at the 19-row ceiling; check_help_lines measures every line here too.
        -- NO LITERAL NUMBER, because l2_sell is a difficulty knob now and this line is static
        -- text that check_help_lines measures rather than resolves. The Sell column already
        -- carries the live figure; this line exists so the loss does not read as a bug.
        { "Forge goods",  "Armaments and Raw Materials sell back at a loss set by difficulty." },
        -- THE FOOTER'S OWN NUMBER, explained. "Worth" is a sell-side figure and a player who
        -- read it as the buy-side total would think the spread had eaten their money.
        { "Worth",        "What all you hold would fetch if sold now - after the spread, not before." },
    },
}

-- WHICH GUIDE LINES CARRY THE PATRON'S NAME, and which the guild's. Named rather than
-- inlined at the rewrite site in EX.bind_race: adding one line to page 1 above the Offerings
-- entry would otherwise silently replace an unrelated sentence with the offerings one, and
-- check_help_lines measures lengths, not meanings. Both are asserted there by content.
EX.HELP_OFFER_LINE = 11
EX.HELP_GUILD_LINE = 1

EX.help_page = 1   -- VIEW STATE ONLY, never saved: the guide always opens on page 1. See
                    -- EX.help_lines() below and the reset in the help-button click handler.

-- THE GUIDE'S NUMBERS, READ LIVE. Each of these lines quotes an MCT setting - or, for the
-- offering, a price that rises with every offering made - and the literal above is only its
-- default: a Hard campaign read "0.5g" of rent over a board charging more, and a Bourse player
-- read "2%" over the dividend their own race profile sets. Keyed by the line's term, so
-- moving a line cannot rewrite the wrong one. Every builder returns its literal word for word
-- at the defaults - check_layout holds it to that - so the wording has one source to agree with.
EX.HELP_LIVE = {
    ["Rent"] = function()
        return EX.num(EX.opt("carry_per_unit")) .. "g per unit per turn, whatever it's worth - "
            .. "cheap bulk hurts, dense goods almost free."
    end,
    ["Offerings"] = function()
        return "Burn " .. EX.offer_cost() .. " units for " .. EX.patron() .. "'s favour, "
            .. EX.OFFER_TURNS .. " turns - the quick way. Holding is the slow one."
    end,
    ["Div"] = function()
        return "Houses pay " .. EX.num(EX.opt("div_yield") * 100) .. "% of their price per "
            .. "share, every turn - it just arrives, no altar needed."
    end,
    ["Delisted"] = function()
        return "A house's capital falls: taken by you pays " .. EX.num(EX.opt("buyout_premium"))
            .. "x, by anyone else " .. EX.num(EX.opt("windup")) .. "x."
    end,
    ["House Sell"] = function()
        return "Sell still pays " .. EX.num(EX.opt("spread") * 100) .. "% under Buy here too - "
            .. "Div shows the dividend, not the sell price."
    end,
}

function EX.help_lines()
    local page = EX.HELP_PAGES[EX.help_page] or EX.HELP_PAGES[1]
    local out = {}
    for i, l in ipairs(page) do
        local f = EX.HELP_LIVE[l[1]]
        local ok, s = false, nil
        if f then ok, s = pcall(f) end
        out[i] = (ok and type(s) == "string") and { l[1], s } or l
    end
    return out
end

-- The guide's own footer. Two static lines, measured by check_help_lines() like the rest.
EX.HELP_FOOT1 = "Rent is charged every turn on all you hold, whichever way the price went."
-- NAMES THE WAY OUT. The arrows used to leave the guide, which was how a player escaped it by
-- accident; now they page it (below), so the help button is the only way out and this line is
-- the only place that says so.
EX.HELP_FOOT2 = "Arrows turn the page. The help button closes the guide."

EX.PANEL_LAYOUT_HELP = {
    { "title_text",    20,  14 },
    { "hdr_name",      54,  50, 200 },
    { "hdr_trend",    260,  50, 620 },
    { "rows_holder",   20,  78 },
    -- BOTH FOOTERS KEEP THE FULL 880. They reach 114 and 118 characters at worst case in a
    -- box that holds ~131, and this text has clipped mid-word in play twice; the nav cluster
    -- got its own strip below them rather than 90px out of that margin.
    { "footer_text",   20, 636 },
    { "footer_text2",  20, 662 },
    { "close_button", 876,  14 },
    { "btn_help",     838,  14 },
    -- THE NAV STRIP, 696..726 in a 736-tall panel. Right edge at 906, the same as
    -- close_button's, so the two controls line up down the right-hand side. nav_page is
    -- Center-aligned in its 44px box, so "1/4" and "4/4" do not shuffle sideways as you page.
    { "derpy_chd_ex_tab_trade", 20, 698, 108 },
    { "derpy_chd_ex_tab_stats", 136, 698, 108 },
    { "derpy_chd_ex_tab_offer", 252, 698, 108 },
    { "derpy_chd_ex_tab_houses", 368, 698, 108 },
    { "derpy_chd_ex_tab_deals", 484, 698, 108 },
    { "derpy_chd_ex_tab_log",   600, 698, 108 },
    { "derpy_chd_ex_prev", 774, 696 },
    { "nav_page",     816, 701,  44 },
    { "derpy_chd_ex_mode", 876, 696 },
}
EX.ROW_LAYOUT_HELP = {
    { "divider",      6, 26 },
    { "row_name",    34,  5, 200 },
    { "row_trend",  240,  5, 620 },
}

-- ===========================================================================================
-- THE INTRODUCTION. Shown once, to each player, the first time they open the panel.
-- ===========================================================================================
--
-- NO NEW COMPONENTS. It borrows the row machinery the guide already borrows, with one cell
-- instead of two: prose across the full width. That is the whole implementation cost of this
-- view, and it is why there are no new GUIDs and no change to the .twui.xml at all.
--
-- NO DIVIDER, deliberately. The guide rules every line because its lines are entries in a
-- table; ruling a paragraph makes it look like one too.
EX.PANEL_LAYOUT_INTRO = {
    { "title_text",    20,  14 },
    -- No hdr_name/hdr_trend: there are no columns to head. EX.layout hides both, and
    -- EX.HEADERS.intro is empty rather than absent - refresh_panel walks
    -- pairs(EX.HEADERS[EX.mode]) BEFORE it branches, so a missing entry indexes nil and takes
    -- the whole refresh down the first time anyone reaches the view.
    { "rows_holder",   20,  78 },
    { "footer_text",   20, 636 },
    { "footer_text2",  20, 662 },
    { "close_button", 876,  14 },
    { "btn_help",     838,  14 },
    -- THE TAB STRIP IS THE WAY OUT, and the only one. There is no dismiss button because the
    -- five buttons the player is about to use are already on screen and the last line points
    -- at them; a sixth button whose whole job is "stop showing this" would be a control the
    -- panel never needs again.
    { "derpy_chd_ex_tab_trade", 20, 698, 108 },
    { "derpy_chd_ex_tab_stats", 136, 698, 108 },
    { "derpy_chd_ex_tab_offer", 252, 698, 108 },
    { "derpy_chd_ex_tab_houses", 368, 698, 108 },
    { "derpy_chd_ex_tab_deals", 484, 698, 108 },
    { "derpy_chd_ex_tab_log",   600, 698, 108 },
    { "derpy_chd_ex_prev", 774, 696 },
    { "nav_page",     816, 701,  44 },
    { "derpy_chd_ex_mode", 876, 696 },
}
EX.ROW_LAYOUT_INTRO = {
    -- THE SAME 6,2 AS EVERY OTHER VIEW, so the paragraphs start at 34 like the commodity
    -- names do. Without this entry EX.draw_intro would still SHOW the cell - it sets
    -- visibility itself - and EX.layout would never MOVE it, so every picture would draw at
    -- whatever x the last view left it at.
    { "icon",         6,  2 },
    { "row_name",    34,  5, 850 },
}

EX.INTRO_UNCOVERED =
    "Your people keep no altar here, but the market is open to you: buy, sell and hold."
-- A PLAIN CRATE for a culture with no profile: there is no crest to draw when there is no
-- race table row, and the alternative - keeping whichever crest was last painted - would tell
-- an uncovered player they are somebody else.
EX.INTRO_UNCOVERED_CREST = "resource"

-- BUILT AT DRAW TIME, NOT AT FILE SCOPE. Every line that names the market, the patron or the
-- race has to be resolved after EX.bind_race, and this file is read before any faction
-- exists - the same reason EX.TIPS and EX.HELP_PAGES carry the note they do. The difference
-- is that those two are literals patched in place; this one has nothing worth caching.
--
-- TWO FIELDS PER LINE: the sentence, and the picture beside it. A line with no picture HIDES
-- the cell rather than leaving the last one standing - see EX.draw_intro.
--
-- A BLANK ROW BETWEEN EVERY PARAGRAPH. Asked for from a screenshot 2026-09-09 ("looks plain
-- ... separate by paragraph"): nine paragraphs on nine consecutive rows read as a wall of
-- text with half a panel of dead space underneath them. The break costs nothing - the view
-- already drew a blank row as a break - and it fills the page.
--
-- SEVENTEEN LINES, AND THE CEILING IS THE RACE'S, NOT THE PANEL'S. EX.mode_instruments hands
-- this view COMMODITIES + LAYER2, and LAYER2 is the Chaos Dwarf pair - every other race binds
-- it empty. So a Chaos Dwarf player has 19 rows and everybody else has 17, and a line past the
-- end is not an error: the draw walks the ROWS, so it simply never appears. Written at 19 and
-- caught by the harness, which binds a race with no Layer 2 - two paragraphs would have gone
-- missing for six profiles out of eight and drawn perfectly for the one being looked at.
--
-- WHICH IS WHY THE CLOSING INSTRUCTION IS IN THE FOOTER. It is the one line that is an
-- instruction rather than a concept, the footers sit directly under the page saying much the
-- same thing, and moving it there bought back the two rows the breaks needed.
function EX.intro_lines()
    local r = EX.rc()
    return {
        { (r and r.intro) or EX.INTRO_UNCOVERED,
          EX.art((r and r.crest) or EX.INTRO_UNCOVERED_CREST) },
        { "" },
        { "BUY AND SELL. Every good shows two prices. You buy at the higher and sell at the "
          .. "lower; the gap is the house's cut.", EX.art("treasury") },
        { "" },
        { "PRICES MOVE IN STEPS. Each step is a fixed move up or down, so a price is a step "
          .. "count rather than a number someone picked.", EX.art("dlc12_discover_up") },
        { "" },
        { "OUTPUT is what the whole world produces each turn. Buying never consumes it. What "
          .. "moves a price against you is pressure.", EX.art("sphere_of_influence_size") },
        { "" },
        { "PRESSURE. Your own trades push the price. Buy the board out and every lot after "
          .. "the first one costs you more.", EX.art("siege_attack") },
        { "" },
        { "WANTED and UNWANTED at the foot of the page are the world's appetites: who "
          .. "wants what this turn, and who does not.", EX.art("edict_stimulate_trade") },
        { "" },
        { "THE WAREHOUSE. All you hold costs rent every turn, whichever way the price went. A "
          .. "pile is a position, not a prize.", EX.art("cargo") },
        { "" },
        { "OFFERINGS AND TITHES. " .. EX.patron() .. " takes goods rather than gold, and "
          .. "remembers whether you paid.", EX.art("effect_rite") },
        { "" },
        { "HOUSES. Buy shares in factions - yours and your bloc's. They pay a dividend each "
          .. "turn, and they can die owing you.", EX.art("office") },
    }
end

-- THE CLOSING INSTRUCTION, and it is these two lines rather than a row for the reason written
-- above EX.intro_lines: the page is exactly as long as the shortest race's holder.
EX.INTRO_FOOT1 = "Click a tab below to begin. The ? button opens the full guide, in more detail."
EX.INTRO_FOOT2 = "This page will not be shown again. Nothing here has cost you anything - no trade is made until you make it."

-- ===========================================================================================
-- THE LOG. Why the Exchange did what it did, in the player's own words rather than a number.
-- ===========================================================================================
--
-- ASKED FOR FROM PLAY, and the reason is worth writing down: every fault reported against this
-- feature so far has been the panel failing to EXPLAIN itself, never the mechanics being
-- wrong. The war lock wearing the refusal sentence, the houses row's live-but-dead Buy, a
-- refusal naming a house that produces none of the good - three reports, three cases of
-- correct behaviour that read as broken. A refusal is a single word on a button and the
-- reasoning behind it (a treaty tier, a rank within the guild's negative spread, a share of a
-- book that is drawn nowhere on the panel) is invisible. This is where it goes.
--
-- A FIFTH VIEW, NOT A NEW PANEL. It is one line in EX.MODES, which is what the tab strip,
-- EX.HEADERS and the layout branches all read; the alternative was a second runtime-created
-- .twui.xml, and docs/CUSTOM_UI.md is a list of the ways that fails in silence. This borrows
-- rows_holder exactly as the guide does.
EX.MODE_LOG = "log"
-- 120 SINCE THE WORLD STARTED WRITING HERE (2026-09-09). At 60 this held about a dozen turns
-- once the guild's books, the dividends and the appetite each took a line, and the entries it
-- dropped were the player's OWN trades - the thing the log was built for. Only the newest
-- EX.MAX_ROWS are ever drawn; the rest is what the arrows page back through.
EX.LOG_MAX = 120
EX.LOG = {}
-- ONE PACKED STRING, the shape EX.SAVE_HOUSES and EX.SAVE_BOOK already use. A log that emptied
-- on every load would answer "why was I refused" with silence in the one situation a player
-- most wants it - coming back to a campaign after a week.
--
-- THE SEPARATORS ARE CONTROL BYTES, not ';' and '|'. Every field here is free text written
-- for a human - a faction's display name, a whole sentence - and any printable delimiter is one
-- loc string away from turning up inside a field and eating the rest of the log.
--
-- Built with string.char rather than written as escapes or as the literal bytes: an editor that
-- cannot show byte 30 cannot show you it was deleted either, and this file has already had a
-- pair of escapes silently rewritten in transit once.
-- WHICH PAGE OF THE LOG IS SHOWING. View state, never saved - the same reasoning as
-- EX.help_page: the log opens on its newest page, which is what a player who just clicked
-- "Log" is asking about.
EX.log_page = 1
EX.SAVE_LOG = "zharr_log"
-- WHAT A LOG LINE CALLS ITS INSTRUMENT. Houses and commodities have different accessors and
-- the log carries both, so this is the one place that knows which to ask.
--
-- IT REPLACES A FUNCTION THAT NEVER EXISTED. Every site used to read
-- `EX.display_name and EX.display_name(res) or res`, and EX.display_name was never defined
-- anywhere - so the guard that was meant to be belt-and-braces silently became the only
-- branch, and the log drew "res_rom_furs" (screenshotted 2026-09-07). An `and ... or` around
-- a name you have not grepped for is not a guard, it is a fallback that hides the typo.
function EX.log_subject(res)
    if not res or res == "" then return "" end
    -- NOT EX.is_house. That is membership of EX.houses, and EX.prune_houses REMOVES a settled
    -- house from it - so the very row drawn for a house's own settlement fell through to the
    -- commodity path and printed the raw key. Asking whether this file has a commodity record
    -- for the key cannot go stale that way: EX.INFO and EX.LAYER2 are fixed lists.
    if EX.INFO[res] or EX.is_layer2(res) then return EX.display(res) end
    return EX.faction_display(res)
end
EX.LOG_RS = string.char(30)
EX.LOG_FS = string.char(31)
function EX.pack_log()
    local out = {}
    for i = 1, #EX.LOG do
        local e = EX.LOG[i]
        out[#out + 1] = tostring(e[1]) .. EX.LOG_FS .. tostring(e[2]) .. EX.LOG_FS
            .. tostring(e[3]) .. EX.LOG_FS .. tostring(e[4] or "")
    end
    return table.concat(out, EX.LOG_RS)
end
function EX.unpack_log(s)
    EX.LOG = {}
    if not s or s == "" then return end
    for rec in string.gmatch(s, "[^" .. EX.LOG_RS .. "]+") do
        local f = {}
        for fld in string.gmatch(rec .. EX.LOG_FS,
                                 "([^" .. EX.LOG_FS .. "]*)" .. EX.LOG_FS) do f[#f + 1] = fld end
        -- 3 FIELDS, NOT 4, IS A LOG SAVED BEFORE THE ICON SHIPPED. Those entries keep their
        -- text and simply draw no icon; refusing them would empty a live campaign's log on the
        -- first load after an update, which is the failure this store exists to prevent.
        if #f >= 3 then
            EX.LOG[#EX.LOG + 1] = { tonumber(f[1]) or 0, f[2], f[3], f[4] or "" }
        end
    end
    while #EX.LOG > EX.LOG_MAX do EX.LOG[#EX.LOG] = nil end
end

-- NEWEST FIRST, and capped. Entries are {turn, subject, detail}.
--
-- DEDUPED ON THE SAME TURN. Turn-start state checks re-run on load and on every refresh that
-- follows, so without this a single closure writes one line per refresh for the rest of the
-- turn and the log is nothing but that.
-- SUBJECT MAY BE THE EMPTY STRING, which means "resolve it from the key when this is drawn".
-- The guard below rejects nil and not "", which is the difference between a half-written entry
-- and a deliberately deferred name.
function EX.log_add(subject, detail, key)
    if not subject or not detail then return end
    local turn = 0
    pcall(function() turn = cm:model():turn_number() end)
    local first = EX.LOG[1]
    if first and first[1] == turn and first[2] == subject and first[3] == detail then return end
    table.insert(EX.LOG, 1, { turn, subject, detail, key or "" })
    while #EX.LOG > EX.LOG_MAX do EX.LOG[#EX.LOG] = nil end
    -- SAVED ON EVERY ADD rather than at turn end: entries are written from the trade path,
    -- which the player can fire any number of times between turns, and a crash or an alt-F4
    -- should not lose the reasoning for the last thing they did.
    pcall(function() EX.setp(EX.SAVE_LOG, EX.pack_log()) end)
end

-- WHAT THE PANEL DRAWS: {left, right} per row, newest first, capped to the rows that exist.
--
-- THE CAP COMES FROM EX.mode_instruments(), which is the list the render loop iterates - not
-- from EX.MAX_ROWS. The two are not the same number: this view borrows one row per instrument
-- and there are 19 of those against 20 slots, so a flat MAX_ROWS cap handed back a 20th line
-- that no row existed to draw AND made the footer claim it had drawn it. Reading the cap off
-- the same list the renderer walks is the only shape where they cannot drift apart.
-- HOW MANY PAGES THE LOG HAS. At least one, so an empty log still draws its placeholder
-- page and the counter reads 1/1 rather than 1/0.
function EX.log_per_page()
    local n = #EX.mode_instruments()
    if n < 1 then n = 1 end
    return n
end
function EX.log_pages()
    local n = math.ceil(#EX.LOG / EX.log_per_page())
    if n < 1 then n = 1 end
    return n
end

function EX.log_lines()
    local out = {}
    local cap = EX.log_per_page()
    -- CLAMPED HERE, not only where the arrows move it. EX.LOG shrinks on a new campaign and
    -- grows on every trade, so a page index that was valid when it was set can be past the
    -- end by the time this runs - and an out-of-range page draws an empty log, which reads
    -- exactly like a log that recorded nothing.
    if EX.log_page > EX.log_pages() then EX.log_page = EX.log_pages() end
    if EX.log_page < 1 then EX.log_page = 1 end
    local from = (EX.log_page - 1) * cap
    for j = 1, cap do
        local i = from + j
        if i > #EX.LOG then break end
        local e = EX.LOG[i]
        -- AN EMPTY SUBJECT IS RESOLVED HERE, from the key. Entries written from a turn handler
        -- defer the name rather than reach common.get_localised_string at turn 1 - see
        -- EX.log_settlement for the CTD that bought.
        local subj = tostring(e[2])
        if subj == "" and e[4] and e[4] ~= "" then
            local ok, nm = pcall(EX.log_subject, e[4])
            subj = (ok and nm and nm ~= "") and nm or e[4]
        end
        -- THIRD FIELD IS THE KEY, and it is what the row's icon is painted from - not the
        -- row's own instrument, which has nothing to do with the line that landed in it.
        out[#out + 1] = { "T" .. tostring(e[1]) .. "  " .. subj, tostring(e[3]),
                          e[4] or "" }
    end
    if #out == 0 then
        out[1] = { "Nothing yet",
                   "Trades, refusals and closures are recorded here as they happen.", "" }
    end
    return out
end

-- ===========================================================================================
-- THE WORLD'S OWN ENTRIES. What the houses and the map did, in the player's log.
-- ===========================================================================================
--
-- ASKED FOR FROM PLAY 2026-09-09: "add all logging to ai so that player can see there is
-- interaction between the mechanics and the ai". Before this the Log recorded six kinds of
-- event and three of them were the player's own; the AI houses traded every turn, their books
-- are what a refusal is measured against, and none of it appeared anywhere at all.
--
-- NOT ONE LINE PER HOUSE. Twenty houses across seventeen goods would fill the whole buffer
-- inside two turns and push out the trades the log exists to explain. One line per topic.
--
-- NO FACTION NAME IS RESOLVED IN HERE, and that is not a style choice: this runs inside
-- FactionTurnStart, where common.get_localised_string took the process down at turn 1 of a
-- fresh campaign with no Lua error, no minidump, and pcall making no difference. Commodity
-- names are safe - EX.display reads the generated EX.INFO table, which is plain Lua - but a
-- house's name is loc. A line that needs one passes subject "" and the KEY in field 4, which
-- EX.log_lines resolves when the row is drawn.
--
-- BUILT ONCE, WRITTEN PER PLAYER, and the split is load-bearing in multiplayer. The books and
-- the appetite are world state, so the decision "is this worth a line" has to be made once: a
-- per-player version would log the appetite change for the first human and swallow it for
-- everybody else, because the first comparison is what stops it being a change.
EX.world_lines = {}
-- The appetite line as it last read. nil means "not compared yet this session" - the first
-- turn after a load therefore records the summary without announcing it as news, the same
-- guard EX.share_shocks uses on EX.cshare_ready and for the same reason.
EX.log_appetite = nil

-- The commodity that moved most, out of one of EX.book_flow's two tallies.
local function top_of(t)
    local key, n = nil, 0
    for res, v in pairs(t or {}) do
        if v > n then key, n = res, v end
    end
    return key, n
end

function EX.build_world_log()
    EX.world_lines = {}
    local f = EX.book_flow
    if f and (f.bought > 0 or f.sold > 0) then
        local tb, tbn = top_of(f.buy)
        local ts, tsn = top_of(f.sell)
        local d = f.houses .. " house(s) traded: bought " .. f.bought
            .. ", sold " .. f.sold .. "."
        if tb then d = d .. "  Most bought " .. EX.display(tb) .. " (+" .. tbn .. ")." end
        if ts then d = d .. "  Most sold " .. EX.display(ts) .. " (-" .. tsn .. ")." end
        -- The icon is the good the guild moved most of, which is the one the line is about.
        EX.world_lines[#EX.world_lines + 1] = { "The guild", d, tb or ts or "" }
    end
    -- THE WORLD'S APPETITE, ON CHANGE ONLY. It is the footer's line verbatim, so the log and
    -- the footer cannot disagree about what the world wants; logging it every turn would be a
    -- line a turn saying nothing moved.
    local ok, sum = pcall(EX.appetite_summary)
    if ok and sum then
        if EX.log_appetite ~= nil and sum ~= EX.log_appetite then
            EX.world_lines[#EX.world_lines + 1] = { "World appetite", sum, "" }
        end
        EX.log_appetite = sum
    end
end

function EX.flush_world_log()
    for _, e in ipairs(EX.world_lines or {}) do EX.log_add(e[1], e[2], e[3]) end
end

-- THE STATE CHECK. Records what CHANGED rather than what is true, so a standing closure does
-- not write a line every turn.
--
-- CALLED FROM ONE PLACE: EX.refresh_panel, under pcall, when the Log view is the open view.
-- Not at turn start, and not after a trade - an earlier version of this comment said both, and
-- a 2026-09-09 grep for those two call sites found neither and wrote the function off as dead.
-- It is not dead. The consequence of the real wiring is that edges are detected at DRAW time:
-- a closure that opens and lifts again while the Log view was never opened is never recorded.
EX.log_seen = {}
function EX.log_scan()
    local closed = EX.market_closed()
    local was = EX.log_seen.closed
    if closed and not was then
        EX.log_add("Market", "CLOSED. Too much of the guild is at war with you, "
            .. EX.faction_display(closed) .. " chief among them. Selling stays open.")
    elseif was and not closed then
        EX.log_add("Market", "Reopened. Enough of the guild is at peace with you again.")
    end
    EX.log_seen.closed = closed and true or false

    -- REFUSALS, per commodity, recorded when they APPEAR and when they LIFT. The share is in
    -- the line because it is the number that justifies the refusal and it appears nowhere else
    -- on the panel - the Trade view's Output column is map-wide production, which is a
    -- different thing and misled a player into thinking the refusing house was the producer.
    for _, res in ipairs(EX.COMMODITIES) do
        local by = EX.refused_by(res)
        local prev = EX.log_seen[res]
        if by and by ~= prev then
            EX.log_add(EX.log_subject(res),
                EX.faction_display(by) .. " refuses to sell. It holds " .. tostring(EX.book_of(by, res))
                .. " of the guild's " .. tostring(EX.guild_book(res)) .. " lots and despises you.", res)
        elseif prev and not by then
            EX.log_add(EX.log_subject(res),
                EX.faction_display(prev) .. " will deal again.", res)
        end
        EX.log_seen[res] = by
    end
end

-- THE DEALS PAGE. Five columns and no sparkline: a deal is a thing somebody is offering now,
-- not a price history. Column x offsets are the row's plus the 20px rows_holder inset, the
-- same rule every other table here follows.
EX.PANEL_LAYOUT_DEALS = {
    { "title_text",    20,  14 },
    -- NO HEADER OVER THE BUTTON, which is the offerings view's arrangement and not an
    -- oversight: hdr_hold is the last column and btn_buy sits to the right of it, labelled.
    { "hdr_name",      54,  50, 170 },
    { "hdr_trend",    234,  50, 250 },
    { "hdr_price",    496,  50,  84 },
    { "hdr_sell",     592,  50,  84 },
    { "hdr_hold",     688,  50,  80 },
    { "rows_holder",   20,  78 },
    { "footer_text",   20, 636 },
    { "footer_text2",  20, 662 },
    { "close_button", 876,  14 },
    { "btn_help",     838,  14 },
    { "derpy_chd_ex_tab_trade", 20, 698, 108 },
    { "derpy_chd_ex_tab_stats", 136, 698, 108 },
    { "derpy_chd_ex_tab_offer", 252, 698, 108 },
    { "derpy_chd_ex_tab_houses", 368, 698, 108 },
    { "derpy_chd_ex_tab_deals", 484, 698, 108 },
    { "derpy_chd_ex_tab_log",   600, 698, 108 },
    { "derpy_chd_ex_prev", 774, 696 },
    { "nav_page",     816, 701,  44 },
    { "derpy_chd_ex_mode", 876, 696 },
}
-- THE ACCEPT BUTTON SITS WHERE THE OFFERINGS VIEW PUTS ITS OWN, at 762 in an 880 row, and
-- every column left of it moved to make the 100px. Widening the row was not an option - the
-- panel clears it by exactly 20px a side and gen_exchange_ui.py asserts that - and dropping the
-- Total column to free the space would have taken the one number the player most needs BEFORE
-- clicking off the screen. btn_buy is reused rather than a new component for the reason the
-- ledger reuses it as Cancel and the offerings view as Sacrifice: a row has two buttons in its
-- .twui.xml and no view has ever needed a third.
EX.ROW_LAYOUT_DEALS = {
    { "divider",      6, 26 },
    { "icon",         6,  2 },
    { "row_name",    34,  5, 170 },
    { "row_trend",  214,  5, 250 },
    { "row_price",  476,  5,  84 },
    { "row_sell",   572,  5,  84 },
    { "row_hold",   668,  5,  80 },
    { "btn_buy",    762,  1 },
}

EX.PANEL_LAYOUT_LOG = {
    { "title_text",    20,  14 },
    { "hdr_name",      54,  50, 200 },
    { "hdr_trend",    260,  50, 620 },
    { "rows_holder",   20,  78 },
    { "footer_text",   20, 636 },
    { "footer_text2",  20, 662 },
    { "close_button", 876,  14 },
    { "btn_help",     838,  14 },
    { "derpy_chd_ex_tab_trade", 20, 698, 108 },
    { "derpy_chd_ex_tab_stats", 136, 698, 108 },
    { "derpy_chd_ex_tab_offer", 252, 698, 108 },
    { "derpy_chd_ex_tab_houses", 368, 698, 108 },
    { "derpy_chd_ex_tab_deals", 484, 698, 108 },
    { "derpy_chd_ex_tab_log",   600, 698, 108 },
    { "derpy_chd_ex_prev", 774, 696 },
    { "nav_page",     816, 701,  44 },
    { "derpy_chd_ex_mode", 876, 696 },
}
EX.ROW_LAYOUT_LOG = {
    { "divider",      6, 26 },
    -- Same 6,2 as the trade view, so row_name stays at 34 and hdr_name at 54 keeps lining up.
    { "icon",         6,  2 },
    { "row_name",    34,  5, 200 },
    { "row_trend",  240,  5, 620 },
}

-- WHICH PAGES THE TRADE VIEW HAS, IN ORDER. A LIST AND NOT AN INDEX, and that is the whole
-- point of this function.
--
-- Until 2026-09-10 EX.on_chart tested `trade_page == 2` and EX.page_count returned
-- `deep_history and 2 or 1`. That held while there was one optional page. With two there are
-- four switch combinations and fixed indices get two of them wrong: with the chart off, the
-- orders page either sits unreachable at index 3 behind a counter reading 1/2, or index 2
-- means two different pages depending on a switch nothing at the call site can see.
--
-- THE BUFFER KEEPS RECORDING regardless of this list. EX.remember is not gated: turning the
-- chart back on after ten turns must not show a flat line for those ten, which is a false
-- reading of the market rather than a missing one. The switch takes the chart off the panel,
-- not the history out of the save.
--
-- The list is built fresh rather than memoised: both switches are live-read and unsnapshotted
-- by design, so they can move inside a campaign at any moment.
function EX.trade_pages()
    local t = { "list" }
    if EX.feature("deep_history") then t[#t + 1] = "chart" end
    if EX.feature("orders") then t[#t + 1] = "orders" end
    return t
end

-- CLAMPS RATHER THAN RETURNING NIL. A switch can be turned off while the player is standing
-- on the page it removes, and every caller here would index a nil.
function EX.trade_kind()
    local pages = EX.trade_pages()
    local at = EX.trade_page or 1
    if at < 1 then at = 1 end
    if at > #pages then at = #pages end
    return pages[at]
end

function EX.on_chart()
    return EX.mode == EX.MODE_TRADE and EX.trade_kind() == "chart"
end

function EX.on_orders()
    return EX.mode == EX.MODE_TRADE and EX.trade_kind() == "orders"
end

-- WHICH SET OF PER-VIEW TABLES APPLIES. The ledger is a PAGE of MODE_TRADE and not a mode of
-- its own, so every table keyed by EX.mode - EX.HEADERS, EX.TIPS, EX.TIP_CELL_TEXT,
-- EX.SORT_VALUE - silently handed it the Trade view's entries. That drew "Buy" over a mid
-- price on rows that are half sells and "Trend" over an order sentence, and it made a header
-- click on the ledger resolve through the trade sorter: the header coloured, the ledger's own
-- rows never moved, and page 1 was re-sorted underneath the player. ONE accessor rather than
-- four separate branches, so a fifth table keyed this way cannot miss the ledger.
function EX.view()
    if EX.on_orders() then return "orders" end
    return EX.mode
end

-- WHERE A NAME CLICK SHOULD LAND: the chart if the player has one, else the page the order
-- ticket is on, else nowhere. EX.chart_page_index alone was right only while the ticket lived
-- on the chart page and nowhere else - with deep_history off that returns nil, the click left
-- the player on the list, and the ticket they were being sent to was never reachable at all.
function EX.selection_page_index()
    local chart, orders
    for i, kind in ipairs(EX.trade_pages()) do
        if kind == "chart" then chart = i
        elseif kind == "orders" then orders = i end
    end
    return chart or orders
end

-- WHERE THE CHART SITS IN THE TRADE PAGE LIST, OR NIL. Pulled out of the row_name click so
-- the nav harness can call it directly: with the chart absent (deep_history off) a click on a
-- commodity's name must leave EX.trade_page alone rather than land on whatever page 2 happens
-- to be under that combination - a literal EX.trade_page = 2 restored at the call site passed
-- the whole suite until this existed to test it on its own.
function EX.chart_page_index()
    for i, kind in ipairs(EX.trade_pages()) do
        if kind == "chart" then return i end
    end
    return nil
end

-- EVERY PANEL-LEVEL COMPONENT ANY VIEW PLACES. Derived from the layout tables themselves,
-- so a component added to one of them is covered here without being named a second time -
-- the fault this exists to stop is exactly a component nobody remembered to hide.
--
-- BUILT ON FIRST CALL, NOT AT FILE SCOPE. PANEL_LAYOUT_OFFER and PANEL_LAYOUT_HOUSES are
-- declared roughly 1,200 lines BELOW this point, so a file-scope union would read two nils
-- and take the whole file down at load - and the tell for that is a 'Loading mod file' line
-- with no 'loaded successfully', which is the quietest failure this codebase has. The
-- memo is safe because the tables are literals that never change after load.
EX.PANEL_CELLS = nil
function EX.panel_cells()
    if EX.PANEL_CELLS then return EX.PANEL_CELLS end
    local t = {}
    -- EX.PANEL_LAYOUT_INTRO IS HERE TOO, for the same reason EX.PANEL_LAYOUT_ORDERS is: every
    -- cell name it carries (title_text, rows_holder, both footers, close_button, btn_help, the
    -- five tabs, the nav strip) is already a subset of EX.PANEL_LAYOUT's own names, so leaving
    -- it out of this list was invisible to every behavioural check in the suite - found
    -- 2026-09-10 by the static check that generalised past naming EX.PANEL_LAYOUT_ORDERS alone.
    for _, tbl in ipairs({ EX.PANEL_LAYOUT, EX.PANEL_LAYOUT_STATS, EX.PANEL_LAYOUT_OFFER,
                           EX.PANEL_LAYOUT_HOUSES, EX.PANEL_LAYOUT_LOG,
                           EX.PANEL_LAYOUT_HELP, EX.PANEL_LAYOUT_CHART,
                           EX.PANEL_LAYOUT_ORDERS, EX.PANEL_LAYOUT_INTRO,
                           EX.PANEL_LAYOUT_DEALS }) do
        for _, e in ipairs(tbl or {}) do t[e[1]] = true end
    end
    EX.PANEL_CELLS = t
    return t
end

-- DOES THE CURRENT VIEW OWN THIS CELL? EX.layout hides every cell the current table does
-- not name, and set_text calls SetVisible(true) - so an unconditional write to a cell only
-- some views carry silently un-hides it on all the others. Seen live on the Ownership view,
-- 2026-09-11: the amount button sitting on top of the Cartel premium header.
function EX.in_layout(name)
    for _, e in ipairs(EX.panel_layout() or {}) do
        if e[1] == name then return true end
    end
    return false
end

function EX.panel_layout()
    if EX.on_orders() then return EX.PANEL_LAYOUT_ORDERS end
    if EX.on_chart() then return EX.PANEL_LAYOUT_CHART end
    if EX.mode == EX.MODE_DEALS  then return EX.PANEL_LAYOUT_DEALS  end
    if EX.mode == EX.MODE_LOG    then return EX.PANEL_LAYOUT_LOG    end
    if EX.mode == EX.MODE_STATS  then return EX.PANEL_LAYOUT_STATS  end
    if EX.mode == EX.MODE_OFFER  then return EX.PANEL_LAYOUT_OFFER  end
    if EX.mode == EX.MODE_HOUSES then return EX.PANEL_LAYOUT_HOUSES end
    if EX.mode == EX.MODE_INTRO  then return EX.PANEL_LAYOUT_INTRO  end
    if EX.mode == EX.MODE_HELP   then return EX.PANEL_LAYOUT_HELP   end
    return EX.PANEL_LAYOUT
end

function EX.row_layout()
    if EX.on_orders() then return EX.ROW_LAYOUT_ORDERS end
    if EX.on_chart() then return EX.ROW_LAYOUT_CHART end
    if EX.mode == EX.MODE_DEALS  then return EX.ROW_LAYOUT_DEALS  end
    if EX.mode == EX.MODE_LOG    then return EX.ROW_LAYOUT_LOG    end
    if EX.mode == EX.MODE_STATS  then return EX.ROW_LAYOUT_STATS  end
    if EX.mode == EX.MODE_OFFER  then return EX.ROW_LAYOUT_OFFER  end
    if EX.mode == EX.MODE_HOUSES then return EX.ROW_LAYOUT_HOUSES end
    if EX.mode == EX.MODE_INTRO  then return EX.ROW_LAYOUT_INTRO  end
    if EX.mode == EX.MODE_HELP   then return EX.ROW_LAYOUT_HELP   end
    return EX.ROW_LAYOUT
end

-- Which header carries which label, per mode. Set here rather than once in build_panel, so a
-- mode switch relabels the columns along with moving them.
-- ===========================================================================================
-- COLUMN SORTING. Click a numeric header: low to high, high to low, then back to the order
-- the list already had. Asked for from play 2026-09-08.
--
-- VIEW STATE, NEVER SAVED, and cleared on every mode change - exactly like EX.help_page. A
-- column id means a different number in each view (row_price is a gold price in Trade, a
-- percentage share in Ownership and an offering cost in Offerings), so a sort carried across
-- a tab would silently re-sort on a quantity the player never clicked.
--
-- THE VALUES COME FROM THE SAME ACCESSORS THE CELLS DO. Sorting on the rendered text was the
-- shorter version and is wrong: only the visible page is ever rendered, so a paged Houses view
-- would sort twenty rows and leave the rest where they were.
EX.sort_col = nil
EX.sort_dir = 1

-- THE TREND COLUMN'S SORT KEY, and it is NOT the rung.
--
-- It was EX.current[res] - the price rung - which is a different quantity from the one the
-- column draws. EX.trend_arrow compares the rung against the PREVIOUS rung, so two rows on
-- the same rung can show opposite arrows and two rows showing the same arrow can be twenty
-- rungs apart. Sorting by rung therefore produced Hi, Hi, ^, ^, ^, ^, ^, -, v, v, v, ^, ^,
-- v, v, ^, v (screenshot, 2026-09-08): loosely grouped, visibly wrong.
--
-- A sortable column has to order rows the way it DRAWS them, so this mirrors trend_arrow's
-- own branch order: direction first, then the cap and floor cases it falls through to.
-- Hi ranks above every rise and Lo below every fall - pinned at the ceiling is the strongest
-- reading of that column, pinned at the floor the weakest.
--
-- FINITE SENTINELS, not math.huge: EX.sorted uses -math.huge for a value it could not read,
-- and a floor row is not an error. A delta cannot exceed EX.RUNGS, so RUNGS + 1 clears them.
function EX.trend_rank(res)
    local now = EX.current[res] or 0
    local was = EX.prev_rung(res) or now
    local d = now - was
    if d ~= 0 then return d end
    if now >= EX.RUNGS then return EX.RUNGS + 1 end
    if now > 0 and now <= 1 then return -(EX.RUNGS + 1) end
    return 0
end

local function sort_share(res)
    local sup = (EX.supply or {})[res]
    local _holder, held = EX.top_holder(res)
    if not sup or sup <= 0 or not held then return -1 end
    return held * 100 / sup
end

-- Only columns holding a NUMBER. hdr_name is a word, hdr_spark is a chart, and the Ownership
-- view's hdr_trend is a faction name - a header with no entry here simply does not respond to
-- a click, which is the right answer for a column with nothing to order by.
EX.SORT_VALUE = {
    trade = {
        hdr_price  = function(r) return EX.buy_price(r) end,
        hdr_sell   = function(r) return EX.sell_price(r) end,
        hdr_supply = function(r) return (EX.supply or {})[r] or -1 end,
        hdr_trend  = EX.trend_rank,
        hdr_hold   = function(r) return EX.held(r) end,
    },
    stats = {
        hdr_supply = function(r) return (EX.supply or {})[r] or -1 end,
        hdr_price  = sort_share,
        hdr_hold   = function(r) return EX.premium(r) or -1e9 end,
    },
    offer = {
        hdr_supply = function(r) return EX.held(r) end,
    },
    houses = {
        -- THE ONLY NON-NUMERIC SORTER IN THIS TABLE. EX.sorted grew a string branch for it;
        -- see the note there. Wrapped rather than referenced, so it resolves at CALL time -
        -- EX.faction_display is defined twice in this file and a captured reference would
        -- bind whichever came first.
        --
        -- EX.faction_display memoises into EX.fac_names and cannot throw (it pcalls
        -- common.get_localised_string and falls back to EX.humanise_key), so sorting a hundred
        -- rows about once a second costs one table lookup each after the first refresh. It is
        -- also draw-time, which is the only time a loc call is safe - see the turn-1 CTD note.
        hdr_name   = function(r) return EX.faction_display(r) end,
        hdr_price  = function(r) return EX.buy_price(r) end,
        hdr_sell   = function(r) return EX.dividend(r) end,
        hdr_hold   = function(r) return EX.held(r) end,
        hdr_trend  = EX.trend_rank,
    },
}

function EX.sort_fn(hid)
    -- EX.view(), NOT EX.mode. The ledger has no entry in EX.SORT_VALUE and that is the point:
    -- its rows are the order list in placement order, and a header click resolving through the
    -- trade sorter coloured the header, left the ledger unchanged and re-sorted page 1.
    local m = EX.SORT_VALUE[EX.view()]
    return (m and hid) and m[hid] or nil
end

-- TIEBROKEN ON THE ORIGINAL INDEX. table.sort is not stable in Lua 5.1, and every one of these
-- columns has ties in it (four commodities on the same rung, eleven houses paying the same
-- dividend). Without the tiebreak those rows reshuffle on every refresh_panel - once a second
-- while the panel is open - which reads as the panel being broken rather than sorted.
--
-- A comparator that ERRORS takes the whole refresh down, so the value is pcall'd and anything
-- that is not a number sorts to the bottom rather than throwing.
function EX.sorted(list)
    local f = EX.sort_fn(EX.sort_col)
    if not f then return list end
    local keyed = {}
    for i, r in ipairs(list) do
        local ok, v = pcall(f, r)
        local t = type(v)
        -- STRINGS ARE ACCEPTED SINCE 2026-09-11, for the Houses view's name column. Everything
        -- else here still hands back a number and is untouched.
        keyed[i] = { r = r, i = i,
                     v = (ok and (t == "number" or t == "string")) and v or -math.huge }
    end
    table.sort(keyed, function(a, b)
        if a.v ~= b.v then
            -- MIXED TYPES ONLY ARISE WHEN AN ACCESSOR ERRORED. One column has one accessor, so
            -- every good value in it is the same type and the -math.huge fallback above is the
            -- only other thing in the table. Lua 5.1 THROWS on `number < string`, and a throw
            -- inside table.sort takes the whole refresh down - so this branch is load-bearing
            -- rather than defensive. The errored row sinks in BOTH directions instead of
            -- floating to the top of a descending sort.
            if type(a.v) ~= type(b.v) then return type(a.v) == "string" end
            return (a.v < b.v) == (EX.sort_dir > 0)
        end
        return a.i < b.i
    end)
    local out = {}
    for i, e in ipairs(keyed) do out[i] = e.r end
    return out
end

-- Returns true if the click WAS a sort, so the listener knows to stop there.
function EX.sort_click(hid)
    if not EX.sort_fn(hid) then return false end
    if EX.sort_col ~= hid then
        EX.sort_col, EX.sort_dir = hid, 1
    elseif EX.sort_dir == 1 then
        EX.sort_dir = -1
    else
        EX.sort_col, EX.sort_dir = nil, 1
    end
    -- BACK TO PAGE 1. Re-sorting a paged list while the player sits on page 2 shows them the
    -- middle of the new order, which is the one part of it that means nothing.
    if EX.mode == EX.MODE_HOUSES then EX.house_page = 1 end
    -- EX.layout AND refresh_panel, the same pair EX.set_mode uses. The header tooltip carries
    -- the sort direction and what the next click does, and EX.apply_tips runs from layout
    -- only - refresh_panel alone would leave it describing the sort just clicked away from.
    EX.layout()
    EX.refresh_panel()
    return true
end

-- WHICH COLUMN IS SORTED, SAID IN COLOUR RATHER THAN IN AN ARROW.
--
-- The obvious version appends " ^" / " v" to the label. It is refused: check_header_labels()
-- measures every label against its box out of HEADER_LABEL_PX, a table of LIVE
-- TextDimensionsForText readings, and refuses any string that has never been measured -
-- because a 38px "Trend" once went into a 36px box on a character-count estimate and drew
-- "Tr..." on screen. Two more characters on fifteen labels is fifteen measurements nobody has
-- taken, and the failure mode is a silently clipped header.
--
-- Colour markup changes no width at all - [[col:...]] is a resolver directive, not glyphs -
-- so the box arithmetic that already passed still holds, and the same green/red pair the
-- trend column uses reads as up/down here for the same reason it does there.
--
-- ponytail: colour marks the column, the tooltip names the direction. An arrow is the nicer
-- affordance and is a two-line change once someone measures the fifteen labels with the arrow
-- on them against a live panel.
function EX.sort_mark(hid, label)
    if EX.sort_col ~= hid then return label end
    -- BOTH TAGS SPELLED OUT, not built by concatenating the colour name in. check_trend_colours
    -- counts literal "[[col:" against literal "[[/col]]" and a composed open tag reads as an
    -- unclosed one; and a colour name that is not one of CA's 42 silently drops the colour
    -- rather than erroring, so a literal is the only spelling anything can check.
    if EX.sort_dir > 0 then return "[[col:green]]" .. label .. "[[/col]]" end
    return "[[col:red]]" .. label .. "[[/col]]"
end

-- What the header's tooltip gains once a column can be clicked: which way it is sorted now,
-- and what the next click does. A control that responds to a click and says nothing about it
-- is the live-looking-dead-control fault this file condemns twice elsewhere.
function EX.sort_tip(hid)
    if not EX.sort_fn(hid) then return "" end
    if EX.sort_col ~= hid then return "||Click to sort this column low to high." end
    if EX.sort_dir > 0 then
        return "||Sorted low to high. Click again for high to low."
    end
    return "||Sorted high to low. Click again for the default order."
end

EX.HEADERS = {
    -- "Regions", NOT "Supply", and the stats view calls the same number the same thing.
    -- Reported 2026-09-05: "i always thought supply is the amount of stocks that you can buy
    -- not the region". It is a region count and buying never consumes it, so the word invited
    -- exactly the wrong model - and the panel taught it, having called one number "Supply" here
    -- and "Regions" two lines down. Depth exists, but it is EX.pressure moving the price, not a
    -- stock draining. If a real per-turn stock is ever wanted, that is a new field, not a
    -- relabel of this one.
    -- "Output", not "Regions" and no longer "Supply". It is now units produced across the
    -- whole map per turn - a real quantity, which "Regions" no longer described and "Supply"
    -- had already been read as purchasable stock (reported 2026-09-05). Buying still does not
    -- consume it; what moves the price against it is EX.pressure.
    -- "Buy" and "Sell", not "Price" and "Sell": with both numbers on screen, one column called
    -- "Price" would leave the player to work out which side of the spread it is.
    trade = { hdr_name = "Commodity", hdr_price = "Buy", hdr_sell = "Sell",
              hdr_supply = "Output",
              hdr_trend = "Trend", hdr_spark = "Last " .. EX.SPARK_BARS .. " turns",
              -- "Held / rent", not "Held": the cell prints "300  -150g" and nothing on the
              -- panel said what the second number was. Asked for from play 2026-09-06.
              -- The footer calls the same charge "Rent" - one number, one name.
              hdr_hold = "Held / rent" },
    stats = { hdr_name = "Commodity", hdr_supply = "Output", hdr_trend = "Largest producer",
              hdr_price = "Share", hdr_hold = "Cartel premium",
              hdr_spark = "Last " .. EX.SPARK_BARS .. " turns" },
    -- hdr_spark is absent: the offerings view has no sparkline, and EX.layout hides any cell
    -- this mode does not place. Every id here still has to exist in EX.HEADERS.trade, which is
    -- what the hide loop iterates.
    offer = { hdr_name = "Commodity", hdr_supply = "Held", hdr_price = "Cost",
              hdr_trend = "Hashut grants", hdr_hold = "Status" },  -- patron-literal: rewritten by EX.bind_race
    -- THE FOURTH VIEW, RELABELLED THROUGH THIS TABLE like every other view. hdr_sell reads
    -- "Div" and hdr_supply reads "Seat" here, because those cells carry the dividend and the
    -- seat state in this mode - exactly the mechanism Stats uses to call hdr_price "Share" and
    -- Offer uses to call hdr_supply "Held".
    --
    -- IT SHIPPED THE OTHER WAY FIRST: hdr_div and hdr_seat as components of their own, on the
    -- argument that a table mapping "hdr_sell" to a dividend column is surprising. That bought
    -- two GUIDs, two EX.HEADERS.trade entries that existed only to feed the hide loop, two
    -- EX.TIPS.trade entries that existed only to satisfy check_tooltips - and a bug, because
    -- EX.TIP_CELL then mapped BOTH hdr_div and hdr_sell onto row_sell and EX.apply_tips walks
    -- pairs(): the trade view's sell column answered with one of the two tooltips at random.
    houses = { hdr_name = "House", hdr_price = "Price", hdr_sell = "Div", hdr_supply = "Seat",
               hdr_trend = "Trend", hdr_spark = "Last " .. EX.SPARK_BARS .. " turns",
               hdr_hold = "Held" },
    -- Two columns only. Every other cell is hidden by EX.layout because ROW_LAYOUT_HELP does
    -- not name it, and both ids used here exist in .trade, which is what the hide loop walks.
    help = { hdr_name = "Term", hdr_trend = "What it means" },
    -- THE LOG, same two-column shape as the guide. This entry is not decoration: refresh_panel
    -- walks pairs(EX.HEADERS[EX.mode]) BEFORE it branches on the mode, so a view in EX.MODES
    -- with no entry here indexes nil and takes the whole refresh down the first time the
    -- player's arrow reaches it. Caught by gen_exchange_ui.py --selftest, never in play.
    -- THE DEALS PAGE. Five columns, no sparkline. hdr_trend carries the offer as a SENTENCE
    -- ("Buys 3 lots of Iron") rather than three narrow columns for side, size and commodity -
    -- the same trick the ledger uses for a standing order, and it reads at a glance.
    deals = { hdr_name = "Faction", hdr_trend = "Offer", hdr_price = "Per lot",
              hdr_sell = "vs market", hdr_hold = "Total" },
    log = { hdr_name = "Turn", hdr_trend = "What happened" },
    -- EMPTY, NOT ABSENT, and the comment above the log entry says why: refresh_panel
    -- walks pairs(EX.HEADERS[EX.mode]) before it branches on the mode. The introduction
    -- draws prose across one column and heads nothing.
    -- THE LEDGER, reached through EX.view() rather than EX.mode - it is a PAGE of the Trade
    -- view, so every table keyed by the mode handed it Trade's labels: "Trend" over an order
    -- sentence and "Buy" over a price on rows that are half sells.
    orders = { hdr_name = "Commodity", hdr_trend = "Standing order", hdr_price = "Now" },
    intro = {},
}

-- TOOLTIPS. One string per COLUMN, put on the header AND on every row cell under it - "what
-- am I looking at" has the same answer either way, and the player asking it hovers whichever
-- of the two the cursor is already near. Asked for from play 2026-09-06, after "what does Hi
-- mean in the trend column": the guide view had the answer and nothing on the row pointed at
-- it.
--
-- SET AT RUNTIME, not as a componentleveltooltip in the .twui.xml, though the XML route is
-- what this panel's six buttons use. The cells are REUSED between modes - row_price is a gold
-- price in the trade view, a percentage share in the ownership view and an offering cost in
-- the offerings view - so one static attribute cannot be true in all three.
--
-- INTERACTIVE, BECAUSE A TOOLTIP ON A DEAD COMPONENT IS NEVER REACHED. Counted in ui3.pack:
-- 1,670 of CA's 1,747 componentleveltooltips sit on an element that declares
-- interactive="true", and of the 77 that do not several are placeholders ("[PH] This unit
-- is...", "r5tyrtu ty dsfdfsdgfgdsfgregfe"). These cells are not clickable and do not become
-- so; interactive here buys hover and nothing else.
--
-- EVERY STRING IS UNDER 60 CHARACTERS, so none of them needs CA's "Title||Body" split - which
-- is only ever been proven to work as literal XML, never through SetTooltipText. CA's own
-- literal tooltips that skip the split run to a median of 42 characters, which is this band.
-- check_tooltips() enforces the ceiling.
EX.TIP_MAX = 60
-- ONE HEADER PER CELL, PER MODE, and check_tooltips() now enforces it. Two headers pointing at
-- one cell is not a wrong tooltip, it is a NONDETERMINISTIC one: EX.apply_tips walks
-- pairs(tips) and writes each header's text onto its cell, and Lua 5.1 does not define that
-- order. hdr_div -> row_sell beside hdr_sell -> row_sell shipped exactly that.
EX.TIP_CELL = {
    hdr_name   = "row_name",   hdr_price = "row_price", hdr_sell = "row_sell",
    hdr_supply = "row_supply", hdr_trend = "row_trend", hdr_spark = "spark",
    hdr_hold   = "row_hold",
}

-- WHERE A CELL'S TOOLTIP MUST DIFFER FROM ITS COLUMN'S. Only one does: the name cell is
-- clickable and the header is not, and "Click to chart it" on a column header would be a
-- lie. Appending to the column tip instead is not an option - hdr_name is already 49
-- characters and the ceiling is 60, above which a tooltip needs CA's Title||Body split,
-- which has only ever been proven to work as literal XML and never through SetTooltipText.
--
-- The cell was ALREADY interactive before the chart existed, because set_tip ties
-- SetInteractive to having text and every row cell has carried its column's tooltip since
-- 2026-09-08. So this buys discoverability, not the click itself.
EX.TIP_CELL_TEXT = {
    trade = { hdr_name = "Click to chart this commodity's price." },
}
-- Keyed by header id and by mode, exactly like EX.HEADERS - the two are checked against each
-- other, so a column that gains a label without a tooltip is a build error. The guide view is
-- deliberately absent: it is already prose, and a tooltip explaining an explanation is noise.
EX.TIPS = {
    -- THE LEDGER. Its three columns mean something different from the Trade view's, which is
    -- why it needs its own entry and not Trade's - and "Now" in particular is the price on
    -- THIS order's side, so the tooltip has to say which side that is.
    orders = {
        hdr_name  = "The instrument this order stands on.",
        hdr_trend = "What the order does, and the price it fills at.",
        hdr_price = "What one lot is worth now, on this order's own side.",
    },
    deals = {
        hdr_name   = "Who is offering. The deal settles with them.",
        hdr_trend  = "What they offer, and how many lots of it.",
        hdr_price  = "Gold per lot. This is the price you pay or get.",
        hdr_sell   = "How far off today's market that price is.",
        hdr_hold   = "Every lot of the deal, at that price.",
    },
    trade = {
        hdr_name   = "The commodity. Its icon matches the map resource.",
        hdr_price  = "Gold to buy one lot at today's price.",
        hdr_sell   = "What one lot pays back, always under Buy.",
        hdr_supply = "Units the whole map produces per turn.",
        hdr_trend  = "^ up, v down, - held. Hi/Lo: at the ladder's limit.",
        hdr_spark  = "This good's price, one bar per turn. Taller costs more.",
        hdr_hold   = "Units you hold, and the rent they cost per turn.",
    },
    stats = {
        hdr_name   = "The commodity. Its icon matches the map resource.",
        hdr_supply = "Units the whole map produces per turn.",
        hdr_trend  = "The faction producing most of the world's supply.",
        hdr_price  = "How much of world output that faction holds.",
        hdr_hold   = "Gold on the price because output is concentrated.",
        hdr_spark  = "This good's price, one bar per turn. Taller costs more.",
    },
    offer = {
        hdr_name   = "The commodity. Its icon matches the map resource.",
        hdr_supply = "Units you hold. An offering is paid out of these.",
        hdr_price  = "Units burned to make an offering. They are gone.",
        hdr_trend  = "What Hashut grants while the offering lasts.",  -- patron-literal: rewritten by EX.bind_race
        hdr_hold   = "Ready, turns of favour left, or units still needed.",
    },
    -- THE TWO COLUMNS SIT SIDE BY SIDE IN DIFFERENT UNITS, so both name their unit. Price is
    -- per LOT - EX.trade charges EX.price(res) and hands over EX.HOUSE_LOT_SIZE shares - while
    -- the dividend is per SHARE, because that is what EX.dividend_total multiplies. (EX.trade
    -- actually charges EX.buy_price(res); it equals EX.price(res) here ONLY because
    -- EX.hostility(res) is hardcoded to 0 for any EX.is_house(res) instrument - a future
    -- house-hostility task must update this comment too.) The first
    -- of these read "Gold to buy one share at today's price", which was wrong by a factor of
    -- five and sat one column from the number that made it look right. The literal 5 is
    -- EX.HOUSE_LOT_SIZE and check_tooltips() pins the two together - these strings are read
    -- straight by SetTooltipText and cannot be a concatenation.
    houses = {
        hdr_name  = "A trading house. Its capital backs its share price.",
        hdr_price = "Gold for one lot: 5 shares at today's price.",
        hdr_sell  = "Gold per share each turn. Price above is for 5 shares.",
        hdr_supply = "Held: safe. LOST: taken. Horde: no capital to lose.",
        hdr_trend = "^ up, v down, - held. Hi/Lo: at the ladder's limit.",
        hdr_spark = "This house's price, one bar per turn. Taller costs more.",
        hdr_hold  = "Shares you hold, and the dividend they pay this turn.",
    },
}

-- THE PER-COMMODITY MARKUP TOOLTIP. EX.TIPS.trade.hdr_price/hdr_sell above are the same string
-- on every row; this is the one thing on the panel that varies BY ROW, because EX.hostility
-- does. Built fresh every refresh_panel, not just on layout/mode-switch, since a trade or a
-- treaty can move it turn to turn - see EX.refresh_panel's trade branch for the call site.
--
-- STARTS FROM THE STATIC TIP and appends via CA's "Title||Body" split rather than a plain
-- concatenation: EX.TIP_MAX=60 exists specifically so the static column tips never need that
-- split, but this one is open-ended once a house's display name is in it, so it is the one
-- tooltip on the panel that does use ||. Both sides are literal text built here, never a loc
-- key - a bare loc key through this route would draw the pipes as characters.
-- THE SAME TWO CAUSES, AND THE SAME RULE AS EX.buy_refusal: a shut market is not a house
-- refusing you. This read EX.blocked and phrased either as "<house> will not sell to you",
-- which is how the war lock came to accuse one named house on every row of the board. Fixed in
-- buy_refusal first and missed here, because the grep was for callers of buy_refusal when it
-- should have been for callers of EX.blocked - there were three.
function EX.buy_tip(res)
    local t = EX.TIPS.trade.hdr_price
    local closed = EX.market_closed()
    local by = not closed and EX.refused_by(res) or nil
    if closed then
        t = t .. "||The Exchange is shut: too much of the guild is at war with you."
    elseif by then
        t = t .. "||" .. EX.faction_display(by) .. " will not sell to you."
    else
        local h = EX.hostility(res)
        if h ~= 0 then
            local cp = EX.hostility_source(res)
            t = t .. "||" .. (cp and EX.faction_display(cp) or "The guild")
                  .. (h > 0 and " holds this and dislikes you: +"
                             or " holds this and likes you: -")
                  -- EX.markup_pct, NOT the raw hostility. See the note on EX.sell_tip.
                  .. EX.markup_pct(res, true) .. "%."
        end
    end
    return t
end

-- THE HELD CELL, PER ROW: how far this pile is up the stockpile ladder and what the next
-- level costs to reach. The cell only colours green once a level is reached, so a player at
-- 240 Iron had no way to see they were 60 short of doubling it. Level 2 is what an offering
-- grants (OFFER_MULT is 2), which is the one level EX.boon's figure describes exactly.
-- The rent clause follows EX.charge_carry's own switch, not EX.carry_cost's.
function EX.hold_tip(res)
    local t = EX.TIPS.trade.hdr_hold
    if EX.is_layer2(res) or EX.is_house(res) then return t end
    local held = EX.held(res)
    local tier = EX.stock_tier(held)
    local n = #EX.STOCK_TIERS
    local body
    if tier == 0 then
        body = "No stockpile bonus yet: " .. (EX.STOCK_TIERS[1] - held) .. " more for level 1 of "
            .. n .. "."
    elseif tier < n then
        body = "Stockpile bonus, level " .. tier .. " of " .. n .. ". "
            .. (EX.STOCK_TIERS[tier + 1] - held) .. " more for level " .. (tier + 1) .. "."
    else
        body = "Stockpile bonus, level " .. n .. " of " .. n .. ": the most there is."
    end
    local boon = EX.boon(res)
    if boon then body = body .. " Level 2 grants " .. boon .. "." end
    local rent = EX.carry_cost(res)
    if rent > 0 and EX.setting("warehouse_rent") then
        body = body .. " Rent " .. rent .. "g a turn."
    end
    return t .. "||" .. body
end

function EX.sell_tip(res)
    local t = EX.TIPS.trade.hdr_sell
    local h = EX.hostility(res)
    if h ~= 0 then
        local cp = EX.hostility_source(res)
        -- EX.markup_pct, NOT math.floor(h * 100 + 0.5). REPORTED FROM A SCREENSHOT
        -- 2026-09-08: the cell read -11% and this tooltip read 10%, on the same row, for the
        -- same trade. Both numbers were defensible and that is the problem - the RAW
        -- hostility is 10%, but what the sell price actually loses is measured against the
        -- sell base (1 - spread), so 0.10 / 0.90 = 11.1%. markup_pct is the realised figure
        -- and the one the cell has always drawn; it also respects the sell floor, which the
        -- raw number does not. One number, one source.
        t = t .. "||" .. (cp and EX.faction_display(cp) or "The guild")
              .. (h > 0 and " holds this and dislikes you: pays you "
                         or " holds this and likes you: pays you ")
              .. EX.markup_pct(res, false)
              .. (h > 0 and "% less." or "% more.")
    end
    return t
end

local function set_tip(c, text)
    if not is_uicomponent(c) then return end
    -- true = write it to ALL states, so a cell that changes state still answers. Two-argument
    -- SetTooltipText(text, all_states) is the form 45+ call sites across the installed mods
    -- use; the binding dispatches on the second argument's type.
    c:SetTooltipText(text, true)
    -- THE EMPTY STRING IS A CLEAR, so it has to hand the hover back as well. A cell left
    -- interactive with no text still swallows the mouse from whatever is drawn under it.
    c:SetInteractive(text ~= "")
end

-- GREYED, AND SEEN TO BE. SetDisabled only stops the click - CA: "Disabled uicomponents do not
-- respond to mouse clicks but still respond to the mouse cursor" - and the look comes from the
-- component's states, and none of ours has an inactive one. So every disabled button in this
-- file drew exactly like a live one: "No offer", the current tab, a Sell with nothing held
-- (screenshot, 2026-09-25). CA's documented set_greyscale_t0 ("Greyscale & Alpha": greyscale
-- 0 to 1, alpha 0 to 1), on ALL states and the text, so hovering does not bring the colour
-- back. EVERY SetDisabled in this file goes through here; check_lua_books fails on any other.
-- pcall: a shader the engine refuses must not take the refresh down with it.
function EX.set_off(c, off)
    if not is_uicomponent(c) then return end
    off = off and true or false
    c:SetDisabled(off)
    pcall(function()
        c:ShaderTechniqueSet(off and "set_greyscale_t0" or "normal_t0", true, true)
        if off then c:ShaderVarsSet(1, 0.6, 0, 0, true, true) end
    end)
end

-- Called from EX.layout, which runs on panel build and on every mode switch. NOT from
-- refresh_panel: a tooltip describes the column, not the number in it, so nothing a trade
-- changes can make one stale.
--
-- A MODE WITH NO TIPS CLEARS THE CELLS - IT DOES NOT SKIP THEM. The row cells are reused
-- between views, so returning early here leaves the LAST view's tooltip sitting on them. That
-- shipped: the Log view's "What happened" column answered with the Houses view's trend legend,
-- "^ up, v down, - held. Hi/Lo: at the ladder's limit.", over the line "Delisted. The house is
-- gone." (from play 2026-09-08). Log and the guide are both deliberately absent from EX.TIPS,
-- so this clear is the only thing keeping either of them silent. Walk EX.TIP_CELL, not the
-- mode's own tips, or a column this view happens not to explain is never written at all.
function EX.apply_tips(panel, holder)
    local tips = EX.TIPS[EX.view()] or {}
    for hid in pairs(EX.TIP_CELL) do
        local t = tips[hid] or ""
        -- ONLY ON A COLUMN THAT HAS ONE. An empty base tip would leave the sort line leading
        -- with "||", and a pipe split with no literal text in front of it draws the pipes -
        -- see the note on EX.buy_refusal's tooltip.
        if t ~= "" then t = t .. EX.sort_tip(hid) end
        set_tip(find_uicomponent(panel, hid), t)
    end
    -- EVERY ROW, not just the ones this view draws - for the same reason the header loop walks
    -- EX.TIP_CELL. A row this view leaves hidden still holds whatever was last written to it,
    -- and it only takes one view showing it again for that to surface; the rows are shared
    -- across views exactly as the cells are. What the view does NOT draw gets the empty
    -- string, which set_tip also takes the hover back on.
    local drawn = {}
    for _, res in ipairs(EX.mode_instruments()) do drawn[res] = true end
    for _, res in ipairs(EX.instruments()) do
        local row = EX.row(holder, res)
        if is_uicomponent(row) then
            local over = EX.TIP_CELL_TEXT[EX.view()] or {}
            for hid, cell in pairs(EX.TIP_CELL) do
                set_tip(find_uicomponent(row, cell),
                        drawn[res] and (over[hid] or tips[hid]) or "")
            end
        end
    end
end


-- Place one layout table's entries relative to (ox, oy). Entry 4, where present, is a width:
-- text clips to its component, so a cell reused across modes has to be resized as well as
-- moved. SetCanResizeWidth is the horizontal twin of the SetCanResizeHeight the sparkline bars
-- already use.
-- Every cell a row owns. place() shows the ones this mode lists; EX.layout hides the rest.
EX.ROW_CELLS = { "divider", "icon", "row_name", "row_price", "row_sell", "row_supply",
                 "row_trend", "spark", "row_hold", "btn_buy", "btn_sell" }

-- Every entry goes through EX.grow first: the table is the 1600x900 end, and this places it
-- at the current box.
local function place(parent, tbl, ox, oy)
    local chart = (tbl == EX.PANEL_LAYOUT_CHART)
    for _, e in ipairs(tbl) do
        local c = find_uicomponent(parent, e[1])
        if is_uicomponent(c) then
            local x, y, w = EX.grow(e, chart)
            if w then
                local _, ch = c:Dimensions()
                c:SetCanResizeWidth(true)
                c:Resize(w, ch)
            end
            c:MoveTo(ox + x, oy + y)
            c:SetVisible(true)
        end
    end
end

function EX.layout()
    local sw, sh = EX.screen()
    -- Last attempt by construction: retry() refuses at >= EX.PLACE_TRIES, so a bad read
    -- here is ignored rather than starting a second chain alongside the first tick's.
    EX.place_button(EX.PLACE_TRIES)
    local panel = EX.panel()
    if not is_uicomponent(panel) then return end
    -- THE PANEL'S SIZE IS COMPUTED, NEVER READ BACK (2026-09-24): EX.fit sizes it for this
    -- screen and it is centred on that number. It used to be read with Dimensions() - never
    -- Bounds(), which is the union of the panel and every row MoveTo'd over it.
    --
    -- The screen half is the one that was actually mis-centring this panel at start: it asked
    -- root:Bounds(), which during load reports bigger than the display, so the panel centred
    -- inside a screen that does not exist and landed low and to the right. See EX.screen().
    local box, pw, ph, rows = EX.fit(sw, sh)
    panel:SetCanResizeWidth(true)
    panel:SetCanResizeHeight(true)
    -- false: WITHOUT ITS CHILDREN. CA's Resize resizes them too by default, which would
    -- stretch every cell place() gives no width - close, help, Buy/Sell, the icons - by the
    -- same factor, and nothing would put them back (review, 2026-09-24).
    panel:Resize(pw, ph, false)
    panel:MoveTo(math.floor((sw - pw) / 2), math.floor((sh - ph) / 2))
    -- ONCE PER CHANGE, not per pass: EX.layout runs on every tab click.
    local fit = "box " .. box .. " on a " .. sw .. "x" .. sh .. " screen, panel " .. pw .. "x"
        .. ph .. ", " .. rows .. " rows a page"
    if fit ~= EX.fit_said then
        EX.fit_said = fit
        EX.say("ui", fit)
    end
    local px, py = panel:Position()
    place(panel, EX.panel_layout(), px, py)

    -- WRITTEN HERE, not in refresh_panel: this label changes with the VIEW and with nothing
    -- else, and EX.layout is the one function that runs on both a panel build and a view
    -- change. nav_page carries no hover state, so a plain SetStateText reaches every state
    -- it has (see EX.TWO_STATE_CELLS for the cells where that is not true).
    local nav = find_uicomponent(panel, EX.NAV_PAGE)
    if is_uicomponent(nav) then nav:SetStateText(EX.nav_label()) end

    -- ANY PANEL-LEVEL COMPONENT THIS VIEW DOES NOT NAME IS TAKEN OFF SCREEN. A component
    -- that is never placed keeps whatever coordinates it was last given - or, if it has
    -- never been placed at all, the dock offset in the .twui.xml - and draws there over
    -- whatever the current view put in that space. It is the same rule EX.ROW_CELLS
    -- enforces one level down and the rows loop enforces one level up.
    --
    -- THIS USED TO WALK EX.HEADERS.trade AND NOTHING ELSE, which covered the seven column
    -- headers and no other panel child. It held only because every panel-level component
    -- that existed was either a header or in every layout table. The deep chart broke that
    -- the day it arrived: `chart`, its forty bars and its four labels are named ONLY by
    -- PANEL_LAYOUT_CHART, so on page 1 they were never placed, never hidden, and drew at
    -- their XML dock offsets straight across the commodity list. Screenshotted 2026-09-09.
    local placed = {}
    for _, e in ipairs(EX.panel_layout()) do placed[e[1]] = true end
    for id, _ in pairs(EX.panel_cells()) do
        if not placed[id] then
            local c = find_uicomponent(panel, id)
            if is_uicomponent(c) then c:SetVisible(false) end
        end
    end

    local holder = find_uicomponent(panel, "rows_holder")
    if not is_uicomponent(holder) then return end
    local hx, hy = holder:Position()
    -- THE HOLDER AND EVERY ROW SPAN THE WIDENED ROW. Nothing is drawn on either, but a parent
    -- narrower than the children placed across it is not a shape to leave the engine to
    -- interpret. 880 and 40 are ROW_W and ROW_H in tools/gen_exchange_ui.py.
    holder:SetCanResizeWidth(true)
    holder:SetCanResizeHeight(true)
    holder:Resize(EX.sc(880), EX.MAX_ROWS * EX.ROW_PITCH, false)
    local rl = EX.row_layout()
    local shown = {}
    for _, e in ipairs(rl) do shown[e[1]] = true end
    -- ONE ROW COMPONENT PER INSTRUMENT EXISTS; THIS MODE DRAWS A SUBSET. A row this view does
    -- not list has to be taken off screen, not merely left unplaced - an unplaced row keeps the
    -- last view's coordinates and draws over whatever the new one put there. Exactly the rule
    -- EX.ROW_CELLS enforces one level down for cells, and the reason the Houses view used to
    -- open on 19 commodity rows with the houses themselves below the panel's bottom edge.
    -- THE LIST IS THE ORDER, NOT JUST THE MEMBERSHIP. This loop used to walk
    -- EX.instruments() - the canonical list - and use mode_instruments() as a set to decide
    -- which rows to show. That draws every view in canonical order whatever the list says,
    -- which is why column sorting changed the header colour and nothing else (reported from a
    -- screenshot 2026-09-08: Buy marked green, rows still 583, 1851, 972, 3700).
    --
    -- Two passes, and they cannot be merged: the hide pass must cover EVERY instrument, not
    -- only the ones this view lists, because a row this view does not draw keeps the last
    -- view's coordinates and draws over whatever the new one put there - the fault that put
    -- 19 commodity rows on top of the Houses view.
    local list = EX.mode_instruments()
    local draw = {}
    local keep = {}
    for _, res in ipairs(list) do
        draw[res] = true
        keep[EX.ROW .. "_" .. EX.short(res)] = true
    end
    -- HIDE BY WALKING THE COMPONENTS THAT EXIST, not the instrument list.
    --
    -- Walking EX.instruments() only ever reaches rows the mod still knows about, and
    -- EX.prune_houses REMOVES a delisted house from EX.houses at turn start - so the moment a
    -- house is pruned its row component leaves the instrument list, the hide pass stops
    -- reaching it, and it stays visible at wherever the last layout put it, drawing on top of
    -- whatever the new pass puts there. Reported from a screenshot 2026-09-08: 22 names in 20
    -- slots on the Houses view, two pairs overlapping. Reproduced in _layout_harness.lua -
    -- 23 visible rows and 3 clashes after a prune - and it survived a view change too, so
    -- stale house rows were landing on the Trade view's commodity rows as well.
    --
    -- The holder's children ARE the truth about what can be on screen. ChildCount/Find is
    -- CA's own enumeration and is already used elsewhere in this pack.
    local n = 0
    pcall(function() n = holder:ChildCount() end)
    for j = 0, n - 1 do
        local ok, child = pcall(function() return UIComponent(holder:Find(j)) end)
        if ok and is_uicomponent(child) then
            local id = child:Id()
            if string.sub(id, 1, #EX.ROW) == EX.ROW and not keep[id] then
                child:SetVisible(false)
            end
        end
    end
    local i = 0
    for _, res in ipairs(list) do
        local row = EX.row(holder, res)
        if is_uicomponent(row) then
            do
                local rx, ry = hx, hy + i * EX.ROW_PITCH
                row:MoveTo(rx, ry)
                row:SetCanResizeWidth(true)
                row:Resize(EX.sc(880), 40, false)
                row:SetVisible(true)
                place(row, rl, rx, ry)
                -- ANY cell this mode does not place must be hidden, not just the buttons: an
                -- unplaced component keeps its last position and would sit on top of whatever
                -- the new mode put there. Started life as a btn_buy/btn_sell special case and
                -- had to grow the moment the offerings view dropped the sparkline too.
                for _, b in ipairs(EX.ROW_CELLS) do
                    if not shown[b] then
                        local c = find_uicomponent(row, b)
                        if is_uicomponent(c) then c:SetVisible(false) end
                    end
                end
                i = i + 1
            end
        end
    end

    -- LAST, after every cell is placed and the unplaced ones hidden: a hidden cell would
    -- otherwise be made interactive and could take hover from whatever is drawn over it.
    EX.apply_tips(panel, holder)
end

-- WHICH CELLS CARRY A HOVER STATE. Must match the components given hover=... in
-- tools/gen_exchange_ui.py; its selftest asserts every interactive component has one, and this
-- generator's check_lua_hover() asserts the two lists agree. They are the only cells that both
-- light on mouseover AND carry a label the script rewrites.
EX.TWO_STATE_CELLS = { btn_buy = true, btn_sell = true,
                      ord_side = true, ord_cmp = true, ord_down = true, ord_up = true,
                      ord_place = true,
                      -- The two amount buttons carry a live number as their label, so the
                      -- hover state going stale would show the wrong size to the one player
                      -- most likely to be looking - the one with the pointer on it.
                      btn_amount = true, ord_qty = true,
                      btn_amt_down = true, btn_amt_up = true,
                      ord_qty_down = true, ord_qty_up = true }
-- THE TABS ARE BUTTONS TOO, so they belong here - a label written to one state only vanishes
-- the instant the mouse is over it. FILLED FROM EX.MODES rather than listed: a sixth view
-- would otherwise add a tab whose label disappears on hover and nothing but a screenshot
-- taken with the pointer on it would ever show that.
for _, m in ipairs(EX.MODES) do EX.TWO_STATE_CELLS[EX.tab_name(m)] = true end

local function set_text(parent, child, text)
    local c = find_uicomponent(parent, child)
    if not is_uicomponent(c) then return end
    c:SetVisible(true)
    if not EX.TWO_STATE_CELLS[child] then
        c:SetStateText(text)
        return
    end
    -- SetStateText WRITES TO THE CURRENT STATE ONLY - CA documents it in exactly those words -
    -- so a button that also has a hover state keeps whatever label that state was authored
    -- with, which is nothing. The effect is a Buy button whose text vanishes the instant the
    -- mouse arrives and comes back when it leaves. This is the whole reason the row buttons
    -- went without a hover until now; it is two extra calls, not a redesign.
    --
    -- The state is RESTORED rather than forced to standard: refresh_panel runs on every trade,
    -- and the mouse is by definition over the button that was just clicked, so forcing
    -- standard would leave it drawn unlit until the pointer moved off and back.
    local was = c:CurrentState()
    c:SetState("hover")
    c:SetStateText(text)
    c:SetState("standard")
    c:SetStateText(text)
    if was and was ~= "" and was ~= "standard" then c:SetState(was) end
end

function EX.draw_spark(row, res)
    local spark = find_uicomponent(row, "spark")
    if not is_uicomponent(spark) then return end
    local h = EX.history[res] or {}
    -- Scale to the range actually visited, not the full 42 rungs, or every sparkline is flat.
    local lo, hi = EX.RUNGS, 1
    for _, v in ipairs(h) do
        if v < lo then lo = v end
        if v > hi then hi = v end
    end
    if hi <= lo then lo, hi = lo - 1, hi + 1 end
    local sx, sy = spark:Position()
    for i = 0, EX.SPARK_BARS - 1 do
        local bar = find_uicomponent(spark, string.format("bar_%02d", i))
        if is_uicomponent(bar) then
            -- history is most-recent-last, and so is the bar row
            local v = h[#h - (EX.SPARK_BARS - 1 - i)]
            if v then
                local frac = (v - lo) / (hi - lo)
                local px = math.floor(3 + frac * (EX.SPARK_H - 3))
                bar:SetCanResizeHeight(true)
                bar:Resize(7, px)
                -- bottom-align by hand: imagedock is ignored like every other dock attribute,
                -- so a shorter bar would otherwise hang from the top and read upside down
                bar:MoveTo(sx + i * 9, sy + (EX.SPARK_H - px))
                bar:SetVisible(true)
            else
                bar:SetVisible(false)
            end
        end
    end
end

-- TRIM TO WHAT THE BOX CAN ACTUALLY DRAW.
--
-- MEASURED 2026-09-06, and this exists because the footer shipped clipped mid-word: the trade
-- line needed 1333px in an 880px component and the game drew "Shaken: Gemsto..." with no error.
--
-- A TALLER BOX DOES NOT HELP. texthbehaviour has no wrap value in this engine ("Never split",
-- "Resize", "Slip by character" are the only three in ui3.pack, and textvbehaviour does not
-- exist), and resizing the live component to 880x60 still measured its text as one 1333px line.
-- So the only fix is fewer characters, and the only honest way to pick how many is to ask the
-- engine - uicomponent:TextDimensionsForText returns what a string WOULD need in this component
-- and its current state.
--
-- A character budget would have been the guess that put us here: the footer's content is
-- unbounded (the shock summary names one commodity per shaken good), so no constant is safe.
local function fit(c, text)
    if not is_uicomponent(c) then return text end
    local w = c:Dimensions()
    local ok, need = pcall(function() return c:TextDimensionsForText(text) end)
    if not ok or not need or need <= w then return text end
    -- Drop trailing words until it fits. Bounded by the word count, and only on a panel
    -- refresh, so the cost is nothing next to the 19 rows being rewritten around it.
    local words = {}
    for word in string.gmatch(text, "%S+") do words[#words + 1] = word end
    while #words > 1 do
        words[#words] = nil
        local try = table.concat(words, " ") .. " ..."
        local ok2, n2 = pcall(function() return c:TextDimensionsForText(try) end)
        if not ok2 or not n2 or n2 <= w then return try end
    end
    return text
end

-- A DISPLAY NAME FOR ANY INSTRUMENT, commodity or house. EX.INFO covers the goods and the
-- two Layer 2 pools; a house is a faction key and only EX.faction_display can name it.
-- WHICH INSTRUMENT A ROW COMPONENT IS, inverting EX.ROW .. "_" .. EX.short(res). Walks
-- EX.instruments() rather than parsing the id, because EX.short is not reversible - it
-- strips a prefix that two different keys could share.
function EX.res_of_row(id)
    for _, res in ipairs(EX.instruments()) do
        if id == EX.ROW .. "_" .. EX.short(res) then return res end
    end
    return nil
end

function EX.instrument_name(res)
    local info = EX.INFO[res]
    if info and info[1] then return info[1] end
    return EX.faction_display(res)
end

-- ITS OWN FUNCTION, and that is not tidiness. The layout harness can lay a view out but
-- cannot run refresh_panel - which needs a live faction, a stance vector and half the campaign
-- interface - so anything written INSIDE refresh_panel is invisible to every check in this
-- codebase. Three mutants proved it: the spare-row hide could be deleted, the row cell could be
-- taken out of the layout, and every scene still passed. EX.draw_chart is a function for the
-- same reason and was mutation-tested the same way.
function EX.draw_intro(panel, rows_holder)
    local lines = EX.intro_lines()
    local i = 0
    for _, res in ipairs(EX.mode_instruments()) do
        local row = EX.row(rows_holder, res)
        i = i + 1
        if is_uicomponent(row) then
            -- A SPARE ROW IS HIDDEN, NOT BLANKED - the guide's note, and it matters more here:
            -- twelve lines into nineteen slots leaves seven, and a blanked row still reserves
            -- its height under the last paragraph. Worse, the rows are the SAME components the
            -- commodity list uses, so a spare left visible on the way in from Trade is a price
            -- sitting under a paragraph.
            row:SetVisible(lines[i] ~= nil)
            if lines[i] then
                set_text(row, "row_name", lines[i][1])
                -- THE PICTURE BELONGS TO THE LINE, NOT THE ROW - the log's note, and it is
                -- the same trap here. Rows are built one per instrument with that
                -- instrument's icon baked in, so a line that paints nothing draws whatever
                -- commodity row i happened to be built with: a paragraph break wearing a
                -- gemstone. The blank rows and the closing line hide the cell instead, and
                -- hiding is not the default - EX.layout has already shown it by the time
                -- this runs, because EX.ROW_LAYOUT_INTRO names it.
                local ic = find_uicomponent(row, "icon")
                if is_uicomponent(ic) then
                    local path = lines[i][2]
                    if path then ic:SetImagePath(path, 0) end
                    ic:SetVisible(path ~= nil)
                end
            end
        end
    end
    local i1 = find_uicomponent(panel, "footer_text")
    local i2 = find_uicomponent(panel, "footer_text2")
    if is_uicomponent(i1) then i1:SetStateText(fit(i1, EX.INTRO_FOOT1)) end
    if is_uicomponent(i2) then i2:SetStateText(fit(i2, EX.INTRO_FOOT2)) end
end

-- THE DEEP CHART. Same bar technique as EX.draw_spark, and the same trap: imagedock is
-- ignored at runtime, so each bar is bottom-aligned by hand with MoveTo or a short bar
-- hangs from the top of the box and the chart reads upside down.
--
-- SCALED TO THE RANGE ACTUALLY VISITED, not to the full 42 rungs, for the reason the
-- sparkline is: against the whole ladder every real price history is a flat line.
-- THE ORDER TICKET. TOP-LEVEL, NOT A LOCAL INSIDE EX.draw_chart, which is where it started.
-- The seven cells were named ONLY by EX.PANEL_LAYOUT_CHART and written ONLY by draw_chart, so
-- with deep_history off there was no chart page, no draw_chart call, and no way to place an
-- order at all - while the ledger page sat there telling the player to "set one under its
-- chart". Both pages place these cells now and both call this.
--
-- GATED ON THE SWITCH as well as on the selection. With orders off the chart page still exists
-- and still places the ticket, and a live Place button with no ledger behind it is a way to
-- create orders that nothing can then cancel. EX.place_order_check carries the same gate for
-- the model; this one keeps the dead button off the screen.
function EX.clear_ticket(panel)
    for _, n in ipairs(EX.TICKET_CELLS) do
        -- BLANK AND HIDDEN TOGETHER, not just blanked: five of these are BUTTONS, and a
        -- blank-but-live button under "No commodity chosen" is still clickable.
        --
        -- BOTH STATES, via set_text, even though the cell is about to be hidden - a click
        -- that reopens it later (SetVisible(true) with no text write in between) must not
        -- show whichever commodity's numbers were left in the state the mouse was not over
        -- when this ran. Plain SetStateText reaches ONE state, which is that bug.
        local c = find_uicomponent(panel, n)
        if EX.TWO_STATE_CELLS[n] then
            set_text(panel, n, "")
        elseif is_uicomponent(c) then
            c:SetStateText("")
        end
        if is_uicomponent(c) then c:SetVisible(false) end
    end
end

function EX.draw_ticket(panel, res)
    if not is_uicomponent(panel) then return end
    if not EX.feature("orders") then return EX.clear_ticket(panel) end
    local known = false
    for _, k in ipairs(EX.instruments()) do
        if k == res then known = true break end
    end
    if not known then return EX.clear_ticket(panel) end
    -- AN EXPLICIT SHOW, for the two ticket cells that carry no hover state and so do not go
    -- through set_text's own SetVisible(true). Without it these two rely on EX.layout() having
    -- shown them at some earlier point, which is silently wrong the moment anything calls
    -- EX.refresh_panel() alone after a clear hid them: five live buttons beside two cells
    -- still hidden from the last time nothing was selected.
    local function show(name, text)
        local c = find_uicomponent(panel, name)
        if is_uicomponent(c) then
            c:SetStateText(text)
            c:SetVisible(true)
        end
    end
    set_text(panel, "ord_side", EX.ord_side == "b" and "Buy" or "Sell")
    set_text(panel, "ord_cmp", EX.ord_cmp == "le" and "At or below" or "At or above")
    set_text(panel, "ord_down", "-")
    set_text(panel, "ord_up", "+")
    set_text(panel, "ord_place", "Place order")
    set_text(panel, "ord_qty_down", "-")
    set_text(panel, "ord_qty", EX.amount_units(res))
    set_text(panel, "ord_qty_up", "+")
    local rung = EX.ord_rung or EX.current[res] or EX.neutral_rung()
    -- THE GOODS AND THE GOLD, under the ticket. Written before the refusal branch below
    -- returns, so a refused placement still shows what the player was trying to buy.
    set_text(panel, "ord_cost", EX.amount_line(res, rung))
    -- WHAT THE FILL WILL PAY, not the mid - see EX.order_price.
    show("ord_price", tostring(EX.order_price(res, EX.ord_side, rung)) .. "g")
    -- THE LAST REFUSAL, IF THERE IS ONE, and it replaces the standing line rather than
    -- sharing it: a player who just pressed Place is being told why nothing happened, and
    -- that is the whole content of this cell until they change something.
    if EX.ord_refusal then
        show("ord_standing", EX.ord_refusal)
        return
    end
    local nm = EX.instrument_name(res)
    local standing = EX.orders_on(res)
    if #standing == 0 then
        show("ord_standing", "No standing order on " .. nm .. ".")
    else
        local parts = {}
        for i = 1, #standing do parts[i] = EX.order_text(standing[i]) end
        show("ord_standing", "Standing on " .. nm .. ": " .. table.concat(parts, "; "))
    end
end

function EX.draw_chart()
    local panel = EX.panel()
    if not is_uicomponent(panel) then return end
    local function say(name, text)
        local c = find_uicomponent(panel, name)
        if is_uicomponent(c) then c:SetStateText(text) end
    end
    -- THE AXES AND THE ICON GO BLANK TOGETHER, and every early return calls this. A label
    -- is a panel-level component: it keeps its last text until something overwrites it, so
    -- charting furs and then clicking away would leave the furs price scale standing
    -- beside "No commodity chosen". Same class as the icon repaint the log rows need.
    local function blank_axes()
        for _, n in ipairs({ "chart_y_hi", "chart_y_mid", "chart_y_lo",
                             "chart_x_left", "chart_x_mid", "chart_x_right" }) do
            say(n, "")
        end
    end
    -- PAINTED FROM EX.icon, the same source the list rows use, so the chart and the row
    -- can never show two different pictures for one commodity. Nil hides the cell rather
    -- than leaving the previous commodity's icon, which would be a claim about the wrong
    -- good - and a wrong image path draws a blank square and logs nothing, so a guess is
    -- strictly worse than nothing.
    local function paint_icon(res)
        local ic = find_uicomponent(panel, "chart_icon")
        if not is_uicomponent(ic) then return end
        local path = res and EX.icon(res) or nil
        if path then ic:SetImagePath(path, 0) end
        ic:SetVisible(path ~= nil)
    end
    local chart = find_uicomponent(panel, "chart")
    local function hide_bars()
        if not is_uicomponent(chart) then return end
        for i = 0, EX.DEEP_BARS - 1 do
            local bar = find_uicomponent(chart, string.format("cbar_%02d", i))
            if is_uicomponent(bar) then bar:SetVisible(false) end
        end
    end

    -- NOTHING CHOSEN IS A LEGITIMATE STATE, not an error. The arrows are live on Trade
    -- whether or not anything is selected, so this is the first thing most players will
    -- see on this page and it has to tell them what to do.
    local res = EX.selected
    local known = false
    for _, k in ipairs(EX.instruments()) do
        if k == res then known = true break end
    end
    if not known then
        say("chart_title", "No commodity chosen")
        say("chart_axis", "")
        say("chart_stats",
            "Go back a page and click a commodity's NAME to chart its price here.")
        say("chart_note", "")
        blank_axes()
        paint_icon(nil)
        hide_bars()
        EX.draw_ticket(panel, nil)
        return
    end

    -- THE TICKET DOES NOT NEED CHART HISTORY, only a selection - it places an order at
    -- whatever the current rung is, which exists from the first turn. Written once here so
    -- both the no-history branch below and the normal one draw it, rather than twice.
    EX.draw_ticket(panel, res)

    local d, lo, hi = EX.deep_of(res)
    local name = EX.instrument_name(res)
    if #d == 0 then
        say("chart_title", name)
        say("chart_axis", "")
        say("chart_stats", "No history yet - one bar is recorded at the end of each turn.")
        say("chart_note", "")
        blank_axes()
        -- The icon still goes up. The commodity IS chosen here; it simply has no bars yet,
        -- and the page should say which good it is waiting on.
        paint_icon(res)
        hide_bars()
        return
    end

    local now = d[#d]
    say("chart_title", name .. " - " .. tostring(EX.price_at(now)) .. " gold")
    say("chart_axis", string.format(
        "Price in gold up the side, one bar a turn, this turn at the right. "
        .. "%d of %d turns recorded.", #d, EX.DEEP_BARS))
    say("chart_stats", string.format("High %d      Low %d      Now %d",
        EX.price_at(hi), EX.price_at(lo), EX.price_at(now)))
    -- The shock that is standing on this commodity, if one is. EX.shock_why is free text
    -- and is also what the trade footer prints, so the two agree by construction.
    local sh = EX.shock[res] or 0
    local why = EX.shock_why[res]
    if sh ~= 0 and why then
        say("chart_note", string.format("Shaken %.1f steps (%s).", sh, why))
    elseif hi == lo then
        say("chart_note", "This price has not moved since it was first recorded.")
    else
        say("chart_note", "")
    end

    paint_icon(res)

    -- A FLAT HISTORY STILL HAS TO DRAW. Without this the divisor is zero and every bar is
    -- a nan; the sparkline carries the same guard.
    --
    -- MOVED ABOVE THE LABELS DELIBERATELY. The y scale has to describe the range the BARS
    -- are drawn against, not the range the data occupies - on a flat history those differ
    -- by exactly this widening, and a scale that disagreed with its own bars would put the
    -- single price at the top of an axis whose top said something else. chart_stats above
    -- still reports the true high and low, which is the other half of the same honesty.
    if hi <= lo then lo, hi = lo - 1, hi + 1 end

    -- THE Y SCALE. price_at is continuous - the ladder is geometric, so it takes the
    -- half-rung the middle gridline lands on - and the bar heights are linear in RUNGS,
    -- which is why the midpoint label is price_at of the mid rung and not the mean of the
    -- two gold prices. Those are different numbers and only one of them is where the eye
    -- reads the middle of the plot.
    say("chart_y_hi", tostring(EX.price_at(hi)))
    say("chart_y_mid", tostring(EX.price_at((lo + hi) / 2)))
    say("chart_y_lo", tostring(EX.price_at(lo)))

    -- THE X SCALE. EX.remember_all appends exactly once per turn and only from the turn
    -- handler - never from the first-tick path, so a reload cannot add a bar - which is
    -- what makes the newest bar THIS turn and every earlier bar one turn per step back.
    -- No turn number is stored anywhere; it is derived, and it is derived from the same
    -- assumption the caption above already states out loud.
    --
    -- A tick whose bar has no data is blank, not a turn number from before the campaign
    -- started. Bar i holds d[#d - (DEEP_BARS - 1 - i)], so it is filled when
    -- #d >= DEEP_BARS - i.
    local turn_now = cm:turn_number()
    for _, t in ipairs({ { "chart_x_left", 0 },
                         { "chart_x_mid", math.floor(EX.DEEP_BARS / 2) },
                         { "chart_x_right", EX.DEEP_BARS - 1 } }) do
        if #d >= EX.DEEP_BARS - t[2] then
            say(t[1], "Turn " .. tostring(turn_now - (EX.DEEP_BARS - 1 - t[2])))
        else
            say(t[1], "")
        end
    end

    if not is_uicomponent(chart) then return end
    local cx, cy = chart:Position()
    -- THE PLOT GROWS WITH THE PANEL (EX.fit): its height, each bar's width and the pitch
    -- between them are the 1600x900 constants at the current box. The gridlines and labels
    -- move with it through EX.GROW_CHART_Y, so the low line still sits on top of the floor stub.
    local ch = EX.sc(EX.CHART_H)
    local bw = EX.sc(EX.CHART_BAR_W)
    for i = 0, EX.DEEP_BARS - 1 do
        local bar = find_uicomponent(chart, string.format("cbar_%02d", i))
        if is_uicomponent(bar) then
            -- history is most-recent-last, and so is the bar row
            local v = d[#d - (EX.DEEP_BARS - 1 - i)]
            if v then
                local frac = (v - lo) / (hi - lo)
                local px = math.floor(EX.CHART_FLOOR
                    + frac * (ch - EX.CHART_FLOOR))
                bar:SetCanResizeHeight(true)
                bar:Resize(bw, px)
                bar:MoveTo(cx + EX.sc(i * EX.CHART_PITCH), cy + (ch - px))
                bar:SetVisible(true)
            else
                bar:SetVisible(false)
            end
        end
    end
end

-- WHAT THE DEALS FOOTER SAYS, and the empty cases are the point of it. A blank list with no
-- sentence under it reads as a broken page; each of these three says something different
-- about the world, and EX.deal_ok returning can_issue and score separately is what makes the
-- middle two distinguishable at all.
--
-- THE SWITCH IS READ LIVE, not off EX.deal_why: a player who turns the feature off mid-turn
-- sees the reason change on the next refresh rather than next turn.
-- THE FIVE STRINGS ONE DEAL DRAWS. Out of the draw call deliberately, the way EX.log_lines
-- and EX.help_lines are: text computed inside EX.refresh_panel can only be checked by
-- rendering a panel, and nothing offline renders one - so it would ship unchecked.
--
-- "Buys" AND "Sells" ARE FROM THE ACTOR'S SIDE, which is the side the name beside them is
-- on. The player does the opposite, and the price column says what that costs them.
function EX.deal_cells(i)
    local d = EX.deals[i]
    if not d then return nil end
    local lots = d.lots .. (d.lots == 1 and " lot of " or " lots of ")
    -- SIGNED, AND ROUNDED AWAY FROM ZERO ON A HALF. math.floor(x + 0.5) agrees with this at
    -- every whole number - floor(-6.0 + 0.5) is -6, not -7, and the first version of this
    -- comment claimed otherwise until a mutant that swapped the two survived. They differ
    -- only at an exact half, where plain floor rounds -6.5 to -6 while rounding +6.5 to +7:
    -- the same distance from market displayed as a different number depending on which side
    -- of it the deal sits, on the one column this page exists for. The fixture carries a
    -- 935-against-1000 deal so this branch is exercised rather than asserted about.
    local mkt = EX.price(d.res)
    local pc = (mkt and mkt > 0) and ((d.px - mkt) / mkt * 100) or 0
    pc = (pc >= 0) and math.floor(pc + 0.5) or -math.floor(-pc + 0.5)
    -- THE BUTTON IS A CELL TOO, and it is computed here for the reason every other string on
    -- this page is: nothing offline can run EX.refresh_panel, so a label or a disabled state
    -- decided inside it ships unread. A mutant that asked EX.buy_refusal on BOTH sides
    -- survived every check in this file on 2026-09-16 with the logic still inside the draw.
    --
    -- ASKED ONLY WHERE THE PLAYER PAYS. d.side is the COUNTERPARTY's verb, so "sell" is the
    -- side where they sell and the player buys. Selling INTO a deal stays open even with the
    -- market shut - the same asymmetry the commodity and house rows already ship ("SELLING
    -- STAYS OPEN, on paper as on commodities"), and not a new rule: the war lock exists to
    -- stop the player buying their way out of a war.
    local why, why_label = nil, nil
    if d.side == "sell" then why, why_label = EX.buy_refusal(d.res) end
    return {
        name  = EX.faction_display(d.fac),
        offer = (d.side == "buy" and "Buys " or "Sells ") .. lots .. EX.display(d.res),
        price = d.px .. "g",
        edge  = string.format("%+d%%", pc),
        total = (d.px * d.lots) .. "g",
        res   = d.res,
        take  = why_label or "Take",
        why   = why,
    }
end

-- ONE ROW OF THE DEALS PAGE. A top-level function and not five lines inside EX.refresh_panel,
-- for the reason EX.draw_intro states for itself: the layout harness can build a panel and lay
-- it out but cannot run refresh_panel, which needs a live faction and half the campaign
-- interface - so anything written inside the draw call ships unread. Two mutants proved it here
-- as three proved it for the chart: SetDisabled(false) and a hardcoded button label both
-- survived a full round with these lines inline.
--
-- IT TAKES THE ROW AND THE INDEX, not the deal. EX.deal_cells already turns an index into
-- every string this writes, and handing it a deal would give the row a second route to the
-- same five cells - the two would then be free to disagree about which faction a row names.
function EX.draw_deal_row(row, i)
    if not is_uicomponent(row) then return end
    local c = EX.deals[i] and EX.deal_cells(i)
    -- HIDDEN, NOT SKIPPED. The row pool is fixed and outlives the page, so a row left alone
    -- keeps last turn's text and draws it under a shorter list.
    row:SetVisible(c ~= nil)
    if not c then return end
    -- THE COUNTERPARTY, and it is the name the settlement uses. EX.accept_deal passes d.fac to
    -- EX.apply_trade as `only`, so what this cell says is what the gold does - see
    -- EX.settle_counterparty's `only` parameter.
    set_text(row, "row_name", c.name)
    set_text(row, "row_trend", c.offer)
    set_text(row, "row_price", c.price)
    set_text(row, "row_sell", c.edge)
    set_text(row, "row_hold", c.total)
    -- THE ICON IS THE DEAL'S, NOT THE ROW'S. These rows are created with no instrument and no
    -- icon baked in - same as the ledger's pool - so an unpainted cell would show whatever the
    -- last view left in it.
    local ic = find_uicomponent(row, "icon")
    if is_uicomponent(ic) then
        local path = EX.icon(c.res)
        if path then ic:SetImagePath(path, 0) end
        ic:SetVisible(path ~= nil)
    end
    -- THE ACCEPT BUTTON, WHOLLY DECIDED IN EX.deal_cells. Both states via set_text - btn_buy is
    -- in EX.TWO_STATE_CELLS, so a hover state left unwritten shows the last view's label to the
    -- one player already pointing at it.
    set_text(row, "btn_buy", c.take)
    local bb = find_uicomponent(row, "btn_buy")
    EX.set_off(bb, c.why ~= nil)
    set_tip(bb, c.why or EX.TIP_DEAL)
end

function EX.deals_line()
    if not EX.setting("ai_deals") then
        return "Deals from the world are switched off in this campaign's settings."
    end
    local n = #EX.deals
    if n > 0 then
        return n .. (n == 1 and " deal is" or " deals are") .. " on the table this turn, "
            .. "up to " .. EX.opt("deal_max") .. ". Click one to take it; they expire at the turn end."
    end
    if EX.deal_why == "declined" then
        return "Every faction in a position to deal turned you down this turn."
    end
    if EX.deal_why == "none" then
        return "No faction on the map is in a position to deal with you this turn."
    end
    return "No deals this turn."
end

-- THE PENDING TITHE, or nil: { res, amount, boon turns, wrath turns, turns left to pay }.
-- "Turns left" counts this one - EX.check_demand lands the wrath at the START of turn
-- EX.demand_due, so the last turn the tithe can be paid is the one before it, and 1 means now.
function EX.tithe()
    if not EX.demand_pending() then return nil end
    local tier = EX.tier_by_suffix(EX.demand_tier)
    if not tier then return nil end
    local left = (EX.demand_due or 0) - cm:turn_number()
    if left < 1 then left = 1 end
    return { res = EX.demand_res, amount = tier[2], turns = tier[3], wrath = tier[4],
             left = left }
end

-- ONE ROW OF THE OFFERINGS VIEW, every string and the button's state. Out of the draw for the
-- reason EX.deal_cells is: nothing offline can run EX.refresh_panel.
--
-- A PENDING TITHE OWNS ITS ROW. EX.apply_offer routes a click on the named good to
-- EX.pay_demand, at the tithe's amount and past the offering cooldown - so this row drawing the
-- ordinary offering ("Ready" at 30 held, against a tithe of 90) promised one thing and did
-- another, and the refusal went to the script log only.
--
-- THE BUTTON'S DISABLED STATE AND TOOLTIP ARE DECIDED HERE, EVERY TIME. The row is shared with
-- the Trade view, which greys btn_buy on a refused buy - so an Offerings row that never wrote
-- the state wore the Trade view's "Closed" through every war, and a disabled button sends no
-- click.
function EX.offer_cells(res)
    local held = EX.held(res)
    local name = EX.display(res)
    local patron = EX.patron()
    if EX.is_layer2(res) then
        local no = patron .. " has no use for these"
        return { held = tostring(held), cost = "-", grants = no, status = "-", btn = "-",
                 why = no .. "." }
    end
    local boon = EX.boon(res) or "-"
    local t = EX.tithe()
    if t and t.res == res then
        local c = { held = tostring(held), cost = tostring(t.amount), grants = boon }
        if held >= t.amount then
            c.status = "Due: " .. t.left .. (t.left == 1 and " turn" or " turns")
            c.btn = "Pay tithe"
            c.tip = "Pay the tithe: " .. t.amount .. " " .. name .. ".||" .. patron
                .. "'s favour, " .. t.turns .. " turns: " .. boon .. "."
        else
            c.status = "Need " .. (t.amount - held)
            c.btn = "Insufficient"
            c.why = "The tithe is " .. t.amount .. " " .. name .. ". You hold " .. held .. ".||"
                .. "Unpaid, " .. patron .. "'s wrath lasts " .. t.wrath .. " turns."
        end
        return c
    end
    local cost = EX.offer_cost()
    local left = EX.offer_turns_left(res)
    local c = { held = tostring(held), cost = tostring(cost), grants = boon }
    if left > 0 then
        c.status = left .. (left == 1 and " turn left" or " turns left")
        c.btn = "Active"
        c.why = "This offering's favour is still running."
    elseif held >= cost then
        c.status = "Ready"
        c.btn = "Sacrifice"
        c.tip = "Burn " .. cost .. " " .. name .. " on the altar.||" .. patron .. "'s favour, "
            .. EX.OFFER_TURNS .. " turns: " .. boon .. "."
    else
        c.status = "Need " .. (cost - held)
        c.btn = "Insufficient"
        c.why = "An offering takes " .. cost .. " " .. name .. ". You hold " .. held .. "."
    end
    return c
end

-- THE SELL BUTTON, on a Trade or Houses row. Greyed below one lot, which is the one sell
-- EX.apply_trade refuses ("nothold") - it used to stay live and the click did nothing.
function EX.draw_sell(bs, res)
    if not is_uicomponent(bs) then return end
    local short = EX.held(res) < EX.lot(res)
    EX.set_off(bs, short)
    set_tip(bs, short and EX.TIP_SELL_NONE or EX.TIP_SELL)
end

function EX.draw_offer_row(row, res)
    if not is_uicomponent(row) then return end
    local c = EX.offer_cells(res)
    set_text(row, "row_supply", c.held)
    set_text(row, "row_price", c.cost)
    set_text(row, "row_trend", c.grants)
    set_text(row, "row_hold", c.status)
    set_text(row, "btn_buy", c.btn)
    local bb = find_uicomponent(row, "btn_buy")
    EX.set_off(bb, c.why ~= nil)
    set_tip(bb, c.why or c.tip)
end

function EX.refresh_panel()
    local panel = EX.panel()
    if not is_uicomponent(panel) then return end
    EX.refresh_button_tip()
    local faction = cm:get_faction(EX.me())
    local stats = (EX.mode == EX.MODE_STATS)
    local offer = (EX.mode == EX.MODE_OFFER)
    local houses = (EX.mode == EX.MODE_HOUSES)
    local orders = EX.on_orders()

    local title = find_uicomponent(panel, "title_text")
    if is_uicomponent(title) then
        -- THE TITLE IS MEASURED, NOT BUDGETED. fit() is defined immediately above this
        -- function; it asks the component what a string WOULD need with
        -- TextDimensionsForText and drops trailing words until it fits. It was already used
        -- for the log footer and not here - and FOUR of the six titles this file shipped are
        -- over the ~19-character ceiling the old comment cited ("Zharr Exchange: Ownership"
        -- is 25), so this fixes a live clip as well as making per-race names safe to author.
        --
        -- FOUR OF THE FIVE DERIVE from the race's name; only the Offerings view's is
        -- authored, because it names the patron rather than the market.
        -- "Exchange", NOT "Zharr Exchange". This is the fallback for an UNCOVERED race - the
        -- majority of this mod's players - and naming the Chaos Dwarf market there put "The
        -- Zharr Exchange" on a Bretonnian player's panel. Same fault as the opener button's
        -- static tooltip, one line apart, and caught by the same check once it learned that a
        -- market's name is as race-specific as its god. EX.the_name() uses the same word.
        local nm = EX.race_name()
        -- EX.the_name() carries the "The " rule; see the note beside it.
        local t = EX.the_name()
        if stats then t = nm .. ": Ownership"
        elseif offer then t = (EX.race and EX.race.offer_title) or "Offerings"
        elseif houses then t = nm .. ": Houses"
        elseif EX.mode == EX.MODE_INTRO then t = EX.the_name()
        elseif EX.mode == EX.MODE_HELP then t = "How the " .. nm .. " works"
        elseif EX.mode == EX.MODE_DEALS then t = nm .. ": Deals"
        elseif EX.mode == EX.MODE_LOG then t = nm .. ": Log" end
        title:SetStateText(fit(title, t))
    end
    for hid, label in pairs(EX.HEADERS[EX.view()]) do
        local c = find_uicomponent(panel, hid)
        if is_uicomponent(c) then c:SetStateText(EX.sort_mark(hid, label)) end
    end
    -- THE LIST'S AMOUNT BUTTON. set_text and not SetStateText: it is in EX.TWO_STATE_CELLS,
    -- and a one-state write leaves the hover state holding whatever it held before - which
    -- on a button whose whole label IS the number means the wrong size is shown to the one
    -- player certain to be looking at it, the one with the pointer on it. check_lua_hover
    -- caught exactly that here.
    -- GUARDED: see EX.in_layout. Only the views whose own layout names this cell may write
    -- to it, because writing to it is also showing it.
    if EX.in_layout("btn_amount") then
        set_text(panel, "btn_amount", EX.amount_label())
        set_text(panel, "btn_amt_down", "-")
        set_text(panel, "btn_amt_up", "+")
    end

    -- THE TAB STRIP. Labels are written every refresh for the same reason the row buttons'
    -- are: set_text writes both states, and a label written once vanishes the moment the
    -- mouse is over the button.
    --
    -- THE CURRENT VIEW'S TAB IS DISABLED, which is how the strip says where you are. Disabled
    -- and not hidden, with a tooltip that says why - the standard this file already holds its
    -- refused Buy buttons and its AI-turn opener to. Hiding it would shuffle the other four
    -- sideways every time the player changed view.
    for _, m in ipairs(EX.MODES) do
        local tab = find_uicomponent(panel, EX.tab_name(m))
        if is_uicomponent(tab) then
            set_text(panel, EX.tab_name(m), EX.TAB_LABEL[m] or m)
            local here = (m == EX.mode)
            local locked = EX.tab_locked(m)
            EX.set_off(tab, here or locked ~= nil)
            set_tip(tab, locked
                    or (here and "You are looking at this view.")
                    or ("Switch to " .. (EX.TAB_LABEL[m] or m) .. "."))
        end
    end

    -- AND THE ARROWS, which page the view rather than cycling views since the tabs arrived.
    -- A view with one page has nothing for them to do, so they grey out and say so instead of
    -- sitting there live and doing nothing when clicked.
    local pages = EX.page_count()
    for _, nm in ipairs({ EX.MODE_PREV, EX.MODE_BTN }) do
        local a = find_uicomponent(panel, nm)
        if is_uicomponent(a) then
            EX.set_off(a, pages < 2)
            set_tip(a, pages < 2 and "This view has a single page."
                    or "Page through this view. The tabs below change view.")
        end
    end

    -- THE CHART PAGE. Drawn here rather than returning early, so the footers, the tab
    -- strip and the title below still run - the world lines are as worth reading on this
    -- page as on the list. The row loop costs nothing: EX.mode_instruments is empty here.
    if EX.on_chart() then EX.draw_chart() end

    -- AND THE TICKET ON THE LEDGER PAGE. draw_chart draws it on the chart page; this page
    -- places the same seven cells and nothing else would ever write them. It is the only
    -- route to placing an order when deep_history is off.
    if EX.on_orders() then EX.draw_ticket(panel, EX.selected) end

    local rows_holder = find_uicomponent(panel, "rows_holder")

    -- THE GUIDE. It borrows the row components rather than owning any: one line per row, the
    -- name cell for the term and the wide cell for the sentence. Everything else is hidden by
    -- EX.layout, because EX.ROW_LAYOUT_HELP does not name it.
    -- THE LOG, drawn exactly as the guide is - borrowed rows, name cell and wide cell. It
    -- scans for changes first so a refusal that appeared this refresh is already in the list
    -- by the time the rows are written.
    -- THE DEALS PAGE. Drawn like the log and the guide - borrowed rows, written by position -
    -- and it returns before EX.hold_guild for the same reason they do: no cell here asks a
    -- price question of the guild. The ROW BODY is EX.draw_deal_row, a top-level function, for
    -- exactly the reason EX.draw_chart and EX.draw_intro are: nothing offline runs
    -- EX.refresh_panel, so two mutants on the button - never disabling it, and writing a
    -- hardcoded label over the one EX.deal_cells computed - survived a full round on
    -- 2026-09-16 while these lines were still inline.
    if EX.mode == EX.MODE_DEALS then
        for i, key in ipairs(EX.mode_instruments()) do
            EX.draw_deal_row(EX.row(rows_holder, key), i)
        end
        local df1 = find_uicomponent(panel, "footer_text")
        local df2 = find_uicomponent(panel, "footer_text2")
        if is_uicomponent(df1) then df1:SetStateText(fit(df1, EX.deals_line())) end
        if is_uicomponent(df2) then
            df2:SetStateText(fit(df2, "A deal lasts one turn and is gone at the next. The "
                .. "price is agreed: the market markup does not apply to it."))
        end
        return
    end

    if EX.mode == EX.MODE_LOG then
        pcall(EX.log_scan)
        local lines = EX.log_lines()
        local i = 0
        for _, res in ipairs(EX.mode_instruments()) do
            local row = EX.row(rows_holder, res)
            i = i + 1
            if is_uicomponent(row) then
                local line = lines[i]
                row:SetVisible(line ~= nil)
                if line then
                    set_text(row, "row_name", line[1])
                    set_text(row, "row_trend", line[2])
                    -- THE ICON BELONGS TO THE LINE, NOT THE ROW. Rows are created one per
                    -- instrument with that instrument's icon baked in at build time, and this
                    -- view writes line i into row i - so without repainting, a refusal about
                    -- furs draws whatever icon row 1 happened to be built with. A line with no
                    -- instrument (a market closure) hides the cell rather than keeping the
                    -- last row's picture, which would read as a claim about that commodity.
                    local ic = find_uicomponent(row, "icon")
                    if is_uicomponent(ic) then
                        local path = line[3] ~= "" and EX.icon(line[3]) or nil
                        if path then ic:SetImagePath(path, 0) end
                        ic:SetVisible(path ~= nil)
                    end
                end
            end
        end
        local lf1 = find_uicomponent(panel, "footer_text")
        local lf2 = find_uicomponent(panel, "footer_text2")
        if is_uicomponent(lf1) then
            lf1:SetStateText(fit(lf1, "Page " .. EX.log_page .. " of " .. EX.log_pages()
                .. ", " .. #lines .. " of " .. #EX.LOG .. " recorded events, newest first. "
                .. "The arrows page this list."))
        end
        if is_uicomponent(lf2) then
            lf2:SetStateText(fit(lf2, "Refusal reads the guild's BOOK - who is holding the "
                .. "goods - not the Output column, which is what the map produces."))
        end
        return
    end

    if EX.mode == EX.MODE_INTRO then
        EX.draw_intro(panel, rows_holder)
        return
    end

    if EX.mode == EX.MODE_HELP then
        local i = 0
        local lines = EX.help_lines()
        for _, res in ipairs(EX.mode_instruments()) do
            local row = EX.row(rows_holder, res)
            i = i + 1
            if is_uicomponent(row) then
                local line = lines[i]
                -- A SPARE ROW IS HIDDEN, NOT BLANKED. EX.layout hides CELLS; the row itself
                -- still draws its divider, so a blanked row leaves a ruled empty band under
                -- the last line of the guide.
                row:SetVisible(line ~= nil)
                if line then
                    set_text(row, "row_name", line[1])
                    set_text(row, "row_trend", line[2])
                end
            end
        end
        local hf1 = find_uicomponent(panel, "footer_text")
        local hf2 = find_uicomponent(panel, "footer_text2")
        if is_uicomponent(hf1) then hf1:SetStateText(fit(hf1, EX.HELP_FOOT1)) end
        if is_uicomponent(hf2) then hf2:SetStateText(fit(hf2, EX.HELP_FOOT2)) end
        return
    end

    -- ONE STANCE VECTOR FOR THE WHOLE REFRESH, and freed at the bottom of this function. Every
    -- row below asks EX.hostility four times (buy_price, sell_price, buy_tip, sell_tip) and
    -- each of those used to re-walk the guild calling treaty_tier and standing_of per member.
    -- OPENED HERE, after both early returns above, so the guide branch cannot leave a hold
    -- standing. See EX.hold_guild for the measured numbers.
    EX.hold_guild()

    -- THIS MODE'S INSTRUMENTS ONLY. EX.layout has already hidden every other row; writing text
    -- into them would be wasted, and worse, feeding a commodity key through the houses branch
    -- is what produced a Seat column reading "horde" for res_animals (cm:get_faction on a
    -- commodity key answers false, so EX.holds_capital returns nil) beside a live Buy button.
    for _, res in ipairs(EX.mode_instruments()) do
        local row = EX.row(rows_holder, res)
        if is_uicomponent(row) then
            set_text(row, "row_name", EX.display(res))
            -- REPAINTED EVERY REFRESH, not just at build. The log view borrows these rows and
            -- overwrites their icons with whatever its lines are about, so a row that was left
            -- carrying the furs icon would still be carrying it on the trade view. Setting it
            -- from the row's OWN instrument here makes the log's repaint local to the log.
            local ic = find_uicomponent(row, "icon")
            if is_uicomponent(ic) then
                local path = EX.icon(res)
                if path then ic:SetImagePath(path, 0) end
                ic:SetVisible(path ~= nil)
            end
            -- World output per turn, the number this commodity's price is derived from.
            -- Layer 2 has no map supply signal at all, so it shows a dash, not a false zero.
            local sup = (EX.supply or {})[res]
            if offer then
                -- The offerings view reuses every cell for a different number: row_supply is
                -- what you HOLD, row_price is what the altar takes, row_trend is what the patron
                -- gives back. EX.offer_cells decides all of it, the tithe and the button too.
                EX.draw_offer_row(row, res)
            elseif stats then
                set_text(row, "row_supply", sup and tostring(sup) or "-")
                local holder, held = EX.top_holder(res)
                set_text(row, "row_trend", EX.faction_display(holder))
                if holder and sup and sup > 0 then
                    set_text(row, "row_price",
                             string.format("%d%%", math.floor(held * 100 / sup + 0.5)))
                else
                    set_text(row, "row_price", "-")
                end
                local prem = EX.premium(res)
                set_text(row, "row_hold", prem and string.format("%+.1f%%", prem) or "-")
            elseif houses then
                -- THE HOUSES VIEW. row_sell carries the dividend and row_supply carries the
                -- seat state - see EX.PANEL_LAYOUT_HOUSES for the column shapes this text has
                -- to fit, and EX.HEADERS.houses, which is what relabels the two headers above
                -- them to "Div" and "Seat".
                --
                -- ONLY HOUSES REACH THIS BRANCH. EX.mode_instruments() gives this view the
                -- discovered house list and nothing else; it used to get every instrument, so
                -- 19 commodities came through here drawing a raw key for a name and a Seat of
                -- "horde" (cm:get_faction on a commodity key answers false).
                set_text(row, "row_name", EX.faction_display(res))
                -- THE WHOLE CLICK, not one lot of it. EX.trade moves EX.amount lots, so a
                -- button that still reads "Buy 10" at x5 understates what pressing it does by
                -- a factor of five - and this is the only place on the panel where the units
                -- are unambiguous, because a row is one instrument with one lot size.
                local lot = EX.lot(res) * EX.clamp_lots(EX.amount)
                local bb = find_uicomponent(row, "btn_buy")
                local bs = find_uicomponent(row, "btn_sell")
                -- house_gone AS WELL AS is_delisted. A house killed during the player's own
                -- turn is not settled until the next FactionTurnStart, so for the rest of that
                -- turn is_delisted is still false while EX.trade already refuses it. Keying the
                -- row on the flag alone left an enabled "Buy 5" that did nothing - the exact
                -- fault the comment below condemns, reintroduced one turn early.
                if EX.is_delisted(res) or EX.house_gone(res) then
                    -- A DELISTED ROW STAYS ON SCREEN rather than vanishing - a row that
                    -- disappears takes the player's memory of what happened with it. But its
                    -- Buy/Sell buttons must not go on reading "Buy 5"/"Sell 5" while EX.trade
                    -- silently refuses them (an out() log line only, nothing the player sees) -
                    -- that is a live-looking control that does nothing. DISABLED, NOT HIDDEN,
                    -- AND THE TOOLTIP SAYS WHY - this file's own standard, from the AI-turn
                    -- gate on the opener button (EX.gate_button).
                    set_text(row, "row_price", "-")
                    set_text(row, "row_sell", "-")
                    set_text(row, "row_supply", "gone")
                    -- AND THE TREND, which this branch used to leave alone. A dead house sits
                    -- on the ladder floor, so the generic cell above had already written a red
                    -- "Lo" - a price signal on a row whose price is "-".
                    set_text(row, "row_trend", "-")
                    set_text(row, "btn_buy", "Delisted")
                    set_text(row, "btn_sell", "Delisted")
                    EX.set_off(bb, true)
                    EX.set_off(bs, true)
                    set_tip(bb, "This house is gone. Its book settled once and the row is frozen.")
                    set_tip(bs, "This house is gone. Its book settled once and the row is frozen.")
                else
                    -- buy_price, NOT price - the Buy column must draw what EX.trade charges.
                    set_text(row, "row_price", tostring(EX.buy_price(res)))
                    set_text(row, "row_sell", "+" .. EX.dividend(res))
                    -- THREE STATES, NOT TWO. true/false/nil out of EX.holds_capital are held,
                    -- LOST and "no capital to lose" respectively - collapsing nil into false
                    -- would read every CHARACTER_BOUND_HORDE house as LOST forever.
                    local seat = EX.holds_capital(cm:get_faction(res))
                    set_text(row, "row_supply",
                             seat == nil and "horde" or (seat and "held" or "LOST"))
                    local held = EX.held(res)
                    local htxt = tostring(held)
                    local div_total = EX.dividend(res) * held
                    if div_total > 0 then htxt = htxt .. "  +" .. div_total .. "g" end
                    set_text(row, "row_hold", htxt)
                    -- THE WAR LOCK REACHES PAPER TOO. EX.trade guards on EX.blocked with no
                    -- is_house exemption, so a share buy IS refused while the market is shut -
                    -- but this branch used to write "Buy 5" and SetDisabled(false)
                    -- unconditionally, so seven house rows sat there looking live and doing
                    -- nothing. Reported from a screenshot, 2026-09-07: the same live-looking
                    -- dead control the delisted branch above condemns in its own comment, on
                    -- the row right beneath it.
                    --
                    -- Houses are exempt from hostility and from refusal (EX.refused_by and
                    -- EX.hostility both return early on is_house), so the only reason that can
                    -- land here is the war lock - but it is read through EX.buy_refusal rather
                    -- than EX.market_closed so this row can never disagree with the commodity
                    -- rows about what is wrong.
                    local why, why_label = EX.buy_refusal(res)
                    set_text(row, "btn_buy", why_label or ("Buy " .. lot))
                    set_text(row, "btn_sell", "Sell " .. lot)
                    EX.set_off(bb, why ~= nil)
                    set_tip(bb, why or EX.TIP_BUY)
                    -- SELLING STAYS OPEN, on paper as on commodities - to anyone holding a lot.
                    EX.draw_sell(bs, res)
                end
                set_text(row, "row_trend", EX.trend_arrow(res))
            elseif orders then
                -- THE ORDER THIS ROW NAMES, straight off the synthetic "ordN" key
                -- EX.mode_instruments handed out - res here is "ord1"/"ord2"/... and NOT a
                -- resource, so o.res (never res) is what EX.display/EX.icon/EX.price are
                -- asked about below. Same index arithmetic EX.order_of_row uses for the
                -- Cancel click, so the row's text and its click agree about which order they
                -- mean even when two orders share an instrument (a ladder).
                local n = tonumber(string.match(res, "^ord(%d+)$"))
                local o = n and EX.orders[n]
                if o then
                    set_text(row, "row_name", EX.display(o.res))
                    -- REPAINTED FROM THE ORDER'S OWN RESOURCE, not the row's - the generic
                    -- icon write a few lines up this loop used res ("ord1") and found
                    -- nothing in EX.INFO, so it already hid this cell once this refresh.
                    local ic = find_uicomponent(row, "icon")
                    if is_uicomponent(ic) then
                        local path = EX.icon(o.res)
                        if path then ic:SetImagePath(path, 0) end
                        ic:SetVisible(path ~= nil)
                    end
                    set_text(row, "row_trend", EX.order_text(o))
                    -- THE SIDE'S OWN PRICE, not the mid. The column is headed "Now" and a
                    -- sell order's row must not quote what a buyer would pay - same reason
                    -- EX.order_text goes through EX.order_price.
                    set_text(row, "row_price", tostring(
                        (o.side == "b") and EX.buy_price(o.res) or EX.sell_price(o.res)))
                    -- BOTH STATES, via set_text - btn_buy is in EX.TWO_STATE_CELLS, so this
                    -- already writes hover and standard; a plain SetStateText call would leave
                    -- "Buy 5" showing the instant the mouse arrived, from whichever state this
                    -- physical row was last drawn as a commodity or a house.
                    set_text(row, "btn_buy", "Cancel")
                    -- ITS OWN TOOLTIP. Unwritten, it kept the row file's static "Buy a lot".
                    set_tip(find_uicomponent(row, "btn_buy"), EX.TIP_CANCEL)
                end
            else
                set_text(row, "row_supply", sup and tostring(sup) or "-")
                -- THE WHOLE CLICK, not one lot of it. EX.trade moves EX.amount lots, so a
                -- button that still reads "Buy 10" at x5 understates what pressing it does by
                -- a factor of five - and this is the only place on the panel where the units
                -- are unambiguous, because a row is one instrument with one lot size.
                local lot = EX.lot(res) * EX.clamp_lots(EX.amount)
                -- NO HOUSE REACHES THIS BRANCH ANY MORE. EX.mode_instruments() gives the trade,
                -- stats and offerings views commodities and layer 2 only, so the delisted-house
                -- special case that used to live here - a row drawn by faction key with a blank
                -- icon and a Buy button EX.trade silently refused - has no input left. Deleted
                -- rather than kept as belt and braces: dead UI code that cannot be exercised
                -- rots, and the Houses view carries the real one.
                local bb = find_uicomponent(row, "btn_buy")
                local bs = find_uicomponent(row, "btn_sell")
                -- WHY THE BUY IS DEAD, OR NIL. Both reasons - nothing on the map produces it,
                -- and a house refusing you or the war lock - come back through one call, so
                -- the price cell, the label, the disabled flag and the tooltip cannot disagree.
                local why, why_label = EX.buy_refusal(res)
                -- 5,054 is the MULT_MAX clamp, not a price anyone would sell at. Showing the
                -- number invited a trade that cannot happen, so the row says so instead.
                -- buy_price, NOT price - the Buy column must draw what EX.trade charges.
                set_text(row, "row_price", why and "-" or EX.price_cell(res, true))
                -- THE SELL PRICE IS SHOWN EVEN WHEN THE BUY PRICE IS NOT: a position carried in
                -- from an older save has to be closable.
                set_text(row, "row_sell", EX.price_cell(res, false))
                -- PER-ROW, ON TOP OF THE STATIC COLUMN TIP set_tip already carries from
                -- EX.apply_tips. Rebuilt every refresh so a trade or a treaty that moves the
                -- hostility markup is reflected without waiting for a mode switch.
                set_tip(find_uicomponent(row, "row_price"), EX.buy_tip(res))
                set_tip(find_uicomponent(row, "row_sell"), EX.sell_tip(res))
                set_tip(find_uicomponent(row, "row_hold"), EX.hold_tip(res))
                set_text(row, "row_trend", EX.trend_arrow(res))
                -- HOLDING AND ITS RENT IN ONE CELL, because they are one decision. Green means
                -- the pile is big enough to be granting a standing bonus - the bundle itself
                -- says which and how much, under Faction Effects, so the cell only has to say
                -- that there IS one. Layer 2 is excluded from both: it pays no rent and has no
                -- warehouse bundle, so colouring it green would promise a bonus that does not
                -- exist.
                local held = EX.held(res)
                local htxt = tostring(held)
                if not EX.is_layer2(res) and EX.stock_tier(held) > 0 then
                    htxt = "[[col:green]]" .. htxt .. "[[/col]]"
                end
                local carry = EX.carry_cost(res)
                if carry > 0 then htxt = htxt .. "  -" .. carry .. "g" end
                set_text(row, "row_hold", htxt)
                -- The label comes from EX.buy_refusal beside the reason string, so "Closed"
                -- can never sit on a row whose tooltip says a house refused it.
                set_text(row, "btn_buy", why_label or ("Buy " .. lot))
                set_text(row, "btn_sell", "Sell " .. lot)
                -- DISABLED, NOT HIDDEN, AND THE TOOLTIP SAYS WHY - see EX.buy_refusal for what
                -- an unconditional SetDisabled(false) here left on screen.
                --
                -- WRITTEN BOTH WAYS ON EVERY REFRESH. A refusal lifts when the standing mends,
                -- when a treaty is signed or when the house's book sells down on its own, and
                -- a button still carrying last turn's reason is the same lie facing the other
                -- way. SELL IS NEVER REFUSED: refusal and the war lock are buy-side only, and
                -- the one thing that greys Sell is holding less than a lot to sell.
                if is_uicomponent(bb) then
                    EX.set_off(bb, why ~= nil)
                    set_tip(bb, why or EX.TIP_BUY)
                end
                EX.draw_sell(bs, res)
            end
            if not offer then EX.draw_spark(row, res) end
        end
    end

    -- TWO LINES, and every string routed through fit(). MEASURED: the trade line needed
    -- 1333px and the offerings line 1333px in an 880px box, and both clipped mid-word on
    -- screen. The split is by MEANING, not by length - line 1 is your position (what you have
    -- and what it costs you), line 2 is the world (what it wants and what has happened to it).
    local footer = find_uicomponent(panel, "footer_text")
    local footer2 = find_uicomponent(panel, "footer_text2")
    local l1, l2 = "", ""
    if offer then
        l1, l2 = EX.offer_footer()
    elseif stats then
        -- 116 chars. THE BOX IS 880px AND THE FONT IS ~6.7px/char, so a fully static footer
        -- line has a hard ceiling near 131 characters - this one shipped at 132 and fit()
        -- amputated "spread wide." in game, leaving the sentence stopped mid-thought. fit()
        -- is the net for footers whose content is unbounded; a line made only of literals
        -- should never reach it. check_footer_literals() pins both of these.
        l1 = "Price rises with scarcity AND concentration: what one faction "
             .. "controls costs more than the same regions spread wide."
        l2 = "Share is the largest producer's portion of world output; the premium is what "
             .. "that concentration adds to the price."
    elseif houses then
        -- ITS OWN BRANCH NOW. It used to fall through to the trade footer, which prints
        -- "Rent: -Ng" and the world appetite summary - a warehouse bill shares can never incur
        -- and a list of what cultures want in GOODS, on the one view that trades neither. And
        -- the dividend, the running total this whole layer turns on, appeared nowhere the
        -- player would look: not in a column total, not in the footer, only inside each row.
        --
        -- Line 1 is bounded by construction: two numbers the game itself caps. Line 2 is now
        -- EX.guild_summary() - the known gap this closed. It used to be a static "Absorb a
        -- house yourself..." formula with the hidden-house count bolted on; that count moved
        -- INTO EX.guild_summary() rather than being dropped (see its own comment), but the
        -- absorb/windup explanation did not migrate anywhere - it was flavour text, not a
        -- live signal, and the two clauses EX.guild_summary already carries plus the hidden
        -- count are already at the "two of two" ceiling check_footer_bounds() holds this to.
        l1 = "Treasury: " .. tostring(faction and faction:treasury() or 0)
        -- THE SAME NUMBER AS THE TRADE FOOTER, deliberately: it is the whole position, goods
        -- and paper together, not the paper alone. A "Worth" that meant one thing on one view
        -- and another on the next is the Supply/Regions mistake with a different label.
        local worth = EX.holdings_value()
        if worth > 0 then l1 = l1 .. "  Worth: " .. worth .. "g" end
        local div = EX.dividend_total()
        if div > 0 then l1 = l1 .. "  Dividends: +" .. div .. "g per turn" end
        l2 = EX.guild_summary()
    elseif faction then
        l1 = "Treasury: " .. tostring(faction:treasury())
        -- WHAT THE POSITION IS WORTH, beside what it costs to keep. The two belong on one
        -- line: rent without a value is a bill with no asset behind it, which is how the
        -- warehouse read for three weeks.
        local worth = EX.holdings_value()
        if worth > 0 then l1 = l1 .. "  Worth: " .. worth .. "g" end
        -- THE ONLY PLACE THE RENT IS EXPLAINED. EX.charge_carry is a direct treasury debit
        -- rather than an effect bundle, so it does not appear as a line item in CA's income
        -- breakdown - if this is ever removed, the gold leaves with no stated cause.
        local carry = EX.carry_total()
        -- "Rent", not "Warehousing", and the Held header says "Held / rent" for the same
        -- reason: one number must not have two names on one panel. That is the exact mistake
        -- the Output column already made, calling itself "Supply" here and "Regions" below.
        if carry > 0 then l1 = l1 .. "  Rent: -" .. carry .. "g" end
        l2 = EX.appetite_summary()
        -- SHAKEN GOES ON LINE 1, not beside the appetite. Line 2 already carries three
        -- clauses whose lists grow, and adding a fourth is what pushed it past the box.
        -- Line 1 is two short fixed-width numbers with ~90 characters spare, so the split is
        -- now "what just happened to you and to the market" / "what the world wants".
        local shaken = EX.shock_summary()
        if shaken then l1 = l1 .. "  " .. shaken end
        -- AND THE CLOSURE, WHERE THE PLAYER ACTUALLY BUYS. The banner was drawn only by
        -- EX.guild_summary, which is the HOUSES footer - so the Trade view said nothing at all
        -- while every Buy on it refused. REPLACES line 2 rather than being appended to it: the
        -- appetite clauses grow with the board and a fourth would overrun the box.
        l2 = EX.closed_banner() or l2
        -- THE EMPTY LEDGER. Everything above still applies on the orders page too - the
        -- world lines are as worth reading there as on the list, same reasoning as the chart
        -- page - but an empty ledger with nothing placed reads as a bare treasury line with
        -- no hint of what the page is even for, so line 1 alone is replaced with the guide.
        if orders and #EX.orders == 0 then
            l1 = "No standing orders. Choose a commodity on the Trade list, then set one "
                .. "on the ticket below."
        end
    end
    if is_uicomponent(footer) then footer:SetStateText(fit(footer, l1)) end
    if is_uicomponent(footer2) then footer2:SetStateText(fit(footer2, l2)) end
    -- THE HOLD OPENED ABOVE THE ROW LOOP CLOSES HERE, on the one exit this function has past
    -- that point. Nothing may read a stance after this: the next refresh builds a fresh vector.
    EX.free_guild()
end

-- THE OFFERINGS VIEW. btn_buy is reused as the Sacrifice button - a third button will not fit
-- (the trade row already ends 18px from the edge) and reusing the cell costs no new GUID,
-- imagepath or soundcategory. btn_sell and spark are absent from this table and are hidden by
-- EX.layout; an unplaced component keeps its last position and would sit over these columns.
EX.PANEL_LAYOUT_OFFER = {
    { "title_text",    20,  14 },
    { "hdr_name",      54,  50, 170 },
    { "hdr_supply",   240,  50,  70 },
    { "hdr_price",    326,  50,  70 },
    { "hdr_trend",    412,  50, 250 },
    { "hdr_hold",     678,  50,  90 },
    { "rows_holder",   20,  78 },
    -- BOTH FOOTERS KEEP THE FULL 880. They reach 114 and 118 characters at worst case in a
    -- box that holds ~131, and this text has clipped mid-word in play twice; the nav cluster
    -- got its own strip below them rather than 90px out of that margin.
    { "footer_text",   20, 636 },
    { "footer_text2",  20, 662 },
    { "close_button", 876,  14 },
    { "btn_help",     838,  14 },
    -- THE NAV STRIP, 696..726 in a 736-tall panel. Right edge at 906, the same as
    -- close_button's, so the two controls line up down the right-hand side. nav_page is
    -- Center-aligned in its 44px box, so "1/4" and "4/4" do not shuffle sideways as you page.
    { "derpy_chd_ex_tab_trade", 20, 698, 108 },
    { "derpy_chd_ex_tab_stats", 136, 698, 108 },
    { "derpy_chd_ex_tab_offer", 252, 698, 108 },
    { "derpy_chd_ex_tab_houses", 368, 698, 108 },
    { "derpy_chd_ex_tab_deals", 484, 698, 108 },
    { "derpy_chd_ex_tab_log",   600, 698, 108 },
    { "derpy_chd_ex_prev", 774, 696 },
    { "nav_page",     816, 701,  44 },
    { "derpy_chd_ex_mode", 876, 696 },
}
EX.ROW_LAYOUT_OFFER = {
    { "divider",      6, 26 },
    { "icon",         6,  2 },
    { "row_name",    34,  5, 170 },
    { "row_supply", 220,  5,  70 },
    { "row_price",  306,  5,  70 },
    { "row_trend",  392,  5, 250 },
    { "row_hold",   658,  5,  90 },
    { "btn_buy",    762,  1 },
}

-- THE HOUSES VIEW. Same components, different places, different widths, different text.
--   row_price  share price, per LOT   row_sell   dividend per SHARE per turn
--   row_supply seat: held / LOST / horde   row_hold   shares held, and this house's dividend
--
-- KNOWN TRADE-OFF, ACCEPTED: row_sell carries the dividend, so this view shows no sell price.
-- It is 10% under Buy as everywhere else, the Sell button's tooltip names it, and the guide
-- has a line for it. The row cannot take a tenth cell - see EX.PANEL_LAYOUT.
--
-- EVERY OFFSET MIRRORS EX.PANEL_LAYOUT / EX.ROW_LAYOUT EXACTLY - this view has the slack for
-- it (up to EX.MAX_ROWS rows against the trade view's 19). The header set is the trade view's,
-- unmoved and unresized; only EX.HEADERS.houses relabels hdr_sell to "Div" and hdr_supply to
-- "Seat", the same way the Stats view relabels hdr_price to "Share".
EX.PANEL_LAYOUT_HOUSES = {
    { "title_text",    20,  14 },
    { "hdr_name",      54,  50, 184 },
    { "hdr_price",    242,  50,  52 },
    { "hdr_sell",     298,  50,  38 },
    -- 12px TO hdr_trend AND NOT ONE LESS. Seat is a tight box, so its label fills it, and
    -- hdr_trend is the only LEFT-aligned header after it - a left-aligned neighbour starts its
    -- text at its own box edge, so the box gap IS the text gap. This is the pair the trade row
    -- once drew as "Trend Last 12 turns".
    { "hdr_supply",   340,  50,  54 },
    -- 46 AND NOT 30, unlike the row cell below it. The header says "Trend" and the row cell
    -- says "^"; they are different components with different text and only the header has
    -- five capitals to fit. Narrowing this to match its column drew "Tr..." twice before.
    { "hdr_trend",    406,  50,  46 },
    { "hdr_spark",    470,  50, 108 },
    { "hdr_hold",     580,  50,  88 },
    -- THE AMOUNT CLUSTER, in the 232px the header row leaves right of hdr_hold (which ends at
    -- 668) - directly above the rows' own Buy and Sell columns at 654 and 762, because that is
    -- what it governs.
    { "btn_amt_down", 676,  46,  26 },
    { "btn_amount",   706,  46, 130 },
    { "btn_amt_up",   840,  46,  26 },
    { "rows_holder",   20,  78 },
    -- BOTH FOOTERS KEEP THE FULL 880. They reach 114 and 118 characters at worst case in a
    -- box that holds ~131, and this text has clipped mid-word in play twice; the nav cluster
    -- got its own strip below them rather than 90px out of that margin.
    { "footer_text",   20, 636 },
    { "footer_text2",  20, 662 },
    { "close_button", 876,  14 },
    { "btn_help",     838,  14 },
    -- THE NAV STRIP, 696..726 in a 736-tall panel. Right edge at 906, the same as
    -- close_button's, so the two controls line up down the right-hand side. nav_page is
    -- Center-aligned in its 44px box, so "1/4" and "4/4" do not shuffle sideways as you page.
    { "derpy_chd_ex_tab_trade", 20, 698, 108 },
    { "derpy_chd_ex_tab_stats", 136, 698, 108 },
    { "derpy_chd_ex_tab_offer", 252, 698, 108 },
    { "derpy_chd_ex_tab_houses", 368, 698, 108 },
    { "derpy_chd_ex_tab_deals", 484, 698, 108 },
    { "derpy_chd_ex_tab_log",   600, 698, 108 },
    { "derpy_chd_ex_prev", 774, 696 },
    { "nav_page",     816, 701,  44 },
    { "derpy_chd_ex_mode", 876, 696 },
}
-- x offsets are the panel's minus the 20px rows_holder inset, exactly as EX.ROW_LAYOUT is to
-- EX.PANEL_LAYOUT. Same COMPONENTS as the trade row, but NOT the same widths, and that is the
-- whole point of this table existing.
--
-- THE NAME COLUMN IS 184, NOT THE TRADE ROW'S 140. Measured in a live campaign 2026-09-07 with
-- uicomponent:TextDimensionsForText on the drawn row_name cells, six of seven house names
-- overflowed a 140px box and were silently ellipsised by fit():
--     Slaves of the Black Dwarf 177   Uzkul Mingol Company 171   Labourfleet of Uzkulak 163
--     Overlords of Zharrduk 162   The Warhost of Zharr 156   The Legion of Azgorh 155
--     Disciples of Hashut 135  <- the only one that ever fit
-- 140 was right for a commodity ("Dwarf Beer" needs 81, the widest, "Carved Obsidian", 120).
-- A FACTION NAME IS NOT A COMMODITY NAME and copying the trade row's width assumed it was.
--
-- The 44px comes off Div and Seat, which this view over-allocated by inheriting the trade
-- row's Sell-price and Supply boxes: Div prints "+4" in 74px and Seat prints "held" in 56.
-- Everything still lands clear of spark at 450 - name ends 218, trend ends 424.
EX.ROW_LAYOUT_HOUSES = {
    { "divider",      6, 26 },
    { "icon",         6,  2 },
    { "row_name",    34,  5, 184 },
    { "row_price",  222,  5,  52 },
    { "row_sell",   278,  5,  38 },
    { "row_supply", 320,  5,  54 },
    { "row_trend",  386,  5,  30 },
    { "spark",      450,  1 },
    { "row_hold",   560,  5,  88 },
    { "btn_buy",    654,  1 },
    { "btn_sell",   762,  1 },
}

-- THE LABEL BETWEEN THE TWO NAV ARROWS. In the guide the strip pages the thing on screen, so
-- it reads page/pages (Task 8) - it used to read a dash, back when the arrows left the guide
-- and printing the number of the view they would land on would have named a view that was not
-- on screen. Now the arrows page the guide itself, so a number is the honest answer again.
-- HOW MANY PAGES THE VIEW ON SCREEN HAS, and which one is showing. Every view answers, so
-- the counter and the arrows read one pair of numbers instead of branching per view.
function EX.page_count()
    if EX.mode == EX.MODE_HELP then return #EX.HELP_PAGES end
    if EX.mode == EX.MODE_LOG then return EX.log_pages() end
    if EX.mode == EX.MODE_HOUSES then return EX.house_pages() end
    -- TRADE'S COUNT IS #EX.trade_pages(), NOT A FIXED NUMBER. It used to read "always two,
    -- even with nothing selected" back when the chart was the only optional page; the orders
    -- ledger made that false the moment it shipped as a second switch - with two switches
    -- there are four combinations and 1-3 pages, and EX.trade_pages is the one place that
    -- already gets all four right, so this only has to defer to it rather than repeat it.
    if EX.mode == EX.MODE_TRADE then
        -- ONE ENTRY PER ENABLED PAGE. Both switches grey the arrows by shortening this list
        -- rather than by arithmetic - see EX.trade_pages.
        return #EX.trade_pages()
    end
    return 1
end
function EX.page_index()
    if EX.mode == EX.MODE_HELP then return EX.help_page end
    if EX.mode == EX.MODE_LOG then return EX.log_page end
    if EX.mode == EX.MODE_HOUSES then return EX.house_page end
    -- CLAMPED, exactly as EX.trade_kind clamps and for the same reason: a switch can be
    -- thrown while the player stands on the page it removes. Unclamped this read "3/2" until
    -- an arrow was pressed, while trade_kind was already correctly showing page 2.
    if EX.mode == EX.MODE_TRADE then
        local n = #EX.trade_pages()
        local at = EX.trade_page or 1
        if at < 1 then at = 1 end
        if at > n then at = n end
        return at
    end
    return 1
end

function EX.nav_label()
    return EX.page_index() .. "/" .. EX.page_count()
end

-- ONE STEP ALONG THE CYCLE, either way. Both arrows walk EX.MODES rather than naming views,
-- so a fifth view is still one line in that table; and both wrap, which is what stops the
-- first and last views being dead ends.
-- ONE PAGE EITHER WAY, WITHIN THE VIEW ON SCREEN. The arrows used to walk EX.MODES; since
-- 2026-09-07 there is a tab per view in the strip beside them, so cycling is a job they no
-- longer have - and paging is the one the log needed, its 60 kept entries against 19 rows
-- leaving 41 unreachable. The guide already worked this way; this makes it the rule.
--
-- -1 then +1 around the modulo, so a step back from page 1 wraps to the last page instead of
-- falling off the front. Lua indexes from 1 and % never returns a negative here.
function EX.step_page(delta)
    local n = EX.page_count()
    if n < 2 then return end          -- one page: nothing to move, and the arrows are greyed
    local at = ((EX.page_index() - 1 + delta) % n) + 1
    if EX.mode == EX.MODE_HELP then
        EX.help_page = at
    elseif EX.mode == EX.MODE_LOG then
        EX.log_page = at
    elseif EX.mode == EX.MODE_HOUSES then
        EX.house_page = at
    elseif EX.mode == EX.MODE_TRADE then
        EX.trade_page = at
    end
    EX.layout()
    EX.refresh_panel()   -- NOT EX.refresh: the function is EX.refresh_panel (see :3499)
end

-- WHICH ARROW GOES WHICH WAY, as a function rather than an argument computed at the click
-- site. The click listener lives inside EX.init and cannot be reached without a live campaign,
-- so with the direction inlined there, swapping the two arrows passed every check in the suite
-- (measured by mutation, 2026-09-07). Out here the harness can press them.
function EX.nav_click(name)
    EX.step_page(name == EX.MODE_PREV and -1 or 1)
end

-- A TAB CLICK. Returns the mode the component selects, or nil if it is not one of ours - so
-- the listener's filter and its handler read the same function and cannot disagree about
-- which components are tabs.
function EX.tab_mode(name)
    for _, m in ipairs(EX.MODES) do
        if name == EX.tab_name(m) then return m end
    end
    return nil
end

-- WHY A TAB IS UNAVAILABLE, or nil if it is not. The tab strip and the harness read the same
-- function, so "which tabs are locked" cannot mean two different things in two places.
--
-- LAYER 1 IS NOT GATED. The commodities market was never Chaos Dwarf - EX.CULTURE_WANTS
-- already prices 25 cultures' appetites - so Trade, Ownership and the Log stay open to
-- everybody.
--
-- THE TWO LOCKED VIEWS ARE LOCKED FOR DIFFERENT REASONS, and conflating them was a real fault.
-- Both used to test EX.covered(), which reads as one rule and is two:
--
--   OFFERINGS genuinely needs a covered race. Every string in the view names a patron, and an
--   uncovered race has none written for it - the view would draw sentences about an altar
--   that does not exist.
--
--   HOUSES needs HOUSES, which is a different question entirely. EX.HOUSE_CULTURE follows the
--   player whatever their culture, so the rows are discovered, priced, traded and settled for
--   an uncovered race exactly as for a covered one. Measured in a live Southern Realms
--   campaign, 2026-09-08: seven houses discovered, two delisted and settled correctly, the
--   whole view working - and the tab greyed over the top of it. Nothing about equity in your
--   own people's factions requires a patron.
--
-- So Houses now asks whether there is anything to list. That un-greys the view for the 23
-- cultures this mod does not cover, not only for the one that prompted it.
--
-- DISABLED, NOT HIDDEN, and with a reason - the standard stated at the tab strip. Hiding one
-- would shuffle the other four sideways every time the player changed view.
function EX.tab_locked(mode)
    if mode == EX.MODE_OFFER and not EX.covered() then
        return "The Exchange keeps no altar for your people. Offerings are closed."
    end
    if mode == EX.MODE_HOUSES and (EX.houses == nil or #EX.houses == 0) then
        return "The Exchange lists no shares in your people's houses."
    end
    return nil
end

-- HAS THIS PLAYER MET THE PANEL BEFORE? Read through EX.getp, so each human in a
-- multiplayer campaign answers for themselves.
function EX.intro_seen()
    return EX.getp(EX.SAVE_INTRO) == true
end

-- MARKED ON THE WAY OUT, NOT ON THE WAY IN. Marking it when the introduction is shown would
-- spend the one showing on a player who alt-F4'd before reading a line of it; marking it when
-- they leave means they have at least clicked something. Saved immediately, because the panel
-- is not a turn boundary and nothing else here would write it.
function EX.mark_intro_seen()
    if EX.intro_seen() then return end
    EX.setp(EX.SAVE_INTRO, true)
end

function EX.set_mode(mode)
    if EX.mode == mode then return end
    -- ANY TAB CLICK RETIRES THE INTRODUCTION. There is no dismiss button; leaving IS the
    -- dismissal, and it is recorded before the view changes so a locked target that returns
    -- early below cannot leave the player stuck on the page forever.
    if EX.mode == EX.MODE_INTRO then EX.mark_intro_seen() end
    -- A DISABLED COMPONENT CAN STILL DELIVER A CLICK in some engine states, and this is the
    -- one place both routes into a view meet. Without it a locked view opens on rows nothing
    -- ever wrote text for.
    if EX.tab_locked(mode) then return end
    -- EVERY VIEW OPENS ON ITS FIRST PAGE. Persisting one would reopen the log three pages
    -- back from the event the player clicked "Log" to read, and the guide on a page about a
    -- system they have since switched off in MCT.
    if mode == EX.MODE_LOG then EX.log_page = 1 end
    if mode == EX.MODE_HELP then EX.help_page = 1 end
    if mode == EX.MODE_HOUSES then EX.house_page = 1 end
    -- Trade reopens on the list, not on whatever chart was last up.
    if mode == EX.MODE_TRADE then EX.trade_page = 1 end
    -- AND THE SORT, for the reason written beside EX.SORT_VALUE.
    EX.sort_col, EX.sort_dir = nil, 1
    EX.mode = mode
    EX.layout()
    EX.refresh_panel()
end

-- IS IT THE PLAYER'S TURN? The exchange is the player's panel and it belongs to the player's
-- turn: prices settle at turn start, and the AI round is 920x736 of map the panel would be
-- sitting on top of. EX.show(false) on FactionTurnEnd takes the panel away; this stops it
-- coming straight back.
--
-- ASKED, NOT REMEMBERED. A flag set on FactionTurnEnd and cleared on FactionTurnStart is wrong
-- after a load, which restores neither - and a stale "it is the AI's turn" would be a dead
-- button with nothing on screen to explain it. `is_factions_turn_by_key` is documented on
-- WORLD_SCRIPT_INTERFACE and answers from the model, so a load cannot desync it.
--
-- IT FAILS OPEN. If the call ever throws - a renamed interface in a patch, a null world during
-- a transition - the player keeps the panel they had. A probe that errors must never be the
-- thing that locks somebody out of their own mod, and the worst case of allowing it is the
-- behaviour that shipped for the last twenty builds.
function EX.player_turn()
    local ok, mine = pcall(function()
        return cm:model():world():is_factions_turn_by_key(EX.me())
    end)
    if not ok then return true end
    return mine ~= false
end

-- The opener button, greyed while it is not the player's turn. SetDisabled and not
-- SetVisible: a button that vanishes and comes back reads as a bug, and the strip would shuffle
-- around the hole. The click listener refuses the press regardless (see EX.player_turn there) -
-- this is the affordance, not the guard, and the two are deliberately independent.
function EX.gate_button(on)
    local b = find_uicomponent(core:get_ui_root(), EX.BUTTON)
    EX.set_off(b, not on)
end

function EX.show(visible)
    local panel = EX.panel()
    if not is_uicomponent(panel) then
        if not EX.build_panel() then return end
        panel = EX.panel()
    end
    if visible then
        -- THE FIRST OPENING OF A CAMPAIGN LANDS ON THE INTRODUCTION. Here rather than in
        -- EX.build_panel, because the panel is built once and shown many times - and the
        -- panel outlives a load while the answer to "has this player read it" does not.
        --
        -- It also has to be here rather than at init: EX.bind_race has resolved by the time
        -- anything can click the opener, and every line of the page names the race, the
        -- market or the patron.
        if not EX.intro_seen() then EX.mode = EX.MODE_INTRO end
        EX.layout()
        EX.refresh_panel()
    end
    panel:SetVisible(visible)
    -- AND IT EATS THE MOUSE WHILE IT IS UP. Without this the panel is scenery: the cursor
    -- reaches the campaign map straight through 920x736 of background, so hovering a row
    -- raises the region and army tooltips of whatever happens to be behind the panel.
    -- CA's own words for the flag: "Interactivity determines if a component can handle mouse
    -- interactions like clicks and mouseovers" - a component that cannot handle them does not
    -- consume them either. An interactive CONTAINER is CA's norm and not a risk to its
    -- children; the rituals panel ships agent_list, bottom and action all interactive with
    -- working children inside them.
    --
    -- TIED TO VISIBILITY, IN THE ONE PLACE VISIBILITY CHANGES. Interactive-while-hidden would
    -- be a 920x736 dead zone in the middle of the map that nothing on screen explains, which
    -- is a far worse bug than the one this fixes. check_panel_blocks_map refuses a literal
    -- true here for exactly that reason.
    panel:SetInteractive(visible)
end

-- ---------------------------------------------------------------------------------------
-- Trading.
-- ---------------------------------------------------------------------------------------

-- ===========================================================================================
-- OPTION A: somebody is on the other side of the trade.
-- ===========================================================================================

-- Move a house's treasury, bounded by the cap and by what it actually has. Returns what was
-- really moved, which is not always what was asked for.
--
-- cm:treasury_mod takes a faction KEY STRING and pays any faction on the map - measured
-- 2026-09-04, and EX.settle_counterparty has been relying on it ever since.
function EX.pay_house(house, amount)
    if not EX.setting("ai_gold") then return 0 end
    if amount == 0 then return 0 end
    if amount > EX.opt("house_cash_max") then amount = EX.opt("house_cash_max") end
    if amount < -EX.opt("house_cash_max") then amount = -EX.opt("house_cash_max") end
    if amount < 0 then
        local f = cm:get_faction(house)
        -- cm:get_faction returns FALSE, not nil, for a key it does not know.
        if not f or f:is_null_interface() then return 0 end
        local ok, gold = pcall(function() return f:treasury() end)
        if not ok or not gold then return 0 end
        if -amount > gold then amount = -gold end
        if amount >= 0 then return 0 end
    end
    cm:treasury_mod(house, amount)
    return amount
end

-- EX.pay_house with the world tier's ceiling. Kept separate rather than parameterised because
-- the two caps differ by an order of magnitude and reading pay_house(x, y, cap) at a call site
-- tells you nothing about which tier you are in.
function EX.pay_actor(faction, amount)
    if not EX.setting("ai_gold") then return 0 end
    if amount == 0 then return 0 end
    local cap = EX.opt("world_cash_max")
    if amount > cap then amount = cap end
    if amount < -cap then amount = -cap end
    if amount < 0 then
        -- THE SCANNED TREASURY, not a cm:get_faction. The scan read it this turn and the whole
        -- tier is built on not re-fetching it ~80 times.
        local gold = ((EX.actors or {})[faction] or {}).gold or 0
        if -amount > gold then amount = -gold end
        if amount >= 0 then return 0 end
    end
    cm:treasury_mod(faction, amount)
    return amount
end

-- THE GUILD HOUSE ON THE OTHER SIDE, or nil. A house at war has left the pool entirely, and
-- that war test is the only one here.
--
-- A HOUSE REFUSING YOU IS NOT TESTED FOR, and this comment used to claim that it was. There is
-- no such test in the code below and there does not need to be: EX.trade refuses a blocked buy
-- outright, before settlement is ever reached, so a second test would be unreachable. Left as
-- the accurate statement rather than as an aspirational one - a comment that contradicts the
-- code beside it is the worst failure mode this file has.
--
-- HOUSES ARE NOT COMMODITIES, same rule EX.book_shift and EX.refused_by already follow. A
-- share is paper; the guild holds no book in it, and without this guard a house trading its
-- own shares can be found as its own counterparty - through its own treasury, on the sell
-- side - which is not a real trade and only corrupts the paper-share bookkeeping.
function EX.guild_counterparty(res, is_buy)
    if EX.is_house(res) then return nil end
    local best, best_n = nil, 0
    for _, house in ipairs(EX.guild()) do
        if EX.treaty_tier(house) ~= "war" then
            local n = EX.book_of(house, res)
            if is_buy then
                -- It can only sell you what it holds.
                if n > best_n then best, best_n = house, n end
            else
                -- It buys with gold, so size the choice on treasury rather than on book.
                local f = cm:get_faction(house)
                if f and not f:is_null_interface() then
                    local ok, gold = pcall(function() return f:treasury() end)
                    if ok and gold and gold > best_n then best, best_n = house, gold end
                end
            end
        end
    end
    return best
end

-- THE WORLD TIER'S COUNTERPARTY. Same shape as EX.guild_counterparty, without the treaty test:
-- a world actor has no guild membership to leave. On a buy it can only sell what it holds; on
-- a sell it buys with gold, so the choice is sized on the scanned treasury.
function EX.world_counterparty(res, is_buy)
    if EX.is_house(res) or EX.is_layer2(res) then return nil end
    if not EX.setting("ai_world") then return nil end
    local best, best_n = nil, 0
    for faction, info in pairs(EX.actors or {}) do
        -- EVERY HUMAN IS EXCLUDED, same rule and same reason as EX.step_world: EX.actors is
        -- built in EX.scan_supply from every landholding faction whose culture is not Chaos
        -- Dwarf, with no human filter on that path - a Chaos Dwarf human is already out of
        -- EX.actors by culture, so the reachable case is a non-Chaos-Dwarf human (the mixed
        -- multiplayer board EX.pool_absent and EX.LAYER2 already support). Without this, that
        -- player is routed to as rung 2's counterparty and both charged and credited the same
        -- price by EX.trade and this function - a free trade. Filtered HERE, the shared reader
        -- both callers of this function go through, not at a call site.
        if not EX.is_human(faction) then
            local n
            if is_buy then n = EX.world_sellable(faction, res) else n = info.gold or 0 end
            if n > best_n then best, best_n = faction, n end
        end
    end
    return best
end

-- NOBODY IS HOLDING ANY. Returns the largest landholder so the tooltip can still name somebody
-- - "Karaz-a-Karak holds the last of it" is a refusal a player can act on; "sold out" is not.
-- Returns nil while stock remains, and nil outright when the switch is off, which is today's
-- shipped behaviour: top_holder as the unbounded fallback.
function EX.sold_out(res)
    if not EX.setting("world_scarcity") then return nil end
    -- AND ai_world. Ruled 2026-09-13 in the pre-flight scan: with the world tier off the world
    -- book is empty by definition, so scarcity alone would report every commodity the guild does
    -- not happen to hold as sold out - taking the market away, which is the worst failure this
    -- feature can produce. The two switches must not combine into a refusal nobody asked for.
    if not EX.setting("ai_world") then return nil end
    if EX.is_house(res) or EX.is_layer2(res) then return nil end
    if EX.guild_book(res) > 0 then return nil end
    -- A COMMODITY THE WORLD TIER CAN NEVER SUPPLY IS NOT ITS TO REFUSE. Every producer smaller
    -- than one lot floors to zero capacity - see EX.world_capacity - so without this, a thin
    -- commodity (the shipped case: glass, 6 units a turn against a 10-unit lot) is refused from
    -- turn 1 for the life of the campaign, at default settings. "Never a participant" is not
    -- scarcity; only a drained EX.world_potential > 0 is.
    if EX.world_potential(res) == 0 then return nil end
    -- SUPPLY, NOT THE NET BOOK. Task 9 made the world book a position, and a position nets to
    -- zero across the map by construction - so testing it here refused every commodity the
    -- guild did not happen to be long, which is most of the board, every turn.
    if EX.world_supply(res) > 0 then return nil end
    return EX.top_holder(res) or "unknown"
end

-- The largest holder of the commodity is the counterparty, and the gold moves to or from their
-- treasury. cm:treasury_mod takes a faction KEY STRING, so any faction on the map can be paid -
-- measured 2026-09-04.
--
-- This is what stops the exchange being a hole in the world that gold falls into. It also makes
-- buying a political act: cornering iron means paying whoever owns the iron, who is quite
-- possibly the faction you are arming against.
-- `only` NAMES THE COUNTERPARTY AND SKIPS THE WALK (Stage 2, Task 4). A deal is struck with
-- one faction and the page prints its name, so the gold has to move to or from THAT faction -
-- a panel that says one name and pays another is the same class of lie as a quoted price that
-- is not the price charged. With `only` given there is NO FALLBACK: the guild rung is skipped,
-- and if the named faction cannot settle, this returns nil rather than quietly paying whoever
-- the preference order would have found instead.
function EX.settle_counterparty(res, is_buy, price, only)
    -- Layer 2 has no map holder. Armaments and Raw Materials come out of the Forge, not off
    -- somebody's land, so there is nobody to pay.
    if EX.is_layer2(res) then return nil end

    -- PREFERENCE ORDER, spec 8.2. A guild house holding the book first; the world tier second
    -- (Rung 2, below); today's top_holder third. Rung 3 is deliberate and unchanged -
    -- "cornering iron means paying whoever owns the iron" - and it is also the empty-guild
    -- path, which is most campaigns.
    -- SKIPPED ENTIRELY FOR A NAMED COUNTERPARTY - see `only` above.
    local g = nil
    if not only then g = EX.guild_counterparty(res, is_buy) end
    -- THE SAME FLAT-CAP MISMATCH RUNG 2 WAS FIXED FOR, one tier up. EX.apply_trade moves the
    -- player's full uncapped price through cm:treasury_mod; EX.pay_house clamps the house's own
    -- leg at house_cash_max. Above that cap the two legs disagree and the difference is minted
    -- on a sell or destroyed on a buy. Checked BEFORE EX.pay_house, because cm:treasury_mod
    -- cannot be un-rung once called.
    --
    -- UNREACHABLE AT ALL FOUR SHIPPED PRESETS and reachable under Custom: the top ladder price
    -- runs 3.7k to 21.7k against caps of 20k to 60k, but a Custom ladder_step of 1.30 gives a
    -- 146k top price against a house_cash_max a player may set to 5,000. Fixed here rather than
    -- inside EX.pay_house because the cap is a deliberate per-turn budget for the guild's OWN
    -- trading in EX.step_books, where nothing uncapped sits opposite it.
    if g and EX.setting("ai_gold") and price > EX.opt("house_cash_max") then g = nil end
    if g then
        local moved = EX.pay_house(g, is_buy and price or -price)
        -- THE BOOK MOVES EVEN WHEN THE GOLD DOES NOT. With MCT's ai_gold off, EX.pay_house
        -- returns 0 by design and the books go NOTIONAL (spec 13) - they are not frozen.
        -- Gating the book on `moved ~= 0` froze them: the player bought a lot, the house stayed
        -- at 20, the gold went to the top land-holder through the fallback below instead, and
        -- the houses went on buying four lots a turn for free. The book ran away in one
        -- direction and book_shift with it, which is exactly what the next paragraph forbids.
        --
        -- STILL GATED ON `moved ~= 0` WHEN GOLD IS ON, because there that zero means something
        -- else: the house could not pay, so it did not buy your lot and the fallback should
        -- take the trade.
        if moved ~= 0 or not EX.setting("ai_gold") then
            -- THE LOT CAME FROM SOMEWHERE. A book that never falls makes the guild an
            -- infinite seller and the price effect in Task 3 stops meaning anything. The book
            -- counts LOTS - EX.house_budget adds lot-counts, bounded by BOOK_TRADE_MAX - not
            -- raw commodity units, and a player trade always moves exactly one lot, so the
            -- book moves by exactly 1, not by EX.lot(res).
            local n = EX.book_of(g, res)
            EX.set_book(g, res, is_buy and (n - 1) or (n + 1))
            -- math.abs(moved), which is 0 with ai_gold off - and EX.trade's log line then says
            -- "(only 0)", which is the honest report of a notional settlement.
            return g, math.abs(moved)
        end
    end

    -- RUNG 2, the world tier. Between the guild and top_holder: a guild house is still
    -- preferred (it is the deeper relationship and the one the panel names), but an actor
    -- actually holding the goods beats a landholder who merely owns the ground they came from.
    local w = only or EX.world_counterparty(res, is_buy)
    -- F2, FINAL REVIEW 2026-09-13. DECLINE UPFRONT WHEN THE FLAT CAP ALONE WOULD SHORT THE
    -- TRADE - checked BEFORE anything is paid, not after. EX.apply_trade always charges or
    -- credits the PLAYER the full, uncapped `price` via cm:treasury_mod, while EX.pay_actor
    -- clamps the actor's own leg at world_cash_max (3000 default, 1500 easy). Above the cap the
    -- two legs disagreed and the difference was minted (a player sell) or destroyed (a player
    -- buy) every single trade, silently, on ordinary prices - the ladder passes world_cash_max
    -- around rung 37 of 42 at default settings.
    --
    -- CHECKED AGAINST `price` DIRECTLY, NOT AGAINST WHAT EX.pay_actor WOULD RETURN, and this
    -- is deliberate: cm:treasury_mod, once called, cannot be un-rung, so the check has to
    -- happen before EX.pay_actor is ever called, not after reading its result back. It is also
    -- why this gate is price > cap and not "the actor cannot afford it" - the actor's OWN gold
    -- shortfall (poverty) is left untouched below, same as it always was and same as rung 3's
    -- own documented trade-off ("a poor counterparty does mint a little gold... bounded by
    -- their treasury") - a real, if small, treasury is the bound rung 3 already accepts. Only
    -- the FLAT, ARTIFICIAL cap being tighter than that is the thing this task fixes; declining
    -- on poverty too would have EX.pay_actor's OWN debit clamp fire, `moved` fall short of
    -- `price` there instead, and the actor would still have been paid a partial, real amount
    -- before this function ever finds out - undoing that would need reversing a
    -- cm:treasury_mod that already ran, which is the same "cannot be un-rung" problem in a
    -- different place. A price-vs-cap comparison needs no such reversal: it never calls
    -- EX.pay_actor at all when it declines, so nothing is ever paid to undo.
    if w and EX.setting("ai_gold") and price > EX.opt("world_cash_max") then
        w = nil
        -- DECLINED: EX.pay_actor was never called, so no gold moved and the book below did
        -- not either. Falls through to EX.top_holder, unclamped by world_cash_max, same as if
        -- EX.world_counterparty had found nobody at all.
        --
        -- A NAMED COUNTERPARTY DECLINED HERE IS REFUSED BY THE `only` GUARD ABOVE RUNG 3,
        -- which every fall-through reaches. A second `if only then return nil end` right
        -- here was written first and deleted after the mutation round showed it could not
        -- be made to fail on its own - both guards caught the same case and only one is
        -- needed. Two guards for one failure is one guard nobody can test.
    end
    if w then
        local moved = EX.pay_actor(w, is_buy and price or -price)
        if moved ~= 0 or not EX.setting("ai_gold") then
            -- SPEND THE SCANNED TREASURY AS A PER-TURN BUDGET, same rule and same reason as
            -- EX.step_world's own match: EX.actors[w].gold is read fresh from the scan once a
            -- turn and nothing else writes it back on this path, so without this line a player
            -- selling (or buying) from the same actor repeatedly in one turn meets the
            -- identical, unclamped treasury every time - `moved` is already signed (positive
            -- paid TO the actor, negative taken FROM them), so one line covers both directions.
            local wi = (EX.actors or {})[w]
            if wi then wi.gold = wi.gold + moved end
            -- THE BOOK MOVES EVEN WHEN THE GOLD DOES NOT, the same rule and the same reason as
            -- the guild rung above: gating the book on moved ~= 0 freezes it with ai_gold off
            -- and the tier becomes an infinite seller again.
            local n = EX.world_book_of(w, res)
            EX.set_world_book(w, res, is_buy and (n - 1) or (n + 1))
            return w, math.abs(moved)
        end
    end

    -- CORNERING A COMMODITY MUST NOT TRAP IT. F2, REVIEW 2026-09-13: EX.top_holder used to
    -- return the player outright and the two lines below refused the trade - which was harmless
    -- while a refusal here silently minted the gold instead, but B2 turned that same nil into an
    -- outright "nobuyer" refusal, and "a position carried in from an older save has to be
    -- closable" (above) and "blocking a sell traps the player's capital with no exit" (EX.apply_
    -- trade's own unavailable-guard comment) both say this file's standard is the opposite.
    -- Skipping the player inside EX.top_holder itself finds the SECOND-largest holder instead,
    -- so a cornering player can still close the position against whoever holds the next pile.
    -- Only when the player is the ONLY holder does this come back nil, same as before.
    -- RUNG 3 IS NOT REACHABLE FOR A NAMED COUNTERPARTY EITHER. Falling here means the named
    -- faction could not pay (EX.pay_actor returned 0 with ai_gold on); the answer to that is a
    -- refusal, not a different faction.
    if only then return nil end

    local who = EX.top_holder(res, EX.who())
    if not who then return nil end

    local moved = price
    if not is_buy then
        -- They pay for what you sell, but only out of gold they actually have. The player is
        -- credited the full price either way - the panel must not lie about a sale - so a poor
        -- counterparty does mint a little gold. That is the honest trade-off, and it is bounded
        -- by their treasury rather than unbounded the way the old round trip was.
        local f = cm:get_faction(who)
        -- cm:get_faction returns FALSE, not nil, for a key it does not know.
        if not f or f:is_null_interface() then return nil end
        local t = f:treasury()
        if t < moved then moved = t end
        if moved <= 0 then return nil end
    end
    cm:treasury_mod(who, is_buy and moved or -moved)
    return who, moved
end

-- THE CLICK. In singleplayer this calls EX.apply_trade on the spot, exactly as it always did;
-- in multiplayer it hands the order to the network and EX.apply_trade runs from the UITrigger
-- on every machine, including this one. Nothing is validated here on purpose - the checks and
-- the gold have to happen in the same pass, on the same machine, or a trade the sender thought
-- was legal moves gold on the clients that disagreed.
function EX.trade(res, is_buy)
    -- The amount rides ON the op rather than being read from EX.amount on the far side: in
    -- multiplayer the op is applied on every machine, and EX.amount is the LOCAL player's
    -- session state - reading it there would have each machine trading its own operator's
    -- current setting. EX.ORD_FS is the separator the order ops already use.
    EX.mp_send(is_buy and "buy" or "sell", res .. EX.ORD_FS .. tostring(EX.amount))
end

-- N LOTS AS N REAL TRADES, not one trade of N lots. Clicking Buy twenty-five times is what
-- this replaces, and it must cost and move exactly what that cost and moved - the same
-- per-trade counterparty walk, the same hostility, the same book drawdown, the same log
-- lines. A bulk path with its own arithmetic would be a second pricing model to keep in
-- agreement with the first.
--
-- IT STOPS AT THE FIRST REFUSAL. Twenty-five attempts against an empty treasury is
-- twenty-five identical "cannot afford" lines in the log and twenty-five counterparty walks
-- for nothing. The first no ends the run, and whatever filled before it stands.
function EX.bulk_trade(arg, is_buy)
    local res, n = arg, 1
    -- NO PLAIN FLAG. See the note above EX.display: string.find(s, p, 1, true) corrupts WH3's
    -- string subsystem process-wide. EX.ORD_FS is matched as a PATTERN, which is safe for the
    -- same reason EX.unpack_orders can build "[^,]+" out of it - it carries no pattern magic.
    local cut = string.find(tostring(arg), EX.ORD_FS)
    if cut then
        res = string.sub(arg, 1, cut - 1)
        n = EX.clamp_lots(string.sub(arg, cut + 1))
    end
    local done, last = 0, nil
    -- ONE LOG LINE FOR A MULTI-LOT CLICK: EX.apply_trade totals into EX.bulk instead of logging
    -- each lot. Cleared on every exit, an error included, or every later trade would go silent.
    EX.bulk = (n > 1) and { gold = 0, units = 0 } or nil
    local ok, err = pcall(function()
        for _ = 1, n do
            last = EX.apply_trade(res, is_buy)
            if last ~= true then break end
            done = done + 1
        end
    end)
    local b = EX.bulk
    EX.bulk = nil
    if not ok then error(err, 0) end
    if n > 1 then
        EX.say("trade", (is_buy and "bulk buy " or "bulk sell ") .. done .. "/" .. n
            .. " lots of " .. tostring(res)
            .. ((last ~= true) and (" - stopped: " .. tostring(last)) or ""))
    end
    EX.log_bulk(res, is_buy, n, done, last, b)
    return done
end

-- The guild's markup on the lot just traded, as a sentence to append to its Log line, or "".
-- Same realised figure the cell and the tooltip use; see EX.sell_tip.
function EX.markup_note(res, is_buy)
    local h = EX.hostility(res)
    if h == 0 then return "" end
    local cp = EX.hostility_source(res)
    return "  " .. (cp and EX.faction_display(cp) or "The guild")
        .. (h > 0 and " dislikes you: " or " likes you: ")
        .. EX.markup_pct(res, is_buy) .. "% "
        .. ((h > 0) == is_buy and "more" or "less") .. "."
end

-- WHY A CLICK STOPPED, for the two refusals EX.apply_trade does not log itself. Both reached
-- the script log only, so a Buy with too little gold or a Sell with too little held did
-- nothing on screen at all.
EX.TRADE_STOP = {
    afford  = "Not enough gold.",
    nothold = "You hold less than one lot.",
}

-- The Log's account of one click: the whole of a multi-lot one in a single line, and a refusal
-- that stopped it if EX.apply_trade left that unsaid.
function EX.log_bulk(res, is_buy, n, done, last, b)
    local stop = (last ~= true) and EX.TRADE_STOP[last] or nil
    pcall(function()
        local nm = EX.log_subject(res)
        if b and done > 0 then
            local line = (is_buy and "Bought " or "Sold ") .. b.units .. " for " .. b.gold .. "g"
                .. ((done < n) and (", " .. done .. " of " .. n .. " lots.")
                                or (" in " .. n .. " lots."))
            if stop then line = line .. " " .. stop end
            EX.log_add(nm, line .. EX.markup_note(res, is_buy), res)
        elseif done == 0 and stop then
            EX.log_add(nm, (is_buy and "Buy refused. " or "Sell refused. ") .. stop, res)
        end
    end)
end

EX.MP_OPS.buy  = function(arg) EX.bulk_trade(arg, true) end
EX.MP_OPS.sell = function(arg) EX.bulk_trade(arg, false) end

-- RETURNS true ON A FILL, or a reason token. Additive: every caller before 2026-09-10
-- ignored the return, and EX.fill_orders is the first to read it. The tokens are classified
-- by EX.ORDER_FATAL and given sentences by EX.ORDER_REASON.
-- TWO OPTIONAL PARAMETERS, ADDED IN STAGE 2 TASK 4, both defaulted to today's behaviour so
-- every existing caller is byte-identical. `unit_px` is the price one lot settles at when
-- the caller has already agreed one (a deal off the Deals page); `only` is the faction that
-- must be on the other side of it.
--
-- NO `lots` PARAMETER, AGAINST THE PLAN'S OWN INTERFACE TABLE. EX.bulk_trade already answers
-- that question - "N LOTS AS N REAL TRADES, not one trade of N lots... a bulk path with its
-- own arithmetic would be a second pricing model to keep in agreement with the first" - and
-- that ruling predates this stage and is still right. EX.accept_deal loops the same way.
--
-- ONE STANCE VECTOR PER TRADE, built fresh and freed on every exit. This used to FREE the memo
-- and run unheld, so EX.blocked, EX.buy_price and the log line each walked the guild once per
-- holder - 2,896 cm:get_faction calls a lot at 105 houses, the ~0.6s before "bought" on every
-- click. hold_guild drops any older hold first, so SEE EX.bind_player still holds: the memo
-- is always the bound player's. The pcall is so an error cannot strand it - a stranded hold
-- would price every tooltip off this trade's diplomacy until the next refresh.
function EX.apply_trade(res, is_buy, unit_px, only)
    EX.hold_guild()
    local ok, r = pcall(EX.apply_trade_held, res, is_buy, unit_px, only)
    EX.free_guild()
    if not ok then error(r, 0) end
    return r
end

function EX.apply_trade_held(res, is_buy, unit_px, only)
    local faction = EX.who()
    if not faction then return "nofaction" end
    -- A SETTLED BOOK TAKES NO ORDERS, in either direction. The position was paid out and
    -- zeroed, so a buy here would mint paper in a house that no longer exists and a sell
    -- would find nothing to sell.
    --
    -- AND NEITHER DOES A HOUSE THAT IS ALREADY DEAD BUT NOT YET SETTLED. EX.is_delisted alone
    -- was not enough, because EX.check_delistings runs at FactionTurnStart and nowhere else:
    -- kill a house during your own turn - take its last region, or confederate it with a Tower
    -- of Zharr seat claim - and it stays is_delisted == false until you end the turn. Its price
    -- does not move either, because EX.house_power_of reads EX.house_regions, a turn-start
    -- snapshot. So the board still offers the last LIVING price on a corpse: buy every lot the
    -- treasury can carry, end turn, and EX.settle_house pays it out at EX.BUYOUT_PREMIUM.
    -- Risk-free 25% on the whole treasury, repeatable once per house killed, and it inverts the
    -- hook exactly - "buy the house BEFORE you take its seat" becomes "buy it after, for free".
    if EX.is_house(res) and (EX.is_delisted(res) or EX.house_gone(res)) then
        EX.say("trade", res .. " is delisted or gone")
        return "delisted"
    end
    -- cm:perform_ritual(performing faction key, target faction key, ritual key). The DB row
    -- carries the gold cost and the pooled-resource movement, so affordability, the treasury
    -- line item and the holdings change are all the engine's, not ours.
    local lot = EX.lot(res)
    local pool = EX.hold_key(res)
    -- A sell must be checked here: the goods no longer ride on the cost record, so the engine
    -- has nothing to refuse with.
    if not is_buy and EX.held(res) < lot then
        EX.say("trade", "not enough " .. pool .. " to sell")
        return "nothold"
    end
    -- No producer anywhere means no seller. See EX.unavailable. Selling is deliberately still
    -- allowed: the held-check above already gates it, and a position carried in from an older
    -- save has to be closable.
    if is_buy and EX.unavailable(res) then
        EX.say("trade", "no offer - nothing on this map produces " .. res)
        return "unavailable"
    end
    -- BUYS ONLY. A house that despises you is delighted to take your goods cheap, and
    -- blocking a sell traps the player's capital with no exit - the lockout that actually
    -- hurts, as opposed to the one that merely costs money.
    if is_buy and EX.blocked(res) then
        EX.say("trade", "no offer - " .. EX.blocked(res) .. " will not sell to you")
        -- THE LOG GETS THE REASON, not the fact. EX.buy_refusal is the same sentence the
        -- button and its tooltip carry, so the three cannot drift into disagreeing about why
        -- a click did nothing - which is the whole complaint this view answers.
        local why = EX.buy_refusal(res)
        pcall(function()
            EX.log_add(EX.log_subject(res), "Buy refused. " .. tostring(why), res)
        end)
        return "blocked"
    end
    -- buy_price, NOT price. EX.price is the world price; what the player pays includes the
    -- guild's hostility markup, and the panel draws the same number.
    -- AN AGREED PRICE IS NOT MARKED UP. buy_price and sell_price carry the guild's hostility
    -- markup, which is the guild's cut of a guild trade; a deal is struck directly with the
    -- faction on the page, at the number the page printed, and that number is already off market
    -- by EX.DEAL_EDGE in the player's favour.
    local price = unit_px or (is_buy and EX.buy_price(res) or EX.sell_price(res))
    local fac = cm:get_faction(faction)
    if is_buy and fac:treasury() < price then
        EX.say("trade", "cannot afford " .. price .. " for " .. pool)
        return "afford"
    end

    -- WHY THIS DOES NOT CALL cm:perform_ritual. Measured in game 2026-09-04: perform_ritual
    -- applies the ritual's pooled side but NEVER charges the treasury - gold went 4900 -> 4900
    -- across a 621 trade, while the goods moved the full 10. Calling it and also moving the
    -- goods here double-granted them (+20 for one lot). So the trade is these two calls and
    -- nothing else, which also guarantees the price charged is exactly the price displayed.
    --
    -- cm:treasury_mod DOES take a negative - measured, 5000 -> 4900 on -100 - despite the
    -- design doc's claim that CA restricts it to positive values.
    --
    -- The factor argument must be the pooled_resource_factors KEY ("other"), not our
    -- pooled_resource_factor_junctions unique_id: passing the junction id succeeds and moves
    -- nothing at all, with no error.
    if not EX.pool_live(res) then
        EX.say("trade", "REFUSED - " .. pool .. " is not registered on " .. faction
            .. "; charging for it would take the gold and grant nothing")
        pcall(function()
            EX.log_add(EX.log_subject(res),
                "Trade refused: this market is not open to your people.", res)
        end)
        return "nopool"
    end
    -- CONSULT SETTLEMENT FIRST. EX.settle_counterparty reads only the counterparty's treasury
    -- and the books, never the player's, so hoisting it above the player's own cm:treasury_mod
    -- is free - and it has to happen first, because cm:treasury_mod cannot be un-rung once
    -- called. See the "NOBODY CAN PAY FOR THIS" guard immediately below for why the order
    -- matters.
    local who, moved = EX.settle_counterparty(res, is_buy, price, only)
    -- NOBODY CAN PAY FOR THIS. EX.apply_trade credits the player the full price through
    -- cm:treasury_mod, and until 2026-09-13 it did so BEFORE asking who was on the other side -
    -- so a sell that found no counterparty at all minted the whole price out of nothing. That
    -- is the oldest of the three leaks this effort found and the only one that predates it.
    --
    -- BUY IS DELIBERATELY NOT REFUSED HERE. A buy with no counterparty destroys gold rather
    -- than minting it, which is a sink and not an exploit; EX.blocked already refuses the buy
    -- cases that matter, and refusing more of them here would take the market away for the
    -- commodity a player has cornered - they are the top holder, which is why rung 3 can
    -- return nil, but only when the player is the SOLE holder. F2 gave EX.top_holder its
    -- optional skip parameter, so with a second holder present rung 3 falls through to them
    -- instead of returning nil.
    --
    -- ONLY A COMMODITY HAS A MAP HOLDER TO PAY, SO ONLY A COMMODITY CAN FAIL TO FIND ONE. F1,
    -- REVIEW 2026-09-13: the guard first shipped here named a single exempt case (houses) where
    -- the general rule was needed, and that omission refused every Layer 2 sell (Armaments,
    -- Raw Materials) forever, at shipped defaults - EX.settle_counterparty's own first line is
    -- `if EX.is_layer2(res) then return nil end`, "Armaments and Raw Materials come out of the
    -- Forge, not off somebody's land, so there is nobody to pay". `who` is structurally nil for
    -- Layer 2 always, not occasionally - the same shape of defect as the house case below, one
    -- tier over. EX.is_commodity(res) is true only for the seventeen commodities, so it excludes
    -- both Layer 2 and Layer 3 (houses) in the one test a house's own exemption needed anyway.
    --
    -- THE WORKED EXAMPLE, KEPT: A HOUSE'S OWN PAPER IS ALSO EXEMPT, which is what first surfaced
    -- this rule. Found by running check_lua_houses.py's held_after_sell fixture (buy 2 lots,
    -- sell 1, expect 5 left) against a guard scoped to `not EX.is_house(res)` alone: it read 10,
    -- because EX.guild_counterparty and EX.world_counterparty BOTH hard-exclude a house at
    -- their own first line (`if EX.is_house(res) then return nil end`), and EX.top_holder
    -- reads EX.owners, which is keyed by COMMODITY and never carries a house key - so `who` is
    -- nil for a house sale ALWAYS, not occasionally. That is not scarcity, it is the paper
    -- model: EX.held's own comment calls shares "save state, not a pooled resource", and every
    -- other refusal in this file (market_closed, house_at_war, refused_by) explicitly leaves
    -- selling shares open. Refusing a house sale here would not close a leak, it would delete
    -- share selling from the game.
    if not is_buy and not who and EX.is_commodity(res) then
        EX.say("trade", "REFUSED - nobody on this map can pay for " .. pool)
        pcall(function()
            EX.log_add(EX.log_subject(res),
                "Sale refused: no buyer on this map can pay for it.", res)
        end)
        return "nobuyer"
    end
    cm:treasury_mod(faction, is_buy and -price or price)
    if EX.is_house(res) then
        -- No pooled resource exists for a house - the key is never in the DB, so
        -- cm:faction_add_pooled_resource would be a silent no-op and the position would only
        -- ever have existed in this session's memory, gone the moment it reloaded.
        EX.set_shares(res, EX.held(res) + (is_buy and lot or -lot))
    else
        cm:faction_add_pooled_resource(faction, pool, "other", is_buy and lot or -lot)
    end
    EX.say("trade", (is_buy and "bought " or "sold ") .. lot .. " " .. pool
        .. " for " .. price
        .. (who and ((is_buy and " paid to " or " taken from ") .. who
                     .. (moved ~= price and (" (only " .. moved .. ")") or "")) or ""))
    -- AND THE FILL, with the markup spelled out. A hostile guild changes the price silently;
    -- the log is the only place a player can go back and see that it did.
    -- INSIDE A BULK CLICK, TOTALLED INSTEAD: EX.bulk_trade writes one line for the whole click,
    -- because twenty-five of these pushed a fifth of the 120-line log out in one go.
    if EX.bulk then
        EX.bulk.gold = EX.bulk.gold + price
        EX.bulk.units = EX.bulk.units + lot
    else
        pcall(function()
            -- NOT ON AN AGREED PRICE. The markup sentence explains a number the guild changed;
            -- on a deal the guild changed nothing, and printing it would tell the player their
            -- 940 was really something else.
            EX.log_add(EX.log_subject(res), (is_buy and "Bought " or "Sold ") .. lot .. " for "
                .. price .. "g." .. (unit_px and "" or EX.markup_note(res, is_buy)), res)
        end)
    end
    local p = (EX.pressure[res] or 0) + (is_buy and 1 or -1)
    if p > EX.PRESSURE_MAX then p = EX.PRESSURE_MAX end
    if p < -EX.PRESSURE_MAX then p = -EX.PRESSURE_MAX end
    EX.pressure[res] = p
    EX.setv(EX.SAVE_PRESS .. res, p)
    -- NOT DURING A FILL PASS. See EX.filling: twelve fills would queue twelve repricings,
    -- and EX.turn_round schedules one for the whole round instead.
    if not EX.filling then
        cm:callback(function()
            EX.apply_prices()
            EX.after_holding_change(faction)
        end, 0.1, "zharr_after_trade_" .. tostring(faction))
    end
    return true
end

-- ===========================================================================================
-- STANDING ORDERS. A target rung, a comparison, and a fill at turn start.
--
-- THE TARGET IS A RUNG AND NEVER A GOLD PRICE. EX.current[res] is an integer 1..EX.RUNGS and
-- the test below is an integer compare. WH3's Lua is single precision - 1.05 is
-- 1.0499999523163 - so comparing EX.price_at() outputs would put a .5 boundary on the wrong
-- side of itself. The ticket DISPLAYS price_at; nothing compares it.
--
-- LIMIT AND STOP ARE THE SAME ROW. side x cmp gives all four:
--   b/le limit buy (buy the dip)      b/ge stop buy   (buy the breakout)
--   s/ge limit sell (take profit)     s/le stop sell  (stop loss)
-- ===========================================================================================

EX.ORDER_MAX = 12
EX.ORD_RS = ";"
EX.ORD_FS = ","

-- THE LIST. Placement order, and EX.fill_orders walks it in that order - see FIFO there.
EX.orders = {}

-- WHAT CAN CARRY AN ORDER: exactly what Trade page 1 lists. EX.mode_instruments never returns
-- a house on that tab and the ticket is reached by selecting a row for the chart, so a house
-- share has no way to be chosen. Refusing it here means the refusal has a sentence rather
-- than being an order nobody can ever see again.
function EX.orderable(res)
    return EX.is_commodity(res) or EX.is_layer2(res)
end

-- READ BACK OUT OF A SAVE STRING, so this is a trust boundary and not a tidy-up. Anything
-- this accepts is something EX.fill_orders will index into on a turn boundary.
-- qty IS OPTIONAL AND DEFAULTS TO ONE. Every caller that predates the amount control passes
-- four arguments, and an order read out of a save written before this build has no fifth
-- field - both must stay valid, or a build upgrade silently empties the ledger.
function EX.valid_order(res, side, cmp, rung, qty)
    if qty ~= nil then
        if type(qty) ~= "number" then return false end
        if qty ~= math.floor(qty) then return false end
        if qty < 1 or qty > EX.AMOUNTS[#EX.AMOUNTS] then return false end
    end
    if type(res) ~= "string" or res == "" then return false end
    if side ~= "b" and side ~= "s" then return false end
    if cmp ~= "le" and cmp ~= "ge" then return false end
    if type(rung) ~= "number" then return false end
    if rung ~= math.floor(rung) then return false end
    if rung < 1 or rung > EX.RUNGS then return false end
    return true
end

function EX.pack_orders()
    local out = {}
    for i = 1, #EX.orders do
        local o = EX.orders[i]
        out[#out + 1] = o.res .. EX.ORD_FS .. o.side .. EX.ORD_FS .. o.cmp
            .. EX.ORD_FS .. tostring(o.rung) .. EX.ORD_FS .. tostring(o.qty or 1)
    end
    return table.concat(out, EX.ORD_RS)
end

-- ONE BAD RECORD MUST NOT EMPTY THE LIST. Same rule EX.unpack_log follows: a record that does
-- not validate is dropped and its neighbours are kept. Refusing the whole string would clear
-- a live campaign's orders on the first load after any change to this format.
function EX.unpack_orders(s)
    EX.orders = {}
    if not s or s == "" then return end
    for rec in string.gmatch(s, "[^" .. EX.ORD_RS .. "]+") do
        local f = {}
        for fld in string.gmatch(rec .. EX.ORD_FS,
                                 "([^" .. EX.ORD_FS .. "]*)" .. EX.ORD_FS) do
            f[#f + 1] = fld
        end
        local rung = tonumber(f[4])
        -- A FOUR-FIELD RECORD IS A PRE-AMOUNT SAVE and loads as one lot. Reading the missing
        -- field as nil and defaulting here is what keeps every order a player already holds
        -- when they take this build.
        local qty = EX.clamp_lots(f[5])
        if #f >= 4 and EX.valid_order(f[1], f[2], f[3], rung, qty) then
            EX.orders[#EX.orders + 1] =
                { res = f[1], side = f[2], cmp = f[3], rung = rung, qty = qty }
        end
    end
    while #EX.orders > EX.ORDER_MAX do EX.orders[#EX.orders] = nil end
end

-- STAGE 2 DEALS. Same shape as EX.pack_orders/EX.unpack_orders above, plain "," and ";"
-- separators rather than EX.ORD_FS/EX.ORD_RS, because every field here is a key, a short side
-- word or a number - none of them free text - so the log's control-byte reasoning does not
-- apply and the file's ordinary separators are correct.
function EX.pack_deals()
    local out = {}
    for i = 1, #EX.deals do
        local d = EX.deals[i]
        out[i] = table.concat({ d.fac, d.res, d.side, d.lots, d.px, d.turn }, ",")
    end
    return table.concat(out, ";")
end

function EX.unpack_deals(s)
    EX.deals = {}
    if type(s) ~= "string" or s == "" then return end
    for chunk in string.gmatch(s, "[^;]+") do
        local f = {}
        for part in string.gmatch(chunk, "[^,]+") do f[#f + 1] = part end
        -- SIX FIELDS OR NONE. A short record is a truncated save, not a deal with defaults:
        -- guessing a missing price would settle real gold against a number nobody wrote.
        if #f == 6 then
            EX.deals[#EX.deals + 1] = {
                fac = f[1], res = f[2], side = f[3],
                lots = tonumber(f[4]), px = tonumber(f[5]), turn = tonumber(f[6]),
            }
        end
    end
end

function EX.save_orders()
    pcall(function() EX.setp(EX.SAVE_ORDERS, EX.pack_orders()) end)
end

-- WRITTEN HERE, NOT ONLY AT THE CALL SITE THAT HAPPENS TO NEED IT. A save key with a reader
-- and no writer is Stage 1's SAVE_WBOOK bug inverted: there the world book was written and
-- never read, so every load silently emptied it. Either half alone passes every gate.
function EX.save_deals()
    pcall(function() EX.setp(EX.SAVE_DEALS, EX.pack_deals()) end)
end

-- THE ONE PLACE THIS MOD ASKS THE ENGINE'S OWN AI A QUESTION AND OBEYS THE ANSWER.
--
-- CA'S ORDER, NOT THE SPEC'S. All six of CA's call sites in wh3_narrative_shared_chains.lua read
-- `if can_issue then ... score ... end`. "Cannot issue" and "scored low" are different states and
-- the page reports them differently, so the score is returned even when can_issue is false rather
-- than being collapsed into one number.
--
-- (MINE, THEM) - THE PLAYER PROPOSES, THE AI FACTION IS THE TARGET WHOSE ACCEPTANCE IS SCORED.
-- FIX ROUND 1: shipped backwards as (them, mine) at first, which computes whether the PLAYER
-- would accept a deal from the AI - the opposite of this function's purpose. CA's own doc text
-- (episodic_scripting.html): "a quick deal score greater than zero means it would likely be
-- accepted by the TARGET faction" - the target is the SECOND argument. CA's six call sites in
-- wh3_narrative_shared_chains.lua pass (faction, met_faction), and the narrative trigger's
-- default event is ScriptEventHumanFactionTurnStart, so `faction` (context:faction(), the first
-- argument) is the human player whose turn just started and `met_faction` (second) is the AI
-- being scored. Confirmed independently against docs/CAMPAIGN_AI.md section 8 as well as the
-- review that caught the inversion - not taken on the review's word alone.
--
-- BOTH FACTION ARGUMENTS ARE INTERFACES, NOT KEYS. episodic_scripting.html's own parameter list
-- reads "faction proposing faction interface" / "faction recipient faction interface" - not key
-- strings. This call is in the group that takes interfaces; a key string here fails silently
-- rather than erroring - see CLAUDE.md's three receiver conventions.
--
-- "diplomatic_option_trade_agreement" is verified, not guessed: CA uses it verbatim at
-- wh3_narrative_shared_chains.lua:3102, and it is a real diplomatic_actions key.
function EX.deal_ok(fkey)
    local me = EX.who()
    if not me or not fkey or fkey == me then return false, 0 end
    local them = cm:get_faction(fkey)
    local mine = cm:get_faction(me)
    -- cm:get_faction returns FALSE, not nil, for a key it does not know.
    if not them or not mine then return false, 0 end
    if them.is_null_interface and them:is_null_interface() then return false, 0 end
    if mine.is_null_interface and mine:is_null_interface() then return false, 0 end
    local score, can_issue = 0, false
    local ok = pcall(function()
        score, can_issue = cm:cai_evaluate_quick_deal_action(
            mine, them, "diplomatic_option_trade_agreement")
    end)
    -- AN ERROR IS A REFUSAL. This is the only engine call in the mod whose answer is obeyed, and
    -- a thrown error must not read as consent.
    if not ok then return false, 0 end
    return (can_issue == true), (tonumber(score) or 0)
end

-- ONE PASS A TURN, AFTER EX.apply_prices. The plan said "immediately after EX.step_world",
-- and its own snippet comment said "so deals reflect the prices this turn actually set" -
-- those two are not the same place. step_world runs BEFORE the reprice, deliberately, because
-- the world tier trades at last turn's prices the way the guild does. A DEAL IS NOT A TRADE:
-- nothing it does moves the market, so there is no circular dependency to avoid, and quoting
-- it off a rung the reprice is about to move would put one number on this page and another on
-- the Trade page beside it. Posted after the reprice, the edge is against the price the panel
-- actually shows.
--
-- THE WHOLE LIST IS REBUILT EVERY TURN, which IS the expiry: a deal not taken on the turn it
-- was posted is gone. No age field to check and nothing to sweep - the `turn` stamp is for the
-- page to show and for a save restored mid-turn to be honest about.
function EX.post_deals()
    EX.deals = {}
    -- WHY THE PAGE IS EMPTY, and this is the whole reason EX.deal_ok returns can_issue and
    -- score SEPARATELY. "Nobody is eligible" and "everybody said no" are different states of
    -- the world and a page that renders both as a blank list explains neither. Not saved:
    -- it is this turn's reason, and after a load the page says the neutral sentence rather
    -- than a stale one.
    EX.deal_why = nil
    -- EX.setting, NOT EX.opt. Both answer true for this key now that it is in EX.TUNE_BOOL,
    -- and they differ on the case that matters: EX.setting FAILS OPEN, so a key that ever
    -- stops being a knob leaves the feature running rather than silently switched off. It is
    -- the same call every other system switch in this file makes.
    if not EX.setting("ai_deals") then return end
    local me = EX.who()
    if not me or not EX.actors then return end
    -- THE FILE'S OWN DEFENSIVE IDIOM (see EX.log_add): a turn number is worth having and never
    -- worth an error. Harnesses stub cm without it.
    local turn = 0
    pcall(function() turn = cm:turn_number() end)

    local cand = {}
    for fac, info in pairs(EX.actors) do
        -- NO HUMAN EVER POSTS A DEAL TO A HUMAN. EX.actors is built from every landholder whose
        -- culture is not Chaos Dwarf, with no human filter on that path - the same hole
        -- EX.step_world had to close in its own fix round 2.
        if fac ~= me and not EX.is_human(fac) then
            for _, res in ipairs(EX.COMMODITIES) do
                local want = EX.world_desire(fac, res)
                local px = EX.price(res)
                local side, lots
                if want > 0 and (info.gold or 0) >= px then
                    side, lots = "buy", 1
                else
                    local sellable = EX.world_sellable(fac, res)
                    if sellable > 0 then
                        side, lots = "sell", math.min(sellable, EX.opt("world_trade_max"))
                    end
                end
                if side then
                    cand[#cand + 1] = { fac = fac, res = res, side = side, lots = lots,
                                        want = want, px = px,
                                        jit = EX.key_hash(fac .. res .. turn) }
                end
            end
        end
    end

    -- STRONGEST CONVICTION FIRST, AND A STABLE TIEBREAK.
    --
    -- ON math.abs, WHICH THE PLAN DID NOT HAVE. Sorting on `want` itself ranks every buyer above
    -- every seller, because a producer's desire for what it already makes is NEGATIVE by
    -- construction (EX.world_desire's production term) while every non-producer scores at least
    -- the +0.5 constant. With ~80 actors and 17 commodities the buy side fills all three slots
    -- every turn and THE SELL HALF OF THE FEATURE NEVER APPEARS. Ranking on the strength of the
    -- conviction rather than its sign is what puts the map's biggest dumper on the page beside
    -- its keenest buyer.
    --
    -- THE TIEBREAK IS NOT COSMETIC. pairs() order over EX.actors is unspecified in Lua 5.1, so
    -- without it the same world state posts a different page on a reload - the reason EX.houses
    -- and EX.pack_book both sort. In multiplayer it is worse: two clients would resolve
    -- different deals from the same save.
    --
    -- AND THE TIEBREAK IS THE TURN HASH, NOT THE ALPHABET. Every non-producer scores the same
    -- +0.5 constant plus its culture's taste, so the buy side of this list is one long exact
    -- tie - and broken on the faction key, the alphabetically first faction of the keenest
    -- culture took a slot every turn, for the life of the campaign. EX.key_hash over
    -- (faction, commodity, turn) is bounded, deterministic and already asserted as both, so
    -- the page rotates through the tied factions without costing multiplayer its determinism:
    -- every client computes the same hash from the same three strings.
    --
    -- THE ALPHABETICAL TIEBREAK STAYS UNDER IT, as a backstop and not as coverage: key_hash
    -- has 65,536 buckets against up to ~1,400 candidates, so two tied candidates sharing a
    -- hash is uncommon rather than impossible, and pairs() order must never be what decides.
    -- It is ONE comparison and not two because the 2026-09-16 mutation round proved it is
    -- reached only on a collision: with the hash above it, deleting the faction comparison
    -- changed no page in any fixture, because the commodity comparison under it was still
    -- total. Two backstops for one unreachable case is one more than the case needs. The
    -- slash is load-bearing - without it 'ab' .. 'c' and 'a' .. 'bc' are the same string,
    -- and a faction key never contains one.
    table.sort(cand, function(a, b)
        local aw, bw = math.abs(a.want), math.abs(b.want)
        if aw ~= bw then return aw > bw end
        if a.jit ~= b.jit then return a.jit < b.jit end
        return a.fac .. "/" .. a.res < b.fac .. "/" .. b.res
    end)

    -- ONE DEAL PER ACTOR, AND THE ENGINE IS ASKED ABOUT EACH FACTION EXACTLY ONCE.
    --
    -- The page is three FACTIONS with something to say, not three rows from whichever faction
    -- happens to be biggest: a producer holding nine regions of iron outranks every buyer on
    -- the map by construction, so undeduplicated it took the whole page. It is also the
    -- gameplay argument - three deals concentrated on one AI treasury is three times the gold
    -- into one faction's armies, and per-lot settlement means world_cash_max never sees the
    -- total (see HOUSE_CASH_MAX's note: this is the one number here that changes the campaign
    -- for factions the player is not playing).
    --
    -- MARKED BEFORE THE ANSWER IS READ, not after a successful post. EX.deal_ok takes a
    -- FACTION and no commodity, so asking twice about one faction cannot give two answers -
    -- it is two wasted cm:get_faction calls. Worst case falls from ~2 x actors x commodities
    -- to 2 x actors, which on a full map is ~2,700 engine calls a turn against ~160.
    local seen = {}
    for i = 1, #cand do
        if #EX.deals >= EX.opt("deal_max") then break end
        local c = cand[i]
        if not seen[c.fac] then
            seen[c.fac] = true
            -- THE ENGINE'S OWN ANSWER, AND IT IS OBEYED. can_issue before score, CA's order.
            local can, score = EX.deal_ok(c.fac)
            if can then EX.deal_why = EX.deal_why or "declined" end
            if can and score > 0 then
                local edge = (c.side == "buy") and (100 + EX.opt("deal_edge"))
                                              or  (100 - EX.opt("deal_edge"))
                EX.deals[#EX.deals + 1] = {
                    fac = c.fac, res = c.res, side = c.side, lots = c.lots,
                    px = math.floor(c.px * edge / 100), turn = turn,
                }
            end
        end
    end
    -- NOBODY WAS EVEN ELIGIBLE, which is not the same as everybody declining. Set last, and
    -- only if the loop never saw a can_issue, so "declined" wins wherever both could be said.
    if #EX.deals == 0 and not EX.deal_why then EX.deal_why = "none" end
    -- THROUGH EX.save_deals, NOT AN INLINE EX.setp. The writer lives with its key so neither
    -- half can go missing on its own - Stage 1 shipped SAVE_WBOOK written and never read.
    EX.save_deals()
end

-- ACCEPTING ONE. A deal is INTENT AND NEVER A RESERVATION (this stage's pre-flight ruling), so
-- the counterparty's money is re-read here, at accept time, and the acceptance can fail. What is
-- NOT re-read is the price: the player agreed to the number the page printed, and a page that
-- quotes one price and charges another is the defect EX.buy_refusal exists to prevent elsewhere
-- in this file.
--
-- SIDE IS FROM THE AI'S POINT OF VIEW, is_buy IS FROM THE PLAYER'S. A deal whose side is "buy"
-- is an actor buying, so the PLAYER SELLS into it. Getting this backwards is Task 2's inverted
-- argument order wearing a different hat, and the assertions pin the direction of the gold rather
-- than the spelling of the flag.
--
-- N LOTS AS N REAL TRADES, the same contract EX.bulk_trade documents and for the same reason.
-- Its own loop is not reused only because its argument is a packed op string and its summary line
-- says "bulk buy"; the CONTRACT is reused exactly, including stopping at the first refusal and
-- letting whatever filled before it stand.
function EX.accept_deal(i)
    local d = EX.deals[tonumber(i) or 0]
    if not d or not d.fac or not d.res or not d.lots or not d.px then return "nodeal" end
    local is_buy = (d.side == "sell")

    -- THE RE-READ. EX.actors[fac].gold is this turn's scanned treasury, spent down as a budget
    -- by every settlement on this path - so a faction that has already been sold to this turn
    -- reads poorer here, which is the intended behaviour and not a stale number.
    local info = (EX.actors or {})[d.fac]
    if not info then return "gone" end
    if not is_buy and (info.gold or 0) < d.px * d.lots then return "poor" end

    local done, last = 0, nil
    for _ = 1, d.lots do
        last = EX.apply_trade(d.res, is_buy, d.px, d.fac)
        if last ~= true then break end
        done = done + 1
    end

    -- ANY SETTLEMENT CONSUMES THE DEAL. A one-turn offer that partly filled is spent, the same
    -- way a bulk order that stopped at the first no does not queue the rest - and leaving it on
    -- the page would let the player click it again for another go at a price the market has
    -- already moved past.
    if done > 0 then
        table.remove(EX.deals, tonumber(i))
        EX.save_deals()
        pcall(function()
            EX.log_add(EX.log_subject(d.res),
                (is_buy and "Bought " or "Sold ") .. done .. "/" .. d.lots .. " lots "
                .. (is_buy and "from " or "to ") .. EX.faction_display(d.fac)
                .. " at " .. d.px .. "g a lot.", d.res)
        end)
    end
    if done < d.lots then return tostring(last) end
    return true
end

function EX.find_order(res, side, cmp, rung)
    for i = 1, #EX.orders do
        local o = EX.orders[i]
        if o.res == res and o.side == side and o.cmp == cmp and o.rung == rung then
            return i
        end
    end
    return nil
end

-- EVERY ORDER ON ONE INSTRUMENT, in placement order. The ticket prints these; the ledger
-- draws all of them.
function EX.orders_on(res)
    local t = {}
    for i = 1, #EX.orders do
        if EX.orders[i].res == res then t[#t + 1] = EX.orders[i] end
    end
    return t
end

-- THE SHARED GUARD. Returns the reason EX.place_order would refuse for, WITHOUT placing -
-- the dry run the ticket's Place button needs so it can print a refusal locally instead of
-- sending an order over MP that the network op then refuses anyway. EX.place_order calls this
-- too, so the button and the op are reading the exact same four checks rather than two
-- copies that could drift apart.
function EX.place_order_check(res, side, cmp, rung)
    -- THE KILL-SWITCH GATES PLACEMENT TOO. It had exactly two readers - EX.trade_pages and
    -- EX.fill_orders - and neither is on this path, so with orders off a player could still
    -- place from the chart page's ticket (that page answers to deep_history) while the ledger
    -- page holding the only Cancel button no longer existed. Twelve orders, no way to delete
    -- one, and all twelve live again the moment the switch went back on. EX.place_order and
    -- EX.MP_OPS.ord both route through here, so this one line closes the button and the op.
    if not EX.feature("orders") then
        return "Standing orders are switched off."
    end
    if not EX.valid_order(res, side, cmp, rung) then
        return "That is not a valid order."
    end
    if not EX.orderable(res) then
        return "The Exchange takes no standing orders on that instrument."
    end
    -- THE DUPLICATE IS TESTED FIRST, and the order matters. With the cap first, re-placing
    -- an order the player already holds while at twelve answered "Cancel one first" - true,
    -- and useless: cancelling one would not have let this one in, because it was already
    -- there. The duplicate is the more specific answer, so it wins whenever both apply.
    if EX.find_order(res, side, cmp, rung) then
        return "That order already stands."
    end
    if #EX.orders >= EX.ORDER_MAX then
        return "You hold " .. EX.ORDER_MAX .. " orders. Cancel one first."
    end
    return nil
end

-- RETURNS THE REASON IT WAS REFUSED, or nil on success. A reason and not a boolean because
-- the ticket prints it - a click that silently does nothing is the complaint the Log view
-- exists to answer, and this is the same standard.
-- THE LEDGER'S OWN HISTORY HAS TO SHOW AN ORDER EXISTING, AND LEAVING.
--
-- Only the FILL pass logged. So an order that disappeared for a bad reason - dropped by a save
-- round trip, truncated over the cap, removed by a machine that disagreed with its neighbour -
-- read exactly like one the player withdrew on purpose: no line either way, in a Log whose
-- whole job is answering "why did that happen". Found 2026-09-10 the only way this kind of
-- thing is found: by trying to answer "did the limit orders work?" from a live campaign's own
-- Log, at turn 11, and being unable to. Three orders had been standing, none was there, and
-- the Log had nothing to say about any of it.
--
-- FOUR VERBS, ALL DIFFERENT, because the whole value here is telling causes apart:
-- "Order placed" / "Order withdrawn" (the player), "Order filled" (the pass), "Order
-- cancelled" (the pass, on a FATAL refusal - a delisted house or an unregistered pool). A
-- withdrawal and a fatal cancel are the two that would otherwise collide, and they are the two
-- a player most needs separated: one they did, one the world did to them.
--
-- ON THE SUCCESS PATH ONLY. A refusal already answers through the return value, which the
-- ticket prints on the standing line and EX.ticket_click logs; logging here as well would put
-- two lines in the Log for one click.
function EX.place_order(res, side, cmp, rung, qty)
    if qty ~= nil then EX.amount = EX.clamp_lots(qty) end
    local why = EX.place_order_check(res, side, cmp, rung)
    if why then return why end
    -- THE AMOUNT ON SCREEN AT THE MOMENT PLACE WAS PRESSED, frozen onto the order. Reading
    -- EX.amount at FILL time instead would let a player change the amount button and quietly
    -- rewrite the size of every standing order they hold.
    local o = { res = res, side = side, cmp = cmp, rung = rung, qty = EX.clamp_lots(EX.amount) }
    EX.orders[#EX.orders + 1] = o
    EX.save_orders()
    -- pcall for the same reason every other EX.log_add call site has one: EX.log_subject
    -- reaches the loc system through EX.display / EX.faction_display, and the Log is never
    -- worth failing a placement over.
    pcall(function()
        EX.log_add(EX.log_subject(res), "Order placed. " .. EX.order_text(o) .. ".", res)
    end)
    return nil
end

-- "WITHDRAWN", NOT "CANCELLED". EX.fill_orders already writes "Order cancelled." when a
-- FATAL refusal kills an order, and that is the one line this must not be mistaken for: the
-- player needs to know whether they did it or the world did. Read as a pair in the Log,
-- "withdrawn" is unambiguously theirs.
function EX.cancel_order(res, side, cmp, rung)
    local i = EX.find_order(res, side, cmp, rung)
    if not i then return false end
    local o = EX.orders[i]
    table.remove(EX.orders, i)
    EX.save_orders()
    pcall(function()
        EX.log_add(EX.log_subject(res), "Order withdrawn. " .. EX.order_text(o) .. ".", res)
    end)
    return true
end

-- IS IT IN THE MONEY. The whole feature, and the one place an inverted comparison would be
-- invisible: a stop-loss that sells on the way up packs, draws and saves perfectly.
function EX.order_hits(o)
    local now = EX.current[o.res] or EX.neutral_rung()
    if o.cmp == "le" then return now <= o.rung end
    return now >= o.rung
end

-- tostring, NOT a formatted number. Every price in this panel is a raw tostring(n) - see
-- EX.price_cell - and a thousands separator here would make these two views look foreign
-- beside the other five.
-- WHAT A FILL AT THIS RUNG ACTUALLY PAYS, on the side the order is. EX.price_at is the MID of
-- the spread, and every order surface printed it: the ticket, the order sentence and the
-- ledger's price column all read "Sell at or above 621g" on an instrument whose sell side pays
-- 559 - or 310 on Layer 2, where EX.sell_price applies the l2_sell factor. A number the player
-- decides against has to be the number they get. Routed through the same two functions the
-- Trade view's own Buy and Sell columns use, with the rung's mid substituted for today's, so
-- the ticket and the list cannot disagree about the spread.
--
-- AT TODAY'S HOSTILITY, which is the honest limit of this: the guild's temper can move between
-- now and the fill. The rung comparison is unaffected - EX.order_hits compares integers and
-- never this number.
function EX.order_price(res, side, rung)
    local at = EX.price_at(rung)
    if side == "b" then return EX.buy_price(res, at) end
    return EX.sell_price(res, at)
end

-- THE SIZE IS ONLY SPOKEN WHEN THERE IS ONE. A ledger of "Buy x1 ..." on every row spends
-- the reader's attention on a number that is the default; the row that is not one lot is the
-- row worth noticing. Fits the 320px row_trend cell either way.
function EX.order_text(o)
    return (o.side == "b" and "Buy" or "Sell")
        .. (((o.qty or 1) > 1) and (" x" .. tostring(o.qty)) or "")
        .. (o.cmp == "le" and " at or below " or " at or above ")
        .. tostring(EX.order_price(o.res, o.side, o.rung)) .. "g"
end

-- WHY A FILL DID NOT HAPPEN, and whether the order survives it.
--
-- FATAL IS THE SHORT LIST ON PURPOSE. A delisted house never comes back and a pooled
-- resource this faction does not hold never appears, so an order against either is dead
-- paper. Everything else is a condition of this turn: the treasury, the guild's temper, the
-- war lock, the map's supply, the position. An order cancelled on a transient refusal is one
-- the player was still waiting on, and nothing on screen would say where it went.
--
-- AN UNKNOWN TOKEN IS TRANSIENT, which is the safe direction - a token added to
-- EX.apply_trade later and not classified here leaves the order standing and visible in the
-- ledger rather than deleting it in silence.
EX.ORDER_FATAL = { delisted = true, nopool = true }

EX.ORDER_REASON = {
    delisted    = "That house is delisted or gone.",
    nopool      = "This market is not open to your people.",
    nothold     = "You hold too little to sell a lot.",
    unavailable = "Nothing on this map produces it.",
    blocked     = "The house that holds the book refuses you.",
    afford      = "You could not afford the fill.",
    rent        = "The fill would not have left this turn's warehousing.",
    threw       = "The trade could not be completed.",
    -- NOT IN EX.ORDER_FATAL, deliberately: nobody able to pay today is a transient state, the
    -- same as "afford" or "blocked" - a counterparty may exist next turn, so the order is
    -- retried rather than cancelled.
    nobuyer     = "Nobody on this map can pay for it.",
}

-- THE FILL HAS TO LEAVE THIS TURN'S WAREHOUSING BEHIND IT.
--
-- EX.fill_orders spends at turn step 9b and EX.charge_carry debits the rent about six steps
-- later in the SAME turn round, with no floor of its own - EX.apply_trade's affordability
-- test is `treasury() < price`, so the last fill can leave the treasury anywhere in
-- 0 .. price-1 and the rent then takes it negative. Worked shape: treasury 1,500, a limit buy
-- fills at 1,400, 600 Tusks at carry_per_unit 0.5 is 300 gold of warehousing, and the turn
-- ends at -200 on two movements of gold the player clicked neither of.
--
-- A MANUAL BUY IS DELIBERATELY NOT FLOORED, and that distinction is the whole design. The
-- player is looking at the treasury when they press Buy, so both the purchase and the
-- decision to be that thin are theirs. A standing order is the one case where neither was,
-- which is why this lives here and not in EX.apply_trade - putting it there would quietly
-- refuse manual buys that have always been allowed.
--
-- THE NEW LOT PAYS RENT THIS TURN TOO, because EX.charge_carry reads EX.held AFTER the pass.
-- Reserving today's EX.carry_total alone under-reserves by exactly what the fill just put in
-- the warehouse. Computed as a DIFFERENCE OF TWO FLOORS rather than floor(lot * rate):
-- EX.carry_cost floors the whole holding, so at carry_per_unit 0.5 a lot of 10 added to an
-- odd holding costs 5 gold on one parity and 5 on the other only because both floors move
-- together - taking floor(lot * rate) on its own disagrees by a gold whenever the holding's
-- own fraction carries, and this number is compared against a treasury.
function EX.rent_delta(res)
    if not EX.setting("warehouse_rent") then return 0 end
    -- The same two exemptions EX.carry_cost makes, and for its reasons: Layer 2 is Hell-Forge
    -- currency out of buildings, and a house is paper with nothing to store.
    if EX.is_layer2(res) or EX.is_house(res) then return 0 end
    local held = EX.held(res)
    local rate = EX.opt("carry_per_unit")
    return math.floor((held + EX.lot(res)) * rate) - math.floor(held * rate)
end

-- FAIL OPEN. If the treasury cannot be read there is nothing to compare it against, and
-- EX.apply_trade's own affordability check still stands behind this. Refusing here instead
-- would stop every fill for a faction whose interface is momentarily null - a kill-switch
-- nobody threw.
--
-- EX.buy_price IS THE PRICE EX.apply_trade WILL CHARGE, the same call on the same line, so
-- the floor cannot drift from the debit it is predicting.
function EX.fill_clears_rent(res, reserve)
    if reserve <= 0 then return true end
    local f = cm:get_faction(EX.who())
    if not f or f:is_null_interface() then return true end
    local ok, gold = pcall(function() return f:treasury() end)
    if not ok or type(gold) ~= "number" then return true end
    return gold - EX.buy_price(res) >= reserve
end

-- TRUE WHILE THE PASS IS RUNNING. EX.apply_trade ends with a cm:callback that reprices;
-- twelve fills would queue twelve of them, and CA's timer_manager docs are explicit that a
-- callback name exists only so remove_callback can cancel every callback matching it - names
-- need not be unique, so all twelve would fire. The flag suppresses the per-trade callback
-- and EX.turn_round schedules exactly one after EX.remember_all.
EX.filling = false
EX.fill_factions = {}

-- ONE PASS, ONE FILL PER INSTRUMENT, FIFO WITHIN AN INSTRUMENT.
--
-- FIFO COSTS THE PLAYER NOTHING. They pay the market price, not their limit, so which rung of
-- a ladder is consumed changes no gold - only which row leaves the ledger.
--
-- THE SWITCH GATES THE MODEL, not just the page. A kill-switch is thrown while the thing is
-- on screen doing the wrong thing, and the half that moves gold is this one.
function EX.fill_orders()
    if not EX.feature("orders") then return end
    if #EX.orders == 0 then return end
    local keep, done = {}, {}
    -- SNAPSHOT ONCE, ACCUMULATE LOCALLY. EX.held reads back out of the pooled resource
    -- manager, and whether that reflects a cm:faction_add_pooled_resource made earlier in
    -- this same pass is NOT MEASURED. Building the reserve from one pre-pass reading plus the
    -- deltas of the fills this loop actually made is exact either way. One fill per instrument
    -- per pass (done[]) is what makes it exact: an instrument's own delta is always read
    -- before that instrument has filled.
    local rent_base = EX.setting("warehouse_rent") and EX.carry_total() or 0
    local rent_added = 0
    EX.filling = true
    for i = 1, #EX.orders do
        local o = EX.orders[i]
        local drop = false
        if not done[o.res] and EX.order_hits(o) then
            local is_buy = (o.side == "b")
            -- AN ORDER IS N LOTS, AND EACH LOT IS ITS OWN TRADE. Same rule as the manual
            -- bulk buy: the price, the counterparty walk and the book drawdown must be the
            -- ones a player clicking N times would have got, not a bulk formula beside them.
            local want, got, r = EX.clamp_lots(o.qty), 0, nil
            for _ = 1, want do
                -- A SELL IS NEVER FLOORED. It credits gold and lowers the holding, so it
                -- moves both sides of this comparison the safe way; floor it and a player
                -- who is short of rent could not raise the money to pay it.
                --
                -- RE-READ PER LOT, and correct whichever way EX.held behaves. If the pooled
                -- resource updates inside the pass, each delta is the true increment and the
                -- accumulated total telescopes exactly. If it does not, every lot re-reads
                -- the same pre-pass holding and the total OVER-reserves - which refuses a
                -- fill that was affordable, the safe direction, and never the reverse.
                local delta = is_buy and EX.rent_delta(o.res) or 0
                if is_buy and not EX.fill_clears_rent(o.res, rent_base + rent_added + delta) then
                    -- TRANSIENT, and it must stay off EX.ORDER_FATAL. The treasury is a
                    -- condition of this turn like the guild's temper is; the order stands and
                    -- the ledger keeps showing it, with the reason in the Log.
                    r = "rent"
                    break
                end
                -- EX.apply_trade IS NOT DEFENSIVE - cm:get_faction and the counterparty walk
                -- can throw - and an error escaping here would skip BOTH the flag reset and
                -- the `EX.orders = keep` commit below. The flag stuck true silently stops
                -- every later manual trade repricing; the missing commit leaves an order that
                -- ALREADY FILLED in the list, to fire a second real trade next turn. An error
                -- is therefore an ordinary transient token: the order stands, the loop
                -- continues, cleanup runs.
                local ok, rr = pcall(function() return EX.apply_trade(o.res, is_buy) end)
                if not ok then
                    EX.say("error",
                        "order fill on " .. tostring(o.res) .. " threw: " .. tostring(rr))
                    r = "threw"
                    break
                end
                if rr ~= true then r = rr break end
                got = got + 1
                rent_added = rent_added + delta
            end
            -- ANY LOT AT ALL CLAIMS THE INSTRUMENT FOR THIS TURN. One fill per instrument
            -- per pass was never about the lot count - it is about a second order on the same
            -- good not compounding the move the first one just made.
            if got > 0 then
                done[o.res] = true
                EX.fill_factions[EX.who()] = true
            end
            if got >= want then
                drop = true
                pcall(function()
                    EX.log_add(EX.log_subject(o.res),
                        "Order filled. " .. EX.order_text(o) .. ".", o.res)
                end)
            elseif got > 0 then
                -- PART-FILLED ORDERS SHRINK AND STAND. Dropping the whole order because the
                -- treasury ran out two lots in would silently discard the rest of a size the
                -- player chose; refilling the full size next turn would buy more than they
                -- asked for. The remainder is what is left to do.
                o.qty = want - got
                pcall(function()
                    EX.log_add(EX.log_subject(o.res), "Order part-filled. " .. got .. " of "
                        .. want .. " lots. " .. (EX.ORDER_REASON[r] or "Not this turn.")
                        .. " The rest still stands.", o.res)
                end)
            elseif EX.ORDER_FATAL[r] then
                drop = true
                pcall(function()
                    EX.log_add(EX.log_subject(o.res), "Order cancelled. "
                        .. (EX.ORDER_REASON[r] or "It can no longer be filled."), o.res)
                end)
            else
                pcall(function()
                    EX.log_add(EX.log_subject(o.res), "Order did not fill. "
                        .. (EX.ORDER_REASON[r] or "Not this turn.")
                        .. " It still stands.", o.res)
                end)
            end
        end
        if not drop then keep[#keep + 1] = o end
    end
    EX.filling = false
    EX.orders = keep
    EX.save_orders()
end

-- THE NETWORK HALF. Placement and cancellation cross; FILLS DO NOT, because they run in the
-- turn round, which every machine already executes identically over cm:get_human_factions().
--
-- CANCEL SENDS THE ORDER, NOT AN INDEX. The list is per-player and every machine holds the
-- same one, so an index would usually work - but "usually" is how a machine deletes a
-- different row from its neighbours and the two saves diverge from then on.
function EX.pack_one(res, side, cmp, rung, qty)
    return res .. EX.ORD_FS .. side .. EX.ORD_FS .. cmp .. EX.ORD_FS .. tostring(rung)
        .. EX.ORD_FS .. tostring(qty or 1)
end

function EX.unpack_one(s)
    local f = {}
    for fld in string.gmatch(tostring(s) .. EX.ORD_FS,
                             "([^" .. EX.ORD_FS .. "]*)" .. EX.ORD_FS) do
        f[#f + 1] = fld
    end
    if #f < 4 then return nil end
    local rung = tonumber(f[4])
    local qty = EX.clamp_lots(f[5])
    if not EX.valid_order(f[1], f[2], f[3], rung, qty) then return nil end
    return f[1], f[2], f[3], rung, qty
end

EX.MP_OPS.ord = function(arg)
    local res, side, cmp, rung, qty = EX.unpack_one(arg)
    if not res then return end
    local why = EX.place_order(res, side, cmp, rung, qty)
    if why then EX.say("trade", "order refused: " .. why) end
end

EX.MP_OPS.ordx = function(arg)
    local res, side, cmp, rung = EX.unpack_one(arg)
    if not res then return end
    EX.cancel_order(res, side, cmp, rung)
end

-- THE DEAL, ACROSS THE WIRE. Everything a click can do to another player's gold goes through
-- EX.mp_send, and this is no different: EX.accept_deal moves the treasury and the book on both
-- sides of a trade, so a local apply in a multiplayer game would desync the save.
--
-- THE INDEX IS THE WHOLE MESSAGE, and that is only safe because both clients resolved the SAME
-- LIST. EX.post_deals sorts on (desire, turn hash, faction/commodity) - every term of it a
-- function of the save - so client B's EX.deals[3] is client A's EX.deals[3] or the feature is
-- broken. That is the property check_lua_mp asserts for this op, and it is the reason the sort
-- carries a collision backstop it will almost never reach.
--
-- EX.mp_send stringifies its argument into the event id, so what EX.MP_OPS.deal receives is
-- "3" and not 3 on the multiplayer path and 3 on the single-player one. EX.accept_deal already
-- takes either - `EX.deals[tonumber(i) or 0]` - which is why nothing converts here.
function EX.deal_send(i)
    EX.mp_send("deal", i)
end

EX.MP_OPS.deal = function(arg)
    local why = EX.accept_deal(arg)
    -- THE REFUSAL IS SAID, NOT SWALLOWED. EX.accept_deal returns true or a reason, and every
    -- reason it can return is about the world rather than the click - the counterparty is gone,
    -- it cannot pay, the market moved - so a silent no reads as a dead button.
    if why ~= true then EX.say("trade", "deal refused: " .. tostring(why)) end
    -- GUARDED, because this runs on EVERY machine and not just the one that clicked. On the
    -- others the panel is very often shut, and EX.refresh_panel with no panel is the same
    -- unguarded call EX.raise_demand already refuses to make. EX.layout as well as the
    -- refresh: a settled deal leaves the list, so the ROW SET changed and not just its text.
    if is_uicomponent(EX.panel()) then
        EX.layout()
        EX.refresh_panel()
    end
end

function EX.order_send(res, side, cmp, rung)
    EX.mp_send("ord", EX.pack_one(res, side, cmp, rung, EX.amount))
end

function EX.order_cancel_send(res, side, cmp, rung)
    EX.mp_send("ordx", EX.pack_one(res, side, cmp, rung))
end

-- ---------------------------------------------------------------------------------------
-- Getting out of CA's rites panel.
-- ---------------------------------------------------------------------------------------

-- ONE-TIME MIGRATION, and the reason the 798 effect_bundles rows still ship.
--
-- Every build before 2026-09-05 applied one derpy_chd_ex_ladder_* bundle per instrument to the
-- faction and swapped it on each reprice, so a live save carries up to 19 of them. What happens
-- when a save holds an applied bundle whose DB row has been deleted under it is NOT MEASURED,
-- and the plausible answer is a load-time fault - so the rows stay for one build while this
-- removes them, and a later build drops the rows.
--
-- The sweep is all 42 rungs of all 19 instruments rather than just the recorded one, because
-- EX.current is restored from saved values and a save older than that bookkeeping would leave a
-- bundle behind that nothing later could name. Removing a bundle that is not applied is a
-- no-op. It runs once per save and records that it did.
function EX.strip_legacy_bundles()
    if EX.getv(EX.SAVE_STRIPPED) then return end
    local faction = EX.me()
    if not faction then return end
    for _, res in ipairs(EX.instruments()) do
        -- HOUSES ARE SKIPPED. Every ladder bundle this sweeps was deleted on 2026-09-05 and
        -- houses landed after that, so derpy_chd_ex_ladder_<house>_NN has never existed in any
        -- save, in any build. Included, it is 42 no-op removes per house on a list that is
        -- discovered and can be twenty-odd long.
        if not EX.is_house(res) then
            for rung = 1, EX.RUNGS do
                pcall(function()
                    cm:remove_effect_bundle(EX.bundle_key(res, rung), faction)
                end)
            end
        end
    end
    EX.setv(EX.SAVE_STRIPPED, true)
    EX.say("turn", "stripped legacy price bundles from this save")
end

-- ---------------------------------------------------------------------------------------
-- Wiring.
-- ---------------------------------------------------------------------------------------

function EX.make_button()
    EX.place_button(1)
end

-- Park it left of the top resource strip, vertically centred on it. See EX.button_anchor.
--
-- TWO ANCHORS HAVE ALREADY BEEN WRONG HERE, both for the same reason, and the history is the
-- reason EX.button_anchor reads a ruler instead of picking a parent:
--   1. "left of the rites button, same row" - there is no row. button_rituals is one member of
--      a RadialList of radius 95, so "left of it by its own width" is a point INSIDE the ring.
--      Measured live: the ring's children occupy x 1364..1593, y 649..847 and the button landed
--      at 1347..1395, overlapping it.
--   2. Parenting to rites:Parent() - that is button_group_management, which carries
--        <LayoutEngine type="RadialList" starting_angle="3.64773798" arc="3.490659"
--                      spacing="0.715584993" radius="95" clockwise="true"/>
--      (ui3.pack/ui/campaign ui/hud_campaign.twui.xml). A layout group OWNS its children's
--      positions, so the button became an extra slot on the Chaos Dwarf ring and CA moved it
--      back onto the arc on every re-layout. MoveTo does not lose a fight with a layout
--      engine - it never gets to have one.
--
-- WHY THE SANITY CHECK AND RETRY. The HUD is NOT laid out when the first-tick callback runs:
-- read button_rituals then and it reports a position off the edge of the screen, and our button
-- goes there. Measured 2026-09-04: placed at 2517,1429 on a 2717x1419 screen - invisible. Once
-- the HUD settles the same button reads 1705,846. So refuse an off-screen answer and try again.
--
-- Never READ a HUD button's tooltip or image (both hard-crash); position and bounds are safe.
-- THE SCREEN, from CA's own accessor. core:get_screen_resolution() is literally
--     function core_object:get_screen_resolution() return self.ui_root:Dimensions() end
-- read out of data_script.pack/script/_lib/lib_core.lua line 392.
--
-- IT IS Dimensions(), NOT Bounds(), AND THE ROOT IS NO EXCEPTION. Bounds() is the extent
-- INCLUDING CHILDREN, so during load - while some HUD component is transiently oversized or
-- parked off-screen - the root's bounds balloon past the real display. Measured 2026-09-05:
-- the opener button landed at 2090,1195 on a 1966x901 screen and PASSED its own on-screen
-- guard, because the guard was asking the same inflated question; and the panel centred
-- against a screen that does not exist, which is what "it opens at the side" was.
-- One wrong call, both symptoms. An earlier note in HANDOFF §14 said the ui root was the one
-- legitimate Bounds() receiver - it is not, and CA's own wrapper is the proof.
function EX.screen()
    return core:get_screen_resolution()
end

-- WHERE THE BUTTON GOES. Asked for 2026-09-06: on the top resource strip rather than down by
-- the rites ring, and off its RIGHT end.
--
-- Neither the strip nor its holder carries a LayoutEngine (read out of
-- ui3.pack/ui/campaign ui/hud_campaign.twui.xml), which matters because a layout group OWNS its
-- children's positions and MoveTo never gets to have the fight - see the two anchors that were
-- already wrong that way, above EX.place_button. It is moot here regardless: the strip is a
-- RULER, never a parent. The button is created on the UI root and only reads coordinates.
--
-- THE BOTTOM-RIGHT DOCKER IS KEPT AS A LAST RESORT, not deleted. If CA renames the strip in a
-- patch, find_uicomponent returns nil and a button that cannot be placed is a mod with no way
-- in at all. Read the ordering note inside before touching it - a fallback that resolves while
-- the real anchor is merely still loading is what made the button teleport.
function EX.button_anchor()
    local root = core:get_ui_root()
    -- resources_bar IS THE ART. resources_bar_holder is a box that neither contains nor aligns
    -- with it - measured live on a 1920x1080 screen 2026-09-06:
    --     resources_bar_holder  pos 564,0    792x67
    --     resources_bar         pos 431,-4  1019x60      <- overhangs its parent BOTH sides
    -- so the holder's left edge is 133px right of the art's, and its right edge 94px left.
    -- Anchoring to the holder is what put the button on open terrain (§14) and its 792x67 box
    -- describes nothing that is drawn.
    --
    -- THE BUTTON SITS OFF THE RIGHT END, asked for from play 2026-09-06.
    local bar = find_uicomponent(root, "resources_bar")
    if is_uicomponent(bar) then
        local bx, by = bar:Position()
        -- Dimensions(), NOT Bounds(): Bounds() includes children and this component is full of
        -- them. Same trap as EX.screen - see the note there.
        local bw, bh = bar:Dimensions()
        return bx + bw + EX.BUTTON_GAP,
               by + math.floor((bh - EX.BUTTON_SIZE) / 2), "resources_bar"
    end
    -- LAST RESORT ONLY, and the ordering here is the whole fix for the teleport.
    --
    -- This used to walk resources_bar_holder's children and fall back to the holder's own
    -- Position() when the walk found nothing. That fallback returned a DIFFERENT PLACE, so the
    -- first-tick call (children not ready, 512,9) and the first click (child found, 379,9)
    -- disagreed by 133px and the button visibly jumped. Measured, both lines in script_log.
    --
    -- A fallback that yields a different position is worse than no placement at all: it turns
    -- "not ready yet" into a guaranteed visible jump. So the ONLY fallback now is for the strip
    -- being absent entirely - a CA rename - and while it merely has not loaded, place_button
    -- retries instead of guessing. Never add a fallback here that resolves to other geometry
    -- while the real anchor is still coming.
    local docker = find_uicomponent(root, "faction_buttons_docker")
    if is_uicomponent(docker) then
        local dx, dy = docker:Position()
        local _dw, dh = docker:Dimensions()
        return dx - EX.BUTTON_SIZE - EX.BUTTON_GAP,
               dy + math.floor((dh - EX.BUTTON_SIZE) / 2), "faction_buttons_docker"
    end
    return nil, nil, nil
end

function EX.place_button(attempt)
    local root = core:get_ui_root()
    local sw, sh = EX.screen()
    local b = find_uicomponent(root, EX.BUTTON)
    -- Every "not ready yet" branch below routes through here, so the chain cannot be given up
    -- on in one place and kept alive in another. Stops on the FIRST successful placement -
    -- after that a bad read must leave the button where it is, never reschedule. See
    -- EX.PLACE_TRIES for why this is not a countdown.
    local function retry()
        if EX.button_at or attempt >= EX.PLACE_TRIES then return false end
        cm:callback(function() EX.place_button(attempt + 1) end, 2.0,
                    "zharr_place_button_" .. attempt)
        return true
    end
    -- CREATION retries too, not just placement. The HUD is not built when the first-tick
    -- callback runs, so a one-shot create silently did nothing forever (measured 2026-09-04 -
    -- the panel existed, the button never did).
    --
    -- CREATED ON THE UI ROOT, not on the anchor. The anchor is only a ruler now - it is read
    -- for coordinates and never becomes the parent - so the button's position cannot be taken
    -- over by whatever CA lays out inside the resource strip at runtime. The root is the same
    -- parent EX.build_panel uses, holds no LayoutEngine, and is always there.
    if not is_uicomponent(b) then
        root:CreateComponent(EX.BUTTON, EX.BUTTON_FILE)
        b = find_uicomponent(root, EX.BUTTON)
    end
    if not is_uicomponent(b) then
        if not retry() then
            EX.say("error", "gave up creating the opener button")
        end
        return
    end
    -- RECOMPUTED EVERY CALL, deliberately. The previous version cached the first good answer,
    -- which made a wrong position permanent instead of self-correcting: at first tick
    -- root:Bounds() reported a screen big enough for 2054,1162 to pass the on-screen test, and
    -- that got cached. Reading a stable anchor each time costs nothing and heals a bad early
    -- read on the next panel open.
    local x, y, anchor = EX.button_anchor()
    if not x then
        -- Neither anchor exists yet. The HUD is not built at first tick, so this is normal
        -- early and a rename-in-a-patch late; both are handled by retrying.
        if not retry() then
            EX.say("error", "no anchor for the opener button - neither "
                .. "resources_bar_holder nor faction_buttons_docker exists")
        end
        return
    end
    -- A SMALL OVERSHOOT IS CLAMPED; A WILD ONE IS STILL REFUSED.
    --
    -- Refusing a bad read is the POINT: with the screen size taken from root:Bounds() a docker
    -- reading of 2150,1097 passed the guard and drew the button at 2090,1195 on a 1600x900
    -- screen, and resources_bar is ANIMATED - it slides off the top for the intro, cutscenes
    -- and end-turn, reporting by = -100, -527, -601, -640 while away against -4 when settled.
    --
    -- But a flat "x < 0 or y < 0" refuses a SETTLED anchor too, and that is how the button
    -- never appeared for a Cathayan faction (reported 2026-09-08): Cathay's resource strip
    -- sits a few pixels higher than the Empire's, the arithmetic below it landed on y = -5,
    -- and the button was refused on every attempt until the chain ran out. The panel then has
    -- no way in at all, because placement only runs again from EX.layout - which needs the
    -- button the player cannot reach.
    --
    -- So: within one button of the screen means the anchor is real and the button merely pokes
    -- out, which is a clamp. Anything further out is a bad or mid-animation read, which is a
    -- retry. The clamp can move the button by at most EX.BUTTON_SIZE, and placement is
    -- recomputed on every panel open, so a clamp taken during an animation heals itself.
    local tol = EX.BUTTON_SIZE
    if x < -tol or y < -tol or x + EX.BUTTON_SIZE > sw + tol
       or y + EX.BUTTON_SIZE > sh + tol then
        -- NOT a failure once the button is already placed - EX.layout() calls this on
        -- every panel open and a hidden resource strip must leave the button where it is.
        local again = retry()
        if not again then
            -- WHY IT DECLINED, because the three reasons are not the same news and the line
            -- used to report all three as "no attempts left".
            --
            -- Two of them are routine. EX.layout() and the panel-opened hook both call
            -- place_button(EX.PLACE_TRIES) deliberately, as a one-shot that must NOT start a
            -- second chain alongside the first tick's - so every panel open while the resource
            -- strip is hidden or animating logs a decline that means nothing at all. Measured
            -- in a Southern Realms campaign 2026-09-08: two of these at -91 and -526, then the
            -- button placed correctly at 1168,5 a few seconds later, and the log read like a
            -- failure the whole time. That cost a full investigation to conclude nothing was
            -- wrong, which is what a log line that cries wolf is for.
            --
            -- The third is the real one: the chain itself ran out having never placed it. Only
            -- that case is an error, and only that case now says so.
            local why
            if EX.button_at then
                why = "already placed at " .. tostring(EX.button_at)
                      .. ", so this reading is ignored - normal"
            elseif attempt >= EX.PLACE_TRIES then
                why = "this caller is a deliberate one-shot and does not reschedule; the "
                      .. "first-tick chain still owns placement - normal"
            else
                why = "and the placement chain is exhausted - THE BUTTON IS NOT PLACED"
            end
            -- "error" bypasses the level and category gates entirely (see EX.say), so it is
            -- reserved for the one case that is actually broken. The routine two stay on "ui".
            local routine = EX.button_at or attempt >= EX.PLACE_TRIES
            EX.say(routine and "ui" or "error",
                   "declined to place the button, " .. anchor .. " put it at "
                .. x .. "," .. y .. " on a " .. sw .. "x" .. sh
                .. " screen - too far out to clamp, " .. why)
        end
        return
    end
    if x < 0 then x = 0 end
    if y < 0 then y = 0 end
    if x + EX.BUTTON_SIZE > sw then x = sw - EX.BUTTON_SIZE end
    if y + EX.BUTTON_SIZE > sh then y = sh - EX.BUTTON_SIZE end
    b:MoveTo(x, y)
    b:SetVisible(true)
    -- WRITTEN HERE, not once at creation: place_button is re-run from EX.layout and from
    -- FactionTurnStart, so a tooltip set before EX.bind_race resolved the race is corrected
    -- rather than left saying the wrong market's name for the campaign.
    b:SetTooltipText(EX.button_tip(), true)
    -- READ IT BACK. This is the check that would have caught the RadialList on day one instead
    -- of costing two screenshots and a wrong fix: if the position we asked for is not the
    -- position we got, something else is laying this component out and no amount of MoveTo will
    -- win. Nothing else in the engine reports that - the button simply appears elsewhere.
    local ax, ay = b:Position()
    if ax ~= x or ay ~= y then
        EX.say("error", "MoveTo OVERRIDDEN - asked " .. x .. "," .. y
            .. " got " .. ax .. "," .. ay .. ". The parent is laying this component out.")
    end
    -- EX.layout() calls this on every panel open and every mode toggle, and an unconditional
    -- log line wrote five "opener button at" lines in the first two minutes. This file's own
    -- diagnosis method is reading script_log, so noise here is how a real line gets missed.
    -- The ANCHOR is in the log line on purpose: falling back to the bottom-right docker is
    -- silent otherwise, and "the button moved back to where it used to be" is exactly the
    -- report that would follow a CA rename.
    local where = x .. "," .. y .. " (" .. anchor .. ")"
    if EX.button_at ~= where then
        EX.button_at = where
        EX.say("ui", "opener button at " .. where)
    end
end

-- ===========================================================================================
-- THE TREASURY BAR
-- ===========================================================================================

-- WHY THIS IS A UI OVERRIDE AND NOT AN EFFECT. The bar reads net_income() and the engine files
-- a scripted cm:treasury_mod as a one-off "Event Outcome", so the rent is in neither term: the
-- player is shown +2338 and receives +1604. There is no DB route left. Measured, twice, across
-- real turn boundaries:
--   a CUSTOM bundle carrying wh2_main_effect_background_income_mod at -734  -> income 4370, 4371
--   CA'S OWN static wh3_main_background_income_mod_1000 at +1000            -> income 3600, 3600
-- and a full survey of the effects table says that is the only flat faction-gold effect in the
-- game: every gdp_* effect is a PERCENTAGE and all 500-odd of its rows are scoped *_to_region_*,
-- and every upkeep effect is a percentage scoped to a force. So the number is corrected where it
-- is drawn.
--
-- ponytail: this FIGHTS the engine rather than joining it. The engine owns dy_income and
-- rewrites it whenever income changes, so this re-reads and re-applies on a timer. The ceiling
-- is that the hover breakdown behind the treasury button still totals the unadjusted figure -
-- its rows are engine-built and a mod cannot add one. Upgrade path if that ever matters: brand
-- the breakdown's own total the same way, once someone finds which component it is.
EX.HUD_PERIOD = 1.0

-- Two states, both authored in hud_campaign_resource_bar_wh3.twui.xml: "positive" is green and
-- "negative" is red. The engine picks by sign and EACH CARRIES ITS OWN TEXT, so both get
-- written - exactly the trap that showed the placeholder "100" in the finance panel.
EX.HUD_STATES = { "positive", "negative" }

function EX.income_label()
    return find_uicomponent(core:get_ui_root(), "hud_campaign", "resources_bar_holder",
                            "resources_bar", "treasury_holder", "treasury_holder_standard",
                            "dy_income")
end

function EX.brand_income()
    local c = EX.income_label()
    -- find_uicomponent returns FALSE, not nil. Absent during loading, battles and the frontend,
    -- and this runs every second in all of them.
    if not is_uicomponent(c) then return end
    local fname = EX.me()
    if not fname then return end
    local faction = cm:get_faction(fname)
    -- get_faction returns FALSE, not nil, for an unknown key - see the note on EX.rescan.
    if not faction or faction:is_null_interface() then return end
    -- THE NUMBER IS COMPUTED, NEVER READ BACK. net_income() is exactly what the engine puts in
    -- this label - measured, net_income 1551 against a label reading 1551 - so the correct text
    -- is derivable from scratch on every pass and nothing has to be remembered.
    --
    -- The first draft did read the label, subtract, and write, with a memo to stop the
    -- subtraction compounding every tick. That memo cannot tell "our text is still on screen"
    -- from "the engine has refreshed to the same number", and the check caught it: sell the
    -- last crate while the engine happens to display the figure we wrote, and the bar sticks
    -- for ever. Deriving the value has no such state and no such case.
    local want = faction:net_income() - EX.carry_total()
    local text = tostring(want)
    if c:GetStateText() == text then return end
    -- BOTH states, then the one the sign calls for. Each carries its own text and the engine
    -- flips between them on its own, so an unwritten state shows whatever was there before -
    -- the same trap that showed the placeholder "100" in the finance panel.
    for i = 1, #EX.HUD_STATES do
        c:SetState(EX.HUD_STATES[i])
        c:SetStateText(text)
    end
    if want < 0 then c:SetState("negative") else c:SetState("positive") end
end

-- ===========================================================================================
-- CA'S FINANCE PANEL
-- ===========================================================================================

-- THE RENT IS NOT INVISIBLE. Measured live on turn 13 with the panel open: CA's detailed
-- finance screen lists it under Expenses > Event Outcomes at 734 this season and 1468 last,
-- and sums it into Total Expenses correctly (12125 construction + 2033 unit upkeep + 734 =
-- 14892). Every cm:treasury_mod is filed into the engine's payload category, whose header is
-- the loc key finance_header_payload and whose tooltip reads "Income from missions, random
-- incidents and dilemmas".
--
-- That corrects the note on EX.charge_carry and the whole reason build 5 reached for an income
-- effect. The only panel that cannot see the rent is the small Predicted Income tooltip, which
-- forecasts RECURRING lines only - CA's own 12125 of construction spending is missing from it
-- too - and no mod can add a line to it.
--
-- WHAT IS ACTUALLY WRONG IS THE COLOUR. Every number in that list is a dy_value with a
-- "positive" state (green) and a "negative" state (red), and the engine leaves the payload row
-- on "positive" however far into the red it goes: measured, Construction and Unit Upkeep both
-- sat in [negative] while our 734 sat in [positive] - green, in the Expenses column, under a
-- red total. It is CA's bug and it predates this mod, but this mod is what puts a number in
-- that row every turn.
--
-- SetState ALONE LOSES THE NUMBER. Each state carries its own authored text: switching
-- dy_value1 to "negative" replaced the live 734 with the twui's placeholder "100". Measured,
-- and the same rule as MEMORY/wh3-setstatetext-is-per-state - read the text in the old state
-- and write it into the new one.
--
-- NO ^ ANCHORS BELOW. string.sub prefix tests instead, because the bridge used to measure all
-- of this mangles a pattern anchor in transit and a check that cannot be run in the game is
-- worth less than one that needs no patterns at all.
function EX.recolour_finance()
    local lb = find_uicomponent(core:get_ui_root(), "finance_screen", "tab_summary",
                                "tab_child", "summary", "listview", "list_clip", "list_box")
    -- find_uicomponent returns FALSE, not nil. This is also the entire filter for the listener
    -- below, which fires on every panel in the game: one failed lookup and out.
    if not is_uicomponent(lb) then return end
    -- One flat run of rows: header_0 (Income), its subheaders and entries, header_sum_16,
    -- spacing_17, header_18 (Expenses), its rows, header_sum_34. The SECOND bare header_ opens
    -- the expenses. header_sum_ is a section total, not a header, hence the inner test.
    local section, fixed = 0, 0
    for i = 0, lb:ChildCount() - 1 do
        local row = UIComponent(lb:Find(i))
        local id = row:Id()
        if string.sub(id, 1, 7) == "header_" then
            if string.sub(id, 1, 11) ~= "header_sum_" then section = section + 1 end
        elseif section == 2 and string.sub(id, 1, 6) == "entry_" then
            for j = 0, row:ChildCount() - 1 do
                local v = UIComponent(row:Find(j))
                if string.sub(v:Id(), 1, 8) == "dy_value"
                        and v:CurrentState() ~= "negative" then
                    local t = v:GetStateText()
                    -- A zero stays green. CA leaves its own empty expense rows green, and a
                    -- red 0 reads as a cost that is not actually there.
                    if t ~= "" and t ~= "0" then
                        v:SetState("negative")
                        v:SetStateText(t)
                        fixed = fixed + 1
                    end
                end
            end
        end
    end
    -- THE ONLY TRACE THIS LEAVES. The wh3 bridge died twice in one session reading this panel
    -- and script_log is what is left, so the recolour says what it did - but only when it did
    -- something, because this fires on every panel open in the game.
    if fixed > 0 then
        EX.say("ui", "finance panel, reddened " .. fixed .. " expense cells")
    end
end

-- ===========================================================================================
-- THE MOD'S OWN SAVE STORE - and why this is not cm:set_saved_value any more.
-- ===========================================================================================
--
-- MEASURED 2026-09-07, and it cost a live campaign its entire share position.
--
-- cm:set_saved_value does NOT write a value of its own into the savegame. Every value every
-- mod on the machine sets is concatenated by CA into ONE string - name:::type:::len:::value;;;
-- repeated - and that single string is handed to the engine under the name "saved_values"
-- (lib_campaign_manager.lua:1688). On load it is read back and re-parsed.
--
-- THE ENGINE CAPS THAT STRING AT 28,672 BYTES (0x7000) AND DROPS IT WHOLE. From the previous
-- session's own log, the blob grew 17,666 -> 19,880 -> ... -> 28,672 over ten turns and stopped
-- dead on 0x7000 - the only line in a 6MB log at exactly that length, in a file that carries
-- lines of 40,484, so it is the value that was capped and not the logging. The next load got
-- the default "" back, and CA's parser BREAKS SILENTLY on an empty string
-- (load_values_from_string, "if not next_separator then break"). No script error, no warning:
-- all 305 saved values from every mod simply were not there.
--
-- The exchange was 101 of those 307 entries and 6,211 of the 28,672 characters - 21.7%, the
-- largest single contributor, and the only one that grows every turn (a zharr_hist_ and a
-- zharr_shock_ per instrument). So it was both the biggest victim and a principal cause.
--
-- THE FIX IS TO STOP RIDING THE SHARED BLOB. cm:save_named_value writes an INDEPENDENT named
-- value, which is what CA's own docs tell client scripts to prefer, and our whole state is
-- ~6KB against a 28KB ceiling it now has to itself. It also hands 21.7% of the shared blob
-- back to every other mod on the machine, which is the part that helps a save that is already
-- close to the line.
--
-- EX.getv FALLS BACK TO THE OLD STORE so a campaign saved before today still restores: its
-- values are in CA's blob and nowhere else. The fallback costs one table lookup and can be
-- deleted once no such save matters.
EX.SAVE_STORE = "zharr_state"
EX.store = {}

function EX.setv(key, value)
    EX.store[key] = value
end

function EX.getv(key)
    local v = EX.store[key]
    if v ~= nil then return v end
    return cm:get_saved_value(key)          -- migration path, see above
end

-- LoadingGame arrives BEFORE the first tick (CA's own sequencing note on
-- add_loading_game_callback), and EX.restore runs IN the first tick, so the store is always
-- populated before anything reads it. Registered at script root because by first tick the
-- LoadingGame event has already been and gone.
cm:add_loading_game_callback(function(context)
    local ok, t = pcall(function()
        return cm:load_named_value(EX.SAVE_STORE, {}, context)
    end)
    EX.store = (ok and type(t) == "table") and t or {}
end)

cm:add_saving_game_callback(function(context)
    pcall(function() cm:save_named_value(EX.SAVE_STORE, EX.store, context) end)
end)

-- THE TICKET-CLICK TAIL, LIFTED OUT OF THE LISTENER for the same reason EX.row_click is
-- below - a harness has to be able to drive a Place click with no live campaign. These six
-- components are PANEL-LEVEL, with no row parent, so the listener calls this BEFORE the
-- `UIComponent(clicked:Parent())` walk that resolves every other click to a row: a branch
-- that only exists after that walk would be unreachable from these clicks and every geometry
-- check would still be green, which is exactly the two fix rounds this cost before a harness
-- could drive it at all.
function EX.ticket_click(s)
    -- THE SWITCH, FIRST. The ticket is placed by the chart page as well as the ledger, and the
    -- chart page answers to deep_history - so with orders off these seven cells were on screen
    -- and live. EX.draw_ticket hides them; this is the half that holds if a click reaches here
    -- anyway, and EX.place_order_check is the half that holds for the model.
    if not EX.feature("orders") then return end
    local res = EX.selected
    if not res then return end
    -- ANY EDIT TO THE TICKET CLEARS THE LAST REFUSAL: it described the order that was on
    -- screen when Place was pressed, and this click has just changed that order.
    EX.ord_refusal = nil
    if s == "ord_side" then
        EX.ord_side = (EX.ord_side == "b") and "s" or "b"
    elseif s == "ord_cmp" then
        EX.ord_cmp = (EX.ord_cmp == "le") and "ge" or "le"
    elseif s == "ord_qty" then
        EX.cycle_amount()
    elseif s == "ord_qty_down" then
        EX.step_amount(-1)
    elseif s == "ord_qty_up" then
        EX.step_amount(1)
    elseif s == "ord_down" or s == "ord_up" then
        local r = (EX.ord_rung or EX.current[res] or EX.neutral_rung())
            + ((s == "ord_up") and 1 or -1)
        if r < 1 then r = 1 end
        if r > EX.RUNGS then r = EX.RUNGS end
        EX.ord_rung = r
    elseif s == "ord_place" then
        local rung = EX.ord_rung or EX.current[res] or EX.neutral_rung()
        -- THE DRY RUN FIRST. A refusal EX.place_order_check already knows about - the cap,
        -- a duplicate, an invalid rung - needs no network round trip at all, and reporting
        -- it locally is what keeps the button and EX.MP_OPS.ord from disagreeing about why.
        local why = EX.place_order_check(res, EX.ord_side, EX.ord_cmp, rung)
        if why then
            EX.say("trade", "order refused: " .. why)
            -- ON SCREEN, NOT ONLY IN THE SCRIPT LOG. EX.say is out() behind log_level >= 2 AND
            -- the log_trade debug toggle, so every refusal this button can give - the cap, a
            -- duplicate, an unorderable instrument, the switch - was invisible in a real game
            -- and the button simply looked dead. The ticket prints it and the Log view keeps
            -- it, which is the standard EX.apply_trade's own refusals already hold to.
            EX.ord_refusal = why
            EX.log_add(EX.log_subject(res), why)
        else
            EX.order_send(res, EX.ord_side, EX.ord_cmp, rung)
        end
    end
    EX.refresh_panel()
end

-- THE ROW-CLICK TAIL, LIFTED OUT OF THE LISTENER so it can be called without a live campaign.
-- The listener body is unreachable from any harness - it is an anonymous function inside
-- EX.init behind a real ComponentLClickUp - so every check of a row click used to call the
-- MODEL directly and proved nothing about whether the click reached it. It did not: the
-- ledger's Cancel sat below a `if not res then return end` gate that a synthetic ord%d row id
-- can never pass, and the whole page was dead with every other check green.
function EX.row_click(s, row_id)
    -- A LEDGER ROW RESOLVES THROUGH EX.order_of_row, NOT EX.res_of_row - a synthetic
    -- "ord%d" id names no instrument, so the res_of_row gate below would eat every ledger
    -- click before this branch was ever reached. THIS ORDER IS THE FIX: on_orders first,
    -- the instrument gate second.
    if EX.on_orders() then
        -- THE ROW'S INDEX, NOT ITS INSTRUMENT. A ladder puts two rows on one
        -- commodity and EX.res_of_row cannot tell them apart - see EX.order_of_row.
        local o = EX.order_of_row(row_id)
        if o and s == "btn_buy" then
            EX.order_cancel_send(o.res, o.side, o.cmp, o.rung)
            EX.layout()
            EX.refresh_panel()
        end
        return
    end
    -- A DEAL ROW RESOLVES THROUGH EX.deal_of_row, AND IT HAS TO BE ABOVE THE GATE BELOW for
    -- the same reason the ledger branch is: "dl3" names no instrument, so EX.res_of_row
    -- answers nil and the gate would eat every deal click before this branch was reached.
    -- That is how Stage 1 shipped a dead Cancel button with every check green.
    if EX.mode == EX.MODE_DEALS then
        local n = EX.deal_of_row(row_id)
        if n and s == "btn_buy" then EX.deal_send(n) end
        return
    end
    local res = EX.res_of_row(row_id)
    if not res then return end
    -- A NAME CLICK CHARTS IT, and takes you to the page the chart is on. Doing
    -- only one of those leaves the player looking at an unchanged list wondering
    -- whether the click registered.
    if s == "row_name" then
        EX.selected = res
        -- A NEW SELECTION RETIRES THE LAST REFUSAL - it named a different instrument.
        EX.ord_refusal = nil
        -- THE PAGE THE SELECTION IS FOR, NOT THE LITERAL 2: the chart when there is one, the
        -- ticket's page otherwise. EX.chart_page_index alone was right only while the ticket
        -- lived on the chart page - with deep_history off it returns nil, and the click left
        -- the player on the list with no indication anything had happened.
        local cp = EX.selection_page_index()
        if cp then EX.trade_page = cp end
        -- The ticket opens on this instrument's own current rung.
        EX.ord_rung = EX.current[res] or EX.neutral_rung()
        EX.layout()
        EX.refresh_panel()
        return
    end
    -- Same component, different verb. btn_buy is the Sacrifice button in the
    -- offerings view, which is why the mode is checked and not just the name.
    if EX.mode == EX.MODE_OFFER then
        if s == "btn_buy" then EX.offer(res) end
    else
        EX.trade(res, s == "btn_buy")
    end
end

-- THE WHOLE CLICK HANDLER, LIFTED OUT for the same reason EX.row_click and EX.ticket_click
-- are above it - and this is the piece that was still missing. Extracting the TAILS proved
-- each of them behaves correctly once called; it proved nothing about whether the real
-- dispatch actually REACHES the ticket branch before the row-resolution walk below it. That
-- gap is exactly how Task 6's Cancel button shipped dead: a correct model, a correct filter,
-- and a handler branch that was never reachable, with every check in the suite green.
--
-- Callable with a bare { string = <component name>, component = <fake UIComponent> } table
-- and no live campaign - see tools/_orders_harness.lua's "TICKET DISPATCH" section, which
-- drives a Place click through THIS function rather than calling EX.ticket_click directly,
-- and separately proves the ticket branch runs before UIComponent(clicked:Parent()) by
-- handing it a component whose Parent() would resolve to a row.
function EX.click_dispatch(context)
    local s = context.string
    if s == EX.BUTTON then
        -- NOT DURING THE AI ROUND. Belt to EX.gate_button's braces: a disabled
        -- component should raise no click at all, but this is the half that is true
        -- even on a save loaded mid-round, where nothing has run to grey anything.
        if not EX.player_turn() then return end
        local p = EX.panel()
        EX.show(not (is_uicomponent(p) and p:Visible()))
        return
    end
    if s == "close_button" then
        EX.show(false)
        return
    end
    if EX.sort_click(s) then return end
    if s == EX.HELP_BTN then
        -- A TOGGLE, and it returns you to the view you left. Sending the player back
        -- to the trade view instead would lose their place every time they checked
        -- what a column meant, which is the one moment they are already lost.
        if EX.mode == EX.MODE_HELP then
            EX.set_mode(EX.mode_before_help or EX.MODE_TRADE)
        else
            EX.mode_before_help = EX.mode
            -- The guide opens on page 1 every time. Persisting the page would
            -- reopen on a page about a system the player has since switched off
            -- in MCT (Task 10 adds those toggles). EX.help_page is view state,
            -- never saved - see the note beside its declaration.
            EX.help_page = 1
            EX.set_mode(EX.MODE_HELP)
        end
        return
    end
    if s == EX.MODE_BTN or s == EX.MODE_PREV then
        EX.nav_click(s)
        return
    end
    -- THE TICKET, ABOVE THE ROW WALK BELOW. These five have no row parent - they are
    -- PANEL-LEVEL - so `UIComponent(clicked:Parent())` would resolve to the panel
    -- itself, not a row, and EX.row_click has no branch for that. THE TAIL LIVES IN
    -- EX.ticket_click, a top-level function outside EX.init, for the same reason
    -- EX.row_click does - see its own comment.
    if s == "ord_side" or s == "ord_cmp" or s == "ord_down"
       or s == "ord_up" or s == "ord_place" or s == "ord_qty"
       or s == "ord_qty_down" or s == "ord_qty_up" then
        EX.ticket_click(s)
        return
    end
    -- THE LIST'S OWN AMOUNT BUTTON, not routed through EX.ticket_click: that function gates
    -- on EX.feature("orders") and on a selected instrument, and neither has anything to do
    -- with how many lots a manual Buy moves. With orders switched off the ticket is gone and
    -- this button must still work.
    if s == "btn_amount" or s == "btn_amt_down" or s == "btn_amt_up" then
        if s == "btn_amount" then EX.cycle_amount()
        else EX.step_amount(s == "btn_amt_up" and 1 or -1) end
        EX.layout()
        EX.refresh_panel()
        return
    end
    local tab = EX.tab_mode(s)
    if tab then
        -- LEAVING THE GUIDE BY TAB has to clear the return-to memory the help button
        -- keeps, or the next press of "?" would toggle back to a view the player left
        -- two tabs ago rather than the one they are looking at.
        EX.mode_before_help = nil
        EX.set_mode(tab)
        return
    end
    -- NO CELL OR BUTTON CARRIES A KEY, so the row it belongs to is what identifies
    -- it. One resolution for all three of buy, sell and the name click - this walk
    -- used to be written out here and a second copy for the chart would be two
    -- places to change when the row naming does.
    --
    -- THE TAIL ITSELF LIVES IN EX.row_click, a top-level function outside EX.init,
    -- so a harness can call it with a bare row id and no live campaign - see the
    -- comment on EX.row_click for why its internal order matters.
    local clicked = UIComponent(context.component)
    local row = UIComponent(clicked:Parent())
    EX.row_click(s, row:Id())
end

-- EVERYTHING THIS MOD DOES AT STARTUP, and it is deliberately not an anonymous first-tick
-- callback any more.
--
-- WHY: cm:process_first_tick_callbacks (lib_campaign_manager.lua:2471) runs all five callback
-- lists through call_each, and call_each has NO pcall. One throwing callback belonging to any
-- other mod on the machine ends the whole pass, and every callback after it in the list simply
-- never runs. This mod's file is named zzz_* to load last, which put it 69th of 69 - the worst
-- possible slot. Measured 2026-09-07: cm.is_processing_first_tick_callbacks was still true on a
-- loaded save, the opener button was absent, and nothing in the log named this script.
--
-- THE FIX IS A SECOND, INDEPENDENT ENTRY POINT. core:add_listener callbacks are dispatched one
-- at a time through xpcall (lib_core.lua, event_protected_callback), so a listener that throws
-- cannot stop any other listener - the opposite of call_each. And CA triggers
-- ScriptEventFirstTickAfterWorldCreated from inside cm:first_tick BEFORE it starts the callback
-- lists, so this route both runs earlier and cannot be reached by another mod's failure.
--
-- The first-tick registration stays as the belt: it is CA's documented route, and if a patch
-- ever stops triggering that event the mod still starts. EX.inited makes whichever arrives
-- second a no-op.
function EX.init()
    if EX.inited then return end
    EX.inited = true
    -- BEFORE EVERYTHING. EX.me() is legal from the first tick onward and not before, and every
    -- line under here reads it - directly, or through EX.who() and EX.humans(). Adopting the
    -- file-scope tables as this client's slice has to happen before any of them is written, or
    -- the first write lands in a slice nothing will ever read back.
    EX.forget_humans()
    EX.adopt_local()
    -- FIRST, BEFORE EX.rescan. rescan -> scan_supply reads EX.HOUSE_CULTURES once per region,
    -- so the rebind has to land before the first scan or turn one's house-region tally is
    -- counted against the Chaos Dwarf default whatever the players actually are.
    EX.bind_race()

    -- THE CULTURE LOCK, and this is the ONLY place it is enforced. After bind_race, because it
    -- reads EX.HOUSE_CULTURE; before everything else, because a locked culture must get no
    -- scan, no UI, no listeners, no saved state and no turn round - as close to "this mod is
    -- not installed" as one return statement gets.
    --
    -- EX.inited IS ALREADY TRUE above, so this returns once and stays returned for the session.
    -- That means UNLOCKING IN MCT NEEDS A RESTART, which the switch's own tooltip says: the
    -- alternative is every listener in this file checking the lock on every call, for a setting
    -- nobody changes twice.
    local locked = EX.exchange_locked()
    if locked then
        EX.say("turn", "no Exchange for " .. tostring(EX.HOUSE_CULTURE)
            .. " - the " .. locked .. " group is locked in the mod settings. Nothing further "
            .. "runs this session; enable it and restart to trade.")
        return
    end

    EX.rescan()
    -- Validate our keys once. resource_exists_anywhere returns false for an INVALID key, which
    -- is the only free runtime key validator available here.
    --
    -- IT IS NO LONGER SUFFICIENT ON ITS OWN. Since supply became production, a commodity with
    -- no deposit anywhere is a perfectly normal commodity - measured on this map, glass and
    -- trinkets have ZERO deposit regions and the world makes 6 and 59 units a turn from
    -- buildings that need no deposit. The old message called that "absent from this map",
    -- which is exactly the false conclusion the region model already led to once.
    -- A real typo is absent from BOTH: no deposit and nothing that produces it.
    local producible = {}
    if EX_PRODUCTION then
        for _key, pairs_ in pairs(EX_PRODUCTION) do
            for k = 1, #pairs_ do producible[pairs_[k][1]] = true end
        end
    end
    local rm = cm:model():world():region_manager()
    for _, res in ipairs(EX.COMMODITIES) do
        if not rm:resource_exists_anywhere(res) then
            if producible[res] then
                EX.say("error", "no deposits of " .. res
                    .. " on this map - its supply is all production")
            else
                EX.say("error", res .. " has no deposit AND nothing produces it - "
                    .. "either a typo'd key or a commodity this map cannot trade")
            end
        end
    end

    -- ONCE PER SESSION, UNCONDITIONAL. EX.houses is always empty here - this callback runs
    -- before EX.restore() populates it - so a cm:is_new_game() guard was dead weight, never
    -- actually skipping a call. Safe to run every load anyway: discovery MERGES rather than
    -- replaces, so a second run this session costs one faction_list walk and changes nothing.
    -- Discover, then restore - restore reads EX.houses.
    EX.discover_houses()

    EX.restore()
    EX.apply_prices()
    EX.apply_trade_income()
    -- THE SAME RESYNC, for the same reason and one bundle family over. EX.rescan() above has
    -- already filled EX.actors, so this is a real sweep and not the early return. Without it a
    -- loaded save wears last session's position bundles until the next turn start, which is
    -- exactly the window apply_trade_income is called here to close.
    EX.apply_positions()
    -- RESYNC, NOT A CHARGE. Effect bundles survive the save and this script's tables do not,
    -- so a load carries whatever tier the last session applied while EX knows nothing about
    -- it. apply_stockpiles removes every tier it does not want, which makes a load self-heal
    -- even if the holding changed outside this script. EX.charge_carry is deliberately NOT
    -- called here: a load is not a turn, and five reloads would be five rent days.
    EX.apply_stockpiles()

    -- The treasury bar, for ever. A find_uicomponent and a string compare every second; the
    -- engine owns this label and there is no event that fires when it changes.
    local function brand_loop()
        EX.brand_income()
        cm:callback(brand_loop, EX.HUD_PERIOD, "zharr_brand_income")
    end
    cm:callback(brand_loop, EX.HUD_PERIOD, "zharr_brand_income")

    cm:callback(function()
        EX.strip_legacy_bundles()
        EX.make_button()
        -- A LOAD RESTORES NO FLAG, so the first thing after the button exists is to ask.
        EX.gate_button(EX.player_turn())
        if EX.build_panel() then
            EX.panel():SetVisible(false)
        end
    end, 1.0, "zharr_exchange_ui")

    -- THE TWO MCT DEBUG BUTTONS. Registered here rather than at file root for the same reason
    -- everything else is: nothing runs at script root in this file. The events are fired by
    -- script/mct/settings/derpy_chd_zharr_exchange.lua, which cannot see EX directly.
    core:add_listener("zharr_exchange_dump_state", "ZharrExchangeDumpState",
        true, function() EX.dump_state() end, true)
    core:add_listener("zharr_exchange_dump_supply", "ZharrExchangeDumpSupply",
        true, function() EX.dump_supply() end, true)

    -- ONE ROUND OF THE MARKET, and the only place the whole thing is ordered.
    --
    -- THREE KINDS OF WORK, and telling them apart is what makes this multiplayer-correct:
    --
    --   WORLD   - the scan, the books, the reprice, the shocks, the trade-income bundles.
    --             One answer for the campaign. Runs once, unbound, and every machine computes
    --             the identical result from the identical inputs.
    --   PLAYER  - the tithe, the rent, the dividends, the warehouse bonus, the bulletins.
    --             Runs once PER HUMAN, on EVERY machine, with that human bound as the subject.
    --             This is the half that used to be scoped to the local faction, and doing it
    --             for only the local faction is precisely what a desync looks like: every
    --             client would move a different set of treasuries.
    --   LOCAL   - the opener button and the panel. Per client by definition, never the model.
    --
    -- THE ORDER IS LOAD-BEARING AND IS THE ORDER IT ALWAYS WAS. The four constraints that were
    -- learned the hard way, kept verbatim:
    --
    --   check_demand BEFORE maybe_demand      - an unpaid tithe is punished before the altar
    --                                           asks again.
    --   check_delistings BEFORE apply_prices  - a dead house reprices to rung 1 in one step, so
    --                                           settlement has to be paid at the LIVING price.
    --                                           Measured: 621 alive, 102 repriced; a 40-share
    --                                           position paid 31,050 here against 5,100 after.
    --   step_books BEFORE apply_prices        - the book level feeds EX.target_rung, and houses
    --                                           trade at last turn's prices by design.
    --   apply_stockpiles BEFORE charge_carry  - the tier the player is shown and the rent they
    --                                           are charged must be read off the same holding.
    --
    -- ONCE PER TURN NUMBER, NOT ONCE PER EVENT. In multiplayer every human raises its own
    -- FactionTurnStart and the arrival order is not promised, so the guard is the turn number
    -- rather than "the first human in the list" - that would make the round depend on which
    -- machine's event landed first. A reload re-runs the handler and re-enters here, which is
    -- why every payout in the player half carries its own idempotence guard.
    function EX.turn_round()
        -- A NEW ROUND IS A NEW HUMAN LIST. A player can drop, resume, or be confederated out
        -- of existence between turns.
        EX.forget_humans()
        -- FIRST, BEFORE ANYTHING READS A KNOB. Every line below prices, charges or pays
        -- something out of EX.opt, so the campaign's settings have to be resolved and
        -- frozen before the first of them runs. See EX.snapshot for why this is here and
        -- not in the first-tick path.
        if EX.snapshot() then
            EX.say("turn", "settings locked for this campaign: preset "
                   .. tostring(EX.preset_name()))
        end
        -- A NEW TURN IS NEW DIPLOMACY. Both stance holds are scoped and close themselves,
        -- so nothing should be held here - but a refresh that errored mid-hold would
        -- otherwise leave a stale stance vector pricing every row for the rest of the
        -- campaign. One line, once a turn, and the memo can never outlive a turn boundary.
        EX.free_guild()

        -- PLAYER, pre-reprice: an unpaid tithe is punished before anything else moves.
        for _, f in ipairs(EX.humans()) do
            EX.with_player(f, function() EX.check_demand() end)
        end

        -- WORLD.
        EX.decay_pressure()
        EX.rescan()
        -- AFTER rescan, which is what measures the shares, and before apply_prices, which
        -- is what reads the shock. Here rather than inside rescan because rescan also runs
        -- at first tick and after a load, and a demand shock minted on a load is a price
        -- move a player can farm with F9.
        EX.share_shocks()
        -- BEFORE apply_prices, AND THAT IS THE WHOLE PRICE OF THE POSITION - see the constraint
        -- list above. EX.settle_house pays every human holder off one living price and only
        -- then sets the world delisted flag.
        EX.check_delistings()

        -- THE BOOK MODEL'S REFERENCE PLAYER.
        --
        -- ponytail: EX.house_desire's front-run term and EX.check_standing_sign both ask "how
        -- does this house feel about the player", and in multiplayer there is no single answer.
        -- The first human in the sorted list is used, which in singleplayer is the player and
        -- is therefore exactly the shipped behaviour. The visible consequence in multiplayer is
        -- that the AI houses front-run player one and nobody else. Upgrade path if that matters:
        -- take the most hostile stance across all humans, which is one max() in EX.stance_of -
        -- but it changes singleplayer pricing the moment a second human exists, so measure it.
        local ref = EX.humans()[1]
        EX.with_player(ref, function()
            EX.check_standing_sign()
            EX.step_books()
        end)

        -- THE WORLD TIER, step 9a. Outside EX.with_player: the world trades with itself and
        -- has no reference human, unlike step_books whose front-run term reads a player's book.
        -- Before apply_prices for the same reason step_books is - actors trade at last turn's
        -- prices and the reprice runs on the result.
        EX.step_world()

        -- WORLD. The reprice, and the record of what it settled at.
        EX.apply_prices()
        -- THE DEALS PAGE. After the reprice on purpose - see EX.post_deals. Not on the
        -- first-tick path either: a load is not a turn, and reposting there would overwrite the
        -- list EX.restore just unpacked out of the save.
        EX.post_deals()

        -- PLAYER, step 9b. AFTER apply_prices, so a limit tests the number the panel shows;
        -- BEFORE remember_all, so the bar this turn records is the price the fill got rather
        -- than the price the fill caused.
        EX.fill_factions = {}
        for _, f in ipairs(EX.humans()) do
            EX.with_player(f, function() EX.fill_orders() end)
        end
        -- AFTER apply_prices: it records the rung the turn settled at. Deliberately not
        -- called from the first-tick path - a load is not a turn, and remembering there
        -- would let five reloads fill the whole sparkline with one turn's price.
        EX.remember_all()
        -- ONE REPRICE FOR THE WHOLE ROUND. Every fill bumped EX.pressure and suppressed its
        -- own callback; this is the single reprice they share, and it is after remember_all
        -- so the recorded bar is untouched by it.
        if next(EX.fill_factions) then
            local who = {}
            for f in pairs(EX.fill_factions) do who[#who + 1] = f end
            EX.fill_factions = {}
            cm:callback(function()
                EX.apply_prices()
                for _, faction in ipairs(who) do EX.after_holding_change(faction) end
            end, 0.1, "zharr_after_fills")
        end
        -- WORLD. The guild's books and the world's appetite, decided ONCE and written to every
        -- human's log below. AFTER step_books, which is what fills EX.book_flow, and after
        -- apply_prices, so the appetite line reads the same numbers the panel will draw.
        -- It only BUILDS the lines; nothing is recorded until the per-player flush.
        pcall(EX.build_world_log)

        -- PLAYER. The shock bulletin, read at full strength and before the guard is cleared.
        for _, f in ipairs(EX.humans()) do
            EX.with_player(f, function() EX.announce_shocks() end)
        end

        -- WORLD. AFTER the bulletins, not before: a settlement razed during the AI round has
        -- to be priced at full strength on the turn the players first see it.
        EX.decay_shocks()
        -- A NEW TURN IS NEW NEWS. Raiding the same region again next turn is a second
        -- event and shocks again; raiding it twice in one turn is one event counted twice.
        EX.shocked = {}
        EX.save_shocked()
        -- WORLD, despite the name: this applies a trade-income bundle to EVERY faction that
        -- owns a commodity region, humans and AI alike, off EX.owners.
        EX.apply_trade_income()
        -- WORLD, its sibling, and immediately after it on purpose: both are world effects
        -- landing on AI factions (spec section 11), and a fixed order between the two bundle
        -- families is one less thing that can differ between two clients in multiplayer.
        EX.apply_positions()
        -- WORLD, and the other half of the same idea: apply_trade_income changes what
        -- the market PAYS an AI faction, this changes how the AI houses FEEL about the
        -- players. After the reprice only because it belongs beside it - it reads
        -- EX.owners and the warehouse, neither of which the reprice touches.
        EX.promote_stances()

        -- PLAYER. The warehouse, the rent, the dividends and the next demand.
        for _, f in ipairs(EX.humans()) do
            EX.with_player(f, function()
                -- apply_stockpiles FIRST: paying a demand or a raid can have moved a holding
                -- across a tier boundary, and the bonus should reflect what is in the vault
                -- now rather than what was there last turn. charge_carry second, on the same
                -- holding the tier was just read from, so the row the player sees and the gold
                -- they are charged cannot disagree.
                EX.apply_stockpiles()
                EX.charge_carry()
                -- AFTER apply_prices, same as EX.remember_all above: the dividend has to be a
                -- fraction of the rung THIS turn settled at, not the one still standing when
                -- the turn began. Deliberately not called from the first-tick path either - a
                -- load is not a turn, and five reloads would be five dividend days, the same
                -- trap EX.charge_carry documents for the rent.
                EX.pay_dividends()
                EX.maybe_demand()
                -- LAST IN THE PLAYER BLOCK, so the turn's entries read in the order they
                -- happened once the log reverses them: the guild's trading and the world's
                -- appetite sit ABOVE this player's own rent and dividends.
                pcall(EX.flush_world_log)
            end)
        end

        -- LOCAL. Nothing below here touches the model.
        --
        -- LAST-RESORT RECOVERY FOR THE OPENER BUTTON, and the reason EX.PLACE_TRIES is
        -- only a backstop rather than the thing the button depends on. The first-tick
        -- retry chain covers a strip that is merely still animating in; it cannot cover a
        -- strip that stays away longer than the chain lives. Turn start can: the player is
        -- looking at the map, so resources_bar is up by definition, and EX.button_at makes
        -- this a no-op on every turn after the first that succeeds.
        --
        -- One shot on purpose - EX.PLACE_TRIES means "do not reschedule". Starting a
        -- second CHAIN here would queue cm:callback names the first-tick chain is already
        -- using.
        EX.place_button(EX.PLACE_TRIES)
        -- AFTER place_button, which may have only just created the button.
        EX.gate_button(true)
        if is_uicomponent(EX.panel()) then EX.refresh_panel() end
    end

    -- THE GATE. Any human's turn starting runs the round; the turn-number guard makes every
    -- one after the first a no-op. Filtering on the LOCAL faction - which is what this did
    -- until 2026-09-09 - both threw in multiplayer, because the unforced accessor errors
    -- there, and would have run a different round on each machine if it had not.
    EX.round_turn = nil

    core:add_listener("zharr_exchange_turn", "FactionTurnStart",
        function(context) return EX.is_human(context:faction():name()) end,
        function()
            local t = 0
            pcall(function() t = cm:turn_number() end)
            if EX.round_turn == t then return end
            EX.round_turn = t
            EX.turn_round()
        end, true)

    -- THE MULTIPLAYER TRANSPORT'S RECEIVING END. CA delivers UITrigger to every machine in the
    -- game, in one order, which is the whole reason a trade can be applied identically on all
    -- of them. In singleplayer this listener is registered and never fires: EX.mp_send calls
    -- the op directly rather than broadcasting, so nothing here is on the singleplayer path.
    core:add_listener("zharr_exchange_uitrigger", "UITrigger",
        function(context)
            local ok, hit = pcall(function()
                local id = context:trigger()
                return type(id) == "string"
                       and string.sub(id, 1, #EX.MP_TAG + 1) == EX.MP_TAG .. "|"
            end)
            return ok and hit == true
        end,
        function(context)
            local ok, err = pcall(function()
                local id = context:trigger()
                -- Two captures, and the argument capture is greedy on purpose: a faction or
                -- commodity key never contains a pipe, but "the rest of the string" is the
                -- shape that stays right if one ever does.
                local op, arg = string.match(id, "^" .. EX.MP_TAG .. "|([^|]*)|(.*)$")
                if not op then return end
                local faction = EX.faction_by_cqi(context:faction_cqi())
                if not faction then
                    -- NOT SILENT. A cqi that resolves to no human means this machine and the
                    -- sender disagree about who is playing, which is worth a log line even
                    -- though there is nothing to be done about it here.
                    EX.say("error", "UITrigger " .. tostring(op) .. " from unknown cqi "
                           .. tostring(context:faction_cqi()))
                    return
                end
                EX.mp_apply(faction, op, arg)
            end)
            if not ok then EX.say("error", "UITrigger failed: " .. tostring(err)) end
        end, true)

    -- ---------------------------------------------------------------------------------
    -- SHOCKS. Four listeners, all unfiltered by faction: this is a world market, so a
    -- settlement burned in Lustria moves the ivory price in Zharr-Naggrund.
    --
    -- The RAZED/SACKED/LOOTED events carry a garrison_residence, which knows its region.
    -- CA also ships CharacterRazesSettlement (present tense) with only a loot amount and no
    -- garrison at all, so the past-tense name is the one to listen for - they are not
    -- interchangeable and the wrong one gives no way to find the region.
    -- ---------------------------------------------------------------------------------
    core:add_listener("zharr_shock_raze", "CharacterRazedSettlement", true,
        function(context) EX.shock_from_garrison(context, "razed") end, true)
    core:add_listener("zharr_shock_sack", "CharacterSackedSettlement", true,
        function(context) EX.shock_from_garrison(context, "sacked") end, true)
    core:add_listener("zharr_shock_loot", "CharacterLootedSettlement", true,
        function(context) EX.shock_from_garrison(context, "looted") end, true)
    -- A CAPTURE IS A GARRISON EVENT like the three above, so it reuses their handler and
    -- its region lookup. Two events, because CA ships the opposed and unopposed cases
    -- separately and a settlement walked into is disrupted exactly as much as one stormed.
    -- They cannot double-count each other: only one of the pair fires for any one capture,
    -- and the per-turn guard is keyed by region AND kind, which is the same kind here.
    core:add_listener("zharr_shock_capture", "CharacterCapturedSettlement", true,
        function(context) EX.shock_from_garrison(context, "captured") end, true)
    core:add_listener("zharr_shock_capture_un", "CharacterCapturedSettlementUnopposed", true,
        function(context) EX.shock_from_garrison(context, "captured") end, true)

    -- REBELLION CARRIES ITS REGION DIRECTLY - CA documents region() on this context, which
    -- is why this one does not go through EX.shock_from_garrison. It fires as a faction
    -- ENDS its turn, before FactionTurnEnd, so the shock is already standing when the next
    -- FactionTurnStart prices it, which is the same timing the raid shocks rely on.
    core:add_listener("zharr_shock_rebels", "RegionRebels", true,
        function(context)
            -- Its own pcall for the reason every interface read in this file has one: a
            -- context that does not answer region() must cost this one shock, not the
            -- listener and everything queued behind it.
            pcall(function() EX.add_shock(context:region(), "rebels") end)
        end, true)

    -- RAIDING. This fires for every army in the world every time it changes stance, so the
    -- condition has to be cheap and it has to reject early.
    --
    -- active_stance() IS READ, NOT context:stance_adopted(). CA documents stance_adopted as
    -- "Interface: NONE", which is a raw value of unstated type, while active_stance() is
    -- documented to return a String - and the event fires on adoption, so the two name the
    -- same stance. Reading the documented one costs an extra interface hop and removes a
    -- guess about the type.
    --
    -- ponytail: a raid is priced as NEWS, once, when it starts - a ten-turn raid is one
    -- spike that fades, not a standing price. Raiding is a STATE and the honest reading is
    -- the siege check in the scan, which needs region:characters_in_region() and a stance
    -- read per character per region per turn. Do that if raids need to hold a price up.
    core:add_listener("zharr_shock_raid", "ForceAdoptsStance",
        function(context)
            local ok, is_raid = pcall(function()
                local mf = context:military_force()
                if not mf or mf:is_null_interface() then return false end
                return EX.RAID_STANCES[mf:active_stance()] == true
            end)
            return ok and is_raid == true
        end,
        function(context)
            local ok, err = pcall(function()
                local ch = context:military_force():general_character()
                if not ch or ch:is_null_interface() then return end
                if not ch:has_region() then return end
                local region = ch:region()
                if not region or region:is_null_interface() then return end
                EX.add_shock(region, "raided")
            end)
            if not ok then EX.say("error", "raid shock failed: " .. tostring(err)) end
        end, true)

    -- NO DilemmaChoiceMadeEvent LISTENER. One that MATCHES hard-crashes this game even with
    -- an EMPTY handler - see the note on EX.DEMANDS_ENABLED. The demand is answered through
    -- the panel instead, which is why EX.pay_demand hangs off EX.offer and not off an event.

    -- CA leaves the Event Outcomes expense row green; see EX.recolour_finance. The listener
    -- takes EVERY panel open in the game rather than filtering on a name, because no vanilla
    -- script writes this panel's name down - grepped all of data_script.pack - and the
    -- recolour already bails on a single failed lookup when it is some other panel.
    core:add_listener("zharr_finance_colour", "PanelOpenedCampaign", true,
        function()
            -- The rows are populated after the open event fires.
            cm:callback(EX.recolour_finance, 0.2, "zharr_finance_colour_cb")
        end, true)

    -- ENDING THE TURN CLOSES THE PANEL. Left open it sits over the whole AI round: 920x736
    -- of interactive box (EX.show) between the player and every army that moves while they
    -- watch. FactionTurnEnd and not the end-turn button's ComponentLClickUp, because the
    -- keyboard shortcut ends the turn too and raises no click. CA's own ToZ script uses this
    -- event with the same context:faction() shape.
    --
    -- Routed through EX.show so the interactive flag comes down with the visibility - see the
    -- note in EX.show; a hidden panel that still eats the mouse is the worse bug. Guarded on
    -- an already-built, already-visible panel so a turn ending with the panel shut is free
    -- and never triggers EX.show's build path.
    core:add_listener("zharr_exchange_close_end_turn", "FactionTurnEnd",
        function(context) return context:faction():name() == EX.me() end,
        function()
            local p = EX.panel()
            if is_uicomponent(p) and p:Visible() then EX.show(false) end
            EX.gate_button(false)
        end, true)

    -- One listener for every click in the game, so the filter has to be cheap and first.
    core:add_listener("zharr_exchange_click", "ComponentLClickUp",
        function(context)
            local s = context.string
            return s == EX.BUTTON or s == "close_button" or s == EX.MODE_BTN
                or s == EX.MODE_PREV or EX.tab_mode(s) ~= nil
                or s == EX.HELP_BTN or s == "btn_buy" or s == "btn_sell"
                -- The name cell, which selects that instrument for the chart.
                or s == "row_name"
                -- THE TICKET. The filter decides whether the game dispatches to us AT ALL -
                -- a name only the handler recognises is a button that never fires, and no
                -- geometry check can see that from here.
                or s == "ord_side" or s == "ord_cmp" or s == "ord_down"
                or s == "ord_up" or s == "ord_place" or s == "ord_qty"
                or s == "ord_qty_down" or s == "ord_qty_up"
                -- THE LIST'S AMOUNT BUTTON. Shipped 2026-09-11 wired into EX.click_dispatch
                -- and NOT into this filter, so it drew, lit on hover and did nothing at all -
                -- which is precisely what the note above says happens. The handler is not the
                -- gate; this is.
                or s == "btn_amount" or s == "btn_amt_down" or s == "btn_amt_up"
                -- Two table lookups, and this filter runs on every click in the game.
                or EX.sort_fn(s) ~= nil
        end,
        -- THE BODY IS EX.click_dispatch, a top-level function outside EX.init - see its own
        -- comment for why the whole dispatch, not just the tails it calls into, has to be a
        -- named function a harness can drive directly.
        EX.click_dispatch, true)
end

core:add_listener("zharr_exchange_init", "ScriptEventFirstTickAfterWorldCreated",
    true, function() EX.init() end, true)
cm:add_first_tick_callback(function() EX.init() end)
