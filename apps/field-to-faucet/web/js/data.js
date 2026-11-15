// Data loader. Every contract file is read from web/data/<file>; if it is not there, web/mock/<file> is used
// instead and the file is recorded as MOCK so the red banner can name it. Mock values never go anywhere else.
//
// Files load in groups so the first view stays light:
//   CORE  (hero text, KPIs, replay slider)                  -> loaded before the first render
//   RIVER (river chart, outlook, method tables)             -> loaded right after the hero is drawn
//   MAP   (HUC-12 hotspots, context layers)                 -> loaded right after the first render
//   FARM  (fields, strategies)                              -> loaded only when the farmer view opens
//   field_index.json + field_detail/<huc12>.json            -> loaded on the first field click
//
// To avoid 404 noise in the console, the loader first reads the directory listing that `python3 -m http.server`
// serves for data/ and the manifest in mock/_manifest.json. On hosts without a listing (GitHub Pages) it requests
// each data file directly.

import { esc } from "./util.js";

export const GROUPS = {
  core: ["meta.json", "facts.json", "scenarios.json", "sites.json"],
  river: ["river_series.json", "validation.json", "outlook.json"],
  map: ["huc12.geojson", "basins.geojson", "rivers.geojson", "places.json"],
  farm: ["fields.geojson", "strategies.json"],
};
export const FILES = [...GROUPS.core, ...GROUPS.river, ...GROUPS.map, ...GROUPS.farm];
// Optional real-only layers: drawn when present, never mocked, never trigger the banner.
const OPTIONAL = ["counties.geojson"];
GROUPS.map.push(...OPTIONAL);

const keyOf = (f) => f.replace(/\.(json|geojson)$/, "");

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  const text = await res.text();
  if (text.trimStart().startsWith("<")) throw new Error(`${url}: got HTML, not JSON`);
  return JSON.parse(text);
}

