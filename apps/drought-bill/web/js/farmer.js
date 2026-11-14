// Farmer view: county + rotation (or a sample field in Plymouth County, IA) -> your drought bill and strategy cards.
import { val, usd, usdBig, rangeTxt, esc, isNum, NA, showTip, hideTip, pick } from './util.js';
import { createMap, makeScale } from './map.js';
import { REDS, countyLabel } from './public.js';

const d3 = window.d3;
export const ROTATIONS = [
  { id: 'corn-soy', label: 'Corn-soybean' },
  { id: 'continuous corn', label: 'Continuous corn' },
  { id: '3+ crop', label: '3 or more crops' },
  { id: 'with perennial', label: 'With alfalfa, hay or grass' },
];
// categorical dot colours for rotation classes (validated palette slots, plus a text legend)
const ROT_COL = { 'corn-soy': '#2a78d6', 'continuous corn': '#eb6834', '3+ crop': '#1baf7a', 'with perennial': '#6250d6' };
const CROP = {
  C: ['Corn', '#f2c230', '#111'], S: ['Soybeans', '#2e8b3e', '#fff'], W: ['Wheat', '#b5835a', '#fff'], O: ['Oats / other small grain', '#d9b38c', '#111'],
  A: ['Alfalfa / hay', '#7b4fa8', '#fff'], G: ['Sorghum', '#c4572b', '#fff'], P: ['Pasture / grass', '#8fbf7a', '#111'], X: ['Other / not cropped', '#bdbdbd', '#111'],
};
const GRADE = { strong: ['●●●', 'Strong evidence'], moderate: ['●●○', 'Moderate evidence'], thin: ['●○○', 'Thin evidence'] };

