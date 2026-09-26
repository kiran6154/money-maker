"""Foundation engine: swings -> protected level -> CHoCH/BOS -> AVWAP pair -> SETUP -> trades.

Every strategy is this engine run with a different parameter row from the `strategy` table.
All decisions use only candles up to the current one (swings are used from their confirmation bar).
"""
import csv, datetime as D


def load(path, date_from, date_to, warmup_days):
    """Candles from (date_from - warmup_days trading days) to date_to. Returns (bars, index of first shown bar)."""
    rows = [r for r in csv.DictReader(open(path)) if r["datetime"][:10] <= date_to]
    days = sorted({r["datetime"][:10] for r in rows})
    shown = [d for d in days if d >= date_from]
    if not shown:
        raise ValueError(f"no data in {path} from {date_from}")
    start = days[max(0, days.index(shown[0]) - warmup_days)]
    rows = [r for r in rows if r["datetime"][:10] >= start]
    bars = dict(t=[r["datetime"] for r in rows],
                o=[float(r["open"]) for r in rows], h=[float(r["high"]) for r in rows],
                l=[float(r["low"]) for r in rows], c=[float(r["close"]) for r in rows],
                v=[float(r["volume"]) for r in rows])
    s0 = next(i for i, t in enumerate(bars["t"]) if t[:10] >= date_from)
    return bars, s0


