// City / tap-water view: impact hero (plant days, $, ban days and what living cover would avoid), KPI strip with
// sources, replay of the measured river with an adoption slider, river model chart, hotspot map, 14-day outlook.
/* global maplibregl */
import { esc, fmt, fmtDate, fmtInt, isNum, link, naturalFreq, pct, plural, segmented, shareAsFreq, usd, LEAK_RAMP, parseDate, band } from "./util.js";
import { colors, legendHTML, timeChart, toXY } from "./charts.js";
import { addContext, addPlaces, addRivers, addSites, bboxOf, createMap, quantileBreaks, rampLegend, stepExpr } from "./map.js";
import { ensure, factsMap, mockChip, nasaStrip } from "./data.js";

const PRIMARY = "05484500";
const nwisUrl = (site) => `https://waterdata.usgs.gov/monitoring-location/${site}/`;
const shortSite = (name) => String(name || "").split(",")[0];
const riverOnly = (name) => shortSite(name).replace(/ at .*/, "");

let S; // store
let F; // facts map
let YEAR; // replay year
let LEVEL = 25; // adoption %

export function renderCity(store) {
  S = store;
  F = factsMap(store.data.facts);
  const ys = years();
  YEAR = ys.includes(S.data.scenarios?.replay?.year) ? S.data.scenarios.replay.year : ys[ys.length - 1] ?? 2025;
  document.getElementById("nasa-strip-city").innerHTML = nasaStrip(S.data.meta);
  initYearSwitch(ys);
  initSliders();
  renderYear();
}

// River chart + outlook: drawn once river_series / validation / outlook have loaded (after the hero).
export function renderCityRiver() {
  renderRiver();
  renderOutlook();
}

// ------------------------------------------------------------------ scenario access
function years() {
  const sc = S.data.scenarios;
  if (!sc) return [];
  const fromReplays = Object.keys(sc.replays || {}).map(Number).filter((y) => sc.by_year?.[y] || sc.by_year?.[String(y)]);
  const ys = fromReplays.length ? fromReplays : sc.replay?.year != null ? [Number(sc.replay.year)] : [];
  return [...new Set(ys)].sort((a, b) => a - b);
}
function replayFor(y) {
  const sc = S.data.scenarios;
  return sc?.replays?.[y] ?? sc?.replays?.[String(y)] ?? (Number(sc?.replay?.year) === y ? sc.replay : null);
}
function yearBlock(y = YEAR) {
  const sc = S.data.scenarios;
  return sc?.by_year?.[y] ?? sc?.by_year?.[String(y)] ?? null;
}
function levelsFor(y = YEAR) {
  return (yearBlock(y)?.levels || []).slice().sort((a, b) => a.x - b.x);
}
function levelAt(x, y = YEAR) {
  const lv = levelsFor(y);
  if (!lv.length) return null;
  return lv.reduce((best, l) => (Math.abs(l.x - x) < Math.abs(best.x - x) ? l : best), lv[0]);
}
// avoided[key] (computed inside each draw by the exporter) or, failing that, level 0 minus level x.
function avoided(lvl, key, y = YEAR) {
  const av = lvl?.avoided?.[key];
  if (av) { const b = band(av); if (b) return { mid: b.mid, lo: Math.min(b.lo, b.hi), hi: Math.max(b.lo, b.hi) }; }
  const base = levelsFor(y)[0];
  const b0 = band(base?.[key]), bx = band(lvl?.[key]);
  if (!b0 || !bx) return null;
  const sign = key === "lbN_kept" ? -1 : 1;
  const a = sign * (b0.mid - bx.hi), b = sign * (b0.mid - bx.lo);
  return { mid: Math.max(0, sign * (b0.mid - bx.mid)), lo: Math.max(0, Math.min(a, b)), hi: Math.max(0, Math.max(a, b)) };
}
// Trial-evidence-only result for the same level (scenarios.json levels[].trials_only), when the export has it.
function trialsOnly(lvl, key) {
  const t = lvl?.trials_only;
  if (!t) return null;
  const b = band(t.avoided?.[key] ?? t[key]);
  return b ? { mid: b.mid, lo: Math.min(b.lo, b.hi), hi: Math.max(b.lo, b.hi) } : null;
}
// Plain-language definition of the slider's X (scenarios.json x_definition, string or {text|label}).
function xDefinition() {
  const d = S.data.scenarios?.x_definition;
  if (!d) return "";
  return typeof d === "string" ? d : d.text || d.label || d.short || "";
}
// Share of focus-area fields where NASA HLS sees winter living cover (a lower bound on cover-crop use).
// From the export when present (scenarios.hls_winter_cover_pct / x_definition / facts); otherwise the fields module's
// published detection rate (notes/fields.md: 0.5-4.2% of fields per winter, 2020-26).
const HLS_SEEN_FALLBACK = { lo: 1, hi: 4 };
function hlsSeen() {
  const sc = S.data.scenarios || {};
  const xd = typeof sc.x_definition === "object" ? sc.x_definition : null;
  const f = F.hls_winter_cover_pct;
  const c = sc.hls_winter_cover_pct ?? xd?.hls_winter_cover_pct ?? xd?.hls_seen_pct ?? (f ? (f.range || f.value) : null);
  if (isNum(c)) return { lo: c, hi: c };
  if (c && isNum(c.lo) && isNum(c.hi)) return { lo: c.lo, hi: c.hi };
  return HLS_SEEN_FALLBACK;
}
function coverToday() {
  const c = fact("iowa_cover_share_pct");
  return c ? Math.round(c.value) : null;
}
function siteName(site) {
  const rs = S.data.river_series?.sites?.[site];
  const st = (S.data.sites || []).find((s) => s.site === site);
  return rs?.name || st?.name || site;
}
function fact(key) {
  const f = F[key];
  return f && isNum(f.value) ? f : null;
}
const srcLine = (...parts) => parts.filter(Boolean).join(" · ");
const rangeTxt = (b, f = fmtInt) => (b ? (Math.round(b.lo) === Math.round(b.hi) ? "" : `range ${f(b.lo)}–${f(b.hi)}`) : "");
const usdRange = (lo, hi) => {
  const a = usd(lo), b = usd(hi);
  if (a === b) return a;
  const ua = a.slice(-1), ub = b.slice(-1);
  return ua === ub && /[kM]/.test(ua) ? `${a.slice(0, -1)}–${b.slice(1)}` : `${a}–${b}`;
};

// Tooltip that also works on touch (focus) and with keyboard.
function tip(text, body) {
  return `<span class="tip" tabindex="0">${text}<span class="tip-body" role="tooltip">${body}</span></span>`;
}

// ------------------------------------------------------------------ year switch + sliders
function initYearSwitch(ys) {
  const box = document.getElementById("year-switch");
  if (ys.length < 2) { box.hidden = true; return; }
  segmented(box, ys.map((y) => ({ value: String(y), label: `Replay ${y}` })), String(YEAR), (v) => {
    YEAR = Number(v);
    renderYear();
    redrawRiver?.();
  });
}

