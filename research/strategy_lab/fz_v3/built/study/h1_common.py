"""H1 gate audit, shared code: loaders that normalise the two timeframes' feature tables to one schema, the
fz_report unit builders (positions from the trade tables), and the loser-filter metrics.

Definitions (fixed here, before any number was looked at):
  unit       one Foundation SETUP with its own engine trade (entry at the SETUP close, exit on the stop / next CHoCH /
             open at the data end; no session square-off), priced at lot 65 with 5 pts slippage per side and
             lab.trade_charges(ZERODHA_NFO_FUT) on the slipped prices (fnd_net = (pts - 10) x 65 - charges)
  kept       FZ held a position on this SETUP: a TAKE on the SETUP bar, or a REENTER whose R5 was this SETUP (possibly
             filled a bar later). 1m: st7_traded; 5m: fzpos_kind not null. Everything else is `skipped` (refused)
  loser      fnd_net <= 0 (costs included). winner = fnd_net > 0. pts-based variants use pts <= 0 / > 0
  precision  P(loser | skipped) = #(skipped & loser) / #skipped        (how clean the skip pile is)
  recall     P(skipped | loser) = #(skipped & loser) / #loser          (how many losers the gate removes)
  winner_skip P(skipped | winner) = #(skipped & winner) / #winner      (the cost: winners thrown away)
  lift       precision / base loser rate (1.0 = no better than skipping at random)
  big winner pts >= 50 (about 2,200 INR net on 1m); huge winner pts >= 100
  split      IS = SETUP date <= 2025-12-31; OOS = 2026-01-01 .. 2026-09-25 (the build's `split` column)
  hour_bin   fz_report.crosstabs bins with the ST7/ST8 clocks: '<09:25', '09' .. '15', '>=15:20' (bar open time)
"""
import sys, os, json
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
LAB = r"D:\office\stocks\workspace\money-maker\research\strategy_lab"
if LAB not in sys.path: sys.path.insert(0, LAB)
import fz_report                                                     # noqa: E402  (imports fz from the lab folder)
import pandas as pd, numpy as np                                     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../fz_v3
STUDY = os.path.join(ROOT, "study")
LOT, SLIP, DRAWS, SEED = 65, 5.0, 2000, "fz"
IS_END = "2025-12-31"
FIRST_BAR, LAST_DAY = "2021-10-01 09:15:00", "2026-09-25"
BIG, HUGE = 50.0, 100.0
PTS_BINS = [-np.inf, -50, -20, 0, 20, 50, 100, np.inf]
PTS_LABELS = ["<=-50", "(-50,-20]", "(-20,0]", "(0,20]", "(20,50]", "(50,100]", ">100"]
HOLD_BINS = [0, 5, 15, 30, 60, 120, 375, np.inf]
HOLD_LABELS = ["1-5", "6-15", "16-30", "31-60", "61-120", "121-375", ">375"]


def hour_bin(hm, ow="09:25", nf="15:20"):
    return "<" + ow if hm < ow else ">=" + nf if hm >= nf else hm[:2]


