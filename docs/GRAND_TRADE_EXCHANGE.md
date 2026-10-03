# The Grand Trade Exchange — complete reference

`derpy_zharr_exchange.pack`, which ships in-game as **the Zharr Exchange**. A live
commodities market, a stock exchange in Chaos Dwarf houses, a patron's tithe, a warehouse
and a war-shock model, on a panel of its own.

This is the **reference for what shipped**.

| | |
|---|---|
| Pack | `Modding Files/Modpacks/derpy_zharr_exchange.pack` |
| Size / md5 | 1,733,633 B / `c58588eb` (2026-09-30: contracts, the index, bonds and loans, the logic-sweep fixes, who caused a trade disruption with the located bulletin, the 09-30 fault fixes, the Houses/Deals sub-tabs, the index opening on load, No gold on the index and house Buy, and themed funds on the Funds tab with the listed fund in yellow, member counts and a Listing footer - §12, §11.1, §17, §18; deployed to the Workshop folder and the restore overlay, byte-verified; not yet uploaded - Steam has the 2026-09-27 10:51 build `4d33c778`) |
| Rows | 681 DB across 10 tables, plus 1,776 loc = 2,457 |
| Runtime | `script/campaign/mod/zzz_derpy_chd_exchange.lua`, 15,169 lines, 488 `EX.*` functions (855 `EX.*` names in all, every one read — `check_no_orphans`) |
| Races | 8 covered, of the game's 28 cultures (27 vanilla since game update 9.0 added Nagash's Undead Legions, plus the Southern Realms) |
| Workshop | *Derpy's Grand Trade Exchange*, item 3798516851. In game it is still the Zharr Exchange |
| Hard dependency | none |
| Multiplayer | supported since 2026-09-09, **never run on two machines** — §18 |
| Soft dependencies | MCT (settings), Cataph's Southern Realms (the eighth board; the base game covers the other seven) |

---

## 1. What it is

CA ships 17 tradeable resources, every one of them priced at a flat `trade_value` of 50, with
no price discovery anywhere in the game. The Exchange is that missing layer: each of those 17
goods gets a live price driven by what the world actually produces, who owns the production,
who is at war, what the AI houses are holding and what you yourself have been buying.

You reach it from a button on the campaign HUD. Inside are six views, a guide, and a market
you can trade against every turn.

**Seven things you can do with gold in it:**

1. **Trade the 17 commodities.** Buy low, sell high, or corner a good and watch your own
   buying move the price against you.
2. **Hold a position** in the warehouse: a big enough pile grants a standing campaign bonus,
   and every unit costs rent per turn.
3. **Burn goods on the altar** for a five-turn buff — the offering.
4. **Buy shares in other Chaos Dwarf houses.** They pay a dividend every turn, and settle when
   the house dies — at a premium if *you* were the one who killed it.
5. **Pay the patron's tithe** when it is demanded, or refuse and take the wrath.
6. **Take a deal.** Each turn a few factions outside the guild post a one-turn offer - to buy
   over the market or to sell under it (§12, "The Deals page").
7. **Leave a standing order** on Trade's third page - buy when a good falls to your price,
   sell when it rises to it. Twelve can wait at once.

And one thing that happens to you whether you trade or not: the price of what your own regions
produce drives your vanilla trade income.

Around the panel, since 2026-09-13, the rest of the map trades too: every landholding faction
outside the guild holds a position and trades each turn (§9.1), a faction's net position
in iron, timber and obsidian changes how fast its armies replenish (§10.1), and the
houses' campaign AI is told how your holdings should make it feel about you (§7.4).

---

## 2. What ships

Seventeen files in the pack.

**Ten DB tables plus loc** (`derpy_chd_zharr_exchange` fragment in each):

| Table | Rows | What it carries |
|---|---:|---|
| `pooled_resources` | 17 | `derpy_chd_ex_hold_<good>` — where a position is held |
| `pooled_resource_factor_junctions` | 19 | the `other` factor each pool moves through - 17 of ours plus CA's two layer-2 pools. v3 since game update 9.0, which added `sort_order` (emitted as CA's 0); `table_version()` reads the version from the cached dump, so delete `.skilltree_cache` after a patch or the old version is written again |
| `campaign_group_pooled_resources` | 34 | 17 pools x 2 groups (CHD feature group + `wh_main_feature_all`) |
| `effect_bundles` | 215 | 8 races x (17 offerings + pleased + wrath) = 152, plus 51 warehouse tiers, plus 8 trade-income steps, plus 4 War Stocks position steps (`derpy_chd_ex_pos_neg02` .. `_pos02`) |
| `effect_bundles_to_effects_junctions` | 231 | the above, with each race's two patron bundles carrying two effects each (16 bundles x 2) |
| `campaign_groups` | 40 | 5 event-feed records per race |
| `campaign_group_members` | 40 | " |
| `campaign_group_member_criteria_values` | 40 | " |
| `event_feed_message_events` | 40 | " |
| `building_effects_junction` | 5 | the five Chaos Dwarf resource buildings that produce no trade good in vanilla — see §4.1 |
| `text/db/…loc` | 1,776 | every title, description and bulletin - 197 rows per race, plus 200 shared by all eight (warehouse tiers, holding pools, shocks, delistings, trade-income and War Stocks bundles) |

`building_effects_junction` is the **only** table here that edits a vanilla row's subject rather than minting a key of this mod's own, and so the only one that can collide with another mod: anything else touching those five buildings' effects wins or loses by load order, with no crash and no warning either way.

This pack **mints no effect of its own** — `effects_tables` is gone. Every bundle carries one of
CA's existing effects. The 798-row price ladder that used to dominate `effect_bundles` was
deleted on 2026-09-05 once the price stopped being an effect at all.

**Six loose files:**

```
script/campaign/mod/zzz_derpy_chd_exchange.lua        the whole runtime
script/campaign/mod/zzz_derpy_chd_exchange_prod.lua   789 buildings -> what each produces
script/mct/settings/derpy_chd_zharr_exchange.lua      MCT registration
ui/campaign ui/derpy_chd_exchange_panel.twui.xml      the panel
ui/campaign ui/derpy_chd_exchange_row.twui.xml        one row
ui/campaign ui/derpy_chd_exchange_button.twui.xml     the HUD opener
```

**Dropped 2026-09-09:** `ui/campaign ui/derpy_chd_ex_delta.twui.xml`, a leftover from the
abandoned rites-panel route (a price-change badge drawn into a ritual card) that nothing in the
runtime ever referenced - it had no loc row either, so its tooltip key resolved to nothing.
Its GUID prefix `DE15xxxx` is **retired, not freed**: reusing it against a save that still
carries the old file is a silent non-draw. See `CUSTOM_UI.md`.

---

## 3. The instruments — three layers

### Layer 1: the 17 world commodities

Faction-agnostic, and the main event.

| Key | Name | Key | Name |
|---|---|---|---|
| `res_animals` | Exotic Animals | `res_rom_iron` | Iron |
| `res_dyes` | Dyes | `res_rom_lead` | **Salt** |
| `res_gems` | Gemstones | `res_rom_marble` | Marble |
| `res_gold_idols` | Golden Idols | `res_rom_textiles` | **Pottery** |
| `res_ivory` | Tusks | `res_rom_timber` | Timber |
| `res_medicine` | Medicinal Plants | `res_rom_wine` | Wine |
| `res_obsidian` | Carved Obsidian | `res_spices` | Spices |
| `res_rom_furs` | Furs | `res_trinkets` | Elven Trinkets |
| `res_rom_glass` | **Dwarf Beer** | | |

The four bolded names are the trap: these are Rome-era keys CA repurposed, so stripping the
prefix gives three wrong names and fourteen ugly ones. Names come from
`resources_onscreen_text_<key>` in the loc (`resources_tables` has no name column at all),
icons from `resources_tables.icon_filepath`. Regenerate with `tools/read_vanilla_loc.py`.

A position is held in a pooled resource, `derpy_chd_ex_hold_<short>`, one per good. Lot size 10.

Every Layer 1 trade settles against a real faction - a guild house, a world-tier actor or the
largest producer (§5, "Who is on the other side"). Layer 1 is the only layer that has one:
Armaments and Raw Materials come out of the Forge and a share is paper, which is the rule the
`nobuyer` sell refusal rests on.

### Layer 2: the two Chaos Dwarf pooled resources

`wh3_dlc23_chd_armaments` and `wh3_dlc23_chd_raw_materials`. Priced flat at the neutral rung —
they have no map supply signal to price against. Chaos Dwarf players only; every other race's
`layer2` is empty.

**A lot is 100 units. Buy 1000; sell back at the `l2_sell` fraction of that** — 500 by default,
750 on Easy, 400 on Hard, 250 on Ultra, anything from 0.05 to 0.95 under Custom.

Layer 2 does not pay the ordinary spread. Its base rung is the neutral one in every campaign,
so a 10% round trip on it was a flat toll on what is effectively a locker, with none of the
price movement that makes a spread a cost of trading rather than a fee. Buying the Forge's
output out of the Exchange is a convenience worth full price; dumping it back is a fire sale.

**Layer 2 is not frozen, though, and that is easy to get wrong.** `EX.target_rung` excludes
appetite, shocks and the guild's book from it — but **not** `EX.pressure_shift`. The player's
own buying moves these two rows, and it is the only thing that does. Four net lots is one rung,
so a sell factor above `1 / ladder_step` pays back more than the buy cost with no market risk
whatsoever: the same loop `check_spread` closes for the commodities, on the one pair of rows
where the player controls both ends of it.

`EX.sell_price` therefore clamps the factor to `1 / ladder_step`, the way `EX.friendly_cap`
clamps the friendly discount. It is a `min()` rather than a fixed slider ceiling because
`ladder_step` is itself a knob — a Custom board at 1.30 needs a tighter cap (0.769) than one at
1.02 (0.980), and no single maximum is right for both. No shipped preset comes near it;
`check_layer2_sell()` refuses a preset that would be clamped, because a clamped preset states a
number the game does not charge.

**Labour is deliberately absent.** `wh3_dlc23_chd_labour` is `FACTION_PROVINCE` scope, and a
province-scoped pool is unreachable from script: measured 2026-09-04, both the faction's and the
province's `pooled_resource_manager` return a null interface for it (same for workload and
efficiency). `cm:faction_add_pooled_resource` moved nothing and the row sat at "0 held" with a
dead Buy button.

### Layer 3: house shares

Every living faction **of the player's own culture** is an instrument. Lot size 5 shares.
Discovered once per campaign by walking `faction_list`, excluding the rebels, the three
quest-battle shells and the invasion faction — none of which anyone can buy into or absorb.

**Not Chaos Dwarfs specifically, and this doc said otherwise until 2026-09-09.** `EX.bind_race`
overwrites `EX.HOUSE_CULTURE` with the local player's culture, over the Chaos Dwarf file-scope
default, and the walk actually reads `EX.HOUSE_CULTURES` — the **union across every human**, so
a multiplayer board carries every player's houses on one list. It is a union rather than a
per-player list because `EX.instruments()` is what `EX.restore`, `EX.apply_prices` and
`EX.remember_all` iterate to keep the *world* price tables: fork it per player and two machines
walk different rows, save different rungs, and the market stops being one market. The panel does
the narrowing at draw time, which is where a per-player difference belongs. An Empire player
therefore buys shares in Empire factions, which is what the per-race `div_yield` / `windup` /
`book_per_rung` profiles in §11 were always for.

Holdings are **save state**, not a pooled resource: there is no DB row for a house, so
`cm:faction_add_pooled_resource` would be a silent no-op and the position would vanish on
reload.

**The index fund** (2026-09-29) holds every house of your culture in one lot, and since
2026-09-30 it is the first of each race's **themed funds** - baskets of goods, or of a friendly
people's houses - on the Houses tab's Funds page. See "The Index page" and "Themed funds" in §12.

**War bonds and loans** (2026-09-29): a house of your culture at war with somebody borrows from
you; one at war with nobody lends to you. Real gold both ways, a payment every turn, the whole
amount at the end - see "The Bonds page" in §12.

---

## 4. The price model

Every instrument sits on one shared **42-rung geometric ladder**. Rung 25 is neutral and costs
`BASE_COST` = 1000 gold a lot. Each rung is `LADDER_STEP` (1.10 by default) from its neighbour,
so the floor is rung 1 at ~102 gold and the ceiling rung 42 at ~5,054.

```
price_at(rung) = 1000 * LADDER_STEP ^ (rung - 25)
```

### 4.1 Where the base rung comes from

**For a commodity** — from supply, and supply is *production*, not region count:

```
raw supply      = units the whole map produces per turn      (region deposits + buildings)
hhi             = sum over owners of (their share) ^ 2       Herfindahl concentration
effective       = raw / (1 + CONCENTRATION_K * hhi)          K = 10
multiplier      = (median effective / this effective) ^ 0.7  clamped to [0.10, 5.00]
base rung       = ladder_index(multiplier)
```

The concentration term is the cartel premium: a good produced in quantity but by one faction
prices as if it were scarce. The exponent softens the curve — 1.0 would be strictly inverse.

`zzz_derpy_chd_exchange_prod.lua` is the production map, 789 buildings and what each makes per
turn, generated by `gen_zharr_exchange.write_production_lua`. It is a separate file because it
is data, and read lazily because mod scripts autoload in no set order.

**Map and settlement mods are covered by the walk; their buildings are not.** `EX.scan_supply`
walks the live `region_manager():region_list()` every turn, so a region added by IEE, an Old
World map or any other campaign mod is scanned exactly like a vanilla one - owner, culture, war
state, deposits and slots. The two supply halves then come out unequal:

- **Deposits work everywhere.** `region:resource_exists(res)` is a live engine call against CA's
  own 17 keys, so a modded settlement carrying a vanilla deposit contributes its
  `LATENT_PER_REGION` unit and counts toward its owner's concentration.
- **A modded building contributes nothing.** `EX_PRODUCTION` is keyed by building name and
  generated from *vanilla* `building_effects_junction` on the build machine, so a key this mod
  has never seen falls through `prod[slot:building():name()]` and is **ignored in silence** -
  the same branch that deliberately swallows `res_gold` and the pasture buildings. There is no
  warning, and unlike `EX.warn_uncovered` for cultures there should not be one: an unmapped
  building is the ordinary case, not a fault.

So a settlement mod reusing CA's resource buildings prices correctly, and one minting its own
producers reads as a region with a deposit and nothing built on it. Covering the second is a
data edit to the production map, not code.

Three things take a region out of supply entirely: it is **abandoned**, it is **razed**, or it
is **under siege**. Nothing leaves a settlement with an army camped outside it.

### 4.1 The five Chaos Dwarf deposits that produced nothing

CA gives the Chaos Dwarfs **five single-rung resource buildings** — gems, iron, timber, marble
and obsidian — that feed the Hell-Forge's Armaments and Raw Materials instead of granting a
tradeable good. Every other Chaos Dwarf resource building climbs a 20 / 30 / 45 ladder across
three tiers; these have no tier 2 or 3 to grow into and grant nothing to trade at all.

That left four of seventeen commodities blind to the only faction that can open this panel, so
the supply scan **priced a surplus that did not exist**: `CHD_PRODUCTION_EXTRA` added ten units
per building to the production map and nothing in the campaign backed it. A Chaos Dwarf iron
mine moved the iron price on the panel while the trade screen showed nothing and no other
faction could buy a bar of it.

**Since 2026-09-09 the pack makes it true**, in five `building_effects_junction` rows:

| Building | Cost | Grants | Also carries |
|---|---:|---:|---|
| `..._gems_1` | 0 | **10** gems | nothing at all — zero rows in the whole table |
| `..._iron_1` | 0 | **10** iron | armaments modifier +15% |
| `..._timber_1` | 0 | **10** timber | armaments modifier +15% |
| `..._marble_1` | 5,000 | **15** marble | raw-material efficiency +15%, +500 raw materials, +400 workload |
| `..._obsidian_1` | 5,000 | **15** obsidian | the same four |

**The values are priced off build cost, not picked.** Ten is `CHD_SURPLUS`, half of vanilla's
tier-1 rate, for the three that are free; fifteen for the two that cost a tier-3 price and pay
the Forge as well. All five are far under the 45 a tier 3 grants. The Hell-Forge still keeps
most of the output — only the surplus reaches the market, which is what the production map
always claimed.

**`CHD_TRADE_GRANT` is the single source of truth.** `build()` writes the DB rows from it and
`production_map()` prices from it, so the panel cannot quote a supply the campaign does not
have. `check_chd_trade_resources()` proves the two agree, that every effect key and scope is
attested in a vanilla row, and that nothing exceeds the tier-3 rate.

Two traps worth keeping:

- **The gems stem is SINGULAR** — `wh_main_effect_region_resource_gem_production`. Effect keys
  are unvalidated strings, so the plural would load cleanly and grant nothing forever. That
  exact plural already lost `gems_1` from the deposit survey once.
- **`building_to_building_own` is the only scope that means "produced here".** The thirteen
  rows in the game using another one change production in *other* regions — a different
  mechanic wearing the same effect name.

**For a house** — from power, on a median over houses only:

```
power       = regions held, or (military forces x 2) for a horde that never had a home region
multiplier  = (power / median power) ^ 0.7                   clamped to [0.10, 5.00]
if it has lost its capital:  multiplier x= SEAT_LOST (0.6)
```

Houses and commodities are priced on different quantities and share only the ladder, so the
medians are separate.

**For layer 2** — the neutral rung, flat.

### 4.2 The six shifts

The base rung is then moved by five independent terms, summed and clamped to [1, 42]:

| Shift | Source | Cap |
|---|---|---|
| **Pressure** | your own net lots bought, `PRESSURE_PER_RUNG` = 4 per rung | +/-6 (`PRESSURE_MAX` 24) |
| **Appetite** | world culture demand + war, see §9 | +/-`AI_MAX_RUNGS` = 2 |
| **Shock** | sacks, razes, sieges and raids, see §8 | +/-`SHOCK_MAX` = 6 |
| **Book** | what the AI houses are holding, `BOOK_PER_RUNG` = 30 lots a step | +/-`BOOK_MAX` = 2 |
| **World book** | every other landholder's net position (§9.1), `world_gain` (4.0) x net lots / 100 - 25 net lots a step at default | +/-`AI_MAX_RUNGS` = 2, clamped on its own |
| — | a delisted house freezes instead: its rung never moves again | — |

Every one of these truncates **toward zero**, never `math.floor` — flooring a signed value would
move a price *down* on a demand too small to move it up, and Lua 5.1 stringifies `-0`.

**`AI_MAX_RUNGS` clamps two terms, each on its own** - appetite and the world book, with no
shared budget - so the AI half's combined reach on one price is double what one term gives:
+46% / -32% at default (1.10 ladder, 2 steps each), +17% / -14% on easy, +108% / -52% on hard,
+423% / -81% on ultra, with both terms pinned the same way. A separate world-tier clamp was
considered and rejected: the tier has its own off switch (`ai_world`, which zeroes the term), and
a number nobody has measured does not earn another settings place.

The world book term is a second term rather than a change to `EX.book_shift`, whose 30-lot
calibration against the guild is what holds the measured spread floor. What moves it is narrow -
see §9.1, "What moves the world book's price, and what does not".

### 4.3 What you actually pay

```
buy  = price * (1 + hostility)
sell = price * max(1 - spread - hostility, sell_floor)

layer 2 only:  sell = price * min(l2_sell, 1 / ladder_step)
```

The layer-2 branch sits at the top of `EX.sell_price`. `EX.hostility` already returns 0 for
layer 2 so the order changes nothing today; it is written that way so a later task giving the
guild a stance on the Forge's output cannot stack a markup on a fire sale that is already
discounted. The `min()` is the round-trip rail — see §3, Layer 2.

`hostility` is the guild's stance as a signed factor: positive is a markup from houses that
despise you, negative a discount from houses that like you (reachable since 2026-09-30 - see below). The two halves are asymmetric on
purpose — hostility runs to `HOSTILE_MAX` (0.25) because charging more can never mint gold,
while the discount is bounded by

```
friendly_cap = (1 - LADDER_STEP * (1 - spread)) / (1 + LADDER_STEP)
```

because a discount **can**. At the default spread of 0.10 and step 1.10 that headroom is 0.48%
(measured by the books harness: a 1000 lot buys at 996 and sells at 904 against 900), so the
*Friendly discount limit* slider does little until the spread is raised - at a 0.25 spread the
same house gives 8%.

This is the round-trip algebra `check_spread()` guards, and it is why `spread`, `ladder_step`,
`sell_floor` and `friendly_max` are the four knobs a race profile is **forbidden** to touch.
The `easy` preset minted gold for months on a four per cent spread against a 1.08 step: selling
one rung up paid 1.0368x what you bought at, with no friendly discount involved at all.

**The discount half fires since 2026-09-30** (found unreachable 2026-09-23). `EX.stance_of`
answers -1..1:

| House | Stance |
|---|---|
| at war with you | -1 |
| ally, vassal or trade partner, treaties actually read | +1 |
| `EX.treaty_tier` could not read its treaties (the `"free"` fallback) | 0 |
| no treaty, standing above 0 | standing / the highest such standing in the guild (`EX.best_standing`) |
| no treaty, standing exactly 0 | 0 |
| no treaty, standing below 0 | ranked against the deepest negative, a pact capping it (unchanged) |

