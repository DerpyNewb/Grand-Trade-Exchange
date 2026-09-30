local NAMED, SAVEG, LOADG = {}, nil, nil

-- THE ENGINE SERIALISES, AND THE STUB HAS TO AS WELL. campaign_manager:save_named_value turns a
-- table into Lua source - "return " .. table.tostring(t, true, -1) - and load_named_value runs it
-- back through loadstring (lib_campaign_manager.lua, process_table_save). Numbers go through
-- plain tostring(), which formats with the process's NUMERIC LOCALE. This stub copied the table
-- until 2026-09-28, and a copy cannot see the one thing that went wrong: under a decimal-comma
-- locale ["ladder_step"]=1,1 loads back as ladder_step = 1 plus a stray list entry, and every
-- price on the board read 1000. ca_tostring below is table.tostring's savegame branch.
local function ca_tostring(t)
    local s, first = { "{" }, true
    for k, v in pairs(t) do
        local tv = type(v)
        if tv == "table" or tv == "string" or tv == "number" or tv == "boolean" then
            if first then first = false else s[#s + 1] = "," end
            if type(k) == "string" then s[#s + 1] = '["' .. k .. '"]'
            else s[#s + 1] = "[" .. tostring(k) .. "]" end
            s[#s + 1] = "="
            if tv == "table" then s[#s + 1] = ca_tostring(v)
            elseif tv == "string" then s[#s + 1] = '"' .. v .. '"'
            else s[#s + 1] = tostring(v) end
        end
    end
    s[#s + 1] = "}"
    return table.concat(s)
end

cm = {
    add_first_tick_callback = function() end,
    -- CAPTURED, not ignored: this harness exists to RUN these two.
    add_loading_game_callback = function(_, f) LOADG = f end,
    add_saving_game_callback = function(_, f) SAVEG = f end,
    save_named_value = function(_, n, v, _c)
        NAMED[n] = (type(v) == "table") and ("return " .. ca_tostring(v)) or v
    end,
    load_named_value = function(_, n, d, _c)
        local v = NAMED[n]
        if v == nil then return d end
        if type(v) == "string" and v:sub(1, 7) == "return " then return loadstring(v)() end
        return v
    end,
    -- The OLD store is deliberately empty, so anything that round-trips did so through the
    -- mod's own named value and NOT through the migration fallback.
    get_saved_value = function() return nil end,
    callback = function() end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])

print("registered_save " .. tostring(SAVEG ~= nil))
print("registered_load " .. tostring(LOADG ~= nil))

EX.setv("zharr_sh_test_house", 20)
EX.setv("zharr_hist_res_gems", "27,27,25")
SAVEG({})
print("blob_written " .. tostring(NAMED[EX.SAVE_STORE] ~= nil))

-- THE RELOAD. Wipe every scrap of in-memory state the way a new process would, then run the
-- loading callback and ask for the values back.
EX.store = {}
LOADG({})
print("shares " .. tostring(EX.getv("zharr_sh_test_house")))
print("hist " .. tostring(EX.getv("zharr_hist_res_gems")))

-- A NEW CAMPAIGN has no named value at all: the store must come back an empty TABLE, not nil,
-- or the first EX.setv indexes a nil and takes the whole script down at turn one.
NAMED = {}
EX.store = nil
LOADG({})
print("fresh_type " .. type(EX.store))
EX.setv("zharr_probe", 1)
print("fresh_write " .. tostring(EX.getv("zharr_probe")))

-- A DECIMAL-COMMA LOCALE, FOR REAL. Reported 2026-09-28: "every time I load prices are fine, but
-- right after end of turn every buy/sell are fixed to 1000". A load prices off live settings
-- (EX.snap is nil until the turn round's EX.snapshot); the turn round then adopts the frozen
-- snapshot out of the save, and that is where the fractions had gone. Every check below is run
-- in the locale that breaks it, not simulated.
local COMMA
for _, name in ipairs({ "German_Germany.1252", "de_DE.UTF-8", "de_DE", "fr_FR.UTF-8" }) do
    if os.setlocale(name, "numeric") and tostring(1.5) == "1,5" then COMMA = name; break end
end
print("comma_locale " .. tostring(COMMA ~= nil))
if COMMA then
    local R = "res_rom_iron"
    local function prices() return EX.buy_price(R) .. "/" .. EX.sell_price(R) end

    NAMED, EX.store, EX.snap = {}, {}, nil
    EX.current[R] = EX.neutral_rung() + 5
    EX.snapshot()
    local before = prices()
    EX.setv(EX.SAVE_SHOCK .. R, 1.5)
    EX.save_cshare({ wh_main_emp_empire = 0.1234 })
    SAVEG({})
    EX.store, EX.snap = {}, nil
    LOADG({})
    EX.snapshot()                              -- the next FactionTurnStart
    local after = prices()
    local shock = EX.getv(EX.SAVE_SHOCK .. R)
    local share = EX.load_cshare().wh_main_emp_empire

    -- A SAVE AN EARLIER BUILD ALREADY BROKE. Exactly what it wrote: the fractions are list
    -- entries now, and the only survivors are the integer parts and the preset's name.
    NAMED = { [EX.SAVE_STORE] = 'return {["zharr_opts"]={["ladder_step"]=1,1000000238419,'
        .. '["spread"]=0,10000000149012,["sell_floor"]=0,25,["preset"]="default"}}' }
    EX.store, EX.snap = {}, nil
    LOADG({})
    EX.snapshot()
    local legacy = prices()

    -- THE DISPLAY HALF, read while the locale is still the comma one: EX.num trimmed "1,000"
    -- to "1," - its trailing-separator strip only knew ".".
    local comma_num = EX.num(1) .. "/" .. EX.num(1.5)

    -- ACROSS LOCALES: a multiplayer save is loaded on every machine, and two players need not
    -- share a separator. Written under the comma locale, read back under "C".
    NAMED, EX.store = {}, {}
    EX.setv(EX.SAVE_SHOCK .. R, 2.5)
    SAVEG({})
    os.setlocale("C", "numeric")
    EX.store = {}
    LOADG({})
    print("cross_shock " .. tostring(EX.getv(EX.SAVE_SHOCK .. R)))

    print("comma_num " .. comma_num)
    print("comma_prices " .. before .. " " .. after)
    print("comma_shock " .. tostring(shock))
    print("comma_cshare " .. tostring(share))
    print("legacy_prices " .. legacy)
end
