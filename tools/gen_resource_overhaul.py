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
           "cth": "wh3_main_sc_cth_cathay", "nor": "wh_dlc08_sc_nor_norsca",
           "chs": "wh_main_sc_chs_chaos", "def": "wh2_main_sc_def_dark_elves", "hef": "wh2_main_sc_hef_high_elves"}
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
             "wizards.",
        sources=[("port", AREA("kislev", "norsca"))]),
    "grain": dict(
        unit="sacks", price=10.0, name="Grain",
        desc="Wheat, rye and barley from the farmland of the Old World and the barley fields of "
             "the Dwarf holds. Bread for cities and fodder for armies.",
        # one row per building and effect, so the Dwarf Barley Field's grain joins the farm rule
        sources=[("farm", ANY(ALL(CLIM("climate_temperate"), AREA(*FARMLAND)), ORIGIN("dwf")))]),
    "warhorses": dict(
        unit="derpy_horses", price=16.0, name="Warhorses",
        desc="Bretonnian destriers, Kislevite steppe horses, Arabyan coursers, Ellyrian steeds, "
             "Averland's herds and the Druchii's Dark Steeds, bred for war.",
        sources=[("stables", ANY(ALL(CLIM("climate_temperate", "climate_savannah", "climate_desert"),
                                     AREA("bretonnia", "kislev", "araby")), ORIGIN("hef", "emp"))),
                 ("darksteeds", ORIGIN("def"))]),
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
                 ("dig", ALL(ORIGIN("dwf", "chd"), CLIM("climate_mountain", "climate_wasteland"))),
                 ("deep", ORIGIN("dwf")),
                 ("toolmaker", ORIGIN("dwf"))]),
    "silver": dict(
        unit="ingot", price=15.0, name="Silver",
        desc="Veins of silver found in mountain mines already worked for iron, gems or gold, and "
             "in the Dwarfs' Underdeep.",
        sources=[(("mine",) + MINED, CLIM("climate_mountain")),
                 ("deep", ORIGIN("dwf"))]),
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
        desc="Yellow sulphur scraped from the vents of the Dark Lands, every obsidian field and the "
             "Dwarfs' deepest workings.",
        sources=[(("mine", "res_obsidian"), None),
                 ("dig", ALL(AREA(*DARKLANDS), CLIM("climate_wasteland", "climate_chaotic"))),
                 ("deep", ORIGIN("dwf"))]),
    "brass": dict(
        unit="ingot", price=12.0, name="Brass",
        desc="Hashut's own metal, cast in the forges of the Chaos Dwarfs.",
        sources=[("forge", ANY(ORIGIN("chd"), REG("the_copper_landing"))),
                 (("mine", "res_rom_iron"), AREA(*DARKLANDS)),
                 ("coppermine", REG("karak_izor"))]),   # the Skaven's Copper Mountain stands only there
    "blackpowder": dict(
        unit="kegs", price=14.0, name="Blackpowder",
        desc="Saltpetre from the salt pans, ground with charcoal and sulphur by the races that "
             "know the secret.",
        sources=[(("mine", "res_rom_lead"), ORIGIN("dwf", "emp", "chd", "cth")),
                 ("settlement", REG("nuln")),
                 ("engineer", ORIGIN("dwf"))]),
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
                          (("settlement", "nor"), CLIM("climate_frozen")),
                          ("furstash", ORIGIN("chs"))]),
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
# EXPORTS HELD (TRADE_RESOURCES.md 28): a visible faction line while any good is held, and one
# hidden marker per good that its hold rows test (hold_rows). The line's record is also what the
# first build's faction-wide -1000 custom bundle was built on, which the script now removes.
HOLD = ("derpy_mr_exports_held", "trade_agreement.png", "Exports held",
        "You are holding some resources back from your trade agreements (the Resource Vault's Trade "
        "tab). Your regions make none of them for trade, so they earn you no trade income. Your stores "
        "still fill.")
HOLD_PREFIX = "derpy_mr_hold_"

# PHASE 6 (spending spec section 4): four store events. A player is offered a DB dilemma at turn
# start (FIRST spends and rewards, SECOND declines); the flows script takes the spend from the
# stores when it is answered, since a payload cannot charge a REGION pool. A computer-run faction
# takes the same deal on a roll of EVENT_AI_PCT. At most one event per faction every EVENT_GAP
# turns. Feast and Siege stores reward with a region bundle; Tribute with CA's dilemma diplomatic
# bonus; Arsenal with a rank for one army's units. `where`: "region" pays from that settlement,
# "realm" from the fullest stores realm-wide. The dilemma text names its target with CA's own
# {{CcoCampaignEventDilemma:...}} tokens.
EVENT_GAP, EVENT_AI_PCT = 10, 20
EVENT_DONOR = "wh2_dlc08_nor_confederate_generic"
_RT = "{{CcoCampaignEventDilemma:RegionTargetName}}"
EVENTS = (
    dict(key="feast", use="provisions", cost=100, where="region", image="celebration",
         title="A Feast", text="The stores of %s overflow with provisions. The people would gladly see "
         "them set out on the tables." % _RT,
         accept=("Hold the feast", "Spend 100 provisions: public order +5 and growth +20 there for 5 turns."),
         bundle=("derpy_mr_event_feast", "public_order_jubilant.png", "Feast", 5,
                 "A feast paid for from this settlement's stores: public order and growth are up.",
                 [("wh_main_effect_public_order_events", "region_to_province_own_unseen", 5),
                  ("wh_main_effect_province_growth_events", "region_to_province_own_unseen", 20)])),
    dict(key="siege", use="provisions", cost=60, where="region", image="food_merchant",
         title="Siege Stores", text="%s is under siege, and its stores still hold provisions. Open them "
         "to the garrison and it can hold out without starving." % _RT,
         accept=("Open the stores", "Spend 60 provisions: the garrison suffers no siege attrition for 2 turns."),
         bundle=("derpy_mr_event_siege", "siege_defence.png", "Siege Stores", 2,
                 "This settlement's stores feed its besieged garrison.",
                 [("wh_main_effect_force_army_campaign_siege_defend_attrition", "region_to_force_own", -100)])),
    dict(key="tribute", use="luxuries", cost=50, where="realm", image="diplomacy",
         title="Tribute", text="{{CcoCampaignEventDilemma:FirstTargetFactionNameWithIcon}} shares a border "
         "with you and is not at war with you. A gift of luxuries from your stores would be remembered.",
         accept=("Send the gift", "Spend 50 luxuries: relations with that neighbour improve."), bundle=None,
         icon="diplomacy.png"),
    # NO CharacterTargetName: seen in game 2026-10-08 drawing blank ("'s army") with the character
    # and the force both handed over; the script's pick is always the largest army, so the text says so.
    dict(key="arsenal", use="war", cost=50, where="realm", image="army_morale_up",
         title="Arsenal", text="Your stores hold war materials enough to re-arm a whole army. "
         "Your largest army would make good use of them.",
         accept=("Re-arm the army", "Spend 50 war materials: every unit in your largest army gains a rank."),
         bundle=None, icon="experience.png"),
    # PHASE 6 PART 2: offered on capture, not at turn start (flows.lua F.on_restore), so it is not
    # in the turn-start order and keeps no gap. The spec's occupation option, as a dilemma: an
    # option row's required_resources may not read a REGION pool, and five building goods would
    # mean five buttons on every capture screen (TRADE_RESOURCES.md 27).
    dict(key="restore", use="building", cost=100, where="region", image="civilisation_up",
         title="Restore", text="The stores of %s hold building materials enough to mend what the fighting "
         "broke." % _RT,
         accept=("Restore it", "Spend 100 building materials there: every building is repaired, and public "
                 "order +5 for 5 turns."),
         bundle=("derpy_mr_event_restore", "public_order_happy.png", "Restored", 5,
                 "Repaired from this settlement's own stores: public order is up.",
                 [("wh_main_effect_public_order_events", "region_to_province_own_unseen", 5)])),
)
EVENT_DECLINE = ("Keep the stores", "Nothing is spent.")

# PHASE 5 (spending spec section 3): three switches per province, paid each turn from the province
# capital's store, SUPPLY_PER for each settlement held there, and each puts its region bundle on
# every one of them. A DB value cannot follow an MCT setting, so the discounts are fixed. Effects
# are CA's: construction cost the way its region bundles carry it, recruit cost with CA's own
# per-class effects (unit sets cavalry_units, monsters, infantry_units, all_land_artillery).
# (key, use, bundle, icon, title, what it does, [(effect, scope, value)])
SUPPLY_PER = 2
SUPPLY = (
    ("materials", "building", "derpy_mr_supply_materials", "construction.png", "Materials on hand",
     "construction cost -25%",
     [("wh_main_effect_building_construction_cost_mod", "region_to_region_own", -25)]),
    ("stable", "mounts", "derpy_mr_supply_stable", "mount.png", "Stable stocked",
     "recruit cost -15% for cavalry and monsters",
     [("wh_main_effect_force_army_campaign_recruitment_cost_cavalry", "region_to_force_own", -15),
      ("wh2_main_effect_lzd_monster_recruitment_cost_down", "region_to_force_own", -15)]),
    ("arms", "war", "derpy_mr_supply_arms", "weapon_damage.png", "Arms stocked",
     "recruit cost -15% for infantry and artillery",
     [("wh_main_effect_force_army_campaign_recruitment_cost_infantry", "region_to_force_own", -15),
      ("wh_main_effect_force_army_campaign_recruitment_cost_artillery", "region_to_force_own", -15)]),
)
# SHIPMENTS: Send here and Supply the capital move goods on the map for SHIP_TURNS turns, drawn as
# a marker an army at war with the owner can seize. CA's own Food Merchant cart, under our row.
# A computer-run faction keeps at most SHIP_AI_CAP on the road; Supply the capital ships when the
# capital holds under SHIP_STAND turns of a switched-on cost, enough for SHIP_AI_ON; a computer
# switches a supply on at SHIP_AI_ON turns of it. SHIP_NEAR: how close an enemy army must stand at
# the owner's turn start to seize one; SHIP_SPOT: CA's preferred distance from the settlement.
SHIP_TURNS, SHIP_AI_CAP, SHIP_STAND, SHIP_AI_ON = 2, 1, 5, 10
SHIP_RADIUS, SHIP_NEAR, SHIP_SPOT = 2, 3, 3
SHIP_INFO, SHIP_MARKER = "derpy_mr_shipment", "food_merchant"
SHIP_NAME = "Shipment"
SHIP_TIP = ("A shipment of resources on the road between two settlements. An army at war with its "
            "owner can seize it by marching in.")

# THE WORKSHOP (docs/superpowers/specs/2026-10-07-resource-overhaul-workshop-design.md): a rare good
# plus a bulk of its use buys a lasting thing. Prices (rare, bulk) by kind; research is luxuries only.
WORK_PRICE = {"item": (40, 150), "unit": (30, 100), "upgrade": (60, 200)}
WORK_RESEARCH = ("luxuries", 300)
WORK_RESEARCH_WAIT, WORK_AI_PCT, WORK_UNIT_MAX = 10, 20, 2
RESEARCH_POINTS = 400        # measured 2026-10-07: the median live cost of the 29 Dwarf techs on screen (100-700)
# WHERE A UNIT GOES, per race: a mercenary_pools key. Measured 2026-10-07 on a Dwarf save: a pool's
# panel lists only the groups mercenary_pool_to_groups_junctions links to it, so each unit's group is
# linked to its race's pool (_works_rows). Dwarfs: the Book of Grudges pool (asked for, and its own
# button); everyone else: the race's Regiments of Renown pool. A faction that does not own its race's
# pool (faction_to_mercenary_set_junctions; most minor factions) gets the unit in an army instead.
WORK_POOLS = {"dwf": "wh3_dlc25_dwf_book_of_grudges_mercenary_pool", "hef": "wh2_main_hef_units_of_renown_pool",
              "chd": "wh3_dlc23_chd_units_of_renown_pool", "def": "wh2_main_def_units_of_renown_pool",
              "skv": "wh2_dlc12_skv_units_of_renown_pool", "wef": "wh_dlc05_wef_units_of_renown_pool",
              "brt": "wh_dlc07_brt_units_of_renown_pool", "emp": "wh_dlc04_emp_units_of_renown_pool",
              "grn": "wh_dlc06_grn_units_of_renown_pool", "ogr": "wh3_main_ogr_units_of_renown_pool",
              # the races stage 3 brings in (spec section 5)
              "vmp": "wh_dlc04_vmp_units_of_renown_pool", "cth": "wh3_main_cth_units_of_renown_pool",
              "nor": "wh_dlc08_nor_units_of_renown_pool"}
