// "GRACE from space" view: time series chart, gridded map, wells-vs-GRACE numbers.
import { esc, fmt, num, isNum, toSeries, NA, decYear, rangeText } from './util.js';

let D, chart = null, mapIdx = 0, mapLayer = 'gws_pct';

export function initGrace(data) { D = data; }

function pctColor(v) {
  if (!isNum(v)) return null;
  // diverging: 0 (driest on record) red -> 50 neutral -> 100 (wettest) blue
  const stops = [[0, [178, 24, 43]], [25, [239, 138, 98]], [50, [247, 247, 247]], [75, [103, 169, 207]], [100, [33, 102, 172]]];
  const x = Math.max(0, Math.min(100, v));
  for (let i = 1; i < stops.length; i++) {
    if (x <= stops[i][0]) {
      const [a, ca] = stops[i - 1], [b, cb] = stops[i], t = (x - a) / (b - a);
      return `rgb(${ca.map((c, k) => Math.round(c + (cb[k] - c) * t)).join(',')})`;
    }
  }
  return 'rgb(33,102,172)';
}
function trendColor(v) {
  if (!isNum(v)) return null;
  return pctColor(50 + Math.max(-50, Math.min(50, v * 25))); // +-2 cm/yr saturates
}

// Work out the map frames from several plausible shapes.
function mapFrames() {
  const m = D.grace?.maps;
  if (!m) return null;
  const bbox = m.bbox, cell = m.cell_deg;
  if (!Array.isArray(bbox) || !isNum(cell)) return null;
  const ncol = Math.round((bbox[2] - bbox[0]) / cell), nrow = Math.round((bbox[3] - bbox[1]) / cell);
  const asGrid = a => {
    if (!Array.isArray(a)) return null;
    if (Array.isArray(a[0])) return a; // rows x cols
    if (a.length === nrow * ncol) { const g = []; for (let r = 0; r < nrow; r++) g.push(a.slice(r * ncol, (r + 1) * ncol)); return g; }
    return null;
  };
  const southUp = Array.isArray(m.lats) && m.lats.length > 1 && m.lats[1] > m.lats[0] || m.row_order === 'south_up';
  const fix = g => (g && southUp ? [...g].reverse() : g);
  const frames = { gws_pct: [], tws_trend_cm_yr: null };
  const gp = m.gws_pct;
  if (Array.isArray(gp)) {
    const is3d = Array.isArray(gp[0]) && Array.isArray(gp[0][0]);
    const isFlatT = !is3d && Array.isArray(gp[0]) && gp[0].length === nrow * ncol && Array.isArray(m.dates) && gp.length === m.dates.length;
    if (is3d || isFlatT) gp.forEach((g, i) => frames.gws_pct.push({ date: m.dates?.[i] ?? `frame ${i + 1}`, grid: fix(asGrid(g)) }));
    else { const g = asGrid(gp); if (g) frames.gws_pct.push({ date: Array.isArray(m.dates) ? m.dates[m.dates.length - 1] : (m.date || ''), grid: fix(g) }); }
  }
  frames.gws_pct = frames.gws_pct.filter(f => f.grid);
  if (m.tws_trend_cm_yr) frames.tws_trend_cm_yr = fix(asGrid(m.tws_trend_cm_yr));
  return { bbox, cell, frames };
}

function drawMap(canvas, mf) {
  const ctx = canvas.getContext('2d');
  const [x0, y0, x1, y1] = mf.bbox;
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#f4f6f4'; ctx.fillRect(0, 0, W, H);
  const grid = mapLayer === 'tws_trend_cm_yr' ? mf.frames.tws_trend_cm_yr : mf.frames.gws_pct[mapIdx]?.grid;
  const colorFn = mapLayer === 'tws_trend_cm_yr' ? trendColor : pctColor;
  const px = lon => (lon - x0) / (x1 - x0) * W, py = lat => (y1 - lat) / (y1 - y0) * H;
  if (grid) {
    const nr = grid.length, cw = W / (grid[0]?.length || 1), ch = H / nr;
    grid.forEach((row, r) => row.forEach((v, c) => { const col = colorFn(v); if (col) { ctx.fillStyle = col; ctx.fillRect(c * cw, r * ch, cw + 0.5, ch + 0.5); } }));
  }
  // County outlines for orientation
  ctx.strokeStyle = 'rgba(20,32,28,.55)'; ctx.lineWidth = 0.8;
  for (const f of D.counties?.features || []) {
    const g = f.geometry; if (!g) continue;
    const polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
    for (const poly of polys) for (const ring of poly) {
      ctx.beginPath(); ring.forEach(([lon, lat], i) => (i ? ctx.lineTo(px(lon), py(lat)) : ctx.moveTo(px(lon), py(lat)))); ctx.stroke();
    }
  }
}

