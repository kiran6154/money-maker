"""H1 gate audit of the frozen FZ v2 gates (ST7 on 1m, ST8 on 5m): what they skip vs keep by Foundation outcome.

    python h1_audit.py 1m      python h1_audit.py 5m

Writes to study/: h1_<tf>_<split>_<table>.csv, h1_<tf>_big_winners_skipped_<split>.csv, h1_<tf>_summary.json.
All gate variants below are pre-declared (nothing is chosen on OOS): the frozen gate as FZ trades it (TAKE + REENTER
positions), the frozen gate as a pure selection (Foundation's own outcome on the kept SETUPs), TAKE-only (as of the
SETUP bar), not-BLOCK (WATCH rows treated as taken) and, diagnostically, each block key inverted on its own (skip only
that key). Every variant gets the loser-filter metrics on IS and OOS; the four gates get the session-matched random
control percentile and the kept-vs-refused permutation p from fz_report.
"""
import sys, os, time, json
import h1_common as H
import pandas as pd, numpy as np

tf = sys.argv[1]
t0 = time.time()
d = H.load(tf)
raw, fzt = H.load_trades(tf)
S = {}
name = {"1m": "ST7 (1m, rooms, Strategy 1 rules prev_swing)", "5m": "ST8 (5m, rooms, Strategy 2 rules choch_candle)"}[tf]
S["gate"] = name
S["definitions"] = H.__doc__

# ---------------------------------------------------------------- consistency of the inputs
assert len(raw) == len(d), (len(raw), len(d))
assert set(raw.entry) == set(d.setup_i)
kept_setups = set(d.setup_i[d.kept == 1])
assert kept_setups == set(fzt.setup), "kept SETUPs must equal the FZ positions' SETUPs"
assert len(fzt) == len(kept_setups) == int(d.kept.sum())
S["counts"] = dict(setups=len(d), sessions_with_setup=int(d.session.nunique()), kept=int(d.kept.sum()),
                   positions=dict(fzt.gate.value_counts()), by_split=dict(d.split.value_counts()),
                   kept_by_split=dict(d.groupby("split").kept.sum()), cross_session_trades=int(d.cross_session.sum()),
                   open_at_end=int(d.open.astype(bool).sum()), warmup_flagged=int(d.in_warmup.sum()))
print(tf, S["counts"], flush=True)

# ---------------------------------------------------------------- gate variants (pre-declared)
def variants(x):
    v = {"frozen": x.kept == 1,
         "take_only": x.gate_at == "TAKE",
         "not_block": x.outcome_gate != "BLOCK"}
    for k in sorted(x.block_key[x.outcome_gate.isin(["BLOCK", "WATCH"])].unique()):
        v[f"skip_only:{k}"] = x.block_key != k          # invert one key: keep everything but that key
    v["take_or_reenter_at_setup"] = x.gate_at.isin(["TAKE", "REENTER"])
    return v

