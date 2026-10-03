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

-- RUN 1 ---------------------------------------------------------------------------------------
dofile(SCRIPT)
stub_panel()
print("r1_join " .. EX.join_more_resources())
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
