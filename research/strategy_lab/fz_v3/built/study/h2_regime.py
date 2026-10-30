"""H2 "sideways = CHoCH without break" study (FZ v3 brief, 2026-09-29).

One timeframe per process (--tf minute | 5minute). Reads the data-build folders fz_v3/<tf>/ (never lab.sessions()).

    --stage is    recompute the regime features per SETUP from events + bars (uniform definitions on both timeframes,
                  cross-checked against the build's columns), describe Foundation P&L by regime and hour on IS, run the
                  pre-registered gate grid on IS, select a candidate on IS only. Writes h2_<tf>_*.csv/json.
    --stage oos   read the IS choice, evaluate the chosen gate and the pre-registered CHoCH-count gates (k = 2, 3, 4)
                  once on OOS (and on IS with the final 2000 draws), plus the OOS bucket tables with IS-defined edges.

PRE-REGISTERED DEFINITIONS (fixed before any number was read)
  Unit = Foundation SETUP with its own engine trade (entry at the SETUP close), outcome = net INR at lot 65 after
  5 pts slippage per side and lab.trade_charges (the build's fnd_net / fnd_net_inr), win = net > 0, loser = net <= 0.
  Events = engine CHoCH / BOS events with bar i <= k (the SETUP bar), in engine order (BOS before CHoCH on one bar).
  Regime features at SETUP bar k (all as-of, bars <= k only):
    n_choch_since_bos      CHoCH events after the last BOS (all CHoCHs when no BOS yet). The SETUP's own CHoCH counts
                           (it is at ch < k), so 1 = own CHoCH only, 0 = a BOS came after the own CHoCH before k,
                           >= 2 = "CHoCH, CHoCH, no BOS" (the user's sideways).
    n_choch_since_bos_today  the same count restricted to events of the SETUP's session (a BOS in an earlier session
                           does not reset today's count; the session start does).
    n_flip_since_bos       of the CHoCHs since the last BOS, the ones that flipped the trend.
    n_bos_since_choch      BOS events after the last CHoCH (>= 1 = the move already broke structure before the SETUP).
    bars_since_choch       k - ch (the SETUP's own CHoCH bar).
    bars_since_bos         k - bar of the last BOS (NaN when none yet); last_bos_agree = its direction == SETUP dir.
    alt_dir6               direction changes between consecutive events among the last 6 events (0..5).
    alt_kind6              kind changes (BOS<->CHoCH) among the last 6 events (0..5).
    n_choch_1h / n_bos_1h / n_choch_3h / n_bos_3h   events with k - N < i <= k, N = 60/180 bars (1m) or 12/36 (5m).
    range_1h_atr, range_3h_atr   (max high - min low) over bars max(session start, k-N+1) .. k, / atr14[k]
                           (same session only: the overnight gap never enters).
    range_since_choch_atr  the same over bars ch .. k.
    session_range_atr      the same over the session's bars up to k; pos_in_session_range = (close - low)/range.
    er_1h                  Kaufman efficiency ratio |c[k]-c[k-N]| / sum|c[j]-c[j-1]| over the last N bars of the
                           session (N = 1h, at least 5 bars; NaN otherwise). Descriptive only, not in the grid.
  Gate grid (skip = do not take the SETUP):
    choch rule: skip when n_choch_since_bos >= kc (scope all) or n_choch_since_bos_today >= kc (scope today),
                kc in {2, 3, 4}; or no choch rule.
    range rule: skip when range_W_atr <= r, W in {1h, 3h, since_choch}, r = the IS quantile q in {0.1, 0.2, 0.3,
                0.4, 0.5} of that range over IS SETUPs (the ATR multiple is recorded); or no range rule.
    combine: OR / AND when both rules are present.
  Gate metrics: kept / skipped n, net sums and means, diff = kept mean - skipped mean, win rates, loser recall
    (skipped losers / all losers), skip precision (skipped losers / skipped), winners skipped share (skipped winners /
    all winners) and winner-net skipped share (net of skipped winners / net of all winners), session-matched random
    control percentile (fz_report.random_control: per session, as many Foundation trades drawn at random as the gate
    kept; kept net's percentile among the draws), and the kept-vs-skipped permutation p (fz_report.permutation_p).
  Selection on IS (before OOS is touched): eligible = kept share >= 0.30 and skipped n >= 100. Score = IS control
    percentile, tie-break = diff. Among the top 5 by score, the chosen cell is the first whose diff > 0 in at least
    3 of the 4 IS year blocks (2021-10..2022, 2023, 2024, 2025); if none, no gate survives IS.
  Grid draws 400 (random control and permutation); finalists 2000. Seed prefix "h2", tag "<tf>|<window>|<cell>".
"""
import sys, os, json, time, bisect, argparse, itertools
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
LAB = "D:/office/stocks/workspace/money-maker/research/strategy_lab"
sys.path.insert(0, LAB)
import numpy as np, pandas as pd
import fz_report

