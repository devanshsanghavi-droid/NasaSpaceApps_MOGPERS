// Community view: GMD + county clocks, sortable list, and the "shift X% of corn" slider.
import { esc, fmt, num, isNum, yrs, yearColor, rangeText, NA, fmtSigned, CAP } from './util.js';
import { countyYears, countyShift, strategyApplies } from './scenario.js';
import { countyName } from './data.js';

let D, S, actions;
let sortKey = 'years', sortDir = 1;
const compact = v => (v >= 1e6 ? fmt(v / 1e6, 1) + 'M' : v >= 1e4 ? fmt(v / 1e3, 0) + 'k' : fmt(v));

export function initCommunity(data, state, act) { D = data; S = state; actions = act; }

function rangeBar(y) {
  // 0..100 years scale bar with the p10-p90 range and the p50 marker.
  const pct = v => Math.max(0, Math.min(100, v));
  if (!isNum(y.p50)) return '<span class="na">n/a</span>';
  const a = isNum(y.p10) ? pct(y.p10) : pct(y.p50), b = isNum(y.p90) ? pct(y.p90) : pct(y.p50);
  return `<span class="rbar" aria-hidden="true"><span class="rbar-rng" style="left:${a}%;width:${Math.max(1, b - a)}%;background:${yearColor(y.p50)}"></span><span class="rbar-mid" style="left:${pct(y.p50)}%"></span></span>`;
}

function gmdCards() {
  const gs = D.clocks?.gmds || [];
  if (!gs.length) return '';
  return `<div class="gmd-row">${gs.map(g => {
    const y = countyYears(g, S.thr);
    return `<div class="gmd" style="border-top-color:${yearColor(y.p50)}">
      <div class="gmd-name">${esc(g.name || g.gmd)}</div>
      <div class="gmd-num"><b>${yrs(y.p50)}</b> yrs</div>
      <div class="gmd-rng">${isNum(y.p10) ? (y.p10 <= 0 && y.p90 >= CAP ? 'very uncertain (0 to 100+)' : `range ${yrs(y.p10)} to ${yrs(y.p90)}`) : ''}</div>
      <div class="gmd-meta">${isNum(g.irrigated_acres) ? fmt(g.irrigated_acres) + ' irrigated ac' : ''}</div>
    </div>`;
  }).join('')}</div>`;
}

function countyTable() {
  const cs = (D.clocks?.counties || []).map(c => ({ c, y: countyYears(c, S.thr, D) }));
  if (!cs.length) return `<p>${NA}: county_clocks.json is missing.</p>`;
  const key = {
    years: r => (isNum(r.y.p50) ? r.y.p50 : 1e9),
    name: r => String(r.c.name),
    gmd: r => String(r.c.gmd) + String(r.c.name),
    acres: r => -(r.c.irrigated_acres || 0),
    decline: r => -(num(r.c.decline_ft_yr) ?? -1e9),
  }[sortKey];
  cs.sort((a, b) => { const x = key(a), z = key(b); return (x < z ? -1 : x > z ? 1 : 0) * sortDir; });
  const th = (k, label) => `<th scope="col"><button type="button" class="sort" data-sort="${k}" aria-pressed="${sortKey === k}">${label}${sortKey === k ? (sortDir > 0 ? ' &#9650;' : ' &#9660;') : ''}</button></th>`;
  return `<div class="table-wrap"><table class="ctable">
    <caption class="sr-only">County water clocks at the ${S.thr} ft threshold</caption>
    <thead><tr>${th('name', 'County')}${th('gmd', 'GMD').replace('<th ', '<th class="hide-xs" ')}${th('years', 'Years left')}<th scope="col" class="hide-sm">Range <span class="sr-only">(0 to 100 years scale)</span></th>${th('decline', 'Drop ft/yr')}${th('acres', 'Irrig. acres')}</tr></thead>
    <tbody>${cs.map(({ c, y }) => `<tr class="${S.fips === String(c.fips) ? 'sel' : ''}">
      <th scope="row"><button type="button" class="link-btn" data-fips="${esc(c.fips)}">${esc(c.name)}</button>${c.data_quality === 'thin' ? ' <span class="dq dq-thin" title="few monitoring wells">thin data</span>' : ''}</th>
      <td class="hide-xs">${esc(c.gmd || '')}</td>
      <td><b>${yrs(y.p50)}</b>${y.below ? ' <span class="rng-sm">already below</span>' : `<span class="rng-sm">${isNum(y.p10) ? ` ${yrs(y.p10)}-${yrs(y.p90)}` : ''}</span>`}</td>
      <td class="hide-sm">${rangeBar(y)}</td>
      <td>${isNum(num(c.decline_ft_yr)) ? fmt(num(c.decline_ft_yr), 1) : 'n/a'}</td>
      <td>${isNum(c.irrigated_acres) ? compact(c.irrigated_acres) : 'n/a'}</td></tr>`).join('')}</tbody>
  </table></div>`;
}