WORK_ITEM_PREFIX, WORK_GROUP_PREFIX, WORK_UP_PREFIX = "derpy_mr_anc_", "derpy_mr_merc_", "derpy_mr_up_"
# (stem, rare, races, CA key or None, our name, donor, flavour). Ours keep the donor's row but key
# and randomly_dropped: the Workshop decides who gets one, and no other route drops it.
WORK_ITEMS = (
    ("gromril_armour", "gromril", ("dwf",), None, "Gromril Armour",
     "wh_main_anc_armour_armour_of_silvered_steel",
     "Gromril, the star-metal of the deep holds, beaten into plate no common blade will bite."),
    ("gromril_greataxe", "gromril", ("dwf",), None, "Gromril Greataxe", "wh_main_anc_weapon_ogre_blade",
     "A gromril edge, rune-hardened, that keeps its bite through a whole war."),
    ("ithilmar_breastplate", "ithilmar", ("hef",), "wh2_main_anc_armour_enchanted_ithilmar_breastplate",
     None, None, None),
    ("dragonhelm", "dragon_bone", ("all",), "wh_main_anc_armour_dragonhelm", None, None, None),
    ("dragonbane_gem", "dragon_bone", ("all",), "wh_main_anc_talisman_dragonbane_gem", None, None, None),
    ("dragonscale_shield", "dragon_bone", ("hef",), "wh2_main_anc_armour_dragonscale_shield", None, None, None),
    ("dragon_slayers_scales", "dragon_bone", ("dwf",), "wh2_dlc10_dwf_anc_armour_dragon_slayers_scales",
     None, None, None),
    ("dragons_claw", "dragon_bone", ("brt",), "wh_dlc07_anc_talisman_dragons_claw", None, None, None),
    ("sea_dragon_cloak", "sea_dragon_hide", ("def",), None, "Sea Dragon Cloak",
     "wh_main_anc_armour_armour_of_fortune",
     "Cut from the hide of a sea dragon, as the corsairs of the Black Arks wear it."),
    ("lotus_venom_blade", "black_lotus", ("def", "skv"), None, "Lotus-Venom Blade",
     "wh_main_anc_weapon_biting_blade", "Its edge is kept wet with black lotus, and the smallest cut is enough."),
    ("starwood_bow", "starwood", ("wef",), None, "Starwood Bow", "wh3_main_anc_weapon_wyvernbone_bow",
     "Grown, not carved, from the willing wood of Athel Loren."),
    ("featherfoe_torc", "feathers", ("brt", "emp"), "wh_main_anc_enchanted_item_featherfoe_torc",
     None, None, None),
    # Ogres only: CA's faction set has_ranged_character removes the Greenskins
    ("wyvernbone_bow", "wyvern_scales", ("ogr",), "wh3_main_anc_weapon_wyvernbone_bow", None, None, None),
    ("wyvern_scale_armour", "wyvern_scales", ("grn", "ogr"), None, "Wyvern-Scale Armour",
     "wh_main_anc_armour_gamblers_armour", "Scales prised from a wyvern of the Badlands, still hard as iron."),
    # RARE WORKS DEEPENED (workshop expansion spec section 5): CA's own items whose material fits
    # the good, every faction set checked (check_works); lore over coverage
    # the panel shows "Armour of Borek Beetlebrow": CA's full name overruns the name column
    ("borek_armour", "gromril", ("dwf",), "wh_main_anc_armour_magnificent_armour_of_borek_beetlebrow",
     "Armour of Borek Beetlebrow", None, None),
    ("ironbeards_armour", "gromril", ("dwf",), "wh2_dlc10_dwf_anc_armour_ironbeards_armour", None, None, None),
    ("helm_of_fortune", "ithilmar", ("hef",), "wh2_main_anc_armour_helm_of_fortune", None, None, None),
    ("armour_of_caledor", "ithilmar", ("hef",), "wh2_main_anc_armour_armour_of_caledor", None, None, None),
    ("spirit_dragon_icon", "dragon_bone", ("cth",), "wh3_main_anc_enchanted_item_icon_of_the_spirit_dragon",
     None, None, None),
    ("drake_hunters_banner", "dragon_bone", ("nor",), "wh_dlc08_anc_magic_standard_drake_hunters", None, None, None),
    ("cloak_of_hag_graef", "sea_dragon_hide", ("def",), "wh2_main_anc_armour_cloak_of_hag_graef", None, None, None),
    ("sea_serpent_standard", "sea_dragon_hide", ("def",), "wh2_main_anc_magic_standard_sea_serpent_standard",
     None, None, None),
    ("hail_of_doom_arrow", "starwood", ("wef",), "wh_dlc05_anc_enchanted_item_hail_of_doom_arrow", None, None, None),
    ("bow_of_loren", "starwood", ("wef",), "wh_dlc05_anc_weapon_the_bow_of_loren", None, None, None),
    ("phoenix_pinion", "feathers", ("brt", "emp"), "wh2_dlc10_anc_enchanted_item_extinguished_phoenix_pinion",
     None, None, None),
    # Bretonnia's faction set refuses the Griffon Banner
    ("griffon_banner", "feathers", ("emp",), "wh_main_anc_magic_standard_griffon_banner", None, None, None),
    ("glittering_scales", "wyvern_scales", ("grn", "ogr"), "wh_main_anc_armour_glittering_scales", None, None, None),
    ("venom_sword", "black_lotus", ("def",), "wh2_main_anc_weapon_venom_sword", None, None, None),
    ("corrosive_blade", "black_lotus", ("skv",), "wh2_main_anc_weapon_weeping_blade", None, None, None),
)
# (rare, race, unit keys) - the units the rare buildings already reward
WORK_UNITS = (
    ("gromril", "dwf", ("wh_main_dwf_inf_ironbreakers", "wh_main_dwf_inf_hammerers")),
    ("ithilmar", "hef", ("wh2_main_hef_inf_swordmasters_of_hoeth_0", "wh2_main_hef_inf_phoenix_guard")),
    ("dragon_bone", "hef", ("wh2_main_hef_cav_dragon_princes",)),
    ("dragon_bone", "chd", ("wh3_dlc23_chd_mon_lammasu", "wh3_dlc23_chd_mon_bale_taurus")),
    ("sea_dragon_hide", "def", ("wh2_main_def_inf_black_ark_corsairs_0",)),
    ("black_lotus", "def", ("wh2_main_def_inf_witch_elves_0",)),
    ("black_lotus", "skv", ("wh2_main_skv_inf_gutter_runners_0",)),
    ("starwood", "wef", ("wh_dlc05_wef_inf_glade_guard_0",)),
    ("feathers", "brt", ("wh_main_brt_cav_pegasus_knights",)),
    ("feathers", "emp", ("wh_main_emp_cav_demigryph_knights_0",)),
    ("wyvern_scales", "grn", ("wh_main_grn_inf_black_orcs",)),
    ("wyvern_scales", "ogr", ("wh3_main_ogr_mon_stonehorn_0", "wh3_dlc26_ogr_mon_thundertusk")),
    # RARE WORKS DEEPENED (spec section 5): one more unit a good, and the races left out where the lore
    # holds - CA's own dragon graves grant the Zombie Dragon; Norsca hunts ice dragons. Not Kislev's
    # Winged Lancers: Kislev makes no feathers, and trade stops at one shipment (check_works)
    ("gromril", "dwf", ("wh_main_dwf_inf_irondrakes_0",)),
    ("ithilmar", "hef", ("wh2_main_hef_cav_silver_helms_0",)),
    ("dragon_bone", "vmp", ("wh3_dlc29_vmp_mon_zombie_dragon",)),
    ("dragon_bone", "cth", ("wh3_main_cth_inf_dragon_guard_0",)),
    ("dragon_bone", "nor", ("wh_dlc08_nor_mon_frost_wyrm_0",)),
    ("sea_dragon_hide", "def", ("wh2_main_def_inf_black_ark_corsairs_1",)),
    ("starwood", "wef", ("wh_dlc05_wef_inf_waywatchers_0",)),
    ("black_lotus", "skv", ("wh2_main_skv_inf_poison_wind_globadiers",)),
)
# (rare, title, what it does, icon, [(effect, scope, value)], the row's short line) - CA's own
# effects, scopes and values
WORK_UPGRADES = (
    ("gromril", "Gromril Gate", "melee defence +10 for your armies here, armour +10 in the province",
     "siege_defence.png",
     [("wh_main_effect_force_stat_melee_defence", "region_to_force_own", 10),
      ("wh3_dlc24_unit_stat_bonus_armour", "province_to_province_own_unseen", 10)], "Melee defence and armour"),
    ("ithilmar", "Ithilmar Spire", "public order +3 in the province, income +10% here", "public_order_happy.png",
     [("wh_main_effect_public_order_base", "region_to_province_own_unseen", 3),
      ("wh_main_effect_economy_gdp_mod_all", "region_to_region_own", 10)], "Public order and income"),
    ("dragon_bone", "Dragon Bone Shrine", "units recruited in the province gain a rank", "experience.png",
     [("wh_main_effect_force_all_campaign_experience_base_all", "region_to_province_own", 1)], "Recruits gain a rank"),
    ("sea_dragon_hide", "Sea Dragon Moorings", "income +15% here", "income.png",
     [("wh_main_effect_economy_gdp_mod_all", "region_to_region_own", 15)], "Income +15% here"),
    ("black_lotus", "Black Lotus Gardens", "hero actions from here succeed more often (+10)", "agent.png",
     [("wh_main_effect_agent_action_success_chance", "region_to_character_own", 10)], "Hero actions succeed more"),
    ("starwood", "Starwood Grove", "growth +20 in the province", "growth.png",
     [("wh_main_effect_province_growth_events", "region_to_province_own_unseen", 20)], "Growth +20"),
    ("feathers", "Eyrie", "recruitment cost -15% in the province", "mount.png",
     [("wh_main_effect_force_all_campaign_recruitment_cost_all", "region_to_province_own", -15)], "Recruitment cost -15%"),
    ("wyvern_scales", "Wyvern Roost", "upkeep -5% for your armies here", "variable_upkeep.png",
     [("wh_main_effect_force_all_campaign_upkeep", "region_to_force_own", -5)], "Army upkeep -5%"),
)
WORK_CATEGORY_WORD = {"armour": "Armour", "weapon": "Weapon", "talisman": "Talisman",
                      "enchanted_item": "Enchanted item", "arcane_item": "Arcane item", "general": "Banner"}
# who carries an item CA limits by character (ancillaries_included_agent_subtypes), plural
WORK_AGENT_WORD = {"wh_dlc05_wef_glade_lord": "Glade Lords", "wh_dlc05_wef_glade_lord_fem": "Glade Lords",
                   "wh_dlc05_wef_waystalker": "Waystalkers", "wh2_twa02_wef_glade_captain": "Glade Captains",
                   "wh2_dlc16_wef_sisters_of_twilight": "the Sisters"}


def work_item_agents():
    """CA item key -> the agent subtypes that alone may carry it."""
    out = collections.defaultdict(set)
    for r in db("ancillaries_included_agent_subtypes_tables")[1]:
        out[r["ancillary"]].add(r["agent_subtype"])
    return out
# THE NAMED RECIPES (workshop expansion spec 2026-10-08, section 4): works priced in named common
# goods, in four kinds. convert: goods into the race's CA currency, once a turn; army: the selected
# army, a wait per army; trait: the selected lord or hero, once each; lasting: a faction bundle for
# good, once a campaign. Effects, scopes and values are CA's own (harvested 2026-10-08).
WORK_RECIPE_WAIT = {"convert": 1, "army": 5}
FORCE_DONOR = "wh2_dlc09_books_of_nagash_reward_1"   # force target, not in 3D, owner only
WORK_RECIPE_PREFIX = "derpy_mr_rc_"
# (key, kind, races, [(stem, n)], name, gives, detail, payload)
WORK_RECIPES = (
    ("conv_armaments", "convert", ("chd",), [("coal", 20), ("brimstone", 20), ("iron", 20)], "Armaments",
     "30 Armaments", "Makes 30 Armaments from your stores, once a turn",
     {"pool": "wh3_dlc23_chd_armaments", "amount": 30}),
    ("conv_food", "convert", ("skv",), [("grain", 30), ("salted_fish", 30)], "Food", "4 Food",
     "Makes 4 Food from your stores, once a turn", {"pool": "skaven_food", "amount": 4}),
    ("conv_oathgold", "convert", ("dwf",), [("gold_idols", 30), ("silver", 30)], "Oathgold", "30 Oathgold",
     "Makes 30 Oathgold from your stores, once a turn", {"pool": "dwf_oathgold", "amount": 30}),
    ("conv_infamy", "convert", ("cst",), [("rum", 30), ("pearls", 30)], "Infamy", "50 Infamy",
     "Makes 50 Infamy from your stores, once a turn", {"pool": "cst_infamy", "amount": 50}),
    ("army_rations", "army", ("all",), [("grain", 35), ("salt", 35), ("beer", 35)], "Rations and Drill",
     "The army gains a rank", "Every unit in the selected army gains a rank", {"rank": 1}),
    ("army_ammo", "army", ("all",), [("blackpowder", 50), ("brass", 50)], "Ammunition Train",
     "Ammunition +20%, 5 turns", "The selected army's ammunition +20% for 5 turns",
     {"fx": [("wh_main_effect_force_stat_ammunition", "force_to_force_own", 20)], "icon": "ammo.png"}),
    ("army_forge", "army", ("all",), [("iron", 50), ("coal", 50)], "Field Forge",
     "Armour +15, 5 turns", "The selected army's armour +15 for 5 turns",
     {"fx": [("wh_main_effect_force_stat_armour", "force_to_force_own", 15)], "icon": "armour.png"}),
    ("army_remounts", "army", ("all",), [("warhorses", 50), ("animals", 50)], "Remounts",
     "Replenishment +10%, 5 turns", "The selected army replenishes 10% faster for 5 turns",
     {"fx": [("wh_main_effect_force_all_campaign_replenishment_rate", "force_to_force_own", 10)],
      "icon": "replenishment.png"}),
    ("army_medicine", "army", ("all",), [("medicine", 50), ("wine", 50)], "Medicine Chests",
     "Attrition -25%, 5 turns", "The selected army suffers 25% less attrition for 5 turns",
     {"fx": [("wh_main_effect_force_army_campaign_attrition_all_resistance", "force_to_force_own", -25)],
      "icon": "attrition.png"}),
    ("trait_silk", "trait", ("all",), [("silk", 50), ("dyes", 50), ("jade", 50)], "Silk-robed",
     "Diplomacy +10", "A trait for the selected lord or hero: diplomatic relations +10",
     {"fx": [("wh_main_faction_political_diplomacy_mod", "character_to_faction", 10)],
      "flavour": "Robed in silk and jade, they are received as an equal at any court."}),
    ("trait_steel", "trait", ("all",), [("iron", 80), ("brass", 80)], "Steel-shod",
     "Armour +10", "A trait for the selected lord or hero: armour +10",
     {"fx": [("wh_main_effect_character_stat_armour", "character_to_character_own", 10)],
      "flavour": "Plate and greaves from the realm's own stores, fitted by its best smiths."}),
    ("trait_read", "trait", ("all",), [("books", 80), ("glassware", 80)], "Well-read",
     "Experience +20%", "A trait for the selected lord or hero: experience gained +20%",
     {"fx": [("wh3_main_effect_character_campaign_experience_mod", "character_to_character_own", 20)],
      "flavour": "A library carried on campaign, and lenses to read it by lamplight."}),
    ("trait_spice", "trait", ("all",), [("spices", 60), ("incense", 60)], "Spice-hardened",
     "Leadership +4, movement -5%", "A trait for the selected lord: leadership +4 for the army, movement -5%",
     {"fx": [("wh_main_effect_force_stat_leadership", "general_to_force_own", 4),
             ("wh_main_effect_force_all_campaign_movement_range", "general_to_force_own", -5)],
      "flavour": "Fiery on the tongue and slow in the stomach: brave, and in no hurry.", "lord": True}),
    ("trait_fur", "trait", ("all",), [("furs", 60), ("wool", 60)], "Furred and Booted",
     "Attrition -25%", "A trait for the selected lord: their army suffers 25% less attrition",
     {"fx": [("wh_main_effect_force_army_campaign_attrition_all_resistance", "general_to_force_own", -25)],
      "flavour": "Fur-lined boots and wool cloaks for every soldier, whatever the weather.", "lord": True}),
    ("last_granary", "lasting", ("all",), [("grain", 120), ("salt", 120), ("salted_meat", 120), ("pottery", 120)],
     "Great Granary", "Growth +15, for good", "Growth +15 in every province, for good",
     {"fx": [("wh_main_effect_province_growth_events", "faction_to_province_own", 15)], "icon": "growth.png"}),
    ("last_records", "lasting", ("all",), [("books", 150), ("glassware", 150), ("silver", 150)],
     "Hall of Records", "Research +15%, for good", "Research rate +15%, for good",
     {"fx": [("wh_main_effect_technology_research_points", "faction_to_faction_own_unseen", 15)],
      "icon": "technology.png"}),
    ("last_bazaar", "lasting", ("all",), [("silk", 120), ("carpets", 120), ("dyes", 120), ("spices", 120)],
     "Grand Bazaar", "Trade income +15%, for good", "Trade income +15%, for good",
     {"fx": [("wh_main_effect_economy_trade_tariff_mod", "faction_to_faction_own", 15)], "icon": "trade_agreement.png"}),
    ("last_arsenal", "lasting", ("all",), [("iron", 150), ("coal", 150), ("brass", 150), ("blackpowder", 150)],
     "Arsenal", "Upkeep -10%, for good", "Army upkeep -10%, for good",
     {"fx": [("wh_main_effect_force_all_campaign_upkeep", "faction_to_force_own", -10)], "icon": "variable_upkeep.png"}),
    ("last_stables", "lasting", ("all",), [("warhorses", 150), ("furs", 150), ("tusks", 150), ("timber", 150)],
     "Royal Stables", "Cavalry cost -20%, for good", "Cavalry recruitment cost -20%, for good",
     {"fx": [("wh_main_effect_force_army_campaign_recruitment_cost_cavalry", "faction_to_force_own_unseen", -20)],
      "icon": "mount.png"}),
)
# the one deliberate downside: Spice-hardened is a trade-off trait (spec 4c)
WORK_RECIPE_PENALTIES = {("trait_spice", "wh_main_effect_force_all_campaign_movement_range")}


