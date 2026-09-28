<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strategy dashboard</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--muted:#6b7280;--line:#e6e8ec;--up:#089981;--dn:#f23645;--acc:#2962ff;--pur:#7b1fa2;--amb:#b45309;--rad:10px}
/* page colour tokens (money, selection, pills, warnings, heatmap). --up --dn --acc --pur stay the chart's own colours */
:root{--pnl-up:#0a7d62;--pnl-dn:#c0392b;--sel:#2954d9;--sel-bg:#eef2ff;--hover:#f5f7fb;--cur-bg:#f8f9fc;--link:#2954d9;--subtle:#fafbfc;--long-bg:#eef1f5;--long-fg:#1f2937;--short-bg:#f3f4f6;--short-fg:#4b5563;--warn-fg:#a16207;--warn-star:#a16207;--warn-bg:#fef7e6;--warn-line:#f1d9a6;--warn-ink:#7a4f05;--h0:#eceef1;--hp1:#d5eee4;--hp2:#9dd4bf;--hp3:#4fae8d;--hp4:#0a7d62;--hn1:#f6dad7;--hn2:#eba7a0;--hn3:#d9695e;--hn4:#c0392b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1600px;margin:0 auto;padding:12px 16px 40px}
h1{font-size:16px;font-weight:600;margin:0}.sub{color:var(--muted);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--rad)}
.seg{display:inline-flex;background:#eceef2;border-radius:7px;padding:2px}
.seg button{border:0;background:transparent;padding:3px 10px;border-radius:5px;font:12px system-ui;color:var(--muted);cursor:pointer;white-space:nowrap}
.seg button.on{background:#fff;color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.08)}.seg.sm button{padding:1px 8px;font-size:11px}
.pipe{color:#c3c7cf;margin:0 8px}
#board{margin:10px 0}
.brow{display:flex;align-items:baseline;flex-wrap:wrap;padding:8px 12px;border-bottom:1px solid var(--line);cursor:pointer;font-variant-numeric:tabular-nums}
.brow:last-child{border-bottom:0}.brow:hover{background:#f7f9ff}.brow b{font-size:13px}
.bhead{display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid var(--line)}
.bhead input{font:12px system-ui;border:1px solid var(--line);border-radius:6px;padding:3px 8px;width:220px}
.sline{display:flex;align-items:center;flex-wrap:wrap;padding:8px 12px}
.link{color:var(--link);cursor:pointer;white-space:nowrap}.link:hover{text-decoration:underline}
.badge{background:var(--warn-bg);color:var(--warn-fg);border-radius:999px;padding:1px 9px;font-size:11px;font-weight:600;margin-left:8px}
.menu{position:relative;display:inline-block}
.pop{position:absolute;top:22px;left:0;z-index:20;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.12);min-width:320px;padding:4px;display:none}
.pop.on{display:block}.pop .it{padding:6px 10px;border-radius:6px;cursor:pointer}.pop .it:hover{background:var(--hover)}.pop .it.on{background:var(--sel-bg)}
.pop .it.off{color:#a0a4ab;cursor:not-allowed}.pop .it small{display:block;color:var(--muted);font-size:11px;white-space:normal}.pop .sep{border-top:1px solid var(--line);margin:4px 0}
.pop code{display:block;background:#f6f7f9;border-radius:6px;padding:6px 8px;margin:4px 0;font-size:11px;white-space:pre-wrap}
#rules{display:none;padding:8px 12px 10px;border-top:1px solid var(--line);font-size:12px}#rules.on{display:block}
.typebar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0 8px}
.optset{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}
.optset select{font:12px system-ui;border:1px solid var(--line);border-radius:6px;padding:2px 6px}
.schemes{display:flex;gap:6px;flex-wrap:wrap}
.pillb{display:inline-flex;align-items:baseline;gap:6px;border:1px solid var(--line);background:#fff;border-radius:999px;padding:3px 11px;cursor:pointer;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.pillb b{font-weight:600}.pillb:hover{border-color:#c9ced6}.pillb.on{border-color:var(--acc);background:#eef2ff;color:var(--ink)}
.cal{margin:8px 0 10px;padding:8px 12px;display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap}
.hm{overflow-x:auto;max-width:100%}.hmhead{display:flex;justify-content:space-between;gap:12px;margin-bottom:4px;font-size:12px}
.hmgrid{display:grid;grid-auto-flow:column;grid-template-rows:repeat(5,12px);grid-auto-columns:12px;gap:3px}
.hmmon{display:grid;grid-auto-flow:column;grid-auto-columns:12px;gap:3px;font-size:10px;color:var(--muted);height:13px}
.hmmon span{overflow:visible;white-space:nowrap}
.hc{width:12px;height:12px;border-radius:2px;background:var(--h0);cursor:pointer}.hc.x{background:transparent;cursor:default}.hc.z{background:var(--h0)}
.hc:hover{outline:1.5px solid #16181d}.hc.sel{outline:1.5px solid var(--sel)}
.hmlegend{display:flex;align-items:center;gap:3px;font-size:10px;color:var(--muted);margin-top:4px}.hmlegend i{width:10px;height:10px;border-radius:2px;display:inline-block}
.hmstats{display:grid;grid-template-columns:repeat(3,auto);gap:4px 18px;font-size:12px;font-variant-numeric:tabular-nums;align-content:start}
.hmstats div{color:var(--muted)}.hmstats b{display:block;color:var(--ink);font-size:13px}
.warn{color:var(--warn-star);font-weight:700;cursor:help;margin-left:1px}
.chartcard{display:flex;flex-direction:column;height:max(460px,calc(100vh - 60px));overflow:hidden}
.ctop{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px 10px;border-bottom:1px solid var(--line)}
.crumb{font-size:13px;font-weight:600}.crumb span{color:var(--muted);font-weight:400;margin:0 4px}
.cbody{position:relative;flex:1;min-height:0}#chart{position:absolute;inset:0}
.optwrap{flex:0 0 46%;display:flex;flex-direction:column;border-top:2px solid var(--line);min-height:0}
.optwrap .ctop{padding:4px 10px}.cbody2{position:relative;flex:1;min-height:0}#chart2{position:absolute;inset:0}
#optNone{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
.ohlc{font:12px ui-monospace,Consolas,monospace;color:var(--muted);white-space:nowrap}.ohlc b{color:var(--ink);font-weight:500}
.nav{display:inline-flex;align-items:center;gap:4px}
.nav button,.nav select{font:12px system-ui;border:1px solid var(--line);background:#fff;border-radius:6px;padding:3px 8px;cursor:pointer;color:var(--ink)}
.layers{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:2px 9px;font-size:11px;color:var(--muted);cursor:pointer;user-select:none}
.chip.on{color:var(--ink);border-color:#c9ced6}.chip i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}
.loading{position:absolute;inset:0;display:none;align-items:center;justify-content:center;background:rgba(255,255,255,.7);z-index:5;color:var(--muted)}
.bq{min-width:360px;max-width:440px;font-size:12px}.bq h5{margin:8px 0 4px;font-size:12px}.bq h5:first-child{margin-top:0}
.bq .row{display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin:3px 0}.bq input{font:inherit;padding:2px 4px;border:1px solid var(--line);border-radius:4px}
.bq .qb{font:inherit;padding:2px 8px;border:1px solid var(--line);border-radius:4px;background:transparent;cursor:pointer;color:inherit}
.bq .qb:hover{border-color:var(--link);color:var(--link)}.bq .qb[disabled]{opacity:.45;cursor:default}.bq .qb.warn{border-style:dashed}
.bq pre{white-space:pre-wrap;max-height:140px;overflow:auto;margin:4px 0 0;font-size:11px;background:var(--sel);padding:4px;border-radius:4px}
.apiOnly{display:none}body.api .apiOnly{display:block}body.api .noApi{display:none}
#jobBadge{font-size:12px;color:var(--link)}#jobBadge.failed{color:var(--warn-fg)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.kpi{padding:10px 12px}.kpi .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.kpi .v{font-size:20px;font-weight:600;margin-top:2px;font-variant-numeric:tabular-nums}.kpi .s{color:var(--muted);font-size:11px}
.tabs{position:sticky;top:0;z-index:4;display:flex;gap:2px;background:var(--bg);padding-top:4px;border-bottom:1px solid var(--line);overflow-x:auto}
.tab{border:0;background:transparent;padding:8px 12px;font:13px system-ui;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
.tab.on{color:var(--ink);border-bottom-color:var(--sel);font-weight:600}
.panel{display:none;padding:12px 0}.panel.on{display:block}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600;text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);background:var(--subtle);position:sticky;top:0}
td{padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
tbody tr.z{cursor:pointer}tbody tr.z:hover{background:var(--hover)}
.num{text-align:right}.pos{color:var(--pnl-up)}.neg{color:var(--pnl-dn)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600}
.pill.long{background:var(--long-bg);color:var(--long-fg)}.pill.short{background:var(--short-bg);color:var(--short-fg)}.pill.open{background:var(--warn-bg);color:var(--warn-ink)}.pill.grey{background:#eef0f3;color:#555}
.scroll{max-height:70vh;overflow:auto}.hint{color:var(--muted);font-size:12px;margin:0 0 8px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px}
.mt{padding:10px 12px}.mt h3{margin:0 0 6px;font-size:13px}.mt table td{padding:5px 8px}.mt table td:first-child{color:var(--muted)}
.note{background:var(--warn-bg);border:1px solid var(--warn-line);color:var(--warn-ink);border-radius:8px;padding:8px 10px;font-size:12px;margin-bottom:10px}
.chartbox{position:relative;height:320px}.chartbox>div{position:absolute;inset:0}
.rules{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
.rules .card{padding:12px 14px}.rules h3{margin:0 0 6px;font-size:13px}.rules ul{margin:0;padding-left:18px}.rules li{margin:3px 0}
.sw{display:inline-block;width:18px;text-align:center;font-weight:700}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:0}dt{color:var(--muted)}dd{margin:0}
svg text{font:10px system-ui;fill:#6b7280}
/* header: one control bar, then one column per type */
.head{margin:10px 0 8px}
.hbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:8px 12px;border-bottom:1px solid var(--line)}
.hbar .brand{font-weight:600;font-size:14px;margin-right:2px}
.hbar .lbl,.hbar .dates{color:var(--muted);font-size:12px}
.hbar .sp{flex:1}
.seg button small{color:var(--muted);margin-left:5px;font-size:10.5px}.seg button.on small{color:var(--muted)}
.seg button.off{color:#c3c7cf;cursor:not-allowed}
.optrow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--muted);padding:6px 12px;border-bottom:1px solid var(--line);border-left:1px solid var(--line);background:var(--subtle)}
.optrow b{color:var(--ink);font-weight:600}.optrow select{font:12px system-ui;border:1px solid var(--line);border-radius:6px;padding:2px 6px}
.optpad{border-bottom:1px solid var(--line)}
.cols{display:grid}
.col{padding:10px 12px 10px;border-left:1px solid var(--line);min-width:0}.col:first-of-type{border-left:0}
.cols>.col:nth-child(1),.cols>.optpad+.optrow+.col,.cols>.optrow+.col{border-left:0}
.col.cur{background:var(--cur-bg)}
.col h4{margin:0;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);cursor:pointer;display:inline-block}
.col.cur h4{color:var(--ink)}.col h4:hover{color:var(--sel)}
.cov{font-size:11px;color:var(--muted);margin:1px 0 6px;min-height:16px}.cov.thin{color:var(--warn-fg)}
.srow{display:grid;grid-template-columns:1fr auto 92px;gap:10px;align-items:baseline;padding:4px 8px;margin:0 -8px;border-radius:6px;cursor:pointer;font-variant-numeric:tabular-nums}
.srow:hover{background:var(--hover)}.srow.on{background:var(--sel-bg);box-shadow:inset 3px 0 0 var(--sel)}
.srow .n{font-weight:600;font-size:14px;text-align:right}.srow .m{color:var(--muted);font-size:11px;text-align:right}
.sides{font-size:11.5px;color:var(--muted);padding:5px 0 0}.sides .sd{cursor:pointer;padding-bottom:1px}.sides .sd:hover{color:var(--ink)}
.sides .sd.on{color:var(--ink);border-bottom:2px solid var(--sel)}.sides b{font-weight:600}
#rules{border-top:0;border-bottom:1px solid var(--line)}
/* daily P&L: heatmap left, one aligned row of day stats right */
.cal{align-items:center;gap:28px}
.hmstats{grid-template-columns:repeat(5,auto);gap:4px 28px;align-content:center}
.hmstats b{font-size:14px}.hmstats small{display:block;color:var(--muted);font-size:11px}
.hmmon{position:relative;display:block;height:14px}.hmmon span{position:absolute;top:0}
</style>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
</head><body><div class="wrap">
<div id="head" class="card head"></div>
<div class="card cal" id="cal"></div>

<div class="card chartcard">
  <div class="ctop">
    <span class="crumb" id="crumb"></span>
    <span class="seg" id="viewSeg" title="which chart"></span>
    <div class="nav" id="dayNav"><button id="prev" title="previous">‹</button><select id="series" title="session / contract"></select><button id="next" title="next">›</button><button id="all" title="load every session of this backtest into one chart">Full period</button><button id="snapPng" title="save the chart as it is shown, as a PNG image">PNG</button><button id="snapJpg" title="save the chart as it is shown, as a JPEG image (smaller file)">JPG</button></div>
    <div class="ohlc" id="ohlc"></div>
    <div class="layers" id="layers"></div>
  </div>
  <div class="cbody"><div id="chart"></div><div class="loading" id="loading">Loading…</div></div>
  <div class="optwrap" id="optWrap" style="display:none">
    <div class="ctop"><span class="crumb" id="optLbl">Option</span><span class="seg sm" id="optSeg"></span><div class="ohlc" id="ohlc2"></div></div>
    <div class="cbody2"><div id="chart2"></div><div class="hint" id="optNone" style="display:none">No option position in this session.</div></div>
  </div>
</div>

<div class="kpis" id="kpis"></div>
<div class="tabs" id="tabs">
  <button class="tab on" data-p="trades">Trades</button><button class="tab" data-p="perf">Performance</button>
  <button class="tab" data-p="equity">Cumulative P&amp;L</button><button class="tab" data-p="dd">Drawdowns</button>
  <button class="tab" data-p="dist">Distribution</button><button class="tab" data-p="mc">Monte Carlo</button>
  <button class="tab" data-p="robust">Robustness</button><button class="tab" data-p="bdown">Breakdown</button>
  <button class="tab" data-p="daily">Daily P&amp;L</button><button class="tab" data-p="signals">Signals</button><button class="tab" data-p="fz">Zone gate</button>
  <button class="tab" data-p="config">Config</button><button class="tab" data-p="rules">Rules</button>
</div>
<div class="panel on" id="p-trades"><p class="hint">Click a trade to open it on the chart. Hover a charges cell for the breakdown.</p><div id="opennote"></div><div class="card scroll"><table id="ttrades"></table></div><div id="skipped" class="hint" style="margin-top:8px"></div></div>
<div class="panel" id="p-perf"></div>
<div class="panel" id="p-equity"><p class="hint" id="eqhint"></p><div class="card"><div class="chartbox" style="height:300px"><div id="eq"></div></div><div class="chartbox" style="height:140px;border-top:1px solid var(--line)"><div id="uw"></div></div></div></div>
<div class="panel" id="p-dd"></div>
<div class="panel" id="p-dist"></div>
<div class="panel" id="p-mc"></div>
<div class="panel" id="p-robust"></div>
<div class="panel" id="p-bdown"></div>
<div class="panel" id="p-daily"><p class="hint">By exit day. Click a day to open it on the chart.</p><div class="card scroll"><table id="tdaily"></table></div></div>
<div class="panel" id="p-signals"><p class="hint" id="sighint"></p><div class="card scroll"><table id="tsignals"></table></div></div>
<div class="panel" id="p-fz"></div>
<div class="panel" id="p-config"><div class="card" style="padding:12px 14px"><dl id="cfg"></dl></div></div>
<div class="panel" id="p-rules"><div class="rules">
  <div class="card"><h3>Strategy, backtest, timeframe</h3><ul>
    <li><b>Strategy</b> — the engine and its rules. Each strategy runs only the backtests defined for it; a backtest the data cannot cover is refused with the reason.</li>
    <li><b>Backtest period</b> — its own run over exactly its dates (plus warm-up). Presets count back from the latest data date; Design period = where the rules were built; Unseen test = dates the rules never saw.</li>
    <li><b>Timeframe</b> — the design timeframe by default; the same rules can be run on other candles (amber badge).</li></ul></div>
  <div class="card"><h3>Types and schemes</h3><ul>
    <li><b>Futures</b> — long on future long, short on future short. Schemes: long + short (total), long, short.</li>
    <li><b>Options (via futures)</b> — the futures' signals in options, 1 lot per signal. Long: CE on future long, PE on future short. Short: PE on future long, CE on future short. Long + short · CE / · PE: that option long on one signal, short on the other.</li>
    <li><b>Options (standalone)</b> — the engine on each option's own chart. Long: bullish setups; short: bearish setups; long + short · CE / · PE: both directions on that chart.</li>
    <li>Expiry (weekly / monthly) and strike apply to both option types and are set on the options bar.</li></ul></div>
  <div class="card"><h3>Chart</h3><ul>
    <li><span class="sw" style="color:var(--up)">■</span>SH / <span style="color:var(--dn)">■</span> SL; ▼ / ▲ confirming candle. Faded dots: unconfirmed candidate.</li>
    <li><span class="sw" style="color:var(--pur)">┅</span>Protected level · <span style="color:var(--pur)">●</span> CHoCH · <span style="color:#9e9e9e">●</span> BOS. Breaks by touch.</li>
    <li><span class="sw" style="color:#ff6d00">━</span>AVWAP from previous SH, <span style="color:var(--acc)">━</span> from previous SL, started at each CHoCH.</li></ul></div>
  <div class="card"><h3>Fills, costs, statistics</h3><ul>
    <li>Entry at the SETUP candle close. Stop: worse of candle open and stop; on a session's first candle, that candle's close. Else exit at the next CHoCH close. A position open at the backtest's end is valued at its last candle (*).</li>
    <li>Slippage per side: futures 5 pts, options 0.5 pt. Charges per the charge schedule. Short option = sell at entry, buy at exit.</li>
    <li>Capital per lot (for returns, Calmar, risk of ruin): futures and short options use the margins in Config; long-only options use the average premium paid.</li>
    <li>Monte Carlo: 2,000 simulations with a fixed seed. * = incomplete data (positions skipped for missing option candles).</li></ul></div>
  <div class="card"><h3>Foundation-Zone (Strategies 5–8)</h3><ul>
    <li><b>Bands</b> — <span class="sw" style="color:var(--pur)">▮</span>A: born when a swing becomes the protected level · <span style="color:var(--acc)">▮</span> B: born when the last <code>cluster_bars</code> closes sit within <code>cluster_width</code>. ± <code>band_half_width</code> around the mid; a new band overlapping one enough merges into it; none is ever deleted (Strategies 5, 6). <b>Rooms</b> (Strategies 7, 8): born only from a sit, a sit inside a live room (or overlapping a room visited this session) is a visit of it, live rooms never overlap, a room with no close inside for <code>room_max_age_sessions</code> sessions is retired; named <code>&lt;letter&gt; &lt;mm-dd hh:mm&gt;</code>. Memory starts at the file's first session, so every window is a slice of one run.</li>
    <li><b>Card</b> (per bar, as-of, on the crosshair) — the ref band whose visit is live, visit n, this and first visit bars and volume, and the read. A visit ends only on <code>leave_closes</code> closes in a row outside on one side. Reads in order: LEAVE of the band just left (for <code>leave_ttl_bars</code>) → HUNT (out and back in: one close on 1m, a deep wick on 5m) → REJECT (wick at an edge, close back toward the mid) → FIRST_PRINT (visit 1) / ACCEPTED (lived <code>accept_bars</code>, volume held) / THIN / RECYCLE → PENDING (first close outside) → NEW.</li>
    <li><b>Gate</b> at each Foundation SETUP, first match: <span class="sw" style="color:var(--dn)">B</span>BLOCK (in a position, open time from <code>no_entry_from</code>, an opening bar piercing a band last visited on an earlier day, a SETUP in the pierce direction of a HUNT within <code>fade_block_bars</code>, NEW ground) · <span class="sw" style="color:var(--acc)">T</span>TAKE (a LEAVE its way, a FIRST_PRINT in the entry direction, an ACCEPTED defend after a HUNT or REJECT at the opposite edge) · <span class="sw" style="color:#9e9e9e">W</span>WATCH on the band holding the close (on the band just left when the SETUP is its first close outside).</li>
    <li><span class="sw" style="color:var(--pur)">R</span><b>REENTER</b> — a watch arms on a close beyond its band and re-enters on the bar where <code>leave_closes</code> closes are out, none came back inside or across the mid, far-side volume is at least the sit's (skipped when NA) and a Foundation SETUP points the same way on that bar or the one before; fill at that bar's close. A close back inside breaks the run and the next close beyond arms the watch again. A LEAVE TAKE of the band a watch waits on, in its direction, is that watch's REENTER; a FIRST_PRINT or defend TAKE stays a TAKE. Cancelled at the next session, by an opposite TAKE or LEAVE, or after <code>cancel_inside_bars</code> closes back inside.</li>
    <li><b>Exits</b> — TAKE is Foundation's own position. REENTER takes Foundation's stop at the fill bar and exits on the stop, then <b>band reclaim</b> (a close back past the band's mid, BAND on the chart), then the next CHoCH.</li>
    <li>Volume NA = not the front month or zero volume: R4, the HUNT burst and THIN are skipped and ACCEPTED is time-only. Clocks use the bar's open time; durations are bars; a visit carries across the overnight gap. Values and sources: Config tab; what the gate did: Zone gate tab.</li></ul></div>
</div></div>
</div>
<script>
/*DATA*/
const fmt=(v,d=1)=>v==null||isNaN(v)?'—':(v>0?'+':'')+(+v).toFixed(d);
const inr=v=>v==null||isNaN(v)?'—':(v<0?'−₹':'₹')+Math.abs(Math.round(v)).toLocaleString('en-IN');
const inrk=v=>v==null?'—':(v<0?'−₹':'₹')+(Math.abs(v)>=1e5?(Math.abs(v)/1e5).toFixed(2)+'L':Math.abs(v)>=1e3?(Math.abs(v)/1e3).toFixed(1)+'k':Math.round(Math.abs(v)));
const pct=v=>v==null||isNaN(v)?'—':(v*100).toFixed(1)+'%';
const iso=t=>new Date(t*1000).toISOString();
const $=id=>document.getElementById(id);
const cl=v=>v>0?'pos':v<0?'neg':'';
const sum=(a,f)=>a.reduce((s,t)=>s+f(t),0);
const EXP={W:'Weekly',M:'Monthly'},ck=k=>k.split('-');
const TYPE={FUT:'Futures',OPT_FUT_SIGNAL:'Options (via futures)',OPT_NATIVE:'Options (standalone)'};
const ORDER=['FUT','OPT_FUT_SIGNAL','OPT_NATIVE'];
const SCH={BOTH:'Long + short',LONG:'Long',SHORT:'Short',CE:'Long + short · CE',PE:'Long + short · PE'};
const SCHEMES=m=>m.variant==='FUT'?['BOTH','LONG','SHORT']:['BOTH','LONG','SHORT','CE','PE'];
const SDESC=(m,s)=>m.variant==='FUT'?{BOTH:'long and short futures (total)',LONG:'long futures',SHORT:'short futures'}[s]
  :m.variant==='OPT_FUT_SIGNAL'?{BOTH:'both legs of every signal: long one option, short the other',LONG:'CE on future long, PE on future short',SHORT:'PE on future long, CE on future short',CE:'CE: long on future long, short on future short',PE:'PE: short on future long, long on future short'}[s]
  :{BOTH:'bullish and bearish setups on the CE and PE charts',LONG:'bullish setups, CE and PE charts',SHORT:'bearish setups, CE and PE charts',CE:'CE chart, both directions',PE:'PE chart, both directions'}[s];
const inSch=(t,s)=>s==='BOTH'||(s==='LONG'||s==='SHORT'?t.pos===s:t.otype===s);
const on={trades:true,avwap:true,prot:true,struct:true,swings:true,vol:true,zones:true,rlevels:true};
const cache={};let ch=null,eqch=null,uwch=null,mcch=null,D=null,cur=null,curChoice=null;
const load_=k=>{try{return JSON.parse(localStorage.getItem(k)||'null');}catch(e){return null;}};
const save_=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v));}catch(e){}};
const fams=[...new Set(INDEX.map(m=>m.family))];
const rowsOf=f=>INDEX.filter(m=>m.family===f).sort((a,b)=>ORDER.indexOf(a.variant)-ORDER.indexOf(b.variant));
const runsOf=f=>rowsOf(f)[0].runs;
const designTf=f=>rowsOf(f)[0].timeframe;
let ST=Object.assign({fam:fams[0],board:true},load_('st2')||{});
const SEL=load_('sel2')||{};   // per strategy: run, type, scheme per type, option expiry and strike
fams.forEach(f=>{const rs=runsOf(f),ok=Object.entries(rs).filter(([k,r])=>r.status==='ok'),o=rowsOf(f).find(m=>m.variant!=='FUT');
  const def=(ok.find(([k,r])=>r.is_default&&r.design)||ok.find(([k,r])=>r.design)||ok[0]||[null])[0];
  SEL[f]=Object.assign({run:def,type:rowsOf(f)[0].code,scheme:{},exp:'W',strike:o?o.strike_default:'ATR2'},SEL[f]||{});
  if(!rs[SEL[f].run]||rs[SEL[f].run].status!=='ok')SEL[f].run=def;});
const saveAll=()=>{save_('st2',ST);save_('sel2',SEL);};
const S=()=>SEL[ST.fam];
const runOf=m=>m.runs[SEL[m.family].run];
const choiceOf=m=>{if(m.variant==='FUT')return '-';const e=SEL[m.family].exp,r=m.runs[SEL[m.family].run];
  return m.variant==='OPT_NATIVE'&&r&&r.choices[`${e}-SCAN`]?`${e}-SCAN`:`${e}-${SEL[m.family].strike}`;};
const HOLD0=m=>m.position&&m.position.square_off?`intraday ${m.position.square_off}`:'positional';
const HOLD=x=>x.holding||'';
const SCANTXT=m=>{const n=m.native_scan;return n?`rescans ${n.choices.join(' · ')} every ${n.every_minutes} min from the index${n.one_per_side?' · one position per side':''}`:'';};
const statOf=(m,sch)=>{const r=runOf(m);const s=r&&r.choices[choiceOf(m)];if(!s)return null;return sch==='BOTH'?s:({LONG:s.long,SHORT:s.short,CE:s.ce,PE:s.pe})[sch]||null;};
const cov=m=>{const r=runOf(m),s=r&&r.choices[choiceOf(m)];if(!s||!s.skipped)return null;return {text:`Incomplete: ${s.trades} of ${s.trades+s.skipped} positions priced; ${s.skipped} skipped for missing option data.`};};
const star=c=>c?`<span class="warn" title="${c.text}">*</span>`:'';
const schemeOf=m=>{const s=SEL[m.family].scheme[m.code];return s&&SCHEMES(m).includes(s)?s:'BOTH';};
const fmtD=d=>d?new Date(d+'T00:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'short',timeZone:'UTC'}):'';
const rng=r=>r&&r.date_from?`${fmtD(r.date_from)} – ${fmtD(r.date_to)} ${r.date_to.slice(0,4)}`:'';

// ================= header: one control bar (strategy · backtest · candles), then one column per type
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
const SNAME=m=>m.strategy_name||m.name.split(' · ').slice(0,2).join(' · ');
const SABOUT=m=>m.strategy_description||m.description||'';
const pctw=x=>x&&x.trades?Math.round(100*x.wins/x.trades)+'%':'—';
function renderHeader(){
  const f=ST.fam,rs=rowsOf(f),m0=rs[0],runs=runsOf(f),r=runs[S().run],dtf=designTf(f);
  // strategy: buttons while they fit, a list beyond that
  const stratCtl=fams.length>6
    ?`<select id="stratSel">${fams.map(x=>`<option value="${x}" ${x===f?'selected':''}>${esc(SNAME(rowsOf(x)[0]))} · ${TFS[designTf(x)]}</option>`).join('')}</select>`
    :`<span class="seg" id="stratSeg">${fams.map(x=>`<button data-f="${x}" class="${x===f?'on':''}" title="${esc(SABOUT(rowsOf(x)[0]))}">${esc(SNAME(rowsOf(x)[0]))}<small>${TFS[designTf(x)]}</small></button>`).join('')}</span>`;
  // backtest: one tab per label on the design timeframe; refused ones stay visible, disabled, with the reason
  const tabs=[],seen=new Set();
  for(const [k,x] of Object.entries(runs)){if(!x.design||seen.has(x.label))continue;seen.add(x.label);tabs.push([k,x]);}
  const btCtl=`<span class="seg" id="btSeg">${tabs.map(([k,x])=>`<button data-l="${esc(x.label)}" class="${x.label===r.label?'on':''} ${x.status!=='ok'?'off':''}" title="${esc(x.status==='ok'?rng(x)+(x.notes?' · '+x.notes:''):'not available: '+x.reason)}">${esc(x.label)}</button>`).join('')}</span>`;
  // candles: only when this backtest also exists on another timeframe
  const alts=Object.entries(runs).filter(([k,x])=>x.label===r.label&&x.kind===r.kind&&x.status==='ok').sort((a,b)=>b[1].design-a[1].design);
  const tfCtl=alts.length>1?`<span class="lbl">Candles</span><span class="seg sm" id="tfSeg">${alts.map(([k,x])=>`<button data-k="${k}" class="${k===S().run?'on':''}">${TFS[x.timeframe]}${x.underlying==='INDEX'?' · index':' · futures'}${HOLD(x)?' · '+HOLD(x).replace(/^intraday .*/,'intraday'):''}${x.design?' · design':''}</button>`).join('')}</span>`:'';
  const addCmds=`<small class="sub">Run in research/strategy_lab, then reload:</small><code>python lab.py backtest ${f} 1Y\npython lab.py backtest ${f} YTD\npython lab.py backtest ${f} 2026-07-10 2026-08-10 --label "July"\npython lab.py backtest ${f} ${r.kind==='all'?'all':r.kind==='preset'?r.preset:r.date_from+' '+r.date_to} --underlying ${(r.underlying||'FUT')==='INDEX'?'FUT':'INDEX'} --label "${r.label}"\npython lab.py backtest ${f} ${r.kind==='all'?'all':r.kind==='preset'?r.preset:r.date_from+' '+r.date_to} --square-off ${/^intraday/.test(HOLD(r)||HOLD0(m0))?'none':'15:25'} --label "${r.label}"\n${['minute','3minute','5minute','15minute','30minute'].filter(t=>!alts.some(([k,x])=>x.timeframe===t)).map(t=>`python lab.py backtest ${f} ${r.kind==='all'?'all':r.kind==='preset'?r.preset:r.date_from+' '+r.date_to} --tf ${t} --label "${r.label}"`).join('\n')}</code><small class="sub">Data covers ${fmtD(DATA_RANGE[0])} ${DATA_RANGE[0].slice(0,4)} – ${fmtD(DATA_RANGE[1])} ${DATA_RANGE[1].slice(0,4)}; a backtest the data cannot cover is refused.</small>`;
  const rules=`<div style="margin-bottom:4px">${esc(SABOUT(m0))}</div><b>Rules</b> — swings (Pine port) → protected level (unbroken swing beyond the trend AVWAP) → CHoCH by ${m0.choch_mode??m0.break_mode}, BOS by ${m0.break_mode} → AVWAP pair from the previous SH and SL at each CHoCH → SETUP (both AVWAPs sloping with the CHoCH and a close beyond the CHoCH candle) → ${m0.position&&m0.position.exit==='position'?`managed exit: ${m0.position.lots} lots, stop ${m0.position.stop.futures_pts} pts (futures) / ${m0.position.stop.option_pct}% of premium (options) = 1R`+(m0.position.scale_out||[]).map((x,i)=>`, lot ${i+1} out at ${x.target_r!=null?x.target_r+'R':'+'+x.target_pts}`).join('')+(m0.position.trail?`, the rest trails from ${m0.position.trail.start_r}R (${m0.position.trail.lag_r}R behind the best R reached)`:'')+'; no CHoCH exit.':`exit on stop loss (${m0.sl_rule.replace('_',' ')}) or the next CHoCH.`}
    <span class="sub"> · designed on ${TFS[dtf]} candles · warm-up ${m0.warmup_days} sessions · AVWAP ${m0.avwap_weight}-weighted · slippage futures 5 / options 0.5 pt per side</span>`;
  // option settings: once, across the option columns
  const opts=rs.filter(m=>m.variant!=='FUT'),nf=rs.length-opts.length,o=opts[0];
  let optRow='';
  if(o){const rr=runOf(o),keys=rr?Object.keys(rr.choices):[],exps=[...new Set(keys.map(k=>ck(k)[0]))],strikes=[...new Set(keys.map(k=>ck(k)[1]))];
    optRow=(nf?`<div class="optpad" style="grid-column:1/${nf+1}"></div>`:'')+
      `<div class="optrow" style="grid-column:${nf+1}/${rs.length+1}"><b>Options</b> expiry <span class="seg sm" id="expSeg">${exps.map(e=>`<button data-v="${e}" class="${S().exp===e?'on':''}">${EXP[e]}</button>`).join('')}</span>
       strike <select id="stkSel">${strikes.map(x=>`<option ${S().strike===x?'selected':''}>${x}</option>`).join('')}</select>
       <span>${S().strike.startsWith('ATR')?`spot ± ${S().strike.slice(3)}×ATR(${o.atr_period}), OTM`:'from spot'}</span><span class="sp" style="flex:1"></span><span>strike: Options (via futures)${rs.some(x=>x.variant==='OPT_NATIVE')?' · Options (standalone) '+SCANTXT(rs.find(x=>x.variant==='OPT_NATIVE')):''}</span></div>`;}
  const col=m=>{const on=m.code===cur.code,sch=schemeOf(m),all=statOf(m,'BOTH');
    const cv=m.variant==='FUT'?`<div class="cov">exchange futures · every signal priced</div>`
      :`<div class="cov ${all&&all.skipped?'thin':''}">${!all?'not run':all.skipped?`${all.trades} of ${all.trades+all.skipped} positions priced · ${all.skipped} without option data`:`all ${all.trades} ${LOTS(m)>1?'lot exits':'positions'} priced`}</div>`;
    const row=x=>{const st=statOf(m,x);return `<div class="srow ${on&&sch===x?'on':''}" data-c="${m.code}" data-s="${x}" title="${esc(SDESC(m,x))}${st?` · PF ${st.pf??'—'}`:''}"><span>${SCH[x]}</span><span class="n ${st?cl(st.net_inr):''}">${st?inr(st.net_inr):'—'}</span><span class="m">${st?`${st.trades} trades · ${pctw(st)}`:''}</span></div>`;};
    const sides=m.variant==='FUT'?'':`<div class="sides">${['CE','PE'].map(x=>{const st=statOf(m,x);return `<span class="sd ${on&&sch===x?'on':''}" data-c="${m.code}" data-s="${x}" title="${esc(SDESC(m,x))}">${x} side <b class="${st?cl(st.net_inr):''}">${st?inr(st.net_inr):'—'}</b></span>`;}).join(' · ')}</div>`;
    const scan=m.variant==='OPT_NATIVE'&&choiceOf(m).endsWith('-SCAN')?`<div class="cov">${SCANTXT(m)}</div>`:'';
    return `<div class="col ${on?'cur':''}"><h4 data-c="${m.code}">${TYPE[m.variant]}</h4>${cv}${scan}${['BOTH','LONG','SHORT'].map(row).join('')}${sides}</div>`;};
  $('head').innerHTML=`<div class="hbar"><span class="brand">Strategy lab</span>${stratCtl}<span class="pipe">|</span>${btCtl}<span class="dates">${r.status==='ok'?rng(r):''}</span>${tfCtl}
      ${r.timeframe!==dtf?`<span class="badge">rules built for ${TFS[dtf]}</span>`:''}${(r.underlying||'FUT')!==(m0.underlying||'FUT')?`<span class="badge">signals on the ${r.underlying==='INDEX'?'index':'futures'} · designed on the ${m0.underlying==='INDEX'?'index':'futures'}</span>`:''}${HOLD(r)&&HOLD(r)!==HOLD0(m0)?`<span class="badge">${HOLD(r)} · the strategy is ${HOLD0(m0)}</span>`:''}<span class="sp"></span>
      <span id="jobBadge"></span><span class="menu"><span class="link" id="addL">+ backtest</span><div class="pop" id="addP" style="left:auto;right:0;padding:8px 10px">${backtestPanel(f,r,runs,addCmds)}</div></span><span class="link" id="rulesL">Rules ${ST.rules?'▴':'▾'}</span></div>
    <div id="rules" class="${ST.rules?'on':''}">${rules}</div>
    <div class="cols" style="grid-template-columns:repeat(${rs.length},minmax(0,1fr))">${optRow}${rs.map(col).join('')}</div>`;
  const go=()=>{saveAll();openType(true);};
  // switching strategy carries the current type, scheme, backtest and option settings across
  const switchStrat=nf=>{if(nf===f)return;const T=SEL[nf],m2=rowsOf(nf).find(x=>x.variant===cur.variant);
    if(m2){T.type=m2.code;T.scheme[m2.code]=schemeOf(cur);}
    const e=Object.entries(runsOf(nf)).filter(([k,x])=>x.label===r.label&&x.status==='ok'),pick=e.find(([k,x])=>x.design)||e[0];if(pick)T.run=pick[0];
    T.exp=S().exp;T.strike=S().strike;ST.fam=nf;go();};
  document.querySelectorAll('#stratSeg button').forEach(b=>b.onclick=()=>switchStrat(b.dataset.f));
  if($('stratSel'))$('stratSel').onchange=e=>switchStrat(e.target.value);
  document.querySelectorAll('#btSeg button').forEach(b=>b.onclick=()=>{if(b.classList.contains('off')||b.dataset.l===r.label)return;
    const e=Object.entries(runs).filter(([k,x])=>x.label===b.dataset.l&&x.status==='ok'),pick=e.find(([k,x])=>x.timeframe===r.timeframe)||e.find(([k,x])=>x.design)||e[0];
    if(pick){S().run=pick[0];go();}});
  document.querySelectorAll('#tfSeg button').forEach(b=>b.onclick=()=>{if(b.dataset.k===S().run)return;S().run=b.dataset.k;go();});
  document.querySelectorAll('#head .srow, #head .sd').forEach(el=>el.onclick=()=>{const c=el.dataset.c;S().scheme[c]=el.dataset.s;
    if(c===cur.code){saveAll();schemeChanged();}else{S().type=c;go();}});
  document.querySelectorAll('#head .col h4').forEach(h=>h.onclick=()=>{if(h.dataset.c===cur.code)return;S().type=h.dataset.c;go();});
  document.querySelectorAll('#expSeg button').forEach(b=>b.onclick=()=>{if(S().exp===b.dataset.v)return;S().exp=b.dataset.v;go();});
  if($('stkSel'))$('stkSel').onchange=e=>{S().strike=e.target.value;go();};
  $('addL').onclick=e=>{e.stopPropagation();$('addP').classList.toggle('on');};
  $('addP').onclick=e=>e.stopPropagation();
  wireBacktestPanel(f,r);
  $('rulesL').onclick=()=>{ST.rules=!ST.rules;saveAll();$('rules').classList.toggle('on',ST.rules);$('rulesL').textContent='Rules '+(ST.rules?'▴':'▾');};
}
document.addEventListener('click',()=>document.querySelectorAll('.pop').forEach(x=>x.classList.remove('on')));

// ================= backtest queue (serve.py): add a period / timeframe and run it from the page
const PRESET_MONTHS={'1M':1,'3M':3,'6M':6,'1Y':12,'5Y':60};
function presetFrom(p){const e=new Date(DATA_RANGE[1]+'T00:00:00Z');if(p==='YTD')return DATA_RANGE[1].slice(0,4)+'-01-01';
  e.setUTCMonth(e.getUTCMonth()-PRESET_MONTHS[p]);return e.toISOString().slice(0,10);}
function backtestPanel(f,r,runs,cmds){
  const dtf=designTf(f),have=new Set(Object.values(runs).filter(x=>x.timeframe===dtf).map(x=>x.label));
  const pre=[...Object.keys(PRESET_MONTHS),'YTD'].sort((a,b)=>presetFrom(b).localeCompare(presetFrom(a)));
  const chip=p=>{const lbl=p,short=presetFrom(p)<DATA_RANGE[0];
    return `<button class="qb ${short?'warn':''}" data-what="${p}" ${have.has(lbl)?'disabled title="already a backtest of this strategy"':short?`title="needs data from ${presetFrom(p)}; the data starts ${DATA_RANGE[0]}, so it will be listed as not available until older data is added"`:`title="${presetFrom(p)} → ${DATA_RANGE[1]}"`}>${lbl}${have.has(lbl)?' ✓':''}</button>`;};
  const tfs=Object.keys(TFS).filter(t=>!Object.values(runs).some(x=>x.label===r.label&&x.timeframe===t));
  return `<div class="bq"><div class="apiOnly">
    <h5>Add a backtest period to ${esc(SNAME(rowsOf(f)[0]))}</h5><div class="row">${pre.map(chip).join('')}${have.has('All data')?'':'<button class="qb" data-what="all">All data</button>'}</div>
    <h5>Custom range</h5><div class="row"><input type="date" id="bqFrom" min="${DATA_RANGE[0]}" max="${DATA_RANGE[1]}" value="${DATA_RANGE[0]}"> → <input type="date" id="bqTo" min="${DATA_RANGE[0]}" max="${DATA_RANGE[1]}" value="${DATA_RANGE[1]}">
      <input id="bqLabel" placeholder="name, e.g. July" size="10" maxlength="40"><button class="qb" id="bqCustom">Run</button></div>
    ${tfs.length?`<h5>Run “${esc(r.label)}” on other candles</h5><div class="row">${tfs.map(t=>`<button class="qb" data-tf="${t}">${TFS[t]}</button>`).join('')}</div>`:''}
    ${(()=>{const other=(r.underlying||'FUT')==='INDEX'?'FUT':'INDEX',has=Object.values(runs).some(x=>x.label===r.label&&x.timeframe===r.timeframe&&(x.underlying||'FUT')===other);
      const h0=HOLD(r)||HOLD0(rowsOf(f)[0]),hOther=/^intraday/.test(h0)?'positional':'15:25',
        hHas=Object.values(runs).some(x=>x.label===r.label&&x.timeframe===r.timeframe&&(x.underlying||'FUT')===(r.underlying||'FUT')&&(HOLD(x)||'')===(hOther==='positional'?'positional':'intraday 15:25'));
      const hold=`<h5>Run “${esc(r.label)}” ${hOther==='positional'?'positional (held overnight, no square-off)':'intraday (every position closed by 15:25)'}</h5><div class="row"><button class="qb" data-hold="${hOther}" ${hHas?'disabled title="already run"':''}>${hOther==='positional'?'Positional':'Intraday 15:25'}${hHas?' ✓':''}</button><span class="sub">now: ${h0}</span></div>`;
      return hold+`<h5>Run “${esc(r.label)}” with signals on the ${other==='INDEX'?'index':'futures'}</h5><div class="row"><button class="qb" data-und="${other}" ${has?'disabled title="already run"':''}>${other==='INDEX'?'NIFTY index (equal-weight AVWAP)':'Near-month futures'}${has?' ✓':''}</button><span class="sub">the Futures type still trades the near-month contract</span></div>`;})()}
    <h5>Results missing or out of date</h5><div class="row"><button class="qb" id="bqAll">Recompute what is missing</button><span class="sub">only what changed is computed</span></div>
    <div id="bqMsg" class="sub"></div><pre id="bqLog" style="display:none"></pre>
    <small class="sub">A job adds the backtest to the strategy's file and runs lab.py; the page reloads when it is done. 1-minute option runs can take a while.</small></div>
    <div class="noApi"><small class="sub">Start the page with <code>python serve.py</code> (in research/strategy_lab) to run backtests from here. Or run in a terminal, then reload:</small>${cmds.replace(/^<small class="sub">[^<]*<\/small>/,'')}</div></div>`;}
async function queueJob(path,body){
  $('bqMsg').textContent='sending…';
  try{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();
    if(!r.ok){$('bqMsg').textContent=j.error||('refused: '+r.status);return;}
    $('bqMsg').textContent=`queued: ${j.job.title}`;pollJobs(true);}catch(e){$('bqMsg').textContent='the job server is not reachable: '+e.message;}}
function wireBacktestPanel(f,r){
  document.querySelectorAll('#addP [data-what]').forEach(b=>b.onclick=()=>queueJob('api/backtest',{code:f,what:b.dataset.what}));
  document.querySelectorAll('#addP [data-tf]').forEach(b=>b.onclick=()=>queueJob('api/backtest',r.kind==='custom'||r.kind==='named'
    ?{code:f,what:'custom',from:r.date_from,to:r.date_to,tf:b.dataset.tf,label:r.label}
    :{code:f,what:r.kind==='all'?'all':r.preset,tf:b.dataset.tf,label:r.label}));
  document.querySelectorAll('#addP [data-hold]').forEach(b=>b.onclick=()=>queueJob('api/backtest',Object.assign(r.kind==='custom'||r.kind==='named'
    ?{code:f,what:'custom',from:r.date_from,to:r.date_to}:{code:f,what:r.kind==='all'?'all':r.preset},
    {label:r.label,square_off:b.dataset.hold==='positional'?null:b.dataset.hold},r.timeframe!==designTf(f)?{tf:r.timeframe}:{},
    (r.underlying||'FUT')!=='FUT'?{underlying:r.underlying}:{})));
  document.querySelectorAll('#addP [data-und]').forEach(b=>b.onclick=()=>queueJob('api/backtest',Object.assign(r.kind==='custom'||r.kind==='named'
    ?{code:f,what:'custom',from:r.date_from,to:r.date_to}:{code:f,what:r.kind==='all'?'all':r.preset},
    {label:r.label,underlying:b.dataset.und},r.timeframe!==designTf(f)?{tf:r.timeframe}:{})));
  if($('bqCustom'))$('bqCustom').onclick=()=>queueJob('api/backtest',{code:f,what:'custom',from:$('bqFrom').value,to:$('bqTo').value,label:$('bqLabel').value.trim()});
  if($('bqAll'))$('bqAll').onclick=()=>queueJob('api/run',{});
  pollJobs(false);}
let JOBT=null,JOBSEEN=null;
async function pollJobs(expect){
  clearTimeout(JOBT);let st;
  try{const r=await fetch('api/status',{cache:'no-store'});if(!r.ok)throw 0;st=await r.json();}catch(e){document.body.classList.remove('api');return;}
  document.body.classList.add('api');
  const j=st.jobs[0],badge=$('jobBadge');if(!badge)return;
  if(j&&(j.state==='queued'||j.state==='running')){
    badge.className='';badge.textContent=`⟳ ${j.state==='running'?'running':'queued'}: ${j.title}`+(st.jobs.filter(x=>x.state==='queued').length>1?` (+${st.jobs.filter(x=>x.state==='queued').length-1} queued)`:'');
    if($('bqLog')){$('bqLog').style.display='block';$('bqLog').textContent=j.log.join('\n');}
    JOBSEEN=j.id;JOBT=setTimeout(()=>pollJobs(true),3000);return;}
  if(j&&j.id===JOBSEEN){            // the job this page was waiting for has ended
    if(j.state==='done'){badge.textContent='✓ done: '+j.title+' · reloading';setTimeout(()=>location.reload(),800);}
    else{badge.className='failed';badge.textContent='✗ failed: '+j.title;if($('bqLog')){$('bqLog').style.display='block';$('bqLog').textContent=j.log.join('\n');}}
    JOBSEEN=null;return;}
  badge.textContent='';if(expect)JOBT=setTimeout(()=>pollJobs(true),3000);}

// ================= save the chart as shown (PNG, or a smaller JPEG), with the breadcrumb as a title line
function saveChart(fmt){
  if(typeof ch==='undefined'||!ch||!ch.takeScreenshot)return;
  const shot=ch.takeScreenshot(),title=($('crumb').innerText||'').replace(/\s+/g,' ').trim(),day=($('series').selectedOptions[0]||{}).text||'';
  const low=ch2&&$('optWrap').style.display!=='none'?ch2.takeScreenshot():null,lowT=low?$('optLbl').textContent:'';
  const H=26,c=document.createElement('canvas');c.width=Math.max(shot.width,low?low.width:0);c.height=shot.height+H+(low?low.height+H:0);
  const g=c.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,c.width,c.height);
  g.fillStyle='#111';g.font='13px system-ui, sans-serif';g.fillText((title+(day?'  ·  '+day:'')).slice(0,220),8,17);g.drawImage(shot,0,H);
  if(low){g.fillText(lowT.slice(0,220),8,shot.height+H+17);g.drawImage(low,0,shot.height+2*H);}
  const name=(title+' '+day).replace(/[^\w.-]+/g,'_').replace(/_+/g,'_').slice(0,120)+(fmt==='jpeg'?'.jpg':'.png');
  c.toBlob(b=>{const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;document.body.appendChild(a);a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1000);},fmt==='jpeg'?'image/jpeg':'image/png',fmt==='jpeg'?0.85:undefined);}
$('snapPng').onclick=()=>saveChart('png');$('snapJpg').onclick=()=>saveChart('jpeg');

// ================= data + chart chunks
const getJSON=async f=>{if(!cache[f])cache[f]=fetch(f).then(r=>{if(!r.ok)throw new Error(f+' '+r.status);return r.json();});return cache[f];};
const busy=(v,txt)=>{$('loading').style.display=v?'flex':'none';if(txt)$('loading').textContent=txt;};
let WIN=null,extending=false,VIEW='signal',ch2=null,SYNC=false;
// option types with an underlying chart: that chart on top (index or futures, whichever the signals came from) and the traded
// option's own chart below it, from the session before; both keep the same time window
const STACK=()=>!!(D&&cur&&cur.variant!=='FUT'&&D.charts.some(c=>(c.kind||'signal')==='signal')&&D.charts.some(c=>c.kind==='option'));
function syncCharts(from,r){if(SYNC||!r)return;const other=from==='opt'?ch:ch2;if(!other)return;SYNC=true;
  try{other.timeScale().setVisibleRange(r);}catch(e){}finally{setTimeout(()=>SYNC=false,0);}}
async function showOpt(day,pick){
  const box=$('optWrap');if(!STACK()){box.style.display='none';if(ch2){ch2.remove();ch2=null;}return;}
  box.style.display='';const ix=D.charts.map((c,i)=>i).filter(i=>D.charts[i].kind==='option'&&D.charts[i].day===day);
  const k=pick!=null&&ix.includes(pick)?pick:ix[0];
  $('optSeg').innerHTML=ix.length>1?ix.map(i=>`<button data-k="${i}" class="${i===k?'on':''}">${esc(D.charts[i].label.split(' · ').slice(1,2).join(''))}</button>`).join(''):'';
  $('optSeg').querySelectorAll('button').forEach(b=>b.onclick=()=>showOpt(day,+b.dataset.k));
  if(k==null){$('optLbl').textContent='Option';$('optNone').style.display='flex';$('ohlc2').innerHTML='';if(ch2){ch2.remove();ch2=null;}return null;}
  $('optNone').style.display='none';$('optLbl').textContent=D.charts[k].label.split(' · ').slice(1).join(' · ')+' · from the session before';
  const c=await getJSON(D.base+D.charts[k].file);drawChart(c,true,null,'opt');
  try{const r=ch&&ch.timeScale().getVisibleRange();if(r)ch2.timeScale().setVisibleRange(r);}catch(e){}
  return c;}
const merge=parts=>{const seen=new Set(),M=[];for(const c of parts)for(const m of c.M)if(!seen.has(m[0]+'|'+m[9])){seen.add(m[0]+'|'+m[9]);M.push(m);}
  // FZ: Z rows per bar, ZONES by id (option chunks have neither). A room (FZ v2 id, not 'A/B<yyyy-mm-dd ...>') is drawn only to the
  // end of the last merged chunk that lists it: lab leaves a room out of every chunk that starts after it retired, so a merged
  // window must not carry it on past that chunk (a 6th element, end; base bands keep none and run to the last bar)
  const cat=k=>parts.flatMap(c=>c[k]||[]),ZN=new Map();
  for(const c of parts){const e=c.C&&c.C.length?c.C[c.C.length-1][0]:null;
    for(const z of c.ZONES||[]){const r=ZN.get(z[0])||[...z.slice(0,5),null];if(!/^[AB]\d{4}-/.test(z[0]))r[5]=e;ZN.set(z[0],r);}}
  return {C:cat('C'),S:cat('S'),E:cat('E'),PR:cat('PR'),PAIR:cat('PAIR'),M,Z:cat('Z'),ZONES:[...ZN.values()]};};
async function renderWin(range){const parts=[];for(let k=WIN.lo;k<=WIN.hi;k++)parts.push(await getJSON(D.base+D.charts[k].file));const c=merge(parts);drawChart(c,!range,range);return c;}
const inView=()=>D.charts.map((c,i)=>i).filter(i=>(D.charts[i].kind||'signal')===VIEW);
async function showChunk(k){if(k==null||isNaN(k))return;$('series').value=k;busy(true,'Loading chart…');
  try{WIN={lo:k,hi:k};const c=await renderWin();await showOpt(D.charts[k].day);return c;}finally{busy(false);}}
async function extend(dir,r){if(extending||VIEW!=='signal')return;
  const k=dir<0?WIN.lo-1:WIN.hi+1;if(k<0||k>=D.charts.length||(D.charts[k].kind||'signal')!=='signal')return;
  extending=true;busy(true,dir<0?'Loading earlier session…':'Loading next session…');
  try{const add=await getJSON(D.base+D.charts[k].file);if(dir<0){WIN.lo=k;await renderWin({from:r.from+add.C.length,to:r.to+add.C.length});}else{WIN.hi=k;await renderWin(r);}}
  finally{busy(false);setTimeout(()=>extending=false,150);}}
async function setView(v,k){VIEW=v;$('viewSeg').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
  const ix=inView();$('series').innerHTML=ix.map(i=>`<option value="${i}">${D.charts[i].label}</option>`).join('');
  $('all').style.display=v==='signal'?'':'none';return showChunk(k??ix[ix.length-1]);}
$('series').onchange=()=>showChunk(+$('series').value);
$('prev').onclick=()=>{const ix=inView(),j=ix.indexOf(+$('series').value);if(j>0)showChunk(ix[j-1]);};
$('next').onclick=()=>{const ix=inView(),j=ix.indexOf(+$('series').value);if(j<ix.length-1)showChunk(ix[j+1]);};
$('all').onclick=async()=>{const ix=inView(),n=ix.length;for(let j=0;j<n;j++){busy(true,`Loading full period… ${j+1}/${n}`);await getJSON(D.base+D.charts[ix[j]].file);}busy(false);WIN={lo:ix[0],hi:ix[n-1]};await renderWin(null);};

// ================= open strategy / type / scheme
async function openStrategy(){await openType();}
async function openType(keepDay){
  const keep=keepDay&&D&&$('series').value!==''?(D.charts[+$('series').value]||{}).day:null;
  const f=ST.fam;cur=rowsOf(f).find(m=>m.code===S().type)||rowsOf(f)[0];S().type=cur.code;curChoice=choiceOf(cur);
  const r=runOf(cur);if(!r.choices[curChoice])curChoice=Object.keys(r.choices)[0];
  renderHeader();
  const file=r.choices[curChoice].file;busy(true,'Loading…');
  try{D=await getJSON(file);D.base=file.slice(0,file.lastIndexOf('/')+1);}finally{busy(false);}
  const kinds=[...new Set(D.charts.map(c=>c.kind||'signal'))];VIEW=STACK()?'signal':kinds.includes('option')?'option':'signal';
  $('viewSeg').style.display=kinds.length>1&&!STACK()?'':'none';
  const und=(runOf(cur).underlying||'FUT')==='INDEX'||cur.variant==='OPT_NATIVE'?'index':'futures';
  $('viewSeg').innerHTML=kinds.map(k=>`<button data-v="${k}">${k==='option'?'Option chart':`Signal chart (${und})`}</button>`).join('');
  if(!STACK()){$('optWrap').style.display='none';if(ch2){ch2.remove();ch2=null;}}
  $('viewSeg').querySelectorAll('button').forEach(b=>b.onclick=()=>setView(b.dataset.v));
  CALM=null;schemeChanged(true);let k0;
  if(keep){const ix=D.charts.map((c,i)=>i).filter(i=>(D.charts[i].kind||'signal')===VIEW&&D.charts[i].day);   // same day, else the nearest one
    const dist=i=>Math.abs(Date.parse(D.charts[i].day)-Date.parse(keep));if(ix.length)k0=ix.reduce((a,b)=>dist(b)<dist(a)?b:a);}
  await setView(VIEW,k0);
}
function schemeChanged(noChart){
  renderHeader();
  const r=runOf(cur),dtf=designTf(ST.fam);
  $('crumb').innerHTML=`${SNAME(cur)}<span>›</span>${r.label}${r.timeframe!==dtf?` · ${TFS[r.timeframe]}`:''}<span>›</span>${TYPE[cur.variant]}<span>›</span>${SCH[schemeOf(cur)]}${cur.variant!=='FUT'?`<span>·</span><span style="margin:0">${EXP[ck(curChoice)[0]]} ${ck(curChoice)[1]}</span>`:''}${star(cov(cur))}`;
  renderBelow();if(!noChart)showChunk(+$('series').value);
}
const inScheme=lbl=>{const [pos,ot]=(lbl||'').split(' ');return inSch({pos,otype:ot||'FUT'},schemeOf(cur));};

// ================= chart
function drawChart(CH_,single,range,tgt){
  const {C,S:SW,E,PR,PAIR,M,Z=[],ZONES=[]}=CH_;
  const OPT=tgt==='opt',EL=$(OPT?'chart2':'chart');
  if(OPT){if(ch2){ch2.remove();ch2=null;}}else if(ch){ch.remove();ch=null;}
  const cx=LightweightCharts.createChart(EL,{autoSize:true,layout:{background:{color:'#fff'},textColor:'#4b5563',fontFamily:'system-ui'},
    grid:{vertLines:{color:'#f3f4f6'},horzLines:{color:'#f3f4f6'}},rightPriceScale:{borderColor:'#e6e8ec'},
    timeScale:{timeVisible:true,secondsVisible:false,rightOffset:4,borderColor:'#e6e8ec'},crosshair:{mode:0},
    handleScroll:{mouseWheel:false,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},
    handleScale:{mouseWheel:false,pinch:true,axisPressedMouseMove:true},localization:{timeFormatter:t=>iso(t).slice(5,16).replace('T',' ')}});
  if(OPT)ch2=cx;else ch=cx;
  // FZ bands / rooms (Strategies 5-8): one translucent lo-hi box per remembered band from its birth (or the first bar) to the last bar
  // (a room: to the end of the last merged chunk that lists it, see merge()),
  // added before the candles so it sits under them; A = protected-level band (chart purple), B = cluster-sit band (chart blue)
  const tint=(h,a)=>`rgba(${parseInt(h.slice(1,3),16)},${parseInt(h.slice(3,5),16)},${parseInt(h.slice(5,7),16)},${a})`;
  const ZS=[],t0=C[0][0],t1=C[C.length-1][0];
  for(const [,kind,lo,hi,born,end] of ZONES){const a=Math.max(born,t0),b=end!=null?Math.min(end,t1):t1;if(a>=b)continue;const col=tint(kind==='A'?'#7b1fa2':'#2962ff',.07);
    const s=cx.addBaselineSeries({lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false,autoscaleInfoProvider:()=>null,visible:on.zones,
      baseValue:{type:'price',price:lo},lineVisible:false,topLineColor:col,topFillColor1:col,topFillColor2:col,bottomLineColor:col,bottomFillColor1:col,bottomFillColor2:col});
    s.setData([{time:a,value:hi},{time:b,value:hi}]);ZS.push(s);}
  const cs=cx.addCandlestickSeries({upColor:'#089981',downColor:'#f23645',wickUpColor:'#089981',wickDownColor:'#f23645',borderVisible:false});
  cs.priceScale().applyOptions({scaleMargins:{top:0.06,bottom:0.2}});
  cs.setData(C.map(r=>({time:r[0],open:r[1],high:r[2],low:r[3],close:r[4]})));
  const base={lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false,autoscaleInfoProvider:()=>null};
  const L={vol:[],swings:[],avwap:[],prot:[],trades:[],zones:ZS,rlevels:[]};
  const line=(layer,opt,data)=>{const s=cx.addLineSeries({...base,...opt,visible:on[layer]});s.setData(data);L[layer].push(s);};
  const vs=cx.addHistogramSeries({priceScaleId:'vol',priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false,visible:on.vol});
  cx.priceScale('vol').applyOptions({scaleMargins:{top:0.84,bottom:0}});
  vs.setData(C.map(r=>({time:r[0],value:r[7],color:r[4]>=r[1]?'rgba(8,153,129,.35)':'rgba(242,54,69,.35)'})));L.vol.push(vs);
  for(const [idx,col] of [[5,'rgba(8,153,129,.4)'],[6,'rgba(242,54,69,.4)']])
    line('swings',{color:col,lineVisible:false,pointMarkersVisible:true,pointMarkersRadius:1.5},C.map(r=>r[idx]==null?{time:r[0]}:{time:r[0],value:r[idx]}));
  const MK={swings:[],struct:[],trades:[],fz:[]};
  for(const [k,t,p,ct] of SW){const hi=k==='H',col=hi?'#089981':'#f23645';
    MK.swings.push({time:t,position:hi?'aboveBar':'belowBar',color:col,shape:'square',size:0.1});
    MK.swings.push({time:ct,position:hi?'aboveBar':'belowBar',color:col,shape:hi?'arrowDown':'arrowUp',size:0.5});
    line('swings',{color:col,lineWidth:1},t===ct?[{time:t,value:p}]:[{time:t,value:p},{time:ct,value:p}]);}
  {const pm=new Map(PR);line('prot',{color:'#7b1fa2',lineWidth:1,lineStyle:2,lineType:1},C.map(r=>pm.has(r[0])?{time:r[0],value:pm.get(r[0])}:{time:r[0]}));}
  for(const a of PAIR){const col=a.side==='H'?'#ff6d00':'#2962ff';
    line('avwap',{color:col,lineWidth:2},a.live.map(([x,v])=>({time:x,value:v})));
    if(a.back.length>1)line('avwap',{color:col,lineWidth:1,lineStyle:1},a.back.map(([x,v])=>({time:x,value:v})));}
  for(const [x,kind,dir] of E)MK.struct.push({time:x,position:dir==='up'?'aboveBar':'belowBar',color:kind==='BOS'?'#9e9e9e':'#7b1fa2',shape:'circle',size:kind==='BOS'?0.2:0.5,text:kind==='BOS'?'':'CHoCH'});
  const tmin=C[0][0],tmax=C[C.length-1][0];
  for(const [et0,ep,xt,xp,d,pts,open,sl,why,label] of M){const lbl=label||(d==='up'?'LONG':'SHORT');if(!inScheme(lbl))continue;
    const up=d==='up',win=pts>0,xe=Math.min(xt,tmax),et=Math.max(et0,tmin);
    if(et0>=tmin)MK.trades.push({time:et0,position:up?'belowBar':'aboveBar',color:'#111',shape:up?'arrowUp':'arrowDown',size:1.5,text:lbl});
    if(xt<=tmax)MK.trades.push({time:xt,position:up?'aboveBar':'belowBar',color:win?'#089981':'#f23645',shape:'circle',size:0.9,text:(why==='stop_loss'?'SL ':why==='trail_stop'?'TRAIL ':why==='eod'?'EOD ':/^target /.test(why||'')?'T'+why.slice(7)+' ':why==='expiry'?'EXPIRY ':why==='band_reclaim'?'BAND ':open?'OPEN* ':'')+fmt(pts)});
    line('trades',{color:win?'#089981':'#f23645',lineWidth:2,lineStyle:2},et===xe?[{time:et,value:ep}]:[{time:et,value:ep},{time:xe,value:xp}]);
    if(sl!=null)line('trades',{color:'#d32f2f',lineWidth:1,lineStyle:1},et===xe?[{time:et,value:sl}]:[{time:et,value:sl},{time:xe,value:sl}]);}
  // managed exits (position.exit "position", Strategies 9-10): each position's stop, its target levels (1R, 2R ...) and the level
  // where the trail starts (3R), from the entry to the position's last exit, labelled on the price axis. R = |entry - initial stop|
  // in the traded instrument; drawn on futures / index charts for the Futures type and on the option's own chart for option types
  if(MANAGED(cur)&&(cur.variant==='FUT'||OPT||VIEW==='option')){
    const P=cur.position,byE=new Map(),seen=new Set(),base0=l=>(l||'').split(' · ')[0];
    for(const t of allTrades())if(t.sl!=null)byE.set(t.ets+'|'+t.pos+'|'+(cur.variant==='FUT'?'':t.otype),t);
    const lv=[['SL',-1,'#d32f2f'],...(P.scale_out||[]).filter(x=>x.target_r!=null).map(x=>[x.target_r+'R',x.target_r,'#089981']),
              ...(P.trail?[[P.trail.start_r+'R trail',P.trail.start_r,'#2962ff']]:[])];
    for(const m of M){const [et0,ep,,,d,,,,,label]=m,lbl=label||(d==='up'?'LONG':'SHORT');if(!inScheme(lbl))continue;
      const pos=d==='up'?'LONG':'SHORT',ot=cur.variant==='FUT'?'':(base0(lbl).split(' ')[1]||''),key=et0+'|'+pos+'|'+ot;
      if(seen.has(key))continue;const t=byE.get(key);if(!t)continue;seen.add(key);
      const end=Math.min(Math.max(...M.filter(z=>z[0]===et0&&z[4]===d&&base0(z[9])===base0(lbl)).map(z=>z[2])),tmax),a=Math.max(et0,tmin);
      const R=Math.abs(t.ep-t.sl),sg=d==='up'?1:-1;if(!R||a>end)continue;
      for(const [name,k,col] of lv){const y=+(ep+sg*k*R).toFixed(2);
        line('rlevels',{color:col,lineWidth:1,lineStyle:k<0?0:2,title:name,lastValueVisible:true},a===end?[{time:a,value:y}]:[{time:a,value:y},{time:end,value:y}]);}}}
  // FZ gate at each Foundation SETUP (T TAKE · W WATCH · B BLOCK · R REENTER), plus R where a watch re-entered on a later bar;
  // below the bar for up, above for down; futures chunks only (they carry Z); toggled with the trades layer
  if(D&&D.fz&&Z.length){const {cols,rows}=D.fz.ledger,[iT,iD,iG,iO,iF,iOG]=['time','dir','gate','watch_outcome','fill_time','outcome_gate'].map(k=>cols.indexOf(k));
    const G={TAKE:['T','#2962ff'],WATCH:['W','#9e9e9e'],BLOCK:['B','#f23645'],REENTER:['R','#7b1fa2']},has=new Set(C.map(r=>r[0]));
    const put=(s,d,[txt,col])=>{const x=Date.parse(s.replace(' ','T')+'Z')/1000;if(has.has(x))MK.fz.push({time:x,position:d==='up'?'belowBar':'aboveBar',color:col,shape:'circle',size:0.3,text:txt});};
    const later=r=>(iOG>=0?r[iOG]==='REENTER':r[iO]==='reenter')&&r[iF]&&r[iF]!==r[iT];   // the SETUP's REENTER filled on a later bar
    for(const r of rows){if(G[r[iG]])put(r[iT],r[iD],G[r[iG]]);if(later(r))put(r[iF],r[iD],G.REENTER);}}
  const markers=()=>{const m=[];if(on.swings)m.push(...MK.swings);if(on.struct)m.push(...MK.struct);if(on.trades)m.push(...MK.trades,...MK.fz);m.sort((a,b)=>a.time-b.time);cs.setMarkers(m);};
  markers();
  const chips=[['trades','Trades','#111'],...(MANAGED(cur)?[['rlevels','1R / 2R / 3R','#089981']]:[]),['avwap','AVWAP','#ff6d00'],['prot','Protected','#7b1fa2'],['struct','CHoCH/BOS','#9e9e9e'],['swings','Swings','#089981'],['vol','Volume','#c3c7cf']].concat(ZONES.length?[['zones','Zones','#2962ff']]:[]);
  if(!OPT){$('layers').innerHTML='';
  for(const [k,lbl,col] of chips){const b=document.createElement('span');b.className='chip'+(on[k]?' on':'');b.innerHTML=`<i style="background:${col}"></i>${lbl}`;
    b.onclick=()=>{on[k]=!on[k];b.classList.toggle('on',on[k]);(L[k]||[]).forEach(s=>s.applyOptions({visible:on[k]}));markers();};$('layers').appendChild(b);}}
  const byT=new Map(C.map(r=>[r[0],r]));
  // FZ card of the hovered bar, from its as-of Z row: band and edges · visit n · this / first visit bars · volume ratio · read
  const byZ=new Map(Z.map(z=>[z[0],z])),ZI=new Map(ZONES.map(z=>[z[0],z])),RD=D&&D.fz?D.fz.legend.read:[];
  const zn=id=>/^[AB]\d{4}-/.test(id)?id[0]+id.slice(6,17):id;               // 'B2026-07-01 11:41:00' -> 'B07-01 11:41'; a room id ('E 09-03 12:20') prints whole
  // the ratio is NA when this visit or the band's first visit is volume-NA (as the gate reads it); fvna is absent in older chunks
  const zcard=z=>{if(!z)return '';const [,id,vn,tb,tv,fb,fv,rc,left,,vna,,,,,fvna]=z,b=id&&ZI.get(id),rd=RD[rc]||'';
    const band=id?`Z ${zn(id)}${b?` ${b[2]}–${b[3]}`:''} · visit ${vn} · ${tb}/${fb??'—'} bars · vol ${!vna&&!fvna&&tv!=null&&fv?(tv/fv).toFixed(2):'NA'}`:'no band';
    return `<span class="pipe">|</span>${band} · <b>${rd}</b>${rd==='LEAVE'&&left?` from ${zn(left)}`:''}`;};
  const showBar=r=>{if(!r)return;$(OPT?'ohlc2':'ohlc').innerHTML=`${iso(r[0]).slice(5,16).replace('T',' ')} O <b>${r[1]}</b> H <b>${r[2]}</b> L <b>${r[3]}</b> C <b class="${r[4]>=r[1]?'pos':'neg'}">${r[4]}</b> V <b>${r[7].toLocaleString('en-IN')}</b>${zcard(byZ.get(r[0]))}`;};
  showBar(C[C.length-1]);cx.subscribeCrosshairMove(p=>showBar(p.time?byT.get(p.time):C[C.length-1]));
  EL.onwheel=e=>{if(!e.ctrlKey)return;e.preventDefault();const ts=cx.timeScale(),r=ts.getVisibleLogicalRange();if(!r)return;
    const x=ts.coordinateToLogical(e.offsetX)??(r.from+r.to)/2,k=e.deltaY>0?1.15:1/1.15;ts.setVisibleLogicalRange({from:x-(x-r.from)*k,to:x+(r.to-x)*k});};
  const per=375/({'minute':1,'3minute':3,'5minute':5,'15minute':15,'30minute':30}[runOf(cur).timeframe]||5);
  if(range)cx.timeScale().setVisibleLogicalRange(range);
  else if(single)cx.timeScale().fitContent();else cx.timeScale().setVisibleLogicalRange({from:C.length-per-2,to:C.length+2});
  if(WIN&&!OPT)cx.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(!r||extending)return;if(r.from<5&&WIN.lo>0)extend(-1,r);else if(r.to>C.length+2&&WIN.hi<D.charts.length-1)extend(1,r);});
  cx.timeScale().subscribeVisibleTimeRangeChange(r=>syncCharts(OPT?'opt':'top',r));
  CH_.zoom=(a,b)=>{const idx=t=>{let lo=0,hi=C.length-1;while(lo<hi){const m=(lo+hi)>>1;if(C[m][0]<t)lo=m+1;else hi=m;}return lo;};cx.timeScale().setVisibleLogicalRange({from:idx(a)-20,to:idx(b)+20});};
}
async function openTrade(et,xt){
  if(STACK()){const day=iso(et).slice(0,10),k=D.charts.findIndex(c=>(c.kind||'signal')==='signal'&&c.day===day);
    if(k>=0){if(VIEW!=='signal')await setView('signal',k);const c=await showChunk(k);if(c)c.zoom(et,xt);
      const o=D.charts.findIndex(c=>c.kind==='option'&&c.day===day&&c.marks.includes(et));if(o>=0)await showOpt(day,o);
      document.querySelector('.chartcard').scrollIntoView({behavior:'smooth',block:'start'});return;}}
  let k=inView().find(i=>D.charts[i].marks.includes(et));
  if(k==null){k=D.charts.findIndex(c=>c.marks.includes(et));if(k<0)k=inView().slice(-1)[0];else await setView(D.charts[k].kind||'signal',k);}
  const c=await showChunk(k);if(c)c.zoom(et,xt);document.querySelector('.chartcard').scrollIntoView({behavior:'smooth',block:'start'});
}
async function openDay(d){const k=inView().find(i=>D.charts[i].day===d);if(k!=null){await showChunk(k);document.querySelector('.chartcard').scrollIntoView({behavior:'smooth',block:'start'});}}
// the futures chart of t0's session, zoomed to t0..t1 (epoch s): a Zone gate ledger row is a SETUP, not necessarily a trade entry
async function openAt(t0,t1){const d=iso(t0).slice(0,10),k=D.charts.findIndex(c=>(c.kind||'signal')==='signal'&&c.day===d);if(k<0)return;
  if(VIEW!=='signal')await setView('signal',k);const c=await showChunk(k);if(c)c.zoom(t0,t1);document.querySelector('.chartcard').scrollIntoView({behavior:'smooth',block:'start'});}

// ================= trades of the current selection
const allTrades=()=>D.trades.map(([otype,instr,strike,cht,et,ep,sl,xt,xp,why,pts,gross,chg,net,open,cb,ue,ux,stale,mfe,mae,pos,ot,sig,exp,g_,rr_,z_,f_,lots,tranche,scan])=>({otype:ot||otype,pos:pos||'LONG',sig:sig||'',exp,instr,strike,cht,et,ep,sl,xt,xp,why,pts,gross,chg,net,open,cb,ue,ux,stale,mfe:mfe??0,mae:mae??0,lots:lots||1,tranche:tranche||'',scan:scan||'',
    ets:Date.parse(et.replace(' ','T')+'Z')/1000,xts:Date.parse(xt.replace(' ','T')+'Z')/1000}));
const sel=()=>allTrades().filter(t=>inSch(t,schemeOf(cur)));
const sessionsOf=()=>[...new Set(D.charts.map(c=>c.day).filter(Boolean))].sort();
const sigName=t=>!t.sig?'—':cur.variant==='OPT_NATIVE'?(t.sig==='BULLISH'?'Bullish (option chart)':'Bearish (option chart)'):(t.sig==='BULLISH'?'Future long':'Future short');
const WHY={stop_loss:'SL',next_choch:'CHoCH',expiry:'Expiry',open:'open*',band_reclaim:'Band',trail_stop:'Trail'};
function statsOf(T){const net=T.map(t=>t.net);let eq=0,pk=0,dd=0;for(const v of net){eq+=v;pk=Math.max(pk,eq);dd=Math.min(dd,eq-pk);}
  const n=net.length,m=n?net.reduce((a,b)=>a+b,0)/n:0,sd=n>1?Math.sqrt(net.reduce((a,v)=>a+(v-m)**2,0)/(n-1)):0;
  const wins=net.filter(v=>v>0),loss=net.filter(v=>v<=0),sl=loss.reduce((a,b)=>a+b,0);
  return {trades:n,wins:wins.length,pts:sum(T,t=>t.pts),gross_inr:sum(T,t=>t.gross),charges_inr:sum(T,t=>t.chg),net_inr:net.reduce((a,b)=>a+b,0),max_dd_inr:dd,
    pf:loss.length&&sl?+(wins.reduce((a,b)=>a+b,0)/-sl).toFixed(2):null,t_stat:sd?+(m/(sd/Math.sqrt(n))).toFixed(2):null,mean:m,sd};}
const tradeMin=(t,sess)=>{const hm=s=>+s.slice(11,13)*60+ +s.slice(14,16);const d0=t.et.slice(0,10),d1=t.xt.slice(0,10);if(d0===d1)return hm(t.xt)-hm(t.et);
  const between=sess.filter(d=>d>d0&&d<d1).length;return (930-hm(t.et))+375*between+(hm(t.xt)-555);};
// capital scales with the lots a position is opened with (position.lots)
const LOTS=m=>(m.position&&m.position.lots)||1,MANAGED=m=>!!(m.position&&m.position.exit==='position');
const capitalFor=T=>{const m=cur,L=LOTS(m),per=L>1?` × ${L} lots`:' per lot';
  if(m.variant==='FUT')return {cap:m.capital_fut*L,how:`futures margin ₹${(m.capital_fut/1e5).toFixed(1)}L${per}`};
  if(T.some(t=>t.pos==='SHORT'))return {cap:m.capital_opt_short*L,how:`short-option margin ₹${(m.capital_opt_short/1e5).toFixed(1)}L${per}`};
  const prem=T.length?sum(T,t=>t.ep*m.lot_size)/T.length*L:0;return {cap:prem,how:`average premium paid ${inr(prem)} per position${L>1?` (${L} lots)`:''}`};};
// R needs the stop in the traded instrument: options via futures carry the futures stop, except under managed exits
const riskPts=t=>((cur.variant==='OPT_FUT_SIGNAL'&&!MANAGED(cur))||t.sl==null)?null:Math.abs(t.ep-t.sl);

// ================= below the chart
// the previous version of this strategy (results/history), same backtest and choice, long + short (the history keeps totals)
function baselineTile(){
  const m=cur,b=m.baseline,v=m.version;if(!b||!v)return '';
  const o=((b.results||{})[S().run]||{})[curChoice],n=statOf(m,'BOTH');
  const why=(v.changes&&v.changes.length?v.changes.join('\n'):'no definition change recorded');
  if(!o)return `<div class="card kpi" title="${esc(why)}"><div class="l">vs version ${b.version}</div><div class="v">—</div><div class="s">not run in version ${b.version}</div></div>`;
  const d=n?n.net_inr-o.net_inr:null;
  return `<div class="card kpi" title="Version ${v.version} (${v.at.slice(0,16).replace('T',' ')}) against version ${b.version} (${b.at.slice(0,16).replace('T',' ')}):\n${esc(why)}"><div class="l">vs version ${b.version} · long + short</div>`+
    `<div class="v ${d!=null?cl(d):''}">${d!=null?(d>=0?'+':'')+inr(d):'—'}</div><div class="s">was ${inr(o.net_inr)} · ${o.trades} trades · PF ${o.pf??'—'} → now ${n?n.trades:'—'} trades · PF ${n&&n.pf!=null?n.pf:'—'}</div></div>`;}
function renderBelow(){
  const m=cur,LOT=m.lot_size,T=sel(),sch=schemeOf(m),s=statsOf(T);
  // incomplete = positions without option data; signals refused by the strike lock are a rule, not missing data
  const skipped=D.skipped.filter(x=>!String(x.why||'').startsWith('strike locked')).filter(x=>sch==='BOTH'||(sch==='LONG'||sch==='SHORT'?(!x.position||x.position===sch):(!x.opt_type||x.opt_type===sch))).length;
  const npos=new Set(T.map(t=>t.et+'|'+t.instr+'|'+t.pos)).size,split=T.some(t=>t.tranche);
  const cv=skipped?{text:`Incomplete: ${s.trades} of ${s.trades+skipped} positions priced.`}:null;
  const exR=T.map(t=>{const rp=riskPts(t);return rp?t.pts/rp:null;}).filter(v=>v!=null);
  // FZ: the random-control percentile sits beside net wherever FZ net is shown (its net is mostly avoided costs); the control
  // is over the whole book, so a one-side scheme says so instead
  const fc=D.fz&&D.fz.control,fzs=!fc?null:sch==='BOTH'&&fc.fz_pct!=null?`random control ${fc.fz_pct.toFixed(1)}th pct · kept-vs-refused p ${D.fz.permutation.p??'—'}`:'gross − charges · FZ control: long + short only';
  $('kpis').innerHTML=[['Net P&L',inr(s.net_inr)+star(cv),cv?`<span style="color:var(--warn-ink)">incomplete · ${s.trades} of ${s.trades+skipped} priced</span>${fzs?' · '+fzs:''}`:(fzs||'gross − charges'),cl(s.net_inr)],
    split?['Positions',npos+(skipped?` of ${npos+skipped}`:''),`${s.trades} lot exits · ${new Set(T.filter(t=>t.pos==='LONG').map(t=>t.et+t.instr)).size} long · ${new Set(T.filter(t=>t.pos==='SHORT').map(t=>t.et+t.instr)).size} short`,'']
      :['Trades',s.trades+(skipped?` of ${s.trades+skipped}`:''),`${T.filter(t=>t.pos==='LONG').length} long · ${T.filter(t=>t.pos==='SHORT').length} short`,''],
    ['Win rate',s.trades?Math.round(100*s.wins/s.trades)+'%':'—',`${s.wins} wins${split?' of '+s.trades+' lot exits':''}`,''],
    ['Profit factor',s.pf??'—','net wins ÷ net losses',''],
    ['Max drawdown',inr(s.max_dd_inr),'peak to trough, by trade',s.max_dd_inr<0?'neg':''],
    ['Expectancy',inr(s.mean),exR.length?`${fmt(exR.reduce((a,b)=>a+b,0)/exR.length,2)} R per trade`:'per trade',cl(s.mean)]]
    .map(([l,v,sub,c])=>`<div class="card kpi"><div class="l">${l}</div><div class="v ${c}">${v}</div><div class="s">${sub}</div></div>`).join('')+baselineTile();
  renderCalendar(T);renderTrades(T,LOT);renderDaily(T);renderBreakdown(T);renderSignals();renderConfig();
  renderTab(document.querySelector('.tab.on').dataset.p);
}
function renderTab(p){const T=sel();({perf:()=>renderPerf(T),equity:()=>renderEquity(T),dd:()=>renderDD(T),dist:()=>renderDist(T),mc:()=>renderMC(T),robust:()=>renderRobust(T),fz:()=>renderFZ()}[p]||(()=>{}))();}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===b));
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('on',p.id==='p-'+b.dataset.p));renderTab(b.dataset.p);});

