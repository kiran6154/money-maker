"""Strategy lab: strategies live in the `strategy` table; `python lab.py` runs every enabled one
through engine.py, stores results in strategy_run / trade / choch_signal, and writes the dashboard.

Every strategy family has variants (column `variant`):
  FUT             signals and trades on the future
  OPT_FUT_SIGNAL  signals on the future, trade the option (CE on bullish, PE on bearish)
  OPT_NATIVE      run the engine on the option's own candles (buy-only: bullish setups on CE and on PE)
Option variants are run once per strike choice (`strike_choices`), selectable in the dashboard.

Edit a strategy:   sqlite3 strategy_lab.db "update strategy set date_from='2026-09-01' where code='S5M'"
"""
import sqlite3, json, csv, calendar, datetime as D, os, sys, math, bisect, hashlib, glob
import engine

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "strategy_lab.db")
CONFIG = os.path.join(HERE, "config", "strategies.json")   # versioned copy of the strategy + charge tables
WEB = os.path.join(HERE, "web")                              # per-variant detail JSON loaded by the dashboard

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
create table if not exists test_period(
  code text primary key, label text not null, date_from text not null, date_to text not null,
  sort integer not null default 0, enabled integer not null default 1, notes text);
create table if not exists choch_signal(
  id integer primary key, run_id integer not null references strategy_run(id),
  strategy_id integer not null references strategy(id), time text, direction text, flipped integer,
  protected_level real, avwap real, anchor_sh_time text, anchor_sh_px real,
  anchor_sl_time text, anchor_sl_px real, setup_time text);
