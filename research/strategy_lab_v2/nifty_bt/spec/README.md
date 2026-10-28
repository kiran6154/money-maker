# Handoff pack — for the "backtesting architecture" chat

Paste or attach these files in that chat and ask:

> "Implement every strategy version in STRATEGY_SPEC_v2.md in our backtesting architecture. Start with §0 priority 1–2
> (engine + Supertrend-swing CHoCH/BOS ₹100+ SELL+BUY). Use `reference_code/` as the oracle (Python), and the
> `golden_trades/` CSVs as acceptance tests: match trade counts and net within ±1 % and the first 20 trades exactly.
> Keep every parameter configurable. Simulation only — no live orders."

Contents
- `STRATEGY_SPEC_v2.md`: complete spec (data, conventions, indicators, every strategy version, results, validation,
  live-use requirements, what failed).
- `golden_trades/G1…G7.csv`: reference trade lists (entry/exit time and price, why, net ₹ per lot of 75).
- `reference_code/`: the Python that produced every number. File → section map:
  - `mtf_bt.py`: Supertrend, pivots/structure, index loader;
  - `opt_sim.py`: option costs;
  - `scan_*.py`, `build_opt_1m.py`: strike scan / data build;
  - `possell.py` (§6.1), `conf_sim.py` + `conf_seq.py` (§6.3), `lock50.py` + `lock_p100_sell.py` (§5.4);
  - `buy_sim.py` + `buy_seq.py` (§6.5), `hedge.py` (§5.5), `combo.py` (§6.6);
  - `stswing*.py` (§12.2–12.3), `choch_st.py` (§12.4);
  - `intra_*.py` (§12.5–12.6), `scale500.py` + `compound500.py` (§12.7);
  - `late_entry.py` (§12.8), `rally_eda.py` (§12.9), `chop_filter.py` + `daytype_study.py` (§4.6–4.7).
