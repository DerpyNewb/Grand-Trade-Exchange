# The Grand Trade Exchange — complete reference

`derpy_zharr_exchange.pack`, which ships in-game as **the Zharr Exchange**. A live
commodities market, a stock exchange in Chaos Dwarf houses, a patron's tithe, a warehouse
and a war-shock model, on a panel of its own.

This is the **reference for what shipped**.

| | |
|---|---|
| Pack | `Modding Files/Modpacks/derpy_zharr_exchange.pack` |
| Size / md5 | 1,341,862 B / `dbf6aa4d4a476ff31584198bc49c55ee` (2026-09-09, deployed and byte-verified under the new name) |
| Rows | 641 DB across 10 tables, plus 1,768 loc = 2,409 |
| Runtime | `script/campaign/mod/zzz_derpy_chd_exchange.lua`, 9,159 lines, 262 `EX.*` functions (514 `EX.*` names in all, every one read — `check_no_orphans`) |
| Races | 8 covered, of the game's 27 cultures |
| Hard dependency | none |
| Multiplayer | supported since 2026-09-09, **never run on two machines** — §18 |
| Soft dependencies | MCT (settings), Cataph's Southern Realms (the eighth board; the base game covers the other seven) |

---

## 1. What it is

CA ships 17 tradeable resources, every one of them priced at a flat `trade_value` of 50, with
no price discovery anywhere in the game. The Exchange is that missing layer: each of those 17
goods gets a live price driven by what the world actually produces, who owns the production,
who is at war, what the AI houses are holding and what you yourself have been buying.

You reach it from a button on the campaign HUD. Inside are five views, a guide, and a market
you can trade against every turn.

**Five things you can do with gold in it:**

1. **Trade the 17 commodities.** Buy low, sell high, or corner a good and watch your own
   buying move the price against you.
2. **Hold a position** in the warehouse: a big enough pile grants a standing campaign bonus,
   and every unit costs rent per turn.
3. **Burn goods on the altar** for a five-turn buff — the offering.
4. **Buy shares in other Chaos Dwarf houses.** They pay a dividend every turn, and settle when
   the house dies — at a premium if *you* were the one who killed it.
5. **Pay the patron's tithe** when it is demanded, or refuse and take the wrath.

And one thing that happens to you whether you trade or not: the price of what your own regions
produce drives your vanilla trade income.

---

## 2. What ships

Seventeen files in the pack.

**Ten DB tables plus loc** (`derpy_chd_zharr_exchange` fragment in each):

| Table | Rows | What it carries |
|---|---:|---|
| `pooled_resources` | 17 | `derpy_chd_ex_hold_<good>` — where a position is held |
| `pooled_resource_factor_junctions` | 19 | the `other` factor each pool moves through - 17 of ours plus CA's two layer-2 pools |
| `campaign_group_pooled_resources` | 34 | 17 pools x 2 groups (CHD feature group + `wh_main_feature_all`) |
| `effect_bundles` | 211 | 8 races x (17 offerings + pleased + wrath) = 152, plus 51 warehouse tiers, plus 8 trade-income steps |
| `effect_bundles_to_effects_junctions` | 227 | the above, with the two patron bundles carrying two effects each |
| `campaign_groups` | 32 | 4 event-feed records per race |
| `campaign_group_members` | 32 | " |
| `campaign_group_member_criteria_values` | 32 | " |
| `event_feed_message_events` | 32 | " |
| `building_effects_junction` | 5 | the five Chaos Dwarf resource buildings that produce no trade good in vanilla — see §4.1 |
| `text/db/…loc` | 1,768 | every title, description and bulletin — 197 rows per race |

`building_effects_junction` is the **only** table here that edits a vanilla row's subject rather than minting a key of this mod's own, and so the only one that can collide with another mod: anything else touching those five buildings' effects wins or loses by load order, with no crash and no warning either way.

This pack **mints no effect of its own** — `effects_tables` is gone. Every bundle carries one of
CA's existing effects. The 798-row price ladder that used to dominate `effect_bundles` was
deleted on 2026-09-05 once the price stopped being an effect at all.

