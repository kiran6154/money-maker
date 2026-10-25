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
   crosshair readout (with the FZ zone card), CE and PE panes that open on the day's ATM CE / ATM PE (nearest weekly expiry, strike nearest the index at the day's first candle; shown whether or not the run traded it, with the index against the strike) and list the contracts the run traded that day, day / range
   navigation, "Full period", PNG snapshot, drag to resize. Drag (or scroll sideways) past the first / last candle and more sessions load on that side with the view kept where it was; a load only follows the reader's own move, so zooming out cannot run away.
6. **Tabs:** Trades (sortable, filterable, charges breakdown, signals not taken; **Download CSV** of the listed trades with every stored column; max profit / max loss with the time each was reached and a **First** column saying which came first — `mfe_time`, `mae_time`, `first_move`, on runs made after 2026-10-11) · Performance · Cumulative P&L ·
   Drawdowns · Distribution · Monte Carlo · Robustness (slippage / charges sensitivity by repricing every trade, month by
   month, other timeframes, expiry × strike) · Breakdown · Daily P&L with the heatmap calendar · Signals · Zone gate
   (FZ) · Journal (learner) · Config · Rules.

`ui/explorer.html` — under the main chart, the **day-open ATM straddle**: per session the strike nearest the index's first candle, CE + PE premium per candle with each leg and their volume (`/api/explorer/straddle`), following the main chart's time range. Any session, any instrument (near-month futures, the index, any option contract with candles that
day), a strategy's rules applied to that instrument's own candles: a visualization, nothing stored.

Every run appends to `history/<CODE>.json` (versioned): a new version whenever the strategy's definition or the code
its results come from changes, with the headline numbers of each run made on it.

The first run after a data change is slower. The CSVs are parsed into `cache/` once and numba compiles the engine once
(also cached).

### The strategy tree (`ui/lineage.html`)

Every strategy under the one it was derived from, with: the one change that makes it a new strategy; every setting that
differs from its parent (computed from the two strategy files); its exits in one line (stop, targets, trail, square-off);
its widest stored result; and "also tried" - variations measured on it without becoming a strategy, and things asked
about that were not tried. One search box over all of it ("1R", "trail", "sweep", "not tried" …). The parent, the change
and the studies are kept in `strategies/lineage.py`: add a line there with every new strategy or study.

### Intraday close

