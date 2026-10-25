// Charts: plain candles of the index, the futures or any option contract, with indicators the reader adds (/api/candles).
// Every indicator is computed here, on the candles loaded (the shown sessions plus a warm-up before them).
import { $, $$, api, esc, num, css, pref } from "./util.js";
import { drawStack } from "./stack.js";

// ---------------------------------------------------------------- indicators: what can be added, their settings and their maths
const COLORS = ["#2962ff", "#ff6d00", "#e5484d", "#30a46c", "#8e4ec6", "#f5a524", "#12a594", "#6b7280"];
const SRC = ["close", "open", "high", "low", "hl2", "hlc3"];
const DEFS = {
  SMA:  { label: "SMA", pane: false, params: { period: 20, source: "close" } },
  EMA:  { label: "EMA", pane: false, params: { period: 20, source: "close" } },
  VWAP: { label: "VWAP (session)", pane: false, params: {} },
  BB:   { label: "Bollinger bands", pane: false, params: { period: 20, mult: 2, source: "close" } },
  PDHL: { label: "Previous day high / low", pane: false, params: {} },
  DOPEN:{ label: "Day open", pane: false, params: {} },
  RSI:  { label: "RSI", pane: true, params: { period: 14, source: "close" } },
  MACD: { label: "MACD", pane: true, params: { fast: 12, slow: 26, signal: 9 } },
  ATR:  { label: "ATR", pane: true, params: { period: 14 } },
};
const src = (c, s) => s === "open" ? c[1] : s === "high" ? c[2] : s === "low" ? c[3] : s === "hl2" ? (c[2] + c[3]) / 2 : s === "hlc3" ? (c[2] + c[3] + c[4]) / 3 : c[4];
function sma(x, n) { const o = Array(x.length).fill(null); let s = 0; for (let i = 0; i < x.length; i++) { s += x[i]; if (i >= n) s -= x[i - n]; if (i >= n - 1) o[i] = s / n; } return o; }
function ema(x, n) { const o = Array(x.length).fill(null), k = 2 / (n + 1); let e = null, s = 0;
  for (let i = 0; i < x.length; i++) { if (x[i] == null) continue; if (e == null) { s += x[i]; if (i === n - 1) e = s / n; else continue; } else e = x[i] * k + e * (1 - k); o[i] = e; } return o; }
function wilder(x, n) { const o = Array(x.length).fill(null); let e = null, s = 0;
  for (let i = 0; i < x.length; i++) { if (e == null) { s += x[i]; if (i === n - 1) e = s / n; else continue; } else e = (e * (n - 1) + x[i]) / n; o[i] = e; } return o; }
