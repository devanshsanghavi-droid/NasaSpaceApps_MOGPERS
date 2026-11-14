// Drought Bill: entry point. Loads data (with mock fallback), wires views, routing and county search.
import { loadAll } from './js/data.js';
import { initPublic, countyLabel } from './js/public.js';
import { initFarmer } from './js/farmer.js';
import { renderAbout } from './js/about.js';
import { esc } from './js/util.js';

const FOCUS = '19149'; // Plymouth County, Iowa
const VIEWS = ['public', 'farmer', 'about'];

async function main() {
  const D = await loadAll();

  if (D.mockFiles.length) {
    const b = document.getElementById('mock-banner');
    b.hidden = false;
    document.getElementById('mock-files').textContent = `Synthetic placeholder numbers from: ${D.mockFiles.join(', ')}. Not results.`;
  }
  if (D.missing.length) console.info('Drought Bill: missing data files', D.missing);

  const state = { view: 'public', layer: 'expected', taxpayer: false, fips: FOCUS, rotation: 'corn-soy', fmode: 'county', field: null };
  let pub = null, farm = null;
  const select = (fips) => {
    state.fips = fips;
    const c = D.bill?.counties?.[fips];
    const label = c ? countyLabel(c, fips) : '';
    document.querySelectorAll('.county-search').forEach((i) => { if (document.activeElement !== i) i.value = label; });
    pub?.setCounty();
    farm?.setCounty();
  };

  // county search (both views share one datalist)
  const names = new Map();
  for (const [f, c] of Object.entries(D.bill?.counties || {})) names.set(countyLabel(c, f).toLowerCase(), f);
  const known = new Set(names.values());
  for (const ft of D.counties?.features || []) {
    const p = ft.properties, f = String(p.fips);
    if (!known.has(f)) names.set(`${p.name} County, ${p.state}`.toLowerCase(), f);
  }
  document.getElementById('county-list').innerHTML = Object.entries(D.bill?.counties || {})
    .map(([f, c]) => countyLabel(c, f)).sort().map((l) => `<option value="${esc(l)}"></option>`).join('');
  document.querySelectorAll('.county-search').forEach((inp) => {
    const go = () => {
      const q = inp.value.trim().toLowerCase();
      if (!q) return;
      let f = names.get(q);
      if (!f) {
        const hits = [...names.keys()].filter((k) => k.startsWith(q) || k.split(',')[0].replace(' county', '') === q);
        if (hits.length === 1 || (hits.length && q.length > 3)) f = names.get(hits[0]);
      }
      if (f) { select(f); inp.blur(); }
    };
    inp.addEventListener('change', go);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  });

  pub = initPublic(D, state, select);
  farm = initFarmer(D, state, select);
  renderAbout(D, D.mockFiles);
  select(state.fips);

  // routing
  const show = () => {
    const v = location.hash.replace('#', '');
    state.view = VIEWS.includes(v) ? v : 'public';
    VIEWS.forEach((k) => { document.getElementById(`view-${k}`).hidden = k !== state.view; });
    document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-current', t.dataset.view === state.view ? 'page' : 'false'));
    if (state.view === 'farmer') farm.show();
    window.dispatchEvent(new Event('resize'));
  };
  window.addEventListener('hashchange', () => { show(); window.scrollTo(0, 0); });
  show();
  document.body.classList.add('ready');
}

main().catch((e) => {
  console.error(e);
  document.getElementById('hero').innerHTML = `<p class="empty">Could not load the data: ${esc(e.message)}</p>`;
});