**Six loose files:**

```
script/campaign/mod/zzz_derpy_chd_exchange.lua        the whole runtime
script/campaign/mod/zzz_derpy_chd_exchange_prod.lua   779 buildings -> what each produces
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

`zzz_derpy_chd_exchange_prod.lua` is the production map, 779 buildings and what each makes per
turn, generated by `gen_zharr_exchange.write_production_lua`. It is a separate file because it
is data, and read lazily because mod scripts autoload in no set order.

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

### 4.2 The five shifts

The base rung is then moved by five independent terms, summed and clamped to [1, 42]:

| Shift | Source | Cap |
|---|---|---|
| **Pressure** | your own net lots bought, `PRESSURE_PER_RUNG` = 4 per rung | +/-6 (`PRESSURE_MAX` 24) |
| **Appetite** | world culture demand + war, see §9 | +/-`AI_MAX_RUNGS` = 2 |
| **Shock** | sacks, razes, sieges and raids, see §8 | +/-`SHOCK_MAX` = 6 |
| **Book** | what the AI houses are holding, `BOOK_PER_RUNG` = 30 units per rung | +/-`BOOK_MAX` = 2 |
| — | a delisted house freezes instead: its rung never moves again | — |

Every one of these truncates **toward zero**, never `math.floor` — flooring a signed value would
move a price *down* on a demand too small to move it up, and Lua 5.1 stringifies `-0`.

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
despise you, negative a discount from houses that like you. The two halves are asymmetric on
purpose — hostility runs to `HOSTILE_MAX` (0.25) because charging more can never mint gold,
while the discount is bounded by

```
friendly_cap = (1 - LADDER_STEP * (1 - spread)) / (1 + LADDER_STEP)
```

because a discount **can**. At the default spread of 0.10 that headroom is about one per cent,
so the Friendly discount slider does nothing much until the spread is raised. The tooltip says
so rather than leaving the player to wonder.

This is the round-trip algebra `check_spread()` guards, and it is why `spread`, `ladder_step`,
`sell_floor` and `friendly_max` are the four knobs a race profile is **forbidden** to touch.
The `easy` preset minted gold for months on a four per cent spread against a 1.08 step: selling
one rung up paid 1.0368x what you bought at, with no friendly discount involved at all.

---

## 5. Trading

`EX.trade(res, is_buy)` — and it is **two calls and nothing else**:

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

**Six ways a buy is refused**, each with the reason on the button, in its tooltip and in the log:

| | |
|---|---|
| Nothing on the map produces it | `EX.unavailable` — the rung is already clamped at 42, so a buy would be a no-op dressed as a trade. Measured: 10 bought and 10 sold back is exactly break-even. Selling stays open. |
| A house refuses | it holds >= `REFUSE_SHARE` (0.50) of the book, is in the bottom `REFUSE_RANK` of the stance spread, and you are at open treaty |
| The market is shut | >= `GUILD_CLOSE` (0.60) of the guild's book is at war with you |
| A house is at war | you cannot buy its own paper while fighting it |
| The house is delisted or dead | see §7.3 |
| The pool is not registered on your faction | charging for it would take the gold and grant nothing |

Selling is **always** open. A house that despises you is delighted to take your goods cheap, and
blocking a sale traps the player's capital with no exit — the lockout that actually hurts.

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
| Carved Obsidian | +10 winds of magic cap | Tusks | +4 research points |
| Marble, Timber | -6% construction cost | Exotic Animals | +10% Labour per battle * |
| Wine, Spices, Dwarf Beer | +4 public order | Medicinal Plants, Salt | +6% replenishment |
| Gemstones, Dyes, Elven Trinkets | +6% trade tariffs | Furs | +6% movement range |
| | | Pottery | -6% recruit cost |

\* Chaos Dwarfs only. The other seven races have no Labour pool, so `boon_over` swaps Exotic
Animals to +4 public order for them — otherwise the bundle applies, the effect moves nothing,
and the panel advertises a number that never arrives.

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

Pay with the same Buy button on the Offerings view (the pending demand takes precedence over the
ordinary offering price and ignores the cooldown). Paying grants the commodity's boon **plus**
`<patron>_pleased`: +3 public order and +5 leadership. Refusing — or letting `DEMAND_GRACE` = 3
turns lapse — applies `<patron>_wrath`.

**It is an event-feed message, not a dilemma.** A `DilemmaChoiceMadeEvent` listener that matches
a custom dilemma hard-crashes the game and bricks the save. `cm:show_message_event`'s last
argument indexes `event_feed_message_events`, which resolves through all four `campaign_group*`
tables; a record missing any one of them draws nothing at all.

Feed indices are per race so a Skaven player is not shown the Chaos Dwarf forge on a Trade
Disrupted bulletin — the picture is a column on the record and nothing can swap it at runtime:

```
""    7401-7404      emp_  7411-7414      cth_  7421-7424
skv_  7431-7434      teb_  7441-7444
                     slots: call, wrath, shock, delist
