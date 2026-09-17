-- The bottom strip: five view tabs on the left, two arrows and a page counter on the right.
--
-- IT USED TO TEST A VIEW CYCLE. Until 2026-09-07 the arrows walked EX.MODES and the guide was
-- the one view they paged instead; the tabs made cycling redundant and paging the rule, so
-- what this measures now is: tabs pick a view, arrows page the view they are on.
--
-- EX.set_mode, EX.layout and EX.refresh_panel all reach a live panel, so the last two are
-- replaced with no-ops after the file loads. EX.set_mode is NOT replaced - it carries the
-- page reset, which is one of the things being measured.
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    get_saved_value = function() return nil end,
    callback = function() end,
    model = function() return { turn_number = function() return 1 end } end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])

EX.layout = function() end
EX.refresh_panel = function() end
EX.store = {}
-- BOUND AS A CHAOS DWARF PLAYER. Since 2026-09-08 EX.tab_locked greys the Offerings and
-- Houses tabs for an uncovered race, so "every view is one click from every other" is only
-- true for a covered one. The locked case is measured by _race_harness.lua instead.
EX.race = EX.RACES["wh3_dlc23_chd_chaos_dwarfs"]
-- EX.guild_summary reaches the guild, the stance model and the closure banner. None of them
-- is what this file measures; the footer's page-count clause is.
EX.guild = function() return EX.houses end
EX.stance_of = function() return 0 end
EX.closed_banner = function() return nil end
EX.faction_display = function(k) return k end

local n = #EX.MODES
print("modes " .. n)

