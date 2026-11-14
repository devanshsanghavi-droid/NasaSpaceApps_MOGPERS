// Main MapLibre map: county outlines, field samples, hero fields, twin highlight; plus the small analog inset map.
import { cssVar, strategyColor, typeColor, BADGE_VARS, isDark, esc } from "./util.js";

const STYLE_LIGHT = "https://tiles.openfreemap.org/styles/positron";
const STYLE_DARK = "https://tiles.openfreemap.org/styles/dark";
const FONT = ["Noto Sans Regular"];

export class FieldMap {
  constructor(container, opts) {
    this.opts = opts; // { onSelect(field_id), describe(field_id) -> html, bounds }
    this.fieldsGeo = { type: "FeatureCollection", features: [] };
    this.countiesGeo = null;
    this.heroGeo = { type: "FeatureCollection", features: [] };
    this.twinGeo = { type: "FeatureCollection", features: [] };
    this.twinLines = { type: "FeatureCollection", features: [] };
    this.selectedGeo = { type: "FeatureCollection", features: [] };
    this.colorBy = "strategy";
    this.typeOrder = [];
    this.emphasisType = null;
    this.ready = false;
    this.map = new maplibregl.Map({
      container, style: isDark() ? STYLE_DARK : STYLE_LIGHT,
      bounds: opts.bounds, fitBoundsOptions: { padding: 24 }, attributionControl: { compact: true },
      dragRotate: false, pitchWithRotate: false,
    });
    this.map.touchZoomRotate.disableRotation();
    blankMissingImages(this.map);
    this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    this.popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
    this.map.on("style.load", () => { this._addLayers(); this.ready = true; this.refreshColors(); });
    this.map.on("error", (e) => {
      const msg = String(e?.error?.message || "");
      if (msg && !/Failed to fetch|NetworkError|AbortError/.test(msg)) console.warn("[map]", msg);
    });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      this.ready = false;
      this.map.setStyle(isDark() ? STYLE_DARK : STYLE_LIGHT);
    });
    this._bindEvents();
  }

  setData({ fieldsGeo, countiesGeo, heroGeo, typeOrder }) {
    this.fieldsGeo = fieldsGeo;
    this.countiesGeo = countiesGeo;
    this.heroGeo = heroGeo;
    this.typeOrder = typeOrder;
    if (this.ready) this._syncSources();
  }

  updateFieldProps(fieldsGeo) {
    this.fieldsGeo = fieldsGeo;
    const src = this.ready && this.map.getSource("fields");
    if (src) src.setData(fieldsGeo);
  }

  _syncSources() {
    const set = (id, d) => { const s = this.map.getSource(id); if (s && d) s.setData(d); };
    set("fields", this.fieldsGeo);
    set("counties", this.countiesGeo || { type: "FeatureCollection", features: [] });
    set("heroes", this.heroGeo);
    set("twins", this.twinGeo);
    set("twin-lines", this.twinLines);
    set("selected", this.selectedGeo);
  }

  _addLayers() {
    const m = this.map;
    const empty = { type: "FeatureCollection", features: [] };
    const add = (id, data) => { if (!m.getSource(id)) m.addSource(id, { type: "geojson", data: data || empty }); };
    add("counties", this.countiesGeo);
    add("fields", this.fieldsGeo);
    add("heroes", this.heroGeo);
    add("twins", this.twinGeo);
    add("twin-lines", this.twinLines);
    add("selected", this.selectedGeo);
    const ink = cssVar("--ink"), muted = cssVar("--muted"), ground = cssVar("--ground"), accent = cssVar("--accent");

    m.addLayer({ id: "counties-line", type: "line", source: "counties", paint: { "line-color": muted, "line-width": 1, "line-opacity": 0.7 } });
    m.addLayer({ id: "counties-label", type: "symbol", source: "counties",
      layout: { "text-field": ["get", "name"], "text-font": FONT, "text-size": 12, "text-transform": "uppercase", "text-letter-spacing": 0.1 },
      paint: { "text-color": muted, "text-halo-color": ground, "text-halo-width": 1.5 } });
    m.addLayer({ id: "fields", type: "circle", source: "fields",
      paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 1.3, 9, 2.2, 11, 4, 13, 7], "circle-color": "#888", "circle-opacity": 0.85,
        "circle-stroke-width": 0, "circle-stroke-color": "#888" } });
    m.addLayer({ id: "fields-hit", type: "circle", source: "fields", paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4, 11, 8, 13, 10], "circle-opacity": 0 } });
    m.addLayer({ id: "twin-lines", type: "line", source: "twin-lines", paint: { "line-color": accent, "line-width": 1.2, "line-dasharray": [2, 2], "line-opacity": 0.9 } });
    m.addLayer({ id: "twins", type: "circle", source: "twins",
      paint: { "circle-radius": 6, "circle-color": ground, "circle-opacity": 0.2, "circle-stroke-color": accent, "circle-stroke-width": 2 } });
    m.addLayer({ id: "heroes", type: "circle", source: "heroes",
      paint: { "circle-radius": 7, "circle-color": ink, "circle-stroke-color": ground, "circle-stroke-width": 2 } });
    m.addLayer({ id: "hero-labels", type: "symbol", source: "heroes",
      layout: { "text-field": ["get", "name"], "text-font": FONT, "text-size": 12, "text-offset": [0, 1.3], "text-anchor": "top", "text-max-width": 12 },
      paint: { "text-color": ink, "text-halo-color": ground, "text-halo-width": 2 } });
    m.addLayer({ id: "selected", type: "circle", source: "selected",
      paint: { "circle-radius": 10, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": accent, "circle-stroke-width": 3 } });
  }

  _bindEvents() {
    const m = this.map;
    const pick = (e) => {
      const feats = m.queryRenderedFeatures(e.point, { layers: ["heroes", "fields-hit"].filter((l) => m.getLayer(l)) });
      return feats.length ? feats[0].properties.id : null;
    };
    m.on("click", (e) => { const id = pick(e); if (id) this.opts.onSelect(id); });
    m.on("mousemove", (e) => {
      if (!this.ready) return;
      const id = pick(e);
      m.getCanvas().style.cursor = id ? "pointer" : "";
      if (id) this.popup.setLngLat(e.lngLat).setHTML(this.opts.describe(id)).addTo(m);
      else this.popup.remove();
    });
    m.on("mouseout", () => this.popup.remove());
  }

  setColorBy(mode) { this.colorBy = mode; this.refreshColors(); }
  setEmphasisType(typeId) { this.emphasisType = typeId; this.refreshColors(); }

  colorExpr() {
    if (this.colorBy === "type") {
      const e = ["match", ["get", "t"]];
      this.typeOrder.forEach((t) => e.push(t, typeColor(t, this.typeOrder)));
      e.push(cssVar("--s0"));
      return e;
    }
    if (this.colorBy === "badge") {
      return ["match", ["get", "b"], "strong", cssVar(BADGE_VARS.strong), "moderate", cssVar(BADGE_VARS.moderate),
        "thin", cssVar(BADGE_VARS.thin), cssVar(BADGE_VARS.beyond)];
    }
    return ["match", ["get", "s"], "S0", strategyColor("S0"), "S1", strategyColor("S1"), "S2", strategyColor("S2"), "S3", strategyColor("S3"), strategyColor("S0")];
  }

  refreshColors() {
    if (!this.ready || !this.map.getLayer("fields")) return;
    const m = this.map;
    const c = this.colorExpr();
    m.setPaintProperty("fields", "circle-color", c);
    // "Beyond evidence" is drawn hollow in evidence mode so it never relies on colour alone.
    const hollow = this.colorBy === "badge" ? ["==", ["get", "b"], "beyond"] : false;
    const base = this.emphasisType ? ["case", ["==", ["get", "t"], this.emphasisType], 0.95, 0.18] : 0.85;
    m.setPaintProperty("fields", "circle-opacity", this.colorBy === "badge" ? ["case", hollow, 0, base] : base);
    m.setPaintProperty("fields", "circle-stroke-width", this.colorBy === "badge" ? ["case", hollow, 1, 0] : 0);
    m.setPaintProperty("fields", "circle-stroke-color", cssVar(BADGE_VARS.beyond));
    m.setPaintProperty("fields", "circle-stroke-opacity", this.emphasisType ? ["case", ["==", ["get", "t"], this.emphasisType], 1, 0.3] : 1);
  }

  select(field) {
    this.selectedGeo = { type: "FeatureCollection", features: field ? [pt(field.lon, field.lat, { id: field.field_id })] : [] };
    if (this.ready) this.map.getSource("selected")?.setData(this.selectedGeo);
  }

  showTwins(hero, twins) {
    this.twinGeo = { type: "FeatureCollection", features: twins.map((f) => pt(f.lon, f.lat, { id: f.field_id })) };
    this.twinLines = { type: "FeatureCollection", features: hero ? twins.map((f) => ({ type: "Feature", properties: {},
      geometry: { type: "LineString", coordinates: [[hero.lon, hero.lat], [f.lon, f.lat]] } })) : [] };
    if (this.ready) { this.map.getSource("twins")?.setData(this.twinGeo); this.map.getSource("twin-lines")?.setData(this.twinLines); }
    if (hero && twins.length) {
      const b = new maplibregl.LngLatBounds([hero.lon, hero.lat], [hero.lon, hero.lat]);
      twins.forEach((f) => b.extend([f.lon, f.lat]));
      this.map.fitBounds(b, { padding: 90, maxZoom: 12, duration: 900 });
    }
  }

  flyTo(field, zoom = 11.5) { this.map.flyTo({ center: [field.lon, field.lat], zoom: Math.max(this.map.getZoom(), zoom), duration: 900 }); }
  resize() { this.map.resize(); }
}

// The OpenFreeMap styles reference a few POI sprites that are not shipped; fill them with a transparent pixel.
function blankMissingImages(map) {
  map.on("styleimagemissing", (e) => { if (!map.hasImage(e.id)) map.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) }); });
}

