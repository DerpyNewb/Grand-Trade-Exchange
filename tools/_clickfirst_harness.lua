-- Proves the Exchange's click handler still runs when another mod's click handler throws.
--
-- The failure being modelled was reported on 2026-10-09 (a Great Guilds player: "click sound,
-- nothing opens"): since 9.1 lib_core calls listeners unprotected, so a throwing
-- ComponentLClickUp handler unwinds the dispatch loop and every listener queued behind it
-- never runs that click. The Exchange registers at the first tick, behind every listener any
-- mod registered at load.
--
-- The harness queues a thrower, then the Exchange's record the way EX.init registers it, runs
-- EX.click_first, and walks the queue the way lib_core does, with no protection.
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
q[#q + 1] = { name = "stranger_throws", condition = true,
              callback = function() error("another mod's click handler") end }
q[#q + 1] = { name = "zharr_exchange_click", condition = true, callback = EX.click_safe }
EX.click_first("zharr_exchange_click")

local ran = {}
EX.click_dispatch = function() end
pcall(function()
    for _, l in ipairs(q) do
        ran[#ran + 1] = l.name
        l.callback({ string = "harness_nothing" })
    end
end)
local reached = false
for _, n in ipairs(ran) do if n == "zharr_exchange_click" then reached = true end end
print("reached " .. tostring(reached))

-- AND BEING FIRST MUST NOT MAKE US THE THROWER.
EX.click_dispatch = function() error("dispatch failed") end
print("swallowed " .. tostring(pcall(EX.click_safe, { string = EX.BUTTON })))
