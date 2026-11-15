// Farmer view: "Your Water Clock" for a field (or county) + strategy cards.
import { esc, fmt, num, lo, hi, isNum, yrs, money, rangeText, list, link, NA, fmtSigned, CAP } from './util.js';
import { fieldYears, countyYears, yearsGained, pumpingShare, strategyApplies } from './scenario.js';
import { clockSvg, uncertaintyText, rangeLine } from './clock.js';
import { countyName } from './data.js';

let D, S, actions;

export function initFarmer(data, state, act) { D = data; S = state; actions = act; }

function thrButtons() {
  return `<div class="thr-btns" role="group" aria-label="Usable-water threshold">
    <span class="thr-lab">Too thin to irrigate below:</span>
    ${D.thresholds.map(t => `<button type="button" class="chip" data-thr="${t}" aria-pressed="${t === S.thr}">${t} ft</button>`).join('')}
  </div>`;
}

function strategyNumbers(fips, s) {
  const pc = D.strategies?.per_county?.[fips]?.[s.id] || {};
  const shift = (base, local) => {
    const c = num(base), l = num(local);
    if (!isNum(l)) return base;
    if (!isNum(c)) return { est: l };
    return { est: l, lo: lo(base) - c + l, hi: hi(base) - c + l };
  };
  return {
    water: shift(s.water_in_ac, pc.net_pumping_in_ac),
    income: shift(s.income_usd_ac, pc.income_usd_ac),
  };
}

// Score = priority-weighted mix of years gained and income, both normalised over the alternative
// plans only (S0 excluded from the range). A plan is eligible for "Best fit" only if it keeps at
// least (1 - priority) of today's income, so a balanced setting never recommends giving up most of
// the income; no water weight is given when no plan has a usable gain here.
function scoreStrategies(fips, years) {
  const rows = D.strategyList.filter(s => strategyApplies(D, fips, s)).map(s => {
    const n = strategyNumbers(fips, s);
    const g = yearsGained(D, fips, s.id, years);
    return { s, n, g };
  });
  const alt = rows.filter(r => r.s.id !== 'S0');
  const norm = (vals) => {
    const v = vals.filter(isNum);
    const mn = Math.min(...v), mx = Math.max(...v);
    return x => (!isNum(x) || !v.length ? 0 : mx - mn < 1e-9 ? 0.5 : (x - mn) / (mx - mn));
  };
  const hasGain = alt.some(r => isNum(r.g?.est) && Math.abs(r.g.est) > 0.05);
  const nG = norm(alt.map(r => r.g?.est)), nI = norm(alt.map(r => num(r.n.income)));
  const w = hasGain ? S.priority / 100 : 0;
  const inc0 = num(rows.find(r => r.s.id === 'S0')?.n.income);
  const minInc = isNum(inc0) && inc0 > 0 ? (1 - S.priority / 100) * inc0 : null;
  rows.forEach(r => {
    r.score = w * nG(r.g?.est) + (1 - w) * nI(num(r.n.income));
    r.eligible = r.s.id !== 'S0' && (!isNum(minInc) || (isNum(num(r.n.income)) && num(r.n.income) >= minInc));
  });
  rows.hasGain = hasGain;
  rows.minIncShare = isNum(minInc) ? 1 - S.priority / 100 : null;
  return rows;
}

