"""S171 - the 10 CE ladder strikes added up into one 1-min candle chart, and whether its CHoCH / BOS differ from the ATM CE's
on sideways days (the user, 2026-10-30: "show me the chart of cumulative candle data of 10 ce see in 1min chart see if
choch and bos in that is different than atm in sideways market").

Per session: expiry = the nearest on or after the day (as the ladder, S167 - S169); ATM = NIFTY 09:15 1-min close rounded to
50; basket = CE ATM, ATM+50 .. ATM+450, fixed for the day. Basket candle per minute = the sum of the 10 contracts' open /
high / low / close (each contract's last close carried over a minute it did not print; the summed high / low is the
upper / lower bound of the basket's true minute range, since the 10 highs need not fall in the same second).
Structure: nifty_bt.indicators.pivot_structure(N = 3) on 1-min bars of the day (CHoCH = +-2, BOS = +-1 at the bar close).
Day type from S170's ratings: sideways = |close - open| < 0.25 ADR20, trend = >= 0.75 ADR20, the rest "between".
Measured per day and instrument: CHoCH / BOS count; agreement = share of one chart's events with a same-direction event
on the other within +-3 minutes; follow-through = the move over the next 15 minutes in the event's direction, % of price;
whipsaw = an opposite event within 15 minutes.
Output: results/nifty_bt/basket_structure/summary.csv and chart.html (sample sideways and trend days, both charts).

    python tools/basket_structure.py     (BASKET=itm for ATM .. ATM-450; from research/strategy_lab_v2; needs results/nifty_bt/regime_rating/ratings.parquet)
"""
import os, sys, json, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain, indicators as I

data.FILES = ("", ".wide", ".wide3k"); data._zip_members.cache_clear(); data.expiries.cache_clear()
STEP_SIGN = -1 if os.environ.get("BASKET", "otm") == "itm" else 1     # otm: ATM .. ATM+450 (S171); itm: ATM .. ATM-450 (S172)
OUT = os.path.join(chain.CACHE, "basket_structure" + ("_itm" if STEP_SIGN < 0 else ""))
os.makedirs(OUT, exist_ok=True)
N, FWD, MATCH = 3, 15, 3
COLS = ("datetime", "strike", "right", "open", "high", "low", "close")


def events(B):
    S = I.pivot_structure(B, N); ev = S["ev"]; c = B.close.values; out = []
    for i in np.flatnonzero(ev):
        d = 1 if ev[i] > 0 else -1
        fwd = d * (c[min(i + FWD, len(c) - 1)] - c[i]) / c[i] * 100 if i + 1 < len(c) else np.nan
        opp = np.flatnonzero(ev[i + 1:i + 1 + FWD] * d < 0)
        out.append(dict(i=int(i), tod=int(B.tod.values[i]), d=d, kind="CHoCH" if abs(ev[i]) == 2 else "BOS", fwd=fwd, whip=len(opp) > 0))
    return out, S


def agree(a, b):
    if not a: return np.nan
    return np.mean([any(y["d"] == x["d"] and abs(y["tod"] - x["tod"]) <= MATCH for y in b) for x in a]) * 100


def day_frames(X, D, A):
    g = X[(X.date == D) & (X.right == "CE") & (X.strike.isin([A + STEP_SIGN * 50 * k for k in range(10)]))]
    if g.strike.nunique() < 10: return None
    piv = {c: g.pivot_table(index="tod", columns="strike", values=c, aggfunc="last").sort_index() for c in ("open", "high", "low", "close")}
    cl = piv["close"].ffill()
    full = cl.notna().all(axis=1)
    if full.sum() < 300: return None
    o = piv["open"].fillna(cl.shift(1)).fillna(cl); h = piv["high"].fillna(cl); l = piv["low"].fillna(cl)
    B = pd.DataFrame(dict(open=o.sum(1), high=h.sum(1), low=l.sum(1), close=cl.sum(1)))[full].reset_index()
    a = g[g.strike == A].set_index("tod")[["open", "high", "low", "close"]].sort_index().reset_index()
    return B, a


