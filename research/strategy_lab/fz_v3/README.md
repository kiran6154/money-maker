# FZ v3 study workspace

Inputs and notes for the FZ v3 research program (see `BRIEF.md` and `docs/STRATEGY_ANALYSIS_TODO.md` S49).
Committed on the user's instruction (2026-09-29) so the study can run in a Claude cloud environment
without the local `D:/nifty` files.

`data/` holds byte-for-byte copies of the four input files that `config/data.json` names on the local box:

| file | rows | what |
|---|---|---|
| `niftyfut_nearmonth_minute_2021-10-01_to_2026-09-25.csv` | 1-minute | NIFTY near-month futures, unadjusted roll, `front_month` column |
| `niftyfut_nearmonth_5minute_2021-10-01_to_2026-09-25.csv` | 5-minute | same, 5-minute |
| `nifty50_breeze_minute_2021-10-01_to_2026-09-25.csv` | 1-minute | NIFTY 50 spot (no usable volume) |
| `nifty50_breeze_5minute_2021-10-01_to_2026-09-25.csv` | 5-minute | same, 5-minute |

Study scripts read these paths directly through `engine.load`; they never go through `lab.sessions()`,
which honours `history_from` in `config/data.json`. Study outputs go under `fz_v3/out/` (not committed
unless they are part of a result the user asked to keep).
