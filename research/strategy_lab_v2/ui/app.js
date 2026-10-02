// Strategy lab v2 UI: reads everything from the server's JSON API; nothing is baked into the page.
"use strict";
const $ = (s) => document.querySelector(s);
const TYPE_LABEL = { FUT: "Futures", OPT_FUT_SIGNAL: "Options (via futures)", OPT_NATIVE: "Options (standalone)" };
const PRESETS = [["MTD", "This month"], ["1M", "1 month"], ["3M", "3 months"], ["6M", "6 months"], ["YTD", "Year to date"],
                 ["1Y", "1 year"], ["5Y", "5 years"], ["all", "All data"], ["custom", "Custom dates…"]];
const S = { strategies: [], code: null, runs: [], run: null, type: null, choice: null, side: "all", result: null,
            rows: [], day: null, inst: "", sel: -1, lastJobs: {} };

async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const inr = (v) => v == null ? "–" : (v < 0 ? "−₹" : "₹") + Math.abs(Math.round(v)).toLocaleString("en-IN");
const num = (v, d = 2) => v == null ? "–" : Number(v).toFixed(d);
const cls = (v) => v > 0 ? "pos" : v < 0 ? "neg" : "";
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const tsOf = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10), +s.slice(11, 13) || 0, +s.slice(14, 16) || 0) / 1000;

// ------------------------------------------------------------ strategies
async function loadStrategies(keep) {
  S.strategies = await api("/api/strategies");
  const ul = $("#strategies");
  ul.innerHTML = S.strategies.map(({ spec, runs }) => {
    const r = runs[0], ch = r && pickDefaultChoice(r, spec);
    const net = ch ? ch.net_inr : null;
    return `<li data-code="${spec.code}" class="${spec.code === S.code ? "on" : ""}">
      <div class="n">${esc(spec.code)} · ${esc(spec.name)}</div>
      <div class="d">${esc(spec.timeframe)} · ${esc(spec.rules.sl_rule)}${net != null ? ` · <span class="${cls(net)}">${inr(net)}</span>` : ""}</div></li>`;
  }).join("");
  ul.querySelectorAll("li").forEach((li) => li.onclick = () => { selectStrategy(li.dataset.code); $("#side").classList.remove("open"); });
  if (!keep && !S.code && S.strategies.length) selectStrategy(localStorageGet("code") || S.strategies[0].spec.code);
}
function pickDefaultChoice(run, spec) {
  const fut = run.types && run.types.FUT;
  return fut && fut.choices && fut.choices["-"];
}
function localStorageGet(k) { try { return localStorage.getItem("lab2." + k); } catch (e) { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem("lab2." + k, v); } catch (e) {} }

function current() { return S.strategies.find((x) => x.spec.code === S.code); }

function selectStrategy(code) {
  if (!S.strategies.find((x) => x.spec.code === code)) code = S.strategies[0].spec.code;
  S.code = code; localStorageSet("code", code);
  document.querySelectorAll("#strategies li").forEach((li) => li.classList.toggle("on", li.dataset.code === code));
  const { spec, runs } = current();
  $("#empty").hidden = true; $("#strategy").hidden = false;
  $("#s-title").textContent = `${spec.code} · ${spec.name}`;
  const r = spec.rules, p = spec.position || {};
  const chips = [spec.timeframe, `signals on ${spec.underlying || "FUT"}`, `break ${r.break_mode}`, `CHoCH ${r.choch_mode || r.break_mode}`,
                 `AVWAP ${r.avwap_weight}`, `stop ${r.sl_rule}`, `entry ${r.entry_rule}`, `exit ${r.exit_rule}`,
                 `${p.lots || 1} lot × ${spec.lot_size}`, p.square_off ? `intraday ${p.square_off}` : "positional", `warm-up ${spec.warmup_days}d`];
  $("#s-chips").innerHTML = chips.map((c) => `<span class="chip">${esc(c)}</span>`).join("");
  $("#s-desc").textContent = spec.description;
  const sel = $("#f-what");
  sel.innerHTML = `<optgroup label="Defined in the strategy file">${spec.backtests.map((b) =>
      `<option value="defined:${esc(b.run)}" ${b.default ? "selected" : ""}>${esc(b.label)} · ${esc(b.run)}${b.notes ? " — " + esc(b.notes.slice(0, 50)) : ""}</option>`).join("")}</optgroup>
    <optgroup label="Ad hoc">${PRESETS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</optgroup>`;
  formMode();
  S.runs = runs;
  renderRuns(localStorageGet("run." + code));
}

