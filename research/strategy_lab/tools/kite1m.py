import requests, csv, time, datetime as D
from kitecreds import creds
k,t,_,_=creds(); H={"X-Kite-Version":"3","Authorization":f"token {k}:{t}"}
TOK,SYM=17512194,"NIFTY26SEPFUT"   # current front-month future
out=[]; d=D.date(2026,7,1); end=D.date(2026,9,26)
while d<=end:
    e=min(d+D.timedelta(days=55),end)
    r=requests.get(f"https://api.kite.trade/instruments/historical/{TOK}/minute",headers=H,
                   params={"from":f"{d} 09:15:00","to":f"{e} 15:30:00","oi":1},timeout=60)
    r.raise_for_status(); c=r.json()["data"]["candles"]; out+=c; print(d,e,len(c)); d=e+D.timedelta(days=1); time.sleep(0.5)
raw=f"D:/nifty/{SYM}_minute.csv"
with open(raw,"w",newline="") as f:
    w=csv.writer(f); w.writerow(["datetime","open","high","low","close","volume","oi"])
    for x in out: w.writerow([x[0][:19].replace("T"," ")]+x[1:])
# working file: regular session only (09:15-15:29), front_month flag from 26 Aug (Aug expiry 25 Aug)
clean=[x for x in out if x[0][11:16]<="15:29"]
fn=f"D:/nifty/niftyfut_minute_2026-07-01_to_2026-09-25.csv"
with open(fn,"w",newline="") as f:
    w=csv.writer(f); w.writerow(["datetime","open","high","low","close","volume","oi","contract","front_month"])
    for x in clean: w.writerow([x[0][:19].replace("T"," ")]+x[1:]+[SYM,int(x[0][:10]>="2026-08-26")])
days={x[0][:10] for x in clean}
from collections import Counter
print(raw,len(out)); print(fn,len(clean),"days",len(days),"candles/day",Counter(Counter(x[0][:10] for x in clean).values()).most_common(4))
