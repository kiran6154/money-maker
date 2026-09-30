# Strategy lab

Prototype bench for NIFTY futures strategies before they are coded into money-maker.
Every strategy is the same **foundation engine** run with its own rule settings, one file per strategy in `strategies/`.

> **Where it sits:** `research/strategy_lab/` inside money-maker. It is standalone Python (3.10, `requests`, `pymysql` for
> `tools/kitecreds.py`) and is **not** part of the Spring Boot build, its schema (SQLite `strategy_lab.db`, not Liquibase)
> or its `Strategy` beans. Nothing here places orders. Candle data is read from `D:/nifty/…` (see *Data*); the Kite
> download tools reuse the app's Zerodha session from `broker_session` and `application.properties`.
> Commit history before the move lives on as the first two commits of this folder (`foundation-v1`, `variants-v1`).

## Foundation (engine.py)
swings (Pine port) → protected level → CHoCH / BOS → AVWAP pair from previous SH & SL at each CHoCH → SETUP → trade

- **Protected low (uptrend):** latest unbroken SL that sat below the trend AVWAP when it confirmed; protected high mirrors it.
- **CHoCH:** protected level broken; trend flips if the AVWAP is broken too.
- **SETUP:** after a CHoCH, both pair AVWAPs slope with it (vs previous candle) and a candle closes beyond the CHoCH candle low (PE) / high (CE).
- **Exit:** stop loss (per `sl_rule`), else close of the next CHoCH candle.
- Swing confirmation, BOS and protected-level use-up break by touch or close (`break_mode`); the CHoCH — the break of the
  protected level and the AVWAP check for a flip — has its own `choch_mode` (defaults to `break_mode`).

## Strategies (`strategies/strategy_<n>.json`)
| Code | Name | Timeframe | CHoCH | Stop loss | Note |
|---|---|---|---|---|---|
| `ST1` | Strategy 1 | 1 min | touch | previous swing | the foundation rules on 1-minute candles |
| `ST2` | Strategy 2 | 5 min | touch | CHoCH candle | the foundation rules on 5-minute candles |
| `ST3` | Strategy 3 | 1 min | **close** | previous swing | Strategy 1, CHoCH needs a close beyond the level |
| `ST4` | Strategy 4 | 5 min | **close** | CHoCH candle | Strategy 2, CHoCH needs a close beyond the level |
| `ST5` | Strategy 5 (FZ base) | 1 min | touch | previous swing | **FZ base**, band model: Strategy 1 SETUPs through the **Foundation-Zone gate** (`entry_rule: fz_v1`, see *FZ* below). Kept as the base; not to be traded (S39, S42) |
| `ST6` | Strategy 6 (FZ base) | 5 min | touch | CHoCH candle | **FZ base**, band model: Strategy 2 SETUPs through the Foundation-Zone gate |
| `ST7` | Strategy 7 | 1 min | touch | previous swing | **FZ v2, the living indicator on rooms** (`entry_rule: fz_v2`, `room_model: rooms`): a room is a band the market sat in, retired after 2 sessions without a visit; Strategy 1 SETUPs gated by the room card ([`FZ.md` §19](FZ.md#19-v2-rooms-strategies-7-8)) |
| `ST8` | Strategy 8 | 5 min | touch | CHoCH candle | FZ v2 on rooms with Strategy 2 SETUPs (20-minute sit, rooms retired after 3 sessions) |
| `ST9` | Strategy 9 | 1 min | touch | **managed** | Strategy 1's entries with **managed exits** (`position.exit: position`): 3 lots, stop 50 pts / 5% of premium = 1R, lot 1 out at 1R, lot 2 at 2R, last lot trails from 3R (1R ladder); no CHoCH exit (S43) |
| `ST10` | Strategy 10 | 5 min | touch | **managed** | the same managed exits on Strategy 2's entries |
| `ST11` | Strategy 11 | 1 min | touch | **managed + reverse** | Strategy 9 with **stop and reverse**: an initial-stop exit opens the opposite position at the stop (full 3 lots, same management), once per signal (S48) |
| `ST12` | Strategy 12 | 5 min | touch | **managed + reverse** | Strategy 10 with stop and reverse |
| `ST15` | Strategy 15 | 1 min | touch | **managed, positional** | Strategy 1's entries, positional, all 3 lots trail from 3R, 2R behind (no partial exits) — best of the 2026 exit study, in-sample (S50) |
| `ST16` | Strategy 16 | 5 min | touch | **managed, positional** | the same exits on Strategy 2's entries |
| `ST17` | Strategy 17 | 1 min | touch | **managed, positional** | Strategy 1's entries, positional, lot 1 out at 2R, lot 2 at 4R, the last lot trails from 4R, 2R behind |
| `ST18` | Strategy 18 | 1 min | touch | **managed, positional** | Strategy 1's entries, positional, stop 75 pts, 1R / 2R, trail from 3R, 2R behind |
| `ST19` / `ST20` | Strategy 19 / 20 | 1 min / 5 min | touch | **learner** (`rl_v1`) | the journal + learner on Strategy 1's / Strategy 2's SETUPs, reward = net rupees (see *Learner* below; S51) |
| `ST21` / `ST22` | Strategy 21 / 22 | 1 min / 5 min | touch | **learner** | the same, reward = R multiple |
| `ST23` / `ST24` | Strategy 23 / 24 | 1 min / 5 min | touch | **learner** | the same, reward = net with losses weighted 1.5x (profit-factor oriented) |
| `ST25` | Strategy 25 | 5 min | **close** | **c2c: premium stop / trail, 15:15 ladder** | **CHoCH to CHoCH put retest** (`entry_rule: c2c_v1`, `c2c.py`, see *CHoCH to CHoCH* below): buy the ITM1 put of the nearest monthly ≥ 15 days out when a swing high confirms within 50 pts of the VWAP anchored at the pre-break peak, after a bearish flip; window PCR rules on; stops on the candle close (S52) |
| `ST26` | Strategy 26 | 5 min | **close** | c2c | Strategy 25 with the PCR rules off |
| `ST27` | Strategy 27 | 5 min | **close** | c2c, **touch stops** | Strategy 25 with stops by touch (exit at the stop; at the open on a gap) |
| `ST28` | Strategy 28 | 5 min | **close** | c2c, touch stops | Strategy 27 with the PCR rules off |
| `ST29` | Strategy 29 | 1 min | touch | **rainbow** (`rainbow_v1`) | **Rainbow ribbon intraday** (see *Rainbow ribbon* below), the grid's pick for 1-minute: EMA 5–55 ribbon, cross, fan none, osc ≥ 25, all-lot trail 3R−2 — in sample 277 positions, net ₹-395,954, PF 0.83, t -1.22; out of sample 112 positions, net ₹-334,212, PF 0.57, t -2.38, OOS rank 11 of 48; no variant qualified (all 48 lost) |
| `ST30` | Strategy 30 | 5 min | touch | **rainbow** (`rainbow_v1`) | **Rainbow ribbon intraday** (see *Rainbow ribbon* below), the grid's pick for 5-minute: Widner 10 × SMA(2), pullback, fan full, osc ≥ 25, all-lot trail 3R−2 — in sample 138 positions, net ₹-150,088, PF 0.87, t -0.68; out of sample 81 positions, net ₹-131,634, PF 0.73, t -1.08, OOS rank 2 of 48; no variant qualified (all 48 lost) |

Each file holds one strategy: `code`, `name`, `description`, design `timeframe`, `warmup_days`, `rules`
(`break_mode`, `choch_mode`, `avwap_weight`, `sl_rule`, `entry_rule`, `exit_rule`), `lot_size`, `capital`, per-type charges and
slippage (`types`), option settings (`options`: expiry types, strike choices / default, ATR period), how positions are held
(`position`, below) and its `backtests`.
**Add a strategy:** copy a file to `strategy_<n+1>.json`, give it a new `code` and `name`, change the rules, run `python lab.py`.
Shared inputs live in `config/data.json` (candle files) and `config/charges.json` (charge schedules). Old rows whose file was
removed are disabled in the database, never deleted.

### Position (`position` in the strategy file)
```json
"position": { "lots": 1, "lock": "strike", "scale_out": [] }
```
- **`lock: "strike"`** (default, the fundamental rule): one open position per traded instrument — strike + expiry + CE/PE
  for options, the contract for futures. A signal that would open a second position on a strike that is still open is not
  taken; it is listed with `why = "strike locked: <instrument> open until <time>"` (Trades tab, under the table) and does not
  lock anything. An exit and a new entry on the same candle count as exit first, so the new position is taken. Foundation
  exits every position at the next CHoCH before the next SETUP, so on Strategies 1–6 today the lock never binds (0 of the
  All-data positions); it matters as soon as a design can re-enter while a position is open. `"none"` switches it off.
- **`lots`**: lots per position (charges, gross and net scale with it; points stay per lot).
- **`square_off`** (`"HH:MM"` or null): intraday. A position still open after that time on its entry day closes at the close of
  the last candle that opens at or before it (exit reason `eod`); a signal at or after it is not taken. Strategies 1–4 and 9–10
  use `"15:25"` (user decision 2026-09-28); the FZ strategies (5–8) keep their own exits.
- **`reverse`** (`{"trigger": "initial_stop", "max": 1}` or null; needs `exit: "position"`, Strategies 11–12): when a position's lots
  leave at its initial stop (not a trail stop), the opposite position opens at the stop fill — a full new position with the
  same lots, stop, targets and trail — up to `max` times per signal, never at or after the square-off. Futures and standalone
  options reverse on the same contract; Options (via futures) reverse a stopped leg into the opposite signal's leg (long CE →
  long PE, short PE → short CE), strike from the index at the stop, entered at that option's close of the stop candle. Reversed
  lots are labelled `REV T1 1R`, `REV rest (trail)`, … in the trades table and on the chart.
- **Intraday or positional per backtest:** any backtest entry can override the strategy's holding with `"square_off": null`
  (positional: held overnight) or `"square_off": "HH:MM"` (intraday). The run key gets `_pos` / `_intra`, the Candles switch
  labels each run intraday / positional, a badge shows when a run is not on the strategy's own holding, and *+ backtest* has
  a *Positional* / *Intraday 15:25* button for the backtest on screen (`python lab.py backtest ST9 MTD --square-off none`).
  Strategies 1–4 and 9–10 carry a positional *This month* next to their intraday default.
- **`scale_out`**: part of the lots exit at a fixed target, the rest ride the strategy's exit, e.g. 2 lots, one out at +10:
  `{"lots": 2, "scale_out": [{"lots": 1, "target_pts": 10}]}`. The target is in the traded instrument's points (option
  premium for options, futures points for futures), from the entry fill; it fills on the first candle after the entry
  candle that reaches it (at the open if the candle opens beyond it, on a session's first candle at the close — no fill on the
  opening print); a target reached only on the candle where the stop is hit counts as not reached (stop first). A tranche
  whose target is never reached exits with the rest. Each tranche is a trade row (`lots`, `tranche` = `T1 +10` / `rest`)
  and is charged as its own round trip (so a scale-out pays one extra brokerage on entry — conservative).
