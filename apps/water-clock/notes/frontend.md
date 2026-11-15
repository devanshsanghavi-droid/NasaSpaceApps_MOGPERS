# Frontend (web) notes

Static app in `apps/water-clock/web/`. No build step: ES modules + two pinned CDN libraries.
Run with `cd apps/water-clock/web && python3 -m http.server 8000` and open http://localhost:8000/.

## Structure
| Path | Role |
|---|---|
| `index.html` | Layout: MOCK banner, header with the region clock, 4 tabs (My field, My county, From space, Proof & data), shared map + side panel |
| `css/style.css` | All styles; phone layout below 900px / 480px |
| `js/app.js` | Entry: library fallback, data load, state, tabs (arrow-key navigation), threshold radios, county search, URL hash (`#farmer/field/<id>`, `#community/county/<fips>`) |
| `js/data.js` | Loads every `web/data/<file>`; if missing, loads `web/mock/mock_<file>` and records it (drives the banner); builds lookups |
| `js/scenario.js` | All client-side clock arithmetic (thresholds, years gained, community slider) |
| `js/map.js` | MapLibre map: counties coloured by years left, optional grid layer, clickable field dots |
| `js/clock.js` | The SVG clock gauge and plain-language uncertainty text |
| `js/farmer.js` | "Your Water Clock" (field or county) + strategy cards + priority slider |
| `js/community.js` | GMD cards, sortable county table, "if X% of corn shifts" slider, county context |
| `js/grace.js` | GRACE chart (Chart.js), canvas heatmap of GRACE maps, wells-vs-GRACE numbers |
| `js/validation.js` | Hindcast tables (generic renderer), 2045 climate cards, data sources with NASA badges, caveats |
| `js/util.js` | Formatting, range text, colour bins (<10, 10-25, 25-50, 50-100, 100+ years) |
| `mock/make_mock.py` + `mock/mock_*.json` | Shape-only fake fixtures (round numbers, schematic box counties, names suffixed "(MOCK)") |
| `tests/smoke.js` | Playwright smoke test (desktop 1366px + phone 375px) |
| `screenshots/` | Screenshots from the smoke test, re-taken on the real web/data (no MOCK banner), desktop 1366px + phone 375px |

Libraries: `maplibre-gl@4.7.1` (unpkg, falls back to jsdelivr) and `chart.js@4.4.4` `dist/chart.umd.js` (jsdelivr, falls back to unpkg).
Basemap: `https://tiles.openfreemap.org/styles/positron` is fetched first (5 s timeout); if that fails, a plain background style
with only the county GeoJSON is used and a small note says so. No API keys.

## Mock rule
The app always requests `data/<file>` first. Only on failure does it read `mock/mock_<file>`, and then a red sticky
"MOCK DATA" banner lists the files that came from mock. Nothing in `web/data/` comes from this module. Once the model writes
all ten files the banner disappears on its own. While files are missing, Chrome logs one "Failed to load resource: 404" per
missing file; that goes away once the real files exist (no other console errors in the tests).

## Data binding (web/data/*.json, contract in CONTRACTS.md "Model outputs")
All ten files are optional in the sense that a missing one shows "not available" (or mock + banner) instead of crashing.
For a real demo, all are needed:
- `county_clocks.json` (core): header clock, county clock, community list, GMD cards, map colours at 15/30/50 ft.
  Header: uses `region.years_left` if the model adds an optional `region` object; otherwise an irrigated-acre-weighted
  average of county p10/p50/p90 (labelled as such). Optional extra county keys shown if present: `population`, `main_towns`,
  `towns`, `ag_share_of_economy`, `econ_note`, plus `town_note`.
- `counties.geojson`: map polygons; `properties.fips` must be a 5-char string matching county_clocks. Names come from
  county_clocks, then the GeoJSON.