const dayOf = (t) => Math.floor(t / 86400);
function compute(ind, C) {
  const p = ind.params, t = C.map((c) => c[0]);
  const line = (v, color, title) => ({ color, title, data: t.map((x, i) => (v[i] == null ? { time: x } : { time: x, value: +v[i].toFixed(2) })) });
  if (ind.type === "SMA" || ind.type === "EMA") {
    const v = (ind.type === "SMA" ? sma : ema)(C.map((c) => src(c, p.source)), +p.period);
    return [line(v, ind.color, `${ind.type} ${p.period}${p.source !== "close" ? " " + p.source : ""}`)];
  }
  if (ind.type === "BB") {
    const x = C.map((c) => src(c, p.source)), n = +p.period, m = sma(x, n), up = [], dn = [];
    for (let i = 0; i < x.length; i++) {
      if (m[i] == null) { up.push(null); dn.push(null); continue; }
      let s = 0; for (let j = i - n + 1; j <= i; j++) s += (x[j] - m[i]) ** 2;
      const sd = Math.sqrt(s / n); up.push(m[i] + p.mult * sd); dn.push(m[i] - p.mult * sd);
    }
    return [line(m, ind.color, `BB ${n}`), { ...line(up, ind.color, ""), dash: true }, { ...line(dn, ind.color, ""), dash: true }];
  }
  if (ind.type === "VWAP") {
    const v = []; let pv = 0, vv = 0, d = null;
    for (const c of C) { if (dayOf(c[0]) !== d) { d = dayOf(c[0]); pv = vv = 0; } const tp = (c[2] + c[3] + c[4]) / 3; pv += tp * c[5]; vv += c[5]; v.push(vv > 0 ? pv / vv : null); }
    return [{ ...line(v, ind.color, "VWAP"), note: C.some((c) => c[5] > 0) ? "" : "no volume on these candles (the index has none): VWAP cannot be drawn" }];
  }
  if (ind.type === "PDHL" || ind.type === "DOPEN") {
    const days = new Map(); for (const c of C) { const d = dayOf(c[0]); const x = days.get(d); if (!x) days.set(d, { o: c[1], h: c[2], l: c[3] }); else { x.h = Math.max(x.h, c[2]); x.l = Math.min(x.l, c[3]); } }
    const ks = [...days.keys()], hi = [], lo = [], op = [];
    for (const c of C) { const d = dayOf(c[0]), k = ks.indexOf(d), prev = k > 0 ? days.get(ks[k - 1]) : null;
      hi.push(prev ? prev.h : null); lo.push(prev ? prev.l : null); op.push(days.get(d).o); }
    const step = (o) => ({ ...o, step: true });
    return ind.type === "PDHL" ? [step(line(hi, "#30a46c", "prev high")), step(line(lo, "#e5484d", "prev low"))] : [step(line(op, ind.color, "day open"))];
  }
  if (ind.type === "RSI") {
    const x = C.map((c) => src(c, p.source)), g = [0], l = [0];
    for (let i = 1; i < x.length; i++) { const d = x[i] - x[i - 1]; g.push(Math.max(d, 0)); l.push(Math.max(-d, 0)); }
    const ag = wilder(g.slice(1), +p.period), al = wilder(l.slice(1), +p.period);
    const v = [null, ...ag.map((a, i) => (a == null ? null : al[i] === 0 ? 100 : 100 - 100 / (1 + a / al[i])))];
    return [line(v, ind.color, `RSI ${p.period}`), { ...line(v.map(() => 70), "#9e9e9e", ""), dash: true, guide: true }, { ...line(v.map(() => 30), "#9e9e9e", ""), dash: true, guide: true }];
  }
  if (ind.type === "MACD") {
    const x = C.map((c) => c[4]), f = ema(x, +p.fast), s = ema(x, +p.slow), m = f.map((a, i) => (a == null || s[i] == null ? null : a - s[i]));
    const first = m.findIndex((v) => v != null), sigv = Array(m.length).fill(null);
    if (first >= 0) ema(m.slice(first), +p.signal).forEach((v, i) => (sigv[first + i] = v));
    return [line(m, ind.color, `MACD ${p.fast}/${p.slow}`), line(sigv, "#ff6d00", `signal ${p.signal}`),
            { ...line(m.map((v, i) => (v == null || sigv[i] == null ? null : v - sigv[i])), "#9e9e9e", "hist"), hist: true }];
  }
  if (ind.type === "ATR") {
    const tr = C.map((c, i) => (i ? Math.max(c[2] - c[3], Math.abs(c[2] - C[i - 1][4]), Math.abs(c[3] - C[i - 1][4])) : c[2] - c[3]));
    return [line(wilder(tr, +p.period), ind.color, `ATR ${p.period}`)];
  }
  return [];
}

// ---------------------------------------------------------------- page state
const st = { inst: pref("charts.inst") || "FUT", right: "CE", exp: "", strike: "", exps: null, ks: null,
             inds: pref("charts.inds") || [{ id: 1, type: "SMA", params: { period: 20, source: "close" }, color: COLORS[0] },
                                           { id: 2, type: "EMA", params: { period: 50, source: "close" }, color: COLORS[1] }] };
let charts = [], data = null, req = 0;
const save = () => { pref("charts.inds", st.inds); pref("charts.inst", st.inst); };
const tf = () => $("#c-tf").value;
const TFM = { minute: 1, "3minute": 3, "5minute": 5, "15minute": 15, "30minute": 30, "60minute": 60 };

