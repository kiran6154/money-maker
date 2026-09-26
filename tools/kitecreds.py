import re, pymysql
P=r"D:/office/stocks/workspace/money-maker/src/main/resources/application.properties"
props={}
for line in open(P,encoding="utf-8",errors="ignore"):
    m=re.match(r"\s*([\w.\-]+)\s*=\s*(.*)",line)
    if m: props[m.group(1)]=m.group(2).strip()
def resolve(v):
    m=re.fullmatch(r"\$\{[^:}]+:?(.*)\}",v); return m.group(1) if m else v
def creds():
    db=pymysql.connect(host="localhost",user=resolve(props["spring.datasource.username"]),password=resolve(props["spring.datasource.password"]),database="moneymath")
    cur=db.cursor(); cur.execute("select access_token, login_at, logged_in from broker_session where broker='ZERODHA'")
    tok,login_at,li=cur.fetchone(); return resolve(props["broker.zerodha.api-key"]),tok,login_at,li
if __name__=="__main__":
    k,t,la,li=creds(); print("login_at",la,"logged_in",li,"token present",bool(t),"apikey present",bool(k))
