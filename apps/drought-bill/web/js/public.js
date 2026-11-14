// Public view: headline bill, county choropleth (layers + taxpayer toggle), county card with diversity slider, 2022 hindcast.
import { val, scale, pick, usd, usdBig, rangeTxt, pct, num, esc, interp, isNum, NA, STATE_NAMES } from './util.js';
import { createMap, makeScale, NODATA } from './map.js';
import { pairedBars, scatter, diversityChart } from './charts.js';

// ColorBrewer "Reds" (sequential, single hue, lightness-monotonic: readable with colour-vision deficiency)
export const REDS = ['#fee5d9', '#fcbba1', '#fc9272', '#fb6a4a', '#ef3b2c', '#cb181d', '#99000d'];
const LAYERS = {
  expected: { tab: 'Expected / yr', long: 'expected drought bill per year' },
  a2022: { tab: '2022 actual', long: 'actual 2022 drought bill' },
  ssp245: { tab: '2045 moderate', long: 'expected bill around 2045, moderate emissions (SSP2-4.5)' },
  ssp585: { tab: '2045 high', long: 'expected bill around 2045, high emissions (SSP5-8.5)' },
};

export function countyLabel(c, fips) {
  if (!c) return fips;
  return `${c.name || fips}${/county|parish/i.test(c.name || '') ? '' : ' County'}, ${c.state || ''}`;
}

export function layerValue(c, layer, taxpayer) {
  if (!c) return val(null);
  let v;
  if (layer === 'expected') {
    if (taxpayer && c.taxpayer_expected_bill) return val(c.taxpayer_expected_bill);
    v = val(c.expected_bill);
  } else if (layer === 'a2022') v = val(pick(c.actual || {}, '2022', 2022));
  else v = val(c.bill_2045?.[layer]);
  return taxpayer ? scale(v, isNum(c.subsidy_share) ? c.subsidy_share : null) : v;
}

/** Region totals: prefer regional_summary.json, else sum county $/ac x insured acres (derived, not invented). */
function regionTotals(D) {
  const r = D.summary?.region || D.summary?.totals || null;
  const counties = D.bill?.counties || {};
  const sum = (fn) => {
    let est = 0, lo = 0, hi = 0, n = 0, hasR = true;
    for (const c of Object.values(counties)) {
      const v = fn(c), A = c.insured_acres;
      if (!isNum(v.est) || !isNum(A)) continue;
      est += v.est * A; n++;
      if (isNum(v.lo) && isNum(v.hi)) { lo += v.lo * A; hi += v.hi * A; } else hasR = false;
    }
    return n ? { est, lo: hasR ? lo : null, hi: hasR ? hi : null } : val(null);
  };
  const t = {
    expected: val(pick(r, 'expected_bill_usd', 'expected_annual_bill_usd', 'expected_bill')),
    taxpayer: val(pick(r, 'taxpayer_share_usd', 'taxpayer_expected_bill_usd', 'taxpayer_usd')),
    a2022: val(pick(r, 'actual_2022_usd') ?? pick(r?.actual || {}, '2022')),
    ch245: val(r?.change_2045_pct?.ssp245),
    ch585: val(r?.change_2045_pct?.ssp585),
    savings: val(pick(r, 'diversity_savings_usd')),
    name: r?.name,
  };
  if (!isNum(t.expected.est)) t.expected = sum((c) => val(c.expected_bill));
  if (!isNum(t.taxpayer.est)) t.taxpayer = sum((c) => layerValue(c, 'expected', true));
  if (!isNum(t.a2022.est)) t.a2022 = sum((c) => layerValue(c, 'a2022', false));
  return t;
}

/** Region-wide saving on a 2022-style bill if every county rose to at least the regional p90 diversity. */
function diversitySavings(counties) {
  let est = 0, lo = 0, hi = 0, base = 0, n = 0;
  for (const c of Object.values(counties || {})) {
    const s = c.slider, d = c.diversity, A = c.insured_acres;
    if (!s || !d || !isNum(A) || !isNum(d.now) || !isNum(d.p90_region)) continue;
    const tgt = Math.max(d.now, d.p90_region);
    const b0 = interp(s.div_values, s.bill_2022_style, d.now), b1 = interp(s.div_values, s.bill_2022_style, tgt);
    if (!isNum(b0) || !isNum(b1)) continue;
    est += (b0 - b1) * A; base += b0 * A; n++;
    const dl = (interp(s.div_values, s.lo, d.now) ?? b0) - (interp(s.div_values, s.lo, tgt) ?? b1);
    const dh = (interp(s.div_values, s.hi, d.now) ?? b0) - (interp(s.div_values, s.hi, tgt) ?? b1);
    lo += Math.min(dl, dh) * A; hi += Math.max(dl, dh) * A;
  }
  return n ? { est, lo, hi, base, share: base > 0 ? est / base : null } : null;
}

