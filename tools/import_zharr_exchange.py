"""Pack the Zharr Exchange.

    py tools/gen_zharr_exchange.py     # writes the TSVs
    py tools/import_zharr_exchange.py  # builds the pack (needs RPFM open)

The MCP plumbing - session handling, SSE parsing, and the mandatory duplicate-combined-key scan
that runs before anything is written - is imported from import_house_ancillaries rather than
copied. That module does nothing at import time; its main() is under __main__.

Table versions are NOT hardcoded here. gen_zharr_exchange.table_version() reads CA's own shipped
definition out of the cached RPFM dump, so a game patch that bumps a version cannot leave this
script writing rows in a shape the game no longer expects.
"""
import io
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from import_house_ancillaries import call, check_keys  # noqa: E402

import gen_zharr_exchange as G  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_DATA_HINT = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III\data"
# RENAMED 2026-09-09, from derpy_chd_zharr_exchange.pack. The mod covers eight cultures and
# "chd" in the filename had stopped being true.
#
# THE PACK BASENAME IS THE ONLY NAME THAT MOVED, and two lookalikes deliberately did not:
#
#   G.FRAG is the DB TABLE filename inside the pack (db/<table>_tables/<FRAG>) and the loc
#   file. It only has to be unique across installed mods, which it is; renaming it rewrites
#   eleven table paths and buys nothing.
#
#   mct:register_mod("derpy_chd_zharr_exchange") in the generated MCT file is the key every
#   player's MCT settings are STORED under. Changing it silently resets the difficulty, all
#   26 sliders and all seven switches for anyone who had configured them.
#
# AND THE OLD NAME MUST NOT BE LEFT IN data/. Two packs shipping the same internal paths -
# the same DB table files, the same zzz_derpy_chd_exchange.lua - is a load-order coin toss,
# not a merge. check_no_stale_pack() below refuses to build while both are installed.
PACK = os.path.join(ROOT, "Modding Files", "Modpacks", "derpy_zharr_exchange.pack")
OLD_PACK_NAMES = ("derpy_chd_zharr_exchange.pack",)


def check_no_stale_pack():
    """Refuse to build if a previous name is still live in the game's data folder.

    The rename is only safe because exactly one of these loads. Both present means both are
    read, they carry byte-identical internal paths, and which one wins is load order - so the
    game could be running a build from a week ago with no sign that it is.
    """
    data = GAME_DATA_HINT
    if not os.path.isdir(data):
        return
    live = [n for n in OLD_PACK_NAMES if os.path.isfile(os.path.join(data, n))]
    if live:
        raise SystemExit(
            "%s is still in %s alongside the renamed pack. Both would load, both ship the "
            "same internal paths, and which one the game reads is load order. Delete the old "
            "one (its .bak_* copies are inert - only a name ending in .pack loads) and "
            "re-run." % (", ".join(live), data))

# Referenced tables before the tables that reference them.
ORDER = [
    "pooled_resources_tables",
    "pooled_resource_factor_junctions_tables",
    "campaign_group_pooled_resources_tables",
    # effects_tables is GONE (stage 2, 2026-09-05) - this pack now mints no effect of its own,
    # only CA's. These two stay: they carry the trade-income steps, the offering bundles and the
    # wrath bundle, all live. The dead price ladder that used to dominate them is what went.
    "effect_bundles_tables",
    "effect_bundles_to_effects_junctions_tables",
    # Hashut's demands. The dilemma rows must be in the pack before the script can launch one:
    # cm:launch_custom_dilemma_from_builder on a key with no row is a silent no-op, so a missing
    # table here looks exactly like a subsystem that was never written.
    # Hashut's demands are an EVENT FEED MESSAGE now, not a dilemma - a DilemmaChoiceMadeEvent
    # listener that matches hard-crashes the game (handoff section 30). show_message_event's
    # index resolves through all four of these, and a record missing any one of them draws
    # nothing at all, so they ship together or not at all.
    "campaign_groups_tables",
    "campaign_group_members_tables",
    "campaign_group_member_criteria_values_tables",
    "event_feed_message_events_tables",
    # THE ONLY TABLE IN THIS PACK THAT EDITS A VANILLA ROW'S SUBJECT rather than minting a key
    # of our own: five Chaos Dwarf resource buildings that produce no trade good in vanilla.
    # Last in the order because it references nothing this pack owns - the buildings and the
    # effects are all CA's. See CHD_TRADE_GRANT in gen_zharr_exchange.py.
    "building_effects_junction_tables",
]

# Loose files added after the tables, straight from the pack mirror.
SCRIPTS = ["script/campaign/mod/zzz_derpy_chd_exchange.lua",
           # The production map: 781 buildings and what each makes per turn, generated
           # by gen_zharr_exchange.write_production_lua. Its own file because it is data,
           # and read lazily by the scan because mod scripts autoload in no set order.
           "script/campaign/mod/zzz_derpy_chd_exchange_prod.lua",
           # Task 10: MCT registration, generated by gen_zharr_exchange.write_mct_lua. MCT scans
           # script/mct/settings/*.lua inside every pack, so without this loose file here the
           # seven toggles exist in EX.setting's Lua but MCT never learns of them - the mod would
           # ship functionally toggle-less, same as derpy_chd_house_ancillaries.pack's own copy.
           "script/mct/settings/derpy_chd_zharr_exchange.lua",
           "ui/campaign ui/derpy_chd_exchange_panel.twui.xml",
           "ui/campaign ui/derpy_chd_exchange_row.twui.xml",
           "ui/campaign ui/derpy_chd_exchange_button.twui.xml"]