// ---- daily P&L heatmap (one square per session, week columns, Mon–Fri rows) + day stats
let CALM=null,HMSEL=null;
function renderCalendar(T){
  const by={};T.forEach(t=>{const d=t.xt.slice(0,10);(by[d]??=[]).push(t);});
  const sess=sessionsOf();if(!sess.length){$('cal').innerHTML='';return;}
  const net=d=>by[d]?sum(by[d],t=>t.net):null,vals=sess.map(net).filter(v=>v!=null),mx=Math.max(1,...vals.map(Math.abs));
  const color=v=>{if(v==null)return '';const k=Math.min(4,Math.ceil(Math.abs(v)/mx*4));
    return v>=0?['var(--hp1)','var(--hp2)','var(--hp3)','var(--hp4)'][k-1]:['var(--hn1)','var(--hn2)','var(--hn3)','var(--hn4)'][k-1];};
  const D0=new Date(sess[0]+'T00:00:00Z'),start=new Date(D0);start.setUTCDate(D0.getUTCDate()-((D0.getUTCDay()+6)%7));
  const end=new Date(sess.at(-1)+'T00:00:00Z'),set=new Set(sess),weeks=[];
  for(const d=new Date(start);d<=end;d.setUTCDate(d.getUTCDate()+7))weeks.push([0,1,2,3,4].map(i=>{const x=new Date(d);x.setUTCDate(d.getUTCDate()+i);return x.toISOString().slice(0,10);}));
  // a week is labelled with the month of its first session; labels closer than 3 columns are dropped
  const mon=k=>new Date(k+'T00:00:00Z').toLocaleDateString('en-GB',{month:'short',timeZone:'UTC'});
  let lastM='',lastI=-9;const labels=[];
  weeks.forEach((w,i)=>{const f0=w.find(k=>set.has(k));if(!f0)return;const mk=f0.slice(0,7);if(mk===lastM)return;lastM=mk;if(i-lastI<3)return;lastI=i;labels.push([i,mon(f0)]);});
  const cells=[];
  for(const w of weeks)for(const k of w){
    if(!set.has(k)){cells.push(`<div class="hc x"></div>`);continue;}
    const v=net(k),n=by[k]?by[k].length:0;
    cells.push(`<div class="hc ${v==null?'z':''} ${k===HMSEL?'sel':''}" data-d="${k}" style="${v!=null?'background:'+color(v):''}" title="${new Date(k+'T00:00:00Z').toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric',timeZone:'UTC'})} · ${v==null?'no trades':inr(v)+' · '+n+' trade'+(n>1?'s':'')}"></div>`);}
  const days=sess.map(d=>[d,net(d)]).filter(x=>x[1]!=null),pos=days.filter(x=>x[1]>0),best=days.reduce((a,b)=>!a||b[1]>a[1]?b:a,null),worst=days.reduce((a,b)=>!a||b[1]<a[1]?b:a,null);
  let g=0,r=0,mg=0,mr=0;for(const [,v] of days){if(v>0){g++;r=0;}else{r++;g=0;}mg=Math.max(mg,g);mr=Math.max(mr,r);}
  const tot=sum(days,x=>x[1]),avg=days.length?tot/days.length:0,fd=d=>new Date(d+'T00:00:00Z').toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short',timeZone:'UTC'});
  $('cal').innerHTML=`<div class="hm"><div class="hmhead"><b>Daily P&amp;L</b><span class="sub">by exit day · click a day to open it</span></div>
      <div class="hmmon" style="width:${weeks.length*15}px">${labels.map(([i,m])=>`<span style="left:${i*15}px">${m}</span>`).join('')}</div><div class="hmgrid">${cells.join('')}</div>
      <div class="hmlegend">loss <i style="background:var(--hn4)"></i><i style="background:var(--hn2)"></i><i style="background:var(--h0)"></i><i style="background:var(--hp2)"></i><i style="background:var(--hp4)"></i> profit · grey = session without trades</div></div>
    <div class="hmstats"><div>Profitable days<b>${pos.length} of ${days.length}</b><small>${days.length?Math.round(100*pos.length/days.length):0}% of days with trades</small></div>
      <div>Average day<b class="${cl(avg)}">${inr(avg)}</b><small>net per day with trades</small></div>
      <div>Best day<b class="pos">${best?inr(best[1]):'—'}</b><small>${best?fd(best[0]):''}</small></div>
      <div>Worst day<b class="neg">${worst?inr(worst[1]):'—'}</b><small>${worst?fd(worst[0]):''}</small></div>
      <div>Longest streak<b><span class="pos">${mg} up</span> · <span class="neg">${mr} down</span></b><small>days in a row</small></div></div>`;
  $('cal').querySelectorAll('.hc[data-d]').forEach(c=>c.onclick=()=>{HMSEL=c.dataset.d;$('cal').querySelectorAll('.hc.sel').forEach(x=>x.classList.remove('sel'));c.classList.add('sel');openDay(c.dataset.d);});
}

