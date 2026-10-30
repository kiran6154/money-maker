"""FZ execution: fills, stops and exits for the entries fz.py decides, and the FZ trade list.

engine.py keeps its fill / stop / exit loop inline (the trades loop at the end of engine.run()), so a REENTER, which fills
on a bar Foundation did not choose, needs that loop restated. simulate() mirrors it statement for statement and adds one
exit that only REENTER rows use: band_reclaim, a close back on the band side of the abandoned band's mid, checked after
the stop and before the next-CHoCH exit on the same candle. tests/test_fz_parity.py runs simulate() on every Foundation
SETUP with the engine's own stop and requires every Foundation trade back, field for field, before any REENTER row is
trusted.

This module sees trade outcomes; fz.py does not. fz.py reaches it only through opener()'s callback, which answers with
the exit bar (or a refusal reason) and nothing else.
"""
import bisect


def view(r):
    """The frozen engine view fz.run() reads: swings as (kind, bar, price, conf) in confirmation order, setups as (bar,
    dir, CHoCH bar), CHoCHs as (bar, dir, level) and the protected level per bar. Nothing final-state (a swing's broken
    flag, a CHoCH window's end) and nothing about trades crosses over."""
    return dict(swings=[(s["k"], s["bar"], s["p"], s["conf"]) for s in r["sw"]],
                setups=[(x["i"], x["dir"], x["ch"]) for x in r["setups"]],
                chs=[(e["i"], e["dir"], e["lvl"]) for e in r["chs"]],
                prot=list(r["prot"]))


def stops(bars, swings, sl_rule):
    """stop(bar, dir, choch_bar): the Foundation stop rule evaluated at `bar`, as engine.run() does at the SETUP bar.
    prev_swing = latest confirmed swing low (long) / high (short) with conf <= bar; choch_candle = the CHoCH candle's
    low / high (the same at every bar); anything else = no stop."""
    conf = {k: [s[3] for s in swings if s[0] == k] for k in "HL"}
    price = {k: [s[2] for s in swings if s[0] == k] for k in "HL"}
    def stop(bar, direction, ch):
        up = direction == "up"
        if sl_rule == "choch_candle": return bars["l"][ch] if up else bars["h"][ch]
        if sl_rule == "prev_swing":
            k = "L" if up else "H"; j = bisect.bisect_right(conf[k], bar) - 1
            return price[k][j] if j >= 0 else None
        return None
    return stop


def refusal(bars, entry, direction, sl, touch, dead=False):
    """Why an entry at `entry`'s close cannot be taken, or None. 'wrong_side_stop' is the engine's own skip; with
    dead=True (REENTER) a stop the entry candle already traded through ('sl_dead_at_fill') refuses too."""
    if sl is None: return None
    up, c = direction == "up", bars["c"]
    if (sl >= c[entry]) if up else (sl <= c[entry]): return "wrong_side_stop"
    if dead:
        hit = ((bars["l"][entry] <= sl) if up else (bars["h"][entry] >= sl)) if touch else \
              ((c[entry] < sl) if up else (c[entry] > sl))
        if hit: return "sl_dead_at_fill"
    return None


def simulate(bars, entry, direction, sl, chi, touch, band=None, choch=None, dead=False):
    """One position from `entry`'s close, engine rules: exit at the stop (touch: the worse of the candle open and the
    stop; close mode: the close; a session's first candle: its close) checked on every candle after the entry, else at the
    close of the first CHoCH after the entry, else open at the last candle. With `band` (a REENTER), a close on the band
    side of its mid (long: below it, short: above it) exits at that close, after the stop and before the CHoCH exit.
    Returns the engine's trade dict, or None when refused (see refusal)."""
    t, o, h, l, c = (bars[k] for k in "tohlc")
    n, up = len(t), direction == "up"
    if refusal(bars, entry, direction, sl, touch, dead): return None
    def below(i, lvl): return (l[i] <= lvl) if touch else (c[i] < lvl)
    def above(i, lvl): return (h[i] >= lvl) if touch else (c[i] > lvl)
    j = bisect.bisect_right(chi, entry)
    nx = chi[j] if j < len(chi) else None
    last = nx if nx is not None else n - 1
    xi, px, reason = last, c[last], ("next_choch" if nx is not None else "open")
    if sl is not None or band is not None:
        for k in range(entry + 1, last + 1):
            if sl is not None:
                gap = o[k] <= sl if up else o[k] >= sl
                hit = below(k, sl) if up else above(k, sl)
                if gap or hit:                   # stop checked before any close-based exit on the same candle
                    xi, reason = k, "stop_loss"
                    if t[k][:10] != t[k - 1][:10]:
                        px = c[k]                # first candle of a session: no fill on the opening print
                    else:                        # worse of the candle open and the stop
                        px = o[k] if gap and touch else (sl if touch else c[k])
                    break
            if band is not None and ((c[k] < band["mid"]) if up else (c[k] > band["mid"])):
                xi, px, reason = k, c[k], "band_reclaim"
                break
    sg = 1 if up else -1
    return dict(entry=entry, exit=xi, exit_px=px, dir=direction, choch=choch, sl=sl, pts=sg * (px - c[entry]),
                open=reason == "open", exit_reason=reason)


