-- Runs the SHIPPED log code. Everything else about the panel is stubbed; the point is the
-- ring buffer, the dedup, the pack/unpack round trip and log_scan's edge detection.
local TURN = 1
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    save_named_value = function() end,
    load_named_value = function(_, _, d) return d end,
    get_saved_value = function() return nil end,
    callback = function() end,
    model = function() return { turn_number = function() return TURN end } end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])

EX.store = {}

-- ORDER AND DEDUP -----------------------------------------------------------------------
EX.LOG = {}
EX.log_add("Gems", "first")
EX.log_add("Gems", "second")
print("newest_first " .. EX.LOG[1][3] .. "," .. EX.LOG[2][3])

EX.log_add("Gems", "second")                    -- identical, same turn
print("dedup_same_turn " .. #EX.LOG)
TURN = 2
EX.log_add("Gems", "second")                    -- identical, LATER turn: a real repeat
print("kept_next_turn " .. #EX.LOG)
print("turn_stamped " .. EX.LOG[1][1] .. "," .. EX.LOG[2][1])

-- A nil field must not land a half-written entry that unpack_log would then drop silently.
local before = #EX.LOG
EX.log_add("Gems", nil)
EX.log_add(nil, "detail")
print("nil_rejected " .. tostring(#EX.LOG == before))

-- THE CAP -------------------------------------------------------------------------------
EX.LOG = {}
for i = 1, EX.LOG_MAX + 25 do
    TURN = i
    EX.log_add("Gems", "entry " .. i)
end
print("cap " .. #EX.LOG)
print("cap_keeps_newest " .. EX.LOG[1][3])

-- WHAT THE PANEL DRAWS ------------------------------------------------------------------
-- The renderer walks EX.mode_instruments() and takes one line per entry, so that count IS the
-- number of rows the view has. Printed alongside so the check compares the two rather than a
-- constant that was right when it was written.
print("rows_available " .. #EX.mode_instruments())
local lines = EX.log_lines()
print("drawn " .. #lines)
print("drawn_left " .. lines[1][1])
EX.LOG = {}
local empty = EX.log_lines()
print("empty_rows " .. #empty)
-- GUARDED, so an empty return reports as an assertion rather than killing this harness with
-- the same nil index the panel would die on - which is the finding, not a harness fault.
print("empty_left " .. (empty[1] and empty[1][1] or "NOTHING"))

-- THE KEY, THE NAME AND THE ICON --------------------------------------------------------
-- log_subject replaces EX.display_name, which was never defined; the `and ... or` guard around
-- it meant the missing function drew the raw key instead of erroring.
EX.LOG = {}
TURN = 5
local probe = EX.COMMODITIES[1]
EX.log_add(EX.log_subject(probe), "probe", probe)
print("subject_named " .. tostring(EX.LOG[1][2] ~= probe and EX.LOG[1][2] ~= ""))
print("subject_matches_display " .. tostring(EX.LOG[1][2] == EX.display(probe)))
print("key_kept " .. tostring(EX.LOG[1][4] == probe))
local kl = EX.log_lines()
print("line_carries_key " .. tostring(kl[1][3] == probe))
print("icon_for_key " .. tostring(EX.icon(probe) ~= nil))
-- THE HOUSE BRANCH. A house is not in EX.INFO, so EX.display would fall through to EX.short
-- and print a truncated faction key where the panel's other four views print a house name.
-- Stubbed rather than discovered because the harness has no campaign to discover houses from.
do
    local real_is_house, real_fd = EX.is_house, EX.faction_display
    EX.is_house = function(r) return r == "wh3_dlc23_chd_zhatan" end
    EX.faction_display = function() return "Zhatan the Black" end
    print("house_named " .. tostring(EX.log_subject("wh3_dlc23_chd_zhatan")))
    print("commodity_still_display " .. tostring(EX.log_subject(probe) == EX.display(probe)))
    EX.is_house, EX.faction_display = real_is_house, real_fd
end
-- A market closure has no instrument, so its line must carry no key - the row hides its icon
-- rather than keeping whatever picture the previous line left there.
EX.log_add("Market", "closed", nil)
print("no_key_is_empty " .. tostring(EX.LOG[1][4] == ""))
print("no_key_line " .. tostring(EX.log_lines()[1][3] == ""))
print("empty_line_key " .. tostring((function() EX.LOG = {} return EX.log_lines()[1][3] end)()))

-- THE ROUND TRIP ------------------------------------------------------------------------
-- The nasty field is the whole reason the separators are control bytes: a display name or a
-- sentence carrying ';' or '|' must not eat the rest of the log.
EX.LOG = {}
TURN = 7
EX.log_add("Legion of Azgorh; Zharr-Naggrund", "Refused | holds 30 of 44 lots; despises you.",
           "res_rom_furs")
TURN = 8
EX.log_add("Market", "CLOSED.")
local packed = EX.pack_log()
-- EX.pkey, because the log is a PER-PLAYER saved key since the multiplayer split - the
-- runtime's own key builder, so this names whatever the runtime names.
print("saved_on_add " .. tostring(EX.store[EX.pkey(EX.SAVE_LOG)] == packed))
EX.LOG = {}
EX.unpack_log(packed)
print("rt_count " .. #EX.LOG)
print("rt_turn " .. EX.LOG[2][1])
print("rt_subject " .. EX.LOG[2][2])
print("rt_detail " .. EX.LOG[2][3])
print("rt_type " .. type(EX.LOG[2][1]))
print("rt_key " .. tostring(EX.LOG[2][4]))
-- A LOG SAVED BEFORE THE ICON SHIPPED has three fields. It must load, keeping its text.
EX.unpack_log("9" .. EX.LOG_FS .. "Old" .. EX.LOG_FS .. "from before the icon")
print("rt_legacy " .. #EX.LOG .. "," .. tostring(EX.LOG[1] and EX.LOG[1][2])
      .. "," .. tostring(EX.LOG[1] and EX.LOG[1][4] == ""))

EX.LOG = { { 1, "x", "y" } }
EX.unpack_log(nil)
print("rt_nil " .. #EX.LOG)
EX.unpack_log("")
print("rt_empty " .. #EX.LOG)

-- A save written before the cap shrank must not restore more rows than the cap allows.
local many = {}
for i = 1, EX.LOG_MAX + 10 do many[#many + 1] = i .. EX.LOG_FS .. "s" .. EX.LOG_FS .. "d" end
EX.unpack_log(table.concat(many, EX.LOG_RS))
print("rt_capped " .. #EX.LOG)

-- LOG_SCAN RECORDS CHANGES, NOT STATE ---------------------------------------------------
-- market_closed / refused_by are covered by check_lua_books; stubbed here so the edge
-- detection is what is being measured.
EX.COMMODITIES = { "res_gems" }
EX.log_subject = function(r) return r end
EX.faction_display = function(f) return f end
EX.book_of = function() return 30 end
EX.guild_book = function() return 44 end
local CLOSED, REFUSED = nil, nil
EX.market_closed = function() return CLOSED end
EX.refused_by = function() return REFUSED end

EX.LOG, EX.log_seen = {}, {}
TURN = 10
EX.log_scan()
print("scan_quiet " .. #EX.LOG)

CLOSED = "wh3_dlc23_chd_zhatan"
EX.log_scan()
print("scan_closed " .. #EX.LOG)
TURN = 11
EX.log_scan()
TURN = 12
EX.log_scan()
print("scan_closure_once " .. #EX.LOG)
CLOSED = nil
EX.log_scan()
print("scan_reopen " .. #EX.LOG)
print("scan_reopen_text " .. EX.LOG[1][3])

EX.LOG, EX.log_seen = {}, {}
REFUSED = "wh3_dlc23_chd_zhatan"
TURN = 20
EX.log_scan()
TURN = 21
EX.log_scan()
print("scan_refusal_once " .. #EX.LOG)
print("scan_key " .. tostring(EX.LOG[1][4]))
print("scan_refusal_text " .. EX.LOG[1][3])
REFUSED = nil
EX.log_scan()
print("scan_lift " .. #EX.LOG)
print("scan_lift_text " .. EX.LOG[1][3])
-- A DIFFERENT house taking over the refusal is a new fact, not the same standing one.
REFUSED = "wh3_dlc23_chd_astragoth"
EX.log_scan()
REFUSED = "wh3_dlc23_chd_zhatan"
EX.log_scan()
print("scan_handover " .. #EX.LOG)

-- THE WORLD'S OWN ENTRIES ----------------------------------------------------------------
-- Added 2026-09-09 with the AI logging. Four writers, and the property that matters most is
-- not what any of them SAYS: it is that none of them resolves a faction name. All four run
-- inside FactionTurnStart, where common.get_localised_string took the process down at turn 1
-- of a fresh campaign with no error, no minidump and pcall making no difference.
local LOC = 0
common = { get_localised_string = function() LOC = LOC + 1 return "SHOULD NOT HAPPEN" end }

-- THE GUILD'S BOOKS. The real EX.step_books loop runs against stubbed accessors, so the
-- tallies are measured against what the loop ACTUALLY did rather than recomputed beside it.
-- Two houses, and only one of them sells: the sell branch needs a non-empty book AND a
-- negative desire, which is the pair a tally written by eye gets wrong.
EX.COMMODITIES = { "res_gems", "res_rom_furs" }
EX.INFO = { res_gems = { "Gemstones", "x" }, res_rom_furs = { "Furs", "x" } }
EX.BOOK_TRADE_MAX = 5
EX.opt = function(k) if k == "spread" then return 0.1 end return 1 end
EX.hold_guild, EX.free_guild = function() end, function() end
EX.price = function() return 100 end
EX.pay_house = function() return 0 end
EX.guild = function() return { "h_one", "h_two" } end
local BOOKS = { h_one = { res_gems = 0, res_rom_furs = 7 },
                h_two = { res_gems = 0, res_rom_furs = 0 } }
EX.book_of = function(h, r) return BOOKS[h][r] end
EX.set_book = function(h, r, v) BOOKS[h][r] = v end
-- h_one wants gems and is dumping furs; h_two wants gems and holds nothing to sell.
EX.house_desire = function(h, r)
    if r == "res_gems" then return 1 end
    return h == "h_one" and -1 or 1
end
EX.house_budget = function(h) return h == "h_one" and 4 or 6 end
EX.step_books()
local f = EX.book_flow
print("flow_bought " .. f.bought)
print("flow_sold " .. f.sold)
print("flow_houses " .. f.houses)
print("flow_top_buy " .. f.buy.res_gems .. "," .. tostring(f.buy.res_rom_furs))
print("flow_top_sell " .. tostring(f.sell.res_gems) .. "," .. f.sell.res_rom_furs)

-- THE REAL APPETITE LINE, ONCE, BEFORE IT IS STUBBED. Everything below replaces it with a
-- constant, so without this the loc counter at the foot of the file would be measuring a stub
-- and the shipped EX.appetite_summary - which build_world_log calls every turn - would never
-- be asked whether it localises anything.
EX.world_appetite = function(r) return r == "res_gems" and 2 or -3 end
EX.war_index = 0.4
EX.is_house = function() return false end
EX.log_appetite = nil
-- THE FLOW IS PUT BACK. step_books above filled it and every guild-line check below reads it;
-- clearing it here to isolate the appetite would quietly turn four of those into "no line".
local keep_flow = EX.book_flow
EX.book_flow = nil
EX.build_world_log()
EX.build_world_log()
print("real_appetite " .. tostring(EX.log_appetite))
EX.book_flow = keep_flow

-- THE LINES. Built once from that flow, then written to each player in turn.
EX.appetite_summary = function() return "World at war: 40%%.  Wanted: Gemstones." end
EX.log_appetite = nil
EX.build_world_log()
print("world_first " .. #EX.world_lines)          -- appetite is not news on the first look
EX.appetite_summary = function() return "World at war: 55%%.  Wanted: Furs." end
EX.build_world_log()
print("world_changed " .. #EX.world_lines)
print("world_guild " .. EX.world_lines[1][2])
print("world_guild_key " .. EX.world_lines[1][3])
print("world_appetite " .. tostring(EX.world_lines[2] and EX.world_lines[2][1]))

-- WRITTEN PER PLAYER, and the same lines twice: two humans each get their own copy. A
-- build_world_log called per player instead would decide "changed" once and swallow it for
-- everybody after the first.
EX.LOG = {}
TURN = 30
EX.flush_world_log()
local first = #EX.LOG
EX.LOG = {}
EX.flush_world_log()
print("flush_per_player " .. first .. "," .. #EX.LOG)

-- AN UNCHANGED APPETITE IS NOT NEWS, however many times the turn round runs.
EX.build_world_log()
print("world_unchanged " .. #EX.world_lines)

-- A QUIET TURN WRITES NOTHING. Every house priced out of trading is not an event.
EX.book_flow = { bought = 0, sold = 0, houses = 0, buy = {}, sell = {} }
EX.build_world_log()
print("world_quiet " .. #EX.world_lines)

-- THE DIVIDEND LINE. Two paying houses, one holding nothing.
EX.houses = { "h_one", "h_two", "h_three" }
EX.is_delisted = function() return false end
EX.held = function(h) return h == "h_three" and 0 or 2 end
EX.dividend = function() return 30 end
EX.setting = function() return false end
EX.who = function() return "player" end
cm.treasury_mod = function() end
EX.LOG = {}
EX.pay_dividends()
print("div_line " .. tostring(EX.LOG[1] and EX.LOG[1][3]))
-- Nothing held is not a line.
EX.held = function() return 0 end
EX.LOG = {}
EX.pay_dividends()
print("div_silent " .. #EX.LOG)

-- THE SHOCK LINE. It has to survive the bulletin, which the player dismisses.
EX.shocked = { res_gems = true }
EX.shock = { res_gems = 3.4 }
EX.shock_why = { res_gems = "raided" }
EX.shock_shift = function() return 3 end
EX.feed = function() return 1 end
EX.short = function(r) return r end
cm.show_message_event = function() end
EX.LOG = {}
EX.announce_shocks()
print("shock_line " .. tostring(EX.LOG[1] and EX.LOG[1][3]))
print("shock_subject " .. tostring(EX.LOG[1] and EX.LOG[1][2]))
print("shock_key " .. tostring(EX.LOG[1] and EX.LOG[1][4]))

-- THE PLAYER'S OWN LEDGER: rent, an offering, and a tithe from demand to answer. Each wrote
-- nothing to the Log - rent reached the treasury as an unexplained lump and the tithe lived in
-- one event-feed message - so these are four of the writers the loc counter below must cover.
local HELD = { res_gems = 400, res_rom_iron = 200 }
EX.held = function(r) return HELD[r] or 0 end
EX.is_house = function() return false end
EX.setting = function() return true end
EX.log_subject = function(r) return EX.display(r) end
cm.faction_add_pooled_resource = function(_, _f, _k, _why, d) end
cm.apply_effect_bundle = function() end
cm.random_number = function() return 1 end
cm.turn_number = function() return TURN end
cm.set_saved_value = function() end
EX.panel = function() return nil end
is_uicomponent = is_uicomponent or function() return false end
EX.offer_until, EX.offerings_made = {}, 0
EX.LOG = {}
EX.charge_carry()
print("rent_line " .. tostring(EX.LOG[1] and EX.LOG[1][2]) .. "|" .. tostring(EX.LOG[1] and EX.LOG[1][3]))
EX.LOG = {}
EX.apply_offer("res_gems")
print("offer_line " .. tostring(EX.LOG[1] and EX.LOG[1][3]))
EX.LOG = {}
EX.demand_res, EX.demand_tier, EX.demand_due = nil, nil, 0
local asked = EX.fire_demand()
print("tithe_asked " .. tostring(asked) .. "|" .. tostring(EX.LOG[1] and EX.LOG[1][3]))
EX.pay_demand()
print("tithe_paid " .. tostring(EX.LOG[1] and EX.LOG[1][3]))
EX.fire_demand()
TURN = TURN + EX.DEMAND_GRACE
EX.LOG = {}
EX.check_demand()
print("tithe_wrath " .. tostring(EX.LOG[1] and EX.LOG[1][3]))

-- AND THE ONE THAT MATTERS. Not one of the four asked the game to localise anything.
print("turn_loc_calls " .. LOC)