function legend() {
  if (mapLayer === 'tws_trend_cm_yr') return `<div class="glg"><span>losing 2+ cm/yr</span><span class="bar trend"></span><span>gaining</span></div>`;
  return `<div class="glg"><span>0 = driest on record</span><span class="bar"></span><span>100 = wettest</span></div>`;
}

function seriesChart(canvas) {
  if (!window.Chart) { canvas.replaceWith(Object.assign(document.createElement('p'), { textContent: 'Chart library could not load.' })); return; }
  const s = D.grace?.series || {};
  const gws = toSeries({ dates: s.dates, v: s.gws_pct }, ['v']);
  const tws = Array.isArray(s.tws_cm) ? toSeries({ dates: s.dates, v: s.tws_cm }, ['v']) : [];
  const wells = toSeries(D.grace?.wells_vs_grace?.well_storage_anom_series);
  const ds = [];
  if (gws.length) ds.push({ label: 'GRACE groundwater percentile (left axis)', data: gws, yAxisID: 'y', borderColor: '#1f6f8b', backgroundColor: 'rgba(31,111,139,.12)', fill: 'origin', borderWidth: 1.5, pointRadius: 0, tension: 0.2 });
  if (tws.length) ds.push({ label: 'GRACE total water storage anomaly, cm (right axis)', data: tws, yAxisID: 'y2', borderColor: '#b2182b', borderWidth: 1.5, pointRadius: 0 });
  if (wells.length) ds.push({ label: 'Wells: storage anomaly, cm (right axis)', data: wells, yAxisID: 'y2', borderColor: '#4a4a4a', borderDash: [5, 3], borderWidth: 2, pointRadius: 2 });
  if (!ds.length) { canvas.replaceWith(Object.assign(document.createElement('p'), { innerHTML: NA + ': grace.json has no series.' })); return; }
  chart?.destroy();
  chart = new Chart(canvas, {
    type: 'line', data: { datasets: ds },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, parsing: false, normalized: true,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 14, font: { size: 11 } } },
        tooltip: { callbacks: { title: items => { const x = items[0].parsed.x; const y = Math.floor(x); const m = Math.floor((x - y) * 12) + 1; return `${y}-${String(m).padStart(2, '0')}`; } } } },
      scales: {
        x: { type: 'linear', ticks: { callback: v => (Number.isInteger(v) ? String(v) : ''), maxTicksLimit: 10 }, grid: { color: '#eef0ee' } },
        y: { display: gws.length > 0, min: 0, max: 100, title: { display: true, text: 'percentile' }, grid: { color: '#eef0ee' } },
        y2: { display: tws.length + wells.length > 0, position: 'right', title: { display: true, text: 'cm of water' }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

function wellsVsGrace() {
  const w = D.grace?.wells_vs_grace;
  const v = D.validation?.grace_vs_wells;
  const src = w || v;
  if (!src) return `<p>${NA}</p>`;
  const r = num(src.correlation);
  return `<dl class="facts big-facts">
    <div><dt>Correlation, wells vs GRACE</dt><dd>${isNum(r) ? fmt(r, 2) : NA}</dd></div>
    <div><dt>Trend from wells</dt><dd>${isNum(num(src.trend_wells_cm_yr)) ? rangeText(src.trend_wells_cm_yr, x => fmt(x, 2), 'cm/yr') : NA}</dd></div>
    <div><dt>Trend from GRACE</dt><dd>${isNum(num(src.trend_grace_cm_yr)) ? rangeText(src.trend_grace_cm_yr, x => fmt(x, 2), 'cm/yr') : NA}</dd></div>
  </dl>
  ${src.notes ? `<p class="fine">${esc(src.notes)}</p>` : ''}`;
}

export function renderGrace() {
  const root = document.getElementById('grace-panel');
  const mf = mapFrames();
  const hasTrend = !!mf?.frames.tws_trend_cm_yr;
  const nFrames = mf?.frames.gws_pct.length || 0;
  if (!nFrames && hasTrend) mapLayer = 'tws_trend_cm_yr';
  mapIdx = Math.min(mapIdx || Math.max(0, nFrames - 1), Math.max(0, nFrames - 1));
  root.innerHTML = `
    <section class="card wide">
      <h2>The water clock, seen from space</h2>
      <p class="ck-sub">NASA's GRACE and GRACE-FO satellites weigh the water in and under the ground by measuring tiny changes in Earth's gravity.
      The groundwater percentile compares each week with the same time of year since 2002 (0 = driest on record, 100 = wettest).</p>
      <div class="chart-box"><canvas id="grace-chart" aria-label="GRACE groundwater over time" role="img"></canvas></div>
    </section>
    <div class="two-col">
      <section class="card">
        <h3>GRACE groundwater map</h3>
        ${mf && (nFrames || hasTrend) ? `
          ${hasTrend && nFrames ? `<div class="thr-btns" role="group" aria-label="Map layer">
            <button type="button" class="chip" data-gl="gws_pct" aria-pressed="${mapLayer === 'gws_pct'}">Percentile</button>
            <button type="button" class="chip" data-gl="tws_trend_cm_yr" aria-pressed="${mapLayer === 'tws_trend_cm_yr'}">Storage trend</button></div>` : ''}
          <canvas id="grace-map" width="360" height="${Math.round(360 * (mf.bbox[3] - mf.bbox[1]) / (mf.bbox[2] - mf.bbox[0]) * 1.27)}" role="img" aria-label="Map of GRACE groundwater"></canvas>
          ${legend()}
          ${mapLayer === 'gws_pct' && nFrames > 1 ? `<label class="picker">Date: <b id="gm-date">${esc(mf.frames.gws_pct[mapIdx].date)}</b>
            <input id="gm-idx" type="range" min="0" max="${nFrames - 1}" value="${mapIdx}"></label>` : (nFrames ? `<p class="fine">Date: ${esc(mf.frames.gws_pct[mapIdx]?.date || '')}</p>` : '')}
          <p class="fine">Grid cells ${fmt(mf.cell, 3)}&deg;; county outlines for orientation.</p>` : `<p>${NA}: grace.json has no maps.</p>`}
      </section>
      <section class="card">
        <h3>Do the wells agree with the satellites?</h3>
        ${wellsVsGrace()}
        <p class="fine">Well storage = water-level change &times; specific yield, averaged over the region. GRACE senses all water (soil, groundwater, reservoirs) over large areas (~300 km), so agreement in trend and timing, not exact values, is the test.</p>
      </section>
    </div>`;
  seriesChart(document.getElementById('grace-chart'));
  const cv = document.getElementById('grace-map');
  if (cv && mf) {
    // width from container at render time (keeps phones sharp, no overflow)
    const w = Math.min(360, cv.parentElement.clientWidth - 4);
    if (w > 100) { const h = Math.round(cv.height * w / cv.width); cv.width = w; cv.height = h; }
    drawMap(cv, mf);
  }
  root.querySelector('#gm-idx')?.addEventListener('input', e => { mapIdx = +e.target.value; document.getElementById('gm-date').textContent = mf.frames.gws_pct[mapIdx].date; drawMap(cv, mf); });
  root.querySelectorAll('[data-gl]').forEach(b => b.addEventListener('click', () => { mapLayer = b.dataset.gl; renderGrace(); }));
}

export function graceSummary() {
  const s = D?.grace?.series;
  if (!s?.dates?.length || !Array.isArray(s.gws_pct)) return null;
  const last = s.gws_pct.length - 1;
  return { date: s.dates[last], pct: s.gws_pct[last], x: decYear(s.dates[last]) };
}
