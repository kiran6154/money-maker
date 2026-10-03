"""ST36 - Strategy 36: sell the option at its swing highs while its SMA 200 is rising (shorts only, options standalone).

On each watched option's own 1-minute chart (native scan: ATR2 / ATM / ITM1 / OTM1 per side every 5 min, one position per
side): when a swing high formed this session is confirmed (Foundation's swings, break by touch) and the confirming candle
closes below it, sell the option at that close - only if the option's SMA 200 (over the contract's whole series) is rising
at that candle (SMA[i] > SMA[i - 1]). Exit: stop 30% of the entry premium above the entry, else flat at 15:25. 1 lot.
Every number is in SPEC (sma_filter, position).
Built 2026-10-04 at the user's request after the short-entry comparison (STRATEGY_ANALYSIS_TODO S60: swing high + SMA200
rising, weekly +Rs 19,300 PF 1.16, monthly +Rs 32,680 PF 1.30 on Jun 30 - Sep 25 2026 - the reference for this build).
"""
import numpy as np
import core

_ST32 = core.family("st32")
ENTRY_RULES = ("swing_short_v1",)
TYPES = ("OPT_NATIVE",)
REFUSED_WHY = "Strategy 36 sells options at swing highs on each option's own chart; futures and options via futures are not part of it"

SPEC = {'code': 'ST36',
 'name': 'Short option swing highs while SMA-200 rises · 1m',
 'description': "Shorts only, on each option's own 1-minute chart: sell the option when a swing high (formed this "
                "session) is confirmed, at the confirming candle's close, only while the option's SMA 200 is rising. "
                "Stop 30% of the entry premium; flat by 15:25; 1 lot; one position per CE / PE side.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'swing_short_v1',
           'exit_rule': 'next_choch'},
 'sma_filter': {'period': 200, 'trend': 'slope', 'want': 'rising',
                'notes': "rising = SMA at the entry candle above the SMA one candle before, on the option's own candles "
                         "over the contract's whole series"},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1,
              'square_off': '15:25',
              'lock': 'strike',
              'exit': 'position',
              'stop': {'futures_pts': 50, 'option_pct': 30},
              'scale_out': [],
              'trail': None},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY', 'MONTHLY'],
             'expiry_min_days': 1,
             'strike_step': 50,
             'strike_choices': ['ATR2', 'ATM', 'ITM2', 'ITM1', 'OTM1', 'OTM2', 'OTM3', 'OTM4'],
             'strike_default': 'ATR2',
             'atr_period': 14,
             'native_scan': {'choices': ['ATR2', 'ATM', 'ITM1', 'OTM1'], 'every_minutes': 5, 'one_per_side': True}},
 'backtests': [{'label': 'All data', 'kind': 'all', 'default': True,
                'notes': "every session with full-chain option data (from 2026-06-30); the reference window of S60"},
               {'label': 'First half', 'kind': 'named', 'from': '2026-06-30', 'to': '2026-08-12'},
               {'label': 'Second half', 'kind': 'named', 'from': '2026-08-13', 'to': '2026-09-25'},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'}]}

CUT = 15 * 3600 + 25 * 60


def signals(bars, spec):
    """Every swing high formed and confirmed in the same session, before the square-off, that the confirming candle closes
    below: a short at that close (the SMA filter acts per trade in leg_filter)."""
    sg = core.foundation(bars, dict(spec["rules"], sl_rule="none"))
    idx = sorted({int(ci) for k_, pb, p, ci in zip(sg.sk, sg.sb, sg.sp, sg.sc)
                  if k_ == 1 and bars.day[int(pb)] == bars.day[int(ci)] and p > bars.c[int(ci)] and bars.t[int(ci)] % core.DAY < CUT})
    tr = [dict(entry=i, exit=i, exit_px=float(bars.c[i]), dir="down", choch=i, sl=None, pts=0.0, open=True,
               exit_reason="open") for i in idx]
    return sg.with_trades(tr)


def leg_filter(ctx, rec, s):
    """The option's SMA 200 must be rising at the entry candle (the whole contract's series)."""
    f = ctx["spec"]["sma_filter"]; n = f["period"]
    i = s.find(rec["entry_time"])
    if i < 1: return f"{rec['instrument']} has no candle at entry"
    v = _ST32.sma_of(s, n)
    if np.isnan(v[i]) or np.isnan(v[i - 1]): return f"SMA {n} not formed yet on {rec['instrument']}"
    if not v[i] > v[i - 1]: return f"SMA {n} of {rec['instrument']} not rising at the swing high"
    return None


option_lines = _ST32.option_lines
