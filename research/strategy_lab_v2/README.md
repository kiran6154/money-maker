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
ST25–ST28 (options via futures, index and futures signals), ST29–ST30 (futures); 1-minute, 5-minute and 15-minute candles; signals on the index; positional holding; stop and reverse.

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

On the page: pick a strategy on the left, then choose a defined backtest or an ad hoc period and press **Run**. Only that
strategy runs, and its results show when the job finishes. Each run has a tab per type (Futures, Options via futures,
Options standalone), a choice per expiry type × strike, KPI tiles, an equity curve, a table comparing the choices, the
trade list (click a trade to open its day) and a chart. The chart shows the signal candles with swings, CHoCH / BOS,
SETUPs, the protected level and the AVWAP pair, or the traded option's own candles.

The first run after a data change is slower. The CSVs are parsed into `cache/` once and numba compiles the engine once
(also cached).

## Files

```
core.py              data cache · numba engine · option chain · positions / pricing / stats · runner · results · charts
strategies/stNN.py   SPEC + signals(); file order = the order on the page
backtest.py          CLI: one strategy per call
server.py            JSON API + static ui/; backtests queue and run one at a time in-process
ui/                  index.html, app.css, app.js (lightweight-charts from jsdelivr)
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
| ST25–ST28 | CHoCH to CHoCH put retest (`c2c_v1`): options via futures, 5-minute, PCR from open interest, premium stop / trail, 15:15 ladder | `strategies/c2c.py` (family module with its own `run`) |
| ST29, ST30 | Rainbow ribbon intraday (`rainbow_v1`), futures only; the ribbon is drawn on the day chart | `strategies/rainbow.py` (family module) |

Not ported yet: the FZ gate (ST5–ST8) and the learner (ST19–ST24). `core.validate` refuses a strategy
file whose entry rule or position block needs a feature that is not ported, so nothing runs silently with the wrong
rules. Each port gets parity cases in `tests/test_parity.py` before its numbers are trusted. v1's result history
(`results/history`), the SQLite tables and the chart explorer are not carried over.

A family of strategies that shares rules beyond the Foundation engine (rainbow today) keeps them in
`strategies/<family>.py`, loaded with `core.family("<family>")`; the numbered files stay one per strategy. A strategy
module can also declare `ENTRY_RULES`, `TYPES`, `UNDERLYINGS`, `TIMEFRAMES` (+ `REFUSED_WHY` / `TF_WHY`: what it does
not run is refused with that reason), `OWN_COVERAGE` (it checks full-chain option data per trade instead of per window)
and `run(ctx)` (it builds its own trades for a type; pricing, stats and results stay in `core`).
