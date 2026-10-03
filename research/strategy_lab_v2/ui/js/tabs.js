// Strategy lab v2 — the analytics tabs below a result (ports of the v1 dashboard tabs, research/strategy_lab/dashboard.tpl).
//   tabsFor(ctx)            -> [{id, label}] available for this ctx, in display order
//   renderTab(id, el, ctx)  -> renders one tab into el (disposes the charts this module made last time)
import {
  inr, inrk, fmt, pct, cl, esc, sum, isoOf, TFS, tradesOf, paramsOf, statsOf, reprice, repriceCheck, sessionsOf, tradeMin,
  dailySeries, streaks, weekKey, capitalFor, rMultiples, curve, underwater, ddEpisodes, monteCarlo, groupBy, entryBucket,
} from './analytics.js';
import { algorithmHtml } from './util.js';

// ---------------------------------------------------------------- tab list
const TABS = [['performance', 'Performance'], ['cumulative', 'Cumulative P&L'], ['drawdowns', 'Drawdowns'], ['distribution', 'Distribution'],
  ['montecarlo', 'Monte Carlo'], ['robustness', 'Robustness'], ['breakdown', 'Breakdown'], ['daily', 'Daily P&L'], ['signals', 'Signals'],
  ['zonegate', 'Zone gate'], ['journal', 'Journal'], ['config', 'Config'], ['rules', 'Rules']];
export function tabsFor(ctx) {
  const r = (ctx && ctx.result) || {};
  return TABS.filter(([id]) => id === 'zonegate' ? !!r.fz : id === 'journal' ? !!r.rl : true).map(([id, label]) => ({ id, label }));
}

// ---------------------------------------------------------------- theme + charts
let charts = [];
function dispose() { for (const c of charts) { try { c.remove(); } catch (e) { /* already gone */ } } charts = []; }
let probe = null;
// any CSS colour -> a form lightweight-charts parses (hex / rgba); it cannot read hsl()
function norm(c, fallback) {
  try { probe ??= document.createElement('canvas').getContext('2d'); probe.fillStyle = fallback; probe.fillStyle = c || fallback; return probe.fillStyle; }
  catch (e) { return fallback; }
}
function alpha(c, a) {
  const h = norm(c, '#888888');
  if (h[0] === '#') { const n = parseInt(h.slice(1), 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; }
  const m = h.match(/[\d.]+/g); return m ? `rgba(${m[0]},${m[1]},${m[2]},${a})` : h;
}
function theme() {
  const s = getComputedStyle(document.documentElement), v = (k, f) => norm(s.getPropertyValue(k).trim(), f);
  return { bg: v('--bg', '#f4f5f7'), card: v('--card', '#ffffff'), ink: v('--ink', '#1c2230'), muted: v('--muted', '#6b7385'), line: v('--line', '#e3e6ec'),
    accent: v('--accent', '#2f6fed'), up: v('--up', '#12805c'), down: v('--down', '#c9372c'), warn: v('--warn', '#9a6700'), chip: v('--chip', '#eef1f6') };
}
function mkChart(el, { timeScale = {}, localization = {} } = {}) {
  const T = theme();
  const c = LightweightCharts.createChart(el, {
    autoSize: true, layout: { background: { type: 'solid', color: T.card }, textColor: T.muted, fontFamily: 'system-ui, sans-serif' },
    grid: { vertLines: { color: alpha(T.line, .6) }, horzLines: { color: alpha(T.line, .6) } }, rightPriceScale: { borderColor: T.line },
    timeScale: Object.assign({ timeVisible: true, borderColor: T.line, minBarSpacing: 0.001 }, timeScale),
    handleScroll: { mouseWheel: false }, handleScale: { mouseWheel: false },
    localization: Object.assign({ timeFormatter: t => isoOf(t).slice(5, 16), priceFormatter: v => inr(v) }, localization),
  });
  charts.push(c); return c;
}
const fit = c => requestAnimationFrame(() => { try { c.timeScale().fitContent(); } catch (e) { /* disposed */ } });

// ---------------------------------------------------------------- small html helpers
const tile = (l, v, sub, c) => `<div class="kpi"><div class="k">${l}</div><div class="v ${c || ''}">${v}</div>${sub ? `<div class="tb-s">${sub}</div>` : ''}</div>`;
const note = h => `<div class="tb-note">${h}</div>`;
const hint = h => `<p class="sub">${h}</p>`;
const kvTable = rows => `<div class="tb-x"><table class="tbl tb-kv">${rows.map(([k, v, c]) => `<tr><td class="l">${k}</td><td class="${c || ''}">${v}</td></tr>`).join('')}</table></div>`;
const kvCard = (h, rows, sub) => `<div class="card tb-card"><h3>${h}</h3>${sub ? hint(sub) : ''}${kvTable(rows)}</div>`;
// a table card: head = [labels], rows = [[cell...]] where a cell is a value or [value, class, title]
const td = (x, i) => Array.isArray(x) ? `<td class="${i ? '' : 'l '}${x[1] || ''}"${x[2] ? ` title="${esc(x[2])}"` : ''}>${x[0] ?? '—'}</td>` : `<td${i ? '' : ' class="l"'}>${x ?? '—'}</td>`;
const table = (head, rows, tall) => `<div class="tablewrap${tall ? ' tall' : ''}"><table class="tbl">${head ? `<thead><tr>${head.map((x, i) => `<th${i ? '' : ' class="l"'}>${x}</th>`).join('')}</tr></thead>` : ''}<tbody>${rows.map(r => `<tr>${r.map(td).join('')}</tr>`).join('')}</tbody></table></div>`;
const tcard = (h, head, rows, sub, tall) => `<div class="card tb-card"><h3>${h}</h3>${sub ? hint(sub) : ''}${table(head, rows, tall)}</div>`;
const pill = (txt, k) => `<span class="tb-pill tb-${k || 'grey'}">${txt}</span>`;
const money = v => [inr(v), cl(v)];
const fd = d => new Date(d + 'T00:00:00Z').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });

// ---------------------------------------------------------------- per-ctx preparation (cached on the rows array)
const prepCache = new WeakMap(), checked = new WeakSet();
function prep(ctx) {
  const key = ctx.rows || [], hit = prepCache.get(key);
  if (hit && hit.r === ctx.result && hit.run === (ctx.run || {}) && hit.spec === (ctx.spec || {})) return Object.assign(hit, { ctx });   // same data, fresh callbacks
  const r = ctx.result || {}, P = paramsOf(ctx), T = tradesOf(r.cols, ctx.rows || []), S = sessionsOf(ctx, T);
  // repricing self-test, once per result: at the run's own slippage the repriced net must equal the stored net
  if (r.trades && !checked.has(r) && r.charges) {
    checked.add(r);
    const bad = repriceCheck(tradesOf(r.cols, r.trades), r.charges, P.lot, P.slip);
    console.assert(!bad.length, `tabs: repricing differs from the stored net on ${bad.length} trade(s) of ${r.code} ${r.run} ${r.type} ${r.choice}`, bad.slice(0, 3));
  }
  const x = { ctx, r, P, T, sess: S.list, sessApprox: S.approx, spec: ctx.spec || {}, run: ctx.run || {} };
  prepCache.set(key, x); return x;
}
const SIDE = { all: 'Long + short', LONG: 'Long', SHORT: 'Short', CE: 'Long + short · CE', PE: 'Long + short · PE' };
const TYPE = { FUT: 'Futures', OPT_FUT_SIGNAL: 'Options (via futures)', OPT_NATIVE: 'Options (standalone)' };
const EXP = { W: 'Weekly', M: 'Monthly' };
const sideOf = (c, side) => !c ? null : side === 'all' || !side ? c : ({ LONG: c.long, SHORT: c.short, CE: c.ce, PE: c.pe })[side] || null;
const WHY = { stop_loss: 'Stop loss', next_choch: 'Next CHoCH', expiry: 'Expiry', open: 'Open at end', band_reclaim: 'Band reclaim', trail_stop: 'Trail stop', eod: 'End of day', band_exit: 'Band exit', choch: 'CHoCH' };
const sigName = (t, type) => !t.sig ? '—' : type === 'OPT_NATIVE' ? (t.sig === 'BULLISH' ? 'Bullish (option chart)' : 'Bearish (option chart)') : (t.sig === 'BULLISH' ? 'Future long' : 'Future short');
const holdOf = (run, spec) => run.holding || (spec.position && spec.position.square_off ? `intraday ${spec.position.square_off}` : 'positional');
const fewNote = n => n < 50 ? note(`Only ${n} trades — treat these ratios as indicative; a few trades move them a lot.`) : '';
const empty = el => { el.innerHTML = hint('No trades for this selection.'); };