def work_item_key(stem, ca):
    return ca or WORK_ITEM_PREFIX + stem


def _work():
    """The catalogue, in panel order: items, units, upgrades, research."""
    import gen_mr_ui
    import read_vanilla_loc as rvl
    anc_names, unit_names = rvl.load("ancillaries"), rvl.load("land_units")
    anc = {r["key"]: r for r in db("ancillaries_tables")[1]}
    land = {r["unit"]: r["land_unit"] for r in db("main_units_tables")[1]}
    use = gen_mr_ui.use_of
    agents = work_item_agents()
    out = []
    for stem, rare, races, ca, name, donor, _flav in WORK_ITEMS:
        cat = anc[ca or donor]["category"]
        who = sorted({WORK_AGENT_WORD.get(a, a) for a in agents.get(ca, ())})
        who = ", ".join(who[:-1]) + " and " + who[-1] if len(who) > 1 else (who[0] if who else "a lord or hero")
        out.append(dict(key="item_" + stem, kind="item", rare=rare, rare_n=WORK_PRICE["item"][0], use=use(rare),
                        use_n=WORK_PRICE["item"][1], races=races, grant=work_item_key(stem, ca), group="",
                        name=name or anc_names.get("ancillaries_onscreen_name_" + ca, ca),
                        gives=WORK_CATEGORY_WORD.get(cat, cat),
                        detail="%s for %s" % (WORK_CATEGORY_WORD.get(cat, cat), who)))
    for rare, race, units in WORK_UNITS:
        for u in units:
            out.append(dict(key="unit_" + u, kind="unit", rare=rare, rare_n=WORK_PRICE["unit"][0], use=use(rare),
                            use_n=WORK_PRICE["unit"][1], races=(race,), grant=u, group=WORK_GROUP_PREFIX + u,
                            pool=WORK_POOLS[race],
                            name=unit_names.get("land_units_onscreen_name_" + land.get(u, u), u),
                            gives="Unit, %d at most" % WORK_UNIT_MAX,
                            detail="%d at most at a time" % WORK_UNIT_MAX))
    for rare, title, what, _icon, _fx, brief in WORK_UPGRADES:
        races = ("all",) if RARE[rare]["races"] == "all" else RARE[rare]["races"]
        out.append(dict(key="up_" + rare, kind="upgrade", rare=rare, rare_n=WORK_PRICE["upgrade"][0], use=use(rare),
                        use_n=WORK_PRICE["upgrade"][1], races=races, grant=WORK_UP_PREFIX + rare, group="",
                        name=title, gives=brief, detail=what[0].upper() + what[1:] + ", for good"))
    for key, kind, races, goods, name, gives, detail, pay in WORK_RECIPES:
        w = dict(key=key, kind=kind, rare="", rare_n=0, use="", use_n=0, races=races, grant="", group="",
                 name=name, gives=gives, detail=detail, goods=list(goods), wait=WORK_RECIPE_WAIT.get(kind, 0))
        w.update(pay)
        if pay.get("fx") and kind in ("army", "lasting"):
            w.update(bundle=WORK_RECIPE_PREFIX + key, turns=5 if kind == "army" else 0)
        if kind == "trait":
            w.update(trait="derpy_mr_trait_" + key[len("trait_"):])
        out.append(w)
    out.append(dict(key="research", kind="research", rare="", rare_n=0, use=WORK_RESEARCH[0], use_n=WORK_RESEARCH[1],
                    races=("all",), grant="", group="", name="Research", gives="%d research points" % RESEARCH_POINTS,
                    detail="%d research points, at once" % RESEARCH_POINTS))
    return out


WORKS = []   # filled on first use: it reads CA's db and loc


def works():
    if not WORKS:
        WORKS.extend(_work())
    return WORKS


def work_cfg():
    return dict(research_points=RESEARCH_POINTS, research_wait=WORK_RESEARCH_WAIT, ai_pct=WORK_AI_PCT,
                unit_max=WORK_UNIT_MAX)


def pool_factions():
    """{pool: sorted faction keys that own it}, for the Workshop's pools, out of CA's db."""
    want = set(WORK_POOLS.values())
    out = {p: set() for p in want}
    for r in db("faction_to_mercenary_set_junctions_tables")[1]:
        if r["mercenary_set"] in want:
            out[r["mercenary_set"]].add(r["faction"])
    return {p: sorted(fs) for p, fs in out.items()}


def work_link_key(group):
    """A stable key for a pool-to-group row: CA's are 32-bit ids; ours hash the group's name."""
    import zlib
    return zlib.crc32(group.encode()) & 0x7FFFFFFF


def _set_admits(fs, race):
    """Does CA's faction set `fs` let race token `race` equip it? A row with no key admits everyone;
    a remove row takes its culture/subculture/faction back out."""
    tok, inn, out = "_%s_" % race, False, False
    for r in db("faction_set_items_tables")[1]:
        if r["set"] == fs:
            k = r["culture"] or r["subculture"] or r["faction"]
            if r["remove"]:
                out = out or tok in k
            else:
                inn = inn or not k or tok in k
    return inn and not out


def check_measured():
    """The value plan Task 1 measures in game. Unset, Research pays 0 points - so pack() refuses, while
    the selftests stay green until it is measured."""
    assert RESEARCH_POINTS > 0, "RESEARCH_POINTS is unset: measure it in game (plan Task 1)"


def check_works():
    """Every grant exists; a CA item's faction set admits every race of its row; the races are real
    subculture tokens; each unit is in main_units; prices are positive; keys are unique."""
    ws = works()
    anc = {r["key"]: r for r in db("ancillaries_tables")[1]}
    units = {r["unit"] for r in db("main_units_tables")[1]}
    tokens = {m.group(1) for r in db("cultures_subcultures_tables")[1]
              for m in [re.search(r"_sc_([a-z]+)_", r["subculture"])] if m}
    ours = {work_item_key(s, None) for s, _r, _x, ca, *_ in WORK_ITEMS if not ca}
    pools = {r["key"] for r in db("mercenary_pools_tables")[1]}
    owners = pool_factions()
    agents = work_item_agents()
    for w in ws:
        for race in w["races"]:
            assert race == "all" or race in tokens, "%s: race %s is no subculture token" % (w["key"], race)
        if w["kind"] in ("item", "unit", "upgrade"):
            assert w["rare"] in RARE and w["rare_n"] > 0 and w["use_n"] > 0 and w["use"], w["key"]
            # A RACE THAT CANNOT MAKE THE GOOD NEVER STOCKS IT (stage 3 review): trade ships only to
            # a capital holding none (F.lacks), so an import stops at one shipment, short of any price
            makers = RARE[w["rare"]]["races"]
            assert makers == "all" or set(w["races"]) <= set(makers), \
                "%s: %s cannot make %s" % (w["key"], sorted(set(w["races"]) - set(makers)), w["rare"])
        if w["kind"] == "item":
            assert w["grant"] in anc or w["grant"] in ours, "no such item: %s" % w["grant"]
            # AN ITEM ONLY SOME CHARACTERS CARRY says which (stage 3 review): CA's agent-subtype list
            for sub in agents.get(w["grant"], ()):
                assert sub in WORK_AGENT_WORD and WORK_AGENT_WORD[sub] in w["detail"], \
                    "%s: carried only by %s, detail %r" % (w["key"], sorted(agents[w["grant"]]), w["detail"])
            if w["grant"] in anc:
                fs = anc[w["grant"]]["faction_set"]
                for race in w["races"]:
                    assert fs == "all" or (race != "all" and _set_admits(fs, race)), \
                        "%s: race %s cannot equip it (faction_set %s)" % (w["grant"], race, fs)
        if w["kind"] == "unit":
            assert w["grant"] in units, "no such unit: %s" % w["grant"]
            assert w["pool"] in pools, "no such pool: %s" % w["pool"]
            assert owners.get(w["pool"]), "no faction owns %s" % w["pool"]
            assert w["name"] != w["grant"], "no CA name for %s" % w["grant"]
    assert len({w["key"] for w in ws}) == len(ws), "a catalogue key twice"
    check_recipes(ws)


def check_recipes(ws):
    """THE NAMED RECIPES (workshop expansion spec section 4): common goods only, races that keep
    stores, FACTION pools, CA's effects and scopes, every value a bonus by its effect's own sign
    unless listed in WORK_RECIPE_PENALTIES."""
    import gen_mr_ui as U
    stems = store_stems()
    van_fx = {r["effect"]: r for r in db("effects_tables")[1]}
    scopes = {r["key"] for r in db("campaign_effect_scopes_tables")[1]}
    pools = {r["key"]: r for r in db("pooled_resources_tables")[1]}
    assert {"convert", "army", "trait", "lasting"} <= {w["kind"] for w in ws}, "a recipe kind with no work"
    for w in ws:
        if not w.get("goods"):
            continue
        assert 2 <= len(w["goods"]) <= 4, "%s: 2-4 goods" % w["key"]
        for stem, n in w["goods"]:
            assert stem in stems and stem not in RARE and n > 0, "%s: %s is no common store good" % (w["key"], stem)
        assert not set(w["races"]) & set(U.NO_STORES), "%s: a race that keeps no stores" % w["key"]
        if w["kind"] == "convert":
            p = pools.get(w["pool"])
            assert p and p["scope"] == "FACTION" and w["amount"] > 0, "%s: pool %s is no FACTION pool" % (w["key"], w["pool"])
        if w["kind"] in ("army", "lasting", "trait"):
            assert w.get("fx") or w.get("rank"), "%s gives nothing" % w["key"]
        for e, sc, v in w.get("fx", ()):
            assert e in van_fx, "%s: no CA effect %s" % (w["key"], e)
            assert sc in scopes, "%s: no CA scope %s" % (w["key"], sc)
            assert (v > 0) == van_fx[e]["is_positive_value_good"] or (w["key"], e) in WORK_RECIPE_PENALTIES, \
                "%s %s is a penalty" % (w["key"], e)


def _works_rows(add, loc):
    """The Workshop's own rows: six items cloned from their donors, and one mercenary group per unit."""
    anc = {r["key"]: r for r in db("ancillaries_tables")[1]}
    for stem, _rare, _races, ca, name, donor, flavour in WORK_ITEMS:
        if ca:
            continue
        k = work_item_key(stem, None)
        add("ancillary_info_tables", {"ancillary": k})
        add("ancillaries_tables", dict(anc[donor], key=k, randomly_dropped=False))
        for r in db("ancillary_to_effects_tables")[1]:
            if r["ancillary"] == donor:
                add("ancillary_to_effects_tables", dict(r, ancillary=k))
        loc += [("ancillaries_onscreen_name_" + k, name), ("ancillaries_colour_text_" + k, flavour)]
    for _rare, _race, units in WORK_UNITS:
        for u in units:
            add("mercenary_unit_groups_tables", {
                "chance_to_replenish": 0.0, "key": WORK_GROUP_PREFIX + u, "max_count": WORK_UNIT_MAX,
                "unit_record": u, "use_partial_replenishment": False, "max_replenish_per_turn": 0.0,
                "ui_order": 0})
            # LINKED TO ITS RACE'S POOL, starting empty: the panel lists only linked groups (measured)
            add("mercenary_pool_to_groups_junctions_tables", {
                "group": WORK_GROUP_PREFIX + u, "initial_unit_count": 0, "key": work_link_key(WORK_GROUP_PREFIX + u),
                "pool": WORK_POOLS[_race], "faction_requirement": "", "subculture_requirement": "",
                "tech_requirement": ""})


