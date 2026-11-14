// Entry point: loads data, renders views, hash routing (#city, #farmer, #farmer/<field_id>, #method).
import { loadAll, renderBanner } from "./data.js";
import { initCityMap, renderCity } from "./city.js";
import { initFarmer, initFarmMap, selectField } from "./farmer.js";
import { renderMethod } from "./method.js";

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
  selectField(id).then((ok) => { if (ok) document.getElementById("field-panel").scrollIntoView({ behavior: "smooth", block: "start" }); });
}

async function route() {
  const { view, arg } = parseHash();
  show(view);
  if (view === "farmer" && arg) await selectField(arg);
}

async function main() {
  store = await loadAll();
  renderBanner(store.source);
  renderCity(store);
  initFarmer(store, onSelectField);
  renderMethod(store);
  window.addEventListener("hashchange", route);
  await route();
}

main();
