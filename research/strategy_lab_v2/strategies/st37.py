"""ST37 - Strategy 37: a real short when an imaginary long's trailing stop is hit (shorts only, options standalone).

On each option's own 1-minute chart an imaginary long follows Strategy 34's long rules: every bullish Foundation SETUP
(break and CHoCH by touch, AVWAP pair, close beyond the CHoCH candle) is bought on paper, stop at the CHoCH candle's low =
1R, trail once SPEC["imaginary"]["trail"]["start_r"] R is reached, lag_r R behind the best R, flat by 15:25. The imaginary
long is never traded. When it exits on its TRAIL stop (not the initial stop, not 15:25), the option is sold for real at the
close of that candle (the first close at which the trail exit is known), if that is before 15:25 the same session.
The real short: stop 30% of the entry premium, else flat at 15:25; 1 lot; native scan (ATR2 / ATM / ITM1 / OTM1 per side
every 5 min), one position per side. Every number is in SPEC (imaginary, position).
Built 2026-10-04 at the user's request ("one more short when the trail SL of a buy is hit; the buy is imaginary, the short
is real"); first numbers: STRATEGY_ANALYSIS_TODO S60.
"""
import numpy as np
import core

ENTRY_RULES = ("trail_flip_short_v1",)
TYPES = ("OPT_NATIVE",)
REFUSED_WHY = "Strategy 37 reads an imaginary long on each option's own chart; futures and options via futures are not part of it"

SPEC = {'code': 'ST37',
 'name': "Short option after an imaginary long's trail stop · 1m",
 'description': "Shorts only, on each option's own 1-minute chart: an imaginary long (bullish Foundation SETUP, stop at "
                "the CHoCH candle's low = 1R, trail from 3R kept 1R behind) is followed on paper; when its trailing stop "
                "is hit, the option is sold for real at that candle's close. Stop 30% of the entry premium; flat by 15:25; "
                "1 lot; one position per CE / PE side.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'choch_candle',
           'entry_rule': 'trail_flip_short_v1',
           'exit_rule': 'next_choch'},
 'imaginary': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'exit': 'position', 'stop': {'from': 'signal'},
               'scale_out': [], 'trail': {'start_r': 3, 'lag_r': 1}, 'reverse': None,
               'notes': "Strategy 34's long: the CHoCH candle's low is the stop and 1R; never traded"},
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
                'notes': "every session with full-chain option data (from 2026-06-30)"},
               {'label': 'First half', 'kind': 'named', 'from': '2026-06-30', 'to': '2026-08-12'},
               {'label': 'Second half', 'kind': 'named', 'from': '2026-08-13', 'to': '2026-09-25'},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'}]}

CUT = 15 * 3600 + 25 * 60


def signals(bars, spec):
    """The imaginary longs on these bars; a short at the close of each candle where one leaves on its trail stop."""
    sg = core.foundation(bars, spec["rules"])
    P = dict(spec["imaginary"])
    out = []
    for x in sg.trades():
        if x["dir"] != "up" or x["sl"] is None: continue
        rec = dict(position="LONG", kind="OPT", instrument="imaginary long", entry_time=int(bars.t[x["entry"]]),
                   entry_px=float(bars.c[x["entry"]]), sl=x["sl"], und_entry=None)
        parts = core.manage(P, rec, bars, int(bars.t[-1]))
        hit = [p_ for p_ in parts if p_["exit_reason"] == "trail_stop"]
        if not hit: continue
        k = int(np.searchsorted(bars.t, hit[0]["exit_time"]))
        if k >= len(bars) or bars.t[k] % core.DAY >= CUT: continue
        out.append(dict(entry=k, exit=k, exit_px=float(bars.c[k]), dir="down", choch=x["entry"], sl=None, pts=0.0,
                        open=True, exit_reason="open"))
    out = sorted({o["entry"]: o for o in out}.values(), key=lambda o: o["entry"])
    return sg.with_trades(out)