`EX.treaty_tier` returns a second value, `true`, only when it read the treaties - that is how
`stance_of` tells a real ally from the fallback it uses so our own failure never charges the
player. Every other reader of `stance_of` acts on its negative side only (front-run, refusal,
the Houses footer's hostile list), so the positive half changes nothing but `EX.hostility`.
`EX.best_standing` is memoised in `EX.hold_guild` beside `deepest`; without it the hold's own
construction walked the guild once per friendly house (896 `cm:get_faction` calls at 14 houses
against 168).

**The sentences speak on the realised percent**, `EX.markup_pct(...) > 0`, not on `h ~= 0`: the
Buy and Sell tooltips and the Log's trade note. Under the default cap the Buy side rounds to 0%
and says nothing, while the Sell side rounds to 1% (904 against 900) and says so.

**The house a markup is blamed on is `EX.hostility_source(res)`**: the holder with the largest
`book x -stance`, houses at war with you included, which are the same terms `EX.hostility` sums.
Three sentences read it: the Buy tooltip ("X holds this and dislikes you: +N%."), the Sell
tooltip ("... pays you N% less.") and the Log's trade line ("X dislikes you: N% more.").
Until 2026-09-23 they named `EX.guild_counterparty`, the house you buy FROM, which skips houses
at war. So the biggest peaceful holder took the blame for other houses' dislike: the Warhost of
Zharr "disliked" a player at +85, a standing `EX.stance_of` then scored 0. The fill still pays the
counterparty; only the sentence changed. `check_lua_books` pins it (`source_named`; since
2026-09-30 the warring house1 holds more than house2, because a +85 house2 is now a real friend
and with the old books the board was a discount). **A discount is credited the same way**: when
the sum is negative, the holder with the most negative `book x -stance` (`friendly_source`).

---

## 5. Trading

`EX.apply_trade_held(res, is_buy, ...)` - reached from `EX.trade` (the network sender) through the `buy`/`sell` op, `EX.bulk_trade` and the `EX.apply_trade` wrapper - and it is **two calls and nothing else**:

```lua
cm:treasury_mod(faction, is_buy and -price or price)
cm:faction_add_pooled_resource(faction, pool, "other", is_buy and lot or -lot)
```

It does **not** call `cm:perform_ritual`. Measured in game 2026-09-04: `perform_ritual` applies
the ritual's pooled side but never charges the treasury — gold went 4900 to 4900 across a 621
trade while the goods moved the full 10. `cm:treasury_mod` does take a negative, despite the
design doc's claim that CA restricts it to positive values.

The factor argument must be the `pooled_resource_factors` **key** (`"other"`), not our
`pooled_resource_factor_junctions` unique id. Passing the junction id succeeds and moves nothing
at all, with no error.

**Seven ways a buy is refused**, each with the reason on the button, in its tooltip and in the log:

| | |
|---|---|
| Nothing on the map produces it | `EX.unavailable` — the rung is already clamped at 42, so a buy would be a no-op dressed as a trade. Measured: 10 bought and 10 sold back is exactly break-even. Selling stays open. |
| A house refuses | it holds >= `REFUSE_SHARE` (0.50) of the book, is in the bottom `REFUSE_RANK` of the stance spread, and you are at open treaty |
| The market is shut | >= `GUILD_CLOSE` (0.60) of the guild's book is at war with you |
| A house is at war | you cannot buy its own paper while fighting it |
| The house is delisted or dead | see §7.3 |
| The pool is not registered on your faction | charging for it would take the gold and grant nothing |
| Nobody is holding any ("Sold out") | `EX.sold_out`, only with `world_scarcity` **and** `ai_world` on: the guild holds none of it, the world tier could supply it (`EX.world_potential` > 0) and no actor can right now (`EX.world_supply` = 0). Names the largest producer. Tested last, because it is the weakest claim. Off on easy; on at default, hard and ultra |

Selling is open against all seven. A house that despises you is delighted to take your goods
cheap, and blocking a sale traps the player's capital with no exit - the lockout that actually
hurts. The one sell refusal is not about anybody's mood: a Layer 1 sale that no faction on the
map can pay for is refused (`nobuyer`) rather than minting the price out of nothing - see "Who is
on the other side" below.

**Sell greys for one reason only: holding less than one lot** (`EX.draw_sell`, on Trade and
Houses rows, since 2026-09-25). That is the one sell `EX.apply_trade` refuses (`nothold`).
Before, the button stayed live and the click did nothing on screen. A war, a closed market or a
hostile house never greys it. Its tooltip is `EX.TIP_SELL`, or `EX.TIP_SELL_NONE` ("You hold
less than one lot of this.") while greyed.

**The two refusals `EX.apply_trade` does not log itself now reach the Log**: `afford` and
`nothold`, worded by `EX.TRADE_STOP` and written by `EX.log_bulk` as "Buy refused. Not enough
gold." and "Sell refused. You hold less than one lot." Both used to reach the script log only.

**What one click costs.** Since 2026-09-23, `EX.apply_trade` is a wrapper: `EX.hold_guild()`,
then `pcall(EX.apply_trade_held, ...)`, then `EX.free_guild()`, then the error re-raised.
Holding one stance vector for the whole trade stops `EX.blocked`, `EX.buy_price` and the Log
line each walking the guild once per holder. That walk cost 2,896 `cm:get_faction` calls a lot
at the 105 houses of a live save, about 0.6s before "bought".

The reprice 0.1s later had the second walk: `EX.target_rung` took the house median once per
house. `EX.apply_prices` now computes `EX.house_median()` once and passes it as the optional
fifth argument `hmed`, which took the reprice from 11,130 power reads to one pass. A caller that
omits it still gets the live read, so keep passing it. `check_lua_books` fails if a 40-house
reprice makes more than 80 power reads. Confirmed live the same day: click, "bought" and
"repriced" arrived inside 0.1s on a 227-instrument board, where they had taken about 1.8s.

The same hold now covers `EX.layout` (a wrapper over `EX.layout_held`) and each player's pass
of `EX.post_all_deals`. Layout sorts the list, and the Buy and Sell sort keys are
`EX.buy_price` / `EX.sell_price`, so an unheld header click walked the guild once per row:
measured live 2026-10-03, 4.06s per click at 148 houses, against 0.27s for the held refresh.
The deals page prices every candidate the same way, the likeliest cause of a 70-80s pause
after the last faction's turn. The selftest counts the walks both save.

### Who is on the other side

Every commodity trade settles against a real faction through
`EX.settle_counterparty(res, is_buy, price, only)`, and `EX.apply_trade` consults it **before**
the player's own `cm:treasury_mod`, because a treasury move cannot be taken back. Three steps, in
order:

| Step | Who | On your buy (they sell) | On your sell (they buy) | Declines when |
|---|---|---|---|---|
| 1. Guild | `EX.guild_counterparty` - a house not at war with you | the house with the largest book in the good | the richest house | price > `house_cash_max` (with `ai_gold` on) |
| 2. World | `EX.world_counterparty` - a non-human actor, only with `ai_world` on | the actor with the most to sell (`EX.world_sellable`) | the actor with the largest scanned treasury | price > `world_cash_max` (with `ai_gold` on) |
| 3. Land | `EX.top_holder(res, you)` - the largest producer that is not you | paid the full price | pays out of its treasury, capped at what it has | you are the only producer, or its treasury is empty |

Steps 1 and 2 move the counterparty's book by one lot; step 3 moves only gold. The two declines
are tested against the price before anything is paid: the player's leg is never capped, so a
flat cap tighter than the price minted gold on a sell and destroyed it on a buy - and the ladder
passes `world_cash_max` around step 37 of 42 at default. A declined step falls through to the
next. With a guild in the game, step 1 takes almost every sell (it needs only one house with
gold), so step 2 is mostly reached by buys.

**`only` names the counterparty and skips the walk** - the Deals page's route. With it the guild
step is skipped and there is no fallback: if the named faction cannot settle, the answer is nil,
never somebody else. A panel that names one faction and pays another is the same lie as a quoted
price that is not the price charged.

**A sell nobody can pay for is refused** (`nobuyer`), and only for a commodity. Layer 2 and house
paper have no counterparty by construction, and refusing them here once took every Layer 2 sale
out of the game. A **buy** with no counterparty is not refused - it destroys gold rather than
minting it - and step 3 skips the player, so cornering a good never traps the position: the
sale goes to the second-largest producer. Before 2026-09-13 the player was credited before
settlement was asked, and a sell into nothing minted the whole price.

---

## 6. The warehouse

One lever pointed both ways.

**Rent.** `CARRY_PER_UNIT` = 0.5 gold per unit held per turn, flat — not a percentage of the
position's value. A warehouse charges by the crate: slaves to haul it, guards to watch it, a
roof over it.

```
800 timber    (~20g/unit)   -> 400g/turn = 2.5%  of the position per turn
800 gemstones (~500g/unit)  -> 400g/turn = 0.1%  of the position per turn
```

Hoarding bulk is ruinous, hoarding dense wealth is cheap, out of one constant and with no
per-commodity table. This is what stops "do nothing and wait" being free.

**The ramp.** `STOCK_TIERS` = 100 / 300 / 600 units held grants that commodity's boon at 1x /
2x / 3x. A cliff at one threshold was rejected: selling one lot out of a 100-unit position
would silently kill the bonus, and losing a buff for selling 10 units reads as a bug the first
time it happens.

Tier 2 grants exactly what *burning* the goods on the altar grants. The comparison is
deliberate: the altar destroys 30 units for a five-turn buff, the warehouse ties up 300 for as
long as you keep paying the carry.

**The boons**, one per commodity:

| Good | Grants | Good | Grants |
|---|---|---|---|
| Iron | +4 armour, all armies | Golden Idols | +2 hero capacity |
| Carved Obsidian | +10 winds of magic reserve | Tusks | +4 research points |
| Marble, Timber | -6% construction cost | Exotic Animals | +10% Labour per battle * |
| Wine, Spices, Dwarf Beer | +4 public order | Medicinal Plants, Salt | +6% replenishment |
| Gemstones, Dyes, Elven Trinkets | +6% trade tariffs | Furs | +6% movement range |
| | | Pottery | -6% recruit cost |

\* Chaos Dwarfs only. The other seven races have no Labour pool, so `boon_over` swaps Exotic
Animals to +4 public order for them — otherwise the bundle applies, the effect moves nothing,
and the panel advertises a number that never arrives.

**The Held cell says how far the next level is** (`EX.hold_tip`, 2026-09-25). Each Trade row's
`row_hold` carries its own tooltip under the column's. The body is one of "No stockpile bonus
yet: N more for level 1 of 3.", "Stockpile bonus, level N of 3. M more for level N+1." or
"Stockpile bonus, level 3 of 3: the most there is." It goes on with "Level 2 grants <boon>."
and, only while rent is charged, "Rent Ng a turn." Level 2 is quoted and no other level,
because it is exactly what an offering grants (`OFFER_MULT` 2). Layer 2 rows and houses get the
column tooltip alone. The rent clause follows `EX.charge_carry`'s own switch
(`warehouse_rent`), and the rest of the panel does not - see §17.

**Rent is in the Log.** `EX.charge_carry` writes one line a turn, subject "Rent": "Warehouse
rent: -Ng." The engine files a scripted `cm:treasury_mod` as a one-off outcome, so the treasury
breakdown never shows the charge, and the Log is the one place last turn's bill can be read back.

---

## 7. The three long games

### 7.1 Offerings

Burn `OFFER_COST` units of a good on the altar, get its boon at 2x for `OFFER_TURNS` = 5 turns.
One offering per commodity at a time; the countdown is the engine's own, via
`cm:apply_effect_bundle(key, faction, turns)`.

The price escalates: `30 * 1.05 ^ (offerings made)`, capped at 5x. It counts **voluntary**
offerings only — a tithe does not raise it.

Offering #1 costs **31, not 32**, and that is not a rounding bug. WH3's Lua numbers are
single-precision: `OFFER_STEP` reads back in game as 1.0499999523163, so `30 * 1.05` is
31.4999985 and the `+0.5` falls the other way. Measured, not reasoned about. Do not "fix" it by
rounding differently — the price shown and the price charged both come from that one function,
so they agree whatever the float does.

**The Offerings row decides its own button on every draw** (`EX.offer_cells`, 2026-09-25). The
row component is the Trade view's, one per commodity, so any state this view does not write is
the last view's. That is how a war lock, greying every Buy on Trade, greyed every Sacrifice
with it and shut the altar for the length of a war. `EX.offer_cells` returns exactly one of a
tooltip (`tip`) or a reason (`why`), and `why` greys the button through `EX.set_off`:

| State | Status | Button | Greyed, and the tooltip |
|---|---|---|---|
| Can offer | Ready | Sacrifice | no - "Burn N <good> on the altar." and the favour it buys |
| Offering running | N turns left | Active | yes - "This offering's favour is still running." |
| Too few held | Need N | Insufficient | yes - what it takes and what you hold |
| Tithe pending on this good | Due: N turns, or Need N | Pay tithe, or Insufficient | only when short - see §7.2 |
| Armaments, Raw Materials | - | - | yes - "<patron> has no use for these." |

Keep the one-of rule. A row that writes both, or neither, inherits the other view's state.
Each offering writes a Log line under the good: "Offered N to <patron>. Favour for 5 turns;
the next offering takes M."

### 7.2 The patron's tithe

From turn `DEMAND_FIRST_TURN` (15), on a `DEMAND_COOLDOWN` (15) cycle, at `DEMAND_CHANCE`
(30%) per turn, the patron names one of your three biggest hoards and asks for it.

| Tier | Units | Boon turns | Wrath turns | Weight |
|---|---:|---:|---:|---:|
| tithe | 30 | 6 | 4 | 55 |
| hunger | 90 | 12 | 8 | 32 |
| wrath | 180 | 24 | 15 | 13 |

The amounts are 1x / 3x / 6x the base offering cost — a tithe is exactly what you would have
given freely. Only commodities you can actually pay out of are ever named.

Pay from the demanded good's own row on the Offerings view: its button reads **Pay tithe** while the
demand is pending, and the click pays the tithe's amount, ignoring the ordinary offering price and
the cooldown (see below). Paying grants the commodity's boon **plus**
`<patron>_pleased`: +3 public order and +5 leadership. Refusing — or letting `DEMAND_GRACE` = 3
turns lapse — applies `<patron>_wrath`.

**A pending tithe owns its row** (2026-09-25). Until then the demanded good drew as an ordinary
offering - "Ready / Sacrifice" at 30 held against a tithe of 90 - while the click went to
`EX.pay_demand` and failed into the script log. The row now shows the tithe's amount as Cost.
With enough held, Status reads "Due: N turns" beside a live **Pay tithe** button, whose tooltip
is "Pay the tithe: N <good>." and the favour it buys. With too little, Status reads "Need N"
beside a greyed Insufficient, whose tooltip names the wrath's length. While a tithe is pending,
Offerings footer line 2 drops the warehouse note for "<patron> demands N <good> within N turns.
Unpaid, the wrath lasts N turns." The HUD opener's tooltip carries the same demand (§12).

**"Turns left" counts the current turn.** `EX.check_demand` lands the wrath at the START of turn
`demand_due`, so `demand_due - turn` is the number of turns still payable, and 1 means this one.
`EX.tithe()` floors it at 1.

**The Log keeps the demand and its answer**, under the good:

- `EX.fire_demand` writes "<patron> demands N, within 3 turns. Pay it on the Offerings tab."
- `EX.pay_demand` writes "Tithe paid: N to <patron>. Favour for T turns."
- `EX.check_demand` writes "Tithe unpaid. <patron>'s wrath for W turns."

The event feed says it once. The Log is where it can be read back three turns later.

**It is an event-feed message, not a dilemma.** A `DilemmaChoiceMadeEvent` listener that matches
a custom dilemma hard-crashes the game and bricks the save. `cm:show_message_event`'s last
argument indexes `event_feed_message_events`, which resolves through all four `campaign_group*`
tables; a record missing any one of them draws nothing at all.

Feed indices are per race so a Skaven player is not shown the Chaos Dwarf forge on a Trade
Disrupted bulletin — the picture is a column on the record and nothing can swap it at runtime:

```
""    7401-7405      emp_  7411-7415      cth_  7421-7425
skv_  7431-7435      teb_  7441-7445      dwf_  7451-7455
hef_  7461-7465      def_  7471-7475
                     slots: call, wrath, shock, delist, shockat
```

`shockat` (2026-09-30) is the shock bulletin with a place: a
`scripted_transient_located_event` record for `cm:show_message_event_located`, which resolves
only against a `_located_` type - against the plain `shock` record it would log success and draw
nothing. Same text, same picture; see §8.2.

### 7.3 Shares, dividends and delisting

`DIV_YIELD` = 2% of the share's **own live price**, per share, per turn:

```lua
dividend(house) = floor(price(house) * div_yield / HOUSE_LOT_SIZE)
```

The `/ HOUSE_LOT_SIZE` is load-bearing. `EX.price` is the price of a *lot*, and one lot is five
shares; taking the yield off the whole lot price and then multiplying by every share held paid
it five times over. Measured on the harness: 100 shares cost 20,000 and paid 2,000 a turn — 10%
of the position per turn, which beats the 10% round-trip spread after **one** turn instead of
five. Park the treasury in the cheapest house, collect risk-free.

The dividend can floor to zero and that is the right answer: a house at the ladder floor has
collapsed to a tenth of neutral, and rounding it up to a gold a share would pay the player to
hold losers.

**War suspends the dividend entirely** — done in `EX.dividend` rather than in the total, so the
Div column, the footer and the payment all read the same zero. The position is not confiscated;
selling stays open and peace resumes the income.

**Settlement.** When a house dies its paper settles once and the row freezes at its last living
price:

| Branch | Multiplier | When |
|---|---:|---|
| Buyout | `BUYOUT_PREMIUM` 1.25 | you took its capital — including by Tower of Zharr seat claim |
| Wind-up | `WINDUP` 0.5 | somebody else destroyed it. You backed a loser. |

Two ordering rules make the payout worth what the house was:

- `EX.check_delistings` runs **before** `EX.apply_prices` at turn start. A dead house owns
  nothing, so a live reprice reads power 0 and drops the row to rung 1 in one step. Measured on
  a house at 8 regions: alive 621, repriced 102 — a 40-share position that cost ~24,840 would
  have paid 5,100 instead of 31,050.
- `EX.absorbed_by_us` asks the **region**, not the faction, using a capital key cached while the
  house was alive. `cm:get_faction` answers `false` for a confederated house, so a version that
  reads `home_region()` off the dead faction can never return true down the confederation path —
  which is exactly how a seat claim kills one. The headline hook would have paid the wind-up
  price every time, silently.

`EX.trade` also refuses any house that is dead-but-not-yet-settled. Kill a house during your own
turn and it stays `is_delisted == false` until you end it, while its price still reads the last
living one: buy every lot the treasury can carry, end turn, collect 25%. Repeatable per house
killed, and it inverts the hook exactly.

**A stake also warms the house.** Every `STANCE_SHARES` (25) shares you hold in a house is a step
toward it being told to feel `FRIENDLY`, then `VERY_FRIENDLY`, toward you; hoarding the goods it
produces pulls the other way. See §7.4.

### 7.4 The houses notice your book - the AI stance hook

Not a fourth long game: a consequence of two of them. `EX.promote_stances`, turn step 15b, is the
one wire from the market into CA's campaign AI.
`cm:cai_strategic_stance_manager_promote_specified_stance_towards_target_faction` makes a
strategic stance "much more likely" (CA's words), and a stance reaches war targeting and deal
generation - parts of the AI no DB row and no other script call can touch. There is no "AI,
consider a trade" hook; `EX.step_books` and `EX.step_world` remain the only things that move a
book. What the AI can be told is how to feel.

**The score is market state and nothing else** - `EX.stance_score(house, mine)`:

    n    = shares you hold in the house / STANCE_SHARES (25)
         - sum, over goods the house produces, of units you hold / STANCE_CORNER (150)
    step = n truncated toward zero, clamped to -2..+2

| Step | Promoted stance |
|---:|---|
| +2 | `CAI_STRATEGIC_STANCE_VERY_FRIENDLY` |
| +1 | `CAI_STRATEGIC_STANCE_FRIENDLY` |
| 0 | none - cleared only |
| -1 | `CAI_STRATEGIC_STANCE_UNFRIENDLY` |
| -2 | `CAI_STRATEGIC_STANCE_VERY_UNFRIENDLY` |

`BEST_FRIENDS` and `BITTER_ENEMIES` are deliberately unused: a commodity position colours a
relationship, it does not force an alliance or a blood feud. "Produces" is
`EX.owners[res][house] > 0` - the same table the prices come from - so a pile of gems means
nothing to a house with no gem output. 25 shares is five lots; 150 units sits just above the
first `STOCK_TIERS` step. Both numbers are guesses.

**`EX.stance_of` must never be an input**, and `check_lua_books` greps `EX.stance_score`'s body
for `stance_of`, `standing_of`, `treaty_tier` and `at_war` to keep it out. `standing_of` reads
`diplomatic_standing_with(player)`, which is the number a promoted stance goes on to move: fed
back in, every house walks itself to `VERY_UNFRIENDLY` within a few turns and the market stops
mattering after the first. The inputs are your shares and your warehouse, which the AI cannot
move. This is also not the markup's stance - `EX.hostility` (§4.3) reads diplomatic
standing; this writes the CAI stance, and the two are independent.

**Clear, then promote, every turn, no memo** - the `EX.apply_trade_income` idiom. For every human
(bound through `EX.with_player`) and every house in `EX.guild()`, the pair's promotions are
cleared and a non-zero step is promoted, each pair in its own `pcall`. Both calls take faction
**key strings**. `EX.held` is read once per commodity before the house loop, not once per house.

**`cai_strategic_stance_manager_clear_all_promotions_between_factions` is not mod-scoped.** It
removes any scripted promotion between that house and that player - a CA narrative script's or
another mod's - every turn, for every house, step zero included. That is what the `ai_stance`
switch ("Houses react to your holdings", Systems, on in every preset) is for, and why off makes
**zero** engine calls rather than clearing without promoting. The cost of that: switched off,
whatever was promoted last is left standing, because nothing clears it.

The guild is not fourteen houses once trading blocs are on - a 2026-09-23 save listed 105 - and
the hook reaches every one of them: two engine calls per house, per human, per turn.

**The only trace is a log line**, `N house(s) warmer, M colder on your book`, in the `house`
debug category (off by default), printed when any score is non-zero. No panel element shows a
stance. Seen in play 2026-09-17 ("0 house(s) warmer, 2 colder"); what the AI then did with it
has not been observed.

---

## 8. War shocks

A settlement is sacked, razed, looted, raided, captured or rises in revolt; that region's share
of world supply comes off the market and the price of what it made spikes.

```
rungs = SHOCK_GAIN (10) * (region's share of world supply) * kind weight
```

| Kind | Weight | Event |
|---|---:|---|
| razed | 3.0 | `CharacterRazedSettlement` |
| sacked | 2.0 | `CharacterSackedSettlement` |
| rebels | 1.5 | `RegionRebels` — a province in revolt ships nothing while it fights itself |
| looted | 1.0 | `CharacterLootedSettlement` |
| raided | 1.0 | `ForceAdoptsStance`, three raiding stances |
| captured | 0.5 | `GarrisonOccupiedEvent` and `CharacterCapturedSettlementUnopposed` |

`rebels` and `captured` were added 2026-09-09, and the event names cost more checking than the
weights did. **`FactionDestroyed` and `DeclaredWar` do not exist** — both were in the design and
neither is in CA's event index, and an event name that does not exist never fires and never
errors. `RegionRebels` carries `region()` directly rather than a garrison, unlike the other
three.

**The opposed capture listened for an event that does not exist, until 2026-09-30.** It was
`CharacterCapturedSettlement`, which is in neither CA's docs nor any of CA's 7,540 scripts, so a
settlement taken by assault never moved a price - only one walked into unopposed did (329
captures logged across 1,573 play sessions, against 652 sacks and 376 razes). The docs check
passed it because it matched as a *substring* of `CharacterCapturedSettlementUnopposed`; it now
matches whole words, and proves it on that pair. `GarrisonOccupiedEvent` replaces it. It was
refused earlier as having "no documented accessor", which was wrong: `scripting_doc.html` lists
`garrison_residence()` and `character()` on it, CA's scripts read both 31 times, and CA's XP
script uses it for "general captures and occupies a settlement", apart from its raze and sack
listeners. If it and the unopposed event both fire for one capture, the per-turn guard is keyed
by region *and* kind, and the share counts once.

Capped at `SHOCK_MAX` = 6 rungs (1.77x — a spike, not a new price level), decaying by
`SHOCK_DECAY` = 0.5 each turn and dropped below 0.05. Gone in about three turns.

`BLOCKADE` is deliberately absent from the raid stances: it is a *situational* stance, never
adopted through `ForceAdoptsStance`, so the listener would never fire.

The per-turn duplicate guard is **persisted**. A guard a reload empties is a guard with a hole
in it: the whole point is that a region is disrupted once, and a mid-turn save and load would
let the next event count it a second time. Raiding the same region again next turn is a second
event; raiding it twice in one turn is one event counted twice.

### 8.1 Demand shocks, taken from the scan rather than from an event

**Every kind above is positive** — supply leaves the market and the price rises. Until
2026-09-09 that was the whole shock model, so the board could spike and never crater, which made
a protective sell-stop an order against a thing that could not happen.

`EX.share_shocks` supplies the other sign, and needs no listener at all. `EX.rescan` already
measures every culture's share of the world's regions every turn, so a share **collapsing** is
the event. One mechanism then catches every cause of it — destroyed, conquered, confederated, or
simply ground down — with no listener firing for every faction in the world and no event name to
get silently wrong.

```lua
bump_shock(res, SHOCK_GAIN * delta_share * CULTURE_WANTS[c][res])
```

That product carries both signs from one line. A culture that **wanted** a good disappearing is
demand leaving and the price falls; one that **supplied** it (a negative want) disappearing is
supply leaving and the price rises; a culture growing gives both mirrored. The threshold is
`SHARE_SHOCK_MIN` = 1% of the world's regions, the same figure `EX.warn_uncovered` uses.

Two guards, both measured rather than reasoned:

- **A culture with no previous entry is skipped**, never read as growing from zero — otherwise
  the first scan of a campaign sees every culture on the map as having just appeared and shocks
  all seventeen commodities at once, on turn one, in every game.
- **The first comparison after any load shocks nothing.** `EX.init` runs its own `EX.rescan`, so
  the first turn round compares an *init-time* scan against a turn-time one — a window that on a
  new campaign holds the whole scripted start, and on a load is however long the player sat
  there. Measured in play 2026-09-09: it announced *"wh_main_emp_empire lost 2.1% of the world"*
  on turn 1, which is a quarter of the Empire in one turn and is really setup being priced as
  news. It costs one turn of real demand shocks after every load, which is the safe direction —
  a missed shock is invisible, an invented one moves the player's money.

Called from the turn round **only**, never from `EX.rescan`, which also runs at first tick and
after a load: a shock minted there is a price move a player can farm with F9, the same unbounded
printer `EX.check_delistings` had to be guarded against.

---

### 8.2 Who did it, and where (2026-09-30)

Every shock records **who** hit the good and **where**, next to the kind: the attacker's faction
key (read from the event's character; the raid's general), and the region. `EX.shock_src[res]`
is `{who, at, big, others}`, world state like `EX.shock`, saved as one
`zharr_shocksrc_<res>` string.

- **The named hit is the biggest one still standing, not the last.** A good is often hit from
  several places in a turn, and "last" names whoever the event order put second. The kind
  (`EX.shock_why`) follows the same hit, so "razed by X" always describes one event. `big` decays
  with the shock, or a three-turn-old raze would keep the name over every fresh hit. When the
  shock fades to nothing the record goes with it.
- **"and others"** once anyone *else's* hit is in the same shock. A second hit by the same
  attacker is not someone else.
- **Rebellions and a culture losing ground have no attacker.** A rebellion keeps its place; a
  culture's shock has neither, and its bulletin is the plain one.
- **A context that cannot name its character still shocks** - `EX.attacker` has its own pcall.

Where it shows:

| Where | Text | When the name is looked up |
|---|---|---|
| Chart page note | `Shaken 4.5 steps (sacked by Skarbrand's Exiles and others).` | when drawn |
| Log | `Demand shock: prices +4 step(s) (sacked by ...).` | when the Log is drawn - the entry stores the faction **key** between two `EX.LOG_NAME` marks (`string.char(29)`), because a name looked up inside the turn round took the process down at turn 1 on 2026-09-07 |
| Bulletin | unchanged text - it is a fixed loc key per good | never. Clicking it moves the camera to the named hit's settlement (`EX.region_xy`); a region the map cannot find, or a shock with no place, takes the plain record |
| Footer | unchanged: `Shaken: Iron (sacked).` | never. Line 1 is at ~110 of its 118-character budget at its widest, and one name is up to 34 |

**A faction name can be a pointer.** 26 of CA's `factions_screen_name_` entries are only
`{{tr:<another key>}}` - the Khorne, Nurgle and Slaanesh invasions among them, the likeliest
raiders. `EX.faction_display` follows each pointer once; a pointer to nothing, or to another
pointer, falls back to the humanised key rather than printing markup.

Checked by `check_shock_source` (21 behaviour assertions, run against the shipped file) and 29
mutants, all caught.

## 9. World appetite — how other factions move your prices

Two independent terms, summed and multiplied by `AI_GAIN` (6.0), then truncated and clamped to
+/-2 rungs.

**Culture.** Each culture's appetite for a good, weighted by its share of the world's
**regions** (not factions, and razed or besieged land is out of both supply and demand):

```lua
culture = sum over cultures of  CULTURE_WANTS[c][res] * share[c]
```

Positive is demand, negative is supply. 27 entries cover all 26 land-holding vanilla cultures
plus the Southern Realms. Two vanilla keys are exempt and the exemption is pinned in two places
so growing the list is a deliberate edit with a reason: `*` is a wildcard row in
`cultures_tables` rather than a culture, and `wh2_main_rogue` holds no regions so its share is
zero by construction.

Every culture has both signs. A culture with only positives demands and never supplies, which
pushes every price it touches one way for the whole campaign; only negatives is the same fault
mirrored.

**Drift — a culture's own state shades what it wants** (2026-09-09). The `CULTURE_WANTS` entry
is a *baseline*, not a constant: each culture's own war load and its own growth move it before
the share multiply.

```lua
drift(c, res) = DRIFT_WAR (0.35)    * WAR_APPETITE[res]   * (war_share(c) - WAR_BASELINE)
              + DRIFT_GROWTH (0.50) * BUILD_APPETITE[res] * culture_trend(c)
```

clamped to +/-`DRIFT_MAX` (0.25). `BUILD_APPETITE` is a second 17-key table, both signs, for
what a culture that is *expanding* consumes. `culture_trend` is growth as a fraction of the
culture's **own** previous size, so a tenth bigger is +0.1 however large the culture is.

**Both halves are deviations, not levels**, which is what keeps them on the same scale as the
world war term below. A war written as a level would be `0.35 * 0.85 = 0.30 * appetite` against
that term's `0.025 * appetite` at a typical index — twelve times larger, and it would swamp the
culture term it is meant to shade.

`war_share` falls back to `WAR_BASELINE`, **not to zero**, for a culture the scan did not
measure. Zero in a term reading a *deviation* means "wholly at peace" — the most negative value
available — so the fallback that looks like no-opinion dragged every unmeasured culture's
appetites hard the wrong way. Caught by the appetite harness's stub board, which has no
`culture_war` at all.

`DRIFT_MAX` bounds the total so drift can shade an appetite and never invert it: a culture at
war wants more iron, it does not start supplying wine. Without it a confederation doubling a
culture's share in one turn is a trend of 1.0 and would do exactly that. All three constants are
**uncalibrated** and ship deliberately small, like the four appetite constants. A culture
missing from `CULTURE_WANTS` still contributes exactly zero *including its drift*, so
`EX.warn_uncovered` below means what it says.

**War.**

```lua
war = WAR_WEIGHT (0.5) * WAR_APPETITE[res] * (war_index - WAR_BASELINE)
```

`war_index` is the share of the world's regions belonging to factions at war. `WAR_BASELINE`
0.80 is measured, not guessed: the index read 0.6235 / 0.6291 / 0.8488 / 0.8969 at turns 1 / 2 /
17 / 27 of one IE campaign. It climbs and flattens near 0.9, so the war term reads negative
through the quiet opening and positive once the world burns. Shipped at 0.35 on 2026-09-06 and
never once went negative.

`WAR_APPETITE` covers every commodity including the zeroes — a missing key is indistinguishable
from a deliberate war-neutral. Armies eat salt, burn timber, bleed and need iron; nobody
commissions a marble frieze during a siege. Dwarf Beer is 0 on purpose.

**Scale, in practice.** A culture holding a tenth of the map with a 0.7 appetite contributes
`6.0 * 0.07 = 0.42` rungs — under one, so no single culture moves a price by itself. What moves
the board is the sum across all 27, and a large swing in one culture's share. An Empire collapse
or a runaway Empire shows up in your prices; an ordinary war between them and Bretonnia mostly
does not.

**A culture with no entry contributes exactly zero, silently** — `world_appetite` reads
`if wants and wants[res]`, with no fallback and nothing in any log. The Southern Realms shipped
that way for a whole build: fully covered as a race, with a patron and seventeen flavour lines,
and invisible to the prices those describe.

`check_culture_appetites()` now stops that for vanilla and for any race this mod covers. It
cannot stop it for **another mod's** culture, because a build-time check only knows what is
installed on the build machine — so the game reports it instead. `EX.warn_uncovered` names any
culture holding >= 1% of the world's regions with no appetite entry, once per campaign:

```
<culture> holds N.N% of the world's regions and this mod has no appetite for it -
it contributes nothing to any price. Add it to EX.CULTURE_WANTS.
```

The threshold is not zero because a single region changing hands mid-war would otherwise
announce a rounding error.

### 9.1 The world tier - every other landholder trades

Since 2026-09-13. The guild is untouched; beside it, every other landholding faction is an
**actor** with a book, a budget and a desire score - and nothing else: no shares, no dividend, no
stance promotion, no guild row. Widening `EX.guild()` instead was rejected: `EX.refused_by` and
`EX.market_closed` are share-of-the-guild's-book thresholds, and across the whole map no share
ever reaches them, so both would stop firing with no error.

**The roster costs nothing.** `EX.scan_supply` already caches culture and war per owning faction
in its region walk; the treasury is one more read, in its own `pcall` (a faction whose treasury
cannot be read is an actor with 0 gold, not a missing one). `EX.actors` is that cache minus every
faction whose culture `EX.is_house_culture` accepts - every human's culture and, with `cross_bloc`
on, their trading blocs - so no faction is both a house and an actor, and no human is ever an
actor. Rebuilt every scan; a failed scan keeps last turn's roster. Every consumer still filters
`EX.is_human` itself. One campaign's load-time sweep counted 73 actors.

**The book is a position, not a warehouse.** `EX.wbook[faction][res]`, in lots, and it may be
**negative**: a producer selling its output is short. What an actor can sell comes from its land,
re-derived on every call and never banked:

    capacity(f, res) = floor(output x WORLD_STOCK_TURNS (3) / lot(res))    output = EX.owners[res][f], in units
    sellable(f, res) = max(0, capacity + book)

**Floor the product, not the factor**: `floor(output / lot) x 3` gave every producer under a lot a
turn capacity 0 forever, and the whole world makes 6 units of Dwarf Beer a turn. `EX.owners` is an
output **amount**, not a region count - the `add()` helper in `EX.scan_supply` is the authority,
and five comments once said otherwise. `EX.set_world_book` lets a write deepen a short only down
to `-capacity`, but always lets a position move toward zero, however far capacity has since
shrunk: a faction that loses the land behind its short is never quietly forgiven part of it. An
accrual step, `EX.accrue_world_stock`, was built first and **withdrawn** - it read output as a
region count, pinned the price term at its ceiling within turns, and only ever added.

**Desire** - `EX.world_desire(faction, res)`, five terms and zero engine calls, since it runs
actors x 17 times a turn:

| Term | Value |
|---|---|
| Production | `-(0.4 x output)` if it produces the good, else `+0.5` |
| Taste | `EX.CULTURE_WANTS[culture][res]` - §9's table, promoted from an aggregate price shift to this faction's personality. Drift is not applied |
| War | `+WAR_APPETITE[res]` if this faction is at war - its own war, not the world index |
| Value | `0.15 x (neutral step - current step)`, as for a house |
| Position | `-0.05 x book` when long only. A short is an actor's normal state, not an appetite to buy back; two-sided, a fully short producer became the keenest buyer on the map for its own good |

No front-run term and no `house_bias`: watching the player's book is a house behaviour.

**The matching pass** - `EX.step_world`, turn step 9a. Each actor names one good to buy (its
highest desire, if above 0) and one to sell (its lowest desire among goods it can sell, if below
0). Per commodity, the i-th buyer is paired with the i-th seller; the longer side's remainder
does not trade this turn. A pair moves `n` lots, capped by the seller's `sellable`, by
`world_trade_max`, by what the buyer's scanned treasury affords, and by
`floor(world_cash_max / price)` - without that last cap `EX.pay_actor` clamped the gold while the
books moved in full, creating goods. **Gold is conserved by construction**: the seller receives
exactly what `EX.pay_actor` took from the buyer, where the guild's `EX.pay_house` is a sink that
would drain eighty treasuries a turn. Both scanned treasuries are spent down as a per-turn
budget, so one treasury cannot pay once per commodity. Trades are at last turn's price, before
the reprice. **The guild's own step, `EX.step_books`, has the same lot cap since the logic sweep
of 2026-09-29**: a house buys and sells no more lots than `house_cash_max` pays for
(`EX.house_lot_cap`, `ai_gold` on). Before, `EX.pay_house` clamped the gold while the book moved
in full, so at a lot price above a quarter of the limit a house booked goods it never paid for. A **confirmed**-dead faction's book and save key are pruned first -
`cm:get_faction` returning `false`, or a faction merely absent from this scan, leaves the entry
alone. `ai_world` off makes the whole pass a no-op.

**What moves the world book's price, and what does not.** `EX.world_book_shift` reads
`EX.world_book(res)`, the sum over `EX.wbook` - the book, not the roster, so a faction missing
from one scan cannot jolt a price. A matched trade moves `n` lots from one book to another and
leaves that sum unchanged, so **world-to-world trading never moves a price.** The sum changes
only when a player trades against an actor (step 2 of §5's walk, or a deal) and when a dead
faction's position is pruned. It is the negative of the humans' cumulative net trade with the
tier: buy 25 net lots from actors at default settings and this term reads one step *down* for as
long as the position stands, while your own pressure (§4.2) pushes up and decays. What the
matching pass does move is treasuries, `sellable` (hence §5's Sold out), the war-goods
positions of §10.1 and next turn's desire.

**Nothing on the panel shows it.** `EX.world_flow` (lots bought and sold, actors that moved) is
built every turn and read by nothing but the harness: no Log line, no footer, no `EX.say`. The
tier is visible only through prices, the Sold out refusal, the Deals page and the War Stocks
bundles.

Switches and knobs, all in §13: `ai_world` ("The world trades"), `world_scarcity` ("Supply
can run out"), `world_cash_max` 3,000, `world_trade_max` 3, `world_gain` 4.0.
`EX.WORLD_STOCK_TURNS` (3) is a constant, not a knob.

---

## 10. Trade income

The Exchange price of what **your own regions produce** drives your vanilla trade income.

```lua
level = sum over your commodities of  regions * (price / 1000 - 1)   / total regions
pct   = level * TRADE_GAIN (40)
```

snapped to the largest step reached in either direction, out of
`{-40, -30, -20, -10, +10, +20, +30, +40}` per cent, applied as one of eight effect bundles
carrying CA's own `wh_main_effect_economy_trade_good_commodity_mod`.

A faction with ten cheap iron regions and one dear gem region is an iron economy, and the number
says so. Switchable off (`trade_income`).

### 10.1 Position bundles - war materiel

Since 2026-09-16. A third bundle family beside trade income and the warehouse: an actor's net
position in war materiel, crossed with its war state, becomes a replenishment bundle on that
faction and so on every one of its forces.

    war goods = res_rom_iron, res_rom_timber, res_obsidian             EX.WAR_GOODS
    position  = the actor's world book summed over those three, NET    long iron and short timber cancel
    steps     = position / pos_step (4 lots), halved if it is not at war
    tier      = the largest of -2, -1, +1, +2 that steps reaches, else none

| Bundle | `wh_main_effect_force_all_campaign_replenishment_rate`, `faction_to_force_own` |
|---|---:|
| `derpy_chd_ex_pos_pos02` | +6% |
| `derpy_chd_ex_pos_pos01` | +3% |
| `derpy_chd_ex_pos_neg01` | -3% |
| `derpy_chd_ex_pos_neg02` | -6% |

`3.0 x tier`, titled "War Stocks". The three goods were chosen by **display** name - `res_rom_lead`
is Salt and `res_rom_glass` Dwarf Beer, so a set picked off the keys would be the wrong three with
every gate green - and `check_lua_books` pins the set at three keys, all in `EX.COMMODITIES`. The
effect/scope pair is the one `WRATH_EFFECTS` already ships; an effect on a scope it does not
support is a row the game accepts and ignores. The `pos_` stem is deliberate: `trade_` and
`stock_` are live families whose sweeps delete their whole family.

**Peace halves the tier, it does not zero it.** A bundle that came and went on every declaration
of war would flicker across the map, and every flicker is a real engine write on every client. A
faction in the book but missing from this scan reads as at peace - the conservative half.

**Who wears one: the world tier, and only the world tier.** The sweep walks `EX.actors`. A human
is never an actor (its culture is a house culture) and has no world book - a player trade moves
the counterparty's book, not the player's - so **the player never wears a War Stocks bundle**,
and neither does a guild house. Selling iron to an actor at war visibly arms it; buying it off
one strips it. A producer that sells its war goods forward carries a negative tier for as long
as the short stands, which is indefinitely (§17). The `world_bundles` MCT tooltip said
"Applies to you and other factions alike" until 2026-09-28, and the 2026-09-17 patch note said the
same; the code never did.

**The sweep** - `EX.apply_positions`, turn step 15a and on the load path: remove all four keys,
then apply one, duration 0, the `EX.apply_trade_income` idiom, because same-effect bundles stack.
`EX.pos_level` is memory only while the engine holds the bundle across a save, so the sweep is
forced once per load (`EX.pos_swept`), and a faction that dropped out of the scan wearing a
bundle has it removed. **Off is a level, not a return**: with `world_bundles` off every answer is
0, so switching it off strips what was applied rather than stranding it - reachable, because a
campaign whose settings snapshot predates the switch reads it live from MCT.

`pos_step` reads backwards from most knobs here: smaller is stronger. 6 / 4 / 3 / 2 on easy /
default / hard / ultra. None of the magnitudes is measured.

---

## 11. The eight races

Everything race-shaped in the file derives from `EX.RACES`. Eight rows.

| Culture | Market | Patron | `seg` | Layer 2 |
|---|---|---|---|---|
| `wh3_dlc23_chd_chaos_dwarfs` | Zharr Exchange | Hashut | `""` | armaments, raw materials |
| `wh_main_emp_empire` | Imperial Bourse | Sigmar | `emp_` | none |
| `wh3_main_cth_cathay` | The Ivory Road | The Court | `cth_` | none |
| `wh2_main_skv_skaven` | The Under-Market | The Council | `skv_` | none |
| `mixer_teb_southern_realms` | Merchant Compact | Myrmidia | `teb_` | none |
| `wh_main_dwf_dwarfs` | The Long Ledger | Grungni | `dwf_` | none |
| `wh2_main_hef_high_elves` | The Emerald Gate | Asuryan | `hef_` | none |
| `wh2_main_def_dark_elves` | The Black Ark Market | Khaine | `def_` | none |

**The patron is a grammatical subject, and two ceilings police it.** It is substituted into
"`<patron>` grants" as the Offerings column header and into "`<patron>` demands 90 Iron within 3
turns" on the Offerings footer, the opener's tooltip and (as "`<patron>` demands 90, within 3
turns") the Log, so a plural collective reads as *"The Ancestors grants"* with nothing anywhere to notice:
the Dwarf patron is **Grungni**, not the Ancestors, for that reason and no other. And
`check_help_lines` substitutes the LONGEST patron name into the guide's offering line and
measures it — at 17 characters *"The Phoenix Court"* reached ~636px in a 620px column and would
have clipped mid-sentence, which is why the High Elf patron is **Asuryan**. Both races keep the
institution in their tier and wrath titles, which is the split the Empire already shipped:
Sigmar receives the tithe, the Temple is what notices.
**`seg` is the save-compatibility mechanism**, not a cosmetic field. Every per-race key is built
as `PREFIX .. seg() .. rest`, so the Chaos Dwarf empty string reproduces the keys this mod has
been shipping — `derpy_chd_ex_offering_gems`, `derpy_chd_ex_dem_tithe_gems` — byte for byte. A
live campaign holds those inside applied effect bundles; renaming one orphans it mid-game with
nothing on screen to say why. `wrath` and `pleased` are carried literally for the same reason:
the patron's name is already inside the Chaos Dwarf key.

The other 20 cultures (19 until game update 9.0 added Nagash's Undead Legions) are **uncovered**,
which is still the majority case. By default 14 of them get no Exchange at all: the culture lock
(`EX.LOCK_GROUPS` - 11 cultures without markets and 3 raider cultures, MCT `allow_uncommercial` /
`allow_raiders`, both off, and always off in multiplayer). The other six, and any the player
unlocks, get the commodities
market — layer 1 was never Chaos Dwarf — with the Offerings tab greyed (no altar, and no
patron written for them), the board titled plainly "Exchange", and their appetite still priced
into every commodity through `EX.CULTURE_WANTS`.

**The Houses tab is NOT greyed for them, and this said otherwise until 2026-09-11.**
`EX.HOUSE_CULTURE` follows the local player whatever their culture, so shares in an uncovered
culture's own factions are discovered, priced, traded and settled exactly as for a covered one.
`EX.tab_locked` greys Houses only when the walk found nothing to list — see its comment.

**Nagash (game update 9.0) sits with the Vampire Counts, not on a ninth board.**
`wh3_dlc29_nag_undead_legions` ("Undead Legions"; one playable faction,
`wh3_dlc29_nag_host_of_nagash`) is in the three places the Counts are:

- its `EX.CULTURE_WANTS` entry is the Counts' appetite, copied exactly;
- it is left out of `EX.BLOC`, like the other three undead cultures, so no other culture can
  buy its shares. The generator's `BLOC_ABSENT` names it, and `check_culture_locks` holds that
  list equal to the uncommercial lock group;
- it is in `EX.LOCK_GROUPS.uncommercial`, so by default a Nagash player gets no Exchange at
  all - no button, no panel, no prices - until the MCT switch "Let cultures without markets
  trade" (`allow_uncommercial`) is on. That takes effect on a restart.

Its 16 `wh3_dlc29_nag_resource_*_1` buildings carry no `..._resource_*_production` effect in
9.0 (army buffs and trade income instead). So the derived production map gives them nothing,
and Nagash land adds demand but no supply. Nothing was invented for them.
`check_culture_appetites` is what caught the gap: 9.0's `cultures_tables` added the key, and the
selftest failed until the entry existed.

### 11.1 Race profiles

A profile is a set of **multipliers** on whatever the difficulty preset and MCT have already
resolved — not a replacement. Skaven aggression composes with Hard rather than being erased by
it. A race that set absolute values would flatten every preset but `default`.

**Chaos Dwarfs carry no profile.** They are the baseline, at ×1 on everything.

**In multiplayer the shared market takes no profile** (logic sweep, 2026-09-29).
`shock_gain`, `shock_max`, `book_per_rung` and `pressure_per_rung` (`EX.WORLD_TUNABLE`) are read
unbound by the world steps and by every reprice, which on each machine means that machine's own
player - so until then a Chaos Dwarf machine and a Skaven one priced the same book differently
and the shared prices never agreed again. In multiplayer those four answer ×1; in singleplayer
the player's profile still shapes the board. The index weighs a dead member at the **index's own
culture's** wind-up (`EX.opt_for_culture`), since one culture's index is one number on every
machine. Every other knob follows the player it is read for, in both modes.

| Knob | Empire | Cathay | Skaven | S. Realms | Dwarfs | High Elves | Dark Elves |
|---|---:|---:|---:|---:|---:|---:|---:|
| `hostile_max` | 0.7 | 0.8 | **2.2** | 0.5 | 0.6 | 1.2 | 1.8 |
| `refuse_share` | — | — | **0.5** | 1.6 | 0.5 | 1.5 | 0.7 |
| `guild_close` | 1.3 | 1.2 | **0.6** | 1.5 | 0.5 | 1.4 | 0.7 |
| `shock_gain` | 0.5 | 0.4 | 2.0 | 1.6 | 0.6 | 0.7 | 1.4 |
| `shock_max` | 0.7 | 0.6 | 1.5 | 1.3 | 0.7 | 0.8 | 1.2 |
| `demand_chance` | 0.7 | 1.2 | 1.83 | 0.8 | 0.7 | 0.6 | 1.4 |
| `demand_cooldown` | 1.4 | 0.8 | — | — | 1.6 | 1.4 | 0.8 |
| `windup` | 1.4 | 1.2 | **0.3** | 1.6 | **1.8** | 1.2 | 0.4 |
| `div_yield` | **1.5** | 1.2 | 0.7 | 1.4 | 0.6 | 1.3 | 1.3 |
| `book_per_rung` | 1.4 | 1.6 | 0.6 | 1.5 | 1.5 | **1.8** | 1.3 |
| `pressure_per_rung` | 1.25 | 1.5 | 0.75 | 1.5 | 1.5 | 1.6 | — |

- **Empire — institutional.** Slow, deep, civil. Shocks damped, half again as much volume to
  move a price, polite even when they dislike you, open through wars that would shut a rougher
  market, orderly wind-ups — and the best paper in the game. Dull, and the best yield.
- **Cathay — regulated.** The calmest board of the eight, with books so thick that cornering
  anything takes real money. What you pay for it is the Assessment: more often and on a shorter
  cycle, because a regulated market is a taxed one.
- **Skaven — predatory.** Every dial that can cost you up, every dial that pays you down. A clan
  that hates you charges more than double the worst markup anyone else can reach; refusals are
  common; a third of the book at war shuts the market; the Council takes its cut nearly twice as
  often; and a dead clan leaves you almost nothing. The books are **thin**, so clans move prices
  against you on volume the others would not notice.
- **Southern Realms — bankers.** The most liquid and forgiving board, and the one that almost
  never shuts. What it pays for that is exposure: a mercantile economy feels every sack, so
  shocks land harder here than anywhere.
- **Dwarfs — the vault.** The safest board and the hardest to get into, and those are the same
  fact: a Dwarf who dislikes you does not charge more, he declines and writes it down, so
  `hostile_max` goes DOWN and `refuse_share` with it. `windup` 1.8 is the exact inverse of the
  Under-Market — a hold that fails pays its debts, so backing a loser costs you almost nothing.
  What you pay is the worst yield on the board and gates that shut early in a war.
- **High Elves — old money.** The deepest books in the game and no refusals: an Elf does not
  decline commerce, an Elf sets a price, which is why `refuse_share` and `hostile_max` go up
  together — the opposite pairing to the Dwarfs, saying the same thing from the other side.
  `div_yield` is deliberately UNDER the Empire's 1.5, because two races tied for a superlative
  is two races with no superlative.
- **Dark Elves — rich and predatory, which is not the Skaven.** The Under-Market is predatory
  AND POOR, and a druchii profile built the same way would be a reskin — so `book_per_rung`
  goes UP: Naggaroth has real wealth, and the depth is the whole difference. The robbery is at
  the END rather than throughout, and `div_yield` up against `windup` down is the race in two
  numbers: slave-worked cities pay handsomely right until one is sacked, and then you get a
  fifth back. `hostile_max` stays under the Skaven's 2.2 on purpose; they are expensive, not
  extortionate.

**A profile's numbers are pinned twice over.** Every factor must be within 0.2 - 3.0, which
is a typo guard rather than a design bound (22 for 2.2 would clamp and look deliberate), and
every resolved value must sit strictly inside its knob's bounds **on the default preset** — a
profile whose number is already clamped before anyone has touched the difficulty does not mean
what it says. At the extremes clamping is expected and shipped: High Elf `refuse_share` and
`guild_close` hit their ceilings on Easy, and Dark Elf `hostile_max` reaches the same 0.75 as
the Skaven on Ultra, so those two boards are distinct on Easy, Default and Hard and identical
at the top. The Southern Realms and Skaven profiles have always clamped the same way.

**The whitelist is the safety rail.** `EX.RACE_TUNABLE` names the 11 knobs a profile may move,
each with a bounds pair. `spread`, `ladder_step`, `sell_floor` and `friendly_max` are
deliberately absent — see §4.3. A key not in the table is inert, and `check_race_tune()` refuses
to build if a profile names one, so "inert" never has to be discovered in play.

**No race profile touches the world tier.** None of its six knobs - `world_cash_max`,
`world_trade_max`, `world_gain`, `deal_max`, `deal_edge`, `pos_step` - is in `EX.RACE_TUNABLE`,
so every board runs the world tier, the Deals page and the position bundles on the preset's
numbers alone. The roster does depend on the player's race: `EX.actors` excludes every house
culture, so a Chaos Dwarf's world tier and an Empire player's are different sets of factions
(§9.1).

The bounds are not decoration. Multiplying compounds: `ultra` already sets `hostile_max` 0.60,
and Skaven's 2.2 on top is 1.32 — a buy at 2.32x the world price, which is not a market, it is a
wall. Every pair contains every preset x race product, with the extremes clamped;
`check_race_tune()` prints which combinations clamp.

### 11.2 The strength dial

```lua
factor = 1 + (profile_factor - 1) * race_strength
```

One slider over the whole feature. 0 switches race profiles off entirely and every board becomes
the shared baseline; 1 is as designed; 2 doubles every departure. It scales the **distance from
1**, so a knob the profile does not touch stays untouched at every strength, and a ×0.6 and a
×1.4 soften and sharpen symmetrically. The presets set it: easy 0.5, default 1.0, hard 1.0,
ultra 1.25.

It is what makes the base sliders honest again. With a profile running they set the base and the
profile multiplies it, so MCT shows 0.25 while a Skaven board runs 0.55 — and there is no way to
say so inside MCT, because an option's tooltip is static text written at registration, before
any faction exists. At strength 0 the two agree exactly.

`race_strength` **must never** be added to `EX.RACE_TUNABLE`. `EX.race_factor` reads it through
`EX.opt`, and `EX.race_apply` returning early for a non-whitelisted key is the only thing
stopping that read recursing into itself. `check_race_tune()` asserts the exclusion.

The profile is applied in `EX.opt`, not `EX.opt_live` — so the campaign snapshot stays raw, and
an in-flight campaign picks up a profile change on the next load.

### 11.3 The Southern Realms is a soft dependency, and must stay one

Cataph's Southern Realms (Steam 2927296206, ships as `!ak_teb3.pack`). Every DB row this mod
generates is keyed by our own prefix, and the culture string appears **only** in the Lua, as a
table key — so with the mod absent nothing ever matches it and the Exchange behaves exactly as
it did before. `check_no_foreign_keys()` asserts that: the string must appear in zero DB rows
and zero loc rows. Naming one of their factions or tables in a row is what would turn this into
a required dependency, and the check exists to stop that happening later.

The culture key was read off a live campaign, not off the store page — a faction of that mod
answers `culture()` **and** `subculture()` with the same string, which is not the usual shape
and is the sort of thing a guess gets wrong silently and forever.

---

## 12. The panel

Its own `.twui.xml`, created at runtime with `CreateComponent` — CA's files are not overridden.
See `docs/CUSTOM_UI.md` for the GUID rules, why `dockpoint` is ignored and `MoveTo` is the only
thing that positions a runtime component, and the texture traps that fail silently.

### Size: the panel grows with the screen

Since 2026-09-24. It was 920x736 on every screen, and 4K players found it too small. **Every
layout table in the Lua is the 1600x900 end, unchanged, and every coordinate this section quotes
is at that end**; `EX.grow` derives the rest.

`EX.fit(sw, sh)` runs on every `EX.layout()` pass. The box is the largest 16:9 width that fits,
`min(sw, sh * 16 / 9)`, clamped to 1600..2560. 1600 is the floor a script ever sees: the root
reports the window divided by UI Scale, floored at 1600x900. 2560 is the cap, because
normal-size text in columns any wider loses the eye along the line. The arithmetic is integer,
`EX.sc(v) = floor((v * box + 800) / 1600)`, because game Lua is float32 and `v * 1.6` would not
stay exact.

| Screen the script sees | Box | Panel | Houses rows a page |
|---|---|---|---|
| 1600x900, or any window at 1280x720 at 100% | 1600 | 920x736 | 20 |
| 1920x1080, 1920x1200, 2560x1080 | 1920 | 1104x883 | 25 |
| 2560x1440, 3840x2160 at 100%, 5120x1440 | 2560 | 1472x1178 | 35 |

`EX.grow(e, chart)` moves each table entry:

- x always scales.
- A width scales unless the cell is in `EX.GROW_FIXED` or `EX.GROW_RIGHT`. `EX.GROW_FIXED` is
  art with a fixed shape (the icons, the sparkline and its header, Buy/Sell, every stepper): it
  moves and never stretches. `EX.GROW_RIGHT` (close, help, the page arrows and counter) keeps
  its distance from the right edge.
- Anything at or below `EX.GROW_BOTTOM` (y 600: the footers, tabs and nav) moves down with the
  panel's bottom edge.
- On the chart page, `EX.GROW_CHART_Y` moves the middle gridline by half the plot's growth and
  everything under the plot by all of it.

A cell no table gives a width widens from its `.twui.xml` width through `EX.GROW_BASE_W`: the
divider (868), both footers (880) and the title (400). The chart's bar height, width and pitch
go through `EX.sc`. Text never grows, because its size is set in the `.twui.xml`. Neither does a
row's height (40) or pitch (28), so rows only widen.

**`Resize` resizes children by default** (CA: "optional, default value=true"). The panel,
`rows_holder` and every row are resized with `false` as the third argument. Without it, every
cell that `place()` gives no width (close, help, Buy/Sell, the icons) would stretch by the same
factor, and nothing would put it back.

**`EX.MAX_ROWS` is the rows a page, and only the Houses list pages by it.** `EX.fit` rewrites it
as `20 + floor(growth / 28)`. The Trade list draws its 17-19 commodities at any size. The Log,
the Guide and the introduction borrow those rows, so on a bigger screen they gain width, not
lines. A row past the last slot would land below the panel: drawn, interactive and off screen.

The panel's size is computed, never read back, and the panel is centred on that number. The HUD
opener is not scaled. A size change is logged once per change, not once per pass: `box B on a
WxH screen, panel PWxPH, R rows a page` (`ui` category). The de-dup field is `EX.fit_said`,
because `check_trend_snapshot` bans the substring `EX.last` anywhere in the file.

**Checks.**

- `check_scale_far_end` re-derives all 20 layout tables at 2560x1440 in Python, from the growth
  sets as the Lua declares them. It requires every cell inside its panel or row, no overlap
  that is not already there at 1600x900, `hdr_spark` still exactly the sparkline's width, and
  the chart page ordered under a plot measured at its grown size. It checks that the last row
  clears the footers at every box from 1600 to 2560, since the row count is a floor and so not
  linear in the box. It refuses any cell that is neither widened, fixed nor stuck right.
- `_layout_harness.lua` runs the real `EX.layout` at eight screens, 1280x720 and 2560x1080
  (height-led) among them. At 3840x2160 it draws 35 and then 6 of 41 houses, with no clash.

**Not cross-checked:** `EX.BASE_W` / `EX.BASE_H` (920, 736), 868, 880, 40 and 600 are copies of
`gen_exchange_ui.py`'s numbers, and nothing asserts that the two agree.

### The first-run introduction

**Shown once, to each player, the first time they open the panel.** `EX.show` puts the panel
into `MODE_INTRO` when `EX.intro_seen()` is false; nine paragraphs explain who your people are
and how the board works, and the first of them is the race's own — the Dwarfs read that the
Long Ledger is a vault, the Druchii that the Black Ark Market pays well right up to the turn a
city falls.

**No new components and no new GUIDs.** It borrows the row machinery the guide already borrows,
with one 850px cell instead of two columns, and no divider — ruling a paragraph makes it look
like a table.

**A picture beside every paragraph, all of it vanilla.** Reported as "looks plain" from a
screenshot 2026-09-09. Each row already has a 24x24 `icon` cell, so the rail costs nothing:
`EX.art(stem)` resolves `ui/campaign ui/effect_bundles/<stem>.png`, which is the family this
panel already paints its resource icons from — the introduction and the commodity list two
clicks away therefore match, which mixing in `ui/buildings/icons/` (bordered art tiles) would
not. The opening line carries the race's own heraldry from CA's `trait_*` set, one per profile,
and the eight concept paragraphs carry `treasury`, `dlc12_discover_up`,
`sphere_of_influence_size`, `siege_attack`, `edict_stimulate_trade`, `cargo`, `effect_rite`
and `office`.

**The paths are verified against the pack index, not a byte-grep.** A missing image path draws
a **blank square** — no error, no log line — and this page is shown once, so nobody gets a
second look. `check_intro_art()` enumerates every path in `ui.pack` and `ui2.pack` with
`read_pack_index` and requires each stem to be in it. A byte-grep would prove nothing either
way: the string could sit in some other file's text, and CA's packs are compressed.

**The picture belongs to the line, not the row** — the log's rule, and the same trap. Rows are
built one per instrument with that commodity's icon baked in, so a paragraph break that does
not actively hide the cell draws a gemstone floating in a gap. `EX.draw_intro` hides it, which
is not the default: `EX.ROW_LAYOUT_INTRO` names the cell, so `EX.layout` has already shown
every one of them by the time the draw runs.

**A blank row between every paragraph**, which is what fills the page — the same screenshot.
The break costs nothing (the view already drew one as a break) and the previous version left
half a panel of dead space under the text.

**The page is exactly as long as the SHORTEST race's holder — 17 lines, not 19.**
`EX.mode_instruments` hands this view `COMMODITIES + LAYER2`, and `LAYER2` is the Chaos Dwarf
pair that every other race binds empty. So a Chaos Dwarf player has 19 rows and everybody else
has 17. Written at 19 first, and the layout harness caught it because it binds no race: two
paragraphs would have drawn perfectly for the race being looked at and silently vanished for
the other six. Nothing errors when a line runs past the end — `EX.draw_intro` walks the rows,
not the lines. `check_layout` holds the count to `len(COMMODITIES)`.

**There is no dismiss button.** The six tabs the player is about to use are already on screen
and the footer points at them; leaving IS the dismissal, and `set_mode` records it on the
way out rather than on the way in — marking it on arrival would spend the one showing on a
player who opened the panel and shut it again without reading a line. The flag is
**per-player**: two humans each meet the panel for the first time on their own turn. The
closing instruction lives in the two **footer** strings rather than in a row, which is what
bought back the two rows the paragraph breaks needed.

### Six views plus a guide and the introduction

| View | Columns |
|---|---|
| **Trade** | Commodity, Buy, Sell, Output, Trend, Last 12 turns, Held / rent |
| **Stats** | Commodity, Output, Largest producer, Share, Cartel premium, Last 12 turns |
| **Offerings** | Commodity, Held, Cost, `<patron>` grants, Status |
| **Houses** | House, Price, Div, Seat, Trend, Last 12 turns, Held |
| **Deals** | Faction, Offer, Per lot, vs market, Total, and a Take button - see "The Deals page" below |
| **Log** | Turn, What happened |
| **Guide** | Term, What it means (2 pages, 28 lines; page 1 is at the 19-row ceiling, so the Worth line went on page 2). Five lines print the live settings - Rent, Offerings, Div, Delisted and House Sell, rebuilt at draw time by `EX.HELP_LIVE` from `carry_per_unit`, the offering cost and patron, `div_yield`, `buyout_premium` / `windup` and `spread`. The Forge-goods line still carries no number: `l2_sell` has no builder |

"Output", not "Supply" and not "Regions". Reported from play 2026-09-05: *"i always thought
supply is the amount of stocks that you can buy not the region"*. It is units produced across
the whole map per turn; buying never consumes it. What moves the price against you is pressure.

"Buy" and "Sell", not "Price" and "Sell" — with both numbers on screen, one column called
"Price" leaves the player working out which side of the spread it is.

**The five live Guide lines have to equal their literals at the defaults, word for word.** The
literal in `EX.HELP_PAGES` is what `check_help_lines` measures and what `EX.bind_race` rewrites
for the patron. `EX.HELP_LIVE`'s builder is what draws, falling back to the literal if it
errors. So edit both or neither: the layout harness holds each builder to its literal at the
defaults, and to a moved setting and a made offering otherwise. `LUA_BOUNDS_HARNESS` measures
all five at their worst case - the longest patron, the offering at its 5x ceiling, and a
race-scaled "12.34" dividend - against the 620px column. The Guide also says "Ownership: the
second tab", not "the third view", since 2026-09-25.

### Trade's pager is a list, not an index

Until 2026-09-10 `EX.on_chart` tested `trade_page == 2` outright and the page counter returned
`deep_history and 2 or 1` — fine while there was exactly one optional page. Limit and stop
orders added a second one, which turns that arithmetic into four switch combinations, and a
fixed index gets two of them wrong: with the chart off, a hardcoded "orders is page 3" either
sits behind a counter reading 1/2 with nothing to page to, or a hardcoded "page 2" means the
chart on one save and the ledger on another, decided by a switch nothing at the call site can
see.

`EX.trade_pages()` returns the enabled page **kinds**, in order, built fresh on every call
because both switches are live-read and unsnapshotted by design:

```lua
function EX.trade_pages()
    local t = { "list" }
    if EX.feature("deep_history") then t[#t + 1] = "chart" end
    if EX.feature("orders") then t[#t + 1] = "orders" end
    return t
end
```

So the ledger is page 2 when the chart is switched off, and page 3 only when both are on — it is
never pinned to a number. `EX.trade_kind()` **clamps** rather than returning nil: a kill-switch
can be thrown while the player is standing on the page it removes, and every caller here would
otherwise index a nil. `EX.on_chart()` and the new `EX.on_orders()` both read `EX.trade_kind()`,
and the page counter is `#EX.trade_pages()` rather than a constant.

The chart's own buffer keeps recording regardless of which page is reachable — `EX.remember_all`
is not gated, so switching the chart back on after ten turns off shows the turns you were away
rather than a flat line. A feature switch removes a page from the panel; it does not touch what
is recorded underneath it, and `orders`' own model-side switch (`EX.fill_orders`, §14) works the
same way: cancelling a standing order takes it off the list, turning the switch back off does not.

### What the Log records, and what it does not

**Entries from the player's own actions and from the world's.** Rent, offerings and the tithe
wrote nothing here until 2026-09-25. Until 2026-09-09 only three of the world's were recorded and the AI houses
traded every turn with nothing anywhere saying so — asked for from play as *"add all logging
to ai so that player can see there is interaction between the mechanics and the ai"*.

| Entry | Written by | Driven by |
|---|---|---|
| Bought / Sold, one line per single-lot click, with the markup and the house that set it (`EX.hostility_source`) | `EX.apply_trade_held` | you |
| **One line for a multi-lot click**: "Bought N for Gg in M lots." or, stopped early, "..., K of M lots." plus the reason | `EX.log_bulk` | you |
| Buy / Sell refused - "Not enough gold." or "You hold less than one lot." | `EX.log_bulk` (`EX.TRADE_STOP`) | you |
| Buy refused, with the reason - a house refuses, the market is shut | `EX.apply_trade_held` | you |
| Trade refused — market not open to your people | `EX.trade` | you, uncovered culture |
| Sale refused - no buyer on this map can pay for it | `EX.apply_trade_held` | you, a commodity sale with no counterparty (`nobuyer`) |
| Bought / Sold *n*/*m* lots from / to a faction, at the agreed price | `EX.accept_deal` | you, taking a deal |
| **The guild** — *n* houses traded, lots bought and sold, and the good most moved each way | `EX.build_world_log` | **the AI** — `step_books` at turn step 9 |
| **World appetite** — the footer's line, recorded when it *changes* | `EX.build_world_log` | **the world** — culture wants and the war index |
| **Dividends** — how many houses paid, and how much | `EX.pay_dividends` | **the AI** — turn step 18 |
| **Demand shock** — the rungs, the reason and who did it (§8.2) | `EX.announce_shocks` | **the world** — turn step 12 |
| Market **CLOSED** / **Reopened**, naming the chief belligerent | `EX.log_scan` | **the world** — guild war state |
| A house **refuses to sell** / **will deal again**, with its share of the guild book | `EX.log_scan` | **the AI** — its attitude and its book |
| **Delisted** — a house died, and what your shares settled for | `EX.log_settlement` | **the world** — via `check_delistings` at turn step 7 |
| **Rent** - "Warehouse rent: -Ng.", once a turn while rent is charged | `EX.charge_carry` | you - turn step 17 |
| **Offered** N to the patron, and what the next offering will take | `EX.apply_offer` | you |
| The patron **demands** N, within 3 turns | `EX.fire_demand` | the patron - turn step 19 |
| **Tithe paid** / **Tithe unpaid**, with the favour or the wrath's length | `EX.pay_demand` / `EX.check_demand` | you / the patron - turn step 3 |

**One line per topic, never one per house.** Twenty houses across seventeen goods would fill the
whole buffer inside two turns and push out the trades the log exists to explain. `EX.book_flow`
is accumulated *as the trades happen* inside `step_books` — a diff of the books afterwards
would also count the player's own trades, every delisting and every book the reprice touched.

**The buffer went from 60 entries to 120** for the same reason: at 60, what the world's three or
four lines a turn pushed out were the player's own.

**No line written at turn time resolves a faction name, and that is not style.**
`common.get_localised_string` from inside a turn handler took the process down at turn 1 of a
fresh campaign — no Lua error, no minidump, and `pcall` made no difference. Commodity names
are safe (`EX.display` reads the generated `EX.INFO` table, which is plain Lua); a house's name
is loc. So a line that needs one passes subject `""` and the **key** in field 4, which
`EX.log_lines` resolves when the row is drawn — and the harness installs a counting `common`
and asserts the count is **zero** across all four writers.
The rent, offering and tithe lines added 2026-09-25 are inside the same count. They name the
patron through `EX.patron()` and the good through `EX.display`, both plain Lua.

**Built once, written per player.** The books and the appetite are world state, so the decision
*"is this worth a line"* is made once and the lines are then flushed into each human's log. A
per-player version would log an appetite change for the first human and swallow it for everyone
after, because the first comparison is what stops it being a change.

**What is still silent:** the per-turn price move itself (the Trend column and the chart are its
record), appetite drift too small to change the summary line, the world tier's own trading
(`EX.world_flow` is built every turn and read by nothing - §9.1), and the CAI stances the houses
are promoted to (one `house` debug line, off by default - §7.4).

**And `log_scan` still runs at DRAW time, not at turn start.** It is called from the Log branch
of `refresh_panel` and nowhere else, so its two edge-detected entries — the closure and the
per-house refusals — are only noticed when the Log view is opened, and **a closure that lifts
between two viewings is never recorded at all.** It was left there deliberately: both of its
lines name a faction mid-sentence, so moving them to turn time means deferring those names
first. That is the next thing to do here.

### Trade page 2: the deep chart

Trade can run to three pages now, and page 1 is the only one that is a list of rows — see
"Trade's pager is a list, not an index" above for how a page's number stops being fixed the
moment either optional page can be switched off. Clicking a commodity's **name** cell on page 1
selects it (`EX.selected`); page 2, when `deep_history` is on, draws that one instrument full
width over forty turns.

`EX.deep` is its own buffer — `zharr_deep_<res>`, 40 bars, written by `EX.remember_all` beside
the 12-bar sparkline and seeded from `zharr_hist_` on a save from before it existed. The
sparkline is not a window onto it: `SPARK_BARS` truncates at **write** time and the same
constant sets the 108px strip, so a deeper view had to have a buffer of its own.

Forty `cbar_NN` components in the panel file, bottom-aligned by hand with `MoveTo` — `imagedock`
is ignored at runtime like every other dock attribute. A bar's height is

```lua
CHART_FLOOR (6) + frac * (CHART_H (300) - CHART_FLOOR)
```

so the lowest price in the window draws a visible stub rather than nothing at all.

**Each y tick has a rule running across the plot** — `chart_grid_hi` / `_mid` / `_lo`, 800x2
of the bars' own `1x1_blank_white.png` tinted to `#C8A05A55`. Asked for from a screenshot
2026-09-09: with three numbers down the left and nothing carrying them across, a bar's value has
to be estimated against a label 800px away. They are **declared before the plot** so the bars
paint over them — that ordering is intent rather than a measurement, so
`check_chart_geometry` pins the order rather than the result, and a rule sitting on top of a bar
is what to look for the first time it is seen in play. The generator's note used to read *"three
ticks and not a grid: a row of 880px-wide images per tick is a lot of components for a rule the
eye supplies anyway"* — the first half was a bad estimate (it is one stretched pixel per
line, three components in total) and the second was wrong in play.

**Each rule's y is pinned to its own label's.** They live in different files — the label
offset in `gen_exchange_ui.py`, the rule's placement in `EX.PANEL_LAYOUT_CHART` — and a rule
one pixel off its number reads as a wrong price rather than a broken chart.
`check_chart_geometry` requires both to equal `CHART_TOP + (CHART_H - CHART_FLOOR) * (1 - frac)`,
and the rule to sit at the label's y **plus 9**, the label being an 18px box centred on the line.

**The axes arrived 2026-09-09, after the chart had shipped without them** — three y ticks in
gold, right-aligned into a 60px gutter at x 20..80, and three x ticks in turn numbers under bars
0, 20 and 39. Two things there are easy to get wrong and neither would look wrong:

- **The y ticks sit on the gridlines the bar formula actually makes**, not on thirds of the box.
  The bottom of the scale is the top of that `CHART_FLOOR` stub, 6px up from the bottom of the
  plot; a label at the box edge is 6px out of step with its own data and reads as correct.
- **The middle label is `price_at((lo + hi) / 2)`, not the mean of the two gold prices.** Bar
  heights are linear in *rungs* and the ladder is geometric, so those are two different numbers
  and only one of them is where the eye reads the middle of the plot. `EX.price_at` is
  continuous, so the half-rung the middle gridline lands on is meaningful.

The x ticks are **fixed**, and a tick with no bar over it is written blank rather than naming a
turn from before the campaign began — which is what lets them be fixed instead of moved from
`EX.draw_chart` on every refresh. The turn numbers are derived, not stored: `EX.remember_all`
appends exactly once per turn and only from the turn round, never from the first-tick path,
which is what makes the newest bar *this* turn and every earlier bar one turn per step back.

The commodity's own icon sits beside the title, painted from `EX.icon` — the same source the
list rows use, so the chart and a row can never show two pictures for one good — and **hidden
outright when nothing is chosen**, because the previous commodity's icon is a claim about the
wrong good.

Every one of those labels is blanked on the two branches that draw no bars. A label is a
panel-level component and keeps its last text forever unless something writes over it, so
charting one commodity and clicking away otherwise leaves its price scale standing beside "No
commodity chosen".

The plot starts at x=86 rather than 20 to leave the gutter, and the pitch came down 21→20 (bar
17→16) to keep all forty bars inside the panel: `86 + 40 * 20 = 886` against a content edge at
900. Those five numbers live in **both** `gen_exchange_ui.py` and the Lua, which share nothing —
the XML lays the bars out at build time and the Lua moves and resizes every one of them at
runtime from its own copies. `check_chart_geometry()` pins them across the two files; before it,
nothing but a comment connected them, and a one-pixel disagreement walks the fortieth bar off
the end of the plot in silence.

**Tooltips are set at runtime, not as `componentleveltooltip` in the XML**, because cells are
reused between modes: `row_price` is a gold price in Trade, a percentage in Stats and an
offering cost (or a pending tithe's amount) in Offerings, so one static attribute cannot be true in
all three. The column tooltips in `EX.TIPS` stay under 60 characters (`EX.TIP_MAX`). CA's
`Title||Body` split does work through `SetTooltipText`: the Buy refusal, the Offerings button,
the Held cell and the HUD opener all set one at runtime, and they render. The rule that bites is the
one `EX.apply_tips` keeps: there must be literal text in front of `||`, or the pipes are drawn.

**Footers.** Two lines each, split by meaning rather than by length: line 1 is your position,
line 2 is the world. Trade's line 2 carries the appetite readout —
`World at war: N%. Wanted: … Unwanted: …` — and Houses' carries the guild line. Both cap
their clause lists at two names: the footer is one 880px component at the 1600x900 size (it widens with the panel, so that size stays the binding case) and the engine does not wrap,
so three of the longest display names overruns the box and the fitter amputates mid-list.
`check_footer_bounds()` measures the real worst case.

**Line 1 is `Treasury: N  Worth: Ng  Rent: -Ng` on Trade** and
`Treasury: N  Worth: Ng  Dividends: +Ng per turn` on Houses. `Worth` is `EX.holdings_value()`,
added 2026-09-09 and **the only number anywhere that adds the position up** — every other view
tells the player what they hold of one thing, so a player with goods in ten markets and paper in
four houses had to total it on paper. Three things about it are load-bearing and each is pinned
by `check_holdings`:

- **It marks at `EX.sell_price`, not `EX.price`.** A book at the mid price is not money: the
  spread is 10% at default and a hostile house widens it, so a mid-priced total overstates the
  liquidation by exactly what the market takes on the way out. This is what the Sell buttons
  would actually pay.
- **It divides by `EX.lot(res)`.** A price is per lot and a holding is per unit — the same
  mismatch that paid the dividend five times over (100 shares cost 20,000 gold and paid 2,000 a
  turn, measured 2026-09-07).
- **It floors per instrument, not once at the end**, so the total cannot disagree with the
  column above it by a gold. The harness board is deliberately two rungs off neutral, where a
  lot sells for 1089 and a unit is 108.9: at the neutral rung everything divides evenly and the
  two arithmetics agree, and the mutant for this survived the whole suite on that board.

A delisted house counts for nothing — its row disables both buttons, so its paper cannot be
sold at all — and it is skipped explicitly rather than trusted to hold zero shares, because
`EX.shares_held` is rebuilt from a save that may predate the delist. **The same number on both
views, under the same name**: a "Worth" meaning goods on one tab and paper on the next is the
Supply/Regions mistake with a different label. The guide's page 2 defines it, because a
sell-side figure read as a buy-side one looks like the spread has eaten the player's money.

Two spaces separate the clauses rather than four; that is where the room for `Worth` came from.
Line 1's worst case is 115 characters against a budget of 118.

Sorting: click any header. The panel closes at `FactionTurnEnd` and the button is gated to the
player's own turn.

**Greyed means drawn grey** (2026-09-25). `SetDisabled` only stops the click. CA: "Disabled
uicomponents do not respond to mouse clicks but still respond to the mouse cursor". The look
comes from a component's states, and none of this mod's buttons has an inactive one. So every
disabled button drew exactly like a live one: "No offer", the tab you are on, the page arrows,
a Sell with nothing held, and the opener during other factions' turns.

`EX.set_off(c, off)` disables the button and applies CA's documented `set_greyscale_t0` shader
("Greyscale & Alpha") to all states and the text, with `ShaderVarsSet(1, 0.6, 0, 0, true,
true)`, so hovering does not bring the colour back. `normal_t0` clears it. The shader calls are
`pcall`'d, so a refusal cannot take a refresh down.

**It is the only `SetDisabled` in the file.** A static check fails on any other call, and the
layout harness's shade audit asserts that every disabled component wears the greyscale on all
states and no enabled one does. The route not taken is CA's own, `SetState("inactive")` against
an authored inactive state (46 sites in CA's scripts), which needs a new state per button in
`gen_exchange_ui.py`.

**Unconfirmed in play.** No CA script uses `set_greyscale_t0`, and a pcall'd shader leaves no
log line either way. If it draws nothing, the inactive-state route is next.

The standing-order ledger's Cancel carries its own tooltip, `EX.TIP_CANCEL`, rather than the
Buy button's.

### Trade page 2's ticket

Under the chart, in the dead space between `chart_note` (y 480) and the footers, sit the eleven
`EX.TICKET_CELLS`: `ord_side`, `ord_cmp`, `ord_down`, `ord_price`, `ord_up`, `ord_place`,
`ord_qty_down`, `ord_qty`, `ord_qty_up`, `ord_cost`, `ord_standing`. Eight are interactive — the
two toggles, the two rung steppers, the two amount steppers, the amount and Place — and three
are read-only: the rung's resolved price, the cost line, and a line of this instrument's own
standing orders.

`EX.ord_side`, `EX.ord_cmp` and `EX.ord_rung` are **session state, never saved**, the same rule
`EX.selected` and `EX.trade_page` already follow — a half-composed ticket need not survive a
reload. `ord_rung` re-seeds from the instrument's own current rung every time a row is selected
for the chart, so switching commodities never carries yesterday's target onto today's good. All
eleven blank and hide together with nothing selected, for the same reason the chart's own icon
does: the previous commodity's ticket is a claim about the wrong instrument.

Placing runs `EX.place_order_check` first — the same four-check dry run `EX.place_order` itself
makes — so the ticket can print "You hold 12 orders. Cancel one first." locally, instead of
sending an order over the network for the op to refuse right back for the identical reason. The
target is always a rung, 1..42, never the gold `EX.price_at` displays next to it — comparing
resolved gold would compare float32s, and `[[wh3-lua-is-single-precision-float]]` (§7.1 has the
measured case: `30 * 1.05` reading back as 31.4999985) is what a .5 rounding boundary does to
one of those. Scope is `EX.orderable`:
the 17 commodities plus the two Layer 2 rows, because the ticket is only ever reached by
selecting a row for the chart and the chart never selects a house.

### The amount

`EX.amount` is one number reached from two clusters. `[-] Amount x5 [+]` sits in the Trade
list's header band at x676..866, in the 232px right of `hdr_hold` and directly above the rows'
own Buy and Sell columns (which start at x654); `[-] Amount 50 [+]` sits on the ticket right of
Place, with the cost line under it. The middle button cycles the `EX.AMOUNTS` ladder — **1, 5,
10, 25** — and the two steppers move **one lot per click**, so a size the ladder does not carry
(20 was the one the player asked for) is still reachable. Both surfaces read and write the same
`EX.amount`, so the size a Buy click moves and the size Place bakes into a new standing order
can never disagree.

**A LOT IS NOT A UNIT, AND THE TWO LABELS DIFFER ON PURPOSE.** `EX.LOT_SIZE` is 10 for a
commodity, `EX.L2_LOT_SIZE` is 100 for Armaments and Raw Materials, and `EX.HOUSE_LOT_SIZE` is
5 for a house share — so "x5" means 50 of one thing and 500 of another, and the multiplier
alone never says how much of anything is being bought. Reported from a screenshot 2026-09-11:
an `Amount x5` on Marble that moved 50 Marble for 2,565 gold with neither number anywhere on
the panel.

Where the units can be stated, they are:

| Surface | Label | Why |
|---|---|---|
| Trade list header | `Amount x5` | It governs 19 instruments at three different lot sizes at once. A unit count here would be wrong on the two Layer 2 rows. |
| Each row's Buy / Sell | `Buy 50`, `Buy 500` | One row is one instrument with one lot size, so this is the one place the count is never ambiguous — and it is the button that does the thing. |
| The ticket's amount | `Amount 50` | `EX.selected` is known, so `EX.amount_units` can multiply by that instrument's own lot. |
| The ticket's cost line | `50 Marble - 2565g` | `EX.amount_line`: the **side's** price (`EX.order_price`, never the mid) at the rung the ticket is set to, times the lots. |

The cost line is a straight multiply rather than a walk of the counterparty book, so it is a
**floor on a buy and a ceiling on a sell** — the honest direction for a number shown before the
money moves. The 25th lot really does cost more than the first.

Measured need, 2026-09-11, one campaign turn: 25 separate Buy clicks on Salt at 3,797 gold,
plus four at 3,452 and four at 3,138. A market whose only size control is the mouse is not a
market.

**A ladder, not a stepper.** The stepper idiom already on the ticket (`ord_down` / `ord_up`)
takes two components and one click per step; twenty-five lots would be twenty-four clicks to
set up, which is the problem rather than the fix. Four rungs cycle on a single button, and
`EX.cycle_amount` reads the *current value* out of the ladder rather than tracking an index, so
a hand-set or stale amount that is not on the ladder lands back on the first rung instead of
sticking.

**N lots is N real trades**, never one trade of N lots. `EX.bulk_trade` calls `EX.apply_trade`
in a loop, so the price walk, the hostility markup, the counterparty selection and the book
drawdown are the ones twenty-five clicks would have produced — a bulk path with its own
arithmetic would be a second pricing model to keep in agreement with the first. It **stops at
the first refusal**: twenty-five attempts against an empty treasury is twenty-five identical
"cannot afford" lines and twenty-five counterparty walks for nothing. Whatever filled before
the refusal stands. The consequence a stub cannot show is that the 25th lot does not cost what
the first one did.

**One Log line per click, not per lot** (2026-09-25). Twenty-five per-lot lines pushed a fifth
of the 120-line Log out in one click. For a click of more than one lot, `EX.bulk_trade` sets
`EX.bulk = { gold, units }`. `EX.apply_trade_held` then adds each fill to it instead of
logging, and `EX.log_bulk` writes the whole click once: "Bought N for Gg in 25 lots." or,
stopped early, "Bought N for Gg, 7 of 25 lots. Not enough gold.", with the markup sentence
after. A click that filled nothing writes the refusal alone.

`EX.bulk` is cleared on every exit, an error included. Left set, every later trade would go
silent. It is **not** per-player state and must never be saved: it lives inside one synchronous
`EX.bulk_trade` call. Deals (`EX.accept_deal`) and standing-order fills (`EX.fill_orders`) do
not set it and still log per lot.

**TWO WAYS IT SHIPPED BROKEN, 2026-09-11, and both are now checked.** First, `btn_amount` was
wired into `EX.click_dispatch` and *not* into the `ComponentLClickUp` listener's condition. That
condition is a name whitelist and it is the real wiring: the button drew, lit on hover, carried
its tooltip and did nothing at all, with no error and no log line, because the click was never
dispatched to us. `check_click_filter` now asserts every literal name the dispatch handles is
also in the filter. Second, `refresh_panel` wrote the label unconditionally — and `set_text`
calls `SetVisible(true)`, so it re-showed the button on every view `EX.layout` had just hidden
it on, drawn across the Ownership view's Cartel premium header. `EX.in_layout` guards the write
now, and `check_panel_cell_shows` refuses an unguarded `set_text` to any cell that is not in
every panel layout. Neither fault was reachable from a harness: the filter is an anonymous
function behind a real listener, and the layout harness stubs `EX.refresh_panel` to a no-op.

`EX.amount` itself is **session state, never saved**, like `EX.ord_side` and `EX.selected`. The
size a standing ORDER carries is different: that one is saved, on the order, as a fifth field.
`EX.clamp_lots` guards every way in — it is reached from a network payload and from a save —
flooring fractions, rejecting zero, negatives and non-numbers to 1, and capping at the ladder's
top. A **four-field record is a pre-amount save** and loads as one lot; refusing it would empty
a live campaign's ledger on the first load after this build, and defaulting it high would
silently resize every order the player already holds.

A fill that runs out of gold part way **shrinks and stands**: `o.qty` becomes the remainder and
the Log reads "Order part-filled. 3 of 5 lots." Dropping the order would discard a size the
player chose; keeping it whole would buy more than they asked for next turn.

### Trade's ledger

The ledger is `EX.trade_pages()`'s `"orders"` entry — page 3 when the chart is also on, page 2
when the chart alone is switched off (see above). One row per **standing order**, not per
instrument: a ladder puts two orders on one commodity, and every other row pool in this file is
one component per instrument (`EX.row` keys on `EX.short(res)`), which would collide the moment
a ladder existed. So the ledger gets its own fixed pool instead — `EX.ORDER_MAX` (12) row
components, created once at `EX.build_panel` time as `..._ord1` through `..._ord12` — and
`EX.mode_instruments`'s `EX.on_orders()` branch hands out synthetic `"ord1".."ordN"` keys, one
per **list position** rather than per resource, so a three-rung ladder draws three distinct rows
instead of colliding on one. `EX.order_of_row` turns a component id back into the order it names
by parsing the trailing digits off `..._ordN` — a full match, not a prefix, so no real
instrument's row component can take this path by coincidence.

Columns: `icon` and `row_name` are the instrument's; `row_trend` prints the order sentence ("Buy
at or below 1,240"); `row_price` is the price now; `btn_buy` is relabelled **Cancel**, and
`btn_sell` is deliberately not placed. Same idiom the Offerings view already established
(`btn_buy` reused as "Sacrifice"), and for the same reason: the click handler branches on which
view it is in, so a placed Sell button over a Cancel column is exactly the fault
`gen_exchange_ui.py`'s existing Offerings-view assertion exists to catch — extending it to this
view is owed, not yet done.

Cancelling sends the packed order over the network (`zx1|ordx|<packed>`), never a list index —
see §18. A fill never draws through this row at all: it happens inside the turn round, and the
ledger simply stops showing a row that is no longer in `EX.orders` the next time the panel opens.

### The Deals page

The sixth tab, since 2026-09-16. Each turn a few world-tier actors post a one-turn offer to the
player, and it is the one place this mod asks the engine's own AI a question and obeys the
answer.

**Posting** - `EX.post_deals`, turn step 10a, after the reprice, so a deal is quoted off the
price the Trade view shows (a deal moves no market, so there is no circularity to avoid). For
every non-human actor and commodity: a **buy** candidate if its desire is above 0 and its scanned
treasury covers one lot, always for one lot; otherwise a **sell** candidate if it has anything
sellable, for `min(sellable, world_trade_max)` lots. Candidates sort by the **strength** of
desire (`math.abs` - on the raw value every buyer outranks every producer, whose desire for its
own good is negative, and the sell side never appears), then by
`EX.key_hash(faction .. res .. turn)`, so tied buyers rotate between turns instead of the
alphabetically first faction taking a slot for the whole campaign, then by `faction/res` as a
collision backstop. One deal per actor, and each faction is asked once:

    score, can_issue = cm:cai_evaluate_quick_deal_action(mine, them, "diplomatic_option_trade_agreement")

**`(mine, them)`: the player proposes; the AI is the target whose acceptance is scored.** CA's doc
text ("accepted by the target faction") and all six of CA's call sites agree. Both arguments are
faction **interfaces**, and the return order is `score, can_issue`. It shipped backwards first,
and the first mutation round "confirmed" the inverted order because a mutation table only pins
whatever baseline it is given. A deal posts on `can_issue and score > 0`, up to `deal_max` (3);
a thrown error is a refusal, never consent.

**Priced in the player's favour both ways.** A buyer pays `floor(price x (100 + deal_edge) / 100)`
for what you sell it, **capped at `EX.buy_price`** (2026-09-30: above that the lot could be bought
on the Trade view and sold straight in, a free round trip - §17); a seller takes
`floor(price x (100 - deal_edge) / 100)` for what you buy. `deal_edge` is 6 at default, so on a
calm board, where the buy price is the market, a buy deal reads +0%. "Buys" and "Sells" on a row are the actor's verbs; you do the
opposite.

**The list is rebuilt every turn, which IS the expiry.** Saved per player (`zharr_deals`) only so
a reload mid-turn shows the page it showed; never reposted on the load path, which would re-roll
it.

**Taking one** - `EX.accept_deal(i)`, sent as the list index (`zx1|deal|<i>`, §18). It
settles lot by lot through `EX.apply_trade(res, is_buy, px, faction)`: `unit_px` fixes the agreed
price and `only` makes the named faction the counterparty (§5). No hostility markup applies
and the Log line carries no markup sentence. The actor's scanned treasury is re-read (`poor` if it
can no longer pay for every lot); the price is not. It stops at the first refusal, and any
settlement consumes the deal.

**The row**: Faction, Offer (a sentence - "Buys 3 lots of Iron"), Per lot, vs market (signed,
rounded away from zero on a half), Total, and Take (`btn_buy` reused, as Cancel and Sacrifice
are). On a sell deal the button asks `EX.buy_refusal` and shows its label and reason; selling into
a deal stays open with the market shut, the same asymmetry as every other row. All five strings
and the button state come from `EX.deal_cells`, and the row from the top-level
`EX.draw_deal_row`, because nothing offline can run `EX.refresh_panel`. The row pool is
`deal_max` components (`..._dl1`, ...) created once at `EX.build_panel`, keyed by position, since
two deals can name one good.

**The footer says why a page is empty**: switched off; "Every faction in a position to deal
turned you down this turn" (something could issue, nothing scored above 0); or "No faction on the
map is in a position to deal with you this turn" (nothing could issue) - which is the whole reason
`EX.deal_ok` returns the two values separately. The switch is read live. The tab is never locked;
with `ai_deals` off it draws nothing and says so. The HUD opener's tooltip counts waiting deals.

**Independent of `ai_world`.** `EX.post_deals` never reads it and a named counterparty skips
`EX.world_counterparty`'s gate, so with the world tier switched off the page still posts and a
taken deal still moves the actor's book. The `ai_world` MCT tooltip says so since 2026-09-28.

### The Contracts page (forward contracts)

The Deals tab's Contracts sub-tab since 2026-09-30 (page 2 of the arrows from 09-29).
A **contract** is a
price agreed now for goods delivered later: "Buys 1 lot of Iron at 1060g, in 7 turns". Taking one
moves no gold and no goods. On the delivery turn the lots trade at the agreed price with that
faction, and **every lot that cannot be delivered, for any reason, is settled in gold** at the gap
to the market price on the day. There is no walking away, for either side.

**Posting** - the same pass as the deals, inside `EX.post_deals`, walking the same ranked
candidate list **after** the deal slots are full, so no faction is on both lists and a contract
never takes a deal's slot. Up to `fwd_max` (2) offers. Two filters a deal does not have: a
faction **at war** with the player is skipped, and so is a price above **`world_cash_max`**
(`EX.pay_actor` clamps every AI payment to it, so the faction could never settle the lot). Neither
marks the faction as asked, because the price test is per commodity. Lots and price exactly as a
deal (`deal_edge`, in the player's favour, a buyer capped at the buy price). Length: `lo + key_hash(fac .. res .. turn) %
(fwd_turns - lo + 1)`, `lo = ceil(fwd_turns / 2)` - 5 to 10 turns at the default, and the same on
every machine. Gated on `ai_forwards`; `ai_deals` and `ai_forwards` are independent.

**Taking** - `EX.accept_forward(k)`, op `fwd` with the offer's index, the Deals op's shape.
Refusals in this order: `nodeal` (bad index), `gone` (the faction is no longer an actor), `full`
(six open, `EX.FWD_OPEN_MAX`); a refusal leaves the offer on the page. Otherwise the contract is
appended with `at = turn + due`, the offer leaves the page, both lists are saved.

**Delivery** - `EX.deliver_forwards`, turn step 10a, per human, each due contract in list order
inside its own `pcall`, under `EX.filling` so it shares the round's one reprice:

1. faction gone (`EX.house_gone`) - cancelled, no gold;
2. at war - no goods move; every lot settles in gold;
3. otherwise lot by lot through `EX.apply_trade(res, is_buy, px, faction)`, the named-faction route
   with no markup, stopping at the first refusal;
4. every lot not delivered: per lot the player is owed `M - px` on a purchase and `px - M` on a
   sale (`M = EX.price(res)`). Owed to the player, the faction pays through `EX.pay_actor`, clamped
   to its scanned treasury, and the player is credited **what was actually taken**; the scanned
   treasury is spent down as it goes. Owed by the player, the player pays **what the faction is
   credited** - the whole gap, unless one lot's gap passes `world_cash_max`, the per-payment limit
   `EX.pay_actor` clamps to (until the logic sweep of 2026-09-29 the player paid in full and the
   excess reached nobody). The treasury may go below zero and CA's bankruptcy applies. With
   `ai_gold` off the faction's leg is notional and the player's moves in full.

An attempted contract always leaves the list, success or error: delivered at most once beats
delivered twice, and an error settles no gold for a trade in an unknown state. Delivery ignores
`ai_forwards` - the switch stops new offers, and an open contract is an obligation.

**The page** keeps the Deals layout. `EX.view()` answers `"contracts"`, so the headers and tips
are their own: Faction, Contract, Per lot, vs market, **Due** (where the deals page has Total -
"in 10 turns" does not fit in the sentence, and the row has no sixth column). Offers first, in the
faction's verb, with Take (greyed "Full" at six open); then the open contracts in the **player's**
verb ("Sell 1 lot of Iron"), with the button as a greyed status: Ready (the goods or the gold are
there today), Short, or At war. Cells from `EX.fwd_cells(k)`, the row from `EX.draw_fwd_row`, one
pool `..._fw1` to `..._fw<fwd_max + 6>` by position. `EX.deals_pages()` lists the page while
`ai_forwards` is on **or any contract is open**, so a contract that is going to settle gold never
becomes invisible. Footer: offers and open contracts counted, and "Lots you cannot deliver settle
in gold at the market price."; the deals list's second footer line points at the Contracts tab
while offers wait there. The opener's tooltip says when a contract delivers next turn. Guide page 2: "Contract" and
"Short". The Log carries taken, delivered, settled and cancelled lines, the faction named at draw
time (`EX.log_add("", ..., faction)`), never at turn start.

### Themed funds (2026-09-30)

The Index sub-tab is now
**Funds**. The index below is fund #1; the engine is the index's own, generalised: `EX.fund_*` over
a fund definition `F`, the `EX.index_*` names kept only where something still calls them.

| Race | Goods fund 1 | Goods fund 2 | House fund |
|---|---|---|---|
| Chaos Dwarfs | Furnace Stock (Iron, Timber, Salt) | Hashut's Hoard (Golden Idols, Gemstones, Carved Obsidian) | Northern Warbands (Norsca, Warriors of Chaos) |
| Empire | Reikland Staples (Iron, Salt, Wine) | Marienburg Luxuries (Spices, Dyes, Gemstones) | Karaz Ankor Holds (Dwarfs) |
| Cathay | Caravan Goods (Spices, Tusks, Dyes) | Jade Court Treasures (Gemstones, Marble, Golden Idols) | Kislev Trade (Kislev) |
| Skaven | Clan Supplies (Iron, Salt, Medicinal Plants) | Scavenged Goods (Elven Trinkets, Furs, Timber) | none |
| Southern Realms | Condottieri Supply (Iron, Marble, Gemstones) | Arabyan Imports (Tusks, Dyes, Exotic Animals) | Imperial Neighbours (Empire) |
| Dwarfs | Hold Staples (Dwarf Beer, Iron, Salt) | Ancestor Gold (Gemstones, Golden Idols, Marble) | Imperial Allies (Empire) |
| High Elves | Ulthuan Luxuries (Gemstones, Spices, Wine) | Far Colonies (Tusks, Dyes, Exotic Animals) | Old World Partners (Empire) |
| Dark Elves | Black Ark Stores (Iron, Timber, Dyes) | Corsair Plunder (Golden Idols, Gemstones, Elven Trinkets) | Zharr-Naggrund Trade (Chaos Dwarfs) |

- **Derived funds.** The 19 other cultures in `EX.CULTURE_WANTS` get one goods fund,
  "<`EX.WANTS_NAME`> Wants", over their three highest positive appetites, ties by key. Cultures
  outside `EX.CULTURE_WANTS` keep the index only, and their page reads as it always did.
- **A house fund** is the index over other cultures' listed houses, dividends included. Those houses
  are listed only through `EX.BLOC`, so a house fund needs `cross_bloc` on, and
  `check_fund_catalogue` fails the build on any house fund whose cultures can never be listed -
  the first Dark Elf fund, over the unlisted Vampire Coast, was that.
- **A goods fund** holds the goods that are produced (`EX.unavailable` false). One nobody makes
  leaves at its price, and rejoins when made again, the level unmoved both times. It reads at
  `EX.settled_price` - the last turn-end rung, from `EX.deep` - while unmade, because a load's
  rescan has already repriced it to the MULT_MAX clamp. Every good gone keeps the state at
  `d = 0` with `s.last` as the level: holders keep their units and can sell. No dividend, no rent.
- **The switch** `funds` (MCT "Themed funds", on, frozen with the other switches). Off: none
  created or offered; one the save already holds stays listed with Buy "Off" and Sell open. No
  themed fund is made on load before the snapshot exists (a new campaign's first tick).
- **Page**: the fund rows (`_idx`, `_fd2`.. `_fd4`), then the selected fund's members. A click on
  a fund's name selects it (`EX.fund_sel`, view state, back to the index each time the tab is
  entered); while there is a choice the selected name is drawn `[[col:yellow]]` (CA's most used
  colour tag). The name's tooltip lists the holdings. A fund row's Share is its member count ("21
  houses", "3 goods"), not 100%. Footer line 1 is the selected fund - with a choice it opens
  "Listing <fund>: <what it holds>." (`EX.fund_listing`: a house fund's count and peoples, a goods
  fund's names in share order via `EX.name_list`), without one it keeps the index's old line -
  and line 2 its rule and the cut count. `row_supply` is 64 wide (54 before) to fit "21 houses".
- **Save and MP**: `zharr_fund_<id>` world, `zharr_fu_<id>` per player (`EX.fund_units`, sliced).
  The `idx` op carries `b<n>@<id>`; an id that is not one of the sender's funds is refused.

### The Index page (index fund)

The Houses tab's Funds sub-tab since 2026-09-30 (Index until the themed funds; the page after the
house list from 09-29). The index is now fund #1 of that page - see "Themed funds" above.
One instrument over **your
own culture's listed houses** (`EX.culture_of(EX.who())`, never `EX.HOUSE_CULTURE`, which is the
local client's): not delisted, not gone, at least two of them, or there is no index.

**Level** `L = S / D`: `S` is the sum of the members' lot prices (`EX.index_weight`), `D` a divisor
kept in world state. Read live, so it moves with every share trade during the turn exactly as the
member rows do. A new index opens with `D` = the member count, at their average lot price.

- **A dead member** reads at `windup x price` the moment it is dead (`EX.index_dead`: delisted or
  gone), not at the next round. At its living price the index would sell a corpse at full value
  for the rest of the turn. The buyout premium never applies: conquest cannot be farmed through
  the index, and one culture's index is one number for every player.
- **Removals**, turn step 7b (`EX.index_sync(false)`): after `check_delistings`, while a dead house
  is still at the living price its share settlement used, before `apply_prices` collapses it. The
  dead leave at the wind-up rate, a member that left alive at full price, and `D` is re-cut to
  `alive / L1` so the level after is the level the dead left. A death therefore lowers the level
  by exactly its weight x (1 - windup) and never raises it. Each death is logged, with its fall,
  to every human of that culture, the house named at draw time.
- **Every member gone ends the index**: its holders are paid `floor(units x L / 5)` (the level, no
  spread, as a share settlement pays) and the state is dropped. A divisor cannot carry a level over
  an empty list, and restarting at the next houses' average would hand a free rise to every unit
  still held. A new index opens fresh when two houses exist again. **This departs from the spec**,
  which kept the state.
- **Joins**, turn step 10c (`EX.index_sync(true)`): after `apply_prices`, so a new house joins at
  its fresh price, not its placeholder. `D' = D + p_new / L`, so the level does not move. The join
  pass also writes `prev` and `last`, the two levels the Trend column compares.

**Trading**: a lot is 5 units. Buy `floor(L + 0.5)`, sell `floor(L x (1 - spread))`, no hostility
markup and no pressure, so buying the index moves no member. Buy is refused with no index ("No
index") and under the war lock ("Closed"); selling is always open, down to the units held. Gold to
and from nobody - the share rule. Op `idx`, argument `b<n>` or `s<n>`, applied as the sender with
`EX.clamp_lots`. Units are per player (`EX.index_units`, `zharr_idxu`, in `EX.SLICE_SCALARS`).
The footer's Worth (`EX.holdings_value`) counts them at the sell price.

**Dividend** - beside `pay_dividends`, per human: the total is floored ONCE, `floor(units x
sum(EX.dividend(h)) / D)` - the number the Div column promises, `5 x sum / D` a lot - and split
across the members by largest remainder, ties by key. Each member pays its part through
`EX.pay_house` (clamped to its treasury, as a share dividend is) and the player is credited what
moved; `ai_gold` off, the player is paid in full. War members pay nothing (`EX.dividend` is 0) and
so do dead ones. **Also a departure from the spec**, which floored per member: at 21 houses each
dropped most of a gold and ten units were paid 21g against the 40g the row showed.

**The page** keeps the Houses layouts. `EX.view()` answers `"index"`; headers Name, Price, Div,
Share, Trend, Last 12 turns, Held; no sort. Row 1 is `..._idx`, created in `EX.build_panel`: "Index
of N houses", buy price and dividend per lot, 100%, trend, no icon, no sparkline, units and "+Ng"
a turn, Buy/Sell with the amount (Share now reads "N houses", see "Themed funds"). Rows 2.. are the members, heaviest first, on their own house row
components with **both buttons hidden** - a member is traded on the list pages, and a live button
here would read as buying the index - capped at `EX.MAX_ROWS - 1`; footer 2 names how many were
cut. Title "<race name>: Funds". Cells from `EX.fund_cells` / `EX.fund_member_cells`, rows from
`EX.draw_fund_row` / `EX.draw_fund_member` (the `EX.draw_index_*` names are wrappers), footers from
`EX.fund_footer`. Guide page 2 has a "Fund" line.

**The page is `EX.house_page == EX.HOUSE_INDEX_PAGE` (-1)**, not "one past the last list page".
`EX.on_index` feeds `EX.view`, and the house list's own sort reads `EX.view` through
`EX.sort_fn`, so an `on_index` that counted list pages recursed until the stack ran out - caught by
the first selftest. The sentinel also keeps a player on the index when the list shortens, and every
`EX.house_page = 1` leaves it with nothing else to reset. Not 0: `_nav_harness.lua` pins 0 as an
out-of-range page that clamps to 1. `EX.house_page_at` clamps a list page, which fixes the "3/2"
counter for the Houses tab (§17).

### The Bonds page (war bonds and loans)

The Houses tab's Bonds sub-tab since 2026-09-30 (the last page of the arrows from 09-29).
Houses post the offers;
the player takes one with a button, the contracts shape.

**Which houses**: `EX.bond_houses()` - your own culture's (`EX.culture_of(EX.who())`), not delisted
or gone (`EX.index_dead`), not at war with you (`EX.treaty_tier ~= "war"`), sorted by key so two
machines holding the list in different orders post the same page.

**Posting**, `EX.post_bonds()`, per human, bound, rebuilt every turn; nothing with `ai_bonds` off.

| | Bond issue (you lend) | Loan offer (you borrow) |
|---|---|---|
| who | `faction:at_war()` true | `at_war()` false |
| order | `EX.price` ascending, weakest first | treasury descending, richest first |
| how many | up to `bond_max` | up to `bond_max` |
| amount | 1000 x (1 + `key_hash(h .. "|a|" .. turn) % 5`), at most `house_cash_max` | the same, then cut to the largest thousand at most half the treasury; under 1000 is not posted |
| term | `ceil(T/2) + key_hash(h .. "|t|" .. turn) % (T - ceil(T/2) + 1)`, `T` = `bond_turns` | the same |
| a turn | `floor(amount x bond_rate x risk + 0.5)`, risk = neutral lot price / `EX.price(h)` kept to [0.5, 2] | `floor(amount x bond_rate + 0.5)` |

Rounded, not floored: float32 reads 1000 x 0.02 as 19.9999996. The two sets cannot share a house,
so nothing can be borrowed from a house and lent straight back to it.

**Taking**, `EX.accept_bond(k)`, op `bond` with the offer's index, applied as the sender.
Refusals, each leaving the offer on the page: `nodeal`, `gone`, `war` (now at war with you),
`full` (`EX.BOND_OPEN_MAX` = 6 open on that side - the limit is per side), `afford` (a bond over
your treasury), `poor` (a loan the house can no longer fund, `ai_gold` on). A bond moves the amount
from you to the house through `EX.pay_house`; a loan credits you what `EX.pay_house(fac, -amt)`
actually moved (the whole amount with `ai_gold` off), and that is the principal. The position is
`{ side, fac, p, c, at = offer turn + term, late = 0 }`.

**Paying**, `EX.pay_bonds()`, per human, bound, every position in its own `pcall` (an error keeps
the position and stops nothing else), ignoring `ai_bonds` - an open position is an obligation:

1. **The other side is dead**: a bond pays `floor(windup x (p + late))`, from nothing, as a share
   settles, never the buyout premium; a loan falls due at once, `p + late`, paid to nobody. Both
   close. Killing a lender never erases the debt.
2. **At war with you**: nothing, and nothing changes - the payments missed are not built up, and a
   principal that falls due waits for peace.
3. **Maturity**: on the first turn `turn >= at` with `p > 0`, `p` folds into `late`, once.
4. **Due** = `late + c` up to and including turn `at`, then `late` alone. A bond: the house pays
   through `EX.pay_house(fac, -due)`, clamped to its treasury and `house_cash_max`; what it could
   not pay stays as `late` (arrears, earning nothing) and is logged. A loan: you pay what the house
   can take in a turn - `due` in full unless it passes `house_cash_max` - into a negative treasury
   if need be, and the rest waits as `late` (logic sweep, 2026-09-29: the excess used to be
   charged and reach nobody). `ai_gold` off, you pay `due` in full.
5. **Closed** when `turn >= at` and `p` and `late` are both 0.

The player's side is at most two `cm:treasury_mod` calls a turn, one a direction, and one Log line.
With `ai_gold` on every gold you gain on a take or a payment is what a house lost, and the reverse;
the two deaths are the only exceptions.

**The page** uses the Deals tab's layouts (`EX.PANEL_LAYOUT_DEALS` / `EX.ROW_LAYOUT_DEALS`):
headers House, Bond, Per turn, Rate, Due; no sort. Rows `..._bd1` to `..._bd<2 x bond_max + 12>`,
created once in `EX.build_panel`: the offers (issues, then loans), then your bonds, then your
loans (`EX.bond_at`).

| Row | Bond | Per turn | Rate | Due | Button |
|---|---|---|---|---|---|
| issue | Borrows 3000g for 8 turns | +60g | 2.0% | in 8 turns | Lend; greyed Full / No gold |
| loan offer | Lends 2000g for 5 turns | -40g | 2.0% | in 5 turns | Borrow; greyed Full |
| your bond | Owes you 3000g | +60g, `-` after the last payment | 2.0%, `-` once matured | in N turns / next turn / overdue | greyed: Paying, Behind, At war |
| your loan | You owe 2000g | -40g | 2.0% | the same | greyed: Paying, At war |

Only an offer's button sends `bond/<k>`; a status or a name click sends nothing. Footer 1 counts
the offers and each side open, or says new ones are switched off; footer 2 gives the net a turn
(leaving out a position at war with you or past its last payment) and the death rule, or, with
nothing open, what a bond and a loan are. The opener's tooltip adds "Ng of loans falls due at the
start of next turn" - loans only, and not one at war with you. Title "<race name>: Bonds". Guide
page 2 has "Bond" and "Loan" lines. Cells from `EX.bond_cells`, rows from `EX.draw_bond_row`,
footers from `EX.bonds_footer`.

**The Houses tab's extra pages are a list**, `EX.house_extra_pages()`: the index always, bonds
while `ai_bonds` is on or any position is open, each its own sentinel (`EX.HOUSE_INDEX_PAGE` -1,
`EX.HOUSE_BONDS_PAGE` -2). `EX.house_extra()` answers which one is showing without reading the
house list (the recursion above), and reads a sentinel whose page has gone - the bonds switch off
with nothing open - as the last extra page, so the player lands on the index and the counter
agrees.

**The sub-tabs (2026-09-30).** Asked for from play: the index and bonds pages sat at 4/5 and 5/5
behind the arrows and were not found. Three slots, `derpy_chd_ex_sub_1..3`, in the title bar at
x 484/600/716, y 16, 108 wide - after `title_text`'s 400px box, clear of `btn_help` at 838, above
the amount cluster at 46 (`gen_exchange_ui.py` asserts all three). Labelled per view from
`EX.SECTIONS`: Houses | Funds | Bonds, Deals | Contracts. **Slots, not a component per section**,
because the bonds page draws on the Deals layout, so `PANEL_LAYOUT_DEALS` places all three and
`EX.draw_sections` hides the third on Deals. The current section and a locked one are greyed
(`EX.section_locked`: bonds or contracts switched off with none open); a live one's tooltip is
"Label||what is on it". `EX.sub_click` sets `EX.house_page` / `EX.deal_page` from
`EX.SECTION_PAGE`, drops the sort as a tab click does, and is a no-op on the section on screen.
**The arrows now page only the section on screen:** the house list's pages, one on the index and
bonds, one on each Deals section. `EX.page_count` / `EX.page_index` have no Deals branch any more.

### The HUD opener

`derpy_chd_exchange_button.twui.xml`, 48px. It is created on the **UI root** and is never
parented to anything CA lays out. Two earlier anchors lost that fight: a `RadialList` owns its
children's positions, and `MoveTo` never wins against a layout engine. `EX.button_anchor` reads
`resources_bar`, the top resource strip's art, as a **ruler**: the button sits `EX.BUTTON_GAP`
(4px) off its right end, centred on it vertically. A HUD component's position and bounds are
safe to read. Its tooltip and image are not: both hard-crash.

**Placement** starts 1s after the first tick and retries every 2s until it has succeeded once,
up to `EX.PLACE_TRIES` (150, five minutes). The strip slides off the top of the screen for the
intro, cutscenes and end-turn, and reports a real but useless y while it is away. `EX.layout`
(every panel open) and turn start each make one more attempt that never reschedules.

`EX.fit_button(x, y)` is the one refuse-or-clamp rule. A reading within one button of the screen
edge is clamped on. One further out is a bad or mid-animation read and is refused. The
bottom-right `faction_buttons_docker` is a last resort for a CA rename only: a fallback that
resolves to other geometry while the strip is merely still loading is what made the button
teleport.

**It follows the strip's end** (2026-09-27). `resources_bar` is docked Top Center and sizes to
its content, so its right end moves whenever an effect icon or faction widget appears, mid-turn,
with no event for it. Middenland's Drakwald threat bar alone moved it from x 1306 to 1441.
`EX.start_follow` runs `EX.follow_bar` every `EX.FOLLOW_MS` (300ms) on the UI clock
(`cm:repeat_real_callback`, named `zharr_follow_bar`). Each pass is one find, two reads, and a
`MoveTo` only when the answer changed. It does nothing until the button is placed, nothing while
the strip is away, and never follows onto the docker fallback. The Great Guilds' opener runs the
same poll off the same strip, so the pair moves together.

**A second-row placement was built and reverted the same day** at the player's request ("put it
besides the top bar"). It fixed the button under the strip's centre, which does not move. Do
not re-apply it without asking.

**Its tooltip is built at runtime**: `EX.the_name() .. "||" .. EX.TIP_OPEN_BODY`, then
`EX.button_news()`. While either clock is running, the news adds "N deals are waiting on the
Deals tab, gone at the end of this turn." and "<patron> demands N <good> within N turns."
Every placement attempt rewrites it, so it is fresh at turn start and on panel open.
`EX.refresh_panel` also rewrites it through `EX.refresh_button_tip`, so a deal taken or a tithe
paid mid-turn does not leave it announcing something already gone. It is written and never read
back. The XML keeps a race-neutral copy of the body as the fallback before the race binds, and
`check_button_tip` holds the two sentences equal.

It is greyed through `EX.set_off` on every turn but the player's own (`EX.gate_button`: off at
`FactionTurnEnd`, on at turn start). Everything in this subsection is local UI and never crosses
the network.

---

## 13. Settings

### 13.1 Presets

Five: **Easy**, **Default**, **Hard**, **Ultra Capitalism**, **Custom**. The preset owns all 37
numeric knobs *and* the fifteen system switches.

| | easy | default | hard | ultra |
|---|---:|---:|---:|---:|
| `ladder_step` | 1.08 | 1.10 | 1.13 | 1.18 |
| `spread` | 0.08 | 0.10 | 0.16 | 0.25 |
| `sell_floor` | 0.60 | 0.25 | 0.15 | 0.10 |
| `l2_sell` | 0.75 | 0.50 | 0.40 | 0.25 |
| `ai_gain` | 3.0 | 6.0 | 9.0 | 14.0 |
| `ai_max_rungs` | 1 | 2 | 3 | 5 |
| `book_per_rung` | 45 | 30 | 22 | 15 |
| `hostile_max` | 0.10 | 0.25 | 0.40 | 0.60 |
| `guild_close` | 0.90 | 0.60 | 0.45 | 0.30 |
| `div_yield` | 0.04 | 0.02 | 0.03 | 0.05 |
| `buyout_premium` | 1.50 | 1.25 | 1.60 | 2.00 |
| `windup` | 0.75 | 0.50 | 0.30 | 0.15 |
| `demand_first_turn` | 30 | 15 | 10 | 5 |
| `shock_max` | 3 | 6 | 8 | 12 |
| `race_strength` | 0.5 | 1.0 | 1.0 | 1.25 |
| `world_cash_max` | 1,500 | 3,000 | 4,000 | 8,000 |
| `world_trade_max` | 2 | 3 | 3 | 4 |
| `world_gain` | 2.0 | 4.0 | 6.0 | 9.0 |
| `deal_max` | 4 | 3 | 3 | 2 |
| `deal_edge` | 7 | 6 | 4 | 2 |
| `fwd_max` | 3 | 2 | 2 | 1 |
| `fwd_turns` | 10 | 10 | 10 | 10 |
| `bond_max` | 3 | 2 | 2 | 1 |
| `bond_turns` | 10 | 10 | 10 | 10 |
| `bond_rate` | 0.02 | 0.02 | 0.02 | 0.02 |
| `pos_step` | 6 | 4 | 3 | 2 |
| rent / tithe | **off** | on | on | on |
| `world_scarcity` | **off** | on | on | on |

Easy is low **risk**, not low reward: a thin spread, most of a bad stake returned, cheap
storage, a slow and forgiving guild — and shares still paying double the default dividend.

### 13.2 MCT

`script/mct/settings/derpy_chd_zharr_exchange.lua`, generated. MCT loads every `.lua` under
`script/mct/settings/`, so the file only ever runs when MCT is installed and the mod is
functional without it.

The page is titled *Derpy's Grand Trade Exchange* with author `_D3rpyN3wb_` since 2026-09-28
(`m:set_title` / `m:set_author`), matching the Workshop title. The key,
`mct:register_mod("derpy_chd_zharr_exchange")`, is deliberately unchanged: every player's saved
settings are stored under it - see the rename note after §16. The same day's build also stopped
the description counting "seven" system switches, and corrected three tooltips that described
behaviour the code does not have: "Let cultures without markets trade" said other cultures could
still buy their shares (they are absent from `EX.BLOC`, so none can), `ai_world` said only
"fourteen houses" trade when it is off (the guild can be far larger, and Deals keep running), and
`world_bundles` said the War Stocks bundles apply to you (§10.1 - they never do).

Fifteen system switches, 37 sliders across seven sections (Market, Rival houses, Shares, Tithes,
War shocks, Race profile, The world), a difficulty picker, **a Features section** and a debug
section - eleven sections in all.

**The world section and five of the Systems switches came with the World Book.** Sliders:
`world_cash_max` "World trader purse", `world_trade_max` "World trade size", `world_gain`
"World trading weight", `deal_max` "Deals offered per turn", `deal_edge` "Deal edge, per cent",
`pos_step` "War-goods position step". Switches: `ai_stance` "Houses react to your holdings",
`ai_world` "The world trades", `world_scarcity` "Supply can run out", `ai_deals` "Factions offer
you deals", `world_bundles` "Positions supply armies". All eleven are in `ECONOMIC` and frozen
like every economic value, and every gate on them uses `EX.setting`, which fails open -
`EX.opt` answers nil for a key in neither `EX.TUNE_NUM` nor `EX.TUNE_BOOL`, and a feature gated
on nil is silently dead. **A campaign whose snapshot predates a key has no entry for it**, so
`EX.opt` falls through to the live MCT value and that switch is a real mid-campaign toggle for
exactly those saves - which is why `world_bundles` off strips bundles instead of returning early
(§10.1). `deal_max` is also the Deals page's row pool, and `deal_edge` and `pos_step`
bottom out at 1, not 0 - all asserted.

**Forward contracts added three (2026-09-29):** `ai_forwards` "Factions offer you contracts" (on
in every preset), `fwd_max` "Contracts offered per turn" (0-3, which with `EX.FWD_OPEN_MAX` is also
the Contracts page's row pool) and `fwd_turns` "Longest contract, in turns" (4-20). The same build
cut `deal_edge`'s slider maximum from 25 to 10, since a deal above one price step is a free round
trip; a campaign already frozen above 10 keeps its value.

**War bonds added four (2026-09-29):** `ai_bonds` "Houses offer bonds and loans" (on in every
preset; off stops new offers only), `bond_max` "Bond and loan offers per turn" (0-3 a side, which
with `EX.BOND_OPEN_MAX` is also the Bonds page's row pool), `bond_turns` "Longest bond, in turns"
(4-20) and `bond_rate` "Bond payment per turn" (0.01-0.05).

**The Features section holds four kill-switches and two permissions** (`feat_deep_history`,
`feat_demand_shocks`, `feat_appetite_drift`, `feat_orders`, plus `allow_uncommercial` and
`allow_raiders`, which open the Exchange to a culture the lock in §11 keeps out - the permissions
default off and stay off in multiplayer, the opposite of the kill-switches, which is why they
read `EX.lock_allowed` rather than `EX.feature`) and is the one economic-looking thing
that is **not** in `ECONOMIC` and so not locked in a campaign. That is deliberate and it is the
whole difference between these and the fifteen system switches above: a system switch is
snapshotted so a price you were quoted stays the price you are charged, while a kill-switch
exists to be moved *while* a bug is happening — the same argument the debug options carry. In
multiplayer all four are forced on, because reconciling a live model switch across machines is
the MCT race `EX.mp_ignores_mct` already refuses to run.

`feat_orders` came back 2026-09-10 with the feature it gates, in the same commit as its first
real call site — the condition the 2026-09-09 handoff set for `orders`' return after it was
**deleted** rather than shipped disabled (a checkbox for a system that does not exist yet is
worse than no checkbox). It has the same two-reader shape `deep_history` already has, and for the
same reason: `EX.trade_pages` stops the ledger page being *reached*, `EX.fill_orders` stops the
model *running* — a kill-switch thrown mid-bug has to stop both halves, not just the one on
screen. See §12 and §14.

`check_features` derives its key set from `EX.FEATURE_DEFAULT` — the table `EX.feature` actually
reads — so a switch the script knows about that MCT never registers is a build failure, and so
is one MCT registers that the script has no default for. It also asserts a **call site** for
each, on the comment-stripped code: a key named only in the paragraph explaining why it exists
is exactly how `orders` and `deep_history` read as wired for a week. And `check_mct` now asserts
that every `set_assigned_section` names a section `add_new_section` creates, in both directions
— an option assigned to a section that was never made is registered, defaulted, and nowhere the
player can reach it.

**Every option has a title of its own, and no option key has moved.** Two culture-lock
checkboxes shipped under one title, "Let raider cultures trade", so the page showed two
identical boxes. The uncommercial one has been "Let cultures without markets trade" since
2026-09-25, and `check_mct` now refuses two options that share a title.

The 2026-09-26 plain-language pass renamed labels and tooltips only:

- "AI traders" is now "Rival houses trade";
- "Trade shares across your bloc" is now "Trade shares across trading partners";
- "Houses react to your book" is now "Houses react to your holdings";
- "Book size per step" is now "Holdings per price step";
- each "... cap" slider is now "... limit" ("Shock cap" is "Shock step limit");
- the "AI houses" section is now "Rival houses".

The first field of each `MCT_OPTIONS` / `TUNABLES` / `CULTURE_LOCKS` tuple is the key every
player's saved settings are stored under, so a rename is label-only by construction.

**Every economic value is frozen into the save at the first `FactionTurnStart`.** MCT's own
campaign gating (`mct_option:set_context_specific`) is dead code, so the snapshot is the lock.
The debug half is deliberately **not** snapshotted — the log level has to be movable while a bug
is happening, which is the whole reason it exists.

Resolution order: `constant default -> preset -> MCT custom -> snapshot`, then the race factor
on top.

The default column in `TUNABLES` is a **copy** and is asserted against the Lua, not the source of
anything: `EX.opt_default` reads the constant in the campaign script, so the constant stays the
one place a default is written. Min/max/step must contain every preset value **and put it on the
grid** — a preset naming a value the slider cannot land on is a setting the player can never
reproduce by hand.

### 13.3 Debug

Four log levels (off / errors only / normal / verbose) across seven categories: turn, trade,
price, house, demand, shock, ui. Plus two buttons, *Dump state to log* and *Re-run supply scan* (`dump_state` / `dump_supply`), fired as
custom events from the MCT file because it cannot see `EX` directly.

---

## 14. Turn order

`FactionTurnStart`, and the order is load-bearing at more points than it used to be. The World
Book added three, each asserted off `EX.turn_round`'s source by `check_lua_books`: `step_world`
between `step_books` and `apply_prices`, `post_deals` after `apply_prices`, and `apply_positions`
after `apply_trade_income`:

```
 0  forget_humans()     a new round is a new human list: a player can drop, resume or be confederated away
 1  snapshot()          FIRST - everything below reads a knob
 2  free_guild()        a new turn is new diplomacy; no stance memo outlives a turn
 3  check_demand()      punish an unpaid tithe before the altar asks again
 4  decay_pressure()
 5  rescan()            supply, owners, culture shares, war index, house regions
 6  share_shocks()      AFTER rescan, which is what measures the shares; before pricing
 7  check_delistings()  BEFORE apply_prices - a dead house must settle at its living price
 7b index_sync(false)   the index's removals, at that same living price (§12, The Index page)
 8  check_standing_sign()
 9  step_books()        AFTER delisting (dead houses have left the guild), BEFORE pricing
 9a step_world()        the world tier (§9.1). AFTER step_books, BEFORE apply_prices -
                        actors trade at last turn's prices and the reprice runs on the result.
                        Outside with_player: the world has no reference human. Prunes each
                        confirmed-dead faction's book, then pairs every commodity's buyers with
                        its sellers. No accrual step: what an actor can sell is re-derived from
                        its land on every call (EX.world_capacity); EX.accrue_world_stock is
                        withdrawn, not merely unused.
10  apply_prices()
10c index_sync(true)    the index's joins, at the fresh price; records the index's trend
    fill_factions = {}  reset HERE, above 10a, so a contract delivery joins the one reprice
10a deliver_all_forwards()  forward contracts due this turn (§12). PER HUMAN. AFTER apply_prices,
                        so a lot settled in gold settles at the price the panel shows; BEFORE the
                        deals, so the offers see the treasuries the deliveries left
10b post_all_deals()    the Deals page and the contract offers. AFTER apply_prices, so a deal is
                        quoted off the price step the Trade view shows. PER HUMAN: EX.post_deals
                        inside EX.with_player for each (2026-09-29; it was called once, unbound - §18)
10d post_all_bonds()    the Bonds page's offers. PER HUMAN. AFTER apply_prices, since a bond's
                        payment reads the house's price, and after the deliveries, since a loan
                        offer reads the treasury they left
 9b fill_orders()       PER HUMAN. AFTER apply_prices, so a limit tests the number the panel
                        shows; BEFORE remember_all, so the bar this turn records is the price
                        the fill got rather than the price the fill caused
11  remember_all()      AFTER pricing - one sparkline and one chart bar per TURN, not per reprice
11b build_world_log()   AFTER step_books, which fills EX.book_flow. BUILDS only, writes nothing
12  announce_shocks()   at full strength, before the decay - and logs the shock
13  decay_shocks()      AFTER pricing - a raze during the AI round prices at full strength
14  save_shocked()
15  apply_trade_income()
15a apply_positions()   WORLD, the sibling bundle family, beside it on purpose; also runs on the
                        load path
15b promote_stances()   PER HUMAN, through its own with_player loop; ai_stance off = no calls
16  apply_stockpiles()  a tithe or raid may have crossed a tier boundary
17  charge_carry()      on the same holding the tier was just read from
18  pay_dividends()     AFTER delisting - a house dying this turn must not also be paid
    pay_index_dividends()  right after it, in the same per-human block
    pay_bonds()            right after that: payments, maturities, deaths (§12, The Bonds page)
19  maybe_demand()
19b flush_world_log()   LAST in the player block, so the world's lines sit above this
                        player's own rent and dividends once the log reverses them
```

The label is the shipped code's own — `EX.turn_round`'s comment calls this step "9b" rather than
renumbering everything from `apply_prices` down, and it is placed here, after row 10, because the
table is in **execution order** and that is where it actually runs.
`0`, `10b`, `15a` and `15b` are this doc's labels; `7b`, `10a`, `10c` and `10d` are the code's
own. `check_lua_books` asserts 7b between the delistings and the reprice, 10c after the reprice,
the index dividend right after `pay_dividends`, and neither index step on the first tick; 10d
after the reprice, `pay_bonds` right after the index dividend, and no bond step on the first tick. Both 10a and 10b
are asserted between the reprice and the fills, reset first, by `check_lua_books`.

**Where the turn round writes the Log** (since 2026-09-25). Step 3 `check_demand` writes "Tithe
unpaid." when the wrath lands. Step 17 `charge_carry` writes the rent line. Step 19
`maybe_demand` -> `fire_demand` writes a new demand. All three run inside the per-player block,
so each human's Log gets its own lines. In the local block, turn start re-runs
`EX.place_button` as a one-shot, which also rewrites the opener's tooltip with this turn's deals
and tithe, and then calls `EX.gate_button(true)`.

**One reprice for the whole round, not one per fill.** `EX.apply_trade_held` (the body the `EX.apply_trade` wrapper runs since 2026-09-23) ends with
`cm:callback(EX.apply_prices, 0.1, "zharr_after_trade_"..faction)` so a manual Buy or Sell click
sees its own price move a moment later. CA's `timer_manager` docs are explicit that a callback
name exists only so `remove_callback` can cancel every callback sharing it — names need not be
unique — so twelve fills in one pass would queue twelve repricings and all twelve would fire.
`EX.filling` is `true` for the whole of `EX.fill_orders` and suppresses that per-trade callback;
`EX.turn_round` schedules exactly one reprice itself, keyed `"zharr_after_fills"`, **after**
`EX.remember_all()` — so the recorded bar is the price the fill got, and the panel still shows
the post-fill price the next time the player looks. `EX.fill_factions` is the set of humans any
fill actually touched this turn; the reprice callback also calls `EX.after_holding_change` for
each of them once pricing is redone, and the whole block is skipped outright when nothing filled.

`EX.fill_orders` itself is not defensive: `EX.apply_trade` is called through a bare `pcall`,
because letting an engine throw escape would skip both the `EX.filling = false` reset and the
`EX.orders = keep` commit that follows it — the flag stuck `true` would silently stop every later
manual trade repricing, and the missing commit would leave an order that already filled sitting
in the list to fire a **second** real trade next turn. An error is therefore folded into an
ordinary transient token (`"threw"`, logged as an error line) rather than being allowed to corrupt
either piece of state — see §17 for how untested that path still is.

Step 11 was a real bug: `remember_all` used to live inside `apply_prices`, which also runs 0.1s
after every buy and sell. A column headed "Last 12 turns" was showing the last 12 *reprices*,
and five trades in one turn threw away five turns of history for every commodity on the board.
Reported from play 2026-09-06 — *"everytime i buy, the last 12 turns moves"*.

Nothing runs at script root. `EX.init` is reached from both
`ScriptEventFirstTickAfterWorldCreated` and `cm:add_first_tick_callback`, and it binds the race
**before** the first scan — otherwise turn one's house-region tally is counted against the Chaos
Dwarf default whatever the player actually is.

A load is not a turn: `charge_carry`, `remember_all`, `share_shocks`, `check_delistings`,
`step_books`, `step_world`, `post_deals`, contract delivery and `promote_stances` are deliberately
absent from the first-tick path. Five reloads would otherwise be five rent days, one turn filling the whole
sparkline, a second settlement payout, five trading days and five re-rolled Deals pages.
`apply_trade_income` and `apply_positions` are the opposite and run on the load path too:
effect bundles survive a save and this script's memo of them does not, so a load re-sweeps.

---

## 15. Save state

All through `EX.setv` / `EX.getv` (and `EX.setp` / `EX.getp` for per-player keys, §18) into
`EX.store`, one table saved as its own named value `zharr_state` with `cm:save_named_value` - off
CA's shared saved-value string since 2026-09-07. `EX.getv` still falls back to
`cm:get_saved_value`, so an older save restores. Most values are packed strings, so anything
list-shaped is delimited; `zharr_opts` is a table. Thirty-two keys now: `zharr_bond` and
`zharr_bondo` (war bonds and loans) are the newest, after `zharr_idx_<culture>` and `zharr_idxu`
(the index fund), `zharr_fwd` and `zharr_fwdo` (forward contracts), `zharr_deals` (the Deals page) and `zharr_wb_<faction>`, one per actor holding a
world-tier position.

**Fractions are tagged on the way through the save** (2026-09-28). CA's table save
(`campaign_manager:process_table_save`) writes a number with plain `tostring`, which follows the
process's numeric locale, and reads the table back through `loadstring`. Under a decimal-comma
locale `1.1` is written `1,1` and loads as `1` plus a stray list entry, with no error anywhere.
Reported as "every time I load prices are fine, but right after end of turn every buy/sell are
fixed to 1000": a load prices off live settings, the turn round's `EX.snapshot` then adopted the
frozen table with `ladder_step` 1 (every step at `BASE_COST`) and `spread` 0 (sell = buy). War
shocks lost their fractions the same way. So:

- `EX.enc_store` writes every non-integer number as `"#f:" .. tostring(v)` at the save callback,
  and `EX.dec_store` turns it back at the load callback through `EX.parse_num`, which reads either
  separator whatever the running locale - a multiplayer save is loaded on every machine, and two
  players need not share one. Integers are untouched: `tostring` gives them no separator.
- `EX.snapshot` treats a saved snapshot with a list entry as one an older build already broke,
  and rebuilds it from the preset name it still holds (a string, so it survived): exact for a
  named preset; Custom takes MCT's sliders as they are now.
- `EX.unpack_cshare` accepts a comma as well, because `EX.pack_cshare`'s `%.4f` writes the
  locale's separator and the old pattern read every culture share as 0.

`_store_harness.lua` serialises the way the engine does, and runs a save, a turn end, a legacy
broken save and a cross-locale load in a real comma locale (`German_Germany.1252`, or a POSIX
equivalent; the selftest says so when none exists). Five mutants, one per piece, all caught.

| Key | Holds |
|---|---|
| `zharr_rung_<res>` | current ladder rung |
| `zharr_hist_<res>` | sparkline history, 12 bars, delimited |
| `zharr_deep_<res>` | the chart buffer, 40 bars, delimited |
| `zharr_press_<res>` | your net pressure |
| `zharr_shock_<res>` / `zharr_shockwhy_<res>` | live shock and its cause |
| `zharr_shocksrc_<res>` | who caused it and where: `attacker;region;size;others` (§8.2) |
| `zharr_shocked` | this turn's duplicate guard, `;`-joined |
| `zharr_bk_<house>` | a house's book, packed |
| `zharr_sh_<house>` | shares you hold |
| `zharr_home_<house>` | its capital region key, cached while alive |
| `zharr_houses` | the discovered list, `;`-joined |
| `zharr_delisted` | permanent |
| `zharr_offer_<res>` / `zharr_offerings_made` | offering countdown and escalator |
| `zharr_demand_res` / `_tier` / `_due` / `zharr_demand_turn` | the pending tithe |
| `zharr_opts` | **the settings snapshot** |
| `zharr_log` | the panel log, RS/FS-delimited |
| `zharr_cshare` | last turn's culture shares — read by drift AND by the demand shocks |
| `zharr_intro` | has this player read the introduction — per-player |
| `zharr_bundles_stripped` | the one-time legacy-ladder migration flag |
| `zharr_ord` | standing orders, `;`/`,`-delimited (`res,side,cmp,rung` per record) — **per-player**, joins `EX.SLICE_TABLES`; see §12 and §18 |
| `zharr_wb_<faction>` | that actor's world book, `res=n;...` sorted, in lots and signed. Cleared when every commodity in it is exactly 0 (`v ~= 0`, not `v > 0` - a short is a real, non-empty book) and when `EX.step_world` confirms the faction dead. Restored by scanning `EX.store` for the prefix (`EX.restore_world_books`), since no actor roster exists that early - until 2026-09-13 it was written and never read, so every load emptied the world book |
| `zharr_idx_<culture>` | the index for that culture, a table `{ d, m, last, prev }`: the divisor (a float - tagged through the save, see above), the sorted member keys and the two trend levels. **World** state: every machine computes it from the same houses, so it is never per player. Dropped when the last member dies |
| `zharr_idxu` | index units held - **per-player**, joins `EX.SLICE_SCALARS` |
| `zharr_bond` | open bonds and loans, `side,fac,p,c,at,late` per record - **per-player**, joins `EX.SLICE_TABLES`. Six fields, whole numbers, or the record is dropped |
| `zharr_bondo` | this turn's bond and loan offers, `side,fac,amt,pay,term,turn` - **per-player**, joins `EX.SLICE_TABLES`. Rebuilt every turn, saved so a reload mid-turn shows the same page |
| `zharr_fwd` | open forward contracts, `fac,res,side,lots,px,at` per record - **per-player**, joins `EX.SLICE_TABLES`. Six fields or the record is dropped |
| `zharr_fwdo` | this turn's contract offers, `fac,res,side,lots,px,turn,due` - **per-player**, joins `EX.SLICE_TABLES`. Rebuilt every turn like `zharr_deals`, saved for the same reason |
| `zharr_deals` | this turn's Deals page, `;`/`,`-delimited (`fac,res,side,lots,px,turn` per deal) - **per-player**, joins `EX.SLICE_TABLES`. Only so a reload mid-turn shows the same page; the next turn start replaces it. A record without all six fields is dropped, never defaulted |

`EX.strip_legacy_bundles` sweeps any `derpy_chd_ex_ladder_*` bundle left applied by a build
before 2026-09-05. Its `cm:remove_effect_bundle` calls are individually pcall-wrapped, so a save
from an older build is swept whether or not the key still resolves.

---

## 16. The toolchain

```powershell
py tools\gen_zharr_exchange.py              # write the TSVs, no RPFM needed
py tools\gen_zharr_exchange.py --check      # build and check against vanilla, write nothing
py tools\gen_zharr_exchange.py --selftest   # 77 checks; also rewrites the MCT file and production map
py tools\gen_exchange_ui.py --selftest      # the three .twui.xml
py tools\import_zharr_exchange.py           # build the pack (needs RPFM open)
```

| Tool | Does |
|---|---|
| `gen_zharr_exchange.py` | 649 DB rows, 1,776 loc, the MCT file, the production map. 77 `check_*` functions |
| `gen_exchange_ui.py` | the panel, row and button `.twui.xml`; GUIDs by counter, every imagepath checked against the game's packs |
| `import_zharr_exchange.py` | packs it; runs **both** selftests first and refuses on a TSV-vs-`build()` row mismatch |
| `preview_exchange.py` | renders the Offerings, Trade and Log views to PNG with the game shut, by running the shipped `EX.build_panel` / `EX.layout` / `EX.refresh_panel` under Lua 5.1 against components built from the three `.twui.xml` files; `--selftest` |

**Sixteen Lua harnesses** in `tools/_*_harness.lua`, plus a dozen more inlined in the
generator, run the shipped script under Lua 5.1.5 against stubbed campaign interfaces and read
back what it actually did. Discovery, prices, books, houses, layout, nav, sorting, tips, log,
store, MCT, multiplayer, race binding, race tuning, warehouse, shocks, footer bounds, header
widths, chart geometry, and the position total.

**Added 2026-09-23..27, each watched to fail first:**

- `check_lua_books` pins who a markup names (`source_named`) and caps a 40-house reprice at 80
  power reads.
- `check_scale_far_end` (§12, Size).
- The layout harness records `Resize`'s third argument, `SetTooltipText`, `ShaderTechniqueSet`
  and `ShaderVarsSet`. Its shade audit holds "disabled" to "greyscale" on every component the
  scenes touched.
- A static check allows exactly one `:SetDisabled(` in the file, inside `EX.set_off`.
- `LUA_BOUNDS_HARNESS` measures the five live Guide lines and the tithe footer at their worst
  case.
- The log harness covers the rent, offering and tithe lines, and still counts zero localisation
  calls at turn time.
- `check_mct` refuses duplicate titles.
- The opener's `followed` / `follow_away` asserts prove the poll follows a wider strip and
  ignores one that has slid away.

Mutation runs: 6 for scaling, 34 for the QoL pass and 6 for the grey fix, all caught.

**A static slice of `EX.refresh_panel` must use `rindex` for the Trade branch.** The Houses
branch comes first and asks the same `EX.buy_refusal` question, so a slice cut with `index()`
is satisfied by the wrong row. One QoL mutant survived on exactly that.

**One of the seventy-seven is not about this mod's rules at all.** `check_no_orphans` scans every
`EX.*` the runtime defines and fails if nothing anywhere reads it — the runtime, the sixteen
harnesses, the tools, the production script and the MCT file. It is the opposite direction from
`check_lua_undeclared.py`, which finds names that are *read* and never declared: this finds
names that are *declared* and never read, which is silent in a worse way, because the code
looks wired and its comment says it is. Three faults of that exact shape were live on
2026-09-09 — `EX.FEATURES`, `EX.feature("orders")` and `EX.step_help`, the last carrying a
comment claiming "the help button and the harness both reach the guide through it" when the
help button calls `EX.set_mode` and the arrows call `EX.nav_click`. Prose is not a reader, so
the scan strips comments and docstrings from the reader files too — leaving them in was enough
to make a re-added dead function look alive, measured by mutation.

**Verification discipline.** Every fix gets mutants: break the thing deliberately, prove the
check catches it. Where a mutant survives, the check is wrong, not the mutant. Three real holes
found that way in the last session alone — a source assertion that encoded the bug it was
guarding, a warning function nothing called, and an exemption list that could be grown without
changing any set arithmetic.

**Unless the mutant is *equivalent*, which has to be proved rather than assumed.** "Drop
`PANEL_LAYOUT_HOUSES` from the union" survived, and measurement showed why: six of the seven
layout tables name nothing no other table names, so dropping any of them leaves the union
identical *as a set*. A check that "caught" it would be asserting on source text rather than on
behaviour. It was dropped with the reason written down and replaced by a two-edit general case.

**And a check that reads its expectation from the code it is checking asserts only that the code
equals itself.** The layout harness first asked `EX.panel_cells()` both which components to
create and which set to verify — so deleting a table from the union meant its cells were never
created either, nothing was left visible, and the mutant walked. Measured: it did. The harness
now scans `EX` for `PANEL_LAYOUT*` keys itself and prints how many of its own cells the function
under test is missing.

**Four traps worth knowing before editing a harness:**

- Harnesses are `%`-formatted in Python to inject the script path, so **every other `%` must be
  doubled** — it looks like a Lua error and is a Python one.
- Lua's `%w` excludes the underscore. Faction, culture and unit keys are underscore-heavy, so a
  pattern capturing one is written `([%%w_]+)`.
- Desktop `lua.exe` is **double** precision; the game is **single**. A harness cannot reproduce
  the float32 artefacts of §7.1.
- A harness that stubs a setter away cannot tell **"painted" from "left up"**. `EX.layout` calls
  `SetVisible(true)` on every cell the current view names, so visibility says nothing about
  whether anything wrote an image or a string into it — deleting the chart icon's paint call
  left a visible cell and the mutant walked. Record what `SetImagePath` and `SetStateText` were
  handed and assert on that. **`Resize` too**, since 2026-09-09: `set_text` FORCES a cell
  visible and writes into it, so a cell no layout table places still draws — at whatever width
  the last view gave it. A paragraph in a price column's 200px is the visible result.
- **A view's DRAW is a different question from its LAYOUT, and only one of them is reachable.**
  The harness cannot run `refresh_panel` — it needs a live faction, a stance vector and half
  the campaign interface — so anything written *inside* that function is invisible to every
  check here. Three mutants walked for exactly that reason before the introduction's draw was
  lifted into `EX.draw_intro`, which is why `EX.draw_chart` is a function too.
- **`EX.MODES` is the tab strip, not the list of views.** The guide and the introduction are
  reachable and deliberately absent from it, so a check that iterates `EX.MODES` covers neither.
  `refresh_panel` indexes `EX.HEADERS[EX.mode]` *before* it branches, so a view with no entry
  takes the whole panel down — and for the introduction that is the first opening of every
  campaign. The header-coverage check now reads `EX.panel_layout`'s own branches instead.

**RPFM only:** the MCP server exists only while RPFM is open. Every new session must call
`set_game_selected(game_name="warhammer_3", rebuild_dependencies=false)`.

---

**Renamed 2026-09-09: the pack file is `derpy_zharr_exchange.pack`.** It shipped as
`derpy_chd_zharr_exchange.pack` and the mod covers eight cultures, so `chd` in the filename had
stopped being true. **Only the pack basename moved**, and two lookalikes deliberately did not:

- `FRAG` in `gen_zharr_exchange.py` is the DB **table** filename inside the pack
  (`db/<table>_tables/derpy_chd_zharr_exchange`) and the loc file. It only has to be unique
  across installed mods, which it is. Renaming it rewrites eleven table paths and buys nothing.
- `mct:register_mod("derpy_chd_zharr_exchange")` is the key every player's MCT settings are
  **stored under**. Changing it silently resets the difficulty, all 32 sliders, all thirteen system
  switches and the Features and Debug settings for anyone who had configured them. The page's
  title and author are free to change and did on 2026-09-28 (*Derpy's Grand Trade Exchange*,
  `_D3rpyN3wb_`); the key did not.

`import_zharr_exchange.py` now refuses to build while a pack under the old name is still live
in the game's `data/` — both would load, both carry byte-identical internal paths, and which
one the game reads is load order, so the game can run a week-old build with nothing saying so.
Its `.bak_*` copies are inert: only a name ending in `.pack` loads.

**Renaming the pack does not re-enable it.** `used_mods.txt` names packs by filename, so the
old entry goes dead and the new file is simply absent from the list — the mod does not load at
all until it is ticked again in the mod manager. See
`MEMORY/wh3-new-pack-in-data-starts-disabled`.

---

## 17. Known limits

**Verified in play:** the commodities market, trading, prices, the warehouse, offerings, the
tithe, shares and dividends, the panel and all five views, Trade page 2's chart with its axes,
its turn numbers and the commodity icon (2026-09-09, turn 2, one bar and one stub), the race profiles binding correctly
(measured: `covered=true`, race "Merchant Compact", patron Myrmidia, `seg=teb_`, feed 7441, all
five tabs open, seven houses, every profiled knob on its intended value, `spread` at ×1).

**Verified in play since 2026-09-23:**

- The Buy-lag fix: click, "bought" and "repriced" arrived
  inside 0.1s on all 8 trades, a 227-instrument board included, where they had taken about
  1.8s.
- The scaled panel at the 1600 and 1920 boxes: 9 sessions on 2026-09-24, with no Exchange
  error. Every click the engine reported matched `EX.sc` to the pixel - panel 408,98 at
  1104x883, the close button still 30x30, Sell still 100x26.
- The grey-fix build loading clean: the panel built and the opener
  was placed.

**Not yet run in a campaign**:

- **Who did it, and the located bulletin** (2026-09-30, §8.2). Proved offline only
  (`check_shock_source`, 29 mutants). Unseen: whether `GarrisonOccupiedEvent` fires once per
  capture as CA's XP script implies (the capture count in a play log should now rise well above
  its old share of sacks), whether clicking the bulletin moves the camera, and whether a real
  `logical_position_x/y` lands on the settlement rather than beside it.

- **Forward contracts, all of it** (2026-09-29). Proved offline only: the books harness, MP
  section 8c, the layout harness's Contracts scene, and 29 mutants, all caught. Two things no
  harness measures: the Due column's widest string ("in 20 turns") against its 80px cell, which
  rests on the file's own 62px-per-10-characters reading and not on `TextDimensionsForText`; and
  the Deals and Contracts **headers**, which `check_header_labels` does not cover at all (it
  measures only the five views in its table). Also unmeasured: how CA's bankruptcy lands on a
  player driven below zero by a settlement they owe.
- **The settlement PAYOUT** — buyout 1.25 and wind-up 0.5, resolved through a *cached* region
  key. **The chain around it is no longer unplayed:** a live Chaos Dwarf campaign on the
  2026-09-09 build (about five turn rounds) delisted
  `cr_chd_slaves_of_the_black_dwarf` into `wh3_dlc23_chd_conclave` — the player's own faction,
  so the buyout branch — then logged the settlement and pruned the house the following turn:
  `delisted ... paid 0` / `settlement logged` / `pruned 1 delisted house(s) held at zero`.
  What that does **not** prove is the arithmetic, because `paid 0` means no paper was held. The
  wind-up branch (somebody else's kill, 0.5) has still never fired in play at all
- A house losing its capital (`SEAT_LOST` 0.6)
- The dividend ceiling: there is none
- Hell-Forge commission-mod coexistence
- MCT coexistence and the campaign lock
- The two debug buttons
- Race profiles and `race_strength` are deployed but unplayed
- **Of the three races added 2026-09-09, the DWARFS are now bound in a live campaign** —
  screenshotted 2026-09-09, The Long Ledger, title and chart drawing correctly at turn 5. High
  Elves and Dark Elves are still generated, checked and mutation-tested and never bound.
  Nothing race-shaped about any of them is new code, so what is unproven is the data: the feed
  blocks at 7461/7471, two of the three patron headers, and whether the boards feel as distinct
  in play as they do on paper
- **Three patron header widths are BOUNDS, not measurements** (`HEADER_LABEL_BOUND`). A width
  can only come from a live `TextDimensionsForText` call over the wh3 bridge, which needs the
  game running with the panel open. They are bounded at 9.0px/char — the rate the 2026-09-08
  measuring run proved overstates every string, by about 1.4x — against a 250px box with a
  longest bound of 180, so nothing can clip. Replace each with a real reading when the panel is
  next open, and delete its entry
- The Chaos Dwarf regression on a pre-build save
- **Appetite drift and the demand shocks have not been seen to move a price.** Both need a
  previous turn's culture shares to compare against, so neither does anything on turn 1, and
  the first comparison after every load is deliberately dropped. All three constants are
  uncalibrated
- **The chart over a long history.** Drawn at two bars, then at five (2026-09-09, the Dwarf
  board, a 386..1100 scale) — never at forty, so nothing has yet exercised the x ticks past a
  low turn number or a y scale spanning the full window
- **The gridlines and the AI's log entries have never been seen in play.** Both shipped
  2026-09-09 after the last campaign screenshot. For the rules, what to look for is one
  drawn *over* a bar rather than under it — sibling draw order is intent here, not a
  measurement. For the log, whether one line per topic per turn reads as informative or as
  noise once several turns have stacked up
- **CLOSED 2026-09-09 — the feature switches.** This entry recorded that all four were
  unregistered in MCT, so `EX.feature` found no boolean and returned true for every one, and
  that **two of the four gated nothing at all**: `EX.feature("orders")` guarded limit and stop
  orders, which were never built, and `EX.feature("deep_history")` guarded the deep chart from
  nowhere. There are now **three** switches, in a tenth MCT section named *Features*, and each
  gates real code. `orders` was **deleted rather than registered** — a checkbox offering to
  turn off a system that does not exist is worse than no checkbox — and `EX.FEATURES`, a
  second copy of the key set that nothing read, went with it. `deep_history` was wired into
  **both** readers of "is there a page 2": `EX.page_count`, which greys the arrows so the page
  cannot be reached, and `EX.on_chart`, which stops the panel drawing it when `trade_page` is
  already 2 as the switch moves — the normal case, since a kill-switch is thrown while the
  thing is on screen misbehaving. The buffer keeps recording either way, so turning the chart
  back on shows the turns you were away rather than a flat line. The three are in the *Features*
  section and **not** in `ECONOMIC`, so unlike the seven system switches they stay movable
  inside a campaign, which is the only thing a kill-switch is for
- **CLOSED 2026-09-10 — `orders` came back, taking Features to four, and two bugs came with the
  check that proved it.** `EX.fill_orders` was genuinely dead for part of this build, and it was
  its own harness that could not see it: the function read `EX.feature("orders")` before
  `orders` was back in `EX.FEATURE_DEFAULT`, and `EX.feature` returns `false` for any key
  `FEATURE_DEFAULT` does not carry — so the fully-written fill step no-opped every turn, silently,
  as if the switch had been thrown deliberately. Its harness stubbed `EX.feature` to `true`
  outright, so every check passed the whole time this was true. Registering `feat_orders` in MCT
  and adding `orders = true` to `FEATURE_DEFAULT`, in the same commit as the first real call site,
  is what revived it — see §13.2. Separately, and unrelated to orders as a feature,
  **`EX.PANEL_LAYOUT_INTRO` was missing from `EX.panel_cells()`'s union in shipped code** — a real
  pre-existing bug found only because building the orders ledger meant generalising that union's
  own check past naming `EX.PANEL_LAYOUT_ORDERS` alone (§16). Every cell `PANEL_LAYOUT_INTRO`
  names is also named by `EX.PANEL_LAYOUT` itself, so no behavioural check could ever have told
  the two apart — the introduction always drew correctly regardless of the omission. The check is
  now general (every `PANEL_LAYOUT*` table found by pattern must appear in the union), which is
  what would have caught this the day it shipped and catches the next one shaped like it

**Limit and stop orders: built 2026-09-10, and PARTLY played the same day.** The half that
draws and accepts input is proven in a live campaign; the half that moves gold is not.

**Proven in play (2026-09-10, `cr_chd_warfleet_of_uzkulak`, the script log plus a
live `wh3_mcp` eval against the running game):**

- The deployed build is the one running — `EX.rent_delta` and `EX.fill_clears_rent` both answer
  `type() == "function"` at runtime, which is what makes every line below a statement about the
  shipped pack rather than about the working copy.
- `panel built with 26 rows`, opener button at 1439,2 on the `resources_bar`, no Exchange error
  anywhere in the log.
- **The ticket has been clicked**: three standing orders exist in a live campaign
  (`res_rom_textiles` b/le 26, `res_spices` b/le 21, `res_rom_iron` b/le 18). Nothing but the
  ticket can create one, so placement, `EX.place_order_check` and the save write all ran.
- **The ledger has drawn its rows in game**, with a Cancel button on each and the ticket beneath
  them — screenshotted on page 3/3 the same day.
- Both switches read `true` at runtime, so the shipped default is what was on screen.
- **A live board really does separate `EX.buy_price` from `EX.price`:** Iron's mid measured 513
  while a buy on it charged 599, a hostile guild's ~17% markup. That is the exact gap the rent
  floor's mutant 8 exists for — reserving against the mid would have spent the markup out of
  the rent — and on a calm board no check could have told the two apart.

**Still unplayed, and this is the half that matters:**

- **No order has filled.** Every fill so far ran against a stubbed `EX.apply_trade` under
  `lua.exe`. Three orders are standing and all three are in the money, so the next turn crossed
  is the first real pass.
- **The rent floor has never bitten.** `EX.fill_clears_rent` returns true for all three standing
  orders (reserve 5, 10 and 15 gold against a treasury of 5,003), so the branch that refuses a
  fill has run only under the harness.
- **Cancel has never been proven in game.** The button draws; nothing has confirmed a click
  removes the row it names, as opposed to a reload doing it.
- **The save round trip is unproven in game.** `zharr_state` loads, but nothing has established
  that it carried orders across a save rather than the orders being placed after the load.
- The fatal/transient split (`EX.ORDER_FATAL`) has never seen a real refusal token from the real
  `EX.apply_trade` — only from the harness's stand-in.
- The two ops, `zx1|ord|<packed>` and `zx1|ordx|<packed>`, have never crossed a network.
- Only one of the four Trade-page feature-switch combinations (both `deep_history` and `orders`
  on, the shipped default) has ever been on screen.
- The `pcall` around `EX.apply_trade` inside `EX.fill_orders` has never caught a real engine
  throw — `"threw"` is a token nothing has forced yet.

**OPEN, and the mod reports it itself:** the 2026-09-10 log carries
`ovn_araby holds 1.2% of the world's regions and this mod has no appetite for it - it
contributes nothing to any price. Add it to EX.CULTURE_WANTS.` That diagnostic is working as
designed — it is the only self-reported gap in a whole session's log — but closing it is a
**design** task rather than a mechanical one. `EX.CULTURE_WANTS` is 27 entries whose appetites
are argued against each other (the Southern Realms block exists so that wine, glass and spices
have a supplier at all). `check_culture_appetites` will hold you to two rules once the entry
exists — every covered race needs an appetite, and no culture may be a **pump** (only positives
demands and never supplies, which pushes every price it touches one way all campaign) — but
neither of those picks the numbers, and nothing enforces agreement with the culture's flavour
text. Decide what Araby wants and supplies first; the check only stops you shipping a
half-answer.

**Six defects found by the whole-feature review, 2026-09-10, all fixed before any deploy.**
None was a Critical: the order model, the FIFO pass, the save round trip, the fatal/transient
split and the multiplayer story all came back sound. What the eleven per-task reviews could
not see is that **six of the seven sat exactly on a task boundary**, each half correct on its
own:

| Was | Now | Check that would have caught it |
|---|---|---|
| With `orders` **off** the ticket stayed live on the chart page (that page answers to `deep_history`), so a player could place orders while the ledger holding the only Cancel button was gone — and all of them fired when the switch came back on | `EX.place_order_check` reads the switch, so `EX.place_order` and `EX.MP_OPS.ord` are both gated by one line; `EX.draw_ticket` reads it too, so the dead button is off screen | `check_features` now asserts the **third** reader; `check_nav_cycle` asserts *placement*, not page count, in all four combinations |
| With `deep_history` **off** there was no chart page, so no ticket, so no order could be created at all — on a ledger page whose own empty-state line said "set one under its chart" | The ticket is named by `PANEL_LAYOUT_ORDERS` as well as `PANEL_LAYOUT_CHART`, at identical coordinates, and drawn by the extracted top-level `EX.draw_ticket`. `EX.selection_page_index` sends a name click to the chart if there is one and the ledger otherwise | `check_chart_geometry` asserts both tables carry all seven at the same coordinates and that they clear 12 ledger rows; the layout harness draws the ledger's ticket |
| Every Place refusal was `EX.say` only — `out()` behind `log_level >= 2` **and** the `log_trade` debug toggle, so a duplicate click did nothing, silently, forever | `EX.ord_refusal` prints in `ord_standing` and the reason goes to `EX.log_add`; cleared by any edit to the ticket or change of instrument | the orders harness counts `log_add` calls — **its stub used to be a bare no-op**, which is the same shape as the `EX.feature` stub that hid the dead `fill_orders` |
| Every order surface quoted `EX.price_at`, the **mid**: "Sell at or above 621g" over a fill paying 559, or **310** on a Layer 2 instrument where `l2_sell` applies | `EX.order_price(res, side, rung)` routes the rung's mid through `EX.buy_price`/`EX.sell_price`, which now take an optional base. The ticket, the order sentence and the ledger's price column all use it | the orders harness measures 559 against a mid of 621 and asserts the sentence carries the side's price |
| The ledger drew the Trade view's headers — "Trend" over an order sentence, "Buy" over a price on rows that are half sells | `EX.view()` returns `"orders"` on the ledger, and `EX.HEADERS`, `EX.TIPS`, `EX.TIP_CELL_TEXT` and `EX.SORT_VALUE` all key off it | the nav harness reads the labels, and a **static** assertion pins `refresh_panel`'s own loop — reading the table alone was a tautology that stayed green while the consumer regressed |
| A header click on the ledger resolved through the trade sorter: header coloured, ledger unmoved, page 1 silently re-sorted | no `orders` entry in `EX.SORT_VALUE`, so `sort_click` refuses outright and leaves `EX.sort_col` alone | the nav harness asserts the refusal and that `sort_col` stays nil |

Also fixed: the page counter read `3/2` when a switch was thrown while standing on the page it
removed (`EX.page_index` now clamps exactly as `EX.trade_kind` does).

**All ten mutants of these fixes are caught by the suite — zero survivors.** Two of the ten
survived the first run and both were failures of the *check*, not the fix: one read the header
table instead of `refresh_panel`'s use of it, and one had no assertion at all.

**CLOSED 2026-09-10 — the rent seam, floored.** A fill spends at turn step 9b and
`EX.charge_carry` debited warehouse rent about six steps later in the same turn round **with no
floor** (`EX.apply_trade`'s affordability test is `treasury() < price`, so the last fill could
leave the treasury anywhere in `0 .. price-1`). Treasury 1,500, one limit buy fills at 1,400,
600 Tusks at `CARRY_PER_UNIT` 0.5 is 300g of rent — the turn ended at **−200** on two
movements of gold the player clicked neither of. Of the three ways out — a floor on the fill,
reserving the rent before the pass, or accepting it — the **floor** was chosen: reserving
would have been a second escrow concept in a design deliberately built with none.

`EX.fill_orders` now refuses a **buy** fill that would not leave this turn's warehousing, with a
transient `rent` token, so the order stands and the Log says why. Three things make it exact:

- **The reserve is `EX.carry_total()` snapshotted once before the loop, plus each fill's own
  delta accumulated as the pass runs.** `EX.held` reads back out of the pooled resource manager
  and whether that reflects a `cm:faction_add_pooled_resource` made earlier in the *same pass*
  is not measured; building the number this way is correct either way. One fill per instrument
  per pass is what makes it exact — an instrument's own delta is always read before it fills.
- **`EX.rent_delta` is a difference of two floors**, not `floor(lot * rate)`. `EX.carry_cost`
  floors the whole holding, so the two disagree by a gold whenever the holding's own fraction
  carries — and this number is compared against a treasury.
- **It predicts `EX.buy_price`, the same call `EX.apply_trade` charges on.** On a calm board
  that equals `EX.price`, so nothing distinguishes them; a hostile guild's markup is real gold
  and does.

**A MANUAL buy is deliberately still unfloored, and that distinction is the whole fix.** The
player is looking at the treasury when they press Buy, so both the purchase and the decision to
be that thin are theirs. A standing order is the one case where neither was — which is why the
floor lives in `EX.fill_orders` and a check asserts it is **absent** from `EX.apply_trade`.
Sells are never floored either: a sell credits gold and lowers the holding, and floored, a
player short of the rent could not sell to raise it. Layer 2 is exempt, the same exemption and
the same reason as `EX.carry_cost` — Armaments and Raw Materials come out of buildings.

**12 mutants, 12 caught.** Three survived the first run and all three were **bad checks**: the
rent-off case reserved 300 against a treasury of exactly 300 and so passed whether the switch
was read or not; `EX.buy_price` and `EX.price` were the same number on a calm board; and no
scene ever ordered a Layer 2 instrument, so its exemption was never executed. A twelfth mutant
was written specifically for the static assertion — it duplicates the floor into
`EX.apply_trade` in a form that changes no behaviour at all, so only that assertion can see it.

**Multiplayer: built 2026-09-09, never run on two machines.** §18. The 27 unforced
`cm:get_local_faction_name` calls are gone — they *threw* in multiplayer, so the mod died at
first tick rather than desyncing — and the turn round now walks `cm:get_human_factions()`. What
no single process can check is the transport itself: that `CampaignUI.TriggerCampaignScriptEvent`
delivers, that `UITrigger` arrives in one order on every machine, and that the model stays in
sync across a turn. Treat it as unverified, and do not claim it on the Workshop page until
someone has run it.

**Watch in play:** the Merchant Compact's `guild_close` at ×1.5 (0.90 effective). It is meant to
keep the Compact trading through wars that would shut a rougher market, but at that value the
war lock is close to off for that race.

**The World Book, the Deals page, position bundles and the stance hook** (2026-09-13 to
2026-09-16).

**Seen in play, 2026-09-17**: three deals taken, three lots each - Exotic
Animals at 642 a lot from Hexoatl, Wine at 1,034 from Carcassonne, Spices at 1,514 from Aislinn -
every lot at the deal's own price against the faction the page named; the stance pass logging
"0 house(s) warmer, 2 colder on your book"; the load-time position sweep touching 73 factions.

**Never seen:** a world-to-world trade (the pass writes no log line at all), any faction wearing a
War Stocks bundle, a Sold out refusal, a `nobuyer` refusal, and a promoted stance in the
diplomacy screen - the log line proves the score and the call ran, not what the AI did with it.
Every constant is a guess: `WORLD_STOCK_TURNS`, `world_gain`, `world_cash_max`, `world_trade_max`,
`deal_max`, `deal_edge`, `pos_step`, `POS_PER_TIER`, `STANCE_SHARES`, `STANCE_CORNER`.

**Limits read off the code:**

- **A short never unwinds.** Nothing credits an actor's output back into its book, so a producer
  that has sold `WORLD_STOCK_TURNS` turns of output forward has nothing more to sell until its
  land grows or it buys the good back - and its desire for its own good is negative, so it will
  not. The comments say "short until it digs it up"; no step digs anything up. The tier's supply
  of a good over the whole campaign is therefore roughly its producers' capacity less what
  players have net bought from it, and with `world_scarcity` on a good the guild is not long in
  reaches Sold out once that is spent.
- **The world book's price term reads only the players.** Matched trades conserve
  `EX.world_book`, so `world_book_shift` moves only on player trades with actors and on a dead
  faction's pruning - and net buying from the world makes the good cheaper through it (§9.1). This is the "player's own offset never unwinds" the Stage 1 handoff left open.
- **Production drowns the other four desire terms.** `-(0.4 x output)` is in units: a 26-unit
  producer scores -10.4 against a taste term inside -1..1. Every producer sells what it makes and
  every non-producer buys; taste, war and value decide little. Inherited from `EX.house_desire`,
  where the error was measured to cost nothing because `book_shift` absorbs it - not measured
  for the world tier.
- **`world_cash_max` is also a price ceiling on the tier.** A good priced above it never trades
  world-to-world (`cap_lots` floors to 0), is never sold to the player through step 2, and a deal
  on it cannot pay the faction it names: a sell deal then charges the player and pays nobody
  while the Log still reads "Bought ... from <faction>", and a buy deal is refused `nobuyer`.
  `EX.post_deals` does not filter on it. On easy (1,500 against a 1.08 ladder) that is anything
  from about step 31 up; at default about step 37.
- **A Take the model refuses says nothing on screen.** `EX.accept_deal`'s own refusals (`poor`,
  `gone`, `nodeal`) reach only `EX.say`, behind the `trade` debug toggle, and the Take button is
  not greyed for any of them - only a sell deal's `EX.buy_refusal` greys it.
- ~~**A buy deal is a riskless edge.**~~ **FIXED 2026-09-30**, build `5001ecd6`. Buying one lot
  on the Trade view at `buy_price` and selling it into the deal at `price x (1 + deal_edge)` was
  profit whenever the hostility markup sat under `deal_edge`. `EX.post_deals` now caps a buying
  faction's price at `EX.buy_price` (read bound, so the markup is the player's own), for deals
  and contract offers alike. On a calm board a buy deal therefore pays exactly market (+0%) -
  still the spread above selling on the Trade view - and on a hostile one the edge stands. The
  slider's maximum is 10, not the 25 this entry once said; its tooltip was reworded.
- **`EX.step_world` pairs buyers to sellers in `pairs()` order** and does not sort - the order
  `EX.post_deals` sorts away rather than trust. Deterministic while every machine builds
  `EX.actors` in the same insertion order, which the scan does; unmeasured across a reload in
  multiplayer.
- ~~**Settings are read live between a load and the next turn start.**~~ **FIXED 2026-09-30**,
  build `5001ecd6`. `EX.snap` was read from the save only inside `EX.snapshot()`, so the load path
  (`apply_prices`, `apply_trade_income`, `apply_positions`, the Deals row pool off `deal_max`) and
  the rest of that loaded turn read live MCT. `EX.adopt_snap()` now puts the saved snapshot in
  force (never taking a new one - that still waits for the turn start, after MCT's registry) and
  `EX.init` calls it straight after `EX.adopt_local()`. A comma-damaged snapshot is left for
  `EX.snapshot` to rebuild. Not tested in game.
- **The guide says nothing** about the Deals page, world trading, Sold out, War Stocks or
  stances. Page 1 is at the 19-row ceiling; page 2 has room.
- ~~**The Deals page is not multiplayer-safe as shipped**~~ - **FIXED 2026-09-29**, build
  `1ba9a03f`; §18. Still never run on two machines, like the rest of §18.

**Not yet seen in play (the 2026-09-23..28 builds):**

- the 2560 box (4K at 100%, or 1080p at 50% UI Scale), and whether the art fills a grown frame
  at any box;
- whether `set_greyscale_t0` draws grey at all (§12);
- the "dislikes you" sentence naming the right house. It is panel text only and never reaches
  the script log;
- the tithe row and paying from it, an x25 click that runs out of gold part way, Sell greying
  below a lot, the Held tooltip, and the opener's news, including how `||` plus a long body
  wraps in CA's tooltip box;
- the text-pass wording on screen. The 2026-09-27 morning logs ran the old build, because Steam
  had restored the published pack. Look for " ..." or a word cut mid-way: that is the only real
  test of fit;
- the opener following the strip mid-turn;
- the MCT page's new title and author (2026-09-28);
- a Nagash campaign of any kind.

**Found 2026-09-23..27, not fixed:**

- ~~**With warehouse rent switched off, rent is still displayed.**~~ **FIXED 2026-09-30**, build
  `5001ecd6`: `EX.carry_cost` reads the switch, so the Held cell, the Trade footer's "Rent:" and
  the HUD income override all answer 0 with it off. The orders harness's rent-off scene pins
  `rentoff_carry = "0 0"`; the old premise ("`carry_total` still answers 300") is gone.
- ~~**The friendly discount is unreachable**~~ **FIXED 2026-09-30** (§4.3).
- **FIXED 2026-09-30: a new campaign filled the Log with houses that never reached the map.**
  With Mixu's unlocker, two fresh campaigns each delisted 56
  factions in one batch at the first turn round - mostly dormant `mixer_*` - which had an army in
  the first-tick window `EX.tradeable_faction` reads. Each wrote "Delisted. The house is gone.
  You held nothing in it." - 56 of the Log's 120 lines. `EX.log_settlement` now skips a
  nothing-held line on turn 1 or earlier; a paid settlement, and every later death, is still
  written. Admission is unchanged: the houses are still discovered and pruned.
- ~~**The page counter can read "3/2" after the panel grows or shrinks.**~~ Fixed 2026-09-29 for
  the Houses tab: `EX.page_index` reads `EX.house_page_at`, which clamps.
- **The index has no sparkline and no chart** - it keeps no price history of its own (spec §7).
- **An index member discovered after the panel was built has no row** to draw on, the same as on
  the Houses list; it still counts in the level, the dividend and the footer's member count.
- **A dead member reads at `windup x EX.price`, and a mid-turn reprice collapses a dead house's
  price** before the round's removal pass. Share settlement has the same exposure and the index
  follows it rather than keeping a price of its own.
- **Bonds: no early repayment, and a house's stance does not move with its bonds** (spec §7). A
  missed payment is arrears for as long as the house lives; nothing short of its death defaults.
- **A bond at war with you still shows its payment** in the Per turn column, though nothing is
  paid until peace. The status button says At war and the footer's net leaves it out.
- **Which house counts as "at war" for posting is `faction:at_war()`**, CA's own answer. Whether
  a war with rebels alone counts is not verified in game.
- **A loan is paid in full from any treasury**, into the negative if need be; CA's bankruptcy
  rules take it from there.
- ~~**Multiplayer: another player's standing order resets your amount button**~~ **FIXED
  2026-09-30** (§18).
- ~~**Multiplayer: another player's Deals, Contracts, Index or Bonds click redraws your open panel
  with their data**~~ **FIXED 2026-09-30**: `EX.refresh_panel` and `EX.layout` return at once
  while anyone but the local player is bound. That also covers a tithe demand, whose
  `EX.raise_demand` redraw ran bound per human. The other machines' panels are no longer redrawn
  by another player's op at all, the same as a buy or sell has always been.
- ~~**The Offerings Status column tooltip**~~ **FIXED 2026-09-30**: "Ready, turns of favour left,
  units needed, or tithe due." `check_tooltips` fails if the column draws "Due: " and its tip
  does not say so.
- No harness scene runs the scaled chart in Lua. Only Python's copy of the rule checks it.
- **The decimal-comma trigger is inferred, not observed.** The save fix is proven offline in a
  real comma locale, but nothing shows WH3's process running Lua under the player's regional
  format: `Warhammer3.exe` does not import `setlocale` by name (its one `setlocale` string is Lua's
  own `os` library). Another DLL or mod could set it. The fix is harmless either way.
- ~~**`EX.num` (display) writes a whole number as "1," under a comma locale**~~ **FIXED
  2026-09-30**: the strip is `[%.,]$`; the store harness pins "1/1,5" in a real comma locale.
- **Not a fault: the 09-27 patch note's "the trend column now says steady".** The trend cell is
  30px wide, too narrow for the word; its header tooltip reads "- steady". The 09-28 draft carries
  a correction line.

---

## 18. Multiplayer

Built 2026-09-09. **Never run on two machines.** Everything below is built to CA's own
documentation and proven self-consistent under `lua.exe`; none of it is verified in play.

**Before this, the mod did not desync in multiplayer — it died.**
`cm:get_local_faction_name()` *throws a script error* in a multiplayer campaign unless `true` is
passed (CA, `campaign_manager.html`, "Local Player Faction"). There were 27 unforced call sites,
and the throw happened inside `cm:process_first_tick_callbacks`, whose `call_each` has no
`pcall` — so it took every mod queued behind this one down with it, with no log line naming the
Exchange.

### The three rules

| Rule | Where it lives |
|---|---|
| Force the local-faction read, once | `EX.me()` — the file's only `cm:get_local_faction_name(true)`, cached |
| Nothing that moves the model runs off a UI click | `EX.mp_send` → `CampaignUI.TriggerCampaignScriptEvent` → `UITrigger` → `EX.mp_apply` on every machine |
| Nothing is scoped to "the local player" | `EX.humans()` — `cm:get_human_factions()`, **sorted**, because CA promises no order |

`CampaignUI.TriggerCampaignScriptEvent(faction_cqi, event_id)` raises `UITrigger` on every
machine; both arguments or neither. The op rides in the id as `zx1|<op>|<arg>`, the faction on
the cqi. Six ops now: `buy`, `sell`, `offer`; `ord` (place) and `ordx` (cancel), added 2026-09-10 for
limit and stop orders; and `deal`, added with the Deals page, which carries only the deal's list
index - see "The Deals page, built per human" below. All well inside MCT's 100-character
convention. `ordx` sends
the whole packed order (`res,side,cmp,rung`) rather than a list index: the list is per-player and
every machine holds the same one, so an index would *usually* land on the right row — and
"usually" is how one machine deletes a different row from its neighbours and the two saves
diverge from there on. **A fill sends nothing over the network at all** — it runs inside the turn
round, which every machine already executes identically over `cm:get_human_factions()`, so there
is nothing to broadcast. The cqi is resolved by walking the human list —
`faction_for_command_queue_index` is in CA's interface index with no signature documented
anywhere.

**Singleplayer runs the same code.** `EX.humans()` is one entry, the subject is always that
entry, and `EX.mp_send` calls the op directly instead of broadcasting. So the only thing
multiplayer does differently is the network round trip — which is also the only thing a single
process cannot test.

### The subject

Per-player state is not threaded through sixty call sites; it is **swapped**. `EX.bind_player`
points `EX.shares_held`, `EX.LOG`, `EX.offer_until`, `EX.orders`, `EX.deals` and the five demand values at another
faction's slice, and `EX.who()` answers whoever is bound (defaulting to `EX.me()`).
`EX.with_player(faction, fn)` is the only sanctioned way in, and its `pcall` is what stops an
error stranding the wrong subject for the rest of the campaign.

Two non-obvious requirements, both of which cost a debug cycle:

- `EX.bind_player` calls `EX.adopt_local()` first, or the very first bind throws the live tables
  away and replaces them with an empty slice.
- `EX.bind_player` clears `EX.guild_hold`. That memo is *one subject's* diplomacy; kept across a
  bind it prices another player's trade off this client's treaties — and only on the machine
  with the panel open.

### The save keys split in two

`EX.store` is one table in a savegame that multiplayer shares.

| | Keys | Accessor |
|---|---|---|
| Per player | `SAVE_SHARES`, `SAVE_OFFER`, `SAVE_OFFERINGS`, `SAVE_DEMAND`, `SAVE_DEM_RES/TIER/DUE`, `SAVE_LOG`, `SAVE_INTRO`, `SAVE_ORDERS`, `SAVE_DEALS` | `EX.setp` / `EX.getp` — appends `@<faction>` |
| World | price steps, history, the deep chart, pressure, shocks, who caused them and the shock guard, house books and world books (`SAVE_WBOOK`), house list, capitals, delisted, culture shares, the legacy-strip flag, the settings snapshot, and the store itself | `EX.setv` / `EX.getv` |

`SAVE_ORDERS` (`zharr_ord`) joined the per-player set 2026-09-10 for the same reason every other
row in it exists: a standing order is a position, and two players sharing one ladder would be two
players cancelling and filling each other's orders. `orders` joined `EX.SLICE_TABLES` alongside
`shares_held`, `offer_until` and `LOG`, so `EX.bind_player` swaps it in and out with everything
else a subject carries — see "The subject" below.
`deals` joined them with the Deals page, and `SAVE_DEALS` the per-player column: a deal is posted
to one player, and a world-scoped key would show every human the page rolled for whoever was
bound last.

Both wrong answers are silent: an unscoped per-player key is two players robbing each other
*and* a divergent save; a scoped world key forks the price ladder and the market stops being one
market. `check_lua_mp()` asserts the split in both directions and that the declared `SAVE_*` set
is exactly those - 27: eleven per player, sixteen world, since `SAVE_WBOOK` joined the world
column and `SAVE_DEALS` the per-player one.

`EX.getp` falls back to the unscoped key **only when there is exactly one human** — every save
written before this build is such a save, and with two humans the fallback would hand player B
player A's position identically on both machines, so not even a desync would announce it.

### The turn round

`EX.turn_round()` replaces the eighty-line `FactionTurnStart` body, sorted into **world** (scan,
books, reprice, shocks, trade income — once, unbound), **player** (tithe, rent, dividends,
warehouse, bulletins — once per human, on every machine, bound) and **local** (button, panel).
It runs **once per turn number**, not once per event: every human raises its own turn start and
the arrival order is not promised.

All four documented ordering constraints are preserved verbatim. Settlement is now two
functions — `EX.settle_house` reads the living price once and walks every human,
`EX.settle_holder` pays one — because "did I take the capital" has a different answer per
player, so one death can pay one holder the 1.25 buyout and everybody else the 0.5 wind-up.

### Two things that are deliberately different in multiplayer

**MCT is ignored, and the reason is a race rather than an absence.** MCT *does* sync: the host
is detected in the lobby, its faction key is distributed at `pre_first_tick` as `mct_host`, its
option values follow as `MctMpInitialLoad`, clients' panels are locked with
`mct_lock_reason_mp_client`, and a mid-campaign Finalize re-broadcasts to everyone. **But that
distribution is two asynchronous network round trips starting at `pre_first_tick`, and nothing
orders them against the first `FactionTurnStart`** — which is where `EX.snapshot()` freezes 45
values into the save, plus the preset name. A client that has not received the host's settings yet would freeze the
defaults while the host freezes its own, permanently, with a correct-looking panel on both. So
in a multiplayer campaign every economic value is the shipped default on every machine, and the
MCT panel says so. The log options are *not* gated — they touch nothing in the model.

Lifting this is a real option and is written up in the handoff: gate the snapshot on
`cm:get_saved_value("mct_mp_init")` plus `cm:progress_on_all_clients_ui_triggered`, or read MCT
on one machine and broadcast the **preset name** over our own transport — one word, because the
four presets are baked identically into every copy of the Lua.

**The AI books front-run player one.** `EX.house_desire`'s front-run term and
`EX.check_standing_sign` both ask "how does this house feel about the player", which has no
single answer with four humans; both run bound to `EX.humans()[1]`. In singleplayer that is the
player, so the shipped behaviour is unchanged. Upgrade path is noted at the call site.

**Found 2026-09-25, FIXED 2026-09-30: one player's order reset another's amount button.**
`EX.place_order` runs on every machine through `EX.MP_OPS.ord`, and it wrote
`EX.amount = EX.clamp_lots(qty)` - the placer's size - into what is otherwise local session
state. It now freezes `qty` onto the order directly and falls back to `EX.amount` only when no
`qty` is given; the orders harness pins `op_qty = "10 amount=1"`.

**Another player's op no longer draws on your panel (2026-09-30).** The `deal`, `fwd`, `idx` and
`bond` ops, and a tithe demand, redrew the panel while the sender was bound, so every machine with
it open showed the sender's slice. `EX.refresh_panel` and `EX.layout` now return while anyone
but the local player is bound; the layout harness's `rival_draw` scene pins both halves.

**Local on purpose:** the opener's placement, its 300ms follow poll, its greying and its
tooltip, and the panel's size (`EX.fit` reads this client's screen) are all UI-only. None of
them crosses the network, so none can desync. `EX.bulk` is the one piece of trade-path state that
is not per-player, and it does not need to be: it is set and cleared inside a single synchronous
`EX.bulk_trade`, which every machine runs the same way from the same op.

### The Deals page, built per human

**Fixed 2026-09-29, build `1ba9a03f`.** Until then `EX.turn_round` called `EX.post_deals` once,
unbound. `EX.post_deals` builds the page for `EX.who()`, so unbound meant the adopted local
subject: each machine rebuilt only its own player's page, and every other human's slice kept
whatever the last load restored. The Take op carries only a list index, applied as the sender on
every machine, so the sender's machine resolved this turn's deal and the others a stale one or
none (`nodeal`). `_mp_harness.lua` section 8 hid it by writing the per-human loop itself.

**Now `EX.turn_round` calls `EX.post_all_deals`**, which runs `EX.post_deals` inside
`EX.with_player` for each human in `EX.humans()`' sorted order. Every machine builds every page
from the same world, and `EX.save_deals` writes each human's own key. It is a named function
rather than a loop inside the round so that the harness runs the shipped loop: `EX.turn_round` is
a closure inside `EX.init`, and nothing offline can call it.

**`EX.deal_why` moved into `EX.SLICE_SCALARS` with it.** It is the footer's reason for an empty
page ("none" or "declined"). Held in one shared value, a per-human pass ended with the last
human's reason, so the local panel explained a page it never had. `EX.restore_player` clears it,
because it is not saved: after a load the footer says the neutral sentence, as it always did.

**Checked by:**

- `_mp_harness.lua` section 8b. zeta_player, last in the walk and not local, is refused
  outright. Every page and every reason must come out per player, and the local reason must
  still be the local player's after the pass.
- `check_lua_books`: the round must call `EX.post_all_deals()` after the reprice and never
  `EX.post_deals()` bare, `EX.post_all_deals` must bind per human, and neither may run on first
  tick.

Four mutants, four caught: the bare call restored, the loop unbound, `deal_why` taken out of the
slice lists and the restore together (only 8b sees that one), and the restore's clear dropped.
Singleplayer is unchanged: one human, bound to itself, as every other per-player step already is.

### Forward contracts, per human

Built per human from the first build that has them (2026-09-29). The offers come out of the same
bound pass as the deals, so offer `k` is the same offer on every machine; they have their own list
(`EX.fwd_offers`) and their own op, `fwd`, carrying that index. Delivery is turn-round work:
`EX.deliver_all_forwards` runs `EX.deliver_forwards` inside `EX.with_player` for each human, like
the deals, and nothing about it crosses the network. Both lists are in `EX.SLICE_TABLES`, both keys
are per player (`zharr_fwd`, `zharr_fwdo`), and `EX.restore_player` unpacks both.

**Checked by** `_mp_harness.lua` section 8c: one deal slot and house_b refusing mid_player, so each
human's offers differ exactly where they should; mid_player takes offer 1 through `mp_apply` on a
machine playing alpha_player, and only mid_player's list grows; on the delivery turn only
mid_player's treasury moves and every list is empty after. `check_lua_mp` pins all of it, plus the
two keys as per-player and `fwd` in the op set.

### One market on every machine

The shared market's four race-tuned knobs take no profile in multiplayer, and the index's
wind-up is its own culture's - §11.1. **Checked by** `_mp_harness.lua` section 8f, which plays
two machines by swapping the local race row between Chaos Dwarf and Skaven: the four knobs read
the same on both, the Empire index weighs a dead member and re-cuts its divisor at the Empire's
wind-up on both, singleplayer still moves with the local race, and each player's own knobs still
follow that player.

### The index fund, per culture

The index is world state, one per culture with a human, rebuilt by both passes over the sorted
list of those cultures, unbound. The units are per player; the `idx` op carries the lots and is
applied as the sender, whose culture - not the local machine's - picks the index. The dividend
runs inside the per-human block. Deaths are logged to every human of that culture through
`EX.index_holders`, which binds each in turn.

**Themed funds** ride the same passes and the same op (`b<n>@<id>`), resolved against the
sender's culture - `fund_mp_units` has the Empire player refused a Chaos Dwarf fund id.

**Checked by** `_mp_harness.lua` section 8d: the index is built for the Chaos Dwarf humans only;
alpha_player (Chaos Dwarf, local) buys and mid_player (Empire, no index) is refused - with both
treasuries reset first, because an earlier section left mid's negative and a gold refusal once
hid an index read off the local culture; only alpha's treasury receives the dividend; and an
Empire member's death, once a second Empire house gives mid an index, lands in mid's log and not
in the local player's.

### War bonds and loans, per player

Offers and positions are both per player (`EX.SLICE_TABLES`), posted inside `EX.with_player` for
each human from that human's culture's houses. The `bond` op carries the offer's index and is
applied as the sender. Payments run in the per-human block, right after the index dividend.

**Checked by** `_mp_harness.lua` section 8e: a house at war posts a bond and one at peace a loan
for alpha_player (Chaos Dwarf, local), while mid_player (Empire) gets the two Empire houses'
loans, richest first - a page built for the local player would hand mid alpha's; alpha lends and
mid borrows with offer 1 each, as the sender, and each take moves exactly the amount between that
player and that house; the next turn's payments move alpha's and mid's treasuries only, each the
exact mirror of its house's; every pass leaves the local player bound.

### What is checked

`check_lua_mp()` plus `tools/_mp_harness.lua` — a four-human stub, shuffled on input, mixing
three covered races and an uncovered one. **10 mutants, 10 caught.** It proves slice isolation,
subject restoration after an error, the key split, the migration guard, the prune test, and that
segment, patron, coverage *and the race profile factors* all follow the bound subject.

It does **not** reach: that `TriggerCampaignScriptEvent` delivers, that `UITrigger` arrives in
one order everywhere, that the engine tolerates the event-id string, that
`command_queue_index()` answers what we assume, or that the model stays in sync across a turn.

---

## 19. Extending it

**A new race** — add a row to `EX.RACES` with a fresh `seg`, a patron, `wrath`/`pleased` keys,
`boon_over` for Exotic Animals, an empty `layer2`, and a `tune` naming only whitelisted knobs.
Add a `<SEG>_TIERS` / `_FLAVOUR` / `_OFFER_TEXT` set and a `RACE_TEXT` entry in the generator,
plus a `FEED_BASE` block ten indices clear of the last. Then add the culture to
`EX.CULTURE_WANTS` — `check_race_table()` and `check_culture_appetites()` both refuse without it,
which is the link that did not exist when the Southern Realms shipped appetite-less.

If the culture is from another mod, register it in `MODDED_CULTURES` so the vanilla-key checks
exempt it, and keep the string out of every DB and loc row — `check_no_foreign_keys()` enforces
the soft dependency.

**A culture appetite only** — one line in `EX.CULTURE_WANTS`, both signs, values within -1..1,
keys from `EX.COMMODITIES`. This is what the runtime warning of §9 is asking for.

**A new commodity** — it must exist in CA's `resources_tables`; take the name from
`resources_onscreen_text_<key>` via `tools/read_vanilla_loc.py` and the icon from
`icon_filepath`. Then: `EX.COMMODITIES`, `EX.INFO`, `EX.BOON`, `EX.WAR_APPETITE` (including a
deliberate zero), the production stems in the generator, and an appetite line in every culture
that should care. `check_lua_appetite()` asserts `WAR_APPETITE` is complete.

**Never** add a knob to `EX.RACE_TUNABLE` without checking §4.3 first. The four excluded ones
are the round-trip algebra, and a race factor on any of them can mint gold.

**A new order kind** — the shape is `{res, side, cmp, rung}` and limit/stop is derived from
`side`/`cmp`, never stored, so a genuinely new kind needs a sixth field (`qty` is already the fifth)
threaded through `EX.pack_orders`/`EX.unpack_orders`/`EX.valid_order`, a new branch in
`EX.order_hits`, and a sentence in `EX.order_text`. Classify every new `EX.apply_trade` refusal
token it can hit into `EX.ORDER_FATAL` or leave it to the transient default before shipping it —
an unclassified token is safe by construction, but a token that is actually fatal and left
unclassified is a standing order that silently never leaves the ledger.

**A new war good** - add the key to `EX.WAR_GOODS`, chosen by display name, and move
`check_lua_books`' pinned count (`war_keys_count == 3`) with it; the pin exists so widening the set
is deliberate. `POS_TEXT_UP` / `POS_TEXT_DOWN` in the generator name the three goods.

**A new position tier** - `EX.POS_TIERS` in the Lua and `POS_TIERS` in the generator must match:
the DB emits one bundle per tier and the sweep removes one key per tier, so a tier on one side
only is a bundle that applies nothing or one that nothing can remove. Keep it symmetric and
without 0 (both asserted), and keep the `pos_` stem.

**A new world-tier knob or switch** - the constant, `EX.TUNE_NUM` (or `EX.TUNE_BOOL`), all three
non-default presets (`default` stays empty), and `TUNABLES` (or `MCT_OPTIONS`) in the generator.
Gate the feature with `EX.setting`, never `EX.opt`, and make a harness prove the switch reads on
before asserting anything: a switch that does not exist yet reads nil, the feature is silently
dead, and every test of it passes.

**A seventh view** - does not fit. The strip is six tabs, 108 wide on a 116 pitch, ending at 708
against `derpy_chd_ex_prev` at 774, and it is written out in all ten `EX.PANEL_LAYOUT*` tables;
`gen_exchange_ui.py` measures each tab's right edge against the arrow. A view keyed by `EX.mode`
also needs `EX.HEADERS` (a missing entry takes the whole refresh down), `EX.TIPS`,
`EX.SORT_VALUE`, a `PANEL_LAYOUT_*` / `ROW_LAYOUT_*` pair and both `EX.panel_layout` /
`EX.row_layout` branches, plus `TAB_MODES` and a `check_mode` call in `gen_exchange_ui.py`.

**Resource Overhaul's goods (2026-10-01)** - Derpy Resource Overhaul adds 37 tradeable goods, and they
join this market only when that mod is installed. Without it, nothing below runs and the
Exchange is the 17-good market it always was.

- **Joined per good at init.** `EX.join_more_resources()` runs before the first scan and before
  `EX.restore`. It appends a good to `EX.COMMODITIES`, `EX.INFO` and `EX.BOON` where
  `common.get_localised_string("resources_onscreen_text_<key>")` is non-empty. Resource Overhaul
  ships that loc key and nothing else does. The vanilla 17 stay first, and `EX.BASE_COUNT` (17)
  marks where they end.
- **Supply comes from the buildings' own effect lists.** Resource Overhaul gates each production row
  by a lore condition on the region, so one port chain makes pearls at Lothern and amber at
  Erengrad. An `EX_PRODUCTION`-style map would be wrong both ways. `EX.region_goods` makes one
  `common.get_context_value("CcoCampaignSettlement", cqi, EX.MR_EXPR)` call per region. It reads
  `BuildingContext.EffectList`, which holds only the rows whose condition holds, at their real
  value. The call is pcall-wrapped. Measured on IEE: 749 regions in 0.064s.
- **The vanilla 17 stay the anchor.** The price median and trade income (Option B, §10) read
  only `EX.COMMODITIES[1..EX.BASE_COUNT]`. Most rare goods have no producer on turn one. If the
  median included them, it would fall towards zero and price every vanilla good as a glut. If
  trade income included them, the Salted Fish glut (every port makes it) would put a penalty on
  nearly every coastal faction. Resource Overhaul's goods already trade through CA's trade
  agreements.
- **The goods list pages.** 55 rows do not fit 20 slots. `EX.goods_pages()` sorts first and
  pages second. Trade gets one `"list"` entry per page ahead of the chart and the ledger in
  `EX.trade_pages()`. Stats and Offerings page through `EX.goods_page`. With 19 rows this is
  one page, so nothing moves without the mod.
- **The DB rows ship in this pack, always.** Each good gets a holding pool, a factor junction,
  three warehouse bundles, one offering per race, the demand text per race and tier, and a
  shock bulletin. That is 26 rows and 98 loc lines per good. The rows are keyed on our own
  prefix and name nothing of Resource Overhaul's, so the pack loads cleanly without it.
  `ALL_GOODS = COMMODITIES + MR_COMMODITIES` drives them in the generator. `COMMODITIES` stays
  the vanilla 17, so every check pinned to it still pins it.
- **Each good burns as a vanilla commodity.** `MR_OFFERING` maps each good to a vanilla
  commodity, and the good takes that commodity's effect, scope and boon. Food maps to
  replenishment, metal and hides to armour, luxuries to tariffs. That keeps the verification
  `OFFERING_EFFECTS` was counted out of vanilla with. The offering text is the vanilla
  commodity's effect text.
- **Demand text is shared across the races.** `MR_FLAVOUR` has one patron-neutral line per good,
  used by all eight races. Each race's own tier title and closing line sit either side of it.
- **Checked by** `check_more_resources()` and `tools/_resource_overhaul_harness.lua`. The harness
  runs the shipped file once without `common` and once with every name but Wool resolving. It
  measures the join, idempotence, the parsed supply string, a throwing read, the median, trade
  income, paging, the chart found by name, and the wrap and reset of the arrows. Mutation-tested
  2026-10-01 against the median, trade-income and paging guards.
- **Not done.** No `EX.CULTURE_WANTS`, `WAR_APPETITE` or `BUILD_APPETITE` entry names these
  goods, and no fund names them. All of those reads are nil-guarded, so the goods simply have no
  appetite. Per-race demand flavour has not been written.

---

### Scrolling lists and Trade's sections (2026-10-01)

Resource Overhaul took the goods list from 19 rows to 56, so Trade, Stats and Offerings paged, and
the chart and the ledger ended up as pages 4 and 5 behind the same arrows. Asked for from play:
a scroll bar instead of pages, buttons for the chart and the standing orders, and the scroll bar
on every other long list.

| View | Now |
|---|---|
| Trade goods, Stats, Offerings, Houses list, Log | scroll bar and mouse wheel |
| Trade chart, Trade ledger | Goods / Chart / Orders buttons in the title bar (`EX.SECTIONS.trade`) |
| Funds, Bonds, Deals, Contracts | unchanged, one page each |
| Help | the only view the arrows and the page counter still show on |

- **Drawn whole, scrolled by moving (2026-10-02).** The first build drew one window of rows and
  redrew the panel (25-200ms) for each new scroll position: a drag froze the game, and the fix
  for that (redraw once the bar stops) left the rows lagging behind it. Asked for from play:
  "rendered all at once and the scrollbar will navigate the already rendered list". Now a built
  list draws EVERY item once, row i at `holder y + (i-1) * ROW_PITCH`, and `rows_holder` is as
  tall as the list. `EX.scroll_slice` hands back everything while `EX.list_key` is set and the
  top `MAX_ROWS` when it is not (a list that broke - nothing can scroll or clip it).
- **The scroll is one MoveTo.** `list_box` holds one empty row per item at the same pitch, so
  `rows_holder` belongs exactly where `list_box` is. A 16ms `cm:repeat_real_callback` poll
  (`EX.scroll_poll` -> `EX.follow_list`) reads `list_box`'s y and moves `rows_holder` there; the
  holder carries every row, because a parent's `MoveTo` moves its children (measured in game
  2026-10-02 on three vanilla HUD components). No layout, no refresh, no move at all on a tick
  where nothing moved. Registered once, never removed (`remove_real_callback` leaks a record per
  call); closing the panel clears `EX.list_key`, so the poll returns at once.
- **What is already on screen is not written again.** `set_text` keeps `EX.drawn[row id/cell]`
  and skips a write whose text is unchanged; `EX.draw_spark` skips a sparkline whose history is
  unchanged (12 bars, each a Resize and a MoveTo). ROW cells only: panel cells are also written
  directly (`EX.clear_ticket`, `EX.draw_chart`), which would leave the memo stale.
  `EX.build_panel` empties it - a new panel is new components with nothing written on them.
  Whether the Lua that WORKS OUT each row also needs skipping is unmeasured: time
  `EX.refresh_panel` in game before adding that.
- **The Log has its own row pool**, `row_lg1`..`row_lg120` (`EX.LOG_MAX`), one per entry, newest
  first. It used to borrow one goods row per line, which capped it at the goods count and painted
  each line onto a goods row - a click on a line's name charted that row's commodity.
  `EX.scroll_n` caps the log's list at the pool, for an older save carrying more.
- **The list is CA's listview** (`ui/campaign ui/derpy_chd_ex_list.twui.xml`, emitted by
  `gen_exchange_ui.build_list` with the Great Guilds' emitter), holding one EMPTY row
  (`derpy_chd_ex_sp`) per item; `rows_holder` is moved into `list_clip` with `Adopt`, over them.
- **`rows_holder` goes back to the panel before any `Destroy`** - Destroy takes every row with
  it. If the engine refuses that hand-back the list stays (hiding it would hide the rows) and only
  its scroll bar goes; if it refuses the rows at build time the empty list is destroyed (it would
  sit over the rows and take their clicks). Either way `EX.list_broken` stops further builds and
  the lists draw their top 20, unscrolled.
- **Rebuilt, never rewound.** `EX.scroll_key()` is view, item count, sort column and direction;
  any change rebuilds at the top. Every opening of the panel does too. An unchanged key keeps the
  list, and `EX.ensure_list` puts the holder back where the list is scrolled to after `place()`
  moved it to the top.
- **The Log is scanned before its list is sized** (a scan after it would rebuild the list at the
  top on the first scroll), and `rows_holder` is pinned to its own position after each `Adopt`,
  because whether `Adopt` keeps the screen position is undocumented.
- **Checked by** `check_scroll_lists()` and `tools/_scroll_harness.lua` (what each list hands
  back built and unbuilt; the UI calls against stub components whose `MoveTo` carries children,
  as the engine's does; and the text and sparkline memo across a rebuilt panel), the house-list
  scene in `_layout_harness.lua`, `_sort_harness.lua`, `_log_harness.lua`,
  `_resource_overhaul_harness.lua`, and Trade's sections in `_nav_harness.lua`. 24 planted faults,
  24 caught (2026-10-02); the 25th, a special case for `lg` keys in `EX.short`, survived because
  the line did nothing, and was deleted.
- **To confirm in game:** the rows following the bar smoothly; rows below the window clipped by
  `list_clip`, and not taking clicks through it; the wheel reaching the list through
  `rows_holder`.

---

## 20. See also

`docs/CUSTOM_UI.md` - runtime `.twui.xml`, GUIDs, `MoveTo`, and the silent-failure
traps behind this panel.