// ================================================================ Performance (v1 renderPerf L855)
function performance(el, X) {
  const { T, P, sess } = X; if (!T.length) return empty(el);
  const s = statsOf(T), dly = dailySeries(T, sess), n = dly.length, mean = n ? dly.reduce((a, b) => a + b, 0) / n : 0;
  const sd = n > 1 ? Math.sqrt(dly.reduce((a, v) => a + (v - mean) ** 2, 0) / (n - 1)) : 0, dsd = n > 1 ? Math.sqrt(dly.reduce((a, v) => a + Math.min(v, 0) ** 2, 0) / (n - 1)) : 0;
  const { cap, how } = capitalFor(T, P), yrs = n / 252, annual = yrs ? s.net_inr / yrs : 0;
  const W = T.filter(t => t.net > 0), L = T.filter(t => t.net <= 0), aw = W.length ? sum(W, t => t.net) / W.length : 0, al = L.length ? sum(L, t => t.net) / L.length : 0, [mw, ml] = streaks(T);
  const mins = T.map(t => tradeMin(t, sess)), inMkt = sum(mins, x => x) / (n * 375 || 1);
  const share = k => { const g = {}; T.forEach(t => { const key = k(t.xt); g[key] = (g[key] || 0) + t.net; }); const v = Object.values(g); return v.length ? `${v.filter(x => x > 0).length} of ${v.length} (${Math.round(100 * v.filter(x => x > 0).length / v.length)}%)` : '—'; };
  const exR = rMultiples(T, P), slipCost = 2 * P.slip * P.lot * sum(T, t => t.lots);
  el.innerHTML = fewNote(T.length) + (X.sessApprox ? note('Sessions are the window\'s weekdays (no signal list for this type), so holidays count as flat days in the daily ratios.') : '') + `<div class="tb-grid">` +
    kvCard('Returns', [['Net P&L', inr(s.net_inr), cl(s.net_inr)], ['Gross P&L', inr(s.gross_inr), cl(s.gross_inr)], ['Charges', inr(-s.charges_inr), 'neg'], ['Slippage cost (already in P&L)', inr(-slipCost), 'neg'],
      ['Capital basis', how], ['Return on capital', cap ? pct(s.net_inr / cap) : '—', cl(s.net_inr)], ['Annualised return', cap && yrs ? pct(annual / cap) : '—', cl(annual)], ['Sessions in backtest', n]]) +
    kvCard('Risk-adjusted', [['Sharpe (daily, annualised)', sd ? (mean / sd * Math.sqrt(252)).toFixed(2) : '—'], ['Sortino', dsd ? (mean / dsd * Math.sqrt(252)).toFixed(2) : '—'], ['Calmar (annual ÷ max drawdown)', s.max_dd_inr < 0 ? (annual / -s.max_dd_inr).toFixed(2) : '—'],
      ['Max drawdown', inr(s.max_dd_inr), 'neg'], ['Max drawdown / capital', cap ? pct(s.max_dd_inr / cap) : '—', 'neg'], ['t-stat (per trade)', s.t_stat ?? '—'], ['Daily P&L volatility', inr(sd)]]) +
    kvCard('Trades', [['Expectancy', inr(s.mean), cl(s.mean)], ['Expectancy in R', exR.length ? fmt(exR.reduce((a, b) => a + b, 0) / exR.length, 2) + ' R' : '— (stop is on the futures)'], ['Win rate', s.trades ? pct(s.wins / s.trades) : '—'],
      ['Average win / loss', `${inr(aw)} / ${inr(al)}`], ['Payoff ratio (avg win ÷ avg loss)', al ? (aw / -al).toFixed(2) : '—'], ['Profit factor', s.pf ?? '—'], ['Largest win', inr(Math.max(0, ...T.map(t => t.net))), 'pos'], ['Largest loss', inr(Math.min(0, ...T.map(t => t.net))), 'neg']]) +
    kvCard('Streaks, time, consistency', [['Longest winning streak', mw + ' trades'], ['Longest losing streak', ml + ' trades'], ['Average holding time', `${Math.round(sum(mins, x => x) / T.length)} trading min`],
      ['Time in market', pct(inMkt)], ['Profitable days', share(x => x.slice(0, 10))], ['Profitable weeks', share(weekKey)], ['Profitable months', share(x => x.slice(0, 7))]]) + `</div>`;
}

// ================================================================ Cumulative P&L (v1 renderEquity L882)
function cumulative(el, X) {
  const { T, ctx } = X; if (!T.length) return empty(el);
  const C = theme();
  el.innerHTML = `<p class="sub" id="tb-eqhint"></p><div class="card tb-card tb-flush"><div class="tb-chart" style="height:300px"></div><div class="tb-chart tb-uw" style="height:140px"></div></div>`;
  const [e1, e2] = el.querySelectorAll('.tb-chart'), eq = mkChart(e1), uw = mkChart(e2);
  const lines = [['Total', T, C.ink, 2], ['Long', T.filter(t => t.pos === 'LONG'), C.up, 1], ['Short', T.filter(t => t.pos === 'SHORT'), C.down, 1]].filter(x => x[1].length);
  const leg = lines.map(([n, rs, c, w]) => {
    const d = curve(rs); eq.addLineSeries({ color: c, lineWidth: w, priceLineVisible: false, title: n }).setData(d);
    const last = d.length ? d[d.length - 1].value : 0; return `<span style="color:${c}">━</span> ${n} <b class="${cl(last)}">${inr(last)}</b>`;
  });
  uw.addAreaSeries({ lineColor: C.down, topColor: alpha(C.down, .05), bottomColor: alpha(C.down, .35), lineWidth: 1, priceLineVisible: false, title: 'Drawdown' }).setData(underwater(curve(T)));
  fit(eq); fit(uw);
  el.querySelector('#tb-eqhint').innerHTML = `Cumulative net P&L by exit time · ${SIDE[ctx.side] || ''} &nbsp; ${leg.join(' &nbsp; ')} &nbsp; · lower chart: drawdown from the running peak`;
}

// ================================================================ Drawdowns (v1 renderDD L898)
function drawdowns(el, X) {
  const { T, sess } = X, e = ddEpisodes(T).slice(0, 5), day = t => t ? isoOf(t).slice(0, 10) : null, dt = t => t ? isoOf(t).slice(0, 16) : 'start';
  const len = (a, b) => { const x = day(a) || sess[0], y = b ? day(b) : sess[sess.length - 1]; return sess.filter(d => d >= x && d <= y).length; };
  el.innerHTML = hint('The five deepest falls of cumulative net P&L from a previous peak (by trade exit).') +
    table(['#', 'Peak', 'Bottom', 'Recovered', 'Depth ₹', 'Length (sessions)'], e.length ? e.map((x, i) => [i + 1, dt(x.start), dt(x.bottom), x.recovered ? dt(x.recovered) : pill('not yet', 'open'), [inr(x.depth), 'neg'], len(x.start, x.recovered)]) : [['No drawdown.', '', '', '', '', '']]);
}

// ================================================================ Distribution (v1 renderDist L916, plain SVG)
function hist(vals, title, fmtX, C, bins = 12) {
  if (!vals.length) return `<div class="card tb-card"><h3>${title}</h3>${hint('No data.')}</div>`;
  let lo = Infinity, hi = -Infinity; for (const v of vals) { if (v < lo) lo = v; if (v > hi) hi = v; }
  const w = (hi - lo) / bins || 1, c = Array(bins).fill(0); vals.forEach(v => { c[Math.min(bins - 1, Math.floor((v - lo) / w))]++; });
  const mx = Math.max(...c), W = 340, H = 150;
  return `<div class="card tb-card"><h3>${title}</h3><svg class="tb-svg" viewBox="0 0 ${W} ${H + 24}" width="100%">` + c.map((n, i) => {
    const x = i * W / bins, h = n / mx * H, mid = lo + (i + .5) * w;
    return `<rect x="${x + 1}" y="${H - h}" width="${W / bins - 2}" height="${h}" fill="${mid >= 0 ? C.up : C.down}" opacity=".75"><title>${fmtX(lo + i * w)} to ${fmtX(lo + (i + 1) * w)}: ${n}</title></rect>`;
  }).join('') + `<text x="0" y="${H + 14}">${fmtX(lo)}</text><text x="${W}" y="${H + 14}" text-anchor="end">${fmtX(hi)}</text></svg></div>`;
}
function scatter(T, C) {
  if (!T.length) return '';
  const W = 340, H = 200, x0 = Math.min(-1, ...T.map(t => t.mae)), y1 = Math.max(1, ...T.map(t => t.mfe)), px = v => (v - x0) / (0 - x0) * (W - 30) + 25, py = v => H - v / y1 * (H - 10);
  return `<div class="card tb-card"><h3>Max profit vs max loss per trade</h3>${hint('x = worst the trade showed, y = best it showed (points). Green = closed in profit.')}<svg class="tb-svg" viewBox="0 0 ${W} ${H + 20}" width="100%"><line x1="25" y1="${H}" x2="${W}" y2="${H}" stroke="${C.line}"/><line x1="${W - 5}" y1="0" x2="${W - 5}" y2="${H}" stroke="${C.line}"/>` +
    T.map(t => `<circle cx="${px(t.mae)}" cy="${py(t.mfe)}" r="3" fill="${t.net > 0 ? C.up : C.down}" opacity=".7"><title>${t.et.slice(5, 16)} ${esc(t.instr)}: best +${t.mfe} / worst ${t.mae}, net ${inr(t.net)}</title></circle>`).join('') +
    `<text x="25" y="${H + 14}">${x0.toFixed(0)} pts</text><text x="${W - 5}" y="${H + 14}" text-anchor="end">0</text><text x="${W - 8}" y="10" text-anchor="end">+${y1.toFixed(0)}</text></svg></div>`;
}
function distribution(el, X) {
  const { T, P, sess } = X; if (!T.length) return empty(el);
  const C = theme(), R = rMultiples(T, P);
  el.innerHTML = `<div class="tb-grid">${hist(T.map(t => t.net), 'Net P&L per trade (₹)', v => inrk(v), C)}${R.length ? hist(R, 'R-multiple per trade', v => v.toFixed(1) + 'R', C)
    : `<div class="card tb-card"><h3>R-multiple per trade</h3>${hint('Not shown: the stop is on the futures, not on the traded option.')}</div>`}${scatter(T, C)}${hist(T.map(t => tradeMin(t, sess)), 'Holding time (trading minutes)', v => Math.round(v) + 'm', C)}</div>`;
}

