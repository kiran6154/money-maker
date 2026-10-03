# Strategy lab v2

A rebuild of [`../strategy_lab`](../strategy_lab/README.md) (v1). v1 is left untouched and still works; v2 reads
the same candle files and does not write anything inside v1.

What changed from v1:

| | v1 | v2 |
|---|---|---|
| Layout | `lab.py` (1,950 lines: engine glue, pricing, DB, page build) + `dashboard.tpl` → a 2 MB `dashboard.html` with the data inlined | **`core.py`** (everything shared) · **`strategies/stNN.py`** (one file per strategy) · **`backtest.py`** (CLI) · **`server.py`** (API) · **`ui/`** (static HTML / CSS / JS that reads the API) |
| Strategy definition | `strategies/strategy_N.json` + rule code spread over `lab.py` / `engine.py` / `fz.py` / … | `strategies/stNN.py`: a `SPEC` dict (same keys as the v1 JSON) and `signals(bars, spec)` |
| Running | `lab.py` re-runs **every** strategy and rebuilds the whole page | `python backtest.py ST1 1Y`, or **Run** on the strategy's page: one strategy, one backtest |
| Engine | pure Python; ~27 s for one year of 1-minute bars (rescans every swing on every bar) | numba-compiled, same decisions; **0.04 s** for the same year |
| Data | CSV parsed on every run (1-minute options: per-strike chunk files) | each CSV parsed once into `cache/` (`.npz`), then loaded in milliseconds |
| Charts | pre-built for every session and choice, written to `web/` | computed when you open a day (`/api/chart`) |
| Storage | SQLite + `web/` + `results/` | `results/<CODE>/<run>/meta.json` + `<TYPE>/<choice>.json` |

## Parity with v1

`tests/test_parity.py` runs v1's `lab.run_variant` and v2's `core.run_type` for the same strategy, window and type, and
compares every priced trade: times, prices, exit reason, points, gross, charges, net, MFE / MAE. It also compares the
reasons for skipped signals. Covered: ST1–ST4, ST9–ST12, ST15–ST18 × Futures / Options (via futures) / Options (standalone), and
ST5–ST8 (futures and options via futures, with the whole FZ payload), ST19 / ST22 / ST23 (the learner, with its whole
payload), ST25–ST28 (options via futures, index and futures signals), ST29–ST30 (futures); 1-minute, 5-minute and 15-minute candles; signals on the index; positional holding; stop and reverse.

```
python tests/test_parity.py            # all cases (v1 is the slow side: several minutes)
python tests/test_parity.py ST2        # one strategy
```

The engine itself is also checked against v1's `engine.run`: swings, CHoCH / BOS events, protected level per bar and
trades are identical.

## Use

```
python server.py                 # http://localhost:8780/  (127.0.0.1 only; --lan to open it to the network)
python backtest.py --list        # strategies and their defined backtests
python backtest.py ST1           # the strategy's default backtest, all three types
python backtest.py ST1 1Y        # MTD 1M 3M 6M YTD 1Y 5Y all
python backtest.py ST1 2026-01-01 2026-06-30 --type FUT
python backtest.py ST1 1Y --tf 5minute --underlying INDEX --square-off none
python backtest.py ST1 --defined # every backtest listed in the strategy file
```

### The page (`ui/index.html`)

1. **Strategy cards** across the top: code, family (Foundation · Managed exits · FZ gate · Learner · CHoCH to CHoCH ·
   Rainbow), description, key rules and the default backtest's net / PF / trades / win rate. Filter by family, search,
   sort by net, PF or recency. Once a strategy is open the cards shrink to one scrolling strip ("Show all as cards"
   brings the grid back).
2. **The selected strategy below:** its rules sentence and version; **Backtests** tabs (every backtest in the strategy
   file plus ad hoc runs) with their candle / signal-source / holding variants; **Run** (this backtest, a preset, custom
   dates, other candles, index or futures signals, positional or intraday; only this strategy runs).
