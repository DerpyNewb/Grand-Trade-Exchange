"""Derpy Resource Overhaul - new trade goods for every faction, no map edit.

    py tools/gen_resource_overhaul.py              # write TSVs + loc, copy icons
    py tools/gen_resource_overhaul.py --check      # build and verify, write nothing
    py tools/gen_resource_overhaul.py --selftest
    py tools/gen_resource_overhaul.py --audit      # what each building makes, by its in-game name
    py tools/gen_resource_overhaul.py --pack       # RPFM open: build Modpacks/derpy_resource_overhaul.pack
                                                # and one derpy_resource_overhaul_<map>.pack per SUBMODS
                                                # (DB tables inside keep FRAG, derpy_more_resources)

37 trade goods (GOODS). Salted Fish alone was proven first in an IEE game - produced, on the
map label, and traded in a Trade Agreement (docs/TRADE_RESOURCES.md §10-§11). CA_GOODS makes
four of CA's own thin goods - Salt, Furs, Pottery, Wine - as common, on CA's own effects (§18).

Every row is cloned off a vanilla donor good (Salt, res_rom_lead) read out of CA's db.pack, so
the column order and versions are CA's own. A sweep of all 1,600 vanilla tables for res_rom_lead
found the tables a tradeable good lives in - resources, resources_to_campaign, commodities (the
price list - only tradeable goods have a row) and cai_personality_strategic_resource_values
(the AI's value of the good, one row per strategic component) - plus the production effect,
its resource binding, and the building rows that produce it.

Source: production rows on EXISTING buildings (CA's own pattern for a good with no deposit -
Dwarf taverns make Beer, High Elf industry makes Trinkets, both at 6/8/12 per level), each gated
by a lore condition on the building's region - see the comment above GOODS. New map deposits
would need a startpos; see the doc.

Packing needs RPFM open (--pack); it packs the TSVs on DISK, so write them first.
"""
import collections, functools, io, json, math, os, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import read_vanilla_db as rvd
import survey_resource_map as srm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "Modding Files", "source", "resource_overhaul")
PACK = os.path.join(ROOT, "Modding Files", "pack")
ICONS = os.path.join(ROOT, "Modding Files", "source", "exchange_icons", "new_commodities")
FRAG = "derpy_more_resources"   # DB table and loc file names: kept through the rename
PACK_NAME = "derpy_resource_overhaul"   # the .pack files (was derpy_more_resources until 2026-10-02)
ICON_DIR = "ui/campaign ui/effect_bundles"

# WHERE A GOOD COMES FROM: a list of sources, each (pool, condition). The POOL is which buildings
# carry the production row; the CONDITION is a lore rule on the building's region, shipped as a
# building_effect_context_expressions row and named in the row's context_requirement - the way
# CA gates 11 of its own production rows (FactionHasTrade, RegionHasAdjacentDwarfFaction). So a
# good is made by the right building AND only where the lore puts it, on any map, IEE included.
#
# A condition is a small tuple tree, RENDERED to CA's expression language for the game and
# EVALUATED in Python against guess_region_commodities' region signals here - check() asserts
# the two agree region-for-region with that tool's RULES on IE and Realm of Chaos, so the lore
# table and what ships cannot drift apart.
#
# Pools:  "port"        every port chain (6/8/12 by level)
#         "farm" / "hunt" / "craft" / "forge" / "dig" / "stables" / ...  the buildings that
#                       make that kind of thing, chosen by name and description, per
#                       culture (KIND_CHAINS). No fallback: a culture with none of that kind makes
#                       none of those goods (Norsca raids, Chaos Dwarfs trade for food, the dead
#                       do not farm) - they get them by trade, as the lore has it.
#         ("settlement", race...) only those races' main-settlement chains (Norscan mead:
#                       the jarl's hall is the mead hall)
#         "settlement"  every main-settlement chain (4/6/8/10/12 by level) - for goods placed
#                       by NAME in a few cities (books), where the city itself is the source
#         ("mine", res) the resource buildings that stand on those deposits (6/8/12, a by-product)
def CLIM(*names):
    return ("clim", names)


def AREA(*names):
    return ("area", names)


def DEP(*res):
    return ("dep", res)


def ORIGIN(*codes):
    return ("origin", codes)


def REG(*tails):
    return ("reg", tails)


def ALL(*parts):
    return ("and", parts)


def ANY(*parts):
    return ("or", parts)


def NOT(part):
    return ("not", part)


def PORT():
    """The region has a port - CA's own `IsRegionPort` expression."""
    return ("port", None)


def PLACES(good):
    """A good placed by name rather than by terrain: the region tails its lore rule picks out.
    Resolved lazily (the region signals load after this module)."""
    return ("places", good)


@functools.lru_cache(None)
def _place_tails(good):
    import guess_region_commodities as grc
    test = dict((c, t) for c, t, _l in grc.RULES)[good]
    return tuple(sorted({g["tail"] for g in _signals().values() if test(g)}))


ORIGINS = {"dwf": "wh_main_sc_dwf_dwarfs", "chd": "wh3_dlc23_sc_chd_chaos_dwarfs",
           "teb": "wh_main_sc_teb_teb", "ogr": "wh3_main_sc_ogr_ogre_kingdoms",
           "cst": "wh2_dlc11_sc_cst_vampire_coast", "emp": "wh_main_sc_emp_empire",
           "cth": "wh3_main_sc_cth_cathay", "nor": "wh_dlc08_sc_nor_norsca"}
MINED = ("res_rom_iron", "res_gems", "res_gold")
CATHAY = ("cathay", "northern_cathay", "southern_cathay")
LUSTRIA = ("lustria", "eastern_lustria", "western_lustria", "isthmus_of_lustria")
DARKLANDS = ("darklands", "northern_darklands", "southern_darklands")
NAGGAROND = ("naggarond", "northern_naggarond", "western_naggarond", "eastern_naggarond",
             "southern_naggarond")
FARMLAND = ("empire", "northern_empire", "southern_empire", "eastern_empire", "bretonnia",
            "border_princes", "eastern_border_princes", "western_border_princes", "kislev",
            "sylvania")
# IEE-only areas (Ind, Nippon, Khuresh) extend a rule past the vanilla map; they match no IE or
# Realm of Chaos region, so the parity check against the rules table is unaffected.
IEE_EAST = ("ind", "nippon")

GOODS = {
    "salted_fish": dict(
        unit="barrels", price=10.0, name="Salted Fish",
        desc="Herring, cod and eel, gutted on the quay and packed in brine. Every port from "
             "Marienburg to Lothern sends it inland, and every army marches on it.",
        sources=[("port", NOT(CLIM("climate_chaotic")))]),
    "whale_oil": dict(
        unit="barrels", price=12.0, name="Whale Oil",
        desc="Rendered from the great whales of the northern seas. It lights the lamps of every "
             "city that can afford them.",
        sources=[("port", ANY(CLIM("climate_frozen"), AREA("norsca")))]),
    "sea_dragon_hide": dict(
        unit="bundle", price=18.0, name="Sea Dragon Hide", scale=0.5,
        desc="Taken by Druchii corsairs from the sea dragons of the cold seas off Naggaroth. "
             "A cloak of it turns a blade.",
        sources=[("port", AREA(*NAGGAROND))]),
    "rum": dict(
        unit="kegs", price=14.0, name="Rum",
        desc="Cane spirit from the hot coasts. Sartosa and the Vampire Coast float on it.",
        sources=[("port", ANY(ORIGIN("cst"), REG("sartosa"),
                              ALL(CLIM("climate_jungle", "climate_island"),
                                  AREA("mangrove_coast", "southlands", *LUSTRIA))))]),
    "amber": dict(
        unit="chests", price=14.0, name="Amber",
        desc="Golden resin washed up on the Sea of Claws shores, prized by jewellers and "
             "wizards alike.",
        sources=[("port", AREA("kislev", "norsca"))]),
    "grain": dict(
        unit="sacks", price=10.0, name="Grain",
        desc="Wheat, rye and barley from the farmland of the Old World. Bread for cities and "
             "fodder for armies.",
        sources=[("farm", ALL(CLIM("climate_temperate"), AREA(*FARMLAND)))]),
    "warhorses": dict(
        unit="derpy_horses", price=16.0, name="Warhorses",
        desc="Bretonnian destriers, Kislevite steppe horses and Arabyan coursers, bred for war.",
        sources=[("stables", ALL(CLIM("climate_temperate", "climate_savannah", "climate_desert"),
                                    AREA("bretonnia", "kislev", "araby")))]),
    "pipeweed": dict(
        unit="bundle", price=14.0, name="Pipeweed", scale=2.0,
        desc="Halfling leaf from the Moot, smoked in every tavern from Altdorf to Marienburg.",
        sources=[("farm", PLACES("pipeweed"))]),
    "books": dict(
        unit="derpy_crates", price=15.0, name="Books", scale=2.0,
        desc="Printed tomes and copied scrolls from the great presses, colleges and libraries.",
        sources=[("settlement", PLACES("books"))]),
    "olive_oil": dict(
        unit="barrels", price=12.0, name="Olive Oil",
        desc="Pressed in the groves of Tilea and Estalia, shipped across the Middle Sea.",
        sources=[("farm", ALL(ORIGIN("teb"), CLIM("climate_temperate", "climate_savannah")))]),
    "silk": dict(
        unit="derpy_bolts", price=16.0, name="Silk",
        desc="Woven in the lowland provinces of Cathay. It is what the Ivory Road carries west.",
        sources=[("craft", ALL(AREA(*(CATHAY + IEE_EAST)),
                                  CLIM("climate_temperate", "climate_jungle", "climate_savannah")))]),
    "tea": dict(
        unit="chests", price=14.0, name="Tea",
        desc="Leaf from the terraced hills of Cathay, steeped from Wei-Jin to Nan-Gau.",
        sources=[("teahouse", ALL(AREA(*(CATHAY + IEE_EAST)),
                              CLIM("climate_mountain", "climate_temperate", "climate_jungle"))),
                 ("farm", ALL(AREA(*(CATHAY + IEE_EAST)),
                              CLIM("climate_mountain", "climate_temperate", "climate_jungle")))]),
    "jade": dict(
        unit="slabs", price=16.0, name="Jade",
        desc="Green stone quarried in Cathay's mountains, carved into charms and statues.",
        sources=[("craft", ALL(AREA(*CATHAY), CLIM("climate_mountain")))]),
    "coal": dict(
        unit="sacks", price=10.0, name="Coal",
        desc="Black fuel dug beside the iron seams. Every forge and furnace burns it.",
        sources=[(("mine", "res_rom_iron"), None),
                 ("dig", ALL(ORIGIN("dwf", "chd"), CLIM("climate_mountain", "climate_wasteland")))]),
    "silver": dict(
        unit="ingot", price=15.0, name="Silver",
        desc="Veins of silver found in mountain mines already worked for iron, gems or gold.",
        sources=[(("mine",) + MINED, CLIM("climate_mountain"))]),
    "gromril": dict(
        unit="ingot", price=20.0, name="Gromril", scale=0.5,
        desc="Meteoric iron found only deep beneath the old Dwarf holds. Nothing forged is harder.",
        sources=[(("mine",) + MINED, ALL(ORIGIN("dwf"), CLIM("climate_mountain")))]),
    "quicksilver": dict(
        unit="derpy_flasks", price=14.0, name="Quicksilver",
        desc="Liquid metal cooked out of cinnabar in volcanic rock. Alchemists and engineers pay "
             "well for it.",
        sources=[(("mine", "res_gold", "res_gems", "res_obsidian"),
                  CLIM("climate_mountain", "climate_wasteland"))]),
    "brimstone": dict(
        unit="sacks", price=12.0, name="Brimstone",
        desc="Yellow sulphur scraped from the vents of the Dark Lands and every obsidian field.",
        sources=[(("mine", "res_obsidian"), None),
                 ("dig", ALL(AREA(*DARKLANDS), CLIM("climate_wasteland", "climate_chaotic")))]),
    "brass": dict(
        unit="ingot", price=12.0, name="Brass",
        desc="Hashut's own metal, cast in the forges of the Chaos Dwarfs.",
        sources=[("forge", ANY(ORIGIN("chd"), REG("the_copper_landing"))),
                 (("mine", "res_rom_iron"), AREA(*DARKLANDS))]),
    "blackpowder": dict(
        unit="kegs", price=14.0, name="Blackpowder",
        desc="Saltpetre from the salt pans, ground with charcoal and sulphur by the races that "
             "know the secret.",
        sources=[(("mine", "res_rom_lead"), ORIGIN("dwf", "emp", "chd", "cth")),
                 ("settlement", REG("nuln"))]),
    "ithilmar": dict(
        unit="ingot", price=20.0, name="Ithilmar", scale=0.5,
        desc="The light, bright metal of the elves, found only in the rock of Ulthuan.",
        sources=[(("mine",) + MINED + ("res_rom_marble",), AREA("ulthuan")),
                 ("settlement", REG("vauls_anvil_ulthuan"))]),
    "dragon_bone": dict(
        unit="derpy_crates", price=20.0, name="Dragon Bone", scale=0.5,
        desc="Bones from the dragon-holds of Caledor and the old dragon graveyards.",
        sources=[("settlement", PLACES("dragon_bone"))]),
    "lustrian_plumes": dict(
        unit="bundle", price=15.0, name="Lustrian Plumes",
        desc="Brilliant feathers of Lustria's jungle birds and serpents, worth their weight in "
             "gold in the courts of the Old World.",
        sources=[("hunt", ALL(AREA(*LUSTRIA), CLIM("climate_jungle")))]),
    "black_lotus": dict(
        unit="ounce", price=18.0, name="Black Lotus", scale=0.5,
        desc="A poison flower of the southern jungles, sought by assassins and Witch Elves.",
        sources=[("hunt", ALL(CLIM("climate_jungle"),
                                    AREA("southlands", "southern_southlands", "khuresh"))),
                 ("farm", ALL(CLIM("climate_jungle"),
                                    AREA("southlands", "southern_southlands", "khuresh")))]),
    "incense": dict(
        unit="sacks", price=15.0, name="Incense",
        desc="Frankincense and myrrh from the deserts of Araby, burned in temples and tombs.",
        sources=[("farm", ANY(ALL(CLIM("climate_desert"), AREA("araby", "nehekara")),
                              ALL(AREA("ind"), CLIM("climate_desert", "climate_savannah", "climate_temperate"))))]),
    "salted_meat": dict(
        unit="barrels", price=10.0, name="Salted Meat",
        desc="Ogre herds and hunting grounds fill the barrels. Meat keeps; armies march on it.",
        sources=[("hunt", ANY(ORIGIN("ogr"), AREA("mountains_of_mourn"))),
                 ("farm", ANY(ORIGIN("ogr"), AREA("mountains_of_mourn")))]),
    # second batch, 2026-10-01
    "carpets": dict(
        unit="derpy_rolls", price=16.0, name="Arabyan Carpets",
        desc="Knotted by hand in the cities of Araby, in patterns older than the Empire.",
        sources=[("craft", AREA("araby"))]),
    "kvas": dict(
        unit="kegs", price=12.0, name="Kvas",
        desc="Sour rye drink of Kislev, brewed from black bread. Every stanitsa keeps a barrel.",
        sources=[("inn", AREA("kislev"))]),
    "rhinox_hides": dict(
        unit="derpy_hides", price=12.0, name="Rhinox Hides",
        desc="Thick grey hides of the Ogre Kingdoms' rhinox herds, tough enough for armour.",
        sources=[("hunt", ANY(ORIGIN("ogr"), AREA("mountains_of_mourn")))]),
    "mead": dict(
        unit="kegs", price=12.0, name="Mead",
        desc="Honey wine of the Norscan halls, drunk from horns before every raid.",
        sources=[("farm", ANY(AREA("norsca"), ORIGIN("nor"))),
                 (("settlement", "nor"), ANY(AREA("norsca"), ORIGIN("nor")))]),
    "glassware": dict(
        unit="derpy_crates", price=15.0, name="Glassware",
        desc="Blown glass from the workshops of Tilea, Estalia, Marienburg and Lothern.",
        sources=[("craft", ANY(ORIGIN("teb"), REG("marienburg", "lothern")))]),
    "wool": dict(
        unit="derpy_bales", price=10.0, name="Wool",
        desc="Fleece from the sheep that graze the Old World's uplands. Spun and woven in every town.",
        sources=[("farm", ALL(AREA(*FARMLAND), CLIM("climate_mountain", "climate_frozen")))]),
    "porcelain": dict(
        unit="derpy_crates", price=16.0, name="Porcelain",
        desc="Fine white ware fired in the kilns of Cathay's lowland cities.",
        sources=[("craft", ALL(AREA(*(CATHAY + ("nippon",))), CLIM("climate_temperate", "climate_savannah")))]),
    "pearls": dict(
        unit="chests", price=18.0, name="Pearls",
        desc="Brought up by divers on the warm coasts, and worn by every noble who can pay.",
        sources=[("port", CLIM("climate_jungle", "climate_island", "climate_savannah", "climate_desert"))]),
    "starwood": dict(
        unit="logs", price=20.0, name="Starwood", scale=0.5,
        desc="Wood the living trees of Athel Loren shed by their own will. It is given, never cut.",
        sources=[(("settlement", "wef"), ALL(AREA("athel_loren"), CLIM("climate_magicforest")))]),
    "feathers": dict(
        unit="bundle", price=18.0, name="Griffon and Pegasus Feathers", scale=0.5,
        desc="Feathers gathered from the mountain eyries of griffons and pegasi.",
        sources=[("eyrie", ALL(CLIM("climate_mountain"),
                                 AREA("bretonnia", "empire", "northern_empire", "southern_empire",
                                      "eastern_empire", "western_empire", "border_princes")))]),
    "wyvern_scales": dict(
        unit="bundle", price=18.0, name="Wyvern Scales", scale=0.5,
        desc="Scales of the wyverns that nest in the Badlands and the Mountains of Mourn.",
        sources=[("settlement", ALL(CLIM("climate_mountain"), AREA("badlands", "mountains_of_mourn")))]),
}

