# nifty_bt — the handoff option strategies as a simulator

Implements `spec/STRATEGY_SPEC_v2.md` (the "NIFTY Supertrend / CHoCH-BOS option strategies" handoff pack the user attached
2026-10-28): every §0 study, on the Breeze store (`D:/nifty_data`, read-only). Simulation only — nothing here can place an
order. Results and the measured comparison with the spec are in `docs/STRATEGY_ANALYSIS_TODO.md` S162.

```
python -m nifty_bt.golden            # rebuild G1-G7 and compare with spec/golden_trades (results/nifty_bt/golden/)
NBT_PARITY_DAYS=14 python -m nifty_bt.golden   # same on the handoff's data window (results/nifty_bt_parity14/)
python -m nifty_bt.books             # every §0 study + §2.9 report (results/nifty_bt/books/; candidates cached)
NBT_NEXP=12 python -m nifty_bt.books # smoke test on the last 12 expiries
python -m nifty_bt.validate          # §9 checks: look-ahead, truncation, strike timing, raw-candle fills, lock, sequencing
```
On the dashboard: ST151 - ST157 (G1 - G7), ST158 (§6.6 ₹100+ SELL + BUY), ST159 (§12.2 ₹100+ positional SELL + BUY), via
`strategies/handoff.py`, which reads the trade lists above (rerun `golden` / `books`, then the strategy's backtest, after a change).
Charts (`chartdata.py`): the main chart is the NIFTY index for reference; the CE / PE panes (full width) are the option itself -
per session the contract the book watched (the day's pick) or held (an open trade's contract; a purple tag marks each switch),
or one traded contract picked in the pane - rebuilt as the books built it, with the Supertrend (green up / red down), the swings
and CHoCH / BOS the entry read (Supertrend segments, pivots, or the 5-minute pivots under the 15-minute Supertrend as known at
each 5-minute close), EMA20 (G7), the stop in force at each bar (trailed to newer swings, to the entry after +50) and the lock
trigger, and a 15-minute view for the books that read two timeframes. On 25 random trades per book (225) the entry's event and
Supertrend side sit on the signal bar and the drawn stop starts at the engine's stop; on 120 stop exits the drawn stop ends at the
fill (or the fill gapped through it).

Run from `research/strategy_lab_v2`. The first run builds `results/nifty_bt/chain_0919.parquet` and `picks.parquet`
(~6 minutes); the books' candidate pass takes ~20-40 minutes and is cached as `results/nifty_bt/books/cand_*.parquet`.

| Module | Spec | What |
|---|---|---|
| `data.py` | §1 | expiry folders (regular + `.wide`; `.wide3k` off), 2026 zip archives (zip rows win on duplicates, as the reference), index 1-min with the 2026-08-03 15:15+ prints dropped, 09:15 five-minute spot; option prices through float32 as the reference stored them; `NBT_PARITY_DAYS` |
| `chain.py` | §3.1-3.2 | trade expiry (next strictly after the day, <= 35 days; the 2018-02-23 .. 03-28 gap skipped), the 09:19 chain, every pick rule (ATM, p100, p300, p500, p500up, p750, u50, p40, u30, u15), the front-expiry ATM plan |
| `indicators.py` | §3.3, §4.1-4.3 | 09:15-anchored bars with close time, Supertrend, pivots + CHoCH / BOS, Supertrend-segment swings, EMA, Wilder ATR, PSAR, RSI |
| `filters.py` | §4.4-4.7 | daily ST direction, ADR, chop filter, day-type score |
| `costs.py` | §2.4 | option charges (lot a parameter, 75 by default) |
| `engine.py` | §3.4, §5, §6, §12.2-12.5 | `Contract`, swing trades (trail, lock50), ST + confirm SELL / BUY with exits and the §5.4 locks, pivot CHoCH -> ST, intraday grid, §6.1 ATM book, `sequence()` |
| `research.py` | §5.5, §12.3, §12.6, §12.8 | hedge overlay, 1-min swings / 5-min signals, dual Supertrend (+ daily caps), late entry |
| `chartdata.py` | - | the dashboard charts: each contract rebuilt as the books built it; Supertrend line, swings, CHoCH / BOS, stop path, lock level, chop values (checked against the engine's own functions) |
| `report.py` | §2.9, §12.7 | stats (2018-22 / 2023-26, ₹1 / ₹2 slippage, yearly), flat-candle share, lot scaling, `SizingPolicy` (Fixed, DoubleUp, DoubleUpDown, AddOne), compounding |

## Golden parity (why the lists do not match to the trade)

The store was re-downloaded on 2026-10-25 with much longer per-expiry history than the handoff had (from 2019 its folders
held about the two weeks before expiry), and the index / some option rows changed. Every trade both lists share has the
same exit (99.8-100 %), the first 20 trades of all seven lists are identical, and G1 / G4 pass the ±1 % test with
`NBT_PARITY_DAYS=14`; the remaining gaps are trades that exist only because of data the handoff did or did not have.
G5 (60-minute ST over each contract's whole folder history) is the most sensitive to the history window.