function initSliders() {
  const sc = S.data.scenarios;
  const lv = levelsFor();
  const xs = (sc?.adoption_levels?.length ? sc.adoption_levels : lv.map((l) => l.x)).filter(isNum);
  const sliders = [...document.querySelectorAll(".js-adopt")];
  if (!xs.length) { sliders.forEach((s) => (s.disabled = true)); return; }
  const min = Math.min(...xs), max = Math.max(...xs), step = xs.length > 1 ? xs[1] - xs[0] : 5;
  LEVEL = xs.includes(25) ? 25 : xs[Math.floor(xs.length / 2)];
  for (const s of sliders) {
    s.min = min; s.max = max; s.step = step; s.value = LEVEL;
    s.addEventListener("input", () => setLevel(Number(s.value)));
  }
  document.querySelector(".slider-ticks").innerHTML = `<span>${min}%</span><span>${(min + max) / 2}%</span><span>${max}%</span>`;
}

function setLevel(x) {
  LEVEL = x;
  document.querySelectorAll(".js-adopt").forEach((s) => { if (Number(s.value) !== x) s.value = x; });
  renderImpact();
  updateReplay();
}
function sliderText(x) {
  const today = coverToday();
  return x > 0 ? `${x}%: cover on ${shareAsFreq(x)} of all upstream corn and soy acres${today != null ? `, beyond the ${today}% already covered` : ""}` : "0%: no added cover";
}

function renderYear() {
  document.querySelectorAll(".js-replay-year").forEach((e) => (e.textContent = YEAR));
  renderHero();
  renderKpis();
  buildReplay();
  renderImpact();
  updateReplay();
}

// ------------------------------------------------------------------ hero
function yearFacts(y = YEAR) {
  const yb = yearBlock(y);
  const obs = yb?.observed || {};
  const th = S.data.scenarios?.thresholds || {};
  const plantF = fact(`plant_days_${y}`);
  const plantDays = plantF?.value ?? (isNum(obs.plant_days) ? obs.plant_days : null);
  const prior = fact("plant_days_record_prior");
  const record = isNum(plantDays) && prior && plantDays > prior.value && (!isNum(prior.year) || y > prior.year);
  const costF = fact(`plant_cost_${y}_usd`);
  const omF = fact(`plant_om_cost_${y}_usd`);
  const c0 = th.cost_per_plant_day;
  const cpd = c0 && isNum(c0.lo) && isNum(c0.hi) ? { lo: c0.lo, hi: c0.hi, mid: (c0.lo + c0.hi) / 2 } : band(c0);
  const est = !costF && isNum(plantDays) && cpd ? { lo: plantDays * cpd.lo, hi: plantDays * cpd.hi } : null;
  const banF = fact(`ban_days_${y}`);
  const banDays = banF?.value ?? (isNum(obs.ban_days) ? obs.ban_days : null);
  // homes were released earlier than businesses/government: fact range lo (or observed.ban_days_homes)
  const banHomes = isNum(obs.ban_days_homes) ? obs.ban_days_homes : isNum(banF?.range?.lo) ? banF.range.lo : null;
  // "for businesses" only when the fact says the headline day count is the business/government one (2026);
  // in 2025 the headline 56 days is the all-customer Stage III window (businesses: 48), so it reads "up to 56".
  const banBiz = isNum(banDays) && new RegExp(`\\b${banDays} days for business`, "i").test(banF?.label || "");
  const people = fact("people_served");
  const peopleTxt = people ? `${fmtInt(people.value)}${/more than|over/i.test(`${people.label} ${people.quote || ""}`) ? "+" : ""}` : null;
  return { yb, obs, th, plantF, plantDays, record, costF, omF, cpd, est, banF, banDays, banHomes, banBiz, people, peopleTxt };
}

function renderHero() {
  const h = document.getElementById("city-h");
  const yf = yearFacts();
  if (!yf.yb) { h.textContent = "Scenario data is not available yet."; return; }
  // Numbers from facts.json (via aliases) or the scenario's observed block; cost and the second ban figure live in the
  // KPI strip below so the headline reads in one breath.
  const plant = isNum(yf.plantDays) ? `${yf.record ? "a record " : ""}<strong>${fmtInt(yf.plantDays)} ${plural(yf.plantDays, "day")}</strong> of nitrate treatment` : "";
  let ban = "";
  if (isNum(yf.banDays)) {
    const homes = isNum(yf.banHomes) && yf.banHomes < yf.banDays;
    ban = !homes ? `a lawn&#8209;watering ban of <strong class="red">${fmtInt(yf.banDays)} days</strong>`
      : yf.banBiz ? `a lawn&#8209;watering ban of <strong class="red">${fmtInt(yf.banHomes)} days for homes</strong> <span class="hero-cost">(${fmtInt(yf.banDays)} for businesses)</span>`
      : `a lawn&#8209;watering ban of <strong class="red">up to ${fmtInt(yf.banDays)} days</strong>`;
  }
  const what = [plant, ban].filter(Boolean).join(" and ");
  h.innerHTML = what
    ? `<span class="hero-main">Bare farm fields upstream cost Des Moines ${what} in <span class="hero-year">${YEAR}</span>.</span> <span class="hero-sub">NASA satellites show which fields sit bare on wet soil — and when.</span>`
    : `NASA satellites show which fields upstream of Des Moines sit bare on wet soil — and when.`;
}

// "~3 weeks" / "5 days": ban changes in a unit that cannot be confused with plant days
function banSpan(d) {
  if (!isNum(d)) return { n: "–", u: "" };
  if (d >= 10.5) { const w = Math.round(d / 7); return { n: `~${w}`, u: plural(w, "week") }; }
  const n = Math.round(d);
  return { n: `~${n}`, u: plural(n, "day") };
}
const fmtMass = (v) => (!isNum(v) ? { n: "–", u: "" } : v >= 1e6 ? { n: (v / 1e6).toFixed(1), u: "million lb" } : v >= 1e3 ? { n: fmtInt(v / 1e3), u: "thousand lb" } : { n: fmtInt(v), u: "lb" });

