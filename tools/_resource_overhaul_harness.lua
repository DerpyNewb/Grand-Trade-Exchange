-- Derpy Resource Overhaul in the Exchange: the shipped file, run twice.
--
-- RUN 1 has no `common` at all, which is what the game looks like to this file when More
-- Resources is not installed (the loc read finds nothing): the join must add nothing and every
-- list, page count and the median must be exactly what they were before the join existed.
--
-- RUN 2 answers the loc read for every good BUT ONE (wool), so the join is measured per good
-- and not as one switch, and answers the building effect read with a string shaped the way the
-- game returns it (empty entries between slots, a two-word good, a good that did not join).
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
local SCRIPT = [[%s]]

local function stub_panel()
    EX.layout = function() end
    EX.refresh_panel = function() end
    EX.store = {}
    EX.race = EX.RACES["wh3_dlc23_chd_chaos_dwarfs"]
    EX.houses = { "h1", "h2" }
    EX.guild = function() return EX.houses end
    EX.stance_of = function() return 0 end
    EX.closed_banner = function() return nil end
    EX.faction_display = function(k) return k end
    -- the race binding is _race_harness.lua's to measure; here Offerings must simply open
    EX.covered = function() return true end
    EX.MAX_ROWS = 20
end

-- the median EX.apply_prices takes, with everything around it stubbed out
local function median_with(base_supply, mr_supply)
    EX.me = function() return true end
    EX.supply, EX.owners = {}, {}
    for i, res in ipairs(EX.COMMODITIES) do
        EX.supply[res] = (i <= EX.BASE_COUNT) and base_supply or mr_supply
    end
    EX.house_median = function() return 1 end
    EX.target_rung = function() return 1 end
    EX.setv = function() end
    EX.say = function() end
    EX.apply_prices()
    return EX.med
end

-- A GOODS VIEW WITH ITS LIST BUILT (the lists are drawn whole since 2026-10-02): how many rows
-- it draws, how many distinct goods they are, and the list's length.
local function windows_of(mode)
    EX.set_mode(mode)
    -- a locked tab leaves the view where it was, and every number below would be another view's
    assert(EX.mode == mode, "set_mode refused " .. mode)
    EX.list_key = "built"
    local w = EX.mode_instruments()
    EX.list_key = nil
    local seen, total = {}, 0
    for _, r in ipairs(w) do
        if not seen[r] then seen[r] = true; total = total + 1 end
    end
    return #w, total, EX.scroll_n()
end

local function fund_baskets()
    local out = {}
    for culture in pairs(EX.CULTURE_WANTS) do
        local f = EX.derived_fund(culture)
        if f then out[culture] = table.concat(f.goods, ",") end
    end
    return out
