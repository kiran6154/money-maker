"""ST104 - Strategy 104: the user's Pine script "Adaptive ATR & Schmitt Trigger [Elite Quant v4]" (2026-10-25), ported
line by line; always in the market after the first signal, stop and reverse on the opposite band.

The script, phase by phase (every bar; nz(x) = 0 where the history is missing):
  1. cycle    P = hl2; BP = (P - P[2]) / 2 + 0.5 BP[1]; I = BP[3]; Q = (BP - BP[2]) / 2; phase = atan(Q / I) (0 when I = 0);
              dphase = max(phase[1] - phase, 2 pi / 360); cycle = 2 pi / dphase; Nt = clamp(ceil(cycle / 2), 2, 60).
  2. adaptive ATR   ER = |close - close[Nt]| / sum_{i<Nt} |close[i] - close[i+1]| (the Kaufman efficiency ratio over Nt);
              alpha = (ER (2/3 - 2/31) + 2/31)^2; ADAT = ADAT[1] + alpha (TR - ADAT[1]).
  3. floor and normalisation   macro = RMA(TR, 200); safe = max(ADAT, macro / 2); V_ref = the upper median of the last
              min(4 Nt, 200) values of safe (this bar included); x = (safe - V_ref) / V_ref; NATR = 1 / (1 + e^(-4 x)).
  4. carrier and trigger   carrier = carrier[1] + 2 / (Nt + 1) (hl2 - carrier[1]); mult = 1.618 + 2 (1 - NATR);
              upper / lower = carrier +/- safe x mult; regime 0 at the start: close above upper while regime <= 0 ->
              long (regime 1); close below lower while regime >= 0 -> short (regime -1).
  5. execution   strategy.entry Long / Short: the opposite entry reverses the position (1 lot), nothing else exits.

Build choices (not in the script, fixed before the first run; in SPEC["schmitt"]):
  fill        at the signal candle's CLOSE (the lab's rule; Pine would fill at the next candle's open).
  candles     the script names no timeframe: 5-minute near-month futures by default; 1- and 15-minute are backtests.
  holding     positional, as the script (a position is held across sessions; the near-month contract's last candle ends it,
              the lab's "expiry" exit, and the next flip opens the next trade). The intraday backtest squares off at 15:25
              and re-enters only at the next flip.
  seeds       carrier starts at the first candle's hl2 (Pine's `var carrier = hl2`, then nz(carrier[1]) = 0 on that bar:
              a 0 seed that the EMA would take ~100 candles to forget); TR on the first candle = high - low; RMA(200)
              is a running mean until 200 candles then Wilder (Pine: na until 200, then SMA-seeded).
  warm-up     8 sessions, so the 200-candle floor and the 200-value median are full before the first shown candle.
Numbers: STRATEGY_ANALYSIS_TODO S114.
"""
import math
import numpy as np
from numba import njit
import core

ENTRY_RULES = ("schmitt_v1",)

