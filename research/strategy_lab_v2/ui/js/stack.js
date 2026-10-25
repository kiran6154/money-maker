// The Charts page's Stack view: one day's futures, the same strike's CE and PE at 15 / 5 / 1 minutes side by side, the OI
// built at each premium level over the contract's life, the CE / PE open interest, and the CE + PE combined candles.
// Everything is drawn from three requests: the futures at the chosen timeframe, and the CE and PE 1-minute candles from
// each contract's first candle to the chosen day (never after it). 5 / 15-minute candles are built here from the 1-minute
// ones, 09:15-aligned (OI = the last value in the candle).
import { esc, num, css } from "./util.js";

const UP = "#089981", DN = "#f23645", CE_C = "#2962ff", PE_C = "#ff6d00";

export function bucket(C, m) {
  if (m === 1) return C;
  const out = [];
  for (const c of C) {
    const tod = c[0] % 86400, b = c[0] - tod + (555 + Math.floor((tod / 60 - 555) / m) * m) * 60, last = out[out.length - 1];
    if (last && last[0] === b) { last[2] = Math.max(last[2], c[2]); last[3] = Math.min(last[3], c[3]); last[4] = c[4]; last[5] += c[5]; if (c.length > 6) last[6] = c[6]; }
    else out.push([b, c[1], c[2], c[3], c[4], c[5], ...(c.length > 6 ? [c[6]] : [])]);
  }
  return out;
}

// CE + PE per minute (open = the two opens, close = the two closes, high / low = the higher / lower of that open and close:
// the legs' own highs come at different moments), then bucketed
export function combined(ce, pe, m) {
  const P = new Map(pe.map((c) => [c[0], c])), out = [];
  for (const a of ce) {
    const b = P.get(a[0]); if (!b) continue;
    const o = a[1] + b[1], c = a[4] + b[4];
    out.push([a[0], o, Math.max(o, c), Math.min(o, c), c, a[5] + b[5]]);
  }
  return bucket(out, m);
}

// OI built at each premium level: every candle's change in OI is credited to the bin its close fell in
export function profile(C) {
  const pts = C.filter((c) => c.length > 6 && c[6] > 0);
  if (pts.length < 2) return null;
  const lo = Math.min(...pts.map((c) => c[4])), hi = Math.max(...pts.map((c) => c[4]));
  const raw = (hi - lo) / 24, mag = 10 ** Math.floor(Math.log10(Math.max(raw, 0.05)));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw) || raw;
  const b0 = Math.floor(lo / step) * step, n = Math.max(1, Math.ceil((hi - b0) / step) + (hi === b0 ? 1 : 0));
  const add = Array(n).fill(0), cut = Array(n).fill(0);
  for (let i = 1; i < pts.length; i++) {
    const d = pts[i][6] - pts[i - 1][6], k = Math.min(n - 1, Math.max(0, Math.floor((pts[i][4] - b0) / step)));
    if (d >= 0) add[k] += d; else cut[k] += d;
  }
  return { b0, step, n, add, cut, last: pts[pts.length - 1][4], oi: pts[pts.length - 1][6] };
}

const lakh = (v) => (Math.abs(v) >= 1e5 ? (v / 1e5).toFixed(1) + "L" : Math.abs(v) >= 1e3 ? (v / 1e3).toFixed(0) + "k" : String(Math.round(v)));