function formMode() {
  const v = $("#f-what").value, adhoc = !v.startsWith("defined:");
  document.querySelectorAll(".form .custom").forEach((e) => e.hidden = v !== "custom");
  document.querySelectorAll(".form .adhoc").forEach((e) => e.hidden = !adhoc);
}

async function runBacktest() {
  const what = $("#f-what").value;
  const q = { code: S.code, what, types: [...document.querySelectorAll(".types input:checked")].map((x) => x.value) };
  if (!q.types.length) { $("#run-msg").textContent = "Pick at least one type."; return; }
  if (!what.startsWith("defined:")) {
    if (what === "custom") { q.from = $("#f-from").value; q.to = $("#f-to").value; }
    if ($("#f-tf").value) q.tf = $("#f-tf").value;
    if ($("#f-und").value) q.underlying = $("#f-und").value;
    const sq = $("#f-sq").value; if (sq !== "keep") q.square_off = sq === "none" ? null : sq;
  }
  try {
    const j = await api("/api/backtest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(q) });
    $("#run-msg").textContent = `Queued ${j.code} · ${j.label}`;
    S.lastJobs[j.id] = j.state;
    pollStatus();
  } catch (e) { $("#run-msg").textContent = "Refused: " + e.message; }
}

// ------------------------------------------------------------ jobs
let pollTimer = null;
async function pollStatus() {
  clearTimeout(pollTimer);
  let st;
  try { st = await api("/api/status"); } catch (e) { pollTimer = setTimeout(pollStatus, 4000); return; }
  $("#jobs").innerHTML = st.jobs.slice(0, 4).map((j) => `<span class="job ${j.state}" title="${esc((j.log || []).join("\n") || j.error || "")}">${esc(j.code)} ${esc(j.label)} · ${j.state}${j.seconds != null ? " " + j.seconds + "s" : ""}</span>`).join("");
  for (const j of st.jobs) {
    const was = S.lastJobs[j.id];
    if (was && was !== j.state && (j.state === "done" || j.state === "failed")) {
      if (j.code === S.code) {
        $("#run-msg").textContent = j.state === "done" ? `${j.code} ${j.label}: done in ${j.seconds}s\n${(j.log || []).join("\n")}` : `${j.code} ${j.label}: failed — ${j.error}`;
        if (j.state === "done") { await loadStrategies(true); S.runs = current().runs; renderRuns(j.run); }
      }
    }
    S.lastJobs[j.id] = j.state;
  }
  $("#run").disabled = false;
  pollTimer = setTimeout(pollStatus, st.busy ? 1000 : 8000);
}

// ------------------------------------------------------------ runs + results
function renderRuns(want) {
  const sel = $("#r-run");
  if (!S.runs.length) {
    sel.innerHTML = "<option>no runs yet — run a backtest above</option>";
    $("#r-meta").textContent = ""; $("#r-types").innerHTML = ""; $("#r-body").hidden = true; $("#r-refused").hidden = true;
    clearResult(); return;
  }
  sel.innerHTML = S.runs.map((m) => `<option value="${esc(m.run)}">${esc(m.label)} · ${esc(m.run)} · ${esc(m.date_from || "")} → ${esc(m.date_to || "")}</option>`).join("");
  sel.value = S.runs.some((m) => m.run === want) ? want : S.runs[0].run;
  selectRun(sel.value);
}

function selectRun(run) {
  S.run = S.runs.find((m) => m.run === run); localStorageSet("run." + S.code, run);
  const m = S.run;
  const secs = Object.entries(m.types).filter(([, t]) => t.seconds != null).map(([k, t]) => `${TYPE_LABEL[k]} ${t.seconds}s`).join(" · ");
  $("#r-meta").textContent = `${m.date_from || "?"} → ${m.date_to || "?"} · ${m.timeframe} · signals on ${m.underlying} · ${m.holding} · run at ${m.at.replace("T", " ")} · ${m.seconds}s${secs ? " (" + secs + ")" : ""}`;
  const types = Object.keys(m.types);
  $("#r-types").innerHTML = types.map((t) => {
    const tm = m.types[t], ok = tm.status === "ok";
    return `<button data-t="${t}">${TYPE_LABEL[t]}${ok ? "" : ' <span class="x">(refused)</span>'}</button>`;
  }).join("");
  $("#r-types").querySelectorAll("button").forEach((b) => b.onclick = () => selectType(b.dataset.t));
  const keep = types.includes(S.type) ? S.type : (types.find((t) => m.types[t].status === "ok") || types[0]);
  selectType(keep);
}

function selectType(t) {
  S.type = t;
  $("#r-types").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.t === t));
  const tm = S.run.types[t];
  if (!tm || tm.status !== "ok") {
    $("#r-refused").hidden = false; $("#r-refused").textContent = `Refused: ${tm ? tm.reason : "not run"}`;
    $("#r-body").hidden = true; clearResult(); return;
  }
  $("#r-refused").hidden = true; $("#r-body").hidden = false;
  const chs = Object.keys(tm.choices);
  const spec = current().spec;
  $("#r-choice").innerHTML = chs.map((c) => `<option>${esc(c)}</option>`).join("");
  const want = chs.includes(S.choice) ? S.choice : (chs.find((c) => c === `W-${spec.options.strike_default}`) || chs[0]);
  $("#r-choice").value = want;
  renderChoices(tm);
  selectChoice(want);
}

