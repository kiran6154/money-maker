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

## Strategy → type → scheme
| Level | Values | Where it is set / seen |
|---|---|---|
| **Strategy** (`family`) | Foundation · 5 min, Foundation · 1 min | one card each: rules, timeframe, SL; the card's **options bar** holds option **expiry** (Weekly / Monthly) and **strike**, shared by both option types |
| **Type** (one `strategy` row each) | Futures (`S5M`) · Options (via futures) (`S5M_FB`) · Options (standalone) (`S5M_NB`) | a row on the card |
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

## Backtests, timeframes, statistics
- **Backtests are per strategy** (`strategy_backtest`): each row is one independent run over its own dates (plus warm-up) —
  `all` (every session after warm-up), presets `1M 3M 6M YTD 1Y 5Y` counted back from the latest data date, or named/custom
  ranges such as **Design period** (26 Aug – 25 Sep: the rules were built here) and **Unseen test** (8 Jul – 25 Aug). A backtest
  the data cannot cover is **refused with the reason** (e.g. 3M needs data before 1 Jul). Add one:
  `python lab.py backtest S5M 1Y` · `python lab.py backtest S5M 2026-07-10 2026-08-10 --label "July"`.
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
  charges sensitivity, month by month, other timeframes, expiry × strike) · Breakdown · Daily P&L · Signals · Config · Rules.

## Workflow
```
python lab.py                 # reuse stored results, recompute only what changed, rebuild dashboard + exports
python lab.py --full          # recompute everything
python lab.py S1M             # one strategy / family
python lab.py backtest S5M 1Y # add a backtest to a strategy and run it
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
