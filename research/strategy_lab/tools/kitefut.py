import requests, csv, time, datetime as D
from kitecreds import creds
k,t,_,_=creds(); H={"X-Kite-Version":"3","Authorization":f"token {k}:{t}"}
# find all listed NIFTY FUT contracts from the NFO instrument dump
r=requests.get("https://api.kite.trade/instruments/NFO",headers=H,timeout=60); r.raise_for_status()
rows=list(csv.DictReader(r.text.splitlines()))
futs=sorted([x for x in rows if x["name"]=="NIFTY" and x["instrument_type"]=="FUT"],key=lambda x:x["expiry"])
print([(x["tradingsymbol"],x["instrument_token"],x["expiry"]) for x in futs])
def fetch(tok,frm,to):
    out=[]; d=frm
    while d<=to:
        e=min(d+D.timedelta(days=90),to)
        u=f"https://api.kite.trade/instruments/historical/{tok}/5minute"
        rr=requests.get(u,headers=H,params={"from":f"{d} 09:15:00","to":f"{e} 15:30:00","oi":1},timeout=60)
        rr.raise_for_status(); out+=rr.json()["data"]["candles"]; d=e+D.timedelta(days=1); time.sleep(0.4)
    return out
for f in futs:
    c=fetch(f["instrument_token"],D.date(2026,1,1),D.date(2026,9,26))
    fn=f"D:/nifty/{f['tradingsymbol']}_5minute.csv"
    with open(fn,"w",newline="") as fh:
        w=csv.writer(fh); w.writerow(["datetime","open","high","low","close","volume","oi"])
        for x in c: w.writerow([x[0][:19].replace("T"," ")]+x[1:])
    print(fn,len(c),c[0][0] if c else None,c[-1][0] if c else None)
