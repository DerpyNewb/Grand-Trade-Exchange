-- Proves the mod still starts when CA's first-tick callback list never runs.
--
-- The failure being modelled is real and was measured on 2026-09-07: cm's five first-tick
-- lists are walked by call_each, which has no pcall, so one throwing callback belonging to any
-- other mod ends the pass and every callback after it never runs. This file is zzz_*, so it is
-- last in that list.
--
-- The harness therefore fires ONLY the ScriptEventFirstTickAfterWorldCreated listener and asks
-- whether the body ran, then fires the first-tick callbacks and asks whether it ran AGAIN.
local TICKS, LISTEN = {}, {}
cm = {
    add_first_tick_callback = function(_, f) TICKS[#TICKS + 1] = f end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    get_saved_value = function() return nil end,
    callback = function() end,
}
core = {
    add_listener = function(_, name, event, _cond, cb, _p)
        LISTEN[#LISTEN + 1] = { name = name, event = event, cb = cb }
    end,
}
function out() end
dofile([[%s]])

local ft
for _, l in ipairs(LISTEN) do
    if l.event == "ScriptEventFirstTickAfterWorldCreated" then ft = l end
end
print("listener " .. tostring(ft ~= nil))
print("tick_registrations " .. #TICKS)

-- EX.rescan is the body's FIRST statement. Counting it and then throwing is what lets this
-- measure entry into the body without stubbing a whole campaign model behind it - and the
-- throw is also what a real first-tick failure looks like from outside.
local body = 0
EX.rescan = function()
    body = body + 1
    error("harness stop")
end

if ft then pcall(function() ft.cb({}) end) end
print("after_listener " .. body)

-- AND THE OTHER ROUTE MUST NOT RUN IT TWICE. On a healthy machine both entry points fire;
-- without the EX.inited guard that is two rescans, two discovery walks and a second set of
-- click listeners on the same buttons.
for _, f in ipairs(TICKS) do pcall(f) end
print("after_tick " .. body)