def run(bars, p):
    """p: dict with break_mode ('touch'|'close'), avwap_weight ('volume'|'equal'),
    entry_rule ('setup_v1'), exit_rule ('next_choch')."""
    t, o, h, l, c, vol = (bars[k] for k in "tohlcv")
    n = len(t)
    touch = p["break_mode"] == "touch"

    # price that "breaks" a level: touch uses the wick, close uses the close
    def below(i, lvl): return (l[i] <= lvl) if touch else (c[i] < lvl)
    def above(i, lvl): return (h[i] >= lvl) if touch else (c[i] > lvl)

    # ---- swing detector (Pine port; confirmation by break_mode) ----
    mode = 0; ch = chb = cl = clb = None; sw = []; cand = []
    for i in range(n):
        he = mode in (0, 1); le = mode in (0, -1)
        if he and (ch is None or h[i] >= ch): ch, chb = h[i], i
        if le and (cl is None or l[i] <= cl): cl, clb = l[i], i
        sh = he and ch is not None and i > chb and below(i, l[chb])
        sl = le and cl is not None and i > clb and above(i, h[clb])
        if mode == 0 and sh and sl:
            if clb < chb: sh = False
            else: sl = False
        if sh:
            sw.append(dict(k="H", bar=chb, p=ch, conf=i)); mode = -1; ch = chb = None; cl, clb = l[i], i
        if sl:
            sw.append(dict(k="L", bar=clb, p=cl, conf=i)); mode = 1; cl = clb = None; ch, chb = h[i], i
        cand.append((ch if he and ch is not None else None, cl if le and cl is not None else None))
    byconf = {}
    for s in sw:
        s["broken"] = False; byconf.setdefault(s["conf"], []).append(s)

    # ---- AVWAP from any anchor bar ----
    tp = [(h[i] + l[i] + c[i]) / 3 for i in range(n)]
    w = vol if p["avwap_weight"] == "volume" else [1.0] * n
    cum = [0.0]; cw = [0.0]
    for x, ww in zip(tp, w): cum.append(cum[-1] + x * ww); cw.append(cw[-1] + ww)
    def av(a, i): return (cum[i + 1] - cum[a]) / (cw[i + 1] - cw[a]) if cw[i + 1] > cw[a] else tp[a]

    # ---- trend, protected level, CHoCH/BOS ----
    trend = 0; anchor = None; events = []; prot = [None] * n
    lastH = lastL = None; bos_used = set()
    unbroken = []          # confirmed, not yet broken swings (both kinds)
    cands = []             # protected-level candidates for the current trend

    def qualifies(s):
        a = av(anchor["bar"], s["conf"])
        return (s["k"] == "L" and s["p"] < a) if trend == 1 else (s["k"] == "H" and s["p"] > a)

    def rebuild(i):
        return [s for s in sw if s["conf"] < i and not s["broken"] and s["bar"] >= anchor["bar"] and qualifies(s)]

    for i in range(n):
        if anchor is not None:
            v = av(anchor["bar"], i)
            P = next((s for s in reversed(cands) if not s["broken"]), None)
            prot[i] = P["p"] if P else None
            if trend == 1 and lastH and id(lastH) not in bos_used and above(i, lastH["p"]):
                bos_used.add(id(lastH)); events.append(dict(i=i, kind="BOS", dir="up"))
            if trend == -1 and lastL and id(lastL) not in bos_used and below(i, lastL["p"]):
                bos_used.add(id(lastL)); events.append(dict(i=i, kind="BOS", dir="down"))
            if P and ((trend == 1 and below(i, P["p"])) or (trend == -1 and above(i, P["p"]))):
                flip = (trend == 1 and below(i, v)) or (trend == -1 and above(i, v))
                events.append(dict(i=i, kind="CHoCH", dir="down" if trend == 1 else "up", flip=flip,
                                   lvl=P["p"], sw=P, av=v, tr=trend, hi=lastH, lo=lastL))
                if flip:
                    for s in (lastL, lastH):
                        if s: bos_used.add(id(s))   # old-leg swings can't make a BOS in the new trend
                    trend = -trend; anchor = lastH if trend == -1 else lastL
                    cands = rebuild(i)
        # swings touched/closed through by this candle are used up
        keep = []
        for s in unbroken:
            if (s["k"] == "L" and below(i, s["p"])) or (s["k"] == "H" and above(i, s["p"])): s["broken"] = True
            else: keep.append(s)
        unbroken = keep
        for s in byconf.get(i, []):
            if s["k"] == "H": lastH = s
            else: lastL = s
            unbroken.append(s)
            if anchor is None:
                trend = -1 if s["k"] == "H" else 1; anchor = s; cands = [s] if qualifies(s) else []
            elif s["bar"] >= anchor["bar"] and qualifies(s):
                cands.append(s)

    # ---- AVWAP pair per CHoCH + SETUP + trades ----
    chs = [e for e in events if e["kind"] == "CHoCH"]
    setups, trades = [], []
    for j, e in enumerate(chs):
        end = chs[j + 1]["i"] if j + 1 < len(chs) else n - 1
        e["end"] = end
        if not (e["hi"] and e["lo"]): continue
        aH, aL, ci = e["hi"]["bar"], e["lo"]["bar"], e["i"]
        for k in range(ci + 1, end + 1):
            if k - 1 <= max(aH, aL): continue
            dH = av(aH, k) - av(aH, k - 1); dL = av(aL, k) - av(aL, k - 1)
            if (e["dir"] == "down" and c[k] < l[ci] and dH < 0 and dL < 0) or \
               (e["dir"] == "up" and c[k] > h[ci] and dH > 0 and dL > 0):
                setups.append(dict(i=k, dir=e["dir"], ch=ci)); break
    chi = [e["i"] for e in chs]
    sl_rule = p.get("sl_rule", "none")
    skipped = []
    for x in setups:
        k0, ci, up = x["i"], x["ch"], x["dir"] == "up"
        sg = 1 if up else -1
        # stop level, known at the entry candle's close
        if sl_rule == "choch_candle":            # CE: CHoCH candle low, PE: CHoCH candle high
            sl = l[ci] if up else h[ci]
        elif sl_rule == "prev_swing":            # CE: latest confirmed SL, PE: latest confirmed SH
            prev = [s for s in sw if s["conf"] <= k0 and s["k"] == ("L" if up else "H")]
            sl = prev[-1]["p"] if prev else None
        else:
            sl = None
        if sl is not None and (sl >= c[k0] if up else sl <= c[k0]):
            skipped.append(dict(entry=k0, dir=x["dir"], sl=sl)); continue   # stop on the wrong side of entry
        nx = next((k for k in chi if k > k0), None)
        last = nx if nx is not None else n - 1
        xi, px, reason = last, c[last], ("next_choch" if nx is not None else "open")
        if sl is not None:
            for k in range(k0 + 1, last + 1):
                gap = o[k] <= sl if up else o[k] >= sl
                hit = below(k, sl) if up else above(k, sl)
                if gap or hit:                   # stop checked before the CHoCH exit on the same candle
                    xi, reason = k, "stop_loss"
                    px = o[k] if gap and touch else (sl if touch else c[k])
                    break
        trades.append(dict(entry=k0, exit=xi, exit_px=px, dir=x["dir"], choch=ci, sl=sl, pts=sg * (px - c[k0]),
                           open=reason == "open", exit_reason=reason))
    return dict(sw=sw, cand=cand, events=events, chs=chs, prot=prot, setups=setups, trades=trades, skipped=skipped, av=av)