def run():
    R = pd.read_parquet(os.path.join(chain.CACHE, "regime_rating", "ratings.parquet"))
    R["type"] = np.where(R.day_move.abs() < 0.25, "sideways", np.where(R.day_move.abs() >= 0.75, "trend", "between"))
    idx = data.index_1m_all(); s0915 = idx[idx.tod == 555].set_index("date").close
    jobs = {}
    for D in R.index:
        e = chain.trade_expiry(D, strictly_after=False)
        if e and D in s0915.index: jobs.setdefault(e, []).append(D)
    rows, evrows, charts = [], [], {}
    random.seed(11)
    pick = set(random.sample(list(R.index[R.type == "sideways"]), 14)) | set(random.sample(list(R.index[R.type == "trend"]), 6))
    for e in sorted(jobs):
        ATMs = {D: int(round(s0915[D] / 50) * 50) for D in jobs[e]}
        X = data.read_expiry(e, columns=COLS, strikes={A + STEP_SIGN * 50 * k for A in ATMs.values() for k in range(10)})
        if X is None: continue
        X = X[X.right == "CE"]
        for D in jobs[e]:
            fr = day_frames(X, D, ATMs[D])
            if fr is None: continue
            B, a = fr
            eb, Sb = events(B); ea, Sa = events(a)
            typ = R.type.get(D)
            for nm, ev in (("basket", eb), ("atm", ea)):
                for x in ev: evrows.append(dict(date=D, type=typ, chart=nm, **x))
            rows.append(dict(date=D, type=typ, expiry=e, atm=ATMs[D], dte=(pd.Timestamp(e) - D).days,
                             b_choch=sum(x["kind"] == "CHoCH" for x in eb), b_bos=sum(x["kind"] == "BOS" for x in eb),
                             a_choch=sum(x["kind"] == "CHoCH" for x in ea), a_bos=sum(x["kind"] == "BOS" for x in ea),
                             basket_in_atm=agree(eb, ea), atm_in_basket=agree(ea, eb)))
            if D in pick:
                ts = lambda tod: int((D + pd.Timedelta(minutes=int(tod))).timestamp())
                pack = lambda F, ev: dict(c=[[ts(t), round(o, 2), round(h, 2), round(l, 2), round(cc, 2)] for t, o, h, l, cc in F[["tod", "open", "high", "low", "close"]].itertuples(index=False)],
                                          m=[[ts(x["tod"]), x["d"], x["kind"]] for x in ev])
                charts[str(D.date())] = dict(type=typ, atm=ATMs[D], expiry=e, move=round(float(R.day_move[D]), 2), basket=pack(B, eb), atmce=pack(a, ea))
        print(e, len(rows), flush=True)
    return pd.DataFrame(rows), pd.DataFrame(evrows), charts


HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ladder CE basket vs ATM CE</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>:root{--bg:#fff;--fg:#1d1d1f;--mut:#6b6b70;--grid:#ececf0}@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececf0;--mut:#9a9aa2;--grid:#26262b}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}h1{font-size:18px;margin:0 0 6px}
.note{color:var(--mut);margin:0 0 12px;max-width:900px}.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
select{font:inherit;padding:4px 6px}.lbl{font-weight:600;margin:10px 0 4px}.ch{height:340px;width:100%}.stat{color:var(--mut)}</style></head><body>
<h1>10 CE ladder strikes, added up, vs the ATM CE &mdash; 1-minute, CHoCH / BOS (pivot 3)</h1>
<p class="note">Top: the sum of CE ATM .. ATM+450 (fixed at 09:15) as one candle per minute. Bottom: the ATM CE alone. Arrows mark CHoCH (C) and BOS (B) at the bar close they were confirmed. Sideways = NIFTY closed within 0.25 x the 20-day average range of its open; trend = 0.75 x or more.</p>
<div class="bar"><label>Day <select id="day"></select></label><span class="stat" id="info"></span></div>
<div class="lbl">10 CE basket</div><div id="a" class="ch"></div><div class="lbl">ATM CE</div><div id="b" class="ch"></div>
<script>
const D=__DATA__;const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function mk(el){return LightweightCharts.createChart(el,{autoSize:true,layout:{background:{color:css('--bg')},textColor:css('--fg')},grid:{vertLines:{color:css('--grid')},horzLines:{color:css('--grid')}},timeScale:{timeVisible:true,secondsVisible:false},crosshair:{mode:0}})}
const ca=mk(document.getElementById('a')),cb=mk(document.getElementById('b'));
const opt={upColor:'#1a9e5a',downColor:'#d1453b',borderVisible:false,wickUpColor:'#1a9e5a',wickDownColor:'#d1453b'};
const sa=ca.addCandlestickSeries(opt),sb=cb.addCandlestickSeries(opt);
let lock=false;function sync(x,y){x.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(lock||!r)return;lock=true;y.timeScale().setVisibleLogicalRange(r);lock=false})}sync(ca,cb);sync(cb,ca);
const marks=m=>m.map(([t,d,k])=>({time:t,position:d>0?'belowBar':'aboveBar',shape:d>0?'arrowUp':'arrowDown',color:d>0?'#1a9e5a':'#d1453b',text:k==='CHoCH'?'C':'B'}));
const sel=document.getElementById('day');Object.keys(D).sort((x,y)=>(D[x].type>D[y].type)-(D[x].type<D[y].type)||(x>y)-(x<y)).forEach(k=>{const o=document.createElement('option');o.value=k;o.textContent=k+' ('+D[k].type+', move '+D[k].move+' ADR)';sel.appendChild(o)});
function show(k){const d=D[k];const f=a=>a.map(([t,o,h,l,c])=>({time:t,open:o,high:h,low:l,close:c}));
sa.setData(f(d.basket.c));sa.setMarkers(marks(d.basket.m));sb.setData(f(d.atmce.c));sb.setMarkers(marks(d.atmce.m));requestAnimationFrame(()=>{lock=true;ca.timeScale().fitContent();cb.timeScale().fitContent();lock=false});
const n=(m,k)=>m.filter(x=>x[2]===k).length;document.getElementById('info').textContent=`ATM ${d.atm}, expiry ${d.expiry} - basket ${n(d.basket.m,'CHoCH')} CHoCH / ${n(d.basket.m,'BOS')} BOS, ATM CE ${n(d.atmce.m,'CHoCH')} CHoCH / ${n(d.atmce.m,'BOS')} BOS`}
sel.onchange=()=>show(sel.value);sel.value=[...sel.options].find(o=>o.textContent.includes('sideways')).value;show(sel.value);
</script></body></html>"""


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    Dd, E, charts = run()
    Dd.to_parquet(os.path.join(OUT, "days.parquet")); E.to_parquet(os.path.join(OUT, "events.parquet"))
    rows = []
    for (typ, ch), g in E.groupby(["type", "chart"]):
        nd = Dd[Dd.type == typ].shape[0]
        for kind, h in [("all", g), ("CHoCH", g[g.kind == "CHoCH"]), ("BOS", g[g.kind == "BOS"])]:
            rows.append(dict(type=typ, chart=ch, kind=kind, days=nd, per_day=round(len(h) / nd, 2), fwd15_pct=round(h.fwd.mean(), 3),
                             fwd15_pos=round((h.fwd > 0).mean() * 100, 1), whipsaw_pct=round(h.whip.mean() * 100, 1)))
    S = pd.DataFrame(rows); S.to_csv(os.path.join(OUT, "summary.csv"), index=False); print(S.to_string(index=False))
    print(Dd.groupby("type")[["basket_in_atm", "atm_in_basket"]].mean().round(1))
    html = HTML if STEP_SIGN > 0 else HTML.replace("ATM .. ATM+450", "ATM, ATM-50 .. ATM-450 (in the money)")
    with open(os.path.join(OUT, "chart.html"), "w", encoding="utf-8") as fh: fh.write(html.replace("__DATA__", json.dumps(charts)))
    print("chart days", len(charts))
