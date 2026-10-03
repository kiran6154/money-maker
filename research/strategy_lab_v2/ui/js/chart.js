// The chart card: the signal candles (futures or index) of one or more sessions with the engine's layers and the trades,
// plus a CE pane and a PE pane (each traded option contract on its own candles) for option types. Computed by the server
// on request (/api/chart). Layers can be switched off; the choice and the chart height are remembered per viewer.
import { $, $$, api, esc, inr, num, css, tsOf, dayOf, pref, reasonTag } from "./util.js";

const LAYERS = [["trades", "Trades"], ["rlevels", "1R/2R/3R"], ["avwap", "AVWAP pair"], ["prot", "Protected"], ["events", "CHoCH/BOS"],
                ["swings", "Swings"], ["volume", "Volume"], ["zones", "Zones"], ["ribbon", "Ribbon"]];
const ZONE_COLORS = { A: "#8e4ec6", B: "#0090ff" };

export class ChartView {
  constructor(root, hooks) {
    this.root = root; this.hooks = hooks || {};
    this.layers = Object.assign(Object.fromEntries(LAYERS.map(([k]) => [k, k !== "swings" ? true : true])), pref("layers") || {});
    this.charts = []; this.req = 0;
    root.innerHTML = `
      <div class="ch-bar">
        <div class="ch-nav">
          <button class="icon" data-k="prev" title="Previous trading day with candles">‹</button>
          <input type="date" class="ch-day" aria-label="Day">
          <button class="icon" data-k="next" title="Next trading day">›</button>
          <select class="ch-days" aria-label="Days with trades"></select>
          <button data-k="full" title="Every session of the run (heavy on long 1-minute runs)">Full period</button>
          <button data-k="snap" title="Save the chart as a PNG">PNG</button>
        </div>
        <div class="ch-layers">${LAYERS.map(([k, l]) => `<button class="chip-t" data-layer="${k}">${l}</button>`).join("")}</div>
      </div>
      <div class="ch-legend muted small"></div>
      <div class="ch-read mono small"></div>
      <div class="ch-box"><div class="ch-main"></div></div>
      <div class="ch-panes"></div>`;
    $$(".ch-layers button", root).forEach((b) => b.onclick = () => { this.layers[b.dataset.layer] = !this.layers[b.dataset.layer]; pref("layers", this.layers); this.redraw(); });
    $('[data-k="prev"]', root).onclick = () => this.step(-1);
    $('[data-k="next"]', root).onclick = () => this.step(1);
    $('[data-k="full"]', root).onclick = () => this.open(this.ctx.result.date_from || this.ctx.run.date_from, this.ctx.run.date_to);
    $('[data-k="snap"]', root).onclick = () => this.snapshot();
    $(".ch-day", root).onchange = (e) => this.open(e.target.value);
    $(".ch-days", root).onchange = (e) => e.target.value && this.open(e.target.value);
    if (this.hooks.static)                         // the explorer: no run, so no day navigation
      $$('.ch-nav [data-k="prev"], .ch-nav [data-k="next"], .ch-nav [data-k="full"], .ch-day, .ch-days', root).forEach((e) => e.hidden = true);
    const box = $(".ch-box", root);
    const h = pref("chartH"); if (h) box.style.height = h + "px";
    new ResizeObserver(() => { if (box.offsetHeight > 150) pref("chartH", box.offsetHeight); }).observe(box);
  }

  // the explorer: draw a payload computed elsewhere, without the run's day navigation
  showStatic(data, ctx) {
    $$('.ch-nav [data-k="prev"], .ch-nav [data-k="next"], .ch-nav [data-k="full"], .ch-day, .ch-days', this.root).forEach((e) => e.hidden = true);
    this.ctx = ctx; this.data = data; this.day = data.day; this.to = null; this.panes = {};
    this.redraw();
  }