"""

FUT5 = "D:/nifty/niftyfut_5minute_2026-07-01_to_2026-09-25.csv"
FUT1 = "D:/nifty/niftyfut_minute_2026-07-01_to_2026-09-25.csv"
SPOT5 = "D:/nifty/nifty50_5minute_kite_2026-07-01_to_2026-09-25.csv"
SPOT1 = "D:/nifty/nifty50_minute_kite_2026-07-01_to_2026-09-25.csv"
OPTDIR = "D:/nifty/options/NIFTY_2026-09-29"
CHOICES = "ATR2,ATM,ITM2,ITM1,OTM1,OTM2,OTM3,OTM4"

_base = dict(date_from="2026-08-26", date_to="2026-09-25", break_mode="touch", avwap_weight="volume",
             entry_rule="setup_v1", exit_rule="next_choch", lot_size=65, option_dir=OPTDIR, option_expiry="2026-09-29",
             option_prefix="NIFTY26SEP", strike_step=50, strike_choices=CHOICES, strike_default="ATR2", atr_period=14,
             option_source="WEEKLY_LOCAL", weekly_dir="D:/nifty/data", expiry_min_days=1, positions="BOTH",
             expiry_types="WEEKLY,MONTHLY")
_fam = dict(S5M=dict(timeframe="5minute", data_file=FUT5, spot_file=SPOT5, warmup_days=5, sl_rule="choch_candle"),
            S1M=dict(timeframe="minute", data_file=FUT1, spot_file=SPOT1, warmup_days=2, sl_rule="prev_swing"))
# (variant, code suffix, label, charge schedule, slippage per side, positions)
#   futures: long on a future-long signal, short on a future-short signal
#   options on future signal, buy version:  future long -> long CE,  future short -> long PE
#   options on future signal, sell version: future long -> short PE, future short -> short CE
# One row per TYPE. Every type runs long + short; the long-only and short-only schemes are its long and short halves.
#   Futures                   long future on future long, short future on future short
#   Options on future signal  long CE / short PE on future long, long PE / short CE on future short
#   Options on native signal  the engine on the option's own chart: long on bullish setups, short on bearish setups
# (variant, code suffix, type label, charge schedule, slippage per side, signal source)
_var = [("FUT", "", "Futures", "ZERODHA_NFO_FUT", 5.0, "FUTURE"),
        ("OPT_FUT_SIGNAL", "_FB", "Options · future signal", "ZERODHA_NFO_OPT", 0.5, "FUTURE"),
        ("OPT_NATIVE", "_NB", "Options · native signal", "ZERODHA_NFO_OPT", 0.5, "OPTION_NATIVE")]
SEED = []
for fam, f in _fam.items():
    for var, suffix, label, charge, slip, source in _var:
        SEED.append(dict(code=fam + suffix, family=fam, variant=var, signal_source=source,
                         name=f"Foundation · {'5 min' if fam == 'S5M' else '1 min'} · {label}",
                         description="Swings -> protected level -> CHoCH -> AVWAP pair -> SETUP; exit SL or next CHoCH",
                         instrument="NIFTY FUT (SEP)" if var == "FUT" else "NIFTY OPT",
                         charge_code=charge, slippage_pts=slip, **dict(_base, positions="BOTH"), **f))
RETIRED = ("S5M_OF", "S1M_OF", "S5M_OB", "S1M_OB", "S5M_OS", "S1M_OS", "S5M_ON", "S1M_ON",
           "S5M_FL", "S1M_FL", "S5M_FS", "S1M_FS", "S5M_NL", "S1M_NL", "S5M_NS", "S1M_NS")   # schemes are halves of one row now


# ---------------------------------------------------------------- schema / config
def connect():
    db = sqlite3.connect(DB); db.row_factory = sqlite3.Row; db.executescript(SCHEMA)
    migrate(db)
    if not db.execute("select count(*) from strategy").fetchone()[0]:
        # fresh database: rebuild from the versioned config if present, else from SEED
        cfg = json.load(open(CONFIG, encoding="utf-8")) if os.path.exists(CONFIG) else {"strategy": SEED}
        for table, rows in cfg.items():
            for s in rows:
                db.execute(f"insert or replace into {table}({','.join(s)}) values({','.join('?' * len(s))})", list(s.values()))
        db.commit()
    seed_missing(db)
    return db


def migrate(db):
    """Columns added after the first version of the schema."""
    cols = lambda t: {r[1] for r in db.execute(f"pragma table_info({t})")}
    add = lambda t, c, ddl: c not in cols(t) and db.execute(f"alter table {t} add column {c} {ddl}")
    add("strategy", "sl_rule", "text not null default 'none'")
    add("strategy", "charge_code", "text not null default 'ZERODHA_NFO_FUT'")
    for c, ddl in (("family", "text"), ("variant", "text not null default 'FUT'"), ("spot_file", "text"),
                   ("option_dir", "text"), ("option_expiry", "text"), ("option_prefix", "text"),
                   ("strike_step", "integer default 50"), ("strike_choices", "text"), ("strike_default", "text"),
                   ("atr_period", "integer default 14"), ("slippage_pts", "real not null default 0"),
                   ("option_source", "text not null default 'WEEKLY_LOCAL'"), ("weekly_dir", "text"),
                   ("expiry_min_days", "integer not null default 1"),
                   ("positions", "text not null default 'BOTH'"),
                   ("expiry_types", "text not null default 'WEEKLY,MONTHLY'"),
                   ("signal_source", "text")):
        add("strategy", c, ddl)
    for c, ddl in (("sl_px", "real"), ("gross_inr", "real"), ("charges_inr", "real"), ("instrument", "text"),
                   ("strike", "real"), ("strike_choice", "text"), ("und_entry_px", "real"), ("und_exit_px", "real"),
                   ("slippage_pts", "real")):
        add("trade", c, ddl)
    for c, ddl in (("gross_inr", "real"), ("charges_inr", "real"), ("strike_choice", "text")):
        add("strategy_run", c, ddl)
    add("charge_schedule", "brokerage_flat", "real not null default 0")
    add("strategy_run", "period", "text")
    add("trade", "period", "text")
    add("trade", "mfe_pts", "real")
    for c in ("position", "signal", "opt_type", "expiry"): add("trade", c, "text")
    add("trade", "mae_pts", "real")
    if not db.execute("select count(*) from test_period").fetchone()[0]:
        db.executemany("insert into test_period(code,label,date_from,date_to,sort,notes) values(?,?,?,?,?,?)", [
            ("IS", "In-sample · 26 Aug – 25 Sep", "2026-08-26", "2026-09-25", 1,
             "Rules were designed on this window. SEP FUT is the front month."),
            ("OOS", "Out-of-sample · 8 Jul – 25 Aug", "2026-07-08", "2026-08-25", 2,
             "Untouched by rule design. SEP FUT is the next-month contract (thinner volume); 29-Sep options have 5-12 weeks to expiry.")])
    if not db.execute("select count(*) from charge_schedule where code='ZERODHA_NFO_FUT'").fetchone()[0]:
        db.execute("insert into charge_schedule(code,segment,brokerage_pct,brokerage_cap,stt_buy_pct,stt_sell_pct,exchange_pct,"
                   "sebi_pct,stamp_buy_pct,gst_pct,effective_from,notes,brokerage_flat) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("ZERODHA_NFO_FUT", "NSE F&O futures", 0.03, 20.0, 0.0, 0.02, 0.00173, 0.0001, 0.002, 18.0, "2024-10-01",
                    "brokerage 0.03% or Rs20/order (lower); STT 0.02% sell; NSE txn 0.00173%; SEBI Rs10/crore; "
                    "stamp 0.002% buy; GST 18% on brokerage+txn+SEBI. Verify current rates.", 0))
    if not db.execute("select count(*) from charge_schedule where code='ZERODHA_NFO_OPT'").fetchone()[0]:
        db.execute("insert into charge_schedule(code,segment,brokerage_pct,brokerage_cap,stt_buy_pct,stt_sell_pct,exchange_pct,"
                   "sebi_pct,stamp_buy_pct,gst_pct,effective_from,notes,brokerage_flat) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("ZERODHA_NFO_OPT", "NSE F&O options", 0, 0, 0.0, 0.1, 0.03503, 0.0001, 0.003, 18.0, "2024-10-01",
                    "brokerage flat Rs20/order; STT 0.1% of sell premium; NSE txn 0.03503% of premium; SEBI Rs10/crore; "
                    "stamp 0.003% buy; GST 18% on brokerage+txn+SEBI. Verify current rates.", 20.0))
    db.commit()


def seed_missing(db):
    """Fill new columns on existing rows and add any SEED strategy that is not in the table yet."""
    db.executemany("update strategy set enabled=0 where code=?", [(c,) for c in RETIRED])
    for x in SEED:   # current labels for the live rows
        db.execute("update strategy set name=?, positions='BOTH', enabled=1 where code=?", (x["name"], x["code"]))
    have = {r["code"]: dict(r) for r in db.execute("select * from strategy")}
    for s in SEED:
        if s["code"] not in have:
            db.execute(f"insert into strategy({','.join(s)}) values({','.join('?' * len(s))})", list(s.values()))
        else:
            for k, v in s.items():
                if have[s["code"]].get(k) is None:
                    db.execute(f"update strategy set {k}=? where code=?", (v, s["code"]))
            if have[s["code"]]["variant"] == "FUT" and not have[s["code"]]["slippage_pts"]:
                db.execute("update strategy set slippage_pts=? where code=?", (s["slippage_pts"], s["code"]))
    db.commit()


# ---------------------------------------------------------------- helpers
def ts(s): return calendar.timegm(D.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timetuple())


def trade_charges(cs, buy_px, sell_px, qty):
    """Round-trip charges for one buy order and one sell order of qty units."""
    buy, sell = buy_px * qty, sell_px * qty
    pct = lambda v, p: v * p / 100
    if cs.get("brokerage_flat"):
        brokerage = 2 * cs["brokerage_flat"]
    else:
        brokerage = min(pct(buy, cs["brokerage_pct"]), cs["brokerage_cap"]) + min(pct(sell, cs["brokerage_pct"]), cs["brokerage_cap"])
    stt = pct(buy, cs["stt_buy_pct"]) + pct(sell, cs["stt_sell_pct"])
    exch = pct(buy + sell, cs["exchange_pct"])
    sebi = pct(buy + sell, cs["sebi_pct"])
    stamp = pct(buy, cs["stamp_buy_pct"])
    gst = pct(brokerage + exch + sebi, cs["gst_pct"])
    return dict(brokerage=brokerage, stt=stt, exchange=exch, sebi=sebi, stamp=stamp, gst=gst,
                total=brokerage + stt + exch + sebi + stamp + gst)


class Series:
    """Candles of one instrument with time lookup."""
    _cache = {}

    def __init__(self, path=None, rows=None):
        if rows is None:
            rows = list(csv.DictReader(open(path))) if path and os.path.exists(path) else []
        self.t = [r["datetime"] for r in rows]
        self.o, self.h, self.l, self.c = ([float(r[k]) for r in rows] for k in ("open", "high", "low", "close"))
        self.v = [float(r.get("volume") or 0) for r in rows]
        self.ix = {x: i for i, x in enumerate(self.t)}

    @classmethod
    def from_rows(cls, rows):
        return cls(rows=rows)

    @classmethod
    def get(cls, path):
        if path not in cls._cache: cls._cache[path] = cls(path)
        return cls._cache[path]

    def at(self, when):
        """Close at `when`, else the last close earlier the same day (stale); None if nothing that day."""
        i = self.ix.get(when)
        if i is not None: return self.c[i], False
        j = bisect.bisect_right(self.t, when) - 1
        if j >= 0 and self.t[j][:10] == when[:10]: return self.c[j], True
        return None, False


def atr_series(s, n):
    """Wilder ATR(n) per candle (value includes the candle itself)."""
    out, a, trs = [], 0.0, []
    for i in range(len(s.t)):
        tr = s.h[i] - s.l[i] if i == 0 else max(s.h[i] - s.l[i], abs(s.h[i] - s.c[i - 1]), abs(s.l[i] - s.c[i - 1]))
        trs.append(tr)
        a = sum(trs) / len(trs) if i < n else (a * (n - 1) + tr) / n   # simple mean until n candles, then Wilder
        out.append(a)
    return out


def pick_strike(choice, side, spot, atr, step):
    """Strike from spot at decision time. OTM = away from spot (CE above, PE below)."""
    rnd = lambda x: round(x / step) * step
    sg = 1 if side == "CE" else -1
    if choice.startswith("ATR"):
        return rnd(spot + sg * float(choice[3:]) * atr)
    atm = rnd(spot)
    if choice == "ATM": return atm
    n = int(choice[3:])
    return atm + sg * n * step if choice.startswith("OTM") else atm - sg * n * step


def stats(trs):
    """Headline numbers over priced trades."""
    net = [x["net"] for x in trs]
    eq = peak = dd = 0.0
    for v in net: eq += v; peak = max(peak, eq); dd = min(dd, eq - peak)
    wk = {}
    for x in trs:
        y, w, _ = D.date.fromisoformat(x["entry_time"][:10]).isocalendar(); wk[f"{y}-W{w:02d}"] = wk.get(f"{y}-W{w:02d}", 0) + x["net"]
    m = sum(net) / len(net) if net else 0
    sd = math.sqrt(sum((v - m) ** 2 for v in net) / (len(net) - 1)) if len(net) > 1 else 0
    wins = [v for v in net if v > 0]; loss = [v for v in net if v <= 0]
    return dict(trades=len(trs), wins=len(wins), pts=round(sum(x["pts"] for x in trs), 2),
                gross_inr=round(sum(x["gross"] for x in trs), 2), charges_inr=round(sum(x["chg"]["total"] for x in trs), 2),
                net_inr=round(sum(net), 2), max_dd_inr=round(dd, 2),
                pf=round(sum(wins) / -sum(loss), 2) if loss and sum(loss) else None,
                t_stat=round(m / (sd / math.sqrt(len(net))), 2) if sd else None,
                weeks=len(wk), pos_weeks=sum(1 for v in wk.values() if v > 0),
                worst_week=min(wk.items(), key=lambda kv: kv[1]) if wk else None)


def chart(bars, r, i0, i1, marks):
    """Chart payload for bars[i0..i1] with engine overlays and trade marks on this chart's prices."""
    t, o, h, l, c, v = (bars[k] for k in "tohlcv"); av = r["av"]
    r2 = lambda x: None if x is None else round(x, 2)
    C = [[ts(t[i]), o[i], h[i], l[i], c[i], r2(r["cand"][i][0]), r2(r["cand"][i][1]), int(v[i])] for i in range(i0, i1 + 1)]
    S = [[s["k"], ts(t[s["bar"]]), s["p"], ts(t[s["conf"]])] for s in r["sw"] if i0 <= s["conf"] <= i1]
    E = [[ts(t[e["i"]]), e["kind"], e["dir"]] for e in r["events"] if i0 <= e["i"] <= i1]
    PR = [[ts(t[i]), r["prot"][i]] for i in range(i0, i1 + 1) if r["prot"][i] is not None]
    PAIR = []
    for e in r["chs"]:
        if e["end"] < i0 or e["i"] > i1: continue
        for side, s in (("H", e["hi"]), ("L", e["lo"])):
            if not s: continue
            a = s["bar"]
            live = [[ts(t[k]), round(av(a, k), 2)] for k in range(max(e["i"], i0), min(e["end"], i1) + 1)]
            back = [[ts(t[k]), round(av(a, k), 2)] for k in range(max(a, i0), min(e["i"], i1) + 1)] if e["i"] >= i0 else []
            PAIR.append(dict(side=side, ch=ts(t[e["i"]]), anchor=t[a][5:16], p=s["p"], live=live, back=back))
    return dict(C=C, S=S, E=E, PR=PR, PAIR=PAIR, M=marks)


