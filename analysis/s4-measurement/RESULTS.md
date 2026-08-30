# S4 measurement — the 036 exit bracket, before/after

**Run date:** 2026-08-31 · **Window:** 2024-01-01 → 2024-01-31 (the Jan-2024 NIFTY
option series changeset 027 was measured on) · **Data source:** `HISTORICAL_ICICI`
· **Mode:** `app.mode=backtest` · **Code:** working tree at `f64af84`
(post-`b194155`), **unmodified** — the only thing that differs between the two runs
is two DB columns.

---

## What was varied

| | Run A — "035 semantics" | Run B — "036 semantics" |
|---|---|---|
| `trade_config.max_sl_points` | `NULL` (cap inert) | `60.0000` |
| `trade_config.trail_ladder` | `NULL` (no trailing) | `25:2,50:25,75:50,100:75` |

Everything else identical: same 18 `trade_config` rows, same window, same JVM
args, same log level, ledger cleared before each run, app restarted between runs
so `TradeConfigScheduler.configsCache` and `SharedData.combinedDto` were cold.

**Controls that held.** `trade_config` count and max id were `126` / `1178`
before Run A, after Run A, and after Run B — the EOD detector was idempotent and
wrote nothing, so the two runs saw the same config set. Both runs replayed
**1047 ticks** across the same 22 trading days. Run A's ledger carries
`trail_ladder_at_entry = NULL` and `trail_sl_at = NULL` on every row and the
uncapped `stop_loss_at_entry` values (62.53 / 77.69 / 100.55 / 63.42), confirming
the feature really was inert in A and live in B.

---

## Headline result

| Metric | Run A (035) | Run B (036) | Δ |
|---|---:|---:|---:|
| Trade count | 12 | **16** | +4 |
| Win rate (P&L > 0) | 58.3% (7/12) | **43.8%** (7/16) | −14.5 pp |
| Mean P&L per trade | **+9.7417** | **−8.8188** | −18.56 |
| **Total P&L** | **+116.90** | **−141.10** | **−258.00** |
| Best / worst trade | +45.20 / −53.65 | +45.35 / −61.30 | |

**P&L is per share (premium points)** — `trade_order.profit` is written by
`OrderService.perShareProfit` and is entry-minus-exit on the option leg, with no
lot multiplier applied. Every row carries `quantity = 75`, so the lot-multiplied
equivalents are **+8,767.50** (A) and **−10,582.50** (B), a **−19,350** swing. No
charges/brokerage are modelled anywhere in the ledger.

### Exit-reason mix

| Exit reason | Run A | Run B |
|---|---:|---:|
| `SIGNAL` | 8 | 5 |
| `TARGET` | 4 | 2 |
| `STOP_LOSS` | 0 | 3 |
| `TRAIL_SL` | 0 | **6** |
| `FORCE_CLOSE` | 0 | 0 |

---

## Where the swing came from

All 12 of Run A's trades reappear in Run B with an identical
(config, strategy, leg, entry_time); Run B adds 4 that 035 never took.

| | P&L |
|---|---:|
| Run A total | **+116.90** |
| effect of the bracket on the 12 **matched** trades | **−226.10** |
| effect of the 4 **newly admitted** trades | **−31.90** |
| Run B total | **−141.10** |

Per matched trade — 5 of 12 changed exit, 7 were untouched:

| entry_time | leg | strat | A exit | A P&L | B exit | B P&L | Δ |
|---|---|---|---|---:|---|---:|---:|
| 2024-01-04 09:30 | 21400 CE | 1 | SIGNAL | −53.65 | **STOP_LOSS** | −60.35 | −6.70 |
| 2024-01-04 09:45 | 21400 CE | 2 | SIGNAL | −49.05 | SIGNAL | −49.05 | 0 |
| 2024-01-12 15:10 | 21900 PE | 1 | SIGNAL | +8.90 | SIGNAL | +8.90 | 0 |
| 2024-01-12 15:10 | 21900 PE | 2 | SIGNAL | +8.90 | SIGNAL | +8.90 | 0 |
| 2024-01-16 09:25 | 22000 PE | 1 | SIGNAL | −1.85 | **TRAIL_SL** | +1.95 | **+3.80** |
| 2024-01-16 09:25 | 22000 PE | 2 | SIGNAL | −1.85 | **TRAIL_SL** | +1.95 | **+3.80** |
| 2024-01-18 12:00 | 21400 CE | 1 | SIGNAL | +43.00 | SIGNAL | +43.00 | 0 |
| 2024-01-18 12:55 | 21300 CE | 2 | SIGNAL | −13.80 | SIGNAL | −13.80 | 0 |
| 2024-01-25 09:15 | 21200 CE | 1 | TARGET | +45.20 | **TRAIL_SL** | −23.30 | **−68.50** |
| 2024-01-25 09:15 | 21200 CE | 2 | TARGET | +45.20 | **TRAIL_SL** | −23.30 | **−68.50** |
| 2024-01-25 11:45 | 21100 CE | 1 | TARGET | +42.95 | **TRAIL_SL** | −2.05 | **−45.00** |
| 2024-01-25 11:45 | 21100 CE | 2 | TARGET | +42.95 | **TRAIL_SL** | −2.05 | **−45.00** |

