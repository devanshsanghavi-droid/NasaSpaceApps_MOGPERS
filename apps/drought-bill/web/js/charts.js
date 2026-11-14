// Small d3 SVG charts. Each renders at the host's pixel width (so text stays legible on phones) and is re-run on resize.
import { isNum, showTip, hideTip, esc } from './util.js';

const d3 = window.d3;
const C = { pred: '#3d4a5c', actual: '#c1121f', band: 'rgba(61,74,92,.16)', grid: '#e6e4df', axis: '#6b6f76' };

const resizers = new Map();
let rt;
window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => resizers.forEach((fn, host) => host.isConnected ? fn() : resizers.delete(host)), 150); });
function mount(host, draw) { resizers.set(host, draw); draw(); }

function frame(host, height, m) {
  host.innerHTML = '';
  const W = Math.max(280, host.clientWidth || 560);
  const svg = d3.select(host).append('svg').attr('width', W).attr('height', height).attr('class', 'chart-svg');
  return { svg, W, iw: W - m.l - m.r, ih: height - m.t - m.b, g: svg.append('g').attr('transform', `translate(${m.l},${m.t})`) };
}

/**
 * Predicted (bar + range whisker) vs actual (red bar) per category.
 * rows: [{label, pred, lo, hi, actual, highlight?}]
 */
export function pairedBars(host, rows, { fmt, height = 240, ariaLabel = '' } = {}) {
  mount(host, () => {
    const m = { t: 12, r: 8, b: 28, l: 52 };
    const { svg, iw, ih, g } = frame(host, height, m);
    svg.attr('role', 'img').attr('aria-label', ariaLabel);
    const max = d3.max(rows.flatMap((r) => [r.pred, r.hi, r.actual].filter(isNum))) || 1;
    const x = d3.scaleBand().domain(rows.map((r) => r.label)).range([0, iw]).padding(0.28);
    const xi = d3.scaleBand().domain(['pred', 'actual']).range([0, x.bandwidth()]).padding(0.12);
    const y = d3.scaleLinear().domain([0, max * 1.08]).nice().range([ih, 0]);
    g.append('g').attr('class', 'grid').selectAll('line').data(y.ticks(4)).join('line')
      .attr('x1', 0).attr('x2', iw).attr('y1', y).attr('y2', y).attr('stroke', C.grid);
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(4).tickFormat(fmt).tickSize(0).tickPadding(8)).call((a) => a.select('.domain').remove());
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ih})`).call(d3.axisBottom(x).tickSize(0).tickPadding(6)).call((a) => a.select('.domain').attr('stroke', C.axis));
    const grp = g.selectAll('.cat').data(rows).join('g').attr('transform', (r) => `translate(${x(r.label)},0)`);
    const bar = (key, color) => grp.filter((r) => isNum(r[key])).append('rect')
      .attr('x', xi(key)).attr('width', xi.bandwidth()).attr('y', (r) => y(r[key])).attr('height', (r) => ih - y(r[key]))
      .attr('rx', 2).attr('fill', color);
    bar('pred', C.pred);
    bar('actual', C.actual);
    const wx = xi('pred') + xi.bandwidth() / 2;
    grp.filter((r) => isNum(r.lo) && isNum(r.hi)).append('path')
      .attr('d', (r) => `M${wx},${y(r.lo)}V${y(r.hi)}M${wx - 5},${y(r.lo)}H${wx + 5}M${wx - 5},${y(r.hi)}H${wx + 5}`)
      .attr('stroke', '#111').attr('stroke-width', 1.5).attr('fill', 'none');
    grp.append('rect').attr('width', x.bandwidth()).attr('height', ih).attr('fill', 'transparent')
      .on('pointermove', (ev, r) => showTip(`<b>${esc(r.label)}</b><br>Predicted ${fmt(r.pred)}${isNum(r.lo) ? ` <span class="muted">(${fmt(r.lo)}–${fmt(r.hi)})</span>` : ''}<br>Actual <b class="red">${fmt(r.actual)}</b>`, ev))
      .on('pointerleave', hideTip);
  });
}

/** Scatter of predicted vs actual with a 1:1 line. pts: [{x: pred, y: actual, label}] */
export function scatter(host, pts, { fmt, height = 260, xLabel = 'Predicted', yLabel = 'Actual' } = {}) {
  mount(host, () => {
    const m = { t: 10, r: 12, b: 36, l: 52 };
    const { svg, iw, ih, g } = frame(host, height, m);
    svg.attr('role', 'img').attr('aria-label', `${yLabel} against ${xLabel}, one dot per county`);
    const max = d3.max(pts.flatMap((p) => [p.x, p.y])) || 1;
    const x = d3.scaleLinear().domain([0, max]).nice().range([0, iw]);
    const y = d3.scaleLinear().domain(x.domain()).range([ih, 0]);
    g.append('g').selectAll('line').data(y.ticks(4)).join('line').attr('x1', 0).attr('x2', iw).attr('y1', y).attr('y2', y).attr('stroke', C.grid);
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(4).tickFormat(fmt).tickSize(0).tickPadding(8)).call((a) => a.select('.domain').remove());
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ih})`).call(d3.axisBottom(x).ticks(4).tickFormat(fmt).tickSize(0).tickPadding(6)).call((a) => a.select('.domain').attr('stroke', C.axis));
    g.append('line').attr('x1', 0).attr('y1', ih).attr('x2', iw).attr('y2', 0).attr('stroke', C.axis).attr('stroke-dasharray', '4 3');
    g.append('text').attr('x', iw - 4).attr('y', 12).attr('text-anchor', 'end').attr('class', 'chart-note').text('perfect prediction');
    g.append('text').attr('x', iw / 2).attr('y', ih + 30).attr('text-anchor', 'middle').attr('class', 'chart-label').text(xLabel);
    g.append('text').attr('transform', `translate(-40,${ih / 2}) rotate(-90)`).attr('text-anchor', 'middle').attr('class', 'chart-label').text(yLabel);
    g.append('g').selectAll('circle').data(pts).join('circle')
      .attr('cx', (p) => x(p.x)).attr('cy', (p) => y(p.y)).attr('r', 3.2)
      .attr('fill', C.actual).attr('fill-opacity', 0.55).attr('stroke', '#fff').attr('stroke-width', 0.6)
      .on('pointermove', (ev, p) => showTip(`<b>${esc(p.label)}</b><br>Predicted ${fmt(p.x)}<br>Actual <b class="red">${fmt(p.y)}</b>`, ev))
      .on('pointerleave', hideTip);
  });
}

