// Entry point: loads data, wires state, tabs, search and threshold controls.
import { loadAll, mockUsed, missing, countyName } from './data.js';
import { esc, isNum, yrs, num, fmt } from './util.js';
import { countyYears } from './scenario.js';
import { initMap, setThreshold, selectField, selectCounty, showGrid, resize, renderLegend, hasGrid } from './map.js';
import { initFarmer, renderFarmer } from './farmer.js';
import { initCommunity, renderCommunity } from './community.js';
import { initGrace, renderGrace } from './grace.js';
import { initValidation, renderValidation } from './validation.js';

const S = { view: 'farmer', thr: 30, fieldId: null, fips: null, priority: 50, cPct: 50, cStrat: null, cFips: null };
let D;

function loadScript(src) {
  return new Promise(res => { const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = res; document.head.appendChild(s); });
}
async function ensureLibs() {
  const jobs = [];
  if (!window.maplibregl) {
    jobs.push(loadScript('https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js'));
    const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = 'https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css'; document.head.appendChild(l);
  }
  if (!window.Chart) jobs.push(loadScript('https://unpkg.com/chart.js@4.4.4/dist/chart.umd.js'));
  await Promise.all(jobs);
}

function regionClock() {
  const r = D.clocks?.region;
  if (r?.years_left) return { y: countyYears(r, S.thr), how: 'region' };
  const cs = (D.clocks?.counties || []).map(c => ({ c, y: countyYears(c, S.thr) })).filter(x => isNum(x.y.p50));
  if (!cs.length) return null;
  const w = x => (isNum(x.c.irrigated_acres) && x.c.irrigated_acres > 0 ? x.c.irrigated_acres : 0);
  const tot = cs.reduce((a, x) => a + w(x), 0);
  if (tot > 0) {
    const avg = k => cs.reduce((a, x) => a + w(x) * (isNum(x.y[k]) ? x.y[k] : x.y.p50), 0) / tot;
    return { y: { p10: avg('p10'), p50: avg('p50'), p90: avg('p90') }, how: 'weighted', n: cs.length };
  }
  const med = k => { const v = cs.map(x => x.y[k]).filter(isNum).sort((a, b) => a - b); return v.length ? v[Math.floor(v.length / 2)] : null; };
  return { y: { p10: med('p10'), p50: med('p50'), p90: med('p90') }, how: 'median', n: cs.length };
}

function renderHeader() {
  if (D.meta?.region) document.getElementById('region-name').textContent = D.meta.region;
  const rc = regionClock();
  const big = document.getElementById('hl-years'), rng = document.getElementById('hl-range'), ctx = document.getElementById('hl-context');
  if (!rc) { big.textContent = 'n/a'; rng.textContent = 'The region clock is not available yet.'; ctx.textContent = ''; return; }
  big.textContent = yrs(rc.y.p50);
  rng.innerHTML = isNum(rc.y.p10) && isNum(rc.y.p90) ? `likely range <b>${yrs(rc.y.p10)} to ${yrs(rc.y.p90)}</b> years` : '';
  const how = rc.how === 'region' ? 'across the region' : rc.how === 'weighted' ? `averaged over the irrigated acres of ${rc.n} counties` : `median of ${rc.n} counties`;
  const sorted = (D.clocks?.counties || []).map(c => ({ c, y: countyYears(c, S.thr).p50 })).filter(x => isNum(x.y)).sort((a, b) => a.y - b.y);
  const spread = sorted.length > 1 ? ` It ranges from about ${yrs(sorted[0].y)} years in ${esc(sorted[0].c.name)} County to ${yrs(sorted[sorted.length - 1].y)} in ${esc(sorted[sorted.length - 1].c.name)}.` : '';
  ctx.innerHTML = `At today's pumping, that is how long the Ogallala aquifer under a typical irrigated acre stays thick enough (over ${S.thr} ft) to irrigate, ${how}.${spread}`;
}

function renderBanner() {
  const b = document.getElementById('mock-banner');
  if (mockUsed.length) {
    b.hidden = false;
    document.getElementById('mock-banner-text').textContent =
      `Model outputs missing from web/data/, shown from web/mock/ instead: ${mockUsed.join(', ')}.`;
    document.body.classList.add('has-mock');
  }
  const gen = document.getElementById('foot-gen');
  gen.textContent = [D.meta?.generated_at ? `Model outputs generated ${D.meta.generated_at}.` : '', missing.length ? `Missing files: ${missing.join(', ')}.` : ''].join(' ');
}

function renderPanels() {
  if (S.view === 'farmer') renderFarmer();
  else if (S.view === 'community') renderCommunity();
  else if (S.view === 'grace') renderGrace();
  else if (S.view === 'data') renderValidation();
}

