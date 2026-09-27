# Strategy lab

Prototype bench for NIFTY futures strategies before they are coded into money-maker.
Every strategy is the same **foundation engine** run with its own rule settings, one file per strategy in `strategies/`.

> **Where it sits:** `research/strategy_lab/` inside money-maker. It is standalone Python (3.10, `requests`, `pymysql` for
> `tools/kitecreds.py`) and is **not** part of the Spring Boot build, its schema (SQLite `strategy_lab.db`, not Liquibase)
> or its `Strategy` beans. Nothing here places orders. Candle data is read from `D:/nifty/…` (see *Data*); the Kite
> download tools reuse the app's Zerodha session from `broker_session` and `application.properties`.
> Commit history before the move lives on as the first two commits of this folder (`foundation-v1`, `variants-v1`).

## Foundation (engine.py)
swings (Pine port) → protected level → CHoCH / BOS → AVWAP pair from previous SH & SL at each CHoCH → SETUP → trade

- **Protected low (uptrend):** latest unbroken SL that sat below the trend AVWAP when it confirmed; protected high mirrors it.
- **CHoCH:** protected level broken; trend flips if the AVWAP is broken too.
- **SETUP:** after a CHoCH, both pair AVWAPs slope with it (vs previous candle) and a candle closes beyond the CHoCH candle low (PE) / high (CE).
- **Exit:** stop loss (per `sl_rule`), else close of the next CHoCH candle.
- Swing confirmation, BOS and protected-level use-up break by touch or close (`break_mode`); the CHoCH — the break of the
  protected level and the AVWAP check for a flip — has its own `choch_mode` (defaults to `break_mode`).

## Strategies (`strategies/strategy_<n>.json`)
| Code | Name | Timeframe | CHoCH | Stop loss | Note |
|---|---|---|---|---|---|
| `ST1` | Strategy 1 | 1 min | touch | previous swing | the foundation rules on 1-minute candles |
| `ST2` | Strategy 2 | 5 min | touch | CHoCH candle | the foundation rules on 5-minute candles |
| `ST3` | Strategy 3 | 1 min | **close** | previous swing | Strategy 1, CHoCH needs a close beyond the level |
| `ST4` | Strategy 4 | 5 min | **close** | CHoCH candle | Strategy 2, CHoCH needs a close beyond the level |
| `ST5` | Strategy 5 | 1 min | touch | previous swing | Strategy 1 SETUPs through the **Foundation-Zone gate** (`entry_rule: fz_v1`, see *FZ* below) |
| `ST6` | Strategy 6 | 5 min | touch | CHoCH candle | Strategy 2 SETUPs through the Foundation-Zone gate |

Each file holds one strategy: `code`, `name`, `description`, design `timeframe`, `warmup_days`, `rules`
(`break_mode`, `choch_mode`, `avwap_weight`, `sl_rule`, `entry_rule`, `exit_rule`), `lot_size`, `capital`, per-type charges and
slippage (`types`), option settings (`options`: expiry types, strike choices / default, ATR period) and its `backtests`.
**Add a strategy:** copy a file to `strategy_<n+1>.json`, give it a new `code` and `name`, change the rules, run `python lab.py`.
Shared inputs live in `config/data.json` (candle files) and `config/charges.json` (charge schedules). Old rows whose file was
removed are disabled in the database, never deleted.

## Strategy → type → scheme
| Level | Values | Where it is set / seen |
|---|---|---|
| **Strategy** (`family`) | Strategy 1 … Strategy 6 | one card each: rules, timeframe, SL; the card's **options bar** holds option **expiry** (Weekly / Monthly) and **strike**, shared by both option types |
| **Type** (one `strategy` row each) | Futures (`ST2`) · Options (via futures) (`ST2_FB`) · Options (standalone) (`ST2_NB`) | a row on the card |
| **Scheme** | Long + short (default) · Long only · Short only | the Total / Long / Short columns on the card, and the scheme switch above the chart |
| Position (per trade) | long / short | trades table |
| Instrument (per trade) | FUT / CE / PE | trades table and one breakdown table — never a separate group |