WORK_TRAIT_DONOR = "wh2_main_trait_defeated_balthasar_gelt"   # one level, one effect, granted by script
WORK_FACTOR = "derpy_mr_workshop"


def _recipe_rows(add, loc):
    """The named recipes' traits (the donor's rows under our key) and the gain-only factor a
    conversion pays into its race's pool through."""
    tr, = [r for r in db("character_traits_tables")[1] if r["key"] == WORK_TRAIT_DONOR]
    lv, = [r for r in db("character_trait_levels_tables")[1] if r["key"] == WORK_TRAIT_DONOR]
    for w in works():
        if w["kind"] != "trait":
            continue
        k = w["trait"]
        add("character_traits_tables", dict(tr, key=k, icon="trait_good"))
        add("character_trait_levels_tables", dict(lv, key=k, trait=k))
        for e, scope, v in w["fx"]:
            add("trait_level_effects_tables", {"trait_level": k, "effect": e, "effect_scope": scope, "value": float(v)})
        add("trait_info_tables", {"trait": k})
        loc += [("character_trait_levels_onscreen_name_" + k, w["name"]),
                ("character_trait_levels_colour_text_" + k, w["flavour"]),
                ("character_trait_levels_explanation_text_" + k, "Fitted out from the Workshop's stores.")]
    add("pooled_resource_factors_tables", {"key": WORK_FACTOR, "is_hidden": False})
    loc += [("pooled_resource_factors_display_name_positive_" + WORK_FACTOR, "Workshop"),
            ("pooled_resource_factors_display_name_negative_" + WORK_FACTOR, "Workshop")]
    for pool in sorted({w["pool"] for w in works() if w["kind"] == "convert"}):
        add("pooled_resource_factor_junctions_tables", {
            "unique_id": WORK_FACTOR + "_" + pool, "factor": WORK_FACTOR, "resource": pool,
            "minimum": 0, "maximum": 2147483647, "specific_faction_set": "", "sort_order": 0})


def check_recipe_rows(t, loc):
    """Each trait is the donor's rows but key, icon and effects, with its three loc lines; the
    conversion factor is gain-only on every conversion pool, with its loc."""
    keys = dict(loc)
    traits = [w for w in works() if w["kind"] == "trait"]
    donor = {tb: [r for r in db(tb)[1] if r.get("key", r.get("trait")) == WORK_TRAIT_DONOR]
             for tb in ("character_traits_tables", "character_trait_levels_tables")}
    rows = {tb: {r["key"]: r for r in t[tb][2]} for tb in ("character_traits_tables", "character_trait_levels_tables")}
    info = {r["trait"] for r in t["trait_info_tables"][2]}
    fx = t["trait_level_effects_tables"][2]
    assert sorted(rows["character_traits_tables"]) == sorted(w["trait"] for w in traits), rows["character_traits_tables"]
    for w in traits:
        k = w["trait"]
        r, d = rows["character_traits_tables"][k], donor["character_traits_tables"][0]
        assert {c for c in d if r[c] != d[c]} <= {"key", "icon"} and r["icon"] == "trait_good", r
        lv = rows["character_trait_levels_tables"][k]
        assert (lv["trait"], lv["level"], lv["threshold_points"]) == (k, 1, 1), lv
        assert k in info, "%s has no trait_info row" % k
        got = [(x["effect"], x["effect_scope"], x["value"]) for x in fx if x["trait_level"] == k]
        assert got == [(e, sc, float(v)) for e, sc, v in w["fx"]], (k, got)
        for pre in ("onscreen_name_", "colour_text_", "explanation_text_"):
            assert keys.get("character_trait_levels_" + pre + k), pre + k
    assert {r["key"]: r for r in t["pooled_resource_factors_tables"][2]}.get(WORK_FACTOR) == \
        {"key": WORK_FACTOR, "is_hidden": False}, "no factor " + WORK_FACTOR
    js = {r["resource"]: r for r in t["pooled_resource_factor_junctions_tables"][2] if r["factor"] == WORK_FACTOR}
    assert set(js) == {w["pool"] for w in works() if w["kind"] == "convert"}, set(js)
    for j in js.values():
        assert j["minimum"] == 0 < j["maximum"] and j["unique_id"] == WORK_FACTOR + "_" + j["resource"], j
    for side in ("positive", "negative"):
        assert keys.get("pooled_resource_factors_display_name_%s_%s" % (side, WORK_FACTOR)) == "Workshop", side


def check_work_rows(t, loc):
    """Each new item is its donor field for field but key and randomly_dropped; its effects are the
    donor's; it has both loc lines; each unit has its group row, never replenished, at the cap."""
    keys = dict(loc)
    anc = {r["key"]: r for r in db("ancillaries_tables")[1]}
    van_fx = {}
    for r in db("ancillary_to_effects_tables")[1]:
        van_fx.setdefault(r["ancillary"], []).append((r["effect"], r["effect_scope"], r["value"]))
    rows = {r["key"]: r for r in t["ancillaries_tables"][2]}
    fx = t["ancillary_to_effects_tables"][2]
    info = [r["ancillary"] for r in t["ancillary_info_tables"][2]]
    ours = [work_item_key(s, None) for s, _r, _x, ca, *_ in WORK_ITEMS if not ca]
    assert sorted(rows) == sorted(ours) == sorted(info), (sorted(rows), sorted(info))
    for stem, _rare, _races, ca, _name, donor, _f in WORK_ITEMS:
        if ca:
            continue
        k = work_item_key(stem, None)
        assert k not in anc, "%s is a CA key" % k
        r, d = rows[k], anc[donor]
        diff = {c for c in d if r[c] != d[c]}
        assert diff <= {"key", "randomly_dropped"} and r["randomly_dropped"] is False, \
            "%s differs from %s in %s" % (k, donor, sorted(diff))
        assert not any("ability" in e for e, _s, _v in van_fx[donor]), "%s carries an ability" % donor
        got = sorted((x["effect"], x["effect_scope"], x["value"]) for x in fx if x["ancillary"] == k)
        assert got == sorted(van_fx[donor]), "%s effects differ from %s" % (k, donor)
        for pre in ("ancillaries_onscreen_name_", "ancillaries_colour_text_"):
            assert keys.get(pre + k), pre + k
    groups = {r["key"]: r for r in t["mercenary_unit_groups_tables"][2]}
    van_groups = {r["key"] for r in db("mercenary_unit_groups_tables")[1]}
    want = [WORK_GROUP_PREFIX + u for _r, _x, us in WORK_UNITS for u in us]
    assert sorted(groups) == sorted(want), sorted(set(groups) ^ set(want))
    for _rare, _race, units in WORK_UNITS:
        for u in units:
            g = groups[WORK_GROUP_PREFIX + u]
            assert g["key"] not in van_groups, g["key"]
            assert g["unit_record"] == u and g["max_count"] == WORK_UNIT_MAX, g
            assert g["chance_to_replenish"] == 0.0 and g["max_replenish_per_turn"] == 0.0, g
    links = {r["group"]: r for r in t["mercenary_pool_to_groups_junctions_tables"][2]}
    van_keys = {r["key"] for r in db("mercenary_pool_to_groups_junctions_tables")[1]}
    for _rare, race, units in WORK_UNITS:
        for u in units:
            g = WORK_GROUP_PREFIX + u
            assert g in links and links[g]["pool"] == WORK_POOLS[race], "%s is not linked to %s" % (g, WORK_POOLS[race])
            assert links[g]["initial_unit_count"] == 0 and links[g]["key"] not in van_keys, links[g]
    assert len({r["key"] for r in links.values()}) == len(links), "two link rows share a key"


def event_dilemma(key):
    return "derpy_mr_dil_" + key


def event_bundles():
    """(key, icon, title, turns, description, effects) of the events that leave a region bundle."""
    return [e["bundle"] for e in EVENTS if e["bundle"]]


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
    # bone talismans for everyone's heroes; and, as CA's own Graves of the Dragons gives them, the
    # High Elves' dragons and Dragon Princes and the Chaos Dwarfs' Lammasu and Taurus - the upkeep
    # is CA's, the cost and rank minted on the same units (MINT_FX)
    "dragon_bone": [(None, "hero", "wh_main_effect_agent_recruitment_xp_all_agents"),
                    ("hef", "cost", "derpy_mr_effect_cost_hef_dragons_dragon_princes"),
                    ("hef", "rank", "derpy_mr_effect_rank_hef_dragons_dragon_princes"),
                    ("hef", "upkeep", "wh2_dlc15_effect_upkeep_reduction_dragons_dragon_princes"),
                    ("chd", "cost", "derpy_mr_effect_cost_chd_lammasu_taurus"),
                    ("chd", "rank", "derpy_mr_effect_rank_chd_lammasu_taurus"),
                    ("chd", "upkeep", "wh3_dlc23_effect_upkeep_chd_lammasu_taurus")],
    # Black Ark Corsairs wear the sea dragon cloak (CA's salt bonus is the Corsairs one)
    "sea_dragon_hide": [("def", "cost", "wh2_main_effect_building_recruitment_cost_reduction_def_resource_salt"),
                        ("def", "rank", "wh2_main_effect_building_unit_xp_levels_def_resource_salt"),
                        ("def", "upkeep", "wh2_main_effect_tech_upkeep_cost_reduction_def_corsairs")],
    # Witch Elves' poisons (CA's medicine bonus); the Eshin assassins and Gutter Runners
    "black_lotus": [("def", "cost", "wh2_main_effect_building_recruitment_cost_reduction_def_resource_medicine"),
                    ("def", "rank", "wh2_main_effect_building_unit_xp_levels_def_resource_medicine"),
                    ("def", "upkeep", "wh2_main_effect_buildling_upkeep_reduction_def_resource_medicine"),
                    ("skv", "hero", "wh2_main_effect_agent_recruitment_xp_skv_assassin"),
                    ("skv", "cost", "wh2_main_effect_tech_recruitment_cost_reduction_skv_nightrunner_gutterrunner"),
                    ("skv", "rank", "wh2_main_effect_tech_unit_xp_levels_skv_nightrunner_gutterrunner"),
                    ("skv", "upkeep", "wh2_main_effect_tech_upkeep_reduction_skv_nightrunner_gutterrunners")],
    # starwood bows: Glade Guard and Glade Riders, all three (the upkeep one minted, see MINT_FX)
    "starwood": [("wef", "cost", "wh2_main_effect_tech_recruitment_cost_reduction_wef_gladeguard_gladeriders"),
                 ("wef", "rank", "wh2_main_effect_tech_unit_xp_levels_wef_gladeguard_gladeriders"),
                 ("wef", "upkeep", "derpy_mr_effect_upkeep_wef_gladeguard_gladeriders")],
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
                      ("grn", "upkeep", "wh_main_effect_tech_upkeep_reduction_black_orcs_big_uns"),
                      ("ogr", "cost", "wh3_dlc26_effect_recruitment_cost_ogr_hunters_beasts"),
                      ("ogr", "rank", "wh3_dlc26_effect_tech_unit_xp_levels_ogr_hunters_beasts"),
                      ("ogr", "upkeep", "wh3_dlc26_effect_upkeep_ogr_hunters_beasts")],
}