function profileSvg(p, color, name) {
  if (!p) return `<div class="muted small" style="padding:8px">${esc(name)}: no open interest on these candles</div>`;
  const net = p.add.map((a, i) => a + p.cut[i]);
  const big = Math.max(1, ...p.add.map(Math.abs), ...p.cut.map(Math.abs));
  const tot = p.add.reduce((s, v) => s + v, 0), kMax = p.add.indexOf(Math.max(...p.add));
  // the bins that carry OI (1% of the largest or more), and the bin the price is in; the empty extremes are dropped
  const keep = [...Array(p.n).keys()].filter((k) => p.add[k] - p.cut[k] >= big * 0.01 || (p.last >= p.b0 + k * p.step && p.last < p.b0 + (k + 1) * p.step));
  const kLo = Math.min(...keep), kHi = Math.max(...keep), nShow = kHi - kLo + 1;
  const W = 560, rowH = 18, H = nShow * rowH + 8, x0 = 92, wMax = W - x0 - 175;
  let rows = "";
  for (let k = kHi; k >= kLo; k--) {
    const y = (kHi - k) * rowH + 4, a = p.b0 + k * p.step, z = a + p.step, here = p.last >= a && p.last < z;
    const wa = (p.add[k] / big) * wMax, wc = (-p.cut[k] / big) * wMax;
    rows += `<text x="${x0 - 6}" y="${y + 12}" text-anchor="end" font-size="11" fill="${here ? css("--ink") : css("--muted")}" font-weight="${here ? 700 : 400}">${num(a, a < 100 ? 1 : 0)}–${num(z, z < 100 ? 1 : 0)}</text>`;
    rows += `<rect x="${x0}" y="${y + 1}" width="${Math.max(wa, 0)}" height="${rowH - 4}" fill="${k === kMax ? color : color + "99"}"/>`;
    if (wc > 0) rows += `<rect x="${x0}" y="${y + rowH - 5}" width="${wc}" height="3" fill="${DN}"/>`;
    rows += `<text x="${x0 + Math.max(wa, wc) + 4}" y="${y + 12}" font-size="10.5" fill="${css("--muted")}">${p.add[k] ? "+" + lakh(p.add[k]) : ""}${p.cut[k] ? " / −" + lakh(-p.cut[k]) : ""}${net[k] && p.cut[k] ? " = " + (net[k] >= 0 ? "+" : "−") + lakh(Math.abs(net[k])) : ""}</text>`;
    if (here) rows += `<line x1="${x0}" x2="${W - 4}" y1="${y + rowH / 2}" y2="${y + rowH / 2}" stroke="${css("--ink")}" stroke-dasharray="3 3" opacity=".35"/>`;
  }
  const a = p.b0 + kMax * p.step;
  return `<div class="small" style="padding:4px 8px"><b style="color:${color}">${esc(name)}</b> <span class="muted">· OI built at each premium (bin ${num(p.step, p.step < 1 ? 2 : 1)}; bars = OI added, red line = OI cut; ${p.n - nShow} empty bins hidden) · max ${num(a, 1)}–${num(a + p.step, 1)}: +${lakh(p.add[kMax])} (${tot ? Math.round((100 * p.add[kMax]) / tot) : 0}% of all added) · now ${num(p.last, 2)}, OI ${lakh(p.oi)}</span></div>
    <svg viewBox="0 0 ${W} ${H}" width="100%" style="max-height:${H}px;display:block">${rows}</svg>`;
}

function opts() {
  return { autoSize: true, layout: { background: { color: css("--card") }, textColor: css("--muted"), fontSize: 11 },
           grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
           timeScale: { timeVisible: true, secondsVisible: false, borderColor: css("--line") }, rightPriceScale: { borderColor: css("--line") },
           crosshair: { mode: 0 } };
}
const candles = (ch, C) => {
  const s = ch.addCandlestickSeries({ upColor: UP, downColor: DN, wickUpColor: UP, wickDownColor: DN, borderVisible: false });
  s.setData(C.map((c) => ({ time: c[0], open: c[1], high: c[2], low: c[3], close: c[4] }))); return s;
};