`config/data.json` `intraday_close`: from 2026-06-01 every intraday position is squared off at **15:14** (when that is
earlier than the strategy's own square-off; an entry at or after it is not taken). Positional runs are unaffected.
`data.v1.json` does not carry it, so the v1 parity test still squares off as v1 does.

## Data

Index and futures: the Breeze Parquet store `D:/nifty_data` (written by `../strategy_lab/tools/breeze_store.py`, another
session's download), **Jan 2018 → the last downloaded day**. `tools/build_from_store.py` reads the store (never writes
to it) and writes the CSV files `core.py` reads under `cache/store/`; `config/data.json` points there. Re-run it to
pick up new downloads, then restart the server:

```
python tools/build_from_store.py        # ~3 min; cache/store/build.json says what was built and every exception
```

- Only 09:15–15:29 candles are kept (the store also has pre-open and post-close rows). Prices are identical to the old
  files wherever both have a candle; the store has more candles (gaps in the old files, and 2018–2021).
- Near-month futures = the monthly contract with the earliest expiry on or after the session. The two contracts the
  store has set aside for re-download (Jan 2019, Jun 2022) come from its `_superseded` copies, one session short each.
- Options: the old folders (`weekly_dir`, the Kite expiry) plus `options.extra_dirs` (`cache/store/options`). A store
  expiry is exported only when its whole window is downloaded; an expiry found in several places is read from the
  first one with a full chain. Full-chain option data still starts 2026-06-30; the store's option history is being
  downloaded backwards (about 85 days at Breeze's daily limit) and appears here expiry by expiry on each rebuild.
- `config/data.v1.json` is the previous set (the files v1 reads). `tests/test_parity.py` uses it (`LAB2_DATA_CONFIG`),
  so v1 and v2 are still compared on the same candles.
- Foundation strategies are path-dependent: on the long history Strategy 1 has no CHoCH from 2020-11 to 2022-03
  (STRATEGY_ANALYSIS_TODO S58), so "All data" is not comparable with runs made on the old Oct 2021 start.

## Files

```
core.py              data cache · numba engine · option chain · positions / pricing / stats · runner · results · charts
strategies/stNN.py   SPEC + signals(); file order = the order on the page
backtest.py          CLI: one strategy per call
server.py            JSON API + static ui/; backtests queue and run one at a time in-process
ui/                  index.html + explorer.html, css/, js/ (main, chart, tabs + analytics, explorer, util); lightweight-charts from jsdelivr
history/             per-strategy versions and their results (versioned)
config/data.json     candle files (cache/store, built from the Breeze store; data.v1.json = the files v1 reads)
tools/build_from_store.py  the Breeze Parquet store -> cache/store (index, near-month futures, finished option expiries)
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
| ST35 (new in v2) | ST34 with the entry on the trend's side of the option's SMA 200: long needs close above it (and the SMA rising), short close below it (and the SMA falling); `sma_filter.price: "with_trend"`. First numbers: STRATEGY_ANALYSIS_TODO S60 | `strategies/st35.py` |
| ST36 (new in v2) | Shorts only on each option's own chart: sell at a same-session swing high (at the confirming close) while the option's SMA 200 is rising; stop 30% of premium or 15:25. First numbers: STRATEGY_ANALYSIS_TODO S60 | `strategies/st36.py` |
| ST37 (new in v2) | Shorts only: an imaginary long (ST34's long rules) runs on each option's chart; when its trail stop is hit, a real short opens at that candle's close; stop 30% of premium or 15:25. First numbers: S60 | `strategies/st37.py` |
| ST57, ST58 (new in v2) | Strategy 3 read on the candles of the day-open ATM straddle (CE + PE of the strike nearest the index at the open; one engine run per session on that session's own pair). ST57: a bullish SETUP buys both legs, a bearish one sells both. ST58: bullish SETUPs only, buying the one leg that is going up, out when the straddle chart turns to the sell side. Options (via futures) type only. The lab's main chart for these two is the derived straddle candles with the structure and the trades on them (a strategy module's `chart_main(ctx, body, day, to)` replaces the futures chart). Numbers: STRATEGY_ANALYSIS_TODO S70 | `strategies/atm_straddle.py` (family module with its own `run`), `st57.py`, `st58.py` |
| ST59 (new in v2) | A short straddle managed leg by leg on the same derived straddle candles: a bearish SETUP sells every leg not held, a bullish SETUP buys back only the leg that is going up, the square-off closes the rest; no stop. Numbers: STRATEGY_ANALYSIS_TODO S72 | `strategies/atm_straddle.py` (`mode: managed_short`), `st59.py` |
| ST60 (new in v2) | Both sides of the derived straddle candles: a bearish SETUP sells both legs, a bullish SETUP buys the leg that is going up, no short is bought back; a 20 point target on every leg's own premium (`straddle.target_pts`), Strategy 3's stop and CHoCH exit for the rest. Numbers: STRATEGY_ANALYSIS_TODO S73 | `strategies/atm_straddle.py` (`mode: both_sides`), `st60.py` |
| ST61 (new in v2) | Strategy 60 with the target as the only exit (`straddle.exit: target_only`): no stop, no CHoCH exit; a leg that has not reached 20 points is closed at the square-off. Numbers: STRATEGY_ANALYSIS_TODO S74 | `strategies/atm_straddle.py`, `st61.py` |
| ST62 (new in v2) | Strategy 61 with the short straddle imaginary (`straddle.real: long`): only the bullish SETUP's rising leg is bought, out at the 20 point target or the square-off. Numbers: STRATEGY_ANALYSIS_TODO S75 | `strategies/atm_straddle.py`, `st62.py` |
| ST63 (new in v2) | Two charts: a bullish SETUP on the derived straddle candles arms the leg that is going up (it trades nothing); Strategy 3 then runs on that option's own candles and its bullish SETUPs buy the option, with the option's own stop and CHoCH exit (`straddle.mode: leg_structure`, `window`, `sides`). Numbers: STRATEGY_ANALYSIS_TODO S76 | `strategies/atm_straddle.py`, `st63.py` |
| ST64 (new in v2) | Strategy 63 with the stop following the option's BOS (`straddle.trail: bos_level`): at every bullish BOS while the long is open the stop moves to the level that BOS broke, never back. Numbers: STRATEGY_ANALYSIS_TODO S77 | `strategies/atm_straddle.py` (`_trail`), `st64.py` |
| ST65 (new in v2) | Any SETUP on the derived straddle candles, buy or sell, buys two lots of the winning leg at that same candle (`straddle.arm: both`, `entry: signal`, `two_lots`): one out at +20 points, one trailed with its stop moved to the option's BOS level only after +20; long only; first stop = 50 points below the entry premium (`straddle.stop`); exit also at the option's next bearish CHoCH. On any gap up or down (a chart's first candle not opening at the previous close: `straddle.gap_restart: "any"`) that chart's structure starts again from the first candle. The filter "only above the option's previous-session low" (`straddle.above_prev_low`) exists and is off. Numbers: STRATEGY_ANALYSIS_TODO S78 - S83 | `strategies/atm_straddle.py` (`_at_signal`, `_walk`), `st65.py` |
| ST66 (new in v2) | Strategy 1 with the market structure reset on a gap day: the session opens 20 points or more from the previous close (`gap_reset.pts`) → swings, protected level, CHoCH / BOS and AVWAP anchors start again from the day's first candle. Every type. Numbers: STRATEGY_ANALYSIS_TODO S84 | `strategies/gap_reset.py` (family module: the engine run piece by piece and joined), `st66.py` |
| ST67, ST68 (new in v2) | Not Foundation strategies: on 5-minute candles, a close down through the SMA 20 / 50 / 100 / 200 / 500 of the candle LOW is a short; 30 point stop, 30 point target, intraday (`sma_low`, `sma_cross`). ST68: the crossed SMA must itself be falling (`sma_cross.falling`). On the futures' own chart and on each option's own chart (the option is sold). The SMAs are drawn in five colours: a strategy's chart lines can carry names and colours (`sg.line_names` / `sg.line_colors`, `LINE_COLORS` for `option_lines`). Numbers: STRATEGY_ANALYSIS_TODO S85, S86 | `strategies/sma_cross.py` (family module), `st67.py`, `st68.py` |
| ST69, ST70 (new in v2) | Strategy 68's signal (a 5-minute close down through a falling SMA of the low) used as a switch: it arms the day, and Strategy 1's (ST69) or Strategy 3's (ST70) bearish SETUPs on 1-minute candles are then shorted; the structure's own stop, a 30 point target, flat by the square-off, no CHoCH exit (`entry_rule: sma_arm_v1`). The 5-minute candles are built from the 1-minute ones. Numbers: STRATEGY_ANALYSIS_TODO S87 | `strategies/sma_cross.py` (`signals_arm`), `st69.py`, `st70.py` |
| ST71, ST72 (new in v2) | ST69 / ST70 with everything on 5-minute candles: the SMA cross and the structure (Strategy 2's / Strategy 4's rules) on the same candles. Numbers: STRATEGY_ANALYSIS_TODO S88 | `strategies/sma_cross.py`, `st71.py`, `st72.py` |
| Summary tab (strategy page, beside Daily P&L) | The shown result summed for a period (year, month, from / to dates), in points per lot or rupees: trades, win %, before slippage, the slippage, charges (rupees), net, total profit, total loss, PF, average, max drawdown; grouped by year / month / week / day with a cumulative column. By exit day, as the Daily P&L. Computed in the page from the loaded result (`ui/js/tabs.js` `summary`). | `ui/js/tabs.js`, `ui/css/app.css` |
| Charts page (`ui/charts.html`) | Plain charts with no strategy, read straight from the download store (D:/nifty_data, `store_reader.py`, read-only; new downloads appear on the next load): the NIFTY index, the near-month futures (with open interest; the contract used is named) or any option contract of the store (Sep 2024 →, with open interest), picked as in the explorer: Year → Expiry → CE / PE → Strike (the day's ATM marked; the strike's own trading dates shown and the day kept inside them); a new day moves to its nearest expiry and ATM unless one was picked (a picked expiry is kept while it trades on the day; outside its life the day's nearest expiry takes over, said on the strike line); a slow earlier load never overwrites a newer one; an option's range can start at its first candle or the previous expiry and end at its expiry. **Stack** view (`ui/js/stack.js`): for the chosen day, expiry and strike (default the day-open ATM), one under another - the futures; the CE and the PE side by side at 15, 5 and 1 minutes; the OI built at each premium level (every 1-minute candle's change in open interest credited to the price bin its close fell in, over the contract's life up to the day; bars = OI added, a red line = OI cut, the largest bin and its share named); the CE and PE open interest; the CE + PE combined candles - all time panes linked. Three requests (the futures, and the CE and PE 1-minute candles from each contract's first candle); 5 / 15-minute candles built in the page. Candles of 1 / 3 / 5 / 15 / 30 / 60 minutes (built from the 1-minute store, regular session only). An Open interest pane (in lakh) for futures and options. Indicators the reader adds, edits and removes, remembered in the browser: SMA, EMA, VWAP, Bollinger bands, previous-day high / low, day open on the price chart; RSI, MACD, ATR in panes - computed in the page (`ui/js/charts.js`) with a warm-up. Server: `GET /api/store/coverage | expiries | strikes | candles`. | `ui/charts.html`, `ui/js/stack.js`, `ui/js/charts.js`, `store_reader.py`, `server.py` |
| Option chart (every strategy page) | Under the strategy's chart and its CE / PE panes: a plain candle chart of any option contract, with an Expiry list, a Strike list (the ATM marked) and CE / PE buttons; it opens on the nearest expiry with data and the ATM of the day, keeps the reader's choice when the day changes, shows the same sessions at the run's timeframe and follows the strategy chart's time range. Nothing is computed on it. Server: `GET /api/candles?expiry=&strike=&right=&from=&to=&tf=` (`core.plain_candles`). | `ui/js/chart.js` (`drawFree`), `core.py`, `server.py`, `ui/css/app.css` |
| Charts of ST67 - ST80 | Under each chart of these strategies the same instrument is drawn on its other timeframes, one below another: the SMA signal candles (15- or 5-minute), the strategy's own candles and the 1-minute candles, each with the signal candles' SMAs (a step on a finer chart) and the same trades. On the strategy page (main chart and the CE / PE panes) and in the chart explorer (futures, index, an option). A strategy module provides them with `chart_views(s1, t_from, t_to, main_min)`; `core.chart` / `core.explorer_chart` return them as `views`; `ui/js/chart.js` `drawViews`. | `strategies/sma_cross.py` (`chart_views`), `core.py`, `ui/js/chart.js`, `ui/css/app.css` |
| ST73 - ST80 (new in v2) | The SMA cross read on 15-minute candles (`sma_cross.candles_min: 15`), then the Foundation shorts: 73 - 76 with the structure on 5-minute candles, 77 - 80 on 1-minute; stop at the previous swing high (73, 74, 77, 78) or at the SMA of the highs of the crossed period (`stop: sma_high`: 75, 76, 79, 80); target 1:1 (odd numbers) or 1:2 (even) of the stop distance (`target_r`). Every entry needs the crossed SMA still falling, the price below it and the last signal candle closed below it (`valid_at_entry: closed_below`). Numbers: STRATEGY_ANALYSIS_TODO S89, S90, S92 | `strategies/sma_cross.py`, `st73.py` - `st80.py` |
| ST81 (new in v2) | The user's NIFTY regime spec: CE / PE open interest of the 3 ATM strikes (the option files' `open_interest`, read by `oi_regime.oi_series`, cached in `cache/oi/`) plus a pivot structure give a regime per bar (Sideways / BOS up / BOS down / CHoCH); entries by regime, stop / target in points, a bar cap, flat on a CHoCH and at the square-off (`oi_regime`). Its chart: its own swings, BOS / CHoCH and regime labels, the CE / PE cumulative dOI lines (in lakh) in a band of the main chart between the candles and the volume, and the same lines in an Open interest pane below. OI exists from August 2025. Numbers: STRATEGY_ANALYSIS_TODO S93 | `strategies/oi_regime.py`, `st81.py` |
| ST82 (new in v2) | The user's document "Structure + Order Block + Previous Day Range": on the index 5-minute candles a CHoCH, then a retest of a fresh Order Block, buys the ATM CE / PE of the nearest weekly expiry, filtered by the option's previous-day low; stop 40% of premium, 1.5R, a 30-minute exit, flat at 15:00 (`ob`; `short_as` buy_pe / sell_pe; `prev_day_filter`). Its own runner prices the option on its candles from December 2025. Numbers: STRATEGY_ANALYSIS_TODO S94 | `strategies/ob_retest.py`, `st82.py` |
| ST83, ST84 (new in v2) | The user's ORR_V1 ruleset (opening-range sweep / reclaim, 1-minute index candles, points with 0.5 slippage): ST83 the ruleset with one change at the user's word - the sweep is a candle close beyond the opening boundary, not a wick (`orr.sweep: close`; `wick` is ORR_V1 as written and reproduces its 133 trades / +1,596.80 points exactly), ST84 with the entry waiting for a BOS / CHoCH that way after the reclaim (`orr.confirm: structure`). Own runner; the chart shows the opening range lines. Numbers: STRATEGY_ANALYSIS_TODO S95, S97 | `strategies/orr.py`, `st83.py`, `st84.py` |
| ST85 (new in v2) | Strategy 83's ORR_V1 signals traded by selling options: a long signal sells the PE at the day's low, a short signal sells the CE at the day's high; out when the index closes back through the strike, else 15:15; both sides may signal, one position per side (`orr_opt`). Option prices from the download store (`store_reader.py`). Numbers: STRATEGY_ANALYSIS_TODO S96, S97 | `strategies/orr_opt.py`, `st85.py` |
| ST94 (new in v2) | Strategy 1's Foundation rules on the day-open ATM option's own 1-minute candles: a bullish SETUP buys the option, out at the previous swing's stop or the next CHoCH, flat 15:25, one trade a leg at a time; each trade tagged inside / above / below the same option's previous-session range (in the label; recorded, not acted on) (`fopt`). The strategy chart is the leg's candles with its structure and the previous-day high / low. Numbers: STRATEGY_ANALYSIS_TODO S107 | `strategies/foundation_opt.py`, `st94.py` |
| ST93 (new in v2) | Strategy 92 with the monthly longs rolled too: under 15 days to expiry they are sold and three of the next monthly (at least 18 days out, premium nearest 200) are bought; the position ends only at +3% / -6% or a roll with no contract (`cagr.roll_long`). Numbers: STRATEGY_ANALYSIS_TODO S105 | `strategies/cagr_hedge.py`, `st93.py` |
| ST92 (new in v2) | Strategy 91 with the weekly shorts rolled: two sessions before their expiry the two shorts are bought back and the same strikes sold on the next weekly (rows `rolled`); the monthly longs stay; the position's realized plus open P&L decides the +3% / -6% (`cagr.roll`). Numbers: STRATEGY_ANALYSIS_TODO S104 | `strategies/cagr_hedge.py`, `st92.py` |
| ST91 (new in v2) | The session before each weekly expiry at 09:30, the index against a fair-value line (2000 on 2000-01-01 at 10% a year): above, sell one next-weekly put near 150 and one near 450 premium and buy three monthly puts near 200 (monthly at least 18 days out); below, the same with calls. Marked hourly; out at +3% / -6% of the margin plus debit, two sessions before the sold expiry, or when the monthly has under 15 days (`cagr`). Each leg a trade row (tranche = the position). The strategy chart is the index with the fair-value line. Numbers: STRATEGY_ANALYSIS_TODO S103 | `strategies/cagr_hedge.py`, `st91.py` |
| ST90 (new in v2) | The day-open ATM CE and PE sold when a 1-minute close goes below the option's own previous-session low; at each bullish CHoCH of the option a losing trade is bought back, a profitable one trails the stop at the bounce's top (lowered to each new swing high); flat 15:15; one position per leg (`pdl`). Option prices from the download store. The strategy chart is the leg's own candles with its structure and the previous-day low. Numbers: STRATEGY_ANALYSIS_TODO S102 | `strategies/pdl_short.py`, `st90.py` |
| ST88, ST89 (new in v2) | A continuation trigger beside Strategy 86's reclaim: three consecutive 1-minute closes above the opening high sell the PE at the day's low, three below the opening low sell the CE at the day's high (`orr_opt.breakout: {closes: 3}`). ST88 keeps the reclaim entries, ST89 is the breakout only (`orr_opt.reclaim: false`). Numbers: STRATEGY_ANALYSIS_TODO S100 | `strategies/orr_opt.py`, `st88.py`, `st89.py` |
| ST87 (new in v2) | Strategy 86 with the sweep by a wick: a low below the opening low (high above the opening high) is enough, the close need not be beyond (`orr.sweep: wick`). Numbers: STRATEGY_ANALYSIS_TODO S99 | `strategies/st87.py` |
| ST86 (new in v2) | Strategy 85 without the opening-candle body rule: every session trades, the 09:15 candle only sets the opening high and low (`orr_opt.body_rule: false`). Numbers: STRATEGY_ANALYSIS_TODO S98 | `strategies/orr_opt.py`, `st86.py` |
| ST55, ST56 (new in v2) | The TradingFinder "Smart Money Liquidity Structure - OB Signal Setups" indicator, ported in `strategies/smls.py` (order-block edges = the origin candle's range: the script's refiner library was not supplied). ST55 = Strategy 3 taken only after a same-side signal within 30 candles; ST56 = the indicator's own Long / Short signals (stop at the block's far edge, flat 15:25; futures only). Both lose in the lab; numbers and the open reconciliation with the user's manual backtest: STRATEGY_ANALYSIS_TODO S69 | `strategies/smls.py` (family module), `st55.py`, `st56.py` |
| ST49–ST54 (new in v2) | The other ported smart-money rules, each as ST46 + one rule, kept for the record (none beats ST46 on both halves): ST49 swing-structure bias, ST50 internal-structure bias, ST51 swing order block tap, ST52 5-minute FVG tap, ST53 equal highs / lows swept, ST54 premium / discount. Numbers: STRATEGY_ANALYSIS_TODO S68 | `strategies/st49.py` … `st54.py` (rule in `SPEC["smc"]`, evaluated by `smc.passes()`) |
| ST47, ST48 (new in v2) | ST46 + one smart-money rule from the user's Pine scripts, ported in `strategies/smc.py` (LuxAlgo-style structure, order blocks, 5-minute FVGs, equal highs / lows; the living-zones volume bands): ST47 = the SETUP candle closes inside a heavy volume zone still open; ST48 = price tapped a live internal order block within 10 candles. About break-even on futures on ~110 trades, in-sample; validation of every ported rule: STRATEGY_ANALYSIS_TODO S68. A backtest takes about a minute | `strategies/smc.py` (family module), `st47.py`, `st48.py` |
| ST46 (new in v2) | ST43 taken only while the 14-candle Choppiness Index is below 38.2 at the SETUP candle (`SPEC["chop_index"]`): the strongest stable entry filter found, PF 0.64 on futures (0.74 / 0.59 by half), still losing. Validation of the other chop rules and numbers: STRATEGY_ANALYSIS_TODO S66 | `strategies/st46.py` |
| ST44, ST45 (new in v2) | Kept for the record (both make ST43 worse): ST44 = ST43 + a sweep of the session's or the previous day's extreme before the CHoCH (`liquidity.extreme_sweep`); ST45 = ST43 + the broken swing is a 15-candle pivot (`liquidity.pivot_degree`). Validation and numbers: STRATEGY_ANALYSIS_TODO S65 | `strategies/st44.py`, `st45.py` |
| ST43 (new in v2) | The reference entry combination: Strategy 3 + AVWAP slope size + swing age + a stop at least 20 pts from the entry (`SPEC["risk"]`), the three filters that held on both halves of the history. PF 0.52 on futures, still losing; numbers in STRATEGY_ANALYSIS_TODO S64 | `strategies/st43.py` |
| ST41, ST42 (new in v2) | The sweep tightened to a swing at least 40 candles old (`sweep.min_age`; `sweep.extreme` as a switch): ST41 = Strategy 3 + that sweep; ST42 = Strategy 3 + AVWAP slope size + swing age (ST38's two filters that helped) + that sweep. First numbers and the holding-time breakdown: STRATEGY_ANALYSIS_TODO S64 | `strategies/st41.py`, `st42.py` |
| ST39, ST40 (new in v2) | Liquidity filters on the SETUP (a sweep of a swing low / high before the CHoCH, equal highs / lows at the broken level, displacement or a fair-value gap on the SETUP candle; switches in `SPEC["liquidity"]`): ST39 on Strategy 3, ST40 on Strategy 38. First numbers: STRATEGY_ANALYSIS_TODO S63 | `strategies/liquidity.py` (family module), `st39.py`, `st40.py` |
| ST38 (new in v2) | Strategy 3 with five anti-chop filters on the SETUP (pair-AVWAP slope size, close beyond the trend AVWAP, age of the broken swing, displacement candle, pair-AVWAP separation), each a switch in `SPEC["chop"]`; futures and options via futures. First numbers: STRATEGY_ANALYSIS_TODO S62 | `strategies/st38.py` |
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
