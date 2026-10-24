"""The Summary page's numbers: every strategy's stored trades, filtered by date and summed (or grouped by year / month /
week), in points and in rupees. Read-only over results/<code>/<run>/<type>/<choice>.json; nothing is recomputed.

Per trade the stored result holds pts (points per lot after the slippage on both sides), lots, gross (rupees after
slippage), charges and net; the run holds the lot size and the slippage per side. From those:
    raw points      = pts + 2 x slippage                  (before slippage)
    slippage points = 2 x slippage                        (both sides)
    raw rupees      = raw points x lot size x lots
    slippage rupees = slippage points x lot size x lots
    net rupees      = gross - charges
Profit / loss = the sum over winning / losing trades (after slippage; in rupees after charges too).
"""
import datetime as dt
import glob
import json
import os

import core

RES = core.RESULTS
_BODY = {}


def _json(path):
    m = os.path.getmtime(path)
    if path not in _BODY or _BODY[path][0] != m:
        while len(_BODY) > 300: del _BODY[next(iter(_BODY))]
        _BODY[path] = (m, json.load(open(path, encoding="utf-8")))
    return _BODY[path][1]


def runs(code):
    """[meta] of a strategy's stored runs."""
    return [_json(p) for p in sorted(glob.glob(os.path.join(RES, code, "*", "meta.json")))]


def pick_run(code, typ, mode):
    """The run used for a strategy: 'longest' (the widest date span with this type) or 'default' (the SPEC's default
    backtest, else the longest)."""
    ok = [m for m in runs(code) if m.get("types", {}).get(typ, {}).get("status") == "ok" and m["types"][typ].get("choices")]
    if not ok: return None
    if mode == "default":
        spec = core.load_strategies()[code].SPEC
        lab = next((b["label"] for b in spec.get("backtests", []) if b.get("default")), None)
        d = [m for m in ok if m.get("label") == lab]
        if d: return d[0]
    return max(ok, key=lambda m: (core.dnum(m["date_to"]) - core.dnum(m["types"][typ].get("date_from") or m["date_from"]), m["date_to"]))


def pick_choice(meta, typ, code):
    ch = list(meta["types"][typ]["choices"])
    if typ == "FUT" or len(ch) == 1: return ch[0]
    spec = core.load_strategies()[code].SPEC; want = "W-" + str(spec.get("options", {}).get("strike_default"))
    return want if want in ch else ch[0]


def period(day, group):
    d = dt.date.fromisoformat(day)
    if group == "year": return day[:4]
    if group == "month": return day[:7]
    if group == "week": y, w, _ = d.isocalendar(); return f"{y}-W{w:02d}"
    if group == "day": return day
    return "all"


def metrics(rows, C, lot, slip):
    n = len(rows)
    lots = [float(r[C["lots"]] or 1) for r in rows]
    pts = [float(r[C["pts"]]) for r in rows]
    net = [float(r[C["net"]]) for r in rows]
    gross = [float(r[C["gross"]]) for r in rows]
    chg = [float(r[C["charges"]]) for r in rows]
    raw = [p + 2 * slip for p in pts]
    eq = peak = dd = 0.0
    for v in net: eq += v; peak = max(peak, eq); dd = min(dd, eq - peak)
    eqp = peakp = ddp = 0.0
    for v in pts: eqp += v; peakp = max(peakp, eqp); ddp = min(ddp, eqp - peakp)
    wp = sum(p for p in pts if p > 0); lp = sum(p for p in pts if p <= 0)
    wr = sum(v for v in net if v > 0); lr = sum(v for v in net if v <= 0)
    return dict(trades=n, wins=sum(p > 0 for p in pts), win_pct=round(100 * sum(p > 0 for p in pts) / n, 1) if n else 0,
                pts=dict(raw=round(sum(raw), 2), slippage=round(-2 * slip * n, 2), net=round(sum(pts), 2), profit=round(wp, 2),
                         loss=round(lp, 2), pf=round(wp / -lp, 2) if lp < 0 else None, avg=round(sum(pts) / n, 2) if n else 0,
                         max_dd=round(ddp, 2)),
                inr=dict(raw=round(sum(r_ * lot * l_ for r_, l_ in zip(raw, lots))), slippage=round(-sum(2 * slip * lot * l_ for l_ in lots)),
                         gross=round(sum(gross)), charges=round(-sum(chg)), net=round(sum(net)), profit=round(wr), loss=round(lr),
                         pf=round(wr / -lr, 2) if lr < 0 else None, avg=round(sum(net) / n) if n else 0, max_dd=round(dd)))


def summary(typ="FUT", mode="longest", frm=None, to=None, year=None, month=None, group="none", code=None):
    """dict(rows=[one per strategy (or per strategy x period when code is given)], ...): see the module text."""
    mods = core.load_strategies()
    codes = [code] if code else sorted(mods, key=lambda c: int(c[2:]))
    out = []
    for c in codes:
        meta = pick_run(c, typ, mode)
        if not meta: continue
        ch = pick_choice(meta, typ, c)
        f = os.path.join(RES, c, meta["run"], meta["types"][typ]["choices"][ch]["file"])
        if not os.path.exists(f): continue
        b = _json(f); C = {k: i for i, k in enumerate(b["cols"])}
        spec = mods[c].SPEC                                   # older results do not carry the lot size / slippage: the SPEC's
        lot = float(b.get("lot_size") or spec.get("lot_size", 65))
        slip = float(b["slippage_pts"] if b.get("slippage_pts") is not None else spec["types"][typ]["slippage_pts"])
        rows = []
        for r in b["trades"]:
            day = str(r[C["entry_time"]])[:10]
            if frm and day < frm: continue
            if to and day > to: continue
            if year and day[:4] != str(year): continue
            if month and int(day[5:7]) != int(month): continue
            rows.append((day, r))
        base = dict(code=c, name=mods[c].SPEC.get("name", ""), run=meta["run"], label=meta.get("label"), type=typ, choice=ch,
                    span=[meta["types"][typ].get("date_from") or meta["date_from"], meta["date_to"]], lot=lot, slip=slip)
        if code and group != "none":
            groups = {}
            for day, r in rows: groups.setdefault(period(day, group), []).append(r)
            for k in sorted(groups): out.append(dict(base, period=k, **metrics(groups[k], C, lot, slip)))
        else:
            out.append(dict(base, period="all", **metrics([r for _, r in rows], C, lot, slip)))
    return dict(type=typ, mode=mode, frm=frm, to=to, year=year, month=month, group=group, code=code, rows=out)