function setView(v, focusTab = false) {
  S.view = v;
  document.querySelectorAll('[role=tab]').forEach(t => {
    const on = t.dataset.view === v;
    t.setAttribute('aria-selected', on); t.tabIndex = on ? 0 : -1;
    if (on && focusTab) t.focus();
  });
  document.querySelectorAll('[role=tabpanel]').forEach(p => { p.hidden = p.id !== 'view-' + v; });
  document.getElementById('workbench').hidden = !(v === 'farmer' || v === 'community');
  renderPanels();
  if (v === 'farmer' || v === 'community') setTimeout(resize, 0);
  try { history.replaceState(null, '', '#' + v + (S.fieldId ? '/field/' + encodeURIComponent(S.fieldId) : S.fips ? '/county/' + S.fips : '')); } catch { /* ignore */ }
}

const actions = {
  setThr(t) {
    S.thr = t;
    document.querySelectorAll('input[name=thr]').forEach(r => { r.checked = +r.value === t; });
    setThreshold(t); renderLegend(document.getElementById('legend'), t); renderHeader(); renderPanels();
  },
  selectField(id) {
    const f = D.fieldRows.find(x => String(x.id) === String(id));
    if (!f) return;
    S.fieldId = String(f.id); S.fips = f.fips;
    selectField(f); selectCounty(f.fips, false);
    setView('farmer');
    scrollPanelIntoView();
  },
  selectCounty(fips, view) {
    if (!fips) return;
    S.fips = String(fips); S.cFips = S.fips;
    if (view !== 'community') S.fieldId = null;
    selectField(null); selectCounty(S.fips, true);
    setView(view || (S.view === 'community' ? 'community' : 'farmer'));
    scrollPanelIntoView();
  },
};

function scrollPanelIntoView() {
  if (window.matchMedia('(max-width: 899px)').matches) {
    const p = document.querySelector('.panel-col');
    setTimeout(() => p?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  } else {
    const wb = document.getElementById('workbench');
    if (wb && wb.getBoundingClientRect().top < 0) wb.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function wireControls() {
  const tabs = [...document.querySelectorAll('[role=tab]')];
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => setView(t.dataset.view));
    t.addEventListener('keydown', e => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        const n = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        setView(n.dataset.view, true); e.preventDefault();
      }
    });
  });
  document.querySelectorAll('input[name=thr]').forEach(r => r.addEventListener('change', () => actions.setThr(+r.value)));
  const gt = document.getElementById('grid-toggle');
  if (!hasGrid()) gt.parentElement.hidden = true;
  gt.addEventListener('change', () => showGrid(gt.checked));
  // County search
  const names = {};
  const all = { ...D.geoByFips, ...D.countyByFips };
  const dl = document.getElementById('county-list');
  Object.entries(all).sort((a, b) => String(a[1].name).localeCompare(b[1].name)).forEach(([f, c]) => {
    names[String(c.name).toLowerCase()] = f; names[String(c.name).toLowerCase().replace(/\s*\(.*\)$/, '')] = f;
    const o = document.createElement('option'); o.value = c.name; dl.appendChild(o);
  });
  const inp = document.getElementById('county-search');
  let lastQ = '';
  const go = () => {
    const q = inp.value.trim().toLowerCase().replace(/\s+county$/, '');
    if (!q || q === lastQ) return; // 'change' also fires on blur after Enter
    lastQ = q;
    const f = names[q] || Object.entries(names).find(([n]) => n.startsWith(q))?.[1] || (/^\d{5}$/.test(q) && all[q] ? q : null);
    if (f) actions.selectCounty(f);
  };
  inp.addEventListener('change', go);
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') { lastQ = ''; go(); e.preventDefault(); } });
  inp.addEventListener('input', () => { if (!inp.value) lastQ = ''; });
}

function restoreFromHash() {
  const m = location.hash.match(/^#(farmer|community|grace|data)(?:\/(field|county)\/(.+))?$/);
  if (!m) return 'farmer';
  if (m[2] === 'field') { const f = D.fieldRows.find(x => String(x.id) === decodeURIComponent(m[3])); if (f) { S.fieldId = String(f.id); S.fips = f.fips; } }
  if (m[2] === 'county' && /^\d{5}$/.test(m[3])) { S.fips = m[3]; S.cFips = m[3]; }
  return m[1];
}

async function main() {
  await ensureLibs();
  D = await loadAll();
  S.thr = D.defaultThr;
  if (window.Chart) { Chart.defaults.font.family = getComputedStyle(document.body).fontFamily; Chart.defaults.color = '#3f4b47'; }
  initFarmer(D, S, actions); initCommunity(D, S, actions); initGrace(D); initValidation(D, S);
  renderBanner(); renderHeader();
  renderLegend(document.getElementById('legend'), S.thr);
  const v = restoreFromHash();
  setView(v);
  wireControls();
  await initMap(D, { onField: id => actions.selectField(id), onCounty: f => actions.selectCounty(f) }, S.thr);
  if (S.fieldId) selectField(D.fieldRows.find(x => String(x.id) === S.fieldId));
  if (S.fips) selectCounty(S.fips, !S.fieldId);
  document.body.classList.add('ready');
}

main().catch(e => {
  console.error(e);
  const h = document.getElementById('hl-range');
  if (h) h.textContent = 'Something went wrong while loading: ' + e.message;
});
