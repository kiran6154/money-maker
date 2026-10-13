// Shared helpers for the strategy lab v2 pages: API calls, formatting, small DOM utilities, per-viewer preferences.
export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];

export async function api(path, opts) {
  const r = await fetch(path, opts);
  let j;
  try { j = await r.json(); } catch (e) { throw new Error(`${r.status} ${r.statusText}`); }
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
export const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const inr = (v) => v == null || Number.isNaN(v) ? "–" : (v < 0 ? "−₹" : "₹") + Math.abs(Math.round(v)).toLocaleString("en-IN");
export const num = (v, d = 2) => v == null || Number.isNaN(+v) ? "–" : Number(v).toFixed(d);
export const pct = (a, b) => (b ? Math.round((100 * a) / b) + "%" : "–");
export const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
export const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
export const tsOf = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10), +s.slice(11, 13) || 0, +s.slice(14, 16) || 0) / 1000;
export const dayOf = (ts) => new Date(ts * 1000).toISOString().slice(0, 10);
export const hm = (s) => (s || "").slice(11, 16);

export function pref(k, v) {            // per-viewer conveniences only; the page works without storage
  try {
    if (v === undefined) { const x = localStorage.getItem("lab2." + k); return x == null ? null : JSON.parse(x); }
    localStorage.setItem("lab2." + k, JSON.stringify(v));
  } catch (e) { return null; }
}

export const TYPE_LABEL = { FUT: "Futures", OPT_FUT_SIGNAL: "Options (via futures)", OPT_NATIVE: "Options (standalone)" };
export const TF_LABEL = { minute: "1m", "3minute": "3m", "5minute": "5m", "15minute": "15m", "30minute": "30m", "60minute": "1h" };

// a short label for an exit reason, used on chart markers and pills
export function reasonTag(r) {
  r = r || "";
  if (r === "stop_loss") return "SL";
  if (r === "trail_stop") return "TRAIL";
  if (r === "next_choch" || r === "choch") return "CHoCH";
  if (r === "eod") return "EOD";
  if (r === "buy_signal") return "BUY SIGNAL";
  if (r === "expiry") return "EXPIRY";
  if (r === "open") return "OPEN*";
  if (r.startsWith("target")) return r.replace("target ", "T ");
  if (r === "band_exit" || r === "band_reclaim") return "BAND";
  if (r.startsWith("ladder")) return r.replace("ladder_", "15:15 ");
  return r.toUpperCase();
}

// ------------------------------------------------------------------ the strategy as numbered steps
// algorithm(spec) -> [{t: text, sub: [...]}] read straight from the strategy's SPEC, so it always says what the code runs:
// 1 candles, 2 structure, 3 entry (3.1 ... conditions), 4 when a signal is not taken, 5 stop and exits, 6 costs.
// a strategy's square-off as shown to the reader: its own time, and the intraday close in force later (config/data.json)
export function sqOf(p) {
  const c = globalThis.__intradayClose;
  return p.square_off + (c && c.time < p.square_off ? ` (${c.time} from ${c.from})` : "");
}

