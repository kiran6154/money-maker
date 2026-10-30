#!/usr/bin/env python3
"""Live progress page for tools/breeze_store.py: rewrites <root>/progress.html every 30 seconds (the page reloads
itself). Read only: it opens the ledger read-only and never calls Breeze.

    python tools/breeze_progress.py                 # loop; open D:/nifty_data/progress.html in a browser
    python tools/breeze_progress.py --once
"""
import argparse
import datetime as dt
import glob
import html
import os
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breeze_store as bs  # noqa: E402

REPLAN_EVERY = 3600          # seconds between rebuilds of the futures / options unit lists (they read the whole index)


def ledger(root):
    p = os.path.join(root, "_meta", "ledger.sqlite")
    if not os.path.exists(p):
        return None
    return sqlite3.connect(f"file:{p.replace(os.sep, '/')}?mode=ro", uri=True, timeout=10)


def closed_units(db):
    """unit ids the downloader will not ask for again without a file: nothing at source."""
    if db is None:
        return {}
    return dict(db.execute("SELECT unit_id, status FROM units WHERE status IN ('empty','no_data_at_source') "
                           "AND (note IS NULL OR note NOT LIKE '%partial%')"))


def summarise(units, closed):
    """[label -> [units, done, requests, requests left, no data]] for a list of units."""
    tot = [0, 0, 0, 0, 0]
    for u in units:
        n = len(u.requests)
        done = u.is_final and (os.path.exists(u.final_path) or u.uid in closed)
        tot[0] += 1
        tot[1] += done
        tot[2] += n
        tot[3] += 0 if done else n
        tot[4] += u.uid in closed
    return tot


def bar(done, total, label, note=""):
    pct = 100.0 * done / total if total else 0.0
    return (f'<div class="row"><div class="lab">{html.escape(label)}</div>'
            f'<div class="track"><div class="fill" style="width:{pct:.1f}%"></div></div>'
            f'<div class="num">{done:,} / {total:,} <span class="dim">({pct:.0f}%)</span></div>'
            f'<div class="note">{html.escape(note)}</div></div>')


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def grid(title, units, closed, month_of, what):
    """Year x month table: each cell = files done / files planned for that month (hover for requests and gaps)."""
    cells = defaultdict(list)
    for u in units:
        cells[month_of(u)].append(u)
    if not cells:
        return ""
    years = sorted({k[:4] for k in cells}, reverse=True)
    out = [f'<div class="card"><h2>{html.escape(title)}</h2><div class="scroll"><table class="grid"><tr><th></th>'
           + "".join(f"<th>{m}</th>" for m in MONTHS) + "<th>year</th></tr>"]
    for y in years:
        row, yt = [], [0, 0, 0, 0, 0]
        for m in range(1, 13):
            us = cells.get(f"{y}-{m:02d}")
            if not us:
                row.append('<td class="na"></td>')
                continue
            s = summarise(us, closed)
            yt = [a + b for a, b in zip(yt, s)]
            open_ = sum(1 for u in us if not u.is_final)
            cls = "done" if s[1] == s[0] else "part" if s[1] else "todo"
            if s[4] and s[4] == s[0]:
                cls = "none"
            pct = 100.0 * s[1] / s[0]
            tip = (f"{y}-{m:02d}: {s[1]} of {s[0]} {what} done, {s[3]:,} requests left"
                   + (f", {s[4]} with no data at source" if s[4] else "")
                   + (f", {open_} still open (refetched until final)" if open_ else ""))
            txt = "&#10003;" if cls == "done" and s[0] == 1 else f"{s[1]}/{s[0]}"
            if cls == "none":
                txt = "no data"
            row.append(f'<td class="{cls}" title="{html.escape(tip)}" style="--p:{pct:.0f}%">{txt}'
                       + ('<i>!</i>' if s[4] and cls != "none" else "") + "</td>")
        ypct = 100.0 * yt[1] / yt[0] if yt[0] else 0
        out.append(f"<tr><th>{y}</th>{''.join(row)}<td class=\"yr\">{yt[1]:,}/{yt[0]:,} "
                   f"<span class=\"dim\">{ypct:.0f}%, {yt[3]:,} req left</span></td></tr>")
    out.append('</table></div><div class="legend"><span class="sw done"></span>complete <span class="sw part"></span>'
               'in progress <span class="sw todo"></span>not started <span class="sw none"></span>no data at source '
               '&middot; <b>!</b> = some files had no data &middot; hover a cell for detail</div></div>')
    return "".join(out)


