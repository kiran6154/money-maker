# S6 measurement — wiring `target_pct` / `sl_pct` into the pipeline, before/after

**Run date:** 2026-08-31 · **Window:** 2024-01-01 → 2024-01-31 (same window as the
S4 pair) · **Data source:** `HISTORICAL_ICICI` · **Mode:** `app.mode=backtest` ·
**Code:** `6ed316b` **plus the S6 wiring change** (`TradeConfigRepository`
SELECT list + `TradeConfigScheduler` mappers + contract test). Full suite **85
tests, 0 failures** before either arm ran.

**One jar for both arms**, built 12:42:58 from that tree. Both arms therefore run
identical bytecode; the only thing that differs is two DB columns.

---

## What was varied

| | Arm A — "absolute" (behaviour before this change) | Arm B — "pct" (the signed-off outcome) |
|---|---|---|
| `trade_config.target_pct` | `NULL` | `0.2000` |
| `trade_config.sl_pct` | `NULL` | `0.3000` |
| `max_sl_points` | `60.0000` — **seeded in both arms** | `60.0000` — **seeded in both arms** |
| `trail_ladder` | `25:2,…` — **seeded in both arms** | `25:2,…` — **seeded in both arms** |

With the pct columns null, `OrderService.bracketAtEntry` takes its
absolute-column fallback (`trade_config.target` / `stop_loss`) — exactly the
behaviour every trade has had since changeset 027. The 036 bracket is live in
both arms, so S6's effect is isolated from S4's.

**Controls that held.** `trade_config` count and max id were `126` / `1178`
before Arm A, after Arm A, and after Arm B — no config was regenerated between
arms. Both arms replayed **1047 ticks** across the same 22 trading days, the same
18 configs, ledger cleared before each.

### Arm A independently reproduces the S4 baseline

Arm A is the same DB state as S4's Run B, run on the newer merged build. Its
ledger is **byte-identical to `analysis/s4-measurement/run-B-ledger.csv` on every
column except the autoincrement `id`** — 16 rows, −141.10, same exit mix. That is
a free double-check of two separate claims: the merged live-safety infra
(`forceCloseOpenPositions` broker exit, day-summary gating) does not move the
backtest ledger, and the S6 wiring change is behaviourally inert while the
columns are null.

---

## Headline result

| Metric | Arm A (absolute) | Arm B (pct) | Δ |
|---|---:|---:|---:|
| Trade count | 16 | **21** | +5 |
| **TARGET hit-rate** | **12.5%** (2/16) | **33.3%** (7/21) | **+20.8 pp** |
| Win rate (P&L > 0) | 43.8% (7/16) | 42.9% (9/21) | −0.9 pp |
| Mean P&L per trade | −8.8188 | **−6.0667** | +2.75 |
| **Total P&L** | **−141.10** | **−127.40** | **+13.70** |
| Mean win / mean loss | +22.20 / −32.94 | +26.31 / −30.35 | |
| Best / worst | +45.35 / −61.30 | +45.80 / −61.30 | |

P&L is **per share** (premium points); `quantity = 75` on every row, so
lot-multiplied totals are **−10,582.50** (A) and **−9,555.00** (B), a **+1,027.50**
improvement. Charges are not modelled.

### Exit-reason mix

| Exit reason | Arm A | Arm B |
|---|---:|---:|
| `TARGET` | 2 | **7** |
| `SIGNAL` | 5 | 5 |
| `STOP_LOSS` | 3 | 5 |
| `TRAIL_SL` | 6 | **4** |
| `FORCE_CLOSE` | 0 | 0 |

**The percentage bracket does what 027 said it would: it converts exits into
`TARGET` hits.** It is still a losing month either way.

### Beside 027's offline claim

027's sweep reported TARGET hit-rate **45.4% → 53.9%** moving from a flat 30/30
points bracket to 20%/30% of entry premium. This run moves **12.5% → 33.3%** —
**same direction, larger delta, far lower absolute level.** The two are not
comparable as levels, for three reasons worth stating so nobody reads the gap as
a contradiction:

1. **027 was an offline sweep with no 036 bracket.** Here the ladder is live in
   both arms and takes 6 and 4 exits respectively that would otherwise have had a
   chance to reach the target — `TRAIL_SL` competes directly with `TARGET`.
2. **027 replayed *every* 5-minute candle as a hypothetical entry** (ATM ±3,
   09:20–14:30, first touch on the 5-minute high/low). The pipeline only takes
   entries that pass the SMA cross, the premium band, the daily cap and the
   parallel cap — 21 trades in a month, not thousands.
3. **027's "before" was a flat 30/30.** Arm A's absolute targets are the
   detector's ATR-derived per-config values, ranging 18.44 to 67.03 — a different
   and generally worse "before" than a flat 30.

---

## The ceiling interaction — it inverts

This is the part the S4 numbers could not show, and it materially changes how
that entry's ceiling result should be read.

| | Arm A (absolute) | Arm B (pct) |
|---|---:|---:|
| rows opened with `stop_loss_at_entry == 60.00` (i.e. the ceiling bound) | **14 / 16 (88%)** | **5 / 21 (24%)** |

Per config, the bracket actually written at entry:

| config | entry | A target | A stop | B target | B stop | pct-derived stop before the ceiling |
|---|---:|---:|---:|---:|---:|---|
| 1072 | 199.45 | 41.69 | 60.00 | 39.89 | 59.84 | 59.84 — under the ceiling |
| 1080 | 126.50 | 18.44 | 27.65 | 25.30 | 37.95 | 37.95 — under |
| 1081 | 80.05 | 51.80 | 60.00 | 16.01 | 24.02 | 24.02 — under |
| 1083 | 102.65 | 67.03 | 60.00 | 20.53 | 30.80 | 30.80 — under |
| 1086 | 229.80 | 42.28 | 60.00 | 45.96 | 60.00 | 68.94 → **capped at 60** |

