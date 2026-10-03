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
-- SINCE 2026-10-01 THE LISTS SCROLL (tools/_scroll_harness.lua measures them), so the arrows
-- page the guide and Trade's sections only. The log is filled past one window anyway, so a
-- count of 1 here is the scroll and not an empty log.
EX.LOG = {}
for i = 1, 45 do EX.LOG[i] = { i, "s" .. i, "d" .. i, "" } end

local counts = {}
for _, m in ipairs(EX.MODES) do
    EX.mode = m
    counts[#counts + 1] = m .. "=" .. EX.page_count()
end
EX.mode = EX.MODE_HELP
counts[#counts + 1] = "help=" .. EX.page_count()
print("page_counts " .. table.concat(counts, ","))

-- THE ARROWS PAGE THE GUIDE, AND DO NOT CHANGE VIEW ---------------------------------------
EX.mode = EX.MODE_HELP
EX.help_page = 1
EX.nav_click(EX.MODE_PREV)
print("help_back_wrap " .. EX.help_page .. "," .. tostring(EX.mode == EX.MODE_HELP))
EX.help_page = 1
EX.nav_click(EX.MODE_BTN)
print("help_fwd " .. EX.help_page)

-- ONE STEP EACH WAY IS A NO-OP.
local ok_rt = true
EX.mode = EX.MODE_HELP
for p = 1, EX.page_count() do
    EX.help_page = p
    EX.nav_click(EX.MODE_BTN)
    EX.nav_click(EX.MODE_PREV)
    if EX.help_page ~= p then ok_rt = false end
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
EX.help_page = 1
local lab = {}
for _, m in ipairs(EX.MODES) do
    EX.mode = m
    lab[#lab + 1] = EX.nav_label()
end
print("labels " .. table.concat(lab, ","))

-- ENTERING THE GUIDE OPENS ITS FIRST PAGE.
EX.mode = EX.MODE_HELP
EX.help_page = 2
EX.set_mode(EX.MODE_TRADE)
EX.set_mode(EX.MODE_HELP)
print("help_reset " .. EX.help_page)

-- WHICH ARROW GOES WHICH WAY. EX.step_page takes a direction and would be just as happy with
-- the two arrows wired backwards; EX.nav_click is the piece that decides which name means
-- which way. Measured by mutation 2026-09-07: with the direction inlined at the click site,
-- swapping the arrows passed every check in the suite. The guide has two pages, where both
-- directions land on the same page, so the direction is read off the call itself.
local real_step, step_got = EX.step_page, nil
EX.step_page = function(d) step_got = d end
EX.nav_click(EX.MODE_PREV)
print("press_prev " .. tostring(step_got))
EX.nav_click(EX.MODE_BTN)
print("press_next " .. tostring(step_got))
EX.step_page = real_step

local function houses(n)
    EX.houses = {}
    for i = 1, n do EX.houses[i] = string.format("house_%%03d", i) end
    EX.house_set = nil
    EX.mode = EX.MODE_HOUSES
end

-- ENTERING THE HOUSES VIEW OPENS THE LIST, whichever section was up last visit.
houses(41)
EX.house_page = EX.HOUSE_INDEX_PAGE
EX.set_mode(EX.MODE_TRADE)
EX.set_mode(EX.MODE_HOUSES)
print("h_reset " .. EX.house_page)

-- THE SUB-TABS ----------------------------------------------------------------------------
-- A slot's component name maps back to its number, and nothing else does - the listener's
-- filter reads EX.sub_slot, so a false positive is a click anywhere in the game.
local smap = {}
for i = 1, EX.SUB_SLOTS do smap[#smap + 1] = tostring(EX.sub_slot(EX.sub_name(i))) end
print("sub_map " .. table.concat(smap, ","))
print("sub_foreign " .. tostring(EX.sub_slot("button_end_turn")) .. ","
      .. tostring(EX.sub_slot(EX.tab_name(EX.MODE_HOUSES))) .. ","
      .. tostring(EX.sub_slot(EX.sub_name(EX.SUB_SLOTS + 1))))
local function secs()
    local t = {}
    for _, s in ipairs(EX.sections() or {}) do t[#t + 1] = s[1] .. "=" .. s[2] end
    return table.concat(t, ",")
end
EX.mode = EX.MODE_HOUSES
print("sub_houses " .. secs())
-- ONE CLICK TO EACH, from the second page of the list, and the counter reads the section.
EX.house_page = 2
EX.sort_col = "hdr_price"
EX.sub_click(2)
print("sub_to_index " .. EX.view() .. "," .. EX.nav_label() .. "," .. tostring(EX.sort_col))
EX.nav_click(EX.MODE_BTN)
EX.nav_click(EX.MODE_PREV)
print("sub_index_arrows " .. EX.view() .. "," .. EX.nav_label())
EX.sub_click(3)
print("sub_to_bonds " .. EX.view() .. "," .. EX.nav_label())
EX.sub_click(1)
print("sub_to_list " .. EX.view() .. "," .. EX.nav_label())
-- THE SECTION ON SCREEN IS A NO-OP: its button is greyed, and a click that still arrives
-- must not throw the player back to page 1 of the list.
EX.house_page = 2
EX.sub_click(1)
print("sub_here " .. EX.view() .. "," .. EX.nav_label())
-- A LOCKED SECTION says why and is not entered: bonds off and none held.
EX.snap = { ai_bonds = false }
local keep_bonds = EX.bonds
EX.bonds = {}
EX.house_page = 1
EX.sub_click(3)
print("sub_bonds_locked " .. EX.view() .. "," .. tostring(EX.section_locked("bonds") ~= nil)
      .. "," .. tostring(EX.section_locked("index") ~= nil))
EX.bonds = { { side = "b" } }
print("sub_bonds_open " .. tostring(EX.section_locked("bonds") ~= nil))
EX.bonds = keep_bonds
EX.snap = nil
-- THE DEALS TAB: two sections, one page each, and no third slot.
EX.mode = EX.MODE_DEALS
EX.deal_page = 1
print("sub_deals " .. secs() .. "," .. EX.nav_label())
EX.sub_click(2)
print("sub_to_contracts " .. EX.view() .. "," .. EX.nav_label())
EX.sub_click(3)
print("sub_deals_slot3 " .. EX.view())
EX.sub_click(1)
print("sub_to_deals " .. EX.view())
EX.snap = { ai_forwards = false }
local keep_fw = EX.forwards
EX.forwards = {}
EX.sub_click(2)
print("sub_contracts_locked " .. EX.view() .. "," .. tostring(EX.section_locked("contracts") ~= nil))
EX.forwards = keep_fw
EX.snap = nil
-- TRADE'S SECTIONS (2026-10-01): Goods, Chart, Orders, one button each, under every
-- combination of the two switches. A locked section's button changes nothing.
local real_feature = EX.feature
local function sections_under(deep, ord)
    EX.feature = function(k)
        if k == "deep_history" then return deep end
        if k == "orders" then return ord end
        return true
    end
    EX.mode = EX.MODE_TRADE
    local got = {}
    for i = 1, 3 do
        EX.trade_page = 1
        EX.sub_click(i)
        got[#got + 1] = tostring(EX.section_on and EX.section_on())
    end
    return table.concat(got, ",")
end
print("tsec_both " .. sections_under(true, true))
print("tsec_nodeep " .. sections_under(false, true))
print("tsec_noord " .. sections_under(true, false))
print("tsec_neither " .. sections_under(false, false))
-- A NAME CLICK LIGHTS THE CHART BUTTON, or Orders when there is no chart.
local function name_click(deep)
    sections_under(deep, true)
    EX.trade_page = 1
    local cp = EX.selection_page_index()
    if cp then EX.trade_page = cp end
    return tostring(EX.section_on and EX.section_on())
end
print("tsec_name " .. name_click(true) .. "," .. name_click(false))
EX.feature = real_feature
EX.trade_page = 1
EX.mode = EX.MODE_HOUSES

-- THE LIST SHRINKING UNDER THE INDEX PAGE KEEPS THE PLAYER ON IT.
EX.house_page = EX.HOUSE_INDEX_PAGE
houses(4)
print("h_index_shrunk " .. EX.nav_label() .. "," .. tostring(EX.on_index()))
-- AND RE-ENTERING THE VIEW LEAVES IT.
EX.set_mode(EX.MODE_TRADE)
EX.set_mode(EX.MODE_HOUSES)
print("h_index_reset " .. tostring(EX.on_index()))
houses(41)
EX.house_page = 1

-- THE ARROWS PAGE THE GUIDE ALONE (2026-10-01): the lists scroll and Trade's chart and
-- ledger are buttons. Every tab view is one page, and an arrow on Trade moves nothing.
local pc = {}
for _, m in ipairs(EX.MODES) do EX.mode = m; pc[#pc + 1] = EX.page_count() end
print("arrows_pages " .. table.concat(pc, ","))
EX.mode = EX.MODE_TRADE
EX.trade_page = 1
EX.nav_click(EX.MODE_BTN)
print("arrows_trade_noop " .. EX.trade_page)
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

-- THE SECTION ON SCREEN CANNOT BE ONE THAT IS GONE (its button is what lights since
-- 2026-10-01; the counter shows on the guide only). THE COUNTER CANNOT READ "3/2". EX.trade_kind clamps and EX.page_index did not, so throwing
-- a switch while standing on the page it removes left the label naming a page that no longer
-- existed until an arrow was pressed.
EX.trade_page = 3
EX.feature = function(k) if k == "orders" then return false end return true end
print("idx_clamped " .. EX.section_on())
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
