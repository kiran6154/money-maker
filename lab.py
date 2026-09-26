"""Strategy lab: strategies live in the `strategy` table; `python lab.py` runs every enabled one
through engine.py, stores results in strategy_run / trade / choch_signal, and writes dashboard.html.

Edit a strategy:   sqlite3 strategy_lab.db "update strategy set date_from='2026-09-01' where code='S5M'"
Add a strategy:    insert a row (see SEED below for the columns), then run lab.py again.
"""
import sqlite3, json, csv, calendar, datetime as D, os, sys
import engine

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "strategy_lab.db")
CONFIG = os.path.join(HERE, "config", "strategies.json")   # versioned copy of the strategy + charge tables

SCHEMA = """
create table if not exists strategy(
  id integer primary key, code text unique not null, name text not null, description text,
  instrument text not null, timeframe text not null, data_file text not null,
  date_from text not null, date_to text not null, warmup_days integer not null default 5,
  break_mode text not null check(break_mode in ('touch','close')),
  avwap_weight text not null check(avwap_weight in ('volume','equal')),
  entry_rule text not null, exit_rule text not null, sl_rule text not null default 'none',
  lot_size integer not null, enabled integer not null default 1,
  created_at text default current_timestamp);
create table if not exists strategy_run(
  id integer primary key, strategy_id integer not null references strategy(id),
  run_at text not null, params_json text not null, bars integer, trades integer, wins integer,
  net_pts real, net_inr real, max_dd_pts real);
create table if not exists trade(
  id integer primary key, run_id integer not null references strategy_run(id),
  strategy_id integer not null references strategy(id), seq integer, side text,
  choch_time text, entry_time text, entry_px real, exit_time text, exit_px real,
  exit_reason text, sl_px real, pts real, inr real, is_open integer);
create table if not exists charge_schedule(
  code text primary key, segment text not null, brokerage_pct real not null, brokerage_cap real not null,
  stt_buy_pct real not null, stt_sell_pct real not null, exchange_pct real not null, sebi_pct real not null,
  stamp_buy_pct real not null, gst_pct real not null, effective_from text, notes text);
create table if not exists choch_signal(
  id integer primary key, run_id integer not null references strategy_run(id),
  strategy_id integer not null references strategy(id), time text, direction text, flipped integer,
  protected_level real, avwap real, anchor_sh_time text, anchor_sh_px real,
  anchor_sl_time text, anchor_sl_px real, setup_time text);
"""

SEED = [
  dict(code="S5M", name="Foundation · 5 min", instrument="NIFTY FUT (SEP)", timeframe="5minute",
       description="Swings -> protected level -> CHoCH -> AVWAP pair (prev SH/SL) -> SETUP; exit next CHoCH",
       data_file="D:/nifty/niftyfut_5minute_2026-07-01_to_2026-09-25.csv",
       date_from="2026-08-26", date_to="2026-09-25", warmup_days=5, break_mode="touch", avwap_weight="volume",
       entry_rule="setup_v1", exit_rule="next_choch", sl_rule="choch_candle", lot_size=65),
  dict(code="S1M", name="Foundation · 1 min", instrument="NIFTY FUT (SEP)", timeframe="minute",
       description="Same foundation rules on 1-minute candles",
       data_file="D:/nifty/niftyfut_minute_2026-07-01_to_2026-09-25.csv",
       date_from="2026-08-26", date_to="2026-09-25", warmup_days=2, break_mode="touch", avwap_weight="volume",
       entry_rule="setup_v1", exit_rule="next_choch", sl_rule="prev_swing", lot_size=65),
]


def connect():
    db = sqlite3.connect(DB); db.row_factory = sqlite3.Row; db.executescript(SCHEMA)
    migrate(db)
    if not db.execute("select count(*) from strategy").fetchone()[0]:
        # fresh database: rebuild from the versioned config if present, else from SEED
        cfg = json.load(open(CONFIG, encoding="utf-8")) if os.path.exists(CONFIG) else None
        for table, rows in (cfg.items() if cfg else [("strategy", SEED)]):
            for s in rows:
                db.execute(f"insert or replace into {table}({','.join(s)}) values({','.join('?' * len(s))})", list(s.values()))
        db.commit()
    return db


