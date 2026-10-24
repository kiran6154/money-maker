"""Strategy lab v2 server: the UI (ui/) and a JSON API over core.py. Backtests run in this process, one at a time, one
strategy per job (candle files and option chains stay loaded between runs, so a rerun is fast).

    python server.py              http://localhost:8780/   (127.0.0.1 only)
    python server.py 8790 --lan   also reachable from the local network

API
    GET  /api/strategies                                   every strategy: spec + its runs (meta)
    GET  /api/runs?code=ST1                                runs of one strategy, newest first
    GET  /api/result?code=&run=&type=&choice=              trades, stats, skipped, signals of one choice
    GET  /api/chart?code=&run=&type=&choice=&day=[&to=][&inst= | &atm=CE|PE]   sessions day..to of a run, computed on request
                                                                         (atm: that day's ATM option, traded or not)
    GET  /api/history?code=ST1                             the strategy's versions (definition, changes, results per run)
    GET  /api/candles?expiry=&strike=&right=CE|PE&from=&to=&tf=      one option contract's plain candles (the strategy page's free chart)
    GET  /api/explorer/meta | instruments?date=&tf= | chart?date=&inst=FUT|INDEX|OPT&code=&tf=&expiry=&strike=&right=
         &days_before=&holding=own|none|HH:MM             any day, any instrument (explorer.html)
    GET  /api/status                                       {busy, jobs: last 20}
    POST /api/backtest {code, what: MTD|1M|3M|6M|YTD|1Y|5Y|all|custom|defined:<run key>, from, to,
                        tf, underlying, square_off (null = positional, "HH:MM", absent = the strategy's), types: [...]}
Nothing here places orders or touches a broker.
"""
import http.server, json, os, sys, threading, time, traceback, urllib.parse, datetime as D, mimetypes
import core

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, "ui")
jobs, lock, wake = [], threading.Lock(), threading.Event()
run_lock = threading.Lock()          # the core runner is not re-entrant: backtests and charts take turns


def family_of(spec):
    """The card filter group of a strategy."""
    rule = spec["rules"].get("entry_rule", "setup_v1")
    if rule.startswith("fz"): return "FZ gate"
    if rule == "rl_v1": return "Learner"
    if rule == "c2c_v1": return "CHoCH to CHoCH"
    if rule == "rainbow_v1": return "Rainbow"
    return "Managed exits" if core.position_of(spec)["exit"] == "position" else "Foundation"


def spec_view(m):
    s = dict(m.SPEC)
    s["backtests"] = [dict(b, run=core.run_key(b, m.SPEC)[0]) for b in s["backtests"]]
    s["family"] = family_of(m.SPEC)
    s["position"] = core.position_of(m.SPEC)
    h = core.history(m.SPEC["code"])["versions"]
    s["version"] = h and dict(version=h[-1]["version"], at=h[-1]["at"], changes=h[-1]["changes"])
    return s


# ------------------------------------------------------------------ the strategy tree (ui/lineage.html)
_SKIP = {"code", "name", "description", "backtests", "notes", "capital", "types", "lot_size"}


def _flat(d, pre=""):
    out = {}
    for k, v in d.items():
        if k in _SKIP or k.startswith("_"): continue
        if isinstance(v, dict): out.update(_flat(v, f"{pre}{k}."))
        else: out[pre + k] = v
    return out


def spec_diff(child, parent):
    """Every SPEC setting that differs between a strategy and the one it was derived from: [(key, parent's, its own)]."""
    a, b = _flat(parent), _flat(child)
    show = lambda v: "–" if v is None else json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)
    return [[k, show(a.get(k)) if k in a else "(not set)", show(b.get(k)) if k in b else "(not set)"]
            for k in sorted(set(a) | set(b)) if a.get(k, "\0") != b.get(k, "\0")]


def exits_of(spec):
    """Stop, targets, trail and square-off of a strategy, in one line (what 'did we try 1:1?' is read from)."""
    r, P = spec["rules"], core.position_of(spec)
    rule = r.get("entry_rule", "setup_v1")
    sq = f"flat by {P['square_off']}" if P.get("square_off") else "positional (held overnight)"
    oc = core.DATA.get("intraday_close") or []
    if P.get("square_off") and oc: sq += f" ({oc[0]['time']} from {oc[0]['from']})"
    if rule == "c2c_v1":
        c = spec["c2c"]
        return f"stop {c['stop_pct']}% of premium then a {c['trail_pts']}-pt trail ({c.get('stop_fill', 'close')}); exit on a bullish flip or the {c['ladder']['time']} ladder; positional"
    if rule == "rl_v1":
        L = spec["rl"]
        return f"the learner picks the stop ({' / '.join(str(x) for x in L['stops_pts'])} pts) and an exit profile ({', '.join(L['profiles'])}); reward {L['reward']}"
    if P["exit"] == "position":
        st = P["stop"] or {}
        stop = ("the signal's own stop (" + {"choch_candle": "CHoCH candle", "prev_swing": "previous swing"}.get(r.get("sl_rule"), "set by the entry rule") + ")"
                if st.get("from") == "signal" else f"{st.get('futures_pts')} pts on futures / {st.get('option_pct')}% of premium on options")
        tg = ", ".join(f"{x['lots']} lot at {x['target_r']}R" if "target_r" in x else f"{x['lots']} lot at +{x['target_pts']} pts" for x in P["scale_out"]) or "none"
        tr = f"from {P['trail']['start_r']}R, {P['trail']['lag_r']}R behind" if P.get("trail") else "none"
        return (f"{P['lots']} lot(s); stop = 1R = {stop}; targets: {tg}; trail: {tr}"
                + (f"; stop and reverse x{P['reverse']['max']}" if P.get("reverse") else "") + f"; {sq}")
    stop = {"prev_swing": "previous swing", "choch_candle": "CHoCH candle low / high", "none": "none"}.get(r.get("sl_rule"), r.get("sl_rule"))
    return f"{P['lots']} lot; stop: {stop}; no target; exit at the stop or the next CHoCH; {sq}"


