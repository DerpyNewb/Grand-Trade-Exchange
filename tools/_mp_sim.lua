-- MULTIPLAYER LOCKSTEP SIMULATOR for the Great Guilds, the Iron Court and the Zharr
-- Exchange. Driven by tools/check_mp_sim.py, which extracts the SHIPPED scripts and
-- layouts out of each pack and writes the config this reads:
--   lua.exe tools\_mp_sim.lua <config.lua>
--
-- WHAT A MULTIPLAYER DESYNC IS, AND THEREFORE WHAT THIS MEASURES. Every machine in a
-- multiplayer campaign runs its own copy of the model, and the copies stay equal only
-- if every machine makes the same model calls in the same order. So each simulated
-- machine gets its own Lua environment, its own world and its own save, and every call
-- that changes the campaign - gold, pooled resources, effect bundles, saved values,
-- cm:random_number, anything cm does that is not a read - goes into that machine's
-- log. After every step the logs' new entries are compared, and a difference is a
-- desync, reported with the file and line that made the call.
--
-- WHAT MAKES THE MACHINES DIFFER, ON PURPOSE: a different local faction, a different
-- MCT on every machine (the host's is not the clients'), a different math.random
-- stream, os.time and os.clock, a different screen size, and the UI itself - a click
-- happens on one machine only, the panel is open on one machine only. A mod that keeps
-- the model equal under all of that has done what CA's "Multiplayer UI Events" asks.
--
-- THE CLICKS ARE THE REAL BUTTONS. Each panel is built from its shipped .twui.xml
-- hierarchy, and the monkey presses every component the mod has made visible, one at a
-- time, on one machine, through ComponentLClickUp - the same event the game raises.
-- CampaignUI.TriggerCampaignScriptEvent goes on a bus, and the bus delivers UITrigger to
-- every machine in one order, which is what CA promises.
--
-- WHAT IT CANNOT SEE: the engine's own lockstep (a stub cannot desync), anything the
-- stubbed world answers wrongly, and code the monkey never reaches. The report lists
-- the ops no click reached for that last reason.

local CFG = dofile(arg[1])
local SIM_SRC = debug.getinfo(1, "S").source
local S = {}            -- everything, so the main chunk stays far under 200 locals
local M = {}            -- the machines
local BUS = {}          -- UITrigger messages not yet delivered
local FINDINGS = {}
local NOTES = {}
local MAX_FINDINGS = CFG.max_findings or 20

-- ---------------------------------------------------------------- serialise ---
local COMP_MT = {}

