-- WHAT EX.bind_race RESOLVES for a given local-faction culture, and what it leaves alone.
--
-- NOT A LIVE PANEL. EX.layout and EX.refresh_panel reach one; neither is called here. EX.init
-- is not called either - it walks the region manager. bind_race is called DIRECTLY, which is
-- the whole point: it must be safe with nothing else initialised, because at init it runs
-- before EX.rescan and before EX.restore.
local CULTURE = "wh3_dlc23_chd_chaos_dwarfs"
local SAVED = {}
local WORLD = {}

local function worldfac(name)
    WORLD[#WORLD + 1] = {
        is_null_interface = function() return false end,
        name = function() return name end,
        culture = function() return CULTURE end,
        is_dead = function() return false end,
        is_rebel = function() return false end,
        is_quest_battle_faction = function() return false end,
        region_list = function() return { num_items = function() return 3 end } end,
        military_force_list = function() return { num_items = function() return 2 end } end,
    }
end
worldfac("player") worldfac("rival_a") worldfac("rival_b")

cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function(_, k, v) SAVED[k] = v end,
    get_saved_value = function(_, k) return SAVED[k] end,
    get_local_faction_name = function() return "player" end,
    get_faction = function(_, n)
        if n ~= "player" then return false end
        return { is_null_interface = function() return false end,
                 name = function() return "player" end,
                 culture = function() return CULTURE end }
    end,
    model = function()
        return { world = function()
            return { faction_list = function()
                return { num_items = function() return #WORLD end,
                         item_at = function(_, i) return WORLD[i + 1] end }
            end }
        end }
    end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])
EX.store = SAVED

-- THE SHIPPED DEFAULTS, read BEFORE any bind. These are what twenty other checks in
-- gen_zharr_exchange.py measure against, because none of them calls bind_race.
print("default_culture " .. tostring(EX.HOUSE_CULTURE))
print("default_layer2 " .. table.concat(EX.LAYER2, ","))
print("default_seg " .. string.format("%%q", EX.seg()))

