-- THE PRESETS AND THE FREEZE, run against the SHIPPED file.
--
-- Everything the static checks can do is read source. What they cannot see is what EX.opt
-- actually answers after a snapshot has been taken and the MCT panel has since been changed -
-- which is the entire promise of "fixed for the life of a campaign". That promise is not the
-- MCT lock: mct_option:set_context_specific is an empty function body and set_local_only is
-- commented out end to end, so the lock is a UI courtesy over a control the player could
-- reach by other means. The snapshot in the save is the enforcement, and this is where it is
-- proved.
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

-- THE STUB PANEL. PRESET is what the dropdown says; CUSTOM is what the sliders and checkboxes
-- say, and is only ever read when PRESET is "custom".
PRESET = "default"
CUSTOM = {}
MCT_PRESENT = true
function get_mct()
    if not MCT_PRESENT then return nil end
    return { get_mod_by_key = function()
        return { get_option_by_key = function(_, k)
            return { get_finalized_setting = function()
                if k == "preset" then return PRESET end
                return CUSTOM[k]
            end }
        end }
    end }
end

local function every_key()
    local t = {}
    for k in pairs(EX.TUNE_NUM) do t[#t + 1] = k end
    for _, k in ipairs(EX.TUNE_BOOL) do t[#t + 1] = k end
    table.sort(t)
    return t
end
local KEYS = every_key()

-- EVERY PRESET, EVERY KNOB, read back the way the game reads it. Compared in Python against
-- the same EX.PRESETS table it parses for the range checks, so nothing here is a hand-typed
-- expectation that could drift with the values.
for _, p in ipairs({ "easy", "default", "hard", "ultra" }) do
    PRESET = p
    EX.snap = nil
    for _, k in ipairs(KEYS) do
        print("p_" .. p .. "_" .. k .. " " .. tostring(EX.opt(k)))
    end
end

-- CUSTOM READS THE PANEL. One knob of each kind, plus the two failure shapes: a slider whose
-- option answers with a boolean, and one the panel has nothing for at all. Both must come back
-- as the default rather than as a boolean or a nil - a nil here reaches arithmetic and takes
-- the script down somewhere else entirely, on a line that is not the bug.
PRESET = "custom"
EX.snap = nil
CUSTOM = { spread = 0.33, ai_max_rungs = 7, warehouse_rent = false, sell_floor = true }
print("custom_spread " .. tostring(EX.opt("spread")))
print("custom_rungs " .. tostring(EX.opt("ai_max_rungs")))
print("custom_rent " .. tostring(EX.opt("warehouse_rent")))
print("custom_setting_rent " .. tostring(EX.setting("warehouse_rent")))
print("custom_wrong_type " .. tostring(EX.opt("sell_floor")))
print("custom_absent " .. tostring(EX.opt("shock_gain")))

-- AN UNKNOWN KEY IS nil, NOT A PLAUSIBLE NUMBER. EX.setting's boolean face still fails open to
-- true, which is what the seven switches have always done when MCT is missing.
print("unknown_opt " .. tostring(EX.opt("no_such_knob")))
print("unknown_setting " .. tostring(EX.setting("no_such_knob")))

-- A PRESET NAME NOTHING DEFINES. A corrupted registry, or a preset renamed between versions
-- of this mod while a save carried the old name. Every knob must fall to its default: EX.opt
-- returning nil here puts nil into arithmetic on some later line that is not the bug.
PRESET = "no_such_preset"
EX.snap = nil
print("bogus_preset_spread " .. tostring(EX.opt("spread")))
print("bogus_preset_rent " .. tostring(EX.setting("warehouse_rent")))

-- MCT ABSENT IS THE DEFAULT PRESET THROUGHOUT.
MCT_PRESENT = false
EX.snap = nil
print("nomct_spread " .. tostring(EX.opt("spread")))
print("nomct_rent " .. tostring(EX.setting("warehouse_rent")))
print("nomct_preset " .. tostring(EX.preset_name()))
MCT_PRESENT = true

-- ===========================================================================================
-- THE FREEZE.
-- ===========================================================================================

-- Take a snapshot on Ultra, then change the panel underneath it. Every value must still be the
-- one the campaign started on.
EX.snap = nil
EX.store = {}
PRESET = "ultra"
print("snap_taken " .. tostring(EX.snapshot()))
local frozen = {}
for _, k in ipairs(KEYS) do frozen[k] = EX.opt(k) end

PRESET = "easy"
local moved = 0
for _, k in ipairs(KEYS) do
    if EX.opt(k) ~= frozen[k] then moved = moved + 1 end
end
print("moved_after_preset_change " .. moved)
print("still_ultra_spread " .. tostring(EX.opt("spread")))
print("preset_name_after_change " .. tostring(EX.preset_name()))

-- A SECOND SNAPSHOT IS A NO-OP. If it were not, every turn would re-read MCT and the campaign
-- would not be frozen at all - the failure would be invisible until a player changed a setting
-- mid-campaign and it took.
print("second_snapshot " .. tostring(EX.snapshot()))
print("still_ultra_after_second " .. tostring(EX.opt("spread")))

-- MCT UNINSTALLED MID-CAMPAIGN CHANGES NOTHING.
MCT_PRESENT = false
print("nomct_after_snap " .. tostring(EX.opt("spread")))
MCT_PRESENT = true

-- IT SURVIVES A LOAD. The store is what a save carries; the in-memory snapshot is not. Drop
-- the snapshot, keep the store, and the next turn start must adopt what was saved rather than
-- resolve a fresh one off whatever the panel now says.
local saved_store = EX.store
EX.snap = nil
EX.store = saved_store
PRESET = "easy"
local retaken = EX.snapshot()
print("retaken_on_load " .. tostring(retaken))
print("after_load_spread " .. tostring(EX.opt("spread")))
print("after_load_preset " .. tostring(EX.preset_name()))

-- AN EXISTING CAMPAIGN - no snapshot in the save - takes one from whatever MCT says now, and
-- is frozen from that point like any other.
EX.snap = nil
EX.store = {}
PRESET = "hard"
print("legacy_taken " .. tostring(EX.snapshot()))
print("legacy_spread " .. tostring(EX.opt("spread")))
PRESET = "easy"
print("legacy_frozen " .. tostring(EX.opt("spread")))

-- ===========================================================================================
-- THE LOG, which is deliberately NOT frozen.
-- ===========================================================================================
--
-- Same session, same snapshot: the log level must follow the panel while every economic value
-- above refuses to. LOGGED counts what actually reached out().
LOGGED = 0
function out() LOGGED = LOGGED + 1 end

local function say_all()
    LOGGED = 0
    EX.say("error", "x")
    for _, c in ipairs(EX.LOG_CATS) do EX.say(c, "x") end
    return LOGGED
end

CUSTOM.log_level = "normal"
print("log_normal " .. say_all())
CUSTOM.log_level = "off"
print("log_off " .. say_all())
CUSTOM.log_level = "errors"
print("log_errors " .. say_all())
CUSTOM.log_level = "verbose"
print("log_verbose " .. say_all())

-- ONE SUBSYSTEM SILENCED, the rest still speaking - and the error still through.
CUSTOM.log_level = "normal"
CUSTOM.log_price = false
print("log_one_off " .. say_all())
CUSTOM.log_price = nil

-- EX.trace is verbose-only.
CUSTOM.log_level = "normal"
LOGGED = 0
EX.trace("price", "x")
print("trace_at_normal " .. LOGGED)
CUSTOM.log_level = "verbose"
LOGGED = 0
EX.trace("price", "x")
print("trace_at_verbose " .. LOGGED)

-- AND THE LOG IS NOT IN THE SNAPSHOT. If it were, a campaign would be stuck at whatever level
-- it began on, which is the one setting that must be movable while a bug is happening.
print("log_in_snapshot " .. tostring(EX.snap.log_level ~= nil))
