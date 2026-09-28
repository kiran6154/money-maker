"""Dashboard server with a backtest queue, so a backtest period can be added and run from the page without anyone at a terminal.

    python serve.py            # http://localhost:8766/dashboard.html  (listens on 127.0.0.1 only)
    python serve.py 8800
    python serve.py 8770 --lan         # also reachable from a phone on the same Wi-Fi / over Tailscale (away from home)
    python serve.py 8770 --host 100.x.y.z   # only on that address
    python serve.py 8770 --tailscale   # only on this PC's Tailscale address: your own devices, from anywhere
Only dashboard.html and web/*.json are served (never the database, strategy files, tools or logs).

Static files come from this folder (as `python -m http.server` did). The API runs lab.py, one job at a time:
    GET  /api/status                       {"api": true, "busy": bool, "jobs": [last 10 jobs, newest first]}
    POST /api/backtest  {"code": "ST1", "what": "MTD|1M|3M|6M|YTD|1Y|5Y|all|custom", "from": "YYYY-MM-DD", "to": "YYYY-MM-DD",
                         "tf": "minute|3minute|5minute|15minute|30minute" (optional), "underlying": "FUT|INDEX" (optional), "square_off": null|"HH:MM" (optional),
                         "label": "..." (optional)}
                        -> `lab.py backtest ...`: adds the backtest to the strategy's file (if it is not there yet), then a
                           full cached run (only what is missing or changed is computed) that republishes dashboard.html
    POST /api/run       {}  -> `lab.py`: recompute whatever is missing or stale, republish
A job's output goes to cache/jobs/<id>.log; the page polls /api/status and reloads when its job finishes.
Nothing here places orders or touches a broker: lab.py only reads candle files.
"""
import http.server, json, os, re, subprocess, sys, threading, time, datetime as D, functools, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(HERE, "cache", "jobs")
PRESETS = ("MTD", "1M", "3M", "6M", "YTD", "1Y", "5Y")
TFS = ("minute", "3minute", "5minute", "15minute", "30minute")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

jobs, lock, wake = [], threading.Lock(), threading.Event()


def codes():
    out = set()
    for f in os.listdir(os.path.join(HERE, "strategies")):
        if f.endswith(".json"):
            try: out.add(json.load(open(os.path.join(HERE, "strategies", f), encoding="utf-8"))["code"])
            except (ValueError, KeyError): pass
    return out


def backtest_args(q):
    """lab.py arguments for a /api/backtest request, or raise ValueError with what is wrong."""
    code, what = str(q.get("code", "")), str(q.get("what", ""))
    if code not in codes(): raise ValueError(f"unknown strategy code {code!r}")
    if what in PRESETS or what == "all": args = [code, what]
    elif what == "custom":
        a, b = str(q.get("from", "")), str(q.get("to", ""))
        if not (DATE.match(a) and DATE.match(b)) or a > b: raise ValueError("custom needs from <= to as YYYY-MM-DD")
        args = [code, a, b]
    else: raise ValueError(f"what must be one of {PRESETS + ('all', 'custom')}")
    if q.get("tf"):
        if q["tf"] not in TFS: raise ValueError(f"tf must be one of {TFS}")
        args += ["--tf", q["tf"]]
    if q.get("underlying"):
        if q["underlying"] not in ("FUT", "INDEX"): raise ValueError("underlying must be FUT or INDEX")
        args += ["--underlying", q["underlying"]]
    if "square_off" in q:                              # holding: null / "none" = positional, "HH:MM" = intraday
        so = q["square_off"]
        if so is not None and so != "none" and not re.fullmatch(r"\d\d:\d\d", str(so)): raise ValueError("square_off is null or HH:MM")
        args += ["--square-off", "none" if so in (None, "none") else so]
    label = str(q.get("label") or "").strip()
    if label:
        if not re.match(r"^[\w .:+()/-]{1,40}$", label): raise ValueError("label: up to 40 letters, digits, spaces and . : + ( ) / -")
        args += ["--label", label]
    return ["backtest", *args]


def submit(args, title):
    with lock:
        same = next((j for j in jobs if j["args"] == args and j["state"] in ("queued", "running")), None)
        if same: return same
        j = dict(id=f"{D.datetime.now():%Y%m%d-%H%M%S}-{len(jobs) + 1}", title=title, args=args, state="queued",
                 queued=D.datetime.now().isoformat(timespec="seconds"), started=None, ended=None, rc=None)
        jobs.append(j)
    wake.set()
    return j


