<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strategy dashboard</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--muted:#6b7280;--line:#e6e8ec;--up:#089981;--dn:#f23645;--acc:#2962ff;--pur:#7b1fa2;--rad:10px}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1600px;margin:0 auto;padding:12px 16px 40px}
header{margin-bottom:10px}h1{font-size:16px;font-weight:600;margin:0}.sub{color:var(--muted);font-size:12px}
.strats{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:10px;margin-bottom:12px}
.vrow{display:grid;grid-template-columns:1fr auto auto;gap:10px;align-items:baseline;padding:5px 8px;margin:0 -8px;border-radius:6px;font-variant-numeric:tabular-nums;cursor:pointer}
.vrow:hover{background:#f3f6ff}.vrow.on{background:#eef2ff}.vrow .vl{font-size:12px}.vrow .vs{font-size:11px;color:var(--muted)}.vrow b{font-size:13px}
.vhead{display:grid;grid-template-columns:1fr auto auto;gap:10px;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-top:8px;padding:0 0 2px;border-bottom:1px solid var(--line)}
.seg{display:inline-flex;background:#eceef2;border-radius:7px;padding:2px}
.seg button{border:0;background:transparent;padding:3px 9px;border-radius:5px;font:12px system-ui;color:var(--muted);cursor:pointer;white-space:nowrap}
.seg button.on{background:#fff;color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.08)}
.scard{background:var(--card);border:1px solid var(--line);border-radius:var(--rad);padding:10px 12px;cursor:pointer;transition:border-color .15s,box-shadow .15s}
.scard:hover{border-color:#c9ced6}.scard.on{border-color:var(--acc);box-shadow:0 0 0 2px rgba(41,98,255,.15)}
.scard .t{display:flex;justify-content:space-between;align-items:center;gap:8px;font-weight:600}
.scard .m{color:var(--muted);font-size:11px;margin-top:2px}
.scard .n{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;font-variant-numeric:tabular-nums}
.scard .n div{font-size:11px;color:var(--muted)}.scard .n b{display:block;font-size:14px;color:var(--ink)}
.tag{font-size:11px;font-weight:600;padding:1px 7px;border-radius:999px;background:#eef2ff;color:#3446b8;white-space:nowrap}
.tag.opt{background:#f3e8ff;color:#6b21a8}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--rad)}
.chartcard{display:flex;flex-direction:column;height:max(460px,calc(100vh - 60px));overflow:hidden}
.ctop{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px 10px;border-bottom:1px solid var(--line)}
.cbody{position:relative;flex:1;min-height:0}#chart{position:absolute;inset:0}
.ohlc{font:12px ui-monospace,Consolas,monospace;color:var(--muted);white-space:nowrap}.ohlc b{color:var(--ink);font-weight:500}
.nav{display:inline-flex;align-items:center;gap:4px}
.nav button,.nav select,.ctl select{font:12px system-ui;border:1px solid var(--line);background:#fff;border-radius:6px;padding:3px 8px;cursor:pointer;color:var(--ink)}
.ctl{display:inline-flex;align-items:center;gap:4px;font-size:12px;color:var(--muted)}
.layers{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:2px 9px;font-size:11px;color:var(--muted);cursor:pointer;user-select:none}
.chip.on{color:var(--ink);border-color:#c9ced6}.chip i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:12px 0}
.kpi{padding:10px 12px}.kpi .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.kpi .v{font-size:20px;font-weight:600;margin-top:2px;font-variant-numeric:tabular-nums}.kpi .s{color:var(--muted);font-size:11px}
.tabs{position:sticky;top:0;z-index:4;display:flex;gap:2px;background:var(--bg);padding-top:4px;border-bottom:1px solid var(--line);overflow-x:auto}
.tab{border:0;background:transparent;padding:8px 14px;font:13px system-ui;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
.tab.on{color:var(--ink);border-bottom-color:var(--acc);font-weight:600}
.panel{display:none;padding:12px 0}.panel.on{display:block}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600;text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);background:#fafbfc;position:sticky;top:0}
td{padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
tbody tr.z{cursor:pointer}tbody tr.z:hover{background:#f3f6ff}
.num{text-align:right}.pos{color:var(--up)}.neg{color:var(--dn)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600}
.pill.ce{background:#e6f6f2;color:#067a66}.pill.pe{background:#fdecee;color:#c0272f}.pill.open{background:#fff4e0;color:#9a5b00}.pill.grey{background:#eef0f3;color:#555}
.scroll{max-height:70vh;overflow:auto}
.rules{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
.rules .card{padding:12px 14px}.rules h3{margin:0 0 6px;font-size:13px}.rules ul{margin:0;padding-left:18px}.rules li{margin:3px 0}
.sw{display:inline-block;width:18px;text-align:center;font-weight:700}.hint{color:var(--muted);font-size:12px;margin:0 0 8px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:0}dt{color:var(--muted)}dd{margin:0}
.loading{position:absolute;inset:0;display:none;align-items:center;justify-content:center;background:rgba(255,255,255,.7);z-index:5;color:var(--muted)}
</style>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
</head><body><div class="wrap">
<header style="display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap"><div><h1>Strategy dashboard</h1><div class="sub">Foundation: swings → protected level → CHoCH → AVWAP pair → SETUP · variants: futures, option on future signal, option native</div></div>
<div><div class="sub" style="margin-bottom:3px">Test period</div><span class="seg" id="periodSeg"></span></div></header>
<div class="sub" id="periodNote" style="margin:-4px 0 10px"></div>
<div class="strats" id="families"></div>

<div class="card chartcard">
  <div class="ctop">
    <span class="seg" id="variantSeg" title="variant"></span>
    <span class="ctl" id="strikeCtl">Strike <select id="strike" title="strike choice"></select></span>
    <div class="nav" id="dayNav"><button id="prev" title="previous">‹</button><select id="series" title="session / contract"></select><button id="next" title="next">›</button><button id="all" title="load every session of this period into one chart">Full period</button></div>
    <div class="ohlc" id="ohlc"></div>
    <div class="layers" id="layers"></div>
  </div>
  <div class="cbody"><div id="chart"></div><div class="loading" id="loading">Loading…</div></div>
</div>

<div class="kpis" id="kpis"></div>
<div class="tabs">
  <button class="tab on" data-p="p-trades">Trades</button>
  <button class="tab" data-p="p-breakdown">Breakdown</button>
  <button class="tab" data-p="p-daily">Daily P&amp;L</button>
  <button class="tab" data-p="p-strikes">Strike comparison</button>
  <button class="tab" data-p="p-signals">Signals log</button>
  <button class="tab" data-p="p-config">Strategy config</button>
  <button class="tab" data-p="p-rules">Rules &amp; legend</button>
</div>
<div class="panel on" id="p-trades"><p class="hint">Click a trade to open it on the chart. Hover a charges cell for the breakdown.</p><div class="card scroll"><table id="ttrades"></table></div><div id="skipped" class="hint" style="margin-top:8px"></div></div>
<div class="panel" id="p-breakdown"><p class="hint">Same trades, grouped. Max profit / max loss = the best and worst the trade was showing before it closed (traded instrument, points before slippage).</p><div id="bdown"></div></div>
<div class="panel" id="p-daily"><p class="hint">Trades grouped by entry day.</p><div class="card scroll"><table id="tdaily"></table></div></div>
<div class="panel" id="p-strikes"><p class="hint">Every strike choice of this variant, same signals. Click a row to switch to it.</p><div class="card scroll"><table id="tstrikes"></table></div></div>
<div class="panel" id="p-signals"><p class="hint" id="sighint">Every CHoCH, the AVWAP pair it started, and the SETUP that followed.</p><div class="card scroll"><table id="tsignals"></table></div></div>
<div class="panel" id="p-config"><div class="card" style="padding:12px 14px"><dl id="cfg"></dl></div></div>
<div class="panel" id="p-rules"><div class="rules">
  <div class="card"><h3>Variants</h3><ul>
    <li><b>Futures</b> — signals and trades on NIFTY SEP FUT (long on bullish, short on bearish).</li>
    <li><b>Option · future signal</b> — same signals and exits as futures; buys CE on bullish / PE on bearish. Strike picked at the signal candle from spot.</li>
    <li><b>Option · native</b> — engine runs on the option's own candles; buy-only (bullish setups on the CE chart and on the PE chart). CE and PE contracts fixed each day at the first completed candle from spot.</li></ul></div>
  <div class="card"><h3>Strike choices</h3><ul>
    <li><b>ATRk</b> — spot ± k × ATR(14) of the strategy timeframe, out of the money (CE above spot, PE below), rounded to 50. Default ATR2.</li>
    <li><b>ATM / ITMn / OTMn</b> — spot rounded to 50, then n strikes (50 each) in/out of the money.</li>
    <li>Strikes are chosen from spot at decision time, never from where the market ended up. Full 29-Sep chain from Kite.</li></ul></div>
  <div class="card"><h3>Structure</h3><ul>
    <li><span class="sw" style="color:var(--up)">■</span>SH / <span style="color:var(--dn)">■</span> SL; ▼ / ▲ confirming candle. Faded dots: unconfirmed candidate.</li>
    <li><span class="sw" style="color:var(--pur)">┅</span>Protected level · <span style="color:var(--pur)">●</span> CHoCH · <span style="color:#9e9e9e">●</span> BOS. Breaks by touch.</li>
    <li><span class="sw" style="color:#ff6d00">━</span>AVWAP from previous SH, <span style="color:var(--acc)">━</span> from previous SL, started at each CHoCH.</li></ul></div>
  <div class="card"><h3>Fills, costs, stats</h3><ul>
    <li>Entry at the SETUP candle close. Stop: worse of candle open and stop; on a session's first candle, that candle's close. Exit otherwise at the next CHoCH close.</li>
    <li>Slippage per side from the strategy row (futures 5 pts, options 0.5 pt). Charges from the charge schedule (Strategy config).</li>
    <li>Points after slippage. Net = gross − charges. t-stat on per-trade net. Weeks by entry date.</li></ul></div>
</div></div>
</div>
<script>
/*DATA*/
const fmt=(v,d=1)=>v==null?'—':(v>0?'+':'')+(+v).toFixed(d);
const inr=v=>v==null?'—':(v<0?'−₹':'₹')+Math.abs(Math.round(v)).toLocaleString('en-IN');
const iso=t=>new Date(t*1000).toISOString();
const tfl=tf=>tf==='minute'?'1m':tf.replace('minute','m');
const VL={FUT:'Futures',OPT_FUT_SIGNAL:'Option · future signal',OPT_NATIVE:'Option · native'};
const $=id=>document.getElementById(id);
const cache={};let ch=null,cur=null,curChoice=null,D=null;
const on={trades:true,avwap:true,prot:true,struct:true,swings:true,vol:true};
const def=m=>m.variant==='FUT'?'-':m.strike_default;
let PER=PERIODS[0].code;try{const p=localStorage.getItem('period');if(PERIODS.some(x=>x.code===p))PER=p;}catch(e){}
const CH=m=>m.periods[PER];

// ---- family sections + variant cards ----
const fams=[...new Set(INDEX.map(m=>m.family))],ORDER=['FUT','OPT_FUT_SIGNAL','OPT_NATIVE'];
const variantsOf=f=>INDEX.filter(m=>m.family===f).sort((a,b)=>ORDER.indexOf(a.variant)-ORDER.indexOf(b.variant));
function renderCards(){
$('families').innerHTML=fams.map(f=>{const vs=variantsOf(f),m0=vs[0];
  return `<div class="scard" data-fam="${f}"><div class="t"><span>${m0.name.split(' · ').slice(0,2).join(' · ')}</span><span class="tag">${f} · ${tfl(m0.timeframe)}</span></div>
  <div class="m">${PERIODS.find(p=>p.code===PER).date_from} → ${PERIODS.find(p=>p.code===PER).date_to} · SL ${m0.sl_rule} · ${vs.length} variants</div>
  <div class="vhead"><span>Variant</span><span>Points</span><span>Net / lot</span></div>`+
  vs.map(m=>{const s=CH(m)[def(m)],wr=s.trades?Math.round(100*s.wins/s.trades):0;
    return `<div class="vrow" data-code="${m.code}"><div><div class="vl">${VL[m.variant]}</div><div class="vs">${m.variant==='FUT'?'futures':'strike '+def(m)} · ${s.trades} trades · ${wr}% win · PF ${s.pf??'—'}</div></div>
    <b class="${s.pts>=0?'pos':'neg'}">${fmt(s.pts)}</b><b class="${s.net_inr>=0?'pos':'neg'}">${inr(s.net_inr)}</b></div>`;}).join('')+'</div>';}).join('');
document.querySelectorAll('.vrow').forEach(el=>el.onclick=e=>{e.stopPropagation();select(el.dataset.code);});
document.querySelectorAll('.scard').forEach(el=>el.onclick=()=>{const vs=variantsOf(el.dataset.fam);
  const keep=cur&&cur.family!==el.dataset.fam?vs.find(m=>m.variant===cur.variant):null;select((keep||vs[0]).code);});
}
function renderPeriods(){
  $('periodSeg').innerHTML=PERIODS.map(p=>`<button data-p="${p.code}" class="${p.code===PER?'on':''}">${p.label}</button>`).join('');
  $('periodNote').textContent=PERIODS.find(p=>p.code===PER).notes||'';
  $('periodSeg').querySelectorAll('button').forEach(b=>b.onclick=()=>{PER=b.dataset.p;try{localStorage.setItem('period',PER);}catch(e){}
    renderPeriods();renderCards();select(cur.code,curChoice);});
}
renderPeriods();renderCards();

const getJSON=async f=>{if(!cache[f])cache[f]=fetch(f).then(r=>{if(!r.ok)throw new Error(f+' '+r.status);return r.json();});return cache[f];};
const busy=(on,txt)=>{$('loading').style.display=on?'flex':'none';if(txt)$('loading').textContent=txt;};
async function load(code,choice){const m=INDEX.find(x=>x.code===code),f=CH(m)[choice].file;
  busy(true,'Loading…');try{const d=await getJSON(f);d.base=f.slice(0,f.lastIndexOf('/')+1);return d;}finally{busy(false);}}
async function chunk(k){busy(true,'Loading chart…');try{return await getJSON(D.base+D.charts[k].file);}finally{busy(false);}}
let WIN=null,extending=false;
const merge=parts=>{const seen=new Set(),M=[];for(const c of parts)for(const m of c.M)if(!seen.has(m[0])){seen.add(m[0]);M.push(m);}
  const cat=k=>parts.flatMap(c=>c[k]);return {C:cat('C'),S:cat('S'),E:cat('E'),PR:cat('PR'),PAIR:cat('PAIR'),M};};
async function renderWin(range){const parts=[];for(let k=WIN.lo;k<=WIN.hi;k++)parts.push(await getJSON(D.base+D.charts[k].file));
  const c=merge(parts);drawChart(c,!range,range);return c;}
async function showChunk(k){$('series').value=k;busy(true,'Loading chart…');try{WIN={lo:k,hi:k};return await renderWin();}finally{busy(false);}}
async function extend(dir,r){          // called when the view reaches the edge of the loaded sessions
  if(extending||cur.variant==='OPT_NATIVE')return;
  const k=dir<0?WIN.lo-1:WIN.hi+1;if(k<0||k>=D.charts.length)return;
  extending=true;busy(true,dir<0?'Loading earlier session…':'Loading next session…');
  try{const add=await getJSON(D.base+D.charts[k].file);
    if(dir<0){WIN.lo=k;await renderWin({from:r.from+add.C.length,to:r.to+add.C.length});}else{WIN.hi=k;await renderWin(r);}
  }finally{busy(false);setTimeout(()=>extending=false,150);}}

async function select(code,choice){
  cur=INDEX.find(x=>x.code===code);curChoice=choice??def(cur);
  if(!CH(cur)[curChoice])curChoice=def(cur);
  document.querySelectorAll('.scard').forEach(el=>el.classList.toggle('on',el.dataset.fam===cur.family));
  document.querySelectorAll('.vrow').forEach(el=>el.classList.toggle('on',el.dataset.code===code));
  $('variantSeg').innerHTML=variantsOf(cur.family).map(m=>`<button data-code="${m.code}" class="${m.code===code?'on':''}">${VL[m.variant]}</button>`).join('');
  $('variantSeg').querySelectorAll('button').forEach(b=>b.onclick=()=>select(b.dataset.code,cur.variant!=='FUT'&&CH(INDEX.find(x=>x.code===b.dataset.code))[curChoice]?curChoice:undefined));
  try{localStorage.setItem('strat',code);}catch(e){}
  const opt=cur.variant!=='FUT';$('strikeCtl').style.display=opt?'':'none';
  $('strike').innerHTML=Object.keys(CH(cur)).map(c=>`<option value="${c}">${c}${c===cur.strike_default?' (default)':''} · ${inr(CH(cur)[c].net_inr)}</option>`).join('');
  $('strike').value=curChoice;
  D=await load(code,curChoice);
  $('series').innerHTML=D.charts.map((c,i)=>`<option value="${i}">${c.label}</option>`).join('');
  $('all').style.display=cur.variant==='OPT_NATIVE'?'none':'';   // native charts are different contracts per day
  renderTables();
  await showChunk(D.charts.length-1);
}
$('strike').onchange=()=>select(cur.code,$('strike').value);
$('series').onchange=()=>showChunk(+$('series').value);
$('prev').onclick=()=>{const k=+$('series').value;if(k>0)showChunk(k-1);};
$('next').onclick=()=>{const k=+$('series').value;if(k<D.charts.length-1)showChunk(k+1);};
$('all').onclick=async()=>{   // explicit full-period load: fetch every session chunk and merge
  const n=D.charts.length;
  for(let k=0;k<n;k++){busy(true,`Loading full period… ${k+1}/${n}`);await getJSON(D.base+D.charts[k].file);}
  busy(false);WIN={lo:0,hi:n-1};await renderWin(null);
};

function drawChart(CH,single,range){
  const {C,S,E,PR,PAIR,M}=CH;
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
  for(const [k,t,p,ct] of S){const hi=k==='H',col=hi?'#089981':'#f23645';
    MK.swings.push({time:t,position:hi?'aboveBar':'belowBar',color:col,shape:'square',size:0.1});
    MK.swings.push({time:ct,position:hi?'aboveBar':'belowBar',color:col,shape:hi?'arrowDown':'arrowUp',size:0.5});
    line('swings',{color:col,lineWidth:1},t===ct?[{time:t,value:p}]:[{time:t,value:p},{time:ct,value:p}]);}
  {const pm=new Map(PR);line('prot',{color:'#7b1fa2',lineWidth:1,lineStyle:2,lineType:1},C.map(r=>pm.has(r[0])?{time:r[0],value:pm.get(r[0])}:{time:r[0]}));}
  for(const a of PAIR){const col=a.side==='H'?'#ff6d00':'#2962ff';
    line('avwap',{color:col,lineWidth:2},a.live.map(([x,v])=>({time:x,value:v})));
    if(a.back.length>1)line('avwap',{color:col,lineWidth:1,lineStyle:1},a.back.map(([x,v])=>({time:x,value:v})));}
  for(const [x,kind,dir] of E)MK.struct.push({time:x,position:dir==='up'?'aboveBar':'belowBar',color:kind==='BOS'?'#9e9e9e':'#7b1fa2',shape:'circle',size:kind==='BOS'?0.2:0.5,text:kind==='BOS'?'':'CHoCH'});
  const tmin=C[0][0],tmax=C[C.length-1][0];
  for(const [et0,ep,xt,xp,d,pts,open,sl,why] of M){const up=d==='up',win=pts>0,native=cur.variant==='OPT_NATIVE';
    const lbl=cur.variant==='FUT'?(up?'LONG':'SHORT'):(native?'BUY':(up?'CE':'PE'));const xe=Math.min(xt,tmax),et=Math.max(et0,tmin);
    if(et0>=tmin)MK.trades.push({time:et0,position:up?'belowBar':'aboveBar',color:'#111',shape:up?'arrowUp':'arrowDown',size:1.5,text:lbl});
    if(xt<=tmax)MK.trades.push({time:xt,position:up?'aboveBar':'belowBar',color:win?'#089981':'#f23645',shape:'circle',size:0.9,text:(why==='stop_loss'?'SL ':open?'OPEN ':'')+fmt(pts)});
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
  if(range)ch.timeScale().setVisibleLogicalRange(range);
  else if(single)ch.timeScale().fitContent();else{const n=C.length,per=cur.timeframe==='minute'?375:75;ch.timeScale().setVisibleLogicalRange({from:n-per-2,to:n+2});}
  if(WIN)ch.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(!r||extending)return;   // scroll / zoom out past the loaded data
    if(r.from<5&&WIN.lo>0)extend(-1,r);else if(r.to>C.length+2&&WIN.hi<D.charts.length-1)extend(1,r);});
  CH.zoom=(a,b)=>{const idx=t=>{let lo=0,hi=C.length-1;while(lo<hi){const m=(lo+hi)>>1;if(C[m][0]<t)lo=m+1;else hi=m;}return lo;};
    const pad=cur.timeframe==='minute'?30:12;ch.timeScale().setVisibleLogicalRange({from:idx(a)-pad,to:idx(b)+pad});};
}

async function openTrade(et,xt){
  let k=D.charts.findIndex(c=>c.marks.includes(et));if(k<0)k=0;
  const c=await showChunk(k);c.zoom(et,xt);document.querySelector('.chartcard').scrollIntoView({behavior:'smooth',block:'start'});
}

function renderTables(){
  const m=cur,LOT=m.lot_size,sum=(a,f)=>a.reduce((s,t)=>s+f(t),0);
  const T=D.trades.map(([side,instr,strike,cht,et,ep,sl,xt,xp,why,pts,gross,chg,net,open,cb,ue,ux,stale,mfe,mae])=>({side,instr,strike,cht,et,ep,sl,xt,xp,why,pts,gross,chg,net,open,cb,ue,ux,stale,mfe:mfe??0,mae:mae??0,
    ets:Date.parse(et.replace(' ','T')+'Z')/1000,xts:Date.parse(xt.replace(' ','T')+'Z')/1000}));
  const SIDES=m.variant==='FUT'?[['CE','Long P&L'],['PE','Short P&L']]:m.variant==='OPT_FUT_SIGNAL'?[['CE','CE (bullish) P&L'],['PE','PE (bearish) P&L']]:[['CE','CE buys P&L'],['PE','PE buys P&L']];
  const s=D.stats,W=T.filter(t=>t.net>0),Ls=T.filter(t=>t.net<=0),avg=a=>a.length?sum(a,t=>t.net)/a.length:0;
  const WHY={stop_loss:'SL',next_choch:'CHoCH',open:'open'};
  const K=[['Points',fmt(s.pts),`after ${m.slippage_pts} pt/side slippage`,s.pts>=0?'pos':'neg'],
    ['Gross P&L',inr(s.gross_inr),`points × ${LOT} (1 lot)`,s.gross_inr>=0?'pos':'neg'],
    ['Charges',inr(-s.charges_inr),`${inr(T.length?s.charges_inr/T.length:0)} / trade`,'neg'],
    ['Net P&L',inr(s.net_inr),'gross − charges',s.net_inr>=0?'pos':'neg'],
    ['Trades',s.trades,`${T.filter(t=>t.side==='CE').length} CE · ${T.filter(t=>t.side==='PE').length} PE`+(D.skipped.length?` · ${D.skipped.length} skipped`:''),''],
    ['Win rate',s.trades?Math.round(100*s.wins/s.trades)+'%':'—',`avg ${inr(avg(W))} / ${inr(avg(Ls))}`,''],
    ['Profit factor',s.pf??'—','net wins ÷ net losses',''],
    ['t-stat',s.t_stat??'—','per-trade net; |t|<2 ≈ noise',''],
    ['Weeks +',`${s.pos_weeks}/${s.weeks}`,s.worst_week?`worst ${s.worst_week[0]} ${inr(s.worst_week[1])}`:'',''],
    ['Max drawdown',inr(s.max_dd_inr),'on net P&L',s.max_dd_inr<0?'neg':''],
    ['Stops hit',T.filter(t=>t.why==='stop_loss').length,`${T.filter(t=>t.open).length} open`,''],
    ...SIDES.map(([k,lbl])=>{const a=T.filter(t=>t.side===k),n=sum(a,t=>t.net);return [lbl,inr(n),a.length?`${a.length} trades · ${Math.round(100*a.filter(t=>t.net>0).length/a.length)}% win · ${fmt(sum(a,t=>t.pts))} pts`:'no trades',n>0?'pos':n<0?'neg':''];}),
    ['Avg max profit',fmt(T.length?sum(T,t=>t.mfe)/T.length:0)+' pts',`gave back ${fmt(T.length?sum(T,t=>t.mfe-(t.pts+2*m.slippage_pts))/T.length:0)} pts on avg`,'pos'],
    ['Avg max loss',fmt(T.length?sum(T,t=>t.mae)/T.length:0)+' pts',`worst ${fmt(Math.min(0,...T.map(t=>t.mae)))} pts`,'neg']];
  $('kpis').innerHTML=K.map(([l,v,sub,c])=>`<div class="card kpi"><div class="l">${l}</div><div class="v ${c}">${v}</div><div class="s">${sub}</div></div>`).join('');
  const cbTip=cb=>['Brokerage '+inr(cb.brokerage),'STT '+inr(cb.stt),'Exchange '+inr(cb.exchange),'SEBI '+inr(cb.sebi),'Stamp '+inr(cb.stamp),'GST '+inr(cb.gst)].join('&#10;');
  const und=m.variant==='OPT_FUT_SIGNAL';let cum=0;
  $('ttrades').innerHTML=`<thead><tr><th>#</th><th>Side</th><th>Instrument</th><th>Entry</th><th class="num">SL${und?' (fut)':''}</th><th>Exit</th><th>Reason</th>${und?'<th class="num">Fut in → out</th>':''}<th class="num">Max profit</th><th class="num">Max loss</th><th class="num">Points</th><th class="num">Gross ₹</th><th class="num">Charges ₹</th><th class="num">Net ₹</th><th class="num">Cum. net ₹</th></tr></thead><tbody>`+
    T.map((t,i)=>{cum+=t.net;const c=t.pts>0?'pos':'neg',cn=t.net>0?'pos':'neg';
      return `<tr class="z" data-a="${t.ets}" data-b="${t.xts}"><td>${i+1}</td><td><span class="pill ${t.side==='CE'?'ce':'pe'}">${t.side}</span></td><td>${t.instr}${t.stale?' <span class="pill open" title="price from an earlier candle the same day">stale</span>':''}</td><td>${t.et.slice(5,16)} @ ${t.ep}</td><td class="num">${t.sl??'—'}</td><td>${t.xt.slice(5,16)} @ ${t.xp}</td><td><span class="pill ${t.why==='stop_loss'?'pe':t.open?'open':'grey'}">${WHY[t.why]}</span></td>${und?`<td class="num">${t.ue} → ${t.ux}</td>`:''}<td class="num pos" title="${inr(t.mfe*LOT)} per lot">${fmt(t.mfe)}</td><td class="num neg" title="${inr(t.mae*LOT)} per lot">${fmt(t.mae)}</td><td class="num ${c}">${fmt(t.pts)}</td><td class="num ${c}">${inr(t.gross)}</td><td class="num neg" title="${cbTip(t.cb)}">${inr(-t.chg)}</td><td class="num ${cn}">${inr(t.net)}</td><td class="num ${cum>=0?'pos':'neg'}">${inr(cum)}</td></tr>`;}).join('')+
    `</tbody><tfoot><tr style="font-weight:600"><td colspan="${und?8:7}">Total</td><td class="num pos">${fmt(sum(T,t=>t.mfe))}</td><td class="num neg">${fmt(sum(T,t=>t.mae))}</td><td class="num">${fmt(s.pts)}</td><td class="num">${inr(s.gross_inr)}</td><td class="num neg">${inr(-s.charges_inr)}</td><td class="num ${s.net_inr>=0?'pos':'neg'}">${inr(s.net_inr)}</td><td></td></tr></tfoot>`;
  $('skipped').innerHTML=D.skipped.length?`${D.skipped.length} signal(s) skipped: `+D.skipped.slice(0,8).map(x=>`${(x.entry_time||'').slice(5,16)} ${x.side} — ${x.why}`).join(' · ')+(D.skipped.length>8?' …':''):'';
  document.querySelectorAll('#ttrades tr.z').forEach(r=>r.onclick=()=>openTrade(+r.dataset.a,+r.dataset.b));
  const byDay={};T.forEach(t=>(byDay[t.et.slice(0,10)]??=[]).push(t));let dc=0;const cl=v=>v>0?'pos':v<0?'neg':'';
  $('tdaily').innerHTML='<thead><tr><th>Day</th><th class="num">Trades</th><th class="num">Wins</th><th class="num">Points</th><th class="num">Gross ₹</th><th class="num">Charges ₹</th><th class="num">Net ₹</th><th class="num">Cum. net ₹</th></tr></thead><tbody>'+
    Object.keys(byDay).sort().map(d=>{const a=byDay[d],p=sum(a,t=>t.pts),g=sum(a,t=>t.gross),c=sum(a,t=>t.chg),nt=g-c;dc+=nt;
      return `<tr class="z" data-a="${a[0].ets}" data-b="${a[a.length-1].xts}"><td>${d}</td><td class="num">${a.length}</td><td class="num">${a.filter(t=>t.net>0).length}</td><td class="num ${cl(p)}">${fmt(p)}</td><td class="num ${cl(g)}">${inr(g)}</td><td class="num neg">${inr(-c)}</td><td class="num ${cl(nt)}">${inr(nt)}</td><td class="num ${dc>=0?'pos':'neg'}">${inr(dc)}</td></tr>`;}).join('')+'</tbody>';
  document.querySelectorAll('#tdaily tr.z').forEach(r=>r.onclick=()=>openTrade(+r.dataset.a,+r.dataset.b));
  const grp=(title,keyOf,order)=>{const g={};T.forEach(t=>(g[keyOf(t)]??=[]).push(t));const ks=order?order.filter(k=>g[k]):Object.keys(g).sort();
    return `<h3 style="font-size:13px;margin:14px 0 6px">${title}</h3><div class="card scroll"><table><thead><tr><th>${title.split(' ').pop()}</th><th class="num">Trades</th><th class="num">Win %</th><th class="num">Points</th><th class="num">Gross ₹</th><th class="num">Charges ₹</th><th class="num">Net ₹</th><th class="num">Avg net ₹</th><th class="num">Avg max profit</th><th class="num">Avg max loss</th></tr></thead><tbody>`+
    ks.map(k=>{const a=g[k],n=sum(a,t=>t.net);return `<tr><td>${k}</td><td class="num">${a.length}</td><td class="num">${Math.round(100*a.filter(t=>t.net>0).length/a.length)}%</td><td class="num ${cl(sum(a,t=>t.pts))}">${fmt(sum(a,t=>t.pts))}</td><td class="num">${inr(sum(a,t=>t.gross))}</td><td class="num neg">${inr(-sum(a,t=>t.chg))}</td><td class="num ${cl(n)}">${inr(n)}</td><td class="num ${cl(n)}">${inr(n/a.length)}</td><td class="num pos">${fmt(sum(a,t=>t.mfe)/a.length)}</td><td class="num neg">${fmt(sum(a,t=>t.mae)/a.length)}</td></tr>`;}).join('')+'</tbody></table></div>';};
  const sideName=Object.fromEntries(SIDES.map(([k,l])=>[k,l.replace(' P&L','')]));
  $('bdown').innerHTML=grp('By side',t=>sideName[t.side],SIDES.map(x=>x[1].replace(' P&L','')))+grp('By exit reason',t=>({stop_loss:'Stop loss',next_choch:'Next CHoCH',open:'Open'})[t.why])+
    grp('By entry time',t=>{const hm=t.et.slice(11,16);return hm<'10:30'?'09:15–10:30':hm<'12:00'?'10:30–12:00':hm<'13:30'?'12:00–13:30':'13:30–15:30';})+
    grp('By holding',t=>t.et.slice(0,10)===t.xt.slice(0,10)?'Intraday':'Overnight');
  const opt=m.variant!=='FUT';
  $('tstrikes').innerHTML=opt?'<thead><tr><th>Strike choice</th><th class="num">Trades</th><th class="num">Win %</th><th class="num">Points</th><th class="num">Gross ₹</th><th class="num">Charges ₹</th><th class="num">Net ₹</th><th class="num">PF</th><th class="num">t-stat</th><th class="num">Weeks +</th></tr></thead><tbody>'+
    Object.entries(CH(m)).map(([c,x])=>`<tr class="z" data-c="${c}" style="${c===curChoice?'background:#eef2ff':''}"><td>${c}${c===m.strike_default?' <span class="pill grey">default</span>':''}</td><td class="num">${x.trades}</td><td class="num">${x.trades?Math.round(100*x.wins/x.trades):0}%</td><td class="num ${cl(x.pts)}">${fmt(x.pts)}</td><td class="num ${cl(x.gross_inr)}">${inr(x.gross_inr)}</td><td class="num neg">${inr(-x.charges_inr)}</td><td class="num ${cl(x.net_inr)}">${inr(x.net_inr)}</td><td class="num">${x.pf??'—'}</td><td class="num">${x.t_stat??'—'}</td><td class="num">${x.pos_weeks}/${x.weeks}</td></tr>`).join('')+'</tbody>'
    :'<tbody><tr><td class="hint">Futures variant has no strike choice.</td></tr></tbody>';
  document.querySelectorAll('#tstrikes tr.z').forEach(r=>r.onclick=()=>select(cur.code,r.dataset.c));
  $('sighint').textContent=D.signals.length?'Every CHoCH on the signal chart, the AVWAP pair it started, and the SETUP that followed.':"Option · native: signals come from each day's CE / PE chart — pick it in the Chart selector.";
  $('tsignals').innerHTML=D.signals.length?'<thead><tr><th>CHoCH</th><th>Direction</th><th class="num">Protected</th><th>AVWAP from SH</th><th>AVWAP from SL</th><th>SETUP</th></tr></thead><tbody>'+
    D.signals.map(g=>`<tr><td>${g.time.slice(5,16)}</td><td><span class="pill ${g.dir==='up'?'ce':'pe'}">${g.dir==='up'?'▲ up':'▼ down'}</span></td><td class="num">${g.lvl}</td><td>${g.hi?g.hi[0].slice(5,16)+' @ '+g.hi[1]:'—'}</td><td>${g.lo?g.lo[0].slice(5,16)+' @ '+g.lo[1]:'—'}</td><td>${g.setup?g.setup.slice(5,16):'<span class="pill grey">none</span>'}</td></tr>`).join('')+'</tbody>':'';
  const lab={code:'Code',family:'Family',variant:'Variant',instrument:'Instrument',timeframe:'Timeframe',break_mode:'Break mode',avwap_weight:'AVWAP weight',entry_rule:'Entry rule',exit_rule:'Exit rule',sl_rule:'Stop-loss rule',slippage_pts:'Slippage (pts/side)',strike_choices:'Strike choices',strike_default:'Default strike',atr_period:'ATR period',lot_size:'Lot size',charge_code:'Charge schedule'};
  const sch=D.charges;
  $('cfg').innerHTML=Object.entries(lab).map(([k,v])=>`<dt>${v}</dt><dd>${m[k]??'—'}</dd>`).join('')+`<dt>Showing</dt><dd>${PERIODS.find(p=>p.code===PER).label} · strike choice ${curChoice}</dd>`+
    `<dt>Brokerage</dt><dd>${sch.brokerage_flat?'₹'+sch.brokerage_flat+' flat per order':sch.brokerage_pct+'% or ₹'+sch.brokerage_cap+' per order, whichever lower'}</dd><dt>STT</dt><dd>${sch.stt_buy_pct}% buy · ${sch.stt_sell_pct}% sell</dd><dt>Exchange txn</dt><dd>${sch.exchange_pct}%</dd><dt>SEBI</dt><dd>${sch.sebi_pct}%</dd><dt>Stamp duty</dt><dd>${sch.stamp_buy_pct}% buy</dd><dt>GST</dt><dd>${sch.gst_pct}% on brokerage + exchange + SEBI</dd><dt>Note</dt><dd>${sch.notes}</dd>`;
}

document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===b));
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('on',p.id===b.dataset.p));});
let start=INDEX[0].code;try{const c=localStorage.getItem('strat');if(INDEX.some(m=>m.code===c))start=c;}catch(e){}
select(start);
</script></body></html>
