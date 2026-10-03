// Chart explorer: one instrument's candles around a date with a strategy's rules applied to them (/api/explorer/*).
import { $, $$, api, esc, inr, num, cls, pref, tsOf, TF_LABEL, reasonTag } from "./util.js";
import { ChartView } from "./chart.js";

const S = Object.assign({ inst: "FUT", right: "CE" }, pref("explorer") || {});
let meta, ins, strategies = {}, view;

async function start() {
  view = new ChartView($("#x-chart"), { static: true });
  meta = await api("/api/explorer/meta");
  strategies = Object.fromEntries(meta.strategies.map((s) => [s.code, s]));
  $("#x-code").innerHTML = meta.strategies.map((s) => `<option value="${esc(s.code)}">${esc(s.code)} · ${esc(s.name)} (${TF_LABEL[s.timeframe]})</option>`).join("");
  $("#x-tf").innerHTML = meta.tfs.map((t) => `<option value="${t}">${TF_LABEL[t]}</option>`).join("");
  const d = $("#x-date"); d.min = meta.first; d.max = meta.last; d.value = S.date || meta.last;
  $("#x-code").value = S.code || meta.strategies[0].code;
  $("#x-tf").value = S.tf || strategies[$("#x-code").value].timeframe;
  $("#x-hold").value = S.hold || "own"; $("#x-before").value = S.before ?? 1;
  $("#x-code").onchange = () => { $("#x-tf").value = strategies[$("#x-code").value].timeframe; };
  $("#x-date").onchange = loadInstruments; $("#x-tf").onchange = loadInstruments;
  $$("#x-inst button").forEach((b) => b.onclick = () => { S.inst = b.dataset.i; paint(); });
  $$("#x-right button").forEach((b) => b.onclick = () => { S.right = b.dataset.r; paint(); fillStrikes(); });
  $("#x-exp").onchange = fillStrikes;
  $("#x-start").value = S.start || "days"; $("#x-end").value = S.end || "date"; $("#x-liq").value = S.liq || 10;
  $("#x-start").onchange = paint;
  $("#x-go").onclick = show;
  paint();
  await loadInstruments();
  show();
}

function paint() {
  $$("#x-inst button").forEach((b) => b.classList.toggle("on", b.dataset.i === S.inst));
  $$("#x-right button").forEach((b) => b.classList.toggle("on", b.dataset.r === S.right));
  $("#x-opt").hidden = S.inst !== "OPT";
  $("#x-liq-l").hidden = $("#x-start").value !== "liquid";
}

async function loadInstruments() {
  $("#x-msg").textContent = "reading the instruments of that session…";
  try { ins = await api("/api/explorer/instruments?" + new URLSearchParams({ date: $("#x-date").value, tf: $("#x-tf").value })); }
  catch (e) { $("#x-msg").textContent = e.message; ins = null; return; }
  $("#x-msg").textContent = `${ins.futures.contract}${ins.futures.expiry ? " (expires " + ins.futures.expiry + ")" : ""} · index open ${num(ins.index_open, 1)} · ${ins.options.length} option expiries with candles`;
  $("#x-exp").innerHTML = ins.options.map((o) => `<option value="${o.expiry}">${o.expiry}${o.monthly ? " (monthly)" : ""}</option>`).join("");
  if (S.exp && ins.options.some((o) => o.expiry === S.exp)) $("#x-exp").value = S.exp;
  fillStrikes();
}

function fillStrikes() {
  const o = ins?.options.find((x) => x.expiry === $("#x-exp").value);
  const ks = o ? o.strikes[S.right] : [];
  const near = ks.length && ins.index_open ? ks.reduce((a, b) => (Math.abs(b - ins.index_open) < Math.abs(a - ins.index_open) ? b : a)) : ks[0];
  $("#x-strike").innerHTML = ks.map((k) => `<option ${k === near ? "selected" : ""}>${k}</option>`).join("");
}