- **Futures:** long future on a future-long signal, short future on a future-short signal.
- **Options (via futures):** the futures' signals traded in options — long CE and short PE on future long, long PE and short CE on future short.
- **Options (standalone):** the engine on the option's own chart, independent of the futures — long on bullish setups, short on bearish setups.

Every type runs long + short once; long only and short only are its long and short halves (same signals, same fills), stored as
`stats_long` / `stats_short` next to `stats`. Below the chart: KPIs (with long and short cards in the long + short scheme) and tabs —
Trades, Cumulative P&L (total / long / short lines), Daily P&L, Breakdown (position, signal, instrument, exit reason, entry time,
holding), Expiry & strike, Signals, Config, Rules. Short option P&L is sell-at-entry, buy-at-exit; margin is not modelled.
Earlier rows (`*_OF/_OB/_OS/_ON/_FL/_FS/_NL/_NS`) are kept disabled.

**Option data (`option_source = WEEKLY_LOCAL`).** Weekly contracts: the nearest expiry at least `expiry_min_days` (1) calendar
days away, so expiry day rolls to the next week. Prices come from the local ICICI weekly files under `weekly_dir`
(`nifty_options` 5-minute, `nifty_options_1minute` 1-minute chunks) and from the full Kite chain for the 29-Sep expiry
(`tools/kite_options.py`). The local files only hold strikes near the ATM of the day before expiry (a hindsight window), so they
supply prices only: a strike picked from spot that is not in the file is **skipped and reported**, never substituted. A position
still open at expiry closes at the contract's last candle (`expiry`). Coverage gaps: 15-Sep and 22-Sep expiries failed to
download (5-minute); the local 1-minute files hold only 4–5 strikes per side, so 1-minute option variants price few signals.

**Expiry type (`expiry_types = WEEKLY,MONTHLY`).** Option variants run once per expiry type × `strike_choices` entry; results
are keyed `W-<strike>` / `M-<strike>` and the dashboard has Expiry and Strike selectors (default `W-ATR2`). Weekly = nearest
weekly expiry; monthly = nearest month-end expiry (28 Jul, 25 Aug, 29 Sep here), both at least `expiry_min_days` away. In the
last week of a month they are the same contract. Monthly 29-Sep uses the full Kite chain, so 1-minute monthly results cover
the in-sample period fully.

Strike choices: default `ATR2` = spot ± 2×ATR(14) of the timeframe, OTM, rounded to 50; also `ATM`, `ITMn`, `OTMn`. Spot from `tools/kite_spot.py`. Slippage per side is `slippage_pts` (futures 5, options 0.5).
Charges: `ZERODHA_NFO_FUT` / `ZERODHA_NFO_OPT` in `charge_schedule`.

Fills: entry at the SETUP candle close; stop at the worse of candle open and stop, or the session's first candle close.
Look-ahead check: `python tests/test_truncation.py`.

## FZ: the Foundation-Zone gate (Strategies 5 and 6)
`ST5` (Strategy 1 rules, 1 min) and `ST6` (Strategy 2 rules, 5 min) run the Foundation engine unchanged and then gate every
Foundation SETUP against a memory of price bands (`rules.entry_rule = "fz_v1"`). `engine.py` is not modified: `fz.py` reads a
frozen view of its output (swings, SETUPs, CHoCHs, the protected level) and the bars, never its trades, exits or final-state fields.

- **Bands.** ± `band_half_width` around a mid. **A** bands are born when a swing becomes the protected level (dated at the first
  protected bar; visit 1 backfilled from the swing bar). **B** bands are born when the last `cluster_bars` same-session closes sit
  within `cluster_width` (on the transition into the sit). A candidate overlapping a band by `merge_overlap` merges into the one
  it overlaps most; the survivor keeps its edges, id and history. No band is ever deleted.
- **Memory = the file.** The band memory starts at the file's first session, so every FZ window (All data, Design, Unseen, 1M)
  is a date slice of one run (`same_sample = file_start`). The Foundation book FZ is compared with comes from that same run, so
  it can differ from ST1's / ST2's independent runs, which re-warm from each window's start (`own_warmup`).
