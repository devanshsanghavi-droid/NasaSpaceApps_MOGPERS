// Loads every contract file from web/data/ first, falling back to web/mock/.
// Records where each file came from so the UI can show a MOCK DATA banner.

export const FILES = [
  "meta.json", "fields_index.json", "field_types.json", "effects.json", "hero_fields.json",
  "hindcast.json", "climate.json", "policy.json", "signpost.json", "badge_calibration.json", "counties.geojson",
];

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  const ct = res.headers.get("content-type") || "";
  const text = await res.text();
  if (ct.includes("text/html") && text.trimStart().startsWith("<")) throw new Error(`${url}: got HTML`);
  return JSON.parse(text);
}

// Which files exist in web/data/? Avoids a console full of 404s while the real export is pending.
// Uses the directory listing that python -m http.server serves; on hosts without one, every file is probed directly.
async function listDataDir() {
  try {
    const res = await fetch("data/", { cache: "no-cache" });
    if (res.ok && (res.headers.get("content-type") || "").includes("text/html")) {
      const html = await res.text();
      if (/Directory listing/i.test(html)) {
        return new Set([...html.matchAll(/href="([^"?#/]+)"/g)].map((m) => decodeURIComponent(m[1])));
      }
    }
  } catch (_) { /* fall through */ }
  return null;
}

export async function loadAll() {
  const data = {};
  const source = {};
  const present = await listDataDir();
  await Promise.all(FILES.map(async (f) => {
    const key = f.replace(/\.(json|geojson)$/, "");
    try {
      if (present && !present.has(f)) throw new Error("not exported");
      data[key] = await fetchJson(`data/${f}`);
      source[key] = "data";
      // A file exported to data/ but still flagged mock counts as mock.
      if (data[key] && !Array.isArray(data[key]) && data[key].mock === true) source[key] = "mock";
    } catch (e1) {
      try {
        data[key] = await fetchJson(`mock/${f}`);
        source[key] = "mock";
      } catch (e2) {
        data[key] = null;
        source[key] = "missing";
        console.warn(`[counterfield] ${f} unavailable in data/ and mock/`);
      }
    }
  }));
  return { data, source };
}

// fields_index is columnar; turn it into objects keyed by field_id
export function indexFields(fi) {
  const byId = new Map();
  if (!fi || !Array.isArray(fi.columns) || !Array.isArray(fi.rows)) return byId;
  const ix = Object.fromEntries(fi.columns.map((c, i) => [c, i]));
  for (const row of fi.rows) {
    const f = {};
    for (const c of fi.columns) f[c] = row[ix[c]];
    if (f.field_id != null && typeof f.lon === "number" && typeof f.lat === "number") byId.set(f.field_id, f);
  }
  return byId;
}
