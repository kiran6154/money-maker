"""Builds exports/ST9_1m_futures_2026-06-29_to_2026-07-02.html from exports/_st9_export.json (one self-contained page)."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
data = open(os.path.join(HERE, "_st9_export.json"), encoding="utf-8").read()

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strategy 9 · 1-min futures · 29 Jun – 2 Jul 2026</title>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#111827;--sub:#6b7280;--line:#e5e7eb;--pos:#067d5f;--neg:#c0392b;--acc:#2954d9}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1280px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:18px 0 8px}
.sub{color:var(--sub);font-size:12.5px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-top:12px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{border:0;background:#fff;padding:6px 12px;font:inherit;cursor:pointer;color:var(--ink)}.seg button.on{background:var(--acc);color:#fff}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}.kpi .l{font-size:11.5px;color:var(--sub);text-transform:uppercase;letter-spacing:.03em}.kpi .v{font-size:19px;font-weight:600}
.pos{color:var(--pos)}.neg{color:var(--neg)}#chart{height:560px;width:100%}
table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{padding:5px 7px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{position:sticky;top:0;background:#fafafa;font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}.scroll{overflow:auto;max-height:420px}
tr.z{cursor:pointer}tr.z:hover{background:#f3f6ff}.chip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:999px;padding:2px 9px;font-size:12px;cursor:pointer;user-select:none}
.chip i{width:9px;height:9px;border-radius:50%;display:inline-block}.chip.off{opacity:.4}dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:0}dt{color:var(--sub)}dd{margin:0}
button.dl{border:1px solid var(--line);background:#fff;border-radius:8px;padding:6px 12px;font:inherit;cursor:pointer}ul{margin:6px 0;padding-left:18px}
</style></head><body><main>
<h1>Strategy 9 · 1-minute NIFTY near-month futures · 29 Jun – 2 Jul 2026</h1>
<div class="sub" id="about"></div>
<div class="card"><div class="bar"><span class="sub">Holding</span><span class="seg" id="modeSeg"></span><span class="sub" style="margin-left:10px">Session</span><span class="seg" id="daySeg"></span>
  <span style="flex:1"></span><button class="dl" id="dlTrades">Download trades (CSV)</button><button class="dl" id="dlCandles">Download candles (CSV)</button></div>
  <div class="kpis" id="kpis" style="margin-top:12px"></div></div>
<div class="card"><div class="bar" id="layers"></div><div id="ohlc" class="sub" style="margin:6px 0"></div><div id="chart"></div>
  <div class="sub">Drag to pan, pinch / Ctrl+wheel to zoom. Times are exchange time (IST). Click a trade below to zoom to it.</div></div>
<div class="card"><h2 style="margin-top:0">Trades (one row per lot group)</h2><div class="scroll"><table id="trades"></table></div><div id="skipped" class="sub" style="margin-top:8px"></div></div>
<div class="card"><h2 style="margin-top:0">Rules and settings used</h2><div id="rules"></div></div>
</main>
<script>
const DATA=__DATA__;
const $=id=>document.getElementById(id),M0=DATA.meta,fmt=(v,d=1)=>v==null?'—':(+v).toFixed(d),inr=v=>(v<0?'−':'')+'₹'+Math.abs(Math.round(v)).toLocaleString('en-IN');
const iso=t=>new Date(t*1000).toISOString().replace('T',' ').slice(0,16);let MODE='intraday',DAY='all',chart=null;
const on={trades:true,rlevels:true,avwap:true,prot:true,struct:true,swings:true,vol:true};
$('about').textContent=M0.description;
function merge(days){const seen=new Set(),M=[];for(const c of days)for(const m of c.M)if(!seen.has(m[0]+'|'+m[9])){seen.add(m[0]+'|'+m[9]);M.push(m);}
  const cat=k=>days.flatMap(c=>c[k]||[]);return {C:cat('C'),S:cat('S'),E:cat('E'),PR:cat('PR'),PAIR:cat('PAIR'),M};}
function book(){return DATA[MODE];}
function segs(){$('modeSeg').innerHTML=['intraday','positional'].map(m=>`<button data-m="${m}" class="${m===MODE?'on':''}">${m==='intraday'?'Intraday (square-off 15:25)':'Positional (held overnight)'}</button>`).join('');
  $('modeSeg').querySelectorAll('button').forEach(b=>b.onclick=()=>{MODE=b.dataset.m;render();});
  const ds=book().days.map(d=>d.day);$('daySeg').innerHTML=['all',...ds].map(d=>`<button data-d="${d}" class="${d===DAY?'on':''}">${d==='all'?'All 4 sessions':d.slice(5)}</button>`).join('');
  $('daySeg').querySelectorAll('button').forEach(b=>b.onclick=()=>{DAY=b.dataset.d;render();});}
function kpis(){const s=book().stats,T=book().trades,pos=new Set(T.map(t=>t.entry_time+t.position)).size;
  $('kpis').innerHTML=[['Net P&L',inr(s.net_inr),s.net_inr],['Positions',pos,null],['Lot exits',s.trades,null],['Win rate (lot exits)',Math.round(100*s.wins/Math.max(1,s.trades))+'%',null],
    ['Gross',inr(s.gross_inr),s.gross_inr],['Charges',inr(-s.charges_inr),-1],['Profit factor',s.pf??'—',null],['Max drawdown',inr(s.max_dd_inr),-1]]
    .map(([l,v,c])=>`<div class="kpi"><div class="l">${l}</div><div class="v ${c==null?'':c>=0?'pos':'neg'}">${v}</div></div>`).join('');}
function draw(){const days=book().days.filter(d=>DAY==='all'||d.day===DAY),CH=merge(days),{C,S:SW,E,PR,PAIR,M}=CH;
  if(chart){chart.remove();chart=null;}
  chart=LightweightCharts.createChart($('chart'),{autoSize:true,layout:{background:{color:'#fff'},textColor:'#4b5563',fontFamily:'system-ui'},
    grid:{vertLines:{color:'#f3f4f6'},horzLines:{color:'#f3f4f6'}},timeScale:{timeVisible:true,secondsVisible:false,rightOffset:4},crosshair:{mode:0},
    handleScroll:{mouseWheel:false,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},handleScale:{mouseWheel:false,pinch:true,axisPressedMouseMove:true},
    localization:{timeFormatter:t=>iso(t).slice(5)}});
  const cs=chart.addCandlestickSeries({upColor:'#089981',downColor:'#f23645',wickUpColor:'#089981',wickDownColor:'#f23645',borderVisible:false});
  cs.priceScale().applyOptions({scaleMargins:{top:0.06,bottom:0.2}});cs.setData(C.map(r=>({time:r[0],open:r[1],high:r[2],low:r[3],close:r[4]})));
  const base={lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false,autoscaleInfoProvider:()=>null},L={vol:[],swings:[],avwap:[],prot:[],trades:[],rlevels:[]};
  const line=(layer,opt,data)=>{const s=chart.addLineSeries({...base,...opt,visible:on[layer]});s.setData(data);L[layer].push(s);};
  const vs=chart.addHistogramSeries({priceScaleId:'vol',priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false,visible:on.vol});
  chart.priceScale('vol').applyOptions({scaleMargins:{top:0.84,bottom:0}});vs.setData(C.map(r=>({time:r[0],value:r[7],color:r[4]>=r[1]?'rgba(8,153,129,.35)':'rgba(242,54,69,.35)'})));L.vol.push(vs);
  const MK={swings:[],struct:[],trades:[]};
  for(const [k,t,p,ct] of SW){const hi=k==='H',col=hi?'#089981':'#f23645';MK.swings.push({time:ct,position:hi?'aboveBar':'belowBar',color:col,shape:hi?'arrowDown':'arrowUp',size:0.5});
    line('swings',{color:col,lineWidth:1},t===ct?[{time:t,value:p}]:[{time:t,value:p},{time:ct,value:p}]);}
  {const pm=new Map(PR);line('prot',{color:'#7b1fa2',lineWidth:1,lineStyle:2,lineType:1},C.map(r=>pm.has(r[0])?{time:r[0],value:pm.get(r[0])}:{time:r[0]}));}
  for(const a of PAIR){const col=a.side==='H'?'#ff6d00':'#2962ff';line('avwap',{color:col,lineWidth:2},a.live.map(([x,v])=>({time:x,value:v})));
    if(a.back.length>1)line('avwap',{color:col,lineWidth:1,lineStyle:1},a.back.map(([x,v])=>({time:x,value:v})));}
  for(const [x,kind,dir] of E)MK.struct.push({time:x,position:dir==='up'?'aboveBar':'belowBar',color:kind==='BOS'?'#9e9e9e':'#7b1fa2',shape:'circle',size:kind==='BOS'?0.2:0.5,text:kind==='BOS'?'':'CHoCH'});
  const tmin=C[0][0],tmax=C[C.length-1][0],P=M0.position,byE=new Map(),seen=new Set(),b0=l=>(l||'').split(' · ')[0];
  for(const t of book().trades)byE.set(Date.parse(t.entry_time.replace(' ','T')+'Z')/1000+'|'+t.position,t);
  for(const [et0,ep,xt,xp,d,pts,open,sl,why,label] of M){const up=d==='up',win=pts>0,xe=Math.min(xt,tmax),et=Math.max(et0,tmin);
    if(et0>=tmin)MK.trades.push({time:et0,position:up?'belowBar':'aboveBar',color:'#111',shape:up?'arrowUp':'arrowDown',size:1.4,text:label});
    if(xt<=tmax)MK.trades.push({time:xt,position:up?'aboveBar':'belowBar',color:win?'#089981':'#f23645',shape:'circle',size:0.9,
      text:(why==='stop_loss'?'SL ':why==='trail_stop'?'TRAIL ':why==='eod'?'EOD ':/^target /.test(why||'')?'T'+why.slice(7)+' ':open?'OPEN* ':'')+fmt(pts)});
    line('trades',{color:win?'#089981':'#f23645',lineWidth:2,lineStyle:2},et===xe?[{time:et,value:ep}]:[{time:et,value:ep},{time:xe,value:xp}]);
    const key=et0+'|'+(up?'LONG':'SHORT');if(seen.has(key))continue;const t=byE.get(key);if(!t)continue;seen.add(key);
    const end=Math.min(Math.max(...M.filter(z=>z[0]===et0&&z[4]===d&&b0(z[9])===b0(label)).map(z=>z[2])),tmax),a=Math.max(et0,tmin),R=Math.abs(t.entry_px-t.sl),sg=up?1:-1;
    const lv=[['SL',-1,'#d32f2f'],...(P.scale_out||[]).map(x=>[x.target_r+'R',x.target_r,'#089981']),...(P.trail?[[P.trail.start_r+'R trail',P.trail.start_r,'#2962ff']]:[])];
    if(R&&a<=end)for(const [nm,k,col] of lv){const y=+(ep+sg*k*R).toFixed(2);line('rlevels',{color:col,lineWidth:1,lineStyle:k<0?0:2,title:nm,lastValueVisible:true},a===end?[{time:a,value:y}]:[{time:a,value:y},{time:end,value:y}]);}}
  const markers=()=>{const m=[];if(on.swings)m.push(...MK.swings);if(on.struct)m.push(...MK.struct);if(on.trades)m.push(...MK.trades);m.sort((a,b)=>a.time-b.time);cs.setMarkers(m);};markers();
  $('layers').innerHTML='';for(const [k,lbl,col] of [['trades','Trades','#111'],['rlevels','Stop / 1R / 2R / 3R','#089981'],['avwap','AVWAP pair','#ff6d00'],['prot','Protected level','#7b1fa2'],['struct','CHoCH / BOS','#9e9e9e'],['swings','Swings','#089981'],['vol','Volume','#c3c7cf']]){
    const b=document.createElement('span');b.className='chip'+(on[k]?'':' off');b.innerHTML=`<i style="background:${col}"></i>${lbl}`;
    b.onclick=()=>{on[k]=!on[k];b.classList.toggle('off',!on[k]);(L[k]||[]).forEach(s=>s.applyOptions({visible:on[k]}));markers();};$('layers').appendChild(b);}
  const byT=new Map(C.map(r=>[r[0],r])),bar=r=>{if(r)$('ohlc').innerHTML=`${iso(r[0])} · O ${r[1]} H ${r[2]} L ${r[3]} C ${r[4]} · V ${r[7].toLocaleString('en-IN')}`;};
  bar(C[C.length-1]);chart.subscribeCrosshairMove(p=>bar(p.time?byT.get(p.time):C[C.length-1]));
  $('chart').onwheel=e=>{if(!e.ctrlKey)return;e.preventDefault();const ts=chart.timeScale(),r=ts.getVisibleLogicalRange();if(!r)return;const x=ts.coordinateToLogical(e.offsetX)??(r.from+r.to)/2,k=e.deltaY>0?1.15:1/1.15;ts.setVisibleLogicalRange({from:x-(x-r.from)*k,to:x+(r.to-x)*k});};
  chart.timeScale().fitContent();return C;}
const WHY={stop_loss:'Stop',trail_stop:'Trail stop',eod:'Square-off 15:25',next_choch:'Next CHoCH',open:'Open at end*',expiry:'Expiry'};
function table(){const T=book().trades.filter(t=>DAY==='all'||t.entry_time.startsWith(DAY)||t.exit_time.startsWith(DAY));let cum=0;
  $('trades').innerHTML='<thead><tr><th>#</th><th>Position</th><th>Contract</th><th>Lot group</th><th class="n">Lots</th><th>CHoCH</th><th>Entry</th><th class="n">Entry px</th><th class="n">Stop</th><th>Exit</th><th class="n">Exit px</th><th>Reason</th><th class="n">Points</th><th class="n">Best</th><th class="n">Worst</th><th class="n">Gross ₹</th><th class="n">Charges ₹</th><th class="n">Net ₹</th><th class="n">Cum. ₹</th></tr></thead><tbody>'+
    T.map((t,i)=>{cum+=t.net;return `<tr class="z" data-a="${t.entry_time}" data-b="${t.exit_time}"><td>${i+1}</td><td class="${t.position==='LONG'?'pos':'neg'}">${t.position}</td><td>${t.instrument}</td><td>${t.tranche||'—'}</td><td class="n">${t.lots}</td><td>${t.choch_time.slice(5,16)}</td><td>${t.entry_time.slice(5,16)}</td><td class="n">${t.entry_px}</td><td class="n">${t.sl}</td><td>${t.exit_time.slice(5,16)}</td><td class="n">${t.exit_px}</td><td>${WHY[t.exit_reason]||t.exit_reason.replace('target','Target')}</td><td class="n ${t.pts>=0?'pos':'neg'}">${fmt(t.pts)}</td><td class="n">${fmt(t.mfe)}</td><td class="n">${fmt(t.mae)}</td><td class="n">${inr(t.gross)}</td><td class="n">${inr(-t.charges)}</td><td class="n ${t.net>=0?'pos':'neg'}">${inr(t.net)}</td><td class="n ${cum>=0?'pos':'neg'}">${inr(cum)}</td></tr>`;}).join('')+'</tbody>';
  document.querySelectorAll('#trades tr.z').forEach(r=>r.onclick=()=>{const a=Date.parse(r.dataset.a.replace(' ','T')+'Z')/1000,b=Date.parse(r.dataset.b.replace(' ','T')+'Z')/1000;
    const C=merge(book().days.filter(d=>DAY==='all'||d.day===DAY)).C,ix=t=>{let i=C.findIndex(c=>c[0]>=t);return i<0?C.length-1:i;};chart.timeScale().setVisibleLogicalRange({from:ix(a)-25,to:ix(b)+25});window.scrollTo({top:$('chart').getBoundingClientRect().top+scrollY-80,behavior:'smooth'});});
  const sk=book().skipped.filter(s=>DAY==='all'||String(s.entry_time).startsWith(DAY));
  $('skipped').innerHTML=sk.length?`<b>Signals not taken (${sk.length})</b>: `+sk.map(s=>`${String(s.entry_time).slice(5,16)} ${s.position||''} — ${s.why}`).join(' · '):'';}
function rules(){const P=M0.position,R=M0.rules;
  $('rules').innerHTML=`<dl><dt>Strategy</dt><dd>${M0.strategy} (${M0.code}) · ${M0.timeframe} · ${M0.instrument}</dd><dt>Period</dt><dd>${M0.period} (engine warm-up: 2 sessions before)</dd>
   <dt>Entry</dt><dd>Swings → protected level → CHoCH (break of the protected level, by ${R.choch_mode}) → AVWAP pair from the previous swing high and low → SETUP when both AVWAPs slope with the CHoCH and a candle closes beyond the CHoCH candle. Entry at the SETUP candle's close. BOS / swings by ${R.break_mode}.</dd>
   <dt>Position</dt><dd>${P.lots} lots; stop ${P.stop.futures_pts} points from entry = 1R; ${P.scale_out.map((x,i)=>`lot ${i+1} out at ${x.target_r}R`).join(', ')}; the rest trails from ${P.trail.start_r}R, ${P.trail.lag_r}R behind the best whole R reached (moves apply from the next candle; the stop is checked before targets on a candle). No CHoCH exit.</dd>
   <dt>Holding</dt><dd><b>Intraday</b>: every position is closed at the close of the 15:25 candle and no entry is taken at or after 15:25. <b>Positional</b>: no time exit; lots stay open until stop, target or trail.</dd>
   <dt>Fills</dt><dd>No fill on a session's opening print: a stop crossed on the first candle fills at its close; a target only if the close is beyond it. A gap through the stop fills at the open.</dd>
   <dt>Lock</dt><dd>One open position per contract: a signal while the contract has an open lot is not taken (listed under the trade table).</dd>
   <dt>Costs</dt><dd>Lot size ${M0.lot_size}; slippage ${M0.slippage_pts} points per side per lot; Zerodha charges (brokerage ₹${M0.charges.brokerage_flat||20} per order, STT ${M0.charges.stt_sell_pct}% sell, exchange ${M0.charges.exchange_pct}%, SEBI, stamp ${M0.charges.stamp_buy_pct}% buy, GST ${M0.charges.gst_pct}%).</dd>
   <dt>Data</dt><dd>${M0.data_file}: 1-minute near-month NIFTY futures from ICICI Breeze, contract switched at each monthly expiry (June contract to 30 Jun, July from 1 Jul).</dd></dl>`;}
function csv(rows,cols){return [cols.join(',')].concat(rows.map(r=>cols.map(c=>{const v=r[c];return typeof v==='string'&&/[",]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v??'';}).join(','))).join('\n');}
function save(name,text){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:'text/csv'}));a.download=name;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},800);}
$('dlTrades').onclick=()=>save(`ST9_1m_futures_trades_${MODE}.csv`,csv(book().trades,['position','instrument','tranche','lots','signal','choch_time','entry_time','entry_px','sl','exit_time','exit_px','exit_reason','pts','mfe','mae','gross','charges','net']));
$('dlCandles').onclick=()=>{const rows=book().days.flatMap(d=>d.C).map(r=>({datetime_ist:iso(r[0])+':00',open:r[1],high:r[2],low:r[3],close:r[4],volume:r[7]}));save('ST9_1m_futures_candles.csv',csv(rows,['datetime_ist','open','high','low','close','volume']));};
function render(){segs();kpis();draw();table();rules();}
render();
</script></body></html>"""
out = os.path.join(HERE, "ST9_1m_futures_2026-06-29_to_2026-07-02.html")
open(out, "w", encoding="utf-8").write(PAGE.replace("__DATA__", data))
print(out, os.path.getsize(out))
