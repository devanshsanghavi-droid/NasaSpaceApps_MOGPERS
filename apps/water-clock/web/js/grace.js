// "GRACE from space" view: time series chart, gridded map, wells-vs-GRACE numbers.
import { esc, fmt, num, isNum, toSeries, NA, decYear, rangeText } from './util.js';

let D, chart = null, mapIdx = 0, mapLayer = 'gws_pct', trendPeriod = null;

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
  const frames = { gws_pct: [], tws_trend_cm_yr: null, trendPeriods: [] };
  const gp = m.gws_pct;
  if (Array.isArray(gp)) {
    const is3d = Array.isArray(gp[0]) && Array.isArray(gp[0][0]);
    const isFlatT = !is3d && Array.isArray(gp[0]) && gp[0].length === nrow * ncol && Array.isArray(m.dates) && gp.length === m.dates.length;
    if (is3d || isFlatT) gp.forEach((g, i) => frames.gws_pct.push({ date: m.dates?.[i] ?? `frame ${i + 1}`, grid: fix(asGrid(g)) }));
    else { const g = asGrid(gp); if (g) frames.gws_pct.push({ date: Array.isArray(m.dates) ? m.dates[m.dates.length - 1] : (m.date || ''), grid: fix(g) }); }
  }
  frames.gws_pct = frames.gws_pct.filter(f => f.grid);
  const tt = m.tws_trend_cm_yr;
  if (Array.isArray(tt)) {
    const g = fix(asGrid(tt));
    if (g) frames.tws_trend_cm_yr = { '': { grid: g, bbox, cell } };
  } else if (tt && typeof tt === 'object') {
    // own grid: {cell_deg, lat, lon, bbox, <period>: rows x cols, ...}
    const tb = Array.isArray(tt.bbox) ? tt.bbox : bbox, tc = isNum(tt.cell_deg) ? tt.cell_deg : cell;
    const tSouthUp = Array.isArray(tt.lat) && tt.lat.length > 1 && tt.lat[1] > tt.lat[0];
    const out = {};
    for (const [k, v] of Object.entries(tt)) {
      if (['cell_deg', 'lat', 'lon', 'bbox'].includes(k) || !Array.isArray(v) || !Array.isArray(v[0])) continue;
      out[k] = { grid: tSouthUp ? [...v].reverse() : v, bbox: tb, cell: tc };
    }
    if (Object.keys(out).length) frames.tws_trend_cm_yr = out;
  }
  frames.trendPeriods = frames.tws_trend_cm_yr ? Object.keys(frames.tws_trend_cm_yr) : [];
  return { bbox, cell, frames };
}

