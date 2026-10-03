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