function renderChoices(tm) {
  const rows = Object.entries(tm.choices);
  $("#choices").innerHTML = `<tr><th class="l">Choice</th><th>Trades</th><th>Win %</th><th>Net</th><th>PF</th><th>t</th><th>Max DD</th><th>Skipped</th><th>Locked</th></tr>` +
    rows.map(([c, s]) => `<tr class="click ${c === S.choice ? "sel" : ""}" data-c="${esc(c)}"><td class="l">${esc(c)}</td><td>${s.trades}</td>
      <td>${s.trades ? Math.round(100 * s.wins / s.trades) : "–"}</td><td class="${cls(s.net_inr)}">${inr(s.net_inr)}</td>
      <td>${num(s.pf)}</td><td>${num(s.t_stat)}</td><td class="neg">${inr(s.max_dd_inr)}</td><td>${s.skipped}</td><td>${s.locked}</td></tr>`).join("");
  $("#choices").querySelectorAll("tr.click").forEach((tr) => tr.onclick = () => { $("#r-choice").value = tr.dataset.c; selectChoice(tr.dataset.c); });
}

async function selectChoice(ch) {
  S.choice = ch;
  $("#choices").querySelectorAll("tr.click").forEach((tr) => tr.classList.toggle("sel", tr.dataset.c === ch));
  const q = new URLSearchParams({ code: S.code, run: S.run.run, type: S.type, choice: ch });
  S.result = await api("/api/result?" + q);
  const C = {}; S.result.cols.forEach((k, i) => C[k] = i); S.C = C;
  renderResult();
  renderReport();
  const first = S.result.trades[S.result.trades.length - 1];
  if (first) openChart(first[C.entry_time].slice(0, 10), "");
  else $("#chart-card").hidden = true;
}

function sideRows() {
  const C = S.C, sd = S.side;
  return S.result.trades.filter((r) => sd === "all" || r[C.position] === sd || r[C.opt_type] === sd);
}

