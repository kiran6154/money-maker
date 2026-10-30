"""Opening-range sweep / reclaim continuation, ORR_V1 (family module for ST83 and ST84).

From the user's IMPLEMENTATION_RULESET.md ("Opening-Range Sweep/Reclaim Continuation", ruleset ORR_V1). Lab port, on the
NIFTY index 1-minute candles (a point-accounting proxy, as the ruleset says):

  eligibility   the 09:15 candle (O, H, L, C): range > 0, C != O, body >= `body_min` x range and < `body_max` x range
                (compared in whole paise, no floating point). Bullish body -> LONG only, bearish -> SHORT only, for the
                whole session. The session must have every minute from 09:15 to 15:29 (the lab's files end at 15:29;
                the ruleset's 15:30 row does not exist here), else it is excluded.
  sweep mode    SPEC["orr"]["sweep"]: "close" (the user's rule from 2026-10-24) - the sweep is a completed candle CLOSING
                beyond the boundary, so the reclaim is always a later candle; "wick" (ORR_V1 as written) - a low / high
                beyond it is enough, and the same candle may also reclaim.
  signal        from the 09:16 candle, while flat: LONG - a completed candle with low < the opening low latches the sweep
                (the first one of the flat scan); then a completed close > the opening low reclaims (same candle allowed;
                equality is neither). SHORT - the mirror on the opening high. Entry at the OPEN of the next consecutive
                minute, strictly before `cutoff`.
  confirm       ST84 only (`confirm: "structure"`): the reclaim does not enter; it arms the setup, and the entry comes at
                the open of the minute after the first BOS or CHoCH that way (the Foundation engine, Strategy 1's rules,
                on the same 1-minute candles) at or after the reclaim candle, strictly before `cutoff`. A new sweep of
                the boundary before that confirmation clears the arm (a fresh reclaim is needed).
  fills         entry fill E = open + s (LONG) / open - s (SHORT), s = `slippage` points; stop and target `stop_pts` /
                `target_pts` from E. Every minute from the entry minute on, in this order: the `cutoff` minute -> out at
                its open (FORCE_CLOSE); open beyond the stop -> out at that open (STOP_GAP); open beyond the target -> out
                at the target; low / high through the stop -> the stop; through the target -> the target. Exit fill =
                raw exit - s (LONG) / + s (SHORT). The lab's slippage (types.FUT.slippage_pts = s) applies exactly that.
  re-entry      unlimited, one position at a time: after an exit the exit minute is skipped, the sweep latch is cleared,
                and a fresh sweep and reclaim of the same 09:15 boundary is needed.
"""
import numpy as np
import core

ENTRY_RULES = ("orr_v1",)
TYPES = ("FUT",)
UNDERLYINGS = ("FUT", "INDEX")
OWN_COVERAGE = True
REFUSED_WHY = "ORR_V1 is a NIFTY spot point-accounting strategy; option types are not part of it"
GRID = 375                                                    # 09:15 .. 15:29


def paise(x):
    return int(round(float(x) * 100))


def sessions_of(b):
    """[(day, first bar, last bar + 1)] of the 1-minute bars."""
    cuts = np.concatenate([[0], np.nonzero(np.diff(b.day))[0] + 1, [len(b)]])
    return [(int(b.day[a]), int(a), int(z)) for a, z in zip(cuts[:-1], cuts[1:])]


def complete(b, a, z):
    """Every minute 09:15 .. 15:29, in order, no gap, no duplicate."""
    if z - a != GRID: return False
    tod = (b.t[a:z] % core.DAY) // 60
    return bool(tod[0] == 555 and np.all(np.diff(tod) == 1))


