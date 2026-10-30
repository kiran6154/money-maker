"""Assemble report.html from results/summary.json, the plot payloads and narrative.json. python build_page.py"""
from __future__ import annotations

import glob
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE / "results"
PER = [("dev", "2024 development"), ("val", "2025 validation"), ("blind", "2026 blind")]


def f(x, d=1, sign=True):
    if x is None:
        return '<span class="dim">–</span>'
    s = f"{x:+.{d}f}" if sign else f"{x:.{d}f}"
    return s


def cls(ci):
    if not ci:
        return "dim"
    return "pos" if ci["lo"] > 0 else "neg" if ci["hi"] < 0 else ""


def cicell(ci):
    if not ci:
        return '<td class="dim">–</td>'
    return f'<td class="{cls(ci)}">{ci["mean"]:+.1f} <span class="dim">[{ci["lo"]:+.1f}, {ci["hi"]:+.1f}]</span></td>'


def table(head, rows):
    h = "".join(f"<th>{html.escape(c)}</th>" for c in head)
    return f'<div class="tbl"><table><thead><tr>{h}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


CODES = [("A", "random / every eligible bar"), ("B", "compression only"), ("C", "volume spike only"),
         ("D", "breakout only"), ("E", "higher low only"), ("F", "breakout + volume"),
         ("G", "compression + breakout (wave 1)"), ("H", "compression + higher low + breakout"),
         ("I", "complete lifecycle so far (wave 2)"), ("I3", "wave 3")]


def controls_table(S, scope):
    rows = []
    for code, name in CODES:
        if code == "A":
            continue
        cells = [f'<td class="l"><b>{code}</b> {name}</td>']
        for per, _ in PER:
            d = S["periods"].get(per, {}).get("tf5", {}).get(scope, {}).get(code)
            cells.append(f'<td>{d["n"] if d else "–"}</td>')
            cells.append(cicell(d.get("xJ") if d else None))
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = ["Signal"] + sum([[f"n {lab[:4]}", f"excess {lab[:4]}"] for _, lab in PER], [])
    return table(head, rows)


def main():
    S = json.load(open(R / "summary.json"))
    import narrative as NM
    N = {k: getattr(NM, k) for k in dir(NM) if not k.startswith("_")}
    plots = []
    for p in sorted(glob.glob(str(R / "plots_tf5_*.json"))):
        plots += json.load(open(p))
    seen = set()
    plots = [p for p in plots if not (p["id"] in seen or seen.add(p["id"]))]
    body = N["html_top"]
    body += '<section id="predict"><h2><span class="tag">D · H1</span> Does the pattern predict the next 30 minutes?</h2>'
    body += N["predict_intro"]
    body += "<h3>Front weekly, all four strikes, strike-set-clean sessions</h3>" + controls_table(S, "all_contracts_front_clean")
    body += "<h3>Primary: ATM only (the pre-registered H1 sample)</h3>" + controls_table(S, "primary_clean")
    body += '<p class="note">Excess = 30-minute log return of the option after the signal minus the mean of bars with the same side, strike, expiry role, DTE bucket, hour and trailing-return decile, in percentage points; brackets are week-clustered 95 % bootstrap intervals. Green: interval above zero; red: below.</p>'
    body += N["predict_after"] + "</section>"
    for key in ("math", "wave", "cepe", "dte", "regime", "oos", "falsify", "extra"):
        body += N.get(key, "")
    page = (HERE / "page_template.html").read_text(encoding="utf-8")
    page = page.replace("__BODY__", body).replace("__PLOTS__", json.dumps(plots, separators=(",", ":")))
    (HERE / "report.html").write_text(page, encoding="utf-8")
    print("report.html", len(page) // 1024, "KB,", len(plots), "event plots")


if __name__ == "__main__":
    main()
