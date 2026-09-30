-- THE MULTIPLAYER SEAM, RUN. Static checks can read that EX.bind_player exists and that the
-- two name lists look complete; they cannot see one player's position leaking into another's,
-- which is the only fault here that costs anybody anything.
--
-- FOUR HUMANS, NOT TWO. Three of the things being measured - the sorted order, the "any human
-- holds it" prune test, and the reference player the AI books front-run - are all trivially
-- true with two and only start meaning something with more.
local SAVED = {}
local GOLD = {}
local BUNDLES = {}
local MESSAGES = {}
local TURN = 10
local MP = false
local AT_WAR = {}

local HUMANS = { "zeta_player", "alpha_player", "mid_player", "omega_player" }
local CULTURE = {
    alpha_player = "wh3_dlc23_chd_chaos_dwarfs",
    mid_player   = "wh_main_emp_empire",
    omega_player = "wh2_main_skv_skaven",
    zeta_player  = "wh_main_brt_bretonnia",     -- uncovered, deliberately
    house_a      = "wh3_dlc23_chd_chaos_dwarfs",
    house_b      = "wh3_dlc23_chd_chaos_dwarfs",
    house_c      = "wh_main_emp_empire",
}
local CQI = { zeta_player = 11, alpha_player = 12, mid_player = 13, omega_player = 14 }

local function mkfac(name)
    return {
        is_null_interface = function() return false end,
        name = function() return name end,
        culture = function() return CULTURE[name] or "wh3_dlc23_chd_chaos_dwarfs" end,
        command_queue_index = function() return CQI[name] or 99 end,
        treasury = function() return GOLD[name] or 100000 end,
        is_dead = function() return false end,
        is_rebel = function() return false end,
        is_quest_battle_faction = function() return false end,
        at_war = function() return AT_WAR[name] == true end,
        region_list = function() return { num_items = function() return 3 end } end,
        military_force_list = function() return { num_items = function() return 2 end } end,
        home_region = function() return { is_null_interface = function() return true end } end,
        pooled_resource_manager = function()
            return { resource = function() return { is_null_interface = function() return false end,
                                                    value = function() return 0 end } end }
        end,
    }
end