// box: the element to fill; D: { fut, ce, pe, futName, ceName, peName, showFrom, day, tfMin }. Returns the charts created.
export function drawStack(box, D) {
  const charts = [], timed = [];
  box.innerHTML = "";
  const pane = (title, h, cls = "") => {
    const el = document.createElement("div"); el.className = "c-pane " + cls;
    el.innerHTML = `<div class="small muted" style="padding:4px 8px">${title}</div><div class="c-pane-c" style="height:${h}px"></div>`;
    box.appendChild(el); return el;
  };
  const chartIn = (el, timedChart = true) => { const ch = LightweightCharts.createChart(el.querySelector(".c-pane-c"), opts()); charts.push(ch); if (timedChart) timed.push(ch); return ch; };
  const day = (C) => C.filter((c) => new Date(c[0] * 1000).toISOString().slice(0, 10) >= D.showFrom && new Date(c[0] * 1000).toISOString().slice(0, 10) <= D.day);
  // 1. futures
  candles(chartIn(pane(`<b>${esc(D.futName)}</b> · ${D.tfMin} min`, 300)), D.fut);
  // 2 - 4. CE | PE at 15, 5 and 1 minutes
  for (const m of [15, 5, 1]) {
    const row = document.createElement("div"); row.className = "c-row"; box.appendChild(row);
    for (const [nm, C, col] of [[D.ceName, D.ce, CE_C], [D.peName, D.pe, PE_C]]) {
      const el = document.createElement("div"); el.className = "c-pane";
      el.innerHTML = `<div class="small muted" style="padding:4px 8px"><b style="color:${col}">${esc(nm)}</b> · ${m} min</div><div class="c-pane-c" style="height:220px"></div>`;
      row.appendChild(el);
      candles(chartIn(el), day(bucket(C, m)));
    }
  }
  // 5. OI built at each premium level, over the contract's life to the day
  const prow = document.createElement("div"); prow.className = "c-row c-pane"; box.appendChild(prow);
  for (const [nm, C, col] of [[D.ceName, D.ce, CE_C], [D.peName, D.pe, PE_C]]) {
    const el = document.createElement("div"); el.innerHTML = profileSvg(profile(C), col, nm + " · from its first candle to " + D.day); prow.appendChild(el);
  }
  // 6. open interest, CE and PE
  const oiCh = chartIn(pane(`<b>Open interest</b> · <span style="color:${CE_C}">CE</span> and <span style="color:${PE_C}">PE</span> (last value in each minute, lakh)`, 190));
  const fmt = { type: "custom", formatter: (v) => (v / 1e5).toFixed(2) + " L" };
  for (const [C, col, t] of [[D.ce, CE_C, "CE OI"], [D.pe, PE_C, "PE OI"]]) {
    const s = oiCh.addLineSeries({ color: col, lineWidth: 2, title: t, priceLineVisible: false, priceFormat: fmt });
    s.setData(day(C).filter((c) => c[6] > 0).map((c) => ({ time: c[0], value: c[6] })));
  }
  // 7. CE + PE combined
  candles(chartIn(pane(`<b>CE + PE combined</b> (${esc(D.ceName.replace(/ CE$/, ""))} straddle premium) · ${D.tfMin} min`, 300)), day(combined(D.ce, D.pe, D.tfMin)));
  // the shown sessions, all time-based panes kept on one time range
  const all = day(D.ce); const t0 = all[0]?.[0] ?? D.fut[0]?.[0], tN = Math.max(all[all.length - 1]?.[0] ?? 0, D.fut[D.fut.length - 1]?.[0] ?? 0);
  // the panes size themselves after they are laid out, and a resize narrows a chart's visible range: the range is applied
  // once they have their width, and only then are they linked (a pan or zoom on any one moves the others)
  const fit = () => { for (const ch of timed) { try { ch.timeScale().setVisibleRange({ from: t0, to: tN }); } catch (e) {} } };
  fit();
  setTimeout(() => {
    fit();
    let busy = false;
    for (const ch of timed) ch.timeScale().subscribeVisibleTimeRangeChange((r) => {
      if (!r || busy) return; busy = true;
      for (const o of timed) if (o !== ch) { try { o.timeScale().setVisibleRange(r); } catch (e) {} }
      busy = false;
    });
  }, 400);
  return charts;
}
