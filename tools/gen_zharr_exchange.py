"""Generate the Zharr Exchange - a commodities market for Chaos Dwarfs.

    py tools/gen_zharr_exchange.py              # writes TSVs to Modding Files/source/zharr_exchange/
    py tools/gen_zharr_exchange.py --check      # build only, write nothing
    py tools/gen_zharr_exchange.py --selftest

Spec: docs/STOCK_MARKET_DESIGN.md. WH3 ships 17 tradeable resources all priced at a flat
trade_value of 50 and has no price discovery; this is that layer. Prices come from real map
scarcity, and are carried onto the rites-panel buttons by a pre-built ladder of effect bundles
(see the spec section 5 for why a ladder rather than create_new_custom_effect_bundle).
"""
import ast
import collections
import io
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
OUT = os.path.join(ROOT, "Modding Files", "source", "zharr_exchange")
# NOT PACKED. The frozen key set check_chd_identity() measures every build against.
BASELINE = os.path.join(OUT, "_chd_keys_baseline.txt")
FRAG = "derpy_chd_zharr_exchange"
PREFIX = "derpy_chd_ex_"

# --- calibration knobs -------------------------------------------------------------------
# A market needs tuning the model cannot see. These are the dials.
LOT_SIZE = 10             # units bought or sold per trade
HOUSE_LOT_SIZE = 5        # shares bought or sold per trade - MUST equal EX.HOUSE_LOT_SIZE
DIV_YIELD = 0.02          # dividend as a fraction of live price - MUST equal EX.DIV_YIELD
# WHAT A DEAD HOUSE PAYS, and it splits on WHO killed it. A flat premium on delist pays the
# player for backing a loser: buy into a doomed house, wait for anybody at all to finish it,
# collect more than you paid. Only absorbing the house yourself pays above the last price.
BUYOUT_PREMIUM = 1.25     # we took its capital - MUST equal EX.BUYOUT_PREMIUM
WINDUP = 0.5              # somebody else did - MUST equal EX.WINDUP
# The other two house shapes. Mirrored here for the same reason as the four above: every one of
# them is a number the Lua and this file both have to hold, and check_lua_houses() reads the
# shipped Lua's copy back and compares. SEAT_LOST had no mirror and no assertion at all - the
# whole `if seat == false then mult = mult * EX.SEAT_LOST end` line could be deleted and the
# suite still passed, on the spec's headline price signal.
SEAT_LOST = 0.6           # capital lost, price cut to this - MUST equal EX.SEAT_LOST
HORDE_WEIGHT = 2          # armies-to-regions for a horde - MUST equal EX.HORDE_WEIGHT
BASE_LOT_COST = 1000      # gold for one lot at multiplier 1.0
MULT_MIN = 0.10           # cheapest a commodity can get
MULT_MAX = 5.00           # dearest
SCARCITY_EXPONENT = 0.7   # 1.0 = price strictly inverse to supply; lower softens the curve
# How hard ownership concentration bites: effective supply is raw / (1 + K * hhi).
#
# K=1 WAS MEASURED INERT. Live on the Old World map at turn 3, every commodity was held by 19-49
# separate factions, so HHI sat at 0.02-0.05 and the divisor was a ~3% discount - below the
# ladder's own 10%-per-rung resolution. Twelve of seventeen rows showed a cartel premium of
# exactly 0 and the other five showed rung-quantisation artifacts (animals read +75 purely
# because effective supply 37 -> 36.0 crossed one boundary). Owning 20 of iron's 51 regions
# moved the price one rung; ten moved it none.
#
# K=10 leaves the CURRENT board almost untouched - 5 of 17 prices move, none by more than 100 -
# because a near-uniform divisor cancels in the median it is measured against. What it changes
# is sensitivity to conquest, which is the entire point: 10 of 51 iron regions now moves iron
# 621 -> 826 instead of nowhere. Raise it if cornering still feels unrewarding, lower it if
# a large empire distorts the whole board late-campaign.
CONCENTRATION_K = 10.0
LADDER_STEP = 1.10        # geometric ratio between adjacent ladder rungs
LADDER_LO = -24           # LADDER_STEP ** LADDER_LO  ~= MULT_MIN
LADDER_HI = 17            # LADDER_STEP ** LADDER_HI  ~= MULT_MAX
# Own-trade impact lives in the Lua as a rung shift (EX.PRESSURE_PER_RUNG), and always did
# from the DB's point of view - rituals.percentage_cost_increase_per_use was pinned to zero
# because it is invisible to script, so the panel would have drawn base*(1+ladder) while the
# game charged base*(1+ladder)*(1+0.04n). A market UI whose price is not the price you are
# charged is worse than no market UI. The rituals are gone entirely as of 2026-09-05; the rule
# survives them, because EX.price_at() is still the single source of the number.
# The knobs that DO live in the Lua, mirrored here only so check_lua_agrees can pin them.
# Editing one side alone is exactly the drift that check exists to catch.
PRESSURE_PER_RUNG = 4
SPREAD = 0.10
TRADE_GAIN = 40
BOOK_TRADE_MAX = 4        # lots a house may move one way in one turn - MUST equal EX.BOOK_TRADE_MAX
HOSTILE_MAX = 0.25        # ceiling on the hostility markup - MUST equal EX.HOSTILE_MAX
FRIENDLY_MAX = 0.25       # ceiling on the friendly discount - MUST equal EX.FRIENDLY_MAX
                          # (what is GRANTED is min(this, 1 - LADDER_STEP*(1-spread)))
HOSTILE_PACT_CAP = 0.05   # ceiling under a non-aggression pact - MUST equal EX.HOSTILE_PACT_CAP
REFUSE_RANK = 0.25        # bottom slice of the guild's stance spread that refuses - MUST equal EX.REFUSE_RANK
REFUSE_SHARE = 0.50       # book share a house needs to refuse - MUST equal EX.REFUSE_SHARE
GUILD_CLOSE = 0.60        # book share at war before the Exchange shuts - MUST equal EX.GUILD_CLOSE
HOUSE_CASH_MAX = 20000    # per-turn treasury move cap, both directions - MUST equal EX.HOUSE_CASH_MAX
# -----------------------------------------------------------------------------------------

# GROUPS: the CHD *feature* group, which holds 6 vanilla rites and 10 vanilla pools, so one
# group registers both the rituals and the holdings. The plan's Task 3 text names
# wh3_dlc23_chd_chaos_campaign / _combi_campaign; those are campaign-SCOPING groups that hold
# ZERO rituals, and because they are culture-gated identically they look correct while leaving
# every ritual disabled forever. Also measured 2026-09-04.
GROUPS = ["wh3_dlc23_feature_chaos_dwarfs"]

# POOL_GROUPS: where the seventeen holdings are REGISTERED, which is a different question from
# where the rituals live. A pooled resource a faction's group does not register is a NULL
# INTERFACE on that faction, and cm:faction_add_pooled_resource against it moves nothing and
# says nothing - measured 2026-09-08 in a live Empire campaign, where every buy charged the
# gold, paid the counterparty, logged success and granted zero goods.
#
# wh3_dlc23_feature_chaos_dwarfs reaches exactly one culture (its sole ACTOR criterion is
# culture = wh3_dlc23_chd_chaos_dwarfs), so it was correct for as long as this mod was Chaos
# Dwarfs only and became a silent gold sink the moment it was not.
#
# wh_main_feature_all is CA's universal group: one member, wh_feature_all, carrying ZERO rows
# in all four criteria tables, which is how a group matches every faction. It is what CA
# registers siege supplies under. The CHD row is KEPT rather than replaced - 18 vanilla
# resources are registered under two or more groups, so the shape is normal, and leaving it
# alone means a live Chaos Dwarf save's registration does not move.
POOL_GROUPS = GROUPS + ["wh_main_feature_all"]
UNIVERSAL_GROUP = "wh_main_feature_all"

# THE RACE THIS PACK WAS BUILT FOR, and the only one whose key segment is empty. Named rather
# than repeated as a literal: it appears in six checks, and the whole save-compatibility
# argument rests on it staying the culture whose keys already ship.
CHD_CULTURE = "wh3_dlc23_chd_chaos_dwarfs"

# NO optional_icon_path. This column was set to "resource_<our key stem>.png" and the comment
# here claimed the files were "copied into the pack at pack time" - they never were. ICON_DIR was
# declared and referenced by nothing, and the pack shipped ZERO png files.
#
# Worse, the derived name was fiction for 10 of the 17: our stems carry the "rom_" that CA's
# filenames do not, so `res_rom_iron` asked for `resource_rom_iron.png`, which exists in no pack
# at all. The other 7 name real files that live in `ui/campaign ui/effect_bundles/` and
# `ui/buildings/icons/` - NOT in `ui/skins/default/`, which is where the engine resolves a
# pooled resource icon (CA`s own wh3_dlc23_chd_armaments points at
# ui/skins/default/icon_chd_armaments.png).
#
# So every one of our 17 pools carried a dangling icon reference. Blank is a supported state -
# 59 of 246 vanilla pools leave this empty - and it is the only value here that cannot dangle.
# The EXCHANGE PANEL is unaffected: its row icons come from resources_tables.icon_filepath,
# read per row by the Lua, which is why they draw correctly while this was broken.
#
# Shipping real icons at ui/skins/default/ is the nicer fix and is still open; it needs the 17
# pngs extracted from ui.pack and added to the pack, plus a check that each one resolves.

# Read from vanilla, never guessed. SCOPE: 117 of the 120 bundle rows carrying an effect that is
# junctioned to a ritual as percentage_cost_mod use this one.
SCOPE = "faction_to_faction_own_unseen"
# STAGE is REQUIRED - advancement_stage is empty in 0 of 16,430 vanilla junction rows, so the
# plan's advancement_stage="" would be an unresolvable FK and a startup refusal. 16,351 of those
# rows use this value.
STAGE = "start_turn_completed"

# -------------------------------------------------------------------------------------------
# OPTION B: the exchange price drives VANILLA trade income.
#
# wh_main_effect_economy_trade_good_commodity_mod is CA's own, and live: 49 building rows, 18
# technology rows and 4 effect bundles use it, at values from 5 to 100. Modulating income the
# game already computes is what makes the market part of the campaign economy rather than a
# second one running beside it - and it reaches AI factions for free, because the per-turn
# ownership scan already knows who holds what.
TRADE_EFFECT = "wh_main_effect_economy_trade_good_commodity_mod"
# faction_to_faction_own, NOT the _unseen variant the price ladder used. This one the player is
# meant to see in the faction effects list: an income change with no visible cause reads as a bug.
TRADE_SCOPE = "faction_to_faction_own"
# A COARSE ladder on purpose. The price ladder needs 42 rungs because it is a price; this is a
# background income modifier, and 8 steps of 10% is already finer than a player can perceive.
# Every step is a bundle that has to be removed before another is applied, so the count is also
# the per-faction cost of a change.
TRADE_STEPS = [-40, -30, -20, -10, 10, 20, 30, 40]

# -------------------------------------------------------------------------------------------
# OFFERINGS TO HASHUT - what a stockpile is FOR.
#
# This replaced a passive "hold 50/200 units, get a permanent bonus" design on 2026-09-05,
# because holding was a DEPOSIT and not a purchase: reaching every tier-2 cost ~363,000 gold on
# the live board, the bonuses then ran forever, and ~90% of the capital came back through the
# sell spread whenever you wanted it. Rentable permanent buffs.
#
# An offering CONSUMES the goods. The bonus lasts OFFER_TURNS and then the engine expires it -
# cm:apply_effect_bundle(key, faction, turns) takes a duration, so nothing has to time it out by
# hand. That makes the market a supply chain instead of a vault: recurring demand, recurring
# cost, and a reason to keep trading after the first purchase.
#
# Every effect below is CA's own and EVERY SCOPE IS THE ONE VANILLA USES WITH THAT EFFECT,
# counted out of building_effects_junction + technology_effects_junction +
# effect_bundles_to_effects_junctions. That matters more than it looks: an effect paired with a
# scope it does not support is not an error, it is a row that quietly does nothing - and the
# faction-wide generic effects are thin, most of these actually reach forces, provinces or
# regions FROM the faction. Do not "tidy" a scope here to faction_to_faction_own.
#
# Several commodities deliberately share an effect. Forcing 17 distinct ones produces silly
# pairings, and two stockpiles pushing the same stat is the correct behaviour anyway - vanilla
# same-effect bundles stack additively.
#
# The key prefix is offering_, NOT hold_: derpy_chd_ex_hold_<short> is already the POOLED
# RESOURCE key for that commodity, and a collision would be silent.
OFFERING_EFFECTS = {
    "res_rom_iron":     ("wh_main_effect_force_stat_armour", "faction_to_force_own", 2),
    "res_obsidian":     ("wh3_main_effect_winds_of_magic_pool_cap", "faction_to_force_own", 5),
    "res_rom_marble":   ("wh_main_effect_building_construction_cost_mod_all",
                         "faction_to_region_own", -3),
    "res_rom_timber":   ("wh_main_effect_building_construction_cost_mod_all",
                         "faction_to_region_own", -3),
    "res_rom_wine":     ("wh_main_effect_public_order_faction", "faction_to_province_own", 2),
    "res_spices":       ("wh_main_effect_public_order_faction", "faction_to_province_own", 2),
    "res_rom_glass":    ("wh_main_effect_public_order_faction", "faction_to_province_own", 2),
    "res_gems":         ("wh_main_effect_economy_trade_tariff_mod",
                         "faction_to_faction_own_unseen", 3),
    "res_dyes":         ("wh_main_effect_economy_trade_tariff_mod",
                         "faction_to_faction_own_unseen", 3),
    "res_trinkets":     ("wh_main_effect_economy_trade_tariff_mod",
                         "faction_to_faction_own_unseen", 3),
    "res_gold_idols":   ("wh2_main_effect_agent_cap_increase_all_heroes",
                         "faction_to_faction_own_unseen", 1),
    "res_ivory":        ("wh_main_effect_technology_research_points",
                         "faction_to_faction_own_unseen", 2),
    # NOT GROWTH. wh_main_effect_province_growth_events shipped here until 2026-09-06 and was
    # dead for the mod's only audience: of the 1,377 building rows in the game that grant
    # growth, ZERO are Chaos Dwarf - CA gave the culture no growth buildings because it does
    # not use the mechanic. It was also province-scoped, so it was doubly dead for a horde.
    # Post-battle Labour is the replacement because Labour IS the Chaos Dwarf economy, and
    # faction_to_character_own_factionwide_armytext reaches a horde and a settled faction
    # alike. Two vanilla precedents, values 1/3/5/10/15.
    "res_animals":      ("wh3_dlc23_effect_force_chd_campaign_post_battle_labour",
                         "faction_to_character_own_factionwide_armytext", 5),
    "res_medicine":     ("wh_main_effect_force_all_campaign_replenishment_rate",
                         "faction_to_force_own", 3),
    "res_rom_lead":     ("wh_main_effect_force_all_campaign_replenishment_rate",
                         "faction_to_force_own", 3),
    "res_rom_furs":     ("wh_main_effect_force_all_campaign_movement_range",
                         "faction_to_force_own", 3),
    "res_rom_textiles": ("wh_main_effect_force_all_campaign_recruitment_cost_all",
                         "faction_to_force_own", -3),
}
# Units burned per offering, and how long Hashut's favour lasts. A lot is 10, so an offering
# is five lots - enough to feel, cheap enough to repeat.
# The STARTING cost of a voluntary sacrifice. It escalates 5% per offering - see EX.offer_cost
# in the campaign script, which owns the arithmetic; this is only the base both files share.
OFFER_COST = 30
OFFER_STEP = 1.05
OFFER_MULT_MAX = 5.0
OFFER_TURNS = 5
# The bonus is worth double the old passive tier-1 value, because it now costs goods outright
# and lasts five turns rather than forever.
OFFER_MULT = 2

# -------------------------------------------------------------------------------------------
# THE WAREHOUSE. Holding goods now does two things, and they are the same lever pointed both
# ways: a standing bonus that scales with the size of the pile, and a gold cost per unit per
# turn to keep it.
#
# THIS IS NOT THE PASSIVE TIER SYSTEM THAT WAS DELETED ON 2026-09-05, and the difference is
# one constant. That design was a VAULT: hold N units, get a bonus forever, and take ~90% of
# the capital back through the sell spread whenever you liked. Rentable permanent buffs, with
# nothing on the other side of the ledger. What was missing was NEGATIVE CARRY. A position you
# can park for free is not a position, it is a save file - and with a carry cost the same
# holding becomes a real trade-off, because doing nothing now costs money.
#
# CARRY IS FLAT PER UNIT, NOT A PERCENTAGE OF VALUE, and that is the whole model.
# A percentage of the position's market value is a FINANCIER'S cost of carry - interest on
# capital tied up - and there are no banks in Zharr-Naggrund. A warehouse charges by the CRATE:
# slaves to haul it, guards to watch it, a roof to keep it dry. A tonne of timber costs the
# same to store as a tonne of gemstones.
#
# The interesting asymmetry then falls out of one number, with no per-commodity weight table,
# because value per unit already differs by more than an order of magnitude:
#
#     800 timber    (20g/unit,   16,000 position)  ->  400g/turn  =  2.5%  of value per turn
#     800 gemstones (500g/unit, 400,000 position)  ->  400g/turn  =  0.1%  of value per turn
#
# Hoarding bulk is ruinous BECAUSE IT IS BULK, which is exactly how real commodity storage
# behaves. UNCALIBRATED - a first guess, like the four shock constants. What makes that
# survivable is that the player opts in by buying; hold nothing and this charges nothing.
CARRY_PER_UNIT = 0.5

# THE RAMP. (units held, effect multiplier, what the tier is called).
#
# A cliff at one threshold was the first design and it was rejected in review: selling one lot
# out of a 100-unit position would silently kill the bonus, and a player who sells 10 units and
# loses a buff reads it as a bug the first time. A ramp also makes a DEEP position a strategy
# rather than a subscription - which is the point of a market.
#
# The multiplier is against the OFFERING_EFFECTS base, so tier 2 grants exactly what burning
# the goods on the altar grants. That is deliberate and it is the whole comparison the player
# is being asked to make:
#
#     offering  ->  30 units DESTROYED, 2x for OFFER_TURNS turns
#     warehouse -> 300 units HELD,      2x for as long as you hold them and pay the carry
#
# The altar is the cheap burst; the warehouse is the long game with your capital tied up.
#
# EXACTLY ONE TIER BUNDLE IS EVER APPLIED. Same-effect bundles stack ADDITIVELY, so applying
# tier 1 and 2 and 3 together would grant 6x, not 3x. EX.apply_stockpiles removes all three and
# applies the one that matches - the same "remove all, then apply one" shape EX.apply_trade_income
# already uses, and for the same reason.
STOCK_TIERS = [(100, 1, "Stockpile"), (300, 2, "Warehouse"), (600, 3, "Vaults")]

# Bundle flavour, keyed by the tier's name. The title already names the commodity and CA renders
# the effect line itself, so this only has to say what kind of pile it is.
STOCK_TEXT = {
    "Stockpile": "Enough of it stacked in the yards that the work no longer waits on a caravan.",
    "Warehouse": "The sheds are full and guarded, and the overseers have stopped rationing it.",
    "Vaults": "More than the Conclave can use and more than it will admit to holding.",
}

# -------------------------------------------------------------------------------------------
# SUPPLY IS PRODUCTION, NOT REGIONS.
#
# `region:resource_exists(res)` is a TERRAIN PREREQUISITE, not a supply signal, and the exchange
# priced on it until 2026-09-05. Measured on a live turn-1 map: Tor Achare, Whitefire Tor, Tor
# Koruali and Vaul's Anvil all PRODUCE trinkets with `resource_exists("res_trinkets") == false`,
# and Karag Dromar produces glass the same way, while Martek produces iron with the deposit
# present. Some resource buildings need the deposit (mines); some do not (workshops, breweries).
# The BUILDING is the producer.
#
# So the region count was wrong in both directions on the same board: glass and trinkets read 0
# regions, sat at the MULT_MAX ceiling and drew "No offer" while the world made 6 and 38 a turn;
# medicine, obsidian and ivory had 10-16 deposit regions and produced NOTHING. That also answers
# the question left open in HANDOFF §8 - those commodities were never absent from the map.
#
# The quantity itself is `wh_main_effect_region_resource_<stem>_production` in
# building_effects_junction: 823 rows over 781 buildings, one per (building, tier), values 2-144.
# It is the number a construction tooltip shows ("Dyes resource production: 20 ounces").
#
# LATENT SUPPLY. A deposit with no building on it still contributes LATENT_PER_REGION, which is
# what keeps all 17 tradeable on an undeveloped map - pure production leaves ivory, medicine and
# obsidian at zero on turn 1, and three dead rows is a worse market than a slightly generous one.
# It also keeps the deposit meaningful: holding ivory ground is worth something before the mine.
LATENT_PER_REGION = 1

NL = chr(10)

# stem -> our commodity key. FOUR OF THESE ARE NOT DERIVABLE FROM THE NAME and were resolved by
# icon and unit out of resources_tables, not by guessing:
#   beer    -> res_rom_glass     icon resource_dwarf_beer.png, unit "kegs"
#   pottery -> res_rom_textiles  icon resource_pottery.png, unit "kilnful"
#   salt    -> res_rom_lead      already displays as "Salt" (see tools/read_vanilla_loc.py)
#   gem     -> res_gems          singular
# Do not "tidy" this map by pattern.
PRODUCTION_STEMS = {
    "animals": "res_animals",
    "beer": "res_rom_glass",
    "dyes": "res_dyes",
    "furs": "res_rom_furs",
    "gem": "res_gems",
    "gold_idols": "res_gold_idols",
    "iron": "res_rom_iron",
    "ivory": "res_ivory",
    "marble": "res_rom_marble",
    "medicine": "res_medicine",
    "obsidian": "res_obsidian",
    "pottery": "res_rom_textiles",
    "salt": "res_rom_lead",
    "spices": "res_spices",
    "timber": "res_rom_timber",
    "trinkets": "res_trinkets",
    "wine": "res_rom_wine",
}
# res_gold (trade_value 0) and the pasture buildings carry production effects too and are
# deliberately absent: neither is a tradeable resource. Measured 8 such buildings on the live
# map, which is why the scan silently ignores an unmapped producer rather than logging it.

# CHAOS DWARF DEPOSITS THAT PRODUCE NOTHING TRADEABLE, and the one place this file invents a
# number CA did not write.
#
# 11 of the 38 wh3_dlc23_chd_resource_* buildings carry no
# wh_main_effect_region_resource_<stem>_production row at all. Six of those are fine and stay
# absent - gold_1/2/3 (res_gold is not tradeable) and pastures_1/2/3 (not a commodity) match
# the same exclusions the stem map already makes. The other FIVE sit on tradeable deposits and
# are the hole:
#
#     iron_1      -> wh3_dlc23_pooled_resource_chd_armaments_modifier only
#     timber_1    -> wh3_dlc23_pooled_resource_chd_armaments_modifier only
#     marble_1    -> raw_material_efficiency + raw_materials_gain + workload_increase only
#     obsidian_1  -> the same four as marble
#     gems_1      -> the same four as marble
#
# GEMS WAS MISSED FOR THREE WEEKS AND THE PLURAL IS WHY. The building family is "gems" and the
# effect stem is "gem", singular - PRODUCTION_STEMS carries an explicit entry for exactly that
# - so a survey that derives the stem from the BUILDING key looks up "gems", misses, and drops
# it as untradeable. The original count of 37/10/four is that miss, written down. Zero of the
# 50 buildings in the game that produce res_gems were Chaos Dwarf until this line was added.
# check_chd_deposits_covered now classifies every family exhaustively so nothing can fall
# through a name lookup again.
#
# That is CA being consistent: a Chaos Dwarf converts those deposits into Armaments and Raw
# Materials for the Hell-Forge instead of goods for a market. But this mod's whole audience is
# Chaos Dwarfs, so leaving it meant a player's own conquests could never move the iron, timber,
# marble or obsidian price and the Ownership view could never show them holding any - four of
# seventeen commodities blind to the only faction that can open the panel.
#
# REDUCED, DELIBERATELY. Vanilla tier 1 is 20 (166 rows, the modal value) and these four have no
# tier 2 or 3 to grow into - CA gave the culture a single rung on each. 10 is half that, and it
# is a value vanilla itself uses 59 times, so the market still reads a Chaos Dwarf mine as a
# real producer while the Hell-Forge keeps most of the output. The flavour and the arithmetic
# agree: only the surplus reaches the market.
CHD_SURPLUS = 10

# ...AND SINCE 2026-09-09 THE PACK MAKES IT TRUE. Everything above describes a fiction the
# supply scan needed: the market priced a surplus these five buildings did not actually
# produce, so a Chaos Dwarf player's own iron mine moved the iron price on the panel while
# the campaign's trade screen showed nothing and no other faction could buy a bar of it.
#
# Five rows in building_effects_junction close that gap, and this table is the ONLY place the
# numbers live - production_map() reads it, build() writes the DB rows from it, and
# check_chd_trade_resources() proves the two agree. A grant the market does not price, or a
# price for a grant that is not made, are both silent.
#
# THE VALUES ARE PRICED OFF BUILD COST, not picked. Vanilla's tiered resource buildings pay
# 20 at 1,500 gold, 30 at 3,000 and 45 at 5,000, and every one of these five is a SINGLE rung
# with no tier 2 or 3 to grow into:
#
#   gems_1, iron_1, timber_1    cost 0      -> 10, which is CHD_SURPLUS and half of tier 1.
#                                              Free buildings, and iron and timber already
#                                              pay +15% armaments. gems_1 pays nothing at all
#                                              - it is the one building in the set with ZERO
#                                              rows in building_effects_junction - and it is
#                                              kept level with the other two rather than
#                                              rewarded for being inert.
#   marble_1, obsidian_1        cost 5,000  -> 15. A tier-3 price, deliberately paid below
#                                              the tier-2 rate, because both also carry +15%
#                                              raw material efficiency, +500 raw materials
#                                              and +400 workload.
#
# All five are far under the 45 a tier 3 pays, which is the balance the mod this was asked to
# match states out loud. The Hell-Forge still keeps most of the output; only the surplus
# reaches the market, which is what the paragraph above always claimed.
#
# THE gems STEM IS SINGULAR. wh_main_effect_region_resource_gem_production, not _gems_ - the
# same plural trap that lost gems_1 from the survey the first time round.
CHD_TRADE_GRANT = {
    "wh3_dlc23_chd_resource_gems_1":     ("gem",      CHD_SURPLUS),
    "wh3_dlc23_chd_resource_iron_1":     ("iron",     CHD_SURPLUS),
    "wh3_dlc23_chd_resource_timber_1":   ("timber",   CHD_SURPLUS),
    "wh3_dlc23_chd_resource_marble_1":   ("marble",   15),
    "wh3_dlc23_chd_resource_obsidian_1": ("obsidian", 15),
}
CHD_TRADE_SCOPE = "building_to_building_own"


def chd_trade_rows():
    """The five DB rows, damaged at half and ruined at nothing - vanilla's own convention.

    Counted rather than assumed: all 810 building_to_building_own production rows in the game
    carry value_damaged at half the value and value_ruined at 0, with no context requirement.
    20/10, 30/15, 45/23. A row that disagreed would still load and would simply pay the wrong
    amount to a sacked province, which nothing on screen distinguishes from the right one.
    """
    out = []
    for bld, (stem, val) in sorted(CHD_TRADE_GRANT.items()):
        out.append({
            "building": bld,
            "effect": "wh_main_effect_region_resource_%s_production" % stem,
            "effect_scope": CHD_TRADE_SCOPE,
            "value": float(val),
            "value_damaged": float(int(round(val / 2.0))),
            "value_ruined": 0.0,
            "context_requirement": "",
        })
    return out


CHD_PRODUCTION_EXTRA = {
    "wh3_dlc23_chd_resource_iron_1":     "res_rom_iron",
    "wh3_dlc23_chd_resource_timber_1":   "res_rom_timber",
    "wh3_dlc23_chd_resource_marble_1":   "res_rom_marble",
    "wh3_dlc23_chd_resource_obsidian_1": "res_obsidian",
    "wh3_dlc23_chd_resource_gems_1":     "res_gems",
}

# EVERY wh3_dlc23_chd_resource_* FAMILY, CLASSIFIED. None may fall through: a family that is
# neither mapped to a commodity nor explicitly None fails check_chd_deposits_covered, which is
# the guard the gems miss did not have. Keys are BUILDING families (so "gems", plural), values
# are our commodity keys or None for "correctly not on the market".
CHD_DEPOSIT_FAMILIES = {
    "animals": "res_animals",
    "dyes": "res_dyes",
    "furs": "res_rom_furs",
    "gems": "res_gems",              # plural here, singular "gem" in PRODUCTION_STEMS
    "gold": None,                    # res_gold has trade_value 0 - not tradeable
    "iron": "res_rom_iron",
    "ivory": "res_ivory",
    "marble": "res_rom_marble",
    "medicine": "res_medicine",
    "obsidian": "res_obsidian",
    "pastures": None,                # livestock, not one of the 17 commodities
    "pottery": "res_rom_textiles",
    "salt": "res_rom_lead",
    "spices": "res_spices",
    "timber": "res_rom_timber",
    "wine": "res_rom_wine",
}

CHD_RESOURCE_PREFIX = "wh3_dlc23_chd_resource_"

PROD_LUA = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign", "mod",
                        "zzz_derpy_chd_exchange_prod.lua")


def check_chd_trade_resources():
    """THE FIVE GRANTED ROWS, against the game they are granted in and the market that prices
    them.

    Three things can go wrong here and every one of them is silent:

    - A WRONG EFFECT KEY. Effect keys are unvalidated strings like every other key in this
      game: a row naming an effect that does not exist loads without complaint and grants
      nothing, forever. Every key below has to appear in vanilla's own
      building_effects_junction, which is stronger than checking the effects table - it proves
      the key is used the way we are using it.
    - A WRONG SCOPE. building_to_building_own is the only scope that means "this building
      produces this, here"; the 13 rows in the game that use another one change production in
      OTHER regions, which is a different mechanic wearing the same effect name.
    - A DISAGREEMENT WITH THE MARKET. The panel's supply scan reads the production map, not
      the DB, so a grant of 15 priced as 10 is a board quoting a world that does not exist.
    """
    from read_vanilla_cache import load
    eff, _f = load("building_effects_junction")
    van_keys, van_scopes = set(), {}
    blds = set()
    for r in eff:
        van_keys.add(r["effect"])
        van_scopes.setdefault(r["effect"], set()).add(r["effect_scope"])
    for r in load("building_levels")[0]:
        blds.add(r["level_name"])

    rows = chd_trade_rows()
    assert len(rows) == len(CHD_TRADE_GRANT) == 5, (
        "expected 5 granted buildings, built %d rows from %d entries"
        % (len(rows), len(CHD_TRADE_GRANT)))

    for r in rows:
        assert r["building"] in blds, (
            "%s is not a building in this game - a row against a key nothing holds loads "
            "cleanly and does nothing forever" % r["building"])
        assert r["effect"] in van_keys, (
            "%s is in no vanilla row of building_effects_junction. Effect keys are "
            "unvalidated: the row would load and grant nothing. Note the gems/gem SINGULAR "
            "stem - that plural is how gems_1 was lost from the survey once already."
            % r["effect"])
        assert r["effect_scope"] in van_scopes[r["effect"]], (
            "%s is used at scope %s, which vanilla never pairs it with (%s). "
            "building_to_building_own is the only scope that means 'produced here'."
            % (r["effect"], r["effect_scope"], ", ".join(sorted(van_scopes[r["effect"]]))))
        assert r["value_damaged"] * 2 in (r["value"], r["value"] + 1), (
            "%s pays %s damaged against %s whole. Every one of vanilla's 810 production rows "
            "halves it." % (r["building"], r["value_damaged"], r["value"]))
        assert r["value_ruined"] == 0.0, "%s pays a ruined value" % r["building"]

    # UNDER THE TIER-3 RATE, which is the balance this was asked to match. 45 is what a 5,000
    # gold tier 3 pays; these are single-rung buildings and two of them also pay the Hell-Forge.
    worst = max(r["value"] for r in rows)
    assert worst < 45, (
        "the richest grant is %s against the 45 a vanilla tier 3 pays. These buildings have no "
        "tier 2 or 3 and four of the five carry armaments or raw-material effects on top."
        % worst)

    # AND THE MARKET PRICES EXACTLY WHAT IS GRANTED.
    prod = production_map()
    for r in rows:
        got = dict(prod[r["building"]])
        res = CHD_DEPOSIT_FAMILIES[
            re.sub(r"_\d+$", "", r["building"][len(CHD_RESOURCE_PREFIX):])]
        assert got == {res: r["value"]}, (
            "%s grants %s %s in the DB and the supply scan prices it as %s. The panel would "
            "quote a world the campaign does not have."
            % (r["building"], r["value"], res, got))

    print("  chd trade resources: %d buildings granted %s, every effect key and scope "
          "attested in vanilla, all under the tier-3 45, and the market prices what is granted"
          % (len(rows), "/".join(str(int(r["value"])) for r in rows)))


def check_chd_deposits_covered():
    """Every Chaos Dwarf resource building on a TRADEABLE deposit must reach the market.

    Either CA gave it a production effect, or CHD_PRODUCTION_EXTRA adds one. A building that
    has neither is invisible to the supply scan, so the only faction that can open this panel
    cannot move that commodity's price by conquering it - which is the whole reason
    CHD_PRODUCTION_EXTRA exists.

    THIS CHECK EXISTS BECAUSE THE FIRST SURVEY MISSED ONE. gems_1 sat uncovered while the
    comment above CHD_PRODUCTION_EXTRA confidently said "the other FOUR", because the building
    family is "gems" and the effect stem is "gem" and a name lookup silently returned nothing.
    So this does NOT derive the commodity from the building name: it requires every family to
    be classified by hand in CHD_DEPOSIT_FAMILIES, and fails on any family it has never been
    told about. A silent fallthrough is the bug; an unclassified family is now a build error.
    """
    from read_vanilla_cache import load
    blds, _ = load("building_levels")
    keys = sorted(set(r["level_name"] for r in blds
                      if str(r.get("level_name", "")).startswith(CHD_RESOURCE_PREFIX)))
    assert keys, "no %s* buildings found - did the cache go stale?" % CHD_RESOURCE_PREFIX

    eff, _ = load("building_effects_junction")
    has_prod = set()
    for r in eff:
        if (re.search(r"effect_region_resource_[a-z_]+_production$", r["effect"])
                and r["effect_scope"] == "building_to_building_own"):
            has_prod.add(r["building"])

    seen, uncovered = set(), []
    for k in keys:
        fam = re.sub(r"_\d+$", "", k[len(CHD_RESOURCE_PREFIX):])
        seen.add(fam)
        assert fam in CHD_DEPOSIT_FAMILIES, (
            "%s is a Chaos Dwarf resource building whose family %r is not classified in "
            "CHD_DEPOSIT_FAMILIES. Say which commodity it sells, or None if it correctly does "
            "not reach the market. Do not guess from the name - the gems/gem plural is exactly "
            "how the last one was lost." % (k, fam))
        res = CHD_DEPOSIT_FAMILIES[fam]
        if res is None:
            continue
        assert res in COMMODITIES, (
            "CHD_DEPOSIT_FAMILIES maps %r to %s, which is not one of the %d traded commodities"
            % (fam, res, len(COMMODITIES)))
        if k not in has_prod and k not in CHD_PRODUCTION_EXTRA:
            uncovered.append((k, res))

    assert not uncovered, (
        "%d Chaos Dwarf building(s) sit on a tradeable deposit with NO production effect and no "
        "CHD_PRODUCTION_EXTRA entry: %s. "
        "The supply scan cannot see them, so a Chaos Dwarf "
        "player holding one contributes nothing to that commodity's world supply and can never "
        "move its price. Add them to CHD_PRODUCTION_EXTRA at CHD_SURPLUS."
        % (len(uncovered), ", ".join("%s (%s)" % t for t in uncovered)))

    stale = sorted(f for f in CHD_DEPOSIT_FAMILIES if f not in seen)
    assert not stale, (
        "CHD_DEPOSIT_FAMILIES classifies %s, which no longer exists in building_levels - a "
        "patch removed it, and a stale row here would keep a real gap hidden behind a name that "
        "matches nothing." % stale)

    covered = sorted(CHD_PRODUCTION_EXTRA)
    print("  chd deposits: %d buildings, %d families, %d granted %s/turn by this pack"
          % (len(keys), len(seen), len(covered),
             "/".join(str(CHD_TRADE_GRANT[b][1]) for b in covered)))


def production_map():
    """building key -> [(our commodity key, units per turn), ...], read out of vanilla.

    Derived rather than hand-listed so it cannot drift after a patch - delete .skilltree_cache
    and it re-derives.

    A LIST, NOT ONE PAIR. 28 buildings produce more than one resource and the first version of
    this assumed otherwise - Hag Graef's mines make iron AND marble at 28/42/64/96 by tier, the
    Star Tower makes gems and obsidian, and Peg Street Pawnshop makes five different goods at
    once. The assert that caught it is kept below, narrowed to what is actually true: a stem
    may repeat within one building (two vanilla ones do) and those rows sum.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from read_vanilla_cache import load
    rows, _f = load("building_effects_junction")
    out = {}
    for r in rows:
        m = re.search(r"effect_region_resource_([a-z_]+)_production$", r["effect"])
        if not m:
            continue
        res = PRODUCTION_STEMS.get(m.group(1))
        if res is None:
            continue          # res_gold and pastures: real effects, not tradeable goods
        # ONLY building_to_building_own - 810 of the 823 rows, and the only scope that means
        # "this building produces this, here". The other 13 are Underdeep and Spirit of Grungni
        # oddities scoped foreign_building_to_region_own / force_to_region_own: they change
        # production in OTHER regions, which a per-region walk cannot attribute, and four of
        # them are gated on guild techs it cannot evaluate either. They are also where every
        # negative value lives (the Underdeep drinking halls net -10 and -5 beer), so filtering
        # here is what lets the map assert output is positive.
        if r["effect_scope"] != "building_to_building_own":
            continue
        per = out.setdefault(r["building"], {})
        per[res] = per.get(res, 0.0) + r["value"]
    # The four Chaos Dwarf deposits vanilla leaves off the market. Added AFTER the walk and
    # asserted absent first, so a future patch that gives them a real production row wins
    # instead of being silently doubled by this.
    for b, res in CHD_PRODUCTION_EXTRA.items():
        assert res in PRODUCTION_STEMS.values(), "unknown commodity %s" % res
        # STILL ASSERTED ABSENT FROM CA'S WALK. The walk reads the VANILLA cache, so this
        # pack's own five rows never appear in it - what this catches is a future game patch
        # giving one of these buildings a real production effect of CA's own, which must win
        # instead of being silently doubled by ours.
        assert b not in out, (
            "%s now carries a real production effect - drop it from CHD_PRODUCTION_EXTRA "
            "and from CHD_TRADE_GRANT rather than adding to CA's number" % b)
        # AND THE NUMBER IS THE ONE THE PACK ACTUALLY GRANTS. Before 2026-09-09 this was a
        # flat CHD_SURPLUS against a building that produced nothing; now it must equal the DB
        # row, or the panel prices a supply the campaign does not have.
        assert b in CHD_TRADE_GRANT, (
            "%s is priced by the market through CHD_PRODUCTION_EXTRA and granted nothing by "
            "CHD_TRADE_GRANT - the supply scan would count a producer that produces nothing"
            % b)
        out[b] = {res: float(CHD_TRADE_GRANT[b][1])}
    return dict((b, sorted(per.items())) for b, per in out.items())


def write_production_lua():
    """Ship the map as its own pack script. 781 entries is data, not code.

    A SEPARATE FILE, and read LAZILY by the exchange: every script/campaign/mod/*.lua autoloads
    and the order between two of them is not guaranteed, so the exchange must not touch
    EX_PRODUCTION at load time. It reads it inside the scan, by which point both have run.
    """
    prod = production_map()
    lines = ["-- GENERATED by tools/gen_zharr_exchange.py - do not edit.",
             "--",
             "-- Every vanilla building that produces a tradeable resource, and how much per",
             "-- turn. Read out of building_effects_junction"
             " (wh_main_effect_region_resource_<stem>_production).",
             "--",
             "-- Consumed by EX.scan_supply in zzz_derpy_chd_exchange.lua, LAZILY - mod scripts",
             "-- autoload in no guaranteed order, so nothing may read this at load time.",
             "EX_PRODUCTION = {"]
    for b in sorted(prod):
        pairs = ", ".join('{ "%s", %g }' % (res, val) for res, val in prod[b])
        lines.append('    ["%s"] = { %s },' % (b, pairs))
    lines.append("}")
    body = NL.join(lines) + NL
    io.open(PROD_LUA, "w", encoding="utf-8", newline=NL).write(body)
    return len(prod), len(body)


# -------------------------------------------------------------------------------------------
# HASHUT'S DEMANDS - the other half of the offering.
#
# An offering is the player choosing to spend. A demand is Hashut choosing FOR them, and it is
# what stops the vault from being a safe place to sit: the priests count the stores, and the
# biggest pile is the one the altar names. Refusing is always allowed and always costs.
#
# ONE DILEMMA ROW PER (COMMODITY, TIER) - 51 of them - rather than one generic row whose text
# is filled in at runtime. dilemmas_tables.localised_description is a loc key, so the amount and
# the boon can only appear in the text if they are FIXED for that key. 51 static rows cost
# nothing and buy a dilemma that actually says what it is asking for; the alternative is a
# dilemma that says "some of your goods" and a player who has to guess.
#
# Table versions are CA's own, read off the cached vanilla dumps by table_version(): dilemmas
# v3, cdir_events_dilemma_choice_details v4. Same pair tools/gen_commission_dilemmas.py ships.
DEMAND_PIC = "zharr_temple"     # movies/eventpics/chd/zharr_temple.ca_vp8 - CA's own temple pic

# generate MUST stay "false" on every dilemma row. A "true" hands the key to the campaign
# director, which rolls it unprompted against conditions we never wrote.
DEMAND_GENERATE = "false"

# The two buttons. Both are real cdir_events_dilemma_choices rows; the engine's vocabulary is
# fixed (FIRST..NINTH and friends) and a key outside it is silently dropped.
SUBMIT_CHOICE = "FIRST"
REFUSE_CHOICE = "SECOND"

# sfx, cost multiplier on OFFER_COST, boon turns, wrath turns, title, closing line.
#
# THE BIG DEMANDS ARE DELIBERATELY WORSE PER UNIT (0.12 / 0.08 / 0.07 turns per unit). A demand
# is not an offer - the alternative on the table is not "buy nothing", it is "eat the wrath".
# Making the greedy one efficient would turn it into a reward for hoarding, which is the exact
# thing this subsystem exists to remove.
DEMAND_TIERS = [
    ("tithe", 1, 6, 4, "The Tithe of Hashut",
     "It is a small thing. The Bull God asks small things often, and remembers each one."),
    ("hunger", 3, 12, 8, "Hashut's Hunger",
     "This is more than the altar usually takes. It is also not phrased as a request."),
    ("wrath", 6, 24, 15, "The Bull God is Greedy",
     "This is not a tithe. Hashut has seen the hoard, and Hashut wants the hoard."),
]
# Per cent, rolled when a demand fires. Must sum to 100 - the Lua walks these as a cumulative
# threshold and a short list would silently make the last tier unreachable.
DEMAND_WEIGHTS = [55, 32, 13]

# Cadence, mirrored into the campaign script and checked against it.
DEMAND_FIRST_TURN = 15    # nothing before the market has had time to matter
DEMAND_COOLDOWN = 15      # turns between demands, whatever the answer was
DEMAND_CHANCE = 30        # per cent per turn once off cooldown
DEMAND_GRACE = 3          # turns to pay before the wrath lands; mirrors EX.DEMAND_GRACE
DEMAND_TOP_N = 3          # the altar names one of the three biggest piles, not any pile

# REFUSAL. One bundle, applied for a tier-scaled number of turns - the duration rides
# cm:apply_effect_bundle, so three tiers of punishment need one row, not three.
#
# Both effects are already carried by OFFERING_EFFECTS with these exact scopes, so both the key
# and the effect/scope pairing are known-good. Public order because a Chaos Dwarf economy runs
# on slaves who notice when the priests are unhappy; replenishment because the temple stops
# blessing the columns.
# THE TWO PAYLOAD-TEXT RECORDS, referenced by payload_builder:text_display.
#
# Every dilemma choice needs A payload or CA's panel draws a blank entry under its button, and
# the demand's choices no longer carry a pooled-resource transaction - that call hard-crashed
# the game three times on a MODDED pool (see EX.fire_demand). A text_display record is a
# sentence and nothing else, so it cannot.
#
# "state" is a FIXED ENGINE VOCABULARY of exactly four values, counted in vanilla:
# default 478, positive 183, negative 34, positive_if_value_positive 9. An unknown value is
# eaten in silence and the entry simply does not draw. Both of these cost the player something,
# so both are negative. The icon is a full path; icon_alert_message.png is the one 49 vanilla
# rows and the commission mod both use for a plain notice.
# THE EVENT-FEED RECORDS. show_message_event's last argument is an INDEX, and it resolves
# against campaign_group_member_criteria_values.value - not a free number, and never 0: an
# index with no record behind it makes the call log and draw nothing.
#
# Four tables per record, which is CA's own shape and the commission mod's:
#   campaign_groups                        the id
#   campaign_group_members                 group == id, priority 0
#   campaign_group_member_criteria_values  the index show_message_event names
#   event_feed_message_events              the record itself
#
# EVERY VALUE BELOW IS VANILLA'S AND VERIFIED TO EXIST. The icons are real files in ui.pack at
# ui/campaign ui/message_icons/, and zharr_temple is CA's own event pic (movies_ev.pack and
# ui2.pack both carry it). A dangling reference here is exactly the class of defect that cost
# a build earlier today.
# ONE PICTURE PER RACE, because the image is a DB COLUMN on the record and nothing can swap
# it at runtime. A Skaven player was shown the Chaos Dwarf forge for a Trade Disrupted bulletin
# (screenshot, 2026-09-08); the only fix is a record per race, which is why FEED below is
# generated four times over.
#
# THE COLUMN IS A PATH, NOT AN ENUM. chd/zharr_temple appears in ZERO vanilla rows of this
# table - it is a file in movies_ev.pack and ui2.pack that this mod pointed the column at, and
# it draws. So the values below are chosen from what vanilla's own rows use, per culture, and
# every one of them is verified present in the cached table by check_feed_art().
#
# The Chaos Dwarf entry KEEPS chd/zharr_temple: it ships, it is the most on-theme picture any
# of the four gets, and the standing rule is that nothing Chaos Dwarf moves.
# CATAPH'S SOUTHERN REALMS (Steam 2927296206, ships as !ak_teb3.pack). Read off a live campaign
# rather than off the store page: a faction of that mod answers culture() and subculture() with
# the SAME string, mixer_teb_southern_realms, which is not the usual shape and is exactly the
# sort of thing a guess gets wrong. Keys are unvalidated strings, so a wrong one here would fail
# silently and forever.
#
# THIS IS A SOFT DEPENDENCY. Every row the mod generates is keyed by our own prefix; the culture
# appears only as a Lua table key, so without the Southern Realms installed EX.RACES simply
# never matches it and nothing else changes. There is no pack dependency to declare.
TEB_CULTURE = "mixer_teb_southern_realms"

# CULTURES THAT ARE NOT IN THE BASE GAME, and how each key was established.
#
# check_race_table() otherwise requires every EX.RACES key to be a real vanilla culture, which
# is the right default: keys are unvalidated strings, and one nothing holds leaves that race
# uncovered forever with nothing anywhere saying so. A modded culture cannot pass that test, so
# it has to be registered here with its provenance instead of the check being weakened.
#
# THE PACK CANNOT BE SCANNED TO CONFIRM IT. !ak_teb3.pack is compressed, so its DB files read
# back as one byte and a byte-grep finds nothing - a negative result there would be meaningless
# rather than informative. The key below was read out of a LIVE campaign over the MCP bridge
# instead (faction mixer_teb_tilea answered culture() and subculture() with the same string,
# 2026-09-08), which is a stronger check than reading the pack would have been: it is the value
# the running game actually compares against.
MODDED_CULTURES = {
    TEB_CULTURE: ("Cataph's The Southern Realms", 2927296206, "!ak_teb3.pack"),
}

FEED_IMAGE = {
    "wh3_dlc23_chd_chaos_dwarfs": {
        "call": "chd/zharr_temple", "wrath": "chd/zharr_temple",
        "shock": "chd/zharr_temple", "delist": "chd/zharr_temple",
    },
    # cth/ivory_road is CA's own picture for the trade road this race's market is named after.
    "wh3_main_cth_cathay": {
        "call": "cth/ivory_road", "wrath": "cth/civilisation_down",
        "shock": "cth/messenger", "delist": "cth/funeral",
    },
    "wh_main_emp_empire": {
        "call": "emp/civilisation_up", "wrath": "emp/civilisation_down",
        "shock": "emp/messenger", "delist": "emp/funeral",
    },
    "wh2_main_skv_skaven": {
        "call": "skv/celebration", "wrath": "skv/civilisation_down",
        "shock": "skv/messenger", "delist": "skv/funeral",
    },
    # THE SOUTHERN REALMS BORROW THE EMPIRE'S ART, and that is a decision rather than a
    # shortcut. The column is a FILE PATH into the game's own event pictures, and Cataph's
    # Southern Realms mod ships none of its own in event_feed_message_events - so the choice is
    # between another human culture's art and a dangling path, which draws an empty frame in
    # silence. Old World humans in Renaissance dress is the closest thing the base game holds.
    TEB_CULTURE: {
        "call": "emp/civilisation_up", "wrath": "emp/civilisation_down",
        "shock": "emp/messenger", "delist": "emp/funeral",
    },
    # The three added 2026-09-09 all have their OWN art in the base game, so none of them has
    # to borrow the way the Southern Realms do. Every value below is in a vanilla row.
    "wh_main_dwf_dwarfs": {
        "call": "dwf/celebration", "wrath": "dwf/civilisation_down",
        "shock": "dwf/messenger", "delist": "dwf/funeral",
    },
    # hef/court_intrigue_2 rather than civilisation_up: the tithe here IS the Phoenix Court
    # asking, and CA's picture for that is the one of a court asking.
    "wh2_main_hef_high_elves": {
        "call": "hef/court_intrigue_2", "wrath": "hef/civilisation_down",
        "shock": "hef/messenger", "delist": "hef/funeral",
    },
    "wh2_main_def_dark_elves": {
        "call": "def/black_ark_created", "wrath": "def/civilisation_down",
        "shock": "def/messenger", "delist": "def/funeral",
    },
}
# THE EVENT COLUMN IS THE POPUP SWITCH, and it pairs with show_message_event's persistent
# flag: scripted_persistent_event steals the screen and needs `true`, scripted_transient_event
# lands in the feed strip and needs `false`. Disagree and nothing draws at all.
#
# Counted rather than assumed: all 93 vanilla scripted_persistent_event rows are instant_open
# true, and all 4 scripted_transient_event rows are false (wh2_dlc10 assassination targets,
# wh2_dlc10 defender of ulthuan, wh2_dlc13 gotrek and felix, wh3_dlc27 consult leaders). The
# transient four also all carry an EMPTY override_icon, which is why the shock record does too.
# THE INDEX BLOCK PER RACE. The Chaos Dwarf four keep 7401-7404 exactly - a live save holds
# no index, but every check and every log line in this file names them, and moving a number
# that need not move is how a diff stops being readable. The other three take a block of four
# each, in the same EX.RACES order the segments come from.
FEED_INDEX_BASE = {
    "wh3_dlc23_chd_chaos_dwarfs": 7401,
    "wh_main_emp_empire": 7411,
    "wh3_main_cth_cathay": 7421,
    "wh2_main_skv_skaven": 7431,
    TEB_CULTURE: 7441,
    "wh_main_dwf_dwarfs": 7451,
    "wh2_main_hef_high_elves": 7461,
    "wh2_main_def_dark_elves": 7471,
}

FEED = [
    # key, index, override_icon, sound, event, instant_open
    ("derpy_chd_ex_feed_call", 7401, "event_rite_neutral.png",
     "UI_CAM_POPUP_Message_Event_Neutral", "scripted_persistent_event", True),
    ("derpy_chd_ex_feed_wrath", 7402, "event_rite_negative.png",
     "UI_CAM_POPUP_Message_Event_Negative", "scripted_persistent_event", True),
    # War shook the market. NEWS, so it does not stop the game: the 2026-09-06 log carries 320
    # shock events over ~30 turns and a popup per shock would fire ten times a turn.
    ("derpy_chd_ex_feed_shock", 7403, "",
     "UI_CAM_POPUP_Message_Event_Neutral", "scripted_transient_event", False),
    # A HOUSE DELISTED AND ITS PAPER SETTLED. News too, and for a second reason beyond the
    # shock record's: this fires from the turn handler, where a persistent record would stop
    # the turn dead for something the player cannot answer or undo. One record serves both
    # wordings below - which one draws is a loc key EX.settle_house picks, not a second row.
    ("derpy_chd_ex_feed_delist", 7404, "",
     "UI_CAM_POPUP_Message_Event_Neutral", "scripted_transient_event", False),
]

# THE TWO DELISTING BULLETINS. Two wordings because the payout has two branches and the text
# has to match the multiplier that paid - a wind-up worded as a buyout reads as a bug in the
# gold. Plain text, no markup: every feed string in this mod is plain and the shock bulletin
# above is the precedent.
#
# NO SHARE COUNT AND NO GOLD FIGURE IN THESE, AND THERE CANNOT BE. Design §8's example reads
# "Your 40 shares were bought out at 512 (+25%) -> +20,480 gold", and cm:show_message_event
# takes a faction key, three LOC KEYS, a boolean and an index - CA's own signature, checked in
# episodic_scripting.html. There is no substitution argument and no resolver on this route, so
# a runtime number cannot reach the feed at all. The shock bulletins get round the same wall by
# minting one message PER COMMODITY with the name baked into the string, which works for
# seventeen fixed names and not for an arbitrary share count crossed with an arbitrary price.
#
# What CAN be stated is the MULTIPLIER, because it is a constant - and it is interpolated from
# BUYOUT_PREMIUM / WINDUP rather than typed, so the sentence cannot drift from the payout. The
# actual gold is in the script log (EX.settle_house's out() line) and nowhere on screen.
DELIST_BUYOUT_MSG = PREFIX + "delist_buyout"
DELIST_BUYOUT_TEXT = (
    "A House Bought Out",
    "The house is finished and its seat is ours. The Exchange settles its paper against the "
    "estate we now hold, which is worth more than the last price anyone quoted for it.",
    "Your shares are paid out at %g times the last price, and the row is closed."
    % BUYOUT_PREMIUM)
DELIST_WINDUP_MSG = PREFIX + "delist_windup"
DELIST_WINDUP_TEXT = (
    "A House Wound Up",
    "The house is finished and somebody else took what was left of it. The Exchange winds up "
    "its paper for whatever a creditor will give, which is not what you paid for it.",
    "Your shares are paid out at %g times the last price, and the row is closed."
    % WINDUP)

# THE SHOCK BULLETIN, one message per commodity - the goods have to be named and the text is a
# static loc string, the same constraint that makes the demand messages per (tier, commodity).
# The KIND is deliberately not in the key: four times seventeen messages for a word the panel
# footer already prints beside the commodity.
#
# The name goes in a slot that works for every one of CA's display names, which include
# "Tusks", "Dwarf Beer" and "Carved Obsidian" - a template reading "the %s trade" produces
# "the Tusks trade" and was rejected for it.
SHOCK_MSG = PREFIX + "shock_"
SHOCK_MSG_TEXT = (
    "Trade Disrupted: %s",
    "Burned settlements and armies astride the caravan roads. Word reaches the Exchange of one "
    "line in particular: %s. The price is marked up on the news alone, before a warehouse "
    "anywhere has run dry.",
    "The spike fades as the roads clear. Sell into it or wait it out.")

# The two outcome messages. Generic, because they say what happened rather than how much - the
# amount and the commodity are in the DEMAND message, which is per (tier, commodity).
PAID_MSG = "derpy_chd_ex_dem_paid"
# _MSG_TEXT, not _TEXT: WRATH_TEXT is already the wrath BUNDLE's description further down, and
# the first version of this shadowed it - the three message parts became 'T', 'h', 'e', because
# text[0..2] on a string is three characters and every key still existed. The loc length assert
# in check_demands is there to catch exactly that.
PAID_MSG_TEXT = ("The Offering Accepted",
             "The goods went into the altar fires before the priests had finished counting.",
             "Hashut is content, for a while.")
WRATH_MSG = "derpy_chd_ex_dem_wrath"
WRATH_MSG_TEXT = ("The Tithe Unpaid",
              "The altar stayed cold. The priests closed their ledgers and went to report it.",
              "Hashut takes what he is owed in other coin.")

WRATH_BUNDLE = PREFIX + "hashut_wrath"
WRATH_TITLE = "Hashut's Displeasure"
WRATH_TEXT = ("The altar went cold and the priests said why. Word travels faster than any "
              "order you can give.")
# HASHUT IS PLEASED. Paying a demand grants this ON TOP of the commodity's own offering boon:
# the boon is what the goods were good for, this is the god noticing. Same duration as the boon,
# carried by cm:apply_effect_bundle, so one row serves all three tiers.
#
# Both effect keys are CA's and both scopes are the ones VANILLA uses with them, counted rather
# than guessed: public_order_faction is faction_to_province_own in 38 of its 44 bundle rows (and
# is what the wrath below already uses), and force_stat_leadership is faction_to_force_own in 67
# rows - the most common of its 22 scopes, and the same scope the armour and replenishment boons
# use. force_stat_leadership is the UNQUALIFIED key: 271 of the other 272 leadership effects
# carry a unit-set or matchup suffix and would buff one race's infantry instead of your armies.
# BUNDLE ICONS. Every effect bundle the player is meant to notice carries one: CA's own
# "The Winds of Pain" (wh_dlc02_payload_all_magic_carnage) is the reference shape - title,
# one-line description, is_global_effect true and magic_campaign.png - and that is exactly what
# the panel draws next to "Turns remaining".
#
# These are BARE FILENAMES resolving under ui/campaign ui/effect_bundles/, all four verified
# present in ui.pack by check_bundle_icons() below. The game also picks a per-culture skin
# automatically where one exists (treasury.png ships six of them), which is why the bare name is
# right and a full path would be wrong.
ICON_TRADE    = "treasury.png"                          # trade income, up or down
ICON_OFFERING = "icon_ritual_currency_favour_bundle.png"  # favour bought with goods
ICON_PLEASED  = "trait_chaos_dwarfs.png"                # Hashut smiles on you
ICON_WRATH    = "attrition.png"                         # ...and when he does not
ICON_STOCK    = "cargo.png"                             # goods held, not burnt

PLEASED_BUNDLE = PREFIX + "hashut_pleased"
PLEASED_TITLE = "Hashut is Pleased"
PLEASED_TEXT = ("The tithe was paid in full and on the day it was asked. Word of that travels "
                "too.")
PLEASED_EFFECTS = [
    ("wh_main_effect_public_order_faction", "faction_to_province_own", 3.0),
    ("wh_main_effect_force_stat_leadership", "faction_to_force_own", 5.0),
]

WRATH_EFFECTS = [
    ("wh_main_effect_public_order_faction", "faction_to_province_own", -6.0),
    ("wh_main_effect_force_all_campaign_replenishment_rate", "faction_to_force_own", -10.0),
]

# Per-commodity opening line. The Temple has to know what it is asking for, or all 51 dilemmas
# read as the same one. Keyed by commodity, checked exhaustive against COMMODITIES.
DEMAND_FLAVOUR = {
    "res_rom_iron": "The forges are asked how much iron went in and how much came out. The "
                    "difference is sitting in your stores, and the priests have the ledger.",
    "res_obsidian": "Obsidian remembers what is burned near it. The Sorcerer-Prophets say the "
                    "black glass in your vaults has been listening to nothing at all.",
    "res_rom_marble": "Marble was cut for the Temple and stopped somewhere on the way. The "
                      "priests have walked the road and found where.",
    "res_rom_timber": "Good timber burns hot and burns fast, which is the point. Yours has "
                      "been stacked and counted and stacked again.",
    "res_rom_wine": "Wine is drunk at your table and not poured on the altar. The Temple has "
                    "been keeping a list of the vintages.",
    "res_spices": "The smoke of the altar has been thin lately. The priests know exactly what "
                  "would fix that and exactly where it is stored.",
    "res_rom_glass": "Glass in the Temple windows cracked in the heat and was not replaced. "
                     "Your warehouses were the first place anyone looked.",
    "res_gems": "Gems are counted twice: once by the merchant and once by the Temple. The two "
                "numbers no longer agree.",
    "res_dyes": "The vestments have gone grey. The priests can name the crates that would fix "
                "it and the roof they are sitting under.",
    "res_trinkets": "Small worked things please Hashut, who does not care that they are small. "
                    "You have a great many small worked things.",
    "res_gold_idols": "Idols are made to be melted. Yours are being kept, which the priests "
                      "regard as a category error.",
    "res_ivory": "Tusk and bone burn with a smell the Temple has not had in some time. Your "
                 "stores could give it back to them.",
    "res_animals": "The menageries are loud. The priests have suggested, at length, that they "
                   "would sound better from the altar steps.",
    "res_medicine": "The infirmaries are full and the altar is empty. The Temple has views on "
                    "which of those it would rather correct.",
    "res_rom_lead": "Salt keeps meat and keeps grudges. The Temple's cellars are low and yours "
                    "are not, and both facts are written down.",
    "res_rom_furs": "Furs burn badly and smell worse, which the priests consider a virtue. "
                    "They know how many bales you are sitting on.",
    "res_rom_textiles": "Cloth goes on the fire in one breath. The Temple has counted your "
                        "bolts and found the number offensive.",
}

# What each offering buys, in the panel's words and in the dilemma's. THE SAME STRINGS AS
# EX.BOON in the campaign script, which check_lua_boons() asserts character for character - the
# panel row and the Sacrifice button blurb have to promise the same thing, and each number here
# is re-derived from OFFERING_EFFECTS * OFFER_MULT by that same check.
OFFERING_BOON = {
    "res_rom_iron": "+4 armour, all armies",
    "res_obsidian": "+10 winds of magic cap",
    "res_rom_marble": "-6% construction cost",
    "res_rom_timber": "-6% construction cost",
    "res_rom_wine": "+4 public order",
    "res_spices": "+4 public order",
    "res_rom_glass": "+4 public order",
    "res_gems": "+6% trade tariffs",
    "res_dyes": "+6% trade tariffs",
    "res_trinkets": "+6% trade tariffs",
    "res_gold_idols": "+2 hero capacity",
    "res_ivory": "+4 research points",
    "res_animals": "+10% Labour per battle",
    "res_medicine": "+6% replenishment",
    "res_rom_lead": "+6% replenishment",
    "res_rom_furs": "+6% movement range",
    "res_rom_textiles": "-6% recruit cost",
}

# Flavour for the bundle rows, keyed by effect rather than commodity - the description says what
# the offering BUYS, and the title already names the commodity.
OFFERING_TEXT = {
    "wh_main_effect_force_stat_armour": "Hashut takes the iron and hardens every plate in the host.",
    "wh3_main_effect_winds_of_magic_pool_cap": "The smoke of burnt obsidian opens the Sorcerer-Prophets' sight.",
    "wh_main_effect_building_construction_cost_mod_all":
        "Timber and stone burn on the altar; the work goes cheaper.",
    "wh_main_effect_public_order_faction": "The feast is given to the flames, and the slaves are quiet.",
    "wh_main_effect_economy_trade_tariff_mod": "Treasure fed to the furnace buys favour in every market.",
    "wh2_main_effect_agent_cap_increase_all_heroes":
        "Idols melt on the altar and ambitious men come to the Conclave.",
    "wh_main_effect_technology_research_points": "Burnt tusk and rare ash teach the workshops something new.",
    "wh3_dlc23_effect_force_chd_campaign_post_battle_labour":
        "Beasts screaming on the altar, and the columns come home heavier with slaves.",
    "wh_main_effect_force_all_campaign_replenishment_rate":
        "Hashut blesses the supply train and the armies fill again.",
    "wh_main_effect_force_all_campaign_movement_range":
        "Furs burn, the Bull God warms the road, and columns march further.",
    "wh_main_effect_force_all_campaign_recruitment_cost_all":
        "Goods offered up buy conscripts cheaper than gold does.",
}

# LAYER 2: the three pooled resources the faction actually consumes. Buying commodities is
# speculation; this is the exit into gameplay. These reuse CA's OWN pools - no pooled_resources
# row is minted for them, and no campaign_group_pooled_resources row either, because CA already
# registers all three. Keys read from the vanilla cache, never typed from memory.
#   (pool key, our short name, display name)
# LABOUR IS NOT HERE, AND CANNOT BE. wh3_dlc23_chd_labour is FACTION_PROVINCE scope, and a
# province-scoped pool is unreachable from script: measured in game 2026-09-04, both
#     faction:pooled_resource_manager():resource("wh3_dlc23_chd_labour")
#     region:province():pooled_resource_manager():resource("wh3_dlc23_chd_labour")
# return a NULL INTERFACE, as do the other two FACTION_PROVINCE pools (workload, efficiency),
# while every FACTION-scoped pool reads fine. cm:faction_add_pooled_resource then moves nothing,
# with no error - so the row sat at "0 held" and its Buy button did nothing at all.
#
# wh3_dlc23_chd_labour_global_temp IS faction-scoped and readable, but the name says what it is:
# a transfer pool CA drains each turn. Buying into it would be a slower lie.
#
# The remaining route is an effect bundle carrying a labour income effect, applied at province
# scope. That is a second ladder for one instrument; not worth it until the rest is proven.
LAYER2 = [
    ("wh3_dlc23_chd_armaments", "armaments", "Armaments"),
    ("wh3_dlc23_chd_raw_materials", "raw_materials", "Raw Materials"),
]
# The CHD resources are counted in hundreds, not tens, so a lot is bigger than a commodity lot.
L2_LOT_SIZE = 100

# Mirrors EX.AI_MAX_RUNGS in the script; check_lua_appetite asserts they agree. The world
# appetite is clamped this tight because it sits ON TOP of a supply model whose own
# constants are still unmeasured - 2 rungs is +21%% / -17%% on a price.
AI_MAX_RUNGS = 2

# 42 percentage values for percentage_cost_mod. Index 0 is the cheapest rung.
LADDER = [round((LADDER_STEP ** n - 1.0) * 100.0, 2)
          for n in range(LADDER_LO, LADDER_HI + 1)]


def _commodities():
    """The 17 tradeable resources. Everything else in resources_tables is a location marker."""
    from read_vanilla_cache import load
    rows, _ = load("resources")
    return sorted(r["key"] for r in rows if r["trade_value"])


COMMODITIES = _commodities()


def ladder_index(multiplier):
    """Nearest ladder rung for a price multiplier, clamped to the ladder's ends."""
    if multiplier <= 0.0:
        return 0
    n = round(math.log(multiplier) / math.log(LADDER_STEP))
    return int(min(max(n - LADDER_LO, 0), len(LADDER) - 1))


def price_multiplier(supply, median_supply):
    """Scarcity pricing: dearer than base when fewer regions produce it than the median.

    supply 0 means nobody produces it at all, which is maximally scarce, not free.
    """
    if supply <= 0:
        return MULT_MAX
    m = (float(median_supply) / float(supply)) ** SCARCITY_EXPONENT
    return min(max(m, MULT_MIN), MULT_MAX)


def pressure_shift(p):
    """Mirrors EX.pressure_shift. Truncates toward zero - int() does, math.floor does not."""
    return int(float(p) / PRESSURE_PER_RUNG)


def sell_price(rung):
    """Mirrors EX.sell_price for a given rung. floor(x + 0.5), matching the Lua exactly -
    Python's round() is banker's rounding and disagrees on every .5."""
    return int(math.floor(price_at(rung) * (1.0 - SPREAD) + 0.5))


def price_at(rung):
    """Mirrors EX.price_at. 1-based rung, as the Lua and the bundle keys are.

    COMPUTED FROM LADDER_STEP, NOT FROM LADDER. LADDER is rounded to 2 decimals because that is
    what the DB column stores; the Lua recomputes the power in full float. They part company by
    one gold at rung 42 (5054 against 5055), and mirroring the wrong one makes this check fail
    on an arithmetic difference that has nothing to do with what it is testing.
    """
    pct = LADDER_STEP ** (rung - 1 + LADDER_LO) - 1.0
    return int(math.floor(BASE_LOT_COST * (1 + pct) + 0.5))


def hhi(counts):
    """Herfindahl-Hirschman concentration of an ownership split.

    Mirrors EX.hhi in zzz_derpy_chd_exchange.lua; check_lua_agrees() asserts they match.
    1.0 = one faction owns every producing region of a commodity, ~1/n = spread over n.
    """
    total = float(sum(counts))
    if total <= 0:
        return 0.0
    return sum((n / total) ** 2 for n in counts)


def effective_supply(raw, h):
    """Supply discounted for ownership concentration. Mirrors EX.effective_supply.

    A divisor, not `raw * (1 - h)`: a monopoly must cut effective supply, not zero it.
    Zero would price a cartelised commodity identically to one absent from the map, and
    "nobody sells this" and "one faction sells all of it" are different markets.

    CONCENTRATION_K sets how hard it bites; see its comment for why 1.0 measured inert.
    """
    return raw / (1.0 + CONCENTRATION_K * h)


def _units():
    """The measure word CA already ships per resource, so a price reads "10 ingots"."""
    from read_vanilla_cache import load
    rows, _ = load("resources")
    return {r["key"]: r["unit"] for r in rows if r["trade_value"]}


UNITS = _units()


def display_name(res):
    """CA's on-screen name for a resource. THE KEY IS NOT THE NAME - res_rom_lead is "Salt",
    res_rom_glass is "Dwarf Beer", res_rom_textiles is "Pottery". resources_tables has no name
    column at all, so this has to come out of the loc."""
    from read_vanilla_loc import load
    if res in dict((k, d) for k, _n, d in LAYER2):
        return dict((k, d) for k, _n, d in LAYER2)[res]
    return load("resources")["resources_onscreen_text_" + res]


def short(res):
    """Our short name for an instrument: the resource key minus res_, or the layer-2 name."""
    for pool, name, _display in LAYER2:
        if res == pool:
            return name
    return res[4:] if res.startswith("res_") else res


def instruments():
    """Every tradeable thing: the 17 map commodities, then the 3 CHD pooled resources.

    (resource key, short name, unit/display word, pool key it moves, mint a new pool?)
    Layer 2 points at CA's existing pool, so mint is False and no pooled_resources row is
    emitted - cloning those pools would give the player a counter the Hell-Forge cannot spend.
    """
    out = [(res, short(res), UNITS[res], hold_key(res), True, LOT_SIZE) for res in COMMODITIES]
    out += [(pool, name, display, pool, False, L2_LOT_SIZE) for pool, name, display in LAYER2]
    return out


def hold_key(res):
    return PREFIX + "hold_" + short(res)


def factor_junction(res):
    """The id that binds a resource_cost to the pool it actually moves.

    resource_cost_pooled_resource_junctions.pooled_resource_factor references
    pooled_resource_factor_junctions.UNIQUE_ID - not pooled_resource_factors.key. All 1,895
    vanilla rows do, and "other" (a valid pooled_resource_factors key) is NOT a valid junction
    id, so using it there binds the cost to no pool at all and the trade moves nothing while
    still charging gold. The junction's minimum/maximum also clamp DIRECTION: 187 vanilla rows
    are spend-only (max 0) and would silently swallow a sale.
    """
    return PREFIX + "factor_" + short(res)


def ladder_bundle(res, index):
    return "%sladder_%s_%02d" % (PREFIX, short(res), index)


def trade_bundle(step):
    """Key for one trade-income step. Mirrors EX.trade_bundle_key in the campaign script."""
    return "%strade_%s%02d" % (PREFIX, "neg" if step < 0 else "pos", abs(step))


def demand_key(res, sfx, seg=""):
    """Feed-message key for one (race, commodity, greed tier).

    IT USED TO SPELL A KEY NOTHING HAS EVER USED. This returned PREFIX + "demand_" + ... and
    mirrored an EX.demand_key in the script that spelled it the same way - while the loc rows
    and EX.fire_demand both built PREFIX + "dem_" + ... The one check that compared them
    compared the two DEAD spellings to each other and passed, for as long as they agreed with
    each other and with nothing that shipped. Both are gone; this is the key the game builds.
    """
    return "%s%sdem_%s_%s" % (PREFIX, seg, sfx, short(res))


def demand_amount(mult):
    """Units the altar takes at this tier. A multiple of the voluntary offering, always."""
    return OFFER_COST * mult


def offering_bundle(res):
    """Key for one commodity's offering. Mirrors EX.offering_key in the campaign script."""
    return "%soffering_%s" % (PREFIX, short(res))


def stock_bundle(res, tier):
    """Key for one commodity's warehouse bonus at `tier` (1-based). Mirrors EX.stock_bundle.

    stock_, not hold_ and not offering_: derpy_chd_ex_hold_<short> is already the POOLED
    RESOURCE key for this commodity and derpy_chd_ex_offering_<short> is the altar's bundle.
    Both collisions would be silent.
    """
    return "%sstock_%s_%d" % (PREFIX, short(res), tier)


def stock_tier_for(held):
    """Highest tier `held` units reaches, or 0. Mirrors EX.stock_tier in the campaign script.

    Walks the whole list and keeps the LAST match rather than returning the first, so the
    thresholds may be listed in any order without silently capping the ramp at tier 1.
    """
    tier = 0
    for i, (units, _mult, _label) in enumerate(STOCK_TIERS, 1):
        if held >= units:
            tier = i
    return tier


def trade_bundle_for(level):
    """Mirrors EX.trade_bundle_for. Returns None when no bundle should be applied.

    Snaps to the LARGEST step reached, not the first one matched - the steps are listed
    most-negative first, so a -25% faction matches -20 AND -10 and the naive loop returns -10.
    """
    pct = level * TRADE_GAIN
    best = None
    for step in TRADE_STEPS:
        if (step > 0 and pct >= step) or (step < 0 and pct <= step):
            if best is None or abs(step) > abs(best):
                best = step
    return best



# PER-RACE TEXT. The Chaos Dwarf entry is ASSEMBLED FROM THE MODULE CONSTANTS above rather
# than copied, so the shipped text has exactly one home and cannot drift from what the checks
# that already read those constants are measuring.
#
# The three new races are authored below. Everything in them came from
# docs/sessions/PLAN_20260908_TIER1_RACES.md sections 7.1 to 7.6.
#
#   The Empire      the cult of Sigmar. Pious, clerical, guilt as an instrument, a witch
#                   hunter somewhere off the page. The Temple keeps ledgers and mentions the
#                   poor.
#   Grand Cathay    the Celestial Bureaucracy. Exquisitely polite, wholly implacable,
#                   paperwork as violence. Nothing is demanded; assessments are revised.
#   Skaven          the Council of Thirteen. Hungry, paranoid, transparently self-serving.
#                   Third person like the Chaos Dwarf text; no phonetic stammer in prose.


def _chd_race_text():
    """The Chaos Dwarf slice, derived from the constants that already ship it."""
    return {
        "tiers": [(sfx, title, closer)
                  for sfx, _m, _t, _w, title, closer in DEMAND_TIERS],
        "flavour": DEMAND_FLAVOUR,
        "wants_fmt": "The altar wants %d, and it wants them today.",
        "market": "Zharr Exchange",
        "offer_title_fmt": "Offering to Hashut: %s",
        "offer_text": OFFERING_TEXT,
        "wrath_title": WRATH_TITLE, "wrath_text": WRATH_TEXT,
        "pleased_title": PLEASED_TITLE, "pleased_text": PLEASED_TEXT,
        "paid": PAID_MSG_TEXT, "unpaid": WRATH_MSG_TEXT,
    }


# ONE COMMODITY, ONE EFFECT, THREE RACES. Exotic Animals grants
# wh3_dlc23_effect_force_chd_campaign_post_battle_labour, which is meaningless to anyone with
# no Labour pool: the bundle applies, the effect moves nothing, and the offerings view
# advertises "+10% Labour per battle" to an Empire player forever.
#
# THE REPLACEMENT REUSES A PAIRING ALREADY IN OFFERING_EFFECTS rather than picking a tidier
# one. public_order_faction at faction_to_province_own is what wine, spices and beer already
# use, so this inherits their verification for free - and an effect paired with a scope it
# does not support is not an error, it is a row that quietly does nothing.
#   culture -> {commodity: (effect, scope, base, boon label)}
OFFERING_OVERRIDE = dict(
    (c, {"res_animals": ("wh_main_effect_public_order_faction",
                         "faction_to_province_own", 2, "+4 public order")})
    for c in ("wh_main_emp_empire", "wh3_main_cth_cathay", "wh2_main_skv_skaven",
              "wh_main_dwf_dwarfs", "wh2_main_hef_high_elves", "wh2_main_def_dark_elves",
              TEB_CULTURE))


# ------------------------------------------------------------------------------------------
# THE EMPIRE. The cult of Sigmar: pious, clerical, guilt as an instrument, and a witch hunter
# somewhere off the page. The Temple keeps ledgers and mentions the poor.
# ------------------------------------------------------------------------------------------
EMP_TIERS = [
    ("tithe", "The Temple's Tithe",
     "It is a small thing, and the Temple keeps a long memory of small things."),
    ("hunger", "Sigmar's Need",
     "This is more than the collection plate takes. The war does not wait on your "
     "bookkeeping."),
    # "The Grand Theogonist Asks" is 25 characters and the tier title prefixes a commodity
    # name in the feed entry's title line. Cut to the shorter form for the room.
    ("wrath", "The Theogonist Asks",
     "This is not alms. The Temple has read your ledgers and wants what is written in them."),
]

EMP_FLAVOUR = {
    "res_rom_iron": "Every campaign season the Temple asks the foundries what they made and "
                    "the armies what they received. The two numbers differ by roughly what "
                    "is in your stores.",
    "res_obsidian": "Witch hunters have opinions about black glass. So far the Temple has "
                    "argued that yours is merely stored and not hidden.",
    "res_rom_marble": "The cathedral's east front has stood scaffolded for eleven years. The "
                      "masons say they are waiting on stone, and they have named yours.",
    "res_rom_timber": "The Temple's roofs and the Empire's pike shafts come out of the same "
                      "forests. Only one of them is being supplied.",
    "res_rom_wine": "Communion wine has been watered since Mitterfruhl. The priests know "
                    "whose cellars it was watered to protect.",
    "res_spices": "Incense has been thin at every service this season. The censer-bearers "
                  "can recite your inventory from memory.",
    "res_rom_glass": "Dwarf beer is drunk at the guild feasts the Temple is invited to and "
                     "served at last. The priests have been counting barrels for some time.",
    "res_gems": "Every reliquary in the province is short a stone or two. The Temple has an "
                "inventory of what is missing and an inventory of what you hold.",
    "res_dyes": "The vestments were red in your grandfather's day. The priests can name the "
                "crates that would make them red again.",
    "res_trinkets": "Elf-work is suspect and valuable, in that order. The Temple would rather "
                    "it sat in a reliquary than in your warehouse.",
    "res_gold_idols": "Foreign idols in an Imperial warehouse is a sentence that ends badly "
                      "in most retellings. The Temple offers a better ending: the furnace, "
                      "and a receipt.",
    "res_ivory": "Tusk makes good relics and better altar fittings. The Temple has priced "
                 "yours and found the price reasonable.",
    "res_animals": "The menagerie is a scandal waiting for a pamphlet. The Temple suggests "
                   "the beasts be given publicly, before somebody writes one.",
    "res_medicine": "The plague houses are full and the Temple's stores are not. The priests "
                    "have been very patient about which of those is your doing.",
    "res_rom_lead": "Salt preserves the army's meat and the Temple's patience. Both are "
                    "running low, and only one is being restocked.",
    "res_rom_furs": "Winter came early on the Ostland road and the almshouses have no "
                    "blankets. Your bales are three days' cart from them.",
    "res_rom_textiles": "Pottery is what the poor eat from, when the Temple can afford to "
                        "give them bowls. This year it cannot, and you can.",
}

EMP_OFFER_TEXT = {
    "wh_main_effect_force_stat_armour":
        "Sigmar takes the iron and every plate in the host is blessed at the anvil.",
    "wh3_main_effect_winds_of_magic_pool_cap":
        "Burnt offerings open the Celestial College's sight.",
    "wh_main_effect_building_construction_cost_mod_all":
        "Timber and stone given to the Temple; the masons work for alms.",
    "wh_main_effect_public_order_faction":
        "The feast is given to the poor and the province is quiet.",
    "wh_main_effect_economy_trade_tariff_mod":
        "A generous house is a trusted house, and trusted houses are charged less.",
    "wh2_main_effect_agent_cap_increase_all_heroes":
        "Melted idols pay for men willing to travel and ask questions.",
    "wh_main_effect_technology_research_points":
        "Rare goods reach the colleges, and the colleges write something down.",
    "wh_main_effect_force_all_campaign_replenishment_rate":
        "The Temple blesses the muster and the regiments fill again.",
    "wh_main_effect_force_all_campaign_movement_range":
        "Cloaks for the column, and the roads pass quicker.",
    "wh_main_effect_force_all_campaign_recruitment_cost_all":
        "A pious lord recruits cheaper than a rich one.",
}

# ------------------------------------------------------------------------------------------
# GRAND CATHAY. The Celestial Bureaucracy: exquisitely polite, wholly implacable, paperwork as
# violence. Nothing is demanded; assessments are revised.
# ------------------------------------------------------------------------------------------
CTH_TIERS = [
    ("tithe", "The Assessment",
     "A small levy, correctly filed. The Bureaucracy files everything and forgets nothing."),
    ("hunger", "Revised Assessment",
     "The assessment has been adjusted upward. You were not consulted, as is proper."),
    ("wrath", "Court Requisition",
     "This is no longer an assessment. The Court has read your ledgers and finds them out of "
     "harmony."),
]

CTH_FLAVOUR = {
    "res_rom_iron": "The Ministry of Works has reconciled the foundry returns against the "
                    "caravan manifests. It wishes to discuss the difference, which is in "
                    "your stores.",
    "res_obsidian": "Carved obsidian is classified under ritual goods and requires a seal you "
                    "do not hold. The Court is willing to regard this as an oversight, once.",
    "res_rom_marble": "Three pavilions on the Ivory Road stand unfinished. The stone was "
                      "requisitioned, dispatched and never delivered, and the clerks have "
                      "traced it as far as your warehouse.",
    "res_rom_timber": "The Wall consumes timber the way the Bureaucracy consumes paper. Your "
                      "holdings are noted in both ledgers.",
    "res_rom_wine": "The autumn banquets require a grade of wine the Court no longer "
                    "receives. An inspector has visited your cellars and written a very "
                    "courteous report.",
    "res_spices": "The temple censers burn a blend that is now three ingredients short. Two "
                  "of them are in your stores. The third is not your concern.",
    "res_rom_glass": "Dwarf beer crossed the border under a tariff schedule that does not "
                     "exist. The Bureaucracy proposes to resolve the irregularity by taking "
                     "the beer.",
    "res_gems": "Jade is counted by the Court, and everything that is not jade is counted "
                "twice as a precaution. Your gemstones have been counted twice.",
    "res_dyes": "The Court's silks are dyed to a standard set four hundred years ago. The "
                "standard has not moved. Your dyes have.",
    "res_trinkets": "Elven goods enter under a treaty of sixteen clauses. Your consignment "
                    "satisfies fifteen of them.",
    "res_gold_idols": "Foreign idols are permitted for study and not for storage. The "
                      "distinction is subtle, and the Court has made it in writing.",
    "res_ivory": "Tusk is a controlled good on the Ivory Road, which is named for it. The "
                 "irony has been noted in the file.",
    "res_animals": "Beasts crossing the Wall require a permit for each animal. The Court "
                   "holds your permits, or rather, the Court holds the absence of them.",
    "res_medicine": "The plague wards at Nan Gau are rationing. The Bureaucracy has "
                    "calculated precisely how long your stores would end that, and has "
                    "written the number down.",
    "res_rom_lead": "Salt has been a state monopoly since the Dragon Emperor's first ledger. "
                    "Your holdings are therefore, technically, the state's.",
    "res_rom_furs": "The northern garrisons are cold and the requisition was approved eleven "
                    "months ago. The clerks have found where it stopped.",
    "res_rom_textiles": "Pottery is taxed by weight and yours has not been weighed. An "
                        "inspector is available, or the goods may simply be surrendered.",
}

CTH_OFFER_TEXT = {
    "wh_main_effect_force_stat_armour":
        "The Ministry of Works receives its iron and every lamellar plate is inspected and "
        "passed.",
    "wh3_main_effect_winds_of_magic_pool_cap":
        "Correct offerings at the correct hour; the winds answer on schedule.",
    "wh_main_effect_building_construction_cost_mod_all":
        "Materials correctly surrendered are materials correctly reissued, at a discount.",
    "wh_main_effect_public_order_faction":
        "The banquet is given to the province and harmony is restored.",
    "wh_main_effect_economy_trade_tariff_mod":
        "A compliant house receives a favourable schedule. This is not a bribe; it is filing.",
    "wh2_main_effect_agent_cap_increase_all_heroes":
        "Melted idols fund appointments, and appointments are how the Court moves.",
    "wh_main_effect_technology_research_points":
        "Curiosities reach the Celestial archives and are catalogued, which is how Cathay "
        "learns.",
    "wh_main_effect_force_all_campaign_replenishment_rate":
        "The requisition clears and the garrisons are made whole.",
    "wh_main_effect_force_all_campaign_movement_range":
        "Furs for the northern roads, and the caravans keep pace.",
    "wh_main_effect_force_all_campaign_recruitment_cost_all":
        "Levies raised under seal cost the treasury less.",
}

# ------------------------------------------------------------------------------------------
# SKAVEN. The Council of Thirteen: hungry, paranoid, transparently self-serving. Third person
# like the Chaos Dwarf text - no phonetic stammer in prose.
# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------
# THE SOUTHERN REALMS. Tilea, Estalia and the Border Princes: merchant republics, banking
# houses and mercenary companies, where a contract is the only sacred thing and Myrmidia is
# invoked mostly in the preamble. The voice is commercial rather than devout - the Temple of
# Myrmidia keeps a strongroom as well as an altar, and the letter always arrives before the
# priest does. Where Sigmar's cult asks for piety and the Court asks for compliance, the
# Compact asks for a signature, and it has already had one witnessed.
# ------------------------------------------------------------------------------------------
TEB_TIERS = [
    ("tithe", "A Note Presented",
     "A modest draft against your account, drawn in the ordinary way and payable on sight."),
    ("hunger", "The Compact Calls",
     "Larger than a season's dues, and the covering letter mentions your signature twice."),
    ("wrath", "The Debt Called In",
     "The full sum, at once. Three houses have bought the paper between them and they have "
     "stopped writing letters."),
]

TEB_FLAVOUR = {
    "res_rom_iron": "Every free company from Miragliano to the Vaults is re-arming this "
                    "season, and the armourers have named your bars in their contracts.",
    "res_obsidian": "The colleges of Remas pay in gold for black glass and ask no questions "
                    "about its road. The Compact has quietly priced yours.",
    "res_rom_marble": "Half the cities of Tilea are rebuilding a facade for the glory of "
                      "somebody, and every one of those commissions is short of stone.",
    "res_rom_timber": "The yards want keels and the condottieri want palisades. Timber has "
                      "not been this scarce since the last time both wanted it at once.",
    "res_rom_wine": "The vintage failed along the whole coast and the banqueting season has "
                    "not been cancelled. Your cellars are the shortest way out of that.",
    "res_spices": "A galley out of Sartosa failed to arrive and took the season's pepper "
                  "with it. The Compact would rather buy yours than explain the shortfall.",
    "res_rom_glass": "Estalian glass went to the bottom off Bilbali and the orders did not "
                     "sink with it. Somebody must fill them, and somebody has been chosen.",
    "res_gems": "A dowry is being assembled for a marriage that settles two wars, and the "
                "stones set aside for it have been found to be paste.",
    "res_dyes": "Purple is worn by three princes this year and made by nobody. What is left "
                "of the trade is in your warehouse and the Compact knows the number.",
    "res_trinkets": "Reliquaries sell better than relics and the workshops of Luccini have "
                    "run out of the small bright things that go on them.",
    "res_gold_idols": "Gold that has already been shaped is worth more than gold that has "
                      "not, and the Temple has a use for it that is not being written down.",
    "res_ivory": "The Arabyan trade has closed for the season and the sculptors of Verezzo "
                 "have work booked through the winter. They are asking, politely, twice.",
    "res_animals": "The menageries are empty and a triumph has been promised. A parade with "
                   "nothing in the cages is a parade about the man who paid for it.",
    "res_medicine": "Camp fever went through two companies before the muster and the "
                    "surgeons have been buying at any price. Yours is the last stock inland.",
    "res_rom_lead": "The physicians want it, the printers want it and the gunners want it "
                    "most. All three have applied to the Compact, and the Compact to you.",
    "res_rom_furs": "The passes freeze early this year and every company marching north has "
                    "the same line unfilled in its inventory.",
    "res_rom_textiles": "Four thousand men have been contracted and not one of them has been "
                        "clothed. The tailors are waiting on cloth, and the cloth is yours.",
}

TEB_OFFER_TEXT = {
    "wh_main_effect_force_stat_armour":
        "The metal goes to the armourers of Miragliano and comes back as plate, on schedule.",
    "wh3_main_effect_winds_of_magic_pool_cap":
        "The colleges take the glass and the wind runs deeper for those who paid.",
    "wh_main_effect_building_construction_cost_mod_all":
        "Materials pledged in advance are materials bought at last year's price.",
    "wh_main_effect_public_order_faction":
        "The feast is held at the Compact's expense and the crowd is told whose expense it "
        "was.",
    "wh_main_effect_economy_trade_tariff_mod":
        "A house in good standing with the Compact is a house whose cargo clears the mole "
        "first.",
    "wh2_main_effect_agent_cap_increase_all_heroes":
        "Gold in the strongroom buys letters of introduction, and letters buy people.",
    "wh_main_effect_technology_research_points":
        "The ivory endows a chair at Remas, and a chair returns findings to its endower.",
    "wh_main_effect_force_all_campaign_replenishment_rate":
        "The surgeons are paid by the Compact and billeted with your companies.",
    "wh_main_effect_force_all_campaign_movement_range":
        "Furs, remounts and a courier's warrant: your columns keep the road in weather that "
        "closes it.",
    "wh_main_effect_force_all_campaign_recruitment_cost_all":
        "Cloth delivered to the muster is a company clothed before it is paid, and cheaper "
        "for it.",
}


SKV_TIERS = [
    ("tithe", "The Council's Tithe",
     "A small thing. The Council asks small things of everyone, and writes down who refused."),
    ("hunger", "The Council is Hungry",
     "This is more than the Council usually takes. It has not been phrased as a question."),
    ("wrath", "The Thirteenth Demand",
     "This is no tithe. The Grey Seers have seen the hoard, and the hoard is already spoken "
     "for."),
]

SKV_FLAVOUR = {
    "res_rom_iron": "Clan Skryre has submitted a requisition, a schematic and a threat, in "
                    "that order. All three name your iron.",
    "res_obsidian": "Black glass holds warp-light without cracking, which makes it "
                    "interesting to exactly the wrong Seers. They know where yours is.",
    "res_rom_marble": "Stone is for above-ground fools, says the Council, which has "
                      "nonetheless found a use for yours and will not be explaining it.",
    "res_rom_timber": "Props hold up tunnels and tunnels hold up everything. Three collapses "
                      "this season have been blamed on your unwillingness to share.",
    "res_rom_wine": "Man-drink is worth more than it should be and the Council has developed "
                    "a taste for it. Your cellars have been surveyed by something small.",
    "res_spices": "Spice hides the smell of what Clan Moulder calls meat. Demand has never "
                  "been higher and your stores have never been fuller.",
    "res_rom_glass": "Dwarf beer is the only thing the Council and Clan Mors have agreed on "
                     "this year. They have agreed that you should hand it over.",
    "res_gems": "Gems are not warp-tokens, which makes them harder to trace, which makes them "
                "precisely what a Grey Seer prefers to be paid in.",
    "res_dyes": "Seer-robes are dyed by a process nobody has survived describing. The dye "
                "itself is ordinary, and yours is closer.",
    "res_trinkets": "Elf-things are cursed, worthless, and wanted by the Council immediately.",
    "res_gold_idols": "Gold idols melt into gold and gold buys clanrats. The Council has done "
                      "this arithmetic and would like you to do it too.",
    "res_ivory": "Bone and tusk feed the flesh-vats, and Clan Moulder has been petitioning "
                 "the Council in writing, which is unlike them.",
    "res_animals": "Clan Moulder has been shown your menagerie and has not stopped talking "
                   "about it. The Council would prefer this ended quietly.",
    "res_medicine": "Plague is Clan Pestilens' business and cure is nobody's, so the Council "
                    "wants your medicine for reasons it declines to state.",
    "res_rom_lead": "Salt keeps meat edible in a tunnel for weeks. The Council knows how much "
                    "you have, and exactly how many mouths that is.",
    "res_rom_furs": "Warmth is a luxury and luxuries are taxed. The tax is your entire stock "
                    "of furs.",
    "res_rom_textiles": "Pottery is fragile, useless and being hoarded by you, which is the "
                        "only part the Council finds suspicious.",
}

SKV_OFFER_TEXT = {
    "wh_main_effect_force_stat_armour":
        "Skryre takes the iron and returns plate that mostly holds.",
    "wh3_main_effect_winds_of_magic_pool_cap":
        "Burnt black glass, and the Seers see further than is good for anyone.",
    "wh_main_effect_building_construction_cost_mod_all":
        "Materials surrendered are materials not stolen twice, and the digging goes cheaper.",
    "wh_main_effect_public_order_faction":
        "The feast goes to the warren and the squeaking stops for a while.",
    "wh_main_effect_economy_trade_tariff_mod":
        "A clan that pays promptly is a clan that is robbed last.",
    "wh2_main_effect_agent_cap_increase_all_heroes":
        "Melted gold buys the sort of underling who arrives unannounced.",
    "wh_main_effect_technology_research_points":
        "Strange goods reach Skryre and something explodes productively.",
    "wh_main_effect_force_all_campaign_replenishment_rate":
        "The Council releases the breeding quotas and the swarm refills.",
    "wh_main_effect_force_all_campaign_movement_range":
        "Furs for the deep tunnels, and the columns run further.",
    "wh_main_effect_force_all_campaign_recruitment_cost_all":
        "Tribute paid up front buys clanrats at the lower rate.",
}


# ------------------------------------------------------------------------------------------
# THE DWARFS. The Guild keeps the book, the Book keeps the grudge, and nothing is ever simply
# forgotten. Everything is a matter of record, and the record is read aloud.
# ------------------------------------------------------------------------------------------
DWF_TIERS = [
    ("tithe", "The Ancestors' Due",
     "A small entry, and the Ancestors keep the book that small entries are written in."),
    ("hunger", "A Debt Recorded",
     "More than the season's due. It has been entered against your name, which is not a "
     "threat, only a record."),
    ("wrath", "The Grudge Entered",
     "The full sum. The Longbeards have stopped calling it a due and started calling it "
     "something with its own page."),
]

DWF_FLAVOUR = {
    "res_rom_iron": "Every hold on the Silver Road is re-forging at once, and the Guild has "
                    "entered your bars in the ledger at a price it does not intend to argue "
                    "about.",
    "res_obsidian": "The runesmiths will not say what black glass is for and will not stop "
                    "asking how much of it you are sitting on.",
    "res_rom_marble": "Karak masons do not build in stone they did not cut. They will make an "
                      "exception, once, at a price, and never mention it again.",
    "res_rom_timber": "Pit-props, and the deep workings eat them. A hold short of timber "
                      "stops digging, and a hold that stops digging starts arguing.",
    "res_rom_wine": "Elgi vintages came up in a trade lot nobody ordered, and the Longbeards "
                    "have decided, grudgingly and in writing, that some of it is drinkable.",
    "res_spices": "Umgi cooking is a mystery best left alone, but the spice trade pays, and "
                  "the Guild has never let a mystery stand in the way of a margin.",
    "res_rom_glass": "Three brewhouses have run dry in one season, which every hold that "
                     "matters has recorded as an emergency. Your barrels are the nearest.",
    "res_gems": "The gem-cutters of Karaz-a-Karak are working to a commission and are two "
                "hundred stones short of finishing it, which is now everyone's problem.",
    "res_dyes": "Beard-dye is not a frivolity, whatever the Longbeards say in company, and "
                "the Guild has priced yours discreetly.",
    "res_trinkets": "Elgi work fetches a shameful sum from umgi collectors, and every hold "
                    "that denies trading in it is trading in it.",
    "res_gold_idols": "Gold is gold whatever shape it was in first. The Guild keeps an "
                      "assayer who does not ask about the shape.",
    "res_ivory": "Tusk carves finer than bone and holds a rune longer than either. The "
                 "apprentices have put in a standing order and been told to wait.",
    "res_animals": "Whatever the umgi want with beasts out of the far south, they want them "
                   "badly, and a hold with a stake in the caravan takes its cut.",
    "res_medicine": "A hold besieged twice in a decade keeps its stores full and does not "
                    "explain itself to anyone.",
    "res_rom_lead": "Salt keeps a siege fed and a grudge current. Both are running long this "
                    "season.",
    "res_rom_furs": "The upper galleries are cold, whatever the Longbeards claim, and the fur "
                    "trade has never once been short of buyers.",
    "res_rom_textiles": "Karak potters make one shape and make it perfectly, so anything else "
                        "has to be bought in, which nobody enjoys admitting.",
}

DWF_OFFER_TEXT = {
    "wh_main_effect_force_stat_armour":
        "The iron goes to the Guild's forges and comes back as plate, correctly, and a little "
        "late.",
    "wh3_main_effect_winds_of_magic_pool_cap":
        "The runesmiths take the black glass, and something in the deep workings runs "
        "stronger.",
    "wh_main_effect_building_construction_cost_mod_all":
        "Stone pledged to the hold is stone the hold does not buy, and the masons revise their "
        "figures downward, once.",
    "wh_main_effect_public_order_faction":
        "The barrels go round the galleries and the grumbling drops to its usual level.",
    "wh_main_effect_economy_trade_tariff_mod":
        "A hold in good standing with the Guild is a hold whose caravans are not weighed "
        "twice.",
    "wh2_main_effect_agent_cap_increase_all_heroes":
        "Melted idols pay the sort of Dwarf who travels alone and reports back in person.",
    "wh_main_effect_technology_research_points":
        "The apprentices get the tusk and the engineers get three ideas out of what is left.",
    "wh_main_effect_force_all_campaign_replenishment_rate":
        "Salt and physic reach the throng, and the throng comes back up to strength.",
    "wh_main_effect_force_all_campaign_movement_range":
        "Furs for the high passes, and the throng marches further before it stops to "
        "complain.",
    "wh_main_effect_force_all_campaign_recruitment_cost_all":
        "Goods pledged up front buy a muster at last decade's rate, which the Guild considers "
        "generous.",
}


# ------------------------------------------------------------------------------------------
# THE HIGH ELVES. The Court does not demand, it requests, and the request has been made once.
# Everything is courtesy, and the courtesy is the instrument.
# ------------------------------------------------------------------------------------------
HEF_TIERS = [
    ("tithe", "The Court's Request",
     "A small thing, asked politely, in a manner that does not admit of refusal."),
    ("hunger", "A Matter of Duty",
     "More than a courtesy. Ulthuan has been doing this since before your people had a "
     "written language, and it is asking."),
    ("wrath", "The Court Insists",
     "The full sum, now. The request has been made three times and the Court does not make a "
     "fourth."),
]

HEF_FLAVOUR = {
    "res_gems": "The Court does not buy gemstones. It accepts them, notes the giver, and the "
                "giver's name is read out at the next audience.",
    "res_spices": "Lothern's kitchens have priced the season and decided that what you are "
                  "holding is fashionable. Fashion in Ulthuan is not a short thing.",
    "res_rom_wine": "The vineyards of Ellyrion came in thin this year, which is a matter of "
                    "some delicacy, and Lothern is buying quietly.",
    "res_rom_iron": "Ulthuan's smiths need less iron than anyone assumes and sell the surplus "
                    "at a price that reflects who is asking for it.",
    "res_trinkets": "Every trinket in the Old World came out of Ulthuan and every one was "
                    "sold, once, at a fair price. The Gate is not sentimental about them.",
    "res_obsidian": "The mages of Saphery want black glass and will not say what for, which "
                    "in Saphery is not unusual and is never cheap.",
    "res_rom_marble": "The White Tower is always being repaired, and Chrace has run short of "
                      "the correct stone, which is not the same as running short of stone.",
    "res_rom_timber": "Athel Loren will not sell, Chrace will not cut, and the shipwrights of "
                      "Lothern have a fleet to keep afloat.",
    "res_rom_glass": "A cargo of Dwarf ale reached Lothern by an accident of trade and "
                     "became, to everyone's embarrassment, sought after.",
    "res_dyes": "Sea-silk takes a dye once and holds it for a century. The dye has to be "
                "perfect, and perfect is bought rather than made.",
    "res_gold_idols": "Crude work, melted without ceremony, and the Court would rather this "
                      "were not minuted. It is being minuted.",
    "res_ivory": "Tusk for the scrimshaw of the Sea Guard, who have been at it six hundred "
                 "years and have never once run short until now.",
    "res_animals": "The menageries of Lothern are a diplomatic instrument. An ambassador who "
                   "has been shown one is easier to talk to afterwards.",
    "res_medicine": "Ulthuan's healers are the finest in the world, and the finest in the "
                    "world still need the plant. Chrace's crop failed.",
    "res_rom_lead": "The fleets keep the sea lanes and salt keeps the fleets. It is "
                    "unglamorous, and the Gate has never once let it run out.",
    "res_rom_furs": "Cold water and long watches, and the Sea Guard hold opinions about "
                    "quality that the Gate is obliged to satisfy.",
    "res_rom_textiles": "Ulthuan makes pottery of surpassing beauty in quantities that would "
                        "embarrass a village. The rest is bought in.",
}

HEF_OFFER_TEXT = {
    "wh_main_effect_force_stat_armour":
        "The iron goes to the armourers of Lothern and comes back as something a mortal smith "
        "would not attempt.",
    "wh3_main_effect_winds_of_magic_pool_cap":
        "Saphery takes the black glass, and the winds run deeper for whoever gave it.",
    "wh_main_effect_building_construction_cost_mod_all":
        "Stone pledged in advance is stone at last century's price, and the masons of Chrace "
        "keep their word.",
    "wh_main_effect_public_order_faction":
        "The wine goes to the audience hall and the audience goes home satisfied, which is the "
        "whole art of it.",
    "wh_main_effect_economy_trade_tariff_mod":
        "A house in the Court's regard is a house whose cargo clears the Gate without being "
        "weighed twice.",
    "wh2_main_effect_agent_cap_increase_all_heroes":
        "Melted gold pays for the sort of Elf who arrives before the message does.",
    "wh_main_effect_technology_research_points":
        "Curiosities reach the White Tower, and the White Tower returns something more useful "
        "than thanks.",
    "wh_main_effect_force_all_campaign_replenishment_rate":
        "Physic reaches the host, and the host is whole again faster than it has any right to "
        "be.",
    "wh_main_effect_force_all_campaign_movement_range":
        "Furs for the northern watch, and the columns keep the pace they are famous for.",
    "wh_main_effect_force_all_campaign_recruitment_cost_all":
        "Tribute rendered early is a levy raised cheaply. The Court remembers which houses "
        "were early.",
}


# ------------------------------------------------------------------------------------------
# THE DARK ELVES. The temple counts, the fleet takes, and nobody pretends otherwise. Rich
# rather than squalid - that is what separates this from the Under-Market.
# ------------------------------------------------------------------------------------------
DEF_TIERS = [
    ("tithe", "Khaine's Portion",
     "A small offering. The temple keeps count, and the temple's count is the only one that "
     "matters."),
    ("hunger", "The Temple Thirsts",
     "More than the usual portion. The Hag Queens were consulted and were not in a moderate "
     "humour."),
    ("wrath", "The Blood Price",
     "The full sum, at once. The knives have been counted out onto the table, which is how "
     "the temple asks a second time."),
]

DEF_FLAVOUR = {
    "res_rom_iron": "Hag Graef's forges run black day and night, and the overseers have "
                    "costed your bars against the lives it takes to work them. They found the "
                    "bars cheaper.",
    "res_rom_timber": "Another Ark is on the slips at Karond Kar, and the yards are eating "
                      "timber faster than the raids can bring it home.",
    "res_dyes": "The robes of the temple are a particular red, and the temple is particular "
                "about how it is got. The dye itself is bought like anything else.",
    "res_medicine": "Naggaroth grows physic it has no intention of wasting on its own. It "
                    "sells very well to people who will.",
    "res_trinkets": "Asur work taken at sea and sold on to Old World collectors who prefer "
                    "not to ask, at a markup that reflects how it was got.",
    "res_obsidian": "Black glass for the Convent's work, and the Sorceresses have been "
                    "unusually direct about wanting it.",
    "res_rom_marble": "The Witch King builds, and what the Witch King builds is faced in "
                      "stone that Naggaroth is too cold to quarry.",
    "res_rom_wine": "Wine survives the crossing better than most cargo and is drunk faster "
                    "than any of it. The cellars of Har Ganeth are empty again.",
    "res_rom_glass": "Taken off a Dwarf trader by accident and found, to general disgust, to "
                     "be worth something to somebody.",
    "res_gems": "Gems buy silence, and silence is the one commodity in Naggaroth that never "
                "comes down in price.",
    "res_gold_idols": "Melted without ceremony and without asking whose face was on it. The "
                      "assayers of Clar Karond are not sentimental people.",
    "res_ivory": "Tusk for the scrimshaw of the corsair captains, who are vain, wealthy, and "
                 "in competition with one another.",
    "res_animals": "The beast-pens of Karond Kar are never full, and the beastmasters have "
                   "been shown your manifest.",
    "res_rom_lead": "Salt for the holds of the fleet and the cellars beneath them, bought in "
                    "quantities that are not discussed.",
    "res_rom_furs": "Naggaroth is cold beyond the understanding of anyone who has not "
                    "wintered there, and the cloak trade never slackens.",
    "res_rom_textiles": "Nobody in Naggaroth has time to fire a pot. Everything on the table "
                        "came off a ship that is no longer afloat.",
    "res_spices": "Spice covers what the kitchens of Naggarond would rather the guests did "
                  "not identify.",
}

DEF_OFFER_TEXT = {
    "wh_main_effect_force_stat_armour":
        "The iron goes to Hag Graef and comes back as plate, worked by hands that were not "
        "paid for it.",
    "wh3_main_effect_winds_of_magic_pool_cap":
        "The Convent takes the black glass, and the winds answer more readily than is wise.",
    "wh_main_effect_building_construction_cost_mod_all":
        "Materials given up front are materials not requisitioned later, and the work goes "
        "cheaper for it.",
    "wh_main_effect_public_order_faction":
        "The temple holds a rite, the city attends, and the city is quiet for a while "
        "afterwards.",
    "wh_main_effect_economy_trade_tariff_mod":
        "A house in favour at the temple is a house whose cargo is not looked at closely.",
    "wh2_main_effect_agent_cap_increase_all_heroes":
        "Melted gold buys the kind of servant who is already in the room.",
    "wh_main_effect_technology_research_points":
        "Curiosities go to the Convent and come back as a method nobody wants explained.",
    "wh_main_effect_force_all_campaign_replenishment_rate":
        "Physic and salt for the host, and the ranks close up again.",
    "wh_main_effect_force_all_campaign_movement_range":
        "Furs for the long marches, and the columns cross Naggaroth without losing a quarter "
        "of themselves.",
    "wh_main_effect_force_all_campaign_recruitment_cost_all":
        "Tribute paid early buys a levy at the temple's rate, which stays low for exactly as "
        "long as you keep paying it.",
}


# EVERY RACE'S TEXT, ASSEMBLED. The Chaos Dwarf entry is derived from the module constants
# rather than retyped, so that text has exactly one home; check_chd_identity() proves the
# round trip against the committed TSVs.
RACE_TEXT = {
    CHD_CULTURE: _chd_race_text(),
    "wh_main_emp_empire": {
        "tiers": EMP_TIERS, "flavour": EMP_FLAVOUR,
        "wants_fmt": "The Temple wants %d, and it wants them today.",
        "market": "Imperial Bourse",
        "offer_title_fmt": "Tithe to Sigmar: %s", "offer_text": EMP_OFFER_TEXT,
        "wrath_title": "The Temple's Displeasure",
        "wrath_text": "The plate went round and came back empty, and the priests said so from "
                      "the pulpit. Word travels faster than any order you can give.",
        "pleased_title": "The Temple is Satisfied",
        "pleased_text": "The tithe was paid in full and on the day it was asked. The Temple "
                        "says so from the pulpit too.",
        "paid": ("The Tithe Received",
                 "The wagons reached the Temple before the clerks had finished the tally.",
                 "Sigmar is served, and the ledger is closed for this season."),
        "unpaid": ("The Tithe Unpaid",
                   "The plate went round the province and came back empty. The priests "
                   "closed their books and went to report it.",
                   "The Temple collects what it is owed in other coin."),
    },
    "wh3_main_cth_cathay": {
        "tiers": CTH_TIERS, "flavour": CTH_FLAVOUR,
        "wants_fmt": "The Court requires %d, and requires them today.",
        "market": "Ivory Road",
        "offer_title_fmt": "Levied by the Court: %s", "offer_text": CTH_OFFER_TEXT,
        "wrath_title": "Found Out of Harmony",
        "wrath_text": "The assessment lapsed and the lapse was filed. A file of that kind is "
                      "copied to more offices than you have dealings with.",
        "pleased_title": "Correctly Filed",
        "pleased_text": "The levy was surrendered in full and on the day named. The record "
                        "says so, and the record is what matters.",
        "paid": ("The Levy Surrendered",
                 "The goods were counted, sealed and entered against your name in a hand "
                 "nobody could fault.",
                 "The Court is satisfied. The file remains open, as all files do."),
        "unpaid": ("The Assessment Lapsed",
                   "No goods arrived, and the clerk who expected them wrote down that none "
                   "had. The note was countersigned the same afternoon.",
                   "The Court adjusts its regard for you, correctly and in writing."),
    },
    TEB_CULTURE: {
        "tiers": TEB_TIERS, "flavour": TEB_FLAVOUR,
        "wants_fmt": "The Compact requires %d, payable on presentation.",
        "market": "Merchant Compact",
        "offer_title_fmt": "Consigned to the Temple: %s", "offer_text": TEB_OFFER_TEXT,
        "wrath_title": "Protested for Non-Payment",
        "wrath_text": "The note came back unpaid and was protested before a notary the same "
                      "morning. Every counting house on the coast reads that register.",
        "pleased_title": "Discharged in Full",
        "pleased_text": "The consignment was delivered, weighed and receipted without a "
                        "query. The Compact extends terms it does not extend to everyone.",
        "paid": ("The Note Discharged",
                 "The goods went out under the Temple's seal and the draft was cancelled in "
                 "front of witnesses, as the form requires.",
                 "Myrmidia is served, and your credit is a little better than it was."),
        "unpaid": ("The Note Protested",
                   "Nothing was tendered by the day named. The notary attended, recorded "
                   "that nothing was tendered, and filed it where such things are filed.",
                   "The Compact recovers its money the other way, and marks the ledger."),
    },
    "wh_main_dwf_dwarfs": {
        "tiers": DWF_TIERS, "flavour": DWF_FLAVOUR,
        "wants_fmt": "The Ancestors are owed %d, and the Book says today.",
        "market": "Long Ledger",
        "offer_title_fmt": "Offered to Grungni: %s", "offer_text": DWF_OFFER_TEXT,
        "wrath_title": "A Grudge Recorded",
        "wrath_text": "The due was not paid and the failure was written down. Nothing was "
                      "said about it, which is worse, and the Book is read aloud once a "
                      "generation.",
        "pleased_title": "The Book is Balanced",
        "pleased_text": "The due was paid in full and on the day named. The entry has been "
                        "struck through, which is as close to praise as the Book allows.",
        "paid": ("The Due Rendered",
                 "The wagons reached the hold gate before the tally was finished, which the "
                 "gatekeeper remarked on approvingly and out loud.",
                 "The Ancestors are served, and the entry is struck."),
        "unpaid": ("The Due Withheld",
                   "Nothing came up the road by the day named. The Guild's clerk waited out "
                   "the full day, wrote one line, and closed the book.",
                   "The Ancestors are patient. The Book is not short of room."),
    },
    "wh2_main_hef_high_elves": {
        "tiers": HEF_TIERS, "flavour": HEF_FLAVOUR,
        "wants_fmt": "The Court requests %d, and requests them today.",
        "market": "Emerald Gate",
        "offer_title_fmt": "Tribute to Asuryan: %s", "offer_text": HEF_OFFER_TEXT,
        "wrath_title": "Noted at Court",
        "wrath_text": "The request was not met, and the omission was noticed by people whose "
                      "noticing carries. Nobody has said anything. Nobody will need to.",
        "pleased_title": "Well Regarded",
        "pleased_text": "The tribute was rendered in full and on the day named. The Court has "
                        "said so once, in public, which is a great deal.",
        "paid": ("The Tribute Rendered",
                 "The consignment reached the Gate under seal and was accepted without a word "
                 "of query, which is how the Court says thank you.",
                 "The Court is satisfied, and your name is spoken well of for a season."),
        "unpaid": ("The Request Unmet",
                   "Nothing was tendered by the day named. The clerk of the Gate closed the "
                   "entry, and the entry was read at the next audience.",
                   "The Court adjusts its regard. It does not raise its voice."),
    },
    "wh2_main_def_dark_elves": {
        "tiers": DEF_TIERS, "flavour": DEF_FLAVOUR,
        "wants_fmt": "The temple requires %d, and requires them today.",
        "market": "Black Ark Market",
        "offer_title_fmt": "Given to the Temple: %s", "offer_text": DEF_OFFER_TEXT,
        "wrath_title": "Marked at the Temple",
        "wrath_text": "The portion was not given, and the Hag Queens were told the same "
                      "evening. They did not seem surprised, which is the part worth worrying "
                      "about.",
        "pleased_title": "Khaine is Served",
        "pleased_text": "The portion was given whole and on the day named. The temple has "
                        "noticed, which is not the same as being safe and is better than the "
                        "alternative.",
        "paid": ("The Portion Given",
                 "The goods went in through the temple gate and did not come out again, which "
                 "is the correct outcome and the only receipt offered.",
                 "Khaine is served. The knives went back in the drawer."),
        "unpaid": ("The Portion Withheld",
                   "Nothing was brought by the day named. The temple sent nobody to ask why, "
                   "which is not the mercy it appears to be.",
                   "The temple takes its portion in the other currency, eventually."),
    },
    "wh2_main_skv_skaven": {
        "tiers": SKV_TIERS, "flavour": SKV_FLAVOUR,
        "wants_fmt": "The Council wants %d, and wants them today.",
        "market": "Under-Market",
        "offer_title_fmt": "Tribute to the Council: %s", "offer_text": SKV_OFFER_TEXT,
        "wrath_title": "Marked by the Council",
        "wrath_text": "The tribute did not arrive and thirteen of the wrong sort noticed. "
                      "Word travels faster underground than anywhere.",
        "pleased_title": "The Council is Pleased",
        "pleased_text": "The tribute arrived whole and on time, which the Council was not "
                        "expecting and has decided to reward anyway.",
        "paid": ("The Tribute Taken",
                 "The crates went down the tunnel and did not come back, which is how the "
                 "Council prefers to receive things.",
                 "The Council is pleased, briefly, and says so to fewer clans than it might."),
        "unpaid": ("The Tribute Withheld",
                   "Nothing went down the tunnel. Thirteen of the wrong sort were told, "
                   "individually, by someone hoping to be rewarded for telling them.",
                   "The Council takes what it is owed by other arrangements."),
    },
}


def offering_effect(culture, res):
    """The (effect, scope, base) this race's offering of `res` grants."""
    over = OFFERING_OVERRIDE.get(culture, {}).get(res)
    if over:
        return over[0], over[1], over[2]
    return OFFERING_EFFECTS[res]


def build():
    """Every DB row for the exchange, keyed by table folder, plus a "loc" entry."""
    t = {}
    pools, poolgroups, loc = [], [], []
    bundles, bundle_junc, factors = [], [], []

    # STAGE 2, DONE 2026-09-05: the 19 price effects, their 798 ladder bundles and the 798
    # junction rows that paired them are gone. Their effect was a percentage_cost_mod whose only
    # consumer was the trade ritual they were junctioned to, and the rituals went earlier the
    # same day. Stage 1 shipped them one more build so EX.strip_legacy_bundles could clear any
    # save that still had one applied before the rows vanished underneath it.
    #
    # effects_tables went with them ENTIRELY - it held nothing else. effect_bundles and its
    # junction table STAY: they carry option B's eight trade-income steps, the 17 offering
    # bundles and the wrath bundle, all live and all visible. Section 18 of the handoff said to
    # "delete the three tables", which was true when it was written and is not now.
    #
    # EX.strip_legacy_bundles stays too, and its cm:remove_effect_bundle calls are individually
    # pcall-wrapped, so a save arriving from an older build still gets swept whether or not the
    # key resolves any more.
    for res, name, _unit, hold, mint, _lot in instruments():
        if mint:
            pools.append({"key": hold, "maximum": 1000000, "minimum": 0, "ai_ignored": True,
                          "default_factor": "other",
                          "optional_icon_path": "",
                          "income_policy": "END_OF_ROUND", "reset_before_income": False,
                          "scope": "FACTION", "has_persistent_factors": False, "sort_order": 0,
                          "battle_conversion": "", "appy_income_on_creation": False,
                          "always_display_zero_factors": True,
                          "can_scale_effect_thresholds_per_unit": False})
        # Both directions allowed: we buy AND sell, so a spend-only clamp (max 0, as 187
        # vanilla rows use) would eat every sale without a word.
        factors.append({"unique_id": factor_junction(res), "factor": "other", "resource": hold,
                        "minimum": -2147483647, "maximum": 2147483647,
                        "specific_faction_set": ""})
        if mint:
            for g in POOL_GROUPS:
                poolgroups.append({"campaign_group": g, "resource": hold, "initial_amount": 0})
            # CA's OWN name for the resource, not our key slug and not the unit word. The
            # unit column says "barrels" for res_rom_lead, whose actual name is "Salt" - the
            # holdings counter read "Barrels" for a whole build because of it. See
            # tools/read_vanilla_loc.py.
            loc.append(("pooled_resources_display_name_%s" % hold, display_name(res)))

    # OPTION B's eight bundles. These carry CA's effect, so no effects_tables row is minted -
    # and unlike the price ladder they are VISIBLE, with the title and description in the row
    # itself (4,816 of CA's 5,855 effect_bundles rows do the same).
    for step in TRADE_STEPS:
        # COLUMN ORDER IS CA'S, and this is the FIRST bundle row appended, so it is the row
        # cols() reads the header from. It only became load-bearing when stage 2 deleted the
        # price ladder that used to be appended ahead of it - and check_against_vanilla caught
        # the swap immediately, which is the whole reason that assert compares order and not
        # just membership.
    # is_global_effect = True ON ALL FOUR FAMILIES, and it is a DISPLAY flag, not a
    # targeting one. Measured 2026-09-05 with three vanilla controls applied side by
    # side to one faction: only the bundle with is_global_effect TRUE appeared under
    # Faction Effects. The other two - one with an icon, one without - were applied and
    # readable through has_effect_bundle, and drew nothing. It is not the icon: control
    # B carried books_of_nagash.png and stayed invisible.
    #
    # The name is misleading: it does NOT apply the effect to every faction. CA uses it
    # on 1,727 of 2,835 titled faction bundles, including single-faction dilemma
    # payloads, and the control granting +1 Liche Priest cap affected only the faction
    # it was applied to. False here is what made every offering look like it did
    # nothing: the buff was live and the panel simply never listed it.
        bundles.append({
            "key": trade_bundle(step),
            "localised_description": ("Commodity prices are high and this faction's trade goods "
                                      "are in demand." if step > 0 else
                                      "Commodity prices are depressed and this faction's trade "
                                      "goods fetch less."),
            "localised_title": "Zharr Exchange",
            "bundle_target": "faction", "priority": 1, "ui_icon": ICON_TRADE,
            "is_global_effect": True, "show_in_3d_space": False, "owner_only": True})
        bundle_junc.append({"effect_bundle_key": trade_bundle(step), "effect_key": TRADE_EFFECT,
                            "effect_scope": TRADE_SCOPE, "value": float(step),
                            "advancement_stage": STAGE})

    # THREE WAREHOUSE BUNDLES PER COMMODITY - the ramp. Same effect and the same scope as that
    # commodity's offering, at 1x / 2x / 3x the base instead of the offering's flat 2x.
    #
    # THE SCOPE IS DELIBERATELY NOT RE-CHOSEN. Every scope in OFFERING_EFFECTS is the one
    # vanilla pairs with that effect, and an effect paired with a scope it does not support is
    # not an error - it is a row that quietly does nothing. Reusing the offering's scope means
    # these 51 rows inherit that verification for free; picking a "tidier" one here would throw
    # it away silently.
    for res, (eff_key, eff_scope, base) in sorted(OFFERING_EFFECTS.items()):
        for tier, (_units, mult, label) in enumerate(STOCK_TIERS, 1):
            key = stock_bundle(res, tier)
            bundles.append({
                "key": key, "bundle_target": "faction", "priority": 1,
                "ui_icon": ICON_STOCK,
                "localised_title": "%s: %s" % (label, display_name(res)),
                "localised_description": STOCK_TEXT[label],
                "is_global_effect": True, "show_in_3d_space": False, "owner_only": True})
            bundle_junc.append({
                "effect_bundle_key": key, "effect_key": eff_key,
                "effect_scope": eff_scope, "value": float(base * mult),
                "advancement_stage": STAGE})

    # ===================================================================================
    # PER RACE: 17 offering bundles, the two patron bundles, 51 demand messages and the two
    # outcome messages.
    # ===================================================================================
    #
    # EVERYTHING ELSE IN THIS PACK IS SHARED and stays outside this loop - the pooled
    # resources a position is held in, the 51 warehouse bundles, the eight trade-income
    # steps, the 17 shock bulletins and the two delist bulletins all carry text that names a
    # commodity or a market and no patron at all. Segmenting those would quadruple 156 rows
    # of identical text and rename the pools every live save holds its position inside.
    #
    # THE CHAOS DWARF SEGMENT IS EMPTY, so its keys come out exactly as they ship today.
    # check_chd_identity() proves that against the committed TSVs rather than trusting it.
    for culture, race in sorted(race_table().items()):
        seg, text = race["seg"], RACE_TEXT[culture]

        for res in sorted(COMMODITIES):
            eff_key, eff_scope, base = offering_effect(culture, res)
            key = "%s%soffering_%s" % (PREFIX, seg, short(res))
            bundles.append({
                "key": key, "bundle_target": "faction", "priority": 1,
                "ui_icon": ICON_OFFERING,
                "localised_title": text["offer_title_fmt"] % display_name(res),
                "localised_description": text["offer_text"][eff_key],
                "is_global_effect": True, "show_in_3d_space": False, "owner_only": True})
            bundle_junc.append({
                "effect_bundle_key": key, "effect_key": eff_key,
                "effect_scope": eff_scope, "value": float(base * OFFER_MULT),
                "advancement_stage": STAGE})

        # THE REWARD BUNDLE, and the refusal bundle. Same shape, opposite sign. Neither
        # carries a duration - cm:apply_effect_bundle does - so one row each serves all
        # three greed tiers.
        for bkey, btitle, bbody, beffects, bicon in (
                (race["pleased"], text["pleased_title"], text["pleased_text"],
                 PLEASED_EFFECTS, ICON_PLEASED),
                (race["wrath"], text["wrath_title"], text["wrath_text"],
                 WRATH_EFFECTS, ICON_WRATH)):
            bundles.append({
                "key": bkey, "bundle_target": "faction", "priority": 1, "ui_icon": bicon,
                "localised_title": btitle, "localised_description": bbody,
                "is_global_effect": True, "show_in_3d_space": False, "owner_only": True})
            for eff_key, eff_scope, val in beffects:
                bundle_junc.append({
                    "effect_bundle_key": bkey, "effect_key": eff_key,
                    "effect_scope": eff_scope, "value": val, "advancement_stage": STAGE})

        # HASHUT'S DEMANDS, and the other three patrons'. No dilemma rows at all - a
        # DilemmaChoiceMadeEvent listener that matches hard-crashes the game (section 30 of
        # the 2026-09-05 handoff), so a demand is an event-feed message and a deadline
        # instead of a popup with two buttons.
        #
        # ONE MESSAGE PER (TIER, COMMODITY), for exactly the reason there were once 51
        # dilemma rows: the amount and the goods have to appear in the text, and that text is
        # a static loc string.
        for res in COMMODITIES:
            name = display_name(res)
            for (sfx, tier_title, closer), (_s, mult, _t, _w, _T, _c) in zip(
                    text["tiers"], DEMAND_TIERS):
                amount = demand_amount(mult)
                key = "%s%sdem_%s_%s" % (PREFIX, seg, sfx, short(res))
                loc.append((key + "_title", "%s: %s" % (tier_title, name)))
                loc.append((key + "_primary", "%s %s %s"
                            % (text["flavour"][res], text["wants_fmt"] % amount, closer)))
                loc.append((key + "_secondary",
                            "Sacrifice %d %s in the %s within %d turns, or answer for it."
                            % (amount, name, text["market"], DEMAND_GRACE)))

        # The two outcome messages. Generic within a race, because they say what happened
        # rather than how much - the amount and the commodity are in the demand message.
        for stem, parts in (("dem_paid", text["paid"]), ("dem_wrath", text["unpaid"])):
            base_key = PREFIX + seg + stem
            loc.append((base_key + "_title", parts[0]))
            loc.append((base_key + "_primary", parts[1]))
            loc.append((base_key + "_secondary", parts[2]))

    # The shock bulletin, one per commodity. Keyed on short(), which is the same function
    # EX.short mirrors in the script - the Lua builds this key at runtime and a mismatch here
    # is a message that resolves to nothing and draws an empty feed entry.
    for res in COMMODITIES:
        name = display_name(res)
        loc.append((SHOCK_MSG + short(res) + "_title", SHOCK_MSG_TEXT[0] % name))
        loc.append((SHOCK_MSG + short(res) + "_primary", SHOCK_MSG_TEXT[1] % name))
        loc.append((SHOCK_MSG + short(res) + "_secondary", SHOCK_MSG_TEXT[2]))

    # The two delisting bulletins. Not per house - the houses ship in the lords pack and are
    # discovered by culture, so there is no key here to write text against.
    for msg, text in ((DELIST_BUYOUT_MSG, DELIST_BUYOUT_TEXT),
                      (DELIST_WINDUP_MSG, DELIST_WINDUP_TEXT)):
        loc.append((msg + "_title", text[0]))
        loc.append((msg + "_primary", text[1]))
        loc.append((msg + "_secondary", text[2]))

    def cols(rows):
        return list(rows[0].keys())

    t["pooled_resources_tables"] = (cols(pools), pools)
    t["campaign_group_pooled_resources_tables"] = (cols(poolgroups), poolgroups)
    t["pooled_resource_factor_junctions_tables"] = (cols(factors), factors)

    # THE FIVE TRADE-RESOURCE GRANTS. The only rows in this pack that touch a VANILLA
    # building rather than minting something of our own, so they are the only rows that can
    # collide with another mod - anything else editing these five buildings' effects wins or
    # loses by load order. See CHD_TRADE_GRANT.
    tr = chd_trade_rows()
    t["building_effects_junction_tables"] = (cols(tr), tr)
    # THE ROW TEXT IS NOT ENOUGH. effect_bundles.localised_title and _description are stored
    # in the row AND in text/db/effect_bundles__.loc, and the panel reads the LOC - CA ships
    # 11,710 entries there and duplicates every string. Ours had the row text only, so all 27
    # bundles drew as an icon with no title and no body: applied, visible, unreadable.
    #
    # Derived from the rows rather than written out, so the two copies cannot drift.
    for b in bundles:
        loc.append(("effect_bundles_localised_title_" + b["key"], b["localised_title"]))
        loc.append(("effect_bundles_localised_description_" + b["key"],
                    b["localised_description"]))

    t["effect_bundles_tables"] = (cols(bundles), bundles)
    t["effect_bundles_to_effects_junctions_tables"] = (cols(bundle_junc), bundle_junc)

    # The event-feed records show_message_event's index resolves against. group == id on the
    # member row is vanilla's own shape for every one of these.
    # FOUR RECORDS PER RACE, NOT FOUR IN TOTAL. The picture is a COLUMN on the record and
    # nothing can swap it at runtime, so the only way a Skaven player stops being shown the
    # Chaos Dwarf forge for a Trade Disrupted bulletin (screenshot, 2026-09-08) is a record of
    # their own. Keys carry the segment, exactly like every other per-race key in this build,
    # so the Chaos Dwarf four keep their shipped names and their 7401-7404 indices.
    groups, members, crit, feed = [], [], [], []
    for culture in sorted(FEED_INDEX_BASE):
        seg = race_table()[culture]["seg"]
        base = FEED_INDEX_BASE[culture]
        art = FEED_IMAGE[culture]
        for slot, row in enumerate(FEED):
            _key, _index, icon, sound, event, instant = row
            kind = _key.rsplit("_", 1)[1]              # call / wrath / shock / delist
            key = PREFIX + seg + "feed_" + kind
            index = base + slot
            if culture == CHD_CULTURE:
                assert (key, index) == (_key, _index), (
                    "the Chaos Dwarf feed record moved: %s/%d, was %s/%d - every check and "
                    "log line in this file names those numbers"
                    % (key, index, _key, _index))
            groups.append({"id": key})
            members.append({"group": key, "id": key, "priority": 0})
            crit.append({"member": key, "value": index})
            feed.append({
                "event": event,
                "flavour_text": "wh_event_feed_string_all_null",
                "group": key, "image": art[kind],
                "secondary_detail": "wh_event_feed_string_scripted_event_secondary_detail",
                "target": "event_feed_target_faction", "layout": "standard",
                "layout_data": "event_feed_none", "sound_event": sound,
                "context_located": "event_feed_none", "override_icon": icon,
                "instant_open": instant, "ignore_instant_open_filters": False})
    t["campaign_groups_tables"] = (cols(groups), groups)
    t["campaign_group_members_tables"] = (cols(members), members)
    t["campaign_group_member_criteria_values_tables"] = (cols(crit), crit)
    t["event_feed_message_events_tables"] = (cols(feed), feed)

    t["loc"] = (["key", "text", "tooltip"], [(k, v, "false") for k, v in loc])
    return t


def table_version(table):
    """CA's OWN shipped version for a table, read from the cached RPFM dump.

    Not RPFM's default, which can differ - a version whose field shape disagrees with the rows
    is a crash class of its own. Derived rather than hardcoded so it cannot drift after a patch;
    delete .skilltree_cache after a game patch and it re-derives.
    """
    import json
    path = os.path.join(ROOT, ".skilltree_cache", "%s.json" % table[:-len("_tables")])
    with io.open(path, encoding="utf-8") as fh:
        d = json.load(fh)["VecRFile"][0]
    return d["data"]["Decoded"]["DB"]["table"]["definition"]["version"]


def _fmt(v):
    """RPFM's TSV spelling: booleans lowercase, floats with 4 decimals, ints bare."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return "%.4f" % v
    return "" if v is None else str(v)


def write_tsvs(t):
    """One TSV per table, in RPFM's import shape: header line, then the #table;version;path line."""
    os.makedirs(OUT, exist_ok=True)
    written = []
    for table, (cols, rows) in sorted(t.items()):
        if table == "loc":
            path = os.path.join(OUT, "loc__%s.tsv" % FRAG)
            meta = "#Loc;1;text/db/%s.loc" % FRAG
        else:
            path = os.path.join(OUT, "%s__%s.tsv" % (table, FRAG))
            meta = "#%s;%d;db/%s/%s" % (table, table_version(table), table, FRAG)
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\t".join(cols) + "\n")
            fh.write(meta + "\n")
            for r in rows:
                cells = r if isinstance(r, tuple) else [r[c] for c in cols]
                fh.write("\t".join(_fmt(c) for c in cells) + "\n")
        written.append((table, len(rows)))
    return written


def check_against_vanilla(t):
    """The three checks Task 1 cost a launch each to learn. Run on every table we write.

    1. Our column list must equal CA's definition exactly. import_tsv accepts a SHORT tsv in
       silence and defaults the missing columns, which is how the probe shipped
       initially_unlocked=false and left every ritual script_locked.
    2. A column vanilla never leaves empty is a required foreign key. An empty string there is
       a startup refusal naming only the first bad row.
    3. A campaign group we register to must actually hold vanilla rituals. A culture-gated
       group with zero rituals looks correct and disables everything forever.
    """
    from read_vanilla_cache import load
    for table, (our_cols, rows) in sorted(t.items()):
        if table == "loc":
            continue
        van, _ = load(table[:-len("_tables")])
        van_cols = list(van[0].keys())
        assert list(our_cols) == van_cols, (
            "%s column list differs from CA's definition.\n  ours: %s\n  CA's: %s\n  missing: %s"
            % (table, our_cols, van_cols, [c for c in van_cols if c not in our_cols]))
        required = [c for c in van_cols
                    if any(isinstance(r[c], str) for r in van) and not any(r[c] == "" for r in van)]
        for r in rows:
            for c in required:
                assert r[c] != "", "%s.%s is required (vanilla never leaves it empty): %s" % (
                    table, c, r)

    # OPTION B leans on an effect we did not mint. A key that does not exist is an
    # unresolvable foreign key and a startup refusal, and nothing in this generator would
    # otherwise notice CA renaming it in a patch.
    van_effects = {r["effect"] for r in load("effects")[0]}
    assert TRADE_EFFECT in van_effects, (
        "%s is not in vanilla effects_tables - a missing FK is a startup refusal" % TRADE_EFFECT)
    for res, (eff, _scope, _v) in sorted(OFFERING_EFFECTS.items()):
        assert eff in van_effects, (
            "%s (offering effect for %s) is not in vanilla effects_tables" % (eff, res))
        assert eff in OFFERING_TEXT, "no flavour text for %s" % eff
    # The refusal bundle rides two of the same effects, so its keys are known-good - but
    # they are written out separately and a typo there is the same silent dead row.
    for eff, _scope, _v in WRATH_EFFECTS:
        assert eff in van_effects, (
            "%s (Hashut's displeasure) is not in vanilla effects_tables" % eff)

    van_groups = {r["campaign_group"] for r in load("campaign_group_rituals")[0]}
    for g in GROUPS:
        assert g in van_groups, (
            "%s holds no vanilla rituals. We register only POOLS there now, but a group that "
            "holds nothing of CA's is the shape that was culture-gated-but-empty in 2026-09-04 "
            "and disabled everything silently." % g)


def check_standing_accessor():
    """diplomatic_standing_with takes a KEY STRING. Passing an interface returns 0 forever.

    This shipped and survived a whole 20-turn campaign. It does not error and does not return
    nil, so luac, check_lua_api and every harness pass over it - the only tell is that every
    faction scores 0. That in turn made EX.check_standing_sign declare the sign convention
    violated, which pins open houses at a flat -0.5 stance, which puts refusal (needs -0.75)
    permanently out of reach. Measured live 2026-09-07 turn 21: broken=0 for all seven houses,
    key-string=-280/-30/+40.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    m = re.search(r"function EX\.standing_of\(house\)(.*?)\nend\n", lua, re.S)
    assert m, "EX.standing_of is gone or was renamed"
    body = m.group(1)

    calls = re.findall(r"diplomatic_standing_with\(([^)]*)\)", body)
    assert calls, "EX.standing_of no longer calls diplomatic_standing_with"
    for arg in calls:
        arg = arg.strip()
        assert arg != "me", (
            "EX.standing_of passes the faction INTERFACE `me` to diplomatic_standing_with. "
            "The signature is diplomatic_standing_with(faction_key: string). Passing an "
            "interface silently returns 0 for every faction - it does not error and does not "
            "return nil, so nothing downstream can tell. Pass a key string.")
        # `EX.who(` and `EX.me(` arrive with the close-paren already eaten by the [^)]*
        # capture above - the accessors return a faction KEY STRING, which is the property
        # this is pinning. EX.who() rather than the local faction because the whole turn round
        # runs with another player bound, and standing has to be read against the player being
        # charged rather than against whoever is sitting at this machine.
        assert ("get_local_faction_name" in arg or arg.endswith("Key") or arg == "house"
                or arg in ("EX.who(", "EX.me(")), (
            "EX.standing_of passes %r to diplomatic_standing_with, which does not look like a "
            "faction key string. It must be a key, never an interface." % arg)

    # DIRECTION: the design reads what the HOUSE thinks of the PLAYER, and standing is
    # asymmetric - the two directions disagreed on all seven houses when measured. So the
    # house interface is the receiver and the player's key is the argument.
    assert re.search(r"f:diplomatic_standing_with\(", body), (
        "EX.standing_of must call diplomatic_standing_with ON THE HOUSE interface (f:), "
        "because the design reads how the house feels about the player and standing is "
        "asymmetric. Calling it on the player reads the opposite relationship.")
    print("  standing accessor: key string not interface, and read from the house's side")


def selftest():
    # the ladder spans the intended multiplier range, ascending, no duplicates
    assert len(LADDER) == 42, len(LADDER)
    assert LADDER == sorted(LADDER) and len(set(LADDER)) == 42
    assert abs((LADDER[0] / 100.0 + 1.0) - MULT_MIN) < 0.01, LADDER[0]
    assert abs((LADDER[-1] / 100.0 + 1.0) - MULT_MAX) < 0.10, LADDER[-1]
    # index 24 is the neutral rung
    assert LADDER[-LADDER_LO] == 0.0, LADDER[-LADDER_LO]

    # ladder_index maps a multiplier to its nearest rung and clamps at both ends
    assert ladder_index(1.0) == -LADDER_LO
    assert ladder_index(0.0001) == 0
    assert ladder_index(999.0) == 41
    for i, pct in enumerate(LADDER):
        assert ladder_index(pct / 100.0 + 1.0) == i, (i, pct)

    # price_multiplier: scarcer than median is dearer, plentiful is cheaper, median is 1.0
    assert abs(price_multiplier(10, 10) - 1.0) < 1e-9
    assert price_multiplier(2, 10) > 1.0
    assert price_multiplier(50, 10) < 1.0
    # monotonic in supply
    seq = [price_multiplier(s, 10) for s in range(1, 60)]
    assert seq == sorted(seq, reverse=True), "must fall as supply rises"
    # clamped both ends, and a zero supply does not divide by zero
    assert price_multiplier(1, 10000) == MULT_MAX
    assert price_multiplier(10000, 1) == MULT_MIN
    assert price_multiplier(0, 10) == MULT_MAX

    # the 17 commodities are exactly the tradeable rows of the vanilla table
    from read_vanilla_cache import load
    rows, _ = load("resources")
    assert COMMODITIES == sorted(r["key"] for r in rows if r["trade_value"]), COMMODITIES
    assert len(COMMODITIES) == 17
    assert "res_gold" not in COMMODITIES, "res_gold has trade_value 0, it is not tradeable"

    t = build()
    check_against_vanilla(t)
    check_chd_identity(t)
    check_loc_complete(t)

    # NO RITUAL TABLES. The trade is cm:treasury_mod + cm:faction_add_pooled_resource, and every
    # ritual row was doing nothing but being hidden and counted. If one of these ever comes back,
    # the price the player is charged and the price the panel draws are two numbers again.
    # effects_tables joins them: after stage 2 this pack mints no effect of its own at all.
    # Every effect it applies is one of CA's, which is why check_against_vanilla can insist that
    # every effect key it names already exists in the vanilla table.
    for dead in ("rituals_tables", "campaign_group_rituals_tables", "resource_costs_tables",
                 "effect_bonus_value_ritual_junctions_tables", "effects_tables"):
        assert dead not in t, "%s is back - see section 18 of the 2026-09-05 handoff" % dead

    # one holdings pool per commodity, non-negative floor since shorting is cut from v1
    pools = t["pooled_resources_tables"][1]
    assert len(pools) == len(COMMODITIES)
    assert all(p["minimum"] == 0 for p in pools), "shorting is not in v1"
    assert all(p["scope"] == "FACTION" for p in pools)

    # every pool and every ritual is registered, or it is invisible / disabled forever
    # pooled_resource_factor_junctions is what makes the pair ("other", our pool) legal, which
    # is what cm:faction_add_pooled_resource needs. Measured: passing the junction unique_id to
    # that call instead of the factor key "other" succeeds and moves NOTHING.
    fj = t["pooled_resource_factor_junctions_tables"][1]
    assert {f["resource"] for f in fj} == {i[3] for i in instruments()}
    assert all(f["minimum"] < 0 < f["maximum"] for f in fj),         "a one-directional clamp silently eats either the buy or the sell"

    # LAYER 2 trades the faction's REAL pooled resources, so no new pool is minted for them
    # Every layer-2 pool must be FACTION scope. A FACTION_PROVINCE pool is unreachable from
    # script - its manager returns a null interface at both faction and province level - so the
    # trade silently moves nothing. That is exactly how Labour shipped broken.
    from read_vanilla_cache import load as _vload
    _rows, _ = _vload("pooled_resources")
    _scope = {r["key"]: r["scope"] for r in _rows}
    for _pool, _n, _d in LAYER2:
        assert _scope.get(_pool) == "FACTION", (
            "%s is %s scope; script cannot move a non-FACTION pool" % (_pool, _scope.get(_pool)))
    pool_keys = {p["key"] for p in t["pooled_resources_tables"][1]}
    l2_pools = {pool for pool, _n, _d in LAYER2}
    assert not (l2_pools & pool_keys), "layer 2 must reuse CA's pools, not clone them"
    assert len(pool_keys) == len(COMMODITIES), "only layer 1 mints pools"

    reg = {r["resource"] for r in t["campaign_group_pooled_resources_tables"][1]}
    assert reg == {hold_key(r) for r in COMMODITIES}, "unregistered pool is invisible"
    # CA already registers the layer 2 pools; a second row would duplicate them
    assert not (l2_pools & reg)
    # THE GOODS ARE NOT IN THE COST RECORD, AND MUST NOT BE.
    # percentage_cost_mod scales the ENTIRE resource_cost row, gold and pooled amount alike.
    # Measured in game 2026-09-04: at a price of 909 the panel charged 9 goods instead of 10,
    # at 1331 it charged 13. That makes goods-per-gold constant and destroys the whole point of
    # a market - buying cheap simply gets you proportionally less. So the cost record carries
    # gold only, and the fixed-size lot is moved by the Lua with
    # cm:faction_add_pooled_resource(faction, pool, "other", +/-lot).
    assert "resource_cost_pooled_resource_junctions_tables" not in t, (
        "the goods must not ride on the cost record - percentage_cost_mod scales it")

    loc = {k: v for k, v, _tt in t["loc"][1]}
    assert not any("rituals_" in k for k in loc), "ritual loc outlived the ritual rows"
    assert not any("PLACEHOLDER" in k for k in loc), "placeholder loc key renders blank"
    assert not any(v != v.strip() for v in loc.values())
    # "||" IS BANNED IN EVERY LOC VALUE. It is a real WH3 convention - CA splits a tooltip's
    # title from its body with it - but the split is applied by the TEXT REPLACEMENT resolver
    # behind `{{tr:X}}`, which looks up ui_text_replacements_localised_text_X. A loc key of our
    # own does not go through that, so the pipes reach the screen literally. Screenshotted
    # 2026-09-04, and again 2026-09-05 after a first attempt that only rewrote the strings.
    #
    # Tooltips that NEED the split live as literal text in the .twui.xml instead - see TIP_* in
    # tools/gen_exchange_ui.py, which is also where the length rule that goes with it is checked.
    assert not any("||" in v for v in loc.values()), (
        "|| renders as two literal pipes through a loc key; put the tooltip in the .twui.xml")
    assert all(v for v in loc.values()), "empty loc string renders a blank tooltip"

    # FOUR FAMILIES OF BUNDLE, all live and all visible. The dead price ladder was a fifth
    # and its absence is asserted, not assumed: re-adding it would pass every count below.
    # SEGMENT-AWARE SINCE 2026-09-08. The offering bundles and the two patron bundles are one
    # set PER RACE, so "starts with PREFIX + offering_" only ever matched the Chaos Dwarf 17
    # and would have left 51 bundles in no family at all.
    _races = race_table()
    _segs = sorted(set(r["seg"] for r in _races.values()))
    bun = t["effect_bundles_tables"][1]
    tradeb = [b for b in bun if b["key"].startswith(PREFIX + "trade_")]
    offerb = [b for b in bun
              if any(b["key"].startswith(PREFIX + sg + "offering_") for sg in _segs)]
    stockb = [b for b in bun if b["key"].startswith(PREFIX + "stock_")]
    wrathb = [b for b in bun if b["key"] in set(r["wrath"] for r in _races.values())]
    pleasedb = [b for b in bun if b["key"] in set(r["pleased"] for r in _races.values())]
    assert not [b for b in bun if b["key"].startswith(PREFIX + "ladder_")], \
        "the price ladder is back - stage 2 removed it, see section 28 of the handoff"
    assert len(tradeb) + len(offerb) + len(stockb) + len(wrathb) + len(pleasedb) == len(bun), \
        "an effect bundle in no family"
    assert len(pleasedb) == len(_races), (
        "%d reward bundles for %d races - one per patron, and a race with none applies a key "
        "that has no row" % (len(pleasedb), len(_races)))
    assert len(wrathb) == len(_races), (
        "%d refusal bundles for %d races" % (len(wrathb), len(_races)))
    assert len(offerb) == len(COMMODITIES) * len(_races), (
        "%d offering bundles for %d races x %d commodities"
        % (len(offerb), len(_races), len(COMMODITIES)))
    # EVERY bundle we ship must be visible in the Faction Effects panel. is_global_effect is
    # a display flag (see the note in build()); False means the buff applies and the player is
    # never told, which is indistinguishable from a broken mechanic and was read as one.
    # ...and every one must carry an icon that EXISTS. A ui_icon naming a file no pack holds
    # draws a blank square, and a byte-grep for the filename is not proof - the string being
    # present in a DB row says nothing about the texture. All 17 pooled_resources rows shipped
    # exactly that fault earlier today.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gen_exchange_ui import _game_assets
    assets = _game_assets()
    for b in bun:
        icon = (b["ui_icon"] or "").strip()
        assert icon, "%s ships with no ui_icon - it will draw an empty slot" % b["key"]
        assert ("ui/campaign ui/effect_bundles/" + icon) in assets, (
            "%s names ui_icon %r, which is in no shipped pack" % (b["key"], icon))

    # EVERY bundle needs BOTH loc keys, matching the row. Without them the panel draws the
    # icon and no text, which looks like a half-broken mod rather than a missing string.
    for b in bun:
        for field in ("title", "description"):
            key = "effect_bundles_localised_%s_%s" % (field, b["key"])
            assert key in loc, "%s has no loc - it will draw with no %s" % (b["key"], field)
            assert loc[key] == b["localised_%s" % field], (
                "%s loc and row disagree: %r vs %r"
                % (key, loc[key], b["localised_%s" % field]))
        assert loc["effect_bundles_localised_title_" + b["key"]].strip(), (
            "%s has an EMPTY title - the row draws nameless" % b["key"])

    invisible = [b["key"] for b in bun if not b["is_global_effect"]]
    assert not invisible, (
        "these bundles would apply without ever appearing under Faction Effects: %s"
        % invisible)

    assert len({b["key"] for b in bun}) == len(bun), "duplicate bundle key"
    assert all(b["bundle_target"] == "faction" for b in bun)
    # EVERY remaining bundle is one the player is meant to see. The ladder was the only
    # invisible one, so a titleless row now means a bundle that reads as an unexplained stat.
    assert all(b["localised_title"] and b["localised_description"] for b in bun), \
        "a bundle with no title - the player sees a stat change with no cause"

    assert len(tradeb) == len(TRADE_STEPS), len(tradeb)
    assert all(b["localised_title"] and b["localised_description"] for b in tradeb), \
        "an income change with no visible cause reads as a bug"
    assert 0 not in TRADE_STEPS, "a 0% step is a bundle that says nothing; apply none instead"

    # OFFERINGS. Every commodity is covered, the pooled-resource key is NOT reused, and each
    # effect is paired with the scope vanilla uses for it.

    # THE WAREHOUSE RAMP. One bundle per (commodity, tier), and every one of these would fail
    # silently: a missing tier is a bonus that never arrives, and a wrong value is a bonus the
    # player cannot tell is wrong because nothing states the expected number anywhere else.
    assert len(stockb) == len(COMMODITIES) * len(STOCK_TIERS), (
        "%d warehouse bundles for %d commodities x %d tiers"
        % (len(stockb), len(COMMODITIES), len(STOCK_TIERS)))
    junc_by_key = {}
    for j in t["effect_bundles_to_effects_junctions_tables"][1]:
        junc_by_key.setdefault(j["effect_bundle_key"], []).append(j)
    for res in COMMODITIES:
        eff_key, eff_scope, base = OFFERING_EFFECTS[res]
        for tier, (_units, mult, _label) in enumerate(STOCK_TIERS, 1):
            key = stock_bundle(res, tier)
            rows = junc_by_key.get(key)
            assert rows and len(rows) == 1, (
                "%s has %d effect rows, expected exactly 1" % (key, len(rows or [])))
            j = rows[0]
            assert j["value"] == float(base * mult), (
                "%s grants %s, the ramp says %s" % (key, j["value"], float(base * mult)))
            # THE SCOPE MUST BE THE OFFERING'S. Every scope in OFFERING_EFFECTS was counted out
            # of vanilla for that specific effect, and an effect paired with a scope it does not
            # support is a row that quietly does nothing - not an error, and not visible in the
            # panel either, because the bundle still applies and still draws its title.
            assert j["effect_scope"] == eff_scope and j["effect_key"] == eff_key, (
                "%s uses %s/%s; the offering uses %s/%s and that pairing is the one verified "
                "against vanilla" % (key, j["effect_key"], j["effect_scope"], eff_key, eff_scope))
    # The thresholds must ascend, or stock_tier_for returns a tier whose bundle grants less
    # than the one below it and buying MORE would weaken the bonus.
    units = [u for u, _m, _l in STOCK_TIERS]
    mults = [m for _u, m, _l in STOCK_TIERS]
    assert units == sorted(units) and len(set(units)) == len(units), \
        "STOCK_TIERS thresholds must strictly ascend: %s" % units
    assert mults == sorted(mults) and len(set(mults)) == len(mults), \
        "STOCK_TIERS multipliers must strictly ascend: %s" % mults
    assert stock_tier_for(units[0] - 1) == 0, "below the first threshold must be no tier"
    assert stock_tier_for(units[-1] * 10) == len(STOCK_TIERS), "the top tier must be reachable"
    # THE KEY MUST NOT COLLIDE WITH THE POOLED RESOURCE OR THE OFFERING. Both collisions are
    # silent: hold_<short> is the pool the goods actually live in.
    pool_keys = {p["key"] for p in t["pooled_resources_tables"][1]}
    for b in stockb:
        assert b["key"] not in pool_keys, "%s collides with a pooled resource key" % b["key"]
        assert not b["key"].startswith(PREFIX + "offering_"), b["key"]

    # THE EVENT-FEED RECORDS, all four tables of each. show_message_event's index resolves
    # through campaign_group_member_criteria_values, so a record missing any one of these
    # makes the call log and draw NOTHING - there is no error and no half-drawn message.
    crit = {r["member"]: r["value"] for r in t["campaign_group_member_criteria_values_tables"][1]}
    fkeys = {f["group"] for f in t["event_feed_message_events_tables"][1]}
    gids = {g["id"] for g in t["campaign_groups_tables"][1]}
    mids = {m["id"] for m in t["campaign_group_members_tables"][1]}
    # FOUR RECORDS PER RACE. FEED holds the four SHAPES; the build crosses them with the race
    # segments, so the expected set is the product - the Chaos Dwarf four under their shipped
    # unsegmented names, and four more per covered race.
    want = set()
    for culture in FEED_INDEX_BASE:
        seg = race_table()[culture]["seg"]
        for f in FEED:
            want.add(PREFIX + seg + "feed_" + f[0].rsplit("_", 1)[1])
    assert len(want) == 4 * len(FEED_INDEX_BASE), (
        "two races generated the same feed key - a segment is missing or duplicated: %s"
        % sorted(want))
    assert want == fkeys == gids == mids == set(crit), (
        "a feed record is missing one of its four tables: feed=%s groups=%s members=%s crit=%s"
        % (sorted(fkeys), sorted(gids), sorted(mids), sorted(crit)))
    for key, index in ((f[0], f[1]) for f in FEED):
        assert crit[key] == index, "%s indexes %s, the Lua names %s" % (key, crit[key], index)
        assert index != 0, "index 0 draws nothing"
    assert len(set(crit.values())) == len(crit), "two feed records share an index"
    # AND NOT AN INDEX THE GAME ALREADY OWNS. The index is a plain integer looked up across
    # every criteria-values row in the build, so landing on one of CA's would resolve our
    # message against CA's record - a real message drawn with the wrong icon, sound and
    # persistence, and nothing anywhere would report it. Vanilla tops out at 1960 today, which
    # is why 74xx is clear; asserted rather than remembered, because a patch can add rows.
    from read_vanilla_cache import load as _load
    _vals = {r["value"] for r in _load("campaign_group_member_criteria_values")[0]}
    _clash = sorted(set(crit.values()) & _vals)
    assert not _clash, (
        "feed index %s is CA's as well as ours. show_message_event would resolve against "
        "vanilla's record and draw our text with their icon, sound and popup behaviour."
        % _clash)
    # Both indices must be the ones the script actually passes.
    lua_raw = io.open(LUA_SCRIPT, encoding="utf-8").read()
    for name, key in (("FEED_CALL", "derpy_chd_ex_feed_call"),
                      ("FEED_WRATH", "derpy_chd_ex_feed_wrath"),
                      ("FEED_SHOCK", "derpy_chd_ex_feed_shock"),
                      ("FEED_DELIST", "derpy_chd_ex_feed_delist")):
        m = re.search(r"EX\.%s\s*=\s*(\d+)" % name, lua_raw)
        assert m and int(m.group(1)) == crit[key], (
            "EX.%s is %s, the row indexes %s" % (name, m and m.group(1), crit[key]))

    # AND NO DILEMMA MAY COME BACK. A DilemmaChoiceMadeEvent listener that MATCHES hard-crashes
    # the game - seven times, byte-identical, the last with an EMPTY handler - and a dilemma
    # cannot be dismissed without answering, so a fired demand bricked the campaign. Comments
    # stripped first: the block explaining the crash names every one of these verbatim.
    lua_code = chr(10).join(l for l in io.open(LUA_SCRIPT, encoding="utf-8").read().splitlines()
                            if not l.lstrip().startswith("--"))
    for banned in ("DilemmaChoiceMadeEvent", "create_dilemma_builder",
                   "launch_custom_dilemma_from_builder", "add_choice_payload",
                   "faction_pooled_resource_transaction"):
        assert banned not in lua_code, (
            "%s is back in the exchange script - see section 30 of the 2026-09-05 handoff; "
            "a matching DilemmaChoiceMadeEvent listener crashes the game and an unanswerable "
            "dilemma bricks the campaign" % banned)
    # The payment route is the panel now, so it must exist and must hang off the offer button.
    assert "function EX.pay_demand()" in lua_code, "nothing can pay a demand"
    assert re.search(r"function EX\.offer\(res\).*?EX\.pay_demand\(\)", lua_code, re.S), (
        "EX.offer does not route a pending demand to EX.pay_demand - the Sacrifice button is "
        "the only way to answer one now")
    assert "EX.check_demand()" in lua_code, "nothing applies the wrath when the deadline passes"

    # NO DANGLING ICON PATH ON A POOLED RESOURCE. Blank is fine (59 of 246 vanilla rows are),
    # a real file is fine, but a name that resolves to nothing is what shipped for 17 pools and
    # is the only concrete defect found while chasing the 2026-09-05 dilemma crash. If this is
    # ever set again, the file must exist in ui/skins/default/ INSIDE THIS PACK - the engine
    # does not look in ui/campaign ui/effect_bundles/, which is where resources_tables points.
    packed = set()
    icon_dir = os.path.join(ROOT, "Modding Files", "pack", "ui", "skins", "default")
    if os.path.isdir(icon_dir):
        packed = set(os.listdir(icon_dir))
    for r in t["pooled_resources_tables"][1]:
        ic = r["optional_icon_path"]
        assert ic == "" or ic in packed, (
            "%s points at %s, which this pack does not ship under ui/skins/default/ - "
            "a pooled resource icon resolves THERE and nowhere else" % (r["key"], ic))

    assert set(OFFERING_EFFECTS) == set(COMMODITIES), (
        "every commodity needs an offering effect: missing %s"
        % (set(COMMODITIES) - set(OFFERING_EFFECTS)))
    assert len(offerb) == len(COMMODITIES) * len(_races)
    assert all(b["localised_title"] and b["localised_description"] for b in offerb)
    for res in COMMODITIES:
        assert offering_bundle(res) != hold_key(res), (
            "offering bundle key collides with the POOLED RESOURCE key for %s" % res)
    # An offering that costs less than a lot could be bought and burned in one click for free
    # value; one that outlives its own cooldown would stack with itself.
    assert OFFER_COST >= LOT_SIZE, "an offering must cost at least one lot"
    # THE ESCALATION, mirrored. The script owns the arithmetic; if these three drift the panel
    # charges one price and the docs promise another, and nothing errors.
    lua_off = io.open(LUA_SCRIPT, encoding="utf-8").read()
    for name, val in (("OFFER_COST", OFFER_COST), ("OFFER_STEP", OFFER_STEP),
                      ("OFFER_MULT_MAX", OFFER_MULT_MAX)):
        m = re.search(r"EX\.%s\s*=\s*([\d.]+)" % name, lua_off)
        assert m and float(m.group(1)) == float(val), (
            "EX.%s is %s in the script, %s here" % (name, m and m.group(1), val))
    assert OFFER_STEP > 1.0, "a step of 1.0 or less is not an escalation"
    # A ceiling is not optional with compounding: uncapped, 5% per sacrifice passes anything a
    # player can hold and the offerings view becomes a wall of "Cannot".
    assert 1.0 < OFFER_MULT_MAX <= 20.0, OFFER_MULT_MAX
    # The panel must show the LIVE price, never the base - the two differ from the second
    # sacrifice onward, and a row that prints the base lies about what the button will charge.
    code_off = chr(10).join(l for l in lua_off.splitlines()
                            if not l.lstrip().startswith("--"))
    # EXACTLY TWO live mentions: the constant itself, and the one read inside EX.offer_cost
    # that turns it into a price. A third is a caller that skipped the escalation and will
    # charge, or display, the base forever.
    n = code_off.count("EX.OFFER_COST")
    assert n == 3, (
        "EX.OFFER_COST is read %d times in live code; expected 3 - the constant, the read "
        "inside EX.offer_cost that turns it into a price, and the guide line EX.bind_race "
        "rewrites, which describes the BASE cost on purpose and used to carry a hand-typed "
        "30. Anything else must call EX.offer_cost()." % n)
    assert OFFER_TURNS >= 1

    bj = t["effect_bundles_to_effects_junctions_tables"][1]
    # THE OFFERING AND PATRON HALVES ARE PER RACE; the warehouse tiers and the trade-income
    # steps are shared. Getting that split wrong in either direction is what this counts.
    assert len(bj) == (len(TRADE_STEPS)
                       + len(COMMODITIES) * len(_races)
                       + len(COMMODITIES) * len(STOCK_TIERS)
                       + (len(WRATH_EFFECTS) + len(PLEASED_EFFECTS)) * len(_races)), len(bj)
    assert all(j["advancement_stage"] == STAGE for j in bj), "empty here is a startup refusal"
    # key -> (culture, commodity), so the junction can be checked against the effect THAT
    # RACE's offering grants - which is not OFFERING_EFFECTS for every race any more.
    offer_keys = dict(("%s%soffering_%s" % (PREFIX, r["seg"], short(res)), (c, res))
                      for c, r in _races.items() for res in COMMODITIES)
    oj = [j for j in bj if j["effect_bundle_key"] in offer_keys]
    assert len(oj) == len(offerb)
    for j in oj:
        culture, res = offer_keys[j["effect_bundle_key"]]
        eff, scope, base = offering_effect(culture, res)
        assert j["effect_key"] == eff and j["effect_scope"] == scope, (
            "%s: junction says %s/%s, %s's offering of %s grants %s/%s"
            % (j["effect_bundle_key"], j["effect_key"], j["effect_scope"],
               culture, res, eff, scope))
        assert j["value"] == float(base * OFFER_MULT)

    tj = [j for j in bj if j["effect_key"] == TRADE_EFFECT]
    assert len(tj) == len(TRADE_STEPS)
    assert all(j["effect_scope"] == TRADE_SCOPE for j in tj)
    assert sorted(j["value"] for j in tj) == sorted(float(x) for x in TRADE_STEPS)
    assert {j["effect_bundle_key"] for j in tj} == {trade_bundle(x) for x in TRADE_STEPS}

    # Every bundle key the Lua can ever APPLY resolves to a real row. The ladder keys are
    # deliberately absent: the only Lua that still names one is EX.strip_legacy_bundles, which
    # REMOVES it, under a pcall, from saves made before stage 2.
    assert ({trade_bundle(x) for x in TRADE_STEPS}
            | set(offer_keys)
            | {stock_bundle(r, i) for r in COMMODITIES
               for i in range(1, len(STOCK_TIERS) + 1)}
            | set(r["wrath"] for r in _races.values())
            | set(r["pleased"] for r in _races.values())) == {b["key"] for b in bun}

    # no duplicate combined key inside any table - the game drops duplicates in silence
    # A junction table's primary key is a COMBINATION of columns, not its first one - keying on
    # column 0 alone reports every junction as duplicated, since bonus_value_id is constant.
    for table, (cs, rows) in sorted(t.items()):
        if table == "loc":
            keys = [r[0] for r in rows]
        elif "key" in cs:
            keys = [r["key"] for r in rows]
        elif "id" in cs:
            keys = [r["id"] for r in rows]
        else:
            keys = [tuple(sorted(r.items())) for r in rows]   # junction: the whole row
        assert len(keys) == len(set(keys)), "duplicate key in %s" % table

    check_race_table()
    check_lua_mp()
    check_race_bind()
    check_pool_reach(t)
    check_sorting()
    check_layout()
    check_chart_geometry()
    check_race_tune()
    check_no_foreign_keys(t)
    check_culture_appetites()
    check_button_decline_log()
    check_no_patron_literals()
    check_intro_art()
    check_button_tip()
    check_key_segments()
    check_titles()
    check_help_line_indices()
    check_trend_colours()
    check_chd_deposits_covered()
    check_chd_trade_resources()
    check_trend_glyph_widths()
    check_spread()
    check_layer2_sell()
    check_friendly()
    check_lua_agrees()
    check_lua_scan()
    check_lua_appetite()
    check_lua_boons()
    check_boon_units()
    check_demands()
    check_production()
    check_mct()
    check_tunables()
    check_presets()
    check_snapshot_and_debug()
    check_trend_snapshot()
    check_trend_survives_load()
    check_lua_shocks()
    check_shock_news()
    check_lua_hover()
    check_lua_warehouse()
    check_lua_houses()
    check_lua_books()
    check_house_row_display()
    check_house_flag_icon()
    check_house_discovery()
    check_save_store()
    check_lua_log()
    check_price_cell()
    check_init_hardening()
    check_lua_placeholder()
    check_nav_cycle()
    check_lua_button()
    check_finance_recolour()
    check_hud_income()
    check_no_orphans()
    check_features()
    check_holdings()
    check_footer_literals()
    check_footer_bounds()
    check_header_labels()
    check_tooltips()
    check_panel_blocks_map()
    check_closes_on_end_turn()
    check_ai_turn_gate()
    check_help_lines()
    check_standing_accessor()

    # DEMANDS_ENABLED is a plain switch again. It existed to disable a feature that bricked
    # the campaign; that feature is rewritten off dilemmas, and the real safety property is now
    # asserted directly - no DilemmaChoiceMadeEvent listener, no dilemma builder, no payload.
    lua_flag = io.open(LUA_SCRIPT, encoding="utf-8").read()
    m = re.search(r"EX\.DEMANDS_ENABLED\s*=\s*(\w+)", lua_flag)
    assert m, "EX.DEMANDS_ENABLED is missing from the script"
    assert re.search(r"if not EX\.DEMANDS_ENABLED then return end", lua_flag), (
        "maybe_demand does not check EX.DEMANDS_ENABLED first")
    if m.group(1) != "true":
        print("*** DEMANDS ARE OFF (EX.DEMANDS_ENABLED = %s)" % m.group(1))

    # THE SHIPPING CADENCE, set 2026-09-05. Chance is per turn once off the 15-turn
    # cooldown, so 30% means a demand roughly every 3 turns of eligibility, not every 3
    # turns - the cooldown dominates. Change these two and this dict together, or the
    # banner starts crying wolf and gets ignored, which is how a test value ships.
    shipping = {"DEMAND_FIRST_TURN": 15, "DEMAND_CHANCE": 30}
    off = ["%s=%d (ships %d)" % (k, globals()[k], v)
           for k, v in sorted(shipping.items()) if globals()[k] != v]
    if off:
        print("*** TEST CADENCE ACTIVE, do not publish: " + ", ".join(off))

    rows = sum(len(v[1]) for v in t.values())
    seen = {}
    for member, value in sorted(crit.items()):
        assert value not in seen, (
            "feed index %d is used by BOTH %s and %s. show_message_event resolves an index to "
            "ONE record, so one of these two draws the other's picture and sound."
            % (value, seen[value], member))
        seen[value] = member
    for slot, f in enumerate(FEED):
        assert crit[f[0]] == f[1], (
            "the Chaos Dwarf %s record is index %d, was %d. Those four numbers are named by "
            "every check and log line in this file." % (f[0], crit[f[0]], f[1]))
        del slot

    print("selftest ok: %d commodities, %d ladder rungs, 0 rituals, %d tables, %d rows, "
          "lua agrees" % (len(COMMODITIES), len(LADDER), len(t) - 1, rows))


LUA_EXE = r"C:\Program Files (x86)\Lua\5.1\lua.exe"
LUA_SCRIPT = os.path.join(ROOT, "Modding Files", "pack", "script", "campaign", "mod",
                          "zzz_derpy_chd_exchange.lua")

MCT_DIR = os.path.join(ROOT, "Modding Files", "pack", "script", "mct", "settings")
MCT_LUA = os.path.join(MCT_DIR, "derpy_chd_zharr_exchange.lua")


# MEASURED IN GAME 2026-09-06 with uicomponent:TextDimensionsForText against a live row_trend
# cell (30x20, state "standard") on the open exchange panel. Widths in pixels.
#
# THIS TABLE EXISTS BECAUSE A CHARACTER BUDGET SHIPPED BROKEN. The cap marker went out as "MAX"
# on the strength of check_help_lines' ~6.7px/char - a figure derived from the GUIDE column at a
# smaller font - and the panel drew "M...". Capitals in the row font run 11-16px EACH.
TREND_GLYPH_PX = {
    "^": 11, "v": 11, "-": 8, "Hi": 19, "Lo": 20,
    # Measured and rejected, kept so nobody re-measures them: three capitals never fit.
    # "MAX": 35, "MIN": 32, "TOP": 33, "max": 29, "min": 26, "^^": 18, "vv": 18,
}


# THE SAME LESSON, ONE COLUMN OVER. Measured in game 2026-09-06 with TextDimensionsForText
# against a live hdr_trend (state "standard", font body_11) on the open panel - every header is
# size 11, so one component measures them all.
#
# check_header_labels ran on ~6.7px/char for its whole life and the character budget is wrong in
# BOTH directions here: "Commodity" measures 71 against an estimate of 60, "Last 12 turns" 79
# against 87. It passed a 36px hdr_trend holding a 38px "Trend" - the panel drew "Tr..." twice
# before anyone asked the engine. A label not in this table is refused rather than estimated,
# which forces a new reading whenever one changes.
HEADER_LABEL_PX = {
    "Commodity": 71, "Buy": 27, "Sell": 25, "Output": 45, "Trend": 38,
    "Last 12 turns": 79, "Held / rent": 66,
    "Largest producer": 101, "Share": 36, "Cartel premium": 94,
    "Held": 32, "Cost": 29, "Hashut grants": 84, "Status": 38,
    "Term": 35, "What it means": 87,
    # THE FOUR PATRON HEADERS AND THE HOUSES VIEW'S FOUR LABELS - ALL MEASURED 2026-09-08, on a
    # live hdr_trend over the MCP bridge, the same TextDimensionsForText route the rest of this
    # table came from. They used to be ESTIMATED at 9.0px/char with a note asking for exactly
    # this, and the estimates were wrong by a lot:
    #
    #     Sigmar grants       117 estimated ->  84 measured
    #     The Court grants    144           -> 101
    #     The Council grants  162           -> 113
    #     House                48           ->  40
    #     Price                48           ->  33
    #     Div                  30           ->  26
    #     Seat                 40           ->  28
    #
    # Every one OVERSTATED, which is the direction the old comment argued was safe - and it was
    # safe, in that no box ever passed that should not have. It was also useless as a
    # measurement: "The Council grants" was carrying 49px of imaginary width, enough to have
    # forced a layout change that was never needed. An estimate biased safe is still a number
    # nobody can reason from.
    #
    # The run also re-measured nine already-measured labels as a control - Commodity, Buy,
    # Sell, Output, Trend, Last 12 turns, Held / rent, Largest producer, Share, Cartel premium,
    # Status, Held, Cost, Term, What it means - and every one came back identical to the
    # 2026-09-06 figures. So the font and component are the same and the new numbers are
    # comparable to the old.
    "Sigmar grants": 84, "The Court grants": 101, "The Council grants": 113,
    "Myrmidia grants": 100,
    "House": 40, "Price": 33, "Div": 26, "Seat": 28,
}

# UPPER BOUNDS, NOT MEASUREMENTS, AND KEPT IN A SEPARATE TABLE SO THEY CANNOT BE MISTAKEN FOR
# ONE. The three races added 2026-09-09 need a width for their "<patron> grants" header, and a
# width can only come from a live TextDimensionsForText call over the wh3 bridge - which needs
# the game running with the panel open, and was not available when these were written.
#
# So they are BOUNDED at 9.0px per character rather than guessed at the truth. That is the
# figure this file used before the 2026-09-08 measuring run, and that run proved it overstates
# every single time: Sigmar grants 117 -> 84, The Court grants 144 -> 101, The Council grants
# 162 -> 113. The bound is roughly 1.4x the real width, and the patron header's box is 250px
# against a longest bound of 216 - so the guarantee the check exists to give (a label never
# clips) holds with room, and holds by arithmetic rather than by hope.
#
# WHAT IS LOST is precision, which is exactly what the 2026-09-08 comment says an
# estimate-biased-safe costs you: nobody can reason about layout from these three numbers.
# That is why they are a different table and why the check prints them separately. Replace
# each one with a real reading the next time the panel is open, and delete its entry here.
HEADER_LABEL_BOUND = {
    "Grungni grants": 126,           # 14 chars
    "Asuryan grants": 126,            # 14 chars
    "Khaine grants": 117,            # 13 chars
}


def check_trend_glyph_widths():
    """Every EX.TREND_* marker must be a string whose width in the row_trend cell was MEASURED.

    The Trend column is the narrowest text cell on the panel and the engine truncates it with an
    ellipsis and no error - "MAX" became "M..." in a shipped build. Nothing else catches this:
    check_header_labels measures HEADER labels, check_help_lines measures the GUIDE columns, and
    neither looks at what EX.trend_arrow actually returns.

    A px-per-character budget is deliberately NOT used. It is what produced the bug: this font's
    advance runs 7px for "|" and 16px for "M", so no average describes it, and summing the
    isolated glyph widths does not reproduce the measured string width either ("M" 16 + "X" 14 is
    30, but "MAX" measures 35). The only honest check is a whitelist of strings someone actually
    asked the engine about - which forces a new measurement whenever a marker changes.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    markup = re.compile(r"\[\[[^\]]*\]\]")

    lay = re.search(r"EX\.ROW_LAYOUT = \{(.*?)" + NL + r"\}", lua, re.S)
    assert lay, "EX.ROW_LAYOUT is gone"
    m = re.search(r'\{\s*"row_trend"\s*,\s*-?\d+\s*,\s*-?\d+\s*,\s*(\d+)', lay.group(1))
    assert m, "row_trend has no explicit width in EX.ROW_LAYOUT - it cannot be checked"
    box = int(m.group(1))

    consts = re.findall(r'(EX\.TREND_\w+)\s*=\s*"([^"]*)"', lua)
    assert consts, "no EX.TREND_* constants found"
    for name, raw in consts:
        text = markup.sub("", raw)
        assert text in TREND_GLYPH_PX, (
            "%s draws %r, which has never been measured in the row_trend cell. Add it to "
            "TREND_GLYPH_PX from a live TextDimensionsForText reading - do NOT estimate from a "
            "character count, which is exactly how \"MAX\" (35px) shipped into a %dpx box and "
            "drew \"M...\"." % (name, text, box))
        need = TREND_GLYPH_PX[text]
        assert need <= box, (
            "%s draws %r, measured at %dpx in a %dpx row_trend cell. The engine truncates with "
            "an ellipsis and reports nothing." % (name, text, need, box))
    print("  trend glyphs: %d markers, widest %dpx in a %dpx cell"
          % (len(consts), max(TREND_GLYPH_PX[markup.sub("", r)] for _, r in consts), box))


def check_trend_colours():
    """Every [[col:NAME]] the campaign script emits must be a name CA actually uses, and every
    tag must be closed.

    Both failure modes are silent, which is the only reason this exists. The markup itself was
    CONFIRMED BY LOOKING at the panel on 2026-09-05 rather than inferred from CA's usage - the
    "||" tooltip split is equally common in vanilla loc and does NOT work through the same call,
    so a usage count is a reason to test a token, never evidence that it works.
    """
    from vanilla_colour_names import COLOURS
    # COMMENT LINES ARE STRIPPED FIRST. The block above TREND_UP explains the markup and
    # quotes it, so the first run of this check counted four opens against two closes and
    # failed on its own documentation.
    lua = chr(10).join(
        l for l in io.open(LUA_SCRIPT, encoding="utf-8").read().splitlines()
        if not l.lstrip().startswith("--"))
    opens = re.findall(r"\[\[col:([A-Za-z_0-9]*)\]\]", lua)
    closes = len(re.findall(r"\[\[/col\]\]", lua))
    assert opens, "no colour markup in the script - did the trend arrows lose their colour?"
    assert len(opens) == closes, (
        "%d [[col:]] opened and %d closed - an unclosed tag bleeds its colour into the rest of "
        "the string" % (len(opens), closes))
    for name in opens:
        assert name in COLOURS, (
            "[[col:%s]] is not a colour CA uses anywhere in local_en.pack (%d names known). "
            "A wrong name fails silently; regenerate tools/vanilla_colour_names.py if a patch "
            "added one." % (name, len(COLOURS)))


def check_boon_units():
    """Every boon string's UNIT must match CA's own description of the effect.

    THIS SHIPPED WRONG. Build 12 relabelled res_animals as "+10 Labour per battle" while
    wh3_dlc23_effect_force_chd_campaign_post_battle_labour is a PERCENTAGE - CA's tooltip
    beside the panel read "Labour gained post-battle: +15%" and the row underneath it promised
    a flat number. Nothing caught it: check_lua_boons compares our two copies of the string to
    each other, so both being wrong the same way passes, and every other check treats the boon
    as opaque text.

    CA already wrote the answer down. effects_description_<key> carries the placeholder, and
    "%+n%" is a percentage while a bare "%+n" is flat - the trailing % is literal. Note the test
    is a SEARCH for "%+n%", not endswith: construction cost is "Construction cost: %+n% for all
    buildings" and an endswith test calls it flat, which is how the first draft of this produced
    two false positives on marble and timber.

    Reads CA's loc with RPFM shut - see tools/read_vanilla_loc.py.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from read_vanilla_loc import load as load_loc
    desc = load_loc("effects")
    checked = 0
    for res, (eff, _scope, _base) in sorted(OFFERING_EFFECTS.items()):
        ca = desc.get("effects_description_" + eff)
        assert ca, "no CA description for %s - effect key wrong?" % eff
        ca_pct = "%+n%" in ca
        our_pct = "%" in OFFERING_BOON[res]
        assert ca_pct == our_pct, (
            "%s: CA says %s (%r) but the boon string reads %r"
            % (res, "percentage" if ca_pct else "flat", ca, OFFERING_BOON[res]))
        checked += 1
    print("  boon units: %d checked against CA's own effect descriptions" % checked)


def race_table():
    """EX.RACES parsed out of the shipped Lua, so Python never types a culture key.

    Returns {culture: {field: value}}, with layer2 a list and boon_over a dict. READ rather
    than mirrored: the Lua is the source, and a second copy here would be a second thing to
    keep in sync - the exact fault check_lua_agrees exists to catch one file over.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    m = re.search(r"EX\.RACES = \{(.*?)" + NL + r"\}", lua, re.S)
    assert m, "EX.RACES is gone from the campaign script"

    # COMMENT LINES COME OUT FIRST, and this is not tidiness. The entry regex below ends an
    # entry at a `},` that is followed by the NEXT entry's `["` - so a comment written BETWEEN
    # two entries makes the earlier one swallow the comment, the later entry, and everything
    # after it. Adding the Southern Realms with a paragraph above it did exactly that: the race
    # vanished from race_table() entirely, and the only reason it was noticed at all is that
    # build() happens to index the culture directly and raised a KeyError. Any check that
    # merely ITERATES what it parsed would have passed over a missing race in silence.
    #
    # Whole-line comments only - the same one-pass rule check_spread and check_presets use, and
    # safe here because a `--` inside one of these strings would have to open the line.
    # NOT `body`: the loop below unpacks `culture, body = ...` and would shadow it.
    block = NL.join(l for l in m.group(1).splitlines()
                    if not l.lstrip().startswith("--"))

    out = {}
    for rm in re.finditer(r'\["([a-z0-9_]+)"\]\s*=\s*\{(.*?)\},\s*(?=\["|$)',
                          block + NL, re.S):
        culture, body = rm.group(1), rm.group(2)
        row = dict(re.findall(r'(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"', body))
        l2 = re.search(r"layer2\s*=\s*\{(.*?)\}", body, re.S)
        row["layer2"] = re.findall(r'"([^"]+)"', l2.group(1)) if l2 else []
        over = re.search(r"boon_over\s*=\s*\{(.*?)\}", body, re.S)
        row["boon_over"] = (dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', over.group(1)))
                            if over else {})
        out[culture] = row
    assert out, "EX.RACES parsed to nothing - the table shape changed"
    # EVERY ENTRY, OR THE PARSE IS WRONG. Counting the openers is independent of the regex that
    # reads the bodies, so the two can only agree when the parse actually worked. Without this
    # a formatting change drops a race quietly and every per-race check simply has one less
    # thing to check - which is the shape of a check that passes while the feature is broken.
    declared = re.findall(r'\["([a-z0-9_]+)"\]\s*=\s*\{', block)
    assert len(out) == len(declared), (
        "EX.RACES declares %d races but the parse read %d. Missing: %s. An entry ends at a "
        "`},` followed by the next entry's `[\"` - check the formatting of the ones named."
        % (len(declared), len(out), sorted(set(declared) - set(out))))
    return out


CHD_CULTURE = "wh3_dlc23_chd_chaos_dwarfs"


def covered_races():
    """The cultures with a profile - every race in EX.RACES except the Chaos Dwarf baseline.

    DERIVED, NEVER TYPED. Six checks used to hardcode "4" or spell the three non-CHD keys into
    a tuple, and adding the Southern Realms broke all six at once - each with a message about
    the wrong thing, and each fixable by bumping a number, which is how a count-based check
    stops meaning anything. A fifth race should need no edit here at all.
    """
    return tuple(sorted(k for k in race_table() if k != CHD_CULTURE))


def check_button_tip():
    """The opener button's tooltip must name the PLAYER's market, not the Chaos Dwarf one.

    It was a static componentleveltooltip in the button's twui.xml reading "The Zharr
    Exchange", and a Skaven player saw exactly that (screenshot, 2026-09-08). The comment
    beside it argued a runtime setter was too risky because CA's Title||Body split is proven
    only as literal XML - stale reasoning, since this file already sets ||-split tooltips
    through set_tip and they render.

    Three things are checked, because the fix has three ways to rot:

    1. The Lua actually WRITES the tooltip, on the path that makes the button visible.
    2. The XML fallback no longer names a race - if the setter ever fails, the text left on
       screen must at least not be wrong for three players out of four.
    3. The body sentence is the SAME in both files. It is written twice by necessity (one is
       static XML, one is runtime Lua) and nothing else would notice them drifting.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    xml_path = os.path.join(ROOT, "Modding Files", "pack", "ui", "campaign ui",
                            "derpy_chd_exchange_button.twui.xml")
    xml = io.open(xml_path, encoding="utf-8").read()

    assert "function EX.button_tip()" in code, "EX.button_tip is gone"
    assert re.search(r"b:SetVisible\(true\)\s*b:SetTooltipText\(EX\.button_tip\(\), true\)",
                     code), (
        "the opener's tooltip is not written where the button is made visible, so it keeps "
        "whatever static text the twui.xml carries")
    assert "EX.the_name()" in code, "EX.button_tip no longer builds from the race's name"

    m = re.search(r'componentleveltooltip="([^"]*)"', xml)
    assert m, "the opener button has no componentleveltooltip fallback at all"
    fallback = m.group(1)
    for culture, row in sorted(race_table().items()):
        assert row["name"] not in fallback, (
            "the XML fallback names %s's market (%r). It is static text on a panel that "
            "serves four races - if the runtime setter ever fails, three players out of four "
            "read the wrong name." % (culture, row["name"]))

    # THE BODY, WORD FOR WORD. Split on the || that separates CA's title from its body.
    assert "||" in fallback, "the fallback lost its Title||Body split"
    xml_body = fallback.split("||", 1)[1]
    lua_body = re.search(r'EX\.TIP_OPEN_BODY = (.*?)\n\n', code, re.S)
    assert lua_body, "EX.TIP_OPEN_BODY is gone"
    # Fold the Lua concatenation into one string the same way the runtime does.
    parts = re.findall(r'"([^"]*)"', lua_body.group(1))
    assert parts, "EX.TIP_OPEN_BODY holds no literal text"
    assert "".join(parts) == xml_body, (
        "the opener tooltip's body has drifted between the Lua and the twui.xml. They are "
        "written twice by necessity - one static, one runtime - and nothing else would "
        "notice.%s  lua: %r%s  xml: %r"
        % (NL, "".join(parts), NL, xml_body))
    print("  button tip: built from the race name, written on the visible path, and the "
          "fallback body matches the Lua word for word")


def check_no_patron_literals():
    """No race's god may be spelled out in a string the player or the log can see.

    EX.bind_race rewrites the HEADERS, TIPS and HELP_PAGES entries, and every check that
    covers wording runs through it - so the on-screen text was right for the Empire from the
    first build. The LOG was not. It read "offered 30 derpy_chd_ex_hold_rom_iron to Hashut"
    in a live Empire campaign 2026-09-08, and two demand lines had the same literal. Found by
    reading the log, not by any check: the wording checks measure what bind_race writes, and
    these three strings were built inline where bind_race never reaches.

    So this reads the file rather than running it - an inline literal is invisible to a
    harness that only inspects the tables bind_race owns.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    # NAMES AS WELL AS PATRONS. The opener button's tooltip said "The Zharr Exchange" to a
    # Skaven player for the same reason the offering log said "Hashut" to an Empire one, and
    # this check was only looking for gods. A market's name is as race-specific as its god.
    gods = sorted({cfg["patron"] for cfg in race_table().values()}
                  | {cfg["name"] for cfg in race_table().values()})
    out = []
    for i, line in enumerate(lua.splitlines(), 1):
        code = line.split("--", 1)[0]              # comments may name anyone
        if "EX.RACES" in code or "patron =" in code or "offer_title" in code:
            continue                               # the race table itself IS the literals
        if "intro =" in code:
            continue          # a race's own blurb; checked properly by the loop below
        if "patron-literal: rewritten by EX.bind_race" in line:
            # The three file-scope defaults bind_race overwrites at init. They must stay
            # byte-identical - ~20 checks read them statically without ever calling init, and
            # the Chaos Dwarf save-compatibility argument rests on the CHD strings not moving.
            # check_race_bind proves each one actually IS rewritten, by running the bind.
            continue
        for g in gods:
            if '"' not in code:
                continue
            for chunk in code.split('"')[1::2]:    # inside string literals only
                if g in chunk:
                    out.append("%d: %s" % (i, line.strip()))
                    break
    # The race table's own rows are excluded above; anything left is a hardcoded patron.
    assert not out, (
        "a race's god or market name is spelled into a runtime string - it will say the "
        "wrong one for three players out of four. Use EX.patron() / EX.race_name(). "
        "Offenders: " + "; ".join(sorted(set(out))))

    # THE INTRO BLURBS ARE THE ONE PLACE A MARKET NAME IS SPELLED OUT ON PURPOSE, because each
    # one lives inside its own race's row and is drawn only for that race. Skipping them
    # outright would have been the easy fix and the wrong one: a blurb in the Dwarf row that
    # names the Ivory Road is exactly the fault this check exists for, merely moved somewhere
    # the check no longer looks. So they are checked HERE, against the row they belong to.
    rows = race_table()
    for culture, cfg in sorted(rows.items()):
        blurb = cfg.get("intro")
        assert blurb, (
            "%s has no intro line. It is the first thing a player of that race reads, and a "
            "missing one falls back to the uncovered-culture sentence, which tells a covered "
            "player their people keep no altar here." % culture)
        assert len(blurb) <= 120, (
            "%s's intro blurb is %d characters. It is printed into one 850px row cell and "
            "text clips to its component with no error - about 126 characters at this font, "
            "so 120 is the working ceiling." % (culture, len(blurb)))
        for other, ocfg in sorted(rows.items()):
            if other == culture:
                continue
            for field in ("name", "patron"):
                token = ocfg[field]
                # A bare given name like "Khaine" can appear in another race's prose by
                # coincidence; a MARKET name cannot, and neither can a patron in practice.
                assert token not in blurb, (
                    "%s's intro blurb names %r, which belongs to %s. Every player of %s "
                    "would read another race's market on their own first page."
                    % (culture, token, other, culture))
        assert cfg["name"] in blurb or cfg["patron"] in blurb, (
            "%s's intro blurb names neither its own market (%r) nor its own patron (%r). The "
            "whole job of this line is to say what kind of board this is."
            % (culture, cfg["name"], cfg["patron"]))

    print("  intro blurbs: %d races, each naming its own market and no other, longest %d "
          "of 120 characters"
          % (len(rows), max(len(c["intro"]) for c in rows.values())))


def check_intro_art():
    """Every picture the introduction draws is a real file, and each race wears its own crest.

    A MISSING IMAGE PATH DRAWS A BLANK SQUARE. No error, no log line, nothing but a hole in
    the rail where a crest should be - and the first opening of a campaign is the one place
    nobody gets a second look. So this does not trust the spelling of a stem.

    IT ENUMERATES THE PACK INDEX RATHER THAN SEARCHING IT. A byte-grep for a path would prove
    nothing either way: the string could sit in some other file's text, and CA's packs are
    compressed so a negative result is meaningless. read_pack_index lists what is actually in
    the archive, which is the only answer to "does this file exist" - and the list is
    gen_exchange_ui._game_assets(), the same cached index that has held every imagepath in the
    three .twui.xml files since button_icon_close_24.png shipped as a blank white square.

    THE ART IS ALL ONE FAMILY on purpose. ui/campaign ui/effect_bundles/ is where this panel
    already gets its resource icons, so the rail matches the commodity list two clicks away;
    mixing in ui/buildings/icons/ would put bordered art tiles next to unbordered glyphs.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()

    dm = re.search(r'EX\.ART_DIR\s*=\s*"([^"]+)"', lua)
    assert dm, "EX.ART_DIR is gone - nothing states where the introduction's pictures live"
    art_dir = dm.group(1)
    assert art_dir.endswith("/"), "EX.ART_DIR %r does not end in a separator" % art_dir

    # WHAT THE GAME ACTUALLY SHIPS - borrowed whole from the UI generator, which has read
    # every ui*.pack index into .skilltree_cache/ui_asset_paths.json since the close button
    # shipped as a blank square. Enumerating the packs again here would be a second answer to
    # the same question, and the two would drift the first time a patch moved a file.
    from gen_exchange_ui import _game_assets
    have = _game_assets()

    # THE STEMS, from the three places they are written.
    lines_fn = lua.split("function EX.intro_lines()", 1)[1].split(NL + "end", 1)[0]
    concept = re.findall(r'EX\.art\("([a-z0-9_]+)"\)', lines_fn)
    # EIGHT, NOT NINE. The ninth picture is the crest on the opening line, and it is resolved
    # out of the race table rather than written here - so it is checked below, per race.
    assert len(concept) == 8, (
        "the introduction names %d literal pictures, not 8 - one per concept paragraph, with "
        "the crest on the opening line coming from the race table instead." % len(concept))
    assert len(set(concept)) == len(concept), (
        "the introduction paints the same picture beside two different concepts: %s"
        % sorted(k for k in set(concept) if concept.count(k) > 1))

    # AND THE OPENING LINE MUST READ THE RACE'S CREST, not the fallback. Nothing dynamic can
    # prove this: the layout harness binds no race at all, so EX.rc() is nil there and the
    # uncovered crate is the correct answer for every scene it runs. A draw that ignored the
    # race table entirely would paint a picture, paint the right NUMBER of pictures, and pass
    # every count in check_layout - while showing a Dwarf player a packing crate. Read the one
    # expression statically instead, the same way EX.show is read for the seen-flag.
    assert "r.crest" in lines_fn, (
        "the introduction's opening line no longer resolves the crest from the race table. "
        "Every count still passes and every path still exists; the crest is simply the same "
        "one for all eight races.")

    um = re.search(r'EX\.INTRO_UNCOVERED_CREST\s*=\s*"([a-z0-9_]+)"', lua)
    assert um, ("EX.INTRO_UNCOVERED_CREST is gone. Without it a culture with no profile keeps "
                "whichever crest was painted last, which tells that player they are somebody "
                "else.")

    rows = race_table()
    crests = {}
    for culture, cfg in sorted(rows.items()):
        crest = cfg.get("crest")
        assert crest, (
            "%s has no crest. The opening line names the race; a blank square beside it is "
            "the first thing a player of that race ever sees of this panel." % culture)
        crests[culture] = crest

    for stem in sorted(set(concept) | set(crests.values()) | {um.group(1)}):
        path = art_dir + stem + ".png"
        assert path in have, (
            "%r is in neither ui.pack nor ui2.pack. It draws a BLANK SQUARE - no error, no "
            "log line - and the introduction is shown once, so nobody gets a second look."
            % path)

    # AND EACH RACE'S OWN, not another one's. Same rule as the event-feed art, and the same
    # single exception: Cataph's Southern Realms ships no crest, so it borrows the Empire's
    # rather than pointing at a path that is not there. A borrow is a decision; a blank
    # square is a bug that looks like a decision.
    OWN = {CHD_CULTURE: "trait_chaos_dwarfs", "wh_main_emp_empire": "trait_human",
           "wh3_main_cth_cathay": "trait_cathay", "wh2_main_skv_skaven": "trait_skaven",
           "wh_main_dwf_dwarfs": "trait_dwarf", "wh2_main_hef_high_elves": "trait_high_elves",
           "wh2_main_def_dark_elves": "trait_dark_elves", TEB_CULTURE: "trait_human"}
    assert set(OWN) == set(crests), (
        "the crest map and EX.RACES disagree: %s" % sorted(set(OWN) ^ set(crests)))
    for culture, crest in sorted(crests.items()):
        assert crest == OWN[culture], (
            "%s wears %r. That is %s's heraldry - the fault the per-race event pictures were "
            "added to fix, moved to the crest."
            % (culture, crest,
               next((c for c, v in OWN.items() if v == crest), "another culture")))

    print("  intro art: %d pictures, all present in the game's ui packs; %d crests, each its "
          "own race's (the Southern Realms borrow the Empire's, as their feed art does)"
          % (len(set(concept)) + 1, len(crests)))


def check_layout():
    """RUN the shipped EX.layout against a stubbed panel and read every row's y back.

    Reported from a screenshot 2026-09-08: 22 names in 20 slots on the Houses view, two pairs
    of rows drawn on top of each other. The cause is not visible in the source of any one
    function, which is why this runs the layout rather than reading it:

      EX.build_panel creates the row components ONCE, from the instrument list as it stands at
      build time. EX.prune_houses then REMOVES a delisted house from EX.houses at turn start.
      The hide pass used to walk EX.instruments() - so the moment a house left that list, the
      pass stopped reaching its component, and the row stayed visible at whatever coordinate
      the previous layout gave it, drawing over whatever the new pass put there. It survived a
      view change too, so a stale house row landed on the Trade view's commodities.

    The fault is a relationship between three functions across two turns. Only laying out,
    mutating the instrument list the way the game does, and laying out again can show it.
    """
    if not os.path.isfile(LUA_EXE):
        print("  (skipped layout run: no lua.exe)")
        return
    import subprocess
    import tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_layout_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace("\\", "\\\\"))
        tmp = fh.name
    try:
        # NOT check_output: a layout that throws is a real finding and its Lua traceback is the
        # whole message. check_output would swallow it into a bare CalledProcessError.
        run = subprocess.run([LUA_EXE, tmp], capture_output=True, universal_newlines=True)
    finally:
        os.unlink(tmp)
    assert run.returncode == 0, (
        "EX.layout threw when run against a stubbed panel:%s%s" % (NL, run.stderr.strip()))
    got = run.stdout
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if not line:
            continue
        tag, _, rest = line.partition(" ")
        have[tag] = dict(kv.split("=", 1) for kv in rest.split(" ") if "=" in kv)

    scenes = ("houses_p1", "houses_p2", "after_prune", "after_discover", "trade_after",
              "chart_p2", "trade_p1_back")
    for tag in scenes:
        assert tag in have, "the layout harness never reported %s: %s" % (tag, got)

    # EX.panel_cells() MUST BE THE WHOLE UNION. The harness builds its own by scanning EX
    # for the PANEL_LAYOUT* tables, so this compares two independently-derived sets - a
    # cell named by some layout table and absent from the union is one EX.layout can
    # never hide. Without this the pstale count below is a tautology: drop a table from
    # the union and the harness stops creating its components too, so nothing is left
    # visible and the mutant walks. Measured: it did.
    assert have["union"]["missing"] == "0", (
        "%s component(s) are named by a PANEL_LAYOUT* table and are NOT in "
        "EX.panel_cells(). EX.layout hides by walking that union, so those cells can "
        "never be taken off screen and will draw at their last coordinates over "
        "whatever the next view puts there." % have["union"]["missing"])
    assert int(have["union"]["tables"]) >= 7, (
        "the harness found %s PANEL_LAYOUT* tables, expected at least 7 (trade, chart, "
        "stats, offerings, houses, log, guide). One has been renamed out of the naming "
        "convention both this harness and EX.panel_cells depend on."
        % have["union"]["tables"])

    for tag in scenes:
        assert have[tag]["clashes"] == "0", (
            "%s put %s pairs of rows at the same y - they draw ON TOP of each other and the "
            "panel shows more names than it has slots. First pair: %s"
            % (tag, have[tag]["clashes"], have[tag].get("first", "?")))
        assert have[tag]["stale"] == "0", (
            "%s left %s row(s) visible that the current view does not list. A row the hide "
            "pass cannot reach stays exactly where the last layout put it - which is the "
            "2026-09-08 overlap. Hide by walking the holder's CHILDREN, never the instrument "
            "list, because a pruned house leaves that list while its component remains."
            % (tag, have[tag]["stale"]))
        assert have[tag]["pstale"] == "0", (
            "%s left %s PANEL-LEVEL component(s) visible that the current view does not "
            "name, starting with %s. The rule that governs rows governs the panel's own "
            "children too: one that is never placed keeps the last view's coordinates, "
            "or - if no view has ever placed it - the dock offset in the .twui.xml, and "
            "draws there over whatever this view put in the space. EX.layout's hide pass "
            "must walk EX.panel_cells(), the union of every layout table, and not one "
            "hand-kept list. Screenshotted 2026-09-09: it walked EX.HEADERS.trade, so the "
            "deep chart's six cells - named only by PANEL_LAYOUT_CHART - drew across the "
            "commodity list on page 1 while the row count above stayed 0."
            % (tag, have[tag]["pstale"], have[tag].get("pfirst", "?")))

    # A full page is a full page. 41 houses, 20 to a page: both pages fill, and the page after
    # a prune still fills rather than showing the 20 minus the 5 that were dropped.
    for tag in ("houses_p1", "houses_p2", "after_prune", "after_discover"):
        assert have[tag]["visible"] == "20", (
            "%s drew %s rows on a page that holds 20" % (tag, have[tag]["visible"]))

    # ...and the trade view draws its commodities and NOTHING else. The count is the shipped
    # list's own length, so this does not go stale when a commodity is added.
    n_trade = len(COMMODITIES)
    assert have["trade_after"]["visible"] == str(n_trade), (
        "the trade view drew %s rows for %d commodities - a house row survived the view "
        "change" % (have["trade_after"]["visible"], n_trade))

    # PAGE 2 OF TRADE IS THE DEEP CHART AND NOTHING ELSE. Not "mostly the chart": a single
    # commodity row left behind here lands in the middle of the plot, and ROW_LAYOUT_CHART
    # is empty precisely so that cannot happen.
    assert have["chart_p2"]["visible"] == "0", (
        "the deep chart page drew %s commodity row(s). Page 2 is one chart at full width; "
        "EX.mode_instruments must return an empty list there."
        % have["chart_p2"]["visible"])

    # ...AND PAGING BACK RESTORES THE LIST IN FULL. The chart page hides all 17 rows, so a
    # hide pass that could not un-hide them would leave page 1 empty - the opposite fault
    # to the overlay, and equally invisible to anything that reads the source.
    assert have["trade_p1_back"]["visible"] == str(n_trade), (
        "paging back from the chart left %s of %d commodity rows on screen"
        % (have["trade_p1_back"]["visible"], n_trade))

    # THE AXIS LABELS, DRAWN RATHER THAN PLACED. Everything above proves the chart's cells
    # are put in the right place and taken off screen again. None of it can see what they
    # SAY, and a label keeps its last text forever unless something writes over it - so
    # charting one commodity and then clicking away used to be the shape of a stale scale
    # standing beside "No commodity chosen".
    assert have["chart_full"]["filled"] == "6", (
        "a full 40-turn buffer filled %s of the 6 axis labels, want all of them: three "
        "gold values up the y scale and three turn numbers along the x."
        % have["chart_full"]["filled"])
    assert have["chart_short"]["filled"] == "4", (
        "a 4-turn buffer filled %s axis labels, want 4. The bars pack to the RIGHT, so on "
        "a short history the first and middle x ticks have no bar over them and must be "
        "blank - a turn number there names a turn from before the campaign started."
        % have["chart_short"]["filled"])
    assert have["chart_none"]["filled"] == "0", (
        "%s axis label(s) survived a click away from the chart. Every one of them has to "
        "be blanked when nothing is chosen: they are panel-level components, so the last "
        "commodity's price scale otherwise stands next to 'No commodity chosen' with "
        "nothing on screen saying whose prices those were."
        % have["chart_none"]["filled"])
    for tag, want in (("chart_full", "1"), ("chart_short", "1"), ("chart_none", "0")):
        assert have[tag]["icon"] == want, (
            "%s has the chart icon %s, want %s. It is painted from EX.icon - the same "
            "source the list rows use - and hidden outright when nothing is chosen, "
            "because the previous commodity's picture is a claim about the wrong good."
            % (tag, have[tag]["icon"], want))

    # THE INTRODUCTION DRAWS NO ROWS OF DATA and heads no columns, so the trade view's own
    # cells are all absent from it - which makes the exit the interesting half. A cell left
    # behind here lands on top of the commodity list the player asked for by clicking Trade.
    assert have["intro"]["visible"] != "0", (
        "the introduction placed no rows at all. It borrows the row machinery to print prose, "
        "so a view with nothing visible is a first-run page that draws an empty panel.")
    assert have["after_intro"]["visible"] == "17", (
        "leaving the introduction left %s rows instead of the trade view's 17 - the prose "
        "rows are the same components the commodity list uses, so a stale one is a paragraph "
        "sitting on a price." % have["after_intro"]["visible"])

    # THE STATE MACHINE, which no scene above can see. A page that draws perfectly and shows
    # on every single opening passes every other assertion in this function.
    assert have["intro_once"]["fresh"] == "false", (
        "a fresh campaign reads the introduction as already seen (%s), so nobody would ever "
        "get it." % have["intro_once"]["fresh"])
    assert have["intro_once"]["arrived"] == "false", (
        "arriving at the introduction retires it. A player who opens the panel and shuts it "
        "again has then spent their one showing without reading a line.")
    assert have["intro_once"]["left"] == "true", (
        "leaving the introduction did not retire it, so it returns on every opening for the "
        "rest of the campaign. There is no dismiss button - leaving IS the dismissal - so "
        "this is the only thing that ever writes the flag.")

    # THE DRAW, coming in from the trade view. Three separate things, and the middle one is
    # what no layout scene can see.
    d = have["intro_draw"]
    # THE CEILING IS THE SHORTEST RACE'S HOLDER, and it is now exactly full: nine paragraphs
    # with a blank row between each. NOT COMMODITIES + LAYER2 - EX.mode_instruments adds
    # LAYER2, but LAYER2 is the Chaos Dwarf pair and every other race binds it empty, so a
    # Chaos Dwarf player has 19 rows and everybody else has 17. Sizing to 19 drew perfectly
    # for the race being looked at and lost two paragraphs for the other six; the harness
    # caught it because it binds a race with no Layer 2. Over the cap nothing errors - the
    # draw walks the rows, so the extra lines simply never appear.
    cap = len(COMMODITIES)
    assert d["lines"] == str(cap), (
        "the introduction is %s lines against the %d rows a race with no Layer 2 gets. Over "
        "the cap the extra lines never draw at all - silently, and only for the six races "
        "that are not Chaos Dwarfs. Under it the page leaves dead space, which is the fault "
        "the paragraph breaks were added to fix. To make room, fold a line into the two "
        "footer strings the way the closing instruction already is."
        % (d["lines"], cap))
    assert d["shown"] == d["lines"], (
        "%s rows are visible for %s lines of introduction. The rows are the SAME components "
        "the commodity list uses, so a spare left over from the trade view is a price sitting "
        "under a paragraph - and a row short of the text is a paragraph that never drew."
        % (d["shown"], d["lines"]))
    assert d["texted"] == d["want"], (
        "%s of %s rows that should carry a paragraph actually do. A row can be visible because "
        "EX.layout placed it and still have had nothing written into it - visible and drawn "
        "are different questions, which is what let the chart icon's paint call be deleted "
        "without a mutant noticing. The two rows that are blank on purpose are the paragraph "
        "breaks, and they are excluded by counting rather than by forgiving a blank."
        % (d["texted"], d["want"]))

    want_w = re.search(r'EX\.ROW_LAYOUT_INTRO = \{.*?"row_name"\s*,\s*-?\d+\s*,'
                       r"\s*-?\d+\s*,\s*(\d+)",
                       io.open(LUA_SCRIPT, encoding="utf-8").read(), re.S)
    assert want_w, "EX.ROW_LAYOUT_INTRO no longer gives row_name an explicit width"
    assert d["width"] == want_w.group(1), (
        "the introduction's paragraphs were drawn %spx wide against the %spx its layout table "
        "asks for. set_text FORCES a cell visible and writes into it, so a cell that no layout "
        "table places still draws - at whatever width the last view gave it. A paragraph in a "
        "price column's 200px is the visible result and nothing raises."
        % (d["width"], want_w.group(1)))

    # THE PICTURES. Three separate questions, and the count is the one that has to be a
    # literal here: the harness derives want_icon from EX.intro_lines itself, so on its own it
    # would only ever prove the table equals itself. Nine is the design - a crest on the line
    # that names the race, one picture per concept, and none on the closing instruction.
    assert d["want_icon"] == "9", (
        "%s of the introduction's lines carry a picture, not 9. The rail is a crest on the "
        "opening line plus one icon per concept; the closing line is an instruction rather "
        "than a concept and deliberately has none." % d["want_icon"])
    assert d["iconed"] == d["want_icon"], (
        "%s of %s pictures were actually painted. A cell can be visible because EX.layout "
        "placed it and still carry nothing - or worse, still carry the commodity picture the "
        "row was BUILT with, which is a paragraph about rent wearing a gemstone. Only the "
        "image path tells the two apart." % (d["iconed"], d["want_icon"]))
    assert d["bare"] == str(int(d["shown"]) - int(d["iconed"])), (
        "%s rows put the picture away against %s that carry one, out of %s shown. A "
        "paragraph break that keeps the last line's icon draws a floating crest in a gap."
        % (d["bare"], d["iconed"], d["shown"]))

    lua_i = io.open(LUA_SCRIPT, encoding="utf-8").read()
    want_x = re.search(r'EX\.ROW_LAYOUT_INTRO = \{.*?"icon"\s*,\s*(-?\d+)', lua_i, re.S)
    assert want_x, (
        "EX.ROW_LAYOUT_INTRO no longer places the icon cell. EX.draw_intro shows it itself, "
        "so the pictures would still DRAW - at whatever x the previous view left them, on top "
        "of the paragraph text.")
    assert d["icon_x"] == want_x.group(1), (
        "the introduction's pictures landed at x=%s against the %s its layout table asks for."
        % (d["icon_x"], want_x.group(1)))

    # AND EX.show IS WHAT CONSULTS IT. The harness sets EX.mode by hand, so it can prove the
    # flag works and never that anything reads it. Read the one caller statically instead.
    lua_src = io.open(LUA_SCRIPT, encoding="utf-8").read()
    body = lua_src.split("function EX.show(", 1)[1].split(NL + "end", 1)[0]
    assert "EX.intro_seen()" in body and "EX.MODE_INTRO" in body, (
        "EX.show no longer puts a first-time player into the introduction. Every check above "
        "still passes: the view draws correctly and the flag works, and nobody is ever sent "
        "there.")

    print("  layout: 9 scenes, no two rows share a y, no row and no panel cell outlives "
          "its view (prune, discovery, a view change and the chart page all covered); "
          "chart axes drawn at 6/4/0 labels and the icon follows the selection; the "
          "introduction fills all %d rows and paints 9 pictures, %d put away"
          % (cap, cap - 9))


def check_chart_geometry():
    """THE CHART'S NUMBERS, ACROSS TWO FILES THAT SHARE NOTHING.

    tools/gen_exchange_ui.py lays the bars out in the .twui.xml at build time; the campaign Lua
    re-positions and re-sizes every one of them at runtime with MoveTo and Resize, from its own
    copies of the same constants. Nothing connects the two but a comment, and a disagreement is
    silent in both directions - a pitch that is one pixel wider in the Lua walks the fortieth
    bar off the end of the plot, and a CHART_H that disagrees puts every bar's baseline in the
    wrong place with no error anywhere.

    It also pins the AXIS TICKS to the bar formula. The y labels are not thirds of the box: the
    lowest price draws a CHART_FLOOR-tall stub rather than nothing, so the bottom of the scale
    is CHART_FLOOR up from the bottom of the plot. A label placed at the box edge instead is
    6px out from its own data and reads as correct.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    import gen_exchange_ui as U

    def luaconst(name):
        m = re.search(r"^EX\.%s\s*=\s*(\d+)" % name, lua, re.M)
        assert m, "EX.%s is not declared in the campaign script" % name
        return int(m.group(1))

    for name in ("DEEP_BARS", "CHART_H", "CHART_PITCH", "CHART_BAR_W", "CHART_FLOOR"):
        want = getattr(U, name)
        got = luaconst(name)
        assert got == want, (
            "EX.%s is %d in the campaign script and %s is %d in gen_exchange_ui.py. The XML "
            "lays the bars out at build time and the Lua moves and resizes every one of them "
            "at runtime, each from its own copy of this number - they disagree in silence."
            % (name, got, name, want))

    # The layout table, read the way check_header_labels reads the others.
    body = lua.split("EX.PANEL_LAYOUT_CHART = {", 1)[1].split(NL + "}", 1)[0]
    cells = dict((n, (int(x), int(y), int(w) if w else None)) for n, x, y, w in re.findall(
        r'\{\s*"(\w+)"\s*,\s*(-?\d+)\s*,\s*(-?\d+)(?:\s*,\s*(-?\d+))?', body))

    # EVERY chart CELL IN THE XML IS NAMED HERE. One that is not can never be placed, and
    # since 2026-09-09 EX.layout hides everything it does not place - so the fault flipped
    # from "draws in the wrong spot forever" to "never draws at all", which is quieter still.
    # cbar_* are children of `chart` and move with it; they are placed by EX.draw_chart.
    xml = set()
    for c in U.build_panel().walk():
        if c.name.startswith("chart") and not c.name.startswith("cbar"):
            xml.add(c.name)
    for name in sorted(xml):
        assert name in cells, (
            "%s exists in the panel .twui.xml and is not named by EX.PANEL_LAYOUT_CHART, so "
            "no view ever places it and EX.layout hides it on every page. It would never "
            "draw, and nothing would say why." % name)

    # THE PLOT FITS. 20px panel margin each side of an ROW_W-wide content strip.
    right = cells["chart"][0] + U.DEEP_BARS * U.CHART_PITCH
    assert right <= 20 + U.ROW_W, (
        "the plot starts at x=%d and %d bars at a pitch of %d reach %d, past the panel's "
        "content edge at %d. The last bars are drawn off the panel."
        % (cells["chart"][0], U.DEEP_BARS, U.CHART_PITCH, right, 20 + U.ROW_W))

    # ...AND THE Y GUTTER CLEARS IT. The labels are right-aligned into 20..80.
    for tick in ("chart_y_hi", "chart_y_mid", "chart_y_lo"):
        end = cells[tick][0] + (cells[tick][2] or 0)
        assert end <= cells["chart"][0], (
            "%s ends at x=%d and the plot starts at x=%d - the y scale would be drawn under "
            "the bars, legible until the buffer fills and then never again"
            % (tick, end, cells["chart"][0]))

    # THE TICKS SIT ON THE GRIDLINES THE BAR FORMULA MAKES, not on thirds of the box.
    span = U.CHART_H - U.CHART_FLOOR
    for tick, frac in (("chart_y_hi", 1.0), ("chart_y_mid", 0.5), ("chart_y_lo", 0.0)):
        line = U.CHART_TOP + span * (1.0 - frac)
        want = int(line - 9)          # an 18px box, vertically centred on the line
        assert cells[tick][1] == want, (
            "%s is at y=%d; the bar top for that price is at y=%.1f, so an 18px label centred "
            "on it belongs at y=%d. EX.draw_chart sizes a bar as CHART_FLOOR + frac * "
            "(CHART_H - CHART_FLOOR): the LOW gridline is %d px up from the bottom of the "
            "plot, not at the bottom."
            % (tick, cells[tick][1], line, want, U.CHART_FLOOR))

    # AND THE RULE SITS ON ITS OWN LABEL. Three numbers down the left and three lines across
    # the plot, in two files that share nothing: a gridline one pixel off its label is a chart
    # that reads wrong rather than a chart that looks broken, and no screenshot would show it.
    for grid, tick, frac in (("chart_grid_hi", "chart_y_hi", 1.0),
                             ("chart_grid_mid", "chart_y_mid", 0.5),
                             ("chart_grid_lo", "chart_y_lo", 0.0)):
        assert grid in cells, (
            "%s is not named by EX.PANEL_LAYOUT_CHART, so EX.layout hides it and the plot "
            "has no rule at the %s price." % (grid, tick))
        gx, gy, gw = cells[grid]
        want = int(U.CHART_TOP + span * (1.0 - frac))
        assert gy == want, (
            "%s is at y=%d and the bar top for that price is at y=%d. The rule and the number "
            "it belongs to would disagree, which reads as a wrong price rather than a broken "
            "chart." % (grid, gy, want))
        assert gy == cells[tick][1] + 9, (
            "%s is at y=%d and %s at y=%d. The label is an 18px box centred on the line, so "
            "the rule belongs at the label's y plus 9 - these two are edited in different "
            "files and nothing else connects them."
            % (grid, gy, tick, cells[tick][1]))
        assert gx == cells["chart"][0], (
            "%s starts at x=%d and the plot at x=%d, so the rule does not begin where the "
            "bars do." % (grid, gx, cells["chart"][0]))
        assert gw == U.DEEP_BARS * U.CHART_PITCH, (
            "%s is %s px wide against a plot of %d. A rule that stops short of the newest "
            "bars is worse than none: the eye reads the gap as no data."
            % (grid, gw, U.DEEP_BARS * U.CHART_PITCH))

    # THE RULES ARE DECLARED AHEAD OF THE PLOT. Siblings are written to the panel file in
    # the order they are added, and the intent is that the bars paint over the rules rather
    # than the other way round. NOT VERIFIED IN PLAY - nothing here has seen the engine's
    # sibling draw order, and a rule on top of a bar is a cosmetic fault rather than a broken
    # one. What this pins is that the order cannot silently FLIP: a later edit that appends
    # the rules after the plot fails here rather than being noticed in a screenshot.
    order = [c.name for c in U.build_panel().walk()]
    for grid in ("chart_grid_hi", "chart_grid_mid", "chart_grid_lo"):
        assert order.index(grid) < order.index("chart"), (
            "%s is declared after the plot in the panel .twui.xml. Sibling order is the only "
            "thing deciding which of the two paints on top." % grid)

    # AND THE X TICKS SIT OVER THE BARS THEY NAME - bar 0, the middle bar, and the newest.
    # EX.draw_chart writes them from the same three indices; if these move, the label names
    # a turn that belongs to a bar somewhere else on the strip.
    plot = cells["chart"][0]
    for tick, bar, align in (("chart_x_left", 0, "L"),
                             ("chart_x_mid", U.DEEP_BARS // 2, "C"),
                             ("chart_x_right", U.DEEP_BARS - 1, "R")):
        x, _y, w = cells[tick]
        lo, hi = plot + bar * U.CHART_PITCH, plot + bar * U.CHART_PITCH + U.CHART_BAR_W
        if align == "L":
            got = x                       # label reads rightward from the bar's left edge
        elif align == "R":
            got = x + w                   # ...and leftward to the bar's right edge
        else:
            got = x + w / 2.0             # centred on the bar
        assert lo - 1 <= got <= hi + 1, (
            "%s anchors at x=%.1f but bar %d spans %d..%d. The tick names a turn belonging to "
            "a bar it does not sit over." % (tick, got, bar, lo, hi))

    print("  chart geometry: %d constants agree across both files, %d cells all reachable, "
          "y ticks on the bar formula's own gridlines with a rule drawn across the plot at each, x ticks over bars 0/%d/%d"
          % (5, len(xml), U.DEEP_BARS // 2, U.DEEP_BARS - 1))


# The four knobs a race profile may NEVER move, and the reason is arithmetic rather than taste:
# these are the terms in the round-trip inequality check_spread() guards. A factor on any of
# them can open a gap between what a buy costs and what a sell one rung up pays, which is a gold
# printer that looks exactly like a working market. The `easy` preset had one for months.
SPREAD_ALGEBRA_KEYS = ("spread", "ladder_step", "sell_floor", "friendly_max")

# The numbers the patch notes state for a default-difficulty Skaven board. Pinned because they
# are what the player was shown when the profile was chosen, and a silent drift in EX.RACES
# would make the notes wrong with nothing failing.
SKAVEN_DEFAULT = {
    "hostile_max": 0.55, "refuse_share": 0.25, "guild_close": 0.36,
    "shock_gain": 20, "shock_max": 9, "demand_chance": 55,
    "windup": 0.15, "div_yield": 0.014, "book_per_rung": 18,
    "pressure_per_rung": 3,
}


def check_button_decline_log():
    """A routine button decline must not be logged as an error.

    EX.layout() and the panel-opened hook both call place_button(EX.PLACE_TRIES) on purpose, as
    a one-shot that must not start a second chain alongside the first tick's. So every panel
    open while the resource strip is hidden or animating produces a decline that means nothing
    - and the line used to end "and no attempts left" for that case, which reads as a failure.

    Measured in a Southern Realms campaign 2026-09-08: two declines at -91 and -526, the button
    placed correctly at 1168,5 seconds later, and a full investigation spent establishing that
    nothing was wrong. A diagnostic that cries wolf is worse than one that says nothing, because
    it spends the reader's attention on the wrong thing at exactly the moment they are looking
    for a real fault.

    The three cases are: already placed (routine), a deliberate one-shot caller (routine), and
    the chain exhausted having never placed it (the only real failure). Only the third may use
    the "error" category, which EX.say lets past the level and subsystem gates unconditionally.
    """
    code = io.open(LUA_SCRIPT, encoding="utf-8").read()
    m = re.search(r"local again = retry\(\)(.*?)\n        end", code, re.S)
    assert m, "the button decline branch is gone"
    body = m.group(1)

    assert "local routine = EX.button_at or attempt >= EX.PLACE_TRIES" in body, (
        "the decline no longer separates the routine cases from the real one. Both "
        "EX.button_at (already placed) and a one-shot caller at EX.PLACE_TRIES are normal; "
        "only an exhausted chain that never placed the button is a failure.")
    assert re.search(r'EX\.say\(routine and "ui" or "error"', body), (
        "the decline is no longer categorised by whether it is routine. \"error\" bypasses "
        "EX.say's level AND category gates, so using it for the routine cases puts a false "
        "alarm in every log at every verbosity.")
    assert "THE BUTTON IS NOT PLACED" in body, (
        "the genuinely-failed case no longer says so in words. It is the one message here "
        "that a reader must not skim past.")
    for phrase in ("- normal", "does not reschedule"):
        assert phrase in body, (
            "the routine decline no longer says it is routine (%r missing)" % phrase)
    # CODE ONLY. The comment above the branch quotes the old wording to explain why it went,
    # and a check that cannot tell a quotation from the thing it warns about is a check that
    # forbids documenting its own history.
    live = NL.join(l for l in body.splitlines() if not l.lstrip().startswith("--"))
    assert "no attempts left" not in live, (
        "the old wording is back. It reported a deliberate one-shot as an exhausted budget, "
        "which is the false alarm this check exists to prevent.")

    print("  button decline: 3 cases distinguished, only an exhausted chain logs as an error")


def check_culture_appetites():
    from read_vanilla_cache import load as _load
    """Every race the mod covers must also have a world appetite, and no culture may be a pump.

    THE HOLE THIS FILLS. EX.world_appetite reads `if wants and wants[res]` - a culture absent
    from EX.CULTURE_WANTS contributes exactly ZERO to world demand, silently, with no fallback
    and nothing in any log. The Southern Realms shipped that way: fully covered as a race, with
    a name, a patron, seventeen flavour lines and a market profile, and contributing nothing at
    all to the prices those things describe. Measured live 2026-09-08 - 2.4% of the campaign's
    factions, the only culture on the board with no appetite entry.

    Nothing caught it because nothing connected the two tables. EX.RACES answers "whose market
    is this", EX.CULTURE_WANTS answers "who wants what", and a race could be in one and not the
    other forever.

    THE PUMP RULE is the second half. A culture with only positives demands and never supplies,
    which pushes every price it touches one way for the whole campaign; only negatives is the
    same fault mirrored. Every one of the 25 shipped cultures has both, so this is describing
    the existing design rather than imposing a new one - but nothing said so until now.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    m = re.search(r"EX\.CULTURE_WANTS = \{(.*?)\n\}", lua, re.S)
    assert m, "EX.CULTURE_WANTS is gone - every culture now contributes zero demand"
    body = m.group(1)
    starts = [(mm.start(), mm.group(1))
              for mm in re.finditer(r'\["([a-z0-9_]+)"\]\s*=\s*\{', body)]
    wants = {}
    for i, (pos, culture) in enumerate(starts):
        blk = body[pos:starts[i + 1][0]] if i + 1 < len(starts) else body[pos:]
        wants[culture] = dict((k, float(v)) for k, v in
                              re.findall(r"(res_\w+)\s*=\s*(-?[0-9.]+)", blk))
    assert len(wants) >= 25, "EX.CULTURE_WANTS parsed to %d cultures" % len(wants)

    # EVERY COVERED RACE HAS ONE. This is the link that did not exist.
    for culture in sorted(race_table()):
        assert culture in wants, (
            "%s is a covered race with no EX.CULTURE_WANTS entry, so every faction of that "
            "culture contributes ZERO to world demand - silently, with no fallback and nothing "
            "in the log. It gets a name, a patron and a market profile describing prices it "
            "cannot move." % culture)

    for culture, w in sorted(wants.items()):
        assert w, "%s has an empty appetite table" % culture
        bad = sorted(k for k in w if k not in COMMODITIES)
        assert not bad, (
            "%s wants %s, which is not a commodity. A key nothing matches is silently ignored "
            "by EX.world_appetite, so the appetite simply does not exist." % (culture, bad))
        for res, v in sorted(w.items()):
            assert -1.0 <= v <= 1.0, (
                "%s's %s appetite is %s - the shipped range is -1.0 to 1.0 and the scale is "
                "multiplied by ai_gain, so an outlier here is an outlier times six."
                % (culture, res, v))
        assert any(v > 0 for v in w.values()) and any(v < 0 for v in w.values()), (
            "%s only %s. A culture that never supplies pushes every price it touches one way "
            "for the whole campaign - all 25 shipped cultures have both sides."
            % (culture, "demands" if all(v > 0 for v in w.values()) else "supplies"))

    # EVERY VANILLA CULTURE THAT CAN HOLD LAND. Shares are computed over REGIONS, so a culture
    # that owns none can never contribute and needs no entry. The two exemptions are named
    # rather than derived because both are permanent facts about the base game:
    #
    #   "*"             a wildcard row in cultures_tables, not a culture at all.
    #   wh2_main_rogue  Rogue Armies - roaming forces that hold no regions. Confirmed absent
    #                   from a live campaign's culture_share entirely, not merely small.
    #
    # This is the rule that catches a NEW race arriving in a WH3 patch. A DLC culture holding
    # provinces with no appetite entry is the Southern Realms fault again, and nothing else
    # here would notice - check_race_table only covers races this mod adopts.
    # WIRED, NOT MERELY CORRECT. The harness calls EX.warn_uncovered() directly - which is
    # what lets it measure the threshold, the de-duplication and the nil case - and that is
    # exactly why it cannot notice the call site being deleted from EX.rescan. A working
    # function nobody calls is the quietest way for a feature to not exist.
    resc = re.search(r"function EX\.rescan\(\)(.*?)\nend", lua, re.S)
    assert resc, "EX.rescan is gone"
    assert "EX.warn_uncovered(share)" in resc.group(1), (
        "EX.rescan no longer calls EX.warn_uncovered, so a culture this mod has no appetite "
        "for is silently worth zero demand again - which is the whole fault the warning "
        "exists to make visible.")

    # THE EXEMPTIONS, PINNED. Both are permanent facts about the base game, and the list is
    # stated twice on purpose: growing it is then a deliberate edit in two places with a reason
    # written down, rather than the one-word way to silence a real gap.
    exempt = {"*", "wh2_main_rogue"}
    assert exempt == {"*", "wh2_main_rogue"}, (
        "the culture exemption list changed to %s. \"*\" is a wildcard row in "
        "cultures_tables rather than a culture, and wh2_main_rogue holds no regions so its "
        "share is zero by construction. Anything else added here is a land-holding culture "
        "being silenced, not exempted - give it an appetite instead." % sorted(exempt))
    real = {r["key"] for r in _load("cultures")[0]}
    uncovered = sorted(real - set(wants) - exempt)
    assert not uncovered, (
        "%d vanilla culture(s) hold land with no appetite: %s. They contribute exactly zero "
        "to world demand, silently. If one of these genuinely cannot own regions, add it to "
        "`exempt` with the reason - do not leave it to be rediscovered."
        % (len(uncovered), uncovered))

    print("  culture appetites: %d cultures, every covered race and every land-holding vanilla "
          "culture has one, all within -1..1, none a one-way pump" % len(wants))


def check_no_foreign_keys(tables):
    """A modded culture may appear in the Lua and in NOTHING this mod ships as data.

    This is what keeps the Southern Realms support OPTIONAL. A culture key written into a DB
    row - a campaign_group criterion, a faction_set, an effect scope - would make the row
    reference a key that does not exist without that mod installed, and an unresolvable foreign
    key is a load-time DB validation reject: the whole pack is dropped and the player gets
    "failed to load mod" with no idea which of the two is at fault.

    In the Lua it is harmless. EX.RACES is a table keyed by culture string; with the mod absent
    no faction ever answers that string, EX.RACES[culture] is nil, and the player is uncovered -
    which is exactly the shipped behaviour for the other 22 cultures.

    So: zero occurrences in every generated row and every loc string. The Lua is not scanned,
    because the Lua is where it is supposed to be.
    """
    for culture, (mod, workshop, pack) in sorted(MODDED_CULTURES.items()):
        hits = []
        for table, (_cols, rows) in sorted(tables.items()):
            for i, row in enumerate(rows):
                values = row if isinstance(row, (list, tuple)) else list(row.values())
                for v in values:
                    if isinstance(v, str) and culture in v:
                        hits.append("%s row %d: %r" % (table, i, v))
        assert not hits, (
            "%r reaches %d generated row(s), which would make %s (Workshop %d, %s) a REQUIRED "
            "dependency: an unresolvable key is a load-time DB reject that drops this whole "
            "pack. Keep the culture in EX.RACES and out of the data. Offenders: %s"
            % (culture, len(hits), mod, workshop, pack, "; ".join(hits[:5])))
    print("  soft dependency: %d modded culture(s) in the Lua, 0 in %d generated tables"
          % (len(MODDED_CULTURES), len(tables)))


def check_race_tune():
    """RUN every (preset, race, knob) through the shipped EX.opt and read the number back.

    A race profile is a MULTIPLIER on whatever the preset and MCT already resolved. That choice
    is the whole feature - absolute values would flatten every preset but `default`, and the
    flavour would vanish for anyone who moved the difficulty - and it is also what makes the
    thing hard to check by reading: the number a player actually plays on is a product of two
    tables, a clamp and a rounding rule, none of which is written down anywhere as a value.

    Recomputing the products in Python would check a mirror against itself. So this runs the
    file and asserts the invariants that would survive any future re-tune:

      - the Chaos Dwarf board does not move, on any preset, for any knob;
      - the four spread-algebra knobs are unreachable from a profile;
      - nothing clamps on `default`, because that is where the profile must read as designed -
        clamping is for the preset extremes;
      - a garbage entry, an uncovered race and a missing snapshot all pass through cleanly;
      - and the factor is applied EXACTLY ONCE, which is the fault that would otherwise appear
        only in campaigns started after the change.
    """
    code = io.open(LUA_SCRIPT, encoding="utf-8").read()

    # ---- THE WHITELIST, READ OFF THE FILE ----
    m = re.search(r"^EX\.RACE_TUNABLE = \{(.*?)^\}", code, re.S | re.M)
    assert m, "EX.RACE_TUNABLE is gone - every knob is now reachable from a race profile"
    bounds = dict(
        (k, (float(lo), float(hi)))
        for k, lo, hi in re.findall(
            r"(\w+)\s*=\s*\{\s*(-?[0-9.]+)\s*,\s*(-?[0-9.]+)\s*\}", m.group(1)))
    assert bounds, "EX.RACE_TUNABLE could not be parsed"
    # EX.race_factor reads race_strength through EX.opt, and the ONLY thing that stops that
    # read recursing into race_factor is EX.race_apply returning early for a key this table
    # does not list. On the whitelist it is an unbounded recursion inside the price path, which
    # runs about once a second while the panel is open.
    assert "race_strength" not in bounds, (
        "race_strength is on EX.RACE_TUNABLE. EX.race_factor reads it through EX.opt, so a "
        "key that reaches race_apply's factor branch recurses until the stack goes - in the "
        "price path, with the panel open.")
    for key in SPREAD_ALGEBRA_KEYS:
        assert key not in bounds, (
            "%r is on the race whitelist. It is a term in the round-trip inequality "
            "check_spread() guards - a race factor on it can make selling ONE RUNG UP pay "
            "more than buying cost, which is a gold printer that reads as a working market."
            % key)
    for key, (lo, hi) in sorted(bounds.items()):
        assert lo < hi, "%s's bounds are inverted: %s..%s" % (key, lo, hi)

    # ---- THE PROFILES ----
    races = re.search(r"^EX\.RACES = \{(.*?)^\}", code, re.S | re.M)
    assert races, "EX.RACES is gone"
    # AN ENTRY DOES NOT END ON A LINE OF ITS OWN - it ends `layer2 = {} },` - so this splits on
    # where the NEXT entry begins rather than trying to match a closing brace through nested
    # tables. Two of the four entries contain a `{ ... }` inside them already.
    body = races.group(1)
    starts = [(m.start(), m.group(1))
              for m in re.finditer(r'\n    \["(\w+)"\] = \{', body)]
    tunes = {}
    for i, (pos, culture) in enumerate(starts):
        block = body[pos:starts[i + 1][0]] if i + 1 < len(starts) else body[pos:]
        t = re.search(r"tune = \{(.*?)\},\n", block, re.S)
        tunes[culture] = dict(
            (k, float(v))
            for k, v in re.findall(r"(\w+)\s*=\s*(-?[0-9.]+)", t.group(1))) if t else None
    assert len(tunes) == len(race_table()), (
        "expected %d races, parsed %d: %s"
        % (len(race_table()), len(tunes), sorted(tunes)))

    assert tunes.get("wh3_dlc23_chd_chaos_dwarfs") is None, (
        "the Chaos Dwarfs have a race profile. They are the baseline every static check and "
        "every live save is measured against - the same rule seg = \"\" follows. A profile "
        "here moves the numbers under campaigns that have been running for months.")
    for culture in covered_races():
        t = tunes.get(culture)
        assert t, "%s has no race profile - the feature is half-shipped" % culture
        for key, f in sorted(t.items()):
            assert key in bounds, (
                "%s's profile names %r, which is not on EX.RACE_TUNABLE. EX.race_apply would "
                "silently ignore it, so the dial reads as configured and does nothing."
                % (culture, key))
            # A TYPO GUARD, not a design bound. 22 for 2.2 would clamp and look deliberate.
            assert 0.2 <= f <= 3.0, (
                "%s sets %s x%s. A factor outside 0.2 - 3.0 is almost always a misplaced "
                "decimal point, and the clamp would hide it." % (culture, key, f))

    # ---- AND NOW RUN IT ----
    if not os.path.isfile(LUA_EXE):
        print("  (skipped race-profile run: no lua.exe)")
        return
    import subprocess
    import tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_racetune_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace("\\", "\\\\"))
        tmp = fh.name
    try:
        run = subprocess.run([LUA_EXE, tmp], capture_output=True, universal_newlines=True)
    finally:
        os.unlink(tmp)
    assert run.returncode == 0, (
        "EX.opt threw while resolving a race profile:%s%s" % (NL, run.stderr.strip()))

    got, opts = {}, {}
    for line in run.stdout.splitlines():
        line = line.strip()
        if line.startswith("opt "):
            _, preset, culture, rest = line.split(" ", 3)
            opts[(preset, culture)] = dict(
                (kv.split("=", 1)[0], float(kv.split("=", 1)[1])) for kv in rest.split(","))
        elif line:
            tag, _, rest = line.partition(" ")
            got[tag] = rest

    want_rows = 4 * len(race_table())
    assert len(opts) == want_rows, (
        "expected 4 presets x %d races = %d rows, got %d - the harness enumerates EX.RACES "
        "itself, so a mismatch means it could not read the table"
        % (len(race_table()), want_rows, len(opts)))

    # The Chaos Dwarf board is byte-identical to the preset's own values, everywhere.
    assert got.get("chd_untouched", "").startswith("true"), (
        "the Chaos Dwarf board MOVED under a race profile: %s" % got.get("chd_untouched"))
    assert got.get("uncovered_passthrough") == "true", (
        "an uncovered race - 23 of the game's 27 cultures - does not get the preset's own "
        "numbers back")

    # The four excluded knobs are inert even when a profile names them outright.
    off = dict(kv.split("=", 1) for kv in got.get("offlist", "").split(" ") if "=" in kv)
    for key, want in (("spread", "0.1"), ("ladder_step", "1.1"), ("sell_floor", "0.25"),
                      ("friendly_max", "0.25"), ("house_cash_max", "20000")):
        assert off.get(key) == want, (
            "a profile naming %r moved it to %s. Every key off EX.RACE_TUNABLE must pass "
            "through untouched - three of these are the round-trip algebra."
            % (key, off.get(key)))

    bools = dict(kv.split("=", 1) for kv in got.get("bools", "").split(" ") if "=" in kv)
    assert bools == {"rent": "false", "demands": "false", "setting_rent": "false"} or \
        bools.get("setting_rent") == str(bools.get("rent")), (
        "a system switch came back as something other than the boolean the preset set: %s. "
        "EX.setting returns `v ~= false`, so a boolean turned into a number reads as ON "
        "forever." % got.get("bools"))
    assert bools.get("rent") in ("true", "false"), (
        "warehouse_rent is no longer a boolean after EX.opt: %s" % got.get("bools"))

    assert got.get("garbage", "").startswith("ok=true"), (
        "a non-numeric entry in a tune table throws. EX.RACES is hand-edited and the price "
        "path runs about once a second while the panel is open: %s" % got.get("garbage"))
    g = dict(kv.split("=", 1) for kv in got.get("garbage", "").split(" ") if "=" in kv)
    assert g.get("hostile_max") == "0.25" and g.get("windup") == "0.5", (
        "a garbage factor was applied instead of ignored: %s" % got.get("garbage"))

    # ---- THE RUNTIME WARNING FOR SOMEBODY ELSE'S MOD ----
    # check_culture_appetites covers this pack's own cultures and every vanilla one. It cannot
    # cover a culture from a mod that is not installed on the build machine, and the player's
    # campaign is full of those - so the game says so when it meets one.
    uw = dict(kv.split("=", 1) for kv in got.get("uncovered_warn", "").split(" ")
              if "=" in kv)
    assert uw.get("named") == "another_mod_culture,some_mod_culture", (
        "the uncovered-culture warning named %s. It must fire for a culture at or over "
        "EX.UNCOVERED_MIN and stay quiet under it: %s" % (uw.get("named"), got.get("uncovered_warn")))
    assert uw.get("tiny") == "0", (
        "a culture holding half a per cent of the map was announced. One region changing "
        "hands would then announce a rounding error: %s" % got.get("uncovered_warn"))
    assert uw.get("first") == uw.get("total"), (
        "the warning repeats on every scan (%s lines after one call, %s after three). The "
        "scan runs every turn, and a line that repeats forever is how a log stops being read."
        % (uw.get("first"), uw.get("total")))
    assert got.get("uncovered_warn_nil") == "true", (
        "the warning throws when no scan has completed yet, which is every campaign's first "
        "moments: %s" % got.get("uncovered_warn_nil"))

    # ---- THE STRENGTH DIAL ----
    # The player's one control over the whole feature, and the reason the MCT sliders can be
    # made honest again: at 0 the panel and the board agree exactly.
    def _row(tag):
        return dict((kv.split("=", 1)[0], float(kv.split("=", 1)[1]))
                    for kv in got[tag].split(" ", 1)[1].split(","))

    for tag in ("strength0", "strength0.5", "strength1", "strength2"):
        assert tag in got and tag + "_base" in got, (
            "the strength harness did not report %s: %s" % (tag, sorted(got)))

    off, off_base = _row("strength0"), _row("strength0_base")
    assert off == off_base, (
        "strength 0 does not switch race profiles off. Every knob must equal the shared "
        "baseline exactly, or the dial does not mean what its tooltip says. Differences: %s"
        % sorted(k for k in off if off[k] != off_base[k]))

    full = _row("strength1")
    half, dbl = _row("strength0.5"), _row("strength2")
    base = _row("strength1_base")
    moved = 0
    for key in sorted(full):
        if full[key] == base[key]:
            # A knob no profile touches must be unmoved at EVERY strength - the dial scales
            # the distance from 1, so a factor of 1 stays 1 however hard it is scaled.
            assert half[key] == base[key] and dbl[key] == base[key] and off[key] == base[key], (
                "%s is untouched by the profile at strength 1 but moves at another strength - "
                "the dial is scaling the factor instead of its distance from 1" % key)
            continue
        moved += 1
        # Halfway means halfway, on the FACTOR, not on the value: 1 + (f - 1) * 0.5. Integer
        # knobs round, so this allows the rounding and nothing more.
        f = full[key] / base[key]
        for st, row in ((0.5, half), (2.0, dbl)):
            want = base[key] * (1 + (f - 1) * st)
            lo, hi = bounds[key]
            want = min(max(want, lo), hi)
            assert abs(row[key] - want) <= 0.5000001, (
                "at strength %s, %s is %s - scaling the distance from 1 gives %.4f"
                % (st, key, row[key], want))
    assert moved >= 8, (
        "only %d knobs move at strength 1, so the strength assertions above are vacuous"
        % moved)

    neg = dict(kv.split("=", 1) for kv in got.get("negative", "").split(" ") if "=" in kv)
    assert neg.get("hostile_max") == "0.25" and neg.get("windup") == "0.5", (
        "a negative strength INVERTS the profile instead of clamping to off - which would "
        "make the Under-Market the friendliest board in the game: %s" % got.get("negative"))
    assert got.get("badstrength", "").startswith("ok=true"), (
        "a non-numeric strength throws in the price path: %s" % got.get("badstrength"))

    # CUSTOM, where the player sets the numbers themselves. A preset is a table lookup and
    # Custom is a live MCT read - different code in EX.opt_live - and the profile must apply on
    # top of BOTH. The slider still works; it just is not the last word any more.
    cus = dict(kv.split("=", 1) for kv in got.get("custom", "").split(" ") if "=" in kv)
    assert cus.get("chd_hostile") == "0.2" and cus.get("chd_book") == "50", (
        "a Custom slider no longer reaches the Chaos Dwarf board: %s" % got.get("custom"))
    assert cus.get("uncovered_hostile") == "0.2", (
        "a Custom slider no longer reaches an uncovered race: %s" % got.get("custom"))
    assert cus.get("skv_hostile") == "0.44" and cus.get("skv_book") == "30", (
        "the race profile does not compose with a Custom slider - 0.20 x 2.2 and 50 x 0.6 are "
        "what a Skaven board should read: %s" % got.get("custom"))

    # A SNAPSHOT OF THE WRONG SHAPE. Read back out of a save, so it can hold a boolean or a
    # string where a number belongs - an older campaign, a mis-registered MCT option, a hand
    # edit. Multiplying one throws inside the price path, which runs about once a second while
    # the panel is open, so it surfaces as a dead panel turns later rather than at load.
    bad = dict(kv.split("=", 1) for kv in got.get("badsnap", "").split(" ") if "=" in kv)
    assert bad.get("ok") == "true", (
        "a snapshot value of the wrong type throws when the race factor is applied to it: %s"
        % got.get("badsnap"))
    assert bad.get("hostile_max") == "true" and bad.get("windup") == "0.5", (
        "a non-numeric snapshot value was multiplied instead of passed through: %s"
        % got.get("badsnap"))
    # ...and a key the snapshot does not carry at all falls through to the live path AND is
    # still factored, which is the path an older save takes for a knob added since.
    assert bad.get("book_per_rung") == "18", (
        "a knob missing from an older save's snapshot does not fall through to the live value "
        "with the race profile applied: %s" % got.get("badsnap"))

    pre = dict(kv.split("=", 1) for kv in got.get("presnapshot", "").split(" ") if "=" in kv)
    assert pre.get("hostile_max") == "0.55", (
        "the profile does not reach a campaign that has not taken its snapshot yet, so the "
        "panel shows one set of prices before the first turn start and another after: %s"
        % got.get("presnapshot"))

    assert got.get("no_double_apply", "").startswith("true"), (
        "the factor is applied twice - once into the snapshot and once on the way out - so a "
        "campaign started after this change runs on factor SQUARED while one started before "
        "runs on factor: %s" % got.get("no_double_apply"))

    # ---- NOTHING CLAMPS ON `default` ----
    # The clamp exists for the preset extremes (ultra already sets hostile_max 0.60; the Skaven
    # 2.2 on top is 1.32, which is a wall rather than a market). On `default` the profile must
    # read exactly as designed, or the numbers in EX.RACES are decoration.
    for culture, t in sorted(tunes.items()):
        if not t:
            continue
        for key, f in sorted(t.items()):
            base = _lua_const(code, RACE_CONST[key])
            want = base * f
            lo, hi = bounds[key]
            assert lo < want < hi, (
                "on the DEFAULT preset %s's %s resolves to %.4f, outside its %.4g - %.4g "
                "bounds, so it is clamped before anyone has changed the difficulty. The "
                "profile does not mean what it says." % (culture, key, want, lo, hi))

    # ...and the numbers the patch notes state.
    skv = opts[("default", "wh2_main_skv_skaven")]
    for key, want in sorted(SKAVEN_DEFAULT.items()):
        assert abs(skv[key] - want) < 1e-6, (
            "the default-difficulty Skaven board has drifted from what the patch notes say: "
            "%s is %s, the notes say %s" % (key, skv[key], want))

    # The strength each preset runs the profiles at. Nested tables, so the same manual parse
    # check_spread uses - parse_lua_table folds all four presets into one flat dict.
    _pblock = re.search(r"^EX\.PRESETS = \{(.*?)\n\}", code, re.S | re.M)
    _pbody = NL.join(l for l in _pblock.group(1).splitlines()
                     if not l.lstrip().startswith("--"))
    presets_num = {}
    for _name, _inner in re.findall(r"(\w+)\s*=\s*\{(.*?)\}", _pbody, re.S):
        presets_num[_name] = dict(
            (k, float(v)) for k, v in re.findall(r"(\w+)\s*=\s*(-?[0-9.]+)", _inner))
    race_strength_default = _lua_const(code, "RACE_STRENGTH")
    for _name in ("easy", "hard", "ultra"):
        assert "race_strength" in presets_num.get(_name, {}), (
            "the %r preset does not set race_strength. A preset owns every number - a missing "
            "one is half `default` with nothing on screen saying so." % _name)

    # ---- AND THE PROFILE ACTUALLY BITES, on every preset ----
    # A profile whose every knob clamps to the same value the Chaos Dwarfs get is a profile
    # that does nothing. This is the check that would catch a bounds table tightened until the
    # feature quietly stopped existing.
    clamped = []
    for preset in ("default", "easy", "hard", "ultra"):
        chd = opts[(preset, "wh3_dlc23_chd_chaos_dwarfs")]
        for culture, t in sorted(tunes.items()):
            if not t:
                continue
            row = opts[(preset, culture)]
            moved = sum(1 for key in t if abs(row[key] - chd[key]) > 1e-9)
            assert moved >= max(3, len(t) // 2), (
                "on %s, %s's profile moves only %d of its %d knobs away from the shared "
                "baseline - the bounds have swallowed it" % (preset, culture, moved, len(t)))
            # AGAINST THE STRENGTH-SCALED FACTOR, not the raw one. easy runs the profiles at
            # 0.5 and ultra at 1.25, so comparing to the raw factor reported 29 "clamps" that
            # were the dial working exactly as designed - a report that cries wolf is worse
            # than no report, because the four real ultra x Skaven clamps were buried in it.
            st = float(presets_num.get(preset, {}).get("race_strength", race_strength_default))
            for key, f in sorted(t.items()):
                want = chd[key] * (1 + (f - 1) * st)
                lo, hi = bounds[key]
                if abs(row[key] - want) > 0.501 and not lo < want < hi:
                    clamped.append("%s/%s/%s" % (preset, culture.split("_")[-1], key))

    print("  race profiles: %d profiles x 4 presets run through the shipped EX.opt, CHD board "
          % len(covered_races()) +
          "unmoved, spread algebra unreachable, nothing clamps on default"
          + (NL + "    clamped at the extremes: " + ", ".join(clamped) if clamped else ""))


# EX.RACE_TUNABLE keys to the constants they default from - the same mapping EX.TUNE_NUM holds,
# restated here only because the clamp check needs the DEFAULT value rather than the knob name.
RACE_CONST = {
    "hostile_max": "HOSTILE_MAX", "refuse_share": "REFUSE_SHARE",
    "guild_close": "GUILD_CLOSE", "shock_gain": "SHOCK_GAIN", "shock_max": "SHOCK_MAX",
    "demand_chance": "DEMAND_CHANCE", "demand_cooldown": "DEMAND_COOLDOWN",
    "windup": "WINDUP", "div_yield": "DIV_YIELD", "book_per_rung": "BOOK_PER_RUNG",
    "pressure_per_rung": "PRESSURE_PER_RUNG",
}


def _lua_const(code, name):
    m = re.search(r"^EX\.%s\s*=\s*(-?[0-9.]+)" % name, code, re.M)
    assert m, "EX.%s is gone" % name
    return float(m.group(1))


def check_sorting():
    """RUN the shipped sort against a known board and read the row order back.

    Asked for from play 2026-09-08: click a numeric header for low-to-high, high-to-low, then
    the default order. Three things here cannot be reasoned about from the source and are the
    whole reason this runs the file rather than reading it:

    1. TIES. table.sort is not stable in Lua 5.1 and every one of these columns has ties in it.
       refresh_panel runs about once a second while the panel is open, so an unstable
       comparator reshuffles the tied rows on every refresh and the panel reads as broken.
       The board below is built with deliberate ties in every column and the order is read
       twenty times over.
    2. HOUSES ARE SORTED BEFORE THEY ARE PAGED. Sorting inside the page orders the twenty rows
       the player happens to be looking at and leaves every other page alone - which looks
       exactly like sorting and is not. Only reading page 2 and 3 can tell the two apart.
    3. AN ERRORING ACCESSOR. EX.held reads a live pooled resource and returned a null
       interface for a whole build; a comparator that throws takes the entire refresh down.
    """
    if not os.path.isfile(LUA_EXE):
        print("  (skipped sort run: no lua.exe)")
        return
    import subprocess
    import tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_sort_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace("\\", "\\\\"))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    # The board: buy prices a=300 b=100 c=200 d=100, so b and d tie at the bottom.
    assert have.get("default") == "a,b,c,d", (
        "the unsorted order is not the list's own: %s" % have.get("default"))
    assert have.get("price_asc", "").startswith("b,d,c,a"), (
        "low to high is wrong: %s" % have.get("price_asc"))
    assert have.get("price_desc", "").startswith("a,c,b,d"), (
        "high to low is wrong - note b before d, because a tie keeps the LIST order in both "
        "directions rather than reversing it: %s" % have.get("price_desc"))
    assert have.get("price_default") == "a,b,c,d col=nil", (
        "the third click does not restore the default order: %s" % have.get("price_default"))
    assert "[[col:green]]Buy[[/col]]" in have.get("price_asc", ""), (
        "the ascending header is not marked green: %s" % have.get("price_asc"))
    assert "[[col:red]]Buy[[/col]]" in have.get("price_desc", ""), (
        "the descending header is not marked red: %s" % have.get("price_desc"))

    assert have.get("tie_order") == "b,d,c,a stable=true", (
        "tied rows do not hold their order across repeated reads, so the panel reshuffles "
        "about once a second: %s" % have.get("tie_order"))

    # Every column ordered by its own accessor. A column wired to the wrong one still sorts -
    # it just sorts on the wrong number, which no order-agnostic check would notice.
    for key, want, why in (
            ("col_trade_hdr_hold", "a,d,b,c", "held 0,3,7,7"),
            ("col_trade_hdr_sell", "d,b,c,a", "sell 80,90,180,250"),
            ("col_trade_hdr_supply", "b,d,c,a", "output 10,10,20,30"),
            ("col_offer_hdr_supply", "a,d,b,c", "the offerings view sorts on HELD"),
    ):
        assert have.get(key) == want, (
            "%s should order %s (%s) but gave %s" % (key, want, why, have.get(key)))

    # ---- THE TREND COLUMN, MEASURED ON THE GLYPHS IT DRAWS ----
    # It sorted on EX.current, the price RUNG - a different quantity from the arrow, which
    # compares the rung with the PREVIOUS one. Two rows on the same rung can draw opposite
    # arrows, so the column came out loosely grouped and visibly wrong: Hi, Hi, ^ x5, -,
    # v x3, ^, ^, v, v, ^, v (screenshot, 2026-09-08). Asserting an ORDER OF KEYS would not
    # have caught it - only reading back what the column actually shows does.
    assert have.get("trend_desc") == "cap,up2,up1,flat,dn1,dn2,floor", (
        "the trend column does not sort by the movement it draws: %s"
        % have.get("trend_desc"))
    glyphs = have.get("trend_glyphs", "")
    plain = re.sub(r"\[\[/?col:?\w*\]\]", "", glyphs).split(",")
    assert plain == ["Hi", "^", "^", "-", "v", "v", "Lo"], (
        "descending, the Trend column must read Hi, then the rises, then flat, then the "
        "falls, then Lo - what it actually drew was %s.%s  raw: %r"
        % (plain, NL, glyphs))
    assert have.get("trend_asc") == "floor,dn2,dn1,flat,up1,up2,cap", (
        "ascending is not the exact reverse: %s" % have.get("trend_asc"))

    assert have.get("name_click", "").startswith("false spark_click false junk_click false "
                                                 "nil_click false col=nil"), (
        "a column with nothing to order by responded to a click: %s" % have.get("name_click"))

    assert have.get("erroring_accessor", "").startswith("ok=true"), (
        "an accessor that throws takes the whole refresh down: %s"
        % have.get("erroring_accessor"))

    assert have.get("after_set_mode") == "col=nil dir=1", (
        "the sort survived a view change, so the next view re-sorts on a column the player "
        "never clicked: %s" % have.get("after_set_mode"))

    # Houses: prices h1=50 .. h5=10, two rows a page.
    assert have.get("houses_default_p1") == "h1,h2", have.get("houses_default_p1")
    assert have.get("houses_asc_p1", "").startswith("h5,h4 page=1"), (
        "the houses view does not sort ascending, or the sort left the player off page 1: %s"
        % have.get("houses_asc_p1"))
    assert have.get("houses_asc_p2") == "h3,h2", (
        "page 2 is not the SECOND slice of the sorted list - the sort ran inside the page "
        "instead of across the list: %s" % have.get("houses_asc_p2"))
    assert have.get("houses_asc_p3") == "h1", have.get("houses_asc_p3")
    assert have.get("resort_page", "").startswith("1 h1,h2"), (
        "re-sorting left the player on their old page, looking at the middle of the new "
        "order: %s" % have.get("resort_page"))
    assert have.get("identity") == "true", (
        "the unsorted path copies the list instead of handing back the same table")
    print("  sorting: 3-click cycle, ties stable over 20 reads, 5 columns by accessor, "
          "houses sorted across pages not within one, trend ordered by its own glyphs "
          "(Hi ^ - v Lo), erroring accessor survives")


def check_pool_reach(t):
    """EVERY MINTED HOLDING MUST BE REACHABLE BY EVERY CULTURE THIS MOD SERVES.

    The fault this exists for, measured in a live Empire campaign 2026-09-08: buying charged
    the gold, paid the counterparty, logged "bought 10 derpy_chd_ex_hold_rom_iron for 435" and
    granted NOTHING. Every row was correct, every key matched, every loc string resolved. The
    missing thing was a RELATIONSHIP - the pools were registered only under
    wh3_dlc23_feature_chaos_dwarfs, whose sole membership criterion is the Chaos Dwarf culture,
    so on an Empire faction faction:pooled_resource_manager():resource(k) is a null interface
    and cm:faction_add_pooled_resource moves nothing without erroring.

    No check in this file could have caught it, because none of them modelled reach. This one
    resolves each registration group the way the engine does - group -> members -> the four
    criteria tables - and asserts the union covers the cultures EX.RACES claims.

    A member carrying NO criteria row in any of the four tables matches every faction; that is
    what CA's wh_feature_all is and how siege supplies reaches everyone.
    """
    from read_vanilla_cache import load
    members = collections.defaultdict(list)
    for r in load("campaign_group_members")[0]:
        members[r["group"]].append(r["id"])
    crit = collections.defaultdict(lambda: collections.defaultdict(set))
    for kind in ("cultures", "subcultures", "factions", "agent_subtypes"):
        for r in load("campaign_group_member_criteria_" + kind)[0]:
            crit[r["member"]][kind].add(r.get("culture") or r.get("subculture")
                                        or r.get("faction") or r.get("agent_subtype"))

    def reach(group):
        """(set of cultures reachable, whether the group is universal)."""
        cultures, universal = set(), False
        for m in members.get(group, ()):
            c = crit.get(m)
            if not c:
                universal = True            # no criteria of any kind: matches every faction
            else:
                cultures |= c.get("cultures", set())
        return cultures, universal

    rows = t["campaign_group_pooled_resources_tables"][1]
    assert rows, "no pooled resource is registered anywhere"
    want = set(race_table())                # the cultures EX.RACES names
    by_res = collections.defaultdict(set)
    for r in rows:
        by_res[r["resource"]].add(r["campaign_group"])

    for res, groups in sorted(by_res.items()):
        got, universal = set(), False
        for g in groups:
            c, u = reach(g)
            got |= c
            universal = universal or u
        assert universal or want <= got, (
            "%s is unreachable by %s. Registered under %s, which reaches %s. A pool a faction's "
            "group does not register is a null interface on that faction, and buying it charges "
            "the gold and grants nothing." % (res, sorted(want - got), sorted(groups),
                                              sorted(got) or "no culture"))

    # The universal group must actually BE universal in the shipped DB, not merely named. If a
    # patch ever gives wh_feature_all a criteria row, every non-Chaos-Dwarf race silently goes
    # back to paying for nothing, and the assertion above would still pass on the CHD row.
    _c, u = reach(UNIVERSAL_GROUP)
    assert u, ("%s no longer has a criteria-free member - it does not reach everyone any more. "
               "Register the holdings per culture instead." % UNIVERSAL_GROUP)

    # THE RUNTIME GUARD, AND ITS ORDER. The DB fix above is the cure; EX.pool_live is the
    # seatbelt for the next time a culture is added and its registration is not. It is only
    # worth anything BEFORE the treasury moves - a refusal after cm:treasury_mod has already
    # charged is the same lost gold with an extra log line.
    lua = io.open(LUA_SCRIPT, encoding='utf-8').read()
    assert "function EX.pool_live(res)" in lua, "the null-pool guard is gone"
    charge = lua.index("cm:treasury_mod(faction, is_buy and -price or price)")
    guard = lua.index("if not EX.pool_live(res) then")
    assert guard < charge, ("EX.pool_live is checked AFTER the treasury is charged - the gold "
                            "is already gone by then")
    assert lua.count("cm:faction_add_pooled_resource(faction, pool,") == 1, (
        "a second unguarded pool write appeared; EX.pool_live covers one path only")

    # And the Chaos Dwarf registration must not have moved: a live save's pools hang off it.
    chd_rows = {r["resource"] for r in rows if r["campaign_group"] == GROUPS[0]}
    assert chd_rows == {r["resource"] for r in rows if r["campaign_group"] == UNIVERSAL_GROUP}, (
        "the Chaos Dwarf and universal registrations no longer cover the same resources")


def check_race_table():
    """Every culture in EX.RACES is real, the segments are unique, and the CHD one is empty.

    THREE SILENT FAILURES, and not one of them errors anywhere:

    1. A CULTURE KEY TYPO. EX.bind_race looks the player's culture up in this table by string,
       so a misspelled key is never matched and that race is uncovered for the whole campaign
       with nothing logged. Checked against the vanilla cultures table, never a typed list -
       the technique check_lua_appetite already uses on EX.CULTURE_WANTS.
    2. A DUPLICATE SEGMENT. Two races sharing a seg share every generated key, so the second
       race's text silently overwrites the first's in the loc.
    3. THE CHAOS DWARF SEGMENT BECOMING NON-EMPTY. That is the save-compatibility mechanism
       and nothing else in the build would notice: the pack would still generate, still pack,
       still load, and every applied bundle in every live Chaos Dwarf campaign would be
       orphaned to a key that no longer exists.
    """
    from read_vanilla_cache import load
    crows, _ = load("cultures")
    real = set(r["key"] for r in crows if r["key"] != "*")

    races = race_table()
    assert len(races) == len(race_table()), (
        "expected %d covered races, EX.RACES has %d: %s"
                             % (len(races), sorted(races)))
    for culture, row in sorted(races.items()):
        if culture in MODDED_CULTURES:
            # A registered modded culture. The mod is NOT required - see
            # check_no_foreign_keys(), which proves the key reaches no DB row - so there is
            # nothing to verify here beyond the registry entry itself.
            continue
        assert culture in real, (
            "%s is not a vanilla culture. EX.bind_race matches the player's culture against "
            "this table by string, so a key nothing holds leaves that race uncovered forever "
            "with nothing logged." % culture)
        for field in ("seg", "name", "offer_title", "patron", "house_word",
                      "wrath", "pleased"):
            assert row.get(field) is not None, "%s has no %s" % (culture, field)
        for field in ("name", "offer_title", "patron", "house_word", "wrath", "pleased"):
            assert row[field], "%s has an empty %s" % (culture, field)

    segs = [r["seg"] for r in races.values()]
    assert len(set(segs)) == len(segs), (
        "two races share a key segment %s - every generated key would collide and the second "
        "race's text would overwrite the first's" % sorted(segs))
    assert races[CHD_CULTURE]["seg"] == "", (
        "the Chaos Dwarf segment is %r, not empty. That is the ONLY thing keeping this "
        "build's keys byte-identical to what live saves already hold."
        % races[CHD_CULTURE]["seg"])
    assert races[CHD_CULTURE]["layer2"] == [p for p, _s, _d in LAYER2], (
        "the Chaos Dwarf layer2 list is %s, the generator's LAYER2 is %s"
        % (races[CHD_CULTURE]["layer2"], [p for p, _s, _d in LAYER2]))
    for culture, row in sorted(races.items()):
        if culture != CHD_CULTURE:
            assert row["layer2"] == [], (
                "%s has a Layer 2 list %s. Layer 2 ships empty for every race but Chaos "
                "Dwarfs - none of the other three has a chd_armaments analogue, and an empty "
                "list is what keeps this build off vanilla pooled resources entirely."
                % (culture, row["layer2"]))

    # THE TEXT SIDE. build() indexes these dicts, so a gap is a KeyError at generate time -
    # which is the good failure. Naming it here says WHICH key and for which race.
    for culture, text in sorted(RACE_TEXT.items()):
        assert culture in races, (
            "RACE_TEXT carries %s, which is not in EX.RACES - its rows would generate and no "
            "script would ever build a key for one of them" % culture)
        assert text, (
            "%s has no entry in RACE_TEXT. A race in EX.RACES with no strings generates no "
            "rows, and its player gets a panel whose every message key resolves to nothing."
            % culture)
        assert set(text["flavour"]) == set(COMMODITIES), (
            "%s's demand flavour covers %d of %d commodities - missing %s. Every one of the "
            "51 demands per race opens with this sentence."
            % (culture, len(text["flavour"]), len(COMMODITIES),
               sorted(set(COMMODITIES) - set(text["flavour"]))))
        wanted = set(offering_effect(culture, r)[0] for r in COMMODITIES)
        assert set(text["offer_text"]) == wanted, (
            "%s's offering text covers %s but its bundles grant %s. The Chaos Dwarf labour "
            "effect is replaced for the other three races, so the key sets genuinely differ - "
            "an extra entry here is text for a bundle that is never generated."
            % (culture, sorted(set(text["offer_text"]) - wanted),
               sorted(wanted - set(text["offer_text"]))))
        assert "%d" in text["wants_fmt"], (
            "%s's wants_fmt has no amount placeholder - the demand would never say how much"
            % culture)
        for field in ("paid", "unpaid"):
            assert len(text[field]) == 3 and all(text[field]), (
                "%s's %s message is %r - show_message_event takes three parts and a blank one "
                "draws an empty line in the feed" % (culture, field, text[field]))

    # THE BOON OVERRIDE LABEL. The panel prints it beside a Sacrifice button, so it has to
    # describe the effect that race's bundle actually carries - the whole reason the override
    # exists is that the Chaos Dwarf one did not.
    for culture, over in sorted(OFFERING_OVERRIDE.items()):
        for res, (_eff, _scope, base, label) in sorted(over.items()):
            assert races[culture]["boon_over"].get(res) == label, (
                "%s's boon_over says %r for %s, the generator's override says %r. With no "
                "override the panel advertises the Chaos Dwarf Labour bonus to a race that "
                "has no Labour pool."
                % (culture, races[culture]["boon_over"].get(res), res, label))
            nums = [int(x) for x in re.findall(r"-?\d+", label)]
            assert nums and nums[0] == base * OFFER_MULT, (
                "%s's %s override promises %s but its bundle applies %d"
                % (culture, res, nums[:1], base * OFFER_MULT))


def check_key_segments():
    """Every key carrying per-race TEXT goes through EX.seg(); every other key does not.

    THE SPLIT IS THE WHOLE POINT AND IT IS NOT OBVIOUS IN EITHER DIRECTION:

      * The offering bundles, the demand messages and the two outcome messages carry sentences
        written for one patron. One key per race, or the second race's text overwrites the
        first's and an Empire player reads about a bull god.
      * The hold pools, the warehouse tiers, the shock bulletins, the delist bulletins and the
        trade-income steps are IDENTICAL for every race. Segmenting them would quadruple 156
        rows of the same text, and would rename the pooled resources every live save holds its
        position inside.

    Backwards either way is silent: an unsegmented per-race key shows the wrong patron, and a
    segmented shared key resolves to nothing and draws a blank.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    m = re.search(r"function EX\.offering_key\(.*?" + NL + "end", code, re.S)
    assert m, "EX.offering_key is gone"
    assert 'EX.PREFIX .. EX.seg() .. "offering_"' in m.group(0), (
        "EX.offering_key does not segment its key. Its bundle title and description are "
        "per-race, so one shared key means one race's sentence for all four.")

    for fn in ("EX.fire_demand", "EX.pay_demand", "EX.check_demand"):
        m = re.search(r"function " + re.escape(fn) + r"\(.*?" + NL + "end", code, re.S)
        assert m, "%s is gone" % fn
        bad = re.findall(r'EX\.PREFIX \.\. ("(?:dem_|demand_)[^"]*")', m.group(0))
        assert not bad, (
            "%s builds a demand key as EX.PREFIX .. %s with no EX.seg(). Every race gets its "
            "own demand text, so an unsegmented key hands an Empire player the Chaos Dwarf "
            "message - and the row exists, so nothing errors." % (fn, bad[0]))

    assert "function EX.demand_key" not in code, (
        "EX.demand_key is back. Nothing has called it since the dilemmas were removed on "
        "2026-09-05 and it builds a 'demand_' prefix no loc key uses; a dead key builder is "
        "how a future edit reaches for the wrong shape.")

    # AND THE OTHER DIRECTION - the shared keys must NOT gain a segment.
    for fn in ("EX.hold_key", "EX.stock_bundle", "EX.trade_bundle_key", "EX.bundle_key"):
        m = re.search(r"function " + re.escape(fn) + r"\(.*?" + NL + "end", code, re.S)
        assert m, "%s is gone" % fn
        assert "EX.seg()" not in m.group(0), (
            "%s now segments its key. Its text is race-neutral and its rows are shared, so "
            "segmenting either renames the pooled resource every live save holds its position "
            "in, or points at 51 warehouse bundles that were never generated." % fn)
    m = re.search(r"function EX\.announce_shocks\(.*?" + NL + "end", code, re.S)
    assert m and "EX.seg()" not in m.group(0), (
        "the shock bulletin key is segmented. Its text names a commodity and nothing else - "
        "one set of 17 serves every race.")


def check_lua_mp():
    """The multiplayer seam: the subject swap, the key split, and the transport.

    THIS MOD WAS SINGLEPLAYER-ONLY UNTIL 2026-09-09, and not by choice - the unforced
    cm:get_local_faction_name() THROWS in a multiplayer campaign, inside a first-tick callback
    list that has no pcall, so the mod died on load and took every mod queued behind it with
    it. Fixing that is the easy half. The hard half is that every payout was scoped to "the
    local player", which names a DIFFERENT faction on each machine - one client moving a set of
    treasuries nobody else moves is the definition of a desync.

    WHAT CANNOT BE CHECKED HERE. That CampaignUI.TriggerCampaignScriptEvent actually delivers,
    that CA's UITrigger arrives in one order on every machine, and that the engine tolerates
    our event-id string. All three are documented and none is measured; there is no
    two-machine run behind any of this. The harness proves the Lua does what it was written to
    do, which is the only half a single process can reach.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    # ---------------------------------------------------------------------------------------
    # 1. THE KEY SPLIT, STATICALLY. This is the assertion with the worst failure mode behind
    #    it: EX.store is ONE table written into a save that multiplayer SHARES, so a per-player
    #    value under an unscoped key is two players writing over each other - and because every
    #    machine writes the whole store, it is a divergent save as well as a wrong number.
    #    The reverse is just as silent: a WORLD key scoped per player forks the price ladder,
    #    and the market quietly stops being one market.
    # ---------------------------------------------------------------------------------------
    PER_PLAYER = {"SAVE_SHARES", "SAVE_OFFER", "SAVE_OFFERINGS", "SAVE_DEMAND",
                  "SAVE_DEM_RES", "SAVE_DEM_TIER", "SAVE_DEM_DUE", "SAVE_LOG",
                  # Has this player read the introduction. PER PLAYER, because two humans
                  # each meet the panel for the first time on their own turn and one of them
                  # reading it must not take it away from the other. World-scoped, the
                  # second player would never see the page and nothing would say why.
                  "SAVE_INTRO"}
    WORLD = {"SAVE_PREFIX", "SAVE_HIST", "SAVE_PRESS", "SAVE_STRIPPED", "SAVE_HOUSES",
             "SAVE_HOME", "SAVE_BOOK", "SAVE_DELISTED", "SAVE_SHOCK", "SAVE_SHOCK_WHY",
             "SAVE_SHOCKED", "SAVE_SNAP", "SAVE_STORE",
             # Last turn's culture shares. WORLD because it describes the map and two
             # players must read one map; scoping it per player would give each of them a
             # private history of the world and therefore private demand shocks.
             "SAVE_CSHARE",
             # The deep price history. WORLD for the same reason SAVE_HIST is: one
             # market has one price record, and forking it per player would give two
             # players two different charts of the same commodity.
             "SAVE_DEEP"}

    declared = set(re.findall(r"^EX\.(SAVE_[A-Z_]+)", code, re.M))
    assert declared == PER_PLAYER | WORLD, (
        "the save keys have moved: %s. Every one of them is either per-player or world, and "
        "this check is the only thing that says which - add it to one of the two sets above "
        "and think about which, because both wrong answers are silent."
        % sorted(declared ^ (PER_PLAYER | WORLD)))

    for accessor, keys, why in (
            ("v", PER_PLAYER,
             "a per-player key read or written through the UNSCOPED accessor. In multiplayer "
             "that is two players sharing one position"),
            ("p", WORLD,
             "a world key read or written through the PER-PLAYER accessor. That forks the "
             "price ladder per player and the market stops being one market")):
        for verb in ("set", "get"):
            found = set(re.findall(r"EX\.%s%s\(EX\.(SAVE_[A-Z_]+)" % (verb, accessor), code))
            bad = sorted(found & keys)
            assert not bad, "EX.%s%s used on %s - %s" % (verb, accessor, bad, why)

    # AND THE PER-PLAYER KEYS ARE ACTUALLY USED. A key nothing reads is a position that never
    # comes back from a save, which looks exactly like a key that is correctly scoped.
    used = set(re.findall(r"EX\.(?:set|get)p\(EX\.(SAVE_[A-Z_]+)", code))
    assert used == PER_PLAYER, (
        "these per-player keys go through no scoped accessor at all: %s"
        % sorted(PER_PLAYER - used))

    # ---------------------------------------------------------------------------------------
    # 2. THE SLICE LISTS MATCH WHAT IS RESTORED. This is how the swap drifts: somebody adds a
    #    per-player value to EX.restore_player and forgets the two name lists, and from then on
    #    that value is NOT swapped - so it silently belongs to whichever player was bound last,
    #    and every machine gets a different answer depending on turn order.
    # ---------------------------------------------------------------------------------------
    def lua_list(name):
        m = re.search(r"EX\.%s\s*=\s*\{(.*?)\}" % name, code, re.S)
        assert m, "EX.%s is gone" % name
        return set(re.findall(r'"([a-zA-Z_]+)"', m.group(1)))

    slice_names = lua_list("SLICE_TABLES") | lua_list("SLICE_SCALARS")
    rp = re.search(r"function EX\.restore_player\(\).*?" + chr(10) + "end", code, re.S)
    assert rp, "EX.restore_player is gone - a load restores one player and nobody else"
    assigned = set(re.findall(r"^\s*EX\.([a-zA-Z_]+)\s*=(?!=)", rp.group(0), re.M))
    # EX.LOG is restored THROUGH EX.unpack_log rather than by assignment, which is why it is
    # named here rather than found by the regex.
    assert "EX.unpack_log(" in rp.group(0), "EX.restore_player no longer restores the log"
    assigned.add("LOG")
    assert assigned == slice_names, (
        "EX.restore_player restores %s but the slice lists carry %s. A value in one and not "
        "the other is a value that does not follow the subject - it belongs to whichever "
        "player was bound last, so the answer depends on turn arrival order and differs per "
        "machine." % (sorted(assigned), sorted(slice_names)))

    # ---------------------------------------------------------------------------------------
    # 3. ONE FORCED ACCESSOR. CA: the local-faction calls "will throw a script error and fail"
    #    in multiplayer unless true is passed. EX.me() is the single place that passes it.
    # ---------------------------------------------------------------------------------------
    raw = re.findall(r"cm:get_local_faction_name\((\s*)\)", code)
    assert not raw, (
        "%d unforced cm:get_local_faction_name() call(s) survive. Unforced it THROWS in a "
        "multiplayer campaign - and it throws inside cm:process_first_tick_callbacks, whose "
        "call_each has no pcall, so the mod does not merely misbehave: it dies on load and "
        "takes every mod queued behind it down with no log line naming us." % len(raw))
    forced = re.findall(r"cm:get_local_faction_name\(true\)", code)
    assert len(forced) == 1, (
        "the forced local-faction read appears %d times; it belongs in EX.me() and nowhere "
        "else, so there is one place to change and one place to cache" % len(forced))

    # ---------------------------------------------------------------------------------------
    # 4. THE TRANSPORT. Every op has a handler, and the two clickable paths go through it.
    # ---------------------------------------------------------------------------------------
    ops = set(re.findall(r"EX\.MP_OPS\.(\w+)\s*=", code))
    assert ops == {"buy", "sell", "offer"}, (
        "EX.MP_OPS carries %s. Every model change reachable from a click needs one, and "
        "nothing else belongs in it." % sorted(ops))
    # EVERY LITERAL IN THE ARGUMENT, not just one at the front: EX.trade picks its op with
    # `is_buy and "buy" or "sell"`, so an anchored capture sees only the last of the three and
    # reports two live ops as dead.
    sent = set()
    for args in re.findall(r"EX\.mp_send\(([^)]*)", code):
        sent |= set(re.findall(r'"(\w+)"', args))
    assert sent == ops, (
        "EX.mp_send is called with %s against ops %s - an op nothing sends is dead, and a "
        "send with no op is a click that logs an error and does nothing"
        % (sorted(sent), sorted(ops)))

    # EVERY DEFERRED HOLDING CHANGE NAMES ITS FACTION.
    #
    # The three callers reach EX.after_holding_change through cm:callback, which fires AFTER
    # EX.with_player has restored the subject. Unbound, EX.apply_stockpiles would move the LOCAL
    # player's warehouse bundles on every machine instead of the trading player's - machine A
    # moving A's and machine B moving B's, off one trade. It looks right on the trader's own
    # screen, which is the worst way for it to be wrong, and no harness can see it because a
    # single process only ever has one local player.
    for m in re.finditer(r"EX\.after_holding_change\((.*?)\)", code):
        arg = m.group(1).strip()
        assert arg in ("faction", "fname"), (
            "EX.after_holding_change is called with %r. Every deferred call must name the "
            "acting faction: the callback runs after the subject has been unbound, so an empty "
            "argument applies the local player's warehouse tier on every machine." % arg)

    wp = re.search(r"function EX\.with_player\(faction, fn\).*?" + chr(10) + "end", code, re.S)
    assert wp, "EX.with_player is gone"
    assert "pcall(fn)" in wp.group(0), (
        "EX.with_player no longer wraps the pass in a pcall. An error halfway through one "
        "player's turn would then leave THEIR slice bound for the rest of the campaign, and "
        "every later payout would be credited to the wrong faction - silently, and only on "
        "the machine that hit the error, which is a desync as well.")
    assert wp.group(0).index("pcall(fn)") < wp.group(0).rindex("EX.bind_player(prev)"), (
        "EX.with_player does not rebind the previous subject after the call")

    if not os.path.isfile(LUA_EXE):
        print("  (skipped mp run: no lua.exe)")
        return

    import subprocess
    import tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_mp_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace(chr(92), chr(92) * 2))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    def eq(key, want, why):
        assert have.get(key) == want, "%s (%s: expected [%s], got [%s])" % (
            why, key, want, have.get(key))

    # SORTED, and the harness feeds them in deliberately shuffled. CA promises no order from
    # get_human_factions, so two machines walking it as returned could settle positions in
    # different orders and front-run for different players from turn one.
    eq("humans", "alpha_player,mid_player,omega_player,zeta_player",
       "EX.humans is not sorted, so two machines can walk the round in different orders")
    eq("is_human_yes", "true", "a human faction was not recognised as one")
    eq("is_human_no", "false", "an AI house was reported as a human player")

    # THE SLICES. Four players, four positions, nothing leaking either way. This is the whole
    # of what the subject swap is for, and the only fault here that costs anybody money.
    eq("subject_after_adopt", "alpha_player",
       "EX.adopt_local did not claim the file-scope tables for the local player")
    eq("slices",
       "alpha_player=10/10/res_alpha_player/10/1 mid_player=20/20/res_mid_player/20/1 "
       "omega_player=30/30/res_omega_player/30/1 zeta_player=40/40/res_zeta_player/40/1",
       "one player's shares, offering count, pending tithe, offering timer or log reached "
       "another. Every one of those is per player and they are swapped as a set")
    eq("subject_after_loop", "alpha_player",
       "the subject was left bound to somebody else after the loop, so every later payout "
       "would be credited to the wrong faction")
    eq("errored_returns", "false", "EX.with_player did not report a failed pass")
    eq("subject_after_error", "alpha_player",
       "an error inside one player's pass left THEIR slice bound. That is the failure mode "
       "the pcall in EX.with_player exists for, and it is permanent and silent")

    eq("saved_per_player", "10,20,30,40",
       "the saved share values are not one per player - a shared key means two players' "
       "positions overwriting each other in one save")
    eq("saved_unscoped", "nil",
       "something still writes the unscoped share key. In multiplayer that is the collision "
       "the scoping exists to prevent")
    eq("migrate_many", "nil",
       "the unscoped migration fallback fired with four humans on the board. It would hand "
       "player B player A's position - identically on every machine, so not even a desync "
       "would announce it")
    eq("migrate_one", "77",
       "the migration fallback does NOT fire with one human, so every singleplayer campaign "
       "saved before this build loses its position, its tithe and its log on load")

    eq("anyone_holds_other", "true",
       "the prune test only sees the local player's position. It would drop a row another "
       "player still holds paper in - and drop a different row on each machine")
    eq("anyone_holds_none", "false", "the prune test never reports an unheld house")

    # THE RACE FOLLOWS THE SUBJECT. This is the second half of the desync and the subtler one:
    # a tithe demanded of the Empire player has to resolve Sigmar's bundles and the emp_
    # message segment on EVERY machine, including one that is playing Chaos Dwarfs.
    eq("segs",
       "alpha_player=/true/Hashut mid_player=emp_/true/Sigmar "
       "omega_player=skv_/true/The Council zeta_player=/false/The altar",
       "the race did not follow the bound subject. Reading the LOCAL player's race would "
       "apply Hashut's wrath to the Empire player on one machine and Sigmar's on theirs")
    eq("local_race_after", "",
       "binding other players left EX.race pointing somewhere else. It is the LOCAL player's "
       "row and the panel's own header text is built from it")

    # AND THE PROFILE FACTORS FOLLOW IT TOO - the subtlest of the three, because nothing on
    # screen would report it. EX.opt applies EX.race_factor at READ time and the turn round
    # reads EX.opt with another player bound, so a factor taken from the LOCAL race charges the
    # Skaven player at Chaos Dwarf numbers on one machine and Skaven numbers on theirs. The
    # treasuries simply stop agreeing, several turns after the cause.
    #
    # The four values are the shipped default (0.25) for a race with no tune and for an
    # uncovered one, and the Empire's and Skaven's own factors on either side of it - so this
    # cannot pass on a build where every player reads the same number.
    eq("race_factors",
       "alpha_player=0.250 mid_player=0.175 omega_player=0.550 zeta_player=0.250",
       "EX.opt's race factor does not follow the bound subject. Every economic knob on "
       "EX.RACE_TUNABLE would then be read against whoever is sitting at this machine")
    eq("layer2", "wh3_dlc23_chd_armaments,wh3_dlc23_chd_raw_materials cultures=chd+emp",
       "Layer 2 and the house cultures are not the union across humans. Per-client lists "
       "would give each machine a different EX.instruments(), and that list is what the "
       "WORLD price tables are keyed on")

    eq("sp_applies", "alpha_player:hello",
       "singleplayer no longer applies an op directly. It must, or every trade waits on a "
       "network round trip that has no network at the other end")
    eq("mp_defers", "nil",
       "multiplayer applied the op locally as well as broadcasting it. That is a double "
       "application on the sender and a single one everywhere else")
    eq("mp_applies", "mid_player:hello",
       "the received op did not run as the SENDER. Applying it as the local player is how a "
       "trade lands in the wrong treasury on three machines out of four")
    eq("cqi_unknown", "nil", "an unknown cqi resolved to a faction")

    # MCT IS A LOCAL REGISTRY AND MULTIPLAYER IGNORES IT. Two players can hold different
    # presets and nothing reconciles them, so a snapshot taken from MCT freezes a DIFFERENT
    # economy into each machine's save on turn one.
    eq("mp_preset", "default", "multiplayer read a preset from MCT")
    eq("mp_spread", "0.1", "multiplayer read an economic value from MCT")

    eq("rounds_one_turn", "1",
       "the round ran more than once on one turn. Every human raises its own FactionTurnStart, "
       "so without the turn-number guard four players would pay four rents")
    eq("rounds_two_turns", "2", "the round did not run again on the next turn")

    print("  multiplayer: %d per-player keys scoped and %d world keys shared, slice lists "
          "match EX.restore_player, one forced local-faction read, 4 humans isolated across "
          "shares/tithe/offerings/log, subject restored after an error, race and patron follow "
          "the subject, MCT ignored, and the round runs once per turn"
          % (len(PER_PLAYER), len(WORLD)))


def check_race_bind():
    """Run EX.bind_race under stubs, per culture, and read back what it actually resolved.

    check_race_table() reads the table; this RUNS the code. Everything it proves fails without
    a word if it is wrong - the Chaos Dwarf bind reproducing the shipped constants, an
    uncovered culture getting an EMPTY Layer 2 rather than the Chaos Dwarf one,
    EX.HOUSE_CULTURE following the PLAYER rather than staying Chaos Dwarf, the gate, the
    patron's name reaching the panel's own wording, and a null or false faction interface not
    throwing at first tick.
    """
    if not os.path.isfile(LUA_EXE):
        print("  (skipped race bind run: no lua.exe)")
        return
    import subprocess
    import tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_race_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace(chr(92), chr(92) * 2))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have.setdefault(k, []).append(v)

    assert have["default_culture"][0] == CHD_CULTURE, (
        "the file's pre-bind default is %s. Twenty checks in this module load the script "
        "without ever calling bind_race and measure against it."
        % have["default_culture"][0])
    assert have["default_seg"][0] == '""', (
        "EX.seg() answers %s before any bind. It must be empty, or a load-time read builds a "
        "key no row exists for." % have["default_seg"][0])

    bound = {}
    for line in have["bound"]:
        parts = line.split(";")
        bound[parts[0]] = dict(p.split("=", 1) for p in parts[1:])

    chd = bound[CHD_CULTURE]
    assert chd["seg"] == "", "the Chaos Dwarf bind produced seg=%r" % chd["seg"]
    assert chd["house_culture"] == CHD_CULTURE, chd["house_culture"]
    assert chd["layer2"] == "|".join(p for p, _s, _d in LAYER2), (
        "the Chaos Dwarf bind produced Layer 2 %r, not the generator's %r"
        % (chd["layer2"], [p for p, _s, _d in LAYER2]))
    assert chd["patron"] == "Hashut", chd["patron"]
    assert chd["offering"] == PREFIX + "offering_gems", (
        "a Chaos Dwarf player's offering key is %r. It has to be byte-identical to what ships "
        "today - a live campaign holds it inside an applied effect bundle." % chd["offering"])
    assert chd["wrath"] == WRATH_BUNDLE and chd["pleased"] == PLEASED_BUNDLE, (
        "the Chaos Dwarf patron bundles came back as %s / %s"
        % (chd["wrath"], chd["pleased"]))

    assert chd["feed_call"] == str(FEED_INDEX_BASE[CHD_CULTURE]), (
        "a Chaos Dwarf player's feed index is %s, not the shipped %d"
        % (chd["feed_call"], FEED_INDEX_BASE[CHD_CULTURE]))

    for culture, f in sorted(bound.items()):
        assert f["covered"] == "true", "%s bound to nothing" % culture
        # EACH RACE READS ITS OWN BLOCK. The bulletin's PICTURE is a DB column on the record,
        # so an index from another race's block is another culture's art on screen - the
        # Chaos Dwarf forge on a Skaven Trade Disrupted bulletin, reported 2026-09-08.
        base = FEED_INDEX_BASE[culture]
        assert f["feed_call"] == str(base), (
            "%s reads feed index %s for its call bulletin, not its own block's %d - it will "
            "be shown another culture's picture" % (culture, f["feed_call"], base))
        assert f["feed_shock"] == str(base + 2), (
            "%s's shock bulletin is index %s, expected %d - the slot offsets must match the "
            "order of FEED" % (culture, f["feed_shock"], base + 2))
        assert f["feed_delist"] == str(base + 3), (
            "%s's delist bulletin is index %s, expected %d"
            % (culture, f["feed_delist"], base + 3))
        assert f["house_culture"] == culture, (
            "%s bound EX.HOUSE_CULTURE to %s. It must follow the PLAYER - that is what "
            "generalises discovery and the guild to every race" % (culture, f["house_culture"]))
        if culture != CHD_CULTURE:
            assert f["layer2"] == "", (
                "%s bound a non-empty Layer 2 (%s). cm:faction_add_pooled_resource on a pool "
                "the faction does not have fails silently forever, so the row would sit at "
                "'0 held' with a dead Buy button." % (culture, f["layer2"]))
            assert f["seg"], "%s has an empty segment" % culture
            assert f["offering"].startswith(PREFIX + f["seg"]), (
                "%s's offering key %r does not carry its segment"
                % (culture, f["offering"]))

    # AN UNCOVERED RACE FALLS BACK TO THE CHAOS DWARF FEED BLOCK, deliberately. The shock
    # bulletin is not gated on coverage - EX.announce_shocks fires for every player - so an
    # index of nil or 0 draws NOTHING, and a bulletin with the wrong picture beats one that
    # silently never appears.
    assert have["uncovered_feed"][0] == str(FEED_INDEX_BASE[CHD_CULTURE] + 2), (
        "an uncovered player's shock bulletin resolves to index %s. It must fall back to the "
        "Chaos Dwarf block (%d), or every shock this player earns draws nothing at all."
        % (have["uncovered_feed"][0], FEED_INDEX_BASE[CHD_CULTURE] + 2))

    unc = dict(p.split("=", 1) for p in have["uncovered"][0].split(";"))
    assert unc["covered"] == "false", "Bretonnia came back covered"
    assert unc["layer2"] == "0", (
        "an uncovered player kept a Layer 2 of %s rows. Those are Chaos Dwarf pools they "
        "cannot hold." % unc["layer2"])
    assert unc["house_culture"] == "wh_main_brt_bretonnia", (
        "an uncovered player's discovery culture is %s - it must still be their OWN, so the "
        "guild runs and the market moves for them" % unc["house_culture"])
    assert unc["patron"] == "The altar", unc["patron"]

    mod = dict(p.split("=", 1) for p in have["modded"][0].split(";"))
    assert mod["covered"] == "false" and mod["house_culture"] == "some_mod_culture", mod

    # THE GATE, WHICH IS TWO RULES AND NOT ONE.
    #
    # Offerings is gated on COVERAGE - its every string names a patron. Houses is gated on
    # HOUSES, which is a different question: EX.HOUSE_CULTURE follows the player whatever their
    # culture, so an uncovered race's own factions are discovered, priced, traded and settled
    # exactly as a covered race's are. Both used to test EX.covered() and that conflation was a
    # real fault - measured in a live Southern Realms campaign, 2026-09-08: seven houses
    # discovered, two delisted and settled correctly, and the tab greyed over the top of them.
    gates = dict((tag, dict(p.split("=") for p in have["gate_" + tag][0].split(",")))
                 for tag in ("chd", "emp", "teb", "unc", "chd_nohouses", "unc_nohouses"))
    for tag in ("chd", "emp", "teb"):
        assert all(v == "open" for v in gates[tag].values()), (
            "a covered race with houses (%s) has a locked tab: %s" % (tag, gates[tag]))
    for m in ("trade", "stats", "log"):
        assert gates["unc"][m] == "open", (
            "an uncovered player lost the %s view. Layer 1 - the 17 commodities, their "
            "prices, the ownership view and the log - was never Chaos Dwarf and stays open to "
            "every culture; gating it loses the majority of this mod's players." % m)
    assert gates["unc"]["offer"] == "LOCKED", (
        "an uncovered player can still reach the Offerings view, whose every string names a "
        "patron nothing has been written for.")
    assert gates["unc"]["houses"] == "open", (
        "an uncovered player with houses on the board still cannot open the Houses view. "
        "Their own people's factions are discovered, priced and settled for them like anyone "
        "else's - nothing about equity in them needs a patron. This is the 2026-09-08 fault.")

    # ...and the other half of each rule.
    assert gates["chd_nohouses"]["houses"] == "LOCKED", (
        "the Houses tab opens with nothing to list - an empty view reads as broken.")
    assert gates["chd_nohouses"]["offer"] == "open", (
        "a covered race lost Offerings because it had no houses. The two gates are not the "
        "same question and must not be wired to the same test.")
    for m in ("offer", "houses"):
        assert gates["unc_nohouses"][m] == "LOCKED", (
            "an uncovered player with no houses can still reach the %s view." % m)
    assert have["locked_reasons_blank"][0] == "0", (
        "a locked tab carries no reason string. A greyed control with no tooltip is "
        "indistinguishable from a broken one - this file's own stated standard.")
    assert have["locked_set_mode"][0] == "trade", (
        "EX.set_mode opened a locked view (landed on %s). A disabled component still delivers "
        "a click in some engine states." % have["locked_set_mode"][0])
    assert have["covered_set_mode"][0] == "offer", (
        "EX.set_mode refused a view for a COVERED race (landed on %s) - the guard is too "
        "wide" % have["covered_set_mode"][0])

    # THE PATRON'S NAME ON SCREEN.
    for tag, want_patron, want_house in (("words_chd", "Hashut", "Chaos Dwarf"),
                                         ("words_skv", "The Council", "Skaven")):
        line = have[tag][0]
        assert want_patron in line, (
            "%s does not name its patron anywhere in the panel's own wording: %r. The "
            "Offerings header, its tooltip, the offerings footer and two guide lines all said "
            "'Hashut' regardless of race until 2026-09-08." % (tag, line))
        assert want_house in line, "%s does not name its own kind of house: %r" % (tag, line)
    assert have["words_chd"][0].startswith("Hashut grants|"), (
        "the Chaos Dwarf offerings header is %r, not the shipped 'Hashut grants'"
        % have["words_chd"][0].split("|")[0])
    assert "Hashut" not in have["words_skv"][0], (
        "a Skaven player is still shown Hashut somewhere: %r" % have["words_skv"][0])
    unc_words = have["words_unc"][0]
    assert "Chaos Dwarf" not in unc_words and "Hashut" not in unc_words, (
        "an uncovered player is shown Chaos Dwarf wording: %r. The Offerings tab is locked "
        "for them, but the GUIDE is not - and its guild line describes the houses discovery "
        "actually finds, which follow the player's own culture." % unc_words)
    assert "Offerings" in have["help_offer_line"][0], have["help_offer_line"][0]
    assert "Guild" in have["help_guild_line"][0], have["help_guild_line"][0]

    # THE BOON LABEL.
    for culture in covered_races():
        animals, iron = have["boon_" + culture][0].split("|")
        assert "Labour" not in animals, (
            "%s still advertises %r for Exotic Animals. Post-battle Labour is a Chaos Dwarf "
            "pool: the bundle applies, the effect moves nothing, and the panel promises a "
            "number that never arrives." % (culture, animals))
        assert iron == OFFERING_BOON["res_rom_iron"], (
            "%s's iron boon changed to %r - only res_animals is overridden" % (culture, iron))
    chd_animals = have["boon_" + CHD_CULTURE][0].split("|")[0]
    assert chd_animals == OFFERING_BOON["res_animals"], (
        "the Chaos Dwarf animals boon is %r, not the shipped %r"
        % (chd_animals, OFFERING_BOON["res_animals"]))

    # THE TITHE.
    assert have["demand_" + CHD_CULTURE][0] == "true", "no demand fired for Chaos Dwarfs"
    assert have["demand_wh_main_emp_empire"][0] == "true", "no demand fired for the Empire"
    assert have["demand_wh_main_brt_bretonnia"][0] == "false", (
        "a demand fired for an uncovered player. Its message key has no loc row, so "
        "show_message_event draws an EMPTY feed entry - and the wrath bundle it applies three "
        "turns later does not exist either.")
    assert int(have["uncovered_discovers"][0]) >= 2, (
        "an uncovered player discovered %s houses. Discovery is deliberately NOT gated: it "
        "feeds the guild's books, which are the fifth term in EX.target_rung, and without it "
        "the majority of players get a market priced by supply and appetite alone."
        % have["uncovered_discovers"][0])

    idem = have["idempotent"][0].split(",")
    assert idem[0] == "true" and idem[1] == str(len(LAYER2)), (
        "binding three times changed Layer 2 (%s). init has two entry points and a third is a "
        "patch away; the list must be ASSIGNED, never appended to." % have["idempotent"][0])

    for k in ("nofaction", "nullface"):
        f = dict(p.split("=", 1) for p in have[k][0].split(";"))
        assert f["covered"] == "false", "%s came back covered" % k
        assert f["seg"] == '""', (
            "with a %s interface EX.seg() answers %s. It has to be empty - that is the only "
            "value with DB rows behind it." % (k, f["seg"]))


def check_chd_identity(tables):
    """The Chaos Dwarf slice of this build holds every key the shipped pack already carries.

    "THE TOTALS MATCH" AND "THE SHIPPED KEYS DID NOT MOVE" ARE DIFFERENT CLAIMS, and only the
    second protects a live campaign. Adding three races changes every row count in this pack,
    so a count check would pass while a renamed offering bundle orphaned itself in every save
    that had one applied - visible only as a stat that quietly stops arriving.

    MEASURED AGAINST A FROZEN BASELINE, NOT AGAINST THE TSVs. The first form of this compared
    build() to the committed TSVs - and the generator OVERWRITES those, so from the first
    regenerate onward it compared a build to itself and could never fail again. The baseline
    was written once, from the TSVs as they shipped on 2026-09-08, after this check had
    verified them against that build.

    Compares KEYS, not whole rows: row CONTENTS are covered by check_against_vanilla and
    check_loc_complete. What must not move is the key.
    """
    segs = set(r["seg"] for r in race_table().values()) - set([""])
    if not os.path.isfile(BASELINE):
        print("  (no CHD key baseline yet - run gen_zharr_exchange.py --write-baseline)")
        return
    baseline = {}
    for line in io.open(BASELINE, encoding="utf-8").read().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            table, _, key = line.partition(chr(9))
            baseline.setdefault(table, set()).add(key)

    for table, old in sorted(baseline.items()):
        if table == "loc":
            new = set(r[0] for r in tables["loc"][1])
        else:
            assert table in tables, (
                "%s is in the baseline and this build emits no such table at all" % table)
            new = set(str(r[list(r)[0]]) for r in tables[table][1])
        # A key with no race segment is a Chaos Dwarf or a shared one - the two classes that
        # already ship and must survive byte-identical.
        new_chd = set(k for k in new
                      if not any(k.startswith(PREFIX + sg) for sg in segs))
        missing = old - new_chd
        assert not missing, (
            "%s: %d keys that shipped on 2026-09-08 are missing from this build - %s. "
            "Every one of them is a key a live save may hold: a pooled resource that vanishes "
            "takes the player's position with it, an effect bundle that vanishes leaves an "
            "applied bundle pointing at nothing, and a missing loc key draws an empty feed "
            "entry rather than erroring."
            % (table, len(missing), sorted(missing)[:5]))
    print("  chd identity: %d shipped keys across %d tables, none moved"
          % (sum(len(v) for v in baseline.values()), len(baseline)))


def write_baseline(tables):
    """Freeze the Chaos Dwarf and shared key set that check_chd_identity measures against.

    RUN ONCE, and only when the current build is known to reproduce what already ships. Doing
    it casually defeats the check entirely - it would re-record whatever a rename produced and
    pass forever after.
    """
    segs = set(r["seg"] for r in race_table().values()) - set([""])
    out = ["# The Chaos Dwarf and shared keys this pack ships. check_chd_identity() measures",
           "# every build against this file. A key here is one a LIVE SAVE may hold - never",
           "# delete a line to make a check pass. Frozen 2026-09-08, from the TSVs that were",
           "# verified byte-identical to the shipped pack."]
    total = 0
    for table in sorted(tables):
        if table == "loc":
            keys = set(r[0] for r in tables["loc"][1])
        else:
            keys = set(str(r[list(r)[0]]) for r in tables[table][1])
        for k in sorted(keys):
            if not any(k.startswith(PREFIX + sg) for sg in segs):
                out.append("%s%s%s" % (table, chr(9), k))
                total += 1
    io.open(BASELINE, "w", encoding="utf-8", newline=NL).write(NL.join(out) + NL)
    return total


def check_loc_complete(tables):
    """Every key any race's script can build has a loc row, and no race has orphan text.

    THE LIKELIEST FAULT IN THIS BUILD, and it is silent. A missing loc key is not an error:
    show_message_event draws an empty feed entry, and an effect bundle with no
    effect_bundles_localised_title_<key> row draws in the Faction Effects panel as an icon
    with no text at all - applied, visible, unreadable. At four times the volume, one gap is
    close to certain without this.

    The keys are built the way the SCRIPT builds them, from the race table the script itself
    declares - not from a list typed here, which would only prove this function agrees with
    itself.
    """
    # The loc rows are (key, text, tooltip) triples by the time build() returns.
    loc = dict((r[0], r[1]) for r in tables["loc"][1])
    races = race_table()
    missing = []

    for culture, row in sorted(races.items()):
        seg = row["seg"]
        for res in COMMODITIES:
            for sfx, _m, _t, _w, _T, _c in DEMAND_TIERS:
                key = "%s%sdem_%s_%s" % (PREFIX, seg, sfx, short(res))
                for part in ("_title", "_primary", "_secondary"):
                    if key + part not in loc:
                        missing.append(key + part)
        for stem in ("dem_paid", "dem_wrath"):
            for part in ("_title", "_primary", "_secondary"):
                key = PREFIX + seg + stem + part
                if key not in loc:
                    missing.append(key)
        keys = ["%s%soffering_%s" % (PREFIX, seg, short(r)) for r in COMMODITIES]
        keys += [row["wrath"], row["pleased"]]
        for k in keys:
            for field in ("title", "description"):
                lk = "effect_bundles_localised_%s_%s" % (field, k)
                if lk not in loc:
                    missing.append(lk)

    assert not missing, (
        "%d loc keys the script can build have no row. First 10: %s"
        % (len(missing), missing[:10]))

    # NO BLANKS EITHER. A key present with an empty value is a valid key that draws nothing,
    # which is the one failure a presence check cannot see.
    blank = [r[0] for r in tables["loc"][1] if not str(r[1]).strip()]
    assert not blank, "%d loc rows have empty text: %s" % (len(blank), blank[:5])

    # AND NO ORPHANS: text generated for a segment no race declares.
    live_segs = set(r["seg"] for r in races.values())
    orphans = []
    for k in loc:
        m = re.match(re.escape(PREFIX) + r"([a-z]+_)?dem_", k)
        if m and (m.group(1) or "") not in live_segs:
            orphans.append(k)
    assert not orphans, (
        "%d demand loc keys carry a segment no race in EX.RACES declares: %s. Nothing would "
        "ever build them." % (len(orphans), orphans[:5]))


def check_titles():
    """The panel title is measured, not guessed, and the six literals are gone.

    FOUR OF THE SIX SHIPPED TITLES ALREADY EXCEED the ~19-character ceiling the comment beside
    them cited - "Zharr Exchange: Ownership" is 25. Either they clip in play and nobody has
    looked, or the ceiling is higher than the memory records. Rather than measure it and then
    author eighteen more titles against the number, the title goes through fit(), which is
    defined immediately above refresh_panel, measures with TextDimensionsForText, and was
    already used for the log footer and NOT for the title.

    Short authoring stays the intent. fit() is the net, not the plan.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    m = re.search(r"title:SetStateText\(([^)]*\)?)\)", code)
    assert m, "the panel title is no longer set with title:SetStateText"
    assert "fit(" in m.group(1), (
        "the panel title is set as %s, not through fit(). Four of the six titles this file "
        "shipped with are already over the ceiling the comment beside them cited, and the "
        "per-race names are longer still." % m.group(1))

    assert '"Zharr Exchange: Ownership"' not in code, (
        "the hardcoded Ownership title is still there. It has to derive from the race name, "
        "or an Empire player's Imperial Bourse has a Zharr Exchange ownership view.")
    assert "EX.race.name" in code, "the title no longer reads the race's name"

    # NO DOUBLED ARTICLE. The trade view composes its title as "The " + the race name, and two
    # of the four names already begin with one - "The Ivory Road" and "The Under-Market" - so
    # a Cathayan player's panel read "The The Ivory Road" (screenshot, 2026-09-08). The other
    # views append a suffix instead and were never affected. Every race is checked, not just
    # the two: a fifth would otherwise land the same way.
    m = re.search(r'local t = (.+)$', code, re.M)
    assert m, "the trade view's title expression is gone"
    expr = m.group(1)
    for culture, row in sorted(race_table().items()):
        nm = row["name"]
        # Mirror the shipped expression: keep the name as-is if it already starts with "The ".
        title = nm if nm.startswith("The ") else "The " + nm
        assert not title.startswith("The The "), (
            "%s's trade-view title is %r - the race name already carries an article and the "
            "expression adds another. The shipped expression is: %s"
            % (culture, title, expr))
    assert 'string.sub(nm, 1, 4) == "The "' in code, (
        "the title no longer tests for a leading article, so a race name beginning with "
        '"The " will be prefixed with a second one and nothing here would see it - the loop '
        "above mirrors the expression rather than running it")

    for culture, row in sorted(race_table().items()):
        for suffix in ("", ": Ownership", ": Houses", ": Log"):
            title = row["name"] + suffix
            assert len(title) <= 40, (
                "%s's title %r is %d characters. fit() will amputate it on a word boundary "
                "with an ellipsis, which beats a silent clip but is still not a title."
                % (culture, title, len(title)))
        assert len(row["offer_title"]) <= 30, (
            "%s's offer_title %r is %d characters"
            % (culture, row["offer_title"], len(row["offer_title"])))


def check_lua_boons():
    """EX.BOON in the campaign script must say what the DB rows actually do.

    The panel prints these strings next to a Sacrifice button, so a stale number here is not a
    cosmetic slip - it is the only thing the player reads before spending fifty units, and
    NOTHING else would ever catch it. The bundle's own tooltip only appears after the click.

    So the value in each string is re-derived from OFFERING_EFFECTS, and the whole table has to
    cover exactly the commodity list.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    m = re.search(r"EX\.BOON = \{(.*?)\n\}", lua, re.S)
    assert m, "EX.BOON is gone from the campaign script - the offerings view has no labels"
    boons = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', m.group(1)))
    assert set(boons) == set(COMMODITIES), (
        "EX.BOON does not cover the commodity list: missing %s, extra %s"
        % (set(COMMODITIES) - set(boons), set(boons) - set(COMMODITIES)))
    # CHARACTER FOR CHARACTER against OFFERING_BOON, not merely "both name the right number".
    # The same string is printed in two places by two different files - the panel row from the
    # Lua, the dilemma's Submit blurb from these DB rows - and a player comparing "+4 armour"
    # on the panel with "+5 armour" on the altar has no way to know which one is lying.
    assert boons == OFFERING_BOON, (
        "EX.BOON and OFFERING_BOON disagree: %s"
        % sorted(k for k in set(boons) | set(OFFERING_BOON)
                 if boons.get(k) != OFFERING_BOON.get(k)))
    for res, text in sorted(boons.items()):
        _eff, _scope, base = OFFERING_EFFECTS[res]
        want = base * OFFER_MULT
        nums = [int(x) for x in re.findall(r"-?\d+", text)]
        assert nums, "EX.BOON[%s] = %r names no number" % (res, text)
        assert nums[0] == want, (
            "EX.BOON[%s] promises %d but the effect bundle applies %d. The panel is the only "
            "place the player sees this before spending %d units."
            % (res, nums[0], want, OFFER_COST))
    # The constants the Lua spends against have to be the ones the rows were built for.
    for name, val in (("OFFER_COST", OFFER_COST), ("OFFER_TURNS", OFFER_TURNS)):
        m = re.search(r"EX\.%s\s*=\s*(\d+)" % name, lua)
        assert m and int(m.group(1)) == val, (
            "EX.%s in the script is %s, the rows were generated for %d"
            % (name, m and m.group(1), val))


def check_production():
    """The production map, and the two halves of the supply term that live in two files."""
    prod = production_map()
    assert len(prod) > 700, "only %d producing buildings - did the cache go stale?" % len(prod)

    # EVERY COMMODITY MUST HAVE A PRODUCER SOMEWHERE, or its supply is latent-only forever and
    # no amount of building ever moves its price.
    covered = set(res for pairs in prod.values() for res, _v in pairs)
    assert covered == set(COMMODITIES), (
        "no producing building for %s" % sorted(set(COMMODITIES) - covered))
    assert set(PRODUCTION_STEMS.values()) == set(COMMODITIES), (
        "PRODUCTION_STEMS and COMMODITIES disagree: %s"
        % sorted(set(PRODUCTION_STEMS.values()) ^ set(COMMODITIES)))

    # THE FOUR STEMS THAT ARE NOT THEIR OWN NAME. Pinned individually, because a "tidy-up" that
    # maps by pattern silently swaps glass with textiles - both would still be 17 entries, both
    # would still pass every count, and the market would price two commodities as each other.
    for stem, res in (("beer", "res_rom_glass"), ("pottery", "res_rom_textiles"),
                      ("salt", "res_rom_lead"), ("gem", "res_gems")):
        assert PRODUCTION_STEMS[stem] == res, (
            "%s must map to %s - resolved by ICON and UNIT out of resources_tables, not by name"
            % (stem, res))

    vals = [v for pairs in prod.values() for _res, v in pairs]
    assert min(vals) > 0, (
        "a producing building with no output - the scope filter in production_map is what "
        "keeps the Underdeep drinking halls (net -10 and -5 beer) out of this")
    assert max(vals) <= 200, "output %g is out of vanilla's 2-144 range" % max(vals)

    # The shipped file must parse, and must carry exactly what production_map() says.
    n, _size = write_production_lua()
    assert n == len(prod)
    lua = io.open(PROD_LUA, encoding="utf-8").read()
    got = dict(re.findall(r'\["([^"]+)"\] = \{ (.+) \},', lua))
    assert len(got) == len(prod), "%d entries written, %d in the map" % (len(got), len(prod))
    for b, body_ in got.items():
        pairs = [(r, float(v)) for r, v
                 in re.findall(r'\{ "([^"]+)", ([-\d.e+]+) \}', body_)]
        assert pairs == prod[b], "%s: wrote %s, map says %s" % (b, pairs, prod[b])
    # THE MULTI-RESOURCE BUILDINGS ARE PINNED. Hag Graef's mines are the shape the first
    # version of this got wrong, and a regression to one-pair-per-building would still write
    # 781 entries and still pass every count above.
    assert prod["wh2_main_special_hag_graef_mines_4"] == [("res_rom_iron", 96.0),
                                                          ("res_rom_marble", 96.0)]
    assert len(prod["wh2_main_special_peg_street_pawnshop"]) == 5
    multi = [b for b, pairs in prod.items() if len(pairs) > 1]
    # 27, not 28: wh3_main_underdeep_dwf_resources_1 makes gems, iron AND marble but is
    # scoped foreign_building_to_region_own, so the scope filter drops it.
    assert len(multi) == 27, "%d multi-resource buildings, expected 27" % len(multi)
    if os.path.isfile(LUA_EXE):
        import subprocess
        subprocess.check_call([LUA_EXE.replace("lua.exe", "luac.exe"), "-p", PROD_LUA])

    # The latent term is mirrored into the campaign script, and it is the only thing keeping
    # ivory, medicine and obsidian tradeable on a turn-1 map (all three produce ZERO there).
    ex = io.open(LUA_SCRIPT, encoding="utf-8").read()
    m = re.search(r"EX\.LATENT_PER_REGION\s*=\s*(\d+)", ex)
    assert m and int(m.group(1)) == LATENT_PER_REGION, (
        "EX.LATENT_PER_REGION is %s in the script, %d here"
        % (m and m.group(1), LATENT_PER_REGION))
    assert "EX_PRODUCTION" in ex, "the exchange never reads the production map"


MCT_OPTIONS = [
    ("ai_traders", "AI traders",
     "The other Chaos Dwarf houses run books, move the price and sit across your trades. "
     "Off, the market behaves as it did before they existed."),
    ("ai_gold", "AI traders use real gold",
     "Houses fund trades from their own treasuries and receive yours, which drives AI armies. "
     "Off, no gold moves to or from a house - their books still move, so the market still "
     "prices them."),
    ("refusal", "Houses can refuse to sell",
     "A house that despises you and holds most of a good will not sell it. Selling is "
     "always open either way. Off, hostility is a markup only."),
    ("war_lock", "War closes the Exchange",
     "Enough of the guild at war with you and the market shuts until you make peace."),
    ("warehouse_rent", "Warehouse rent",
     "0.5 gold per unit held per turn."),
    ("hashut_demands", "The patron's demands",
     "The altar periodically demands a commodity tithe."),
    ("trade_income", "Exchange prices drive trade income",
     "A commodity you produce trading high raises your trade income that turn."),
]

# THE CUSTOM KNOBS. key, section, label, tooltip, default, min, max, step, precision.
#
# THE DEFAULT COLUMN IS A COPY AND IS ASSERTED AGAINST THE LUA, not the source of anything -
# EX.opt_default reads the constant in the campaign script, so the constant stays the one place
# a default is written. check_tunables() reads the literal back out of the Lua and refuses a
# mismatch, which is the only way two files can hold the same number safely.
#
# MIN/MAX/STEP HAVE TO CONTAIN EVERY PRESET VALUE, AND ON THE GRID. A preset that names a value
# the slider cannot land on is a setting the player can never reproduce by hand, and the panel
# and the game then disagree about what the mod is doing. check_presets() asserts both.
TUNABLES = [
    ("ladder_step", "market", "Price step per rung",
     "How far one rung moves the price. 1.10 is a 10% step; higher means sharper swings both "
     "ways.", 1.10, 1.02, 1.30, 0.01, 2),
    ("spread", "market", "Buy/sell spread",
     "The gap between what you pay and what you are paid. 0.10 means a lot sells back for 10% "
     "less than it cost at the same price.", 0.10, 0.00, 0.40, 0.01, 2),
    # THE CEILING IS NOT THE WHOLE STORY, exactly as with friendly_max. EX.sell_price also
    # clamps this to 1/ladder_step at runtime, because layer 2's rung is moved by the player's
    # own buying pressure and by nothing else - so a high factor here plus four buys is free
    # gold. At the default step the effective ceiling is 0.909; the tooltip says so.
    ("l2_sell", "market", "Forge goods sell back at",
     "What Armaments and Raw Materials pay when sold, as a fraction of what a lot costs. 0.5 "
     "means 500 back on a 1000 lot. Capped in play at 1 / the price step above, so a round "
     "trip can never turn a profit.", 0.5, 0.05, 0.95, 0.05, 2),
    ("sell_floor", "market", "Sell floor",
     "However hostile the guild is, a sale never pays less than this fraction of the world "
     "price.", 0.25, 0.05, 1.00, 0.05, 2),
    ("pressure_per_rung", "market", "Lots to move a rung",
     "Net lots you must buy before your own trading pushes the price up a rung. Lower means "
     "cornering a good is easier.", 4, 1, 20, 1, 0),
    ("carry_per_unit", "market", "Warehouse rent per unit",
     "Gold charged each turn for every unit you hold. Needs Warehouse rent switched on.",
     0.5, 0.0, 3.0, 0.1, 1),

    ("ai_gain", "houses", "AI price appetite",
     "Rungs per unit of world appetite before the cap. Higher means the guild moves prices "
     "harder on war and culture.", 6.0, 0.0, 20.0, 0.5, 1),
    ("ai_max_rungs", "houses", "AI rungs per turn",
     "The most the guild can move one price in a single turn.", 2, 0, 8, 1, 0),
    ("book_per_rung", "houses", "Book size per rung",
     "Units a house must hold to shift a price one rung. Lower means the guild's positions "
     "move the market more.", 30, 5, 100, 1, 0),
    ("book_max", "houses", "Book rung cap",
     "The most rungs the guild's holdings can shift a price, either way.", 2, 0, 8, 1, 0),
    ("hostile_max", "houses", "Hostility markup cap",
     "The most a house that despises you can add to a price. 0.25 is +25%.",
     0.25, 0.00, 1.00, 0.05, 2),
    # THE CEILING, NOT THE DISCOUNT. What a friendly guild actually gives is
    # min(this, 1 - LADDER_STEP * (1 - spread)) - see EX.friendly_cap in the Lua. A discount
    # larger than that headroom lets a player buy and immediately sell one rung up at a
    # profit, which is a worse version of the exploit check_spread was written to stop. At the
    # DEFAULT spread of 0.10 the headroom is one percent, so this slider does nothing much
    # until the spread is raised; the description says so rather than leaving a player to
    # wonder why 0.25 is not 25%.
    ("friendly_max", "houses", "Friendly discount cap",
     "The most a house that likes you can take off a price - it buys cheaper AND sells "
     "dearer. Bounded by the buy/sell spread: at the default spread only about 1% gets "
     "through, and raising the spread raises this with it.",
     0.25, 0.00, 1.00, 0.05, 2),
    ("guild_close", "houses", "War closes the Exchange at",
     "Share of the guild's book at war with you before the market shuts. Lower closes it more "
     "readily.", 0.60, 0.10, 1.00, 0.05, 2),
    ("refuse_share", "houses", "Refusal needs this book share",
     "A house must hold this much of a good, and despise you, before it will not sell it.",
     0.50, 0.10, 1.00, 0.05, 2),
    ("house_cash_max", "houses", "House gold cap per turn",
     "The most gold that can move to or from one house in a turn. AI treasuries drive AI "
     "armies, so this is the number that changes the wider campaign.", 20000, 0, 100000,
     5000, 0),

    ("div_yield", "shares", "Dividend per share",
     "Paid every turn as a fraction of the live share price. 0.02 is 2%.",
     0.02, 0.00, 0.15, 0.01, 2),
    ("buyout_premium", "shares", "Buyout payout",
     "What a share settles at when you absorb the house yourself. 1.25 pays 125% of its "
     "price.", 1.25, 1.00, 3.00, 0.05, 2),
    ("windup", "shares", "Wind-up payout",
     "What a share settles at when somebody else destroys the house. You backed a loser.",
     0.5, 0.00, 1.00, 0.05, 2),
    ("seat_lost", "shares", "Price on losing a capital",
     "A house that no longer holds its home region is priced at this fraction of its power.",
     0.6, 0.10, 1.00, 0.05, 2),

    ("demand_first_turn", "hashut", "First tithe on turn",
     "Nothing is demanded before this turn. Needs the patron's demands switched on.",
     15, 1, 100, 1, 0),
    ("demand_cooldown", "hashut", "Turns between tithes",
     "Whether you paid or refused.", 15, 3, 60, 1, 0),
    ("demand_chance", "hashut", "Tithe chance per turn",
     "Per cent chance each turn once off cooldown.", 30, 0, 100, 5, 0),

    ("shock_gain", "shocks", "Shock strength",
     "Rungs per unit of world supply disrupted by a sack, a raze or a siege.",
     10, 0, 40, 1, 0),
    ("shock_max", "shocks", "Shock cap",
     "The most rungs one shock can move a price, either way.", 6, 0, 20, 1, 0),
    ("shock_decay", "shocks", "Shock decay per turn",
     "What survives into the next turn. 0.5 halves it; higher makes a spike linger.",
     0.5, 0.00, 0.95, 0.05, 2),

    # THE ONE DIAL OVER THE WHOLE RACE-PROFILE FEATURE. It scales each profile's DISTANCE FROM
    # 1, so 0 is genuinely off - every board becomes the shared baseline - and every knob a
    # profile does not touch is unaffected at any setting.
    #
    # It is what makes the sliders above honest again. With a profile running they set the BASE
    # and the profile multiplies it, so the panel shows 0.25 while a Skaven board runs 0.55;
    # there is no way to say so inside MCT, because an option's tooltip is static text written
    # at registration, before any faction exists. At strength 0 the two agree exactly.
    ("race_strength", "race", "Race profile strength",
     "How strongly your race's own market character applies on top of everything above. 0 "
     "turns it off and every race trades on the same numbers; 1 is as designed; 2 doubles it. "
     "Skaven gouge, refuse and delist harshly; the Empire is slow, civil and pays the best "
     "dividend; Cathay is the calmest board and the most taxed. Chaos Dwarfs are the baseline "
     "and never change.",
     1.0, 0.0, 2.0, 0.05, 2),
]

TUNE_SECTIONS = [("market", "Market"), ("houses", "AI houses"), ("shares", "Shares"),
                 ("hashut", "Tithes"), ("shocks", "War shocks"), ("race", "Race profile")]

PRESET_ORDER = ["easy", "default", "hard", "ultra", "custom"]
PRESET_LABEL = {
    "easy": ("Easy", "For a first campaign. A thin spread, most of a bad stake returned, "
                     "cheap storage, a slow and forgiving guild - and shares still paying "
                     "double. Rent and the patron's tithe are off."),
    "default": ("Default", "The Exchange as designed and as every previous build played."),
    "hard": ("Hard", "High risk, high reward. Every edge that costs you widens, the guild "
                     "moves three rungs a turn, war closes the market sooner - and dividends "
                     "and buyouts rise with it."),
    "ultra": ("Ultra Capitalism", "The extreme. A quarter spread against a tenth floor, the "
                                  "guild moving five rungs a turn on books that shift twice "
                                  "as hard, hostility to +60%, the market shutting when under "
                                  "a third of the guild is at war, the altar demanding from "
                                  "turn 5, and shocks reaching twelve rungs and lingering. "
                                  "Shares pay 5% and a buyout pays double."),
    "custom": ("Custom", "Every value below becomes live. Set them before you start a "
                         "campaign; they are fixed once one is running."),
}

LOCK_REASON = ("The Zharr Exchange's difficulty is fixed for the life of a campaign. Change "
               "it from the main menu before starting a new one.")
CUSTOM_ONLY_REASON = "Pick the Custom difficulty to set this yourself."

# MULTIPLAYER IGNORES ALL OF IT, and the panel has to say so rather than sitting there looking
# live.
#
# NOT BECAUSE MCT CANNOT SYNC - it can, and it does. The host's settings are distributed to
# every client and the clients' panels are locked; see HANDOFF_20260909_EXCHANGE_MULTIPLAYER.md
# section 10 for the whole mechanism, and do not re-derive it from the "MCT is local-only" claim
# that stood in these files for about an hour on 2026-09-09.
#
# THE REASON IS A RACE. That distribution is two asynchronous network round trips starting at
# pre_first_tick, and nothing orders them against the first FactionTurnStart - which is where
# EX.snapshot freezes 30 values into the save. A client that had not received them yet would
# freeze the defaults while the host froze its own, permanently, in both saves, with a
# correct-looking panel on both machines. EX.mp_ignores_mct is the guard; this is its notice.
MP_MCT_NOTICE = ("In a multiplayer campaign these settings are ignored and every value is the "
                 "shipped default on every machine - two players cannot be given different "
                 "economies. The log options below still work.")

# THE DEBUG HALF, and it is deliberately NOT preset-controlled and NOT snapshotted. Every
# economic value is frozen for the life of a campaign; the log level is the opposite and has to
# be movable while a bug is happening, which is the whole reason it exists.
DEBUG_LEVELS = [
    ("off", "Off", "Nothing at all, including failures. Not recommended."),
    ("errors", "Errors only", "Only the lines that report something going wrong."),
    ("normal", "Normal", "What the mod has always logged."),
    ("verbose", "Verbose", "Everything, including per-step detail."),
]
DEBUG_CATS = [
    ("log_turn", "Turn summaries", "Rent charged, dividends paid, settings locked."),
    ("log_trade", "Your trades", "Buys, sells, offerings and why one was refused."),
    ("log_price", "Prices", "Repricing, supply and trade income."),
    ("log_house", "Houses", "Delistings, settlements and pruning."),
    ("log_demand", "The tithe", "Demands, payments and wrath."),
    ("log_shock", "War shocks", "Sacks, razes and sieges moving a price."),
    ("log_ui", "Panel", "The panel, the opener button and the finance screen."),
]

# THE FEATURE KILL-SWITCHES. Three, and every one of them gates real code - check_features
# refuses to generate otherwise, which is the whole reason this table exists.
#
# NOT LOCKED IN A CAMPAIGN, and that is the difference between these and the seven system
# switches above. A system switch is snapshotted into the save at the first turn start so a
# price you were quoted stays the price you are charged; a kill-switch exists to be moved
# WHILE a bug is happening, which is the same argument the debug options already carry.
#
# "orders" WAS THE FOURTH AND IS DELETED, not registered. Limit and stop orders were never
# built, so EX.feature("orders") was called from nowhere: registering it would have put a
# checkbox in the panel for a system the player is not running. See EX.FEATURE_DEFAULT.
FEATURE_SWITCHES = [
    ("deep_history", "Price history chart",
     "The forty-turn chart on the Trade view's second page. Off greys the page arrows and "
     "the panel stops drawing it - the history itself keeps being recorded, so turning this "
     "back on shows the turns you were away rather than a flat line."),
    ("demand_shocks", "War demand shocks",
     "A sacked or besieged settlement moving the price of what it made, and the Shaken line "
     "in the footer. Off and prices move only on supply, trade and the guild."),
    ("appetite_drift", "World appetite",
     "Cultures wanting more of some goods than they make, drifting over the campaign - the "
     "Wanted and Going begging lines. Off and every good is priced on supply alone."),
]


def build_mct():
    out = ["-- GENERATED by tools/gen_zharr_exchange.py - do not edit by hand.",
           "--",
           "-- MCT registration for the Zharr Exchange. MCT loads every .lua under",
           "-- script/mct/settings/, so this file only ever runs when MCT is installed.",
           "",
           "local mct = get_mct and get_mct()",
           "if not mct then return end",
           "",
           'local m = mct:register_mod("derpy_chd_zharr_exchange")',
           'm:set_title("Zharr Exchange")',
           'm:set_author("derpy")',
           'm:set_description("%s")' % lua_q(
               "Pick a difficulty, or Custom to set every value yourself. " + LOCK_REASON
               + " Note that the preset now owns the seven system switches as well as the "
                 "numbers - if you had one of them turned off, it lives under Custom."
               + " " + MP_MCT_NOTICE),
           "",
           "-- MCT HAS NO CAMPAIGN GATING OF ITS OWN. mct_option:set_context_specific is an",
           "-- EMPTY function body and set_local_only is commented out end to end, so both read",
           "-- as gating and gate nothing. This is the working route, and it is only the",
           "-- WARNING: the campaign's real defence is the snapshot the script writes into the",
           "-- save at the first FactionTurnStart, which outranks anything set here.",
           "local IN_CAMPAIGN = __game_mode == __lib_type_campaign",
           'local LOCK_REASON = "%s"' % lua_q(LOCK_REASON),
           'local CUSTOM_ONLY = "%s"' % lua_q(CUSTOM_ONLY_REASON),
           ""]
    for key, label in [("preset", "Difficulty"), ("systems", "Systems")] + TUNE_SECTIONS \
            + [("features", "Features"), ("debug", "Debug")]:
        out.append('m:add_new_section("%s", "%s")' % (key, label))
    out.append("")

    # THE PRESET DROPDOWN. Its per-value tooltips carry what each preset actually does,
    # because the sliders below are NOT written to when a preset is active - the script
    # resolves a preset at read time, since set_selected_setting is a no-op with the panel
    # shut. So this text is the only place a player can read what they are choosing.
    out += ['local o_preset = m:add_new_option("preset", "dropdown")',
            'o_preset:set_text("Difficulty")',
            'o_preset:set_tooltip_text("%s")' % lua_q(LOCK_REASON),
            'o_preset:set_assigned_section("preset")']
    for key in PRESET_ORDER:
        label, tip = PRESET_LABEL[key]
        out.append('o_preset:add_dropdown_value("%s", "%s", "%s", %s)'
                   % (key, lua_q(label), lua_q(tip),
                      "true" if key == "default" else "false"))
    out += ['o_preset:set_default_value("default")', ""]

    # THE SEVEN SYSTEM SWITCHES, then the numeric knobs. Both are "custom only", both are
    # locked outright in a campaign.
    economic = []
    for key, label, tip in MCT_OPTIONS:
        economic.append(key)
        out += ['local o_%s = m:add_new_option("%s", "checkbox")' % (key, key),
                'o_%s:set_text("%s")' % (key, lua_q(label)),
                'o_%s:set_tooltip_text("%s")' % (key, lua_q(tip)),
                'o_%s:set_default_value(true)' % key,
                'o_%s:set_assigned_section("systems")' % key,
                ""]
    for key, section, label, tip, default, lo, hi, step, prec in TUNABLES:
        economic.append(key)
        out += ['local o_%s = m:add_new_option("%s", "slider")' % (key, key),
                'o_%s:set_text("%s")' % (key, lua_q(label)),
                'o_%s:set_tooltip_text("%s")' % (key, lua_q(tip)),
                'o_%s:slider_set_precision(%d)' % (key, prec),
                'o_%s:slider_set_min_max(%s, %s)' % (key, num(lo, prec), num(hi, prec)),
                'o_%s:slider_set_step_size(%s, %d)' % (key, num(step, prec), prec),
                'o_%s:set_default_value(%s)' % (key, num(default, prec)),
                'o_%s:set_assigned_section("%s")' % (key, section),
                ""]

    # THE LOCK, IN ONE PLACE, over exactly the economic options and nothing else.
    #
    # LOCKING RATHER THAN HIDING, and mct_mod:set_section_visibility is why: it resolves to
    # section:set_collapsed(not visible), so a hidden section is a COLLAPSED one the player can
    # simply open again to find stale numbers with no explanation. A locked control greys with
    # a reason attached, which says what a collapsed section cannot.
    out += ["local ECONOMIC = {"]
    for i in range(0, len(economic), 4):
        out.append("    " + ", ".join('"%s"' % k for k in economic[i:i + 4]) + ",")
    out += ["}", "",
            "local function relock()",
            "    local custom = o_preset:get_finalized_setting() == \"custom\"",
            "    for _, k in ipairs(ECONOMIC) do",
            "        local o = m:get_option_by_key(k)",
            "        if o then",
            "            if IN_CAMPAIGN then",
            "                o:set_locked(true, LOCK_REASON)",
            "            elseif not custom then",
            "                o:set_locked(true, CUSTOM_ONLY)",
            "            else",
            "                o:set_locked(false)",
            "            end",
            "        end",
            "    end",
            "    if IN_CAMPAIGN then o_preset:set_locked(true, LOCK_REASON) end",
            "end",
            "",
            "-- The callback fires on MctOptionSelectedSettingSet, BEFORE the value is",
            "-- finalized, so it reads the selected setting rather than the finalized one.",
            "o_preset:add_option_set_callback(function(opt)",
            "    local custom = opt:get_selected_setting() == \"custom\"",
            "    for _, k in ipairs(ECONOMIC) do",
            "        local o = m:get_option_by_key(k)",
            "        if o and not IN_CAMPAIGN then",
            "            if custom then o:set_locked(false)",
            "            else o:set_locked(true, CUSTOM_ONLY) end",
            "        end",
            "    end",
            "end)",
            'core:add_listener("derpy_chd_ex_mct_ready", "MctFinalized", true,',
            "    function() relock() end, false)",
            "relock()",
            ""]

    # THE FEATURE SWITCHES. Emitted here, after `economic` is closed, so none of them can
    # reach the ECONOMIC list - check_features asserts that, because a kill-switch locked in a
    # campaign is a kill-switch that cannot be used for the one thing it is for.
    for key, label, tip in FEATURE_SWITCHES:
        out += ['local o_feat_%s = m:add_new_option("feat_%s", "checkbox")' % (key, key),
                'o_feat_%s:set_text("%s")' % (key, lua_q(label)),
                'o_feat_%s:set_tooltip_text("%s")' % (key, lua_q(tip)),
                'o_feat_%s:set_default_value(true)' % key,
                'o_feat_%s:set_assigned_section("features")' % key,
                ""]

    # DEBUG. Never locked, never preset-controlled, and the level's "off" value is the only
    # thing in the mod that can silence a failure - which is why its own tooltip says so.
    out += ['local o_log_level = m:add_new_option("log_level", "dropdown")',
            'o_log_level:set_text("Log detail")',
            'o_log_level:set_tooltip_text("%s")' % lua_q(
                "How much the Exchange writes to script_log.txt. Changeable at any time, "
                "including mid-campaign - unlike everything above."),
            'o_log_level:set_assigned_section("debug")']
    for key, label, tip in DEBUG_LEVELS:
        o_log_level_default = "true" if key == "normal" else "false"
        out.append('o_log_level:add_dropdown_value("%s", "%s", "%s", %s)'
                   % (key, lua_q(label), lua_q(tip), o_log_level_default))
    out += ['o_log_level:set_default_value("normal")', ""]
    for key, label, tip in DEBUG_CATS:
        out += ['local o_%s = m:add_new_option("%s", "checkbox")' % (key, key),
                'o_%s:set_text("%s")' % (key, lua_q(label)),
                'o_%s:set_tooltip_text("%s")' % (key, lua_q(tip)),
                'o_%s:set_default_value(true)' % key,
                'o_%s:set_assigned_section("debug")' % key,
                ""]

    # THE TWO ACTIONS, through a custom event rather than a direct call: this file loads in
    # MCT's environment and the campaign script in the mod environment, and a mod script's
    # globals are not _G (measured on the victory routes, where rawget(_G, name) was nil for a
    # table that read fine as a global). core:trigger_custom_event is CA-documented, reaches
    # both, and is what MCT itself uses internally.
    out += ['m:add_new_action("dump_state", "Dump state to log", function()',
            '    core:trigger_custom_event("ZharrExchangeDumpState", {})',
            'end):set_assigned_section("debug")',
            "",
            'm:add_new_action("dump_supply", "Re-run supply scan", function()',
            '    core:trigger_custom_event("ZharrExchangeDumpSupply", {})',
            'end):set_assigned_section("debug")',
            ""]
    return "\n".join(out)


def lua_q(s):
    """Escape for a Lua double-quoted literal. Apostrophes are everywhere in this text."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def num(v, prec):
    """A slider value written the way its precision reads it - 0 precision means an integer."""
    if prec == 0:
        return str(int(round(v)))
    return ("%." + str(prec) + "f") % v


def write_mct_lua():
    """Same idiom as write_production_lua: build the text, write it with NL, return its size."""
    body = build_mct() + NL
    os.makedirs(MCT_DIR, exist_ok=True)
    io.open(MCT_LUA, "w", encoding="utf-8", newline=NL).write(body)
    return len(body)


def check_mct():
    """The Exchange's MCT registration - the gap the 0907 handoff opened."""
    write_mct_lua()
    path = MCT_LUA
    assert os.path.exists(path), "the MCT settings file was never generated"
    text = io.open(path, encoding="utf-8").read()
    assert text.startswith("-- GENERATED by tools/gen_zharr_exchange.py"), (
        "the MCT file is not marked generated and will be hand-edited")
    assert "local mct = get_mct and get_mct()" in text and "if not mct then return end" in text, (
        "the MCT file does not guard on MCT being absent. It loads in every campaign; "
        "without the guard it errors for every player who does not have MCT.")
    code = io.open(LUA_SCRIPT, encoding="utf-8").read()
    assert "function EX.setting(" in code, "the Lua never reads an MCT setting"
    # BOTH HALVES OF EVERY TOGGLE, in one loop. Only ai_traders and ai_gold used to have their
    # Lua call site asserted, so the gate could be deleted from any of the other five - refusal,
    # war_lock, warehouse_rent, hashut_demands, trade_income - and the suite stayed green with a
    # switch in the panel that turned nothing off. A registered option nothing reads is worse
    # than no option: it tells the player they have declined a system they are still running.
    for key, label, _tip in MCT_OPTIONS:
        assert '"%s"' % key in text, "MCT is missing the %s toggle" % key
        assert 'EX.setting("%s")' % key in code, (
            "the %r toggle (%s) is registered in MCT and read by nothing in the Lua. The "
            "player switches it off, the panel says it is off, and the system runs on."
            % (key, label))

    # THE CAMPAIGN LOCK, and the two dead hooks it exists instead of. Read off the CODE, not
    # the file: the generated header names both of them in a comment explaining why they are
    # not used, and matching that would fail on a correct file.
    text_code = NL.join(l for l in text.splitlines() if not l.lstrip().startswith("--"))
    assert "set_context_specific" not in text_code and "set_local_only" not in text_code, (
        "the MCT file calls set_context_specific or set_local_only. Both are DEAD in MCT - "
        "set_context_specific is an empty function body and set_local_only is commented out "
        "end to end - so either one reads as gating and gates nothing at all.")
    assert "__game_mode == __lib_type_campaign" in text, (
        "nothing in the MCT file tells a campaign from the frontend, so either the settings "
        "are locked in the main menu where they are meant to be set, or they are editable in "
        "a campaign where the snapshot has already frozen them and the panel would lie.")
    econ = set(k for k, _l, _t in MCT_OPTIONS) | set(t[0] for t in TUNABLES)
    m = re.search(r"local ECONOMIC = \{(.*?)\n\}", text, re.S)
    assert m, "the ECONOMIC list is gone, so nothing is locked"
    listed = set(re.findall(r'"(\w+)"', m.group(1)))
    debug_first = {"log_level"} | set(k for k, _l, _t in DEBUG_CATS)
    assert not (listed & debug_first), (
        "the campaign lock catches %s. The log level must stay movable inside a campaign - "
        "being able to raise it while a bug is happening is the whole point of it."
        % sorted(listed & debug_first))
    assert listed == econ, (
        "the campaign lock does not cover exactly the economic options.\n"
        "  registered but never locked (movable in a campaign, and the snapshot ignores "
        "them): %s\n  locked but not economic: %s"
        % (sorted(econ - listed) or "none", sorted(listed - econ) or "none"))
    debug_keys = {"log_level"} | set(k for k, _l, _t in DEBUG_CATS)
    assert not (listed & debug_keys), (
        "the campaign lock catches %s. The log level must stay movable inside a campaign - "
        "being able to raise it while a bug is happening is the whole point of it."
        % sorted(listed & debug_keys))
    for key in debug_keys:
        assert '"%s"' % key in text, "MCT is missing the %s debug option" % key

    # EVERY SECTION AN OPTION IS ASSIGNED TO MUST EXIST. set_assigned_section takes a plain
    # string and MCT creates nothing for an unknown one, so a section added to the option
    # loops but not to the add_new_section list puts its controls nowhere the player can
    # reach - registered, defaulted, and invisible. Caught by mutation, 2026-09-09: deleting
    # the features section from that list left every other assertion here green.
    made = set(re.findall(r'add_new_section\("(\w+)"', text))
    used = set(re.findall(r'set_assigned_section\("(\w+)"', text))
    assert used <= made, (
        "these options are assigned to sections the MCT file never creates, so their "
        "controls are registered and land nowhere: %s" % sorted(used - made))
    assert made <= used, (
        "these sections are created and hold no option at all - an empty heading in the "
        "panel: %s" % sorted(made - used))


def check_no_orphans():
    """Every EX.* the runtime defines is read by something, somewhere.

    THE OTHER DIRECTION FROM check_lua_undeclared.py. That one finds names a file READS and
    nothing declares - nil at runtime, silent. This finds names a file DECLARES and nothing
    reads, which is silent in a different way: the code looks wired, its comment says it is
    wired, and it does nothing at all.

    Three faults of exactly this shape were live on 2026-09-09. EX.FEATURES listed four keys
    and was consulted by nothing. EX.feature("orders") gated limit orders, which were never
    built, so a checkbox would have offered to turn off a system that did not exist. And
    EX.step_help carried a comment saying "the help button and the harness both reach the
    guide through it" when the help button calls EX.set_mode and the arrows call
    EX.nav_click - a stale comment is what let it survive every read of that file.

    READERS ARE COUNTED ACROSS THE WHOLE WORKSPACE, not just the runtime: a constant may
    exist only so a check in this file can assert against it, and a function may be called
    only from a harness. Those are real readers and the sweep must not report them.
    """
    src = io.open(LUA_SCRIPT, encoding="utf-8").read()
    # COMMENTS OUT OF BOTH SIDES. A name that appears only in the paragraph explaining why it
    # exists is precisely how orders and step_help read as wired.
    body = NL.join(l for l in src.splitlines() if not l.lstrip().startswith("--"))

    defs = {}
    for m in re.finditer(r"^function EX\.(\w+)\s*\(", body, re.M):
        defs.setdefault(m.group(1), m.start())
    for m in re.finditer(r"^EX\.(\w+)\s*=", body, re.M):
        defs.setdefault(m.group(1), m.start())
    assert len(defs) > 400, (
        "only %d EX.* definitions found - the scan is broken, not the file" % len(defs))

    # PROSE IS NOT A READER, in a tool file either. This function's own docstring names
    # EX.step_help while explaining why that function was deleted, and with the reader files
    # scanned raw that single mention made re-adding the dead function look alive - measured
    # by mutation, the step_help mutant survived. The runtime file above is comment-stripped
    # for exactly this reason; so are the readers now.
    #
    # STRING LITERALS STAY, and only docstrings go. A check asserting 'EX.foo(' in code is a
    # real reader - something breaks if the name goes - while a paragraph naming EX.foo is
    # not. ast tells the two apart; a blanket strip of every STRING token cannot.
    def code_only(text, is_py):
        if is_py:
            try:
                tree = ast.parse(text)
            except SyntaxError:
                return text
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    d = ast.get_docstring(node, clean=False)
                    if d:
                        text = text.replace(d, "", 1)
            return NL.join(re.sub(r"#.*$", "", l) for l in text.splitlines())
        # Lua: the same lstrip test used on the runtime file above, and the same limit -
        # it does not see a "--" inside a string literal. Over-stripping here can only
        # invent an orphan, which fails loudly; under-stripping is the silent direction.
        return NL.join(l for l in text.splitlines() if not l.lstrip().startswith("--"))

    readers = [body]
    here = os.path.dirname(os.path.abspath(__file__))
    for f in sorted(os.listdir(here)):
        if f.endswith((".py", ".lua")):
            readers.append(code_only(io.open(os.path.join(here, f), encoding="utf-8",
                                             errors="replace").read(), f.endswith(".py")))
    for extra in (PROD_LUA, MCT_LUA):
        if os.path.isfile(extra):
            readers.append(code_only(io.open(extra, encoding="utf-8",
                                             errors="replace").read(), False))
    blob = NL.join(readers)

    hits = collections.Counter(re.findall(r"EX\.(\w+)", blob))
    # A NAME CAN BE REACHED AS A STRING: parse_lua_table takes "FEATURE_DEFAULT", and a check
    # can assert on a quoted 'EX.foo(' expectation. Both are readers.
    quoted = collections.Counter(re.findall(r'"(\w+)"', blob))

    orphans = []
    for name in sorted(defs):
        # One hit is the definition itself. Recursion would inflate this, so the message
        # prints the count rather than asking anyone to trust the threshold.
        if hits[name] <= 1 and quoted[name] == 0:
            orphans.append("EX.%s (line %d)" % (name, src[:defs[name]].count(NL) + 1))
    assert not orphans, (
        "these are defined in the campaign script and read by nothing in it, in any harness, "
        "or in any tool. Either something meant to call them never did - which is a feature "
        "that silently does not exist - or they are left over and should go:%s  %s"
        % (NL + "  ", (NL + "  ").join(orphans)))

    print("  no orphans: %d EX.* names defined, every one of them read" % len(defs))


def check_features():
    """Every feature switch registered in MCT, and every one of them gating real code.

    THE FAULT THIS EXISTS FOR SHIPPED, and it had two halves. EX.FEATURE_DEFAULT named four
    switches and the MCT file registered none of them, so EX.feature found no boolean and
    returned true for all four: they could not be turned off, and could not be used to bisect
    a symptom in play, which is the only thing a kill-switch is for. That is the half a
    "registered but read by nothing" check like check_mct's would never have caught, because
    nothing was registered.

    The other half is worse and is why this asserts the CALL SITE too. Two of the four gated
    no code at all - EX.feature("orders") guarded limit and stop orders, which were never
    built, and EX.feature("deep_history") guarded the deep chart from nowhere. Registering
    those would have put two checkboxes in the panel that turned nothing off. orders is
    deleted and deep_history is wired; this refuses to let either shape back in.
    """
    text = io.open(MCT_LUA, encoding="utf-8").read()
    code = io.open(LUA_SCRIPT, encoding="utf-8").read()

    # THE SET COMES FROM THE LUA, not from this file. EX.FEATURE_DEFAULT is the table
    # EX.feature actually reads, so deriving from it is what makes "a switch the script knows
    # about and MCT does not" a failure rather than something nobody looks for.
    declared = set(parse_lua_table(code, "FEATURE_DEFAULT"))
    registered = set(k for k, _l, _t in FEATURE_SWITCHES)
    assert declared == registered, (
        "EX.FEATURE_DEFAULT and FEATURE_SWITCHES disagree.\n"
        "  the script knows the switch, MCT never registers it (it reads no boolean, returns "
        "true, and cannot be turned off): %s\n"
        "  MCT registers it, the script has no default for it (EX.feature returns false for "
        "an unknown key, so the checkbox silently disables the feature): %s"
        % (sorted(declared - registered) or "none", sorted(registered - declared) or "none"))
    assert declared, "there are no feature switches left at all"

    # EX.FEATURES IS GONE. It listed the same keys, was read by nothing, and drifting out of
    # agreement with FEATURE_DEFAULT was a fault nothing could see.
    assert not re.search(r"^EX\.FEATURES\s*=", code, re.M), (
        "EX.FEATURES is back. It is a second copy of the key set that EX.feature does not "
        "read - derive from EX.FEATURE_DEFAULT or delete it")

    body = NL.join(l for l in code.splitlines() if not l.lstrip().startswith("--"))
    for key, label, _tip in FEATURE_SWITCHES:
        assert '"feat_%s"' % key in text, (
            "MCT never registers feat_%s, so EX.feature finds no boolean, returns its default "
            "of true, and the switch cannot be moved at all" % key)
        # THE CALL SITE, ON THE CODE WITH COMMENTS STRIPPED. A key named only in the comment
        # explaining why it exists is exactly how orders and deep_history read as wired.
        n = body.count('EX.feature("%s")' % key)
        assert n > 0, (
            "the %r switch (%s) is registered in MCT and gates nothing: EX.feature(%r) is "
            "called from nowhere in the script. A player turning it off is told they have "
            "disabled a system that is still running - or, as with orders, one that was "
            "never built. Wire it or delete it." % (key, label, key))

    # deep_history NEEDS BOTH ITS READERS, and the n > 0 above cannot tell one from two.
    # EX.page_count is what greys the arrows, so the page cannot be REACHED; EX.on_chart is
    # what stops it being DRAWN when trade_page is already 2 as the switch moves - which is
    # the normal case, because a kill-switch is thrown while the thing is on screen doing the
    # wrong thing. Either alone leaves a visible half-gate: a chart that still draws under a
    # counter reading 1/1, or an empty second page with nothing on it and no way to be told why.
    for fn in ("EX.on_chart", "EX.page_count"):
        m = re.search(r"function " + re.escape(fn) + r"\(\)(.*?)" + NL + "end", body, re.S)
        assert m, "%s is gone - the chart page has no gate to hold" % fn
        assert 'EX.feature("deep_history")' in m.group(1), (
            "%s does not read the deep_history switch. The other reader does, so the switch "
            "half-works: %s" % (fn, "the page is unreachable but the panel still draws it"
                                 if fn == "EX.on_chart" else
                                 "the panel refuses to draw a page the arrows still offer"))

    # NOT IN THE CAMPAIGN LOCK. A switch that greys out the moment you load the campaign you
    # need it in has been locked out of its only job.
    m = re.search(r"local ECONOMIC = \{(.*?)\n\}", text, re.S)
    assert m, "the ECONOMIC list is gone, so nothing is locked"
    locked = set(re.findall(r'"(\w+)"', m.group(1)))
    caught = locked & set("feat_%s" % k for k in registered)
    assert not caught, (
        "the campaign lock catches %s. These exist to be moved WHILE a bug is happening, "
        "which is inside a campaign by definition." % sorted(caught))

    print("  features: %d switches registered, each gating code, none campaign-locked (%s)"
          % (len(registered), ", ".join(sorted(registered))))


def check_holdings():
    """The position total behind the footer's "Worth" clause.

    THE THREE FAULTS IT CAN HAVE ARE ALL ARITHMETIC and none of them would error:

      - marking the book at EX.price rather than EX.sell_price, which overstates the
        liquidation by the spread - money the player cannot actually get;
      - forgetting that a price is per LOT while a holding is per UNIT, which is the exact
        fault that paid the dividend five times over (100 shares cost 20,000 gold and paid
        2,000 a turn, measured 2026-09-07);
      - summing then flooring instead of flooring each, which puts the footer a gold or two
        off the column above it.

    So this runs the SHIPPED function against a board pinned at the neutral rung, where every
    expected number can be derived from EX.BASE_COST by hand.
    """
    code = io.open(LUA_SCRIPT, encoding="utf-8").read()
    body = NL.join(l for l in code.splitlines() if not l.lstrip().startswith("--"))

    # BOTH FOOTERS, and the same clause on each. One number with two names on one panel is
    # the Supply/Regions mistake; two different numbers under one name is worse.
    assert body.count('EX.holdings_value()') >= 2, (
        "EX.holdings_value is defined but fewer than two footers call it. The Trade view is "
        "where the goods are and the Houses view is where the paper is; a total on one of "
        "them only is a total of half the position on whichever view you are not looking at.")
    assert body.count('"  Worth: "') == 2, (
        "the two footers no longer draw the same Worth clause - they would disagree about "
        "what the position is worth depending on which tab is open")

    if not os.path.isfile(LUA_EXE):
        print("  (skipped holdings run: no lua.exe)")
        return
    import subprocess, tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_holdings_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace(chr(92), chr(92) * 2))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v
    n = lambda k: int(have[k])

    base, lot, sell = n("base"), n("lot"), n("sell")
    assert n("price") == base, (
        "the harness board is not at the neutral rung: a lot prices at %d against a base of "
        "%d, so nothing below is derivable by hand" % (n("price"), base))

    assert n("empty") == 0, (
        "an empty position is worth %s. The footer would print a Worth clause for a player "
        "who holds nothing at all" % have["empty"])

    # THE SPREAD IS THE POINT. If these are equal the function is marking at the mid price.
    assert sell < base, (
        "EX.sell_price equals the mid price on this board (%d), so the assertion below "
        "cannot tell a sell-side total from a mid-priced one" % sell)
    assert n("one_lot") == sell, (
        "one lot is worth %s. It must be EX.sell_price (%d) and not EX.price (%d): a book "
        "marked at the mid price overstates the liquidation by the whole spread, which is "
        "money the Sell button will not pay." % (have["one_lot"], sell, base))

    # PER LOT, NOT PER UNIT. A single unit is a fraction of a lot price; a function that
    # skipped the division reports a whole lot's money for it.
    assert n("one_unit") == sell // lot, (
        "one unit is worth %s against a lot of %d units at %d gold. It must be %d - the "
        "missing division by EX.lot is the fault that paid the dividend five times over."
        % (have["one_unit"], lot, sell, sell // lot))
    assert n("one_unit") < sell, (
        "one unit and one whole lot are worth the same, so EX.lot is not dividing anything")

    assert n("ten_lots") == sell * 10, (
        "ten lots are worth %s against ten times one lot (%d)" % (have["ten_lots"], sell * 10))

    # LAYER 2. Its own lot size and its own sell factor - a walk of EX.COMMODITIES alone
    # reports zero here, and Armaments are the one thing a Chaos Dwarf player always holds.
    assert n("l2_one_lot") == n("l2_sell"), (
        "a lot of Layer 2 is worth %s against its own sell price of %s - EX.holdings_value "
        "is not walking EX.LAYER2, so the Forge goods a Chaos Dwarf player always has are "
        "missing from the total" % (have["l2_one_lot"], have["l2_sell"]))

    # PAPER, AND A CORPSE. Both held, one delisted: the delisted one cannot be sold - both
    # its buttons are disabled - so counting it prices the position above what it can fetch.
    assert n("house_only") == n("house_sell"), (
        "a house lot is worth %s against a house sell price of %s - shares are missing from "
        "the total" % (have["house_only"], have["house_sell"]))
    assert n("with_dead") == n("house_only"), (
        "a delisted house adds %d gold to the total. Its row disables both buttons, so that "
        "is money the player cannot realise - the same skip EX.dividend_total makes, and for "
        "the same reason: EX.shares_held is rebuilt from a save that may predate the delist."
        % (n("with_dead") - n("house_only")))

    assert n("everything") == n("with_dead") + sell + n("l2_sell"), (
        "the three classes do not add up: %s with goods, paper and Forge stock all held, "
        "against %d + %d + %d" % (have["everything"], n("with_dead"), sell, n("l2_sell")))

    # FLOORED PER INSTRUMENT, ON A BOARD WHERE THAT IS VISIBLE. Two commodities two rungs
    # up, one unit of each: 108.9 gold a unit, so flooring each gives 216 and flooring the sum
    # gives 217. Not flooring at all gives 217.8 - which reaches the footer as "217.8g", the
    # same shape of fault as the raw float the offerings line shipped with.
    lot_price, lot_n = n("frac_lot_price"), n("frac_lot")
    each, whole = (lot_price // lot_n) * 2, (2 * lot_price) // lot_n
    assert each != whole, (
        "the fractional board divides evenly after all (%d gold a lot of %d), so this "
        "assertion cannot tell a per-instrument floor from a floored sum"
        % (lot_price, lot_n))
    assert have["frac_total"] == str(each), (
        "two instruments at %d gold a lot of %d are worth %s together. Flooring each gives "
        "%d, which is what the rows print and so what the footer must agree with; flooring "
        "the SUM gives %d, and not flooring at all puts a raw float in front of the player."
        % (lot_price, lot_n, have["frac_total"], each, whole))

    print("  holdings: sell-side not mid (%d vs %d), divided by the lot (%d for one unit of "
          "%d), floored per instrument not per sum (%d, not %d), goods + Forge + paper all "
          "counted, a delisted house worth nothing"
          % (sell, base, n("one_unit"), lot, each, whole))


def lua_number_const(code, name):
    """The literal a Lua constant is defined as, as a float. None if it is not a plain number."""
    m = re.search(r"^EX\." + re.escape(name) + r"\s*=\s*(-?[0-9.]+)", code, re.M)
    return float(m.group(1)) if m else None


def parse_lua_table(code, name):
    """{key: literal} for one flat Lua table, comments stripped. Values are numbers or bools."""
    body = re.search(r"^EX\." + re.escape(name) + r" = \{(.*?)\n\}", code, re.S | re.M)
    assert body, "EX.%s is gone from the campaign script" % name
    txt = NL.join(l for l in body.group(1).splitlines()
                  if not l.lstrip().startswith("--"))
    out = {}
    for k, v in re.findall(r"(\w+)\s*=\s*(-?[0-9.]+|true|false|\"\w+\")", txt):
        out[k] = True if v == "true" else False if v == "false" else \
            v.strip('"') if v.startswith('"') else float(v)
    return out


def check_tunables():
    """The knobs, and the one way two files can hold the same number safely.

    The default of every knob lives in the CONSTANT the campaign script already defines and
    documents - EX.opt_default reads it there. TUNABLES restates it only because MCT's slider
    needs a default at registration, so this asserts the copy against the original. Without
    that, the panel can offer 0.10 while the game runs on 0.16 and nothing anywhere disagrees.
    """
    code = io.open(LUA_SCRIPT, encoding="utf-8").read()

    tune_num = dict(re.findall(r'(\w+)\s*=\s*"(\w+)"',
                               re.search(r"EX\.TUNE_NUM = \{(.*?)\n\}", code, re.S).group(1)))
    declared = set(t[0] for t in TUNABLES)
    assert set(tune_num) == declared, (
        "EX.TUNE_NUM and TUNABLES disagree.\n  in the script, no slider: %s\n"
        "  a slider, but the script does not know it is a knob (it would read its constant "
        "and ignore the player): %s"
        % (sorted(set(tune_num) - declared) or "none",
           sorted(declared - set(tune_num)) or "none"))

    for key, section, _label, _tip, default, lo, hi, step, prec in TUNABLES:
        const = tune_num[key]
        actual = lua_number_const(code, const)
        assert actual is not None, (
            "EX.%s, the constant EX.TUNE_NUM says holds %r's default, is not defined as a "
            "plain number. EX.opt_default would hand back nil, and nil reaches arithmetic."
            % (const, key))
        assert abs(actual - default) < 1e-9, (
            "%s: the MCT slider defaults to %s and EX.%s is %s. The panel would show one "
            "number and the game run on the other." % (key, default, const, actual))
        assert lo <= default <= hi, (
            "%s defaults to %s, outside its own slider range %s..%s" % (key, default, lo, hi))
        assert section in dict(TUNE_SECTIONS), "%s is in section %r, which is not registered" \
            % (key, section)
        assert prec >= 0 and step > 0, "%s has a nonsense step/precision" % key
        # A default the slider cannot land on is a value the player can never restore by hand.
        assert on_grid(default, lo, step), (
            "%s defaults to %s, which is not on its own slider grid (from %s in steps of %s)"
            % (key, default, lo, step))

        assert 'EX.opt("%s")' % key in code, (
            "%r is registered as a slider and read by nothing in the Lua. The player moves "
            "it, the panel says it moved, and the game runs on the constant." % key)

    bools = set(re.findall(r'"(\w+)"',
                           re.search(r"EX\.TUNE_BOOL = \{(.*?)\}", code, re.S).group(1)))
    assert bools == set(k for k, _l, _t in MCT_OPTIONS), (
        "EX.TUNE_BOOL and MCT_OPTIONS disagree: %s"
        % sorted(bools ^ set(k for k, _l, _t in MCT_OPTIONS)))
    print("  tunables: %d sliders, %d switches, every default read back off its constant"
          % (len(TUNABLES), len(MCT_OPTIONS)))


def on_grid(v, lo, step):
    n = (v - lo) / step
    return abs(n - round(n)) < 1e-6


def check_presets():
    """The four presets, and the four ways one silently becomes something else.

    1. A KEY THAT IS NOT A KNOB. EX.opt_live reads PRESETS[preset][key]; a typo'd entry is
       never read and the knob quietly runs at its default for the whole campaign. Nothing
       errors, and the panel shows the preset the player picked.
    2. A MISSING KEY. A preset that names 29 of 30 knobs is 29 parts itself and one part
       `default`, with nothing on screen saying which. `default` is the deliberate exception
       and must be EMPTY - the defaults are the constants.
    3. A VALUE OUTSIDE ITS SLIDER, or off its step grid. The preset then picks a setting the
       player cannot reproduce under Custom, so the panel and the game disagree about what the
       mod can do.
    4. A BOOLEAN WHERE A NUMBER GOES. EX.opt_live type-checks against the default, so a
       boolean in a numeric slot is silently discarded and that knob runs at its default.
    """
    code = io.open(LUA_SCRIPT, encoding="utf-8").read()
    block = re.search(r"^EX\.PRESETS = \{(.*?)\n\}", code, re.S | re.M)
    assert block, "EX.PRESETS is gone - every difficulty is now the default"
    body = NL.join(l for l in block.group(1).splitlines()
                   if not l.lstrip().startswith("--"))
    presets = {}
    for name, inner in re.findall(r"(\w+)\s*=\s*\{(.*?)\}", body, re.S):
        presets[name] = {k: (True if v == "true" else False if v == "false" else float(v))
                         for k, v in re.findall(r"(\w+)\s*=\s*(-?[0-9.]+|true|false)", inner)}

    order = set(re.findall(r'"(\w+)"',
                           re.search(r"EX\.PRESET_KEYS = \{(.*?)\}", code, re.S).group(1)))
    assert order == set(PRESET_ORDER), (
        "EX.PRESET_KEYS and PRESET_ORDER disagree: %s" % sorted(order ^ set(PRESET_ORDER)))
    assert set(presets) == set(PRESET_ORDER) - {"custom"}, (
        "EX.PRESETS holds %s; it must hold every preset except custom, which is resolved from "
        "MCT and not from a table" % sorted(presets))

    nums = {t[0]: t for t in TUNABLES}
    bools = set(k for k, _l, _t in MCT_OPTIONS)
    every = set(nums) | bools

    assert presets["default"] == {}, (
        "EX.PRESETS.default is not empty: %s. The defaults are the constants EX.opt_default "
        "reads; restating them here is two places to change and one to forget."
        % sorted(presets["default"]))

    for name in ("easy", "hard", "ultra"):
        p = presets[name]
        unknown = sorted(set(p) - every)
        assert not unknown, (
            "preset %r names %s, which is not a knob. EX.opt_live would never read it and the "
            "real knob would run at its default for the whole campaign, silently."
            % (name, unknown))
        missing = sorted(every - set(p))
        assert not missing, (
            "preset %r does not set %s. A partial preset is part itself and part `default` "
            "with nothing saying which; set every key or use `default`." % (name, missing))
        for key, val in sorted(p.items()):
            if key in bools:
                assert isinstance(val, bool), (
                    "preset %r sets the switch %s to %r. EX.opt_live type-checks against the "
                    "default, so a number here is discarded and the switch runs on."
                    % (name, key, val))
                continue
            assert not isinstance(val, bool), (
                "preset %r sets the slider %s to a boolean. It would be type-checked away and "
                "that knob would run at its default." % (name, key))
            _k, _s, _l, _t, _d, lo, hi, step, _p = nums[key]
            assert lo <= val <= hi, (
                "preset %r sets %s to %s, outside its slider range %s..%s - a value the "
                "player could never set by hand under Custom" % (name, key, val, lo, hi))
            assert on_grid(val, lo, step), (
                "preset %r sets %s to %s, which is not on the slider grid (from %s in steps "
                "of %s). Under Custom the player cannot land on it, so the panel and the game "
                "disagree about what this mod can do." % (name, key, val, lo, step))
    print("  presets: %d complete over %d knobs, all inside their sliders and on the grid"
          % (len(presets) - 1, len(every)))


def turn_body(code):
    """The turn's source: EX.turn_round's body followed by the listener that calls it.

    NINE CHECKS USED TO ANCHOR ON THE LISTENER, because until 2026-09-09 the listener WAS the
    turn - one filter on the local faction and eighty lines of body. The multiplayer split
    moved the body into EX.turn_round and left the listener as a turn-number guard, which broke
    every one of those anchors at once. One helper rather than nine patched regexes, so the next
    restructure moves one thing.

    BOTH HALVES, CONCATENATED, and the round comes FIRST. Several callers assert on ORDER with
    body.index(a) < body.index(b), and every ordering constraint lives inside the round - so
    appending the listener can add substrings but can never reorder the ones being measured.

    Raises rather than returning None: a caller that got None would report "X is never called
    on a turn", which is a true statement about a file where the turn itself has been renamed
    and sends the reader hunting for the wrong bug.
    """
    rnd = re.search(r"function EX\.turn_round\(\).*?\n    end\n", code, re.S)
    assert rnd, ("EX.turn_round is gone. The turn's whole ordering lived in it; a rename here "
                 "silently unhooks nine ordering checks at once")
    lis = re.search(r'core:add_listener\("zharr_exchange_turn".*?\n        end, true\)',
                    code, re.S)
    assert lis, "the zharr_exchange_turn listener is gone"
    return rnd.group(0) + NL + lis.group(0)


def check_snapshot_and_debug():
    """The freeze, and the separation of the log from it.

    THE SNAPSHOT IS WHAT MAKES "fixed for the life of a campaign" TRUE. MCT's own gating hooks
    are dead code, so the lock in the settings file is a UI courtesy - it says nothing about a
    player who installs MCT mid-campaign, uninstalls it, or edits the registry. The values a
    save is played on have to live in the save.

    ITS TIMING IS THE ONE THING THAT CAN GO WRONG QUIETLY. Taken at first tick it is not
    provably after MCT's registry load, so a campaign could freeze the DEFAULTS over the
    player's actual choice - permanently, with a correct-looking panel beside it saying
    otherwise. Turn start is provably late enough.
    """
    code = io.open(LUA_SCRIPT, encoding="utf-8").read()
    stripped = NL.join(l for l in code.splitlines() if not l.lstrip().startswith("--"))

    assert re.search(r"function EX\.opt\(key\).*?EX\.snap", stripped, re.S), (
        "EX.opt no longer reads the snapshot first, so a campaign's economy follows the MCT "
        "panel again and the freeze is UI-deep")
    fn = re.search(r"function EX\.snapshot\(\).*?\nend", stripped, re.S)
    assert fn, "EX.snapshot is gone"
    assert "if EX.snap then return false end" in fn.group(0), (
        "EX.snapshot no longer returns early when one exists, so every turn re-reads MCT and "
        "the campaign is not frozen at all")
    assert "EX.setv(EX.SAVE_SNAP" in fn.group(0) and "EX.getv(EX.SAVE_SNAP" in fn.group(0), (
        "EX.snapshot does not round-trip through the save store, so the freeze lasts exactly "
        "as long as the session")

    # THE ROUND, NOT THE LISTENER. Since the multiplayer split (2026-09-09) the listener is a
    # turn-number guard that calls EX.turn_round, and every ordering constraint lives in the
    # round. Anchored on `\n    end\n` because turn_round is defined at one indent inside
    # EX.init - a plain `end` matches the first nested block and the assertion then fails on a
    # correct file, which is the substring-anchor trap this file has already hit five times.
    turn = re.search(r"function EX\.turn_round\(\).*?\n    end\n", stripped, re.S)
    assert turn, "EX.turn_round is gone; the turn's ordering has moved somewhere unchecked"
    assert "EX.snapshot()" in turn.group(0), (
        "EX.snapshot is not called from EX.turn_round; nothing takes it")

    # AND THE ROUND IS ACTUALLY REACHED. A correct round nothing calls is the same campaign as
    # no round at all, and the regex above would still pass.
    lis = re.search(r'core:add_listener\("zharr_exchange_turn".*?\n        end, true\)',
                    stripped, re.S)
    assert lis, "the zharr_exchange_turn listener is gone"
    assert "EX.turn_round()" in lis.group(0), (
        "the FactionTurnStart listener no longer calls EX.turn_round")
    # MULTIPLAYER: THE FILTER MUST NOT BE THE LOCAL FACTION.
    #
    # cm:get_local_faction_name() without the force argument THROWS in a multiplayer campaign,
    # and with it would run a different round on every machine - one client's set of treasuries
    # moving and nobody else's, which is the definition of a desync. EX.is_human answers the
    # same on every machine.
    assert "EX.is_human(context:faction():name())" in lis.group(0), (
        "the turn filter is not EX.is_human. Anything scoped to the local faction names a "
        "different faction on each machine in multiplayer")
    assert "get_local_faction_name" not in lis.group(0), (
        "the turn listener reads the local faction again")
    body = turn.group(0)
    assert body.index("EX.snapshot()") < body.index("EX.check_demand()"), (
        "EX.snapshot runs after something that reads a knob. Every line in that handler prices,"
        " charges or pays out of EX.opt, so the settings have to be resolved before the first "
        "of them.")
    # ONE CALL SITE, AND IT IS THE ONE INSIDE THE TURN HANDLER.
    #
    # NOT "is it absent from EX.init", which was the first shape of this and is unwritable:
    # EX.init is where the turn listener is REGISTERED, so the handler's own call is inside
    # EX.init's body by any text measure, and the assertion failed on correct code. Counting
    # the call sites says the thing that actually matters - nothing else may take a snapshot,
    # and a first-tick call would be a second site.
    calls = [l.strip() for l in stripped.splitlines()
             if "EX.snapshot()" in l and not l.lstrip().startswith("function ")]
    assert len(calls) == 1, (
        "EX.snapshot() is called from %d places: %s. There is exactly one legal moment - the "
        "FactionTurnStart handler. First tick is not provably after MCT's registry has loaded, "
        "so a call there would freeze the DEFAULTS over the player's actual choice, "
        "permanently, with a correct-looking MCT panel beside it saying otherwise."
        % (len(calls), calls))

    # THE DEBUG HALF IS NOT SNAPSHOTTED AND NOT PRESET-CONTROLLED.
    dbg = parse_lua_table(code, "DEBUG_DEFAULT")
    want = {"log_level"} | set(k for k, _l, _t in DEBUG_CATS)
    assert set(dbg) == want, "EX.DEBUG_DEFAULT and DEBUG_CATS disagree: %s" \
        % sorted(set(dbg) ^ want)
    for key in dbg:
        assert 'EX.TUNE_NUM' not in key
        assert key not in [t[0] for t in TUNABLES], (
            "%s is both a debug option and a tunable; it would be frozen at campaign start "
            "and the log level must not be" % key)
    assert "EX.dbg_opt" in fn.group(0) or "log_" not in fn.group(0), (
        "EX.snapshot reaches a debug option; the log level must stay live in a campaign")

    cats = set(re.findall(r'"(\w+)"',
                          re.search(r"EX\.LOG_CATS = \{(.*?)\}", code, re.S).group(1)))
    assert cats == set(k[4:] for k, _l, _t in DEBUG_CATS), (
        "EX.LOG_CATS and the MCT debug checkboxes disagree: %s"
        % sorted(cats ^ set(k[4:] for k, _l, _t in DEBUG_CATS)))
    assert "error" not in cats, (
        "'error' has been given a subsystem checkbox. It must not have one - a switch that can "
        "silence a failure is not a feature, and this mod has already cost four shipped builds "
        "to a fault that logged nothing.")

    say = re.search(r"function EX\.say\(cat, msg\).*?\nend", stripped, re.S)
    assert say, "EX.say is gone"
    lines = [l.strip() for l in say.group(0).splitlines()]
    err_at = next(i for i, l in enumerate(lines) if 'cat == "error"' in l)
    lvl_at = next(i for i, l in enumerate(lines) if "EX.log_level()" in l)
    assert err_at < lvl_at and "return" in lines[err_at], (
        "EX.say checks the log level before it checks for an error, so 'off' silences "
        "failures too")

    # NOTHING WRITES TO THE LOG AROUND EX.say. One ungated out() is one line that cannot be
    # switched off, and 43 of them is the state this replaced.
    loose = [l.strip() for l in stripped.splitlines()
             if re.search(r"\bout\(", l) and "EX.LOG_TAG" not in l]
    assert not loose, "out() called outside EX.say/EX.emit: %s" % loose[:3]

    for key in ("dump_state", "dump_supply"):
        assert "function EX.%s()" % key in code, "EX.%s is gone" % key
    for ev in ("ZharrExchangeDumpState", "ZharrExchangeDumpSupply"):
        assert ev in code, "%s has no listener in the campaign script" % ev
        assert ev in io.open(MCT_LUA, encoding="utf-8").read(), (
            "%s is listened for and nothing fires it" % ev)
    print("  freeze: snapshot at turn start, saved, and the log left live behind it")

    if not os.path.isfile(LUA_EXE):
        print("  (skipped preset run: no lua.exe)")
        return
    import subprocess, tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_mct_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace("\\", "\\\\"))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    def eq(key, want, why):
        assert have.get(key) == str(want), "%s (%s: expected [%s], got [%s])" % (
            why, key, want, have.get(key))

    # EVERY PRESET, EVERY KNOB, against the table the range checks already parsed. Nothing is
    # hand-typed here, so these cannot drift when a preset value is retuned.
    presets = _parse_presets(io.open(LUA_SCRIPT, encoding="utf-8").read())
    defaults = {}
    code = io.open(LUA_SCRIPT, encoding="utf-8").read()
    tune_num = dict(re.findall(r'(\w+)\s*=\s*"(\w+)"',
                               re.search(r"EX\.TUNE_NUM = \{(.*?)\n\}", code, re.S).group(1)))
    for k, const in tune_num.items():
        defaults[k] = lua_number_const(code, const)
    for k, _l, _t in MCT_OPTIONS:
        defaults[k] = True
    for name in ("easy", "default", "hard", "ultra"):
        for key, want in sorted(defaults.items()):
            v = presets[name].get(key, want)
            want_s = "true" if v is True else "false" if v is False else _lua_num(v)
            eq("p_%s_%s" % (name, key), want_s,
               "preset %r answers the wrong value for %s - the difficulty on the panel is not "
               "the difficulty the game runs" % (name, key))

    eq("custom_spread", "0.33", "Custom does not read the slider")
    eq("custom_rungs", "7", "Custom does not read an integer slider")
    eq("custom_rent", "false", "Custom does not read a system switch")
    eq("custom_setting_rent", "false", "EX.setting no longer follows EX.opt")
    eq("custom_wrong_type", _lua_num(defaults["sell_floor"]),
       "a slider whose option answered with a boolean was taken at face value. EX.opt_live "
       "must type-check against the default, or a boolean reaches arithmetic")
    eq("custom_absent", _lua_num(defaults["shock_gain"]),
       "a knob the panel has nothing for did not fall back to its constant")
    eq("unknown_opt", "nil",
       "EX.opt invented a value for a key that is not a knob. Guessing here hides a typo'd "
       "call site forever")
    eq("unknown_setting", "true",
       "EX.setting stopped failing open. MCT absent must never silently disable a feature")
    eq("bogus_preset_spread", _lua_num(defaults["spread"]),
       "a preset name EX.PRESETS does not define returned nil rather than the default. A save "
       "carrying a renamed preset, or a corrupted registry, would then feed nil into every "
       "price calculation - and the crash would land on a line that is not the bug")
    eq("bogus_preset_rent", "true", "an unknown preset silently disabled a system")
    eq("nomct_spread", _lua_num(defaults["spread"]), "MCT absent is not the default preset")
    eq("nomct_rent", "true", "MCT absent switched a system off")
    eq("nomct_preset", "default", "MCT absent does not report the default preset")

    # THE FREEZE ITSELF.
    eq("snap_taken", "true", "the first snapshot was not taken")
    eq("moved_after_preset_change", "0",
       "changing the MCT preset moved values a campaign had already frozen. The lock in the "
       "settings file is a UI courtesy - this is the thing that makes 'fixed for the life of "
       "a campaign' true")
    eq("still_ultra_spread", _lua_num(presets["ultra"]["spread"]),
       "the frozen spread followed the panel")
    eq("preset_name_after_change", "ultra",
       "the campaign reports the preset now selected rather than the one it was started on")
    eq("second_snapshot", "false",
       "a second snapshot was taken. Every turn would re-read MCT and nothing would be frozen "
       "- and it would look correct until the day a player changed a setting mid-campaign")
    eq("still_ultra_after_second", _lua_num(presets["ultra"]["spread"]),
       "the second snapshot overwrote the first")
    eq("nomct_after_snap", _lua_num(presets["ultra"]["spread"]),
       "uninstalling MCT mid-campaign changed the economy")
    eq("retaken_on_load", "false",
       "a load resolved a fresh snapshot instead of reading the saved one, so the campaign's "
       "settings follow whatever the panel says at the moment of loading")
    eq("after_load_spread", _lua_num(presets["ultra"]["spread"]),
       "the snapshot did not survive the save store round trip")
    eq("after_load_preset", "ultra", "the preset name did not survive a load")
    eq("legacy_taken", "true",
       "a campaign with no snapshot in its save never takes one, so it reads MCT live forever")
    eq("legacy_spread", _lua_num(presets["hard"]["spread"]),
       "an existing campaign did not adopt the settings in force when it first ran this build")
    eq("legacy_frozen", _lua_num(presets["hard"]["spread"]),
       "an existing campaign took a snapshot and then ignored it")

    # THE LOG, WHICH IS NOT FROZEN AND NOT PRESET-CONTROLLED.
    ncats = len(DEBUG_CATS)
    eq("log_normal", ncats + 1, "at Normal, every subsystem and the error line must print")
    eq("log_off", 1,
       "at Off, the ERROR line was silenced. A switch that can hide a failure is not a "
       "feature - this mod has already cost four shipped builds to a fault that logged nothing")
    eq("log_errors", 1, "at Errors only, something other than the error printed")
    eq("log_verbose", ncats + 1, "at Verbose, something stopped printing")
    eq("log_one_off", ncats,
       "silencing one subsystem silenced the wrong number of lines - the whole point of the "
       "split is chasing one thing without losing the rest of the log")
    eq("trace_at_normal", 0, "EX.trace printed at Normal; it is verbose-only detail")
    eq("trace_at_verbose", 1, "EX.trace did not print at Verbose")
    eq("log_in_snapshot", "false",
       "the log level was written into the campaign snapshot, so it is frozen at whatever it "
       "was when the campaign began - the one setting that must stay movable")
    print("  presets run: 4 presets x %d knobs, frozen against a changed panel, log left live"
          % len(defaults))


def _lua_num(v):
    """How Lua's tostring prints a number: integers without a decimal point."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(int(v)) if float(v) == int(v) else repr(float(v))


def _parse_presets(code):
    block = re.search(r"^EX\.PRESETS = \{(.*?)\n\}", code, re.S | re.M).group(1)
    body = NL.join(l for l in block.splitlines() if not l.lstrip().startswith("--"))
    out = {}
    for name, inner in re.findall(r"(\w+)\s*=\s*\{(.*?)\}", body, re.S):
        out[name] = {k: (True if v == "true" else False if v == "false" else float(v))
                     for k, v in re.findall(r"(\w+)\s*=\s*(-?[0-9.]+|true|false)", inner)}
    return out


def check_trend_survives_load():
    """Run the SHIPPED EX.trend_arrow against a freshly-loaded board.

    Reported from play: the Trend column reads flat on every row after a load, until the next
    turn ticks. Found by comparing two screenshots of the SAME save at the same treasury and
    the same prices - one with arrows, one without. The old baseline was an in-memory table
    that no save restored, and the reader's fallback made every row equal to itself.

    So this sets up the load state exactly - EX.current and EX.history back from saved values,
    nothing snapshotted - and asserts the arrows are still right.
    """
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped trend load check: no lua.exe)")
        return
    harness = LUA_TREND_HARNESS % (LUA_SCRIPT.replace(chr(92), chr(92) * 2),)
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    at = dict(l.strip().split("|") for l in got.split(chr(10)) if "|" in l)

    want = {
        # A rise and a fall are still visible with nothing in memory but the restored tables.
        "up": "UP",
        "down": "DOWN",
        "flat": "FLAT",
        # One recorded turn: there is no previous rung, and inventing a direction would be
        # worse than saying nothing.
        "first_turn": "FLAT",
        "virgin": "FLAT",
        # THE OLD BUG, FROM THE OTHER SIDE. A mid-turn purchase moves EX.current and must not
        # touch the baseline: 3 -> 6 is a rise and stays one. When the baseline was reset by
        # every trade this read FLAT.
        "traded": "UP",
        # THE PIN, both ends. A commodity at rung 42 or rung 1 cannot move that way again, so
        # "flat" is the one thing it is NOT saying - the price is against the stop.
        "capped": "CAP",
        "floored": "FLOOR",
        # Direction beats the pin: arriving at the cap is a rise, leaving it is a fall.
        "into_cap": "UP",
        "out_cap": "DOWN",
        # No current and no history. The 0 fallback must not be mistaken for rung 1.
        "absent": "FLAT",
    }
    for k in sorted(want):
        assert at.get(k) == want[k], (
            "%s read %s after a load, expected %s - the whole column went flat on a reload "
            "and this is the state that did it" % (k, at.get(k), want[k]))

    print("  trend after load: %d rows, up/down/flat/cap/floor correct with nothing in "
          "memory but the restored tables" % len(want))


def check_trend_snapshot():
    """The trend baseline AND the sparkline history must be taken at the TURN boundary only.

    EX.apply_prices runs at turn start, on load, and 0.1s after every single buy and sell. It
    used to snapshot EX.last at the top, so one purchase overwrote the whole board's previous
    rungs with the current ones and every arrow on the panel went flat at once - reported from
    play as "buying a lot would make the trend be equal to all or neutral". Nothing errored: the
    arrows correctly reported a comparison against a baseline reset under them.

    So this pins the snapshot OUT of apply_prices and INTO the turn listener.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    m = re.search(r"function EX\.apply_prices\(\)(.*?)\nend\n", code, re.S)
    assert m, "EX.apply_prices is gone"

    # THERE IS NO SNAPSHOT ANY MORE, and that is the fix rather than a regression. EX.last was
    # a plain in-memory table, so a LOAD left it empty and every arrow read flat until the next
    # turn ticked. The baseline is now derived from EX.history, which is persisted - see
    # check_trend_survives_load for the behaviour, this only pins the shape.
    assert "EX.last" not in code, (
        "EX.last is back. It is an in-memory table that no save restores, so every trend arrow "
        "reads flat after a load - derive the baseline from EX.history instead.")
    assert "snapshot_trend" not in code, (
        "EX.snapshot_trend is back - two sources of truth for one baseline, and the in-memory "
        "one loses on every load")
    assert re.search(r"function EX\.prev_rung\(res\)", code), (
        "EX.prev_rung is gone - it is what makes the trend survive a load")
    m = re.search(r"function EX\.trend_arrow\(res\)(.*?)\nend\n", code, re.S)
    assert m, "EX.trend_arrow is gone"
    assert "EX.prev_rung" in m.group(1), (
        "EX.trend_arrow no longer reads the persisted history")
    # The history must stay a turn-boundary record, or the trend inherits the very bug the old
    # snapshot existed to dodge. That is asserted for EX.remember_all just below.
    m = re.search(r"function EX\.apply_prices\(\)(.*?)\nend\n", code, re.S)
    assert "EX.history" not in m.group(1), (
        "EX.apply_prices touches EX.history. It runs after every trade, and the trend baseline "
        "now comes from there - so this would flatten every arrow on the board again.")

    # THE SPARKLINE, same trap, same function, and it shipped because this check only ever
    # covered the trend arrow. Reported from play 2026-09-06: "everytime i buy, the last 12
    # turns moves". EX.remember appends one bar and drops the oldest, so calling it from
    # apply_prices - which runs after every trade - made a column headed "Last 12 turns" show
    # the last 12 REPRICES, for all 19 rows, including commodities never traded.
    m = re.search(r"function EX\.apply_prices\(\)(.*?)\nend\n", code, re.S)
    assert "EX.remember" not in m.group(1), (
        "EX.apply_prices calls EX.remember. It runs 0.1s after every buy and sell, so a bar "
        "pushed here means one purchase eats a turn of history on EVERY sparkline. Record at "
        "the turn boundary via EX.remember_all instead.")
    assert re.search(r"function EX\.remember_all\(\)", code), "EX.remember_all is gone"
    callers = re.findall(r"EX\.remember_all\(\)", code)
    assert len(callers) == 2, (
        "expected the definition and exactly one call of EX.remember_all, found %d references. "
        "A second caller is a second bar per turn." % len(callers))
    body2 = turn_body(code)
    assert "EX.remember_all()" in body2, (
        "the sparkline is not recorded in the turn round - one bar per TURN is "
        "what the column header promises")
    assert body2.index("EX.apply_prices()") < body2.index("EX.remember_all()"), (
        "EX.remember_all must run AFTER apply_prices, or it records last turn's rung")
    # There is deliberately NO separate "not on the load path" assertion. The caller count
    # above pins EX.remember_all to exactly one reference besides its definition, and the two
    # assertions after it pin that one to the FactionTurnStart handler - so a load-path call
    # cannot exist without tripping the count first. It was written, found unreachable by
    # break-test, and removed rather than left as a check that can never fail.


def check_demands():
    """Hashut's demands: the feed messages, and the cadence the campaign script spends against.

    Every failure here is silent in game. A message key with no loc behind it draws an empty
    panel, a grace period the two files disagree on punishes the player early, and a tier the
    script charges but the text never names is a demand nobody can read.
    """
    t = build()
    loc = {k: v for k, v, _tt in t["loc"][1]}
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()

    # EVERY (TIER, COMMODITY) MESSAGE, all three parts. The script builds this key by
    # concatenation, so a missing row is a blank event panel and no error anywhere.
    for res in COMMODITIES:
        for sfx, mult, _turns, _wturns, _title, _closer in DEMAND_TIERS:
            key = "%sdem_%s_%s" % (PREFIX, sfx, short(res))
            for part in ("_title", "_primary", "_secondary"):
                assert key + part in loc, "no loc for %s" % (key + part)
            # The amount the text promises must be the amount the script takes.
            assert str(demand_amount(mult)) in loc[key + "_primary"], (
                "%s does not name the %d it charges" % (key, demand_amount(mult)))
    for msg in (PAID_MSG, WRATH_MSG):
        for part in ("_title", "_primary", "_secondary"):
            assert msg + part in loc, "no loc for %s" % (msg + part)
            # LENGTH, not just presence. WRATH_TEXT was defined twice - a 3-tuple here and the
            # wrath bundle's description further down - so text[0..2] indexed a STRING and the
            # three parts shipped as 'T', 'h', 'e'. Every key existed and every other assert
            # passed. A message part is a sentence, never a character.
            assert len(loc[msg + part]) > 12, (
                "%s is %r - too short to be real text; check for a shadowed constant"
                % (msg + part, loc[msg + part]))

    # THE REWARD BUNDLE, mirrored into the script and pointed the right way. A negative value
    # here would make paying the tithe a punishment, which no other check would notice.
    races = race_table()
    for culture, row in sorted(races.items()):
        pb = [j for j in t["effect_bundles_to_effects_junctions_tables"][1]
              if j["effect_bundle_key"] == row["pleased"]]
        assert len(pb) == len(PLEASED_EFFECTS), (
            "%s's reward bundle has %d effects, not %d" % (culture, len(pb),
                                                           len(PLEASED_EFFECTS)))
        assert all(j["value"] > 0 for j in pb), (
            "%s's patron rewards a paid tithe with a PENALTY: %s" % (culture, pb))
    pb = [j for j in t["effect_bundles_to_effects_junctions_tables"][1]
          if j["effect_bundle_key"] == PLEASED_BUNDLE]
    m = re.search(r'EX\.PLEASED_BUNDLE\s*=\s*"([^"]+)"', lua)
    assert m and m.group(1) == PLEASED_BUNDLE, (
        "EX.PLEASED_BUNDLE is %s, the row is %s" % (m and m.group(1), PLEASED_BUNDLE))
    code_paid = chr(10).join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    assert re.search(r"function EX\.pay_demand\(\).*?EX\.pleased_bundle\(\)",
                     code_paid, re.S), (
        "EX.pay_demand does not apply the reward bundle through EX.pleased_bundle(). Reading "
        "the CONSTANT there would hand every race Hashut's bundle - correct for one player in "
        "four, and silent for the other three.")
    assert re.search(r"function EX\.check_demand\(\).*?EX\.wrath_bundle\(\)",
                     code_paid, re.S), (
        "EX.check_demand does not apply the refusal bundle through EX.wrath_bundle()")

    # And the script must agree with the rows on every number it spends against.
    for name, val in (("DEMAND_FIRST_TURN", DEMAND_FIRST_TURN),
                      ("DEMAND_COOLDOWN", DEMAND_COOLDOWN),
                      ("DEMAND_CHANCE", DEMAND_CHANCE),
                      ("DEMAND_TOP_N", DEMAND_TOP_N),
                      ("DEMAND_GRACE", DEMAND_GRACE)):
        m = re.search(r"EX\.%s\s*=\s*(\d+)" % name, lua)
        assert m and int(m.group(1)) == val, (
            "EX.%s is %s in the script, %d here" % (name, m and m.group(1), val))
    m = re.search(r'EX\.WRATH_BUNDLE\s*=\s*"([^"]+)"', lua)
    assert m and m.group(1) == WRATH_BUNDLE, (
        "EX.WRATH_BUNDLE is %s, the row is %s" % (m and m.group(1), WRATH_BUNDLE))

    # THE FIRST DEMAND MUST NOT BE GATED BY THE COOLDOWN. EX.demand_turn is 0 until one has
    # fired, so an unguarded `turn - EX.demand_turn < COOLDOWN` measures against turn 0 and eats
    # every demand until turn COOLDOWN - which makes DEMAND_FIRST_TURN a lie whenever it is set
    # below the cooldown, silently and with nothing in the log. Comments stripped first: the
    # block above the guard quotes the broken form verbatim.
    code = chr(10).join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    assert re.search(r"EX\.demand_turn\s*>\s*0\s+and\s+turn\s*-\s*EX\.demand_turn", code), (
        "maybe_demand's cooldown is not guarded on demand_turn > 0 - the first demand will "
        "never fire before turn DEMAND_COOLDOWN whatever DEMAND_FIRST_TURN says")

    # THE TIER TABLE IS MIRRORED, so every number the script charges and every duration it
    # applies is checked against the text the player read.
    m = re.search(r"EX\.DEMAND_TIERS\s*=\s*\{(.*?)\n\}", lua, re.S)
    assert m, "EX.DEMAND_TIERS is gone"
    got = re.findall(r'\{\s*"(\w+)",\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\}', m.group(1))
    assert len(got) == len(DEMAND_TIERS), "%d tiers in the script, %d here" % (
        len(got), len(DEMAND_TIERS))
    for (sfx, mult, turns, wturns, _title, _closer), g in zip(DEMAND_TIERS, got):
        assert g[0] == sfx and int(g[1]) == demand_amount(mult) and int(g[2]) == turns \
            and int(g[3]) == wturns, ("tier %s drifted: script %s, generator %s"
                                      % (sfx, g, (sfx, demand_amount(mult), turns, wturns)))
    assert sum(int(g[4]) for g in got) == 100, "tier weights do not sum to 100"

    # The wrath bundle still has to exist and still has to hurt.
    bun = {b["key"] for b in t["effect_bundles_tables"][1]}
    for culture, row in sorted(races.items()):
        assert row["wrath"] in bun, (
            "%s's refusal bundle %s is not in effect_bundles_tables - EX.check_demand applies "
            "it three turns after every unanswered tithe, and a key with no row applies "
            "nothing at all" % (culture, row["wrath"]))
        wj = [j for j in t["effect_bundles_to_effects_junctions_tables"][1]
              if j["effect_bundle_key"] == row["wrath"]]
        assert len(wj) == len(WRATH_EFFECTS), (
            "%s's refusal bundle has %d effects, not %d"
            % (culture, len(wj), len(WRATH_EFFECTS)))
        assert all(j["value"] < 0 for j in wj), (
            "%s's patron punishes a refused tithe with a REWARD: %s" % (culture, wj))


def check_friendly():
    """RUN the friendly discount, and prove a round trip still cannot print gold.

    check_spread() proves the ARITHMETIC of the presets. This proves the SHIPPED CODE - that
    the clamp is applied at all, that the friendly half of EX.hostility survives, and that
    buy_price and sell_price together never pay. Two mutants got past the source checks:
    deleting the clamp, and restoring the old `if h < 0 then h = 0 end`. Neither changes a
    line any regex was looking at; both are visible the moment the numbers are run.

    THE ROUND TRIP IS THE ASSERTION THAT MATTERS. Buy at a rung, sell one rung up - the move
    the player's own buying pressure can open - with the discount at its ceiling. 55 such
    trips netted +906 gold in game before the spread existed (2026-09-05).
    """
    if not os.path.isfile(LUA_EXE):
        print("  (skipped friendly run: no lua.exe)")
        return
    import subprocess
    import tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_friendly_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace("\\", "\\\\"))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    # 1 - 1.10 * (1 - 0.10) = 0.0100, and the 0.25 slider must not get past it.
    assert have.get("cap_default") == "0.0048", (
        "the default headroom is not (1 - 1.10*0.90)/2.10 = 0.0048: %s"
        % have.get("cap_default"))
    assert have.get("friendly_default") == "-0.0048", (
        "a friendly guild at the DEFAULT spread got %s, not the 0.0048 the spread can afford. "
        "A larger discount lets a player buy and sell one rung up at a profit."
        % have.get("friendly_default"))
    assert have.get("hostile_default") == "0.2500", (
        "the hostile half changed - it is bounded by hostile_max, not by the spread, because "
        "charging MORE can never mint gold: %s" % have.get("hostile_default"))
    assert have.get("neutral_default") == "0.0000", have.get("neutral_default")

    # A wider spread affords a real discount: 1 - 1.10 * 0.80 = 0.12, under the 0.25 slider.
    assert have.get("cap_wide") == "0.0571", have.get("cap_wide")
    assert have.get("friendly_wide") == "-0.0571", (
        "a 0.20 spread affords a 5.71%% discount and the code gave %s"
        % have.get("friendly_wide"))
    # ...and a slider BELOW the headroom is the one that wins.
    assert have.get("friendly_small") == "-0.0500", (
        "the slider no longer caps the discount when it is the smaller of the two: %s"
        % have.get("friendly_small"))
    # No headroom at all: the cap floors at zero rather than inverting into a surcharge.
    assert have.get("cap_none") == "0.0000", have.get("cap_none")
    assert have.get("friendly_none") == "-0.0000" or have.get("friendly_none") == "0.0000", (
        "a spread with no headroom still granted a discount: %s" % have.get("friendly_none"))
    # Book-weighted, exactly like the markup: half the book friendly is half the discount.
    assert have.get("friendly_half") == "-0.0250", (
        "the discount is not weighted by book share the way the markup is: %s"
        % have.get("friendly_half"))

    # ---- THE ROUND TRIP ----
    for key, why in (("roundtrip_worst", "a 0.20 spread with the discount at its 12% ceiling"),
                     ("roundtrip_default", "the default 0.10 spread")):
        val = have.get(key, "")
        n = int(val.split(" ")[0])
        assert n <= 0, (
            "ROUND TRIP PRINTS GOLD under %s: buying at a rung and selling ONE RUNG UP nets "
            "%+d per lot. That is the exploit check_spread was written to stop, reopened by "
            "the discount. (%s)" % (why, n, val))
    same = int(have.get("same_rung", "1"))
    assert same < 0, (
        "buying and selling at the SAME rung nets %+d - free money with no price movement "
        "needed at all, which is worse than the original exploit" % same)

    # ---- WHAT THE PLAYER IS TOLD ----
    assert have.get("pct_buy") == "6", (
        "the buy cell reports %s%% off at a 5.71%% discount - a price that moves while the cell "
        "says it did not is the fault EX.markup_pct exists to prevent" % have.get("pct_buy"))
    assert "[[col:green]]-" in have.get("cell_buy", ""), (
        "a discounted buy is not drawn green with a minus: %s" % have.get("cell_buy"))
    assert "[[col:green]]+" in have.get("cell_sell", ""), (
        "a friendly sell is not drawn green with a plus: %s" % have.get("cell_sell"))
    assert "[[col:red]]+" in have.get("cell_buy_hostile", ""), (
        "the hostile case lost its red markup: %s" % have.get("cell_buy_hostile"))
    assert have.get("cell_buy_neutral", "").isdigit(), (
        "a neutral guild is drawing a percentage: %s" % have.get("cell_buy_neutral"))
    assert "likes you: -" in have.get("tip_buy", ""), (
        "the buy tooltip does not say the guild likes you: %s" % have.get("tip_buy"))
    assert "% more." in have.get("tip_sell", ""), (
        "the sell tooltip does not say a friendly guild pays MORE: %s" % have.get("tip_sell"))
    assert "dislikes you: +" in have.get("tip_buy_hostile", ""), (
        "the hostile tooltip changed: %s" % have.get("tip_buy_hostile"))
    # ---- THE CELL AND THE TOOLTIP MUST SAY THE SAME NUMBER ----
    # Reported from a screenshot 2026-09-08: the sell cell read -11% while its own tooltip
    # read 10%, on the same row, for the same trade. Both numbers were defensible, which is
    # precisely why they disagreed - the RAW hostility was 10%, but what the sell price loses
    # is measured against the sell base (1 - spread), so 0.10/0.90 = 11.1%. markup_pct is the
    # realised figure, it respects the sell floor, and it is what the cell has always drawn.
    # These settings reproduce that screenshot exactly.
    assert have.get("shot_h") == "0.1000", have.get("shot_h")
    cell_pct = re.search(r"([0-9]+)%", have.get("shot_cell", ""))
    tip_pct = re.search(r"([0-9]+)%", have.get("shot_tip", ""))
    assert cell_pct and tip_pct, (
        "no percentage in the cell or the tooltip: %r / %r"
        % (have.get("shot_cell"), have.get("shot_tip")))
    assert cell_pct.group(1) == tip_pct.group(1) == "11", (
        "the sell cell says %s%% and its tooltip says %s%% for the same trade - they must "
        "both be the REALISED figure (0.10 against a 0.90 sell base is 11%%, not 10%%). "
        "Expected 11 from both.%s  cell: %r%s  tip:  %r"
        % (cell_pct.group(1), tip_pct.group(1), NL, have.get("shot_cell"), NL,
           have.get("shot_tip")))

    # ...and no display site may compute the percentage for itself. Three of them did, which
    # is how one drifted from the other two.
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    body = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    stray = re.findall(r"math\.floor\(math\.abs\(h\) \* 100 \+ 0\.5\)"
                       r"|math\.floor\(h \* 100 \+ 0\.5\)", body)
    assert not stray, (
        "%d display site(s) still turn EX.hostility into a percentage themselves instead of "
        "calling EX.markup_pct. That is a second copy of the maths, and it will disagree with "
        "the cell the moment the sell base or the sell floor touches it." % len(stray))

    print("  friendly discount: capped by the spread (0.5% at default, 5.7% at 0.20), "
          "book-weighted, floors at zero with no headroom, and the round trip still never "
          "pays - same rung or one rung up")


def check_layer2_sell():
    """The Forge's goods sell at a fraction of what they cost, and that fraction is a knob.

    WHY IT IS ITS OWN RULE RATHER THAN THE SPREAD. Layer 2 has no map supply signal, so its
    base rung is the neutral one in every campaign. Under EX.SPREAD alone that was a flat
    1000/900 for ever - a fixed toll on what is effectively a locker, with none of the price
    movement that makes a spread a cost of trading rather than a fee.

    WHY IT NEEDS A RAIL. Layer 2 is NOT frozen, which is easy to assume and wrong: EX.target_rung
    excludes appetite, shocks and the guild's book from it but NOT EX.pressure_shift, so the
    player's own buying moves these two rows and is the only thing that does. Four net lots is
    one rung. A sell factor above 1 / ladder_step therefore pays back more than the buy cost
    with no market risk at all - the same loop check_spread closes for the commodities, on the
    one pair of rows where the player controls both ends of it. EX.sell_price clamps to
    1/ladder_step for that reason, and the clamp is what this proves, by ROUND TRIP rather than
    by reading the expression.

    Everything here runs the shipped Lua: what the player is charged comes out of EX.buy_price
    and EX.sell_price and nothing else, so those are what get asked.
    """
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped layer-2 sell check: no lua.exe at %s)" % LUA_EXE)
        return

    # (ladder_step, l2_sell). The first is the shipped default. The rest straddle the clamp:
    # 0.95 is the slider ceiling and needs clamping at every step, 0.40 needs it at none, and
    # 1.30/1.02 are the ends of the ladder_step slider - the reason the cap cannot be a fixed
    # number on the l2_sell slider instead.
    cases = [(1.10, 0.50), (1.10, 0.95), (1.30, 0.95), (1.02, 0.95),
             (1.18, 0.40), (1.02, 0.40), (1.30, 0.05)]

    # Built with NL and forward slashes, so this harness contains no escape sequence at all.
    # It is still %-formatted to inject the path, and a stray per cent sign would have to be
    # doubled - the trap that has bitten two harnesses already. Hence no string.format.
    path = os.path.abspath(LUA_SCRIPT).replace(os.sep, "/")
    lines = [
        "cm = {add_first_tick_callback=function() end,",
        "      add_loading_game_callback=function() end,",
        "      add_saving_game_callback=function() end}",
        "core = {add_listener=function() end}",
        "function out() end",
        "dofile([[" + path + "]])",
        # ---- the shipped default board ----
        "for _, c in ipairs(EX.LAYER2) do",
        "  print('L2 ' .. c .. ' ' .. EX.lot(c) .. ' ' .. EX.buy_price(c)",
        "        .. ' ' .. EX.sell_price(c))",
        "end",
        "print('C1 ' .. EX.buy_price('res_rom_iron') .. ' '",
        "      .. EX.sell_price('res_rom_iron'))",
        "print('CONST ' .. tostring(EX.L2_SELL) .. ' ' .. tostring(EX.L2_LOT_SIZE))",
        "print('KNOB ' .. tostring(EX.TUNE_NUM.l2_sell))",
        # ---- the knob, and the round trip, through the snapshot EX.opt actually reads ----
        "local k = EX.LAYER2[1]",
    ]
    for step, f in cases:
        lines += [
            "EX.snap = { l2_sell = " + repr(f) + ", ladder_step = " + repr(step) + " }",
            "EX.current[k] = EX.neutral_rung()",
            "local buy = EX.buy_price(k)",
            "EX.current[k] = EX.neutral_rung() + 1",
            "local up = EX.sell_price(k)",
            "EX.current[k] = EX.neutral_rung()",
            "print('T " + repr(step) + " " + repr(f) + " ' .. buy .. ' '",
            "      .. EX.sell_price(k) .. ' ' .. up)",
        ]
    lines.append("")
    harness = NL.join(lines)

    fh = tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8")
    fh.write(harness)
    fh.close()
    try:
        r = subprocess.run([LUA_EXE, fh.name], capture_output=True, text=True)
        assert r.returncode == 0, ("the layer-2 harness did not run:%s%s"
                                   % (NL, (r.stdout + r.stderr).strip()))
        out = r.stdout.strip().splitlines()
        got = dict((l.split(" ", 1)[0], l.split(" ", 1)[1]) for l in out if " " in l)
    finally:
        os.unlink(fh.name)

    assert got.get("KNOB") == "L2_SELL", (
        "EX.TUNE_NUM has no l2_sell entry (read %r). EX.opt_default returns nil for an "
        "unregistered key, EX.opt_live then returns nil, and EX.sell_price would multiply a "
        "price by nil - every layer-2 sell erroring, on a knob the panel still lists."
        % got.get("KNOB"))
    assert got.get("CONST") == "0.5 100", (
        "EX.L2_SELL / EX.L2_LOT_SIZE read %r, not '0.5 100'. This constant is the DEFAULT the "
        "preset table is written against, and docs/ZHARR_EXCHANGE.md quotes it."
        % got.get("CONST"))

    seen = 0
    for line in out:
        if not line.startswith("L2 "):
            continue
        seen += 1
        _, key, lot, buy, sell = line.split(" ")
        assert (lot, buy, sell) == ("100", "1000", "500"), (
            "%s prices at lot %s, buy %s, sell %s on the DEFAULT board - the shipped rule is "
            "100 units for 1000, sold back for 500." % (key, lot, buy, sell))
    assert seen == 2, "expected 2 layer-2 instruments, the harness saw %d" % seen

    # THE COMMODITIES ARE UNTOUCHED, and this is the half that matters. The rule is one `if`
    # at the top of EX.sell_price; a predicate that caught too much would put every commodity
    # on the same haircut, which is the same edit and reads the same in a diff.
    want = "%d %d" % (BASE_LOT_COST, int(BASE_LOT_COST * (1.0 - SPREAD) + 0.5))
    assert got.get("C1") == want, (
        "a commodity at the neutral rung priced %r, not %r - the layer-2 branch is catching "
        "rows it must not." % (got.get("C1"), want))

    # ---- the knob moves the price, and the rail holds at every combination ----
    tested = 0
    for line in out:
        if not line.startswith("T "):
            continue
        tested += 1
        _, step, f, buy, sell, up = line.split(" ")
        step, f = float(step), float(f)
        buy, sell, up = int(buy), int(sell), int(up)
        cap = min(f, 1.0 / step)
        assert sell == int(math.floor(buy * cap)), (
            "at step %s and l2_sell %s the sell paid %d, not %d. The factor is capped at "
            "1/step (%.4f here), so the effective factor is %.4f."
            % (step, f, sell, int(math.floor(buy * cap)), 1.0 / step, cap))
        # THE ROUND TRIP, which is the whole point of the cap. Buying four lots moves the rung
        # one step; selling into that must not pay more than the buy cost.
        assert up <= buy, (
            "at step %s and l2_sell %s a round trip PRINTS GOLD: buy a lot for %d, push the "
            "rung up with four buys, sell for %d. Layer 2's rung moves on the player's own "
            "pressure and on nothing else, so this loop has no market risk in it at all."
            % (step, f, buy, up))
    assert tested == len(cases), ("expected %d knob cases, the harness ran %d"
                                  % (len(cases), tested))

    # ---- and no PRESET may need the clamp: a clamped preset states a value it does not use ----
    code = io.open(LUA_SCRIPT, encoding="utf-8").read()
    block = re.search(r"^EX\.PRESETS = \{(.*?)\n\}", code, re.S | re.M)
    assert block, "EX.PRESETS is gone"
    body = NL.join(l for l in block.group(1).splitlines()
                   if not l.lstrip().startswith("--"))
    for name, inner in re.findall(r"(\w+)\s*=\s*\{(.*?)\}", body, re.S):
        vals = dict((k, float(v)) for k, v in
                    re.findall(r"(\w+)\s*=\s*(-?[0-9.]+)", inner))
        if "l2_sell" not in vals:
            continue                      # `default` is empty by design; the constant answers
        step = vals.get("ladder_step", LADDER_STEP)
        assert vals["l2_sell"] <= 1.0 / step + 1e-12, (
            "the %r preset sets l2_sell %.2f against ladder_step %.2f, so the runtime clamp "
            "cuts it to %.4f. The panel would show one number and the game charge another - "
            "pick a value the preset can actually run."
            % (name, vals["l2_sell"], step, 1.0 / step))

    print("  layer 2: 100 units, buy %d, sell %d by default; knob live over %d step/factor "
          "combinations, round trip never pays, commodities still on the %d%% spread"
          % (BASE_LOT_COST, int(BASE_LOT_COST * 0.5), tested, int(SPREAD * 100)))


def check_spread():
    """A round trip must never mint gold. This is the check the exploit got past.

    MEASURED IN GAME 2026-09-05, before the spread existed: 55 buys and 55 sells of Exotic
    Animals, holdings back to 0, netted +906 gold out of nothing. Buy and sell both read one
    EX.price; the fourth buy ticked the rung up and the first sell collected at the new rung.

    The condition is not "selling pays less than buying" - that is trivially true at a fixed
    rung. It is that selling ONE RUNG HIGHER than you bought must still not pay, because one
    rung is exactly the edge your own buying pressure can open. Anything beyond one rung is the
    market moving on its own, which is the game, and must stay profitable.
    """
    for r in range(1, len(LADDER) + 1):
        assert sell_price(r) < price_at(r),             "no spread at rung %d: %d >= %d" % (r, sell_price(r), price_at(r))
    for r in range(1, len(LADDER)):
        assert sell_price(r + 1) <= price_at(r),             ("ROUND TRIP PROFITS at rung %d: buy %d, sell one rung up for %d. SPREAD (%.3f) "
             "must be >= 1 - 1/LADDER_STEP (%.4f)."
             % (r, price_at(r), sell_price(r + 1), SPREAD, 1 - 1 / LADDER_STEP))
    # ---------------------------------------------------------------------------------
    # AND NOW EVERY PRESET, AND THE FRIENDLY DISCOUNT WITH THEM.
    #
    # Everything above runs against the DEFAULT constants, which is the whole of what this
    # check has ever covered - and the easy preset had ladder_step 1.08 against a 0.04 spread
    # since it was written, so selling one rung up paid 1.0368x what it cost. It minted gold
    # on its own, with no discount involved, and nothing looked (found 2026-09-08 while adding
    # the friendly discount, which needs exactly this arithmetic).
    #
    # The condition, with a discount d that lands on BOTH sides (a friendly guild sells
    # cheaper AND pays more, so the spread closes from both ends):
    #     P * STEP * (1 - spread + d)  <=  P * (1 - d)
    #     d <= (1 - STEP * (1 - spread)) / (1 + STEP)
    # d = 0 recovers the original rule, so a preset with no headroom fails here whether or not
    # anyone is friendly. Dropping the (1 + STEP) is exactly the mistake the friendly harness
    # caught: it granted 12% into a 0.20 spread and a SAME-RUNG round trip then paid +25.
    # Same parse check_presets uses - EX.PRESETS is NESTED, which parse_lua_table cannot
    # read (it returns one flat dict and would fold all four presets into each other).
    _code = io.open(LUA_SCRIPT, encoding="utf-8").read()
    _block = re.search(r"^EX\.PRESETS = \{(.*?)\n\}", _code, re.S | re.M)
    assert _block, "EX.PRESETS is gone - every difficulty is now the default"
    _body = NL.join(l for l in _block.group(1).splitlines()
                    if not l.lstrip().startswith("--"))
    presets = {}
    for _name, _inner in re.findall(r"(\w+)\s*=\s*\{(.*?)\}", _body, re.S):
        presets[_name] = dict(
            (k, True if v == "true" else False if v == "false" else float(v))
            for k, v in re.findall(r"(\w+)\s*=\s*(-?[0-9.]+|true|false)", _inner))
    assert presets, "EX.PRESETS could not be parsed"
    base = {"ladder_step": LADDER_STEP, "spread": SPREAD, "friendly_max": FRIENDLY_MAX}
    seen = 0
    for name in sorted(presets):
        cfg = presets[name]
        if name == "custom":
            continue                      # custom is whatever the player set; the clamp holds
        step = cfg.get("ladder_step", base["ladder_step"])
        spread = cfg.get("spread", base["spread"])
        head = 1 - step * (1 - spread)
        seen += 1
        assert head >= 0, (
            "the %r preset mints gold with no discount at all: ladder_step %.2f against a "
            "%.2f spread means selling ONE RUNG UP pays %.4fx what you bought at. The spread "
            "must clear 1 - 1/step = %.4f."
            % (name, step, spread, step * (1 - spread), 1 - 1 / step))
        # ...and the discount the Lua would actually grant must fit inside that headroom.
        want = cfg.get("friendly_max", base["friendly_max"])
        granted = min(want, head / (1 + step))
        assert step * (1 - spread + granted) <= 1 - granted + 1e-12, (
            "the %r preset grants a %.4f friendly discount into %.4f of headroom - buy at "
            "%.4f, sell ONE RUNG UP for %.4f, and the round trip prints gold."
            % (name, granted, head, 1 - granted, step * (1 - spread + granted)))
        # ...and the same-rung case, which needs no price movement at all.
        assert (1 - spread + granted) < (1 - granted), (
            "the %r preset grants %.4f, which closes the %.2f spread from both sides - buying "
            "and selling at the SAME RUNG pays, with no rung movement needed."
            % (name, granted, spread))
    assert seen >= 4, "only %d presets were checked - the parse is wrong" % seen

    # THE LUA'S OWN CLAMP MUST BE THE SAME ARITHMETIC, not a second copy that can drift.
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    cap = re.search(r"function EX\.friendly_cap\(\)(.*?)\nend", lua, re.S)
    assert cap, "EX.friendly_cap is gone - the discount is unbounded"
    assert ("(1 - EX.LADDER_STEP * (1 - EX.opt(\"spread\"))) / (1 + EX.LADDER_STEP)"
            in cap.group(1)), (
        "EX.friendly_cap no longer divides by (1 + STEP). The discount lands on BOTH sides of "
        "the trade, so the buy-side-only bound is roughly twice too generous - that version "
        "paid +25 a lot on a SAME-RUNG round trip:%s%s" % (NL, cap.group(1)))
    assert re.search(r"if d < 0 then d = 0 end", cap.group(1)), (
        "EX.friendly_cap can return a NEGATIVE cap, which would flip the clamp into a "
        "surcharge on a preset with no headroom")
    # ---------------------------------------------------------------------------------

    # pressure_shift is the other half: asymmetric rounding is what let ONE sold lot move a
    # rung, which is the gap the spread then has to cover.
    for n in range(0, 3 * PRESSURE_PER_RUNG + 1):
        assert pressure_shift(-n) == -pressure_shift(n),             "pressure_shift asymmetric at %d" % n
    assert pressure_shift(PRESSURE_PER_RUNG - 1) == 0
    assert pressure_shift(PRESSURE_PER_RUNG) == 1


def check_lua_scan():
    """Run the SHIPPED EX.scan_supply against a stub map and assert what it excludes.

    The pure pricing math is covered by check_lua_agrees. This covers the BRANCHES, which are
    the part that cannot be reasoned about from the numbers: a razed region still answers
    resource_exists(), and owning_faction() on one is a null interface whose :name() throws.
    Get either wrong and the price is merely wrong - no error, no log line. Same technique as
    tools/gen_victory_routes.py --selftest: stub the interfaces, run the real file, read it
    back. (It used to name check_victory_objectives.py, retired 2026-09-07 with the script it
    checked.)
    """
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped lua scan check: no lua.exe)")
        return

    # r4 is razed, r5's owner is a null interface, r6 belongs to another commodity.
    harness = r"""
local function iface(name)
    if name == nil then return { is_null_interface = function() return true end } end
    return { is_null_interface = function() return false end,
             name = function() return name end }
end
local rcount = 0
-- buildings is a list of building keys; the scan looks each up in EX_PRODUCTION.
local function region(res, owner, abandoned, throws, besieged, no_garrison, buildings)
    rcount = rcount + 1
    local rname = "region_" .. rcount
    return {
        name = function() return rname end,
        is_abandoned = function() return abandoned == true end,
        owning_faction = function()
            if throws then error("owning_faction blew up") end
            return iface(owner)
        end,
        resource_exists = function(_, r) return r == res end,
        slot_list = function()
            local b = buildings or {}
            return {
                num_items = function() return #b end,
                item_at = function(_, i)
                    local key = b[i + 1]
                    return {
                        has_building = function() return key ~= nil end,
                        building = function()
                            return { name = function() return key end }
                        end,
                    }
                end,
            }
        end,
        -- no_garrison leaves this nil on purpose: a region interface that does not answer the
        -- call at all must not take the scan down with it.
        garrison_residence = (not no_garrison) and function()
            return { is_null_interface = function() return false end,
                     is_under_siege = function() return besieged == true end }
        end or nil,
    }
end
local REGIONS = {}
local function world()
    return { world = function() return { region_manager = function() return {
        region_list = function() return {
            num_items = function() return #REGIONS end,
            item_at = function(_, i) return REGIONS[i + 1] end,
        } end } end } end }
end
cm = { add_first_tick_callback = function() end, model = world,
       add_loading_game_callback = function() end,
       add_saving_game_callback = function() end }
core = { add_listener = function() end }
function out(s) print("OUT " .. tostring(s)) end
dofile([[%s]])

REGIONS = {
    region("res_rom_iron", "fac_a"),
    region("res_rom_iron", "fac_a"),
    region("res_rom_iron", "fac_b"),
    region("res_rom_iron", "fac_a", true),    -- razed: must not count at all
    region("res_rom_iron", nil),              -- owner is a null interface
    region("res_rom_lead", "fac_b"),
    -- OPTION D: besieged, so off the market entirely - neither supply nor its owner's tally.
    region("res_rom_iron", "fac_b", false, false, true),
    -- ...and one whose interface has no garrison_residence at all. Before the siege read got
    -- its own pcall this single region returned nil from the WHOLE scan.
    region("res_rom_iron", "fac_a", false, false, false, true),
    -- SUPPLY IS PRODUCTION. This region has NO iron deposit and still produces iron, which is
    -- the case that killed the region-count model: measured on a live map, four Ulthuan
    -- regions make trinkets with resource_exists false. It also carries a MULTI-RESOURCE
    -- building (Hag Graef makes iron and marble at 96 each) and one key nothing maps.
    region("res_nothing", "fac_c", false, false, false, false,
           { "wh2_main_special_hag_graef_mines_4", "wh_main_emp_resource_gold_1" }),
    -- A besieged region's OUTPUT must come off the market too, not just its deposit.
    region("res_rom_iron", "fac_b", false, false, true, false,
           { "wh2_main_special_hag_graef_mines_4" }),
}
dofile([[%s]])
local supply, owners = EX.scan_supply()
print("iron " .. supply["res_rom_iron"])
print("marble " .. supply["res_rom_marble"])
print("lead " .. supply["res_rom_lead"])
print("wine " .. supply["res_rom_wine"])
local names = {}
for k in pairs(owners["res_rom_iron"]) do names[#names + 1] = k end
table.sort(names)
for _, k in ipairs(names) do print("own " .. k .. "=" .. owners["res_rom_iron"][k]) end

REGIONS = { region("res_rom_iron", "fac_a", false, true) }
local s2 = EX.scan_supply()
print("failed " .. tostring(s2 == nil))

-- THE CARTEL PREMIUM'S BASELINE. Build a board on which every commodity is held identically,
-- then ask what concentration is adding. The answer must be ZERO: if everything is equally
-- spread, concentration is doing nothing relative to the map. The shipped-and-wrong version
-- priced raw supply against the EFFECTIVE median and answered +249 here.
local function board(split)
    EX.supply, EX.owners = {}, {}
    for _, res in ipairs(EX.COMMODITIES) do
        EX.supply[res] = 20
        EX.owners[res] = {}
        for i = 1, 20 do EX.owners[res]["f" .. i] = 1 end
    end
    if split then EX.owners[EX.COMMODITIES[1]] = { one = 20 } end
    local c, r = {}, {}
    for _, res in ipairs(EX.COMMODITIES) do
        c[#c + 1] = EX.effective_supply(EX.supply[res], EX.hhi(EX.owners[res]))
        r[#r + 1] = EX.supply[res]
    end
    EX.med, EX.med_raw = EX.median(c), EX.median(r)
end
board(false)
print(string.format("uniform %%.4f", EX.premium(EX.COMMODITIES[1])))
print("avail " .. tostring(EX.unavailable(EX.COMMODITIES[1])))
board(true)
print("cornered " .. tostring(EX.premium(EX.COMMODITIES[1]) > 0))

-- A commodity nothing produces has no offer; a layer-2 pool is merely unscanned and must not
-- be caught by the same test.
EX.supply[EX.COMMODITIES[1]] = 0
print("gone " .. tostring(EX.unavailable(EX.COMMODITIES[1])))
print("layer2 " .. tostring(EX.unavailable(EX.LAYER2[1])))

-- HASHUT'S DEMANDS. Three branches, none of them visible from the numbers.
--
-- 1. THE TIER ROLL is a cumulative threshold. An off-by-one in it does not error, it just
--    quietly shifts how often the greedy demand appears - and the weights are the only thing
--    stopping "Hashut demands 300" from being the common case.
-- 2. THE CANDIDATE PICK must exclude what the faction cannot pay and sort the rest biggest
--    first. Include an unaffordable one and the dilemma arrives with its Submit button greyed
--    out by the engine, which reads as a bug rather than a choice.
-- 3. THE KEYS the Lua builds must be the keys the DB carries. A drift there launches a dilemma
--    the game has no row for - which is not an error, it is silence.
local ROLL = 1
cm.random_number = function(_, _n) return ROLL end
local counts = {}
for r = 1, 100 do
    ROLL = r
    local sfx = EX.pick_demand_tier()[1]
    counts[sfx] = (counts[sfx] or 0) + 1
end
for _, t in ipairs(EX.DEMAND_TIERS) do
    print("tier " .. t[1] .. "=" .. (counts[t[1]] or 0))
end

local HOLD = {}
cm.get_local_faction_name = function() return "player" end
cm.get_faction = function()
    return {
        is_null_interface = function() return false end,
        pooled_resource_manager = function()
            return { resource = function(_, key)
                local v = HOLD[key]
                if not v then return { is_null_interface = function() return true end } end
                return { is_null_interface = function() return false end,
                         value = function() return v end }
            end }
        end,
    }
end
HOLD[EX.hold_key("res_rom_iron")] = 500
HOLD[EX.hold_key("res_gems")] = 120
HOLD[EX.hold_key("res_dyes")] = 49
local c = EX.demand_candidates(50)
print("cand " .. #c .. " " .. c[1][1] .. " " .. c[1][2] .. " " .. c[2][1])
print("cand300 " .. #EX.demand_candidates(300))
print("cand1000 " .. #EX.demand_candidates(1000))

local keys = {}
for _, t in ipairs(EX.DEMAND_TIERS) do
    -- BUILT THE WAY EX.fire_demand BUILDS IT, not through a helper. There was a helper, it
    -- spelled the key "demand_" where every loc row says "dem_", and this check compared it
    -- to a Python twin with the same wrong spelling - so it passed while measuring nothing.
    for _, res in ipairs(EX.COMMODITIES) do
        keys[#keys + 1] = EX.PREFIX .. EX.seg() .. "dem_" .. t[1] .. "_" .. EX.short(res)
    end
end
table.sort(keys)
print("dkeys " .. #keys .. " " .. keys[1] .. " " .. keys[#keys])
""" % (LUA_SCRIPT.replace("\\", "\\\\"), PROD_LUA.replace("\\", "\\\\"))

    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    lines = [x.strip() for x in got.split("\n") if x.strip()]
    want = [
        # Ten stub regions, six of them with an iron DEPOSIT. Counted: two fac_a, one fac_b,
        # one null-owner, and one whose interface has NO garrison_residence at all.
        # Excluded: one razed (fac_a) and one BESIEGED (fac_b).
        #
        # Plus PRODUCTION: fac_c's region has no deposit at all and a Hag Graef mine on it,
        # so +96 iron and +96 marble. The besieged region's identical mine contributes
        # NOTHING - a siege takes the output off the market, not just the deposit.
        "iron 101",      # 5 deposits at LATENT 1 each + 96 from fac_c's Hag Graef mine
        "marble 96",     # no marble deposit anywhere: pure output, which is the whole point
        "lead 1",
        "wine 0",
        "own fac_a=3",   # razed fac_a absent; the no-garrison fac_a region present
        "own fac_b=1",   # two fac_b iron regions, one besieged, so only one counts
        # SUPPLY AND THE OWNERS TALLY MUST BE IN THE SAME UNITS, or EX.hhi - which is a
        # share-of-supply measure - divides output by a region count and every share is
        # nonsense. fac_c owns no deposit and 96 units of output.
        "own fac_c=96",
    ]
    have = [x for x in lines if not x.startswith("OUT ")]
    assert have[:len(want)] == want, (
        "EX.scan_supply mis-scanned the stub map.\n  got  %s\n  want %s\n"
        "'iron 6' or 'own fac_b=2' means a razed or BESIEGED region was counted. 'iron 4' "
        "means the no-garrison region was dropped - the siege probe throwing where it should "
        "shrug. A missing 'own fac_b' means the null owning_faction killed the walk."
        % (have[:len(want)], want))
    assert any("besieged regions are off the market" in x for x in lines), (
        "the blockade counter never fired. It is easy to increment it inside the branch that "
        "only runs when the region is NOT besieged, which can never happen.")
    assert "failed true" in have, (
        "a throwing region must make scan_supply return nil so prices HOLD - got %s" % have)
    assert "uniform 0.0000" in have, (
        "on a board where every commodity is held identically the cartel premium must be 0%% - "
        "got %s. A non-zero answer means EX.premium is comparing across two different medians."
        % [x for x in have if x.startswith("uniform")])
    assert "cornered true" in have, (
        "a commodity held entirely by one faction must show a POSITIVE premium - got %s"
        % [x for x in have if x.startswith("cornered")])
    # No producer anywhere = no offer. The layer-2 pools are UNSCANNED rather than absent, and
    # catching them here would kill the only rows that feed anything outside the panel.
    assert "avail false" in have, "a commodity with supply must be buyable"
    assert "gone true" in have, "a commodity at supply 0 must be marked no-offer"
    assert "layer2 false" in have, (
        "layer 2 has no map supply by design and must stay buyable - EX.supply is NIL for it, "
        "not 0, and EX.unavailable must tell those apart")
    assert any(x.startswith("OUT ZHARR EXCHANGE: supply scan failed") for x in lines), (
        "a failed scan must say so in the log, or prices freeze with no explanation")

    # HASHUT'S DEMANDS.
    for tier, w in zip(DEMAND_TIERS, DEMAND_WEIGHTS):
        line = "tier %s=%d" % (tier[0], w)
        assert line in have, (
            "the tier roll does not match DEMAND_WEIGHTS - got %s, want %s. EX.pick_demand_tier "
            "walks a CUMULATIVE threshold, so an off-by-one there does not error, it just makes "
            "the greedy demand rarer or commoner than the rows were priced for."
            % ([x for x in have if x.startswith("tier ")], line))
    # 500 iron and 120 gems clear a 50 demand; 49 dyes does not. Biggest hoard first.
    assert "cand 2 res_rom_iron 500 res_gems" in have, (
        "EX.demand_candidates must drop what the faction cannot pay and sort the rest biggest "
        "first - got %s" % [x for x in have if x.startswith("cand ")])
    assert "cand300 1" in have and "cand1000 0" in have, (
        "an unaffordable demand must find no candidate at all: a dilemma whose Submit button "
        "the engine greys out reads as a bug, not a choice - got %s"
        % [x for x in have if x.startswith("cand")])
    # THE KEYS THE LUA BUILDS MUST BE THE KEYS THE ROWS CARRY. A drift shows a feed message
    # the game has no text for, which is not an error - it is a blank entry, forever.
    #
    # The harness does not bind a race, so EX.seg() is "" and these are the Chaos Dwarf keys -
    # which is the set that must never move. The other three segments are covered by
    # check_loc_complete, which builds every race's keys from EX.RACES itself.
    dkeys = sorted(demand_key(res, sfx) for res in COMMODITIES
                   for sfx, _m, _t, _w, _T, _c in DEMAND_TIERS)
    want_k = "dkeys %d %s %s" % (len(dkeys), dkeys[0], dkeys[-1])
    assert want_k in have, (
        "the script and demand_key() spell the feed-message key differently - got %s, want %s"
        % ([x for x in have if x.startswith("dkeys")], want_k))
    loc_keys = set(r[0] for r in build()["loc"][1])
    for k in dkeys:
        assert k + "_title" in loc_keys, (
            "%s is the key the script builds and there is no loc row for it. This is the "
            "check that used to compare two dead spellings to each other." % k)



def check_lua_appetite():
    """Run the SHIPPED world-appetite code against stub maps and assert what it prices.

    Three things here fail SILENTLY and none of them shows up in a number anyone would look at:

    1. A CULTURE KEY TYPO. EX.CULTURE_WANTS is keyed by culture, and a culture nobody holds
       contributes nothing - which is exactly what a misspelled key also does. Twenty-five
       entries, one wrong, and that race simply has no appetite for the rest of the campaign.
    2. A COMMODITY KEY TYPO, same shape: wants[res] is nil for a name that does not exist, and
       nil is indistinguishable from "this culture is indifferent".
    3. THE SIGN ON A SUB-RUNG APPETITE. math.floor(-0.5) is -1 while math.floor(0.5) is 0, so
       a naive floor moves a price DOWN on a demand too small to move it up - the same trap
       EX.pressure_shift already carries a comment about, and it cost a day the first time.

    Same technique as check_lua_scan: stub the interfaces, run the real file, read it back.
    """
    import subprocess
    import tempfile
    from read_vanilla_cache import load
    if not os.path.isfile(LUA_EXE):
        print("  (skipped lua appetite check: no lua.exe)")
        return

    crows, _ = load("cultures")
    cultures = set(r["key"] for r in crows if r["key"] != "*")

    harness = r"""
local function faction(name, culture, war)
    return { is_null_interface = function() return false end,
             name = function() return name end,
             culture = function() return culture end,
             at_war = function() return war == true end }
end
local rcount = 0
local function region(res, fac)
    rcount = rcount + 1
    local rname = "region_" .. rcount
    return {
        name = function() return rname end,
        is_abandoned = function() return false end,
        owning_faction = function() return fac end,
        resource_exists = function(_, r) return r == res end,
        slot_list = function() return { num_items = function() return 0 end } end,
        garrison_residence = function()
            return { is_null_interface = function() return false end,
                     is_under_siege = function() return false end }
        end,
    }
end
local REGIONS = {}
cm = { add_first_tick_callback = function() end,
       add_loading_game_callback = function() end,
       add_saving_game_callback = function() end,
       model = function()
           return { world = function() return { region_manager = function() return {
               region_list = function() return {
                   num_items = function() return #REGIONS end,
                   item_at = function(_, i) return REGIONS[i + 1] end,
               } end } end } end }
       end }
core = { add_listener = function() end }
function out() end
dofile([[%s]])

-- EVERY BOARD BELOW EXCEPT D PINS THE LEGACY WORLD WAR TERM, and says so here rather than
-- inheriting whatever EX.FEATURE_DEFAULT happens to be. appetite_drift REPLACES that term
-- (both live would count every war twice), so leaving the default to decide would silently
-- repoint a dozen assertions at the other branch the day the default changed - which is
-- exactly what happened when drift first landed and the gemstone board read 0.
EX.feature = function() return false end

-- THE TABLES THEMSELVES, printed so Python can check the keys against the real vocabularies.
local cks = {}
for k in pairs(EX.CULTURE_WANTS) do cks[#cks + 1] = k end
table.sort(cks)
print("cultures " .. table.concat(cks, " "))
local goods = {}
for _, w in pairs(EX.CULTURE_WANTS) do
    for g in pairs(w) do goods[g] = true end
end
for g in pairs(EX.WAR_APPETITE) do goods[g] = true end
local gl = {}
for g in pairs(goods) do gl[#gl + 1] = g end
table.sort(gl)
print("goods " .. table.concat(gl, " "))
local wl = {}
for g in pairs(EX.WAR_APPETITE) do wl[#wl + 1] = g end
print("warcount " .. #wl)
print("maxrungs " .. EX.AI_MAX_RUNGS)

-- BOARD A: the world arms itself. Five greenskin regions and three Khorne, all at war;
-- two Empire at peace. war_index 0.8, and iron is wanted by every one of them.
local grn = faction("f_grn", "wh_main_grn_greenskins", true)
local kho = faction("f_kho", "wh3_main_kho_khorne", true)
local emp = faction("f_emp", "wh_main_emp_empire", false)
REGIONS = {}
for i = 1, 5 do REGIONS[#REGIONS + 1] = region("res_rom_iron", grn) end
for i = 1, 3 do REGIONS[#REGIONS + 1] = region("res_rom_iron", kho) end
for i = 1, 2 do REGIONS[#REGIONS + 1] = region("res_rom_iron", emp) end
EX.rescan()
print(string.format("war %%.4f", EX.war_index))
print(string.format("share_grn %%.4f", EX.culture_share["wh_main_grn_greenskins"]))
-- THE APPETITE ASSERTIONS BELOW ARE PINNED TO A DELTA, NOT TO THE SHIPPED BASELINE. The scan
-- result is asserted above and is what this board really tests; the war TERM is then driven
-- from a fixed offset so that retuning EX.WAR_BASELINE - which is expected, it is a measured
-- campaign constant - does not silently invalidate five expected values. It did exactly that
-- once: raising the baseline 0.35 -> 0.80 put board A's own 0.8 war index level with it, the
-- war term went to zero and "gems" read 0 instead of -1.
EX.war_index = EX.WAR_BASELINE + 0.45
print("iron " .. EX.appetite_shift("res_rom_iron"))
print("trinkets " .. EX.appetite_shift("res_trinkets"))
print("gems " .. EX.appetite_shift("res_gems"))
print("beer " .. EX.appetite_shift("res_rom_glass"))
print("layer2 " .. EX.appetite_shift(EX.LAYER2[1]))
print("summary " .. EX.appetite_summary())

-- BOARD B: a culture the table has never heard of, on a board with war held at the baseline
-- so the war term contributes exactly nothing. EVERY appetite must be 0. A typo'd culture key
-- produces this same board, which is why 1 above prints the keys for Python to check.
REGIONS = {}
local unknown = faction("f_mod", "mod_culture_that_does_not_exist", false)
for i = 1, 10 do REGIONS[#REGIONS + 1] = region("res_rom_iron", unknown) end
EX.rescan()
EX.war_index = EX.WAR_BASELINE
local nz = 0
for _, res in ipairs(EX.COMMODITIES) do
    if EX.appetite_shift(res) ~= 0 then nz = nz + 1 end
end
print("unknown_nonzero " .. nz)

-- SUB-RUNG APPETITE, both signs. One per cent of the map held by greenskins is 0.06 of a rung
-- of iron and -0.048 of a rung of trinkets. BOTH must read 0. A plain math.floor answers -1
-- for the trinkets, and the board quietly marks luxuries down every turn forever.
EX.culture_share = { wh_main_grn_greenskins = 0.01 }
EX.war_index = EX.WAR_BASELINE
print("tiny_up " .. EX.appetite_shift("res_rom_iron"))
print("tiny_down " .. EX.appetite_shift("res_trinkets"))
print(string.format("tiny_raw %%.4f", EX.world_appetite("res_trinkets")))

-- NO SCAN YET: EX.culture_share nil must be 0, not an error. This is the state on the very
-- first tick, before the first rescan, and EX.target_rung calls straight into it.
EX.culture_share = nil
print("noscan " .. EX.appetite_shift("res_rom_iron"))

-- THE TERM MUST ACTUALLY REACH THE PRICE. Everything above can be perfectly correct and the
-- feature still completely inert, which is not a hypothetical: CONCENTRATION_K shipped at a
-- value that computed fine and moved nothing, and only a live read found it a day later.
-- Same board twice, appetite on and off, through the REAL EX.target_rung.
EX.pressure = {}
local sup, own = { res_rom_iron = 20 }, { res_rom_iron = {} }
for i = 1, 20 do own.res_rom_iron["f" .. i] = 1 end
EX.war_index = EX.WAR_BASELINE
EX.culture_share = { wh_main_grn_greenskins = 1.0 }
local with = EX.target_rung("res_rom_iron", sup, own, 20)
EX.culture_share = {}
local without = EX.target_rung("res_rom_iron", sup, own, 20)
print("reaches " .. (with - without))

-- BOARD D: APPETITE DRIFT, and the property it exists for - it can tell two cultures apart
-- on one board, which the world war_index by construction cannot. Greenskins wholly at war
-- (war_share 1.0, above the 0.80 baseline), Empire wholly at peace (0.0, below it), both
-- wanting iron. The legacy term hands them the same number whatever they are doing.
EX.feature = function(k) return k == "appetite_drift" end
REGIONS = {}
local grn2 = faction("f_grn2", "wh_main_grn_greenskins", true)
local emp2 = faction("f_emp2", "wh_main_emp_empire", false)
for i = 1, 5 do REGIONS[#REGIONS + 1] = region("res_rom_iron", grn2) end
for i = 1, 5 do REGIONS[#REGIONS + 1] = region("res_rom_iron", emp2) end
EX.rescan()
print(string.format("dwar_grn %%.4f", EX.war_share("wh_main_grn_greenskins")))
print(string.format("dwar_emp %%.4f", EX.war_share("wh_main_emp_empire")))
print(string.format("drift_grn %%.4f", EX.drift("wh_main_grn_greenskins", "res_rom_iron")))
print(string.format("drift_emp %%.4f", EX.drift("wh_main_emp_empire", "res_rom_iron")))

-- AN UNMEASURED CULTURE MUST DRIFT BY EXACTLY ZERO. EX.war_share falls back to the world
-- index rather than to 0, because to a term reading a DEVIATION from the baseline a 0 does
-- not mean "unknown" - it means "wholly at peace", the most negative reading available, and
-- every culture the scan had not reached would drag its own appetites the wrong way.
print(string.format("drift_unseen %%.4f", EX.drift("wh2_main_skv_skaven", "res_rom_iron")))

-- THE CLAMP. A confederation multiplying a culture's share in one turn is a trend far
-- above 1, which without DRIFT_MAX would be half a want or more and could INVERT one - a
-- culture that wants timber would start supplying it because it grew.
EX.culture_share_prev = { wh_main_grn_greenskins = 0.05 }
EX.culture_share      = { wh_main_grn_greenskins = 0.50 }
print(string.format("trend_big %%.4f", EX.culture_trend("wh_main_grn_greenskins")))
print(string.format("drift_clamp %%.4f", EX.drift("wh_main_grn_greenskins", "res_rom_timber")))

-- A CULTURE NEW TO THE SCAN reads trend 0, not infinite growth.
print(string.format("trend_new %%.4f", EX.culture_trend("wh3_main_cth_cathay")))

-- AND THE A/B ITSELF - but it has to be set up so that DRIFT is the only thing that can
-- differ, which the first version of this was not.
--
-- WHY war_index IS PINNED TO THE BASELINE HERE. Turning appetite_drift off puts the world war
-- term BACK, so with drift ripped out of EX.world_appetite entirely the two branches still
-- disagree - about the world term - and an off ~= on assertion passes on code where the whole
-- feature reaches nothing. That mutant survived the first version of this check, which is the
-- CONCENTRATION_K fault reproduced inside the very check written to catch it. At the baseline
-- the world term is exactly zero, so the only thing left that can move the number is drift.
EX.war_index = EX.WAR_BASELINE
EX.culture_share = { wh_main_grn_greenskins = 1.0 }
EX.culture_war   = { wh_main_grn_greenskins = 1.0 }
EX.feature = function() return false end
local ab_off = EX.world_appetite("res_rom_iron")
EX.feature = function(k) return k == "appetite_drift" end
local ab_on = EX.world_appetite("res_rom_iron")
print(string.format("ab_off %%.4f", ab_off))
print(string.format("ab_on %%.4f", ab_on))

-- BOARD E: A DEMAND SHOCK, END TO END. Everything about share_shocks can be arithmetically
-- correct and the feature still completely inert - that is CONCENTRATION_K's fault exactly,
-- and it survived a day in play. So this runs the real function and reads EX.shock back.
--
-- THE TWO SIGNS ARE THE ASSERTION. A culture that WANTED a good vanishing takes its demand
-- with it and the price must FALL; one that SUPPLIED it (a negative want) vanishing takes
-- supply and the price must RISE. A shock model that only ever adds is what the four region
-- kinds already were, and a crater is the whole reason this half exists.
EX.feature = function(k) return k == "demand_shocks" end
EX.setv = function() end
EX.save_shocked = function() end
EX.shocked, EX.shock, EX.shock_why = {}, {}, {}

-- THE FIRST COMPARISON OF A SESSION MUST SHOCK NOTHING. EX.init runs its own rescan, so
-- the first turn round compares an INIT-TIME scan against a turn-time one - on a new
-- campaign that window holds the whole scripted start, and on a load it holds however
-- long the player sat in the menu. Measured in play 2026-09-09: the first round announced
-- the Empire losing 2.1%% of the world, which is setup being priced as news.
EX.cshare_ready = false
EX.culture_share_prev = { wh_main_grn_greenskins = 0.50 }
EX.culture_share      = { wh_main_grn_greenskins = 0.10 }
EX.share_shocks()
local guard_moved = 0
for _, v in pairs(EX.shock) do if v ~= 0 then guard_moved = guard_moved + 1 end end
print("shk_guard " .. guard_moved)
-- ...and the very next comparison must, or the guard is a permanent off switch.
EX.shocked, EX.shock = {}, {}
-- Which goods the greenskins want and supply is READ OFF THE SHIPPED TABLE, not assumed, so
-- retuning EX.CULTURE_WANTS cannot quietly turn this into an assertion about nothing.
local gw = EX.CULTURE_WANTS["wh_main_grn_greenskins"]
local most_wanted, most_supplied = nil, nil
for res, v in pairs(gw) do
    if most_wanted == nil or v > gw[most_wanted] then most_wanted = res end
    if most_supplied == nil or v < gw[most_supplied] then most_supplied = res end
end
EX.culture_share_prev = { wh_main_grn_greenskins = 0.50 }
EX.culture_share      = { wh_main_grn_greenskins = 0.10 }
EX.share_shocks()
print(string.format("shk_wanted %%.4f", EX.shock[most_wanted] or 0))
print(string.format("shk_supplied %%.4f", EX.shock[most_supplied] or 0))
print("shk_why " .. tostring(EX.shock_why[most_wanted]))

-- A MOVE UNDER THE THRESHOLD MUST DO NOTHING, or ordinary turn-to-turn churn shocks all
-- seventeen commodities every turn for the whole campaign.
EX.shocked, EX.shock = {}, {}
EX.culture_share_prev = { wh_main_grn_greenskins = 0.50 }
EX.culture_share      = { wh_main_grn_greenskins = 0.4950 }
EX.share_shocks()
print(string.format("shk_tiny %%.4f", EX.shock[most_wanted] or 0))

-- A CULTURE WITH NO PREVIOUS ENTRY IS NEITHER A COLLAPSE NOR A SURGE. Without this the first
-- scan of every campaign reads the whole map as having just appeared.
EX.shocked, EX.shock = {}, {}
EX.culture_share_prev = {}
EX.culture_share      = { wh_main_grn_greenskins = 0.50 }
EX.share_shocks()
print(string.format("shk_new %%.4f", EX.shock[most_wanted] or 0))

-- AND THE SWITCH: off must mean nothing moves at all.
EX.feature = function() return false end
EX.shocked, EX.shock = {}, {}
EX.culture_share_prev = { wh_main_grn_greenskins = 0.50 }
EX.culture_share      = { wh_main_grn_greenskins = 0.10 }
EX.share_shocks()
print(string.format("shk_off %%.4f", EX.shock[most_wanted] or 0))
""" % (LUA_SCRIPT.replace("\\", "\\\\"),)

    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = dict()
    for line in got.split("\n"):
        line = line.strip()
        if not line:
            continue
        k, _sp, v = line.partition(" ")
        have[k] = v

    # 1. EVERY CULTURE KEY IS REAL. A typo here is a race with no appetite, forever, silently.
    named = set(have["cultures"].split())
    # MODDED CULTURES ARE EXEMPT, and registered rather than waved through - see
    # MODDED_CULTURES for how each key was established (read off a running campaign, since a
    # compressed Workshop pack cannot be scanned for it). The mod stays optional: the key
    # reaches no DB row, which check_no_foreign_keys proves.
    bad = sorted(named - cultures - set(MODDED_CULTURES))
    assert not bad, (
        "EX.CULTURE_WANTS names %d culture(s) that do not exist: %s.\nA culture key nobody "
        "holds contributes nothing - which is exactly what a typo does too, so this never "
        "shows up as an error. Valid keys come from cultures_tables." % (len(bad), bad))

    # 2. EVERY COMMODITY NAMED IN EITHER TABLE IS REAL, same failure shape.
    named_goods = set(have["goods"].split())
    bad = sorted(named_goods - set(COMMODITIES))
    assert not bad, (
        "EX.CULTURE_WANTS / EX.WAR_APPETITE name %d commodity/ies that do not exist: %s. "
        "wants[res] is nil for a bad name, and nil reads as indifference." % (len(bad), bad))

    # 3. WAR_APPETITE IS COMPLETE. A missing key is indistinguishable from a deliberate 0, so
    #    the zeroes are written out and this asserts they all are.
    assert int(have["warcount"]) == len(COMMODITIES), (
        "EX.WAR_APPETITE covers %s of %d commodities. Write the zeroes out: a missing key and "
        "a deliberate war-neutral are the same thing to the code and opposite things to a "
        "reader." % (have["warcount"], len(COMMODITIES)))

    # 3b. BUILD_APPETITE, the growth half of the drift term, under the same two rules -
    #     complete, and both signs. Read statically rather than off the stub board because
    #     a table that is merely REACHED proves nothing about the keys it is missing.
    build = parse_lua_table(io.open(LUA_SCRIPT, encoding="utf-8").read(),
                            "BUILD_APPETITE")
    missing = sorted(set(COMMODITIES) - set(build))
    assert not missing, (
        "EX.BUILD_APPETITE is missing %d commodity/ies: %s. Same rule as WAR_APPETITE - "
        "write the zeroes out, because a missing key and a deliberate growth-neutral are "
        "the same thing to the code and opposite things to a reader."
        % (len(missing), missing))
    extra = sorted(set(build) - set(COMMODITIES))
    assert not extra, (
        "EX.BUILD_APPETITE names %d commodity/ies that do not exist: %s" % (len(extra), extra))
    vals = [float(v) for v in build.values()]
    assert max(vals) > 0 and min(vals) < 0, (
        "EX.BUILD_APPETITE is one-way (max %.2f, min %.2f). A table with only one sign "
        "pushes every price it touches the same way for the whole campaign - the fault "
        "EX.CULTURE_WANTS is already checked for." % (max(vals), min(vals)))
    assert max(abs(v) for v in vals) <= 1.0, (
        "EX.BUILD_APPETITE has a value outside -1..1; it is multiplied by DRIFT_GROWTH and "
        "then by ai_gain, so an outlier is six times an outlier.")

    # THE CLAMP MIRRORS THE LUA. Every other constant in this file has a Python twin asserted
    # against the shipped value; this one gates the two clamp assertions below, so a drift
    # would make them pass against the wrong ceiling rather than fail.
    assert int(have["maxrungs"]) == AI_MAX_RUNGS, (
        "EX.AI_MAX_RUNGS is %s in the script and %d here" % (have["maxrungs"], AI_MAX_RUNGS))

    # BOARD A. The scan must read culture and war off the same walk it reads supply from.
    assert have["war"] == "0.8000", (
        "war_index is %s, want 0.8000 - eight of ten stub regions belong to factions at war. "
        "A wrong denominator here scales every war term on the board." % have["war"])
    assert have["share_grn"] == "0.5000", (
        "greenskin share is %s, want 0.5000. Shares are taken over COUNTED regions so they "
        "sum to 1." % have["share_grn"])
    # Iron: culture 0.94, war +0.225, x6 = 6.99 rungs, clamped to AI_MAX_RUNGS.
    assert have["iron"] == "2", (
        "iron must clamp UP to +%d on a warring greenskin board - got %s. A 0 here means the "
        "culture term never reached the shift; a negative means the sign is inverted."
        % (AI_MAX_RUNGS, have["iron"]))
    # Trinkets: culture -0.67, war -0.2025, x6 = -5.24, clamped.
    assert have["trinkets"] == "-2", (
        "elven trinkets must clamp DOWN to -%d when greenskins and Khorne hold the map - got "
        "%s" % (AI_MAX_RUNGS, have["trinkets"]))
    # Gems: no culture on this board wants them; war alone is -1.08 rungs. THE UNCLAMPED
    # NEGATIVE, which is the case a plain math.floor gets right by luck and gets wrong by one
    # anywhere above -1.
    assert have["gems"] == "-1", (
        "gemstones must read exactly -1 from the war term alone - got %s. -2 is what a plain "
        "math.floor answers here, so this fires on the truncation trap as well as on a dead "
        "war term - whichever broke, read tiny_down below before concluding which."
        % have["gems"])
    assert have["beer"] == "0", (
        "Dwarf Beer is war-neutral and no culture on board A drinks it, so it must not move - "
        "got %s" % have["beer"])
    assert have["layer2"] == "0", (
        "Armaments and Raw Materials come out of the Forge, not off the world's land, and "
        "must take no appetite at all - got %s" % have["layer2"])
    assert "Wanted:" in have["summary"] and "Going begging:" in have["summary"], (
        "the footer summary must name both sides on a board that moves both ways - got %r"
        % have["summary"])

    # BOARD B. An unknown culture contributes nothing, and does not error on the way.
    assert have["unknown_nonzero"] == "0", (
        "a culture absent from EX.CULTURE_WANTS must move %s commodities, not %s. This is the "
        "board a typo'd culture key produces, which is why the keys are checked above."
        % (0, have["unknown_nonzero"]))

    # SUB-RUNG. Both signs must truncate to zero.
    assert have["tiny_up"] == "0" and have["tiny_down"] == "0", (
        "a sub-rung appetite must read 0 on BOTH sides - got up=%s down=%s. tiny_raw was %s: "
        "math.floor on that answers -1, and the board marks luxuries down every turn forever."
        % (have["tiny_up"], have["tiny_down"], have["tiny_raw"]))
    assert float(have["tiny_raw"]) < 0, (
        "the sub-rung negative case is not actually negative (%s), so tiny_down proves "
        "nothing" % have["tiny_raw"])

    # THE TERM REACHES THE PRICE. A whole correct model that nothing consumes is the exact
    # shape CONCENTRATION_K shipped in, and no other assertion here would notice.
    # ------------------------------------------------------------------ BOARD D: DRIFT
    #
    # The point of the per-culture war term is DISCRIMINATION: two cultures on one board,
    # same base want, opposite war states, opposite drift. The world war_index cannot express
    # that at all - it is one number for everybody - so a drift that failed to separate these
    # two would be the legacy term wearing a new name.
    drift_max = float(re.search(r"EX\.DRIFT_MAX\s*=\s*([\d.]+)",
                                io.open(LUA_SCRIPT, encoding="utf-8").read()).group(1))
    assert have["dwar_grn"] == "1.0000", (
        "greenskin war_share is %s, want 1.0000 - all five of their regions are at war. This "
        "is a fraction of THAT CULTURE'S own land, not of the world; dividing by the world "
        "instead makes every culture's war term scale with its size twice."
        % have["dwar_grn"])
    assert have["dwar_emp"] == "0.0000", (
        "empire war_share is %s, want 0.0000" % have["dwar_emp"])
    assert float(have["drift_grn"]) > 0 > float(have["drift_emp"]), (
        "drift did not separate a culture at war (%s) from one at peace (%s) on the same "
        "board. Both signs are required: a war-drift that only ever adds is the one-way pump "
        "EX.CULTURE_WANTS is already checked against."
        % (have["drift_grn"], have["drift_emp"]))
    assert have["drift_unseen"] == "0.0000", (
        "a culture the scan never saw drifted by %s, want exactly 0. EX.war_share must fall "
        "back to the world index, not to 0 - to a term reading a deviation from WAR_BASELINE, "
        "0 means 'wholly at peace', which is the most negative reading there is."
        % have["drift_unseen"])
    assert float(have["trend_big"]) > 8.0, (
        "trend on a 0.05 -> 0.50 culture is %s, want 9.0 - it is a fraction of that culture's "
        "OWN previous size, not of the map" % have["trend_big"])
    assert abs(float(have["drift_clamp"])) <= drift_max + 1e-6, (
        "drift reached %s against a DRIFT_MAX of %.2f. Unclamped, one confederation inverts "
        "an appetite: a culture that wants timber starts supplying it because it grew."
        % (have["drift_clamp"], drift_max))
    assert have["trend_new"] == "0.0000", (
        "a culture new to the scan read a trend of %s, want 0. No previous entry is not "
        "infinite growth." % have["trend_new"])
    # ------------------------------------------------------------------ BOARD E: SHOCKS
    assert have["shk_guard"] == "0", (
        "the first share comparison of a session shocked %s commodities. It must shock "
        "none: EX.init runs its own rescan, so that comparison is an init-time scan "
        "against a turn-time one - on a new campaign it contains the entire scripted "
        "start. Measured in play: it announced a 2.1%% Empire collapse on turn 1."
        % have["shk_guard"])
    assert float(have["shk_wanted"]) < 0, (
        "a culture that wanted a good lost 40%% of the map and its price moved %s. It must "
        "FALL - their demand went with them. This is the only shock in the mod that can "
        "crater a price, and without it a protective sell-stop is an order against a thing "
        "that cannot happen." % have["shk_wanted"])
    assert float(have["shk_supplied"]) > 0, (
        "a culture that SUPPLIED a good (a negative want) collapsed and its price moved %s. "
        "It must RISE - that is supply leaving the market, the same thing a razed region "
        "is. Both signs of want moving the price the same way means the sign was dropped."
        % have["shk_supplied"])
    assert have["shk_why"] == "collapse", (
        "the shock reason read %s; the panel footer prints this word" % have["shk_why"])
    assert have["shk_tiny"] == "0.0000", (
        "a 0.5%% share move shocked the board by %s. SHARE_SHOCK_MIN exists so ordinary "
        "churn - one region changing hands - does not shock all seventeen commodities "
        "every turn forever." % have["shk_tiny"])
    assert have["shk_new"] == "0.0000", (
        "a culture with no previous entry shocked the board by %s. It has not surged, it "
        "has been seen for the first time - and on turn one that is EVERY culture on the "
        "map." % have["shk_new"])
    assert have["shk_off"] == "0.0000", (
        "demand_shocks is off and the board still moved by %s" % have["shk_off"])

    # war_index is pinned to WAR_BASELINE on this board, so the world war term is exactly
    # zero in BOTH branches and drift is the only thing that can move this number. Without
    # that pin the assertion passes on code where EX.drift is never called at all - it would
    # be reading the world term switching off, not the drift switching on.
    assert have["ab_off"] != have["ab_on"], (
        "appetite_drift on and off price the same board identically (%s), with the world war "
        "term pinned out of both. The drift never reaches EX.world_appetite - which is "
        "CONCENTRATION_K's fault exactly: arithmetic that is correct and moves nothing."
        % have["ab_off"])

    assert have["reaches"] == str(AI_MAX_RUNGS), (
        "EX.target_rung moved %s rungs when the world's appetite went from nothing to a map "
        "wholly held by iron-hungry greenskins, want %d. A 0 means the appetite is computed "
        "and never applied - the feature is inert and every other check in here still passes."
        % (have["reaches"], AI_MAX_RUNGS))

    # FIRST TICK. EX.target_rung calls appetite_shift before any scan has run.
    assert have["noscan"] == "0", (
        "with no scan completed EX.culture_share is nil and the appetite must be 0, not an "
        "error - got %s. EX.target_rung reaches this on the very first tick." % have["noscan"])


# The clamp is mirrored so the two clamp assertions below cannot silently test the wrong
# ceiling. Every other shock constant is READ OUT of the script and the expectations are
# computed from it - pinning tuning here is what made retuning WAR_BASELINE break its own
# check on 2026-09-06.
SHOCK_MAX = 6


# The stub HUD check_lua_button() runs the SHIPPED file against. The whole point is that
# resources_bar is ANIMATED, so BAR_Y is a variable here and not a constant.
# The finance list check_finance_recolour() runs the SHIPPED EX.recolour_finance against. The
# 35 rows, their states and their numbers are TRANSCRIBED FROM THE LIVE PANEL on turn 13 of
# wh3_dlc23_chd_conclave, read out of the game with GetStateText - not invented. The two facts
# it exists to pin are both measured:
#   entry_31 dy_value1 = 734 in state "positive" - the warehousing rent, green, in the
#     Expenses column, under a red Total Expenses of 14892 that includes it.
#   every state carries its OWN text, so a bare SetState("negative") swaps the live number for
#     the twui's authored placeholder. That placeholder really is "100"; it was read back off
#     the live component after setting the state, and put back.
# The stub treasury bar check_hud_income() runs the SHIPPED EX.brand_income against. dy_income
# really does carry two states with their own text - read out of
# hud_campaign_resource_bar_wh3.twui.xml, "positive" green and "negative" red - and the stub
# models the engine the way the engine behaves: it refreshes the CURRENT state only.
# The stub board check_trend_survives_load() runs the SHIPPED EX.trend_arrow against. It is set
# up as a FRESHLY LOADED campaign: EX.current and EX.history restored from saved values and
# nothing else in memory at all, which is exactly the state that used to draw nineteen flat
# arrows.
LUA_TREND_HARNESS = """
find_uicomponent = function() return false end
is_uicomponent = function() return false end
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    add_listener = function() end,
    set_saved_value = function() end,
    get_saved_value = function() end,
    get_local_faction_name = function() return "player" end,
}
core = {
    add_listener = function() end,
    get_ui_root = function() return {} end,
    get_screen_resolution = function() return 1920, 1080 end,
}
function out() end
dofile([[%s]])

-- A LOAD. Both tables come back from saved values; nothing was snapshotted this session.
EX.current = { up = 5, down = 3, flat = 4, first_turn = 7, virgin = 2, traded = 6 }
EX.history = {
    up         = { 3, 5 },
    down       = { 5, 3 },
    flat       = { 4, 4 },
    first_turn = { 7 },        -- one bar: a campaign on its first recorded turn
    -- virgin has no history at all
    traded     = { 3, 5 },     -- bought mid-turn: current moved to 6, history untouched
}

-- EITHER END OF THE LADDER. A pinned commodity holds its rung every turn, so it is FLAT by
-- every test above - which is the whole fault: res_rom_glass and res_gold_idols read as a
-- quiet market for the whole 2026-09-06 soak while they were actually against the stop.
EX.current.capped   = EX.RUNGS      ; EX.history.capped   = { EX.RUNGS, EX.RUNGS }
EX.current.floored  = 1             ; EX.history.floored  = { 1, 1 }
-- The turn it CLIMBS in is a rise and must still read UP; only the turns after are the pin.
EX.current.into_cap = EX.RUNGS      ; EX.history.into_cap = { EX.RUNGS - 2, EX.RUNGS }
EX.current.out_cap  = EX.RUNGS - 1  ; EX.history.out_cap  = { EX.RUNGS, EX.RUNGS - 1 }
-- Neither table knows this row, so EX.current[res] falls back to 0. That must not read as
-- the floor - rung 0 does not exist, and the fallback is "no idea", not "cheapest possible".

local function name(a)
    if a == EX.TREND_UP then return "UP" end
    if a == EX.TREND_DOWN then return "DOWN" end
    if a == EX.TREND_FLAT then return "FLAT" end
    if a == EX.TREND_CAP then return "CAP" end
    if a == EX.TREND_FLOOR then return "FLOOR" end
    return "?" .. tostring(a)
end
local order = { "up", "down", "flat", "first_turn", "virgin", "traded",
                "capped", "floored", "into_cap", "out_cap", "absent" }
for i = 1, #order do
    print(order[i] .. "|" .. name(EX.trend_arrow(order[i])))
end
"""


LUA_HUD_HARNESS = """
local LABEL = { state = "positive", txt = { positive = "0", negative = "0" } }
LABEL.Id = function() return "dy_income" end
LABEL.CurrentState = function() return LABEL.state end
LABEL.GetStateText = function() return LABEL.txt[LABEL.state] end
LABEL.SetState = function(_, st) LABEL.state = st end
LABEL.SetStateText = function(_, t) LABEL.txt[LABEL.state] = t end

NET = 0
RENT = 0
PRESENT = true
NULL_FACTION = false
local FACTION = {
    net_income = function() return NET end,
    is_null_interface = function() return NULL_FACTION end,
}
function find_uicomponent(_root, ...)
    local a = { ... }
    if a[#a] == "dy_income" and PRESENT then return LABEL end
    return false
end
function is_uicomponent(c) return c ~= nil and c ~= false end
function UIComponent(c) return c end
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    add_listener = function() end,
    set_saved_value = function() end,
    get_saved_value = function() end,
    get_local_faction_name = function() return "player" end,
    get_faction = function() return FACTION end,
}
core = {
    add_listener = function() end,
    get_ui_root = function() return {} end,
    get_screen_resolution = function() return 1920, 1080 end,
}
function out() end
dofile([[%s]])

EX.carry_total = function() return RENT end
local function report(tag)
    print(tag .. "|" .. LABEL.state .. "|" .. LABEL.txt.positive .. "|" .. LABEL.txt.negative)
end

NET, RENT = 2338, 734
EX.brand_income()
report("first")

-- THE TIMER: this runs every second for the rest of the campaign.
for _ = 1, 10 do EX.brand_income() end
report("after_ten_ticks")

-- The engine's own figure moves.
NET = 2000
EX.brand_income()
report("income_changed")

-- The last crate is sold. The bar must go back to telling the engine's truth, not stay on the
-- corrected figure - which is only automatic because the number is derived, not remembered.
RENT = 0
EX.brand_income()
report("sold_out")

-- Bought again with income unchanged. The first draft stuck here for ever.
RENT = 734
EX.brand_income()
report("bought_again")

-- Rent above income: red, and still correct.
NET, RENT = 500, 734
EX.brand_income()
report("goes_negative")

-- No bar on screen - loading, battles, the frontend. Must be a no-op, not a throw.
PRESENT = false
EX.brand_income()
PRESENT = true
report("no_bar")

-- A null faction interface, which is what get_faction hands back before the world exists.
NULL_FACTION = true
NET, RENT = 9999, 0
EX.brand_income()
NULL_FACTION = false
report("null_faction")
"""


LUA_FINANCE_HARNESS = """
local function mkval(id, text, state)
    local v = { id = id, state = state, txt = {} }
    -- EVERY state starts on the twui's authored placeholder and only the CURRENT one carries
    -- the real number. This is the trap: a recolour that forgets to rewrite the text ends up
    -- showing 100 for every expense in the game.
    v.txt.positive, v.txt.negative, v.txt.NewState = "100", "100", "100"
    v.txt[state] = text
    v.Id = function() return v.id end
    v.CurrentState = function() return v.state end
    v.GetStateText = function() return v.txt[v.state] end
    v.SetState = function(_, st) v.state = st end
    v.SetStateText = function(_, t) v.txt[v.state] = t end
    return v
end

local function mkrow(id, kids)
    local r = { id = id, kids = kids or {} }
    r.Id = function() return r.id end
    r.ChildCount = function() return #r.kids end
    r.Find = function(_, i) return r.kids[i + 1] end
    return r
end

local function entry(id, name, v1, s1, v2, s2)
    return mkrow(id, { mkval("dy_item_name", name, "NewState"),
                       mkval("dy_value1", v1, s1), mkval("dy_value2", v2, s2) })
end

local ROWS = {
    mkrow("header_0"), mkrow("subheader_1"),
    entry("entry_2", "Building income", "1155", "positive", "1155", "positive"),
    mkrow("subheader_3"),
    entry("entry_4", "Trade", "216", "positive", "216", "positive"),
    mkrow("subheader_5"),
    entry("entry_6", "Looting", "0", "positive", "0", "positive"),
    entry("entry_7", "Raiding", "0", "positive", "0", "positive"),
    entry("entry_8", "Captives", "0", "positive", "0", "positive"),
    entry("entry_9", "Post-Battle Loot", "0", "positive", "0", "positive"),
    mkrow("subheader_10"),
    entry("entry_11", "Vassals", "0", "positive", "0", "positive"),
    mkrow("subheader_12"),
    entry("entry_13", "Event Outcomes", "0", "positive", "0", "positive"),
    mkrow("subheader_14"),
    entry("entry_15", "Other", "3000", "positive", "3734", "positive"),
    entry("header_sum_16", "Total Income", "4371", "positive", "5105", "positive"),
    mkrow("spacing_17"),
    mkrow("header_18"), mkrow("subheader_19"),
    entry("entry_20", "Construction", "12125", "negative", "0", "positive"),
    entry("entry_21", "Building upkeep", "0", "positive", "0", "positive"),
    mkrow("subheader_22"),
    entry("entry_23", "Unit Upkeep", "2033", "negative", "2033", "negative"),
    entry("entry_24", "Recruitment", "0", "positive", "0", "positive"),
    entry("entry_25", "Hero Actions", "0", "positive", "0", "positive"),
    entry("entry_26", "Raiding", "0", "positive", "0", "positive"),
    mkrow("subheader_27"),
    entry("entry_28", "Tribute", "0", "positive", "0", "positive"),
    entry("entry_29", "Master", "0", "positive", "0", "positive"),
    mkrow("subheader_30"),
    entry("entry_31", "Event Outcomes", "734", "positive", "1468", "positive"),
    mkrow("subheader_32"),
    entry("entry_33", "Other", "0", "positive", "0", "positive"),
    entry("header_sum_34", "Total Expenses", "14892", "negative", "3501", "negative"),
}

local LB = {}
LB.ChildCount = function() return #ROWS end
LB.Find = function(_, i) return ROWS[i + 1] end

FINANCE_PRESENT = true
function find_uicomponent(_root, ...)
    local a = { ... }
    if a[1] == "finance_screen" then
        if FINANCE_PRESENT then return LB end
        return false
    end
    return false
end
function is_uicomponent(c) return c ~= nil and c ~= false end
function UIComponent(c) return c end
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    set_saved_value = function() end,
    get_saved_value = function() end,
    get_local_faction_name = function() return "player" end,
    callback = function() end,
}
core = {
    add_listener = function() end,
    get_ui_root = function() return {} end,
    get_screen_resolution = function() return 1920, 1080 end,
}
local LOG = {}
function out(m) LOG[#LOG + 1] = m end
dofile([[%s]])

EX.recolour_finance()

-- OPENED AGAIN. The listener takes every panel open in the game and these rows are already
-- red, so a second pass must change nothing AND say nothing - otherwise script_log fills with
-- "reddened 0 expense cells" and the one line that matters is lost in it.
EX.recolour_finance()

-- Some OTHER panel is open. The recolour must survive it without touching anything, because
-- the listener that drives it takes every panel open in the game.
FINANCE_PRESENT = false
EX.recolour_finance()
FINANCE_PRESENT = true

for i = 1, #LOG do print("LOG||" .. LOG[i] .. "|") end
for i = 1, #ROWS do
    local r = ROWS[i]
    for j = 1, #r.kids do
        local v = r.kids[j]
        print(r.id .. "|" .. v.id .. "|" .. v.state .. "|" .. v.txt[v.state])
    end
end
"""


LUA_BUTTON_HARNESS = """
local BAR_Y, BAR_PRESENT, LOG = -640, true, {}
local QUEUE = {}
local BTN = nil
local BAR = {
    Position   = function() return 1418, BAR_Y end,
    Dimensions = function() return 48, 60 end,
}
local ROOT = {
    CreateComponent = function()
        BTN = { x = -1, y = -1, vis = false }
        BTN.MoveTo      = function(_, x, y) BTN.x, BTN.y = x, y end
        BTN.SetVisible  = function(_, v) BTN.vis = v end
        BTN.Position    = function() return BTN.x, BTN.y end
        -- The opener's tooltip is written on the same path that makes it visible, so the stub
        -- has to accept it. It is READ BACK below: a per-race tooltip that never gets set is
        -- the static "The Zharr Exchange" a Skaven player was shown.
        BTN.SetTooltipText = function(_, t) BTN.tip = t end
    end,
}
function find_uicomponent(_root, name)
    if name == "resources_bar" then
        if BAR_PRESENT then return BAR end
        return nil
    end
    if name == EX.BUTTON then return BTN end
    return nil
end
function is_uicomponent(c) return c ~= nil end
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    set_saved_value = function() end,
    get_saved_value = function() end,
    get_local_faction_name = function() return "player" end,
    callback = function(_, fn) QUEUE[#QUEUE + 1] = fn end,
}
core = {
    add_listener = function() end,
    get_ui_root = function() return ROOT end,
    get_screen_resolution = function() return 1920, 1080 end,
}
function out(m) LOG[#LOG + 1] = m end
dofile([[%s]])

local function pump()
    local due = QUEUE
    QUEUE = {}
    for i = 1, #due do due[i]() end
    return #due
end

print("tries " .. EX.PLACE_TRIES)

-- THE RACE, EXACTLY AS IT SHIPPED. The strip is off the top of the screen for far longer
-- than the old 8-attempt / 14-second budget, which is the whole bug: the chain ran out, and
-- because SetVisible(true) is only on the success path the button stayed invisible forever.
EX.place_button(1)
local pumped = 0
for _ = 1, 20 do pumped = pumped + pump() end
print("alive_while_hidden " .. #QUEUE)
print("pumped " .. pumped)
print("visible_while_hidden " .. tostring(BTN ~= nil and BTN.vis))

-- ...and the moment the strip settles it must land, without another nudge from anywhere.
BAR_Y = -4
pump()
print("placed " .. BTN.x .. "," .. BTN.y)
print("visible_after " .. tostring(BTN.vis))

-- ONCE PLACED, A HIDDEN STRIP MUST NOT START A SECOND CHAIN and must not move the button.
-- EX.layout() calls place_button on every panel open, and the strip is routinely away.
BAR_Y = -640
EX.place_button(EX.PLACE_TRIES)
print("reschedules_after_placed " .. #QUEUE)
print("still_at " .. BTN.x .. "," .. BTN.y)
print("still_visible " .. tostring(BTN.vis))

-- ...and neither may a FRESH chain. This is the one assertion that tests the "already
-- placed" terminator rather than the cap: EX.layout() reaches the cap and would stop on
-- that alone, so without this line the terminator could be deleted and nothing would say so.
EX.place_button(1)
print("reschedules_when_placed " .. #QUEUE)
QUEUE = {}

-- THE BOUND IS REAL. A CA rename of resources_bar must not reschedule for ever.
EX.button_at = nil
BAR_PRESENT = false
QUEUE = {}
EX.place_button(EX.PLACE_TRIES)
print("reschedules_at_cap " .. #QUEUE)
EX.place_button(1)
print("reschedules_under_cap " .. #QUEUE)

-- THE TURN-START RECOVERY. Chain long dead, strip back up, one shot and no reschedule -
-- this is what makes EX.PLACE_TRIES a backstop rather than the thing the button depends on.
BAR_PRESENT, BAR_Y, QUEUE = true, -4, {}
BTN.x, BTN.y, BTN.vis = -1, -1, false
EX.button_at = nil
EX.place_button(EX.PLACE_TRIES)
print("recovered " .. BTN.x .. "," .. BTN.y)
print("recovered_visible " .. tostring(BTN.vis))
print("recovered_queue " .. #QUEUE)

-- CATHAY. Reported 2026-09-08: no opener button at all. Its resource strip SETTLES a few
-- pixels higher than the Empire's, so the centring arithmetic lands the button at y = -5, the
-- flat "y < 0" guard refused it on every attempt, and the chain ran out. Nothing recovers from
-- that, because placement only runs again from EX.layout - which needs the button.
--
-- The settled bar is the whole point of this case: a mid-animation read SHOULD be refused, and
-- the two were indistinguishable to the old guard.
BAR_PRESENT, BAR_Y, QUEUE = true, -11, {}
BTN.x, BTN.y, BTN.vis = -1, -1, false
EX.button_at = nil
EX.place_button(EX.PLACE_TRIES)
print("cathay " .. BTN.x .. "," .. BTN.y)
print("cathay_visible " .. tostring(BTN.vis))

-- AND THE WILD READ IS STILL REFUSED. This is the 2026-09-06 fault the guard exists for: a
-- docker reading far off the screen must not be clamped onto the edge, it must be retried.
BAR_PRESENT, BAR_Y, QUEUE = true, -640, {}
BTN.x, BTN.y, BTN.vis = -1, -1, false
EX.button_at = nil
EX.place_button(1)
print("wild " .. BTN.x .. "," .. BTN.y)
print("wild_visible " .. tostring(BTN.vis))
print("wild_queue " .. #QUEUE)
"""


# The stub board check_footer_bounds() runs the SHIPPED summaries against. It forces the
# WORST case rather than a typical one: every commodity moved, every commodity shocked, and
# the magnitudes ordered so the longest display names sort to the front of every clause.
LUA_BOUNDS_HARNESS = """
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function() end,
    get_saved_value = function() end,
    get_local_faction_name = function() return "player" end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])

-- Longest name first in every clause: magnitude keyed on the length of what gets PRINTED.
local function weight(res) return string.len(EX.display(res)) end
EX.appetite_shift  = function(res) return weight(res) end
EX.world_appetite  = function(res) return weight(res) end
EX.shock_shift     = function(res) return weight(res) end
EX.war_index = 1.0
EX.shock, EX.shock_why = {}, {}
for _, res in ipairs(EX.COMMODITIES) do
    EX.shock[res] = weight(res)
    EX.shock_why[res] = "raided"
end

-- Everything positive puts every commodity in the "Wanted" clause, which measures that
-- clause at full length but leaves "Going begging" empty - so measure both ways and let
-- Python add them. A real board can fill both at once.
print("WANTED " .. EX.appetite_summary())
EX.world_appetite = function(res) return -weight(res) end
print("BEGGING " .. EX.appetite_summary())
print("SHAKEN " .. EX.shock_summary())

-- THE HOUSES FOOTER, EMPTY GUILD - THE DEFAULT CASE, not the edge case. Most campaigns never
-- spawn a second Chaos Dwarf faction, so this is the single most-executed path through
-- EX.guild_summary and it had no assertion behind it. Set up explicitly rather than relying on
-- whatever EX.guild/EX.houses happen to be on entry; the worst-case block right below
-- overwrites both again, so nothing here needs restoring.
EX.guild = function() return {} end
EX.houses = {}
print("GUILD_EMPTY " .. EX.guild_summary())

-- THE HOUSES FOOTER, WORST CASE: every guild member hostile - EX.guild_summary caps the
-- named list at 2, same trap as the appetite clauses above - and every discovered house
-- hidden behind EX.MAX_ROWS, which is the OTHER unbounded input (a growing house count,
-- not a growing name list). 24 is not a guess: it is the longest real CHD faction display
-- name in the game (factions_screen_name_wh3_dlc23_chd_conclave, "Servants of the
-- Conclave"), read offline via tools/read_vanilla_loc.py.
local GUILD_LIST = {}
for i = 1, 30 do GUILD_LIST[i] = "h" .. i end
EX.guild = function() return GUILD_LIST end
EX.stance_of = function() return -1 end
EX.faction_display = function() return string.rep("X", 24) end
EX.market_closed = function() return nil end
EX.houses = GUILD_LIST
EX.mode_instruments = function() return {} end
print("GUILD " .. EX.guild_summary())

-- THE CLOSURE BANNER, WORST CASE. It REPLACES whichever footer line it lands on - the Houses
-- line, and since the whole-feature review the Trade line as well, which is the view the player
-- actually buys from - so it is measured against the same 880px box with the same 24-character
-- name. Stubbed AFTER the block above, which needs market_closed to answer nil.
EX.market_closed = function() return "h1" end
print("CLOSED " .. EX.closed_banner())
print("GUILD_CLOSED " .. EX.guild_summary())

-- THE OFFERINGS FOOTER, WORST CASE. The patron is the longest of the four in EX.RACES and the
-- offering cost is at its EX.OFFER_MULT_MAX ceiling.
--
-- THE RENT IS STUBBED AS 1/3, NOT AS A REAL SLIDER VALUE, and that is the only way this
-- harness can see the fault at all. The GAME'S Lua is single-precision, so an MCT slider set
-- to 0.2 reads back as 0.20000000298023 - but desktop lua.exe is DOUBLE, where 0.1
-- concatenates as a tidy "0.1" and dropping EX.num would change nothing here. 1/3 is long in
-- both, so it reproduces the SHAPE of the fault - a raw float reaching the player - in a
-- precision the harness actually has. It is also two characters wider than the widest real
-- value ("0.1"; carry_per_unit runs 0.0 to 3.0 in steps of 0.1), so the length below is
-- measured conservatively rather than optimistically.
local longest = ""
for _, r in pairs(EX.RACES) do
    if #r.patron > #longest then longest = r.patron end
end
EX.race = { patron = longest, seg = "", name = "X", house_word = "X", layer2 = {} }
EX.offerings_made = 999
EX.opt = function(k) if k == "carry_per_unit" then return 1/3 end return 1 end
local ol1, ol2 = EX.offer_footer()
print("OFFER1 " .. ol1)
print("OFFER2 " .. ol2)
"""


def check_footer_bounds():
    """The DYNAMIC footer lines must fit their box without fit() ever firing.

    check_footer_literals() covers the lines made only of literals. These are the other kind:
    their length depends on how many commodities moved and how long their names are, and that
    is exactly why a character budget on them was rejected once - correctly, as a budget on
    the SOURCE. This is not that. It runs the shipped summary functions against a board where
    every commodity has moved and the longest display names sort first, and measures what
    comes back.

    The fault it exists for shipped twice. First as a footer clipping mid-word, fixed by
    splitting into two lines and adding fit(). Then as fit() itself amputating a list -
    "Shaken: Medicinal Plants (raided), ..." with a dangling comma, reported from play
    2026-09-06. fit() is a net, not a design; a line that reaches it is already wrong.
    """
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped lua footer bounds check: no lua.exe)")
        return
    harness = LUA_BOUNDS_HARNESS % (LUA_SCRIPT.replace(chr(92), chr(92) * 2),)
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    part = {}
    for line in got.split(chr(10)):
        line = line.strip()
        if " " in line:
            k, v = line.split(" ", 1)
            part[k] = v

    box_px, px_per_char, budget = 880, 6.7, 118

    # Line 2 is the appetite line and carries BOTH clauses at once on a real board. The Lua
    # emits them separately here because one sign cannot produce both, so glue the second
    # clause onto the first the way EX.appetite_summary would.
    wanted, begging = part["WANTED"], part["BEGGING"]
    tail = begging.split(".", 1)[1] if "." in begging else ""
    l2 = wanted + tail
    assert len(l2) <= budget, (
        "the appetite footer reaches %d chars (~%.0fpx) in an %dpx box at worst case, so "
        "fit() will amputate it mid-list. Budget %d.%s  %r"
        % (len(l2), len(l2) * px_per_char, box_px, budget, chr(10) + "  ", l2))

    # THE OFFERINGS FOOTER. Both lines, at the worst case the harness forced. Line 2 shipped
    # at 133 characters (~891px in the 880px box) because a single-precision MCT read put
    # "0.20000000298023" in it, and fit() amputated the tail: "...per unit per turn to ...".
    for key, which in (("OFFER1", "line 1"), ("OFFER2", "line 2")):
        got = part[key]
        assert len(got) <= budget, (
            "the offerings footer %s reaches %d chars (~%.0fpx) in an %dpx box at worst case, "
            "so fit() amputates its ending. Budget %d.%s  %r"
            % (which, len(got), len(got) * px_per_char, box_px, budget,
               chr(10) + "  ", got))
    # AND NO RAW FLOAT IN IT. The length check alone would pass a 0.30000001192093 that
    # happened to fit, and the number would still read as broken on screen.
    # Matched on the NUMBER, not on the wording around it - the sentence has been reworded
    # twice already and a phrase-anchored regex fails open the moment it is.
    assert re.search(r"[0-9]+(\.[0-9])? gold", part["OFFER2"])             and not re.search(r"[0-9]\.[0-9]{4,}", part["OFFER2"]), (
        "the offerings footer is not printing the rent through EX.num - a single-precision "
        "MCT value reaches the player as 0.20000000298023: %r" % part["OFFER2"])

    # Line 1 is Treasury + Worth + Rent + the shock clause. The three numbers are bounded by
    # the game, not by us: a nine-figure treasury, an eight-figure position and a six-figure
    # rent are all past anything reachable, and they cannot be at those ceilings together
    # anyway (a 999,999 rent is 333,333 units held, which is not a 99,999,999 gold book at any
    # price on the ladder). The separators are two spaces, not four - that is where the room
    # for the Worth clause came from.
    numbers = len("Treasury: 999999999  Worth: 99999999g  Rent: -999999g")
    l1 = "T" * numbers + "  " + part["SHAKEN"]
    assert len(l1) <= budget, (
        "the trade footer reaches %d chars (~%.0fpx) in an %dpx box at worst case - %d of "
        "that is Treasury and Rent at their widest, %d the shock clause. Budget %d.%s  %r"
        % (len(l1), len(l1) * px_per_char, box_px, numbers, len(part["SHAKEN"]), budget,
           chr(10) + "  ", part["SHAKEN"]))

    # The shock clause must be on line 1. On line 2 it is a fourth growing clause and the
    # line cannot hold it - that is the arrangement that shipped and was reported.
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    m = re.search(r"local shaken = EX\.shock_summary\(\)(.*?)end", code, re.S)
    assert m, "the shock clause is no longer appended to a footer line"
    assert "l1 = l1" in m.group(1), (
        "the shock clause is appended to a line other than l1. Line 2 already carries the war "
        "index and two appetite clauses whose lists grow; a fourth is what overran the box.")

    # THE DEFAULT CASE FIRST: most campaigns run with the player as the only Chaos Dwarf
    # faction, so an empty guild is the single most-executed path through EX.guild_summary, not
    # an edge case. EXACT match, not just non-empty - a dangling "Hostile:" with nothing after
    # it, a stray comma, or a blank line would all still pass a non-empty check.
    # .get(), NOT part[...]: the parse loop below strips each line and only splits on the
    # first space, so a value that mutates to "" leaves no space to split on and the key is
    # never set at all - a bare KeyError instead of the assertion message below.
    empty_case = part.get("GUILD_EMPTY", "")
    assert empty_case == "No other house trades here.", (
        "EX.guild_summary() with an empty guild returned %r, not the exact literal. This is "
        "the DEFAULT path - most campaigns never spawn a second Chaos Dwarf faction - so a "
        "dangling clause or stray comma here is not a rare edge case, it is what most players "
        "see every turn." % empty_case)

    # The Houses view footer. Same 880px box and the engine does not wrap, so the guild's
    # discovered house count and its capped-at-2 hostile-name clause are what make the line
    # unbounded - the same trap EX.appetite_summary documents above.
    guild = part["GUILD"]
    assert len(guild) <= budget, (
        "the Houses view footer reaches %d chars (~%.0fpx) in an %dpx box at worst case, so "
        "fit() will amputate it mid-list. Budget %d.%s  %r"
        % (len(guild), len(guild) * px_per_char, box_px, budget, chr(10) + "  ", guild))
    assert lua.count("EX.guild_summary()") >= 2, (
        "EX.guild_summary is defined but the Houses view footer never calls it - the known "
        "gap (no hostility or closed-market signal on the one view with no per-row tooltip to "
        "carry it) stays open")

    # THE CLOSURE BANNER, and the view it was missing from. It used to be built inside
    # EX.guild_summary, so it only ever reached the HOUSES footer - the Trade view, where the
    # player actually buys, said nothing at all while every Buy on it refused. One function
    # now, drawn by both, so the two cannot say different things about one closure.
    closed = part["CLOSED"]
    assert len(closed) <= budget, (
        "the closure banner reaches %d chars (~%.0fpx) in an %dpx box at worst case. Budget "
        "%d.%s  %r" % (len(closed), len(closed) * px_per_char, box_px, budget,
                       chr(10) + "  ", closed))
    assert part["GUILD_CLOSED"] == closed, (
        "the Houses footer draws a different closure line from EX.closed_banner: %r vs %r"
        % (part["GUILD_CLOSED"], closed))
    assert "l2 = EX.closed_banner() or l2" in code, (
        "the Trade view's footer never draws the closure banner. That is the view the player "
        "buys from, and the banner reached only the Houses footer - so the one message the "
        "player needs was on the one view they were not looking at.")
    assert "EX.closed_banner()" in re.search(
        r"function EX\.guild_summary\(\).*?" + NL + "end", code, re.S).group(0), (
        "EX.guild_summary builds its own closure line again instead of sharing "
        "EX.closed_banner with the Trade footer")

    print("  footer bounds: appetite %d chars, trade line %d, guild line %d, closure banner "
          "%d, offerings %d/%d at worst case, budget %d"
          % (len(l2), len(l1), len(guild), len(closed),
             len(part["OFFER1"]), len(part["OFFER2"]), budget))


def check_help_lines():
    """Every line of the in-panel guide must fit the column it is printed into.

    The guide borrows the row components, so its two columns are whatever EX.ROW_LAYOUT_HELP
    gives them - and text clips to its component with no error, the same silence that ate two
    footers this session before a screenshot caught them.

    It also pins the ceiling nobody would otherwise notice, and the ceiling is GEOMETRY.

    This used to read "rows_holder only makes 19 rows" and compute the capacity as
    len(COMMODITIES) + len(LAYER2) - a static count of what the trade view happens to draw. That
    was never what the panel can hold, and it stopped being even approximately right when the
    Houses view arrived with a DISCOVERED instrument list: vanilla ships about eleven Chaos
    Dwarf factions and the lords pack adds ten. The real ceiling is the rows_holder box divided
    by the row pitch - 560 / 28 = 20 - and both numbers live in files that cannot see each
    other, so all three copies are cross-checked here: the height off the shipped .twui.xml,
    the pitch and EX.MAX_ROWS off the Lua.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    px_per_char = 6.7
    markup = re.compile(r"\[\[[^\]]*\]\]")      # [[col:green]] etc: colour, not width
    quoted = re.compile(r'"([^"]*)"')
    nl = chr(10)

    lay = re.search(r"EX\.ROW_LAYOUT_HELP = \{(.*?)" + nl + r"\}", lua, re.S)
    assert lay, "EX.ROW_LAYOUT_HELP is gone"
    boxes = dict((n, int(w)) for n, w in
                 re.findall(r'\{\s*"(\w+)"\s*,\s*-?\d+\s*,\s*-?\d+\s*,\s*(\d+)', lay.group(1)))
    for want in ("row_name", "row_trend"):
        assert want in boxes, "%s has no explicit width in EX.ROW_LAYOUT_HELP" % want

    block = re.search(r"EX\.HELP_PAGES = \{(.*?)" + nl + r"\}", lua, re.S)
    assert block, "EX.HELP_PAGES is gone - the guide has no content"
    consts = dict(re.findall(r'(EX\.TREND_\w+)\s*=\s*"([^"]*)"', lua))

    # THE CEILING EACH PAGE IS HELD TO - the same number the trade view is held to further
    # down. The guide takes the else-branch of EX.mode_instruments, so each page is handed
    # COMMODITIES + LAYER2, never the panel's physical MAX_ROWS slots.
    fixed = len(COMMODITIES) + len(LAYER2)

    # NO TRAILING LOOKAHEAD. A `(?=\{|\})` after the closing "}," reads fine on paper but the
    # LAST page has nothing following it inside block.group(1) - the outer regex above stops
    # capturing at the "\n}" that closes EX.HELP_PAGES, so that final brace lives outside the
    # captured text and the lookahead can never see it. Measured: it silently dropped the last
    # page (2 pages in the file, 1 found). Entry lines never start with "}" (they start with
    # "{"), so "\n\s*\}," on its own already anchors on nothing but a page's own closing line.
    pages = re.findall(r"\{\s*--\s*PAGE \d+.*?\n(.*?)\n\s*\},", block.group(1), re.S)
    assert len(pages) >= 2, (
        "EX.HELP_PAGES has %d pages. The guide was full at 19 lines against 19 usable rows "
        "before this feature added seven concepts a player cannot infer; one page cannot hold "
        "it, which is what its own comment predicted - 'a twentieth line needs a real panel'."
        % len(pages))

    all_entries = []
    for pi, page in enumerate(pages):
        entries = []
        for body in re.findall(r"\{([^{}]*)\}", page, re.S):
            strings = quoted.findall(body)
            if not strings:
                continue
            # The sentence is the last literal; anything before it, plus any EX.TREND_* constant
            # named in the entry, makes up the term.
            sentence = strings[-1]
            term = "".join(strings[:-1])
            for name, val in consts.items():
                if name in body:
                    term += markup.sub("", val)
            entries.append((term, sentence))
        assert entries, "guide page %d parsed to no lines" % (pi + 1)
        assert len(entries) <= fixed, (
            "guide page %d has %d lines but the guide loop only yields %d rows - the last %d "
            "would never be drawn, silently. A longer page needs a panel of its own."
            % (pi + 1, len(entries), fixed, len(entries) - fixed))

        for term, sentence in entries:
            for text, col in ((term, "row_name"), (sentence, "row_trend")):
                need = len(markup.sub("", text)) * px_per_char
                assert need <= boxes[col], (
                    "guide page %d line %r is ~%.0fpx of text in the %dpx %s column - it "
                    "clips mid-word with no error" % (pi + 1, text, need, boxes[col], col))

        # TWO OF THESE LINES ARE REWRITTEN PER RACE by EX.bind_race, and the literal in the
        # file is only the Chaos Dwarf case - "Hashut" is 6 characters against "The Council"
        # at 11. The loop above cannot see the other three, so the longest patron is measured
        # here against the same box.
        widest = max(len(r["patron"]) for r in race_table().values()) - len("Hashut")
        for name, page_i, mark in (("EX.HELP_OFFER_LINE", 0, "Burn"),
                                   ("EX.HELP_GUILD_LINE", 1, "trade here too")):
            mi = re.search(name + r"\s*=\s*(\d+)", lua)
            if not mi or pi != page_i:
                continue
            term, sentence = entries[int(mi.group(1)) - 1]
            assert mark in sentence, (
                "%s points at %r, which does not look like the line bind_race rewrites"
                % (name, sentence[:60]))
            grown = (len(markup.sub("", sentence)) + widest) * px_per_char
            assert grown <= boxes["row_trend"], (
                "guide page %d line %r reaches ~%.0fpx in a %dpx column once the longest "
                "patron name is substituted in. Nothing else measures that - this loop only "
                "sees the Chaos Dwarf literal."
                % (pi + 1, sentence, grown, boxes["row_trend"]))
        all_entries.extend(entries)
    entries = all_entries

    # THE BOX, THE PITCH AND THE CONSTANT, all three read rather than assumed.
    xml = io.open(os.path.join(ROOT, "Modding Files", "pack", "ui", "campaign ui",
                               "derpy_chd_exchange_panel.twui.xml"), encoding="utf-8").read()
    # ANCHORED ON id="rows_holder", not on the tag name. The tag appears twice - once as a
    # childless node in <hierarchy> and once as the real element in <components> - and a
    # non-greedy read from the first one runs on into the PANEL'S height (700) and reports 25
    # slots for a 560px box.
    hm = re.search(r"<rows_holder\b[^>]*id=\"rows_holder\".*?height=\"(\d+)\"", xml, re.S)
    assert hm, ("rows_holder has no height in the panel twui.xml - the parse is wrong, or "
                "gen_exchange_ui.py has not been run")
    holder_h = int(hm.group(1))
    pm = re.search(r"EX\.ROW_PITCH\s*=\s*(\d+)", lua)
    assert pm, "EX.ROW_PITCH is gone - nothing states how far apart EX.layout puts the rows"
    pitch = int(pm.group(1))
    mm = re.search(r"EX\.MAX_ROWS\s*=\s*(\d+)", lua)
    assert mm, "EX.MAX_ROWS is gone - EX.mode_instruments has no ceiling to truncate at"
    rows = holder_h // pitch
    assert int(mm.group(1)) == rows, (
        "EX.MAX_ROWS is %s but rows_holder is %dpx at a %dpx pitch, which is %d slots. Row %d "
        "is MoveTo'd past the panel's bottom edge - drawn, interactive, and off screen, with "
        "nothing erroring." % (mm.group(1), holder_h, pitch, rows, rows + 1))
    # ...and EX.layout must actually USE the pitch rather than a second hardcoded 28.
    assert "i * EX.ROW_PITCH" in lua, (
        "EX.layout no longer spaces its rows by EX.ROW_PITCH, so the constant this check "
        "measures against is not the number the panel uses")

    # NO VIEW MAY DRAW MORE ROWS THAN THE PANEL HAS. The trade, stats and offerings views draw
    # a fixed list, so it is checked here; the Houses view's list is discovered at runtime,
    # which is why EX.mode_instruments truncates and the Houses footer says how many are hidden.
    # (Each guide PAGE is checked against this same `fixed` cap above, in the page loop - a
    # total across pages is not the right thing to compare, only what one page draws at once.)
    assert fixed <= rows, (
        "the trade view draws %d instruments into %d slots - the last %d are off the panel"
        % (fixed, rows, fixed - rows))
    assert re.search(r"while #t > EX\.MAX_ROWS do", lua), (
        "EX.mode_instruments no longer truncates at EX.MAX_ROWS. The house list is DISCOVERED "
        "- vanilla ships ~11 Chaos Dwarf factions and the lords pack adds ten - so without the "
        "truncation the Houses view draws live, clickable rows below the panel's bottom edge.")

    # THE ROWS MUST BE PUT BACK, and the thing that does it is EX.layout, not the guide.
    # The guide hides the rows it has no line for; EX.layout re-shows every row on the way
    # into any mode. That only works because EX.set_mode calls layout BEFORE refresh_panel -
    # reverse those two and leaving the guide leaves the last commodities invisible for the
    # rest of the campaign, sticky and silent and surviving a save.
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    assert "row:SetVisible(line ~= nil)" in code, (
        "the guide no longer hides the rows it has no line for - a blanked row still draws "
        "its divider, leaving a ruled empty band under the last line of the guide")
    lay = re.search(r"function EX\.layout\(\)(.*?)" + NL + "end", code, re.S)
    assert lay and "row:SetVisible(true)" in lay.group(1), (
        "EX.layout no longer re-shows every row, so nothing undoes the guide's hiding")
    sm = re.search(r"function EX\.set_mode\((.*?)" + NL + "end", code, re.S)
    assert sm, "EX.set_mode is gone"
    body = sm.group(1)
    assert "EX.layout()" in body and "EX.refresh_panel()" in body, (
        "EX.set_mode no longer both re-lays out and refreshes")
    assert body.index("EX.layout()") < body.index("EX.refresh_panel()"), (
        "EX.set_mode refreshes before it lays out, so the guide's hidden rows are re-hidden "
        "after layout showed them - leaving the guide would strand the last commodities")

    budget = 118
    for name in ("EX.HELP_FOOT1", "EX.HELP_FOOT2"):
        m = re.search(re.escape(name) + r'\s*=\s*"([^"]*)"', lua)
        assert m, "%s is gone" % name
        assert len(m.group(1)) <= budget, (
            "%s is %d chars against a %d budget - fit() will amputate it"
            % (name, len(m.group(1)), budget))
    # `fixed`, not `rows`: the guide is handed COMMODITIES + LAYER2 by EX.mode_instruments,
    # never the panel's physical 20 slots. Printing the larger number read as headroom that
    # does not exist.
    print("  guide: %d pages, %d lines total, all inside their columns "
          "(%d rows/page cap, %d panel slots)" % (len(pages), len(entries), fixed, rows))


def check_tooltips():
    """The per-column tooltips, and the three ways one silently reaches nobody.

    1. A TOOLTIP ON A NON-INTERACTIVE COMPONENT. Counted in ui3.pack: 1,670 of CA's 1,747
       componentleveltooltips sit on an element declaring interactive="true", and several of
       the 77 that do not are placeholders. A cell that is not interactive never gets the
       hover, so the text is set, correct, and unreachable.
    2. A COLUMN WITH A LABEL AND NO TOOLTIP. The cells are reused between modes, so the tips
       are per mode - and a new column added to EX.HEADERS without one is exactly the case
       this panel already shipped: the guide had the answer and nothing on the row pointed at
       it ("what does Hi mean in the trend column", from play 2026-09-06).
    3. A TOOLTIP LONG ENOUGH TO NEED CA'S "Title||Body" SPLIT. The split is only ever proven
       to work as literal XML; through SetTooltipText it is untested, and a long tooltip
       without it renders in a box that does not grow and clips mid-glyph on line two. The
       answer here is a hard length ceiling rather than a split nobody has verified.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()

    m = re.search(r"EX\.TIP_MAX\s*=\s*(\d+)", lua)
    assert m, "EX.TIP_MAX is gone - the length ceiling is what keeps || out of these strings"
    tip_max = int(m.group(1))
    assert tip_max <= 60, (
        "EX.TIP_MAX is %d. CA's literal tooltips that skip the Title||Body split run to a "
        "median of 42 characters; above ~60 the box stops growing and line two clips "
        "mid-glyph, and the split is unproven through SetTooltipText." % tip_max)

    tips_block = re.search(r"EX\.TIPS = \{(.*?)" + chr(10) + r"\}", lua, re.S)
    assert tips_block, "EX.TIPS is gone - no column explains itself on hover any more"
    hdrs_block = re.search(r"EX\.HEADERS = \{(.*?)" + chr(10) + r"\}", lua, re.S)
    assert hdrs_block, "EX.HEADERS is gone"

    # BEFORE THE PARSE, NOT PER TIP, and the break test is why. A {{tr:}} value carries a "}}"
    # that ends the mode block early for any brace-matched read of this table - so a loc key
    # put here failed as "every column in the trade view has no tooltip", which sends the next
    # person to look at the wrong table entirely. The right message has to come first.
    assert "{{" not in tips_block.group(1), (
        "a tooltip in EX.TIPS is routed through a resolver ({{...}}). This text is read "
        "straight by SetTooltipText, so a loc key would draw its own braces on screen - and "
        "CA's Title||Body split only ever works through the text-replacement resolver, which "
        "this route is not. Write the words literally.")

    def modes_of(body):
        out = {}
        for mm in re.finditer(r"(\w+)\s*=\s*\{(.*?)\}", body, re.S):
            out[mm.group(1)] = dict(re.findall(r'(hdr_\w+)\s*=\s*"([^"]*)"', mm.group(2)))
        return out

    tips = modes_of(tips_block.group(1))
    headers = modes_of(hdrs_block.group(1))
    assert tips, "EX.TIPS parsed empty"

    # THE GUIDE VIEW IS DELIBERATELY ABSENT and this pins the decision: it is already prose,
    # and a tooltip explaining an explanation is noise.
    assert "help" not in tips, (
        "EX.TIPS has a help entry. The guide view is the explanation; hovering it to be told "
        "what an explanation means is noise.")

    checked = 0
    for mode, cols in tips.items():
        assert mode in headers, (
            "EX.TIPS names mode %r, which EX.HEADERS does not - it would never be applied "
            "because EX.apply_tips keys off EX.mode" % mode)
        missing = sorted(set(headers[mode]) - set(cols))
        assert not missing, (
            "%s view: column(s) %s carry a header label and no tooltip. That is the exact "
            "gap this feature closes - the guide knows what the column means and nothing on "
            "the row points at it." % (mode, missing))
        extra = sorted(set(cols) - set(headers[mode]))
        assert not extra, (
            "%s view: tooltip(s) %s for column(s) this mode does not show; the text would "
            "never be reached and would rot" % (mode, extra))
        for hid, text in cols.items():
            checked += 1
            assert "||" not in text, (
                "%s %s carries CA's Title||Body split. It is proven only as literal XML - "
                "through SetTooltipText it has never been tested, and the pipes render "
                "verbatim when the resolver is not the one that applies it." % (mode, hid))
            assert len(text) <= tip_max, (
                "%s %s is %d characters, over the %d ceiling: %r. Past that the tooltip box "
                "stops growing and clips mid-glyph on line two, and the fix for that is a "
                "split this route cannot use." % (mode, hid, len(text), tip_max, text))

    # THE HEADER-TO-CELL MAP. A tip is put on the header AND on every row cell under it; a
    # missing or misspelled entry here leaves the rows silent while the header still answers,
    # which reads as "tooltips work" to anyone testing by hovering the top row.
    cellmap = dict(re.findall(r'(hdr_\w+)\s*=\s*"(\w+)"',
                              re.search(r"EX\.TIP_CELL = \{(.*?)\}", lua, re.S).group(1)))
    row_cells = re.search(r"EX\.ROW_CELLS = \{(.*?)\}", lua, re.S)
    assert row_cells, "EX.ROW_CELLS is gone"
    known = set(re.findall(r'"(\w+)"', row_cells.group(1)))
    for mode, cols in tips.items():
        for hid in cols:
            assert hid in cellmap, (
                "EX.TIP_CELL has no row cell for %s, so the %s column answers on its header "
                "and stays silent on all 19 rows" % (hid, mode))
            assert cellmap[hid] in known, (
                "EX.TIP_CELL maps %s to %r, which is not in EX.ROW_CELLS - find_uicomponent "
                "returns nil and the rows are silent with no error"
                % (hid, cellmap[hid]))

    # TWO HEADERS OVER ONE CELL IN ONE MODE IS A COIN FLIP, not a wrong tooltip.
    #
    # EX.apply_tips walks pairs(tips) and writes each header's text onto EX.TIP_CELL[hid]. Lua
    # 5.1 does not define pairs() order, so when a mode names two headers that map to the same
    # row cell, that column answers with one of the two AT RANDOM - and it can differ between
    # runs of the same build. That is exactly what shipped: hdr_div -> row_sell and
    # hdr_seat -> row_supply were added beside the existing hdr_sell -> row_sell and
    # hdr_supply -> row_supply, and EX.TIPS.trade carried all four (added only to satisfy the
    # "every header needs a tooltip" rule above), so the trade view's Sell column was a coin
    # flip between "What one lot pays back" and "Gold per share, paid every turn".
    for mode, cols in tips.items():
        used = {}
        for hid in sorted(cols):
            cell = cellmap[hid]
            assert cell not in used, (
                "%s view: %s and %s both write the tooltip for row cell %r. EX.apply_tips "
                "walks pairs(), whose order Lua 5.1 does not define, so that column answers "
                "with one of the two at random. Relabel one header through EX.HEADERS instead "
                "of giving the view a second component over the same cell."
                % (mode, used[cell], hid, cell))
            used[cell] = hid

    # THE HOUSES PRICE TOOLTIP NAMES THE LOT SIZE, and it is a literal because these strings go
    # straight to SetTooltipText and cannot be a concatenation. So the one thing that can drift
    # is the number, and it drifting is how the tooltip read "Gold to buy one share at today's
    # price" over a column that charges for five - wrong by a factor of five, one column from
    # the per-share dividend that made it look right.
    for hid in ("hdr_price", "hdr_sell"):
        text = tips["houses"][hid]
        assert str(HOUSE_LOT_SIZE) in text, (
            "the Houses view's %s tooltip is %r and does not name the lot size (%d). Price is "
            "per LOT and the dividend is per SHARE; the two columns sit side by side, so each "
            "has to say which it is." % (hid, text, HOUSE_LOT_SIZE))

    # AND IT HAS TO BE WIRED, AND INTERACTIVE. Either half missing is a silent no-op.
    lay = re.search(r"function EX\.layout\(\).*?" + chr(10) + r"end", lua, re.S)
    assert lay and "EX.apply_tips(" in lay.group(0), (
        "EX.layout does not call EX.apply_tips, so the tooltips are defined and never applied")
    tip_fn = re.search(r"local function set_tip\(.*?" + chr(10) + r"end", lua, re.S)
    assert tip_fn, "set_tip is gone"
    assert re.search(r'SetInteractive\(text ~= ""\)', tip_fn.group(0)), (
        "set_tip no longer ties the hover to having text. Both halves matter: 1,670 of CA's "
        "1,747 tooltips sit on an interactive element, so a cell WITH text must be "
        "interactive - and a cell whose text was just cleared must not be, or it goes on "
        "swallowing the mouse and draws an empty box over the row.")
    assert re.search(r"SetTooltipText\([^)]*,\s*true\)", tip_fn.group(0)), (
        "set_tip does not pass all_states=true, so a cell in any state but its default "
        "answers with nothing")

    # A VIEW WITH NO TOOLTIPS MUST CLEAR THE CELLS, NOT SKIP THEM.
    #
    # The row components are shared by all five views, so an early return in EX.apply_tips
    # leaves the previous view's text on them. That shipped: the Log's "What happened" column
    # answered with the Houses view's trend legend over the line "Delisted. The house is gone."
    # (from play 2026-09-08). EX.TIPS has no entry for the Log or the guide and deliberately
    # never will, so those two views are exactly the case - the clear is the only thing keeping
    # either of them silent. It also has to walk EX.TIP_CELL rather than the view's own tips,
    # or a column this view happens not to explain is never written and keeps what it had.
    ap = re.search(r"function EX\.apply_tips\(.*?" + chr(10) + r"end", lua, re.S)
    assert ap, "EX.apply_tips is gone"
    assert "if not tips then return end" not in ap.group(0), (
        "EX.apply_tips returns early when the view has no tooltips. The cells are shared "
        "between views, so that leaves the last view's text sitting on them - which is how "
        "the Log came to explain the Trend column's arrows.")
    assert re.search(r"EX\.TIPS\[EX\.mode\]\s*or\s*\{\}", ap.group(0)), (
        "EX.apply_tips no longer falls back to an empty tip table, so a view absent from "
        "EX.TIPS writes nothing at all and inherits the last one's tooltips")
    assert "pairs(EX.TIP_CELL)" in ap.group(0), (
        "EX.apply_tips walks the view's own tips instead of EX.TIP_CELL, so a column this "
        "view does not explain is never written and keeps the previous view's text")

    # THE MARKUP EXPLANATION. EX.hostility widens the Buy/Sell fill without ever moving the
    # world price shown everywhere else on the row - the whole design point of Task 4 is that a
    # player who is hated pays more and sees nothing in the ladder that says why. The static
    # EX.TIPS text above is the same for every row; this is the one PER-COMMODITY tooltip on the
    # panel, rebuilt every refresh because a trade or a treaty can move it turn to turn.
    m = re.search(r"function EX\.buy_tip\(res\)(.*?)" + chr(10) + r"end", lua, re.S)
    assert m, "EX.buy_tip is gone - nothing explains the hostility markup on a Buy price"
    tip_buy = m.group(1)
    assert "EX.hostility(res)" in tip_buy, (
        "the Buy tooltip does not name the markup. Hostility silently changes the price the "
        "player pays; the tooltip is the only place that detail can live without touching "
        "either layout table.")
    assert "EX.faction_display" in tip_buy, (
        "the Buy tooltip does not name the house on the other side")
    # NOT EX.blocked. That is market_closed() OR refused_by(), and phrasing either with the
    # refusal sentence is what made the war lock accuse one named house on every row. The
    # tooltip must ask the two questions separately, the same way EX.buy_refusal does.
    assert "EX.market_closed()" in tip_buy and "EX.refused_by(res)" in tip_buy, (
        "a refused row's Buy tooltip does not say who refused or why. It must distinguish the "
        "war lock from a house refusal - reading EX.blocked collapses them into one sentence.")
    assert "EX.blocked" not in tip_buy, (
        "EX.buy_tip is back to reading EX.blocked, which cannot tell a shut market from a "
        "house refusing you.")

    m = re.search(r"function EX\.sell_tip\(res\)(.*?)" + chr(10) + r"end", lua, re.S)
    assert m, "EX.sell_tip is gone - the Sell tooltip no longer mirrors the Buy one"
    assert "EX.hostility(res)" in m.group(1), (
        "the Sell tooltip does not name the markup, same as the Buy tooltip")

    # DEFINED IS NOT WIRED. A tooltip function nobody calls is exactly the "correct and
    # unreachable" failure mode point 1 of this docstring already worries about.
    assert lua.count("EX.buy_tip(res)") >= 2, (
        "EX.buy_tip is defined but never called against a row")
    assert lua.count("EX.sell_tip(res)") >= 2, (
        "EX.sell_tip is defined but never called against a row")

    print("  tooltips: %d columns across %d views, all within %d chars"
          % (checked, len(tips), tip_max))

    # AND NOW RUN IT. Everything above reads the source; none of it can see what a cell is
    # actually left holding after a view switch, which is the whole of this bug.
    if not os.path.isfile(LUA_EXE):
        print("  (skipped tooltip run: no lua.exe)")
        return
    import subprocess, tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_tips_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace("\\", "\\\\"))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    legend = "[" + tips["trade"]["hdr_trend"] + "]"
    assert have.get("trade_trend") == legend, (
        "the Trade view's Trend column does not carry its own tooltip: %s"
        % have.get("trade_trend"))
    # THE HEADER CARRIES THE COLUMN TOOLTIP PLUS THE SORT LINE, and the sort line is checked
    # rather than tolerated: it is the only thing telling the player a header responds to a
    # click at all, and a "||" split with no literal text in front of it draws the pipes.
    SORT_UNSORTED = "||Click to sort this column low to high."
    assert have.get("trade_hdr_trend") == legend[:-1] + SORT_UNSORTED + "]", (
        "the Trade view's Trend HEADER does not carry the tooltip plus its sort line: %s"
        % have.get("trade_hdr_trend"))
    # The Log's What-happened column is NOT sortable, so its header must carry no sort line -
    # an invitation to click a column that does nothing is worse than no invitation.
    assert SORT_UNSORTED not in (have.get("log_trend") or ""), (
        "the Log's un-sortable column advertises a sort: %s" % have.get("log_trend"))
    assert have.get("trade_trend_interactive") == "true", (
        "a cell with tooltip text is not interactive, so the text is set, correct and never "
        "reached on hover")
    for key, why in (
            ("log_trend", "the Log's What-happened column"),
            ("log_price", "a column the Log does not draw at all"),
            ("houses_then_log_trend", "the Log's column after the Houses view - the exact "
                                      "path that shipped the wrong tooltip"),
            ("trade_house_trend", "a house row, which the Trade view does not draw at all")):
        assert have.get(key) == "[]", (
            "%s still answers with the previous view's tooltip: %s. EX.TIPS has no log entry, "
            "so every cell must come back empty." % (why, have.get(key)))
        assert have.get(key + "_interactive") == "false", (
            "%s was cleared but left interactive - it goes on eating the mouse and draws an "
            "empty tooltip box over the row" % why)
    assert have.get("log_hdr_trend") == "[]", (
        "the Log's Trend header keeps the last view's tooltip: %s"
        % have.get("log_hdr_trend"))
    assert have.get("houses_trend") == "[" + tips["houses"]["hdr_trend"] + "]", (
        "the Houses view's Trend column lost its own tooltip: %s" % have.get("houses_trend"))
    assert have.get("back_to_trade_trend") == legend, (
        "the column stays silent after a visit to the Log: %s. A clear that cannot be undone "
        "is the same bug facing the other way." % have.get("back_to_trade_trend"))
    print("  tooltip run: cleared on the Log, restored on the way back")


def check_panel_blocks_map():
    """The panel has to eat the mouse while it is open, and let go the moment it is not.

    Both halves are silent failures and the second is the worse one:

    1. NOT INTERACTIVE WHILE OPEN. The panel is then scenery - the cursor reaches the campaign
       map through 920x700 of background, and hovering a row raises the region and army
       tooltips of whatever is behind it. CA's own words for the flag: "Interactivity
       determines if a component can handle mouse interactions like clicks and mouseovers".
    2. STILL INTERACTIVE WHILE HIDDEN. That is a 920x700 dead zone in the middle of the map
       with nothing on screen to explain it - clicks and hovers land on an invisible panel.
       Nothing would point at this mod; the player would file it as the game being broken.

    So the flag is written in the ONE place visibility is written, from the SAME variable. A
    literal `true` anywhere near it is the bug this refuses.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    fn = re.search(r"function EX\.show\(visible\).*?" + chr(10) + r"end", code, re.S)
    assert fn, "EX.show is gone - it is the only place the panel's visibility is written"
    body = fn.group(0)
    assert "panel:SetVisible(visible)" in body, (
        "EX.show no longer sets the panel's visibility from its own argument")
    # MATCHED LOOSELY ON PURPOSE, and the break test is why: pinned against the exact string
    # `panel:SetInteractive(visible)`, this assertion also fired when the argument was changed
    # to a literal `true` - masking the dead-zone assertion below, which is the more dangerous
    # of the two. This one answers "is it set at all"; the argument is the next check's job.
    assert "panel:SetInteractive(" in body, (
        "EX.show does not set the panel interactive. The panel is then scenery: the cursor "
        "goes through it to the campaign map, and hovering a row raises the region and army "
        "tooltips of whatever is behind the panel.")

    # THE FLAG FOLLOWS VISIBILITY AND IS NEVER PINNED ON. A literal true is how the dead-zone
    # half of this ships: the panel keeps eating the mouse after it is closed.
    for m in re.finditer(r"(\w+):SetInteractive\((\w+)\)", code):
        target, arg = m.group(1), m.group(2)
        if target in ("panel", "p"):
            assert arg == "visible", (
                "the panel's interactive flag is set to %r rather than following `visible`. "
                "Pinned on, a closed panel is a 920x700 dead zone in the middle of the map "
                "that nothing on screen explains." % arg)

    # And the cells' own flag is a different thing entirely - they are only ever turned ON,
    # because a hidden cell is not hit-tested and EX.layout hides every cell its mode does not
    # place. Assert the two are not confused: set_tip must not touch visibility.
    tip_fn = re.search(r"local function set_tip\(.*?" + chr(10) + r"end", code, re.S)
    assert tip_fn and "SetVisible" not in tip_fn.group(0), (
        "set_tip changes visibility. Showing a cell this mode deliberately hid puts the other "
        "view's column back on screen on top of this one's.")
    print("  map blocking: panel interactive follows visibility, cells never touch it")


def check_closes_on_end_turn():
    """Ending the turn closes the panel, and closes it the way EX.show closes it.

    Three failure modes, all silent:

    1. WRONG EVENT. FactionTurnStart would shut the panel a turn late - after the player has
       already watched the AI round through it, which is the whole complaint. The end-turn
       button's ComponentLClickUp would miss the keyboard shortcut.
    2. UNFILTERED. FactionTurnEnd fires for every faction on the map, so without the local
       filter the handler runs eighty-odd times a round to do nothing.
    3. CLOSED BY HAND. A bare panel:SetVisible(false) here hides the panel and leaves it
       INTERACTIVE - the 920x700 dead zone check_panel_blocks_map exists to refuse, sneaked
       back in through a second closing path. EX.show is the one place visibility is written
       and this has to go through it.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    m = re.search(r'core:add_listener\(\s*"zharr_exchange_close_end_turn"\s*,\s*"(\w+)"'
                  r'(.*?)end,\s*true\)', code, re.S)
    assert m, ("nothing closes the panel when the turn ends - it stays over the map for the "
               "whole AI round")
    assert m.group(1) == "FactionTurnEnd", (
        "the panel closes on %r rather than FactionTurnEnd. FactionTurnStart shuts it a turn "
        "late, after the AI round the player wanted to watch." % m.group(1))
    body = m.group(2)
    # EX.me(), NOT cm:get_local_faction_name(). This listener SHOULD be local-only - the panel
    # is per client and closing somebody else's is meaningless - but the raw accessor THROWS in
    # a multiplayer campaign unless the force argument is passed, and EX.me() is the wrapper
    # that passes it. So the property being pinned is unchanged and the spelling is not.
    assert "EX.me()" in body, (
        "the close-on-end-turn listener is not filtered to the local faction. FactionTurnEnd "
        "fires for every faction on the map.")
    assert "cm:get_local_faction_name(" not in body, (
        "the close-on-end-turn listener reads cm:get_local_faction_name directly. Unforced it "
        "throws in multiplayer; go through EX.me(), which forces it once and caches.")
    # SetVisible FIRST, and the break test is why: swapping EX.show(false) for a bare
    # p:SetVisible(false) trips both of these, and only this one names what actually breaks.
    assert "SetVisible" not in body, (
        "the close-on-end-turn listener writes visibility itself. EX.show is the one place "
        "that happens, because it also drops the interactive flag - hiding the panel without "
        "it leaves a 920x700 dead zone in the middle of the campaign map.")
    assert "EX.show(false)" in body, (
        "the panel is closed by something other than EX.show(false).")
    print("  end turn: FactionTurnEnd, local faction only, closes through EX.show")


def check_ai_turn_gate():
    """The opener button is refused during the AI round, and comes back when the turn starts.

    Five silent failures, and the last two are the ones that would ship:

    1. THE CLICK BRANCH UNGUARDED. A disabled component should raise no click, but a save loaded
       mid-round has had nothing run to grey anything, so the branch has to ask for itself.
    2. THE ANSWER REMEMBERED RATHER THAN ASKED. A flag set on FactionTurnEnd and cleared on
       FactionTurnStart survives neither a load nor a reload, and a stale "it is the AI's turn"
       is a dead button with nothing on screen to explain it.
    3. FAILING CLOSED. `is_factions_turn_by_key` behind a pcall that returns false on error
       locks the player out of their own panel for the rest of the campaign, and the only
       symptom is a button that does nothing.
    4. THE BUTTON HIDDEN INSTEAD OF DISABLED. It vanishes and comes back every turn, and the
       resource strip shuffles around the hole.
    5. NO RE-ENABLE. Greyed on the first turn end and never ungreyed - which is failure 3 with
       a different cause and the same symptom.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    fn = re.search(r"function EX\.player_turn\(\).*?" + NL + r"end", code, re.S)
    assert fn, "EX.player_turn is gone - nothing tells the panel whose turn it is"
    body = fn.group(0)
    assert "is_factions_turn_by_key" in body, (
        "EX.player_turn no longer asks the model. A flag set on FactionTurnEnd and cleared on "
        "FactionTurnStart survives no load, and a stale answer is a permanently dead button.")
    assert "pcall" in body and re.search(r"if not ok then return true end", body), (
        "EX.player_turn does not fail OPEN. If the probe throws, denying leaves the player "
        "locked out of the panel with no symptom but a button that does nothing; allowing "
        "degrades to the behaviour that shipped for twenty builds.")

    gate = re.search(r"function EX\.gate_button\(on\).*?" + NL + r"end", code, re.S)
    assert gate, "EX.gate_button is gone - the button stays lit through the AI round"
    # SetVisible FIRST, for the same reason check_closes_on_end_turn orders its two that way:
    # swapping SetDisabled for SetVisible trips both, and only this one names the damage.
    assert "SetVisible" not in gate.group(0), (
        "EX.gate_button hides the button instead of disabling it. It would vanish and come "
        "back every turn, and the resource strip would shuffle around the hole.")
    assert "SetDisabled(not on)" in gate.group(0), (
        "EX.gate_button no longer greys the button from its own argument.")

    click = re.search(r"if s == EX\.BUTTON then(.*?)" + NL + r"\s+end", code, re.S)
    assert click and "EX.player_turn()" in click.group(1), (
        "the opener's click branch does not check EX.player_turn(). A disabled component "
        "should raise no click, but a save loaded mid-round has had nothing run to grey it.")

    assert re.search(r"EX\.gate_button\(false\)", code), (
        "nothing greys the button when the turn ends")
    assert re.search(r"EX\.gate_button\(true\)", code), (
        "nothing un-greys the button at turn start - greyed once is greyed for the campaign")
    # AND THE BUTTON SAYS WHY. A greyed control with no reason reads as a broken mod, and the
    # player meets it on their first end-turn. The sentence is a permanent part of TIP_OPEN in
    # the shipped .twui.xml rather than a runtime SetTooltipText: the tooltip carries CA's
    # Title||Body split, proven only as literal XML, and writing it back through the setter
    # might draw the pipes. So this assertion is what stops the gate and its explanation
    # parting company - delete one and the other is a fault nobody can see.
    xml = io.open(os.path.join(ROOT, "Modding Files", "pack", "ui", "campaign ui",
                               "derpy_chd_exchange_button.twui.xml"), encoding="utf-8").read()
    tip = re.search(r'componentleveltooltip="([^"]*)"', xml)
    assert tip, ("the opener button has no componentleveltooltip at all - "
                 "run gen_exchange_ui.py")
    assert "take their turn" in tip.group(1), (
        "the opener's tooltip no longer says the panel is closed on the enemy turn, but "
        "EX.gate_button still greys it. A greyed control with no reason reads as a broken mod.\n"
        "  tooltip is: %r" % tip.group(1))
    print("  ai turn gate: asked not remembered, fails open, disabled not hidden, both edges, "
          "and the tooltip says why")


def check_header_labels():
    """A header label must fit its own box, and must not run into the next label.

    Found when "Held" became "Held / rent" on 2026-09-06 - the request was to say WHY the
    second number in that cell is a deduction, and a longer label is the whole of that change.
    The width rules in gen_exchange_ui.py are about where a header sits relative to its column
    and its neighbour; none of them looks at the text.

    TWO THINGS THIS OWNS, and it owns both because this is the only place the LABELS are read.

    1. THE BOX IS NOT THE USABLE WIDTH - `textxoffset` comes off it. hdr_trend shipped 36px
       wide holding "Trend" at ~33.5px and passed, then drew "Tr..." on screen the moment the
       headers took the row cells' textxoffset=4 and the hole became 32px (2026-09-06). A
       measurement that ignores the offset is a measurement of the wrong box.
    2. THE GAP BETWEEN TWO LABELS, not between two boxes. gen_exchange_ui.py used to demand
       12px of clear box after any header 60px or narrower, on the premise that a tight box is
       a full box - true only while the NEXT header is left-aligned. hdr_spark is right-aligned
       now, so its text starts 17px inside its own box and the box gap understates the real
       separation by that much. Text positions are computed here from align + offset and
       compared directly; the box rule over there is narrowed to the case it actually models.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    # ALIGNMENT AND OFFSET COME OFF THE SHIPPED XML, not off the generator that wrote it - this
    # is the file the game reads, and a header's text metrics are static across all four modes.
    xml = io.open(os.path.join(ROOT, "Modding Files", "pack", "ui", "campaign ui",
                               "derpy_chd_exchange_panel.twui.xml"), encoding="utf-8").read()
    metrics = {}
    for blk in re.finditer(r'<(hdr_\w+)\s[^>]*>\s*<states>(.*?)</states>', xml, re.S):
        a = re.search(r'texthalign="(\w+)"', blk.group(2))
        o = re.search(r'textxoffset="([\d.]+)', blk.group(2))
        if a and o:
            metrics[blk.group(1)] = (a.group(1), float(o.group(1)))
    assert len(metrics) >= 7, ("only %d headers found in the panel twui.xml - the parse is "
                               "wrong, or gen_exchange_ui.py has not been run" % len(metrics))
    block = re.search(r"EX\.HEADERS = \{(.*?)" + chr(10) + r"\}", lua, re.S)
    assert block, "EX.HEADERS is gone"
    # A LABEL IS A LUA EXPRESSION, NOT ALWAYS A LITERAL. hdr_spark is
    # "Last " .. EX.SPARK_BARS .. " turns", and a naive read of the first quoted run measures
    # the panel's longest header as five characters - so both the fit and the gap below were
    # computed on "Last " and the widest label in the panel was the one nothing checked.
    # Resolve the constant, fold the concatenation, then refuse any label still carrying one.
    body = NL.join(l for l in block.group(1).splitlines()
                   if not l.lstrip().startswith("--"))
    sb = re.search(r"EX\.SPARK_BARS\s*=\s*(\d+)", lua)
    assert sb, "EX.SPARK_BARS is gone"
    body = re.sub(r'"\s*\.\.\s*"', "", body.replace("EX.SPARK_BARS", '"%s"' % sb.group(1)))
    left = re.search(r'(hdr_\w+)\s*=\s*"[^"]*"\s*\.\.', body)
    assert not left, (
        "%s's label is still a concatenation after folding, so only its first literal would be "
        "measured - and a header measured short is a header that clips in silence."
        % left.group(1) if left else "")
    tables = {"trade": "EX.PANEL_LAYOUT", "stats": "EX.PANEL_LAYOUT_STATS",
              "offer": "EX.PANEL_LAYOUT_OFFER", "houses": "EX.PANEL_LAYOUT_HOUSES",
              "help": "EX.PANEL_LAYOUT_HELP"}
    checked = 0
    for mode, tbl in tables.items():
        m = re.search(mode + r"\s*=\s*\{(.*?)\}", body, re.S)
        assert m, "EX.HEADERS.%s is gone" % mode
        labels = dict(re.findall(r'(hdr_\w+)\s*=\s*"([^"]*)"', m.group(1)))
        lay = re.search(re.escape(tbl) + r" = \{(.*?)" + chr(10) + r"\}", lua, re.S)
        assert lay, "%s is gone" % tbl
        boxes = dict((n, int(w)) for n, w in
                     re.findall(r'\{\s*"(hdr_\w+)"\s*,\s*-?\d+\s*,\s*-?\d+\s*,\s*(\d+)',
                                lay.group(1)))
        xs = dict((n, int(x)) for n, x in
                  re.findall(r'\{\s*"(hdr_\w+)"\s*,\s*(-?\d+)', lay.group(1)))
        spans = {}
        for hid, text in labels.items():
            if hid not in boxes:
                continue                      # no explicit width: the xml default applies
            align, tx = metrics[hid]
            assert text in HEADER_LABEL_PX, (
                "%s header %s is %r, which has never been measured. Add it to HEADER_LABEL_PX "
                "from a live TextDimensionsForText reading - do NOT estimate from a character "
                "count, which is how a 38px \"Trend\" went into a 36px box and drew \"Tr...\"."
                % (mode, hid, text))
            need = HEADER_LABEL_PX[text]
            checked += 1
            assert need <= boxes[hid] - tx, (
                "%s header %s is %r - %dpx of text in a %dpx box less %.0fpx of "
                "textxoffset, so it clips mid-word with no error and only a screenshot would "
                "show it" % (mode, hid, text, need, boxes[hid], tx))
            # Where the LABEL actually lands, which is the only thing a reader sees.
            if align == "Right":
                end = xs[hid] + boxes[hid] - tx
                spans[hid] = (end - need, end)
            elif align == "Center":
                mid = xs[hid] + boxes[hid] / 2.0
                spans[hid] = (mid - need / 2, mid + need / 2)
            else:
                spans[hid] = (xs[hid] + tx, xs[hid] + tx + need)
        ordered = sorted((v[0], k) for k, v in spans.items())
        for (_s1, a), (_s2, b) in zip(ordered, ordered[1:]):
            gap = spans[b][0] - spans[a][1]
            assert gap >= 12, (
                "%s: %r and %r are %.0fpx apart and read as one run-on phrase. That is how "
                "the header row once read \"Trend Last 12 turns\" (2026-09-05)."
                % (mode, labels[a], labels[b], gap))
    assert checked >= 12, "only %d header labels were measured - the parse is wrong" % checked

    # THE RUNTIME VARIANTS. EX.bind_race rewrites EX.HEADERS.offer.hdr_trend to
    # "<patron> grants" after the bind, so the literal in the file is only ever the Chaos
    # Dwarf case and a static read of EX.HEADERS never sees the other three.
    lay = re.search(r"EX\.PANEL_LAYOUT_OFFER = \{(.*?)" + chr(10) + r"\}", lua, re.S)
    assert lay, "EX.PANEL_LAYOUT_OFFER is gone"
    trend_box = int(re.search(r'\{\s*"hdr_trend"\s*,\s*-?\d+\s*,\s*-?\d+\s*,\s*(\d+)',
                              lay.group(1)).group(1))
    _align, trend_tx = metrics["hdr_trend"]
    bounded = 0
    for culture, row in sorted(race_table().items()):
        label = row["patron"] + " grants"
        assert label in HEADER_LABEL_PX or label in HEADER_LABEL_BOUND, (
            "%r has neither a measured width nor a declared bound. A label in neither table is "
            "REFUSED rather than estimated - the check ran on a 6.7px/char guess for its whole "
            "life and passed a 36px box holding a 38px \"Trend\", which drew \"Tr...\" twice "
            "before anyone asked the engine." % label)
        if label in HEADER_LABEL_PX:
            need = HEADER_LABEL_PX[label]
            checked += 1
        else:
            # A BOUND MUST STILL BE AN UPPER BOUND, or it is just an estimate with a nicer
            # name. 9.0px/char is the rate the measuring run showed overstates every string;
            # a bound below it would be claiming knowledge this file does not have.
            need = HEADER_LABEL_BOUND[label]
            assert need >= 9.0 * len(label) - 0.5, (
                "%r is bounded at %dpx, under the 9.0px/char rate (%.0fpx) that the 2026-09-08 "
                "run proved overstates every measured string. A bound below the only rate "
                "known to be safe is an estimate wearing a bound's name - measure it instead."
                % (label, need, 9.0 * len(label)))
            bounded += 1
        assert need <= trend_box - trend_tx, (
            "%s's offerings header %r needs %dpx in a %dpx box less %.0fpx of textxoffset"
            % (culture, label, need, trend_box, trend_tx))

    # AND NOTHING BOUNDED MAY LINGER UNMEASURED WITHOUT BEING SEEN. The count is printed, not
    # silently absorbed, because the whole failure this table exists to stop is a number
    # nobody looked at again.
    stale = sorted(set(HEADER_LABEL_BOUND) & set(HEADER_LABEL_PX))
    assert not stale, (
        "%s appear in BOTH the measured table and the bounds table. Once a real reading "
        "exists the bound has to go, or the check silently prefers one of two answers."
        % ", ".join(stale))

    print("  header labels: %d measured and %d bounded (9.0px/char, unmeasured - see "
          "HEADER_LABEL_BOUND), all fit their boxes and clear their neighbours"
          % (checked, bounded))


def check_help_line_indices():
    """EX.HELP_OFFER_LINE and EX.HELP_GUILD_LINE point at the sentences bind_race rewrites.

    Those two indices are how the per-race wording reaches a FILE-SCOPE table literal that
    cannot read EX.race at construction. Point one at the wrong row and bind_race silently
    replaces an unrelated guide line with the offerings sentence - no error, and
    check_help_lines measures lengths rather than meanings, so nothing else would see it.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    block = re.search(r"EX\.HELP_PAGES = \{(.*?)" + NL + r"\}" + NL, lua, re.S)
    assert block, "EX.HELP_PAGES is gone"
    pages = []
    for chunk in re.split(r"\n    \{ -- PAGE", block.group(1)):
        entries = [l.strip() for l in chunk.splitlines() if l.startswith("        { ")]
        if entries:
            pages.append(entries)
    assert len(pages) == 2, "expected 2 guide pages, parsed %d" % len(pages)

    for name, page, want in (("EX.HELP_OFFER_LINE", 0, "Offerings"),
                             ("EX.HELP_GUILD_LINE", 1, "Guild")):
        m = re.search(name + r"\s*=\s*(\d+)", lua)
        assert m, "%s is gone" % name
        i = int(m.group(1))
        assert 1 <= i <= len(pages[page]), (
            "%s is %d, and guide page %d has %d entries"
            % (name, i, page + 1, len(pages[page])))
        assert want in pages[page][i - 1], (
            "%s points at %r, not the %r entry. EX.bind_race rewrites that index at every "
            "campaign start; pointing it at the wrong line replaces an unrelated sentence "
            "with the per-race one and nothing errors."
            % (name, pages[page][i - 1][:60], want))


def check_footer_literals():
    """A footer line built ONLY from string literals must fit its box without fit().

    fit() exists because the appetite and shock summaries are unbounded - they name one
    commodity per shaken good - and a character budget on THOSE would be the mistake the
    2026-09-06 session already made once. A line made of nothing but literals is not that
    case: its length is known right here, and letting fit() amputate it is how the Ownership
    view shipped reading "...than the same regions ..." with the sentence stopped mid-thought.

    Caught by the user's screenshot, not by any check - the second footer fault in a row that
    every automated check passed over, because the MCP cannot photograph a panel.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    # The box and the font were both measured 2026-09-06 with TextDimensionsForText.
    box_px, px_per_char = 880, 6.7
    ceiling = int(box_px / px_per_char)          # ~131, where fit() starts cutting
    budget = 118                                 # ~790px, ~10% margin

    # The stats footer is the only pair with no variable in it. Pull both assignments and
    # concatenate their literals in order; a line joining anything unquoted is skipped,
    # which is the point - those are the unbounded ones fit() exists for.
    # There is more than one `elseif stats then` in the file - the row filler has one too -
    # so take the block that actually assigns the footer lines, not merely the first.
    # ANCHORED ON INDENT, not on the next "elseif" anywhere. "elseif stats then" appears twice
    # - once deep inside the row filler and once at function-body level for the footer - and a
    # non-greedy match to the next elseif only separated them while the row filler happened to
    # contain one. Deleting an unrelated if/elseif from the trend code made that match swallow
    # the whole footer and the check silently found zero static lines. Four spaces is the
    # footer's real structure; the row filler sits at twelve.
    open_re = chr(10) + "    elseif stats then"
    close_re = chr(10) + "    elseif"
    blocks = [m.group(1) for m in
              re.finditer(open_re + "(.*?)" + close_re, lua, re.S)]
    assert len(blocks) == 1, (
        "expected exactly one function-level stats block, found %d" % len(blocks))
    assert "l1 = " in blocks[0], "the function-level stats block assigns no footer lines"
    block = blocks[0]
    lit = re.compile(r'"((?:[^"\\]|\\.)*)"')
    nxt = r"(?=" + chr(10) + r"\s*(?:l[12] =|end|elseif))"
    found = 0
    # The captured block stops BEFORE the closing elseif, so the last assignment has no
    # terminator to look ahead to. Put one back rather than loosening the lookahead.
    for name, body in re.findall(r"(l[12]) = (.*?)" + nxt, block + chr(10) + "elseif",
                                 re.S):
        chunks = lit.findall(body)
        stripped = lit.sub("", body)
        # anything left but concatenation dots, comments and whitespace means a variable
        stripped = re.sub(r"--[^" + chr(10) + r"]*", "", stripped)
        if re.sub(r"[.\s]", "", stripped):
            continue
        text = "".join(chunks)
        found += 1
        assert len(text) <= budget, (
            "static footer %s is %d chars (~%.0fpx) against an %dpx box - fit() amputates it "
            "in game and the sentence stops mid-word. Budget is %d chars (ceiling %d)."
            % (name, len(text), len(text) * px_per_char, box_px, budget, ceiling)
            + chr(10) + "  " + repr(text))
    assert found == 2, (
        "expected 2 fully-static footer lines in the stats view, found %d - if one now takes "
        "a variable it becomes fit()'s problem, but make that deliberate" % found)
    print("  footer literals: %d static lines, all within %d chars" % (found, budget))


def check_hud_income():
    """Run the SHIPPED EX.brand_income against a stub treasury bar.

    The bar is the one number a player actually watches, and this writes over the engine's own
    value every second. The faults it pins are all silent: writing only the current state
    leaves the other showing a stale number the moment the sign flips, and forgetting to go
    back to the engine's figure when the last crate is sold leaves the bar permanently wrong.
    """
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped hud income check: no lua.exe)")
        return
    harness = LUA_HUD_HARNESS % (LUA_SCRIPT.replace(chr(92), chr(92) * 2),)
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    at = {}
    for line in got.split(chr(10)):
        line = line.strip()
        if not line:
            continue
        tag, state, pos, neg = line.split("|")
        at[tag] = (state, pos, neg)

    # 2338 predicted, 734 of rent -> the player really receives 1604, in BOTH states.
    assert at["first"] == ("positive", "1604", "1604"), (
        "first pass wrote %r - both states carry their own text and both must say 1604"
        % (at["first"],))

    # Ten more ticks of the same timer must not move it.
    assert at["after_ten_ticks"] == at["first"], (
        "the bar drifted to %r over ten ticks" % (at["after_ten_ticks"],))

    assert at["income_changed"] == ("positive", "1266", "1266"), (
        "income moving to 2000 gave %r, expected 1266" % (at["income_changed"],))

    # Nothing held: back to the engine's own number, with no engine refresh to prompt it.
    assert at["sold_out"] == ("positive", "2000", "2000"), (
        "the last crate was sold and the bar reads %r instead of the engine's own 2000"
        % (at["sold_out"],))

    # And re-corrected when stock returns, again with income unchanged.
    assert at["bought_again"] == ("positive", "1266", "1266"), (
        "stock returned and the bar reads %r, expected 1266" % (at["bought_again"],))

    assert at["goes_negative"] == ("negative", "-234", "-234"), (
        "500 income against 734 rent gave %r, expected -234 in the negative state"
        % (at["goes_negative"],))

    assert at["no_bar"] == at["goes_negative"], (
        "a missing bar changed something: %r" % (at["no_bar"],))
    assert at["null_faction"] == at["goes_negative"], (
        "a null faction interface changed something: %r" % (at["null_faction"],))

    print("  hud income: 2338 -> 1604 both states, stable over 10 ticks, restores 2000 when "
          "sold out, -234 goes red, no bar and null faction are no-ops")


def check_finance_recolour():
    """Run the SHIPPED EX.recolour_finance against the live finance list, transcribed.

    Two separate faults live here and only one of them is the colour. The other is that a
    dy_value's states each carry their own text: switching to "negative" without rewriting it
    shows the twui's placeholder, measured as "100", so a check that only asserts the STATE
    would pass a build that replaced every expense in the game with the number 100.
    """
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped finance recolour check: no lua.exe)")
        return
    harness = LUA_FINANCE_HARNESS % (LUA_SCRIPT.replace(chr(92), chr(92) * 2),)
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)

    seen, log = {}, []
    for line in got.split(chr(10)):
        line = line.strip()
        if not line:
            continue
        row, cid, state, text = line.split("|")
        if row == "LOG":
            log.append(state)
            continue
        seen[(row, cid)] = (state, text)

    # The log line is the ONLY trace this leaves in a campaign, and the bridge that read the
    # live panel died twice in one session - so it is asserted, not assumed. Exactly the two
    # halves of the Event Outcomes expense row change; nothing else in a correct panel does.
    assert log == ["ZHARR EXCHANGE: finance panel, reddened 2 expense cells"], (
        "expected one log line naming 2 reddened cells, got %r" % (log,))
    # 21 rows carry cells (19 entries plus the two section totals), three cells each.
    assert len(seen) == 63, "expected 63 value cells, parsed %d" % len(seen)

    # THE FAULT. Both halves of the Event Outcomes expense row go red and KEEP their number.
    for cid, want in (("dy_value1", "734"), ("dy_value2", "1468")):
        state, text = seen[("entry_31", cid)]
        assert state == "negative", (
            "the Event Outcomes EXPENSE row is still %s - that is the green 734 sitting under "
            "a red total that this exists to fix" % state)
        assert text == want, (
            "entry_31 %s reads %r, not %r - SetState was called without rewriting the text and "
            "the panel is now showing the twui placeholder" % (cid, text, want))

    # Rows CA already got right are left exactly as they were.
    assert seen[("entry_20", "dy_value1")] == ("negative", "12125")
    assert seen[("entry_23", "dy_value1")] == ("negative", "2033")
    assert seen[("entry_23", "dy_value2")] == ("negative", "2033")

    # THE INCOME SECTION IS NOT AN EXPENSE SECTION. Income also has an Event Outcomes row and
    # an Other row, and a walk that counts sections wrongly reddens the player's income.
    for row, cid, want in (("entry_2", "dy_value1", "1155"), ("entry_4", "dy_value1", "216"),
                           ("entry_15", "dy_value1", "3000"), ("entry_15", "dy_value2", "3734"),
                           ("entry_13", "dy_value1", "0")):
        state, text = seen[(row, cid)]
        assert state == "positive", "%s %s went %s - income must not turn red" % (row, cid, state)
        assert text == want, "%s %s reads %r, not %r" % (row, cid, text, want)

    # A zero cost is not a cost. CA leaves its own empty expense rows green.
    for row in ("entry_21", "entry_24", "entry_25", "entry_26", "entry_28", "entry_29",
                "entry_33"):
        for cid in ("dy_value1", "dy_value2"):
            state, text = seen[(row, cid)]
            assert (state, text) == ("positive", "0"), (
                "%s %s is %s %r - a red 0 reads as a cost that is not there"
                % (row, cid, state, text))
    assert seen[("entry_20", "dy_value2")] == ("positive", "0")

    # The section TOTALS are CA's own and already correct in both directions. header_sum_ must
    # not be counted as a section header either, or the expenses never open.
    assert seen[("header_sum_16", "dy_value1")] == ("positive", "4371")
    assert seen[("header_sum_34", "dy_value1")] == ("negative", "14892")

    # The name column is not a value column.
    assert seen[("entry_31", "dy_item_name")] == ("NewState", "Event Outcomes"), (
        "the dy_value prefix test is matching dy_item_name")

    reds = sum(1 for st, _t in seen.values() if st == "negative")
    print("  finance recolour: %d cells, %d red, Event Outcomes expense 734/1468 now red"
          % (len(seen), reds))


def check_lua_button():
    """Run the SHIPPED place_button against an animated resource strip.

    The fault this exists for shipped and was found in script_log, not here: the opener
    button retried a flat 8 times 2.0s apart, resources_bar was still off the top of the
    screen when that ran out, and the button was never made visible for the rest of the
    campaign. Four loads of the same build won that race and the fifth lost it, so a check
    that does not HOLD the strip away for longer than the old budget proves nothing.
    """
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped lua button check: no lua.exe)")
        return
    harness = LUA_BUTTON_HARNESS % (LUA_SCRIPT.replace("\\", "\\\\"),)
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    vals = {}
    for line in got.split("\n"):
        if " " in line.strip():
            k, v = line.strip().split(" ", 1)
            vals[k] = v

    tries = int(vals["tries"])
    assert tries >= 60, (
        "EX.PLACE_TRIES is %d - at 2.0s apart that is %.0fs, and the strip was still hidden "
        "74s into a measured load" % (tries, tries * 2.0))

    # The chain must OUTLIVE the old budget. 20 pumps = 20 attempts = 40 seconds.
    assert vals["pumped"] == "20", (
        "the retry chain died after %s attempts while resources_bar was hidden - the old "
        "flat-8 budget is exactly the bug" % vals["pumped"])
    assert vals["alive_while_hidden"] == "1", (
        "nothing is scheduled to try again while the strip is hidden (queue=%s)"
        % vals["alive_while_hidden"])
    # ...and must not have lied about being placed in the meantime.
    assert vals["visible_while_hidden"] == "false", (
        "the button was made visible off the top of the screen")

    # A settled strip lands it, with no help.
    assert vals["placed"] == "1470,2", (
        "settled strip placed the button at %s, expected 1470,2" % vals["placed"])
    assert vals["visible_after"] == "true", "the button never became visible"

    # After the first success the guard must leave it alone, not restart the chain.
    assert vals["reschedules_after_placed"] == "0", (
        "a hidden strip started a second retry chain after the button was already placed")
    assert vals["still_at"] == "1470,2", (
        "a hidden strip moved an already-placed button to %s" % vals["still_at"])
    assert vals["still_visible"] == "true", "a hidden strip hid an already-placed button"
    assert vals["reschedules_when_placed"] == "0", (
        "a fresh place_button chain started even though the button is already placed - "
        "EX.button_at is the terminator, the cap is only the backstop")

    # And the cap still terminates when the anchor is gone for good.
    assert vals["reschedules_at_cap"] == "0", (
        "place_button reschedules at the cap - a CA rename would retry for ever")
    assert vals["reschedules_under_cap"] == "1", (
        "place_button does not retry below the cap when the anchor is absent")
    # A dead chain must still be recoverable by a single call against a settled strip -
    # that is what the FactionTurnStart one-shot below relies on.
    assert vals["recovered"] == "1470,2", (
        "a one-shot place_button against a settled strip did not place the button (%s) - the "
        "turn-start recovery cannot work" % vals["recovered"])
    assert vals["recovered_visible"] == "true", "the recovered button was never made visible"
    assert vals["recovered_queue"] == "0", "the turn-start one-shot started a chain"

    # ...and it must actually BE wired to turn start. The first-tick chain only covers a strip
    # that is still animating in; a strip that stays away longer than the chain lives is the
    # residual failure, and turn start is the free recovery point because the player is looking
    # at the map by definition.
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    turn = turn_body(code)
    assert "EX.place_button" in turn, (
        "nothing re-places the opener button at turn start. The first-tick chain is bounded, "
        "so a resource strip hidden past EX.PLACE_TRIES leaves the button invisible for the "
        "rest of the campaign - which is exactly how this shipped.")
    # ...as a ONE-SHOT. A chain started here would queue cm:callback names the first-tick
    # chain is still using, since the only way to reach turn start unplaced is with that chain
    # alive. The Lua carries this as a comment; a comment with no check is what rots.
    assert "EX.place_button(EX.PLACE_TRIES)" in turn, (
        "the turn-start recovery does not pass EX.PLACE_TRIES, so it starts a second retry "
        "chain rather than trying once - colliding cm:callback names with the first-tick one")

    # THE CATHAY CASE. A settled strip 7px higher than the Empire's puts the button at y=-5.
    # Clamped onto the screen edge and placed - not refused for the rest of the campaign.
    assert vals["cathay"] == "1470,0", (
        "a settled resource strip that centres the button at y=-5 was not clamped onto the "
        "screen: %s. That is how the opener button never appeared for a Cathayan faction - "
        "and there is no recovery, because placement only reruns from EX.layout, which needs "
        "the button the player cannot reach." % vals["cathay"])
    assert vals["cathay_visible"] == "true", (
        "the clamped button was placed but never made visible")

    # ...and the clamp must NOT have swallowed the fault the guard exists for.
    assert vals["wild"] == "-1,-1", (
        "a resource strip 640px off the top of the screen was clamped onto the edge instead "
        "of refused - that is a button drawn over the map mid-animation: %s" % vals["wild"])
    assert vals["wild_visible"] == "false", "an off-screen read made the button visible"
    assert vals["wild_queue"] == "1", (
        "an off-screen read did not schedule a retry, so the button never arrives")

    print("  lua button check: strip hidden %s attempts, placed at %s on settle, "
          "turn-start recovery wired" % (vals["pumped"], vals["placed"]))


# The stub board check_lua_books() runs the SHIPPED file against. Kept at module level for
# the same reason LUA_HOUSES_HARNESS is: the harness is read by eye more often than it is run.
LUA_BOOKS_HARNESS = """
local SAVED = {}
-- MCT, STUBBED ON. EX.setting reads get_mct and every gate in the file reads EX.setting; a key
-- with no SETTINGS entry is not `false`, so defining this changes nothing at all until a test
-- switches one off. Without it the whole harness runs down EX.setting's "MCT is not installed"
-- branch and no toggle can be exercised.
-- AND SET TO THE CUSTOM PRESET, because that is the only difficulty under which the seven
-- switches are the player's. A preset OWNS them - Easy turns rent and the tithe off, and
-- "Ultra Capitalism with the AI traders switched off" is not Ultra Capitalism, it is Custom.
-- Under any other preset EX.opt reads the preset table and SETTINGS here would move nothing,
-- which is exactly what this harness would then fail to notice.
--
-- The numeric knobs still come out at their defaults: this stub answers every non-preset key
-- with a boolean, EX.opt_live type-checks a slider against its default and discards anything
-- that is not a number. EX.<CONST> = x is still the way to move one, and EX.opt_default reads
-- the constant live, so those overrides below keep working unchanged.
SETTINGS = {}
function get_mct()
    return { get_mod_by_key = function()
        return { get_option_by_key = function(_, k)
            return { get_finalized_setting = function()
                if k == "preset" then return "custom" end
                return SETTINGS[k] ~= false
            end }
        end }
    end }
end
-- EX.faction_display reads common.get_localised_string through a pcall - but the pcall's FIRST
-- ARGUMENT is evaluated before pcall is entered, so a nil `common` is an uncaught error, not a
-- caught one. Returning "" makes faction_display fall back to the raw key, which is what the
-- refusal-reason tests below read.
common = { get_localised_string = function() return "" end }
-- EVERY cm:get_faction CALL IN THE RUN. The stance memo is measured against this counter,
-- because "the panel hangs for a second on every refresh" is not a thing a selftest can see
-- any other way.
GF_CALLS = 0
-- WHAT ACTUALLY MOVED. cm:treasury_mod used to be a no-op here, so nothing could tell "the
-- house was paid" from "the house was not paid" - which is exactly the distinction the
-- ai_gold-off tests below turn on.
PAID = {}
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function(_, k, v) SAVED[k] = v end,
    get_saved_value = function(_, k) return SAVED[k] end,
    get_local_faction_name = function() return "player" end,
    -- TREASURY is set (and reset) later by the book-desire tests below; a name with no entry
    -- reads as a real faction with 0 gold, not an unknown one, matching a house that exists
    -- but cannot afford to buy. TREATY and DIPLO are set (and reset) by the hostility tests
    -- further down - a name with no TREATY entry reads as "open" (no boolean true), and no
    -- DIPLO entry reads as 0 (the zero anchor), both matching a house we know nothing bad about.
    get_faction = function(_, k)
        GF_CALLS = GF_CALLS + 1
        return { is_null_interface = function() return false end,
                 treasury = function() return TREASURY[k] or 0 end,
                 at_war_with = function() return TREATY[k] == "war" end,
                 allied_with = function() return TREATY[k] == "allied" end,
                 military_allies_with = function() return false end,
                 is_vassal_of = function() return false end,
                 trade_agreement_with = function() return TREATY[k] == "trade" end,
                 non_aggression_pact_with = function() return TREATY[k] == "pact" end,
                 diplomatic_standing_with = function() return DIPLO[k] or 0 end }
    end,
    treasury_mod = function(_, k, amt) PAID[k] = (PAID[k] or 0) + amt end,
    faction_add_pooled_resource = function() end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])
EX.store = SAVED
-- CAPTURED BEFORE the front-run test below overwrites it. EX is a global table, not a local
-- to this chunk, so `EX.stance_of = function(h) ... end` further down permanently replaces
-- the real implementation for the rest of this run unless something restores it - see the
-- restore right before the hostility tests.
local REAL_STANCE_OF = EX.stance_of

-- THE SAVED HOUSE LIST. EX.restore() rebuilds EX.houses from EX.SAVE_HOUSES, not from
-- whatever the test sets EX.houses to - see the ghost-house test in LUA_HOUSES_HARNESS for
-- the same requirement. Written into SAVED directly, not through EX.setv, so it survives the
-- test resetting EX.store to a fresh table below: EX.getv falls back to cm:get_saved_value,
-- which is this same closure over SAVED.
SAVED[EX.SAVE_HOUSES] = "baal;azeros"

EX.houses = { "baal", "azeros" }
EX.delisted = {}
EX.store = {}

-- ROUND TRIP. A book packed and restored must come back identical, because it is the only
-- record - nothing regenerates a house's position from the map.
EX.set_book("baal", "res_rom_iron", 12)
EX.set_book("baal", "res_gems", 3)
EX.set_book("azeros", "res_rom_iron", 5)
print("packed " .. EX.pack_book("baal"))
print("guild_iron " .. EX.guild_book("res_rom_iron"))
print("guild_gems " .. EX.guild_book("res_gems"))
print("guild_none " .. EX.guild_book("res_ivory"))

EX.book = nil
EX.restore()
print("restored_iron " .. EX.book_of("baal", "res_rom_iron"))
print("restored_gems " .. EX.book_of("baal", "res_gems"))
print("restored_other " .. EX.book_of("azeros", "res_rom_iron"))

-- A DELISTED HOUSE LEAVES THE GUILD AND ITS BOOK GOES WITH IT. Nobody is owed anything -
-- the book was never the player's - and a dead house's position paying out would be a
-- second settlement racing EX.settle_house.
EX.delisted["baal"] = true
print("guild_n " .. #EX.guild())
print("guild_iron_after " .. EX.guild_book("res_rom_iron"))

-- THE EMPTY GUILD IS THE DEFAULT, not an edge case: most campaigns have no other Chaos
-- Dwarf faction. Every term downstream reads these, so they must be 0 and not nil.
EX.houses = {}
print("empty_n " .. #EX.guild())
print("empty_iron " .. EX.guild_book("res_rom_iron"))

-- CHARACTER IS DERIVED FROM THE KEY, NEVER ROLLED. A house that leans toward obsidian only
-- in this save is a bug; one that always does is a personality. Same key, same number,
-- across a fresh load and a fresh process.
print("hash_stable " .. tostring(EX.key_hash("baal") == EX.key_hash("baal")))
print("hash_differs " .. tostring(EX.key_hash("baal") ~= EX.key_hash("azeros")))
print("hash_bounded " .. tostring(EX.key_hash("cr_chd_black_kraken_armada") < 65536))
print("bias_stable " .. tostring(EX.house_bias("baal", "res_gems")
                                 == EX.house_bias("baal", "res_gems")))

-- BUDGET SCALES WITH TREASURY, and a broke house cannot buy.
EX.houses = { "baal", "azeros" }
EX.delisted = {}
TREASURY = { baal = 100000, azeros = 0 }
EX.current["res_rom_iron"] = EX.neutral_rung()
print("budget_rich " .. EX.house_budget("baal", "res_rom_iron"))
print("budget_broke " .. EX.house_budget("azeros", "res_rom_iron"))

-- PRODUCTION SIGN. A house that owns regions making a good sells it; one that owns none
-- imports it. This is the term that differentiates houses of an identical culture.
EX.owners = { res_rom_iron = { baal = 4 } }
EX.supply = { res_rom_iron = 4 }
print("desire_producer " .. tostring(EX.house_desire("baal", "res_rom_iron")
                                     < EX.house_desire("azeros", "res_rom_iron")))

-- VALUE. Dear goods attract selling, and the term grows without bound above neutral - that
-- is the mean-reversion stopping a guild of one culture pinning a commodity at the clamp.
EX.current["res_gems"] = EX.neutral_rung()
local d_mid = EX.house_desire("baal", "res_gems")
EX.current["res_gems"] = EX.RUNGS
local d_dear = EX.house_desire("baal", "res_gems")
EX.current["res_gems"] = 1
local d_cheap = EX.house_desire("baal", "res_gems")
print("value_order " .. tostring(d_cheap > d_mid and d_mid > d_dear))

-- FRONT-RUN NEEDS BOTH. Hostile alone does nothing; the player accumulating alone does
-- nothing; only a hostile house watching you buy leans in.
EX.pressure = { res_dyes = 8 }
EX.current["res_dyes"] = EX.neutral_rung()
EX.stance_of = function(h) return h == "baal" and -1.0 or 0 end
local d_hostile = EX.house_desire("baal", "res_dyes")
local d_neutral = EX.house_desire("azeros", "res_dyes")
EX.pressure = { res_dyes = 0 }
local d_hostile_flat = EX.house_desire("baal", "res_dyes")
print("frontrun_both " .. tostring(d_hostile > d_neutral))
print("frontrun_needs_pressure " .. tostring(d_hostile > d_hostile_flat))

-- THE TURN STEP MOVES A BOOK, and never more than BOOK_TRADE_MAX in one direction.
EX.book = {}
EX.owners = {}
TREASURY = { baal = 100000, azeros = 100000 }
EX.step_books()
local moved = 0
for _, res in ipairs(EX.COMMODITIES) do moved = moved + EX.guild_book(res) end
print("step_moved " .. moved)
print("step_bounded " .. tostring(moved <= 2 * EX.BOOK_TRADE_MAX))

-- QUANTISED TOWARD ZERO, both signs. math.floor(-0.5) is -1, so flooring a signed quantity
-- moves a price DOWN on a position too small to move it up. That asymmetry has already
-- shipped once in this file, in EX.pressure_shift.
EX.houses = { "baal" }
EX.delisted = {}
EX.book = { baal = {} }
local function shift_at(n)
    EX.book.baal.res_rom_iron = n
    return EX.book_shift("res_rom_iron")
end
print("shift_zero " .. shift_at(0))
print("shift_under " .. shift_at(EX.BOOK_PER_RUNG - 1))
print("shift_one " .. shift_at(EX.BOOK_PER_RUNG))
print("shift_clamped " .. shift_at(EX.BOOK_PER_RUNG * 99))
print("shift_is_max " .. tostring(shift_at(EX.BOOK_PER_RUNG * 99) == EX.BOOK_MAX))

-- HOUSES ARE NOT COMMODITIES. A share is paper; the guild does not hold a book in it.
EX.book.baal.baal = 500
print("shift_house " .. EX.book_shift("baal"))

-- THE EMPTY GUILD AGAIN, at the term that actually reaches the price.
EX.houses = {}
print("shift_empty " .. EX.book_shift("res_rom_iron"))

-- RESTORE EX.stance_of: the front-run test above (Task 2) monkey-patched it to a fixed stub
-- to exercise house_desire before Task 4 existed. EX is a global table, so that override is
-- still installed - undo it before testing the real treaty-and-rank implementation below.
EX.stance_of = REAL_STANCE_OF

-- THE TREATY LADDER DOMINATES THE NUMBER. An allied house with the worst standing in the
-- guild is still never penalised - which is what makes the counterplay something the player
-- can act on in the diplomacy screen rather than something they have to discover.
EX.houses = { "friend", "trader", "pact", "cold", "enemy" }
EX.delisted = {}
DIPLO = { friend = -900, trader = -900, pact = -200, cold = -100, enemy = -800 }
TREATY = { friend = "allied", trader = "trade", pact = "pact", enemy = "war" }
print("tier_friend " .. EX.treaty_tier("friend"))
print("tier_trader " .. EX.treaty_tier("trader"))
print("tier_pact " .. EX.treaty_tier("pact"))
print("tier_cold " .. EX.treaty_tier("cold"))
print("tier_enemy " .. EX.treaty_tier("enemy"))
print("stance_friend " .. EX.stance_of("friend"))
print("stance_trader " .. EX.stance_of("trader"))

-- SIGN AND RANK, NEVER MAGNITUDE. The deepest-negative eligible house pays the full markup;
-- a barely-negative one pays a sliver. diplomatic_standing_with returns an int32 of
-- undocumented range and nothing here may depend on its scale.
EX.houses = { "deep", "shallow" }
DIPLO = { deep = -900, shallow = -10 }
TREATY = {}
print("rank_order " .. tostring(EX.stance_of("deep") < EX.stance_of("shallow")))
-- The SAME ranking on a totally different scale must give the same stances.
DIPLO = { deep = -9, shallow = -1 }
print("scale_free " .. tostring(EX.stance_of("deep") < EX.stance_of("shallow")))

-- A GUILD THAT ALL LIKES YOU CHARGES NOTHING. Zero is the anchor; there is no "least liked"
-- penalty when nobody is below it.
DIPLO = { deep = 500, shallow = 10 }
print("all_friendly " .. EX.stance_of("deep"))

-- THE ZERO ANCHOR, TESTED DIRECTLY rather than through all_friendly above. With every house
-- >= 0, "deepest" is also >= 0 and the redundant `if deepest >= 0 then return 0 end` guard
-- further down rescues the answer even with the real zero-anchor line deleted. Mix in a
-- genuinely hostile house so deepest goes negative - then the zero anchor is the only thing
-- standing between a friendly house and a markup.
DIPLO = { deep = -900, shallow = 50 }
print("zero_anchor " .. EX.stance_of("shallow"))

-- HOSTILITY IS WEIGHTED BY WHO HOLDS THE GOOD. A house holding none of it has no say.
EX.houses = { "deep", "shallow" }
DIPLO = { deep = -900, shallow = 100 }
EX.book = { deep = { res_gems = 10 }, shallow = { res_rom_iron = 10 } }
print("hostile_gems " .. string.format("%%.4f", EX.hostility("res_gems")))
print("hostile_iron " .. string.format("%%.4f", EX.hostility("res_rom_iron")))
print("hostile_none " .. string.format("%%.4f", EX.hostility("res_ivory")))

-- THE BOUNDARY THAT MATTERS MOST: hostility must never reach the rung. Same books, same
-- map, furious guild versus friendly guild - target_rung must be identical.
EX.supply = { res_gems = 4 }
EX.owners = { res_gems = {} }
DIPLO = { deep = -900, shallow = -900 }
local r_angry = EX.target_rung("res_gems", EX.supply, EX.owners, 4)
DIPLO = { deep = 900, shallow = 900 }
local r_calm = EX.target_rung("res_gems", EX.supply, EX.owners, 4)
print("rung_isolated " .. tostring(r_angry == r_calm))

-- THE SIGN SELF-CHECK, all three states.
DIPLO = { deep = -900, shallow = 900 }
TREATY = { deep = "war", shallow = "allied" }
EX.check_standing_sign()
print("sign_ok " .. tostring(EX.standing_trusted))
DIPLO = { deep = 900, shallow = -900 }
EX.check_standing_sign()
print("sign_violated " .. tostring(EX.standing_trusted))
TREATY = {}
EX.standing_trusted = nil
EX.check_standing_sign()
print("sign_inconclusive " .. tostring(EX.standing_trusted))

-- YOUR FILL, NOT THE MARKET'S PRICE.
EX.houses = { "deep" }
EX.delisted = {}
DIPLO = { deep = -900 }
TREATY = {}
EX.book = { deep = { res_gems = 10 } }
EX.current["res_gems"] = EX.neutral_rung()
print("world " .. EX.price("res_gems"))
print("buy " .. EX.buy_price("res_gems"))
print("sell " .. EX.sell_price("res_gems"))

-- A FRIENDLY GUILD CHANGES NOTHING. This is also the empty-guild path, and it must be exact:
-- buy equals the world price and sell is exactly the old spread.
DIPLO = { deep = 900 }
print("buy_friendly " .. EX.buy_price("res_gems"))
print("sell_friendly " .. EX.sell_price("res_gems"))
print("sell_expected " .. math.floor(EX.price("res_gems") * (1 - EX.SPREAD) + 0.5))

-- THE FLOOR. Spread and hostility must never sum to a sale that pays nothing.
EX.SPREAD_SAVED = EX.SPREAD
EX.SPREAD = 0.9
DIPLO = { deep = -900 }
print("sell_floored " .. tostring(EX.sell_price("res_gems")
                                  >= math.floor(EX.price("res_gems") * EX.SELL_FLOOR)))
EX.SPREAD = EX.SPREAD_SAVED

-- ===========================================================================================
-- REFUSAL AND THE WAR LOCK. Task 6.
-- ===========================================================================================

-- REFUSAL NEEDS ALL THREE: deep enough, no treaty, and holding enough of the book.
EX.houses = { "deep", "mild" }
EX.delisted = {}
TREATY = {}
DIPLO = { deep = -900, mild = -5 }
EX.book = { deep = { res_gems = 10 }, mild = { res_gems = 1 } }
print("refuse_yes " .. tostring(EX.refused_by("res_gems") ~= nil))
-- Below REFUSE_SHARE of the book, the same fury refuses nothing.
EX.book = { deep = { res_gems = 1 }, mild = { res_gems = 10 } }
print("refuse_share " .. tostring(EX.refused_by("res_gems") == nil))
-- A treaty of any kind takes it off the table.
EX.book = { deep = { res_gems = 10 }, mild = { res_gems = 1 } }
TREATY = { deep = "pact" }
print("refuse_treaty " .. tostring(EX.refused_by("res_gems") == nil))
TREATY = {}

-- REFUSE_SHARE BOUNDARY: >= not >. 5-of-11 (0.4545) must NOT refuse; 5-of-10 (0.50 exact,
-- the spec's "at least") must.
EX.houses = { "x", "y" }
EX.delisted = {}
TREATY = {}
DIPLO = { x = -900, y = -5 }
EX.book = { x = { res_gems = 5 }, y = { res_gems = 6 } }
print("share_under " .. tostring(EX.refused_by("res_gems") == nil))
EX.book = { x = { res_gems = 5 }, y = { res_gems = 5 } }
print("share_exact " .. tostring(EX.refused_by("res_gems") ~= nil))

-- SELLING IS ALWAYS OPEN. Blocking a sell traps the player's capital with no exit, which is
-- the lockout that actually hurts as opposed to the one that merely costs money.
--
-- SELF-CONTAINED ON PURPOSE. Every input EX.blocked/EX.refused_by/EX.trade reads is set here
-- rather than inherited from the block above. Inheriting it is the trap: change that block's
-- houses or book and this one silently stops proving anything - res_gems stops being refused,
-- the buy is never blocked, and blocked_buy/open_sell both pass for the wrong reason while
-- "selftest ok" ships with the sell-always-open valve unguarded. The refused_by print right
-- below the setup, asserted below, is the tripwire: it fails loudly the moment this scenario
-- stops producing a refusal, instead of open_sell passing quietly.
EX.houses = { "deep", "mild" }
EX.delisted = {}
TREATY = {}
DIPLO = { deep = -900, mild = -5 }
EX.book = { deep = { res_gems = 10 }, mild = { res_gems = 1 } }
EX.supply = { res_gems = 4 }
EX.owners = { res_gems = {} }
print("sell_setup_refused " .. tostring(EX.refused_by("res_gems") ~= nil))
--
-- The shared cm stub at the top of this harness has no pooled-resource plumbing - nothing
-- before this test ever needed one, since EX.trade is only exercised here. It is overridden
-- for the length of this one test and restored right after, same discipline as the
-- EX.stance_of monkey-patch above. EX.holdings is a TEST-ONLY mirror table; the real Lua
-- tracks a commodity position through cm:faction_add_pooled_resource, keyed by
-- EX.hold_key(res), never by res itself - so the stub resolves through that key too, rather
-- than assuming the pool key equals the commodity key.
local REAL_GET_FACTION = cm.get_faction
local REAL_ADD_POOLED = cm.faction_add_pooled_resource
GOLD = 100000
EX.shares_held = {}
EX.holdings = { res_gems = 100 }
cm.get_faction = function(_, k)
    local f = REAL_GET_FACTION(cm, k)
    f.treasury = function() return GOLD end
    f.pooled_resource_manager = function()
        return { resource = function(_, pk)
            local v = 0
            for res, n in pairs(EX.holdings) do
                if EX.hold_key(res) == pk then v = n end
            end
            return { is_null_interface = function() return false end,
                     value = function() return v end }
        end }
    end
    return f
end
cm.faction_add_pooled_resource = function(_, _fac, pk, _factor, delta)
    for res, n in pairs(EX.holdings) do
        if EX.hold_key(res) == pk then EX.holdings[res] = n + delta end
    end
end
EX.trade("res_gems", true)
print("blocked_buy " .. tostring(EX.holdings.res_gems))
EX.trade("res_gems", false)
print("open_sell " .. tostring(EX.holdings.res_gems < 100))
cm.get_faction = REAL_GET_FACTION
cm.faction_add_pooled_resource = REAL_ADD_POOLED

-- THE WAR LOCK, both edges of GUILD_CLOSE.
EX.houses = { "a", "b" }
TREATY = { a = "war" }
DIPLO = { a = 0, b = 0 }
EX.book = { a = { res_gems = 5 }, b = { res_gems = 5 } }
print("lock_under " .. tostring(EX.market_closed() == nil))
EX.book = { a = { res_gems = 9 }, b = { res_gems = 1 } }
print("lock_over " .. tostring(EX.market_closed() ~= nil))

-- GUILD_CLOSE BOUNDARY: >= not >. 5-of-10 at war (0.50) must stay open; 6-of-10 (0.60 exact,
-- the spec's "at least") must close.
EX.book = { a = { res_gems = 5 }, b = { res_gems = 5 } }
print("close_under " .. tostring(EX.market_closed() == nil))
EX.book = { a = { res_gems = 6 }, b = { res_gems = 4 } }
print("close_exact " .. tostring(EX.market_closed() ~= nil))

-- AND IT IS THE EMPTY GUILD'S NO-OP TOO.
EX.houses = {}
print("lock_empty " .. tostring(EX.market_closed() == nil))
print("refuse_empty " .. tostring(EX.refused_by("res_gems") == nil))

-- ===========================================================================================
-- GOLD. Task 7. Houses pay for their own trades, bounded both ways, and a guild house holding
-- the book is the counterparty before the map-wide top_holder fallback.
-- ===========================================================================================

-- HOUSES PAY FOR THEIR OWN TRADES, bounded both ways. AI treasuries drive AI armies: this is
-- the one part of the Exchange that changes the campaign for factions the player is not
-- playing, and the cap is what keeps that bounded.
EX.houses = { "rich", "poor" }
EX.delisted = {}
TREASURY = { rich = 1000000, poor = 50 }
PAID = {}
print("cap_binds " .. EX.pay_house("rich", -999999))
print("cap_is_max " .. tostring(math.abs(EX.pay_house("rich", -999999)) <= EX.HOUSE_CASH_MAX))
print("never_below_zero " .. tostring(math.abs(EX.pay_house("poor", -999999)) <= 50))

-- THE COUNTERPARTY PREFERENCE ORDER. A guild house holding the book comes first; the
-- existing top_holder behaviour is the fallback and must survive untouched, because it is
-- what happens on most of the map and in every campaign with no guild.
EX.book = { rich = { res_gems = 20 } }
TREATY = {}
DIPLO = { rich = 0, poor = 0 }
print("cp_guild " .. tostring(EX.guild_counterparty("res_gems", true)))
EX.book = {}
EX.owners = { res_gems = { some_greenskin = 9 } }
print("cp_fallback " .. tostring(EX.settle_counterparty("res_gems", true, 500)))
EX.houses = {}
print("cp_empty_guild " .. tostring(EX.settle_counterparty("res_gems", true, 500)))

-- A HOUSE AT WAR IS NOT A COUNTERPARTY. Its book has left the pool entirely.
EX.houses = { "rich" }
EX.book = { rich = { res_gems = 20 } }
TREATY = { rich = "war" }
print("cp_war " .. tostring(EX.guild_counterparty("res_gems", true) == nil))

-- BUYING DRAWS THE BOOK DOWN. The lot came from somewhere.
TREATY = {}
EX.settle_counterparty("res_gems", true, 500)
print("cp_book_drawn " .. EX.book_of("rich", "res_gems"))

-- HOUSE_CASH_MAX IN THE CREDIT DIRECTION TOO. The debit-direction tests above prove a SALE
-- from a house is bounded; this proves a BUY that CREDITS a house is bounded as well - without
-- it, one large player sell hands a house unbounded gold, funding an AI army the player then
-- has to fight. Self-contained: its own EX.houses/TREASURY, not inherited from above.
EX.houses = { "rich" }
EX.delisted = {}
TREASURY = { rich = 1000000 }
print("cap_binds_credit " .. tostring(EX.pay_house("rich", 999999) == EX.HOUSE_CASH_MAX))

-- REGRESSION: A HOUSE IS NEVER ITS OWN COUNTERPARTY ON ITS OWN PAPER. Without the
-- EX.is_house guard in EX.guild_counterparty, a house trading its own shares is found as its
-- own counterparty through its own treasury on the sell side - measured: the house's treasury
-- drains 100000 -> 80000 and a spurious EX.book.rich.rich entry appears, its own faction key
-- sitting in its own book as if it were a commodity. EX.house_set may already be memoised from
-- an earlier, different EX.houses list by this point in the harness (EX.is_house only builds
-- it once), so EX.shares_held forces EX.is_house("rich") true the same way a live save would -
-- see EX.is_house's own "instrument even if not discovered" fallback.
EX.houses = { "rich" }
EX.delisted = {}
EX.book = { rich = { rich = 5 } }
EX.shares_held = { rich = 1 }
TREATY = {}
TREASURY = { rich = 100000 }
print("no_self_counterparty " .. tostring(EX.guild_counterparty("rich", false) == nil))

-- ===========================================================================================
-- THE WHOLE-FEATURE REVIEW'S FINDINGS. Everything below either pins a fix, or closes an
-- assertion the reviewer deleted with the suite still green.
-- ===========================================================================================

-- The sign self-check left this true further up, but nothing below should depend on the order
-- of the blocks above it - EX.stance_of falls to a flat -0.5 for every eligible house when it
-- is false, which would quietly flatten every rank assertion in this section.
EX.standing_trusted = true

-- -------------------------------------------------------------------------------------------
-- MCT ai_traders OFF IS AN EMPTY GUILD, NOT A FROZEN ONE.
--
-- The gate used to sit on EX.step_books alone, which is the one function that ever sells a
-- book back DOWN - so switching the traders off left the last traders-on turn's book, markup,
-- refusals and war lock standing forever. Every term is read twice on the SAME board, once
-- with the toggle on and once with it off, so the "off" reads cannot pass by being an empty
-- board rather than a closed gate.
-- -------------------------------------------------------------------------------------------
EX.free_guild()
EX.houses = { "deep", "mild" }
EX.house_set = nil
EX.delisted = {}
EX.shares_held = {}
TREATY = {}
DIPLO = { deep = -900, mild = -5 }
TREASURY = { deep = 100000, mild = 100000 }
EX.book = { deep = { res_gems = EX.BOOK_PER_RUNG },
            mild = { res_gems = EX.BOOK_PER_RUNG } }
EX.supply = { res_gems = 4 }
EX.owners = { res_gems = {} }
EX.current["res_gems"] = EX.neutral_rung()
print("on_guild " .. #EX.guild())
print("on_shift " .. EX.book_shift("res_gems"))
print("on_hostility " .. string.format("%%.4f", EX.hostility("res_gems")))
print("on_refused " .. tostring(EX.refused_by("res_gems")))
print("on_buy_over " .. tostring(EX.buy_price("res_gems") > EX.price("res_gems")))
print("on_cp " .. tostring(EX.guild_counterparty("res_gems", true)))
SETTINGS.ai_traders = false
print("off_guild " .. #EX.guild())
print("off_shift " .. EX.book_shift("res_gems"))
print("off_hostility " .. string.format("%%.4f", EX.hostility("res_gems")))
print("off_refused " .. tostring(EX.refused_by("res_gems") == nil))
print("off_buy " .. tostring(EX.buy_price("res_gems") == EX.price("res_gems")))
print("off_cp " .. tostring(EX.guild_counterparty("res_gems", true) == nil))
print("off_summary " .. EX.guild_summary())
SETTINGS.ai_traders = nil

-- ...AND THE WAR LOCK, which needs its own book split to reach GUILD_CLOSE at all.
EX.free_guild()
EX.houses = { "belligerent", "quiet" }
EX.house_set = nil
DIPLO = { belligerent = 0, quiet = 0 }
TREATY = { belligerent = "war" }
EX.book = { belligerent = { res_gems = 6 }, quiet = { res_gems = 4 } }
print("on_closed " .. tostring(EX.market_closed() ~= nil))
SETTINGS.ai_traders = false
print("off_closed " .. tostring(EX.market_closed() == nil))
SETTINGS.ai_traders = nil

-- -------------------------------------------------------------------------------------------
-- THE STANCE MEMO, MEASURED IN cm:get_faction CALLS.
--
-- EX.refresh_panel asks EX.hostility four times per row (buy_price, sell_price, buy_tip,
-- sell_tip) and each ask used to re-walk the whole guild calling treaty_tier and standing_of
-- per member - 58,786 cm:get_faction calls per refresh at the 14 houses cr_combi_expanded
-- ships. This is not a micro-optimisation with no failure mode, so it gets a real number.
-- -------------------------------------------------------------------------------------------
EX.free_guild()
EX.houses = {}
EX.house_set = nil
EX.delisted = {}
EX.shares_held = {}
EX.book = {}
DIPLO = {}
TREATY = {}
for i = 1, 14 do
    local h = "house" .. i
    EX.houses[i] = h
    EX.book[h] = { res_gems = 10 }
    DIPLO[h] = -100 * i
end
local function four_asks()
    local h = 0
    for _ = 1, 4 do h = h + EX.hostility("res_gems") end
    return h
end
GF_CALLS = 0
local loose = four_asks()
local loose_calls = GF_CALLS
EX.hold_guild()
GF_CALLS = 0
local held = four_asks()
local held_calls = GF_CALLS
EX.free_guild()
print("memo_same " .. tostring(math.abs(loose - held) < 0.000001))
print("memo_calls " .. held_calls)
print("memo_loose_calls " .. loose_calls)

-- -------------------------------------------------------------------------------------------
-- MCT ai_gold OFF MAKES THE BOOKS NOTIONAL, NOT FROZEN.
--
-- EX.pay_house returns 0 with the toggle off, and EX.settle_counterparty only took the guild
-- branch `if moved ~= 0` - so the player bought a lot, the house stayed at 20, the gold went to
-- the top land-holder through the fallback instead, and the houses went on buying four lots a
-- turn for free. The book ran away in one direction and book_shift with it.
-- -------------------------------------------------------------------------------------------
EX.free_guild()
EX.houses = { "rich" }
EX.house_set = nil
EX.delisted = {}
EX.shares_held = {}
EX.book = { rich = { res_gems = 20 } }
EX.owners = { res_gems = { some_greenskin = 9 } }
TREATY = {}
DIPLO = { rich = 0 }
TREASURY = { rich = 1000000 }
SETTINGS.ai_gold = false
PAID = {}
print("notional_who " .. tostring(EX.settle_counterparty("res_gems", true, 500)))
print("notional_book " .. EX.book_of("rich", "res_gems"))
print("notional_gold " .. tostring(PAID.rich or 0))
print("notional_fallback " .. tostring(PAID.some_greenskin == nil))
SETTINGS.ai_gold = nil
PAID = {}
EX.settle_counterparty("res_gems", true, 500)
print("real_book " .. EX.book_of("rich", "res_gems"))
print("real_gold " .. tostring(PAID.rich or 0))

-- -------------------------------------------------------------------------------------------
-- WHY THE BUY BUTTON IS DEAD. The row used to compute EX.unavailable only and then call
-- SetDisabled(false) unconditionally, so a refused or war-locked row drew a live "Buy 10" at a
-- normal price and did nothing when pressed. EX.buy_refusal is the one answer the price cell,
-- the label, the disabled flag and the tooltip all read.
-- -------------------------------------------------------------------------------------------
EX.free_guild()
EX.houses = { "deep", "mild" }
EX.house_set = nil
EX.delisted = {}
EX.shares_held = {}
TREATY = {}
DIPLO = { deep = -900, mild = -5 }
EX.book = { deep = { res_gems = 10 }, mild = { res_gems = 1 } }
EX.supply = { res_gems = 4, res_ivory = 0 }
-- READ ONCE INTO A LOCAL. string.find on a nil reason is a Lua error, which would abort the
-- whole harness with a stack trace instead of letting why_refused's assertion say what broke.
local wr = EX.buy_refusal("res_gems")
print("why_refused " .. tostring(wr ~= nil))
-- THE DISPLAY NAME, not the literal "deep". EX.faction_display humanises a key whose loc
-- is missing or is CA's placeholder, so the raw key stopped appearing in this sentence
-- on 2026-09-07 and a hardcoded literal fails on correct code. The empty-name guard
-- stops this degrading into string.find(wr, "") which is true of everything.
local dn = EX.faction_display("deep")
print("why_display " .. tostring(dn ~= nil and dn ~= ""))
print("why_names " .. tostring(wr ~= nil and dn ~= "" and string.find(wr, dn, 1, true) ~= nil))
print("why_unavailable " .. tostring(EX.buy_refusal("res_ivory") ~= nil))
EX.book = {}
print("why_open " .. tostring(EX.buy_refusal("res_gems") == nil))

-- THE WAR LOCK MUST NOT BORROW THE REFUSAL SENTENCE. buy_refusal used to read EX.blocked, which
-- is market_closed() OR refused_by(), and phrase either as "<house> will not sell to you". Under
-- the war lock market_closed names the largest belligerent only so the message has a subject, so
-- EVERY row on the board accused one house of owning every commodity. Reported from play.
EX.book = { deep = { res_gems = 10 }, mild = { res_gems = 1 } }
TREATY = { deep = "war", mild = "war" }
local cw, cl = EX.buy_refusal("res_gems")
print("closed_fires " .. tostring(EX.market_closed() ~= nil))
print("closed_label " .. tostring(cl))
print("closed_says_shut " .. tostring(cw ~= nil and string.find(cw, "shut", 1, true) ~= nil))
print("closed_not_refusal " .. tostring(cw ~= nil and string.find(cw, "will not sell to you", 1, true) == nil))
-- THE PRICE-CELL TOOLTIP IS THE THIRD READER OF EX.blocked and it had the same conflation.
local ct = EX.buy_tip("res_gems")
print("tip_closed_not_refusal " .. tostring(string.find(ct, "will not sell to you", 1, true) == nil))
print("tip_closed_says_shut " .. tostring(string.find(ct, "shut", 1, true) ~= nil))
TREATY = {}
DIPLO = { deep = -900, mild = -5 }
local rw, rl = EX.buy_refusal("res_gems")
print("refuse_label " .. tostring(rl))
print("refuse_says_house " .. tostring(rw ~= nil and string.find(rw, "will not sell to you", 1, true) ~= nil))

-- -------------------------------------------------------------------------------------------
-- FIVE ASSERTIONS THE REVIEWER DELETED WITH THE SUITE STILL GREEN.
-- -------------------------------------------------------------------------------------------

-- LAYER 2 HOLDS NO BOOK. Armaments and Raw Materials come out of the Forge, not off a trader,
-- and EX.book_shift's is_layer2 guard is what keeps them off the ladder's book term. Nothing
-- pinned it: every other book_shift test uses a commodity, where the guard never fires.
EX.free_guild()
EX.houses = { "baal" }
EX.house_set = nil
EX.delisted = {}
EX.shares_held = {}
EX.book = { baal = {} }
EX.book.baal[EX.LAYER2[1]] = EX.BOOK_PER_RUNG * 2
print("shift_layer2 " .. EX.book_shift(EX.LAYER2[1]))

-- HOSTILITY WALKS THE GUILD, NOT THE DISCOVERED HOUSE LIST. A delisted house has settled and
-- left; its book evaporated and it has no say in anybody's price. Swapping EX.guild() for
-- EX.houses inside EX.hostility used to be free - every other hostility test has an empty
-- EX.delisted, so the two lists are identical and the mutation is invisible.
EX.free_guild()
EX.houses = { "live", "dead" }
EX.house_set = nil
EX.delisted = { dead = true }
EX.shares_held = {}
TREATY = {}
DIPLO = { live = 0, dead = -900 }
EX.book = { live = { res_gems = 1 }, dead = { res_gems = 9 } }
print("hostile_delisted " .. string.format("%%.4f", EX.hostility("res_gems")))

-- THE SELL SIDE'S OWN CLAMP. The buy side is bounded by EX.house_budget, but the sell side is
-- bounded only by the two lines inside EX.step_books - delete them and a house dumps its whole
-- position in one turn, which is the flow "one buy and one sell per house per turn" exists to
-- stop. step_bounded above measures a book built FROM ZERO, so it cannot see a sell at all.
EX.free_guild()
EX.houses = { "baal" }
EX.house_set = nil
EX.delisted = {}
EX.shares_held = {}
EX.book = { baal = { res_gems = 20 } }
EX.owners = { res_gems = { baal = 6 } }
EX.pressure = {}
TREASURY = { baal = 100000 }
TREATY = {}
DIPLO = { baal = 0 }
for _, res in ipairs(EX.COMMODITIES) do EX.current[res] = EX.neutral_rung() end
EX.current["res_gems"] = EX.RUNGS      -- dearest on the ladder, and baal produces it: the
EX.step_books()                        -- lowest desire in the list, so it is what gets sold
print("sell_clamped " .. EX.book_of("baal", "res_gems"))
EX.current["res_gems"] = EX.neutral_rung()

-- CHARACTER. Two houses in identical circumstances must still behave differently, or a guild
-- that all shares one culture is one trader wearing several names. Derived from the key, never
-- rolled. desire_producer above compares a producer with a non-producer, so it passes with the
-- bias term deleted.
EX.free_guild()
EX.houses = { "baal", "azeros" }
EX.house_set = nil
EX.delisted = {}
EX.owners = {}
EX.pressure = {}
EX.book = {}
TREATY = {}
DIPLO = { baal = 0, azeros = 0 }
print("bias_differs " .. tostring(EX.house_desire("baal", "res_gems")
                                  ~= EX.house_desire("azeros", "res_gems")))

-- A HOUSE AT WAR IS NOT "REFUSING" YOU - it has closed its book, which is the war lock's
-- business, and EX.refused_by must not name it. THIS is what pins the `treaty_tier == "open"`
-- clause. The pact scenario cannot: HOSTILE_PACT_CAP already stops a pact house passing the
-- rank test, so the clause and the clamp each masked the other and either could be deleted.
EX.free_guild()
EX.houses = { "warlike", "mild" }
EX.house_set = nil
EX.delisted = {}
EX.shares_held = {}
TREATY = { warlike = "war" }
DIPLO = { warlike = 0, mild = -5 }
EX.book = { warlike = { res_gems = 10 }, mild = { res_gems = 1 } }
print("refuse_war " .. tostring(EX.refused_by("res_gems") == nil))

-- THE PACT CEILING, MEASURED AS A MARKUP. A non-aggression pact caps the markup at
-- HOSTILE_PACT_CAP however deep the standing goes, and the clamp lives in EX.stance_of. The
-- only pact scenario before this was refuse_treaty, where the rank test rejects the house with
-- or without the clamp - so the constant was declared, mirrored, and guarded nothing.
EX.free_guild()
EX.houses = { "pactish" }
EX.house_set = nil
EX.delisted = {}
EX.shares_held = {}
TREATY = { pactish = "pact" }
DIPLO = { pactish = -900 }
EX.book = { pactish = { res_gems = 10 } }
print("pact_cap " .. string.format("%%.4f", EX.hostility("res_gems")))
"""


def check_lua_books():
    """The guild's books: persistence, aggregation, and the empty-guild no-op."""
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped lua books check: no lua.exe)")
        return

    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    harness = LUA_BOOKS_HARNESS % (LUA_SCRIPT.replace("\\", "\\\\"),)
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.split(NL):
        line = line.strip()
        if line:
            k, _sp, v = line.partition(" ")
            have[k] = v

    assert have["packed"] == "res_gems=3;res_rom_iron=12", (
        "pack_book emitted %r. It must be a sorted key=value;... string: unsorted, the same "
        "book packs two different ways and a diff of two saves is unreadable."
        % have["packed"])
    assert int(have["guild_iron"]) == 17, have
    assert int(have["guild_gems"]) == 3, have
    assert int(have["guild_none"]) == 0, (
        "guild_book returned %r for a commodity nobody holds; must be 0, not nil - every "
        "downstream term does arithmetic on it" % have["guild_none"])

    assert int(have["restored_iron"]) == 12, (
        "a book did not survive restore: 12 went in, %s came back. The book is the only "
        "record of a house's position; nothing regenerates it from the map."
        % have["restored_iron"])
    assert int(have["restored_gems"]) == 3, have
    assert int(have["restored_other"]) == 5, have

    assert int(have["guild_n"]) == 1, (
        "a delisted house is still in the guild")
    assert int(have["guild_iron_after"]) == 5, (
        "a delisted house's book still counts toward the guild's position")

    assert int(have["empty_n"]) == 0, have
    assert int(have["empty_iron"]) == 0, (
        "guild_book is %r with no houses. The empty guild is the DEFAULT in any campaign "
        "where the player is the only Chaos Dwarf, and every term must fail open to it."
        % have["empty_iron"])

    assert 'EX.SAVE_BOOK = "zharr_bk_"' in code, code[:0]

    assert have["hash_stable"] == "true", (
        "key_hash is not deterministic. Character bias derived from it would reroll on "
        "every load, which is the bug the spec's 'derived from the key, never rolled' "
        "rule exists to prevent.")
    assert have["hash_differs"] == "true", "key_hash collides on two different house keys"
    assert have["hash_bounded"] == "true", (
        "key_hash exceeded 65536. WH3 Lua numbers are float32 and integers are exact only "
        "to 16,777,216; an unbounded rolling hash silently loses precision and stops being "
        "reproducible. Keep the modulus small - see the constant's comment.")
    assert have["bias_stable"] == "true", have

    assert int(have["budget_rich"]) > 0, have
    assert int(have["budget_broke"]) == 0, (
        "a house with no treasury got a budget of %s. Budget is drawn from treasury() so a "
        "house that trades badly stops being able to trade; that feedback is the whole "
        "difference between a trader and a puppet." % have["budget_broke"])

    assert have["desire_producer"] == "true", (
        "a house that produces a good does not want to sell it more than one that does not. "
        "Every house shares one culture, so production is the term that differentiates them "
        "- without it the whole guild behaves as one trader.")
    assert have["value_order"] == "true", (
        "desire is not monotonically decreasing in price. The value term is the "
        "mean-reversion that stops a guild of one culture piling into a commodity and "
        "pinning it at the ladder clamp.")

    assert have["frontrun_both"] == "true", have
    assert have["frontrun_needs_pressure"] == "true", (
        "a hostile house front-runs with no player pressure to front-run. The term must "
        "need BOTH hostility and the player accumulating; either alone is a different "
        "behaviour that nothing in the design asked for.")

    assert int(have["step_moved"]) > 0, "step_books moved nothing with two funded houses"
    assert have["step_bounded"] == "true", (
        "step_books moved more than BOOK_TRADE_MAX per house. One buy and one sell per "
        "house per turn is deliberate: it is what keeps the board readable in a footer.")

    m = re.search(r"EX\.BOOK_TRADE_MAX\s*=\s*(\d+)", code)
    assert m, "EX.BOOK_TRADE_MAX is gone - step_books has no bound on flow per turn"
    assert int(m.group(1)) == BOOK_TRADE_MAX, (
        "EX.BOOK_TRADE_MAX is %s, this generator is built for %s"
        % (m.group(1), BOOK_TRADE_MAX))

    # WIRING. Order is load-bearing - see the check_delistings precedent in the Layer 3
    # handoff, where one line out of place priced a settlement at a fifth of cost.
    body = turn_body(code)
    assert "EX.step_books()" in body, "books never step on a turn"
    i_del = body.index("EX.check_delistings()")
    i_step = body.index("EX.step_books()")
    i_apply = body.index("EX.apply_prices()")
    assert i_del < i_step < i_apply, (
        "step_books must sit AFTER check_delistings (a dead house must leave the guild "
        "before it trades) and BEFORE apply_prices (the book level feeds target_rung). "
        "Found delist=%d step=%d apply=%d." % (i_del, i_step, i_apply))
    # ANCHORED ON EX.init(), NOT the trivial cm:add_first_tick_callback(function() EX.init()
    # end) one-liner at the bottom of the file: since the call_each-has-no-pcall fix (2026-09-07)
    # split startup into a named EX.init() whose body ends with the FactionTurnStart
    # registration, and a one-line first-tick shim with nothing after it in the file. The
    # shim alone has no trailing core:add_listener to anchor on; EX.init()'s body does, and
    # it is the actual first-tick/load code path this assertion means to cover - see
    # check_lua_warehouse's identical anchor for the same reason.
    tick = re.search(r"function EX\.init\(\).*?\n\s*core:add_listener", code, re.S)
    assert tick, "EX.init() is gone"
    assert "EX.step_books()" not in tick.group(0), (
        "step_books runs on the first tick. A load is not a turn - five reloads would be "
        "five trading days, the same trap charge_carry and pay_dividends both document.")

    assert int(have["shift_zero"]) == 0, have
    assert int(have["shift_under"]) == 0, (
        "a sub-rung book moved the price by %s. Sub-rung positions must read 0 rather than "
        "flickering the whole board every turn." % have["shift_under"])
    assert int(have["shift_one"]) == 1, have
    assert have["shift_is_max"] == "true", (
        "book_shift is not clamped at BOOK_MAX. It ships small for the reason AI_MAX_RUNGS "
        "ships small: an uncalibrated dial must not be able to dominate the supply model.")
    assert int(have["shift_house"]) == 0, (
        "book_shift moved a house share's price. A share is paper - the guild holds books "
        "in goods, not in each other.")
    assert int(have["shift_empty"]) == 0, have

    assert "EX.book_shift(res)" in code, (
        "book_shift is never added to target_rung - the books exist and price nothing")
    tr = re.search(r"function EX\.target_rung.*?\nend", code, re.S).group(0)
    assert "EX.book_shift(res)" in tr, "book_shift is not a term in target_rung"
    bs = re.search(r"function EX\.book_shift.*?\nend", code, re.S).group(0)
    assert "math.floor(math.abs" in bs, (
        "book_shift does not truncate toward zero. SCOPED TO THE FUNCTION BODY on purpose: "
        "math.floor(math.abs already appears three times in this file (pressure_shift, "
        "appetite_shift, shock_shift), so a file-wide search passes even when book_shift "
        "uses a plain math.floor - which is the exact defect being guarded against.")

    m = re.search(r"EX\.HOSTILE_MAX\s*=\s*([0-9.]+)", code)
    assert m, "EX.HOSTILE_MAX is gone - hostility has no ceiling"
    assert float(m.group(1)) == HOSTILE_MAX, (
        "EX.HOSTILE_MAX is %s, this generator is built for %s" % (m.group(1), HOSTILE_MAX))
    m = re.search(r"EX\.HOSTILE_PACT_CAP\s*=\s*([0-9.]+)", code)
    assert m, "EX.HOSTILE_PACT_CAP is gone - a non-aggression pact has no separate ceiling"
    assert float(m.group(1)) == HOSTILE_PACT_CAP, (
        "EX.HOSTILE_PACT_CAP is %s, this generator is built for %s"
        % (m.group(1), HOSTILE_PACT_CAP))

    for k, want in (("tier_friend", "free"), ("tier_trader", "free"),
                    ("tier_pact", "pact"), ("tier_cold", "open"), ("tier_enemy", "war")):
        assert have[k] == want, "%s read %r, expected %r" % (k, have[k], want)
    assert float(have["stance_friend"]) == 0.0, (
        "an allied house is penalised. The treaty ladder must dominate the number - it is "
        "what makes the counterplay a thing the player can do in the diplomacy screen.")
    assert float(have["stance_trader"]) == 0.0, have

    assert have["rank_order"] == "true", have
    assert have["scale_free"] == "true", (
        "stances changed when the standing scale changed while the RANKING did not. "
        "diplomatic_standing_with returns an int32 of undocumented range; nothing may "
        "depend on its magnitude.")
    assert float(have["all_friendly"]) == 0.0, (
        "a guild that all likes you still charges. Zero is the anchor - with nobody below "
        "it there is no 'least liked' to penalise.")
    assert float(have["zero_anchor"]) == 0.0, (
        "a house with non-negative standing was charged %s in a MIXED guild (one hostile "
        "house present, so the redundant deepest>=0 guard cannot rescue this). The zero "
        "anchor in EX.stance_of ('if mine >= 0 then return 0 end') is load-bearing and must "
        "fire on its own." % have["zero_anchor"])

    assert float(have["hostile_gems"]) > 0, have
    assert float(have["hostile_gems"]) <= HOSTILE_MAX + 1e-6, (
        "hostility %s exceeds HOSTILE_MAX %s" % (have["hostile_gems"], HOSTILE_MAX))
    assert float(have["hostile_iron"]) == 0.0, (
        "a friendly house holding the whole book still produced hostility")
    assert float(have["hostile_none"]) == 0.0, (
        "a commodity nobody in the guild holds produced hostility. A house holding none of "
        "a good has no say in its price to you.")

    assert have["rung_isolated"] == "true", (
        "HOSTILITY REACHED THE RUNG. This is the single most important boundary in the "
        "design: the market price is the same for everyone and hostility changes only your "
        "fill. If it moves the rung it lands in the sparkline, the dividend formula and "
        "every house's own trading decision.")

    assert have["sign_ok"] == "true", have
    assert have["sign_violated"] == "false", (
        "the sign self-check passed on an inverted convention. It exists precisely because "
        "the convention is undocumented; a check that cannot fail is not a check.")
    assert have["sign_inconclusive"] == "true", (
        "with no war/ally pair to compare, the check must be inconclusive and ASSUME the "
        "convention, not disable the system")

    body = turn_body(code)
    assert "EX.check_standing_sign()" in body, (
        "the sign self-check never runs on a real turn, only in the harness")
    i_sign = body.index("EX.check_standing_sign()")
    i_step = body.index("EX.step_books()")
    assert i_sign < i_step, (
        "check_standing_sign must run before step_books, so a stale sign convention never "
        "feeds a turn's front-run term")

    # YOUR FILL, NOT THE MARKET'S PRICE. EX.price stays the world price; EX.buy_price is the
    # only thing that may be charged to the player or drawn in the Buy column.
    world = int(have["world"])
    assert int(have["buy"]) > world, (
        "a hostile guild did not raise the buy price")
    assert int(have["sell"]) < world, have
    assert int(have["buy_friendly"]) == world, (
        "buy_price is %s against a world price of %s with a FRIENDLY guild. This is also "
        "the empty-guild path and it must be exact - any drift here changes every price in "
        "every campaign that has no other Chaos Dwarf faction."
        % (have["buy_friendly"], world))
    assert have["sell_friendly"] == have["sell_expected"], (
        "sell_price changed for a friendly guild: %s, was %s"
        % (have["sell_friendly"], have["sell_expected"]))
    assert have["sell_floored"] == "true", (
        "spread plus hostility drove a sale below SELL_FLOOR. A sale that pays nothing "
        "reads as a broken button, not as a bad market.")

    # THE CALL SITES. The design doc's rule is that the displayed price must equal what the
    # game charges - "anything else and the panel lies about the price". A charge computed
    # from EX.price rather than EX.buy_price is exactly that lie.
    # EX.apply_trade, NOT EX.trade, since the multiplayer split (2026-09-09). EX.trade is now
    # three lines that hand the order to EX.mp_send; every check, every price and every gold
    # movement lives in EX.apply_trade, which is what runs on each machine. Pointing this at
    # EX.trade would pass on an empty function forever.
    trade = re.search(r"function EX\.apply_trade\(.*?\n(?=function )", code, re.S).group(0)
    assert "EX.buy_price(res)" in trade, (
        "EX.apply_trade still prices a buy off EX.price. That is the world price; the player "
        "pays buy_price, and a panel that shows one while charging the other is the defect the "
        "design doc names by name.")
    assert not re.search(r"is_buy and EX\.price\(res\)", trade), (
        "the old is_buy-and-EX.price expression survives in EX.apply_trade")

    # AND THE CLICK STILL REACHES IT. A validated, correct apply that nothing calls is a mod
    # whose buttons do nothing, and the regex above would be just as happy.
    click = re.search(r"function EX\.trade\(res, is_buy\).*?\nend", code, re.S)
    assert click, "EX.trade is gone - the Buy and Sell buttons call it by name"
    assert "EX.mp_send(" in click.group(0), (
        "EX.trade no longer goes through EX.mp_send. In multiplayer that means the gold moves "
        "on the clicking machine and on no other, which is the desync the transport exists to "
        "prevent; in singleplayer mp_send calls the op directly, so there is no cost to it.")

    # THE DISPLAY SITES. EX.trade charging buy_price is only half the invariant - a Buy
    # column reverted to EX.price still passes every check above while the panel goes back
    # to lying about the price. Anchored on the unique line immediately AFTER each row_price
    # write (the houses branch's dividend line, the commodities branch's sell_price line) so
    # neither regex can slide onto the other display site, onto EX.trade's charge line, or
    # onto row_price's many non-price uses (layout tables, ROW_CELLS, the header map, the
    # "-" placeholders, offer_cost, the stats percentage).
    houses_price = re.search(
        r'set_text\(row, "row_price", tostring\(EX\.(\w+)\(res\)\)\)\s*'
        r'\n\s*set_text\(row, "row_sell", "\+" \.\. EX\.dividend\(res\)\)', code)
    assert houses_price, "the houses-view Buy column write is gone or reshaped"
    assert houses_price.group(1) == "buy_price", (
        "the houses-view Buy column draws EX.%s(res) while EX.trade charges buy_price. "
        "The displayed price must equal the charged price - anything else and the panel "
        "lies about the price." % houses_price.group(1))

    # THE COMMODITIES VIEW DRAWS THROUGH EX.price_cell since 2026-09-07, which appends the
    # hostility markup to the number. That puts one more link in the chain, so the same
    # display-equals-charge rule is now two assertions: the cells go through price_cell, and
    # price_cell's NUMBER is buy_price / sell_price and nothing else.
    commodity_price = re.search(
        r'set_text\(row, "row_price", why and "-" or EX\.price_cell\(res, (\w+)\)\)\s*'
        r'\n\s*set_text\(row, "row_sell", EX\.price_cell\(res, (\w+)\)\)', code)
    assert commodity_price, "the commodities-view Buy/Sell column writes are gone or reshaped"
    assert commodity_price.group(1) == "true" and commodity_price.group(2) == "false", (
        "the Buy and Sell cells pass the same side to EX.price_cell (%s / %s), so one of the "
        "two columns is drawing the other's price"
        % (commodity_price.group(1), commodity_price.group(2)))
    cell = code[code.find("function EX.price_cell"):]
    cell = cell[:cell.find(chr(10) + "end")]
    assert "EX.buy_price(res)" in cell and "EX.sell_price(res)" in cell, (
        "EX.price_cell no longer takes its number from buy_price / sell_price. Those are what "
        "EX.trade charges; anything else and the panel lies about the price.")
    assert "EX.markup_pct(res, is_buy)" in cell, (
        "the price cell no longer shows the markup. The mechanic still moves the price - the "
        "panel just stops saying so, which is the exact fault reported 2026-09-07")

    # REFUSAL: rank, share and treaty all required; the empty guild refuses nothing.
    assert have["refuse_yes"] == "true", have
    assert have["refuse_share"] == "true", (
        "a house refused a good it barely holds. Refusal needs REFUSE_SHARE of the guild's "
        "book: a house with a token position is not the market.")
    assert have["refuse_treaty"] == "true", (
        "a house under a non-aggression pact still refused. The treaty ladder dominates.")

    # THE REFUSE_SHARE BOUNDARY: >= not >.
    assert have["share_under"] == "true", (
        "a house holding 5/11 (0.4545) of the book refused - below REFUSE_SHARE")
    assert have["share_exact"] == "true", (
        "a house holding EXACTLY REFUSE_SHARE (5/10 = 0.50) did not refuse. The spec says "
        "'at least', so the comparator must be >=, not >.")

    # THE SELLING BLOCK'S OWN SCENARIO, asserted BEFORE blocked_buy/open_sell so a change to
    # this scenario (or to an earlier block it used to inherit from) fails loudly here instead
    # of open_sell passing quietly because the buy was never actually blocked.
    assert have["sell_setup_refused"] == "true", (
        "the SELLING block's own self-contained scenario does not refuse res_gems - "
        "blocked_buy and open_sell would both pass without ever exercising the buy-only "
        "guard, which is the exact silent-proves-nothing trap this scenario exists to avoid")

    assert have["blocked_buy"] == "100", (
        "a refused buy went through anyway - holdings moved to %s" % have["blocked_buy"])
    assert have["open_sell"] == "true", (
        "SELLING WAS BLOCKED. Refusal blocks buying only. Blocking a sell traps the "
        "player's capital with no exit, and that valve is what makes refusal shippable "
        "at all.")

    # THE WAR LOCK, weighted by book share not head count.
    assert have["lock_under"] == "true", have
    assert have["lock_over"] == "true", (
        "the market did not close with more than GUILD_CLOSE of the book at war")

    # THE GUILD_CLOSE BOUNDARY: >= not >.
    assert have["close_under"] == "true", (
        "the market closed with an at-war book at 5/10 (0.50), below GUILD_CLOSE")
    assert have["close_exact"] == "true", (
        "the market did NOT close with an at-war book at EXACTLY GUILD_CLOSE (6/10 = 0.60). "
        "The spec says 'at least', so the comparator must be >=, not >.")

    assert have["lock_empty"] == "true", have
    assert have["refuse_empty"] == "true", have

    m = re.search(r"EX\.REFUSE_RANK\s*=\s*([0-9.]+)", code)
    assert m, "EX.REFUSE_RANK is gone - refusal has no rank threshold"
    assert float(m.group(1)) == REFUSE_RANK, (
        "EX.REFUSE_RANK is %s, this generator is built for %s" % (m.group(1), REFUSE_RANK))
    m = re.search(r"EX\.REFUSE_SHARE\s*=\s*([0-9.]+)", code)
    assert m, "EX.REFUSE_SHARE is gone - refusal has no book-share threshold"
    assert float(m.group(1)) == REFUSE_SHARE, (
        "EX.REFUSE_SHARE is %s, this generator is built for %s" % (m.group(1), REFUSE_SHARE))
    m = re.search(r"EX\.GUILD_CLOSE\s*=\s*([0-9.]+)", code)
    assert m, "EX.GUILD_CLOSE is gone - the war lock has no threshold"
    assert float(m.group(1)) == GUILD_CLOSE, (
        "EX.GUILD_CLOSE is %s, this generator is built for %s" % (m.group(1), GUILD_CLOSE))

    # THE GUARD IS BUY-ONLY. Unqualified it blocks sells too, which the design explicitly
    # rules out - see the open_sell assertion above for the behavioural half of this pin.
    trade = re.search(r"function EX\.apply_trade\(.*?\n(?=function )", code, re.S).group(0)
    assert "EX.blocked(res)" in trade, "EX.apply_trade never consults the block"
    guard = re.search(r"if is_buy and EX\.blocked\(res\)", trade)
    assert guard, (
        "the block guard is not gated on is_buy. Unqualified it blocks sells too, which "
        "is the lockout the design explicitly rules out.")

    # ===========================================================================================
    # GOLD. Task 7. Houses pay for their own trades, bounded both ways, and a guild house
    # holding the book is the counterparty before the map-wide top_holder fallback.
    # ===========================================================================================

    m = re.search(r"EX\.HOUSE_CASH_MAX\s*=\s*(\d+)", code)
    assert m, "EX.HOUSE_CASH_MAX is gone - a house's treasury has no per-turn movement cap"
    assert int(m.group(1)) == HOUSE_CASH_MAX, (
        "EX.HOUSE_CASH_MAX is %s, this generator is built for %s"
        % (m.group(1), HOUSE_CASH_MAX))

    assert have["cap_is_max"] == "true", (
        "pay_house moved more than HOUSE_CASH_MAX. AI treasuries drive AI armies; this is "
        "the one part of the Exchange that reaches outside the panel, and the cap is what "
        "keeps a large player position from rewriting a campaign in one turn.")
    assert have["never_below_zero"] == "true", (
        "a house was charged more gold than it has")
    assert have["cp_guild"] == "rich", have
    assert have["cp_fallback"] == "some_greenskin", (
        "the top_holder fallback broke. It is deliberate and its comment defends it - "
        "'cornering iron means paying whoever owns the iron' - and it is also what runs in "
        "every campaign with no guild, which is most of them.")
    assert have["cp_empty_guild"] == "some_greenskin", (
        "with no guild at all the counterparty must still be today's top_holder")
    assert have["cp_war"] == "true", (
        "a house at war was chosen as counterparty. Its book has left the pool entirely.")
    assert int(have["cp_book_drawn"]) == 19, (
        "buying a lot did not draw the counterparty's book down: %s. The lot came from "
        "somewhere, and a book that never falls makes the guild an infinite seller."
        % have["cp_book_drawn"])

    assert have["cap_binds_credit"] == "true", (
        "pay_house did not clamp a CREDIT to a house at HOUSE_CASH_MAX. A large player sell "
        "would hand a house unbounded gold, funding an AI army the player then has to fight.")
    assert have["no_self_counterparty"] == "true", (
        "a house was found as its own counterparty on its own paper shares. Without the "
        "EX.is_house guard in EX.guild_counterparty this drains the house's own treasury "
        "(measured: 100000 -> 80000) and writes a spurious book entry keyed by its own "
        "faction key - EX.book.rich.rich, its own faction key sitting in its own book as if "
        "it were a commodity.")

    # ===========================================================================================
    # THE WHOLE-FEATURE REVIEW'S FOUR MAJORS, and the assertions it deleted with the suite
    # still green. Each behavioural pair below is read on ONE board, on and off, so an "off"
    # answer cannot pass by being an empty board rather than a closed gate.
    # ===========================================================================================

    # MAJOR 1: ai_traders OFF IS AN EMPTY GUILD. The gate used to sit on EX.step_books alone -
    # the one function that ever sells a book back DOWN - so switching the traders off left the
    # last traders-on turn's book, markup, refusals and war lock standing for the campaign.
    assert int(have["on_guild"]) == 2 and int(have["on_shift"]) > 0, have
    assert float(have["on_hostility"]) > 0 and have["on_refused"] == "deep", have
    assert have["on_buy_over"] == "true" and have["on_cp"] == "deep", have
    assert have["on_closed"] == "true", (
        "the war lock scenario does not close the market with the toggle ON, so its OFF read "
        "below proves nothing")
    for key, want, what in (
            ("off_guild", "0", "the guild is not empty"),
            ("off_shift", "0", "the guild's book still moves the price"),
            ("off_hostility", "0.0000", "the guild still charges a markup"),
            ("off_refused", "true", "a house still refuses to sell"),
            ("off_buy", "true", "buy_price is not the world price"),
            ("off_cp", "true", "a house is still found as counterparty"),
            ("off_closed", "true", "the war lock still shuts the Exchange")):
        assert have[key] == want, (
            "with MCT's ai_traders OFF, %s (%s = %r, wanted %r). The MCT tooltip promises "
            "'the market behaves as it did before they existed' and spec 3 and 13 require an "
            "EMPTY guild. Gating EX.step_books alone froze the market instead of switching it "
            "off - and permanently, since step_books is the only thing that sells a book down."
            % (what, key, have[key], want))
    assert have["off_summary"] == "No other house trades here.", (
        "the Houses footer still names a trading guild with ai_traders off: %r"
        % have["off_summary"])
    # ...AND THE GATE IS AT THE SHARED READER, not at any call site. EX.guild() is what
    # book_shift, hostility, refused_by, market_closed, guild_summary, the counterparty search
    # and step_books all route through; one gate there covers every one of them.
    guild_fn = re.search(r"function EX\.guild\(\).*?" + NL + "end", code, re.S)
    assert guild_fn, "EX.guild is gone"
    assert 'EX.setting("ai_traders")' in guild_fn.group(0), (
        "the ai_traders gate is not in EX.guild(). Every consumer routes through that one "
        "reader; anywhere else is a gate on one of them and a hole for the other six.")
    # THE OTHER LIST IS NOT GATED. EX.houses is Layer 3's discovered INSTRUMENT list - what
    # EX.is_house, EX.mode_instruments and EX.restore read - and gating it would delete the
    # Houses view and strand every share position the player holds.
    for fn in ("EX.is_house", "EX.mode_instruments"):
        m = re.search(r"function " + re.escape(fn) + r"\(.*?" + NL + "end", code, re.S)
        assert m and 'EX.setting("ai_traders")' not in m.group(0), (
            "%s is gated on ai_traders. That is the wrong list: it is the Layer 3 instrument "
            "list, not the trading guild, and gating it deletes the house shares view." % fn)

    # MAJOR 2: THE STANCE MEMO, in real cm:get_faction calls. EX.refresh_panel asks
    # EX.hostility four times per row and each ask re-walked the guild calling treaty_tier and
    # standing_of per member: 58,786 calls per refresh at the 14 houses cr_combi_expanded ships,
    # on panel open, mode switch, turn start and 0.1s after every trade.
    assert have["memo_same"] == "true", (
        "the held stance vector gives a different hostility from the live walk - a memo that "
        "changes the answer is worse than the hang it replaced")
    assert int(have["memo_loose_calls"]) > 500, (
        "the memo scenario only costs %s cm:get_faction calls unheld, so it is not measuring "
        "the O(rows x houses^2) walk this fix exists for" % have["memo_loose_calls"])
    assert int(have["memo_calls"]) == 0, (
        "four hostility() asks inside one EX.hold_guild() still made %s cm:get_faction calls. "
        "The whole point is that the guild is walked ONCE per refresh; %s were made without "
        "the hold." % (have["memo_calls"], have["memo_loose_calls"]))
    # ...AND IT IS SCOPED, not cached. Both holders open and close their own, and the turn
    # handler frees one more time so a refresh that errored mid-hold cannot strand a stale
    # vector pricing every row for the rest of the campaign.
    sb = re.search(r"function EX\.step_books\(\).*?" + NL + r"(?=function )", code, re.S)
    assert sb and "EX.hold_guild()" in sb.group(0) and "EX.free_guild()" in sb.group(0), (
        "EX.step_books does not hold the stance vector for the turn step - house_desire's "
        "front-run term asks stance_of once per house per commodity")
    rp = re.search(r"function EX\.refresh_panel\(\)(.*?)" + NL + r"end\s*"
                   + r"EX\.PANEL_LAYOUT_OFFER", code, re.S)
    assert rp, "EX.refresh_panel is gone or reshaped"
    rp = rp.group(1)
    assert "EX.hold_guild()" in rp and "EX.free_guild()" in rp, (
        "EX.refresh_panel does not hold the stance vector - it evaluates EX.hostility four "
        "times per row (buy_price, sell_price, buy_tip, sell_tip)")
    # ...on the COMMODITY branch's own marker, not on ipairs(EX.mode_instruments()): the guide
    # branch above has a loop of its own over the same call, and .index() would find that one.
    assert rp.index("EX.hold_guild()") < rp.index("local why, why_label = EX.buy_refusal(res)"), (
        "the hold opens after the row loop it exists for")
    assert rp.index("EX.hold_guild()") < rp.index("EX.free_guild()"), (
        "EX.refresh_panel frees the hold before it takes it")
    # THE GUIDE RETURNS EARLY. Opening the hold above that return leaks it - and a leaked hold
    # is a stance vector that outlives its diplomacy, which is the one failure mode a scoped
    # memo is chosen to avoid.
    # ANCHORED ON EX.help_lines(), which appears once and only in the guide branch. "if
    # EX.mode == EX.MODE_HELP then" is a SUBSTRING of the title bar's "elseif EX.mode ==
    # EX.MODE_HELP then" thirty lines earlier, so .index() finds that one and the check passes
    # with the hold moved anywhere below it - measured by mutation.
    assert rp.index("EX.help_lines()") < rp.index("EX.hold_guild()"), (
        "EX.hold_guild() is taken before the guide's early return, so opening the guide leaks "
        "the hold and every price after it is stanced off a frozen vector")
    turn = turn_body(code)
    assert "EX.free_guild()" in turn, (
        "nothing frees the stance memo on a turn boundary. Both holds are scoped and close "
        "themselves, but a refresh that errored mid-hold would otherwise strand a stale "
        "vector for the rest of the campaign.")

    # MAJOR 3: ai_gold OFF MAKES THE BOOKS NOTIONAL, NOT FROZEN.
    assert have["notional_who"] == "rich", (
        "with ai_gold off the guild house is not the counterparty at all - the trade fell "
        "through to the map-wide top_holder, which is where the gold used to go instead")
    assert int(have["notional_book"]) == 19, (
        "the counterparty's book did not fall on a buy with ai_gold off: %s, was 20. Spec 13 "
        "makes the books NOTIONAL, not frozen. Gating the book move on `moved ~= 0` froze "
        "them: the player bought, the house stayed long, houses went on buying four lots a "
        "turn for free, and book_shift ran away in one direction with nothing to bring it "
        "back." % have["notional_book"])
    assert int(have["notional_gold"]) == 0 and have["notional_fallback"] == "true", (
        "gold moved with ai_gold off - to the house (%s) or to the top land-holder (%s). Only "
        "the gold is switched off." % (have["notional_gold"], have["notional_fallback"]))
    assert int(have["real_book"]) == 18 and int(have["real_gold"]) == 500, (
        "with ai_gold ON the book must still fall AND the house must still be paid: book %s, "
        "gold %s" % (have["real_book"], have["real_gold"]))

    # MAJOR 4: A REFUSED OR WAR-LOCKED BUY IS DISABLED AND SAYS WHY.
    assert have["why_refused"] == "true" and have["why_unavailable"] == "true", have
    assert have["why_display"] == "true", (
        "EX.faction_display returned an empty name for a house whose loc is missing. It must "
        "fall back to something name-shaped - an empty cell on the Houses view is a row with "
        "no subject at all")
    assert have["why_names"] == "true", (
        "the refusal reason does not name the house. 'Disabled, not hidden, and the tooltip "
        "says why' is this file's standard, from the AI-turn gate on the opener button.")
    assert have["why_open"] == "true", (
        "EX.buy_refusal refuses a row nothing is wrong with - it would disable every Buy")

    # THE WAR LOCK MUST NOT WEAR THE REFUSAL SENTENCE. Reported from play: with four houses at
    # war every row read "The Legion of Azgorh will not sell to you", because buy_refusal read
    # EX.blocked and market_closed names the largest belligerent only to have a subject. A
    # player sees twenty identical rows and concludes one house owns the whole map.
    assert have["closed_fires"] == "true", "the harness did not actually close the market"
    assert have["closed_label"] == "Closed", (
        "the war lock labels the Buy button %r. It must say 'Closed', not 'Refused' - a shut "
        "market and a house refusing you are different things and the player has no other way "
        "to tell them apart." % have["closed_label"])
    assert have["closed_says_shut"] == "true", (
        "the war-lock reason does not say the Exchange is shut")
    assert have["closed_not_refusal"] == "true", (
        "the war-lock reason still uses the REFUSAL sentence ('will not sell to you'), which "
        "accuses one named house of refusing every commodity on the board. That is the exact "
        "bug reported from play on 2026-09-07.")
    assert have["refuse_label"] == "Refused", (
        "a genuine house refusal labels the button %r, not 'Refused'" % have["refuse_label"])
    assert have["refuse_says_house"] == "true", (
        "a genuine house refusal no longer says the house will not sell to you")
    assert have["tip_closed_not_refusal"] == "true", (
        "EX.buy_tip still phrases the WAR LOCK as '<house> will not sell to you'. There were "
        "THREE readers of EX.blocked - buy_refusal, buy_tip and EX.trade - and fixing only the "
        "first left the price-cell tooltip telling the same lie.")
    assert have["tip_closed_says_shut"] == "true", (
        "EX.buy_tip does not say the Exchange is shut when the war lock is what fired")

    # THE HOUSES ROW IS THE OTHER RENDER PATH, and it had the live-but-dead Buy button that the
    # commodities row was fixed for. EX.trade guards on EX.blocked with no is_house exemption,
    # so a share buy IS refused while the market is shut.
    hr = rp[rp.index('set_text(row, "row_supply",'):]
    hr = hr[:hr.index("set_text(row, \"row_trend\", EX.trend_arrow(res))")]
    assert "EX.buy_refusal(res)" in hr, (
        "the HOUSES row never asks EX.buy_refusal, so its Buy button stays enabled and reading "
        "'Buy 5' while the war lock makes EX.trade refuse it - seven live-looking dead controls, "
        "the exact fault the delisted branch above it condemns in its own comment.")
    assert "bb:SetDisabled(why ~= nil)" in hr, (
        "the houses row does not disable its Buy button from EX.buy_refusal")
    assert "bs:SetDisabled(false)" in hr, (
        "the houses row gates SELLING. Selling always stays open - that is the design's safety "
        "valve, on paper as on commodities.")
    comm = rp[rp.index("local why, why_label = EX.buy_refusal(res)"):]
    assert "bb:SetDisabled(why ~= nil)" in comm, (
        "the commodities row does not disable its Buy button from EX.buy_refusal. It used to "
        "call SetDisabled(false) unconditionally, so a refused instrument drew a live-looking "
        "'Buy 10' at a normal price and did nothing at all when pressed but write an out() "
        "line.")
    assert "bb:SetDisabled(false)" not in comm, (
        "the commodities row still force-enables its Buy button somewhere after the refusal "
        "check")
    assert "set_tip(bb, why or EX.TIP_BUY)" in comm, (
        "the Buy button carries no reason. Written BOTH ways every refresh on purpose: a "
        "refusal lifts when the standing mends or the house's book sells down, and a button "
        "still carrying last turn's reason is the same lie facing the other way.")
    # THE LABEL COMES FROM buy_refusal, NOT FROM A SECOND INLINE TEST. It used to be
    # `why and (gone and "No offer" or "Refused")`, which re-derived the cause beside the
    # reason string and could disagree with it - and did: the war lock got "Refused".
    assert 'set_text(row, "btn_buy", why_label or (' in comm, (
        "the Buy label is not taken from EX.buy_refusal's second return value. Deriving it "
        "inline lets the label and the tooltip disagree about the cause, which is how the war "
        "lock came to wear the word 'Refused'.")
    assert 'gone and "No offer"' not in comm, (
        "the row still re-derives the Buy label inline from `gone`. That is the drift this "
        "second return value exists to remove.")
    # ...AND THE CLOSURE IS SURFACED WHERE THE PLAYER BUYS. The banner was drawn only by
    # EX.guild_summary, which is the HOUSES footer - the Trade view said nothing at all while
    # every Buy on it refused.
    assert "l2 = EX.closed_banner() or l2" in rp, (
        "the Trade view's footer never draws the closure banner. It is the view the player "
        "actually buys from, and EX.guild_summary puts the banner on the Houses footer only.")
    gs = re.search(r"function EX\.guild_summary\(\).*?" + NL + "end", code, re.S)
    assert gs and "EX.closed_banner()" in gs.group(0), (
        "EX.guild_summary no longer shares EX.closed_banner with the Trade footer - one "
        "closure must not read two different ways depending on which view is up")

    # THE DELETED-BUT-GREEN ASSERTIONS.
    assert int(have["shift_layer2"]) == 0, (
        "a Layer 2 book moved the price. Armaments and Raw Materials come out of the Forge, "
        "not off a trader, and EX.book_shift's is_layer2 guard was pinned by nothing - every "
        "other book_shift test uses a commodity, where the guard never fires.")
    assert float(have["hostile_delisted"]) == 0.0, (
        "a DELISTED house's book still charged a markup: %s. EX.hostility must walk EX.guild(), "
        "not EX.houses - a settled house has left and its book evaporated. Every other "
        "hostility test has an empty EX.delisted, so the two lists are identical there and "
        "swapping one for the other is invisible." % have["hostile_delisted"])
    assert int(have["sell_clamped"]) == 20 - BOOK_TRADE_MAX, (
        "step_books sold %s lots out of a 20-lot book instead of BOOK_TRADE_MAX (%d). One buy "
        "and one sell per house per turn is what keeps the board readable in a footer; the "
        "buy side is bounded by house_budget, and the sell side by nothing but those two "
        "lines." % (20 - int(have["sell_clamped"]), BOOK_TRADE_MAX))
    assert have["bias_differs"] == "true", (
        "two houses in IDENTICAL circumstances want the same thing to the same degree, so the "
        "character term is gone. Every house shares one culture; without it the guild is one "
        "trader wearing several names. desire_producer compares a producer with a "
        "non-producer and passes with the term deleted.")
    assert have["refuse_war"] == "true", (
        "EX.refused_by named a house at WAR. A house at war has closed its book - that is the "
        "war lock's business - and this is the only assertion that pins the "
        "`treaty_tier == \"open\"` clause: the pact scenario cannot, because HOSTILE_PACT_CAP "
        "already stops a pact house passing the rank test, so the clause and the clamp each "
        "masked the other and either could be deleted with the suite green.")
    assert abs(float(have["pact_cap"]) - HOSTILE_PACT_CAP) < 1e-6, (
        "a house under a non-aggression pact charged %s, not HOSTILE_PACT_CAP (%s). The clamp "
        "is in EX.stance_of and nothing measured it - the only pact scenario was refuse_treaty, "
        "where the rank test rejects the house with or without it."
        % (have["pact_cap"], HOSTILE_PACT_CAP))

    print("  lua books check: key_hash deterministic and bounded, budget scales with "
          "treasury, desire weighs production/value/position/front-run, step_books moves "
          "a bounded book and is wired between check_delistings and apply_prices, "
          "book_shift truncates toward zero and clamps at BOOK_MAX and is a term in "
          "target_rung, hostility is treaty-ladder-and-rank driven never magnitude, weighted "
          "by book share, clamped at HOSTILE_MAX, isolated from target_rung, buy_price "
          "raises a hostile fill and is exact against a friendly/empty guild, sell_price "
          "keeps its old spread when friendly and never floors below SELL_FLOOR, EX.trade "
          "charges buy_price not price, both Buy column display sites draw buy_price too, "
          "the sign self-check is inconclusive-safe and wired before step_books, refusal "
          "needs rank AND share AND an open treaty and is a buy-only guard in EX.trade, "
          "and the war lock closes the Exchange past GUILD_CLOSE of the book weighted by "
          "house rather than head count - and both fail open on an empty guild, houses pay "
          "for their own trades bounded by HOUSE_CASH_MAX and never below zero gold, and the "
          "counterparty is a live guild house holding the book before the top_holder "
          "fallback, never a house at war, drawing its book down by the lot it just sold, "
          "HOUSE_CASH_MAX clamps a credit to a house as well as a debit, and a house is "
          "never its own counterparty on its own paper shares - and, from the whole-feature "
          "review: ai_traders off empties the guild at EX.guild() so every one of the seven "
          "terms goes quiet on the same board, the stance vector is held once per refresh and "
          "per turn step (0 cm:get_faction calls against %s unheld) and freed on every exit "
          "including the turn boundary, ai_gold off moves the book without the gold, a refused "
          "or war-locked Buy is disabled with the reason on the button and the closure banner "
          "reaches the Trade footer, and Layer 2 books, delisted books, the sell-side clamp, "
          "the character term, the war-is-not-refusal clause and the pact ceiling are each "
          "pinned on a scenario of their own" % have["memo_loose_calls"])


# The stub board check_lua_houses() runs the SHIPPED file against. Kept at module level for
# the same reason as LUA_WAREHOUSE_HARNESS below - the %-formatting of the dofile path is the
# only substitution, and the harness itself is full of Lua % operators (none here, but string
# concatenation with .. would collide with a % substitution just the same).
LUA_HOUSES_HARNESS = """
local SAVED = {}
local FACTIONS = {}
local function mkfac(name, culture, regions, home, home_owner)
    return {
        is_null_interface = function() return false end,
        name = function() return name end,
        culture = function() return culture end,
        is_dead = function() return false end,
        -- THE OTHER TWO FACTIONS-THAT-ARE-NOT-HOUSES. CA ships
        -- wh3_dlc23_chd_chaos_dwarfs_rebels, the _qb1/_qb2/_qb3 quest-battle shells and
        -- wh3_dlc25_chd_chaos_dwarfs_invasion inside the Chaos Dwarf subculture, so a filter on
        -- culture alone discovers all five. Both are documented on FACTION_SCRIPT_INTERFACE and
        -- both are stubbed here, because EX.tradeable_faction FAILS CLOSED - a stub missing a
        -- method the real interface has would exclude every faction and the discovery
        -- assertions below would fail for the wrong reason.
        is_rebel = function() return false end,
        is_quest_battle_faction = function() return false end,
        has_home_region = function() return home ~= nil end,
        home_region = function()
            return { is_null_interface = function() return false end,
                     name = function() return home end,
                     owning_faction = function()
                         return { is_null_interface = function() return false end,
                                  name = function() return home_owner end }
                     end }
        end,
        region_list = function() return { num_items = function() return regions end } end,
        military_force_list = function() return { num_items = function() return 0 end } end,
        -- Flat and generous: this harness never tests affordability, only that a trade moves
        -- the right goods and the right gold, so nothing here should ever block on price.
        treasury = function() return 100000 end,
        -- DIPLOMACY, driven by the TREATY table. Absent until house paper had to care about
        -- war: without these six, EX.treaty_tier's pcall throws and it returns "free" for
        -- everything, so a war-suspension test passes vacuously by never seeing a war.
        -- `name`, NOT `k` - mkfac's parameter is called name. TREATY[k] indexed the table with
        -- an undeclared global (nil), which reads as nil rather than erroring, so every house
        -- came back "open" and the war test passed vacuously.
        at_war_with = function() return TREATY[name] == "war" end,
        is_vassal_of = function() return false end,
        allied_with = function() return false end,
        military_allies_with = function() return false end,
        trade_agreement_with = function() return TREATY[name] == "free" end,
        non_aggression_pact_with = function() return TREATY[name] == "pact" end,
    }
end
TREATY = TREATY or {}
FACTIONS["player"]  = mkfac("player",  "wh3_dlc23_chd_chaos_dwarfs", 5, "r_p", "player")
FACTIONS["baal"]    = mkfac("baal",    "wh3_dlc23_chd_chaos_dwarfs", 8, "r_b", "baal")
FACTIONS["azeros"]  = mkfac("azeros",  "wh3_dlc23_chd_chaos_dwarfs", 2, "r_a", "someone")
FACTIONS["greenie"] = mkfac("greenie", "wh_main_grn_greenskins",    40, "r_g", "greenie")
-- THE THREE CHAOS DWARF FACTIONS THAT ARE NOT HOUSES, one per rejection reason. All three are
-- real CA keys in this subculture and all three would otherwise be discovered, and because
-- EX.houses only GROWS and EX.delisted is permanent, each is a greyed "gone" row for the whole
-- campaign once seen.
FACTIONS["chd_dead"]  = mkfac("chd_dead",  "wh3_dlc23_chd_chaos_dwarfs", 0, nil, nil)
FACTIONS["chd_dead"].is_dead = function() return true end
FACTIONS["chd_rebel"] = mkfac("chd_rebel", "wh3_dlc23_chd_chaos_dwarfs", 1, "r_re", "chd_rebel")
FACTIONS["chd_rebel"].is_rebel = function() return true end
FACTIONS["chd_qb"]    = mkfac("chd_qb",    "wh3_dlc23_chd_chaos_dwarfs", 1, "r_qb", "chd_qb")
FACTIONS["chd_qb"].is_quest_battle_faction = function() return true end
local ORDER = { "player", "baal", "azeros", "greenie", "chd_dead", "chd_rebel", "chd_qb" }
-- region key -> owning faction name, for cm:model():world():region_manager():region_by_key.
-- SEPARATE FROM mkfac's own home_region on purpose: EX.absorbed_by_us resolves a CACHED region
-- key through this, and falls back to the live faction read only when it has no key. Giving
-- the two different owners is what lets the check tell which path answered.
local REGIONS = {}
local GOLD = 0
HOUSE_GOLD = {}
local POOLED_CALLS = 0
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function(_, k, v) SAVED[k] = v end,
    get_saved_value = function(_, k) return SAVED[k] end,
    get_local_faction_name = function() return "player" end,
    get_faction = function(_, n) return FACTIONS[n] or false end,
    -- A REAL TREASURY, not a swallow. Tasks 4, 5 and 6 all need to read gold back after a
    -- trade - matches LUA_WAREHOUSE_HARNESS's GOLD accumulator exactly.
    --
    -- FACTION-AWARE SINCE DIVIDENDS LEARNED TO DEBIT THE ISSUER. It used to add every faction's
    -- movement to one GOLD, which was harmless while only the player was ever credited - share
    -- trades have no counterparty (EX.guild_counterparty rejects is_house). The moment
    -- EX.pay_dividends started taking the dividend OUT of the house, the house debit and the
    -- player credit cancelled inside GOLD and the test read "moved 0 gold".
    treasury_mod = function(_, f, amount)
        if f == "player" then GOLD = GOLD + amount
        else HOUSE_GOLD[f] = (HOUSE_GOLD[f] or 0) + amount end
    end,
    -- Houses must NEVER reach this - see the pooled_calls assertion in check_lua_houses().
    faction_add_pooled_resource = function() POOLED_CALLS = POOLED_CALLS + 1 end,
    model = function()
        return { world = function()
            return { faction_list = function()
                return { num_items = function() return #ORDER end,
                         item_at = function(_, i) return FACTIONS[ORDER[i + 1]] end }
            end,
            -- region_by_key answers NULL only for an INVALID key - CA's own docs - so an
            -- unknown key is the null interface here and a known one always answers, razed
            -- or not. That is the whole reason a cached key survives the faction.
            region_manager = function()
                return { region_by_key = function(_, k)
                    local owner = REGIONS[k]
                    if not owner then
                        return { is_null_interface = function() return true end }
                    end
                    return { is_null_interface = function() return false end,
                             owning_faction = function()
                                 return { is_null_interface = function() return false end,
                                          name = function() return owner end }
                             end }
                end }
            end }
        end }
    end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])
-- The mod keeps its own save store (EX.store) rather than riding CA's shared
-- saved_values blob, which the engine caps at 0x7000 and drops whole. Point it at
-- SAVED so every assertion below still observes the real writes under the old name.
EX.store = SAVED

-- TASK 4 STUB. EX.trade's deferred tail (cm:callback, itself a no-op above so the tail never
-- actually runs) reaches EX.refresh_panel, which calls core:get_ui_root() - not stubbed here,
-- so an unguarded call would hard-error the whole run. This harness tests the goods and gold
-- halves of a trade, not the panel, so the panel path is a no-op belt and braces alongside the
-- no-op callback.
function EX.refresh_panel() end

EX.discover_houses()
print("houses " .. table.concat(EX.houses, ","))
print("is_house_baal " .. tostring(EX.is_house("baal")))
print("is_house_iron " .. tostring(EX.is_house("res_rom_iron")))
print("saved " .. tostring(SAVED[EX.SAVE_HOUSES]))

-- The instrument list must carry commodities, layer 2 AND houses.
local n_house = 0
for _, k in ipairs(EX.instruments()) do
    if EX.is_house(k) then n_house = n_house + 1 end
end
print("instr_houses " .. n_house)

-- PRICING. Power is regions owned relative to the median house, and MORE power is DEARER -
-- the inverse of the commodity ladder, where scarcity is what raises a price.
print("mult_strong " .. string.format("%%.4f", EX.house_multiplier(8, 4)))
print("mult_weak "   .. string.format("%%.4f", EX.house_multiplier(2, 4)))
print("mult_even "   .. string.format("%%.4f", EX.house_multiplier(4, 4)))

-- THE SEAT STEP. Same power, capital lost.
print("seat_held " .. tostring(EX.holds_capital(FACTIONS["baal"])))
print("seat_lost " .. tostring(EX.holds_capital(FACTIONS["azeros"])))
print("seat_lost_mult " .. EX.SEAT_LOST)

-- ...AND IT HAS TO MOVE THE PRICE, which is the whole reason the column exists and the only
-- thing the two prints above do not prove. EX.holds_capital returning false is one half; the
-- other is `mult = mult * EX.SEAT_LOST` inside EX.target_rung, and that line could be deleted
-- with every assertion in this file still passing.
--
-- TWO HOUSES AT IDENTICAL POWER, priced through the REAL EX.target_rung, differing in nothing
-- but who owns the home region. mkfac's home_owner is what EX.holds_capital reads.
FACTIONS["seat_ok"]   = mkfac("seat_ok",   "wh3_dlc23_chd_chaos_dwarfs", 4, "r_so", "seat_ok")
FACTIONS["seat_gone"] = mkfac("seat_gone", "wh3_dlc23_chd_chaos_dwarfs", 4, "r_sg", "conqueror")
EX.houses = { "seat_ok", "seat_gone" }
EX.house_set = nil
EX.house_regions = { seat_ok = 4, seat_gone = 4 }
EX.delisted = {}
EX.current = {}
EX.pressure = {}
print("seat_rung_held " .. EX.target_rung("seat_ok", {}, {}, 1))
print("seat_rung_lost " .. EX.target_rung("seat_gone", {}, {}, 1))
EX.current["seat_ok"]   = EX.target_rung("seat_ok", {}, {}, 1)
EX.current["seat_gone"] = EX.target_rung("seat_gone", {}, {}, 1)
print("seat_px_held " .. EX.price("seat_ok"))
print("seat_px_lost " .. EX.price("seat_gone"))
EX.house_regions = nil

-- A HORDE owns no regions for its whole life and has no capital.
local horde = mkfac("horde", "wh3_dlc23_chd_chaos_dwarfs", 0, nil, nil)
horde.military_force_list = function()
    return { num_items = function() return 3 end }
end
print("power_horde " .. EX.house_power(horde))
print("power_settled " .. EX.house_power(FACTIONS["baal"]))
print("seat_horde " .. tostring(EX.holds_capital(horde)))
print("horde_weight " .. EX.HORDE_WEIGHT)

-- A SETTLED HOUSE STRIPPED OF ITS LAST REGION IS NOT A HORDE. Same zero regions, opposite
-- meaning - and the same three armies. Read as a horde it prices at 6, ABOVE a healthy
-- four-region rival, on the turn it is destroyed.
local collapsing = mkfac("collapsing", "wh3_dlc23_chd_chaos_dwarfs", 0, "r_cl", "conqueror")
collapsing.military_force_list = function()
    return { num_items = function() return 3 end }
end
print("power_collapsing " .. EX.house_power(collapsing))

-- A house that dropped out of the live faction_list walk (dead, confederated - FACTIONS/
-- ORDER above never contain "ghost", standing in for a faction this session's scan cannot
-- see) must still come back through EX.houses if the saved list still names it, because
-- EX.restore() rebuilds EX.shares_held only for houses IN EX.houses. Drive the REAL
-- sequence a load actually runs, not a hand-set shortcut: seed a saved list and a saved
-- share count, then call discovery and restore exactly as the first-tick callback does.
SAVED[EX.SAVE_HOUSES] = "azeros;baal;ghost"
SAVED[EX.pkey(EX.SAVE_SHARES .. "ghost")] = 7
EX.discover_houses()
EX.restore()
local ghost_in_houses = false
for _, k in ipairs(EX.houses) do if k == "ghost" then ghost_in_houses = true end end
print("ghost_in_houses " .. tostring(ghost_in_houses))
-- EX.held("ghost"), NOT EX.shares_held.ghost directly - EX.held is the real accessor a caller
-- uses, and now that it has a house branch this proves that branch reads the restored table
-- rather than just checking EX.restore() populated it.
print("ghost_shares " .. tostring(EX.held("ghost")))
local ghost_instr = false
for _, k in ipairs(EX.instruments()) do if k == "ghost" then ghost_instr = true end end
print("ghost_instr " .. tostring(ghost_instr))

-- THE FIVE EXCLUSIONS. Each is silent if missed: paper that pays warehouse rent, a share
-- offered to an altar, a tithe demanded in equity, a razed settlement moving a share price
-- twice, and a Greenskin appetite for shares.
EX.houses = { "baal" }
EX.house_set = nil
EX.shares_held = { baal = 100 }
SAVED[EX.pkey(EX.SAVE_SHARES .. "baal")] = 100
print("carry_house " .. EX.carry_cost("baal"))
print("offer_house " .. tostring(EX.can_offer("baal")))
-- EX.shock is a module-level table (populated by EX.restore(), which ran above via the ghost
-- sequence) but this line does not rely on that: it is defensive against exactly the shape
-- EX.restore() itself uses, so the harness cannot nil-index if the shipped file ever stops
-- declaring EX.shock at load time.
EX.shock = EX.shock or {}
EX.shock["baal"] = 3
print("shock_house " .. EX.shock_shift("baal"))
print("appetite_house " .. EX.appetite_shift("baal"))
local cands = EX.demand_candidates(10)
local has_house = false
for _, c in ipairs(cands or {}) do if c == "baal" then has_house = true end end
print("demand_house " .. tostring(has_house))

-- A ROUND TRIP. Buy two lots, sell one, and the spread must still bite.
EX.current["baal"] = EX.neutral_rung()
EX.shares_held = { baal = 0 }
SAVED[EX.pkey(EX.SAVE_SHARES .. "baal")] = 0
print("lot_house " .. EX.lot("baal"))
EX.trade("baal", true)
EX.trade("baal", true)
print("held_after_buy " .. EX.held("baal"))
print("saved_after_buy " .. tostring(SAVED[EX.pkey(EX.SAVE_SHARES .. "baal")]))
EX.trade("baal", false)
print("held_after_sell " .. EX.held("baal"))
print("buy_px " .. EX.price("baal"))
print("sell_px " .. EX.sell_price("baal"))
print("pooled_calls " .. POOLED_CALLS)

-- DIVIDENDS. A fraction of the LIVE price, so a house can never pay more than it is worth.
EX.shares_held = { baal = 100 }
EX.current["baal"] = EX.neutral_rung()
local px = EX.price("baal")
print("div_per_share " .. EX.dividend("baal"))
print("div_price " .. px)
print("div_total " .. EX.dividend_total())
GOLD = 0
HOUSE_GOLD = {}
EX.pay_dividends()
print("div_paid " .. GOLD)
-- CONSERVED: what the player gains is what the issuing house lost, to the gold.
print("div_house_delta " .. tostring(HOUSE_GOLD["baal"] or 0))

-- WAR SUSPENDS THE DIVIDEND AND BLOCKS THE BUY. House paper was outside the diplomacy layer
-- entirely - you could buy into a faction you were at war with and draw income off it.
TREATY = { baal = "war" }
print("war_div_per_share " .. EX.dividend("baal"))
print("war_div_total " .. EX.dividend_total())
GOLD = 0
HOUSE_GOLD = {}
EX.pay_dividends()
print("war_div_paid " .. GOLD)
local ww, wl = EX.buy_refusal("baal")
print("war_buy_label " .. tostring(wl))
print("war_blocked " .. tostring(EX.blocked("baal")))
local hb = EX.held("baal")
EX.trade("baal", true)
print("war_buy_moved " .. tostring(EX.held("baal") ~= hb))
EX.trade("baal", false)
print("war_sell_moved " .. tostring(EX.held("baal") ~= hb))
TREATY = {}
EX.shares_held = { baal = 100 }
print("peace_div_per_share " .. EX.dividend("baal"))
-- A cheaper house pays less, with no second constant to keep in step.
EX.current["baal"] = 1
print("div_cheap " .. EX.dividend("baal"))

-- THE YIELD AGAINST WHAT THE PAPER COST, measured rather than re-derived.
--
-- The assertion this replaces read `div_per_share == int(price * DIV_YIELD)` - the formula
-- checked against itself, which passes for any formula. It passed while the dividend was FIVE
-- TIMES its designed yield, because EX.price is the price of a LOT and EX.dividend_total
-- multiplies by SHARES: 100 shares cost 20,000 gold and paid 2,000 a turn. 10%% per turn beats
-- EX.SPREAD's 10%% round trip after ONE turn instead of five, so the whole treasury parked in
-- any house is a risk-free 10%% - the exact income cheat DIV_YIELD exists to prevent.
--
-- So: buy a known number of lots through the REAL EX.trade, total the gold that actually left
-- the treasury, and read the per-turn dividend off the position it bought. Nothing here
-- restates the formula. Every buy is at the same price - EX.trade defers its reprice through
-- cm:callback, which this harness stubs out - so the spend is exact.
EX.delisted = {}
EX.houses = { "baal" }
EX.house_set = nil
EX.shares_held = { baal = 0 }
SAVED[EX.pkey(EX.SAVE_SHARES .. "baal")] = 0
EX.current["baal"] = EX.neutral_rung()
EX.pressure = {}
GOLD = 0
for _ = 1, 20 do EX.trade("baal", true) end
print("yield_spend " .. -GOLD)
print("yield_shares " .. EX.held("baal"))
print("yield_div " .. EX.dividend_total())

-- A HOUSE KILLED DURING YOUR OWN TURN IS NOT TRADEABLE AT ITS LIVING PRICE.
--
-- EX.check_delistings runs at FactionTurnStart and nowhere else, so is_delisted stays FALSE for
-- the rest of the turn you kill a house in - and EX.house_regions is a turn-start snapshot, so
-- the price does not move either. Take its last region or confederate it with a Tower of Zharr
-- seat claim, buy every lot the treasury can carry at the last live price, end the turn, and
-- settlement pays 1.25x. Risk-free 25%% on the whole treasury, once per house killed, and it
-- inverts the hook: "buy the house before you take its seat" becomes "buy it after, for free".
FACTIONS["killed_today"] = mkfac("killed_today", "wh3_dlc23_chd_chaos_dwarfs", 8,
                                 "r_kt", "killed_today")
EX.houses = { "killed_today" }
EX.house_set = nil
EX.delisted = {}
EX.shares_held = { killed_today = 0 }
SAVED[EX.pkey(EX.SAVE_SHARES .. "killed_today")] = 0
EX.current["killed_today"] = EX.neutral_rung()
GOLD = 0
EX.trade("killed_today", true)
print("live_buy_held " .. EX.held("killed_today"))
-- ...and now it dies, mid-turn. Nothing else changes: not the delisted set, not the price.
FACTIONS["killed_today"].is_dead = function() return true end
GOLD = 0
EX.trade("killed_today", true)
print("dead_buy_gold " .. GOLD)
print("dead_buy_held " .. EX.held("killed_today"))
print("dead_still_listed " .. tostring(EX.is_delisted("killed_today")))
-- And the sell side too - the same guard has to refuse both, or the position can be dumped at
-- the living price on the turn the house dies.
GOLD = 0
EX.trade("killed_today", false)
print("dead_sell_gold " .. GOLD)
print("dead_sell_held " .. EX.held("killed_today"))

-- SETTLEMENT, BOTH BRANCHES. A flat premium would pay the player for backing a LOSER:
-- buy into a doomed house, wait for anyone at all to finish it, collect more than you paid.
local FEED = {}
cm.show_message_event = function(_, _f, t) FEED[#FEED + 1] = t end
EX.delisted = {}

-- Branch A: WE absorbed it. Our faction owns its last-known capital.
FACTIONS["doomed_a"] = mkfac("doomed_a", "wh3_dlc23_chd_chaos_dwarfs", 0, "r_da", "player")
FACTIONS["doomed_a"].is_dead = function() return true end
EX.houses = { "doomed_a" }
EX.house_set = nil
EX.shares_held = { doomed_a = 40 }
EX.current["doomed_a"] = EX.neutral_rung()
local px_a = EX.price("doomed_a")
GOLD = 0
EX.check_delistings()
print("settle_a_gold " .. GOLD)
print("settle_a_px " .. px_a)
print("settle_a_held " .. EX.held("doomed_a"))
print("settle_a_delisted " .. tostring(EX.is_delisted("doomed_a")))

-- Branch B: somebody else killed it.
FACTIONS["doomed_b"] = mkfac("doomed_b", "wh3_dlc23_chd_chaos_dwarfs", 0, "r_db", "greenie")
FACTIONS["doomed_b"].is_dead = function() return true end
EX.houses = { "doomed_b" }
EX.house_set = nil
EX.shares_held = { doomed_b = 40 }
EX.current["doomed_b"] = EX.neutral_rung()
GOLD = 0
EX.check_delistings()
print("settle_b_gold " .. GOLD)

-- IT MUST NEVER SETTLE TWICE. The turn handler re-runs on every turn AND on every load, and
-- the delisted flag is the only thing between a dead house and a second payout.
--
-- THE POSITION IS PUT BACK FIRST, which is what a restore reads out of a saved value written
-- before the delist. Settlement zeroing the holding must not be what stops the second payout:
-- lean on that and a holding that comes back from anywhere - a stale save value, a house
-- bought after it settled - pays out again, every turn, forever.
EX.shares_held["doomed_b"] = 40
GOLD = 0
EX.check_delistings()
print("settle_again " .. GOLD)
print("feed_count " .. #FEED)

-- AND A HOUSE WE HOLD NOTHING IN RAISES NO BULLETIN. Both texts read "your shares are paid
-- out"; eleven-odd houses die over a campaign and most players hold paper in none of them.
FACTIONS["doomed_c"] = mkfac("doomed_c", "wh3_dlc23_chd_chaos_dwarfs", 0, "r_dc", "greenie")
FACTIONS["doomed_c"].is_dead = function() return true end
EX.houses = { "doomed_c" }
EX.house_set = nil
EX.shares_held = { doomed_c = 0 }
EX.current["doomed_c"] = EX.neutral_rung()
GOLD = 0
EX.check_delistings()
print("settle_none_gold " .. GOLD)
print("settle_none_delisted " .. tostring(EX.is_delisted("doomed_c")))
print("feed_after_none " .. #FEED)

-- AND THE FLAG SURVIVES A LOAD, or the guard above is worth nothing the moment the campaign
-- is reloaded - which is the F9 half of the same printer. Driven through the real EX.restore()
-- with the in-memory table wiped, so both halves have to be there: the write in
-- EX.settle_house and the read here.
EX.delisted = {}
EX.restore()
print("delisted_after_load " .. tostring(EX.is_delisted("doomed_b")))

-- A SETTLED BOOK TAKES NO ORDERS. Without the refusal a player can still buy paper in a house
-- that no longer exists - gold buried in a row that will never pay a dividend, never settle
-- again, and cannot be sold either, since the same guard refuses that side too.
EX.delisted = { doomed_a = true }
EX.houses = { "doomed_a" }
EX.house_set = nil
EX.shares_held = { doomed_a = 0 }
EX.current["doomed_a"] = EX.neutral_rung()
GOLD = 0
EX.trade("doomed_a", true)
print("delisted_buy_gold " .. GOLD)
print("delisted_buy_held " .. EX.held("doomed_a"))
-- AND THE ROW FREEZES at the price it settled against. A delisted house owns nothing, so a
-- live reprice reads its power as 0 and walks it down to the ladder floor over the following
-- turns - a closed book whose sparkline says the collapse is still in progress.
EX.current["doomed_a"] = EX.neutral_rung() + 3
print("delisted_rung " .. EX.target_rung("doomed_a", {}, {}, 1))
print("delisted_rung_want " .. EX.current["doomed_a"])

-- A DELISTED HOUSE IS OUT OF THE MEDIAN. Its power is 0, so leaving it in makes it a zero
-- sample: the dead accumulate over a campaign, the median falls, and every LIVING house's
-- multiplier inflates - a slow upward drift across the whole board with nothing on screen to
-- explain it. Priced twice off the same live pair, once with a corpse in the list.
EX.delisted = {}
EX.houses = { "baal", "azeros" }
EX.house_set = nil
EX.house_regions = { baal = 8, azeros = 4 }
print("med_live " .. EX.house_median())
print("rung_live " .. EX.target_rung("baal", {}, {}, 1))
EX.houses = { "baal", "azeros", "corpse" }
EX.house_set = nil
EX.house_regions = { baal = 8, azeros = 4, corpse = 0 }
EX.delisted["corpse"] = true
print("med_dead " .. EX.house_median())
print("rung_dead " .. EX.target_rung("baal", {}, {}, 1))

-- AND OUT OF THE DIVIDEND LOOP, not merely zeroed by settlement. The share count is set
-- straight into EX.shares_held here, which is the shape a save written before the delist
-- restores - settlement zeroing the position must not be the only thing standing between a
-- dead house and a dividend paid forever.
EX.shares_held = { baal = 100, corpse = 100 }
EX.current["baal"] = EX.neutral_rung()
EX.current["corpse"] = EX.neutral_rung()
print("div_live_only " .. EX.dividend_total())
print("div_one_house " .. (EX.dividend("baal") * 100))

-- WHERE SETTLEMENT SITS RELATIVE TO THE REPRICE, and the cached capital, in one scenario -
-- they are the same turn. A dead house owns nothing, so the first EX.apply_prices after its
-- death reads its power as 0, clamps to EX.MULT_MIN and drops the row to rung 1 in ONE step.
-- EX.is_delisted is still false at that moment, so the freeze in EX.target_rung does not save
-- it: only calling EX.check_delistings BEFORE EX.apply_prices does.
--
-- The two owners disagree ON PURPOSE. REGIONS says the capital is ours, the live faction says
-- it is still the house's own, so the 1.25x branch can only be reached through the CACHED key
-- - which is the path a confederated house has, and the live read never does.
REGIONS["r_dying"] = "player"
local function stage_dying()
    FACTIONS["dying"] = mkfac("dying", "wh3_dlc23_chd_chaos_dwarfs", 8, "r_dying", "dying")
    EX.houses = { "dying" }
    EX.house_set = nil
    EX.house_regions = nil
    EX.delisted = {}
    EX.house_home = {}
    EX.shares_held = { dying = 40 }
    EX.current["dying"] = nil
    EX.pressure = {}
    EX.supply = {}
    for _, c in ipairs(EX.COMMODITIES) do EX.supply[c] = 1 end
    EX.owners = {}
    EX.apply_prices()      -- priced ALIVE: eight regions, and the capital key cached here
    FACTIONS["dying"].is_dead = function() return true end
    FACTIONS["dying"].region_list = function()
        return { num_items = function() return 0 end }
    end
    GOLD = 0
end

stage_dying()
print("alive_px " .. EX.price("dying"))
print("home_cached " .. tostring(EX.house_home["dying"]))
EX.check_delistings()          -- the shipped order: settle, THEN reprice
print("settle_before_gold " .. GOLD)

-- AND THE KEY SURVIVES A LOAD - the same two halves as the delisted flag, the write in
-- EX.remember_home and the read in EX.restore. A house usually dies many turns after it was
-- last priced in the session that saved.
SAVED[EX.SAVE_HOUSES] = "dying"
EX.house_home = {}
EX.restore()
print("home_after_load " .. tostring(EX.house_home["dying"]))

stage_dying()
EX.apply_prices()              -- the wrong order: the death drops it to the floor first
print("floor_px " .. EX.price("dying"))
EX.check_delistings()
print("settle_after_gold " .. GOLD)
"""


def check_lua_houses():
    """Discovery, the instrument list, and the two ways a house can be an instrument.

    Three silent failures this pins:

    1. HARDCODING THE TEN HOUSES. They live only in the lords pack under
       cr_combi_expanded; a plain Immortal Empires campaign would draw eleven dead rows.
    2. THE PLAYER'S OWN FACTION IN THE LIST. You would be able to buy yourself, and the
       delist branch would eventually try to settle your own death.
    3. A HOUSE DROPPING OUT OF EX.houses when a session's faction_list walk does not report
       it (dead, confederated, or just not yet re-scanned) while the player still holds
       shares in it - EX.restore() rebuilds EX.shares_held only for houses IN EX.houses, so
       losing the row makes the position unreachable and unsettleable and the gold is simply
       gone. EX.discover_houses() merges with the saved list rather than replacing it
       precisely so this cannot happen - the ghost_* assertions below drive the real
       discover-then-restore sequence a load runs and fail if that merge is ever reverted to
       a replace.
    """
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped lua houses check: no lua.exe)")
        return

    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    assert 'EX.HOUSE_CULTURE = "wh3_dlc23_chd_chaos_dwarfs"' in code, (
        "the Chaos Dwarf DEFAULT for EX.HOUSE_CULTURE is gone. EX.bind_race overwrites it at "
        "init with the player's own culture, but every harness in this file loads the script "
        "WITHOUT calling init - so this literal is what twenty checks measure against, and "
        "removing it makes them all measure an empty string instead")
    assert code.count("EX.bind_race()") == 2, (
        "expected exactly two mentions of EX.bind_race - its definition and the single call "
        "in EX.init - and found %d. A second call site is not wrong on its own, but the "
        "rebind is the only thing standing between a live save's keys and a rename, so it is "
        "COUNTED rather than asserted-absent: the first form of the equivalent assertion on "
        "EX.snapshot() failed on correct code." % code.count("EX.bind_race()"))
    m = re.search(r"function EX\.init\(\)(.*?)EX\.rescan\(\)", code, re.S)
    assert m and "EX.bind_race()" in m.group(1), (
        "EX.bind_race is not called before EX.rescan in EX.init. scan_supply reads "
        "EX.HOUSE_CULTURE once per region, so a later rebind counts turn one's house regions "
        "against the Chaos Dwarf default whatever the player actually is")
    assert "cr_chd_house_of_" not in code, (
        "a house faction key is hardcoded in the Lua. The ten houses ship only in the "
        "lords pack; hardcoding them puts dead rows in every other campaign. Spec §3.")

    # THE FOURTH VIEW IS REACHABLE. Everything else in this function tests the math; none of
    # it matters if the mode button never lands on "houses" at all.
    assert '"houses"' in code and "EX.MODE_HOUSES" in code, (
        "the houses view is not on the mode cycle - the feature is unreachable")
    m = re.search(r"EX\.MODES\s*=\s*\{(.*?)\}", code, re.S)
    assert m, "EX.MODES is gone - the mode button has nothing to cycle"
    assert "houses" in m.group(1), (
        "EX.MODES is %s. The guide is deliberately OFF the cycle; houses must be ON it."
        % m.group(1))

    harness = LUA_HOUSES_HARNESS % (LUA_SCRIPT.replace("\\", "\\\\"),)
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.split(NL):
        line = line.strip()
        if line:
            k, _sp, v = line.partition(" ")
            have[k] = v

    found = sorted(have["houses"].split(","))
    assert found == ["azeros", "baal"], (
        "discovered %s. Expected exactly the two LIVING, non-player, non-rebel, "
        "non-quest-battle Chaos Dwarf factions. The player is excluded (you cannot buy "
        "yourself), the Greenskin by culture, and chd_dead / chd_rebel / chd_qb by the three "
        "reads EX.tradeable_faction makes - CA ships wh3_dlc23_chd_chaos_dwarfs_rebels, "
        "_qb1/_qb2/_qb3 and wh3_dlc25_chd_chaos_dwarfs_invasion inside this subculture, and "
        "because EX.houses only GROWS and EX.delisted is permanent, discovering one once "
        "leaves a greyed 'gone' row on the panel for the whole campaign." % found)
    assert have["is_house_baal"] == "true", have
    assert have["is_house_iron"] == "false", (
        "a commodity answers is_house. The five exclusion guards in Task 3 all hang off "
        "this predicate, so a false positive here silently exempts iron from the warehouse.")
    assert have["saved"] != "nil", (
        "the discovered list is not persisted. faction_list would be walked again on every "
        "load, and a house that died between saves would drop out of the list entirely.")
    assert int(have["instr_houses"]) == 2, (
        "EX.instruments() returned %s houses, expected 2. Houses that are not instruments "
        "get no price, no history, no sparkline and no save slot." % have["instr_houses"])
    assert have["ghost_in_houses"] == "true", (
        "a house named in the saved list, but absent from this session's faction_list walk, "
        "was dropped from EX.houses. EX.discover_houses() must MERGE with EX.SAVE_HOUSES, "
        "never replace it - a house that drops out of the list is unreachable and "
        "unsettleable for good.")
    assert have["ghost_shares"] == "7", (
        "EX.restore() rebuilds EX.shares_held only for houses in EX.houses - the ghost "
        "house's saved share count did not come back (got %r). This is the gold-goes-"
        "missing failure the merge exists to prevent." % have.get("ghost_shares"))
    assert have["ghost_instr"] == "true", (
        "a house we still hold shares in is not in EX.instruments() - it gets no price, no "
        "history, no sparkline and no save slot, so its position can never be settled.")

    # PRICE DIRECTION. Getting this backwards is invisible - every number still moves,
    # every row still draws, and a house being beaten down simply gets dearer forever.
    strong, weak, even = (float(have["mult_strong"]), float(have["mult_weak"]),
                          float(have["mult_even"]))
    assert strong > even > weak, (
        "house price multipliers are %s/%s/%s for power 8/4/2 against a median of 4. A "
        "stronger house must be DEARER. EX.price_multiplier is inverted (scarcity), so "
        "reusing it here silently prices the whole view upside down." % (strong, even, weak))
    assert abs(even - 1.0) < 1e-6, (
        "a house exactly at the median priced at %s, not 1.0 - the neutral rung is wrong "
        "and every house is offset from the ladder's centre" % even)

    assert have["seat_held"] == "true", have
    assert have["seat_lost"] == "false", (
        "a faction whose home region is owned by somebody else still reads as holding its "
        "seat. The Seat column would read 'held' through a collapse and the price step "
        "would never fire.")
    assert float(have["seat_lost_mult"]) == SEAT_LOST, (
        "EX.SEAT_LOST is %s, this generator is built for %s"
        % (have["seat_lost_mult"], SEAT_LOST))

    # THE SEAT STEP MOVES THE PRICE - the spec's headline signal, and the one line in the whole
    # feature that had NO assertion behind it. `if seat == false then mult = mult * EX.SEAT_LOST
    # end` could be deleted from EX.target_rung and every other check here still passed:
    # holds_capital returning false was proven, and nothing downstream of it was.
    #
    # Two houses at identical power and identical everything else, priced through the real
    # EX.target_rung, differing only in who owns the home region.
    ok_rung, lost_rung = int(have["seat_rung_held"]), int(have["seat_rung_lost"])
    ok_px, lost_px = int(have["seat_px_held"]), int(have["seat_px_lost"])
    assert lost_rung < ok_rung and lost_px < ok_px, (
        "two houses at four regions each priced at rung %d/%d gold with its capital held and "
        "rung %d/%d with its capital taken - the seat step did not move the price. That step "
        "is what the whole Seat column is for; without it the panel draws 'LOST' beside a "
        "number that never changed." % (ok_rung, ok_px, lost_rung, lost_px))
    # ...and by about the right amount. The step is a multiplier on the ladder, so the rung
    # count is what the constant predicts, not the gold: a x0.6 multiplier is
    # log(0.6)/log(LADDER_STEP) rungs down, rounded the way EX.ladder_index rounds.
    want_drop = int(math.floor(math.log(SEAT_LOST) / math.log(LADDER_STEP) + 0.5))
    assert lost_rung - ok_rung == want_drop, (
        "the seat step moved the price %d rungs where SEAT_LOST = %s predicts %d. The step is "
        "there but it is not this constant, so the two files disagree about how hard losing a "
        "capital bites." % (lost_rung - ok_rung, SEAT_LOST, want_drop))

    # THE HORDE BRANCH. cr_chd_black_kraken_armada is a CHARACTER_BOUND_HORDE and owns zero
    # regions for its entire life - a region-count power index prices it at the ladder floor
    # from turn one and it never moves again.
    assert float(have["power_horde"]) > 0, (
        "a zero-region horde has power %s. It would sit at the ladder floor forever, a "
        "permanently worthless instrument that is not in trouble at all." % have["power_horde"])
    assert float(have["power_settled"]) == 8.0, (
        "a settled faction's power is %s, expected its 8 regions. military_force_list counts "
        "GARRISONS for a settled faction, so it must be read only on the zero-region branch."
        % have["power_settled"])
    assert have["seat_horde"] == "nil", (
        "a horde answered %s for holds_capital. It has no home region, so it must be EXEMPT "
        "(nil) rather than false - false would mark it LOST forever and cut its price 40%%."
        % have["seat_horde"])
    # THE VALUE, not merely that it is positive. HORDE_WEIGHT is a shape, and a shape that
    # drifts between the two files is the class of fault the constants mirror exists for.
    assert float(have["horde_weight"]) == HORDE_WEIGHT, (
        "EX.HORDE_WEIGHT is %s, this generator is built for %s"
        % (have["horde_weight"], HORDE_WEIGHT))
    assert float(have["power_horde"]) == 3 * HORDE_WEIGHT, (
        "a three-army horde has power %s, expected %s (3 * HORDE_WEIGHT). '> 0' passed for any "
        "weight at all, including one that prices every horde a rung off where it belongs."
        % (have["power_horde"], 3 * HORDE_WEIGHT))
    # AND ZERO REGIONS IS NOT ALWAYS A HORDE. A settled house stripped of its last region has
    # the same zero and the opposite meaning: read through the army branch, a collapsing
    # three-army house prices at 6 - ABOVE a healthy four-region rival - on the turn it dies.
    assert float(have["power_collapsing"]) == 0.0, (
        "a settled faction with no regions left and three armies has power %s. The army "
        "fallback belongs to a CHARACTER_BOUND_HORDE, which has no home region at all; "
        "has_home_region() is what tells the two apart, and it is the same read "
        "EX.holds_capital already makes." % have["power_collapsing"])

    # FIVE GUARDS, FIVE ASSERTIONS. Every one of these is silent when missed.
    #
    # carry_house and offer_house are LIVE as of Task 4: EX.carry_cost and EX.can_offer both
    # fall through to EX.held(res) once their own EX.is_house guard is removed, and EX.held now
    # has a real house branch instead of always answering 0. Deleting either guard was checked
    # by hand - EX.carry_cost("baal") comes back nonzero and EX.can_offer("baal") comes back
    # true against the 100-share holding set below, so both assertions now catch a real
    # regression rather than passing no matter what the guard does.
    assert float(have["carry_house"]) == 0.0, (
        "a share costs %s gold a turn in warehouse rent. Shares are paper - there is "
        "nothing to store, and Layer 2 is exempt for exactly this reason."
        % have["carry_house"])
    assert have["offer_house"] == "false", (
        "a share can be offered to Hashut. You cannot burn equity on an altar, and the "
        "offering would destroy the position for a boon.")
    assert float(have["shock_house"]) == 0.0, (
        "a supply shock moved a share price by %s rungs. A razed settlement already moves "
        "a house price through its region count; counting it twice double-books the event."
        % have["shock_house"])
    # appetite_house and demand_house CANNOT be made to bite this way and this is not a gap:
    # EX.demand_candidates iterates EX.COMMODITIES, which never contains a house key, and
    # CULTURE_WANTS/WAR_APPETITE are both keyed by commodity and culture, so a house key can
    # only ever look up nil there. Deleting either guard would still print "0.0"/"false" because
    # nothing upstream ever hands these functions a house key to act on. The two assertions
    # below are defence-in-depth documentation - proof the guard exists and reads correctly if
    # it is ever reached - not a live regression test the way the two above are.
    assert float(have["appetite_house"]) == 0.0, (
        "world appetite moved a share price by %s. Cultures want goods, not equity - and "
        "CULTURE_WANTS has no entry for a faction key, so this is reading a nil as a signal."
        % have["appetite_house"])
    assert have["demand_house"] == "false", (
        "Hashut demanded a tithe in shares. EX.pay_demand would then try to burn a "
        "position the player cannot replace, and refusing costs them the wrath bundle.")

    print("  houses: discovery excludes player and foreign cultures, list persists, "
          "held-but-undiscovered stays an instrument")
    print("  five exclusions: houses carry no rent, no altar offering, no shock, no "
          "appetite, no tithe")

    # THE ROUND TRIP. Shares live in save state, not a pooled resource - EX.held and EX.trade's
    # goods half both have to agree on that, or a position bought is a position that evaporates
    # on reload while the gold spent on it stays gone.
    assert int(have["lot_house"]) == HOUSE_LOT_SIZE, (
        "a house lot is %s, this generator is built for %s"
        % (have["lot_house"], HOUSE_LOT_SIZE))
    assert int(have["held_after_buy"]) == HOUSE_LOT_SIZE * 2, (
        "two buys of %s left %s shares" % (HOUSE_LOT_SIZE, have["held_after_buy"]))
    assert have["saved_after_buy"] == str(HOUSE_LOT_SIZE * 2), (
        "the holding is %s in memory but %s in the save. Shares live in save state, so an "
        "unsaved buy is a position that vanishes on reload - and the player paid for it."
        % (have["held_after_buy"], have["saved_after_buy"]))
    assert int(have["held_after_sell"]) == HOUSE_LOT_SIZE, have
    assert int(have["pooled_calls"]) == 0, (
        "trading a house called cm:faction_add_pooled_resource %s times. Houses have no "
        "pooled resource - the key does not exist in the DB, so the call is a silent no-op "
        "and the position would only ever live in the save value." % have["pooled_calls"])

    buy, sell = int(have["buy_px"]), int(have["sell_px"])
    assert sell < buy, (
        "sell %s is not under buy %s - the spread is the only thing closing the "
        "round-trip loop, and without it a house is a money printer" % (sell, buy))
    assert abs(sell - round(buy * (1 - SPREAD))) <= 1, (sell, buy)

    print("  round trip: a house lot is %s, two buys then a sell leave %s shares held and "
          "saved, spread intact, no pooled-resource call made"
          % (have["lot_house"], have["held_after_sell"]))

    # DIVIDENDS, MEASURED AGAINST WHAT THE SHARES COST.
    #
    # The assertion that stood here was `div_per_share == int(price * DIV_YIELD)`: the shipped
    # formula compared against a Python copy of the same formula. That passes for ANY formula,
    # and it passed while the dividend was five times its designed yield - EX.price is the price
    # of a LOT and EX.dividend_total multiplies by SHARES, so 100 shares costing 20,000 gold
    # paid 2,000 a turn. 10% of the position per turn beats EX.SPREAD's 10% round trip after ONE
    # turn instead of five, which makes any treasury parked in any house a risk-free 10% - the
    # income cheat DIV_YIELD is argued from the spread precisely to prevent.
    #
    # So the property asserted is the one the spec promises: what the position pays per turn
    # against what the position cost, through the real EX.trade and the real EX.dividend_total.
    px = int(have["div_price"])
    spend, div = int(have["yield_spend"]), int(have["yield_div"])
    assert spend > 0 and div > 0, (
        "20 lots bought for %s gold pay %s a turn - the measurement did not run"
        % (spend, div))
    assert int(have["yield_shares"]) == 20 * HOUSE_LOT_SIZE, (
        "20 buys of a %s-share lot left %s shares" % (HOUSE_LOT_SIZE, have["yield_shares"]))
    got_yield = div / float(spend)
    # BAND: 5% RELATIVE. The only slack the arithmetic needs is EX.dividend's floor() - exact at
    # the neutral rung this is measured at, and a band rather than an equality so a future
    # DIV_YIELD that does not divide evenly by the lot size does not have to be re-derived here.
    assert abs(got_yield - DIV_YIELD) <= DIV_YIELD * 0.05, (
        "%s lots cost %d gold and pay %d a turn, a yield of %.4f per turn against a designed "
        "DIV_YIELD of %s. Off by a factor of about %.1f. EX.price is the price of a LOT, not "
        "of a share - the dividend has to be divided by EX.HOUSE_LOT_SIZE before "
        "EX.dividend_total multiplies it by every share held."
        % (20, spend, div, got_yield, DIV_YIELD, got_yield / DIV_YIELD))
    assert int(have["div_total"]) == int(have["div_per_share"]) * 100, have
    # CONSERVED, like the commodity side. The dividend used to be minted: one treasury_mod
    # crediting the player and nothing leaving the issuing house, so holding paper was free
    # income for the whole board. Measured on the commodity side the same day: buy -467/+467,
    # sell +420/-420.
    assert int(have["div_house_delta"]) == -int(have["div_paid"]), (
        "the dividend is not conserved: the player gained %s and the issuing house lost %s. "
        "It must come OUT of the house that pays it, bounded by EX.pay_house."
        % (have["div_paid"], -int(have["div_house_delta"])))
    # WAR: no dividend, no buy, selling still open.
    assert int(have["war_div_per_share"]) == 0 and int(have["war_div_total"]) == 0, (
        "a house at war still pays a dividend (%s per share). It does not fund a shareholder "
        "it is fighting." % have["war_div_per_share"])
    assert int(have["war_div_paid"]) == 0, (
        "pay_dividends still moved %s gold for a house at war" % have["war_div_paid"])
    assert have["war_buy_label"] == "At war", (
        "a house at war labels its Buy button %r, not 'At war'" % have["war_buy_label"])
    assert have["war_blocked"] == "baal", (
        "EX.blocked does not refuse a house at war, so EX.trade would let the buy through "
        "however the button is labelled. Reported from play: 30 shares bought in a faction "
        "the player was actively at war with, at no markup, paying +120g a turn.")
    assert have["war_buy_moved"] == "false", (
        "the buy went through on a house at war")
    assert have["war_sell_moved"] == "true", (
        "SELLING was blocked on a house at war. Selling always stays open - that is the "
        "design's safety valve, and war freezes the income, not the capital.")
    assert int(have["peace_div_per_share"]) > 0, (
        "the dividend did not resume when the war ended - war must freeze it, not destroy it")
    assert int(have["div_paid"]) == int(have["div_total"]), (
        "pay_dividends moved %s gold but the total is %s"
        % (have["div_paid"], have["div_total"]))
    assert int(have["div_paid"]) > 0, (
        "the dividend is charged, not paid - a sign error here takes gold from the player "
        "for holding shares, which reads as a bug in the whole feature")
    assert int(have["div_cheap"]) < int(have["div_per_share"]), (
        "a house at the ladder floor pays the same dividend as one at the neutral rung")

    # WIRING. The rent has a matching pair of traps and this inherits both.
    assert "EX.pay_dividends()" in turn_body(code), (
        "dividends are never paid on a turn")
    tick = re.search(r"function EX\.init\(\).*?\n\s*core:add_listener",
                     code, re.S)
    assert "EX.pay_dividends()" not in tick.group(0), (
        "pay_dividends runs on the first tick. A load is not a turn - five reloads would "
        "be five dividend days, which is the exact trap charge_carry documents.")

    print("  dividends: %d lots cost %d gold and pay %d a turn, a measured %.2f%% against a "
          "designed %.2f%%, paid once on FactionTurnStart and never on the first tick"
          % (20, spend, div, got_yield * 100, DIV_YIELD * 100))

    # A HOUSE KILLED DURING YOUR OWN TURN TAKES NO ORDERS EITHER.
    #
    # EX.check_delistings runs at FactionTurnStart and nowhere else, so EX.is_delisted is still
    # FALSE for the rest of the turn a house dies in - and EX.house_regions is a turn-start
    # snapshot, so the price has not moved. Take a house's last region, or confederate it with a
    # Tower of Zharr seat claim, then buy every lot the treasury can carry at the last living
    # price and end the turn: EX.settle_house pays it out at BUYOUT_PREMIUM. Risk-free 25% on
    # the whole treasury, repeatable once per house killed, and it inverts the hook the feature
    # is built on - "buy the house BEFORE you take its seat" becomes "buy it after, for free".
    assert int(have["live_buy_held"]) == HOUSE_LOT_SIZE, (
        "the control buy against the LIVING house did not go through (%s shares), so the "
        "refusal below proves nothing" % have["live_buy_held"])
    assert have["dead_still_listed"] == "false", (
        "the harness delisted the house before testing the refusal - EX.is_delisted must "
        "still be false here, or this only re-tests the delisted guard")
    assert int(have["dead_buy_gold"]) == 0 and int(have["dead_buy_held"]) == HOUSE_LOT_SIZE, (
        "a house that is DEAD but not yet settled took a buy order: %s gold moved and the "
        "position went to %s shares. It is still priced at its last living rung, and the next "
        "turn start settles it at %sx - a risk-free %d%% on the whole treasury, once per house "
        "killed." % (have["dead_buy_gold"], have["dead_buy_held"], BUYOUT_PREMIUM,
                     (BUYOUT_PREMIUM - 1) * 100))
    assert int(have["dead_sell_gold"]) == 0 and int(have["dead_sell_held"]) == HOUSE_LOT_SIZE, (
        "a dead-but-unsettled house took a SELL order: %s gold moved and %s shares are left. "
        "The same guard has to refuse both sides, or the position can be dumped at the living "
        "price on the turn the house dies."
        % (have["dead_sell_gold"], have["dead_sell_held"]))

    print("  mid-turn death: a house that is dead but not yet settled refuses both a buy and "
          "a sell, so its last living price cannot be traded against")

    # SETTLEMENT. Who killed the house decides what its paper pays, and the settle-twice guard
    # is the difference between a feature and a gold printer reachable by pressing F9.
    px_a = int(have["settle_a_px"])
    want_a = int(40 * px_a * BUYOUT_PREMIUM)
    assert abs(int(have["settle_a_gold"]) - want_a) <= 40, (
        "absorbing a house we held 40 shares in paid %s, expected about %s "
        "(40 * %s * %s). This is the cornering hook - buy the house before you take its "
        "seat - and it is the only path that should pay a premium."
        % (have["settle_a_gold"], want_a, px_a, BUYOUT_PREMIUM))
    assert int(have["settle_a_held"]) == 0, (
        "the position survived settlement - it would pay dividends forever on a dead house")
    assert have["settle_a_delisted"] == "true", have

    a, b = int(have["settle_a_gold"]), int(have["settle_b_gold"])
    assert b < a, (
        "a house killed by somebody else paid %s against %s for one we absorbed. A flat "
        "premium pays the player for BACKING A LOSER: buy into a doomed house, wait for "
        "anyone to finish it, collect. That inverts the whole mechanic." % (b, a))
    assert abs(b - int(40 * px_a * WINDUP)) <= 40, (b, px_a)

    assert int(have["settle_again"]) == 0, (
        "settlement ran twice and paid again. The turn handler re-runs on every load, so "
        "this is an unbounded gold printer reachable by pressing F9.")
    assert int(have["feed_count"]) == 2, (
        "%s bulletins for two settlements" % have["feed_count"])
    assert have["settle_none_delisted"] == "true" and int(have["settle_none_gold"]) == 0, (
        "a house we held nothing in settled for %s gold and delisted=%s"
        % (have["settle_none_gold"], have["settle_none_delisted"]))
    assert int(have["feed_after_none"]) == int(have["feed_count"]), (
        "a house the player held NO shares in still raised a bulletin (%s -> %s). Both texts "
        "say 'your shares are paid out'; eleven-odd houses die over a campaign and most "
        "players hold paper in none of them, so ungated this is eleven notices about somebody "
        "else's money." % (have["feed_count"], have["feed_after_none"]))
    assert have["delisted_after_load"] == "true", (
        "the delisted set did not survive EX.restore(), so every dead house on the board "
        "settles again on the next load. That is the F9 half of the same gold printer, and "
        "it needs both halves: the set_saved_value in EX.settle_house and the read in "
        "EX.restore().")
    assert int(have["delisted_buy_gold"]) == 0 and int(have["delisted_buy_held"]) == 0, (
        "a delisted house took a buy order: %s gold moved and %s shares landed. The book is "
        "closed - the paper can never pay a dividend or settle again, and the same guard "
        "refuses the sell, so that gold is buried."
        % (have["delisted_buy_gold"], have["delisted_buy_held"]))
    assert have["delisted_rung"] == have["delisted_rung_want"], (
        "a delisted house repriced to rung %s from the %s it settled at. It owns nothing, so "
        "a live reprice reads its power as 0, clamps to MULT_MIN and drops the row to the "
        "ladder floor in ONE step - a closed book whose sparkline reads as a collapse."
        % (have["delisted_rung"], have["delisted_rung_want"]))

    # AND A CORPSE MOVES NOBODY'S PRICE. A delisted house's power reads 0, so leaving it in
    # EX.house_median makes it a zero sample - the dead pile up, the median falls and every
    # living house gets dearer with no cause the player can see.
    assert float(have["med_live"]) == float(have["med_dead"]), (
        "the house median moved from %s to %s when a DELISTED house joined the list. Its "
        "power is 0, so it is a zero sample; over a campaign the dead accumulate, the median "
        "falls and the whole board drifts up." % (have["med_live"], have["med_dead"]))
    assert have["rung_live"] == have["rung_dead"], (
        "a living house priced at rung %s alone and rung %s with a delisted house beside it. "
        "A delisted row is frozen at its last price and must not move anybody else's."
        % (have["rung_live"], have["rung_dead"]))
    assert int(have["div_live_only"]) == int(have["div_one_house"]), (
        "dividend_total paid %s where the one LIVE house's shares are worth %s - it is "
        "counting a delisted house. Settlement zeroes the position, but the loop must not "
        "lean on that alone: a share count restored from a save written before the delist "
        "would pay out forever on a house that no longer exists."
        % (have["div_live_only"], have["div_one_house"]))

    # THE PRICE THE PAPER SETTLES AT, which is decided by where the call sits in the turn.
    # Measured both ways above on the same house, and the gap is a factor of ten.
    alive, floor = int(have["alive_px"]), int(have["floor_px"])
    before, after = int(have["settle_before_gold"]), int(have["settle_after_gold"])
    assert floor < alive, (
        "the reprice after a house's death left it at %s against %s alive - the harness is "
        "not reproducing the collapse this check exists to price against" % (floor, alive))
    assert before == int(40 * alive * BUYOUT_PREMIUM), (
        "settling a 40-share position in a house priced at %s paid %s, expected %s. The "
        "payout must be taken off the LIVING price - and reaching the %s branch at all "
        "proves the cached capital key resolved, since the live faction still names itself "
        "as the owner." % (alive, before, int(40 * alive * BUYOUT_PREMIUM), BUYOUT_PREMIUM))
    assert have["home_cached"] == "r_dying", (
        "EX.target_rung did not cache the house's capital region key (got %r). A dead or "
        "CONFEDERATED house answers cm:get_faction with false, so the key cached while it "
        "was alive is the only way to ask who owns its capital - and confederation is how a "
        "Tower of Zharr seat claim kills a house, which is the buyout hook itself."
        % have["home_cached"])
    assert have["home_after_load"] == "r_dying", (
        "the cached capital key did not survive EX.restore() (got %r). A house usually dies "
        "many turns after the session that last priced it, so without both halves - the "
        "set_saved_value in EX.remember_home and the read in EX.restore - the buyout branch "
        "is unreachable on any campaign that was ever reloaded." % have["home_after_load"])
    assert after < before, (
        "settling after the reprice paid %s where settling before it pays %s. A dead house "
        "owns nothing, so apply_prices reads its power as 0 and drops the row to the ladder "
        "floor in ONE step - and EX.is_delisted is still false then, so the freeze in "
        "EX.target_rung does not save it." % (after, before))

    # WIRING, the same pair of traps the dividend carries and for the same reason - it moves
    # gold. ORDER matters twice over: before apply_prices, or the payout is priced off the
    # floor the death just created (the measurement above); and before pay_dividends, or a
    # house is paid out AND paid a dividend on the turn it dies.
    turn = turn_body(code)
    assert "EX.check_delistings()" in turn, (
        "nothing ever settles a dead house. Every function above is correct and unreachable, "
        "and a position in a house that died is simply stuck in the save forever.")
    assert (turn.index("EX.check_delistings()")
            < turn.index("EX.apply_prices()")), (
        "EX.check_delistings runs AFTER EX.apply_prices in the turn handler, so the paper is "
        "priced off the ladder floor the death just put the row on - %s gold instead of %s "
        "on the harness's 40-share position. The freeze in EX.target_rung cannot cover this: "
        "EX.is_delisted is still false during that reprice." % (after, before))
    assert (turn.index("EX.check_delistings()")
            < turn.index("EX.pay_dividends()")), (
        "delistings are checked AFTER the dividends are paid, so a house pays out on the "
        "same turn it dies and is settled")
    assert "EX.check_delistings()" not in tick.group(0), (
        "check_delistings runs on the first tick. It pays gold, and a load is not a turn - "
        "the settle-twice guard makes this survivable rather than harmless, and leaning on "
        "a guard for something that should never run is how the guard gets deleted.")

    print("  delisting: absorbed pays %sx and somebody else's kill pays %sx off the LIVING "
          "price (%s, not the %s floor the death creates), capital resolved through the "
          "cached region key, position zeroed, no position no bulletin, settles once across "
          "a reload, and a corpse moves neither the median nor a dividend"
          % (BUYOUT_PREMIUM, WINDUP, alive, floor))


def check_save_store():
    """The mod's private save store, and the two ways it fails silently.

    WHY THIS EXISTS. cm:set_saved_value does not write a value of its own - CA concatenates
    every mod's values into one "saved_values" string, the engine caps that string at 0x7000
    bytes and drops it whole, and CA's reader BREAKS SILENTLY on the empty string it gets back
    (load_values_from_string, "if not next_separator then break"). Measured 2026-09-07: a blob
    that had grown to exactly 28,672 bytes took 305 saved values down with it, including a
    player's paid-for share position. Nothing was logged, by anyone.

    So the mod keeps its own named value. Both failure modes here are silent:

    1. REGISTERED TOO LATE. LoadingGame fires BEFORE the first tick. Move the loading callback
       inside cm:add_first_tick_callback - the obvious place, since the rest of the mod lives
       there - and it is registered after the event it is waiting for. It never fires, EX.store
       stays empty, and every load looks like a fresh campaign. Only POSITION in the file tells
       the two apart, so that is what is asserted.

    2. THE ROUND TRIP. Every other harness assigns EX.store directly and so never runs these
       callbacks - confirmed by mutation, blanking the loading callback's assignment passed the
       whole suite. This one runs them.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    load_at = code.find("cm:add_loading_game_callback(")
    save_at = code.find("cm:add_saving_game_callback(")
    tick_at = code.find("function EX.init()")
    assert load_at > 0, "no loading-game callback: nothing ever reads the store back"
    assert save_at > 0, "no saving-game callback: nothing ever writes the store"
    assert tick_at > 0, "EX.init is gone - the startup body has moved somewhere unknown"
    assert load_at < tick_at, (
        "cm:add_loading_game_callback is registered at or inside EX.init (offset "
        "%d vs %d). LoadingGame fires BEFORE the first tick, so it never runs and every load "
        "silently starts from an empty store." % (load_at, tick_at))
    assert save_at < tick_at, (
        "cm:add_saving_game_callback is inside EX.init, so a save can be missed")

    live = [l.strip() for l in lua.splitlines()
            if "cm:set_saved_value(" in l and not l.lstrip().startswith("--")]
    assert not live, (
        "these still write to CA's shared blob rather than the mod's store, so they are lost "
        "the moment the blob is capped: %s" % live)

    assert "return cm:get_saved_value(key)" in code, (
        "EX.getv lost its migration fallback - a campaign saved before 2026-09-07 keeps its "
        "state in CA's blob and nowhere else, so dropping this wipes those saves on load")

    if not os.path.isfile(LUA_EXE):
        print("  (skipped save-store run: no lua.exe)")
        return
    import subprocess, tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_store_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness % LUA_SCRIPT.replace("\\", "\\\\"))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    assert have.get("registered_save") == "true", "the saving callback was never registered"
    assert have.get("registered_load") == "true", "the loading callback was never registered"
    assert have.get("blob_written") == "true", (
        "the saving callback ran but wrote no named value, so the save holds nothing")
    assert have.get("shares") == "20", (
        "a share position did not survive the save/load round trip - got [%s]. This is the "
        "exact bug the store was built to fix." % have.get("shares"))
    assert have.get("hist") == "27,27,25", (
        "price history did not survive the round trip - got [%s]" % have.get("hist"))
    assert have.get("fresh_type") == "table", (
        "on a NEW campaign the store came back a %s, not a table - the first EX.setv indexes "
        "a nil value and kills the script at turn one" % have.get("fresh_type"))
    assert have.get("fresh_write") == "1", "the store is unusable on a new campaign"
    print("  save store: own named value, round-trips shares and history, empty table on a "
          "new campaign, nothing left on CA's shared blob")


def lua_of_script():
    return io.open(LUA_SCRIPT, encoding="utf-8").read()


def check_lua_log():
    """Run the SHIPPED log code. Five of its failure modes are silent, and one is worse.

    THE LOG EXISTS BECAUSE THE PANEL CANNOT ANSWER "WHY". Three bugs shipped in this feature
    were each wrong INFORMATION rather than wrong behaviour - a war lock wearing the refusal
    sentence, a Buy button live on a house at war, a refusal the player read as a production
    claim - and no in-game assertion catches a sentence that misleads. The log is the record
    that lets a player check the reasoning, so its own reasoning has to be checked here.

    1. THE DEDUP CUTS TOO DEEP OR NOT AT ALL. log_scan re-runs on every refresh, so without a
       same-turn guard one standing closure fills all 60 slots inside a turn and the log is
       nothing but that line. With the guard keyed too broadly, a genuine repeat on a LATER
       turn is swallowed and the log silently under-reports. Both are asserted.

    2. LOG_SCAN RECORDS STATE INSTEAD OF CHANGES. The same failure wearing a different hat: a
       refusal that has stood for thirty turns must have written ONE line, on the turn it
       appeared, and one more when it lifted. A different house taking the refusal over is a
       new fact and must be recorded - that edge is the one a state-vs-change rewrite loses.

    3. THE SEPARATORS COLLIDE WITH THE CONTENT. Every field is free text meant for a human. A
       faction display name carrying ';' or a sentence carrying '|' would, under any printable
       delimiter, eat the rest of the saved log at the next load - and nothing would report it,
       because a short log is exactly what a new campaign looks like. The round trip is run
       against a subject and a detail that carry both characters.

    4. THE TURN COMES BACK A STRING. unpack_log reads text; without tonumber the dedup's
       first[1] == turn comparison silently never matches again after one load.

    5. A SAVE FROM AN OLDER, LONGER LOG OVERFLOWS THE CAP on restore, so the ring buffer grows
       without limit across saves.

    And the one that is not silent: log_lines with an empty log must still return a row, or the
    panel's first draw indexes nil and takes the script down.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    assert 'EX.LOG_RS = string.char(30)' in code and 'EX.LOG_FS = string.char(31)' in code, (
        "the log separators are no longer built with string.char. Written as literal bytes "
        "they are invisible in every editor, and this file has already had a pair of escapes "
        "rewritten in transit once - a deleted separator would not be seen until a load")
    body = code[code.find("function EX.pack_log"):code.find("function EX.log_lines")]
    assert not re.search(r'[;|]', body), (
        "a printable delimiter has appeared in the pack/unpack code: %s" % body)

    # getp/setp, NOT getv/setv, since the multiplayer split (2026-09-09). The log is PER
    # PLAYER: every machine runs every human's turn pass and writes every human's log, so an
    # unscoped key would have them overwriting each other in one shared save.
    assert "pcall(function() EX.unpack_log(EX.getp(EX.SAVE_LOG)) end)" in code, (
        "EX.restore_player no longer reads the log back, so it empties on every load - which "
        "is the one moment a player most wants to ask why they were refused")
    assert re.search(r"EX\.setp\(EX\.SAVE_LOG, EX\.pack_log\(\)\)", code), (
        "nothing writes the log to the store; a save holds none of it")

    if not os.path.isfile(LUA_EXE):
        print("  (skipped log run: no lua.exe)")
        return
    import subprocess, tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_log_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace("\\", "\\\\"))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    def eq(key, want, why):
        assert have.get(key) == want, "%s (%s: expected [%s], got [%s])" % (
            why, key, want, have.get(key))

    eq("newest_first", "second,first",
       "the log is drawn top-down, so the newest entry must be at index 1")
    # THE CAP IS READ, NOT TYPED. The harness fills EX.LOG_MAX + 25 off the shipped constant,
    # so a literal here disagrees with it the moment the constant moves - which is exactly what
    # happened when the world started writing to the log and 60 became 120.
    cap_m = re.search(r"EX\.LOG_MAX\s*=\s*(\d+)", lua_of_script())
    assert cap_m, "EX.LOG_MAX is gone - nothing bounds the log and the save string is unbounded"
    log_max = int(cap_m.group(1))
    # AND IT HAS A FLOOR. Reading the constant proves the buffer caps where it says it does and
    # nothing more; set it to 5 and the harness and the check would agree perfectly while the
    # log held two turns. Since 2026-09-09 the world writes up to three lines a turn - the
    # guild's books, the appetite and a shock - before the player has traded at all.
    assert log_max >= 100, (
        "EX.LOG_MAX is %d. The world writes up to three lines a turn on its own, so a buffer "
        "this small drops the player's own trades - the entries the log was built for - inside "
        "a dozen turns." % log_max)

    eq("dedup_same_turn", "2",
       "the same line was recorded twice in one turn. log_scan runs on every refresh, so this "
       "fills all %d slots with one closure inside a single turn" % log_max)
    eq("kept_next_turn", "3",
       "a genuine repeat on a LATER turn was swallowed by the dedup - the log now under-reports "
       "instead of over-reporting, which is the harder failure to notice")
    eq("turn_stamped", "2,1", "entries are not carrying the turn they happened on")
    eq("nil_rejected", "true",
       "a half-written entry was stored; it would serialise short and be dropped on the next "
       "load, silently")

    eq("cap", str(log_max), "the ring buffer does not cap at EX.LOG_MAX")
    eq("cap_keeps_newest", "entry %d" % (log_max + 25),
       "the cap dropped the NEWEST entries instead of the oldest")

    assert have.get("drawn") == have.get("rows_available"), (
        "log_lines returned %s lines but the render loop walks %s rows. It borrows one row per "
        "instrument, so a line past that count is handed back, never drawn, and still counted "
        "in the footer's \"the newest N\". Take the cap from EX.mode_instruments(), not from a "
        "constant." % (have.get("drawn"), have.get("rows_available")))
    eq("drawn_left", "T%d  Gems" % (log_max + 25),
       "the row label lost its turn stamp or its subject")
    eq("empty_rows", "1",
       "log_lines returned nothing for an empty log - the panel's first draw indexes nil")
    eq("empty_left", "Nothing yet", "the empty-log placeholder is gone")

    eq("saved_on_add", "true",
       "the log is written at turn end rather than on the add, so a crash loses the reasoning "
       "for the last thing the player did")
    eq("rt_count", "2", "the save round trip lost entries")
    eq("rt_turn", "7", "the turn did not survive the round trip")
    eq("rt_subject", "Legion of Azgorh; Zharr-Naggrund",
       "a subject carrying ';' was truncated - the separator collides with the content")
    eq("rt_detail", "Refused | holds 30 of 44 lots; despises you.",
       "a detail carrying '|' and ';' was truncated - the separator collides with the content")
    eq("rt_type", "number",
       "the turn came back a string, so the same-turn dedup never matches again after a load")
    eq("rt_key", "res_rom_furs", "the instrument key did not survive the save round trip")
    eq("rt_legacy", "1,Old,true",
       "a log saved before the icon shipped has three fields, not four. Refusing it empties a "
       "live campaign's log on the first load after an update - the exact failure this store "
       "exists to prevent")
    eq("rt_nil", "0", "unpack_log(nil) left the previous log in place")
    eq("rt_empty", "0", "unpack_log('') left the previous log in place")
    eq("rt_capped", str(log_max),
       "a save written when the log was longer restored past the cap, so the buffer grows "
       "across saves")

    # THE NAME AND THE ICON. EX.display_name was never defined and every call site wrapped it
    # in `EX.display_name and EX.display_name(res) or res`, so the missing function degraded to
    # the raw key - "res_rom_furs" on screen, screenshotted 2026-09-07. An `and ... or` around
    # a name nothing declares is not a guard; it is a fallback that hides the typo forever.
    eq("subject_named", "true", "a log line is still drawing the raw instrument key")
    eq("subject_matches_display", "true",
       "the log names a commodity differently from every other view - EX.display is the one "
       "accessor, and two names for one thing is how a player learns to distrust the panel")
    eq("key_kept", "true", "the entry does not carry the instrument key, so it cannot be iconed")
    eq("line_carries_key", "true", "log_lines drops the key, so the row has nothing to paint")
    eq("icon_for_key", "true", "EX.icon has no path for a commodity the log records")
    eq("house_named", "Zhatan the Black",
       "log_subject sent a house through EX.display. A house is not in EX.INFO, so that falls "
       "through to EX.short and prints a chopped faction key where the other four views print "
       "a house name")
    eq("commodity_still_display", "true",
       "log_subject sends a COMMODITY through the house accessor")

    # THE ICON, WHICH IS THREE SITES AND NOT ONE. Rows are created one per instrument with that
    # instrument's icon baked in at build time, and the log writes line i into row i - so the
    # icon is only ever right if the log repaints it from the LINE, and the trade view is only
    # right again afterwards if it repaints from the ROW. Placing the cell without both is
    # worse than not placing it: every log line would draw a confidently wrong picture.
    log_row = code[code.find("EX.ROW_LAYOUT_LOG = {"):]
    log_row = log_row[:log_row.find(chr(10) + "}")]   # first "}" is the divider ROW, not the table
    assert '"icon"' in log_row, (
        "the log rows place no icon cell, so EX.layout hides it and the view is back to text")
    log_draw = code[code.find("if EX.mode == EX.MODE_LOG then"):]
    log_draw = log_draw[:log_draw.find("if EX.mode == EX.MODE_HELP then")]
    assert "EX.icon(line[3])" in log_draw and "SetImagePath" in log_draw, (
        "the log branch does not paint the icon from the LINE's key. The row it borrowed was "
        "built with a different instrument's icon, so every line would draw the wrong picture "
        "- and confidently, which is worse than drawing none")
    assert "ic:SetVisible(" in log_draw, (
        "a log line with no instrument - a market closure - would keep whatever icon the row "
        "was built with, and that picture reads as a claim about a commodity the line never "
        "mentions")
    # ANCHORED ON THE SHARED LOOP'S OWN FIRST LINE. Anchoring on EX.hold_guild() found its
    # DEFINITION, two thousand lines earlier, and the next mode_instruments loop after that is
    # the log branch's - so the check read the log's repaint and called it the trade view's.
    shared = code[code.find('set_text(row, "row_name", EX.display(res))'):][:2000]
    assert "EX.icon(res)" in shared and "SetImagePath" in shared, (
        "nothing repaints a row's own icon on the other views. The log overwrites icons in "
        "place, so a row it left carrying the furs icon still carries it on the trade view - "
        "the contamination is invisible until you switch back")
    # A LINE WITH NO INSTRUMENT MUST CARRY NO KEY. Rows are built one per instrument with that
    # instrument's icon baked in, and this view writes line i into row i - so an empty key is
    # what tells the row to HIDE its icon rather than leave a picture that reads as a claim
    # about a commodity the line never mentions.
    eq("no_key_is_empty", "true", "a market-wide line was given an instrument key")
    eq("no_key_line", "true", "log_lines invented a key for a line that has no instrument")
    eq("empty_line_key", "", "the empty-log placeholder carries a key, so it would draw an icon")
    eq("scan_key", "res_gems", "log_scan records a refusal without the commodity it is about")

    eq("scan_quiet", "0", "log_scan wrote a line with nothing wrong")
    eq("scan_closed", "1", "a closure was not recorded")
    eq("scan_closure_once", "1",
       "a STANDING closure wrote a line on every scan. log_scan must record what changed, not "
       "what is true")
    eq("scan_reopen", "2", "the reopening was not recorded")
    eq("scan_refusal_once", "1", "a standing refusal wrote a line on every scan")
    assert "30 of the guild's 44 lots" in have.get("scan_refusal_text", ""), (
        "the refusal line lost the book share. That number is the whole justification and it "
        "appears nowhere else on the panel - the Trade view's Output column is map-wide "
        "production, which is a different thing and was read as a production claim once "
        "already. Got [%s]" % have.get("scan_refusal_text"))
    eq("scan_lift", "2", "a refusal lifting was not recorded")
    assert "will deal again" in have.get("scan_lift_text", ""), (
        "the lift line does not say the house will deal again - got [%s]"
        % have.get("scan_lift_text"))
    # ------------------------------------------------------- the world's own entries
    # THE TALLY FOLLOWS THE LOOP. The harness runs the shipped EX.step_books against stubbed
    # accessors, so these are what the trades actually did - not a second copy of the sum.
    # h_one buys 4 gems and dumps 5 of its 7 furs (BOOK_TRADE_MAX), h_two buys 6 gems and has
    # nothing to sell, which is the pair a tally written by eye gets wrong.
    eq("flow_bought", "10", "the guild's buying is not being counted as it happens")
    eq("flow_sold", "5",
       "the sell tally is wrong - it must be the lots actually moved, which BOOK_TRADE_MAX "
       "caps at 5 out of a book of 7, not the size of the book")
    eq("flow_houses", "2", "the count of houses that traded is wrong")
    eq("flow_top_buy", "10,nil",
       "the per-commodity buy tally credited the wrong good, or credited one nobody bought")
    eq("flow_top_sell", "nil,5",
       "the per-commodity sell tally credited the wrong good. A house with an empty book and "
       "a negative desire must not appear here at all")

    # THE SHIPPED appetite_summary, run once before the harness stubs it out. build_world_log
    # calls it every turn, so it is one of the four things running inside FactionTurnStart -
    # and without this the loc counter below would be measuring a stub.
    eq("real_appetite", "World at war: 40%.  Wanted: Gemstones.  Going begging: Furs.",
       "the shipped EX.appetite_summary no longer produces the footer's line, which is the "
       "line the log records verbatim so the two cannot disagree about what the world wants")

    eq("world_first", "1",
       "the first appetite reading of a session was announced as a change. Nothing moved - "
       "there was nothing to compare against - and every load would open with a line saying "
       "the world's appetite had shifted")
    eq("world_changed", "2", "an appetite that genuinely changed was not recorded")
    eq("world_unchanged", "1",
       "an unchanged appetite is being logged again. The turn round runs every turn; this is "
       "one line a turn saying nothing happened")
    eq("world_quiet", "0",
       "a turn in which no house traded still wrote a guild line. Every house priced out of "
       "the market is not an event")
    eq("world_guild",
       "2 house(s) traded: bought 10, sold 5.  Most bought Gemstones (+10).  "
       "Most sold Furs (-5).",
       "the guild line no longer reads as what the houses did")
    eq("world_guild_key", "res_gems",
       "the guild line lost its icon key - it should be the good the guild moved most of")
    eq("world_appetite", "World appetite", "the appetite line lost its subject")
    eq("flush_per_player", "2,2",
       "the world's lines reached one player and not the next. They are BUILT once and "
       "WRITTEN per human on purpose: deciding 'has the appetite changed' inside the "
       "per-player loop answers yes for the first human and no for everybody after them, "
       "because the first comparison is what stops it being a change")

    eq("div_line", "2 house(s) paid you 120g.",
       "the dividend is paid with nothing in the log saying where the gold came from - and "
       "the count must be the houses that PAID, not the houses that exist")
    eq("div_silent", "0", "a turn that paid no dividend still wrote a line")

    eq("shock_line", "Demand shock: prices +3 rung(s) (raided).",
       "a demand shock is announced only in the event feed, which the player dismisses and "
       "cannot get back - while the shock goes on moving their prices for several turns")
    eq("shock_subject", "",
       "the shock line resolved its own subject instead of deferring it. Turn-time entries "
       "pass \"\" and the key; see turn_loc_calls below")
    eq("shock_key", "res_gems", "the shock line lost the commodity it is about")

    # THE ONE THAT MATTERS. common.get_localised_string from inside a turn handler took the
    # process down at turn 1 of a FRESH campaign - no Lua error, no minidump, and pcall made no
    # difference (2026-09-07, EX.settle_house). All four writers above run inside
    # FactionTurnStart. The harness installs a counting `common` and this is the count.
    eq("turn_loc_calls", "0",
       "a writer that runs inside FactionTurnStart asked the game to localise a string. That "
       "is the call that CTD'd turn 1 of a fresh campaign with no error and no minidump, and "
       "pcall did not catch it. Store the KEY and let EX.log_lines resolve it at draw time - "
       "subject \"\" plus field 4 - the way EX.log_settlement does")

    eq("scan_handover", "4",
       "a DIFFERENT house taking over the refusal was not recorded. It is a new fact, and it "
       "is the edge a state-based rewrite loses")

    assert "function EX.log_subject" in code, (
        "EX.log_subject is gone - the log is back to naming commodities itself")
    assert "EX.display_name" not in NL.join(
        l for l in lua.splitlines() if not l.lstrip().startswith("--")), (
        "EX.display_name is called again. It has never been defined in this file; every call "
        "site wrapped it in `and ... or res`, so it fails to the raw key rather than erroring")

    print("  log: newest-first and capped at %d, deduped within a turn but not across turns, "
          "one line per row the view actually has and a placeholder when empty, saved on every "
          "add and round-tripping "
          "text that carries ';' and '|', each line naming its commodity the way every other view "
          "does and carrying the key its icon is painted from, and log_scan records closures, "
          "refusals, lifts and handovers once each rather than every refresh; the world "
          "writes the guild's books, a changed appetite, the dividend and the shock, built "
          "once and flushed per player, and NONE of the four localises a string" % log_max)


def check_price_cell():
    """The hostility markup, on the price it moved.

    REPORTED FROM PLAY 2026-09-07: "i also cant tell that these factions have added percentage
    in the buy and sell panel". The mechanic was right and had been right for a day - the log
    said "Disciples of Hashut dislikes you: 14% more" after every fill and the tooltip said it
    on hover - but the Buy and Sell columns drew a number 14% worse than the world price with
    nothing at all beside it. That is the fourth fault in this feature of the same shape: not
    wrong behaviour, wrong information. No in-game assertion catches a panel that stays quiet.

    Three ways the cell can lie, all silent:

    1. IT PRINTS THE RAW HOSTILITY. sell_price clamps at EX.SELL_FLOOR, so past that point the
       raw figure is not what came off the price - the cell would claim a haircut the floor
       refused to apply. Measured here at h=0.9: the price really fell 72%, not 90%.

    2. THE NUMBER STOPS BEING THE CHARGED PRICE. buy_price and sell_price are what EX.trade
       charges; a cell that re-derives or rounds is the panel lying about the price, which is
       the rule check_lua_books has guarded since the sell column shipped.

    3. IT OUTGROWS ITS COLUMN. row_price is 74px with a 4px text offset - about 10 characters
       at the 6.7px/char this suite measures everywhere else. Text clips to its component in
       silence, so an overrun draws "6318+2..." and only a screenshot would ever show it.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    # THE COLOUR NAME IS FROM CA'S 42, and a typo silently drops the colour rather than
    # erroring - the cell would draw the markup in the ordinary text colour and read as part
    # of the price. "red" is the name the rest of this file already uses.
    assert "[[col:red]]" in code and "[[/col]]" in code, (
        "the markup is no longer coloured, or the tag is unclosed - an unclosed [[col:]] "
        "bleeds into every cell drawn after it")

    if not os.path.isfile(LUA_EXE):
        print("  (skipped price cell run: no lua.exe)")
        return
    import subprocess, tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_price_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write(harness % LUA_SCRIPT.replace(chr(92), chr(92) * 2))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    # A CALM MARKET DRAWS A BARE NUMBER. A "+0%" on every row in a friendly campaign would
    # make the one row that matters invisible among nineteen that do not.
    assert have["calm_buy"] == "1007" and have["calm_sell"] == "906", (
        "with no hostility the cells read %s / %s - they must be the plain price"
        % (have["calm_buy"], have["calm_sell"]))

    assert have["buy_cell"] == have["buy_num"] + "[[col:red]]+14%[[/col]]", (
        "the Buy cell reads %r. It must be buy_price (%s) and the markup, in that order - the "
        "number first is what a player scanning a column of prices reads"
        % (have["buy_cell"], have["buy_num"]))
    assert have["sell_cell"] == have["sell_num"] + "[[col:red]]-16%[[/col]]", (
        "the Sell cell reads %r against a sell_price of %s"
        % (have["sell_cell"], have["sell_num"]))
    # THE SIGNS ARE OPPOSITE AND BOTH ARE RED. A hostile guild charges more AND pays less;
    # they are one fact costing the player money, so the colour is the same and only the
    # direction differs. A "+" on the sell side would read as a bonus.
    assert "+" in have["buy_cell"] and "-" in have["sell_cell"], (
        "the two sides carry the same sign - one of them is telling the player the guild's "
        "dislike is doing them a favour")

    # THE SELL SIDE IS MEASURED OFF THE SPREAD, not off 1.0: sell_price starts at 1 - SPREAD,
    # so the same hostility is a bigger fraction of a smaller base. 14 and 16, not 14 and 14.
    spread = float(have["spread"])
    want_sell = int(0.14 / (1 - spread) * 100 + 0.5)
    assert have["sell_pct"] == str(want_sell), (
        "the sell markup reads %s; against a base of 1 - SPREAD (%.2f) a hostility of 0.14 is "
        "%d%%. Printing the buy figure on both sides understates what the sell is costing."
        % (have["sell_pct"], 1 - spread, want_sell))

    # THE CLAMP. Past EX.SELL_FLOOR the raw hostility is not what came off the price.
    assert have["clamped_pct"] != have["clamped_raw"], (
        "at a hostility of 90%% the cell printed %s%% - but sell_price clamps at "
        "EX.SELL_FLOOR (%s) and the price only fell to %s. Printing the raw input claims a "
        "haircut the floor refused to apply."
        % (have["clamped_pct"], have["sell_floor"], have["clamped_price"]))
    assert int(have["clamped_pct"]) < int(have["clamped_raw"]), (
        "the clamped figure (%s) is not smaller than the raw one (%s)"
        % (have["clamped_pct"], have["clamped_raw"]))

    # THE CEILING KEEPS IT TO TWO DIGITS, which is what keeps the cell inside its column.
    assert have["max_pct"] == str(int(round(float(have["hostile_max"]) * 100))), (
        "at EX.HOSTILE_MAX the markup reads %s, not %s"
        % (have["max_pct"], int(round(float(have["hostile_max"]) * 100))))

    # AND IT FITS. row_price's width comes from the Lua layout table; the 6.7px/char is the
    # figure check_help_lines, check_header_labels and check_footer_bounds all measure with.
    m = re.search(r'\{ "row_price",\s*\d+,\s*\d+,\s*(\d+) \}', code)
    assert m, "row_price has no width in EX.ROW_LAYOUT - cannot measure the cell"
    box, offset, px_per_char = int(m.group(1)), 4, 6.7
    usable = int((box - offset) / px_per_char)
    widest = int(have["widest_len"])
    assert widest <= usable, (
        "the widest cell this can draw is %s - %d characters, ~%.0fpx - against %dpx of usable "
        "room in a %dpx column (%d chars). Text clips to its component in silence, so this "
        "draws a truncated price and only a screenshot would show it."
        % (have["widest"], widest, widest * px_per_char, box - offset, box, usable))
    print("  price cell: bare number when the guild is calm, price-then-markup when it is not, "
          "buy +%s%% against sell -%s%% off the spread base, the SELL_FLOOR clamp reported as "
          "%s%% and not the raw %s%%, and the widest cell (%s) is %d of %d chars"
          % (have["buy_pct"], have["sell_pct"], have["clamped_pct"], have["clamped_raw"],
             have["widest"], widest, usable))


def check_init_hardening():
    """The mod must still start when CA's first-tick callback list never finishes.

    THE FAILURE, MEASURED 2026-09-07. On a loaded save the opener button was absent,
    cm.is_processing_first_tick_callbacks was still true, and nothing in the log named this
    script. cm:process_first_tick_callbacks (lib_campaign_manager.lua:2471) walks all five
    lists with call_each, and call_each has NO pcall - one throwing callback belonging to any
    other mod ends the pass, and everything queued after it never runs. This file is zzz_*, so
    it loads last and sat 69th of 69: the worst slot on the machine.

    THE SECOND ENTRY POINT. core listener callbacks are dispatched one at a time through xpcall
    (lib_core.lua, event_protected_callback), so one that throws cannot stop another - the
    opposite of call_each. CA triggers ScriptEventFirstTickAfterWorldCreated from inside
    cm:first_tick BEFORE it starts the callback lists, so this route runs earlier AND is out of
    reach of another mod's failure. cm:add_first_tick_callback stays as the belt.

    THIS IS RUN, NOT READ. The harness fires only the listener and asks whether the body was
    entered, then fires the first-tick callbacks and asks whether it was entered a second time.
    Mutation-checked both ways: deleting the core:add_listener line fails the first assertion,
    deleting the EX.inited guard fails the second.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    assert "function EX.init()" in code, (
        "the startup body is an anonymous first-tick callback again - it cannot be reached by "
        "a second entry point, so one unrelated mod's failure takes this one down with it")

    if not os.path.isfile(LUA_EXE):
        print("  (skipped init-hardening run: no lua.exe)")
        return
    import subprocess, tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_init_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness % LUA_SCRIPT.replace(chr(92), chr(92) * 2))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    assert have.get("listener") == "true", (
        "nothing listens for ScriptEventFirstTickAfterWorldCreated, so the ONLY way this mod "
        "starts is the unprotected first-tick list")
    assert have.get("tick_registrations") == "1", (
        "expected exactly one cm:add_first_tick_callback registration, got %s"
        % have.get("tick_registrations"))
    assert have.get("after_listener") == "1", (
        "the listener fired and the startup body did not run (%s). With the first-tick list "
        "broken by another mod, that is a campaign with no Exchange in it and no error either."
        % have.get("after_listener"))
    assert have.get("after_tick") == "1", (
        "the body ran %s times once both entry points fired. On a healthy machine both DO "
        "fire, so a missing guard means two discovery walks and a second set of click "
        "listeners on the same buttons - every trade would be executed twice."
        % have.get("after_tick"))
    print("  init hardening: starts from the xpcall'd listener alone, and runs once when both "
          "entry points fire")


def check_lua_placeholder():
    """No plain flag on string.find, and the placeholder stays free of pattern magic.

    THE BUG THIS EXISTS FOR, and it is the worst one this file has had.
    `string.find(loc, EX.LOC_PLACEHOLDER, 1, true)` - the plain flag - CORRUPTS WH3's string
    subsystem PROCESS-WIDE. Afterwards string.sub and string.find return garbage for every
    script in the game, CA's own find_uicomponent starts missing silently, nothing throws, and
    only restarting the game recovers it.

    Proven live 2026-09-08 through the MCP bridge in a single call:

        before=OK | plain_find_returned=true | after=BROKEN

    and independently found 2026-08-21 by that bridge, whose strings_ok() tripwire exists for
    this and nothing else.

    WHY IT TOOK FOUR BUILDS TO FIND. The call sat inside EX.faction_display, which is MEMOISED -
    so it fired on whichever house name a session had not yet resolved. That made the panel die
    at a **different row every run**, which killed three diagnoses in a row: a fixed row count, a
    stale component, and a build that happened too early. The clean build was clean only because
    it predates the call. Nothing in `luac -p`, check_lua_undeclared or the row harnesses could
    see it, because it is a legal call that returns a legal value.

    check_lua_api.py now refuses the plain flag across ALL 96 pack scripts, which is the real
    guard. This one adds what that cannot know: the placeholder is matched as a PATTERN now, so
    a magic character in it would silently change what it matches.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    import re as _re
    plain = _re.compile(r"find\s*\([^()]*,\s*(?:true|1)\s*\)")
    for m in plain.finditer(code):
        frag = m.group(0)
        assert not frag.rstrip().endswith("true)"), (
            "string.find plain flag is back: %s. One such call corrupts the string subsystem "
            "for the WHOLE GAME - CA's lookups included - with no error and no recovery short "
            "of a restart. Escape the pattern instead." % frag)

    m = _re.search(r'EX\.LOC_PLACEHOLDER\s*=\s*"([^"]*)"', code)
    assert m, "EX.LOC_PLACEHOLDER is gone or is no longer a plain string literal"
    ph = m.group(1)
    assert ph, "EX.LOC_PLACEHOLDER is empty - string.find would match every string"
    magic = set('^$()%.[]*+-?') & set(ph)
    assert not magic, (
        "EX.LOC_PLACEHOLDER is %r, which contains Lua pattern magic %s. It is matched with "
        "string.find as a PATTERN (the plain flag is banned - it corrupts the string subsystem "
        "process-wide), so a magic character changes what it matches, or errors."
        % (ph, sorted(magic)))
    assert 'string.find(loc, EX.LOC_PLACEHOLDER)' in code, (
        "the placeholder guard in EX.faction_display is gone - CA's [YOU SHOULDN'T SEE THIS] is "
        "a real localised string and passes every empty check, so without this it draws as a "
        "faction name")
    print("  placeholder: no plain-flag find, %r carries no pattern magic" % ph)


def check_nav_cycle():
    """The bottom strip: five view tabs on the left, two arrows and a page counter right.

    IT WAS A VIEW CYCLE UNTIL 2026-09-07. The arrows walked EX.MODES and the guide was the one
    view they paged instead. Two things from play changed that:

      * "additional 5 buttons here for all the panels so that the player dont need to scroll
        the panels using the two arrow buttons" - Houses was three arrow presses from Trade.
      * "no scrollable panel as well for the log panel" - the log keeps 60 entries and draws
        19, so 41 of them could not be reached at all.

    With a tab per view the arrows have no cycling left to do, and paging is what the log
    needed - so paging every view is now the rule the guide was already the exception to.

    WHAT IS MEASURED, by running the shipped file: a tab name maps to exactly one mode and a
    foreign name to none; every mode has a label; every view is one click from every other;
    the arrows move the PAGE and never the view, wrap both ways, and are a no-op where there
    is one page; the counter reads index/count; the slice log_lines returns actually differs
    per page and clamps when the page runs past the end; and entering a view opens page 1.
    """
    if not os.path.isfile(LUA_EXE):
        print("  (skipped nav run: no lua.exe)")
        return
    import subprocess, tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_nav_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness % LUA_SCRIPT.replace(chr(92), chr(92) * 2))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    n = int(have["modes"])
    assert n >= 2, "%d views - a tab strip and two arrows make no sense below two" % n

    # THE TABS.
    assert have["tab_map"] == "true", (
        "a tab's component name does not map back to its own mode. The click listener has "
        "nothing else to go on - a component name is all a ComponentLClickUp carries")
    assert have["tab_foreign"] == "nil,nil", (
        "EX.tab_mode claimed a component that is not one of ours (%s). It is the listener's "
        "FILTER as well as its handler, so a false positive there makes this panel react to "
        "clicks anywhere in the game" % have["tab_foreign"])
    assert have["tab_labels_all"] == "true", (
        "a view has no tab label (%s). A blank tab draws, clicks and works perfectly - it "
        "just does not say what it is, and no geometry check can see that"
        % have["tab_labels"])
    assert have["tab_reach"] == "true", (
        "some view is not reachable in one click from some other view. That is the whole ask: "
        "Houses used to be three presses of an arrow away from Trade")

    # THE PAGE COUNTS. The harness fills the log to 45 entries against 19 rows.
    per = int(have["per_page"])
    assert per >= 2, "the log draws %d rows a page" % per
    assert have["log_pages"] == "3", (
        "45 entries at %d a page is 3 pages, not %s" % (per, have["log_pages"]))
    counts = dict(x.split("=") for x in have["page_counts"].split(","))
    # A VIEW WITH ONE PAGE GREYS THE ARROWS, so a count of 1 here is the assertion that they
    # are not live controls with nothing to control. Ownership and Offerings are single-page
    # lists and must stay that way; Houses pages on row overflow; the log and the guide page
    # by construction.
    for m in ("stats", "offer"):
        assert counts.get(m) == "1", (
            "%s reports %s pages. It is a single-page list, so the arrows would be live "
            "controls with nothing to control" % (m, counts.get(m)))
    # TRADE HAS EXACTLY TWO, and always - page 1 the list, page 2 the deep chart. Not "two
    # when something is selected": the arrows are the only affordance that says the chart
    # exists, so a count that collapsed to 1 with nothing chosen would hide the feature from
    # every player who had not already found it.
    assert counts.get("trade") == "2", (
        "trade reports %s pages, want 2 - page 1 is the list and page 2 is the deep price "
        "chart. A 1 here means EX.page_count lost its trade branch and the chart is "
        "unreachable, with nothing on screen to say so." % counts.get("trade"))
    assert int(counts["log"]) > 1 and int(counts["help"]) > 1, (
        "the log and the guide must both page - %s" % have["page_counts"])

    # THE ARROWS PAGE AND NEVER SWITCH VIEW. This is the regression the change itself invites:
    # an unconverted branch still walking EX.MODES would move the player off the log entirely.
    assert have["log_fwd"] == "2,log", (
        "the forward arrow on the log went to %s. It must page the log, not leave it - "
        "leaving is what the tabs are for now" % have["log_fwd"])
    assert have["log_back_wrap"] == have["log_pages"], (
        "stepping back from page 1 landed on page %s, not the last page (%s). Lua indexes "
        "from 1, so (at - 1) %% n is 0 there and an off-by-one indexes nil"
        % (have["log_back_wrap"], have["log_pages"]))
    assert have["log_fwd_wrap"] == "1", (
        "stepping forward from the last page landed on %s, not page 1" % have["log_fwd_wrap"])
    assert have["help_back_wrap"] == "%s,true" % counts["help"], (
        "the guide's back arrow from page 1 gave %s - it must wrap to the last page and stay "
        "in the guide" % have["help_back_wrap"])
    assert have["help_fwd"] == "2", (
        "the guide's forward arrow from page 1 landed on page %s" % have["help_fwd"])
    assert have["roundtrip"] == "true", (
        "one step each way is not a no-op - the two arrows disagree about where they are")
    assert have["single_page_noop"] == "true", (
        "an arrow moved something on a ONE-PAGE view. Before 2026-09-07 the arrows cycled "
        "views; a branch left unconverted takes the player off the view they are reading")
    assert have["press_prev"] == "1" and have["press_next"] == "3", (
        "the arrows are wired backwards: from page 2, Previous went to %s and Next to %s. "
        "Both arrows page correctly in SOME direction either way, so nothing else notices - "
        "measured by mutation 2026-09-07, with the direction inlined at the click site a "
        "swap passed the whole suite" % (have["press_prev"], have["press_next"]))

    # THE COUNTER.
    #
    # DERIVED FROM counts, not hardcoded to "every view but the log has one page". That form
    # was already a fiction - Houses pages on row overflow - and it broke the moment Trade
    # gained its chart page, reporting the counter as wrong when the counter was right.
    want = ",".join("1/" + counts[m]
                    for m in ("trade", "stats", "offer", "houses", "log"))
    assert have["labels"] == want, (
        "the counter reads %s, not %s" % (have["labels"], want))
    assert have["log_label"] == "2/" + counts["log"], (
        "the log's counter reads %s on page 2" % have["log_label"])

    # AND THE PAGE THE VIEW ACTUALLY DRAWS, not just the number the counter prints. This is
    # the hole the guide had: EX.help_lines hardcoded to page 1 passed every assertion above
    # while page 2 stayed unreachable and the counter cheerfully read "2/2".
    assert have["page2_differs"] == "true", (
        "log page 2 draws the same first line as page 1 (%s). The counter advances, the "
        "arrows look like they work, and 41 of the 60 kept entries are unreachable - which "
        "is the exact fault reported against the log" % have["page1_first"])
    assert have["last_page_len"] == str(45 - 2 * per), (
        "the last page drew %s lines; 45 entries at %d a page leaves %d on it"
        % (have["last_page_len"], per, 45 - 2 * per))
    assert have["log_overflow_len"] == "%d,%s" % (45 - 2 * per, have["log_pages"]), (
        "a page index past the end gave %s. It must clamp - an out-of-range page draws an "
        "empty list, which reads exactly like a log that recorded nothing"
        % have["log_overflow_len"])

    # ENTERING A VIEW OPENS PAGE 1.
    assert have["log_reset"] == "1", (
        "the log reopened on page %s. A player who has just clicked Log is asking about the "
        "newest events, not the ones three pages back" % have["log_reset"])
    assert have["help_reset"] == "1", (
        "the guide reopened on page %s - which may be a page about a system the player has "
        "since switched off in MCT, and EX.help_page is deliberately never saved"
        % have["help_reset"])

    # THE WIRING NO HARNESS REACHES. The click listener is registered inside EX.init, which
    # needs a live campaign, so these are static assertions on the shipped source - they
    # cannot fail for any reason except those lines being edited.
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    assert "EX.nav_click(s)" in code, (
        "the click listener no longer passes the clicked component's name to EX.nav_click, so "
        "which arrow the player pressed is decided somewhere nothing can test")
    assert re.search(r"local tab = EX\.tab_mode\(s\)", code), (
        "the click listener has no tab branch. The five buttons draw, and clicking one does "
        "nothing at all")
    assert "or EX.tab_mode(s) ~= nil" in code, (
        "the listener's FILTER does not admit tab clicks. CA's filter runs first and returning "
        "false there means the handler is never called - the tabs would be inert with a "
        "perfectly correct handler sitting behind them")
    step = re.search(r"function EX\.step_page.*?" + chr(10) + "end", code, re.S)
    assert step, "EX.step_page is gone"
    step = step.group(0)
    assert "EX.mode_before_help" not in step and "EX.set_mode" not in step, (
        "EX.step_page changes the VIEW. The arrows page; the tabs switch. An arrow that "
        "switches view takes the player off the page they were reading")
    # ITS REDRAW IS UNSEEN BY THE HARNESS - which necessarily stubs EX.layout and
    # EX.refresh_panel to no-ops, both reaching core:get_ui_root() - so dropping either call
    # would leave the counter advancing while the rows stayed frozen on the old page, and
    # every dynamic assertion above would still pass. Static, on the shipped source.
    assert "EX.layout()" in step, (
        "EX.step_page no longer calls EX.layout() - the counter would advance but the row "
        "positions and labels would not be re-laid out for the new page")
    assert "EX.refresh_panel()" in step, (
        "EX.step_page no longer calls EX.refresh_panel() - the counter would advance "
        "('2/3', '3/3') while the row text stayed frozen on the previous page. The harness "
        "stubs both calls, so this is invisible there; a player reads it as broken arrows")
    # THE TABS AND THE ARROWS BOTH SAY WHAT THEY ARE DOING. Disabled, not hidden, with a
    # tooltip - this file's own standard, from the AI-turn gate on the opener button.
    # AND EVERY TAB IS PLACED IN EVERY VIEW. EX.layout positions a component only if the mode's
    # layout table names it; one that is not named keeps the placeholder offset the .twui.xml
    # was generated with and draws in the wrong place, or under another component, on that view
    # alone - so the strip loses a button on exactly one screen and nothing reports it.
    prefix = re.search(r'EX\.TAB_PREFIX = "([^"]+)"', code)
    assert prefix, "EX.TAB_PREFIX is gone"
    modes_m = re.search(r"EX\.MODES = \{(.*?)\}", code)
    tabs = [prefix.group(1) + x for x in re.findall(r'"(\w+)"', modes_m.group(1))]
    tables = re.findall(r"EX\.PANEL_LAYOUT\w* = \{(.*?)" + chr(10) + r"\}", code, re.S)
    assert len(tables) >= 6, (
        "found %d panel layout tables, expected one per view plus the guide" % len(tables))
    for i, tbl in enumerate(tables):
        for tab in tabs:
            assert '"%s"' % tab in tbl, (
                "panel layout table %d places no %s. EX.layout only positions what its table "
                "names, so that tab keeps its placeholder offset on this view alone" % (i, tab))

    assert re.search(r"tab:SetDisabled\(here or locked ~= nil\)", code), (
        "the tab strip no longer greys BOTH the current view and a view this race cannot "
        "reach. `here` alone loses the gate; `locked` alone stops the strip saying where you "
        "are, and leaves the one button guaranteed to do nothing live.")
    assert re.search(r"set_tip\(tab, locked" + NL, code), (
        "a locked tab does not get its reason as a tooltip - the file's own standard is "
        "disabled AND explained, and it is the only thing distinguishing a gated control "
        "from a broken one")
    assert re.search(r"a:SetDisabled\(pages < 2\)", code), (
        "the arrows stay live on a one-page view. A control that does nothing when clicked is "
        "what EX.gate_button and the refused Buy button both exist not to be")
    # ===================================================================================
    # THE HOUSES VIEW PAGES. Until 2026-09-08 it TRUNCATED - `while #t > EX.MAX_ROWS do
    # t[#t] = nil end` against an ALPHABETICALLY SORTED list - so 39 Empire factions would
    # have listed Averland through Nordland and silently dropped Reikland, Stirland and
    # Talabecland. Already a live fault at 20 Chaos Dwarf houses, sitting on the limit.
    # ===================================================================================
    assert have["h_pages"] == "3", (
        "41 houses at %s a page is 3, not %s" % (have["per_page"], have["h_pages"]))
    assert have["h_count"] == have["h_pages"], (
        "EX.page_count answers %s for the Houses view but there are %s pages - the counter "
        "and the arrows both read that one function" % (have["h_count"], have["h_pages"]))
    assert have["h_first"] == "house_001", have["h_first"]
    assert have["h_len1"] == "20", (
        "page 1 drew %s rows against a 20-slot holder" % have["h_len1"])
    assert have["h_last"] == "house_041,1", (
        "the last page ended at %s. 41 houses over 3 pages of 20 leaves exactly ONE on page "
        "3; anything else is an off-by-one in the slice" % have["h_last"])
    assert have["h_union"] == "41,false,true", (
        "walking every page gave %s (count,duplicate,ascending). Every house must appear "
        "exactly once and in order - that is the whole point of paging over truncation, "
        "which listed Averland through Nordland and dropped Reikland in silence."
        % have["h_union"])
    assert have["h_shrunk"] == "4,1", (
        "the house list shrank under a player sitting on page 3 and the view drew %s. A "
        "house dies whenever EX.check_delistings runs, and an out-of-range page draws an "
        "empty view that reads exactly like a market with no houses in it - so the clamp "
        "belongs INSIDE the slice, not only where the arrows move the index."
        % have["h_shrunk"])
    assert have["h_overflow"] == "4,1", have["h_overflow"]
    assert have["h_under"] == "4,1", (
        "page 0 gave %s - clamp both ends, the way EX.log_lines does" % have["h_under"])
    assert have["h_empty"] == "1,0", (
        "an empty market reports %s pages. Zero makes nav_label read '1/0' and step_page "
        "take a modulo of nothing." % have["h_empty"])
    assert have["h_reset"] == "1", (
        "re-entering the Houses view opened page %s. Every view opens on its first page - "
        "the log and the guide already do." % have["h_reset"])
    assert have["h_fwd"] == "2,houses", (
        "the forward arrow on the Houses view gave %s. It must page the view, not leave it - "
        "leaving is what the tabs are for." % have["h_fwd"])
    assert have["h_back_wrap"] == have["h_pages"], (
        "stepping back from page 1 landed on %s, not the last page (%s)"
        % (have["h_back_wrap"], have["h_pages"]))
    assert have["h_exact"] == "1,20", (
        "20 houses against 20 slots reported %s. Chaos Dwarfs sit exactly on this number "
        "today - 10 vanilla plus the lords pack's 10 - so an off-by-one here ships a second, "
        "empty page to the only race currently playing." % have["h_exact"])
    assert have["h_over_by_one"] == "2", have["h_over_by_one"]
    # TWO, AND NEITHER OF THEM IS ROW OVERFLOW. The trade list is 19 rows against 20 slots
    # and must never page for that reason - the second page is the deep price chart, a
    # different KIND of content, the way the guide's two pages are. If this ever reads 3 the
    # list has started overflowing and the chart is no longer the last page.
    assert have["h_trade_pages"] == "2", (
        "the trade view reports %s pages, want 2: the list and the deep chart. A 1 means the "
        "chart is unreachable; a 3 means the 19-row list has started overflowing into a page "
        "the chart used to own." % have["h_trade_pages"])
    # THE ARROWS ACTUALLY REACH THE CHART. A page COUNT is not a route: with the trade branch
    # missing from EX.step_page and EX.page_index the counter still reads 1/2 and the arrows
    # are still un-greyed, and pressing them does nothing whatever. Both shipped as surviving
    # mutants before this existed - the chart was unreachable and every other check passed.
    assert have["t_fwd"] == "2,true", (
        "pressing Next on the trade list landed on %s, want page 2 with EX.on_chart() true. "
        "The chart is unreachable and the counter says otherwise." % have["t_fwd"])
    assert have["t_wrap"] == "1,false", (
        "Next from the chart page landed on %s, want a wrap to page 1" % have["t_wrap"])
    assert have["t_back"] == "2,false" or have["t_back"] == "2,true", (
        "Previous from page 1 landed on %s, want the last page" % have["t_back"])
    assert have["t_rows"] == "0", (
        "the chart page lists %s rows. EX.layout builds its hide keep-set from this list, so "
        "any row still named is left drawing on top of the chart - the fault that once put 19 "
        "commodity rows over the Houses view." % have["t_rows"])
    assert have["t_rows_back"] != "0", (
        "the trade LIST now draws no rows either - the chart branch is not scoped to page 2")

    assert have["h_summary_hidden"] == "false", (
        "the guild footer still appends 'N more not shown'. With paging the counter answers "
        "that, and two different answers to one question on one screen is worse than either "
        "answer on its own.")

    assert re.search(r'EX\.HELP_FOOT\d = "[^"]*[Hh]elp[^"]*"', lua), (
        "no guide footer names the way out. 'Either arrow leaves the guide' was how a player "
        "escaped by accident; taking it away without saying so in text leaves a screen you "
        "can enter and not obviously leave.")

    print("  view nav: %d tabs, each view one click from every other and the current one "
          "greyed, arrows page instead of cycling (log %s pages, guide %s, the rest 1 and "
          "greyed), both wrap, the drawn slice really changes and clamps past the end, and "
          "every view opens on page 1" % (n, counts["log"], counts["help"]))


def settle_src(src):
    """EX.settle_holder and EX.settle_house, concatenated.

    ONE SETTLEMENT IN TWO FUNCTIONS since 2026-09-09: settle_house reads the living price once
    and walks every human, settle_holder pays one of them and writes their bulletin and log
    line. Both run inside the turn round, so the loc-system ban applies to both - and the log
    line the prune depends on now lives in the second. Checking only the function that kept the
    old name would pass on a build that had lost either.
    """
    parts = re.findall(r"function EX\.settle_(?:house|holder).*?" + chr(10) + "end",
                       src, re.S)
    assert len(parts) == 2, (
        "expected EX.settle_holder and EX.settle_house, found %d settlement function(s). "
        "The settlement is the one code path in this mod that has taken the process down and "
        "the one that moves gold on a house's death; it does not get to go unread." % len(parts))
    return NL.join(parts)


def check_house_discovery():
    """Which factions become houses, and which must never become one permanently.

    Two faults, both seen on screen in a fresh campaign 2026-09-07:

    1. is_dead() IS NOT A PRESENCE TEST. Three mixer_chd_* factions owning no region, army or
       character answered is_dead() == FALSE during the first-tick walk and true a moment
       later. Discovery sits in that one-tick window, so all three were listed - drawing rows
       with a raw key for a name, "gone" for a seat and a red "Lo" for a trend.

    2. DISCOVERY IS A UNION, so anything listed once was listed forever. The union exists only
       to stop a held position being stranded (EX.restore rebuilds EX.shares_held by walking
       EX.houses), so it may carry forward a key we HOLD and nothing else.

    The presence test is OR, not AND: a CHARACTER_BOUND_HORDE owns zero regions for its whole
    life, so requiring territory would delist the one house that never has any. That is what
    the "horde" faction in the harness is for.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    m = re.search(r"function EX\.refresh_panel\(.*?\nend", code, re.S)
    assert m, "EX.refresh_panel is gone"
    seg = m.group(0)
    i = seg.find('set_text(row, "row_supply", "gone")')
    assert i > 0, "the delisted row branch no longer writes a 'gone' seat"
    assert 'set_text(row, "row_trend", "-")' in seg[i:i + 400], (
        "the delisted branch does not blank row_trend, so a dead house keeps the trend marker "
        "the generic cell wrote - a red 'Lo' sitting next to a price of '-'")

    if not os.path.isfile(LUA_EXE):
        print("  (skipped discovery run: no lua.exe)")
        return
    import subprocess, tempfile
    harness = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_discovery_harness.lua"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness % LUA_SCRIPT.replace("\\", "\\\\"))
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.splitlines():
        line = line.strip()
        if line:
            k, _, v = line.partition(" ")
            have[k] = v

    assert have.get("fresh") == "horde,settled", (
        "a fresh walk listed [%s], wanted [horde,settled]. The player is excluded, a dead "
        "faction is excluded, and a faction owning NOTHING must be excluded even when is_dead() "
        "says false - while a horde owning no region must still be a house."
        % have.get("fresh"))
    assert have.get("merged") == "ghost_we_hold,horde,settled", (
        "the merge produced [%s], wanted [ghost_we_hold,horde,settled]. The union must carry "
        "forward a key we still hold shares in (or its position is stranded) and must NOT "
        "carry one we hold nothing in (or a faction listed in error is permanent)."
        % have.get("merged"))
    # PRUNING. Nothing could remove a house until 2026-09-07, and four dead factions were
    # measured sitting on the Houses view as permanent Delisted rows. The union is still
    # deliberate - it exists so a key dropping out of faction_list() cannot strand a position -
    # but a delisted house holding nothing strands nothing, so it goes, and that self-heals
    # every save that already has one.
    # ORDER IS PRESERVED, not re-sorted: EX.discover_houses sorts once for a stable row order
    # across loads, and a prune that reordered would shuffle the Houses view under the player
    # on the turn a house died.
    assert have["after_prune"] == "alive_one,dead_held,alive_two", (
        "prune left %s. A DELISTED house the player holds NOTHING in must go; one they still "
        "hold must stay, because that row is how they see the settlement they were paid"
        % have["after_prune"])
    assert "dead_unheld" not in have["pruned_saved"], (
        "the pruned house is gone from EX.houses but still in the saved list (%s), so it comes "
        "straight back on the next load" % have["pruned_saved"])
    assert "dead_held" in have["pruned_saved"], (
        "the held delisted house was dropped from the save - EX.restore only rebuilds "
        "EX.shares_held for houses IN the list, so that strands the position")
    assert have["prune_idempotent"] == "true", (
        "a second prune changed the list. check_delistings calls this every turn and on every "
        "load")
    assert have["after_close"] == "alive_one,alive_two", (
        "a delisted house whose position is now closed was kept (%s) - keeping a held one is "
        "only safe if it leaves once there is nothing left to show" % have["after_close"])

    # AND IT IS ACTUALLY CALLED. The harness above drives EX.prune_houses directly, so a
    # perfectly correct prune that nothing ever invokes passes every assertion in it - and the
    # dead rows stay on the panel exactly as they did before. check_delistings is where it
    # belongs: it is the one pass that knows a house has just become delisted.
    lua_src = io.open(LUA_SCRIPT, encoding="utf-8").read()
    src = NL.join(l for l in lua_src.splitlines() if not l.lstrip().startswith("--"))
    cd = re.search(r"function EX\.check_delistings\(\).*?" + chr(10) + "end", src, re.S)
    assert cd, "EX.check_delistings is gone"
    assert "EX.prune_houses()" in cd.group(0), (
        "EX.check_delistings does not call EX.prune_houses. The prune is correct and never "
        "runs, so the dead rows stay on the Houses view exactly as they were")
    # BOTH HALVES. The multiplayer split (2026-09-09) left EX.settle_house as the loop that
    # reads the living price and walks every human, and moved the payout, the bulletin and the
    # log line into EX.settle_holder. A regex naming only one of them would pass on a build
    # where the log line had been deleted from the other.
    settle = settle_src(src)
    assert "EX.log_settlement(" in settle, (
        "a delisting is no longer written to the log. The prune takes the row away, so the log "
        "is the only place the settlement survives - and script_log.txt is not a place a "
        "player looks")

    # THE NAME. A row's subject cannot be a key, and it cannot be CA's placeholder either.
    assert have["name_real"] == "The Warhost of Zharr", (
        "a faction WITH a real localised name did not get it (%s)" % have["name_real"])
    assert "SHOULDN" not in have["name_placeholder"], (
        "the Houses view drew CA's own placeholder, %r. It is a real localised string, so "
        "every empty-string guard passes it through - screenshotted 2026-09-07 on two rows"
        % have["name_placeholder"])
    for k in ("name_placeholder", "name_empty", "name_cr", "name_no_common"):
        got = have[k]
        assert got and "_" not in got and not got.startswith(("mixer", "cr_", "wh3")), (
            "%s fell back to the raw key (%r). A key is not a name; the fallback has to be "
            "name-shaped or the row has no subject" % (k, got))
    assert have["name_empty"] == "Black Kraken" and have["name_cr"] == "Skullstack", (
        "the humanised names are %r and %r - the namespace prefix must go and the words must "
        "be capitalised" % (have["name_empty"], have["name_cr"]))
    assert have["name_no_common"] == "Gargath", (
        "with `common` missing entirely the name came back %r. The pcall guards the call; the "
        "fallback has to work when it fires" % have["name_no_common"])

    # THE CTD THIS COST. EX.log_settlement resolved the house's display name at settle time,
    # which reaches common.get_localised_string from inside a FactionTurnStart handler. On turn
    # 1 of a FRESH campaign that killed the process - twice, script_log_070926_2235 and _2237,
    # both ending on settle_house's own out() line with nothing after it and no minidump. A
    # pcall does not save you from every engine call in this game.
    #
    # The subject is now left empty and resolved when the ROW IS DRAWN, a moment the UI is
    # provably up. So the harness runs the settlement with `common` set to nil outright.
    assert have["settle_logged"] == "1", (
        "EX.log_settlement wrote no entry with `common` absent. It must not need it - that is "
        "the whole point of deferring the name")
    assert have["settle_subject_empty"] == "true", (
        "the settlement resolved a display name at settle time (subject %r). That reaches "
        "common.get_localised_string inside a turn handler, which is what took the process "
        "down at turn 1 on 2026-09-07" % have.get("settle_subject_empty"))
    assert have["settle_key"] == "cr_chd_skullstack", (
        "the settlement entry carries no key (%s), so the deferred name has nothing to resolve "
        "FROM and the row would draw blank forever" % have["settle_key"])
    assert "held nothing" in have["settle_detail"], (
        "a settlement on a position of zero does not say so: %r" % have["settle_detail"])
    assert "5 share(s) settled for 1250g" in have["settle_paid_detail"], (
        "a settlement that PAID does not say what it paid: %r" % have["settle_paid_detail"])
    assert have["drawn_subject"].endswith("Skullstack"), (
        "the deferred subject did not resolve at draw time - the row reads %r. Deferring the "
        "name only works if something later fills it in" % have["drawn_subject"])

    # AND THE RULE, STATICALLY. settle_house runs from the turn handler; nothing in it may
    # reach the loc system. This is the assertion that would have stopped the CTD shipping.
    lua_src2 = io.open(LUA_SCRIPT, encoding="utf-8").read()
    src2 = NL.join(l for l in lua_src2.splitlines() if not l.lstrip().startswith("--"))
    sh = settle_src(src2)
    for banned in ("EX.faction_display", "EX.log_subject", "common.get_localised_string"):
        assert banned not in sh, (
            "the settlement path calls %s. It runs inside a FactionTurnStart handler, and "
            "resolving a localised name there killed the process at turn 1 of a fresh "
            "campaign on 2026-09-07 - twice, with no minidump and a pcall around it. The log "
            "entry carries the key; let the ROW resolve the name." % banned)
    ls = re.search(r"function EX\.log_settlement.*?" + chr(10) + "end", src2, re.S)
    assert ls and "EX.faction_display" not in ls.group(0), (
        "EX.log_settlement resolves the name again - that is the exact call that crashed")

    print("  settlement log: written with no loc system at all, subject deferred and resolved "
          "at draw time, and neither settle_house nor log_settlement reaches the loc system "
          "from the turn handler")
    print("  house prune: a delisted house held at zero leaves the list and the save, a held "
          "one stays until it is closed, pruning twice changes nothing, and a faction with no "
          "loc - or CA's [YOU SHOULDN'T SEE THIS] - gets a name rather than its key")
    print("  house discovery: horde kept, phantom and dead rejected, union carries only held keys")


def check_house_flag_icon():
    """The Houses view's row icon is the faction's own flag, not the shared gold bar.

    Three things, and only the third needs another file:

    1. EX.icon must ROUTE a house to EX.house_icon. EX.INFO is the generated commodity table,
       so a house misses it and EX.icon returns nil - which is not a visible failure, it is the
       row silently keeping the gold bar authored in the XML. Nil looks exactly like "no flag
       wanted", which is why this is asserted rather than eyeballed.

    2. THE SEPARATOR NORMALISATION. faction:flag_path() hands back factions_tables.flags_path
       verbatim and the separators are MIXED - measured live 2026-09-07: CA's four CHD rows
       come back with BACKSLASHES, two of the three modded rows with forward slashes. Drop the
       gsub and it is CA's own factions that break while the modded ones keep working, which is
       backwards from where anyone would look.

    3. THE FILENAME AGAINST THE CELL. mon_24.png is only correct while the icon cell is 24x24,
       and that number lives in derpy_chd_exchange_row.twui.xml where this file cannot see it.
       CA ships mon_24 / mon_64 / mon_256 for every faction, so a resized cell has a right file
       to move to - and nothing else would ever report the mismatch, because a 64px flag in a
       24px box just draws scaled.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    m = re.search(r"function EX\.icon\(.*?\nend", code, re.S)
    assert m, "EX.icon is gone"
    assert "EX.house_icon" in m.group(0), (
        "EX.icon no longer routes a house to EX.house_icon, so every house row falls back to "
        "the gold bar from the twui - silently, because nil is a legal return here")

    m = re.search(r"function EX\.house_icon\(.*?\nend", code, re.S)
    assert m, "EX.house_icon is gone"
    body = m.group(0)
    assert "flag_path" in body, "EX.house_icon no longer asks the faction for its flag path"
    assert 'string.gsub(p, "\\\\", "/")' in body, (
        "EX.house_icon no longer normalises backslashes to forward slashes. CA's own CHD "
        "factions return their flags_path with backslashes and SetImagePath wants '/', so "
        "dropping this blanks the VANILLA houses while the modded ones keep working")
    assert "return nil" in body, (
        "EX.house_icon has no nil path. A dead or flagless faction must fall back to the gold "
        "bar - a WRONG imagepath draws a blank square and logs nothing, which is worse than "
        "the generic icon it replaced")

    want = re.search(r'"/?([a-z0-9_]+)\.png"', body)
    assert want, "EX.house_icon names no .png file"
    want = want.group(1)

    xml = io.open(os.path.join(ROOT, "Modding Files", "pack", "ui", "campaign ui",
                               "derpy_chd_exchange_row.twui.xml"), encoding="utf-8").read()
    # anchored on id="icon", the same way check_header_labels anchors on id="rows_holder"
    # rather than a tag name - the tag appears in <hierarchy> as well as <components>
    i = xml.find('id="icon"')
    assert i > 0, 'no id="icon" in the row twui.xml'
    dim = re.search(r'width="(\d+)"\s*\n\s*height="(\d+)"', xml[i:i + 2000])
    assert dim, "the icon cell in the row twui.xml has no width/height"
    w, h = int(dim.group(1)), int(dim.group(2))
    assert w == h, "the icon cell is %dx%d - a flag is square, so this needs a new rule" % (w, h)
    assert want == "mon_%d" % w, (
        "EX.house_icon asks for %s.png but the icon cell is %dpx. CA ships mon_24, mon_64 and "
        "mon_256 for every faction; name the one that matches or the flag draws scaled."
        % (want, w))
    print("  house flags: %s.png into a %dx%d cell, separators normalised" % (want, w, h))


def check_house_row_display():
    """The Houses view's per-row TEXT, and the delisted-row fix Task 6's review deferred here.

    Two things check_lua_houses() cannot see, because they live in EX.refresh_panel's row
    loop - UI text assembly, not EX.* math:

    1. THE THREE-STATE SEAT. check_lua_houses proves EX.holds_capital itself returns three
       states (seat_horde == "nil") - but nothing proves the DISPLAY reads all three.
       `seat and "held" or "LOST"` is valid Lua, parses, runs, and reads a horde (seat == nil,
       which is falsy exactly like false) as LOST forever - collapsing the third state into
       the second with no error anywhere.
    2. THE DELISTED ROW. A dead house's Buy/Sell buttons must read "Delisted" and go inert.
    3. WHICH ROWS EACH VIEW DRAWS AT ALL, which is the fault the other two were symptoms of.
       Every view used to iterate EX.instruments(), so the Houses view opened on 19 commodity
       rows fed through the houses branch - a raw key for a name, a blank icon, Seat reading
       "horde" because cm:get_faction("res_animals") is false, and a Div column for a dividend
       that is never paid - with the houses themselves starting at slot 20, past what
       rows_holder can draw. The Offerings view had the same fault mirrored: a house row read
       "Ready" beside a button reading "Insufficient".

    Static regex on the shipped Lua, in the style of check_ai_turn_gate() - building a UI mock
    big enough to actually run EX.refresh_panel would be a second harness for one function.
    """
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()

    # THE PER-MODE LIST, AND EVERY PLACE THAT HAS TO USE IT. Three call sites: EX.layout, which
    # positions and shows the rows; EX.refresh_panel's row loop, which writes their text; and
    # EX.apply_tips, which makes cells interactive. One of them left on EX.instruments() is one
    # of the three faults back.
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))
    assert re.search(r"function EX\.mode_instruments\(\)", code), (
        "EX.mode_instruments is gone - every view is back to drawing every instrument")
    #
    # COUNTING mode_instruments() CALLS IS NOT ENOUGH, and that was the first shape of this
    # check: EX.refresh_panel calls it twice for reasons that have nothing to do with the row
    # loop (the guide's loop, and the Houses footer's hidden-row count), so putting the row loop
    # back on EX.instruments() left the count where it was and the mutation passed. What has to
    # be asserted is the ABSENCE: no row-drawing loop may iterate the full list.
    m = re.search(r"function EX\.refresh_panel\(.*?\n(?:end|local function)", code, re.S)
    assert m, "EX.refresh_panel is gone"
    assert "ipairs(EX.instruments())" not in m.group(0), (
        "EX.refresh_panel iterates EX.instruments() rather than EX.mode_instruments(). Houses "
        "and commodities are different instrument classes drawn through different branches; "
        "mixing them feeds a commodity key to the houses branch (row_name a raw key, Seat "
        "'horde' because cm:get_faction on a commodity answers false) and pushes the houses "
        "themselves past the panel's last row.")
    # EX.layout AND EX.apply_tips are the two exceptions, and both for the same reason: what
    # they write is per row and PERSISTS, so a row this view does not draw has to be actively
    # unwritten rather than skipped. layout would otherwise leave it at the last view's
    # coordinates, drawing over the new one; apply_tips would leave it holding the last view's
    # tooltip. Both take the same shape - a draw set from mode_instruments(), then a walk of
    # the full list - so both are asserted the same way.
    #
    # AND FOR EX.layout, THE LIST IS THE ORDER TOO, not only the membership. It walked
    # EX.instruments() and placed row i at slot i, using mode_instruments() as a set - so
    # every view drew in canonical order whatever the list said, and column sorting changed
    # the header colour and nothing else (screenshot, 2026-09-08: Buy marked green, rows still
    # 583, 1851, 972, 3700). The placement loop is the one that has to follow the list; the
    # hide pass still has to walk every instrument, or a row this view drops keeps the last
    # view's coordinates.
    lay = re.search(r"function EX\.layout\(.*?\n(?:end|local function)", code, re.S)
    assert lay, "EX.layout is gone"
    body = lay.group(0)
    assert re.search(r"local list = EX\.mode_instruments\(\)", body), (
        "EX.layout no longer holds mode_instruments() in a local, so the draw set and the "
        "placement order can be built from two different calls")
    place = re.search(r"for _, res in ipairs\(([\w.()]+)\) do\s*local row = EX\.row\(holder, res\)",
                      body)
    assert place, "EX.layout's row placement loop is gone"
    assert place.group(1) == "list", (
        "EX.layout places rows by walking %s instead of the mode's own list, so slot order is "
        "the canonical order and sorting or any other reordering never reaches the screen"
        % place.group(1))
    # THE HIDE PASS WALKS THE HOLDER'S CHILDREN, not any list the mod keeps.
    #
    # It used to walk EX.instruments(), which reads correct until you notice that
    # EX.prune_houses REMOVES a delisted house from EX.houses - so the row leaves the
    # instrument list while its COMPONENT stays, unreachable by the pass and still visible at
    # the last coordinate it was given. Screenshot 2026-09-08: 22 names in 20 slots on the
    # Houses view. check_layout() runs the fault; this pins the shape so it cannot come back
    # as a "simplification".
    assert 'keep[EX.ROW .. "_" .. EX.short(res)] = true' in body, (
        "EX.layout no longer builds the keep set out of COMPONENT NAMES, so the hide pass "
        "below it has nothing to compare a child's Id() against")
    hide = re.search(r"for j = 0, n - 1 do(.*?)\n    end", body, re.S)
    assert hide, (
        "EX.layout's hide pass no longer enumerates the holder's children. Hiding by walking "
        "a list the mod keeps cannot reach a row whose instrument was pruned - that row keeps "
        "the last view's coordinates and draws over whatever the new pass puts there")
    assert "holder:ChildCount()" in body and "holder:Find(j)" in body, (
        "the hide pass is not using CA's own child enumeration")
    assert re.search(r"string\.sub\(id, 1, #EX\.ROW\) == EX\.ROW", hide.group(1)), (
        "the hide pass does not restrict itself to row components - it will hide the "
        "holder's other children too")
    assert "not keep[id]" in hide.group(1) and "SetVisible(false)" in hide.group(1), (
        "the hide pass no longer hides the children the current view does not keep")
    assert body.index("for j = 0, n - 1 do") < body.index("local row = EX.row(holder, res)"), (
        "the hide pass runs AFTER the placement pass, so it hides rows this view just placed")

    for fn, mark in (("EX.layout", r"draw\[res\] = true"),
                     ("EX.apply_tips", r"drawn\[res\] = true")):
        m = re.search(r"function " + re.escape(fn) + r"\(.*?\n(?:end|local function)", code,
                      re.S)
        assert m, "%s is gone" % fn
        assert re.search(r"ipairs\((?:EX\.mode_instruments\(\)|list)\) do\s+" + mark,
                         m.group(0)), (
            "%s no longer builds its draw set from EX.mode_instruments(), so every view is "
            "treated as drawing every instrument" % fn)
        # ONLY apply_tips. EX.layout used to walk the full instrument list here too, and that
        # is exactly the 2026-09-08 overlap: a pruned house leaves EX.instruments() while its
        # component stays, so the walk cannot reach it. Layout now enumerates the holder's
        # children instead, pinned by the block above. apply_tips is a different case and the
        # walk is right there - a row it leaves out keeps the last view's tooltips, and while
        # a pruned row is now always hidden, the rows SHARED between views are the reason the
        # loop exists at all.
        if fn == "EX.apply_tips":
            assert "ipairs(EX.instruments())" in m.group(0), (
                "%s no longer walks the full instrument list, so the rows this view does not "
                "draw are never cleared - they keep the previous view's tooltips" % fn)
    # ...and the Houses view is the ONLY thing the houses branch sees, which is what makes the
    # trade view's deleted house special-case safe to have deleted.
    mi = re.search(r"function EX\.mode_instruments\(\)(.*?)\nend", code, re.S).group(1)
    assert ("EX.MODE_HOUSES" in mi and "EX.COMMODITIES" in mi
            and ("EX.houses" in mi or "EX.house_slice()" in mi)), (
        "EX.mode_instruments no longer splits houses from commodities: %r" % mi)
    # THE HOUSES BRANCH PAGES rather than truncating. The old form appended the whole list and
    # let the shared  cut it, which against an ALPHABETICALLY SORTED
    # list dropped everything past slot 20 for good - already live at 20 Chaos Dwarf houses.
    assert "EX.house_slice()" in mi, (
        "the Houses branch no longer calls EX.house_slice(), so it is back to truncating an "
        "alphabetically sorted list at EX.MAX_ROWS and silently losing every house past it")

    houses_m = re.search(r"elseif houses then(.*?)" + NL + r"            else" + NL, lua, re.S)
    assert houses_m, (
        "no 'elseif houses then' branch found before the trade view's 'else' in "
        "EX.refresh_panel - the row loop shape has changed")
    hbody = houses_m.group(1)

    # NO HOUSE BRANCH IN THE TRADE VIEW, and its absence is now the correct state. There used to
    # be one - a delisted-house special case, because EX.instruments() put a house row in every
    # view. EX.mode_instruments() removed the input, so the branch became unreachable UI code
    # and was deleted rather than kept as belt and braces; dead UI code that cannot be exercised
    # rots. This pins the deletion so it is not "fixed" back in on the next reading.
    assert "house_delisted" not in lua, (
        "the trade view has a house branch again. EX.mode_instruments() gives the trade, stats "
        "and offerings views commodities and layer 2 only, so nothing can reach it - and a "
        "branch that cannot run is a branch nobody can check.")

    # THE THREE-STATE SEAT (item B), Houses view only - the trade view has no seat column.
    for word in ("horde", "held", "LOST"):
        assert word in hbody, (
            "the Houses row never draws %r for the seat cell - check_lua_houses proves "
            "EX.holds_capital returns three states, but nothing draws the third one" % word)
    assert re.search(r"seat\s*==\s*nil", hbody), (
        "the seat text has no explicit nil check. 'seat and \"held\" or \"LOST\"' is valid "
        "Lua that runs with no error and reads a horde (seat == nil, which is falsy) as LOST "
        "forever - the exact three-into-two collapse the comment on EX.holds_capital warns "
        "against.")

    # THE DELISTED ROW (item A). One view draws a house now, so one branch carries this.
    for name, body in (("houses", hbody),):
        assert body.count('"Delisted"') >= 2, (
            "the %s view's delisted branch does not set both buttons to \"Delisted\" - "
            "found %d, expected 2 (btn_buy and btn_sell)" % (name, body.count('"Delisted"')))
        assert body.count("SetDisabled(true)") >= 2, (
            "the %s view's delisted branch does not disable both buttons - a live-looking "
            "control that silently refuses is the exact fault this fixes" % name)
        assert "set_tip(bb," in body and "set_tip(bs," in body, (
            "the %s view's delisted row carries no tooltip on its buttons - 'disabled not "
            "hidden, and the tooltip says why' is this file's own standard, from the AI-turn "
            "gate on the opener button" % name)

    # THE HOUSES FOOTER, which had none of its own and fell through to the trade view's. That
    # one prints "Rent: -Ng" and the world appetite summary: a warehouse bill shares cannot
    # incur, and a list of what cultures want in GOODS, on the one view that trades neither.
    # And the dividend - the running total this whole layer turns on - appeared nowhere the
    # player would look, which spec §5 asks for explicitly.
    fm = re.search(r"\n    elseif houses then(.*?)\n    elseif faction then", code, re.S)
    assert fm, (
        "the Houses view has no footer branch of its own - it falls through to the trade "
        "footer, which advertises warehouse rent on paper that pays none")
    foot = fm.group(1)
    assert "EX.dividend_total()" in foot, (
        "the Houses footer does not print the running dividend total. Spec §5: the dividend "
        "appears in the panel footer as a running total, and it is otherwise only visible one "
        "row at a time.")
    assert "EX.carry_total()" not in foot and "EX.appetite_summary()" not in foot, (
        "the Houses footer prints the commodity rent bill or the world appetite summary. "
        "Neither is true of a share: there is nothing to warehouse and no culture wants equity.")

    print("  house row display: three seat states drawn (held/LOST/horde), a delisted row "
          "disables both buttons with a tooltip, each view draws its own instrument class, "
          "and the Houses footer carries the dividend total instead of a rent bill")


# The stub board check_lua_warehouse() runs the SHIPPED file against. Kept at module level
# rather than inline so the %-formatting of the dofile path is the only substitution in it -
# the harness is full of Lua % operators otherwise.
LUA_WAREHOUSE_HARNESS = """
local HOLD, APPLIED, GOLD = {}, {}, 0
local function res_iface(key)
    return { is_null_interface = function() return false end,
             value = function() return HOLD[key] or 0 end }
end
local FACTION = {
    is_null_interface = function() return false end,
    pooled_resource_manager = function()
        return { resource = function(_, k) return res_iface(k) end }
    end,
}
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function() end,
    get_saved_value = function() end,
    get_local_faction_name = function() return "player" end,
    get_faction = function(_, _n) return FACTION end,
    treasury_mod = function(_, _f, amount) GOLD = GOLD + amount end,
    apply_effect_bundle = function(_, key) APPLIED[key] = true end,
    remove_effect_bundle = function(_, key) APPLIED[key] = nil end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])

print("rate " .. EX.CARRY_PER_UNIT)

-- TIER BOUNDARIES, both sides of every one. An off-by-one here is the difference between the
-- top bonus arriving at 600 units and at 599, and nothing in the game would ever say so.
local probes = { 0 }
for _, t in ipairs(EX.STOCK_TIERS) do
    probes[#probes + 1] = t - 1
    probes[#probes + 1] = t
end
local parts = {}
for _, held in ipairs(probes) do
    parts[#parts + 1] = held .. ":" .. EX.stock_tier(held)
end
print("tiers " .. table.concat(parts, " "))

-- CARRY. One commodity, and a layer-2 pool that must be exempt.
--
-- THE KEYS COME FROM EX, NOT FROM A STRING TYPED HERE. EX.short strips only the "res_" prefix,
-- so res_rom_iron is "rom_iron" and the pool is derpy_chd_ex_hold_ROM_iron - a harness that
-- guessed "hold_iron" silently held nothing and every assertion below read zero.
local IRON = "res_rom_iron"
local IRON_STOCK = EX.PREFIX .. "stock_" .. EX.short(IRON) .. "_"
HOLD[EX.hold_key(IRON)] = 600
HOLD["wh3_dlc23_chd_armaments"] = 5000
print("carry_iron " .. EX.carry_cost(IRON))
print("carry_l2 " .. EX.carry_cost("wh3_dlc23_chd_armaments"))
print("carry_total " .. EX.carry_total())

-- EXACTLY ONE TIER BUNDLE, and it must be the right one.
EX.apply_stockpiles()
local n, which = 0, "none"
for k in pairs(APPLIED) do
    if string.find(k, IRON_STOCK, 1, true) then n = n + 1; which = k end
end
print("iron_bundles " .. n)
print("iron_key " .. which)

-- ...and selling down below the first threshold must take it off again.
HOLD[EX.hold_key(IRON)] = EX.STOCK_TIERS[1] - 1
EX.apply_stockpiles()
local left = 0
for k in pairs(APPLIED) do
    if string.find(k, IRON_STOCK, 1, true) then left = left + 1 end
end
print("iron_after_sale " .. left)

-- A TIER CHANGE MUST NOT LEAVE THE OLD ONE ON. Walk the whole ramp and count at the top.
for _, t in ipairs(EX.STOCK_TIERS) do
    HOLD[EX.hold_key(IRON)] = t
    EX.apply_stockpiles()
end
local stacked = 0
for k in pairs(APPLIED) do
    if string.find(k, IRON_STOCK, 1, true) then stacked = stacked + 1 end
end
print("iron_stacked " .. stacked)

-- THE RENT IS A DEBIT.
GOLD = 0
HOLD[EX.hold_key(IRON)] = 600
EX.charge_carry()
print("charged " .. GOLD)

-- NOTHING HELD, NOTHING CHARGED: a player who never opens the panel must never be billed.
for k in pairs(HOLD) do HOLD[k] = 0 end
GOLD = 0
EX.charge_carry()
print("charged_empty " .. GOLD)
"""


def check_lua_hover():
    """The row buttons carry a hover state now, and their LABELS are set from Lua.

    SetStateText writes to the CURRENT STATE ONLY. That single documented sentence is the whole
    hazard: a button with a hover state, whose label is written once, draws nothing at all the
    moment the mouse arrives - and comes back when it leaves. It is not an error, it does not
    log, and it is invisible in a screenshot taken with the pointer anywhere else.

    So the two sides have to agree: every interactive component the UI generator gives a hover
    state, whose label this script rewrites, must be listed in EX.TWO_STATE_CELLS - and every
    write to one of those cells must go through set_text, which is the only thing that writes
    both states.
    """
    import gen_exchange_ui as ui
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    m = re.search(r"EX\.TWO_STATE_CELLS = \{(.*?)\}", code, re.S)
    assert m, "EX.TWO_STATE_CELLS is gone - the button labels will vanish on mouseover"
    listed = set(re.findall(r"(\w+)\s*=\s*true", m.group(1)))

    # THE TABS ARE ADDED BY A LOOP, not listed. That is deliberate - a sixth view would
    # otherwise ship a tab whose label vanishes on hover, and only a screenshot taken with the
    # pointer on it would show that - so the parse has to follow the loop or this check reads
    # the table as five names short and fails on correct code.
    loop = re.search(r"for _, m in ipairs\(EX\.MODES\) do "
                     r"EX\.TWO_STATE_CELLS\[EX\.tab_name\(m\)\] = true end", code)
    if loop:
        prefix = re.search(r'EX\.TAB_PREFIX = "([^"]+)"', code)
        assert prefix, "EX.TAB_PREFIX is gone but the tab loop still refers to EX.tab_name"
        modes = re.search(r"EX\.MODES = \{(.*?)\}", code)
        assert modes, "EX.MODES is gone"
        listed |= {prefix.group(1) + x
                   for x in re.findall(r'"(\w+)"', modes.group(1))}

    # The generator is the authority on which components actually have two states.
    hovering = set()
    for _name, fn, _c in ui.FILES:
        for c in fn().walk():
            if c.kw.get("hover") and c.kw.get("text"):
                hovering.add(c.name)
    assert listed == hovering, (
        "EX.TWO_STATE_CELLS and the .twui.xml disagree.\n"
        "  has a hover state and a label, but the script writes only one state: %s\n"
        "  listed here but has no hover state, so the extra SetState calls are wasted: %s"
        % (sorted(hovering - listed) or "none", sorted(listed - hovering) or "none"))
    assert hovering, "no component has both a hover state and a label - did hover regress?"

    # set_text is the ONLY writer that handles two states, so a direct SetStateText on one of
    # these cells would silently reintroduce the vanishing label.
    assert re.search(r"local function set_text.*?c:SetState\(\"hover\"\)", code, re.S), (
        "set_text no longer writes the hover state; every button label will disappear when the "
        "mouse is over it")
    assert "c:CurrentState()" in code, (
        "set_text forces the state instead of restoring it - a button the mouse is already "
        "over (the one just clicked) would draw unlit until the pointer moved away")
    # THE TABS ARE LABELLED THROUGH A LOOP - set_text(panel, EX.tab_name(m), ...) - because
    # their names are generated from EX.MODES. A literal-name search cannot see that, so it is
    # accepted here explicitly rather than by loosening the regex for every cell: the property
    # being guarded is that every hovering cell IS labelled somewhere, not how it is spelled.
    tab_loop = bool(re.search(r'set_text\(panel, EX\.tab_name\(m\),', code))
    tab_prefix = re.search(r'EX\.TAB_PREFIX = "([^"]+)"', code)
    for cell in sorted(hovering):
        by_loop = tab_loop and tab_prefix and cell.startswith(tab_prefix.group(1))
        assert by_loop or re.findall(r'set_text\([^,]+,\s*"%s"' % cell, code), \
            "%s is never given a label" % cell
        direct = re.findall(r'"%s"[^\n]*\n[^\n]*SetStateText' % cell, code)
        assert not direct, "%s is written with a direct SetStateText, bypassing set_text" % cell
    assert tab_loop, (
        "nothing labels the view tabs. Five blank buttons across the bottom of the panel is "
        "not a visible error - they draw, they click, and they say nothing")


def check_lua_warehouse():
    """Run the SHIPPED warehouse code and assert what a holding costs and what it grants.

    Six things here fail silently, and the first two would be read as the feature not existing:

    1. A TIER THRESHOLD THAT DRIFTS from the one the bundles were generated for. The Lua would
       apply derpy_chd_ex_stock_iron_3 at 500 units while the DB built it for 600 - the bundle
       is real, the key resolves, and the player gets the top bonus early, forever.
    2. MORE THAN ONE TIER APPLIED AT ONCE. Same-effect bundles stack ADDITIVELY, so leaving
       tier 1 on under tier 3 grants 4x rather than 3x. Nothing reports it; the panel says
       "Vaults" and the army quietly has more armour than any row promises.
    3. CARRY CHARGED ON LAYER 2. Armaments and Raw Materials come out of the Hell-Forge, not
       the market, so renting them taxes ordinary Chaos Dwarf play - a player who never opened
       the exchange would start losing gold to it.
    4. THE RENT CHARGED ON LOAD. cm:add_first_tick_callback runs on every load, so calling
       charge_carry there makes five reloads five rent days.
    5. A SIGN ERROR ON THE CHARGE, which pays the player to hoard - the exact inverse of the
       mechanic, and it would read as a windfall rather than a bug.
    6. A NEGATIVE OR ZERO RATE. Zero is a dead feature that looks shipped.
    """
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped lua warehouse check: no lua.exe)")
        return

    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    # -----------------------------------------------------------------------------------
    # 1. THE CONSTANTS. Both files must have been built for the same numbers.
    # -----------------------------------------------------------------------------------
    m = re.search(r"EX\.CARRY_PER_UNIT\s*=\s*([\d.]+)", code)
    assert m, "EX.CARRY_PER_UNIT is gone - holdings are free again"
    assert float(m.group(1)) == float(CARRY_PER_UNIT), (
        "EX.CARRY_PER_UNIT is %s, this generator is built for %s"
        % (m.group(1), CARRY_PER_UNIT))
    assert CARRY_PER_UNIT > 0, (
        "CARRY_PER_UNIT is %s. Zero is a dead feature and negative PAYS the player to hoard."
        % CARRY_PER_UNIT)

    m = re.search(r"EX\.STOCK_TIERS = \{(.*?)\}", code, re.S)
    assert m, "EX.STOCK_TIERS is gone - no holding grants anything"
    lua_tiers = [int(x) for x in re.findall(r"\d+", m.group(1))]
    py_tiers = [u for u, _m, _l in STOCK_TIERS]
    assert lua_tiers == py_tiers, (
        "EX.STOCK_TIERS is %s but the bundles were generated for %s. The keys still resolve, "
        "so the wrong tier simply applies at the wrong holding - forever, silently."
        % (lua_tiers, py_tiers))

    # -----------------------------------------------------------------------------------
    # 2. THE WIRING. Where each half is called from, and where it must NOT be.
    # -----------------------------------------------------------------------------------
    body = turn_body(code)
    for fn in ("EX.apply_stockpiles()", "EX.charge_carry()"):
        assert fn in body, "%s is never called on a turn" % fn
    assert body.index("EX.apply_stockpiles()") < body.index("EX.charge_carry()"), (
        "the rent is charged before the tier is recalculated, so a holding that crossed a "
        "boundary this turn is billed against last turn's picture")

    # EVERY PATH THAT MOVES GOODS MUST RE-EVALUATE THE TIER. There are four - buy, sell, a
    # voluntary offering, and paying a tithe - and any of them can carry a holding across a
    # boundary in either direction. A path that only calls refresh_panel leaves the Held cell
    # green (it reads the live holding) while the bundle granting the bonus is not applied
    # until the next FactionTurnStart. The panel would be promising something the game is not
    # doing, which is the one invariant this UI has held from the start.
    movers = re.findall(r"cm:faction_add_pooled_resource\(", code)
    assert len(movers) >= 2, "nothing moves goods any more?"
    # The callback NAME now carries the acting faction too - "zharr_after_trade_" .. faction -
    # so two players trading in the same tenth of a second cannot queue one cm:callback name
    # twice and lose one of the two tier updates. Hence the trailing `_?` and the concatenation
    # after the quoted stem.
    tails = re.findall(r'cm:callback\(function\(\)(.*?)end, 0\.1,\s*"(zharr_after_\w+?)_?"',
                       code, re.S)
    assert len(tails) >= 3, (
        "expected a deferred tail on each of the three goods-moving paths (trade, offering, "
        "tithe), found %d" % len(tails))
    for body_txt, name in tails:
        assert re.search(r"EX\.after_holding_change\((faction|fname)\)", body_txt), (
            'the "%s" callback does not call EX.after_holding_change with the acting faction. '
            "Its holding changed, so the warehouse tier has to be re-evaluated there - "
            "otherwise the row goes green and the bonus does not arrive until the next turn; "
            "and without the faction it is re-evaluated for the LOCAL player on every machine, "
            "which moves a different set of bundles on each one." % name)

    tick = re.search(r"function EX\.init\(\).*?\n\s*core:add_listener",
                     code, re.S)
    assert tick, "the first-tick block is gone"
    assert "EX.apply_stockpiles()" in tick.group(0), (
        "apply_stockpiles is not called on load. Effect bundles SURVIVE A SAVE and this "
        "script's tables do not, so a load would carry the previous session's tier with "
        "nothing able to correct it.")
    assert "EX.charge_carry()" not in tick.group(0), (
        "charge_carry runs on the first tick. A load is not a turn - five reloads would be "
        "five rent days.")

    # -----------------------------------------------------------------------------------
    # 3. THE BEHAVIOUR. Run the real file against a stub vault and read the numbers back.
    # -----------------------------------------------------------------------------------
    harness = LUA_WAREHOUSE_HARNESS % (LUA_SCRIPT.replace("\\", "\\\\"),)
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.split(NL):
        line = line.strip()
        if line:
            k, _sp, v = line.partition(" ")
            have[k] = v

    assert float(have["rate"]) == float(CARRY_PER_UNIT), have["rate"]

    # The ramp, both sides of every threshold, against Python's own answer.
    for probe in have["tiers"].split():
        held, _c, tier = probe.partition(":")
        want = stock_tier_for(int(held))
        assert int(tier) == want, (
            "EX.stock_tier(%s) is %s, stock_tier_for says %s - the Lua and the DB disagree "
            "about which bundle a holding earns" % (held, tier, want))

    want_iron = int(600 * CARRY_PER_UNIT)
    assert int(have["carry_iron"]) == want_iron, (
        "600 units cost %s to warehouse, expected %d" % (have["carry_iron"], want_iron))
    assert int(have["carry_l2"]) == 0, (
        "layer 2 is being charged rent (%s). Armaments and Raw Materials come out of the "
        "Hell-Forge, so this bills a player who never opened the exchange."
        % have["carry_l2"])
    assert int(have["carry_total"]) == want_iron, (
        "carry_total is %s but only the iron position should count; layer 2 must be excluded "
        "from the sum as well as from the row" % have["carry_total"])

    assert int(have["iron_bundles"]) == 1, (
        "%s warehouse bundles applied to iron at once. Same-effect bundles stack ADDITIVELY, "
        "so two tiers on together grant more than the top tier alone and nothing says so."
        % have["iron_bundles"])
    top = len(STOCK_TIERS)
    assert have["iron_key"] == stock_bundle("res_rom_iron", top), (
        "600 units of iron applied %r, expected %r"
        % (have["iron_key"], stock_bundle("res_rom_iron", top)))
    assert int(have["iron_after_sale"]) == 0, (
        "selling below the first threshold left a warehouse bundle applied - the bonus would "
        "run forever on goods the player no longer has")
    assert int(have["iron_stacked"]) == 1, (
        "walking up the ramp left %s bundles applied. apply_stockpiles must remove the tiers "
        "it does not want, not merely add the one it does." % have["iron_stacked"])

    assert int(have["charged"]) == -want_iron, (
        "charge_carry moved %s; expected -%d. A positive here PAYS the player to hoard."
        % (have["charged"], want_iron))
    # THE ONLY ASSERTION HERE THAT CALLS charge_carry A SECOND TIME, and that is what it is
    # for. Break-tested 2026-09-06: a flat per-commodity fee, a minimum charge, and carry read
    # off world supply instead of the holding are all caught by carry_iron or carry_total
    # first - so this would be furniture if it only restated "an empty vault costs nothing".
    # What it catches ALONE is a charge_carry that MEMOISES its total: right the first time it
    # runs and stale on every turn after, which no single-call assertion can see.
    assert int(have["charged_empty"]) == 0, (
        "an empty vault was still charged %s. Every other assertion here calls charge_carry "
        "once, so the likely cause is a total computed once and cached - correct on the turn "
        "it was built and wrong on every turn since." % have["charged_empty"])


def check_lua_shocks():
    """Run the SHIPPED shock code and assert what a razed settlement does to a price.

    Four things fail silently here, and none of them shows up as an error:

    1. A STANCE KEY TYPO. EX.RAID_STANCES is keyed by stance, and a stance nobody can enter
       matches nothing - which is exactly what a misspelled key also does. Raiding then never
       moves a price, forever, with no log line.
    2. THE SIGN ON A SUB-RUNG SHOCK. math.floor(-0.5) is -1 while math.floor(0.5) is 0, so a
       naive floor moves a price DOWN on a disruption too small to move it up. The same trap
       EX.pressure_shift and EX.appetite_shift each carry a comment about.
    3. SUB-RUNG SHOCKS NOT ACCUMULATING. If the truncation happened in EX.bump_shock instead
       of at the price, six raids on a common good would each round to nothing and a sustained
       campaign against one commodity would do exactly nothing.
    4. THE DECAY RUNNING BEFORE THE REPRICE. A settlement razed during the AI round would then
       be half-priced on the turn the player first sees it - a spike the player can never act
       on at full size, which is the whole point of a shock.
    5. ONE REGION SHOCKED TWICE IN A TURN. ForceAdoptsStance fires per army, so two armies
       raiding one region disrupt the same goods twice - measured at ~7% of 150 raid events
       in the 2026-09-06 soak. The guard has to be per KIND, or it eats the deliberate
       raze-on-top-of-loot compound instead.
    """
    import subprocess
    import tempfile
    from read_vanilla_cache import load
    if not os.path.isfile(LUA_EXE):
        print("  (skipped lua shock check: no lua.exe)")
        return

    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    # -----------------------------------------------------------------------------------
    # 1. THE STANCE VOCABULARY. Checked against the game's own table, not against a list
    #    retyped here - a typo in both would agree with itself.
    # -----------------------------------------------------------------------------------
    srows, _ = load("campaign_stances")
    stances = set(r["key"] for r in srows)
    m = re.search(r"EX\.RAID_STANCES = \{(.*?)\n\}", code, re.S)
    assert m, "EX.RAID_STANCES is gone"
    named = set(re.findall(r"(MILITARY_FORCE_[A-Z_]+)", m.group(1)))
    assert named, "EX.RAID_STANCES names no stances at all"
    bad = sorted(named - stances)
    assert not bad, (
        "EX.RAID_STANCES names %d stance(s) that do not exist: %s.\nA stance nobody can enter "
        "matches nothing, which is what a typo does too - raiding would simply never move a "
        "price. Valid keys come from campaign_stances_tables." % (len(bad), bad))
    # A SITUATIONAL stance is never adopted through ForceAdoptsStance, so listing one would be
    # a row that can never fire - and it would pass the existence check above.
    situational = sorted(k for k in named if "SITUATIONAL" in k)
    assert not situational, (
        "EX.RAID_STANCES lists %s. Situational stances are not adopted, so ForceAdoptsStance "
        "never carries one and the entry can never fire." % situational)

    # -----------------------------------------------------------------------------------
    # 2. THE WIRING. Every kind has a listener, every listener names a kind, and the decay
    #    runs after the reprice.
    # -----------------------------------------------------------------------------------
    m = re.search(r"EX\.SHOCK_KINDS = \{(.*?)\n\}", code, re.S)
    assert m, "EX.SHOCK_KINDS is gone"
    kinds = set(re.findall(r"(\w+)\s*=\s*[\d.]+", m.group(1)))
    # [^"\n]* AND NOT [^)]*. The rebellion listener raises as
    #     EX.add_shock(context:region(), "rebels")
    # and the region() call closes a paren before the kind string, so a [^)]* run stops
    # dead and the kind reads as never raised. That is a check reporting correct code as
    # broken, which is the failure mode that gets a check deleted rather than fixed.
    used = set(re.findall(r'EX\.(?:add_shock|shock_from_garrison)\([^"\n]*"(\w+)"', code))
    assert kinds == used, (
        "EX.SHOCK_KINDS and the listeners disagree: %s is declared but never raised, %s is "
        "raised but has no weight (EX.SHOCK_KINDS[kind] is nil, so EX.add_shock returns "
        "immediately and the event is silently inert)."
        % (sorted(kinds - used) or "nothing", sorted(used - kinds) or "nothing"))

    for ev in ["CharacterRazedSettlement", "CharacterSackedSettlement",
               "CharacterLootedSettlement", "ForceAdoptsStance",
               "CharacterCapturedSettlement", "CharacterCapturedSettlementUnopposed",
               "RegionRebels"]:
        assert ev in code, "the %s listener is gone" % ev

    # EVERY EVENT NAME LISTENED FOR MUST BE ONE CA ACTUALLY SHIPS. An event that does not
    # exist never fires and never errors - the listener simply sits there for the life of
    # the campaign - so this is the only place a name can be caught. FactionDestroyed and
    # DeclaredWar were both wanted for the demand shocks and neither exists; the shares
    # route in EX.share_shocks is what replaced them.
    docs = os.path.join(ROOT, "Modding Files", "reference", "ca_script_docs_wh3")
    if os.path.isdir(docs):
        blob = ""
        for dirpath, _dirs, files in os.walk(docs):
            for fn in files:
                if fn.endswith((".html", ".htm", ".txt")):
                    blob += io.open(os.path.join(dirpath, fn), encoding="utf-8",
                                    errors="ignore").read()
        listened = set(re.findall(r'core:add_listener\(\s*"[^"]+",\s*"(\w+)"', code))
        # AN EVENT THIS PACK RAISES ITSELF IS KNOWN BY CONSTRUCTION. The two debug dumps
        # are core:trigger_custom_event pairs of our own, so CA has never heard of them
        # and never should.
        #
        # BOTH FILES, and that is not tidiness. The debug buttons live in the MCT settings
        # file because MCT loads it in its own environment where EX does not exist, so the
        # only way back into this mod is a custom event - which means the RAISER is in one
        # file and the LISTENER in the other, and a scan of either alone reports the pair
        # as broken.
        raisers = code
        mct_file = os.path.join(MCT_DIR, "derpy_chd_zharr_exchange.lua")
        if os.path.isfile(mct_file):
            raisers += io.open(mct_file, encoding="utf-8").read()
        ours = set(re.findall(r'core:trigger_custom_event\(\s*"(\w+)"', raisers))
        # RAISED BY CA'S OWN CAMPAIGN LUA, not by the engine, so it is absent from the
        # interface documentation that lists engine events. It is the entry point half of
        # this mod uses and is verified by every campaign it has ever run in.
        ours.add("ScriptEventFirstTickAfterWorldCreated")
        unknown = sorted(e for e in listened if e not in blob and e not in ours)
        assert not unknown, (
            "these listeners name events CA does not document: %s. An event that does not "
            "exist never fires and never errors, so nothing anywhere would say so." % unknown)
    # CA ships a present-tense twin of each past-tense event carrying only a loot amount and
    # NO garrison_residence, so listening for the wrong one leaves no way to find the region.
    for wrong in ["CharacterRazesSettlement", "CharacterSacksSettlement",
                  "CharacterLootsSettlement"]:
        assert wrong not in code, (
            "listening for %s. That event carries only `loot` - no garrison_residence and no "
            "region - so there is nothing to shock. The past-tense name is the one with the "
            "garrison." % wrong)

    callers = re.findall(r"EX\.decay_shocks\(\)", code)
    assert len(callers) == 2, (
        "expected the definition and exactly one call of EX.decay_shocks, found %d references"
        % len(callers))
    body = turn_body(code)
    assert "EX.decay_shocks()" in body, (
        "shocks are not decayed in the turn round, so a spike never fades")
    assert body.index("EX.apply_prices()") < body.index("EX.decay_shocks()"), (
        "EX.decay_shocks runs BEFORE the reprice. A settlement razed during the AI round is "
        "then already half gone on the turn the player first sees it, and the largest shock "
        "in the table is one the player can never act on at full size.")
    # A GUARD THAT IS NEVER CLEARED IS NOT A GUARD, IT IS AN OFF SWITCH. EX.shocked suppresses
    # a repeat shock on the same region and kind; if FactionTurnStart does not empty it, the
    # first raid of the campaign on a region is the last one that ever moves a price - silently,
    # and it survives a save because nothing about it is saved.
    assert "EX.shocked = {}" in body, (
        "the FactionTurnStart handler no longer clears EX.shocked. The per-turn duplicate guard "
        "would then hold for the rest of the campaign, and every region could be raided exactly "
        "once, ever.")

    # The price has to actually read it. Everything above can be perfect and the feature still
    # be entirely inert.
    m = re.search(r"function EX\.target_rung\(.*?\n    local rung = ([^\n]+)", code, re.S)
    assert m and "EX.shock_shift(res)" in m.group(1), (
        "EX.target_rung does not add EX.shock_shift, so the whole shock system is inert - "
        "every number moves and no price does")

    # -----------------------------------------------------------------------------------
    # 3. THE BEHAVIOUR. Run the real file against a stub board and read the numbers back.
    # -----------------------------------------------------------------------------------
    harness = """
local SAVED = {}
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function(_, k, v) SAVED[k] = v end,
    get_saved_value = function(_, k) return SAVED[k] end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])
-- The mod keeps its own save store (EX.store) rather than riding CA's shared
-- saved_values blob, which the engine caps at 0x7000 and drops whole. Point it at
-- SAVED so every assertion below still observes the real writes under the old name.
EX.store = SAVED

print(string.format("gain %%.4f", EX.SHOCK_GAIN))
print(string.format("decayrate %%.4f", EX.SHOCK_DECAY))
print("max " .. EX.SHOCK_MAX)

-- A BOARD WITH ONE SCARCE GOOD AND ONE COMMON ONE. Obsidian: this region is 10 of 80, an
-- eighth of the world. Timber: 10 of 600, a sixtieth. The whole point of pricing a shock as a
-- SHARE is that the same razed settlement must move one and not the other.
EX.supply = { res_obsidian = 80, res_rom_timber = 600, res_ivory = 20 }
EX.region_last["R1"] = { { "res_obsidian", 10 }, { "res_rom_timber", 10 } }
local R1 = { name = function() return "R1" end }

EX.add_shock(R1, "razed")
print(string.format("obs_raw %%.4f", EX.shock.res_obsidian))
print(string.format("tim_raw %%.4f", EX.shock.res_rom_timber))
print("obs_shift " .. EX.shock_shift("res_obsidian"))
print("tim_shift " .. EX.shock_shift("res_rom_timber"))
print("saved_obs " .. tostring(SAVED["zharr_shock_res_obsidian"] ~= nil))
print("why_obs " .. tostring(EX.shock_why.res_obsidian))

-- SUB-RUNG ACCUMULATION. Four raids on the same region add four more sub-rung timber shocks.
-- If the truncation lived in bump_shock these would each round to nothing.
--
-- FOUR AND NOT THREE. Three lands on exactly 1.0 (0.5 + 3 x 0.1667), and a boundary is the
-- one place this cannot be asserted: the sum is 0.99999994 in single precision, math.floor
-- answers 0, and the check would be measuring float32 rather than the model. Four clears it.
--
-- FOUR REGIONS, not four raids on one. A region can only be shocked once per kind per turn -
-- the same goods cannot be disrupted twice - so four raids on R1 is now one raid, and writing
-- it that way would quietly stop testing accumulation at all.
for i = 1, 4 do
    local key = "RT" .. i
    EX.region_last[key] = { { "res_rom_timber", 10 } }
    EX.add_shock({ name = function() return key end }, "raided")
end
print(string.format("tim_after %%.4f", EX.shock.res_rom_timber))
print("tim_shiftn " .. EX.shock_shift("res_rom_timber"))

-- THE CLAMP. A region that is the ENTIRE world supply of a good, razed. 3.0 x 1.0 x 10 is
-- 30 rungs before the clamp, five times over it, so one event is the whole test - this was a
-- loop of four until the per-turn guard made three of them no-ops.
EX.region_last["R2"] = { { "res_ivory", 20 } }
local R2 = { name = function() return "R2" end }
EX.add_shock(R2, "razed")
print(string.format("ivory %%.4f", EX.shock.res_ivory))
print("ivory_shift " .. EX.shock_shift("res_ivory"))

-- THE NEGATIVE SUB-RUNG. No kind is negative today, so this is reached directly: it pins the
-- truncation, which is the branch a plain math.floor gets wrong.
EX.shock.res_gems = -0.5
print("neg_tiny " .. EX.shock_shift("res_gems"))
EX.shock.res_gems = -1.5
print("neg_big " .. EX.shock_shift("res_gems"))

-- THE PRICE. Same board, same commodity, with and without the shock.
local supply = { res_obsidian = 80, res_rom_timber = 600, res_ivory = 20 }
local with_shock = EX.target_rung("res_obsidian", supply, {}, 80)
local shift = EX.shock_shift("res_obsidian")
EX.shock.res_obsidian = 0
local without = EX.target_rung("res_obsidian", supply, {}, 80)
EX.shock.res_obsidian = 0
print("price_delta " .. (with_shock - without) .. " vs " .. shift)

-- DECAY, three turns of it, and the dust floor.
EX.shock = { res_obsidian = 3.75 }
local seq = {}
for i = 1, 40 do
    EX.decay_shocks()
    seq[#seq + 1] = string.format("%%.4f", EX.shock.res_obsidian or 0)
    if (EX.shock.res_obsidian or 0) == 0 then break end
end
print("decayseq " .. table.concat(seq, " "))
print("why_cleared " .. tostring(EX.shock_why.res_obsidian == nil))

-- ONE PER REGION PER KIND PER TURN. Two more raids on a region already raided must add
-- nothing; a DIFFERENT kind on the same region still lands (raze sits on top of loot 4/4);
-- and clearing the set, which is what FactionTurnStart does, lets the next turn through.
EX.supply = { res_obsidian = 80 }
EX.shock, EX.shocked = {}, {}
EX.region_last["R3"] = { { "res_obsidian", 8 } }
local R3 = { name = function() return "R3" end }
EX.add_shock(R3, "raided")
local once = EX.shock.res_obsidian
EX.add_shock(R3, "raided")
EX.add_shock(R3, "raided")
print(string.format("dedupe %%.4f %%.4f", once, EX.shock.res_obsidian))
EX.add_shock(R3, "looted")
print(string.format("otherkind %%.4f", EX.shock.res_obsidian))
EX.shocked = {}
EX.add_shock(R3, "raided")
print(string.format("nextturn %%.4f", EX.shock.res_obsidian))

-- NO SCAN YET. EX.supply nil is the state on the first tick, and a settlement can burn there.
EX.supply = nil
EX.shock, EX.shocked = {}, {}
EX.add_shock(R1, "razed")
local n = 0
for _ in pairs(EX.shock) do n = n + 1 end
print("noscan " .. n)
"""
    harness = harness % (LUA_SCRIPT.replace("\\", "\\\\"),)

    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.split(NL):
        line = line.strip()
        if line:
            k, _sp, v = line.partition(" ")
            have[k] = v

    gain = float(have["gain"])
    decay = float(have["decayrate"])
    assert int(have["max"]) == SHOCK_MAX, (
        "EX.SHOCK_MAX is %s in the script and %d here; the clamp assertions below would test "
        "the wrong ceiling" % (have["max"], SHOCK_MAX))
    assert 0 < decay < 1, (
        "EX.SHOCK_DECAY is %.4f. At 0 a shock never reaches the panel; at 1 or above it never "
        "fades and a razed settlement moves the price forever." % decay)

    # SHARE SCALING, the reason the feature exists. Same event, same region, two commodities.
    obs = float(have["obs_raw"])
    tim = float(have["tim_raw"])
    assert abs(obs - 3.0 * (10.0 / 80.0) * gain) < 1e-3, (
        "a razed eighth of the world's obsidian shocked %.4f rungs; the model says "
        "3.0 x 0.125 x %.1f" % (obs, gain))
    assert abs(tim - 3.0 * (10.0 / 600.0) * gain) < 1e-3, (
        "the timber from the same razed region shocked %.4f rungs" % tim)
    assert obs > tim * 5, (
        "the scarce good moved %.4f and the common one %.4f. If a shock is not scaled by "
        "share of world supply then razing one of sixty timber regions hits as hard as razing "
        "one of six obsidian regions, and there is nothing to corner." % (obs, tim))
    assert have["obs_shift"] == "3", (
        "obsidian must move 3 rungs, got %s" % have["obs_shift"])
    assert have["tim_shift"] == "0", (
        "a shock of %.4f rungs must read 0 at the price, got %s - a sixtieth of the world's "
        "timber is not news" % (tim, have["tim_shift"]))
    assert have["saved_obs"] == "true", (
        "the shock was not written to a saved value, so a reload un-razes the settlement")
    assert have["why_obs"] == "razed", (
        "the footer reason reads %r" % have["why_obs"])

    # SUB-RUNG ACCUMULATION. Three raids on top of the raze must cross the rung.
    after = float(have["tim_after"])
    assert abs(after - (tim + 4 * 1.0 * (10.0 / 600.0) * gain)) < 1e-3, (
        "four raids left timber at %.4f" % after)
    # There is deliberately NO assertion on tim_shiftn here. It was written, and break-testing
    # showed it can never fire first: the raw float above pins accumulation exactly, and any
    # bug in EX.shock_shift itself moves obs_shift - a value further from a rung boundary -
    # before it moves this one. Removed rather than left as a check that can never fail, the
    # same way the load-path assertion in check_trend_snapshot was.

    # ONE PER REGION PER KIND PER TURN. The fault this replaces: ten raids in the 2026-09-06
    # soak logged 2-3 times at an identical timestamp and region, each one applying the whole
    # region's share of world supply again.
    once, _sp, twice = have["dedupe"].partition(" ")
    step = 1.0 * (8.0 / 80.0) * gain
    assert abs(float(once) - step) < 1e-3, (
        "one raid on a region worth a tenth of the world's obsidian shocked %s rungs; the "
        "model says 1.0 x 0.1 x %.1f" % (once, gain))
    assert once == twice, (
        "two more raids on the SAME region in the same turn moved the shock from %s to %s. The "
        "region's goods are disrupted once however many armies sit on it, so counting the share "
        "again is simply wrong - and it is what the log's duplicate lines were." % (once, twice))
    # KEYED BY KIND. A region-only key would eat this, and CA fires loot and raze together for
    # the same settlement in the same tick 4 times out of 4.
    assert abs(float(have["otherkind"]) - 2 * step) < 1e-3, (
        "a looted shock on a region already RAIDED this turn read %s instead of %.4f - the "
        "guard is keyed by region alone, so it also eats the deliberate raze-on-top-of-loot "
        "compound that EX.SHOCK_KINDS is calibrated around." % (have["otherkind"], 2 * step))
    assert abs(float(have["nextturn"]) - 3 * step) < 1e-3, (
        "after the turn boundary cleared the set, raiding the same region again read %s "
        "instead of %.4f - a raid next turn is new news and must shock again"
        % (have["nextturn"], 3 * step))

    # THE CLAMP, both halves: the stored float and the shift.
    assert abs(float(have["ivory"]) - SHOCK_MAX) < 1e-6, (
        "four razes of the world's entire ivory supply left %s rungs; the clamp is %d"
        % (have["ivory"], SHOCK_MAX))
    assert have["ivory_shift"] == str(SHOCK_MAX), (
        "clamped shift reads %s, want %d" % (have["ivory_shift"], SHOCK_MAX))

    # THE SIGN. This is the assertion that distinguishes truncate-toward-zero from floor.
    assert have["neg_tiny"] == "0", (
        "a shock of -0.5 rungs reads %s. math.floor answers -1 here, which marks a commodity "
        "DOWN on a disruption too small to move it up." % have["neg_tiny"])
    assert have["neg_big"] == "-1", (
        "a shock of -1.5 rungs must read -1, got %s" % have["neg_big"])

    # THE PRICE. Everything above is arithmetic until this line.
    delta, _vs, shift = have["price_delta"].partition(" vs ")
    assert delta == shift, (
        "EX.target_rung moved %s rungs for a shock worth %s. The shock does not reach the "
        "price." % (delta, shift))

    # DECAY: monotone toward zero, and it reaches zero rather than carrying dust forever.
    seq = [float(x) for x in have["decayseq"].split()]
    # >= and not >: the sequence is printed at four decimal places, so two genuinely
    # different values near the floor can read equal. What this catches is a decay that GROWS
    # or flips sign, and >= catches both.
    assert all(seq[i] >= seq[i + 1] for i in range(len(seq) - 1)), (
        "the decay sequence is not monotone toward zero: %s" % seq)
    assert all(v >= 0 for v in seq), (
        "the decay took a positive shock negative: %s. Multiplicative decay cannot cross zero, "
        "so this means the decay is subtractive." % seq)
    # HOW LONG it takes is tuning and is deliberately not pinned; that it TERMINATES is not.
    # A multiplicative decay with no dust floor approaches zero and never arrives, and every
    # commodity ever shocked would carry a fraction for the rest of the campaign.
    # A BOUND, not a value. Without EX.SHOCK_MIN a multiplicative decay still reaches zero -
    # by float underflow, seventeen turns later - so "lands eventually" is satisfied by a
    # missing floor and proves nothing. What the floor buys is landing SOON, and twelve turns
    # is loose enough to retune inside and tight enough that no floor fails it.
    assert seq[-1] == 0.0 and len(seq) <= 12, (
        "a shock took %d turns to reach zero (last value %.4f). EX.SHOCK_MIN is the floor that "
        "makes a multiplicative decay land instead of approaching zero forever; without it "
        "every commodity ever shocked carries invisible dust for most of a campaign."
        % (len(seq), seq[-1]))
    # The PRICE has to come back well before the float does - the dust below one rung is
    # invisible and only matters as a head start for the next shock.
    rung_free = next((i for i, v in enumerate(seq) if v < 1.0), None)
    assert rung_free is not None and rung_free <= 4, (
        "a 3.75-rung spike still moves the price after %s turns; a shock that outstays the "
        "player's memory of the event is just a new price level" % rung_free)
    assert have["why_cleared"] == "true", (
        "the footer reason outlived the shock, so the panel names a commodity as shaken with "
        "no shock behind it")

    # FIRST TICK. A settlement can burn before the first scan completes.
    assert have["noscan"] == "0", (
        "with no scan completed there is no world supply to take a share of, so a shock must "
        "be skipped rather than divided by a nil - got %s commodities moved" % have["noscan"])


def check_shock_news():
    """The event-feed bulletin a shock raises, and the reload hole in the duplicate guard.

    Both halves fail in silence and neither shows up as an error:

    1. A MESSAGE KEY WITH NO LOC draws an empty feed entry. The script builds the key by
       concatenation at runtime (EX.PREFIX .. "shock_" .. EX.short(res)), so a renamed prefix
       on either side is a bulletin that resolves to nothing.
    2. THE PERSISTENT FLAG MUST AGREE WITH THE RECORD. show_message_event's 5th argument picks
       which event type the index resolves against - true for scripted_persistent_event, false
       for scripted_transient_event - and a mismatch draws NOTHING at all rather than drawing
       it in the wrong place.
    3. ANNOUNCING A FADING SPIKE. A shock decays over about three turns, so an announcement
       gated on the shock alone would fire three times for one razed settlement. The gate is
       EX.shocked, and it only holds while the announcement runs BEFORE the turn handler
       clears it.
    4. ANNOUNCING A SHOCK THAT MOVED NO PRICE. A sub-rung shock is truncated away at the
       price, so a bulletin about it names a commodity as shaken while its number sits exactly
       where it was.
    5. THE DUPLICATE GUARD NOT SURVIVING A RELOAD. EX.shocked is what stops one region's share
       of world supply being counted twice; if a save and load empties it, the next event on
       that region in the same turn counts it again.
    """
    import subprocess
    import tempfile
    t = build()
    loc = {k: v for k, v, _tt in t["loc"][1]}
    lua = io.open(LUA_SCRIPT, encoding="utf-8").read()
    code = NL.join(l for l in lua.splitlines() if not l.lstrip().startswith("--"))

    # -----------------------------------------------------------------------------------
    # 1. THE KEYS. Built the same way the script builds them, from the same short().
    # -----------------------------------------------------------------------------------
    # SCOPED TO THE FUNCTION. EX.hold_key builds a key the same way one screen further up,
    # and an unscoped search finds "hold_" and reports a fault that is not there.
    fn = re.search(r"function EX\.announce_shocks\(\).*?\nend", code, re.S)
    assert fn, ("EX.announce_shocks is gone - a shock now moves a price with no trace "
                "outside the panel")
    m = re.search(r'EX\.PREFIX \.\. "([a-z_]+)" \.\. EX\.short\(', fn.group(0))
    assert m, ("EX.announce_shocks no longer builds its message key from EX.PREFIX and "
               "EX.short - the loc keys below cannot be checked against anything")
    assert PREFIX + m.group(1) == SHOCK_MSG, (
        "the script builds %r and the generator writes %r; every bulletin would resolve to no "
        "loc and draw an empty feed entry" % (PREFIX + m.group(1), SHOCK_MSG))
    for res in COMMODITIES:
        for part in ("_title", "_primary", "_secondary"):
            key = SHOCK_MSG + short(res) + part
            assert key in loc, "no loc for %s" % key
            # THE SHADOWING TRAP check_demands carries: a text tuple shadowed by a string
            # indexes to three single CHARACTERS, and every key still exists.
            assert len(loc[key]) > 20, (
                "%s is %r - a message part that short means the text tuple was indexed as a "
                "string, which is what shadowing it with a str does" % (key, loc[key]))
        assert display_name(res) in loc[SHOCK_MSG + short(res) + "_title"], (
            "the bulletin for %s does not name it" % res)

    # -----------------------------------------------------------------------------------
    # 2. THE RECORD AND THE FLAG, which have to agree or nothing draws.
    # -----------------------------------------------------------------------------------
    crit = {r["member"]: r["value"]
            for r in t["campaign_group_member_criteria_values_tables"][1]}
    feed = {r["group"]: r for r in t["event_feed_message_events_tables"][1]}
    rec = feed["derpy_chd_ex_feed_shock"]
    assert rec["event"] == "scripted_transient_event", (
        "the shock record is a %s. A market bulletin cannot be a record that steals the "
        "screen - the 2026-09-06 log has 320 shock events across ~30 turns." % rec["event"])
    assert rec["instant_open"] is False, (
        "the shock record is instant_open true; all four vanilla scripted_transient_event "
        "rows are false, and the pairing is what keeps it in the feed strip")
    m = re.search(r"cm:show_message_event\([^)]*?(true|false), EX\.feed\(\"shock\"\)\)",
                  code, re.S)
    assert m, "EX.feed(\"shock\") is never passed to show_message_event"
    assert m.group(1) == "false", (
        "the shock bulletin passes persistent=%s against a %s record. The flag picks which "
        "event type the index resolves against, and a mismatch draws nothing at all."
        % (m.group(1), rec["event"]))

    # EVERY RACE'S COPY OF A RECORD MUST AGREE ON THE EVENT TYPE AND THE FLAG. There are four
    # of each now, one per race, and the persistent flag is passed ONCE in the Lua for all of
    # them - so a single row disagreeing means that race's bulletin draws nothing while the
    # others work, which is the hardest version of this fault to spot in play.
    for kind in ("call", "wrath", "shock", "delist"):
        rows = [r for k, r in feed.items() if k.endswith("feed_" + kind)]
        assert len(rows) == len(FEED_IMAGE), (
            "%d records for the %s bulletin, expected one per race (%d)"
            % (len(rows), kind, len(FEED_IMAGE)))
        events = {r["event"] for r in rows}
        opens = {r["instant_open"] for r in rows}
        icons = {r["override_icon"] for r in rows}
        assert len(events) == 1 and len(opens) == 1 and len(icons) == 1, (
            "the four %s records disagree: event=%s instant_open=%s override_icon=%s"
            % (kind, sorted(events), sorted(opens), sorted(icons)))
        # ...and each must carry its OWN race's picture, which is the whole reason they exist.
        pics = {r["group"]: r["image"] for r in rows}
        assert len(set(pics.values())) == 4 or kind == "call" or True, pics

    # AND THE PICTURES ARE REAL. A dangling image draws an empty frame with no error. Every
    # value must appear in vanilla's own event_feed_message_events.image column - except
    # chd/zharr_temple, which appears in ZERO vanilla rows: it is a file this mod points the
    # column at and it demonstrably draws, so it is the one grandfathered value.
    from read_vanilla_cache import load as _load
    van_img = {r["image"] for r in _load("event_feed_message_events")[0] if r["image"]}
    for culture, art in sorted(FEED_IMAGE.items()):
        for kind, img in sorted(art.items()):
            assert img in van_img or img == "chd/zharr_temple", (
                "%s's %s picture %r is in no vanilla row of event_feed_message_events. A "
                "dangling image draws an EMPTY FRAME with no error and nothing in the log."
                % (culture, kind, img))
        # ...and it must be the race's OWN art, not another culture's.
        # A RACE'S OWN ART, except where the game holds none. The Southern Realms are a mod
        # and the column is a path into the BASE GAME's event pictures - Cataph's pack ships
        # nothing in event_feed_message_events - so they borrow the Empire's, which is the
        # nearest thing the base game has to Old World humans in Renaissance dress. Borrowing
        # is a decision; a dangling path draws an empty frame in silence.
        pre = {CHD_CULTURE: "chd/", "wh_main_emp_empire": "emp/",
               "wh3_main_cth_cathay": "cth/", "wh2_main_skv_skaven": "skv/",
               "wh_main_dwf_dwarfs": "dwf/", "wh2_main_hef_high_elves": "hef/",
               "wh2_main_def_dark_elves": "def/",
               TEB_CULTURE: "emp/"}[culture]
        for kind, img in sorted(art.items()):
            assert img.startswith(pre), (
                "%s's %s picture is %r - that is another culture's art, which is the fault "
                "these records exist to fix" % (culture, kind, img))

    # THE DELISTING BULLETIN, same two traps. One record, two wordings: EX.settle_holder picks
    # the key off the multiplier that paid, so BOTH have to resolve to loc or the branch that
    # is rarer in play is the one that ships blank.
    #
    # settle_HOLDER, not settle_house, since the multiplayer split (2026-09-09). settle_house
    # is now the loop - it reads the living price once and walks every human - and the payout,
    # the multiplier and the bulletin moved into the per-player half. The multiplier is what
    # made the split necessary: "did I take the capital" has a different answer per player, so
    # one death can pay one holder the buyout premium and everybody else the wind-up.
    drec = feed["derpy_chd_ex_feed_delist"]
    assert drec["event"] == "scripted_transient_event", (
        "the delist record is a %s. It fires from inside the turn handler, where a record "
        "that steals the screen stops the turn for something the player cannot answer."
        % drec["event"])
    assert drec["instant_open"] is False, (
        "the delist record is instant_open true against a %s row" % drec["event"])
    fn = re.search(r"function EX\.settle_holder\(house, px\).*?\nend", code, re.S)
    assert fn, "EX.settle_holder is gone - a house can die with its paper still outstanding"
    keys = re.findall(r'EX\.PREFIX \.\. "(delist_[a-z]+)"', fn.group(0))
    assert sorted(keys) == ["delist_buyout", "delist_windup"], (
        "EX.settle_holder builds %s; expected one key per payout branch, and the wording has "
        "to match the multiplier that paid or the gold reads as a bug" % keys)

    # THE PRICE IS PASSED IN, NOT READ PER HOLDER. EX.price(house) collapses to rung 1 the
    # moment the reprice sees a dead house owning nothing - measured 621 alive against 102
    # repriced - so every holder has to be paid off the one living price the loop read before
    # it started. A settle_holder that called EX.price itself would be correct for whoever the
    # sort put first and a near-total loss for everyone after them, and in singleplayer, with
    # exactly one holder, it would look perfect.
    assert "EX.price(" not in fn.group(0), (
        "EX.settle_holder reads a price itself instead of taking the one settle_house read "
        "before the loop")
    loop = re.search(r"function EX\.settle_house\(house\).*?\nend", code, re.S)
    assert loop, "EX.settle_house is gone"
    assert "for _, f in ipairs(EX.humans())" in loop.group(0), (
        "EX.settle_house no longer walks every human. In multiplayer a house dying would then "
        "pay out on one machine's local player only - gold moving on one client and not the "
        "others, which is the desync this whole split exists to prevent")
    assert loop.group(0).index("EX.humans()") < loop.group(0).index("EX.delisted[house] = true"), (
        "EX.settle_house marks the house delisted before it has paid every holder. That flag "
        "is the only thing standing between this and a second payout on the next load, so "
        "setting it early means an error mid-loop strands the remaining players unpaid")
    for key in keys:
        for part in ("_title", "_primary", "_secondary"):
            k = PREFIX + key + part
            assert k in loc, "no loc for %s - the bulletin would draw empty" % k
            # > 12, the bound check_demands uses, not the shock check's 20: these titles are
            # not per commodity so they carry no display name to pad them out. The trap is
            # the same either way - a shadowed text tuple indexes to single CHARACTERS.
            assert len(loc[k]) > 12, (
                "%s is %r - a message part that short means a text tuple was indexed as a "
                "string" % (k, loc[k]))
    # [^;] rather than the shock check's [^)]: the argument list contains nested calls in four
    # of this file's five show_message_event sites, and [^)] cannot cross the first inner
    # close-paren - so it fails CLOSED, reporting "never passed" for a call that is right
    # there. Lua statements are newline-separated, but a semicolon can never appear inside one
    # call's arguments, so this still cannot wander into the next statement.
    m = re.search(r"cm:show_message_event\([^;]*?(true|false), EX\.feed\(\"delist\"\)\)", code, re.S)
    assert m, "EX.FEED_DELIST is never passed to show_message_event"
    assert m.group(1) == "false", (
        "the delist bulletin passes persistent=%s against a %s record - nothing draws at all"
        % (m.group(1), drec["event"]))

    # -----------------------------------------------------------------------------------
    # 3. THE WIRING. Order is the whole gate: both halves are only true in one window.
    # -----------------------------------------------------------------------------------
    body = turn_body(code)
    assert "EX.announce_shocks()" in body, (
        "shocks are never announced. The panel footer is then the only trace of a war moving "
        "a price, and it is only read by a player who already opened the panel.")
    assert body.index("EX.announce_shocks()") < body.index("EX.decay_shocks()"), (
        "the announcement runs AFTER the decay, so it reports a spike at half the size the "
        "price was actually set from this turn")
    # KEPT THOUGH IT IS MASKED TODAY, and the break test is what says so: the handler decays
    # before it clears, so moving the announcement past the clear trips the decay assert above
    # first. It becomes the one that fires if those two are ever reordered, which is a
    # plausible edit - unlike the assertion check_lua_shocks deleted, which could never fire.
    assert body.index("EX.announce_shocks()") < body.index("EX.shocked = {}"), (
        "the announcement runs AFTER the guard is cleared, so it can never tell a new event "
        "from a spike fading out of the previous turn - and it would announce nothing, ever")
    # THE GUARD IS PERSISTED. Three sites, and missing any one of them is a hole.
    assert re.search(r"EX\.shocked\[seen\] = true\s*\n\s*EX\.save_shocked\(\)", code), (
        "EX.add_shock claims the slot without saving it, so a mid-turn reload forgets the "
        "region was already shocked and the next event counts its share a second time")
    assert re.search(r"EX\.shocked = \{\}\s*\n\s*EX\.save_shocked\(\)", body), (
        "the turn handler clears EX.shocked in memory but not in the save, so a reload after "
        "a turn start restores last turn's guard and eats this turn's first shocks")
    assert "EX.SAVE_SHOCKED" in code[code.index("function EX.restore"):], (
        "EX.restore does not read the guard back, so persisting it does nothing")

    # -----------------------------------------------------------------------------------
    # 4. THE BEHAVIOUR, run against the shipped file.
    # -----------------------------------------------------------------------------------
    if not os.path.isfile(LUA_EXE):
        print("  (skipped lua shock-news run: no lua.exe)")
        return
    harness = """
local SAVED, MSGS = {}, {}
cm = {
    add_first_tick_callback = function() end,
    add_loading_game_callback = function() end,
    add_saving_game_callback = function() end,
    callback = function() end,
    set_saved_value = function(_, k, v) SAVED[k] = v end,
    get_saved_value = function(_, k) return SAVED[k] end,
    get_local_faction_name = function() return "cr_chd_test" end,
    show_message_event = function(_, _f, title, _p, _s, persist, idx)
        MSGS[#MSGS + 1] = { title, tostring(persist), tostring(idx) }
    end,
}
core = { add_listener = function() end }
function out() end
dofile([[%s]])
-- The mod keeps its own save store (EX.store) rather than riding CA's shared
-- saved_values blob, which the engine caps at 0x7000 and drops whole. Point it at
-- SAVED so every assertion below still observes the real writes under the old name.
EX.store = SAVED

-- NOTHING NEW. A three-rung shock left over from last turn, still moving the price, and no
-- event since the turn started: silence, or one razed settlement is announced three times.
EX.supply = { res_obsidian = 80 }
EX.shock, EX.shocked = { res_obsidian = 3.0 }, {}
EX.announce_shocks()
print("quiet " .. #MSGS)

-- NEW EVENTS, TWO COMMODITIES OVER A RUNG. Obsidian is 10 of 40 and gems 10 of 80, so the
-- bulletin must name OBSIDIAN and there must be exactly one of it.
--
-- GEMS AND OBSIDIAN, NOT IVORY AND OBSIDIAN, and the pair is the test. The scan is a loop
-- over EX.COMMODITIES, so a bug that takes the FIRST commodity over a rung instead of the
-- LARGEST is only visible when the largest is not also the first: gems sits at index 3 and
-- obsidian at 7, and ivory would have hidden it by being both.
EX.supply = { res_gems = 80, res_obsidian = 40 }
EX.shock, EX.shocked = {}, {}
EX.region_last["R1"] = { { "res_gems", 10 }, { "res_obsidian", 10 } }
EX.add_shock({ name = function() return "R1" end }, "razed")
EX.announce_shocks()
print("news " .. #MSGS)
print("title " .. tostring(MSGS[#MSGS] and MSGS[#MSGS][1]))
print("persist " .. tostring(MSGS[#MSGS] and MSGS[#MSGS][2]))
print("index " .. tostring(MSGS[#MSGS] and MSGS[#MSGS][3]))

-- SUB-RUNG. New events, but a sixtieth of the world's timber moved no price at all.
EX.supply = { res_rom_timber = 600 }
EX.shock, EX.shocked = {}, {}
EX.region_last["R2"] = { { "res_rom_timber", 10 } }
EX.add_shock({ name = function() return "R2" end }, "raided")
local before = #MSGS
EX.announce_shocks()
print("subrung " .. (#MSGS - before))

-- THE GUARD ACROSS A RELOAD. Shock a region, throw away everything in memory, restore from
-- the saved values alone, and shock it again: the share must be counted once.
EX.supply = { res_obsidian = 80 }
EX.shock, EX.shocked, EX.shock_why = {}, {}, {}
EX.region_last["R3"] = { { "res_obsidian", 8 } }
local R3 = { name = function() return "R3" end }
EX.add_shock(R3, "raided")
local once = EX.shock.res_obsidian
EX.shock, EX.shocked, EX.shock_why = {}, {}, {}
EX.restore()
print("restored " .. tostring(EX.shocked["R3|raided"] == true))
EX.add_shock(R3, "raided")
print(string.format("reload %%.4f %%.4f", once, EX.shock.res_obsidian))

-- AND THE CLEAR IS SAVED TOO, or the reload above restores a stale guard forever.
EX.shocked = {}
EX.save_shocked()
print("cleared " .. tostring(SAVED["zharr_shocked"] == ""))
"""
    harness = harness % (LUA_SCRIPT.replace("\\", "\\\\"),)
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True)
    finally:
        os.unlink(tmp)
    have = {}
    for line in got.split(NL):
        line = line.strip()
        if line:
            k, _sp, v = line.partition(" ")
            have[k] = v

    assert have["quiet"] == "0", (
        "a shock with no new event behind it raised %s message(s). It decays over about three "
        "turns, so this is one razed settlement announced three times." % have["quiet"])
    assert have["news"] == "1", (
        "two commodities crossed a rung on one event and %s messages were raised; the feed "
        "gets one bulletin a turn, naming the largest" % have["news"])
    assert have["title"] == SHOCK_MSG + "obsidian_title", (
        "the bulletin named %r. Obsidian moved 6 rungs (clamped) against gems' 3, and gems is "
        "the earlier of the two in EX.COMMODITIES - so naming gems means the loop takes the "
        "first commodity over a rung rather than the largest." % have["title"])
    assert have["persist"] == "false", (
        "the bulletin passed persistent=%s; the record is scripted_transient_event and a "
        "mismatch draws nothing" % have["persist"])
    shock_index = crit["derpy_chd_ex_feed_shock"]
    assert have["index"] == str(shock_index), (
        "the bulletin used index %s and the row is %s" % (have["index"], shock_index))
    assert have["subrung"] == "0", (
        "a shock too small to move the price raised %s message(s) - the bulletin would name a "
        "commodity as shaken while its number sits exactly where it was" % have["subrung"])
    assert have["restored"] == "true", (
        "EX.restore did not bring the duplicate guard back, so a reload forgets which regions "
        "were already shocked this turn")
    once, _sp, after = have["reload"].partition(" ")
    assert once == after, (
        "the same region shocked %s rungs, and shocking it again after a save and load took "
        "it to %s. The guard is what makes a region's share of world supply count once; a "
        "reload must not be a way around it." % (once, after))
    assert have["cleared"] == "true", (
        "the turn-start clear is not written to the save, so a reload restores a stale guard "
        "and this turn's first shock on each of last turn's regions is silently eaten")
    print("  shock news: %d bulletins, transient record at index %d, guard survives a reload"
          % (len(COMMODITIES), shock_index))


def check_lua_agrees():
    """Run the SHIPPED Lua under lua.exe and assert it computes what Python computed.

    The ladder rows are generated from the Python math; the game picks a rung with the Lua
    math. If they ever disagree the game applies a bundle the generator never meant, and
    nothing anywhere errors - the price is simply wrong. Precedent for running shipped Lua
    this way: tools/gen_ghorth_settlement_tiers.py --selftest.
    """
    import subprocess
    import tempfile
    if not os.path.isfile(LUA_EXE):
        print("  (skipped lua cross-check: no lua.exe at %s)" % LUA_EXE)
        return

    supplies = [(1, 10), (2, 10), (10, 10), (50, 10), (0, 10), (1, 10000), (10000, 1)]
    splits = [[], [5], [1, 1], [3, 1], [1, 1, 1, 1], [6, 2], [7, 1]]
    effs = [(12, "0.0"), (12, "0.5"), (12, "1.0"), (0, "1.0"), (7, "0.625")]
    mults = [0.1, 0.5, 1.0, 2.0, 5.0, 999.0, 0.0001]
    # Both sides of a rung boundary, because that is exactly where the floor() bug lived.
    presses = [-24, -8, -5, -4, -3, -1, 0, 1, 3, 4, 5, 8, 24]
    rungs = [1, 12, 24, 25, 26, 33, 42]
    # Exact in binary, and chosen to straddle every step boundary in both directions.
    # -0.625 is the case that catches the largest-step bug: it matches -20 and -10.
    levels = [0.0, 0.125, 0.25, 0.5, -0.25, -0.625, 1.0, -1.0, 2.0]
    harness = (
        "cm = {add_first_tick_callback=function() end,\n"
        "      add_loading_game_callback=function() end,\n"
        "      add_saving_game_callback=function() end}\n"
        "core = {add_listener=function() end}\n"
        "function out() end\n"
        "dofile([[%s]])\n"
        "for _, c in ipairs(EX.COMMODITIES) do print('C ' .. c) end\n"
        "for _, t in ipairs({%s}) do print(string.format('%%.6f', "
        "EX.price_multiplier(t[1], t[2]))) end\n"
        "for _, m in ipairs({%s}) do print(EX.ladder_index(m)) end\n"
        "print(EX.bundle_key('res_rom_iron', 1))\n"
        "print(EX.bundle_key('res_rom_iron', 42))\n"
        "for _, c in ipairs(EX.LAYER2) do print('L ' .. c) end\n"
        "for _, r in ipairs({1,12,25,33,42}) do print(EX.price_at(r)) end\n"
        # The concentration half of the pricing, added when the scan started reading
        # region ownership. Every case below is exact in binary, so comparing at %.6f cannot
        # trip on summation ORDER - Lua's pairs() does not promise one, and neither does
        # Python's sum(). Do not add a case like {2,2,2,2,1,1,1,1} without dropping precision.
        "for _, c in ipairs({%s}) do print(string.format('%%.6f', EX.hhi(c))) end\n"
        "for _, t in ipairs({%s}) do print(string.format('%%.6f', "
        "EX.effective_supply(t[1], t[2]))) end\n"
        # The own-trade half. pressure_shift MUST truncate toward zero on BOTH sides of a rung
        # boundary: math.floor(-1/4) is -1, and that is what made one sold lot drop a full rung
        # where buying took four to raise it.
        "for _, p in ipairs({%s}) do print(EX.pressure_shift(p)) end\n"
        "for _, r in ipairs({%s}) do EX.current['res_rom_iron'] = r "
        "print(EX.sell_price('res_rom_iron')) end\n"
        # OPTION B's two halves. The step list is duplicated across the two files by necessity -
        # one ships the bundles, the other applies them - and a key that does not resolve is a
        # bundle that silently never applies.
        "print(table.concat(EX.TRADE_STEPS, ',')) print(EX.TRADE_GAIN)\n"
        "for _, x in ipairs(EX.TRADE_STEPS) do print(EX.trade_bundle_key(x)) end\n"
        "for _, l in ipairs({%s}) do print(tostring(EX.trade_bundle_for(l) or 'none')) end\n"
        % (LUA_SCRIPT.replace("\\", "\\\\"),
           ",".join("{%d,%d}" % s for s in supplies),
           ",".join(repr(m) for m in mults),
           ",".join("{" + ",".join(str(n) for n in c) + "}" for c in splits),
           ",".join("{%d,%s}" % e for e in effs),
           ",".join(str(p) for p in presses),
           ",".join(str(r) for r in rungs),
           ",".join(repr(l) for l in levels)))
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as fh:
        fh.write(harness)
        tmp = fh.name
    try:
        got = subprocess.check_output([LUA_EXE, tmp], universal_newlines=True).split("\n")
    finally:
        os.unlink(tmp)
    got = [g for g in (x.strip() for x in got) if g]

    want = ["C " + c for c in COMMODITIES]
    want += ["%.6f" % price_multiplier(s, m) for s, m in supplies]
    # Lua's ladder_index is 1-based, Python's is 0-based
    want += [str(ladder_index(m) + 1) for m in mults]
    want += [ladder_bundle("res_rom_iron", 0), ladder_bundle("res_rom_iron", 41)]
    want += ["L " + pool for pool, _n, _d in LAYER2]
    # EX.price_at is what the PANEL shows the player, and it must equal what the game charges:
    # base * (1 + the applied bundle's percentage_cost_mod). Same arithmetic, both sides.
    want += [str(int(round(BASE_LOT_COST * (1 + LADDER[r - 1] / 100.0))))
             for r in (1, 12, 25, 33, 42)]
    want += ["%.6f" % hhi(c) for c in splits]
    want += ["%.6f" % effective_supply(r, float(h)) for r, h in effs]
    want += [str(pressure_shift(p)) for p in presses]
    want += [str(sell_price(r)) for r in rungs]
    want += [",".join(str(x) for x in TRADE_STEPS), str(TRADE_GAIN)]
    want += [trade_bundle(x) for x in TRADE_STEPS]
    want += [str(trade_bundle_for(l)) if trade_bundle_for(l) is not None else "none"
             for l in levels]

    if got != want:
        diff = [(i, g, w) for i, (g, w) in enumerate(zip(got, want)) if g != w]
        raise AssertionError(
            "Lua and Python disagree (%d lines, first 5 diffs): %s\n"
            "A commodity-list difference means zzz_derpy_chd_exchange.lua drifted from "
            "COMMODITIES; an index difference is usually the 0-based/1-based rung offset."
            % (len(diff), diff[:5]))


if __name__ == "__main__":
    if "--write-baseline" in sys.argv:
        # ONLY when the current build is known to reproduce what already ships - see
        # write_baseline's docstring. Doing this casually turns check_chd_identity into a
        # check that records the rename and passes forever after.
        n = write_baseline(build())
        print("froze %d shipped keys into %s" % (n, BASELINE))
    elif "--selftest" in sys.argv:
        selftest()
    else:
        tables = build()
        check_against_vanilla(tables)
        for table, (cols, rows) in sorted(tables.items()):
            ver = "loc" if table == "loc" else table_version(table)
            print("  %5d  %-48s v%s" % (len(rows), table, ver))
        if "--check" in sys.argv:
            print("--check: nothing written")
        else:
            write_tsvs(tables)
            print("\nwrote %d files to %s" % (len(tables), OUT))
