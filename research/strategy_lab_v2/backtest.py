"""Backtest ONE strategy. Results go to results/<CODE>/<run>/ and show in the UI (server.py).

    python backtest.py --list                          strategies and their backtests
    python backtest.py ST1                             ST1's default backtest, every type
    python backtest.py ST1 1Y                          a preset: MTD 1M 3M 6M YTD 1Y 5Y, or all
    python backtest.py ST1 2026-01-01 2026-06-30       custom dates
    python backtest.py ST1 1Y --type FUT               only one type: FUT, OPT_FUT_SIGNAL, OPT_NATIVE (repeatable)
    python backtest.py ST1 1Y --tf 5minute --underlying INDEX --square-off none|15:25
    python backtest.py ST1 --defined                   every backtest listed in the strategy file
    python backtest.py --prepare                       parse all candle / option files into cache/ (once, or after new data)
"""
import argparse, sys, time
import core


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("code", nargs="?")
    ap.add_argument("period", nargs="*", help="preset (MTD 1M 3M 6M YTD 1Y 5Y all) or FROM TO")
    ap.add_argument("--type", action="append", choices=[t for t, _, _ in core.TYPES])
    ap.add_argument("--tf", choices=list(core.TF_MIN))
    ap.add_argument("--underlying", choices=("FUT", "INDEX"))
    ap.add_argument("--square-off", help="none = positional, HH:MM = intraday (default: the strategy's)")
    ap.add_argument("--label")
    ap.add_argument("--defined", action="store_true", help="run every backtest in the strategy file")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--prepare", action="store_true", help="cache every candle and option file (first use, or after new data)")
    a = ap.parse_args()
    if a.prepare:
        core.prepare(); return
    mods = core.load_strategies()
    if a.list or not a.code:
        for code, m in mods.items():
            s = m.SPEC
            print(f"{code:<6} {s['name']:<14} {s['timeframe']:<9} {s['description'][:90]}")
            for bt in s["backtests"]:
                print(f"         {'*' if bt.get('default') else ' '} {core.run_key(bt, s)[0]}")
        return
    if a.code not in mods: sys.exit(f"unknown strategy {a.code}; --list shows them")
    spec = mods[a.code].SPEC
    if a.defined:
        bts = spec["backtests"]
    elif not a.period:
        bts = [next(b for b in spec["backtests"] if b.get("default"))]
    else:
        sq = "keep" if a.square_off is None else (None if a.square_off == "none" else a.square_off)
        if len(a.period) == 2: bt = core.custom_backtest(spec, "custom", a.period[0], a.period[1], a.tf, a.underlying, sq, a.label)
        else: bt = core.custom_backtest(spec, a.period[0], tf=a.tf, underlying=a.underlying, square_off=sq, label=a.label)
        bts = [bt]
    t0 = time.time()
    for bt in bts:
        m = core.backtest(a.code, bt, a.type)
        print(f"== {a.code} {m['run']}  {m['date_from']} .. {m['date_to']}  {m['status']}{': ' + m['reason'] if m['reason'] else ''}")
        for typ, tm in m["types"].items():
            if tm.get("status") != "ok":
                print(f"   {typ:<15} refused: {tm.get('reason')}"); continue
            for ch, s in tm["choices"].items():
                print(f"   {typ:<15} {ch:<8} trades {s['trades']:>5}  net {s['net_inr']:>+12,.0f}  PF {s['pf']}  t {s['t_stat']}"
                      f"  skipped {s['skipped']}  locked {s['locked']}")
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