# CA's OWN common goods, made as common as ours (user, 2026-10-02): CA put Salt, Furs, Pottery and
# Wine on only 11-13 deposits each. Same sources and lore gates as GOODS, but the row carries CA's
# own production effect, so no resource, icon or loc is minted. A level that already makes the good
# in vanilla keeps CA's row and gets none of ours (Wood Elf Game Lodges already make Furs).
CA_GOODS = {
    "salt": dict(res="res_rom_lead", effect="wh_main_effect_region_resource_salt_production",
                 sources=[("port", CLIM("climate_temperate", "climate_savannah", "climate_desert",
                                        "climate_island"))]),
    "furs": dict(res="res_rom_furs", effect="wh_main_effect_region_resource_furs_production",
                 sources=[("hunt", ANY(CLIM("climate_frozen"), ALL(ORIGIN("ogr"), CLIM("climate_mountain")))),
                          ("farm", CLIM("climate_frozen")),
                          (("settlement", "nor"), CLIM("climate_frozen"))]),
    "pottery": dict(res="res_rom_textiles", effect="wh_main_effect_region_resource_pottery_production",
                    sources=[("craft", ALL(NOT(CLIM("climate_frozen", "climate_chaotic", "climate_mountain")),
                                           ANY(AREA(*(FARMLAND + ("araby",))), ORIGIN("teb"))))]),
    "wine": dict(res="res_rom_wine", effect="wh_main_effect_region_resource_wine_production",
                 sources=[("vineyard", ALL(CLIM("climate_temperate", "climate_savannah", "climate_island"),
                                       ANY(AREA("bretonnia", "southern_empire", "border_princes",
                                                "eastern_border_princes", "western_border_princes", "ulthuan"),
                                           ORIGIN("teb"))))]),
}


def good_spec(good):
    return GOODS[good] if good in GOODS else CA_GOODS[good]


# THE STORES (spec docs/superpowers/specs/2026-10-02-resource-overhaul-stores-design.md): every
# settlement keeps a store of each good, filled each turn by exactly what its buildings make.
# CA's 17 tradeable goods by stem - the display stem, so salt not lead, beer not glass, tusks not ivory.
CA_STEMS = {"res_animals": "animals", "res_dyes": "dyes", "res_gems": "gems", "res_gold_idols": "gold_idols",
            "res_ivory": "tusks", "res_medicine": "medicine", "res_obsidian": "obsidian", "res_rom_furs": "furs",
            "res_rom_glass": "beer", "res_rom_iron": "iron", "res_rom_lead": "salt", "res_rom_marble": "marble",
            "res_rom_textiles": "pottery", "res_rom_timber": "timber", "res_rom_wine": "wine",
            "res_spices": "spices", "res_trinkets": "trinkets"}
STORE_DONOR = "wh3_dlc27_sla_thralls_region"   # CA's per-settlement (REGION) pool
STORE_FACTOR = "derpy_mr_stocked"
STORE_CAP_FX = "derpy_mr_store_capacity"
CAP_FX_DONOR = "wh2_dlc12_pooled_resource_nuke_cap"   # a CA maximum_mod effect row, cloned
STORE_BASE, STORE_STEP, STORE_TOP = 200, 200, 4   # space 200 at level 1, +200 a level, to 1,000
STORE_LOC = ("pooled_resources_display_name_", "pooled_resources_description_",
             "pooled_resources_positive_factors_display_name_",
             "pooled_resources_negative_factors_display_name_")


def store(stem):
    return "derpy_mr_store_" + stem


def store_fx(stem):
    """The store's feed effect AND its factor junction id (two tables, one name)."""
    return "derpy_mr_store_%s_stocked" % stem


# THE FLOWS (spec 2026-10-02-resource-overhaul-stores-flows-design.md section 5): one factor per
# kind of move, and one junction per store and kind. TWO-WAY, unlike the gain-only _stocked one:
# a junction's bounds decide which way stock may move (CA's wh3_cp1_cth_relics_settlements_other
# is -max..0, _uncovered 0..max), and a raid books OUT of the victim and IN to the raider on the
# same factor. CA ships 456 two-way junctions, 7 on REGION pools.
FLOW_FACTORS = (("raided", "Raid spoils", "Raided"), ("plundered", "Plunder", "Plundered"),
                ("traded", "Traded in", "Traded out"), ("eaten", "Eaten", "Eaten"),
                ("moved", "Moved in", "Moved out"), ("spent", "Spent", "Spent"), ("sold", "Sold", "Sold"))

# PHASE 4 (spending spec section 2): what well-stocked stores give a settlement, one region bundle
# per use, applied and removed by the flows script each turn. Effects, scopes and values are CA's
# own (plan 2026-10-02-resource-overhaul-phase4-upkeep.md): growth and public order the way CA's
# region bundles carry them, the garrison buff the way Sayl's region bundle reaches the garrison.
# (use, key, icon, title, description, [(effect, scope, value)])
USE_BUNDLES = (
    ("provisions", "derpy_mr_well_fed", "growth.png", "Well fed",
     "After eating, this settlement's stores still hold five turns of provisions.",
     [("wh_main_effect_province_growth_events", "region_to_province_own_unseen", 10)]),
    ("war", "derpy_mr_garrison_stocked", "siege_defence.png", "Garrison stocked",
     "War materials fill at least a quarter of one store's space in this settlement.",
     [("wh_main_effect_force_stat_melee_attack", "region_to_force_own_regionwide_if_garrison", 4),
      ("wh_main_effect_force_stat_melee_defence", "region_to_force_own_regionwide_if_garrison", 4)]),
    ("luxuries", "derpy_mr_comforts", "public_order_happy.png", "Comforts",
     "Luxuries fill at least a quarter of one store's space in this settlement.",
     [("wh_main_effect_public_order_events", "region_to_province_own_unseen", 3)]),
)
BUNDLE_DONOR = "wh2_dlc15_hef_mist_of_yvresse_rite_empowered"   # global, not in 3D, owner only

# PHASE 7 (spending spec section 5): the panel's three orders, each a faction bundle bought with
# ORDER_COST of one use. (key, use, bundle, icon, title, what it does, [(effect, scope, value)])
ORDER_COST, ORDER_TURNS, ORDER_COOLDOWN = 200, 5, 10
ORDERS = (
    ("festival", "luxuries", "derpy_mr_order_festival", "public_order_jubilant.png", "Festival",
     "public order +4 in every province",
     [("wh_main_effect_public_order_events", "faction_to_province_own", 4)]),
    ("muster", "war", "derpy_mr_order_muster", "experience.png", "Muster",
     "recruit rank +1 for every unit",
     [("wh_main_effect_force_all_campaign_experience_base_all", "faction_to_force_own", 1)]),
    ("great_works", "building", "derpy_mr_order_great_works", "construction.png", "Great Works",
     "construction cost -20% for every building",
     [("wh_main_effect_building_construction_cost_mod", "faction_to_region_own", -20)]),
)
ORDER_DONOR = "wh2_dlc09_bundle_tretch_treaty_broken"   # a faction bundle: global, not in 3D, owner only


def flow_factor(kind):
    return "derpy_mr_" + kind


def flow_junction(stem, kind):
    return "derpy_mr_store_%s_%s" % (stem, kind)


@functools.lru_cache(None)
def _ca_names():
    import read_vanilla_loc as rvl
    names = rvl.load("resources")
    return {res: names["resources_onscreen_text_" + res] for res in CA_STEMS}


def store_stems():
    """stem -> (resource key, its production effect, its display name): ours, then CA's."""
    out = {g: (key(g), effect(g), GOODS[g]["name"]) for g in GOODS}
    prod = {r["resource"]: r["effect"] for r in db("effect_bonus_value_resource_junction_tables")[1]
            if r["bonus_value_id"] == "production"}
    for res, stem in CA_STEMS.items():
        out[stem] = (res, prod[res], _ca_names()[res])
    return out


# Our units, beside CA's twelve (commodity_unit_names): key -> (singular, plural).
UNITS = {"derpy_horses": ("horse", "horses"), "derpy_crates": ("crate", "crates"),
         "derpy_bolts": ("bolt", "bolts"), "derpy_flasks": ("flask", "flasks"),
         "derpy_rolls": ("roll", "rolls"), "derpy_hides": ("hide", "hides"),
         "derpy_bales": ("bale", "bales")}
DONOR = "res_rom_lead"   # Salt: every row a tradeable good needs is cloned off it

# The rare goods' own buildings (user, 2026-10-01): a three-level chain each, built by the races its
# lore names, in any ordinary slot - and making NOTHING outside the good's lore regions. No region
# lock exists without a startpos, so the condition IS the lock: rare_cond() derives it from the
# good's sources above, so the building can never reach a region the by-product cannot. The
# by-products stay at half rate, so the AI - which gets no score row and never builds these -
# still makes some. Production is about half a vanilla deposit building (20/30/45).
RARE = {
    # frame: the CA resource-building icon whose race frame and cog the glyph is set into
    # (tools/gen_building_icons.py); None = CA's race-neutral style, the glyph alone
    "gromril": dict(races=("dwf",), frame="dwarf_gold",
                    levels=("Gromril Prospect", "Gromril Delving", "Deep Gromril Mine"),
                    where="Only a Dwarf hold in the mountains, sitting on iron, gems or gold, has gromril "
                          "to dig."),
    "ithilmar": dict(races=("hef",), frame="high_elves_resource_gold",
                     levels=("Ithilmar Lode", "Ithilmar Mine", "Ithilmar Deepworks"),
                     where="Ithilmar lies only in the rock of Ulthuan, under iron, gems, gold or marble, "
                           "and at Vaul's Anvil."),
    "dragon_bone": dict(races="all", frame=None,
                        levels=("Bone Pickers", "Dragon Bone Digs", "Dragon Graveyard Excavation"),
                        where="Dragon bones lie only in Caledor's dragon mountains and mines and on the "
                              "Plain of Bones."),
    "sea_dragon_hide": dict(races=("def",), frame="dark_elves_resource_gold",
                            levels=("Flensing Yard", "Sea Dragon Hunters", "Sea Dragon Fleet"),
                            where="Sea dragons are hunted only from the ports of Naggaroth's cold coasts."),
    "black_lotus": dict(races=("def", "skv"), frame="dark_elves_resource_gold",
                        levels=("Lotus Gatherers", "Lotus Garden", "Black Lotus Plantation"),
                        where="The black lotus grows only in the jungles of the Southlands and Khuresh."),
    "starwood": dict(races=("wef",), frame=None,
                     levels=("Glade of Gifts", "Starwood Grove", "Grove of the Willing"),
                     where="Only the enchanted forest of Athel Loren gives starwood."),
    "feathers": dict(races=("brt", "emp"), frame="empire_gold",
                     levels=("Eyrie Climbers", "Mountain Eyrie", "Great Eyrie"),
                     where="Griffons and pegasi nest only in the mountains of Bretonnia, the Empire and "
                           "the Border Princes."),
    "wyvern_scales": dict(races=("grn", "ogr"), frame="wh_main_grn_resource_gold",
                          levels=("Scale Scavengers", "Wyvern Roost", "Wyvern Hunters' Lodge"),
                          where="Wyverns nest only in the mountains of the Badlands and the Mountains "
                                "of Mourn."),
}
# Per level, after CA's resource buildings (wh_main_dwf_resource_iron 1-3: 20/30/45 of the good,
# 100/150/200 income, then a lore bonus for the units the good arms). The good is halved: these
# goods trade at about double a common one's price.
RARE_TABLE = [10, 15, 23]
RARE_GDP = ("wh_main_effect_economy_gdp_mining", [100, 150, 200])
# The lore bonus, each one a CA effect CA already puts on a building, at CA's own scope and
# per-level values: kind -> (scope, [L1, L2, L3]); 0 = not at that level.
BONUS_KINDS = {"cost": ("province_to_province_own", [-20, -25, -30]),
               "rank": ("province_to_province_own", [0, 1, 2]),
               "upkeep": ("faction_to_force_own", [0, 0, -3]),
               "hero": ("faction_to_province_own", [0, 1, 2])}