function card(r, years, best, rank) {
  const { s, n, g } = r;
  const isCur = s.id === 'S0';
  const ev = Array.isArray(s.evidence) && s.evidence.length
    ? '<ul class="ev">' + s.evidence.map(e => `<li>${esc(e.text || '')}${e.source || e.url ? ` <span class="src">(${link(e.source || 'source', e.url)})</span>` : ''}</li>`).join('') + '</ul>'
    : NA;
  const gainTxt = isCur ? 'Today\'s clock'
    : years.below ? '<span class="na">already below the threshold here; try a lower threshold</span>'
    : !g ? NA
    : g.atCap ? 'none needed: already 100+ years here'
    : `${fmtSigned(g.est, 0)} years${g.hi - g.lo >= 0.5 ? ` <span class="rng">(range ${fmtSigned(g.lo, 0)} to ${g.hiCapped ? 'clock 100+' : fmtSigned(g.hi, 0)})</span>` : ''}`;
  const newClock = !isCur && g && !g.atCap && !years.below && isNum(years.p50) && years.p50 > 0 && years.p50 < CAP
    ? `<div class="sub">clock ${yrs(years.p50)} &rarr; ${yrs(years.p50 + g.est)} years${g.hiCapped && !g.capped ? ' (up to 100+)' : ''}</div>` : '';
  const rot = Array.isArray(s.rotation) && s.rotation.length ? s.rotation.map(c => `<span class="crop">${esc(c)}</span>`).join('<span class="arrow" aria-hidden="true">&rarr;</span>') : '';
  return `<article class="strat ${best ? 'best' : ''} ${isCur ? 'current' : ''}" aria-label="${esc(s.name || s.id)}">
    <header>
      ${best ? '<span class="badge best-badge">Best fit for your priorities</span>' : ''}
      ${isCur ? '<span class="badge cur-badge">What most fields do now</span>' : ''}
      <h4>${esc(s.name || s.id)}</h4>
      <div class="rot">${rot}${s.irrigation ? `<span class="irr irr-${esc(s.irrigation)}">${esc({ full: 'full irrigation', limited: 'limited irrigation', none: 'no irrigation' }[s.irrigation] || s.irrigation)}</span>` : ''}</div>
    </header>
    <dl class="metrics">
      <div><dt>Years gained if all irrigated land around you switched</dt><dd class="m-gain">${gainTxt}${newClock}</dd></div>
      <div><dt>Water pumped</dt><dd>${rangeText(n.water, v => fmt(v, 0), 'in/acre/yr')}</dd></div>
      <div><dt>Net income</dt><dd>${rangeText(n.income, money, '/acre/yr')}</dd></div>
      <div><dt>Drought yield risk</dt><dd>${s.yield_risk ? esc(s.yield_risk) : NA}</dd></div>
    </dl>
    <p class="why"><b>Why suggested:</b> ${s.why ? esc(s.why) : NA}</p>
    ${s.applies_where ? `<p class="where"><b>Where it fits:</b> ${esc(s.applies_where)}</p>` : ''}
    <details>
      <summary>Soil health, evidence, gaps and risks</summary>
      <h5>Soil health</h5><p>${s.soil_health ? esc(s.soil_health) : NA}</p>
      <h5>Benefits</h5>${list(s.benefits)}
      <h5>Evidence</h5>${ev}
      <h5>What we don't know yet</h5>${list(s.gaps)}
      <h5>Risks to check locally</h5>${list(s.risks)}
    </details>
  </article>`;
}

function strategiesBlock(fips, years, crop) {
  if (!D.strategyList.length) return `<section class="card"><h3>Strategies</h3><p>${NA}: strategies.json is missing.</p></section>`;
  const rows = scoreStrategies(fips, years);
  const anyGain = rows.some(r => r.s.id !== 'S0' && r.g && isNum(r.g.est));
  const best = anyGain ? rows.filter(r => r.eligible).sort((a, b) => b.score - a.score)[0] : null;
  const sorted = [...rows].sort((a, b) => (a.s.id === 'S0' ? -1 : b.s.id === 'S0' ? 1 : b.score - a.score));
  const share = pumpingShare(D, fips);
  const nAll = D.strategyList.length, nHere = rows.length;
  const cropNote = crop && !/corn/i.test(crop)
    ? `<p class="note">Compared with continuous irrigated corn, the most common plan here. This well's crop on record is <b>${esc(crop)}</b>, so its own savings may differ.</p>` : '';
  const hidNote = nHere < nAll ? `<p class="fine">${nAll - nHere} plan${nAll - nHere > 1 ? 's are' : ' is'} not shown because ${nAll - nHere > 1 ? 'they were' : 'it was'} only assessed for other counties.</p>` : '';
  return `<section class="card strategies" aria-labelledby="st-h">
    <h3 id="st-h">What could you grow instead?</h3>
    <div class="prio">
      <label for="prio">What matters most to you?</label>
      <div class="prio-row"><span>Protect income</span>
        <input id="prio" type="range" min="0" max="100" step="5" value="${S.priority}" aria-valuetext="${S.priority < 35 ? 'mostly income' : S.priority > 65 ? 'mostly water life' : 'balanced'}">
        <span>Make water last</span></div>
    </div>
    ${cropNote}
    <div class="strat-list">${sorted.map((r, i) => card(r, years, best && r === best, i)).join('')}</div>
    ${hidNote}
    ${best ? `<p class="fine">"Best fit" weighs years gained against income using the slider${isNum(rows.minIncShare) && rows.minIncShare > 0 ? `, among plans that keep at least ${fmt(rows.minIncShare * 100, 0)}% of today's income` : ''}.${rows.hasGain ? '' : ' No plan shows a years gain here, so it is based on income only.'}</p>` : '<p class="fine">No "best fit" is shown because no plan has a years-gained estimate at this spot and threshold.</p>'}
    <p class="fine">Years gained assume this field <em>and all irrigated land around it</em> (every crop, not only corn) on the same part of the aquifer make the same change; one field alone barely moves the local water table. The "My county" slider moves only corn acres, so its gains are smaller.
      ${share.assumed ? 'The share of the decline caused by pumping is not available for this county, so all of it is attributed to pumping.'
        : share.capped ? `In ${esc(countyName(D, fips))} County the water balance says recent pumping alone would cause about ${fmt(share.raw, 1)} times the observed decline, so water also flows back in (recharge, return flow). The central number assumes the decline shrinks only in proportion to pumping, which is likely conservative: the top of each range lets the decline respond more strongly. In the Sheridan-6 area a 35% pumping cut slowed the decline by about 80% (Kansas Geological Survey, 2017).`
        : `In ${esc(countyName(D, fips))} County the model attributes about ${fmt(share.share * 100, 0)}% of the water-table decline to local pumping.`}
      Income ranges come from year-to-year swings in county yields and Kansas prices. ${D.strategies?.method ? esc(D.strategies.method) : ''}</p>
    <p class="agro"><b>Decision support, not a replacement for your agronomist.</b> Talk to your agronomist, crop insurer and GMD before changing a rotation or water right.</p>
  </section>`;
}

