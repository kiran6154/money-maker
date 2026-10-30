"""Report prose for build_page.py (numbers copied from results/summary.json, 2026-09-30 run)."""

html_top = """
<header class="lede">
  <span class="eyebrow">NIFTY weekly options · 2024 → 2026-09 · pre-registered</span>
  <h1>Option Wave Lifecycle Test</h1>
  <p>The claim: large intraday option moves climb in steps. Compression, expansion, a higher base, another expansion, and the steps follow a law such as exponential growth. The study defined every step as code that sees only past bars, froze the design and the code before opening 2025 and 2026, and then tried to break the claim.</p>
</header>

<div class="verdict">
  <div class="num">4</div>
  <div>
    <div class="choice">Inconclusive under the pre-registered rule, and every precise measurement points to no structure</div>
    <p>The pattern appears exactly as often in bars shuffled within each session as in the real ones. It is not followed by a third wave more often than chance. Its one development-period edge (+10.7 % over matched bars at 30 minutes) fell to +2.4 % in 2025 and −10.5 % in 2026. The rule written before the run calls this "inconclusive" because the 2025–26 intervals are wider than the round-trip cost. The strongest statement the data supports: no trading edge was found, and the wave shape is what random ordering of the same bars produces.</p>
  </div>
  <div class="scale">
    <div>1 · strong, reproducible</div><div>2 · structure, not tradable</div><div>3 · no predictive structure</div><div class="on">4 · inconclusive</div>
  </div>
</div>

<section id="definition">
  <h2><span class="tag">A</span> The mechanical definition</h2>
  <p>Everything runs on the log premium of one contract. ATR is the mean log true range of the previous 20 bars. State resets at each session open.</p>
  <div class="tbl"><table><thead><tr><th>Term</th><th>Rule (primary cell)</th></tr></thead><tbody>
  <tr><td class="l">Compression</td><td class="l">range of the last L = 12 bars ÷ (ATR before the box × √12) ≤ 0.75. A random walk gives ≈ 1 (measured median 0.91).</td></tr>
  <tr><td class="l">Base 0</td><td class="l">the latest compressed box; armed for 12 bars</td></tr>
  <tr><td class="l">Expansion n / breakout</td><td class="l">a close above the box top (n = 1) or above the previous peak R<sub>n−1</sub></td></tr>
  <tr><td class="l">Acceptance</td><td class="l">2 consecutive closes above the breakout level. Otherwise the expansion failed. Signal time = the second close.</td></tr>
  <tr><td class="l">Resistance R<sub>n</sub></td><td class="l">zig-zag peak confirmed by a later bar's low 2 ATR below it (a bar that sets a new high cannot confirm, because OHLC hides intrabar order)</td></tr>
  <tr><td class="l">Higher base</td><td class="l">every close in the pullback stays above the old resistance R<sub>n−1</sub>; a close below it ends the lifecycle</td></tr>
  <tr><td class="l">Resistance retest · higher low</td><td class="l">counted as features: highs within 0.5 ATR of R<sub>n</sub> without a close above; zig-zag swing lows above the previous one</td></tr>
  <tr><td class="l">Complete lifecycle</td><td class="l">three accepted expansions in one session. The test signal <b>I</b> is the accepted second expansion: compression → E1 → higher base → E2. This is the moment the pattern first becomes visible.</td></tr>
  </tbody></table></div>
  <p class="note">Strikes are fixed at 09:20 from the index on the 100-pt grid (ATM, ±100, ±200); front weekly expiry; entry at the signal bar's close. The grid of 360 neighbouring cells (L 8–16, ratio 0.6–0.9, zig-zag 1.5–3 ATR, 1–3 acceptance closes, strict or loose support) is reported in full. Nothing was chosen by result. Sessions before each week's Monday 09:20 are excluded because the files' strike list was picked then.</p>
</section>
"""

predict_intro = """<p>For each signal family, the 30-minute return after the signal is compared with bars that share its side, strike, expiry role, DTE bucket, hour and trailing-return decile. 2024 was used to debug and is in-sample; 2025 and 2026 ran once on frozen code.</p>"""

