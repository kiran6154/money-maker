"""FZ v3 data build, 1-minute, stage 3: per-bar volume baselines, the per-SETUP feature table, parquet copies.

Every feature at a SETUP bar k uses bars <= k only (the card is as-of by construction; events with i <= k; rolling
windows end at k; touch verdicts are read only for windows that closed by k). Labels (fnd_*, win, fwd_*) and the st7_*
post-SETUP outcome columns use later bars and are never features. The README next to the files states the status of
every column.
Inputs: bars.csv, sessions.csv, swings.csv, events.csv, setups.csv, trades.csv, skipped.csv, card.csv, ledger.csv,
zones.csv, fz_trades.csv. Outputs: bars_volume.csv, setup_features.csv, *.parquet, timing_03.json.
"""
import os, sys, json, time, bisect, warnings
import numpy as np, pandas as pd
import psutil
warnings.filterwarnings("ignore", category=RuntimeWarning)     # all-NaN slices / NaN comparisons are expected

OUT = os.path.dirname(os.path.abspath(__file__))
IS_END = "2025-12-31"
OPEN_WINDOW_UNTIL, NO_ENTRY_FROM = "09:25", "15:20"       # ST7 clock keys; the hour_bin edges fz_report.crosstabs uses
TOUCH_LOOKBACK, TOUCH_VERDICT_BARS, BREAK_ATR = 60, 15, 0.5
MED_MIN_BARS = 5                                            # prior same-session bars a volume baseline needs
proc = psutil.Process()
timing = {}
def rss(): return round(proc.memory_info().rss / 1e6, 1)
def say(*a): print(time.strftime("%H:%M:%S"), *a, f"[rss {rss()} MB]", flush=True)
P = lambda name: os.path.join(OUT, name)

# ---------------------------------------------------------------- bars + volume baselines
t0 = time.time()
bars = pd.read_csv(P("bars.csv"), dtype={"datetime": str, "date": str, "tod": str})
n = len(bars)
sessions = pd.read_csv(P("sessions.csv"), dtype={"date": str, "contract": str, "expiry": str, "split": str})
split_of_sess = dict(zip(sessions.session_i, sessions.split))
g = bars.groupby("session_i")["volume"]
bars["vol_med20_prior"] = g.transform(lambda s: s.shift(1).rolling(20, min_periods=MED_MIN_BARS).median())
bars["vol_med60_prior"] = g.transform(lambda s: s.shift(1).rolling(60, min_periods=MED_MIN_BARS).median())
usable = (bars.fm_na == 0)
for N in (20, 60):
    m = bars[f"vol_med{N}_prior"]
    bars[f"vol_ratio{N}"] = np.where(usable & (m > 0), bars.volume / m.replace(0, np.nan), np.nan)
bars["sess_cumvol"] = g.cumsum()
# cumulative session volume at the same bar-in-session over the previous 20 sessions (median), as-of
S = int(bars.session_i.max()) + 1; SB = int(bars.session_bar.max()) + 1
cum = np.full((S, SB), np.nan)
cum[bars.session_i.values, bars.session_bar.values] = bars.sess_cumvol.values
ref = np.full((S, SB), np.nan)
for s in range(1, S):
    lo = max(0, s - 20)
    with np.errstate(all="ignore"): ref[s] = np.nanmedian(cum[lo:s], axis=0) if s - lo >= 5 else np.nan
bars["sess_cumvol_ratio20s"] = np.where(usable, bars.sess_cumvol.values / ref[bars.session_i.values, bars.session_bar.values], np.nan)
bars[["bar_i", "vol_med20_prior", "vol_med60_prior", "vol_ratio20", "vol_ratio60", "sess_cumvol", "sess_cumvol_ratio20s"]] \
    .to_csv(P("bars_volume.csv"), index=False)
bars.to_parquet(P("bars.parquet"), index=False)
timing["bars_volume_s"] = round(time.time() - t0, 1)
say(f"bars {n}, volume baselines written; hv3 bars (ratio20 >= 3): {int((bars.vol_ratio20 >= 3).sum())}")

