"""Kite credentials for the download tools: the app's api key (application.properties) and today's access token
(broker_session, written when money-maker logs in to Zerodha). Nothing is stored here."""
import os, re, pymysql
# money-maker's own properties file, three levels up from research/strategy_lab/tools
P=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..","..","src","main","resources","application.properties")
props={}
for line in open(P,encoding="utf-8",errors="ignore"):
    m=re.match(r"\s*([\w.\-]+)\s*=\s*(.*)",line)
    if m: props[m.group(1)]=m.group(2).strip()
def resolve(v):
    """${ENV_VAR:default} -> the environment variable if set, else the default (same rule as Spring)."""
    m=re.fullmatch(r"\$\{([^:}]+):?(.*)\}",v); return os.environ.get(m.group(1),m.group(2)) if m else v
def creds():
    db=pymysql.connect(host="localhost",user=resolve(props["spring.datasource.username"]),password=resolve(props["spring.datasource.password"]),database="moneymath")
    cur=db.cursor(); cur.execute("select access_token, login_at, logged_in from broker_session where broker='ZERODHA'")
    tok,login_at,li=cur.fetchone(); return resolve(props["broker.zerodha.api-key"]),tok,login_at,li
if __name__=="__main__":
    k,t,la,li=creds(); print("login_at",la,"logged_in",li,"token present",bool(t),"apikey present",bool(k))
