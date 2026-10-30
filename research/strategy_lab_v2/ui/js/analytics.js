// Strategy lab v2 — pure analytics behind the analytics tabs (no DOM, testable in node).
// Every metric is a port of the v1 dashboard (research/strategy_lab/dashboard.tpl); the v1 line it follows is noted.

// ---------------------------------------------------------------- formatting
export const inr = v => v == null || isNaN(v) ? '—' : (v < 0 ? '−₹' : '₹') + Math.abs(Math.round(v)).toLocaleString('en-IN');
export const inrk = v => v == null ? '—' : (v < 0 ? '−₹' : '₹') + (Math.abs(v) >= 1e5 ? (Math.abs(v) / 1e5).toFixed(2) + 'L'
  : Math.abs(v) >= 1e3 ? (Math.abs(v) / 1e3).toFixed(1) + 'k' : Math.round(Math.abs(v)));
export const fmt = (v, d = 1) => v == null || isNaN(v) ? '—' : (v > 0 ? '+' : '') + (+v).toFixed(d);
export const pct = v => v == null || isNaN(v) ? '—' : (v * 100).toFixed(1) + '%';
export const cl = v => v > 0 ? 'pos' : v < 0 ? 'neg' : '';
export const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
export const sum = (a, f) => a.reduce((s, t) => s + f(t), 0);
export const tsOf = s => Date.parse(String(s).replace(' ', 'T') + 'Z') / 1000;          // 'YYYY-MM-DD HH:MM:SS' -> epoch s (wall clock as UTC)
export const isoOf = t => new Date(t * 1000).toISOString().slice(0, 19).replace('T', ' ');
export const TFS = { minute: '1m', '3minute': '3m', '5minute': '5m', '10minute': '10m', '15minute': '15m', '30minute': '30m', '60minute': '1h', day: '1d' };

// ---------------------------------------------------------------- trades
// result.trades rows (arrays) -> objects; missing columns read as null
export function tradesOf(cols, rows) {
  const ix = Object.fromEntries((cols || []).map((k, i) => [k, i]));
  const g = (r, k) => ix[k] == null ? null : r[ix[k]];
  return (rows || []).map(r => {
    const et = g(r, 'entry_time'), xt = g(r, 'exit_time');
    return {
      pos: g(r, 'position') || 'LONG', otype: g(r, 'opt_type') || 'FUT', instr: g(r, 'instrument') || '', strike: g(r, 'strike'),
      exp: g(r, 'expiry'), sig: g(r, 'signal') || '', cht: g(r, 'choch_time'), et, ep: g(r, 'entry_px'), sl: g(r, 'sl'), xt, xp: g(r, 'exit_px'),
      why: g(r, 'exit_reason') || '', pts: g(r, 'pts') ?? 0, gross: g(r, 'gross') ?? 0, chg: g(r, 'charges') ?? 0, net: g(r, 'net') ?? 0,
      open: !!g(r, 'open'), lots: g(r, 'lots') || 1, tranche: g(r, 'tranche') || '', ue: g(r, 'und_entry'), ux: g(r, 'und_exit'),
      stale: g(r, 'stale'), mfe: g(r, 'mfe') ?? 0, mae: g(r, 'mae') ?? 0, scan: g(r, 'scan') || '', kind: g(r, 'kind'), cb: g(r, 'chg_parts'),
      ets: tsOf(et), xts: tsOf(xt),
    };
  });
}

// the run parameters, from the result body when it carries them, else from the SPEC
export function paramsOf(ctx) {
  const s = ctx.spec || {}, r = ctx.result || {}, pos = s.position || {};
  return {
    lot: r.lot_size ?? s.lot_size ?? 1,
    slip: r.slippage_pts ?? ((s.types || {})[ctx.type] || {}).slippage_pts ?? 0,
    capital: r.capital || s.capital || {},
    L: pos.lots || 1,                                   // lots a position opens with (v1 LOTS)
    managed: pos.exit === 'position',                   // v1 MANAGED
    type: ctx.type,
  };
}

