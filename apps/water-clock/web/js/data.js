// Data loading. Real model output lives in web/data/<file>. If (and only if) a real file is
// missing, the shape-only fixture web/mock/mock_<file> is used and the file is recorded in
// `mockUsed`, which drives the red MOCK DATA banner (BUILD_RULES rule 2).

export const FILES = {
  meta: 'meta.json',
  counties: 'counties.geojson',
  clocks: 'county_clocks.json',
  fields: 'fields.json',
  grid: 'grid.json',
  strategies: 'strategies.json',
  scenario: 'scenario.json',
  grace: 'grace.json',
  validation: 'validation.json',
  climate: 'climate.json',
};

export const mockUsed = [];
export const missing = [];

async function getJson(url) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function loadOne(key, file) {
  try {
    return await getJson(`data/${file}`);
  } catch (e) {
    try {
      const d = await getJson(`mock/mock_${file}`);
      mockUsed.push(file);
      return d;
    } catch {
      missing.push(file);
      return null;
    }
  }
}

export async function loadAll() {
  const keys = Object.keys(FILES);
  const vals = await Promise.all(keys.map(k => loadOne(k, FILES[k])));
  const D = {};
  keys.forEach((k, i) => { D[k] = vals[i]; });
  return index(D);
}

// Build lookups so views do not re-scan arrays.
function index(D) {
  D.countyByFips = {};
  for (const c of D.clocks?.counties || []) D.countyByFips[String(c.fips)] = c;
  D.gmdByName = {};
  for (const g of D.clocks?.gmds || []) D.gmdByName[String(g.gmd || g.name || g.fips)] = g;
  // County names/gmd also from the GeoJSON (in case county_clocks is missing a county).
  D.geoByFips = {};
  for (const f of D.counties?.features || []) {
    const p = f.properties || {};
    if (p.fips != null) D.geoByFips[String(p.fips)] = p;
  }
  // Fields: columnar -> objects.
  D.fieldRows = [];
  if (D.fields?.columns && Array.isArray(D.fields.rows)) {
    const cols = D.fields.columns;
    D.fieldRows = D.fields.rows.map(r => {
      const o = {};
      cols.forEach((c, i) => { o[c] = r[i]; });
      if (o.fips != null) o.fips = String(o.fips);
      return o;
    });
  }
  // Scenario per county: accept {counties:{fips:{}}}, {counties:[{fips}]}, or {fips:{}}.
  D.scenByFips = {};
  const sc = D.scenario;
  if (sc) {
    const src = sc.counties ?? sc.per_county ?? sc;
    if (Array.isArray(src)) for (const c of src) { if (c && c.fips != null) D.scenByFips[String(c.fips)] = c; }
    else if (src && typeof src === 'object') {
      for (const [k, v] of Object.entries(src)) if (/^\d{5}$/.test(k) && v && typeof v === 'object') D.scenByFips[k] = v;
    }
  }
  D.strategyList = Array.isArray(D.strategies?.strategies) ? D.strategies.strategies : [];
  D.thresholds = D.clocks?.thresholds_ft || [15, 30, 50];
  D.defaultThr = D.clocks?.threshold_default_ft || 30;
  return D;
}

export function countyName(D, fips) {
  const c = D.countyByFips[fips] || D.geoByFips[fips];
  return c?.name || `County ${fips}`;
}
