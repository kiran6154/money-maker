// The chart card: the signal candles (futures or index) of one or more sessions with the engine's layers and the trades,
// plus a CE pane and a PE pane (each traded option contract on its own candles) for option types. Computed by the server
// on request (/api/chart). Layers can be switched off; the choice and the chart height are remembered per viewer.
import { $, $$, api, esc, inr, num, css, tsOf, dayOf, pref, reasonTag } from "./util.js";

const LAYERS = [["trades", "Trades", "#111111"], ["rlevels", "1R / 2R / 3R", "#089981"], ["rainbow", "Rainbow", "#ff9800"],
                ["avwap", "AVWAP", "#ff6d00"], ["prot", "Protected", "#7b1fa2"], ["struct", "CHoCH/BOS", "#9e9e9e"],
                ["swings", "Swings", "#089981"], ["vol", "Volume", "#c3c7cf"], ["zones", "Zones", "#2962ff"],
                ["index", "Index & strike", "#6b7280"], ["miles", "Milestones", "#8e4ec6"], ["olines", "SMA", "#f5a524"]];
const ZONE_COLORS = { A: "#8e4ec6", B: "#0090ff" };

export class ChartView {
  constructor(root, hooks) {
    this.root = root; this.hooks = hooks || {};
    this.layers = Object.assign(Object.fromEntries(LAYERS.map(([k]) => [k, true])), pref("layers2") || {});
    this.charts = []; this.req = 0;
    (window.__charts = window.__charts || []).push(this);   // for inspecting the charts from the browser console
    root.innerHTML = `
      <div class="ch-bar">
        <div class="ch-nav">
          <button class="icon" data-k="prev" title="Previous trading day with candles">‹</button>
          <input type="date" class="ch-day" aria-label="Day">
          <button class="icon" data-k="next" title="Next trading day">›</button>
          <select class="ch-days" aria-label="Days with trades"></select>
          <button data-k="more-prev" title="Add the previous session to this chart">+ earlier</button>
          <button data-k="more-next" title="Add the next session to this chart">+ later</button>
          <button data-k="full" title="Every session of the run (heavy on long 1-minute runs)">Full period</button>
          <button data-k="snap" title="Save the chart as a PNG">PNG</button>
        </div>
        <div class="ch-layers"></div>
      </div>
      <div class="ch-legend muted small"></div>
      <div class="ch-read mono small"></div>
      <div class="ch-box"><div class="ch-main"></div>
</div>
      <div class="ch-panes"></div>`;
    $('[data-k="prev"]', root).onclick = () => this.step(-1);
    $('[data-k="next"]', root).onclick = () => this.step(1);
    $('[data-k="full"]', root).onclick = () => this.open(this.ctx.result.date_from || this.ctx.run.date_from, this.ctx.run.date_to);
    $('[data-k="more-prev"]', root).onclick = () => this.extend(-1);
    $('[data-k="more-next"]', root).onclick = () => this.extend(1);
    $('[data-k="snap"]', root).onclick = () => this.snapshot();
    $(".ch-day", root).onchange = (e) => this.open(e.target.value);
    $(".ch-days", root).onchange = (e) => e.target.value && this.open(e.target.value);
    if (this.hooks.static)                         // the explorer: no run, so no day navigation
      $$('.ch-nav [data-k="prev"], .ch-nav [data-k="next"], .ch-nav [data-k="full"], .ch-nav [data-k^="more"], .ch-day, .ch-days', root).forEach((e) => e.hidden = true);
    const box = $(".ch-box", root);
    const h = pref("chartH"); if (h) box.style.height = h + "px";
    new ResizeObserver(() => { if (box.offsetHeight > 150) pref("chartH", box.offsetHeight); }).observe(box);
  }