def mark(x, bars, label=None):
    """Trade drawn on a chart: [entry ts, entry px, exit ts, exit px, dir, pts, open, sl, reason, label]."""
    t = bars["t"]
    return [ts(t[x["entry"]]), bars["c"][x["entry"]], ts(t[x["exit"]]), x["exit_px"], x["dir"], None, x["open"], x["sl"],
            x["exit_reason"], label]


def option_chart(s, i0, i1, marks):
    """Chart payload for an option contract's own candles (no engine overlays: the signals came from elsewhere)."""
    C = [[ts(s.t[i]), s.o[i], s.h[i], s.l[i], s.c[i], None, None, int(s.v[i])] for i in range(i0, i1 + 1)]
    return dict(C=C, S=[], E=[], PR=[], PAIR=[], M=marks)


class OptionChain:
    """Option candles by (expiry, strike, CE/PE) for one timeframe.

    WEEKLY_LOCAL reads the local ICICI weekly files under `weekly_dir` (5-minute: one CSV per expiry and right;
    1-minute: per-strike chunk files) plus the full Kite chain saved under `option_dir` for `option_expiry`.
    The local weekly files hold only strikes near the ATM of the day before expiry - a window chosen with hindsight -
    so they are used for prices only: the strike always comes from spot at decision time, and a strike that is not in
    the file is reported as missing, never replaced by one that is."""

    def __init__(self, st):
        self.tf, self.local, self.kite = st["timeframe"], st["weekly_dir"], st["option_dir"]
        self.kite_exp, self.pre = st["option_expiry"], st["option_prefix"]
        sub = "nifty_options" if self.tf == "5minute" else "nifty_options_1minute"
        self.root = os.path.join(self.local, sub)
        cal = set([self.kite_exp])
        for y in os.listdir(self.root) if os.path.isdir(self.root) else []:
            if y.isdigit(): cal |= {e for e in os.listdir(os.path.join(self.root, y)) if len(e) == 10}
        self.calendar = sorted(cal)          # every weekly expiry date known, with or without data
        self._rights, self._cache = {}, {}

    def expiry_for(self, day, min_days, kind="WEEKLY"):
        """Nearest expiry of `kind` (WEEKLY: any weekly expiry; MONTHLY: the last expiry of a month) at least
        `min_days` calendar days after `day`."""
        d = D.date.fromisoformat(day)
        cal = self.calendar
        if kind == "MONTHLY":
            last = {}
            for e in cal: last[e[:7]] = e           # calendar is sorted: the month's last expiry wins
            cal = sorted(last.values())
        return next((e for e in cal if (D.date.fromisoformat(e) - d).days >= min_days), None)

    def _local_right(self, expiry, right):
        key = (expiry, right)
        if key in self._rights: return self._rights[key]
        base = os.path.join(self.root, expiry[:4], expiry)
        by = {}
        files = [os.path.join(base, f"NIFTY_{expiry}_{right}_{'5minute' if self.tf == '5minute' else '1minute'}.csv")]
        if self.tf != "5minute":
            files += sorted(glob.glob(os.path.join(base, ".chunks", "options", right, "*", "*.csv")))
        for f in files:
            if not os.path.exists(f): continue
            for r in csv.DictReader(open(f)):
                if r["datetime"][11:16] > "15:29": continue
                by.setdefault(int(float(r["strike_price"])), {})[r["datetime"]] = r
        self._rights[key] = {k: [v[t] for t in sorted(v)] for k, v in by.items()}
        return self._rights[key]

    def get(self, expiry, strike, right):
        key = (expiry, int(strike), right)
        if key in self._cache: return self._cache[key]
        s = None
        if expiry == self.kite_exp:
            p = os.path.join(self.kite, "minute" if self.tf == "minute" else "5minute", f"{self.pre}{int(strike)}{right}.csv")
            if os.path.exists(p) and os.path.getsize(p) > 100: s = Series(p)
        else:
            rows = self._local_right(expiry, right).get(int(strike))
            if rows: s = Series.from_rows(rows)
        self._cache[key] = s if s and s.t else None
        return self._cache[key]

    def name(self, expiry, strike, right):
        return f"NIFTY {D.date.fromisoformat(expiry):%d%b%y} {int(strike)} {right}".upper()


