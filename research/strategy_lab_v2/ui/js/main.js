// Strategy lab v2 page: strategy cards on top, the selected strategy's details below (backtests, run controls, the three
// trade types side by side, KPIs, the chart and the analysis tabs). Everything comes from the server's JSON API.
import { $, $$, api, post, esc, inr, num, pct, cls, tsOf, pref, TYPE_LABEL, TF_LABEL, reasonTag, rulesSentence } from "./util.js";
import { ChartView } from "./chart.js";
import * as T from "./tabs.js";

const FAMILY_ORDER = ["Foundation", "Managed exits", "FZ gate", "Learner", "CHoCH to CHoCH", "Rainbow"];
const PRESETS = [["1M", "1M"], ["3M", "3M"], ["6M", "6M"], ["YTD", "YTD"], ["1Y", "1Y"], ["5Y", "5Y"], ["all", "All data"]];
const S = { list: [], code: null, family: pref("family") || "All", search: "", sort: pref("sort") || "code",
            label: null, run: null, type: null, exp: "W", strike: null, side: "all", result: null, rows: [], tab: pref("tab") || "trades",
            jobs: {}, sortCol: null, sortDir: 1 };
let chart;

// ------------------------------------------------------------------ data
async function load() {
  S.list = await api("/api/strategies");
  for (const s of S.list) s.byRun = Object.fromEntries(s.runs.map((m) => [m.run, m]));
}
const cur = () => S.list.find((x) => x.spec.code === S.code);

function headline(item) {
  // the card's numbers: the default backtest's run (else the newest run), futures, else the first option type that ran
  const spec = item.spec, def = spec.backtests.find((b) => b.default);
  const m = (def && item.byRun[def.run]) || item.runs[0];
  if (!m) return null;
  for (const t of ["FUT", "OPT_FUT_SIGNAL", "OPT_NATIVE"]) {
    const tm = m.types[t]; if (!tm || tm.status !== "ok") continue;
    const chs = tm.choices, key = chs["-"] ? "-" : chs[`W-${spec.options.strike_default}`] ? `W-${spec.options.strike_default}` : Object.keys(chs)[0];
    if (key) return { m, t, key, s: chs[key] };
  }
  return { m, t: null };
}

// ------------------------------------------------------------------ cards
function renderFilters() {
  const fams = ["All", ...FAMILY_ORDER.filter((f) => S.list.some((x) => x.spec.family === f))];
  $("#fam").innerHTML = fams.map((f) => {
    const n = f === "All" ? S.list.length : S.list.filter((x) => x.spec.family === f).length;
    return `<button class="chip-t ${f === S.family ? "on" : ""}" data-f="${esc(f)}">${esc(f)} <span class="muted">${n}</span></button>`;
  }).join("");
  $$("#fam button").forEach((b) => b.onclick = () => { S.family = b.dataset.f; pref("family", S.family); renderFilters(); renderCards(); });
  $("#sort").value = S.sort;
}

function renderCards() {
  let items = S.list.filter((x) => (S.family === "All" || x.spec.family === S.family) &&
    (!S.search || `${x.spec.code} ${x.spec.name} ${x.spec.description} ${x.spec.family}`.toLowerCase().includes(S.search)));
  const val = (x, k) => { const h = headline(x); return h && h.s ? h.s[k] ?? -1e18 : -1e18; };
  if (S.sort === "net") items.sort((a, b) => val(b, "net_inr") - val(a, "net_inr"));
  else if (S.sort === "pf") items.sort((a, b) => val(b, "pf") - val(a, "pf"));
  else if (S.sort === "recent") items.sort((a, b) => ((b.runs[0]?.at || "") > (a.runs[0]?.at || "") ? 1 : -1));
  const compact = !!S.code && !S.expanded;           // a strategy is open: the cards shrink to one scrolling strip
  $("#cards").classList.toggle("compact", compact);
  $("#cards-toggle").hidden = !S.code;
  $("#cards-toggle").textContent = compact ? "Show all as cards" : "Compact strip";
  $("#cards").innerHTML = items.map((x) => {
    const sp = x.spec, p = sp.position || {}, h = headline(x);
    const chips = [TF_LABEL[sp.timeframe], sp.underlying === "INDEX" ? "index signals" : "futures signals", p.square_off ? `flat ${p.square_off}` : "positional",
                   p.exit === "position" ? `${p.lots} lots · stop ${p.stop?.futures_pts}` : `stop ${sp.rules.sl_rule.replace("_", " ")}`];
    const st = h && h.s;
    return `<button class="card scard ${sp.code === S.code ? "sel" : ""}" data-code="${esc(sp.code)}">
      <div class="sc-top"><span class="code">${esc(sp.code)}</span><span class="fam fam-${esc(sp.family.replace(/\W+/g, "-"))}">${esc(sp.family)}</span></div>
      <div class="sc-name">${esc(sp.name)}</div>
      <div class="sc-desc">${esc(sp.description)}</div>
      <div class="chips">${chips.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>
      ${st ? `<div class="sc-stats">
          <div><div class="k">Net</div><div class="v ${cls(st.net_inr)}">${inr(st.net_inr)}</div></div>
          <div><div class="k">PF</div><div class="v">${num(st.pf)}</div></div>
          <div><div class="k">Trades</div><div class="v">${st.trades}</div></div>
          <div><div class="k">Win</div><div class="v">${pct(st.wins, st.trades)}</div></div></div>
        <div class="sc-foot muted">${esc(h.m.label)} · ${esc(TYPE_LABEL[h.t])}${h.key !== "-" ? " " + esc(h.key) : ""} · ${esc(h.m.date_from || "")} → ${esc(h.m.date_to || "")}</div>`
        : `<div class="sc-foot muted">${h ? "last run refused: " + esc(h.m.reason || Object.values(h.m.types)[0]?.reason || "") : "not run yet — open it and press Run"}</div>`}
    </button>`;
  }).join("") || `<div class="muted">No strategy matches.</div>`;
  $$("#cards .scard").forEach((b) => b.onclick = () => {
    // from the strip: stay put (the details are right below); from the full grid: collapse it, then go to the details once
    const fromGrid = S.expanded || !S.code;
    S.expanded = false;
    if (fromGrid) { select(b.dataset.code, false); renderCards(); requestAnimationFrame(() => $("#detail").scrollIntoView({ block: "start" })); }
    else keepScroll(() => { select(b.dataset.code, false); renderCards(); });
  });
  const sel = $("#cards .scard.sel");
  if (compact && sel) sel.scrollIntoView({ block: "nearest", inline: "center" });
}