function renderResult() {
  const C = S.C, rows = sideRows();
  S.rows = rows;
  // KPIs over the side shown
  const net = rows.map((r) => r[C.net]);
  let eq = 0, peak = 0, dd = 0;
  const byExit = rows.map((r) => [tsOf(r[C.exit_time]), r[C.net]]).sort((a, b) => a[0] - b[0]);
  const curve = [];
  for (const [t, v] of byExit) {
    eq += v; peak = Math.max(peak, eq); dd = Math.min(dd, eq - peak);
    if (curve.length && curve[curve.length - 1].time === t) curve[curve.length - 1].value = eq; else curve.push({ time: t, value: eq });
  }
  const wins = net.filter((v) => v > 0), loss = net.filter((v) => v <= 0);
  const sum = (a) => a.reduce((x, y) => x + y, 0);
  const m = net.length ? sum(net) / net.length : 0;
  const sd = net.length > 1 ? Math.sqrt(sum(net.map((v) => (v - m) ** 2)) / (net.length - 1)) : 0;
  const pf = loss.length && sum(loss) ? sum(wins) / -sum(loss) : null;
  const kp = [["Trades", rows.length, ""], ["Win %", rows.length ? Math.round(100 * wins.length / rows.length) + "%" : "–", ""],
              ["Net", inr(sum(net)), cls(sum(net))], ["Points", num(sum(rows.map((r) => r[C.pts])), 1), cls(sum(rows.map((r) => r[C.pts])))],
              ["Charges", inr(sum(rows.map((r) => r[C.charges]))), ""], ["Profit factor", num(pf), ""],
              ["Max drawdown", inr(dd), "neg"], ["t-stat", sd ? num(m / (sd / Math.sqrt(net.length))) : "–", ""],
              ["Avg / trade", inr(m), cls(m)]];
  $("#kpis").innerHTML = kp.map(([k, v, c]) => `<div class="kpi"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join("");
  drawEquity(curve);
  renderTrades();
  const sk = S.result.skipped;
  $("#sk-sum").textContent = `Not taken (${sk.length}): no option data, strike lock, square-off`;
  const keys = ["entry_time", "position", "opt_type", "instrument", "why"];
  $("#skipped").innerHTML = `<tr>${keys.map((k) => `<th class="l">${k}</th>`).join("")}</tr>` +
    sk.slice(0, 2000).map((s) => `<tr>${keys.map((k) => `<td class="l">${esc(s[k])}</td>`).join("")}</tr>`).join("");
}

function renderTrades() {
  const C = S.C, f = $("#t-filter").value.trim().toLowerCase();
  const rows = S.rows.map((r, i) => [r, i]).filter(([r]) => !f || r.join(" ").toLowerCase().includes(f));
  $("#t-count").textContent = `(${rows.length})`;
  const head = ["Entry", "Exit", "Side", "Instrument", "Entry px", "Exit px", "Stop", "Reason", "Pts", "Net", "MFE", "MAE"];
  $("#trades").innerHTML = `<tr>${head.map((h, i) => `<th class="${i < 4 || i === 7 ? "l" : ""}">${h}</th>`).join("")}</tr>` +
    rows.slice().reverse().map(([r, i]) => `<tr class="click ${i === S.sel ? "sel" : ""}" data-i="${i}">
      <td class="l">${esc(r[C.entry_time].slice(0, 16))}</td><td class="l">${esc(r[C.exit_time].slice(0, 16))}${r[C.open] ? " *" : ""}</td>
      <td class="l">${esc(r[C.label] || r[C.position])}</td><td class="l">${esc(r[C.instrument])}</td>
      <td>${num(r[C.entry_px])}</td><td>${num(r[C.exit_px])}</td><td>${num(r[C.sl])}</td><td class="l">${esc(r[C.exit_reason])}</td>
      <td class="${cls(r[C.pts])}">${num(r[C.pts], 1)}</td><td class="${cls(r[C.net])}">${inr(r[C.net])}</td>
      <td>${num(r[C.mfe], 1)}</td><td>${num(r[C.mae], 1)}</td></tr>`).join("");
  $("#trades").querySelectorAll("tr.click").forEach((tr) => tr.onclick = () => {
    const i = +tr.dataset.i, r = S.rows[i]; S.sel = i;
    $("#trades").querySelectorAll("tr.sel").forEach((x) => x.classList.remove("sel")); tr.classList.add("sel");
    openChart(r[C.entry_time].slice(0, 10), S.type === "FUT" ? "" : r[C.instrument]);
    $("#chart-card").scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

// a strategy family's own report: the FZ gate (fz) or the learner (rl)
function renderReport() {
  const R = S.result, card = $("#report-card");
  const kp = (rows) => rows.map(([k, v, c]) => `<div class="kpi"><div class="k">${esc(k)}</div><div class="v ${c || ""}">${v}</div></div>`).join("");
  const table = (cols, rows, max) => `<div class="tablewrap"><table class="tbl"><tr>${cols.map((c) => `<th class="l">${esc(c)}</th>`).join("")}</tr>` +
    rows.slice(0, max || 500).map((r) => `<tr>${r.map((v) => `<td class="l">${esc(typeof v === "number" ? Math.round(v * 100) / 100 : v)}</td>`).join("")}</tr>`).join("") + "</table></div>";
  if (R.fz) {
    const h = R.fz.headline, b = R.fz.books;
    $("#rep-title").textContent = "Foundation-Zone gate";
    $("#rep-kpis").innerHTML = kp([["SETUPs", h.setups], ["Take", h.take], ["Re-enter", h.reenter], ["Watch", h.watch], ["Block", h.block],
      ["FZ net", inr(b.fz.net), cls(b.fz.net)], ["Foundation net", inr(b.raw.net), cls(b.raw.net)],
      ["Random-gate pct", h.control_pct ?? "–"], ["Permutation p", h.perm_p ?? "–"], ["Active sessions", h.active_sessions]]);
    const L = R.fz.ledger;
    $("#rep-body").innerHTML = `<div class="sub">SETUP ledger (${L.rows.length}): the gate's read at each Foundation SETUP and both outcomes</div>` +
      table(["time", "dir", "gate", "outcome_gate", "read", "block_reason", "take_why", "zone_id", "fnd_net", "fz_kind", "fz_net"],
            L.rows.map((r) => ["time", "dir", "gate", "outcome_gate", "read", "block_reason", "take_why", "zone_id", "fnd_net", "fz_kind", "fz_net"].map((c) => r[L.cols.indexOf(c)])));
    card.hidden = false;
  } else if (R.rl) {
    const s = R.rl.summary, rd = R.rl.random, pm = R.rl.permutation, sd = R.rl.seeds;
    $("#rep-title").textContent = `Learner · reward ${R.rl.reward} · learned from ${R.rl.learn_from}`;
    $("#rep-kpis").innerHTML = kp([["SETUPs", s.setups], ["Taken", s.taken], ["Skipped", s.skipped], ["Locked", s.locked],
      ["Learner net", inr(s.rl_net), cls(s.rl_net)], ["Base book", inr(s.base_net), cls(s.base_net)], ["Random draw 0", inr(s.control_net), cls(s.control_net)],
      ["Oracle", inr(s.oracle_net), "pos"], ["Pct vs random", rd.learner_pct ?? "–"], ["Pct vs permutations", pm.learner_pct ?? "–"],
      ["Seeds positive", `${sd.positive}/${sd.runs.length}`]]);
    const J = R.rl.journal.filter((j) => j.scored);
    $("#rep-body").innerHTML = `<div class="sub">Months (learning rows and scored rows)</div>` +
      table(["month", "scored", "setups", "taken", "locked", "learner", "base", "random", "oracle"],
            R.rl.months.map((m) => [m.month, m.scored ? "scored" : "learning", m.setups, m.taken, m.locked, m.rl_net, m.base_net, m.control_net, m.oracle_net])) +
      `<div class="sub" style="margin-top:10px">Journal of the scored window (${J.length} SETUPs)</div>` +
      table(["time", "dir", "decision", "pred", "net", "base_net", "oracle_net", "oracle_arm"], J.map((j) => [j.time, j.dir, j.decision, j.pred, j.net, j.base_net, j.oracle_net, j.oracle_arm]));
    card.hidden = false;
  } else card.hidden = true;
}