SPEC = {'code': 'ST104',
 'name': 'Adaptive ATR & Schmitt Trigger (Pine port) · 5m',
 'description': "The user's Pine script ported: a phase-locked cycle length tunes an efficiency-ratio adaptive ATR and a "
                "carrier EMA; bands = carrier +/- adaptive ATR x (1.618 + 2 x (1 - a median-normalised volatility)); a "
                "close above the upper band goes long, below the lower band goes short, each flip reversing the position. "
                "Always in the market after the first signal; positional on 5-minute near-month futures.",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 8,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'schmitt_v1', 'exit_rule': 'reverse'},
 'schmitt': {'fast': 2, 'slow': 30, 'nt_max': 60, 'nt_min': 2, 'macro_len': 200, 'floor': 0.5, 'median_cap': 200,
             'median_mult': 4, 'sigmoid_k': 4.0, 'mult_base': 1.618, 'mult_range': 2.0, 'fill': 'close',
             'notes': "the script's constants, named; fill: 'close' = the signal candle's close (Pine: the next open)"},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': None, 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY', 'MONTHLY'], 'expiry_min_days': 1, 'strike_step': 50,
             'strike_choices': ['ATR2', 'ATM', 'ITM2', 'ITM1', 'OTM1', 'OTM2', 'OTM3', 'OTM4'], 'strike_default': 'ATR2',
             'atr_period': 14,
             'native_scan': {'choices': ['ATR2', 'ATM', 'ITM1', 'OTM1'], 'every_minutes': 5, 'one_per_side': True}},
 'backtests': [{'label': 'All data', 'kind': 'all', 'default': True, 'notes': 'positional, as the script: held across sessions'},
               {'label': 'All data', 'kind': 'all', 'square_off': '15:25', 'notes': 'intraday: squared off at 15:25, re-entered at the next flip'},
               {'label': 'All data', 'kind': 'all', 'timeframe': 'minute', 'notes': 'the same on 1-minute candles, positional'},
               {'label': 'All data', 'kind': 'all', 'timeframe': '15minute', 'notes': 'the same on 15-minute candles, positional'},
               {'label': 'First half', 'kind': 'named', 'from': '2018-01-15', 'to': '2022-06-30'},
               {'label': 'Second half', 'kind': 'named', 'from': '2022-07-01', 'to': '2026-10-09'},
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'}]}


@njit(cache=True)
def _kernel(o, h, l, c, fast, slow, nt_min, nt_max, macro_len, floor, med_cap, med_mult, sig_k, m_base, m_range):
    n = len(c)
    BP = np.zeros(n); phase = np.zeros(n); Nt = np.zeros(n, np.int64)
    adat = np.zeros(n); safe = np.zeros(n); natr = np.zeros(n); carrier = np.zeros(n)
    upper = np.zeros(n); lower = np.zeros(n); regime = np.zeros(n, np.int64); sig = np.zeros(n, np.int64)
    tr = np.zeros(n); macro = np.zeros(n)
    a_fast = 2.0 / (fast + 1.0); a_slow = 2.0 / (slow + 1.0)
    two_pi = 2.0 * math.pi; min_d = two_pi / 360.0
    ring = np.zeros(med_cap); ring_n = 0                       # the last med_cap values of safe, newest first
    reg = 0; car = (h[0] + l[0]) / 2.0; ad = 0.0; s_tr = 0.0
    for i in range(n):
        p = (h[i] + l[i]) / 2.0
        p2 = (h[i - 2] + l[i - 2]) / 2.0 if i >= 2 else 0.0
        bp1 = BP[i - 1] if i >= 1 else 0.0
        BP[i] = (p - p2) / 2.0 + 0.5 * bp1
        I = BP[i - 3] if i >= 3 else 0.0
        Q = (BP[i] - (BP[i - 2] if i >= 2 else 0.0)) / 2.0
        ph = math.atan(Q / I) if I != 0.0 else 0.0
        phase[i] = ph
        d = (phase[i - 1] if i >= 1 else 0.0) - ph
        if d < min_d: d = min_d
        cyc = two_pi / d
        nt = int(math.ceil(0.5 * cyc))
        if nt < nt_min: nt = nt_min
        if nt > nt_max: nt = nt_max
        Nt[i] = nt
        # efficiency ratio over nt
        S = abs(c[i] - c[i - nt]) if i >= nt else abs(c[i] - c[0])
        V = 0.0
        for k in range(nt):
            j = i - k
            if j >= 1: V += abs(c[j] - c[j - 1])
        if V == 0.0: V = 0.00001
        ER = S / V
        a_dyn = (ER * (a_fast - a_slow) + a_slow) ** 2
        t = h[i] - l[i]
        if i >= 1:
            t = max(t, abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        tr[i] = t
        ad = ad + a_dyn * (t - ad); adat[i] = ad
        # macro floor: running mean until macro_len, then Wilder
        if i < macro_len:
            s_tr += t; m = s_tr / (i + 1)
        else:
            m = (macro[i - 1] * (macro_len - 1) + t) / macro_len
        macro[i] = m
        sf = ad if ad > m * floor else m * floor
        safe[i] = sf
        # the upper median of the last min(med_mult * nt, med_cap) values, this one included
        if ring_n < med_cap: ring_n += 1
        for k in range(ring_n - 1, 0, -1): ring[k] = ring[k - 1]
        ring[0] = sf
        w = med_mult * nt
        if w > med_cap: w = med_cap
        if w > ring_n: w = ring_n
        tmp = np.sort(ring[:w].copy())
        mi = int(w * 0.5)
        if mi > w - 1: mi = w - 1
        vref = tmp[mi]
        x = (sf - vref) / (vref if vref != 0.0 else 0.00001)
        na = 1.0 / (1.0 + math.exp(-sig_k * x)); natr[i] = na
        car = car + (2.0 / (nt + 1.0)) * (p - car); carrier[i] = car
        band = sf * (m_base + m_range * (1.0 - na))
        upper[i] = car + band; lower[i] = car - band
        if reg <= 0 and c[i] > upper[i]:
            reg = 1; sig[i] = 1
        elif reg >= 0 and c[i] < lower[i]:
            reg = -1; sig[i] = -1
        regime[i] = reg
    return sig, regime, carrier, upper, lower, Nt, safe, natr


def indicator(bars, spec):
    X = spec["schmitt"]
    return _kernel(bars.o, bars.h, bars.l, bars.c, float(X["fast"]), float(X["slow"]), int(X["nt_min"]), int(X["nt_max"]),
                   int(X["macro_len"]), float(X["floor"]), int(X["median_cap"]), int(X["median_mult"]), float(X["sigmoid_k"]),
                   float(X["mult_base"]), float(X["mult_range"]))


def signals(bars, spec):
    """Each regime flip opens a position at that candle's close and closes the previous one there (stop and reverse)."""
    sig, regime, carrier, upper, lower, Nt, safe, natr = indicator(bars, spec)
    c = bars.c; n = len(bars); trades = []
    flips = np.nonzero(sig)[0]
    for k, i in enumerate(flips):
        i = int(i); up = sig[i] == 1
        if k + 1 < len(flips):
            x = int(flips[k + 1]); px = float(c[x]); why, still = "reverse", False
        else:
            x = n - 1; px = float(c[x]); why, still = "open", True
        e = float(c[i])
        trades.append(dict(entry=i, exit=x, exit_px=px, dir="up" if up else "down", choch=i, sl=None,
                           pts=(px - e) if up else (e - px), open=still, exit_reason=why))
    sg = core.foundation(bars, spec["rules"]).with_trades(trades, [carrier, upper, lower])
    sg.line_names = ["Carrier", "Upper band", "Lower band"]; sg.line_colors = ["#8e8e8e", "#30a46c", "#e5484d"]
    sg.extra = dict(Nt=Nt, safe=safe, natr=natr, regime=regime)
    return sg


def option_lines(s):
    _, _, carrier, upper, lower, _, _, _ = indicator(s, SPEC)
    return [("Carrier", carrier), ("Upper band", upper), ("Lower band", lower)]