def opener(bars, r, sl_rule, touch):
    """The open_position callback for fz.run(). TAKE = Foundation's own trade on that SETUP (its exit bar; refused when
    the engine skipped the SETUP for a wrong-side stop). REENTER = simulate() from the fill bar with the stop rule
    evaluated there and the band_reclaim exit. Only the exit bar (or the refusal reason) goes back to fz.py."""
    by_entry = {x["entry"]: x for x in r["trades"]}
    chi = [e["i"] for e in r["chs"]]
    ch_of = {x["i"]: x["ch"] for x in r["setups"]}
    stop = stops(bars, view(r)["swings"], sl_rule)
    def open_position(kind, entry_bar, direction, setup_i, band):
        if kind == "TAKE":
            x = by_entry.get(entry_bar)
            return x["exit"] if x is not None else "wrong_side_stop"
        sl = stop(entry_bar, direction, ch_of[setup_i])
        why = refusal(bars, entry_bar, direction, sl, touch, dead=True)
        if why: return why
        return simulate(bars, entry_bar, direction, sl, chi, touch, band=band, choch=ch_of[setup_i], dead=True)["exit"]
    return open_position


def build_trades(bars, r, fz_out, sl_rule, touch):
    """The FZ trade list in engine shape, sorted by entry. TAKE rows are Foundation's trade dicts copied; REENTER rows
    come from simulate() at the fill bar. Every row carries gate, zone_id, fill_used and reenter_reason; REENTER rows also
    setup_i, sl_bar ('setup' when the stop at the fill bar equals the SETUP-bar stop, else 'fill') and sl_in_band. The
    ledger row of each REENTER's SETUP gets sl_bar too."""
    by_entry = {x["entry"]: x for x in r["trades"]}
    chi = [e["i"] for e in r["chs"]]
    ch_of = {x["i"]: x["ch"] for x in r["setups"]}
    stop = stops(bars, view(r)["swings"], sl_rule)
    rows = {x["i"]: x for x in fz_out["ledger"]}
    out = []
    for kind, entry, d, si, band in fz_out["decisions"]:
        if kind == "TAKE":
            x = dict(by_entry[entry], gate="TAKE", zone_id=band["id"], fill_used="setup_close", reenter_reason=None)
        else:
            ch = ch_of[si]
            sl, sl0 = stop(entry, d, ch), stop(si, d, ch)
            x = simulate(bars, entry, d, sl, chi, touch, band=band, choch=ch, dead=True)
            assert x is not None, f"REENTER at bar {entry} was opened by fz.run but refused by simulate()"
            why, used = fz_out["reasons"][entry]
            x.update(gate="REENTER", zone_id=band["id"], fill_used=used, reenter_reason=why, setup_i=si,
                     sl_bar="setup" if sl == sl0 else "fill",
                     sl_in_band=sl is not None and band["lo"] <= sl <= band["hi"])
            if si in rows: rows[si]["sl_bar"] = x["sl_bar"]
        out.append(x)
    out.sort(key=lambda x: x["entry"])
    for a, b in zip(out, out[1:]):
        assert b["entry"] >= a["exit"], f"FZ positions overlap: entry {b['entry']} before exit {a['exit']}"
    return out