function intro() {
  const opts = Object.keys(D.countyByFips).length ? Object.values(D.countyByFips) : Object.values(D.geoByFips);
  return `<section class="card intro">
    <h2>Find your water clock</h2>
    <ol class="steps">
      <li><b>Click a dot</b> on the map: each one is an irrigation well (a Kansas water-right point of diversion).</li>
      <li>Or <b>pick your county</b>:
        <select id="intro-county" aria-label="Choose a county"><option value="">Choose a county...</option>
        ${opts.sort((a, b) => String(a.name).localeCompare(b.name)).map(c => `<option value="${esc(c.fips)}">${esc(c.name)}</option>`).join('')}</select></li>
      <li>See how many years of water are left, and what each crop plan would change.</li>
    </ol>
    <p class="fine">"Years left" means years until the water-bearing layer under you (the Ogallala / High Plains aquifer) is thinner than the threshold you choose, usually 30 ft, the approximate minimum Kansas agencies use for large-volume irrigation wells.</p>
  </section>`;
}

function fieldFacts(f) {
  const inAc = isNum(f.af_yr) && isNum(f.acres) && f.acres > 0 ? f.af_yr * 12 / f.acres : null;
  return `<dl class="facts">
    <div><dt>Water-bearing layer now</dt><dd>${isNum(f.sat_ft) ? fmt(f.sat_ft) + ' ft thick' : NA}</dd></div>
    <div><dt>Water table change</dt><dd>${isNum(f.decl) ? (f.decl > 0 ? 'falling ' + fmt(f.decl, 1) + ' ft/yr' : 'not falling') : NA}</dd></div>
    <div><dt>Irrigated acres</dt><dd>${isNum(f.acres) ? fmt(f.acres) : NA}</dd></div>
    <div><dt>Reported pumping</dt><dd>${isNum(f.af_yr) ? fmt(f.af_yr) + ' acre-ft/yr' + (isNum(inAc) ? ` (${fmt(inAc, 1)} in/acre)` : '') : NA}</dd></div>
    <div><dt>Crop on record</dt><dd>${f.crop ? esc(f.crop) : NA}</dd></div>
    <div><dt>County</dt><dd>${esc(countyName(D, f.fips))}</dd></div>
  </dl>`;
}

// 2045 climate stress test (NASA NEX-GDDP-CMIP6) for the county, from climate.json.
function climateLine(fips) {
  const sc = D.climate?.scenarios?.ssp245;
  const c = sc?.clock_shift_years_combined?.county?.[fips];
  if (!c || !isNum(c.pumping_only)) return '';
  const a = c.pumping_only, b = isNum(c.total_response) ? c.total_response : a;
  const txt = Math.abs(a) < 0.5 && Math.abs(b) < 0.5 ? 'little change (the county clock is at or near 100+)'
    : `about <b>${fmtSigned(Math.max(a, b), 0)} to ${fmtSigned(Math.min(a, b), 0)} years</b> on the county clock`;
  return `<p class="nasa-line"><b>2045 climate</b> (NASA NEX-GDDP-CMIP6, 5 models, SSP2-4.5): ${txt}, from extra pumping only up to the full weather response of water levels.</p>`;
}