async function show() {
  const q = { date: $("#x-date").value, inst: S.inst, code: $("#x-code").value, tf: $("#x-tf").value, days_before: $("#x-before").value, holding: $("#x-hold").value };
  if (S.inst === "OPT") Object.assign(q, { expiry: $("#x-exp").value, strike: $("#x-strike").value, right: S.right,
                                           start: $("#x-start").value, end: $("#x-end").value, liq_pct: $("#x-liq").value });
  Object.assign(S, { date: q.date, code: q.code, tf: q.tf, hold: q.holding, before: q.days_before, exp: q.expiry || S.exp,
                     start: $("#x-start").value, end: $("#x-end").value, liq: $("#x-liq").value });
  pref("explorer", S);
  $("#x-msg").textContent = "computing…";
  let d;
  try { d = await api("/api/explorer/chart?" + new URLSearchParams(q)); } catch (e) { $("#x-msg").textContent = e.message; return; }
  const m = d.meta;
  $("#x-msg").textContent = `${m.instrument} · ${m.strategy} · ${TF_LABEL[m.tf]} · warm-up from ${m.warmup_from} · lot ${m.lot_size} · slippage ${m.slippage_pts} · ${m.note}`;
  d.day = m.range ? m.range[0] : m.first_shown; d.sessions = new Set(d.candles.map((c) => new Date(c[0] * 1000).toISOString().slice(0, 10))).size;
  view.showStatic(d, { code: m.code, run: { underlying: "FUT", label: "explorer", run: "" }, type: "FUT", choice: "-", result: { cols: d.cols }, rows: [],
                       spec: { position: m.position } });
  if (m.range) view.to = m.range[1];
  // the contract's milestones: click one to zoom the chart to it
  $("#x-miles").innerHTML = (d.milestones || []).map((x) => x.ts == null
    ? `<span class="chip muted">${esc(x.label)}: never</span>`
    : `<button class="chip-t" data-ts="${x.ts}" title="zoom the chart to it">${esc(x.label)} · ${esc(x.time.slice(0, 16))}</button>`).join("");
  $$("#x-miles button").forEach((b) => b.onclick = () => {
    const t = +b.dataset.ts, c = view.charts[0];
    if (c) try { c.timeScale().setVisibleRange({ from: t - 4 * 3600, to: t + 4 * 3600 }); } catch (e) {}
  });
  const C = Object.fromEntries(d.cols.map((k, i) => [k, i]));
  $("#x-sum").innerHTML = `(${d.trades.length}) · net <span class="${cls(d.net)}">${inr(d.net)}</span>`;
  $("#x-trades").innerHTML = `<tr>${["Position", "Lots", "CHoCH", "Entry", "Entry px", "SL", "Exit", "Exit px", "Reason", "Pts", "Gross", "Charges", "Net", "MFE", "MAE"].map((h, i) => `<th class="${i < 4 || i === 6 || i === 8 ? "l" : ""}">${h}</th>`).join("")}</tr>` +
    d.trades.map((r) => `<tr class="click" data-t="${esc(r[C.entry_time])}"><td class="l">${esc(r[C.label] || r[C.position])}</td><td>${r[C.lots]}</td>
      <td class="l">${esc(r[C.choch_time].slice(11, 16))}</td><td class="l">${esc(r[C.entry_time].slice(0, 16))}</td><td>${num(r[C.entry_px])}</td><td>${num(r[C.sl])}</td>
      <td class="l">${esc(r[C.exit_time].slice(0, 16))}${r[C.open] ? " *" : ""}</td><td>${num(r[C.exit_px])}</td><td class="l">${esc(reasonTag(r[C.exit_reason]))}</td>
      <td class="${cls(r[C.pts])}">${num(r[C.pts], 1)}</td><td>${inr(r[C.gross])}</td><td>${inr(r[C.charges])}</td><td class="${cls(r[C.net])}">${inr(r[C.net])}</td>
      <td>${num(r[C.mfe], 1)}</td><td>${num(r[C.mae], 1)}</td></tr>`).join("");
  $$("#x-trades tr.click").forEach((tr) => tr.onclick = () => {
    const t = tsOf(tr.dataset.t), c = view.charts[0];
    if (c) try { c.timeScale().setVisibleRange({ from: t - 2400, to: t + 2400 }); } catch (e) {}
  });
  $("#x-sk-sum").textContent = `Not taken (${d.skipped.length})`;
  $("#x-sk").innerHTML = d.skipped.map((s) => `<div class="small">${esc(s.entry_time)} · ${esc(s.position)} · ${esc(s.why)}</div>`).join("");
}

start().catch((e) => { $("#x-msg").textContent = "Server not reachable: " + e.message; });