- **Card (per bar, as-of, never rewritten).** The *ref band* is the band whose visit is live; a visit ends only on `leave_closes`
  consecutive closes outside it on one side (a single close inside a neighbouring band does not end it). The card holds the
  band, visit n, this / first visit bars and volume, the band just left, the session bar, the opening gap and the **read**,
  first match: LEAVE (of the band just left, for `leave_ttl_bars` while no close comes back inside or crosses its mid) → HUNT
  (1m: one close out and back in; 5m: a wick beyond an edge by `hunt_min_depth_atr` × ATR14 with both closes inside; a volume
  burst of `hunt_burst` when volume is live) → REJECT (a wick within `reject_tol` of an edge, close nearer the mid than the open)
  → FIRST_PRINT (visit 1) / ACCEPTED (`accept_bars` lived and volume ≥ `accept_vol_ratio` × the first visit's) / THIN / RECYCLE
  → PENDING (the first close outside) → NEW. One live visit at a time wins over a return (evaluation D01): a close back inside
  the band just left ends its LEAVE and marks that band's leave as failed (`last_leave_failed` on the card while it is the ref
  band), but it opens visit n+1 on that band only when no other band holds the live visit; otherwise the neighbour keeps the
  visit and the bar is counted as `leave_return_no_visit` (Zone gate tab, card statistics; docs/STRATEGY_ANALYSIS_TODO.md S40 c).
- **Gate at each Foundation SETUP**, first match: **BLOCK** (no watch) for `in_position`, `clock` (bar open ≥ `no_entry_from`),
  `open_pierce` (in the first `open_bars`, the bar crosses an edge of a band last visited on an earlier day with fewer than
  `open_sit_closes` closes inside today), `hunt_fade` (a SETUP in the pierce direction of a HUNT within `fade_block_bars`) or
  `new`; **TAKE** = Foundation's own position (branch 1 a LEAVE in its direction, checked against `leave_far_side`, and refused
  while `session_bar < open_quiet_bars` when the leave's outside closes include the session's first bar, i.e. a gap leave;
  branch 2 a FIRST_PRINT in the visit's entry direction after `first_print_min_bars`; branch 3 an ACCEPTED defend after a HUNT
  or REJECT at the opposite edge within `defend_window_bars`); else **WATCH** on the band holding the close (WATCH_EDGE on the
  band just left when the SETUP is its first close outside and `edge_watch = ref_band`); else BLOCK `new`. A branch-1 (LEAVE)
  TAKE of the band a watch waits on, in the watch's direction, is that watch's **REENTER** (evaluation M22); a FIRST_PRINT or
  defend TAKE stays Foundation's own TAKE and leaves the watch as it is. The gap rule takes a gap leave as soon as
  `open_quiet_bars` have passed; the evaluation's "and R2 re-met by closes after that" is not implemented (S40 a).
- **WATCH → ARMED → REENTER**, one watch at a time: R1 a close beyond the band on the watch's side (arms it), R2 `leave_closes`
  such closes, R3 none back inside or across the mid since R1, R4 far-side volume ≥ the sit's (skipped when NA), R5 a Foundation
  SETUP the same way on that bar or the one before. The fill is the close of the bar where R1–R5 hold (`reenter_fill =
  confirm_bar`); the stop is Foundation's rule evaluated at the fill bar; exits are the stop, then **`band_reclaim`** (a close
  back past the band's mid), then the next CHoCH (`fz_exec.simulate`, which reproduces every Foundation trade). A watch is
  cancelled at the next session's first bar, by an opposite TAKE or LEAVE, or, once armed, by `cancel_inside_bars` closes back inside.
  R3 is read as an unbroken far-side run: a close back inside (fewer than `cancel_inside_bars` of them) breaks the run and the
  next close beyond arms the watch again, so the ledger carries `armed_bars` (from the first arming) and `rearmed_bars` (from
  the latest); the strict reading, no close back inside at all since the first R1, is an open question (S40 b).
- **Volume NA.** A bar is NA when the 1-minute file's `front_month` is 0 that session or its volume is 0; a visit is NA if any bar
  is. NA skips R4, the HUNT burst and THIN, and makes ACCEPTED time-only. Everything before 26 Aug is volume-blind.