def expire(rec, s, expiry):
    """A position still open after its contract's last candle is closed at that candle (reason 'expiry')."""
    last = bisect.bisect_right(s.t, f"{expiry} 23:59:59") - 1
    if last >= 0 and s.t[last] < rec["exit_time"]:
        rec.update(exit_time=s.t[last], exit_px=s.c[last], exit_reason="expiry", open=False)
    return rec


# ---------------------------------------------------------------- variants
def choice_keys(st):
    """Result keys: '-' for futures; '<W|M>-<strike choice>' for options (expiry type x strike choice)."""
    if st["variant"] == "FUT": return ["-"]
    return [f"{e.strip()[0]}-{c.strip()}" for e in (st.get("expiry_types") or "WEEKLY").split(",")
            for c in st["strike_choices"].split(",")]


def split_choice(key):
    kind, strike = key.split("-", 1)
    return ("MONTHLY" if kind == "M" else "WEEKLY"), strike


def excursion(tl, hl, ll, rec, long):
    """Max favourable / adverse move inside the trade, in traded-instrument points (before slippage).
    Uses candles after the entry candle up to and including the exit candle."""
    i0 = bisect.bisect_right(tl, rec["entry_time"]); i1 = bisect.bisect_right(tl, rec["exit_time"]) - 1
    if i1 < i0:
        rec.update(mfe=0.0, mae=0.0); return rec
    hi, lo, e = max(hl[i0:i1 + 1]), min(ll[i0:i1 + 1]), rec["entry_px"]
    fav, adv = (hi - e, lo - e) if long else (e - lo, e - hi)
    rec.update(mfe=round(max(fav, 0.0), 2), mae=round(min(adv, 0.0), 2))
    return rec


