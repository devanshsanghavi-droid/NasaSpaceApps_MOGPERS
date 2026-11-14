// Data loader. Every contract file is read from web/data/<file>; if it is not there, web/mock/<file> is used
// instead and the file is recorded as MOCK so the red banner can name it. Mock values never go anywhere else.
//
// To avoid 404 noise in the console while the real exports are pending, the loader first reads the directory
// listing that `python3 -m http.server` serves for data/ and the manifest in mock/_manifest.json. On hosts without
// a listing (GitHub Pages) it requests each data file directly.

import { esc } from "./util.js";

export const FILES = [
  "meta.json", "basins.geojson", "huc12.geojson", "rivers.geojson", "sites.json", "places.json",
  "river_series.json", "validation.json", "scenarios.json", "outlook.json", "fields.geojson", "strategies.json",
  "facts.json",
];
// Optional real-only layers: drawn when present, never mocked, never trigger the banner.
const OPTIONAL = ["counties.geojson"];

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

export async function loadAll() {
  const data = {};
  const source = {}; // key -> "data" | "mock" | "partial" | "missing"
  const detail = { mode: "none", source: "missing", split: new Set() };
  const [present, manifest] = await Promise.all([listDir("data"), fetchJson("mock/_manifest.json").catch(() => null)]);
  const mockFiles = new Set(manifest?.files || []);

  async function loadMock(f) {
    if (manifest && !mockFiles.has(f)) throw new Error("no mock");
    return fetchJson(`mock/${f}`);
  }

  await Promise.all([...FILES, ...OPTIONAL].map(async (f) => {
    const key = keyOf(f);
    const optional = OPTIONAL.includes(f);
    try {
      if (present && !present.has(f)) throw new Error("not exported yet");
      data[key] = await fetchJson(`data/${f}`);
      source[key] = data[key] && !Array.isArray(data[key]) && data[key].mock === true ? "mock" : "data";
    } catch (_) {
      if (optional) { data[key] = null; return; }
      try {
        data[key] = await loadMock(f);
        source[key] = "mock";
      } catch (_) {
        data[key] = null;
        source[key] = "missing";
      }
    }
  }));

  // Partial HUC-12: real outlines, mock scores
  const realHuc = source.huc12 === "data" ? data.huc12 : null;
  if (realHuc && Array.isArray(realHuc.features) && realHuc.features.length && !realHuc.features.some((f) => f.properties && f.properties.leak_index != null)) {
    try {
      const mock = await loadMock("huc12.geojson");
      const byId = new Map(mock.features.map((f) => [f.properties.huc12, f.properties]));
      for (const f of realHuc.features) {
        const m = byId.get(f.properties.huc12);
        if (!m) continue;
        for (const k of HUC_SCORE_KEYS) if (f.properties[k] == null || (k === "in_focus" && f.properties[k] === false)) f.properties[k] = m[k];
      }
      source.huc12 = "partial";
    } catch (_) { /* keep outlines only */ }
  }

  // Field detail: one file, or split per HUC-12 (contract allows both). Must come from the same place as fields.
  if (source.fields === "data") {
    if (!present || present.has("field_detail.json")) {
      try { data.field_detail = await fetchJson("data/field_detail.json"); detail.mode = "single"; detail.source = "data"; } catch (_) { /* try split */ }
    }
    if (detail.mode === "none" && (!present || present.has("field_detail/"))) { detail.mode = "split"; detail.source = "data"; detail.base = "data/field_detail/"; }
  } else if (source.fields === "mock" && manifest?.field_detail_split?.length) {
    detail.mode = "split"; detail.source = "mock"; detail.base = "mock/field_detail/";
    detail.split = new Set(manifest.field_detail_split);
  }
  source.field_detail = detail.source;

  return { data, source, detail };
}

const detailCache = new Map();
// Returns the detail record for one field or null.
export async function getFieldDetail(store, fieldId, huc12) {
  const { data, detail } = store;
  if (detail.mode === "single") return data.field_detail?.[fieldId] ?? null;
  if (detail.mode !== "split" || !huc12) return null;
  if (detail.source === "mock" && !detail.split.has(huc12)) return null;
  if (!detailCache.has(huc12)) {
    detailCache.set(huc12, fetchJson(`${detail.base}${huc12}.json`).catch(() => ({})));
  }
  const part = await detailCache.get(huc12);
  return part?.[fieldId] ?? null;
}

const LABELS = {
  meta: "meta.json", basins: "basins.geojson", huc12: "huc12.geojson", rivers: "rivers.geojson", sites: "sites.json", places: "places.json",
  river_series: "river_series.json", validation: "validation.json", scenarios: "scenarios.json", outlook: "outlook.json",
  fields: "fields.geojson", strategies: "strategies.json", facts: "facts.json", field_detail: "field_detail",
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
  if (!keys.length && !missing.length) { b.hidden = true; return; }
  const list = keys.map((k) => `<code>${esc(LABELS[k] || k)}${source[k] === "partial" ? " (leak scores)" : ""}</code>`).join(" ");
  const miss = missing.length ? ` Missing: ${missing.map((k) => `<code>${esc(LABELS[k] || k)}</code>`).join(" ")}.` : "";
  b.innerHTML = `<strong>MOCK DATA — not real.</strong> ${keys.length ? `Placeholder values from <code>web/mock/</code>: ${list}. Do not cite these numbers.` : ""}${miss}`;
  b.hidden = false;
  const setH = () => document.documentElement.style.setProperty("--banner-h", b.offsetHeight + "px");
  setH();
  window.addEventListener("resize", setH);
}

export function provenanceTable(source) {
  const rows = Object.keys(LABELS).map((k) => {
    const s = source[k] || "missing";
    const txt = s === "data" ? "real (web/data)" : s === "partial" ? "outlines real, leak scores MOCK" : s === "mock" ? "MOCK (web/mock)" : "not available";
    return `<tr><td><code>${esc(LABELS[k])}</code></td><td class="${s === "data" ? "src-data" : "src-mock"}">${esc(txt)}</td></tr>`;
  });
  return `<div class="tbl-wrap"><table class="data"><thead><tr><th>File</th><th>Source</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}

// facts.json: {facts:{key:{value,unit,label,source,url,verified}}} or a list of {id|key, ...}
export function factsMap(facts) {
  if (!facts) return {};
  const f = facts.facts ?? facts;
  if (Array.isArray(f)) return Object.fromEntries(f.filter((x) => x && (x.id || x.key)).map((x) => [x.id || x.key, x]));
  return f;
}
