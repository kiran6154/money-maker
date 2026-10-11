// The strategy tree: every strategy under the one it was derived from, with the change, the settings that differ, its
// exits in one line, its widest stored result, and the variations tried on it (/api/lineage; strategies/lineage.py).
import { $, $$, api, esc, inr, num, cls, TF_LABEL } from "./util.js";

let D = null;
const KIND = { "not tried": "NOT TRIED", exit: "exit", stop: "stop", "entry filter": "entry filter", timing: "timing", data: "data" };

function text(n) {
  return [n.code, n.name, n.family, n.change, n.exits, ...n.diff.flat(), ...n.studies.flatMap((s) => [s.kind, s.what, s.result, s.ref])].join(" ").toLowerCase();
}

function box(n, kids, q) {
  const r = n.result, hit = q && text(n).includes(q);
  const res = !r ? '<span class="muted">no stored backtest</span>' : !r.trades ? `<span class="muted">${esc(r.label)}: no trades</span>`
    : `${esc(r.label)} · ${esc(r.type)}${r.choice && r.choice !== "-" ? " " + esc(r.choice) : ""} · ${esc(r.date_from || "")} → ${esc(r.date_to || "")} · ${r.trades.toLocaleString("en-IN")} trades · ` +
      `<b class="${cls(r.net)}">${inr(r.net)}</b> · PF ${r.pf == null ? "–" : num(r.pf)}`;
  const diff = n.diff.length && $("#l-diff").checked ? `<div class="diff"><table>${n.diff.map(([k, a, b]) =>
      `<tr><td>${esc(k)}</td><td><span class="old">${esc(a)}</span> → <b>${esc(b)}</b></td></tr>`).join("")}</table></div>` : "";
  const st = $("#l-st").checked ? n.studies.map((s) => `<div class="study ${s.kind === "not tried" ? "nt" : ""}"><span class="tag">${esc(KIND[s.kind] || s.kind)}</span>` +
      `<b>${esc(s.what)}</b><br>${esc(s.result)}${s.ref ? ` <span class="muted">(${esc(s.ref)})</span>` : ""}</div>`).join("") : "";
  return `<li><div class="node ${n.parent ? "" : "root"} ${hit ? "hit" : ""}" id="n-${esc(n.code)}">
      <h4><a href="./?code=${encodeURIComponent(n.code)}" title="open in the Strategy Lab">${esc(n.code)}</a> <span>${esc(n.name)}</span>
        <span class="tag">${esc(n.family)}</span><span class="tag">${esc(TF_LABEL[n.timeframe] || n.timeframe)}</span></h4>
      <div class="chg">${n.parent ? `<span class="muted">from ${esc(n.parent)} — changed:</span> ` : '<span class="muted">starting point:</span> '}${esc(n.change)}</div>
      <div class="kv"><b>Exits</b><span>${esc(n.exits)}</span><b>Result</b><span>${res}</span></div>
      ${diff}${st}</div>
    ${kids.length ? `<ul>${kids.join("")}</ul>` : ""}</li>`;
}

function render() {
  const q = $("#l-q").value.trim().toLowerCase();
  const by = new Map(D.nodes.map((n) => [n.code, n])), kids = new Map();
  for (const n of D.nodes) { const k = n.parent || ""; if (!kids.has(k)) kids.set(k, []); kids.get(k).push(n); }
  // with a search: keep a strategy when it, one of its ancestors' matches below it, or one of its descendants matches
  const match = new Set();
  if (q) for (const n of D.nodes) if (text(n).includes(q)) { let x = n; while (x) { match.add(x.code); x = by.get(x.parent); } }
  const build = (n) => {
    if (q && !match.has(n.code)) return "";
    return box(n, (kids.get(n.code) || []).map(build).filter(Boolean), q);
  };
  $("#l-tree").innerHTML = `<ul class="tree">${(kids.get("") || []).map(build).filter(Boolean).join("")}</ul>`;
  const hits = q ? D.nodes.filter((n) => text(n).includes(q)).length : D.nodes.length;
  $("#l-count").textContent = q ? `${hits} of ${D.nodes.length} strategies match "${q}"` : `${D.nodes.length} strategies, ${(kids.get("") || []).length} starting points`;
}

async function start() {
  D = await api("/api/lineage");
  const c = D.intraday_close || [];
  if (c.length) $("#l-intro").innerHTML += ` <b>Intraday close:</b> ${c.map((r) => `from ${esc(r.from)} every intraday position is closed at ${esc(r.time)}`).join("; ")} (earlier dates keep each strategy's own square-off).`;
  for (const id of ["#l-q", "#l-diff", "#l-st"]) $(id).addEventListener("input", render);
  const want = new URLSearchParams(location.search).get("q"); if (want) $("#l-q").value = want;
  render();
  if (location.hash) document.getElementById("n-" + location.hash.slice(1))?.scrollIntoView({ block: "center" });
}
start().catch((e) => { $("#l-tree").textContent = "Server not reachable: " + e.message; });