def load(tf):
    """Normalised per-SETUP table for '1m' or '5m'. Columns: setup_i, time, date, session, split, dir, hhmm, hour_bin,
    read, gate_at, outcome_gate, block_reason, branch, take_why, watch_kind, visit_n, zone_kind, entered_read,
    leave_vol_ok, kept, pos_kind, fnd_pts, fnd_net, fnd_gross, fnd_charges, win, exit_reason, bars_held, exit_time,
    cross_session, open, sl_dist_pts, mfe, mae, in_warmup (5m only, else 0)."""
    if tf == "1m":
        f = pd.read_parquet(os.path.join(ROOT, "minute", "setup_features.parquet"))
        assert len(f) == 5326 and f.traded.all()
        d = pd.DataFrame(dict(
            setup_i=f.setup_i, time=f.time, date=f.date.astype(str), session=f.session_i, split=f.split, dir=f.dir,
            hhmm=f.time.str[11:16], read=f.card_read, gate_at=f.st7_gate, outcome_gate=f.st7_outcome_gate,
            block_reason=f.st7_block_reason, branch=f.st7_branch, take_why=f.st7_take_why, watch_kind=f.st7_watch_kind,
            visit_n=f.card_visit_n, zone_kind=f.st7_zone_kind, entered_read=f.st7_entered_read,
            leave_vol_ok=f.st7_leave_vol_ok, kept=f.st7_traded.astype(int), pos_kind=None,
            fnd_pts=f.fnd_pts, fnd_net=f.fnd_net, fnd_gross=f.fnd_gross, fnd_charges=f.fnd_charges,
            exit_reason=f.fnd_exit_reason, bars_held=f.fnd_bars_held, exit_time=f.fnd_exit_time, open=f.fnd_open,
            sl_dist_pts=f.sl_dist_pts, mfe=f.fnd_mfe, mae=f.fnd_mae, in_warmup=0))
        d["pos_kind"] = np.where(d.kept == 1, d.outcome_gate, None)   # TAKE or REENTER when kept
        assert (d.loc[d.kept == 1, "outcome_gate"].isin(["TAKE", "REENTER"])).all()
    elif tf == "5m":
        f = pd.read_parquet(os.path.join(ROOT, "5minute", "features.parquet"))
        assert len(f) == 1012 and f.fnd_traded.all()
        d = pd.DataFrame(dict(
            setup_i=f.setup_i, time=f.time, date=f.date.astype(str), session=f.session_idx, split=f.split, dir=f.dir,
            hhmm=f.hhmm, read=f.fz_read, gate_at=f.fz_gate, outcome_gate=f.fzpost_outcome_gate,
            block_reason=f.fz_block_reason, branch=f.fz_branch, take_why=f.fz_take_why, watch_kind=f.fz_watch_kind,
            visit_n=f.fz_visit_n, zone_kind=f.fz_zone_kind, entered_read=f.fz_entered_read,
            leave_vol_ok=f.fz_leave_vol_ok, kept=f.fzpos_kind.notna().astype(int), pos_kind=f.fzpos_kind,
            fnd_pts=f.fnd_pts, fnd_net=f.fnd_net_inr, fnd_gross=f.fnd_gross_inr, fnd_charges=f.fnd_charges_inr,
            exit_reason=f.fnd_exit_reason, bars_held=f.fnd_bars_held, exit_time=f.fnd_exit_time, open=f.fnd_open,
            sl_dist_pts=f.sl_dist_pts, mfe=f.fnd_mfe_pts, mae=f.fnd_mae_pts, in_warmup=f.in_warmup.astype(int)))
    else:
        raise ValueError(tf)
    d["hour_bin"] = d.hhmm.map(hour_bin)
    d["win"] = (d.fnd_net > 0).astype(int)
    d["win_pts"] = (d.fnd_pts > 0).astype(int)
    d["loser"] = 1 - d["win"]
    d["skipped"] = 1 - d["kept"]
    d["cross_session"] = (d.exit_time.astype(str).str[:10] != d.date).astype(int)
    d["big"] = (d.fnd_pts >= BIG).astype(int)
    d["huge"] = (d.fnd_pts >= HUGE).astype(int)
    d["pts_bucket"] = pd.cut(d.fnd_pts, PTS_BINS, labels=PTS_LABELS, right=True)
    d["hold_bucket"] = pd.cut(d.bars_held, HOLD_BINS, labels=HOLD_LABELS, right=True)
    d["visit_bin"] = d.visit_n.map(lambda v: "none" if pd.isna(v) else ("4+" if v >= 4 else str(int(v))))
    for c in ("read", "gate_at", "outcome_gate", "block_reason", "branch", "take_why", "watch_kind", "zone_kind",
              "entered_read", "pos_kind"):
        d[c] = d[c].where(d[c].notna(), "none").astype(str)
    d["block_key"] = np.where(d.outcome_gate == "BLOCK", "BLOCK:" + d.block_reason,
                              np.where((d.outcome_gate == "WATCH") & (d.block_reason != "none"),
                                       "WATCH:" + d.block_reason, d.outcome_gate))
    assert set(d.split) == {"IS", "OOS"}
    return d.reset_index(drop=True)