- `fields.json` (core): columnar `{columns, rows}`; uses id, lon, lat, fips, acres, crop, af_yr, sat_ft, decl, y10, y50, y90.
- `grid.json`: rows `[lon, lat, sat_ft, decl_ft_yr, years_p50]`, drawn as squares of `cell_deg` (toggle "Show detailed grid").
- `strategies.json` (core): cards use name, short, rotation, irrigation (full|limited|none), why, evidence[{text,source,url}],
  benefits, gaps, risks, soil_health, water_in_ac, pumping_change_pct (percent, negative = less pumping), income_usd_ac,
  yield_risk, applies_where, plus `method`. `per_county[fips][Sk].net_pumping_in_ac / income_usd_ac` replace the central
  estimate for that county (the strategy-level lo/hi spread is kept around it). `S0` must be the current practice.
- `scenario.json` (core for the slider): accepts `{counties:{fips:{...}}}`, `{counties:[{fips,...}]}` or `{fips:{...}}`.
  Keys: sat_avail_ft (number or `{"15":..,"30":..,"50":..}`), decline_ft_yr (number or {est,lo,hi}),
  decline_from_pumping_ft_yr, irrigated_corn_acres, irrigated_acres, pumping_af_yr, ft_per_af_ac; `formula` text is shown verbatim.
- `grace.json`: `series.dates` + `series.gws_pct` (+ `tws_cm` or null); `maps` = {cell_deg, bbox [W,S,E,N], dates, gws_pct, tws_trend_cm_yr}.
  `maps.gws_pct` may be dates x rows x cols, dates x flat(rows*cols), or a single rows x cols grid. **Row 0 is assumed to be
  the north edge** unless `maps.lats` is ascending or `maps.row_order == "south_up"`. `wells_vs_grace.well_storage_anom_series`
  may be `{dates, cm}`, `{years, values}`, `[{date, cm}]` or `[[date, cm]]`. Numbers: correlation, trend_wells_cm_yr, trend_grace_cm_yr, notes.
- `validation.json`: rendered generically: scalars as key/value, and any object whose children share metric keys
  (e.g. `{model:{mae..}, baseline_no_change:{mae..}}`) as a table, with rows named *model* highlighted. `grace_vs_wells` gets its own block.
- `climate.json`: scenarios found under `scenarios` or at top level (objects containing `et0_change_pct` or `clock_shift_years`);
  values may be numbers or {est,lo,hi}; `clock_shift_years` may be a number, a range, or `{region, county:{fips:..}}`.
  Optional `baseline`, `future`, `models` strings.
- `meta.json`: `region` (header subtitle), `generated_at`, `data_sources[{name,nasa,role,url,status}]`, `caveats`.

## Client-side formulas (js/scenario.js)
- Field years at a threshold T other than 30 ft: read from fields.json `y10_15..y90_50` (the model's Monte Carlo at 15 and 50 ft;
  final fix pass). Fallback for older files: scale by (sat_ft - T)/(sat_ft - 30), but a capped 100+ at a stricter threshold becomes
  min(100, (sat_ft - T)/decl) and a p10 of 0 at a looser threshold becomes unknown. If sat_ft <= T: "already below".
- Strategies are only shown/offered where assessed: a strategy is dropped for a county when `s.counties` is a list that
  does not contain it, or when `per_county[fips]` exists but has no entry for it (S4 cotton = 7 southern counties).
