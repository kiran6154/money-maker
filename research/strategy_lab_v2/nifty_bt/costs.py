"""Charges (spec §2.4, §2.8). LOT is a parameter everywhere; 75 reproduces the handoff numbers."""
LOT = 75


def costs(entry, exit_, d, lot=LOT, slip=0.10):
    """Round-trip option charges in rupees for `lot` units. d = +1 bought the option, -1 sold it. slip = rupees per side per unit."""
    buy_px, sell_px = (entry, exit_) if d == 1 else (exit_, entry)
    tb = buy_px * lot; ts = sell_px * lot
    brokerage = 40.0
    stt = 0.001 * ts
    exch = 0.0003503 * (tb + ts)
    sebi = 1e-6 * (tb + ts)
    stamp = 0.00003 * tb
    gst = 0.18 * (brokerage + exch + sebi)
    return brokerage + stt + exch + sebi + stamp + gst + slip * lot * 2


def net(entry, exit_, d, lot=LOT, slip=0.10):
    return d * (exit_ - entry) * lot - costs(entry, exit_, d, lot, slip)