export function pt(lon, lat, props) { return { type: "Feature", properties: props, geometry: { type: "Point", coordinates: [lon, lat] } }; }

// ---------------- analog inset (created once, moved into the panel each render) ----------------
export class AnalogMap {
  constructor(tileCenter) {
    this.node = document.createElement("div");
    this.node.id = "analog-map";
    this.tileCenter = tileCenter;
    this.map = null;
    this.analogs = [];
    this.visible = false;
  }
  mount(parent, analogs, visible) {
    parent.appendChild(this.node);
    this.analogs = analogs || [];
    this.visible = visible;
    if (!this.map) {
      const pts = [this.tileCenter, ...this.analogs.filter((a) => typeof a.lon === "number").map((a) => [a.lon, a.lat])];
      const b = pts.reduce((acc, p) => acc.extend(p), new maplibregl.LngLatBounds(pts[0], pts[0]));
      this.map = new maplibregl.Map({ container: this.node, style: isDark() ? STYLE_DARK : STYLE_LIGHT, bounds: b,
        fitBoundsOptions: { padding: 18, maxZoom: 6 }, interactive: false, attributionControl: false });
      blankMissingImages(this.map);
      this.map.on("style.load", () => this._layers());
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => this.map.setStyle(isDark() ? STYLE_DARK : STYLE_LIGHT));
    } else {
      this.map.resize();
      this._update();
    }
  }
  _geo() {
    return { type: "FeatureCollection", features: this.visible ? this.analogs.filter((a) => typeof a.lon === "number").map((a, i) => pt(a.lon, a.lat, { i: i + 1 })) : [] };
  }
  _layers() {
    const m = this.map;
    m.addSource("tile", { type: "geojson", data: { type: "FeatureCollection", features: [pt(this.tileCenter[0], this.tileCenter[1], {})] } });
    m.addSource("analogs", { type: "geojson", data: this._geo() });
    m.addLayer({ id: "analogs", type: "circle", source: "analogs", paint: { "circle-radius": 4, "circle-color": cssVar("--accent"), "circle-stroke-color": cssVar("--ground"), "circle-stroke-width": 1 } });
    m.addLayer({ id: "tile", type: "circle", source: "tile", paint: { "circle-radius": 6, "circle-color": cssVar("--ink"), "circle-stroke-color": cssVar("--ground"), "circle-stroke-width": 2 } });
  }
  _update() { const s = this.map?.getSource("analogs"); if (s) s.setData(this._geo()); }
}

export function describeFieldHtml(f, typeLabel) {
  return `<strong>${esc(typeLabel || f.type_id)}</strong><br>${esc(f.county || "")} County · ${esc(f.field_id)}`;
}