def run_selftests():
    """BOTH generators, before anything is packed.

    The TSV row check in main() only proves the DB half is current. The Lua and the .twui.xml
    are copied into the pack verbatim, so nothing between an edit and the Workshop looked at
    them - and the two gates that DO look are separate commands a human has to remember.

    That gap is not theoretical. The log view reached this function with no EX.HEADERS entry:
    refresh_panel walks pairs(EX.HEADERS[EX.mode]) BEFORE it branches on the mode, so the first
    player to reach the fifth view would have indexed nil and taken the panel's whole refresh
    down. gen_exchange_ui.py --selftest catches it in a second; nothing on the packing path was
    asking.
    """
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    for gen in ("gen_zharr_exchange.py", "gen_exchange_ui.py"):
        r = subprocess.run([sys.executable, os.path.join(here, gen), "--selftest"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
            raise SystemExit("%s --selftest failed - refusing to pack:\n  %s"
                             % (gen, "\n  ".join(tail)))
        print("  selftest ok: %s" % gen)


def main():
    tables = G.build()
    G.check_against_vanilla(tables)
    db = sorted(k for k in tables if k != "loc")
    assert sorted(ORDER) == db, "ORDER and build() disagree:\n  %s\n  %s" % (sorted(ORDER), db)

    # Every new MCP session must bind the schema itself - the game key is global and persisted,
    # the schema binding is per-session. rebuild_dependencies=False skips the 105MB rebuild,
    # which check_keys does not need since a combined key is intra-table.
    call("set_game_selected", {"game_name": "warhammer_3", "rebuild_dependencies": False})

    plan = []
    for table in ORDER:
        plan.append(("db/%s/%s" % (table, G.FRAG),
                     {"DB": [G.FRAG, table, G.table_version(table)]},
                     "%s__%s.tsv" % (table, G.FRAG),
                     G.OUT))
    plan.append(("text/db/%s.loc" % G.FRAG, {"Loc": G.FRAG},
                 "loc__%s.tsv" % G.FRAG, G.OUT))

    for entry in plan:
        full = os.path.join(entry[3], entry[2])
        if not os.path.isfile(full):
            raise SystemExit("missing %s - run gen_zharr_exchange.py first" % full)
        assert entry[0] == entry[0].lower(), "uppercase in a pack path crashes since 6.1"

    # THE TSVs ON DISK ARE NOT NECESSARILY WHAT build() SAYS. This packs files, not the objects
    # above, so an edit to gen_zharr_exchange.py that was only ever --selftested still ships the
    # PREVIOUS generate. Caught 2026-09-04: dropping Labour cut build() to 38 rituals while the
    # stale TSVs packed 40, and the pack would have shipped the broken instrument.
    for table in ORDER:
        full = os.path.join(G.OUT, "%s__%s.tsv" % (table, G.FRAG))
        on_disk = sum(1 for _ in open(full, encoding="utf-8")) - 2
        want = len(tables[table][1])
        if on_disk != want:
            raise SystemExit(
                "%s.tsv has %d rows but build() makes %d - re-run gen_zharr_exchange.py"
                % (table, on_disk, want))

    check_no_stale_pack()
    check_keys(plan)
    run_selftests()

    # THE .twui.xml ON DISK IS NOT NECESSARILY WHAT gen_exchange_ui.py BUILDS, and its
    # --selftest cannot tell you: that builds every file in memory and asserts on the result
    # without ever looking at the folder. Exactly the trap the TSV check above exists for, and
    # it bit on 2026-09-09 - the deep chart's 40 bar components were built, selftested at 285
    # GUIDs and shipped as a 40,236-byte panel file that did not contain one of them. The Lua
    # reached for cbar_00 forever and nothing anywhere said why.
    import gen_exchange_ui as U
    for name, fn, comment in U.FILES:
        built = U.layout(fn(), comment)
        path = os.path.join(U.OUT, name)
        if not os.path.isfile(path):
            raise SystemExit("%s has never been written - run gen_exchange_ui.py" % name)
        on_disk = io.open(path, encoding="utf-8", newline="\n").read()
        if on_disk != built:
            raise SystemExit(
                "%s on disk is %d bytes and gen_exchange_ui.py builds %d - re-run "
                "`py tools/gen_exchange_ui.py`. --selftest does NOT write the files."
                % (name, len(on_disk), len(built)))
    print("  ui files match the generator")

    pack = call("new_pack", {})["String"]
    print("new pack: %s" % pack)

    total = 0
    for path, newfile, tsv, folder in plan:
        full = os.path.join(folder, tsv)
        call("new_packed_file", {"pack_key": pack, "path": path,
                                 "new_file": json.dumps(newfile)})
        call("import_tsv", {"pack_key": pack, "table_path": path, "tsv_path": full})
        rows = sum(1 for _ in open(full, encoding="utf-8")) - 2
        total += rows
        print("  %5d  %s" % (rows, path))

    for rel in SCRIPTS:
        src = os.path.join(ROOT, "Modding Files", "pack", *rel.split("/"))
        if not os.path.isfile(src):
            raise SystemExit("missing %s" % src)
        assert rel == rel.lower(), "uppercase in a pack path crashes since 6.1"
        call("add_packed_files", {"pack_key": pack, "source_paths": [src],
                                  "destination_paths": json.dumps([{"File": rel}])})
        print("  %5dB  %s" % (os.path.getsize(src), rel))

    call("save_pack_as", {"pack_key": pack, "path": PACK})
    print("\nsaved %s\n  %d files, %d rows" % (PACK, len(plan) + len(SCRIPTS), total))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError:
        sys.exit("RPFM is not running - its MCP server only exists while RPFM is open")