function renderImpact() {
  const lvl = levelAt(LEVEL);
  const text = document.getElementById("impact-text");
  const tiles = document.getElementById("impact-tiles");
  const fine = document.getElementById("impact-fine");
  const today = coverToday();
  document.getElementById("adopt-hero-frac").textContent = LEVEL > 0 ? shareAsFreq(LEVEL) : "none";
  document.getElementById("adopt-hero-pct").textContent = `${LEVEL}%`;
  document.getElementById("adopt-hero-today").textContent = today != null ? `, beyond the ~${today}% already covered` : "";
  document.querySelectorAll(".js-adopt").forEach((el) => el.setAttribute("aria-valuetext", sliderText(LEVEL)));
  if (!lvl) { text.textContent = "Scenario results are not available yet."; tiles.innerHTML = ""; return; }
  const yf = yearFacts();
  const th = yf.th;
  const sc = S.data.scenarios;
  const kept = avoided(lvl, "lbN_kept"), pd = avoided(lvl, "plant_days"), ban = avoided(lvl, "ban_days"), cost = avoided(lvl, "cost_usd");
  const banTest = th.calibration?.ban?.test_2026;
  const banTip = `Ban days come from a proxy rule (the utility's rules are not public)${th.ban_rule ? `: ${esc(th.ban_rule)}` : ""}. Fitted on 2025, tested on 2026${banTest ? `: ${fmtInt(banTest.pred_days)} proxy days vs ${fmtInt(banTest.true_days)} real` : ""}. Demand and treatment capacity also drive bans, so treat this as indicative.`;
  const banLabel = `<span class="muted">${tip("indicative (proxy rule)", banTip)}</span>`;
  const km = fmtMass(kept?.mid), bs = banSpan(ban?.mid);
  if (lvl.x === 0) {
    text.innerHTML = `Move the slider: what if more upstream corn and soy acres kept living roots over winter?`;
  } else {
    const pdN = Math.round(pd?.mid ?? 0);
    text.innerHTML = `If cover went on <strong>${shareAsFreq(lvl.x)}</strong> of all upstream corn and soy acres${today != null ? ` (beyond today's ~${today}%)` : ""}: about <strong>${km.n} ${km.u} of nitrogen</strong> stays on the fields, <strong>${fmtInt(pdN)} fewer plant ${plural(pdN, "day")}</strong>${pd && rangeTxt(pd) ? ` (${rangeTxt(pd)})` : ""}, a watering ban <strong>${bs.n} ${bs.u} shorter</strong> <span class="muted">(${tip("indicative, proxy rule", banTip)})</span>, and <strong>~${usd(cost?.mid)}</strong> operating cost avoided (estimate).`;
  }
  const lbRange = (b) => (b && Math.round(b.lo) !== Math.round(b.hi) ? `range ${fmtLbRange(b.lo, b.hi)}` : "");
  const toTxt = {
    lbN_kept: (b) => { const m = fmtMass(b.mid); return `${m.n} ${m.u}`; },
    plant_days: (b) => `${fmtInt(b.mid)} fewer plant ${plural(b.mid, "day")}`,
    ban_days: (b) => { const x = banSpan(b.mid); return `ban ${x.n} ${x.u} shorter`; },
    cost_usd: (b) => usd(b.mid),
  };
  const t = [
    { k: "lbN_kept", b: kept, v: `${km.n}<span class="itile-u"> ${km.u}</span>`, l: "of nitrogen kept on upstream fields instead of reaching the river", r: lbRange(kept) },
    { k: "plant_days", b: pd, v: `${fmtInt(pd?.mid)}<span class="itile-u"> fewer plant ${plural(pd?.mid ?? 0, "day")}</span>`, l: "the city's nitrate-removal plant runs less", r: rangeTxt(pd) ? `${rangeTxt(pd)} days` : "" },
    { k: "ban_days", b: ban, v: `${bs.n}<span class="itile-u"> ${bs.u} shorter</span>`, l: `lawn-watering ban ${banLabel}`, r: rangeTxt(ban) ? `${rangeTxt(ban)} days` : "" },
    { k: "cost_usd", b: cost, v: `${usd(cost?.mid)}`, l: `operating cost avoided <span class="muted">(estimate)</span>`, r: cost ? rangeTxt(cost, usd) : "" },
  ];
  const zero = lvl.x === 0;
  tiles.innerHTML = t.map((x) => {
    const tr = zero ? null : trialsOnly(lvl, x.k);
    return `<div class="itile"><div class="itile-v ${zero ? "zero" : ""}">${x.v}</div><div class="itile-l">${x.l}</div><div class="itile-r">${zero ? "&nbsp;" : x.r || "&nbsp;"}</div>${tr ? `<div class="itile-t">trials only: ${toTxt[x.k](tr)}</div>` : ""}</div>`;
  }).join("") + mockChip(S.source, "scenarios");
  const cpd = yf.cpd;
  const nDraws = sc?.method_detail?.n_draws;
  const cover = fact("iowa_cover_share_pct");
  const hs = hlsSeen();
  const xd = xDefinition();
  const anyTrials = levelsFor().some((l) => l.trials_only);
  fine.innerHTML = [
    xd ? `<strong>What the slider means:</strong> ${esc(xd)}${/[.!?]$/.test(xd.trim()) ? "" : "."}` : "",
    `Ranges: 8 in 10${isNum(nDraws) ? ` of ${fmtInt(nDraws)}` : ""} simulations${anyTrials ? "; “trials only” = Iowa field-trial evidence alone, without our satellite-trained river model" : ""}.`,
    `$ = operating cost only${cpd ? ` (plant days × ${usd(cpd.lo)}–${usd(cpd.hi)} a day)` : ""}; capital is not avoided.`,
    cover ? `Today about ${Math.round(cover.value)}% of Iowa corn and soy acres have cover (${link(cover.url, cover.source || "source")}).` : "",
    `NASA HLS sees winter cover on only ~${Math.round(hs.lo) === Math.round(hs.hi) ? fmtInt(hs.lo) : `${fmtInt(hs.lo)}–${fmtInt(hs.hi)}`}% of focus-area fields: a lower bound, because small or late-planted covers aren't visible from space.`,
    "The river may take more than one season to respond (nitrate stored in soils).",
  ].filter(Boolean).join(" ");
}

// ------------------------------------------------------------------ KPI strip
function renderKpis() {
  const yf = yearFacts();
  const { obs, th } = yf;
  const site = yf.yb?.site || PRIMARY;
  const chipSc = mockChip(S.source, "scenarios"), chipF = mockChip(S.source, "facts");
  const measured = obs.measured_days;
  let costV = "–", costL = "spent removing nitrate", costS = "";
  if (yf.costF) {
    costV = usd(yf.costF.value);
    const capital = yf.omF ? yf.costF.value - yf.omF.value : null;
    costL = `spent removing nitrate, <strong>incl. capital</strong>${yf.omF ? ` (${usd(yf.omF.value)} operating + ${usd(capital)} capital)` : ""}`;
    costS = link(yf.costF.url, yf.costF.source || "source");
  } else if (yf.est) {
    costV = `~${usdRange(yf.est.lo, yf.est.hi)}`;
    costL = `removal cost, <strong>estimate</strong>: ${fmtInt(yf.plantDays)} days × ${usd(yf.cpd.lo)}–${usd(yf.cpd.hi)}/day, operating only (no full-year figure published)`;
    const src = (th.sources || []).find((s) => /cost_per_day|om_cost/.test(s.id));
    costS = src ? link(src.url, "CIWW cost per day") : "";
  }
  const banHomesTxt = isNum(yf.banHomes) && yf.banHomes < yf.banDays ? (yf.banBiz ? ` for businesses and government; <strong>${fmtInt(yf.banHomes)} days for homes</strong>` : `, all customers; <strong>${fmtInt(yf.banHomes)} days for homes</strong>`) : "";
  // ban dates are derived by us from the utility's (CIWW) releases: name the utility, not ourselves
  const banSrc = yf.banF ? (/field to faucet|derived/i.test(yf.banF.source || "") ? `${/CIWW|Central Iowa Water Works/i.test(`${yf.banF.source_title} ${yf.banF.url}`) ? "CIWW" : "utility"} releases: ban dates` : `${yf.banF.source || "source"}: ban dates`) : "";
  const tiles = [
    { v: fmtInt(obs.days_over10), red: true, l: `days the Raccoon River intake was above the 10 mg/L limit${isNum(measured) ? ` (of ${fmtInt(measured)} measured)` : ""}`, s: srcLine(link(nwisUrl(site), `USGS ${site}`), chipSc) },
    { v: fmtInt(yf.plantDays), l: `days the nitrate-removal plant ran${yf.record ? " — a record" : ""}`, s: srcLine(yf.plantF ? link(yf.plantF.url, yf.plantF.source || "source") : "", yf.plantF ? chipF : chipSc) },
    { v: costV, l: costL, s: srcLine(costS, chipF) },
    { v: fmtInt(yf.banDays), l: `days of lawn-watering ban${banHomesTxt}`, s: srcLine(yf.banF ? link(yf.banF.url, banSrc) : "", chipF) },
    { v: yf.people ? (yf.people.value >= 1e5 ? `${Math.round(yf.people.value / 1000)}k${yf.peopleTxt?.endsWith("+") ? "+" : ""}` : fmtInt(yf.people.value)) : "–", l: "people drink this water", s: srcLine(yf.people ? link(yf.people.url, yf.people.source || "source") : "", chipF) },
  ];
  document.getElementById("city-kpis").innerHTML = tiles.map((t) => `<div class="kpi"><div class="kpi-value ${t.red ? "red" : ""}">${t.v}</div><div class="kpi-label">${t.l}</div><div class="kpi-src">${t.s || ""}</div></div>`).join("");
  const lede = document.getElementById("city-lede");
  const partial = obs.partial_year_through ? ` ${YEAR} is a partial year (data through ${fmtDate(parseDate(obs.partial_year_through))}).` : "";
  lede.innerHTML = isNum(obs.days_over10) && isNum(measured)
    ? `In ${YEAR} the Raccoon River at the intake was above the federal nitrate limit on ${fmtInt(obs.days_over10)} of ${fmtInt(measured)} measured days, ${naturalFreq(obs.days_over10, measured)}.${partial} NASA satellites show when upstream fields sit bare on wet soil — when nitrate can wash out.`
    : "";
}

// ------------------------------------------------------------------ replay chart
let replayChart, replayDates, replayCtx;
function buildReplay() {
  const rp = replayFor(YEAR);
  const box = document.getElementById("replay-chart");
  if (replayChart) { replayChart.destroy(); replayChart = null; }
  if (!rp?.dates?.length) { document.getElementById("replay-freq").textContent = `No replay for ${YEAR}.`; return; }
  const c = colors();
  const dates = rp.dates.map(parseDate);
  replayDates = dates;
  const measured = toXY(dates, rp.obs);
  const baseObserved = !rp.base_kind || rp.base_kind === "observed";
  const series = [
    { label: "Scenario low", data: measured.map((p) => ({ ...p })), kind: "bandLo", order: 4 },
    { label: "Scenario high", data: measured.map((p) => ({ ...p })), kind: "bandHi", order: 4 },
    { label: "Measured, today's fields", data: measured, color: c.obs, width: 1.6, order: 1 },
    { label: "With more living cover", data: measured.map((p) => ({ ...p })), color: c.accent, width: 2, order: 0 },
  ];
  if (!baseObserved && rp.base_p50) series.push({ label: "Model, today's fields", data: toXY(dates, rp.base_p50), color: c.base, width: 1.4, dash: [4, 3], order: 2 });
  replayCtx = { rp, baseObserved };
  replayChart = timeChart(box, { xMin: dates[0], xMax: dates[dates.length - 1], threshold: { value: S.data.river_series?.mcl ?? 10, label: "EPA limit 10 mg/L" }, series, bandLabel: "Scenario 8-in-10 range" });
  // shade between measured and scenario = nitrate kept out of the river
  if (replayChart) replayChart.data.datasets[3].fill = { target: 2, above: "transparent", below: "rgba(11,95,102,0.45)" };
  const site = rp.site || PRIMARY;
  document.getElementById("replay-cap").innerHTML = `Data: measured daily nitrate from the USGS sensor on the ${esc(riverOnly(rp.name || siteName(site)))} (${link(nwisUrl(site), site)}). Scenario = measured × (1 − daily cut); the cut blends Iowa cereal-rye trials (INRS 2024) with our river model's response to less bare soil (NASA MODIS/HLS cover, NASA POWER rain and soil wetness).`;
  document.getElementById("replay-note").innerHTML = `${esc(S.data.scenarios?.method || "")} ${mockChip(S.source, "scenarios")}`;
}

function updateReplay() {
  if (!replayCtx) return;
  const { rp, baseObserved } = replayCtx;
  const lvl = levelAt(LEVEL);
  if (!lvl) return;
  const c = colors();
  const k = String(lvl.x);
  const pick = (o) => o?.[k] ?? o?.[lvl.x];
  const mid = pick(rp.by_level), lo = pick(rp.by_level_lo), hi = pick(rp.by_level_hi);
  const showBand = !!(document.getElementById("replay-band").checked && lo && hi && lvl.x > 0);
  if (replayChart) {
    const ds = replayChart.data.datasets;
    ds[3].data = mid ? toXY(replayDates, mid) : ds[2].data;
    ds[3].label = `With cover on ${lvl.x}% more corn/soy acres`;
    ds[3].hidden = lvl.x === 0;
    ds[0].data = lo ? toXY(replayDates, lo) : ds[2].data;
    ds[1].data = hi ? toXY(replayDates, hi) : ds[2].data;
    ds[0].hidden = ds[1].hidden = !showBand;
    replayChart.update("none");
  }
  document.getElementById("adopt-val").textContent = `${lvl.x}%`;
  document.querySelectorAll(".js-adopt").forEach((el) => el.setAttribute("aria-valuetext", sliderText(lvl.x)));
  const items = [
    { label: baseObserved ? "Measured, today's fields (USGS)" : "Measured (USGS)", color: c.obs },
    ...(lvl.x > 0 ? [
      { label: `With cover on ${lvl.x}% more corn/soy acres`, color: c.accent },
      { label: "Nitrate kept out of the river", color: "rgba(11,95,102,0.5)", kind: "band" },
    ] : []),
    ...(showBand ? [{ label: "Scenario 8-in-10 range", color: c.accent, kind: "band" }] : []),
    ...(!baseObserved ? [{ label: "Model, today's fields", color: c.base, kind: "dash" }] : []),
    { label: "EPA limit 10 mg/L", color: c.nitrate, kind: "dash" },
  ];
  document.getElementById("replay-legend").innerHTML = legendHTML(items);
  renderDeltas(lvl, rp);
}

document.addEventListener("change", (e) => { if (e.target?.id === "replay-band") updateReplay(); });

function renderDeltas(lvl, rp) {
  const obs = yearBlock()?.observed || {};
  const measured = isNum(obs.measured_days) ? obs.measured_days : rp.obs.filter(isNum).length;
  const dd = avoided(lvl, "days_over10");
  const freq = document.getElementById("replay-freq");
  const river = riverOnly(rp.name || siteName(rp.site || PRIMARY));
  if (lvl.x === 0) {
    freq.innerHTML = `Measured in ${YEAR}: the ${esc(river)} was above the limit on <strong>${fmtInt(obs.days_over10)} of ${fmtInt(measured)}</strong> measured days (${naturalFreq(obs.days_over10, measured)}). Move the slider to add cover.`;
  } else if (dd && isNum(obs.days_over10)) {
    const n = Math.max(0, obs.days_over10 - dd.mid), lo = Math.max(0, obs.days_over10 - dd.hi), hi = Math.max(0, obs.days_over10 - dd.lo);
    freq.innerHTML = `Measured: the ${esc(river)} was above the limit on <strong>${fmtInt(obs.days_over10)}</strong> days. With cover on ${lvl.x}% more corn/soy acres: about <strong>${fmtInt(n)} days</strong> (range ${fmtInt(lo)}–${fmtInt(hi)}). It sat far above 10 mg/L for weeks, so a few-percent cut flips few days; the plant and ban rules respond more.`;
  }
  const tiles = [
    { k: "days_over10", lab: `fewer days above 10 mg/L, ${esc(river)}`, f: fmtInt },
    { k: "days_over10_dm", lab: "fewer days above 10 mg/L, Des Moines River", f: fmtInt },
    { k: "load_tN", lab: "tonnes of nitrate-N kept out of the two rivers", f: fmtInt },
  ];
  const html = tiles.map((t) => {
    const b = avoided(lvl, t.k);
    if (!b) return "";
    return `<div class="delta"><div class="delta-num ${b.mid === 0 ? "zero" : ""}">${t.f(b.mid)}</div><div class="delta-lab">${t.lab}</div><div class="delta-rng">${lvl.x === 0 ? "&nbsp;" : rangeTxt(b, t.f)}</div></div>`;
  }).join("");
  const kept = avoided(lvl, "lbN_kept");
  const fert = fact("fert_price_usd_lb_N");
  const keptTxt = kept && lvl.x > 0 ? `<p class="fine" style="grid-column:1/-1">That is about <strong>${fmtLb(kept.mid)}</strong> of nitrogen (range ${fmtLbRange(kept.lo, kept.hi)}) staying upstream instead of reaching the intakes: fertilizer farmers already paid for${fert ? ` (at ${link(fert.url, `$${fert.value.toFixed(2)}/lb N`)}, an upper bound)` : ""}.</p>` : "";
  document.getElementById("replay-deltas").innerHTML = html + keptTxt;
}
const fmtLbRange = (a, b) => (isNum(b) && b >= 1e6 && a >= 1e5 ? `${(a / 1e6).toFixed(1)}–${(b / 1e6).toFixed(1)} million lb` : `${fmtLb(a)}–${fmtLb(b)}`);
const fmtLb = (v) => (!isNum(v) ? "–" : v >= 1e6 ? `${(v / 1e6).toFixed(1)} million lb` : `${fmtInt(v)} lb`);

// ------------------------------------------------------------------ river chart
const MODEL_NAME = { v1: "Model v1 (weather + cover)", v2: "Model v2 (+ drought carry-over)" };
export function displayModel(site) {
  const rs = S.data.river_series, v = S.data.validation;
  const m = rs?.sites?.[site]?.model;
  return (typeof m === "string" ? m : m?.model) || rs?.display_model?.[site] || v?.display_model?.[site] || v?.sites?.[site]?.display_model || (typeof v?.display_model === "string" ? v.display_model : "v1");
}

// One plain line on the 2025 miss, built from validation.json numbers.
export function honestLine(validation) {
  const sites = Object.values(validation?.sites || {});
  const nse = sites.map((s) => s.by_split?.test?.gbm?.NSE).filter(isNum);
  const ratios = sites.map((s) => s.level_ratio_obs_over_model?.["2025"]).filter(isNum);
  if (!nse.length) return "";
  const nseTxt = `~${(nse.reduce((a, b) => a + b, 0) / nse.length).toFixed(1)}`;
  const lo = Math.min(...ratios), hi = Math.max(...ratios);
  const rTxt = ratios.length ? (hi - lo < 0.15 ? `about ${hi.toFixed(1)}×` : `about ${lo.toFixed(1)}–${hi.toFixed(1)}×`) : "a lot";
  return `The weather-and-cover model explains normal years (test NSE ${nseTxt}) but under-predicted 2025-26 by ${rTxt} — one hypothesis: nitrate left over after the 2020-23 drought. That's why impact numbers replay the measured river with relative changes.`;
}

let riverChart, riverSite = PRIMARY, riverRange = "test", redrawRiver, setRange;
function renderRiver() {
  const rs = S.data.river_series;
  const box = document.getElementById("river-chart");
  const v = S.data.validation;
  document.getElementById("river-honest").innerHTML = honestLine(v) ? `<strong>Honest limit:</strong> ${esc(honestLine(v))} ${link("#method", "How we test it")}` : "";
  if (!rs?.sites || !Object.keys(rs.sites).length) {
    document.getElementById("river-note").textContent = "River series not available yet.";
    return;
  }
  const sites = Object.keys(rs.sites).sort((a, b) => (a === PRIMARY ? -1 : b === PRIMARY ? 1 : 0));
  if (!sites.includes(riverSite)) riverSite = sites[0];
  segmented(document.getElementById("river-site"), sites.map((s) => ({ value: s, label: riverOnly(rs.sites[s].name) })), riverSite, (val) => { riverSite = val; drawRiver(); });
  const rangeOpts = () => [{ value: "all", label: "All years" }, { value: "test", label: "Test 2023–25" }, { value: "year", label: String(YEAR) }];
  const rangeBox = document.getElementById("river-range");
  setRange = segmented(rangeBox, rangeOpts(), riverRange, (val) => { riverRange = val; drawRiver(); });
  redrawRiver = () => { rangeBox.querySelector('[data-v="year"]').textContent = String(YEAR); drawRiver(); };
  drawRiver();

  function drawRiver() {
    const c = colors();
    const s = rs.sites[riverSite];
    const dm = displayModel(riverSite);
    const mName = MODEL_NAME[dm] || `Model ${dm}`;
    document.getElementById("river-legend").innerHTML = legendHTML([
      { label: "Measured (USGS sensor)", color: c.obs },
      { label: `${mName}, median`, color: c.accent },
      { label: "Model 8-in-10 range", color: c.accent, kind: "band" },
      { label: "EPA limit 10 mg/L", color: c.nitrate, kind: "dash" },
    ]) + mockChip(S.source, "river_series");
    const dates = s.dates.map(parseDate);
    const sp = rs.split || {};
    const last = dates[dates.length - 1];
    const span = (k) => (sp[k] ? { from: parseDate(sp[k][0]), to: sp[k][1] ? parseDate(sp[k][1]) : last } : null);
    const spans = [
      span("train") && { ...span("train"), label: "Training years", fill: "rgba(0,0,0,0)" },
      span("test") && { ...span("test"), label: "Out-of-time test", fill: "rgba(16,24,31,0.05)" },
      span("live") && { ...span("live"), label: "Live", fill: "rgba(11,95,102,0.07)" },
    ].filter(Boolean);
    let xMin = dates[0];
    if (riverRange === "test" && span("test")) xMin = span("test").from;
    if (riverRange === "year") xMin = Date.UTC(YEAR, 0, 1);
    const xMax = riverRange === "year" ? Math.min(Date.UTC(YEAR, 11, 31), last) : last;
    const series = [
      { label: "Model low", data: toXY(dates, s.p10), kind: "bandLo", order: 3 },
      { label: "Model high", data: toXY(dates, s.p90), kind: "bandHi", order: 3 },
      { label: `${mName}`, data: toXY(dates, s.p50), color: c.accent, width: 1.6, order: 1 },
      { label: "Measured", data: toXY(dates, s.obs), color: c.obs, width: 1.4, order: 0 },
    ];
    riverChart?.destroy();
    riverChart = timeChart(box, { series, xMin, xMax, spans, threshold: { value: rs.mcl ?? 10, label: "EPA limit 10 mg/L" } });
    const inRange = s.obs.filter((val, i) => isNum(val) && dates[i] >= xMin && dates[i] <= xMax);
    const over = inRange.filter((val) => val > (rs.mcl ?? 10)).length;
    const v2 = v?.sites?.[riverSite]?.v2;
    const post = dm === "v2" && v2 ? ` v2 adds a nitrogen carry-over store for the years after a drought; it was designed after seeing the 2025 miss, so its test-year fit is not a clean test (v1's is).` : "";
    const prov = s.provisional_from ? ` USGS data from ${fmtDate(parseDate(s.provisional_from))} on are provisional.` : "";
    document.getElementById("river-cap").innerHTML = `Data: measured nitrate, USGS sensor ${link(nwisUrl(riverSite), riverSite)}. Model drivers: NASA POWER rain and root-zone soil wetness (GWETROOT), NASA MODIS/HLS bare cropland, USDA CDL crops, USGS flow. The model never sees measured nitrate.${post}`;
    document.getElementById("river-note").innerHTML = `${esc(s.name)}: ${fmtInt(over)} of ${fmtInt(inRange.length)} measured days in view were above 10 mg/L. Gaps are days without a sensor reading.${prov}`;
  }
}

// ------------------------------------------------------------------ hotspot map
let cityMap, cityMetric = "share_of_basin_leak", cityPopup;
const METRICS = {
  share_of_basin_leak: { label: "Share of basin leak", fmt: (v) => pct(v, v < 0.01 ? 2 : 1) },
  leak_index: { label: "Leak per acre", fmt: (v) => `${fmt(v, 2)}× avg` },
};

function hucFeatures() {
  return S.data.huc12?.features || [];
}

export async function initCityMap() {
  if (cityMap !== undefined) { cityMap?.resize(); return; }
  cityMap = null;
  await ensure(S, "map");
  renderHotspotList();
  const feats = hucFeatures();
  const container = document.getElementById("city-map");
  const bounds = bboxOf(S.data.basins?.features?.length ? S.data.basins.features : feats);
  const map = await createMap(container, { bounds, attribution: "Boundaries: USGS WBD · Rivers: USGS NHD" });
  if (!map) return;
  cityMap = map;
  const hasScores = feats.some((f) => isNum(f.properties.leak_index));
  map.addSource("huc", { type: "geojson", data: S.data.huc12, promoteId: "huc12" });
  map.addLayer({ id: "huc-fill", type: "fill", source: "huc", paint: { "fill-color": "#dddddd", "fill-opacity": 0.92 } });
  map.addLayer({ id: "huc-line", type: "line", source: "huc", paint: { "line-color": "#ffffff", "line-width": 0.5 } });
  map.addLayer({ id: "huc-hover", type: "line", source: "huc", paint: { "line-color": "#10181f", "line-width": 2.2 }, filter: ["==", ["get", "huc12"], ""] });
  map.addLayer({ id: "huc-focus", type: "line", source: "huc", paint: { "line-color": "#0b5f66", "line-width": 2, "line-dasharray": [2, 1.5] }, filter: ["==", ["get", "in_focus"], true] });
  addContext(map, S.data);
  addRivers(map, S.data.rivers);
  addSites(map, S.data.sites);
  addPlaces(map, S.data.places, { townMinZoom: 7.8 });

  segmented(document.getElementById("map-metric"), Object.entries(METRICS).map(([k, m]) => ({ value: k, label: m.label })), cityMetric, (val) => { cityMetric = val; paint(); });
  function paint() {
    const legend = document.getElementById("city-map-legend");
    if (!hasScores) {
      legend.innerHTML = `<span>Leak scores not computed yet; outlines only.</span>`;
      return;
    }
    const ramp = LEAK_RAMP();
    const vals = feats.map((f) => f.properties[cityMetric]);
    const br = quantileBreaks(vals, ramp.length);
    map.setPaintProperty("huc-fill", "fill-color", stepExpr(cityMetric, br, ramp));
    const vv = vals.filter(isNum).sort((a, b) => a - b);
    legend.innerHTML = rampLegend(ramp, [`lower (${METRICS[cityMetric].fmt(vv[0])})`, `higher (${METRICS[cityMetric].fmt(vv[vv.length - 1])})`], METRICS[cityMetric].label + " · equal-count classes") +
      `<span><span class="sw" style="display:inline-block;width:18px;border-top:2px dashed #0b5f66;vertical-align:middle;margin-right:6px"></span>Farmer focus area</span>` + mockChip(S.source, "huc12");
  }
  paint();

  map.on("mousemove", "huc-fill", (e) => {
    map.getCanvas().style.cursor = "pointer";
    const id = e.features?.[0]?.properties?.huc12;
    map.setFilter("huc-hover", ["==", ["get", "huc12"], id || ""]);
  });
  map.on("mouseleave", "huc-fill", () => { map.getCanvas().style.cursor = ""; map.setFilter("huc-hover", ["==", ["get", "huc12"], ""]); });
  map.on("click", "huc-fill", (e) => {
    const f = e.features?.[0];
    if (f) openHucPopup(f.properties, e.lngLat);
  });
}

function basinCount(basin) {
  return hucFeatures().filter((f) => f.properties.basin === basin).length;
}

function hucPopupHTML(p) {
  const row = (k, val) => `<tr><td>${k}</td><td>${val}</td></tr>`;
  const basinName = p.basin === "raccoon" ? "Raccoon" : p.basin === "desmoines" ? "Des Moines" : esc(p.basin);
  const n = (k) => (p[k] == null ? null : Number(p[k]));
  return `<h4>${esc(p.name || "Sub-watershed")}</h4><div class="fine" style="margin:0 0 4px">HUC-12 ${esc(p.huc12)} · ${basinName} basin${mockChip(S.source, "huc12")}</div>
  <table class="pop-table">
    ${isNum(n("lbN_ac_yr")) ? row("Modelled leak", `${fmt(n("lbN_ac_yr"), 1)} lb N/ac/yr`) : ""}
    ${row("Share of basin leak", pct(n("share_of_basin_leak"), 1))}
    ${row("Rank in basin", isNum(n("rank")) ? `${fmtInt(n("rank"))} of ${isNum(n("n_in_basin")) ? n("n_in_basin") : basinCount(p.basin)}` : "–")}
    ${row("Row-crop share", pct(n("row_crop_share")))}
    ${row("Poorly drained cropland", pct(n("poorly_drained_share")))}
    ${row("Bare + wet days / yr", fmtInt(n("bare_days_wet")))}
  </table>`;
}

function openHucPopup(p, lngLat, anchor) {
  if (!cityMap) return;
  cityPopup?.remove();
  cityPopup = new maplibregl.Popup({ maxWidth: "min(280px, 80vw)", ...(anchor ? { anchor } : {}) }).setLngLat(lngLat).setHTML(hucPopupHTML(p)).addTo(cityMap);
}

let hotspotBound = false;
function renderHotspotList() {
  const feats = hucFeatures().filter((f) => f.properties.basin === "raccoon" && isNum(Number(f.properties.rank)) && f.properties.rank != null);
  const list = document.getElementById("hotspot-list");
  const note = document.getElementById("hotspot-note");
  document.getElementById("hotspot-basin").textContent = "· Raccoon basin";
  if (!feats.length) { list.innerHTML = "<li>Leak scores not computed yet.</li>"; return; }
  const top = feats.sort((a, b) => a.properties.rank - b.properties.rank).slice(0, 6);
  list.innerHTML = top.map((f) => `<li><button type="button" data-huc="${esc(f.properties.huc12)}">${esc(f.properties.name || f.properties.huc12)}</button><br><span class="muted">${pct(f.properties.share_of_basin_leak, 1)} of the leak · ${pct(f.properties.row_crop_share)} row crops</span></li>`).join("");
  const all = hucFeatures().filter((f) => f.properties.basin === "raccoon");
  const areaAll = all.reduce((s, f) => s + (f.properties.area_km2 || 0), 0);
  const areaTop = top.reduce((s, f) => s + (f.properties.area_km2 || 0), 0);
  const shareTop = top.reduce((s, f) => s + (f.properties.share_of_basin_leak || 0), 0);
  note.innerHTML = `These ${top.length} sub-watersheds cover ${pct(areaTop / areaAll)} of the Raccoon basin but account for about <strong>${pct(shareTop)}</strong> of the modelled leak index (not measured), mostly because their cropland sits bare on more wet days. ${mockChip(S.source, "huc12")}`;
  if (hotspotBound) return;
  hotspotBound = true;
  list.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-huc]");
    if (!b) return;
    const f = hucFeatures().find((x) => x.properties.huc12 === b.dataset.huc);
    if (!f || !cityMap) return;
    const bb = bboxOf([f]);
    cityMap.fitBounds(bb, { padding: 60, maxZoom: 10, duration: 600 });
    // wide maps: popup beside the sub-watershed's centre so it is never cut off at the bottom
    const wide = document.getElementById("city-map").clientWidth >= 600;
    openHucPopup(f.properties, [(bb[0][0] + bb[1][0]) / 2, (bb[0][1] + bb[1][1]) / 2], wide ? "left" : undefined);
    document.getElementById("city-map").scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

// ------------------------------------------------------------------ outlook
let outlookChart, outlookSite;
function outlookFor(site) {
  const o = S.data.outlook;
  if (!o) return null;
  const e = o.sites?.[site];
  if (e) return { ...e, drivers: e.drivers ?? (site === o.site ? o.drivers : null), weather_forecast_used: e.weather_forecast_used ?? o.weather_forecast_used };
  return site === (o.site || PRIMARY) ? o : null;
}
// Horizon-by-horizon skill from validation.json (fallback: outlook.json's own skill block).
function outlookSkill(site) {
  const vs = S.data.validation?.outlook_skill?.[site];
  const os = outlookFor(site)?.skill || {};
  const h = (n) => vs?.[`h${n}`]?.gbm;
  const mse7 = h(7)?.skill_vs_persistence_mse ?? os.test_2023_2025_h7;
  // typical error (RMSE) vs persistence; from the two RMSEs, else from the squared-error skill (RMSE ratio = sqrt(1 - skill))
  const pr = vs?.h7?.persistence?.RMSE, gr = h(7)?.RMSE;
  const rmse7 = isNum(pr) && isNum(gr) && pr > 0 ? 1 - gr / pr : isNum(mse7) && mse7 < 1 ? 1 - Math.sqrt(1 - mse7) : null;
  const bss14 = h(14)?.brier_skill_vs_persistence ?? os.brier_skill_vs_prob_persistence_h14;
  let probDays = null; // last lead with a useful probability skill (Brier skill >= 0.05 vs persistence at every lead up to it)
  if (vs) { probDays = 0; for (let n = 1; n <= 14; n++) { const b = h(n)?.brier_skill_vs_persistence; if (isNum(b) && b >= 0.05) probDays = n; else break; } }
  return { mse7, rmse7, bss14, probDays };
}

function renderOutlook() {
  const o = S.data.outlook;
  const sub = document.getElementById("outlook-sub");
  if (!o?.dates?.length) { sub.textContent = "Outlook not available yet."; return; }
  const sites = o.sites ? Object.keys(o.sites).sort((a, b) => (a === PRIMARY ? -1 : b === PRIMARY ? 1 : 0)) : [o.site || PRIMARY];
  outlookSite = sites.includes(o.site) ? o.site : sites[0];
  const segBox = document.getElementById("outlook-site");
  if (sites.length > 1) segmented(segBox, sites.map((s) => ({ value: s, label: riverOnly(outlookFor(s)?.name || siteName(s)) })), outlookSite, (v) => { outlookSite = v; drawOutlook(); });
  else segBox.parentElement.hidden = true;
  drawOutlook();
}

function drawOutlook() {
  const site = outlookSite;
  const o = outlookFor(site);
  if (!o?.dates?.length) return;
  const sub = document.getElementById("outlook-sub");
  sub.innerHTML = `${esc(o.name || siteName(site))}. Issued ${esc(o.issued || "")} from the latest measurement, soil wetness, recent rain and how much cropland is bare. ${mockChip(S.source, "outlook")}`;
  const c = colors();
  const fd = o.dates.map(parseDate);
  const rs = S.data.river_series?.sites?.[site];
  let recent = [];
  if (rs) {
    const end = o.last_obs?.date ? parseDate(o.last_obs.date) : fd[0];
    const from = end - 30 * 86400000;
    rs.dates.forEach((d, i) => { const t = parseDate(d); if (t >= from && t <= end) recent.push({ x: t, y: isNum(rs.obs[i]) ? rs.obs[i] : null }); });
  } else if (o.last_obs) recent = [{ x: parseDate(o.last_obs.date), y: o.last_obs.value }];
  const anchor = o.last_obs && isNum(o.last_obs.value) ? [{ x: parseDate(o.last_obs.date), y: o.last_obs.value }] : [];
  const fan = (arr) => [...anchor, ...toXY(fd, arr)];
  const xMin = recent.length ? recent[0].x : fd[0];
  const xMax = fd[fd.length - 1];
  outlookChart?.destroy();
  outlookChart = timeChart(document.getElementById("outlook-chart"), {
    xMin, xMax, threshold: { value: S.data.river_series?.mcl ?? 10, label: "EPA limit 10 mg/L" },
    spans: [{ from: fd[0], to: xMax, label: "Outlook", fill: "rgba(11,95,102,0.06)" }],
    series: [
      { label: "Low", data: fan(o.p10), kind: "bandLo", order: 3 },
      { label: "High", data: fan(o.p90), kind: "bandHi", order: 3 },
      { label: "Outlook (median)", data: fan(o.p50), color: c.accent, width: 2, dash: [5, 3], order: 1 },
      { label: "Measured", data: recent, color: c.obs, width: 1.6, order: 0 },
    ],
  });
  document.getElementById("outlook-legend").innerHTML = legendHTML([
    { label: "Measured, last 30 days (USGS)", color: c.obs },
    { label: "Outlook (median)", color: c.accent, kind: "dash" },
    { label: "8-in-10 range", color: c.accent, kind: "band" },
    { label: "EPA limit 10 mg/L", color: c.nitrate, kind: "dash" },
  ]);
  const sk = outlookSkill(site);
  const probs = o.prob_over10 || [];
  document.getElementById("outlook-prob").innerHTML = probs.map((p, i) => {
    const cls = p >= 0.5 ? "hot" : p >= 0.2 ? "warm" : "";
    const noskill = isNum(sk.probDays) && i + 1 > sk.probDays ? " noskill" : "";
    return `<div class="prob-cell ${cls}${noskill}" title="${fmtDate(fd[i])}: ${isNum(p) ? Math.round(p * 100) : "–"}% chance above 10 mg/L${noskill ? " (no tested skill this far ahead)" : ""}">${isNum(p) ? Math.round(p * 100) : "–"}%</div>`;
  }).join("") + `<div class="prob-cap" style="grid-column:1/-1">Chance above 10 mg/L, each of the next ${probs.length} days${isNum(sk.probDays) && sk.probDays < probs.length ? `. Faded: beyond day ${sk.probDays} these chances did not beat "no change" in testing` : ""}.</div>`;
  const expDays = isNum(o.expected_days_over10) ? o.expected_days_over10 : probs.filter(isNum).reduce((a, b) => a + b, 0);
  const above = o.last_obs && isNum(o.last_obs.value) && o.last_obs.value > (S.data.river_series?.mcl ?? 10);
  const head = document.getElementById("outlook-headline");
  const lastD = o.last_obs?.date ? fmtDate(parseDate(o.last_obs.date), { month: "short", day: "numeric" }) : "";
  if (above) head.innerHTML = `<span class="red">Already above the limit</span> (${fmt(o.last_obs.value, 1)} mg/L on ${lastD}). Expect about <strong>${Math.round(expDays)} of the next ${probs.length} days</strong> above 10 mg/L.`;
  else if (expDays >= 0.5) head.innerHTML = `Expect about <strong>${Math.round(expDays)} of the next ${probs.length} days</strong> above the 10 mg/L limit.`;
  else head.textContent = `Low chance of crossing the safe limit in the next ${probs.length} days.`;
  const dr = o.drivers || {};
  const items = [];
  const vsPast = (p, more = "more") => (p >= 99 ? `the highest for this time of year since 2016` : p <= 1 ? `the lowest for this time of year since 2016` : `${more} than in ${Math.round(p)}% of past years at this time`);
  if (isNum(dr.rain_7d_mm)) items.push(`<b>Rain, last 7 days:</b> ${fmt(dr.rain_7d_mm, dr.rain_7d_mm < 10 ? 1 : 0)} mm${isNum(dr.rain_7d_pctile) ? ` — ${vsPast(dr.rain_7d_pctile)}` : ""} <span class="muted">(NASA POWER)</span>`);
  if (isNum(dr.gwetroot)) items.push(`<b>Root-zone soil wetness:</b> ${fmt(dr.gwetroot, 2)} on a 0–1 scale${isNum(dr.gwetroot_pctile) ? ` — ${vsPast(dr.gwetroot_pctile, "wetter")}` : ""} <span class="muted">(NASA POWER GWETROOT)</span>`);
  if (isNum(dr.bare_share)) items.push(`<b>Bare cropland:</b> ${pct(dr.bare_share)} of row-crop land has no living cover${isNum(dr.bare_share_pctile) ? ` — ${vsPast(dr.bare_share_pctile)}` : ""} <span class="muted">(NASA MODIS/HLS${isNum(dr.bare_share_age_days) ? `, last clear view ${dr.bare_share_age_days} days old` : ""})</span>`);
  if (o.last_obs && isNum(o.last_obs.value)) items.push(`<b>Last measurement:</b> ${fmt(o.last_obs.value, 1)} mg/L on ${esc(o.last_obs.date)} <span class="muted">(USGS)</span>`);
  document.getElementById("outlook-drivers").innerHTML = items.map((t) => `<li>${t}</li>`).join("");
  const parts = [];
  if (o.weather_forecast_used === false) parts.push(`<strong>No weather forecast used</strong>: a big storm can push nitrate outside this range.`);
  if (isNum(sk.mse7)) parts.push(isNum(sk.rmse7)
    ? `Tested on 2023–25: at 7 days its typical error was ${Math.round(sk.rmse7 * 100)}% smaller than assuming "no change" (squared error ${Math.round(sk.mse7 * 100)}% smaller).`
    : `Tested on 2023–25: at 7 days its squared error was ${Math.round(sk.mse7 * 100)}% smaller than assuming "no change" (persistence).`);
  if (isNum(sk.bss14)) parts.push(sk.bss14 < 0.05 ? `At 14 days the chance above 10 mg/L has no probability skill over "no change" (Brier skill ${Math.round(sk.bss14 * 100)}%), so read the late days as a rough guide.` : `At 14 days the chance above 10 mg/L beats "no change" by ${Math.round(sk.bss14 * 100)}% (Brier skill).`);
  document.getElementById("outlook-skill").innerHTML = parts.join(" ");
  document.getElementById("outlook-text").textContent = o.text || "";
  document.getElementById("outlook-cap").innerHTML = `Data: last 30 days measured by the USGS sensor (${link(nwisUrl(site), site)}); outlook from that measurement plus NASA POWER rain and soil wetness and NASA MODIS/HLS bare cropland up to today.`;
}