def worker():
    os.makedirs(JOBS_DIR, exist_ok=True)
    while True:
        wake.wait(); wake.clear()
        while True:
            with lock: j = next((x for x in jobs if x["state"] == "queued"), None)
            if not j: break
            j.update(state="running", started=D.datetime.now().isoformat(timespec="seconds"))
            log = os.path.join(JOBS_DIR, f"{j['id']}.log")
            with open(log, "w", encoding="utf-8") as fh:
                env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
                rc = subprocess.call([sys.executable, "-u", os.path.join(HERE, "lab.py"), *j["args"]], cwd=HERE,
                                     stdout=fh, stderr=subprocess.STDOUT, env=env)
            j.update(state="done" if rc == 0 else "failed", rc=rc, ended=D.datetime.now().isoformat(timespec="seconds"))


def tail(j, n=12):
    f = os.path.join(JOBS_DIR, f"{j['id']}.log")
    if not os.path.exists(f): return []
    return open(f, encoding="utf-8", errors="replace").read().splitlines()[-n:]


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *a):
        if self.path.startswith("/api/"): sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % a))

    def end_headers(self):
        if self.path.startswith("/api/") or self.path.endswith((".html", "summary.json")):
            self.send_header("Cache-Control", "no-store")      # a finished job must show on reload
        super().end_headers()

    def reply(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def public(self):
        """Only the dashboard and its result files are served - never the database, strategy files, tools or logs."""
        p = urllib.parse.unquote(self.path.split("?")[0].split("#")[0])
        if p in ("/", ""): return "/dashboard.html"
        if ".." in p or "\\" in p: return None
        if p == "/dashboard.html" or (p.startswith("/web/") and p.endswith(".json")): return p
        return None

    def do_GET(self):
        if self.path.split("?")[0] == "/api/status":
            with lock:
                js = [dict(j, log=tail(j)) for j in reversed(jobs[-10:])]
            return self.reply(200, dict(api=True, busy=any(j["state"] in ("queued", "running") for j in js), jobs=js))
        p = self.public()
        if p is None: return self.send_error(404)
        self.path = p
        return super().do_GET()

    def do_HEAD(self):
        p = self.public()
        if p is None: return self.send_error(404)
        self.path = p
        return super().do_HEAD()

    def list_directory(self, path):                  # no folder listings
        self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0]
        # same-origin only: the page served by this server (whatever address the phone or PC used to open it)
        origin, host = self.headers.get("Origin"), self.headers.get("Host")
        if origin is not None and origin != f"http://{host}":
            return self.reply(403, dict(error="cross-origin request refused"))
        try:
            n = int(self.headers.get("Content-Length") or 0)
            q = json.loads(self.rfile.read(n) or b"{}") if n <= 10000 else {}
        except ValueError:
            return self.reply(400, dict(error="body must be JSON"))
        try:
            if path == "/api/backtest":
                args = backtest_args(q)
                j = submit(args, f"{q['code']} · {q.get('label') or q['what']}" + (f" · {q['tf']}" if q.get("tf") else "")
                           + (" · index" if q.get("underlying") == "INDEX" else "")
                           + ((" · positional" if q["square_off"] in (None, "none") else f" · intraday {q['square_off']}") if "square_off" in q else ""))
            elif path == "/api/run":
                j = submit([], "recompute missing / changed results")
            else:
                return self.reply(404, dict(error="unknown endpoint"))
        except ValueError as e:
            return self.reply(400, dict(error=str(e)))
        return self.reply(202, dict(job=j))


class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = False               # Windows would otherwise let a second server share the port silently

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def addresses():
    """This PC's IPv4 addresses (Tailscale ones start with 100.)."""
    import socket
    try: return sorted({a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)})
    except OSError: return []


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = sys.argv[1:]
    port = int(args[0]) if args else 8766
    # --lan: every network address of this PC (home Wi-Fi, and Tailscale for away from home); --host <ip>: one address,
    # e.g. the Tailscale 100.x address only. Default: this PC only.
    host = "0.0.0.0" if "--lan" in opts else (opts[opts.index("--host") + 1] if "--host" in opts else "127.0.0.1")
    if "--tailscale" in opts:                         # away from home: only the Tailscale address (your own devices)
        ts = [a for a in addresses() if a.startswith("100.")]
        if not ts: sys.exit("no Tailscale address on this PC: install Tailscale, sign in, then run again")
        host = ts[0]
    try:
        srv = Server((host, port), functools.partial(Handler, directory=HERE))
    except OSError as e:
        sys.exit(f"port {port} is in use ({e.strerror}); stop the other server or pass another port: python serve.py 8770")
    threading.Thread(target=worker, daemon=True).start()
    print(f"strategy lab: http://localhost:{port}/dashboard.html  (backtest queue on; Ctrl+C to stop)")
    if host != "127.0.0.1":
        for a in (addresses() if host == "0.0.0.0" else [host]):
            if not a.startswith("127."):
                print(f"  from a phone: http://{a}:{port}/dashboard.html" + ("   (Tailscale: works away from home)" if a.startswith("100.") else ""))
        print("  anyone who can reach these addresses can open the page and queue backtests (nothing here touches a broker)")
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