- **Managed exits** (`"exit": "position"`, Strategies 9–10): the strategy's own exit (next CHoCH, `rules.sl_rule`) is not used;
  each position is run on its own candles (futures, or the option's premium) from the entry fill:
  ```json
  "position": { "lots": 3, "lock": "strike", "exit": "position",
                "stop": { "futures_pts": 50, "option_pct": 5 },
                "scale_out": [ { "lots": 1, "target_r": 1 }, { "lots": 1, "target_r": 2 } ],
                "trail": { "start_r": 3, "lag_r": 1 } }
  ```
  R = `stop.futures_pts` for futures, `stop.option_pct` % of the entry premium for options; the stop starts 1R against the
  entry. Per candle: the stop first (all open lots), then targets (`target_r` × R, or `target_pts`), then the trail — once
  `start_r` full R have been reached (best price so far) the stop moves to (R reached − `lag_r`) × R and steps up by whole R,
  applying from the next candle. Lots still open at the backtest end are valued there (`open`, *), option lots at their
  contract's last candle (`expiry`). Exit reasons: `stop_loss`, `target 1R`, `target 2R`, `trail_stop`. Set `rules.sl_rule`
  to `none` with it (a rule-based stop would make the engine refuse SETUPs whose swing sits on the wrong side).
Changing any of these is a strategy change: its results get a new version in `results/history` (below).

## Strategy → type → scheme
| Level | Values | Where it is set / seen |
|---|---|---|
| **Strategy** (`family`) | Strategy 1 … Strategy 8 | one card each: rules, timeframe, SL; the card's **options bar** holds option **expiry** (Weekly / Monthly) and **strike**, shared by both option types |
| **Type** (one `strategy` row each) | Futures (`ST2`) · Options (via futures) (`ST2_FB`) · Options (standalone) (`ST2_NB`) | a row on the card |
| **Scheme** | Long + short (default) · Long only · Short only | the Total / Long / Short columns on the card, and the scheme switch above the chart |
| Position (per trade) | long / short | trades table |
| Instrument (per trade) | FUT / CE / PE | trades table and one breakdown table — never a separate group |

- **Futures:** long future on a future-long signal, short future on a future-short signal.
- **Options (via futures):** the futures' signals traded in options — long CE and short PE on future long, long PE and short CE on future short.
- **Options (standalone):** the engine on the option's own chart, independent of the futures — long on bullish setups, short
  on bearish setups. **Rescan** (`options.native_scan`, default `{"choices": ["ATR2", "ATM", "ITM1", "OTM1"],
  "every_minutes": 5, "one_per_side": true}`): every 5 minutes, on the index candle that has just completed, the strike of
  each scan choice is picked for CE and PE (ATR(14) on those 5-minute candles; nearest weekly or month-end expiry), and each
  picked contract is watched until the next scan. The choices are checked independently; the first SETUP on any watched
  contract whose entry candle closes in the watch opens the position (ties: scan-list order). With `one_per_side` no other
  CE (or PE) is entered until that position has closed — the strike is held till the trade completes; signals refused
  meanwhile are listed as `strike locked: CE side open until …`. Exits: the engine's own on that option's chart (next CHoCH,
  stop), or the managed position (Strategies 9–10); a contract's data ends at its expiry. Results: one book per expiry
  type, `W-SCAN` / `M-SCAN` (the strike selector applies to Options (via futures)); each trade records the scan choice that
  picked it (trades table, strike column).

### Signal source: futures or index (`underlying`)
A strategy's `underlying` (`"FUT"` default, or `"INDEX"`) is the candle series the engine reads; any backtest can run on the
other one (`"underlying"` in the backtest entry, `python lab.py backtest ST2 all --underlying INDEX`, or *+ backtest → Run
with signals on the index / futures*; run keys get `_idx`, the Candles switch labels each run futures / index, and a badge
shows when a run is not on the strategy's own source).
- **INDEX:** the NIFTY index candles, with an **equal-weighted AVWAP** (the index has no volume; user decision 2026-09-27).
  The Futures type still trades the near-month futures: entry at the futures close of the signal candle; exits at the
  futures price of the exit candle — a stop crossed on the index fills at the futures price of that candle shifted by the
  stop's distance. Options (via futures) take their strikes from the index as always. FZ strategies and Options
  (standalone) refuse index runs (FZ's thresholds are futures points; standalone options read the option's own chart).
- **Near-month futures only:** each futures position trades the contract of its entry candle (`contract` / `expiry`
  columns of the 1-minute file), which is the near-month contract from the day after the previous monthly expiry to its own
  expiry; a position still open at that contract's last candle is closed there (`expiry`). The upcoming contract is never
  traded early. The strike lock is per contract, so the next contract is free after the roll. (The Kite files of July–
  September hold the September contract throughout; `tools/breeze_history.py` builds the near-month files.)

Every type runs long + short once; long only and short only are its long and short halves (same signals, same fills), stored as
`stats_long` / `stats_short` next to `stats`. Below the chart: KPIs (with long and short cards in the long + short scheme) and tabs —
Trades, Cumulative P&L (total / long / short lines), Daily P&L, Breakdown (position, signal, instrument, exit reason, entry time,
holding), Expiry & strike, Signals, Config, Rules. Short option P&L is sell-at-entry, buy-at-exit; margin is not modelled.
Earlier rows (`*_OF/_OB/_OS/_ON/_FL/_FS/_NL/_NS`) are kept disabled.

**Option data (`option_source = WEEKLY_LOCAL`).** Weekly contracts: the nearest expiry at least `expiry_min_days` (1) calendar
days away, so expiry day rolls to the next week. Prices come from the local ICICI weekly files under `weekly_dir`
(`nifty_options` 5-minute, `nifty_options_1minute` 1-minute chunks) and from the full Kite chain for the 29-Sep expiry
(`tools/kite_options.py`). The local files only hold strikes near the ATM of the day before expiry (a hindsight window), so they
supply prices only: a strike picked from spot that is not in the file is **skipped and reported**, never substituted. A position
still open at expiry closes at the contract's last candle (`expiry`). Coverage gaps: 15-Sep and 22-Sep expiries failed to
download (5-minute); the local 1-minute files hold only 4–5 strikes per side, so 1-minute option variants price few signals.
**Filling the missing strikes (`tools/breeze_options.py`, STRATEGY_ANALYSIS_TODO S41):** ICICI Breeze serves expired
contracts, so the gap is closed with data, not a rule change. For each expiry it works out every strike any strategy's strike
choice can pick from spot on the sessions that use that expiry (weekly and monthly, 1- and 5-minute candles) and fetches
those not already in the files into the same `.chunks/options/<CE|PE>/<strike>/` layout (both intervals are read from there),
then marks the expiry's `manifest.json` so stored results re-run. `--plan` shows the request count without logging in
(2026-07-28 + 2026-08-25: 694 requests; every weekly and monthly expiry from July to 22 September: 1,374; Breeze allows
5,000 a day). The login is yours: set `BREEZE_API_KEY`, `BREEZE_API_SECRET` and the day's `BREEZE_SESSION_TOKEN` in the
environment (never stored) and `pip install breeze-connect` once.

**Expiry type (`expiry_types = WEEKLY,MONTHLY`).** Option variants run once per expiry type × `strike_choices` entry; results
are keyed `W-<strike>` / `M-<strike>` and the dashboard has Expiry and Strike selectors (default `W-ATR2`). Weekly = nearest
weekly expiry; monthly = nearest month-end expiry (28 Jul, 25 Aug, 29 Sep here), both at least `expiry_min_days` away. In the
last week of a month they are the same contract. Monthly 29-Sep uses the full Kite chain, so 1-minute monthly results cover
the in-sample period fully.

Strike choices: default `ATR2` = spot ± 2×ATR(14) of the timeframe, OTM, rounded to 50; also `ATM`, `ITMn`, `OTMn`. Spot from `tools/kite_spot.py`. Slippage per side is `slippage_pts` (futures 5, options 0.5).
Charges: `ZERODHA_NFO_FUT` / `ZERODHA_NFO_OPT` in `charge_schedule`.

Fills: entry at the SETUP candle close; stop at the worse of candle open and stop, or the session's first candle close.
Look-ahead check: `python tests/test_truncation.py`.

## Learner: journal every trade, learn after each one (Strategies 19–24, `rl.py`, `entry_rule: rl_v1`)
At every Foundation SETUP a contextual bandit (Bayesian linear regression per action, Thompson sampling) decides **skip, or
trade with which exit profile, which stop and how many lots** — the strategy file's `rl` block lists the actions:
```json
"rl": { "reward": "net", "seed": 7, "ridge": 1.0, "explore": 0.3, "stops_pts": [35, 50, 75], "lots": [1, 2, 3],
        "profiles": { "intraday 1R/2R trail 3R-1": {...}, "positional trail 3R-2": {...}, "positional 2R/4R trail 4R-2": {...} },
        "notes": "what was fixed before any result was seen" }
```
- **Features** (all at the SETUP candle's close): hour bucket, direction, trend flip, ATR % of price, distance from the two
  AVWAPs in ATRs, bars since the CHoCH, entry-candle body, 20-bar range, CHoCHs so far today, the session's closed result
  in R, form over the last 3 trades, consecutive losses, closed trades today, distance from the day's open.
- **Learning:** full information — once a SETUP's candles have played out, the outcome of every action is known from the
  price data, so every action's model updates (in exit-time order, only after the exit candle has closed: no decision sees
  the future; `tests/test_rl.py` checks this by truncation). Rewards: `net` = net ₹ in units of one lot's 50-point risk,
  `r` = net points per lot ÷ stop, `pf` = net with losses × 1.5. Skip earns 0.
- **Window:** the learner starts empty at the futures file's first session (Oct 2021) and learns to its end once per
  strategy; each backtest is a window cut from that run, so a 2026 window is out of sample for the weights it starts with
  (not for the action set: the three profiles came from the 2026 exit study, S50 — the `notes` say so). Every book is
  valued at the window's last candle for positions still open there; a month straddling the window's start is two rows
  (learning, scored).
- **Journal tab** (dashboard, learner strategies only): tiles — SETUPs, taken / skipped / locked; learner net with its t;
  the base book = Strategy 9's rule run as its own book under the same one-position lock; **random books** = the learner's
  percentile among 200 seeded books of a uniformly random action per SETUP (skip is 1 action in 28, so they trade almost
  every free SETUP: necessary to beat, not sufficient); the oracle = the best net per SETUP in hindsight (never below 0, an
  upper bound); **seed spread** = the same learner run from empty on 4 more seeds (`spread_seeds`), this window's net per
  seed; **matched permutations** = the learner's own window decisions shuffled 200 times across the same SETUPs under the
  same lock (same take rate and sizes), the learner's percentile and the share at or above it — the test of *where* it chose
  to trade; pred vs realised (correlation and gap); clipped outcomes per action — then the action mix, month by month (a
  month straddling the window start is a learning row and a scored row; the scored rows sum to the tiles), the learned
  weights ranked by |weight| × the feature's spread, and every scored SETUP with its features, decision, predicted reward,
  outcome, base and oracle. `summary.json['rl']` carries all of it (`summary`, `months`, `seeds`, `random`, `permutation`,
  `prediction`, `clipped_by_arm`, `feature_sd`, `weights`, `journal`). Read the seed spread and the permutation percentile
  before any single net. Known bias, not yet priced in (S51 (9)): an action's reward is its own outcome, but a long-held
  position also costs the book the SETUPs it locks out — so the learner leans to the positional profiles.
- **Scope v1:** near-month futures only (option types, index signals and a backtest's square-off override are refused with
  the reason — each exit profile carries its own square-off). Costs, strike lock and fill rules are the lab's; a contract
  whose candles end before its expiry date closes its lots there (`expiry`). `lab.py` touches the learner only from its
  exempt functions (loader, dispatch in `main`, `cache_key` and the `results/history` version id add `rl.py`), so the other
  strategies' stored results are unaffected by learner changes.

## CHoCH to CHoCH: put retest (Strategies 25–28, `c2c.py`, `entry_rule: c2c_v1`)
From the user's *Nifty CHoCH to CHoCH in Plain English* spec (2026-09-29). Every number is in the file's `c2c` block (no
defaults in code); the four files differ only in `pcr` (window PCR rules, or `null`) and `stop_fill` (`close` / `touch`):
```json
"c2c": { "band_pts": 50, "day_drop_pct": 0.6, "stop_pct": 5, "trail_pts": 5, "stop_fill": "close", "max_open": 1,
         "pcr": { "entry_max": 1.3, "exit_above": 0.95, "window_pts": 300, "min_strikes": 9 },
         "ladder": { "time": "15:15", "profit_pct": 40, "loss_pct": 2 } }
```
- **Regime and VWAP** are the engine's (break and CHoCH by close): bearish from a CHoCH that flips the trend down until one
  flips it up; the anchored VWAP is the engine's AVWAP from the swing high the flip re-anchors at (equal-weighted on the
  index, volume-weighted on futures). A CHoCH that breaks the protected level without flipping the trend changes nothing.
- **Entry**, all on one closed 5-minute candle: bearish regime, a swing high confirms there, VWAP − 50 < swing high < VWAP
  + 50, close > the session's first open × 0.994, not the flip candle, and (PCR books) window PCR < 1.3. The ITM1 put
  (one strike above the ATM of the index close) of the nearest monthly ≥ 15 days out, bought at the open of its first
  candle at or after the next signal candle, the same session only. One position at a time; positional (no square-off).
- **Exits** on the put's own candles, in this order: stop (5 % below the entry premium, then 5 pts behind the peak premium
  once it has gained — `close`: a close at or below it, the peak from closes; `touch`: the low touching it, the peak from
  highs, at the open on a gap), a bullish flip (that candle's close), and the 15:15 ladder once per session (profit > 40 %,
  loss > 2 %, or PCR > 0.95). A position entered after 15:15 meets its first ladder the next session.