ROOT = "C:/Users/Admin/AppData/Local/Temp/claude/D--office-stocks-workspace-money-maker/f477107e-5dd8-4bd5-8444-6fb6c59c6ba7/scratchpad/fz_v3"
OUT = ROOT + "/study"
FIRST_BAR, LAST_BAR_DATE = "2021-10-01 09:15:00", "2026-09-25"
IS_END, OOS_START, OOS_END = "2025-12-31", "2026-01-01", "2026-09-25"
LOT, SLIP_INR = 65, 650.0
GRID_DRAWS, FINAL_DRAWS, SEED = 400, 2000, "h2"
YEAR_BLOCKS = [("2021-10-01", "2022-12-31"), ("2023-01-01", "2023-12-31"), ("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31")]
MIN_KEPT_SHARE, MIN_SKIPPED = 0.30, 100

CFG = {
    "minute": dict(feat="setup_features.parquet", bars="bars.parquet", events="events.parquet", bar_i="bar_i",
                   sess="session_i", ch="ch", net="fnd_net", pts="fnd_pts", gross="fnd_gross", charges="fnd_charges",
                   win="win", traded="traded", exit_time="fnd_exit_time", opn="fnd_open", reason="fnd_exit_reason",
                   bph=60, ev_seq="event_i", build_cols=dict(n_choch_since_bos="reg_n_choch_since_bos",
                                                             n_bos_since_choch="reg_n_bos_since_choch",
                                                             alt_dir6="reg_alt6", n_flip_since_bos="reg_n_flip_since_bos")),
    "5minute": dict(feat="features.parquet", bars="bars.parquet", events="events.parquet", bar_i="i", sess="session_idx",
                    ch="choch_i", net="fnd_net_inr", pts="fnd_pts", gross="fnd_gross_inr", charges="fnd_charges_inr",
                    win="fnd_win", traded="fnd_traded", exit_time="fnd_exit_time", opn="fnd_open", reason="fnd_exit_reason",
                    bph=12, ev_seq="seq", build_cols=dict(n_choch_since_bos="n_choch_since_bos",
                                                          n_bos_since_choch="n_bos_since_choch",
                                                          alt_kind6="alternations_last6",
                                                          n_flip_since_bos="n_flip_choch_since_bos")),
}


def rss_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().peak_wset / 1e6, 1)
    except Exception:
        return None


# ---------------------------------------------------------------- load + regime features
def load(tf):
    c = CFG[tf]
    D = f"{ROOT}/{tf}"
    feat = pd.read_parquet(f"{D}/{c['feat']}")
    bars = pd.read_parquet(f"{D}/{c['bars']}", columns=[c["bar_i"], "datetime", c["sess"], "session_bar", "high", "low", "close", "atr14"])
    assert bars["datetime"].iloc[0] == FIRST_BAR, bars["datetime"].iloc[0]
    assert bars["datetime"].iloc[-1][:10] == LAST_BAR_DATE, bars["datetime"].iloc[-1]
    assert (bars[c["bar_i"]].values == np.arange(len(bars))).all()
    ev = pd.read_parquet(f"{D}/{c['events']}", columns=[c["ev_seq"], "i", "kind", "dir", "flip"]).sort_values(c["ev_seq"])
    return feat, bars, ev


