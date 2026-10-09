# The Grand Trade Exchange

A commodities market and stock exchange for *Total War: WARHAMMER III*, built as a
Chaos Dwarf campaign mod. Written entirely in the game's own extension surface (DB tables,
Lua 5.1 and CA's `.twui.xml` UI layer), with no engine access, no decompiler, and no
official API beyond CA's published script reference. It ships in-game as **the Zharr
Exchange**.

The game ships 17 tradeable resources, every one priced at a flat value of 50, with
no price discovery anywhere. The Exchange is that missing layer: each good gets a
live price driven by what the world actually produces, who owns the production, who
is at war, what the other factions are holding, and what the player has been buying.

What you can do with gold in it:

- Trade the 17 commodities: corner a good and watch your own buying move the price against you.
- Hold a position in a warehouse, for a standing campaign bonus and per-turn rent.
- Burn goods on the altar for a timed buff.
- Buy shares in other factions. They pay a per-turn dividend and settle when the faction dies, at a premium if you were the one who killed it. Which factions you may buy into is set by lore-shaped trading blocs, not by your own culture alone.
- Pay a patron's tithe, or refuse it and take the consequences.
- Take a deal. Each turn a few factions with real money and a real need post an offer: over the market for what they lack, under it for what they are dumping.
- Leave a standing order: buy when a good falls to your price, sell when it rises to it. Twelve can wait at once.
- Sign a contract: a price agreed now for goods delivered turns later. Lots nobody can deliver settle in gold at the gap to the market, and war does not cancel one.
- Buy a fund: the index, one lot of every trading house of your own people paying all their dividends, or a themed fund per race, which is two baskets of goods and one of a friendly people's houses (Chaos Dwarfs back Norsca and the Warriors of Chaos). A house that dies leaves at the wind-up rate.
- Lend and borrow. Houses at war sell you bonds, houses at peace offer you loans; a payment every turn, the whole amount at the end, and real gold on both sides.

And two things that happen whether you trade or not:

- The world trades against itself. Every landholding faction keeps a book and buys and sells each turn, so prices move because the world moved.
- Iron, timber and obsidian are war materiel. A faction outside the trading houses that holds them replenishes its armies faster and one that has sold them short replenishes slower, doubled at war, so selling iron to someone at war arms them.

Full reference: [docs/GRAND_TRADE_EXCHANGE.md](docs/GRAND_TRADE_EXCHANGE.md).

---

## What's here

