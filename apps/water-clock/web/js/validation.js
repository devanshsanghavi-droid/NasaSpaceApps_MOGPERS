// "Proof & data" view: hindcast metrics, 2045 climate shift, data sources, caveats.
import { esc, fmt, num, lo, hi, isNum, link, prettyKey, NA, rangeText, fmtSigned } from './util.js';
import { countyName } from './data.js';

let D, S;
export function initValidation(data, state) { D = data; S = state; }

const isObj = v => v && typeof v === 'object' && !Array.isArray(v);
const isRange = v => isObj(v) && ['est', 'lo', 'hi', 'p10', 'p50', 'p90'].some(k => k in v) && Object.values(v).every(x => x === null || isNum(x));

function cell(v) {
  if (v === null || v === undefined) return '<span class="na">n/a</span>';
  if (isNum(v)) {
    if (Number.isInteger(v)) return v >= 1800 && v <= 2200 ? String(v) : fmt(v, 0);
    return fmt(v, Math.abs(v) < 10 ? 2 : 1);
  }
  if (isRange(v)) return rangeText(v, x => fmt(x, 2));
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (Array.isArray(v)) return v.length <= 8 && v.every(x => typeof x !== 'object') ? esc(v.join(', ')) : `<span class="na">${v.length} values</span>`;
  if (typeof v === 'string') return esc(v.length > 1500 ? v.slice(0, 1500) + '...' : v);
  return null;
}