function clearResult() {
  $("#report-card").hidden = true;
  $("#kpis").innerHTML = ""; $("#trades").innerHTML = ""; $("#skipped").innerHTML = ""; $("#t-count").textContent = "";
  $("#chart-card").hidden = true; drawEquity([]);
}

// ------------------------------------------------------------ charts
function chartOpts() {
  return { autoSize: true, layout: { background: { color: css("--card") }, textColor: css("--muted") },
           grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
           timeScale: { timeVisible: true, secondsVisible: false, borderColor: css("--line") },
           rightPriceScale: { borderColor: css("--line") }, crosshair: { mode: 0 } };
}
let eqChart = null;
function drawEquity(curve) {
  const el = $("#equity");
  if (eqChart) { eqChart.remove(); eqChart = null; }
  if (!curve.length) return;
  eqChart = LightweightCharts.createChart(el, chartOpts());
  const last = curve[curve.length - 1].value;
  eqChart.addAreaSeries({ lineColor: last >= 0 ? css("--up") : css("--down"), topColor: "transparent", bottomColor: "transparent", lineWidth: 2 })
    .setData(curve);
  eqChart.timeScale().fitContent();
}

let pxChart = null;
async function openChart(day, inst) {
  S.day = day; S.inst = inst || "";
  $("#chart-card").hidden = false;
  $("#c-day").value = day;
  // instruments traded that day in this choice (options), plus the signal chart
  const C = S.C, insts = [...new Set(S.result.trades.filter((r) => r[C.entry_time].startsWith(day) && S.type !== "FUT").map((r) => r[C.instrument]))];
  const sigName = S.run.underlying === "INDEX" ? "NIFTY index (signals)" : "Near-month futures (signals)";
  $("#c-inst").innerHTML = (S.type === "OPT_NATIVE" ? "" : `<option value="">${sigName}</option>`) + insts.map((x) => `<option>${esc(x)}</option>`).join("");
  if (S.type === "OPT_NATIVE" && !S.inst && insts.length) S.inst = insts[0];
  $("#c-inst").value = S.inst;
  if (S.type === "OPT_NATIVE" && !S.inst) { $("#c-legend").textContent = "No standalone-option trades on this day."; if (pxChart) { pxChart.remove(); pxChart = null; } return; }
  const q = new URLSearchParams({ code: S.code, run: S.run.run, type: S.type, choice: S.choice, day, inst: S.inst });
  $("#c-title").textContent = `Chart · ${day}${S.inst ? " · " + S.inst : ""}`;
  $("#c-legend").textContent = "loading…";
  let d;
  try { d = await api("/api/chart?" + q); } catch (e) { $("#c-legend").textContent = e.message; if (pxChart) { pxChart.remove(); pxChart = null; } return; }
  drawPrice(d);
}

