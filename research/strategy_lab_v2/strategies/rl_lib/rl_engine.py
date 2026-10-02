"""v1 engine.py's API (load / run, string times, dict output) over v2's cached candles and numba engine, for the learner
(rl.py) and nothing else. run() gives the same swings, CHoCHs, SETUPs, trades and AVWAP as v1 engine.run (the engine
itself is checked against v1 in tests/test_parity.py)."""
import numpy as np
import core
import rl_lab


def load(path, date_from, date_to, warmup_days):
    """Candles from (date_from - warmup_days sessions) to date_to as v1 dict lists; (bars, index of the first shown bar)."""
    b, s0 = core.window(core.load_file(path), date_from, date_to, warmup_days)
    bars = dict(t=core.tstrs(b.t).tolist(), o=b.o.tolist(), h=b.h.tolist(), l=b.l.tolist(), c=b.c.tolist(), v=b.v.tolist(), _bars=b)
    rl_lab.register(bars, b)                   # manage()'s numba loop reads the same candles as arrays
    return bars, s0


def run(bars, p):
    """v1 engine.run(bars, p) output from v2's engine: sw, chs, setups, trades, events, prot, av."""
    b = bars.get("_bars")
    if b is None:
        b = core.Bars(core.np.array([core.ts(x) for x in bars["t"]], dtype=np.int64), bars["o"], bars["h"], bars["l"], bars["c"], bars["v"])
    sg = core.foundation(b, p)
    sw = [dict(k="H" if k == 1 else "L", bar=int(bb), p=float(pp), conf=int(c), broken=False)
          for k, bb, pp, c in zip(sg.sk, sg.sb, sg.sp, sg.sc)]
    chs = []
    for j in range(len(sg.qi)):
        hi, lo = int(sg.qhi[j]), int(sg.qlo[j])
        chs.append(dict(i=int(sg.qi[j]), kind="CHoCH", dir="up" if sg.qd[j] == 1 else "down", flip=bool(sg.qflip[j]),
                        lvl=float(sg.qlvl[j]), sw=sw[int(sg.qsw[j])], av=float(sg.qav[j]), tr=int(sg.qtr[j]),
                        hi=sw[hi] if hi >= 0 else None, lo=sw[lo] if lo >= 0 else None, end=int(sg.qend[j])))
    events = [dict(i=int(i), kind="BOS" if k == 0 else "CHoCH", dir="up" if d == 1 else "down") for i, k, d in zip(sg.ei, sg.ek, sg.ed)]
    setups = [dict(i=int(i), dir="up" if d == 1 else "down", ch=int(ch)) for i, d, ch in zip(sg.ui, sg.ud, sg.uch)]
    prot = [None if np.isnan(v) else float(v) for v in sg.prot]
    return dict(sw=sw, chs=chs, events=events, setups=setups, trades=sg.trades(), prot=prot, av=sg.av,
                skipped=[dict(entry=int(e), dir="up" if d == 1 else "down", sl=float(s)) for e, d, s in zip(sg.ke, sg.kd, sg.ksl)])