function clockCard(title, sub, y, extra, opts = {}) {
  return `<section class="card clock-card" aria-labelledby="ck-h">
    <h2 id="ck-h">${title}</h2>
    <p class="ck-sub">${sub}</p>
    <div class="clock-row">
      ${clockSvg(y)}
      <div class="clock-text">
        <div class="ck-big">${y.below ? `Already below <span class="n">${S.thr}</span> ft` : `<span class="n">${yrs(y.p50)}</span> years left`}</div>
        <div class="ck-range">${rangeLine(y)}</div>
        ${thrButtons()}
      </div>
    </div>
    <p class="plain">${opts.outside ? 'This well is outside the mapped High Plains aquifer area, so there is no saturated-thickness estimate and no clock here.' : uncertaintyText(y, S.thr)}</p>
    ${opts.fips ? climateLine(opts.fips) : ''}
    ${extra || ''}
  </section>`;
}

function fieldPicker(fips) {
  const fs = D.fieldRows.filter(f => f.fips === fips).sort((a, b) => (b.acres || 0) - (a.acres || 0)).slice(0, 400);
  if (!fs.length) return '';
  return `<label class="picker">Pick a well in this county (largest first)
    <select id="field-pick"><option value="">Choose a well...</option>
    ${fs.map(f => `<option value="${esc(f.id)}">${esc(f.id)}: ${isNum(f.acres) ? fmt(f.acres) + ' ac' : ''} ${f.crop ? esc(f.crop) : ''}, ${yrs(fieldYears(f, S.thr, D.defaultThr).p50)} yrs</option>`).join('')}
    </select></label>`;
}

export function renderFarmer() {
  const root = document.getElementById('farmer-panel');
  let html = '';
  const f = S.fieldId ? D.fieldRows.find(x => String(x.id) === S.fieldId) : null;
  if (f) {
    const y = fieldYears(f, S.thr, D.defaultThr);
    html += clockCard('Your Water Clock', `Irrigation well ${esc(f.id)}, ${esc(countyName(D, f.fips))} County`, y,
      fieldFacts(f) + `<button type="button" class="link-btn" id="to-county">See ${esc(countyName(D, f.fips))} County's clock</button>`,
      { outside: !isNum(f.sat_ft), fips: f.fips });
    html += strategiesBlock(f.fips, y, f.crop);
  } else if (S.fips) {
    const c = D.countyByFips[S.fips];
    const y = c ? countyYears(c, S.thr, D) : { p10: null, p50: null, p90: null };
    const extra = (c ? `<dl class="facts">
        <div><dt>Water-bearing layer (typical)</dt><dd>${rangeText(c.sat_thick_ft, v => fmt(v), 'ft')}</dd></div>
        <div><dt>Water table change</dt><dd>${isNum(num(c.decline_ft_yr)) ? rangeText(c.decline_ft_yr, v => fmt(v, 1), 'ft/yr falling') : NA}</dd></div>
        <div><dt>Irrigated acres</dt><dd>${isNum(c.irrigated_acres) ? fmt(c.irrigated_acres) : NA}</dd></div>
        <div><dt>Monitoring wells used</dt><dd>${isNum(c.n_wells) ? fmt(c.n_wells) : NA}${c.data_quality ? ` <span class="dq dq-${esc(c.data_quality)}">${esc(c.data_quality)} data</span>` : ''}</dd></div>
      </dl>` : `<p>${NA}: no county clock for this county.</p>`) + fieldPicker(S.fips);
    html += clockCard(`${esc(countyName(D, S.fips))} County's Water Clock`, 'Typical irrigated acre in the county. Click a dot or pick a well for your own spot.', y, extra, { fips: S.fips });
    html += strategiesBlock(S.fips, y);
  } else {
    html = intro();
  }
  root.innerHTML = html;
  bind(root);
}

function bind(root) {
  root.querySelectorAll('[data-thr]').forEach(b => b.addEventListener('click', () => actions.setThr(+b.dataset.thr)));
  root.querySelector('#intro-county')?.addEventListener('change', e => e.target.value && actions.selectCounty(e.target.value));
  root.querySelector('#field-pick')?.addEventListener('change', e => e.target.value && actions.selectField(e.target.value));
  root.querySelector('#to-county')?.addEventListener('click', () => actions.selectCounty(D.fieldRows.find(x => String(x.id) === S.fieldId)?.fips, 'community'));
  const pr = root.querySelector('#prio');
  if (pr) {
    pr.addEventListener('change', () => { S.priority = +pr.value; renderFarmerKeepFocus('#prio'); });
    pr.addEventListener('input', () => { S.priority = +pr.value; });
  }
}

function renderFarmerKeepFocus(sel) {
  const y = window.scrollY, pc = document.querySelector('.panel-col'), py = pc ? pc.scrollTop : 0;
  renderFarmer();
  document.querySelector(sel)?.focus({ preventScroll: true });
  if (pc) pc.scrollTop = py;
  window.scrollTo(0, y);
}
