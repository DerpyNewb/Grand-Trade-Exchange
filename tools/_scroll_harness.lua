-- The Exchange's scrolling lists (docs/superpowers/specs/2026-10-01-zharr-exchange-scroll-
-- lists-design.md), run against the shipped file. Since 2026-10-02 a built list is drawn
-- WHOLE, once, and scrolled by moving rows_holder after list_box. Part 1 measures the DATA:
-- every scrolling list hands back every item while its list is built, and the top window
-- when none is. Part 2 measures the UI calls against stub components, and part 3 the memo
-- that skips a write whose text is already on screen. Filled in by Python's percent
-- operator, so every literal percent sign is doubled.
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    get_saved_value = function() return nil end,
    callback = function() end,
    repeat_real_callback = function() end,
    model = function() return { turn_number = function() return 1 end } end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])

EX.layout = function() end
EX.refresh_panel = function() end
EX.store = {}
EX.race = EX.RACES["wh3_dlc23_chd_chaos_dwarfs"]
EX.guild = function() return EX.houses end
EX.stance_of = function() return 0 end
EX.closed_banner = function() return nil end
EX.faction_display = function(k) return k end
EX.feature = function() return true end
EX.MAX_ROWS = 20

-- 54 COMMODITIES AND THE LAYER-2 PAIR, the Resource Overhaul count, so the list is longer than
-- the window.
local base = #EX.COMMODITIES
for i = base + 1, 54 do EX.COMMODITIES[i] = string.format("res_derpy_t%%02d", i) end
EX.commodity_set = nil
local function first_last(t) return tostring(t[1]) .. "," .. tostring(t[#t]) .. "," .. #t end

-- EVERY GOOD while the list is built, in the list's order; the top window when it is not.
for _, m in ipairs({ "trade", "stats", "offer" }) do
    EX.mode = m
    EX.trade_page = 1
    EX.sort_col, EX.sort_dir = nil, 1
    local all = EX.sorted((function()
        local t = {}
        for _, r in ipairs(EX.COMMODITIES) do t[#t + 1] = r end
        for _, r in ipairs(EX.LAYER2) do t[#t + 1] = r end
        return t end)())
    local n = #all
    print("s_" .. m .. "_n " .. n .. "," .. tostring(EX.scroll_n()) .. ","
          .. tostring(EX.scrolls()))
    EX.list_key = nil
    print("s_" .. m .. "_top " .. first_last(EX.mode_instruments()) .. "|" .. all[1] .. ","
          .. all[20] .. ",20")
    EX.list_key = "built"
    print("s_" .. m .. "_all " .. first_last(EX.mode_instruments()) .. "|" .. all[1] .. ","
          .. all[n] .. "," .. n)
end

-- THE HOUSES LIST, every listed house in EX.listed_houses' order.
local function houses(n)
    EX.houses = {}
    for i = 1, n do EX.houses[i] = string.format("house_%%03d", i) end
    EX.house_set = nil
    EX.mode = EX.MODE_HOUSES
    EX.house_page = 1
end
houses(41)
local listed = EX.listed_houses()
EX.list_key = "built"
do
    local w = EX.mode_instruments()
    local same = #w == #listed
    for i = 1, #listed do if w[i] ~= listed[i] then same = false end end
    print("s_houses_all " .. #w .. "," .. #listed .. "," .. tostring(same))
end
EX.list_key = nil
print("s_houses_top " .. first_last(EX.mode_instruments()) .. "|" .. listed[1] .. ","
      .. listed[20] .. ",20")
-- FUNDS AND BONDS DO NOT SCROLL.
EX.house_page = EX.HOUSE_INDEX_PAGE
print("s_index_scrolls " .. tostring(EX.scrolls()))
EX.house_page = 1

-- THE LOG, on its own row pool: one row per entry, newest first.
EX.mode = EX.MODE_LOG
EX.LOG = {}
for i = 1, 45 do EX.LOG[i] = { i, "s" .. i, "d" .. i, "" } end
EX.list_key = "built"
do
    local rows, lines = EX.mode_instruments(), EX.log_lines()
    print("s_log " .. EX.scroll_n() .. "," .. #rows .. "," .. rows[1] .. "," .. rows[#rows] .. ","
          .. #lines .. "," .. tostring(lines[45] and lines[45][1] == "T45  s45") .. ","
          .. tostring(EX.scrolls()))
end
EX.list_key = nil
print("s_log_top " .. #EX.mode_instruments())
-- NO MORE ROWS THAN THE POOL HAS: a log past EX.LOG_MAX (an older save) lists the pool's worth.
for i = 46, EX.LOG_MAX + 10 do EX.LOG[i] = { i, "s" .. i, "d" .. i, "" } end
EX.list_key = "built"
print("s_log_cap " .. #EX.mode_instruments() .. "," .. EX.scroll_n() .. "," .. EX.LOG_MAX)
-- AN EMPTY LOG draws its one placeholder line, and its list has nothing to scroll.
EX.LOG = {}
do
    local rows, lines = EX.mode_instruments(), EX.log_lines()
    print("s_log_empty " .. #rows .. "," .. rows[1] .. "," .. lines[1][1] .. "," .. EX.scroll_n())
end
EX.list_key = nil
print("s_short " .. EX.short("lg7"))

-- THE ARROWS NO LONGER PAGE THE LISTS.
local counts = {}
for _, m in ipairs({ "stats", "offer", "houses", "log" }) do
    EX.mode = m
    EX.house_page = 1
    counts[#counts + 1] = EX.page_count()
end
print("s_pages " .. table.concat(counts, ","))

-- =========================================================================================
-- PART 2: THE UI CALLS, against stub components that record every Adopt and Destroy.
-- =========================================================================================
local CALLS, MOVES, WRITES, BAR_MOVES = {}, {}, {}, 0
local function uic(name, parent)
    local c = { __uic = true, name = name, kids = {}, x = 0, y = 0, w = 0, h = 0,
                visible = true, props = {} }
    c.parent = parent
    if parent then parent.kids[#parent.kids + 1] = c end
    function c:Id() return self.name end
    function c:Address() return self end
    function c:Position() return self.x, self.y end
    -- A PARENT CARRIES ITS CHILDREN, as the engine does (measured 2026-10-02: three vanilla HUD
    -- components moved 7px, and every child moved 7px with them).
    function c:MoveTo(x, y)
        MOVES[self.name] = (MOVES[self.name] or 0) + 1
        if string.sub(self.name, 1, 4) == "bar_" then BAR_MOVES = BAR_MOVES + 1 end
        local dx, dy = x - self.x, y - self.y
        local function shift(k) k.x, k.y = k.x + dx, k.y + dy for _, g in ipairs(k.kids) do shift(g) end end
        shift(self)
    end
    function c:Resize(w, h) self.w, self.h = w, h end
    function c:SetCanResizeWidth() end
    function c:SetCanResizeHeight() end
    function c:SetVisible(v) self.visible = v end
    function c:Visible() return self.visible end
    function c:SetInteractive() end
    function c:SetProperty(k, v) self.props[k] = v end
    function c:SetStateText(t) self.text = t WRITES[#WRITES + 1] = self.name end
    function c:CurrentState() return "standard" end
    function c:SetState() end
    function c:SetImagePath() end
    function c:Layout() end
    function c:Adopt(addr)
        if ADOPT_FAILS or (CLIP_ADOPT_FAILS and self.name == "list_clip") then
            error("adopt refused")
        end
        -- AN ENGINE THAT KEEPS THE OLD PARENT-RELATIVE OFFSET under the new parent.
        if ADOPT_SHIFTS then addr.x, addr.y = addr.x + self.x, addr.y + self.y end
        local old = addr.parent
        if old then
            for i, k in ipairs(old.kids) do if k == addr then table.remove(old.kids, i) break end end
        end
        addr.parent = self
        self.kids[#self.kids + 1] = addr
        CALLS[#CALLS + 1] = "adopt:" .. self.name .. "<-" .. addr.name
    end
    function c:Destroy()
        CALLS[#CALLS + 1] = "destroy:" .. self.name
        local p = self.parent
        if p then
            for i, k in ipairs(p.kids) do if k == self then table.remove(p.kids, i) break end end
        end
        -- AND EVERYTHING UNDER IT, as the engine's Destroy does: that is why the holder must
        -- leave first.
        local function kill(c) c.dead = true for _, k in ipairs(c.kids) do kill(k) end end
        kill(self)
    end
    function c:CreateComponent(nm, path)
        local n = uic(nm, self)
        if path == EX.LIST_FILE then
            local clip = uic("list_clip", n)
            uic("list_box", clip)
            local vs = uic("vslider", n)
            uic("handle", vs)
        elseif path == EX.PANEL_FILE then
            uic("rows_holder", n)
        elseif path == EX.ROW_FILE then
            for _, cell in ipairs({ "row_name", "row_trend", "icon" }) do uic(cell, n) end
            local spark = uic("spark", n)
            for i = 0, EX.SPARK_BARS - 1 do uic(string.format("bar_%%02d", i), spark) end
        end
        return n
    end
    return c
end
function is_uicomponent(c) return type(c) == "table" and c.__uic == true and not c.dead end
function find_uicomponent(root, name)
    if not is_uicomponent(root) then return false end
    for _, k in ipairs(root.kids) do
        if k.name == name and not k.dead then return k end
        local f = find_uicomponent(k, name)
        if f then return f end
    end
    return false
end

local PANEL = uic("derpy_chd_ex_panel")
local HOLDER = uic("rows_holder", PANEL)
HOLDER.x, HOLDER.y = 100, 200
EX.panel = function() return PANEL end
EX.sc = function(v) return v end
EX.say = function() end
local LAYOUTS, REFRESHES = 0, 0
EX.layout = function() LAYOUTS = LAYOUTS + 1 end
EX.refresh_panel = function() REFRESHES = REFRESHES + 1 end
EX.list_key, EX.list_broken = nil, nil

local function idx(s) for i, c in ipairs(CALLS) do if c == s then return i end end return 0 end
local function parts()
    local l = find_uicomponent(PANEL, EX.LIST)
    local cl = find_uicomponent(l, "list_clip")
    return l, cl, find_uicomponent(cl, "list_box"), find_uicomponent(l, "vslider")
end
-- WHAT EX.layout DOES FIRST: place() puts rows_holder back at the top of the list area.
local function placed() HOLDER:MoveTo(100, 200) end

-- BUILT: Trade's goods list. The holder moves into the clip, one empty row per good, and sits
-- where list_box is.
EX.mode = EX.MODE_TRADE
EX.trade_page = 1
EX.sort_col, EX.sort_dir = nil, 1
EX.ensure_list(PANEL)
local list, clip, box, slider = parts()
print("u_build " .. tostring(HOLDER.parent == clip) .. "," .. #box.kids .. "," .. EX.scroll_n()
      .. "," .. tostring(slider.visible) .. "," .. clip.h .. "," .. HOLDER.y .. "," .. box.y)

-- THE ROWS FOLLOW THE LIST, on every tick and by the pixel, and nothing is redrawn: a redraw is
-- the whole panel (measured 25-200ms in game, 2026-10-01), and the rows are already drawn.
box.y = clip.y - 3 * EX.ROW_PITCH - 5
LAYOUTS, REFRESHES = 0, 0
EX.scroll_poll()
local first = tostring(HOLDER.y == box.y and HOLDER.x == 100)
local track = true
for r = 5, 12 do
    box.y = clip.y - r * EX.ROW_PITCH - r
    EX.scroll_poll()
    if HOLDER.y ~= box.y then track = false end
end
local before = MOVES["rows_holder"] or 0
EX.scroll_poll()
print("u_follow " .. first .. "," .. tostring(track) .. "," .. LAYOUTS .. "," .. REFRESHES .. ","
      .. ((MOVES["rows_holder"] or 0) - before))
-- A HIDDEN PANEL'S LIST IS LEFT ALONE.
PANEL.visible = false
box.y = clip.y - 2 * EX.ROW_PITCH
EX.scroll_poll()
local hidden = tostring(HOLDER.y ~= box.y)
PANEL.visible = true
-- AND A CLOSED ONE HAS NO LIST TO POLL: the poll runs for the whole campaign.
EX.show(false)
print("u_hidden " .. hidden .. "," .. tostring(EX.list_key))
PANEL.visible = true

-- AN UNCHANGED VIEW KEEPS ITS LIST AND ITS PLACE: a trade click lays the panel out again, and
-- place() has just put the holder at the top of a list that is scrolled.
EX.ensure_list(PANEL)
list, clip, box = parts()
box.y = clip.y - 7 * EX.ROW_PITCH
EX.scroll_poll()
placed()
CALLS = {}
EX.ensure_list(PANEL)
print("u_same " .. #CALLS .. "," .. tostring(HOLDER.y == box.y))

-- A RE-SORT REBUILDS AT THE TOP: the holder goes home BEFORE the old list is destroyed, then
-- into the new one, at its top.
placed()
CALLS = {}
EX.sort_col = "hdr_price"
EX.ensure_list(PANEL)
list, clip, box = parts()
print("u_order " .. idx("adopt:derpy_chd_ex_panel<-rows_holder") .. "," .. idx("destroy:" .. EX.LIST)
      .. "," .. tostring(HOLDER.parent == clip) .. "," .. tostring(not HOLDER.dead)
      .. "," .. tostring(HOLDER.y == box.y and box.y == clip.y))

-- THE CHART DOES NOT SCROLL: the list goes, the holder is the panel's again.
EX.trade_page = 2
EX.ensure_list(PANEL)
print("u_drop " .. tostring(find_uicomponent(PANEL, EX.LIST) == false) .. ","
      .. tostring(HOLDER.parent == PANEL) .. "," .. tostring(EX.list_key))
-- AND BACK TO THE LIST STARTS AT THE TOP.
EX.trade_page = 1
placed()
EX.ensure_list(PANEL)
list, clip, box = parts()
print("u_rebuild " .. tostring(HOLDER.parent == clip) .. "," .. tostring(HOLDER.y == clip.y))

-- A LIST THAT FITS HAS NO SCROLL BAR.
local keep = {}
for i = 1, #EX.COMMODITIES do keep[i] = EX.COMMODITIES[i] end
for i = #EX.COMMODITIES, base + 1, -1 do EX.COMMODITIES[i] = nil end
EX.commodity_set = nil
EX.ensure_list(PANEL)
print("u_short " .. tostring(select(4, parts()).visible) .. "," .. EX.scroll_n())
for i, r in ipairs(keep) do EX.COMMODITIES[i] = r end
EX.commodity_set = nil

-- THE LOG: one empty row per entry, under a window MAX_ROWS rows tall.
EX.mode = EX.MODE_LOG
EX.LOG = {}
for i = 1, 45 do EX.LOG[i] = { i, "s" .. i, "d" .. i, "" } end
EX.ensure_list(PANEL)
list, clip, box = parts()
print("u_log " .. #box.kids .. "," .. clip.h)

-- THE LOG IS SCANNED BEFORE IT IS SIZED. EX.refresh_panel scans after EX.layout built the
-- list, and the first scan of a session can add entries - a list sized before it rebuilds at
-- the top on the player's first scroll, throwing the wheel away.
local grown = false
local real_scan = EX.log_scan
EX.log_scan = function()
    if grown then return end
    grown = true
    for i = 1, 3 do table.insert(EX.LOG, 1, { 100 + i, "n" .. i, "d", "" }) end
end
EX.list_key = nil
EX.ensure_list(PANEL)
EX.log_scan()                    -- what EX.refresh_panel does next
CALLS = {}
EX.ensure_list(PANEL)            -- what the next layout does
print("u_log_grow " .. idx("destroy:" .. EX.LIST) .. "," .. #EX.LOG .. ","
      .. #select(3, parts()).kids)
EX.log_scan = real_scan

-- AN UNCHANGED POLL TICK IS CHEAP: on Houses the item count is a sort of every house, and the
-- poll runs every frame.
houses(41)
EX.ensure_list(PANEL)
local real_listed, listed_calls = EX.listed_houses, 0
EX.listed_houses = function(...) listed_calls = listed_calls + 1 return real_listed(...) end
EX.scroll_poll()
EX.listed_houses = real_listed
print("u_poll_cheap " .. listed_calls)

-- THE HOLDER STAYS WHERE IT WAS PUT across an Adopt, whatever the engine does with offsets:
-- every row is placed from holder:Position().
ADOPT_SHIFTS = true
EX.mode = EX.MODE_STATS
placed()
EX.ensure_list(PANEL)
local pos_in = HOLDER.x .. "," .. HOLDER.y
EX.mode = EX.MODE_HOUSES
EX.house_page = EX.HOUSE_INDEX_PAGE
EX.ensure_list(PANEL)
print("u_pos " .. pos_in .. "," .. HOLDER.x .. "," .. HOLDER.y)
ADOPT_SHIFTS = false
EX.house_page = 1

-- THE ROWS NEVER ARRIVE: the clip refuses them at build time. The rows are still the panel's,
-- so the empty list must go - left up, it sits over the rows and takes their clicks - and it
-- is not built again.
EX.mode = EX.MODE_OFFER
CLIP_ADOPT_FAILS = true
EX.ensure_list(PANEL)
CLIP_ADOPT_FAILS = false
print("u_clip_fail " .. tostring(find_uicomponent(PANEL, EX.LIST) == false) .. ","
      .. tostring(HOLDER.parent == PANEL) .. "," .. tostring(EX.list_broken))
EX.list_broken = nil
EX.ensure_list(PANEL)

-- ADOPT REFUSED ON THE WAY OUT: the rows are never destroyed, and never built again.
CALLS = {}
ADOPT_FAILS = true
EX.mode = EX.MODE_STATS
EX.ensure_list(PANEL)
ADOPT_FAILS = false
-- AND THE ROWS STILL DRAW: the holder is inside the list, so a hidden list hides every row.
local function shown(c) while c do if not c.visible then return false end c = c.parent end return true end
print("u_adopt_fail " .. idx("destroy:" .. EX.LIST) .. "," .. tostring(not HOLDER.dead) .. ","
      .. tostring(EX.list_broken) .. "," .. tostring(shown(HOLDER)) .. ","
      .. #EX.mode_instruments())
EX.list_broken = nil

-- =========================================================================================
-- PART 3: WHAT IS ALREADY ON SCREEN IS NOT WRITTEN AGAIN - and a rebuilt panel forgets it.
-- =========================================================================================
local ROOT = uic("root")
core.get_ui_root = function() return ROOT end
EX.panel = function() return find_uicomponent(ROOT, EX.PANEL) end
local real_opt = EX.opt
EX.opt = function() return 2 end
cm.get_faction = function() return false end      -- the house rows' crests: none here
EX.built = false
EX.build_panel()
local P = EX.panel()
local H = find_uicomponent(P, "rows_holder")
local lg = 0
for _, k in ipairs(H.kids) do if string.match(k.name, "_lg%%d+$") then lg = lg + 1 end end
print("p_pool " .. lg .. "," .. EX.LOG_MAX)

EX.mode = EX.MODE_INTRO
local function row_writes()
    local n = 0
    for _, w in ipairs(WRITES) do if w == "row_name" then n = n + 1 end end
    return n
end
WRITES = {}
EX.draw_intro(P, H)
local w1 = row_writes()
WRITES = {}
EX.draw_intro(P, H)
local w2 = row_writes()
-- THE SPARKLINE TOO: twelve bars, each a Resize and a MoveTo, on every row of every refresh.
local res1 = EX.COMMODITIES[1]
local row1 = EX.row(H, res1)
EX.history[res1] = { 3, 5, 9, 4 }
BAR_MOVES = 0
EX.draw_spark(row1, res1)
local b1 = BAR_MOVES
BAR_MOVES = 0
EX.draw_spark(row1, res1)
local b2 = BAR_MOVES
EX.history[res1] = { 3, 5, 9, 4, 6 }
BAR_MOVES = 0
EX.draw_spark(row1, res1)
local b3 = BAR_MOVES
-- A NEW PANEL IS NEW COMPONENTS with nothing written on them.
P:Destroy()
EX.built = false
EX.build_panel()
P = EX.panel()
H = find_uicomponent(P, "rows_holder")
WRITES = {}
EX.draw_intro(P, H)
local w3 = row_writes()
BAR_MOVES = 0
EX.draw_spark(EX.row(H, res1), res1)
print("p_memo " .. w1 .. "," .. w2 .. "," .. w3 .. "|" .. b1 .. "," .. b2 .. "," .. b3 .. ","
      .. BAR_MOVES)
EX.opt = real_opt