function setSeg(id, attr, val) { $$(`#${id} button`).forEach((b) => b.classList.toggle("on", b.dataset[attr] === val)); }
function showOpt() {
  const opt = st.inst === "OPT" || st.inst === "STACK", stack = st.inst === "STACK";
  $$(".c-opt").forEach((e) => (e.hidden = !opt));
  $$("#c-start .o-opt").forEach((o) => { o.hidden = !opt; o.disabled = !opt; });
  if (!opt) { $("#c-start").value = "days"; $("#c-end").value = "date"; }
  $("#c-days-l").hidden = $("#c-start").value !== "days";
  setSeg("c-inst", "i", st.inst); setSeg("c-right", "r", st.right);
  $("#c-right-f").hidden = stack; $("#c-start-l").hidden = stack; $("#c-end-l").hidden = stack;   // Stack: the same strike's CE and PE, the shown sessions
  $("#c-main").hidden = stack; $("#c-oi-l").hidden = stack;    // Stack: the indicators apply to every candle chart in it
  if (stack) { st.right = "CE"; $("#c-start").value = "days"; $("#c-days-l").hidden = false; }
}
function shiftDay(d, k) { let x = new Date(d + "T00:00:00Z"); do { x = new Date(x.getTime() + k * 86400000); } while (x.getUTCDay() === 0 || x.getUTCDay() === 6); return x.toISOString().slice(0, 10); }
const optTf = () => (TFM[tf()] < 5 ? "minute" : "5minute");

// option pickers as in the explorer: year -> expiry (weekly / monthly, full chain or not) -> right -> strike (its own dates)
async function loadExpiries() {
  if (!st.exps) st.exps = (await api("/api/store/expiries")).map((e) => ({ ...e, full_chain: true }));
  const years = [...new Set(st.exps.map((e) => e.expiry.slice(0, 4)))].sort().reverse();
  const day = $("#c-date").value;
  if (!st.exp || !st.exps.some((e) => e.expiry === st.exp)) {
    const next = [...st.exps].sort((a, b) => (a.expiry < b.expiry ? -1 : 1)).find((e) => e.expiry >= day);
    st.exp = (next || st.exps[0]).expiry;
  }
  st.year = st.exp.slice(0, 4);
  $("#c-year").innerHTML = years.map((y) => `<option ${y === st.year ? "selected" : ""}>${y}</option>`).join("");
  $("#c-exp").innerHTML = st.exps.filter((e) => e.expiry.startsWith(st.year)).sort((a, b) => (a.expiry < b.expiry ? 1 : -1)).map((e) =>
    `<option value="${e.expiry}" ${e.expiry === st.exp ? "selected" : ""}>${e.expiry} · ${e.monthly ? "monthly" : "weekly"}${e.full_chain ? "" : " · strikes near settlement only"}</option>`).join("");
}
async function loadStrikes() {
  const s = await api("/api/store/strikes?" + new URLSearchParams({ expiry: st.exp, date: $("#c-date").value }));
  st.ks = s;
  const ks = s.strikes[st.right] || [], keep = st.userK && ks.map(String).includes(String(st.strike)) && st.kExp === s.expiry;
  st.strike = String(keep ? st.strike : s.atm[st.right] ?? ks[0] ?? ""); st.kExp = s.expiry;
  $("#c-strike").innerHTML = ks.map((k) => `<option value="${k}" ${String(k) === st.strike ? "selected" : ""}>${k}${k === s.atm[st.right] ? " · ATM on " + s.date.slice(5) : ""}</option>`).join("");
  // the chart is the selected day's: an expiry or a strike that does not trade on it is said so, never moved to another day
  const day = $("#c-date").value, life = s.lives?.[st.right]?.[st.strike];
  if (s.date !== day) throw new Error(`the ${st.exp} expiry has no candles on ${day} in the store (it trades ${s.first} → ${s.last})`);
  if (life && (day < life[0] || day > life[1])) throw new Error(`${st.right} ${st.strike} of ${st.exp} does not trade on ${day} (it trades ${life[0]} → ${life[1]}): pick another strike`);
  const moved = st.movedFrom ? ` · the ${st.movedFrom} expiry picked earlier does not trade on ${day}: moved to ${st.exp}` : "";
  $("#c-life").textContent = `${st.right} ${st.strike} traded ${life ? life[0] + " → " + life[1] : "?"} · this expiry's contracts ${s.first} → ${s.last} · index close on ${s.date}: ${num(s.index_close, 1)}${moved}`;
}