export function initFarmer(D, state, onSelect) {
  const counties = D.bill?.counties || {};
  const S = D.strategies || {};
  const stratMeta = new Map((S.strategies || []).map((s) => [s.id, s]));
  const F = D.fields;
  let fieldsMap = null;
  let stratDraw = null;
  window.addEventListener('resize', () => stratDraw && stratDraw(), { passive: true });

  // ----- mode tabs -----
  const modeBtns = document.querySelectorAll('[data-fmode]');
  modeBtns.forEach((b) => b.addEventListener('click', () => {
    state.fmode = b.dataset.fmode;
    modeBtns.forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    document.getElementById('fm-county').hidden = state.fmode !== 'county';
    document.getElementById('fm-field').hidden = state.fmode !== 'field';
    if (state.fmode === 'field') { drawFields(); if (state.field) { state.fips = F?.county?.fips || '19149'; onSelect(state.fips); } }
    renderResults();
  }));

  // ----- rotation chips -----
  const rotBox = document.getElementById('rot-chips');
  rotBox.innerHTML = ROTATIONS.map((r) => `<button type="button" class="chip" data-rot="${esc(r.id)}" aria-pressed="${r.id === state.rotation}">${esc(r.label)}</button>`).join('');
  rotBox.addEventListener('click', (e) => {
    const b = e.target.closest('[data-rot]');
    if (!b) return;
    state.rotation = b.dataset.rot;
    rotBox.querySelectorAll('.chip').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    renderResults();
  });

  // ----- small county map -----
  let cmap = null;
  if (D.counties) {
    cmap = createMap(document.getElementById('farm-map'), {
      counties: D.counties, states: D.states, width: 640, label: 'Pick your county on the map',
      onSelect: (f) => onSelect(f),
      tip: (f) => `<b>${esc(counties[f] ? countyLabel(counties[f], f) : (cmap.byFips.get(f)?.properties?.name || f))}</b><br>${usd(val(counties[f]?.expected_bill).est)} expected / acre / yr`,
    });
    const sc = makeScale(Object.values(counties).map((c) => val(c.expected_bill).est), REDS);
    cmap.paint((f) => sc.scale(val(counties[f]?.expected_bill).est));
  }

  // ----- sample fields -----
  function drawFields() {
    const host = document.getElementById('field-map');
    if (fieldsMap || !host) return;
    if (!F || !Array.isArray(F.fields) || !F.fields.length) { host.innerHTML = '<p class="empty">Sample fields (focus_fields.json) are not available yet.</p>'; return; }
    const fips = String(F.county?.fips || '19149');
    const poly = D.counties?.features.find((f) => String(f.properties.fips) === fips);
    const pts = { type: 'FeatureCollection', features: F.fields.filter((f) => isNum(f.lon) && isNum(f.lat)).map((f) => ({ type: 'Feature', properties: f, geometry: { type: 'Point', coordinates: [f.lon, f.lat] } })) };
    const W = 420, H = 360;
    const proj = d3.geoConicEqualArea().parallels([37, 45]).rotate([96, 0]).fitExtent([[10, 10], [W - 10, H - 10]], poly || pts);
    const path = d3.geoPath(proj);
    host.innerHTML = '';
    const svg = d3.select(host).append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('class', 'map-svg').attr('role', 'img')
      .attr('aria-label', `Sample fields in ${F.county?.name || 'the focus'} county coloured by rotation`);
    if (poly) svg.append('path').attr('d', path(poly)).attr('class', 'field-county');
    const dots = svg.append('g').selectAll('circle').data(pts.features).join('circle')
      .attr('cx', (f) => proj(f.geometry.coordinates)[0]).attr('cy', (f) => proj(f.geometry.coordinates)[1])
      .attr('r', 4.5).attr('fill', (f) => ROT_COL[f.properties.rotation_class] || '#8a8f98').attr('class', 'fdot')
      .on('pointermove', (ev, f) => { if (ev.pointerType === 'mouse') showTip(`<b>Field ${esc(f.properties.id)}</b><br>${esc(f.properties.rotation_class || NA)}<br><span class="mono">${esc(f.properties.seq || '')}</span>`, ev); })
      .on('pointerleave', hideTip)
      .on('click', (ev, f) => { hideTip(); pickField(f.properties); });
    fieldsMap = { dots };
    document.getElementById('field-legend').innerHTML = Object.entries(ROT_COL).map(([k, c]) => `<span class="lg-item"><i style="background:${c}"></i>${esc(k)}</span>`).join('');
    if (!state.field) pickField(F.fields.find((f) => f.rotation_class === 'corn-soy') || F.fields[0]);
  }

  function pickField(f) {
    state.field = f;
    state.rotation = f.rotation_class;
    rotBox.querySelectorAll('.chip').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.rot === state.rotation)));
    fieldsMap?.dots.classed('on', (d) => d.properties.id === f.id);
    const years = F.years || [];
    const seq = String(f.seq || '');
    document.getElementById('field-strip').innerHTML = `
      <p class="fig-cap"><b>Field ${esc(f.id)}</b>: ${esc(f.rotation_class || NA)}${isNum(f.ncrop5) ? ` · ${f.ncrop5} crops in 2020–24` : ''}${isNum(f.div5) ? ` · diversity ${f.div5.toFixed(2)}` : ''} <span class="muted">(Cropland Data Layer)</span></p>
      <div class="strip" role="list">${[...seq].map((ch, i) => { const c = CROP[ch] || CROP.X; return `<div class="strip-cell" role="listitem" style="background:${c[1]};color:${c[2]}" title="${years[i] ?? ''}: ${esc(c[0])}"><b>${esc(ch)}</b><span>${String(years[i] ?? '').slice(2)}</span></div>`; }).join('')}</div>
      <p class="strip-key">${Object.entries(CROP).filter(([k]) => seq.includes(k)).map(([k, c]) => `<span><b>${k}</b> ${esc(c[0])}</span>`).join('')}</p>`;
    const fips = String(F.county?.fips || '19149');
    if (state.fips !== fips) onSelect(fips); else renderResults();
  }

  // ----- results -----
  function renderResults() {
    const el = document.getElementById('farm-results');
    const c = counties[state.fips];
    const rows = S.counties?.[state.fips]?.[state.rotation];
    const rotLabel = ROTATIONS.find((r) => r.id === state.rotation)?.label || state.rotation;
    if (cmap) cmap.select(state.fips);
    const where = c ? countyLabel(c, state.fips) : (cmap?.byFips.get(state.fips)?.properties?.name || 'your county');
    document.getElementById('farm-where').textContent = `${where} · ${rotLabel}`;
    const cur = rows?.find((r) => r.strategy_id === 'current') || rows?.[0];
    const own = !!cur;
    const exp = own ? val(cur.expected_bill) : val(c?.expected_bill);
    const b5 = own && cur.bill_1in5 ? val(cur.bill_1in5) : val(c?.bill_1in5);
    const b10 = own ? val(cur.bill_1in10) : val(c?.bill_1in10);
    const fromCounty = !own || !cur.bill_1in5;
    const bill = (v, k, sub) => `<div class="bill"><div class="bill-k">${k}</div><div class="bill-v red">${usd(v.est)}<small>/acre</small></div><div class="bill-r">${rangeTxt(v) ? `range ${rangeTxt(v)}` : 'range n/a'}${sub ? ` · ${sub}` : ''}</div></div>`;
    el.innerHTML = `
      <div class="your-bill">
        <p class="eyebrow">Your drought bill</p>
        <div class="yb-main"><span class="red money">${usd(exp.est)}</span><span class="unit">per acre per year, expected</span></div>
        <p class="muted small">${rangeTxt(exp) ? `Likely range ${rangeTxt(exp)}. ` : ''}${own ? `For a ${esc(rotLabel.toLowerCase())} rotation in ${esc(where)}.` : `County average for all rotations in ${esc(where)}: no rotation-specific estimate here yet.`} This is the crop-insurance drought payout an average insured acre draws per year; your own loss can be larger than what insurance pays.</p>
        <div class="bills">
          ${bill(b5, 'Bad year (1 in 5)', fromCounty ? 'county average' : '')}
          ${bill(b10, 'Very bad year (1 in 10)', !own ? 'county average' : '')}
        </div>
      </div>
      <p class="decision-note"><b>Decision support, not a replacement for your agronomist or crop-insurance agent.</b> Numbers are averages for similar insured acres, with ranges. Check them against your own records.</p>
      ${rows && rows.length ? `
        <h3 class="cards-h">Compare ${rows.length} strategies</h3>
        <div id="strat-chart" class="strat-chart"></div>
        <div class="cards">${rows.map((r) => card(r, cur)).join('')}</div>`
      : `<p class="empty">Strategy comparisons are not available for ${esc(where)} with a ${esc(rotLabel.toLowerCase())} rotation yet.${S.counties?.[state.fips] ? ` Available here: ${Object.keys(S.counties[state.fips]).map(esc).join(', ')}.` : ' Try Plymouth County, IA.'}</p>`}`;
    if (rows && rows.length) stratChart(document.getElementById('strat-chart'), rows);
  }

  function delta(v, { good = 'neg', unit = '/ac' } = {}) {
    if (!isNum(v.est)) return `<span class="muted">${NA}</span>`;
    const better = good === 'neg' ? v.est < 0 : v.est > 0;
    const cls = Math.abs(v.est) < 0.5 ? '' : better ? 'green' : 'red';
    return `<b class="${cls}">${usd(v.est, { sign: true })}${unit}</b>${rangeTxt(v) ? ` <span class="muted">(${usd(v.lo, { sign: true })} to ${usd(v.hi, { sign: true })})</span>` : ''}`;
  }

  function card(r, cur) {
    const m = stratMeta.get(r.strategy_id) || {};
    const isCur = r.strategy_id === 'current';
    const g = GRADE[r.evidence?.grade] || ['○○○', r.evidence?.grade ? `${r.evidence.grade} evidence` : 'Evidence n/a'];
    const tail = r.delta_bill_1in10 ? val(r.delta_bill_1in10)
      : (isNum(val(r.bill_1in10).est) && isNum(val(cur?.bill_1in10).est) ? { est: val(r.bill_1in10).est - val(cur.bill_1in10).est, lo: null, hi: null } : val(null));
    const list = (arr) => (Array.isArray(arr) && arr.length ? `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : `<p class="muted">${NA}</p>`);
    const srcs = r.evidence?.sources || [];
    return `
      <article class="card${isCur ? ' current' : ''}">
        <header>
          <p class="eyebrow">${isCur ? 'Your current rotation' : esc(m.short || 'Option')}</p>
          <h4 class="card-h">${esc(m.name || r.strategy_id)}</h4>
          <span class="grade grade-${esc(r.evidence?.grade || 'na')}" title="${esc(g[1])}"><span aria-hidden="true">${g[0]}</span> ${esc(g[1])}</span>
        </header>
        <div class="card-bill"><span class="red">${usd(val(r.expected_bill).est)}</span><small>/acre/yr expected drought bill</small>${rangeTxt(val(r.expected_bill)) ? `<span class="muted small">range ${rangeTxt(val(r.expected_bill))}</span>` : ''}</div>
        ${isCur ? '<p class="small muted">The baseline the other options are compared with.</p>' : `
        <table class="kv small">
          <tr><th>Expected bill</th><td>${delta(val(r.delta_bill))}</td></tr>
          <tr><th>1-in-10 bad year</th><td>${delta(tail)}</td></tr>
          <tr><th>Average income</th><td>${delta(val(r.delta_income_per_ac), { good: 'pos' })}</td></tr>
        </table>`}
        ${r.why || m.description ? `<p class="why"><b>Why:</b> ${esc(r.why || m.description)}</p>` : ''}
        <details open><summary>Benefits</summary>${list(r.benefits)}</details>
        <details><summary>Information gaps</summary>${list(r.gaps)}</details>
        <details><summary>Risks needing local review</summary>${list(r.risks)}</details>
        ${srcs.length ? `<p class="small muted src">Evidence: ${srcs.map((s) => (/^https?:/.test(s) ? `<a href="${esc(s)}" target="_blank" rel="noopener">${esc(s.replace(/^https?:\/\//, '').slice(0, 40))}</a>` : esc(s))).join('; ')}</p>` : ''}
      </article>`;
  }

  function stratChart(host, rows) {
    const draw = () => {
      host.innerHTML = '';
      const W = Math.max(280, host.clientWidth || 500), rowH = 30, m = { t: 6, r: 56, b: 22, l: Math.min(170, W * 0.38) };
      const H = m.t + m.b + rows.length * rowH;
      const svg = d3.select(host).append('svg').attr('width', W).attr('height', H).attr('role', 'img').attr('aria-label', 'Expected drought bill per strategy with ranges');
      const g = svg.append('g').attr('transform', `translate(${m.l},${m.t})`);
      const iw = W - m.l - m.r;
      const vs = rows.map((r) => val(r.expected_bill));
      const x = d3.scaleLinear().domain([0, d3.max(vs, (v) => (isNum(v.hi) ? v.hi : v.est)) || 1]).nice().range([0, iw]);
      const y = d3.scaleBand().domain(rows.map((r) => r.strategy_id)).range([0, rows.length * rowH]).padding(0.3);
      g.append('g').attr('class', 'axis').attr('transform', `translate(0,${rows.length * rowH})`).call(d3.axisBottom(x).ticks(4).tickFormat((t) => usd(t)).tickSize(0)).call((a) => a.select('.domain').attr('stroke', '#6b6f76'));
      rows.forEach((r, i) => {
        const v = vs[i], yy = y(r.strategy_id);
        const name = stratMeta.get(r.strategy_id)?.short || stratMeta.get(r.strategy_id)?.name || r.strategy_id;
        g.append('text').attr('x', -8).attr('y', yy + y.bandwidth() / 2).attr('dy', '0.35em').attr('text-anchor', 'end').attr('class', 'chart-cat').text(name);
        if (!isNum(v.est)) return;
        g.append('rect').attr('x', 0).attr('y', yy).attr('height', y.bandwidth()).attr('width', x(v.est)).attr('rx', 2)
          .attr('fill', r.strategy_id === 'current' ? '#3d4a5c' : '#c1121f');
        if (isNum(v.lo) && isNum(v.hi)) {
          const cy = yy + y.bandwidth() / 2;
          g.append('path').attr('d', `M${x(v.lo)},${cy}H${x(v.hi)}M${x(v.lo)},${cy - 5}V${cy + 5}M${x(v.hi)},${cy - 5}V${cy + 5}`).attr('stroke', '#111').attr('stroke-width', 1.4);
        }
        g.append('text').attr('x', x(isNum(v.hi) ? Math.max(v.hi, v.est) : v.est) + 6).attr('y', yy + y.bandwidth() / 2).attr('dy', '0.35em').attr('class', 'chart-val').text(usd(v.est));
      });
    };
    stratDraw = () => host.isConnected && draw();
    draw();
  }

  return {
    setCounty() { renderResults(); },
    show() { if (state.fmode === 'field') drawFields(); renderResults(); },
  };
}
