local NAMED, SAVEG, LOADG = {}, nil, nil
local function copy(t)
    local c = {}
    for k, v in pairs(t) do c[k] = v end
    return c
end
cm = {
    add_first_tick_callback = function() end,
    -- CAPTURED, not ignored: this harness exists to RUN these two.
    add_loading_game_callback = function(_, f) LOADG = f end,
    add_saving_game_callback = function(_, f) SAVEG = f end,
    -- copy on save, because the engine serialises rather than keeping our table alive
    save_named_value = function(_, n, v, _c) NAMED[n] = (type(v) == "table") and copy(v) or v end,
    load_named_value = function(_, n, d, _c)
        local v = NAMED[n]
        if v == nil then return d end
        return (type(v) == "table") and copy(v) or v
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
