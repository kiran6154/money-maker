// Chart explorer: one instrument's candles over a chosen range with a strategy's rules applied to them (/api/explorer/*).
// Controls in three groups (Strategy · Instrument · Range); every change applies at once; Refresh stays in the header.
import { $, $$, api, esc, inr, num, cls, css, pref, tsOf, TF_LABEL, reasonTag } from "./util.js";
import { ChartView } from "./chart.js";

const S = Object.assign({ inst: "FUT", right: "CE", start: "days", end: "date", before: "1", liq: "10", hold: "own" }, pref("explorer2") || {});
S.side = "all";                                   // the trade filter starts at All on every visit (a hidden Long / Short looked empty)
let meta, strategies = {}, view, data = null, timer = null, req = 0, expiries = [];

const save = () => pref("explorer2", S);
const later = () => { clearTimeout(timer); timer = setTimeout(show, 250); };

async function start() {
  view = new ChartView($("#x-chart"), { static: true, onEdge: grow });
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
  $("#x-strike").onchange = () => { S.strike = $("#x-strike").value; fitDate(); later(); };
  $("#x-go").onclick = () => show();
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
  S.strike = $("#x-strike").value; S.strikeExp = s.expiry; S.lives = s.lives; S.life = s;
  if ($("#x-date").value !== s.date) $("#x-date").value = s.date;     // the date moved into the contract's life
  fitDate();
}

function fitDate() {
  // each strike trades over its own dates: keep the date inside the chosen strike's life, and say when it moved
  const s = S.life; if (!s) return;
  const life = S.lives?.[S.right]?.[String(S.strike)];
  let moved = "";
  if (life) {
    const d = $("#x-date").value;
    if (d < life[0]) { $("#x-date").value = life[0]; moved = ` · date moved to ${life[0]}, its first day`; }
    else if (d > life[1]) { $("#x-date").value = life[1]; moved = ` · date moved to ${life[1]}, its last day`; }
  }
  $("#x-life").textContent = `${S.right} ${S.strike} traded ${life ? life[0] + " → " + life[1] : "?"} · this expiry's contracts ${s.first} → ${s.last} · index close on ${s.date}: ${num(s.index_close, 1)}${moved}`;
}

// The reader dragged past the first (dir -1) or last (dir +1) candle: load more sessions on that side and keep the view.
// The range becomes "N sessions before / after the date", whatever range the form had asked for.
const MAX_CANDLES = 60000;
let ext = null;                                   // {before, after} sessions around the date once the reader has scrolled out
async function grow(dir, keep) {
  if (!data) return;
  if (data.candles.length >= MAX_CANDLES) { flashMsg(`${data.candles.length.toLocaleString()} candles loaded: pick a higher timeframe to go further`); return; }
  const days = [...new Set(data.candles.map((c) => new Date(c[0] * 1000).toISOString().slice(0, 10)))];
  const date = data.meta.date, per = Math.max(1, data.candles.length / days.length);
  const step = Math.max(1, Math.round(1500 / per));                 // about 1,500 candles per load
  ext = ext || { before: days.filter((d) => d < date).length, after: days.filter((d) => d > date).length };
  if (dir < 0) ext.before += step; else ext.after += step;
  await show(keep);
}
function flashMsg(t) { const el = $("#x-msg"); el.dataset.note = t; el.innerHTML += ` · <span class="warn">${esc(t)}</span>`; }

async function show(keep) {
  clearTimeout(timer);
  const growing = keep !== undefined && ext;
  if (!growing) { ext = null; if (view) view.edgeDone = {}; }
  const q = { date: $("#x-date").value, inst: S.inst, code: $("#x-code").value, tf: $("#x-tf").value, days_before: $("#x-before").value, holding: $("#x-hold").value };
  if (S.inst === "OPT") Object.assign(q, { expiry: $("#x-exp").value, strike: $("#x-strike").value, right: S.right,
                                           start: $("#x-start").value, end: $("#x-end").value, liq_pct: $("#x-liq").value });
  if (growing) Object.assign(q, { date: data.meta.date, days_before: ext.before, days_after: ext.after, start: "days", end: "date" });
  if (!growing) { Object.assign(S, { date: q.date, code: q.code, tf: q.tf, hold: q.holding, before: q.days_before, start: $("#x-start").value, end: $("#x-end").value, liq: $("#x-liq").value }); save(); }
  const my = ++req;
  if (growing) $("#x-msg").innerHTML += ` · <span class="muted">loading more…</span>`; else $("#x-msg").textContent = "computing…";
  let d;
  try { d = await api("/api/explorer/chart?" + new URLSearchParams(q)); }
  catch (e) {
    if (my !== req) return;
    // never leave the previous contract's chart and P&L next to a new selection
    data = null; view.clear(); $(".ch-panes", $("#x-chart")).innerHTML = ""; $(".ch-legend", $("#x-chart")).textContent = "";
    $("#x-sum").textContent = ""; $("#x-trades").innerHTML = ""; $("#x-miles").innerHTML = ""; $("#x-sk").innerHTML = "";
    $("#x-msg").innerHTML = `<span class="warn">Nothing to show for this selection: ${esc(e.message.replace(/^\w+Error: /, ""))}. Pick another date, strike or range.</span>`;
    return;
  }
  if (my !== req) return;
  data = d;
  if (growing && keep) view.keepRange = keep;      // the chart stays where the reader was
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
  straddle();
  $("#x-sk-sum").textContent = `Not taken (${d.skipped.length})`;
  $("#x-sk").innerHTML = d.skipped.map((s) => `<div class="small">${esc(s.entry_time)} · ${esc(s.position)} · ${esc(s.why)}</div>`).join("");
}