// ------------------------------------------------------------------ selection
function variants(item) {
  // every backtest of the strategy file (run or not) plus every ad hoc run, keyed by run key
  const out = new Map();
  for (const b of item.spec.backtests) out.set(b.run, { run: b.run, label: b.label, bt: b, meta: item.byRun[b.run] || null });
  for (const m of item.runs) if (!out.has(m.run)) out.set(m.run, { run: m.run, label: m.label, bt: null, meta: m });
  return [...out.values()];
}

function select(code, scroll) {
  S.code = code; pref("code", code);
  $$("#cards .scard").forEach((b) => b.classList.toggle("sel", b.dataset.code === code));
  const item = cur(); const vs = variants(item);
  const saved = pref("sel." + code) || {};
  const def = item.spec.backtests.find((b) => b.default);
  const want = vs.find((v) => v.run === saved.run && v.meta) || vs.find((v) => def && v.run === def.run && v.meta) || vs.find((v) => v.meta) || vs.find((v) => def && v.run === def.run) || vs[0];
  S.label = want.label; S.run = want.run; S.resultKey = null;
  Object.assign(S, { type: saved.type || null, exp: saved.exp || "W", strike: saved.strike || item.spec.options.strike_default, side: saved.side || "all" });
  $("#detail").hidden = false;
  const busy = Object.values(S.jobs).some((j) => j.code === code && (j.state === "running" || j.state === "queued"));
  if (!busy) status("");
  renderDetail();
  if (scroll) $("#detail").scrollIntoView({ block: "start" });
}

function save() { pref("sel." + S.code, { run: S.run, type: S.type, exp: S.exp, strike: S.strike, side: S.side }); }

// ------------------------------------------------------------------ detail
function renderDetail() {
  const item = cur(), sp = item.spec;
  $("#d-title").innerHTML = `<span class="code">${esc(sp.code)}</span> ${esc(sp.name)} <span class="fam fam-${esc(sp.family.replace(/\W+/g, "-"))}">${esc(sp.family)}</span>` +
    (sp.version ? ` <span class="ver" title="${esc((sp.version.changes || []).join("\n") || "first version")}">version ${sp.version.version}</span>` : "");
  $("#d-desc").textContent = sp.description;
  $("#d-rules").textContent = rulesSentence(sp);
  renderBacktests();
  renderRunPanel();
  showRun();
}