export function algorithm(spec) {
  const r = spec.rules || {}, p = spec.position || {}, o = spec.options || {}, rule = r.entry_rule || "setup_v1";
  const TF = { minute: "1-minute", "3minute": "3-minute", "5minute": "5-minute", "15minute": "15-minute", "30minute": "30-minute", "60minute": "1-hour" };
  const by = (m) => (m === "close" ? "a candle closing beyond it" : "a candle touching it (high / low)");
  const S = (t, sub) => ({ t, sub: sub || [] });
  const steps = [];
  if (spec.rules?.entry_rule === "sma_arm_v1") {       // Strategies 69 / 70: the SMA cross arms the day, Foundation trades
    const x = spec.sma_cross, m = spec.sma_low, P0 = spec.position || {};
    return [
      S(`Candles: ${TF[spec.timeframe] || spec.timeframe} candles of what is traded — the near-month NIFTY futures (Futures), or each option's own candles (Options standalone). The first ${spec.warmup_days} sessions only form the SMAs and the structure.`),
      S(`The signal, on ${x.candles_min}-minute candles${spec.timeframe === "5minute" ? " (the same candles)" : " built from them"}: SMA ${m.periods.join(", ")} of the candle LOW. A ${x.candles_min}-minute candle CLOSES below an SMA that the previous one closed at or above${x.falling ? ", while that SMA is falling (below its value one candle before)" : ""} — any of the SMA ${x.periods.join(" / ")}.`, [
        S("It trades nothing. From the next candle until the square-off the day is ARMED."),
        S("Before the first such cross of the day nothing is traded.")]),
      S(`Market structure (Foundation engine), candle by candle on the ${TF[spec.timeframe] || spec.timeframe} candles:`, [
        S(`Swing high / low: confirmed when a later candle breaks the swing candle's low / high — ${by(r.break_mode)}.`),
        S("Protected level: in an uptrend, the latest confirmed swing low that sat below the trend AVWAP; in a downtrend the mirror."),
        S(`CHoCH: price breaks the protected level — ${by(r.choch_mode || r.break_mode)}.`),
        S("SETUP: after a CHoCH, both AVWAPs slope its way and a candle closes beyond the CHoCH candle.")]),
      S("Entry: a BEARISH SETUP while the day is armed → SHORT at that candle's close.", [
        S("Futures: sell the futures. Options standalone: SELL that option. Options via futures: the futures signal buys a put."),
        S("Bullish SETUPs are not traded. One position at a time.")]),
      S("Exit — first of:", [
        S(x.stop === "sma_high"
          ? `Stop: the SMA of the candle HIGHS on the ${x.candles_min}-minute candles, with the period of the SMA that was crossed last before the entry (the fastest when several were crossed together); its value at the entry candle, fixed from then. Not above the entry → the SETUP is not traded. Out at the stop (at the open if the candle opens above it).`
          : "Stop: the latest confirmed swing high at the entry (the engine's own stop) → out at the stop (at the open if the candle opens above it)."),
        S(x.target_r ? `Target: ${x.target_r} × the stop's distance below the entry (risk to reward 1:${x.target_r}) → out at the target (at the open if the candle opens below it).`
                     : `Target: ${x.target_pts} points below the entry → out at the target (at the open if the candle opens below it).`),
        S("In one candle the stop is checked before the target. The next CHoCH is NOT an exit."),
        S(`${sqOf(P0)}: no new entry from then; a position still open is closed at that candle's close (intraday).`)]),
      S(`Costs: slippage per side ${spec.types?.FUT?.slippage_pts ?? "–"} pts futures, ${spec.types?.OPT_NATIVE?.slippage_pts ?? "–"} pts options; charges per the broker schedule; lot size ${spec.lot_size}.`)];
  }
  if (spec.rules?.entry_rule === "sma_cross_v1") {     // Strategy 67: no Foundation rule trades; its own short list
    const x = spec.sma_cross, m = spec.sma_low, P0 = spec.position || {};
    return [
      S(`Candles: ${TF[spec.timeframe] || spec.timeframe} candles of what is traded — the near-month NIFTY futures (Futures), or each option's own candles (Options standalone). The first ${spec.warmup_days} sessions only form the SMAs.`),
      S(`Indicators: the SMA ${m.periods.join(", ")} of the candle LOW (the average of the last N candle lows), each in its own colour on the chart.`),
      S(`Entry: a candle CLOSES below an SMA that the previous candle closed at or above (a cross down), for any of the SMA ${x.periods.join(" / ")} → SHORT at that close.`, [
        S("Futures: sell the futures. Options standalone: SELL that option. Options via futures: the futures signal buys a put."),
        ...(x.falling ? [S("The SMA that is crossed must be FALLING at that candle: its value below its value one candle before. A cross down through a flat or rising SMA is not traded.")] : []),
        S("One position at a time: a cross while a position is open is ignored."),
        S("No entry on the last candle before the square-off."),
        S(`An option priced at or under ${x.target_pts} is not sold (the target could not be reached).`)]),
      S("Exit — first of:", [
        S(`Stop: ${x.stop_pts} points above the entry → out at the stop (at the open if the candle opens above it).`),
        S(`Target: ${x.target_pts} points below the entry → out at the target (at the open if the candle opens below it).`),
        S("In one candle the stop is checked before the target."),
        S(`${sqOf(P0)}: no new entry from then; a position still open is closed at that candle's close (intraday).`)]),
      S("The Foundation layers (swings, CHoCH / BOS, AVWAPs) may still be switched on in the chart; nothing here trades on them."),
      S(`Costs: slippage per side ${spec.types?.FUT?.slippage_pts ?? "–"} pts futures, ${spec.types?.OPT_NATIVE?.slippage_pts ?? "–"} pts options; charges per the broker schedule; lot size ${spec.lot_size}.`)];
  }
  const onOpt = !!spec.sma_filter;                 // Strategy 32: everything is read on each option's own chart
  const ns = o.native_scan || {};
  const sd = spec.straddle;                           // ST57 / ST58: everything is read on the derived straddle candles
  if (sd) steps.push(S(`Candles: ${TF[spec.timeframe] || spec.timeframe} DERIVED candles of the day-open ATM straddle — not the futures, not the index, not one option.`, [
    S(`Each day: take the strike nearest the NIFTY index at its first candle; the CE and the PE of that strike on the nearest weekly expiry at least ${o.expiry_min_days ?? 1} day out.`),
    S("Each candle = CE + PE: open = the two opens added, close = the two closes added, high / low = the highest / lowest of that open and close, volume = both."),
    S(`The pair's own candles of the ${spec.warmup_days} session(s) before warm the structure up; only SETUPs inside the day trade.`),
    ...(sd.gap_restart === "any" ? [S("Gap up or gap down, any size: when a chart's first candle of the day opens at any other price than the previous session's last close, that chart's CHoCH / BOS structure is RESET — built from the day's first candle only, with no memory of the earlier sessions. Checked separately on the straddle candles and on the option's own candles; in practice this is every day.")] :
        sd.gap_restart ? [S("Gap day: when a chart's first candle of the day opens above the previous session's high or below its low, that chart starts again — its structure is built from the day's first candle only, with no memory of the earlier sessions. Checked separately on the straddle candles and on the option's own candles.")] : [])]));
  else if (onOpt) steps.push(S(`Candles: ${TF[spec.timeframe] || spec.timeframe} candles of each option contract itself (not the index, not the futures); the first ${spec.warmup_days} session(s) only warm the indicators up.`, [
    S(`Which contracts: every ${ns.every_minutes || 5} minutes, for CE and PE, the ${(ns.choices || []).join(" / ")} strike${(ns.choices || []).length > 1 ? "s" : ""} (from the index's last closed candle) on the nearest expiry; each is watched until the next scan.`)]));
  else steps.push(S(`Candles: ${TF[spec.timeframe] || spec.timeframe} candles of the ${spec.underlying === "INDEX" ? "NIFTY index (AVWAP equal-weighted: the index has no volume)" : "near-month NIFTY futures"}; the first ${spec.warmup_days} session(s) only warm the indicators up.`));
  if (rule !== "rainbow_v1") steps.push(S(sd ? "Market structure (Foundation engine), candle by candle ON THE DERIVED STRADDLE CANDLES (never on the futures or on a single option):" : "Market structure (Foundation engine), candle by candle:", [
    S(`Swing high / low: confirmed when a later candle breaks the swing candle's low / high — ${by(r.break_mode)}.`),
    S("Protected level: in an uptrend, the latest confirmed swing low that sat below the trend AVWAP; in a downtrend the mirror (swing high above it)."),
    S(`CHoCH: price breaks the protected level — ${by(r.choch_mode || r.break_mode)}. If it also breaks the trend AVWAP, the trend flips.`),
    S("BOS: price breaks the last swing high (uptrend) / swing low (downtrend) — trend continuation, no trade by itself."),
  ]));
  const setup = S("SETUP: after a CHoCH, both AVWAPs (anchored at the previous swing high and swing low) slope in the CHoCH's direction AND a candle closes beyond the CHoCH candle (above its high for a bullish CHoCH, below its low for a bearish one). The entry is that candle's close.");
  const dirs = S("Direction → position: bullish = futures LONG · options LONG CE and SHORT PE; bearish = futures SHORT · options LONG PE and SHORT CE (each option leg is its own position).");
  const dirsOpt = S(`Direction → position on that option: bullish SETUP = LONG (buy it), bearish = SHORT (sell it); ${ns.one_per_side ? "one position per side (CE / PE) at a time; " : ""}first SETUP wins.`);
  if (rule === "setup_v1") steps.push(S("Entry: every SETUP is a position.", [setup, onOpt ? dirsOpt : dirs]));
  else if (rule === "straddle_v1" && sd.mode === "managed_short") {
    steps.push(S("Entry: a bearish SETUP on the derived straddle candles (the combined premium turning down) → be SHORT the straddle.", [setup,
      S("Flat → SELL the CE and SELL the PE."),
      S("One leg was bought back earlier → SELL that leg again (the re-entry); the leg still held is left as it is."),
      S("Each leg is its own position and fills at its own candle close at that candle.")]));
    steps.push(S("Management: a bullish SETUP on the derived straddle candles (the combined premium turning up) → BUY BACK one leg, keep the other.", [
      S(`The leg bought back is the one going up: the CE or the PE whose own close rose more over the last ${sd.lookback} candles (a tie: the CE).`),
      S("That leg is not held (already bought back) → nothing happens; the other leg stays short."),
      S(`No stop and no CHoCH exit. ${sqOf(p)}: every leg still open is closed at that candle's close.`)]));
  }
  else if (rule === "straddle_v1" && sd.mode === "leg_structure") {
    steps.push(S(sd.arm === "both" ? "The scenario: ANY SETUP on the derived straddle candles — a buy signal (the combined premium turning up) or a sell signal (turning down). It trades nothing; it picks the option."
                                   : "The long scenario: a bullish SETUP on the derived straddle candles (the combined premium turning up). It trades nothing; it picks the option.", [setup,
      S(`The option picked (armed) is the leg going up: the CE or the PE whose own close rose more over the last ${sd.lookback} candles (a tie: the CE).`),
      S(sd.window === "day" ? "Once armed, a leg stays armed until the close. A later long scenario can arm the other leg too."
                            : "A leg is armed only while that straddle SETUP is alive: until its stop (the previous swing of the combined premium) or the next CHoCH on the straddle chart.")]));
    if (sd.entry === "signal") steps.push(S("Entry: at that same candle's close, BUY the picked option. No SETUP of the option is waited for.", [
      S("Long only: nothing is sold, also on the straddle chart's sell signal."),
      ...(sd.above_prev_low ? [S("Filter: the option's price at the entry must be ABOVE the low that same option made in the session before. At or below it → not bought.")] : []),
      S(`The option's own 1-minute candles carry the same structure rules (its ${spec.warmup_days} sessions before warm them up); they give the stop and the exit, not the entry.`),
      S(sd.stop?.rule === "fixed" ? `Initial stop: ${sd.stop.pts} points below the entry premium, flat.` : sd.stop?.rule === "prev_choch"
        ? `Initial stop: the low of the option's latest CHoCH candle at or before the entry, less ${sd.stop.buffer_pct}% of that low. No CHoCH yet, or that level is not below the entry → the signal is skipped.`
        : "Initial stop: the option's latest confirmed swing low below the entry price. None → the signal is skipped."),
      ...(sd.two_lots ? [S(`TWO lots are bought: lot T1 (out at +${sd.two_lots.target_pts} points) and lot TRAIL (trailed).`)] : []),
      S("One trade a leg at a time.")]));
    else steps.push(S("Entry: Strategy 3 on the ARMED OPTION'S OWN 1-minute candles (not the straddle, not the futures).", [
      S(`The same structure rules run on the option's own candles (its ${spec.warmup_days} sessions before warm it up): swings, protected level, CHoCH, SETUP.`),
      S(sd.sides === "both" ? "The option's bullish SETUP → BUY it. Its bearish SETUP → SELL it." : "The option's bullish SETUP, after it was armed → BUY the option. Its bearish SETUPs are not traded."),
      S("Entry at that candle's close. One trade a leg at a time.")]));
    steps.push(S("Exit — on the option's own candles, first of:", [
      S(sd.stop?.rule === "prev_choch" || sd.stop?.rule === "fixed" ? "Stop: the level above — exits when touched (fill: the stop, or the open if the candle opens below it)."
                                       : "Stop: the option's latest confirmed swing low (long) / swing high (short) — exits when touched (fill: the stop, or the open if the candle gaps through it)."),
      ...(sd.two_lots ? [
        S(`Lot T1: target ${sd.two_lots.target_pts} points above the entry premium → out there (at the open if the candle opens above it). Its stop never moves.`),
        S(`Lot TRAIL: its stop stays at the first stop until the option has traded ${sd.two_lots.trail_after_pts} points above the entry. From then it sits at the level of the latest bullish BOS since the entry and follows every later BOS; it never moves back. An exit at a moved stop is shown as TRAIL.`),
        S("Within one candle the stop is checked before the target.")] : []),
      ...(sd.trail && !sd.two_lots ? [S(sd.trail === "bos_level"
        ? "The stop follows the BOS: each BOS of the option in the trade's direction moves the stop to the level that BOS broke (the swing high it took out, for a long), from the next candle. It never moves back. An exit at a moved stop is shown as TRAIL."
        : "The stop follows the BOS: each BOS of the option in the trade's direction moves the stop to the latest confirmed swing low (long) / high (short), from the next candle. It never moves back. An exit at a moved stop is shown as TRAIL.")] : []),
      S(sd.entry === "signal" ? "The option's next bearish CHoCH → exit at that candle's close." : "The option's next CHoCH → exit at that candle's close."),
      S(`${sqOf(p)}: still open → exit at that candle's close.`)]));
  }
  else if (rule === "straddle_v1" && sd.mode === "both_sides") steps.push(S("Entry: a SETUP on the derived straddle candles.", [setup,
    sd.real === "long" ? S("Bearish SETUP (the combined premium turning down) → NOTHING is sold: the short straddle is imaginary.")
                       : S("Bearish SETUP (the combined premium turning down) → SELL the CE and SELL the PE."),
    S(`Bullish SETUP (the combined premium turning up) → BUY ONE leg: the CE or the PE whose own close rose more over the last ${sd.lookback} candles.${sd.real === "long" ? "" : " A short still open is NOT bought back."}`),
    S(sd.real === "long" ? "The leg fills at its own candle close at that candle. One long at a time." : "Each leg fills at its own candle close at that candle. One entry a side at a time; a short entry and a long entry can be open together."),
    S(`Target, every leg: ${sd.target_pts} points on its own premium (${sd.real === "long" ? "" : `short: entry − ${sd.target_pts}; `}long: entry + ${sd.target_pts}), touched on the leg's own 1-minute candles → that leg exits there (at the open if the candle gaps through).`)]));
  else if (rule === "straddle_v1") steps.push(S("Entry: a SETUP on the derived straddle candles.", [setup,
    sd.mode === "rising_leg"
      ? S(`Bullish SETUP only (the combined premium turning up) → BUY ONE leg: the CE or the PE whose own close rose more over the last ${sd.lookback} candles. A bearish SETUP is not traded: it is the exit.`)
      : S("Bullish SETUP (the combined premium turning up) → BUY the CE and BUY the PE. Bearish SETUP → SELL the CE and SELL the PE. Each leg is its own position."),
    S("Each leg fills at its own candle close at the straddle's entry candle. One straddle trade at a time.")]));
  else if (rule === "htf_v1") {
    const h = spec.htf || {};
    steps.push(S("Entry: a SETUP is taken only in the higher-timeframe direction.", [setup,
      S(`Direction filter: run the same engine on ${TF[h.timeframe] || h.timeframe} candles (${h.warmup_sessions} sessions warm-up); the direction is ${h.mode === "trend" ? "its trend (changes only on a flipping CHoCH)" : "the latest 1-hour CHoCH"}, using only the higher-timeframe candles closed by the entry.`),
      S("If the SETUP agrees with that direction → enter; otherwise skip it. No direction yet → skip."), dirs]));
  } else if (rule === "fz_v1" || rule === "fz_v2") {
    steps.push(S(`Entry: each SETUP goes through the Foundation-Zone gate (${rule === "fz_v2" ? "rooms: bands the market sat in, retired when not visited" : "bands born at protected levels and cluster sits, never retired"}).`, [setup,
      S("TAKE (the zone card allows it: leave, first print or defend branch) → enter at the SETUP close, Foundation's own stop and exit."),
      S("WATCH → no position now; watch the band: after a confirmed leave that holds (R1–R5) and a SETUP that way, REENTER at that bar's close with an extra exit when price closes back through the band's middle."),
      S("BLOCK → skip (reason in the zone-gate ledger)."), dirs]));
  } else if (rule === "rl_v1") {
    const L = spec.rl || {};
    steps.push(S("Entry: a learner decides at every SETUP.", [setup,
      S(`Choice: skip, or one exit profile (${Object.keys(L.profiles || {}).join(" / ")}) × stop (${(L.stops_pts || []).join(" / ")} pts) × lots (${(L.lots || []).join(" / ")}) — Thompson sampling over a linear model of the SETUP's features.`),
      S(`Learning: after a position's exit candle closes, every action's outcome at that SETUP updates the model (reward: ${L.reward}). It learns from the first session of the data; a backtest is a window of that one run.`),
      S("One position per contract: a SETUP while one is open is skipped (locked).")]));
  } else if (rule === "c2c_v1") {
    const c = spec.c2c || {};
    steps.push(S(`Entry: buy one ${o.strike_default} put (nearest ${(o.expiry_types || []).join("/").toLowerCase()} expiry ≥ ${o.expiry_min_days} days out) when ALL hold on the same closed candle:`, [
      S("The structure is bearish: the last trend flip was down, and this is not the flip candle itself."),
      S(`A swing high confirms within ${c.band_pts} pts of the VWAP anchored at the peak before the break.`),
      S(`The close is above the session's first open − ${c.day_drop_pct}% (the day is not already falling hard).`),
      ...(c.pcr ? [S(`Window PCR (strikes within ${c.pcr.window_pts} pts of ATM) is below ${c.pcr.entry_max}.`)] : []),
      S("Then enter at the open of the put's next candle, same session; one position at a time."),
    ]));
  } else if (rule === "rainbow_v1") {
    const rb = spec.rainbow || {};
    steps.push(S(`Ribbon: ${rb.kind === "ema" ? `EMAs of ${(rb.periods || []).join(", ")}` : `${rb.levels} recursive SMA(${rb.period}) lines`} of the close; the band is the lowest to the highest line.`));
    steps.push(S(`Entry (between ${rb.entry_from} and ${rb.entry_until}): a candle closes outside the band when the previous one did not.`, [
      ...(rb.fan === "full" ? [S("The fan must be ordered that way (every faster line beyond the next slower one).")] : []),
      S(`The oscillator must be at least ${rb.osc_min} (lookback ${rb.lookback}) in the trade's direction.`),
      ...(rb.trigger === "pullback" ? [S(`Pullback: within the last ${rb.pullback_bars} candles price had already closed outside on that side, and the far edge kept its slope.`)] : []),
      S("Above the band → LONG, below → SHORT; enter at that close; one position per contract.")]));
  }
  if (spec.sma_filter) {                           // Strategy 32: each option leg checked against the option's own SMA
    const f = spec.sma_filter;
    steps[steps.length - 1].sub.push(S(`Trend filter, on the same option chart: its SMA ${f.period} at the entry candle versus the candle before — LONG needs it rising, SHORT needs it falling; otherwise the trade is not taken (listed with the reason). The SMA starts at the contract's first candle, so it exists from its 200th.`));
  }
  const skip = [S("The entry time is at or after the square-off time" + (p.square_off ? ` (${sqOf(p)})` : "") + "."),
                S("The same instrument (option strike + expiry + right, or the futures contract) already has an open position (strike lock)."),
                S("Options: no candle for the picked strike at the entry (strike from the index: " + (o.strike_default || "") + ", " + (o.expiry_types || []).join(" / ").toLowerCase() + " expiry ≥ " + (o.expiry_min_days ?? 1) + " day out).")];
  if (rule !== "c2c_v1") steps.push(S("A signal is not taken when:", skip));
  if (rule === "c2c_v1") {
    const c = spec.c2c || {};
    steps.push(S("Exit, checked on every candle of the put, first one wins:", [
      S(`Stop ${c.stop_pct}% below the entry premium, then trailing ${c.trail_pts} pts behind the peak premium (never lowered) — ${c.stop_fill === "close" ? "on a candle close" : "on a touch"}.`),
      S("The structure flips bullish → exit at that candle's close."),
      S(`At ${c.ladder?.time} once a session: up more than ${c.ladder?.profit_pct}%, down more than ${c.ladder?.loss_pct}%` + (c.pcr ? `, or window PCR above ${c.pcr.exit_above}` : "") + " → exit at the close."),
      S("The contract's last candle → expiry.")]));
  } else if (rule === "rl_v1") {
    const L = spec.rl || {};
    const prof = Object.entries(L.profiles || {}).map(([name, v]) => S(`${name}: ` +
      ((v.scale_out || []).map((x) => `1 lot out at ${x.target_r}R`).join(", ") || "no targets") +
      (v.trail ? `, the rest trails from ${v.trail.start_r}R, ${v.trail.lag_r}R behind` : "") +
      (v.square_off ? `, flat by ${v.square_off}` : ", held overnight") + "."));
    steps.push(S("Exit — managed with the stop and lots the learner chose (R = that stop in points); the stop at 1R exits every open lot, then per profile:",
      [...prof, S("The contract's last candle in the data → expiry.")]));
  } else if (p.exit === "position") {
    const so = (p.scale_out || []).map((x, i) => S(`Target ${i + 1}: ${x.lots} lot out at ${x.target_r != null ? x.target_r + "R" : "+" + x.target_pts + " pts"} (at the open if it gaps beyond; on a session's first candle only on its close).`));
    steps.push(S(`Exit — managed from the entry, ${p.lots} lot(s); R = ${p.stop?.futures_pts} pts on futures, ${p.stop?.option_pct}% of the premium on options. Every candle, in this order:`, [
      S("Stop at 1R against the entry → every open lot exits (at the open if it gaps through; a session's first candle at its close)."),
      ...so,
      ...(p.trail ? [S(`Trail: once ${p.trail.start_r}R is reached, the stop moves to (best R − ${p.trail.lag_r})R and only ever tightens, from the next candle.`)] : []),
      ...(p.reverse ? [S(`Stop and reverse: when the INITIAL stop is hit, open the opposite position at the stop (same lots and rules), at most ${p.reverse.max} time(s) per signal.`)] : []),
      ...(p.square_off ? [S(`${sqOf(p)}: whatever is still open closes (intraday).`)] : [S("No square-off: positions are held overnight (positional).")]),
      S("The contract's last candle in the data → expiry.")]));
  } else if (sd && sd.mode === "leg_structure") {      // its exits are listed with the entry above
  } else if (sd && sd.exit === "target_only") {
    steps.push(S("Exit — the target is the only exit:", [
      S(`A leg leaves when its own premium has moved ${sd.target_pts} points in its favour (the target above).`),
      S("No stop. No CHoCH exit. A SETUP of the other side does not close anything."),
      S(`${sqOf(p)}: a leg that has not reached its target is closed at that candle's close.`)]));
  } else if (sd && sd.mode === "managed_short") {      // its exits are the management step above
  } else {
    const sl = { prev_swing: "the latest confirmed swing low (long) / swing high (short)", choch_candle: "the CHoCH candle's low (long) / high (short)", none: "none" }[r.sl_rule] || r.sl_rule;
    steps.push(S(spec.straddle ? "Exit — read on the derived straddle candles, first of (each leg then fills at its own candle close):" : "Exit — first of:", [
      S(`Stop: ${sl}${r.sl_rule !== "none" ? " — exits when touched (fill: the stop, or the open if the candle gaps through it; a session's first candle fills at its close)" : ""}.`),
      S("The next CHoCH → exit at that candle's close."),
      ...(rule === "fz_v1" || rule === "fz_v2" ? [S("REENTER positions only: a close back through the band's middle → exit at that close.")] : []),
      ...(p.square_off ? [S(`${sqOf(p)}: still open → exit at that candle's close (intraday).`)] : [S("No square-off: held overnight (positional).")]),
      S("The contract's last candle in the data → expiry.")]));
  }
  if (spec.gap_reset) {                            // Strategy 66: the structure starts again on a gap day
    const k = steps.findIndex((x) => /^Market structure/.test(x.t));
    steps.splice(k < 0 ? 0 : k, 0, S(`Gap day: the session's first candle opens ${spec.gap_reset.pts} points or more above or below the previous session's last close → the structure is RESET.`, [
      S("Swings, protected level, trend, CHoCH / BOS and the AVWAP anchors of the earlier sessions are forgotten; everything is built again from the day's first candle."),
      S("Not a gap day → the structure carries over from the day before.")]));
  }
  const t = spec.types || {};
  steps.push(S(`Costs: slippage per side ${t.FUT?.slippage_pts ?? "–"} pts futures, ${t.OPT_FUT_SIGNAL?.slippage_pts ?? "–"} pts options; charges per the broker schedule (brokerage, STT, exchange, SEBI, stamp, GST); lot size ${spec.lot_size}.`));
  return steps;
}

