// Chart explorer: one instrument's candles over a chosen range with a strategy's rules applied to them (/api/explorer/*).
// Controls in three groups (Strategy · Instrument · Range); every change applies at once; Refresh stays in the header.
import { $, $$, api, esc, inr, num, cls, pref, tsOf, TF_LABEL, reasonTag } from "./util.js";
import { ChartView } from "./chart.js";

const S = Object.assign({ inst: "FUT", right: "CE", side: "all", start: "days", end: "date", before: "1", liq: "10", hold: "own" }, pref("explorer2") || {});
let meta, strategies = {}, view, data = null, timer = null, req = 0, expiries = [];

const save = () => pref("explorer2", S);
const later = () => { clearTimeout(timer); timer = setTimeout(show, 250); };

async function start() {
  view = new ChartView($("#x-chart"), { static: true });
  meta = await api("/api/explorer/meta");
  strategies = Object.fromEntries(meta.strategies.map((s) => [s.code, s]));
  $("#x-code").innerHTML = meta.strategies.map((s) => `<option value="${esc(s.code)}">${esc(s.code)} · ${esc(s.name)} (${TF_LABEL[s.timeframe]})</option>`).join("");
  $("#x-tf").innerHTML = meta.tfs.map((t) => `<option value="${t}">${TF_LABEL[t]}</option>`).join("");
  const d = $("#x-date"); d.min = meta.first; d.max = meta.last; d.value = S.date || meta.last;
  $("#x-code").value = strategies[S.code] ? S.code : meta.strategies[0].code;
  $("#x-tf").value = S.tf || strategies[$("#x-code").value].timeframe;
  holdingOptions();
  $("#x-start").value = S.start; $("#x-end").value = S.end; $("#x-before").value = S.before; $("#x-liq").value = S.liq;
  // every control applies at once
  $("#x-code").onchange = () => { $("#x-tf").value = strategies[$("#x-code").value].timeframe; holdingOptions(); later(); };
  $("#x-tf").onchange = async () => { await loadExpiries(); later(); };
  $("#x-hold").onchange = later;
  $("#x-date").onchange = async () => { if (S.inst === "OPT") await loadStrikes(); later(); };
  $("#x-start").onchange = () => { paint(); later(); };
  $("#x-end").onchange = later; $("#x-before").onchange = later; $("#x-liq").onchange = later;
  $$("#x-inst button").forEach((b) => b.onclick = async () => { S.inst = b.dataset.i; paint(); if (S.inst === "OPT" && !$("#x-strike").options.length) await loadStrikes(); later(); });
  $$("#x-right button").forEach((b) => b.onclick = async () => { S.right = b.dataset.r; paint(); await loadStrikes(); later(); });
  $$("#x-side button").forEach((b) => b.onclick = () => { S.side = b.dataset.s; save(); paint(); render(); });
  $("#x-exp").onchange = async () => { S.exp = $("#x-exp").value; await loadStrikes(); later(); };
  $("#x-strike").onchange = () => { S.strike = $("#x-strike").value; later(); };
  $("#x-go").onclick = show;
  await loadExpiries();
  if (S.inst === "OPT") await loadStrikes();
  paint();
  show();
}

function holdingOptions() {
  // the strategy's own holding, said in words, and only the other choices that differ from it
  const sq = strategies[$("#x-code").value]?.square_off ?? null;
  const own = meta.strategies.find((s) => s.code === $("#x-code").value);
  const ownSq = own?.square_off;
  const ownTxt = ownSq ? `strategy's own (intraday ${ownSq})` : "strategy's own (positional)";
  const opts = [["own", ownTxt]];
  if (ownSq !== "15:25") opts.push(["15:25", "intraday — flat by 15:25"]);
  if (ownSq) opts.push(["none", "positional — held overnight"]);
  $("#x-hold").innerHTML = opts.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
  $("#x-hold").value = opts.some(([v]) => v === S.hold) ? S.hold : "own";
  void sq;
}