// v1 statsOf (L609)
export function statsOf(T) {
  const net = T.map(t => t.net); let eq = 0, pk = 0, dd = 0;
  for (const v of net) { eq += v; pk = Math.max(pk, eq); dd = Math.min(dd, eq - pk); }
  const n = net.length, m = n ? net.reduce((a, b) => a + b, 0) / n : 0, sd = n > 1 ? Math.sqrt(net.reduce((a, v) => a + (v - m) ** 2, 0) / (n - 1)) : 0;
  const wins = net.filter(v => v > 0), loss = net.filter(v => v <= 0), sl = loss.reduce((a, b) => a + b, 0);
  return {
    trades: n, wins: wins.length, pts: sum(T, t => t.pts), gross_inr: sum(T, t => t.gross), charges_inr: sum(T, t => t.chg),
    net_inr: net.reduce((a, b) => a + b, 0), max_dd_inr: dd,
    pf: loss.length && sl ? +(wins.reduce((a, b) => a + b, 0) / -sl).toFixed(2) : null,
    t_stat: sd ? +(m / (sd / Math.sqrt(n))).toFixed(2) : null, mean: m, sd,
  };
}

// ---------------------------------------------------------------- repricing (port of core.trade_charges / price_trade)
export function tradeCharges(cs, buyPx, sellPx, qty) {
  const buy = buyPx * qty, sell = sellPx * qty, p = (v, x) => v * (x || 0) / 100;
  const brokerage = cs.brokerage_flat ? 2 * cs.brokerage_flat
    : Math.min(p(buy, cs.brokerage_pct), cs.brokerage_cap) + Math.min(p(sell, cs.brokerage_pct), cs.brokerage_cap);
  const stt = p(buy, cs.stt_buy_pct) + p(sell, cs.stt_sell_pct), exchange = p(buy + sell, cs.exchange_pct), sebi = p(buy + sell, cs.sebi_pct);
  const stamp = p(buy, cs.stamp_buy_pct), gst = p(brokerage + exchange + sebi, cs.gst_pct);
  return { brokerage, stt, exchange, sebi, stamp, gst, total: brokerage + stt + exchange + sebi + stamp + gst };
}
// one trade at slippage `slip` pts per side: {pts, gross, chg, net}
export function reprice(t, cs, lot, slip) {
  const qty = (t.lots || 1) * lot;
  let buy, sell;
  if (t.pos === 'SHORT') { sell = t.ep - slip; buy = t.xp + slip; } else { buy = t.ep + slip; sell = t.xp - slip; }
  const pts = sell - buy, gross = pts * qty, chg = tradeCharges(cs, buy, sell, qty).total;
  return { pts, gross, chg, net: gross - chg };
}
// self-test: at the run's own slippage the repriced net equals the stored net (to the paisa); returns the mismatches
export function repriceCheck(T, cs, lot, slip) {
  const bad = T.filter(t => t.ep != null && t.xp != null && Math.abs(Math.round(reprice(t, cs, lot, slip).net * 100) - Math.round(t.net * 100)) > 1);
  return bad;
}