async function listDir(dir) {
  // GitHub Pages has no listings and would answer 404 (a console error); probe files directly there.
  if (/github\.io$/i.test(location.hostname)) return null;
  try {
    const res = await fetch(`${dir}/`, { cache: "no-cache" });
    if (!res.ok) return null;
    const html = await res.text();
    if (!/Directory listing/i.test(html)) return null;
    return new Set([...html.matchAll(/href="([^"?#]+)"/g)].map((m) => decodeURIComponent(m[1])));
  } catch (_) {
    return null;
  }
}

// HUC-12 leak scores are produced by the model after the outlines exist. If the real file has outlines but no
// scores yet, scores are taken from the mock file (by huc12 id) and the file is reported as partly mock.
const HUC_SCORE_KEYS = ["row_crop_share", "poorly_drained_share", "bare_days_wet", "leak_index", "share_of_basin_leak", "rank", "in_focus"];

// Creates the store and loads the CORE group.
export async function createStore() {
  const [present, manifest] = await Promise.all([listDir("data"), fetchJson("mock/_manifest.json").catch(() => null)]);
  const store = {
    data: {},
    source: {}, // key -> "data" | "mock" | "partial" | "missing" | "pending" (real file present, not loaded yet)
    detail: { mode: "none", source: "missing", split: new Set() },
    present,
    manifest,
    mockFiles: new Set(manifest?.files || []),
    loading: new Map(),
    listeners: [],
  };
  // Pre-classify lazy files from the listing so the banner and provenance table are right before they load.
  // (No listing, e.g. GitHub Pages: assume the real export is there; the banner is re-checked after each load.)
  for (const f of FILES) if (!present || present.has(f)) store.source[keyOf(f)] = "pending";
  if (!present || present.has("field_detail/") || present.has("field_detail.json")) store.source.field_detail = "pending";
  await ensure(store, "core");
  return store;
}

export function onLoaded(store, fn) {
  store.listeners.push(fn);
}

// Loads a group ("core" | "river" | "map" | "farm") once; returns a promise that resolves when it is in store.data.
export function ensure(store, group) {
  if (!store.loading.has(group)) {
    const p = Promise.all(GROUPS[group].map((f) => loadOne(store, f))).then(async () => {
      if (group === "map") await mergeHucScores(store);
      if (group === "farm") setupDetail(store);
      store.listeners.forEach((fn) => fn(group));
    });
    store.loading.set(group, p);
  }
  return store.loading.get(group);
}
export const isLoaded = (store, group) => store.loading.has(group);

async function loadOne(store, f) {
  const { data, source, present, manifest, mockFiles } = store;
  const key = keyOf(f);
  const optional = OPTIONAL.includes(f);
  try {
    if (present && !present.has(f)) throw new Error("not exported yet");
    data[key] = await fetchJson(`data/${f}`);
    source[key] = data[key] && !Array.isArray(data[key]) && data[key].mock === true ? "mock" : "data";
  } catch (_) {
    if (optional) { data[key] = null; delete source[key]; return; }
    try {
      if (manifest && !mockFiles.has(f)) throw new Error("no mock");
      data[key] = await fetchJson(`mock/${f}`);
      source[key] = "mock";
    } catch (_) {
      data[key] = null;
      source[key] = "missing";
    }
  }
}

async function mergeHucScores(store) {
  const { data, source, manifest, mockFiles } = store;
  const realHuc = source.huc12 === "data" ? data.huc12 : null;
  if (!(realHuc && Array.isArray(realHuc.features) && realHuc.features.length && !realHuc.features.some((f) => f.properties && f.properties.leak_index != null))) return;
  try {
    if (manifest && !mockFiles.has("huc12.geojson")) return;
    const mock = await fetchJson("mock/huc12.geojson");
    const byId = new Map(mock.features.map((f) => [f.properties.huc12, f.properties]));
    for (const f of realHuc.features) {
      const m = byId.get(f.properties.huc12);
      if (!m) continue;
      for (const k of HUC_SCORE_KEYS) if (f.properties[k] == null || (k === "in_focus" && f.properties[k] === false)) f.properties[k] = m[k];
    }
    source.huc12 = "partial";
  } catch (_) { /* keep outlines only */ }
}

// Field detail must come from the same place as the fields. Real exports are split per HUC-12
// (field_detail/<huc12>.json + field_index.json); a single field_detail.json is still accepted.
function setupDetail(store) {
  const { source, present, manifest, detail } = store;
  if (source.fields === "data") {
    detail.source = "data";
    detail.base = "data/field_detail/";
    if (present && present.has("field_detail.json") && !present.has("field_detail/")) detail.mode = "single";
    else detail.mode = "split";
    detail.hasIndex = !present || present.has("field_index.json");
  } else if (source.fields === "mock" && manifest?.field_detail_split?.length) {
    detail.mode = "split"; detail.source = "mock"; detail.base = "mock/field_detail/";
    detail.split = new Set(manifest.field_detail_split);
    detail.hasIndex = false;
  } else {
    detail.mode = "none"; detail.source = "missing";
  }
  source.field_detail = detail.source;
}

const detailCache = new Map();
let indexPromise = null;
// Returns the detail record for one field or null. Loads field_index.json and the HUC-12 part on first use.
export async function getFieldDetail(store, fieldId, hucHint) {
  const { data, detail } = store;
  if (detail.mode === "single") {
    if (!data.field_detail) data.field_detail = await fetchJson("data/field_detail.json").catch(() => ({}));
    return data.field_detail?.[fieldId] ?? null;
  }
  if (detail.mode !== "split") return null;
  let huc12 = hucHint;
  if (detail.hasIndex) {
    if (!indexPromise) indexPromise = fetchJson("data/field_index.json").catch(() => null);
    const idx = await indexPromise;
    data.field_index = idx;
    huc12 = idx?.[fieldId] ?? idx?.fields?.[fieldId] ?? hucHint;
  }
  if (!huc12) return null;
  if (detail.source === "mock" && !detail.split.has(huc12)) return null;
  if (!detailCache.has(huc12)) {
    detailCache.set(huc12, fetchJson(`${detail.base}${huc12}.json`).catch(() => {
      // A missing or broken detail file is reported (banner + panel note), never swallowed.
      store.source.field_detail = "missing";
      store.detail.failed = [...(store.detail.failed || []), `${huc12}.json`];
      store.listeners.forEach((fn) => fn("detail"));
      return null;
    }));
  }
  const part = await detailCache.get(huc12);
  if (part === null) return { _missing: `${huc12}.json` };
  return part?.[fieldId] ?? null;
}

const LABELS = {
  meta: "meta.json", facts: "facts.json", scenarios: "scenarios.json", river_series: "river_series.json", validation: "validation.json",
  outlook: "outlook.json", sites: "sites.json", huc12: "huc12.geojson", basins: "basins.geojson", rivers: "rivers.geojson",
  places: "places.json", fields: "fields.geojson", strategies: "strategies.json", field_detail: "field_detail/<huc12>.json",
};

export function mockKeys(source) {
  return Object.entries(source).filter(([, s]) => s === "mock" || s === "partial").map(([k]) => k);
}
export const isMock = (source, key) => source[key] === "mock" || source[key] === "partial";
export const mockChip = (source, ...keys) => (keys.some((k) => isMock(source, k)) ? `<span class="mock-chip" title="This part uses mock data">mock</span>` : "");

export function renderBanner(source) {
  const b = document.getElementById("mock-banner");
  const keys = mockKeys(source);
  const missing = Object.entries(source).filter(([, s]) => s === "missing").map(([k]) => k);
  b.classList.toggle("warn", !keys.length);
  if (!keys.length && !missing.length) { b.hidden = true; b.innerHTML = ""; document.documentElement.style.setProperty("--banner-h", "0px"); return; }
  const list = keys.map((k) => `<code>${esc(LABELS[k] || k)}${source[k] === "partial" ? " (leak scores)" : ""}</code>`).join(" ");
  const miss = missing.length ? ` Missing: ${missing.map((k) => `<code>${esc(LABELS[k] || k)}</code>`).join(" ")}.` : "";
  b.innerHTML = keys.length ? `<strong>MOCK DATA — not real.</strong> Placeholder values from <code>web/mock/</code>: ${list}. Do not cite these numbers.${miss}` : `<strong>Some data is missing.</strong>${miss}`;
  b.hidden = false;
  const setH = () => document.documentElement.style.setProperty("--banner-h", b.offsetHeight + "px");
  setH();
  if (!renderBanner.bound) { renderBanner.bound = true; window.addEventListener("resize", setH); }
}

export function provenanceTable(source) {
  const rows = Object.keys(LABELS).map((k) => {
    const s = source[k] || "missing";
    const txt = s === "data" ? "real (web/data)" : s === "pending" ? "real (web/data), loads when its view opens" : s === "partial" ? "outlines real, leak scores MOCK" : s === "mock" ? "MOCK (web/mock)" : "not available";
    return `<tr><td><code>${esc(LABELS[k])}</code></td><td class="${s === "data" || s === "pending" ? "src-data" : "src-mock"}">${esc(txt)}</td></tr>`;
  });
  return `<div class="tbl-wrap"><table class="data"><thead><tr><th>File</th><th>Source</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}

// facts.json: {facts:{id:{value,unit,label,source,url,verified}}, aliases:{key:id}} or a list of {id|key, ...}.
// Alias keys (people_served, plant_days_<Y>, ban_days_<Y>, ...) resolve to the original ids.
export function factsMap(facts) {
  if (!facts) return {};
  const f = facts.facts ?? facts;
  const map = Array.isArray(f) ? Object.fromEntries(f.filter((x) => x && (x.id || x.key)).map((x) => [x.id || x.key, x])) : { ...f };
  for (const [alias, id] of Object.entries(facts.aliases || {})) if (map[id] && !map[alias]) map[alias] = map[id];
  return map;
}

// "What NASA sees": the NASA sources in meta.json, matched by name.
export const NASA_ITEMS = [
  { re: /HLS/i, label: "HLS (Landsat + Sentinel-2)", what: "bare soil vs living cover on every 40-acre field", through: "hls" },
  { re: /MODIS/i, label: "MODIS", what: "share of watershed cropland left bare, every 8 days", through: "modis" },
  { re: /POWER/i, label: "NASA POWER", what: "rain and root-zone soil wetness (GWETROOT)", through: "power" },
  { re: /IMERG/i, label: "GPM IMERG", what: "satellite rainfall that validated storm days, 2016–21" },
  { re: /NASADEM/i, label: "NASADEM", what: "slope of every field and sub-watershed" },
];
export function nasaStrip(meta, { compact = false } = {}) {
  const src = meta?.sources || [];
  const thr = meta?.data_through || {};
  const items = NASA_ITEMS.map((it) => ({ ...it, s: src.find((s) => s.nasa && it.re.test(s.name)) })).filter((x) => x.s);
  if (!items.length) return "";
  const fmtThrough = (d) => {
    if (!d) return "";
    const m = /^(\d{4})-(\d{2})/.exec(d);
    return m ? `to ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m[2]) - 1]} ${m[1]}` : "";
  };
  return `<div class="nasa-strip${compact ? " compact" : ""}" role="list" aria-label="NASA data used">
    <div class="nasa-strip-h"><span class="nasa">NASA</span> What NASA sees</div>
    ${items.map((x) => `<div class="nasa-item" role="listitem" title="${esc(x.s.role || "")}"><a href="${esc(x.s.url)}" target="_blank" rel="noopener">${esc(x.label)}</a><span>${esc(x.what)}${x.through && thr[x.through] ? ` <em>${esc(fmtThrough(thr[x.through]))}</em>` : ""}</span></div>`).join("")}
  </div>`;
}
