# NIFTY Supertrend / CHoCH-BOS option strategies — implementation spec (v2, all versions)

**Audience:** an AI coding agent (Claude) building these strategies from scratch. Everything you need is in this file:
- conventions;
- exact definitions;
- parameters;
- the backtest numbers you should reproduce (±5 %);
- a validation checklist.

**Status:** research / backtest only. Nothing here has been paper-traded. Build it as a **simulator first**. Live order
placement must be a separate, explicitly-approved step with hard risk limits in code (see §10).

---

## 0. Priority — what to build first (v2)

| # | Build | Spec |
|---|---|---|
| 1 | Common engine: data, strike scan, premium bars, Supertrend, swing structures (pivot **and** Supertrend-segment), fills/costs, one-position-per-leg sequencing, candidate→sequence pipeline | §1–§4, §12.1 |
| 2 | **★ Supertrend-swing CHoCH/BOS, ₹100+ positional SELL + BUY** — current best | §12.2 |
| 3 | ST-flip + 5-min confirm + LOCK, ₹100+ SELL + BUY (previous best; run alongside) | §5.4, §6.6 |
| 4 | Normal pivot CHoCH → Supertrend-confirmation variant | §12.4 |
| 5 | Intraday variants (5-min confirm + chop filter; dual Supertrend) | §12.5–12.6 |
| 6 | Lot scaling / compounding module | §12.7 |
| 7 | Hedge overlay, day-type score, cheap-buy grid, late-entry, rally EDA (research) | §5.5, §4.7, §6.7, §12.8–12.9 |

**Golden trade lists** in `golden_trades/` (G1–G7) are the acceptance tests. Your engine must match each file's trade count
and net within ±1 %, plus entry/exit time and price of the first 20 trades exactly.

| File | Strategy | Trades | Net ₹ |
|---|---|---|---|
| G1 | ST-swing ₹100+ positional SELL · 5m ST(4,3) · CHoCH+BOS · trail + lock50 | 1,153 | +8,94,411 |
| G2 | ST-swing ₹100+ positional BUY · 15m ST(4,3) · CHoCH · trail + lock50 | 410 | +5,88,240 |
| G3 | ₹100+ SELL · 15m ST(4,3) + 5m confirm · ST exit · lock50 / ₹50 target | 1,541 | +7,92,410 |
| G4 | ₹100+ BUY · 15m ST(4,3) + 5m confirm · ST exit · lock → expiry | 1,322 | +9,47,207 |
| G5 | ATM positional SELL · 60m ST(4,3) flip · front expiry | 584 | +7,43,214 |
| G6 | ₹100+ SELL · 15m pivot CHoCH/BOS → ST(10,3) confirm · trail | 2,401 | +8,83,110 |
| G7 | Intraday ₹100+ BUY · 15m ST(10,3) + 5m confirm · EMA20 exit · chop filter | 474 | +1,99,409 |

---

## 1. Data