function paint() {
  $$("#x-inst button").forEach((b) => b.classList.toggle("on", b.dataset.i === S.inst));
  $$("#x-right button").forEach((b) => b.classList.toggle("on", b.dataset.r === S.right));
  $$("#x-side button").forEach((b) => b.classList.toggle("on", b.dataset.s === S.side));
  const opt = S.inst === "OPT";
  $$(".x-opt").forEach((e) => e.hidden = !opt);
  $$("#x-start .o-opt").forEach((o) => { o.hidden = !opt; o.disabled = !opt; });
  if (!opt && $("#x-start").value !== "days") $("#x-start").value = "days";
  $("#x-before-l").hidden = $("#x-start").value !== "days";
  $("#x-liq-l").hidden = $("#x-start").value !== "liquid";
}

async function loadExpiries() {
  try { expiries = await api("/api/explorer/expiries?" + new URLSearchParams({ tf: $("#x-tf").value })); } catch (e) { expiries = []; }
  const byYear = {};
  for (const x of expiries) (byYear[x.expiry.slice(0, 4)] = byYear[x.expiry.slice(0, 4)] || []).push(x);
  $("#x-exp").innerHTML = Object.keys(byYear).sort().reverse().map((y) => `<optgroup label="${y}">${byYear[y].map((x) =>
    `<option value="${x.expiry}">${x.expiry} · ${x.monthly ? "monthly" : "weekly"}${x.full_chain ? "" : " · strikes near settlement only"}</option>`).join("")}</optgroup>`).join("");
  if (S.exp && expiries.some((x) => x.expiry === S.exp)) $("#x-exp").value = S.exp;
  else {                                           // the first expiry on or after the date
    const d = $("#x-date").value, next = [...expiries].reverse().find((x) => x.expiry >= d);
    if (next) $("#x-exp").value = next.expiry;
  }
  S.exp = $("#x-exp").value;
}

async function loadStrikes() {
  if (!$("#x-exp").value) return;
  let s;
  try { s = await api("/api/explorer/strikes?" + new URLSearchParams({ expiry: $("#x-exp").value, tf: $("#x-tf").value, date: $("#x-date").value })); }
  catch (e) { $("#x-life").textContent = e.message; $("#x-strike").innerHTML = ""; return; }
  const ks = s.strikes[S.right] || [], keep = ks.map(String).includes(String(S.strike)) && S.strikeExp === s.expiry;
  const pick = keep ? +S.strike : s.atm[S.right];
  $("#x-strike").innerHTML = ks.map((k) => `<option value="${k}" ${k === pick ? "selected" : ""}>${k}${k === s.atm[S.right] ? " · ATM on " + s.date.slice(5) : ""}</option>`).join("");
  S.strike = $("#x-strike").value; S.strikeExp = s.expiry;
  if ($("#x-date").value !== s.date) $("#x-date").value = s.date;     // the date moved into the contract's life
  $("#x-life").textContent = `contracts traded ${s.first} → ${s.last} · index close on ${s.date}: ${num(s.index_close, 1)} · ${ks.length} ${S.right} strikes`;
}

async function show() {
  clearTimeout(timer);
  const q = { date: $("#x-date").value, inst: S.inst, code: $("#x-code").value, tf: $("#x-tf").value, days_before: $("#x-before").value, holding: $("#x-hold").value };
  if (S.inst === "OPT") Object.assign(q, { expiry: $("#x-exp").value, strike: $("#x-strike").value, right: S.right,
                                           start: $("#x-start").value, end: $("#x-end").value, liq_pct: $("#x-liq").value });
  Object.assign(S, { date: q.date, code: q.code, tf: q.tf, hold: q.holding, before: q.days_before, start: $("#x-start").value, end: $("#x-end").value, liq: $("#x-liq").value });
  save();
  const my = ++req;
  $("#x-msg").textContent = "computing…";
  let d;
  try { d = await api("/api/explorer/chart?" + new URLSearchParams(q)); } catch (e) { if (my === req) $("#x-msg").textContent = e.message; return; }
  if (my !== req) return;
  data = d;
  render();
}