| | lines |
|---|---:|
| Python (`tools/`, including the sibling mods' generators the Exchange imports) | 45,451 |
| Campaign and settings Lua (`Modding Files/pack/script/`) | 16,454 |
| Lua test harnesses (`tools/_*_harness.lua`, 20 files) | 6,695 |
| UI layouts (`.twui.xml`, 9 files) | 11,656 |
| Generated DB and localisation (TSV) | 7,045 rows |
| Documentation | 301 KB |

The mod itself is 10 DB tables with 1,643 rows, 5,402 localisation strings, the Lua and
the UI.

## What is generated, and what is not

A 4,466-line XML UI file is not something you edit by hand twice. The data half of the mod
is emitted by `tools/gen_zharr_exchange.py`, which owns every price curve, every table row
and every localised string, and generates:

- the 10 DB table fragments and the loc, as TSV
- the MCT settings Lua (a difficulty preset, 37 sliders and 29 switches)
- and, via `gen_exchange_ui.py`, the seven Exchange `.twui.xml` files, with 738 GUIDs all
  allocated and paired by the generator, because a duplicate or mismatched GUID in that
  format is a silent non-draw with no error anywhere

The campaign script, `zzz_derpy_chd_exchange.lua`, is written by hand. Every constant it
shares with the generator is mirrored there, and the selftest fails when the two disagree.
The generated files are committed so the repo is readable without running anything, which
means they can be checked against their source:

```
py tools/gen_zharr_exchange.py             # regenerate the TSVs
py tools/gen_zharr_exchange.py --selftest  # also rewrites the settings Lua and production map
py tools/gen_exchange_ui.py                # regenerate the .twui.xml files
git diff                                   # empty, or the generator and the repo disagree
```

## Testing a mod that has no test framework

Campaign Lua runs inside a closed game. There is no test runner, no assertion library, no
way to import a module, and a runtime error inside a listener is dropped silently, with no
log line. So the checks run outside the game instead.

`--selftest` runs the shipped Lua file itself under a local Lua 5.1.5 against stubbed
campaign interfaces, through the 20 harnesses in `tools/_*_harness.lua`:

```
py tools/gen_zharr_exchange.py --selftest
py tools/gen_exchange_ui.py --selftest
```

It prints 87 groups of checks. Among them:

- every one of the 882 `EX.*` names the script defines is read somewhere, so there are no orphans
- prices agree between the Python model and the Lua that ships
- every view is one click from every other, the page arrows wrap and point the right way, and every view opens on its first page
- every label fits its box: 32 headers measured against their neighbours, footers bounded at 118 characters, the widest price cell 8 of 10 characters
- multiplayer paths route through the right entry points
- the UI generator's 738 GUIDs are unique and hierarchy-paired

## Notes for a reader

**Why the odd folder names.** `Modding Files/pack/...` mirrors the layout inside a built
`.pack` one-for-one, and `tools/` sits beside it because that is how the generators resolve
paths. The tree is kept as-is so the scripts here are the same files that build the live mod,
not a re-pathed copy that drifts.

**Running it locally.** The generators need Python 3 and, for the UI asset check, an
installed copy of the game to resolve icon paths against. They cache those into a gitignored
`.skilltree_cache/`. `import_zharr_exchange.py` also needs
[RPFM](https://github.com/Frodo45127/rpfm) running, since a `.pack` is a binary container
that only RPFM writes. The generator runs above need neither RPFM nor a running game.
Resource Overhaul's commodity icons are not published, so the selftest skips its check that
they exist when it runs in a git clone.

**Some things here are deliberately load-bearing weirdness.** `read_vanilla_loc.py` reads the
game's localisation with RPFM shut, because the format turned out to be zstd behind a `u32`
length prefix with UTF-16LE keys *and* values. `check_lua_undeclared.py` exists because an
undeclared global in Lua is `nil` rather than an error, so a typo'd constant silently disables
a whole branch and `luac -p` passes it. Each of these is a workaround for a specific failure
the project actually hit; [docs/CUSTOM_UI.md](docs/CUSTOM_UI.md) collects the UI ones.

## Layout

```
tools/
  gen_zharr_exchange.py       the generator: all data, all rows, all strings
  gen_exchange_ui.py          emits the seven Exchange .twui.xml files
  preview_exchange.py         renders views to PNG by running the shipped Lua headless
  gen_resource_overhaul.py    the sibling mod's goods list, which the Exchange trades when
                              that mod is installed (with read_vanilla_db.py and
                              survey_resource_map.py, which it imports)
  gen_guilds_ui.py            the sibling Great Guilds' UI generator; the scrolling list
                              reuses its slider parts (with gen_great_guilds.py)
  gen_exchange_diagrams.py    the Workshop diagrams, as generated PNGs
  import_zharr_exchange.py    pushes the generated files into a .pack via RPFM
  import_house_ancillaries.py the RPFM client the importer calls (shared with a sibling mod,
                              kept under its original name so it stays one file, not a fork)
  export_exchange_icons.py    resolves which CA icon each commodity draws
  read_vanilla_cache.py       reads cached vanilla DB tables offline
  read_vanilla_loc.py         reads CA .loc files offline
  read_pack_index.py          lists the contents of any .pack offline
  check_lua_api.py            flags calls CA does not document
  check_lua_undeclared.py     flags globals nothing declares
  _*_harness.lua              20 test harnesses, run under real Lua 5.1
Modding Files/
  pack/                       1:1 mirror of the in-pack layout; the campaign Lua is
                              hand-written, the rest is generated
  source/zharr_exchange/      the generated DB and loc, as TSV
docs/
  GRAND_TRADE_EXCHANGE.md     complete reference for what ships
  CUSTOM_UI.md                building a runtime UI panel in this engine
```

## Licence

Source is MIT; see [LICENSE](LICENSE). No Creative Assembly or Games Workshop
asset is included in this repository; where a layout names an icon by path, that
path points into the player's own game install. Warhammer and Total War belong to
Games Workshop and Creative Assembly respectively. Unofficial, unaffiliated,
non-commercial fan work.