def load_trades(tf):
    """(raw, fzt): the Foundation trade table and the FZ position table with the columns the unit builder needs."""
    if tf == "1m":
        r = pd.read_parquet(os.path.join(ROOT, "minute", "trades.parquet"))
        z = pd.read_parquet(os.path.join(ROOT, "minute", "fz_trades.parquet"))
        raw = pd.DataFrame(dict(entry=r.entry, setup=r.entry, gate="RAW", entry_time=r.entry_time, exit_time=r.exit_time,
                                net=r.net, gross=r.gross, charges=r.charges, open=r.open.astype(bool), pts=r.pts))
        fzt = pd.DataFrame(dict(entry=z.entry, setup=z.setup_i, gate=z.gate, entry_time=z.entry_time, exit_time=z.exit_time,
                                net=z.net, gross=z.gross, charges=z.charges, open=z.open.astype(bool), pts=z.pts))
    else:
        r = pd.read_parquet(os.path.join(ROOT, "5minute", "trades.parquet"))
        z = pd.read_parquet(os.path.join(ROOT, "5minute", "fz_trades.parquet"))
        raw = pd.DataFrame(dict(entry=r.entry_i, setup=r.entry_i, gate="RAW", entry_time=r.entry_time, exit_time=r.exit_time,
                                net=r.net_inr, gross=r.gross_inr, charges=r.charges_inr, open=r.open.astype(bool), pts=r.pts))
        fzt = pd.DataFrame(dict(entry=z.entry_i, setup=z.setup_i, gate=z.gate, entry_time=z.entry_time, exit_time=z.exit_time,
                                net=z.net_inr, gross=z.gross_inr, charges=z.charges_inr, open=z.open.astype(bool), pts=z.pts))
    for x in (raw, fzt):
        x["day"] = x.entry_time.astype(str).str[:10]
        x["split"] = np.where(x.day <= IS_END, "IS", "OOS")
    return raw, fzt


def units(df):
    """fz_report.units over a trade frame: one record per position with entry, setup, gate, day, net, gross, charges,
    slip (2 x 5 x 65 = 650) and open. `gross` is the lab's gross after slippage, so gross + slip is the price move."""
    legs = [dict(_entry=int(x.entry), _setup=int(x.setup), _gate=x.gate, entry_time=str(x.entry_time),
                 exit_time=str(x.exit_time), net=float(x.net), gross=float(x.gross), chg=dict(total=float(x.charges)),
                 open=bool(x.open)) for x in df.itertuples(index=False)]
    return fz_report.units(legs, LOT, SLIP)


def metrics(d, kept):
    """Loser-filter metrics of a gate over frame d (kept = boolean Series aligned with d)."""
    kept = kept.astype(bool); sk = ~kept
    n, nk, ns = len(d), int(kept.sum()), int(sk.sum())
    L, W = d.loser.astype(bool), d.win.astype(bool)
    nl, nw = int(L.sum()), int(W.sum())
    sl_, sw_ = int((sk & L).sum()), int((sk & W).sum())
    base = nl / n if n else None
    prec = sl_ / ns if ns else None
    out = dict(n=n, kept_n=nk, skipped_n=ns, losers=nl, winners=nw,
               kept_net=round(float(d.fnd_net[kept].sum()), 2), skipped_net=round(float(d.fnd_net[sk].sum()), 2),
               kept_mean=round(float(d.fnd_net[kept].mean()), 2) if nk else None,
               skipped_mean=round(float(d.fnd_net[sk].mean()), 2) if ns else None,
               kept_pts=round(float(d.fnd_pts[kept].sum()), 2), skipped_pts=round(float(d.fnd_pts[sk].sum()), 2),
               kept_win_rate=round(float(W[kept].mean()), 4) if nk else None,
               skipped_win_rate=round(float(W[sk].mean()), 4) if ns else None,
               base_loser_rate=round(base, 4) if base is not None else None,
               precision=round(prec, 4) if prec is not None else None,
               recall=round(sl_ / nl, 4) if nl else None,
               winner_skip=round(sw_ / nw, 4) if nw else None,
               lift=round(prec / base, 3) if (prec is not None and base) else None,
               big_total=int(d.big.sum()), big_skipped=int((sk & d.big.astype(bool)).sum()),
               big_pts_total=round(float(d.fnd_pts[d.big.astype(bool)].sum()), 2),
               big_pts_skipped=round(float(d.fnd_pts[sk & d.big.astype(bool)].sum()), 2),
               huge_total=int(d.huge.sum()), huge_skipped=int((sk & d.huge.astype(bool)).sum()),
               winner_net_total=round(float(d.fnd_net[W].sum()), 2), winner_net_skipped=round(float(d.fnd_net[sk & W].sum()), 2),
               loser_net_total=round(float(d.fnd_net[L].sum()), 2), loser_net_skipped=round(float(d.fnd_net[sk & L].sum()), 2))
    out["kept_minus_skipped_mean"] = (round(out["kept_mean"] - out["skipped_mean"], 2)
                                      if out["kept_mean"] is not None and out["skipped_mean"] is not None else None)
    return out