def headline(code, spec):
    """The widest stored backtest of a strategy: its All-data run if there is one, else its default; futures first."""
    base = os.path.join(core.RESULTS, code)
    runs = [r for r in (os.listdir(base) if os.path.isdir(base) else []) if os.path.exists(os.path.join(base, r, "meta.json"))]
    if not runs: return None
    dflt = next((core.run_key(b_, spec)[0] for b_ in spec["backtests"] if b_.get("default")), None)
    plain = [r for r in runs if r.startswith("all-data") and not r.endswith(("_idx", "_pos", "_intra"))]
    order = sorted(plain, key=lambda r: r != f"all-data_{core.TF_LABEL[spec['timeframe']]}") + ([dflt] if dflt in runs else []) + runs
    best = None
    for r in order:
        m = json.load(open(os.path.join(base, r, "meta.json"), encoding="utf-8"))
        for typ, want in (("FUT", "-"), ("OPT_NATIVE", "W-SCAN"), ("OPT_FUT_SIGNAL", f"W-{spec['options'].get('strike_default')}")):
            tm = m["types"].get(typ) or {}
            ch = (tm.get("choices") or {})
            c = ch.get(want) or (next(iter(ch.values())) if ch else None)
            if tm.get("status") == "ok" and c and c.get("trades"):
                return dict(run=r, label=m["label"], type=tm.get("label") or typ, choice=want if want in ch else next(iter(ch)), date_from=tm.get("date_from"),
                            date_to=m.get("date_to"), trades=c["trades"], wins=c.get("wins"), net=c.get("net_inr"), pf=c.get("pf"), t=c.get("t_stat"), at=m.get("at"))
        best = best or dict(run=r, label=m["label"], trades=0)
    return best


def lineage_view():
    mods = core.load_strategies(); L = core.family("lineage")
    out = []
    for code, m in mods.items():
        sp = m.SPEC; par, change = L.LINEAGE.get(code, (None, "(no entry in strategies/lineage.py yet)"))
        out.append(dict(code=code, name=sp["name"], family=family_of(sp), timeframe=sp["timeframe"], parent=par if par in mods else None, change=change,
                        diff=spec_diff(sp, mods[par].SPEC) if par in mods else [], exits=exits_of(sp), types=list(getattr(m, "TYPES", ("FUT", "OPT_FUT_SIGNAL", "OPT_NATIVE"))),
                        result=headline(code, sp),
                        studies=[dict(kind=k, what=w, result=r, ref=ref) for c_, k, w, r, ref in L.STUDIES if c_ == code]))
    return dict(nodes=out, intraday_close=core.DATA.get("intraday_close", []))


def submit(q):
    mods = core.load_strategies()
    code = str(q.get("code", ""))
    if code not in mods: raise ValueError(f"unknown strategy {code!r}")
    spec = mods[code].SPEC
    what = str(q.get("what", ""))
    if what.startswith("defined:"):
        rk = what.split(":", 1)[1]
        bt = next((b for b in spec["backtests"] if core.run_key(b, spec)[0] == rk), None)
        if bt is None: raise ValueError(f"{code} has no backtest {rk}")
    else:
        sq = q["square_off"] if "square_off" in q else "keep"
        if sq == "none": sq = None
        bt = core.custom_backtest(spec, what, q.get("from"), q.get("to"), q.get("tf") or None, q.get("underlying") or None, sq,
                                  (q.get("label") or "").strip() or None)
    types = [t for t in (q.get("types") or []) if t in {x for x, _, _ in core.TYPES}] or None
    with lock:
        same = next((j for j in jobs if j["code"] == code and j["bt"] == bt and j["types"] == types
                     and j["state"] in ("queued", "running")), None)
        if same: return same
        j = dict(id=f"{D.datetime.now():%H%M%S}-{len(jobs) + 1}", code=code, bt=bt, types=types, state="queued",
                 queued=time.time(), started=None, ended=None, seconds=None, run=None, error=None, log=[])
        jobs.append(j)
    wake.set()
    return j


