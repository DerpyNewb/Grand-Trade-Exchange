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
        at_war = function() return false end,
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
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function() EX.post_deals() end)
end
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