def price_trade(st, cs, rec):
    """Slippage, gross, charges, net for a trade record with entry_px / exit_px in traded-instrument units."""
    lot, slip = st["lot_size"], st["slippage_pts"]
    if rec["position"] == "SHORT":                             # short: sell entry, buy exit
        sell, buy = rec["entry_px"] - slip, rec["exit_px"] + slip
    else:                                                      # long future or long option
        buy, sell = rec["entry_px"] + slip, rec["exit_px"] - slip
    pts = sell - buy
    rec.update(pts=pts, gross=pts * lot, chg=trade_charges(cs, buy, sell, lot))
    rec["net"] = rec["gross"] - rec["chg"]["total"]
    return rec


def run_variant(st, cs):
    """Returns {choice: dict(trades, skipped, charts, signals)} for one strategy row.

    Terminology: `position` is LONG/SHORT, `opt_type` the instrument (FUT/CE/PE), `signal` BULLISH/BEARISH.
    Long and short positions exist in futures and in both CE and PE. Futures: long on bullish, short on bearish.
    Option on future signal: bullish -> long CE and short PE, bearish -> long PE and short CE, each leg a separate trade.
    Option native: bullish setup on the option's chart -> long that option, bearish setup -> short it.
    `positions` (BOTH / LONG / SHORT) limits option variants to one side."""
    fut, s0 = engine.load(st["data_file"], st["date_from"], st["date_to"], st["warmup_days"])
    p = dict(break_mode=st["break_mode"], avwap_weight=st["avwap_weight"], sl_rule=st["sl_rule"])
    spot = Series.get(st["spot_file"]); atr = atr_series(spot, st["atr_period"])
    step = st["strike_step"]
    chain = OptionChain(st) if st["variant"] != "FUT" else None
    out = {}

    if st["variant"] in ("FUT", "OPT_FUT_SIGNAL"):
        r = engine.run(fut, p)
        sig = [x for x in r["trades"] if x["entry"] >= s0]
        t = fut["t"]
        signals = [dict(time=t[e["i"]], dir=e["dir"], flipped=e["flip"], lvl=e["lvl"], av=e["av"],
                        hi=(t[e["hi"]["bar"]], e["hi"]["p"]) if e["hi"] else None,
                        lo=(t[e["lo"]["bar"]], e["lo"]["p"]) if e["lo"] else None) for e in r["chs"] if e["i"] >= s0]
        setup_at = {x["ch"]: t[x["i"]] for x in r["setups"]}
        for sgl, e in zip(signals, [e for e in r["chs"] if e["i"] >= s0]): sgl["setup"] = setup_at.get(e["i"])
        day_span = {}
        for i in range(s0, len(t)):
            day_span.setdefault(t[i][:10], [i, i])[1] = i
        day_base = {d: chart(fut, r, i0, i1, []) for d, (i0, i1) in day_span.items()}
        for ch in choice_keys(st):
            ekind, sc = split_choice(ch) if ch != "-" else (None, None)
            trs, skipped, fmarks, omarks = [], [], [], {}
            for x in sig:
                bull = x["dir"] == "up"
                base = dict(dir=x["dir"], signal="BULLISH" if bull else "BEARISH", choch_time=t[x["choch"]],
                            entry_time=t[x["entry"]], exit_time=t[x["exit"]], exit_reason=x["exit_reason"], open=x["open"],
                            sl=x["sl"], und_entry=fut["c"][x["entry"]], und_exit=x["exit_px"], expiry=None)
                if st["variant"] == "FUT":
                    rec = dict(base, kind="FUT", position="LONG" if bull else "SHORT", opt_type="FUT",
                               instrument="NIFTY SEP FUT", strike=None, entry_px=fut["c"][x["entry"]], exit_px=x["exit_px"])
                    excursion(t, fut["h"], fut["l"], rec, bull)
                    legs = [(price_trade(st, cs, rec), "LONG" if bull else "SHORT", None)]
                else:
                    # bullish -> long CE and short PE; bearish -> long PE and short CE (separate positions)
                    legs = []
                    for pos in (("LONG", "SHORT") if st["positions"] == "BOTH" else (st["positions"],)):
                        right = ("CE" if bull else "PE") if pos == "LONG" else ("PE" if bull else "CE")
                        si = spot.ix.get(t[x["entry"]])
                        if si is None: skipped.append(dict(base, position=pos, opt_type=right, why="no spot candle")); continue
                        k = pick_strike(sc, right, spot.c[si], atr[si], step)
                        exp = chain.expiry_for(t[x["entry"]][:10], st["expiry_min_days"], ekind)
                        os_ = chain.get(exp, k, right) if exp else None
                        nm = chain.name(exp, k, right) if exp else f"{int(k)} {right}"
                        if os_ is None:
                            skipped.append(dict(base, position=pos, opt_type=right, why=f"no data for {nm}")); continue
                        en, st1 = os_.at(t[x["entry"]])
                        if en is None:
                            skipped.append(dict(base, position=pos, opt_type=right, why=f"{nm} has no candle at entry")); continue
                        rec = dict(base, kind="OPT", position=pos, opt_type=right, instrument=nm, strike=k, expiry=exp,
                                   entry_px=en, exit_px=None, stale=st1)
                        expire(rec, os_, exp)
                        if rec["exit_px"] is None:
                            ex, st2 = os_.at(rec["exit_time"])
                            if ex is None:
                                skipped.append(dict(base, position=pos, opt_type=right, why=f"{nm} has no candle at exit")); continue
                            rec.update(exit_px=ex, stale=st1 or st2)
                        excursion(os_.t, os_.h, os_.l, rec, pos == "LONG")
                        legs.append((price_trade(st, cs, rec), f"{pos} {right}", os_))
                for rec, lbl, os_ in legs:
                    trs.append(rec)
                    fm = mark(x, fut, lbl); fm[5] = round(rec["pts"], 2); fm.append(x["dir"])
                    if rec["exit_reason"] == "expiry": fm[2], fm[8] = ts(rec["exit_time"]), "expiry"
                    fmarks.append(fm)
                    if os_ is not None:                        # the traded option's own chart
                        omarks.setdefault((rec["instrument"], rec["entry_time"][:10]), (os_, []))[1].append(
                            [ts(rec["entry_time"]), rec["entry_px"], ts(rec["exit_time"]), rec["exit_px"],
                             "up" if rec["position"] == "LONG" else "down", round(rec["pts"], 2), rec["open"], None,
                             rec["exit_reason"], lbl, x["dir"]])
            charts = []
            for d, (i0, i1) in day_span.items():      # one futures chart chunk per session, loaded lazily by the dashboard
                lo, hi = ts(t[i0]), ts(t[i1])
                mk = [m for m in fmarks if m[0] <= hi and m[2] >= lo]
                n = sum(1 for m in fmarks if lo <= m[0] <= hi)
                pnl = sum(m[5] for m in fmarks if lo <= m[0] <= hi)
                charts.append(dict(day_base[d], M=mk, day=d, kind="signal",
                                   label=f"{d} · futures" + (f" · {n} trades · {pnl:+.1f} pts" if n else "")))
            for (nm, d), (os_, mk) in sorted(omarks.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                i0 = bisect.bisect_left(os_.t, f"{d} 00:00:00")
                i1 = max(bisect.bisect_right(os_.t, f"{d} 23:59:59") - 1,
                         max(bisect.bisect_right(os_.t, D.datetime.utcfromtimestamp(m[2]).strftime("%Y-%m-%d %H:%M:%S")) - 1 for m in mk))
                charts.append(dict(option_chart(os_, i0, i1, mk), day=d, kind="option",
                                   label=f"{d} · {nm} · {len(mk)} trade{'s' * (len(mk) > 1)} · {sum(m[5] for m in mk):+.1f} pts"))
            out[ch] = dict(trades=trs, skipped=skipped, signals=signals, charts=charts)
        return out

    # OPT_NATIVE: the engine runs on the option's own candles: a bullish setup opens a long position in that option,
    # a bearish setup a short position (per `positions`).
    # Each day's CE and PE contract (nearest weekly expiry, strike from spot) is fixed at the first completed candle.
    days = sorted({x[:10] for x in fut["t"][s0:]})
    runs = {}
    for ch in choice_keys(st):
        ekind, sc = split_choice(ch)
        trs, skipped, charts = [], [], []
        for d in days:
            first = bisect.bisect_left(spot.t, f"{d} 00:00:00")
            if first >= len(spot.t) or spot.t[first][:10] != d: continue
            exp = chain.expiry_for(d, st["expiry_min_days"], ekind)
            for right in ("CE", "PE"):
                k = pick_strike(sc, right, spot.c[first], atr[first], step)
                nm = chain.name(exp, k, right) if exp else f"{int(k)} {right}"
                os_ = chain.get(exp, k, right) if exp else None
                if os_ is None:
                    skipped.append(dict(signal="BULLISH", opt_type=right, entry_time=d, why=f"no data for {nm}")); continue
                key = (exp, int(k), right)
                if key not in runs:
                    try:
                        ob, os0 = engine.window(dict(t=os_.t, o=os_.o, h=os_.h, l=os_.l, c=os_.c, v=os_.v),
                                                st["date_from"], st["date_to"], st["warmup_days"], nm)
                        runs[key] = (ob, engine.run(ob, p))
                    except ValueError:
                        runs[key] = None
                if runs[key] is None:
                    skipped.append(dict(signal="BULLISH", opt_type=right, entry_time=d, why=f"no candles for {nm} in period")); continue
                ob, r = runs[key]; t = ob["t"]
                day_idx = [i for i, x in enumerate(t) if x[:10] == d]
                if not day_idx:
                    skipped.append(dict(signal="BULLISH", opt_type=right, entry_time=d, why=f"{nm} has no candles on {d}")); continue
                want = {"BOTH": ("up", "down"), "LONG": ("up",), "SHORT": ("down",)}[st["positions"]]
                picks = [x for x in r["trades"] if x["dir"] in want and t[x["entry"]][:10] == d and x["entry"] > day_idx[0]]
                marks = []
                for x in picks:
                    lng = x["dir"] == "up"
                    rec = dict(dir=x["dir"], signal="BULLISH" if lng else "BEARISH", position="LONG" if lng else "SHORT",
                               opt_type=right, kind="OPT", instrument=nm, strike=k,
                               expiry=exp, choch_time=t[x["choch"]], entry_time=t[x["entry"]], exit_time=t[x["exit"]],
                               exit_reason=x["exit_reason"], open=x["open"], sl=x["sl"], entry_px=ob["c"][x["entry"]],
                               exit_px=x["exit_px"], und_entry=None, und_exit=None)
                    if x["open"] and t[x["exit"]][:10] == exp:
                        rec.update(exit_reason="expiry", open=False)     # the contract's data ends at its expiry
                    excursion(t, ob["h"], ob["l"], rec, lng)
                    trs.append(price_trade(st, cs, rec))
                    m = mark(x, ob, f"{rec['position']} {right}"); m[5] = round(rec["pts"], 2); m[8] = rec["exit_reason"]
                    m.append(x["dir"]); marks.append(m)
                i1 = max([day_idx[-1]] + [x["exit"] for x in picks])
                charts.append(dict(label=f"{d} · {nm}" + (f" · {len(picks)} trade{'s' * (len(picks) > 1)}" if picks else ""),
                                   day=d, kind="option", **chart(ob, r, day_idx[0], i1, marks)))
        trs.sort(key=lambda x: x["entry_time"])
        out[ch] = dict(trades=trs, skipped=skipped, signals=[], charts=charts)
    return out


def side_of(res, positions):
    """Long only / short only rows are the matching side of the long + short run (same signals, same fills)."""
    if positions == "BOTH":
        return res
    keep = lambda lbl, d: (lbl or ("LONG" if d == "up" else "SHORT")).startswith(positions)
    trades = [x for x in res["trades"] if x["position"] == positions]
    skipped = [x for x in res["skipped"] if x.get("position", positions) == positions]
    charts = []
    for c in res["charts"]:
        M = [m for m in c["M"] if keep(m[9] if len(m) > 9 else None, m[4])]
        if c.get("kind") == "option" and c["M"] and not M and not c["S"]:
            continue                      # an option-on-future-signal contract chart with none of this side's trades
        lo, hi = c["C"][0][0], c["C"][-1][0]
        inday = [m for m in M if lo <= m[0] <= hi]
        head = " · ".join(c["label"].split(" · ")[:2])
        label = head + (f" · {len(inday)} trade{'s' * (len(inday) > 1)} · {sum(m[5] for m in inday):+.1f} pts" if inday else "")
        charts.append(dict(c, M=M, label=label))
    return dict(trades=trades, skipped=skipped, signals=res["signals"], charts=charts)


# ---------------------------------------------------------------- persistence + output
def save_run(db, st, ch, res, cs):
    s = stats(res["trades"])
    params = {k: st[k] for k in ("variant", "break_mode", "avwap_weight", "entry_rule", "exit_rule", "sl_rule",
                                 "charge_code", "slippage_pts", "timeframe")}
    params.update(strike_choice=ch, period=st["period"], date_from=st["date_from"], date_to=st["date_to"])
    run_id = db.execute("insert into strategy_run(strategy_id,run_at,params_json,bars,trades,wins,net_pts,gross_inr,charges_inr,"
                        "net_inr,max_dd_pts,strike_choice,period) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (st["id"], D.datetime.now().isoformat(timespec="seconds"), json.dumps(params), None, s["trades"], s["wins"],
                         s["pts"], s["gross_inr"], s["charges_inr"], s["net_inr"], s["max_dd_inr"], ch, st["period"])).lastrowid
    for j, x in enumerate(res["trades"], 1):
        db.execute("insert into trade(run_id,strategy_id,seq,side,choch_time,entry_time,entry_px,exit_time,exit_px,exit_reason,sl_px,"
                   "pts,gross_inr,charges_inr,inr,is_open,instrument,strike,strike_choice,und_entry_px,und_exit_px,slippage_pts,period,"
                   "mfe_pts,mae_pts,position,signal,opt_type,expiry) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, st["id"], j, x["position"], x["choch_time"], x["entry_time"], x["entry_px"], x["exit_time"], x["exit_px"],
                    x["exit_reason"], x["sl"], round(x["pts"], 2), round(x["gross"], 2), round(x["chg"]["total"], 2),
                    round(x["net"], 2), int(x["open"]), x["instrument"], x["strike"], ch, x["und_entry"], x["und_exit"],
                    st["slippage_pts"], st["period"], x["mfe"], x["mae"], x["position"], x["signal"], x["opt_type"], x["expiry"]))
    for g in res["signals"]:
        db.execute("insert into choch_signal(run_id,strategy_id,time,direction,flipped,protected_level,avwap,anchor_sh_time,"
                   "anchor_sh_px,anchor_sl_time,anchor_sl_px,setup_time) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, st["id"], g["time"], g["dir"], int(g["flipped"]), g["lvl"], round(g["av"], 2),
                    *(g["hi"] or (None, None)), *(g["lo"] or (None, None)), g["setup"]))
    return run_id, s