function renderBacktests() {
  const item = cur(), vs = variants(item);
  const labels = [...new Set(vs.map((v) => v.label))];
  $("#bt-tabs").innerHTML = labels.map((l) => {
    const any = vs.filter((v) => v.label === l), ran = any.find((v) => v.meta);
    const ok = ran && Object.values(ran.meta.types).some((t) => t.status === "ok");
    return `<button class="tab ${l === S.label ? "on" : ""} ${ran ? "" : "dim"}" data-l="${esc(l)}" title="${esc(any[0].bt?.notes || "")}">${esc(l)}${ran && !ok ? " ⊘" : ""}</button>`;
  }).join("");
  $$("#bt-tabs button").forEach((b) => b.onclick = () => keepScroll(() => {
    S.label = b.dataset.l;
    const vsl = variants(cur()).filter((v) => v.label === S.label);
    S.run = (vsl.find((v) => v.meta) || vsl[0]).run; save(); renderBacktests(); renderRunPanel(); showRun();
  }));
  const same = vs.filter((v) => v.label === S.label);
  $("#bt-vars").innerHTML = same.map((v) => {
    const m = v.meta, b = v.bt || {};
    const tf = m ? m.timeframe : (b.timeframe || item.spec.timeframe), und = m ? m.underlying : (b.underlying || item.spec.underlying || "FUT");
    const hold = m ? m.holding : ("square_off" in b ? (b.square_off ? `intraday ${b.square_off}` : "positional") : (item.spec.position?.square_off ? `intraday ${item.spec.position.square_off}` : "positional"));
    return `<button class="seg-b ${v.run === S.run ? "on" : ""} ${m ? "" : "dim"}" data-r="${esc(v.run)}" title="${esc(b.notes || "")}">${TF_LABEL[tf]} candles · ${und === "INDEX" ? "index" : "futures"} signals · ${esc(hold)}${m ? "" : " · not run"}</button>`;
  }).join("");
  $$("#bt-vars button").forEach((b) => b.onclick = () => keepScroll(() => { S.run = b.dataset.r; save(); renderBacktests(); renderRunPanel(); showRun(); }));
}

function renderRunPanel() {
  const item = cur(), v = variants(item).find((x) => x.run === S.run);
  $("#rp-presets").innerHTML = PRESETS.map(([w, l]) => `<button class="chip-t" data-w="${w}">${l}</button>`).join("");
  $$("#rp-presets button").forEach((b) => b.onclick = () => submit({ what: b.dataset.w }));
  $("#rp-this").textContent = v?.meta ? "Re-run this backtest" : "Run this backtest";
  $("#rp-this").onclick = () => {
    if (v?.bt) return submit({ what: "defined:" + v.run }, true);
    const m = v.meta; const q = { what: m.kind === "preset" ? m.preset : m.kind === "all" ? "all" : "custom", from: m.date_from, to: m.date_to, label: m.label,
      tf: m.timeframe, underlying: m.underlying, square_off: m.square_off };
    submit(q, true);
  };
  $("#rp-custom").onclick = () => submit({ what: "custom", from: $("#rp-from").value, to: $("#rp-to").value, label: $("#rp-label").value || undefined });
}

async function submit(q, keepVariant) {
  const types = $$("#rp-types input:checked").map((x) => x.value);
  if (!types.length) { $("#rp-msg").textContent = "Pick at least one type."; return; }
  q = Object.assign({ code: S.code, types }, q);
  if (!keepVariant && !String(q.what).startsWith("defined:")) {
    if ($("#rp-tf").value) q.tf = $("#rp-tf").value;
    if ($("#rp-und").value) q.underlying = $("#rp-und").value;
    const sq = $("#rp-sq").value; if (sq !== "keep") q.square_off = sq === "none" ? null : sq;
  }
  if (q.square_off === undefined) delete q.square_off;
  try {
    const j = await post("/api/backtest", q);
    S.jobs[j.id] = { state: j.state, code: j.code };
    $("#rp-msg").textContent = `Queued: ${j.code} · ${j.label}`;
    status(`<span class="spin"></span> Queued <b>${esc(j.code)} · ${esc(j.label)}</b> — the results appear here when it finishes`, "busy");
    $("#status").scrollIntoView({ block: "nearest" });
    poll();
  } catch (e) { $("#rp-msg").textContent = "Refused: " + e.message; status(`Not run: ${esc(e.message)}`, "bad"); }
}

// ------------------------------------------------------------------ a run: types, KPIs, chart, tabs
function meta() { return cur().byRun[S.run] || null; }

