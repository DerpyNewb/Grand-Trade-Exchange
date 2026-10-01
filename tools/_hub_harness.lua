-- THE DERPY HUD HUB under Lua 5.1, against a stub UI. Run from the workspace root:
--     lua.exe tools/_hub_harness.lua                    the source
--     lua.exe tools/_hub_harness.lua a.lua b.lua c.lua  shipped copies, in load order
-- Prints ok/FAIL per check and exits 1 on any FAIL.
--
-- HOVER IS THE MOUSE, NOT AN EVENT. The first design opened on ComponentMouseOn and did not
-- open in game (2026-10-01: "hover doesnt work still need to click"). The hub now polls
-- IsMouseOverChildren, so these checks move a stub mouse and run the poll; no MouseOn/Off is
-- ever fired, and a hub that depended on one would fail here.
local FILES = {}
for i = 1, #arg do FILES[#FILES + 1] = arg[i] end
if #FILES == 0 then FILES = {"Modding Files/source/derpy_hub/derpy_hud_hub.lua"} end
local SOURCE = FILES[1]

local fails = 0
local function check(what, fn)
    local ok, err = pcall(fn)
    if ok then print("ok   " .. what)
    else fails = fails + 1; print("FAIL " .. what .. ": " .. tostring(err)) end
end

local W
local function new_comp(name, w, h)
    local c = {name = name, x = 0, y = 0, w = w, h = h, vis = true, moves = 0,
               pulse = {}, shader = nil, tip = nil, tips = 0, mouse = false, alpha = 255,
               sizable = 0}
    function c:Position() return self.x, self.y end
    function c:Address() return self end
    function c:SetOpacity(a, all)
        assert(all == true, "SetOpacity without all states leaves the hover state opaque")
        self.alpha = a
    end
    function c:SetCanResizeWidth(on) if on then self.sizable = self.sizable + 1 end end
    function c:SetCanResizeHeight(on) if on then self.sizable = self.sizable + 1 end end
    function c:Resize(w, h, kids)
        assert(self.sizable >= 2, "Resize before SetCanResizeWidth/Height(true)")
        assert(kids == false, "Resize without false rescales the children too")
        self.w, self.h = w, h
    end
    function c:Dimensions() return self.w, self.h end
    function c:MoveTo(x, y) self.x, self.y, self.moves = x, y, self.moves + 1 end
    function c:SetVisible(v)
        assert(type(v) == "boolean", "SetVisible needs a boolean, got " .. type(v))
        self.vis = v
    end
    function c:Visible() return self.vis end
    function c:Id() return self.name end
    function c:SetTooltipText(t) self.tip, self.tips = t, self.tips + 1 end
    function c:ShaderTechniqueSet(t) self.shader = t end
    function c:ShaderVarsSet() end
    -- The ENGINE answers this from where the cursor is, whether or not the component is
    -- drawn; the hub must ask Visible itself.
    function c:IsMouseOverChildren() return self.mouse end
    -- THE GETTERS THAT CRASH THE GAME ON A HUD BUTTON. Any call fails the check.
    function c:GetTooltipText() error("GetTooltipText on a HUD button hard-crashes the game") end
    function c:GetImagePath() error("GetImagePath on a HUD button hard-crashes the game") end
    return c
end