/** Bill vs rotation diversity line with range band, markers for "today" and the slider value. */
export function diversityChart(host, s, { now, sel, p90, fmt }) {
  mount(host, () => {
    const m = { t: 10, r: 10, b: 32, l: 44 };
    const { svg, iw, ih, g } = frame(host, 150, m);
    svg.attr('role', 'img').attr('aria-label', 'Estimated 2022-style drought bill as rotation diversity rises');
    const pts = s.div_values.map((d, i) => ({ d, b: s.bill_2022_style[i], lo: s.lo?.[i], hi: s.hi?.[i] })).filter((p) => isNum(p.d) && isNum(p.b));
    if (!pts.length) return;
    const x = d3.scaleLinear().domain(d3.extent(pts, (p) => p.d)).range([0, iw]);
    const y = d3.scaleLinear().domain([0, d3.max(pts, (p) => (isNum(p.hi) ? p.hi : p.b)) * 1.05]).nice().range([ih, 0]);
    g.append('g').selectAll('line').data(y.ticks(3)).join('line').attr('x1', 0).attr('x2', iw).attr('y1', y).attr('y2', y).attr('stroke', C.grid);
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(3).tickFormat(fmt).tickSize(0).tickPadding(8)).call((a) => a.select('.domain').remove());
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${ih})`).call(d3.axisBottom(x).ticks(5).tickSize(0).tickPadding(6)).call((a) => a.select('.domain').attr('stroke', C.axis));
    g.append('text').attr('x', iw).attr('y', ih + 28).attr('text-anchor', 'end').attr('class', 'chart-label').text('share of cropland in 3+ crop rotations →');
    const band = pts.filter((p) => isNum(p.lo) && isNum(p.hi));
    if (band.length > 1) g.append('path').attr('d', d3.area().x((p) => x(p.d)).y0((p) => y(p.lo)).y1((p) => y(p.hi))(band)).attr('fill', 'rgba(193,18,31,.13)');
    g.append('path').attr('d', d3.line().x((p) => x(p.d)).y((p) => y(p.b))(pts)).attr('fill', 'none').attr('stroke', C.actual).attr('stroke-width', 2);
    const mark = (v, cls, label) => {
      if (!isNum(v)) return;
      const cx = x(Math.max(x.domain()[0], Math.min(x.domain()[1], v)));
      g.append('line').attr('x1', cx).attr('x2', cx).attr('y1', 0).attr('y2', ih).attr('class', cls);
      g.append('text').attr('x', cx + 3).attr('y', 10).attr('class', 'chart-note').text(label);
    };
    mark(now, 'mk-now', 'today');
    if (isNum(p90) && Math.abs(p90 - now) > 0.05) mark(p90, 'mk-p90', 'top 10%');
    mark(sel, 'mk-sel', '');
  });
}