The ladder helped once (+3.80 × 2, on a trade 035 exited flat) and cost heavily
four times, all by pre-empting a `TARGET` that 035 went on to reach.

### (a) The ceiling

`max_sl_points = 60` bound on **4 of the 5 configs that actually traded**:

| config | A `stop_loss_at_entry` | B `stop_loss_at_entry` |
|---|---:|---:|
| 1072 | 62.53 | 60.00 |
| 1080 | 27.65 | 27.65 *(under the ceiling — unaffected)* |
| 1081 | 77.69 | 60.00 |
| 1083 | 100.55 | 60.00 |
| 1086 | 63.42 | 60.00 |

It produced all 3 `STOP_LOSS` exits (035 had none) and cost −6.70 on the one
matched trade it changed.

> **The S4 entry's stated binding condition does not describe the running
> system.** It says the ceiling "only binds above a ~200-point entry with
> `sl_pct = 0.30`". Because **S6** is still unwired, `sl_pct` never reaches the
> pipeline: `bracketAtEntry` falls back to the absolute `trade_config.stop_loss`
> column, and the ceiling is compared against *that*. Confirmed on the ledger —
> e.g. order 1371 opened at 229.80 with `target_at_entry = 42.28`, the config's
> absolute `target`, not 229.80 × 0.20 = 45.96. So the ceiling binds wherever the
> absolute stop exceeds 60, which was 8 of the 18 window configs.

### (b) The ladder

6 `TRAIL_SL` exits. `peak_profit` giveback (peak minus realised):

| id | leg | peak | realised | giveback | floor |
|---:|---|---:|---:|---:|---:|
| 1379 | 22000 PE 01-16 09:25 | 25.15 | +1.95 | 23.20 | 2.00 |
| 1380 | 22000 PE 01-16 09:25 | 25.15 | +1.95 | 23.20 | 2.00 |
| 1385 | 21200 CE 01-25 09:15 | 35.30 | **−23.30** | 58.60 | 2.00 |
| 1386 | 21200 CE 01-25 09:15 | 35.30 | **−23.30** | 58.60 | 2.00 |
| 1389 | 21100 CE 01-25 11:45 | 25.90 | **−2.05** | 27.95 | 2.00 |
| 1390 | 21100 CE 01-25 11:45 | 25.90 | **−2.05** | 27.95 | 2.00 |

**Total giveback 219.50 points; mean 36.58 per trailed trade.**

Two things stand out:

1. **Every trailed exit fired off the first rung (`25:2`), and none reached the
   second.** The ladder as configured is effectively a single rung on this
   window: peak crosses 25, the floor goes to +2, and the trade is out.
2. **4 of the 6 `TRAIL_SL` exits closed RED**, at −23.30, −23.30, −2.05, −2.05.
   The S4 entry states "the ladder can only exit a trade *green*" — **that is
   false as measured.** The floor is only tested on 5-minute monitor ticks, so a
   bar that travels far enough between ticks blows straight through it:
   order 1385 was at peak +35.30 on the 09:20 tick and −23.30 on the 09:25 tick,
   and `thresholdBreach` labelled it `TRAIL_SL` because `pnl <= trailSl` was
   satisfied from far below. The label says "trailed", the fill says "gapped
   through the floor". This is not the dead-zone question; it is a separate
   property of the design and is the largest single contributor to the swing.

---

## S1 — `Strategy2` SELL entries on the first settled bar of the session

`trade_order.entry_time` is the **decision candle's timestamp**
(`TradeSignal.signalTime = lastCandle.getTimestamp()`), not the tick time. An NSE
session opens 09:15, so on every timeframe the session's first settled bar is the
one stamped **09:15** (5-minute settles at 09:20, 15-minute at 09:30).

**From Run B's ledger:** 8 `Strategy2` SELL entries, of which **2 fell on the
first settled bar of their session**:

| timeframe | first-bar entries / all Strategy2 entries |
|---|---|
| `5min` | **1 / 5** |
| `15min` | **1 / 3** |
| total | **2 / 8 (25%)** |

| id | entry | timeframe | leg | exit | P&L |
|---:|---|---|---|---|---:|
| 1386 | 2024-01-25 09:15 | 5min/SMA200 | 21200 CE | TRAIL_SL | **−23.30** |
| 1388 | 2024-01-25 09:15 | 15min/SMA50 | 21400 CE | TARGET | **+45.35** |

(Run A, for reference: 6 Strategy2 SELL entries, 1 on the first settled bar —
id 1372, the same 21200 CE, which under 035 exited `TARGET +45.20`.)

Both first-bar entries land on the same session, 2024-01-25, and they point in
opposite directions (−23.30 and +45.35), so this window cannot say whether the
inert slope filter helps or hurts. 2 observations is far too small a subset to
compare against the rest; S1's own text asks for exactly this count, and the
honest answer is that the count exists but the P&L comparison it was meant to
enable does not yet have the sample to support it.

## S7 — same-leg re-entries within one candle interval

**Zero, in both runs.** No trade in either ledger re-enters the same
(config, strategy, option_token) within one candle interval of that leg's
previous exit — so the re-entry set is empty and there is no P&L comparison to
make against the rest.

The flip-flop pattern S7 was opened on came from the 2024-01-02…04 verification
run of 2026-08-30, which predates the stale-bar guard (S3) and the
`latestCachedCandle` fix. On the current code over the full month the pattern
does not reproduce: the daily cap (`numberOfTradesPerDay = 5`) is nowhere near
reached — the busiest config-day is 1086 on 2024-01-25 with 3 entries per
strategy — and `SIGNAL` is no longer the only exit reason.

---

## Anomalies and caveats

1. **The bracket changed the trade *count*, not just the exits.** 036 admitted 4
   entries that 035 blocked. Mechanism: `no_of_parrellel_trades = 1`, so an
   earlier exit frees the slot and lets a later signal through that 035 was still
   holding the slot against. Verified in the Run B log — order 1379 is closed
   (`[position] CLOSE orderId=1379`) *before* `[order] OPEN id=1381` on the
   following tick, so the cap was correctly enforced in both runs. The
   consequence is that A and B are not a matched pair of the same 12 trades, and
   the decomposition table above is the honest way to read the difference.

2. **The sample is small and not independent.** 12 and 16 rows. Every config in
   the window is tagged `strategy_ids = '1,2'`, and Strategy1 and Strategy2
   agreed on all but one entry, so the rows come in near-duplicate pairs — there
   are only ~8 independent trades in Run B. The whole −258.00 swing rests on 5
   changed matched trades and 2 new ones, and −137.00 of it is a single 2024-01-25
   session. **Do not treat this as a statistically settled result**; it is one
   valid before/after pair on the window S4 asked for, and it is enough to say
   the ladder as configured hurt on this window, not enough to size the effect.

3. **A stale intra-day signal fired one of the new entries.** Orders 1381/1382
   opened at 142.80 — the close of the bar stamped 11:55 — on a tick after 12:45,
   by which time that leg was trading near 191. The identical signal line
   (`time=2024-01-16T11:55`, same open/close/SMA) was re-emitted on roughly 20
   consecutive ticks. Recorded as **S8** in `STRATEGY_ANALYSIS_TODO.md`; not
   fixed, and not caused by 036 (036 only exposed it by freeing the slot).

4. **Run A had zero `STOP_LOSS` and zero `FORCE_CLOSE` exits.** 8 of 12 exits
   were `SIGNAL`. Worth noting when comparing against the older runs quoted
   elsewhere in the docs.

---

## Artifacts

| File | Contents |
|---|---|
| `config-snapshot-before.csv` | the 18 Jan-2024 `trade_config` rows as seeded by 036, taken before anything was touched; the source of truth the restore was driven from |
| `trade_order-preexisting.csv` | the 105 ledger rows that existed before this measurement (exported, then the table was cleared) |
| `run-A-ledger.csv` | Run A's 12 rows, full columns |
| `run-B-ledger.csv` | Run B's 16 rows, full columns |
| `RESULTS.md` | this file |

**End state:** `trade_config` restored to the exact seeded 036 values
(`max_sl_points = 60.0000`, `trail_ladder = '25:2,50:25,75:50,100:75'` on all 18
rows, verified by `SELECT`); `trade_order` holds Run B's 16 rows.