local WORLD = { "house_a", "house_b", "house_c" }
for _, h in ipairs(HUMANS) do WORLD[#WORLD + 1] = h end

local LOCAL = "alpha_player"

cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function(_, k, v) SAVED[k] = v end,
    get_saved_value = function(_, k) return SAVED[k] end,
    turn_number = function() return TURN end,
    random_number = function() return 1 end,
    is_multiplayer = function() return MP end,
    get_local_faction_name = function() return LOCAL end,
    get_human_factions = function() return HUMANS end,
    get_faction = function(_, n)
        for _, k in ipairs(WORLD) do if k == n then return mkfac(n) end end
        return false
    end,
    treasury_mod = function(_, f, n) GOLD[f] = (GOLD[f] or 0) + n end,
    faction_add_pooled_resource = function() end,
    apply_effect_bundle = function(_, b, f) BUNDLES[f .. "|" .. b] = true end,
    remove_effect_bundle = function(_, b, f) BUNDLES[f .. "|" .. b] = nil end,
    show_message_event = function(_, f) MESSAGES[#MESSAGES + 1] = f end,
    model = function()
        return { world = function()
            return { faction_list = function()
                        return { num_items = function() return #WORLD end,
                                 item_at = function(_, i) return mkfac(WORLD[i + 1]) end }
                     end,
                     region_manager = function()
                        return { resource_exists_anywhere = function() return true end,
                                 region_by_key = function()
                                    return { is_null_interface = function() return true end }
                                 end }
                     end }
        end,
        turn_number = function() return TURN end }
    end,
}
core = { add_listener = function() end }
CampaignUI = { TriggerCampaignScriptEvent = function() end }
function out() end
function is_uicomponent() return false end
dofile([[%s]])
EX.store = SAVED

-- ------------------------------------------------------------------------------------------
-- 1. THE HUMAN LIST. Sorted, so every machine walks it in one order.
-- ------------------------------------------------------------------------------------------
print("humans " .. table.concat(EX.humans(), ","))
print("is_human_yes " .. tostring(EX.is_human("mid_player")))
print("is_human_no " .. tostring(EX.is_human("house_a")))
print("me " .. tostring(EX.me()))

-- ------------------------------------------------------------------------------------------
-- 2. THE SLICE. Four players, four positions, no leakage in either direction.
-- ------------------------------------------------------------------------------------------
EX.houses = { "house_a", "house_b" }
EX.house_set = nil
EX.adopt_local()
print("subject_after_adopt " .. tostring(EX.subject))

-- ONE STANDING ORDER PER PLAYER, on four distinct real commodities. "orders" is in
-- EX.SLICE_TABLES beside shares_held/offer_until/LOG, and this is the only way to prove the
-- swap actually moves it rather than just naming it: a table left pointing at whoever was
-- bound last would fill every human's orders out of one player's treasury.
local ORDER_OF = {
    alpha_player = { "res_gems",       "b", "le" },
    mid_player   = { "res_dyes",       "s", "ge" },
    omega_player = { "res_gold_idols", "b", "ge" },
    zeta_player  = { "res_rom_timber", "s", "le" },
}

local n = 0
for _, f in ipairs(EX.humans()) do
    n = n + 10
    EX.with_player(f, function()
        EX.set_shares("house_a", n)
        EX.offerings_made = n
        EX.demand_res = "res_" .. f
        EX.offer_until["res_gems"] = n
        EX.LOG[#EX.LOG + 1] = { 1, f, "line for " .. f, "" }
        local o = ORDER_OF[f]
        EX.place_order(o[1], o[2], o[3], n)
    end)
end

local got = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        local o = EX.orders[1]
        local sig = o and (o.res .. ":" .. o.side .. o.cmp .. ":" .. tostring(o.rung)) or "-"
        got[#got + 1] = f .. "=" .. tostring(EX.held("house_a"))
            .. "/" .. tostring(EX.offerings_made)
            .. "/" .. tostring(EX.demand_res)
            .. "/" .. tostring(EX.offer_until["res_gems"])
            .. "/" .. tostring(#EX.LOG)
            .. "/" .. #EX.orders .. ":" .. sig
    end)
end
print("slices " .. table.concat(got, " "))

-- THE SUBJECT COMES BACK. A pass that leaves somebody else bound credits every later payout
-- to the wrong faction, silently and for the rest of the campaign.
print("subject_after_loop " .. tostring(EX.subject))

-- ...INCLUDING AFTER AN ERROR. This is the whole reason EX.with_player carries a pcall.
local ok = EX.with_player("omega_player", function() error("boom") end)
print("errored_returns " .. tostring(ok))
print("subject_after_error " .. tostring(EX.subject))

-- ------------------------------------------------------------------------------------------
-- 3. THE SAVED KEYS. One per player, and the world keys shared.
-- ------------------------------------------------------------------------------------------
local keys = {}
for _, f in ipairs(EX.humans()) do
    keys[#keys + 1] = tostring(SAVED[EX.pkey(EX.SAVE_SHARES .. "house_a", f)])
end
print("saved_per_player " .. table.concat(keys, ","))
print("saved_unscoped " .. tostring(SAVED[EX.SAVE_SHARES .. "house_a"]))

-- THE MIGRATION FALLBACK. An unscoped value is readable ONLY while there is one human - which
-- is every save written before this build, because the mod could not survive first tick in
-- multiplayer. With four humans it must not be readable, or player B inherits player A's money.
SAVED["zharr_migrate_probe"] = 77
print("migrate_many " .. tostring(EX.getp("zharr_migrate_probe", "mid_player")))
local keep = HUMANS
HUMANS = { "alpha_player" }
EX.forget_humans()
print("migrate_one " .. tostring(EX.getp("zharr_migrate_probe", "alpha_player")))
HUMANS = keep
EX.forget_humans()

-- ------------------------------------------------------------------------------------------
-- 4. THE PRUNE TEST. "Nobody holds it", not "I do not hold it".
-- ------------------------------------------------------------------------------------------
EX.with_player("alpha_player", function()
    print("anyone_holds_other " .. tostring(EX.anyone_holds("house_a")))
end)
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function() EX.set_shares("house_a", 0) end)
end
EX.with_player("alpha_player", function()
    print("anyone_holds_none " .. tostring(EX.anyone_holds("house_a")))
end)

-- ------------------------------------------------------------------------------------------
-- 5. THE RACE FOLLOWS THE SUBJECT. A tithe demanded of the Empire player must resolve Sigmar's
-- segment on EVERY machine, including this one, which is playing Chaos Dwarfs.
-- ------------------------------------------------------------------------------------------
EX.bind_race()
local segs = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        segs[#segs + 1] = f .. "=" .. EX.seg() .. "/" .. tostring(EX.covered())
            .. "/" .. EX.patron()
    end)
end
print("segs " .. table.concat(segs, " "))
print("local_race_after " .. tostring(EX.race and EX.race.seg))

-- THE RACE PROFILE FACTORS FOLLOW THE SUBJECT TOO, and this is the subtlest of the three.
-- EX.opt applies EX.race_factor at READ time, and the turn round reads EX.opt while another
-- player is bound - so a factor taken from the LOCAL race would charge the Skaven player's
-- rent at Chaos Dwarf numbers on one machine and Skaven numbers on theirs. Nothing on screen
-- would say so; the treasuries would simply stop agreeing.
--
-- hostile_max, because it is on EX.RACE_TUNABLE and the Skaven profile moves it (x2.2) while
-- the Chaos Dwarf profile has no tune at all - so the two answers are far apart and neither is
-- a rounding artefact.
EX.snap = nil
local facs = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        facs[#facs + 1] = f .. "=" .. string.format("%%.3f", EX.opt("hostile_max"))
    end)
end
print("race_factors " .. table.concat(facs, " "))

-- LAYER 2 IS THE UNION. Chaos Dwarfs are in this game, so the two Chaos Dwarf pools are on
-- the board for everyone - and the Empire player's Buy button must say so rather than looking
-- live and refusing.
print("layer2 " .. table.concat(EX.LAYER2, ",") .. " cultures=" .. tostring(
    (EX.HOUSE_CULTURES["wh3_dlc23_chd_chaos_dwarfs"] and "chd" or "-")
    .. (EX.HOUSE_CULTURES["wh_main_emp_empire"] and "+emp" or "")))

-- ------------------------------------------------------------------------------------------
-- 6. THE TRANSPORT. Singleplayer applies directly; multiplayer sends and applies nothing until
-- the UITrigger comes back.
-- ------------------------------------------------------------------------------------------
EX.applied = nil
EX.MP_OPS.probe = function(arg) EX.applied = tostring(EX.who()) .. ":" .. tostring(arg) end
MP = false
EX.mp_send("probe", "hello")
print("sp_applies " .. tostring(EX.applied))

EX.applied = nil
MP = true
EX.mp_send("probe", "hello")
print("mp_defers " .. tostring(EX.applied))
-- ...and the receiving end resolves the sender by cqi and applies it as THEM, not as us.
EX.mp_apply(EX.faction_by_cqi(13), "probe", "hello")
print("mp_applies " .. tostring(EX.applied))
print("cqi_unknown " .. tostring(EX.faction_by_cqi(4242)))
MP = false

-- MCT IS IGNORED IN MULTIPLAYER. Two players can hold different settings and nothing
-- reconciles them, so the economy has to come off the shipped defaults on every machine.
EX.snap = nil
MP = true
print("mp_preset " .. tostring(EX.opt_live_preset()))
print("mp_spread " .. tostring(EX.opt_live("spread")))
MP = false

-- ------------------------------------------------------------------------------------------
-- 7. THE ROUND RUNS ONCE PER TURN NUMBER, however many humans raise the event.
-- ------------------------------------------------------------------------------------------
local rounds = 0
EX.turn_round = function() rounds = rounds + 1 end
local function fire()
    local t = TURN
    if EX.round_turn == t then return end
    EX.round_turn = t
    EX.turn_round()
end
for _ = 1, #EX.humans() do fire() end
print("rounds_one_turn " .. rounds)
TURN = 11
for _ = 1, #EX.humans() do fire() end
print("rounds_two_turns " .. rounds)

-- ------------------------------------------------------------------------------------------
-- 8. THE DEALS PAGE, AND THE ONE THING THAT MAKES ITS BUTTON SAFE TO SHIP IN MULTIPLAYER.
--
-- EX.mp_send carries the deal's LIST INDEX and nothing else - "3", not a faction and a
-- commodity - so client B's EX.deals[3] must be client A's EX.deals[3] or the two machines
-- settle different trades out of the same click. Two properties, and they are not the same:
--
--   AGREEMENT: every machine computes the same page for the same player. The page is per
--   PLAYER, not per machine (EX.post_deals builds it against EX.who() and excludes humans),
--   so what has to match is A's answer for mid_player against B's answer for mid_player.
--
--   THE RIGHT RECIPIENT: the engine is asked whether the AI would deal with THE BOUND PLAYER,
--   not with whoever is sitting at this machine. Agreement alone cannot see that fault - four
--   machines all asking about their own local player would agree perfectly and be wrong for
--   three players out of four - so the stub below REFUSES one (faction, player) pair and the
--   pages have to disagree in exactly that one place. Measured first without it: all four
--   pages came back identical, which is correct for this feature (the AI world offers the same
--   deals to every human) and is also a check that would have passed on four copies of one
--   string.
-- ------------------------------------------------------------------------------------------
-- house_b will not deal with mid_player and will with everyone else. The recipient is the
-- SECOND argument, which is the `them` side of EX.deal_ok - so this reads the proposing side,
-- `mine`, which is the bound player and the thing under test.
cm.cai_evaluate_quick_deal_action = function(_, mine, them)
    if them.name() == "house_b" and mine.name() == "mid_player" then return 0, false end
    return 42, true
end
EX.snap = { ai_deals = true }

-- TWO INSERTION ORDERS, because pairs() follows the hash layout and the layout follows the
-- order keys were added. This is the only way a single process can stand in for two machines
-- that built their tables from the same save by different routes.
local function build_world(order)
    EX.actors = {}
    for _, f in ipairs(order) do
        EX.actors[f] = { culture = CULTURE[f] or "wh3_dlc23_chd_chaos_dwarfs",
                         war = (f == "house_c"), gold = 50000, regions = 4 }
    end
    EX.actors.house_a.regions = 9
    EX.owners = { res_rom_iron = { house_a = 9 } }
    for _, res in ipairs(EX.COMMODITIES) do EX.current[res] = EX.neutral_rung() end
    EX.wbook = {}
    EX.set_world_book("house_a", "res_rom_iron", 6)
end
local function page()
    local r = {}
    for i = 1, #EX.deals do
        local d = EX.deals[i]
        r[#r + 1] = d.fac .. ":" .. d.res .. ":" .. d.side .. ":" .. d.lots .. ":" .. d.px
    end
    return table.concat(r, ";")
end
local function run_client(order)
    local out = {}
    for _, f in ipairs(EX.humans()) do
        build_world(order)
        EX.with_player(f, function()
            EX.post_deals()
            out[f] = page()
        end)
    end
    return out
end

local CLIENT_A = run_client({ "house_a", "house_b", "house_c",
                              "zeta_player", "alpha_player", "mid_player", "omega_player" })
local CLIENT_B = run_client({ "omega_player", "mid_player", "house_c", "alpha_player",
                              "house_b", "zeta_player", "house_a" })

local agree, distinct, empty, odd = 0, {}, 0, 0
for _, f in ipairs(EX.humans()) do
    if CLIENT_A[f] == CLIENT_B[f] then agree = agree + 1 end
    if CLIENT_A[f] == "" then empty = empty + 1 end
    if string.find(CLIENT_A[f], "house_b", 1) then odd = odd + 1 end
    distinct[CLIENT_A[f]] = true
end
-- THREE OF FOUR, and it must be mid_player that is missing house_b. A mod that asked the
-- engine about the local player would print 4 here on the alpha_player machine and 3 on
-- mid_player's - the same save, two answers.
print("deal_house_b_pages " .. odd)
print("deal_mid_has_house_b " .. tostring(string.find(CLIENT_A.mid_player, "house_b", 1) ~= nil))
local n = 0
for _ in pairs(distinct) do n = n + 1 end
print("deal_pages_agree " .. agree .. "/" .. #EX.humans())
print("deal_pages_distinct " .. n)
print("deal_pages_empty " .. empty)

-- AND THE OP SETTLES AS THE SENDER. mid_player clicks Take on their machine; this machine is
-- playing alpha_player, and the gold that moves here must still be mid_player's. Applying it
-- as the local player is a desync that looks correct on the clicker's own screen.
MP = true
-- THE TURN ROUND'S OWN PASS, not a loop written here. Until 2026-09-29 this harness wrapped
-- EX.post_deals per human itself while EX.turn_round called it once, unbound - so this section
-- proved a page-building shape the game never ran.
EX.post_all_deals()
local before = {}
for _, f in ipairs(EX.humans()) do before[f] = GOLD[f] or 0 end
EX.mp_apply(EX.faction_by_cqi(13), "deal", "1")
local moved = {}
for _, f in ipairs(EX.humans()) do
    if (GOLD[f] or 0) ~= before[f] then moved[#moved + 1] = f end
end
print("deal_moved " .. table.concat(moved, ","))
print("deal_subject_after " .. tostring(EX.who()))
MP = false

-- ------------------------------------------------------------------------------------------
-- 8b. EVERY HUMAN'S PAGE, AND EVERY HUMAN'S OWN REASON FOR AN EMPTY ONE.
--
-- EX.deal_why is the sentence an empty page shows - "none" (nobody could even issue a deal)
-- or "declined" (somebody could and scored it no). It is per PLAYER, like the page it
-- explains. zeta_player is LAST in the sorted walk and is NOT the local player, which is what
-- makes this discriminating: the engine cannot issue a deal to zeta at all, so zeta's reason
-- is "none"; everyone else is offered deals, and EX.post_deals marks "declined" on any
-- can_issue. A reason held in one shared global ends the pass as zeta's "none", and the
-- local player's panel would then explain a page they never had.
-- ------------------------------------------------------------------------------------------
cm.cai_evaluate_quick_deal_action = function(_, mine, them)
    if mine.name() == "zeta_player" then return 0, false end
    return 42, true
end
build_world({ "house_a", "house_b", "house_c",
              "zeta_player", "alpha_player", "mid_player", "omega_player" })
EX.post_all_deals()
local pages = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        pages[#pages + 1] = f .. "=" .. #EX.deals .. "/" .. tostring(EX.deal_why)
    end)
end
print("deal_all_pages " .. table.concat(pages, " "))
print("deal_why_local " .. tostring(EX.deal_why))
print("deal_all_subject_after " .. tostring(EX.who()))

-- ------------------------------------------------------------------------------------------
-- 8c. FORWARD CONTRACTS (2026-09-29): each human's own offers, taken as the SENDER by index,
-- delivered per human on the delivery turn.
--
-- One deal slot, so the three houses spill onto the contract list at all. house_b refuses
-- mid_player again, so mid's lists are the discriminating ones: the offers are built for the
-- BOUND player, and a pass built for the local one would give mid house_b.
-- ------------------------------------------------------------------------------------------
cm.cai_evaluate_quick_deal_action = function(_, mine, them)
    if them.name() == "house_b" and mine.name() == "mid_player" then return 0, false end
    return 42, true
end
EX.snap = { ai_deals = true, ai_forwards = true, deal_max = 1 }
build_world({ "house_a", "house_b", "house_c",
              "zeta_player", "alpha_player", "mid_player", "omega_player" })
EX.post_all_deals()
local fp = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        local r = {}
        for i = 1, #EX.fwd_offers do r[#r + 1] = EX.fwd_offers[i].fac end
        for i = 1, #EX.deals do r[#r + 1] = "d:" .. EX.deals[i].fac end
        fp[#fp + 1] = f .. "=" .. table.concat(r, ",")
    end)
end
print("fwd_pages " .. table.concat(fp, " "))

-- TAKEN AS THE SENDER. mid_player clicks on their machine; this one plays alpha_player.
MP = true
EX.mp_apply(EX.faction_by_cqi(13), "fwd", "1")
MP = false
local held, at = {}, nil
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        held[#held + 1] = f .. "=" .. #EX.forwards
        if f == "mid_player" and EX.forwards[1] then at = EX.forwards[1].at end
    end)
end
print("fwd_taken " .. table.concat(held, " "))
print("fwd_subject_after " .. tostring(EX.who()))

-- DELIVERED PER HUMAN on the delivery turn: only mid_player's treasury moves among the humans,
-- and only mid_player's list empties. None of the humans holds any goods here, so every lot
-- settles in gold - which is exactly what makes the moved-gold list readable.
local gbefore = {}
for _, f in ipairs(EX.humans()) do gbefore[f] = GOLD[f] or 0 end
TURN = at or TURN
-- THE MARKET MOVES BEFORE DELIVERY (2026-09-30). A buying faction's contract is held to the
-- Trade view's buy price, which on this calm board IS the market, so an unmoved market settled
-- every short lot at a difference of 0 and no treasury moved to be read. Put back after.
local keep_rungs = {}
for _, res in ipairs(EX.COMMODITIES) do
    keep_rungs[res] = EX.current[res]
    EX.current[res] = (EX.current[res] or EX.neutral_rung()) + 3
end
EX.deliver_all_forwards()
for _, res in ipairs(EX.COMMODITIES) do EX.current[res] = keep_rungs[res] end
local gmoved, left = {}, {}
for _, f in ipairs(EX.humans()) do
    if (GOLD[f] or 0) ~= gbefore[f] then gmoved[#gmoved + 1] = f end
    EX.with_player(f, function() left[#left + 1] = f .. "=" .. #EX.forwards end)
end
print("fwd_delivered_moved " .. table.concat(gmoved, ","))
print("fwd_left " .. table.concat(left, " "))
print("fwd_deliver_subject_after " .. tostring(EX.who()))

-- ------------------------------------------------------------------------------------------
-- 8d. THE INDEX FUND (2026-09-29): one index per culture with a human, world state; units per
-- player, bought as the SENDER; members' dividends paid to each holder bound; a death logged to
-- that culture's humans only.
--
-- house_a and house_b are Chaos Dwarf, house_c is the Empire's only house. So alpha_player has
-- an index and mid_player has none - and the machine here plays alpha, so an index read off
-- the LOCAL culture would hand mid the Chaos Dwarf one and let the buy through.
-- ------------------------------------------------------------------------------------------
EX.houses = { "house_a", "house_b", "house_c" }
EX.house_set = nil
EX.delisted = {}
EX.snap = nil
-- GOLD FIRST. Earlier sections leave treasuries wherever their settlements put them, and a
-- human who cannot afford a lot is refused for the wrong reason - which is what let an index
-- read off the local culture pass this section once.
for _, f in ipairs(EX.humans()) do GOLD[f] = 100000 end
EX.index_sync(true)
local st = {}
for _, c in ipairs(EX.index_cultures()) do
    local s = EX.index_state(c)
    st[#st + 1] = c .. "=" .. (s and table.concat(s.m, ",") or "none")
end
print("idx_mp_states " .. table.concat(st, " "))

MP = true
EX.mp_apply(EX.faction_by_cqi(12), "idx", "b1")      -- alpha, Chaos Dwarf: buys
EX.mp_apply(EX.faction_by_cqi(13), "idx", "b1")      -- mid, Empire: no index to buy
MP = false
local units = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function() units[#units + 1] = f .. "=" .. EX.index_units end)
end
print("idx_mp_units " .. table.concat(units, " "))
print("idx_mp_subject_after " .. tostring(EX.who()))

-- THE DIVIDEND, bound per human the way the round's player block binds it.
local gb = {}
for _, f in ipairs(EX.humans()) do gb[f] = GOLD[f] or 0 end
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function() EX.pay_index_dividends() end)
end
local moved = {}
for _, f in ipairs(EX.humans()) do
    if (GOLD[f] or 0) > gb[f] then moved[#moved + 1] = f end
end
print("idx_mp_div_moved " .. table.concat(moved, ","))

-- THEMED FUNDS BY ID (2026-09-30): the fund rides on the idx op after an "@", resolved against
-- the SENDER's culture - a Chaos Dwarf fund id from the Empire player is refused, not traded.
EX.snap = nil
EX.index_sync(true)
MP = true
EX.mp_apply(EX.faction_by_cqi(12), "idx", "b1@chd_furnace")   -- alpha, Chaos Dwarf: buys
EX.mp_apply(EX.faction_by_cqi(13), "idx", "b1@chd_furnace")   -- mid, Empire: not theirs
EX.mp_apply(EX.faction_by_cqi(13), "idx", "b1@emp_staples")   -- mid: buys their own
MP = false
local fu = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        local t = {}
        for id, n in pairs(EX.fund_units) do
            if n > 0 then t[#t + 1] = id .. ":" .. n end
        end
        table.sort(t)
        fu[#fu + 1] = f .. "=" .. table.concat(t, ",")
    end)
end
print("fund_mp_units " .. table.concat(fu, " "))
print("fund_mp_subject_after " .. tostring(EX.who()))
local fk = {}
for k in pairs(EX.store) do
    if string.sub(k, 1, #EX.SAVE_FUND) == EX.SAVE_FUND then fk[#fk + 1] = string.sub(k, #EX.SAVE_FUND + 1) end
end
table.sort(fk)
print("fund_mp_states " .. table.concat(fk, ","))

-- A DEATH, LOGGED TO THE CULTURE THAT HOLDS THE INDEX. The pass itself runs unbound, and the
-- index that loses a member here is the EMPIRE's - a second Empire house gives mid_player one -
-- so a log written unbound lands in alpha_player's, the local slice, and not in mid's.
WORLD[#WORLD + 1] = "house_d"
CULTURE.house_d = "wh_main_emp_empire"
EX.houses = { "house_a", "house_b", "house_c", "house_d" }
EX.house_set = nil
EX.index_sync(true)
EX.delisted.house_c = true
EX.index_sync(false)
local told = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        for _, e in ipairs(EX.LOG) do
            if e[4] == "house_c" and e[2] == "" then told[#told + 1] = f; break end
        end
    end)
end
print("idx_mp_death_told " .. table.concat(told, ","))
print("idx_mp_death_subject_after " .. tostring(EX.who()))
EX.delisted = {}

-- ------------------------------------------------------------------------------------------
-- 8e. WAR BONDS AND LOANS (2026-09-29): each human's own offers, from houses of their own
-- culture; taken as the SENDER by index; paid per human, bound.
--
-- house_a is at war with somebody, so it issues a bond; house_b is at peace, so it lends. Both
-- are Chaos Dwarf, so they are alpha's. house_c and house_d are the Empire's and at peace, so
-- mid gets two loan offers, richest first. An offer list built for the LOCAL player (alpha)
-- would hand mid alpha's.
-- ------------------------------------------------------------------------------------------
EX.houses = { "house_a", "house_b", "house_c", "house_d" }
EX.house_set = nil
EX.delisted = {}
EX.snap = { ai_bonds = true, ai_gold = true, bond_max = 2 }
AT_WAR.house_a = true
for _, f in ipairs(EX.humans()) do GOLD[f] = 100000 end
GOLD.house_a, GOLD.house_b, GOLD.house_c, GOLD.house_d = 50000, 50000, 60000, 80000
EX.post_all_bonds()
local bo = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        local r = {}
        for _, o in ipairs(EX.bond_offers) do r[#r + 1] = o.side .. ":" .. o.fac end
        bo[#bo + 1] = f .. "=" .. table.concat(r, ",")
    end)
end
print("bd_mp_offers " .. table.concat(bo, " "))
print("bd_mp_post_subject_after " .. tostring(EX.who()))

-- TAKEN AS THE SENDER. alpha lends to house_a; mid borrows from house_d - offer 1 on each
-- player's own list. Every gold one side gains is what the other lost.
local g0 = {}
for k, v in pairs(GOLD) do g0[k] = v end
MP = true
EX.mp_apply(EX.faction_by_cqi(12), "bond", "1")
EX.mp_apply(EX.faction_by_cqi(13), "bond", "1")
MP = false
local held = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        local r = {}
        for _, x in ipairs(EX.bonds) do r[#r + 1] = x.side .. ":" .. x.fac end
        held[#held + 1] = f .. "=" .. table.concat(r, ",") .. "/" .. #EX.bond_offers
    end)
end
print("bd_mp_taken " .. table.concat(held, " "))
print("bd_mp_take_moved alpha=" .. (GOLD.alpha_player - g0.alpha_player)
    .. "|" .. (GOLD.house_a - g0.house_a) .. " mid=" .. (GOLD.mid_player - g0.mid_player)
    .. "|" .. (GOLD.house_d - g0.house_d))
print("bd_mp_take_subject_after " .. tostring(EX.who()))

-- PAID PER HUMAN, the round's own player block: next turn alpha is paid by house_a and mid pays
-- house_d; nobody else's treasury moves.
TURN = TURN + 1
local g1 = {}
for k, v in pairs(GOLD) do g1[k] = v end
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function() EX.pay_bonds() end)
end
local pm = {}
for _, f in ipairs(EX.humans()) do
    if GOLD[f] ~= g1[f] then pm[#pm + 1] = f end
end
print("bd_mp_paid_moved " .. table.concat(pm, ","))
print("bd_mp_paid_sum " .. tostring((GOLD.alpha_player - g1.alpha_player)
    + (GOLD.house_a - g1.house_a) == 0 and (GOLD.mid_player - g1.mid_player)
    + (GOLD.house_d - g1.house_d) == 0 and GOLD.alpha_player > g1.alpha_player
    and GOLD.mid_player < g1.mid_player))
print("bd_mp_pay_subject_after " .. tostring(EX.who()))
TURN = TURN - 1
AT_WAR.house_a = nil
EX.snap = nil

-- ------------------------------------------------------------------------------------------
-- 8f. ONE MARKET ON EVERY MACHINE (logic sweep, 2026-09-29). The world steps and every reprice
-- read the shared market's knobs UNBOUND, which on each machine means that machine's own
-- player - so a knob that follows the local race prices the same book differently on a Chaos
-- Dwarf machine and a Skaven one, and the shared prices never agree again. Two machines are
-- played here by swapping the local race row. The index's wind-up is the same trap: the index
-- belongs to a culture, and its level must be that culture's on every machine.
-- ------------------------------------------------------------------------------------------
local WORLD_KEYS = { "pressure_per_rung", "book_per_rung", "shock_gain", "shock_max" }
local function world_read()
    local r = {}
    for _, k in ipairs(WORLD_KEYS) do r[#r + 1] = string.format("%%.3f", EX.opt(k)) end
    return table.concat(r, ",")
end
local real_race = EX.race
EX.snap = nil
EX.houses = { "house_a", "house_b", "house_c", "house_d" }
EX.house_set = nil
EX.delisted = { house_c = true }
local px_c = EX.price("house_c")
local emp_w
EX.with_player(EX.faction_by_cqi(13), function() emp_w = EX.opt("windup") end)
local chd_w = EX.opt("windup")
MP = true
EX.race = EX.RACES["wh3_dlc23_chd_chaos_dwarfs"]
local w_chd, i_chd = world_read(), EX.index_weight("house_c")
EX.race = EX.RACES["wh2_main_skv_skaven"]
local w_skv, i_skv = world_read(), EX.index_weight("house_c")
MP = false
local w_sp = world_read()
EX.race = real_race
EX.delisted = {}
print("mp_world_same " .. tostring(w_chd == w_skv))
print("mp_world_sp_moved " .. tostring(w_sp ~= w_chd))
print("mp_index_windup_same " .. tostring(i_chd == i_skv))
print("mp_index_windup_empire " .. tostring(math.abs(i_chd - emp_w * px_c) < 1e-6))
print("mp_index_windup_differs " .. tostring(emp_w ~= chd_w))
-- AND THE REMOVAL PASS re-cuts the Empire index's divisor at the Empire's wind-up on every
-- machine: house_c dies out of an index of house_c and house_d, once per local race.
local EMP = "wh_main_emp_empire"
local function removal_d(race_row)
    EX.setv(EX.SAVE_INDEX .. EMP, nil)
    EX.delisted = {}
    EX.index_sync(true)
    EX.delisted = { house_c = true }
    EX.race = race_row
    MP = true
    EX.index_remove(EMP)
    MP = false
    EX.race = real_race
    local s = EX.index_state(EMP)
    return s and string.format("%%.6f", s.d) or "none"
end
local rd1 = removal_d(EX.RACES["wh3_dlc23_chd_chaos_dwarfs"])
local rd2 = removal_d(EX.RACES["wh2_main_skv_skaven"])
EX.delisted = {}
EX.setv(EX.SAVE_INDEX .. EMP, nil)
print("mp_index_removal_same " .. tostring(rd1 == rd2 and rd1 ~= "none"))
-- AND A PLAYER'S OWN KNOBS STILL FOLLOW THAT PLAYER in multiplayer: the fix is for the shared
-- market only. The Empire player's markup ceiling is the Empire's, the Skaven player's Skaven.
MP = true
local own = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        own[#own + 1] = f .. "=" .. string.format("%%.3f", EX.opt("hostile_max"))
    end)
end
MP = false
print("mp_own_knobs " .. table.concat(own, " "))