# good -> [(race, kind, effect)]. race None = whoever owns it; on a building more than one race
# can build, a named race's bonus is gated on the owner's culture as well as on the lore.
BONUS = {
    "gromril": [("dwf", "cost", "wh2_main_effect_resource_recruitment_cost_reduction_dwf_ironbreaker_hammerer"),
                ("dwf", "rank", "wh2_main_effect_resource_unit_xp_levels_dwf_ironbreaker_hammerer"),
                ("dwf", "upkeep", "wh2_main_effect_resource_upkeep_cost_reduction_dwf_ironbreaker_hammerer")],
    # Swordmasters, Phoenix Guard, Dragon Princes - the ithilmar-armoured elites (CA's iron bonus)
    "ithilmar": [("hef", "cost", "wh2_main_effect_building_recruitment_cost_reduction_hef_resource_iron"),
                 ("hef", "rank", "wh2_main_effect_building_unit_xp_levels_hef_resource_iron"),
                 ("hef", "upkeep", "wh2_main_effect_buildling_upkeep_reduction_hef_resource_iron")],
    "dragon_bone": [(None, "hero", "wh_main_effect_agent_recruitment_xp_all_agents")],
    # Black Ark Corsairs wear the sea dragon cloak (CA's salt bonus is the Corsairs one)
    "sea_dragon_hide": [("def", "cost", "wh2_main_effect_building_recruitment_cost_reduction_def_resource_salt"),
                        ("def", "rank", "wh2_main_effect_building_unit_xp_levels_def_resource_salt"),
                        ("def", "upkeep", "wh2_main_effect_tech_upkeep_cost_reduction_def_corsairs")],
    # Witch Elves' poisons (CA's medicine bonus), and the Eshin assassins
    "black_lotus": [("def", "cost", "wh2_main_effect_building_recruitment_cost_reduction_def_resource_medicine"),
                    ("def", "rank", "wh2_main_effect_building_unit_xp_levels_def_resource_medicine"),
                    ("def", "upkeep", "wh2_main_effect_buildling_upkeep_reduction_def_resource_medicine"),
                    ("skv", "hero", "wh2_main_effect_agent_recruitment_xp_skv_assassin")],
    # starwood bows
    "starwood": [("wef", "cost", "wh2_main_effect_tech_recruitment_cost_reduction_wef_gladeguard_gladeriders"),
                 ("wef", "rank", "wh2_main_effect_tech_unit_xp_levels_wef_gladeguard_gladeriders")],
    # pegasi (CA's Bretonnian animals bonus) and griffons - the Empire's Demigryphs
    "feathers": [("brt", "cost", "wh2_main_effect_building_recruitment_cost_reduction_brt_resource_animals"),
                 ("brt", "rank", "wh2_main_effect_resource_unit_xp_levels_brt_resource_animals"),
                 ("brt", "upkeep", "wh2_main_effect_building_upkeep_cost_reduction_brt_resource_animals"),
                 ("emp", "cost", "wh2_main_effect_resource_recruitment_cost_reduction_emp_demigryphs"),
                 ("emp", "rank", "wh2_main_effect_resource_unit_xp_levels_emp_demigryphs"),
                 ("emp", "upkeep", "wh2_main_effect_resource_upkeep_cost_reduction_emp_demigryphs")],
    # wyvern-scale armour for the Black Orcs; the Ogre hunters' monsters
    "wyvern_scales": [("grn", "cost", "wh_main_effect_tech_recruitment_cost_reduction_bigun_black_orcs"),
                      ("grn", "rank", "wh_main_effect_tech_unit_xp_levels_bigun_black_orcs"),
                      ("ogr", "cost", "wh3_dlc26_effect_recruitment_cost_ogr_hunters_beasts"),
                      ("ogr", "rank", "wh3_dlc26_effect_tech_unit_xp_levels_ogr_hunters_beasts"),
                      ("ogr", "upkeep", "wh3_dlc26_effect_upkeep_ogr_hunters_beasts")],
}


def damaged(v):
    """CA's damaged value: half, rounded away from zero (-25 -> -13, 45 -> 23, 1 -> 1)."""
    return math.copysign(math.ceil(abs(v) / 2.0), v)


# race code -> culture; its availability rosters come from building_chain_availabilities by culture
CULTURES = {"dwf": "wh_main_dwf_dwarfs", "hef": "wh2_main_hef_high_elves", "def": "wh2_main_def_dark_elves",
            "wef": "wh_dlc05_wef_wood_elves", "brt": "wh_main_brt_bretonnia", "emp": "wh_main_emp_empire",
            "grn": "wh_main_grn_greenskins", "ogr": "wh3_main_ogr_ogre_kingdoms", "skv": "wh2_main_skv_skaven",
            "lzd": "wh2_main_lzd_lizardmen", "cth": "wh3_main_cth_cathay", "ksl": "wh3_main_ksl_kislev",
            "chd": "wh3_dlc23_chd_chaos_dwarfs", "nor": "wh_dlc08_nor_norsca",
            "vmp": "wh_main_vmp_vampire_counts", "cst": "wh2_dlc11_cst_vampire_coast", "chs": "wh_main_chs_chaos"}
# race code -> the building set its economy chains sit in (building_set_to_building_junctions)
ECON_SET = {"dwf": "wh_main_set_dwarf_economy", "hef": "wh2_main_set_highelf_infrastructure",
            "def": "wh2_main_set_darkelf_infrastructure", "wef": "wh_dlc05_set_woodelves_economy",
            "brt": "wh_main_set_empire_economy", "emp": "wh_main_set_empire_economy",
            "grn": "wh_main_set_greenskin_economy", "ogr": "wh3_main_set_ogre_infrastructure",
            "skv": "wh2_main_set_skaven_infrastructure", "lzd": "wh2_main_set_lizardmen_infrastructure",
            "cth": "wh3_main_set_cth_infrastructure", "ksl": "wh3_main_set_ksl_infrastructure",
            "chd": "wh3_dlc23_chd_factory_infrastructure", "nor": "wh_main_set_norsca_economy",
            "vmp": "wh_main_set_vampire_economy", "cst": "wh2_dlc11_set_vampire_coast_infrastructure",
            "chs": "wh3_main_set_chaos_economy"}
GENERIC_SET = "wh3_main_secondary_core_generic_minor"
WEF_SET = "wh3_main_secondary_core_generic_major_variant_wef_forest"   # Wood Elves build here instead
BUILD_DONOR = "wh_main_DWARFS_industry"   # the chain row: an ordinary secondary-slot chain
LEVEL_DONOR = "wh_main_DWARFS_resource_iron"   # the level rows: CA's resource-building costs,
                                               # turns and settlement-level requirements
# loc: per good the short and long description (one stem, every race's chain shares it);
# per chain its three level names and its tooltip
LOC_PER_RARE_GOOD, LOC_PER_CHAIN = 2, 4


def rare_races(good):
    r = RARE[good]["races"]
    return tuple(sorted(CULTURES)) if r == "all" else r


def bld_stem(good):
    """The good's shared key stem: its icon and its description, whichever race builds it."""
    return "derpy_mr_bld_" + good


def rare_chains(good):
    """[(race, chain)] - ONE CHAIN PER RACE. The game files a chain under exactly one building
    set: a shared chain listing 17 race sets was filed under the first (High Elf) everywhere, and
    Chaos Dwarf slots, which take only their own sets, never offered it (measured in game,
    2026-10-01). So each race gets its own chain, in its own set and roster."""
    races = rare_races(good)
    if len(races) == 1:
        return [(races[0], bld_stem(good))]
    return [(r, "%s_%s" % (bld_stem(good), r)) for r in races]


def bld_icon(good):
    return "ui/buildings/icons/%s.png" % bld_stem(good)


def bld_levels(chain):
    return ["%s_%d" % (chain, n) for n in (1, 2, 3)]


def rare_cond(good):
    """Where the good's building makes it: anywhere one of its by-product sources would."""
    parts = []
    for pool, cond in GOODS[good]["sources"]:
        kind = _kind(pool)   # what the by-product's pool required of the region, made explicit
        need = PORT() if kind == "port" else DEP(*pool[1:]) if kind == "mine" else None
        parts.append(ALL(*[p for p in (need, cond) if p is not None]))
    return parts[0] if len(parts) == 1 else ANY(*parts)


def n_loc():
    chains = sum(len(rare_chains(g)) for g in RARE)
    return (LOC_PER_GOOD * len(GOODS) + 2 * len(UNITS) + LOC_PER_RARE_GOOD * len(RARE)
            + LOC_PER_CHAIN * chains + 5 * (len(GOODS) + len(CA_STEMS)) + 3 + 2 * len(FLOW_FACTORS)
            + 2 * len(USE_BUNDLES) + 2 * len(ORDERS))

# Owners with no living people to make or eat a good: daemons, the dead, and beasts with no towns
# to sell in. Matched on the CHAIN key, so a special variant for one of them goes too.
EXCLUDE = re.compile(r"(^|_)(dae|kho|nur|sla|tze|tmb|nag|bst|beastmen|BEASTMEN)(_|$)")
# Chains that stand in a port or deposit slot but are not a harbour or a mine, by their own names:
# the Chaos Dwarf river sluice and irrigation qanat, Nakai's port temples; and the `_military`
# smithies on an iron deposit (Arsenal, Black Orc Forge, Master Swordsmith's Forge), which CA
# itself gives none of the deposit's good.
NOT_A_HARBOUR = re.compile(r"chd_factory_port|chd_outpost_port|lzd_port_nakai")
NOT_A_MINE = re.compile(r"_military")
# main-settlement chains that are not a living town: ruins, the prologue, dummies, endgame spawns
SETTLE_SKIP = re.compile(r"ruin|prologue|dummy|endgame|horde")
TABLES = {"port": [6, 8, 12], "mine": [6, 8, 12], "settlement": [4, 6, 8, 10, 12],
          **{k: [6, 8, 12] for k in ("farm", "hunt", "teahouse", "inn", "craft", "forge", "dig",
                                     "stables", "eyrie", "vineyard")}}

# The economy buildings of each kind, by culture - the "green" buildings. Listed rather than
# matched, because the naming is per DLC (Cathay's growth/income yin and yang, the Chaos Dwarf
# refinery). check() asserts each exists and is buildable in a secondary slot.
KIND_CHAINS = {
    # Chosen by each building's own NAME and DESCRIPTION (CA's loc), not by chain_category: a pool
    # once held every "growth" and "income" chain, so the Greenskin Idolz grew grain, the Skaven
    # Rubbish Pit made porcelain and the Gold Sluice made coal (user, in game, 2026-10-01).
    # Fields / Windmill / Barley Field / Elf Homestead / Kislev Farmstead / Dark Elf Manors
    "farm": ["wh_main_BRETONNIA_farm_basic", "wh_main_BRETONNIA_farm_extra", "wh_main_EMPIRE_farm_basic",
             "wh_main_DWARFS_farm", "wh2_main_hef_farm", "wh3_main_ksl_growth_xp", "wh2_main_def_farm"],
    # Skink Foraging Camp ... Meat Storage Hall / Trapper's Den, Game Lodge / Ogre Maw Pit
    "hunt": ["wh2_main_lzd_farm", "wh_dlc05_wef_growth", "wh3_main_ogr_farm"],
    "teahouse": ["wh3_main_cth_growth_yin"],                 # Tea Parlour / Contemplation Gardens
    "inn": ["wh3_main_ksl_growth_recruit_cost"],             # Roadhouse: "sell nothing but kvas"
    # Weaving House / Clothier, Elven Craftsman, Druchii Artisan's House, Cathay Wares Market and
    # Goods Emporium, Kislev Market Square, Skink markets
    "craft": ["wh_main_EMPIRE_industry_basic", "wh_main_BRETONNIA_industry_basic", "wh2_main_hef_industry",
              "wh2_main_def_industry", "wh3_main_cth_income_yang", "wh3_main_cth_income_yin",
              "wh3_main_ksl_trade_order", "wh2_main_lzd_industry"],
    # Chaos Dwarf Cinerator / Grand Furnace and Gunsmith, Dwarf Toolmaker - metal cast and worked
    "forge": ["wh3_dlc23_chd_tower_furnace", "wh3_dlc23_chd_factory_assembly_line", "wh_main_DWARFS_industry"],
    # what is DUG: the Chaos Dwarf Miners' Workshop and the outpost Mineshaft
    "dig": ["wh3_dlc23_chd_factory_drills", "wh3_dlc23_chd_outpost_mine"],
    # horse breeders - Kislev's is the Stud Farm; its "stables" chain is the Tzar Guard's barracks
    "stables": ["wh2_main_hef_stables", "wh_main_BRETONNIA_stables", "wh_main_EMPIRE_stables",
                "wh_main_NORSCA_stables", "wh3_main_ksl_growth_xp"],
    # where griffons and pegasi are kept: the Pegasus Aerie and the Menagerie
    "eyrie": ["wh_main_BRETONNIA_stables", "wh_main_EMPIRE_stables"],
    # the farms of the peoples who keep vines - not a Dwarf barley field or a Druchii manor
    "vineyard": ["wh_main_BRETONNIA_farm_basic", "wh_main_BRETONNIA_farm_extra", "wh_main_EMPIRE_farm_basic",
                 "wh2_main_hef_farm"],
}
# A chain's race, from the tag in its key - CA's culture variants leave 80 settlement chains
# without a culture, so the key is the only reliable signal. Synonyms fold to one code.
_RACE = re.compile(r"(?i)(?:^|_)(vampirecoast|cst|savageorc|greenskin|grn|norsca|nor|empire|emp|"
                   r"bretonnia|brt|dwarfs?|dwf|vampires|vmp|def|hef|lzd|skv|ogr|cth|ksl|wef|chd|woc|chs|teb)(?=_|$)")
_FOLD = {"vampirecoast": "cst", "savageorc": "grn", "greenskin": "grn", "norsca": "nor",
         "empire": "emp", "bretonnia": "brt", "dwarf": "dwf", "dwarfs": "dwf", "vampires": "vmp",
         "woc": "chs"}


def race(chain):
    m = _RACE.search(chain)
    if not m:
        return None
    tag = m.group(1).lower()
    return _FOLD.get(tag, tag)

# Map mods with their own campaign key. Each gets its OWN small pack holding only the
# resources_to_campaign rows: a row naming a campaign that is not loaded is an unresolvable
# foreign key, and the game refuses the whole pack - so it cannot live in the main one. Same
# shape as IEE's own "!cr_vanilla" fragment, which links CA's 18 goods to its campaign.
# The Old World ("cr_oldworld") goes here once that mod is updated.
WORKSHOP = r"F:\SteamLibrary\steamapps\workshop\content\1142710"
SUBMODS = {
    "iee": dict(campaign="cr_combi_expanded", port_prefix="cr_port_",
                pack=os.path.join(WORKSHOP, "3007996493", "!cr_immortal_empires_expanded.pack")),
}


# THE MAP LABEL. The settlement label's resource row (`resource_list` in CA's city_info_bar) is
# filled by the engine from MAP DEPOSITS only - measured 2026-10-01, Bay of Blades has a port
# making Salted Fish and its label shows nothing, and CA's own building-made Beer and Trinkets
# never show there either. So the label gets one icon per good of ours, placed right after that
# row inside `icon_holder` (a HorizontalList, so it flows), visible only while one of the
# settlement's buildings carries the good's production effect. A whole-file override of a CA
# file: re-run after any patch that touches it (it is rebuilt from the live ui3.pack each run).
UI_PACK = os.path.join(os.path.dirname(rvd.DB_PACK), "ui3.pack")
LABEL = "ui/campaign ui/city_info_bar.twui.xml"
LOC_PER_GOOD = 5