def regime_features(tf, feat, bars, ev):
    c = CFG[tf]
    N1, N3 = c["bph"], 3 * c["bph"]
    H, L, C, A = (bars[x].values.astype(float) for x in ("high", "low", "close", "atr14"))
    SESS = bars[c["sess"]].values; SB = bars["session_bar"].values
    ev_i = ev["i"].values.astype(int); ev_kind = ev["kind"].values; ev_dir = ev["dir"].values
    ev_flip = np.array([bool(x) if x is not None and x == x else False for x in ev["flip"].values])
    ev_sess = SESS[ev_i]
    is_ch = ev_kind == "CHoCH"
    ch_i = ev_i[is_ch]                         # for counts in the last N bars
    bos_i = ev_i[~is_ch]
    rows = []
    for k, ch, d, sess in zip(feat["setup_i"].values.astype(int), feat[c["ch"]].values.astype(int), feat["dir"].values, feat[c["sess"]].values):
        n = bisect.bisect_right(ev_i, k)
        kinds, dirs, flips, sesses = ev_kind[:n], ev_dir[:n], ev_flip[:n], ev_sess[:n]
        bos_idx = np.flatnonzero(kinds == "BOS"); ch_idx = np.flatnonzero(kinds == "CHoCH")
        last_bos = int(bos_idx[-1]) if len(bos_idx) else -1
        last_ch = int(ch_idx[-1]) if len(ch_idx) else -1
        since_bos = kinds[last_bos + 1:]
        n_choch_since_bos = int((since_bos == "CHoCH").sum())
        n_flip_since_bos = int(flips[last_bos + 1:].sum())
        n_bos_since_choch = int((kinds[last_ch + 1:] == "BOS").sum())
        # today's count: events of this session only, after the last BOS of this session (or from the session start)
        tod = np.flatnonzero(sesses == sess)
        if len(tod):
            t0 = int(tod[0]); tk, td = kinds[t0:], None
            tb = np.flatnonzero(tk == "BOS")
            start = int(tb[-1]) + 1 if len(tb) else 0
            n_choch_since_bos_today = int((tk[start:] == "CHoCH").sum())
            n_events_today = len(tk); n_choch_today = int((tk == "CHoCH").sum())
        else:
            n_choch_since_bos_today = n_events_today = n_choch_today = 0
        last6_dir, last6_kind = dirs[max(0, n - 6):n], kinds[max(0, n - 6):n]
        alt_dir6 = int(sum(1 for a, b in zip(last6_dir[:-1], last6_dir[1:]) if a != b))
        alt_kind6 = int(sum(1 for a, b in zip(last6_kind[:-1], last6_kind[1:]) if a != b))
        cnt = lambda arr, N: int(bisect.bisect_right(arr, k) - bisect.bisect_right(arr, k - N))
        s0 = k - SB[k]
        rng = lambda a, b: (H[a:b + 1].max() - L[a:b + 1].min())
        a = A[k] if A[k] > 0 else np.nan
        lo1, lo3 = max(s0, k - N1 + 1), max(s0, k - N3 + 1)
        srange = rng(s0, k)
        nN = min(N1, k - s0)
        if nN >= 5:
            cc = C[k - nN:k + 1]
            path = np.abs(np.diff(cc)).sum()
            er = abs(cc[-1] - cc[0]) / path if path > 0 else np.nan
        else:
            er = np.nan
        rows.append(dict(
            n_choch_since_bos=n_choch_since_bos, n_choch_since_bos_today=n_choch_since_bos_today,
            n_flip_since_bos=n_flip_since_bos, n_bos_since_choch=n_bos_since_choch,
            bars_since_choch=int(k - ch), bars_since_bos=(k - ev_i[last_bos]) if last_bos >= 0 else np.nan,
            last_bos_agree=(1 if dirs[last_bos] == d else 0) if last_bos >= 0 else np.nan,
            alt_dir6=alt_dir6, alt_kind6=alt_kind6, n_events_today=n_events_today, n_choch_today=n_choch_today,
            n_choch_1h=cnt(ch_i, N1), n_bos_1h=cnt(bos_i, N1), n_choch_3h=cnt(ch_i, N3), n_bos_3h=cnt(bos_i, N3),
            range_1h_atr=rng(lo1, k) / a, range_3h_atr=rng(lo3, k) / a, range_since_choch_atr=rng(ch, k) / a,
            session_range_atr=srange / a, pos_in_session_range=((C[k] - L[s0:k + 1].min()) / srange) if srange > 0 else np.nan,
            er_1h=er))
    R = pd.DataFrame(rows, index=feat.index)
    # cross-check against the build's own columns (definitional audit, reported not asserted)
    checks = {}
    for mine, theirs in c["build_cols"].items():
        if theirs in feat.columns:
            checks[f"{mine}=={theirs}"] = int((R[mine].values == feat[theirs].values.astype(int)).sum()) / len(R)
    return R, checks