o, h, l, c, v = (bars[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
atr = bars.atr14.values.astype(float); prot = bars.prot.values.astype(float)
sess = bars.session_i.values; sbar = bars.session_bar.values
r20 = bars.vol_ratio20.values; r60 = bars.vol_ratio60.values
cumratio = bars.sess_cumvol_ratio20s.values
tod = bars.tod.values; tstr = bars.datetime.values
sfirst = np.zeros(n, dtype=int)                              # first bar of each bar's session
first_of = sessions.set_index("session_i").first_bar.to_dict()
sfirst = np.array([first_of[s] for s in sess])
del bars["datetime"]; del bars["date"]; del bars["tod"]

# ---------------------------------------------------------------- engine outputs
sw = pd.read_csv(P("swings.csv"))
swH = sw[sw.kind == "H"]; swL = sw[sw.kind == "L"]
confH, pH, barH = swH.conf.values, swH.price.values, swH.bar.values
confL, pL, barL = swL.conf.values, swL.price.values, swL.bar.values
assert (np.diff(confH) >= 0).all() and (np.diff(confL) >= 0).all(), "swings not in confirmation order"
ev = pd.read_csv(P("events.csv"))
ev_i = ev.i.values; ev_kind = ev.kind.values; ev_dir = ev["dir"].values; ev_flip = ev.flip.fillna(0).values.astype(int)
ev_lvl = ev.lvl.values
assert (np.diff(ev_i) >= 0).all(), "events not in bar order"
ch_flip = {int(i): int(f) for i, f, k in zip(ev_i, ev_flip, ev_kind) if k == "CHoCH"}
ch_lvl = {int(i): float(x) for i, x, k in zip(ev_i, ev_lvl, ev_kind) if k == "CHoCH"}
setups = pd.read_csv(P("setups.csv"), dtype={"time": str, "ch_time": str})
trades = pd.read_csv(P("trades.csv"), dtype={"entry_time": str, "exit_time": str, "choch_time": str, "exit_reason": str})
skipped = pd.read_csv(P("skipped.csv"))
zones = pd.read_csv(P("zones.csv"), dtype={"zone_id": str, "retired_by": str, "born_ts": str, "retired_time": str})
z_lo, z_hi = zones.lo.values.astype(float), zones.hi.values.astype(float)
z_birth = zones.birth_bar.values.astype(int)
z_ret = zones.retired_bar.fillna(np.inf).values.astype(float)
z_id = zones.zone_id.values
fzt = pd.read_csv(P("fz_trades.csv"))
st7_traded = set(fzt.setup_i.astype(int))
say(f"swings {len(sw)}, events {len(ev)}, setups {len(setups)}, trades {len(trades)}, skipped {len(skipped)}, rooms {len(zones)}")

# ---------------------------------------------------------------- card + ledger at SETUP bars
t0 = time.time()
card = pd.read_csv(P("card.csv"), dtype={"datetime": str, "zone_id": str, "read": str, "left_id": str, "out_side": str,
                                          "last_hunt_dir": str, "last_reject_dir": str, "in_id": str, "leave_side": str,
                                          "leave_kind": str})
card.to_parquet(P("card.parquet"), index=False)
card_at = card.set_index("bar_i").loc[setups.setup_i.values]
del card
ledger = pd.read_csv(P("ledger.csv"), dtype=str).set_index("i")
ledger.index = ledger.index.astype(int)
ledger_at = ledger.loc[setups.setup_i.values]
timing["card_ledger_s"] = round(time.time() - t0, 1)
say("card / ledger rows at SETUP bars joined")

# ---------------------------------------------------------------- helpers
def touch_stats(L, k):
    """Touch episodes of level L in bars [k-60, k-1] (a bar touches when l <= L <= h). For the last episode: the side
    price came from (close before the episode, else the episode's first open), then within the TOUCH_VERDICT_BARS bars
    after it (never past k): 'broke' = a close beyond L on the far side by more than BREAK_ATR x atr14 at the episode's
    last bar; 'held' = no such close and the window closed by k; 'pending' = window still open at k; 'none' = no touch."""
    if not np.isfinite(L): return np.nan, "na", np.nan
    j0 = max(0, k - TOUCH_LOOKBACK)
    hit = (l[j0:k] <= L) & (h[j0:k] >= L)
    if not hit.any(): return 0, "none", np.nan
    idx = np.flatnonzero(hit) + j0
    starts = idx[np.r_[True, np.diff(idx) > 1]]
    n_ep = len(starts)
    js = starts[-1]; je = idx[-1]
    ref_px = c[js - 1] if js >= 1 else o[js]
    side = np.sign(ref_px - L) or np.sign(o[js] - L)
    if side == 0: return n_ep, "na", k - je
    a = atr[je]; w0, w1 = je + 1, min(je + TOUCH_VERDICT_BARS, k)
    broke = False
    if w1 >= w0:
        cc = c[w0:w1 + 1]
        broke = bool(((L - cc) > BREAK_ATR * a).any() if side > 0 else ((cc - L) > BREAK_ATR * a).any())
    if broke: verdict = "broke"
    elif je + TOUCH_VERDICT_BARS > k: verdict = "pending"
    else: verdict = "held"
    return n_ep, verdict, k - je

def hv_stats(k, thr):
    """Latest bar j in [session start, k] with vol_ratio20 >= thr: bars ago, that bar's direction, whether its low / high
    held since (bars j+1..k), NaN / 'none' when no such bar."""
    j0 = sfirst[k]
    seg = r20[j0:k + 1]
    ok = np.flatnonzero(seg >= thr)
    if len(ok) == 0: return np.nan, "none", np.nan, np.nan, np.nan
    j = j0 + ok[-1]
    d = "up" if c[j] > o[j] else "down" if c[j] < o[j] else "flat"
    if j == k: return 0, d, np.nan, np.nan, r20[j]
    low_held = float(l[j + 1:k + 1].min() >= l[j]); high_held = float(h[j + 1:k + 1].max() <= h[j])
    return k - j, d, low_held, high_held, r20[j]

def hour_bin(hm): return "<" + OPEN_WINDOW_UNTIL if hm < OPEN_WINDOW_UNTIL else ">=" + NO_ENTRY_FROM if hm >= NO_ENTRY_FROM else hm[:2]

# ---------------------------------------------------------------- per-SETUP loop
t0 = time.time()
tr_by_entry = trades.set_index("entry")
sk_by_entry = skipped.set_index("entry")
setups_by_sess = {}
for k_, s_ in zip(setups.setup_i.values, sess[setups.setup_i.values]): setups_by_sess.setdefault(int(s_), []).append(int(k_))
tr_exit_by_sess = {}
for e_, x_, p_ in zip(trades.entry.values, trades.exit.values, trades.pts.values):
    tr_exit_by_sess.setdefault(int(sess[e_]), []).append((int(x_), float(p_)))
rows = []
for k, d, ch in zip(setups.setup_i.values.astype(int), setups["dir"].values, setups.ch.values.astype(int)):
    sg = 1 if d == "up" else -1
    a = atr[k]; ck = c[k]; s = int(sess[k]); j0s = int(sfirst[k])
    row = dict(setup_i=k, time=tstr[k], date=tstr[k][:10], session_i=s, session_bar=int(sbar[k]), tod=tod[k],
               hour_bin=hour_bin(tod[k]), minute_of_day=int(tod[k][:2]) * 60 + int(tod[k][3:5]), split=split_of_sess[s],
               dir=d, dir_sign=sg, ch=ch, ch_time=tstr[ch], close=ck, atr14=a, atr_bps=1e4 * a / ck,
               choch_flip=ch_flip.get(ch, np.nan), choch_lvl=ch_lvl.get(ch, np.nan))
    # ---- stop and trade status (the stop is known at the SETUP close: engine.run evaluates it there)
    if k in tr_by_entry.index:
        x = tr_by_entry.loc[k]; row.update(traded=1, skipped_wrong_side_stop=0, sl=float(x.sl), sl_dist_pts=float(x.sl_dist_pts))
    else:
        x = None; y = sk_by_entry.loc[k]
        row.update(traded=0, skipped_wrong_side_stop=1, sl=float(y.sl), sl_dist_pts=float(sg * (ck - y.sl)))
    row["sl_dist_atr"] = row["sl_dist_pts"] / a
    # ---- regime from events with i <= k
    m = bisect.bisect_right(ev_i, k)
    K, Dd, F, I = ev_kind[:m], ev_dir[:m], ev_flip[:m], ev_i[:m]
    bos_pos = np.flatnonzero(K == "BOS"); ch_pos = np.flatnonzero(K == "CHoCH")
    lb = bos_pos[-1] if len(bos_pos) else -1; lc = ch_pos[-1] if len(ch_pos) else -1
    since_bos = K[lb + 1:]; since_bos_flip = F[lb + 1:]
    row.update(reg_n_choch_since_bos=int((since_bos == "CHoCH").sum()),
               reg_n_flip_since_bos=int(since_bos_flip[since_bos == "CHoCH"].sum()) if len(since_bos) else 0,
               reg_n_bos_since_choch=int((K[lc + 1:] == "BOS").sum()),
               reg_bars_since_choch=int(k - I[lc]) if lc >= 0 else np.nan, reg_bars_since_own_choch=int(k - ch),
               reg_bars_since_bos=int(k - I[lb]) if lb >= 0 else np.nan,
               reg_last_bos_dir=Dd[lb] if lb >= 0 else "none", reg_last_bos_agree=(int(Dd[lb] == d) if lb >= 0 else np.nan))
    last6 = list(zip(K[-6:], Dd[-6:]))
    row["reg_alt6"] = int(sum(1 for (_, d1), (_, d2) in zip(last6, last6[1:]) if d1 != d2))
    row["reg_last6"] = " ".join(("C" if kk == "CHoCH" else "B") + ("u" if dd == "up" else "d") for kk, dd in last6)
    for N in (60, 120):
        w = I > k - N
        row[f"reg_n_choch_{N}"] = int((K[w] == "CHoCH").sum()); row[f"reg_n_bos_{N}"] = int((K[w] == "BOS").sum())
    for N in (20, 60):
        j0 = max(0, k - N + 1)
        row[f"reg_range{N}_atr"] = (h[j0:k + 1].max() - l[j0:k + 1].min()) / a
    shi, slo = h[j0s:k + 1].max(), l[j0s:k + 1].min()
    row["reg_session_range_atr"] = (shi - slo) / a
    row["reg_pos_in_session_range"] = (ck - slo) / (shi - slo) if shi > slo else np.nan
    row["reg_range_since_choch_atr"] = (h[ch:k + 1].max() - l[ch:k + 1].min()) / a
    row["reg_prior_setups_today"] = sum(1 for kk in setups_by_sess[s] if kk < k)
    row["reg_prior_closed_pts_today"] = float(sum(p for x_, p in tr_exit_by_sess.get(s, []) if x_ <= k))
    # ---- volume
    row.update(vol_bar=v[k], vol_fm_na=int(bars.fm_na.values[k]), vol_ratio20=r20[k], vol_ratio60=r60[k],
               vol_med20_prior=bars.vol_med20_prior.values[k], vol_sess_cumvol_ratio20s=cumratio[k])
    for N in (5, 15):
        j0 = max(j0s, k - N + 1); seg = r20[j0:k + 1]
        row[f"vol_max_ratio20_{N}"] = np.nanmax(seg) if np.isfinite(seg).any() else np.nan
    for thr in (2, 3):
        ago, hd, lowh, highh, rr = hv_stats(k, thr)
        row.update({f"vol_hv{thr}_bars_ago": ago, f"vol_hv{thr}_dir": hd, f"vol_hv{thr}_agree": (int(hd == d) if hd != "none" else np.nan),
                    f"vol_hv{thr}_low_held": lowh, f"vol_hv{thr}_high_held": highh, f"vol_hv{thr}_ratio": rr})
    seg = r20[ch:k + 1]
    row["vol_ratio20_at_choch"] = r20[ch]; row["vol_max_ratio20_choch_to_k"] = np.nanmax(seg) if np.isfinite(seg).any() else np.nan
    # ---- levels: protected level, CHoCH level, rooms, swings
    Lp = prot[k]
    row["lvl_prot"] = Lp; row["lvl_prot_dist_atr"] = (ck - Lp) / a if np.isfinite(Lp) else np.nan
    row["lvl_prot_dist_dir_atr"] = sg * (ck - Lp) / a if np.isfinite(Lp) else np.nan
    row["lvl_choch_dist_dir_atr"] = sg * (ck - row["choch_lvl"]) / a if np.isfinite(row["choch_lvl"]) else np.nan
    alive = (z_birth <= k) & (z_ret > k)
    row["lvl_n_rooms_alive"] = int(alive.sum())
    Lr = np.nan
    if alive.any():
        lo_, hi_, ids = z_lo[alive], z_hi[alive], z_id[alive]
        edges = np.concatenate([lo_, hi_]); eids = np.concatenate([ids, ids]); ekind = np.array(["lo"] * len(lo_) + ["hi"] * len(hi_))
        dd = edges - ck; jn = int(np.argmin(np.abs(dd)))
        Lr = edges[jn]
        row.update(lvl_room_edge=Lr, lvl_room_edge_dist_atr=dd[jn] / a, lvl_room_edge_dist_dir_atr=sg * dd[jn] / a,
                   lvl_room_edge_id=eids[jn], lvl_room_edge_kind=ekind[jn])
        ahead = sg * dd; ah = ahead[ahead > 1e-9]; bh = -ahead[ahead < -1e-9]
        row["lvl_room_ahead_dist_atr"] = ah.min() / a if len(ah) else np.nan
        row["lvl_room_behind_dist_atr"] = bh.min() / a if len(bh) else np.nan
    else:
        row.update(lvl_room_edge=np.nan, lvl_room_edge_dist_atr=np.nan, lvl_room_edge_dist_dir_atr=np.nan, lvl_room_edge_id="",
                   lvl_room_edge_kind="", lvl_room_ahead_dist_atr=np.nan, lvl_room_behind_dist_atr=np.nan)
    iH = bisect.bisect_right(confH, k) - 1; iL = bisect.bisect_right(confL, k) - 1
    lastH = pH[iH] if iH >= 0 else np.nan; lastL = pL[iL] if iL >= 0 else np.nan
    row.update(lvl_last_sh=lastH, lvl_last_sh_dist_atr=(lastH - ck) / a if iH >= 0 else np.nan,
               lvl_last_sh_age=int(k - barH[iH]) if iH >= 0 else np.nan,
               lvl_last_sl=lastL, lvl_last_sl_dist_atr=(ck - lastL) / a if iL >= 0 else np.nan,
               lvl_last_sl_age=int(k - barL[iL]) if iL >= 0 else np.nan)
    cands = [(abs(lastH - ck), "H", lastH)] if iH >= 0 else []
    cands += [(abs(lastL - ck), "L", lastL)] if iL >= 0 else []
    Ls = np.nan
    if cands:
        _, kind_, Ls = min(cands); row.update(lvl_swing_near_kind=kind_, lvl_swing_near_dist_atr=(Ls - ck) / a,
                                              lvl_swing_near_dist_dir_atr=sg * (Ls - ck) / a)
    else: row.update(lvl_swing_near_kind="", lvl_swing_near_dist_atr=np.nan, lvl_swing_near_dist_dir_atr=np.nan)
    row["lvl_swing_ahead_dist_atr"] = ((lastH - ck) / a if iH >= 0 else np.nan) if d == "up" else ((ck - lastL) / a if iL >= 0 else np.nan)
    for name, L in (("prot", Lp), ("room", Lr), ("swing", Ls)):
        ne, verdict, ago = touch_stats(L, k)
        row.update({f"lvl_touch_{name}_n60": ne, f"lvl_touch_{name}_last": verdict, f"lvl_touch_{name}_bars_ago": ago})
    # ---- labels (never features)
    if x is not None:
        row.update(fnd_pts=float(x.pts), fnd_slip_pts=float(x.slip_pts), fnd_gross=float(x.gross), fnd_charges=float(x.charges),
                   fnd_net=float(x.net), win=int(x.win), win_pts=int(x.win_pts), fnd_exit_reason=x.exit_reason,
                   fnd_bars_held=int(x.bars_held), fnd_mfe=float(x.mfe), fnd_mae=float(x.mae), fnd_mfe_bar=int(x.mfe_bar),
                   fnd_mae_bar=int(x.mae_bar), fnd_exit_time=x.exit_time, fnd_open=int(x.open))
    else:
        row.update(fnd_pts=np.nan, fnd_slip_pts=np.nan, fnd_gross=np.nan, fnd_charges=np.nan, fnd_net=np.nan, win=np.nan,
                   win_pts=np.nan, fnd_exit_reason="", fnd_bars_held=np.nan, fnd_mfe=np.nan, fnd_mae=np.nan, fnd_mfe_bar=np.nan,
                   fnd_mae_bar=np.nan, fnd_exit_time="", fnd_open=np.nan)
    for N in (5, 15, 30):
        row[f"fwd_ret{N}"] = sg * (c[min(k + N, n - 1)] - ck)
    j1 = min(k + 30, n - 1)
    row["fwd_mfe30"] = (h[k + 1:j1 + 1].max() - ck if d == "up" else ck - l[k + 1:j1 + 1].min()) if j1 > k else np.nan
    row["fwd_mae30"] = (l[k + 1:j1 + 1].min() - ck if d == "up" else ck - h[k + 1:j1 + 1].max()) if j1 > k else np.nan
    row["st7_traded"] = int(k in st7_traded)
    rows.append(row)
F = pd.DataFrame(rows)
timing["setup_loop_s"] = round(time.time() - t0, 1)
say(f"per-SETUP features: {len(F)} rows x {F.shape[1]} cols")

# ---------------------------------------------------------------- card_* and st7_* joins
CARD_COLS = ["zone_id", "visit_n", "this_bars", "this_vol", "vol_na", "first_bars", "first_vol", "first_vol_na", "read",
             "left_id", "out_run", "out_side", "session_bar", "gap_pts", "wick_depth", "last_hunt_at", "last_hunt_dir",
             "last_reject_at", "last_reject_dir", "cluster_sit", "prev_bars", "prev_vol", "last_leave_failed", "in_id",
             "leave_side", "leave_vol_ok", "leave_kind", "first_clock_lived", "touches"]
C = card_at[CARD_COLS].reset_index(drop=True).add_prefix("card_")
assert (card_at.index.values == F.setup_i.values).all()
F = pd.concat([F, C], axis=1)
live = (F.card_vol_na == 0) & (F.card_first_vol_na == 0) & (F.card_first_vol > 0)
F["card_vol_ratio"] = np.where(live, F.card_this_vol / F.card_first_vol.replace(0, np.nan), np.nan)
F["card_bars_since_hunt"] = F.setup_i - F.card_last_hunt_at
F["card_bars_since_reject"] = F.setup_i - F.card_last_reject_at
F["card_hunt_dir_agree"] = np.where(F.card_last_hunt_dir.isna(), np.nan, (F.card_last_hunt_dir == F["dir"]).astype(float))
F["card_in_room"] = F.card_in_id.notna().astype(int)
F["card_ref_room_live"] = F.card_zone_id.notna().astype(int)
ST7_ASOF = ["zone_kind", "band_lo", "band_hi", "level_in_band", "gate", "block_reason", "branch", "take_why", "refused",
            "entered_zone_id", "entered_visit_n", "entered_read", "leave_vol_ok", "leave_kind", "watch_kind", "watch_band_id"]
ST7_POST = ["outcome_gate", "watch_outcome", "reenter_reason", "fill_used", "fill_bar", "fill_delay_bars", "edge_dist_pts",
            "armed_bars", "rearmed_bars", "sl_bar"]
Ld = ledger_at[ST7_ASOF + ST7_POST].reset_index(drop=True).add_prefix("st7_")
assert (ledger_at.index.values == F.setup_i.values).all()
F = pd.concat([F, Ld], axis=1)
for col in ("st7_band_lo", "st7_band_hi", "st7_entered_visit_n", "st7_fill_bar", "st7_fill_delay_bars", "st7_edge_dist_pts",
            "st7_armed_bars", "st7_rearmed_bars"):
    F[col] = pd.to_numeric(F[col], errors="coerce")
F["st7_level_in_band"] = pd.to_numeric(F.st7_level_in_band, errors="coerce")
F["st7_leave_vol_ok"] = pd.to_numeric(F.st7_leave_vol_ok, errors="coerce")
width = F.st7_band_hi - F.st7_band_lo
F["card_room_lo"] = F.st7_band_lo; F["card_room_hi"] = F.st7_band_hi; F["card_room_mid"] = (F.st7_band_lo + F.st7_band_hi) / 2
F["card_room_width_atr"] = width / F.atr14
F["card_room_pos"] = np.where((F.card_out_run == 0) & (width > 0), (F.close - F.st7_band_lo) / width.replace(0, np.nan), np.nan)
F["card_room_pos_dir"] = np.where(F["dir"] == "up", F.card_room_pos, 1 - F.card_room_pos)
F.to_csv(P("setup_features.csv"), index=False)
F.to_parquet(P("setup_features.parquet"), index=False)

# ---------------------------------------------------------------- parquet copies of the other tables
for name in ("sessions", "swings", "events", "setups", "trades", "skipped", "ledger", "zones", "visits", "watches",
             "decisions", "fz_trades"):
    pd.read_csv(P(name + ".csv"), low_memory=False).to_parquet(P(name + ".parquet"), index=False)

# ---------------------------------------------------------------- summary
def book(df):
    d = df[df.traded == 1]
    return dict(setups=int(len(df)), traded=int(len(d)), net=round(float(d.fnd_net.sum()), 2), pts=round(float(d.fnd_pts.sum()), 2),
                wins=int(d.win.sum()), win_rate=round(float(d.win.mean()), 4) if len(d) else None,
                mean_net=round(float(d.fnd_net.mean()), 2) if len(d) else None,
                mean_cost_inr=round(float((d.fnd_charges + 2 * 5 * 65).mean()), 2) if len(d) else None,
                exit_reasons={str(k): int(v) for k, v in d.fnd_exit_reason.value_counts().items()},
                st7_gate_at_setup={str(k): int(v) for k, v in df.st7_gate.value_counts().items()},
                st7_outcome_gate={str(k): int(v) for k, v in df.st7_outcome_gate.value_counts().items()},
                st7_traded=int(df.st7_traded.sum()), sessions=int(df.session_i.nunique()))
timing.update(rows=int(len(F)), cols=int(F.shape[1]), columns=list(F.columns), by_split={s: book(F[F.split == s]) for s in ("IS", "OOS")},
              peak_rss_mb=round(proc.memory_info().peak_wset / 1e6, 1), touch_lookback=TOUCH_LOOKBACK,
              touch_verdict_bars=TOUCH_VERDICT_BARS, break_atr=BREAK_ATR, med_min_bars=MED_MIN_BARS)
json.dump(timing, open(P("timing_03.json"), "w"), indent=1)
say("done"); print(json.dumps({k: v for k, v in timing.items() if k != "columns"}, indent=1), flush=True)
