"""Rainbow ribbon intraday (entry_rule rainbow_v1, Strategies 29-30): trade the near-month futures when price closes
outside a fanned moving-average ribbon, on its own 1-minute or 5-minute candles, flat by the square-off.

The ribbon (the file's `rainbow` block picks one)
  widner  Mel Widner's Rainbow Charts: line 1 = SMA(period) of the close, line k = SMA(period) of line k-1, `levels` lines
          (the classic is 10 lines of period 2). The Rainbow Oscillator = 100 x (close - mean of the lines) / (highest
          close - lowest close over `lookback` candles): how far price sits from the ribbon, in units of the recent range.
  ema     `periods` exponential averages of the close (ascending periods), the same oscillator.
  A line's value at candle i uses candles <= i only; an EMA is seeded with the simple average of its first `period`
  closes, so its first values depend on where the candles start (each backtest warms up on its own warmup_days, like
  the engine). The band = [lowest line, highest line]; the fan is bullish when every faster line is above the next slower
  one, bearish when every faster line is below it.

Entry (every number is in the `rainbow` block; nothing is hard-coded)
  A long signal is a candle whose close is above the whole band when the previous candle's close was not (a fresh close
  outside the band); a short signal mirrors it below the band. Then:
    fan       "full": the fan must be bullish (bearish) on the signal candle; "none": no fan condition
    osc_min   the oscillator must be at least osc_min (at most -osc_min for a short)
    trigger   "cross": nothing more. "pullback": a re-emergence - within the last `pullback_bars` candles price had
              already closed outside the band on the trade's side and then came back to or into it (the fresh-close test
              says the previous close was not outside), and the ribbon's far edge kept its slope over those candles (the
              bottom line for a long: bot[i] > bot[i - N]; the top line fallen for a short). The first break out of a
              range is a cross, not a pullback. (A touch of the band is implied by any fresh close outside it, so a
              touch is not the test; nor is the fan's order, which the fastest lines of a 2-period ribbon swap on any dip.)
  The ribbon runs through session opens (no reset at 09:15): the first candles of a session read the previous close.
  The entry candle's previous close is the previous candle's, whichever session it belongs to.
    entry_from / entry_until  signals only in this session window (HH:MM, from inclusive, until exclusive)
  The entry is the signal candle's close (the lab's rule), on the near-month futures contract of that time.

Exits - the lab's position handling decides, from the file's `position` block:
  exit "strategy": the stop is the far side of the band at the signal candle (the bottom line for a long): a candle
      whose low touches it exits at the stop, at the open when the candle opens beyond it, at the close on a session's
      first candle (no fill on the opening print); `exit` "band" also closes the position at the first close back through
      the far side of the band (that candle's close); the square-off (position.square_off) cuts what is still open;
      scale-out targets in points apply (lab.tranches).
  exit "position": the lab's managed exits (position.stop.futures_pts, R-based scale-out, trail, square-off) from the
      entry; the ribbon plays no part after the entry (lab.manage).
  One position per contract at a time (the lab's strike lock): a signal while one is open is skipped with the reason.
  The contract's last candle in the data ends a position (position mode: lab.manage's cap; strategy mode: the exit is
  moved there, reason 'expiry'); on the expiry day lab.manage labels lots still open at the 15:25 square-off 'expiry'
  rather than 'eod' (the contract's end is checked first), so an intraday run shows a few 'expiry' exits.

Chart: the ribbon's lines are drawn on the futures chart (the Rainbow layer); the engine's swings / CHoCH / AVWAP overlays
stay, for reading the structure around the entries - they do not decide anything here.

v1 scope: the Futures type on the futures' own candles; option types and index signals are refused with a reason.
Costs, the strike lock and the fill rules are the lab's. The variant in each strategy file was picked by the grid in
studies/rainbow_grid.py (STRATEGY_ANALYSIS_TODO S53) on Jan-Jun 2026 and checked on Jul-Sep 2026.
"""
import bisect, hashlib, json, os
import engine
import lab