for sp in ("IS", "OOS"):
    x = d[d.split == sp].reset_index(drop=True)
    R = {"n": len(x)}
    # --- loser-filter metrics of every variant
    R["variants"] = {k: H.metrics(x, m) for k, m in variants(x).items()}
    # --- group tables
    tabs = {}
    for by in ("outcome_gate", "gate_at", "block_key", "read", "branch", "take_why", "hour_bin", "dir", "visit_bin",
               "zone_kind", "exit_reason", "pts_bucket", "hold_bucket", "cross_session", "pos_kind", "entered_read"):
        t = H.group_table(x, by)
        t.to_csv(os.path.join(H.STUDY, f"h1_{tf}_{sp}_by_{by}.csv"), index=False)
        tabs[by] = t.to_dict(orient="records")
    # two-way: read x outcome_gate, hour x outcome_gate (n / net / winners)
    for a, b in (("read", "outcome_gate"), ("hour_bin", "outcome_gate"), ("hour_bin", "kept"), ("pts_bucket", "outcome_gate"),
                 ("pts_bucket", "kept"), ("hold_bucket", "kept"), ("read", "kept"), ("exit_reason", "kept")):
        ct = x.pivot_table(index=a, columns=b, values="fnd_net", aggfunc=["count", "sum"], observed=True, fill_value=0)
        ct.columns = [f"{s}_{c}" for s, c in ct.columns]
        ct.round(2).to_csv(os.path.join(H.STUDY, f"h1_{tf}_{sp}_x_{a}_{b}.csv"))
    R["tables"] = tabs
    # --- big winners: where the gate skips them
    W = x[x.win == 1]
    R["winners"] = dict(n=len(W), net=round(float(W.fnd_net.sum()), 2), pts=round(float(W.fnd_pts.sum()), 2),
                        skipped_n=int(W.skipped.sum()), skipped_net=round(float(W.fnd_net[W.skipped == 1].sum()), 2),
                        skipped_pts=round(float(W.fnd_pts[W.skipped == 1].sum()), 2),
                        cross_session_n=int(W.cross_session.sum()), cross_session_pts=round(float(W.fnd_pts[W.cross_session == 1].sum()), 2),
                        by_outcome_gate=W.groupby("outcome_gate").agg(n=("win", "size"), pts=("fnd_pts", "sum"), net=("fnd_net", "sum")).round(2).to_dict(orient="index"),
                        by_block_key=W.groupby("block_key").agg(n=("win", "size"), pts=("fnd_pts", "sum"), net=("fnd_net", "sum")).round(2).to_dict(orient="index"),
                        by_read=W.groupby("read").agg(n=("win", "size"), pts=("fnd_pts", "sum"), skipped=("skipped", "sum")).round(2).to_dict(orient="index"),
                        by_hour=W.groupby("hour_bin").agg(n=("win", "size"), pts=("fnd_pts", "sum"), skipped=("skipped", "sum")).round(2).to_dict(orient="index"),
                        by_hold=W.groupby("hold_bucket", observed=True).agg(n=("win", "size"), pts=("fnd_pts", "sum"), skipped=("skipped", "sum"), kept_pts=("fnd_pts", lambda s: s[x.loc[s.index, "kept"] == 1].sum())).round(2).to_dict(orient="index"),
                        median_bars_held_kept=float(W.bars_held[W.kept == 1].median()) if (W.kept == 1).any() else None,
                        median_bars_held_skipped=float(W.bars_held[W.kept == 0].median()) if (W.kept == 0).any() else None)
    B = x[x.big == 1].sort_values("fnd_pts", ascending=False)
    R["big"] = dict(n=len(B), pts=round(float(B.fnd_pts.sum()), 2), net=round(float(B.fnd_net.sum()), 2),
                    skipped_n=int(B.skipped.sum()), skipped_pts=round(float(B.fnd_pts[B.skipped == 1].sum()), 2),
                    cross_session_n=int(B.cross_session.sum()), cross_session_skipped=int(B.cross_session[B.skipped == 1].sum()),
                    same_session_n=int((B.cross_session == 0).sum()), same_session_skipped=int(((B.cross_session == 0) & (B.skipped == 1)).sum()),
                    same_session_pts=round(float(B.fnd_pts[B.cross_session == 0].sum()), 2),
                    same_session_pts_skipped=round(float(B.fnd_pts[(B.cross_session == 0) & (B.skipped == 1)].sum()), 2),
                    by_block_key=B.groupby("block_key").agg(n=("big", "size"), pts=("fnd_pts", "sum"), cross=("cross_session", "sum")).round(2).to_dict(orient="index"),
                    by_read=B.groupby("read").agg(n=("big", "size"), pts=("fnd_pts", "sum"), skipped=("skipped", "sum")).round(2).to_dict(orient="index"),
                    by_hour=B.groupby("hour_bin").agg(n=("big", "size"), pts=("fnd_pts", "sum"), skipped=("skipped", "sum")).round(2).to_dict(orient="index"),
                    huge_n=int(x.huge.sum()), huge_skipped=int((x.huge * x.skipped).sum()), huge_cross=int((x.huge * x.cross_session).sum()))
    cols = ["setup_i", "time", "dir", "hour_bin", "read", "gate_at", "outcome_gate", "block_reason", "branch", "take_why",
            "visit_n", "fnd_pts", "fnd_net", "exit_reason", "bars_held", "exit_time", "cross_session", "mfe", "mae", "sl_dist_pts"]
    B[B.skipped == 1][cols].to_csv(os.path.join(H.STUDY, f"h1_{tf}_big_winners_skipped_{sp}.csv"), index=False)
    B[cols + ["kept"]].to_csv(os.path.join(H.STUDY, f"h1_{tf}_big_winners_all_{sp}.csv"), index=False)
    # --- the controls: random-control percentile and permutation p (fz_report), four gates
    raw_u = H.units(raw[raw.split == sp])
    fz_u = H.units(fzt[fzt.split == sp])
    C = {}
    kept_n, ref_n = x.fnd_net[x.kept == 1], x.fnd_net[x.kept == 0]
    C["frozen_fz_book"] = H.controls(raw_u, fz_u, kept_n, ref_n, f"H1|{tf}|{sp}|frozen")
    for k in ("frozen", "take_only", "not_block", "take_or_reenter_at_setup"):
        m = variants(x)[k]
        su = H.sel_units(raw_u, x.setup_i[m])
        C[f"{k}_selection"] = H.controls(raw_u, su, x.fnd_net[m], x.fnd_net[~m], f"H1|{tf}|{sp}|{k}|sel")
    R["controls"] = C
    S[sp] = R
    print(f"{tf} {sp}: n {len(x)} kept {int(x.kept.sum())} | Foundation net {x.fnd_net.sum():,.0f} | kept net {kept_n.sum():,.0f} "
          f"| FZ book {C['frozen_fz_book']['fz_book']['net']:,.0f} pct {C['frozen_fz_book']['control']['fz_pct']} "
          f"p {C['frozen_fz_book']['permutation']['p']} | selection pct {C['frozen_selection']['control']['fz_pct']}", flush=True)

S["run_s"] = round(time.time() - t0, 1)
H.dump(S, f"h1_{tf}_summary.json")
print("done", S["run_s"], "s")
