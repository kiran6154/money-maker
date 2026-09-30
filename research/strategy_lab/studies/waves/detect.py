"""Causal wave-lifecycle detector (PREREG.md §3) and the component controls (§5).

Every function walks bars forward and only reads bars <= t when it decides at t.
Inputs are log prices (lh, ll, lc) of one contract, all its sessions in time order.
"""
from __future__ import annotations

import numpy as np
from numba import njit

NV = 20  # ATR window (bars)

# columns of the signal table
S_T, S_WAVE, S_LC, S_BH, S_BL, S_LEVEL, S_RET, S_HL, S_FAIL, S_START, S_RPREV, S_BPREV, S_BO = range(13)
NS = 13
# lifecycle table
L_START, L_END, L_REASON, L_MAXW, L_P0, L_BL, L_BOX0 = range(7)
NL = 7
# per-wave table [lc, wave, field]
W_BO, W_ACC, W_PEAK, W_PEAKI, W_CONF, W_BLOW, W_BLOWI, W_LEVEL, W_RET, W_FAILS = range(10)
NW = 10
MAXW = 12
REASONS = {0: "open", 1: "failed_base", 2: "stalled", 3: "session_end", 4: "failed_e1"}


@njit(cache=True)
def atr_log(lh, ll, lc, filler, newsess, nv):
    n = lh.shape[0]
    tr = np.full(n, np.nan)
    for t in range(n):
        if filler[t]:
            continue
        if t == 0 or newsess[t]:
            tr[t] = lh[t] - ll[t]
        else:
            tr[t] = max(lh[t], lc[t - 1]) - min(ll[t], lc[t - 1])
    out = np.full(n, np.nan)
    buf = np.zeros(nv)
    cnt = 0
    pos = 0
    s = 0.0
    for t in range(n):
        if not np.isnan(tr[t]):
            if cnt < nv:
                buf[pos] = tr[t]
                s += tr[t]
                cnt += 1
            else:
                s -= buf[pos]
                buf[pos] = tr[t]
                s += tr[t]
            pos = (pos + 1) % nv
        if cnt >= nv // 2:
            out[t] = s / cnt
    return out


@njit(cache=True)
def comp_ratio(lh, ll, atr, bis, L):
    """CR_t over bars t-L+1..t (all today); ATR_pre = ATR at bar t-L (may be yesterday's)."""
    n = lh.shape[0]
    out = np.full(n, np.nan)
    for t in range(n):
        if bis[t] < L - 1 or t - L < 0:
            continue
        a = atr[t - L]
        if np.isnan(a) or a <= 0:
            continue
        hi = -1e18
        lo = 1e18
        for j in range(t - L + 1, t + 1):
            if lh[j] > hi:
                hi = lh[j]
            if ll[j] < lo:
                lo = ll[j]
        out[t] = (hi - lo) / (a * np.sqrt(L))
    return out