local order = {}
for k in pairs(EX.RACES) do order[#order + 1] = k end
table.sort(order)
print("races " .. table.concat(order, ","))

local function bind(culture)
    CULTURE = culture
    EX.bind_race()
end

for _, culture in ipairs(order) do
    bind(culture)
    local r = EX.RACES[culture]
    print("bound " .. culture
        .. ";seg=" .. EX.seg()
        .. ";house_culture=" .. tostring(EX.HOUSE_CULTURE)
        .. ";layer2=" .. table.concat(EX.LAYER2, "|")
        .. ";covered=" .. tostring(EX.covered())
        .. ";patron=" .. EX.patron()
        .. ";wrath=" .. tostring(EX.wrath_bundle())
        .. ";pleased=" .. tostring(EX.pleased_bundle())
        .. ";offering=" .. EX.offering_key("res_gems")
        -- THE EVENT-FEED RECORD, which is per race because the bulletin's PICTURE is a DB
        -- column and nothing can swap it at runtime. A race reading another's index is shown
        -- another culture's art - the Chaos Dwarf forge on a Skaven bulletin, 2026-09-08.
        .. ";feed_call=" .. EX.feed("call")
        .. ";feed_shock=" .. EX.feed("shock")
        .. ";feed_delist=" .. EX.feed("delist"))
end

-- AN UNCOVERED CULTURE. Bretonnia is in EX.CULTURE_WANTS and is not a covered race, which is
-- the majority case for this mod's players - 23 of the game's 27 cultures.
bind("wh_main_brt_bretonnia")
-- AN UNCOVERED RACE FALLS BACK TO THE CHAOS DWARF BLOCK, deliberately: EX.announce_shocks is
-- not gated, so a nil index would draw NOTHING, and a bulletin with the wrong picture beats a
-- bulletin that silently never appears.
print("uncovered_feed " .. EX.feed("shock"))
print("uncovered seg=" .. EX.seg()
    .. ";house_culture=" .. tostring(EX.HOUSE_CULTURE)
    .. ";layer2=" .. tostring(#EX.LAYER2)
    .. ";covered=" .. tostring(EX.covered())
    .. ";patron=" .. EX.patron())

-- A CULTURE THAT DOES NOT EXIST, which is what a modded race looks like from here.
bind("some_mod_culture")
print("modded house_culture=" .. tostring(EX.HOUSE_CULTURE)
    .. ";covered=" .. tostring(EX.covered()))

-- THE GATE. Which tabs a race may reach - and it is now TWO questions, not one.
--
-- Offerings needs a covered race, because every string in it names a patron. Houses needs
-- HOUSES, which is independent of coverage: EX.HOUSE_CULTURE follows the player whatever their
-- culture, so an uncovered race discovers, prices, trades and settles its own people's
-- factions exactly as a covered one does. Both used to test EX.covered(), and a live Southern
-- Realms campaign showed what that cost - seven houses discovered and settling correctly
-- behind a greyed tab (2026-09-08).
--
-- So both axes are crossed here. Testing only the covered/uncovered one would pass on a build
-- that had quietly gone back to a single gate.
local function gate(culture, houses)
    bind(culture)
    EX.houses = houses and { "h1", "h2" } or {}
    local locks = {}
    for _, m in ipairs(EX.MODES) do
        local why = EX.tab_locked(m)
        locks[#locks + 1] = m .. "=" .. (why and "LOCKED" or "open")
    end
    return table.concat(locks, ",")
end
print("gate_chd " .. gate("wh3_dlc23_chd_chaos_dwarfs", true))
print("gate_emp " .. gate("wh_main_emp_empire", true))
print("gate_teb " .. gate("mixer_teb_southern_realms", true))
print("gate_unc " .. gate("wh_main_brt_bretonnia", true))
print("gate_chd_nohouses " .. gate("wh3_dlc23_chd_chaos_dwarfs", false))
print("gate_unc_nohouses " .. gate("wh_main_brt_bretonnia", false))

-- EVERY LOCKED TAB SAYS WHY. A greyed control with no tooltip is a bug report. Both locks have
-- to be live for this to mean anything, so: uncovered AND no houses.
bind("wh_main_brt_bretonnia")
EX.houses = {}
local blank = 0
for _, m in ipairs(EX.MODES) do
    local why = EX.tab_locked(m)
    if why ~= nil and (type(why) ~= "string" or why == "") then blank = blank + 1 end
end
print("locked_reasons_blank " .. blank)

-- A LOCKED VIEW CANNOT BE OPENED. EX.set_mode is reachable from the tab click listener, and
-- a disabled component still delivers a click in some engine states.
EX.layout = function() end
EX.refresh_panel = function() end
EX.mode = EX.MODE_TRADE
EX.set_mode(EX.MODE_OFFER)
print("locked_set_mode " .. tostring(EX.mode))
bind("wh_main_emp_empire")
EX.set_mode(EX.MODE_OFFER)
print("covered_set_mode " .. tostring(EX.mode))
EX.mode = EX.MODE_TRADE

-- THE PATRON'S NAME ON SCREEN. EX.HEADERS, EX.TIPS and EX.HELP_PAGES are FILE-SCOPE table
-- literals: they are built before any faction exists, so they cannot read EX.race at
-- construction and bind_race rewrites the race-dependent entries after the bind. Which is why
-- these are measured by RUNNING the bind rather than by reading the file.
local function words(culture)
    bind(culture)
    return EX.HEADERS.offer.hdr_trend
        .. "|" .. EX.TIPS.offer.hdr_trend
        .. "|" .. EX.TIPS.houses.hdr_name
        .. "|" .. EX.HELP_PAGES[1][EX.HELP_OFFER_LINE][2]
        .. "|" .. EX.HELP_PAGES[2][EX.HELP_GUILD_LINE][2]
end
print("words_chd " .. words("wh3_dlc23_chd_chaos_dwarfs"))
print("words_skv " .. words("wh2_main_skv_skaven"))
print("words_unc " .. words("wh_main_brt_bretonnia"))
print("help_offer_line " .. EX.HELP_OFFER_LINE .. "," .. EX.HELP_PAGES[1][EX.HELP_OFFER_LINE][1])
print("help_guild_line " .. EX.HELP_GUILD_LINE .. "," .. EX.HELP_PAGES[2][EX.HELP_GUILD_LINE][1])

-- THE BOON LABEL. Exotic Animals grants Chaos Dwarf post-battle Labour; the other three races
-- have no Labour pool, so the bundle applies, the effect moves nothing, and the panel would
-- advertise a number that never arrives.
for _, culture in ipairs(order) do
    bind(culture)
    print("boon_" .. culture .. " " .. tostring(EX.boon("res_animals"))
        .. "|" .. tostring(EX.boon("res_rom_iron")))
end

-- THE TITHE. EX.maybe_demand must return before it rolls anything for an uncovered player - a
-- demand whose message key has no loc row draws an EMPTY event-feed entry.
local fired
EX.fire_demand = function() fired = true end
EX.setting = function() return true end
EX.opt = function(k)
    if k == "demand_first_turn" then return 1 end
    if k == "demand_cooldown" then return 0 end
    return 100
end
cm.turn_number = function() return 40 end
cm.random_number = function() return 1 end
EX.demand_turn = 0
for _, culture in ipairs({ "wh3_dlc23_chd_chaos_dwarfs", "wh_main_emp_empire",
                           "wh_main_brt_bretonnia" }) do
    bind(culture)
    fired = false
    EX.maybe_demand()
    print("demand_" .. culture .. " " .. tostring(fired))
end

-- HOUSE DISCOVERY IS DELIBERATELY NOT GATED. It feeds the guild, whose books are the fifth
-- term in EX.target_rung - so an uncovered player's market still moves rather than being
-- priced by supply, appetite and shocks alone. Gating it would be MORE code and a worse game.
bind("wh_main_brt_bretonnia")
EX.houses = {}
EX.house_set = nil
EX.discover_houses()
print("uncovered_discovers " .. #EX.houses)

-- REBINDING IS IDEMPOTENT. init has two entry points and a third is a patch away; the Layer 2
-- list must be ASSIGNED, never appended to.
bind("wh3_dlc23_chd_chaos_dwarfs")
local first = table.concat(EX.LAYER2, "|")
EX.bind_race()
EX.bind_race()
print("idempotent " .. tostring(first == table.concat(EX.LAYER2, "|")) .. "," .. #EX.LAYER2)

-- THE NULL FACTION. cm:get_faction returns FALSE, not nil, for a name it does not know, and a
-- script-root call can hand back a null interface. Neither may throw, and both must leave the
-- segment empty - "" is the only value with DB rows behind it.
cm.get_faction = function() return false end
EX.bind_race()
print("nofaction covered=" .. tostring(EX.covered())
    .. ";seg=" .. string.format("%%q", EX.seg()))
cm.get_faction = function()
    return { is_null_interface = function() return true end }
end
EX.bind_race()
print("nullface covered=" .. tostring(EX.covered())
    .. ";seg=" .. string.format("%%q", EX.seg()))