def write_result(folder, st, ch, res, s, cs, key):
    """Result folder: summary.json (KPIs, trades, signals, chart index) + one c<k>.json per chart chunk (a session / contract).
    The dashboard reads the summary first and fetches chart chunks only when they are shown."""
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder): os.remove(os.path.join(folder, f))
    trades = [[x["opt_type"], x["instrument"], x["strike"], x["choch_time"], x["entry_time"], x["entry_px"], x["sl"], x["exit_time"],
               x["exit_px"], x["exit_reason"], round(x["pts"], 2), round(x["gross"], 2), round(x["chg"]["total"], 2),
               round(x["net"], 2), x["open"], {k: round(v, 2) for k, v in x["chg"].items()}, x.get("und_entry"), x.get("und_exit"),
               bool(x.get("stale")), x["mfe"], x["mae"], x["position"], x["opt_type"], x["signal"], x["expiry"]] for x in res["trades"]]
    charts = []
    for k, c in enumerate(res["charts"]):
        fn = f"c{k}.json"
        json.dump({kk: v for kk, v in c.items() if kk not in ("label", "day", "kind")}, open(os.path.join(folder, fn), "w"), separators=(",", ":"))
        charts.append(dict(label=c["label"], day=c.get("day"), kind=c.get("kind", "signal"), file=fn, marks=[m[0] for m in c["M"]]))
    json.dump(dict(code=st["code"], choice=ch, period=st["period"], key=key, stats=s, charges=cs, trades=trades,
                   stats_long=stats([x for x in res["trades"] if x["position"] == "LONG"]),
                   stats_short=stats([x for x in res["trades"] if x["position"] == "SHORT"]),
                   skipped=res["skipped"], signals=res["signals"], charts=charts),
              open(os.path.join(folder, "summary.json"), "w", encoding="utf-8"), separators=(",", ":"))