// The day-open ATM straddle under the main chart: CE + PE premium (thick), each leg (thin), their volume; it covers the
// sessions the main chart shows and follows its time range.
let stChart = null, stReq = 0, stKey = "";
async function straddle(force) {
  const d = data; if (!d) return;
  const m = d.meta, range = m.range || [m.first_shown, m.date], key = [m.code, m.tf, range[0], range[1]].join("|");
  const host = $("#x-straddle"), msg = $("#x-st-msg");
  const follow = () => {                           // the main chart is rebuilt on every draw: (re)attach to the new one
    const main = view.charts[0]; if (!main || !stChart) return;
    const set = (r) => { if (r && stChart) try { stChart.timeScale().setVisibleRange(r); } catch (e) {} };
    main.timeScale().subscribeVisibleTimeRangeChange(set); set(main.timeScale().getVisibleRange());
  };
  if (key === stKey && stChart && !force) return follow();
  const my = ++stReq; msg.textContent = "loading…";
  let r;
  try { r = await api("/api/explorer/straddle?" + new URLSearchParams({ code: m.code, from: range[0], to: range[1], tf: m.tf })); }
  catch (e) { if (my === stReq) { msg.textContent = e.message; if (stChart) { stChart.remove(); stChart = null; } stKey = ""; } return; }
  if (my !== stReq) return;
  stKey = key;
  if (stChart) stChart.remove();
  stChart = LightweightCharts.createChart(host, { autoSize: true, layout: { background: { color: css("--card") }, textColor: css("--muted"), fontSize: 11 },
    grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } }, crosshair: { mode: 0 },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: css("--line"), rightOffset: 0 }, rightPriceScale: { borderColor: css("--line") },
    handleScroll: { mouseWheel: true, pressedMouseMove: true }, handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true } });
  // rows: [time, open, high, low, close, ce close, pe close, volume]
  const line = (o, k) => { const x = stChart.addLineSeries({ priceLineVisible: false, ...o }); x.setData(r.rows.map((q) => ({ time: q[0], value: q[k] }))); return x; };
  const vs = stChart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
  stChart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  vs.setData(r.rows.map((q) => ({ time: q[0], value: q[7], color: q[4] >= q[1] ? "rgba(8,153,129,.5)" : "rgba(242,54,69,.5)" })));
  if ($("#x-st-legs")?.checked) {
    line({ color: "#2962ff", lineWidth: 1, title: "CE", lastValueVisible: false }, 5);
    line({ color: "#ff9800", lineWidth: 1, title: "PE", lastValueVisible: false }, 6);
  }
  const main = stChart.addCandlestickSeries({ upColor: "#089981", downColor: "#f23645", wickUpColor: "#089981", wickDownColor: "#f23645", borderVisible: false, title: "CE + PE" });
  main.setData(r.rows.map((q) => ({ time: q[0], open: q[1], high: q[2], low: q[3], close: q[4] })));
  main.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.24 } });
  stChart.subscribeCrosshairMove((pt) => {
    const q = pt && pt.time ? rowAt.get(pt.time) : null;
    $("#x-st-read").textContent = q ? `${new Date(q[0] * 1000).toISOString().slice(5, 16).replace("T", " ")}  O ${q[1]}  H ${q[2]}  L ${q[3]}  C ${q[4]}  ·  CE ${q[5]}  PE ${q[6]}  ·  V ${Math.round(q[7]).toLocaleString("en-IN")}` : "";
  });
  const rowAt = new Map(r.rows.map((q) => [q[0], q]));
  // one marker per session: the strike it used (flagged when it is not the true ATM)
  const firstT = new Map(); for (const q of r.rows) { const dd = new Date(q[0] * 1000).toISOString().slice(0, 10); if (!firstT.has(dd)) firstT.set(dd, q[0]); }
  main.setMarkers(r.legs.filter((g) => g.strike && firstT.has(g.day)).map((g) => ({ time: firstT.get(g.day), position: "aboveBar", shape: "circle", size: 0.6,
    color: g.off ? "#f5a524" : "#5b6472", text: `${g.strike}${g.off ? " (ATM " + g.true_atm + " missing)" : ""}` })));
  const ok = r.legs.filter((g) => g.strike), bad = r.legs.filter((g) => !g.strike), off = ok.filter((g) => g.off);
  const g0 = ok[ok.length - 1];
  msg.innerHTML = !ok.length ? `<span class="warn">No day in this range has both an ATM CE and PE in the data (${esc(bad[0]?.why || "")}).</span>`
    : `${ok.length} session${ok.length > 1 ? "s" : ""} · ${esc(g0.day)}: strike <b>${g0.strike}</b> (index opened ${num(g0.index_open, 1)}), expiry ${esc(g0.expiry)}, ` +
      `combined premium ${num(g0.first)} → ${num(g0.last)} <span class="${cls(g0.last - g0.first)}">(${g0.last - g0.first >= 0 ? "+" : ""}${num(g0.last - g0.first)})</span>` +
      (off.length ? ` · <span class="warn">${off.length} session(s) use the nearest strike with candles, not the true ATM</span>` : "") +
      (bad.length ? ` · <span class="warn">${bad.length} session(s) without a CE + PE pair in the data</span>` : "") +
      ` · candles = CE + PE (day range ${num(g0.low)} – ${num(g0.high)}), bars = volume of both`;
  follow();
}

document.addEventListener("change", (e) => { if (e.target && e.target.id === "x-st-legs") straddle(true); });

start().catch((e) => { $("#x-msg").textContent = "Server not reachable: " + e.message; });
