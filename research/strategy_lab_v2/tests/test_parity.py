"""v2 against v1, trade for trade: the same strategy, window and type through v1's lab.run_variant and v2's core.run_type
must give the same priced trades (times, prices, exit reasons, pts, gross, charges, net, mfe / mae) and the same skipped
signals. v1 is imported read-only from ../strategy_lab (nothing there is written).

    python tests/test_parity.py                 # the default cases (a few minutes: v1 is the slow side)
    python tests/test_parity.py ST1 OPT_NATIVE  # one strategy / type
    pytest tests/test_parity.py
"""
import os, sys, json, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V1 = os.path.join(os.path.dirname(HERE), "strategy_lab")
sys.path.insert(0, HERE)
import core

# (code, date_from, date_to, timeframe override, underlying override, square_off override ('keep' = the strategy's))
CASES = [
    ("ST1", "2026-08-26", "2026-09-25", None, None, "keep"),
    ("ST2", "2026-07-08", "2026-08-25", None, None, "keep"),
    ("ST3", "2026-09-01", "2026-09-25", None, None, None),
    ("ST4", "2026-08-26", "2026-09-25", None, "INDEX", "keep"),
    ("ST1", "2026-09-01", "2026-09-25", "15minute", None, "keep"),
    # managed exits: stop / targets in R / trail (ST9, ST10), stop and reverse (ST11, ST12), positional (ST15-ST18)
    ("ST9", "2026-08-26", "2026-09-25", None, None, "keep"),
    ("ST10", "2026-07-08", "2026-08-25", None, None, "keep"),
    ("ST11", "2026-08-26", "2026-09-25", None, None, "keep"),
    ("ST12", "2026-07-08", "2026-09-25", None, None, "keep"),
    ("ST15", "2026-08-26", "2026-09-25", None, None, "keep"),
    ("ST16", "2026-07-08", "2026-09-25", None, None, "keep"),
    ("ST17", "2026-08-26", "2026-09-25", None, "INDEX", "keep"),
    ("ST18", "2026-09-01", "2026-09-25", None, None, "keep"),
    ("ST11", "2026-09-01", "2026-09-25", None, None, None),
    # rainbow ribbon (futures only)
    ("ST29", "2026-07-01", "2026-09-25", None, None, "keep"),
    ("ST30", "2026-01-05", "2026-06-30", None, None, "keep"),
    ("ST29", "2026-09-01", "2026-09-25", None, None, None),
    # CHoCH to CHoCH put retest (options via futures, 5-minute): PCR on / off x stops on close / touch, index or futures signals
    ("ST25", "2026-06-23", "2026-09-14", None, None, "keep"),
    ("ST25", "2026-06-23", "2026-09-14", None, "FUT", "keep"),
    ("ST26", "2026-06-23", "2026-09-14", None, None, "keep"),
    ("ST27", "2026-06-23", "2026-09-14", None, None, "keep"),
    ("ST28", "2026-01-05", "2026-09-25", None, "FUT", "keep"),
]
FIELDS = ("position", "opt_type", "instrument", "strike", "expiry", "entry_time", "entry_px", "exit_time", "exit_px",
          "exit_reason", "open", "lots", "tranche", "sl", "pts", "gross", "net", "mfe", "mae")


def _v1():
    if V1 not in sys.path: sys.path.insert(1, V1)
    cwd = os.getcwd(); os.chdir(V1)
    try:
        import lab
    finally:
        os.chdir(cwd)
    return lab


def v1_run(lab, code, typ, frm, to, tf, und, sq):
    n = int(code[2:])
    spec = json.load(open(os.path.join(V1, "strategies", f"strategy_{n}.json"), encoding="utf-8"))
    row = next(r for r in lab.type_rows(spec) if r["variant"] == typ)
    tf = tf or spec["timeframe"]; und = und or spec.get("underlying", "FUT")
    pos = lab.position_of(spec)
    if sq != "keep": pos = dict(pos, square_off=sq)
    stp = dict(row, id=0, timeframe=tf, data_file=lab.tf_file("fut", tf), spot_file=lab.tf_file("spot", tf), underlying=und,
               signal_file=lab.tf_file("spot" if und == "INDEX" else "fut", tf), date_from=frm, date_to=to, period="t",
               warmup_days=spec["warmup_days"], positions="BOTH", position_json=json.dumps(pos, sort_keys=True))
    cs = json.load(open(os.path.join(V1, "config", "charges.json"), encoding="utf-8"))[row["charge_code"]]
    if spec["rules"]["entry_rule"] == "c2c_v1":
        import c2c
        return c2c.run_variant(stp, cs)
    if spec["rules"]["entry_rule"] == "rainbow_v1":
        import rainbow
        return rainbow.run_variant(stp, cs)
    return lab.run_variant(stp, cs)


