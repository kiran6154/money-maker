"""Strategy lab: runs every strategy defined in strategies/*.json through engine.py and writes the dashboard.

Source of truth (versioned, one file per concern):
  strategies/strategy_<n>.json   one file per strategy: rules, timeframe, types, option settings, capital, backtests
  config/data.json               input candle files shared by every strategy
  config/charges.json            charge schedules referenced by the strategy types
strategy_lab.db is a rebuildable cache of those files plus the backtest results (web/ holds the dashboard's result files).

Each strategy has three types, one `strategy` row each:
  FUT             futures: long on a future-long signal, short on a future-short signal
  OPT_FUT_SIGNAL  options (via futures): the futures' signals traded in options
  OPT_NATIVE      options (standalone): the engine on each option's own candles
Every type runs long + short once per backtest, timeframe, expiry type and strike; the dashboard's schemes are slices.

`rules.entry_rule` picks what turns Foundation SETUPs into positions: `setup_v1` = every SETUP (engine.py's own trades);
`fz_v1` = the Foundation-Zone gate (fz.py card + gate, fz_exec.py fills, fz_report.py tables) with the thresholds of the
file's `fz` block. An FZ row's memory starts at the first session of the data file, so its Design / Unseen windows are
date slices of one run; OPT_NATIVE is refused for FZ (its thresholds are futures points).

    python lab.py                          run what changed (stored results are reused)
    python lab.py --full                   recompute everything
    python lab.py ST1                      one strategy (a partial run: dashboard.html and results/ are not rebuilt)
    python lab.py backtest ST1 1Y [--tf 15minute] [--label "..."]   add a backtest to strategies/strategy_1.json and run it
"""
import sqlite3, json, csv, calendar, datetime as D, os, sys, math, bisect, hashlib, glob, re, types
import engine, fz, fz_exec, fz_report

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "strategy_lab.db")
WEB = os.path.join(HERE, "web")                              # per-run result files loaded by the dashboard
STRATDIR = os.path.join(HERE, "strategies")
DATACFG = os.path.join(HERE, "config", "data.json")
CHARGECFG = os.path.join(HERE, "config", "charges.json")

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
create table if not exists strategy_backtest(
  id integer primary key, family text not null, label text not null,
  kind text not null check(kind in ('all','preset','named','custom')), preset text,
  date_from text, date_to text, timeframe text, is_default integer not null default 0,
  enabled integer not null default 1, notes text);
create table if not exists choch_signal(
  id integer primary key, run_id integer not null references strategy_run(id),
  strategy_id integer not null references strategy(id), time text, direction text, flipped integer,
  protected_level real, avwap real, anchor_sh_time text, anchor_sh_px real,
  anchor_sl_time text, anchor_sl_px real, setup_time text);
