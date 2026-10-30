"""Chart explorer: one instrument's candles for a chosen date, with the engine's indicators and a strategy's trades computed
directly on those candles. A visualization, not a backtest: nothing is stored, nothing is compared with a baseline.

Used by serve.py (GET /api/explorer/...). Instruments:
    FUT    near-month NIFTY futures (the contract of that date)
    INDEX  the NIFTY index (equal-weighted AVWAP: it has no volume)
    OPT    one option contract (expiry, strike, CE / PE) - the strategy is applied to the option's own chart
The strategy supplies the rules (break / CHoCH mode, AVWAP weight, stop rule), the position handling (lots, managed exits,
scale-out, trail, reverse, square-off, strike lock) and the costs, exactly as in the lab. The engine warms up on the
strategy's warm-up sessions before the date; the chart shows `days_before` sessions before the date and the date itself.
"""
import bisect, csv, json, os
from collections import OrderedDict
import engine
import lab
import rainbow

TFS = ("minute", "3minute", "5minute", "15minute", "30minute")
CHARGES = json.load(open(lab.CHARGECFG, encoding="utf-8"))
_ROWS = OrderedDict()        # (kind, tf, first, last) -> candle dict   (a few recent requests)
_CHAINS = {}                 # base timeframe -> OptionChain


def _cache(d, key, value, keep=6):
    d[key] = value
    while len(d) > keep: d.popitem(last=False)
    return value


def strategies():
    """[{code, name, timeframe, description}] for the strategy picker (FZ strategies included; their gate is not applied here)."""
    return [dict(code=sp["code"], name=sp["name"], timeframe=sp["timeframe"], description=sp["description"],
                 managed=lab.position_of(sp)["exit"] == "position") for _, sp in lab.load_strategies()]


def data_range():
    ss = lab.sessions()
    return dict(first=ss[0], last=ss[-1])


def _spec(code):
    for _, sp in lab.load_strategies():
        if sp["code"] == code: return sp
    raise ValueError(f"unknown strategy {code!r}")


def _window_days(date, warmup, days_before):
    ss = lab.sessions()
    if date not in ss: raise ValueError(f"{date} is not a session in the data ({ss[0]} .. {ss[-1]})")
    i = ss.index(date)
    return ss[max(0, i - max(warmup, days_before))], ss[max(0, i - days_before)], date


def _rows(path, first, last):
    """Candle dicts of `path` from session `first` to `last` (read by scanning; the files are sorted by time)."""
    out = []
    with open(path) as f:
        for r in csv.DictReader(f):
            d = r["datetime"][:10]
            if d < first: continue
            if d > last: break
            if r["datetime"][11:16] <= "15:29": out.append(r)
    return out


def _bars(kind, tf, first, last):
    key = (kind, tf, first, last)
    if key in _ROWS: return _ROWS[key]
    src = lab.FUT1 if kind == "FUT" else lab.SPOT1
    rows = _rows(src, first, last)
    if tf != "minute": rows = lab.resample_rows(rows, lab.TF_MIN[tf])
    b = dict(t=[r["datetime"] for r in rows], o=[float(r["open"]) for r in rows], h=[float(r["high"]) for r in rows],
             l=[float(r["low"]) for r in rows], c=[float(r["close"]) for r in rows], v=[float(r.get("volume") or 0) for r in rows])
    return _cache(_ROWS, key, b)


def _chain(tf):
    base = "minute" if tf in ("minute", "3minute") else "5minute"
    if base not in _CHAINS:
        row = dict(lab.type_rows(lab.load_strategies()[0][1])[1], timeframe=base)
        _CHAINS[base] = lab.OptionChain(row)
    return _CHAINS[base]