function S.ser(v, depth)
    local t = type(v)
    if t == "string" then return string.format("%q", v) end
    if t == "number" then
        if v == math.floor(v) and math.abs(v) < 1e15 then return string.format("%d", v) end
        return string.format("%.6g", v)
    end
    if t == "function" then return "fn" end
    if t ~= "table" then return tostring(v) end
    if getmetatable(v) == COMP_MT then return "ui:" .. tostring(rawget(v, "id")) end
    local tag = rawget(v, "__simtag")
    if tag then return tag end
    depth = depth or 0
    if depth > 3 then return "{...}" end
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b)
        local ta, tb = type(a), type(b)
        if ta ~= tb then return ta < tb end
        if ta == "number" or ta == "string" then return a < b end
        return tostring(a) < tostring(b)
    end)
    local parts = {}
    for _, k in ipairs(keys) do
        local ks = type(k) == "string" and k or ("[" .. S.ser(k, depth + 1) .. "]")
        parts[#parts + 1] = ks .. "=" .. S.ser(v[k], depth + 1)
    end
    return "{" .. table.concat(parts, ",") .. "}"
end

function S.args(...)
    local n = select("#", ...)
    local parts = {}
    for i = 1, n do parts[i] = S.ser((select(i, ...))) end
    return table.concat(parts, ", ")
end

-- WHERE A CALL CAME FROM: the first few frames outside this file.
function S.origin()
    local out = {}
    for lvl = 3, 60 do
        local info = debug.getinfo(lvl, "Sl")
        if not info then break end
        if info.source ~= SIM_SRC and info.currentline and info.currentline > 0 then
            local src = string.match(info.short_src or "?", "[^/\\]+$") or info.short_src
            out[#out + 1] = src .. ":" .. info.currentline
            if #out >= 4 then break end
        end
    end
    return table.concat(out, " < ")
end

function S.record(m, what, ...)
    m.log[#m.log + 1] = {s = what .. "(" .. S.args(...) .. ")", at = S.origin()}
end

function S.err(m, where, e)
    local key = where .. ": " .. tostring(e)
    m.errors[key] = (m.errors[key] or 0) + 1
end

function S.note_unknown(m, what)
    m.unknown[what] = (m.unknown[what] or 0) + 1
end

-- ---------------------------------------------------------------- world -----
-- One spec, built separately into every machine. Three humans: two Chaos Dwarf
-- houses and a Dwarf hold, because two of the three mods run one race's court or
-- board per human and a two-human, one-race game would never send a mixed op.
S.FACTIONS = {
    {k = "wh3_dlc23_chd_conclave", cul = "wh3_dlc23_chd_chaos_dwarfs",
     sub = "wh3_dlc23_sc_chd_chaos_dwarfs", human = 1, cqi = 11,
     regions = {"wh3_main_combi_region_zharr_naggrund", "wh3_main_combi_region_the_falls_of_doom"}},
    {k = "wh3_dlc23_chd_astragoth", cul = "wh3_dlc23_chd_chaos_dwarfs",
     sub = "wh3_dlc23_sc_chd_chaos_dwarfs", human = 2, cqi = 12,
     regions = {"wh3_main_combi_region_uzkulak", "wh3_main_combi_region_black_fortress"}},
    {k = "wh_main_dwf_dwarfs", cul = "wh_main_dwf_dwarfs", sub = "wh_main_sc_dwf_dwarfs",
     human = 3, cqi = 13,
     regions = {"wh3_main_combi_region_karaz_a_karak", "wh3_main_combi_region_karak_azul"}},
    {k = "wh3_dlc23_chd_legion_of_azgorh", cul = "wh3_dlc23_chd_chaos_dwarfs",
     sub = "wh3_dlc23_sc_chd_chaos_dwarfs", cqi = 21,
     regions = {"wh3_main_combi_region_gash_kadrak"}},
    {k = "wh3_dlc23_chd_zhatan", cul = "wh3_dlc23_chd_chaos_dwarfs",
     sub = "wh3_dlc23_sc_chd_chaos_dwarfs", cqi = 22,
     regions = {"wh3_main_combi_region_the_tower_of_gorgoth"}},
    {k = "wh_main_emp_empire", cul = "wh_main_emp_empire", sub = "wh_main_sc_emp_empire",
     cqi = 23, regions = {"wh3_main_combi_region_altdorf"}},
    {k = "wh2_main_skv_clan_mors", cul = "wh2_main_skv_skaven", sub = "wh2_main_sc_skv_skaven",
     cqi = 24, regions = {"wh3_main_combi_region_karak_eight_peaks"}},
}
S.HUMANS = {}
for _, f in ipairs(S.FACTIONS) do
    if f.human then S.HUMANS[f.human] = f.k end
end
S.NMACH = #S.HUMANS

function S.iface(m, tag, methods)
    local o = {__simtag = tag}
    setmetatable(o, {__index = function(_, k)
        local f = methods[k]
        if f ~= nil then return f end
        return S.auto(m, tag, k)
    end})
    return o
end

function S.list(m, items)
    return S.iface(m, "list", {
        num_items = function() return #items end,
        item_at = function(_, i) return items[i + 1] or S.null(m) end,
        is_empty = function() return #items == 0 end,
        is_null_interface = function() return false end,
    })
end

function S.null(m)
    if not m.NULL then
        m.NULL = S.iface(m, "null", {is_null_interface = function() return true end})
    end
    return m.NULL
end

S.NUMERIC = {"^num_", "count$", "value$", "^turns", "strength", "_x$", "_y$", "^rank$",
             "loyalty", "^age$", "income", "upkeep", "cost", "amount", "level", "percent",
             "points$", "score", "size$", "health", "morale", "supply", "wealth", "gold",
             "experience", "distance", "rate$", "treasury", "^total", "_turns$", "duration"}

-- AN UNSTUBBED METHOD: answered by its name, and counted so the report can say which
-- answers were guesses.
function S.auto(m, tag, k)
    local kind = string.match(tag, "^[^:]+") or tag
    S.note_unknown(m, kind .. ":" .. k)
    if k == "is_null_interface" then return function() return false end end
    if string.match(k, "^is_") or string.match(k, "^has_") or string.match(k, "^can_")
       or string.match(k, "^are_") or string.match(k, "^at_war") or string.match(k, "^was_")
       or string.match(k, "^won") then
        return function() return false end
    end
    if string.match(k, "_list$") or string.match(k, "^factions_") then
        return function() return S.list(m, {}) end
    end
    for _, p in ipairs(S.NUMERIC) do
        if string.match(k, p) then return function() return 0 end end
    end
    if string.match(k, "key$") or string.match(k, "name$") or string.match(k, "path$") then
        return function() return "sim_" .. k end
    end
    return function() return S.null(m) end
end

-- Six characters a faction, four of them lords with armies, at ranks a court's offices
-- can and cannot take.
S.CHARS, S.LORDS = 6, 4
S.RANKS = {30, 22, 14, 8, 25, 3}

function S.build_world(m)
    local W = {turn = 1, gold = {}, bundles = {}, pooled = {}, fac = {}, reg = {}, chars = {},
               forces = {}, order = {}}
    m.W = W
    for _, spec in ipairs(S.FACTIONS) do
        W.gold[spec.k] = 50000
        W.bundles[spec.k] = {}
        W.pooled[spec.k] = {}
        W.order[#W.order + 1] = spec.k
    end
    for _, spec in ipairs(S.FACTIONS) do
        for i, r in ipairs(spec.regions) do W.reg[r] = {owner = spec.k, i = i} end
        for j = 1, S.CHARS do
            local cqi = spec.cqi * 100 + j
            W.chars[cqi] = {cqi = cqi, faction = spec.k, leader = (j == 1), traits = {},
                            general = (j <= S.LORDS), region = spec.regions[1], loyalty = 5,
                            rank = S.RANKS[j],
                            subtype = (j > S.LORDS) and "sim_hero" or "sim_lord"}
            if j <= S.LORDS then W.forces[cqi] = cqi end
        end
    end
end

function S.spec(k)
    for _, f in ipairs(S.FACTIONS) do if f.k == k then return f end end
end

function S.faction(m, k)
    local spec = S.spec(k)
    if not spec then return nil end
    m.fcache = m.fcache or {}
    if m.fcache[k] then return m.fcache[k] end
    local W = m.W
    local o
    o = S.iface(m, "faction:" .. k, {
        is_null_interface = function() return false end,
        name = function() return k end,
        culture = function() return spec.cul end,
        subculture = function() return spec.sub end,
        is_human = function() return spec.human ~= nil end,
        is_dead = function() return false end,
        command_queue_index = function() return spec.cqi end,
        treasury = function() return W.gold[k] end,
        has_effect_bundle = function(_, b) return W.bundles[k][b] ~= nil end,
        region_list = function()
            local rs = {}
            for _, r in ipairs(spec.regions) do rs[#rs + 1] = S.region(m, r) end
            return S.list(m, rs)
        end,
        num_regions = function() return #spec.regions end,
        character_list = function()
            local cs = {}
            for j = 1, S.CHARS do cs[#cs + 1] = S.char(m, spec.cqi * 100 + j) end
            return S.list(m, cs)
        end,
        military_force_list = function()
            local fs = {}
            for j = 1, S.LORDS do fs[#fs + 1] = S.force(m, spec.cqi * 100 + j) end
            return S.list(m, fs)
        end,
        faction_leader = function() return S.char(m, spec.cqi * 100 + 1) end,
        has_faction_leader = function() return true end,
        home_region = function() return S.region(m, spec.regions[1]) end,
        has_home_region = function() return true end,
        factions_met = function()
            local fs = {}
            for _, f in ipairs(S.FACTIONS) do
                if f.k ~= k then fs[#fs + 1] = S.faction(m, f.k) end
            end
            return S.list(m, fs)
        end,
        factions_at_war_with = function() return S.list(m, {}) end,
        at_war_with = function() return false end,
        pooled_resource_manager = function()
            return S.iface(m, "prm:" .. k, {
                resource = function(_, res)
                    return S.iface(m, "pooled:" .. k .. ":" .. tostring(res), {
                        is_null_interface = function() return false end,
                        key = function() return res end,
                        value = function() return W.pooled[k][res] or 0 end,
                        maximum_value = function() return 1000000 end,
                        minimum_value = function() return 0 end,
                    })
                end,
            })
        end,
    })
    m.fcache[k] = o
    return o
end

function S.region(m, r)
    local rec = m.W.reg[r]
    if not rec then return nil end
    local settlement = S.iface(m, "settlement:" .. r, {
        key = function() return "settlement:" .. r end,
        region = function() return S.region(m, r) end,
        faction = function() return S.faction(m, rec.owner) end,
        is_null_interface = function() return false end,
        logical_position_x = function() return 100 * rec.i end,
        logical_position_y = function() return 100 end,
        primary_slot = function() return S.region(m, r):settlement():slot_list():item_at(0) end,
        slot_list = function()
            local slot = S.iface(m, "slot:" .. r, {
                has_building = function() return true end,
                building = function()
                    return S.iface(m, "building:" .. r, {
                        name = function() return "wh3_dlc23_chd_settlement_major_2" end,
                        chain = function() return "wh3_dlc23_chd_settlement_major" end,
                        building_level = function() return 2 end,
                        region = function() return S.region(m, r) end,
                        faction = function() return S.faction(m, rec.owner) end,
                    })
                end,
                name = function() return "slot_1" end,
                type = function() return "primary" end,
                region = function() return S.region(m, r) end,
                faction = function() return S.faction(m, rec.owner) end,
            })
            return S.list(m, {slot})
        end,
    })
    return S.iface(m, "region:" .. r, {
        is_null_interface = function() return false end,
        province = function()
            return S.iface(m, "province:prov_" .. r, {key = function() return "prov_" .. r end,
                                                      name = function() return "prov_" .. r end})
        end,
        adjacent_region_list = function() return S.list(m, {}) end,
        name = function() return r end,
        key = function() return r end,
        owning_faction = function() return S.faction(m, rec.owner) end,
        is_abandoned = function() return false end,
        settlement = function() return settlement end,
        province_name = function() return "prov_" .. r end,
        public_order = function() return 0 end,
        cqi = function() return 500 + rec.i end,
        slot_list = function() return settlement:slot_list() end,
        garrison_residence = function()
            return S.iface(m, "garrison:" .. r, {
                region = function() return S.region(m, r) end,
                faction = function() return S.faction(m, rec.owner) end,
                settlement_interface = function() return settlement end,
            })
        end,
    })
end

function S.char(m, cqi)
    local c = m.W.chars[cqi]
    if not c then return nil end
    local details = S.iface(m, "details:" .. cqi, {
        is_null_interface = function() return false end,
        character = function() return S.char(m, cqi) end,
        has_trait = function(_, t) return c.traits[t] ~= nil end,
        trait_points = function(_, t) return c.traits[t] or 0 end,
        get_forename = function() return "names_name_" .. cqi end,
        get_surname = function() return "names_name_s" .. cqi end,
        faction = function() return S.faction(m, c.faction) end,
        command_queue_index = function() return cqi + 50000 end,
    })
    return S.iface(m, "character:" .. cqi, {
        is_null_interface = function() return false end,
        is_alive = function() return true end,
        has_trait = function(_, t) return c.traits[t] ~= nil end,
        trait_points = function(_, t) return c.traits[t] or 0 end,
        character_details = function() return details end,
        command_queue_index = function() return cqi end,
        cqi = function() return cqi end,
        faction = function() return S.faction(m, c.faction) end,
        character_subtype_key = function() return c.subtype end,
        character_subtype = function(_, s) return s == c.subtype end,
        character_type = function(_, t) return t == (c.general and "general" or "champion") end,
        character_type_key = function() return c.general and "general" or "champion" end,
        is_faction_leader = function() return c.leader end,
        has_military_force = function() return c.general end,
        military_force = function() return c.general and S.force(m, cqi) or S.null(m) end,
        family_member = function()
            return S.iface(m, "family:" .. cqi, {
                command_queue_index = function() return cqi + 50000 end,
                character = function() return S.char(m, cqi) end,
                is_null_interface = function() return false end,
            })
        end,
        get_forename = function() return "names_name_" .. cqi end,
        get_surname = function() return "names_name_s" .. cqi end,
        rank = function() return c.rank end,
        display_position_x = function() return 40 + cqi % 97 end,
        display_position_y = function() return 30 + cqi % 13 end,
        loyalty = function() return c.loyalty end,
        region = function() return S.region(m, c.region) end,
        has_region = function() return true end,
        logical_position_x = function() return cqi % 97 end,
        logical_position_y = function() return 7 end,
        is_wounded = function() return false end,
    })
end

function S.force(m, cqi)
    if not m.W.forces[cqi] then return nil end
    local c = m.W.chars[cqi]
    return S.iface(m, "force:" .. cqi, {
        is_null_interface = function() return false end,
        command_queue_index = function() return cqi + 90000 end,
        general_character = function() return S.char(m, cqi) end,
        has_general = function() return true end,
        faction = function() return S.faction(m, c.faction) end,
        is_armed_citizenry = function() return false end,
        unit_list = function()
            local us = {}
            for u = 1, 4 do
                us[#us + 1] = S.iface(m, "unit:" .. cqi .. ":" .. u, {
                    unit_key = function() return "sim_unit_" .. u end,
                    faction = function() return S.faction(m, c.faction) end,
                    percentage_proportion_of_full_strength = function() return 100 end,
                    force_commander = function() return S.char(m, cqi) end,
                })
            end
            return S.list(m, us)
        end,
        active_stance = function() return "MILITARY_FORCE_ACTIVE_STANCE_TYPE_DEFAULT" end,
    })
end

function S.model(m)
    if m.model then return m.model end
    local W = m.W
    local world = S.iface(m, "world", {
        faction_by_key = function(_, k) return S.faction(m, k) or S.null(m) end,
        faction_exists = function(_, k) return S.spec(k) ~= nil end,
        faction_list = function()
            local fs = {}
            for _, k in ipairs(W.order) do fs[#fs + 1] = S.faction(m, k) end
            return S.list(m, fs)
        end,
        region_manager = function()
            return S.iface(m, "region_manager", {
                region_by_key = function(_, r) return S.region(m, r) or S.null(m) end,
                region_list = function()
                    local rs = {}
                    for _, f in ipairs(S.FACTIONS) do
                        for _, r in ipairs(f.regions) do rs[#rs + 1] = S.region(m, r) end
                    end
                    return S.list(m, rs)
                end,
            })
        end,
        whose_turn_is_it = function()
            return S.list(m, {S.faction(m, m.turn_of or S.HUMANS[1])})
        end,
        -- SIMULTANEOUS TURNS: during the human phase every human's turn is now.
        is_factions_turn_by_key = function(_, k)
            if m.human_phase then return S.spec(k) ~= nil and S.spec(k).human ~= nil end
            return k == m.turn_of
        end,
    })
    m.model = S.iface(m, "model", {
        world = function() return world end,
        turn_number = function() return W.turn end,
        is_multiplayer = function() return true end,
        campaign_name = function(_, n) return n == "main_warhammer" end,
        campaign_name_key = function() return "main_warhammer" end,
        faction_for_command_queue_index = function(_, cqi)
            for _, f in ipairs(S.FACTIONS) do
                if f.cqi == cqi then return S.faction(m, f.k) end
            end
            return S.null(m)
        end,
        character_for_command_queue_index = function(_, cqi) return S.char(m, cqi) or S.null(m) end,
        military_force_for_command_queue_index = function(_, cqi)
            return S.force(m, (cqi or 0) - 90000) or S.null(m)
        end,
        random_percent = function(_, n) return S.rng(m, "model:random_percent", 100) <= (n or 0) end,
        pending_battle = function() return S.null(m) end,
    })
    return m.model
end

-- THE MODEL'S RANDOM STREAM: one seed for every machine, so equal call sequences give
-- equal answers, and every call is in the log, because in the game a roll one machine
-- makes and the others do not moves the shared stream out of step.
function S.rng(m, what, hi, lo)
    m.rng = (m.rng * 1103515245 + 12345) % 2147483648
    hi = tonumber(hi) or 100
    lo = tonumber(lo) or 1
    if hi < lo then hi, lo = lo, hi end
    local v = lo + (m.rng % (hi - lo + 1))
    S.record(m, what, hi, lo)
    return v
end

-- ---------------------------------------------------------------- the UI ----
local COMP = {}
COMP_MT.__index = function(c, k)
    local f = COMP[k]
    if f then return f end
    -- CA's methods are CamelCase; a lowercase miss is one of this file's own fields
    -- that is nil, such as the parent of a root.
    if not string.match(k, "^%u") then return nil end
    S.note_unknown(rawget(c, "m"), "uic:" .. k)
    return function() return nil end
end

function S.comp(m, id, parent, w, h)
    local c = setmetatable({id = id, kids = {}, visible = true, state = "standard",
                            text = "", tip = "", img = {}, interactive = true,
                            disabled = false, x = 0, y = 0, w = w or 100, h = h or 30,
                            props = {}, m = m}, COMP_MT)
    local same = m.ids[id]
    if not same then same = {} m.ids[id] = same end
    same[#same + 1] = c
    if parent then
        c.parent = parent
        parent.kids[#parent.kids + 1] = c
    end
    return c
end

function S.find_walk(c, name)
    for _, k in ipairs(c.kids) do
        if k.id == name then return k end
    end
    for _, k in ipairs(c.kids) do
        local f = S.find_walk(k, name)
        if f then return f end
    end
    return nil
end

-- AN ID INDEX, SO A FIND IS NOT A WALK. A panel refresh makes thousands of finds over
-- a 5,500-component tree, which walked was a fifth of a second a click. Every component
-- ever made is indexed by id; a find keeps the ones still under `c`, and only when
-- exactly one is left does it skip the walk - two or more and the walk decides, because
-- the engine's first-match order is the walk's and not the index's.
function S.find_desc(c, name)
    local all = c.m and c.m.ids[name]
    if not all then return nil end
    local found, n = nil, 0
    for _, k in ipairs(all) do
        local p = k.parent
        while p and p ~= c do p = p.parent end
        if p == c then
            found, n = k, n + 1
            if n > 1 then return S.find_walk(c, name) end
        end
    end
    return found
end

function S.detach(c)
    local p = c.parent
    if not p then return end
    for i = #p.kids, 1, -1 do
        if p.kids[i] == c then table.remove(p.kids, i) end
    end
    c.parent = nil
end

function S.build_layout(m, node, parent, rename)
    local c = S.comp(m, rename or node.id, parent, node.w, node.h)
    for _, ch in ipairs(node.c or {}) do S.build_layout(m, ch, c) end
    return c
end

function S.norm_path(p)
    p = string.lower(tostring(p or ""))
    p = string.gsub(p, "\\", "/")
    p = string.gsub(p, "^ui/", "")
    p = string.gsub(p, "%.twui%.xml$", "")
    return p
end

function S.copy(c, parent, rename)
    local n = S.comp(c.m, rename or c.id, parent, c.w, c.h)
    n.visible, n.state, n.text, n.tip = c.visible, c.state, c.text, c.tip
    for _, k in ipairs(c.kids) do S.copy(k, n) end
    return n
end

COMP.Id = function(c) return c.id end
COMP.Address = function(c) return c end
COMP.Parent = function(c) return c.parent end
COMP.Find = function(c, x)
    if type(x) == "number" then return c.kids[x + 1] end
    return S.find_desc(c, x)
end
COMP.ChildCount = function(c) return #c.kids end
COMP.CreateComponent = function(c, name, path)
    local layout = c.m.LAYOUTS[S.norm_path(path)]
    if not layout then
        S.note_unknown(c.m, "layout:" .. S.norm_path(path))
        return S.comp(c.m, name, c)
    end
    -- A layout's root is the file's container; the component the engine hands back is
    -- the one under it, renamed.
    if layout.id == "root" and layout.c and #layout.c == 1 then layout = layout.c[1] end
    return S.build_layout(c.m, layout, c, name)
end
COMP.CopyComponent = function(c, name) return S.copy(c, c.parent, name) end
COMP.Adopt = function(c, child)
    if type(child) ~= "table" then return end
    S.detach(child)
    child.parent = c
    c.kids[#c.kids + 1] = child
end
COMP.Divorce = function(c, child) if type(child) == "table" then S.detach(child) end end
COMP.Destroy = function(c) S.detach(c) end
COMP.DestroyChildren = function(c)
    for _, k in ipairs(c.kids) do k.parent = nil end
    c.kids = {}
end
COMP.SetVisible = function(c, b) c.visible = b and true or false end
COMP.Visible = function(c) return c.visible end
COMP.IsVisible = COMP.Visible
COMP.VisibleFromRoot = function(c)
    local p = c
    while p do
        if not p.visible then return false end
        p = p.parent
    end
    return c.m.root == S.root_of(c)
end
COMP.SetState = function(c, s) c.state = s end
COMP.CurrentState = function(c) return c.state end
COMP.SetStateText = function(c, t) c.text = tostring(t or "") end
COMP.SetText = COMP.SetStateText
COMP.GetStateText = function(c) return c.text end
COMP.SetTooltipText = function(c, t) c.tip = tostring(t or "") end
COMP.GetTooltipText = function(c) return c.tip end
COMP.SetImagePath = function(c, p, i) c.img[(i or 0) + 1] = p end
COMP.GetImagePath = function(c, i) return c.img[(i or 0) + 1] or "" end
COMP.SetInteractive = function(c, b) c.interactive = b and true or false end
COMP.IsInteractive = function(c) return c.interactive end
COMP.SetDisabled = function(c, b) c.disabled = b and true or false end
COMP.IsDisabled = function(c) return c.disabled end
COMP.MoveTo = function(c, x, y) c.x, c.y = x or 0, y or 0 end
COMP.Position = function(c) return c.x, c.y end
COMP.Resize = function(c, w, h) c.w, c.h = w or c.w, h or c.h end
COMP.Dimensions = function(c) return c.w, c.h end
COMP.Width = function(c) return c.w end
COMP.Height = function(c) return c.h end
COMP.Bounds = function(c) return c.w, c.h end
COMP.GetDockOffset = function() return 0, 0 end
COMP.SetProperty = function(c, k, v) c.props[k] = v end
COMP.GetProperty = function(c, k) return c.props[k] end
COMP.TextDimensionsForText = function(_, t) return 7 * #tostring(t or ""), 16 end
COMP.TextDimensions = function(c) return 7 * #c.text, 16 end
COMP.WidthOfTextLine = function(_, t) return 7 * #tostring(t or "") end
COMP.GetOpacity = function() return 255 end
COMP.Priority = function() return 100 end
COMP.NumStates = function() return 1 end
COMP.GetStateByIndex = function() return "standard" end
COMP.SimulateLClick = function(c)
    local m = c.m
    m.pending_clicks[#m.pending_clicks + 1] = c
end
for _, k in ipairs({"SetDockOffset", "SetDockingPoint", "SetCanResizeWidth",
                    "SetCanResizeHeight", "SetContextObject", "SetOpacity", "SetMoveable",
                    "PropagatePriority", "RegisterTopMost", "RemoveTopMost",
                    "SetCurrentStateImageOpacity", "ShaderTechniqueSet", "SetTextHAlign",
                    "SetTextVAlign", "SetTextXOffset", "SetTextYOffset", "ResizeTextResizingComponentToInitialSize",
                    "SetImageRotation", "SetGlobalExclusiveFocus", "LockPriority",
                    "UnLockPriority", "SetTooltipTextWithRLSKey", "SetStateTextXOffset",
                    "SetCurrentStateImageTiled", "SetCurrentStateImageMargins",
                    "SetImageColour", "SetCurrentStateImageDockOffset", "TriggerAnimation",
                    "SetCanResizeCurrentStateImageWidth", "SetCanResizeCurrentStateImageHeight",
                    "ResizeCurrentStateImage", "SetCurrentStateImageDockingPoint",
                    "SetTextColour", "SetTextSize", "SetFont", "StopAnimation"}) do
    COMP[k] = function() end
end

function S.root_of(c)
    local p = c
    while p.parent do p = p.parent end
    return p
end

function S.find_uicomponent(m, ...)
    local args = {...}
    local cur, i = m.root, 1
    if getmetatable(args[1]) == COMP_MT then cur, i = args[1], 2 end
    if not cur then return false end
    for j = i, #args do
        local nxt = S.find_desc(cur, args[j])
        if not nxt then return false end
        cur = nxt
    end
    return cur
end

-- ---------------------------------------------------------------- events ----
function S.ctx(m, fields)
    local c = {}
    for k, v in pairs(fields) do
        if k == "string" or k == "component" then c[k] = v end
    end
    return setmetatable(c, {__index = function(_, k)
        local v = fields[k]
        if v ~= nil then return function() return v end end
        return S.auto(m, "ctx", k)
    end})
end

function S.fire(m, ev, fields)
    m.fired[ev] = (m.fired[ev] or 0) + 1
    local list = m.E.events[ev]
    if not list then return end
    local ctx = S.ctx(m, fields or {})
    local snapshot = {}
    for i, f in ipairs(list) do snapshot[i] = f end
    for _, f in ipairs(snapshot) do
        local ok, e = pcall(f, ctx)
        if not ok then S.err(m, ev, e) end
    end
end

function S.make_core(m)
    local core = {event_listeners = {}}
    local function dispatcher(ev)
        return function(ctx)
            local list = core.event_listeners[ev] or {}
            local snapshot = {}
            for i, l in ipairs(list) do snapshot[i] = l end
            for _, l in ipairs(snapshot) do
                local pass = l.condition == true
                if not pass and type(l.condition) == "function" then
                    local ok, r = pcall(l.condition, ctx)
                    if not ok then S.err(m, ev .. " condition " .. tostring(l.name), r) end
                    pass = ok and r and true or false
                end
                if pass then
                    if not l.persistent then
                        for i = #list, 1, -1 do if list[i] == l then table.remove(list, i) end end
                    end
                    local ok, e = pcall(l.callback, ctx)
                    if not ok then S.err(m, ev .. " " .. tostring(l.name), e) end
                end
            end
        end
    end
    function core:add_listener(name, ev, condition, callback, persistent)
        if not core.event_listeners[ev] then
            core.event_listeners[ev] = {}
            m.E.events[ev] = m.E.events[ev] or {}
            table.insert(m.E.events[ev], dispatcher(ev))
        end
        table.insert(core.event_listeners[ev], {name = name, event = ev, condition = condition,
                                                callback = callback, persistent = persistent})
    end
    function core:remove_listener(name)
        for _, list in pairs(core.event_listeners) do
            for i = #list, 1, -1 do if list[i].name == name then table.remove(list, i) end end
        end
    end
    function core:trigger_event(ev, ...)
        local fields = {}
        for i = 1, select("#", ...) do
            local a = select(i, ...)
            local tag = type(a) == "table" and rawget(a, "__simtag") or nil
            if type(a) == "string" then fields.string = a
            elseif tag then
                local kind = string.match(tag, "^[^:]+")
                fields[kind] = a
            end
        end
        S.fire(m, ev, fields)
    end
    core.trigger_custom_event = core.trigger_event
    function core:get_ui_root() return m.root end
    function core:svr_load_bool(k)
        if k == "mct_local_is_host" then return m.i == 1 end
        return m.svr[k] == true
    end
    function core:svr_save_bool(k, v) m.svr[k] = v end
    function core:svr_load_string(k) return m.svr[k] end
    function core:svr_save_string(k, v) m.svr[k] = v end
    function core:get_screen_resolution() return m.res[1], m.res[2] end
    function core:add_ui_created_callback(fn) m.ui_created[#m.ui_created + 1] = fn end
    function core:is_ui_created() return true end
    function core:is_campaign() return true end
    function core:is_battle() return false end
    function core:is_frontend() return false end
    function core:get_static_object(k) return m.statics[k] end
    function core:add_static_object(k, v) m.statics[k] = v end
    return setmetatable(core, {__index = function(_, k)
        S.note_unknown(m, "core:" .. k)
        return function() return nil end
    end})
end

-- ---------------------------------------------------------------- cm -------
-- Calls the game answers on this machine alone and that change nothing in the model:
-- timers, the camera, UI overrides, the advisor. Kept out of the log; a mod is free to
-- make them from a click.
S.LOCAL_CM = {"^callback$", "^real_callback$", "^repeat_callback$", "^repeat_real_callback$",
              "^remove_callback$", "^remove_real_callback$", "^add_first_tick_callback",
              "^add_loading_game_callback$", "^add_saving_game_callback$",
              "^add_post_first_tick_callback", "^scroll_camera", "^set_camera", "^steal_",
              "^release_", "^override_ui", "^disable_shortcut", "^highlight", "^unhighlight",
              "^show_advice", "^dismiss_advice", "^set_ui", "^out$", "^cache_",
              "^take_shroud_snapshot", "^restore_shroud", "^enable_ui", "^disable_ui",
              "^suppress_ui", "^zoom_camera", "^get_", "^is_", "^has_", "^can_",
              "^char_lookup_str$", "^model$", "^turn_number$", "^lookup", "^query",
              "^are_", "^does_", "_exists$", "^num_", "^whose_turn", "^faction_is_",
              "^campaign_name", "^load_named_value$", "^print", "^log"}

function S.is_local_cm(k)
    for _, p in ipairs(S.LOCAL_CM) do
        if string.match(k, p) then return true end
    end
    return false
end

function S.make_cm(m)
    local W = m.W
    local cm = {}
    function cm:add_first_tick_callback(fn) m.first_ticks[#m.first_ticks + 1] = fn end
    cm.add_first_tick_callback_new = cm.add_first_tick_callback
    cm.add_first_tick_callback_mp_new = cm.add_first_tick_callback
    function cm:add_first_tick_callback_sp_new() end
    cm.add_post_first_tick_callback = cm.add_first_tick_callback
    function cm:add_loading_game_callback(fn) m.load_cbs[#m.load_cbs + 1] = fn end
    function cm:add_saving_game_callback(fn) m.save_cbs[#m.save_cbs + 1] = fn end
    function cm:save_named_value(name, v)
        S.record(m, "save_named_value", name, v)
        m.log[#m.log].v = v
        m.named[name] = v
    end
    function cm:load_named_value(name, default)
        if m.loaded[name] ~= nil then return m.loaded[name] end
        return default
    end
    function cm:callback(fn, t, name) m.timers[#m.timers + 1] = {fn = fn, name = name} end
    cm.real_callback = cm.callback
    function cm:repeat_callback(fn, t, name)
        m.timers[#m.timers + 1] = {fn = fn, name = name, rep = true}
    end
    cm.repeat_real_callback = cm.repeat_callback
    function cm:remove_callback(name)
        for i = #m.timers, 1, -1 do
            if m.timers[i].name == name then table.remove(m.timers, i) end
        end
    end
    cm.remove_real_callback = cm.remove_callback

    function cm:is_multiplayer() return true end
    function cm:is_new_game() return m.new_game end
    function cm:model() return S.model(m) end
    function cm:turn_number() return W.turn end
    function cm:get_campaign_name() return "main_warhammer" end
    function cm:get_human_factions()
        local t = {}
        for i, k in ipairs(S.HUMANS) do t[i] = k end
        return t
    end
    -- CA: "will throw a script error in multiplayer unless force is set".
    function cm:get_local_faction_name(force)
        if not force then error("get_local_faction_name called unforced in multiplayer", 2) end
        return m.faction
    end
    function cm:get_local_faction(force)
        if not force then error("get_local_faction called unforced in multiplayer", 2) end
        return S.faction(m, m.faction)
    end
    function cm:get_faction(k) return S.faction(m, k) or false end
    function cm:get_region(r) return S.region(m, r) or false end
    function cm:get_character_by_cqi(c) return S.char(m, c) or false end
    function cm:get_military_force_by_cqi(c) return S.force(m, (c or 0) - 90000) or false end
    function cm:get_family_member_by_cqi(c)
        local ch = S.char(m, (c or 0) - 50000)
        return ch and ch:family_member() or false
    end
    function cm:char_lookup_str(c)
        if type(c) == "table" then c = c:command_queue_index() end
        return "character_cqi:" .. tostring(c)
    end
    function cm:get_saved_value(k) return m.saved[k] end
    -- THE SELECTION IS THIS MACHINE'S: what its player last clicked on the map.
    function cm:get_campaign_ui_manager()
        return S.iface(m, "uim", {
            get_char_selected_cqi = function() return m.selected_char end,
            get_char_selected = function()
                return m.selected_char and ("character_cqi:" .. m.selected_char) or ""
            end,
            get_selected_settlement_region = function() return m.selected_region end,
            is_char_selected = function() return m.selected_char ~= nil end,
            is_settlement_selected = function() return m.selected_region ~= nil end,
        })
    end
    function cm:random_number(hi, lo) return S.rng(m, "random_number", hi, lo) end

    function cm:set_saved_value(k, v)
        S.record(m, "set_saved_value", k, v)
        m.log[#m.log].v = v
        m.saved[k] = v
    end
    function cm:treasury_mod(f, n)
        S.record(m, "treasury_mod", f, n)
        if W.gold[f] then W.gold[f] = W.gold[f] + (tonumber(n) or 0) end
    end
    function cm:faction_add_pooled_resource(f, res, factor, n)
        S.record(m, "faction_add_pooled_resource", f, res, factor, n)
        if W.pooled[f] then W.pooled[f][res] = (W.pooled[f][res] or 0) + (tonumber(n) or 0) end
    end
    function cm:apply_effect_bundle(b, f, t)
        S.record(m, "apply_effect_bundle", b, f, t)
        if W.bundles[f] then W.bundles[f][b] = t or -1 end
    end
    -- TRAITS ARE STATE: a court remembers who sits in which party by them.
    local function char_of(x)
        if type(x) == "string" then return W.chars[tonumber(string.match(x, "(%d+)$")) or -1] end
        if type(x) == "number" then return W.chars[x] end
        if type(x) == "table" then
            local ok, n = pcall(function() return x:command_queue_index() end)
            if ok then return W.chars[n] or W.chars[(n or 0) - 50000] end
        end
    end
    function cm:force_add_trait(who, t, _show, pts)
        S.record(m, "force_add_trait", who, t, pts)
        local c = char_of(who)
        if c then c.traits[t] = (c.traits[t] or 0) + (tonumber(pts) or 1) end
    end
    function cm:force_add_trait_to_character_details(who, t, _show, pts)
        S.record(m, "force_add_trait_to_character_details", who, t, pts)
        local c = char_of(who)
        if c then c.traits[t] = (c.traits[t] or 0) + (tonumber(pts) or 1) end
    end
    function cm:force_remove_trait(who, t)
        S.record(m, "force_remove_trait", who, t)
        local c = char_of(who)
        if c then c.traits[t] = nil end
    end
    function cm:remove_effect_bundle(b, f)
        S.record(m, "remove_effect_bundle", b, f)
        if W.bundles[f] then W.bundles[f][b] = nil end
    end
    return setmetatable(cm, {__index = function(_, k)
        if S.is_local_cm(k) then
            S.note_unknown(m, "cm-read:" .. k)
            return function() return nil end
        end
        S.note_unknown(m, "cm-write:" .. k)
        return function(_, ...) S.record(m, "cm:" .. k, ...) end
    end})
end

-- ---------------------------------------------------------------- MCT ------
-- The settings files run once, against a recorder, to learn every option's type,
-- default, bounds and choices. Each machine then answers with its OWN value: the host
-- moves every option one way, the clients another, so a mod that read its own MCT in
-- multiplayer freezes a different campaign on every machine.
S.OPTS = {}

function S.recorder()
    local function any()
        return setmetatable({}, {__index = function() return function(self) return self end end})
    end
    local mct = {}
    function mct:register_mod(key)
        local opts = {}
        S.OPTS[key] = opts
        local mod = {}
        function mod:add_new_option(okey, otype)
            local o = {type = otype, values = {}}
            opts[okey] = o
            local opt = any()
            local mt = getmetatable(opt)
            local base = mt.__index
            mt.__index = function(_, k)
                if k == "set_default_value" then
                    return function(self, v) o.default = v return self end
                elseif k == "slider_set_min_max" then
                    return function(self, a, b) o.min, o.max = a, b return self end
                elseif k == "add_dropdown_value" then
                    return function(self, v) o.values[#o.values + 1] = v return self end
                elseif k == "add_dropdown_values" then
                    return function(self, list)
                        for _, v in ipairs(list or {}) do
                            o.values[#o.values + 1] = type(v) == "table" and (v.key or v[1]) or v
                        end
                        return self
                    end
                end
                return base(_, k)
            end
            return opt
        end
        return setmetatable(mod, {__index = function() return function(self) return any() end end})
    end
    return setmetatable(mct, {__index = function() return function() return any() end end})
end

function S.capture_mct(files)
    for _, path in ipairs(files) do
        local E = setmetatable({}, {__index = _G})
        E._G = E
        local rec = S.recorder()
        E.get_mct = function() return rec end
        E.core = setmetatable({}, {__index = function() return function() end end})
        E.out = setmetatable({}, {__call = function() end,
                                  __index = function() return function() end end})
        local chunk, e = loadfile(path)
        if chunk then
            setfenv(chunk, E)
            local ok, e2 = pcall(chunk)
            if not ok then NOTES[#NOTES + 1] = "MCT file " .. path .. ": " .. tostring(e2) end
        else
            NOTES[#NOTES + 1] = "MCT file " .. path .. ": " .. tostring(e)
        end
    end
end

-- skew 1 is the host, 2 and 3 the clients; skew 4 is a client changing its mind.
function S.mct_value(o, skew)
    local d = o.default
    if o.type == "checkbox" or type(d) == "boolean" then
        if skew == 2 then return d end
        return not d
    end
    if o.type == "slider" or type(d) == "number" then
        local lo, hi = tonumber(o.min), tonumber(o.max)
        if skew == 1 then return lo or ((d or 0) + 1) end
        if skew == 2 then return hi or ((d or 0) + 2) end
        if skew == 3 then return ((lo or 0) + (hi or 0)) / 2 end
        return hi or ((d or 0) + 3)
    end
    if #o.values > 0 then
        local others = {}
        for _, v in ipairs(o.values) do if v ~= d then others[#others + 1] = v end end
        if #others == 0 then return d end
        return others[((skew - 1) % #others) + 1]
    end
    return d
end

function S.make_mct(m)
    local mct = {}
    function mct:get_mod_by_key(key)
        local opts = S.OPTS[key]
        if not opts then return nil end
        local mod = {}
        function mod:get_option_by_key(okey)
            local o = opts[okey]
            if not o then return nil end
            local opt = {}
            function opt:get_finalized_setting() return S.mct_value(o, m.skew) end
            opt.get_selected_setting = opt.get_finalized_setting
            function opt:get_key() return okey end
            return setmetatable(opt, {__index = function() return function() return nil end end})
        end
        return setmetatable(mod, {__index = function() return function() return nil end end})
    end
    return setmetatable(mct, {__index = function() return function() return nil end end})
end

-- ---------------------------------------------------------------- machine ---
function S.copy_lib(t)
    local c = {}
    for k, v in pairs(t) do c[k] = v end
    return c
end

function S.new_machine(i)
    local m = {i = i, faction = S.HUMANS[i], log = {}, mark = 0, errors = {}, unknown = {},
               saved = {}, named = {}, loaded = {}, svr = {}, statics = {}, timers = {},
               first_ticks = {}, load_cbs = {}, save_cbs = {}, ui_created = {},
               pending_clicks = {}, fired = {}, sent = 0, received = 0, rng = 20261021,
               new_game = true, skew = i, clk = 0, mrand = 7919 * i, ids = {},
               res = (i == 1) and {1920, 1080} or {2560, 1440}}
    S.build_world(m)
    m.root = S.comp(m, "root", nil, m.res[1], m.res[2])
    m.LAYOUTS = S.LAYOUTS

    local E = {}
    for k, v in pairs(_G) do E[k] = v end
    E.string, E.table = S.copy_lib(string), S.copy_lib(table)
    E.math = S.copy_lib(math)
    -- A DIFFERENT STREAM ON EVERY MACHINE, as the game's own math.random is: a value
    -- rolled here and put into the model is a desync the log will show.
    E.math.random = function(a, b)
        m.mrand = (m.mrand * 16807) % 2147483647
        local r = m.mrand / 2147483647
        if a and b then return a + math.floor(r * (b - a + 1)) end
        if a then return 1 + math.floor(r * a) end
        return r
    end
    E.math.randomseed = function() end
    E.os = {time = function() return 1790000000 + 1000 * i end,
            clock = function() m.clk = m.clk + 0.01 * i return m.clk end,
            date = os.date, difftime = os.difftime, getenv = function() return nil end}
    local sink = {write = function(self) return self end, close = function() end,
                  flush = function() end, lines = function() return function() end end,
                  read = function() return nil end, seek = function() return 0 end}
    E.io = {open = function() return sink end, write = function() end,
            lines = function() return function() end end, stdout = sink, stderr = sink}
    E.print = function() end
    E._G = E
    E.loadstring = function(s, n)
        local f, e = loadstring(s, n)
        if f then setfenv(f, E) end
        return f, e
    end
    E.loadfile = function(p)
        local f, e = loadfile(p)
        if f then setfenv(f, E) end
        return f, e
    end
    E.dofile = function(p) local f = assert(E.loadfile(p)) return f() end
    E.events = {}
    m.E = E

    E.cm = S.make_cm(m)
    E.core = S.make_core(m)
    local mct = S.make_mct(m)
    E.get_mct = function() return mct end
    E.out = setmetatable({}, {__call = function() end,
                              __index = function() return function() end end})
    E.find_uicomponent = function(...) return S.find_uicomponent(m, ...) end
    E.UIComponent = function(c) return c end
    E.is_uicomponent = function(c) return getmetatable(c) == COMP_MT end
    E.CampaignUI = setmetatable({
        TriggerCampaignScriptEvent = function(cqi, str)
            m.sent = m.sent + 1
            str = tostring(str)
            m.max_sent = math.max(m.max_sent or 0, #str)
            if cqi ~= S.spec(m.faction).cqi then
                S.record(m, "SENT_AS_ANOTHER_FACTION", cqi, str)
            end
            if CFG.mutant then
                -- THE PLANTED FAULT: the op runs here and nowhere else. A clean run
                -- of the real mods under this switch would mean no click reached an op.
                S.fire(m, "UITrigger", {trigger = str, faction_cqi = cqi})
            else
                BUS[#BUS + 1] = {cqi = cqi, str = str, from = i}
            end
        end,
    }, {__index = function(_, k)
        S.note_unknown(m, "CampaignUI." .. k)
        return function() return nil end
    end})
    local lib = setmetatable({}, {__index = function(_, k)
        if k == "get_localised_string" then return function(key) return tostring(key) end end
        S.note_unknown(m, "common." .. k)
        return function() return nil end
    end})
    E.common = lib
    E.effect = lib
    E.is_string = function(x) return type(x) == "string" end
    E.is_number = function(x) return type(x) == "number" end
    E.is_table = function(x) return type(x) == "table" end
    E.is_function = function(x) return type(x) == "function" end
    E.is_boolean = function(x) return type(x) == "boolean" end
    E.is_nil = function(x) return x == nil end
    setmetatable(E, {__index = function(_, k)
        S.note_unknown(m, "global:" .. tostring(k))
        return nil
    end})
    return m
end

function S.load_scripts(m, files)
    for _, path in ipairs(files) do
        local chunk, e = loadfile(path)
        if not chunk then
            S.err(m, "load " .. path, e)
        else
            setfenv(chunk, m.E)
            local ok, e2 = pcall(chunk)
            if not ok then S.err(m, "load " .. path, e2) end
        end
    end
end

function S.run_list(m, list, where)
    for _, fn in ipairs(list) do
        local ok, e = pcall(fn)
        if not ok then S.err(m, where, e) end
    end
end

-- Timers run to quiet, a bounded number of passes; a repeating one runs once a pass.
function S.run_timers(m)
    for _ = 1, 8 do
        if #m.timers == 0 then return end
        local now = m.timers
        m.timers = {}
        for _, t in ipairs(now) do
            local ok, e = pcall(t.fn)
            if not ok then S.err(m, "callback " .. tostring(t.name), e) end
            if t.rep then m.timers[#m.timers + 1] = t end
        end
        local only_rep = true
        for _, t in ipairs(m.timers) do if not t.rep then only_rep = false end end
        if only_rep then return end
    end
end

function S.deliver()
    for _ = 1, 200 do
        for _, m in ipairs(M) do S.run_timers(m) end
        for _, m in ipairs(M) do
            while #m.pending_clicks > 0 do
                local c = table.remove(m.pending_clicks, 1)
                S.fire(m, "ComponentLClickUp", {string = c.id, component = c})
            end
        end
        if #BUS == 0 then return end
        local msg = table.remove(BUS, 1)
        local op = string.match(msg.str, "^([^|]*|[^|]*)") or msg.str
        S.OPS_SEEN[op] = (S.OPS_SEEN[op] or 0) + 1
        for _, m in ipairs(M) do
            m.received = m.received + 1
            S.fire(m, "UITrigger", {trigger = msg.str, faction_cqi = msg.cqi})
        end
    end
    NOTES[#NOTES + 1] = "the bus did not go quiet in 200 deliveries"
end

-- ---------------------------------------------------------------- compare ---
S.STEPS = 0

function S.step(label, fn)
    S.STEPS = S.STEPS + 1
    if CFG.trace then io.write("STEP ", label, "\n") end
    for _, m in ipairs(M) do m.mark = #m.log end
    local ok, e = pcall(fn)
    if not ok then NOTES[#NOTES + 1] = "step '" .. label .. "' raised: " .. tostring(e) end
    S.deliver()
    S.compare(label)
end

function S.compare(label)
    local delta = {}
    for i, m in ipairs(M) do
        local d = {}
        for j = m.mark + 1, #m.log do d[#d + 1] = m.log[j] end
        delta[i] = d
    end
    local n = 0
    for _, d in ipairs(delta) do n = math.max(n, #d) end
    for j = 1, n do
        local s1 = delta[1][j] and delta[1][j].s
        local same = true
        for i = 2, #M do
            local si = delta[i][j] and delta[i][j].s
            if si ~= s1 then same = false end
        end
        if not same then
            -- ONE FINDING PER CAUSE: the same call from the same lines on every machine,
            -- however many steps hit it.
            local sig = {}
            for i = 1, #M do
                local en = delta[i][j]
                sig[i] = en and (string.match(en.s, "^[^(]*") .. "@" .. en.at) or "-"
            end
            sig = table.concat(sig, "|")
            S.SEEN_SIG = S.SEEN_SIG or {}
            local dup = S.SEEN_SIG[sig]
            if dup then
                dup.repeats = dup.repeats + 1
                return
            end
            if #FINDINGS < MAX_FINDINGS then
                local lines = {}
                local keyed = S.key_diff(delta, j)
                for i, m in ipairs(M) do
                    local en = delta[i][j]
                    local s = en and en.s or "(no call)"
                    if keyed and #s > 160 then s = string.sub(s, 1, 160) .. " ..." end
                    lines[#lines + 1] = string.format("    machine %d (%s): %s", i, m.faction,
                        en and (s .. "   <- " .. en.at) or s)
                end
                for _, l in ipairs(keyed or {}) do lines[#lines + 1] = l end
                FINDINGS[#FINDINGS + 1] = {label = label, entry = j, repeats = 0,
                                           counts = S.counts(delta), lines = lines}
                S.SEEN_SIG[sig] = FINDINGS[#FINDINGS]
            else
                S.OVERFLOW = (S.OVERFLOW or 0) + 1
            end
            return
        end
    end
    S.CALLS = (S.CALLS or 0) + #delta[1]
end

-- A SAVED TABLE THAT DIFFERS: which keys, and what each machine holds there.
function S.key_diff(delta, j)
    local vals = {}
    for i = 1, #M do
        local en = delta[i][j]
        if not (en and type(en.v) == "table") then return nil end
        vals[i] = en.v
    end
    local keys, seen = {}, {}
    for i = 1, #M do
        for k in pairs(vals[i]) do
            if not seen[k] then seen[k] = true keys[#keys + 1] = k end
        end
    end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    local out = {}
    for _, k in ipairs(keys) do
        local s1 = S.ser(vals[1][k])
        local differs = false
        for i = 2, #M do if S.ser(vals[i][k]) ~= s1 then differs = true end end
        if differs then
            if #out >= 8 * #M then out[#out + 1] = "      ... more keys differ" break end
            for i = 1, #M do
                local s = S.ser(vals[i][k])
                if #s > 200 then s = string.sub(s, 1, 200) .. " ..." end
                out[#out + 1] = string.format("      key %s, machine %d: %s", tostring(k), i, s)
            end
        end
    end
    return out
end

function S.counts(delta)
    local t = {}
    for i, d in ipairs(delta) do t[#t + 1] = "m" .. i .. "=" .. #d end
    return table.concat(t, " ")
end

-- ---------------------------------------------------------------- monkey ----
S.CLOSE = {"close", "cancel", "exit", "dismiss", "back"}

function S.is_closer(id)
    id = string.lower(id)
    for _, w in ipairs(S.CLOSE) do if string.find(id, w, 1, true) then return true end end
    return false
end

-- WHAT A BUTTON SAYS, AS WELL AS WHERE IT IS. A panel that reuses one row pool for
-- every view puts a picker's choices on rows already pressed in the court list, so a
-- row is new again whenever its own text, its tooltip or a child's text changes.
function S.sig(c)
    local parts = {c.text, c.tip}
    for _, k in ipairs(c.kids) do
        if k.visible then parts[#parts + 1] = k.text end
    end
    return table.concat(parts, "\1")
end

function S.walk(c, path, out)
    for idx, k in ipairs(c.kids) do
        if k.visible then
            local p = path .. "/" .. k.id .. "#" .. idx
            if k.interactive and not k.disabled then
                out[#out + 1] = {c = k, path = p, key = p .. "\2" .. S.sig(k)}
            end
            S.walk(k, p, out)
        end
    end
    return out
end

function S.candidates(m, visited)
    local all = S.walk(m.root, "", {})
    local open, closers = {}, {}
    for _, e in ipairs(all) do
        if not visited[e.key] then
            if S.is_closer(e.c.id) then closers[#closers + 1] = e else open[#open + 1] = e end
        end
    end
    local sorter = function(a, b) return a.path < b.path end
    table.sort(open, sorter)
    table.sort(closers, sorter)
    return open[1] or closers[1]
end

function S.click(m, c, label)
    S.CLICKS = (S.CLICKS or 0) + 1
    S.step(label, function()
        S.fire(m, "ComponentLClickUp", {string = c.id, component = c})
    end)
end

function S.click_name(m, name, label)
    local c = S.find_desc(m.root, name) or S.comp(m, name, nil)
    S.click(m, c, label)
end

function S.monkey(m, round)
    local tag = "round " .. round .. ", machine " .. m.i .. " (" .. m.faction .. ")"
    local leader = S.char(m, S.spec(m.faction).cqi * 100 + 1)
    S.step(tag .. ": selects its faction leader", function()
        m.selected_char = leader:command_queue_index()
        m.selected_region = S.region(m, S.spec(m.faction).regions[1])
        S.fire(m, "CharacterSelected", {character = leader})
        S.fire(m, "SettlementSelected",
               {garrison_residence = S.region(m, S.spec(m.faction).regions[1]):garrison_residence()})
    end)
    local visited = {}
    local budget = CFG.max_clicks or 250
    local reopened = 0
    while budget > 0 do
        local e = S.candidates(m, visited)
        if not e then
            if reopened >= #CFG.openers * 2 then break end
            local name = CFG.openers[(reopened % #CFG.openers) + 1]
            reopened = reopened + 1
            S.click_name(m, name, tag .. ": opens " .. name)
        else
            visited[e.key] = true
            budget = budget - 1
            S.click(m, e.c, tag .. ": clicks " .. e.path)
        end
    end
    S.step(tag .. ": opens a CA panel over it", function()
        S.fire(m, "PanelOpenedCampaign", {string = "diplomacy_dropdown"})
        S.fire(m, "PanelClosedCampaign", {string = "diplomacy_dropdown"})
    end)
end

-- ---------------------------------------------------------------- run -------
S.LAYOUTS = CFG.layouts and dofile(CFG.layouts) or {}
S.OPS_SEEN = {}
S.capture_mct(CFG.mct_files or {})
for i = 1, S.NMACH do M[i] = S.new_machine(i) end

-- Events the game raises on one machine only. Everything else a listener names is a
-- model event, raised on every machine with the same context.
S.LOCAL_EVENTS = {ComponentLClickUp = true, ComponentLClickDown = true, UITrigger = true,
                  PanelOpenedCampaign = true, PanelClosedCampaign = true,
                  CharacterSelected = true, SettlementSelected = true, MctFinalized = true,
                  MctOptionSettingFinalized = true, ComponentMouseOn = true,
                  ShortcutTriggered = true, RealTimeTrigger = true}

S.step("load the scripts", function()
    for _, m in ipairs(M) do S.load_scripts(m, CFG.scripts) end
end)
S.step("UI created", function()
    for _, m in ipairs(M) do S.run_list(m, m.ui_created, "ui created callback") end
end)
S.step("first tick of a new campaign", function()
    for _, m in ipairs(M) do S.run_list(m, m.first_ticks, "first tick") end
end)

-- A MID-CAMPAIGN START, from check_mp_sim.py: the same Lua in every machine, so it
-- cannot itself desync anything, and the compare after it proves that.
if CFG.seed then
    S.step("seed the campaign to mid-game", function()
        for _, m in ipairs(M) do
            local f, e = loadstring(CFG.seed, "=seed")
            if not f then error(e) end
            setfenv(f, m.E)
            local ok, e2 = pcall(f)
            if not ok then S.err(m, "seed", e2) end
        end
    end)
end

function S.rich(m, fk)
    local spec = S.spec(fk)
    local f = S.faction(m, fk)
    local r = S.region(m, spec.regions[1])
    local leader = f:faction_leader()
    local force = leader:military_force()
    return {faction = f, character = leader, region = r,
            garrison_residence = r:garrison_residence(), confederation = f,
            proposer = f, recipient = S.faction(m, S.HUMANS[2]),
            requesting_faction = f, target_character = leader, family_member = leader:family_member(),
            military_force = force, unit = force:unit_list():item_at(0),
            building = r:settlement():slot_list():item_at(0):building(),
            mission = S.iface(m, "mission:sim", {mission_record_key = function() return "sim_mission" end,
                                                 faction = function() return f end}),
            ritual = S.iface(m, "ritual:sim", {ritual_key = function() return "sim_ritual" end,
                                               ritual_category = function() return "STANDARD_RITUAL" end}),
            technology = "sim_tech", resource = "sim_resource", succeeded = true,
            mission_result_success = true, is_allied = false, ranks_gained = 1,
            agent_action_key = "sim_action", string = "sim"}
end

-- Model events with a listener and no special handling below: each raised once a round,
-- about the first human, on every machine.
function S.model_events()
    local names = {}
    for ev in pairs(M[1].E.core.event_listeners) do
        if not S.LOCAL_EVENTS[ev] and ev ~= "FactionTurnStart" and ev ~= "FactionTurnEnd"
           and not string.match(ev, "^Derpy") and not string.match(ev, "^Zharr") then
            names[#names + 1] = ev
        end
    end
    table.sort(names)
    return names
end

function S.local_events()
    local names = {}
    for ev in pairs(M[1].E.core.event_listeners) do
        if string.match(ev, "^Derpy") or string.match(ev, "^Zharr") then names[#names + 1] = ev end
    end
    table.sort(names)
    return names
end

for round = 1, CFG.rounds or 2 do
    S.step("round " .. round .. ": world start", function()
        for _, m in ipairs(M) do S.fire(m, "WorldStartRound", {}) end
    end)
    for _, spec in ipairs(S.FACTIONS) do
        if not spec.human then
            S.step("round " .. round .. ": " .. spec.k .. " turn", function()
                for _, m in ipairs(M) do
                    m.turn_of = spec.k
                    S.fire(m, "FactionTurnStart", {faction = S.faction(m, spec.k)})
                    S.fire(m, "FactionTurnEnd", {faction = S.faction(m, spec.k)})
                end
            end)
        end
    end
    for _, k in ipairs(S.HUMANS) do
        S.step("round " .. round .. ": " .. k .. " turn starts", function()
            for _, m in ipairs(M) do
                m.turn_of = k
                m.human_phase = true
                S.fire(m, "FactionTurnStart", {faction = S.faction(m, k)})
            end
        end)
    end
    for _, ev in ipairs(S.model_events()) do
        S.step("round " .. round .. ": model event " .. ev, function()
            for _, m in ipairs(M) do S.fire(m, ev, S.rich(m, S.HUMANS[1])) end
        end)
    end
    for _, m in ipairs(M) do S.monkey(m, round) end
    -- MCT buttons and a client changing its MCT mid-campaign: one machine each.
    for _, ev in ipairs(S.local_events()) do
        S.step("round " .. round .. ": machine 2 raises " .. ev, function()
            S.fire(M[2], ev, {})
        end)
    end
    S.step("round " .. round .. ": machine 2 changes its MCT and finalizes", function()
        M[2].skew = 4
        S.fire(M[2], "MctFinalized", {})
    end)
    for _, k in ipairs(S.HUMANS) do
        S.step("round " .. round .. ": " .. k .. " turn ends", function()
            for _, m in ipairs(M) do S.fire(m, "FactionTurnEnd", {faction = S.faction(m, k)}) end
        end)
    end
    for _, m in ipairs(M) do m.human_phase = false end
    S.step("round " .. round .. ": every machine saves", function()
        for _, m in ipairs(M) do S.run_list(m, m.save_cbs, "saving game callback") end
    end)
    for _, m in ipairs(M) do m.W.turn = m.W.turn + 1 end
end

-- A DEBUGGING HOOK, never set by check_mp_sim.py: a file run with S and M in scope.
if CFG.probe then
    local f = assert(loadfile(CFG.probe))
    setfenv(f, setmetatable({S = S, M = M, BUS = BUS}, {__index = _G}))
    f()
end

-- ---------------------------------------------------------------- report ----
local R = {}
local function P(s) R[#R + 1] = s end

P("MP SIM " .. CFG.name .. (CFG.mutant and " [planted fault: ops apply on the sender only]" or ""))
P(string.format("  %d machines, %d steps, %d clicks, %d model calls compared",
                #M, S.STEPS, S.CLICKS or 0, S.CALLS or 0))
local sent, recv = 0, 0
for _, m in ipairs(M) do sent = sent + m.sent; recv = math.max(recv, m.received) end
P(string.format("  %d multiplayer events sent, %d delivered to every machine, longest %d chars",
                sent, recv, (function() local x = 0 for _, m in ipairs(M) do x = math.max(x, m.max_sent or 0) end return x end)()))

-- OPS REACHED: every MP_OPS table any loaded mod declares, against what crossed the bus.
local declared = {}
for name, v in pairs(M[1].E) do
    if type(v) == "table" and type(rawget(v, "MP_OPS")) == "table" and type(rawget(v, "MP_TAG")) == "string" then
        for op in pairs(v.MP_OPS) do declared[#declared + 1] = v.MP_TAG .. "|" .. op end
    end
end
table.sort(declared)
local missed = {}
for _, op in ipairs(declared) do if not S.OPS_SEEN[op] then missed[#missed + 1] = op end end
local reached = #declared - #missed
P(string.format("  ops reached: %d of %d declared", reached, #declared))
if #missed > 0 then P("  ops no click reached: " .. table.concat(missed, ", ")) end

if #FINDINGS == 0 then
    P("  DESYNCS: none")
else
    P("  DESYNCS: " .. #FINDINGS .. (S.OVERFLOW and (" (+" .. S.OVERFLOW .. " more not shown)") or ""))
    for _, f in ipairs(FINDINGS) do
        P("  - " .. f.label .. "  [first difference at call " .. f.entry .. "; " .. f.counts .. "]"
          .. (f.repeats > 0 and ("  and " .. f.repeats .. " later step(s) the same way") or ""))
        for _, l in ipairs(f.lines) do P(l) end
    end
end

-- ERRORS: summed across machines, first 15 by count.
local errs = {}
for _, m in ipairs(M) do
    for k, n in pairs(m.errors) do errs[k] = (errs[k] or 0) + n end
end
local ek = {}
for k in pairs(errs) do ek[#ek + 1] = k end
table.sort(ek, function(a, b) if errs[a] ~= errs[b] then return errs[a] > errs[b] end return a < b end)
if #ek > 0 then
    P("  script errors (" .. #ek .. " distinct; the stubbed world answers some calls wrongly):")
    for i = 1, math.min(CFG.show_errors or 15, #ek) do P(string.format("    %5d  %s", errs[ek[i]], ek[i])) end
end
local uk, unk = {}, {}
for _, m in ipairs(M) do for k, n in pairs(m.unknown) do uk[k] = (uk[k] or 0) + n end end
for k in pairs(uk) do
    if string.match(k, "^cm%-write:") or string.match(k, "^layout:") then unk[#unk + 1] = k end
end
table.sort(unk)
if #unk > 0 then P("  unstubbed writes / missing layouts: " .. table.concat(unk, ", ")) end
for _, n in ipairs(NOTES) do P("  note: " .. n) end

if CFG.dump_unknown then
    local all = {}
    for k in pairs(uk) do all[#all + 1] = k end
    table.sort(all, function(a, b) return uk[a] > uk[b] end)
    for i = 1, math.min(80, #all) do P(string.format("    unknown %6d %s", uk[all[i]], all[i])) end
end

local text = table.concat(R, "\n")
io.write(text, "\n")
io.write(string.format("RESULT desyncs=%d clicks=%d ops_reached=%d ops_declared=%d errors=%d\n",
                       #FINDINGS + (S.OVERFLOW or 0), S.CLICKS or 0, reached, #declared, #ek))
os.exit(#FINDINGS > 0 and 1 or 0)