end
local function check_optional_appetites(joined, original_funds, omitted)
    assert(type(EX.MR_CULTURE_WANTS) == "table", "missing optional culture appetites")
    local goods, positive, negative = {}, {}, {}
    for _, item in ipairs(EX.MR) do goods[item[1]] = true end
    for _, field in ipairs({ "MR_WAR_APPETITE", "MR_BUILD_APPETITE" }) do
        local count = 0
        for res, value in pairs(EX[field]) do
            assert(goods[res], field .. " unknown good: " .. res)
            assert(type(value) == "number" and value >= -1 and value <= 1, "invalid appetite")
            count = count + 1
        end
        assert(count == #EX.MR, field .. " incomplete; include neutral zeroes")
    end
    for culture, wants in pairs(EX.MR_CULTURE_WANTS) do
        assert(EX.CULTURE_WANTS[culture], "unknown optional culture: " .. culture)
        local plus, minus = false, false
        for res, value in pairs(wants) do
            assert(goods[res], "unknown optional preference: " .. res)
            assert(type(value) == "number" and value >= -1 and value <= 1, "invalid culture preference")
            if value > 0 then positive[res], plus = true, true end
            if value < 0 then negative[res], minus = true, true end
        end
        assert(plus and minus, "one-sided optional culture: " .. culture)
    end
    local now = fund_baskets()
    for culture, wants in pairs(EX.CULTURE_WANTS) do
        local optional = EX.MR_CULTURE_WANTS[culture]
        assert(optional, "culture missing optional profile: " .. culture)
        for res in pairs(goods) do
            assert(positive[res] and negative[res], "good lacks opposing culture preferences: " .. res)
            local active = joined and res ~= omitted
            if active then
                assert(wants[res] == (optional[res] or 0), "joined culture preference missing: " .. res)
                assert(EX.WAR_APPETITE[res] == EX.MR_WAR_APPETITE[res], "joined war appetite missing: " .. res)
                assert(EX.BUILD_APPETITE[res] == EX.MR_BUILD_APPETITE[res], "joined build appetite missing: " .. res)
            else
                assert(wants[res] == nil and EX.WAR_APPETITE[res] == nil and EX.BUILD_APPETITE[res] == nil,
                    "unavailable good acquired an appetite: " .. res)
            end
        end
        if original_funds[culture] then assert(now[culture] == original_funds[culture], "fund basket changed: " .. culture) end
    end
end

-- RUN 1 ---------------------------------------------------------------------------------------
dofile(SCRIPT)
stub_panel()
local original_funds = fund_baskets()
print("r1_join " .. EX.join_more_resources())
check_optional_appetites(false, original_funds)
print("r1_n " .. #EX.COMMODITIES .. " " .. EX.BASE_COUNT)
print("r1_mr_rows " .. #EX.MR)
print("r1_trade " .. table.concat({ windows_of(EX.MODE_TRADE) }, " "))
print("r1_stats " .. table.concat({ windows_of(EX.MODE_STATS) }, " "))
print("r1_median " .. tostring(median_with(100, 0)))

-- RUN 2 ---------------------------------------------------------------------------------------
local ASKED = {}
local CCO = "derpy_effect_region_resource_amber_production=6,derpy_effect_region_resource_pearls_production=6,,,"
    .. "derpy_effect_region_resource_wool_production=8,derpy_effect_region_resource_black_lotus_production=12,,"
common = {
    get_localised_string = function(k)
        if k == "resources_onscreen_text_res_derpy_wool" then return "" end
        if string.find(k, "^resources_onscreen_text_res_derpy_") then return "named" end
        return ""
    end,
    get_context_value = function(ctx, id, expr)
        ASKED[#ASKED + 1] = ctx .. "|" .. tostring(id) .. "|" .. tostring(expr == EX.MR_EXPR)
        if id == "666" then error("no settlement") end
        return CCO
    end,
}
dofile(SCRIPT)
stub_panel()
print("r2_join " .. EX.join_more_resources())
check_optional_appetites(true, original_funds, "res_derpy_wool")
print("r2_appetites " .. #EX.MR)
print("r2_again " .. EX.join_more_resources() .. " " .. #EX.COMMODITIES)
print("r2_n " .. #EX.COMMODITIES .. " " .. EX.BASE_COUNT)
print("r2_first17 " .. tostring(EX.COMMODITIES[17]) .. " " .. tostring(EX.COMMODITIES[18]))
print("r2_wool " .. tostring(EX.is_commodity("res_derpy_wool")) .. " " .. tostring(EX.INFO["res_derpy_wool"]))
print("r2_amber " .. tostring(EX.is_commodity("res_derpy_amber")) .. " " .. tostring(EX.display("res_derpy_amber"))
      .. " | " .. tostring(EX.BOON["res_derpy_amber"]))

local function region(cqi)
    return {
        resource_exists = function() return false end,
        slot_list = function() return { num_items = function() return 0 end } end,
        settlement = function() return { cqi = function() return cqi end } end,
    }
end
EX_PRODUCTION = {}
local got = {}
for _, g in ipairs(EX.region_goods(region(42))) do got[#got + 1] = g[1] .. "=" .. g[2] end
table.sort(got)
print("r2_goods " .. table.concat(got, ","))
print("r2_asked " .. tostring(ASKED[1]))
local ok, bad = pcall(EX.region_goods, region(666))
print("r2_throws " .. tostring(ok) .. " " .. tostring(ok and #bad))

-- Equal supply isolates demand, rather than crediting scarcity for a price movement.
;(function()
    local opt, feature = EX.opt, EX.feature
    local shock, book, worldbook = EX.shock_shift, EX.book_shift, EX.world_book_shift
    local target = EX.target_rung
    EX.opt = function(k)
        if k == "ai_gain" then return 4 end
        if k == "ai_max_rungs" then return 2 end
        return opt(k)
    end
    EX.feature = function() return false end
    EX.shock_shift, EX.book_shift, EX.world_book_shift = function() return 0 end, function() return 0 end, function() return 0 end
    EX.pressure, EX.owners, EX.current = {}, {}, {}
    EX.culture_share = { wh_main_emp_empire = 1 }
    EX.war_index = EX.WAR_BASELINE
    local up, down = EX.appetite_shift("res_derpy_blackpowder"), EX.appetite_shift("res_derpy_grain")
    assert(up == 2 and down == -2, "culture price direction or clamp changed")
    local supply = { res_derpy_blackpowder = 100, res_derpy_grain = 100 }
    local buy = target("res_derpy_blackpowder", supply, {}, 100)
    local sell = target("res_derpy_grain", supply, {}, 100)
    assert(buy - sell == 4 and EX.price_at(buy) > EX.BASE_COST and EX.price_at(sell) < EX.BASE_COST,
        "equal-supply prices ignored optional appetites")
    print("r2_sensitivity " .. EX.price_at(buy) .. " " .. EX.price_at(sell))
    -- Legacy war pricing and per-culture drift remain alternative branches.
    EX.culture_share = { unknown = 1 }
    EX.war_index = EX.WAR_BASELINE + 1
    assert(EX.appetite_shift("res_derpy_blackpowder") == 2, "war demand missing")
    assert(EX.appetite_shift("res_derpy_jade") < 0, "wartime luxury sign reversed")
    assert(EX.world_appetite("res_derpy_books") == 0, "explicit war-neutral not honored")
    EX.feature = function(k) return k == "appetite_drift" end
    EX.culture_share, EX.culture_share_prev = { wh_main_emp_empire = 1 }, { wh_main_emp_empire = 0.5 }
    EX.culture_war = { wh_main_emp_empire = EX.WAR_BASELINE }
    assert(EX.appetite_shift("res_derpy_starwood") == 1, "neutral culture entry lost building drift")
    assert(EX.appetite_shift("res_derpy_feathers") == 0, "growth-neutral good moved")
    EX.culture_share_prev.wh_main_emp_empire = 1
    EX.culture_war.wh_main_emp_empire = EX.WAR_BASELINE + 0.2
    local with_world_war = EX.world_appetite("res_derpy_blackpowder")
    EX.war_index = EX.WAR_BASELINE
    assert(EX.world_appetite("res_derpy_blackpowder") == with_world_war, "war counted twice with drift")
    -- Actual actor desire uses the same new culture and war coefficients.
    EX.actors = { actor = { culture = "wh_main_emp_empire", war = false } }
    EX.wbook = {}
    local peace = EX.world_desire("actor", "res_derpy_blackpowder")
    EX.actors.actor.war = true
    local war = EX.world_desire("actor", "res_derpy_blackpowder")
    assert(math.abs(peace - 1.3) < 0.000001 and math.abs(war - 2.3) < 0.000001, "AI actor ignored new tastes")
    EX.opt, EX.feature = opt, feature
    EX.shock_shift, EX.book_shift, EX.world_book_shift = shock, book, worldbook
end)()

print("r2_median " .. tostring(median_with(100, 0)))

-- TRADE INCOME is the vanilla 17's too: a faction making only a Resource Overhaul good at a glut
-- price has no trade-income level, one making a vanilla good at the same price has one.
EX.owners = { res_derpy_amber = { only_mr = 10 }, res_rom_iron = { vanilla = 10 } }
EX.price = function() return EX.BASE_COST / 2 end
print("r2_income " .. EX.trade_income_level("only_mr") .. " " .. EX.trade_income_level("vanilla"))
print("r2_trade " .. table.concat({ windows_of(EX.MODE_TRADE) }, " "))
print("r2_chart " .. tostring(EX.chart_page_index()) .. " " .. table.concat(EX.trade_pages(), ","))
print("r2_stats " .. table.concat({ windows_of(EX.MODE_STATS) }, " "))
print("r2_offer " .. table.concat({ windows_of(EX.MODE_OFFER) }, " "))

-- the arrows' counter on a goods view: one page, whatever the length
EX.set_mode(EX.MODE_STATS)
print("r2_nav " .. EX.nav_label())

-- Full installation, including the good deliberately missing from run 2.
common.get_localised_string = function(k)
    if string.find(k, "^resources_onscreen_text_res_derpy_") then return "named" end
    return ""
end
dofile(SCRIPT)
stub_panel()
assert(EX.join_more_resources() == #EX.MR, "full installation did not join all goods")
check_optional_appetites(true, original_funds)
assert(EX.CULTURE_WANTS.wh3_main_ksl_kislev.res_derpy_wool == 0.4, "full-installation wool taste missing")
print("r3_join " .. EX.mr_joined)
print("r3_again " .. EX.join_more_resources() .. " " .. #EX.COMMODITIES)

-- Processed-only supply is actual recent output, never an idle workshop or stale owner's book.
local bake_region = region(123)
bake_region.name = function() return "bakery" end
bake_region.owning_faction = function() return {name=function() return "baker" end} end
DERPY_MR_FLOWS = {state={economy={bakery={f="baker",paid={bake=4}}}}}
DERPY_MR_FLOWS_ECONOMY = {bake={output={"hardtack",12}}}
local now = 4
cm.model = function() return {turn_number=function() return now end} end
local function biscuits()
    local n=0
    for _,pair in ipairs(EX.region_goods(bake_region)) do
        if pair[1]=="res_derpy_hardtack" then n=n+pair[2] end
    end
    return n
end
assert(biscuits()==12,"paid biscuits missing from Exchange supply")
now=5;assert(biscuits()==12,"last owner-cycle batch missing")
now=6;assert(biscuits()==0,"stale biscuits counted as recurring production")
now=3;assert(biscuits()==0,"future batch counted")
now=4;DERPY_MR_FLOWS.state.economy.bakery.f="former_owner"
assert(biscuits()==0,"captured bakery kept former owner's production")
DERPY_MR_FLOWS.state.economy.bakery=nil
assert(biscuits()==0,"idle bakery invented supply")
DERPY_MR_FLOWS=nil
assert(biscuits()==0,"missing main mod invented supply")
