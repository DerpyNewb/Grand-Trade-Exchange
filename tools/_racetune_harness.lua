-- THE RACE PROFILES, RUN. What EX.opt actually hands back for every (preset, race, knob), read
-- out of the shipped file rather than recomputed from the Python mirror.
--
-- Recomputing in Python would check the mirror against itself. The three things only running
-- the file can answer are whether the factor COMPOSES with a preset (rather than replacing it
-- or being replaced by it), whether the clamp and the rounding land where the bounds say, and
-- whether a knob off the whitelist is genuinely inert - all of which live in EX.race_apply and
-- in the order EX.opt calls it.
local SAVED = {}
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function(_, k, v) SAVED[k] = v end,
    get_saved_value = function(_, k) return SAVED[k] end,
    get_local_faction_name = function() return "player" end,
    get_faction = function() return false end,
    turn_number = function() return 10 end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])
EX.store = SAVED

-- The preset resolved the way EX.snapshot would have written it into the save: the preset's
-- own values over the file's constants. The race factor is NOT in here, which is the point -
-- it is applied on top, at read time, by EX.opt.
local function snap_for(preset)
    local t = {}
    for key, const in pairs(EX.TUNE_NUM) do t[key] = EX[const] end
    local p = EX.PRESETS[preset] or {}
    for key, v in pairs(p) do
        if EX.TUNE_NUM[key] then t[key] = v end
    end
    for _, key in ipairs(EX.TUNE_BOOL) do
        t[key] = (p[key] ~= nil) and p[key] or true
    end
    return t
end