  // the explorer: draw a payload computed elsewhere, without the run's day navigation
  showStatic(data, ctx) {
    $$('.ch-nav [data-k="prev"], .ch-nav [data-k="next"], .ch-nav [data-k="full"], .ch-nav [data-k^="more"], .ch-day, .ch-days', this.root).forEach((e) => e.hidden = true);
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

  async extend(dir) {
    // + earlier / + later: load the previous (next) session into the same chart; the view stays where it was. Up to
    // MAX_SESSIONS sessions are kept so the chart stays light.
    const MAX_SESSIONS = 20;
    if (this.extending || this.hooks.static || !this.data || (this.data.sessions || 1) >= MAX_SESSIONS) return;
    this.extending = true;
    const keep = this.charts[0]?.timeScale().getVisibleRange();
    const { code, run, type, choice } = this.ctx, start = this.day, end = this.to || this.day, span = this.data.sessions || 1;
    let d = new Date((dir < 0 ? start : end) + "T00:00:00Z");
    try {
      for (let n = 0; n < 7; n++) {                 // skip weekends and holidays: the range grows only when a session is added
        d = new Date(d.getTime() + dir * 86400000);
        if (d.getUTCDay() === 0 || d.getUTCDay() === 6) continue;
        const s = d.toISOString().slice(0, 10), day = dir < 0 ? s : start, to = dir < 0 ? end : s;
        let data;
        try { data = await api("/api/chart?" + new URLSearchParams({ code, run: run.run, type, choice, day, to })); } catch (e) { continue; }
        if ((data.sessions || 1) <= span) continue;
        const my = ++this.req;
        this.day = day; this.to = to; this.data = data; this.keepRange = keep;
        $(".ch-day", this.root).value = day;
        this.panes = {};
        if (!this.hooks.static) await this.loadPanes(my);
        if (my === this.req) this.redraw();
        break;
      }
    } finally { this.extending = false; }
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
    const pane = this.panes[right];                  // a newer open() replaces this.panes; write only to this request's pane
    let data;
    try { data = await api("/api/chart?" + q); } catch (e) { data = { error: e.message }; }
    if (!pane || (my != null && my !== this.req)) return;
    pane.data = data; if (!data.error) pane.pick = inst;
  }

  clear() { for (const c of this.charts) c.remove(); this.charts = []; }

  opts(el) {
    return { autoSize: true, layout: { background: { color: css("--card") }, textColor: css("--muted"), fontSize: 11 },
             grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
             // fixed edges: zooming out stops at the first / last candle (no empty space, nothing to "reach")
             timeScale: { timeVisible: true, secondsVisible: false, borderColor: css("--line"), minBarSpacing: 0.001, rightOffset: 0,
                          fixLeftEdge: true, fixRightEdge: true },
             rightPriceScale: { borderColor: css("--line") }, crosshair: { mode: 0 },
             handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
             handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true } };
  }

