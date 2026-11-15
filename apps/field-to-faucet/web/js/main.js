// Entry point: loads data in groups, renders views, hash routing (#city, #farmer, #farmer/<field_id>, #method).
// First paint: the hero, KPIs and replay slider render from meta/facts/scenarios; the river chart, outlook and method
// tables follow when river_series/validation/outlook arrive.
import { createStore, ensure, onLoaded, renderBanner } from "./data.js";
import { initCityMap, renderCity, renderCityRiver } from "./city.js";
import { initFarmer, initFarmMap, selectField, showFieldNotFound } from "./farmer.js";
import { renderMethod, renderProvenance } from "./method.js";
import { initTips } from "./util.js";

const VIEWS = ["city", "farmer", "method"];
let store;
let currentView = null;

function parseHash() {
  const h = decodeURIComponent(location.hash.replace(/^#/, ""));
  const [view, arg] = h.split("/");
  return { view: VIEWS.includes(view) ? view : "city", arg };
}

function show(view) {
  for (const sec of document.querySelectorAll(".view")) sec.hidden = sec.dataset.view !== view;
  for (const a of document.querySelectorAll(".tabs a")) a.setAttribute("aria-selected", String(a.dataset.view === view));
  if (view !== currentView) window.scrollTo(0, 0);
  currentView = view;
  if (view === "city") initCityMap();
  if (view === "farmer") initFarmMap(onSelectField);
}

function onSelectField(id) {
  history.replaceState(null, "", `#farmer/${encodeURIComponent(id)}`);
  if (currentView !== "farmer") show("farmer");
  selectField(id).then((ok) => {
    if (ok) document.getElementById("field-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    else showFieldNotFound(id);
  });
}

async function route() {
  const { view, arg } = parseHash();
  show(view);
  if (view === "farmer" && arg) {
    const ok = await selectField(arg);
    if (!ok) showFieldNotFound(arg);
  }
}

// The vendored libraries are plain scripts; if one failed to load, say so instead of throwing later.
function checkLibs() {
  const missing = [];
  if (typeof window.Chart === "undefined") missing.push("Chart.js (charts)");
  if (typeof window.maplibregl === "undefined") missing.push("MapLibre GL (maps)");
  const b = document.getElementById("lib-banner");
  if (!missing.length) return;
  b.innerHTML = `<strong>Some page parts could not load:</strong> ${missing.join(", ")}. Numbers and text still work; reload the page to try again.`;
  b.hidden = false;
}

async function main() {
  checkLibs();
  initTips();
  store = await createStore();
  onLoaded(store, () => { renderBanner(store.source); renderProvenance(store); });
  renderBanner(store.source);
  renderCity(store);
  initFarmer(store, onSelectField);
  window.addEventListener("hashchange", route);
  await route();
  // River chart, outlook and method tables next; then map layers (city map + hotspot list); farm data waits until
  // the farmer view opens.
  ensure(store, "river").then(() => { renderCityRiver(); renderMethod(store); });
  ensure(store, "map");
}

main();