def frame(tf, feat, R):
    c = CFG[tf]
    df = pd.DataFrame(dict(
        setup_i=feat["setup_i"].astype(int), time=feat["time"], date=feat["date"].astype(str), sess=feat[c["sess"]].astype(int),
        session_bar=feat["session_bar"].astype(int), hour=feat["time"].str[11:13], split=feat["split"], dir=feat["dir"],
        atr14=feat["atr14"], net=feat[c["net"]].astype(float), pts=feat[c["pts"]].astype(float),
        gross=feat[c["gross"]].astype(float), charges=feat[c["charges"]].astype(float), win=feat[c["win"]].astype(int),
        reason=feat[c["reason"]], exit_day=feat[c["exit_time"]].astype(str).str[:10], opn=feat[c["opn"]].astype(int),
        traded=feat[c["traded"]].astype(int)))
    assert (df["traded"] == 1).all() and df["net"].notna().all()
    assert ((df["win"] == 1) == (df["net"] > 0)).all()
    return pd.concat([df, R], axis=1)


# ---------------------------------------------------------------- stats + gate evaluation
def units(d, gate):
    return [dict(entry=int(r.setup_i), setup=int(r.setup_i), gate=gate, day=r.date, exit_day=r.exit_day, legs=1, net=float(r.net),
                 gross=float(r.gross), charges=float(r.charges), slip=SLIP_INR, open=bool(r.opn)) for r in d.itertuples()]


def stats(d):
    n = len(d)
    if n == 0: return dict(n=0)
    return dict(n=n, net_sum=round(d.net.sum(), 2), net_mean=round(d.net.mean(), 2), net_median=round(d.net.median(), 2),
                win_rate=round(d.win.mean(), 4), pts_sum=round(d.pts.sum(), 2), pts_mean=round(d.pts.mean(), 3),
                stop_share=round((d.reason == "stop_loss").mean(), 4), cost_mean=round((d.charges + SLIP_INR).mean(), 2),
                sessions=int(d.sess.nunique()))


def bucket_table(d, col, bins, tf, win, draws, labels=None):
    """Foundation outcome by bucket of `col`, each bucket vs its complement with a permutation p."""
    x = d[col]
    if bins is None:
        cat = x.astype("object").where(x.notna(), "nan")
    else:
        cat = pd.cut(x, bins=bins, labels=labels, include_lowest=True, right=True).astype("object").where(x.notna(), "nan")
    rows = []
    for b in (list(dict.fromkeys(labels)) if labels else sorted(cat.unique(), key=lambda v: (str(v) == "nan", v if isinstance(v, (int, float, np.integer, np.floating)) else str(v)))):
        m = cat == b
        if m.sum() == 0: continue
        s = stats(d[m]); comp = d[~m]
        p = fz_report.permutation_p(list(comp.net), list(d[m].net), draws, SEED, f"{tf}|{win}|{col}|{b}") if len(comp) and m.sum() else {}
        rows.append(dict(col=col, bucket=str(b), **s, diff_vs_rest=p.get("diff"), perm_p=p.get("p")))
    return rows