// ---------------------------------------------------------------- sessions and time
const weekdays = (a, b) => {
  const out = [];
  for (let d = new Date(a + 'T00:00:00Z'), e = new Date(b + 'T00:00:00Z'); d <= e; d.setUTCDate(d.getUTCDate() + 1))
    if (d.getUTCDay() % 6) out.push(d.toISOString().slice(0, 10));
  return out;
};
// the backtest's sessions. v1 read them from the chart chunks; v2 has no charts here, so: every day the run saw a candle event
// (a CHoCH, a SETUP, a trade, a skipped SETUP, an FZ ledger row) inside the window; with no signal list (standalone options)
// the window's weekdays up to the last trade (exchange holidays then count as sessions — flagged by `approx`).
export function sessionsOf(ctx, T) {
  const r = ctx.result || {}, run = ctx.run || {};
  const from = r.date_from || run.date_from || null, to = r.date_to || run.date_to || null;
  const inWin = d => (!from || d >= from) && (!to || d <= to);
  const days = new Set();
  for (const g of r.signals || []) { if (g.time) days.add(g.time.slice(0, 10)); if (g.setup) days.add(g.setup.slice(0, 10)); }
  const fromSignals = days.size > 0;
  for (const x of r.skipped || []) if (x.entry_time) days.add(x.entry_time.slice(0, 10));
  const L = r.fz && r.fz.ledger; if (L) { const i = L.cols.indexOf('time'); if (i >= 0) L.rows.forEach(x => x[i] && days.add(String(x[i]).slice(0, 10))); }
  let list = [...days].filter(inWin);
  let approx = false;
  if (!fromSignals && from) {
    // weekdays from the window start to the last day anything happened (the data can end before the window does)
    const seen = [...list, ...T.map(t => t.xt.slice(0, 10))].sort(), last = seen.length ? seen[seen.length - 1] : to;
    if (last) { list = weekdays(from, to && last > to ? to : last); approx = true; }
  }
  const set = new Set(list);
  for (const t of T) { set.add(t.et.slice(0, 10)); set.add(t.xt.slice(0, 10)); }   // a trade's days always count
  return { list: [...set].sort(), approx };
}
const hm = s => +s.slice(11, 13) * 60 + +s.slice(14, 16);
// v1 tradeMin (L614): trading minutes held, 09:15–15:30 sessions
export function tradeMin(t, sess) {
  const d0 = t.et.slice(0, 10), d1 = t.xt.slice(0, 10);
  if (d0 === d1) return hm(t.xt) - hm(t.et);
  const between = sess.filter(d => d > d0 && d < d1).length;
  return (930 - hm(t.et)) + 375 * between + (hm(t.xt) - 555);
}
// v1 dailySeries (L853): net by exit day over every session (0 on a session without exits)
export function dailySeries(T, sess) { const by = {}; T.forEach(t => { const d = t.xt.slice(0, 10); by[d] = (by[d] || 0) + t.net; }); return sess.map(d => by[d] || 0); }
export function streaks(T) { let w = 0, l = 0, mw = 0, ml = 0; for (const t of T) { if (t.net > 0) { w++; l = 0; } else { l++; w = 0; } mw = Math.max(mw, w); ml = Math.max(ml, l); } return [mw, ml]; }
// ISO week key (v1 wkKey)
export const weekKey = x => {
  const d = new Date(x.slice(0, 10) + 'T00:00:00Z'), y = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 4 - (d.getUTCDay() || 7)));
  return y.getUTCFullYear() + '-' + Math.ceil(((y - new Date(Date.UTC(y.getUTCFullYear(), 0, 1))) / 864e5 + 1) / 7);
};

// ---------------------------------------------------------------- capital and R
// v1 capitalFor (L618): futures -> futures margin × lots; options with any short -> short-option margin × lots;
// long-only options -> average premium paid per position × lots
export function capitalFor(T, P) {
  const L = P.L, per = L > 1 ? ` × ${L} lots` : ' per lot', fm = P.capital.futures_margin, om = P.capital.short_option_margin;
  if (P.type === 'FUT') return fm ? { cap: fm * L, how: `futures margin ₹${(fm / 1e5).toFixed(1)}L${per}` } : { cap: 0, how: 'futures margin not set' };
  if (T.some(t => t.pos === 'SHORT')) return om ? { cap: om * L, how: `short-option margin ₹${(om / 1e5).toFixed(1)}L${per}` } : { cap: 0, how: 'short-option margin not set' };
  const prem = T.length ? sum(T, t => t.ep * P.lot) / T.length * L : 0;
  return { cap: prem, how: `average premium paid ${inr(prem)} per position${L > 1 ? ` (${L} lots)` : ''}` };
}
// v1 riskPts (L623): R needs the stop in the traded instrument; options via futures carry the futures stop unless managed
export const riskPts = (t, P) => ((P.type === 'OPT_FUT_SIGNAL' && !P.managed) || t.sl == null || t.ep == null) ? null : Math.abs(t.ep - t.sl) || null;
export const rMultiples = (T, P) => T.map(t => { const rp = riskPts(t, P); return rp ? t.pts / rp : null; }).filter(v => v != null);

// ---------------------------------------------------------------- curves and drawdowns
// cumulative net by exit time; trades exiting on the same second are merged (strictly increasing times)
export function curve(T) {
  const agg = new Map(); T.forEach(t => agg.set(t.xts, (agg.get(t.xts) || 0) + t.net));
  let c = 0; return [...agg.keys()].sort((a, b) => a - b).map(x => ({ time: x, value: Math.round(c += agg.get(x)) }));
}
export function underwater(d) { let pk = 0; return d.map(p => { pk = Math.max(pk, p.value); return { time: p.time, value: p.value - pk }; }); }
// v1 ddEpisodes (L894), deepest first
export function ddEpisodes(T) {
  const d = curve(T), out = []; let pk = 0, pkT = null, ep = null;
  for (const p of d) {
    if (p.value >= pk) { if (ep) { ep.recovered = p.time; out.push(ep); ep = null; } pk = p.value; pkT = p.time; }
    else if (!ep) ep = { start: pkT, bottom: p.time, depth: p.value - pk, recovered: null };
    else if (p.value - pk < ep.depth) { ep.depth = p.value - pk; ep.bottom = p.time; }
  }
  if (ep) out.push(ep); return out.sort((a, b) => a.depth - b.depth);
}

