-- THE EXCHANGE SAVES AND LOADS FIRST, whatever another mod does (2026-10-02). CA's
-- cm:saving_game and cm:loading_game run every mod's callback in one UNPROTECTED loop
-- (lib_campaign_manager.lua), so a mod that throws ahead of us stops the loop and our state is
-- left out of the save, or out of the load. On 2026-10-01 !zorbaz_kiki threw and the save went
-- out with no zharr_state. Here the lists already hold that mod, and the loops run as CA's do.
-- Filled in by Python's percent operator, so every literal percent sign is doubled.
local NAMED, LOGGED = {}, {}
local function thrower() error("another mod's callback failed") end
cm = {
    saving_game_callbacks = { thrower },
    loading_game_callbacks = { thrower },
    add_first_tick_callback = function() end,
    -- WHAT CA'S OWN add_* DO: append.
    add_loading_game_callback = function(self, f) table.insert(self.loading_game_callbacks, f) end,
    add_saving_game_callback = function(self, f) table.insert(self.saving_game_callbacks, f) end,
    save_named_value = function(_, n, v) NAMED[n] = v end,
    load_named_value = function(_, n, d)
        if n == "zharr_state" then return { zharr_probe = 7 } end
        return d
    end,
    get_saved_value = function() return nil end,
    callback = function() end,
    repeat_real_callback = function() end,
    model = function() return { turn_number = function() return 1 end } end,
}
core = { add_listener = function() end }
function out(s) LOGGED[#LOGGED + 1] = tostring(s) end
dofile([[%s]])

-- CA's loops, as cm:saving_game and cm:loading_game run them: the thrower stops each one.
local function run(list) pcall(function() for i = 1, #list do list[i]({}) end end) end

EX.store = { zharr_x = 1 }
run(cm.saving_game_callbacks)
print("saved " .. tostring(type(NAMED.zharr_state) == "table" and NAMED.zharr_state.zharr_x))
EX.store = {}
run(cm.loading_game_callbacks)
print("loaded " .. tostring(EX.store.zharr_probe))

-- AND A SAVE OR LOAD THAT FAILS SAYS SO, rather than shipping a save with nothing in it.
local function said(word)
    for _, l in ipairs(LOGGED) do if string.find(l, word, 1, true) then return true end end
    return false
end
cm.save_named_value = function() error("engine refused") end
LOGGED = {}
run(cm.saving_game_callbacks)
local save_said = said("could not save")
cm.load_named_value = function() error("engine refused") end
LOGGED = {}
run(cm.loading_game_callbacks)
print("said " .. tostring(save_said) .. "," .. tostring(said("could not load")))
