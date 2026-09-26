# Strategy lab

Prototype bench for NIFTY futures strategies before they are coded into money-maker.
Every strategy is the same **foundation engine** run with a different row in the `strategy` table.

## Foundation (engine.py)
swings (Pine port) → protected level → CHoCH / BOS → AVWAP pair from previous SH & SL at each CHoCH → SETUP → trade

- **Protected low (uptrend):** latest unbroken SL that sat below the trend AVWAP when it confirmed; protected high mirrors it.
- **CHoCH:** protected level broken; trend flips if the AVWAP is broken too.
- **SETUP:** after a CHoCH, both pair AVWAPs slope with it (vs previous candle) and a candle closes beyond the CHoCH candle low (PE) / high (CE).
- **Exit:** stop loss (per `sl_rule`), else close of the next CHoCH candle.
- Breaks are by touch or close (`break_mode`).

## Variants (column `variant`, grouped by `family`)
| Variant | Signals | Trades | Strike |
|---|---|---|---|
| `FUT` | future | future (long / short) | — |
| `OPT_FUT_SIGNAL` | future | buy CE on bullish, PE on bearish | at the signal candle, from spot |
| `OPT_NATIVE` | the option's own candles (buy-only: bullish setups on CE and PE) | that option | CE and PE fixed per day at the first completed candle, from spot |

Option variants run once per `strike_choices` entry (default `ATR2` = spot ± 2×ATR(14) of the timeframe, OTM, rounded to 50;
also `ATM`, `ITMn`, `OTMn`) and the dashboard switches between them. Option prices come from the full Kite chain for the
29-Sep expiry (`tools/kite_options.py`); spot from `tools/kite_spot.py`. Slippage per side is `slippage_pts`
(futures 5, options 0.5). Charges: `ZERODHA_NFO_FUT` / `ZERODHA_NFO_OPT` in `charge_schedule`.

Fills: entry at the SETUP candle close; stop at the worse of candle open and stop, or the session's first candle close.
Look-ahead check: `python tests/test_truncation.py`.

## Files
| Path | What |
|---|---|
| `engine.py` | foundation engine (pure; no I/O besides loading candles) |
| `lab.py` | runs enabled strategies, stores results, writes dashboard + exports |
| `dashboard.tpl` | dashboard template (`dashboard.html` is generated) |
| `config/strategies.json` | **versioned** copy of the `strategy` and `charge_schedule` tables |
| `results/summary.json`, `results/trades.csv` | **versioned** latest headline numbers and trades — diff them across commits |
| `tools/` | Kite downloads: `kitefut.py` / `kite1m.py` futures, `kite_spot.py` index, `kite_options.py` option chain; credentials read at runtime from money-maker |
| `web/` | per-variant, per-strike detail JSON the dashboard loads (generated, not versioned) |
| `tests/test_truncation.py` | look-ahead test |
| `strategy_lab.db` | SQLite working DB (not versioned; rebuilt from `config/strategies.json` if missing) |

## Tables
`strategy` (definition + rules), `charge_schedule` (brokerage/STT/exchange/SEBI/stamp/GST rates),
`strategy_run`, `trade`, `choch_signal` (results per run).

## Workflow
```
python lab.py                 # reuse stored results, recompute only what changed, rebuild dashboard + exports
python lab.py --full          # recompute everything
python lab.py S1M             # one strategy / family
python -m http.server 8766    # then open http://localhost:8766/dashboard.html
```
**Stored results:** each (strategy, period, strike choice) is written to `web/<code>/<period>/<choice>/` as `summary.json`
(KPIs, trades, signals, chart index) plus one `c<k>.json` chart chunk per session (per day-contract for option · native).
`summary.json` carries a cache key over the strategy row, the period, `engine.py` + `lab.py`, and the input data files;
a run is reused while the key matches. **Test periods** live in the `test_period` table (IS / OOS).

**Dashboard loading:** it reads the summary, then only the session on screen; ‹ › and the session list fetch more on demand,
and *Full period* loads every session of the period into one chart only when clicked.
Change a rule → edit the strategy row (or add a new row for a variant) → `python lab.py` →
commit `config/` + `results/` together so the commit shows the rule change and its before/after numbers.

## Data
`D:/nifty/niftyfut_5minute_2026-07-01_to_2026-09-25.csv`, `D:/nifty/niftyfut_minute_2026-07-01_to_2026-09-25.csv`
(NIFTY26SEPFUT from Kite; `front_month` = 1 from 2026-08-26).