// ---------------------------------------------------------------- the indicator list (add / edit / remove)
function renderInds() {
  $("#c-add").innerHTML = Object.entries(DEFS).map(([k, d]) => `<option value="${k}">${d.label}</option>`).join("");
  $("#c-inds").innerHTML = st.inds.map((ind) => {
    const d = DEFS[ind.type];
    const fields = Object.entries(ind.params).map(([k, v]) => k === "source"
      ? `<select data-k="${k}">${SRC.map((s) => `<option ${s === v ? "selected" : ""}>${s}</option>`).join("")}</select>`
      : `<label class="small muted">${k} <input data-k="${k}" type="number" step="any" value="${v}" style="width:4.5em"></label>`).join(" ");
    return `<div class="c-ind" data-id="${ind.id}"><input type="color" value="${ind.color}" title="colour"><b class="small">${esc(d.label)}</b> ${fields}
      <button class="c-del" title="remove">✕</button></div>`;
  }).join("") || `<div class="muted small">No indicators — add one above.</div>`;
  $$(".c-ind").forEach((row) => {
    const ind = st.inds.find((x) => x.id === +row.dataset.id);
    $$("[data-k]", row).forEach((el) => (el.onchange = () => { ind.params[el.dataset.k] = el.tagName === "SELECT" ? el.value : +el.value; save(); draw(); }));
    $('input[type="color"]', row).onchange = (e) => { ind.color = e.target.value; save(); draw(); };
    $(".c-del", row).onclick = () => { st.inds = st.inds.filter((x) => x !== ind); save(); renderInds(); draw(); };
  });
}
$("#c-add-go").onclick = () => {
  const type = $("#c-add").value, id = Math.max(0, ...st.inds.map((x) => x.id)) + 1;
  st.inds.push({ id, type, params: { ...DEFS[type].params }, color: COLORS[st.inds.length % COLORS.length] });
  save(); renderInds(); load();                                   // a longer period may need more warm-up
};