```

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
| captured | 0.5 | `CharacterCapturedSettlement` and its `Unopposed` twin |

`rebels` and `captured` were added 2026-09-09, and the event names cost more checking than the
weights did. **`FactionDestroyed` and `DeclaredWar` do not exist** — both were in the design and
neither is in CA's event index, and an event name that does not exist never fires and never
errors. `RegionRebels` carries `region()` directly rather than a garrison, unlike the other
three. `GarrisonOccupiedEvent` was **refused**: it appears in the index with no documented
context accessor, so what it carries would be a guess — and a listener reading a method the
context does not have fails inside a pcall and shocks nothing, forever, silently. It also almost
certainly double-counts a capture.

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

## 9. World appetite — how other factions move your prices

Two independent terms, summed and multiplied by `AI_GAIN` (6.0), then truncated and clamped to
+/-2 rungs.

**Culture.** Each culture's appetite for a good, weighted by its share of the world's
**regions** (not factions, and razed or besieged land is out of both supply and demand):

```lua
culture = sum over cultures of  CULTURE_WANTS[c][res] * share[c]
```

Positive is demand, negative is supply. 26 entries cover all 25 land-holding vanilla cultures
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
the board is the sum across all 26, and a large swing in one culture's share. An Empire collapse
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
"`<patron>` grants" as the Offerings column header and into "`<patron>` demands 8 Iron" in the
log, so a plural collective reads as *"The Ancestors grants"* with nothing anywhere to notice:
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

The other 19 cultures are **uncovered**, which is still the majority case. They get the commodities
market — layer 1 was never Chaos Dwarf — with the Offerings tab greyed (no altar) and the
Houses tab greyed (no shares in their people's houses), each with a reason on the tab.

### 11.1 Race profiles

A profile is a set of **multipliers** on whatever the difficulty preset and MCT have already
resolved — not a replacement. Skaven aggression composes with Hard rather than being erased by
it. A race that set absolute values would flatten every preset but `default`.

**Chaos Dwarfs carry no profile.** They are the baseline, at ×1 on everything.

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
- **Cathay — regulated.** The calmest board of the five, with books so thick that cornering
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

Twenty rows per page, 28px pitch. Row 21 would land below the panel: drawn, interactive and off
screen.

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

**There is no dismiss button.** The five tabs the player is about to use are already on screen
and the footer points at them; leaving IS the dismissal, and `set_mode` records it on the
way out rather than on the way in — marking it on arrival would spend the one showing on a
player who opened the panel and shut it again without reading a line. The flag is
**per-player**: two humans each meet the panel for the first time on their own turn. The
closing instruction lives in the two **footer** strings rather than in a row, which is what
bought back the two rows the paragraph breaks needed.

### Five views plus a guide, a log and the introduction

| View | Columns |
|---|---|
| **Trade** | Commodity, Buy, Sell, Output, Trend, Last 12 turns, Held / rent |
| **Stats** | Commodity, Output, Largest producer, Share, Cartel premium, Last 12 turns |
| **Offerings** | Commodity, Held, Cost, `<patron>` grants, Status |
| **Houses** | House, Price, Div, Seat, Trend, Last 12 turns, Held |
| **Log** | Turn, What happened |
| **Guide** | Term, What it means (2 pages, 28 lines; page 1 is at the 19-row ceiling, so the Worth line went on page 2). The Forge-goods line carries no number, because `l2_sell` is a difficulty knob and these lines are static text |

"Output", not "Supply" and not "Regions". Reported from play 2026-09-05: *"i always thought
supply is the amount of stocks that you can buy not the region"*. It is units produced across
the whole map per turn; buying never consumes it. What moves the price against you is pressure.

"Buy" and "Sell", not "Price" and "Sell" — with both numbers on screen, one column called
"Price" leaves the player working out which side of the spread it is.

### What the Log records, and what it does not

**Ten kinds of entry, from six writers.** Three are the player's own actions; the other seven
are the world's. Until 2026-09-09 only three of the world's were recorded and the AI houses
traded every turn with nothing anywhere saying so — asked for from play as *"add all logging
to ai so that player can see there is interaction between the mechanics and the ai"*.

| Entry | Written by | Driven by |
|---|---|---|
| Bought / Sold, with the markup and who set it | `EX.trade` | you |
| Buy refused, with the reason | `EX.trade` | you (one of the six refusals) |
| Trade refused — market not open to your people | `EX.trade` | you, uncovered culture |
| **The guild** — *n* houses traded, lots bought and sold, and the good most moved each way | `EX.build_world_log` | **the AI** — `step_books` at turn step 9 |
| **World appetite** — the footer's line, recorded when it *changes* | `EX.build_world_log` | **the world** — culture wants and the war index |
| **Dividends** — how many houses paid, and how much | `EX.pay_dividends` | **the AI** — turn step 18 |
| **Demand shock** — the rungs and the reason | `EX.announce_shocks` | **the world** — turn step 12 |
| Market **CLOSED** / **Reopened**, naming the chief belligerent | `EX.log_scan` | **the world** — guild war state |
| A house **refuses to sell** / **will deal again**, with its share of the guild book | `EX.log_scan` | **the AI** — its attitude and its book |
| **Delisted** — a house died, and what your shares settled for | `EX.log_settlement` | **the world** — via `check_delistings` at turn step 7 |

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

**Built once, written per player.** The books and the appetite are world state, so the decision
*"is this worth a line"* is made once and the lines are then flushed into each human's log. A
per-player version would log an appetite change for the first human and swallow it for everyone
after, because the first comparison is what stops it being a change.

**What is still silent:** the per-turn price move itself (the Trend column and the chart are its
record), and appetite drift too small to change the summary line.

**And `log_scan` still runs at DRAW time, not at turn start.** It is called from the Log branch
of `refresh_panel` and nowhere else, so its two edge-detected entries — the closure and the
per-house refusals — are only noticed when the Log view is opened, and **a closure that lifts
between two viewings is never recorded at all.** It was left there deliberately: both of its
lines name a faction mid-sentence, so moving them to turn time means deferring those names
first. That is the next thing to do here.

### Trade page 2: the deep chart

Trade has a second page, and it is the only page that is not a list. Clicking a commodity's
**name** cell on page 1 selects it (`EX.selected`); page 2 draws that one instrument full width
over forty turns.

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
offering cost in Offerings, so one static attribute cannot be true in all three. Every string is
under 60 characters so none needs CA's `Title||Body` split, which has only ever been proven to
work as literal XML and never through `SetTooltipText`.

**Footers.** Two lines each, split by meaning rather than by length: line 1 is your position,
line 2 is the world. Trade's line 2 carries the appetite readout —
`World at war: N%. Wanted: … Going begging: …` — and Houses' carries the guild line. Both cap
their clause lists at two names: the footer is one 880px component and the engine does not wrap,
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

---

## 13. Settings

### 13.1 Presets

Five: **Easy**, **Default**, **Hard**, **Ultra Capitalism**, **Custom**. The preset owns all 26
numeric knobs *and* the seven system switches.

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
| rent / tithe | **off** | on | on | on |

Easy is low **risk**, not low reward: a thin spread, most of a bad stake returned, cheap
storage, a slow and forgiving guild — and shares still paying double the default dividend.

### 13.2 MCT

`script/mct/settings/derpy_chd_zharr_exchange.lua`, generated. MCT loads every `.lua` under
`script/mct/settings/`, so the file only ever runs when MCT is installed and the mod is
functional without it.

Seven system switches, 26 sliders across six sections (Market, AI houses, Shares, Tithes, War
shocks, Race profile), a difficulty picker, **a Features section** and a debug section — ten
sections in all.

**The Features section holds the three kill-switches** (`feat_deep_history`,
`feat_demand_shocks`, `feat_appetite_drift`) and is the one economic-looking thing that is
**not** in `ECONOMIC` and so not locked in a campaign. That is deliberate and it is the whole
difference between these and the seven system switches above: a system switch is snapshotted so
a price you were quoted stays the price you are charged, while a kill-switch exists to be moved
*while* a bug is happening — the same argument the debug options carry. In multiplayer all three
are forced on, because reconciling a live model switch across machines is the MCT race
`EX.mp_ignores_mct` already refuses to run.

`check_features` derives its key set from `EX.FEATURE_DEFAULT` — the table `EX.feature` actually
reads — so a switch the script knows about that MCT never registers is a build failure, and so
is one MCT registers that the script has no default for. It also asserts a **call site** for
each, on the comment-stripped code: a key named only in the paragraph explaining why it exists
is exactly how `orders` and `deep_history` read as wired for a week. And `check_mct` now asserts
that every `set_assigned_section` names a section `add_new_section` creates, in both directions
— an option assigned to a section that was never made is registered, defaulted, and nowhere the
player can reach it.

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
price, house, demand, shock, ui. Plus two buttons, `Dump state` and `Dump supply`, fired as
custom events from the MCT file because it cannot see `EX` directly.

---

## 14. Turn order

`FactionTurnStart`, and the order is load-bearing at four points:

```
 1  snapshot()          FIRST - everything below reads a knob
 2  free_guild()        a new turn is new diplomacy; no stance memo outlives a turn
 3  check_demand()      punish an unpaid tithe before the altar asks again
 4  decay_pressure()
 5  rescan()            supply, owners, culture shares, war index, house regions
 6  share_shocks()      AFTER rescan, which is what measures the shares; before pricing
 7  check_delistings()  BEFORE apply_prices - a dead house must settle at its living price
 8  check_standing_sign()
 9  step_books()        AFTER delisting (dead houses have left the guild), BEFORE pricing