export function initPublic(D, state, onSelect) {
  const counties = D.bill?.counties || {};
  const T = regionTotals(D);
  const sav = isNum(T.savings.est) ? { ...T.savings, share: null } : diversitySavings(counties);
  const nasa = (D.meta?.data_sources || []).filter((s) => s.nasa).map((s) => s.name.split('(')[0].trim());
  const dollarYear = D.bill?.dollar_year || D.summary?.dollar_year;

  function renderHero() {
    const tax = state.taxpayer;
    const big = tax ? T.taxpayer : T.expected;
    const pctTax = isNum(T.taxpayer.est) && isNum(T.expected.est) && T.expected.est > 0 ? T.taxpayer.est / T.expected.est : null;
    document.getElementById('hero').innerHTML = `
      <p class="eyebrow">The drought bill · ${esc(T.name || '7 Corn Belt and Plains states')} · crop insurance</p>
      <h1 class="hero-h">${tax ? 'Taxpayers pay' : 'Drought costs'} <span class="red money">${usdBig(big.est)}</span> ${tax ? 'of the drought bill' : ''} every year${tax ? '.' : ' in insured crop losses.'}</h1>
      <p class="hero-range">Expected yearly crop-insurance payouts for drought${tax ? ' funded by premium subsidies' : ''}${rangeTxt(big, usdBig) ? `, likely range <b>${rangeTxt(big, usdBig)}</b>` : ''}${dollarYear ? ` (${esc(dollarYear)} dollars)` : ''}.</p>
      <p class="hero-sub">${sav && isNum(sav.est) && sav.est > 0
        ? `<b>Diverse rotations cut it.</b> If every county's rotation diversity rose to the region's top 10%, a 2022-style drought bill would shrink by <span class="green">${usdBig(sav.est)}</span>${isNum(sav.share) ? ` (${pct(sav.share)})` : ''}${isNum(sav.lo) ? `, range ${usdBig(sav.lo)}–${usdBig(sav.hi)}` : ''}.`
        : '<b>Diverse rotations cut it.</b> Move the slider on any county to see by how much.'}</p>
      <div class="tiles">
        <div class="tile"><div class="tile-k">2022 actual drought bill</div><div class="tile-v red">${usdBig(T.a2022.est)}</div><div class="tile-s">insured drought losses, all payers</div></div>
        <div class="tile"><div class="tile-k">Paid by taxpayers</div><div class="tile-v red">${usdBig(T.taxpayer.est)}</div><div class="tile-s">${isNum(pctTax) ? `${pct(pctTax)} of the expected bill, via premium subsidies` : 'via premium subsidies'}</div></div>
        <div class="tile"><div class="tile-k">By 2045 (NASA climate projections)</div><div class="tile-v">${isNum(T.ch245.est) ? `${T.ch245.est > 0 ? '+' : ''}${T.ch245.est.toFixed(0)}%` : NA}</div><div class="tile-s">moderate emissions${rangeTxt(T.ch245, (x) => `${x.toFixed(0)}%`) ? `, range ${rangeTxt(T.ch245, (x) => `${x.toFixed(0)}%`)}` : ''}${isNum(T.ch585.est) ? `; high: ${T.ch585.est > 0 ? '+' : ''}${T.ch585.est.toFixed(0)}%` : ''}</div></div>
      </div>
      <p class="nasa-line"><span class="nasa-badge">NASA</span> Built on ${nasa.length ? nasa.map(esc).join(' · ') : 'NASA Earth observations'}.</p>`;
  }

  // ----- map -----
  const host = document.getElementById('pub-map');
  let map = null;
  if (D.counties) {
    map = createMap(host, {
      counties: D.counties, states: D.states, label: 'Map of the expected drought bill per insured acre by county',
      onSelect: (f) => onSelect(f),
      tip: (f) => {
        const c = counties[f];
        const v = layerValue(c, state.layer, state.taxpayer);
        const name = c ? countyLabel(c, f) : (map.byFips.get(f)?.properties?.name || f);
        return `<b>${esc(name)}</b><br><span class="red big-tip">${usd(v.est)}</span> per insured acre/yr${rangeTxt(v) ? `<br><span class="muted">range ${rangeTxt(v)}</span>` : ''}<br><span class="muted">${esc(LAYERS[state.layer].long)}${state.taxpayer ? ', taxpayer share' : ''}</span>`;
      },
    });
  } else {
    host.innerHTML = '<p class="empty">County shapes (data/counties.geojson) are not available yet.</p>';
  }
  const all = (layers) => Object.values(counties).flatMap((c) => layers.map((l) => layerValue(c, l, false).est));
  const scales = {
    future: makeScale(all(['expected', 'ssp245', 'ssp585']), REDS),
    a2022: makeScale(all(['a2022']), REDS),
  };

  function renderMap() {
    const sc = state.layer === 'a2022' ? scales.a2022 : scales.future;
    if (map) {
      map.paint((f) => sc.scale(layerValue(counties[f], state.layer, state.taxpayer).est));
      map.select(state.fips);
    }
    const lab = (i) => (i === 0 ? `< ${usd(sc.breaks[0])}` : i === sc.breaks.length ? `≥ ${usd(sc.breaks[i - 1])}` : `${usd(sc.breaks[i - 1])}–${usd(sc.breaks[i])}`);
    document.getElementById('pub-legend').innerHTML = `
      <div class="legend-title">${state.taxpayer ? 'Taxpayer-funded ' : ''}${esc(LAYERS[state.layer].long)}<br><b>$ per insured acre per year</b></div>
      <div class="legend-scale">${sc.colors.map((col, i) => `<div class="lg-cell"><span class="lg-sw" style="background:${col}"></span><span class="lg-lab">${lab(i)}</span></div>`).join('')}
      <div class="lg-cell"><span class="lg-sw" style="background:${NODATA}"></span><span class="lg-lab">no data</span></div></div>`;
  }

  // ----- controls -----
  const seg = document.getElementById('layer-seg');
  seg.innerHTML = Object.entries(LAYERS).map(([k, l]) => `<button type="button" class="seg-btn" data-layer="${k}" aria-pressed="${k === state.layer}">${l.tab}</button>`).join('');
  seg.addEventListener('click', (e) => {
    const b = e.target.closest('[data-layer]');
    if (!b) return;
    state.layer = b.dataset.layer;
    seg.querySelectorAll('.seg-btn').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    renderMap(); renderCard();
  });
  const taxBox = document.getElementById('tax-toggle');
  taxBox.addEventListener('change', () => { state.taxpayer = taxBox.checked; renderHero(); renderMap(); renderCard(); });

  // ----- county card + slider -----
  let sliderVal = null;
  function renderCard() {
    const el = document.getElementById('pub-card');
    const c = counties[state.fips];
    if (!c) {
      const nm = map?.byFips.get(state.fips)?.properties;
      el.innerHTML = `<p class="eyebrow">County</p><h3>${esc(nm ? `${nm.name}, ${nm.state}` : 'Pick a county')}</h3><p class="muted">${nm ? 'No drought bill estimate for this county (too few insured acres or missing data).' : 'Tap a county on the map or search above.'}</p>`;
      return;
    }
    const v = layerValue(c, state.layer, state.taxpayer);
    const A = c.insured_acres;
    const exp = val(c.expected_bill), b5 = val(c.bill_1in5), b10 = val(c.bill_1in10), tx = layerValue(c, 'expected', true);
    const hc = c.hindcast?.['2022'] || {};
    const f245 = val(c.bill_2045?.ssp245), f585 = val(c.bill_2045?.ssp585);
    const dv = c.diversity || {};
    const row = (k, x, extra = '') => `<tr><th>${k}</th><td class="num">${typeof x === 'string' ? x : `<b>${usd(x.est)}</b>${rangeTxt(x) ? ` <span class="muted">${rangeTxt(x)}</span>` : ''}`}${extra}</td></tr>`;
    el.innerHTML = `
      <p class="eyebrow">${esc(STATE_NAMES[c.state] || c.state || '')}</p>
      <h3>${esc(countyLabel(c, state.fips))}</h3>
      <div class="card-big"><span class="red money">${usd(v.est)}</span><span class="unit">per insured acre / yr</span></div>
      <p class="card-range">${rangeTxt(v) ? `Range ${rangeTxt(v)}. ` : ''}${esc(LAYERS[state.layer].long)}${state.taxpayer ? ', taxpayer-funded share' : ''}.
        ${isNum(v.est) && isNum(A) ? `About <b class="red">${usdBig(v.est * A)}</b> across ${Math.round(A).toLocaleString('en-US')} insured acres.` : ''}</p>
      <table class="kv">
        ${row('Expected bill / yr', exp)}
        ${row('Bad year (1 in 5)', b5)}
        ${row('Very bad year (1 in 10)', b10)}
        ${row('Taxpayer share / yr', tx, isNum(c.subsidy_share) ? ` <span class="muted">(${pct(c.subsidy_share)} subsidy)</span>` : '')}
        ${row('2022 actual', val(pick(c.actual || {}, '2022')))}
        ${row('2022 predicted (data to 2020)', val(hc))}
        ${row('2045 moderate / high', `<b>${usd(f245.est)}</b> / <b>${usd(f585.est)}</b>`)}
        ${row('Rotation diversity now', `${num(dv.now)} <span class="muted">region top 10%: ${num(dv.p90_region)}</span>`)}
        ${row('Continuous corn share', pct(dv.share_cont_corn))}
        ${row('Irrigated share · soil water', `${pct(c.irrigated_share)} · ${isNum(c.aws_mm) ? `${Math.round(c.aws_mm)} mm` : NA}`)}
      </table>
      <div class="slider-block" id="slider-block"></div>`;
    renderSlider(c);
  }

  function renderSlider(c) {
    const box = document.getElementById('slider-block');
    const s = c.slider, d = c.diversity || {};
    if (!s || !Array.isArray(s.div_values) || s.div_values.filter(isNum).length < 2 || !isNum(d.now)) {
      box.innerHTML = '<h4>What if rotations diversified?</h4><p class="muted">No diversity scenario for this county.</p>';
      return;
    }
    const xs = s.div_values.filter(isNum);
    const min = Math.min(...xs), max = Math.max(...xs);
    if (sliderVal == null || sliderVal.fips !== state.fips) sliderVal = { fips: state.fips, x: Math.min(max, Math.max(min, isNum(d.p90_region) ? Math.max(d.p90_region, d.now) : max)) };
    box.innerHTML = `
      <h4>What if rotations diversified?</h4>
      <label class="sr-only" for="div-slider">Rotation diversity</label>
      <input type="range" id="div-slider" min="${min}" max="${max}" step="${((max - min) / 100).toFixed(4)}" value="${sliderVal.x}">
      <div class="slider-ends"><span>less diverse</span><span>more diverse</span></div>
      <p class="slider-sentence" id="slider-sentence" aria-live="polite"></p>
      <div id="div-chart" class="div-chart"></div>`;
    const input = document.getElementById('div-slider');
    const update = () => {
      const x = +input.value;
      sliderVal.x = x;
      const A = interp(xs, s.bill_2022_style, d.now), B = interp(xs, s.bill_2022_style, x);
      const Blo = interp(xs, s.lo, x), Bhi = interp(xs, s.hi, x);
      const fall = B <= A;
      const tot = isNum(A) && isNum(B) && isNum(c.insured_acres) ? (A - B) * c.insured_acres : null;
      document.getElementById('slider-sentence').innerHTML = `If rotation diversity here ${x >= d.now ? 'rose' : 'fell'} from <b>${num(d.now)}</b> to <b>${num(x)}</b>, a 2022-style drought bill would ${fall ? 'fall' : 'rise'} from <span class="red">${usd(A)}</span> to <span class="${fall ? 'green' : 'red'}">${usd(B)}</span> per acre${isNum(Blo) && isNum(Bhi) ? ` <span class="muted">(range ${usd(Math.min(Blo, Bhi))}–${usd(Math.max(Blo, Bhi))})</span>` : ''}${isNum(tot) && Math.abs(tot) >= 1 ? `: about <b class="${fall ? 'green' : 'red'}">${usdBig(Math.abs(tot))}</b> ${fall ? 'saved' : 'more'} across the county.` : '.'}`;
      diversityChart(document.getElementById('div-chart'), s, { now: d.now, sel: x, p90: d.p90_region, fmt: (y) => usd(y) });
    };
    input.addEventListener('input', update);
    update();
  }

  // ----- hindcast -----
  function renderHindcast() {
    const H = D.hindcast;
    const el = document.getElementById('hindcast-body');
    if (!H) { el.innerHTML = '<p class="empty">Hindcast results (hindcast.json) are not available yet.</p>'; return; }
    const by = H.by_year || {};
    const y22 = by['2022'] || by[2022];
    const tr = Array.isArray(H.train_years) ? H.train_years : [];
    const trainEnd = tr.length ? Math.max(...tr) : 2020;
    const lede = document.getElementById('hindcast-lede');
    if (y22) {
      lede.innerHTML = `Trained only on data through <b>${trainEnd}</b>, the model predicted a 2022 drought bill of <b>${usdBig(y22.pred_total_usd)}</b>${isNum(y22.lo) ? ` (range ${usdBig(y22.lo)}–${usdBig(y22.hi)})` : ''}. The actual bill was <b class="red">${usdBig(y22.actual_total_usd)}</b>.`;
    }
    const years = Object.keys(by).sort();
    const M = H.metrics || {};
    const mrow = (k, label) => {
      const m = M[k] || {};
      return `<tr${k === 'model' ? ' class="hl"' : ''}><th>${label}</th><td class="num">${num(m.mae, 1)}</td><td class="num">${num(m.rmse, 1)}</td><td class="num">${num(m.r2)}</td><td class="num">${num(m.spearman)}</td><td class="num">${isNum(m.total_bias_pct) ? `${m.total_bias_pct > 0 ? '+' : ''}${m.total_bias_pct.toFixed(0)}%` : NA}</td></tr>`;
    };
    const st = (H.by_state || []).filter((r) => r && (r.year == null || String(r.year) === '2022'));
    const pts = Object.entries(counties).map(([f, c]) => ({ x: c.hindcast?.['2022']?.pred, y: c.hindcast?.['2022']?.actual, label: countyLabel(c, f) })).filter((p) => isNum(p.x) && isNum(p.y));
    el.innerHTML = `
      <div class="hc-grid">
        <figure class="hc-fig"><figcaption><b>Region total by test year</b><span class="key"><i class="k-pred"></i>predicted (bar = range)<i class="k-act"></i>actual</span></figcaption><div id="hc-years"></div></figure>
        <figure class="hc-fig"><figcaption><b>2022 by state</b><span class="key"><i class="k-pred"></i>predicted<i class="k-act"></i>actual</span></figcaption><div id="hc-states"></div></figure>
        <figure class="hc-fig"><figcaption><b>2022 by county, $ per insured acre</b></figcaption><div id="hc-scatter"></div></figure>
        <div class="hc-fig">
          <p class="fig-cap"><b>Test-period accuracy vs simple baselines</b>${H.metrics_units ? ` <span class="muted">(${esc(H.metrics_units)})</span>` : ''}</p>
          <div class="table-wrap"><table class="metrics"><thead><tr><th></th><th>MAE</th><th>RMSE</th><th>R²</th><th>Rank corr.</th><th>Total bias</th></tr></thead>
          <tbody>${mrow('model', 'Drought Bill model')}${mrow('baseline_hazard_only', 'Weather only (no rotation)')}${mrow('baseline_mean', 'County average')}</tbody></table></div>
          <p class="small muted">Lower MAE/RMSE and higher R²/rank correlation are better. Test years ${esc((H.test_years || []).join(', ') || NA)}; trained ${esc(tr.length ? `${Math.min(...tr)}–${trainEnd}` : NA)}.</p>
        </div>
      </div>`;
    if (years.length) pairedBars(document.getElementById('hc-years'), years.map((y) => ({ label: y, pred: by[y].pred_total_usd, lo: by[y].lo, hi: by[y].hi, actual: by[y].actual_total_usd })), { fmt: usdBig, ariaLabel: 'Predicted versus actual drought bill by test year' });
    else document.getElementById('hc-years').innerHTML = '<p class="empty">n/a</p>';
    if (st.length) pairedBars(document.getElementById('hc-states'), st.map((r) => ({ label: r.state, pred: r.pred_total_usd, lo: r.lo, hi: r.hi, actual: r.actual_total_usd })), { fmt: usdBig, ariaLabel: '2022 predicted versus actual by state' });
    else document.getElementById('hc-states').innerHTML = '<p class="empty">n/a</p>';
    if (pts.length) scatter(document.getElementById('hc-scatter'), pts, { fmt: (x) => usd(x), xLabel: 'predicted from data through ' + trainEnd, yLabel: 'actual 2022' });
    else document.getElementById('hc-scatter').innerHTML = '<p class="empty">n/a</p>';
  }

  renderHero(); renderMap(); renderCard(); renderHindcast();
  return {
    setCounty() { renderMap(); renderCard(); },
  };
}
