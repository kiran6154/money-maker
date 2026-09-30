"""Checks for the detector: the user's example path is found as a 3-wave lifecycle, and truncation leaves every
earlier decision unchanged (no look-ahead). Run: python -m pytest -q test_detect.py (or python test_detect.py)."""
import numpy as np

import detect as D


def path_from_levels(levels, bars_per_leg=6, flat=24, noise=0.002, seed=1):
    rng = np.random.default_rng(seed)
    px = [levels[0]] * flat
    for a, b in zip(levels[:-1], levels[1:]):
        px += list(np.linspace(a, b, bars_per_leg + 1)[1:])
    px = np.log(np.array(px)) + rng.normal(0, noise, len(px))
    lc = px
    lh = px + 0.004
    ll = px - 0.004
    return lh, ll, lc


def run(lh, ll, lc, L=12, c=0.75, k=2.0, m=2, strict=True, sess_len=None):
    n = len(lc)
    sess_len = sess_len or n
    bis = np.arange(n) % sess_len
    newsess = bis == 0
    filler = np.zeros(n, np.bool_)
    atr = D.atr_log(lh, ll, lc, filler, newsess, D.NV)
    cr = D.comp_ratio(lh, ll, atr, bis, L)
    return D.lifecycle(lh, ll, lc, cr, atr, bis, newsess, c, L, k, m, strict)


def test_user_example_is_three_waves():
    # 100 -> 115 -> 108 -> 130 -> 120 -> 150 -> 140 -> 175, preceded by a quiet noisy stretch (ATR warm-up) and a tight box
    rng = np.random.default_rng(3)
    warm = list(np.log(100) + np.cumsum(rng.normal(0, 0.01, 30)))
    lvl = [100, 115, 108, 130, 120, 150, 140, 175]
    lh, ll, lc = path_from_levels(lvl, bars_per_leg=6, flat=14, noise=0.0005)
    shift = warm[-1] - np.log(100)
    lc = np.concatenate([np.array(warm) - shift, lc])
    lh = np.concatenate([np.array(warm) - shift + 0.012, lh])
    ll = np.concatenate([np.array(warm) - shift - 0.012, ll])
    sig, lcs, waves, fails = run(lh, ll, lc, L=12, k=1.0)
    assert len(sig) >= 3, sig
    assert sig[:, D.S_WAVE].max() >= 3
    lc0 = int(sig[0, D.S_LC])
    peaks = np.exp(waves[lc0, :3, D.W_PEAK])
    assert np.all(np.diff(peaks) > 0), peaks


def test_truncation_no_lookahead():
    rng = np.random.default_rng(7)
    n = 75 * 30
    r = rng.standard_t(4, n) * 0.004
    lc = np.log(100) + np.cumsum(r)
    lh = lc + np.abs(rng.normal(0, 0.003, n))
    ll = lc - np.abs(rng.normal(0, 0.003, n))
    full = run(lh, ll, lc, L=8, c=0.9, k=1.5, m=2, sess_len=75)[0]
    assert len(full) > 5
    for cut in rng.integers(200, n - 10, 25):
        part = run(lh[:cut], ll[:cut], lc[:cut], L=8, c=0.9, k=1.5, m=2, sess_len=75)[0]
        want = full[full[:, D.S_T] < cut]
        assert part.shape == want.shape, (cut, part.shape, want.shape)
        assert np.allclose(np.nan_to_num(part, nan=-9), np.nan_to_num(want, nan=-9))


if __name__ == "__main__":
    test_user_example_is_three_waves()
    test_truncation_no_lookahead()
    print("ok")
