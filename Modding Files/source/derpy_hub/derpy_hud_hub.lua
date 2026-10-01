-- THE DERPY HUD HUB. With two or three of the Iron Court, the Great Guilds and the Zharr
-- Exchange installed, one button sits in the slot beside the resource strip and shows the
-- mods' own buttons in a column on a plate under it while the mouse is over it. With one installed, nothing here
-- does anything. Spec: docs/superpowers/specs/2026-10-01-derpy-hud-hub-design.md.
--
-- ONE SOURCE, THREE SHIPPED COPIES. Edit Modding Files/source/derpy_hub/derpy_hud_hub.lua
-- only. tools/sync_derpy_hub.py writes script/campaign/mod/derpy_hub_<tag>.lua into each mod
-- under its own path, so every installed copy loads. The highest HUB_VERSION serves all of
-- them; raise it on any behaviour change.
--
-- THE CONTRACT EVERY VERSION KEEPS, because a mod built against an older hub calls it on a
-- newer one: DERPY_HUB.version (integer), DERPY_HUB.manages(key) -> boolean, and the
-- DERPY_HUB_QUEUE entry {key, button, order, label = fn, live = fn, wants = fn}.
--
-- UI-ONLY AND LOCAL: nothing here touches the model or the save, so it cannot desync
-- multiplayer. It moves, hides and shows the mods' buttons and nothing else. Each mod keeps
-- its button's creation, click, tooltip, greying and pulse.
local HUB_VERSION = 4            -- 4: the column folds away as well as out; a baked plate
local HUB_TAG = "src"            -- rewritten per copy by tools/sync_derpy_hub.py

local HUB = {
    version = HUB_VERSION,
    PATH = "ui/campaign ui/derpy_hub_" .. HUB_TAG,
    NAME = "derpy_hub",
    PLATE = "derpy_hub_plate",
    PLATE_PATH = "ui/campaign ui/derpy_hub_plate_" .. HUB_TAG,
    PAD = 14,                    -- plate box past the buttons; its frame line is ~9px in
    PLATE_MIN = 56,              -- panel_stack's nine-slice margins add to 52 (sync_derpy_hub)
    SIZE = 48,                   -- must match HUB_W/HUB_H in tools/sync_derpy_hub.py
    GAP = 4,                     -- EX.BUTTON_GAP, the gap the openers already keep
    POLL_MS = 100,               -- hover is polled, so this is how fast the column opens
    -- Shut on the first poll that finds the mouse gone. The plate fills the gaps between
    -- buttons, so nothing needs crossing; 500ms was felt as a lag (author, 2026-10-01).
    GRACE_MS = 100,
    ANIM_STEPS = 5,              -- the unfold: five frames, 25ms apart
    ANIM_MS = 25,
    PULSE = 5,                   -- ICUI.PULSE_STRENGTH, the court's own look
    managed = {},                -- key -> true while the hub owns that button
    row = {},                    -- {reg, c} for each managed button, column order
    open = false,
    away = 0,                    -- ms since the mouse was last over the hub or the column
    last_over = nil,             -- what the mouse was over at the previous poll
    anim = 1,                    -- 0 folded into the hub .. 1 in place
    anim_gen = 0,                -- bumped on every open and shut; a late frame is void
    folding = false,             -- shut, but still visible while it folds into the hub
    plate_w = nil,
    plate_h = nil,
    placed = false,
    grey = nil,
    pulsing = nil,
    started = false,
}

function HUB.manages(key)
    return HUB.managed[key] == true
end

-- A probe that throws or answers a non-boolean gets the default: fail open.
local function ask(fn, default)
    if type(fn) ~= "function" then return default end
    local ok, v = pcall(fn)
    if not ok or type(v) ~= "boolean" then return default end
    return v
end