function showRun() {
  const m = meta();
  $("#run-none").hidden = !!m; $("#run-body").hidden = !m;
  if (!m) {
    // an empty state that says what this backtest is and runs it in place (no search for the button above)
    const item = cur(), v = variants(item).find((x) => x.run === S.run), b = v?.bt || {};
    const tf = b.timeframe || item.spec.timeframe, und = b.underlying || item.spec.underlying || "FUT";
    const hold = "square_off" in b ? (b.square_off ? `intraday ${b.square_off}` : "positional") : (item.spec.position?.square_off ? `intraday ${item.spec.position.square_off}` : "positional");
    const period = b.kind === "named" ? `${b.from} → ${b.to}` : b.kind === "preset" ? `the last ${b.preset}` : b.kind === "all" ? "all the data" : "";
    $("#run-none").innerHTML = `<h3>${esc(S.label)} has not been run yet</h3>
      <p class="muted">${esc(S.code)} over ${esc(period)} · ${TF_LABEL[tf]} candles · ${und === "INDEX" ? "index" : "futures"} signals · ${esc(hold)}${b.notes ? " — " + esc(b.notes) : ""}</p>
      <button class="primary" id="run-now">Run it now</button> <span class="muted small">only ${esc(S.code)} runs; usually a few seconds (the learner strategies take 1–2 minutes)</span>`;
    $("#run-now").onclick = () => $("#rp-this").click();
    return;
  }
  $("#run-meta").textContent = `${m.date_from || "?"} → ${m.date_to || "?"} · ${TF_LABEL[m.timeframe]} candles · signals on ${m.underlying === "INDEX" ? "the index" : "futures"} · ${m.holding} · run ${m.at.replace("T", " ")} in ${m.seconds}s` +
    (m.status !== "ok" ? ` · refused: ${m.reason}` : "");
  const ok = Object.keys(m.types).filter((t) => m.types[t].status === "ok");
  if (!S.type || !ok.includes(S.type)) S.type = ok[0] || Object.keys(m.types)[0];
  renderTypes();
}

function optKeys(m) {
  return { fb: Object.keys(m.types.OPT_FUT_SIGNAL?.status === "ok" ? m.types.OPT_FUT_SIGNAL.choices : {}),
           nb: Object.keys(m.types.OPT_NATIVE?.status === "ok" ? m.types.OPT_NATIVE.choices : {}) };
}

function choiceOf(m, t) {
  if (t === "FUT") return "-";
  if (t === "OPT_NATIVE") return `${S.exp}-SCAN`;
  return `${S.exp}-${S.strike}`;
}