  // ctx = {code, run (meta), type, choice, result, spec, rows}
  setContext(ctx) {
    this.ctx = ctx;
    const C = this.C = Object.fromEntries(ctx.result.cols.map((k, i) => [k, i]));
    const days = [...new Set(ctx.rows.map((r) => r[C.entry_time].slice(0, 10)))].sort();
    this.tradeDays = days;
    $(".ch-days", this.root).innerHTML = `<option value="">days with trades (${days.length})</option>` +
      days.slice().reverse().map((d) => `<option>${d}</option>`).join("");
  }

  async open(day, to, focus) {
    this.day = day; this.to = to || null; this.focus = focus || null;
    $(".ch-day", this.root).value = day;
    const { code, run, type, choice } = this.ctx;
    const q = new URLSearchParams({ code, run: run.run, type, choice, day });
    if (to) q.set("to", to);
    const my = ++this.req;
    $(".ch-legend", this.root).textContent = "loading…";
    try {
      this.data = await api("/api/chart?" + q);
    } catch (e) {
      if (my !== this.req) return;
      $(".ch-legend", this.root).textContent = e.message; this.clear(); $(".ch-panes", this.root).innerHTML = ""; return;
    }
    if (my !== this.req) return;
    this.panes = {};
    if (!this.hooks.static) await this.loadPanes(my);
    if (my !== this.req) return;
    this.redraw();
  }

  async paneSource() {
    // the option row's contracts: this choice's own option trades, or - on a Futures run - the same signals traded in
    // options (the run's Options (via futures) result at the strategy's default strike), so every chart has both rows
    const { run, type, choice, spec } = this.ctx;
    if (type !== "FUT") return { type, choice, rows: this.ctx.rows, C: this.C, note: "" };
    const tm = run.types?.OPT_FUT_SIGNAL;
    if (!tm || tm.status !== "ok") return { note: tm ? `options not run for this backtest: ${tm.reason || ""}` : "options not run for this backtest" };
    const keys = Object.keys(tm.choices), want = `W-${spec.options?.strike_default}`;
    const ch = keys.includes(want) ? want : keys.find((k) => k.endsWith(spec.options?.strike_default)) || keys[0];
    const key = `${this.ctx.code}|${run.run}|${ch}`;
    if (this._optKey !== key) {
      this._optRes = await api("/api/result?" + new URLSearchParams({ code: this.ctx.code, run: run.run, type: "OPT_FUT_SIGNAL", choice: ch }));
      this._optKey = key;
    }
    const C = Object.fromEntries(this._optRes.cols.map((k, i) => [k, i]));
    return { type: "OPT_FUT_SIGNAL", choice: ch, rows: this._optRes.trades, C, note: `the same signals in options (${ch})` };
  }

  async step(k) {
    // next / previous calendar day that has candles (weekends and holidays are skipped by asking again)
    let d = new Date(this.day + "T00:00:00Z");
    for (let n = 0; n < 7; n++) {
      d = new Date(d.getTime() + k * 86400000);
      const s = d.toISOString().slice(0, 10);
      if (d.getUTCDay() === 0 || d.getUTCDay() === 6) continue;
      const { code, run, type, choice } = this.ctx;
      try { await api("/api/chart?" + new URLSearchParams({ code, run: run.run, type, choice, day: s })); return this.open(s); } catch (e) { /* no candles: keep going */ }
    }
  }

  async loadPanes(my) {
    // the option contracts traded in this range, by right; one pane per right with a picker when there are several
    let src;
    try { src = await this.paneSource(); } catch (e) { src = { note: e.message }; }
    this.paneSrc = src;
    const d0 = this.day, d1 = this.to || this.day, C = src.C;
    const inRange = src.rows ? src.rows.filter((r) => { const d = r[C.entry_time].slice(0, 10); return d >= d0 && d <= d1; }) : [];
    for (const right of ["CE", "PE"]) {
      const insts = [...new Set(inRange.filter((r) => r[C.opt_type] === right).map((r) => r[C.instrument]))];
      const pick = this.focus && insts.includes(this.focus) ? this.focus : insts[0];
      this.panes[right] = { insts, pick, data: null };
      if (pick) await this.loadPane(right, pick, my);
    }
  }