// ---- trades, daily, breakdown, signals, config
function renderTrades(T,LOT){
  const cbTip=cb=>['Brokerage '+inr(cb.brokerage),'STT '+inr(cb.stt),'Exchange '+inr(cb.exchange),'SEBI '+inr(cb.sebi),'Stamp '+inr(cb.stamp),'GST '+inr(cb.gst)].join('&#10;');
  const und=cur.variant==='OPT_FUT_SIGNAL',opt=cur.variant!=='FUT',lotc=T.some(t=>t.lots>1||t.tranche);let cum=0;
  const expD=e=>e?new Date(e+'T00:00:00Z').toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'2-digit',timeZone:'UTC'}):'—';
  const inst=t=>opt?`<td>${expD(t.exp)}</td><td class="num" title="${esc(t.instr)}${t.scan?' · picked by the '+t.scan+' scan':''}">${t.strike!=null?Math.round(t.strike):'—'}${t.scan?' <span class="sub">'+t.scan+'</span>':''}</td><td>${t.otype}</td>`:`<td>${t.instr}</td>`;
  $('ttrades').innerHTML=`<thead><tr><th>#</th><th>Position</th>${opt?'<th>Expiry</th><th class="num">Strike</th><th>CE/PE</th>':'<th>Instrument</th>'}<th>Signal</th><th>${opt?'Option entry':'Entry'}</th><th class="num">SL${und?' (fut)':opt?' (option)':''}</th><th>${opt?'Option exit':'Exit'}</th><th>Reason</th>${und?'<th class="num">Fut in → out</th>':''}${lotc?'<th class="num">Lots</th>':''}<th class="num">Max profit</th><th class="num">Max loss</th><th class="num">Points</th><th class="num">Gross ₹</th><th class="num">Charges ₹</th><th class="num">Net ₹</th><th class="num">Cum. net ₹</th></tr></thead><tbody>`+
    T.map((t,i)=>{cum+=t.net;return `<tr class="z" data-a="${t.ets}" data-b="${t.xts}"><td>${i+1}</td><td><span class="pill ${t.pos==='LONG'?'long':'short'}">${t.pos}</span></td>${inst(t).replace(/<\/td>$/,(t.stale?' <span class="pill open" title="price from an earlier candle the same day">stale</span>':'')+'</td>')}<td>${sigName(t)}</td><td>${t.et.slice(5,16)} @ ${t.ep}</td><td class="num">${t.sl??'—'}</td><td>${t.xt.slice(5,16)} @ ${t.xp}</td><td><span class="pill ${t.why==='stop_loss'?'short':t.open?'open':'grey'}">${WHY[t.why]||t.why}</span></td>${und?`<td class="num">${t.ue} → ${t.ux}</td>`:''}${lotc?`<td class="num" title="${esc(t.tranche)}">${t.lots}${t.tranche?' · '+esc(t.tranche):''}</td>`:''}<td class="num pos" title="${inr(t.mfe*LOT)} per lot">${fmt(t.mfe)}</td><td class="num neg" title="${inr(t.mae*LOT)} per lot">${fmt(t.mae)}</td><td class="num ${cl(t.pts)}">${fmt(t.pts)}</td><td class="num ${cl(t.pts)}">${inr(t.gross)}</td><td class="num neg" title="${cbTip(t.cb)}">${inr(-t.chg)}</td><td class="num ${cl(t.net)}">${inr(t.net)}${t.open?'<span class="warn" title="open at the backtest end, valued at its last candle">*</span>':''}</td><td class="num ${cl(cum)}">${inr(cum)}</td></tr>`;}).join('')+'</tbody>';
  const op=T.filter(t=>t.open);
  $('opennote').innerHTML=op.length?`<div class="note"><b>*</b> ${op.length} position${op.length>1?'s':''} still open at the backtest end, valued at the last available candle: `+op.map(t=>`${t.pos.toLowerCase()} ${t.instr} from ${t.et.slice(5,16)} → ${t.xt.slice(5,16)} ${inr(t.net)}`).join(' · ')+'</div>':'';
  const nLock=D.skipped.filter(x=>String(x.why||'').startsWith('strike locked')).length,nData=D.skipped.length-nLock;
  $('skipped').innerHTML=D.skipped.length?`${D.skipped.length} position(s) not taken`+(nData?` · ${nData} without option data`:'')+(nLock?` · ${nLock} because the strike already had an open position (strike lock)`:'')+': '+D.skipped.slice(0,8).map(x=>`${(x.entry_time||'').slice(5,16)} — ${x.why}`).join(' · ')+(D.skipped.length>8?' …':''):'';
  document.querySelectorAll('#ttrades tr.z').forEach(r=>r.onclick=()=>openTrade(+r.dataset.a,+r.dataset.b));
}
function renderDaily(T){const byDay={};T.forEach(t=>(byDay[t.xt.slice(0,10)]??=[]).push(t));let dc=0;
  $('tdaily').innerHTML='<thead><tr><th>Day</th><th class="num">Trades</th><th class="num">Long ₹</th><th class="num">Short ₹</th><th class="num">Net ₹</th><th class="num">Cum. net ₹</th></tr></thead><tbody>'+
    Object.keys(byDay).sort().map(d=>{const a=byDay[d],nt=sum(a,t=>t.net),lg=sum(a.filter(t=>t.pos==='LONG'),t=>t.net),sh=sum(a.filter(t=>t.pos==='SHORT'),t=>t.net);dc+=nt;
      return `<tr class="z" data-d="${d}"><td>${d}</td><td class="num">${a.length}</td><td class="num ${cl(lg)}">${inr(lg)}</td><td class="num ${cl(sh)}">${inr(sh)}</td><td class="num ${cl(nt)}">${inr(nt)}</td><td class="num ${cl(dc)}">${inr(dc)}</td></tr>`;}).join('')+'</tbody>';
  document.querySelectorAll('#tdaily tr.z').forEach(r=>r.onclick=()=>openDay(r.dataset.d));}
