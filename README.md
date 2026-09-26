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

## Files
| Path | What |
|---|---|
| `engine.py` | foundation engine (pure; no I/O besides loading candles) |
| `lab.py` | runs enabled strategies, stores results, writes dashboard + exports |
| `dashboard.tpl` | dashboard template (`dashboard.html` is generated) |
| `config/strategies.json` | **versioned** copy of the `strategy` and `charge_schedule` tables |
| `results/summary.json`, `results/trades.csv` | **versioned** latest headline numbers and trades — diff them across commits |
| `tools/` | Kite data downloads (`kitefut.py` 5-min, `kite1m.py` 1-min); credentials read at runtime from money-maker |
| `strategy_lab.db` | SQLite working DB (not versioned; rebuilt from `config/strategies.json` if missing) |

## Tables
`strategy` (definition + rules), `charge_schedule` (brokerage/STT/exchange/SEBI/stamp/GST rates),
`strategy_run`, `trade`, `choch_signal` (results per run).

## Workflow
```
python lab.py                 # run all enabled strategies, rebuild dashboard + exports
python lab.py S1M             # run one
python -m http.server 8766    # then open http://localhost:8766/dashboard.html
```
Change a rule → edit the strategy row (or add a new row for a variant) → `python lab.py` →
commit `config/` + `results/` together so the commit shows the rule change and its before/after numbers.

## Data
`D:/nifty/niftyfut_5minute_2026-07-01_to_2026-09-25.csv`, `D:/nifty/niftyfut_minute_2026-07-01_to_2026-09-25.csv`
(NIFTY26SEPFUT from Kite; `front_month` = 1 from 2026-08-26).
