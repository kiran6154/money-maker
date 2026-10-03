"""No look-ahead: signals computed on data cut at random bars equal the full-data signals before the cut."""
import numpy as np
import accel as A


def test_truncation():
    b = A.fut_bars(5)
    b = b[b.year == 2024].reset_index(drop=True).iloc[:6000]
    prm = A.PRIMARY
    f = A.features(b, prm["L"]); el = A.eligible(b, f, prm["L"])
    full = A.signals(b, f, el, prm["L"], prm["a"], prm["v"])
    rng = np.random.default_rng(3)
    for cut in rng.integers(800, len(b) - 10, 12):
        bb = b.iloc[:cut].reset_index(drop=True)
        ff = A.features(bb, prm["L"]); ee = A.eligible(bb, ff, prm["L"])
        part = A.signals(bb, ff, ee, prm["L"], prm["a"], prm["v"])
        for k in full:
            assert np.array_equal(full[k][:cut], part[k]), (k, cut)


if __name__ == "__main__":
    test_truncation()
    print("ok")