function drawMap(canvas, mf) {
  const ctx = canvas.getContext('2d');
  const [x0, y0, x1, y1] = mf.bbox;
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#f4f6f4'; ctx.fillRect(0, 0, W, H);
  const isTrend = mapLayer === 'tws_trend_cm_yr';
  const layer = isTrend ? mf.frames.tws_trend_cm_yr?.[trendPeriod]
    : (mf.frames.gws_pct[mapIdx] ? { grid: mf.frames.gws_pct[mapIdx].grid, bbox: mf.bbox, cell: mf.cell } : null);
  const colorFn = isTrend ? trendColor : pctColor;
  const px = lon => (lon - x0) / (x1 - x0) * W, py = lat => (y1 - lat) / (y1 - y0) * H;
  if (layer?.grid) {
    // each cell placed by its own lon/lat (row 0 = north edge of the layer's bbox)
    const [gx0, , , gy1] = layer.bbox, cd = layer.cell;
    layer.grid.forEach((row, r) => row.forEach((v, c) => {
      const col = colorFn(v); if (!col) return;
      const lx = px(gx0 + c * cd), rx = px(gx0 + (c + 1) * cd), ty = py(gy1 - r * cd), by = py(gy1 - (r + 1) * cd);
      ctx.fillStyle = col; ctx.fillRect(lx, ty, rx - lx + 0.5, by - ty + 0.5);
    }));
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
  return `<div class="glg"><span>0 = driest</span><span class="bar"></span><span>100 = wettest (vs 1948-2012)</span></div>`;
}

function seriesChart(canvas) {
  if (!window.Chart) { canvas.replaceWith(Object.assign(document.createElement('p'), { textContent: 'Chart library could not load.' })); return; }
  const s = D.grace?.series || {};
  const gws = toSeries({ dates: s.dates, v: s.gws_pct }, ['v']);
  // cm series have different zero baselines in the source files; set each to zero on its own
  // average over the common years so only trend and timing are compared.
  const Y0 = 2003, Y1 = 2027;
  const center = pts => {
    const inWin = pts.filter(p => p.x >= Y0 && p.x < Y1);
    if (!inWin.length) return pts;
    const m = inWin.reduce((a, p) => a + p.y, 0) / inWin.length;
    return pts.map(p => ({ x: p.x, y: p.y - m }));
  };
  const tws = Array.isArray(s.tws_cm) ? center(toSeries({ dates: s.dates, v: s.tws_cm }, ['v'])) : [];
  const g3p = Array.isArray(s.g3p_gws_cm) ? center(toSeries({ dates: s.dates, v: s.g3p_gws_cm }, ['v'])) : [];
  const wells = center(toSeries(D.grace?.wells_vs_grace?.well_storage_anom_series));
  const ds = [];
  if (gws.length) ds.push({ label: 'GRACE groundwater percentile (left axis)', data: gws, yAxisID: 'y', borderColor: '#1f6f8b', backgroundColor: 'rgba(31,111,139,.12)', fill: 'origin', borderWidth: 1.5, pointRadius: 0, tension: 0.2 });
  if (tws.length) ds.push({ label: 'GRACE total water storage anomaly, cm (right axis)', data: tws, yAxisID: 'y2', borderColor: '#b2182b', borderWidth: 1.5, pointRadius: 0 });
  if (g3p.length) ds.push({ label: 'GRACE groundwater (G3P), cm (right axis)', data: g3p, yAxisID: 'y2', borderColor: '#7b3294', borderWidth: 1.5, pointRadius: 0 });
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
        y2: { display: tws.length + wells.length + g3p.length > 0, position: 'right', title: { display: true, text: 'cm of water' }, grid: { drawOnChartArea: false } },
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
  const rd = num(w?.correlation_detail?.gfz_tws_cm?.r_first_difference ?? v?.correlation_first_difference);
  const tw = num(src.trend_wells_cm_yr), tg = num(src.trend_grace_cm_yr);
  return `<dl class="facts big-facts">
    <div><dt>Timing agrees: correlation of yearly levels</dt><dd>${isNum(r) ? 'r = ' + fmt(r, 2) : NA}</dd></div>
    <div><dt>Correlation of year-to-year changes</dt><dd>${isNum(rd) ? 'r = ' + fmt(rd, 2) : NA}</dd></div>
    <div><dt>Size differs: trend from wells</dt><dd>${isNum(tw) ? rangeText(src.trend_wells_cm_yr, x => fmt(x, 2), 'cm/yr') : NA}</dd></div>
    <div><dt>Trend from GRACE</dt><dd>${isNum(tg) ? rangeText(src.trend_grace_cm_yr, x => fmt(x, 2), 'cm/yr') : NA}${isNum(tw) && isNum(tg) && tg < 0 ? ` <span class="rng">(wells about ${fmt(tw / tg, 0)}&times; GRACE)</span>` : ''}</dd></div>
  </dl>
  <p class="plain">The wells and GRACE share the long-term fall and the drought dips, but the wells show a much bigger storage loss. GRACE is used to check timing and direction, not to set the size of the clock.</p>
  ${src.notes ? `<details><summary>Full explanation</summary><p class="fine">${esc(src.notes)}</p></details>` : ''}`;
}

// Headline numbers from the series: GRACE/GRACE-FO storage drop since 2003 (independent of the
// file's zero point) and the latest GRACE-DA groundwater percentile.
function graceHeadline() {
  const s = D.grace?.series;
  if (!s?.dates?.length) return '';
  const yearMean = (arr, y) => {
    const v = s.dates.map((d, i) => [d, arr[i]]).filter(([d, x]) => String(d).startsWith(String(y)) && isNum(x)).map(([, x]) => x);
    return v.length ? { m: v.reduce((a, b) => a + b, 0) / v.length, n: v.length } : null;
  };
  const out = [];
  if (Array.isArray(s.tws_cm)) {
    const lastY = Number(String(s.dates[s.dates.length - 1]).slice(0, 4));
    const a = yearMean(s.tws_cm, 2003), b = yearMean(s.tws_cm, lastY);
    if (a && b) out.push(`<div class="hl-g"><span class="v">${fmt(a.m - b.m, 0)} cm</span><span class="l">less water stored over the region in ${lastY}${b.n < 12 ? ` (months available, n = ${b.n})` : ''} than in 2003 (GRACE/GRACE-FO total water storage)</span></div>`);
  }
  if (Array.isArray(s.gws_pct)) {
    let i = s.gws_pct.length - 1;
    while (i > 0 && !isNum(s.gws_pct[i])) i--;
    if (isNum(s.gws_pct[i])) out.push(`<div class="hl-g"><span class="v">${fmt(s.gws_pct[i], 1)}</span><span class="l">GRACE-DA groundwater percentile, ${esc(String(s.dates[i]).slice(0, 7))}: drier than about ${fmt(100 - s.gws_pct[i], 0)}% of the same time of year in 1948-2012 (a drought index, not a volume)</span></div>`);
  }
  return out.length ? `<div class="grace-hl">${out.join('')}</div>` : '';
}

export function renderGrace() {
  const root = document.getElementById('grace-panel');
  const mf = mapFrames();
  const hasTrend = !!mf?.frames.tws_trend_cm_yr;
  const periods = mf?.frames.trendPeriods || [];
  if (!periods.includes(trendPeriod)) trendPeriod = periods.includes('2003_latest') ? '2003_latest' : periods[0] ?? null;
  const periodLabel = k => (k === '2003_latest' ? '2003 to latest' : k === '2003_2016' ? '2003 to 2016 (GRACE)' : k.replace(/_/g, ' to '));
  const nFrames = mf?.frames.gws_pct.length || 0;
  if (!nFrames && hasTrend) mapLayer = 'tws_trend_cm_yr';
  mapIdx = Math.min(mapIdx || Math.max(0, nFrames - 1), Math.max(0, nFrames - 1));
  root.innerHTML = `
    <section class="card wide">
      <h2>The water clock, seen from space</h2>
      <p class="ck-sub">NASA's GRACE and GRACE-FO satellites weigh the water in and under the ground by measuring tiny changes in Earth's gravity.
      The groundwater percentile compares each week with the same time of year in a 1948-2012 reference period (0 = driest, 100 = wettest).</p>
      ${graceHeadline()}
      <div class="chart-box"><canvas id="grace-chart" aria-label="GRACE groundwater over time" role="img"></canvas></div>
      <p class="fine">Lines in cm are each set to zero on their own 2003-2026 average, because the files use different reference levels; compare their trend and timing, not their height.</p>
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
          ${mapLayer === 'tws_trend_cm_yr' && periods.length > 1 ? `<label class="picker">Period <select id="gm-period">${periods.map(k => `<option value="${esc(k)}" ${k === trendPeriod ? 'selected' : ''}>${esc(periodLabel(k))}</option>`).join('')}</select></label>` : ''}
          ${mapLayer === 'tws_trend_cm_yr' ? `<p class="fine">Total water storage trend on a coarser ${fmt(mf.frames.tws_trend_cm_yr[trendPeriod]?.cell, 1)}&deg; grid (GRACE sees areas a few hundred kilometres across).</p>` : ''}
          ${mapLayer === 'gws_pct' && nFrames > 1 ? `<label class="picker">Date: <b id="gm-date">${esc(mf.frames.gws_pct[mapIdx].date)}</b>
            <input id="gm-idx" type="range" min="0" max="${nFrames - 1}" value="${mapIdx}"></label>` : (nFrames && mapLayer === 'gws_pct' ? `<p class="fine">Date: ${esc(mf.frames.gws_pct[mapIdx]?.date || '')}</p>` : '')}
          ${mapLayer === 'gws_pct' ? `<p class="fine">Grid cells ${fmt(mf.cell, 3)}&deg;; county outlines for orientation.</p>` : ''}` : `<p>${NA}: grace.json has no maps.</p>`}
      </section>
      <section class="card">
        <h3>Do the wells agree with the satellites?</h3>
        ${wellsVsGrace()}
        <p class="fine">Well storage = water-level change &times; specific yield, averaged over the region. GRACE senses all water (soil, groundwater, reservoirs) over areas a few hundred kilometres across, so agreement in trend and timing, not exact values, is the test.</p>
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
  root.querySelector('#gm-period')?.addEventListener('change', e => { trendPeriod = e.target.value; drawMap(cv, mf); });
  root.querySelectorAll('[data-gl]').forEach(b => b.addEventListener('click', () => { mapLayer = b.dataset.gl; renderGrace(); }));
}

export function graceSummary() {
  const s = D?.grace?.series;
  if (!s?.dates?.length || !Array.isArray(s.gws_pct)) return null;
  const last = s.gws_pct.length - 1;
  return { date: s.dates[last], pct: s.gws_pct[last], x: decYear(s.dates[last]) };
}