predict_after = """
<ul class="plain">
  <li><b>The shuffle test sets the bar to beat.</b> Wave-2 signals found in bars shuffled within each session also show a positive "excess": +2.3 % (2024), +0.0 % (2025), +2.5 % (2026). Selecting a run-up biases the matched baseline. The 2025 real value, +2.4 %, sits on top of that.</li>
  <li><b>The grid does not rescue it.</b> In 2026 the primary cell's L-neighbours (8, 10, 12, 14, 16 bars) give −5.9, −10.5, −10.5, −18.8, −18.3 %. In 2024 they were +7 to +11 %. A sign flip between periods across the whole neighbourhood marks an in-sample artefact.</li>
  <li><b>Other timeframes disagree in sign.</b> Wave-2 excess, 2025 / 2026: 1-minute −1.4 / +5.8 %, 3-minute +3.0 / +11.9 %, 5-minute +2.4 / −10.5 %. At 10 and 15 minutes a 12-bar compression plus two waves rarely fits in a session (≤ 9 events).</li>
  <li><b>Part 14 probabilities are no better than a random bar.</b> P(another accepted expansion | wave 2): 4 % / 0 % / 11 % (ATM, n = 26 / 8 / 9). P(session MFE ≥ +20 %): wave-2 31 % / 50 % / 56 % against 55 % / 53 % / 64 % for every eligible bar.</li>
  <li><b>Costs (Part 15)</b>, ATM, 1 lot, exit after 30 minutes, 0.5 % slippage each side, ₹20 per order plus statutory charges: +₹118 per trade in 2024, −₹83 in 2025, −₹1,145 in 2026. Entering at the next bar's open changes each by under ₹40.</li>
  <li>Two nominally significant cells turned up: H (loose support, no acceptance) in 2025 5-minute, and wave-3 events on 1-minute in both years (ATM n = 19 / 13). Neither holds on another timeframe or in both periods, and they came from a family of several hundred comparisons. They are leads, not findings.</li>
</ul>
"""

math = """
<section id="math">
  <h2><span class="tag">B</span> Which law do the wave peaks follow?</h2>
  <p>Too few lifecycles reach four confirmed levels to fit two-parameter curves on their own (2, 1 and 0 per period), so in-sample R² is not reported as evidence. The test that has data: at the accepted second expansion, each law extrapolates the next peak from the known levels (P0 = box top, R1), and that forecast is scored against where the peak actually formed.</p>
  <div class="tbl"><table><thead><tr><th>Next-peak forecast, mean |log error|</th><th>2024</th><th>2025</th><th>2026</th></tr></thead><tbody>
  <tr><td class="l">Linear (equal point steps)</td><td>0.180</td><td>0.192</td><td>0.238</td></tr>
  <tr><td class="l">Logarithmic</td><td>0.178</td><td>0.200</td><td>0.186</td></tr>
  <tr><td class="l">Power law</td><td>0.173</td><td>0.195</td><td>0.356</td></tr>
  <tr><td class="l neg">Geometric / exponential (equal % steps)</td><td class="neg">0.250</td><td class="neg">0.223</td><td class="neg">0.580</td></tr>
  <tr><td class="l">No further gain (peak = R1)</td><td>0.309</td><td>0.289</td><td>0.291</td></tr>
  <tr><td class="l">R1 × the 2024 median step (one constant, fixed in 2024)</td><td class="dim">–</td><td>0.192</td><td>0.143</td></tr>
  <tr><td class="l dim">n lifecycles</td><td class="dim">113</td><td class="dim">64</td><td class="dim">36</td></tr>
  </tbody></table></div>
  <ul class="plain">
    <li><b>Exponential is rejected.</b> Equal percentage steps give the worst forecast in every period and overshoot by +5 to +42 % (log bias +0.12 / +0.05 / +0.42).</li>
    <li>Successive percentage steps shrink: median g2/g1 = 0.51 / 0.85 / 0.63 (all front contracts). Shuffled bars give 0.63 / 0.58 / 0.66. Deceleration is what the detector's own selection produces, so it is not a property of NIFTY options.</li>
    <li>The simplest rule, "the next step is the typical step", ties or beats every fitted law out of sample. <b>Answer: none of the laws describes the progression better than a constant.</b></li>
  </ul>
</section>
"""

wave = """
<section id="wave">
  <h2><span class="tag">C</span> Wave amplitude</h2>
  <div class="tbl"><table><thead><tr><th>Median, front contracts</th><th>2024 real</th><th>shuffled</th><th>2025 real</th><th>shuffled</th><th>2026 real</th><th>shuffled</th></tr></thead><tbody>
  <tr><td class="l">Expansion 2 ÷ expansion 1 (log)</td><td>0.86</td><td>0.84</td><td>0.95</td><td>0.80</td><td>0.87</td><td>0.85</td></tr>
  <tr><td class="l">Retracement ÷ expansion 1</td><td>0.51</td><td>0.46</td><td>0.51</td><td>0.46</td><td>0.46</td><td>0.46</td></tr>
  <tr><td class="l">Δ2 ÷ Δ1 (points)</td><td>0.75</td><td>0.87</td><td>1.05</td><td>0.77</td><td>0.88</td><td>0.91</td></tr>
  <tr><td class="l">P(wave 3 | wave 2)</td><td>6 %</td><td>10 %</td><td>2 %</td><td>10 %</td><td>8 %</td><td>8 %</td></tr>
  <tr><td class="l">Lifecycles reaching wave 1</td><td>1,007</td><td>1,032</td><td>673</td><td>663</td><td>342</td><td>320</td></tr>
  </tbody></table></div>
  <p>Retracements take about half of the prior expansion and the next expansion is about 0.85–0.95 of the last. Shuffled bars do the same. The number of lifecycles is the same with and without the real bar order, in all three years. Whatever makes a chart look like a staircase is present in random orderings of the same bars.</p>
</section>
"""

