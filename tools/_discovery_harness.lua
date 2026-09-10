local SAVED = {}
local FACTIONS, ORDER = {}, {}
local function mkfac(name, regions, forces, dead)
    local f = {
        is_null_interface = function() return false end,
        name = function() return name end,
        culture = function() return "wh3_dlc23_chd_chaos_dwarfs" end,
        is_dead = function() return dead == true end,
        is_rebel = function() return false end,
        is_quest_battle_faction = function() return false end,
        has_home_region = function() return regions > 0 end,
        region_list = function() return { num_items = function() return regions end } end,
        military_force_list = function() return { num_items = function() return forces end } end,
        treasury = function() return 100000 end,
    }
    FACTIONS[name] = f
    ORDER[#ORDER + 1] = name
    return f
end
mkfac("player",   5, 6, false)
mkfac("settled",  4, 5, false)
-- THE HORDE. cr_chd_black_kraken_armada owns zero regions for its entire life and must still
-- be a house: this is why the presence test is OR and not AND.
mkfac("horde",    0, 3, false)
-- THE PHANTOM, and this is the exact shape measured in game 2026-09-07. Owns nothing anywhere
-- and STILL answers is_dead() == false during the first-tick walk. is_dead alone lets it in.
mkfac("phantom",  0, 0, false)
-- The ordinary dead faction, which is_dead already caught.
mkfac("deadfac",  0, 0, true)

cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function(_, k, v) SAVED[k] = v end,
    get_saved_value = function(_, k) return SAVED[k] end,
    get_local_faction_name = function() return "player" end,
    get_faction = function(_, n) return FACTIONS[n] or false end,
    model = function()
        return { world = function()
            return { faction_list = function()
                return { num_items = function() return #ORDER end,
                         item_at = function(_, i) return FACTIONS[ORDER[i + 1]] end }
            end }
        end }
    end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])
EX.store = SAVED

local function listed()
    local t = {}
    for _, k in ipairs(EX.houses) do t[#t + 1] = k end
    table.sort(t)
    return table.concat(t, ",")
end

EX.discover_houses()
print("fresh " .. listed())

-- THE UNION, AND WHAT IT IS ALLOWED TO CARRY. Put the phantom back in the saved list holding
-- nothing, and a real house holding 20. Only the held one may survive - otherwise one bad tick
-- of is_dead() is a permanent row.
EX.setv(EX.SAVE_HOUSES, "settled;phantom;ghost_we_hold")
EX.setv(EX.SAVE_SHARES .. "phantom", 0)
EX.setv(EX.SAVE_SHARES .. "ghost_we_hold", 20)
EX.discover_houses()
print("merged " .. listed())

-- =========================================================================================
-- PRUNING, AND THE NAME A NAMELESS FACTION GETS
--
-- Measured live 2026-09-07: four dead factions sat on the Houses view as permanent Delisted
-- rows - admitted during the one-tick window EX.tradeable_faction documents, and then never
-- removed, because nothing in the mod could remove a house. Two drew CA's placeholder loc and
-- two drew the raw key.
-- =========================================================================================
EX.houses = { "alive_one", "dead_unheld", "dead_held", "alive_two" }
EX.house_set = nil
EX.delisted = { dead_unheld = true, dead_held = true }
EX.shares_held = { dead_held = 4 }
EX.store = EX.store or {}
EX.prune_houses()
print("after_prune " .. table.concat(EX.houses, ","))
print("pruned_saved " .. tostring(EX.getv(EX.SAVE_HOUSES)))

-- A SECOND PASS IS A NO-OP. check_delistings calls this every turn and on every load.
local before = table.concat(EX.houses, ",")
EX.prune_houses()
print("prune_idempotent " .. tostring(table.concat(EX.houses, ",") == before))

-- CLOSING THE POSITION LETS THE ROW GO on the next pass, which is what makes keeping a held
-- delisted row safe rather than permanent.
EX.shares_held["dead_held"] = 0
EX.prune_houses()
print("after_close " .. table.concat(EX.houses, ","))

-- THE NAME. common is stubbed per case, so what is measured is which branch is taken.
EX.fac_names = {}
common = { get_localised_string = function() return "The Warhost of Zharr" end }
print("name_real " .. EX.faction_display("wh3_dlc23_chd_zhatan"))
EX.fac_names = {}
common = { get_localised_string = function() return "[YOU SHOULDN'T SEE THIS]" end }
print("name_placeholder " .. EX.faction_display("mixer_chd_lost_slavers"))
EX.fac_names = {}
common = { get_localised_string = function() return "" end }
print("name_empty " .. EX.faction_display("mixer_chd_black_kraken"))
EX.fac_names = {}
print("name_cr " .. EX.faction_display("cr_chd_skullstack"))
EX.fac_names = {}
common = nil
print("name_no_common " .. EX.faction_display("mixer_chd_gargath"))

-- =========================================================================================
-- THE DEFERRED SUBJECT. EX.log_settlement leaves the name empty and the KEY is what the row
-- resolves it from at draw time - because resolving it at settle time reaches
-- common.get_localised_string inside a FactionTurnStart handler, and that took the process
-- down at turn 1 of a fresh campaign on 2026-09-07, twice.
-- =========================================================================================
EX.LOG = {}
EX.store = EX.store or {}
common = nil                     -- exactly what settle time must survive
EX.log_settlement("cr_chd_skullstack", 0, 0)
print("settle_logged " .. #EX.LOG)
print("settle_subject_empty " .. tostring(EX.LOG[1] and EX.LOG[1][2] == ""))
print("settle_key " .. tostring(EX.LOG[1] and EX.LOG[1][4]))
print("settle_detail " .. tostring(EX.LOG[1] and EX.LOG[1][3]))

EX.log_settlement("cr_chd_skullstack", 1250, 5)
print("settle_paid_detail " .. tostring(EX.LOG[1] and EX.LOG[1][3]))

-- AT DRAW TIME the name appears, resolved from the key.
EX.fac_names = {}
common = { get_localised_string = function() return "" end }
local drawn = EX.log_lines()
print("drawn_subject " .. drawn[#drawn][1])