function renderBreakdown(T){
  const grp=(title,keyOf)=>{const g={};T.forEach(t=>(g[keyOf(t)]??=[]).push(t));
    return `<div class="card mt"><h3>${title}</h3><table><thead><tr><th></th><th class="num">Trades</th><th class="num">Win %</th><th class="num">Net ₹</th><th class="num">Avg ₹</th><th class="num">Avg max profit</th><th class="num">Avg max loss</th></tr></thead><tbody>`+
    Object.keys(g).sort().map(k=>{const a=g[k],n=sum(a,t=>t.net);return `<tr><td>${k}</td><td class="num">${a.length}</td><td class="num">${Math.round(100*a.filter(t=>t.net>0).length/a.length)}%</td><td class="num ${cl(n)}">${inr(n)}</td><td class="num ${cl(n)}">${inr(n/a.length)}</td><td class="num pos">${fmt(sum(a,t=>t.mfe)/a.length)}</td><td class="num neg">${fmt(sum(a,t=>t.mae)/a.length)}</td></tr>`;}).join('')+'</tbody></table></div>';};
  $('p-bdown').innerHTML=`<div class="grid2">${grp('By position',t=>t.pos==='LONG'?'Long':'Short')}${grp('By signal',sigName)}${grp('By instrument',t=>t.otype)}${grp('By exit reason',t=>({stop_loss:'Stop loss',next_choch:'Next CHoCH',expiry:'Expiry',open:'Open at end',band_reclaim:'Band reclaim',trail_stop:'Trail stop'})[t.why]||t.why)}${grp('By entry time',t=>{const hm=t.et.slice(11,16);return hm<'10:30'?'09:15–10:30':hm<'12:00'?'10:30–12:00':hm<'13:30'?'12:00–13:30':'13:30–15:30';})}${grp('By holding',t=>t.et.slice(0,10)===t.xt.slice(0,10)?'Intraday':'Overnight')}</div>`;}
