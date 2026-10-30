# G1 "theta harvest" — implementation spec for an independent backtest

Purpose: re-implement this rule from scratch in the strategy lab (do not reuse the Cowork engine) and reconcile against the
reference numbers at the end. Treat every number here as a claim to be checked, not a target to be hit.

## 1. Data
- Source: the Breeze 1-minute store `D:\nifty_data` (index/1minute, options/1minute). Use every expiry folder; read both
  `*.parquet` and `*.wide.parquet` in an expiry folder and drop duplicate (datetime, strike, right) rows.
- Session: one-minute bars from **09:16 to 15:29 inclusive** for options. **Drop the 09:15 one-minute bar**: Breeze's 09:15
  option candle opens on the previous close (a stale print) and its high/low include it.
- 5-minute bars: group the one-minute bars by `floor(datetime, 5min)`; label = bar start; open = first, high = max,
  low = min, close = last, volume = sum. The bar labelled 09:30 therefore covers 09:30:00–09:34:59 and its close is known at 09:35.
- Index: NIFTY 50 one-minute bars 09:15–15:29, same 5-minute grouping. Spot for a decision = the index 5-minute close of the
  same bar label as the option bar used.
- Expiries: every expiry present in the store. "Front expiry" for a session D = the earliest expiry date >= D.
  dte = (expiry date − D) in calendar days.
- Window to run: sessions from **2020-06-01** to the end of the store (last expiry 2026-10-19).

## 2. When to trade
- Trade on every session whose front expiry has **dte = 1 or dte = 2** (the session before expiry and the one before that;
  with Tuesday expiries that is Monday and Friday; with Thursday expiries, Wednesday and Tuesday).
- Decision time: the close of the 5-minute bar labelled **09:30** (i.e. at 09:35). Nothing after that bar is used for the decision.

## 3. What to sell (per side, independently: one CE and one PE)
- ATM = round(spot / 50) * 50 using the index close of the 09:30 bar.
- Candidate strikes: CE strikes strictly above ATM (ATM+50, ATM+100, … up to ATM+1450); PE strikes strictly below ATM.
- Candidate filter at the 09:30 bar: option **close >= ₹5** and bar **volume >= 5 lots** (lot size of that expiry, see §7).
- For each candidate solve the Black-Scholes implied vol from the 09:30 bar close:
  S = index close of that bar, K = strike, r = 6.5% continuous, q = 0, T = (expiry date 15:30 − 09:35 on D) in years / 365.
  Solve with a root finder on [0.0001, 5.0]; if the price is at or below intrinsic + 0.01, skip the strike.
- Delta from the same inputs (CE: N(d1); PE: N(d1) − 1).
- **Pick the candidate whose |delta| is nearest to the target (primary 0.10; variants 0.15, 0.25).** Ties: the strike nearer ATM.
- If a side has no candidate, skip that side for the day.

## 4. Fills and exits
- Sell at the 09:30 bar close **minus slippage**, slippage = max(₹0.05, 0.5% of price) per side.
- **Primary exit: hold to expiry.** Close at the close of the last 5-minute bar of expiry day (labelled 15:25) **plus slippage**.
  (Note for the write-up: real settlement is at intrinsic value on the official close; the last trade is used here. Report
  both if easy; the difference is small for strikes that expire OTM.)
- Variant exit: stop at **2x the sale price** — on any later 5-minute bar whose high >= stop, cover at the worse of the bar's
  open and the stop level; if that bar is the first bar after the sale, or the first bar of a day (gap), cover at that bar's
  close; otherwise cover at the 15:25 close of the sale day.
- A dte-2 sale is held overnight into the next session when held to expiry.

## 5. Costs (per leg, Zerodha, current rates)
- Brokerage ₹20 per executed order (₹40 for the round trip).
- STT 0.1% of the premium on the **sell** leg; NSE transaction charge 0.03503% of premium both legs; SEBI ₹10 per crore both
  legs; stamp duty 0.003% on the **buy** leg; GST 18% on (brokerage + exchange + SEBI).

## 6. Position rules
- 1 lot per leg; both legs every qualifying session; no other filter (no OI, no trend, no vol condition).

## 7. Lot size by expiry (NSE circulars)
- 75 for expiries up to 22 Jul 2021; **50** from the 29 Jul 2021 monthly and all weeklies from Aug 2021;
  **25** for expiries from 2 May 2024 (circular effective 26 Apr 2024) through Dec 2024;
  **75** for 2025 expiries except the 30 Jan 2025 monthly (25, introduced before the change);
  **65** from the 6 Jan 2026 expiry onward (circular FAOP70616).

## 8. What to report
- Trades, sessions, hit rate (net > 0), premium points per trade (sale − cover), ₹ per trade, total ₹; by year.
- Realised worst day, max drawdown of the daily realised P&L, day-clustered t-stat (daily P&L series).
- Mark-to-market: for hold-to-expiry trades, the maximum (bar high − sale price) × lot after entry, per trade; count trades
  where it exceeded 3x, 5x and 10x the premium; worst MTM day across both legs.
- A truncation test: cut each day's bars at a random bar and confirm the 09:30 decision is unchanged.

## 9. Reference results to reconcile (Cowork run, 2020-06-01 → 2026-10-19, official lots)
| variant | trades | hit | pts/trade | ₹/trade | total ₹ | worst day | max DD |
|---|---|---|---|---|---|---|---|
| |delta|≈0.10, hold to expiry | 1138 | 92.9% | 5.86 | 303 | 3,45,021 | −23,967 (23 Feb 2022) | −28,603 |
| |delta|≈0.15, hold to expiry | 1138 | 88.8% | 5.97 | 330 | 3,75,340 | −30,680 | −49,193 |
| |delta|≈0.25, hold to expiry | 1138 | 81.3% | 6.80 | 408 | 4,64,825 | −33,848 | −97,643 |
| |delta|≈0.10, stop 2x, cover 15:25 | 1138 | 67.0% | 1.68 | 41 | 46,373 | −3,795 | −7,250 |

By year, |delta|≈0.10 hold to expiry (₹): 2020 63,373 · 2021 79,179 · 2022 33,739 · 2023 21,592 · 2024 28,858 · 2025 84,511 · 2026 33,768.
MTM for the same: premium went >= 3x against on 154 trades, >= 5x on 111, >= 10x on 54 (of 1138); worst MTM day ₹29,932 (2 Feb 2026).
Every trade is in `G1_theta_harvest_reference_trades.csv` (sale/cover prices after slippage, delta, lot, net). Reconcile trade by
trade first (same strike chosen on the same day), then the aggregates. Expect small differences from the IV root-finder and
from the last-trade vs settlement treatment; expect no difference in strike choice except where the implementations disagree on
the 09:30 bar boundary or the stale 09:15 minute.

## 10. Known caveats to carry into the write-up
- Expiries before Apr 2025 hold only strikes within ~±250 points of that week's index range; the full chain exists only from
  the 3 Apr 2025 expiry. For this rule the effect can only move the chosen strike nearer ATM (riskier) when far strikes are
  missing. Report the share of days where the chosen strike was the outermost available.
- The hit rate is structural: P(expires worthless) ≈ 1 − |delta|. The expectancy is the variance risk premium; the tail is
  naked. Margin calls on MTM days are not modelled. Simulation only — never place orders from this.