function sliderBlock() {
  const fipsList = Object.keys(D.scenByFips).length ? Object.keys(D.scenByFips) : Object.keys(D.countyByFips);
  if (!fipsList.length) return `<section class="card"><h3>What if farmers shift?</h3><p>${NA}: scenario.json is missing.</p></section>`;
  if (!S.fips || !fipsList.includes(S.fips)) S.cFips = S.cFips && fipsList.includes(S.cFips) ? S.cFips : fipsList.slice().sort((a, b) => countyName(D, a).localeCompare(countyName(D, b)))[0];
  else S.cFips = S.fips;
  const strats = D.strategyList.filter(s => s.id !== 'S0' && strategyApplies(D, S.cFips, s));
  if (!S.cStrat || !strats.find(s => s.id === S.cStrat)) S.cStrat = strats[0]?.id;
  return `<section class="card shift" aria-labelledby="sh-h">
    <h3 id="sh-h">What if farmers shift?</h3>
    <div class="shift-form">
      <label>County <select id="sh-county">${fipsList.slice().sort((a, b) => countyName(D, a).localeCompare(countyName(D, b))).map(f => `<option value="${esc(f)}" ${f === S.cFips ? 'selected' : ''}>${esc(countyName(D, f))}</option>`).join('')}</select></label>
      <label>Switch to <select id="sh-strat">${strats.map(s => `<option value="${esc(s.id)}" ${s.id === S.cStrat ? 'selected' : ''}>${esc(s.short || s.name)}</option>`).join('')}</select></label>
      <label class="sh-pct">Share of irrigated corn acres that switch: <b id="sh-pct-v">${S.cPct}%</b>
        <input id="sh-pct" type="range" min="0" max="100" step="5" value="${S.cPct}"></label>
    </div>
    <div id="sh-out" class="sh-out" aria-live="polite"></div>
    <details class="formula"><summary>How this is calculated</summary>
      <p>Water saved = share &times; irrigated corn acres &times; (water pumped for corn &minus; water pumped for the new plan) &divide; 12.
      The part of the water-table decline caused by pumping shrinks in proportion to the water saved. Years left = usable thickness &divide; decline rate (capped at 100).
      Range uses the low and high decline-rate estimates.</p>
      ${D.scenario?.formula ? `<p><b>Model's formula (scenario.json):</b> ${esc(D.scenario.formula)}</p>` : ''}
    </details>
  </section>`;
}

function renderShift() {
  const out = document.getElementById('sh-out');
  if (!out) return;
  const r = countyShift(D, S.cFips, S.cStrat, S.cPct / 100, S.thr);
  const name = esc(countyName(D, S.cFips));
  const s = D.strategyList.find(x => x.id === S.cStrat);
  if (r.error) { out.innerHTML = `<p>${esc(r.error)}</p>`; return; }
  if (r.below) { out.innerHTML = `<p class="sh-big">${name} County: ${esc(r.note)}</p>`; return; }
  if (r.risingAlready || r.before >= CAP) {
    out.innerHTML = `<p class="sh-big">${name} County already has <b>100+</b> years at the ${S.thr} ft threshold.</p>`;
    return;
  }
  const gainTxt = r.after >= CAP ? 'more than 100 years in total' : `<b>${fmtSigned(r.gain, 1)}</b> years`;
  out.innerHTML = `<p class="sh-sentence">If <b>${S.cPct}%</b> of irrigated corn in ${name} County shifts to <b>${esc(s?.short || s?.name || S.cStrat)}</b>, the county clock gains ${gainTxt}.</p>
    <div class="sh-clocks"><div><span class="lab">Now</span><span class="v" style="color:${yearColor(r.before)}">${yrs(r.before, 1)}</span><span class="u">years</span></div>
      <div class="sh-arrow" aria-hidden="true">&rarr;</div>
      <div><span class="lab">After shift</span><span class="v" style="color:${yearColor(r.after)}">${yrs(r.after, 1)}</span><span class="u">years</span></div></div>
    <p class="fine">Range of the gain: ${fmtSigned(r.gainLo, 1)} to ${fmtSigned(r.gainHi, 1)} years. Water saved: about ${fmt(r.savedAf, 0)} acre-ft per year.
    Water-table drop: ${fmt(r.decline, 2)} &rarr; ${fmt(r.newDecline, 2)} ft/yr.</p>`;
}

const CTX_LABELS = {
  population: 'People',
  main_towns: 'Main towns',
  towns: 'Towns',
  crop_sales_per_resident_usd: 'Crop sales per resident',
  ag_share_of_economy: 'Share of economy from irrigated farming',
  econ_note: 'Local economy',
};

function countyContext() {
  const c = D.countyByFips[S.cFips];
  if (!c) return '';
  const items = [];
  // town_note already lists the main towns; keep only its first sentence (drops model jargon)
  const townNote = typeof c.town_note === 'string'
    ? c.town_note.replace(/\s*Town public-supply[^.]*\.?/i, '').replace(/\s*\(not verified\)/i, '').replace(/^Main towns:\s*/i, '').replace(/\.\s*$/, '').trim() : '';
  if (townNote) items.push(['Main towns (people)', esc(townNote)]);
  for (const k of Object.keys(CTX_LABELS)) {
    if (townNote && (k === 'main_towns' || k === 'towns')) continue;
    const v = c[k];
    if (v == null || v === '') continue;
    let t;
    if (Array.isArray(v)) t = esc(v.join(', '));
    else if (typeof v === 'number') t = k.endsWith('_usd') ? '$' + fmt(v) : k === 'ag_share_of_economy' && v <= 1 ? fmt(v * 100) + '%' : fmt(v);
    else t = esc(v);
    items.push([CTX_LABELS[k], t]);
  }
  const corn = isNum(c.corn_share_irrigated) ? `${fmt(c.corn_share_irrigated * 100)}% of irrigated acres are corn.` : '';
  return `<section class="card"><h3>${esc(c.name)} County: who depends on this water</h3>
    <dl class="facts">
      <div><dt>Irrigated acres</dt><dd>${isNum(c.irrigated_acres) ? fmt(c.irrigated_acres) : NA}</dd></div>
      <div><dt>Pumping</dt><dd>${isNum(c.pumping_af_yr) ? fmt(c.pumping_af_yr) + ' acre-ft/yr' : NA}</dd></div>
      <div><dt>Water-bearing layer</dt><dd>${rangeText(c.sat_thick_ft, v => fmt(v), 'ft')}</dd></div>
      <div><dt>Corn share</dt><dd>${corn || NA}</dd></div>
    </dl>
    ${items.length ? `<dl class="kv ctx">${items.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join('')}</dl>` : '<p>Town and local-economy details: not available.</p>'}
    ${c.town_note ? '<p class="fine">Town public-supply wells are not linked to this clock.</p>' : ''}</section>`;
}

export function renderCommunity() {
  const root = document.getElementById('community-panel');
  root.innerHTML = `<section class="card"><h2>County and district water clocks</h2>
      <p class="ck-sub">Years until the typical irrigated acre falls below ${S.thr} ft of water-bearing layer. Click a county name to zoom the map.</p>
      ${gmdCards()}${countyTable()}</section>
    ${sliderBlock()}<div id="cc-ctx"></div>`;
  document.getElementById('cc-ctx').innerHTML = countyContext();
  renderShift();
  root.querySelectorAll('[data-sort]').forEach(b => b.addEventListener('click', () => {
    const k = b.dataset.sort; if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = 1; }
    renderCommunity(); root.querySelector(`[data-sort="${k}"]`)?.focus();
  }));
  root.querySelectorAll('[data-fips]').forEach(b => b.addEventListener('click', () => actions.selectCounty(b.dataset.fips, 'community')));
  root.querySelector('#sh-county')?.addEventListener('change', e => { S.cFips = e.target.value; actions.selectCounty(S.cFips, 'community'); });
  root.querySelector('#sh-strat')?.addEventListener('change', e => { S.cStrat = e.target.value; renderShift(); });
  const p = root.querySelector('#sh-pct');
  p?.addEventListener('input', () => { S.cPct = +p.value; document.getElementById('sh-pct-v').textContent = S.cPct + '%'; renderShift(); });
}