function renderSignals(){
  const F=D.fz,fr=new Map(),GP={TAKE:'long',REENTER:'long',WATCH:'grey',BLOCK:'short'};   // FZ: the card's read and the gate, joined on the SETUP time
  if(F){const {cols,rows}=F.ledger,[iT,iR,iG,iOG]=['time','read','gate','outcome_gate'].map(k=>cols.indexOf(k));rows.forEach(x=>fr.set(x[iT],[x[iR],x[iG],iOG>=0?x[iOG]:x[iG]]));}
  // the gate the SETUP ended with (a WATCH whose watch later re-entered on it reads REENTER), the gate at its bar in the title
  const fzc=g=>{if(!F)return '';const z=g.setup&&fr.get(g.setup);return z?`<td>${z[0]}</td><td title="gate at the SETUP bar: ${z[1]}"><span class="pill ${GP[z[2]]||'grey'}">${z[2]}</span></td>`:'<td></td><td></td>';};
  $('sighint').textContent=D.signals.length?'Every CHoCH on the futures chart, the AVWAP pair it started, and the SETUP that followed.'+(F?' Read and Gate: the FZ card at that SETUP and what the gate did (details in the Zone gate tab).':''):'Options (standalone): the signals are on each day\'s option chart — pick it in the session list above the chart.';
  $('tsignals').innerHTML=D.signals.length?`<thead><tr><th>CHoCH</th><th>Direction</th><th class="num">Protected</th><th>AVWAP from SH</th><th>AVWAP from SL</th><th>SETUP</th>${F?'<th>Read</th><th>Gate</th>':''}</tr></thead><tbody>`+
    D.signals.map(g=>`<tr><td>${g.time.slice(5,16)}</td><td><span class="pill ${g.dir==='up'?'long':'short'}">${g.dir==='up'?'future long':'future short'}</span></td><td class="num">${g.lvl}</td><td>${g.hi?g.hi[0].slice(5,16)+' @ '+g.hi[1]:'—'}</td><td>${g.lo?g.lo[0].slice(5,16)+' @ '+g.lo[1]:'—'}</td><td>${g.setup?g.setup.slice(5,16):'<span class="pill grey">none</span>'}</td>${fzc(g)}</tr>`).join('')+'</tbody>':'';}