"""

DATA = json.load(open(DATACFG, encoding="utf-8"))
FUT1, FUT5 = DATA["futures"]["minute"], DATA["futures"]["5minute"]
SPOT1, SPOT5 = DATA["spot"]["minute"], DATA["spot"]["5minute"]
# (variant, code suffix, type label, signal source)
TYPES = [("FUT", "", "Futures", "FUTURE"),
         ("OPT_FUT_SIGNAL", "_FB", "Options (via futures)", "FUTURE"),
         ("OPT_NATIVE", "_NB", "Options (standalone)", "OPTION_NATIVE")]
TIMEFRAMES = ("minute", "3minute", "5minute", "15minute", "30minute")
ENTRY_RULES = ("setup_v1", "fz_v1")
FZ_MODULES = ("fz.py", "fz_exec.py", "fz_report.py")
FZ_NATIVE_WHY = "FZ thresholds are futures points; no native-option unit rule in v1"
FZ_TRADE_KEYS = ("gate", "reenter_reason", "zone_id", "fill_used")          # trade fields 25..28 of an FZ row
ENGINE_TRADE_KEYS = ("entry", "exit", "exit_px", "dir", "choch", "sl", "pts", "open", "exit_reason")
# per-SETUP ledger (summary.json['fz'].ledger, results/fz_setups.csv, table fz_setup): fz.py's gate columns, then the
# Foundation outcome of the SETUP (fnd_*) and the FZ position it opened (fz_*), joined here after the gate ran (diagnostic)
LEDGER_COLS = ("time", "dir", "choch_time", "zone_id", "zone_kind", "band_lo", "band_hi", "visit_n", "this_bars", "this_vol",
               "first_bars", "first_vol", "vol_na", "first_vol_na", "read", "left_id", "in_id", "session_bar",
               "level_in_band", "gate", "outcome_gate", "block_reason", "branch", "take_why", "refused", "entered_zone_id",
               "entered_visit_n", "entered_read", "leave_vol_ok", "leave_kind", "watch_kind", "watch_band_id",
               "watch_outcome", "reenter_reason", "fill_used", "fill_time", "fill_delay_bars", "edge_dist_pts",
               "armed_bars", "rearmed_bars", "sl_bar", "fnd_pts", "fnd_exit_reason", "fnd_exit_time", "fnd_net", "fz_kind",
               "fz_entry_time", "fz_pts", "fz_exit_reason", "fz_exit_time", "fz_net")
WATCH_COLS = ("opened_time", "band_id", "dir", "kind", "opened_by_read", "setup_time", "outcome", "outcome_time",
              "armed_time", "last_armed_time")
# chart chunk Z row; read = index in fz.READS; vol_na / first_vol_na: this visit's / the band's first visit's volume is NA
# (the gate's volume ratio is NA when either is, so the crosshair prints NA then too)
Z_COLS = ("time", "zone_id", "visit_n", "this_bars", "this_vol", "first_bars", "first_vol", "read", "left_id", "out_run",
          "vol_na", "gap_pts", "session_bar", "wick_depth", "in_id", "first_vol_na")
ZONE_COLS = ("id", "kind", "lo", "hi", "born")                              # chart chunk ZONES row; born = epoch seconds


# ---------------------------------------------------------------- strategy files
def load_strategies():
    """[(path, spec)] for every strategies/*.json, validated, in file-name order."""
    out, codes = [], set()
    for path in sorted(glob.glob(os.path.join(STRATDIR, "*.json"))):
        spec = json.load(open(path, encoding="utf-8"))
        where = os.path.basename(path)
        for k in ("code", "name", "description", "timeframe", "warmup_days", "rules", "lot_size", "capital", "types",
                  "options", "backtests"):
            if k not in spec: sys.exit(f"{where}: missing '{k}'")
        r = spec["rules"]
        if r.get("break_mode") not in ("touch", "close") or r.get("choch_mode", r["break_mode"]) not in ("touch", "close"):
            sys.exit(f"{where}: break_mode / choch_mode must be 'touch' or 'close'")
        if spec["timeframe"] not in TIMEFRAMES: sys.exit(f"{where}: timeframe must be one of {TIMEFRAMES}")
        if r.get("entry_rule") not in ENTRY_RULES: sys.exit(f"{where}: entry_rule must be one of {ENTRY_RULES}")
        if r["entry_rule"].startswith("fz"):
            # thresholds per timeframe; every key an object with a value and a source (fz.thresholds refuses a missing,
            # unknown, ill-typed or unsourced key: there are no defaults in code)
            blocks = spec.get("fz")
            if not isinstance(blocks, dict) or spec["timeframe"] not in blocks:
                sys.exit(f"{where}: entry_rule {r['entry_rule']} needs an 'fz' block keyed by timeframe, with '{spec['timeframe']}'")
            for tf, block in blocks.items():
                if tf not in TIMEFRAMES: sys.exit(f"{where}: fz block '{tf}' is not a timeframe ({TIMEFRAMES})")
                try: fz.thresholds(block)
                except ValueError as e: sys.exit(f"{where}: fz[{tf}]: {e}")
        elif "fz" in spec:
            sys.exit(f"{where}: an 'fz' block needs entry_rule fz_v1 (it would be stored but never applied)")
        if spec["code"] in codes: sys.exit(f"{where}: duplicate strategy code {spec['code']}")
        if sum(1 for b in spec["backtests"] if b.get("default")) != 1: sys.exit(f"{where}: exactly one backtest needs \"default\": true")
        codes.add(spec["code"])
        out.append((path, spec))
    if not out: sys.exit(f"no strategy files in {STRATDIR}")
    return out


def type_rows(spec):
    """The three `strategy` table rows (one per type) a strategy file describes."""
    r, o, cap = spec["rules"], spec["options"], spec["capital"]
    rows = []
    for var, suffix, label, source in TYPES:
        t = spec["types"][var]
        rows.append(dict(
            code=spec["code"] + suffix, family=spec["code"], variant=var, signal_source=source,
            name=f"{spec['name']} · {label}", description=spec["description"],
            instrument="NIFTY FUT" if var == "FUT" else "NIFTY OPT", timeframe=spec["timeframe"],
            data_file=FUT1, spot_file=SPOT1, date_from="", date_to="", warmup_days=spec["warmup_days"],
            break_mode=r["break_mode"], choch_mode=r.get("choch_mode", r["break_mode"]), avwap_weight=r["avwap_weight"],
            entry_rule=r["entry_rule"], exit_rule=r["exit_rule"], sl_rule=r["sl_rule"],
            lot_size=spec["lot_size"], enabled=1, charge_code=t["charge_code"], slippage_pts=t["slippage_pts"],
            option_source="WEEKLY_LOCAL", weekly_dir=DATA["options"]["weekly_dir"], option_dir=DATA["options"]["kite_dir"],
            option_expiry=DATA["options"]["kite_expiry"], option_prefix=DATA["options"]["kite_prefix"],
            strike_step=o["strike_step"], strike_choices=",".join(o["strike_choices"]), strike_default=o["strike_default"],
            atr_period=o["atr_period"], expiry_types=",".join(o["expiry_types"]), expiry_min_days=o["expiry_min_days"],
            positions="BOTH", capital_fut=cap["futures_margin"], capital_opt_short=cap["short_option_margin"],
            fz_json=json.dumps(spec["fz"], ensure_ascii=False) if "fz" in spec else None))   # verbatim, with provenance
    return rows


def sync(db):
    """Make the database match the files: charge schedules, strategy rows, backtests. Rows from removed files are disabled."""
    for code, c in json.load(open(CHARGECFG, encoding="utf-8")).items():
        if code.startswith("_"): continue
        db.execute("insert or replace into charge_schedule(code,segment,brokerage_pct,brokerage_cap,stt_buy_pct,stt_sell_pct,"
                   "exchange_pct,sebi_pct,stamp_buy_pct,gst_pct,effective_from,notes,brokerage_flat) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (code, c["segment"], c["brokerage_pct"], c["brokerage_cap"], c["stt_buy_pct"], c["stt_sell_pct"], c["exchange_pct"],
                    c["sebi_pct"], c["stamp_buy_pct"], c["gst_pct"], c["effective_from"], c["notes"], c["brokerage_flat"]))
    specs = load_strategies()
    live = set()
    for path, spec in specs:
        for row in type_rows(spec):
            live.add(row["code"])
            cols = list(row)
            db.execute(f"insert into strategy({','.join(cols)}) values({','.join('?' * len(cols))}) "
                       f"on conflict(code) do update set {','.join(f'{c}=excluded.{c}' for c in cols)}", [row[c] for c in cols])
        db.execute("delete from strategy_backtest where family=?", (spec["code"],))
        for b in spec["backtests"]:
            db.execute("insert into strategy_backtest(family,label,kind,preset,date_from,date_to,timeframe,is_default,notes)"
                       " values(?,?,?,?,?,?,?,?,?)", (spec["code"], b["label"], b["kind"], b.get("preset"), b.get("from"),
                                                      b.get("to"), b.get("timeframe"), int(bool(b.get("default"))), b.get("notes")))
    for r in db.execute("select code from strategy where enabled=1").fetchall():
        if r[0] not in live: db.execute("update strategy set enabled=0 where code=?", (r[0],))
    db.commit()
    return specs


def connect():
    db = sqlite3.connect(DB); db.row_factory = sqlite3.Row; db.executescript(SCHEMA)
    migrate(db)
    sync(db)
    return db


def migrate(db):
    """Columns added after the first version of the schema (the database is a cache; this keeps old copies usable)."""
    cols = lambda t: {r[1] for r in db.execute(f"pragma table_info({t})")}
    add = lambda t, c, ddl: c not in cols(t) and db.execute(f"alter table {t} add column {c} {ddl}")
    for c, ddl in (("sl_rule", "text not null default 'none'"), ("charge_code", "text not null default 'ZERODHA_NFO_FUT'"),
                   ("family", "text"), ("variant", "text not null default 'FUT'"), ("spot_file", "text"),
                   ("option_dir", "text"), ("option_expiry", "text"), ("option_prefix", "text"),
                   ("strike_step", "integer default 50"), ("strike_choices", "text"), ("strike_default", "text"),
                   ("atr_period", "integer default 14"), ("slippage_pts", "real not null default 0"),
                   ("option_source", "text not null default 'WEEKLY_LOCAL'"), ("weekly_dir", "text"),
                   ("expiry_min_days", "integer not null default 1"), ("positions", "text not null default 'BOTH'"),
                   ("expiry_types", "text not null default 'WEEKLY,MONTHLY'"), ("signal_source", "text"),
                   ("capital_fut", "real not null default 120000"), ("capital_opt_short", "real not null default 150000"),
                   ("choch_mode", "text"), ("fz_json", "text")):
        add("strategy", c, ddl)
    for c, ddl in (("sl_px", "real"), ("gross_inr", "real"), ("charges_inr", "real"), ("instrument", "text"),
                   ("strike", "real"), ("strike_choice", "text"), ("und_entry_px", "real"), ("und_exit_px", "real"),
                   ("slippage_pts", "real"), ("period", "text"), ("mfe_pts", "real"), ("mae_pts", "real"),
                   ("position", "text"), ("signal", "text"), ("opt_type", "text"), ("expiry", "text"),
                   ("gate", "text"), ("reenter_reason", "text"), ("zone_id", "text"), ("fill_used", "text")):
        add("trade", c, ddl)
    for c, ddl in (("gross_inr", "real"), ("charges_inr", "real"), ("strike_choice", "text"), ("period", "text")):
        add("strategy_run", c, ddl)
    add("charge_schedule", "brokerage_flat", "real not null default 0")
    # one row per Foundation SETUP of an FZ run: the ledger columns (the SETUP's time is setup_time)
    db.execute("create table if not exists fz_setup(id integer primary key, run_id integer not null references strategy_run(id),"
               " strategy_id integer not null references strategy(id), setup_time text)")
    for c in LEDGER_COLS[1:]:
        if c not in cols("fz_setup"): db.execute(f'alter table fz_setup add column "{c}"')
    db.commit()


def slug(label):
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


# ---------------------------------------------------------------- timeframes
TF_MIN = {"minute": 1, "3minute": 3, "5minute": 5, "15minute": 15, "30minute": 30}
TF_LABEL = {"minute": "1m", "3minute": "3m", "5minute": "5m", "15minute": "15m", "30minute": "30m"}
CACHE = os.path.join(HERE, "cache")          # resampled candles (generated, not versioned)


def resample_rows(rows, minutes):
    """1-minute (or 5-minute) candle dicts -> `minutes` candles aligned to 09:15 (volume summed, OI = last)."""
    out, cur, key = [], None, None
    for r in rows:
        dt = r["datetime"]; m = int(dt[11:13]) * 60 + int(dt[14:16]); b = 555 + (m - 555) // minutes * minutes
        k = f"{dt[:11]}{b // 60:02d}:{b % 60:02d}:00"
        o, h, l, c = (float(r[x]) for x in ("open", "high", "low", "close"))
        v = float(r.get("volume") or 0)
        if k != key:
            if cur: out.append(cur)
            key, cur = k, dict(datetime=k, open=o, high=h, low=l, close=c, volume=v, oi=r.get("oi", ""))
        else:
            cur["high"] = max(cur["high"], h); cur["low"] = min(cur["low"], l); cur["close"] = c
            cur["volume"] += v; cur["oi"] = r.get("oi", "")
    if cur: out.append(cur)
    return out


def tf_file(kind, tf):
    """Candle file for futures ('fut') or spot ('spot') at timeframe tf; other timeframes are built from 1-minute data."""
    base1, base5 = (FUT1, FUT5) if kind == "fut" else (SPOT1, SPOT5)
    if tf == "minute": return base1
    if tf == "5minute": return base5
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, f"{kind}_{tf}.csv")
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(base1):
        rows = [r for r in csv.DictReader(open(base1)) if r["datetime"][11:16] <= "15:29"]
        with open(out, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["datetime", "open", "high", "low", "close", "volume", "oi"])
            for r in resample_rows(rows, TF_MIN[tf]):
                w.writerow([r["datetime"], r["open"], r["high"], r["low"], r["close"], r["volume"], r["oi"]])
    return out


_SESS = {}
def sessions():
    """Trading sessions available in the futures data."""
    if not _SESS:
        _SESS["d"] = sorted({r["datetime"][:10] for r in csv.DictReader(open(FUT1))})
    return _SESS["d"]


_FM = {}
def fm_by_day():
    """front_month flag per session from the 1-minute futures file (1 = the contract in the file was the front month that
    day). FZ reads volume as NA (fm_na) on a bar of a session that was not the front month, or on a zero-volume bar."""
    if not _FM:
        for r in csv.DictReader(open(FUT1)): _FM[r["datetime"][:10]] = int(float(r.get("front_month") or 0))
    return _FM


def resolve_backtest(bt, warmup):
    """(date_from, date_to, status, reason). A backtest is refused when the data does not cover it plus its warm-up."""
    ss = sessions(); last = ss[-1]
    if bt["kind"] == "all":
        if len(ss) <= warmup: return None, None, "refused", "not enough data for the warm-up"
        return ss[warmup], last, "ok", None
    if bt["kind"] == "preset":
        p, to = bt["preset"], D.date.fromisoformat(last)
        if p == "YTD":
            frm = D.date(to.year, 1, 1)
        else:
            months = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "5Y": 60}[p]
            y, m = to.year, to.month - months
            while m <= 0: y, m = y - 1, m + 12
            frm = D.date(y, m, min(to.day, 28)) + D.timedelta(days=1)
        frm, to = frm.isoformat(), last
    else:
        frm, to = bt["date_from"], min(bt["date_to"], last)
    before = [d for d in ss if d < frm]
    if len(before) < warmup:
        return frm, to, "refused", f"needs data from before {frm} (plus {warmup} sessions of warm-up); futures data starts {ss[0]}"
    frm = next((d for d in ss if d >= frm), None)
    if not frm or frm > to: return frm, to, "refused", "no sessions in this range"
    return frm, to, "ok", None


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


def fz_chart(bars, F, i0, i1):
    """FZ layers of a futures chart chunk bars[i0..i1]. Z: the as-of zone card per bar (Z_COLS), read from fz.run()'s card,
    never from the final zone list. ZONES: the bands to draw (ZONE_COLS), i.e. every band born by then that holds a close of
    the chunk, every band a Z row names (ref, left, containing), plus the 3 bands nearest the chunk's first close among
    those born by then (a zone_max_age_sessions number hides, from this view only, a band not visited for that many
    sessions; FZ itself never forgets a band)."""
    t, c, card, zs = bars["t"], bars["c"], F["out"]["card"], F["out"]["zones"]
    code = {x: k for k, x in enumerate(fz.READS)}
    iv = lambda x: None if x is None else int(round(x))
    Z = [[ts(t[i]), d["zone_id"], d["visit_n"], d["this_bars"], iv(d["this_vol"]), d["first_bars"], iv(d["first_vol"]),
          code[d["read"]], d["left_id"], d["out_run"], int(bool(d["vol_na"])), d["gap_pts"], d["session_bar"],
          d["wick_depth"], d["in_id"], int(bool(d["first_vol_na"]))] for i in range(i0, i1 + 1) for d in (card[i],)]
    lo, hi = min(c[i0:i1 + 1]), max(c[i0:i1 + 1])
    keep = {}
    for z in zs:
        if z["birth_bar"] > i1 or z["hi"] + fz.EPS < lo or z["lo"] - fz.EPS > hi: continue
        if any(z["lo"] - fz.EPS <= c[i] <= z["hi"] + fz.EPS for i in range(max(i0, z["birth_bar"]), i1 + 1)): keep[z["id"]] = z
    age, sess = F["cfg"]["zone_max_age_sessions"], F["sess"]
    def fresh(z):
        if age is None: return True
        ends = [V["end"] for V in z["visits"] if V["start"] < i0]
        last = z["birth_bar"] if not ends else (i0 if ends[-1] is None or ends[-1] >= i0 else ends[-1])
        return sess[i0] - sess[last] <= age
    near = sorted((z for z in zs if z["birth_bar"] <= i0 and fresh(z)), key=lambda z: abs(z["mid"] - c[i0]))[:3]
    for z in near: keep.setdefault(z["id"], z)
    byid = {z["id"]: z for z in zs}
    for row in Z:                                  # every band a card row names, so the crosshair can print its edges
        for zid in (row[1], row[8], row[14]):
            if zid is not None: keep.setdefault(zid, byid[zid])
    ZONES = [[z["id"], z["kind"], z["lo"], z["hi"], ts(z["born_ts"])] for z in sorted(keep.values(), key=lambda z: z["birth_bar"])]
    return dict(Z=Z, ZONES=ZONES)


def chart(bars, r, i0, i1, marks, F=None):
    """Chart payload for bars[i0..i1] with engine overlays and trade marks on this chart's prices; with an FZ run F, the
    zone card per bar (Z) and the bands to draw (ZONES) too."""
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
    out = dict(C=C, S=S, E=E, PR=PR, PAIR=PAIR, M=marks)
    if F is not None: out.update(fz_chart(bars, F, i0, i1))
    return out


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
        self.base = "minute" if self.tf in ("minute", "3minute") else "5minute"   # source data the timeframe is built from
        sub = "nifty_options" if self.base == "5minute" else "nifty_options_1minute"
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
        files = [os.path.join(base, f"NIFTY_{expiry}_{right}_{'5minute' if self.base == '5minute' else '1minute'}.csv")]
        if self.base != "5minute":
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
            p = os.path.join(self.kite, self.base, f"{self.pre}{int(strike)}{right}.csv")
            rows = list(csv.DictReader(open(p))) if os.path.exists(p) and os.path.getsize(p) > 100 else None
        else:
            rows = self._local_right(expiry, right).get(int(strike))
        if rows:
            if TF_MIN[self.tf] != TF_MIN[self.base]: rows = resample_rows(rows, TF_MIN[self.tf])
            s = Series.from_rows(rows)
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


# ---------------------------------------------------------------- FZ (Foundation-Zone gate)
def fz_rule(st):
    return str(st.get("entry_rule") or "").startswith("fz")


_FZ_HASH = {}
def fz_hash():
    """sha1[:16] over fz.py, fz_exec.py and fz_report.py (line endings normalised): the FZ code a result came from."""
    if not _FZ_HASH:
        h = hashlib.sha1()
        for f in FZ_MODULES: h.update(open(os.path.join(HERE, f), "rb").read().replace(b"\r\n", b"\n"))
        _FZ_HASH["h"] = h.hexdigest()[:16]
    return _FZ_HASH["h"]


def run_fz(st, fut, s0, r):
    """The FZ gate over one futures window: memory from the first bar of `fut` (the data file's first session), ledger
    and positions from s0. fz.py sees candles, fm_na / atr14 and the frozen engine view; fz_exec answers its position
    callback and prices nothing. Returns F = dict(out (fz.run output), trades (engine-shaped FZ positions), raw
    (Foundation's trades), cfg, sess (session number per bar), xt (fz_report.crosstabs of the window), all_na (gate and
    position counts with volume NA on every bar: the like-for-like comparator across volume regimes), memory_start).
    Exits when the gate left Foundation untouched (no WATCH or BLOCK and the same trades): that row would be Foundation
    reported under an FZ code."""
    cfg = fz.thresholds(json.loads(st["fz_json"])[st["timeframe"]])
    touch = st["break_mode"] == "touch"
    fm, t = fm_by_day(), fut["t"]
    bars = dict(fut, fm_na=[fm.get(x[:10], 0) == 0 or vv == 0 for x, vv in zip(t, fut["v"])],
                atr14=atr_series(types.SimpleNamespace(t=t, h=fut["h"], l=fut["l"], c=fut["c"]), st["atr_period"]))
    view = fz_exec.view(r)
    gate = lambda b: fz.run(b, view, cfg, TF_MIN[st["timeframe"]], s0, fz_exec.opener(b, r, st["sl_rule"], touch))
    out = gate(bars)
    trades = fz_exec.build_trades(bars, r, out, st["sl_rule"], touch)
    L = out["ledger"]
    eng = lambda xs: [tuple(x[k] for k in ENGINE_TRADE_KEYS) for x in xs if x["entry"] >= s0]
    if L and not any(x["gate"] in ("WATCH", "BLOCK") for x in L) and eng(trades) == eng(r["trades"]):
        sys.exit(f"{st['code']} {st.get('period')}: FZ row produced Foundation's trades unchanged")
    na = gate(dict(bars, fm_na=[True] * len(t)))
    sess, k = [], -1
    for i, x in enumerate(t):
        k += i == 0 or x[:10] != t[i - 1][:10]; sess.append(k)
    shown = [x for x in trades if x["entry"] >= s0]
    xt = fz_report.crosstabs(L, [w for w in out["watches"] if w["opened_at"] >= s0], shown, out["stats"], out["card"][s0:],
                             sorted({x[:10] for x in t[s0:]}), cfg)
    all_na = dict(gates={g: sum(1 for x in na["ledger"] if x["outcome_gate"] == g) for g in fz_report.GATES},
                  positions={g: sum(1 for d in na["decisions"] if d[0] == g and d[1] >= s0) for g in ("TAKE", "REENTER")})
    return dict(out=out, trades=trades, raw=r["trades"], cfg=cfg, sess=sess, xt=xt, all_na=all_na, memory_start=t[0][:10])


def fz_payload(st, fut, s0, F, legs, raw_legs):
    """summary.json['fz'] for one priced choice. The ledger carries the diagnostic join done here, after fz.run() finished:
    the Foundation outcome of every SETUP (fnd_*) and the FZ position it opened (fz_*), both priced in this choice. Then the
    watch log, the gate cross-tabs, the bridge from Foundation's net to FZ's, the session-matched random control, the
    kept-vs-refused permutation test, both books with the M45 sample flags, the all-NA comparator and the legend of every
    compact array. legs / raw_legs = the priced legs of the FZ positions / of Foundation's trades (tagged _entry,
    _setup, _gate)."""
    out, cfg, t, xt = F["out"], F["cfg"], fut["t"], F["xt"]
    lot = st["lot_size"]
    fzu, rawu = fz_report.units(legs, lot, st["slippage_pts"]), fz_report.units(raw_legs, lot, st["slippage_pts"])
    tag = f"{st['code']}|{st['period']}"
    L = out["ledger"]
    # kept vs refused by what FZ traded: the SETUPs it held a position on (TAKE, or a REENTER on that SETUP even when the
    # fill came on a later bar and the SETUP's own gate read WATCH), not by the gate as of the SETUP bar
    traded = {x.get("setup_i", x["entry"]) for x in F["trades"]}
    kept = [u["net"] for u in rawu if u["entry"] in traded]
    refused = [u["net"] for u in rawu if u["entry"] not in traded]
    T = lambda i: None if i is None else t[i]
    eng, pos = {x["entry"]: x for x in F["raw"]}, {}
    for x in F["trades"]: pos.setdefault(x.get("setup_i", x["entry"]), x)
    rnet, fnet = {u["entry"]: u["net"] for u in rawu}, {u["entry"]: u["net"] for u in fzu}
    r2 = lambda v: round(v, 2) if isinstance(v, float) else v
    rows = []
    for x in L:
        e, p = eng.get(x["i"]), pos.get(x["i"])
        d = dict(x, time=t[x["i"]], choch_time=T(x["choch_i"]), fill_time=T(x["fill_bar"]),
                 fnd_pts=e and e["pts"], fnd_exit_reason=e and e["exit_reason"], fnd_exit_time=e and t[e["exit"]],
                 fnd_net=rnet.get(x["i"]), fz_kind=p and p["gate"], fz_entry_time=p and t[p["entry"]],
                 fz_pts=p and p["pts"], fz_exit_reason=p and p["exit_reason"], fz_exit_time=p and t[p["exit"]],
                 fz_net=p and fnet.get(p["entry"]))
        rows.append([r2(d[c]) for c in LEDGER_COLS])
    W = [[T(w["opened_at"]), w["band_id"], w["dir"], w["kind"], w["opened_by_read"], T(w["setup_i"]), w["outcome"],
          T(w["outcome_bar"]), T(w["armed_at"]), T(w["last_armed_at"])] for w in out["watches"] if w["opened_at"] >= s0]
    books = dict(fz=fz_report.book(fzu, lot), raw=fz_report.book(rawu, lot))
    ctl = fz_report.random_control(rawu, fzu, cfg["control_draws"], cfg["control_seed"], tag)
    perm = fz_report.permutation_p(kept, refused, cfg["control_draws"], cfg["control_seed"], tag)
    flags = fz_report.sample_flags(books["fz"]["n"], books["fz"]["sd"], books["fz"]["weeks"], xt["active_sessions"], lot)
    g, ps = xt["gates"], xt["positions"]
    # take / watch / block / reenter: SETUPs by how they ended (outcome_gate); at_setup: the gate as of the SETUP bar
    headline = dict(setups=xt["setups"], take=g["TAKE"], watch=g["WATCH"], block=g["BLOCK"], reenter=g["REENTER"],
                    at_setup=xt["gates_at_setup"],
                    take_trades=ps["TAKE"], reenter_trades=ps["REENTER"], priced=len(fzu), control_pct=ctl["fz_pct"],
                    control_p_beat=ctl["p_beat"], perm_p=perm["p"], active_sessions=xt["active_sessions"],
                    sessions=xt["sessions"], pf_t=flags["pf_t"])
    legend = dict(Z=Z_COLS, ZONES=ZONE_COLS, read=fz.READS, trade_fields={str(25 + k): f for k, f in enumerate(FZ_TRADE_KEYS)},
                  gates=dict(TAKE="Foundation's own position on this SETUP (same fill, stop and exit)",
                             REENTER="a position from a watch after a confirmed leave of its band: fill at the close of the "
                                     "bar R1-R5 hold, Foundation's stop at that bar, plus the band_reclaim exit",
                             WATCH="no position now; a watch on the band that may REENTER later",
                             BLOCK="no position and no watch (block_reason)"),
                  outcome_gate="the gate a SETUP ended with: REENTER when a REENTER used this SETUP (on its bar or a later "
                               "one), else its gate at the SETUP bar (column gate); the gate tables and headline counts "
                               "use it, headline.at_setup the gate at the SETUP bar",
                  permutation="kept = Foundation's trades on the SETUPs FZ held a position on (TAKE or REENTER), refused = "
                              "Foundation's other trades",
                  hour_bins=list(xt["by_hour"]), units="net / gross / charges in INR per lot; pts in points; "
                                                        "fnd_* / fz_* are diagnostics joined after the gate ran")
    return dict(fz_hash=fz_hash(), memory_start=F["memory_start"], window_start=t[s0][:10], same_sample="file_start",
                thresholds=cfg, headline=headline, stats=xt, counters=out["stats"], bridge=fz_report.bridge(rawu, fzu),
                control=ctl, permutation=perm, books=books, flags=flags, all_na=F["all_na"],
                ledger=dict(cols=LEDGER_COLS, rows=rows), watches=dict(cols=WATCH_COLS, rows=W), legend=legend)


def run_variant(st, cs):
    """Returns {choice: dict(trades, skipped, charts, signals)} for one strategy row.

    Terminology: `position` is LONG/SHORT, `opt_type` the instrument (FUT/CE/PE), `signal` BULLISH/BEARISH.
    Long and short positions exist in futures and in both CE and PE. Futures: long on bullish, short on bearish.
    Options (via futures): bullish -> long CE and short PE, bearish -> long PE and short CE, each a separate 1-lot trade;
    the dashboard's schemes are slices of these (long, short, long + short within CE, long + short within PE).
    Options (standalone): bullish setup on the option's own chart -> long that option, bearish setup -> short it.
    `positions` (BOTH / LONG / SHORT) limits option types to one side.

    entry_rule fz_v1: the positions are FZ's (fz.py gates Foundation's SETUPs; TAKE = Foundation's own trade, REENTER =
    fz_exec.simulate() from the fill bar) instead of every SETUP; each choice also gets `fz` (fz_payload) and each
    futures chart chunk the zone card (Z / ZONES). OPT_NATIVE is refused for FZ (the thresholds are futures points)."""
    if st["entry_rule"] not in ENTRY_RULES: sys.exit(f"{st['code']}: unknown entry_rule {st['entry_rule']!r}")
    fzr = fz_rule(st)
    if fzr and st["variant"] == "OPT_NATIVE":
        return {ch: dict(trades=[], skipped=[dict(why=FZ_NATIVE_WHY)], signals=[], charts=[]) for ch in choice_keys(st)}
    fut, s0 = engine.load(st["data_file"], st["date_from"], st["date_to"], st["warmup_days"])
    p = dict(break_mode=st["break_mode"], choch_mode=st.get("choch_mode") or st["break_mode"],
             avwap_weight=st["avwap_weight"], sl_rule=st["sl_rule"])
    spot = Series.get(st["spot_file"]); atr = atr_series(spot, st["atr_period"])
    step = st["strike_step"]
    chain = OptionChain(st) if st["variant"] != "FUT" else None
    out = {}

    if st["variant"] in ("FUT", "OPT_FUT_SIGNAL"):
        r = engine.run(fut, p)
        F = None
        if fzr:                                   # FZ's positions replace Foundation's; the SETUPs and signals are the engine's
            F = run_fz(st, fut, s0, r)
            r = dict(r, trades=F["trades"])
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
        day_base = {d: chart(fut, r, i0, i1, [], F) for d, (i0, i1) in day_span.items()}
        for ch in choice_keys(st):
            ekind, sc = split_choice(ch) if ch != "-" else (None, None)
            trs, skipped, fmarks, omarks = [], [], [], {}

            def legs_of(x, skipped):
                """The priced positions one futures signal opens under this choice: [(record, label, option series)];
                a leg that cannot be priced goes to `skipped` with the reason."""
                bull = x["dir"] == "up"
                base = dict(dir=x["dir"], signal="BULLISH" if bull else "BEARISH", choch_time=t[x["choch"]],
                            entry_time=t[x["entry"]], exit_time=t[x["exit"]], exit_reason=x["exit_reason"], open=x["open"],
                            sl=x["sl"], und_entry=fut["c"][x["entry"]], und_exit=x["exit_px"], expiry=None)
                if fzr: base.update({k: x.get(k) for k in FZ_TRADE_KEYS})
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
                if fzr:                               # which position a leg belongs to, for fz_report.units()
                    for rec, _, _ in legs: rec.update(_entry=x["entry"], _setup=x.get("setup_i", x["entry"]),
                                                      _gate=x.get("gate") or "RAW")
                return legs

            for x in sig:
                legs = legs_of(x, skipped)
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
            if F is not None:                         # Foundation's own trades priced the same way, for the bridge
                raw = [leg[0] for x in F["raw"] if x["entry"] >= s0 for leg in legs_of(x, [])]
                out[ch]["fz"] = fz_payload(st, fut, s0, F, trs, raw)
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
    params = {k: st[k] for k in ("variant", "break_mode", "choch_mode", "avwap_weight", "entry_rule", "exit_rule", "sl_rule",
                                 "charge_code", "slippage_pts", "timeframe")}
    params.update(strike_choice=ch, period=st["period"], date_from=st["date_from"], date_to=st["date_to"])
    if fz_rule(st): params.update(fz_json=st["fz_json"], fz_hash=fz_hash(), warmup_days=st["warmup_days"])
    run_id = db.execute("insert into strategy_run(strategy_id,run_at,params_json,bars,trades,wins,net_pts,gross_inr,charges_inr,"
                        "net_inr,max_dd_pts,strike_choice,period) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (st["id"], D.datetime.now().isoformat(timespec="seconds"), json.dumps(params), None, s["trades"], s["wins"],
                         s["pts"], s["gross_inr"], s["charges_inr"], s["net_inr"], s["max_dd_inr"], ch, st["period"])).lastrowid
    for j, x in enumerate(res["trades"], 1):
        db.execute("insert into trade(run_id,strategy_id,seq,side,choch_time,entry_time,entry_px,exit_time,exit_px,exit_reason,sl_px,"
                   "pts,gross_inr,charges_inr,inr,is_open,instrument,strike,strike_choice,und_entry_px,und_exit_px,slippage_pts,period,"
                   "mfe_pts,mae_pts,position,signal,opt_type,expiry,gate,reenter_reason,zone_id,fill_used)"
                   " values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, st["id"], j, x["position"], x["choch_time"], x["entry_time"], x["entry_px"], x["exit_time"], x["exit_px"],
                    x["exit_reason"], x["sl"], round(x["pts"], 2), round(x["gross"], 2), round(x["chg"]["total"], 2),
                    round(x["net"], 2), int(x["open"]), x["instrument"], x["strike"], ch, x["und_entry"], x["und_exit"],
                    st["slippage_pts"], st["period"], x["mfe"], x["mae"], x["position"], x["signal"], x["opt_type"], x["expiry"],
                    *(x.get(k) for k in FZ_TRADE_KEYS)))
    if res.get("fz"):                                  # the SETUP ledger of an FZ run
        L = res["fz"]["ledger"]
        cols = ",".join(f'"{c}"' for c in L["cols"][1:])
        db.executemany(f"insert into fz_setup(run_id,strategy_id,setup_time,{cols}) values({','.join('?' * (len(L['cols']) + 2))})",
                       [(run_id, st["id"], *row) for row in L["rows"]])
    for g in res["signals"]:
        db.execute("insert into choch_signal(run_id,strategy_id,time,direction,flipped,protected_level,avwap,anchor_sh_time,"
                   "anchor_sh_px,anchor_sl_time,anchor_sl_px,setup_time) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, st["id"], g["time"], g["dir"], int(g["flipped"]), g["lvl"], round(g["av"], 2),
                    *(g["hi"] or (None, None)), *(g["lo"] or (None, None)), g["setup"]))
    return run_id, s


def write_result(folder, st, ch, res, s, cs, key):
    """Result folder: summary.json (KPIs, trades, signals, chart index) + one c<k>.json per chart chunk (a session / contract).
    The dashboard reads the summary first and fetches chart chunks only when they are shown.
    FZ rows: each trade gains gate, reenter_reason, zone_id, fill_used (indices 25-28), summary.json gains 'fz'
    (fz_payload: ledger, cross-tabs, bridge, control, legend ...) and fz_hash next to key."""
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder): os.remove(os.path.join(folder, f))
    extra = (lambda x: [x.get(k) for k in FZ_TRADE_KEYS]) if fz_rule(st) else (lambda x: [])
    trades = [[x["opt_type"], x["instrument"], x["strike"], x["choch_time"], x["entry_time"], x["entry_px"], x["sl"], x["exit_time"],
               x["exit_px"], x["exit_reason"], round(x["pts"], 2), round(x["gross"], 2), round(x["chg"]["total"], 2),
               round(x["net"], 2), x["open"], {k: round(v, 2) for k, v in x["chg"].items()}, x.get("und_entry"), x.get("und_exit"),
               bool(x.get("stale")), x["mfe"], x["mae"], x["position"], x["opt_type"], x["signal"], x["expiry"], *extra(x)]
              for x in res["trades"]]
    charts = []
    for k, c in enumerate(res["charts"]):
        fn = f"c{k}.json"
        json.dump({kk: v for kk, v in c.items() if kk not in ("label", "day", "kind")}, open(os.path.join(folder, fn), "w"), separators=(",", ":"))
        charts.append(dict(label=c["label"], day=c.get("day"), kind=c.get("kind", "signal"), file=fn, marks=[m[0] for m in c["M"]]))
    body = dict(code=st["code"], choice=ch, period=st["period"], key=key, stats=s, charges=cs, trades=trades,
                stats_long=stats([x for x in res["trades"] if x["position"] == "LONG"]),
                stats_short=stats([x for x in res["trades"] if x["position"] == "SHORT"]),
                stats_ce=stats([x for x in res["trades"] if x["opt_type"] == "CE"]),
                stats_pe=stats([x for x in res["trades"] if x["opt_type"] == "PE"]),
                skipped=res["skipped"], signals=res["signals"], charts=charts)
    if res.get("fz"): body.update(fz_hash=res["fz"]["fz_hash"], fz=res["fz"])
    json.dump(body, open(os.path.join(folder, "summary.json"), "w", encoding="utf-8"), separators=(",", ":"))


def cache_key(st, pr):
    """Everything a result depends on: the strategy row (an FZ row's fz_json included), the period, the code (the three FZ
    modules only for FZ rows, so an fz.py edit re-runs FZ rows and nothing else), and the input data files."""
    h = hashlib.sha1()
    row = {k: v for k, v in st.items() if k not in ("id", "created_at", "enabled", "name", "description")}
    h.update(json.dumps([row, pr["date_from"], pr["date_to"]], sort_keys=True, default=str).encode())
    code = ("engine.py", "lab.py") + (FZ_MODULES if fz_rule(st) else ())
    for f in code:
        h.update(open(os.path.join(HERE, f), "rb").read().replace(b"\r\n", b"\n"))   # line endings differ across checkouts
    files = [st["data_file"], st["spot_file"], os.path.join(st["option_dir"] or "", "manifest.csv")]
    if fz_rule(st): files.append(FUT1)                  # front_month per session comes from the 1-minute file
    if st["variant"] != "FUT" and st.get("weekly_dir"):
        files += sorted(glob.glob(os.path.join(st["weekly_dir"], "nifty_options*", "*", "*", "manifest.json")))
        # the option candle files themselves, so a refreshed data set is picked up even if a manifest did not change
        files += sorted(glob.glob(os.path.join(st["weekly_dir"], "nifty_options*", "*", "*", "NIFTY_*_[CP]E_*.csv")))
    for f in files:
        if f and os.path.exists(f): h.update(f"{f}:{os.path.getsize(f)}:{int(os.path.getmtime(f))}".encode())
    return h.hexdigest()[:16]


def add_backtest(argv):
    """python lab.py backtest <CODE> <1M|3M|6M|YTD|1Y|5Y|all|FROM> [TO] [--tf 15minute] [--label "..."]
    Appends the backtest to that strategy's file in strategies/ (the source of truth) and returns the code to run."""
    args, opts, i = [], {}, 0
    while i < len(argv):
        if argv[i].startswith("--"): opts[argv[i][2:]] = argv[i + 1]; i += 2
        else: args.append(argv[i]); i += 1
    code, what = args[0], args[1]
    path = next((p for p, sp in load_strategies() if sp["code"] == code), None)
    if not path: sys.exit(f"no strategy file with code {code}")
    if opts.get("tf") and opts["tf"] not in TIMEFRAMES: sys.exit(f"--tf must be one of {', '.join(TIMEFRAMES)}")
    if what in ("1M", "3M", "6M", "YTD", "1Y", "5Y"): b = dict(label=opts.get("label", what), kind="preset", preset=what)
    elif what == "all": b = dict(label=opts.get("label", "All data"), kind="all")
    else: b = dict(label=opts.get("label", f"{what} to {args[2]}"), kind="custom", **{"from": what, "to": args[2]})
    if opts.get("tf"): b["timeframe"] = opts["tf"]
    spec = json.load(open(path, encoding="utf-8"))
    spec["backtests"].append(b)
    json.dump(spec, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"added to {os.path.basename(path)}:", b)
    return [code]


def fz_flat(fzp):
    """(table, row, col, value) rows of an FZ payload's tables for results/fz_ledger.csv: a path of two keys is
    (table, row), a longer one (table.subtable, row, col...); lists are JSON text."""
    out = []
    def walk(path, v):
        if isinstance(v, dict):
            for k, x in v.items(): walk(path + [str(k)], x)
        elif isinstance(v, list) and v and all(isinstance(x, dict) and "key" in x for x in v):
            for x in v: walk(path + [x["key"]], {k: y for k, y in x.items() if k != "key"})
        else:
            v = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, tuple)) else v
            out.append((path[0], path[1] if len(path) > 1 else "", "", v) if len(path) < 3 else
                       (f"{path[0]}.{path[1]}", path[2], ".".join(path[3:]), v))
    for sec in ("headline", "stats", "bridge", "control", "permutation", "books", "flags", "all_na"):
        walk([sec], fzp.get(sec))
    return out


def main():
    full = "--full" in sys.argv                     # recompute everything, ignoring stored results
    argv = [a for a in sys.argv[1:] if a != "--full"]
    if argv[:1] == ["backtest"]:
        add_backtest(argv[1:]); only = []           # then a complete run (stored results are reused), so the page is whole
    else:
        only = [a for a in argv if not a.startswith("--")]
    db = connect()
    sts = [dict(x) for x in db.execute("select * from strategy where enabled=1 order by family, id")]
    bts = [dict(x) for x in db.execute("select * from strategy_backtest where enabled=1 order by family, is_default desc, id")]
    os.makedirs(WEB, exist_ok=True)
    index, summary, all_trades, group_runs, fz_setups, fz_tabs = [], [], [], {}, [], []
    ss = sessions()
    for st in sts:
        if only and st["code"] not in only and st["family"] not in only: continue
        fzr = fz_rule(st)
        blocks = json.loads(st["fz_json"]) if fzr else {}
        cs = dict(db.execute("select * from charge_schedule where code=?", (st["charge_code"],)).fetchone())
        meta = {k: st[k] for k in ("code", "family", "variant", "positions", "signal_source", "name", "description",
                                   "instrument", "timeframe", "warmup_days",
                                   "break_mode", "avwap_weight", "entry_rule", "exit_rule", "sl_rule", "lot_size",
                                   "charge_code", "slippage_pts", "strike_choices", "strike_default", "atr_period",
                                   "expiry_types", "capital_fut", "capital_opt_short", "fz_json")}
        meta.update(strategy_name=st["name"].split(" · ")[0], strategy_description=st["description"],
                    choch_mode=st.get("choch_mode") or st["break_mode"])
        if fzr: meta["fz_hash"] = fz_hash()
        meta["runs"] = {}
        for bt in [b for b in bts if b["family"] == st["family"]]:
            tf = bt["timeframe"] or st["timeframe"]
            rk = f"{slug(bt['label'])}_{TF_LABEL[tf]}"
            frm, to, status, reason = resolve_backtest(bt, st["warmup_days"])
            if status == "ok" and fzr:
                if tf not in blocks: status, reason = "refused", f"no FZ thresholds for {tf}"
                elif st["variant"] == "OPT_NATIVE": status, reason = "refused", FZ_NATIVE_WHY
            info = dict(id=bt["id"], label=bt["label"], kind=bt["kind"], preset=bt["preset"], notes=bt["notes"],
                        date_from=frm, date_to=to, timeframe=tf, design=tf == st["timeframe"], is_default=bt["is_default"],
                        status=status, reason=reason, choices={})
            meta["runs"][rk] = info
            if status != "ok":
                print(f"refused {rk:<12} {st['code']:<8} {bt['label']}: {reason}"); continue
            # engine warm-up: the strategy's own for Foundation rows (each window re-warms from its own start); for FZ rows
            # every session before the window, so the band memory starts at the file's first session and the Design /
            # Unseen runs are date slices of the All-data run (resolve_backtest still refuses on the file's warm-up)
            warm = ss.index(frm) if fzr else st["warmup_days"]
            info.update(memory_start=ss[max(0, ss.index(frm) - warm)], same_sample="file_start" if fzr else "own_warmup")
            stp = dict(st, timeframe=tf, data_file=tf_file("fut", tf), spot_file=tf_file("spot", tf),
                       date_from=frm, date_to=to, period=rk, warmup_days=warm)
            pr = dict(date_from=frm, date_to=to)
            key = cache_key(stp, pr)
            choices = choice_keys(stp)
            folders = {ch: os.path.join(WEB, st["code"], rk, ch) for ch in choices}
            stored = {}
            if not full:
                for ch, fo in folders.items():
                    f = os.path.join(fo, "summary.json")
                    if os.path.exists(f):
                        d = json.load(open(f, encoding="utf-8"))
                        if d.get("key") == key: stored[ch] = d
            fresh = len(stored) < len(choices)
            if fresh:
                gk = (st["family"], st["variant"], st["entry_rule"], rk)
                if gk not in group_runs:
                    group_runs[gk] = run_variant(dict(stp, positions="BOTH"), cs)
                res = {ch: side_of(rr, st["positions"]) for ch, rr in group_runs[gk].items()}
            for ch in choices:
                if fresh:
                    rr = res[ch]
                    run_id, s = save_run(db, stp, ch, rr, cs)
                    write_result(folders[ch], stp, ch, rr, s, cs, key)
                    rows = [[x["position"], x["instrument"], x["entry_time"], x["entry_px"], x["exit_time"], x["exit_px"], x["exit_reason"],
                             round(x["pts"], 2), round(x["gross"], 2), round(x["chg"]["total"], 2), round(x["net"], 2), int(x["open"])]
                            for x in rr["trades"]]
                    n_skip = len(rr["skipped"])
                    part = lambda f: stats([x for x in rr["trades"] if f(x)])
                    s_long, s_short = part(lambda x: x["position"] == "LONG"), part(lambda x: x["position"] == "SHORT")
                    s_ce, s_pe = part(lambda x: x["opt_type"] == "CE"), part(lambda x: x["opt_type"] == "PE")
                    fzp = rr.get("fz")
                else:
                    d = stored[ch]; s = d["stats"]; run_id = None; n_skip = len(d["skipped"])
                    s_long, s_short, s_ce, s_pe = (d.get(k) for k in ("stats_long", "stats_short", "stats_ce", "stats_pe"))
                    rows = [[x[21] if len(x) > 21 else x[0], x[1], x[4], x[5], x[7], x[8], x[9], x[10], x[11], x[12], x[13], int(x[14])] for x in d["trades"]]
                    fzp = d.get("fz")
                hl = fzp["headline"] if fzr and fzp else None
                rel = os.path.relpath(folders[ch], HERE).replace(os.sep, "/")
                brief = lambda z: z and {k: z[k] for k in ("trades", "wins", "pts", "net_inr", "pf")}
                info["choices"][ch] = dict(file=f"{rel}/summary.json", run_id=run_id, skipped=n_skip, **s,
                                           long=brief(s_long), short=brief(s_short), ce=brief(s_ce), pe=brief(s_pe),
                                           **({"fz": hl} if hl else {}))
                srow = dict(run=rk, backtest=bt["label"], timeframe=tf, code=st["code"], variant=st["variant"], choice=ch, **s)
                if hl:
                    # fz_take .. fz_reenter: SETUPs by how they ended; fz_reenter_at_setup: gated REENTER on their own bar;
                    # fz_*_trades: positions; fz_priced: the positions priced in this choice (the control's denominator)
                    srow.update(fz_take=hl["take"], fz_watch=hl["watch"], fz_block=hl["block"], fz_reenter=hl["reenter"],
                                fz_reenter_at_setup=hl["at_setup"]["REENTER"],
                                fz_take_trades=hl["take_trades"], fz_reenter_trades=hl["reenter_trades"],
                                fz_priced=hl["priced"], control_pct=hl["control_pct"], perm_p=hl["perm_p"],
                                active_sessions=hl["active_sessions"], fz_sessions=hl["sessions"], fz_hash=fzp["fz_hash"])
                    if st["variant"] == "FUT" or ch == f"W-{st['strike_default']}":   # futures + the default option choice
                        fz_setups += [[rk, st["code"], ch, *x] for x in fzp["ledger"]["rows"]]
                        fz_tabs += [[rk, st["code"], ch, *x] for x in fz_flat(fzp)]
                summary.append(srow)
                all_trades += [[rk, st["code"], ch, *row] for row in rows]
                print(f'{"run   " if fresh else "stored"} {rk:<12} {st["code"]:<8} {ch:<7} trades {s["trades"]:>3}  '
                      f'skipped {n_skip:>3}  net {s["net_inr"]:>+10,.0f}  PF {s["pf"]}  t {s["t_stat"]}'
                      + (f'  FZ take {hl["take"]} watch {hl["watch"]} block {hl["block"]} reenter {hl["reenter"]}'
                         f' (positions {hl["take_trades"]} + {hl["reenter_trades"]})  control pct {hl["control_pct"]}'
                         if hl else ""))
        index.append(meta)
    db.commit()
    if only:                                           # never publish a dashboard or results/ that lack the other strategies
        print(f"partial run ({' '.join(only)}): dashboard and results not rebuilt")
        return
    page = open(os.path.join(HERE, "dashboard.tpl"), encoding="utf-8").read()
    page = page.replace("/*DATA*/", "const INDEX=" + json.dumps(index, separators=(",", ":")) + ";const TFS="
                        + json.dumps(TF_LABEL) + ";const DATA_RANGE=" + json.dumps([sessions()[0], sessions()[-1]]) + ";")
    open(os.path.join(HERE, "dashboard.html"), "w", encoding="utf-8").write(page)
    # versioned result snapshots (the strategy definitions themselves live in strategies/*.json)
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(summary, open(os.path.join(HERE, "results", "summary.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    with open(os.path.join(HERE, "results", "trades.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "strategy", "choice", "position", "instrument", "entry_time", "entry_px", "exit_time", "exit_px",
                    "exit_reason", "pts", "gross_inr", "charges_inr", "net_inr", "is_open"])
        w.writerows(all_trades)
    # FZ: one row per Foundation SETUP (the gate ledger) and the cross-tabs / bridge / control, per FZ code and run
    with open(os.path.join(HERE, "results", "fz_setups.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["run", "strategy", "choice", *LEDGER_COLS]); w.writerows(fz_setups)
    with open(os.path.join(HERE, "results", "fz_ledger.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["run", "strategy", "choice", "table", "row", "col", "value"]); w.writerows(fz_tabs)
    print("wrote dashboard.html, web/*, results/summary.json, results/trades.csv, results/fz_setups.csv, results/fz_ledger.csv")


if __name__ == "__main__":
    main()