- **Window PCR** = Σ PE OI / Σ CE OI over the strikes within 300 pts of the ATM on the traded expiry (both rights needed;
  NA below 9 strikes, which blocks an entry and never triggers an exit). The local files hold a strike window, not the full
  chain: a stand-in for the exchange PCR (S52).
- **Data:** only expiries with full-chain data are priced (the lab's coverage rule, per trade); signals on other expiries are
  skipped with the reason. For "nearest monthly ≥ 15 days" that is 2026-06-23 → 07-13 and 07-22 → 09-14 today (Jul-28 and
  Aug-25 from Breeze, Sep-29 from Kite; Oct-27 is missing). The default backtest is that window on index signals, with the
  same window on futures signals beside it.
- **Scope v1:** the Options (via futures) type only (Futures and standalone options are refused with the reason), 5-minute
  candles only. `summary.json['c2c']` carries the entry funnel (swing highs → bearish → not the flip candle → in the band →
  above the day floor → PCR → priced → taken / locked), the exit reasons and the PCR distribution at the candidates.
  `tests/test_c2c.py` walks the exits on synthetic candles and checks no look-ahead by cutting the window.

## Rainbow ribbon intraday (Strategies 29–30, `rainbow.py`, `entry_rule: rainbow_v1`)
User (2026-09-29): "create a new strategy of best intraday with rainbow for 1min and 5min". Neither word had a definition in
the repo, so the build took **rainbow** = Mel Widner's Rainbow Charts (10 recursive 2-period simple averages of the close,
plus his oscillator) with an EMA ribbon as the alternative, and **best intraday** = the variant a pre-registered grid picks
in sample and a later window then reports (S53). Every number is in the file's `rainbow` block:
```json
"rainbow": { "kind": "widner", "levels": 10, "period": 2, "trigger": "cross", "fan": "none", "osc_min": 25, "lookback": 10,
             "pullback_bars": 5, "entry_from": "09:20", "entry_until": "14:30", "exit": "none" }
```
- **Ribbon:** `widner` = line 1 is SMA(period) of the close, line k the SMA of line k−1, `levels` lines; `ema` = EMAs of the
  `periods`. Band = [lowest line, highest line]; fan bullish when every faster line is above the next; oscillator = 100 ×
  (close − mean of the lines) / (highest − lowest close over `lookback` candles). All from candles ≤ the current one.
