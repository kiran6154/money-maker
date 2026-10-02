"""Strategy lab v2 server: the UI (ui/) and a JSON API over core.py. Backtests run in this process, one at a time, one
strategy per job (candle files and option chains stay loaded between runs, so a rerun is fast).

    python server.py              http://localhost:8780/   (127.0.0.1 only)
    python server.py 8790 --lan   also reachable from the local network

API
    GET  /api/strategies                                   every strategy: spec + its runs (meta)
    GET  /api/runs?code=ST1                                runs of one strategy, newest first
    GET  /api/result?code=&run=&type=&choice=              trades, stats, skipped, signals of one choice
    GET  /api/chart?code=&run=&type=&choice=&day=[&inst=]  one session's chart, computed on request
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


def spec_view(m):
    s = dict(m.SPEC)
    s["backtests"] = [dict(b, run=core.run_key(b, m.SPEC)[0]) for b in s["backtests"]]
    return s


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
        self.end_headers(); self.wfile.write(b)

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
                    return self.reply(200, core.chart(q["code"], q["run"], q["type"], q["choice"], q["day"], q.get("inst") or None))
            if u.path == "/api/status":
                with lock:
                    return self.reply(200, dict(busy=any(j["state"] in ("queued", "running") for j in jobs),
                                                jobs=[public_job(j) for j in reversed(jobs[-20:])]))
            p = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            f = os.path.normpath(os.path.join(UI, p))
            if not f.startswith(UI) or not os.path.isfile(f): return self.reply(404, {"error": "not found"})
            return self.reply(200, open(f, "rb").read(), mimetypes.guess_type(f)[0] or "application/octet-stream")
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