// ================================================================ Monte Carlo (v1 renderMC L922)
const RUIN_KEY = 'lab2.ruin';
const loadRuin = () => { try { const v = +JSON.parse(localStorage.getItem(RUIN_KEY) || 'null'); return [.2, .3, .5].includes(v) ? v : .3; } catch (e) { return .3; } };
const saveRuin = v => { try { localStorage.setItem(RUIN_KEY, JSON.stringify(v)); } catch (e) { /* storage blocked */ } };
function montecarlo(el, X) {
  const { T, P, r } = X, n = T.length, C = theme();
  if (n < 5) { el.innerHTML = note('Too few trades for a Monte Carlo analysis.'); return; }
  const { cap, how } = capitalFor(T, P), ruin = loadRuin(), cs = r.charges;
  // slippage stress: every trade repriced at the run's slippage + 2 / + 5 pts per side (when the charge schedule is known)
  const stressNets = cs ? { '+2 pts slippage per side': T.map(t => reprice(t, cs, P.lot, P.slip + 2).net), '+5 pts slippage per side': T.map(t => reprice(t, cs, P.lot, P.slip + 5).net) } : {};
  const M = monteCarlo(T.map(t => t.net), cap, ruin, stressNets);
  const edge = M.expLo < 0 && M.expHi > 0 ? pill('not proven — range includes zero', 'open') : M.expHi <= 0 ? pill('negative', 'short') : pill('positive', 'long');
  el.innerHTML = (n < 50 ? note(`Only ${n} trades. Monte Carlo reshuffles these trades — it cannot add information they do not contain. Read the ranges as rough.`) : '') +
    `<div class="card tb-card"><h3>Trade-order shuffle: 2,000 random orderings of the same ${n} trades</h3>${hint('Percentile bands of cumulative net P&L by trade number (5 / 25 / 50 / 75 / 95%). Same final P&L, different paths — how rough the ride could have been.')}<div class="tb-chart" style="height:320px"></div></div><div class="tb-grid">` +
    kvCard('Drawdown and losing streaks (shuffle)', [['Max drawdown — actual', inr(M.actualDD), 'neg'], ['Max drawdown — median', inr(M.ddMedian), 'neg'], ['Max drawdown — 95% worst case', inr(M.dd95), 'neg'],
      ['Longest losing streak — median', M.lsMedian + ' trades'], ['Longest losing streak — 95% worst case', M.ls95 + ' trades']]) +
    kvCard('Bootstrap: trades resampled with replacement', [['Final net — 5% / median / 95%', `${inr(M.final5)} / ${inr(M.final50)} / ${inr(M.final95)}`], ['Probability of finishing below zero', pct(M.pLoss)],
      ['Expectancy per trade — 95% range', `${inr(M.expLo)} to ${inr(M.expHi)}`], ['Edge', edge]]) +
    tcard('Stress tests', ['', 'Median net', '5% worst', 'P(loss)'], M.stress.map(([l, md, w, pl]) => [l, money(md), money(w), pct(pl)]), cs ? '' : 'Slippage rows need the charge schedule, which this result does not carry.') +
    `<div class="card tb-card"><h3>Risk of ruin</h3><p class="sub">Chance the account falls by <select class="tb-ruin">${[.2, .3, .5].map(v => `<option value="${v}" ${v === ruin ? 'selected' : ''}>${v * 100}%</option>`).join('')}</select> of capital at any point. Capital: ${how}.</p>` +
    kvTable([['Shuffled orderings', cap ? pct(M.ruinShuffle) : '—'], ['Bootstrap samples', cap ? pct(M.ruinBoot) : '—']]) + `</div></div>`;
  el.querySelector('.tb-ruin').onchange = e => { saveRuin(+e.target.value); dispose(); montecarlo(el, X); };
  // the fan on a fake daily time axis: trade k sits at B + k days
  const B = 1600000000, ch = mkChart(el.querySelector('.tb-chart'), { timeScale: { timeVisible: false, tickMarkFormatter: t => String(Math.round((t - B) / 86400)) }, localization: { timeFormatter: t => 'trade ' + Math.round((t - B) / 86400) } });
  [[C.down, 1], [alpha(C.down, .5), 1], [C.ink, 2], [alpha(C.up, .5), 1], [C.up, 1]].forEach(([c, w], j) =>
    ch.addLineSeries({ color: c, lineWidth: w, priceLineVisible: false, lastValueVisible: false, title: ['5%', '25%', '50%', '75%', '95%'][j] })
      .setData(M.fan[j].map((v, i) => ({ time: B + (i + 1) * 86400, value: Math.round(v) }))));
  fit(ch);
}

// ================================================================ Robustness (v1 renderRobust L950; sensitivities by repricing every trade)
function robustness(el, X) {
  const { T, P, r, ctx, run } = X, cs = r.charges, s = statsOf(T), opt = ctx.type !== 'FUT';
  const at = slip => sum(T, t => reprice(t, cs, P.lot, slip).net);
  const slips = [...new Set([0, 1, 2, 5, 10, P.slip])].sort((a, b) => a - b);
  const slip = cs ? slips.map(x => [x, at(x)]) : [];
  const base = cs ? T.map(t => reprice(t, cs, P.lot, P.slip)) : [], g = sum(base, x => x.gross), c = sum(base, x => x.chg);
  const chg = cs ? [0, .5, 1, 1.5, 2].map(x => [x, g - x * c]) : [];
  const byM = groupBy(T, t => t.xt.slice(0, 7));
  const runs = (ctx.runs || []).filter(x => x.label === run.label && x.kind === run.kind && x.status === 'ok');
  const otherRows = runs.map(x => {
    const ty = (x.types || {})[ctx.type], c0 = ty && ty.status === 'ok' && ty.choices ? ty.choices[ctx.choice] : null, v = sideOf(c0, ctx.side);
    const tf = TFS[x.timeframe] || x.timeframe, design = x.timeframe === X.spec.timeframe;
    return [`${tf}${design ? ' (design)' : ''}${x.underlying === 'INDEX' ? ' · index' : ''}${x.holding ? ' · ' + esc(x.holding) : ''}${x.run === run.run ? ' · shown' : ''}`,
      [v ? inr(v.net_inr) + (c0 && c0.skipped ? '<span class="tb-warn" title="positions skipped for missing data">*</span>' : '') : '—', v ? cl(v.net_inr) : ''], v ? v.trades + ' trades' : ''];
  });
  const [ce, ck] = String(ctx.choice || '-').split('-');
  let html = (cs ? '' : note('This result carries no charge schedule, so the slippage and charges sensitivities cannot be repriced.')) + `<div class="tb-grid">` +
    (cs ? kvCard('Slippage sensitivity', slip.map(([x, v]) => [`${x} pts per side${x === P.slip ? ' (base)' : ''}`, inr(v), cl(v)]), `Net P&L with every trade repriced at a different slippage per side (base ${P.slip} pts); charges follow the new fill prices.`) +
      kvCard('Charges sensitivity', chg.map(([x, v]) => [`${x === 0 ? 'No charges' : x + '× charges'}${x === 1 ? ' (base)' : ''}`, inr(v), cl(v)]), 'Net P&L at different charge levels.') : '') +
    tcard('Month by month', ['Month', 'Trades', 'Net ₹', 'Win %'], Object.keys(byM).sort().map(k => { const a = byM[k], v = sum(a, t => t.net); return [k, a.length, money(v), Math.round(100 * a.filter(t => t.net > 0).length / a.length) + '%']; }), 'By exit month.') +
    tcard('Same rules on other timeframes', null, otherRows.length ? otherRows : [['No run of this backtest.', '', '']],
      `This backtest (${esc(run.label || '')}), ${SIDE[ctx.side] || ''}${opt ? `, ${EXP[ce] || ce} ${ck}` : ''}.${runs.length < 2 ? ' Only this timeframe has been run for this backtest.' : ''}`) + `</div>`;
  // expiry × strike: every choice of this type in this run; click applies it
  const ty = ((run.types || {})[ctx.type]) || {}, choices = ty.choices || {};
  if (opt && Object.keys(choices).length) {
    html += `<div class="card tb-card"><h3>Expiry × strike</h3>${hint('Every expiry and strike choice for this type and backtest. Click a row to apply it.')}<div class="tablewrap tall"><table class="tbl"><thead><tr><th class="l">Expiry</th><th class="l">Strike</th><th>Trades</th><th>Long ₹</th><th>Short ₹</th><th>L+S · CE ₹</th><th>L+S · PE ₹</th><th>Net ₹</th><th>PF</th></tr></thead><tbody>` +
      Object.entries(choices).map(([k, x]) => {
        const [e, st] = k.split('-'), m = v => `<td class="${cl(v && v.net_inr)}">${inr(v && v.net_inr)}</td>`;
        return `<tr class="click${k === ctx.choice ? ' sel' : ''}" data-c="${esc(k)}"><td class="l">${EXP[e] || e}</td><td class="l">${esc(st)}</td><td>${x.trades}${x.skipped ? `<span class="tb-warn" title="${x.skipped} skipped">*</span>` : ''}</td>${m(x.long)}${m(x.short)}${m(x.ce)}${m(x.pe)}<td class="${cl(x.net_inr)}">${inr(x.net_inr)}</td><td>${x.pf ?? '—'}</td></tr>`;
      }).join('') + `</tbody></table></div></div>`;
  }
  el.innerHTML = html;
  el.querySelectorAll('tr.click[data-c]').forEach(tr => tr.onclick = () => ctx.onPickChoice && ctx.onPickChoice(tr.dataset.c));
}

// ================================================================ Breakdown (v1 renderBreakdown L715)
function breakdown(el, X) {
  const { T, ctx } = X; if (!T.length) return empty(el);
  const grp = (title, keyOf) => {
    const g = groupBy(T, keyOf);
    return tcard(title, ['', 'Trades', 'Win %', 'Net ₹', 'Avg ₹', 'Avg max profit', 'Avg max loss'], Object.keys(g).sort().map(k => {
      const a = g[k], n = sum(a, t => t.net);
      return [esc(k), a.length, Math.round(100 * a.filter(t => t.net > 0).length / a.length) + '%', money(n), money(n / a.length), [fmt(sum(a, t => t.mfe) / a.length), 'pos'], [fmt(sum(a, t => t.mae) / a.length), 'neg']];
    }));
  };
  el.innerHTML = `<div class="tb-grid">${grp('By position', t => t.pos === 'LONG' ? 'Long' : 'Short')}${grp('By signal', t => sigName(t, ctx.type))}${grp('By instrument', t => t.otype)}` +
    `${grp('By exit reason', t => WHY[t.why] || t.why)}${grp('By entry time', entryBucket)}${grp('By holding', t => t.et.slice(0, 10) === t.xt.slice(0, 10) ? 'Intraday' : 'Overnight')}</div>`;
}

