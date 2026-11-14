// Data loader. Reads web/data/<file>; only if that file is missing (or unreadable) falls back to web/mock/<file>
// and records it, so the app can show the MOCK DATA banner (BUILD_RULES rule 2). Geometry has no mock fallback.

const FILES = {
  meta: 'meta.json',
  bill: 'county_bill.json',
  hindcast: 'hindcast.json',
  strategies: 'strategies.json',
  summary: 'regional_summary.json',
  fields: 'focus_fields.json',
  counties: 'counties.geojson',
  states: 'states.geojson',
};
const NO_MOCK = new Set(['counties', 'states']);

async function getJSON(url) {
  try {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

/** Make polygon rings follow d3-geo's winding (exterior clockwise in lon/lat), whatever the source used. */
function rewind(fc) {
  if (!fc || !Array.isArray(fc.features)) return fc;
  const area = (r) => { let s = 0; for (let i = 0; i < r.length - 1; i++) s += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]; return s / 2; };
  const fixPoly = (p) => p.map((ring, i) => { const a = area(ring); return (i === 0 ? a > 0 : a < 0) ? ring.slice().reverse() : ring; });
  for (const f of fc.features) {
    const g = f.geometry;
    if (!g) continue;
    if (g.type === 'Polygon') g.coordinates = fixPoly(g.coordinates);
    else if (g.type === 'MultiPolygon') g.coordinates = g.coordinates.map(fixPoly);
  }
  return fc;
}

export async function loadAll() {
  const out = { mockFiles: [], missing: [] };
  await Promise.all(Object.entries(FILES).map(async ([key, file]) => {
    let d = await getJSON(`data/${file}`);
    if (d == null && !NO_MOCK.has(key)) {
      d = await getJSON(`mock/${file}`);
      if (d != null) out.mockFiles.push(file);
    }
    if (d == null) out.missing.push(file);
    else if (d.mock === true && !out.mockFiles.includes(file)) out.mockFiles.push(file);
    out[key] = d;
  }));
  rewind(out.counties);
  rewind(out.states);
  return out;
}
