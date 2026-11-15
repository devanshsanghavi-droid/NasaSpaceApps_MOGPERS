// MapLibre map: counties coloured by years left, optional detailed grid, clickable fields.
import { yearStepExpr, YEAR_BINS, esc, yrs, isNum } from './util.js';
import { fieldYears, countyYears } from './scenario.js';
import { loadLazy } from './data.js';

const POSITRON = 'https://tiles.openfreemap.org/styles/positron';
const BBOX = [[-102.06, 36.99], [-99.55, 40.01]];

const FALLBACK_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#eef1ec' } }],
};

let map = null, D = null, handlers = {}, beforeId, usingBasemap = false;
let hoverPopup = null;

async function fetchStyle() {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 5000);
  try {
    const r = await fetch(POSITRON, { signal: ctl.signal });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const s = await r.json();
    if (!s || !Array.isArray(s.layers)) throw new Error('bad style');
    return s;
  } catch {
    return null;
  } finally { clearTimeout(t); }
}

function countiesFC(thr) {
  const fc = D.counties;
  if (!fc?.features) return { type: 'FeatureCollection', features: [] };
  return {
    type: 'FeatureCollection',
    features: fc.features.map(f => {
      const p = { ...(f.properties || {}) };
      const c = D.countyByFips[String(p.fips)];
      const y = c ? countyYears(c, thr) : (thr === D.defaultThr ? { p50: p.years_p50 } : { p50: null });
      p.yv = isNum(y.p50) ? y.p50 : null;
      p.fips = String(p.fips);
      return { type: 'Feature', geometry: f.geometry, properties: p };
    }),
  };
}

function fieldsFC(thr) {
  return {
    type: 'FeatureCollection',
    features: D.fieldRows.filter(f => isNum(f.lon) && isNum(f.lat)).map(f => {
      const y = fieldYears(f, thr, D.defaultThr);
      return { type: 'Feature', geometry: { type: 'Point', coordinates: [f.lon, f.lat] }, properties: { id: String(f.id), yv: isNum(y.p50) ? y.p50 : null } };
    }),
  };
}

function gridFC() {
  const g = D.grid;
  if (!g?.rows || !isNum(g.cell_deg)) return { type: 'FeatureCollection', features: [] };
  const h = g.cell_deg / 2;
  return {
    type: 'FeatureCollection',
    features: g.rows.filter(r => isNum(r[0]) && isNum(r[1])).map(r => ({
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [[[r[0] - h, r[1] - h], [r[0] + h, r[1] - h], [r[0] + h, r[1] + h], [r[0] - h, r[1] + h], [r[0] - h, r[1] - h]]] },
      properties: { yv: isNum(r[4]) ? r[4] : null, sat: r[2], decl: r[3] },
    })),
  };
}

function bboxOf(fc) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const walk = c => { if (typeof c[0] === 'number') { x0 = Math.min(x0, c[0]); x1 = Math.max(x1, c[0]); y0 = Math.min(y0, c[1]); y1 = Math.max(y1, c[1]); } else c.forEach(walk); };
  for (const f of fc?.features || []) if (f.geometry) walk(f.geometry.coordinates);
  return isFinite(x0) ? [[x0, y0], [x1, y1]] : null;
}

export function renderLegend(elm, thr) {
  // collapsible: open on wide screens, closed on phones so it does not cover the map; keeps the user's choice
  const prev = elm.querySelector('details');
  const open = prev ? prev.open : !window.matchMedia('(max-width: 640px)').matches;
  elm.innerHTML = `<details ${open ? 'open' : ''}><summary class="lg-title">Years of water left <span>(${thr} ft)</span></summary>` +
    YEAR_BINS.map(b => `<div class="lg-row"><span class="sw" style="background:${b.color}"></span>${b.label}</div>`).join('') +
    `<div class="lg-row"><span class="sw" style="background:#9aa0a6"></span>no estimate (outside mapped aquifer)</div>` +
    `<div class="lg-row"><span class="sw dot"></span>irrigation well (click)</div><div class="lg-row lg-mid">middle estimate</div></details>`;
}

