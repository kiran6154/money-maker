"""Foundation-Zone gate (entry_rule fz_v1 / fz_v2): the family module behind ST5-ST8 (v1 lab.run_fz / fz_payload).

The FZ rules themselves are v1's fz.py / fz_exec.py / fz_report.py, copied to strategies/fz_lib/. The only edit is
in fz.py: the live zones are indexed by price, so a bar looks at the zones near its close instead of every zone ever
born (same decisions; tests/test_parity.py compares the trades and the whole payload with v1). This module does what
v1's lab did around them:
  gate     fz.run() over the window's candles with the engine's frozen view, positions through fz_exec.opener; FZ's
           positions replace Foundation's (TAKE = Foundation's own trade, REENTER = fz_exec.simulate from the fill bar)
  payload  per priced choice: the SETUP ledger joined with Foundation's and FZ's priced outcome, watches, cross-tabs,
           bridge, random control, permutation test, books and flags (fz_report)
Memory starts at config/data.json fz_memory_from (v1: its history_from), so every window is a date slice of one run
from there; backtests resolve against the sessions from that date (v1's sessions()).
Futures and Options (via futures) on futures signals only: the thresholds are futures points.
"""
import os, sys, json, hashlib
import numpy as np
import core

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fz_lib"))
import lib_fz as fz, lib_fz_exec as fz_exec, lib_fz_report as fz_report   # v1's modules, copied (unique names)

ENTRY_RULES = ("fz_v1", "fz_v2")
FIRST_SESSION = core.DATA.get("fz_memory_from")
FZ_NATIVE_WHY = "FZ thresholds are futures points; no native-option unit rule in v1"
INDEX_WHY_FZ = "FZ runs on futures candles (its thresholds are futures points)"
FZ_TRADE_KEYS = ("gate", "reenter_reason", "zone_id", "fill_used")
ENGINE_TRADE_KEYS = ("entry", "exit", "exit_px", "dir", "choch", "sl", "pts", "open", "exit_reason")
LEDGER_COLS = ("time", "dir", "choch_time", "zone_id", "zone_kind", "band_lo", "band_hi", "visit_n", "this_bars", "this_vol",
               "first_bars", "first_vol", "vol_na", "first_vol_na", "read", "left_id", "in_id", "session_bar",
               "level_in_band", "gate", "outcome_gate", "block_reason", "branch", "take_why", "refused", "entered_zone_id",
               "entered_visit_n", "entered_read", "leave_vol_ok", "leave_kind", "watch_kind", "watch_band_id",
               "watch_outcome", "reenter_reason", "fill_used", "fill_time", "fill_delay_bars", "edge_dist_pts",
               "armed_bars", "rearmed_bars", "sl_bar", "fnd_pts", "fnd_exit_reason", "fnd_exit_time", "fnd_net", "fz_kind",
               "fz_entry_time", "fz_pts", "fz_exit_reason", "fz_exit_time", "fz_net")
WATCH_COLS = ("opened_time", "band_id", "dir", "kind", "opened_by_read", "setup_time", "outcome", "outcome_time",
              "armed_time", "last_armed_time")
Z_COLS = ("time", "zone_id", "visit_n", "this_bars", "this_vol", "first_bars", "first_vol", "read", "left_id", "out_run",
          "vol_na", "gap_pts", "session_bar", "wick_depth", "in_id", "first_vol_na")
ZONE_COLS = ("id", "kind", "lo", "hi", "born")


def refuse(typ, und, tf, spec):
    """Why this strategy does not run a type / signal source / timeframe, or None."""
    if typ == "OPT_NATIVE": return FZ_NATIVE_WHY
    if und == "INDEX": return INDEX_WHY_FZ
    if tf not in spec["fz"]: return f"no FZ thresholds for {tf}"
    return None


def signals(bars, spec):
    """Foundation on these candles (the chart and the CHoCH list); the gate replaces its trades in gate()."""
    return core.foundation(bars, spec["rules"])


_HASH = {}
def fz_hash():
    if "h" not in _HASH:
        h = hashlib.sha1()
        for f in ("lib_fz.py", "lib_fz_exec.py", "lib_fz_report.py"):
            h.update(open(os.path.join(os.path.dirname(fz.__file__), f), "rb").read().replace(b"\r\n", b"\n"))
        _HASH["h"] = h.hexdigest()[:16]
    return _HASH["h"]


_FM = {}
def fm_by_day():
    """front_month per session (day number) from the 1-minute futures file (the last row of the session wins, as v1)."""
    if "d" not in _FM:
        b = core.load_file(core.FUT1)
        fm = b.extra.get("front_month")
        d = {}
        if fm is not None:
            for day, f in zip(b.day.tolist(), fm.tolist()): d[day] = int(float(f or 0))
        _FM["d"] = d
    return _FM["d"]