  async loadPane(right, inst, my) {
    const { code, run } = this.ctx, { type, choice } = this.paneSrc;
    const q = new URLSearchParams({ code, run: run.run, type, choice, day: this.day, inst });
    if (this.to) q.set("to", this.to);
    try { this.panes[right].data = await api("/api/chart?" + q); this.panes[right].pick = inst; }
    catch (e) { this.panes[right].data = { error: e.message }; }
  }

  clear() { for (const c of this.charts) c.remove(); this.charts = []; }

  opts(el) {
    return { autoSize: true, layout: { background: { color: css("--card") }, textColor: css("--muted"), fontSize: 11 },
             grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
             timeScale: { timeVisible: true, secondsVisible: false, borderColor: css("--line"), minBarSpacing: 0.001, rightOffset: 3 },
             rightPriceScale: { borderColor: css("--line") }, crosshair: { mode: 0 },
             handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
             handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true } };
  }

  zoomOnCtrlWheel(el, ch) {
    // plain wheel scrolls the page; Ctrl / ⌘ + wheel zooms the chart around the middle of the view
    el.addEventListener("wheel", (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const c = el._chart || ch;                       // the chart drawn in this element now (charts are redrawn)
      const ts = c.timeScale(), r = ts.getVisibleLogicalRange(); if (!r) return;
      const f = e.deltaY > 0 ? 1.18 : 0.85, mid = (r.from + r.to) / 2, half = Math.max(5, ((r.to - r.from) / 2) * f);
      ts.setVisibleLogicalRange({ from: mid - half, to: mid + half });
    }, { passive: false });
  }

  redraw() {
    this.clear();
    $$(".ch-layers button", this.root).forEach((b) => b.classList.toggle("on", !!this.layers[b.dataset.layer]));
    const d = this.data; if (!d) return;
    const main = this.draw($(".ch-main", this.root), d, { own: this.ctx.type === "FUT" && this.ctx.run.underlying !== "INDEX", main: true });
    this.legend(d);
    // row 2: the CE pane and the PE pane, side by side
    const host = $(".ch-panes", this.root);
    if (this.hooks.static) { host.innerHTML = ""; return; }
    const note = this.paneSrc?.note || "";
    host.innerHTML = ["CE", "PE"].map((r) => {
      const p = this.panes[r] || { insts: [] };
      return `<div class="pane" data-r="${r}"><div class="pane-h"><b>${r}</b>
        ${p.insts.length > 1 ? `<select>${p.insts.map((x) => `<option ${x === p.pick ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>`
                             : `<span class="muted small">${esc(p.pick || (this.paneSrc?.rows ? `no ${r} position in this range` : ""))}</span>`}
        <span class="muted small">${p.pick ? "· from the session before" : ""}${note ? " · " + esc(note) : ""}${p.data?.error ? " · " + esc(p.data.error) : ""}</span></div>
        <div class="pane-c">${p.pick ? "" : `<div class="pane-empty muted small">${esc(this.paneSrc?.rows ? `No ${r} position on ${this.day}${this.to && this.to !== this.day ? " – " + this.to : ""}.` : note)}</div>`}</div></div>`;
    }).join("");
    for (const r of ["CE", "PE"]) {
      const p = this.panes[r]; const el = $(`.pane[data-r="${r}"]`, host);
      const sel = $("select", el); if (sel) sel.onchange = async (e) => { await this.loadPane(r, e.target.value, this.req); this.redraw(); };
      if (p?.data && !p.data.error) this.draw($(".pane-c", el), p.data, { own: true });
    }
    this.sync();
  }

  sync() {
    // the panes follow the main chart's time range
    if (this.charts.length < 2) return;
    const [m, ...rest] = this.charts;
    m.timeScale().subscribeVisibleTimeRangeChange((r) => { if (!r) return; for (const c of rest) { try { c.timeScale().setVisibleRange(r); } catch (e) {} } });
  }

  draw(el, d, { own, main }) {
    const ch = LightweightCharts.createChart(el, this.opts(el));
    this.charts.push(ch);
    if (!el.dataset.wheel) { el.dataset.wheel = "1"; this.zoomOnCtrlWheel(el, ch); el._chart = ch; } else el._chart = ch;
    const L = this.layers, up = css("--up"), dn = css("--down"), mut = css("--muted"), acc = css("--accent"), warn = css("--warn");
    const cs = ch.addCandlestickSeries({ upColor: up, downColor: dn, wickUpColor: up, wickDownColor: dn, borderVisible: false });
    const times = d.candles.map((c) => c[0]);
    cs.setData(d.candles.map((c) => ({ time: c[0], open: c[1], high: c[2], low: c[3], close: c[4] })));
    if (L.volume) {
      const v = ch.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
      ch.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      v.setData(d.candles.map((c) => ({ time: c[0], value: c[5], color: c[4] >= c[1] ? up + "55" : dn + "55" })));
    }
    const line = (pts, color, style = 0, width = 1, extra = {}) => {
      const s = ch.addLineSeries(Object.assign({ color, lineWidth: width, lineStyle: style, priceLineVisible: false, lastValueVisible: false,
                                                 crosshairMarkerVisible: false }, extra));
      s.setData(pts); return s;
    };
    const snap = (t) => { let lo = 0, hi = times.length - 1; if (t < times[0] || t > times[hi] + 86400) return null;
      while (lo < hi) { const m = (lo + hi + 1) >> 1; if (times[m] <= t) lo = m; else hi = m - 1; } return times[lo]; };
    const markers = [];
    // FZ zones: each band's edges as dashed lines over the range (A births purple, B blue)
    if (L.zones && d.fz) {
      for (const [id, kind, lo, hi, born] of d.fz.ZONES) {
        const t0 = snap(Math.max(born, times[0])) ?? times[0], col = ZONE_COLORS[kind] || mut;
        const seg = times.filter((t) => t >= t0);
        if (seg.length < 2) continue;
        line(seg.map((t) => ({ time: t, value: hi })), col, 2, 1);
        line(seg.map((t) => ({ time: t, value: lo })), col, 2, 1);
      }
    }
    if (L.ribbon && d.lines) {
      const RB = ["#e5484d", "#f76b15", "#f5a524", "#e2c93a", "#7ac943", "#30a46c", "#12a594", "#0090ff", "#3e63dd", "#8e4ec6"];
      d.lines.forEach((ln, k, all) => { if (ln.length > 1) line(ln.map(([t, v]) => ({ time: t, value: v })), RB[all.length > 1 ? Math.round(9 * k / (all.length - 1)) : 0]); });
    }
    if (L.prot && d.prot) {
      const m = new Map(d.prot);
      line(times.map((t) => (m.has(t) ? { time: t, value: m.get(t) } : { time: t })), mut, 2, 1);
    }
    if (L.avwap && d.pair) for (const p of d.pair) {
      const col = p.side === "H" ? dn : up;
      if (p.live.length > 1) line(p.live.map(([t, v]) => ({ time: t, value: v })), col, 0, 1);
      if (p.back && p.back.length > 1) line(p.back.map(([t, v]) => ({ time: t, value: v })), col, 1, 1);
    }
    if (L.swings && d.swings) {
      for (const s of d.swings) markers.push({ time: s[1], position: s[0] === "H" ? "aboveBar" : "belowBar", color: mut, shape: "circle", size: 0.1 });
      if (d.cand) {
        line(d.cand.map(([t, h]) => (h == null ? { time: t } : { time: t, value: h })), mut + "66", 0, 1, { lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1 });
        line(d.cand.map(([t, , l]) => (l == null ? { time: t } : { time: t, value: l })), mut + "66", 0, 1, { lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1 });
      }
    }
    if (L.events && d.events) {
      const flips = new Set(d.flips || []);
      for (const e of d.events) markers.push(e[1] === "CHoCH"
        ? { time: e[0], position: e[2] === "up" ? "belowBar" : "aboveBar", color: acc, shape: "square", size: 0.6, text: flips.has(e[0]) ? "CHoCH ⇅" : "CHoCH" }
        : { time: e[0], position: e[2] === "up" ? "belowBar" : "aboveBar", color: mut, shape: "square", size: 0.2 });
      for (const s of d.setups || []) markers.push({ time: s[0], position: s[1] === "up" ? "belowBar" : "aboveBar", color: warn, shape: "circle", size: 0.6, text: "S" });
    }
    // FZ gate markers at each SETUP (T take, R re-enter, W watch, B block)
    if (L.zones && main && this.ctx.result.fz) {
      const Lg = this.ctx.result.fz.ledger, gi = Lg.cols.indexOf("outcome_gate"), ti = Lg.cols.indexOf("time");
      for (const r of Lg.rows) { const t = snap(tsOf(r[ti])); if (t != null && t >= times[0]) markers.push({ time: t, position: "aboveBar", color: ZONE_COLORS.A, shape: "circle", size: 0.4, text: (r[gi] || "?")[0] }); }
    }
    // trades: entry arrow, exit circle with its reason and points, the entry -> exit path, the stop and the R levels
    const C = Object.fromEntries(d.cols.map((k, i) => [k, i]));
    // a level is drawn only on its own price scale: an option traded on a futures signal carries the futures stop
    let lo = Infinity, hi = -Infinity; for (const c of d.candles) { if (c[3] < lo) lo = c[3]; if (c[2] > hi) hi = c[2]; }
    const onScale = (v) => v != null && v >= lo - (hi - lo) * 0.5 && v <= hi + (hi - lo) * 0.5;
    if (L.trades) for (const r of d.trades) {
      const te = snap(tsOf(r[C.entry_time])), tx = snap(tsOf(r[C.exit_time]));
      const lng = r[C.position] === "LONG", win = r[C.net] > 0;
      if (te != null) markers.push({ time: te, position: lng ? "belowBar" : "aboveBar", color: lng ? up : dn, shape: lng ? "arrowUp" : "arrowDown",
                                     text: (lng ? "L" : "S") + (r[C.tranche] ? " " + r[C.tranche].replace(" (trail)", "") : "") });
      if (tx != null) markers.push({ time: tx, position: lng ? "aboveBar" : "belowBar", color: win ? up : dn, shape: "circle", size: 0.6,
                                     text: `${reasonTag(r[C.exit_reason])} ${num(r[C.pts], 0)}` });
      if (own && te != null && tx != null && te < tx) {
        line([{ time: te, value: r[C.entry_px] }, { time: tx, value: r[C.exit_px] }], win ? up : dn, 2, 2);
        if (onScale(r[C.sl])) line([{ time: te, value: r[C.sl] }, { time: tx, value: r[C.sl] }], dn, 1, 1);
        if (L.rlevels && this.ctx.spec.position?.exit === "position" && onScale(r[C.sl])) {
          const R = Math.abs(r[C.entry_px] - r[C.sl]), sg = lng ? 1 : -1;
          for (const k of [1, 2, 3]) line([{ time: te, value: r[C.entry_px] + sg * k * R }, { time: tx, value: r[C.entry_px] + sg * k * R }], acc + "aa", 3, 1);
        }
      }
    }
    // every marker on a candle of this chart (a swing confirmed today can sit on yesterday's bar: dropped, not drawn
    // off the left edge, which would stretch the time axis)
    const t0 = times[0], tN = times[times.length - 1];
    const placed = markers.filter((m) => m.time != null && m.time >= t0 && m.time <= tN).map((m) => Object.assign(m, { time: snap(m.time) }));
    placed.sort((a, b) => a.time - b.time);
    cs.setMarkers(placed);
    // crosshair readout: OHLCV and, for FZ, the zone card of that bar
    const Z = d.fz ? new Map(d.fz.Z.map((z) => [z[0], z])) : null;
    ch.subscribeCrosshairMove((p) => {
      const box = $(".ch-read", this.root);
      if (!p || !p.time) { box.textContent = ""; return; }
      const c = d.candles[times.indexOf(p.time)]; if (!c) return;
      let s = `${new Date(p.time * 1000).toISOString().slice(0, 16).replace("T", " ")}  O ${c[1]}  H ${c[2]}  L ${c[3]}  C ${c[4]}  V ${Math.round(c[5]).toLocaleString("en-IN")}`;
      if (Z && Z.has(p.time)) {
        const z = Z.get(p.time), k = Object.fromEntries(d.fz.Z_COLS.map((n, i) => [n, z[i]]));
        const zone = d.fz.ZONES.find((x) => x[0] === k.zone_id);
        s += `  ·  zone ${k.zone_id ?? "–"}${zone ? ` [${zone[2]}–${zone[3]}]` : ""} visit ${k.visit_n ?? "–"} bars ${k.this_bars ?? "–"}` +
             (k.first_vol && k.this_vol ? ` vol× ${(k.this_vol / k.this_bars / (k.first_vol / k.first_bars)).toFixed(2)}` : "") +
             ` read ${d.fz.READS[k.read] ?? "–"}${k.left_id ? ` · LEAVE from ${k.left_id}` : ""}`;
      }
      box.textContent = s;
    });
    requestAnimationFrame(() => {
      if (this.focusTime && main) {
        const t = this.focusTime; this.focusTime = null;
        try { ch.timeScale().setVisibleRange({ from: t - 3600, to: t + 3600 }); return; } catch (e) {}
      }
      ch.timeScale().fitContent();
    });
    return ch;
  }

  legend(d) {
    const n = d.trades.length, net = d.trades.reduce((a, r) => a + r[d.cols.indexOf("net")], 0);
    $(".ch-legend", this.root).innerHTML =
      `${esc(this.day)}${this.to && this.to !== this.day ? " → " + esc(this.to) : ""} · ${d.sessions} session${d.sessions > 1 ? "s" : ""} · ` +
      `${d.candles.length} candles · ${n} trade${n === 1 ? "" : "s"} <span class="${net > 0 ? "pos" : net < 0 ? "neg" : ""}">${inr(net)}</span>` +
      ` · arrow = entry, circle = exit (reason, pts), dashed = path, red dots = stop` + (d.fz ? " · purple / blue dashes = FZ bands (A / B), letters = gate" : "") +
      (d.pair && d.pair.length ? " · red / green = AVWAP from SH / SL (dotted: back to the anchor)" : "") + " · drag the bottom edge to resize · Ctrl/⌘ + wheel zooms";
  }

  async snapshot() {
    if (!this.charts.length) return;
    const shots = this.charts.map((c) => c.takeScreenshot());
    const w = Math.max(...shots.map((s) => s.width)), h = shots.reduce((a, s) => a + s.height, 0) + 28;
    const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
    const g = cv.getContext("2d"); g.fillStyle = css("--card"); g.fillRect(0, 0, w, h);
    g.fillStyle = css("--ink"); g.font = "14px system-ui"; g.fillText(`${this.ctx.code} · ${this.ctx.run.label} · ${this.ctx.type} ${this.ctx.choice} · ${this.day}${this.to ? " → " + this.to : ""}`, 8, 18);
    let y = 28; for (const s of shots) { g.drawImage(s, 0, y); y += s.height; }
    const a = document.createElement("a"); a.href = cv.toDataURL("image/png"); a.download = `${this.ctx.code}_${this.day}.png`; a.click();
  }
}
