// County choropleth drawn as SVG with d3-geo (Albers equal-area conic fitted to the 7 states). No tile server.
import { showTip, hideTip } from './util.js';

const d3 = window.d3;
export const NODATA = '#d9d9d6';

/**
 * @param {HTMLElement} host
 * @param {{counties, states, width?, onSelect?(fips), tip?(fips)->html, label}} opts
 */
export function createMap(host, opts) {
  const { counties, states } = opts;
  const width = opts.width || 960;
  const proj = d3.geoConicEqualArea().parallels([37, 45]).rotate([96, 0]);
  proj.fitWidth(width, states && states.features?.length ? states : counties);
  const path = d3.geoPath(proj);
  const [[, y0], [, y1]] = path.bounds(states && states.features?.length ? states : counties);
  const height = Math.ceil(y1 + Math.max(0, y0)) + 2;

  host.innerHTML = '';
  const svg = d3.select(host).append('svg')
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('role', 'img')
    .attr('aria-label', opts.label || 'County map')
    .attr('class', 'map-svg');
  const gC = svg.append('g').attr('class', 'counties');
  const gS = svg.append('g').attr('class', 'states').attr('pointer-events', 'none');
  const gSel = svg.append('g').attr('class', 'sel').attr('pointer-events', 'none');

  const feats = counties.features.filter((f) => f.geometry);
  const byFips = new Map(feats.map((f) => [String(f.properties.fips), f]));
  const paths = gC.selectAll('path').data(feats).join('path')
    .attr('d', path)
    .attr('data-fips', (f) => f.properties.fips)
    .attr('fill', NODATA);

  if (states) {
    gS.selectAll('path').data(states.features).join('path').attr('d', path).attr('class', 'state-line');
  }

  paths.on('pointermove', (ev, f) => {
    if (ev.pointerType !== 'mouse' || !opts.tip) return;
    showTip(opts.tip(f.properties.fips), ev);
  }).on('pointerleave', hideTip)
    .on('click', (ev, f) => { hideTip(); opts.onSelect && opts.onSelect(String(f.properties.fips)); });

  const api = {
    proj, path, svg, byFips,
    /** Recolour: fill(fips) -> css colour */
    paint(fill) { paths.attr('fill', (f) => fill(String(f.properties.fips))); },
    select(fips) {
      const f = byFips.get(fips);
      gSel.selectAll('path').data(f ? [f] : []).join('path').attr('d', path).attr('class', 'sel-line');
    },
  };
  return api;
}

/** Threshold scale with "nice" rounded breaks from value quantiles; returns {scale, breaks, colors}. */
export function makeScale(values, colors) {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  const n = colors.length;
  if (!v.length) return { scale: () => NODATA, breaks: [], colors };
  const raw = [];
  for (let i = 1; i < n; i++) raw.push(d3.quantileSorted(v, i / n));
  const niceStep = (x) => (x < 2 ? 0.5 : x < 10 ? 1 : x < 25 ? 5 : x < 100 ? 10 : x < 250 ? 25 : 50);
  let breaks = raw.map((b) => Math.round(b / niceStep(b)) * niceStep(b));
  breaks = [...new Set(breaks)].filter((b, i, a) => i === 0 || b > a[i - 1]);
  const m = breaks.length + 1;
  const cols = m === 1 ? [colors[Math.floor(n / 2)]] : d3.range(m).map((i) => colors[Math.round((i * (n - 1)) / (m - 1))]);
  const scale = d3.scaleThreshold().domain(breaks).range(cols);
  return { scale: (x) => (Number.isFinite(x) ? scale(x) : NODATA), breaks, colors: cols };
}