def v1_view(sig):
    """v2 Signals as the v1 engine.run() dict fz_exec / fz read: swings, setups, CHoCHs, protected level, trades."""
    sw = [dict(k="H" if k == 1 else "L", bar=int(b), p=float(p), conf=int(c)) for k, b, p, c in zip(sig.sk, sig.sb, sig.sp, sig.sc)]
    setups = [dict(i=int(i), dir="up" if d == 1 else "down", ch=int(ch)) for i, d, ch in zip(sig.ui, sig.ud, sig.uch)]
    chs = [dict(i=int(i), dir="up" if d == 1 else "down", lvl=float(lv)) for i, d, lv in zip(sig.qi, sig.qd, sig.qlvl)]
    prot = [None if np.isnan(v) else float(v) for v in sig.prot]
    return dict(sw=sw, setups=setups, chs=chs, prot=prot, trades=sig.trades())


def gate(ctx, fut, s0, sig):
    """(Signals with FZ's positions as its trades, F) for one window (v1 lab.run_fz)."""
    spec, tf = ctx["spec"], ctx["tf"]
    cfg = fz.thresholds(spec["fz"][tf])
    rules = spec["rules"]
    touch = rules["break_mode"] == "touch"
    t = core.tstrs(fut.t).tolist()
    fm = fm_by_day()
    bars = dict(t=t, o=fut.o.tolist(), h=fut.h.tolist(), l=fut.l.tolist(), c=fut.c.tolist(), v=fut.v.tolist(),
                fm_na=[fm.get(int(dd), 0) == 0 or vv == 0 for dd, vv in zip(fut.day.tolist(), fut.v.tolist())],
                atr14=core._atr(fut.h, fut.l, fut.c, spec["options"]["atr_period"]).tolist())
    r = v1_view(sig)
    view = fz_exec.view(r)
    run = lambda b: fz.run(b, view, cfg, core.TF_MIN[tf], s0, fz_exec.opener(b, r, rules["sl_rule"], touch))
    out = run(bars)
    trades = fz_exec.build_trades(bars, r, out, rules["sl_rule"], touch)
    L = out["ledger"]
    eng = lambda xs: [tuple(x[k] for k in ENGINE_TRADE_KEYS) for x in xs if x["entry"] >= s0]
    if L and not any(x["gate"] in ("WATCH", "BLOCK") for x in L) and eng(trades) == eng(r["trades"]):
        raise ValueError(f"{spec['code']}: FZ row produced Foundation's trades unchanged")
    na = run(dict(bars, fm_na=[True] * len(t)))
    sess, k = [], -1
    for i, x in enumerate(t):
        k += i == 0 or x[:10] != t[i - 1][:10]; sess.append(k)
    shown = [x for x in trades if x["entry"] >= s0]
    xt = fz_report.crosstabs(L, [w for w in out["watches"] if w["opened_at"] >= s0], shown, out["stats"], out["card"][s0:],
                             sorted({x[:10] for x in t[s0:]}), cfg)
    all_na = dict(gates={g: sum(1 for x in na["ledger"] if x["outcome_gate"] == g) for g in fz_report.GATES},
                  positions={g: sum(1 for d in na["decisions"] if d[0] == g and d[1] >= s0) for g in ("TAKE", "REENTER")})
    F = dict(out=out, trades=trades, raw=r["trades"], cfg=cfg, sess=sess, xt=xt, all_na=all_na, memory_start=t[0][:10], t=t)
    return sig.with_trades(trades), F


def _str_times(legs):
    return [dict(x, entry_time=core.tstr(x["entry_time"]), exit_time=core.tstr(x["exit_time"])) for x in legs]


