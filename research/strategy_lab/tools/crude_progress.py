#!/usr/bin/env python3
"""Live progress page for crude_store.py: <root>/progress.html, rewritten every 30 s (read-only on the store).

    python tools/crude_progress.py            # loop
    python tools/crude_progress.py --once
"""
import datetime as dt
import glob
import html
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crude_store as cs  # noqa: E402

ROOT = cs.ROOT


def ledger():
    p = os.path.join(ROOT, "_meta", "ledger.sqlite")
    if not os.path.exists(p):
        return {}, 0, 0
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    units = {u: s for u, s in db.execute("SELECT unit_id, status FROM units")}
    calls = db.execute("SELECT COALESCE(SUM(n), 0) FROM calls").fetchone()[0]
    failed = db.execute("SELECT COUNT(DISTINCT unit_id) FROM failed_requests WHERE unit_id NOT IN "
                        "(SELECT unit_id FROM units WHERE status IN ('done','empty'))").fetchone()[0]
    db.close()
    return units, calls, failed


def log_state():
    logs = sorted(glob.glob(os.path.join(ROOT, "_meta", "run_*.log")), key=os.path.getmtime)
    if not logs:
        return None, [], None, False
    t = open(logs[-1], encoding="utf-8", errors="replace").read().splitlines()
    pts = []
    for line in t:
        m = re.match(r"\s+(\d\d:\d\d:\d\d) (\d+) requests this run", line)
        if m:
            pts.append((m.group(1), int(m.group(2))))
    pace = None
    if len(pts) >= 2:
        def sec(s):
            h, mi, se = map(int, s.split(":"))
            return h * 3600 + mi * 60 + se
        a, b = pts[max(0, len(pts) - 11)], pts[-1]
        d = (sec(b[0]) - sec(a[0])) % 86400
        pace = (b[1] - a[1]) * 60 / d if d else None
    age = time.time() - os.path.getmtime(logs[-1])
    ended = any(x in "\n".join(t[-30:]) for x in ("all requested phases", "giving up", "Traceback"))
    phase = next((ln for ln in reversed(t) if re.match(r"(futures|option strikes|options 1-minute):", ln)), "expiry dates")
    return os.path.basename(logs[-1]), t[-12:], (pace, age, phase), ended


def bar(done, total, label, note):
    pct = 100 * done / total if total else 0
    return (f'<div class="row"><div class="lab">{label}</div><div class="track"><div class="fill" style="width:{pct:.1f}%">'
            f'</div></div><div class="num">{done:,} / {total:,} ({pct:.0f}%)</div><div class="note">{note}</div></div>')


def grid(title, cells):
    """cells: {(year, month): (done, total)}"""
    if not cells:
        return ""
    years = sorted({y for y, _ in cells})
    rows = ["<tr><th></th>" + "".join(f"<th>{dt.date(2000, m, 1):%b}</th>" for m in range(1, 13)) + "</tr>"]
    for y in years:
        tds = []
        for m in range(1, 13):
            d, t = cells.get((y, m), (0, 0))
            cls = "na" if not t else "ok" if d >= t else "part" if d else "todo"
            tds.append(f'<td class="{cls}" title="{d}/{t}">{"" if not t else ("&#10003;" if d >= t else f"{d}/{t}")}</td>')
        rows.append(f"<tr><th>{y}</th>{''.join(tds)}</tr>")
    return f"<h2>{html.escape(title)}</h2><table>{''.join(rows)}</table>"