@njit(cache=True)
def lifecycle(lh, ll, lc, cr, atr, bis, newsess, c, L, k, m, strict):
    """Returns (sig, lcs, waves, fails, nsig, nlc, nfail).

    sig rows: accepted expansions (the signal bar = the m-th close above the level).
    fails rows: [t, wave attempted, lc id] for breakouts not accepted.
    """
    n = lh.shape[0]
    sig = np.full((n // 2 + 10, NS), np.nan)
    lcs = np.full((n // 2 + 10, NL), np.nan)
    waves = np.full((n // 2 + 10, MAXW, NW), np.nan)
    fails = np.full((n + 10, 3), np.nan)
    nsig = 0
    nlc = 0
    nfail = 0

    phase = 0          # 0 search, 1 base0 armed, 2 accept window, 3 expansion, 4 base n
    base_hi = 0.0
    base_lo = 0.0
    box_start = -1
    armed_until = -1
    wave = 0           # accepted expansions in the current lifecycle
    lcid = -1
    level = 0.0
    acc = 0
    bo = -1
    runmax = 0.0
    runmax_i = -1
    pull = 0.0
    pull_i = -1
    conf_i = -1
    support = 0.0
    retests = 0
    hl_count = 0
    last_sl = 0.0
    sl_run = 0.0       # running low for the in-base zig-zag
    sl_armed = False
    sh_run = 0.0
    nfails_wave = 0
    R_prev = np.nan
    B_prev = np.nan

    for t in range(n):
        a = atr[t - 1] if t > 0 else np.nan
        if newsess[t]:
            # close any live lifecycle at the session boundary
            if phase >= 2 and lcid >= 0:
                lcs[lcid, L_END] = t - 1
                lcs[lcid, L_REASON] = 3
                lcs[lcid, L_MAXW] = wave
            phase = 0
            wave = 0
            lcid = -1
        if np.isnan(a):
            continue

        if phase == 1:
            if lc[t] > base_hi:
                # E1 breakout off base 0 -> a lifecycle starts
                lcid = nlc
                nlc += 1
                lcs[lcid, L_START] = box_start
                lcs[lcid, L_P0] = base_hi
                lcs[lcid, L_BL] = base_lo
                lcs[lcid, L_BOX0] = t
                lcs[lcid, L_REASON] = 0
                wave = 0
                phase = 2
                level = base_hi
                acc = 1
                bo = t
                nfails_wave = 0
                retests = 0
                hl_count = 0
                R_prev = np.nan
                B_prev = np.nan
                waves[lcid, 0, W_BO] = t
                waves[lcid, 0, W_LEVEL] = level
            elif t > armed_until:
                phase = 0
        elif phase == 2:
            if lc[t] > level:
                acc += 1
            else:
                fails[nfail, 0] = t
                fails[nfail, 1] = wave + 1
                fails[nfail, 2] = lcid
                nfail += 1
                nfails_wave += 1
                if wave == 0:
                    # E1 not accepted: the lifecycle never started a wave
                    lcs[lcid, L_END] = t
                    lcs[lcid, L_REASON] = 4
                    lcs[lcid, L_MAXW] = 0
                    lcid = -1
                    phase = 1 if t <= armed_until else 0
                else:
                    phase = 4
                    if lc[t] <= support:
                        lcs[lcid, L_END] = t
                        lcs[lcid, L_REASON] = 1
                        lcs[lcid, L_MAXW] = wave
                        phase = 0
                        wave = 0
                        lcid = -1
        if phase == 2 and acc >= m:
            wave += 1
            w = wave - 1
            if w < MAXW:
                waves[lcid, w, W_ACC] = t
                waves[lcid, w, W_FAILS] = nfails_wave
                waves[lcid, w, W_RET] = retests
            sig[nsig, S_T] = t
            sig[nsig, S_WAVE] = wave
            sig[nsig, S_LC] = lcid
            sig[nsig, S_BH] = base_hi
            sig[nsig, S_BL] = base_lo
            sig[nsig, S_LEVEL] = level
            sig[nsig, S_RET] = retests
            sig[nsig, S_HL] = hl_count
            sig[nsig, S_FAIL] = nfails_wave
            sig[nsig, S_START] = lcs[lcid, L_START]
            sig[nsig, S_RPREV] = R_prev
            sig[nsig, S_BPREV] = B_prev
            sig[nsig, S_BO] = bo
            nsig += 1
            phase = 3
            runmax = -1e18
            for j in range(bo, t + 1):
                if lh[j] > runmax:
                    runmax = lh[j]
                    runmax_i = j
            nfails_wave = 0
            retests = 0
            hl_count = 0
            continue
        if phase == 3:
            # a bar that makes a new high cannot also confirm the reversal (OHLC does not say which came first)
            if lh[t] > runmax:
                runmax = lh[t]
                runmax_i = t
            elif ll[t] <= runmax - k * a:
                w = wave - 1
                if w < MAXW:
                    waves[lcid, w, W_PEAK] = runmax
                    waves[lcid, w, W_PEAKI] = runmax_i
                    waves[lcid, w, W_CONF] = t
                conf_i = t
                pull = 1e18
                for j in range(runmax_i, t + 1):
                    if ll[j] < pull:
                        pull = ll[j]
                        pull_i = j
                # support for base n
                if strict:
                    support = level  # R_{n-1} (or base_hi for n = 1): the broken level
                else:
                    support = base_lo if wave == 1 else B_prev
                R_prev = runmax
                sl_run = pull
                sl_armed = True
                last_sl = -1e18
                retests = 0
                hl_count = 0
                phase = 4
                if lc[t] <= support:
                    lcs[lcid, L_END] = t
                    lcs[lcid, L_REASON] = 1
                    lcs[lcid, L_MAXW] = wave
                    if w < MAXW:
                        waves[lcid, w, W_BLOW] = pull
                        waves[lcid, w, W_BLOWI] = pull_i
                    phase = 0
                    wave = 0
                    lcid = -1
                continue
        if phase == 4:
            w = wave - 1
            if lc[t] <= support:
                if w < MAXW:
                    waves[lcid, w, W_BLOW] = min(pull, ll[t])
                    waves[lcid, w, W_BLOWI] = pull_i if pull <= ll[t] else t
                lcs[lcid, L_END] = t
                lcs[lcid, L_REASON] = 1
                lcs[lcid, L_MAXW] = wave
                phase = 0
                wave = 0
                lcid = -1
            elif lc[t] > R_prev:
                # breakout n+1: the base ends at the bar before
                if w < MAXW:
                    waves[lcid, w, W_BLOW] = pull
                    waves[lcid, w, W_BLOWI] = pull_i
                B_prev = pull
                phase = 2
                level = R_prev
                acc = 1
                bo = t
                if wave < MAXW:
                    waves[lcid, wave, W_BO] = t
                    waves[lcid, wave, W_LEVEL] = level
                if m <= 1:
                    wave += 1
                    ww = wave - 1
                    if ww < MAXW:
                        waves[lcid, ww, W_ACC] = t
                        waves[lcid, ww, W_FAILS] = nfails_wave
                        waves[lcid, ww, W_RET] = retests
                    sig[nsig, S_T] = t
                    sig[nsig, S_WAVE] = wave
                    sig[nsig, S_LC] = lcid
                    sig[nsig, S_BH] = base_hi
                    sig[nsig, S_BL] = base_lo
                    sig[nsig, S_LEVEL] = level
                    sig[nsig, S_RET] = retests
                    sig[nsig, S_HL] = hl_count
                    sig[nsig, S_FAIL] = nfails_wave
                    sig[nsig, S_START] = lcs[lcid, L_START]
                    sig[nsig, S_RPREV] = R_prev
                    sig[nsig, S_BPREV] = B_prev
                    sig[nsig, S_BO] = bo
                    nsig += 1
                    phase = 3
                    runmax = lh[t]
                    runmax_i = t
                    nfails_wave = 0
                    retests = 0
                    hl_count = 0
            else:
                if ll[t] < pull:
                    pull = ll[t]
                    pull_i = t
                if lh[t] >= R_prev - 0.5 * a and lc[t] <= R_prev:
                    retests += 1
                # in-base zig-zag for the higher-low count
                newlow = ll[t] < sl_run
                if newlow:
                    sl_run = ll[t]
                if sl_armed and not newlow and lh[t] >= sl_run + k * a:
                    if sl_run > last_sl and last_sl > -1e17:
                        hl_count += 1
                    last_sl = sl_run
                    sl_armed = False
                    sh_run = lh[t]
                elif not sl_armed:
                    if lh[t] > sh_run:
                        sh_run = lh[t]
                    elif ll[t] <= sh_run - k * a:
                        sl_run = ll[t]
                        sl_armed = True
                if t - conf_i > 2 * L:
                    if w < MAXW:
                        waves[lcid, w, W_BLOW] = pull
                        waves[lcid, w, W_BLOWI] = pull_i
                    lcs[lcid, L_END] = t
                    lcs[lcid, L_REASON] = 2
                    lcs[lcid, L_MAXW] = wave
                    phase = 0
                    wave = 0
                    lcid = -1

        # base 0 search runs whenever no lifecycle is live
        if phase <= 1 and not np.isnan(cr[t]) and cr[t] <= c:
            hi = -1e18
            lo = 1e18
            for j in range(t - L + 1, t + 1):
                if lh[j] > hi:
                    hi = lh[j]
                if ll[j] < lo:
                    lo = ll[j]
            base_hi = hi
            base_lo = lo
            box_start = t - L + 1
            armed_until = t + L
            phase = 1

    # lifecycles still live at the end of data
    if lcid >= 0 and phase >= 2:
        lcs[lcid, L_END] = n - 1
        lcs[lcid, L_REASON] = 3
        lcs[lcid, L_MAXW] = wave
    return sig[:nsig], lcs[:nlc], waves[:nlc], fails[:nfail]


@njit(cache=True)
def swing_lows(lh, ll, atr, newsess, k):
    """Intraday zig-zag. Returns per bar: 1 if a swing low is confirmed at t and it is above the previous swing low
    (control E), 0 if confirmed but not higher, -1 otherwise."""
    n = lh.shape[0]
    out = np.full(n, -1, np.int8)
    up = False
    ext = 0.0
    prev_sl = np.nan
    started = False
    for t in range(n):
        a = atr[t - 1] if t > 0 else np.nan
        if newsess[t] or not started:
            up = False
            ext = ll[t]
            prev_sl = np.nan
            started = True
            continue
        if np.isnan(a):
            continue
        if not up:
            if ll[t] < ext:
                ext = ll[t]
            elif lh[t] >= ext + k * a:
                out[t] = 1 if (not np.isnan(prev_sl) and ext > prev_sl) else 0
                prev_sl = ext
                up = True
                ext = lh[t]
        else:
            if lh[t] > ext:
                ext = lh[t]
            elif ll[t] <= ext - k * a:
                up = False
                ext = ll[t]
    return out