function render() {
  // the side filter is applied here, on the computed trades: All / Long / Short
  const d = data; if (!d) return;
  const m = d.meta, C = Object.fromEntries(d.cols.map((k, i) => [k, i]));
  const rows = d.trades.filter((r) => S.side === "all" || r[C.position] === S.side);
  const net = rows.reduce((a, r) => a + r[C.net], 0);
  const hold = m.position?.square_off ? `intraday ${m.position.square_off}` : "positional";
  $("#x-msg").innerHTML = `<b>${esc(m.instrument)}</b> · ${esc(m.strategy)} · ${TF_LABEL[m.tf]} · ${esc(hold)} · ${esc((m.range || [m.first_shown, m.date]).join(" → "))} · warm-up from ${esc(m.warmup_from)} · <span class="muted">${esc(m.note)}</span>`;
  const shown = Object.assign({}, d, { trades: rows });
  shown.day = m.range ? m.range[0] : m.first_shown;
  shown.sessions = new Set(d.candles.map((c) => new Date(c[0] * 1000).toISOString().slice(0, 10))).size;
  view.showStatic(shown, { code: m.code, run: { underlying: "FUT", label: "explorer", run: "" }, type: "FUT", choice: "-", result: { cols: d.cols }, rows: [],
                           spec: { position: m.position } });
  if (m.range) view.to = m.range[1];
  $("#x-miles").innerHTML = (d.milestones || []).map((x) => x.ts == null
    ? `<span class="chip muted">${esc(x.label)}: never</span>`
    : `<button class="chip-t" data-ts="${x.ts}" title="zoom the chart to it">${esc(x.label)} · ${esc(x.time.slice(0, 16))}</button>`).join("");
  $$("#x-miles button").forEach((b) => b.onclick = () => {
    const t = +b.dataset.ts, c = view.charts[0];
    if (c) try { c.timeScale().setVisibleRange({ from: t - 4 * 3600, to: t + 4 * 3600 }); } catch (e) {}
  });
  const longs = d.trades.filter((r) => r[C.position] === "LONG").length;
  $("#x-sum").innerHTML = `${rows.length} shown (${longs} long · ${d.trades.length - longs} short) · net <span class="${cls(net)}">${inr(net)}</span>`;
  $("#x-trades").innerHTML = `<tr>${["Position", "Lots", "CHoCH", "Entry", "Entry px", "SL", "Exit", "Exit px", "Reason", "Pts", "Gross", "Charges", "Net", "MFE", "MAE"].map((h, i) => `<th class="${i < 4 || i === 6 || i === 8 ? "l" : ""}">${h}</th>`).join("")}</tr>` +
    rows.map((r) => `<tr class="click" data-t="${esc(r[C.entry_time])}"><td class="l"><span class="pill ${r[C.position] === "LONG" ? "pl" : "ps"}">${esc(r[C.label] || r[C.position])}</span></td><td>${r[C.lots]}</td>
      <td class="l">${esc(r[C.choch_time].slice(5, 16))}</td><td class="l">${esc(r[C.entry_time].slice(0, 16))}</td><td>${num(r[C.entry_px])}</td><td>${num(r[C.sl])}</td>
      <td class="l">${esc(r[C.exit_time].slice(0, 16))}${r[C.open] ? " *" : ""}</td><td>${num(r[C.exit_px])}</td><td class="l">${esc(reasonTag(r[C.exit_reason]))}</td>
      <td class="${cls(r[C.pts])}">${num(r[C.pts], 1)}</td><td>${inr(r[C.gross])}</td><td>${inr(r[C.charges])}</td><td class="${cls(r[C.net])}">${inr(r[C.net])}</td>
      <td>${num(r[C.mfe], 1)}</td><td>${num(r[C.mae], 1)}</td></tr>`).join("");
  $$("#x-trades tr.click").forEach((tr) => tr.onclick = () => {
    const t = tsOf(tr.dataset.t), c = view.charts[0];
    if (c) try { c.timeScale().setVisibleRange({ from: t - 2400, to: t + 2400 }); } catch (e) {}
    $("#x-chart").scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("#x-sk-sum").textContent = `Not taken (${d.skipped.length})`;
  $("#x-sk").innerHTML = d.skipped.map((s) => `<div class="small">${esc(s.entry_time)} · ${esc(s.position)} · ${esc(s.why)}</div>`).join("");
}

start().catch((e) => { $("#x-msg").textContent = "Server not reachable: " + e.message; });