def group_table(d, by, kept_col="kept"):
    """Per-group Foundation outcome with the kept / skipped split: n, kept, net, mean, win rate, pts, big winners."""
    g = d.groupby(by, observed=True, dropna=False)
    t = pd.DataFrame(dict(
        n=g.size(), kept=g[kept_col].sum(), kept_share=g[kept_col].mean().round(4),
        net=g.fnd_net.sum().round(2), mean_net=g.fnd_net.mean().round(2), win_rate=g.win.mean().round(4),
        pts=g.fnd_pts.sum().round(2), mean_pts=g.fnd_pts.mean().round(2),
        winners=g.win.sum(), big=g.big.sum(), huge=g.huge.sum(),
        kept_net=d[d[kept_col] == 1].groupby(by, observed=True, dropna=False).fnd_net.sum().round(2),
        skipped_net=d[d[kept_col] == 0].groupby(by, observed=True, dropna=False).fnd_net.sum().round(2),
        kept_mean=d[d[kept_col] == 1].groupby(by, observed=True, dropna=False).fnd_net.mean().round(2),
        skipped_mean=d[d[kept_col] == 0].groupby(by, observed=True, dropna=False).fnd_net.mean().round(2),
        kept_win_rate=d[d[kept_col] == 1].groupby(by, observed=True, dropna=False).win.mean().round(4),
        skipped_win_rate=d[d[kept_col] == 0].groupby(by, observed=True, dropna=False).win.mean().round(4),
        big_skipped=d[d[kept_col] == 0].groupby(by, observed=True, dropna=False).big.sum()))
    for c in ("kept_net", "skipped_net", "big_skipped"): t[c] = t[c].fillna(0)
    return t.reset_index()


def controls(raw_u, fz_u, kept_nets, refused_nets, tag):
    """The brief's two tests for a gate over one window: fz_report.random_control (session-matched random gate, 2000
    draws, seed 'fz') on the FZ units against the Foundation pool, and fz_report.permutation_p (kept vs refused
    Foundation trades, 2000 shuffles). Also the bridge and both books."""
    rc = fz_report.random_control(raw_u, fz_u, DRAWS, SEED, tag)
    pp = fz_report.permutation_p(list(kept_nets), list(refused_nets), DRAWS, SEED, tag)
    br = fz_report.bridge(raw_u, fz_u) if fz_u else None
    return dict(control=rc, permutation=pp, bridge=br, raw_book=fz_report.book(raw_u, LOT),
                fz_book=fz_report.book(fz_u, LOT) if fz_u else None)


def sel_units(raw_u, keep_entries):
    """Selection-only FZ book: Foundation's own units on the kept SETUPs (no REENTER exit change)."""
    ke = set(int(x) for x in keep_entries)
    return [dict(u, gate="SEL") for u in raw_u if u["entry"] in ke]


def dump(obj, name):
    with open(os.path.join(STUDY, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
