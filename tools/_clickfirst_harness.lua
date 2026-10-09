-- Proves the Exchange's click handler still runs when another mod's click CONDITION throws.
--
-- The failure being modelled was reported on 2026-10-09 (a Great Guilds player: "click sound,
-- nothing opens", and again after the listener was moved to the front of core's queue): since
-- 9.0 lib_core calls listeners unprotected, and core:event_callback tests every listener's
-- condition before it calls any callback, so one throwing condition drops the whole click
-- wherever ours sits in core's queue.
--
-- The harness builds the engine's list, events.ComponentLClickUp, with core's two-pass
-- dispatcher as its one entry, queues a thrower and the Exchange's record the way EX.init
-- registers it, runs EX.click_first, and walks the engine's list with no protection.
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    get_saved_value = function() return nil end,
    callback = function() end,
}
core = { event_listeners = {}, add_listener = function() end }
function out() end
dofile([[%s]])

local q = {}
core.event_listeners.ComponentLClickUp = q
events = { ComponentLClickUp = { function(context)
    local go = {}
    for _, l in ipairs(core.event_listeners.ComponentLClickUp) do
        if l.condition == true or l.condition(context) then go[#go + 1] = l end
    end
    for _, l in ipairs(go) do l.callback(context) end
end } }
local throws = true
q[#q + 1] = { name = "stranger_throws", callback = function() end, condition = function()
    if throws then error("another mod's click condition") end
    return false
end }
q[#q + 1] = { name = "zharr_exchange_click", condition = true, callback = EX.click_safe }
EX.click_first("zharr_exchange_click")

-- Then a click the stranger lets through: a copy left in core's queue would run it twice.
local seen = 0
EX.click_dispatch = function() seen = seen + 1 end
for _, t in ipairs({ true, false }) do
    throws, seen = t, 0
    pcall(function()
        for _, fn in ipairs(events.ComponentLClickUp) do fn({ string = "harness_nothing" }) end
    end)
    print("reached " .. seen)
end

-- AND BEING FIRST MUST NOT MAKE US THE THROWER.
EX.click_dispatch = function() error("dispatch failed") end
print("swallowed " .. tostring(pcall(EX.click_safe, { string = EX.BUTTON })))