def evaluate(d, skip, draws, tf, win, cell):
    kept, skp = d[~skip], d[skip]
    out = dict(cell=cell, window=win, n=len(d), n_kept=len(kept), n_skipped=len(skp), kept_share=round(len(kept) / len(d), 4),
               net_all=round(d.net.sum(), 2), net_kept=round(kept.net.sum(), 2), net_skipped=round(skp.net.sum(), 2),
               mean_kept=round(kept.net.mean(), 2) if len(kept) else None, mean_skipped=round(skp.net.mean(), 2) if len(skp) else None,
               win_rate_kept=round(kept.win.mean(), 4) if len(kept) else None, win_rate_skipped=round(skp.win.mean(), 4) if len(skp) else None,
               pts_kept=round(kept.pts.sum(), 2), pts_skipped=round(skp.pts.sum(), 2),
               sessions_kept=int(kept.sess.nunique()), sessions_all=int(d.sess.nunique()))
    losers, winners = d.net <= 0, d.net > 0
    out.update(loser_recall=round((skip & losers).sum() / losers.sum(), 4) if losers.sum() else None,
               skip_precision=round((skip & losers).sum() / skip.sum(), 4) if skip.sum() else None,
               winners_skipped_share=round((skip & winners).sum() / winners.sum(), 4) if winners.sum() else None,
               winner_net_skipped_share=round(d.net[skip & winners].sum() / d.net[winners].sum(), 4) if winners.sum() else None,
               stop_share_kept=round((kept.reason == "stop_loss").mean(), 4) if len(kept) else None,
               stop_share_skipped=round((skp.reason == "stop_loss").mean(), 4) if len(skp) else None)
    if len(kept) and len(skp):
        ctl = fz_report.random_control(units(d, "RAW"), units(kept, "TAKE"), draws, SEED, f"{tf}|{win}|{cell}")
        perm = fz_report.permutation_p(list(kept.net), list(skp.net), draws, SEED, f"{tf}|{win}|{cell}")
        out.update(control_pct=ctl["fz_pct"], control_p_beat=ctl["p_beat"], control_p5=ctl["p5"], control_p50=ctl["p50"],
                   control_p95=ctl["p95"], control_draws=draws, control_capped=ctl["capped"], diff=perm["diff"], perm_p=perm["p"])
    else:
        out.update(control_pct=None, control_p_beat=None, control_p5=None, control_p50=None, control_p95=None, control_draws=draws,
                   control_capped=None, diff=None, perm_p=None)
    return out


def rule_mask(d, kc, scope, rw, r, combine):
    m_ch = None if kc is None else ((d["n_choch_since_bos"] if scope == "all" else d["n_choch_since_bos_today"]) >= kc)
    m_r = None if rw is None else (d[f"range_{rw}_atr"] <= r)
    if m_ch is None and m_r is None: return None
    if m_ch is None: return m_r.values
    if m_r is None: return m_ch.values
    return (m_ch | m_r).values if combine == "OR" else (m_ch & m_r).values


def cell_name(kc, scope, rw, r, combine):
    a = f"choch>={kc}[{scope}]" if kc is not None else ""
    b = f"range_{rw}<={r:.3f}atr" if rw is not None else ""
    return f"{a} {combine} {b}".strip() if a and b else (a or b)


def config_of(kc, scope, rw, r, combine, tf):
    rules = []
    if kc is not None: rules.append(dict(feature="n_choch_since_bos" + ("_today" if scope == "today" else ""), op=">=", value=int(kc)))
    if rw is not None: rules.append(dict(feature=f"range_{rw}_atr", op="<=", value=round(float(r), 4)))
    return dict(timeframe=tf, action="skip_setup_when", combine=(combine if len(rules) == 2 else "single"), rules=rules,
                bars_per_hour=CFG[tf]["bph"], range_scope="same session, bars <= SETUP bar, / atr14 at the SETUP bar")