3. **The three types side by side** (Futures · Options via futures · Options standalone) with Long + short / Long /
   Short / CE side / PE side rows and how many signals were priced; the expiry and strike bar.
4. **KPIs** for the selected type and side, and the **vs version N** tile (the same backtest on the strategy's previous
   version, from `history/<CODE>.json`).
5. **Chart:** the signal candles with layers you can switch (trades, 1R/2R/3R, AVWAP pair with its back-extension,
   protected level, CHoCH / BOS, swings and candidates, volume, FZ zone bands and gate letters, rainbow ribbon), a
   crosshair readout (with the FZ zone card), CE and PE panes with each traded option on its own candles, day / range
   navigation, "Full period", PNG snapshot, drag to resize.
6. **Tabs:** Trades (sortable, filterable, charges breakdown, signals not taken) · Performance · Cumulative P&L ·
   Drawdowns · Distribution · Monte Carlo · Robustness (slippage / charges sensitivity by repricing every trade, month by
   month, other timeframes, expiry × strike) · Breakdown · Daily P&L with the heatmap calendar · Signals · Zone gate
   (FZ) · Journal (learner) · Config · Rules.

`ui/explorer.html` — any session, any instrument (near-month futures, the index, any option contract with candles that
day), a strategy's rules applied to that instrument's own candles: a visualization, nothing stored.

Every run appends to `history/<CODE>.json` (versioned): a new version whenever the strategy's definition or the code
its results come from changes, with the headline numbers of each run made on it.

The first run after a data change is slower. The CSVs are parsed into `cache/` once and numba compiles the engine once
(also cached).

## Files

```
core.py              data cache · numba engine · option chain · positions / pricing / stats · runner · results · charts
strategies/stNN.py   SPEC + signals(); file order = the order on the page
backtest.py          CLI: one strategy per call
server.py            JSON API + static ui/; backtests queue and run one at a time in-process
ui/                  index.html + explorer.html, css/, js/ (main, chart, tabs + analytics, explorer, util); lightweight-charts from jsdelivr
history/             per-strategy versions and their results (versioned)
config/data.json     candle files (same as v1; history_from null = the whole files, so 1Y / 5Y presets work)
config/charges.json  charge schedules (copy of v1's)
tests/test_parity.py v2 against v1, trade for trade
cache/, results/     generated (git-ignored)
```

## Add a strategy