export async function initMap(data, h, thr) {
  D = data; handlers = h;
  const note = document.getElementById('map-note');
  if (!window.maplibregl) {
    note.hidden = false;
    note.textContent = 'The map library could not load (offline?). Use the county search above; all numbers still work.';
    return null;
  }
  const style = await fetchStyle();
  usingBasemap = !!style;
  if (!style) {
    note.hidden = false;
    note.textContent = 'Background map tiles unavailable; showing county outlines only.';
  }
  map = new maplibregl.Map({
    container: 'map',
    style: style || FALLBACK_STYLE,
    bounds: bboxOf(D.counties) || BBOX,
    fitBoundsOptions: { padding: window.matchMedia('(min-width: 900px)').matches ? { top: 20, right: 20, bottom: 20, left: 150 } : 20 },
    attributionControl: { compact: true },
    cooperativeGestures: false,
  });
  window.__waterClockMap = map; // used by tests/smoke.js to click a field
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  map.on('error', e => {
    // Basemap tile/glyph failures should not break the app; log once quietly.
    if (!map.__warned) { map.__warned = true; console.warn('Map resource issue:', e?.error?.message || e); }
  });
  await new Promise(res => map.on('load', res));
  beforeId = (map.getStyle().layers || []).find(l => l.type === 'symbol')?.id;

  map.addSource('counties', { type: 'geojson', data: countiesFC(thr) });
  map.addSource('grid', { type: 'geojson', data: gridFC() });
  map.addSource('fields', { type: 'geojson', data: fieldsFC(thr) });

  map.addLayer({ id: 'county-fill', type: 'fill', source: 'counties', paint: { 'fill-color': yearStepExpr('yv'), 'fill-opacity': usingBasemap ? 0.55 : 0.75 } }, beforeId);
  map.addLayer({ id: 'grid-fill', type: 'fill', source: 'grid', layout: { visibility: 'none' }, paint: { 'fill-color': yearStepExpr('yv'), 'fill-opacity': 0.8 } }, beforeId);
  map.addLayer({ id: 'county-line', type: 'line', source: 'counties', paint: { 'line-color': '#33413d', 'line-width': 0.8 } }, beforeId);
  map.addLayer({ id: 'county-sel', type: 'line', source: 'counties', filter: ['==', ['get', 'fips'], ''], paint: { 'line-color': '#111', 'line-width': 3 } });
  map.addLayer({
    id: 'fields', type: 'circle', source: 'fields',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 2.5, 9, 4.5, 12, 7],
      'circle-color': yearStepExpr('yv'),
      'circle-stroke-color': '#1d2422', 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 6, 0.4, 10, 1],
    },
  });
  map.addLayer({ id: 'field-sel', type: 'circle', source: 'fields', filter: ['==', ['get', 'id'], ''], paint: { 'circle-radius': 9, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#111', 'circle-stroke-width': 3 } });

  if (usingBasemap) {
    try {
      const font = findFont(map.getStyle());
      if (font) map.addLayer({ id: 'county-label', type: 'symbol', source: 'counties', layout: { 'text-field': ['get', 'name'], 'text-font': [font], 'text-size': 11 }, paint: { 'text-color': '#1d2422', 'text-halo-color': '#fff', 'text-halo-width': 1.2 } });
    } catch { /* labels are optional */ }
  }

  map.on('click', e => {
    const f = map.queryRenderedFeatures(e.point, { layers: ['fields'] })[0];
    if (f) { handlers.onField?.(String(f.properties.id)); return; }
    const c = map.queryRenderedFeatures(e.point, { layers: ['county-fill'] })[0];
    if (c) handlers.onCounty?.(String(c.properties.fips));
  });
  hoverPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: 'hover-pop' });
  map.on('mousemove', e => {
    const f = map.queryRenderedFeatures(e.point, { layers: ['fields', 'county-fill'] })[0];
    map.getCanvas().style.cursor = f ? 'pointer' : '';
    if (!f) { hoverPopup.remove(); return; }
    const p = f.properties;
    const txt = f.layer.id === 'fields'
      ? `Well ${esc(p.id)}: <b>${yrs(p.yv)}</b> years`
      : `${esc(p.name)} County: <b>${yrs(p.yv)}</b> years`;
    hoverPopup.setLngLat(e.lngLat).setHTML(txt).addTo(map);
  });
  map.on('mouseout', () => hoverPopup.remove());
  return map;
}

function findFont(style) {
  for (const l of style.layers || []) {
    const f = l.layout?.['text-font'];
    if (Array.isArray(f) && typeof f[0] === 'string') return f[0];
  }
  return null;
}

export function setThreshold(thr) {
  if (!map?.getSource('counties')) return;
  map.getSource('counties').setData(countiesFC(thr));
  map.getSource('fields').setData(fieldsFC(thr));
}

export async function showGrid(on) {
  if (!map?.getLayer('grid-fill')) return;
  if (on && D.grid === undefined) {
    await loadLazy(D, 'grid');
    map.getSource('grid')?.setData(gridFC());
  }
  map.setLayoutProperty('grid-fill', 'visibility', on ? 'visible' : 'none');
  map.setPaintProperty('county-fill', 'fill-opacity', on ? 0 : (usingBasemap ? 0.55 : 0.75));
}

export function selectField(f) {
  if (!map?.getLayer('field-sel')) return;
  map.setFilter('field-sel', ['==', ['get', 'id'], f ? String(f.id) : '']);
  if (f && isNum(f.lon)) map.easeTo({ center: [f.lon, f.lat], zoom: Math.max(map.getZoom(), 8), duration: 600 });
}

export function selectCounty(fips, fly = true) {
  if (!map?.getLayer('county-sel')) return;
  map.setFilter('county-sel', ['==', ['get', 'fips'], fips || '']);
  if (!fips || !fly) return;
  const feat = D.counties?.features?.find(f => String(f.properties?.fips) === fips);
  const bb = feat && bboxOf({ features: [feat] });
  if (bb) map.fitBounds(bb, { padding: 40, maxZoom: 9, duration: 700 });
}

export function resize() { map?.resize(); }
export function hasGrid() { return D?.grid === undefined || (D?.grid?.rows || []).length > 0; }