function renderConfig(){const m=cur,r=runOf(m),sch=D.charges,labs={code:'Code',holding:'Holding',break_mode:'Break mode (swings, BOS)',choch_mode:'CHoCH mode',avwap_weight:'AVWAP weight',sl_rule:'Stop-loss rule',warmup_days:'Warm-up (sessions)',slippage_pts:'Slippage (pts/side)',lot_size:'Lot size',capital_fut:'Futures margin / lot (₹)',capital_opt_short:'Short option margin / lot (₹)',charge_code:'Charge schedule'};
  $('cfg').innerHTML=`<dt>Showing</dt><dd>${m.name} · ${SCH[schemeOf(m)]}${m.variant!=='FUT'?` · ${EXP[ck(curChoice)[0]]} · strike ${ck(curChoice)[1]}`:''}</dd><dt>Backtest</dt><dd>${r.label} · ${r.date_from} → ${r.date_to} · ${TFS[r.timeframe]}${r.design?' (design timeframe)':''}</dd>`+
    Object.entries(labs).map(([k,v])=>`<dt>${v}</dt><dd>${k==='holding'?(HOLD(r)||HOLD0(m)):m[k]??'—'}</dd>`).join('')+
    `<dt>Brokerage</dt><dd>${sch.brokerage_flat?'₹'+sch.brokerage_flat+' flat per order':sch.brokerage_pct+'% or ₹'+sch.brokerage_cap+' per order'}</dd><dt>STT</dt><dd>${sch.stt_buy_pct}% buy · ${sch.stt_sell_pct}% sell</dd><dt>Exchange</dt><dd>${sch.exchange_pct}%</dd><dt>Stamp</dt><dd>${sch.stamp_buy_pct}% buy</dd><dt>GST</dt><dd>${sch.gst_pct}%</dd><dt>Note</dt><dd>${sch.notes}</dd>`+fzConfig(m,r);}
// FZ rows: every threshold of this timeframe's fz block as the strategy file states it, with its provenance
function fzConfig(m,r){let b=null;try{b=m.fz_json?JSON.parse(m.fz_json)[r.timeframe]:null;}catch(e){}if(!b)return '';
  return `<dt style="margin-top:10px"><b>Foundation-Zone</b></dt><dd style="margin-top:10px">entry rule ${esc(m.entry_rule)} · fz_hash ${esc(m.fz_hash||'—')} · band memory from ${esc(r.memory_start||'—')} (${esc(r.same_sample||'')}: every window is a date slice of one run from the file start) · thresholds for ${TFS[r.timeframe]} candles</dd>`+
    Object.entries(b).map(([k,x])=>`<dt>${esc(k)}</dt><dd>${x.value===null?'null':esc(x.value)} <span class="sub">· ${esc(x.source)}${x.statistic?' · '+esc(x.statistic):''}${x.note?' · '+esc(x.note):''}</span></dd>`).join('');}