# ---------------------------------------------------------------- stages
def stage_is(tf):
    t0 = time.time(); laps = {}
    feat, bars, ev = load(tf); laps["load"] = round(time.time() - t0, 1)
    R, checks = regime_features(tf, feat, bars, ev); laps["features"] = round(time.time() - t0, 1)
    df = frame(tf, feat, R)
    df.to_parquet(f"{OUT}/h2_{tf}_setups.parquet"); df.to_csv(f"{OUT}/h2_{tf}_setups.csv", index=False)
    del bars
    IS = df[df.split == "IS"].reset_index(drop=True)
    assert IS.date.max() <= IS_END and (df[df.split == "OOS"].date.min() >= OOS_START)
    # ---- descriptive tables on IS
    q = lambda col: [round(float(IS[col].quantile(p)), 4) for p in (0.2, 0.4, 0.6, 0.8)]
    edges = {col: q(col) for col in ("range_1h_atr", "range_3h_atr", "range_since_choch_atr", "session_range_atr", "er_1h")}
    tables = []
    tables += bucket_table(IS, "n_choch_since_bos", [-0.5, 0.5, 1.5, 2.5, 3.5, 99], tf, "IS", 1000, ["0", "1", "2", "3", "4+"])
    tables += bucket_table(IS, "n_choch_since_bos_today", [-0.5, 0.5, 1.5, 2.5, 3.5, 99], tf, "IS", 1000, ["0", "1", "2", "3", "4+"])
    tables += bucket_table(IS, "n_flip_since_bos", [-0.5, 0.5, 1.5, 2.5, 99], tf, "IS", 1000, ["0", "1", "2", "3+"])
    tables += bucket_table(IS, "n_bos_since_choch", [-0.5, 0.5, 1.5, 99], tf, "IS", 1000, ["0", "1", "2+"])
    bph = CFG[tf]["bph"]
    tables += bucket_table(IS, "bars_since_choch", [0, bph / 12, bph / 4, bph / 2, bph, 1e9], tf, "IS", 1000, ["<=5min", "5-15min", "15-30min", "30-60min", ">60min"])
    tables += bucket_table(IS, "bars_since_bos", [-1, bph / 2, bph, 3 * bph, 1e9], tf, "IS", 1000, ["<=30min", "30-60min", "1-3h", ">3h"])
    tables += bucket_table(IS, "last_bos_agree", None, tf, "IS", 1000)
    tables += bucket_table(IS, "alt_dir6", None, tf, "IS", 1000)
    tables += bucket_table(IS, "alt_kind6", None, tf, "IS", 1000)
    tables += bucket_table(IS, "n_choch_1h", [-0.5, 0.5, 1.5, 2.5, 99], tf, "IS", 1000, ["0", "1", "2", "3+"])
    tables += bucket_table(IS, "n_choch_3h", [-0.5, 1.5, 3.5, 5.5, 99], tf, "IS", 1000, ["0-1", "2-3", "4-5", "6+"])
    tables += bucket_table(IS, "n_bos_1h", [-0.5, 0.5, 2.5, 99], tf, "IS", 1000, ["0", "1-2", "3+"])
    for col in edges:
        e = edges[col]
        tables += bucket_table(IS, col, [-1e9] + e + [1e9], tf, "IS", 1000, [f"q1<={e[0]}", f"q2<={e[1]}", f"q3<={e[2]}", f"q4<={e[3]}", f"q5>{e[3]}"])
    tables += bucket_table(IS, "hour", None, tf, "IS", 1000)
    pd.DataFrame(tables).to_csv(f"{OUT}/h2_{tf}_IS_buckets.csv", index=False)
    # hour x sideways
    IS["sideways2"] = (IS.n_choch_since_bos >= 2).astype(int)
    hx = IS.groupby(["hour", "sideways2"]).agg(n=("net", "size"), net_sum=("net", "sum"), net_mean=("net", "mean"), win_rate=("win", "mean"), pts_mean=("pts", "mean")).reset_index()
    hx.to_csv(f"{OUT}/h2_{tf}_IS_hour_x_sideways.csv", index=False)
    # by direction x sideways, by exit reason x sideways
    dx = IS.groupby(["dir", "sideways2"]).agg(n=("net", "size"), net_mean=("net", "mean"), win_rate=("win", "mean")).reset_index()
    rx = IS.groupby(["sideways2", "reason"]).agg(n=("net", "size"), net_mean=("net", "mean")).reset_index()
    # year blocks x sideways
    yb = []
    for a, b in YEAR_BLOCKS:
        w = IS[(IS.date >= a) & (IS.date <= b)]
        for s in (0, 1):
            ww = w[w.sideways2 == s]
            yb.append(dict(block=f"{a}..{b}", sideways2=s, **stats(ww)))
    laps["descriptive"] = round(time.time() - t0, 1)
    # ---- the grid on IS
    grid = []
    rqs = {rw: {p: round(float(IS[f"range_{rw}_atr"].quantile(p)), 4) for p in (0.1, 0.2, 0.3, 0.4, 0.5)} for rw in ("1h", "3h", "since_choch")}
    cells = []
    for kc, scope in [(None, None)] + list(itertools.product((2, 3, 4), ("all", "today"))):
        for rw in (None, "1h", "3h", "since_choch"):
            for p in ((None,) if rw is None else (0.1, 0.2, 0.3, 0.4, 0.5)):
                r = None if rw is None else rqs[rw][p]
                for combine in (("OR", "AND") if (kc is not None and rw is not None) else ("-",)):
                    if kc is None and rw is None: continue
                    cells.append((kc, scope, rw, r, p, combine))
    for kc, scope, rw, r, p, combine in cells:
        m = rule_mask(IS, kc, scope, rw, r, combine)
        e = evaluate(IS, m, GRID_DRAWS, tf, "IS", cell_name(kc, scope, rw, r, combine))
        e.update(kc=kc, scope=scope, rw=rw, r=r, rq=p, combine=combine)
        grid.append(e)
    G = pd.DataFrame(grid)
    G.to_csv(f"{OUT}/h2_{tf}_IS_grid.csv", index=False)
    laps["grid"] = round(time.time() - t0, 1)
    # ---- selection on IS only
    elig = G[(G.kept_share >= MIN_KEPT_SHARE) & (G.n_skipped >= MIN_SKIPPED) & G.control_pct.notna()].copy()
    elig = elig.sort_values(["control_pct", "diff"], ascending=False)
    top = elig.head(5)
    chosen, top_rows = None, []
    for _, row in top.iterrows():
        m = rule_mask(IS, row.kc if pd.notna(row.kc) else None, row.scope if isinstance(row.scope, str) else None,
                      row.rw if isinstance(row.rw, str) else None, row.r if pd.notna(row.r) else None, row.combine)
        blocks = []
        for a, b in YEAR_BLOCKS:
            w = (IS.date >= a) & (IS.date <= b)
            kept, skp = IS.net[w & ~m], IS.net[w & m]
            blocks.append(dict(block=f"{a}..{b}", n_kept=int(len(kept)), n_skipped=int(len(skp)),
                               diff=round(kept.mean() - skp.mean(), 2) if len(kept) and len(skp) else None))
        ok = sum(1 for x in blocks if x["diff"] is not None and x["diff"] > 0)
        top_rows.append(dict(cell=row.cell, control_pct=row.control_pct, diff=row["diff"], kept_share=row.kept_share, blocks=blocks, blocks_positive=ok))
        if chosen is None and ok >= 3:
            chosen = dict(cell=row.cell, kc=None if pd.isna(row.kc) else int(row.kc), scope=row.scope if isinstance(row.scope, str) else None,
                          rw=row.rw if isinstance(row.rw, str) else None, r=None if pd.isna(row.r) else float(row.r),
                          rq=None if pd.isna(row.rq) else float(row.rq), combine=row.combine, blocks=blocks, blocks_positive=ok,
                          is_control_pct_400=row.control_pct, is_diff_400=row["diff"])
    summary = dict(tf=tf, stage="is", is_window=[IS.date.min(), IS.date.max()], n_is=len(IS), n_oos=int((df.split == "OOS").sum()),
                   feature_checks_vs_build=checks, quantile_edges=edges, range_thresholds=rqs, grid_cells=len(G),
                   grid_pct_summary=dict(median=float(G.control_pct.median()), share_ge95=float((G.control_pct >= 95).mean()),
                                         share_ge90=float((G.control_pct >= 90).mean()), share_le5=float((G.control_pct <= 5).mean())),
                   eligible_cells=len(elig), top5=top_rows, chosen=chosen, chosen_config=None if chosen is None else
                   config_of(chosen["kc"], chosen["scope"], chosen["rw"], chosen["r"], chosen["combine"], tf),
                   selection_rule="eligible: kept_share>=0.30 & n_skipped>=100; score = IS control pct (400 draws), tie diff; "
                                  "first of top-5 with diff>0 in >=3 of 4 IS year blocks",
                   hour_x_sideways=hx.to_dict("records"), dir_x_sideways=dx.to_dict("records"), reason_x_sideways=rx.to_dict("records"),
                   yearblock_x_sideways=yb, laps=laps, peak_rss_mb=rss_mb())
    json.dump(summary, open(f"{OUT}/h2_{tf}_IS_summary.json", "w"), indent=1, default=str)
    print(json.dumps(dict(tf=tf, checks=checks, chosen=chosen and chosen["cell"], grid=len(G), laps=laps, rss=rss_mb()), default=str))


