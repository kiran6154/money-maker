// Summary: every strategy's stored result summed over a period, in points or rupees, and one strategy broken down by
// year / month / week / day (/api/summary). Nothing is re-run.
import { $, $$, api, esc, num, inr, pref } from "./util.js";

const S = { type: pref("sum.type") || "FUT", unit: pref("sum.unit") || "pts", sort: { k: "net", d: -1 }, rows: [], code: pref("sum.code") || "" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const COLS = {
  pts: [["raw", "Points before slippage"], ["slippage", "Slippage"], ["net", "Points (net)"], ["profit", "Total profit"], ["loss", "Total loss"],
        ["pf", "PF"], ["avg", "Avg / trade"], ["max_dd", "Max drawdown"]],
  inr: [["raw", "₹ before slippage"], ["slippage", "Slippage"], ["charges", "Charges"], ["net", "Net ₹"], ["profit", "Total profit"], ["loss", "Total loss"],
        ["pf", "PF"], ["avg", "Avg / trade"], ["max_dd", "Max drawdown"]],
};
const fmt = (k, v) => v == null ? "–" : k === "pf" ? num(v, 2) : S.unit === "inr" ? inr(v) : num(v, 1);
const cls = (k, v) => (k === "pf" ? (v == null ? "" : v >= 1 ? "pos" : "neg") : v > 0 ? "pos" : v < 0 ? "neg" : "");

function seg(id, attr, val) { $$(`#${id} button`).forEach((b) => b.classList.toggle("on", b.dataset[attr] === val)); }
function query(extra) {
  const q = { type: S.type, mode: $("#s-mode").value };
  for (const [k, id] of [["year", "#s-year"], ["month", "#s-month"], ["from", "#s-from"], ["to", "#s-to"]]) if ($(id).value) q[k] = $(id).value;
  return new URLSearchParams({ ...q, ...extra });
}
function head(first) {
  return `<tr>${first.map(([k, l]) => `<th data-k="${k}">${l}</th>`).join("")}<th data-k="trades">Trades</th><th data-k="win_pct">Win %</th>${
    COLS[S.unit].map(([k, l]) => `<th data-k="${k}" class="r">${l}</th>`).join("")}</tr>`;
}
function cells(x) {
  const m = x[S.unit];
  return `<td class="r">${x.trades}</td><td class="r">${num(x.win_pct, 1)}</td>${COLS[S.unit].map(([k]) => `<td class="r ${cls(k, m[k])}">${fmt(k, m[k])}</td>`).join("")}`;
}
function val(x, k) { return k === "code" ? +x.code.slice(2) : k === "trades" || k === "win_pct" ? x[k] : k === "period" ? x.period : x[S.unit][k] ?? -1e18; }

function drawMain() {
  const f = $("#s-find").value.trim().toLowerCase();
  let rows = S.rows.filter((x) => !f || x.code.toLowerCase().includes(f) || x.name.toLowerCase().includes(f));
  rows = rows.slice().sort((a, b) => S.sort.d * (val(a, S.sort.k) > val(b, S.sort.k) ? 1 : val(a, S.sort.k) < val(b, S.sort.k) ? -1 : 0));
  const tot = rows.reduce((t, x) => { t.trades += x.trades; t.wins += x.wins; for (const k of ["raw", "slippage", "net", "profit", "loss", "charges"]) t[S.unit][k] = (t[S.unit][k] || 0) + (x[S.unit][k] || 0); return t; },
                          { trades: 0, wins: 0, pts: {}, inr: {} });
  $("#s-sum").textContent = `· ${rows.length} strategies · ${tot.trades.toLocaleString()} trades · net ${S.unit === "inr" ? inr(tot.inr.net || 0) : num(tot.pts.net || 0, 1) + " points"} (summed over the strategies shown)`;
  $("#s-tab").innerHTML = head([["code", "Strategy"], ["run", "Run · choice"]]) + rows.map((x) => `<tr data-c="${x.code}" class="${x.code === S.code ? "sel" : ""}" style="cursor:pointer">
    <td class="l"><a href="./?code=${x.code}">${x.code}</a> <span class="muted small">${esc(x.name)}</span></td>
    <td class="l small muted">${esc(x.label || x.run)} · ${esc(x.choice)} · ${x.span[0]} → ${x.span[1]}</td>${cells(x)}</tr>`).join("");
  $$("#s-tab th").forEach((th) => (th.onclick = () => { const k = th.dataset.k; S.sort = { k, d: S.sort.k === k ? -S.sort.d : -1 }; drawMain(); }));
  $$("#s-tab tr[data-c]").forEach((tr) => (tr.onclick = (e) => { if (e.target.tagName === "A") return; S.code = tr.dataset.c; pref("sum.code", S.code); $("#s-code").value = S.code; drawMain(); breakdown(); }));
}

async function breakdown() {
  const code = $("#s-code").value; if (!code) { $("#s-bd").innerHTML = ""; return; }
  const g = $("#s-group").value;
  $("#s-bd-h").textContent = `Breakdown · ${code} by ${g} · loading…`;
  try {
    const d = await api("/api/summary?" + query({ code, group: g }));
    const rows = d.rows;
    $("#s-bd-h").innerHTML = `Breakdown · <a href="./?code=${code}">${code}</a> by ${g} <span class="muted small">· ${rows.length} ${g}s · ${esc(rows[0]?.label || "")} ${esc(rows[0]?.choice || "")} · lot ${rows[0]?.lot ?? "–"}, slippage ${rows[0]?.slip ?? "–"} per side</span>`;
    let cum = 0;
    $("#s-bd").innerHTML = head([["period", g[0].toUpperCase() + g.slice(1)]]).replace("</tr>", `<th class="r">Cumulative</th></tr>`) +
      rows.map((x) => { cum += x[S.unit].net; return `<tr><td class="l">${x.period}</td>${cells(x)}<td class="r ${cum >= 0 ? "pos" : "neg"}">${S.unit === "inr" ? inr(cum) : num(cum, 1)}</td></tr>`; }).join("");
  } catch (e) { $("#s-bd-h").textContent = `Breakdown · ${code}: ${e.message}`; $("#s-bd").innerHTML = ""; }
}

async function load() {
  $("#s-msg").textContent = "loading…";
  try {
    const d = await api("/api/summary?" + query({}));
    S.rows = d.rows;
    $("#s-code").innerHTML = S.rows.map((x) => `<option ${x.code === S.code ? "selected" : ""}>${x.code}</option>`).join("");
    if (!S.rows.some((x) => x.code === S.code)) S.code = S.rows[0]?.code || "";
    $("#s-code").value = S.code;
    $("#s-msg").textContent = `${S.rows.length} strategies have a stored ${$("#s-type .on")?.textContent || S.type} result.` +
      " Points are per lot; rupees use each strategy's lot size and charges. A strategy's run spans its own dates, so a period outside them shows no trades.";
    drawMain(); breakdown();
  } catch (e) { $("#s-msg").textContent = e.message; }
}

$("#s-year").innerHTML += Array.from({ length: 9 }, (_, i) => 2026 - i).map((y) => `<option>${y}</option>`).join("");
$("#s-month").innerHTML += MONTHS.map((m, i) => `<option value="${i + 1}">${m}</option>`).join("");
seg("s-type", "t", S.type); seg("s-unit", "u", S.unit);
$$("#s-type button").forEach((b) => (b.onclick = () => { S.type = b.dataset.t; pref("sum.type", S.type); seg("s-type", "t", S.type); load(); }));
$$("#s-unit button").forEach((b) => (b.onclick = () => { S.unit = b.dataset.u; pref("sum.unit", S.unit); seg("s-unit", "u", S.unit); drawMain(); breakdown(); }));
for (const id of ["#s-mode", "#s-year", "#s-month", "#s-from", "#s-to"]) $(id).onchange = load;
$("#s-group").onchange = breakdown;
$("#s-code").onchange = (e) => { S.code = e.target.value; pref("sum.code", S.code); drawMain(); breakdown(); };
$("#s-find").oninput = drawMain;
$("#s-go").onclick = load;
load();
