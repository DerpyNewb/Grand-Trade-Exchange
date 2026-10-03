"""Survey how trade resources are placed on the campaign maps and what can produce them.

    py tools/survey_resource_map.py              # full report
    py tools/survey_resource_map.py --regions    # per-region CSV -> Modding Files/reference/region_resources.csv
    py tools/survey_resource_map.py --selftest

Reads RPFM-free: CA's db.pack through read_vanilla_db (9.0 compiled tables) and the Assembly
Kit's raw start_pos_region_slot_templates.xml, which db.pack does not carry (0 rows there).

The chain this walks, each link a table:

    start_pos_region_slot_templates   campaign + region + slot_type -> slot_template
    slot_templates.resource           slot_template -> the deposit (blank on most)
    slot_template_permitted_building_chains   slot_template -> chain / super_chain / chain_set
    building_chain_sets(.parent_set) + building_chain_set_items   chain_set -> chains, superchains
    building_chains.building_superchain        superchain -> chains
    building_levels.chain                      chain -> level keys
    building_effects_junction  wh_main_effect_region_resource_<stem>_production, scope
                               building_to_building_own -> what a level produces, per turn
"""
import collections, os, re, sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import read_vanilla_db as rvd

AK = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III\assembly_kit\raw_data\db"
GENERIC = 20   # a chain permitted in more templates than this counts as an ordinary building
PROD = re.compile(r"effect_region_resource_([a-z_]+)_production$")
# Stem -> resource key, from gen_zharr_exchange.PRODUCTION_STEMS (resolved there by icon and
# unit, never by name: beer is res_rom_glass, pottery res_rom_textiles, salt res_rom_lead).
# Copied rather than imported - that module runs its whole build at import time.
STEMS = {"animals": "res_animals", "beer": "res_rom_glass", "dyes": "res_dyes",
         "furs": "res_rom_furs", "gem": "res_gems", "gold_idols": "res_gold_idols",
         "iron": "res_rom_iron", "ivory": "res_ivory", "marble": "res_rom_marble",
         "medicine": "res_medicine", "obsidian": "res_obsidian", "pottery": "res_rom_textiles",
         "salt": "res_rom_lead", "spices": "res_spices", "timber": "res_rom_timber",
         "trinkets": "res_trinkets", "wine": "res_rom_wine", "gold": "res_gold"}


def db(table):
    return [r for _p, _v, rows in rvd.load(rvd.DB_PACK, table) for r in rows]


def ak(table):
    return [{c.tag: (c.text or "") for c in rec}
            for rec in ET.parse(os.path.join(AK, table + ".xml")).getroot() if rec.tag == table]


def expand_set(name, set_parent, set_items, sc_chains, seen=()):
    """chain_set -> set of chains, parent first, then this set's adds, then its removes."""
    if name in seen:
        return set()
    out = expand_set(set_parent[name], set_parent, set_items, sc_chains, seen + (name,)) \
        if set_parent.get(name) else set()
    for it in set_items.get(name, ()):
        got = {it["chain"]} if it["chain"] else sc_chains.get(it["super_chain"], set())
        out = out - got if it["remove"] else out | got
    return out


def permitted(rows, set_parent, set_items, sc_chains):
    """slot_template -> set of chains it may build."""
    out = collections.defaultdict(set)
    for remove_pass in (False, True):
        for r in rows:
            if bool(r["remove"]) != remove_pass:
                continue
            if r["chain"]:
                got = {r["chain"]}
            elif r["super_chain"]:
                got = sc_chains.get(r["super_chain"], set())
            else:
                got = expand_set(r["chain_set"], set_parent, set_items, sc_chains)
            if remove_pass:
                out[r["slot_template"]] -= got
            else:
                out[r["slot_template"]] |= got
    return out