- Years gained for a strategy at a field: p = fractional pumping change vs S0 (county net pumping if present, else
  pumping_change_pct/100). The strategy-level lo/hi spread is scaled proportionally to the county estimate
  (lo_local = local * lo/est), and for a water-saving strategy the upper bound of p is clamped to <= 0, so a plan that
  pumps less never shows negative years. share = scenario `pumping_share` (else decline_from_pumping / decline; 1 if missing).
  raw = scenario `pumping_share_raw` (uncapped; > 1 means net inflow, so the decline responds more than proportionally).
  Computed at Y = field p50 only (final fix pass; the old p10/p90 combinations made the range an artefact of the 100-year cap):
  est = Y/(1 + share*p_est) - Y; lo = same with the smallest cut; hi = Y/(1 + raw*p_lo) - Y. Already below / Y <= 0 -> no gain (null);
  Y at the cap -> "already 100+". "Best fit" = top priority-weighted score among plans keeping >= (1 - priority) of S0 income,
  normalised over the alternative plans only; no badge when no plan has a gain.
  The UI states that this assumes all irrigated land around the field (every crop) makes the same change, unlike the corn-only slider.
- Community slider: saved_af = X * irrigated_corn_acres * (net_S0 - net_Sk)/12; new_decline = decline -
  decline_from_pumping * saved_af / pumping_af_yr (fallback: decline - ft_per_af_ac * saved_af / irrigated_acres);
  years = sat_avail_ft[T] / decline (cap 100); Z = years(new) - years(old). Range from decline lo/hi; the net-inflow reading
  (decline_from_pumping_ft_yr_net_inflow) is shown as a second, higher gain. Default county: Gray (20069); slider above the table.
  If `median_below_threshold[T]` is true the slider shows `median_below_threshold_note[T]` instead of numbers; if the
  strategy is not assessed for the county, or would use more water than corn there, it shows an error, never a negative saving.
- Already below: county clocks use `countyYears(c, thr, D)`, which sets `below` from scenario `median_below_threshold[T]`
  (or sat_thick p50 <= T when the flag is absent); the clock then says "Already below T ft" and years gained are not shown.
- Ranges with p10 = 0 and p90 = 100+ are shown as "very uncertain here" (the model's Monte Carlo spreads many counties and
  ~900 fields that wide); a p10 of 0 alone is phrased "parts of this area may already be below T ft".
- GRACE chart: cm series (GFZ TWS, G3P groundwater, wells storage) are each centred on their own 2003-2026 mean before
  plotting (the files use different reference levels); the chart says so. The storage-trend map layer reads
  `maps.tws_trend_cm_yr` as its own 1-degree grid ({cell_deg, lat, lon, bbox, <period>: rows}) with a period picker.
  **If the model's `scenario.formula` differs, js/scenario.js `countyShift` must be updated to match.**
- Priority slider: score = w * normalised(years gained) + (1 - w) * normalised(income); the best non-current strategy gets the
  "Best fit for your priorities" badge and cards re-order (current practice always first).

## Testing
`node tests/smoke.js` with `BASE=http://127.0.0.1:8765/` and optional `LIB_DIR` (folder holding `npm pack` output of
maplibre-gl@4.7.1 and chart.js@4.4.4), because unpkg/jsdelivr/openfreemap are refused by this container's proxy. The test
serves the pinned CDN files from the local npm packs, blocks the basemap (fallback path), and checks: no page/console errors
(besides the expected 404s for missing data files), no horizontal scroll at 1366px and 375px, county search -> field picker ->
field clock, threshold switch (40 -> 29 years on mock), priority slider re-orders cards, a real map click on a field dot opens
its clock, community slider changes the sentence, GRACE chart + map render, validation tables + sources render.
Result on 2026-11-14 (mock data): all checks pass at both widths, 0 errors.
Result on 2026-11-15 after the fix pass (real web/data, commit after a2dce47): all checks pass at both widths, MOCK banner
hidden, 0 page/console errors (the one "Failed to load resource" is the blocked basemap style). Overflow was also checked
with `body{overflow-x}` temporarily set to visible: scrollWidth == innerWidth at 375px on home, field, county, GRACE and data views.

## Caveats / not done
- The positron basemap could not be tested here (host blocked by the proxy); only the fallback style was exercised.
- Map dots are not keyboard-focusable; keyboard users reach every field through county search/select + the "Pick a well" list.
- No dark mode (light colour scheme declared).