cepe = """
<section id="cepe">
  <h2><span class="tag">E · 8 · 10</span> CE vs PE, strikes, and what moves the premium</h2>
  <div class="tbl"><table><thead><tr><th>Share of the expansion gain</th><th>2024</th><th>2025</th><th>2026</th></tr></thead><tbody>
  <tr><td class="l">NIFTY move × delta</td><td>85 %</td><td>86 %</td><td>84 %</td></tr>
  <tr><td class="l">Convexity (gamma / moneyness)</td><td>15 %</td><td>13 %</td><td>18 %</td></tr>
  <tr><td class="l">Theta</td><td>−3.5 %</td><td>−3.0 %</td><td>−5.1 %</td></tr>
  <tr><td class="l">IV change (includes smile / model error)</td><td>+3.0 %</td><td>+4.0 %</td><td>+3.4 %</td></tr>
  <tr><td class="l">Legs where NIFTY moved with the wave</td><td>99.8 %</td><td>100 %</td><td>100 %</td></tr>
  </tbody></table></div>
  <p><b>Answer to Part 8: B, a reflection of NIFTY</b>, amplified by gamma, with IV contributing about 3–4 %. IV is backed out with Black-76 on the put-call-parity forward; there is no quoted IV in the data. The opposite leg confirms it: at a CE wave-2 signal, the same-strike PE lost 33 % / 6 % / 13 % over the next 30 minutes.</p>
  <p>CE and PE were not symmetric out of sample (wave-2 excess CE +7.7 / +17.9 %, PE −5.6 / −27.2 %, n = 28/10 and 19/17), but the intervals overlap zero and the split was not pre-registered. Strikes: OTM1 was highest in 2024 and 2025 (+15.9, +11.1 %) and negative in 2026. ITM and OTM2 were near zero or negative. The mirror pattern (a descending lifecycle) forecast nothing either: −1 % / +3 % / −11 %, all intervals across zero.</p>
</section>
"""

dte = """
<section id="dte">
  <h2><span class="tag">F · 9</span> Expiry: the same NIFTY move, a bigger and more lopsided option move</h2>
  <p>Every non-overlapping 15-minute window, ATM front weekly: option log return regressed on the forward's log return with a squared term.</p>
  <div class="tbl"><table><thead><tr><th>ATM CE, 15 min</th><th>DTE 3–4</th><th>DTE 2</th><th>DTE 1</th><th>DTE 0 (expiry day)</th></tr></thead><tbody>
  <tr><td class="l">Elasticity 2024 / 2025 / 2026</td><td>79 / 82 / –</td><td>61 / 76 / –</td><td>108 / 142 / 102</td><td>184 / 238 / 229</td></tr>
  <tr><td class="l">Premium for NIFTY +0.25 %, 2025</td><td>+20.9 %</td><td>+16.8 %</td><td>+34.5 %</td><td>+48.8 %</td></tr>
  <tr><td class="l">Premium for NIFTY −0.25 %, 2025</td><td>−20.2 %</td><td>−21.1 %</td><td>−36.5 %</td><td>−70.3 %</td></tr>
  <tr><td class="l">Drift with NIFTY flat, 2025</td><td>−0.7 %</td><td>−0.6 %</td><td>−1.0 %</td><td>−6.9 %</td></tr>
  </tbody></table></div>
  <p>Measured, not assumed: sensitivity roughly doubles from DTE 3–4 to DTE 1 and triples by expiry day. On expiry day the response turns lopsided: a 0.25 % adverse move costs half to two-thirds of the premium, while the same favourable move adds 40–60 %. That, plus the −5 to −9 % drift per 15 minutes, is the non-linearity a trader sees near expiry. The wave-2 signal's excess did not rise toward expiry in 2025 or 2026 (DTE 0: −10.3 / −10.9 %). DTE 5+ cannot be measured cleanly because the files' strike lists for those sessions were picked in hindsight. 2026's clean sessions are DTE 0–1 only (Tuesday expiry, Monday strike list).</p>
</section>
"""