-- resources_bar as measured live, 1920x1080, settled: 431,-4 1019x60.
local function reset(sw)
    W = {comps = {}, repeats = {}, listeners = {}, ticks = {}, timers = {},
         bar = {x = 431, y = -4, w = 1019, h = 60}, sw = sw or 1920, sh = 1080,
         created = 0, path = nil, paths = {}, kids = {}}
    W.comps.resources_bar = {
        Position = function() return W.bar.x, W.bar.y end,
        Dimensions = function() return W.bar.w, W.bar.h end,
        Id = function() return "resources_bar" end,
    }
    W.kids[1] = W.comps.resources_bar
    -- THE ROOT'S CHILD LIST IS THE DRAW ORDER: a later child draws over an earlier one.
    local root = {
        CreateComponent = function(_, name, path)
            W.created, W.path = W.created + 1, path
            W.paths[name] = path
            W.comps[name] = new_comp(name, 48, 48)
            W.kids[#W.kids + 1] = W.comps[name]
        end,
        ChildCount = function() return #W.kids end,
        Find = function(_, i) return W.kids[i + 1] end,          -- 0-based, as the engine
        Adopt = function(_, c, at)
            for i, k in ipairs(W.kids) do
                if k == c then table.remove(W.kids, i) break end
            end
            table.insert(W.kids, (at or -1) < 0 and #W.kids + 1 or at + 1, c)
        end,
    }
    UIComponent = function(address) return address end
    core = {
        get_ui_root = function() return root end,
        get_screen_resolution = function() return W.sw, W.sh end,
        add_listener = function(_, name, event, cond, fn)
            W.listeners[#W.listeners + 1] = {name = name, event = event, cond = cond, fn = fn}
        end,
    }
    cm = {
        add_first_tick_callback = function(_, fn) W.ticks[#W.ticks + 1] = fn end,
        repeat_real_callback = function(_, fn, ms, name)
            W.repeats[#W.repeats + 1] = {fn = fn, ms = ms, name = name}
        end,
        -- One-shots are kept, in the order they are due, and run by frame()/frames().
        real_callback = function(_, fn, ms, name)
            assert(type(ms) == "number" and ms > 0, "a one-shot with no delay")
            W.timers[#W.timers + 1] = {fn = fn, ms = ms, name = name, n = #W.timers}
            table.sort(W.timers, function(a, b)
                if a.ms ~= b.ms then return a.ms < b.ms end
                return a.n < b.n
            end)
        end,
        remove_real_callback = function() error("remove_real_callback leaks in CA's timer_manager") end,
    }
    -- false, not nil, for an absent component: that is what the engine returns.
    find_uicomponent = function(_root, name) return W.comps[name] or false end
    is_uicomponent = function(c) return type(c) == "table" and c.Position ~= nil end
    pulse_uicomponent = function(c, on, _s, _p, state) c.pulse[state or "?"] = on end
    DERPY_HUB, DERPY_HUB_QUEUE = nil, nil
end

local function load_text(path) return assert(io.open(path, "rb")):read("*a") end
local function load_chunk(text, name) assert(loadstring(text, name))() end
local function load_files(list) for _, f in ipairs(list) do load_chunk(load_text(f), f) end end
local function first_tick() for _, fn in ipairs(W.ticks) do fn() end end
-- ONE POLL, through the registered callback when there is one, so a hub that never starts
-- its poll fails rather than being driven by hand. Errors are not swallowed here: the
-- callback pcalls, so the tick is called directly when the poll exists to surface them.
local function tick()
    assert(#W.repeats == 1, "no poll registered")
    DERPY_HUB.tick()
end
local function poll_ms() return W.repeats[1].ms end
local function fire(event, id)
    for _, l in ipairs(W.listeners) do
        local ctx = {string = id}
        if l.event == event and (l.cond == true or l.cond(ctx)) then l.fn(ctx) end
    end
end
-- Put the mouse over one component (or none), the way the cursor is over exactly one thing.
local function mouse(name)
    for n, c in pairs(W.comps) do
        if type(c) == "table" and c.mouse ~= nil then c.mouse = (n == name) end
    end
end
-- Ticks the poll for `ms` of real time, rounding up.
local function wait(ms)
    for _ = 1, math.ceil(ms / poll_ms()) do tick() end
end
local function button(name, size)
    W.comps[name] = new_comp(name, size, size)
    W.kids[#W.kids + 1] = W.comps[name]
    return W.comps[name]
end
-- The next one-shot that falls due, or all of them.
local function frame()
    local t = table.remove(W.timers, 1)
    if t then t.fn() end
    return t
end
local function frames() while frame() do end end
local function index_of(c)
    for i, k in ipairs(W.kids) do if k == c then return i end end
end
local function register(key, name, order, extra)
    DERPY_HUB_QUEUE = DERPY_HUB_QUEUE or {}
    local r = {key = key, button = name, order = order,
               label = function() return "Mod " .. key end}
    for k, v in pairs(extra or {}) do r[k] = v end
    table.insert(DERPY_HUB_QUEUE, r)
    return r
end
-- Expected geometry, written out here and not read from DERPY_HUB, so a slip in the hub
-- cannot agree with itself. Hub: 431 + 1019 + 4 = 1454, y = -4 + (60 - 48) / 2 = 2.
-- The column hangs under it, one 4px gap apart, each button centred on the hub's 48px.
local HUB_X, HUB_Y = 1454, 2
local COL_Y = HUB_Y + 48 + 4                       -- 54
local function x_for(size) return HUB_X + math.floor((48 - size) / 2) end
-- The plate: from the hub's middle to PAD under the last button, PAD either side.
-- panel_stack's frame line is ~9px inside its box, so 14 shows ~5px of frame round them.
local PAD = 14
local PLATE_X, PLATE_Y = HUB_X - PAD, HUB_Y + 24
-- Closing waits at most this long after the mouse leaves (the author, 2026-10-01: "thers
-- also a delay when hovering out of the ui" - it was 500ms).
local GRACE = 100

-- A standard world: the source loaded, first tick run, three mods registered.
local function world(opts)
    opts = opts or {}
    reset(opts.sw)
    if opts.register_first then
        register("ex", "ex_btn", 3); register("ic", "ic_btn", 1); register("gg", "gg_btn", 2)
    end
    load_files(opts.files or {SOURCE})
    if not opts.register_first then
        register("ex", "ex_btn", 3); register("ic", "ic_btn", 1); register("gg", "gg_btn", 2)
    end
    first_tick()
    if opts.ic ~= false then button("ic_btn", 44) end
    if opts.gg ~= false then button("gg_btn", 44) end
    if opts.ex ~= false then button("ex_btn", 48) end
end

check("the poll is started once, on the UI clock, fast enough for a hover", function()
    world()
    assert(#W.repeats == 1, "expected one poll, got " .. #W.repeats)
    assert(W.repeats[1].name == "derpy_hub_poll", "poll named " .. tostring(W.repeats[1].name))
    assert(W.repeats[1].ms <= 150, "a hover would take " .. W.repeats[1].ms .. "ms to open")
end)

check("newest wins: an older copy loaded first or last never serves", function()
    local src = load_text(SOURCE)
    local v = tonumber(src:match("local HUB_VERSION = (%d+)"))
    assert(v, "the source must declare local HUB_VERSION = <integer>")
    local newer = src:gsub("local HUB_VERSION = %d+", "local HUB_VERSION = " .. (v + 1), 1)
    for _, order in ipairs({{src, newer}, {newer, src}}) do
        reset()
        load_chunk(order[1], "first"); load_chunk(order[2], "second")
        assert(DERPY_HUB.version == v + 1, "the hub serving is version " .. DERPY_HUB.version)
        first_tick()
        assert(#W.repeats == 1, "two copies both started a poll: " .. #W.repeats)
        assert(#W.listeners == 1, "listeners registered: " .. #W.listeners .. ", want 1")
    end
end)

check("equal versions: the first loaded serves and only it starts", function()
    reset()
    local src = load_text(SOURCE)
    load_chunk(src, "a")
    local first = DERPY_HUB
    load_chunk(src, "b")
    assert(DERPY_HUB == first, "a second copy of the same version replaced the first")
    first_tick()
    assert(#W.repeats == 1 and #W.listeners == 1, "start ran more than once")
end)

check("the queue works whichever loads first, the mods or the hub", function()
    for _, before in ipairs({true, false}) do
        world({register_first = before})
        tick()
        assert(DERPY_HUB.manages("ic") and DERPY_HUB.manages("gg") and DERPY_HUB.manages("ex"),
               "registered before=" .. tostring(before) .. ": not all three managed")
    end
end)

check("one button: no hub, no moves, no hiding", function()
    world({gg = false, ex = false})
    tick()
    assert(W.created == 0, "a hub was made for one button")
    assert(not DERPY_HUB.manages("ic"), "the hub claimed the only button")
    assert(W.comps.ic_btn.moves == 0 and W.comps.ic_btn.vis == true, "the lone button was touched")
end)

check("one registration only: no hub", function()
    reset(); load_files({SOURCE}); register("ex", "ex_btn", 3); first_tick()
    button("ex_btn", 48)
    tick()
    assert(W.created == 0 and not DERPY_HUB.manages("ex"), "a hub of one")
end)

check("two buttons: the hub in the strip slot, a column under it, hidden until hovered",
      function()
    world({gg = false})
    tick()
    local hub = W.comps.derpy_hub
    assert(hub, "no hub created")
    assert(W.path and W.path:find("^ui/campaign ui/derpy_hub_"), "hub file path " .. tostring(W.path))
    assert(hub.x == HUB_X and hub.y == HUB_Y, "hub at " .. hub.x .. "," .. hub.y)
    assert(hub.vis == true, "the hub was never shown")
    assert(W.comps.ic_btn.vis == false and W.comps.ex_btn.vis == false, "the column shows unhovered")
    local ic, ex = W.comps.ic_btn, W.comps.ex_btn
    assert(ic.x == x_for(44) and ic.y == COL_Y, "ic at " .. ic.x .. "," .. ic.y)
    assert(ex.x == x_for(48) and ex.y == COL_Y + 44 + 4, "ex at " .. ex.x .. "," .. ex.y)
end)

check("three buttons: the column in registration order, not queue order", function()
    world()
    tick()
    local ic, gg, ex = W.comps.ic_btn, W.comps.gg_btn, W.comps.ex_btn
    assert(ic.y == COL_Y and ic.x == x_for(44), "ic at " .. ic.x .. "," .. ic.y)
    assert(gg.y == COL_Y + 48 and gg.x == x_for(44), "gg at " .. gg.x .. "," .. gg.y)
    assert(ex.y == COL_Y + 96 and ex.x == x_for(48), "ex at " .. ex.x .. "," .. ex.y)
end)

check("a missing button component is skipped and closes the gap", function()
    world({gg = false})
    tick()
    assert(not DERPY_HUB.manages("gg"), "the hub claims a button that does not exist")
    assert(W.comps.ex_btn.y == COL_Y + 48, "ex did not close the gap: " .. W.comps.ex_btn.y)
end)

check("hover: the mouse on the hub opens the column within one poll", function()
    world()
    tick()
    mouse("derpy_hub")
    tick()
    assert(W.comps.ic_btn.vis and W.comps.gg_btn.vis and W.comps.ex_btn.vis,
           "the mouse is on the hub and the column is shut")
end)

check("hover: the column and the plate between its buttons keep it open; leaving shuts it fast",
      function()
    world()
    tick()
    mouse("derpy_hub"); tick()
    frames()
    for _, over in ipairs({"gg_btn", "derpy_hub_plate", "ex_btn"}) do
        mouse(over)                               -- down the column, through a gap
        wait(GRACE * 3)
        frames()                                  -- a fold, had one begun, runs out here
        assert(W.comps.ic_btn.vis, "the column closed with the mouse on " .. over)
    end
    mouse(nil)
    wait(GRACE)
    assert(#W.timers > 0, "the fold had not begun " .. GRACE .. "ms after the mouse left")
    frames()
    assert(not W.comps.ic_btn.vis and not W.comps.ex_btn.vis, "the column stayed open")
    assert(not W.comps.derpy_hub_plate.vis, "the plate stayed up with the column shut")
end)

check("the plate: made once, hidden while shut, framing hub and column, drawn behind them",
      function()
    world()
    tick()
    local plate = W.comps.derpy_hub_plate
    assert(plate, "no plate created")
    assert(W.paths.derpy_hub_plate and W.paths.derpy_hub_plate:find("^ui/campaign ui/derpy_hub_plate_"),
           "plate file path " .. tostring(W.paths.derpy_hub_plate))
    assert(plate.vis == false, "the plate shows with the column shut")
    for _, n in ipairs({"derpy_hub", "ic_btn", "gg_btn", "ex_btn"}) do
        assert(index_of(plate) < index_of(W.comps[n]), "the plate draws over " .. n)
    end
    mouse("derpy_hub"); tick()
    frames()
    assert(plate.vis == true, "the column is open and the plate is not")
    -- Last button ex (48) at 54 + 48 + 48 = 150, bottom 198; plate to 198 + PAD.
    assert(plate.x == PLATE_X and plate.y == PLATE_Y, "plate at " .. plate.x .. "," .. plate.y)
    assert(plate.w == 48 + 2 * PAD and plate.h == 198 + PAD - PLATE_Y,
           "plate is " .. plate.w .. "x" .. plate.h)
    tick(); tick()
    assert(W.created == 2, "components created: " .. W.created .. ", want the hub and the plate")
end)

check("opening unfolds: from the hub, transparent, to their places, opaque", function()
    world()
    tick()
    local ic, ex = W.comps.ic_btn, W.comps.ex_btn
    mouse("derpy_hub"); tick()
    assert(ic.vis and ic.alpha == 0, "ic opened at alpha " .. ic.alpha)
    assert(ic.y == HUB_Y and ex.y == HUB_Y, "the column did not start at the hub: "
           .. ic.y .. "," .. ex.y)
    assert(#W.timers >= 3, "an unfold of " .. #W.timers .. " frames")
    local last_y, last_a = ex.y, ex.alpha
    while frame() do
        assert(ex.y >= last_y and ex.alpha >= last_a, "the unfold went backwards")
        last_y, last_a = ex.y, ex.alpha
    end
    assert(ic.y == COL_Y and ex.y == COL_Y + 96, "unfolded to " .. ic.y .. "," .. ex.y)
    assert(ic.alpha == 255 and ex.alpha == 255 and W.comps.derpy_hub_plate.alpha == 255,
           "the unfold ended translucent")
    for _, t in ipairs(W.timers) do error("a frame left over: " .. tostring(t.name)) end
end)

check("hovering out folds: back into the hub, fading, then hidden at full alpha", function()
    -- The author, 2026-10-01: "there should also be a hovering out animation".
    world()
    tick()
    local ic, ex, plate = W.comps.ic_btn, W.comps.ex_btn, W.comps.derpy_hub_plate
    mouse("derpy_hub"); tick()
    frames()
    mouse(nil); tick()
    assert(ex.vis and plate.vis, "the column vanished instead of folding")
    assert(#W.timers >= 3, "a fold of " .. #W.timers .. " frames")
    local last_y, last_a, last_h = ex.y, ex.alpha, plate.h
    while #W.timers > 1 do
        frame()
        assert(ex.vis, "hidden before the fold finished")
        assert(ex.y <= last_y and ex.alpha <= last_a and plate.h <= last_h, "the fold went backwards")
        last_y, last_a, last_h = ex.y, ex.alpha, plate.h
    end
    assert(ex.y < COL_Y + 96 and ex.alpha < 255, "the fold never moved or faded")
    frame()
    assert(not ic.vis and not ex.vis and not plate.vis, "the fold ended with the column up")
    assert(ic.alpha == 255 and ex.alpha == 255 and plate.alpha == 255,
           "the fold left a hidden button translucent")
    tick()
    assert(not ex.vis and ex.y == COL_Y + 96, "the shut column was not put back in place")
end)

check("back on the hub mid-fold: it unfolds again from where it got to, never hidden", function()
    world()
    tick()
    local ex = W.comps.ex_btn
    mouse("derpy_hub"); tick()
    frames()
    mouse(nil); tick()
    frame(); frame()
    local y, a = ex.y, ex.alpha
    mouse("derpy_hub"); tick()
    assert(ex.vis and ex.y == y and ex.alpha == a, "the reopen jumped instead of turning round")
    while frame() do
        assert(ex.vis, "the old fold hid the reopened column")
    end
    assert(ex.y == COL_Y + 96 and ex.alpha == 255, "did not unfold back: " .. ex.y .. " a" .. ex.alpha)
end)

check("a shut mid-unfold folds from there; a reopen after the fold starts from the hub",
      function()
    world()
    tick()
    local ic = W.comps.ic_btn
    mouse("derpy_hub"); tick()
    frame()
    local a = ic.alpha
    mouse(nil); tick()
    frame()
    assert(ic.alpha < a, "the late unfold frames kept fading in during the fold")
    frames()
    assert(not ic.vis and ic.alpha == 255, "the fold did not finish")
    mouse("derpy_hub"); tick()
    assert(ic.alpha == 0 and ic.y == HUB_Y, "the reopen did not restart the unfold")
    frames()
    assert(ic.alpha == 255 and ic.y == COL_Y, "the reopen did not finish")
end)

check("hover on something else, or on a hidden column button, opens nothing", function()
    world()
    tick()
    mouse("resources_bar"); tick()
    assert(not W.comps.ic_btn.vis, "an unrelated hover opened the column")
    mouse("ic_btn"); tick()                       -- where the hidden button sits
    assert(not W.comps.ic_btn.vis, "a hidden column button counted as hovered")
end)

check("a click on the hub opens the column at once", function()
    world()
    tick()
    fire("ComponentLClickUp", "derpy_hub")
    assert(W.comps.ic_btn.vis and W.comps.gg_btn.vis and W.comps.ex_btn.vis, "click did not open")
end)

check("the hub's tooltip names the mods in column order, written once per hover", function()
    world()
    DERPY_HUB_QUEUE[1].label = function() error("loc failed") end   -- ex's label throws
    tick()
    mouse("derpy_hub")
    wait(GRACE)
    local hub = W.comps.derpy_hub
    assert(hub.tip == "Mod ic\nMod gg\nex", "tip was " .. tostring(hub.tip))
    assert(hub.tips == 1, "the tooltip was rewritten " .. hub.tips .. " times in one hover")
end)

check("grey only when every managed button is grey; a throwing probe fails open", function()
    world()
    local ic, gg, ex = DERPY_HUB_QUEUE[2], DERPY_HUB_QUEUE[3], DERPY_HUB_QUEUE[1]
    ic.live = function() return false end
    gg.live = function() return false end
    ex.live = function() return true end
    tick()
    assert(W.comps.derpy_hub.shader ~= "set_greyscale_t0", "greyed while the Exchange is live")
    ex.live = function() return false end
    tick()
    assert(W.comps.derpy_hub.shader == "set_greyscale_t0", "not greyed with every button grey")
    ex.live = function() error("probe failed") end
    tick()
    assert(W.comps.derpy_hub.shader == "normal_t0", "a throwing live() greyed the hub")
end)

check("the hub pulses while any managed mod wants attention, in both states", function()
    world()
    DERPY_HUB_QUEUE[2].wants = function() return true end
    tick()
    local p = W.comps.derpy_hub.pulse
    assert(p.standard == true and p.hover == true, "no pulse while the court waits")
    DERPY_HUB_QUEUE[2].wants = function() return false end
    tick()
    assert(p.standard == false and p.hover == false, "the pulse was never stopped")
end)

check("unsettled strip: everything stays hidden and unmoved until it settles", function()
    world()
    W.bar.y = -600
    tick()
    assert(W.comps.derpy_hub and W.comps.derpy_hub.vis == false, "hub shown off a sliding strip")
    assert(not W.comps.ic_btn.vis and W.comps.ic_btn.moves == 0, "column shown or moved mid-slide")
    W.bar.y = -4
    tick()
    assert(W.comps.derpy_hub.vis == true and W.comps.derpy_hub.x == HUB_X, "not placed once settled")
end)

check("the hub and column follow the strip's end, and an unchanged strip is no MoveTo",
      function()
    world()
    tick()
    W.bar.w = W.bar.w + 50
    tick()
    assert(W.comps.derpy_hub.x == HUB_X + 50, "did not follow: " .. W.comps.derpy_hub.x)
    assert(W.comps.ic_btn.x == x_for(44) + 50, "the column did not follow the hub")
    local n = W.comps.derpy_hub.moves
    tick()
    assert(W.comps.derpy_hub.moves == n, "MoveTo every tick on an unchanged strip")
end)

check("narrow screen: the hub clamps onto it and the column stays under the hub", function()
    world({sw = 1480})
    tick()
    local hub = W.comps.derpy_hub
    assert(hub.x == 1480 - 48, "hub at " .. hub.x)
    assert(W.comps.ic_btn.x == hub.x + 2 and W.comps.ex_btn.x == hub.x, "the column left the hub")
end)

check("show_hud: a hidden hovered button counts as left, and nothing hidden is re-shown",
      function()
    world()
    tick()
    W.comps.ic_btn.vis = true                    -- ICUI.show_hud(true) restoring it, closed
    tick()
    assert(W.comps.ic_btn.vis == false, "a restored column button stayed up with it closed")
    mouse("derpy_hub"); tick()
    frames()
    mouse("ic_btn"); tick()                      -- open, mouse on the court's button
    local plate = W.comps.derpy_hub_plate
    -- The court opens: show_hud(false) hides every visible root child, plate included.
    W.comps.ic_btn.vis, W.comps.derpy_hub.vis, plate.vis = false, false, false
    wait(GRACE)
    frames()                                     -- the fold runs out under the court
    assert(W.comps.ic_btn.vis == false and W.comps.derpy_hub.vis == false and plate.vis == false,
           "the poll re-showed what the court hid")
    assert(W.comps.gg_btn.vis == false, "the column stayed open under the court")
    -- The court closes: restore, mouse still where the plate is.
    W.comps.ic_btn.vis, W.comps.derpy_hub.vis, plate.vis = true, true, true
    mouse("derpy_hub_plate")
    tick()
    assert(W.comps.ic_btn.vis == false and plate.vis == false,
           "the column came back open after the court closed")
end)

check("release: down to one button, the hub goes and the button is handed back", function()
    world({gg = false})
    tick()
    mouse("derpy_hub"); tick()
    frame()                                       -- mid-unfold, translucent
    W.comps.ex_btn = nil
    tick()
    frames()
    assert(not DERPY_HUB.manages("ic"), "still managing after release")
    assert(W.comps.derpy_hub.vis == false, "the hub stayed up")
    assert(W.comps.derpy_hub_plate.vis == false, "the plate stayed up")
    assert(W.comps.ic_btn.vis == true, "the handed-back button stayed hidden")
    assert(W.comps.ic_btn.alpha == 255, "handed back at alpha " .. W.comps.ic_btn.alpha)
end)

check("released mid-fold, then hubbed again: the column still opens", function()
    world()
    tick()
    mouse("derpy_hub"); tick()
    frames()
    mouse(nil); tick()
    frame()                                       -- folding
    local ex = W.comps.ex_btn
    W.comps.ex_btn, W.comps.gg_btn = nil, nil
    tick()                                        -- one button left: released
    frames()
    W.comps.ex_btn, W.comps.gg_btn = ex, button("gg_btn", 44)
    tick()
    assert(not W.comps.ic_btn.vis and not ex.vis, "hubbed again, the column shows unhovered")
    mouse("derpy_hub"); tick()
    frames()
    assert(W.comps.ic_btn.vis and ex.vis, "after a release mid-fold the column never opens")
    assert(ex.alpha == 255 and ex.y == COL_Y + 96, "it opened at alpha " .. ex.alpha .. " y" .. ex.y)
end)

check("no resources_bar at all: the hub manages nothing and the mods keep their own way in",
      function()
    world()
    W.comps.resources_bar = nil
    tick()
    assert(not DERPY_HUB.manages("ic") and not DERPY_HUB.manages("ex"),
           "with no strip the hub claimed buttons it can never show")
    assert(W.comps.ic_btn.vis and W.comps.ic_btn.moves == 0, "a mod's button was hidden or moved")
end)

check("manages() is false before the first tick and for an unknown key", function()
    reset(); load_files({SOURCE})
    assert(DERPY_HUB.manages("ic") == false and DERPY_HUB.manages("nope") == false)
end)

check("every listed file loads, and exactly one hub starts", function()
    reset()
    load_files(FILES)
    first_tick()
    assert(#W.repeats == 1 and #W.listeners == 1, "polls " .. #W.repeats .. ", listeners "
           .. #W.listeners)
end)

if fails > 0 then print(fails .. " FAILED"); os.exit(1) end
print("all hub checks passed")