- **Entry:** a fresh close outside the band (the previous close was not), in the `entry_from`–`entry_until` window, with the
  `fan` condition (`full` / `none`), the oscillator at least `osc_min` (signed), and for `trigger: pullback` a re-emergence:
  price had already closed outside the band on that side within the last `pullback_bars` candles, came back, and the band's
  far edge kept its slope (the first break out of a range is a cross, not a pullback). Entry at the signal close on the
  near-month contract; one position per contract (a signal while one is open is skipped). The ribbon runs through session
  opens (no reset at 09:15), so the first candles of a session read the previous close; the payload counts entries per hour.
- **Exits** are the lab's `position` block: `exit: "strategy"` uses the ribbon's far side at the signal as the stop and (with
  `rainbow.exit: "band"`) a close back through it as the exit; `exit: "position"` uses the managed exits (stop in points,
  R-based scale-out, trail). Square-off 15:25 in both files.
- **The grid (S53, pre-registered, corrected after the review before the published run):** kind (widner, ema) × trigger
  (cross, pullback) × fan (full, none) × osc_min (0, 25) × exits (band; managed 1R / 2R + trail 3R−1 at stop 50; managed
  all-lot trail 3R−2 at stop 50) = 48 variants per timeframe on Jan 5 – Jun 30 2026 (100 sessions, no May contract), Jul 1 –
  Sep 25 2026 (62 sessions) held out; rule = highest in-sample net with ≥ 30 positions and PF > 1, else the highest
  in-sample net, said so. `studies/rainbow_grid.py` reproduces it; `studies/rainbow_grid.json` holds every row.
  **Every one of the 96 variants lost money in both halves**, so the two files hold the least-losing rule, not an edge.
  Result: **1-minute (ST29)**: pick = EMA 5–55 ribbon, cross, fan none, osc ≥ 25, all-lot trail 3R−2 (NO variant qualified - the highest in-sample net taken); in sample 277 positions, net ₹-395,954, PF 0.83, t -1.22; out of sample 112 positions, net ₹-334,212, PF 0.57, t -2.38; its out-of-sample rank 11 of 48. Across the grid: 0 of 48 variants positive in sample, 0 out of sample; the best out-of-sample variant was Widner 10 × SMA(2), cross, fan none, osc ≥ 25, all-lot trail 3R−2 at ₹-288,563; the worst in sample lost ₹-20,411,088 (5744 positions, band stop + band exit). Band exits (the ribbon's own stop and exit) averaged 1,807 in-sample positions and ₹-6,479,492 per variant against 285 and ₹-754,541 for the managed exits (whose one-position lock refuses most signals): a fast ribbon flips sides every few candles, so the ribbon's own exits trade the costs away. **5-minute (ST30)**: pick = Widner 10 × SMA(2), pullback, fan full, osc ≥ 25, all-lot trail 3R−2 (NO variant qualified - the highest in-sample net taken); in sample 138 positions, net ₹-150,088, PF 0.87, t -0.68; out of sample 81 positions, net ₹-131,634, PF 0.73, t -1.08; its out-of-sample rank 2 of 48. Across the grid: 0 of 48 variants positive in sample, 0 out of sample; the best out-of-sample variant was Widner 10 × SMA(2), cross, fan full, osc ≥ 25, all-lot trail 3R−2 at ₹-123,638; the worst in sample lost ₹-3,937,188 (1114 positions, band stop + band exit). Band exits (the ribbon's own stop and exit) averaged 347 in-sample positions and ₹-1,049,482 per variant against 196 and ₹-495,639 for the managed exits (whose one-position lock refuses most signals): a fast ribbon flips sides every few candles, so the ribbon's own exits trade the costs away.
- **Chart:** the ribbon is drawn on the futures chart (the *Rainbow* layer, red = fastest line, violet = slowest); the
  engine's swings / CHoCH / AVWAP overlays stay for context and decide nothing here.
- **Scope v1:** the Futures type on the futures' own candles; option types and index signals are refused with the reason.
  `summary.json['rainbow']` carries the signal count, taken / locked / after-square-off, the exit reasons and the oscillator
  at the signals. `tests/test_rainbow.py` checks the arithmetic on hand-made candles, the signal rules, the exits, the
  config and no look-ahead by cutting a real window.

## FZ: the Foundation-Zone gate (Strategies 5 and 6)
> Builder's reference with every rule as coded, the lab wiring, the tests and the open decisions: [`FZ.md`](FZ.md).
> **v2 (Strategies 7 and 8)** replaces the band memory below with rooms (born only from sits, never overlapping, retired after
> `room_max_age_sessions` without a visit, named `<letter> <mm-dd hh:mm>`); the card, reads, gate and watch are the same code.
> See [`FZ.md` §19](FZ.md#19-v2-rooms-strategies-7-8). Strategies 5 and 6 are the base (`room_model: bands`), bit for bit.

`ST5` (Strategy 1 rules, 1 min) and `ST6` (Strategy 2 rules, 5 min) run the Foundation engine unchanged and then gate every
Foundation SETUP against a memory of price bands (`rules.entry_rule = "fz_v1"`). `engine.py` is not modified: `fz.py` reads a
frozen view of its output (swings, SETUPs, CHoCHs, the protected level) and the bars, never its trades, exits or final-state fields.

- **Bands.** ± `band_half_width` around a mid. **A** bands are born when a swing becomes the protected level (dated at the first
  protected bar; visit 1 backfilled from the swing bar). **B** bands are born when the last `cluster_bars` same-session closes sit
  within `cluster_width` (on the transition into the sit). A candidate overlapping a band by `merge_overlap` merges into the one
  it overlaps most; the survivor keeps its edges, id and history. No band is ever deleted.
- **Memory = the file.** The band memory starts at the file's first session, so every FZ window (All data, Design, Unseen, 1M)
  is a date slice of one run (`same_sample = file_start`). The Foundation book FZ is compared with comes from that same run, so
  it can differ from ST1's / ST2's independent runs, which re-warm from each window's start (`own_warmup`).
- **Card (per bar, as-of, never rewritten).** The *ref band* is the band whose visit is live; a visit ends only on `leave_closes`
  consecutive closes outside it on one side (a single close inside a neighbouring band does not end it). The card holds the
  band, visit n, this / first visit bars and volume, the band just left, the session bar, the opening gap and the **read**,
  first match: LEAVE (of the band just left, for `leave_ttl_bars` while no close comes back inside or crosses its mid) → HUNT
  (1m: one close out and back in; 5m: a wick beyond an edge by `hunt_min_depth_atr` × ATR14 with both closes inside; a volume
  burst of `hunt_burst` when volume is live) → REJECT (a wick within `reject_tol` of an edge, close nearer the mid than the open)
  → FIRST_PRINT (visit 1) / ACCEPTED (`accept_bars` lived and volume ≥ `accept_vol_ratio` × the first visit's) / THIN / RECYCLE
  → PENDING (the first close outside) → NEW. One live visit at a time wins over a return (evaluation D01): a close back inside
  the band just left ends its LEAVE and marks that band's leave as failed (`last_leave_failed` on the card while it is the ref
  band), but it opens visit n+1 on that band only when no other band holds the live visit; otherwise the neighbour keeps the
  visit and the bar is counted as `leave_return_no_visit` (Zone gate tab, card statistics; docs/STRATEGY_ANALYSIS_TODO.md S40 c).
- **Gate at each Foundation SETUP**, first match: **BLOCK** (no watch) for `in_position`, `clock` (bar open ≥ `no_entry_from`),
  `open_pierce` (in the first `open_bars`, the bar crosses an edge of a band last visited on an earlier day with fewer than
  `open_sit_closes` closes inside today), `hunt_fade` (a SETUP in the pierce direction of a HUNT within `fade_block_bars`) or
  `new`; **TAKE** = Foundation's own position (branch 1 a LEAVE in its direction, checked against `leave_far_side`, and refused
  while `session_bar < open_quiet_bars` when the leave's outside closes include the session's first bar, i.e. a gap leave;
  branch 2 a FIRST_PRINT in the visit's entry direction after `first_print_min_bars`; branch 3 an ACCEPTED defend after a HUNT
  or REJECT at the opposite edge within `defend_window_bars`); else **WATCH** on the band holding the close (WATCH_EDGE on the
  band just left when the SETUP is its first close outside and `edge_watch = ref_band`); else BLOCK `new`. A branch-1 (LEAVE)
  TAKE of the band a watch waits on, in the watch's direction, is that watch's **REENTER** (evaluation M22); a FIRST_PRINT or
  defend TAKE stays Foundation's own TAKE and leaves the watch as it is. The gap rule takes a gap leave as soon as
  `open_quiet_bars` have passed; the evaluation's "and R2 re-met by closes after that" is not implemented (S40 a).
- **WATCH → ARMED → REENTER**, one watch at a time: R1 a close beyond the band on the watch's side (arms it), R2 `leave_closes`
  such closes, R3 none back inside or across the mid since R1, R4 far-side volume ≥ the sit's (skipped when NA), R5 a Foundation
  SETUP the same way on that bar or the one before. The fill is the close of the bar where R1–R5 hold (`reenter_fill =
  confirm_bar`); the stop is Foundation's rule evaluated at the fill bar; exits are the stop, then **`band_reclaim`** (a close
  back past the band's mid), then the next CHoCH (`fz_exec.simulate`, which reproduces every Foundation trade). A watch is
  cancelled at the next session's first bar, by an opposite TAKE or LEAVE, or, once armed, by `cancel_inside_bars` closes back inside.
  R3 is read as an unbroken far-side run: a close back inside (fewer than `cancel_inside_bars` of them) breaks the run and the
  next close beyond arms the watch again, so the ledger carries `armed_bars` (from the first arming) and `rearmed_bars` (from
  the latest); the strict reading, no close back inside at all since the first R1, is an open question (S40 b).
- **Volume NA.** A bar is NA when the 1-minute file's `front_month` is 0 that session or its volume is 0; a visit is NA if any bar
  is. NA skips R4, the HUNT burst and THIN, and makes ACCEPTED time-only. Everything before 26 Aug is volume-blind.
- **Clocks.** Durations are bars; clock rules use the bar's **open** time (`open_window_until`, `no_entry_from`); a visit inside at
  a session's last bar continues at the next session's first bar (`this_bars` grows by one across the night).

**The `fz` block.** Keyed by timeframe (`"minute"` in `strategy_5.json`, `"5minute"` in `strategy_6.json`); a backtest on a
timeframe without a block is refused, and Options (standalone) is refused for FZ (the thresholds are futures points). Every
key is `{value, source, statistic[, note]}` with `source` = `spec:<section>`, `decision:<n>` or `evaluation:<M/C/D-id>` of the
2026-09-27 FZ evaluation; `fz.thresholds()` refuses a missing, unknown or unsourced key and there are no defaults in code. The
Config tab prints them. `leave_far_side` (`any` / `block_list` / `no_band`) and `birth_b` (`band` / `flag`) are still the user's
decisions (docs/STRATEGY_ANALYSIS_TODO.md S35, S36); a changed value is a new strategy code or a recorded before / after run.

**Files and outputs.** `fz.py` (pure: bands, card, reads, gate, watch state machine), `fz_exec.py` (frozen view, `simulate()`,
the position callback, the FZ trade list), `fz_report.py` (cross-tabs, bridge, session-matched random control, permutation p,
sample-size flags), `tests/test_fz_parity.py`, FZ cases in `tests/test_truncation.py`. Per run and choice `summary.json['fz']`
(ledger, watches, cross-tabs, bridge, control, books, flags, all-NA comparator, legend); `Z` (the card per bar) and `ZONES` (bands
to draw) in each futures chart chunk; table `fz_setup` and trade columns `gate`, `reenter_reason`, `zone_id`, `fill_used`;
`results/fz_setups.csv` (one row per ledger row: futures and the W-ATR2 options-via-futures choice) and `results/fz_ledger.csv`
(cross-tabs, bridge and control per code and run).

The ledger has two gate columns: `gate` is the gate as of the SETUP bar (what the truncation test checks), `outcome_gate` the
gate the SETUP ended with: `REENTER` when a REENTER used that SETUP, even when the fill came on a later bar and the SETUP's own
gate read WATCH (most REENTERs fill that way). The gate × read tables, the headline counts and the all-NA comparator count
SETUPs by `outcome_gate`, so REENTER rows match REENTER positions. In `results/summary.json` an FZ row carries `fz_take`,
`fz_watch`, `fz_block`, `fz_reenter` (SETUPs by how they ended), `fz_reenter_at_setup` (SETUPs gated REENTER on their own bar),
`fz_take_trades` / `fz_reenter_trades` (positions), `fz_priced` (the positions priced in that choice: the denominator of
`control_pct`; for options via futures a position with no option candles is unpriced, so `trades` counts priced legs),
`control_pct`, `perm_p`, `active_sessions`, `fz_sessions` and `fz_hash`. The permutation test splits Foundation's trades by what
FZ traded: kept = the SETUPs FZ held a position on (a TAKE, or a REENTER on that SETUP), refused = the rest.

**Dashboard.** Zones chip (A bands purple, B bands blue), the hovered bar's card on the price line (its volume ratio is NA when
this visit or the band's first visit is volume-NA, as the gate reads it), T / W / B / R gate markers with the trades layer,
BAND exits; the random-control percentile and the kept-vs-refused p beside Net P&L in the KPI strip; the **Zone gate** tab (gate × read, watches, positions, the three `leave_far_side` counts,
volume NA and R4, bridge, random control and kept-vs-refused permutation, both books with sample flags, active sessions and
dormant stretches, gate by hour / visit / direction / zone kind, card statistics, and the ledger: click a row to open the chart
at that SETUP); Read and Gate in Signals; the `fz` keys in Config; a Foundation-Zone card in Rules.

**Procedure.**
- Iterate with a filtered run: `python lab.py ST5 ST6` stores ST5 / ST6 but does not rewrite `dashboard.html` or `results/*`
  ("partial run"). **Never commit `results/` from a filtered run**; the final build is a plain `python lab.py`. An edit to
  `fz.py` / `fz_exec.py` / `fz_report.py` invalidates only FZ rows (about 5 minutes); an edit to `lab.py` invalidates every row
  (about 3 hours).
- Judge FZ by its ledger and the random control, not by net against Foundation: Foundation's per-trade loss is about its costs,
  so any gate that drops trades raises net. The bridge separates price from cost avoidance; the session-matched random control
  and the kept-vs-refused permutation p say whether the selection beats chance.
- The **Unseen window is not out of sample for FZ**: several thresholds were read off tape-wide statistics that include it, and
  it is volume-blind. Read Design against the **all-NA comparator** (the same run with volume NA on every bar), not against
  Unseen. The first genuine out-of-sample check is the sessions from 2026-09-28 on, run once with the strategy files unchanged.
- `python tests/test_fz_parity.py` and `python tests/test_truncation.py` must pass before any FZ result is read.

**Pre-registered expectations (evaluation, 2026-09-27) against the first run** (All data, seeded values; the verdict so far is
docs/STRATEGY_ANALYSIS_TODO.md S39: no better than random selection on either timeframe):

| Expectation | 1 min (ST5) | 5 min (ST6) |
|---|---|---|
| ~92% (1m) / ~82% (5m) of bars close inside a band | 94.7% | 83.5% |
| LEAVE the most common read | yes, 43.7% of bars | yes, 38.4% |
| visit_n median ~30 at 1m SETUPs | **19** (26.5 over inside reads): not met. The build keeps a visit live through a close inside a neighbouring band, where the evaluation's simulator ended it, so visits are fewer and longer (S38 c) | 7 |
| FIRST_PRINT ~0 at SETUP (0–2 on 1m, 0–6 on 5m) | 0 | 0 |
| REENTER a small book (~64 on 1m with `edge_watch = ref_band`, ~6 with `containing_band`) | 22 positions (20 from a WATCH_EDGE, 2 from a plain WATCH) | 12 (all WATCH_EDGE) |
| Branch-1 TAKEs under `block_list` ~10–16 on 1m | 10 | 14 |
| SETUPs by the gate they ended with, TAKE / WATCH / BLOCK / REENTER (gate at the SETUP bar) | 29 / 114 / 42 / 22 of 207 (29 / 134 / 42 / 2) | 14 / 32 / 15 / 12 of 73 (14 / 44 / 15 / 0) |
| Random-control percentile · permutation p (kept = SETUPs FZ traded) | 6.2th · 0.44 | 49.8th · 0.18 |

Numbers above are from the 2026-09-27 phase-5 rebuild (S40: a FIRST_PRINT / defend TAKE is no longer turned into a REENTER,
which moved two 1m positions; the permutation now splits by the SETUPs FZ traded). The first run read 27 / 24 positions on
1m, gate rows as of the SETUP bar, and control 4.0th · p 0.58 / 49.8th · p 0.63.

## Files
| Path | What |
|---|---|
| `engine.py` | foundation engine (pure; no I/O besides loading candles) |
| `c2c.py` | the CHoCH to CHoCH put-retest rule (Strategies 25–28): entry funnel, premium stop / trail, 15:15 ladder, window PCR (see *CHoCH to CHoCH*) |
| `rainbow.py`, `tests/test_rainbow.py`, `studies/rainbow_grid.py` | the rainbow-ribbon intraday rule (Strategies 29–30): Widner / EMA ribbon, fresh-close entries with fan / oscillator / pullback filters, band or managed exits; its tests; the pre-registered grid that picked the two files' variants (S53) |
| `fz.py`, `fz_exec.py`, `fz_report.py` | the Foundation-Zone gate (Strategies 5–6 bands, 7–8 rooms): gate, execution / simulator, reports (see *FZ*) |
| `lab.py` | runs enabled strategies, stores results, writes dashboard + exports |
| `dashboard.tpl` | dashboard template (`dashboard.html` is generated) |
| `strategies/strategy_<n>.json` | **versioned** — one file per strategy: the source of truth for its rules and backtests |
| `config/data.json`, `config/charges.json` | **versioned** — input candle files, charge schedules |
| `results/summary.json`, `results/trades.csv` | **versioned** latest headline numbers and trades — diff them across commits |
| `results/history/<CODE>.json` | **versioned** — every version of a strategy (definition + result code) with its headline numbers per backtest and choice; the baseline each new version is read against |
| `serve.py`, `start_lab.cmd` | the dashboard server with the backtest queue (`python serve.py`, or double-click `start_lab.cmd`); binds its port exclusively and says so if it is taken |
| `explorer.py`, `explorer.html` | the chart explorer: any date, futures / index / one option, every indicator and a strategy's trades on that instrument's own candles (read-only, via serve.py) |
| `studies/` | one-off study scripts that reuse the lab without writing its results (`r_combinations.py`: exit combinations for Strategies 9–10) |
| `exports/` | standalone HTML exports (chart + trades + CSV) for sharing, e.g. `ST9_1m_futures_2026-06-29_to_2026-07-02.html` |
| `tests/test_strategy_files.py` | adding a backtest (terminal or dashboard) adds exactly one line in the style of its neighbours; the rest of every strategy file stays as written |
| `rl.py`, `tests/test_rl.py` | the learner (journal + contextual bandit, `rl_v1`) and its tests: no look-ahead by truncation, determinism, learning, outcome arithmetic |
| `tests/test_position.py` | position handling on hand-made candles: managed exits, R targets, the ladder trail, first-candle fills, scale-out, the strike lock |
| `results/fz_setups.csv`, `results/fz_ledger.csv` | **versioned** FZ gate ledger (one row per SETUP) and its per-run tables; written only by a full build |
| `tools/` | Kite downloads: `kitefut.py` / `kite1m.py` futures, `kite_spot.py` index, `kite_options.py` option chain (credentials read at runtime from money-maker); `breeze_options.py` fills expired option strikes and `breeze_history.py` fetches years of near-month futures and index candles from ICICI Breeze (credentials from the environment) |
| `web/` | per-variant, per-strike detail JSON the dashboard loads (generated, not versioned) |
| `tests/test_truncation.py` | look-ahead test (Foundation and FZ) |
| `tests/test_fz_parity.py` | FZ: `simulate()` reproduces every Foundation trade, no trade fields in `fz.py`, the card does not depend on positions, every `fz` key has a source |
| `strategy_lab.db` | SQLite working DB (not versioned; a cache of the files above plus run history; delete it any time) |

## Tables
`strategy` (definition + rules), `charge_schedule` (brokerage/STT/exchange/SEBI/stamp/GST rates),
`strategy_run`, `trade`, `choch_signal` (results per run), `fz_setup` (the FZ gate ledger per run; `strategy.fz_json` holds the
`fz` block verbatim and `trade.gate / reenter_reason / zone_id / fill_used` the FZ position fields).

## Backtests, timeframes, statistics
- **This month** (`preset: "MTD"`, from the 1st of the latest data month) is the default backtest of Strategies 1–4 and 9–10;
  All data (five years for futures), 1Y, 3M, 1M, Design and Unseen stay one click away.
- **Charts for option types:** the underlying chart on top (the index when the run's signals come from the index or for
  Options (standalone), else the near-month futures) and the traded option's own chart below it, from the session before
  the trade; both keep the same time window when either is scrolled or zoomed. A session with several contracts shows a
  button per contract; clicking a trade opens its session and its contract, zoomed to it. *PNG* / *JPG* save both charts.
- **Strategy files keep their layout:** adding a backtest from the terminal or the dashboard inserts one line after the last
  backtest in the style of the others (`lab.insert_backtest`); nothing else in the file is rewritten.
- **Backtests are per strategy** (listed in the strategy's file, synced to `strategy_backtest`): each is one independent run over its own dates (plus warm-up) —
  `all` (every session after warm-up), presets `1M 3M 6M YTD 1Y 5Y` counted back from the latest data date, or named/custom
  ranges such as **Design period** (26 Aug – 25 Sep: the rules were built here) and **Unseen test** (8 Jul – 25 Aug). A backtest
  the data cannot cover is **refused with the reason** (e.g. 3M needs data before 1 Jul). Add one:
  `python lab.py backtest ST2 1Y` · `python lab.py backtest ST2 2026-07-10 2026-08-10 --label "July"` (appended to that
  strategy's file, then run).
- **Timeframe** defaults to the strategy's design timeframe; the same rules can run on other candles
  (`--tf minute|3minute|5minute|15minute|30minute`), built from 1-minute futures/spot (`cache/`) and 1-/5-minute options.
  Non-design runs show an amber badge.
- **Open at the end:** a position still open when a backtest ends is valued at its last candle and flagged `*`.
- **Capital per lot** (`capital_fut`, `capital_opt_short` on the strategy row; long options use the premium paid) feeds return on
  capital, Calmar and risk of ruin.
- **Trades table:** options show Expiry, Strike and CE/PE as their own columns, the option entry and exit (time @ premium),
  and for Options (via futures) the futures price in → out; a Lots column appears when a strategy scales out. Positions not
  taken are listed under the table with the reason (no option data / strike locked).
- **Dashboard tabs:** Trades · Performance (returns, Sharpe / Sortino / Calmar, expectancy in ₹ and R, payoff, streaks, time in
  market, % profitable days / weeks / months) · Cumulative P&L with drawdown curve · Drawdowns (top 5) · Distribution (P&L and
  R histograms, max-profit vs max-loss scatter, holding time) · Monte Carlo (2,000 runs, fixed seed: trade-order shuffle fan and
  drawdown / streak percentiles, bootstrap P(loss) and expectancy range, stress tests, risk of ruin) · Robustness (slippage and
  charges sensitivity, month by month, other timeframes, expiry × strike) · Breakdown · Daily P&L · Signals · Zone gate (FZ
  strategies only) · Config · Rules.

## Workflow
```
python lab.py                 # reuse stored results, recompute only what changed, rebuild dashboard + exports
python lab.py --full          # recompute everything
python lab.py ST1             # one strategy (partial run: stores it, does not rebuild dashboard.html or results/*)
python lab.py backtest ST2 1Y # add a backtest to strategies/strategy_2.json and run it
python serve.py               # then open http://localhost:8766/dashboard.html (python serve.py 8770 for another port)
start_lab.cmd                 # the same, by double-click (keeps the window open)
python serve.py 8770 --lan    # also reachable from other devices (see "From a phone" below)
```
**Running backtests from the page (no terminal, no assistant):** open the dashboard through `python serve.py`. *+ backtest*
then lists the presets (1M 3M 6M YTD 1Y 5Y, All data — ✓ = already a backtest of this strategy; dashed = the data does not
reach back that far yet, so it will be listed as not available until older data is added), a custom range, "run this backtest
on other candles", and *Recompute what is missing*. A click queues a job: it adds the backtest to the strategy's file and runs
`lab.py` (only missing or changed results are computed), the header shows the job, and the page reloads when it finishes.
Jobs run one at a time; a terminal `lab.py` run waits for a running job and the other way round (`cache/lab.lock`). Logs:
`cache/jobs/<id>.log`. The server listens on 127.0.0.1 only and refuses cross-origin POSTs; it never touches a broker.
Opened any other way (a plain static server), the panel shows the equivalent terminal commands instead.

**Chart explorer (`explorer.html`, via `python serve.py`):** a visualization page, not a backtest. Pick a date, a strategy,
the candle size, the holding (strategy's own / intraday 15:25 / positional) and how many sessions before to show. The top
chart is the near-month futures or the NIFTY index; the chart below is one option (expiry, CE / PE, strike — only contracts
with candles that day are offered; the default strike is the one nearest the index open). Both charts draw every indicator
(swings, AVWAP pair, protected level, CHoCH / BOS, volume) and the strategy's trades computed on that instrument's own
candles (for the option, the strategy applied to the option chart itself), with the stop / 1R / 2R / 3R lines, and keep
the same time window. Served by `explorer.py` through `GET /api/explorer/{meta,instruments,chart}` (read-only; the first
option listing of a date takes about 30 s, then it is cached).

**Studies (`studies/`):** one-off scripts that reuse the lab without writing its results — e.g. `studies/r_combinations.py`
(exit combinations for Strategies 9–10 over the last year and five years; output `studies/r_combinations.json`) and
`studies/rainbow_grid.py` (the pre-registered rainbow grid that picked Strategies 29–30; output `studies/rainbow_grid.json`).

**From a phone:** the server listens only on this PC unless started with `--lan` (every network address of the PC — home
Wi-Fi), `--tailscale` (only the PC's Tailscale address) or `--host <ip>`; it prints the phone address(es) at start.
- **At home:** `python serve.py 8770 --lan`, open `http://<PC address>:8770/dashboard.html`; Windows Firewall asks once.
- **Away from home:** install Tailscale on the PC and the phone and sign in with the same account, then
  `python serve.py 8770 --tailscale` (or `start_lab.cmd 8770 --tailscale`) and open the printed `http://100.x…` address.
  Only devices on your Tailscale account can reach it; it refuses to start when Tailscale is not connected.
- **Not offered:** port-forwarding or a public tunnel (ngrok, Cloudflare quick tunnel). The server has no login, so a public
  address would let anyone open the page and queue jobs.
Whatever the address: only `dashboard.html` and `web/*.json` are served (never the database, strategy files, tools, logs or
folder listings), and queue requests are accepted only from the page itself (same origin).

**Versions (before / after a change):** every full run writes `results/history/<CODE>.json`. A new version starts whenever the
strategy's definition (the file without its name, description and backtest list) or the code its results come from changes;
the current version's numbers are refreshed on every run. The run prints each changed headline (net and trades per backtest,
futures and the ATR2 option choices) against the previous version, and the dashboard's KPI row carries a *vs version N* tile
(long + short, same backtest and choice; the tooltip lists what changed). Version 1 of Strategies 1–6 is the result set
stored before the position config (lab.py of commit `7a8b10e`).

**Saving a chart:** *PNG* / *JPG* in the chart toolbar save the chart as it is shown (zoom, layers, the breadcrumb and session
as a title line). JPG is the smaller file.
**Stored results:** each (strategy, period, strike choice) is written to `web/<code>/<backtest>_<tf>/<choice>/` (e.g. `web/ST2/all-data_5m/W-ATR2/`) as `summary.json`
(KPIs, trades, signals, chart index) plus one `c<k>.json` chart chunk per session (per day-contract for option · native).
`summary.json` carries a cache key over the strategy row, the period, `engine.py` + `lab.py` (without the functions listed in
`CACHE_EXEMPT` — definitions sync, CLI, history and output bookkeeping — so editing those keeps stored results), and the input data files
(for FZ rows also `fz.py`, `fz_exec.py`, `fz_report.py` and the 1-minute file); a run is reused while the key matches.

**Dashboard loading:** it reads the summary, then only the session on screen; ‹ › and the session list fetch more on demand,
and *Full period* loads every session of the period into one chart only when clicked.
Change a rule → edit the strategy's file (or copy it into a new strategy) → `python lab.py` →
commit `strategies/` + `results/` together so the commit shows the rule change and its before/after numbers.

## Data
**Longer history (`tools/breeze_history.py`):** 1-minute near-month NIFTY futures (contract switched at each monthly
expiry, `contract` / `expiry` / `front_month` columns) and the 1-minute NIFTY index from ICICI Breeze, 2 sessions per request,
resumable (`D:/nifty/breeze/...`). `--plan` counts the requests without a login (1 Oct 2021 – 25 Sep 2026: 1,237 sessions,
60 contracts, 1,250 requests, about 15 minutes); `--build` writes `niftyfut_nearmonth_{minute,5minute}_<from>_to_<to>.csv` and
`nifty50_breeze_{minute,5minute}_…csv` and repoints `config/data.json` (only the four path values change). Presets 1Y and 5Y
are then no longer refused; option legs older than the local files stay skipped (orange *) until those expiries are filled
with `tools/breeze_options.py`.

Current files (built 2026-09-28): `D:/nifty/niftyfut_nearmonth_{minute,5minute}_2021-10-01_to_2026-09-25.csv` and
`D:/nifty/nifty50_breeze_{minute,5minute}_2021-10-01_to_2026-09-25.csv` — 1,188 sessions. **Gaps:** the April 2025 and May 2026
futures contracts (their monthly dates were first taken from the option calendar's last weekly; `lab.monthly_expiry` now
applies the exchange rule — last Thursday to Aug 2025, last Tuesday from Sep 2025, the session before on a holiday; the
missing 32 requests come with the next `tools/breeze_history.py --from 2021-10-01` run, then `--build`), and the index on
30–31 Mar 2022. Options run only from 30 Jun 2026, where every expiry has a full chain (`lab.option_coverage`); earlier
option backtests are refused with the reason, and All data for option types starts there. The earlier Kite files
(`niftyfut_*_2026-07-01_to_2026-09-25.csv`, the September contract throughout) are no longer used.