def payload(ctx, fut, s0, F, legs, raw_legs):
    """summary['fz'] for one priced choice (v1 lab.fz_payload)."""
    out, cfg, t, xt = F["out"], F["cfg"], F["t"], F["xt"]
    lot = ctx["lot_size"]
    legs, raw_legs = _str_times(legs), _str_times(raw_legs)
    fzu, rawu = fz_report.units(legs, lot, ctx["slippage_pts"]), fz_report.units(raw_legs, lot, ctx["slippage_pts"])
    suffix = {t_: s_ for t_, s_, _ in core.TYPES}[ctx["type"]]       # v1 seeds with the type's code (ST5, ST5_FB)
    tag = f"{ctx['spec']['code']}{suffix}|{ctx['period']}"
    L = out["ledger"]
    traded = {x.get("setup_i", x["entry"]) for x in F["trades"]}
    kept = [u["net"] for u in rawu if u["entry"] in traded]
    refused = [u["net"] for u in rawu if u["entry"] not in traded]
    T = lambda i: None if i is None else t[i]
    eng, pos = {x["entry"]: x for x in F["raw"]}, {}
    for x in F["trades"]: pos.setdefault(x.get("setup_i", x["entry"]), x)
    rnet, fnet = {u["entry"]: u["net"] for u in rawu}, {u["entry"]: u["net"] for u in fzu}
    r2 = lambda v: round(v, 2) if isinstance(v, float) else v
    rows = []
    for x in L:
        e, p = eng.get(x["i"]), pos.get(x["i"])
        d = dict(x, time=t[x["i"]], choch_time=T(x["choch_i"]), fill_time=T(x["fill_bar"]),
                 fnd_pts=e and e["pts"], fnd_exit_reason=e and e["exit_reason"], fnd_exit_time=e and t[e["exit"]],
                 fnd_net=rnet.get(x["i"]), fz_kind=p and p["gate"], fz_entry_time=p and t[p["entry"]],
                 fz_pts=p and p["pts"], fz_exit_reason=p and p["exit_reason"], fz_exit_time=p and t[p["exit"]],
                 fz_net=p and fnet.get(p["entry"]))
        rows.append([r2(d[cc]) for cc in LEDGER_COLS])
    W = [[T(w["opened_at"]), w["band_id"], w["dir"], w["kind"], w["opened_by_read"], T(w["setup_i"]), w["outcome"],
          T(w["outcome_bar"]), T(w["armed_at"]), T(w["last_armed_at"])] for w in out["watches"] if w["opened_at"] >= s0]
    books = dict(fz=fz_report.book(fzu, lot), raw=fz_report.book(rawu, lot))
    ctl = fz_report.random_control(rawu, fzu, cfg["control_draws"], cfg["control_seed"], tag)
    perm = fz_report.permutation_p(kept, refused, cfg["control_draws"], cfg["control_seed"], tag)
    flags = fz_report.sample_flags(books["fz"]["n"], books["fz"]["sd"], books["fz"]["weeks"], xt["active_sessions"], lot)
    g, ps = xt["gates"], xt["positions"]
    headline = dict(setups=xt["setups"], take=g["TAKE"], watch=g["WATCH"], block=g["BLOCK"], reenter=g["REENTER"],
                    at_setup=xt["gates_at_setup"],
                    take_trades=ps["TAKE"], reenter_trades=ps["REENTER"], priced=len(fzu), control_pct=ctl["fz_pct"],
                    control_p_beat=ctl["p_beat"], perm_p=perm["p"], active_sessions=xt["active_sessions"],
                    sessions=xt["sessions"], pf_t=flags["pf_t"])
    legend = dict(Z=Z_COLS, ZONES=ZONE_COLS, read=fz.READS, trade_fields={str(25 + k): f for k, f in enumerate(FZ_TRADE_KEYS)},
                  gates=dict(TAKE="Foundation's own position on this SETUP (same fill, stop and exit)",
                             REENTER="a position from a watch after a confirmed leave of its band: fill at the close of the "
                                     "bar R1-R5 hold, Foundation's stop at that bar, plus the band_reclaim exit",
                             WATCH="no position now; a watch on the band that may REENTER later",
                             BLOCK="no position and no watch (block_reason)"),
                  outcome_gate="the gate a SETUP ended with: REENTER when a REENTER used this SETUP (on its bar or a later "
                               "one), else its gate at the SETUP bar (column gate); the gate tables and headline counts "
                               "use it, headline.at_setup the gate at the SETUP bar",
                  permutation="kept = Foundation's trades on the SETUPs FZ held a position on (TAKE or REENTER), refused = "
                              "Foundation's other trades",
                  hour_bins=list(xt["by_hour"]), units="net / gross / charges in INR per lot; pts in points; "
                                                        "fnd_* / fz_* are diagnostics joined after the gate ran")
    return dict(fz_hash=fz_hash(), memory_start=F["memory_start"], window_start=t[s0][:10], same_sample="file_start",
                thresholds=cfg, headline=headline, stats=xt, counters=out["stats"], bridge=fz_report.bridge(rawu, fzu),
                control=ctl, permutation=perm, books=books, flags=flags, all_na=F["all_na"],
                ledger=dict(cols=LEDGER_COLS, rows=rows), watches=dict(cols=WATCH_COLS, rows=W), legend=legend)
