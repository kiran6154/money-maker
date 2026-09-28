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

A strategy file's optional `position` block sets how each signal is held (defaults: POSITION_DEFAULT): `lots` per position,
`lock` ("strike": one open position per traded instrument - strike + expiry + right, or the futures contract - so a new
entry on a locked instrument is skipped until the open one exits; "none"), and `scale_out` tranches that exit part of
the lots at a fixed target in traded-instrument points while the rest ride the strategy's exit.

Signal source (`underlying`, strategy file; a backtest may override it): "FUT" runs the engine on the near-month futures
candles, "INDEX" on the NIFTY index candles with an equal-weighted AVWAP (the index has no volume). Either way the Futures
type trades the near-month futures contract (priced on its own candles at the signal's times; a stop crossed on the index
fills at the futures price of that candle shifted by the stop's distance), and a position still open at its contract's
last candle is closed there (`expiry`) - the next month's contract is never used early.

Options (standalone) rescan (`options.native_scan`): every `every_minutes` the strikes of each scan choice are picked for
CE and PE from the index; the first SETUP on any picked contract opens the position; with `one_per_side` no other contract
of that side is entered until it has closed. Results are keyed W-SCAN / M-SCAN.

Every full run also appends to results/history/<CODE>.json: one version per change of the strategy's definition or of
the code its results come from, with the headline numbers per backtest and choice, so a modified strategy is always read
against its previous version (the dashboard shows the difference; the run prints it).
"""
import sqlite3, json, csv, calendar, datetime as D, os, sys, math, bisect, hashlib, glob, re, types, ast
import engine, fz, fz_exec, fz_report

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "strategy_lab.db")
WEB = os.path.join(HERE, "web")                              # per-run result files loaded by the dashboard
STRATDIR = os.path.join(HERE, "strategies")
DATACFG = os.path.join(HERE, "config", "data.json")
CHARGECFG = os.path.join(HERE, "config", "charges.json")
HISTORY = os.path.join(HERE, "results", "history")           # per-strategy result versions (versioned)

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
ENTRY_RULES = ("setup_v1", "fz_v1", "fz_v2")
POSITION_DEFAULT = {"lots": 1, "lock": "strike", "scale_out": [], "exit": "strategy", "stop": None, "trail": None,
                    "square_off": None, "reverse": None}
REVERSE_TRIGGERS = ("initial_stop",)
POSITION_EXITS = ("strategy", "position")
UNDERLYINGS = ("FUT", "INDEX")
NATIVE_SCAN_DEFAULT = {"choices": ["ATR2", "ATM", "ITM1", "OTM1"], "every_minutes": 5, "one_per_side": True}
INDEX_WHY_FZ = "FZ runs on futures candles (its thresholds are futures points)"
INDEX_WHY_NATIVE = "standalone options run on each option's own candles; the signal source does not apply"
POSITION_LOCKS = ("strike", "none")
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
    num = lambda f: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", os.path.basename(f))]   # strategy_10 after _9
    for path in sorted(glob.glob(os.path.join(STRATDIR, "*.json")), key=num):
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
            sys.exit(f"{where}: an 'fz' block needs an fz entry_rule (fz_v1 / fz_v2; it would be stored but never applied)")
        try: position_of(spec)
        except ValueError as e: sys.exit(f"{where}: position: {e}")
        try: native_scan_of(spec)
        except ValueError as e: sys.exit(f"{where}: options.native_scan: {e}")
        if spec.get("underlying", "FUT") not in UNDERLYINGS: sys.exit(f"{where}: underlying must be one of {UNDERLYINGS}")
        for b in spec["backtests"]:
            if b.get("underlying", "FUT") not in UNDERLYINGS: sys.exit(f"{where}: backtest {b['label']!r}: underlying must be one of {UNDERLYINGS}")
            if "square_off" in b:                     # holding override: null = positional, "HH:MM" = intraday
                try: position_of({"position": {"square_off": b["square_off"]}})
                except ValueError as e: sys.exit(f"{where}: backtest {b['label']!r}: {e}")
        if spec["code"] in codes: sys.exit(f"{where}: duplicate strategy code {spec['code']}")
        if sum(1 for b in spec["backtests"] if b.get("default")) != 1: sys.exit(f"{where}: exactly one backtest needs \"default\": true")
        codes.add(spec["code"])
        out.append((path, spec))
    if not out: sys.exit(f"no strategy files in {STRATDIR}")
    return out


def position_of(spec):
    """The file's `position` block over POSITION_DEFAULT, validated:
    {lots, lock, scale_out: [{lots, target_pts | target_r}], exit, stop: {futures_pts, option_pct}, trail: {start_r, lag_r}}."""
    p = dict(POSITION_DEFAULT, **(spec.get("position") or {}))
    unknown = set(p) - set(POSITION_DEFAULT)
    if unknown: raise ValueError(f"unknown key(s) {sorted(unknown)}")
    if not isinstance(p["lots"], int) or p["lots"] < 1: raise ValueError("lots must be a whole number >= 1")
    if p["lock"] not in POSITION_LOCKS: raise ValueError(f"lock must be one of {POSITION_LOCKS}")
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    if p["exit"] not in POSITION_EXITS: raise ValueError(f"exit must be one of {POSITION_EXITS}")
    if p["stop"] is not None and (set(p["stop"]) != {"futures_pts", "option_pct"} or not all(map(num, p["stop"].values()))):
        raise ValueError('stop is {"futures_pts": pts > 0, "option_pct": % of the entry premium > 0}')
    if p["trail"] is not None and (set(p["trail"]) != {"start_r", "lag_r"} or not all(map(num, p["trail"].values()))):
        raise ValueError('trail is {"start_r": R > 0, "lag_r": R > 0}')
    if p["exit"] == "position" and p["stop"] is None: raise ValueError('exit "position" needs a stop (lots would never close)')
    if p["reverse"] is not None:
        rv = p["reverse"]
        if not isinstance(rv, dict) or set(rv) != {"trigger", "max"} or rv["trigger"] not in REVERSE_TRIGGERS \
                or not isinstance(rv["max"], int) or rv["max"] < 1:
            raise ValueError(f'reverse is {{"trigger": one of {REVERSE_TRIGGERS}, "max": reversals per signal >= 1}}, or null')
        if p["exit"] != "position": raise ValueError('reverse needs exit "position" (it reverses at the managed stop)')
    if p["square_off"] is not None and not (isinstance(p["square_off"], str) and re.fullmatch(r"\d\d:\d\d", p["square_off"])
                                            and "09:15" < p["square_off"] <= "15:30"):
        raise ValueError('square_off is "HH:MM" after 09:15 and up to 15:30 (every position closed by then), or null')
    if (p["trail"] or any("target_r" in so for so in p["scale_out"])) and p["stop"] is None:
        raise ValueError("target_r / trail are multiples of the stop distance (R): they need a stop")
    for so in p["scale_out"]:
        if set(so) not in ({"lots", "target_pts"}, {"lots", "target_r"}):
            raise ValueError('each scale_out entry is {"lots": n, "target_pts": pts} or {"lots": n, "target_r": R}')
        if not isinstance(so["lots"], int) or so["lots"] < 1: raise ValueError("scale_out lots must be a whole number >= 1")
        if not num(so.get("target_pts", so.get("target_r"))): raise ValueError("a target must be > 0")
    if sum(so["lots"] for so in p["scale_out"]) > p["lots"]: raise ValueError("scale_out lots add up to more than lots")
    return p


def native_scan_of(spec):
    """options.native_scan over NATIVE_SCAN_DEFAULT, validated: {choices, every_minutes, one_per_side}."""
    n = dict(NATIVE_SCAN_DEFAULT, **(spec["options"].get("native_scan") or {}))
    if set(n) != set(NATIVE_SCAN_DEFAULT): raise ValueError(f"keys are {sorted(NATIVE_SCAN_DEFAULT)}")
    if not n["choices"] or not all(re.fullmatch(r"ATM|ATR\d+(\.\d+)?|(ITM|OTM)\d+", c) for c in n["choices"]):
        raise ValueError("choices are strike choices such as ATR2, ATM, ITM1, OTM1")
    if n["every_minutes"] not in (1, 3, 5, 15, 30): raise ValueError("every_minutes is one of 1, 3, 5, 15, 30")
    if not isinstance(n["one_per_side"], bool): raise ValueError("one_per_side is true or false")
    return n


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
            fz_json=json.dumps(spec["fz"], ensure_ascii=False) if "fz" in spec else None,   # verbatim, with provenance
            position_json=json.dumps(position_of(spec), sort_keys=True),
            underlying=spec.get("underlying", "FUT"), native_scan_json=json.dumps(native_scan_of(spec), sort_keys=True)))
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
            db.execute("insert into strategy_backtest(family,label,kind,preset,date_from,date_to,timeframe,is_default,notes,"
                       "underlying,square_off) values(?,?,?,?,?,?,?,?,?,?,?)",
                       (spec["code"], b["label"], b["kind"], b.get("preset"), b.get("from"), b.get("to"), b.get("timeframe"),
                        int(bool(b.get("default"))), b.get("notes"), b.get("underlying"),
                        ("none" if b["square_off"] is None else b["square_off"]) if "square_off" in b else None))
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
                   ("choch_mode", "text"), ("fz_json", "text"), ("position_json", "text"), ("underlying", "text"),
                   ("native_scan_json", "text")):
        add("strategy", c, ddl)
    for c, ddl in (("sl_px", "real"), ("gross_inr", "real"), ("charges_inr", "real"), ("instrument", "text"),
                   ("strike", "real"), ("strike_choice", "text"), ("und_entry_px", "real"), ("und_exit_px", "real"),
                   ("slippage_pts", "real"), ("period", "text"), ("mfe_pts", "real"), ("mae_pts", "real"),
                   ("position", "text"), ("signal", "text"), ("opt_type", "text"), ("expiry", "text"),
                   ("gate", "text"), ("reenter_reason", "text"), ("zone_id", "text"), ("fill_used", "text"),
                   ("lots", "integer"), ("tranche", "text")):
        add("trade", c, ddl)
    for c, ddl in (("gross_inr", "real"), ("charges_inr", "real"), ("strike_choice", "text"), ("period", "text")):
        add("strategy_run", c, ddl)
    add("charge_schedule", "brokerage_flat", "real not null default 0")
    add("strategy_backtest", "underlying", "text")
    add("strategy_backtest", "square_off", "text")      # NULL: the strategy's own; 'none': positional; 'HH:MM': intraday
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
        elif p == "MTD":                               # this month: from the 1st of the latest data month
            frm = D.date(to.year, to.month, 1)
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
    sessions; FZ itself never forgets a band). Rooms (FZ v2): a room retired at or before the chunk's first bar is not
    drawn, unless a Z row names it (then it is sent so the crosshair can print its edges)."""
    t, c, card, zs = bars["t"], bars["c"], F["out"]["card"], F["out"]["zones"]
    byid = {z["id"]: z for z in zs}
    zs = [z for z in zs if z.get("retired_bar") is None or z["retired_bar"] > i0]
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


def prev_session_start(tl, i0):
    """Index of the first candle of the session before the one starting at i0 (i0 itself when there is none): option charts
    open one session early so the day before the trade is visible."""
    if i0 <= 0: return max(i0, 0)
    d = tl[i0 - 1][:10]
    return bisect.bisect_left(tl, f"{d} 00:00:00")


def option_chart(s, i0, i1, marks):
    """Chart payload for an option contract's own candles (no engine overlays: the signals came from elsewhere)."""
    C = [[ts(s.t[i]), s.o[i], s.h[i], s.l[i], s.c[i], None, None, int(s.v[i])] for i in range(i0, i1 + 1)]
    return dict(C=C, S=[], E=[], PR=[], PAIR=[], M=marks)


_KNOWN = {}
def known_sessions():
    """Every session in the candle files (futures 1-minute and the long index 5-minute files under the data root)."""
    if not _KNOWN:
        days = set(sessions())
        root = os.path.dirname(os.path.normpath(DATA["options"]["weekly_dir"]))
        for f in glob.glob(os.path.join(root, "nifty50_5minute_*.csv")):
            if " - Copy" not in f: days |= {r["datetime"][:10] for r in csv.DictReader(open(f))}
        _KNOWN["d"] = days
    return _KNOWN["d"]


def monthly_expiry(ym):
    """NIFTY monthly expiry of month 'YYYY-MM': the last Thursday up to August 2025, the last Tuesday from September 2025
    (NSE), moved to the session before when that day is a holiday (only where the candle files know the sessions)."""
    y, m = int(ym[:4]), int(ym[5:7])
    d = (D.date(y + (m == 12), m % 12 + 1, 1) - D.timedelta(days=1))
    wd = 3 if (y, m) < (2025, 9) else 1
    while d.weekday() != wd: d -= D.timedelta(days=1)
    days = known_sessions()
    if days and d.isoformat() <= max(days):
        while d.isoformat() not in days and d.month == m: d -= D.timedelta(days=1)
    return d.isoformat()


_COV = {}
def option_coverage(st):
    """First session from which every session's contracts (each expiry type of the row, nearest expiry >= expiry_min_days)
    have full-chain option data - an expiry whose manifest.json carries `full_chain` (tools/breeze_options.py) or the Kite
    chain expiry - through the end of the data. Before it, only the local files' five strikes around each expiry's
    settlement exist (a hindsight window), so option types are not run there."""
    base = "minute" if st["timeframe"] in ("minute", "3minute") else "5minute"
    key = (base, st.get("expiry_types"), st.get("expiry_min_days"))
    if key not in _COV:
        chain = OptionChain(dict(st, timeframe=base))
        sub = "nifty_options" if base == "5minute" else "nifty_options_1minute"
        full = {}
        def ok(e):
            if e is None: return False
            if e == st["option_expiry"]: return True
            if e not in full:
                f = os.path.join(st["weekly_dir"], sub, e[:4], e, "manifest.json")
                full[e] = os.path.exists(f) and "full_chain" in json.load(open(f, encoding="utf-8"))
            return full[e]
        kinds = [k.strip() for k in (st.get("expiry_types") or "WEEKLY").split(",")]
        ss, start = sessions(), None
        for d in ss:
            good = all(ok(chain.expiry_for(d, st["expiry_min_days"], k)) for k in kinds)
            if good and start is None: start = d
            if not good: start = None
        _COV[key] = start
    return _COV[key]


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
            cal = sorted({monthly_expiry(e[:7]) for e in cal})    # the exchange's monthly date, not the month's last weekly
        return next((e for e in cal if (D.date.fromisoformat(e) - d).days >= min_days), None)

    def _local_right(self, expiry, right):
        key = (expiry, right)
        if key in self._rights: return self._rights[key]
        base = os.path.join(self.root, expiry[:4], expiry)
        by = {}
        files = [os.path.join(base, f"NIFTY_{expiry}_{right}_{'5minute' if self.base == '5minute' else '1minute'}.csv")]
        # per-strike chunk files: the combined file's sources, plus strikes filled in later (tools/breeze_options.py)
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
    if st["variant"] == "OPT_NATIVE" and not fz_rule(st):       # the rescan book (options.native_scan), per expiry type
        return [f"{e.strip()[0]}-SCAN" for e in (st.get("expiry_types") or "WEEKLY").split(",")]
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
    """Slippage, gross, charges, net for a trade record with entry_px / exit_px in traded-instrument units, for its `lots`
    (a scale-out tranche is charged as its own round trip)."""
    lot, slip = st["lot_size"] * rec.setdefault("lots", 1), st["slippage_pts"]
    if rec["position"] == "SHORT":                             # short: sell entry, buy exit
        sell, buy = rec["entry_px"] - slip, rec["exit_px"] + slip
    else:                                                      # long future or long option
        buy, sell = rec["entry_px"] + slip, rec["exit_px"] - slip
    pts = sell - buy
    rec.update(pts=pts, gross=pts * lot, chg=trade_charges(cs, buy, sell, lot))
    rec["net"] = rec["gross"] - rec["chg"]["total"]
    return rec


def position_cfg(st):
    return json.loads(st["position_json"]) if st.get("position_json") else dict(POSITION_DEFAULT)


class StrikeLock:
    """lock "strike": one open position per traded instrument (strike + expiry + right, or the futures contract). A new
    entry while that instrument's position is open is skipped; an exit and a new entry on the same candle count as
    exit first, so the new position is taken."""

    def __init__(self, st):
        self.on, self.until = position_cfg(st)["lock"] == "strike", {}

    def held(self, inst, entry_time):
        """The open position's exit time if `inst` is locked at `entry_time`, else None."""
        u = self.until.get(inst)
        return u if self.on and u is not None and entry_time < u else None

    def hold(self, inst, exit_time):
        self.until[inst] = max(exit_time, self.until.get(inst, ""))


def tranches(st, rec, tl, ol, hl, ll, cl):
    """One position as its lots (position_cfg): each scale_out tranche exits at entry +/- target_pts (traded-instrument
    points) on the first candle after the entry candle that reaches it - at the candle open when it opens beyond the
    target, else at the target; on a session's first candle only if its close is still at the target (no fill on the
    opening print). A target
    reached only on the candle where the stop is hit counts as not reached (the stop is assumed first). A tranche whose
    target is never reached, and the remaining lots, keep the strategy's exit. Default config: the position unchanged."""
    P = position_cfg(st)
    if not P["scale_out"]: return [dict(rec, lots=P["lots"], tranche="")]
    long, e = rec["position"] == "LONG", rec["entry_px"]
    i0 = bisect.bisect_right(tl, rec["entry_time"]); i1 = bisect.bisect_right(tl, rec["exit_time"]) - 1
    out, left = [], P["lots"]
    for n, so in enumerate(P["scale_out"], 1):
        tgt, hit = (e + so["target_pts"] if long else e - so["target_pts"]), None
        for k in range(i0, i1 + 1):
            if k == i1 and rec["exit_reason"] == "stop_loss": break
            gap = ol[k] >= tgt if long else ol[k] <= tgt
            first = k > 0 and tl[k][:10] != tl[k - 1][:10]
            if first:                                  # no fill on the opening print: the close must still be at the target
                if cl[k] >= tgt if long else cl[k] <= tgt: hit = (k, cl[k]); break
            elif gap or (hl[k] >= tgt if long else ll[k] <= tgt):
                hit = (k, ol[k] if gap else tgt); break
        t = dict(rec, lots=so["lots"], tranche=f"T{n} +{so['target_pts']:g}")
        if hit: t.update(exit_time=tl[hit[0]], exit_px=hit[1], exit_reason=f"target {so['target_pts']:g}", open=False)
        out.append(t); left -= so["lots"]
    if left: out.append(dict(rec, lots=left, tranche="rest"))
    return out


_FC = {}
def fut_contracts():
    """({time: (contract, expiry)}, {contract: its last candle time}) from the 1-minute futures file's `contract` /
    `expiry` columns (near-month files from tools/breeze_history.py carry both; a file without `expiry` is not cut)."""
    if FUT1 not in _FC:
        by, last = {}, {}
        for r in csv.DictReader(open(FUT1)):
            c, e = r.get("contract") or "NIFTY FUT", r.get("expiry") or None
            by[r["datetime"]] = (c, e); last[c] = r["datetime"]
        _FC[FUT1] = (by, last)
    return _FC[FUT1]


def native_scan_cfg(st):
    return json.loads(st["native_scan_json"]) if st.get("native_scan_json") else dict(NATIVE_SCAN_DEFAULT)


def square_off_at(st, entry_time):
    """The session-end cut for a position entered at entry_time ("YYYY-MM-DD HH:MM:00"), or None (position.square_off)."""
    T = position_cfg(st).get("square_off")
    return f"{entry_time[:10]} {T}:00" if T else None


def reversal_of(st, parts, depth):
    """position.reverse: when the managed lots of a position leave at its initial stop (exit_reason 'stop_loss', not a
    trail stop), (time, price) at which the opposite position opens - a full new position, managed the same way - else
    None. Not after the square-off time, and at most `max` reversals per signal (depth counts the ones already made)."""
    rv = position_cfg(st).get("reverse")
    if not rv or depth >= rv["max"]: return None
    hit = [p_ for p_ in parts if p_["exit_reason"] == "stop_loss"]
    if not hit: return None
    t0, px = hit[0]["exit_time"], hit[0]["exit_px"]
    sq = square_off_at(st, t0)
    if sq and t0 >= sq: return None
    return t0, px


def flip(rec, t0, px, depth):
    """The opposite position of rec, opened at t0 / px: same instrument, other side."""
    up = rec["position"] != "LONG"
    return dict(rec, position="LONG" if up else "SHORT", dir="up" if up else "down", signal="BULLISH" if up else "BEARISH",
                entry_time=t0, entry_px=px, exit_time=t0, exit_px=None, exit_reason="open", open=True, reversal=depth + 1)


def rev_tag(tr):
    """Tranche label of a reversed position's lots ('REV T1 1R', 'REV2 rest (trail)' ...)."""
    d = tr.get("reversal") or 0
    if d: tr["tranche"] = f"REV{d if d > 1 else ''} {tr['tranche']}".strip()
    return tr


def eod_cut(st, rec, tl, cl):
    """Intraday: a position still open after its entry day's square_off time is closed at the close of the last candle
    that opens at or before it (reason 'eod'). Returns False for an entry at or after that time (not taken)."""
    e = square_off_at(st, rec["entry_time"])
    if not e: return True
    if rec["entry_time"] >= e: return False
    if rec["exit_time"] > e:
        j = bisect.bisect_right(tl, e) - 1
        if j >= 0 and tl[j][:10] == e[:10] and tl[j] >= rec["entry_time"]:
            rec.update(exit_time=tl[j], exit_px=cl[j], exit_reason="eod", open=False)
    return True


def position_mode(st):
    return position_cfg(st)["exit"] == "position"


def manage(st, rec, tl, ol, hl, ll, cl, cap, expiry=None):
    """exit "position": the position is managed from the entry fill on its own candles and the strategy's exit (the next
    CHoCH, rules.sl_rule) is not used. R = stop.futures_pts for futures, stop.option_pct % of the entry premium for options;
    the stop starts 1R against the entry for every lot. Candle by candle after the entry candle, up to `cap` (the backtest's
    last candle, or the contract's last candle before it):
      1. stop - all open lots exit at the stop (at the candle open if it opens beyond it; on a session's first candle at its
         close: no fill on the opening print). The stop is checked before targets on the same candle.
      2. targets - each scale_out lot exits at entry +/- target_r x R (or target_pts): at the candle open if it opens beyond
         the target, else at the target; on a session's first candle only if its close is still at or beyond the target,
         at that close.
      3. trail - from the best price so far: once start_r full R are reached, the stop moves to (reached R - lag_r) x R and
         steps up by whole R after that (never back). A move made on this candle applies from the next candle.
    Lots still open at `cap` close at its candle: reason 'expiry' at the contract's end, else 'open' (valued, marked *).
    Returns one record per lot group (tranche), like tranches()."""
    P = position_cfg(st)
    long, e, kind = rec["position"] == "LONG", rec["entry_px"], rec["kind"]
    sg = 1 if long else -1
    R = P["stop"]["futures_pts"] if kind == "FUT" else e * P["stop"]["option_pct"] / 100
    stop = e - sg * R
    tag = lambda so: f"{so['target_r']:g}R" if "target_r" in so else f"+{so['target_pts']:g}"
    lots = [dict(lots=so["lots"], tranche=f"T{n} {tag(so)}", tgt=e + sg * (so["target_r"] * R if "target_r" in so else so["target_pts"]),
                 why=f"target {tag(so)}") for n, so in enumerate(P["scale_out"], 1)]
    left = P["lots"] - sum(so["lots"] for so in P["scale_out"])
    if left: lots.append(dict(lots=left, tranche="rest" + (" (trail)" if P["trail"] else ""), tgt=None))
    eod = square_off_at(st, rec["entry_time"])
    if eod: cap = min(cap, eod)                       # intraday: the session-end cut is the last candle
    i0 = bisect.bisect_right(tl, rec["entry_time"]); iend = bisect.bisect_right(tl, cap) - 1
    best, trailing, out = e, False, []
    base = dict(rec, sl=round(stop, 2))

    def close(lot, k, px, why):
        out.append(dict(base, lots=lot["lots"], tranche=lot["tranche"], exit_time=tl[k], exit_px=round(px, 2),
                        exit_reason=why, open=False))

    for k in range(i0, iend + 1):
        first = k > 0 and tl[k][:10] != tl[k - 1][:10]
        gap = ol[k] <= stop if long else ol[k] >= stop
        if gap or (ll[k] <= stop if long else hl[k] >= stop):
            px = cl[k] if first else (ol[k] if gap else stop)
            for lot in lots: close(lot, k, px, "trail_stop" if trailing else "stop_loss")
            lots = []; break
        for lot in [x for x in lots if x["tgt"] is not None]:
            g = ol[k] >= lot["tgt"] if long else ol[k] <= lot["tgt"]
            if first:                                  # no fill on the opening print: the close must still be at the target
                if cl[k] >= lot["tgt"] if long else cl[k] <= lot["tgt"]:
                    close(lot, k, cl[k], lot["why"]); lots.remove(lot)
            elif g or (hl[k] >= lot["tgt"] if long else ll[k] <= lot["tgt"]):
                close(lot, k, ol[k] if g else lot["tgt"], lot["why"]); lots.remove(lot)
        if not lots: break
        if P["trail"]:
            best = max(best, hl[k]) if long else min(best, ll[k])
            reached = math.floor(sg * (best - e) / R + 1e-9)
            if reached >= P["trail"]["start_r"]:
                new = e + sg * (reached - P["trail"]["lag_r"]) * R
                if (new > stop) if long else (new < stop): stop, trailing = new, True
    if lots:
        k = max(iend, i0 - 1)
        ended = expiry is not None and k >= 0 and (tl[k][:10] >= expiry or k == len(tl) - 1)
        at_eod = bool(eod) and k >= 0 and tl[k][:10] == eod[:10] and (k == len(tl) - 1 or tl[k + 1] > eod)
        for lot in lots:
            out.append(dict(base, lots=lot["lots"], tranche=lot["tranche"], exit_time=tl[k], exit_px=cl[k],
                            exit_reason="expiry" if ended else "eod" if at_eod else "open", open=not (ended or at_eod)))
    return out


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
    fzr, pmode = fz_rule(st), position_mode(st)
    if fzr and st["variant"] == "OPT_NATIVE":
        return {ch: dict(trades=[], skipped=[dict(why=FZ_NATIVE_WHY)], signals=[], charts=[]) for ch in choice_keys(st)}
    index_sig = st.get("underlying") == "INDEX"
    # `fut` = the candles the engine reads (the signal source): near-month futures, or the index
    fut, s0 = engine.load(st.get("signal_file") or st["data_file"], st["date_from"], st["date_to"], st["warmup_days"])
    p = dict(break_mode=st["break_mode"], choch_mode=st.get("choch_mode") or st["break_mode"],
             avwap_weight="equal" if index_sig else st["avwap_weight"], sl_rule=st["sl_rule"])   # the index has no volume
    FS = Series.get(st["data_file"]) if index_sig else None       # the traded futures, when the signals come from the index
    contracts, clast = fut_contracts()
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
                    te = t[x["entry"]]
                    c_, e_ = contracts.get(te, ("NIFTY FUT", None))
                    if index_sig:                     # priced on the near-month futures at the index signal's times
                        fe, _ = FS.at(te); fxc, _ = FS.at(t[x["exit"]])
                        if fe is None or fxc is None:
                            skipped.append(dict(base, position="LONG" if bull else "SHORT", opt_type="FUT",
                                                why=f"no futures candle at {te if fe is None else t[x['exit']]}")); return []
                        # a stop crossed on the index fills at the futures price of that candle shifted by the stop's distance
                        fx = x["exit_px"] + (fxc - fut["c"][x["exit"]]) if x["exit_reason"] == "stop_loss" else fxc
                        PT = (FS.t, FS.o, FS.h, FS.l, FS.c)
                    else:
                        fe, fx = fut["c"][x["entry"]], x["exit_px"]
                        PT = (t, fut["o"], fut["h"], fut["l"], fut["c"])
                    rec = dict(base, kind="FUT", position="LONG" if bull else "SHORT", opt_type="FUT",
                               instrument=c_, expiry=e_, strike=None, entry_px=fe, exit_px=fx)
                    cap = t[-1]
                    if e_:                            # near month: the contract's last candle ends the position
                        cap = min(cap, clast[c_])
                        if not pmode and rec["exit_time"] > clast[c_]:
                            j = bisect.bisect_right(PT[0], clast[c_]) - 1
                            rec.update(exit_time=PT[0][j], exit_px=PT[4][j], exit_reason="expiry", open=False)
                    if not pmode and not eod_cut(st, rec, PT[0], PT[4]) or pmode and square_off_at(st, te) and te >= square_off_at(st, te):
                        skipped.append(dict(base, position=rec["position"], opt_type="FUT", instrument=c_,
                                            why=f"entry at or after the square-off time ({position_cfg(st)['square_off']})")); return []
                    parts = (manage(st, rec, *PT, cap, e_) if pmode else tranches(st, rec, *PT))
                    if pmode:                         # stop and reverse (position.reverse), on the same contract
                        cur_rec, cur, depth = rec, parts, 0
                        while (rv := reversal_of(st, cur, depth)):
                            cur_rec = flip(cur_rec, rv[0], rv[1], depth); depth += 1
                            cur = [rev_tag(p_) for p_ in manage(st, cur_rec, *PT, cap, e_)]; parts = parts + cur
                    legs = [(price_trade(st, cs, excursion(PT[0], PT[2], PT[3], tr, tr["position"] == "LONG")),
                             tr["position"] + (f" · {tr['tranche']}" if tr["tranche"] else ""), None) for tr in parts]
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
                        sq = square_off_at(st, rec["entry_time"])
                        if sq and rec["entry_time"] >= sq:
                            skipped.append(dict(base, position=pos, opt_type=right, instrument=nm,
                                                why=f"entry at or after the square-off time ({position_cfg(st)['square_off']})")); continue
                        if pmode:                             # managed on the option's own candles up to the backtest end
                            end_ = f"{st['date_to']} 23:59:59"
                            cur = manage(st, rec, os_.t, os_.o, os_.h, os_.l, os_.c, end_, exp)
                            for tr in cur:
                                excursion(os_.t, os_.h, os_.l, tr, pos == "LONG")
                                legs.append((price_trade(st, cs, tr), f"{pos} {right}" + (f" · {tr['tranche']}" if tr["tranche"] else ""), os_))
                            # stop and reverse: the opposite signal's leg (long CE -> long PE, short PE -> short CE), strike from
                            # the index at the stop, entered at that option's close of the stop candle
                            depth, r_right = 0, right
                            while (rv := reversal_of(st, cur, depth)):
                                t0 = rv[0]; r_right = "PE" if r_right == "CE" else "CE"
                                si2 = spot.ix.get(t0)
                                if si2 is None:
                                    skipped.append(dict(base, position=pos, opt_type=r_right, entry_time=t0, why="reverse: no spot candle")); break
                                k2 = pick_strike(sc, r_right, spot.c[si2], atr[si2], step)
                                exp2 = chain.expiry_for(t0[:10], st["expiry_min_days"], ekind)
                                os2 = chain.get(exp2, k2, r_right) if exp2 else None
                                nm2 = chain.name(exp2, k2, r_right) if exp2 else f"{int(k2)} {r_right}"
                                en2 = os2.at(t0)[0] if os2 is not None else None
                                if en2 is None:
                                    skipped.append(dict(base, position=pos, opt_type=r_right, entry_time=t0, why=f"reverse: no data for {nm2}")); break
                                rdir = "down" if (cur[0]["dir"] if cur else rec["dir"]) == "up" else "up"
                                rec2 = dict(rec, dir=rdir, signal="BULLISH" if rdir == "up" else "BEARISH", opt_type=r_right,
                                            instrument=nm2, strike=k2, expiry=exp2, entry_time=t0, entry_px=en2, exit_time=t0, exit_px=None,
                                            exit_reason="open", open=True, reversal=depth + 1)
                                depth += 1
                                cur = [rev_tag(p_) for p_ in manage(st, rec2, os2.t, os2.o, os2.h, os2.l, os2.c, end_, exp2)]
                                for tr in cur:
                                    excursion(os2.t, os2.h, os2.l, tr, pos == "LONG")
                                    legs.append((price_trade(st, cs, tr), f"{pos} {r_right}" + (f" · {tr['tranche']}" if tr["tranche"] else ""), os2))
                            continue
                        if sq and rec["exit_time"] > sq:     # intraday: the session-end cut, before the contract's own end
                            j = bisect.bisect_right(os_.t, sq) - 1
                            if j >= 0 and os_.t[j][:10] == sq[:10] and os_.t[j] >= rec["entry_time"]:
                                rec.update(exit_time=os_.t[j], exit_px=os_.c[j], exit_reason="eod", open=False)
                        expire(rec, os_, exp)
                        if rec["exit_px"] is None:
                            ex, st2 = os_.at(rec["exit_time"])
                            if ex is None:
                                skipped.append(dict(base, position=pos, opt_type=right, why=f"{nm} has no candle at exit")); continue
                            rec.update(exit_px=ex, stale=st1 or st2)
                        for tr in tranches(st, rec, os_.t, os_.o, os_.h, os_.l, os_.c):
                            excursion(os_.t, os_.h, os_.l, tr, pos == "LONG")
                            legs.append((price_trade(st, cs, tr), f"{pos} {right}" + (f" · {tr['tranche']}" if tr["tranche"] else ""), os_))
                if fzr:                               # which position a leg belongs to, for fz_report.units()
                    for rec, _, _ in legs: rec.update(_entry=x["entry"], _setup=x.get("setup_i", x["entry"]),
                                                      _gate=x.get("gate") or "RAW")
                return legs

            lock = StrikeLock(st)
            for x in sig:
                legs = legs_of(x, skipped)
                for inst in dict.fromkeys(rec["instrument"] for rec, _, _ in legs):     # the strike lock, per instrument
                    mine = [lg for lg in legs if lg[0]["instrument"] == inst]
                    u = lock.held(inst, mine[0][0]["entry_time"])
                    if u:
                        r0 = mine[0][0]
                        skipped.append(dict({k: r0.get(k) for k in ("dir", "signal", "choch_time", "entry_time", "position",
                                                                     "opt_type", "instrument", "expiry")},
                                            why=f"strike locked: {inst} open until {u}"))
                        legs = [lg for lg in legs if lg[0]["instrument"] != inst]
                    else:
                        lock.hold(inst, max(lg[0]["exit_time"] for lg in mine))
                for rec, lbl, os_ in legs:
                    trs.append(rec)
                    fm = mark(x, fut, lbl); fm[5] = round(rec["pts"], 2); fm.append(rec.get("dir") or x["dir"])
                    if rec.get("reversal"):
                        j0 = max(bisect.bisect_right(t, rec["entry_time"]) - 1, 0)
                        fm[0], fm[1] = ts(t[j0]), (rec["entry_px"] if rec["kind"] == "FUT" and not index_sig else fut["c"][j0])
                        fm[4] = "up" if (rec["position"] == "LONG") == (rec["kind"] == "FUT" or rec["opt_type"] == "CE") else "down"
                    if rec["exit_reason"] in ("expiry", "eod"):
                        j = max(bisect.bisect_right(t, rec["exit_time"]) - 1, 0)
                        fm[2], fm[3], fm[6], fm[8] = ts(t[j]), (rec["exit_px"] if rec["kind"] == "FUT" and not index_sig
                                                                else fut["c"][j]), False, rec["exit_reason"]
                    if pmode:                                  # the lot's own exit, drawn at the futures price of that candle
                        j = max(bisect.bisect_right(t, rec["exit_time"]) - 1, 0)
                        fm[2], fm[3], fm[6], fm[7], fm[8] = ts(t[j]), (rec["exit_px"] if rec["kind"] == "FUT" and not index_sig
                                                                       else fut["c"][j]), \
                            rec["open"], rec["sl"], rec["exit_reason"]
                    fmarks.append(fm)
                    if os_ is not None:                        # the traded option's own chart
                        omarks.setdefault((rec["instrument"], rec["entry_time"][:10]), (os_, []))[1].append(
                            [ts(rec["entry_time"]), rec["entry_px"], ts(rec["exit_time"]), rec["exit_px"],
                             "up" if rec["position"] == "LONG" else "down", round(rec["pts"], 2), rec["open"], None,
                             rec["exit_reason"], lbl, rec.get("dir") or x["dir"]])
            charts = []
            for d, (i0, i1) in day_span.items():      # one futures chart chunk per session, loaded lazily by the dashboard
                lo, hi = ts(t[i0]), ts(t[i1])
                mk = [m for m in fmarks if m[0] <= hi and m[2] >= lo]
                n = sum(1 for m in fmarks if lo <= m[0] <= hi)
                pnl = sum(m[5] for m in fmarks if lo <= m[0] <= hi)
                charts.append(dict(day_base[d], M=mk, day=d, kind="signal",
                                   label=f"{d} · futures" + (f" · {n} trades · {pnl:+.1f} pts" if n else "")))
            for (nm, d), (os_, mk) in sorted(omarks.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                i0 = prev_session_start(os_.t, bisect.bisect_left(os_.t, f"{d} 00:00:00"))   # from the session before
                i1 = max(bisect.bisect_right(os_.t, f"{d} 23:59:59") - 1,
                         max(bisect.bisect_right(os_.t, D.datetime.utcfromtimestamp(m[2]).strftime("%Y-%m-%d %H:%M:%S")) - 1 for m in mk))
                charts.append(dict(option_chart(os_, i0, i1, mk), day=d, kind="option",
                                   label=f"{d} · {nm} · {len(mk)} trade{'s' * (len(mk) > 1)} · {sum(m[5] for m in mk):+.1f} pts"))
            out[ch] = dict(trades=trs, skipped=skipped, signals=signals, charts=charts)
            if F is not None:                         # Foundation's own trades priced the same way, for the bridge
                raw = [leg[0] for x in F["raw"] if x["entry"] >= s0 for leg in legs_of(x, [])]
                out[ch]["fz"] = fz_payload(st, fut, s0, F, trs, raw)
        return out

    # OPT_NATIVE: the engine runs on each option's own candles (strategy timeframe). Every NS["every_minutes"] the strike
    # of each scan choice is picked for CE and PE from the index candle of that length that has just completed (ATR(n) on
    # the same candles), and that contract is watched until the next scan. A SETUP on a watched contract whose entry candle
    # closes inside the watch opens a position: bullish -> long that option, bearish -> short (per `positions`); the first
    # one wins (ties: scan-list order). With one_per_side no other contract of that side (CE / PE) is entered until the
    # position has closed; otherwise the lock is per strike. Exits: the engine's own (next CHoCH / stop) or the managed
    # position; a contract's data ends at its expiry.
    NS = native_scan_cfg(st)
    scan_tf = {1: "minute", 3: "3minute", 5: "5minute", 15: "15minute", 30: "30minute"}[NS["every_minutes"]]
    sp = Series.get(tf_file("spot", scan_tf)); satr = atr_series(sp, st["atr_period"])
    tfm, days = TF_MIN[st["timeframe"]], {x[:10] for x in fut["t"][s0:]}
    plus = lambda tt, m: (D.datetime.strptime(tt, "%Y-%m-%d %H:%M:%S") + D.timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S")
    scans = [(plus(sp.t[j], NS["every_minutes"]), j) for j in range(len(sp.t)) if sp.t[j][:10] in days]
    want = {"BOTH": ("up", "down"), "LONG": ("up",), "SHORT": ("down",)}[st["positions"]]
    runs = {}
    spot_tf, spot_days = Series.get(st["spot_file"]), {}                # the index on the strategy's candles, per session
    for i, x in enumerate(spot_tf.t):
        if x[:10] in days: spot_days.setdefault(x[:10], [i, i])[1] = i

    def contract_run(exp, k, right, nm):
        """(bars, engine result, entry-candle close times, trades sorted by them) for one contract, or None (no data)."""
        key = (exp, int(k), right)
        if key not in runs:
            os_ = chain.get(exp, k, right) if exp else None
            runs[key] = None
            if os_ is not None:
                try:
                    ob, _ = engine.window(dict(t=os_.t, o=os_.o, h=os_.h, l=os_.l, c=os_.c, v=os_.v),
                                          st["date_from"], st["date_to"], st["warmup_days"], nm)
                    r = engine.run(ob, p)
                    ends = sorted(((plus(ob["t"][x["entry"]], tfm), x) for x in r["trades"]), key=lambda z: (z[0], z[1]["entry"]))
                    runs[key] = (ob, r, [z[0] for z in ends], [z[1] for z in ends])
                except ValueError:
                    pass
        return runs[key]

    for ch in choice_keys(st):
        ekind, _ = split_choice(ch)
        trs, skipped, charts, marks_by = [], [], [], {}
        for right in ("CE", "PE"):
            events, missing = [], set()
            for n, (T, j) in enumerate(scans):
                T2 = scans[n + 1][0] if n + 1 < len(scans) and scans[n + 1][0][:10] == T[:10] else f"{T[:10]} 23:59:59"
                exp = chain.expiry_for(T[:10], st["expiry_min_days"], ekind)
                for rank, c in enumerate(NS["choices"]):
                    k = pick_strike(c, right, sp.c[j], satr[j], step)
                    nm = chain.name(exp, k, right) if exp else f"{int(k)} {right}"
                    cr = contract_run(exp, k, right, nm)
                    if cr is None:
                        if (T[:10], nm) not in missing:
                            missing.add((T[:10], nm))
                            skipped.append(dict(signal="", opt_type=right, instrument=nm, expiry=exp, entry_time=T[:10],
                                                why=f"no data for {nm} (scan {c})"))
                        continue
                    _, _, ends, xs = cr
                    for q in range(bisect.bisect_left(ends, T), bisect.bisect_left(ends, T2)):
                        if xs[q]["dir"] in want: events.append((ends[q], rank, c, exp, int(k), nm, xs[q]))
            events.sort(key=lambda z: (z[0], z[1]))
            side_free, lock, seen = "", StrikeLock(st), set()
            for when, rank, c, exp, k, nm, x in events:
                if (nm, x["entry"]) in seen: continue      # the same SETUP seen through two scan choices
                seen.add((nm, x["entry"]))
                ob, r, _, _ = runs[(exp, k, right)]; t_ = ob["t"]
                lng = x["dir"] == "up"
                rec = dict(dir=x["dir"], signal="BULLISH" if lng else "BEARISH", position="LONG" if lng else "SHORT",
                           opt_type=right, kind="OPT", instrument=nm, strike=k, expiry=exp, scan=c,
                           choch_time=t_[x["choch"]], entry_time=t_[x["entry"]], exit_time=t_[x["exit"]],
                           exit_reason=x["exit_reason"], open=x["open"], sl=x["sl"], entry_px=ob["c"][x["entry"]],
                           exit_px=x["exit_px"], und_entry=None, und_exit=None)
                held = (side_free if NS["one_per_side"] and rec["entry_time"] < side_free else None) or lock.held(nm, rec["entry_time"])
                if held:
                    skipped.append(dict(signal=rec["signal"], position=rec["position"], opt_type=right, instrument=nm,
                                        expiry=exp, entry_time=rec["entry_time"],
                                        why=f"strike locked: {right} side open until {held} ({nm}, scan {c})"))
                    continue
                if x["open"] and t_[x["exit"]][:10] == exp:
                    rec.update(exit_reason="expiry", open=False)     # the contract's data ends at its expiry
                sq = square_off_at(st, rec["entry_time"])
                if sq and rec["entry_time"] >= sq: continue          # no entry at or after the square-off time
                if not pmode: eod_cut(st, rec, t_, ob["c"])
                parts = (manage(st, rec, t_, ob["o"], ob["h"], ob["l"], ob["c"], t_[-1], exp) if pmode
                         else tranches(st, rec, t_, ob["o"], ob["h"], ob["l"], ob["c"]))
                if pmode:                                  # stop and reverse on the same option
                    cur_rec, cur, depth = rec, parts, 0
                    while (rv := reversal_of(st, cur, depth)):
                        cur_rec = flip(cur_rec, rv[0], rv[1], depth); depth += 1
                        cur = [rev_tag(p_) for p_ in manage(st, cur_rec, t_, ob["o"], ob["h"], ob["l"], ob["c"], t_[-1], exp)]
                        parts = parts + cur
                end = max(p_["exit_time"] for p_ in parts)
                side_free = max(side_free, end); lock.hold(nm, end)
                for tr in parts:
                    excursion(t_, ob["h"], ob["l"], tr, tr["position"] == "LONG")
                    trs.append(price_trade(st, cs, tr))
                    jx = bisect.bisect_right(t_, tr["exit_time"]) - 1
                    m = mark(x, ob, f"{tr['position']} {right}" + (f" · {tr['tranche']}" if tr["tranche"] else ""))
                    m[2], m[3], m[5], m[6], m[7], m[8] = ts(t_[jx]), tr["exit_px"], round(tr["pts"], 2), tr["open"], tr["sl"], tr["exit_reason"]
                    if tr.get("reversal"):                 # drawn from its own entry, in its own direction
                        j0 = max(bisect.bisect_right(t_, tr["entry_time"]) - 1, 0)
                        m[0], m[1], m[4] = ts(t_[j0]), tr["entry_px"], "up" if tr["position"] == "LONG" else "down"
                    m.append(tr.get("dir") or x["dir"])
                    marks_by.setdefault((nm, rec["entry_time"][:10], exp, k, right), []).append((m, jx))
        for (nm, d, exp, k, right), ms in sorted(marks_by.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            ob, r, _, _ = runs[(exp, k, right)]; t_ = ob["t"]
            idx = [i for i, x in enumerate(t_) if x[:10] == d]
            i1 = max([idx[-1]] + [jx for _, jx in ms])
            n_ = len({m[0] for m, _ in ms})
            charts.append(dict(label=f"{d} · {nm} · {n_} trade{'s' * (n_ > 1)} · {sum(m[5] for m, _ in ms):+.1f} pts",
                               day=d, kind="option", **chart(ob, r, prev_session_start(t_, idx[0]), i1, [m for m, _ in ms])))
        # the index, one chart per session, drawn above the option charts (the strikes are picked from it)
        for d, (i0, i1) in sorted(spot_days.items()):
            charts.append(dict(label=f"{d} · index", day=d, kind="signal", **option_chart(spot_tf, i0, i1, [])))
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
                   "mfe_pts,mae_pts,position,signal,opt_type,expiry,gate,reenter_reason,zone_id,fill_used,lots,tranche)"
                   " values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, st["id"], j, x["position"], x["choch_time"], x["entry_time"], x["entry_px"], x["exit_time"], x["exit_px"],
                    x["exit_reason"], x["sl"], round(x["pts"], 2), round(x["gross"], 2), round(x["chg"]["total"], 2),
                    round(x["net"], 2), int(x["open"]), x["instrument"], x["strike"], ch, x["und_entry"], x["und_exit"],
                    st["slippage_pts"], st["period"], x["mfe"], x["mae"], x["position"], x["signal"], x["opt_type"], x["expiry"],
                    *(x.get(k) for k in FZ_TRADE_KEYS), x.get("lots", 1), x.get("tranche", "")))
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
    FZ rows: each trade's gate, reenter_reason, zone_id, fill_used (indices 25-28; None on other rows), summary.json gains
    'fz' (fz_payload: ledger, cross-tabs, bridge, control, legend ...) and fz_hash next to key.
    Every row: lots (29), tranche (30: "" for a whole position, "T1 +5" / "rest" for scale-out parts) and scan (31: the
    scan choice that picked a standalone option's strike, else "")."""
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder): os.remove(os.path.join(folder, f))
    extra = lambda x: [x.get(k) for k in FZ_TRADE_KEYS] + [x.get("lots", 1), x.get("tranche", ""), x.get("scan", "")]
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


# lab.py functions that cannot change a result (definitions sync, CLI, output bookkeeping): an edit to them keeps stored
# results; any other lab.py edit, engine.py, and (FZ rows) the FZ modules re-run
CACHE_EXEMPT = {"main", "add_backtest", "load_strategies", "type_rows", "sync", "connect", "migrate", "save_run",
                "cache_key", "code_hash", "record_history", "def_view", "flat", "fz_flat", "slug", "insert_backtest"}
_CODE_HASH = {}
def code_hash(fzr=False):
    """sha1[:16] of the code a result comes from: lab.py without CACHE_EXEMPT functions, engine.py, FZ modules for FZ."""
    if fzr not in _CODE_HASH:
        src = open(os.path.join(HERE, "lab.py"), encoding="utf-8").read().replace("\r\n", "\n")
        drop = [(n.lineno, n.end_lineno) for n in ast.parse(src).body
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in CACHE_EXEMPT]
        keep = [ln for i, ln in enumerate(src.split("\n"), 1) if not any(a <= i <= b for a, b in drop)]
        h = hashlib.sha1("\n".join(keep).encode())
        for f in ("engine.py",) + (FZ_MODULES if fzr else ()):
            h.update(open(os.path.join(HERE, f), "rb").read().replace(b"\r\n", b"\n"))   # line endings differ across checkouts
        _CODE_HASH[fzr] = h.hexdigest()[:16]
    return _CODE_HASH[fzr]


def cache_key(st, pr):
    """Everything a result depends on: the strategy row (an FZ row's fz_json included), the period, the code (the three FZ
    modules only for FZ rows, so an fz.py edit re-runs FZ rows and nothing else), and the input data files."""
    h = hashlib.sha1()
    row = {k: v for k, v in st.items() if k not in ("id", "created_at", "enabled", "name", "description")}
    h.update(json.dumps([row, pr["date_from"], pr["date_to"]], sort_keys=True, default=str).encode())
    h.update(code_hash(fz_rule(st)).encode())
    files = [st["data_file"], st["spot_file"], st.get("signal_file"), FUT1, os.path.join(st["option_dir"] or "", "manifest.csv")]
    if fz_rule(st): files.append(FUT1)                  # front_month per session comes from the 1-minute file
    if st["variant"] != "FUT" and st.get("weekly_dir"):
        files += sorted(glob.glob(os.path.join(st["weekly_dir"], "nifty_options*", "*", "*", "manifest.json")))
        # the option candle files themselves, so a refreshed data set is picked up even if a manifest did not change
        files += sorted(glob.glob(os.path.join(st["weekly_dir"], "nifty_options*", "*", "*", "NIFTY_*_[CP]E_*.csv")))
    for f in files:
        if f and os.path.exists(f): h.update(f"{f}:{os.path.getsize(f)}:{int(os.path.getmtime(f))}".encode())
    return h.hexdigest()[:16]


BRIEF = ("trades", "wins", "pts", "net_inr", "pf", "max_dd_inr", "t_stat")


def def_view(spec):
    """What defines a strategy's results: the file without its name, description and backtest list."""
    out = {k: v for k, v in spec.items() if k not in ("name", "description", "backtests")}
    out["position"] = position_of(spec)              # an explicit default block is not a change
    return out


def flat(d, pre=""):
    out = {}
    for k, v in (d.items() if isinstance(d, dict) else []):
        if isinstance(v, dict): out.update(flat(v, f"{pre}{k}."))
        else: out[f"{pre}{k}"] = v
    return out


def record_history(specs, index):
    """results/history/<CODE>.json: a new version whenever the strategy's definition (def_view) or the code its results
    come from changes; the results of the current version are refreshed on every full run. Returns {family: (current,
    previous)} - previous is the version this one is read against (None for a strategy's first version)."""
    os.makedirs(HISTORY, exist_ok=True)
    out = {}
    for path, spec in specs:
        fam = spec["code"]; metas = [m for m in index if m["family"] == fam]
        if not metas: continue
        dv, ch = def_view(spec), code_hash(str(spec["rules"].get("entry_rule", "")).startswith("fz"))
        vid = hashlib.sha1(json.dumps([dv, ch], sort_keys=True).encode()).hexdigest()[:12]
        res = {m["code"]: {rk: {c: {k: v.get(k) for k in BRIEF} for c, v in info["choices"].items()}
                           for rk, info in m["runs"].items() if info["choices"]} for m in metas}
        f = os.path.join(HISTORY, f"{fam}.json")
        H = json.load(open(f, encoding="utf-8")) if os.path.exists(f) else {"code": fam, "versions": []}
        V = H["versions"]
        now = D.datetime.now().isoformat(timespec="seconds")
        if V and V[-1]["vid"] == vid:
            V[-1].update(updated=now, results=res)
        else:
            changes = []
            if V:
                prev = dict(V[-1]["def"], position=position_of(V[-1]["def"]))   # defaults added later are not changes
                a, b = flat(prev), flat(dv)
                prov = lambda k: k.rsplit(".", 1)[-1] in ("source", "statistic", "note")     # provenance, not a rule
                changes = [f"{k}: {json.dumps(a.get(k))} -> {json.dumps(b.get(k))}" for k in sorted(set(a) | set(b))
                           if a.get(k) != b.get(k) and not prov(k)]
                if V[-1]["code_hash"] != ch: changes.append("code (engine.py / lab.py pricing / FZ modules) changed")
            V.append({"version": len(V) + 1, "vid": vid, "at": now, "updated": now, "code_hash": ch, "def": dv,
                      "changes": changes, "results": res})
        json.dump(H, open(f, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        out[fam] = (V[-1], V[-2] if len(V) > 1 else None)
    return out


def add_backtest(argv):
    """python lab.py backtest <CODE> <MTD|1M|3M|6M|YTD|1Y|5Y|all|FROM> [TO] [--tf 15minute] [--underlying INDEX]
       [--square-off none|HH:MM] [--label "..."]
    Appends the backtest to that strategy's file in strategies/ (the source of truth) and returns the code to run."""
    args, opts, i = [], {}, 0
    while i < len(argv):
        if argv[i].startswith("--"): opts[argv[i][2:]] = argv[i + 1]; i += 2
        else: args.append(argv[i]); i += 1
    code, what = args[0], args[1]
    path = next((p for p, sp in load_strategies() if sp["code"] == code), None)
    if not path: sys.exit(f"no strategy file with code {code}")
    if opts.get("tf") and opts["tf"] not in TIMEFRAMES: sys.exit(f"--tf must be one of {', '.join(TIMEFRAMES)}")
    if what in ("MTD", "1M", "3M", "6M", "YTD", "1Y", "5Y"):
        b = dict(label=opts.get("label", "This month" if what == "MTD" else what), kind="preset", preset=what)
    elif what == "all": b = dict(label=opts.get("label", "All data"), kind="all")
    else: b = dict(label=opts.get("label", f"{what} to {args[2]}"), kind="custom", **{"from": what, "to": args[2]})
    if opts.get("tf"): b["timeframe"] = opts["tf"]
    if opts.get("underlying"):
        if opts["underlying"] not in UNDERLYINGS: sys.exit(f"--underlying must be one of {UNDERLYINGS}")
        b["underlying"] = opts["underlying"]
    if opts.get("square-off"):                        # positional: --square-off none; intraday: --square-off 15:25
        b["square_off"] = None if opts["square-off"].lower() in ("none", "positional") else opts["square-off"]
        try: position_of({"position": {"square_off": b["square_off"]}})
        except ValueError as e: sys.exit(f"--square-off: {e}")
    spec = json.load(open(path, encoding="utf-8"))
    key = lambda x: (x["label"], x.get("timeframe") or spec["timeframe"], x.get("underlying") or spec.get("underlying", "FUT"),
                     x.get("square_off", "own"))
    same = lambda x: key(x) == key(b)
    if any(same(x) for x in spec["backtests"]):
        print(f"{os.path.basename(path)} already has backtest {b['label']!r} on {b.get('timeframe') or spec['timeframe']}; running it")
        return [code]
    insert_backtest(path, b)
    print(f"added to {os.path.basename(path)}:", b)
    return [code]


def insert_backtest(path, b):
    """Add one backtest to a strategy file as one line after the last entry of its "backtests" list, in the style of the
    entries already there; the rest of the file (its layout, key order, comments in notes) stays byte for byte."""
    raw = open(path, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    k = raw.index('"backtests"')
    i = raw.index("[", k)
    depth, j = 0, i
    for j in range(i, len(raw)):                     # the list's closing bracket (strings in it hold no brackets)
        depth += raw[j] == "["; depth -= raw[j] == "]"
        if depth == 0: break
    body = raw[i + 1:j]
    last = body.rstrip()
    line_start = raw.rfind(nl, 0, i + 1 + len(last)) + len(nl)
    indent = re.match(r"[ \t]*", raw[line_start:]).group(0) if last else "    "
    one = "{ " + ", ".join(f"{json.dumps(kk)}: {json.dumps(v, ensure_ascii=False)}" for kk, v in b.items()) + " }"
    if last:
        pos = i + 1 + len(last)
        new = raw[:pos] + "," + nl + indent + one + raw[pos:]
    else:
        new = raw[:i + 1] + nl + indent + one + nl + raw[i + 1:]
    json.loads(new)                                  # still valid JSON, or nothing is written
    open(path, "w", encoding="utf-8", newline="").write(new)


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
    import gc
    def run_lock():
        """One lab.py run at a time (a dashboard job and a terminal run would write the same web/ folders and database):
        an OS lock on cache/lab.lock, released when the process ends; a second run waits for it."""
        os.makedirs(CACHE, exist_ok=True)
        fh = open(os.path.join(CACHE, "lab.lock"), "a+")
        if os.name == "nt":
            import msvcrt
            take = lambda: msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            take = lambda: fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        said = False
        while True:
            try:
                fh.seek(0); take(); return fh
            except OSError:
                if not said: print("another lab.py run is in progress; waiting for it to finish"); said = True
                __import__('time').sleep(5)

    _lock = run_lock()

    def wopen(path):
        """Open an output file for writing; retry for a while if another program (antivirus, indexer, a viewer) holds it."""
        for n in range(10):
            try: return open(path, "w", encoding="utf-8", newline="")
            except OSError:
                if n == 9: raise
                print(f"{os.path.basename(path)} is busy; retrying"); __import__("time").sleep(3)
    full = "--full" in sys.argv                     # recompute everything, ignoring stored results
    argv = [a for a in sys.argv[1:] if a != "--full"]
    if argv[:1] == ["backtest"]:
        add_backtest(argv[1:]); only = []           # then a complete run (stored results are reused), so the page is whole
    else:
        only = [a for a in argv if not a.startswith("--")]
    db = connect()
    specs0 = load_strategies()          # the files as this run read them: another session editing them mid-run cannot stop it
    order = {sp["code"]: i for i, (_, sp) in enumerate(specs0)}      # strategy file order: 1, 2, ... 9, 10
    sts = sorted((dict(x) for x in db.execute("select * from strategy where enabled=1 order by family, id")),
                 key=lambda x: (order.get(x["family"], 999), x["id"]))
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
        meta["position"] = position_cfg(st)
        meta.update(underlying=st.get("underlying") or "FUT", native_scan=native_scan_cfg(st))
        meta.update(strategy_name=st["name"].split(" · ")[0], strategy_description=st["description"],
                    choch_mode=st.get("choch_mode") or st["break_mode"])
        if fzr: meta["fz_hash"] = fz_hash()
        meta["runs"] = {}
        for bt in [b for b in bts if b["family"] == st["family"]]:
            tf = bt["timeframe"] or st["timeframe"]
            und = bt.get("underlying") or st.get("underlying") or "FUT"
            # holding: the strategy's own (position.square_off), or the backtest's override - positional ('none') or intraday
            sq0 = position_cfg(st).get("square_off"); ov = bt.get("square_off")
            sq = sq0 if ov is None else (None if ov == "none" else ov)
            rk = (f"{slug(bt['label'])}_{TF_LABEL[tf]}" + ("_idx" if und == "INDEX" else "")
                  + ("" if sq == sq0 else "_pos" if sq is None else "_intra"))
            frm, to, status, reason = resolve_backtest(bt, st["warmup_days"])
            if status == "ok" and st["variant"] != "FUT":   # options: only where a full option chain exists (no hindsight strikes)
                cov = option_coverage(st)
                if cov is None:
                    status, reason = "refused", "no full-chain option data; fill expiries with tools/breeze_options.py"
                elif frm < cov:
                    if bt["kind"] == "all":
                        frm = cov                             # All data for options = the full-chain period
                    else:
                        status, reason = "refused", (f"options have full-chain data from {cov} (earlier expiries hold only the five "
                                                     f"strikes around settlement); fill them with tools/breeze_options.py")
            if status == "ok" and und == "INDEX":
                if fzr: status, reason = "refused", INDEX_WHY_FZ
                elif st["variant"] == "OPT_NATIVE": status, reason = "refused", INDEX_WHY_NATIVE
            if status == "ok" and fzr:
                if tf not in blocks: status, reason = "refused", f"no FZ thresholds for {tf}"
                elif st["variant"] == "OPT_NATIVE": status, reason = "refused", FZ_NATIVE_WHY
            info = dict(id=bt["id"], label=bt["label"], kind=bt["kind"], preset=bt["preset"], notes=bt["notes"],
                        date_from=frm, date_to=to, timeframe=tf, underlying=und,
                        holding=f"intraday {sq}" if sq else "positional",
                        design=tf == st["timeframe"] and und == (st.get("underlying") or "FUT") and sq == sq0, is_default=bt["is_default"],
                        status=status, reason=reason, choices={})
            meta["runs"][rk] = info
            if status != "ok":
                print(f"refused {rk:<12} {st['code']:<8} {bt['label']}: {reason}"); continue
            # engine warm-up: the strategy's own for Foundation rows (each window re-warms from its own start); for FZ rows
            # every session before the window, so the band memory starts at the file's first session and the Design /
            # Unseen runs are date slices of the All-data run (resolve_backtest still refuses on the file's warm-up)
            warm = ss.index(frm) if fzr else st["warmup_days"]
            info.update(memory_start=ss[max(0, ss.index(frm) - warm)], same_sample="file_start" if fzr else "own_warmup")
            if sq != sq0: st = dict(st, position_json=json.dumps(dict(position_cfg(st), square_off=sq), sort_keys=True))
            stp = dict(st, timeframe=tf, data_file=tf_file("fut", tf), spot_file=tf_file("spot", tf), underlying=und,
                       signal_file=tf_file("spot" if und == "INDEX" else "fut", tf),
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
            if fresh:                                  # one run per code and backtest; freed once written (memory)
                res = {ch: side_of(rr, st["positions"]) for ch, rr in run_variant(dict(stp, positions="BOTH"), cs).items()}
            for ch in choices:
                if fresh:
                    rr = res[ch]
                    run_id, s = save_run(db, stp, ch, rr, cs)
                    write_result(folders[ch], stp, ch, rr, s, cs, key)
                    rows = [[x["position"], x["instrument"], x["entry_time"], x["entry_px"], x["exit_time"], x["exit_px"], x["exit_reason"],
                             round(x["pts"], 2), round(x["gross"], 2), round(x["chg"]["total"], 2), round(x["net"], 2), int(x["open"])]
                            for x in rr["trades"]]
                    skl = rr["skipped"]
                    part = lambda f: stats([x for x in rr["trades"] if f(x)])
                    s_long, s_short = part(lambda x: x["position"] == "LONG"), part(lambda x: x["position"] == "SHORT")
                    s_ce, s_pe = part(lambda x: x["opt_type"] == "CE"), part(lambda x: x["opt_type"] == "PE")
                    fzp = rr.get("fz")
                else:
                    d = stored[ch]; s = d["stats"]; run_id = None; skl = d["skipped"]
                    s_long, s_short, s_ce, s_pe = (d.get(k) for k in ("stats_long", "stats_short", "stats_ce", "stats_pe"))
                    rows = [[x[21] if len(x) > 21 else x[0], x[1], x[4], x[5], x[7], x[8], x[9], x[10], x[11], x[12], x[13], int(x[14])] for x in d["trades"]]
                    fzp = d.get("fz")
                hl = fzp["headline"] if fzr and fzp else None
                rel = os.path.relpath(folders[ch], HERE).replace(os.sep, "/")
                brief = lambda z: z and {k: z[k] for k in ("trades", "wins", "pts", "net_inr", "pf")}
                # skipped = positions without option data (incomplete, *); locked = signals the strike lock refused (a rule)
                n_lock = sum(str(k.get("why", "")).startswith("strike locked") for k in skl); n_skip = len(skl) - n_lock
                info["choices"][ch] = dict(file=f"{rel}/summary.json", run_id=run_id, skipped=n_skip, locked=n_lock, **s,
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
            res = rr = None; gc.collect()
            Series._cache.clear()                      # candle files are re-read per run; option chains die with the run
        index.append(meta)
    db.commit()
    if only:                                           # never publish a dashboard or results/ that lack the other strategies
        print(f"partial run ({' '.join(only)}): dashboard and results not rebuilt")
        return
    hist = record_history(specs0, index)
    for m in index:                                    # the previous version of the same strategy, to read this one against
        cur, prev = hist.get(m["family"], (None, None))
        m["version"] = cur and dict(version=cur["version"], at=cur["at"], changes=cur["changes"])
        m["baseline"] = prev and dict(version=prev["version"], at=prev["at"], results=prev["results"].get(m["code"], {}))
    for fam, (cur, prev) in hist.items():
        if not prev: continue
        print(f"{fam}: version {cur['version']} vs {prev['version']}" + (f" ({'; '.join(cur['changes'])})" if cur["changes"] else ""))
        for code, runs in cur["results"].items():
            for rk, chs in runs.items():
                for c, v in chs.items():
                    o = prev["results"].get(code, {}).get(rk, {}).get(c)
                    if o and (c == "-" or c.endswith("-ATR2")) and o.get("net_inr") != v.get("net_inr"):
                        print(f"   {code:<7} {rk:<18} {c:<7} net {o['net_inr']:>+10,.0f} -> {v['net_inr']:>+10,.0f}   "
                              f"trades {o['trades']} -> {v['trades']}")
    page = open(os.path.join(HERE, "dashboard.tpl"), encoding="utf-8").read()
    page = page.replace("/*DATA*/", "const INDEX=" + json.dumps(index, separators=(",", ":")) + ";const TFS="
                        + json.dumps(TF_LABEL) + ";const DATA_RANGE=" + json.dumps([sessions()[0], sessions()[-1]]) + ";")
    open(os.path.join(HERE, "dashboard.html"), "w", encoding="utf-8").write(page)
    # versioned result snapshots (the strategy definitions themselves live in strategies/*.json)
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(summary, open(os.path.join(HERE, "results", "summary.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    with wopen(os.path.join(HERE, "results", "trades.csv")) as f:
        w = csv.writer(f)
        w.writerow(["run", "strategy", "choice", "position", "instrument", "entry_time", "entry_px", "exit_time", "exit_px",
                    "exit_reason", "pts", "gross_inr", "charges_inr", "net_inr", "is_open"])
        w.writerows(all_trades)
    # FZ: one row per Foundation SETUP (the gate ledger) and the cross-tabs / bridge / control, per FZ code and run
    with wopen(os.path.join(HERE, "results", "fz_setups.csv")) as f:
        w = csv.writer(f); w.writerow(["run", "strategy", "choice", *LEDGER_COLS]); w.writerows(fz_setups)
    with wopen(os.path.join(HERE, "results", "fz_ledger.csv")) as f:
        w = csv.writer(f); w.writerow(["run", "strategy", "choice", "table", "row", "col", "value"]); w.writerows(fz_tabs)
    print("wrote dashboard.html, web/*, results/summary.json, results/trades.csv, results/fz_setups.csv, results/fz_ledger.csv")


if __name__ == "__main__":
    main()