RULES = ("rainbow_v1",)
MODULES = ("rainbow.py",)
FUT_WHY = "rainbow v1 trades the near-month futures on their own candles; option types and index signals are not part of it yet"
KINDS = ("widner", "ema")
TRIGGERS = ("cross", "pullback")
FANS = ("full", "none")
EXITS = ("band", "none")
KEYS = {"kind", "levels", "period", "periods", "trigger", "fan", "osc_min", "lookback", "pullback_bars", "entry_from", "entry_until",
        "exit", "notes"}
NEED = {"kind", "trigger", "fan", "osc_min", "lookback", "pullback_bars", "entry_from", "entry_until", "exit"}


def rainbow_rule(st):
    return str(st.get("entry_rule") or "") in RULES


def code_hash():
    """sha1[:16] of this module (line endings normalised): the code a rainbow result comes from."""
    h = hashlib.sha1()
    for f in MODULES: h.update(open(os.path.join(lab.HERE, f), "rb").read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


# ---------------------------------------------------------------- configuration (strategy file `rainbow` block)
def _hm(s):
    return isinstance(s, str) and len(s) == 5 and s[2] == ":" and s[:2].isdigit() and s[3:].isdigit() and 0 <= int(s[:2]) < 24 and 0 <= int(s[3:]) < 60


def config_of(spec):
    """The strategy file's `rainbow` block, validated (see the module docstring for what each key does)."""
    c = spec.get("rainbow")
    if not isinstance(c, dict): raise ValueError("entry_rule rainbow_v1 needs a 'rainbow' block")
    if not NEED <= set(c) <= KEYS: raise ValueError(f"keys are {sorted(NEED)} (+ optional {sorted(KEYS - NEED)}; got {sorted(c)})")
    if c["kind"] not in KINDS: raise ValueError(f"kind must be one of {KINDS}")
    if c["kind"] == "widner":
        if not (isinstance(c.get("levels"), int) and c["levels"] >= 2): raise ValueError("widner: levels is a whole number >= 2")
        if not (isinstance(c.get("period"), int) and c["period"] >= 2): raise ValueError("widner: period is a whole number >= 2")
    else:
        ps = c.get("periods")
        if not (isinstance(ps, list) and len(ps) >= 2 and all(isinstance(p, int) and p >= 1 for p in ps) and ps == sorted(ps) and len(set(ps)) == len(ps)):
            raise ValueError("ema: periods is an ascending list of at least two distinct whole numbers >= 1")
    if c["trigger"] not in TRIGGERS: raise ValueError(f"trigger must be one of {TRIGGERS}")
    if c["fan"] not in FANS: raise ValueError(f"fan must be one of {FANS}")
    if not (isinstance(c["osc_min"], (int, float)) and 0 <= c["osc_min"] <= 100): raise ValueError("osc_min is a number in 0..100")
    if not (isinstance(c["lookback"], int) and c["lookback"] >= 2): raise ValueError("lookback is a whole number >= 2")
    if not (isinstance(c["pullback_bars"], int) and c["pullback_bars"] >= 1): raise ValueError("pullback_bars is a whole number >= 1")
    if not (_hm(c["entry_from"]) and _hm(c["entry_until"]) and c["entry_from"] < c["entry_until"]):
        raise ValueError("entry_from / entry_until are HH:MM with entry_from < entry_until")
    if c["exit"] not in EXITS: raise ValueError(f"exit must be one of {EXITS}")
    if "notes" in c and not isinstance(c["notes"], str): raise ValueError("notes is text")
    return c


# ---------------------------------------------------------------- the ribbon
def sma(x, p):
    """Simple average of the last p values; None until p values are defined (a None input restarts the count). The sum is
    taken afresh each candle (no running sum), so a value depends on its p inputs alone: a window that starts earlier
    gives the same lines, band and fan - a running sum would let floating-point drift decide their ties."""
    out, win = [None] * len(x), []
    for i, v in enumerate(x):
        if v is None:
            win = []; continue
        win.append(v)
        if len(win) > p: win.pop(0)
        if len(win) == p: out[i] = sum(win) / p
    return out


def ema(x, p):
    """Exponential average, alpha 2 / (p + 1), seeded with the simple average of the first p values."""
    out, a, seed, prev = [None] * len(x), 2.0 / (p + 1), [], None
    for i, v in enumerate(x):
        if prev is None:
            seed.append(v)
            if len(seed) == p: prev = sum(seed) / p; out[i] = prev
            continue
        prev = prev + a * (v - prev); out[i] = prev
    return out


def lines_of(c, cfg):
    """The ribbon's lines, fastest first: widner = `levels` recursive SMA(period) of the close; ema = EMA(p) per period."""
    if cfg["kind"] == "widner":
        out, src = [], c
        for _ in range(cfg["levels"]):
            src = sma(src, cfg["period"]); out.append(src)
        return out
    return [ema(c, p) for p in cfg["periods"]]


def ribbon(bars, cfg):
    """Everything the entry reads, per candle: lines, top / bot of the band, bullish / bearish fan, the oscillator, and
    `start` = the first candle where every line is defined."""
    c, h, l = bars["c"], bars["h"], bars["l"]
    n = len(c)
    L = lines_of(c, cfg)
    start = next((i for i in range(n) if all(ln[i] is not None for ln in L)), n)
    top, bot, fan_up, fan_dn, osc = [None] * n, [None] * n, [False] * n, [False] * n, [0.0] * n
    hh, ll = [None] * n, [None] * n
    for i in range(start, n):
        vals = [ln[i] for ln in L]
        top[i], bot[i] = max(vals), min(vals)
        fan_up[i] = all(vals[k] > vals[k + 1] for k in range(len(vals) - 1))
        fan_dn[i] = all(vals[k] < vals[k + 1] for k in range(len(vals) - 1))
        j0 = max(0, i - cfg["lookback"] + 1)
        hi, lo = max(c[j0:i + 1]), min(c[j0:i + 1])
        osc[i] = 100.0 * (c[i] - sum(vals) / len(vals)) / (hi - lo) if hi > lo else 0.0
    return dict(lines=L, top=top, bot=bot, fan_up=fan_up, fan_dn=fan_dn, osc=osc, start=start)


# ---------------------------------------------------------------- signals and trades
def signals(bars, cfg, R=None):
    """Every entry signal in time order, each from candles <= its own: dict(i, dir, top, bot, osc, fan, reentry)."""
    R = R or ribbon(bars, cfg)
    t, c, h, l = bars["t"], bars["c"], bars["h"], bars["l"]
    top, bot, osc = R["top"], R["bot"], R["osc"]
    n, N, out = len(c), cfg["pullback_bars"], []
    for i in range(R["start"] + 1, n):
        hm = t[i][11:16]
        if not (cfg["entry_from"] <= hm < cfg["entry_until"]): continue
        for d, sg, fan in (("up", 1, R["fan_up"]), ("down", -1, R["fan_dn"])):
            now = c[i] > top[i] if d == "up" else c[i] < bot[i]
            prev = c[i - 1] > top[i - 1] if d == "up" else c[i - 1] < bot[i - 1]
            if not now or prev: continue                                  # a fresh close outside the band
            if cfg["fan"] == "full" and not fan[i]: continue
            if sg * osc[i] < cfg["osc_min"]: continue
            reentry = None
            if cfg["trigger"] == "pullback":
                j0 = i - N
                if j0 < R["start"]: continue
                slope_ok = bot[i] > bot[j0] if d == "up" else top[i] < top[j0]   # the ribbon's far edge kept its slope
                if not slope_ok: continue
                # a re-emergence: a close outside the band on this side within the last N candles, before the dip that the
                # fresh-close test proves (the previous close was not outside); the first break of a range is not a pullback
                reentry = any((c[j] > top[j]) if d == "up" else (c[j] < bot[j]) for j in range(j0, i - 1))
                if not reentry: continue
            out.append(dict(i=i, dir=d, top=top[i], bot=bot[i], osc=round(osc[i], 1), fan=fan[i], reentry=reentry))
    return out


def trades_of(bars, sig, cfg, R):
    """Engine-shaped trades for the strategy-exit mode: entry at the signal close; the stop is the band's far side at the
    signal candle (touch: at the stop, at the open beyond it, at the close on a session's first candle); `exit` "band"
    also closes at the first close back through the far side of the band. Still open at the last candle: 'open'.
    (In position mode the lab's manage() replaces every exit here and the stop is position.stop; the entry candle and
    the direction are what it keeps.)"""
    t, o, h, l, c = bars["t"], bars["o"], bars["h"], bars["l"], bars["c"]
    top, bot = R["top"], R["bot"]
    n, out = len(c), []
    for s in sig:
        i, up = s["i"], s["dir"] == "up"
        sg = 1 if up else -1
        sl = s["bot"] if up else s["top"]
        xi, px, why = n - 1, c[n - 1], "open"
        for k in range(i + 1, n):
            gap = o[k] <= sl if up else o[k] >= sl
            hit = l[k] <= sl if up else h[k] >= sl
            first = t[k][:10] != t[k - 1][:10]
            if gap or hit:
                xi, why, px = k, "stop_loss", (c[k] if first else (o[k] if gap else sl)); break
            if cfg["exit"] == "band" and ((c[k] < bot[k]) if up else (c[k] > top[k])):
                xi, why, px = k, "band_exit", c[k]; break
        out.append(dict(entry=i, exit=xi, exit_px=px, dir=s["dir"], choch=i, sl=sl, pts=sg * (px - c[i]), open=why == "open",
                        exit_reason=why, osc=s["osc"], fan=s["fan"], reentry=s["reentry"]))
    return out


# ---------------------------------------------------------------- the run
def run_variant(st, cs):
    """Lab-shaped result for a rainbow futures row: {'-': dict(trades, skipped, signals, charts, rainbow)} for the window
    st['date_from'] .. st['date_to'] (the engine's warm-up sessions before it feed the ribbon)."""
    if st["variant"] != "FUT" or (st.get("underlying") or "FUT") != "FUT":
        return {ch: dict(trades=[], skipped=[dict(why=FUT_WHY)], signals=[], charts=[]) for ch in lab.choice_keys(st)}
    cfg = json.loads(st["rainbow_json"])
    bars, s0 = engine.load(st["data_file"], st["date_from"], st["date_to"], st["warmup_days"])
    p = dict(break_mode=st["break_mode"], choch_mode=st.get("choch_mode") or st["break_mode"], avwap_weight=st["avwap_weight"], sl_rule=st["sl_rule"])
    r = engine.run(bars, p)                       # structure overlays and the signals list only; the ribbon decides the trades
    t, o, h, l, c = bars["t"], bars["o"], bars["h"], bars["l"], bars["c"]
    R = ribbon(bars, cfg)
    sig = signals(bars, cfg, R)
    X = trades_of(bars, sig, cfg, R)
    contracts, clast = lab.fut_contracts()
    pmode, lock = lab.position_mode(st), lab.StrikeLock(st)
    trs, skipped, marks = [], [], []
    n_sig = n_lock = n_late = 0
    for x in X:
        if x["entry"] < s0: continue
        n_sig += 1
        te, bull = t[x["entry"]], x["dir"] == "up"
        c_, e_ = contracts.get(te, ("NIFTY FUT", None))
        rec = dict(dir=x["dir"], signal="BULLISH" if bull else "BEARISH", position="LONG" if bull else "SHORT", opt_type="FUT",
                   kind="FUT", instrument=c_, strike=None, expiry=e_, choch_time=te, entry_time=te, exit_time=t[x["exit"]],
                   exit_reason=x["exit_reason"], open=x["open"], sl=round(x["sl"], 2), entry_px=c[x["entry"]], exit_px=x["exit_px"],
                   und_entry=None, und_exit=None, osc=x["osc"])
        sq = lab.square_off_at(st, te)
        if sq and te >= sq:
            n_late += 1
            skipped.append(dict(entry_time=te, position=rec["position"], dir=x["dir"], why=f"entry at or after the square-off time ({lab.position_cfg(st)['square_off']})")); continue
        u = lock.held(c_, te)
        if u:
            n_lock += 1
            skipped.append(dict(entry_time=te, position=rec["position"], dir=x["dir"], why=f"strike locked: {c_} open until {u}")); continue
        cap = t[-1]
        if e_ and c_ in clast:
            cap = min(cap, clast[c_])
            if not pmode and rec["exit_time"] > clast[c_]:      # the contract's last candle ends the position
                j = bisect.bisect_right(t, clast[c_]) - 1
                rec.update(exit_time=t[j], exit_px=c[j], exit_reason="expiry", open=False)
        if not pmode: lab.eod_cut(st, rec, t, c)
        O = (t, o, h, l, c)
        parts = lab.manage(st, rec, *O, cap, e_) if pmode else lab.tranches(st, rec, *O)
        if pmode:
            cur_rec, cur, depth = rec, parts, 0
            while (rv := lab.reversal_of(st, cur, depth)):
                cur_rec = lab.flip(cur_rec, rv[0], rv[1], depth); depth += 1
                cur = [lab.rev_tag(q) for q in lab.manage(st, cur_rec, *O, cap, e_)]; parts = parts + cur
        lock.hold(c_, max(q["exit_time"] for q in parts), any(q["open"] for q in parts))
        for tr in parts:
            lab.excursion(t, h, l, tr, tr["position"] == "LONG")
            lab.price_trade(st, cs, tr)
            j0 = max(bisect.bisect_right(t, tr["entry_time"]) - 1, 0); jx = max(bisect.bisect_right(t, tr["exit_time"]) - 1, 0)
            marks.append([lab.ts(t[j0]), tr["entry_px"], lab.ts(t[jx]), tr["exit_px"], tr["dir"], round(tr["pts"], 2), tr["open"], tr["sl"],
                          tr["exit_reason"], tr["position"] + (f" · {tr['tranche']}" if tr["tranche"] else ""), tr["dir"]])
            trs.append(tr)
    signals_ = [dict(time=t[e["i"]], dir=e["dir"], flipped=e["flip"], lvl=e["lvl"], av=e["av"],
                     hi=(t[e["hi"]["bar"]], e["hi"]["p"]) if e["hi"] else None, lo=(t[e["lo"]["bar"]], e["lo"]["p"]) if e["lo"] else None,
                     setup=None) for e in r["chs"] if e["i"] >= s0]
    day_span, charts = {}, []
    for i in range(s0, len(t)): day_span.setdefault(t[i][:10], [i, i])[1] = i
    for d, (i0, i1) in day_span.items():
        lo_, hi_ = lab.ts(t[i0]), lab.ts(t[i1])
        mk = [m for m in marks if m[0] <= hi_ and m[2] >= lo_]
        inday = [m for m in mk if lo_ <= m[0] <= hi_]
        n_pos = len({m[0] for m in inday})                   # positions, not lot exits
        pay = lab.chart(bars, r, i0, i1, mk)
        pay["RB"] = [[[lab.ts(t[i]), round(ln[i], 2)] for i in range(i0, i1 + 1) if ln[i] is not None] for ln in R["lines"]]
        charts.append(dict(pay, day=d, kind="signal",
                           label=f"{d} · futures" + (f" · {n_pos} position{'s' * (n_pos > 1)} · {sum(m[5] for m in inday):+.1f} pts" if inday else "")))
    why_n = {}
    for x in trs: why_n[x["exit_reason"]] = why_n.get(x["exit_reason"], 0) + 1
    payload = dict(config=cfg, lines=len(R["lines"]), signals=n_sig, taken=sum(1 for x in X if x["entry"] >= s0) - n_lock - n_late,
                   positions=len({(x["entry_time"], x["position"]) for x in trs}), lot_exits=len(trs),
                   locked=n_lock, after_square_off=n_late, exits=why_n,
                   entries_by_hour={hr: sum(1 for x in trs if x["entry_time"][11:13] == hr and x["tranche"] in ("", "T1 1R", "rest (trail)", "rest")) for hr in ("09", "10", "11", "12", "13", "14")},
                   osc_at_signals=sorted(round(x["osc"], 1) for x in X if x["entry"] >= s0),
                   note="entries = a fresh close outside the ribbon with the file's fan / oscillator / trigger rules; one position per "
                        "contract; exits per the position block (strategy: band stop and band exit; position: the lab's managed exits)")
    return {"-": dict(trades=trs, skipped=skipped, signals=signals_, charts=charts, rainbow=payload)}
