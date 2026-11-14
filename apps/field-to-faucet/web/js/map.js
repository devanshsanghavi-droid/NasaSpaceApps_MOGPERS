// MapLibre maps drawn only from our own GeoJSON: no external tiles, no glyphs (labels are HTML markers).
/* global maplibregl */
import { cssVar, esc, isNum } from "./util.js";

const BLANK_STYLE = () => ({
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": cssVar("--mapbg") || "#eef0ec" } }],
});

export function bboxOf(features) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const walk = (c) => {
    if (typeof c[0] === "number") { x0 = Math.min(x0, c[0]); y0 = Math.min(y0, c[1]); x1 = Math.max(x1, c[0]); y1 = Math.max(y1, c[1]); return; }
    c.forEach(walk);
  };
  for (const f of features || []) if (f?.geometry?.coordinates) walk(f.geometry.coordinates);
  return isFinite(x0) ? [[x0, y0], [x1, y1]] : null;
}

// Returns a promise of a loaded map, or null (with a message in the container) if WebGL is unavailable.
export function createMap(container, { bounds, attribution }) {
  return new Promise((resolve) => {
    let map;
    try {
      map = new maplibregl.Map({
        container,
        style: BLANK_STYLE(),
        bounds: bounds || [[-96, 41], [-93, 44]],
        fitBoundsOptions: { padding: 20 },
        attributionControl: { compact: true, customAttribution: attribution || "Boundaries: USGS WBD" },
        dragRotate: false,
        pitchWithRotate: false,
        cooperativeGestures: false,
        maxZoom: 15,
      });
    } catch (e) {
      container.innerHTML = `<div class="map-msg">The map needs WebGL, which this browser has turned off. The list beside the map shows the same ranking.</div>`;
      resolve(null);
      return;
    }
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => resolve(map));
    map.on("error", (e) => {
      // Never let a map problem reach the console as an uncaught error; show it in the UI instead.
      const msg = e?.error?.message || "map error";
      if (!container.querySelector(".map-msg")) container.insertAdjacentHTML("beforeend", `<div class="map-msg" style="pointer-events:none;align-items:end">${esc(msg)}</div>`);
    });
  });
}

// HTML label marker (no glyph server needed)
export function addLabel(map, lngLat, text, cls = "", anchor = "bottom") {
  const node = document.createElement("div");
  node.className = `place-label ${cls} anchor-${anchor}`;
  node.textContent = text;
  // MapLibre positions markers with an inline transform, so offsets go through the marker, not CSS.
  const offset = { bottom: [0, -8], top: [0, 6], left: [10, 0], right: [-10, 0] }[anchor] || [0, 0];
  return new maplibregl.Marker({ element: node, anchor, offset: cls.includes("huc") ? [0, 0] : offset }).setLngLat(lngLat).addTo(map);
}

export function addContext(map, data, { basinsOutline = true } = {}) {
  if (data.counties?.features?.length) {
    map.addSource("counties", { type: "geojson", data: data.counties });
    map.addLayer({ id: "counties-line", type: "line", source: "counties", paint: { "line-color": "#c9c6bd", "line-width": 0.6 } });
  }
  if (basinsOutline && data.basins?.features?.length) {
    map.addSource("basins", { type: "geojson", data: data.basins });
    map.addLayer({ id: "basins-line", type: "line", source: "basins", paint: { "line-color": cssVar("--ink"), "line-width": 1.6 } });
  }
}

export function addRivers(map, rivers) {
  if (!rivers?.features?.length) return;
  map.addSource("rivers", { type: "geojson", data: rivers });
  map.addLayer({
    id: "rivers-line", type: "line", source: "rivers",
    paint: {
      "line-color": "#3c7fb1",
      "line-width": ["interpolate", ["linear"], ["coalesce", ["to-number", ["get", "order"]], 4], 3, 0.8, 7, 2.6],
      "line-opacity": 0.85,
    },
  });
}

export function addSites(map, sites) {
  if (!Array.isArray(sites) || !sites.length) return;
  const fc = { type: "FeatureCollection", features: sites.filter((s) => isNum(s.lon) && isNum(s.lat)).map((s) => ({ type: "Feature", properties: { site: s.site, name: s.name }, geometry: { type: "Point", coordinates: [s.lon, s.lat] } })) };
  map.addSource("sites", { type: "geojson", data: fc });
  map.addLayer({ id: "sites-c", type: "circle", source: "sites", paint: { "circle-radius": 6, "circle-color": cssVar("--ink"), "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
  // The two intakes are ~30 km apart: put the western label to the left of its dot and the eastern one to the right.
  const lons = fc.features.map((f) => f.geometry.coordinates[0]);
  const mid = (Math.min(...lons) + Math.max(...lons)) / 2;
  for (const s of fc.features) {
    const river = String(s.properties.name).split(",")[0].replace(/ at .*/, "");
    const west = fc.features.length > 1 && s.geometry.coordinates[0] < mid;
    addLabel(map, s.geometry.coordinates, `${river} intake`, "site", west ? "right" : "left");
  }
}

export function addPlaces(map, places, { exclude = [], townMinZoom = 0 } = {}) {
  if (!Array.isArray(places)) return;
  const towns = [];
  for (const p of places) {
    if (!isNum(p.lon) || !isNum(p.lat) || exclude.includes(p.name) || p.kind === "intake") continue;
    const m = addLabel(map, [p.lon, p.lat], p.name, p.kind === "city" ? "city" : "", p.kind === "city" ? "top" : "bottom");
    if (p.kind !== "city") towns.push(m);
  }
  if (townMinZoom > 0 && towns.length) {
    const upd = () => { const show = map.getZoom() >= townMinZoom; towns.forEach((m) => { m.getElement().style.display = show ? "" : "none"; }); };
    map.on("zoomend", upd);
    upd();
  }
}

// Quantile class breaks for n classes
export function quantileBreaks(values, n) {
  const v = values.filter(isNum).sort((a, b) => a - b);
  if (!v.length) return [];
  const out = [];
  for (let i = 1; i < n; i++) out.push(v[Math.min(v.length - 1, Math.floor((i / n) * v.length))]);
  return out;
}

// MapLibre "step" expression from breaks + ramp
export function stepExpr(prop, breaks, ramp, fallback = "#dddddd") {
  const expr = ["step", ["coalesce", ["to-number", ["get", prop]], -1e9], fallback, -1e8, ramp[0]];
  let last = -1e8;
  breaks.forEach((b, i) => { if (isNum(b) && b > last) { expr.push(b, ramp[i + 1]); last = b; } });
  return expr;
}

export function rampLegend(ramp, labels, title) {
  return `<span>${esc(title)}</span><span class="ramp-wrap"><span class="ramp">${ramp.map((c) => `<span style="background:${c}"></span>`).join("")}</span><span class="ramp-labels"><span>${esc(labels[0])}</span><span>${esc(labels[1])}</span></span></span>`;
}