// ---- Zone gate (Strategies 5-6): the gate ledger and its reports, all precomputed by lab.py into summary.json['fz']
let FZG='ALL';   // ledger filter: ALL or one gate
function renderFZ(){
  const F=D&&D.fz,el=$('p-fz');
  if(!F){el.innerHTML='<p class="hint">Not an FZ strategy. The Zone gate belongs to Strategies 5 to 8, which card every Foundation SETUP against a memory of price bands and gate it TAKE / WATCH / BLOCK, with REENTER after a confirmed leave of the band.</p>';return;}
  const s=F.stats,c=F.control,pm=F.permutation,fl=F.flags,w=s.watches||{},p=s.positions||{},r=runOf(cur),GT=['TAKE','REENTER','WATCH','BLOCK'];
  const kv=o=>Object.entries(o||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`${k} ${v}`).join(' · ')||'—';
  const ord=(o,ks)=>ks.filter(k=>o&&o[k]!=null).map(k=>`${k} ${o[k]}`).join(' · ')||'—';
  const money=v=>[inr(v),cl(v)];
  const td=(x,i)=>Array.isArray(x)?`<td class="${i?'num ':''}${x[1]||''}"${x[2]?` title="${esc(x[2])}"`:''}>${x[0]??'—'}</td>`:`<td${i?' class="num"':''}>${x??'—'}</td>`;
  const card=(title,head,rows,hint)=>`<div class="card mt"><h3>${title}</h3>${hint?`<p class="hint">${hint}</p>`:''}<div class="scroll"><table>${head?`<thead><tr>${head.map((x,i)=>`<th${i?' class="num"':''}>${x}</th>`).join('')}</tr></thead>`:''}<tbody>${rows.map(rw=>`<tr>${rw.map(td).join('')}</tr>`).join('')}</tbody></table></div></div>`;
  const by=(title,o,keys)=>card(title,['',...GT,'All'],(keys||Object.keys(o||{})).filter(k=>o&&o[k]).map(k=>[esc(k),...GT.map(g=>o[k][g]||''),Object.values(o[k]).reduce((a,b)=>a+b,0)]));
  // headline tiles: the control percentile always sits beside net (cost avoidance is not edge)
  const B=F.books||{},bf=B.fz||{},bw=B.raw||{},h=F.headline||{};
  // SETUPs by how they ended (a WATCH whose watch later re-entered on it counts REENTER); at_setup = the gate at the SETUP bar
  const ats=h.at_setup;
  const tiles=[['Foundation SETUPs',s.setups,`ended TAKE ${h.take} · WATCH ${h.watch} · BLOCK ${h.block} · REENTER ${h.reenter}${ats?` (${ats.REENTER} of them at the SETUP bar)`:''}`,''],
    ['FZ positions',`${h.take_trades} + ${h.reenter_trades}`,`TAKE + REENTER · ${h.priced} priced`,''],
    ['FZ net',inr(bf.net),`Foundation ${inr(bw.net)} in the same run`,cl(bf.net)],
    ['Random control',c.fz_pct!=null?c.fz_pct.toFixed(1)+'th pct':'—',`session-matched · ${c.draws} draws`,''],
    ['Kept vs refused',pm.p!=null?'p '+pm.p:'—',`mean <span class="${cl(pm.kept_mean)}">${inr(pm.kept_mean)}</span> vs <span class="${cl(pm.blocked_mean)}">${inr(pm.blocked_mean)}</span>`,''],
    ['Sample',fl.pf_t,`n ${fl.n}${fl.ci_inr!=null?` · 95% CI ±${inr(fl.ci_inr)}`:''}`,'']]
    .map(([l,v,sub,k])=>`<div class="card kpi"><div class="l">${l}</div><div class="v ${k}">${v}</div><div class="s">${sub}</div></div>`).join('');
  // gate x read: rows are SETUPs; BLOCK split by reason
  const reads=F.legend.read.filter(x=>GT.some(g=>(s.gate_read[g]||{})[x])),grow=(lbl,o,n)=>[lbl,...reads.map(x=>(o||{})[x]||''),n];
  const gr=[...['TAKE','REENTER','WATCH'].map(g=>grow(g,s.gate_read[g],s.gates[g]||0)),
    ...Object.entries(s.block_read||{}).map(([k,o])=>grow('BLOCK · '+k,o,Object.values(o).reduce((a,b)=>a+b,0))),grow('<b>All SETUPs</b>',s.reads_at_setup,s.setups)];
  const sb=p.reenter_sl_bar||{},ls=(s.r4||{}).leave_setups||{},r4=s.r4||{},na=F.all_na||{},lf=s.leave_far_side||{},b1=s.branch1||{},br=F.bridge||{lines:[]},cd=s.card||{},sm=cd.since_memory_start||{};
  const cells=[
    card('Watches',['Outcome','Watches'],Object.entries(w.outcomes||{}).sort((a,b)=>b[1]-a[1]),
      `${w.opened??0} opened (${kv(w.kinds)}); ${w.armed??0} armed${w.rearmed!=null?`, ${w.rearmed} re-armed (a close back inside breaks the far-side run; the next far close arms again)`:''}. Armed watches that expired: median ${w.armed_bars_median??'—'} bars from the first arming${w.rearmed_bars_median!=null?`, ${w.rearmed_bars_median} from the latest`:''}. Ended armed with R1–R4 met but no same-direction SETUP: ${w.no_same_dir_setup??0}. REENTER held by the ${F.thresholds.no_entry_from} clock: ${w.clock_1520??0}. Refused at the fill: ${w.reenter_refused??0}.`),
    card('Positions',null,[["TAKE (Foundation's own position)",p.TAKE],['REENTER',p.REENTER],...Object.entries(p.reenter_exits||{}).map(([k,v])=>['REENTER exit · '+k,v]),
      ...Object.entries(p.reenter_fill||{}).map(([k,v])=>['REENTER fill · '+k,v]),['REENTER stop from the SETUP / fill bar',`${sb.setup||0} / ${sb.fill||0}`],['REENTER stop inside the band',p.reenter_sl_in_band],
      ['LEAVE TAKE turned REENTER (a watch waited on the band left, same way)',p.reenter_converted_take],['TAKE refused (stop)',p.take_refused]]),
    card('LEAVE into another band (TAKE branch 1)',['leave_far_side','Branch-1 TAKEs'],['any','block_list','no_band'].map(k=>[k===lf.seeded?`<b>${k}</b> (seeded)`:k,lf[k]]),
      `What each reading of a leave whose far side is another remembered band would TAKE on these rows (counted from the ledger's entered read; only the seeded one gated). Seeded branch-1 TAKEs ${b1.n??0}: far side in no band ${b1.far_side_no_band??0}, inside a band ${b1.far_side_in_band??0} (entered visit_n median ${b1.in_band_visit_n_median??'—'}; by visit ${kv(b1.in_band_visit_n)}; entered read ${kv(b1.in_band_entered_read)}).`),
    card('Volume NA and R4',null,[['SETUPs whose visit volume is NA',`${s.vol_na} of ${s.setups}`],["SETUPs whose band's first visit is NA",s.first_vol_na],['ACCEPTED on time alone (volume NA)',s.accepted_time_only],
      ['R4 far-side bars evaluated / failed / NA',`${r4.bars_evaluated??0} / ${r4.bars_fail??0} / ${r4.bars_na??0}`],['LEAVE SETUPs by R4: NA / pass / fail',`${ls.none||0} / ${ls.true||0} / ${ls.false||0}`]],
      `A bar is volume-NA when the file is not on the front month or its volume is 0; a visit is NA if any of its bars is. NA skips R4, the HUNT burst and THIN, and makes ACCEPTED time-only. All-NA comparator (volume NA on every bar, the like-for-like read across volume regimes): SETUPs by the gate they ended with ${ord(na.gates,GT)}; positions ${ord(na.positions,['TAKE','REENTER'])}.`),
    card('Bridge: Foundation to FZ net',['','n','₹'],br.lines.map(l=>[['raw_net','fz_net'].includes(l.key)?`<b>${l.label}</b>`:l.label,l.n,money(l.value)]),
      `Foundation's net in this same run, plus what FZ avoided by not holding its other positions (their price move, then their charges and slippage), plus the REENTER exit difference, equals FZ net. Price lines <span class="${cl(br.selection)}">${inr(br.selection)}</span>, cost avoidance <span class="${cl(br.costs)}">${inr(br.costs)}</span>: with a losing Foundation book any gate that drops trades gains the costs, so judge the selection by the random control.`),
    card('Random control and kept vs refused',null,[['Random books (session-matched)',`${c.draws} × ${c.k} positions`],['Random net · 5th percentile',money(c.p5)],['Random net · median',money(c.p50)],['Random net · 95th percentile',money(c.p95)],
      ['FZ net',money(c.fz_net)],['FZ percentile among the random books',c.fz_pct!=null?c.fz_pct.toFixed(1)+'th':'—'],['Random books that beat FZ',c.p_beat!=null?pct(c.p_beat):'—'],
      ['Kept: Foundation trades on the SETUPs FZ traded (TAKE, or a REENTER on that SETUP)',pm.kept_n],['Kept · mean',money(pm.kept_mean)],['Refused: Foundation trades on the SETUPs FZ never traded',pm.blocked_n],['Refused · mean',money(pm.blocked_mean)],['Difference of means',money(pm.diff)],['Permutation p (two-sided)',pm.p??'—']],
      `${esc(c.scheme)}; seed ${esc(c.seed)}${c.capped?`; ${c.capped} positions capped`:''}. The permutation shuffles the kept / refused labels ${pm.draws} times.`),
    card('Books and sample size',['','FZ','Foundation'],[['Positions',bf.n,bw.n],['Net',money(bf.net),money(bw.net)],['Net without positions open at the end',money(bf.net_ex_open),money(bw.net_ex_open)],
      ['Mean per position',money(bf.mean),money(bw.mean)],['SD per position',inr(bf.sd),inr(bw.sd)],['Wins',bf.wins,bw.wins],
      ...[['Profit factor','pf'],['t per position','t_trade'],['t per active session','t_session']].map(([l,k])=>[l,fl.pf_t==='not reported'?'not reported':bf[k],bw[k]]),
      ['Sessions / weeks with a position',`${bf.sessions} / ${bf.weeks}`,`${bw.sessions} / ${bw.weeks}`],['Open at the end',bf.open,bw.open],
      ['95% CI on the mean (₹ · pts)',bf.ci_inr!=null?`±${inr(bf.ci_inr)} · ±${bf.ci_pts}`:'—',bw.ci_inr!=null?`±${inr(bw.ci_inr)} · ±${bw.ci_pts}`:'—']],
      `Sample flags for the FZ book: PF / t ${fl.pf_t}, week stats ${fl.weeks}, Sharpe / Calmar ${fl.sharpe}. ${esc(fl.rule)}.`),
    card('Active sessions and dormant stretches',['No Foundation SETUP','Sessions'],(s.dormant||[]).map(([a,b,n])=>[a===b?a:`${a} → ${b}`,n]),
      `Sessions with at least one Foundation SETUP: ${s.active_sessions} of ${s.sessions}. A dormant stretch is Foundation's silence, not FZ's selectivity.`),
    by('Gate by hour (bar open time)',s.by_hour,F.legend.hour_bins),by('Gate by visit_n',s.by_visit,['1','2','3','4+','none']),by('Gate by direction',s.by_dir,['up','down']),
    by('Gate by zone kind (A protected level · B cluster sit)',s.by_zone_kind,['A','B','none']),
    card('The card on every shown bar',null,[['Bars',cd.bars],['Closing inside a band',cd.inside_pct+'%'],['With a live visit',cd.ref_live_pct+'%'],['Bands since the memory start',cd.zones_since_memory_start],
      ['Born A / B (B by drift)',`${sm.births_A} / ${sm.births_B} (${sm.births_B_drift})`],['Born in this window A / B',`${(cd.births_in_window||{}).A??0} / ${(cd.births_in_window||{}).B??0}`],['Merged candidates A / B',`${sm.merges_A} / ${sm.merges_B}`],['visit_n at SETUP, median',s.visit_n_median],
      ['Closes back inside the band just left while another band holds the visit (no new visit on it)',cd.leave_return_no_visit??'—']],
      `Reads by bar (%): ${F.legend.read.filter(x=>(cd.reads||{})[x]!=null).map(x=>`${x} ${cd.reads[x]}`).join(' · ')}. Reads at SETUP: ${kv(s.reads_at_setup)}.`)];
  // the ledger: one row per Foundation SETUP; a click opens the chart at it
  const L=F.ledger,ix=Object.fromEntries(L.cols.map((k,i)=>[k,i])),g=(rw,k)=>rw[ix[k]],tsOf=x=>Date.parse(x.replace(' ','T')+'Z')/1000,zn=id=>!id?'—':/^[AB]\d{4}-/.test(id)?id[0]+id.slice(6,17):id;
  const ratio=rw=>!g(rw,'vol_na')&&!g(rw,'first_vol_na')&&g(rw,'this_vol')!=null&&g(rw,'first_vol')?(g(rw,'this_vol')/g(rw,'first_vol')).toFixed(2):'NA';
  // og = the gate the SETUP ended with (ledgers built before outcome_gate existed fall back to the gate at the SETUP bar)
  const og=rw=>ix.outcome_gate!=null?g(rw,'outcome_gate'):g(rw,'gate');
  const GP={TAKE:'long',REENTER:'long',WATCH:'grey',BLOCK:'short'},rows=L.rows.filter(rw=>FZG==='ALL'||og(rw)===FZG);
  const seg=`<span class="seg sm" id="fzSeg">${['ALL',...GT].map(k=>`<button data-g="${k}" class="${FZG===k?'on':''}">${k==='ALL'?'All':k}<small>${k==='ALL'?L.rows.length:(s.gates[k]||0)}</small></button>`).join('')}</span>`;
  const lrow=(rw,i)=>{const t=g(rw,'time'),fp=g(rw,'fnd_pts'),zp=g(rw,'fz_pts'),x=g(rw,'fz_exit_time')||g(rw,'fnd_exit_time')||t,wk=g(rw,'watch_kind');
    return `<tr class="z" data-a="${tsOf(t)}" data-b="${tsOf(x)}"><td>${i+1}</td><td>${t.slice(5,16)}</td><td><span class="pill ${g(rw,'dir')==='up'?'long':'short'}">${g(rw,'dir')}</span></td>`+
      `<td title="${esc(g(rw,'zone_id')||'')}${g(rw,'band_lo')!=null?` · ${g(rw,'band_lo')}–${g(rw,'band_hi')}`:''}">${zn(g(rw,'zone_id'))}</td><td>${g(rw,'zone_kind')||'—'}</td><td class="num">${g(rw,'visit_n')??'—'}</td>`+
      `<td class="num">${g(rw,'this_bars')??'—'} / ${g(rw,'first_bars')??'—'}</td><td class="num">${ratio(rw)}</td><td>${g(rw,'read')||'—'}</td><td><span class="pill ${GP[og(rw)]||'grey'}">${og(rw)}</span>${og(rw)!==g(rw,'gate')?` <small class="sub">${g(rw,'gate')} at the SETUP bar</small>`:''}</td>`+
      `<td>${g(rw,'block_reason')||g(rw,'take_why')||''}${g(rw,'refused')?' · refused '+g(rw,'refused'):''}</td><td>${g(rw,'branch')||''}</td>`+
      `<td title="${esc(g(rw,'entered_zone_id')||'')}">${g(rw,'entered_read')?`${g(rw,'entered_read')} (v${g(rw,'entered_visit_n')})`:''}</td>`+
      `<td>${wk?`${wk==='WATCH_EDGE'?'edge':'watch'} → ${g(rw,'watch_outcome')||'active'}`:''}</td>`+
      `<td title="${g(rw,'fill_time')?esc(`fill ${g(rw,'fill_time')} · ${g(rw,'edge_dist_pts')??'—'} pts beyond the edge · armed ${g(rw,'armed_bars')??'—'} bars${g(rw,'rearmed_bars')!=null&&g(rw,'rearmed_bars')!==g(rw,'armed_bars')?` (${g(rw,'rearmed_bars')} since it re-armed)`:''} · stop from the ${g(rw,'sl_bar')||'—'} bar`):''}">${g(rw,'fill_used')?`${g(rw,'fill_used')}${g(rw,'fill_delay_bars')?' +'+g(rw,'fill_delay_bars'):''}`:''}</td>`+
      `<td class="num ${cl(fp)}" title="${esc(fp==null?'':`${g(rw,'fnd_exit_reason')} ${g(rw,'fnd_exit_time')} · ${inr(g(rw,'fnd_net'))}`)}">${fp==null?'—':fmt(fp)}</td>`+
      `<td class="num ${cl(zp)}" title="${esc(g(rw,'fz_kind')?`${g(rw,'fz_kind')} · ${g(rw,'fz_exit_reason')} ${g(rw,'fz_exit_time')} · ${inr(g(rw,'fz_net'))}`:'')}">${zp==null?'—':fmt(zp)}</td></tr>`;};
  el.innerHTML=`<p class="hint">Every Foundation SETUP of this backtest, carded against the band memory from ${F.memory_start} (the file's first session; the window starts ${F.window_start}) and gated. ${r.notes?'Backtest: '+esc(r.notes)+'. ':''}${esc(F.legend.units)}.</p>`+
    `<div class="kpis">${tiles}</div>`+
    card('Gate × read',['',...reads,'SETUPs'],gr,`Rows are Foundation SETUPs by the gate they ended with and the card's read at the SETUP bar; BLOCK is split by reason. A WATCH whose watch later re-entered on this SETUP counts as REENTER${s.gates_at_setup?` (gate at the SETUP bar: ${ord(s.gates_at_setup,GT)})`:''}. WATCH at the SETUP bar after a LEAVE into a RECYCLE / THIN / HUNT / REJECT band: ${kv(s.watch_reason)}. Not a TAKE because: ${kv(s.take_why)}. Branches: TAKE ${kv((s.branches||{}).TAKE)}; REENTER ${kv((s.branches||{}).REENTER)}.`)+
    `<div class="grid2">${cells.join('')}</div>`+
    `<div class="card mt" style="margin-top:12px"><h3>Gate ledger ${seg}</h3><p class="hint">One row per Foundation SETUP (skipped ones included). Hover the zone, entered read, fill and points for detail; click a row to open it on the chart. Foundation pts = what Foundation's own position on this SETUP did; FZ pts = the FZ position this SETUP opened (TAKE, or REENTER after its watch).</p>`+
    `<div class="scroll"><table><thead><tr><th>#</th><th>SETUP</th><th>Dir</th><th>Zone</th><th>Kind</th><th class="num">Visit</th><th class="num">This / first bars</th><th class="num">Vol ratio</th><th>Read</th><th>Gate</th><th>Reason</th><th>Branch</th><th>Entered</th><th>Watch</th><th>Fill</th><th class="num">Foundation pts</th><th class="num">FZ pts</th></tr></thead><tbody>${rows.map(lrow).join('')}</tbody></table></div></div>`;
  el.querySelectorAll('#fzSeg button').forEach(b=>b.onclick=()=>{FZG=b.dataset.g;renderFZ();});
  el.querySelectorAll('tr.z').forEach(tr=>tr.onclick=()=>openAt(+tr.dataset.a,+tr.dataset.b));
}

// ---- performance scorecard
function dailySeries(T){const sess=sessionsOf(),by={};T.forEach(t=>{const d=t.xt.slice(0,10);by[d]=(by[d]||0)+t.net;});return sess.map(d=>by[d]||0);}
function streaks(T){let w=0,l=0,mw=0,ml=0;for(const t of T){if(t.net>0){w++;l=0;}else{l++;w=0;}mw=Math.max(mw,w);ml=Math.max(ml,l);}return [mw,ml];}
function renderPerf(T){
  const s=statsOf(T),m=cur,sess=sessionsOf(),dly=dailySeries(T),n=dly.length,mean=n?dly.reduce((a,b)=>a+b,0)/n:0;
  const sd=n>1?Math.sqrt(dly.reduce((a,v)=>a+(v-mean)**2,0)/(n-1)):0,dsd=n>1?Math.sqrt(dly.reduce((a,v)=>a+Math.min(v,0)**2,0)/(n-1)):0;
  const {cap,how}=capitalFor(T),yrs=n/252,annual=yrs?s.net_inr/yrs:0;
  const W=T.filter(t=>t.net>0),L=T.filter(t=>t.net<=0),aw=W.length?sum(W,t=>t.net)/W.length:0,al=L.length?sum(L,t=>t.net)/L.length:0,[mw,ml]=streaks(T);
  const mins=T.map(t=>tradeMin(t,sess)),inMkt=sum(mins,x=>x)/(n*375||1);
  const share=k=>{const g={};T.forEach(t=>{const key=k(t.xt);g[key]=(g[key]||0)+t.net;});const v=Object.values(g);return v.length?`${v.filter(x=>x>0).length} of ${v.length} (${Math.round(100*v.filter(x=>x>0).length/v.length)}%)`:'—';};
  const wkKey=x=>{const d=new Date(x.slice(0,10)+'T00:00:00Z'),y=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate()+4-(d.getUTCDay()||7)));return y.getUTCFullYear()+'-'+Math.ceil(((y-new Date(Date.UTC(y.getUTCFullYear(),0,1)))/864e5+1)/7);};
  const exR=T.map(t=>{const rp=riskPts(t);return rp?t.pts/rp:null;}).filter(v=>v!=null);
  const slipCost=2*m.slippage_pts*m.lot_size*T.length;
  const tbl=(h,rows)=>`<div class="card mt"><h3>${h}</h3><table>${rows.map(([k,v,c])=>`<tr><td>${k}</td><td class="num ${c||''}">${v}</td></tr>`).join('')}</table></div>`;
  $('p-perf').innerHTML=(T.length<50?`<div class="note">Only ${T.length} trades — treat these ratios as indicative; a few trades move them a lot.</div>`:'')+`<div class="grid2">`+
    tbl('Returns',[['Net P&L',inr(s.net_inr),cl(s.net_inr)],['Gross P&L',inr(s.gross_inr),cl(s.gross_inr)],['Charges',inr(-s.charges_inr),'neg'],['Slippage cost (already in P&L)',inr(-slipCost),'neg'],
      ['Capital basis',how],['Return on capital',cap?pct(s.net_inr/cap):'—',cl(s.net_inr)],['Annualised return',cap&&yrs?pct(annual/cap):'—',cl(annual)],['Sessions in backtest',n]])+
    tbl('Risk-adjusted',[['Sharpe (daily, annualised)',sd?(mean/sd*Math.sqrt(252)).toFixed(2):'—'],['Sortino',dsd?(mean/dsd*Math.sqrt(252)).toFixed(2):'—'],['Calmar (annual ÷ max drawdown)',s.max_dd_inr<0?(annual/-s.max_dd_inr).toFixed(2):'—'],
      ['Max drawdown',inr(s.max_dd_inr),'neg'],['Max drawdown / capital',cap?pct(s.max_dd_inr/cap):'—','neg'],['t-stat (per trade)',s.t_stat??'—'],['Daily P&L volatility',inr(sd)]])+
    tbl('Trades',[['Expectancy',inr(s.mean),cl(s.mean)],['Expectancy in R',exR.length?fmt(exR.reduce((a,b)=>a+b,0)/exR.length,2)+' R':'— (stop is on the futures)'],['Win rate',s.trades?pct(s.wins/s.trades):'—'],
      ['Average win / loss',`${inr(aw)} / ${inr(al)}`],['Payoff ratio (avg win ÷ avg loss)',al?(aw/-al).toFixed(2):'—'],['Profit factor',s.pf??'—'],['Largest win',inr(Math.max(0,...T.map(t=>t.net))),'pos'],['Largest loss',inr(Math.min(0,...T.map(t=>t.net))),'neg']])+
    tbl('Streaks, time, consistency',[['Longest winning streak',mw+' trades'],['Longest losing streak',ml+' trades'],['Average holding time',T.length?`${Math.round(sum(mins,x=>x)/T.length)} trading min`:'—'],
      ['Time in market',pct(inMkt)],['Profitable days',share(x=>x.slice(0,10))],['Profitable weeks',share(wkKey)],['Profitable months',share(x=>x.slice(0,7))]])+`</div>`;
}

// ---- cumulative P&L + drawdown curve
function mkChart(el,opt={}){return LightweightCharts.createChart(el,Object.assign({autoSize:true,layout:{background:{color:'#fff'},textColor:'#4b5563',fontFamily:'system-ui'},
  grid:{vertLines:{color:'#f3f4f6'},horzLines:{color:'#f3f4f6'}},rightPriceScale:{borderColor:'#e6e8ec'},timeScale:{timeVisible:true,borderColor:'#e6e8ec'},
  handleScroll:{mouseWheel:false},handleScale:{mouseWheel:false},localization:{timeFormatter:t=>iso(t).slice(5,16).replace('T',' '),priceFormatter:v=>inr(v)}},opt));}