# Bonus effects we mint where CA's nearest covers the wrong units: key -> (donor effect whose row
# and bonus value it copies, CA unit sets it binds to, loc). CA's Wood Elf missile upkeep also
# takes Scouts, Waywatchers, Hawk Riders and Sisters; the cost and rank pair is Glade Guard and
# Glade Riders only, so the upkeep is minted on the pair's own two sets. CA's dragon cost and rank
# effects leave out the Dragon Princes its dragon upkeep covers, and it has none for Lammasu or
# Taurus; those are minted on the units the upkeep names (not CA's chd_monsters set, which also
# holds the Siege Giant its tooltip does not mention).
MINT_FX = {
    "derpy_mr_effect_cost_hef_dragons_dragon_princes": (
        "wh_main_effect_building_recruitment_cost_reduction_hef_def_dragons", ("hef_dragons", "hef_dragonprince"),
        "Recruitment cost: %+n% for Dragons and Dragon Princes"),
    "derpy_mr_effect_rank_hef_dragons_dragon_princes": (
        "wh2_main_effect_building_unit_xp_levels_hef_def_dragons", ("hef_dragons", "hef_dragonprince"),
        "Recruit rank: %+n for Dragons and Dragon Princes"),
    "derpy_mr_effect_cost_chd_lammasu_taurus": (
        "wh_main_effect_building_recruitment_cost_reduction_hef_def_dragons",
        ("wh3_dlc23_chd_lammasu", "wh3_dlc23_chd_great_taurus", "wh3_dlc23_chd_bale_taurus"),
        "Recruitment cost: %+n% for Lammasu, Great Taurus and Bale Taurus units"),
    "derpy_mr_effect_rank_chd_lammasu_taurus": (
        "wh2_main_effect_building_unit_xp_levels_hef_def_dragons",
        ("wh3_dlc23_chd_lammasu", "wh3_dlc23_chd_great_taurus", "wh3_dlc23_chd_bale_taurus"),
        "Recruit rank: %+n for Lammasu, Great Taurus and Bale Taurus units"),
    "derpy_mr_effect_upkeep_wef_gladeguard_gladeriders": (
        "wh2_dlc16_effect_upkeep_reduction_wef_missile_units", ("wef_dlc05_glade_guard", "wef_dlc05_glade_riders"),
        "Upkeep: %+n% for Glade Guard and Glade Riders units"),
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
# The set a rare chain is filed under: CA's own resource-building set, which every race's mines
# sit in (405 chains) - the construction menu's Special group. ECON_SET[race] is the fallback for
# a race whose slots turn out not to list it (Chaos Dwarf slots listed only CHD sets, 2026-10-01).
RESOURCE_SET = "wh2_main_set_resource"
RARE_SET = {race_: RESOURCE_SET for race_ in ECON_SET}
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
            + 2 * len(USE_BUNDLES) + 2 * len(ORDERS) + 2 * len(event_bundles()) + 8 * len(EVENTS) + 1   # 8: 6 dilemma lines, cost and reward; 1: Nothing is spent
            + 2 * len(SUPPLY) + 2 + len(MINT_FX) + 2 + 2 * len(store_stems())   # Exports held; the hidden markers
            + 2 * len(WORK_UPGRADES) + 2 * sum(1 for w in WORK_ITEMS if not w[3])
            + 2   # Recruits
            + 2 * len(recipe_bundles()) + 3 * sum(1 for w in works() if w["kind"] == "trait") + 2)   # recipes

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
                                     "stables", "eyrie", "vineyard", "deep", "toolmaker", "engineer",
                                     "furstash", "coppermine", "darksteeds")}}

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
    # DWARF HOLDS (user, 2026-10-04: a Dwarf hold made nothing where a Chaos Dwarf one made coal
    # and brimstone). One kind per building, so a good lands on the Dwarf building alone and not
    # on a Chaos Dwarf forge or an Empire farm standing in a captured hold.
    "deep": ["wh3_main_underdeep_dwf_resources"],   # the Underdeep mines, where CA digs gems, iron, marble
    "toolmaker": ["wh_main_DWARFS_industry"],       # Toolmakers' forges burn the hold's coal
    "engineer": ["wh_main_DWARFS_engineer"],        # Engineers' Guild: the Thunderers' and cannons' powder
    # OTHER THIN RACES (user, 2026-10-04, each picked from CA's own building description)
    "furstash": ["wh3_main_chs_slaves"],            # Fur Stash: "Mutant pelts ... do not come cheap"
    "coppermine": ["wh2_main_special_copper_mountain_skv"],   # "exploit its massive copper ore deposits"
    "darksteeds": ["wh2_main_def_riders"],          # Plateau of Dark Steeds: Naggaroth's horses
}   # (the Barley Field's grain is an ORIGIN("dwf") branch of grain's farm rule)
FOREIGN_KINDS = {"deep": "wh3_main_set_dwarf_foreign_economy"}   # kind -> the foreign-slot set it lives in
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
# The Old World's "devastate" variant (3813271876) reuses the cr_oldworld key and ships no
# regions of its own, so the one oldworld pack covers it too.
WORKSHOP = r"F:\SteamLibrary\steamapps\workshop\content\1142710"
SUBMODS = {
    "iee": dict(campaign="cr_combi_expanded", port_prefix="cr_port_",
                pack=os.path.join(WORKSHOP, "3007996493", "!cr_immortal_empires_expanded.pack")),
    "oldworld": dict(campaign="cr_oldworld", port_prefix="cr_port_",
                     pack=os.path.join(WORKSHOP, "3081800026", "!cr_oldworld_campaign.pack")),
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
    return _tiers(by)


def _tiers(by):
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
    """Can this region make the good: some source's building can stand here and its rule holds. A
    rare good: its own building, which stands where rare_cond holds."""
    if good in RARE:
        return evaluate(rare_cond(good), g)
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


def hold_key(stem, cond):
    return HOLD_PREFIX + stem + ("__" + cond if cond else "")


def is_hold(r):
    return r["context_requirement"].startswith(HOLD_PREFIX)


def our_exprs():
    """Every condition this pack writes, key -> expression (produce() adds the same rows)."""
    return {cond_key(good, i): render(cond) for good in list(GOODS) + list(CA_GOODS)
            for i, (_pool, cond) in enumerate(good_spec(good)["sources"]) if cond is not None}


def hold_rows(rows, by_fx, exprs):
    """A STOPPED EXPORT'S CANCEL: each production row once more, its values negated, gated by its
    own condition AND the owner's hidden marker for that good - so the cancel is exactly what is
    made, damage and lore gates included, and a good's total never goes below zero. Seen in game
    2026-10-08: a faction-wide -1000 turned every good the faction did not make into an export,
    18,801 gold of trade from 465. Returns (rows, {expression key: text})."""
    out, need = [], {}
    for r in rows:
        stem = by_fx.get(r["effect"])
        # EVERY SCOPE, the twin keeping it: CA's Underdeep and Grungni beer halls make on
        # foreign_building_to_region_own and force_to_region_own, and the drinking halls CONSUME beer
        # there - holding only the building_to_building_own rows left a held beer total below zero,
        # the phantom-export case (sweep 2026-10-08)
        if stem is None or is_hold(r):
            continue
        cond, mark = r["context_requirement"], 'Owner.IsEffectBundleActive("%s%s") == true' % (HOLD_PREFIX, stem)
        k = hold_key(stem, cond)
        need[k] = "(%s) && %s" % (exprs[cond], mark) if cond else mark
        out.append(dict(r, value=-r["value"], value_damaged=-r["value_damaged"], value_ruined=-r["value_ruined"],
                        context_requirement=k))
    return out, need


def _holds(t, add, loc):
    """The hold rows on our production rows and CA's, their conditions, and the 54 hidden markers.
    In files of their own, so every production check reads production; hold_ca is CA-derived and
    the public repo refuses it as it refuses the _ca twins."""
    by_fx = {fx: stem for stem, (_r, fx, _n) in store_stems().items()}
    exprs = {r["key"]: r["expression"] for r in db("building_effect_context_expressions_tables")[1]}
    exprs.update({r["key"]: r["expression"] for r in t["building_effect_context_expressions_tables"][2]})
    need = {}
    for part, src in (("hold", t["building_effects_junction_tables"][2]),
                      ("hold_ca", db("building_effects_junction_tables")[1])):
        rows, n = hold_rows(src, by_fx, exprs)
        need.update(n)
        for r in rows:
            add("building_effects_junction_tables", r, part)
    for k, e in sorted(need.items()):
        add("building_effect_context_expressions_tables",
            {"expression": e, "key": k, "display_only_active_effects": True, "always_show_display_text": False})
    donor, = [r for r in db("effect_bundles_tables")[1] if r["key"] == ORDER_DONOR]
    for stem in store_stems():
        k = HOLD_PREFIX + stem
        add("effect_bundles_tables", dict(donor, key=k, localised_title="[hidden]", localised_description="[hidden]",
                                          ui_icon=""))
        loc += [("effect_bundles_localised_title_" + k, "[hidden]"), ("effect_bundles_localised_description_" + k, "[hidden]")]


def store_rows(t):
    """Every store twin: the ones on our production rows, then the ones on CA's."""
    return ([r for r in t["building_effects_junction_tables"][2]
             if r["effect"].startswith("derpy_mr_store_") and r["effect"] != STORE_CAP_FX]
            + list(t["building_effects_junction_tables:ca"][2]))


def _recruit(add, loc):
    """The recruitment draw's shortfall is paid OUT of the race's CA pool (Armaments, Meat, Food):
    a factor of ours bound to each, spend-only like CA's own wh3_dlc23_chd_hellforge, so
    cm:faction_add_pooled_resource can take from it."""
    import gen_mr_ui as U
    add("pooled_resource_factors_tables", {"key": "derpy_mr_recruit", "is_hidden": False})
    loc += [("pooled_resource_factors_display_name_positive_derpy_mr_recruit", "Recruits"),
            ("pooled_resource_factors_display_name_negative_derpy_mr_recruit", "Recruits")]
    for pool in sorted(c["pool"] for c in U.CURRENCY.values()):
        add("pooled_resource_factor_junctions_tables", {
            "unique_id": "derpy_mr_recruit_" + pool, "factor": "derpy_mr_recruit", "resource": pool,
            "minimum": -2147483647, "maximum": 0, "specific_faction_set": "", "sort_order": 0})


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


def production_rows(good, e, chains_of, made):
    """Each source's rows: one per level of the chains chains_of(pool) gives, gated by its condition."""
    g = good_spec(good)
    for i, (pool, cond) in enumerate(g["sources"]):
        req = "" if cond is None else cond_key(good, i)
        table = TABLES[_kind(pool)]
        for c, levels in sorted(chains_of(pool).items()):
            for n, lvl in enumerate(levels):
                if (lvl, e) in made:   # the building already makes it; that row stands
                    continue
                v = float(max(1, round(table[min(n, len(table) - 1)] * g.get("scale", 1.0))))
                yield {   # damaged = half, as CA's own rows
                    "building": lvl, "effect": e, "effect_scope": "building_to_building_own",
                    "value": v, "value_damaged": damaged(v), "value_ruined": 0.0,
                    "context_requirement": req}


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
        for i, (pool, cond) in enumerate(good_spec(good)["sources"]):
            if cond is not None:
                # display_only_active_effects: the tooltip shows the line only where it applies
                add("building_effect_context_expressions_tables", {
                    "expression": render(cond), "key": cond_key(good, i),
                    "display_only_active_effects": True, "always_show_display_text": False})
        for r in production_rows(good, e, pool_chains, van_made):
            add("building_effects_junction_tables", r)

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
        if good not in RARE:   # a rare good comes from its OWN building only (user, 2026-10-04): its
            produce(good, e)   # sources are just the lore rule that building stands under (rare_cond)
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
            for tpl in rare_templates(good):   # offered ONLY where a lore region's own template is
                add("slot_template_permitted_building_chains_tables",
                    {"chain": ch, "chain_set": "", "remove": False, "slot_template": tpl, "super_chain": ""})
            add("building_set_to_building_junctions_tables",   # ONE set: the game uses only one
                {"building_chain": ch, "building_level": "", "building_set": RARE_SET[race_], "exclude": False})
            for sid in sorted({r["set_id"] for r in rosters   # every roster of the culture, faction ones too
                               if r["culture"] == CULTURES[race_] and not r["campaign"]}):
                add("building_chain_availability_sets_tables", {"building_chain": ch, "id": sid})
            for a, b in zip(bld_levels(ch), bld_levels(ch)[1:]):   # the upgrade edge; without it
                add("building_upgrades_junction_tables", {"from": a, "to": b})   # II and III never build
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
        text = "%s Anywhere else it makes nothing." % spec["where"]
        loc += [("building_short_description_texts_short_description_" + stem, text),
                ("building_description_texts_long_description_" + stem, text)]
    fx_rows = {r["effect"]: r for r in db("effects_tables")[1]}
    for fx, (donor, sets, text) in sorted(MINT_FX.items()):
        add("effects_tables", dict(fx_rows[donor], effect=fx))
        bv, = {r["bonus_value_id"] for r in db("effect_bonus_value_ids_unit_sets_tables")[1] if r["effect"] == donor}
        for us in sets:
            add("effect_bonus_value_ids_unit_sets_tables", {"bonus_value_id": bv, "effect": fx, "unit_set": us})
        loc.append(("effects_description_" + fx, text))
    _stores(t, add, loc)
    _recruit(add, loc)
    _recipe_rows(add, loc)
    _holds(t, add, loc)
    _bundles(add, loc)
    _dilemmas(add, loc)
    _shipments(add, loc)
    _works_rows(add, loc)
    return t, loc


def _shipments(add, loc):
    """Phase 5's map marker: CA's Food Merchant cart under our own key, with our name and tooltip."""
    donor, = [r for r in db("campaign_interactable_marker_infos_tables")[1] if r["key"] == SHIP_MARKER]
    add("campaign_interactable_marker_infos_tables", dict(donor, key=SHIP_INFO, marker_type=SHIP_MARKER))
    loc += [("campaign_interactable_marker_infos_name_" + SHIP_INFO, SHIP_NAME),
            ("campaign_interactable_marker_infos_tooltip_" + SHIP_INFO, SHIP_TIP)]


def check_shipments(t, loc):
    """The marker row draws a prefab CA ships, and carries its name and tooltip."""
    rows = t["campaign_interactable_marker_infos_tables"][2]
    assert [r["key"] for r in rows] == [SHIP_INFO], rows
    types = {r["marker_type"] for r in db("campaign_interactable_marker_infos_tables")[1]}
    assert rows[0]["marker_type"] in types, "no CA marker prefab %s" % rows[0]["marker_type"]
    keys = dict(loc)
    for pre in ("campaign_interactable_marker_infos_name_", "campaign_interactable_marker_infos_tooltip_"):
        assert keys.get(pre + SHIP_INFO), pre + SHIP_INFO


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
    for key, icon_, title, _turns, desc, fx in event_bundles():   # phase 6, region bundles like phase 4's
        add("effect_bundles_tables", dict(donor, key=key, localised_title=title, localised_description=desc,
                                          ui_icon=icon_))
        for e, scope, v in fx:
            add("effect_bundles_to_effects_junctions_tables", {
                "effect_bundle_key": key, "effect_key": e, "effect_scope": scope, "value": float(v),
                "advancement_stage": "start_turn_completed"})
        loc += [("effect_bundles_localised_title_" + key, title),
                ("effect_bundles_localised_description_" + key, desc)]
    for _k, _use, key, icon_, title, what, fx in SUPPLY:   # phase 5, region bundles like phase 4's
        desc = "Supplied from the province capital's stores each turn: %s." % what
        add("effect_bundles_tables", dict(donor, key=key, localised_title=title, localised_description=desc,
                                          ui_icon=icon_))
        for e, scope, v in fx:
            add("effect_bundles_to_effects_junctions_tables", {
                "effect_bundle_key": key, "effect_key": e, "effect_scope": scope, "value": float(v),
                "advancement_stage": "start_turn_completed"})
        loc += [("effect_bundles_localised_title_" + key, title),
                ("effect_bundles_localised_description_" + key, desc)]
    for rare, title, what, icon_, fx, _brief in WORK_UPGRADES:   # the Workshop's upgrades, region bundles that never expire
        key, desc = WORK_UP_PREFIX + rare, "Built from your stores: %s." % what
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
    # THE NAMED RECIPES' BUNDLES (workshop expansion spec section 4): an army work's force bundle on
    # CA's force donor, a lasting work's faction bundle on the order donor
    force, = [r for r in db("effect_bundles_tables")[1] if r["key"] == FORCE_DONOR]
    for target, key, icon_, fx in recipe_bundles():
        w = next(x for x in works() if x.get("bundle") == key)
        title, desc = w["name"], "Paid for from your stores: %s." % (w["gives"][0].lower() + w["gives"][1:])
        add("effect_bundles_tables", dict(force if target == "force" else donor, key=key, localised_title=title,
                                          localised_description=desc, ui_icon=icon_))
        for e, scope, v in fx:
            add("effect_bundles_to_effects_junctions_tables", {
                "effect_bundle_key": key, "effect_key": e, "effect_scope": scope, "value": float(v),
                "advancement_stage": "start_turn_completed"})
        loc += [("effect_bundles_localised_title_" + key, title),
                ("effect_bundles_localised_description_" + key, desc)]
    # EXPORTS HELD: the record flows.lua's F.hold_exports builds its custom bundle on; no effect
    # rows here, the script adds one per stopped good (TRADE_RESOURCES.md 28)
    key, icon_, title, desc = HOLD
    add("effect_bundles_tables", dict(donor, key=key, localised_title=title, localised_description=desc,
                                      ui_icon=icon_))
    loc += [("effect_bundles_localised_title_" + key, title),
            ("effect_bundles_localised_description_" + key, desc)]


def all_bundles():
    """(target, key, icon, effects) of every bundle this pack mints."""
    return [("region", k, i, fx) for _u, k, i, _t, _d, fx in USE_BUNDLES] + \
           [("region", k, i, fx) for k, i, _t, _n, _d, fx in event_bundles()] + \
           [("region", k, i, fx) for _k, _u, k, i, _t, _w, fx in SUPPLY] + \
           [("region", WORK_UP_PREFIX + r, i, fx) for r, _t, _w, i, fx, _b in WORK_UPGRADES] + \
           [("faction", k, i, fx) for _o, _u, k, i, _t, _w, fx in ORDERS] + \
           [("faction", HOLD[0], HOLD[1], [])] + \
           recipe_bundles()   # its effects are the script's (HOLD)


def recipe_bundles():
    """(target, key, icon, effects) of the named recipes' bundles: a force bundle per army work with
    effects, a faction bundle per lasting work (workshop expansion spec section 4)."""
    out = []
    for w in works():
        if w.get("bundle"):
            out.append(("force" if w["kind"] == "army" else "faction", w["bundle"], w["icon"], w["fx"]))
    return out


def _dilemmas(add, loc):
    """Phase 6's dilemmas: two choices each, TEXT_DISPLAY lines only - the flows script spends and rewards."""
    donor, = [r for r in db("dilemmas_tables")[1] if r["key"] == EVENT_DONOR]
    seen = set()
    for e in EVENTS:
        k = event_dilemma(e["key"])
        add("dilemmas_tables", dict(donor, key=k, localised_title=e["title"], localised_description=e["text"],
                                    ui_image=e["image"], sound_popup_override="", sound_click_override="",
                                    override_icon="", generate=False, prioritized=False, event_category="Event",
                                    is_large_dilemma=False))
        loc += [("dilemmas_localised_title_" + k, e["title"]), ("dilemmas_localised_description_" + k, e["text"])]
        for choice, (label, line) in (("FIRST", e["accept"]), ("SECOND", EVENT_DECLINE)):
            add("cdir_events_dilemma_choice_details_tables",
                {"choice_key": choice, "dilemma_key": k, "audio_event_hover": "", "audio_choice_vo": ""})
            pre = "cdir_events_dilemma_choice_details_localised_choice_"
            loc += [(pre + "label_" + k + choice, label), (pre + "title_" + k + choice, line)]
            # THE LIST UNDER THE BUTTON is drawn from payload rows only (seen in game 2026-10-08: none
            # drawn). TEXT_DISPLAY pays nothing, so the flows script still spends and rewards.
            for comp, icon_, state, text in event_lines(e, choice):
                add("cdir_events_dilemma_payloads_tables", {
                    "choice_key": choice, "dilemma_key": k, "id": work_link_key(k + choice + comp),
                    "payload_key": "TEXT_DISPLAY", "value": "LOOKUP[%s]" % comp, "target_key": "default"})
                if (comp, text) not in seen:
                    seen.add((comp, text))
                    add("campaign_payload_ui_details_tables",
                        {"component": comp, "icon": icon_, "state": state, "sort_order": 0})
                    loc.append(("campaign_payload_ui_details_description_" + comp, text))


def event_lines(e, choice):
    """(component, icon, state, text) under a store event's button: the cost and the reward,
    both read off the accept line, or 'Nothing is spent.' under the decline."""
    import gen_mr_ui
    if choice == "SECOND":
        return [("derpy_mr_dil_keep", "", "default", EVENT_DECLINE[1].rstrip("."))]
    cost, reward = e["accept"][1].rstrip(".").split(": ", 1)
    icon_ = e["bundle"][1] if e["bundle"] else e["icon"]
    k = event_dilemma(e["key"])
    return [(k + "_cost", EB_ICONS + gen_mr_ui.USE_ICON[e["use"]], "negative", cost),
            (k + "_reward", EB_ICONS + icon_, "positive", reward[0].upper() + reward[1:])]


EB_ICONS = "ui/campaign ui/effect_bundles/"


def check_dilemmas(t, loc):
    """Each event's dilemma exists with two choices and every loc line; its image is one CA uses;
    its text names only targets the script hands it."""
    keys = dict(loc)
    images = {r["ui_image"] for r in db("dilemmas_tables")[1]}
    rows = {r["key"]: r for r in t["dilemmas_tables"][2]}
    choices = t["cdir_events_dilemma_choice_details_tables"][2]
    pays = t["cdir_events_dilemma_payloads_tables"][2]
    target ={"region": "RegionTargetName", "tribute": "FirstTargetFactionNameWithIcon",
              "arsenal": "CharacterTargetName"}
    for e in EVENTS:
        k = event_dilemma(e["key"])
        assert rows[k]["ui_image"] in images, "no CA dilemma image %s" % rows[k]["ui_image"]
        assert sorted(c["choice_key"] for c in choices if c["dilemma_key"] == k) == ["FIRST", "SECOND"], k
        for pre in ("dilemmas_localised_title_", "dilemmas_localised_description_"):
            assert keys.get(pre + k), pre + k
        for c in ("FIRST", "SECOND"):
            for part in ("label_", "title_"):
                assert keys.get("cdir_events_dilemma_choice_details_localised_choice_" + part + k + c), (k, c, part)
        tokens = set(re.findall(r"\{\{CcoCampaignEventDilemma:(\w+)\}\}", e["text"]))
        want = target["region"] if e["where"] == "region" else target.get(e["key"])
        assert tokens <= {want}, "%s names %s, the script hands it %s" % (k, tokens, want)
        for c in ("FIRST", "SECOND"):
            assert [p for p in pays if p["dilemma_key"] == k and p["choice_key"] == c], "%s%s draws no line" % (k, c)
    assert len(rows) == len(EVENTS)
    # the lines under the buttons: TEXT_DISPLAY only (the script pays), each with its text and a
    # legal state - anything outside CA's four draws nothing (RITUALS.md) - and an icon CA ships
    import gen_mr_emitter as E
    have = E._game_assets()
    ui = {r["component"]: r for r in t["campaign_payload_ui_details_tables"][2]}
    for p in pays:
        assert p["payload_key"] == "TEXT_DISPLAY", p
        comp = p["value"][len("LOOKUP["):-1]
        assert comp in ui and keys.get("campaign_payload_ui_details_description_" + comp), comp
    for r in ui.values():
        assert r["state"] in ("default", "positive", "negative", "positive_if_value_positive"), r
        assert not r["icon"] or r["icon"] in have, "no such icon: %s" % r["icon"]
    ids = [p["id"] for p in pays]
    assert len(set(ids)) == len(ids), "two payload rows share an id"
    assert not set(ids) & {r["id"] for r in db("cdir_events_dilemma_payloads_tables")[1]}, "an id CA uses"


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
    assert len(rows) == len(all_bundles()) + len(store_stems()), sorted(rows)   # + check_holds' markers


def check_hold_part(part, src, rows, exprs):
    """Every production row in src has exactly one hold row in rows: its values negated, its own
    condition AND its good's marker. exprs: every condition either can name, key -> text."""
    by_fx = {fx: stem for stem, (_r, fx, _n) in store_stems().items()}
    made = [r for r in src if r["effect"] in by_fx and not is_hold(r)]
    assert all(is_hold(r) for r in rows), part
    holds = {(r["building"], r["effect"], r["context_requirement"]): r for r in rows}
    assert len(holds) == len(rows) == len(made), "%s: %d hold rows for %d production rows" % (part, len(rows), len(made))
    for p in made:
        stem = by_fx[p["effect"]]
        h = holds.get((p["building"], p["effect"], hold_key(stem, p["context_requirement"])))
        assert h, "%s: no hold row for %s %s" % (part, p["building"], p["effect"])
        for c in ("value", "value_damaged", "value_ruined"):
            assert h[c] == -p[c], "%s %s: hold %s=%r for %r" % (p["building"], p["effect"], c, h[c], p[c])
        e = exprs[h["context_requirement"]]
        assert e.endswith('Owner.IsEffectBundleActive("%s%s") == true' % (HOLD_PREFIX, stem)), e
        if p["context_requirement"]:
            assert e.startswith("(%s) && " % exprs[p["context_requirement"]]), e


def check_holds(t, loc):
    """Every production row, ours and CA's, has exactly one hold row (check_hold_part); every
    marker is a hidden faction bundle."""
    keys = dict(loc)
    exprs = {r["key"]: r["expression"] for r in db("building_effect_context_expressions_tables")[1]}
    exprs.update({r["key"]: r["expression"] for r in t["building_effect_context_expressions_tables"][2]})
    bundles = {r["key"]: r for r in t["effect_bundles_tables"][2]}
    for part, src in ((":hold", t["building_effects_junction_tables"][2]),
                      (":hold_ca", db("building_effects_junction_tables")[1])):
        check_hold_part(part, src, t["building_effects_junction_tables" + part][2], exprs)
    for stem in store_stems():
        b = bundles[HOLD_PREFIX + stem]
        assert b["bundle_target"] == "faction" and b["localised_title"] == "[hidden]", b
        assert keys.get("effect_bundles_localised_title_" + HOLD_PREFIX + stem) == "[hidden]", stem


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
# rare_cond() holds AND a permitted slot template lets the chain in (ai_regions(): the narrower
# list), on IE, the Realm of Chaos, IEE's own and the Old World's. A region whose IEE deposit or origin is
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
    """good -> sorted region keys where its building can be built: the regions of its permitted
    templates, over IE, RoC and every SUBMODS map."""
    _by_reg, by_tpl = _secondary_templates()
    out = {}
    for good in RARE:
        regs = {k for t in rare_templates(good) for k in by_tpl[t]}
        for name in SUBMODS:
            if os.path.isfile(SUBMODS[name]["pack"]):
                regs |= set(rare_submod_templates(good, name).values())
        out[good] = sorted(regs)
    return out


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


# WHERE A RARE BUILDING CAN BE BUILT - the vanilla way. A CA mine is offered only in slots whose
# template permits it, and the startpos gives a deposit region its own template. Which chains a
# template permits is DB (slot_template_permitted_building_chains, a chain or a chain set per row),
# so a rare chain is permitted on the secondary templates of its lore regions and nowhere else: no
# startpos edit, no script. Only a template used by NO other region qualifies - 278 of IE's 307
# secondary templates belong to one region (special settlements all do) - so a lore region on a
# shared template goes without (lore over coverage; user ruling 2026-10-04). Replaced a per-region
# script lock whose call never showed in game. Map mods name a template per region
# (cr_{major,minor,minimal}_secondary_<tail>), so there every lore region qualifies; their
# deposits and origin are in a binary startpos and read EMPTY offline, so a good gated on those
# (gromril, ithilmar) is not permitted there until those facts are supplied.
@functools.lru_cache(None)
def _secondary_templates():
    """(region -> its secondary templates, template -> its regions) on IE and RoC (Assembly Kit)."""
    _tr, _perm, _cp, _t, _rc, sp = srm.load()
    by_reg, by_tpl = collections.defaultdict(set), collections.defaultdict(set)
    for r in sp:
        if r["slot_type"] == "secondary":
            by_reg[r["region"]].add(r["slot_template"])
            by_tpl[r["slot_template"]].add(r["region"])
    return by_reg, by_tpl


@functools.lru_cache(None)
def rare_templates(good):
    """CA's secondary templates a rare good's building is permitted on: every one whose regions are
    ALL lore regions, so nothing leaks."""
    by_reg, by_tpl = _secondary_templates()
    lore = {g["region"] for g in _signals().values() if evaluate(rare_cond(good), g)}
    return tuple(sorted(t for t, regs in by_tpl.items() if regs and regs <= lore))


@functools.lru_cache(None)
def rare_submod_templates(good, name):
    """template -> region on a map mod: each lore region's own secondary template(s)."""
    tpls = {r["key"] for r in _sub_rows(name, "slot_templates_tables")}
    out = {}
    for g in submod_signals(name).values():
        if evaluate(rare_cond(good), g):
            for size in ("major", "minor", "minimal"):
                t = "cr_%s_secondary_%s" % (size, g["tail"])
                if t in tpls:
                    out[t] = g["region"]
    return out


def check_rare_templates(t):
    """Every rare chain is offered somewhere, and no permitted template is used by a region its
    lore does not hold for (the leak a shared template would bring)."""
    by_reg, by_tpl = _secondary_templates()
    chain_good = {ch: gd for gd in RARE for _r, ch in rare_chains(gd)}
    sig = {g["region"]: g for g in _signals().values()}
    tpl_of = collections.defaultdict(set)
    for r in t["slot_template_permitted_building_chains_tables"][2]:
        assert r["chain"] in chain_good and not r["chain_set"], r
        tpl_of[r["chain"]].add(r["slot_template"])
    for ch, gd in chain_good.items():
        assert tpl_of[ch], "%s is permitted nowhere" % ch
        for tpl in tpl_of[ch]:
            assert tpl in by_tpl, "%s: unknown template %s" % (ch, tpl)
            leak = [k for k in by_tpl[tpl] if k not in sig or not evaluate(rare_cond(gd), sig[k])]
            assert not leak, "%s offered outside its lore via %s: %s" % (ch, tpl, leak[:3])
    return sum(len(v) for v in tpl_of.values())


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
    check_holds(t, loc)
    check_dilemmas(t, loc)
    check_shipments(t, loc)
    check_works()
    check_work_rows(t, loc)
    check_recipe_rows(t, loc)
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
    # a hold condition wraps CA's own text, held to its original by check_holds
    names = set(re.findall(r'"([^"]+)"', " ".join(v for k, v in ctx.items() if not k.startswith(HOLD_PREFIX))))
    own_bundles = {r["key"] for r in t["effect_bundles_tables"][2]}   # the hold markers
    regions, groups = _map_data()
    for n in names:   # every string an expression names is a real key of its kind
        assert (n in van_bundles or n in groups or n in regions or n in van_res
                or n in ORIGINS.values() or n in own_bundles), "expression names unknown key %s" % n
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
    # ...except the Underdeep's, built in the Dwarfs' own foreign slots: in CA's Underdeep economy set
    sets = collections.defaultdict(set)
    for r in db("building_set_to_building_junctions_tables")[1]:
        sets[r["building_set"]].add(r["building_chain"])
    for kind, chains in KIND_CHAINS.items():
        ok = sets[FOREIGN_KINDS[kind]] if kind in FOREIGN_KINDS else sec
        bad = [c for c in chains if c not in ok]
        assert not bad, "%s chains not buildable in a %s slot: %s" % (
            kind, "foreign" if kind in FOREIGN_KINDS else "secondary", bad)
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
    check_recruit_factor(t, loc)
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
    assert set(RARE_SET.values()) <= sets, set(RARE_SET.values()) - sets
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
        assert bsets[ch] == [RARE_SET[race_]], "%s building sets %s, want only %s" % (ch, bsets[ch], RARE_SET[race_])
        assert av[ch] and {culture_of[s] for s in av[ch]} == {CULTURES[race_]}, (ch, sorted(av[ch]))
    edges = {(r["from"], r["to"]) for r in t["building_upgrades_junction_tables"][2]}
    for ch in chains:   # level I -> II -> III, or the upper levels never build
        lv = bld_levels(ch)
        assert set(zip(lv, lv[1:])) <= edges, "%s has no upgrade edge" % ch
    # a rare good comes from its own building and nowhere else, as a vanilla mine from its deposit
    rare_fx = {effect(gd): gd for gd in RARE}
    stray = [r for r in t["building_effects_junction_tables"][2]
             if r["effect"] in rare_fx and r["building"] not in ours]
    assert not stray, "rare good made outside its building: %s" % stray[:2]
    check_rare_templates(t)
    # a minted bonus binds the donor's bonus value to CA unit sets that exist, and to nothing else
    sets = {r["unit_set"] for r in db("unit_set_to_unit_junctions_tables")[1]}
    bound = collections.defaultdict(set)
    for r in t["effect_bonus_value_ids_unit_sets_tables"][2]:
        bound[r["effect"]].add(r["unit_set"])
    assert set(bound) == set(MINT_FX), set(bound) ^ set(MINT_FX)
    for fx, (_d, us, _txt) in MINT_FX.items():
        assert bound[fx] == set(us) and set(us) <= sets, (fx, bound[fx])
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
        assert r["effect"] in van_fx or r["effect"] in MINT_FX or r["effect"] in (effect(good), store_fx(good)), \
            "unknown effect %s" % r["effect"]   # its production, its store twin, a CA or minted bonus
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


def check_recruit_factor(t, loc):
    """The recruitment draw's shortfall (workshop expansion spec section 3) is paid OUT of the
    race's CA pool through a spend-only factor of ours, one junction per pool, with its loc."""
    import gen_mr_ui as U
    keys = dict(loc)
    assert {"key": "derpy_mr_recruit", "is_hidden": False} in t["pooled_resource_factors_tables"][2]
    js = {r["resource"]: r for r in t["pooled_resource_factor_junctions_tables"][2] if r["factor"] == "derpy_mr_recruit"}
    assert set(js) == {c["pool"] for c in U.CURRENCY.values()}, set(js)
    for c in U.CURRENCY.values():
        j = js[c["pool"]]
        assert j["minimum"] < 0 == j["maximum"] and j["unique_id"] == "derpy_mr_recruit_" + c["pool"], j
    for side in ("positive", "negative"):
        assert keys.get("pooled_resource_factors_display_name_%s_derpy_mr_recruit" % side) == "Recruits", side


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


def _sub_rows(name, table):
    return [r for _p, _v, rs in rvd.load(SUBMODS[name]["pack"], table) for r in rs]


@functools.lru_cache(None)
def submod_slots(name):
    """(port templates, primary templates, every template) -> the chains each permits, over the
    map mod's OWN templates (the startpos is binary, so found by NAME). Its vanilla regions use
    CA's templates, which the main pack already covers."""
    rows = functools.partial(_sub_rows, name)
    sc = collections.defaultdict(set)
    for r in db("building_chains_tables")[1] + rows("building_chains_tables"):
        sc[r["building_superchain"]].add(r["key"])
    parent = {r["key"]: r["parent_set"]
              for r in db("building_chain_sets_tables")[1] + rows("building_chain_sets_tables")}
    items = collections.defaultdict(list)
    for r in db("building_chain_set_items_tables")[1] + rows("building_chain_set_items_tables"):
        items[r["set"]].append(r)
    perm = srm.permitted(rows("slot_template_permitted_building_chains_tables"), parent, items, sc)
    port = {t: v for t, v in perm.items() if t.startswith(SUBMODS[name]["port_prefix"])}
    prim = {t: v for t, v in perm.items() if "primary" in t}
    return port, prim, perm


@functools.lru_cache(None)
def submod_levels(name):
    """The map mod's OWN chains (no CA chain of that key) -> their non-ruin level rows. Those
    levels exist only in its pack, so a row naming one can only ship in the sub-pack."""
    van = {r["key"] for r in db("building_chains_tables")[1]}
    by = collections.defaultdict(list)
    for r in _sub_rows(name, "building_levels_tables"):
        if r["chain"] not in van and "ruin" not in r["level_name"]:
            by[r["chain"]].append(r)
    return by


def _sub_chains(name, slots):
    lv = submod_levels(name)
    return {c: [r["level_name"] for r in sorted(lv[c], key=lambda r: (r["level"], r["level_name"]))]
            for v in slots.values() for c in v if c in lv}


def submod_pool_chains(name, pool):
    """pool_chains() over the map mod's own port and main-settlement chains; its mines, kinds and
    our rare buildings are all CA chains (check_submod asserts the mines)."""
    port, prim, _perm = submod_slots(name)
    if pool == "port":
        out = {c: v for c, v in _sub_chains(name, port).items() if not NOT_A_HARBOUR.search(c)}
    elif _kind(pool) == "settlement":
        out = {c: v for c, v in _sub_chains(name, prim).items() if not SETTLE_SKIP.search(c)
               and (pool == "settlement" or race(c) in pool[1:])}
    else:
        return {}
    return {c: v for c, v in out.items() if not EXCLUDE.search(c)}


def build_submod(name):
    """One map mod's pack: its campaign links, one row per good, and the rows the main pack cannot
    carry because their building exists only in the map mod - production on its own port and
    settlement chains, their store twins (and twins of its own rows making CA's goods), and store
    space on its own settlements. Row shapes are the main pack's own."""
    ver, van = db("resources_to_campaign_junctions_tables")
    rows = [{"campaign": SUBMODS[name]["campaign"], "resource": key(g)} for g in GOODS]
    assert all(list(r) == list(van[0]) for r in rows)
    t = {"resources_to_campaign_junctions_tables": (ver, list(van[0]), rows)}
    own = {r["level_name"] for v in submod_levels(name).values() for r in v}
    made = {(r["building"], r["effect"]) for r in _sub_rows(name, "building_effects_junction_tables")}
    bej = []
    for good in [x for x in list(GOODS) + list(CA_GOODS) if x not in RARE]:   # rare: own building only
        e = effect(good) if good in GOODS else CA_GOODS[good]["effect"]
        bej += production_rows(good, e, functools.partial(submod_pool_chains, name), made)
    by_fx = {fx: stem for stem, (_r, fx, _n) in store_stems().items()}
    theirs = [r for r in _sub_rows(name, "building_effects_junction_tables") if r["building"] in own
              and r["effect"] in by_fx and r["effect_scope"] == "building_to_building_own"]
    bej += [dict(r, effect=store_fx(by_fx[r["effect"]]), effect_scope="region_to_region_own")
            for r in bej + theirs if r["effect"] in by_fx]
    # the hold rows on this map's own production, as the main pack's (hold_rows)
    exprs = {r["key"]: r["expression"] for r in db("building_effect_context_expressions_tables")[1]}
    exprs.update({r["key"]: r["expression"] for r in _sub_rows(name, "building_effect_context_expressions_tables")})
    exprs.update(our_exprs())
    # every scope, as the main pack's (hold_rows); the store twins above stay on theirs
    holds, need = hold_rows(bej + [r for r in _sub_rows(name, "building_effects_junction_tables")
                                   if r["building"] in own and r["effect"] in by_fx], by_fx, exprs)
    bej += holds
    if need:
        ver, van = db("building_effect_context_expressions_tables")
        t["building_effect_context_expressions_tables"] = (ver, list(van[0]), [
            {"expression": e, "key": k, "display_only_active_effects": True, "always_show_display_text": False}
            for k, e in sorted(need.items())])
        assert all(list(r) == list(van[0]) for r in t["building_effect_context_expressions_tables"][2])
    _port, prim, _perm = submod_slots(name)
    lv = submod_levels(name)
    tiers = _tiers({c: lv[c] for c in {c for v in prim.values() for c in v} if c in lv and not SETTLE_SKIP.search(c)})
    for lvl, n in sorted(tiers.items()):
        v = float(STORE_STEP * min(n, STORE_TOP))
        if v:
            bej.append({"building": lvl, "effect": STORE_CAP_FX, "effect_scope": "region_to_region_own",
                        "value": v, "value_damaged": v, "value_ruined": 0.0, "context_requirement": ""})
    if bej:
        ver, van = db("building_effects_junction_tables")
        assert all(list(r) == list(van[0]) for r in bej)
        t["building_effects_junction_tables"] = (ver, list(van[0]), bej)
    # the rare chains, permitted on this map's own lore-region templates (rare_submod_templates)
    perm = [{"chain": ch, "chain_set": "", "remove": False, "slot_template": tpl, "super_chain": ""}
            for good in sorted(RARE) for _r, ch in rare_chains(good)
            for tpl in sorted(rare_submod_templates(good, name))]
    if perm:
        ver, van = db("slot_template_permitted_building_chains_tables")
        assert all(list(r) == list(van[0]) for r in perm)
        t["slot_template_permitted_building_chains_tables"] = (ver, list(van[0]), perm)
    return t


def check_submod(name, t):
    """The map mod's campaign key is real, and every chain its own port, main-settlement and mine
    slots permit is either CA's (covered by the main pack) or has rows in t."""
    sm = SUBMODS[name]
    assert os.path.isfile(sm["pack"]), "%s not installed: %s" % (name, sm["pack"])
    assert sm["campaign"] in {r["campaign_name"] for r in _sub_rows(name, "campaigns_tables")}, sm["campaign"]
    port, prim, perm = submod_slots(name)
    assert port and prim, "%s: no port or primary templates found - the naming guess is stale" % name
    bej = t.get("building_effects_junction_tables", (0, [], []))[2]
    own = {r["level_name"]: c for c, v in submod_levels(name).items() for r in v}
    assert all(r["building"] in own for r in bej), "%s rows on a level it does not ship" % name
    rowed = collections.defaultdict(set)   # chain -> the effects its levels carry here
    for r in bej:
        rowed[own[r["building"]]].add(r["effect"])
    makes = {c for c, fx in rowed.items() if any(not f.startswith("derpy_mr_store_") for f in fx)}
    skip = {c for c in own.values() if EXCLUDE.search(c)}
    skip |= {c for c in own.values() if NOT_A_HARBOUR.search(c)}
    missing = {c for v in port.values() for c in v} - set(port_chains()) - skip - makes
    assert not missing, "%s port chains with no production rows: %s" % (name, sorted(missing))
    settle = {c for v in prim.values() for c in v if not EXCLUDE.search(c) and not SETTLE_SKIP.search(c)}
    missing = settle - set(pool_chains("settlement")) - makes
    assert not missing, "%s settlement chains with no production rows: %s" % (name, sorted(missing))
    lv = submod_levels(name)   # tier 0 gets the base space only, as in the main pack
    missing = {c for c in settle if c in lv and any(_tiers({c: lv[c]}).values())
               and STORE_CAP_FX not in rowed[c]}
    assert not missing, "%s settlements with no store space: %s" % (name, sorted(missing))
    deposit = {r["key"]: r["resource"] for r in _sub_rows(name, "slot_templates_tables") if r["resource"]}
    for pool in {p for g in GOODS.values() for p, _c in g["sources"] if _kind(p) == "mine"}:
        missing = {c for t_, res in deposit.items() if res in pool[1:] for c in perm.get(t_, ())
                   if "resource" in c and not EXCLUDE.search(c) and not NOT_A_MINE.search(c)} - set(pool_chains(pool))
        assert not missing, "%s %s chains with no production rows: %s" % (name, pool, sorted(missing))
    check_submod_reach(name)
    exprs = {r["key"]: r["expression"] for r in db("building_effect_context_expressions_tables")[1]}
    for x in (_sub_rows(name, "building_effect_context_expressions_tables"),
              t.get("building_effect_context_expressions_tables", (0, [], []))[2]):
        exprs.update({r["key"]: r["expression"] for r in x})
    exprs.update(our_exprs())
    theirs = [r for r in _sub_rows(name, "building_effects_junction_tables") if r["building"] in own]
    check_hold_part(name, bej + theirs, [r for r in bej if is_hold(r)], exprs)
    return len(port)


@functools.lru_cache(None)
def submod_signals(name):
    """The map mod's OWN regions as region signals, from what its pack ships: areas, climate
    (campaign_map_settlements), province, and a coast where a `<port_prefix><tail>` template
    exists. Deposits and cultural origin live only in its binary startpos, so they read empty -
    a deposit- or origin-gated good is UNDER-counted, never over - unless a facts file read live
    through the bridge supplies them (submod_facts)."""
    sm = SUBMODS[name]
    facts = submod_facts(name)

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
        f = facts.get(k, {})
        out[k] = dict(region=k, tail=tail, areas=areas.get(k, set()), climate=climate[k],
                      coastal=(sm["port_prefix"] + tail) in tpls, deposits=set(f.get("deposits", ())),
                      origin=_ORIGIN_CODE.get(f.get("origin", ""), ""),
                      templates=set(), province=prov.get(k, ""), campaign=sm["campaign"])
    return out


# A map mod's deposits and region origin, read LIVE once (tools/../scratch probe: one loop of
# resource_exists and CcoCampaignSettlement ModelRegionContext.OriginatingSubcultureKey) and kept
# beside the TSVs: {region: {"origin": subculture key, "deposits": [resource keys]}}.
FACTS = os.path.join(OUT, "%s_region_facts.json")
_ORIGIN_CODE = {v: k for k, v in ORIGINS.items()}


@functools.lru_cache(None)
def submod_facts(name):
    path = FACTS % name
    if not os.path.isfile(path):
        return {}
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


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
    """No good blankets a whole area IE and RoC lack by a rule with no terrain condition: that is
    a rule with its terrain condition missing - Ind incense reached all 31 Ind regions, peaks and
    jungle alike. An area CA's maps have is vetted there (Norscan mead is all of Norsca on IE
    too), and a terrain rule over an area of one terrain blankets it honestly (the Old World's
    Athel Loren is all forest)."""
    ca_areas = {a for g in _signals().values() for a in g["areas"]}
    # origin discriminates like terrain does: an all-Dwarf area is honestly all Dwarf holds
    plain = {good for good in list(GOODS) + list(CA_GOODS)
             if not any(c is not None and ("climate_" in render(c) or "IsOriginatingSubculture" in render(c))
                        for _p, c in good_spec(good)["sources"])}
    bad = ["%s: %s in all %d regions" % (a, good, n)
           for a, (n, goods) in submod_reach(name).items() if n >= 10 and a not in ca_areas
           for good, k in goods.items() if k == n and good in plain]
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


def copy_build(t):
    """A deep copy of build()'s tables: build() is cached, and a mutation must not stick to it."""
    import copy
    return copy.deepcopy(t)


def selftest():
    t, loc = build()
    check(t, loc)
    print(check_ai(ai_script()).strip().splitlines()[-1])
    for breakit in (lambda t, l: t["effect_bundles_to_effects_junctions_tables"][2][0].update(value=-10.0),
                    lambda t, l: t["effect_bundles_to_effects_junctions_tables"][2][0].update(effect_scope="nowhere"),
                    lambda t, l: next(b for b in t["effect_bundles_tables"][2]
                                      if not b["key"].startswith(HOLD_PREFIX)).update(bundle_target="faction"),
                    lambda t, l: t["effect_bundles_tables"][2][-1].update(bundle_target="region"),
                    lambda t, l: t["effect_bundles_to_effects_junctions_tables"][2][-1].update(value=20.0),
                    lambda t, l: next(b for b in t["effect_bundles_tables"][2]
                                      if not b["key"].startswith(HOLD_PREFIX)).update(ui_icon="no_such.png"),
                    lambda t, l: l.remove([x for x in l if x[0].startswith("effect_bundles_localised_title_")
                                           and HOLD_PREFIX not in x[0]][0])):
        bad, bloc = build()
        breakit(bad, bloc)
        try:
            check_bundles(bad, bloc)
        except AssertionError:
            continue
        raise SystemExit("selftest: a broken bundle passed check_bundles()")
    for breakit in (lambda t, l: t["cdir_events_dilemma_choice_details_tables"][2].pop(),
                    lambda t, l: t["dilemmas_tables"][2][0].update(ui_image="no_such_image"),
                    lambda t, l: l.remove([x for x in l if x[0].startswith("cdir_events_dilemma_choice_details")][0]),
                    lambda t, l: EVENTS[2].update(text=EVENTS[2]["text"] + " {{CcoCampaignEventDilemma:RegionTargetName}}"),
                    lambda t, l: t["campaign_payload_ui_details_tables"][2][0].update(state="text"),
                    lambda t, l: t["campaign_payload_ui_details_tables"][2][0].update(icon="ui/no_such.png"),
                    lambda t, l: t["cdir_events_dilemma_payloads_tables"][2].__setitem__(
                        slice(None), [p for p in t["cdir_events_dilemma_payloads_tables"][2] if p["choice_key"] != "SECOND"])):
        saved = dict(EVENTS[2])
        bad, bloc = build()
        breakit(bad, bloc)
        try:
            check_dilemmas(bad, bloc)
        except AssertionError:
            continue
        finally:
            EVENTS[2].clear(); EVENTS[2].update(saved)
        raise SystemExit("selftest: a broken dilemma passed check_dilemmas()")
    for breakit in (lambda t, l: t["campaign_interactable_marker_infos_tables"][2][0].update(marker_type="no_cart"),
                    lambda t, l: l.remove([x for x in l if x[0].startswith("campaign_interactable_marker_infos_tooltip_")][0])):
        bad, bloc = build()
        breakit(bad, bloc)
        try:
            check_shipments(bad, bloc)
        except AssertionError:
            continue
        raise SystemExit("selftest: a broken marker passed check_shipments()")

    def hold_expr(t, gated):
        return next(r for r in t["building_effect_context_expressions_tables"][2]
                    if r["key"].startswith(HOLD_PREFIX) and ("__" in r["key"]) == gated)
    for breakit in (lambda t, l: t["building_effects_junction_tables:hold"][2].pop(),
                    lambda t, l: t["building_effects_junction_tables:hold_ca"][2].pop(),
                    lambda t, l: t["building_effects_junction_tables:hold"][2][0].update(
                        value=abs(t["building_effects_junction_tables:hold"][2][0]["value"])),
                    lambda t, l: t["building_effects_junction_tables:hold_ca"][2][0].update(value_damaged=0.0),
                    lambda t, l: t["building_effects_junction_tables:hold"][2].append(
                        t["building_effects_junction_tables"][2][0]),
                    lambda t, l: hold_expr(t, False).update(expression="true"),
                    lambda t, l: hold_expr(t, True).update(
                        expression=hold_expr(t, True)["expression"].split(" && ")[-1]),
                    lambda t, l: next(b for b in t["effect_bundles_tables"][2]
                                      if b["key"].startswith(HOLD_PREFIX)).update(localised_title="Coal held"),
                    lambda t, l: t["effect_bundles_tables"][2].remove(
                        next(b for b in t["effect_bundles_tables"][2] if b["key"].startswith(HOLD_PREFIX)))):
        bad, bloc = build()
        breakit(bad, bloc)
        try:
            check_holds(bad, bloc)
        except (AssertionError, KeyError):
            continue
        raise SystemExit("selftest: a broken hold passed check_holds()")
    # a bad row must be caught, or the check proves nothing
    for breakit in (lambda t: t["building_effects_junction_tables"][2].append(
                        dict(t["building_effects_junction_tables"][2][0], building="wh3_main_dae_port_1")),
                    lambda t: t["cai_personality_strategic_resource_values_tables"][2].pop(),
                    lambda t: t["building_upgrades_junction_tables"][2].pop(),   # II never builds
                    lambda t: t["effect_bonus_value_ids_unit_sets_tables"][2].pop(),   # Glade Riders lose it
                    lambda t: t["slot_template_permitted_building_chains_tables"][2].append(   # a shared
                        dict(t["slot_template_permitted_building_chains_tables"][2][0],       # template leaks
                             slot_template="wh_main_human_minor_secondary")),
                    lambda t: t["building_effects_junction_tables"][2].append(   # gromril off a CA mine
                        dict(t["building_effects_junction_tables"][2][0], building="wh_main_dwf_resource_iron_1",
                             effect=effect("gromril"))),
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
        for name in [n for n in SUBMODS if "ind" in submod_reach(n)]:
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
                check_submod(name, build_submod(name))
            except AssertionError:
                continue
            raise SystemExit("selftest: %s passed with a port chain uncovered" % name)
    finally:
        port_chains = real
    for name in SUBMODS:
        st = build_submod(name)
        check_submod(name, st)
        bej = st.get("building_effects_junction_tables", (0, [], []))[2]
        first = next((i for i, r in enumerate(bej) if is_hold(r)), None)   # iee ships no building rows
        try:
            if first is not None:
                check_submod(name, dict(st, building_effects_junction_tables=(0, [], bej[:first] + bej[first + 1:])))
        except AssertionError:
            pass
        else:
            if first is not None:
                raise SystemExit("selftest: %s passed with a hold row gone" % name)
        own = {r["level_name"]: c for c, v in submod_levels(name).items() for r in v}
        for fx in ({r["effect"] for r in bej if not r["effect"].startswith("derpy_mr_store_")}, {STORE_CAP_FX}):
            for c in sorted({own[r["building"]] for r in bej if r["effect"] in fx and not is_hold(r)}):
                cut = dict(st, building_effects_junction_tables=(0, [], [
                    r for r in bej if not (own[r["building"]] == c and r["effect"] in fx)]))
                try:
                    check_submod(name, cut)
                except AssertionError:
                    continue
                raise SystemExit("selftest: %s passed with %s's %s rows gone" % (name, c, sorted(fx)[0]))
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
    # THE WORKSHOP'S MEASURED VALUES: no pack while either is unset
    global RESEARCH_POINTS
    kept = RESEARCH_POINTS
    for rp, bad in ((0, True), (500, False)):
        RESEARCH_POINTS = rp
        try:
            check_measured()
        except AssertionError:
            assert bad, rp
        else:
            assert not bad, "check_measured passed research %r" % rp
    RESEARCH_POINTS = kept
    # THE WORKSHOP'S ROWS: a copied field changed, an effect dropped, a group that replenishes
    for breakit, want in ((lambda t, l: t["ancillaries_tables"][2][0].update(uniqueness_score=1), "differs"),
                          (lambda t, l: t["ancillary_to_effects_tables"][2].pop(), "effects differ"),
                          (lambda t, l: t["mercenary_unit_groups_tables"][2][0].update(chance_to_replenish=1.0),
                           "chance_to_replenish"),
                          (lambda t, l: t["mercenary_pool_to_groups_junctions_tables"][2].pop(), "not linked"),
                          (lambda t, l: l.remove([x for x in l if x[0].startswith("ancillaries_colour_text_")][0]),
                           "ancillaries_colour_text_")):
        bad, bloc = build()
        bad, bloc = copy_build(bad), list(bloc)
        breakit(bad, bloc)
        try:
            check_work_rows(bad, bloc)
        except AssertionError as e:
            assert want in str(e), (want, e)
            continue
        raise SystemExit("selftest: check_work_rows missed: " + want)
    # THE WORKSHOP: a bad grant key, a CA item its race cannot equip, a unit that does not exist
    import copy
    good = copy.deepcopy(works())

    def first(kind):
        return next(x for x in WORKS if x["kind"] == kind)
    for mutate, want in (
            (lambda: first("item").update(grant="derpy_mr_anc_no_such"), "no such item"),
            # the named recipes (workshop expansion spec section 4)
            (lambda: first("convert").update(goods=[("gromril", 20), ("coal", 20)]), "no common store good"),
            (lambda: first("convert").update(races=("tmb",)), "keeps no stores"),
            (lambda: first("convert").update(pool="wh3_main_ogr_meat"), "no FACTION pool"),
            (lambda: first("lasting").update(fx=[("wh_main_effect_force_all_campaign_upkeep", "faction_to_force_own", 10)]),
             "is a penalty"),
            (lambda: first("army").update(fx=[], rank=None), "gives nothing"),
            (lambda: next(x for x in WORKS if x["grant"] == "wh2_main_anc_armour_dragonscale_shield")
             .update(races=("grn",)), "cannot equip"),
            (lambda: next(x for x in WORKS if x["grant"] == "wh3_main_anc_weapon_wyvernbone_bow")
             .update(races=("grn", "ogr")), "cannot equip"),
            (lambda: first("unit").update(grant="wh_main_dwf_inf_no_such"), "no such unit"),
            (lambda: first("unit").update(races=("xyz",)), "no subculture token"),
            (lambda: first("unit").update(pool="no_such_pool"), "no such pool")):
        WORKS[:] = copy.deepcopy(good)
        mutate()
        try:
            check_works()
        except AssertionError as e:
            assert want in str(e), (want, e)
        else:
            raise SystemExit("selftest: check_works missed: " + want)
    WORKS[:] = good
    check_works()
    print("selftest ok")


def modpack(frag):
    """The pack FILE is named for the mod; its DB table files keep FRAG (renamed 2026-10-02)."""
    return os.path.join(ROOT, "Modding Files", "Modpacks", frag.replace(FRAG, PACK_NAME, 1) + ".pack")


def pack(t, frag=FRAG):
    """Build the pack in RPFM from the TSVs on disk, then reopen the SAVED pack and count rows."""
    import tempfile
    import read_pack_index as rpi
    from import_house_ancillaries import call, check_keys
    check_measured()
    call("set_game_selected", {"game_name": "warhammer_3", "rebuild_dependencies": False})
    plan = []
    for tk, (ver, _c, _r) in sorted(t.items(), key=lambda kv: (kv[0] != "ancillary_info_tables", kv[0])):
        # a "table:part" key is a second file of that table; ancillary_info, the parent row, imports first
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
        subs[name] = build_submod(name)
        n = check_submod(name, subs[name])
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