def run_day(b, a, z, X, ev=None):
    """The trades of one session: dicts with bar indices and raw prices (before slippage)."""
    o, h, l, c, t = b.o, b.h, b.l, b.c, b.t
    O, H, L, C = paise(o[a]), paise(h[a]), paise(l[a]), paise(c[a])
    rng, body = H - L, abs(C - O)
    info = dict(day=core.dstr(int(b.day[a])), range=(H - L) / 100, body=body / 100, frac=(body / rng if rng else None), side=0, why="")
    if rng <= 0: info["why"] = "zero range"; return [], info
    if C == O: info["why"] = "doji"; return [], info
    if not (body * 100 >= rng * round(X["body_min"] * 100) and body * 100 < rng * round(X["body_max"] * 100)):
        info["why"] = f"body {body / rng:.1%} of the range"; return [], info
    side = 1 if C > O else -1; info["side"] = side
    oh, ol = float(h[a]), float(l[a]); s = float(X["slippage"])
    cut = t[a] - t[a] % core.DAY + core.hhmm_sec(X["cutoff"])
    structure = X.get("confirm") == "structure"
    out, i, swept, armed = [], a + 1, False, None
    while i < z and t[i] < cut:
        # flat: look for the setup on this completed candle
        body = X.get("sweep") == "close"                  # the sweep is a candle CLOSING beyond the boundary, not a wick poking
        if side > 0:
            sweep, reclaim = (c[i] < ol) if body else (l[i] < ol), c[i] > ol
        else:
            sweep, reclaim = (c[i] > oh) if body else (h[i] > oh), c[i] < oh
        if structure and armed is not None and sweep: armed = None; swept = False        # a new sweep: start again
        if sweep and not swept: swept, sw_i = True, i
        go = None
        if not structure:
            if swept and reclaim: go = i
        else:
            if armed is None and swept and reclaim: armed = i
            if armed is not None and ev is not None and ev[i] == side: go = i
        if go is None: i += 1; continue
        e_i = go + 1                                          # entry: the next consecutive minute's open
        if e_i >= z or t[e_i] != t[go] + 60 or t[e_i] >= cut: break
        raw = float(o[e_i]); E = raw + s * side
        stop, tgt = E - side * X["stop_pts"], E + side * X["target_pts"]
        k, why, px = e_i, None, None
        while k < z:
            if t[k] >= cut: why, px = "FORCE_CLOSE", float(o[k]); break
            ok_ = float(o[k])
            if (ok_ <= stop) if side > 0 else (ok_ >= stop): why, px = "STOP_GAP", ok_; break
            if (ok_ >= tgt) if side > 0 else (ok_ <= tgt): why, px = "target 1", tgt; break
            if (l[k] <= stop) if side > 0 else (h[k] >= stop): why, px = "stop_loss", stop; break
            if (h[k] >= tgt) if side > 0 else (l[k] <= tgt): why, px = "target 1", tgt; break
            k += 1
        if why is None: k, why, px = z - 1, "eod", float(c[z - 1])
        out.append(dict(entry=e_i, exit=k, raw_entry=raw, raw_exit=px, why=why, side=side, sweep=sw_i, reclaim=(armed if structure else go),
                        signal=go, stop=stop, target=tgt))
        i, swept, armed = k + 1, False, None                  # the exit minute is not scanned; a fresh sweep is needed
    return out, info


