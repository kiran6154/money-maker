<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strategy dashboard</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--muted:#6b7280;--line:#e6e8ec;--up:#089981;--dn:#f23645;--acc:#2962ff;--pur:#7b1fa2;--amb:#b45309;--rad:10px}
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
.link{color:var(--acc);cursor:pointer;white-space:nowrap}.link:hover{text-decoration:underline}
.badge{background:#fff4e0;color:var(--amb);border-radius:999px;padding:1px 9px;font-size:11px;font-weight:600;margin-left:8px}
.menu{position:relative;display:inline-block}
.pop{position:absolute;top:22px;left:0;z-index:20;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.12);min-width:320px;padding:4px;display:none}
.pop.on{display:block}.pop .it{padding:6px 10px;border-radius:6px;cursor:pointer}.pop .it:hover{background:#f3f6ff}.pop .it.on{background:#eef2ff}
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
.hc{width:12px;height:12px;border-radius:2px;background:#ebedf0;cursor:pointer}.hc.x{background:transparent;cursor:default}.hc.z{background:#ebedf0}
.hc:hover{outline:1.5px solid #16181d}.hc.sel{outline:1.5px solid var(--acc)}
.hmlegend{display:flex;align-items:center;gap:3px;font-size:10px;color:var(--muted);margin-top:4px}.hmlegend i{width:10px;height:10px;border-radius:2px;display:inline-block}
.hmstats{display:grid;grid-template-columns:repeat(3,auto);gap:4px 18px;font-size:12px;font-variant-numeric:tabular-nums;align-content:start}
.hmstats div{color:var(--muted)}.hmstats b{display:block;color:var(--ink);font-size:13px}
.warn{color:#d97706;font-weight:700;cursor:help;margin-left:1px}
.chartcard{display:flex;flex-direction:column;height:max(460px,calc(100vh - 60px));overflow:hidden}
.ctop{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px 10px;border-bottom:1px solid var(--line)}
.crumb{font-size:13px;font-weight:600}.crumb span{color:var(--muted);font-weight:400;margin:0 4px}
.cbody{position:relative;flex:1;min-height:0}#chart{position:absolute;inset:0}
.ohlc{font:12px ui-monospace,Consolas,monospace;color:var(--muted);white-space:nowrap}.ohlc b{color:var(--ink);font-weight:500}
.nav{display:inline-flex;align-items:center;gap:4px}
.nav button,.nav select{font:12px system-ui;border:1px solid var(--line);background:#fff;border-radius:6px;padding:3px 8px;cursor:pointer;color:var(--ink)}
.layers{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:2px 9px;font-size:11px;color:var(--muted);cursor:pointer;user-select:none}
.chip.on{color:var(--ink);border-color:#c9ced6}.chip i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}
.loading{position:absolute;inset:0;display:none;align-items:center;justify-content:center;background:rgba(255,255,255,.7);z-index:5;color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.kpi{padding:10px 12px}.kpi .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.kpi .v{font-size:20px;font-weight:600;margin-top:2px;font-variant-numeric:tabular-nums}.kpi .s{color:var(--muted);font-size:11px}
.tabs{position:sticky;top:0;z-index:4;display:flex;gap:2px;background:var(--bg);padding-top:4px;border-bottom:1px solid var(--line);overflow-x:auto}
.tab{border:0;background:transparent;padding:8px 12px;font:13px system-ui;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
.tab.on{color:var(--ink);border-bottom-color:var(--acc);font-weight:600}
.panel{display:none;padding:12px 0}.panel.on{display:block}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600;text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);background:#fafbfc;position:sticky;top:0}
td{padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
tbody tr.z{cursor:pointer}tbody tr.z:hover{background:#f3f6ff}
.num{text-align:right}.pos{color:var(--up)}.neg{color:var(--dn)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600}
.pill.long{background:#e6f6f2;color:#067a66}.pill.short{background:#fdecee;color:#c0272f}.pill.open{background:#fff4e0;color:#9a5b00}.pill.grey{background:#eef0f3;color:#555}
.scroll{max-height:70vh;overflow:auto}.hint{color:var(--muted);font-size:12px;margin:0 0 8px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px}
.mt{padding:10px 12px}.mt h3{margin:0 0 6px;font-size:13px}.mt table td{padding:5px 8px}.mt table td:first-child{color:var(--muted)}
.note{background:#fff8eb;border:1px solid #f5d9a8;color:#8a5a00;border-radius:8px;padding:8px 10px;font-size:12px;margin-bottom:10px}
.chartbox{position:relative;height:320px}.chartbox>div{position:absolute;inset:0}
.rules{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
.rules .card{padding:12px 14px}.rules h3{margin:0 0 6px;font-size:13px}.rules ul{margin:0;padding-left:18px}.rules li{margin:3px 0}
.sw{display:inline-block;width:18px;text-align:center;font-weight:700}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:0}dt{color:var(--muted)}dd{margin:0}
svg text{font:10px system-ui;fill:#6b7280}
</style>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
</head><body><div class="wrap">
<h1>Strategy dashboard</h1>
<div class="sub">Strategy → backtest period and timeframe → type (futures · options via futures · options standalone) → scheme</div>
<div id="board" class="card"></div>
<div class="typebar"><span class="seg" id="typeSeg"></span><span class="pipe">|</span><div class="schemes" id="tiles"></div><div class="optset" id="optset"></div></div>
<div class="card cal" id="cal"></div>

<div class="card chartcard">
  <div class="ctop">
    <span class="crumb" id="crumb"></span>
    <span class="seg" id="viewSeg" title="which chart"></span>
    <div class="nav" id="dayNav"><button id="prev" title="previous">‹</button><select id="series" title="session / contract"></select><button id="next" title="next">›</button><button id="all" title="load every session of this backtest into one chart">Full period</button></div>
    <div class="ohlc" id="ohlc"></div>
    <div class="layers" id="layers"></div>
  </div>
  <div class="cbody"><div id="chart"></div><div class="loading" id="loading">Loading…</div></div>
</div>

<div class="kpis" id="kpis"></div>
<div class="tabs" id="tabs">
  <button class="tab on" data-p="trades">Trades</button><button class="tab" data-p="perf">Performance</button>
  <button class="tab" data-p="equity">Cumulative P&amp;L</button><button class="tab" data-p="dd">Drawdowns</button>
  <button class="tab" data-p="dist">Distribution</button><button class="tab" data-p="mc">Monte Carlo</button>
  <button class="tab" data-p="robust">Robustness</button><button class="tab" data-p="bdown">Breakdown</button>
  <button class="tab" data-p="daily">Daily P&amp;L</button><button class="tab" data-p="signals">Signals</button>
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
const SCHEMES=m=>m.variant==='FUT'?['BOTH','LONG','SHORT']:['LONG','SHORT','CE','PE'];
const SDESC=(m,s)=>m.variant==='FUT'?{BOTH:'long and short futures (total)',LONG:'long futures',SHORT:'short futures'}[s]
  :m.variant==='OPT_FUT_SIGNAL'?{LONG:'CE on future long, PE on future short',SHORT:'PE on future long, CE on future short',CE:'CE: long on future long, short on future short',PE:'PE: short on future long, long on future short'}[s]
  :{LONG:'bullish setups, CE and PE charts',SHORT:'bearish setups, CE and PE charts',CE:'CE chart, both directions',PE:'PE chart, both directions'}[s];
const inSch=(t,s)=>s==='BOTH'||(s==='LONG'||s==='SHORT'?t.pos===s:t.otype===s);
const on={trades:true,avwap:true,prot:true,struct:true,swings:true,vol:true};
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
const choiceOf=m=>m.variant==='FUT'?'-':`${SEL[m.family].exp}-${SEL[m.family].strike}`;
const statOf=(m,sch)=>{const r=runOf(m);const s=r&&r.choices[choiceOf(m)];if(!s)return null;return sch==='BOTH'?s:({LONG:s.long,SHORT:s.short,CE:s.ce,PE:s.pe})[sch]||null;};
const cov=m=>{const r=runOf(m),s=r&&r.choices[choiceOf(m)];if(!s||!s.skipped)return null;return {text:`Incomplete: ${s.trades} of ${s.trades+s.skipped} positions priced; ${s.skipped} skipped for missing option data.`};};
const star=c=>c?`<span class="warn" title="${c.text}">*</span>`:'';
const schemeOf=m=>{const s=SEL[m.family].scheme[m.code];return s&&SCHEMES(m).includes(s)?s:(m.variant==='FUT'?'BOTH':'CE');};
const fmtD=d=>d?new Date(d+'T00:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'short',timeZone:'UTC'}):'';
const rng=r=>r&&r.date_from?`${fmtD(r.date_from)} – ${fmtD(r.date_to)} ${r.date_to.slice(0,4)}`:'';

// ================= strategy board (expanded) / strategy line (collapsed)
function renderBoard(){
  const b=$('board');
  if(ST.board){
    b.innerHTML=`<div class="bhead"><b>Strategies</b><span class="sub">${fams.length} · click one to open</span><input id="bfilter" placeholder="Filter strategies" style="margin-left:auto"></div>`+
      fams.map(f=>{const rs=rowsOf(f),r=runsOf(f)[SEL[f].run];
        const cell=m=>{const s=statOf(m,schemeOf(m)),c=cov(m);return `${TYPE[m.variant]} <b class="${s?cl(s.net_inr):''}">${s?inrk(s.net_inr):'—'}</b>${star(c)}`;};
        return `<div class="brow" data-f="${f}"><b>${rs[0].name.split(' · ').slice(0,2).join(' · ')}</b><span class="pipe">|</span>${TFS[designTf(f)]} design<span class="pipe">|</span>${r?r.label+' · '+rng(r):'—'}`+
          rs.map(m=>`<span class="pipe">|</span>${cell(m)}`).join('')+`</div>`;}).join('');
    $('bfilter').oninput=e=>{const q=e.target.value.toLowerCase();b.querySelectorAll('.brow').forEach(x=>x.style.display=x.innerText.toLowerCase().includes(q)?'':'none');};
    b.querySelectorAll('.brow').forEach(x=>x.onclick=()=>{ST.fam=x.dataset.f;ST.board=false;saveAll();openStrategy();});
    return;
  }
  const f=ST.fam,m0=rowsOf(f)[0],rs=runsOf(f),r=rs[S().run],tf=r.timeframe,dtf=designTf(f);
  const designRuns=Object.entries(rs).filter(([k,x])=>x.design);
  const sameLabel=Object.entries(rs).filter(([k,x])=>x.label===r.label&&x.kind===r.kind);
  b.innerHTML=`<div class="sline"><b>${m0.name.split(' · ').slice(0,2).join(' · ')}</b><span class="pipe">|</span><span>${TFS[dtf]} design · SL ${m0.sl_rule.replace('_',' ')}</span><span class="pipe">|</span>
    <span class="menu">Backtest: <span class="link" id="btL">${r.label} · ${rng(r)} ▾</span><div class="pop" id="btP"></div></span><span class="pipe">|</span>
    <span class="menu">Timeframe: <span class="link" id="tfL">${TFS[tf]}${tf===dtf?' (design)':''} ▾</span><div class="pop" id="tfP"></div></span>
    ${tf!==dtf?`<span class="badge">Running on ${TFS[tf]} · designed for ${TFS[dtf]}</span>`:''}<span class="pipe">|</span><span class="link" id="rulesL">rules ▾</span>
    <span class="link" style="margin-left:auto" id="allL">▾ all strategies (${fams.length})</span></div><div id="rules"></div>`;
  $('btP').innerHTML=designRuns.map(([k,x])=>`<div class="it ${x.status!=='ok'?'off':''} ${k===S().run?'on':''}" data-k="${k}">${x.label} · ${x.status==='ok'?rng(x):'not available'}${x.is_default?' · default':''}<small>${x.status==='ok'?(x.notes||''):x.reason}</small></div>`).join('')+
    `<div class="sep"></div><div class="it" id="addBt">+ Add backtest</div><div id="addBtBox" style="display:none;padding:4px 8px"><small class="sub">Run one of these in research/strategy_lab, then reload:</small>
    <code>python lab.py backtest ${f} 1Y\npython lab.py backtest ${f} 5Y\npython lab.py backtest ${f} YTD\npython lab.py backtest ${f} 2026-07-10 2026-08-10 --label "July"</code><small class="sub">Data covers ${fmtD(DATA_RANGE[0])} ${DATA_RANGE[0].slice(0,4)} – ${fmtD(DATA_RANGE[1])} ${DATA_RANGE[1].slice(0,4)}; longer backtests are refused until more data is added.</small></div>`;
  $('tfP').innerHTML=sameLabel.sort((a,b)=>(b[1].design-a[1].design)).map(([k,x])=>`<div class="it ${k===S().run?'on':''}" data-k="${k}">${TFS[x.timeframe]}${x.design?' · design':''}<small>${x.design?'the timeframe the rules were built for':'same rules on '+TFS[x.timeframe]+' candles'}</small></div>`).join('')+
    `<div class="sep"></div><div class="it" id="addTf">+ Test on another timeframe</div><div id="addTfBox" style="display:none;padding:4px 8px"><small class="sub">Run in research/strategy_lab, then reload:</small><code>${['minute','3minute','5minute','15minute','30minute'].filter(t=>!sameLabel.some(([k,x])=>x.timeframe===t)).map(t=>`python lab.py backtest ${f} ${r.kind==='all'?'all':r.kind==='preset'?r.preset:r.date_from+' '+r.date_to} --tf ${t} --label "${r.label}"`).join('\n')}</code></div>`;
  const toggle=(l,p)=>{$(l).onclick=e=>{e.stopPropagation();document.querySelectorAll('.pop').forEach(x=>x!==$(p)&&x.classList.remove('on'));$(p).classList.toggle('on');};};
  toggle('btL','btP');toggle('tfL','tfP');
  document.querySelectorAll('.pop').forEach(p=>p.onclick=e=>e.stopPropagation());
  document.querySelectorAll('#btP .it[data-k], #tfP .it[data-k]').forEach(it=>it.onclick=()=>{if(it.classList.contains('off'))return;S().run=it.dataset.k;saveAll();document.querySelectorAll('.pop').forEach(x=>x.classList.remove('on'));openStrategy();});
  $('addBt').onclick=()=>{$('addBtBox').style.display='block';};
  $('addTf').onclick=()=>{$('addTfBox').style.display='block';};
  $('rulesL').onclick=()=>$('rules').classList.toggle('on');
  $('rules').innerHTML=`<b>Rules</b> — swings (Pine port) → protected level (unbroken swing beyond the trend AVWAP) → CHoCH / BOS by ${m0.break_mode} → AVWAP pair from the previous SH and SL at each CHoCH → SETUP (both AVWAPs sloping with the CHoCH and a close beyond the CHoCH candle) → exit on stop loss (${m0.sl_rule.replace('_',' ')}) or the next CHoCH.
    <span class="sub"> · warm-up ${m0.warmup_days} sessions · AVWAP ${m0.avwap_weight}-weighted · slippage futures 5 / options 0.5 pt per side</span>`;
  $('allL').onclick=()=>{ST.board=true;saveAll();renderBoard();};
}
document.addEventListener('click',()=>document.querySelectorAll('.pop').forEach(x=>x.classList.remove('on')));

// ================= type tabs, option settings, scheme tiles
function renderTypes(){
  const f=ST.fam,rs=rowsOf(f),o=rs.find(m=>m.variant!=='FUT'),m=cur;
  $('typeSeg').innerHTML=rs.map(x=>`<button data-c="${x.code}" class="${x.code===m.code?'on':''}">${TYPE[x.variant]}</button>`).join('');
  $('typeSeg').querySelectorAll('button').forEach(b=>b.onclick=()=>{S().type=b.dataset.c;saveAll();openType();});
  if(m.variant!=='FUT'&&o){const r=runOf(o),keys=r?Object.keys(r.choices):[],exps=[...new Set(keys.map(k=>ck(k)[0]))],strikes=[...new Set(keys.map(k=>ck(k)[1]))];
    $('optset').innerHTML=`Options <span class="seg sm" id="expSeg">${exps.map(e=>`<button data-v="${e}" class="${S().exp===e?'on':''}">${EXP[e]}</button>`).join('')}</span> strike <select id="stkSel">${strikes.map(s=>`<option ${S().strike===s?'selected':''}>${s}</option>`).join('')}</select><span>${S().strike.startsWith('ATR')?`spot ± ${S().strike.slice(3)}×ATR(${o.atr_period}), OTM`:'from spot'}</span>`;
    $('expSeg').querySelectorAll('button').forEach(b=>b.onclick=()=>{S().exp=b.dataset.v;saveAll();openType();});
    $('stkSel').onchange=e=>{S().strike=e.target.value;saveAll();openType();};
  }else $('optset').innerHTML='';
  const c=cov(m);
  $('tiles').innerHTML=SCHEMES(m).map(s=>{const x=statOf(m,s),on_=s===schemeOf(m);
    const tip=`${SCH[s]}: ${SDESC(m,s)}${x?` · ${x.trades} trades · ${x.trades?Math.round(100*x.wins/x.trades):0}% win · PF ${x.pf??'—'}`:''}${c?' · '+c.text:''}`;
    return `<span class="pillb ${on_?'on':''}" data-s="${s}" title="${tip}">${SCH[s]} <b class="${x?cl(x.net_inr):''}">${x?inr(x.net_inr):'—'}</b>${star(c)}</span>`;}).join('');
  $('tiles').querySelectorAll('.pillb').forEach(t=>t.onclick=()=>{S().scheme[m.code]=t.dataset.s;saveAll();schemeChanged();});
}

// ================= data + chart chunks
const getJSON=async f=>{if(!cache[f])cache[f]=fetch(f).then(r=>{if(!r.ok)throw new Error(f+' '+r.status);return r.json();});return cache[f];};
const busy=(v,txt)=>{$('loading').style.display=v?'flex':'none';if(txt)$('loading').textContent=txt;};
let WIN=null,extending=false,VIEW='signal';
const merge=parts=>{const seen=new Set(),M=[];for(const c of parts)for(const m of c.M)if(!seen.has(m[0]+'|'+m[9])){seen.add(m[0]+'|'+m[9]);M.push(m);}
  const cat=k=>parts.flatMap(c=>c[k]);return {C:cat('C'),S:cat('S'),E:cat('E'),PR:cat('PR'),PAIR:cat('PAIR'),M};};
async function renderWin(range){const parts=[];for(let k=WIN.lo;k<=WIN.hi;k++)parts.push(await getJSON(D.base+D.charts[k].file));const c=merge(parts);drawChart(c,!range,range);return c;}
const inView=()=>D.charts.map((c,i)=>i).filter(i=>(D.charts[i].kind||'signal')===VIEW);
async function showChunk(k){if(k==null||isNaN(k))return;$('series').value=k;busy(true,'Loading chart…');try{WIN={lo:k,hi:k};return await renderWin();}finally{busy(false);}}
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
async function openType(){
  const f=ST.fam;cur=rowsOf(f).find(m=>m.code===S().type)||rowsOf(f)[0];S().type=cur.code;curChoice=choiceOf(cur);
  const r=runOf(cur);if(!r.choices[curChoice])curChoice=Object.keys(r.choices)[0];
  renderBoard();renderTypes();
  const file=r.choices[curChoice].file;busy(true,'Loading…');
  try{D=await getJSON(file);D.base=file.slice(0,file.lastIndexOf('/')+1);}finally{busy(false);}
  const kinds=[...new Set(D.charts.map(c=>c.kind||'signal'))];VIEW=kinds.includes('option')?'option':'signal';
  $('viewSeg').style.display=kinds.length>1?'':'none';
  $('viewSeg').innerHTML=kinds.map(k=>`<button data-v="${k}">${k==='option'?'Option chart':'Signal chart (futures)'}</button>`).join('');
  $('viewSeg').querySelectorAll('button').forEach(b=>b.onclick=()=>setView(b.dataset.v));
  CALM=null;schemeChanged(true);await setView(VIEW);
}
function schemeChanged(noChart){
  renderTypes();renderBoard();
  const r=runOf(cur),dtf=designTf(ST.fam);
  $('crumb').innerHTML=`${cur.name.split(' · ').slice(0,2).join(' · ')}<span>›</span>${r.label}${r.timeframe!==dtf?` · ${TFS[r.timeframe]}`:''}<span>›</span>${TYPE[cur.variant]}<span>›</span>${SCH[schemeOf(cur)]}${cur.variant!=='FUT'?`<span>·</span><span style="margin:0">${EXP[ck(curChoice)[0]]} ${ck(curChoice)[1]}</span>`:''}${star(cov(cur))}`;
  renderBelow();if(!noChart)showChunk(+$('series').value);
}
const inScheme=lbl=>{const [pos,ot]=(lbl||'').split(' ');return inSch({pos,otype:ot||'FUT'},schemeOf(cur));};

// ================= chart
function drawChart(CH_,single,range){
  const {C,S:SW,E,PR,PAIR,M}=CH_;
  if(ch){ch.remove();ch=null;}
  ch=LightweightCharts.createChart($('chart'),{autoSize:true,layout:{background:{color:'#fff'},textColor:'#4b5563',fontFamily:'system-ui'},
    grid:{vertLines:{color:'#f3f4f6'},horzLines:{color:'#f3f4f6'}},rightPriceScale:{borderColor:'#e6e8ec'},
    timeScale:{timeVisible:true,secondsVisible:false,rightOffset:4,borderColor:'#e6e8ec'},crosshair:{mode:0},
    handleScroll:{mouseWheel:false,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},
    handleScale:{mouseWheel:false,pinch:true,axisPressedMouseMove:true},localization:{timeFormatter:t=>iso(t).slice(5,16).replace('T',' ')}});
  const cs=ch.addCandlestickSeries({upColor:'#089981',downColor:'#f23645',wickUpColor:'#089981',wickDownColor:'#f23645',borderVisible:false});
  cs.priceScale().applyOptions({scaleMargins:{top:0.06,bottom:0.2}});
  cs.setData(C.map(r=>({time:r[0],open:r[1],high:r[2],low:r[3],close:r[4]})));
  const base={lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false,autoscaleInfoProvider:()=>null};
  const L={vol:[],swings:[],avwap:[],prot:[],trades:[]};
  const line=(layer,opt,data)=>{const s=ch.addLineSeries({...base,...opt,visible:on[layer]});s.setData(data);L[layer].push(s);};
  const vs=ch.addHistogramSeries({priceScaleId:'vol',priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false,visible:on.vol});
  ch.priceScale('vol').applyOptions({scaleMargins:{top:0.84,bottom:0}});
  vs.setData(C.map(r=>({time:r[0],value:r[7],color:r[4]>=r[1]?'rgba(8,153,129,.35)':'rgba(242,54,69,.35)'})));L.vol.push(vs);
  for(const [idx,col] of [[5,'rgba(8,153,129,.4)'],[6,'rgba(242,54,69,.4)']])
    line('swings',{color:col,lineVisible:false,pointMarkersVisible:true,pointMarkersRadius:1.5},C.map(r=>r[idx]==null?{time:r[0]}:{time:r[0],value:r[idx]}));
  const MK={swings:[],struct:[],trades:[]};
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
    if(xt<=tmax)MK.trades.push({time:xt,position:up?'aboveBar':'belowBar',color:win?'#089981':'#f23645',shape:'circle',size:0.9,text:(why==='stop_loss'?'SL ':why==='expiry'?'EXPIRY ':open?'OPEN* ':'')+fmt(pts)});
    line('trades',{color:win?'#089981':'#f23645',lineWidth:2,lineStyle:2},et===xe?[{time:et,value:ep}]:[{time:et,value:ep},{time:xe,value:xp}]);
    if(sl!=null)line('trades',{color:'#d32f2f',lineWidth:1,lineStyle:1},et===xe?[{time:et,value:sl}]:[{time:et,value:sl},{time:xe,value:sl}]);}
  const markers=()=>{const m=[];if(on.swings)m.push(...MK.swings);if(on.struct)m.push(...MK.struct);if(on.trades)m.push(...MK.trades);m.sort((a,b)=>a.time-b.time);cs.setMarkers(m);};
  markers();
  const chips=[['trades','Trades','#111'],['avwap','AVWAP','#ff6d00'],['prot','Protected','#7b1fa2'],['struct','CHoCH/BOS','#9e9e9e'],['swings','Swings','#089981'],['vol','Volume','#c3c7cf']];
  $('layers').innerHTML='';
  for(const [k,lbl,col] of chips){const b=document.createElement('span');b.className='chip'+(on[k]?' on':'');b.innerHTML=`<i style="background:${col}"></i>${lbl}`;
    b.onclick=()=>{on[k]=!on[k];b.classList.toggle('on',on[k]);(L[k]||[]).forEach(s=>s.applyOptions({visible:on[k]}));markers();};$('layers').appendChild(b);}
  const byT=new Map(C.map(r=>[r[0],r]));
  const showBar=r=>{if(!r)return;$('ohlc').innerHTML=`${iso(r[0]).slice(5,16).replace('T',' ')} O <b>${r[1]}</b> H <b>${r[2]}</b> L <b>${r[3]}</b> C <b class="${r[4]>=r[1]?'pos':'neg'}">${r[4]}</b> V <b>${r[7].toLocaleString('en-IN')}</b>`;};
  showBar(C[C.length-1]);ch.subscribeCrosshairMove(p=>showBar(p.time?byT.get(p.time):C[C.length-1]));
  $('chart').onwheel=e=>{if(!e.ctrlKey)return;e.preventDefault();const ts=ch.timeScale(),r=ts.getVisibleLogicalRange();if(!r)return;
    const x=ts.coordinateToLogical(e.offsetX)??(r.from+r.to)/2,k=e.deltaY>0?1.15:1/1.15;ts.setVisibleLogicalRange({from:x-(x-r.from)*k,to:x+(r.to-x)*k});};
  const per=375/({'minute':1,'3minute':3,'5minute':5,'15minute':15,'30minute':30}[runOf(cur).timeframe]||5);
  if(range)ch.timeScale().setVisibleLogicalRange(range);
  else if(single)ch.timeScale().fitContent();else ch.timeScale().setVisibleLogicalRange({from:C.length-per-2,to:C.length+2});
  if(WIN)ch.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(!r||extending)return;if(r.from<5&&WIN.lo>0)extend(-1,r);else if(r.to>C.length+2&&WIN.hi<D.charts.length-1)extend(1,r);});
  CH_.zoom=(a,b)=>{const idx=t=>{let lo=0,hi=C.length-1;while(lo<hi){const m=(lo+hi)>>1;if(C[m][0]<t)lo=m+1;else hi=m;}return lo;};ch.timeScale().setVisibleLogicalRange({from:idx(a)-20,to:idx(b)+20});};
}
async function openTrade(et,xt){
  let k=inView().find(i=>D.charts[i].marks.includes(et));
  if(k==null){k=D.charts.findIndex(c=>c.marks.includes(et));if(k<0)k=inView().slice(-1)[0];else await setView(D.charts[k].kind||'signal',k);}
  const c=await showChunk(k);if(c)c.zoom(et,xt);document.querySelector('.chartcard').scrollIntoView({behavior:'smooth',block:'start'});
}
async function openDay(d){const k=inView().find(i=>D.charts[i].day===d);if(k!=null){await showChunk(k);document.querySelector('.chartcard').scrollIntoView({behavior:'smooth',block:'start'});}}

// ================= trades of the current selection
const allTrades=()=>D.trades.map(([otype,instr,strike,cht,et,ep,sl,xt,xp,why,pts,gross,chg,net,open,cb,ue,ux,stale,mfe,mae,pos,ot,sig,exp])=>({otype:ot||otype,pos:pos||'LONG',sig:sig||'',exp,instr,strike,cht,et,ep,sl,xt,xp,why,pts,gross,chg,net,open,cb,ue,ux,stale,mfe:mfe??0,mae:mae??0,
    ets:Date.parse(et.replace(' ','T')+'Z')/1000,xts:Date.parse(xt.replace(' ','T')+'Z')/1000}));
const sel=()=>allTrades().filter(t=>inSch(t,schemeOf(cur)));
const sessionsOf=()=>[...new Set(D.charts.map(c=>c.day).filter(Boolean))].sort();
const sigName=t=>!t.sig?'—':cur.variant==='OPT_NATIVE'?(t.sig==='BULLISH'?'Bullish (option chart)':'Bearish (option chart)'):(t.sig==='BULLISH'?'Future long':'Future short');
const WHY={stop_loss:'SL',next_choch:'CHoCH',expiry:'Expiry',open:'open*'};
function statsOf(T){const net=T.map(t=>t.net);let eq=0,pk=0,dd=0;for(const v of net){eq+=v;pk=Math.max(pk,eq);dd=Math.min(dd,eq-pk);}
  const n=net.length,m=n?net.reduce((a,b)=>a+b,0)/n:0,sd=n>1?Math.sqrt(net.reduce((a,v)=>a+(v-m)**2,0)/(n-1)):0;
  const wins=net.filter(v=>v>0),loss=net.filter(v=>v<=0),sl=loss.reduce((a,b)=>a+b,0);
  return {trades:n,wins:wins.length,pts:sum(T,t=>t.pts),gross_inr:sum(T,t=>t.gross),charges_inr:sum(T,t=>t.chg),net_inr:net.reduce((a,b)=>a+b,0),max_dd_inr:dd,
    pf:loss.length&&sl?+(wins.reduce((a,b)=>a+b,0)/-sl).toFixed(2):null,t_stat:sd?+(m/(sd/Math.sqrt(n))).toFixed(2):null,mean:m,sd};}
const tradeMin=(t,sess)=>{const hm=s=>+s.slice(11,13)*60+ +s.slice(14,16);const d0=t.et.slice(0,10),d1=t.xt.slice(0,10);if(d0===d1)return hm(t.xt)-hm(t.et);
  const between=sess.filter(d=>d>d0&&d<d1).length;return (930-hm(t.et))+375*between+(hm(t.xt)-555);};
const capitalFor=T=>{const m=cur;if(m.variant==='FUT')return {cap:m.capital_fut,how:`futures margin ₹${(m.capital_fut/1e5).toFixed(1)}L per lot`};
  if(T.some(t=>t.pos==='SHORT'))return {cap:m.capital_opt_short,how:`short-option margin ₹${(m.capital_opt_short/1e5).toFixed(1)}L per lot`};
  const prem=T.length?sum(T,t=>t.ep*m.lot_size)/T.length:0;return {cap:prem,how:`average premium paid ${inr(prem)} per trade`};};
const riskPts=t=>(cur.variant==='OPT_FUT_SIGNAL'||t.sl==null)?null:Math.abs(t.ep-t.sl);   // R needs the stop in the traded instrument

// ================= below the chart
function renderBelow(){
  const m=cur,LOT=m.lot_size,T=sel(),sch=schemeOf(m),s=statsOf(T);
  const skipped=D.skipped.filter(x=>sch==='BOTH'||(sch==='LONG'||sch==='SHORT'?(!x.position||x.position===sch):(!x.opt_type||x.opt_type===sch))).length;
  const cv=skipped?{text:`Incomplete: ${s.trades} of ${s.trades+skipped} positions priced.`}:null;
  const exR=T.map(t=>{const rp=riskPts(t);return rp?t.pts/rp:null;}).filter(v=>v!=null);
  $('kpis').innerHTML=[['Net P&L',inr(s.net_inr)+star(cv),cv?`<span style="color:#9a5b00">incomplete · ${s.trades} of ${s.trades+skipped} priced</span>`:'gross − charges',cl(s.net_inr)],
    ['Trades',s.trades+(skipped?` of ${s.trades+skipped}`:''),`${T.filter(t=>t.pos==='LONG').length} long · ${T.filter(t=>t.pos==='SHORT').length} short`,''],
    ['Win rate',s.trades?Math.round(100*s.wins/s.trades)+'%':'—',`${s.wins} wins`,''],
    ['Profit factor',s.pf??'—','net wins ÷ net losses',''],
    ['Max drawdown',inr(s.max_dd_inr),'peak to trough, by trade',s.max_dd_inr<0?'neg':''],
    ['Expectancy',inr(s.mean),exR.length?`${fmt(exR.reduce((a,b)=>a+b,0)/exR.length,2)} R per trade`:'per trade',cl(s.mean)]]
    .map(([l,v,sub,c])=>`<div class="card kpi"><div class="l">${l}</div><div class="v ${c}">${v}</div><div class="s">${sub}</div></div>`).join('');
  renderCalendar(T);renderTrades(T,LOT);renderDaily(T);renderBreakdown(T);renderSignals();renderConfig();
  renderTab(document.querySelector('.tab.on').dataset.p);
}
function renderTab(p){const T=sel();({perf:()=>renderPerf(T),equity:()=>renderEquity(T),dd:()=>renderDD(T),dist:()=>renderDist(T),mc:()=>renderMC(T),robust:()=>renderRobust(T)}[p]||(()=>{}))();}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===b));
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('on',p.id==='p-'+b.dataset.p));renderTab(b.dataset.p);});

// ---- daily P&L heatmap (one square per session, week columns, Mon–Fri rows) + day stats
let CALM=null,HMSEL=null;
function renderCalendar(T){
  const by={};T.forEach(t=>{const d=t.xt.slice(0,10);(by[d]??=[]).push(t);});
  const sess=sessionsOf();if(!sess.length){$('cal').innerHTML='';return;}
  const net=d=>by[d]?sum(by[d],t=>t.net):null,vals=sess.map(net).filter(v=>v!=null),mx=Math.max(1,...vals.map(Math.abs));
  const color=v=>{if(v==null)return '';const k=Math.min(4,Math.ceil(Math.abs(v)/mx*4));
    return v>=0?['#c6e9dc','#8fd3bb','#4db894','#089981'][k-1]:['#fbd3d6','#f5a3aa','#ee6f7a','#e03444'][k-1];};
  const D0=new Date(sess[0]+'T00:00:00Z'),start=new Date(D0);start.setUTCDate(D0.getUTCDate()-((D0.getUTCDay()+6)%7));
  const end=new Date(sess.at(-1)+'T00:00:00Z'),set=new Set(sess),cells=[],mons=[];let col=0,lastMon='';
  for(const d=new Date(start);d<=end;d.setUTCDate(d.getUTCDate()+1)){const wd=(d.getUTCDay()+6)%7;if(wd>4)continue;
    const k=d.toISOString().slice(0,10);if(wd===0){const mk=k.slice(0,7);mons.push(mk!==lastMon?new Date(k+'T00:00:00Z').toLocaleDateString('en-GB',{month:'short',timeZone:'UTC'}):'');if(mk!==lastMon)lastMon=mk;col++;}
    if(!set.has(k)){cells.push(`<div class="hc x"></div>`);continue;}
    const v=net(k),n=by[k]?by[k].length:0;
    cells.push(`<div class="hc ${v==null?'z':''} ${k===HMSEL?'sel':''}" data-d="${k}" style="${v!=null?'background:'+color(v):''}" title="${new Date(k+'T00:00:00Z').toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric',timeZone:'UTC'})} · ${v==null?'no trades':inr(v)+' · '+n+' trade'+(n>1?'s':'')}"></div>`);}
  // day stats
  const days=sess.map(d=>[d,net(d)]).filter(x=>x[1]!=null),pos=days.filter(x=>x[1]>0),best=days.reduce((a,b)=>!a||b[1]>a[1]?b:a,null),worst=days.reduce((a,b)=>!a||b[1]<a[1]?b:a,null);
  let g=0,r=0,mg=0,mr=0;for(const [,v] of days){if(v>0){g++;r=0;}else{r++;g=0;}mg=Math.max(mg,g);mr=Math.max(mr,r);}
  const tot=sum(days,x=>x[1]),fd=d=>new Date(d+'T00:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'short',timeZone:'UTC'});
  $('cal').innerHTML=`<div class="hm"><div class="hmhead"><b>Daily P&amp;L</b><span class="sub">by exit day · hover for details, click to open the day</span></div>
      <div class="hmmon">${mons.map(m=>`<span>${m}</span>`).join('')}</div><div class="hmgrid">${cells.join('')}</div>
      <div class="hmlegend">loss <i style="background:#e03444"></i><i style="background:#f5a3aa"></i><i style="background:#ebedf0"></i><i style="background:#8fd3bb"></i><i style="background:#089981"></i> profit · grey = session without trades</div></div>
    <div class="hmstats"><div>Net<b class="${cl(tot)}">${inr(tot)}</b></div><div>Profitable days<b>${pos.length} of ${days.length}</b></div><div>Average day<b class="${cl(days.length?tot/days.length:0)}">${inr(days.length?tot/days.length:0)}</b></div>
      <div>Best day<b class="pos">${best?inr(best[1]):'—'}</b>${best?fd(best[0]):''}</div><div>Worst day<b class="neg">${worst?inr(worst[1]):'—'}</b>${worst?fd(worst[0]):''}</div><div>Longest run<b><span class="pos">${mg}</span> green · <span class="neg">${mr}</span> red</b>days in a row</div></div>`;
  $('cal').querySelectorAll('.hc[data-d]').forEach(c=>c.onclick=()=>{HMSEL=c.dataset.d;$('cal').querySelectorAll('.hc.sel').forEach(x=>x.classList.remove('sel'));c.classList.add('sel');openDay(c.dataset.d);});
}

// ---- trades, daily, breakdown, signals, config
function renderTrades(T,LOT){
  const cbTip=cb=>['Brokerage '+inr(cb.brokerage),'STT '+inr(cb.stt),'Exchange '+inr(cb.exchange),'SEBI '+inr(cb.sebi),'Stamp '+inr(cb.stamp),'GST '+inr(cb.gst)].join('&#10;');
  const und=cur.variant==='OPT_FUT_SIGNAL';let cum=0;
  $('ttrades').innerHTML=`<thead><tr><th>#</th><th>Position</th><th>Instrument</th><th>Signal</th><th>Entry</th><th class="num">SL${und?' (fut)':''}</th><th>Exit</th><th>Reason</th>${und?'<th class="num">Fut in → out</th>':''}<th class="num">Max profit</th><th class="num">Max loss</th><th class="num">Points</th><th class="num">Gross ₹</th><th class="num">Charges ₹</th><th class="num">Net ₹</th><th class="num">Cum. net ₹</th></tr></thead><tbody>`+
    T.map((t,i)=>{cum+=t.net;return `<tr class="z" data-a="${t.ets}" data-b="${t.xts}"><td>${i+1}</td><td><span class="pill ${t.pos==='LONG'?'long':'short'}">${t.pos}</span></td><td>${t.instr}${t.stale?' <span class="pill open" title="price from an earlier candle the same day">stale</span>':''}</td><td>${sigName(t)}</td><td>${t.et.slice(5,16)} @ ${t.ep}</td><td class="num">${t.sl??'—'}</td><td>${t.xt.slice(5,16)} @ ${t.xp}</td><td><span class="pill ${t.why==='stop_loss'?'short':t.open?'open':'grey'}">${WHY[t.why]}</span></td>${und?`<td class="num">${t.ue} → ${t.ux}</td>`:''}<td class="num pos" title="${inr(t.mfe*LOT)} per lot">${fmt(t.mfe)}</td><td class="num neg" title="${inr(t.mae*LOT)} per lot">${fmt(t.mae)}</td><td class="num ${cl(t.pts)}">${fmt(t.pts)}</td><td class="num ${cl(t.pts)}">${inr(t.gross)}</td><td class="num neg" title="${cbTip(t.cb)}">${inr(-t.chg)}</td><td class="num ${cl(t.net)}">${inr(t.net)}${t.open?'<span class="warn" title="open at the backtest end, valued at its last candle">*</span>':''}</td><td class="num ${cl(cum)}">${inr(cum)}</td></tr>`;}).join('')+'</tbody>';
  const op=T.filter(t=>t.open);
  $('opennote').innerHTML=op.length?`<div class="note"><b>*</b> ${op.length} position${op.length>1?'s':''} still open at the backtest end, valued at the last available candle: `+op.map(t=>`${t.pos.toLowerCase()} ${t.instr} from ${t.et.slice(5,16)} → ${t.xt.slice(5,16)} ${inr(t.net)}`).join(' · ')+'</div>':'';
  $('skipped').innerHTML=D.skipped.length?`${D.skipped.length} signal(s) skipped for missing option data: `+D.skipped.slice(0,8).map(x=>`${(x.entry_time||'').slice(5,16)} — ${x.why}`).join(' · ')+(D.skipped.length>8?' …':''):'';
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
  $('p-bdown').innerHTML=`<div class="grid2">${grp('By position',t=>t.pos==='LONG'?'Long':'Short')}${grp('By signal',sigName)}${grp('By instrument',t=>t.otype)}${grp('By exit reason',t=>({stop_loss:'Stop loss',next_choch:'Next CHoCH',expiry:'Expiry',open:'Open at end'})[t.why])}${grp('By entry time',t=>{const hm=t.et.slice(11,16);return hm<'10:30'?'09:15–10:30':hm<'12:00'?'10:30–12:00':hm<'13:30'?'12:00–13:30':'13:30–15:30';})}${grp('By holding',t=>t.et.slice(0,10)===t.xt.slice(0,10)?'Intraday':'Overnight')}</div>`;}
function renderSignals(){
  $('sighint').textContent=D.signals.length?'Every CHoCH on the futures chart, the AVWAP pair it started, and the SETUP that followed.':'Options (standalone): the signals are on each day\'s option chart — pick it in the session list above the chart.';
  $('tsignals').innerHTML=D.signals.length?'<thead><tr><th>CHoCH</th><th>Direction</th><th class="num">Protected</th><th>AVWAP from SH</th><th>AVWAP from SL</th><th>SETUP</th></tr></thead><tbody>'+
    D.signals.map(g=>`<tr><td>${g.time.slice(5,16)}</td><td><span class="pill ${g.dir==='up'?'long':'short'}">${g.dir==='up'?'future long':'future short'}</span></td><td class="num">${g.lvl}</td><td>${g.hi?g.hi[0].slice(5,16)+' @ '+g.hi[1]:'—'}</td><td>${g.lo?g.lo[0].slice(5,16)+' @ '+g.lo[1]:'—'}</td><td>${g.setup?g.setup.slice(5,16):'<span class="pill grey">none</span>'}</td></tr>`).join('')+'</tbody>':'';}
function renderConfig(){const m=cur,r=runOf(m),sch=D.charges,labs={code:'Code',break_mode:'Break mode',avwap_weight:'AVWAP weight',sl_rule:'Stop-loss rule',warmup_days:'Warm-up (sessions)',slippage_pts:'Slippage (pts/side)',lot_size:'Lot size',capital_fut:'Futures margin / lot (₹)',capital_opt_short:'Short option margin / lot (₹)',charge_code:'Charge schedule'};
  $('cfg').innerHTML=`<dt>Showing</dt><dd>${m.name} · ${SCH[schemeOf(m)]}${m.variant!=='FUT'?` · ${EXP[ck(curChoice)[0]]} · strike ${ck(curChoice)[1]}`:''}</dd><dt>Backtest</dt><dd>${r.label} · ${r.date_from} → ${r.date_to} · ${TFS[r.timeframe]}${r.design?' (design timeframe)':''}</dd>`+
    Object.entries(labs).map(([k,v])=>`<dt>${v}</dt><dd>${m[k]??'—'}</dd>`).join('')+
    `<dt>Brokerage</dt><dd>${sch.brokerage_flat?'₹'+sch.brokerage_flat+' flat per order':sch.brokerage_pct+'% or ₹'+sch.brokerage_cap+' per order'}</dd><dt>STT</dt><dd>${sch.stt_buy_pct}% buy · ${sch.stt_sell_pct}% sell</dd><dt>Exchange</dt><dd>${sch.exchange_pct}%</dd><dt>Stamp</dt><dd>${sch.stamp_buy_pct}% buy</dd><dt>GST</dt><dd>${sch.gst_pct}%</dd><dt>Note</dt><dd>${sch.notes}</dd>`;}

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
      Object.entries(r.choices).map(([c,x])=>`<tr class="z" data-c="${c}" style="${c===curChoice?'background:#eef2ff':''}"><td>${EXP[ck(c)[0]]}</td><td>${ck(c)[1]}</td><td class="num">${x.trades}${x.skipped?`<span class="warn" title="${x.skipped} skipped">*</span>`:''}</td><td class="num ${cl(x.long?.net_inr)}">${inr(x.long?.net_inr)}</td><td class="num ${cl(x.short?.net_inr)}">${inr(x.short?.net_inr)}</td><td class="num ${cl(x.ce?.net_inr)}">${inr(x.ce?.net_inr)}</td><td class="num ${cl(x.pe?.net_inr)}">${inr(x.pe?.net_inr)}</td><td class="num">${x.pf??'—'}</td></tr>`).join('')+'</tbody></table></div></div>':'');
  document.querySelectorAll('#p-robust tr.z').forEach(tr=>tr.onclick=()=>{const [e,k]=ck(tr.dataset.c);S().exp=e;S().strike=k;saveAll();openType();});
}

// ================= start
if(!fams.includes(ST.fam))ST.fam=fams[0];
openType();
</script></body></html>