def stage_oos(tf):
    t0 = time.time()
    S = json.load(open(f"{OUT}/h2_{tf}_IS_summary.json"))
    df = pd.read_parquet(f"{OUT}/h2_{tf}_setups.parquet")
    IS, OOS = df[df.split == "IS"].reset_index(drop=True), df[df.split == "OOS"].reset_index(drop=True)
    assert OOS.date.min() >= OOS_START and OOS.date.max() <= OOS_END and IS.date.max() <= IS_END
    # pre-registered cells: the CHoCH-count gates k = 2, 3, 4 (scope all and today) + the IS-chosen cell
    cells = [(k, s, None, None, "-") for k in (2, 3, 4) for s in ("all", "today")]
    ch = S["chosen"]
    if ch is not None:
        cells.append((ch["kc"], ch["scope"], ch["rw"], ch["r"], ch["combine"]))
    rows = []
    for kc, scope, rw, r, combine in cells:
        name = cell_name(kc, scope, rw, r, combine)
        for win, d in (("IS", IS), ("OOS", OOS)):
            m = rule_mask(d, kc, scope, rw, r, combine)
            e = evaluate(d, m, FINAL_DRAWS, tf, win, name)
            e.update(kc=kc, scope=scope, rw=rw, r=r, combine=combine, chosen=(ch is not None and name == ch["cell"]))
            rows.append(e)
            # per-year blocks on IS for the record, OOS as one block
    F = pd.DataFrame(rows); F.to_csv(f"{OUT}/h2_{tf}_final.csv", index=False)
    # OOS bucket tables with the IS-defined edges (descriptive, computed once)
    tables = []
    tables += bucket_table(OOS, "n_choch_since_bos", [-0.5, 0.5, 1.5, 2.5, 3.5, 99], tf, "OOS", 1000, ["0", "1", "2", "3", "4+"])
    tables += bucket_table(OOS, "n_choch_since_bos_today", [-0.5, 0.5, 1.5, 2.5, 3.5, 99], tf, "OOS", 1000, ["0", "1", "2", "3", "4+"])
    tables += bucket_table(OOS, "n_bos_since_choch", [-0.5, 0.5, 1.5, 99], tf, "OOS", 1000, ["0", "1", "2+"])
    tables += bucket_table(OOS, "alt_dir6", None, tf, "OOS", 1000)
    for col, e in S["quantile_edges"].items():
        tables += bucket_table(OOS, col, [-1e9] + e + [1e9], tf, "OOS", 1000, [f"q1<={e[0]}", f"q2<={e[1]}", f"q3<={e[2]}", f"q4<={e[3]}", f"q5>{e[3]}"])
    tables += bucket_table(OOS, "hour", None, tf, "OOS", 1000)
    pd.DataFrame(tables).to_csv(f"{OUT}/h2_{tf}_OOS_buckets.csv", index=False)
    OOS = OOS.copy(); OOS["sideways2"] = (OOS.n_choch_since_bos >= 2).astype(int)
    hx = OOS.groupby(["hour", "sideways2"]).agg(n=("net", "size"), net_sum=("net", "sum"), net_mean=("net", "mean"), win_rate=("win", "mean")).reset_index()
    hx.to_csv(f"{OUT}/h2_{tf}_OOS_hour_x_sideways.csv", index=False)
    out = dict(tf=tf, stage="oos", chosen=ch, chosen_config=S["chosen_config"], final=rows, laps=round(time.time() - t0, 1), peak_rss_mb=rss_mb())
    json.dump(out, open(f"{OUT}/h2_{tf}_OOS_summary.json", "w"), indent=1, default=str)
    print(F[["cell", "window", "n_kept", "n_skipped", "mean_kept", "mean_skipped", "diff", "control_pct", "perm_p", "loser_recall", "winners_skipped_share"]].to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--tf", required=True, choices=list(CFG)); ap.add_argument("--stage", required=True, choices=["is", "oos"])
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    (stage_is if a.stage == "is" else stage_oos)(a.tf)