function drawPrice(d) {
  const el = $("#chart");
  if (pxChart) { pxChart.remove(); pxChart = null; }
  pxChart = LightweightCharts.createChart(el, chartOpts());
  const up = css("--up"), dn = css("--down"), acc = css("--accent"), mut = css("--muted");
  const cs = pxChart.addCandlestickSeries({ upColor: up, downColor: dn, wickUpColor: up, wickDownColor: dn, borderVisible: false });
  const times = d.candles.map((c) => c[0]);
  cs.setData(d.candles.map((c) => ({ time: c[0], open: c[1], high: c[2], low: c[3], close: c[4] })));
  const snap = (t) => { let lo = 0, hi = times.length - 1; if (t < times[0] || t > times[hi] + 86400) return null;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (times[m] <= t) lo = m; else hi = m - 1; } return times[lo]; };
  const line = (pts, color, style, width) => {
    const s = pxChart.addLineSeries({ color, lineWidth: width || 1, lineStyle: style || 0, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    s.setData(pts); return s;
  };
  const markers = [];
  let nS = 0, nE = 0;
  if (d.prot) {   // protected level, with gaps
    const m = new Map(d.prot.map(([t, v]) => [t, v]));
    line(times.map((t) => m.has(t) ? { time: t, value: m.get(t) } : { time: t }), mut, 2);
  }
  // a strategy's own lines (rainbow ribbon): fastest red .. slowest violet (hex: the chart library parses no hsl())
  const RIBBON = ["#e5484d", "#f76b15", "#f5a524", "#e2c93a", "#7ac943", "#30a46c", "#12a594", "#0090ff", "#3e63dd", "#8e4ec6"];
  (d.lines || []).forEach((ln, k, all) => {
    const j = all.length > 1 ? Math.round((RIBBON.length - 1) * k / (all.length - 1)) : 0;
    if (ln.length > 1) line(ln.map(([t, v]) => ({ time: t, value: v })), RIBBON[j], 0);
  });
  for (const p of d.pair || []) if (p.live.length > 1) line(p.live.map(([t, v]) => ({ time: t, value: v })), p.side === "H" ? dn : up, 1);
  for (const s of d.swings || []) { nS++; markers.push({ time: s[1], position: s[0] === "H" ? "aboveBar" : "belowBar", color: mut, shape: "circle", size: 0.4, text: s[0] === "H" ? "SH" : "SL" }); }
  for (const e of d.events || []) { nE++; markers.push({ time: e[0], position: e[2] === "up" ? "belowBar" : "aboveBar", color: e[1] === "CHoCH" ? acc : mut, shape: "square", size: 0.6, text: e[1] }); }
  for (const s of d.setups || []) markers.push({ time: s[0], position: s[1] === "up" ? "belowBar" : "aboveBar", color: css("--warn"), shape: "circle", size: 0.8, text: "SETUP" });
  const C = {}; d.cols.forEach((k, i) => C[k] = i);
  const ownPrices = S.inst || (S.type === "FUT" && S.run.underlying !== "INDEX");
  for (const r of d.trades) {
    const te = snap(tsOf(r[C.entry_time])), tx = snap(tsOf(r[C.exit_time]));
    const lng = r[C.position] === "LONG", win = r[C.net] > 0;
    const tag = r[C.label] || r[C.position];
    if (te != null) markers.push({ time: te, position: lng ? "belowBar" : "aboveBar", color: lng ? up : dn, shape: lng ? "arrowUp" : "arrowDown", text: tag });
    if (tx != null) markers.push({ time: tx, position: lng ? "aboveBar" : "belowBar", color: win ? up : dn, shape: "circle", size: 0.7, text: `${r[C.exit_reason]} ${num(r[C.pts], 1)}` });
    if (ownPrices && te != null && tx != null && te < tx)
      line([{ time: te, value: r[C.entry_px] }, { time: tx, value: r[C.exit_px] }], win ? up : dn, 2, 2);
  }
  markers.sort((a, b) => a.time - b.time);
  cs.setMarkers(markers);
  pxChart.timeScale().fitContent();
  $("#c-legend").textContent = `${d.candles.length} candles · ${nS} swings · ${nE} CHoCH/BOS · ${d.trades.length} trade(s)` +
    (d.prot ? " · grey dashes = protected level · red/green = AVWAP pair from SH / SL" : "");
}

function stepDay(k) {
  const C = S.C;
  const days = [...new Set(S.result.trades.map((r) => r[C.entry_time].slice(0, 10)))].sort();
  if (!days.length) return;
  let i = days.indexOf(S.day);
  if (i < 0) i = days.findIndex((x) => x > S.day) - (k > 0 ? 1 : 0);
  i = Math.max(0, Math.min(days.length - 1, i + k));
  openChart(days[i], "");
}

// ------------------------------------------------------------ wiring
$("#menu").onclick = () => $("#side").classList.toggle("open");
$("#f-what").onchange = formMode;
$("#run").onclick = runBacktest;
$("#r-run").onchange = (e) => selectRun(e.target.value);
$("#r-choice").onchange = (e) => selectChoice(e.target.value);
$("#r-side").querySelectorAll("button").forEach((b) => b.onclick = () => {
  S.side = b.dataset.side; $("#r-side").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); S.sel = -1; renderResult();
});
$("#t-filter").oninput = renderTrades;
$("#c-day").onchange = (e) => openChart(e.target.value, "");
$("#c-inst").onchange = (e) => openChart(S.day, e.target.value);
$("#c-prev").onclick = () => stepDay(-1);
$("#c-next").onclick = () => stepDay(1);
loadStrategies().then(pollStatus).catch((e) => { $("#empty").textContent = "Server not reachable: " + e.message; });