regime = """
<section id="regime">
  <h2><span class="tag">G · 7 · 11</span> Regimes and volume</h2>
  <p><b>Regimes.</b> Wave-2 excess by the day's direction (known only after the close, so descriptive only), 2024 / 2025 / 2026: bull +9.9 / +13.3 / +16.9 %, bear +11.7 / −3.8 / −32.1 %, flat +10.8 / +1.8 / +8.0 %. Split by the direction known at the signal: up-so-far +15.7 / +7.7 / +16.8 %, down-so-far +9.6 / −2.2 / −27.3 %. Each out-of-sample cell holds 4 to 21 events, so these are not findings. Pooling does hide one consistent tilt: the pattern fared better on days already moving its way.</p>
  <p><b>Volume leads nothing.</b> Around the wave-2 breakout the volume ratio is 0.9–1.1 on the bars before it, 1.5–2.0 on the breakout bar and after. The correlation between volume ratio and the size of the move is highest in the same bar and equal one bar before and after (2025: 0.12 / 0.23 / 0.14). Volume-spike signals had negative excess every year (C −1.8 / −1.7 / −1.1 %; F −4.0 / −5.8 / −4.3 %). With volume shuffled within each session, the same rules score higher (+1.7, +5.8 % in 2025), so real spikes mark exhaustion rather than ignition.</p>
</section>
"""

oos = """
<section id="oos">
  <h2><span class="tag">H · 16</span> In-sample vs out-of-sample, side by side</h2>
  <div class="tbl"><table><thead><tr><th>Wave-2 signal, 5-minute</th><th>2024 dev (in-sample)</th><th>2025 validation</th><th>2026 blind</th></tr></thead><tbody>
  <tr><td class="l">Excess, ATM (pre-registered H1)</td><td class="pos">+9.4 [+0.5, +19.3] n 26</td><td>+3.2 [−2.3, +7.5] n 8</td><td>−8.5 [−33.9, +15.6] n 9</td></tr>
  <tr><td class="l">Excess, all front strikes</td><td class="pos">+10.7 [+3.3, +19.3] n 105</td><td>+2.4 [−5.1, +8.7] n 47</td><td>−10.5 [−35.6, +18.3] n 27</td></tr>
  <tr><td class="l">Same, on shuffled bars (20×)</td><td>+2.3</td><td>+0.0</td><td>+2.5</td></tr>
  <tr><td class="l">Grid cells with positive excess</td><td>100 %</td><td>83 %</td><td>68 %</td></tr>
  <tr><td class="l">Net ₹ per ATM lot, 30 min</td><td>+118</td><td>−83</td><td>−1,145</td></tr>
  </tbody></table></div>
  <p class="note">Brackets: week-clustered 95 % intervals, percentage points. The 2025 and 2026 columns were produced once, by code frozen with a SHA-256 before those years were opened. Two later changes were memory-only and were checked to reproduce the frozen 2024 panel exactly (LEDGER).</p>
</section>
"""

falsify = """
<section id="falsify">
  <h2><span class="tag">I · 17 · 18</span> Trying to break it</h2>
  <ul class="plain">
    <li><b>Shuffled bars (20 per session, per year).</b> Same lifecycle count, same continuation, same amplitude ratios, and a positive "excess" of +0 to +2.5 %. <b>The shape is not distinguishable from random ordering.</b></li>
    <li><b>Label permutation within matched cells.</b> ATM wave-2 p = 0.095 (2024), 0.26 (2025), 0.78 (2026).</li>
    <li><b>Parameter neighbourhood.</b> Stable in 2024, sign-flipped in 2026 across all five L values.</li>
    <li><b>Timeframes.</b> Signs disagree between 1, 3 and 5 minutes within each year.</li>
    <li><b>Opposite leg and mirror.</b> Consistent with NIFTY driving the premium; the descending mirror has no edge.</li>
    <li><b>Look-ahead.</b> Truncation test: cutting the series at 25 random bars leaves every earlier signal identical. One hindsight bug (a bar confirming its own high) was found and fixed in 2024, before the freeze.</li>
  </ul>
</section>
"""

extra = """
<section id="limits">
  <h2><span class="tag">J</span> Limits and what would change the answer</h2>
  <ul class="plain">
    <li>Sample: 26 / 8 / 9 ATM wave-2 events. The pre-registered H1 cannot be settled either way on this data, which is why the verdict is 4 and not 3.</li>
    <li>No bid/ask quotes: spreads are assumed (0.25–1 % per side). No quoted IV: Black-76 on the parity forward.</li>
    <li>The 2025–26 files hold 5 strikes around the Monday ATM, and clean sessions are the expiry week only.</li>
    <li>What would move the verdict: full option-chain minute data for 2021–2023 (more lifecycles, more DTE range), run once through the frozen detector.</li>
  </ul>
  <p class="note">Files: <code>research/strategy_lab/studies/waves/</code>: PREREG.md (design, hashed), LEDGER.md, REPORT.md, events_tf5_*.csv (Part 19 event table, one row per signal, outcome columns prefixed OUTCOME_), results/*.json. Rule-0 entry: docs/STRATEGY_ANALYSIS_TODO.md S54.</p>
</section>
"""