local KEYS = {}
for k in pairs(EX.RACE_TUNABLE) do KEYS[#KEYS + 1] = k end
table.sort(KEYS)

local RACES = {}
for culture in pairs(EX.RACES) do RACES[#RACES + 1] = culture end
table.sort(RACES)

-- ---- EVERY COMBINATION, as the game would read it ----
for _, preset in ipairs({ "default", "easy", "hard", "ultra" }) do
    for _, culture in ipairs(RACES) do
        EX.race = EX.RACES[culture]
        EX.snap = snap_for(preset)
        local out_ = {}
        for _, k in ipairs(KEYS) do
            out_[#out_ + 1] = k .. "=" .. tostring(EX.opt(k))
        end
        print("opt " .. preset .. " " .. culture .. " " .. table.concat(out_, ","))
    end
end

-- ---- THE CHAOS DWARF INVARIANT ----
-- They carry no profile, so every knob must come back BYTE-IDENTICAL to what the snapshot
-- holds. This is the same rule seg = "" follows and it is what keeps live saves exact.
local same, differ = true, ""
for _, preset in ipairs({ "default", "easy", "hard", "ultra" }) do
    EX.race = EX.RACES["wh3_dlc23_chd_chaos_dwarfs"]
    local snap = snap_for(preset)
    EX.snap = snap
    for key in pairs(EX.TUNE_NUM) do
        if EX.opt(key) ~= snap[key] then
            same = false
            differ = differ .. preset .. ":" .. key .. " "
        end
    end
    for _, key in ipairs(EX.TUNE_BOOL) do
        if EX.opt(key) ~= snap[key] then
            same = false
            differ = differ .. preset .. ":" .. key .. " "
        end
    end
end
print("chd_untouched " .. tostring(same) .. " " .. (differ == "" and "-" or differ))

-- ---- AN UNCOVERED RACE ----
-- 23 of 27 cultures. EX.race is nil and every knob must pass straight through.
EX.race = nil
EX.snap = snap_for("hard")
local unc = true
for _, k in ipairs(KEYS) do
    if EX.opt(k) ~= EX.snap[k] then unc = false end
end
print("uncovered_passthrough " .. tostring(unc))

-- ---- A KNOB OFF THE WHITELIST IS INERT ----
-- The four spread-algebra knobs are excluded on purpose. A profile that names one must change
-- nothing at all, because a race factor on the spread mints gold.
EX.race = { tune = { spread = 0.5, ladder_step = 2.0, sell_floor = 0.1,
                     friendly_max = 4.0, house_cash_max = 9.0 } }
EX.snap = snap_for("default")
print("offlist spread=" .. tostring(EX.opt("spread"))
    .. " ladder_step=" .. tostring(EX.opt("ladder_step"))
    .. " sell_floor=" .. tostring(EX.opt("sell_floor"))
    .. " friendly_max=" .. tostring(EX.opt("friendly_max"))
    .. " house_cash_max=" .. tostring(EX.opt("house_cash_max")))

-- ---- BOOLEANS SURVIVE ----
-- EX.setting routes through EX.opt. A factor applied to `true` would make it a number, and
-- `EX.setting` returns `v ~= false`, so a broken boolean reads as ON forever.
EX.race = EX.RACES["wh2_main_skv_skaven"]
EX.snap = snap_for("easy")
print("bools rent=" .. tostring(EX.opt("warehouse_rent"))
    .. " demands=" .. tostring(EX.opt("hashut_demands"))
    .. " setting_rent=" .. tostring(EX.setting("warehouse_rent")))

-- ---- A GARBAGE FACTOR IS IGNORED ----
-- Not defensive noise: EX.RACES is hand-edited, and a string or a nil in a tune table would
-- otherwise throw inside the price path, which runs about once a second while the panel is up.
EX.race = { tune = { hostile_max = "lots", windup = false, div_yield = nil } }
EX.snap = snap_for("default")
local ok, err = pcall(function()
    return EX.opt("hostile_max"), EX.opt("windup"), EX.opt("div_yield")
end)
print("garbage ok=" .. tostring(ok) .. " hostile_max=" .. tostring(EX.opt("hostile_max"))
    .. " windup=" .. tostring(EX.opt("windup"))
    .. " err=" .. tostring(err))

-- ---- THE STRENGTH DIAL ----
-- The one control the player has over the whole feature. What is pinned here is that 0 is
-- GENUINELY off - the board must equal the Chaos Dwarf board key for key, not merely be close
-- to it - that the scaling is symmetric (a x0.6 softens exactly as far as a x1.4 sharpens, at
-- the same strength), and that a knob no profile touches is unmoved at every setting.
for _, st in ipairs({ 0, 0.5, 1, 2 }) do
    EX.race = EX.RACES["wh2_main_skv_skaven"]
    EX.snap = snap_for("default")
    EX.snap.race_strength = st
    local skv = {}
    for _, k in ipairs(KEYS) do skv[#skv + 1] = k .. "=" .. tostring(EX.opt(k)) end
    EX.race = EX.RACES["wh3_dlc23_chd_chaos_dwarfs"]
    EX.snap.race_strength = st
    local base = {}
    for _, k in ipairs(KEYS) do base[#base + 1] = k .. "=" .. tostring(EX.opt(k)) end
    print("strength" .. tostring(st) .. " skv " .. table.concat(skv, ","))
    print("strength" .. tostring(st) .. "_base chd " .. table.concat(base, ","))
end

-- A NEGATIVE STRENGTH IS CLAMPED, NOT INVERTED. An MCT slider cannot go below its own minimum,
-- but a hand-edited save or a mis-registered option can, and inverting the profile would make
-- the Skaven the FRIENDLIEST market in the game - a bug that reads as a design decision.
EX.race = EX.RACES["wh2_main_skv_skaven"]
EX.snap = snap_for("default")
EX.snap.race_strength = -3
print("negative hostile_max=" .. tostring(EX.opt("hostile_max"))
    .. " windup=" .. tostring(EX.opt("windup")))

-- ...and a strength that is not a number at all falls back to the shipped constant rather than
-- throwing in the price path.
EX.snap.race_strength = "lots"
local st_ok = pcall(function() return EX.opt("hostile_max") end)
print("badstrength ok=" .. tostring(st_ok)
    .. " hostile_max=" .. tostring(st_ok and EX.opt("hostile_max") or "THREW"))

-- ---- CUSTOM: THE PLAYER'S OWN SLIDERS ----
-- The preset path and the custom path are different code in EX.opt_live - a preset is a table
-- lookup, Custom is a live MCT read - and only one of them is exercised above. What is being
-- pinned is that MCT still WORKS under a profile (the slider moves the base) and that the
-- profile still applies on top of it (the slider is not the final number).
--
-- This is also the one place the panel and the game disagree: MCT shows 0.25 and a Skaven
-- board runs 0.55. There is no fix inside MCT - an option's tooltip is static text set at
-- registration, before any faction exists - so it is a documented gap, not a bug to catch.
EX.mct_raw = function(k)
    if k == "preset" then return "custom" end
    if k == "hostile_max" then return 0.20 end
    if k == "book_per_rung" then return 50 end
    return nil
end
EX.snap = nil
EX.race = EX.RACES["wh2_main_skv_skaven"]
local skv_h, skv_b = EX.opt("hostile_max"), EX.opt("book_per_rung")
EX.race = EX.RACES["wh3_dlc23_chd_chaos_dwarfs"]
local chd_h, chd_b = EX.opt("hostile_max"), EX.opt("book_per_rung")
EX.race = nil
local unc_h = EX.opt("hostile_max")
print("custom skv_hostile=" .. tostring(skv_h) .. " skv_book=" .. tostring(skv_b)
    .. " chd_hostile=" .. tostring(chd_h) .. " chd_book=" .. tostring(chd_b)
    .. " uncovered_hostile=" .. tostring(unc_h))
EX.mct_raw = function() return nil end

-- ---- A SNAPSHOT THAT HOLDS THE WRONG SHAPE ----
-- This is what the type guard in EX.race_apply is actually for, and the boolean case is NOT:
-- booleans are off the whitelist and the bounds lookup already returns them untouched.
--
-- The snapshot is a table read back out of a SAVE. A campaign made before a knob existed, an
-- MCT option mis-registered as a checkbox where the code wants a slider, a save edited by
-- hand - any of those puts a boolean or a string where a number belongs, and multiplying it
-- throws inside the price path rather than at load, so the failure surfaces as a dead panel
-- several turns later with nothing in the log pointing at the save.
EX.race = EX.RACES["wh2_main_skv_skaven"]
EX.snap = snap_for("default")
EX.snap.hostile_max = true
EX.snap.windup = "0.5"
EX.snap.book_per_rung = nil          -- absent entirely: EX.opt falls through to opt_live
local bad_ok, bad_err = pcall(function()
    return tostring(EX.opt("hostile_max")) .. tostring(EX.opt("windup"))
        .. tostring(EX.opt("book_per_rung"))
end)
print("badsnap ok=" .. tostring(bad_ok)
    .. " hostile_max=" .. tostring(bad_ok and EX.opt("hostile_max") or "THREW")
    .. " windup=" .. tostring(bad_ok and EX.opt("windup") or "THREW")
    .. " book_per_rung=" .. tostring(bad_ok and EX.opt("book_per_rung") or "THREW")
    .. " err=" .. tostring(bad_err))

-- ---- IT REACHES A CAMPAIGN WITH NO SNAPSHOT ----
-- EX.opt falls through to EX.opt_live before the first turn start. The factor must apply there
-- too, or the panel shows one set of prices until the turn ticks and another after.
EX.race = EX.RACES["wh2_main_skv_skaven"]
EX.snap = nil
print("presnapshot hostile_max=" .. tostring(EX.opt("hostile_max"))
    .. " windup=" .. tostring(EX.opt("windup")))

-- ---- AND IT IS NOT APPLIED TWICE ----
-- The snapshot is built from EX.opt_live. If the factor were applied there as well as in
-- EX.opt, a new campaign would run on factor-squared while an old one ran on factor.
EX.race = EX.RACES["wh2_main_skv_skaven"]
EX.snap = nil
local live = {}
for _, k in ipairs(KEYS) do live[k] = EX.opt_live(k) end
EX.snap = live
local double = ""
for _, k in ipairs(KEYS) do
    if EX.opt(k) ~= EX.race_apply(k, EX[EX.TUNE_NUM[k]]) then
        double = double .. k .. " "
    end
end
print("no_double_apply " .. tostring(double == "") .. " " .. (double == "" and "-" or double))

-- ---- THE UNCOVERED-CULTURE WARNING ----
-- A culture missing from EX.CULTURE_WANTS contributes exactly zero world demand, silently. A
-- build-time check can only see the cultures installed on the build machine, so the GAME has to
-- report the ones it meets. What is measured here: it fires for a real share, stays quiet under
-- the threshold, stays quiet for a covered culture, and says each culture ONCE however many
-- times the scan runs - a per-turn scan repeating a line forever is how a log stops being read.
local said = {}
EX.say = function(cat, msg) said[#said + 1] = cat .. "|" .. msg end
EX.said_uncovered = nil
local share = {
    wh_main_emp_empire = 0.50,          -- covered
    some_mod_culture = 0.24,            -- uncovered, well over the threshold
    tiny_mod_culture = 0.005,           -- uncovered, under it
    another_mod_culture = 0.01,         -- uncovered, exactly ON the threshold
}
EX.warn_uncovered(share)
local first = #said
EX.warn_uncovered(share)
EX.warn_uncovered(share)
local named, tiny = {}, 0
for _, line in ipairs(said) do
    for c in string.gmatch(line, "([%%w_]+) holds") do named[#named + 1] = c end
    if string.find(line, "tiny_mod_culture", 1, true) then tiny = tiny + 1 end
end
table.sort(named)
print("uncovered_warn first=" .. first .. " total=" .. #said
    .. " named=" .. table.concat(named, ",") .. " tiny=" .. tiny)

-- ...and a nil share (no scan has completed) must not throw.
local ok_nil = pcall(function() EX.warn_uncovered(nil) end)
print("uncovered_warn_nil " .. tostring(ok_nil))