def v2_run(code, typ, frm, to, tf, und, sq):
    mod = core.load_strategies()[code]
    if core.allowed(mod, typ, und or mod.SPEC.get("underlying", "FUT"), tf or mod.SPEC["timeframe"]): return None
    spec = mod.SPEC
    tf = tf or spec["timeframe"]; und = und or spec.get("underlying", "FUT")
    s = core.position_of(spec)["square_off"] if sq == "keep" else sq
    return core.run_type(core.context(mod, typ, tf, und, s, frm, to))


def norm2(x):
    d = dict(x, entry_time=core.tstr(x["entry_time"]), exit_time=core.tstr(x["exit_time"]))
    return tuple(d.get(k) for k in FIELDS) + (round(x["chg"]["total"], 6),)


def norm1(x):
    return tuple(x.get(k) for k in FIELDS) + (round(x["chg"]["total"], 6),)


def compare(code, typ, frm, to, tf=None, und=None, sq="keep", lab=None):
    lab = lab or _v1()
    t0 = time.time(); a = v1_run(lab, code, typ, frm, to, tf, und, sq); t1 = time.time()
    b = v2_run(code, typ, frm, to, tf, und, sq); t2 = time.time()
    if b is None:                                     # v2 refuses the type up front (v1 returns a refusal row)
        why = {str(x.get("why")) for r in a.values() for x in r["skipped"]}
        ok = all(not r["trades"] for r in a.values())
        print(f"{code} {typ:<15} refused by both: {ok} ({'; '.join(why)[:80]})")
        return ok
    bad = []
    assert set(a) == set(b), (sorted(a), sorted(b))
    n = 0
    for ch in a:
        ta, tb = [norm1(x) for x in a[ch]["trades"]], [norm2(x) for x in b[ch]["trades"]]
        n += len(ta)
        if ta != tb:
            k = next((i for i, (p, q) in enumerate(zip(ta, tb)) if p != q), min(len(ta), len(tb)))
            bad.append(f"{ch}: {len(ta)} vs {len(tb)} trades; first difference at {k}:\n  v1 {ta[k] if k < len(ta) else None}\n"
                       f"  v2 {tb[k] if k < len(tb) else None}")
        wa = sorted(str(x.get("why")) for x in a[ch]["skipped"])
        wb = sorted(str(x.get("why")) for x in b[ch]["skipped"])
        if wa != wb: bad.append(f"{ch}: skipped differ ({len(wa)} vs {len(wb)}): {sorted(set(wa) ^ set(wb))[:3]}")
    print(f"{code} {typ:<15} {frm}..{to} tf={tf or '-'} und={und or '-'} sq={sq}: {len(a)} choices, {n} trades, "
          f"v1 {t1 - t0:.1f}s v2 {t2 - t1:.2f}s  {'OK' if not bad else 'DIFF'}")
    for x in bad[:6]: print("   ", x)
    return not bad


def test_parity():
    lab = _v1()
    ok = all([compare(c, typ, f, t, tf, u, s, lab) for c, f, t, tf, u, s in CASES for typ, _, _ in core.TYPES
              if not (u == "INDEX" and typ == "OPT_NATIVE")])
    assert ok


if __name__ == "__main__":
    args = sys.argv[1:]
    lab = _v1()
    oks = []
    for c, f, t, tf, u, s in CASES:
        if args and args[0] != c: continue
        for typ, _, _ in core.TYPES:
            if len(args) > 1 and args[1] != typ: continue
            if u == "INDEX" and typ == "OPT_NATIVE": continue
            oks.append(compare(c, typ, f, t, tf, u, s, lab))
    print("ALL OK" if all(oks) else "DIFFERENCES FOUND")
    sys.exit(0 if all(oks) else 1)
