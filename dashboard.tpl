<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strategy dashboard</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--muted:#6b7280;--line:#e6e8ec;--up:#089981;--dn:#f23645;--acc:#2962ff;--pur:#7b1fa2;--rad:10px}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1600px;margin:0 auto;padding:12px 16px 40px}
header{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px}
h1{font-size:16px;font-weight:600;margin:0}.sub{color:var(--muted);font-size:12px}
.strats{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;margin-bottom:12px}
.scard{background:var(--card);border:1px solid var(--line);border-radius:var(--rad);padding:10px 12px;cursor:pointer;transition:border-color .15s,box-shadow .15s}
.scard:hover{border-color:#c9ced6}.scard.on{border-color:var(--acc);box-shadow:0 0 0 2px rgba(41,98,255,.15)}
.scard .t{display:flex;justify-content:space-between;align-items:center;gap:8px;font-weight:600}
.scard .m{color:var(--muted);font-size:11px;margin-top:2px}
.scard .n{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;font-variant-numeric:tabular-nums}
.scard .n div{font-size:11px;color:var(--muted)}.scard .n b{display:block;font-size:15px;color:var(--ink)}
.tf{font-size:11px;font-weight:600;padding:1px 7px;border-radius:999px;background:#eef2ff;color:#3446b8}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--rad)}
.chartcard{display:flex;flex-direction:column;height:max(460px,calc(100vh - 60px));overflow:hidden}
.ctop{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px 10px;border-bottom:1px solid var(--line)}
.cbody{position:relative;flex:1;min-height:0}#chart{position:absolute;inset:0}
.ohlc{font:12px ui-monospace,Consolas,monospace;color:var(--muted);white-space:nowrap}.ohlc b{color:var(--ink);font-weight:500}
.nav{display:inline-flex;align-items:center;gap:4px}
.nav button,.nav select{font:12px system-ui;border:1px solid var(--line);background:#fff;border-radius:6px;padding:3px 8px;cursor:pointer;color:var(--ink)}
.layers{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:2px 9px;font-size:11px;color:var(--muted);cursor:pointer;user-select:none}
.chip.on{color:var(--ink);border-color:#c9ced6}.chip i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:12px 0}
.kpi{padding:10px 12px}.kpi .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.kpi .v{font-size:20px;font-weight:600;margin-top:2px;font-variant-numeric:tabular-nums}.kpi .s{color:var(--muted);font-size:11px}
.tabs{position:sticky;top:0;z-index:4;display:flex;gap:2px;background:var(--bg);padding-top:4px;border-bottom:1px solid var(--line)}
.tab{border:0;background:transparent;padding:8px 14px;font:13px system-ui;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
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
</style>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
</head><body><div class="wrap">
<header><div><h1>Strategy dashboard</h1><div class="sub">Foundation: swings → protected level → CHoCH → AVWAP pair → SETUP · NIFTY futures · P&amp;L in futures points</div></div></header>
<div class="strats" id="strats"></div>

<div class="card chartcard">
  <div class="ctop">
    <div class="nav"><button id="prev" title="previous day">‹</button><select id="day"></select><button id="next" title="next day">›</button><button id="all">All</button></div>
    <div class="ohlc" id="ohlc"></div>
    <div class="layers" id="layers"></div>
  </div>
  <div class="cbody"><div id="chart"></div></div>
</div>

<div class="kpis" id="kpis"></div>
<div class="tabs">
  <button class="tab on" data-p="p-trades">Trades</button>
  <button class="tab" data-p="p-daily">Daily P&amp;L</button>
  <button class="tab" data-p="p-signals">Signals log</button>
  <button class="tab" data-p="p-config">Strategy config</button>
  <button class="tab" data-p="p-rules">Rules &amp; legend</button>
</div>
<div class="panel on" id="p-trades"><p class="hint">Click a trade to zoom the chart to it. Hover a charges cell for the breakdown.</p><div class="card scroll"><table id="ttrades"></table></div></div>
<div class="panel" id="p-daily"><p class="hint">Trades grouped by entry day. Click a day to open it on the chart.</p><div class="card scroll"><table id="tdaily"></table></div></div>
<div class="panel" id="p-signals"><p class="hint">Every CHoCH, the AVWAP pair it started, and the SETUP that followed. Click to zoom.</p><div class="card scroll"><table id="tsignals"></table></div></div>
<div class="panel" id="p-config"><div class="card" style="padding:12px 14px"><dl id="cfg"></dl></div></div>
<div class="panel" id="p-rules"><div class="rules">
  <div class="card"><h3>Swings</h3><ul>
    <li><span class="sw" style="color:var(--up)">■</span>SH / <span style="color:var(--dn)">■</span> SL on the swing candle; line to the confirming candle (▼ / ▲).</li>
    <li>SH confirms when a later candle breaks the SH candle's low (SL mirrored). Break = touch or close per strategy.</li>
    <li>Faded dots: running candidate, not yet confirmed.</li></ul></div>
  <div class="card"><h3>Structure</h3><ul>
    <li><span class="sw" style="color:var(--pur)">┅</span>Protected low (uptrend): latest unbroken SL that sat below the AVWAP when confirmed. Protected high mirrors it.</li>
    <li><span class="sw" style="color:var(--pur)">●</span>CHoCH: protected level broken; trend flips if the AVWAP is broken too.</li>
    <li><span class="sw" style="color:#9e9e9e">●</span>BOS: latest swing in the trend direction broken.</li></ul></div>
  <div class="card"><h3>AVWAP</h3><ul>
    <li>Typical price (H+L+C)/3, weighted by futures volume (or equal weight per strategy).</li>
    <li><span class="sw" style="color:#ff6d00">━</span>From previous SH and <span style="color:var(--acc)">━</span> from previous SL, started at every CHoCH until the next one. Dotted = back-filled.</li></ul></div>
  <div class="card"><h3>Trades</h3><ul>
    <li><b>Entry</b> — SETUP candle close: after a CHoCH, both AVWAPs slope with it and a candle closes beyond the CHoCH candle's low (PE) / high (CE).</li>
    <li><b>Stop loss</b> — <i>choch_candle</i> (5 min): CHoCH candle high for PE / low for CE. <i>prev_swing</i> (1 min): latest confirmed SH for PE / SL for CE at entry. Hit by touch; gap-through fills at the open; SL wins if it and the CHoCH exit fall on the same candle.</li>
    <li><b>Exit</b> — stop loss, else close of the next CHoCH candle; open trades marked to the last close.</li>
    <li>Points = futures points. Gross ₹ = points × lot. Charges = NSE futures round trip per the strategy's charge schedule (Strategy config tab). Net ₹ = gross − charges. Not option premium.</li></ul></div>
</div></div>
</div>
<script>
/*DATA*/
const fmt=(v,d=1)=>(v>0?'+':'')+v.toFixed(d);
const inr=v=>(v<0?'−₹':'₹')+Math.abs(Math.round(v)).toLocaleString('en-IN');
const iso=t=>new Date(t*1000).toISOString();
const tfl=tf=>tf==='minute'?'1m':tf.replace('minute','m');
const $=id=>document.getElementById(id);
let ch=null,cur=null;
const on={trades:true,avwap:true,prot:true,struct:true,swings:true,vol:true};

// ---- strategy cards ----
$('strats').innerHTML=STRATS.map((s,i)=>{const m=s.meta,wr=m.trades?Math.round(100*m.wins/m.trades):0;
  return `<div class="scard" data-i="${i}"><div class="t"><span>${m.name}</span><span class="tf">${tfl(m.timeframe)}</span></div>
  <div class="m">${m.code} · ${m.instrument} · ${m.date_from} → ${m.date_to}</div>
  <div class="n"><div>Points<b class="${m.net_pts>=0?'pos':'neg'}">${fmt(m.net_pts)}</b></div><div>Gross<b class="${m.gross_inr>=0?'pos':'neg'}">${inr(m.gross_inr)}</b></div><div>Charges<b class="neg">${inr(-m.charges_inr)}</b></div><div>Net<b class="${m.net_inr>=0?'pos':'neg'}">${inr(m.net_inr)}</b></div></div>
  <div class="m" style="margin-top:6px">${m.trades} trades · ${wr}% win</div></div>`;}).join('');
document.querySelectorAll('.scard').forEach(el=>el.onclick=()=>select(+el.dataset.i));

function select(i){
  document.querySelectorAll('.scard').forEach(el=>el.classList.toggle('on',+el.dataset.i===i));
  cur=STRATS[i];try{localStorage.setItem('strat',cur.meta.code);}catch(e){}
  render(cur);
}

function render(D){
  const {C,S,E,PR,PAIR,TR,meta}=D,LOT=meta.lot_size;
  if(ch){ch.remove();ch=null;}
  ch=LightweightCharts.createChart($('chart'),{autoSize:true,
    layout:{background:{color:'#fff'},textColor:'#4b5563',fontFamily:'system-ui'},
    grid:{vertLines:{color:'#f3f4f6'},horzLines:{color:'#f3f4f6'}},rightPriceScale:{borderColor:'#e6e8ec'},
    timeScale:{timeVisible:true,secondsVisible:false,rightOffset:4,borderColor:'#e6e8ec'},crosshair:{mode:0},
    handleScroll:{mouseWheel:false,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},
    handleScale:{mouseWheel:false,pinch:true,axisPressedMouseMove:true},
    localization:{timeFormatter:t=>iso(t).slice(5,16).replace('T',' ')}});
  const cs=ch.addCandlestickSeries({upColor:'#089981',downColor:'#f23645',wickUpColor:'#089981',wickDownColor:'#f23645',borderVisible:false});
  cs.priceScale().applyOptions({scaleMargins:{top:0.06,bottom:0.2}});
  cs.setData(C.map(r=>({time:r[0],open:r[1],high:r[2],low:r[3],close:r[4]})));
  const base={lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false,autoscaleInfoProvider:()=>null}; // candles alone set the price scale
  const L={vol:[],swings:[],avwap:[],prot:[],trades:[]};
  const line=(layer,opt,data)=>{const s=ch.addLineSeries({...base,...opt,visible:on[layer]});s.setData(data);L[layer].push(s);};
  const vs=ch.addHistogramSeries({priceScaleId:'vol',priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false,visible:on.vol});
  ch.priceScale('vol').applyOptions({scaleMargins:{top:0.84,bottom:0}});
  vs.setData(C.map(r=>({time:r[0],value:r[7],color:r[4]>=r[1]?'rgba(8,153,129,.35)':'rgba(242,54,69,.35)'})));L.vol.push(vs);
  for(const [idx,col] of [[5,'rgba(8,153,129,.4)'],[6,'rgba(242,54,69,.4)']])
    line('swings',{color:col,lineVisible:false,pointMarkersVisible:true,pointMarkersRadius:1.5},C.map(r=>r[idx]==null?{time:r[0]}:{time:r[0],value:r[idx]}));
  const M={swings:[],struct:[],trades:[]};
  for(const [k,t,p,ct] of S){const hi=k==='H',col=hi?'#089981':'#f23645';
    M.swings.push({time:t,position:hi?'aboveBar':'belowBar',color:col,shape:'square',size:0.1});
    M.swings.push({time:ct,position:hi?'aboveBar':'belowBar',color:col,shape:hi?'arrowDown':'arrowUp',size:0.5});
    line('swings',{color:col,lineWidth:1},t===ct?[{time:t,value:p}]:[{time:t,value:p},{time:ct,value:p}]);}
  {const pm=new Map(PR);line('prot',{color:'#7b1fa2',lineWidth:1,lineStyle:2,lineType:1},C.map(r=>pm.has(r[0])?{time:r[0],value:pm.get(r[0])}:{time:r[0]}));}
  for(const a of PAIR){const col=a.side==='H'?'#ff6d00':'#2962ff';
    line('avwap',{color:col,lineWidth:2},a.live.map(([x,v])=>({time:x,value:v})));
    if(a.back.length>1)line('avwap',{color:col,lineWidth:1,lineStyle:1},a.back.map(([x,v])=>({time:x,value:v})));}
  for(const [x,kind,dir] of E)
    M.struct.push({time:x,position:dir==='up'?'aboveBar':'belowBar',color:kind==='BOS'?'#9e9e9e':'#7b1fa2',shape:'circle',size:kind==='BOS'?0.2:0.5,text:kind==='BOS'?'':'CHoCH'});
  const T=TR.map(([et,ep,xt,xp,d,pts,open,es,xs,sl,why,chg,cb])=>({et,ep,xt,xp,up:d==='up',pts,open,es,xs,sl,why,gross:pts*LOT,chg,cb,net:pts*LOT-chg}));
  const cbTip=cb=>['Brokerage '+inr(cb.brokerage),'STT '+inr(cb.stt),'Exchange '+inr(cb.exchange),'SEBI '+inr(cb.sebi),'Stamp '+inr(cb.stamp),'GST '+inr(cb.gst)].join('&#10;');
  const WHY={stop_loss:'SL',next_choch:'CHoCH',open:'open'};
  for(const t of T){const win=t.pts>0;
    M.trades.push({time:t.et,position:t.up?'belowBar':'aboveBar',color:'#111',shape:t.up?'arrowUp':'arrowDown',size:1.5,text:t.up?'CE':'PE'});
    M.trades.push({time:t.xt,position:t.up?'aboveBar':'belowBar',color:win?'#089981':'#f23645',shape:'circle',size:0.9,text:(t.why==='stop_loss'?'SL ':t.open?'OPEN ':'')+fmt(t.pts)});
    line('trades',{color:win?'#089981':'#f23645',lineWidth:2,lineStyle:2},t.et===t.xt?[{time:t.et,value:t.ep}]:[{time:t.et,value:t.ep},{time:t.xt,value:t.xp}]);
    if(t.sl!=null)line('trades',{color:'#d32f2f',lineWidth:1,lineStyle:1},t.et===t.xt?[{time:t.et,value:t.sl}]:[{time:t.et,value:t.sl},{time:t.xt,value:t.sl}]);}
  const markers=()=>{const m=[];if(on.swings)m.push(...M.swings);if(on.struct)m.push(...M.struct);if(on.trades)m.push(...M.trades);m.sort((a,b)=>a.time-b.time);cs.setMarkers(m);};
  markers();

  // layers
  const chips=[['trades','Trades','#111'],['avwap','AVWAP','#ff6d00'],['prot','Protected','#7b1fa2'],['struct','CHoCH/BOS','#9e9e9e'],['swings','Swings','#089981'],['vol','Volume','#c3c7cf']];
  $('layers').innerHTML='';
  for(const [k,lbl,col] of chips){const b=document.createElement('span');b.className='chip'+(on[k]?' on':'');b.innerHTML=`<i style="background:${col}"></i>${lbl}`;
    b.onclick=()=>{on[k]=!on[k];b.classList.toggle('on',on[k]);(L[k]||[]).forEach(s=>s.applyOptions({visible:on[k]}));markers();};$('layers').appendChild(b);}

  // ohlc readout
  const byT=new Map(C.map(r=>[r[0],r]));
  const showBar=r=>{if(!r)return;$('ohlc').innerHTML=`${iso(r[0]).slice(5,16).replace('T',' ')} O <b>${r[1]}</b> H <b>${r[2]}</b> L <b>${r[3]}</b> C <b class="${r[4]>=r[1]?'pos':'neg'}">${r[4]}</b> V <b>${r[7].toLocaleString('en-IN')}</b>`;};
  showBar(C[C.length-1]);ch.subscribeCrosshairMove(p=>showBar(p.time?byT.get(p.time):C[C.length-1]));

  // ctrl+wheel zoom
  $('chart').onwheel=e=>{if(!e.ctrlKey)return;e.preventDefault();const ts=ch.timeScale(),r=ts.getVisibleLogicalRange();if(!r)return;
    const x=ts.coordinateToLogical(e.offsetX)??(r.from+r.to)/2,k=e.deltaY>0?1.15:1/1.15;ts.setVisibleLogicalRange({from:x-(x-r.from)*k,to:x+(r.to-x)*k});};

  // day navigation (opens on the last day)
  const idxOf=t=>{let lo=0,hi=C.length-1;while(lo<hi){const m=(lo+hi)>>1;if(C[m][0]<t)lo=m+1;else hi=m;}return lo;};
  const days=[...new Set(C.map(r=>iso(r[0]).slice(0,10)))];
  const span={};C.forEach((r,i)=>{const d=iso(r[0]).slice(0,10);(span[d]??=[i,i])[1]=i;});
  const dayPnl={};T.forEach(t=>{const d=iso(t.et).slice(0,10);dayPnl[d]=(dayPnl[d]||0)+t.net;});
  $('day').innerHTML=days.map(d=>`<option value="${d}">${d}${dayPnl[d]!=null?'  '+inr(dayPnl[d])+' net':''}</option>`).join('');
  const showDay=d=>{$('day').value=d;const [a,b]=span[d];ch.timeScale().setVisibleLogicalRange({from:a-2,to:b+2});};
  $('day').onchange=()=>showDay($('day').value);
  $('prev').onclick=()=>{const k=days.indexOf($('day').value);if(k>0)showDay(days[k-1]);};
  $('next').onclick=()=>{const k=days.indexOf($('day').value);if(k<days.length-1)showDay(days[k+1]);};
  $('all').onclick=()=>ch.timeScale().fitContent();
  showDay(days[days.length-1]);
  const zoom=(a,b,pad)=>{pad=pad??(meta.timeframe==='minute'?30:12);ch.timeScale().setVisibleLogicalRange({from:idxOf(a)-pad,to:idxOf(b)+pad});
    const d=iso(a).slice(0,10);if(days.includes(d))$('day').value=d;document.querySelector('.chartcard').scrollIntoView({behavior:'smooth',block:'start'});};

  // KPIs
  const sum=(a,f)=>a.reduce((s,t)=>s+f(t),0);
  const tot=sum(T,t=>t.pts),G=sum(T,t=>t.gross),CH=sum(T,t=>t.chg),N=G-CH,W=T.filter(t=>t.net>0),Ls=T.filter(t=>t.net<=0);
  let eq=0,peak=0,dd=0;for(const t of T){eq+=t.net;peak=Math.max(peak,eq);dd=Math.min(dd,eq-peak);}
  const avg=a=>a.length?sum(a,t=>t.net)/a.length:0;
  const pf=-sum(Ls,t=>t.net);const pfv=pf>0?(sum(W,t=>t.net)/pf).toFixed(2):'—';
  const K=[['Points',fmt(tot),'gross futures points',tot>=0?'pos':'neg'],
    ['Gross P&L',inr(G),`points × ${LOT} (1 lot)`,G>=0?'pos':'neg'],
    ['Charges',inr(-CH),`${inr(T.length?CH/T.length:0)} / trade ≈ ${T.length?(CH/LOT/T.length).toFixed(1):0} pts`,'neg'],
    ['Net P&L',inr(N),'gross − charges',N>=0?'pos':'neg'],
    ['Trades',T.length,`${T.filter(t=>t.up).length} CE · ${T.filter(t=>!t.up).length} PE`,''],
    ['Win rate',T.length?Math.round(100*W.length/T.length)+'%':'—',`${W.length} W · ${Ls.length} L (after charges)`,''],
    ['Avg win / loss',`<span style="font-size:16px">${inr(avg(W))} / ${inr(avg(Ls))}</span>`,'net per trade',''],
    ['Profit factor',pfv,'net wins ÷ net losses',''],
    ['Max drawdown',inr(dd),'on net P&L',dd<0?'neg':''],
    ['Stops hit',T.filter(t=>t.why==='stop_loss').length,`${T.filter(t=>t.why==='next_choch').length} exited on CHoCH`,''],
    ['Open',T.filter(t=>t.open).length,(T.some(t=>t.open)?'marked to last close':'none')+(meta.skipped?` · ${meta.skipped} setups skipped (SL wrong side)`:''),'']];
  $('kpis').innerHTML=K.map(([l,v,s,c])=>`<div class="card kpi"><div class="l">${l}</div><div class="v ${c}">${v}</div><div class="s">${s}</div></div>`).join('');

  // trades
  let cum=0;
  $('ttrades').innerHTML='<thead><tr><th>#</th><th>Side</th><th>Entry (SETUP close)</th><th class="num">SL</th><th>Exit</th><th>Reason</th><th class="num">Points</th><th class="num">Gross ₹</th><th class="num">Charges ₹</th><th class="num">Net ₹</th><th class="num">Cum. net ₹</th></tr></thead><tbody>'+
    T.map((t,i)=>{cum+=t.net;const c=t.pts>0?'pos':'neg',cn=t.net>0?'pos':'neg';return `<tr class="z" data-a="${t.et}" data-b="${t.xt}"><td>${i+1}</td><td><span class="pill ${t.up?'ce':'pe'}">${t.up?'CE':'PE'}</span></td><td>${t.es} @ ${t.ep}</td><td class="num">${t.sl??'—'}</td><td>${t.xs} @ ${t.xp}</td><td><span class="pill ${t.why==='stop_loss'?'pe':t.open?'open':'grey'}">${WHY[t.why]}</span></td><td class="num ${c}">${fmt(t.pts)}</td><td class="num ${c}">${inr(t.gross)}</td><td class="num neg" title="${cbTip(t.cb)}">${inr(-t.chg)}</td><td class="num ${cn}">${inr(t.net)}</td><td class="num ${cum>=0?'pos':'neg'}">${inr(cum)}</td></tr>`;}).join('')+
    `</tbody><tfoot><tr style="font-weight:600"><td colspan="7">Total</td><td class="num ${tot>=0?'pos':'neg'}">${fmt(tot)}</td><td class="num ${G>=0?'pos':'neg'}">${inr(G)}</td><td class="num neg">${inr(-CH)}</td><td class="num ${N>=0?'pos':'neg'}">${inr(N)}</td><td></td></tr></tfoot>`;
  // daily
  const byDay={};T.forEach(t=>{const d=iso(t.et).slice(0,10);(byDay[d]??=[]).push(t);});let dc=0;
  const cl=v=>v>0?'pos':v<0?'neg':'';
  $('tdaily').innerHTML='<thead><tr><th>Day</th><th class="num">Trades</th><th class="num">Wins</th><th class="num">Points</th><th class="num">Gross ₹</th><th class="num">Charges ₹</th><th class="num">Net ₹</th><th class="num">Cum. net ₹</th></tr></thead><tbody>'+
    days.map(d=>{const a=byDay[d]||[],p=sum(a,t=>t.pts),g=sum(a,t=>t.gross),c=sum(a,t=>t.chg),nt=g-c;dc+=nt;const [x,y]=span[d];
      return `<tr class="z" data-a="${C[x][0]}" data-b="${C[y][0]}" data-day="${d}"><td>${d}</td><td class="num">${a.length}</td><td class="num">${a.filter(t=>t.net>0).length}</td><td class="num ${cl(p)}">${a.length?fmt(p):'—'}</td><td class="num ${cl(g)}">${a.length?inr(g):'—'}</td><td class="num ${a.length?'neg':''}">${a.length?inr(-c):'—'}</td><td class="num ${cl(nt)}">${a.length?inr(nt):'—'}</td><td class="num ${dc>=0?'pos':'neg'}">${inr(dc)}</td></tr>`;}).join('')+'</tbody>';
  // signals
  const chE=E.filter(e=>e[1]==='CHoCH');
  $('tsignals').innerHTML='<thead><tr><th>CHoCH</th><th>Direction</th><th>AVWAP from SH</th><th>AVWAP from SL</th><th>SETUP → P&amp;L</th></tr></thead><tbody>'+
    chE.map(([x,,dir],j)=>{const nx=j+1<chE.length?chE[j+1][0]:Infinity;const h=PAIR.find(p=>p.ch===x&&p.side==='H'),l=PAIR.find(p=>p.ch===x&&p.side==='L');const st=T.find(t=>t.et>x&&t.et<=nx);
      return `<tr class="z" data-a="${x}" data-b="${st?st.xt:x}"><td>${iso(x).slice(5,16).replace('T',' ')}</td><td><span class="pill ${dir==='up'?'ce':'pe'}">${dir==='up'?'▲ up':'▼ down'}</span></td><td>${h?h.anchor+' @ '+h.p:'—'}</td><td>${l?l.anchor+' @ '+l.p:'—'}</td><td>${st?`<span class="pill ${st.up?'ce':'pe'}">${st.up?'CE':'PE'}</span> ${st.es} → <span class="${st.pts>0?'pos':'neg'}">${fmt(st.pts)}</span>`:'<span class="pill grey">none</span>'}</td></tr>`;}).join('')+'</tbody>';
  document.querySelectorAll('tr.z').forEach(r=>r.onclick=()=>r.dataset.day?(showDay(r.dataset.day),document.querySelector('.chartcard').scrollIntoView({behavior:'smooth'})):zoom(+r.dataset.a,+r.dataset.b));
  // config
  const lab={code:'Code',name:'Name',description:'Description',instrument:'Instrument',timeframe:'Timeframe',date_from:'From',date_to:'To',break_mode:'Break mode',avwap_weight:'AVWAP weight',entry_rule:'Entry rule',exit_rule:'Exit rule',sl_rule:'Stop-loss rule',charge_code:'Charge schedule',lot_size:'Lot size',run_id:'Run id'};
  const sch=meta.charges;
  $('cfg').innerHTML=Object.entries(lab).map(([k,v])=>`<dt>${v}</dt><dd>${meta[k]}</dd>`).join('')+
    `<dt>Brokerage</dt><dd>${sch.brokerage_pct}% or ₹${sch.brokerage_cap} per order, whichever lower</dd><dt>STT</dt><dd>${sch.stt_buy_pct}% buy · ${sch.stt_sell_pct}% sell</dd>
     <dt>Exchange txn</dt><dd>${sch.exchange_pct}%</dd><dt>SEBI</dt><dd>${sch.sebi_pct}%</dd><dt>Stamp duty</dt><dd>${sch.stamp_buy_pct}% buy</dd><dt>GST</dt><dd>${sch.gst_pct}% on brokerage + exchange + SEBI</dd><dt>Charges note</dt><dd>${sch.notes}</dd>`;
}

document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===b));
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('on',p.id===b.dataset.p));});
let start=0;try{const c=localStorage.getItem('strat');const k=STRATS.findIndex(s=>s.meta.code===c);if(k>=0)start=k;}catch(e){}
select(start);
</script></body></html>