def build(root, cap, cache):
    today = dt.date.today()
    frm = dt.date(2018, 1, 1)
    db = ledger(root)
    closed = closed_units(db)
    calls = dict(db.execute("SELECT day, n FROM calls ORDER BY day")) if db else {}
    missing_req = db.execute("SELECT COUNT(*) FROM empty_requests").fetchone()[0] if db else 0
    if db:
        db.close()
    calls_today = calls.get(today.isoformat(), 0)

    iu = bs.index_units(root, frm, today, today)
    idx = summarise(iu, closed)
    index_whole = all((not u.is_final) or os.path.exists(u.final_path) for u in iu)

    fut = opt = wid = w3 = None
    by_tier, by_year = {}, {}
    grids = [grid("Index by month", iu, closed, lambda u: u.uid.split("|")[1], "month file(s)")]
    if index_whole:
        if "units" not in cache or time.time() - cache["at"] > REPLAN_EVERY:
            days = bs.IndexDays(root)
            cal = bs.calendar_for(root, days.sessions)
            cache["units"] = (bs.futures_units(root, cal, days.sessions, frm, today, today),
                              bs.options_units(root, cal, days, frm, today, today, (1, 2, 3), bs.WINGS),
                              bs.wide_units(root, cal, days, frm, today, today, (1, 2), bs.WINGS, bs.WIDE_POINTS),
                              bs.wide_units(root, cal, days, frm, today, today, (1, 2), bs.WINGS, bs.WIDE3000_POINTS,
                                            inner=bs.WIDE_POINTS, tag="wide3k"))
            cache["at"] = time.time()
        fu, ou, wu, w3u = cache["units"]
        fut, opt, wid = summarise(fu, closed), summarise(ou, closed), summarise(wu, closed)
        w3 = summarise(w3u, closed)
        g_t, g_y = defaultdict(list), defaultdict(list)
        for u in ou:
            g_t[u.tier].append(u)
            g_y[u.expiry[:4]].append(u)
        by_tier = {t: summarise(g_t[t], closed) for t in sorted(g_t)}
        by_year = {y: summarise(g_y[y], closed) for y in sorted(g_y, reverse=True)}
        grids.append(grid("Futures by contract month", fu, closed, lambda u: u.expiry[:7], "contract(s)"))
        grids.append(grid("Options by expiry month: all (files = expiry x 2-session chunk, every identified contract)", ou, closed,
                          lambda u: u.expiry[:7], "files"))
        for t in sorted(g_t):
            grids.append(grid(f"Options by expiry month: {('', 'weekly expiries (45 days of history each)', 'monthly expiries (75 days of history each)')[t]}",
                              g_t[t], closed, lambda u: u.expiry[:7], "files"))
        grids.insert(1, grid(f"Far strikes (index \u00b1{bs.WIDE_POINTS:,} points) by expiry month: files = expiry x 2-session "
                             f"chunk of the extra contracts (*.wide.parquet)", wu, closed, lambda u: u.expiry[:7], "files"))
        grids.insert(1, grid(f"Far strikes {bs.WIDE_POINTS:,} to {bs.WIDE3000_POINTS:,} points out by expiry month: files = "
                             f"expiry x 2-session chunk (*.wide3k.parquet)", w3u, closed, lambda u: u.expiry[:7], "files"))

    # pace: calls in the ledger now against the previous page build
    now = time.time()
    rate = None
    # all days together: a run that started yesterday keeps counting under yesterday's date after midnight
    calls_all = sum(calls.values())
    if "calls" in cache and now > cache["calls_at"]:
        rate = (calls_all - cache["calls"]) * 60.0 / (now - cache["calls_at"])
        cache["rates"] = (cache.get("rates", []) + [rate])[-10:]
    cache.update(calls=calls_all, calls_at=now)
    rates = cache.get("rates", [])
    pace = sum(rates) / len(rates) if rates else None

    logs = sorted(glob.glob(os.path.join(root, "_meta", "run_*.log")), key=os.path.getmtime)
    tail, log_age = [], None
    if logs:
        log_age = now - os.path.getmtime(logs[-1])
        with open(logs[-1], encoding="utf-8-sig", errors="replace") as fh:
            tail = [x.rstrip() for x in fh.readlines()[-8:]]
    running = bool(rates) and rates[-1] > 0
    size = sum(os.path.getsize(os.path.join(dp, f)) for k in bs.PHASES
               for dp, _, fs in os.walk(os.path.join(root, k)) for f in fs if f.endswith(".parquet"))

    left = idx[3] + (fut[3] if fut else 0) + (opt[3] if opt else 0) + (wid[3] if wid else 0) + (w3[3] if w3 else 0)
    # requests really asked so far against the plan: about 83% for the main options, about 50% for far strikes
    left_real = idx[3] + (fut[3] if fut else 0) + 0.83 * (opt[3] if opt else 0) + 0.5 * (wid[3] if wid else 0) + 0.4 * (w3[3] if w3 else 0)
    last = " ".join(tail[-3:]).lower()
    state = ("downloading" if running else
             "stopped: Breeze session expired - needs a new token" if "expired" in last else
             "stopped on an error - see the log below" if "giving up" in last else
             "not running" if rates else "measuring pace...")
    eta_today = ""
    days_left = "known once the index is complete (futures and options are planned from it)"
    if index_whole:
        days_left = ("at most (contracts that stop trading going back are skipped: about 83% of main options and "
                     "50% of far strikes is really asked)")
        if running and pace:
            hrs = left_real / pace / 60
            eta_today = f"about {hrs:,.0f} hours of downloading left at this pace"
            days_left += f"; {hrs / 9:,.0f} days at 9 hours a day, {hrs / 24:,.1f} days non-stop"

    rows = [bar(idx[1], idx[0], "Index", "months")]
    if fut:
        rows.append(bar(fut[1], fut[0], "Futures", f"contracts; {fut[4]} with no data at source"))
        rows.append(bar(opt[1], opt[0], "Options", f"files; at most {opt[3]:,} requests left; {opt[4]} with no data at source"))
        rows.append(bar(wid[1], wid[0], f"Far strikes \u00b1{bs.WIDE_POINTS:,}",
                        f"files; at most {wid[3]:,} requests left; {wid[4]} chunks with no extra candles"))
        rows.append(bar(w3[1], w3[0], f"Far strikes {bs.WIDE_POINTS:,}-{bs.WIDE3000_POINTS:,}",
                        f"files; at most {w3[3]:,} requests left; {w3[4]} chunks with no extra candles"))
    else:
        rows.append('<div class="row"><div class="lab">Futures, options</div><div class="note wide">'
                    'start after the index is complete</div></div>')
    tiers = {1: "Weekly expiries", 2: "Monthly expiries"}
    trows = [bar(v[1], v[0], tiers.get(t, f"Tier {t}"), f"{v[3]:,} requests left") for t, v in by_tier.items()]
    yrows = [bar(v[1], v[0], y, f"{v[3]:,} requests left; {v[4]} no data") for y, v in by_year.items()]
    crow = "".join(f"<tr><td>{d}</td><td>{n:,}</td></tr>" for d, n in sorted(calls.items(), reverse=True)[:14])

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="30">
<title>NIFTY data download</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#16202c;--dim:#667385;--line:#dfe3e8;--fill:#1f7a5c;--track:#e6e9ee;--warn:#a15c00}}
@media (prefers-color-scheme: dark){{:root{{--bg:#12161c;--card:#1a2029;--ink:#e6eaf0;--dim:#93a0b2;--line:#2a323e;--fill:#3fb58a;--track:#2a323e;--warn:#e0a44a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:20px 16px 40px}}h1{{font-size:20px;margin:0 0 2px}}h2{{font-size:14px;margin:0 0 10px;color:var(--dim);font-weight:600;text-transform:uppercase;letter-spacing:.04em}}
.sub{{color:var(--dim);margin-bottom:16px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:14px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}.k b{{display:block;font-size:22px;font-variant-numeric:tabular-nums}}.k span{{color:var(--dim);font-size:13px}}
.row{{display:grid;grid-template-columns:170px 1fr 150px;gap:4px 12px;align-items:center;padding:5px 0}}.lab{{font-weight:600}}
.track{{height:10px;background:var(--track);border-radius:6px;overflow:hidden}}.fill{{height:100%;background:var(--fill)}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}.dim,.note{{color:var(--dim);font-size:13px}}.note{{grid-column:2 / 4}}.wide{{grid-column:2 / 4}}
.state{{font-weight:600;color:var(--fill)}}.state.stop{{color:var(--warn)}}pre{{margin:0;overflow-x:auto;font:12px/1.5 Consolas,monospace;color:var(--dim)}}
table{{border-collapse:collapse}}td{{padding:2px 18px 2px 0;font-variant-numeric:tabular-nums}}
.scroll{{overflow-x:auto}}.grid{{width:100%;min-width:760px;border-collapse:separate;border-spacing:3px}}.grid th{{font-size:12px;color:var(--dim);font-weight:600;padding:2px 4px;text-align:center}}
.grid td{{padding:5px 2px;text-align:center;font-size:12px;border-radius:5px;min-width:48px;position:relative}}.grid td.na{{background:transparent}}
.grid td.todo{{background:var(--track);color:var(--dim)}}.grid td.done{{background:var(--fill);color:#fff}}
.grid td.part{{background:linear-gradient(90deg,color-mix(in srgb,var(--fill) 55%,transparent) var(--p),var(--track) var(--p))}}
.grid td.none{{background:color-mix(in srgb,var(--warn) 30%,transparent);color:var(--ink)}}.grid td i{{font-style:normal;font-weight:700;color:var(--warn);margin-left:3px}}.grid td.done i{{color:#ffe08a}}
.grid td.yr{{text-align:left;padding-left:10px;white-space:nowrap;min-width:190px}}
.legend{{color:var(--dim);font-size:12px;margin-top:8px}}.sw{{display:inline-block;width:11px;height:11px;border-radius:3px;margin:0 4px 0 10px;vertical-align:-1px}}
.sw.done{{background:var(--fill)}}.sw.part{{background:linear-gradient(90deg,color-mix(in srgb,var(--fill) 55%,transparent) 50%,var(--track) 50%)}}.sw.todo{{background:var(--track)}}.sw.none{{background:color-mix(in srgb,var(--warn) 30%,transparent)}}
@media (max-width:640px){{.row{{grid-template-columns:1fr 110px}}.track{{grid-column:1 / 3;grid-row:2}}.note{{grid-column:1 / 3}}}}
</style></head><body><main>
<h1>NIFTY 1-minute data download</h1>
<div class="sub">ICICI Breeze &rarr; {html.escape(root)} &middot; page written {dt.datetime.now():%Y-%m-%d %H:%M:%S}, reloads every 30 s</div>
<div class="card"><div class="kpis">
<div class="k"><b class="state {'' if running else 'stop'}">{html.escape(state)}</b><span>{html.escape(eta_today) or '&nbsp;'}</span></div>
<div class="k"><b>{calls_today:,}</b><span>Breeze requests made today (no daily cap set)</span></div>
<div class="k"><b>{f'{pace:.0f}' if pace is not None else '-'} / min</b><span>current pace</span></div>
<div class="k"><b>{left:,}{'' if index_whole else '+'}</b><span>requests still to make: {html.escape(days_left)}</span></div>
<div class="k"><b>{size / 1e6:,.1f} MB</b><span>data on disk</span></div>
<div class="k"><b>{missing_req:,}</b><span>requests with no candles (listed in _missing/missing.csv)</span></div>
</div></div>
<div class="card"><h2>Overall</h2>{''.join(rows)}</div>
{f'<div class="card"><h2>Options by tier</h2>{"".join(trows)}</div>' if trows else ''}
{''.join(grids)}
<div class="card"><h2>Requests per day</h2><table>{crow or '<tr><td>none yet</td></tr>'}</table></div>
<div class="card"><h2>Last lines of the run log{f' (updated {int(log_age)} s ago)' if log_age is not None else ''}</h2><pre>{html.escape(chr(10).join(tail))}</pre></div>
</main></body></html>"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=bs.DEFAULT_ROOT)
    p.add_argument("--day-cap", type=int, default=bs.DEFAULT_DAY_CAP)
    p.add_argument("--every", type=int, default=30)
    p.add_argument("--once", action="store_true")
    a = p.parse_args()
    out, cache = os.path.join(a.root, "progress.html"), {}
    while True:
        try:
            page = build(a.root, a.day_cap, cache)
            with open(out + ".tmp", "w", encoding="utf-8") as fh:
                fh.write(page)
            os.replace(out + ".tmp", out)
        except Exception as ex:                    # a file caught mid-write, a busy ledger: try again next round
            print(f"{dt.datetime.now():%H:%M:%S} skipped: {type(ex).__name__}: {ex}", flush=True)
        if a.once:
            return
        time.sleep(a.every)


if __name__ == "__main__":
    main()