// ================================================================ Daily P&L: heatmap calendar (v1 renderCalendar L664) + day table (v1 renderDaily L710)
let hmSel = null;
function daily(el, X) {
  const { T, sess, ctx } = X, C = theme(), by = groupBy(T, t => t.xt.slice(0, 10));
  if (!sess.length) return empty(el);
  const net = d => by[d] ? sum(by[d], t => t.net) : null, vals = sess.map(net).filter(v => v != null), mx = Math.max(1, ...vals.map(Math.abs));
  const A = [.3, .5, .75, 1], color = v => { const k = Math.min(4, Math.ceil(Math.abs(v) / mx * 4)) || 1; return alpha(v >= 0 ? C.up : C.down, A[k - 1]); };
  const D0 = new Date(sess[0] + 'T00:00:00Z'), start = new Date(D0); start.setUTCDate(D0.getUTCDate() - ((D0.getUTCDay() + 6) % 7));
  const end = new Date(sess[sess.length - 1] + 'T00:00:00Z'), set = new Set(sess), weeks = [];
  for (const d = new Date(start); d <= end; d.setUTCDate(d.getUTCDate() + 7)) weeks.push([0, 1, 2, 3, 4].map(i => { const x = new Date(d); x.setUTCDate(d.getUTCDate() + i); return x.toISOString().slice(0, 10); }));
  // a week is labelled with the month of its first session; labels closer than 3 columns are dropped
  const mon = k => new Date(k + 'T00:00:00Z').toLocaleDateString('en-GB', { month: 'short', timeZone: 'UTC' });
  let lastM = '', lastI = -9; const labels = [];
  weeks.forEach((w, i) => { const f0 = w.find(k => set.has(k)); if (!f0) return; const mk = f0.slice(0, 7); if (mk === lastM) return; lastM = mk; if (i - lastI < 3) return; lastI = i; labels.push([i, mon(f0)]); });
  const cells = [];
  for (const w of weeks) for (const k of w) {
    if (!set.has(k)) { cells.push('<div class="tb-hc tb-hx"></div>'); continue; }
    const v = net(k), n = by[k] ? by[k].length : 0;
    cells.push(`<div class="tb-hc${k === hmSel ? ' tb-sel' : ''}" data-d="${k}" style="${v != null ? 'background:' + color(v) : ''}" title="${new Date(k + 'T00:00:00Z').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })} · ${v == null ? 'no trades' : inr(v) + ' · ' + n + ' trade' + (n > 1 ? 's' : '')}"></div>`);
  }
  const days = sess.map(d => [d, net(d)]).filter(x => x[1] != null), pos = days.filter(x => x[1] > 0);
  const best = days.reduce((a, b) => !a || b[1] > a[1] ? b : a, null), worst = days.reduce((a, b) => !a || b[1] < a[1] ? b : a, null);
  let g = 0, rr = 0, mg = 0, mr = 0; for (const [, v] of days) { if (v > 0) { g++; rr = 0; } else { rr++; g = 0; } mg = Math.max(mg, g); mr = Math.max(mr, rr); }
  const tot = sum(days, x => x[1]), avg = days.length ? tot / days.length : 0;
  let dc = 0;
  const rows = Object.keys(by).sort().map(d => {
    const a = by[d], nt = sum(a, t => t.net), lg = sum(a.filter(t => t.pos === 'LONG'), t => t.net), sh = sum(a.filter(t => t.pos === 'SHORT'), t => t.net); dc += nt;
    return `<tr class="click" data-d="${d}"><td class="l">${d}</td><td>${a.length}</td><td class="${cl(lg)}">${inr(lg)}</td><td class="${cl(sh)}">${inr(sh)}</td><td class="${cl(nt)}">${inr(nt)}</td><td class="${cl(dc)}">${inr(dc)}</td></tr>`;
  }).join('');
  el.innerHTML = `<div class="card tb-card tb-cal"><div class="tb-hm"><div class="tb-hmhead"><b>Daily P&amp;L</b><span class="sub">by exit day · click a day to open it</span></div>
      <div class="tb-hmmon" style="width:${weeks.length * 15}px">${labels.map(([i, m]) => `<span style="left:${i * 15}px">${m}</span>`).join('')}</div><div class="tb-hmgrid">${cells.join('')}</div>
      <div class="tb-hmlegend">loss <i style="background:${alpha(C.down, 1)}"></i><i style="background:${alpha(C.down, .5)}"></i><i class="tb-h0"></i><i style="background:${alpha(C.up, .5)}"></i><i style="background:${alpha(C.up, 1)}"></i> profit · grey = session without trades${X.sessApprox ? ' (weekdays; holidays not known here)' : ''}</div></div>
    <div class="tb-hmstats"><div>Profitable days<b>${pos.length} of ${days.length}</b><small>${days.length ? Math.round(100 * pos.length / days.length) : 0}% of days with trades</small></div>
      <div>Average day<b class="${cl(avg)}">${inr(avg)}</b><small>net per day with trades</small></div>
      <div>Best day<b class="pos">${best ? inr(best[1]) : '—'}</b><small>${best ? fd(best[0]) : ''}</small></div>
      <div>Worst day<b class="neg">${worst ? inr(worst[1]) : '—'}</b><small>${worst ? fd(worst[0]) : ''}</small></div>
      <div>Longest streak<b><span class="pos">${mg} up</span> · <span class="neg">${mr} down</span></b><small>days in a row</small></div></div></div>` +
    hint('By exit day. Click a day to open it on the chart.') +
    `<div class="tablewrap tall"><table class="tbl"><thead><tr><th class="l">Day</th><th>Trades</th><th>Long ₹</th><th>Short ₹</th><th>Net ₹</th><th>Cum. net ₹</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  const open = d => { hmSel = d; el.querySelectorAll('.tb-hc.tb-sel').forEach(x => x.classList.remove('tb-sel')); const c = el.querySelector(`.tb-hc[data-d="${d}"]`); if (c) c.classList.add('tb-sel'); ctx.onOpenDay && ctx.onOpenDay(d); };
  el.querySelectorAll('.tb-hc[data-d]').forEach(c => c.onclick = () => open(c.dataset.d));
  el.querySelectorAll('tr.click[data-d]').forEach(tr => tr.onclick = () => open(tr.dataset.d));
}

// ================================================================ Signals (v1 renderSignals L720)
function signals(el, X) {
  const { r } = X, sig = r.signals || [], F = r.fz, fr = new Map(), GP = { TAKE: 'long', REENTER: 'long', WATCH: 'grey', BLOCK: 'short' };
  if (F && F.ledger) { const { cols, rows } = F.ledger, [iT, iR, iG, iOG] = ['time', 'read', 'gate', 'outcome_gate'].map(k => cols.indexOf(k)); rows.forEach(x => fr.set(x[iT], [x[iR], x[iG], iOG >= 0 ? x[iOG] : x[iG]])); }
  if (!sig.length) { el.innerHTML = hint(X.ctx.type === 'OPT_NATIVE' ? 'Options (standalone): the signals are on each day\'s option chart.' : 'No signals in this result.'); return; }
  // FZ: the card's read at the SETUP and the gate the SETUP ended with (the gate at its bar in the title)
  const fzc = g => { if (!F) return []; const z = g.setup && fr.get(g.setup); return z ? [z[0] || '—', [pill(z[2], GP[z[2]]), '', 'gate at the SETUP bar: ' + z[1]]] : ['', '']; };
  el.innerHTML = hint('Every CHoCH on the signal chart, the AVWAP pair it started, and the SETUP that followed.' + (F ? ' Read and Gate: the FZ card at that SETUP and what the gate did (details in the Zone gate tab).' : '')) +
    table(['CHoCH', 'Direction', 'Protected', 'AVWAP from SH', 'AVWAP from SL', 'SETUP', ...(F ? ['Read', 'Gate'] : [])],
      sig.map(g => [g.time.slice(5, 16), pill(g.dir === 'up' ? 'future long' : 'future short', g.dir === 'up' ? 'long' : 'short'), g.lvl ?? '—',
        g.hi ? g.hi[0].slice(5, 16) + ' @ ' + g.hi[1] : '—', g.lo ? g.lo[0].slice(5, 16) + ' @ ' + g.lo[1] : '—', g.setup ? g.setup.slice(5, 16) : pill('none'), ...fzc(g)]), true);
}

// ================================================================ Config (v1 renderConfig L728 + fzConfig)
function config(el, X) {
  const { r, P, spec, run, ctx } = X, ru = spec.rules || {}, pos = spec.position || {}, ty = (spec.types || {})[ctx.type] || {}, sch = r.charges, o = spec.options || {};
  const [ce, ck] = String(ctx.choice || '-').split('-');
  const tf = TFS[run.timeframe] || run.timeframe || '—';
  const posTxt = [`${pos.lots || 1} lot${(pos.lots || 1) > 1 ? 's' : ''}`, pos.lock ? 'lock ' + pos.lock : '', pos.exit === 'position' ? 'managed exit' : 'strategy exit',
    pos.stop ? `stop ${pos.stop.futures_pts ?? '—'} pts (futures) / ${pos.stop.option_pct ?? '—'}% of premium (options)` : '',
    ...(pos.scale_out || []).map((x, i) => `lot ${i + 1} out at ${x.target_r != null ? x.target_r + 'R' : '+' + x.target_pts + ' pts'}`),
    pos.trail ? `trail from ${pos.trail.start_r}R, ${pos.trail.lag_r}R behind` : '', pos.reverse ? 'stop and reverse' : ''].filter(Boolean).join(' · ');
  const rows = [['Showing', `${esc(spec.name || spec.code || '')} · ${TYPE[ctx.type] || ctx.type} · ${SIDE[ctx.side] || ctx.side}${ctx.type !== 'FUT' ? ` · ${EXP[ce] || ce} · strike ${esc(ck)}` : ''}`],
    ['Backtest', `${esc(run.label || '')} · ${r.date_from || run.date_from || '—'} → ${r.date_to || run.date_to || '—'} · ${tf}${run.timeframe === spec.timeframe ? ' (design timeframe)' : ''}${run.notes ? ' · ' + esc(run.notes) : ''}`],
    ['Code', esc(spec.code)], ['Holding', esc(holdOf(run, spec))], ['Signals on', run.underlying === 'INDEX' ? 'NIFTY index' : 'futures'],
    ['Break mode (swings, BOS)', esc(ru.break_mode ?? '—')], ['CHoCH mode', esc(ru.choch_mode ?? ru.break_mode ?? '—')], ['AVWAP weight', esc(ru.avwap_weight ?? '—')],
    ['Stop-loss rule', esc(ru.sl_rule ?? '—')], ['Entry rule', esc(ru.entry_rule ?? '—')], ['Exit rule', esc(ru.exit_rule ?? '—')], ['Position', esc(posTxt)],
    ['Warm-up (sessions)', spec.warmup_days ?? '—'], ['Slippage (pts/side)', P.slip], ['Lot size', P.lot],
    ['Futures margin / lot (₹)', P.capital.futures_margin != null ? inr(P.capital.futures_margin) : '—'], ['Short option margin / lot (₹)', P.capital.short_option_margin != null ? inr(P.capital.short_option_margin) : '—'],
    ['Charge schedule', esc(ty.charge_code || '—')]];
  if (ctx.type !== 'FUT' && o.strike_choices) rows.push(['Options', esc(`expiries ${(o.expiry_types || []).join(' / ')} · strikes ${o.strike_choices.join(' · ')} (default ${o.strike_default}) · ATR(${o.atr_period})${o.native_scan && ctx.type === 'OPT_NATIVE' ? ` · rescans ${o.native_scan.choices.join(' · ')} every ${o.native_scan.every_minutes} min` : ''}`)]);
  if (sch) rows.push(['Segment', esc(sch.segment || '—') + (sch.effective_from ? ` <span class="sub">· from ${esc(sch.effective_from)}</span>` : '')],
    ['Brokerage', sch.brokerage_flat ? '₹' + sch.brokerage_flat + ' flat per order' : sch.brokerage_pct + '% or ₹' + sch.brokerage_cap + ' per order'], ['STT', `${sch.stt_buy_pct}% buy · ${sch.stt_sell_pct}% sell`],
    ['Exchange', sch.exchange_pct + '%'], ['SEBI', sch.sebi_pct + '%'], ['Stamp', sch.stamp_buy_pct + '% buy'], ['GST', sch.gst_pct + '%'], ['Note', esc(sch.notes || '')]);
  let fzRows = '';
  const F = r.fz;
  if (F || spec.fz) {
    // every threshold of this timeframe's fz block as the strategy file states it, with its provenance; else the values the run used
    const blk = spec.fz && (spec.fz[run.timeframe] || spec.fz[spec.timeframe]), th = blk || (F && F.thresholds) || {};
    fzRows = `<div class="card tb-card"><h3>Foundation-Zone</h3>${hint(`entry rule ${esc(ru.entry_rule || '—')} · fz_hash ${esc((F && F.fz_hash) || '—')} · band memory from ${esc((F && F.memory_start) || '—')}${F && F.same_sample ? ` (${esc(F.same_sample)})` : ''} · thresholds for ${tf} candles`)}` +
      kvTable(Object.entries(th).map(([k, x]) => {
        const o2 = x && typeof x === 'object' && 'value' in x ? x : { value: x };
        return [esc(k), `${o2.value === null ? 'null' : esc(typeof o2.value === 'object' ? JSON.stringify(o2.value) : o2.value)}${o2.source ? ` <span class="sub">· ${esc(o2.source)}${o2.statistic ? ' · ' + esc(o2.statistic) : ''}${o2.note ? ' · ' + esc(o2.note) : ''}</span>` : ''}`];
      })) + `</div>`;
  }
  el.innerHTML = `<div class="card tb-card">${kvTable(rows)}</div>` + fzRows;
}

// ================================================================ Rules (v1 static cards L179, plus this strategy's own chain)
function rules(el, X) {
  const { spec, P } = X, ru = spec.rules || {}, pos = spec.position || {}, C = theme(), sw = (c, ch) => `<span class="tb-sw" style="color:${c}">${ch}</span>`;
  const slips = Object.entries(spec.types || {}).map(([k, v]) => `${TYPE[k] || k} ${v.slippage_pts} pt`).join(' · ');
  const chain = `swings (Pine port) → protected level (unbroken swing beyond the trend AVWAP) → CHoCH by ${esc(ru.choch_mode ?? ru.break_mode)}, BOS by ${esc(ru.break_mode)} → AVWAP pair from the previous SH and SL at each CHoCH → SETUP (both AVWAPs sloping with the CHoCH and a close beyond the CHoCH candle) → ` +
    (pos.exit === 'position' && pos.stop ? `managed exit: ${pos.lots} lots, stop ${pos.stop.futures_pts} pts (futures) / ${pos.stop.option_pct}% of premium (options) = 1R` + (pos.scale_out || []).map((x, i) => `, lot ${i + 1} out at ${x.target_r != null ? x.target_r + 'R' : '+' + x.target_pts}`).join('') +
      (pos.trail ? `, the rest trails from ${pos.trail.start_r}R (${pos.trail.lag_r}R behind the best R reached)` : '') + '; no CHoCH exit.' : `exit on stop loss (${esc(String(ru.sl_rule || '').replace('_', ' '))}) or the next CHoCH.`);
  const card = (h, items) => `<div class="card tb-card"><h3>${h}</h3><ul class="tb-ul">${items.map(x => `<li>${x}</li>`).join('')}</ul></div>`;
  const cards = [
    `<div class="card tb-card"><h3>This strategy — step by step</h3>${algorithmHtml(spec)}</div>`,
    card('Strategy, backtest, timeframe', ['<b>Strategy</b> — the engine and its rules. Each strategy runs only the backtests defined for it; a backtest the data cannot cover is refused with the reason.',
      '<b>Backtest period</b> — its own run over exactly its dates (plus warm-up). Presets count back from the latest data date; Design period = where the rules were built; Unseen test = dates the rules never saw.',
      '<b>Timeframe</b> — the design timeframe by default; the same rules can be run on other candles.']),
    card('Types and schemes', ['<b>Futures</b> — long on future long, short on future short. Schemes: long + short (total), long, short.',
      '<b>Options (via futures)</b> — the futures\' signals in options, 1 lot per signal. Long: CE on future long, PE on future short. Short: PE on future long, CE on future short. Long + short · CE / · PE: that option long on one signal, short on the other.',
      '<b>Options (standalone)</b> — the engine on each option\'s own chart. Long: bullish setups; short: bearish setups; long + short · CE / · PE: both directions on that chart.',
      'Expiry (weekly / monthly) and strike apply to both option types.']),
    card('Chart', [`${sw(C.up, '■')}SH / ${sw(C.down, '■')} SL; ▼ / ▲ confirming candle. Faded dots: unconfirmed candidate.`,
      `${sw(C.accent, '┅')}Protected level · ● CHoCH · ${sw(C.muted, '●')} BOS. Breaks by ${esc(ru.break_mode || 'touch')}.`,
      `${sw(C.warn, '━')}AVWAP from previous SH, ${sw(C.accent, '━')} from previous SL, started at each CHoCH.`]),
    card('Fills, costs, statistics', ['Entry at the SETUP candle close. Stop: worse of candle open and stop; on a session\'s first candle, that candle\'s close. Else exit at the next CHoCH close. A position open at the backtest\'s end is valued at its last candle (*).',
      `Slippage per side: ${slips || P.slip + ' pt'}. Charges per the charge schedule. Short option = sell at entry, buy at exit.`,
      'Capital per lot (for returns, Calmar, risk of ruin): futures and short options use the margins in Config; long-only options use the average premium paid.',
      'Monte Carlo: 2,000 simulations with a fixed seed. * = incomplete data (positions skipped for missing option candles).']),
  ];
  if (spec.fz || X.r.fz) cards.push(card('Foundation-Zone (Strategies 5–8)', [
    `<b>Bands</b> — ${sw(C.accent, '▮')}A: born when a swing becomes the protected level · ${sw(C.accent, '▮')} B: born when the last <code>cluster_bars</code> closes sit within <code>cluster_width</code>. ± <code>band_half_width</code> around the mid; a new band overlapping one enough merges into it; none is ever deleted (Strategies 5, 6). <b>Rooms</b> (Strategies 7, 8): born only from a sit, a sit inside a live room (or overlapping a room visited this session) is a visit of it, live rooms never overlap, a room with no close inside for <code>room_max_age_sessions</code> sessions is retired; named <code>&lt;letter&gt; &lt;mm-dd hh:mm&gt;</code>. Memory starts at the file's first session, so every window is a slice of one run.`,
    '<b>Card</b> (per bar, as-of) — the ref band whose visit is live, visit n, this and first visit bars and volume, and the read. A visit ends only on <code>leave_closes</code> closes in a row outside on one side. Reads in order: LEAVE of the band just left (for <code>leave_ttl_bars</code>) → HUNT (out and back in: one close on 1m, a deep wick on 5m) → REJECT (wick at an edge, close back toward the mid) → FIRST_PRINT (visit 1) / ACCEPTED (lived <code>accept_bars</code>, volume held) / THIN / RECYCLE → PENDING (first close outside) → NEW.',
    `<b>Gate</b> at each Foundation SETUP, first match: ${sw(C.down, 'B')}BLOCK (in a position, open time from <code>no_entry_from</code>, an opening bar piercing a band last visited on an earlier day, a SETUP in the pierce direction of a HUNT within <code>fade_block_bars</code>, NEW ground) · ${sw(C.accent, 'T')}TAKE (a LEAVE its way, a FIRST_PRINT in the entry direction, an ACCEPTED defend after a HUNT or REJECT at the opposite edge) · ${sw(C.muted, 'W')}WATCH on the band holding the close (on the band just left when the SETUP is its first close outside).`,
    `${sw(C.accent, 'R')}<b>REENTER</b> — a watch arms on a close beyond its band and re-enters on the bar where <code>leave_closes</code> closes are out, none came back inside or across the mid, far-side volume is at least the sit's (skipped when NA) and a Foundation SETUP points the same way on that bar or the one before; fill at that bar's close. A close back inside breaks the run and the next close beyond arms the watch again. A LEAVE TAKE of the band a watch waits on, in its direction, is that watch's REENTER; a FIRST_PRINT or defend TAKE stays a TAKE. Cancelled at the next session, by an opposite TAKE or LEAVE, or after <code>cancel_inside_bars</code> closes back inside.`,
    '<b>Exits</b> — TAKE is Foundation\'s own position. REENTER takes Foundation\'s stop at the fill bar and exits on the stop, then <b>band reclaim</b> (a close back past the band\'s mid), then the next CHoCH.',
    'Volume NA = not the front month or zero volume: R4, the HUNT burst and THIN are skipped and ACCEPTED is time-only. Clocks use the bar\'s open time; durations are bars; a visit carries across the overnight gap. Values and sources: Config tab; what the gate did: Zone gate tab.']));
  el.innerHTML = `<div class="tb-grid">${cards.join('')}</div>`;
}