**Wiring the percentage bracket largely disarms the 036 ceiling.** Under the
absolute columns the detector's ATR-derived stops were frequently above 60, so
the ceiling bound on almost every trade. Under `sl_pct = 0.30` the stop scales to
the premium, and on an 80–250 band only entries above ~200 produce a stop above
60 — which is precisely the binding condition **S4's entry originally claimed and
which was false at the time it was written**. It is true *now*, because of this
change. S4's measured "ceiling bound on 4 of 5 configs" describes a world that no
longer exists.

The `TRAIL_SL` drop (6 → 4) has the same root: with targets pulled down to 20% of
premium, two trades reached `TARGET` before the ladder's first rung could take
them (22000 PE on 01-16, `TRAIL_SL +1.95` → `TARGET +21.00`, twice).

---

## Where the +13.70 came from

All 16 of Arm A's trades recur in Arm B on the same (config, strategy, leg,
entry_time); Arm B adds 5; none are lost.

| | P&L |
|---|---:|
| Arm A total | **−141.10** |
| effect on the 16 **matched** trades | **−10.25** |
| effect of the 5 **newly admitted** trades | **+23.95** |
| Arm B total | **−127.40** |

**Read that carefully: on the trades both arms took, the percentage bracket was
slightly *worse*.** The net gain came entirely from entries the pct bracket
admitted — the same `no_of_parrellel_trades = 1` slot-freeing mechanism S4 hit.

Matched trades that changed exit (11 of 16 were unchanged):

| entry_time | leg | s | A exit | A P&L | B exit | B P&L | Δ |
|---|---|---|---|---:|---|---:|---:|
| 2024-01-16 09:25 | 22000 PE | 1 | TRAIL_SL | +1.95 | **TARGET** | +21.00 | **+19.05** |
| 2024-01-16 09:25 | 22000 PE | 2 | TRAIL_SL | +1.95 | **TARGET** | +21.00 | **+19.05** |
| 2024-01-18 12:00 | 21400 CE | 1 | SIGNAL | +43.00 | **TARGET** | +32.45 | −10.55 |
| 2024-01-25 09:15 | 21400 CE | 1 | TARGET | +45.35 | TARGET | +26.45 | −18.90 |
| 2024-01-25 09:15 | 21400 CE | 2 | TARGET | +45.35 | TARGET | +26.45 | −18.90 |

The last three are the cost of a *smaller* target: config 1086's absolute target
was 42.28 while 20% of an 89.30 entry is 17.86, so the trade banks less on a move
it would have ridden further. The first two are the benefit: config 1081's
absolute target of 51.80 was unreachable on an 80.05 premium in the time
available, so the trade sat until the ladder yanked it at +1.95; at 20% the
target is 16.01 and it hits.

New entries in Arm B:

| id | entry | leg | s | timeframe | exit | P&L |
|---:|---|---|---|---|---|---:|
| 1413 | 2024-01-16 11:45 | 22100 PE | 1 | 5min/SMA50 | STOP_LOSS | −31.40 |
| 1414 | 2024-01-16 11:45 | 22100 PE | 2 | 5min/SMA50 | STOP_LOSS | −31.40 |
| 1418 | 2024-01-18 12:40 | 21300 CE | 1 | 5min/SMA50 | SIGNAL | −4.85 |
| 1424 | 2024-01-25 09:30 | 21200 CE | 1 | 15min/SMA50 | TARGET | +45.80 |
| 1425 | 2024-01-25 09:30 | 21200 CE | 2 | 15min/SMA50 | TARGET | +45.80 |

3 of 5 lost; the pair of +45.80 winners carried the subtotal.

---

## Caveats

1. **The net gain rests on newly admitted entries, not on better exits.** The
   matched-trade effect is −10.25. A different window that did not free the
   parallel slot at a lucky moment could easily invert the sign.
2. **Small, non-independent sample.** 16 and 21 rows; every config is tagged
   `strategy_ids = '1,2'` so rows come in near-duplicate Strategy1/Strategy2
   pairs (~11 independent trades in Arm B). The +23.95 new-entry subtotal is
   really two independent trades.
3. **Both arms lose money on this window.** The change improves a losing month
   from −141.10 to −127.40. Nothing here says the strategy is profitable; it says
   the percentage bracket is the better of the two brackets on this window, by a
   margin smaller than the noise the sample can resolve.
4. **The 036 ceiling is now largely inert** (24% of entries vs 88%). If the
   ceiling was doing useful work, it is doing much less of it now — that is an
   input to the still-open S4 decision, not something settled here.
5. **S8 is still present.** Orders on 22200 PE at 11:55 (ids in both arms) are
   the stale-cached-strike entries recorded as S8; unchanged by this measurement.

---

## Artifacts

| File | Contents |
|---|---|
| `config-snapshot-before.csv` | the 18 Jan-2024 configs with their pct values as seeded, taken before anything was touched; the source the Arm B restore was driven from |
| `trade_order-preexisting-s4-runB.csv` | the 16 rows left by the S4 measurement, exported before the table was cleared |
| `run-A-ledger.csv` | Arm A (absolute), 16 rows |
| `run-B-ledger.csv` | Arm B (pct), 21 rows |
| `RESULTS.md` | this file |

**End state:** `target_pct = 0.2000` / `sl_pct = 0.3000` **restored** on all 18
configs (verified by `SELECT`) — the percentage bracket is live, which is the
signed-off outcome. `max_sl_points` / `trail_ladder` untouched and still seeded.
`trade_order` holds Arm B's 21 rows.