def worker():
    while True:
        wake.wait(); wake.clear()
        while True:
            with lock: j = next((x for x in jobs if x["state"] == "queued"), None)
            if not j: break
            j.update(state="running", started=time.time())
            try:
                with run_lock:
                    m = core.backtest(j["code"], j["bt"], j["types"], log=lambda s: j["log"].append(s))
                j.update(state="done", run=m["run"])
            except Exception as e:
                j.update(state="failed", error=f"{type(e).__name__}: {e}")
                traceback.print_exc()
            j.update(ended=time.time(), seconds=round(time.time() - j["started"], 2))


def public_job(j):
    return {k: v for k, v in j.items() if k != "bt"} | {"label": j["bt"].get("label")}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        if self.path.startswith("/api/backtest"): sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % a))

    def reply(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
        try:
            self.end_headers(); self.wfile.write(b)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass                                        # the browser left (page change, newer request): nothing to send

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/api/strategies":
                mods = core.load_strategies()
                return self.reply(200, [dict(spec=spec_view(m), runs=core.list_runs(c)) for c, m in mods.items()])
            if u.path == "/api/runs":
                return self.reply(200, core.list_runs(q["code"]))
            if u.path == "/api/result":
                f = os.path.join(core.RESULTS, q["code"], q["run"], q["type"], f"{q['choice']}.json")
                if ".." in f or not os.path.exists(f): return self.reply(404, {"error": "no such result"})
                return self.reply(200, open(f, "rb").read())
            if u.path == "/api/chart":
                with run_lock:
                    return self.reply(200, core.chart(q["code"], q["run"], q["type"], q["choice"], q["day"], q.get("inst") or None,
                                                      q.get("to") or None, q.get("atm") or None))
            if u.path == "/api/history":
                return self.reply(200, core.history(q["code"]))
            if u.path == "/api/explorer/meta":
                return self.reply(200, core.explorer_meta())
            if u.path == "/api/explorer/expiries":
                with run_lock:
                    return self.reply(200, core.explorer_expiries(q.get("tf") or "minute"))
            if u.path == "/api/lineage":
                return self.reply(200, lineage_view())
            if u.path == "/api/config":
                return self.reply(200, dict(intraday_close=core.DATA.get("intraday_close", [])))
            if u.path == "/api/explorer/straddle":
                with run_lock:
                    return self.reply(200, core.explorer_straddle(q["code"], q["from"], q["to"], q.get("tf") or "minute"))
            if u.path == "/api/candles":
                with run_lock:
                    return self.reply(200, core.plain_candles(q["expiry"], q["strike"], q["right"], q["from"], q.get("to") or q["from"],
                                                              q.get("tf") or "minute"))
            if u.path == "/api/explorer/strikes":
                with run_lock:
                    return self.reply(200, core.explorer_strikes(q["expiry"], q.get("tf") or "minute", q.get("date") or None))
            if u.path == "/api/explorer/instruments":
                with run_lock:
                    return self.reply(200, core.explorer_instruments(q["date"], q.get("tf") or "minute"))
            if u.path == "/api/explorer/chart":
                with run_lock:
                    return self.reply(200, core.explorer_chart(q["date"], q["inst"], q["code"], q.get("tf") or "minute",
                                                               q.get("expiry") or None, q.get("strike") or None, q.get("right") or None,
                                                               int(q.get("days_before") or 1), q.get("holding") or "own",
                                                               q.get("start") or "days", q.get("end") or "date",
                                                               float(q.get("liq_pct") or 10), int(q.get("days_after") or 0)))
            if u.path == "/api/status":
                with lock:
                    return self.reply(200, dict(busy=any(j["state"] in ("queued", "running") for j in jobs),
                                                jobs=[public_job(j) for j in reversed(jobs[-20:])]))
            p = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            f = os.path.normpath(os.path.join(UI, p))
            if not f.startswith(UI) or not os.path.isfile(f): return self.reply(404, {"error": "not found"})
            ext = os.path.splitext(f)[1].lower()           # Windows' registry can map .js to text/plain: modules would not load
            ctype = {".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8",
                     ".svg": "image/svg+xml"}.get(ext) or mimetypes.guess_type(f)[0] or "application/octet-stream"
            return self.reply(200, open(f, "rb").read(), ctype)
        except (KeyError, ValueError) as e:
            return self.reply(400, {"error": f"{type(e).__name__}: {e}"})
        except Exception as e:
            traceback.print_exc()
            return self.reply(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            q = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/backtest": return self.reply(200, public_job(submit(q)))
            return self.reply(404, {"error": "not found"})
        except (ValueError, KeyError) as e:
            return self.reply(400, {"error": str(e)})


def main():
    args = sys.argv[1:]
    port = int(next((a for a in args if a.isdigit()), 8780))
    host = "0.0.0.0" if "--lan" in args else "127.0.0.1"
    threading.Thread(target=worker, daemon=True).start()
    srv = http.server.ThreadingHTTPServer((host, port), Handler)
    print(f"strategy lab v2 on http://{'localhost' if host == '127.0.0.1' else host}:{port}/")
    srv.serve_forever()


if __name__ == "__main__":
    main()