def render():
    today = dt.date.today()
    p = os.path.join(ROOT, "_meta", "expiries.json")
    exp = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    units, calls, failed = ledger()
    logname, tail, st, ended = log_state()
    months_total = sum(1 for _ in cs.months(dt.date(2018, 1, 1), today + dt.timedelta(days=100)))
    fut = [(k, v["futures"]) for k, v in exp.items() if v.get("futures")
           and dt.date.fromisoformat(v["futures"]) - dt.timedelta(days=cs.DAYS) <= today]
    opt = [(k, o) for k, v in exp.items() for o in (v.get("options_all") or [])
           if dt.date.fromisoformat(o) - dt.timedelta(days=cs.DAYS) <= today]
    fdone = sum(1 for _, e in fut if units.get(f"fut|{e}") in ("done", "partial"))
    sdone = sum(1 for _, e in opt if units.get(f"ostrikes|{e}") in ("done", "partial"))
    ou = cs.option_units(ROOT, exp, today, dt.date(2018, 1, 1))
    odone = [u for u in ou if units.get(u[0]) in ("done", "partial")]
    oreq_left = sum(len(u[3]) for u in ou if units.get(u[0]) not in ("done", "partial"))
    pace, age, phase = st if st else (None, None, "-")
    left_now = oreq_left + 2 * 260 * (len(opt) - sdone) + 43 * (len(fut) - fdone)
    eta = f"about {left_now / pace / 60:.1f} h at the current pace (option 1-minute requests are only known " \
          f"for expiries whose strikes are already scanned)" if pace else "-"
    state = "finished or stopped" if ended else ("running" if age is not None and age < 300 else
                                                   f"no log line for {age / 60:.0f} min" if age else "not started")
    no_opt = sorted(k for k, v in exp.items() if v.get("futures") and "options_all" in v and not v["options_all"]
                    and v["futures"] < today.isoformat())
    rows = [bar(len(exp), months_total, "Expiry dates", "months checked (Jan 2018 to 3 months ahead)"),
            bar(fdone, len(fut), "Futures", "contracts, 60 days of 1-minute candles each"),
            bar(sdone, len(opt), "Option strikes", "expiries scanned (every strike, daily candles)"),
            bar(len(odone), len(ou), "Options 1-minute", f"expiry-sessions; {oreq_left:,} requests left on the "
                                                         f"expiries scanned so far")]
    gf, gs, go = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for k, e in fut:
        y, m = map(int, k.split("-"))
        gf[(y, m)][1] += 1
        gf[(y, m)][0] += units.get(f"fut|{e}") in ("done", "partial")
    for k, e in opt:
        y, m = map(int, k.split("-"))
        gs[(y, m)][1] += 1
        gs[(y, m)][0] += units.get(f"ostrikes|{e}") in ("done", "partial")
    for u in ou:
        key = (u[1].year, u[1].month)
        go[key][1] += 1
        go[key][0] += units.get(u[0]) in ("done", "partial")
    body = f"""<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="30">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Crude download</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--dim:#6e6e73;--track:#e8e8ed;--fill:#2f7d4f;--part:#f3d27a;--todo:#f0f0f3;--line:#d2d2d7}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151517;--fg:#f2f2f4;--dim:#a1a1a6;--track:#2c2c30;--fill:#4caf78;--part:#8a6d1e;--todo:#232327;--line:#3a3a3e}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1000px;padding:16px}}
h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:16px;margin:24px 0 8px}}.dim,.note{{color:var(--dim);font-size:13px}}
.kpis{{display:flex;flex-wrap:wrap;gap:20px;margin:14px 0}}.kpi b{{display:block;font-size:20px}}
.row{{display:grid;grid-template-columns:150px 1fr 170px;gap:4px 12px;align-items:center;margin:10px 0}}
.track{{background:var(--track);height:12px;border-radius:6px;overflow:hidden}}.fill{{background:var(--fill);height:100%}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}.note{{grid-column:2 / 4}}
table{{border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}}td,th{{border:1px solid var(--line);padding:3px 6px;text-align:center;min-width:34px}}
td.ok{{background:var(--fill);color:#fff}}td.part{{background:var(--part)}}td.todo{{background:var(--todo)}}
pre{{font-size:12px;overflow-x:auto;background:var(--todo);padding:8px;border-radius:6px}}
@media (max-width:600px){{.row{{grid-template-columns:1fr}}.num{{text-align:left}}.note{{grid-column:1}}}}
</style></head><body>
<h1>MCX crude oil download (Breeze, D:/crude_data)</h1>
<div class="dim">updated {dt.datetime.now():%Y-%m-%d %H:%M:%S}; refreshes every 30 s; log {logname or '-'}</div>
<div class="kpis"><div class="kpi"><b>{state}</b>state</div><div class="kpi"><b>{html.escape(phase.split(':')[0])}</b>current step</div>
<div class="kpi"><b>{calls:,}</b>requests so far</div><div class="kpi"><b>{f'{pace:.0f}/min' if pace else '-'}</b>pace</div>
<div class="kpi"><b>{failed}</b>units with failed requests</div><div class="kpi"><b>{eta.split(' (')[0]}</b>left (rough)</div></div>
{''.join(rows)}
<div class="note">{html.escape(eta)}</div>
{f'<p class="dim">Futures but no options on Breeze for: {", ".join(no_opt)}</p>' if no_opt else ''}
{grid("Futures contracts by expiry month", gf)}
{grid("Option strike scans by expiry month", gs)}
{grid("Options 1-minute: expiry-sessions by expiry month", go)}
<h2>Last log lines</h2><pre>{html.escape(chr(10).join(tail))}</pre></body></html>"""
    out = os.path.join(ROOT, "progress.html")
    with open(out + ".tmp", "w", encoding="utf-8") as fh:
        fh.write(body)
    os.replace(out + ".tmp", out)


if __name__ == "__main__":
    while True:
        try:
            render()
        except Exception as ex:                     # a half-written file mid-run must not stop the page
            print("render failed:", ex, flush=True)
        if "--once" in sys.argv:
            break
        time.sleep(30)
