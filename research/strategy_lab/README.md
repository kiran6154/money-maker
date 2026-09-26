# Strategy lab

Prototype bench for NIFTY futures strategies before they are coded into money-maker.
Every strategy is the same **foundation engine** run with a different row in the `strategy` table.

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
- Breaks are by touch or close (`break_mode`).

## Strategy → signal groups → variants
**Terminology.** *Position* is long or short; *instrument* is FUT, CE or PE; *signal* is bullish or bearish (for the future
signal group: future long / future short). Long and short positions can exist in futures and in both CE and PE. Short option
P&L is sell-at-entry, buy-at-exit; margin is not modelled.

**Strategy level** (one card per `family`, e.g. Foundation · 5 min): timeframe, engine rules, SL rule, and the option settings
**expiry** (Weekly / Monthly) and **strike** — chosen on the card and applied to every option row and to the chart.

| Group (`signal_source`) | Row (code) | Positions |
|---|---|---|
| **Future signal** | Futures (`S5M`) | long future on future long, short future on future short |
| | Options long only (`S5M_FL`) | long CE on future long, long PE on future short |
| | Options short only (`S5M_FS`) | short PE on future long, short CE on future short |
| | Options long + short (`S5M_FB`) | both of the above |
| **Option native signal** | Options long only (`S5M_NL`) | long on bullish setups on the option's own chart (CE and PE) |
| | Options short only (`S5M_NS`) | short on bearish setups |
| | Options long + short (`S5M_NB`) | both |

Each option group is computed once per period with both sides; the long-only and short-only rows are the matching side of that
run (same signals, same fills). **Group total** = every distinct position in the group (Futures + Options long + short for the
future signal group; Options long + short for option native) — long only / short only are not added again. Clicking a group
heading opens its cumulative P&L. The dashboard's All · Long · Short (Future long · Future short) switch filters by signal.
Rows `S*M_OF / _OB / _OS / _ON` from earlier versions are kept disabled.

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