def load():
    tpl_res = {r["key"]: r["resource"] for r in db("slot_templates_tables")}
    sc_chains = collections.defaultdict(set)
    for r in db("building_chains_tables"):
        sc_chains[r["building_superchain"]].add(r["key"])
    set_parent = {r["key"]: r["parent_set"] for r in db("building_chain_sets_tables")}
    set_items = collections.defaultdict(list)
    for r in db("building_chain_set_items_tables"):
        set_items[r["set"]].append(r)
    perm = permitted(db("slot_template_permitted_building_chains_tables"),
                     set_parent, set_items, sc_chains)
    level_chain = {r["level_name"]: r["chain"] for r in db("building_levels_tables")}
    # chain -> {resource: max per-turn output over its levels}
    chain_prod = collections.defaultdict(dict)
    for r in db("building_effects_junction_tables"):
        m = PROD.search(r["effect"])
        if not m or r["effect_scope"] != "building_to_building_own" or r["building"] not in level_chain:
            continue
        res = STEMS.get(m.group(1), "stem:" + m.group(1))
        c = chain_prod[level_chain[r["building"]]]
        c[res] = max(c.get(res, 0), r["value"])
    tradeable = sorted(r["key"] for r in db("resources_tables") if r["trade_value"])
    res_campaign = collections.defaultdict(set)
    for r in db("resources_to_campaign_junctions_tables"):
        res_campaign[r["resource"]].add(r["campaign"])
    sp = ak("start_pos_region_slot_templates")
    return tpl_res, perm, chain_prod, tradeable, res_campaign, sp


def report():
    tpl_res, perm, chain_prod, tradeable, res_campaign, sp = load()
    by_campaign = collections.defaultdict(lambda: collections.defaultdict(set))  # camp -> region -> templates
    for r in sp:
        by_campaign[r["campaign"]][r["region"]].add(r["slot_template"])

    print("== Campaigns in start_pos_region_slot_templates (Assembly Kit)")
    for camp, regions in sorted(by_campaign.items(), key=lambda kv: -len(kv[1])):
        dep = sum(1 for ts in regions.values() if any(tpl_res.get(t) for t in ts))
        print("  %-28s %4d regions, %4d with a deposit template" % (camp, len(regions), dep))

    print("\n== Deposit regions per resource, per campaign (regions whose templates carry it)")
    camps = [c for c, _ in sorted(by_campaign.items(), key=lambda kv: -len(kv[1]))][:4]
    all_res = sorted({v for v in tpl_res.values() if v})
    print("  %-22s %s  campaigns listed in resources_to_campaign" % ("", " ".join("%14s" % c[:14] for c in camps)))
    for res in all_res:
        n = [sum(1 for ts in by_campaign[c].values() if any(tpl_res.get(t) == res for t in ts)) for c in camps]
        mark = "*" if res in tradeable else " "
        print("  %s%-21s %s  %s" % (mark, res, " ".join("%14d" % x for x in n),
                                     ",".join(sorted(res_campaign.get(res, ()))) or "-"))
    print("  (* = tradeable, trade_value > 0)")

    print("\n== Per tradeable resource: who can build a producer, and where")
    deposit_tpls = collections.defaultdict(set)
    for t, res in tpl_res.items():
        if res:
            deposit_tpls[res].add(t)
    for res in tradeable:
        producers = {c for c, p in chain_prod.items() if res in p}
        on_dep = set().union(*(perm.get(t, set()) for t in deposit_tpls[res])) if deposit_tpls[res] else set()
        dep_producers = producers & on_dep
        dep_dead = sorted(c for c in on_dep if "_resource_" in c and res not in chain_prod.get(c, {}))
        # templates that permit a producer of res without carrying the res deposit, and the
        # regions that actually use them - those regions produce res with resource_exists false
        # A producer allowed in many templates is an ordinary building (DEF beast pens, HEF
        # industry); one allowed in a few is a landmark or a one-off template. Report them apart.
        n_tpl = {c: sum(1 for t, cs in perm.items() if tpl_res.get(t) != res and c in cs) for c in producers}
        common = sorted("%s (%d)" % (c, n) for c, n in n_tpl.items() if n > GENERIC)
        few = {c for c, n in n_tpl.items() if 0 < n <= GENERIC}
        few_tpl = {t for t, cs in perm.items() if tpl_res.get(t) != res and cs & few}
        few_regions = sorted({"%s/%s" % (r["campaign"].replace("wh3_main_", ""), r["region"].split("_region_")[-1])
                              for r in sp if r["slot_template"] in few_tpl})
        unplaced = sorted(producers - set().union(*perm.values()))
        print("  %s: %d producing chains (%d on its deposit), %d deposit templates" %
              (res, len(producers), len(dep_producers), len(deposit_tpls[res])))
        if common:
            print("    ordinary buildings, no deposit needed (templates): %s" % ", ".join(common))
        if few_regions:
            print("    special templates without the deposit, %d regions: %s"
                  % (len(few_regions), ", ".join(few_regions)))
        if dep_dead:
            print("    resource chains on its deposit that produce none of it: %s" % ", ".join(dep_dead))
        if unplaced:
            print("    producing chains no slot template permits: %s" % ", ".join(unplaced))

    print("\n== Deposit templates that permit no producer of their own resource")
    for t in sorted(tpl_res):
        res = tpl_res[t]
        if res in tradeable and not any(res in chain_prod.get(c, {}) for c in perm.get(t, ())):
            print("  %-60s %s" % (t, res))

    other = sorted({r for p in chain_prod.values() for r in p if r not in tradeable})
    print("\n== Production stems that are not tradeable: %s" % (", ".join(other) or "none"))