// ---------------------------------------------------------------- Monte Carlo (v1 L919-947, same seed and draw order)
export function prng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const qs = (b, p) => b[Math.min(b.length - 1, Math.max(0, Math.floor(p * (b.length - 1))))];   // b sorted ascending
export const q = (a, p) => qs([...a].sort((x, y) => x - y), p);
export function pathStats(arr, cap, ruin) {
  let c = 0, pk = 0, dd = 0, ls = 0, cs = 0, hit = false;
  for (const v of arr) { c += v; pk = Math.max(pk, c); dd = Math.min(dd, c - pk); if (v <= 0) { cs++; ls = Math.max(ls, cs); } else cs = 0; if (cap && c <= -ruin * cap) hit = true; }
  return { final: c, dd, ls, hit };
}
// net: per-trade net; stressNets: {label: per-trade net array at a repriced slippage}; returns every number the tab shows
export function monteCarlo(net, cap, ruin, stressNets, N = 2000, seed = 20260927) {
  const rnd = prng(seed), n = net.length;
  const shuffle = a => { const b = [...a]; for (let i = b.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; } return b; };
  const boot = a => a.map(() => a[Math.floor(rnd() * a.length)]);
  const sh = [], bs = [], paths = [], means = [];
  for (let k = 0; k < N; k++) {
    const a = shuffle(net); sh.push(pathStats(a, cap, ruin)); if (k < 400) { let c = 0; paths.push(a.map(v => c += v)); }
    const b = boot(net); bs.push(pathStats(b, cap, ruin)); means.push(b.reduce((x, y) => x + y, 0) / n);
  }
  // fan: per trade number, the 5/25/50/75/95% of the first 400 shuffled paths (one sort per step)
  const P5 = [.05, .25, .5, .75, .95], fan = P5.map(() => []), col = new Float64Array(paths.length);
  for (let i = 0; i < n; i++) { for (let k = 0; k < paths.length; k++) col[k] = paths[k][i]; col.sort(); P5.forEach((p, j) => fan[j].push(qs(col, p))); }
  // stress: skip a share of trades at random, or reprice at extra slippage (v1 subtracted 2·slip·lot; here every trade is repriced)
  const stress = (arr, skip) => { const res = []; for (let k = 0; k < N; k++) { let s = 0; for (const v of arr) if (rnd() >= skip) s += v; res.push(s); } return res; };
  const rows = [['As tested', net, 0], ['Skip 10% of trades', net, .1], ['Skip 20% of trades', net, .2],
    ...Object.entries(stressNets).map(([l, a]) => [l, a, 0])].map(([l, a, sk]) => { const r = stress(a, sk).sort((x, y) => x - y); return [l, qs(r, .5), qs(r, .05), r.filter(x => x < 0).length / N]; });
  const shDD = sh.map(x => x.dd).sort((a, b) => a - b), shLS = sh.map(x => x.ls).sort((a, b) => a - b), bsF = bs.map(x => x.final).sort((a, b) => a - b), mS = means.sort((a, b) => a - b);
  return {
    n, N, fan, actualDD: pathStats(net).dd,
    ddMedian: qs(shDD, .5), dd95: qs(shDD, .05), lsMedian: qs(shLS, .5), ls95: qs(shLS, .95),
    final5: qs(bsF, .05), final50: qs(bsF, .5), final95: qs(bsF, .95), pLoss: bs.filter(x => x.final < 0).length / N,
    expLo: qs(mS, .025), expHi: qs(mS, .975), stress: rows,
    ruinShuffle: sh.filter(x => x.hit).length / N, ruinBoot: bs.filter(x => x.hit).length / N,
  };
}

// ---------------------------------------------------------------- grouping helpers
export function groupBy(T, keyOf) { const g = {}; T.forEach(t => (g[keyOf(t)] ??= []).push(t)); return g; }
export const entryBucket = t => { const h = t.et.slice(11, 16); return h < '10:30' ? '09:15–10:30' : h < '12:00' ? '10:30–12:00' : h < '13:30' ? '12:00–13:30' : '13:30–15:30'; };