def run(ctx):
    """{choice: dict(trades, skipped, signals)} over the window, every complete session."""
    spec = ctx["spec"]; X = spec["orr"]
    sp = core.series("spot", "minute")
    d0, d1 = core.dnum(ctx["date_from"]), core.dnum(ctx["date_to"]); ss = core.sessions()
    k0 = int(np.searchsorted(ss, d0)); first = int(ss[max(0, k0 - 2)])
    a, z = int(np.searchsorted(sp.day, first)), int(np.searchsorted(sp.day, d1, "right"))
    b = sp.slice(a, z)
    ev = None
    if X.get("confirm") == "structure":                       # BOS / CHoCH per bar: +1 up, -1 down, 0 none
        sg = core.foundation(b, spec["rules"]); ev = np.zeros(len(b), np.int8)
        for i_, d_ in zip(sg.ei, sg.ed): ev[int(i_)] = int(d_)
    trs, skipped, sigs = [], [], []
    lots = ctx["position"]["lots"]
    for day, s0, s1 in sessions_of(b):
        if day < d0: continue
        if not complete(b, s0, s1):
            skipped.append(dict(signal="", position="", opt_type="", instrument="NIFTY 50", entry_time=core.dstr(day), why=f"incomplete session: {s1 - s0} of {GRID} minutes"))
            continue
        days_tr, info = run_day(b, s0, s1, X, ev)
        if not info["side"]:
            skipped.append(dict(signal="", position="", opt_type="", instrument="NIFTY 50", entry_time=core.dstr(day), filtered=True, why=f"not eligible: {info['why']}"))
            continue
        for n, x in enumerate(days_tr, 1):
            pos = "LONG" if x["side"] > 0 else "SHORT"
            rec = dict(dir="up" if x["side"] > 0 else "down", signal="BULLISH" if x["side"] > 0 else "BEARISH", strike=None, expiry=None,
                       choch_time=int(b.t[x["signal"]]), position=pos, opt_type="FUT", kind="FUT", instrument="NIFTY 50 (spot proxy)",
                       entry_time=int(b.t[x["entry"]]), entry_px=x["raw_entry"], exit_time=int(b.t[x["exit"]]), exit_px=x["raw_exit"],
                       exit_reason=x["why"], open=False, sl=round(x["stop"], 2), und_entry=x["raw_entry"], und_exit=x["raw_exit"], stale=False,
                       lots=lots, tranche=f"#{n}", label=f"{pos} #{n}",
                       sweep_time=core.tstr(b.t[x["sweep"]]), reclaim_time=core.tstr(b.t[x["reclaim"]]), target=round(x["target"], 2),
                       opening_body_fraction=round(info["frac"], 4))
            core.excursion(b, rec, x["side"] > 0)
            trs.append(core.price_trade(ctx, rec))
        sigs.append(dict(time=int(b.t[s0]), dir="up" if info["side"] > 0 else "down", flipped=False, lvl=float(b.c[s0]), av=None, hi=None, lo=None, setup=None))
    return {ch: dict(trades=trs, skipped=skipped, signals=sigs) for ch in core.choice_keys(spec, "FUT")}


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """The index 1-minute candles with the opening range lines, the trades and (ST84) the structure."""
    spec = ctx["spec"]; X = spec["orr"]; sp = core.series("spot", "minute")
    d0, d1 = core.dnum(day), core.dnum(to); ss = core.sessions(); k0 = int(np.searchsorted(ss, d0))
    a, z = int(np.searchsorted(sp.day, int(ss[max(0, k0 - 2)]))), int(np.searchsorted(sp.day, d1, "right"))
    b = sp.slice(a, z); i0 = int(np.searchsorted(b.day, d0)); i1 = len(b) - 1
    if i0 > i1: raise ValueError(f"no index candles from {day}")
    T = lambda i: int(b.t[i]); C = {k: i for i, k in enumerate(body["cols"])}
    rows = [r for r in body["trades"] if d0 <= core.dnum(r[C["entry_time"]][:10]) <= d1]
    trig = []
    for dd, s0, s1 in sessions_of(b):
        if s0 < i0: continue
        up = b.c[s0] > b.o[s0]
        for p_, d_ in ((float(b.h[s0]), "down"), (float(b.l[s0]), "up")):
            trig.append(dict(dir=d_, p=round(p_, 2), a=T(s0), z=T(s1 - 1), hit=(d_ == "up") == up))
    out = dict(day=day, to=to, inst=None, candles=core._chart_bars(b, i0, i1), cols=body["cols"], trades=rows, own=True,
               sessions=int(len(np.unique(b.day[i0:i1 + 1]))), trig=trig)
    if X.get("confirm") == "structure":
        sg = core.foundation(b, spec["rules"]); out.update(core._overlays(b, sg, i0, i1, pair=False))
        out["trig"] = trig
    return out