export function algorithmHtml(spec) {
  const li = (s) => `<li>${esc(s.t)}${s.sub.length ? `<ol>${s.sub.map(li).join("")}</ol>` : ""}</li>`;
  return `<ol class="algo">${algorithm(spec).map(li).join("")}</ol>`;
}

// the sentence that says what a strategy does, built from its SPEC (rules + position)
export function rulesSentence(spec) {
  const r = spec.rules, p = spec.position || {};
  const parts = [];
  parts.push(`swings, CHoCH / BOS by ${r.break_mode}` + ((r.choch_mode || r.break_mode) !== r.break_mode ? ` (CHoCH by ${r.choch_mode})` : ""));
  parts.push(`AVWAP ${r.avwap_weight === "volume" ? "volume-weighted" : "equal-weighted"}`);
  if (r.entry_rule === "fz_v1" || r.entry_rule === "fz_v2") parts.push(`entries through the Foundation-Zone gate (${r.entry_rule === "fz_v2" ? "rooms" : "bands"})`);
  else if (r.entry_rule === "rl_v1") parts.push(`a learner (reward ${spec.rl?.reward}) picks skip or profile × stop (${(spec.rl?.stops_pts || []).join(" / ")} pts) × lots (${(spec.rl?.lots || []).join(" / ")})`);
  else if (r.entry_rule === "c2c_v1") parts.push(`buys the ${spec.options?.strike_default} put on a bearish flip + swing-high retest of the anchored VWAP (band ${spec.c2c?.band_pts} pts)`);
  else if (r.entry_rule === "rainbow_v1") parts.push(`a fresh close outside a ${spec.rainbow?.kind} ribbon (${spec.rainbow?.trigger}, fan ${spec.rainbow?.fan}, osc ≥ ${spec.rainbow?.osc_min})`);
  else parts.push("every SETUP is a position");
  if (p.exit === "position") {
    const so = (p.scale_out || []).map((s) => (s.target_r != null ? `${s.target_r}R` : `+${s.target_pts}`)).join(", ");
    parts.push(`managed: ${p.lots} lots, stop ${p.stop?.futures_pts} pts / ${p.stop?.option_pct}% premium = 1R` +
               (so ? `, targets ${so}` : "") + (p.trail ? `, trail from ${p.trail.start_r}R, ${p.trail.lag_r}R behind` : "") +
               (p.reverse ? `, stop and reverse ×${p.reverse.max}` : ""));
  } else if (r.entry_rule !== "c2c_v1" && r.entry_rule !== "rl_v1") {
    parts.push(`stop ${r.sl_rule.replace("_", " ")}, exit ${r.exit_rule.replace("_", " ")}`);
  }
  if (r.entry_rule === "c2c_v1") parts.push(`stop ${spec.c2c?.stop_pct}% then ${spec.c2c?.trail_pts}-pt trail, exit on a bullish flip or the ${spec.c2c?.ladder?.time} ladder`);
  parts.push(p.square_off ? `flat by ${sqOf(p)}` : "positional");
  parts.push(`warm-up ${spec.warmup_days} sessions`);
  return parts.join(" · ");
}