def instruments(date, tf="minute"):
    """What can be shown on `date`: the futures contract, the index, and the option contracts with candles that day
    (nearest weekly expiries and the month's expiry; strikes per right)."""
    ss = lab.sessions()
    if date not in ss: raise ValueError(f"{date} is not a session in the data ({ss[0]} .. {ss[-1]})")
    by, _ = lab.fut_contracts()
    fc = next((v for k, v in by.items() if k.startswith(date)), ("NIFTY FUT", None))
    ch = _chain(tf)
    exps = [e for e in ch.calendar if e >= date][:3]
    mo = ch.expiry_for(date, 0, "MONTHLY")
    if mo and mo not in exps: exps.append(mo)
    opts = []
    for e in exps:
        strikes = {}
        for right in ("CE", "PE"):
            if e == ch.kite_exp:
                folder = os.path.join(ch.kite, ch.base)
                ks = sorted({int(f[len(ch.pre):-6]) for f in os.listdir(folder) if f.startswith(ch.pre) and f.endswith(right + ".csv")}) \
                    if os.path.isdir(folder) else []
                ks = [k for k in ks if (s := ch.get(e, k, right)) is not None and any(x.startswith(date) for x in s.t)]
            else:
                cols = ch._local_right(e, right)
                ks = sorted(k for k, cs_ in cols.items() if any(x.startswith(date) for x in cs_[0]))
            strikes[right] = ks
        if strikes["CE"] or strikes["PE"]:
            opts.append(dict(expiry=e, monthly=e == mo, strikes=strikes))
    spot = _bars("INDEX", "minute", date, date)
    return dict(date=date, futures=dict(contract=fc[0], expiry=fc[1]), index_open=spot["o"][0] if spot["t"] else None,
                options=opts)


