// The big "water clock" gauge (inline SVG) + plain-language uncertainty text.
import { isNum, yrs, yearColor, CAP, esc } from './util.js';

const FULL = 50; // a full ring = 50 years; beyond that the ring is full and the number says so

function arc(cx, cy, r, a0, a1) {
  const p = a => [cx + r * Math.sin(a * 2 * Math.PI), cy - r * Math.cos(a * 2 * Math.PI)];
  const [x0, y0] = p(a0), [x1, y1] = p(Math.min(a1, 0.9999));
  const large = a1 - a0 > 0.5 ? 1 : 0;
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

export function clockSvg(y, size = 168) {
  const c = size / 2, r = c - 14;
  const frac = v => (isNum(v) ? Math.max(0, Math.min(1, v / FULL)) : 0);
  const col = yearColor(y.p50);
  const ticks = [];
  for (let i = 0; i < 5; i++) {
    const a = (i / 5) * 2 * Math.PI;
    const x0 = c + (r + 7) * Math.sin(a), y0 = c - (r + 7) * Math.cos(a), x1 = c + (r + 12) * Math.sin(a), y1 = c - (r + 12) * Math.cos(a);
    ticks.push(`<line x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}" stroke="#7b8580" stroke-width="1.5"/>`);
  }
  const range = isNum(y.p10) && isNum(y.p90) && frac(y.p90) > frac(y.p10)
    ? `<path d="${arc(c, c, r, frac(y.p10), frac(y.p90))}" stroke="${col}" stroke-opacity="0.35" stroke-width="20" fill="none"/>` : '';
  const main = frac(y.p50) > 0
    ? (frac(y.p50) >= 1 ? `<circle cx="${c}" cy="${c}" r="${r}" stroke="${col}" stroke-width="10" fill="none"/>`
      : `<path d="${arc(c, c, r, 0, frac(y.p50))}" stroke="${col}" stroke-width="10" stroke-linecap="round" fill="none"/>`) : '';
  const label = isNum(y.p50) ? yrs(y.p50) : '?';
  return `<svg class="clock-svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="${esc(label)} years left">
    <circle cx="${c}" cy="${c}" r="${r}" stroke="#e4e8e5" stroke-width="10" fill="none"/>
    ${ticks.join('')}${range}${main}
    <text x="${c}" y="${c + 4}" text-anchor="middle" class="clock-num" fill="#14201c">${esc(label)}</text>
    <text x="${c}" y="${c + 26}" text-anchor="middle" class="clock-unit" fill="#3f4b47">years left</text>
  </svg>`;
}

// Range p10..p90 that spans "already below" to "100+" carries no information for a farmer.
export function veryUncertain(y) {
  return isNum(y.p10) && isNum(y.p90) && y.p10 <= 0 && y.p90 >= CAP;
}

export function uncertaintyText(y, thr) {
  if (y.below) return `The aquifer here is already thinner than ${thr} ft, the level used as "too thin to irrigate reliably". Wells may still pump, but at falling rates. Try a lower threshold to see how long the remaining water lasts.`;
  if (!isNum(y.p50)) return 'Not enough data to estimate the clock here.';
  if (y.p50 >= CAP) return `The water table here is flat or rising, or falling so slowly that the aquifer stays thicker than ${thr} ft for more than 100 years at today's pace.`;
  let r = '';
  if (veryUncertain(y)) {
    r = ` This estimate is <b>very uncertain here</b>: depending on how thick the water-bearing layer really is and how fast it is falling, parts of this area may already be below ${thr} ft while others could last more than 100 years.`;
  } else if (isNum(y.p10) && isNum(y.p90)) {
    const low = y.p10 <= 0
      ? ` Parts of this area may already be below ${thr} ft.`
      : ` There is roughly a 1-in-10 chance it is shorter than <b>${yrs(y.p10)}</b> years.`;
    r = `${low} There is roughly a 1-in-10 chance it is longer than <b>${yrs(y.p90)}</b> years.`;
  }
  return `If pumping continues at the 2011-2026 pace, with average weather, the aquifer under this spot is expected to stay thicker than ${thr} ft for about <b>${yrs(y.p50)}</b> more years.${r} The spread comes from how fast the water table has been falling, how much water the sand and gravel hold, and how much rain soaks back in.`;
}

export function rangeLine(y) {
  if (y.below) return 'pick a lower threshold to see the remaining water';
  if (!isNum(y.p10) || !isNum(y.p90)) return 'range not available';
  if (veryUncertain(y)) return 'very uncertain here (range 0 to 100+ years)';
  return `likely range <b>${yrs(y.p10)} to ${yrs(y.p90)}</b> years`;
}

export function headlineRange(y) {
  if (!isNum(y.p10) || !isNum(y.p90)) return '';
  return `range ${yrs(y.p10)} to ${yrs(y.p90)} years`;
}