- **Clocks.** Durations are bars; clock rules use the bar's **open** time (`open_window_until`, `no_entry_from`); a visit inside at
  a session's last bar continues at the next session's first bar (`this_bars` grows by one across the night).

**The `fz` block.** Keyed by timeframe (`"minute"` in `strategy_5.json`, `"5minute"` in `strategy_6.json`); a backtest on a
timeframe without a block is refused, and Options (standalone) is refused for FZ (the thresholds are futures points). Every
key is `{value, source, statistic[, note]}` with `source` = `spec:<section>`, `decision:<n>` or `evaluation:<M/C/D-id>` of the
2026-09-27 FZ evaluation; `fz.thresholds()` refuses a missing, unknown or unsourced key and there are no defaults in code. The
Config tab prints them. `leave_far_side` (`any` / `block_list` / `no_band`) and `birth_b` (`band` / `flag`) are still the user's
decisions (docs/STRATEGY_ANALYSIS_TODO.md S35, S36); a changed value is a new strategy code or a recorded before / after run.

**Files and outputs.** `fz.py` (pure: bands, card, reads, gate, watch state machine), `fz_exec.py` (frozen view, `simulate()`,
the position callback, the FZ trade list), `fz_report.py` (cross-tabs, bridge, session-matched random control, permutation p,
sample-size flags), `tests/test_fz_parity.py`, FZ cases in `tests/test_truncation.py`. Per run and choice `summary.json['fz']`
(ledger, watches, cross-tabs, bridge, control, books, flags, all-NA comparator, legend); `Z` (the card per bar) and `ZONES` (bands
to draw) in each futures chart chunk; table `fz_setup` and trade columns `gate`, `reenter_reason`, `zone_id`, `fill_used`;
`results/fz_setups.csv` (one row per ledger row: futures and the W-ATR2 options-via-futures choice) and `results/fz_ledger.csv`
(cross-tabs, bridge and control per code and run).

The ledger has two gate columns: `gate` is the gate as of the SETUP bar (what the truncation test checks), `outcome_gate` the
gate the SETUP ended with: `REENTER` when a REENTER used that SETUP, even when the fill came on a later bar and the SETUP's own
gate read WATCH (most REENTERs fill that way). The gate × read tables, the headline counts and the all-NA comparator count
SETUPs by `outcome_gate`, so REENTER rows match REENTER positions. In `results/summary.json` an FZ row carries `fz_take`,
`fz_watch`, `fz_block`, `fz_reenter` (SETUPs by how they ended), `fz_reenter_at_setup` (SETUPs gated REENTER on their own bar),
`fz_take_trades` / `fz_reenter_trades` (positions), `fz_priced` (the positions priced in that choice: the denominator of
`control_pct`; for options via futures a position with no option candles is unpriced, so `trades` counts priced legs),
`control_pct`, `perm_p`, `active_sessions`, `fz_sessions` and `fz_hash`. The permutation test splits Foundation's trades by what
FZ traded: kept = the SETUPs FZ held a position on (a TAKE, or a REENTER on that SETUP), refused = the rest.

**Dashboard.** Zones chip (A bands purple, B bands blue), the hovered bar's card on the price line (its volume ratio is NA when
this visit or the band's first visit is volume-NA, as the gate reads it), T / W / B / R gate markers with the trades layer,
BAND exits; the random-control percentile and the kept-vs-refused p beside Net P&L in the KPI strip; the **Zone gate** tab (gate × read, watches, positions, the three `leave_far_side` counts,
volume NA and R4, bridge, random control and kept-vs-refused permutation, both books with sample flags, active sessions and
dormant stretches, gate by hour / visit / direction / zone kind, card statistics, and the ledger: click a row to open the chart
at that SETUP); Read and Gate in Signals; the `fz` keys in Config; a Foundation-Zone card in Rules.

**Procedure.**
- Iterate with a filtered run: `python lab.py ST5 ST6` stores ST5 / ST6 but does not rewrite `dashboard.html` or `results/*`
  ("partial run"). **Never commit `results/` from a filtered run**; the final build is a plain `python lab.py`. An edit to
  `fz.py` / `fz_exec.py` / `fz_report.py` invalidates only FZ rows (about 5 minutes); an edit to `lab.py` invalidates every row
  (about 3 hours).