def chart(date, inst, code, tf="minute", expiry=None, strike=None, right=None, days_before=1, square_off="own"):
    """Chart payload (C, S, E, PR, PAIR, M as the dashboard draws them) and the strategy's trades on one instrument."""
    if tf not in TFS: raise ValueError(f"tf must be one of {TFS}")
    if inst not in ("FUT", "INDEX", "OPT"): raise ValueError("inst must be FUT, INDEX or OPT")
    days_before = max(0, min(int(days_before), 5))
    spec = _spec(code)
    row = next(x for x in lab.type_rows(spec) if x["variant"] == ("FUT" if inst != "OPT" else "OPT_NATIVE"))
    if square_off != "own":                      # the page's intraday / positional switch
        row = dict(row, position_json=json.dumps(dict(lab.position_cfg(row), square_off=square_off or None), sort_keys=True))
    first, show, last = _window_days(date, spec["warmup_days"], days_before)
    if inst == "OPT":
        if not (expiry and strike and right in ("CE", "PE")): raise ValueError("an option needs expiry, strike and right (CE / PE)")
        s = _chain(tf).get(expiry, int(strike), right)
        if s is None: raise ValueError(f"no candles for {expiry} {strike} {right}")
        name = _chain(tf).name(expiry, int(strike), right)
        keep = [i for i, x in enumerate(s.t) if first <= x[:10] <= last]
        if not any(s.t[i].startswith(date) for i in keep): raise ValueError(f"{name} has no candles on {date}")
        bars = {k: [getattr(s, k)[i] for i in keep] for k in "tohlcv"}
        kind, pos_kind = "OPT", "OPT"
    else:
        bars = _bars(inst, tf, first, last)
        name = "NIFTY index" if inst == "INDEX" else None
        kind, pos_kind = inst, "FUT"
    if not bars["t"]: raise ValueError("no candles in that window")
    p = dict(break_mode=row["break_mode"], choch_mode=row.get("choch_mode") or row["break_mode"],
             avwap_weight="equal" if inst == "INDEX" else row["avwap_weight"], sl_rule=row["sl_rule"])
    r = engine.run(bars, p)
    rule = spec["rules"].get("entry_rule")
    X, RB, rule_note = r["trades"], None, ""
    if rule in rainbow.RULES:                    # the ribbon and its trades on these candles; the engine's overlays stay for context
        rcfg = rainbow.config_of(spec); Rr = rainbow.ribbon(bars, rcfg)
        X, RB = rainbow.trades_of(bars, rainbow.signals(bars, rcfg, Rr), rcfg, Rr), Rr["lines"]
    elif rule not in lab.ENTRY_RULES:
        rule_note = f"; NOTE: this strategy's entries come from its own module ({rule}) - the trades shown are the engine's Foundation SETUPs, not the strategy's"
    t = bars["t"]
    i0 = bisect.bisect_left(t, f"{show} 00:00:00"); i1 = len(t) - 1
    cs = dict(CHARGES[row["charge_code"] if inst == "OPT" else spec["types"]["FUT"]["charge_code"]])
    st = dict(row, slippage_pts=spec["types"]["OPT_NATIVE" if inst == "OPT" else "FUT"]["slippage_pts"])
    by, clast = lab.fut_contracts()
    pmode, lock = lab.position_mode(st), lab.StrikeLock(st)
    trades, skipped, marks = [], [], []
    for x in X:
        if x["entry"] < i0: continue
        lng = x["dir"] == "up"
        inst_name = name or by.get(t[x["entry"]], ("NIFTY FUT", None))[0]
        exp_ = expiry if inst == "OPT" else (by.get(t[x["entry"]], (None, None))[1] if inst == "FUT" else None)
        rec = dict(dir=x["dir"], signal="BULLISH" if lng else "BEARISH", position="LONG" if lng else "SHORT", opt_type=right or kind,
                   kind=pos_kind, instrument=inst_name, strike=strike, expiry=exp_, choch_time=t[x["choch"]],
                   entry_time=t[x["entry"]], exit_time=t[x["exit"]], exit_reason=x["exit_reason"], open=x["open"], sl=x["sl"],
                   entry_px=bars["c"][x["entry"]], exit_px=x["exit_px"], und_entry=None, und_exit=None)
        sq = lab.square_off_at(st, rec["entry_time"])
        if sq and rec["entry_time"] >= sq:
            skipped.append(dict(entry_time=rec["entry_time"], position=rec["position"], why="entry at or after the square-off time")); continue
        u = lock.held(inst_name, rec["entry_time"])
        if u:
            skipped.append(dict(entry_time=rec["entry_time"], position=rec["position"], why=f"strike locked: open until {u}")); continue
        cap = t[-1]
        if inst == "FUT" and exp_ and inst_name in clast: cap = min(cap, clast[inst_name])
        if not pmode: lab.eod_cut(st, rec, t, bars["c"])
        O = (t, bars["o"], bars["h"], bars["l"], bars["c"])
        parts = lab.manage(st, rec, *O, cap, exp_) if pmode else lab.tranches(st, rec, *O)
        if pmode:
            cur_rec, cur, depth = rec, parts, 0
            while (rv := lab.reversal_of(st, cur, depth)):
                cur_rec = lab.flip(cur_rec, rv[0], rv[1], depth); depth += 1
                cur = [lab.rev_tag(q) for q in lab.manage(st, cur_rec, *O, cap, exp_)]; parts = parts + cur
        lock.hold(inst_name, max(q["exit_time"] for q in parts), any(q["open"] for q in parts))
        for tr in parts:
            lab.excursion(t, bars["h"], bars["l"], tr, tr["position"] == "LONG")
            lab.price_trade(st, cs, tr)
            jx = max(bisect.bisect_right(t, tr["exit_time"]) - 1, 0)
            j0 = max(bisect.bisect_right(t, tr["entry_time"]) - 1, 0)
            m = lab.mark(x, bars, tr["position"] + (f" · {tr['tranche']}" if tr["tranche"] else ""))
            m[0], m[1], m[2], m[3], m[4] = lab.ts(t[j0]), tr["entry_px"], lab.ts(t[jx]), tr["exit_px"], "up" if tr["position"] == "LONG" else "down"
            m[5], m[6], m[7], m[8] = round(tr["pts"], 2), tr["open"], tr["sl"], tr["exit_reason"]
            m.append(m[4]); marks.append(m)
            trades.append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in tr.items()
                           if k in ("position", "instrument", "expiry", "tranche", "lots", "choch_time", "entry_time", "entry_px", "sl",
                                    "exit_time", "exit_px", "exit_reason", "pts", "gross", "net", "mfe", "mae")}
                          | {"charges": round(tr["chg"]["total"], 2)})
    payload = lab.chart(bars, r, i0, i1, marks)
    if RB: payload["RB"] = [[[lab.ts(t[i]), round(ln[i], 2)] for i in range(i0, i1 + 1) if ln[i] is not None] for ln in RB]
    return dict(meta=dict(date=date, first_shown=show, inst=inst, instrument=name or by.get(f"{date} 09:15:00", ("NIFTY FUT",))[0],
                          expiry=expiry, strike=strike, right=right, tf=tf, code=code, strategy=spec["name"],
                          position=lab.position_cfg(st), rules=spec["rules"], lot_size=spec["lot_size"],
                          slippage_pts=st["slippage_pts"], warmup_from=first,
                          note="visualization only: the strategy applied to this instrument's own candles; FZ gates are not applied" + rule_note),
                chart=payload, trades=trades, skipped=skipped,
                net=round(sum(x["net"] for x in trades), 2))