// ---------------------------------------------------------------- loading and drawing
function warmBars() {
  let n = 0;
  for (const ind of st.inds) { const p = ind.params; n = Math.max(n, +(p.period || 0), +(p.slow || 0) + +(p.signal || 0)); }
  return n + 5;
}
async function load() {
  const my = ++req, shown = +$("#c-days").value;
  if (st.inst === "OPT" || st.inst === "STACK") {
    const dayNow = $("#c-date").value;
    if (st.optLast && dayNow > st.optLast) {             // past the options in the store: say so at once, no expiry search
      $("#c-legend").textContent = `no option candles on ${dayNow}: the store's options run to ${st.optLast} — pick ${st.optLast} or earlier`; clear(); return;
    }
    $("#c-legend").textContent = "finding the day's expiry and strike…";
    try {
      await loadExpiries();
      try { await loadStrikes(); }
      catch (e) {                                   // an expiry with no candles yet (or none on this day): the nearest one that has them
        if (st.userExp && !st.dayChanged) throw e;  // the user picked this expiry for this day: say so, do not move
        const orig = st.exp;
        if (st.userExp) { st.exp = ""; st.userExp = false; await loadExpiries(); }   // a new day outside the picked expiry's life: the day's nearest expiry
        const all = st.exps.map((x) => x.expiry).sort(), k = all.indexOf(st.exp), tries = [st.exp];
        for (let n = 1; n <= 6; n++) { if (all[k - n]) tries.push(all[k - n]); if (all[k + n]) tries.push(all[k + n]); }
        let ok = false;
        for (const e2 of tries) { if (my !== req) return; st.exp = e2; try { await loadExpiries(); await loadStrikes(); ok = true; break; } catch (err) { /* next */ } }   // a newer load owns the state: stop
        if (ok && st.exp !== orig) { st.movedFrom = orig; await loadStrikes(); }   // the note on the life line
        if (!ok) { st.exp = orig; await loadExpiries(); }               // show the expiry that was asked for, not the last one tried
        if (!ok) throw new Error(`no option candles on ${$("#c-date").value} in the store (options there run to ${st.exps[0]?.expiry || "?"}): pick an earlier day`);
      }
      st.dayChanged = false;
    } catch (e) { if (my === req) { $("#c-legend").textContent = e.message; clear(); } return; }   // a stale load never overwrites a newer one's legend
    if (my !== req) return;
  }
  if (st.inst === "STACK") return loadStack(my, shown);
  const day = $("#c-date").value;
  const perDay = Math.floor(375 / TFM[tf()]), warmDays = Math.ceil(warmBars() / Math.max(perDay, 1)) + 1;
  let frm = day; for (let k = 0; k < shown - 1 + warmDays + (st.inds.some((i) => i.type === "PDHL") ? 1 : 0); k++) frm = shiftDay(frm, -1);
  let showFrom = day; for (let k = 0; k < shown - 1; k++) showFrom = shiftDay(showFrom, -1);
  $("#c-legend").textContent = "loading…";
  try {
    let to = $("#c-date").value, start = $("#c-start").value;
    if (st.inst === "OPT") {                               // the contract's own range: its first day / the previous expiry, to its last day
      const life = st.ks?.lives?.[st.right]?.[st.strike];
      if (start === "listing" && life) frm = life[0];
      if (start === "prev_expiry") { const all = st.exps.map((x) => x.expiry).sort(), k = all.indexOf(st.exp); frm = k > 0 ? all[k - 1] : (life ? life[0] : frm); }
      if ($("#c-end").value === "expiry" && life) to = life[1];
    }
    const q = { inst: st.inst, from: frm, to, tf: tf() };
    if (st.inst === "OPT") Object.assign(q, { expiry: st.exp, strike: st.strike, right: st.right });
    const d = await api("/api/store/candles?" + new URLSearchParams(q));
    if (my !== req) return;
    data = d; data.showFrom = st.inst === "OPT" && start !== "days" ? d.frm : showFrom; draw();
  } catch (e) { if (my === req) { $("#c-legend").textContent = e.message; clear(); } }
}
function clear() { for (const c of charts) c.remove(); charts = []; $("#c-panes").innerHTML = ""; }
// the Stack view: futures, CE | PE at 15 / 5 / 1 minutes, the OI built at each premium, the OI, CE + PE combined
let stackData = null;
async function loadStack(my, shown) {
  const day = $("#c-date").value, L = st.ks?.lives || {}, k = st.strike;
  let showFrom = day; for (let n = 0; n < shown - 1; n++) showFrom = shiftDay(showFrom, -1);
  // the futures' warm-up for the indicators (the options are read from their first candle, so they have theirs)
  const perDay = Math.floor(375 / TFM[tf()]), warmDays = Math.ceil(warmBars() / Math.max(perDay, 1)) + 1 + (st.inds.some((i) => i.type === "PDHL") ? 1 : 0);
  let futFrom = showFrom; for (let n = 0; n < warmDays; n++) futFrom = shiftDay(futFrom, -1);
  $("#c-legend").textContent = "loading…";
  try {
    if (!L.PE?.[k]) throw new Error(`no PE ${k} for the ${st.exp} expiry in the store: pick another strike`);
    const lifeCE = L.CE?.[k], lifePE = L.PE[k];
    const opt = (r, life) => api("/api/store/candles?" + new URLSearchParams({ inst: "OPT", from: life[0], to: day, tf: "minute", expiry: st.exp, strike: k, right: r }));
    const [fut, ce, pe] = await Promise.all([api("/api/store/candles?" + new URLSearchParams({ inst: "FUT", from: futFrom, to: day, tf: tf() })), opt("CE", lifeCE), opt("PE", lifePE)]);
    if (my !== req) return;
    stackData = { fut, ce, pe, showFrom, day, k };
    drawStackNow();
    const c = ce.candles[ce.candles.length - 1], p = pe.candles[pe.candles.length - 1];
    $("#c-legend").textContent = `CE ${num(c?.[4], 2)} · PE ${num(p?.[4], 2)} · CE + PE ${num((c?.[4] ?? 0) + (p?.[4] ?? 0), 2)} at ${c ? new Date(c[0] * 1000).toISOString().slice(0, 16).replace("T", " ") : "?"}`;
  } catch (e) { if (my === req) { $("#c-legend").textContent = e.message; clear(); } }
}
function drawStackNow() {
  if (!stackData) return;
  const { fut, ce, pe, showFrom, day, k } = stackData;
  clear();
  $("#c-title").innerHTML = `<b>Stack · ${esc(st.exp)} ${esc(k)}</b> <span class="muted">· ${showFrom} → ${day} · futures and CE + PE at the ${$("#c-tf").selectedOptions[0].text} candles chosen; CE / PE also at 15, 5 and 1 minutes</span>`;
  const nm = (s) => s.replace(/ \(store\)$/i, ""); charts = drawStack($("#c-panes"), { fut: fut.candles, ce: ce.candles, pe: pe.candles, futName: nm(fut.name), ceName: nm(ce.name), peName: nm(pe.name),
                                        showFrom, day, tfMin: TFM[tf()],
                                        overlay: (C) => st.inds.filter((i) => !DEFS[i.type].pane).flatMap((i) => compute(i, C)),
                                        panes: st.inds.filter((i) => DEFS[i.type].pane).map((i) => ({ label: `${DEFS[i.type].label} ${Object.values(i.params).join(" / ")}`, color: i.color, lines: (C) => compute(i, C) })) });
}
function opts() {
  return { autoSize: true, layout: { background: { color: css("--card") }, textColor: css("--muted"), fontSize: 11 },
           grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
           timeScale: { timeVisible: true, secondsVisible: false, borderColor: css("--line") }, rightPriceScale: { borderColor: css("--line") },
           crosshair: { mode: 0 } };
}
function draw() {
  if (st.inst === "STACK") return drawStackNow();             // an indicator edit redraws the stack from the candles already loaded
  clear(); if (!data) return;
  const C = data.candles, UP = "#089981", DN = "#f23645";
  $("#c-title").innerHTML = `<b>${esc(data.name)}</b> <span class="muted">· ${$("#c-tf").selectedOptions[0].text} candles · ${data.frm} → ${data.to}${data.contracts ? " · contract expiry " + data.contracts.join(", ") : ""}</span>`;
  const main = LightweightCharts.createChart($("#c-main"), opts()); charts.push(main);
  const cs = main.addCandlestickSeries({ upColor: UP, downColor: DN, wickUpColor: UP, wickDownColor: DN, borderVisible: false });
  cs.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.25 } });
  cs.setData(C.map((c) => ({ time: c[0], open: c[1], high: c[2], low: c[3], close: c[4] })));
  const vs = main.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
  main.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  vs.setData(C.map((c) => ({ time: c[0], value: c[5], color: c[4] >= c[1] ? "rgba(8,153,129,.5)" : "rgba(242,54,69,.5)" })));
  const notes = [], add = (ch, ln) => {
    if (ln.hist) { const h = ch.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
      h.setData(ln.data.map((p) => (p.value == null ? { time: p.time } : { ...p, color: p.value >= 0 ? "rgba(8,153,129,.6)" : "rgba(242,54,69,.6)" }))); return; }
    const s = ch.addLineSeries({ color: ln.color, lineWidth: ln.guide ? 1 : 2, lineStyle: ln.dash ? 2 : 0, lineType: ln.step ? 1 : 0, title: ln.title,
                                 priceLineVisible: false, lastValueVisible: !!ln.title, crosshairMarkerVisible: !ln.guide });
    s.setData(ln.data);
  };
  for (const ind of st.inds.filter((i) => !DEFS[i.type].pane)) for (const ln of compute(ind, C)) { add(main, ln); if (ln.note) notes.push(ln.note); }
  for (const ind of st.inds.filter((i) => DEFS[i.type].pane)) {
    const box = document.createElement("div"); box.className = "c-pane";
    box.innerHTML = `<div class="small muted" style="padding:4px 8px"><b style="color:${ind.color}">${esc(DEFS[ind.type].label)}</b> ${esc(Object.values(ind.params).join(" / "))}</div><div class="c-pane-c"></div>`;
    $("#c-panes").appendChild(box);
    const ch = LightweightCharts.createChart($(".c-pane-c", box), opts()); charts.push(ch);
    for (const ln of compute(ind, C)) add(ch, ln);
  }
  if (data.oi && $("#c-oi").checked) {                    // open interest of the instrument itself, in lakh
    const box = document.createElement("div"); box.className = "c-pane";
    box.innerHTML = `<div class="small muted" style="padding:4px 8px"><b style="color:#7b1fa2">Open interest</b> of ${esc(data.name)} (last value in each candle)</div><div class="c-pane-c"></div>`;
    $("#c-panes").prepend(box);
    const ch = LightweightCharts.createChart($(".c-pane-c", box), opts()); charts.push(ch);
    const s = ch.addLineSeries({ color: "#7b1fa2", lineWidth: 2, title: "OI", priceLineVisible: false, priceFormat: { type: "custom", formatter: (v) => (v / 1e5).toFixed(2) + " L" } });
    s.setData(C.filter((c) => c[6] > 0).map((c) => ({ time: c[0], value: c[6] })));
  }
  // the sessions asked for; the warm-up before them stays reachable by scrolling left
  const t0 = C.find((c) => new Date(c[0] * 1000).toISOString().slice(0, 10) >= data.showFrom)?.[0] ?? C[0][0], tN = C[C.length - 1][0];
  for (const ch of charts) { try { ch.timeScale().setVisibleRange({ from: t0, to: tN }); } catch (e) {} }
  const [m, ...rest] = charts;
  m.timeScale().subscribeVisibleTimeRangeChange((r) => { if (r) for (const c of rest) { try { c.timeScale().setVisibleRange(r); } catch (e) {} } });
  m.subscribeCrosshairMove((p) => {
    const c = p?.time != null ? C.find((x) => x[0] === p.time) : C[C.length - 1];
    if (!c) return;
    $("#c-legend").textContent = `${new Date(c[0] * 1000).toISOString().slice(0, 16).replace("T", " ")}  O ${num(c[1], 2)}  H ${num(c[2], 2)}  L ${num(c[3], 2)}  C ${num(c[4], 2)}  V ${num(c[5], 0)}${c.length > 6 ? `  OI ${num(c[6], 0)}` : ""}`;
  });
  const c = C[C.length - 1];
  $("#c-legend").textContent = `${C.length} candles · last ${new Date(c[0] * 1000).toISOString().slice(0, 16).replace("T", " ")}  C ${num(c[4], 2)}` + (notes.length ? " · " + notes.join(" · ") : "");
}