Copy a file in `strategies/` to the next number and give it a new `code` and `name`. Change the `SPEC`. For a new idea,
replace `signals()`: it receives the candles (`core.Bars`) and returns a `core.Signals` (the engine's arrays). Every
pricing, lock, square-off and option rule in `core.run_type` then applies unchanged.

## Ported so far

| Codes | What | Where |
|---|---|---|
| ST1–ST4 | Foundation: every SETUP, exit at the stop (`sl_rule`) or the next CHoCH | `strategies/st01.py` … `st04.py` → `core.foundation` |
| ST9–ST12, ST15–ST18 | Foundation entries with managed exits (`position.exit: "position"`): stop in points / % of premium = 1R, targets in R, trail, stop and reverse (ST11, ST12), positional (ST15–ST18) | `core.manage`, `core.managed_with_reversals` |
| ST5–ST8 | Foundation-Zone gate (`fz_v1` bands, `fz_v2` rooms) on Foundation SETUPs; futures and options via futures; the whole FZ report (ledger, cross-tabs, controls) | `strategies/foundation_zone.py` + v1's `fz.py` / `fz_exec.py` / `fz_report.py` copied to `strategies/fz_lib/lib_*.py` |
| ST19–ST24 | The learner (`rl_v1`): contextual bandit over Foundation SETUPs, learning once over the whole futures file; journal, base / random books, permutations, seed spread | `strategies/learner.py` + v1's `rl.py` copied to `strategies/rl_lib/lib_rl.py` |
| ST25–ST28 | CHoCH to CHoCH put retest (`c2c_v1`): options via futures, 5-minute, PCR from open interest, premium stop / trail, 15:15 ladder | `strategies/c2c.py` (family module with its own `run`) |
| ST32 (new in v2) | Strategy 1's Foundation rules run on each option's own chart (Options standalone only; the futures row of the chart is reference only), each trade taken only with the option's own SMA-200 slope (long: rising, short: falling). A strategy vetoes single option legs through `leg_filter(ctx, rec, series)`. First numbers: STRATEGY_ANALYSIS_TODO S60 | `strategies/st32.py` |
| ST33 (new in v2) | ST32's entries (Foundation on each option's own chart + its SMA-200 slope) with ST9's managed exits (3 lots, stop 5% of premium = 1R, 1R / 2R targets, trail from 3R). First numbers: STRATEGY_ANALYSIS_TODO S60 | `strategies/st33.py` (filter and SMA line from `st32.py`) |
| ST34 (new in v2) | ST33 with Foundation's CHoCH-candle stop (`sl_rule: choch_candle`) as 1R on the option's own chart (`position.stop.from: "signal"`: R = entry → the engine's stop); everything else as ST33. First numbers: STRATEGY_ANALYSIS_TODO S60 | `strategies/st34.py` |
| ST31 (new in v2) | Strategy 1's 1-minute Foundation trades taken only in the direction of the latest 1-hour CHoCH (1-hour candles closed by the entry); futures and options via futures. First numbers: STRATEGY_ANALYSIS_TODO S59 | `strategies/st31.py`; look-ahead test `tests/test_st31_causal.py` |
| ST29, ST30 | Rainbow ribbon intraday (`rainbow_v1`), futures only; the ribbon is drawn on the day chart | `strategies/rainbow.py` (family module) |

All 28 v1 strategies are ported (ST1–ST12, ST15–ST30; ST13 / ST14 are reserved numbers in v1 too). `core.validate` refuses a strategy file
whose entry rule or position block needs a feature v2 does not have, so nothing runs silently with the wrong rules. Each port gets parity cases in `tests/test_parity.py` before its numbers are trusted. v1's result history
(`results/history`), the SQLite tables and the chart explorer are not carried over.

### Copied v1 modules (FZ and the learner)

FZ and the learner are large, reviewed rule sets; v2 runs v1's own modules rather than a rewrite, so their decisions
cannot drift. The copies differ from v1 only where noted at the edit, never in a decision:
- `fz_lib/lib_fz.py` (v1 `fz.py`): the live zones are indexed by price (`near_lo` / `near_mid`), so a bar tests the zones near its close
  instead of every zone ever born (bands are never retired, so v1 scanned thousands per bar); a zone's run of inside
  closes is kept lazily. Same output; FZ over Jan–Sep 2026 on 1-minute bars: ~7 s instead of ~45 s.
- `rl_lib/lib_rl.py` (v1 `rl.py`): imports `rl_engine` / `rl_lab` (v1's engine API over v2's engine; the v1 lab functions it calls,
  copied); `manage()`'s candle loop runs in numba; the books that do not learn skip the feature fill they never read;
  the per-day charts are not built (v2 draws charts on request).
FZ's memory starts at `config/data.json` `fz_memory_from` (2026-01-01, v1's `history_from`): every FZ window is a slice
of one run from there and FZ backtests resolve against the sessions from that date, as in v1. The learner always
learns over the whole futures file (Oct 2021 on), as in v1.

A family of strategies that shares rules beyond the Foundation engine (rainbow today) keeps them in
`strategies/<family>.py`, loaded with `core.family("<family>")`; the numbered files stay one per strategy. A strategy
module can also declare `ENTRY_RULES`, `TYPES`, `UNDERLYINGS`, `TIMEFRAMES` (+ `REFUSED_WHY` / `TF_WHY`: what it does
not run is refused with that reason), `OWN_COVERAGE` (it checks full-chain option data per trade instead of per window)
and `run(ctx)` (it builds its own trades for a type; pricing, stats and results stay in `core`).