  redraw() {
    this.clear();
    const d = this.data; if (!d) return;
    // the layer chips this chart has (Rainbow only for ribbon strategies, Zones only for FZ, 1R/2R/3R only for managed exits)
    const has = { rlevels: this.ctx.spec.position?.exit === "position", rainbow: !!d.lines, zones: !!d.fz, index: !!d.spot, miles: !!d.milestones,
                  olines: !!(d.olines || Object.values(this.panes || {}).some((p) => p && p.data && p.data.olines)) };
    const host0 = $(".ch-layers", this.root);
    host0.innerHTML = LAYERS.filter(([k]) => has[k] !== false).map(([k, l, col]) =>
      `<button class="chip-t lay ${this.layers[k] ? "on" : ""}" data-layer="${k}"><i style="background:${col}"></i>${l}</button>`).join("");
    $$("button", host0).forEach((b) => b.onclick = () => { this.layers[b.dataset.layer] = !this.layers[b.dataset.layer]; pref("layers2", this.layers); this.redraw(); });
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

  // v1's chart look (dashboard.tpl drawChart): TradingView-style candles, swings as small squares with their level line
  // and a confirming arrow, faded candidate dots, CHoCH (purple) / BOS (grey) dots, the AVWAP pair (orange from the SH,
  // blue from the SL; dotted back to the anchor), the protected level (purple dashes), translucent FZ bands, the trades
  // (black arrow + label at entry, coloured exit dot with its reason and points, dashed path, dotted stop) and, for
  // managed exits, the stop / target / trail levels labelled on the price axis.
  draw(el, d, { own, main }) {
    const ch = LightweightCharts.createChart(el, this.opts(el));
    this.charts.push(ch);
    el._chart = ch;
    const on = this.layers, UP = "#089981", DN = "#f23645", PURPLE = "#7b1fa2", BLUE = "#2962ff", ORANGE = "#ff6d00", GREY = "#9e9e9e";
    const C0 = d.candles, times = C0.map((c) => c[0]), t0 = times[0], tN = times[times.length - 1];
    const base = { lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, autoscaleInfoProvider: () => null };
    const rgba = (h, a) => `rgba(${parseInt(h.slice(1, 3), 16)},${parseInt(h.slice(3, 5), 16)},${parseInt(h.slice(5, 7), 16)},${a})`;
    // FZ bands: one translucent lo-hi box per band, from its birth (or the first bar) to the last bar, under the candles
    if (on.zones && d.fz) for (const [, kind, lo, hi, born] of d.fz.ZONES) {
      const a = Math.max(born, t0); if (a >= tN) continue;
      const col = rgba(kind === "A" ? PURPLE : BLUE, 0.08);
      const s = ch.addBaselineSeries({ ...base, baseValue: { type: "price", price: lo }, lineVisible: false, topLineColor: col, topFillColor1: col,
                                       topFillColor2: col, bottomLineColor: col, bottomFillColor1: col, bottomFillColor2: col });
      s.setData([{ time: this.snapT(times, a), value: hi }, { time: tN, value: hi }]);
    }
    const cs = ch.addCandlestickSeries({ upColor: UP, downColor: DN, wickUpColor: UP, wickDownColor: DN, borderVisible: false });
    cs.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.2 } });
    cs.setData(C0.map((c) => ({ time: c[0], open: c[1], high: c[2], low: c[3], close: c[4] })));
    const line = (opt, data) => { const s = ch.addLineSeries({ ...base, ...opt }); s.setData(data); return s; };
    if (on.vol) {
      const vs = ch.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
      ch.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
      vs.setData(C0.map((c) => ({ time: c[0], value: c[5], color: c[4] >= c[1] ? "rgba(8,153,129,.35)" : "rgba(242,54,69,.35)" })));
    }
    const snap = (t) => this.snapT(times, t);
    const M = [];
    if (on.swings) {
      if (d.cand) for (const [k, col] of [[1, "rgba(8,153,129,.4)"], [2, "rgba(242,54,69,.4)"]])
        line({ color: col, lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1.5 }, d.cand.map((r) => (r[k] == null ? { time: r[0] } : { time: r[0], value: r[k] })));
      for (const [k, t, p, ct] of d.swings || []) {
        const hi = k === "H", col = hi ? UP : DN;
        if (t >= t0) M.push({ time: t, position: hi ? "aboveBar" : "belowBar", color: col, shape: "square", size: 0.1 });
        M.push({ time: ct, position: hi ? "aboveBar" : "belowBar", color: col, shape: hi ? "arrowDown" : "arrowUp", size: 0.5 });
        const a = Math.max(t, t0);
        line({ color: col, lineWidth: 1 }, a === ct ? [{ time: ct, value: p }] : [{ time: snap(a), value: p }, { time: ct, value: p }]);
      }
    }
    if (on.prot && d.prot) {
      const pm = new Map(d.prot);
      line({ color: PURPLE, lineWidth: 1, lineStyle: 2, lineType: 1 }, times.map((t) => (pm.has(t) ? { time: t, value: pm.get(t) } : { time: t })));
    }
    // an option on its own chart: the index (left scale) against the strike, to see it go in and out of the money
    if (on.index && d.spot && d.spot.length) {
      ch.applyOptions({ leftPriceScale: { visible: true, borderColor: css("--line") } });
      const sl = ch.addLineSeries({ ...base, autoscaleInfoProvider: undefined, priceScaleId: "left", color: "#6b7280", lineWidth: 1, title: "NIFTY", lastValueVisible: true });
      sl.setData(d.spot.map(([t, v]) => ({ time: t, value: v })));
      const ks = ch.addLineSeries({ ...base, autoscaleInfoProvider: undefined, priceScaleId: "left", color: "#8e4ec6", lineWidth: 1, lineStyle: 2, title: `strike ${d.strike}`, lastValueVisible: true });
      ks.setData([{ time: t0, value: d.strike }, { time: tN, value: d.strike }]);
    }
    if (on.miles && d.milestones) for (const m of d.milestones) {
      if (m.ts == null || m.ts < t0 || m.ts > tN) continue;
      M.push({ time: snap(m.ts), position: "aboveBar", color: "#8e4ec6", shape: "square", size: 0.8, text: m.label });
    }
    if (on.olines && d.olines) for (const ln of d.olines)       // e.g. the option's SMA 200 (Strategy 32's filter)
      if (ln.pts.length) line({ color: "#f5a524", lineWidth: 2, title: ln.name, lastValueVisible: true }, ln.pts.map(([x, v]) => ({ time: x, value: v })));
    if (on.rainbow && d.lines) {
      const RB = ["#e5484d", "#f76b15", "#f5a524", "#e2c93a", "#7ac943", "#30a46c", "#12a594", "#0090ff", "#3e63dd", "#8e4ec6"];
      d.lines.forEach((ln, k, all) => { if (ln.length) line({ color: RB[all.length > 1 ? Math.round(9 * k / (all.length - 1)) : 0], lineWidth: 1 }, ln.map(([x, v]) => ({ time: x, value: v }))); });
    }
    if (on.avwap && d.pair) for (const a of d.pair) {
      const col = a.side === "H" ? ORANGE : BLUE;
      if (a.live.length) line({ color: col, lineWidth: 2 }, a.live.map(([x, v]) => ({ time: x, value: v })));
      if (a.back && a.back.length > 1) line({ color: col, lineWidth: 1, lineStyle: 1 }, a.back.map(([x, v]) => ({ time: x, value: v })));
    }
    if (on.struct && d.events) for (const [x, kind, dir] of d.events)
      M.push({ time: x, position: dir === "up" ? "aboveBar" : "belowBar", color: kind === "BOS" ? GREY : PURPLE, shape: "circle", size: kind === "BOS" ? 0.2 : 0.5, text: kind === "BOS" ? "" : "CHoCH" });
    const C = Object.fromEntries(d.cols.map((k, i) => [k, i]));
    let lo = Infinity, hi = -Infinity; for (const c of C0) { if (c[3] < lo) lo = c[3]; if (c[2] > hi) hi = c[2]; }
    const onScale = (v) => v != null && v >= lo - (hi - lo) * 0.5 && v <= hi + (hi - lo) * 0.5;
    const tag = (why, open) => (why === "stop_loss" ? "SL " : why === "trail_stop" ? "TRAIL " : why === "eod" ? "EOD " : /^target /.test(why || "") ? "T" + why.slice(7) + " "
      : why === "expiry" ? "EXPIRY " : why === "band_reclaim" || why === "band_exit" ? "BAND " : why === "next_choch" || why === "choch" ? "" : open ? "OPEN* " : "");
    const P = this.ctx.spec.position || {}, managed = P.exit === "position", seen = new Set();
    if (on.trades && !d.reference) for (const r of d.trades) {       // reference row: the trades are on the option panes
      const ets = tsOf(r[C.entry_time]), xts = tsOf(r[C.exit_time]), up = r[C.position] === "LONG", win = r[C.pts] > 0;
      const lbl = r[C.label] || r[C.position];
      const et = Math.max(ets, t0), xe = Math.min(xts, tN);
      if (ets >= t0 && ets <= tN) M.push({ time: snap(ets), position: up ? "belowBar" : "aboveBar", color: "#111111", shape: up ? "arrowUp" : "arrowDown", size: 1.5, text: lbl });
      if (xts <= tN && xts >= t0) M.push({ time: snap(xts), position: up ? "aboveBar" : "belowBar", color: win ? UP : DN, shape: "circle", size: 0.9, text: tag(r[C.exit_reason], r[C.open]) + num(r[C.pts], 1) });
      if (!own || et > xe) continue;
      line({ color: win ? UP : DN, lineWidth: 2, lineStyle: 2 }, snap(et) === snap(xe) ? [{ time: snap(et), value: r[C.entry_px] }] : [{ time: snap(et), value: r[C.entry_px] }, { time: snap(xe), value: r[C.exit_px] }]);
      if (onScale(r[C.sl])) line({ color: "#d32f2f", lineWidth: 1, lineStyle: 1 }, [{ time: snap(et), value: r[C.sl] }, { time: snap(xe), value: r[C.sl] }]);
      // managed exits: the position's stop, its targets and where the trail starts, labelled on the price axis (once per position)
      const key = ets + "|" + r[C.position] + "|" + r[C.instrument];
      if (on.rlevels && managed && onScale(r[C.sl]) && !seen.has(key)) {
        seen.add(key);
        const end = Math.min(tN, Math.max(...d.trades.filter((z) => tsOf(z[C.entry_time]) === ets && z[C.position] === r[C.position] && z[C.instrument] === r[C.instrument]).map((z) => tsOf(z[C.exit_time]))));
        const R = Math.abs(r[C.entry_px] - r[C.sl]), sg = up ? 1 : -1;
        const lv = [["SL", -1, "#d32f2f"], ...(P.scale_out || []).filter((x) => x.target_r != null).map((x) => [x.target_r + "R", x.target_r, UP]),
                    ...(P.trail ? [[P.trail.start_r + "R trail", P.trail.start_r, BLUE]] : [])];
        if (R && et <= end) for (const [name, k, col] of lv) {
          const y = +(r[C.entry_px] + sg * k * R).toFixed(2);
          line({ color: col, lineWidth: 1, lineStyle: k < 0 ? 0 : 2, title: name, lastValueVisible: true }, snap(et) === snap(end) ? [{ time: snap(et), value: y }] : [{ time: snap(et), value: y }, { time: snap(end), value: y }]);
        }
      }
    }
    // FZ gate at each Foundation SETUP: T take (blue) · W watch (grey) · B block (red) · R re-enter (purple)
    if (on.trades && main && this.ctx.result.fz && d.fz) {
      const Lg = this.ctx.result.fz.ledger, ix = (k) => Lg.cols.indexOf(k);
      const G = { TAKE: ["T", BLUE], WATCH: ["W", GREY], BLOCK: ["B", DN], REENTER: ["R", PURPLE] };
      for (const r of Lg.rows) {
        const g = G[r[ix("gate")]], x = tsOf(r[ix("time")]);
        if (g && x >= t0 && x <= tN) M.push({ time: snap(x), position: r[ix("dir")] === "up" ? "belowBar" : "aboveBar", color: g[1], shape: "circle", size: 0.3, text: g[0] });
        const f = r[ix("fill_time")];
        if (r[ix("outcome_gate")] === "REENTER" && f && f !== r[ix("time")]) { const y = tsOf(f); if (y >= t0 && y <= tN) M.push({ time: snap(y), position: r[ix("dir")] === "up" ? "belowBar" : "aboveBar", color: PURPLE, shape: "circle", size: 0.3, text: "R" }); }
      }
    }
    const placed = M.filter((m) => m.time != null && m.time >= t0 && m.time <= tN);
    placed.sort((a, b) => a.time - b.time);
    cs.setMarkers(placed);
    // crosshair readout: OHLCV and, for FZ, the zone card of that bar
    const Z = d.fz ? new Map(d.fz.Z.map((z) => [z[0], z])) : null;
    ch.subscribeCrosshairMove((p) => {
      const box = $(".ch-read", this.root);
      if (!p || !p.time) { box.textContent = ""; return; }
      const c = C0[times.indexOf(p.time)]; if (!c) return;
      let s = `${new Date(p.time * 1000).toISOString().slice(5, 16).replace("T", " ")}  O ${c[1]}  H ${c[2]}  L ${c[3]}  C ${c[4]}  V ${Math.round(c[5]).toLocaleString("en-IN")}`;
      if (Z && Z.has(p.time)) {
        const z = Z.get(p.time), k = Object.fromEntries(d.fz.Z_COLS.map((n, i) => [n, z[i]]));
        const zone = d.fz.ZONES.find((x) => x[0] === k.zone_id);
        s += `  ·  zone ${k.zone_id ?? "–"}${zone ? ` [${zone[2]}–${zone[3]}]` : ""} visit ${k.visit_n ?? "–"} bars ${k.this_bars ?? "–"}` +
             (k.first_vol && k.this_vol && k.this_bars && k.first_bars ? ` vol× ${(k.this_vol / k.this_bars / (k.first_vol / k.first_bars)).toFixed(2)}` : "") +
             ` read ${d.fz.READS[k.read] ?? "–"}${k.left_id ? ` · LEAVE from ${k.left_id}` : ""}`;
      }
      box.textContent = s;
    });
    requestAnimationFrame(() => {
      if (main && this.keepRange) {                // an extension: keep the view the reader had
        const r = this.keepRange; this.keepRange = null;
        try { ch.timeScale().setVisibleRange(r); } catch (e) { ch.timeScale().fitContent(); }
      } else if (this.focusTime && main) {
        const t = this.focusTime; this.focusTime = null;
        try { ch.timeScale().setVisibleRange({ from: t - 3600, to: t + 3600 }); } catch (e) { ch.timeScale().fitContent(); }
      } else ch.timeScale().fitContent();
    });
    return ch;
  }

  snapT(times, t) {
    // the last candle at or before t (the chart's own bars), else the first one
    let lo = 0, hi = times.length - 1;
    if (t <= times[0]) return times[0];
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (times[m] <= t) lo = m; else hi = m - 1; }
    return times[lo];
  }

  legend(d) {
    const n = d.trades.length, net = d.trades.reduce((a, r) => a + r[d.cols.indexOf("net")], 0);
    $(".ch-legend", this.root).innerHTML =
      (d.reference ? `<b>Futures for reference only: the signals are read on each option's own chart (CE / PE below).</b> ` : "") +
      `${esc(this.day)}${this.to && this.to !== this.day ? " → " + esc(this.to) : ""} · ${d.sessions} session${d.sessions > 1 ? "s" : ""} · ` +
      `${d.candles.length} candles · ${n} trade${n === 1 ? "" : "s"} <span class="${net > 0 ? "pos" : net < 0 ? "neg" : ""}">${inr(net)}</span>` +
      ` · arrow = entry, dot = exit (reason, pts), dashed = path, dotted red = stop` + (d.fz ? " · purple / blue boxes = FZ bands (A / B), T W B R = gate" : "") +
      (d.pair && d.pair.length ? " · orange / blue = AVWAP from SH / SL (dotted: back to the anchor)" : "") +
      (this.hooks.static ? "" : " · + earlier / + later add sessions") + " · mouse wheel zooms, drag pans · drag the bottom edge to resize";
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