- Judge FZ by its ledger and the random control, not by net against Foundation: Foundation's per-trade loss is about its costs,
  so any gate that drops trades raises net. The bridge separates price from cost avoidance; the session-matched random control
  and the kept-vs-refused permutation p say whether the selection beats chance.
- The **Unseen window is not out of sample for FZ**: several thresholds were read off tape-wide statistics that include it, and
  it is volume-blind. Read Design against the **all-NA comparator** (the same run with volume NA on every bar), not against
  Unseen. The first genuine out-of-sample check is the sessions from 2026-09-28 on, run once with the strategy files unchanged.
- `python tests/test_fz_parity.py` and `python tests/test_truncation.py` must pass before any FZ result is read.

**Pre-registered expectations (evaluation, 2026-09-27) against the first run** (All data, seeded values; the verdict so far is
docs/STRATEGY_ANALYSIS_TODO.md S39: no better than random selection on either timeframe):

| Expectation | 1 min (ST5) | 5 min (ST6) |
|---|---|---|
| ~92% (1m) / ~82% (5m) of bars close inside a band | 94.7% | 83.5% |
| LEAVE the most common read | yes, 43.7% of bars | yes, 38.4% |
| visit_n median ~30 at 1m SETUPs | **19** (26.5 over inside reads): not met. The build keeps a visit live through a close inside a neighbouring band, where the evaluation's simulator ended it, so visits are fewer and longer (S38 c) | 7 |
| FIRST_PRINT ~0 at SETUP (0–2 on 1m, 0–6 on 5m) | 0 | 0 |
| REENTER a small book (~64 on 1m with `edge_watch = ref_band`, ~6 with `containing_band`) | 22 positions (20 from a WATCH_EDGE, 2 from a plain WATCH) | 12 (all WATCH_EDGE) |
| Branch-1 TAKEs under `block_list` ~10–16 on 1m | 10 | 14 |
| SETUPs by the gate they ended with, TAKE / WATCH / BLOCK / REENTER (gate at the SETUP bar) | 29 / 114 / 42 / 22 of 207 (29 / 134 / 42 / 2) | 14 / 32 / 15 / 12 of 73 (14 / 44 / 15 / 0) |
| Random-control percentile · permutation p (kept = SETUPs FZ traded) | 6.2th · 0.44 | 49.8th · 0.18 |

Numbers above are from the 2026-09-27 phase-5 rebuild (S40: a FIRST_PRINT / defend TAKE is no longer turned into a REENTER,
which moved two 1m positions; the permutation now splits by the SETUPs FZ traded). The first run read 27 / 24 positions on
1m, gate rows as of the SETUP bar, and control 4.0th · p 0.58 / 49.8th · p 0.63.

## Files
| Path | What |
|---|---|
| `engine.py` | foundation engine (pure; no I/O besides loading candles) |
| `fz.py`, `fz_exec.py`, `fz_report.py` | the Foundation-Zone gate (Strategies 5–6): gate, execution / simulator, reports (see *FZ*) |
| `lab.py` | runs enabled strategies, stores results, writes dashboard + exports |
| `dashboard.tpl` | dashboard template (`dashboard.html` is generated) |
| `strategies/strategy_<n>.json` | **versioned** — one file per strategy: the source of truth for its rules and backtests |
| `config/data.json`, `config/charges.json` | **versioned** — input candle files, charge schedules |
| `results/summary.json`, `results/trades.csv` | **versioned** latest headline numbers and trades — diff them across commits |
| `results/fz_setups.csv`, `results/fz_ledger.csv` | **versioned** FZ gate ledger (one row per SETUP) and its per-run tables; written only by a full build |
| `tools/` | Kite downloads: `kitefut.py` / `kite1m.py` futures, `kite_spot.py` index, `kite_options.py` option chain; credentials read at runtime from money-maker |
| `web/` | per-variant, per-strike detail JSON the dashboard loads (generated, not versioned) |
| `tests/test_truncation.py` | look-ahead test (Foundation and FZ) |
| `tests/test_fz_parity.py` | FZ: `simulate()` reproduces every Foundation trade, no trade fields in `fz.py`, the card does not depend on positions, every `fz` key has a source |
| `strategy_lab.db` | SQLite working DB (not versioned; a cache of the files above plus run history; delete it any time) |

