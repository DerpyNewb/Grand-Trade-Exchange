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

local n = 0
for _, f in ipairs(EX.humans()) do
    n = n + 10
    EX.with_player(f, function()
        EX.set_shares("house_a", n)
        EX.offerings_made = n
        EX.demand_res = "res_" .. f
        EX.offer_until["res_gems"] = n
        EX.LOG[#EX.LOG + 1] = { 1, f, "line for " .. f, "" }
    end)
end

local got = {}
for _, f in ipairs(EX.humans()) do
    EX.with_player(f, function()
        got[#got + 1] = f .. "=" .. tostring(EX.held("house_a"))
            .. "/" .. tostring(EX.offerings_made)
            .. "/" .. tostring(EX.demand_res)
            .. "/" .. tostring(EX.offer_until["res_gems"])
            .. "/" .. tostring(#EX.LOG)
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