-- The newest registration per key, in column order. The queue is a plain table, so a mod that
-- loads before or after every hub copy is seen either way.
function HUB.registrations()
    local by_key, out = {}, {}
    for _, r in ipairs(DERPY_HUB_QUEUE or {}) do
        if type(r) == "table" and r.key and r.button then by_key[r.key] = r end
    end
    for _, r in pairs(by_key) do out[#out + 1] = r end
    table.sort(out, function(a, b)
        local oa, ob = a.order or 0, b.order or 0
        if oa ~= ob then return oa < ob end
        return a.key < b.key
    end)
    return out
end

-- Only buttons that EXIST count: the court makes none for a faction with no court, the
-- Guilds none for a race with no guilds, and a hub of one is no hub.
function HUB.present(root)
    local out = {}
    for _, r in ipairs(HUB.registrations()) do
        local c = find_uicomponent(root, r.button)
        if is_uicomponent(c) then out[#out + 1] = {reg = r, c = c} end
    end
    return out
end

-- Created hidden: placed at the root's origin until the strip settles, it would draw in
-- the corner of the screen.
function HUB.button(root)
    local hub = find_uicomponent(root, HUB.NAME)
    if is_uicomponent(hub) then return hub end
    pcall(function() root:CreateComponent(HUB.NAME, HUB.PATH) end)
    hub = find_uicomponent(root, HUB.NAME)
    if not is_uicomponent(hub) then return nil end
    hub:SetVisible(false)
    HUB.placed, HUB.grey, HUB.pulsing = false, nil, nil
    return hub
end

-- THE PLATE BEHIND THE COLUMN (author, 2026-10-01: "no background ui"): CA's panel_stack,
-- nine-sliced. Interactive, so IsMouseOverChildren answers over the gaps between buttons.
-- The root draws its children in list order, so the plate is adopted in front of the hub
-- and every button already made; one made later lands after it anyway. Compared by Id, not
-- by ==: the engine hands back a fresh wrapper per lookup.
function HUB.plate(root, here)
    local plate = find_uicomponent(root, HUB.PLATE)
    if is_uicomponent(plate) then return plate end
    pcall(function() root:CreateComponent(HUB.PLATE, HUB.PLATE_PATH) end)
    plate = find_uicomponent(root, HUB.PLATE)
    if not is_uicomponent(plate) then return nil end
    plate:SetVisible(false)
    HUB.plate_w, HUB.plate_h = nil, nil
    pcall(function()
        plate:SetCanResizeWidth(true)
        plate:SetCanResizeHeight(true)
    end)
    pcall(function()
        local ours = {[HUB.NAME] = true}
        for _, e in ipairs(here) do ours[e.reg.button] = true end
        for i = 0, root:ChildCount() - 1 do
            if ours[UIComponent(root:Find(i)):Id()] then
                root:Adopt(plate:Address(), i)
                break
            end
        end
    end)
    return plate
end

-- The strip is the ruler, read the way the openers read it: resources_bar is the art,
-- Dimensions not Bounds, and a far-negative y means it is sliding in or away.
function HUB.anchor(root)
    local bar = find_uicomponent(root, "resources_bar")
    if not is_uicomponent(bar) then return nil end
    local bx, by = bar:Position()
    local bw, bh = bar:Dimensions()
    if by < -HUB.SIZE then return nil end
    return bx + bw + HUB.GAP, by, bh
end

local function move(c, x, y)
    local ax, ay = c:Position()
    if ax ~= x or ay ~= y then c:MoveTo(x, y) end
end

local function centred(top, bh, h)
    local y = top + math.floor((bh - h) / 2)
    if y < 0 then y = 0 end          -- Cathay's strip settles a few pixels higher
    return y
end

-- The hub in the slot nearest the strip, and the mods' buttons in a COLUMN under it, each
-- centred on the hub (asked for 2026-10-01: "make it by column instead"). The column hangs
-- below the top row, so it cannot run off the side of the screen.
function HUB.place(root, hub, here)
    local x, top, bh = HUB.anchor(root)
    if not x then return end
    local sw = core:get_screen_resolution()
    if x + HUB.SIZE > sw then x = sw - HUB.SIZE end
    local hy = centred(top, bh, HUB.SIZE)
    move(hub, x, hy)
    if not HUB.placed then
        hub:SetVisible(true)
        HUB.placed = true
    end
    -- THE UNFOLD: every button starts at the hub and eases out to its place.
    local t = HUB.anim * (2 - HUB.anim)
    local cy, bottom = hy + HUB.SIZE + HUB.GAP, hy + HUB.SIZE
    for _, e in ipairs(here) do
        local w, h = e.c:Dimensions()
        local y = hy + math.floor((cy - hy) * t + 0.5)
        move(e.c, x + math.floor((HUB.SIZE - w) / 2), y)
        if y + h > bottom then bottom = y + h end
        cy = cy + h + HUB.GAP
    end
    local plate = find_uicomponent(root, HUB.PLATE)
    if is_uicomponent(plate) then
        local py = hy + math.floor(HUB.SIZE / 2)
        local pw = HUB.SIZE + 2 * HUB.PAD
        local ph = math.max(HUB.PLATE_MIN, bottom + HUB.PAD - py)
        if pw ~= HUB.plate_w or ph ~= HUB.plate_h then
            pcall(function() plate:Resize(pw, ph, false) end)
            HUB.plate_w, HUB.plate_h = pw, ph
        end
        move(plate, x - HUB.PAD, py)
    end
end

-- Greyed only when EVERY managed button is grey, and pulsing while ANY wants attention, so
-- a closed column hides nothing. Written only on a change.
function HUB.paint(hub, here)
    local live, wants = false, false
    for _, e in ipairs(here) do
        if ask(e.reg.live, true) then live = true end
        if ask(e.reg.wants, false) then wants = true end
    end
    if wants ~= HUB.pulsing then
        HUB.pulsing = wants
        for _, st in ipairs({"standard", "hover"}) do
            pcall(function() pulse_uicomponent(hub, wants, HUB.PULSE, false, st) end)
        end
    end
    local grey = not live
    if grey ~= HUB.grey then
        HUB.grey = grey
        pcall(function()
            hub:ShaderTechniqueSet(grey and "set_greyscale_t0" or "normal_t0", true, true)
            if grey then hub:ShaderVarsSet(1, 0.6, 0, 0, true, true) end
        end)
    end
end

local function fade(list, plate, a)
    for _, e in ipairs(list) do
        if is_uicomponent(e.c) then pcall(function() e.c:SetOpacity(a, true) end) end
    end
    if is_uicomponent(plate) then pcall(function() plate:SetOpacity(a, true) end) end
end

-- One frame of the unfold or the fold. Void once the column has turned round since it was
-- scheduled. The fold's last frame hides the column and puts its alpha back.
local function anim_frame(gen, a, last)
    if HUB.anim_gen ~= gen then return end
    local root = core:get_ui_root()
    local hub = find_uicomponent(root, HUB.NAME)
    local plate = find_uicomponent(root, HUB.PLATE)
    HUB.anim = a
    fade(HUB.row, plate, math.floor(a * 255 + 0.5))
    if is_uicomponent(hub) then HUB.place(root, hub, HUB.row) end
    if last and HUB.folding then
        HUB.folding, HUB.anim = false, 1
        fade(HUB.row, plate, 255)
        for _, e in ipairs(HUB.row) do
            if is_uicomponent(e.c) then e.c:SetVisible(false) end
        end
        if is_uicomponent(plate) then plate:SetVisible(false) end
    end
end

-- From wherever the column is to `to` (1 out, 0 folded) in ANIM_STEPS one-shot frames. They
-- clear themselves; never remove_real_callback (lib_timer_manager.lua:590 leaks a record).
local function animate(to)
    HUB.anim_gen = HUB.anim_gen + 1
    local gen, from = HUB.anim_gen, HUB.anim
    for k = 1, HUB.ANIM_STEPS do
        local a = from + (to - from) * k / HUB.ANIM_STEPS
        cm:real_callback(function() pcall(anim_frame, gen, a, k == HUB.ANIM_STEPS) end,
                         k * HUB.ANIM_MS, "derpy_hub_anim")
    end
end

-- OPEN UNFOLDS OUT OF THE HUB, SHUT FOLDS BACK INTO IT (author, 2026-10-01: "there should also
-- be a hovering out animation"). Either turns round mid-way from where the column got to.
function HUB.show_row(on)
    HUB.away = 0
    if not on then
        HUB.open, HUB.folding = false, true
        animate(0)
        return
    end
    local fresh = not HUB.open and not HUB.folding
    HUB.open, HUB.folding = true, false
    if fresh then
        local root = core:get_ui_root()
        local plate = find_uicomponent(root, HUB.PLATE)
        HUB.anim = 0
        fade(HUB.row, plate, 0)
        local hub = find_uicomponent(root, HUB.NAME)
        if is_uicomponent(hub) then HUB.place(root, hub, HUB.row) end
        if is_uicomponent(plate) then plate:SetVisible(true) end
        for _, e in ipairs(HUB.row) do
            if is_uicomponent(e.c) then e.c:SetVisible(true) end
        end
    end
    animate(1)
end

-- Down to one button: give it back. Its own mod places it again on its next poll or turn.
function HUB.release(root, here)
    if next(HUB.managed) == nil then return end
    HUB.managed, HUB.row = {}, {}
    HUB.open, HUB.folding, HUB.away, HUB.last_over = false, false, 0, nil
    HUB.anim, HUB.anim_gen = 1, HUB.anim_gen + 1
    local plate = find_uicomponent(root, HUB.PLATE)
    fade(here, plate, 255)
    for _, e in ipairs(here) do e.c:SetVisible(true) end
    local hub = find_uicomponent(root, HUB.NAME)
    if is_uicomponent(hub) then hub:SetVisible(false) end
    if is_uicomponent(plate) then plate:SetVisible(false) end
    HUB.placed = false
end

-- IS THE MOUSE ON IT? ASKED, NOT HEARD. ComponentMouseOn/Off were the first design and did
-- not open the column in game (2026-10-01: "hover doesnt work still need to click"): a click
-- reached the hub, a hover did not stay. IsMouseOverChildren is CA's own query ("whether or
-- not the mouse cursor is currently over this uicomponent or any of its children"), called
-- by Workshop mods on CA's own panels, so the poll asks it and no event order matters. A
-- hidden component never counts: the Iron Court's panel hides the HUD under the mouse.
local function mouse_on(c)
    if not c:Visible() then return false end
    local ok, v = pcall(function() return c:IsMouseOverChildren() end)
    return ok and v == true
end

function HUB.over(hub, here, plate)
    if mouse_on(hub) then return hub end
    if HUB.open then
        for _, e in ipairs(here) do
            if mouse_on(e.c) then return e.c end
        end
        if is_uicomponent(plate) and mouse_on(plate) then return plate end
    end
    return nil
end

function HUB.tip()
    local lines = {}
    for _, e in ipairs(HUB.row) do
        local ok, s = pcall(e.reg.label)
        if not ok or type(s) ~= "string" or s == "" then s = e.reg.key end
        lines[#lines + 1] = s
    end
    return table.concat(lines, "\n")
end

-- Open while the mouse is on the hub, the column or the plate between them; folding away
-- GRACE_MS after it has left all of them. Mid-fold only the hub reopens it: the column is
-- shrinking out from under the mouse and must not catch it on the way.
function HUB.hover(hub, here, plate)
    local over = HUB.over(hub, here, plate)
    if over == hub and HUB.last_over ~= hub then
        hub:SetTooltipText(HUB.tip(), true)        -- on hover, a UI moment: loc is safe here
    end
    HUB.last_over = over
    if over then
        if not HUB.open then HUB.show_row(true) end
        HUB.away = 0
    elseif HUB.open then
        HUB.away = HUB.away + HUB.POLL_MS
        if HUB.away >= HUB.GRACE_MS then HUB.show_row(false) end
    end
end

function HUB.tick()
    local root = core:get_ui_root()
    local here = HUB.present(root)
    -- NO STRIP, NO HUB. A CA rename or a HUD mod that drops resources_bar would leave a hub
    -- that is never placed hiding every button it holds; handed back instead, the Exchange
    -- still reaches its faction_buttons_docker fallback.
    if #here < 2 or not is_uicomponent(find_uicomponent(root, "resources_bar")) then
        HUB.release(root, here)
        return
    end
    local managed = {}
    for _, e in ipairs(here) do managed[e.reg.key] = true end
    HUB.managed, HUB.row = managed, here
    local hub = HUB.button(root)
    if not hub then return end
    local plate = HUB.plate(root, here)
    HUB.place(root, hub, here)
    HUB.hover(hub, here, plate)
    if not HUB.open and not HUB.folding then
        if is_uicomponent(plate) and plate:Visible() then plate:SetVisible(false) end
        -- CLOSED MEANS HIDDEN, settled strip or not. This only ever HIDES: the Iron Court's
        -- full-screen panel hides every root child and restores them on close, and a poll
        -- that re-showed would put the column on top of the court.
        for _, e in ipairs(here) do
            if e.c:Visible() then e.c:SetVisible(false) end
        end
    end
    HUB.paint(hub, here)
end

-- A click on the hub opens the column at once; the poll keeps it open while the mouse stays.
function HUB.on_click()
    if next(HUB.managed) == nil then return end
    if not HUB.open then HUB.show_row(true) end
    HUB.away = 0
end

function HUB.start()
    if HUB.started then return end
    HUB.started = true
    core:add_listener("derpy_hub_click", "ComponentLClickUp",
        function(context) return context.string == HUB.NAME end,
        function() HUB.on_click() end, true)
    cm:repeat_real_callback(function() pcall(HUB.tick) end, HUB.POLL_MS, "derpy_hub_poll")
end

-- THE NEWEST COPY WINS. Strictly newer replaces, so of two equal copies the first loaded
-- serves. Only the serving copy starts, and only once.
if not DERPY_HUB or (DERPY_HUB.version or 0) < HUB.version then DERPY_HUB = HUB end
DERPY_HUB_QUEUE = DERPY_HUB_QUEUE or {}
cm:add_first_tick_callback(function()
    if DERPY_HUB == HUB then HUB.start() end
end)
