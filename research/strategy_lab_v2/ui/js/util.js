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
export function algorithm(spec) {
  const r = spec.rules || {}, p = spec.position || {}, o = spec.options || {}, rule = r.entry_rule || "setup_v1";
  const TF = { minute: "1-minute", "3minute": "3-minute", "5minute": "5-minute", "15minute": "15-minute", "30minute": "30-minute", "60minute": "1-hour" };
  const by = (m) => (m === "close" ? "a candle closing beyond it" : "a candle touching it (high / low)");
  const S = (t, sub) => ({ t, sub: sub || [] });
  const steps = [];
  steps.push(S(`Candles: ${TF[spec.timeframe] || spec.timeframe} candles of the ${spec.underlying === "INDEX" ? "NIFTY index (AVWAP equal-weighted: the index has no volume)" : "near-month NIFTY futures"}; the first ${spec.warmup_days} session(s) only warm the indicators up.`));
  if (rule !== "rainbow_v1") steps.push(S("Market structure (Foundation engine), candle by candle:", [
    S(`Swing high / low: confirmed when a later candle breaks the swing candle's low / high — ${by(r.break_mode)}.`),
    S("Protected level: in an uptrend, the latest confirmed swing low that sat below the trend AVWAP; in a downtrend the mirror (swing high above it)."),
    S(`CHoCH: price breaks the protected level — ${by(r.choch_mode || r.break_mode)}. If it also breaks the trend AVWAP, the trend flips.`),
    S("BOS: price breaks the last swing high (uptrend) / swing low (downtrend) — trend continuation, no trade by itself."),
  ]));
  const setup = S("SETUP: after a CHoCH, both AVWAPs (anchored at the previous swing high and swing low) slope in the CHoCH's direction AND a candle closes beyond the CHoCH candle (above its high for a bullish CHoCH, below its low for a bearish one). The entry is that candle's close.");
  const dirs = S("Direction → position: bullish = futures LONG · options LONG CE and SHORT PE; bearish = futures SHORT · options LONG PE and SHORT CE (each option leg is its own position).");
  if (rule === "setup_v1") steps.push(S("Entry: every SETUP is a position.", [setup, dirs]));
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
  const skip = [S("The entry time is at or after the square-off time" + (p.square_off ? ` (${p.square_off})` : "") + "."),
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
      ...(p.square_off ? [S(`${p.square_off}: whatever is still open closes (intraday).`)] : [S("No square-off: positions are held overnight (positional).")]),
      S("The contract's last candle in the data → expiry.")]));
  } else {
    const sl = { prev_swing: "the latest confirmed swing low (long) / swing high (short)", choch_candle: "the CHoCH candle's low (long) / high (short)", none: "none" }[r.sl_rule] || r.sl_rule;
    steps.push(S("Exit — first of:", [
      S(`Stop: ${sl}${r.sl_rule !== "none" ? " — exits when touched (fill: the stop, or the open if the candle gaps through it; a session's first candle fills at its close)" : ""}.`),
      S("The next CHoCH → exit at that candle's close."),
      ...(rule === "fz_v1" || rule === "fz_v2" ? [S("REENTER positions only: a close back through the band's middle → exit at that close.")] : []),
      ...(p.square_off ? [S(`${p.square_off}: still open → exit at that candle's close (intraday).`)] : [S("No square-off: held overnight (positional).")]),
      S("The contract's last candle in the data → expiry.")]));
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
  parts.push(p.square_off ? `flat by ${p.square_off}` : "positional");
  parts.push(`warm-up ${spec.warmup_days} sessions`);
  return parts.join(" · ");
}