def export(db, payload):
    """Text snapshots that git versions: the strategy definitions and the latest headline results."""
    cfg = {t: [dict(r) for r in db.execute(f"select * from {t} order by 1")] for t in ("strategy", "charge_schedule")}
    for s in cfg["strategy"]: s.pop("created_at", None)
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    keys = ("code", "name", "timeframe", "date_from", "date_to", "break_mode", "avwap_weight", "entry_rule", "exit_rule",
            "sl_rule", "charge_code", "trades", "wins", "net_pts", "gross_inr", "charges_inr", "net_inr", "max_dd")
    summary = [{k: s["meta"][k] for k in keys} for s in payload]
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(summary, open(os.path.join(HERE, "results", "summary.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    with open(os.path.join(HERE, "results", "trades.csv"), "w", encoding="utf-8", newline="") as f:
        cols = ["strategy", "seq", "side", "choch_time", "entry_time", "entry_px", "sl_px", "exit_time", "exit_px",
                "exit_reason", "pts", "gross_inr", "charges_inr", "net_inr", "is_open"]
        w = csv.writer(f); w.writerow(cols)
        for s in payload:
            for r in db.execute("select seq,side,choch_time,entry_time,entry_px,sl_px,exit_time,exit_px,exit_reason,pts,"
                                "gross_inr,charges_inr,inr,is_open from trade where run_id=? order by seq", (s["meta"]["run_id"],)):
                w.writerow([s["meta"]["code"], *r])


def migrate(db):
    """Columns added after the first version of the schema."""
    cols = lambda t: {r[1] for r in db.execute(f"pragma table_info({t})")}
    if "sl_rule" not in cols("strategy"):
        db.execute("alter table strategy add column sl_rule text not null default 'none'")
        db.execute("update strategy set sl_rule='choch_candle' where code='S5M'")   # CHoCH candle high (PE) / low (CE)
        db.execute("update strategy set sl_rule='prev_swing' where code='S1M'")     # previous SH (PE) / SL (CE)
    if "sl_px" not in cols("trade"):
        db.execute("alter table trade add column sl_px real")
    if "charge_code" not in cols("strategy"):
        db.execute("alter table strategy add column charge_code text not null default 'ZERODHA_NFO_FUT'")
    for col in ("gross_inr", "charges_inr"):
        if col not in cols("trade"): db.execute(f"alter table trade add column {col} real")
        if col not in cols("strategy_run"): db.execute(f"alter table strategy_run add column {col} real")
    if not db.execute("select count(*) from charge_schedule").fetchone()[0]:
        # percentages of turnover (price x qty); brokerage per executed order, capped
        db.execute("insert into charge_schedule values(?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("ZERODHA_NFO_FUT", "NSE F&O futures", 0.03, 20.0, 0.0, 0.02, 0.00173, 0.0001, 0.002, 18.0,
                    "2024-10-01", "brokerage 0.03% or Rs20/order (lower); STT 0.02% sell; NSE txn 0.00173%; "
                    "SEBI Rs10/crore; stamp 0.002% buy; GST 18% on brokerage+txn+SEBI. Verify current rates."))
    db.commit()


def trade_charges(cs, buy_px, sell_px, qty):
    """Round-trip charges for one buy order and one sell order of qty units."""
    buy, sell = buy_px * qty, sell_px * qty
    pct = lambda v, p: v * p / 100
    brokerage = min(pct(buy, cs["brokerage_pct"]), cs["brokerage_cap"]) + min(pct(sell, cs["brokerage_pct"]), cs["brokerage_cap"])
    stt = pct(buy, cs["stt_buy_pct"]) + pct(sell, cs["stt_sell_pct"])
    exch = pct(buy + sell, cs["exchange_pct"])
    sebi = pct(buy + sell, cs["sebi_pct"])
    stamp = pct(buy, cs["stamp_buy_pct"])
    gst = pct(brokerage + exch + sebi, cs["gst_pct"])
    return dict(brokerage=brokerage, stt=stt, exchange=exch, sebi=sebi, stamp=stamp, gst=gst,
                total=brokerage + stt + exch + sebi + stamp + gst)


def ts(s): return calendar.timegm(D.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timetuple())


def run_strategy(db, st):
    bars, s0 = engine.load(st["data_file"], st["date_from"], st["date_to"], st["warmup_days"])
    p = dict(break_mode=st["break_mode"], avwap_weight=st["avwap_weight"],
             entry_rule=st["entry_rule"], exit_rule=st["exit_rule"], sl_rule=st["sl_rule"])
    r = engine.run(bars, p)
    t, o, h, l, c, v = (bars[k] for k in "tohlcv"); n = len(t); av = r["av"]; lot = st["lot_size"]
    trades = [x for x in r["trades"] if x["entry"] >= s0]
    cs = dict(db.execute("select * from charge_schedule where code=?", (st["charge_code"],)).fetchone())
    for x in trades:   # CE side = long futures (buy entry, sell exit); PE side = short (sell entry, buy exit)
        en, ex = c[x["entry"]], x["exit_px"]
        x["gross"] = x["pts"] * lot
        x["chg"] = trade_charges(cs, en if x["dir"] == "up" else ex, ex if x["dir"] == "up" else en, lot)
        x["net"] = x["gross"] - x["chg"]["total"]
    gross_inr = sum(x["gross"] for x in trades); chg_inr = sum(x["chg"]["total"] for x in trades)
    eq = peak = dd = 0.0
    for x in trades:
        eq += x["pts"]; peak = max(peak, eq); dd = min(dd, eq - peak)
    net = sum(x["pts"] for x in trades); wins = sum(1 for x in trades if x["pts"] > 0)
    p["charge_code"] = st["charge_code"]
    cur = db.execute("insert into strategy_run(strategy_id,run_at,params_json,bars,trades,wins,net_pts,gross_inr,charges_inr,"
                     "net_inr,max_dd_pts) values(?,?,?,?,?,?,?,?,?,?,?)", (st["id"], D.datetime.now().isoformat(timespec="seconds"),
                     json.dumps(p), n - s0, len(trades), wins, round(net, 2), round(gross_inr, 2), round(chg_inr, 2),
                     round(gross_inr - chg_inr, 2), round(dd, 2)))
    run_id = cur.lastrowid
    for j, x in enumerate(trades, 1):
        db.execute("insert into trade(run_id,strategy_id,seq,side,choch_time,entry_time,entry_px,exit_time,exit_px,"
                   "exit_reason,sl_px,pts,gross_inr,charges_inr,inr,is_open) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, st["id"], j, "CE" if x["dir"] == "up" else "PE", t[x["choch"]], t[x["entry"]], c[x["entry"]],
                    t[x["exit"]], x["exit_px"], x["exit_reason"], x["sl"], round(x["pts"], 2), round(x["gross"], 2),
                    round(x["chg"]["total"], 2), round(x["net"], 2), int(x["open"])))
    setup_at = {x["ch"]: x["i"] for x in r["setups"]}
    for e in r["chs"]:
        if e["i"] < s0: continue
        db.execute("insert into choch_signal(run_id,strategy_id,time,direction,flipped,protected_level,avwap,anchor_sh_time,"
                   "anchor_sh_px,anchor_sl_time,anchor_sl_px,setup_time) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, st["id"], t[e["i"]], e["dir"], int(e["flip"]), e["lvl"], round(e["av"], 2),
                    t[e["hi"]["bar"]] if e["hi"] else None, e["hi"]["p"] if e["hi"] else None,
                    t[e["lo"]["bar"]] if e["lo"] else None, e["lo"]["p"] if e["lo"] else None,
                    t[setup_at[e["i"]]] if e["i"] in setup_at else None))
    db.commit()

    # ---- chart payload ----
    r2 = lambda x: None if x is None else round(x, 2)
    C = [[ts(t[i]), o[i], h[i], l[i], c[i], r2(r["cand"][i][0]), r2(r["cand"][i][1]), int(v[i])] for i in range(s0, n)]
    S = [[s["k"], ts(t[s["bar"]]), s["p"], ts(t[s["conf"]])] for s in r["sw"] if s["conf"] >= s0]
    E = [[ts(t[e["i"]]), e["kind"], e["dir"]] for e in r["events"] if e["i"] >= s0]
    PR = [[ts(t[i]), r["prot"][i]] for i in range(s0, n) if r["prot"][i] is not None]
    PAIR = []
    for e in r["chs"]:
        if e["end"] < s0: continue
        for side, s in (("H", e["hi"]), ("L", e["lo"])):
            if not s: continue
            a = s["bar"]
            live = [[ts(t[k]), round(av(a, k), 2)] for k in range(max(e["i"], s0), e["end"] + 1)]
            back = [[ts(t[k]), round(av(a, k), 2)] for k in range(max(a, s0), e["i"] + 1)] if e["i"] >= s0 else []
            PAIR.append(dict(side=side, ch=ts(t[e["i"]]), anchor=t[a][5:16], p=s["p"], live=live, back=back))
    TR = [[ts(t[x["entry"]]), c[x["entry"]], ts(t[x["exit"]]), x["exit_px"], x["dir"], round(x["pts"], 2), x["open"],
           t[x["entry"]][5:16], t[x["exit"]][5:16], x["sl"], x["exit_reason"],
           round(x["chg"]["total"], 2), {k: round(v, 2) for k, v in x["chg"].items()}] for x in trades]
    skipped = [x for x in r["skipped"] if x["entry"] >= s0]
    meta = {k: st[k] for k in ("code", "name", "description", "instrument", "timeframe", "date_from", "date_to",
                               "break_mode", "avwap_weight", "entry_rule", "exit_rule", "sl_rule", "lot_size", "charge_code")}
    meta.update(charges=cs, gross_inr=round(gross_inr, 2), charges_inr=round(chg_inr, 2), net_inr=round(gross_inr - chg_inr, 2),
                skipped=len(skipped), run_id=run_id, net_pts=round(net, 2), trades=len(trades), wins=wins, max_dd=round(dd, 2))
    print(f'{st["code"]}: run {run_id}  bars {n - s0}  CHoCH {len([e for e in r["chs"] if e["i"] >= s0])}  '
          f'trades {len(trades)}  wins {wins}  gross {net:+.1f} pts / Rs{gross_inr:,.0f}  charges Rs{chg_inr:,.0f}  '
          f'net Rs{gross_inr - chg_inr:,.0f}  maxDD {dd:.1f}  '
          f'stops {sum(1 for x in trades if x["exit_reason"] == "stop_loss")}  skipped(SL wrong side) {len(skipped)}')
    return dict(meta=meta, C=C, S=S, E=E, PR=PR, PAIR=PAIR, TR=TR)


def main():
    db = connect()
    only = sys.argv[1:]
    sts = [dict(x) for x in db.execute("select * from strategy where enabled=1 order by id")]
    payload = [run_strategy(db, st) for st in sts if not only or st["code"] in only]
    page = open(os.path.join(HERE, "dashboard.tpl"), encoding="utf-8").read()
    page = page.replace("/*DATA*/", "const STRATS=" + json.dumps(payload, separators=(",", ":")) + ";")
    open(os.path.join(HERE, "dashboard.html"), "w", encoding="utf-8").write(page)
    export(db, payload)
    print("wrote dashboard.html, config/strategies.json, results/summary.json, results/trades.csv")


if __name__ == "__main__":
    main()