10  apply_prices()
11  remember_all()      AFTER pricing - one sparkline and one chart bar per TURN, not per reprice
11b build_world_log()   AFTER step_books, which fills EX.book_flow. BUILDS only, writes nothing
12  announce_shocks()   at full strength, before the decay - and logs the shock
13  decay_shocks()      AFTER pricing - a raze during the AI round prices at full strength
14  save_shocked()
15  apply_trade_income()
16  apply_stockpiles()  a tithe or raid may have crossed a tier boundary
17  charge_carry()      on the same holding the tier was just read from
18  pay_dividends()     AFTER delisting - a house dying this turn must not also be paid
19  maybe_demand()
19b flush_world_log()   LAST in the player block, so the world's lines sit above this
                        player's own rent and dividends once the log reverses them
```

Step 11 was a real bug: `remember_all` used to live inside `apply_prices`, which also runs 0.1s
after every buy and sell. A column headed "Last 12 turns" was showing the last 12 *reprices*,
and five trades in one turn threw away five turns of history for every commodity on the board.
Reported from play 2026-09-06 — *"everytime i buy, the last 12 turns moves"*.

Nothing runs at script root. `EX.init` is reached from both
`ScriptEventFirstTickAfterWorldCreated` and `cm:add_first_tick_callback`, and it binds the race
**before** the first scan — otherwise turn one's house-region tally is counted against the Chaos
Dwarf default whatever the player actually is.

A load is not a turn: `charge_carry`, `remember_all`, `share_shocks` and `check_delistings`
are deliberately absent from the first-tick path. Five reloads would otherwise be five rent days, one turn
filling the whole sparkline, and a second settlement payout.

---

## 15. Save state

All through `cm:set_saved_value` / `get_saved_value`, which store scalars only — so anything
list-shaped is a delimited string.

| Key | Holds |
|---|---|
| `zharr_rung_<res>` | current ladder rung |
| `zharr_hist_<res>` | sparkline history, 12 bars, delimited |
| `zharr_deep_<res>` | the chart buffer, 40 bars, delimited |
| `zharr_press_<res>` | your net pressure |
| `zharr_shock_<res>` / `zharr_shockwhy_<res>` | live shock and its cause |
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

`EX.strip_legacy_bundles` sweeps any `derpy_chd_ex_ladder_*` bundle left applied by a build
before 2026-09-05. Its `cm:remove_effect_bundle` calls are individually pcall-wrapped, so a save
from an older build is swept whether or not the key still resolves.

---

## 16. The toolchain

```powershell
py tools\gen_zharr_exchange.py --check      # write TSVs, no RPFM needed
py tools\gen_zharr_exchange.py --selftest   # 70 checks
py tools\gen_exchange_ui.py --selftest      # the three .twui.xml
py tools\import_zharr_exchange.py           # build the pack (needs RPFM open)
```

| Tool | Does |
|---|---|
| `gen_zharr_exchange.py` | 641 DB rows, 1,768 loc, the MCT file, the production map. 70 `check_*` functions |
| `gen_exchange_ui.py` | the panel, row and button `.twui.xml`; GUIDs by counter, every imagepath checked against the game's packs |
| `import_zharr_exchange.py` | packs it; runs **both** selftests first and refuses on a TSV-vs-`build()` row mismatch |

**Fifteen Lua harnesses** in `tools/_*_harness.lua`, plus a dozen more inlined in the
generator, run the shipped script under Lua 5.1.5 against stubbed campaign interfaces and read
back what it actually did. Discovery, prices, books, houses, layout, nav, sorting, tips, log,
store, MCT, multiplayer, race binding, race tuning, warehouse, shocks, footer bounds, header
widths, chart geometry, and the position total.

**One of the seventy is not about this mod's rules at all.** `check_no_orphans` scans every
`EX.*` the runtime defines and fails if nothing anywhere reads it — the runtime, the fifteen
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
  **stored under**. Changing it silently resets the difficulty, all 26 sliders and all seven
  switches for anyone who had configured them.

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

**Not yet run in a campaign:**

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
the cqi. Three ops: `buy`, `sell`, `offer`. The cqi is resolved by walking the human list —
`faction_for_command_queue_index` is in CA's interface index with no signature documented
anywhere.

**Singleplayer runs the same code.** `EX.humans()` is one entry, the subject is always that
entry, and `EX.mp_send` calls the op directly instead of broadcasting. So the only thing
multiplayer does differently is the network round trip — which is also the only thing a single
process cannot test.

### The subject

Per-player state is not threaded through sixty call sites; it is **swapped**. `EX.bind_player`
points `EX.shares_held`, `EX.LOG`, `EX.offer_until` and the five demand values at another
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
| Per player | `SAVE_SHARES`, `SAVE_OFFER`, `SAVE_OFFERINGS`, `SAVE_DEMAND`, `SAVE_DEM_RES/TIER/DUE`, `SAVE_LOG` | `EX.setp` / `EX.getp` — appends `@<faction>` |
| World | rungs, history, pressure, shocks, books, house list, delisted, the settings snapshot | `EX.setv` / `EX.getv` |

Both wrong answers are silent: an unscoped per-player key is two players robbing each other
*and* a divergent save; a scoped world key forks the price ladder and the market stops being one
market. `check_lua_mp()` asserts the split in both directions and that the declared `SAVE_*` set
is exactly those 21.

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
orders them against the first `FactionTurnStart`** — which is where `EX.snapshot()` freezes 30
values into the save. A client that has not received the host's settings yet would freeze the
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

---

## 20. See also

`docs/CUSTOM_UI.md` - runtime `.twui.xml`, GUIDs, `MoveTo`, and the silent-failure
traps behind this panel.