def cache_key(st, pr):
    """Everything a result depends on: the strategy row, the period, the code, and the input data files."""
    h = hashlib.sha1()
    row = {k: v for k, v in st.items() if k not in ("id", "created_at", "enabled", "name", "description")}
    h.update(json.dumps([row, pr["date_from"], pr["date_to"]], sort_keys=True, default=str).encode())
    for f in (os.path.join(HERE, "engine.py"), os.path.join(HERE, "lab.py")):
        h.update(open(f, "rb").read().replace(b"\r\n", b"\n"))   # line endings differ across checkouts
    files = [st["data_file"], st["spot_file"], os.path.join(st["option_dir"] or "", "manifest.csv")]
    if st["variant"] != "FUT" and st.get("weekly_dir"):
        files += sorted(glob.glob(os.path.join(st["weekly_dir"], "nifty_options*", "*", "*", "manifest.json")))
    for f in files:
        if f and os.path.exists(f): h.update(f"{f}:{os.path.getsize(f)}:{int(os.path.getmtime(f))}".encode())
    return h.hexdigest()[:16]


def main():
    db = connect()
    full = "--full" in sys.argv                     # recompute everything, ignoring stored results
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    sts = [dict(x) for x in db.execute("select * from strategy where enabled=1 order by family, id")]
    os.makedirs(WEB, exist_ok=True)
    periods = [dict(r) for r in db.execute("select * from test_period where enabled=1 order by sort")]
    index, summary, all_trades, group_runs = [], [], [], {}
    for st in sts:
        if only and st["code"] not in only and st["family"] not in only: continue
        cs = dict(db.execute("select * from charge_schedule where code=?", (st["charge_code"],)).fetchone())
        meta = {k: st[k] for k in ("code", "family", "variant", "positions", "signal_source", "name", "description",
                                   "instrument", "timeframe",
                                   "break_mode", "avwap_weight", "entry_rule", "exit_rule", "sl_rule", "lot_size",
                                   "charge_code", "slippage_pts", "strike_choices", "strike_default", "atr_period",
                                   "expiry_types")}
        meta["periods"] = {}
        for pr in periods:
            stp = dict(st, date_from=pr["date_from"], date_to=pr["date_to"], period=pr["code"])
            key = cache_key(st, pr)
            choices = choice_keys(st)
            folders = {ch: os.path.join(WEB, st["code"], pr["code"], ch) for ch in choices}
            stored = {}
            if not full:
                for ch, fo in folders.items():
                    f = os.path.join(fo, "summary.json")
                    if os.path.exists(f):
                        d = json.load(open(f, encoding="utf-8"))
                        if d.get("key") == key: stored[ch] = d
            fresh = len(stored) < len(choices)
            if fresh:
                gk = (st["family"], st["variant"], pr["code"])
                if gk not in group_runs:
                    group_runs[gk] = run_variant(dict(stp, positions="BOTH"), cs)
                res = {ch: side_of(rr, st["positions"]) for ch, rr in group_runs[gk].items()}
            meta["periods"][pr["code"]] = {}
            for ch in choices:
                if fresh:
                    rr = res[ch]
                    run_id, s = save_run(db, stp, ch, rr, cs)
                    write_result(folders[ch], stp, ch, rr, s, cs, key)
                    rows = [[x["position"], x["instrument"], x["entry_time"], x["entry_px"], x["exit_time"], x["exit_px"], x["exit_reason"],
                             round(x["pts"], 2), round(x["gross"], 2), round(x["chg"]["total"], 2), round(x["net"], 2), int(x["open"])]
                            for x in rr["trades"]]
                    n_skip = len(rr["skipped"])
                    s_long = stats([x for x in rr["trades"] if x["position"] == "LONG"])
                    s_short = stats([x for x in rr["trades"] if x["position"] == "SHORT"])
                else:
                    d = stored[ch]; s = d["stats"]; run_id = None; n_skip = len(d["skipped"])
                    s_long, s_short = d.get("stats_long"), d.get("stats_short")
                    rows = [[x[21] if len(x) > 21 else x[0], x[1], x[4], x[5], x[7], x[8], x[9], x[10], x[11], x[12], x[13], int(x[14])] for x in d["trades"]]
                rel = os.path.relpath(folders[ch], HERE).replace(os.sep, "/")
                brief = lambda z: z and {k: z[k] for k in ("trades", "wins", "pts", "net_inr", "pf")}
                meta["periods"][pr["code"]][ch] = dict(file=f"{rel}/summary.json", run_id=run_id, skipped=n_skip, **s,
                                                       long=brief(s_long), short=brief(s_short))
                summary.append(dict(period=pr["code"], code=st["code"], variant=st["variant"], choice=ch, **s))
                all_trades += [[pr["code"], st["code"], ch, *row] for row in rows]
                print(f'{"run   " if fresh else "stored"} {pr["code"]:<3} {st["code"]:<8} {ch:<7} trades {s["trades"]:>3}  '
                      f'skipped {n_skip:>2}  pts {s["pts"]:>+8.1f}  gross {s["gross_inr"]:>+10,.0f}  '
                      f'charges {s["charges_inr"]:>8,.0f}  net {s["net_inr"]:>+10,.0f}  PF {s["pf"]}  t {s["t_stat"]}')
        index.append(meta)
    db.commit()
    page = open(os.path.join(HERE, "dashboard.tpl"), encoding="utf-8").read()
    page = page.replace("/*DATA*/", "const INDEX=" + json.dumps(index, separators=(",", ":")) + ";const PERIODS="
                        + json.dumps(periods, separators=(",", ":")) + ";")
    open(os.path.join(HERE, "dashboard.html"), "w", encoding="utf-8").write(page)
    # versioned text snapshots
    cfg = {t: [dict(r) for r in db.execute(f"select * from {t} order by 1")] for t in ("strategy", "charge_schedule", "test_period")}
    for s in cfg["strategy"]: s.pop("created_at", None)
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(summary, open(os.path.join(HERE, "results", "summary.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    with open(os.path.join(HERE, "results", "trades.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period", "strategy", "strike_choice", "position", "instrument", "entry_time", "entry_px", "exit_time", "exit_px",
                    "exit_reason", "pts", "gross_inr", "charges_inr", "net_inr", "is_open"])
        w.writerows(all_trades)
    print("wrote dashboard.html, web/*.json, config/strategies.json, results/summary.json, results/trades.csv")


if __name__ == "__main__":
    main()