_ICON_XML = """<{id}
\tthis="{g}"
\tid="{id}"
\tallowhorizontalresize="false"
\tallowverticalresize="false"
\tcomponentleveltooltip="{tip}"
\ttooltiplabel="{lbl}"
\ttooltipslocalised="true"
\tuniqueguid="{g}"
\tcurrentstate="{s}"
\tdefaultstate="{s}">
\t<callbackwithcontextlist>
\t\t<callback_with_context
\t\t\tcallback_id="ContextVisibilitySetter"
\t\t\tcontext_object_id="CcoCampaignSettlement"
\t\t\tcontext_function_id="{expr}"/>
\t</callbackwithcontextlist>
\t<componentimages>
\t\t<component_image
\t\t\tthis="{ci}"
\t\t\tuniqueguid="{ci}"
\t\t\timagepath="{img}"/>
\t</componentimages>
\t<states>
\t\t<newstate
\t\t\tthis="{s}"
\t\t\tname="NewState"
\t\t\twidth="24"
\t\t\theight="24"
\t\t\tinteractive="true"
\t\t\tdisabled="true"
\t\t\tuniqueguid="{s}">
\t\t\t<imagemetrics>
\t\t\t\t<image
\t\t\t\t\tthis="{im}"
\t\t\t\t\tuniqueguid="{im}"
\t\t\t\t\tcomponentimage="{ci}"
\t\t\t\t\twidth="24"
\t\t\t\t\theight="24"/>
\t\t\t</imagemetrics>
\t\t</newstate>
\t</states>
</{id}>"""


def _guid(tag):
    """CA's 8-4-4-16 GUID shape, fixed per tag so a rebuild does not churn the file."""
    import hashlib
    h = hashlib.md5(("derpy_more_resources:" + tag).encode()).hexdigest().upper()
    return "%s-%s-%s-%s" % (h[:8], h[8:12], h[12:16], h[16:32])


def label_id(good):
    return "derpy_mr_" + good


def tooltip(good):
    g = GOODS[good]
    return "%s||A building in this settlement produces %s, a trade resource." % (g["name"], g["name"])


def label_vanilla():
    """CA's city_info_bar.twui.xml as text, CRLF kept."""
    for _path, comp, data in __import__("read_pack_index").read(UI_PACK, LABEL):
        if comp:
            import read_vanilla_loc
            data = read_vanilla_loc._decompress(data)
        return data.decode("utf-8")
    raise SystemExit("%s not in %s" % (LABEL, UI_PACK))


def label_check(text):
    """Everything the insert assumes, against CA's live file."""
    h0, h1 = text.index("<hierarchy>"), text.index("</hierarchy>")
    hier, comps = text[h0:h1], text[h1:]
    assert hier.count("<resource_list ") == 1 and hier.count("</resource_list>") == 1, "resource_list moved"
    assert comps.count('id="resource_list"') == 1, "resource_list component count changed"
    ih = hier[hier.index("<icon_holder "):hier.index("</icon_holder>")]
    assert "<resource_list " in ih, "resource_list is no longer inside icon_holder"
    seg = comps[comps.index('id="icon_holder"'):]
    seg = seg[:seg.index("</icon_holder>")]
    assert 'type="HorizontalList"' in seg, "icon_holder is no longer a horizontal row"
    for good in GOODS:
        assert label_id(good) not in text, "%s already in CA's file" % label_id(good)
        for tag in ("c", "s", "ci", "im"):
            assert _guid(good + tag) not in text, "guid collision"


def label_patch(text):
    label_check(text)
    nl = "\r\n" if "\r\n" in text else "\n"
    h1 = text.index("</hierarchy>")
    hi = text.index("</resource_list>")
    line_start = text.rindex(nl, 0, hi) + len(nl)
    indent = text[line_start:hi]
    ci = text.index("</resource_list>", h1)
    c_start = text.rindex(nl, 0, ci) + len(nl)
    c_indent = text[c_start:ci]
    hier_add, comp_add = "", ""
    for good in GOODS:
        expr = ('BuildingSlotList.Any(BuildingContext.EffectList.Any(EffectKey == &quot;%s&quot;))'
                % effect(good))
        xml = _ICON_XML.format(id=label_id(good), g=_guid(good + "c"), s=_guid(good + "s"),
                               ci=_guid(good + "ci"), im=_guid(good + "im"), expr=expr,
                               img="%s/%s.png" % (ICON_DIR, icon(good)), tip=tooltip(good),
                               lbl=label_id(good) + "_Tooltip")
        hier_add += nl + indent + '<%s this="%s"/>' % (label_id(good), _guid(good + "c"))
        comp_add += nl + nl.join(c_indent + l for l in xml.split("\n"))
    out = text[:ci + len("</resource_list>")] + comp_add + text[ci + len("</resource_list>"):]
    return out[:hi + len("</resource_list>")] + hier_add + out[hi + len("</resource_list>"):]