const curve=rs=>{const agg=new Map();rs.forEach(t=>agg.set(t.xts,(agg.get(t.xts)||0)+t.net));let c=0;return [...agg.keys()].sort((a,b)=>a-b).map(x=>({time:x,value:Math.round(c+=agg.get(x))}));};
function renderEquity(T){
  if(eqch){eqch.remove();eqch=null;}if(uwch){uwch.remove();uwch=null;}
  eqch=mkChart($('eq'));uwch=mkChart($('uw'));
  const lines=[['Total',T,'#111',2],['Long',T.filter(t=>t.pos==='LONG'),'#089981',1],['Short',T.filter(t=>t.pos==='SHORT'),'#f23645',1]].filter(x=>x[1].length);
  const leg=lines.map(([n,rs,c,w])=>{const d=curve(rs);eqch.addLineSeries({color:c,lineWidth:w,priceLineVisible:false,title:n}).setData(d);return `<span style="color:${c}">━</span> ${n} <b class="${cl(d.length?d.at(-1).value:0)}">${inr(d.length?d.at(-1).value:0)}</b>`;});
  const d=curve(T);let pk=0;const uw=d.map(p=>{pk=Math.max(pk,p.value);return {time:p.time,value:p.value-pk};});
  uwch.addAreaSeries({lineColor:'#f23645',topColor:'rgba(242,54,69,.05)',bottomColor:'rgba(242,54,69,.35)',lineWidth:1,priceLineVisible:false,title:'Drawdown'}).setData(uw);
  eqch.timeScale().fitContent();uwch.timeScale().fitContent();
  $('eqhint').innerHTML=`Cumulative net P&L by exit time · ${SCH[schemeOf(cur)]} &nbsp; ${leg.join(' &nbsp; ')} &nbsp; · lower chart: drawdown from the running peak`;
}

// ---- drawdowns
function ddEpisodes(T){const d=curve(T),out=[];let pk=0,pkT=null,ep=null;
  for(const p of d){if(p.value>=pk){if(ep){ep.recovered=p.time;out.push(ep);ep=null;}pk=p.value;pkT=p.time;}
    else if(!ep)ep={start:pkT,bottom:p.time,depth:p.value-pk,recovered:null};else if(p.value-pk<ep.depth){ep.depth=p.value-pk;ep.bottom=p.time;}}
  if(ep)out.push(ep);return out.sort((a,b)=>a.depth-b.depth);}
function renderDD(T){const e=ddEpisodes(T).slice(0,5),sess=sessionsOf(),day=t=>t?iso(t).slice(0,10):null,dt=t=>t?iso(t).slice(0,16).replace('T',' '):'start';
  const len=(a,b)=>{const x=day(a)||sess[0],y=b?day(b):sess.at(-1);return sess.filter(d=>d>=x&&d<=y).length;};
  $('p-dd').innerHTML=`<p class="hint">The five deepest falls of cumulative net P&L from a previous peak (by trade exit).</p><div class="card scroll"><table><thead><tr><th>#</th><th>Peak</th><th>Bottom</th><th>Recovered</th><th class="num">Depth ₹</th><th class="num">Length (sessions)</th></tr></thead><tbody>`+
    (e.length?e.map((x,i)=>`<tr><td>${i+1}</td><td>${dt(x.start)}</td><td>${dt(x.bottom)}</td><td>${x.recovered?dt(x.recovered):'<span class="pill open">not yet</span>'}</td><td class="num neg">${inr(x.depth)}</td><td class="num">${len(x.start,x.recovered)}</td></tr>`).join(''):'<tr><td colspan="6" class="hint">No drawdown.</td></tr>')+'</tbody></table></div>';}

// ---- distribution (plain SVG)
function hist(vals,title,fmtX,bins=12){if(!vals.length)return `<div class="card mt"><h3>${title}</h3><p class="hint">No data.</p></div>`;
  const lo=Math.min(...vals),hi=Math.max(...vals),w=(hi-lo)/bins||1,c=Array(bins).fill(0);
  vals.forEach(v=>{c[Math.min(bins-1,Math.floor((v-lo)/w))]++;});
  const mx=Math.max(...c),W=340,H=150;
  return `<div class="card mt"><h3>${title}</h3><svg viewBox="0 0 ${W} ${H+24}" width="100%">`+c.map((n,i)=>{const x=i*W/bins,h=n/mx*H,mid=lo+(i+.5)*w;
    return `<rect x="${x+1}" y="${H-h}" width="${W/bins-2}" height="${h}" fill="${mid>=0?'#089981':'#f23645'}" opacity=".75"><title>${fmtX(lo+i*w)} to ${fmtX(lo+(i+1)*w)}: ${n}</title></rect>`;}).join('')+
    `<text x="0" y="${H+14}">${fmtX(lo)}</text><text x="${W}" y="${H+14}" text-anchor="end">${fmtX(hi)}</text></svg></div>`;}
function scatter(T){if(!T.length)return '';const W=340,H=200,x0=Math.min(-1,...T.map(t=>t.mae)),y1=Math.max(1,...T.map(t=>t.mfe)),px=v=>(v-x0)/(0-x0)*(W-30)+25,py=v=>H-v/y1*(H-10);
  return `<div class="card mt"><h3>Max profit vs max loss per trade</h3><p class="hint">x = worst the trade showed, y = best it showed (points). Green = closed in profit.</p><svg viewBox="0 0 ${W} ${H+20}" width="100%"><line x1="25" y1="${H}" x2="${W}" y2="${H}" stroke="#e6e8ec"/><line x1="${W-5}" y1="0" x2="${W-5}" y2="${H}" stroke="#e6e8ec"/>`+
    T.map(t=>`<circle cx="${px(t.mae)}" cy="${py(t.mfe)}" r="3" fill="${t.net>0?'#089981':'#f23645'}" opacity=".7"><title>${t.et.slice(5,16)} ${t.instr}: best +${t.mfe} / worst ${t.mae}, net ${inr(t.net)}</title></circle>`).join('')+
    `<text x="25" y="${H+14}">${x0.toFixed(0)} pts</text><text x="${W-5}" y="${H+14}" text-anchor="end">0</text><text x="${W-8}" y="10" text-anchor="end">+${y1.toFixed(0)}</text></svg></div>`;}
function renderDist(T){const sess=sessionsOf(),R=T.map(t=>{const rp=riskPts(t);return rp?t.pts/rp:null;}).filter(v=>v!=null);
  $('p-dist').innerHTML=`<div class="grid2">${hist(T.map(t=>t.net),'Net P&L per trade (₹)',v=>inrk(v))}${R.length?hist(R,'R-multiple per trade',v=>v.toFixed(1)+'R'):`<div class="card mt"><h3>R-multiple per trade</h3><p class="hint">Not shown: the stop is on the futures, not on the traded option.</p></div>`}${scatter(T)}${hist(T.map(t=>tradeMin(t,sess)),'Holding time (trading minutes)',v=>Math.round(v)+'m')}</div>`;}

// ---- Monte Carlo
function prng(seed){return ()=>{seed|=0;seed=seed+0x6D2B79F5|0;let t=Math.imul(seed^seed>>>15,1|seed);t=t+Math.imul(t^t>>>7,61|t)^t;return ((t^t>>>14)>>>0)/4294967296;};}
const q=(a,p)=>{const b=[...a].sort((x,y)=>x-y);return b[Math.min(b.length-1,Math.max(0,Math.floor(p*(b.length-1))))];};
function pathStats(arr,cap,ruin){let c=0,pk=0,dd=0,ls=0,cs=0,hit=false;for(const v of arr){c+=v;pk=Math.max(pk,c);dd=Math.min(dd,c-pk);if(v<=0){cs++;ls=Math.max(ls,cs);}else cs=0;if(cap&&c<=-ruin*cap)hit=true;}return {final:c,dd,ls,hit};}
function renderMC(T){
  const N=2000,rnd=prng(20260927),net=T.map(t=>t.net),n=net.length,{cap,how}=capitalFor(T);
  if(n<5){$('p-mc').innerHTML='<div class="note">Too few trades for a Monte Carlo analysis.</div>';return;}
  const ruin=load_('ruin')||0.3;
  const shuffle=a=>{const b=[...a];for(let i=b.length-1;i>0;i--){const j=Math.floor(rnd()*(i+1));[b[i],b[j]]=[b[j],b[i]];}return b;};
  const boot=a=>a.map(()=>a[Math.floor(rnd()*a.length)]);
  const sh=[],bs=[],paths=[],means=[];
  for(let k=0;k<N;k++){const a=shuffle(net);sh.push(pathStats(a,cap,ruin));if(k<400){let c=0;paths.push(a.map(v=>c+=v));}
    const b=boot(net);bs.push(pathStats(b,cap,ruin));means.push(b.reduce((x,y)=>x+y,0)/n);}
  const stress=(skip,slip)=>{const res=[];for(let k=0;k<N;k++){const a=net.filter(()=>rnd()>=skip).map(v=>v-2*slip*cur.lot_size);res.push(a.reduce((x,y)=>x+y,0));}return res;};
  const rows=[['As tested',0,0],['Skip 10% of trades',.1,0],['Skip 20% of trades',.2,0],['+2 pts slippage per side',0,2],['+5 pts slippage per side',0,5]].map(([l,sk,sl])=>{const r=stress(sk,sl);return [l,q(r,.5),q(r,.05),r.filter(x=>x<0).length/N];});
  const band=p=>paths[0].map((_,i)=>q(paths.map(x=>x[i]),p));
  const lo=q(means,.025),hi=q(means,.975);
  $('p-mc').innerHTML=(n<50?`<div class="note">Only ${n} trades. Monte Carlo reshuffles these trades — it cannot add information they do not contain. Read the ranges as rough.</div>`:'')+
    `<div class="card mt"><h3>Trade-order shuffle: 2,000 random orderings of the same ${n} trades</h3><p class="hint">Percentile bands of cumulative net P&L by trade number (5 / 25 / 50 / 75 / 95%). Same final P&L, different paths — how rough the ride could have been.</p><div class="chartbox"><div id="mcfan"></div></div></div>`+
    `<div class="grid2">`+
    `<div class="card mt"><h3>Drawdown and losing streaks (shuffle)</h3><table><tr><td>Max drawdown — actual</td><td class="num neg">${inr(pathStats(net).dd)}</td></tr><tr><td>Max drawdown — median</td><td class="num neg">${inr(q(sh.map(x=>x.dd),.5))}</td></tr><tr><td>Max drawdown — 95% worst case</td><td class="num neg">${inr(q(sh.map(x=>x.dd),.05))}</td></tr><tr><td>Longest losing streak — median</td><td class="num">${q(sh.map(x=>x.ls),.5)} trades</td></tr><tr><td>Longest losing streak — 95% worst case</td><td class="num">${q(sh.map(x=>x.ls),.95)} trades</td></tr></table></div>`+
    `<div class="card mt"><h3>Bootstrap: trades resampled with replacement</h3><table><tr><td>Final net — 5% / median / 95%</td><td class="num">${inr(q(bs.map(x=>x.final),.05))} / ${inr(q(bs.map(x=>x.final),.5))} / ${inr(q(bs.map(x=>x.final),.95))}</td></tr><tr><td>Probability of finishing below zero</td><td class="num">${pct(bs.filter(x=>x.final<0).length/N)}</td></tr><tr><td>Expectancy per trade — 95% range</td><td class="num">${inr(lo)} to ${inr(hi)}</td></tr><tr><td>Edge</td><td class="num">${lo<0&&hi>0?'<span class="pill open">not proven — range includes zero</span>':hi<=0?'<span class="pill short">negative</span>':'<span class="pill long">positive</span>'}</td></tr></table></div>`+
    `<div class="card mt"><h3>Stress tests</h3><table><thead><tr><th></th><th class="num">Median net</th><th class="num">5% worst</th><th class="num">P(loss)</th></tr></thead><tbody>${rows.map(([l,md,w,pl])=>`<tr><td>${l}</td><td class="num ${cl(md)}">${inr(md)}</td><td class="num ${cl(w)}">${inr(w)}</td><td class="num">${pct(pl)}</td></tr>`).join('')}</tbody></table></div>`+
    `<div class="card mt"><h3>Risk of ruin</h3><p class="hint">Chance the account falls by <select id="ruinSel">${[.2,.3,.5].map(v=>`<option value="${v}" ${v===ruin?'selected':''}>${v*100}%</option>`).join('')}</select> of capital at any point. Capital: ${how}.</p><table><tr><td>Shuffled orderings</td><td class="num">${pct(sh.filter(x=>x.hit).length/N)}</td></tr><tr><td>Bootstrap samples</td><td class="num">${pct(bs.filter(x=>x.hit).length/N)}</td></tr></table></div></div>`;
  $('ruinSel').onchange=e=>{save_('ruin',+e.target.value);renderMC(sel());};
  if(mcch){mcch.remove();mcch=null;}
  const B=1600000000;mcch=mkChart($('mcfan'),{timeScale:{borderColor:'#e6e8ec',tickMarkFormatter:t=>String(Math.round((t-B)/86400))},localization:{timeFormatter:t=>'trade '+Math.round((t-B)/86400),priceFormatter:v=>inr(v)}});
  [[.05,'#f23645',1],[.25,'#f5a08f',1],[.5,'#111',2],[.75,'#7fd6bb',1],[.95,'#089981',1]].forEach(([p,c,w])=>mcch.addLineSeries({color:c,lineWidth:w,priceLineVisible:false,lastValueVisible:false,title:(p*100)+'%'}).setData(band(p).map((v,i)=>({time:B+(i+1)*86400,value:Math.round(v)}))));
  mcch.timeScale().fitContent();
}

// ---- robustness
function renderRobust(T){
  const m=cur,r=runOf(m),s=statsOf(T),lot=m.lot_size,base=m.slippage_pts,n=T.length,sch=schemeOf(m),opt=m.variant!=='FUT';
  const slip=[0,1,2,5,10].map(x=>[x,s.net_inr+2*(base-x)*lot*n]);
  const chg=[0,.5,1,1.5,2].map(x=>[x,s.gross_inr-x*s.charges_inr]);
  const byM={};T.forEach(t=>{const k=t.xt.slice(0,7);(byM[k]??=[]).push(t);});
  const other=Object.entries(m.runs).filter(([k,x])=>x.label===r.label&&x.kind===r.kind&&x.status==='ok');
  $('p-robust').innerHTML=`<div class="grid2">`+
    `<div class="card mt"><h3>Slippage sensitivity</h3><p class="hint">Net P&L if slippage per side were different (base ${base} pts).</p><table>${slip.map(([x,v])=>`<tr><td>${x} pts per side${x===base?' (base)':''}</td><td class="num ${cl(v)}">${inr(v)}</td></tr>`).join('')}</table></div>`+
    `<div class="card mt"><h3>Charges sensitivity</h3><p class="hint">Net P&L at different charge levels.</p><table>${chg.map(([x,v])=>`<tr><td>${x===0?'No charges':x+'× charges'}${x===1?' (base)':''}</td><td class="num ${cl(v)}">${inr(v)}</td></tr>`).join('')}</table></div>`+
    `<div class="card mt"><h3>Month by month</h3><table><thead><tr><th>Month</th><th class="num">Trades</th><th class="num">Net ₹</th><th class="num">Win %</th></tr></thead><tbody>${Object.keys(byM).sort().map(k=>{const a=byM[k],v=sum(a,t=>t.net);return `<tr><td>${k}</td><td class="num">${a.length}</td><td class="num ${cl(v)}">${inr(v)}</td><td class="num">${Math.round(100*a.filter(t=>t.net>0).length/a.length)}%</td></tr>`;}).join('')}</tbody></table></div>`+
    `<div class="card mt"><h3>Same rules on other timeframes</h3><p class="hint">This backtest, ${SCH[sch]}${opt?`, ${EXP[S().exp]} ${S().strike}`:''}.</p><table>${other.map(([k,x])=>{const c=x.choices[choiceOf(m)];const v=c?(sch==='BOTH'?c:({LONG:c.long,SHORT:c.short,CE:c.ce,PE:c.pe})[sch]):null;return `<tr><td>${TFS[x.timeframe]}${x.design?' (design)':''}</td><td class="num ${v?cl(v.net_inr):''}">${v?inr(v.net_inr):'—'}${c&&c.skipped?'<span class="warn">*</span>':''}</td><td class="num">${v?v.trades+' trades':''}</td></tr>`;}).join('')}${other.length<2?'<tr><td colspan="3" class="hint">Only the design timeframe has been run for this backtest — use Timeframe ▾ above to add one.</td></tr>':''}</table></div>`+
    `</div>`+(opt?`<div class="card mt" style="margin-top:12px"><h3>Expiry × strike</h3><p class="hint">Every expiry and strike choice for this type and backtest. Click a row to apply it.</p><div class="scroll"><table><thead><tr><th>Expiry</th><th>Strike</th><th class="num">Trades</th><th class="num">Long ₹</th><th class="num">Short ₹</th><th class="num">L+S · CE ₹</th><th class="num">L+S · PE ₹</th><th class="num">PF</th></tr></thead><tbody>`+
      Object.entries(r.choices).map(([c,x])=>`<tr class="z" data-c="${c}" style="${c===curChoice?'background:var(--sel-bg)':''}"><td>${EXP[ck(c)[0]]}</td><td>${ck(c)[1]}</td><td class="num">${x.trades}${x.skipped?`<span class="warn" title="${x.skipped} skipped">*</span>`:''}</td><td class="num ${cl(x.long?.net_inr)}">${inr(x.long?.net_inr)}</td><td class="num ${cl(x.short?.net_inr)}">${inr(x.short?.net_inr)}</td><td class="num ${cl(x.ce?.net_inr)}">${inr(x.ce?.net_inr)}</td><td class="num ${cl(x.pe?.net_inr)}">${inr(x.pe?.net_inr)}</td><td class="num">${x.pf??'—'}</td></tr>`).join('')+'</tbody></table></div></div>':'');
  document.querySelectorAll('#p-robust tr.z').forEach(tr=>tr.onclick=()=>{const [e,k]=ck(tr.dataset.c);S().exp=e;S().strike=k;saveAll();openType();});
}

// ================= start
if(!fams.includes(ST.fam))ST.fam=fams[0];
openType();
</script></body></html>