// ---------------------------------------------------------------- controls
$$("#c-inst button").forEach((b) => (b.onclick = () => { st.inst = b.dataset.i; save(); showOpt(); load(); }));
$$("#c-right button").forEach((b) => (b.onclick = () => { st.right = b.dataset.r; showOpt(); load(); }));
$("#c-year").onchange = (e) => {                        // a year: its expiry nearest the day, else its last one
  const y = e.target.value, list = st.exps.filter((x) => x.expiry.startsWith(y)).map((x) => x.expiry).sort();
  const d = $("#c-date").value; st.exp = list.find((x) => x >= d) || list[list.length - 1]; st.userK = false; st.userExp = false;
  if (st.exp < d || !d.startsWith(y)) $("#c-date").value = st.exp;
  load();
};
$("#c-exp").onchange = (e) => { st.exp = e.target.value; st.userExp = true; st.userK = false; st.movedFrom = ""; if ($("#c-date").value > st.exp) $("#c-date").value = st.exp; load(); };
$("#c-strike").onchange = (e) => { st.strike = e.target.value; st.userK = true; load(); };
$("#c-start").onchange = () => { showOpt(); load(); };
$("#c-end").onchange = () => load();
$("#c-tf").onchange = () => { pref("charts.tf", tf()); load(); };
$("#c-days").onchange = () => { pref("charts.days", $("#c-days").value); load(); };
const newDay = () => { if (!st.userExp) st.exp = ""; st.userK = false; st.dayChanged = true; st.movedFrom = ""; load(); };   // a new day: its nearest expiry and ATM; a picked expiry is kept while it trades on the day
$("#c-date").onchange = newDay;
$("#c-prev").onclick = () => { $("#c-date").value = shiftDay($("#c-date").value, -1); newDay(); };
$("#c-next").onclick = () => { $("#c-date").value = shiftDay($("#c-date").value, 1); newDay(); };
$("#c-go").onclick = () => load();
$("#c-oi").onchange = () => draw();

(async () => {
  $("#c-tf").value = pref("charts.tf") || "5minute";
  $("#c-days").value = pref("charts.days") || "2";
  try {
    const cv = await api("/api/store/coverage");
    $("#c-src").textContent = cv.root;
    $("#c-cov").textContent = `In the store now: index ${cv.index[0]} → ${cv.index[1]} · futures ${cv.futures[0]} → ${cv.futures[1]} · options ${cv.expiries} expiries, ${cv.options[0]} → ${cv.options[1]}`;
    st.optLast = cv.options[1];
    // the latest day with data for the chart remembered: option views stop where the options do
    $("#c-date").value = ((st.inst === "OPT" || st.inst === "STACK") && cv.options[1] < cv.index[1] ? cv.options[1] : cv.index[1]) || new Date().toISOString().slice(0, 10);
  } catch (e) { $("#c-cov").textContent = e.message; $("#c-date").value = new Date().toISOString().slice(0, 10); }
  showOpt(); renderInds(); load();
})();