// Object whose values are all objects sharing scalar keys -> matrix table.
function asMatrix(o) {
  const rows = Object.entries(o).filter(([, v]) => isObj(v) && !isRange(v));
  if (rows.length < 2 || rows.length !== Object.keys(o).length) return null;
  const cols = [];
  for (const [, v] of rows) for (const [k, x] of Object.entries(v)) if (!isObj(x) || isRange(x)) { if (!cols.includes(k)) cols.push(k); }
  if (!cols.length || rows.some(([, v]) => Object.values(v).some(x => isObj(x) && !isRange(x)))) return null;
  return `<div class="table-wrap"><table class="mtable"><thead><tr><th scope="col"></th>${cols.map(c => `<th scope="col">${esc(prettyKey(c))}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(([rk, v]) => `<tr class="${/model|ours|state/i.test(rk) && !/base/i.test(rk) ? 'ours' : ''}"><th scope="row">${esc(prettyKey(rk))}</th>${cols.map(c => `<td>${cell(v[c]) ?? ''}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function render(o, depth = 0) {
  if (!isObj(o)) return cell(o) ?? '';
  const m = asMatrix(o);
  if (m) return m;
  const scalars = Object.entries(o).filter(([, v]) => cell(v) !== null);
  const nested = Object.entries(o).filter(([, v]) => cell(v) === null);
  let html = '';
  if (scalars.length) html += `<dl class="kv">${scalars.map(([k, v]) => `<div><dt>${esc(prettyKey(k))}</dt><dd>${cell(v)}</dd></div>`).join('')}</dl>`;
  for (const [k, v] of nested) {
    if (depth > 3) continue;
    html += `<div class="nest"><h${Math.min(6, 4 + depth)}>${esc(prettyKey(k))}</h${Math.min(6, 4 + depth)}>${render(v, depth + 1)}</div>`;
  }
  return html;
}

function climateBlock() {
  const c = D.climate;
  if (!c) return `<p>${NA}: climate.json is missing.</p>`;
  const src = isObj(c.scenarios) ? c.scenarios : c;
  const scen = Object.entries(src).filter(([, v]) => isObj(v) && ('et0_change_pct' in v || 'clock_shift_years' in v));
  if (!scen.length) return render(c);
  const shift = v => {
    const cs = v.clock_shift_years;
    if (isNum(cs) || isRange(cs)) return cs;
    if (isObj(cs)) {
      const cf = S.fips || S.cFips;
      const county = cf && (cs.county?.[cf] ?? cs.counties?.[cf] ?? cs[cf]);
      return { region: cs.region ?? cs.region_mean ?? null, county, cf };
    }
    return null;
  };
  const label = k => ({ ssp245: 'Middle-of-the-road emissions (SSP2-4.5)', ssp585: 'High emissions (SSP5-8.5)' }[k] || k);
  const r = (v, f, u) => (isNum(num(v)) ? rangeText(v, f, u) : '<span class="na">n/a</span>');
  return `<div class="clim-row">${scen.map(([k, v]) => {
      const s = shift(v);
      const reg = isObj(s) && 'region' in s ? s.region : s;
      return `<div class="clim">
        <h4>${esc(label(k))}</h4>
        ${(() => {
          const cb = v.clock_shift_years_combined?.region;
          if (cb && isNum(cb.pumping_only) && isNum(cb.total_response)) {
            return `<div class="clim-big"><b>${fmtSigned(cb.pumping_only, 0)} to ${fmtSigned(cb.total_response, 0)}</b> years on the region's clock</div>
              <div class="fine">From extra pumping only (${fmtSigned(cb.pumping_only, 1)}) to the full fitted weather response of water levels, which also counts lower recharge (${fmtSigned(cb.total_response, 1)}). Range over 5 models and both routes: ${fmtSigned(cb.hi, 1)} to ${fmtSigned(cb.lo, 1)} years.</div>`;
          }
          return `<div class="clim-big">${isNum(num(reg)) ? `<b>${fmtSigned(num(reg), 1)}</b> years on the region's clock` : 'Clock shift: <span class="na">n/a</span>'}</div>
            ${isNum(num(reg)) && isNum(lo(reg)) && lo(reg) !== hi(reg) ? `<div class="fine">range ${fmtSigned(lo(reg), 1)} to ${fmtSigned(hi(reg), 1)} years</div>` : ''}`;
        })()}
        ${isObj(s) && isNum(num(s.county)) ? `<div class="fine">${esc(countyName(D, s.cf))} County: ${rangeText(s.county, x => fmtSigned(x, 1), 'years')} (pumping only)${isNum(num(v.clock_shift_years_total_response?.county?.[s.cf])) ? `; ${fmtSigned(num(v.clock_shift_years_total_response.county[s.cf]), 1)} with the full weather response` : ''}</div>` : ''}
        <dl class="facts">
          <div><dt>Crop water demand (ET0)</dt><dd>${r(v.et0_change_pct, x => fmtSigned(x, 1), '%')}</dd></div>
          <div><dt>Apr-Sep rain</dt><dd>${r(v.gs_precip_change_in, x => fmtSigned(x, 1), 'in')}</dd></div>
          <div><dt>Extra irrigation needed</dt><dd>${r(v.extra_pumping_in_ac, x => fmtSigned(x, 1), 'in/acre')}</dd></div>
        </dl></div>`;
    }).join('')}</div>
    <p class="fine">Change from ${esc(c.baseline || '1995-2014')} to ${esc(c.future || 'around 2045')}${Array.isArray(c.models) ? `, ${c.models.length} climate models (${esc(c.models.join(', '))})` : ''}. Source: NASA NEX-GDDP-CMIP6. The 2035-2055 change is applied from today over the whole horizon.</p>`;
}

function sourcesBlock() {
  const ds = D.meta?.data_sources;
  if (!Array.isArray(ds) || !ds.length) return `<p>${NA}: meta.json is missing.</p>`;
  const order = s => (s.nasa ? 0 : 1);
  return `<ul class="sources">${[...ds].sort((a, b) => order(a) - order(b)).map(s => `<li>
      ${s.nasa ? '<span class="badge nasa">NASA</span>' : '<span class="badge partner">partner</span>'}
      <span class="st st-${esc(s.status || 'used')}">${esc(s.status || 'used')}</span>
      <b>${link(s.name || 'source', s.url)}</b>${s.role ? ` &mdash; ${esc(s.role)}` : ''}</li>`).join('')}</ul>`;
}

const TABLE_TITLES = {
  hindcast_2014_temporal_10yr_change_ft: 'Trained to 2014: 10-year change 2014 to 2024, same wells (ft)',
  hindcast_2014_spatial_10yr_change_ft: 'Trained to 2014: 10-year change 2014 to 2024, wells the model never saw (ft). This is the test that matches the field clock.',
  hindcast_2004_temporal_10yr_change_ft: 'Trained to 2004: 10-year change 2004 to 2014, same wells (ft)',
  hindcast_2004_spatial_10yr_change_ft: 'Trained to 2004: 10-year change 2004 to 2014, wells the model never saw (ft)',
  hindcast_2014_temporal_latest_level_ft: 'Trained to 2014: latest water level (2024-2026), same wells (ft)',
  hindcast_2014_spatial_latest_level_ft: 'Trained to 2014: latest water level, wells the model never saw (ft)',
  hindcast_2004_temporal_latest_level_ft: 'Trained to 2004: water level about 10 years later, same wells (ft)',
  hindcast_2004_spatial_latest_level_ft: 'Trained to 2004: water level about 10 years later, wells the model never saw (ft)',
  saturated_thickness_vs_usgs_2009: 'Our rebuilt 2009 saturated thickness vs the USGS 2009 map',
  water_balance: 'Water balance (pumping vs decline)',
  grace_vs_wells: 'GRACE vs wells',
  model_settings: 'Model settings',
};
const OPEN_TABLES = ['hindcast_2014_temporal_10yr_change_ft', 'hindcast_2014_spatial_10yr_change_ft', 'hindcast_2004_temporal_10yr_change_ft'];

function verdictTiles(v) {
  const covs = Object.entries(v).filter(([k, x]) => k.startsWith('hindcast_') && isNum(x?.model?.cov80)).map(([, x]) => x.model.cov80);
  const t4 = v.hindcast_2004_temporal_10yr_change_ft, pub = v.saturated_thickness_vs_usgs_2009;
  const tiles = [];
  if (covs.length) tiles.push([`${fmt(Math.min(...covs) * 100, 0)}-${fmt(Math.max(...covs) * 100, 0)}%`, `of the time our 80% ranges held the truth (${covs.length} tests; should be about 80%)`]);
  if (isNum(t4?.model?.mae) && isNum(t4?.baseline_no_change?.mae)) tiles.push([`${fmt(t4.model.mae, 1)} vs ${fmt(t4.baseline_no_change.mae, 1)} ft`, 'error when trained to 2004, model vs "no change" (declines sped up after 2004)']);
  if (isNum(pub?.r)) tiles.push([`r = ${fmt(pub.r, 2)}`, `our rebuilt 2009 thickness vs the USGS 2009 map (typical error ${fmt(pub.mae_ft, 0)} ft)`]);
  return tiles.length ? `<div class="verdicts">${tiles.map(([a, b]) => `<div class="verdict"><span class="v">${esc(a)}</span><span class="l">${esc(b)}</span></div>`).join('')}</div>` : '';
}

function tableBlock(k, x) {
  return `<div class="nest"><h4>${esc(TABLE_TITLES[k] || prettyKey(k))}</h4>${render(x)}</div>`;
}

export function renderValidation() {
  const root = document.getElementById('data-panel');
  const v = D.validation;
  const skip = new Set(['summary', 'train_end', 'test_years', 'n_wells_test']);
  const rest = v ? Object.entries(v).filter(([k]) => !skip.has(k) && !OPEN_TABLES.includes(k)) : [];
  root.innerHTML = `
    <section class="card wide">
      <h2>Does the clock work? Testing on the past</h2>
      <p class="ck-sub">We hid the water levels measured after a cut-off year (2014, and separately 2004), let the model predict the next 10 years from earlier data only, then compared with what wells actually measured.
      Lower error is better; "80% interval coverage" should be near 0.80. Baselines are simple rules the model must beat.</p>
      ${v ? verdictTiles(v) : ''}
      ${v?.summary ? `<p class="plain">${esc(v.summary)}</p>` : ''}
      ${v ? OPEN_TABLES.filter(k => v[k]).map(k => tableBlock(k, v[k])).join('') : `<p>${NA}: validation.json is missing.</p>`}
      ${rest.length ? `<details class="tech"><summary>Technical tables (water levels, other tests, water balance, GRACE, model settings)</summary>${rest.map(([k, x]) => tableBlock(k, x)).join('')}</details>` : ''}
    </section>
    <div class="two-col">
      <section class="card"><h3>How climate shifts the clock by 2045</h3>${climateBlock()}</section>
      <section class="card"><h3>Data sources</h3>${sourcesBlock()}
        ${Array.isArray(D.meta?.caveats) && D.meta.caveats.length ? `<h4>Caveats</h4><ul>${D.meta.caveats.map(c => `<li>${esc(c)}</li>`).join('')}</ul>` : ''}
      </section>
    </div>`;
}