// ================================================================ Zone gate (v1 renderFZ L768)
let fzGate = 'ALL';   // ledger filter: ALL or one gate
function zonegate(el, X) {
  const F = X.r.fz, run = X.run, ctx = X.ctx;
  if (!F) { el.innerHTML = hint('Not an FZ strategy. The Zone gate belongs to Strategies 5 to 8, which card every Foundation SETUP against a memory of price bands and gate it TAKE / WATCH / BLOCK, with REENTER after a confirmed leave of the band.'); return; }
  const s = F.stats || {}, c = F.control || {}, pm = F.permutation || {}, fl = F.flags || {}, w = s.watches || {}, p = s.positions || {}, GT = ['TAKE', 'REENTER', 'WATCH', 'BLOCK'], lg = F.legend || {};
  const thv = k => { const x = (F.thresholds || {})[k]; return x && typeof x === 'object' && 'value' in x ? x.value : x; };
  const kv = o => Object.entries(o || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join(' · ') || '—';
  const ord = (o, ks) => ks.filter(k => o && o[k] != null).map(k => `${k} ${o[k]}`).join(' · ') || '—';
  const by = (title, o, keys) => tcard(title, ['', ...GT, 'All'], (keys || Object.keys(o || {})).filter(k => o && o[k]).map(k => [esc(k), ...GT.map(g => o[k][g] || ''), Object.values(o[k]).reduce((a, b) => a + b, 0)]));
  // headline tiles: the control percentile always sits beside net (cost avoidance is not edge)
  const B = F.books || {}, bf = B.fz || {}, bw = B.raw || {}, h = F.headline || {}, ats = h.at_setup;
  const tiles = [tile('Foundation SETUPs', s.setups ?? '—', `ended TAKE ${h.take} · WATCH ${h.watch} · BLOCK ${h.block} · REENTER ${h.reenter}${ats ? ` (${ats.REENTER} of them at the SETUP bar)` : ''}`),
    tile('FZ positions', `${h.take_trades} + ${h.reenter_trades}`, `TAKE + REENTER · ${h.priced} priced`),
    tile('FZ net', inr(bf.net), `Foundation ${inr(bw.net)} in the same run`, cl(bf.net)),
    tile('Random control', c.fz_pct != null ? c.fz_pct.toFixed(1) + 'th pct' : '—', `session-matched · ${c.draws} draws`),
    tile('Kept vs refused', pm.p != null ? 'p ' + pm.p : '—', `mean <span class="${cl(pm.kept_mean)}">${inr(pm.kept_mean)}</span> vs <span class="${cl(pm.blocked_mean)}">${inr(pm.blocked_mean)}</span>`),
    tile('Sample', fl.pf_t ?? '—', `n ${fl.n}${fl.ci_inr != null ? ` · 95% CI ±${inr(fl.ci_inr)}` : ''}`)].join('');
  // gate × read: rows are SETUPs; BLOCK split by reason
  const gr0 = s.gate_read || {}, reads = (lg.read || []).filter(x => GT.some(g => (gr0[g] || {})[x])), grow = (lbl, o, n) => [lbl, ...reads.map(x => (o || {})[x] || ''), n];
  const gr = [...['TAKE', 'REENTER', 'WATCH'].map(g => grow(g, gr0[g], (s.gates || {})[g] || 0)),
    ...Object.entries(s.block_read || {}).map(([k, o]) => grow('BLOCK · ' + esc(k), o, Object.values(o).reduce((a, b) => a + b, 0))), grow('<b>All SETUPs</b>', s.reads_at_setup, s.setups)];
  const sb = p.reenter_sl_bar || {}, r4 = s.r4 || {}, ls = r4.leave_setups || {}, na = F.all_na || {}, lf = s.leave_far_side || {}, b1 = s.branch1 || {}, br = F.bridge || { lines: [] }, cd = s.card || {}, sm = cd.since_memory_start || {};
  const cells = [
    tcard('Watches', ['Outcome', 'Watches'], Object.entries(w.outcomes || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => [esc(k), v]),
      `${w.opened ?? 0} opened (${kv(w.kinds)}); ${w.armed ?? 0} armed${w.rearmed != null ? `, ${w.rearmed} re-armed (a close back inside breaks the far-side run; the next far close arms again)` : ''}. Armed watches that expired: median ${w.armed_bars_median ?? '—'} bars from the first arming${w.rearmed_bars_median != null ? `, ${w.rearmed_bars_median} from the latest` : ''}. Ended armed with R1–R4 met but no same-direction SETUP: ${w.no_same_dir_setup ?? 0}. REENTER held by the ${esc(thv('no_entry_from') ?? '—')} clock: ${w.clock_1520 ?? 0}. Refused at the fill: ${w.reenter_refused ?? 0}.`),
    tcard('Positions', null, [["TAKE (Foundation's own position)", p.TAKE], ['REENTER', p.REENTER], ...Object.entries(p.reenter_exits || {}).map(([k, v]) => ['REENTER exit · ' + esc(k), v]),
      ...Object.entries(p.reenter_fill || {}).map(([k, v]) => ['REENTER fill · ' + esc(k), v]), ['REENTER stop from the SETUP / fill bar', `${sb.setup || 0} / ${sb.fill || 0}`], ['REENTER stop inside the band', p.reenter_sl_in_band],
      ['LEAVE TAKE turned REENTER (a watch waited on the band left, same way)', p.reenter_converted_take], ['TAKE refused (stop)', p.take_refused]]),
    tcard('LEAVE into another band (TAKE branch 1)', ['leave_far_side', 'Branch-1 TAKEs'], ['any', 'block_list', 'no_band'].map(k => [k === lf.seeded ? `<b>${k}</b> (seeded)` : k, lf[k]]),
      `What each reading of a leave whose far side is another remembered band would TAKE on these rows (counted from the ledger's entered read; only the seeded one gated). Seeded branch-1 TAKEs ${b1.n ?? 0}: far side in no band ${b1.far_side_no_band ?? 0}, inside a band ${b1.far_side_in_band ?? 0} (entered visit_n median ${b1.in_band_visit_n_median ?? '—'}; by visit ${kv(b1.in_band_visit_n)}; entered read ${kv(b1.in_band_entered_read)}).`),
    tcard('Volume NA and R4', null, [['SETUPs whose visit volume is NA', `${s.vol_na} of ${s.setups}`], ["SETUPs whose band's first visit is NA", s.first_vol_na], ['ACCEPTED on time alone (volume NA)', s.accepted_time_only],
      ['R4 far-side bars evaluated / failed / NA', `${r4.bars_evaluated ?? 0} / ${r4.bars_fail ?? 0} / ${r4.bars_na ?? 0}`], ['LEAVE SETUPs by R4: NA / pass / fail', `${ls.none || 0} / ${ls.true || 0} / ${ls.false || 0}`]],
      `A bar is volume-NA when the file is not on the front month or its volume is 0; a visit is NA if any of its bars is. NA skips R4, the HUNT burst and THIN, and makes ACCEPTED time-only. All-NA comparator (volume NA on every bar, the like-for-like read across volume regimes): SETUPs by the gate they ended with ${ord(na.gates, GT)}; positions ${ord(na.positions, ['TAKE', 'REENTER'])}.`),
    tcard('Bridge: Foundation to FZ net', ['', 'n', '₹'], (br.lines || []).map(l => [['raw_net', 'fz_net'].includes(l.key) ? `<b>${esc(l.label)}</b>` : esc(l.label), l.n, money(l.value)]),
      `Foundation's net in this same run, plus what FZ avoided by not holding its other positions (their price move, then their charges and slippage), plus the REENTER exit difference, equals FZ net. Price lines <span class="${cl(br.selection)}">${inr(br.selection)}</span>, cost avoidance <span class="${cl(br.costs)}">${inr(br.costs)}</span>: with a losing Foundation book any gate that drops trades gains the costs, so judge the selection by the random control.`),
    tcard('Random control and kept vs refused', null, [['Random books (session-matched)', `${c.draws} × ${c.k} positions`], ['Random net · 5th percentile', money(c.p5)], ['Random net · median', money(c.p50)], ['Random net · 95th percentile', money(c.p95)],
      ['FZ net', money(c.fz_net)], ['FZ percentile among the random books', c.fz_pct != null ? c.fz_pct.toFixed(1) + 'th' : '—'], ['Random books that beat FZ', c.p_beat != null ? pct(c.p_beat) : '—'],
      ['Kept: Foundation trades on the SETUPs FZ traded (TAKE, or a REENTER on that SETUP)', pm.kept_n], ['Kept · mean', money(pm.kept_mean)], ['Refused: Foundation trades on the SETUPs FZ never traded', pm.blocked_n], ['Refused · mean', money(pm.blocked_mean)], ['Difference of means', money(pm.diff)], ['Permutation p (two-sided)', pm.p ?? '—']],
      `${esc(c.scheme)}; seed ${esc(c.seed)}${c.capped ? `; ${c.capped} positions capped` : ''}. The permutation shuffles the kept / refused labels ${pm.draws} times.`),
    tcard('Books and sample size', ['', 'FZ', 'Foundation'], [['Positions', bf.n, bw.n], ['Net', money(bf.net), money(bw.net)], ['Net without positions open at the end', money(bf.net_ex_open), money(bw.net_ex_open)],
      ['Mean per position', money(bf.mean), money(bw.mean)], ['SD per position', inr(bf.sd), inr(bw.sd)], ['Wins', bf.wins, bw.wins],
      ...[['Profit factor', 'pf'], ['t per position', 't_trade'], ['t per active session', 't_session']].map(([l, k]) => [l, fl.pf_t === 'not reported' ? 'not reported' : bf[k], bw[k]]),
      ['Sessions / weeks with a position', `${bf.sessions} / ${bf.weeks}`, `${bw.sessions} / ${bw.weeks}`], ['Open at the end', bf.open, bw.open],
      ['95% CI on the mean (₹ · pts)', bf.ci_inr != null ? `±${inr(bf.ci_inr)} · ±${bf.ci_pts}` : '—', bw.ci_inr != null ? `±${inr(bw.ci_inr)} · ±${bw.ci_pts}` : '—']],
      `Sample flags for the FZ book: PF / t ${fl.pf_t}, week stats ${fl.weeks}, Sharpe / Calmar ${fl.sharpe}. ${esc(fl.rule)}.`),
    tcard('Active sessions and dormant stretches', ['No Foundation SETUP', 'Sessions'], (s.dormant || []).map(([a, b, n]) => [a === b ? a : `${a} → ${b}`, n]),
      `Sessions with at least one Foundation SETUP: ${s.active_sessions} of ${s.sessions}. A dormant stretch is Foundation's silence, not FZ's selectivity.`),
    by('Gate by hour (bar open time)', s.by_hour, lg.hour_bins), by('Gate by visit_n', s.by_visit, ['1', '2', '3', '4+', 'none']), by('Gate by direction', s.by_dir, ['up', 'down']),
    by('Gate by zone kind (A protected level · B cluster sit)', s.by_zone_kind, ['A', 'B', 'none']),
    tcard('The card on every shown bar', null, [['Bars', cd.bars], ['Closing inside a band', cd.inside_pct + '%'], ['With a live visit', cd.ref_live_pct + '%'], ['Bands since the memory start', cd.zones_since_memory_start],
      ['Born A / B (B by drift)', `${sm.births_A} / ${sm.births_B} (${sm.births_B_drift})`], ['Born in this window A / B', `${(cd.births_in_window || {}).A ?? 0} / ${(cd.births_in_window || {}).B ?? 0}`], ['Merged candidates A / B', `${sm.merges_A} / ${sm.merges_B}`], ['visit_n at SETUP, median', s.visit_n_median],
      ['Closes back inside the band just left while another band holds the visit (no new visit on it)', cd.leave_return_no_visit ?? '—']],
      `Reads by bar (%): ${(lg.read || []).filter(x => (cd.reads || {})[x] != null).map(x => `${x} ${cd.reads[x]}`).join(' · ')}. Reads at SETUP: ${kv(s.reads_at_setup)}.`)];
  // the ledger: one row per Foundation SETUP; a click opens the chart at it
  const L = F.ledger || { cols: [], rows: [] }, ix = Object.fromEntries(L.cols.map((k, i) => [k, i])), g = (rw, k) => ix[k] == null ? null : rw[ix[k]];
  const zn = id => !id ? '—' : /^[AB]\d{4}-/.test(id) ? id[0] + id.slice(6, 17) : id;
  const ratio = rw => !g(rw, 'vol_na') && !g(rw, 'first_vol_na') && g(rw, 'this_vol') != null && g(rw, 'first_vol') ? (g(rw, 'this_vol') / g(rw, 'first_vol')).toFixed(2) : 'NA';
  const og = rw => ix.outcome_gate != null ? g(rw, 'outcome_gate') : g(rw, 'gate');   // the gate the SETUP ended with
  const GP = { TAKE: 'long', REENTER: 'long', WATCH: 'grey', BLOCK: 'short' }, rows = L.rows.filter(rw => fzGate === 'ALL' || og(rw) === fzGate);
  const seg = `<span class="seg tb-seg">${['ALL', ...GT].map(k => `<button data-g="${k}" class="${fzGate === k ? 'on' : ''}">${k === 'ALL' ? 'All' : k} <small>${k === 'ALL' ? L.rows.length : ((s.gates || {})[k] || 0)}</small></button>`).join('')}</span>`;
  const lrow = (rw, i) => {
    const t = g(rw, 'time'), fp = g(rw, 'fnd_pts'), zp = g(rw, 'fz_pts'), wk = g(rw, 'watch_kind');
    return `<tr class="click" data-t="${esc(t)}"><td class="l">${i + 1}</td><td class="l">${String(t).slice(5, 16)}</td><td class="l">${pill(g(rw, 'dir'), g(rw, 'dir') === 'up' ? 'long' : 'short')}</td>` +
      `<td class="l" title="${esc(g(rw, 'zone_id') || '')}${g(rw, 'band_lo') != null ? ` · ${g(rw, 'band_lo')}–${g(rw, 'band_hi')}` : ''}">${esc(zn(g(rw, 'zone_id')))}</td><td class="l">${g(rw, 'zone_kind') || '—'}</td><td>${g(rw, 'visit_n') ?? '—'}</td>` +
      `<td>${g(rw, 'this_bars') ?? '—'} / ${g(rw, 'first_bars') ?? '—'}</td><td>${ratio(rw)}</td><td class="l">${g(rw, 'read') || '—'}</td><td class="l">${pill(og(rw), GP[og(rw)])}${og(rw) !== g(rw, 'gate') ? ` <small class="sub">${g(rw, 'gate')} at the SETUP bar</small>` : ''}</td>` +
      `<td class="l">${esc(g(rw, 'block_reason') || g(rw, 'take_why') || '')}${g(rw, 'refused') ? ' · refused ' + esc(g(rw, 'refused')) : ''}</td><td class="l">${esc(g(rw, 'branch') || '')}</td>` +
      `<td class="l" title="${esc(g(rw, 'entered_zone_id') || '')}">${g(rw, 'entered_read') ? `${g(rw, 'entered_read')} (v${g(rw, 'entered_visit_n')})` : ''}</td>` +
      `<td class="l">${wk ? `${wk === 'WATCH_EDGE' ? 'edge' : 'watch'} → ${g(rw, 'watch_outcome') || 'active'}` : ''}</td>` +
      `<td class="l" title="${g(rw, 'fill_time') ? esc(`fill ${g(rw, 'fill_time')} · ${g(rw, 'edge_dist_pts') ?? '—'} pts beyond the edge · armed ${g(rw, 'armed_bars') ?? '—'} bars${g(rw, 'rearmed_bars') != null && g(rw, 'rearmed_bars') !== g(rw, 'armed_bars') ? ` (${g(rw, 'rearmed_bars')} since it re-armed)` : ''} · stop from the ${g(rw, 'sl_bar') || '—'} bar`) : ''}">${g(rw, 'fill_used') ? `${esc(g(rw, 'fill_used'))}${g(rw, 'fill_delay_bars') ? ' +' + g(rw, 'fill_delay_bars') : ''}` : ''}</td>` +
      `<td class="${cl(fp)}" title="${esc(fp == null ? '' : `${g(rw, 'fnd_exit_reason')} ${g(rw, 'fnd_exit_time')} · ${inr(g(rw, 'fnd_net'))}`)}">${fp == null ? '—' : fmt(fp)}</td>` +
      `<td class="${cl(zp)}" title="${esc(g(rw, 'fz_kind') ? `${g(rw, 'fz_kind')} · ${g(rw, 'fz_exit_reason')} ${g(rw, 'fz_exit_time')} · ${inr(g(rw, 'fz_net'))}` : '')}">${zp == null ? '—' : fmt(zp)}</td></tr>`;
  };
  el.innerHTML = hint(`Every Foundation SETUP of this backtest, carded against the band memory from ${esc(F.memory_start)} (the file's first session; the window starts ${esc(F.window_start)}) and gated. ${run.notes ? 'Backtest: ' + esc(run.notes) + '. ' : ''}${esc(lg.units || '')}.`) +
    `<div class="kpis">${tiles}</div>` +
    tcard('Gate × read', ['', ...reads, 'SETUPs'], gr, `Rows are Foundation SETUPs by the gate they ended with and the card's read at the SETUP bar; BLOCK is split by reason. A WATCH whose watch later re-entered on this SETUP counts as REENTER${s.gates_at_setup ? ` (gate at the SETUP bar: ${ord(s.gates_at_setup, GT)})` : ''}. WATCH at the SETUP bar after a LEAVE into a RECYCLE / THIN / HUNT / REJECT band: ${kv(s.watch_reason)}. Not a TAKE because: ${kv(s.take_why)}. Branches: TAKE ${kv((s.branches || {}).TAKE)}; REENTER ${kv((s.branches || {}).REENTER)}.`) +
    `<div class="tb-grid">${cells.join('')}</div>` +
    `<div class="card tb-card"><div class="tb-h3row"><h3>Gate ledger</h3>${seg}</div>${hint('One row per Foundation SETUP (skipped ones included). Hover the zone, entered read, fill and points for detail; click a row to open it on the chart. Foundation pts = what Foundation\'s own position on this SETUP did; FZ pts = the FZ position this SETUP opened (TAKE, or REENTER after its watch).')}` +
    `<div class="tablewrap tall"><table class="tbl"><thead><tr><th class="l">#</th><th class="l">SETUP</th><th class="l">Dir</th><th class="l">Zone</th><th class="l">Kind</th><th>Visit</th><th>This / first bars</th><th>Vol ratio</th><th class="l">Read</th><th class="l">Gate</th><th class="l">Reason</th><th class="l">Branch</th><th class="l">Entered</th><th class="l">Watch</th><th class="l">Fill</th><th>Foundation pts</th><th>FZ pts</th></tr></thead><tbody>${rows.map(lrow).join('')}</tbody></table></div></div>`;
  el.querySelectorAll('.tb-seg button').forEach(b => b.onclick = () => { fzGate = b.dataset.g; zonegate(el, X); });
  el.querySelectorAll('tr.click[data-t]').forEach(tr => tr.onclick = () => ctx.onOpenAt && ctx.onOpenAt(tr.dataset.t));
}

// ================================================================ Journal (v1 renderJournal L739)
function journal(el, X) {
  const R = X.r.rl, ctx = X.ctx;
  if (!R) { el.innerHTML = hint('Not a learner strategy.'); return; }
  const S = R.summary || {}, J = (R.journal || []).filter(j => j.scored), W = (R.journal || []).filter(j => !j.scored), arms = R.arms || [];
  const takeRate = S.setups ? Math.round(100 * S.taken / S.setups) + '%' : '—', pc = v => v == null ? '—' : v.toFixed(1) + 'th', RD = R.random, PM = R.permutation, SD = R.seeds, PR = R.prediction;
  const tiles = [tile('SETUPs (scored)', S.setups, `${S.taken} taken · ${S.skipped} skipped by the learner · ${S.locked} locked`),
    tile('Take rate', takeRate, 'of the scored SETUPs'),
    tile('Learner net', inr(S.rl_net), `its own trades, after costs${S.rl_t != null ? ` · t ${fmt(S.rl_t, 2)}` : ''}; locked = SETUPs its own open position blocked`, cl(S.rl_net)),
    tile('Base book', inr(S.base_net), esc(R.base_arm), cl(S.base_net)),
    tile('Random books', RD ? pc(RD.learner_pct) : inr(S.control_net), RD ? `learner's percentile among ${RD.draws} seeded random books (mean ${inr(RD.mean)}, 5th–95th ${inr(RD.p5)} … ${inr(RD.p95)}; the journal's Random column is draw 0, ${inr(RD.draw0)}). Skip is 1 action in ${arms.length}, so they trade ${Math.round(100 * (RD.take_rate || 0))}% of SETUPs — necessary to beat, not sufficient` : 'a seeded uniformly random action per SETUP (skip included), same one-position lock', RD ? cl(RD.learner_pct - 50) : cl(S.control_net)),
    tile('Oracle', inr(S.oracle_net), 'best net per SETUP in hindsight, skip included, so never below 0 at a SETUP; the maximum of the noisy action outcomes summed — an upper bound, not a target', cl(S.oracle_net)),
    tile('Seed spread', SD && SD.sd != null ? `${inr(SD.mean)} ± ${inr(SD.sd)}` : '—', SD && SD.runs ? `this window's net over ${SD.runs.length} seeds run from empty (${SD.positive} positive): ${SD.runs.map(x => `${x.seed}: ${inr(x.net)}`).join(' · ')}. One seed is one path — read this before any sign` : '', SD && SD.mean != null ? cl(SD.mean) : ''),
    tile('Matched permutations', PM && PM.n ? pc(PM.learner_pct) : '—', PM && PM.n ? `learner's percentile among ${PM.n} shuffles of its own ${PM.actions} window decisions across the same SETUPs (same take rate and sizes); share at or above the learner p = ${PM.p_ge}; shuffle mean ${inr(PM.mean)} — the test of where it chose to trade` : '', PM && PM.n ? cl(PM.learner_pct - 50) : ''),
    tile('pred vs realised', PR && PR.taken_corr != null ? fmt(PR.taken_corr, 2) : '—', PR ? `correlation over ${PR.taken_n} taken trades (mean gap pred − realised ${PR.taken_gap == null ? '—' : fmt(PR.taken_gap, 2)} reward units); over all ${PR.all_n} feasible action outcomes ${PR.all_corr == null ? '—' : fmt(PR.all_corr, 2)}. pred is the maximum of the action estimates, so it runs high` : ''),
    tile('Clipped outcomes', S.clipped != null ? `${S.clipped} of ${S.outcomes}` : '—', 'action outcomes whose per-lot value passed ±10 — the right tail only, losses are stop-bounded' + (R.clipped_by_arm && R.clipped_by_arm.length ? `; most on ${esc(R.clipped_by_arm[0][0])} (${R.clipped_by_arm[0][1]})` : '')),
    tile('Learning before the window', `${S.warmup_setups} SETUPs`, `from ${esc(R.learn_from)} · learner ${inr(S.warmup_rl_net)} vs base ${inr(S.warmup_base_net)} · ${R.learned_updates} updates`)].join('');
  const mixA = R.action_mix || [];
  const mix = mixA.length ? table(['Action', 'Taken', 'Share'], mixA.map(([a, n]) => [esc(a), n, Math.round(100 * n / Math.max(1, S.taken)) + '%'])) : hint('No trade taken in the window.');
  const months = `<div class="tablewrap tall"><table class="tbl"><thead><tr><th class="l">Month</th><th class="l"></th><th>SETUPs</th><th>Taken</th><th>Locked</th><th>Learner ₹</th><th>Base ₹</th><th>Random ₹</th><th>Oracle ₹</th></tr></thead><tbody>` +
    (R.months || []).map(m => `<tr class="${m.scored ? '' : 'tb-dim'}"><td class="l">${m.month}</td><td class="l">${m.scored ? 'scored' : 'learning'}</td><td>${m.setups}</td><td>${m.taken}</td><td>${m.locked}</td><td class="${cl(m.rl_net)}">${inr(m.rl_net)}</td><td class="${cl(m.base_net)}">${inr(m.base_net)}</td><td class="${cl(m.control_net)}">${inr(m.control_net)}</td><td class="${cl(m.oracle_net)}">${inr(m.oracle_net)}</td></tr>`).join('') + '</tbody></table></div>';
  // what it learned: the actions it took most, each with its strongest features (|weight| × the feature's spread)
  const F = R.features || [], cnt = a => (mixA.find(x => x[0] === a) || [0, 0])[1];
  const top = Object.entries(R.weights || {}).sort((a, b) => cnt(b[0]) - cnt(a[0])).slice(0, 6);
  const weights = top.length ? `<div class="tablewrap"><table class="tbl"><thead><tr><th class="l">Action</th><th class="l">Strongest features (ranked by |weight| × the feature's spread in the window; the hour dummies and the bias are collinear, so read their split as signs only)</th></tr></thead><tbody>${top.map(([a, wv]) => {
    const sd = R.feature_sd || F.map(() => 1), ws = wv.map((v, i) => [F[i], v, Math.abs(v) * (sd[i] || 0)]).filter(x => x[0] !== 'bias').sort((x, y) => y[2] - x[2]).slice(0, 5);
    return `<tr><td class="l">${esc(a)}</td><td class="l">bias ${fmt(wv[0], 2)} · ${ws.map(([f, v]) => `${esc(f)} <b class="${cl(v)}">${fmt(v, 2)}</b>`).join(' · ')}</td></tr>`;
  }).join('')}</tbody></table></div>` : '';
  const WHYD = d => d === 'skip' ? pill('skip') : d === 'locked' ? pill('locked', 'open') : esc(d);
  const rows = J.map((j, i) => `<tr class="click" data-t="${esc(j.time)}"><td class="l">${i + 1}</td><td class="l">${j.time.slice(5, 16)}</td><td class="l">${pill(j.dir === 'up' ? 'LONG' : 'SHORT', j.dir === 'up' ? 'long' : 'short')}</td><td class="l">${WHYD(j.decision)}</td><td>${j.pred == null ? '—' : fmt(j.pred, 2)}</td><td class="${cl(j.net)}">${inr(j.net)}</td><td class="${cl(j.base_net)}">${inr(j.base_net)}</td><td class="l">${esc(j.oracle_arm)} <span class="${cl(j.oracle_net)}">${inr(j.oracle_net)}</span></td><td>${fmt(j.atr_pct, 3)}</td><td>${fmt(j.d_hi, 1)} / ${fmt(j.d_lo, 1)}</td><td>${fmt(j.day_r, 1)}</td><td>${j.form3 ?? '—'}</td><td>${j.consec_loss ?? '—'}</td></tr>`).join('');
  el.innerHTML = `<div class="kpis">${tiles}</div>${R.notes ? hint(esc(R.notes)) : ''}<div class="tb-grid"><div class="card tb-card"><h3>Actions taken</h3>${mix}</div><div class="card tb-card"><h3>What it learned</h3>${hint(`Reward: ${esc(R.reward)} · seed ${esc(R.seed)} · ${Math.max(0, arms.length - 1)} actions + skip; every action's model updates on every SETUP (full information), so each has as many updates as there were learnable SETUPs; the exploration term shrinks with them and plays no learning role here — a decision is close to the argmax of the posterior means, and lots are chosen by expected reward with no risk term.`)}${weights}</div></div>` +
    `<div class="card tb-card"><h3>Month by month</h3>${hint(`${esc(R.books || '')} Base = ${esc(R.base_arm)}. Figures are by entry month; the scored rows sum to the tiles.`)}${months}</div>` +
    `<div class="card tb-card"><h3>Journal — every scored SETUP (${J.length}; ${W.length} learning rows before the window not listed)</h3>${hint('pred = the learner\'s expected reward for its decision at the time (the maximum over the action estimates, so biased upward); net = what the trade made; base = what the base rule would have made; oracle = the best action in hindsight. Features: ATR % of price, distance from the AVWAP high / low in ATRs (signed with the trade), the day\'s closed result in R, form over the last 3 trades, consecutive losses. Click a row to open it on the chart.')}` +
    `<div class="tablewrap tall"><table class="tbl"><thead><tr><th class="l">#</th><th class="l">Time</th><th class="l">Dir</th><th class="l">Decision</th><th>pred</th><th>Net ₹</th><th>Base ₹</th><th class="l">Oracle</th><th>ATR %</th><th>d AVWAP H / L</th><th>Day R</th><th>Form 3</th><th>Losses in a row</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  el.querySelectorAll('tr.click[data-t]').forEach(tr => tr.onclick = () => ctx.onOpenAt && ctx.onOpenAt(tr.dataset.t));
}

// ---------------------------------------------------------------- dispatch
const RENDER = { performance, cumulative, drawdowns, distribution, montecarlo, robustness, breakdown, daily, signals, zonegate, journal, config, rules };
export function renderTab(id, el, ctx) {
  dispose();
  el.innerHTML = '';
  const fn = RENDER[id];
  if (!fn) { el.innerHTML = hint('Unknown tab.'); return; }
  try { fn(el, prep(ctx)); }
  catch (e) { console.error('tabs:', id, e); el.innerHTML = `<div class="tb-note">This tab could not be drawn: ${esc(e.message)}</div>`; }
}