function renderTypes() {
  const m = meta(), sp = cur().spec;
  const k = optKeys(m), exps = [...new Set([...k.fb, ...k.nb].map((x) => x[0]))];
  if (exps.length && !exps.includes(S.exp)) S.exp = exps[0];
  const strikes = [...new Set(k.fb.filter((x) => x[0] === S.exp).map((x) => x.slice(2)))];
  if (strikes.length && !strikes.includes(S.strike)) S.strike = strikes.includes(sp.options.strike_default) ? sp.options.strike_default : strikes[0];
  const col = (t) => {
    const tm = m.types[t];
    if (!tm) return "";
    const head = `<h4>${TYPE_LABEL[t]}</h4>`;
    if (tm.status !== "ok") return `<div class="tcol off" data-t="${t}">${head}<div class="muted small">not run: ${esc(tm.reason || "")}</div></div>`;
    const ch = choiceOf(m, t), s = tm.choices[ch];
    if (!s) return `<div class="tcol off" data-t="${t}">${head}<div class="muted small">no ${esc(ch)} result</div></div>`;
    const cov = t === "FUT" ? (s.rl ? `learner: ${s.trades} lot exits · ${s.rl.skipped} declined · ${s.rl.locked} locked` : "exchange futures · every signal priced")
      : t === "OPT_NATIVE" ? `rescans strikes from the index · ${s.trades} priced${s.skipped ? ` · ${s.skipped} without data` : ""}${s.locked ? ` · ${s.locked} locked` : ""}`
      : (s.skipped ? `<span class="warn">${s.trades} priced · ${s.skipped} without option data</span>` : `all ${s.trades} priced`) + (s.locked ? ` · ${s.locked} strike-locked` : "");
    const row = (side, lbl, st) => `<button class="srow ${S.type === t && S.side === side ? "on" : ""}" data-t="${t}" data-s="${side}">
        <span>${lbl}</span><span class="${cls(st?.net_inr)}">${inr(st?.net_inr)}</span><span class="muted">${st ? st.trades + " · " + pct(st.wins, st.trades) : ""}</span></button>`;
    return `<div class="tcol ${S.type === t ? "cur" : ""}" data-t="${t}">${head}<div class="muted small cov">${cov}</div>
      ${row("all", "Long + short", s)}${row("LONG", "Long", s.long)}${row("SHORT", "Short", s.short)}
      ${t !== "FUT" ? row("CE", "CE side", s.ce) + row("PE", "PE side", s.pe) : ""}</div>`;
  };
  $("#types").innerHTML = ["FUT", "OPT_FUT_SIGNAL", "OPT_NATIVE"].map(col).join("");
  $$("#types .srow").forEach((b) => b.onclick = () => { S.type = b.dataset.t; S.side = b.dataset.s; save(); renderTypes(); });
  $$("#types .tcol h4").forEach((h) => h.onclick = () => { const t = h.parentElement.dataset.t; if (m.types[t]?.status === "ok") { S.type = t; S.side = "all"; save(); renderTypes(); } });
  // the options bar: expiry and strike (expiry shared by both option types; the strike is options via futures')
  const ob = $("#optbar");
  ob.hidden = !exps.length;
  if (!ob.hidden) {
    const why = (x) => x?.startsWith("ATR") ? `spot ± ${x.slice(3)}×ATR(${sp.options.atr_period}), OTM` : x === "ATM" ? "the strike nearest spot" : x ? `${x.slice(0, 3)} ${x.slice(3)}: ${x.slice(3)} strike(s) ${x.startsWith("ITM") ? "in" : "out of"} the money` : "";
    ob.innerHTML = `<b>Options</b> <span class="muted">expiry</span>
      <span class="seg">${exps.map((e) => `<button class="${e === S.exp ? "on" : ""}" data-e="${e}">${e === "W" ? "Weekly" : "Monthly"}</button>`).join("")}</span>
      ${strikes.length ? `<span class="muted">strike</span> <select id="strike">${strikes.map((x) => `<option ${x === S.strike ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
      <span class="muted small">${esc(why(S.strike))} (options via futures)</span>` : ""}
      ${k.nb.length ? `<span class="muted small">· standalone options rescan ${esc((sp.options.native_scan?.choices || ["ATR2", "ATM", "ITM1", "OTM1"]).join(" · "))} every ${sp.options.native_scan?.every_minutes || 5} min, one position per side</span>` : ""}`;
    $$("#optbar .seg button").forEach((b) => b.onclick = () => { S.exp = b.dataset.e; save(); renderTypes(); });
    const sel = $("#strike"); if (sel) sel.onchange = (e) => { S.strike = e.target.value; save(); renderTypes(); };
  }
  loadResult();
}

async function loadResult() {
  const m = meta(), t = S.type, tm = m.types[t];
  if (!tm || tm.status !== "ok") { $("#res").hidden = true; return; }
  const ch = choiceOf(m, t);
  if (!tm.choices[ch]) { $("#res").hidden = true; return; }
  $("#res").hidden = false;
  $("#crumb").textContent = `${S.code} › ${m.label} (${TF_LABEL[m.timeframe]}) › ${TYPE_LABEL[t]} › ${S.side === "all" ? "long + short" : S.side === "CE" || S.side === "PE" ? S.side + " side" : S.side.toLowerCase()}${ch !== "-" ? " · " + ch : ""}`;
  const key = [S.code, S.run, t, ch].join("|");
  if (S.resultKey !== key) {
    S.result = await api("/api/result?" + new URLSearchParams({ code: S.code, run: S.run, type: t, choice: ch }));
    S.resultKey = key; S.chartKey = null;
  }
  const C = S.C = Object.fromEntries(S.result.cols.map((k, i) => [k, i]));
  S.rows = S.result.trades.filter((r) => S.side === "all" || r[C.position] === S.side || r[C.opt_type] === S.side);
  renderKPIs();
  chart.setContext({ code: S.code, run: m, type: t, choice: ch, result: S.result, spec: cur().spec, rows: S.rows });
  if (S.chartKey !== key) {                       // a new result opens on its last trading day; a side switch keeps the day
    S.chartKey = key;
    const last = S.rows[S.rows.length - 1];
    chart.open(last ? last[C.entry_time].slice(0, 10) : m.date_to);
  } else if (chart.data) chart.redraw();
  renderTabs();
}

function renderKPIs() {
  const C = S.C, rows = S.rows;
  const net = rows.map((r) => r[C.net]), sum = (a) => a.reduce((x, y) => x + y, 0);
  const wins = net.filter((v) => v > 0), loss = net.filter((v) => v <= 0);
  let eq = 0, peak = 0, dd = 0; for (const v of [...rows].sort((a, b) => (a[C.exit_time] < b[C.exit_time] ? -1 : 1)).map((r) => r[C.net])) { eq += v; peak = Math.max(peak, eq); dd = Math.min(dd, eq - peak); }
  const positions = new Set(rows.map((r) => r[C.entry_time] + r[C.instrument])).size;
  const rs = rows.filter((r) => r[C.sl] != null && r[C.entry_px] !== r[C.sl]).map((r) => r[C.pts] / Math.abs(r[C.entry_px] - r[C.sl]));
  const open = rows.filter((r) => r[C.open]).length;
  const tiles = [
    ["Net P&L", inr(sum(net)), cls(sum(net)), `gross ${inr(sum(rows.map((r) => r[C.gross])))} − charges ${inr(sum(rows.map((r) => r[C.charges])))}`],
    [positions !== rows.length ? "Positions" : "Trades", `${positions !== rows.length ? positions : rows.length}`, "",
     (positions !== rows.length ? `${rows.length} lot exits · ` : "") + `${rows.filter((r) => r[C.position] === "LONG").length} long · ${rows.filter((r) => r[C.position] === "SHORT").length} short`],
    ["Win rate", pct(wins.length, rows.length), "", `${wins.length} winners`],
    ["Profit factor", loss.length && sum(loss) ? num(sum(wins) / -sum(loss)) : "–", "", ""],
    ["Max drawdown", inr(dd), "neg", "closed net, by exit time"],
    ["Expectancy", inr(rows.length ? sum(net) / rows.length : null), cls(sum(net)), rs.length ? `${num(sum(rs) / rs.length)} R per trade` : "per trade"],
  ];
  const b = baseline();
  if (b) tiles.push(b);
  $("#kpis").innerHTML = tiles.map(([k, v, c, sub]) => `<div class="kpi"><div class="k">${k}</div><div class="v ${c}">${v}</div><div class="s muted">${esc(sub)}</div></div>`).join("");
  $("#kpi-note").textContent = (S.result.skipped.length ? `${S.result.skipped.length} signal(s) not taken (listed under Trades) · ` : "") +
    (open ? `${open} position(s) still open at the window end, valued there (*)` : "");
}

function baseline() {
  // the same backtest on the strategy's previous version (history), long + short only
  const m = meta(); if (!m.baseline || S.side !== "all") return null;
  const ch = choiceOf(m, S.type), old = m.baseline.results?.[S.type]?.[ch];
  const now = m.types[S.type].choices[ch];
  const tip = (m.version?.changes || []).slice(0, 4).join("; ");
  if (!old) return [`vs version ${m.baseline.version}`, "new", "", `not run in version ${m.baseline.version}`];
  const d = now.net_inr - old.net_inr;
  return [`vs version ${m.baseline.version}`, (d >= 0 ? "+" : "") + inr(d), cls(d), `was ${inr(old.net_inr)} · ${old.trades} trades · PF ${num(old.pf)}${tip ? " · changed: " + tip : ""}`];
}

// ------------------------------------------------------------------ tabs
function tabCtx() {
  const m = meta();
  return { spec: cur().spec, run: m, runs: cur().runs, type: S.type, choice: choiceOf(m, S.type), side: S.side, result: S.result, rows: S.rows,
           onOpenDay: (d) => { chart.open(d); $("#chart-card").scrollIntoView({ behavior: "smooth", block: "start" }); },
           onOpenAt: (t) => { chart.focusTime = tsOf(t); chart.open(t.slice(0, 10)); $("#chart-card").scrollIntoView({ behavior: "smooth", block: "start" }); },
           onPickChoice: (c) => { if (c.includes("-")) { S.exp = c[0]; if (!c.endsWith("SCAN")) S.strike = c.slice(2); } save(); renderTypes(); } };
}

function renderTabs() {
  const ctx = tabCtx();
  let list = [{ id: "trades", label: "Trades" }];
  try { list = list.concat(T.tabsFor(ctx)); } catch (e) { console.error(e); }
  if (!list.some((x) => x.id === S.tab)) S.tab = "trades";
  $("#tabs").innerHTML = list.map((x) => `<button class="tab ${x.id === S.tab ? "on" : ""}" data-id="${x.id}">${esc(x.label)}</button>`).join("");
  $$("#tabs button").forEach((b) => b.onclick = () => { S.tab = b.dataset.id; pref("tab", S.tab); renderTabs(); });
  const el = $("#tab-body");
  if (S.tab === "trades") renderTrades(el);
  else { try { T.renderTab(S.tab, el, ctx); } catch (e) { el.innerHTML = `<div class="warn">This tab failed: ${esc(e.message)}</div>`; console.error(e); } }
}

function renderTrades(el) {
  const C = S.C, t = S.type, rows = S.rows;
  const isOpt = t !== "FUT", fb = t === "OPT_FUT_SIGNAL", lots = rows.some((r) => r[C.tranche]);
  const cols = [
    ["#", null, "r"], ["Position", (r) => r[C.label] || r[C.position], "l"],
    ...(isOpt ? [["Expiry", (r) => r[C.expiry], "l"], ["Strike", (r) => r[C.strike], "r"], ["Right", (r) => r[C.opt_type], "l"]] : [["Instrument", (r) => r[C.instrument], "l"]]),
    ["Signal", (r) => r[C.signal], "l"], ["Entry", (r) => r[C.entry_time], "l"], ["Entry px", (r) => r[C.entry_px], "r"], ["SL", (r) => r[C.sl], "r"],
    ["Exit", (r) => r[C.exit_time], "l"], ["Exit px", (r) => r[C.exit_px], "r"], ["Reason", (r) => r[C.exit_reason], "l"],
    ...(lots ? [["Lots", (r) => r[C.lots], "r"]] : []),
    ...(fb ? [["Fut in → out", (r) => r[C.und_entry], "r"]] : []),
    ["Max profit", (r) => r[C.mfe], "r"], ["Max loss", (r) => r[C.mae], "r"], ["Points", (r) => r[C.pts], "r"],
    ["Gross", (r) => r[C.gross], "r"], ["Charges", (r) => r[C.charges], "r"], ["Net", (r) => r[C.net], "r"], ["Cum. net", null, "r"]];
  const f = ($("#t-filter")?.value || "").toLowerCase();
  const list = rows.map((r, i) => ({ r, i })).filter(({ r }) => !f || r.join(" ").toLowerCase().includes(f));
  let cum = 0; const cumOf = new Map(); for (const { r, i } of [...list].sort((a, b) => (a.r[C.entry_time] < b.r[C.entry_time] ? -1 : 1))) { cum += r[C.net]; cumOf.set(i, cum); }
  if (S.sortCol != null && cols[S.sortCol] && cols[S.sortCol][1]) { const g = cols[S.sortCol][1]; list.sort((a, b) => { const x = g(a.r), y = g(b.r); return (x < y ? -1 : x > y ? 1 : 0) * S.sortDir; }); }
  else list.reverse();
  const cell = (name, r, i) => {
    const v = (k) => r[C[k]];
    switch (name) {
      case "#": return i + 1;
      case "Position": return `<span class="pill ${v("position") === "LONG" ? "pl" : "ps"}">${esc(v("label") || v("position"))}</span>${v("stale") ? ' <span class="pill pw" title="priced on an earlier candle">stale</span>' : ""}${v("scan") ? ` <span class="muted small">${esc(v("scan"))}</span>` : ""}`;
      case "Expiry": return esc(v("expiry")); case "Strike": return esc(v("strike")); case "Right": return esc(v("opt_type"));
      case "Instrument": return esc(v("instrument")); case "Signal": return esc(v("signal"));
      case "Entry": return esc(v("entry_time").slice(0, 16)); case "Exit": return esc(v("exit_time").slice(0, 16)) + (v("open") ? " *" : "");
      case "Entry px": return num(v("entry_px")); case "SL": return num(v("sl")); case "Exit px": return num(v("exit_px"));
      case "Reason": return `<span class="pill">${esc(reasonTag(v("exit_reason")))}</span>`;
      case "Lots": return v("lots");
      case "Fut in → out": return `${num(v("und_entry"), 1)} → ${num(v("und_exit"), 1)}`;
      case "Max profit": return `<span title="${inr((v("mfe") || 0) * (S.result.lot_size || 65))} per lot">${num(v("mfe"), 1)}</span>`;
      case "Max loss": return `<span title="${inr((v("mae") || 0) * (S.result.lot_size || 65))} per lot">${num(v("mae"), 1)}</span>`;
      case "Points": return `<span class="${cls(v("pts"))}">${num(v("pts"), 1)}</span>`;
      case "Gross": return `<span class="${cls(v("gross"))}">${inr(v("gross"))}</span>`;
      case "Charges": { const p = v("chg_parts") || {}; return `<span title="${esc(Object.entries(p).map(([k, x]) => `${k} ₹${x}`).join("\n"))}">${inr(v("charges"))}</span>`; }
      case "Net": return `<span class="${cls(v("net"))}">${inr(v("net"))}${v("open") ? "*" : ""}</span>`;
      case "Cum. net": return `<span class="${cls(cumOf.get(i))}">${inr(cumOf.get(i))}</span>`;
    }
    return "";
  };
  const sk = S.result.skipped, why = (p) => sk.filter((x) => String(x.why || "").startsWith(p)).length;
  const nLock = why("strike locked"), nDecl = why("learner skipped"), nData = sk.length - nLock - nDecl;
  el.innerHTML = `<div class="row between wrap gap"><div class="muted small">${list.length} of ${rows.length} trades · click a row to open it on the chart · click a header to sort</div>
      <input id="t-filter" type="search" placeholder="filter (date, reason, strike…)" value="${esc(f)}"></div>
    <div class="tablewrap tall"><table class="tbl"><tr>${cols.map(([h, , a], k) => `<th class="${a === "l" ? "l" : ""}" data-k="${k}">${h}${S.sortCol === k ? (S.sortDir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr>
      ${list.map(({ r, i }) => `<tr class="click" data-i="${i}">${cols.map(([h, , a]) => `<td class="${a === "l" ? "l" : ""}">${cell(h, r, i)}</td>`).join("")}</tr>`).join("")}</table></div>
    <details class="skipped"><summary>${sk.length} signal(s) not taken: ${nData} without option data or other · ${nLock} strike lock · ${nDecl} declined by the learner</summary>
      <div class="tablewrap"><table class="tbl"><tr><th class="l">time</th><th class="l">position</th><th class="l">right</th><th class="l">instrument</th><th class="l">why</th></tr>
      ${sk.slice(0, 3000).map((x) => `<tr><td class="l">${esc(x.entry_time)}</td><td class="l">${esc(x.position)}</td><td class="l">${esc(x.opt_type)}</td><td class="l">${esc(x.instrument)}</td><td class="l">${esc(x.why)}</td></tr>`).join("")}</table></div></details>`;
  $("#t-filter").oninput = () => { const p = $("#t-filter").selectionStart; renderTrades(el); const n = $("#t-filter"); n.focus(); n.setSelectionRange(p, p); };
  $$("th", el).forEach((th) => th.onclick = () => { const k = +th.dataset.k; if (S.sortCol === k) S.sortDir = -S.sortDir; else { S.sortCol = k; S.sortDir = 1; } renderTrades(el); });
  $$("tr.click", el).forEach((tr) => tr.onclick = () => {
    const r = rows[+tr.dataset.i];
    chart.focusTime = tsOf(r[C.entry_time]);
    chart.open(r[C.entry_time].slice(0, 10), null, isOpt ? r[C.instrument] : null);
    $("#chart-card").scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

// ------------------------------------------------------------------ status + stable scrolling
// One status line at the top of the details says what is happening (running / done / failed / refused), so a change
// below never comes unannounced; re-renders keep the reader's scroll position.
function status(text, kind) {
  const el = $("#status");
  el.hidden = !text; el.className = "status " + (kind || ""); el.innerHTML = text || "";
}
function keepScroll(fn) {
  const y = window.scrollY;
  const r = fn();
  requestAnimationFrame(() => window.scrollTo(0, y));
  return r;
}
function flash(el) {
  if (!el) return;
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
}

// ------------------------------------------------------------------ jobs
let pollT = null;
async function poll() {
  clearTimeout(pollT);
  let st; try { st = await api("/api/status"); } catch (e) { pollT = setTimeout(poll, 5000); return; }
  $("#jobs").innerHTML = st.jobs.slice(0, 4).map((j) => `<span class="job ${j.state}" title="${esc((j.log || []).join("\n") || j.error || "")}">${esc(j.code)} ${esc(j.label)} · ${j.state}${j.seconds != null ? " " + j.seconds + "s" : ""}</span>`).join("");
  const mine = st.jobs.find((j) => j.code === S.code && (j.state === "running" || j.state === "queued"));
  if (mine) status(`<span class="spin"></span> ${mine.state === "running" ? "Running" : "Queued"} <b>${esc(mine.code)} · ${esc(mine.label)}</b> — the results appear here when it finishes (usually a few seconds; the learner takes 1–2 minutes)`, "busy");
  for (const j of st.jobs) {
    const was = S.jobs[j.id];
    if (was && was.state !== j.state && (j.state === "done" || j.state === "failed")) {
      if (j.code === S.code) {
        if (j.state === "failed") status(`<b>${esc(j.code)} · ${esc(j.label)}</b> failed: ${esc(j.error || "")}`, "bad");
        $("#rp-msg").textContent = j.state === "done" ? `${j.code} ${j.label}: done in ${j.seconds}s` : `${j.code} ${j.label}: failed — ${j.error}`;
      }
      if (j.state === "done") {
        await load(); keepScroll(() => { renderFilters(); renderCards(); });
        if (j.code === S.code) {
          S.run = j.run; S.label = cur().byRun[j.run]?.label || S.label; S.resultKey = null; save();
          keepScroll(() => renderDetail());
          const m = meta(), ok = m && Object.values(m.types).some((t) => t.status === "ok");
          status(ok ? `<b>${esc(j.code)} · ${esc(j.label)}</b> done in ${j.seconds}s — showing its results below`
                    : `<b>${esc(j.code)} · ${esc(j.label)}</b> finished, but every type was refused: ${esc(m?.reason || Object.values(m?.types || {})[0]?.reason || "")}`, ok ? "good" : "bad");
          const target = ok ? $("#run-body") : $("#run-none");
          setTimeout(() => { target.scrollIntoView({ behavior: "smooth", block: "start" }); flash(target); }, 150);
        }
      }
    }
    S.jobs[j.id] = { state: j.state, code: j.code };
  }
  pollT = setTimeout(poll, st.busy ? 1000 : 8000);
}

// ------------------------------------------------------------------ start
async function start() {
  chart = new ChartView($("#chart-view"));
  $("#search").oninput = (e) => { S.search = e.target.value.trim().toLowerCase(); renderCards(); };
  $("#sort").onchange = (e) => { S.sort = e.target.value; pref("sort", S.sort); renderCards(); };
  $("#cards-toggle").onclick = () => { S.expanded = !S.expanded; renderCards(); };
  try { await load(); } catch (e) { $("#cards").innerHTML = `<div class="warn">Server not reachable: ${esc(e.message)}</div>`; return; }
  renderFilters(); renderCards();
  const code = pref("code"); if (code && S.list.some((x) => x.spec.code === code)) { select(code, false); renderCards(); }
  poll();
}
start();