Root (user's laptop): `D:\nifty_data`

```
index/1minute/<year>/<YYYY-MM>[.partial].parquet          # NIFTY spot 1-min: datetime, open, high, low, close
options/1minute/<year>/<expiry YYYY-MM-DD>/<d1>__<d2>.parquet        # "regular" strikes
options/1minute/<year>/<expiry YYYY-MM-DD>/<d1>__<d2>.wide.parquet   # extra strikes (full chain from 2019-09-12)
(+ zip archives containing <expiry>/<file>.parquet for some 2026 expiries)
```

**Option columns:** `datetime, strike, right ('CE'/'PE'), open, high, low, close, volume, open_interest, expiry`.
- Each expiry folder holds that expiry's contracts, but only for the ~1–2 weeks before expiry.
- There is no far-month data.

**Coverage notes** (you must handle these):
- **2018:** monthly expiries only, regular files only (narrow chain, ~16 strikes/day). The 2018-03-28 folder is
  missing, so skip 2018-02-23 … 2018-03-28 rather than substituting another expiry.
- **2019-01 … 2019-09-11:** weeklies from Feb 2019, still a narrow chain.
- **2019-09-12 onward:** regular + wide files form the full chain.
- **Index data bug:** from 2026-08-03 the index prints at 15:15–15:29 are bad. Drop those minutes.
- Sessions run 09:15–15:29. Use minute-of-day `tod = hour*60+minute`; the session is 555…929.
- Deep-ITM options (premium ≥ ₹300) are **illiquid**: 16–71 % of their 1-min candles are flat (o=h=l=c, no trade).
  Report this whenever such strikes are used.

---

## 2. Global conventions (non-negotiable)

1. **No look-ahead.** A signal computed on a bar is known only at that bar's close.
   - Act at the **next 1-min bar's open**.
   - Higher-timeframe bars count only once closed. A 1-min bar starting at `t` may use an HTF bar of length
     `L` only if `htf_start <= t + 1 - L`.
2. **No hindsight in strike selection.** Strikes are chosen from data available at the selection time (§3).
3. **Fills.**
   - **Entry:** next 1-min open.
   - **State-based exit** (an indicator condition on a bar close): next 1-min open after that bar closes.
   - **Stop:** a buy-back stop on a short fills at `max(open, stop)`; a sell stop on a long fills at `min(open, stop)`.
     This covers gaps.
   - **Limit target:** a short's target fills at `min(open, target)`; a long's at `max(open, target)`.
   - **Expiry exit:** the open of the 15:15 bar on expiry day. If that minute is missing, use the next available
     bar, or the last close.
4. **Option charges per round trip, 1 lot** (implemented as `costs(entry, exit, d)`, where d = +1 for a buy, −1 for a sell):
   - brokerage ₹20 × 2;
   - STT 0.1 % of the sell-side premium turnover;
   - NSE transaction charge 0.03503 % on both sides;
   - SEBI fee 1e-6 × turnover;
   - stamp duty 0.003 % on the buy side;
   - GST 18 % on (brokerage + exchange + SEBI);
   - slippage ₹0.10 per side × lot (i.e. ₹15 per round trip).
   
   Typical total: ₹62–140 per round trip.
5. **Lot size: fixed 75** for all years. The real NIFTY lot changed over time, so rupee results are approximate.
   Make it a parameter.
6. **Minimum premium to trade:** ₹2.
7. **Positions:** one open position per **leg**. Legs are independent books: e.g. SELL-CE, SELL-PE, BUY-CE, BUY-PE.
   A new signal on a leg is ignored while that leg has an open position (sequencing in §3.4).
8. **Futures (intraday studies only):**
   - charges about ₹390 per round trip plus 1 pt slippage per side (≈ 5.3 index pts in total);
   - lot 75.
9. **Always report:**
   - net, trades, win %, max drawdown, worst trade, worst open (mark-to-market) loss;
   - yearly P&L;
   - **2018–22 vs 2023–26 split**;
   - result with ₹1 / ₹2 slippage per side;
   - flat-candle share for illiquid strikes.

---

## 3. Contract selection (the "scan") and sequencing

### 3.1 Trade expiry
For session date D:
- **Positional option studies** (recommended): use the nearest expiry folder **strictly after** D, so you never trade
  an option on its own expiry day. It must be within 35 calendar days.
- *Older ATM study variant:* the nearest expiry ≥ D (includes expiry day).

### 3.2 Strike picks
Built from the 09:19 1-min close of every strike of the trade expiry. That close is known at 09:20; spot is the NIFTY
09:15 5-min close.

| Pick id | Rule | Typical result |
|---|---|---|
| `ATM` | strike nearest spot | premium ~₹112 |
| `p100` ("₹100+") | **cheapest** premium ≥ ₹100 | ~₹111, ≈ ATM (−90…+190 pts OTM) |
| `p300` | premium closest to ₹300 | ~260 pts ITM (illiquid) |
| `p500` | dearest premium ≤ ₹500 | ~440 pts ITM (illiquid) |
| `p500up` ("₹500+") | **cheapest** premium ≥ ₹500 | ~₹529, ≈ 520 pts ITM (illiquid) |
| `p750` | premium closest to ₹750 | ~730 pts ITM (very illiquid) |
| `u50` | **OTM only**, dearest premium < ₹50 (≥ ₹2) | ~₹44, ≈ 190 pts OTM |
| `p40` | OTM only, closest to ₹40 | ~205 pts OTM |
| `u30` | OTM only, dearest < ₹30 | ~₹26, ≈ 280 pts OTM |
| `u15` | OTM only, closest to ₹15 | ~375 pts OTM |

Pick separately for CE and PE.
- A contract is **"watched" only on the days it is the pick**. New entries are allowed only on watched days.
- An open position stays on its own contract until it exits, even after that contract stops being the pick.

### 3.3 Premium bars
Build bars from each contract's own 1-min premium data:
- **Warm-up:** include the 3 sessions before the contract's first watched day.
- **Bucketing:** `bucket = date + 555 + floor((tod-555)/L)*L` minutes. 15-min bars are anchored at 09:15; the last
  bar is 15:15–15:29.
- **Bar close time:** `last_minute_in_bar + 1 min`.

Supertrend is computed continuously across days (positional). For intraday index studies, HTF values must come from
the same session only.

### 3.4 Sequencing (one position per leg)
For each leg:
1. Sort the candidate entries by signal time.
2. Take a candidate if `signal_time >= exit_time of the previous taken trade`.
3. Each candidate's outcome is independent of other trades. So you can first compute every candidate's outcome,
   then sequence. This is memory-efficient; process per expiry file.

---

## 4. Indicators and filters (exact definitions)

### 4.1 Supertrend(p, m) — "ST"
- `TR = max(H−L, |H−C₋₁|, |L−C₋₁|)`; ATR is Wilder RMA, `ewm(alpha=1/p, adjust=False)`.
- `hl2=(H+L)/2`; `ub = hl2 + m·ATR`; `lb = hl2 − m·ATR`.
- Final upper band: `fu[i] = ub[i] if (ub[i] < fu[i−1] or C[i−1] > fu[i−1]) else fu[i−1]`.
- Final lower band: `fl[i] = lb[i] if (lb[i] > fl[i−1] or C[i−1] < fl[i−1]) else fl[i−1]`.
- Direction: `dir[i] = +1 if C[i] > fu[i−1]; −1 if C[i] < fl[i−1]; else dir[i−1]`. Line = `fl` if up, `fu` if down.
- A **flip** is a change in `dir` between consecutive bars.
- Parameters used: **(4,3)**, (10,3), (7,2).

### 4.2 Swing pivots and CHoCH / BOS (structure)
- **Swing high at p:**
  - `H[p] > max(H[p−N … p−1])` and `H[p] >= max(H[p+1 … p+N])`;
  - confirmed (usable) at bar `p+N`.
  
  Swing lows mirror this.
- **State:**
  - last confirmed swing high `top` and low `bot`, each flagged "not yet crossed";
  - `trend ∈ {+1, −1, 0}`.
- **At each bar close:**
  - If `close > top` (uncrossed): event = **BOS +1** if trend was +1, else **CHoCH +2**. Set trend = +1 and mark
    `top` crossed.
  - If `close < bot` (uncrossed): event = **BOS −1** if trend was −1, else **CHoCH −2**. Set trend = −1 and mark
    `bot` crossed.
- **Bearish event** = event < 0 (BOS or CHoCH); bullish = event > 0.
- **Parameters:**
  - 1-min structure: N = 5;
  - 5-min structure: N = 3;
  - (intraday index study also used N = 3).
- Also track the latest swing low/high (`last_sl`, `last_sh`) and newly confirmed swings (`new_sl`, `new_sh`) for
  stops and trails.

### 4.3 Exit indicators (on 15-min premium bars unless stated)
- **EMA20:** `ewm(span=20, adjust=False)` of close. Short exit: close > EMA20. Long exit: close < EMA20.
- **Chandelier (22, 3):**
  - ATR22 is Wilder; short exit: `close > lowest_low(22) + 3·ATR22`;
  - long exit: `close < highest_high(22) − 3·ATR22`.
- **Parabolic SAR (0.02 / 0.2):** standard. Short exit when it flips bullish, long exit when bearish.
- **RSI(14):** Wilder. Used as a take-profit (short: RSI < 30) with ST as the stop. *Performed badly; keep only for
  comparison.*
- **5-min CHoCH back:** short exit on a bullish 5-min structure event; long exit on a bearish one.

### 4.4 Daily ST direction filter (index)
- Daily NIFTY bars from 1-min data; Supertrend(10,3) or (7,2).
- Direction for day D = the value at **D−1's close** (shift by 1).
- **Sell side:** up → only sell PE; down → only sell CE.
- **Buy side:** up → only buy CE; down → only buy PE.
- Optional exit: if the daily ST turns against an open position, exit at the next session's 09:15 open.

### 4.5 ADR
ADR = mean(high − low) of the previous 20 sessions, excluding today.

### 4.6 Index choppy-day filter — "chop filter"
Evaluated on index data at the signal minute (bars ≤ the signal bar only):
- `rng_so_far = (day_high_so_far − day_low_so_far) / ADR` **≥ 0.8** (A)
- `ER = |close − day_open| / Σ|Δclose since open|` **≥ 0.10** (B; efficiency of the day's path)
- `pos_dir ≥ 0.8` (C), where `pos = (close − day_low)/(day_high − day_low)`:
  - `pos_dir = pos` if the trade bets on the index **rising** (long futures, buy CE, sell PE);
  - `pos_dir = 1 − pos` if it bets on a fall.

Trade only if A and B and C are true.
- A alone did most of the work in futures. The thresholds were chosen on 2018–22 and held up on 2023–26.

### 4.7 Day-type score (live; for reporting or as an alternative filter)
At checkpoints 10:15 / 11:00 / 12:00 / 13:00, score 1 point each for:

| Measure | 12:00 threshold |
|---|---|
| \|price − open\| / ADR | ≥ 0.34 |
| ER | ≥ 0.09 |
| one-sidedness (share of minutes on one side of the running average close) | ≥ 0.62 |
| crosses of the day open | ≤ 2 |

Thresholds for the other checkpoints are in `day_type/rules.json`.
- **At 12:00 (2023–26):** score 0–1 → 76–84 % of days were choppy; score 4 → 60 % were trend days (base rate 28 %).
- **Useless (≈ coin flip):** NR7, inside day, previous day's range or efficiency, gap size.

**Day-type labels** use the full day, so they're for evaluation only, never as a live filter:
- **Gap day:** |gap| ≥ 0.8 %.
- **Trending up / down:** |close−open|/range ≥ 0.6 and range/median-range ≥ 0.8.
- **Sideways:** |body|/range ≤ 0.25 and relative range ≤ 0.9.
- **Reversal:** |body|/range ≤ 0.35 and extension ≥ 0.45.
- **Mixed / choppy:** otherwise.

---

## 5. Exit framework (applies to every positional option strategy)

### 5.1 Base exit — "ST exit"
- **Short:** the premium's 15-min ST turns **up**.
- **Long:** it turns **down**.

In both cases, act at the next 1-min open after that 15-min bar closes.

### 5.2 Alternative exits
EMA20, chandelier, PSAR, 5-min CHoCH back, RSI target, and premium targets:
- **Sell:** a 50 % decay target.
- **Buy:** a 2× or 3× target.

Targets keep the ST exit as the stop.

### 5.3 Always
Force the exit at 15:15 on expiry day.

### 5.4 LOCK rule — the key improvement (user's rule)
**SELL (short premium):**
- Once the premium has traded at or below `entry − 50` (before the normal exit fires):
  - stop = **entry price**;
  - **ignore the normal exit**.
- Exit only on the first of:
  - (a) high ≥ entry → buy back at `max(open, entry)`;
  - (b) low ≤ **₹50** → buy back at `min(open, 50)` (apply only if 50 < entry − 50);
  - (c) 15:15 on expiry day.
- Check from the minute **after** the trigger minute.

**BUY (long premium), mirror:**
- Once high ≥ `entry + 50`: stop = entry and the normal exit is ignored.
- Exit on low ≤ entry → `min(open, entry)`, or at 15:15 on expiry day.
- Variant: also take profit at 2× entry (`max(open, 2·entry)`).

Make the trigger (50 pts) and the target (₹50 / 2×) parameters. Also tested: lock at +25 pts and lock at 2× entry
(for cheap buys).

### 5.5 Hedge overlay (for shorts)
- **Strike:** the same expiry and right, **OTM**, whose 09:19 premium is closest to ₹5 / ₹10 / ₹20 (typically
  600 / 450 / 300 pts from a ₹100+ short).
- **Timing:** buy it at the short's entry minute open and sell it at the short's exit minute open.
- **Costs:** charges on both legs.
- **MTM:** report the worst open loss on a per-minute close basis, for the naked and hedged versions.
- **Finding:** it costs 40–65 % of the ₹100+ short's profit (≈ ₹62 charges + ₹80–160 decay per trade on a ₹340–480
  average trade) and barely changed the 2018–26 worst losses. Its value is lower margin and tail protection.
- **Suggested next build (not yet tested):** hold one hedge per expiry per leg instead of one per trade.

---

## 6. Strategies to implement (with results to reproduce)

All results: 1 lot (75) per leg, CE and PE legs both traded, 2018-01 → 2026-10-19, ₹0.10 slippage per side unless
noted. "DD" = maximum drawdown of the cumulative realised P&L, by exit time.

### 6.1 Positional SELL on the option's own chart — base (no confirmation)
- **Contract:** the day's ATM CE/PE (front expiry incl. expiry day, strike fixed at 09:20).
- **Signal:** the premium's ST(p,m) on 15-min or 60-min bars **turns down** (bar close, 09:20–15:00, watched day)
  → **sell** at the next 1-min open.
- **Exit:** the same contract's ST turns up, or 15:15 on expiry day.

| Setting | Trades | Net | Max DD | Years + |
|---|---|---|---|---|
| **60-min ST(4,3)** | 584 | **+₹7.43 L** | −₹0.60 L | 9/9 |
| 60-min ST(7,2) | 768 | +₹6.77 L | −₹0.82 L | 9/9 |
| 60-min ST(10,3) | 604 | +₹4.38 L | −₹0.64 L | 8/9 |
| 15-min ST(4,3) | 1,434 | +₹6.56 L | −₹0.67 L | 9/9 |
| Baseline: short ATM straddle held to expiry, no indicator | 824 | +₹2.88 L | −₹2.33 L | 6/9 |
| Baseline: short ATM straddle 09:20–15:15 daily | 4,220 | +₹0.14 L | −₹1.55 L | 3/9 |

Margin: naked, both legs open together in about half of the CE trades, so roughly ₹2.5–3 L per lot-pair.

### 6.2 Daily-ST filter + premium scan (100–500)
- Pick from the next expiry (§3.2): ATM / p100 / p300 / p500.
- Daily ST filter (§4.4): only one leg is ever open, so margin is about half.
- Results for 60-min ST(7,2) on the premium:

| Pick | No filter | Daily ST(10,3) | Daily ST(7,2) |
|---|---|---|---|
| ATM | +₹6.56 L / DD −0.92 | +₹3.39 L / −0.55 | +₹3.41 L / −0.46 |
| p100 | +₹6.37 L / −0.60 | +₹2.91 L / −0.42 | +₹2.80 L / −0.36 (9/9) |
| p300 | +₹5.65 L / −1.22 | +₹3.54 L / −1.64 | +₹4.22 L / −1.36 |
| p500 | +₹6.15 L / −2.01 | +₹3.14 L | +₹5.31 L / −1.33 |

- The daily filter roughly halves both profit and margin and lowers the DD.
- Headline p300 · 15m ST(4,3) · no filter: **+₹11.58 L** (DD −₹1.61 L), but its data is illiquid.

### 6.3 SELL with CHoCH/BOS confirmation + alternative exits (premium chart)
- **Trend:** 15-min ST on the premium is down (last closed bar).
- **Entry:**
  - `none` = on the ST down-flip;
  - `1m` = any bearish 1-min (N=5) BOS/CHoCH while ST is down;
  - `5m` = any bearish 5-min (N=3) event while ST is down.
  
  The confirmed modes allow **re-entry** after an exit while ST is still down.
- **Exits:** §5.1–5.2.
- **p100, 15-min ST(4,3):**

| Exit \ entry | ST flip | + 1m BOS/CHoCH | + 5m BOS/CHoCH |
|---|---|---|---|
| ST turns up | +₹7.46 L (−0.67) | **+₹7.84 L (−0.60)** | +₹7.77 L (−0.76) |
| Chandelier | +₹5.77 L | +₹7.24 L | +₹7.58 L (−0.73) |
| Close > EMA20 | +₹3.39 L | +₹5.78 L | **+₹6.70 L (−0.39)** ← best return/DD |
| 5m CHoCH up | +₹2.44 L | +₹6.26 L | +₹6.03 L |
| 50 % decay target | +₹3.91 L | +₹6.50 L (−0.50) | +₹4.90 L |
| PSAR | +₹3.37 L | +₹3.58 L | +₹4.61 L |
| RSI < 30 | +₹3.81 L | −₹1.64 L | +₹1.85 L |

### 6.4 SELL ₹500+ (deep ITM) and the LOCK rule
- p500up / p750 with the §6.3 machinery.
- **Best before lock:** p500up · ST(10,3) flip → ST up: **+₹14.29 L**, DD −₹1.53 L, 9/9 years.
  - With ₹2 slippage per side: +₹10.59 L.
- **With the §5.4 lock:** better in **59/60** combinations, DD lower in 57/60.

| Setup | Before | With lock | Max DD |
|---|---|---|---|
| p750 · ST(10,3) + 5m confirm → ST up | +₹12.46 L | **+₹19.00 L** | −1.40 → −0.99 L |
| p500up · ST(10,3) flip → ST up | +₹14.29 L | +₹16.98 L | −1.53 → −1.03 L |
| p500up · ST(4,3) + 5m confirm → ST up | +₹11.81 L | +₹15.18 L | −1.64 → −1.16 L |

- **Exit mix** (p750 book):
  - 515 ST-up exits: −₹33.7 L;
  - 526 locked → back to entry: −₹3.2 L;
  - 198 locked → expiry: **+₹40.1 L**;
  - 37 locked → ₹50 target: +₹15.8 L.
- **Caveat:** 33–71 % flat candles, so stale prices can understate touches of the breakeven stop. It's
  effectively a directional (delta ≈ 0.9) futures-like trade.

### 6.5 BUY mirror on the premium chart (+ lock)
- **Trend:** 15-min ST on the premium is up.
- **Entry:** on the flip, or with bullish 1m/5m BOS/CHoCH confirmation.
- **Exits:** ST turns down / chandelier / EMA20 / 2× target.
- **Lock:** §5.4 BUY.

| Pick · setup | Normal | Lock → expiry | Lock + 2× | Notes |
|---|---|---|---|---|
| **p100 · ST(4,3) + 5m → ST down** | +₹5.78 L (−1.15) | **+₹9.47 L (−1.06)** | +₹7.64 L | win 15 %; 184 lock-expiry trades +₹34.6 L |
| p500up · ST(4,3) + 5m → ST down | +₹7.00 L (−2.50) | +₹14.20 L (−1.45) | +₹14.90 L (−1.42) | illiquid |
| p750 · ST(10,3) + 5m → ST down | +₹7.72 L | +₹13.97 L | +₹14.65 L (−1.40) | illiquid |

### 6.6 ★ RECOMMENDED — ₹100+ SELL + BUY portfolio (separate lots)
There are four independent books, 1 lot each. **Same rules in every book:**
- strike: p100 from the next expiry, picked at 09:20;
- trend: 15-min ST(4,3) on the option's own premium;
- confirmation: 5-min (N=3) BOS/CHoCH;
- base exit: the ST flip;
- the +50 lock.

**The four books:**

| Book | Entry | Lock | Exit |
|---|---|---|---|
| SELL-CE, SELL-PE | premium ST down + bearish 5-min event | +50 → SL entry | until expiry or premium ₹50 |
| BUY-CE, BUY-PE | premium ST up + bullish 5-min event | +50 → SL entry | until expiry |

**Combined result:** **+₹17.40 L**, max DD **−₹1.04 L**, 8/9 years positive, 69 % of months positive.
- Monthly correlation sell vs buy = **0.12**, so the two sides offset each other.

Yearly (₹ thousand):

| | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|---|
| SELL | −25 | 93 | 116 | 168 | 99 | 147 | 23 | 159 | 11 |
| BUY | 87 | 15 | 204 | 94 | 75 | 168 | 199 | 123 | −17 |
| **Total** | 62 | 108 | 320 | 262 | 174 | 315 | 223 | 282 | −6 |

\*2026 to 19-Oct. Cumulative by year end (₹ L): 0.62, 1.70, 4.90, 7.52, 9.26, 12.41, 14.64, 17.46, 17.40.

Alternative: the **₹500+ SELL + BUY** portfolio with the same rules on p500up made +₹29.37 L, DD −₹1.97 L, 9/9 years.
- Correlation is 0.61: it's the same directional bet twice.
- The strikes are illiquid.

**Why 2018–19 were weak:**
- NIFTY's daily range was 106–123 pts then, against 190–240 later, so the +50 lock fired far less often.
- 2018 had monthly expiries only.
- ₹500+ strikes existed on only 131 / 58 days.
- **Suggested improvement:** make the lock trigger a % of the entry premium (e.g. 40 %) rather than fixed points.

### 6.7 Cheap OTM buys (< ₹30 / < ₹50) — research only, not recommended
- **< ₹30 (u30) with §6.6 rules:**
  - +₹1.98 L, DD −₹1.50 L;
  - negative every year 2024–26;
  - +₹1.29 L at ₹0.50 slippage.
- **~₹15 (u15):** about −₹0.10 L.
- **Grid of 1,620 combinations on u50 / p40 / u30** (3 ST × 3 entries × 5 exits × 4 locks × 3 filters):
  - 92 % profitable in 2018–22, only **25 % in 2023–26**;
  - the top 15 chosen on 2018–22 **all lost** in 2023–26.
- **The one family that held in both periods:** *index chop filter + 1-min confirm + EMA20 exit, no lock*:
  - u50 · ST(4,3): +₹2.77 L (DD −₹46k);
  - u30 · ST(4,3): +₹2.25 L (DD −₹28k).
  
  It was found after looking at 2023–26, so it's unproven; paper-trade it before using it.

---

## 7. Earlier intraday studies (for reference; all fail as stand-alone)
- **Index futures:** 15-min ST(10,3) direction + 1-min BOS (N=5), stop at the opposite 1-min swing, min risk
  10 pts, +1R → breakeven then trail to new swings; entries 09:30–14:45, flat at 15:15.
  - 4,276 trades, +1.08 pts per trade before costs, **−₹13.26 L** net, 0/9 years.
  - ST (7,2) / (4,3) don't help.
  - Taking every swing break (BOS+CHoCH) is worse: −₹25.4 L.
- **Same + chop filter (§4.6):** +₹0.90 L (581 trades, +7.5 pts/trade), 6/9 years.
  - Longs +₹0.63 L; shorts +₹0.27 L.
  - Fragile: without 2024 it's −₹46k.
- **Intraday on the option premium chart** (ATM CE/PE, 15-min premium ST + 1-min BOS, buy on bullish / sell on
  bearish):
  - buys lose without the filter;
  - sells are thinly positive (mostly expiry-day decay);
  - with the index chop filter both are positive: best ST(4,3) pivot-5 BOS swing **+₹1.92 L**, 2023–26 +₹0.84 L.

---

## 8. Suggested code structure

```
nifty_bt/
  data.py        # load index 1m (with the 2026-08-03 fix), list expiry folders, read option files per expiry (regular+wide+zip)
  chain.py       # 09:19 chain snapshot per (date, trade-expiry); pick functions (§3.2); front/next expiry logic (§3.1)
  bars.py        # resample 1m -> L-min bars with close_time; HTF mapping without look-ahead
  indicators.py  # supertrend, wilder_atr, ema, chandelier, psar, rsi, pivots/structure (§4.1–4.3)
  filters.py     # daily ST direction, ADR, chop filter, day-type score (§4.4–4.7)
  costs.py       # option & futures charges (§2.4, §2.8)
  engine.py      # candidate generation per contract -> outcome per exit spec; lock/hedge overlays; sequencing per leg
  report.py      # stats, yearly, train/test split, slippage sensitivity, flat-candle share, charts
  configs/       # YAML per strategy (pick, ST params, TF, entry mode, exit, lock, filter, hedge, lot)
  tests/         # validation checklist (§9)
```

**Implementation notes:**
- Generate candidates **per expiry file**, then free memory: the whole option tree is 1.3 GB. Write candidate
  chunks to parquet with categorical columns. Earlier versions ran out of memory with 8 GB.
- Evaluate exits with `searchsorted` on bar-close-time arrays and `flatnonzero` on 1-min high/low slices; no
  per-minute Python loops needed.
- Run long jobs as tracked processes, not detached `&`.

---

## 9. Validation checklist (the agent must pass all of these)
1. **Look-ahead:**
   - a 1-min bar at 10:03 sees the 09:55 5-min bar but not the 10:00 one;
   - the 15-min ST at 10:14 equals the 09:45 bar's value;
   - truncation test: recompute any indicator using only data up to time t and confirm it matches the full-series
     value at t.
2. **Strike selection** uses only 09:19 data, and the expiry is never the trade day (for the positional scan).
3. **Trade checks against raw candles:** for 3 random trades per strategy, check entry = next 1-min open, stop/target
   fills per §2.3, charges recomputed, net = (pts × lot) − charges.
4. **Locked trades:**
   - the trigger minute is the first touch of entry ± 50;
   - after it, no normal exit is applied;
   - the exit is the first of stop / target / expiry.
5. **Sequencing:** no overlapping trades within a leg.
6. **Reproduce §6 results within ±5 %:**
   - §6.1: 60-min ST(4,3) +₹7.43 L;
   - §6.3: p100 1m/ST-up +₹7.84 L;
   - §6.6: SELL +₹7.92 L, BUY +₹9.47 L, combined +₹17.40 L.
7. Report the 2018–22 vs 2023–26 split and ₹1 / ₹2 slippage results for every headline number.
8. For strikes with a > 10 % flat-candle share, print a warning in the report.

---

## 10. Before any live use (hard requirements)
- **Paper-trade first:** a forward test of at least 2–3 months on the §6.6 rules exactly as specified, no changes.
- **Risk limits in code:**
  - maximum lots per leg;
  - maximum daily loss;
  - maximum open MTM loss;
  - kill switch;
  - no new entries after 15:00;
  - forced exit on expiry day at 15:15.
- **Naked shorts:** require explicit opt-in. Default to the §5.5 hedge to cap gap risk and margin.
- **Orders:** use limit orders, handle partial fills and rejections, and reconcile positions with the broker every
  minute.
- **Regulation:** follow SEBI's retail algo framework and the broker's rules (approved / registered algos, order
  tagging).
- **Never send real orders from the backtest code path.**

---

## 11. Open items / next experiments
1. One hedge per expiry per leg instead of per trade (§5.5).
2. Lock trigger as a % of premium (30 / 40 / 50 %) instead of 50 points; also lock trigger 30 / 70 pts (robustness).
3. Run the same rules on **NIFTY futures, positional** (15-min ST + 5-min confirm + lock in index points): the clean,
   liquid version of the deep-ITM edge.
4. Realistic lot sizes by date, and margin-based return on capital.
5. Bid/ask-aware fills, where quote data is available.

---

## Appendix — where the original research code and outputs are
(Container paths from the research session; re-implement rather than copy.)
- Futures / intraday: `bt/mtf_bt.py`, `bt/mtf_st.py`, `bt/st_params.py`, `bt/chop_*.py`, `bt/daytype_*.py`.
- Option scans: `bt/scan_build.py` (09:19 chain), `bt/scan_pick*.py` (picks 1–4), `bt/build_opt_1m.py` (ATM 1-min).
- Option strategies:
  - `bt/possell.py` (§6.1), `bt/scan_sim2.py` (§6.2);
  - `bt/conf_sim*.py` + `conf_seq*.py` (§6.3–6.4);
  - `bt/lock50.py`, `bt/lock_p100_sell.py` (§5.4);
  - `bt/buy_sim*.py`, `bt/buy_grid*.py` (§6.5, §6.7);
  - `bt/hedge.py` (§5.5), `bt/combo.py` (§6.6).
- Output folders delivered to the user:
  - `positional_sell_supertrend/` (+ `daily_scan/`, `confirm_exits/`, `premium_500plus/`, `hedged/`, `lock50/`);
  - `positional_buy_supertrend/`, `sell_plus_buy/` (+ `cheap_buy/`), `buy_under50/`;
  - `mtf_choch_bos/` (+ `examples/`, `choppy_filter/`, `options_standalone/`, `day_type/`).


---

## 12. v2 additions (built after the first spec)

### 12.1 Engine pattern used for every study (copy it)
1. For each expiry file: load the picked contracts → build premium bars (1/3/5/15/60-min, §3.3) → indicators/structure.
2. Emit **candidates**: every signal on a watched day, with its fully-simulated outcome for every exit/lock variant.
   (A trade's outcome does not depend on other trades.) Write candidates per expiry as parquet with categorical columns.
3. **Sequence** per book and leg (§3.4). For intraday caps, also count trades per leg per day.
4. Filters that depend only on entry-time information (chop filter, daily ST) are applied to candidates **before** sequencing.

### 12.2 ★ Supertrend-swing CHoCH/BOS (current best)
Run on each option's own premium chart (picks §3.2, next expiry).
- **Supertrend segments:** consecutive bars with the same ST direction.
  - **Swing high** = highest high of a completed UP segment, **confirmed at the close of the flip-down bar**.
  - **Swing low** = lowest low of a completed DOWN segment, confirmed at the flip-up bar close.
  - The running segment extreme starts from the flip bar's own high/low.
- **Structure:**
  - On each bar close, if `close > last confirmed swing high` (and it hasn't been crossed since confirmation) → bullish
    event; it's a **CHoCH** if the structure trend was bearish or none, a **BOS** if it was bullish. Set trend = +1.
  - Mirror for bearish events.
  - A new confirmed swing resets its "crossed" flag.
- **Trade:**
  - bullish → **BUY** the option, **SL = last confirmed swing low**;
  - bearish → **SELL** the option, **SL = last confirmed swing high**.
  - Skip the trade if SL is not at least 2 points on the losing side.
- **Trail:** each newly confirmed swing in the trade's favour moves the SL. Swing lows ratchet a long's SL up, swing highs
  ratchet a short's SL down; never loosen it.
- **Optional lock50:** once the trade is 50 points in favour, the SL floor is the entry price.
- **Fills and window:**
  - SL fills at the worse of open / SL;
  - entries 09:20–15:00 on watched days;
  - **positional** = until SL or 15:15 on expiry day;
  - **intraday** = until SL or 15:15 the same day, entries until 14:30.
- **Results** (1 lot/leg, 2018-01 → 2026-10; 218/256 combinations positive in both 2018–22 and 2023–26):

| Book | Trades | Net | ₹1 slip | Max DD | 2023–26 | Years + |
|---|---|---|---|---|---|---|
| ₹100+ positional SELL · 5m ST(4,3) · CHoCH+BOS · trail+lock50 (G1) | 1,153 | +₹8.94 L | +₹7.39 L | −₹0.52 L | +₹5.31 L | 9/9 |
| ₹100+ positional BUY · 15m ST(4,3) · CHoCH · trail+lock50 (G2) | 410 | +₹5.88 L | +₹5.33 L | −₹0.71 L | +₹2.55 L | 8/9 |
| **₹100+ positional SELL + BUY** | 1,563 | **+₹14.83 L** | +₹12.72 L | **−₹0.64 L** | +₹7.86 L | **9/9** |
| ₹500+ positional SELL + BUY (illiquid) | 2,266 | +₹41.36 L | +₹38.30 L | −₹2.11 L | +₹23.28 L | 9/9 |
| ₹100+ intraday SELL + BUY | 2,703 | +₹4.26 L | +₹0.61 L | −₹1.49 L | +₹2.10 L | 8/9 |

  Yearly, ₹100+ SELL + BUY (₹ thousand), 2018 → 2026: +107, +107, +250, +165, +69, +216, +175, +299, +96.

**Looks better in the data, avoid in practice:** the chop filter for positional; lock50 on ₹500+; intraday ₹100+ SELL
(negative at ₹1 slip).

### 12.3 Variant: swings from the 1-min Supertrend, signals on 5-min closes
- Swings from 1-min ST segments; events only on 5-min bar closes, using swings confirmed by that close.
- **Results:**
  - ₹100+ SELL + BUY, ST(4,3): **+₹17.89 L gross but only +₹4.85 L at ₹1 slip**;
  - ST(10,4): +₹14.62 L gross / +₹6.40 L at ₹1 slip.
- It trades 700–1,100 times a year: too cost-sensitive. Keep it as an option only for SELL with 1-min ST(10,4).

### 12.4 Variant: normal pivot CHoCH → Supertrend confirmation
- **Structure:** pivots on 5-min (N=3) or 15-min (N=2), as in §4.2.
- **Waiting for confirmation:** after a CHoCH/BOS at bar i, wait for the same-TF Supertrend to agree, up to 200 bars;
  enter at that bar's close (next 1-min open).
- **Discard the pending setup if, before confirmation:**
  - an opposite BOS/CHoCH prints, or
  - a close crosses the setup's stop.
- **Stop:** the swing level current at confirmation; trail to newly confirmed pivots.
- **Results:**
  - ₹100+ SELL + BUY, 15-min (SELL ST(10,3), BUY ST(4,3), CHoCH+BOS): +₹15.18 L / +₹9.10 L at ₹1 slip, DD −₹1.06 L;
  - without the ST confirmation: +₹15.30 L / +₹7.96 L at ₹1 slip;
  - confirmation removes about 15 % of trades, almost all of them losers.
- ₹500+ SELL · 15m → ST(10,3) · CHoCH+BOS: +₹20.66 L, DD −₹0.99 L, 9/9 years.
- **Not yet tested — close-based exits:** exit only on a candle **close** through the swing (a real opposite BOS/CHoCH)
  instead of an intrabar touch. Implement it as a stop-mode flag `touch | close`.

### 12.5 Intraday — 5-min confirmation + chop filter (best intraday family)
- **Grid:** 1,296 combinations of
  - pick: ₹100+ / ₹500+;
  - side: sell / buy;
  - premium ST: 5-min or 15-min, (4,3) or (10,3);
  - entry: on the flip, or 1m / 5m confirmation;
  - exit: ST / chandelier / EMA20;
  - lock: none / +20 / +40;
  - filter: none / chop / daily.
- **What holds up:** 5-min confirmation and the chop filter make money in both periods in 69 % of combinations
  (128/144 together); 1-min confirmation, entry on the flip, and the daily filter do not.
- **Portfolio** (each leg chosen on 2018–22): ₹100+ SELL / ₹100+ BUY / ₹500+ SELL / ₹500+ BUY = **+₹8.57 L**,
  2023–26 +₹3.00 L, DD −₹1.58 L, about 210 trades a year.
- **Weak years:** 2023 and 2025, when the index range was ≤ 0.87 % of spot and win/loss ratios collapsed.

### 12.6 Intraday — dual Supertrend
- **Roles:** slow ST(10,4) or (14,4) sets direction; fast ST(5,2) or (7,2) times entries.
- **Entries:** `agree` = first bar where both agree; `pullback` = fast flips back to the slow ST's direction.
- **Exits:** fast flip, slow flip, or slow + lock20/40.
- **Cap:** 1 / 2 / unlimited trades per leg per day.
- **Charts:** 1-min (fails: whipsaw), 3-min and 5-min (both work).
- **Best:**
  - SELL 3m (10,4)/(5,2) agree → slow exit, ≤ 2/day: +₹3.30 L, DD −₹0.45 L;
  - BUY 5m agree → fast exit, ≤ 2/day: +₹4.12 L.
- Very cost-sensitive at about 4 trades a day: the portfolio's +₹7.42 L becomes +₹2.55 L at ₹0.50 slip.

### 12.7 Lot scaling and compounding (₹500+ positional SELL + BUY)
- **Charges:** brokerage + GST (₹47.2) is per order; everything else scales with lots.
- **Capital per lot-per-leg:**
  - peak concurrent short lots × ₹2 L margin (assumed; read the real value from the broker);
  - plus peak long-premium outlay;
  - plus 1.5 × max drawdown.
  - Result: about ₹9.2 L at ₹1 slip.
- **Return:** roughly 32–34 % a year on that capital at 1–10 lots (₹1 slip). The liquidity cap on deep-ITM strikes is
  about 4–5 lots.
- **Compounding rules** (lots decided at entry using realised equity only), starting from ₹9.19 L:

| Rule | Final | CAGR | Max DD |
|---|---|---|---|
| fixed 1 lot | ₹35.0 L | 16.4 % | −₹2.2 L |
| double when capital allows 2×, never reduce | ₹62.5 L | 24.3 % | −₹12.9 L |
| **double when allowed, halve if equity < required** (recommended) | **₹66.9 L** | 25.3 % | −₹8.1 L |
| add 1 lot whenever affordable | ₹82.9 L | 28.4 % | −₹15.6 L |

  Implement as a `SizingPolicy` interface, with a cap of 10 lots.

### 12.8 Late entry ("buy only after +X")
- **Rule:** a buy-stop at signal price + X (50 / 100 / 150), valid until the ST exit.
- **Result:** it does **not** isolate rallies.
  - ₹100+: entering after +100 makes +₹2.8–3.1 L against +₹9.47 L entering at the signal.
  - Exception: ₹500+ with +50 and a 50-point stop made +₹16.0 L against +₹14.2 L.
- Of signals that reach +100, 45 % go on to +200.

### 12.9 Rally EDA (₹100+ buy signals, 4,934 signals)
- **Rally size:**
  - median rally (MFE before the ST exit) is 46 points;
  - 29 % of signals reach +100, 13 % +200, 7 % +300.
- **Predictors** (AUC about 0.58–0.63): the option's day range so far, premium change today, premium level, and the
  index move in the trade's direction ÷ ADR.
- **But the top predictor quintile had the worst 2023–26 P&L.** Don't filter on "rally-ness".
- **Mild, consistent filters:** skip premium < ₹115; skip index ER < 0.04.

### 12.10 Hedge-per-trade cost breakdown (why it took 40–75 % of profit)
- **The ₹100+ short's average edge:** ₹340–480 per trade.
- **A ₹20 hedge costs about ₹221 per trade:** ₹63 in charges plus ₹158 in decay.
- **It pays off rarely:** in only 11–39 % of trades.
- **Build next:** one hedge per expiry per leg (§11.1).

### 12.11 Things that were tested and **don't work** (so you don't re-test them)
- Any 1-min Supertrend for signals (whipsaw).
- RSI-target and PSAR exits.
- Cheap OTM buys (< ₹30 / ₹50) as a standalone strategy.
- Waiting for +100 before buying ₹100+ options.
- The daily-ST filter for intraday.
- The chop filter for positional.
- Taking every swing break (BOS + CHoCH without ST context) on index futures intraday.