def regions(out_csv):
    """One row per (campaign, region): its deposits and every trade good a building allowed
    in its own templates can produce. Ordinary buildings allowed nearly everywhere (DEF/LZD
    beasts, KSL bears, Dwarf tavern, HEF industry) are left out of the rows and named once."""
    import csv
    import read_vanilla_loc as loc
    tpl_res, perm, chain_prod, tradeable, _rc, sp = load()
    names = loc.load("regions")
    rnames = loc.load("resources")
    rname = lambda k: rnames.get("resources_onscreen_text_" + k, k)
    # Ordinary = allowed in many templates that do NOT carry the good it makes. Counting all
    # templates calls every iron mine ordinary: there are 22 iron deposit templates.
    generic = {c for c, p in chain_prod.items()
               if sum(1 for t, cs in perm.items() if c in cs and tpl_res.get(t) not in p) > GENERIC}
    by = collections.defaultdict(set)
    for r in sp:
        by[(r["campaign"], r["region"])].add(r["slot_template"])
    rows = []
    for (camp, reg), ts in sorted(by.items()):
        deposits = sorted({tpl_res[t] for t in ts if tpl_res.get(t)})
        goods = sorted({res for t in ts for c in perm.get(t, ()) if c not in generic
                        for res in chain_prod.get(c, {}) if res in tradeable})
        rows.append({"campaign": camp,
                     "region": names.get("regions_onscreen_" + reg, reg),
                     "region_key": reg,
                     "deposit": ", ".join(rname(d) for d in deposits),
                     "can_produce": ", ".join(rname(g) for g in goods),
                     "without_deposit": ", ".join(rname(g) for g in goods if g not in deposits)})
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for camp in sorted({r["campaign"] for r in rows}):
        cr = [r for r in rows if r["campaign"] == camp]
        print("%-16s %4d regions, %4d can produce a trade good, %3d of them without a deposit for it"
              % (camp, len(cr), sum(1 for r in cr if r["can_produce"]),
                 sum(1 for r in cr if r["without_deposit"])))
    print("ordinary buildings left out (allowed almost everywhere): %s"
          % ", ".join("%s -> %s" % (c, "/".join(rname(x) for x in chain_prod[c])) for c in sorted(generic)))
    print("wrote %s" % out_csv)


def selftest():
    sc = {"sc_iron": {"emp_iron", "dwf_iron"}}
    parent = {"base": "", "child": "base"}
    items = {"base": [{"chain": "", "super_chain": "sc_iron", "remove": False}],
             "child": [{"chain": "farm", "super_chain": "", "remove": False},
                       {"chain": "dwf_iron", "super_chain": "", "remove": True}]}
    assert expand_set("child", parent, items, sc) == {"emp_iron", "farm"}
    rows = [{"slot_template": "t", "chain": "", "super_chain": "", "chain_set": "child", "remove": False},
            {"slot_template": "t", "chain": "farm", "super_chain": "", "chain_set": "", "remove": True},
            {"slot_template": "t", "chain": "", "super_chain": "sc_iron", "chain_set": "", "remove": False}]
    # removes apply after every add, whatever the row order
    assert permitted(rows, parent, items, sc)["t"] == {"emp_iron", "dwf_iron"}
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--regions" in sys.argv:
        regions(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Modding Files",
                             "reference", "region_resources.csv"))
    else:
        report()