## Tables
`strategy` (definition + rules), `charge_schedule` (brokerage/STT/exchange/SEBI/stamp/GST rates),
`strategy_run`, `trade`, `choch_signal` (results per run), `fz_setup` (the FZ gate ledger per run; `strategy.fz_json` holds the
`fz` block verbatim and `trade.gate / reenter_reason / zone_id / fill_used` the FZ position fields).

## Backtests, timeframes, statistics
- **Backtests are per strategy** (listed in the strategy's file, synced to `strategy_backtest`): each is one independent run over its own dates (plus warm-up) —
  `all` (every session after warm-up), presets `1M 3M 6M YTD 1Y 5Y` counted back from the latest data date, or named/custom
  ranges such as **Design period** (26 Aug – 25 Sep: the rules were built here) and **Unseen test** (8 Jul – 25 Aug). A backtest
  the data cannot cover is **refused with the reason** (e.g. 3M needs data before 1 Jul). Add one:
  `python lab.py backtest ST2 1Y` · `python lab.py backtest ST2 2026-07-10 2026-08-10 --label "July"` (appended to that
  strategy's file, then run).
- **Timeframe** defaults to the strategy's design timeframe; the same rules can run on other candles
  (`--tf minute|3minute|5minute|15minute|30minute`), built from 1-minute futures/spot (`cache/`) and 1-/5-minute options.
  Non-design runs show an amber badge.
- **Open at the end:** a position still open when a backtest ends is valued at its last candle and flagged `*`.
- **Capital per lot** (`capital_fut`, `capital_opt_short` on the strategy row; long options use the premium paid) feeds return on
  capital, Calmar and risk of ruin.
- **Dashboard tabs:** Trades · Performance (returns, Sharpe / Sortino / Calmar, expectancy in ₹ and R, payoff, streaks, time in
  market, % profitable days / weeks / months) · Cumulative P&L with drawdown curve · Drawdowns (top 5) · Distribution (P&L and
  R histograms, max-profit vs max-loss scatter, holding time) · Monte Carlo (2,000 runs, fixed seed: trade-order shuffle fan and
  drawdown / streak percentiles, bootstrap P(loss) and expectancy range, stress tests, risk of ruin) · Robustness (slippage and
  charges sensitivity, month by month, other timeframes, expiry × strike) · Breakdown · Daily P&L · Signals · Zone gate (FZ
  strategies only) · Config · Rules.

## Workflow
```
python lab.py                 # reuse stored results, recompute only what changed, rebuild dashboard + exports
python lab.py --full          # recompute everything
python lab.py ST1             # one strategy (partial run: stores it, does not rebuild dashboard.html or results/*)
python lab.py backtest ST2 1Y # add a backtest to strategies/strategy_2.json and run it
python -m http.server 8766    # then open http://localhost:8766/dashboard.html
```
**Stored results:** each (strategy, period, strike choice) is written to `web/<code>/<backtest>_<tf>/<choice>/` (e.g. `web/ST2/all-data_5m/W-ATR2/`) as `summary.json`
(KPIs, trades, signals, chart index) plus one `c<k>.json` chart chunk per session (per day-contract for option · native).
`summary.json` carries a cache key over the strategy row, the period, `engine.py` + `lab.py`, and the input data files
(for FZ rows also `fz.py`, `fz_exec.py`, `fz_report.py` and the 1-minute file); a run is reused while the key matches.

**Dashboard loading:** it reads the summary, then only the session on screen; ‹ › and the session list fetch more on demand,
and *Full period* loads every session of the period into one chart only when clicked.
Change a rule → edit the strategy's file (or copy it into a new strategy) → `python lab.py` →
commit `strategies/` + `results/` together so the commit shows the rule change and its before/after numbers.

## Data
`D:/nifty/niftyfut_5minute_2026-07-01_to_2026-09-25.csv`, `D:/nifty/niftyfut_minute_2026-07-01_to_2026-09-25.csv`
(NIFTY26SEPFUT from Kite; `front_month` = 1 from 2026-08-26).
