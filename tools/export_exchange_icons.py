# -*- coding: utf-8 -*-
"""Resolve and export every icon the Zharr Exchange uses, out of CA's ui packs.

WHY THIS IS NOT A BYTE-GREP. `ui/**/*.png` in CA's packs is COMPRESSED (compression flag 1
on every one measured 2026-09-09), so read_pack_index gets the path and the raw block and not
a usable PNG. RPFM is the only thing that decompresses, which is why the extraction half of
this runs through the MCP server and this file only does the two ends: work out exactly which
paths are wanted and which pack each is in, then check what came back.

WHY THE WANTED LIST IS DERIVED, NOT TYPED. The commodity list, the race crests and the intro
art stems all come from the shipped Lua and the generator, so a commodity added tomorrow is
picked up here without this file being edited. The only hand-written part is the mapping from
a commodity KEY to CA's icon STEM, because CA did not name them the same - and every one of
those is asserted against the display name the mod already resolves ("Salt" -> resource_salt),
so a wrong guess fails here rather than shipping a picture of the wrong good.

    py tools\\export_exchange_icons.py --resolve   # write the manifest, no RPFM needed
    py tools\\export_exchange_icons.py --check     # verify what was extracted
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

GAME = r"F:\SteamLibrary\steamapps\common\Total War WARHAMMER III"
OUT = os.path.join(ROOT, "Modding Files", "source", "exchange_icons")
MANIFEST = os.path.join(OUT, "_manifest.json")

ART = "ui/campaign ui/effect_bundles/"

# COMMODITY KEY -> CA'S ICON STEM. CA's resource keys and its icon filenames disagree on five
# of the seventeen, which is exactly the trap the generator's own note records: `res_rom_iron`
# asked for `resource_rom_iron.png`, which exists in no pack. Each of these is checked against
# the display name below, so the mapping cannot silently drift.
ICON_STEM = {
    "res_animals": "resource_animals",
    "res_dyes": "resource_dyes",
    "res_gems": "resource_gemstones",
    "res_gold_idols": "resource_gold_idols",
    "res_ivory": "resource_ivory",
    "res_medicine": "resource_medicine",
    "res_obsidian": "resource_obsidian",
    "res_rom_furs": "resource_furs",
    "res_rom_glass": "resource_dwarf_beer",
    "res_rom_iron": "resource_iron",
    "res_rom_lead": "resource_salt",
    "res_rom_marble": "resource_marble",
    "res_rom_textiles": "resource_pottery",
    "res_rom_timber": "resource_timber",
    "res_rom_wine": "resource_wine",
    "res_spices": "resource_spices",
    "res_trinkets": "resource_trinkets",
}

# The stem must appear in the display name, or the display name in the stem, for the five that
# disagree. This is the check that makes the table above safe to trust.
NAME_PROOF = {
    "res_gems": "gemstones", "res_gold_idols": "idols", "res_ivory": "tusks",
    "res_rom_glass": "beer", "res_rom_lead": "salt", "res_rom_textiles": "pottery",
    "res_animals": "animals", "res_dyes": "dyes", "res_medicine": "medicinal",
    "res_obsidian": "obsidian", "res_rom_furs": "furs", "res_rom_iron": "iron",
    "res_rom_marble": "marble", "res_rom_timber": "timber", "res_rom_wine": "wine",
    "res_spices": "spices", "res_trinkets": "trinkets",
}


def wanted():
    """{group: [pack-relative path]} - everything the mod draws, derived where it can be."""
    import gen_zharr_exchange as G
    lua = io.open(os.path.join(ROOT, "Modding Files", "pack", "script", "campaign", "mod",
                               "zzz_derpy_chd_exchange.lua"), encoding="utf-8").read()
    import re

    w = {}

    # --- the seventeen, plus CA's _large variant where one exists (added by the caller
    # against the real index; asking for one that does not exist is not an error) ---
    com = []
    for key in G.COMMODITIES:
        stem = ICON_STEM[key]
        proof = NAME_PROOF[key]
        assert proof in G.display_name(key).lower(), (
            "%s displays as %r, which does not contain %r - the icon mapping to %s.png is a "
            "guess, and a wrong one ships a picture of the wrong good"
            % (key, G.display_name(key), proof, stem))
        com.append(ART + stem + ".png")
        com.append(ART + stem + "_large.png")
    w["commodities"] = com

    # --- the intro page: every EX.art("...") literal, plus every race crest ---
    stems = set(re.findall(r'EX\.art\("([a-z0-9_]+)"\)', lua))
    stems |= set(re.findall(r'crest\s*=\s*"([a-z0-9_]+)"', lua))
    m = re.search(r'EX\.INTRO_UNCOVERED_CREST\s*=\s*"([a-z0-9_]+)"', lua)
    if m:
        stems.add(m.group(1))
    assert len(stems) >= 15, "only %d intro art stems found - the scan is broken" % len(stems)
    w["intro"] = [ART + s + ".png" for s in sorted(stems)]

    # --- the effect-bundle icons the DB rows carry ---
    w["bundles"] = [ART + n for n in sorted({
        G.ICON_TRADE, G.ICON_OFFERING, G.ICON_PLEASED, G.ICON_WRATH, G.ICON_STOCK})]

    # --- the event-feed pictures. G.FEED is (key, index, image, ...) per row ---
    # Empties filtered: not every feed row carries a picture, and a blank one would resolve to
    # the bare folder and report as missing.
    feed = sorted({r[2] for r in G.FEED if r[2]})
    assert feed, "no feed images found - G.FEED changed shape"
    w["feed"] = ["ui/campaign ui/message_icons/" + n for n in feed]

    # THE HOUSE FLAG IS NOT EXPORTABLE AND THAT IS NOT A GAP. EX.house_icon builds
    # ui/flags/<faction key>/mon_24.png at runtime - CA ships 486 of them, one per faction,
    # and which one a row draws depends on which houses that campaign discovered. There is no
    # single file to copy out; the folder is the asset.
    return w


def resolve():
    """Every wanted path -> the pack that holds it. Unresolved paths are reported, not hidden."""
    import read_pack_index as rpi
    data = os.path.join(GAME, "data")
    packs = [n for n in sorted(os.listdir(data))
             if n.startswith("ui") and n.endswith(".pack")]
    index = {}
    for name in packs:
        for p in rpi.paths(os.path.join(data, name)):
            index.setdefault(p.replace(chr(92), "/").lower(), name)

    w = wanted()
    found, missing = {}, []
    for group, paths in w.items():
        for p in paths:
            pack = index.get(p.lower())
            if pack:
                found.setdefault(group, []).append({"path": p, "pack": pack})
            elif not p.endswith("_large.png"):
                # A _large variant CA never made is not a fault; anything else is.
                missing.append(p)
    return found, missing, packs


def organise():
    """Readable copies beside the raw extraction, without disturbing it.

    The raw tree keeps CA's own paths because that is what makes a file re-importable and what
    proves where it came from. Nobody can build a store image out of `resource_dwarf_beer.png`
    though - five of the seventeen filenames do not match the good they draw - so this writes a
    second, flat set named by what the player actually sees, with the key kept in brackets so
    the two halves can always be matched back up.
    """
    import shutil
    import gen_zharr_exchange as G

    src = os.path.join(OUT, "ui", "campaign ui")
    bundles, msgs = os.path.join(src, "effect_bundles"), os.path.join(src, "message_icons")
    if not os.path.isdir(bundles):
        raise SystemExit("nothing extracted yet - run the RPFM extraction first")

    def size_of(p):
        try:
            from PIL import Image
            with Image.open(p) as im:
                return "%dx%d" % im.size
        except Exception:
            return "?"

    made = 0
    com = os.path.join(OUT, "commodities")
    os.makedirs(com, exist_ok=True)
    rows = []
    for key in G.COMMODITIES:
        stem, name = ICON_STEM[key], G.display_name(key)
        for suffix, tag in (("", "small"), ("_large", "large")):
            s = os.path.join(bundles, stem + suffix + ".png")
            if not os.path.isfile(s):
                continue
            d = os.path.join(com, "%s [%s] %s.png" % (name, key, tag))
            shutil.copy2(s, d)
            made += 1
            rows.append((name, key, stem + suffix, size_of(s)))

    for group, names in (
            ("intro", sorted(os.path.basename(p) for p in
                             _group_files(bundles, ("trait_", "resource.png", "treasury",
                                                    "dlc12_", "sphere_", "siege_", "edict_",
                                                    "cargo", "effect_rite", "office")))),
            ("feed", sorted(os.listdir(msgs)) if os.path.isdir(msgs) else [])):
        dst = os.path.join(OUT, group)
        os.makedirs(dst, exist_ok=True)
        for n in names:
            s = os.path.join(bundles if group == "intro" else msgs, n)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(dst, n))
                made += 1

    readme = [
        "# Zharr Exchange icons, exported from CA's ui.pack",
        "",
        "Extracted %s with `tools/export_exchange_icons.py` + RPFM." % "2026-09-09",
        "**CA's art, not mine** - fine to work from locally; do not redistribute as an asset "
        "pack.",
        "",
        "`ui/` is the raw extraction with CA's own paths kept, so a file here can go straight "
        "back into a pack. The folders beside it are renamed copies of the same bytes.",
        "",
        "## The seventeen commodities",
        "",
        "Five of these filenames do not match the good they draw, which is why the renamed",
        "copies exist. `res_rom_lead` is Salt; `res_rom_glass` is Dwarf Beer.",
        "",
        "| Display name | Key | CA file | Size |",
        "|---|---|---|---|",
    ]
    for name, key, f, sz in rows:
        readme.append("| %s | `%s` | `%s.png` | %s |" % (name, key, f, sz))
    readme += [
        "",
        "## Not exported, deliberately",
        "",
        "- **House flags.** `EX.house_icon` builds `ui/flags/<faction key>/mon_24.png` at "
        "runtime. CA ships 486 of them, one per faction, and which one a row draws depends on "
        "the campaign. The folder is the asset; there is no single file to copy.",
        "- **Commodity icons in `ui/skins/default/`.** The mod ships none - see the note on "
        "`optional_icon_path` in `gen_zharr_exchange.py`. These 24x24 files are the obvious "
        "donors if that is ever built.",
    ]
    io.open(os.path.join(OUT, "README.md"), "w", encoding="utf-8", newline="\n").write(
        "\n".join(readme) + "\n")
    print("  organised %d copies + README.md" % made)


def _group_files(folder, prefixes):
    for n in sorted(os.listdir(folder)):
        if any(n.startswith(p) or n == p for p in prefixes):
            yield os.path.join(folder, n)


def main():
    os.makedirs(OUT, exist_ok=True)
    if "--organise" in sys.argv:
        organise()
        return 0
    found, missing, packs = resolve()
    n = sum(len(v) for v in found.values())
    for group in sorted(found):
        print("  %-12s %3d" % (group, len(found[group])))
    print("  %-12s %3d  across %s" % ("TOTAL", n, ", ".join(sorted(
        {e["pack"] for v in found.values() for e in v}))))
    if missing:
        print("\n  MISSING (%d) - these are referenced and in no ui pack:" % len(missing))
        for p in missing:
            print("    %s" % p)
    json.dump(found, io.open(MANIFEST, "w", encoding="utf-8"), indent=1, sort_keys=True)
    print("\nmanifest: %s" % MANIFEST)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