def label_verify(out):
    """The patched file parses, and each icon is declared once, inside icon_holder, GUID-paired."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(out.encode("utf-8"))
    hier, comps = root.find("hierarchy"), root.find("components")
    holder = [e for e in hier.iter("icon_holder")]
    assert len(holder) == 1
    for good in GOODS:
        lid = label_id(good)
        h = [e for e in holder[0] if e.tag == lid]
        c = [e for e in comps if e.tag == lid]
        assert len(h) == 1 and len(c) == 1, (lid, len(h), len(c))
        assert h[0].get("this") == c[0].get("this") == c[0].get("uniqueguid"), lid
        kids = [e.tag for e in holder[0]]
        assert kids.index(lid) == kids.index("resource_list") + 1 + list(GOODS).index(good), kids
        img = c[0].find("componentimages/component_image").get("imagepath")
        assert img.endswith(icon(good) + ".png"), img
        cb = c[0].find("callbackwithcontextlist/callback_with_context").get("context_function_id")
        assert effect(good) in cb, cb


def key(good):
    return "res_derpy_" + good


def effect(good):
    return "derpy_effect_region_resource_%s_production" % good


def icon(good):
    return "resource_derpy_%s" % good


@functools.lru_cache(None)
def db(table):
    """(version, rows) of one vanilla table."""
    (_p, ver, rows), = rvd.load(rvd.DB_PACK, table)
    return ver, rows


@functools.lru_cache(None)
def port_chains():
    """Every chain the startpos permits in a port slot -> its non-ruin levels in order."""
    _tr, perm, _cp, _t, _rc, sp = srm.load()
    tpls = {r["slot_template"] for r in sp if r["slot_type"] == "port"}
    chains = {c for t in tpls for c in perm.get(t, ())}
    levels = collections.defaultdict(list)
    for r in db("building_levels_tables")[1]:
        if r["chain"] in chains and not r["level_name"].endswith("_ruin") \
                and "_ruin_" not in r["level_name"]:
            levels[r["chain"]].append((r["level"], r["level_name"]))
    return {c: [n for _l, n in sorted(v)] for c, v in levels.items()}


@functools.lru_cache(None)
def _chain_levels(chains):
    levels = collections.defaultdict(list)
    for r in db("building_levels_tables")[1]:
        if r["chain"] in chains and not r["level_name"].endswith("_ruin") \
                and "_ruin_" not in r["level_name"]:
            levels[r["chain"]].append((r["level"], r["level_name"]))
    return {c: [n for _l, n in sorted(v)] for c, v in levels.items()}


@functools.lru_cache(None)
def pool_chains(pool):
    """pool -> {chain: [level, ...]}, owners in EXCLUDE already dropped."""
    if pool == "port":
        out = {c: v for c, v in port_chains().items() if not NOT_A_HARBOUR.search(c)}
    elif _kind(pool) == "build":
        return {ch: bld_levels(ch) for _r, ch in rare_chains(pool[1])}
    else:
        _tr, perm, _cp, _t, _rc, sp = srm.load()
        if _kind(pool) == "settlement":
            tpls = {r["slot_template"] for r in sp if r["slot_type"] == "primary"}
            chains = {c for t in tpls for c in perm.get(t, ()) if not SETTLE_SKIP.search(c)}
            if pool != "settlement":
                chains = {c for c in chains if race(c) in pool[1:]}
        elif pool in KIND_CHAINS:
            chains = set(KIND_CHAINS[pool])
        else:   # ("mine", res, ...): the resource chains on templates carrying those deposits
            tpls = {t for t, res in _tr.items() if res in pool[1:]}
            chains = {c for t in tpls for c in perm.get(t, ()) if "resource" in c and not NOT_A_MINE.search(c)}
        out = _chain_levels(frozenset(chains))
    return {c: v for c, v in out.items() if not EXCLUDE.search(c)}


@functools.lru_cache(None)
def settlement_tiers():
    """Every main-settlement level -> its tier (0 = the chain's first level), ranked by its LEVEL
    NUMBER, not its place in the list: daemon chains carry two buildings per level (an _a variant)
    and some chains list a level-0 _ruins first. Ruins get no tier. No EXCLUDE: a store is the
    settlement's whoever owns it, and CA's own production fills Tomb Kings and Nagash stores too."""
    _tr, perm, _cp, _t, _rc, sp = srm.load()
    tpls = {r["slot_template"] for r in sp if r["slot_type"] == "primary"}
    chains = {c for t in tpls for c in perm.get(t, ()) if not SETTLE_SKIP.search(c)}
    by = collections.defaultdict(list)
    for r in db("building_levels_tables")[1]:
        if r["chain"] in chains and "ruin" not in r["level_name"]:
            by[r["chain"]].append(r)
    out = {}
    for rows in by.values():
        nums = sorted({r["level"] for r in rows})
        out.update({r["level_name"]: nums.index(r["level"]) for r in rows})
    return out


def _kind(pool):
    return pool if isinstance(pool, str) else pool[0]


@functools.lru_cache(None)
def _signals():
    import guess_region_commodities as grc
    return grc.signals()


@functools.lru_cache(None)
def _map_data():
    """Region keys and region groups the expressions may name: vanilla plus every SUBMODS pack."""
    regions = {r["key"] for r in db("regions_tables")[1]}
    groups = {r["region_group"] for r in db("regions_to_region_groups_junctions_tables")[1]}
    for sm in SUBMODS.values():
        if os.path.isfile(sm["pack"]):
            for _p, _v, rs in rvd.load(sm["pack"], "regions_tables"):
                regions |= {r["key"] for r in rs}
            for _p, _v, rs in rvd.load(sm["pack"], "regions_to_region_groups_junctions_tables"):
                groups |= {r["region_group"] for r in rs}
    return frozenset(regions), frozenset(groups)


CLIMATE_STATES = ("suitable", "unsuitable", "uninhabitable")


def render(c):
    """A condition as CA's building-effect expression (the root is the building; Region. is its region)."""
    op, a = c
    if op == "places":
        return render(REG(*_place_tails(a)))
    if op in ("and", "or"):
        return "(" + (" && " if op == "and" else " || ").join(render(p) for p in a) + ")"
    if op == "not":
        return "!" + render(a)
    if op == "clim":   # CA's own MountainClimate form: the three climate bundles of that climate
        return "(" + " || ".join('Region.IsEffectBundleActive("wh3_dlc20_climate_%s_%s")'
                                 % (s, n[len("climate_"):]) for n in a for s in CLIMATE_STATES) + ")"
    if op == "area":
        groups = _map_data()[1]
        names = [p % n for n in a for p in ("cai_region_hint_area_%s", "cai_region_hint_sub_area_%s",
                                             "cai_chaos_region_hint_area_%s",
                                             "cai_chaos_region_hint_sub_area_%s") if p % n in groups]
        for n in a:
            assert any(n in g for g in names), "no region group for area %s" % n
        return "(" + " || ".join('Region.BelongsToRegionGroup("%s")' % g for g in names) + ")"
    if op == "dep":
        return "(" + " || ".join('Region.HasResource("%s")' % r for r in a) + ")"
    if op == "port":
        return "Region.IsPort == true"
    if op == "origin":
        return "Region.IsOriginatingSubcultureOneOf(%s)" % ",".join('"%s"' % ORIGINS[o] for o in a)
    if op == "reg":
        keys = sorted(k for k in _map_data()[0] if k.rsplit("_region_", 1)[-1] in a)
        for tail in a:
            assert any(k.endswith("_region_" + tail) for k in keys), "no region %s" % tail
        return "Region.RecordKeyIsOneOf(%s)" % ",".join('"%s"' % k for k in keys)
    raise ValueError(op)


def evaluate(c, g):
    """The same condition, on one region's signals from guess_region_commodities."""
    if c is None:
        return True
    op, a = c
    if op == "places":
        return g["tail"] in _place_tails(a)
    if op == "and":
        return all(evaluate(p, g) for p in a)
    if op == "or":
        return any(evaluate(p, g) for p in a)
    if op == "not":
        return not evaluate(a, g)
    if op == "clim":
        return g["climate"] in a
    if op == "area":
        return bool(g["areas"] & set(a))
    if op == "dep":
        return bool(g["deposits"] & set(a))
    if op == "port":
        return g["coastal"]
    if op == "origin":
        return g["origin"] in a
    if op == "reg":
        return g["tail"] in a
    raise ValueError(op)


def reaches(good, g):
    """Can this region make the good: some source's building can stand here and its rule holds."""
    for pool, cond in good_spec(good)["sources"]:
        kind = _kind(pool)
        if kind == "port" and not g["coastal"]:
            continue
        if kind == "mine" and not g["deposits"] & set(pool[1:]):
            continue
        if evaluate(cond, g):
            return True
    return False


def cond_key(good, i):
    return "derpy_mr_%s_%s" % (good, i)


def _table_frag(tk, frag):
    """'building_effects_junction_tables:ca' -> ('building_effects_junction_tables', frag + '_ca')."""
    table, _, part = tk.partition(":")
    return table, frag + ("_" + part if part else "")


def store_rows(t):
    """Every store twin: the ones on our production rows, then the ones on CA's."""
    return ([r for r in t["building_effects_junction_tables"][2]
             if r["effect"].startswith("derpy_mr_store_") and r["effect"] != STORE_CAP_FX]
            + list(t["building_effects_junction_tables:ca"][2]))


def _stores(t, add, loc):
    """The 54 stores: pools, factor, junctions, reach, feed effects and their bindings, loc."""
    stems = store_stems()
    donor, = [r for r in db("pooled_resources_tables")[1] if r["key"] == STORE_DONOR]
    fx_rows = {r["effect"]: r for r in db("effects_tables")[1]}
    fx_rows.update({r["effect"]: r for r in t["effects_tables"][2]})   # ours, built above
    add("pooled_resource_factors_tables", {"key": STORE_FACTOR, "is_hidden": False})
    loc += [("pooled_resource_factors_display_name_positive_" + STORE_FACTOR, "Stocked"),
            ("pooled_resource_factors_display_name_negative_" + STORE_FACTOR, "Stocked")]
    for kind, pos, neg in FLOW_FACTORS:
        add("pooled_resource_factors_tables", {"key": flow_factor(kind), "is_hidden": False})
        loc += [("pooled_resource_factors_display_name_positive_" + flow_factor(kind), pos),
                ("pooled_resource_factors_display_name_negative_" + flow_factor(kind), neg)]
    for stem, (_res, fx, name) in stems.items():
        add("pooled_resources_tables", dict(donor, key=store(stem), maximum=STORE_BASE, minimum=0,
                                            ai_ignored=True, default_factor="other", optional_icon_path="",
                                            income_policy="END_OF_ROUND", scope="REGION"))
        add("pooled_resource_factor_junctions_tables", {
            "unique_id": store_fx(stem), "factor": STORE_FACTOR, "resource": store(stem),
            "minimum": 0, "maximum": 2147483647, "specific_faction_set": "", "sort_order": 0})
        for kind, _pos, _neg in FLOW_FACTORS:
            add("pooled_resource_factor_junctions_tables", {
                "unique_id": flow_junction(stem, kind), "factor": flow_factor(kind),
                "resource": store(stem), "minimum": -2147483647, "maximum": 2147483647,
                "specific_faction_set": "", "sort_order": 0})
        add("campaign_group_pooled_resources_tables",
            {"campaign_group": "wh_main_feature_all", "resource": store(stem), "initial_amount": 0})
        add("effects_tables", dict(fx_rows[fx], effect=store_fx(stem)))
        add("effect_bonus_value_pooled_resource_factor_junctions_tables",
            {"bonus_value_id": "base_amount", "effect": store_fx(stem), "resource_factor": store_fx(stem)})
        loc += [("pooled_resources_display_name_" + store(stem), name),
                ("pooled_resources_description_" + store(stem),
                 "%s kept in this settlement's stores. They fill each turn with what its buildings make." % name),
                ("pooled_resources_positive_factors_display_name_" + store(stem), "Stocked"),
                ("pooled_resources_negative_factors_display_name_" + store(stem), "Used"),
                ("effects_description_" + store_fx(stem), "%s stocked: %%n" % name)]
    by_fx = {fx: stem for stem, (_r, fx, _n) in stems.items()}
    ours = [r for r in t["building_effects_junction_tables"][2] if r["effect"] in by_fx]
    theirs = [r for r in db("building_effects_junction_tables")[1]
              if r["effect"] in by_fx and r["effect_scope"] == "building_to_building_own"]
    for part, src in (("", ours), ("ca", theirs)):
        for r in src:   # same level, values and lore condition; the store is the settlement's own
            add("building_effects_junction_tables",
                dict(r, effect=store_fx(by_fx[r["effect"]]), effect_scope="region_to_region_own"), part)
    cap, = [r for r in db("effects_tables")[1] if r["effect"] == CAP_FX_DONOR]
    add("effects_tables", dict(cap, effect=STORE_CAP_FX))
    for stem in stems:   # one effect raises all 54 (CA binds one effect to five pools the same way)
        add("effect_bonus_value_pooled_resource_junctions_tables",
            {"bonus_value_id": "maximum_mod", "effect": STORE_CAP_FX, "pooled_resource": store(stem)})
    for lvl, n in sorted(settlement_tiers().items()):
        v = float(STORE_STEP * min(n, STORE_TOP))
        if v:   # damaged keeps the space: a shrinking store would destroy goods
            add("building_effects_junction_tables", {
                "building": lvl, "effect": STORE_CAP_FX, "effect_scope": "region_to_region_own",
                "value": v, "value_damaged": v, "value_ruined": 0.0, "context_requirement": ""})
    loc.append(("effects_description_" + STORE_CAP_FX, "Space in this settlement's stores: +%n of each resource"))


def build():
    t = {}

    def add(table, row, part=""):
        ver, van = db(table)
        cols = list(van[0].keys())
        assert list(row) == cols, "%s columns %s != CA's %s" % (table, list(row), cols)
        t.setdefault(table + (":" + part if part else ""), (ver, cols, []))[2].append(row)

    van_made = {(r["building"], r["effect"]) for r in db("building_effects_junction_tables")[1]}

    def produce(good, e):
        """One production row per level of each source's pool, gated by the source's condition."""
        g = good_spec(good)
        for i, (pool, cond) in enumerate(g["sources"]):
            req = ""
            if cond is not None:
                req = cond_key(good, i)
                # display_only_active_effects: the tooltip shows the line only where it applies
                add("building_effect_context_expressions_tables", {
                    "expression": render(cond), "key": req,
                    "display_only_active_effects": True, "always_show_display_text": False})
            for c, levels in sorted(pool_chains(pool).items()):
                table = TABLES[_kind(pool)]
                for n, lvl in enumerate(levels):
                    if (lvl, e) in van_made:   # CA already makes it here; its row stands
                        continue
                    v = float(max(1, round(table[min(n, len(table) - 1)] * g.get("scale", 1.0))))
                    add("building_effects_junction_tables", {   # damaged = half, as CA's own rows
                        "building": lvl, "effect": e, "effect_scope": "building_to_building_own",
                        "value": v, "value_damaged": damaged(v), "value_ruined": 0.0,
                        "context_requirement": req})

    loc = []
    donor, = [r for r in db("resources_tables")[1] if r["key"] == DONOR]
    dfx, = [r for r in db("effects_tables")[1] if r["effect"] == "wh_main_effect_region_resource_salt_production"]
    for unit, (one, many) in UNITS.items():
        add("commodity_unit_names_tables", {"unit": unit})
        loc += [("commodity_unit_names_singular_" + unit, one), ("commodity_unit_names_plural_" + unit, many)]
    for good, g in GOODS.items():
        k, e = key(good), effect(good)
        add("resources_tables", dict(donor, key=k, unit=g["unit"],
                                     icon_filepath="ui\\campaign ui\\effect_bundles\\%s.png" % icon(good)))
        for r in db("resources_to_campaign_junctions_tables")[1]:
            if r["resource"] == DONOR:
                add("resources_to_campaign_junctions_tables", dict(r, resource=k))
        add("commodities_tables", {"key": k, "baseline_price_per_unit": g["price"]})
        for r in db("cai_personality_strategic_resource_values_tables")[1]:
            if r["resource"] == DONOR:
                add("cai_personality_strategic_resource_values_tables", dict(r, resource=k))
        add("effects_tables", dict(dfx, effect=e, icon=icon(good) + ".png",
                                   icon_negative=icon(good) + ".png"))
        add("effect_bonus_value_resource_junction_tables",
            {"effect": e, "bonus_value_id": "production", "resource": k})
        produce(good, e)
        unit = UNITS.get(g["unit"], (None, g["unit"]))[1]
        loc += [("resources_onscreen_text_" + k, g["name"]),
                ("resources_description_" + k, g["desc"]),
                ("resources_long_description_" + k, ""),
                ("effects_description_" + e, "%s resource production: %%n %s" % (g["name"], unit)),
                ("uied_component_texts_localised_string_%s_Tooltip" % label_id(good), tooltip(good))]
    for good, g in CA_GOODS.items():   # CA's goods: rows only, on CA's own effect and loc
        produce(good, g["effect"])
    # the rare goods' own buildings, every wide row cloned off one vanilla three-level chain
    chain_row, = [r for r in db("building_chains_tables")[1] if r["key"] == BUILD_DONOR]
    lvl_rows = sorted((r for r in db("building_levels_tables")[1] if r["chain"] == LEVEL_DONOR),
                      key=lambda r: r["level"])[:3]
    var_row, = [r for r in db("building_culture_variants_tables")[1]
                if r["building"] == lvl_rows[0]["level_name"]]
    rosters = db("building_chain_availabilities_tables")[1]
    for good, spec in RARE.items():
        stem, req = bld_stem(good), cond_key(good, "bld")
        add("building_effect_context_expressions_tables", {   # the lore gate: every row below
            "expression": render(rare_cond(good)), "key": req,
            "display_only_active_effects": True, "always_show_display_text": False})
        for race_, ch in rare_chains(good):
            add("building_superchains_tables", {"key": ch})
            add("building_chains_tables", dict(chain_row, key=ch, building_superchain=ch))
            add("building_instances_tables", {"key": ch, "num_instances": 1})
            for s in [GENERIC_SET] + ([WEF_SET] if race_ == "wef" else []):
                add("building_chain_set_items_tables", {"chain": ch, "remove": False, "set": s, "super_chain": ""})
            add("building_set_to_building_junctions_tables",   # ONE set: the game uses only one
                {"building_chain": ch, "building_level": "", "building_set": ECON_SET[race_], "exclude": False})
            for sid in sorted({r["set_id"] for r in rosters   # every roster of the culture, faction ones too
                               if r["culture"] == CULTURES[race_] and not r["campaign"]}):
                add("building_chain_availability_sets_tables", {"building_chain": ch, "id": sid})
            for n, (lvl, name, donor) in enumerate(zip(bld_levels(ch), spec["levels"], lvl_rows)):
                add("building_levels_tables", dict(donor, level_name=lvl, chain=ch, building_instance_key=ch))
                add("building_culture_variants_tables", dict(var_row, building=lvl, description=stem,
                                                             icon=stem, short_description=stem))
                rows = [(effect(good), "building_to_building_own", RARE_TABLE[n]),
                        (RARE_GDP[0], "building_to_building_own", RARE_GDP[1][n])]
                for who, kind, fx in BONUS[good]:   # this race's bonus, and any everyone's
                    scope, vals = BONUS_KINDS[kind]
                    if vals[n] and who in (None, race_):
                        rows.append((fx, scope, vals[n]))
                for fx, scope, v in rows:
                    add("building_effects_junction_tables", {
                        "building": lvl, "effect": fx, "effect_scope": scope, "value": float(v),
                        "value_damaged": damaged(v), "value_ruined": 0.0, "context_requirement": req})
                loc.append(("building_culture_variants_name_" + lvl, name))
            loc.append(("building_chains_chain_tooltip_" + ch, GOODS[good]["name"]))
        text = "%s %s Anywhere else it makes nothing." % (GOODS[good]["desc"], spec["where"])
        loc += [("building_short_description_texts_short_description_" + stem, text),
                ("building_description_texts_long_description_" + stem, text)]
    _stores(t, add, loc)
    _bundles(add, loc)
    return t, loc


def _bundles(add, loc):
    """Phase 4's three region bundles, their effects and loc."""
    donor, = [r for r in db("effect_bundles_tables")[1] if r["key"] == BUNDLE_DONOR]
    for _use, key, icon_, title, desc, fx in USE_BUNDLES:
        add("effect_bundles_tables", dict(donor, key=key, localised_title=title, localised_description=desc,
                                          ui_icon=icon_))
        for e, scope, v in fx:
            add("effect_bundles_to_effects_junctions_tables", {
                "effect_bundle_key": key, "effect_key": e, "effect_scope": scope, "value": float(v),
                "advancement_stage": "start_turn_completed"})
        loc += [("effect_bundles_localised_title_" + key, title),
                ("effect_bundles_localised_description_" + key, desc)]
    donor, = [r for r in db("effect_bundles_tables")[1] if r["key"] == ORDER_DONOR]
    for _k, _use, key, icon_, title, what, fx in ORDERS:
        desc = "Paid for from your stores: %s." % what
        add("effect_bundles_tables", dict(donor, key=key, localised_title=title, localised_description=desc,
                                          ui_icon=icon_))
        for e, scope, v in fx:
            add("effect_bundles_to_effects_junctions_tables", {
                "effect_bundle_key": key, "effect_key": e, "effect_scope": scope, "value": float(v),
                "advancement_stage": "start_turn_completed"})
        loc += [("effect_bundles_localised_title_" + key, title),
                ("effect_bundles_localised_description_" + key, desc)]


def all_bundles():
    """(target, key, icon, effects) of every bundle this pack mints."""
    return [("region", k, i, fx) for _u, k, i, _t, _d, fx in USE_BUNDLES] + \
           [("faction", k, i, fx) for _o, _u, k, i, _t, _w, fx in ORDERS]


def check_bundles(t, loc):
    """Each bundle is a region bundle with its loc; every effect and scope is CA's; every value
    is a bonus by its effect's own sign; the icon is in CA's ui packs."""
    import gen_mr_emitter as E
    keys = dict(loc)
    rows = {r["key"]: r for r in t["effect_bundles_tables"][2]}
    van_fx = {r["effect"]: r for r in db("effects_tables")[1]}
    scopes = {r["key"] for r in db("campaign_effect_scopes_tables")[1]}
    have = E._game_assets()
    fx = t["effect_bundles_to_effects_junctions_tables"][2]
    for target, key, icon_, effects in all_bundles():
        b = rows[key]
        assert b["bundle_target"] == target and b["ui_icon"] == icon_, b
        assert "ui/campaign ui/effect_bundles/" + icon_ in have, "no such bundle icon: %s" % icon_
        for pre in ("effect_bundles_localised_title_", "effect_bundles_localised_description_"):
            assert keys.get(pre + key), pre + key
        got = [(r["effect_key"], r["effect_scope"], r["value"]) for r in fx if r["effect_bundle_key"] == key]
        assert got == [(e, s, float(v)) for e, s, v in effects], (key, got)
        for e, s, v in got:
            assert e in van_fx, "no CA effect %s" % e
            assert s in scopes, "no CA scope %s" % s
            assert (v > 0) == van_fx[e]["is_positive_value_good"], "%s %s is a penalty" % (key, e)
    assert len(rows) == len(all_bundles()), sorted(rows)


AUDIT = os.path.join(ROOT, "Modding Files", "reference", "resource_overhaul_building_audit.md")


def audit():
    """Every building that makes a good, by its in-game NAME and description (CA's loc), beside
    what it makes - the table to read a pool against. Written to AUDIT."""
    import read_vanilla_loc as rvl
    names, shorts = rvl.load("building_culture_variants"), rvl.load("building_short_description_texts")

    def look(table, prefix, lvl):
        k = prefix + lvl
        if k in table:
            return table[k]
        hits = sorted(v for kk, v in table.items() if kk.startswith(k) and not v.startswith("{{"))
        return hits[0] if hits else "?"
    made = collections.defaultdict(set)
    levels = {}
    for good, spec in GOODS.items():
        for pool, _c in spec["sources"]:
            for ch, lv in pool_chains(pool).items():
                made[ch].add((_kind(pool), good))
                levels[ch] = lv
    by_pool = collections.defaultdict(list)
    for ch, gs in made.items():
        by_pool[" + ".join(sorted({k for k, _g in gs}))].append(ch)
    out = ["# Derpy Resource Overhaul - what each building makes", "",
           "Generated by `py tools/gen_resource_overhaul.py --audit`. Names and descriptions are CA's own",
           "loc; a good only appears in game where its lore condition holds for the region", ""]
    for pool in sorted(by_pool):
        out += ["## %s (%d buildings)" % (pool, len(by_pool[pool])), "",
                "| Building (levels) | Chain | Makes |", "|---|---|---|"]
        for ch in sorted(by_pool[pool], key=lambda c: look(names, "building_culture_variants_name_", levels[c][0])):
            nm = " / ".join(look(names, "building_culture_variants_name_", l) for l in levels[ch])
            out.append("| %s | `%s` | %s |" % (nm, ch, ", ".join(sorted(g for _k, g in made[ch]))))
        out.append("")
    out += ["## The rare goods' own buildings", "", "| Building (levels) | Chain | Makes | Bonus |", "|---|---|---|---|"]
    for good, spec in RARE.items():
        for race_, ch in rare_chains(good):
            bonus = ", ".join(sorted({fx for who, _k, fx in BONUS[good] if who in (None, race_)}))
            out.append("| %s | `%s` | %s | %s |" % (" / ".join(spec["levels"]), ch, good, bonus))
    with io.open(AUDIT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    print("wrote", AUDIT, sum(len(v) for v in by_pool.values()), "buildings")


# THE AI BUILDS THE RARE BUILDINGS - BY SCRIPT, AND ONLY WHERE THEY WORK (user, 2026-10-01).
# The campaign AI scores a building only through cai_construction_system_building_values, and a
# row there is one flat score per chain: the AI would put Dragon Bone Digs in any settlement, and
# outside the lore regions the building makes nothing. So the chains get NO score row (the AI
# never picks them), and this script builds them instead, for AI factions, in the regions where
# rare_cond() holds - the same condition the building's rows are gated by, evaluated here on
# every region of IE, the Realm of Chaos and IEE's own. A region whose IEE deposit or origin is
# unreadable offline reads as no, so the error runs towards not building, never towards a dead one.
#
# PLAYER-LIKE: CA's price per level (LEVEL_DONOR's create_cost), the settlement tier each level
# needs, and a treasury reserve. cm:add_building_to_settlement picks the slot itself, and the
# building is looked for afterwards: gold is charged only for a building that is really there.
AI_LUA = os.path.join(PACK, "script", "campaign", "mod", "derpy_more_resources_ai.lua")
AI_PACE = 5        # turns between one AI faction's actions, staggered per faction
AI_RESERVE = 2     # it pays only while it holds this many times the price
AI_HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_resource_overhaul_ai_harness.lua")
LUA_EXE = r"C:\Program Files (x86)\Lua\5.1\lua.exe"

_AI_LOGIC = """
local function say(s) if out then out("derpy_mr_ai: " .. s) end end

-- Bounded, so float32 keeps it exact (the Exchange's EX.key_hash).
function MR_AI.hash(s)
    local h = 0
    for i = 1, #s do h = (h * 31 + string.byte(s, i)) % 65536 end
    return h
end

function MR_AI.due(fname, turn)
    return (turn + MR_AI.hash(fname)) % MR_AI.PACE == 0
end

-- "<chain>_<n>" -> n, by prefix, no pattern: chain keys are plain and a pattern match would read
-- "black_lotus" as the start of "black_lotus_def".
function MR_AI.level_in(chain, bname)
    local pre = chain .. "_"
    if string.sub(bname, 1, #pre) ~= pre then return nil end
    return tonumber(string.sub(bname, #pre + 1))
end

function MR_AI.tier(region)
    local ok, t = pcall(function()
        return region:settlement():primary_slot():building():building_level()
    end)
    return ok and t or 0
end

-- The slot holding this chain in the region, and its level.
function MR_AI.find(region, chain)
    local slots = region:slot_list()
    for i = 0, slots:num_items() - 1 do
        local s = slots:item_at(i)
        if s:has_building() then
            local n = MR_AI.level_in(chain, s:building():name())
            if n then return s, n end
        end
    end
    return nil, nil
end

-- What this faction may build: {good, chain, region} for every owned lore region.
function MR_AI.options(faction)
    local out_, culture = {}, faction:culture()
    local regions = faction:region_list()
    for _, good in ipairs(MR_AI.GOODS) do
        local chain = (MR_AI.CHAIN[good] or {})[culture]
        if chain then
            for i = 0, regions:num_items() - 1 do
                local r = regions:item_at(i)
                if MR_AI.REGIONS[good][r:name()] then out_[#out_ + 1] = { good, chain, r } end
            end
        end
    end
    return out_
end

-- ONE ACTION, OR NONE. An upgrade first - a building the faction already owns, whose next level
-- the settlement's tier allows - then a new building. Returns what it did, for the log and the
-- harness.
function MR_AI.act(faction)
    local fname = faction:name()
    local opts = MR_AI.options(faction)
    if #opts == 0 then return nil end
    local function afford(cost) return faction:treasury() >= cost * MR_AI.RESERVE end
    for _, o in ipairs(opts) do
        local slot, n = MR_AI.find(o[3], o[2])
        if slot and n < 3 and MR_AI.tier(o[3]) >= MR_AI.REQ[n + 1] and afford(MR_AI.COST[n + 1]) then
            local want = o[2] .. "_" .. (n + 1)
            cm:instantly_upgrade_building_in_region(slot, want)
            local got = MR_AI.find(o[3], o[2])
            if got and got:building():name() == want then
                cm:treasury_mod(fname, -MR_AI.COST[n + 1])
                say(fname .. " upgraded " .. want .. " in " .. o[3]:name())
                return "upgrade " .. want .. " " .. o[3]:name()
            end
            say(fname .. " could not upgrade to " .. want .. " in " .. o[3]:name())
        end
    end
    for _, o in ipairs(opts) do
        if not MR_AI.find(o[3], o[2]) and MR_AI.tier(o[3]) >= MR_AI.REQ[1] and afford(MR_AI.COST[1]) then
            local want = o[2] .. "_1"
            cm:add_building_to_settlement(o[3]:name(), want)
            if MR_AI.find(o[3], o[2]) then
                cm:treasury_mod(fname, -MR_AI.COST[1])
                say(fname .. " built " .. want .. " in " .. o[3]:name())
                return "build " .. want .. " " .. o[3]:name()
            end
            -- no free slot that takes it: try the next region, and say so once in the log
            say(fname .. " found no slot for " .. want .. " in " .. o[3]:name())
        end
    end
    return nil
end

function MR_AI.turn(faction)
    if faction:is_human() or faction:is_dead() then return nil end
    if not MR_AI.due(faction:name(), cm:model():turn_number()) then return nil end
    local ok, did = pcall(MR_AI.act, faction)
    if not ok then say("error for " .. faction:name() .. ": " .. tostring(did)) return nil end
    return did
end

if core then
    core:add_listener("derpy_mr_ai", "FactionTurnStart", true,
        function(context) MR_AI.turn(context:faction()) end, true)
end
"""


def ai_regions():
    """good -> sorted region keys where its building works, over IE, RoC and every SUBMODS map."""
    sig = list(_signals().values())
    for name in SUBMODS:
        if os.path.isfile(SUBMODS[name]["pack"]):
            sig += list(submod_signals(name).values())
    return {good: sorted({g["region"] for g in sig if evaluate(rare_cond(good), g)}) for good in RARE}


def ai_script():
    lvl = sorted((r for r in db("building_levels_tables")[1] if r["chain"] == LEVEL_DONOR),
                 key=lambda r: r["level"])[:3]
    regions = ai_regions()
    lines = ["-- Derpy Resource Overhaul: the AI builds the rare goods' buildings, only where they work.",
             "-- GENERATED by tools/gen_resource_overhaul.py (ai_script). Edit the generator, not this file.",
             "MR_AI = {}",
             "MR_AI.PACE = %d" % AI_PACE,
             "MR_AI.RESERVE = %d" % AI_RESERVE,
             "MR_AI.COST = { %s }" % ", ".join(str(int(r["create_cost"])) for r in lvl),
             "MR_AI.REQ = { %s }   -- the settlement tier each level needs" % ", ".join(
                 str(int(r["primary_slot_building_building_level_requirement"])) for r in lvl),
             "MR_AI.GOODS = { %s }" % ", ".join('"%s"' % g for g in sorted(RARE)),
             "MR_AI.CHAIN = {"]
    for good in sorted(RARE):
        lines.append("    %s = { %s }," % (good, ", ".join(
            '%s = "%s"' % (CULTURES[race_], ch) for race_, ch in rare_chains(good))))
    lines.append("}")
    lines.append("MR_AI.REGIONS = {")
    for good in sorted(RARE):
        lines.append("    %s = {" % good)
        for k in regions[good]:
            lines.append('        ["%s"] = true,' % k)
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n" + _AI_LOGIC


def check_ai(text):
    """The script must agree with build(): every chain and level it names is one build() mints,
    every culture is one its chain is rostered for, and every good has somewhere to build."""
    import subprocess, tempfile
    t, _loc = build()
    levels = {r["level_name"] for r in t["building_levels_tables"][2]}
    for good in RARE:
        for race_, ch in rare_chains(good):
            assert '%s = "%s"' % (CULTURES[race_], ch) in text, (good, race_)
            assert all(l in levels for l in bld_levels(ch)), ch
    regions = ai_regions()
    assert all(regions[g] for g in RARE), [g for g in RARE if not regions[g]]
    if not os.path.isfile(LUA_EXE):
        return
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        script = fh.name
    try:
        harness = io.open(AI_HARNESS, encoding="utf-8").read().replace("__SCRIPT__", script.replace("\\", "/"))
        with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
            fh.write(harness)
            hpath = fh.name
        got = subprocess.run([LUA_EXE, hpath], capture_output=True, text=True)
        os.unlink(hpath)
    finally:
        os.unlink(script)
    assert got.returncode == 0 and "harness ok" in got.stdout, got.stdout + got.stderr
    return got.stdout


def reach_table():
    """good -> {campaign: regions it can be made in}, from the region signals."""
    out = {}
    for good in list(GOODS) + list(CA_GOODS):
        n = collections.Counter()
        for g in _signals().values():
            if reaches(good, g):
                n[g["campaign"]] += 1
        out[good] = n
    return out


def check(t, loc):
    """Fail on anything that would load wrong or silently do nothing."""
    check_bundles(t, loc)
    import guess_region_commodities as grc
    import gen_commodity_icons
    # every good has an icon, a lore rule, and is one of the 26
    assert sorted(GOODS) == sorted(gen_commodity_icons.ICONS), set(GOODS) ^ set(gen_commodity_icons.ICONS)
    # every key we mint is new; every key we point at exists
    van_res = {r["key"] for r in db("resources_tables")[1]}
    van_fx = {r["effect"] for r in db("effects_tables")[1]}
    van_lvl = {r["level_name"] for r in db("building_levels_tables")[1]}
    van_units = {r["unit"] for r in db("commodity_unit_names_tables")[1]}
    van_ctx = {r["key"] for r in db("building_effect_context_expressions_tables")[1]}
    van_bundles = {r["key"] for r in db("effect_bundles_tables")[1]}
    for good, g in GOODS.items():
        assert key(good) not in van_res and effect(good) not in van_fx, good
        assert g["unit"] in van_units or g["unit"] in UNITS, (good, g["unit"])
        for size in ("small", "large"):
            assert os.path.exists(os.path.join(ICONS, size, good + ".png")), (good, size)
    assert not set(UNITS) & van_units
    ctx = {r["key"]: r["expression"] for r in t["building_effect_context_expressions_tables"][2]}
    assert len(ctx) == len(t["building_effect_context_expressions_tables"][2]), "duplicate condition key"
    assert not set(ctx) & van_ctx
    names = set(re.findall(r'"([^"]+)"', " ".join(ctx.values())))
    regions, groups = _map_data()
    for n in names:   # every string an expression names is a real key of its kind
        assert (n in van_bundles or n in groups or n in regions or n in van_res
                or n in ORIGINS.values()), "expression names unknown key %s" % n
    ours = {l for g in RARE for _r, ch in rare_chains(g) for l in bld_levels(ch)}
    made = {effect(g) for g in GOODS}
    seen = set()
    for r in t["building_effects_junction_tables"][2]:
        assert r["building"] in van_lvl or r["building"] in ours, r
        store_row = r["effect"].startswith("derpy_mr_store_")
        assert store_row or not EXCLUDE.search(r["building"]), r   # stores follow CA's own rows
        assert r["value_damaged"] == (r["value"] if r["effect"] == STORE_CAP_FX else damaged(r["value"])), r
        assert r["effect"] not in made or r["value"] >= 1, r
        assert not r["context_requirement"] or r["context_requirement"] in ctx, r
        assert (r["building"], r["effect"]) not in seen, "two sources give %s %s" % (r["building"], r["effect"])
        seen.add((r["building"], r["effect"]))
    for good in GOODS:   # every good has rows
        assert any(r["effect"] == effect(good) for r in t["building_effects_junction_tables"][2]), good
    # CA's goods: CA's own effect, bound to that good, and no row of ours lands on a CA row's key
    assert not set(CA_GOODS) & set(GOODS)
    van_bind = {(r["effect"], r["bonus_value_id"]): r["resource"] for r in db("effect_bonus_value_resource_junction_tables")[1]}
    for good, g in CA_GOODS.items():
        assert van_bind.get((g["effect"], "production")) == g["res"], (good, g["effect"])
        assert any(r["effect"] == g["effect"] for r in t["building_effects_junction_tables"][2]), good
    van_made = {(r["building"], r["effect"]) for r in db("building_effects_junction_tables")[1]}
    clash = [r for r in t["building_effects_junction_tables"][2] if (r["building"], r["effect"]) in van_made]
    assert not clash, "rows on a key CA already uses: %s" % clash[:3]
    # the donor's footprint is copied whole: same row count per table as Salt has
    for table, want in (("resources_to_campaign_junctions_tables", 2),
                        ("cai_personality_strategic_resource_values_tables", 78)):
        assert len(t[table][2]) == want * len(GOODS), (table, len(t[table][2]))
    bound = {r["effect"] for r in t["effect_bonus_value_resource_junction_tables"][2]}
    assert bound == {effect(g) for g in GOODS}
    # THE LORE PARITY: what ships reaches exactly the regions the rules table names, per region
    rules = dict((c, test) for c, test, _l in grc.RULES + grc.CA_RULES)
    assert sorted(c for c, _t, _l in grc.CA_RULES) == sorted(CA_GOODS)
    for good in list(GOODS) + list(CA_GOODS):
        diff = [g["region"] for g in _signals().values() if reaches(good, g) != bool(rules[good](g))]
        assert not diff, "%s: shipped rule and rules table disagree on %d regions, e.g. %s" % (
            good, len(diff), diff[:4])
    # the excluded owners really were in the pools, so the filter is doing something
    gone = sorted(c for c in port_chains() if EXCLUDE.search(c))
    assert {"wh3_main_dae_port", "wh2_dlc09_tmb_port", "wh3_dlc29_nag_port"} <= set(gone), gone
    assert {"wh_main_EMPIRE_port", "wh2_main_hef_port", "wh_main_special_marienburg_port",
            "wh3_dlc23_chd_tower_port"} <= set(pool_chains("port")), "port pool lost a chain"
    assert not {"wh3_dlc23_chd_factory_port", "wh3_dlc23_chd_outpost_port",
                "wh2_dlc13_lzd_port_nakai_itzl"} & set(pool_chains("port")), "a non-harbour is fishing"
    assert "wh_main_DWARF_resource_iron_military" not in pool_chains(("mine", "res_rom_iron")), "a forge is mining"
    assert {"wh_main_EMPIRE_settlement_major", "wh3_dlc23_chd_settlement_factory",
            "wh3_main_cth_settlement_major"} <= set(pool_chains("settlement")), "settlement pool"
    assert "wh_main_DWARFS_resource_iron" in pool_chains(("mine", "res_rom_iron"))
    # every listed economy chain exists and can be built in an ordinary (secondary) slot
    _tr, perm, _cp, _t, _rc, sp = srm.load()
    sec = {c for r in sp if r["slot_type"] == "secondary" for c in perm.get(r["slot_template"], ())}
    for kind, chains in KIND_CHAINS.items():
        bad = [c for c in chains if c not in sec]
        assert not bad, "%s chains not buildable in a secondary slot: %s" % (kind, bad)
        assert all(race(c) for c in chains), "%s chain with no race tag" % kind
    # lore: these make no farm/industry goods of their own - a fallback must not creep back in
    for kind, races in (("farm", {"chd", "nor", "vmp"}), ("craft", {"nor", "vmp"}),
                        ("vineyard", set(CULTURES) - {"brt", "emp", "hef"})):
        leak = sorted(c for c in pool_chains(kind) if race(c) in races)
        assert not leak, "%s pool reaches %s: %s" % (kind, races, leak)
    hall = pool_chains(("settlement", "nor"))
    assert hall and all(race(c) == "nor" for c in hall), "Norscan mead hall pool"
    check_rare(t, ours)
    check_stores(t, loc)
    assert len(loc) == n_loc() and len(dict(loc)) == len(loc), "loc count or duplicate loc key"
    return gone


def check_rare(t, ours):
    """The rare buildings: new keys, real rosters/sets/icons, and NOTHING made outside the lore."""
    import read_pack_index as rpi
    import guess_region_commodities as grc
    assert set(RARE) <= set(GOODS)
    van_chains = {r["key"] for r in db("building_chains_tables")[1]}
    van_lvl = {r["level_name"] for r in db("building_levels_tables")[1]}
    chains = {ch: (g, r) for g in RARE for r, ch in rare_chains(g)}
    assert not (set(chains) & van_chains) and not (ours & van_lvl), "rare key not new"
    assert set(CULTURES.values()) <= {r["key"] for r in db("cultures_tables")[1]}, "culture key"
    sets = {r["building_set"] for r in db("building_set_to_building_junctions_tables")[1]}
    assert set(ECON_SET.values()) <= sets, set(ECON_SET.values()) - sets
    rosters = db("building_chain_availabilities_tables")[1]
    icons = {p for p in rpi.paths(os.path.join(os.path.dirname(rvd.DB_PACK), "ui.pack"))
             if p.startswith("ui/buildings/icons/")}
    for good, spec in RARE.items():
        assert spec["frame"] is None or "ui/buildings/icons/%s.png" % spec["frame"] in icons, good
        assert os.path.exists(os.path.join(PACK, *bld_icon(good).split("/"))),             "no %s - run tools/gen_building_icons.py" % bld_icon(good)
        assert set(rare_races(good)) <= set(CULTURES), good
        assert len(spec["levels"]) == len(RARE_TABLE), good
    # a chain is filed under ONE building set - its own race's - and built by its own race only
    culture_of = {r["set_id"]: r["culture"] for r in rosters}
    bsets = collections.defaultdict(list)
    for r in t["building_set_to_building_junctions_tables"][2]:
        bsets[r["building_chain"]].append(r["building_set"])
    av = collections.defaultdict(set)
    for r in t["building_chain_availability_sets_tables"][2]:
        assert r["id"] in culture_of, r
        av[r["building_chain"]].add(r["id"])
    for ch, (good, race_) in chains.items():
        assert bsets[ch] == [ECON_SET[race_]], "%s building sets %s, want only %s" % (ch, bsets[ch], ECON_SET[race_])
        assert av[ch] and {culture_of[s] for s in av[ch]} == {CULTURES[race_]}, (ch, sorted(av[ch]))
    # the user's rule: the building gives nothing outside the lore - every row it has is gated
    van_fx = {r["effect"] for r in db("effects_tables")[1]}
    chain_of = {l: ch for ch in chains for l in bld_levels(ch)}
    rows = [r for r in t["building_effects_junction_tables"][2] if r["building"] in ours]
    for lvl in ours:
        good = chains[chain_of[lvl]][0]
        made = [r for r in rows if r["building"] == lvl and r["effect"] == effect(good)]
        assert len(made) == 1, "%s has %d production rows" % (lvl, len(made))
    for r in rows:
        good, race_ = chains[chain_of[r["building"]]]
        assert r["context_requirement"] == cond_key(good, "bld"), "ungated rare building row %s" % r
        assert r["effect"] in van_fx or r["effect"] in (effect(good), store_fx(good)), \
            "unknown effect %s" % r["effect"]   # its production, its store twin, or a CA bonus
        theirs = [w for w, _k, fx in BONUS[good] if fx == r["effect"]]
        assert not theirs or set(theirs) & {None, race_}, "%s carries another race's bonus %s" % (r["building"], r["effect"])
    for good in RARE:   # every race that can build it gets something of its own
        named = {race_ for race_, _k, _f in BONUS[good]}
        assert None in named or set(rare_races(good)) <= named, (good, set(rare_races(good)) - named)
        for race_, kind, _fx in BONUS[good]:
            assert kind in BONUS_KINDS and (race_ is None or race_ in rare_races(good)), (good, race_, kind)
    # and it reaches no region its good's lore rule does not
    rules = dict((c, test) for c, test, _l in grc.RULES)
    for good in RARE:
        loose = [g["region"] for g in _signals().values() if evaluate(rare_cond(good), g) and not rules[good](g)]
        assert not loose, "%s building reaches %d regions its lore does not, e.g. %s" % (good, len(loose), loose[:3])


def check_stores(t, loc):
    """The settlement stores (spec 2026-10-02-resource-overhaul-stores-design.md): 54 REGION pools,
    each reachable by every owner, each with its gain-only junction, base_amount binding and loc."""
    import read_vanilla_loc as rvl
    stems = store_stems()
    assert len(stems) == len(GOODS) + len(CA_STEMS) == 54, len(stems)
    assert not set(CA_STEMS.values()) & set(GOODS), "a CA stem shadows one of our goods"
    pools = {r["key"]: r for r in t["pooled_resources_tables"][2]}
    assert set(pools) == {store(s) for s in stems}, set(pools) ^ {store(s) for s in stems}
    for k, p in pools.items():
        assert (p["scope"], p["maximum"], p["minimum"], p["income_policy"]) == \
            ("REGION", STORE_BASE, 0, "END_OF_ROUND"), (k, p)
    j = {r["unique_id"]: r for r in t["pooled_resource_factor_junctions_tables"][2]}
    for s in stems:
        jr = j[store_fx(s)]
        assert jr["resource"] == store(s) and jr["factor"] == STORE_FACTOR, jr
        assert jr["minimum"] == 0 < jr["maximum"], "store junction must be gain-only: %s" % jr
    factors = {r["key"] for r in t["pooled_resource_factors_tables"][2]}
    for kind, pos, neg in FLOW_FACTORS:
        assert flow_factor(kind) in factors, "no factor %s" % flow_factor(kind)
        for s in stems:
            jr = j.get(flow_junction(s, kind))
            assert jr, "no flow junction %s" % flow_junction(s, kind)
            assert (jr["resource"], jr["factor"]) == (store(s), flow_factor(kind)), jr
            assert jr["minimum"] < 0 < jr["maximum"], "flow junction must be two-way: %s" % jr
    reach = {(r["campaign_group"], r["resource"]) for r in t["campaign_group_pooled_resources_tables"][2]}
    assert {("wh_main_feature_all", store(s)) for s in stems} <= reach, "a store no owner can reach"
    bind = {(r["effect"], r["resource_factor"]) for r in
            t["effect_bonus_value_pooled_resource_factor_junctions_tables"][2] if r["bonus_value_id"] == "base_amount"}
    assert bind == {(store_fx(s), store_fx(s)) for s in stems}, bind ^ {(store_fx(s), store_fx(s)) for s in stems}
    # every loc prefix we write is one CA's own pools use (a misspelt prefix shows the raw key)
    van = rvl.load("pooled_resources")
    keys = dict(loc)
    for pre in STORE_LOC:
        assert any(k.startswith(pre) for k in van), "no CA pool uses loc prefix %s" % pre
        for s in stems:
            assert keys.get(pre + store(s)), pre + store(s)
    for kind, pos, neg in FLOW_FACTORS:
        assert keys.get("pooled_resource_factors_display_name_positive_" + flow_factor(kind)) == pos, kind
        assert keys.get("pooled_resource_factors_display_name_negative_" + flow_factor(kind)) == neg, kind
    for s in stems:
        assert keys.get("effects_description_" + store_fx(s)), store_fx(s)
    by_fx = {fx: s for s, (_r, fx, _n) in stems.items()}
    rows = t["building_effects_junction_tables"][2]
    prod = [r for r in rows if r["effect"] in by_fx] + \
           [r for r in db("building_effects_junction_tables")[1]
            if r["effect"] in by_fx and r["effect_scope"] == "building_to_building_own"]
    twins = {(r["building"], r["effect"]): r for r in store_rows(t)}
    assert len(twins) == len(store_rows(t)), "two twins on one building and store"
    assert len(twins) == len(prod), "%d twins for %d production rows" % (len(twins), len(prod))
    for p in prod:
        tw = twins.get((p["building"], store_fx(by_fx[p["effect"]])))
        assert tw, "production row with no store twin: %s %s" % (p["building"], p["effect"])
        for c in ("value", "value_damaged", "value_ruined", "context_requirement"):
            assert tw[c] == p[c], "%s %s: twin %s=%r, production %r" % (p["building"], p["effect"], c, tw[c], p[c])
        assert tw["effect_scope"] == "region_to_region_own", tw
    # CA's rows' twins live in their own file, so the public repo can refuse it
    ca = {r["building"] for r in t["building_effects_junction_tables:ca"][2]}
    van_lvl = {r["building"] for r in db("building_effects_junction_tables")[1] if r["effect"] in by_fx}
    assert ca <= van_lvl, "a non-CA row in the _ca file"
    capb = {r["pooled_resource"] for r in t["effect_bonus_value_pooled_resource_junctions_tables"][2]
            if r["effect"] == STORE_CAP_FX and r["bonus_value_id"] == "maximum_mod"}
    assert capb == {store(s) for s in stems}, "capacity effect must raise every store"
    cap = {r["building"]: r for r in rows if r["effect"] == STORE_CAP_FX}
    n_cap = 0
    for lvl, n in settlement_tiers().items():
        want = float(STORE_STEP * min(n, STORE_TOP))
        got = cap[lvl]["value"] if lvl in cap else 0.0
        assert got == want, "%s (tier %d): space +%s, want +%s" % (lvl, n, got, want)
        if lvl in cap:
            n_cap += 1
            assert cap[lvl]["value_damaged"] == want, "damage must not shrink a store: %s" % lvl
            assert cap[lvl]["effect_scope"] == "region_to_region_own", cap[lvl]
    assert n_cap == len(cap), "capacity on a level that is not a main settlement"
    # Space follows the LEVEL NUMBER, never list position: daemon chains carry two buildings per
    # level (an _a variant) and some chains list a level-0 _ruins first (review, 2026-10-02).
    lvl_no = {r["level_name"]: (r["chain"], r["level"]) for r in db("building_levels_tables")[1]}
    by_no = collections.defaultdict(set)
    for lvl, r in cap.items():
        by_no[lvl_no[lvl]].add(r["value"])
    assert all(len(v) == 1 for v in by_no.values()), "two buildings of one level get different space: %s" % \
        sorted(k for k, v in by_no.items() if len(v) > 1)[:3]
    for lvl, want in (("wh3_main_kho_settlement_major_3", 400.0), ("wh3_main_kho_settlement_major_3_a", 400.0),
                      ("wh3_main_kho_settlement_major_5_a", 800.0), ("wh3_dlc27_sla_dec_palace_settlement_1", 0.0),
                      ("wh3_dlc27_sla_dec_palace_settlement_5", 800.0), ("wh_main_emp_settlement_major_5", 800.0),
                      ("wh_main_emp_settlement_major_2", 200.0)):
        got = cap[lvl]["value"] if lvl in cap else 0.0
        assert got == want, "%s: space +%s, want +%s" % (lvl, got, want)
    assert not any("ruin" in l for l in cap), "space on a ruin level"
    assert keys.get("effects_description_" + STORE_CAP_FX)
    return len(stems)


def build_submod(name):
    """The campaign links for one map mod, one row per good."""
    ver, van = db("resources_to_campaign_junctions_tables")
    rows = [{"campaign": SUBMODS[name]["campaign"], "resource": key(g)} for g in GOODS]
    assert all(list(r) == list(van[0]) for r in rows)
    return {"resources_to_campaign_junctions_tables": (ver, list(van[0]), rows)}


def check_submod(name):
    """The map mod's campaign key is real, and every port slot it adds builds a chain we cover."""
    sm = SUBMODS[name]
    assert os.path.isfile(sm["pack"]), "%s not installed: %s" % (name, sm["pack"])

    def rows(table):
        return [r for _p, _v, rs in rvd.load(sm["pack"], table) for r in rs]
    assert sm["campaign"] in {r["campaign_name"] for r in rows("campaigns_tables")}, sm["campaign"]
    sc = collections.defaultdict(set)
    for r in db("building_chains_tables")[1] + rows("building_chains_tables"):
        sc[r["building_superchain"]].add(r["key"])
    parent = {r["key"]: r["parent_set"]
              for r in db("building_chain_sets_tables")[1] + rows("building_chain_sets_tables")}
    items = collections.defaultdict(list)
    for r in db("building_chain_set_items_tables")[1] + rows("building_chain_set_items_tables"):
        items[r["set"]].append(r)
    # Its own templates (the startpos is binary, so found by NAME); a new chain in one of them
    # would make none of our goods. Its vanilla regions use CA's templates, already covered.
    perm = srm.permitted(rows("slot_template_permitted_building_chains_tables"), parent, items, sc)
    port = {t: v for t, v in perm.items() if t.startswith(sm["port_prefix"])}
    prim = {t: v for t, v in perm.items() if "primary" in t}
    assert port and prim, "%s: no port or primary templates found - the naming guess is stale" % name
    missing = set(c for v in port.values() for c in v) - set(port_chains())
    assert not missing, "%s port chains with no production rows: %s" % (name, sorted(missing))
    missing = {c for v in prim.values() for c in v
               if not EXCLUDE.search(c) and not SETTLE_SKIP.search(c)} - set(pool_chains("settlement"))
    assert not missing, "%s settlement chains with no production rows: %s" % (name, sorted(missing))
    deposit = {r["key"]: r["resource"] for r in rows("slot_templates_tables") if r["resource"]}
    for pool in {p for g in GOODS.values() for p, _c in g["sources"] if _kind(p) == "mine"}:
        missing = {c for t, res in deposit.items() if res in pool[1:] for c in perm.get(t, ())
                   if "resource" in c and not EXCLUDE.search(c) and not NOT_A_MINE.search(c)} - set(pool_chains(pool))
        assert not missing, "%s %s chains with no production rows: %s" % (name, pool, sorted(missing))
    check_submod_reach(name)
    return len(port)


@functools.lru_cache(None)
def submod_signals(name):
    """The map mod's OWN regions as region signals, from what its pack ships: areas, climate
    (campaign_map_settlements), province, and a coast where a `<port_prefix><tail>` template
    exists. Deposits and cultural origin live only in its binary startpos, so they read empty:
    a deposit- or origin-gated good is UNDER-counted here, never over."""
    sm = SUBMODS[name]

    def rows(table):
        return [r for _p, _v, rs in rvd.load(sm["pack"], table) for r in rs]
    areas = collections.defaultdict(set)
    for r in rows("regions_to_region_groups_junctions_tables"):
        m = re.match(r"cai_(?:chaos_)?region_hint_(?:sub_)?area_(.+)$", r["region_group"])
        if m:
            areas[r["region"]].add(m.group(1))
    climate = {r["settlement_id"].split(":")[-1]: r["climate_type"] for r in rows("campaign_map_settlements_tables")}
    tpls = {r["key"] for r in rows("slot_templates_tables")}
    prov = {r["region"]: r["province"].split("_province_")[-1] for r in rows("region_to_province_junctions_tables")}
    out = {}
    for r in rows("regions_tables"):
        k = r["key"]
        if not climate.get(k):   # a sea or river region: no settlement, nothing to build
            continue
        tail = k.split("_region_")[-1]
        out[k] = dict(region=k, tail=tail, areas=areas.get(k, set()), climate=climate[k],
                      coastal=(sm["port_prefix"] + tail) in tpls, deposits=set(), origin="",
                      templates=set(), province=prov.get(k, ""), campaign=sm["campaign"])
    return out


def submod_reach(name):
    """area -> (regions, {good: regions it reaches}) over the map mod's own land regions."""
    sig = submod_signals(name)
    out = collections.defaultdict(lambda: [0, collections.Counter()])
    for g in sig.values():
        for a in g["areas"] or {"(none)"}:
            out[a][0] += 1
            for good in list(GOODS) + list(CA_GOODS):
                if reaches(good, g):
                    out[a][1][good] += 1
    return out


def check_submod_reach(name):
    """No good blankets a whole area of the map mod's own: that is a rule with its terrain
    condition missing - Ind incense reached all 31 Ind regions, peaks and jungle alike."""
    bad = ["%s: %s in all %d regions" % (a, good, n)
           for a, (n, goods) in submod_reach(name).items() if n >= 10
           for good, k in goods.items() if k == n]
    assert not bad, "%s goods with no terrain condition in an area: %s" % (name, bad)


def write(t, loc, frag=FRAG):
    os.makedirs(OUT, exist_ok=True)
    for tk, (ver, cols, rows) in t.items():
        table, ff = _table_frag(tk, frag)
        with io.open(os.path.join(OUT, "%s__%s.tsv" % (table, ff)), "w",
                     encoding="utf-8", newline="\n") as fh:
            fh.write("\t".join(cols) + "\n#%s;%d;db/%s/%s\n" % (table, ver, table, ff))
            for r in rows:
                fh.write("\t".join(_fmt(r[c]) for c in cols) + "\n")
    if frag != FRAG:
        return
    with io.open(os.path.join(OUT, "loc__%s.tsv" % FRAG), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("key\ttext\ttooltip\n#Loc;1;text/db/%s.loc\n" % FRAG)
        for k, v in loc:
            fh.write("%s\t%s\tfalse\n" % (k, v))
    dst = os.path.join(PACK, *ICON_DIR.split("/"))
    for good in GOODS:
        shutil.copyfile(os.path.join(ICONS, "small", good + ".png"), os.path.join(dst, icon(good) + ".png"))
        shutil.copyfile(os.path.join(ICONS, "large", good + ".png"), os.path.join(dst, icon(good) + "_large.png"))
    with io.open(AI_LUA, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(ai_script())
    import gen_mr_ui   # the Stores panel: its script and .twui.xml (tools/gen_mr_ui.py)
    gen_mr_ui.write_all()
    out = label_patch(label_vanilla())
    label_verify(out)
    with io.open(os.path.join(PACK, *LABEL.split("/")), "w", encoding="utf-8", newline="") as fh:
        fh.write(out)


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return "%.4f" % v
    return str(v)


def selftest():
    t, loc = build()
    check(t, loc)
    print(check_ai(ai_script()).strip().splitlines()[-1])
    for breakit in (lambda t, l: t["effect_bundles_to_effects_junctions_tables"][2][0].update(value=-10.0),
                    lambda t, l: t["effect_bundles_to_effects_junctions_tables"][2][0].update(effect_scope="nowhere"),
                    lambda t, l: t["effect_bundles_tables"][2][0].update(bundle_target="faction"),
                    lambda t, l: t["effect_bundles_tables"][2][-1].update(bundle_target="region"),
                    lambda t, l: t["effect_bundles_to_effects_junctions_tables"][2][-1].update(value=20.0),
                    lambda t, l: t["effect_bundles_tables"][2][0].update(ui_icon="no_such.png"),
                    lambda t, l: l.remove([x for x in l if x[0].startswith("effect_bundles_localised_title_")][0])):
        bad, bloc = build()
        breakit(bad, bloc)
        try:
            check_bundles(bad, bloc)
        except AssertionError:
            continue
        raise SystemExit("selftest: a broken bundle passed check_bundles()")
    # a bad row must be caught, or the check proves nothing
    for breakit in (lambda t: t["building_effects_junction_tables"][2].append(
                        dict(t["building_effects_junction_tables"][2][0], building="wh3_main_dae_port_1")),
                    lambda t: t["cai_personality_strategic_resource_values_tables"][2].pop(),
                    lambda t: t["building_effects_junction_tables"][2].append(
                        dict(t["building_effects_junction_tables"][2][0], building="no_such_level")),
                    lambda t: [r.update(context_requirement="") for r in t["building_effects_junction_tables"][2]
                               if r["building"] == bld_levels(bld_stem("gromril"))[0]],
                    lambda t: t["building_set_to_building_junctions_tables"][2].append(   # two sets
                        dict(t["building_set_to_building_junctions_tables"][2][0],
                             building_set="wh2_main_set_highelf_infrastructure")),
                    lambda t: t["building_effects_junction_tables"][2].append(   # another race's bonus
                        dict([r for r in t["building_effects_junction_tables"][2]
                              if r["building"] == "derpy_mr_bld_feathers_brt_1"][0],
                             effect="wh2_main_effect_resource_recruitment_cost_reduction_emp_demigryphs")),
                    lambda t: t["building_effects_junction_tables"][2].append(   # onto CA's own furs row
                        dict(t["building_effects_junction_tables"][2][0], building="wh_dlc05_wef_growth_1",
                             effect=CA_GOODS["furs"]["effect"])),
                    lambda t: t["pooled_resources_tables"][2][0].update(scope="FACTION"),
                    lambda t: t["pooled_resource_factor_junctions_tables"][2][0].update(maximum=0),
                    lambda t: [r for r in t["pooled_resource_factor_junctions_tables"][2]
                               if r["unique_id"].endswith("_raided")][0].update(minimum=0),
                    lambda t: t["campaign_group_pooled_resources_tables"][2].pop(),
                    lambda t: t["building_effects_junction_tables:ca"][2].pop(),
                    lambda t: [r for r in t["building_effects_junction_tables"][2]
                               if r["effect"].startswith("derpy_mr_store_")][0].update(value=999.0),
                    lambda t: [r for r in t["building_effects_junction_tables"][2]
                               if r["effect"].startswith("derpy_mr_store_") and r["context_requirement"]][0]
                              .update(context_requirement=""),
                    lambda t: t["building_effects_junction_tables"][2].remove(
                        [r for r in t["building_effects_junction_tables"][2] if r["effect"] == STORE_CAP_FX][0]),
                    lambda t: [r for r in t["building_effects_junction_tables"][2]
                               if r["effect"] == STORE_CAP_FX][0].update(value_damaged=100.0),
                    lambda t: t["effect_bonus_value_pooled_resource_junctions_tables"][2].pop()):
        bad, _ = build()
        breakit(bad)
        try:
            check(bad, loc)
        except AssertionError:
            continue
        raise SystemExit("selftest: a broken build passed check()")
    # a lore rule that drifts from the rules table must be caught - loosened, tightened, renamed
    for good, sources in (("whale_oil", [("port", None)]),
                          ("gromril", [(("mine",) + MINED, CLIM("climate_mountain"))]),
                          ("books", [("settlement", REG("altdorf"))]),
                          ("grain", [("settlement", ALL(CLIM("climate_temperate"), AREA("no_such_area")))]),
                          ("salt", [("port", None)]),
                          ("wine", [("farm", CLIM("climate_temperate"))])):
        real = good_spec(good)["sources"]
        good_spec(good)["sources"] = sources
        try:
            bad, bloc = build()
            check(bad, bloc)
        except AssertionError:
            continue
        finally:
            good_spec(good)["sources"] = real
        raise SystemExit("selftest: a drifted rule for %s passed check()" % good)
    # an IEE-only area with its terrain condition dropped must be caught
    real = GOODS["incense"]["sources"]
    GOODS["incense"]["sources"] = [("farm", AREA("ind"))]
    try:
        for name in SUBMODS:
            try:
                check_submod_reach(name)
            except AssertionError:
                continue
            raise SystemExit("selftest: %s passed a blanket area rule" % name)
    finally:
        GOODS["incense"]["sources"] = real
    # a map mod port chain we give no rows to must be caught
    global port_chains
    real = port_chains
    port_chains = lambda: {c: v for c, v in real().items() if c != "wh_main_EMPIRE_port"}
    try:
        for name in SUBMODS:
            try:
                check_submod(name)
            except AssertionError:
                continue
            raise SystemExit("selftest: %s passed with a port chain uncovered" % name)
    finally:
        port_chains = real
    for name in SUBMODS:
        check_submod(name)
    # the label: patched output verifies, and each guard bites on a broken CA file
    van = label_vanilla()
    label_verify(label_patch(van))
    for broken, why in ((van.replace("</resource_list>", "", 1), "row gone from hierarchy"),
                        (van.replace('type="HorizontalList"', 'type="VerticalList"'), "row not horizontal"),
                        (van.replace('id="resource_list"', 'id="x"'), "row component renamed"),
                        (van + label_id(next(iter(GOODS))), "our id already there")):
        try:
            label_check(broken)
        except (AssertionError, ValueError):
            continue
        raise SystemExit("selftest: label_check missed: %s" % why)
    print("selftest ok")


def modpack(frag):
    """The pack FILE is named for the mod; its DB table files keep FRAG (renamed 2026-10-02)."""
    return os.path.join(ROOT, "Modding Files", "Modpacks", frag.replace(FRAG, PACK_NAME, 1) + ".pack")


def pack(t, frag=FRAG):
    """Build the pack in RPFM from the TSVs on disk, then reopen the SAVED pack and count rows."""
    import tempfile
    import read_pack_index as rpi
    from import_house_ancillaries import call, check_keys
    call("set_game_selected", {"game_name": "warhammer_3", "rebuild_dependencies": False})
    plan = []
    for tk, (ver, _c, _r) in sorted(t.items()):   # a "table:part" key is a second file of that table
        table, ff = _table_frag(tk, frag)
        plan.append(("db/%s/%s" % (table, ff), {"DB": [ff, table, ver]}, "%s__%s.tsv" % (table, ff), OUT, tk))
    main = frag == FRAG   # loc and icons ship once, in the main pack
    if main:
        plan.append(("text/db/%s.loc" % frag, {"Loc": frag}, "loc__%s.tsv" % frag, OUT))
    for path, _n, tsv, _o, *tk in plan:   # the files on disk must be what build() makes
        rows = sum(1 for _ in open(os.path.join(OUT, tsv), encoding="utf-8")) - 2
        want = len(t[tk[0]][2]) if tk else n_loc()
        assert rows == want, "%s has %d rows, build() makes %d - run without --pack first" % (tsv, rows, want)
    check_keys(plan)
    key = call("new_pack", {})["String"]
    for path, newfile, tsv, _o, *_tk in plan:
        call("new_packed_file", {"pack_key": key, "path": path, "new_file": json.dumps(newfile)})
        call("import_tsv", {"pack_key": key, "table_path": path, "tsv_path": os.path.join(OUT, tsv)})
    icons = ["%s/%s%s.png" % (ICON_DIR, icon(g), s)
             for g in GOODS for s in ("", "_large")] + [bld_icon(g) for g in RARE] + [LABEL] if main else []
    if main:   # the label on disk must be what label_patch() builds from CA's CURRENT file
        with io.open(os.path.join(PACK, *LABEL.split("/")), encoding="utf-8", newline="") as fh:
            assert fh.read() == label_patch(label_vanilla()), "stale %s - run without --pack first" % LABEL
    if main:   # the AI script on disk must be what ai_script() builds
        with io.open(AI_LUA, encoding="utf-8") as fh:
            assert fh.read() == ai_script(), "stale %s - run without --pack first" % AI_LUA
        icons.append("script/campaign/mod/" + os.path.basename(AI_LUA))
    if main:   # the Stores panel (gen_mr_ui.py) and this pack's Derpy HUD hub copy (sync_derpy_hub.py)
        import gen_mr_ui
        import sync_derpy_hub
        drift = gen_mr_ui.stale() + sync_derpy_hub.check()
        assert not drift, "stale - run py tools/gen_resource_overhaul.py and py tools/sync_derpy_hub.py: %s" % drift
        gen_mr_ui.selftest()
        icons += gen_mr_ui.pack_paths() + [d for _s, d in sync_derpy_hub.pack_files("mr")]
    for rel in icons:
        call("add_packed_files", {"pack_key": key, "source_paths": [os.path.join(PACK, *rel.split("/"))],
                                  "destination_paths": json.dumps([{"File": rel}])})
    out = modpack(frag)
    call("save_pack_as", {"pack_key": key, "path": out})
    # verify what was SAVED, not what was planned
    again = call("open_packfiles", {"paths": [out]})["StringContainerInfo"][0]
    tmp = tempfile.mkdtemp()
    for path, _n, tsv, _o, *_tk in plan:
        dst = os.path.join(tmp, tsv)
        call("export_tsv", {"pack_key": again, "table_path": path, "tsv_path": dst})
        got = sum(1 for l in io.open(dst, encoding="utf-8") if l.strip()) - 2
        want = sum(1 for _ in open(os.path.join(OUT, tsv), encoding="utf-8")) - 2
        assert got == want, "saved %s has %d rows, expected %d" % (path, got, want)
        print("  %4d  %s" % (got, path))
    have = set(rpi.paths(out))
    assert set(icons) <= have, sorted(set(icons) - have)
    print("saved and verified", out)


def main():
    if "--audit" in sys.argv:
        return audit()
    if "--selftest" in sys.argv:
        return selftest()
    t, loc = build()
    gone = check(t, loc)
    print(check_ai(ai_script()).strip().splitlines()[-1])
    subs = {}
    for name in SUBMODS:
        n = check_submod(name)
        subs[name] = build_submod(name)
        print("%s: %s, %d port templates, all covered" % (name, SUBMODS[name]["campaign"], n))
    if "--pack" in sys.argv:
        pack(t)
        for name, st in subs.items():
            pack(st, "%s_%s" % (FRAG, name))
        return
    for table, (ver, _c, rows) in sorted(t.items()):
        print("%-55s v%d %4d rows" % (table, ver, len(rows)))
    print("loc %d keys; excluded port chains: %s" % (len(loc), ", ".join(gone)))
    sig = _signals()
    tot = collections.Counter(g["campaign"] for g in sig.values())
    print("%-16s %4s %4s  sources" % ("good", "IE", "RoC"))
    for good, n in reach_table().items():
        print("%-16s %4d %4d  %s" % (good, n["wh3_main_combi"], n["wh3_main_chaos"],
                                       ", ".join(str(_kind(p)) for p, _c in good_spec(good)["sources"])))
    print("(of %d IE and %d RoC regions)" % (tot["wh3_main_combi"], tot["wh3_main_chaos"]))
    for name in SUBMODS:   # the map mod's own regions, by area (deposit/origin goods under-counted)
        print("%s own regions, by area:" % name)
        for a, (n, goods) in sorted(submod_reach(name).items(), key=lambda x: -x[1][0]):
            print("  %-20s %3d  %s" % (a, n, ", ".join("%s %d" % kv for kv in goods.most_common())))
    if "--check" not in sys.argv:
        write(t, loc)
        for name, st in subs.items():
            write(st, None, "%s_%s" % (FRAG, name))
        print("wrote", OUT)


if __name__ == "__main__":
    main()