-- THE TABS -------------------------------------------------------------------------------
-- A tab's component name maps back to exactly one mode, and nothing else does. EX.tab_mode is
-- read by BOTH halves of the click listener - the filter and the handler - so a name that
-- resolves in one and not the other is impossible by construction; what can still go wrong is
-- the mapping itself.
local ok_map, names = true, {}
for _, m in ipairs(EX.MODES) do
    local nm = EX.tab_name(m)
    names[#names + 1] = nm
    if EX.tab_mode(nm) ~= m then ok_map = false end
end
print("tab_map " .. tostring(ok_map))
print("tab_names " .. table.concat(names, ","))
print("tab_foreign " .. tostring(EX.tab_mode("button_end_turn"))
      .. "," .. tostring(EX.tab_mode("close_button")))

-- EVERY VIEW HAS A LABEL. A tab with no label is a blank button that draws and clicks and
-- says nothing - not an error anywhere, and invisible to every check that reads geometry.
local labels, ok_lbl = {}, true
for _, m in ipairs(EX.MODES) do
    local l = EX.TAB_LABEL[m]
    if not l or l == "" then ok_lbl = false end
    labels[#labels + 1] = tostring(l)
end
print("tab_labels " .. table.concat(labels, ","))
print("tab_labels_all " .. tostring(ok_lbl))

-- A TAB REACHES ITS VIEW IN ONE CLICK, from anywhere. This is the whole ask: Houses used to
-- be three presses of an arrow away from Trade.
--
-- BOTH GATES OPEN FIRST. This measures NAVIGATION, not gating - EX.tab_locked is covered by
-- _race_harness.lua, on all four combinations of coverage and houses. Without a race bound and
-- a house on the board, Offerings and Houses are legitimately locked and set_mode legitimately
-- refuses them, and this loop would report a navigation fault that is not one.
EX.race = EX.RACES["wh3_dlc23_chd_chaos_dwarfs"]
EX.houses = { "h1", "h2" }
local ok_reach = true
for _, from in ipairs(EX.MODES) do
    for _, to in ipairs(EX.MODES) do
        EX.mode = from
        EX.set_mode(EX.tab_mode(EX.tab_name(to)))
        if EX.mode ~= to then ok_reach = false end
    end
end
print("tab_reach " .. tostring(ok_reach))

-- THE PAGE COUNT -------------------------------------------------------------------------
-- Fill the log past one page so the log's count is a real number and not an empty-log 1.
EX.LOG = {}
for i = 1, 45 do EX.LOG[i] = { i, "s" .. i, "d" .. i, "" } end
local per = EX.log_per_page()
print("per_page " .. per)
print("log_pages " .. EX.log_pages())

local counts = {}
for _, m in ipairs(EX.MODES) do
    EX.mode = m
    counts[#counts + 1] = m .. "=" .. EX.page_count()
end
EX.mode = EX.MODE_HELP
counts[#counts + 1] = "help=" .. EX.page_count()
print("page_counts " .. table.concat(counts, ","))

-- THE ARROWS PAGE, AND DO NOT CHANGE VIEW ------------------------------------------------
EX.mode = EX.MODE_LOG
EX.log_page = 1
EX.nav_click(EX.MODE_BTN)
print("log_fwd " .. EX.log_page .. "," .. tostring(EX.mode))
EX.log_page = 1
EX.nav_click(EX.MODE_PREV)
print("log_back_wrap " .. EX.log_page)
EX.log_page = EX.log_pages()
EX.nav_click(EX.MODE_BTN)
print("log_fwd_wrap " .. EX.log_page)

EX.mode = EX.MODE_HELP
EX.help_page = 1
EX.nav_click(EX.MODE_PREV)
print("help_back_wrap " .. EX.help_page .. "," .. tostring(EX.mode == EX.MODE_HELP))
EX.help_page = 1
EX.nav_click(EX.MODE_BTN)
print("help_fwd " .. EX.help_page)

-- ONE STEP EACH WAY IS A NO-OP, on both paging views.
local ok_rt = true
for _, pair in ipairs({ { EX.MODE_LOG, "log_page" }, { EX.MODE_HELP, "help_page" } }) do
    EX.mode = pair[1]
    for p = 1, EX.page_count() do
        EX[pair[2]] = p
        EX.nav_click(EX.MODE_BTN)
        EX.nav_click(EX.MODE_PREV)
        if EX[pair[2]] ~= p then ok_rt = false end
    end
end
print("roundtrip " .. tostring(ok_rt))

-- A ONE-PAGE VIEW IS UNMOVED BY EITHER ARROW, and above all is not switched away from - the
-- arrows cycled views until 2026-09-07 and an unconverted branch would still do it.
local ok_single = true
for _, m in ipairs(EX.MODES) do
    EX.mode = m
    if EX.page_count() == 1 then
        EX.nav_click(EX.MODE_BTN)
        EX.nav_click(EX.MODE_PREV)
        if EX.mode ~= m or EX.page_index() ~= 1 then ok_single = false end
    end
end
print("single_page_noop " .. tostring(ok_single))

-- THE COUNTER reads index/count for every view, including the ones with a single page.
EX.log_page, EX.help_page = 1, 1   -- the wrap tests above left both mid-list
local lab = {}
for _, m in ipairs(EX.MODES) do
    EX.mode = m
    lab[#lab + 1] = EX.nav_label()
end
print("labels " .. table.concat(lab, ","))
EX.mode = EX.MODE_LOG
EX.log_page = 2
print("log_label " .. EX.nav_label())

-- WHAT THE PAGE ACTUALLY DRAWS. Nothing pinned EX.help_lines to EX.help_page once and the
-- counter read "2/2" over page one's text; the same hole in the log would leave 41 of its 60
-- entries unreachable with the arrows looking like they worked.
EX.mode = EX.MODE_LOG
EX.log_page = 1
local p1 = EX.log_lines()
EX.log_page = 2
local p2 = EX.log_lines()
print("page1_first " .. p1[1][1])
print("page2_first " .. p2[1][1])
print("page2_differs " .. tostring(p1[1][1] ~= p2[1][1]))
print("last_page_len " .. (function()
    EX.log_page = EX.log_pages()
    return #EX.log_lines()
end)())
-- AN OUT-OF-RANGE PAGE CLAMPS rather than drawing an empty list, which reads exactly like a
-- log that recorded nothing.
EX.log_page = EX.log_pages() + 9
print("log_overflow_len " .. #EX.log_lines() .. "," .. EX.log_page)

-- ENTERING A VIEW OPENS ITS FIRST PAGE ----------------------------------------------------
EX.mode = EX.MODE_LOG
EX.log_page = 3
EX.set_mode(EX.MODE_TRADE)
EX.set_mode(EX.MODE_LOG)
print("log_reset " .. EX.log_page)
EX.mode = EX.MODE_HELP
EX.help_page = 2
EX.set_mode(EX.MODE_TRADE)
EX.set_mode(EX.MODE_HELP)
print("help_reset " .. EX.help_page)

-- WHICH ARROW GOES WHICH WAY. EX.step_page takes a direction and would be just as happy with
-- the two arrows wired backwards; EX.nav_click is the piece that decides which name means
-- which way, and it is the only piece a player can get wrong from the outside. Measured by
-- mutation 2026-09-07: with the direction inlined at the click site, swapping the two arrows
-- passed every check in the suite.
EX.mode = EX.MODE_LOG
EX.log_page = 2
EX.nav_click(EX.MODE_PREV)
print("press_prev " .. EX.log_page)
EX.log_page = 2
EX.nav_click(EX.MODE_BTN)
print("press_next " .. EX.log_page)

-- =========================================================================================
-- THE HOUSES VIEW PAGES. Until 2026-09-08 it TRUNCATED: `while #t > EX.MAX_ROWS do t[#t] =
-- nil end` against an ALPHABETICALLY SORTED list, so 39 Empire factions would have listed
-- Averland through Nordland and silently dropped Reikland, Stirland and Talabecland. It is
-- already a live fault at 20 Chaos Dwarf houses - 10 vanilla plus the lords pack's 10,
-- sitting exactly on the limit.
-- =========================================================================================
local function houses(n)
    EX.houses = {}
    for i = 1, n do EX.houses[i] = string.format("house_%%03d", i) end
    EX.house_set = nil
    EX.mode = EX.MODE_HOUSES
end

houses(41)                      -- Skaven, the deepest list in the game
print("h_pages " .. EX.house_pages())
print("h_count " .. EX.page_count())
EX.house_page = 1
print("h_first " .. EX.mode_instruments()[1])
print("h_len1 " .. #EX.mode_instruments())
EX.house_page = 3
local hlast = EX.mode_instruments()
print("h_last " .. hlast[#hlast] .. "," .. #hlast)

-- EVERY HOUSE IS REACHABLE, which is the entire reason this task exists. Walk the pages and
-- assert the union is the whole list, in order, with nothing repeated.
local seen, dupe, order_ok, prev, uniq = {}, false, true, "", 0
for pg = 1, EX.house_pages() do
    EX.house_page = pg
    for _, h in ipairs(EX.mode_instruments()) do
        if seen[h] then dupe = true end
        if h <= prev then order_ok = false end
        prev = h
        seen[h] = true
    end
end
for _ in pairs(seen) do uniq = uniq + 1 end
print("h_union " .. uniq .. "," .. tostring(dupe) .. "," .. tostring(order_ok))

-- THE CLAMP, and it is not inherited from the log. A house can DIE while the player sits on
-- page 3 - EX.check_delistings runs at turn start and EX.prune_houses can shorten the list -
-- and an out-of-range page draws an empty view that reads exactly like a market with no
-- houses in it. The log clamps INSIDE its render function, not only where the arrows move it.
EX.house_page = 3
houses(4)
print("h_shrunk " .. #EX.mode_instruments() .. "," .. EX.house_page)
EX.house_page = 99
print("h_overflow " .. #EX.mode_instruments() .. "," .. EX.house_page)
EX.house_page = 0
print("h_under " .. #EX.mode_instruments() .. "," .. EX.house_page)

-- AN EMPTY MARKET. Zero houses is ONE page, not zero: a zero makes nav_label read "1/0" and
-- step_page take a modulo of nothing.
houses(0)
print("h_empty " .. EX.house_pages() .. "," .. #EX.mode_instruments())

-- ENTERING THE VIEW OPENS PAGE 1, like the log and the guide.
houses(41)
EX.house_page = 3
EX.set_mode(EX.MODE_TRADE)
EX.set_mode(EX.MODE_HOUSES)
print("h_reset " .. EX.house_page)

-- THE ARROWS PAGE HOUSES AND DO NOT LEAVE THE VIEW.
EX.mode = EX.MODE_HOUSES
EX.house_page = 1
EX.nav_click(EX.MODE_BTN)
print("h_fwd " .. EX.house_page .. "," .. tostring(EX.mode))
EX.house_page = 1
EX.nav_click(EX.MODE_PREV)
print("h_back_wrap " .. EX.house_page)

-- EXACTLY AT THE LIMIT IS ONE PAGE. 20 houses in 20 slots must not produce a second, empty
-- page - the off-by-one this ceiling invites, and the number Chaos Dwarfs sit on today.
houses(EX.MAX_ROWS)
print("h_exact " .. EX.house_pages() .. "," .. #EX.mode_instruments())
houses(EX.MAX_ROWS + 1)
print("h_over_by_one " .. EX.house_pages())

-- TRADE HAS TWO PAGES: the 19-row list, and the deep price chart. It must never page for row
-- overflow (19 rows against 20 slots) - the second page is a different KIND of content, the
-- way the guide's two pages are.
EX.mode = EX.MODE_TRADE
EX.trade_page = 1
print("h_trade_pages " .. EX.page_count())

-- AND THE ARROWS MUST ACTUALLY REACH IT. Every assertion above is about the page COUNT, and a
-- count is not a route: with EX.step_page and EX.page_index both missing their trade branch
-- the counter still reads 1/2, the arrows are still un-greyed, and pressing them does nothing
-- at all. Both of those shipped as surviving mutants on 2026-09-09 before this was written -
-- the chart was unreachable and the whole suite passed.
EX.nav_click(EX.MODE_BTN)
print("t_fwd " .. EX.page_index() .. "," .. tostring(EX.on_chart()))
EX.nav_click(EX.MODE_BTN)
print("t_wrap " .. EX.page_index() .. "," .. tostring(EX.on_chart()))
EX.nav_click(EX.MODE_PREV)
print("t_back " .. EX.page_index() .. "," .. tostring(EX.on_chart()))
-- THE CHART PAGE DRAWS NO ROWS, which is what takes the list off screen: EX.layout builds its
-- keep-set from this list, so anything it still named would be left sitting on top of the chart.
EX.trade_page = 2
print("t_rows " .. #EX.mode_instruments())
EX.trade_page = 1
print("t_rows_back " .. #EX.mode_instruments())

-- THE FOOTER NO LONGER LIES. It appended "N more not shown" because rows were DROPPED; with
-- paging the counter answers that, and two different answers to one question on one screen
-- is worse than either.
houses(41)
EX.house_page = 1
print("h_summary_hidden " .. tostring(string.find(EX.guild_summary() or "",
                                                  "not shown") ~= nil))

-- TRADE PAGES UNDER EVERY COMBINATION OF THE TWO SWITCHES ---------------------------------
-- Four combinations, and the index arithmetic this replaced got two of them wrong: with
-- deep_history off, page 2 was the chart's index and the orders page was unreachable at 3.
EX.mode = EX.MODE_TRADE
local function combo(deep, ord)
    EX.feature = function(k)
        if k == "deep_history" then return deep end
        if k == "orders" then return ord end
        return true
    end
    return table.concat(EX.trade_pages(), ",")
end
print("pages_both " .. combo(true, true))
print("pages_nodeep " .. combo(false, true))
print("pages_noord " .. combo(true, false))
print("pages_neither " .. combo(false, false))

-- CAN AN ORDER ACTUALLY BE PLACED, per combination, and where does the ticket live. A page
-- COUNT answers neither, which is how two of the four combinations shipped broken on
-- 2026-09-10 with this whole section green: with orders OFF the ticket sat live on the chart
-- page (that page answers to deep_history) while the ledger holding the only Cancel button
-- was gone, and with deep_history off there was no chart page, so no ticket at all, on a
-- ledger page that told the player to go and set one under its chart.
local function place_reach(deep, ord)
    EX.feature = function(k)
        if k == "deep_history" then return deep end
        if k == "orders" then return ord end
        return true
    end
    EX.orders = {}
    local why = EX.place_order_check("res_gems", "b", "le", 18)
    local idx = EX.selection_page_index()
    return (why and "refused" or "ok") .. "," .. (idx and EX.trade_pages()[idx] or "none")
end
print("place_both " .. place_reach(true, true))
print("place_nodeep " .. place_reach(false, true))
print("place_noord " .. place_reach(true, false))
print("place_neither " .. place_reach(false, false))

-- THE LEDGER'S OWN COLUMN LABELS, AND ITS DEAD SORT. The ledger is a PAGE of the trade view
-- and not a mode, so every table keyed by EX.mode handed it Trade's entries: "Buy" over a
-- price on rows that are half sells, "Trend" over an order sentence, and a header click that
-- resolved through the trade sorter - colouring the header, leaving the ledger's own rows
-- exactly where they were, and re-sorting page 1 underneath the player. EX.view() is the one
-- accessor all four tables route through now.
EX.feature = function() return true end
EX.mode = EX.MODE_TRADE
EX.trade_page = 3
print("view3 " .. tostring(EX.view()))
print("hdr3_price " .. tostring((EX.HEADERS[EX.view()] or {}).hdr_price))
print("hdr3_trend " .. tostring((EX.HEADERS[EX.view()] or {}).hdr_trend))
-- NO SORTER FOR THE LEDGER, deliberately: its rows are the order list in placement order.
-- sort_click must therefore refuse the click outright rather than half-handling it, and it
-- must leave EX.sort_col alone - that field is what carries the green mark onto page 1.
EX.sort_col = nil
print("sort3 " .. tostring(EX.sort_fn("hdr_price")))
print("sortclick3 " .. tostring(EX.sort_click("hdr_price")))
print("sortcol3 " .. tostring(EX.sort_col))
EX.trade_page = 1
print("hdr1_price " .. tostring((EX.HEADERS[EX.view()] or {}).hdr_price))
print("sort1 " .. tostring(EX.sort_fn("hdr_price") ~= nil))

-- THE COUNTER CANNOT READ "3/2". EX.trade_kind clamps and EX.page_index did not, so throwing
-- a switch while standing on the page it removes left the label naming a page that no longer
-- existed until an arrow was pressed.
EX.trade_page = 3
EX.feature = function(k) if k == "orders" then return false end return true end
print("idx_clamped " .. EX.page_index())
print("nav_clamped " .. EX.nav_label())
EX.feature = function() return true end
EX.trade_page = 1

-- THE KIND FOLLOWS THE INDEX, whatever the list holds.
EX.feature = function() return true end
EX.trade_page = 1
print("kind1 " .. EX.trade_kind())
EX.trade_page = 2
print("kind2 " .. EX.trade_kind())
print("onchart2 " .. tostring(EX.on_chart()))
EX.trade_page = 3
print("kind3 " .. EX.trade_kind())
print("onorders3 " .. tostring(EX.on_orders()))

-- AND WITH THE CHART OFF, page 2 IS the orders page - no gap, no dead page.
EX.feature = function(k) return k ~= "deep_history" end
EX.trade_page = 2
print("nodeep_kind2 " .. EX.trade_kind())
print("nodeep_onchart " .. tostring(EX.on_chart()))
print("nodeep_onorders " .. tostring(EX.on_orders()))

-- A PAGE INDEX PAST THE END CLAMPS rather than returning nil. The switch can move while the
-- player is standing on page 3.
EX.feature = function() return false end
EX.trade_page = 3
print("clamped " .. EX.trade_kind())

-- THE ROW-NAME CLICK'S CHART JUMP, closed here rather than through a simulated UI click -
-- EX.chart_page_index is a pure function pulled out of the click handler for exactly this.
-- Task 5 shipped the dynamic lookup (finding "chart" in EX.trade_pages()) replacing a literal
-- EX.trade_page = 2, but nothing ran it with the chart switched off, so reverting to that
-- literal passed the whole suite - measured 2026-09-10, and the mutant this closes.
EX.feature = function() return true end
print("chart_idx_both " .. tostring(EX.chart_page_index()))
EX.feature = function(k) return k ~= "deep_history" end
print("chart_idx_nodeep " .. tostring(EX.chart_page_index()))
EX.feature = function(k) return k ~= "orders" end
print("chart_idx_noord " .. tostring(EX.chart_page_index()))
